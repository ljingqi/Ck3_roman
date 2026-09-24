# Fix the "the publisher could not be verified" confirmation on this project's
# launchers (启动续传.bat / 启动监控.bat / 继续战役.bat / 新开战役.bat ...).
#
# Why the dialog appears: agent sandboxes on Windows (dsh 0.1.7 and later) stamp
# the workspace root with an INHERITABLE Low integrity label (S-1-16-4096), so
# every file inside - the launchers included - materializes Low, and the shell
# interposes its "Open File - Security Warning / the publisher could not be
# verified" confirmation before it launches a Low-integrity executable.
#
# What this script does: gives the root's top-level `.bat`/`.cmd`/`.exe` files an
# EXPLICIT INFORMATIONAL Medium label (S-1-16-8192, policy bits 0). An explicit
# label overrides the inherited one, so the file is Medium again and the shell
# launches it without a prompt. Policy bits 0 mean "recorded identity only": no
# mandatory restriction is attached, so a confined (Low) agent child keeps
# exactly the write authority its DACL grants over these files.
#
# Usage (the .bat wrapper self-elevates for you):
#   fix_bat_label.bat                 fix the root's launchers (default: this repo)
#   fix_bat_label.bat -Check          report only, change nothing
#   fix_bat_label.bat -Clear          remove the explicit label again
#   fix_bat_label.bat -Root D:\X      act on another project root
#
# If your agent build already carries the launcher exemption (dsh commit
# f6698853f3 and later), you do not need this script: opening one session in the
# project repairs the launchers automatically.

[CmdletBinding()]
param(
    [string]$Root = '',
    [switch]$Check,
    [switch]$Clear
)

$ErrorActionPreference = 'Stop'

# `$PSScriptRoot` is not populated inside the param block, so the default root is
# resolved here: the project directory that holds this tools\ folder.
if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Split-Path -Parent $PSScriptRoot
}
if ([string]::IsNullOrWhiteSpace($Root)) {
    throw 'could not resolve the project root; pass -Root <directory>'
}

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not $Check -and -not (Test-Admin)) {
    Write-Host 'Requesting one elevation prompt (writing an integrity label needs an elevated token)...'
    Start-Process -FilePath (Get-Process -Id $PID).Path `
        -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Root', "`"$Root`"" `
        -Verb RunAs
    exit
}

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class LauncherLabel {
    public const uint SE_FILE_OBJECT = 1;
    public const uint LABEL_SECURITY_INFORMATION = 0x00000010;
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string sddl, uint revision, out IntPtr sd, out uint size);
    [DllImport("advapi32.dll", SetLastError = true)]
    public static extern bool GetSecurityDescriptorSacl(IntPtr sd, out bool present, out IntPtr sacl, out bool defaulted);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern uint SetNamedSecurityInfoW(string name, uint type, uint info, IntPtr owner, IntPtr group, IntPtr dacl, IntPtr sacl);
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr LocalFree(IntPtr handle);
}
'@

# SDDL for exactly the informational label the fixed harness writes:
# mandatory-label ACE, no inheritance, policy 0 (no mandatory restriction), Medium.
$InformationalMediumSddl = 'S:(ML;;;;;S-1-16-8192)'

function Set-LauncherLabel {
    param([string]$Path, [IntPtr]$LabelSacl)
    return [LauncherLabel]::SetNamedSecurityInfoW(
        $Path, [LauncherLabel]::SE_FILE_OBJECT, [LauncherLabel]::LABEL_SECURITY_INFORMATION,
        [IntPtr]::Zero, [IntPtr]::Zero, [IntPtr]::Zero, $LabelSacl)
}

function Get-LauncherLabelState {
    param([string]$Path)
    $line = icacls $Path 2>$null | Select-String 'Mandatory Label'
    if (-not $line) { return 'unlabeled' }
    $text = $line.Line
    if ($text -match '\(I\)') { return 'inherited-low' }
    if ($text -match 'Medium') { return 'explicit-medium' }
    return 'explicit-other'
}

$launchers = @(Get-ChildItem -LiteralPath $Root -File -ErrorAction Stop |
    Where-Object { $_.Extension -match '^\.(bat|cmd|exe)$' } |
    Sort-Object Name)

Write-Host "Root: $Root"
if ($launchers.Count -eq 0) { Write-Host 'No top-level .bat/.cmd/.exe launcher found.'; exit 0 }

if ($Check) {
    foreach ($file in $launchers) {
        Write-Host ("{0,-28} {1}" -f $file.Name, (Get-LauncherLabelState $file.FullName))
    }
    exit 0
}

$labelSacl = [IntPtr]::Zero
$descriptor = [IntPtr]::Zero
if (-not $Clear) {
    $size = 0
    if (-not [LauncherLabel]::ConvertStringSecurityDescriptorToSecurityDescriptorW(
            $InformationalMediumSddl, 1, [ref]$descriptor, [ref]$size)) {
        throw "SDDL parse failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    $present = $false; $defaulted = $false
    if (-not [LauncherLabel]::GetSecurityDescriptorSacl($descriptor, [ref]$present, [ref]$labelSacl, [ref]$defaulted) -or -not $present) {
        throw 'the SDDL descriptor carries no label ACL'
    }
}

$failed = 0
try {
    foreach ($file in $launchers) {
        $before = Get-LauncherLabelState $file.FullName
        if (-not $Clear -and ($before -eq 'explicit-medium' -or $before -eq 'explicit-other')) {
            Write-Host ("{0,-28} kept ({1})" -f $file.Name, $before)
            continue
        }
        $result = Set-LauncherLabel $file.FullName $labelSacl
        $after = Get-LauncherLabelState $file.FullName
        if ($result -ne 0) {
            $failed++
            Write-Host ("{0,-28} FAILED (Win32 {1}); run from an elevated prompt" -f $file.Name, $result)
            continue
        }
        Write-Host ("{0,-28} {1} -> {2}" -f $file.Name, $before, $after)
    }
}
finally {
    if ($descriptor -ne [IntPtr]::Zero) { [void][LauncherLabel]::LocalFree($descriptor) }
}

if ($Clear) { Write-Host 'Explicit labels removed; the files inherit the workspace label again.' }
elseif ($failed -eq 0) { Write-Host 'Done. Double-click a launcher: the publisher confirmation is gone.' }

Write-Host ''
Write-Host 'Note: executables in subdirectories (for example tools\rakaly.exe) keep the'
Write-Host 'inherited Low label by design and still prompt; this script covers the root'
Write-Host 'launchers a user double-clicks.'
exit $failed
