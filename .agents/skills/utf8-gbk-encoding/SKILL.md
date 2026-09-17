---
name: utf8-gbk-encoding
description: Use whenever reading, writing, or editing text files in this project or session — choose UTF-8 for Python sources, JSON data files, logs, output artifacts, and CK3 save envelopes; choose GBK (ANSI/cp936) for .bat batch files and legacy ANSI text from Chinese Windows; specify the encoding explicitly on both the read and write sides (PowerShell 7 -Encoding UTF8 / -Encoding 936, Python encoding="utf-8" / encoding="gbk").
---

# UTF-8 与 GBK 编码使用规则（utf8-gbk-encoding）

本技能用于本项目（CK3 记忆素材库）及本会话中所有文本文件的读写。核心规则：**每个文件的编码由文件类型决定，读取与写入两侧都显式指定同一编码。**

## 一律使用 UTF-8 的对象

- Python 源文件（`.py`）：中文注释与字符串按 UTF-8 书写与读取。
- JSON 数据文件：`config.json`、缓存 `output/<家族>/data/player_*.json`、熔件 `melt_*.json`、`data/` 下临时熔件。
- 日志与产物：`logs/journal.log`、`logs/prompts.log`、`output/<家族>/` 下的 `.md` 传记与 `index.html`。
- CK3 存档（`.ck3`）信封头：`meta_player_name` 等字段按 UTF-8 解码（`read_save_envelope` 的做法）。
- rakaly 熔出的 JSON 输出。

Python 侧统一写法：读取用 `open(path, encoding="utf-8")`，写入用 `open(path, "w", encoding="utf-8")`；`json.dump(..., ensure_ascii=False)` 保留中文原文。

## 一律使用 GBK（ANSI/cp936）的对象

- `.bat` 批处理文件：`启动监控.bat`、`启动续传.bat`。cmd 默认代码页为 936，GBK 编码保证批处理中的中文菜单与提示正常显示；UTF-8 保存会出现乱码。
- 中文 Windows 下由旧工具、记事本「ANSI」保存产生的其他文本文件。

Python 侧读 GBK：`open(path, encoding="gbk")`（别名 `cp936`）。写入 `.bat` 时用 `encoding="gbk"` 保存。

## 读取与写入两侧都显式指定编码

- 读 GBK 文件（`.bat`）用 `Get-Content -Encoding 936`；在 pwsh 7 下**不要**用 `-Encoding Default`（见下方警告）。
- 读 UTF-8 文件显式加 `-Encoding UTF8`（pwsh 7 默认已是 UTF-8，但写明可免歧义）。
- read 工具按 UTF-8 读取；对 `.bat` 等 GBK 文件改用 pwsh `Get-Content -Encoding 936`。
- 每个新写入的文件在落盘时按上表选择编码并写明。

### ⚠️ pwsh 7 下 `-Encoding Default` 已不再是 GBK（实测 2026-09-11，pwsh 7.6.6）

PowerShell 5.1 的 `-Encoding Default` = 系统 ANSI（zh-CN 即 cp936），所以旧版下它恰好能读 GBK。
**pwsh 7 已改变语义**：`[System.Text.Encoding]::Default.CodePage` = `65001`，`-Encoding Default`
与不带 `-Encoding` 完全等价，都是 UTF-8：

| 读 `启动监控.bat`（GBK） | 结果 |
| --- | --- |
| `Get-Content -Encoding 936` | ✅ `title CK3 记忆素材库监控（新档）` |
| `Get-Content -Encoding Default` | ❌ `title CK3 �����زĿ��أ��µ���` |
| `Get-Content`（不带参数） | ❌ 同上 |

写入侧同样变了：`Set-Content -Encoding Default` 写出的是 UTF-8 字节（`e4 b8 ad e6 96 87…`），
**既不能读 GBK，也不能写 GBK**。要写 GBK 用 `-Encoding 936`，或让 Python 以
`encoding="gbk"` 落盘（项目 `.bat` 的实际做法）。

其他打开方式：`.NET [Text.Encoding]::GetEncoding(936)`；本机系统 ANSI 代码页经注册表
`HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage\ACP` 核实仍为 `936`。

## 判断方法（先来源，后试读）

1. 先看文件来源：本项目 Python 程序生成或读取的文件一律是 UTF-8；用户手工创建的 `.bat` 与旧工具产物按 GBK 处理。
2. UTF-8 解析失败即为 GBK 信号：read 工具报「invalid UTF-8 text」、`json.load` 抛 UnicodeDecodeError、PowerShell 按 UTF-8 读 GBK 文件出现中文乱码时，改按 GBK 读取。
3. 只用 read 工具或 Python 严格解码来「试读」判断编码：read 工具对 GBK 会**明确报错**（已复现），可靠；而 pwsh 的 `Get-Content -Encoding UTF8` 读 GBK **不报错**，会静默产出 `U+FFFD`（`�`），无法据此判断，还会掩盖问题。

## 工具链调用（开发/自动化的子进程编码）

文件编码之外，**子进程 stdout 的编码**是另一处独立坑，实测（2026-09-11）：

| 命令 | 结果 |
| --- | --- |
| `python -c "print('中文')"` | ❌ 乱码（Python 按 cp936 写出，pwsh/DSH 侧按 UTF-8 解码） |
| `$env:PYTHONIOENCODING='utf-8'; python …` | ✅ 正常 |
| `python -X utf8 …` | ✅ 正常 |
| `. <项目根>\tools\enc.ps1; python …` | ✅ 正常（生效的是 `PYTHONIOENCODING` / `PYTHONUTF8`；见下方注） |
| `cmd /c "chcp 65001 & python …"` | ❌ 仍乱码（chcp 只改控制台代码页，管道下 Python 用的是 locale 编码） |

结论：**换控制台（cmd）解决不了**——问题在小进程写出的编码，不在 shell。做法：

1. 开发侧跑 Python 一律用包装脚本：`& <项目根>\tools\py.ps1 <脚本> [参数]`；
   混合命令先点源 `. <项目根>\tools\enc.ps1`（两者只设环境变量，不改项目代码）。
2. 产品入口（`启动监控.bat`，chcp 936）**不要**设 `PYTHONIOENCODING`：那里 Python 输出
   GBK 才是与 cmd 控制台一致的正确行为。包装脚本只服务开发/自动化会话。
3. 输出仍建议一并落 UTF-8 报告文件（`Out-File -Encoding UTF8` 或脚本内 `open(..., "w",
   encoding="utf-8")`）：一次写入可反复 `read`，避免「跑一遍→乱码→再跑一遍」的往返。

> **注（pwsh 7.6.6 实测）**：`enc.ps1` 里真正承重的是 `PYTHONIOENCODING` / `PYTHONUTF8`
> 两项环境变量；`$OutputEncoding` 只影响向原生命令管道**传输**的编码，对「捕获 Python stdout」
> 这条路径已不再起作用，`[Console]::OutputEncoding` 在 pwsh 7 下默认就是 65001。两者保留无害。
> 根因仍然成立：pwsh 7.6.6 捕获下 `python -c` 的 `sys.stdout.encoding` 实测为 **`gbk`**
> （`locale.getpreferredencoding()` = `cp936`），故乱码照旧复现。

**配套的调用纪律**（同一教训的另一半）：`output/<家族>/data/melt_*.json` 有 100–125MB，
`cache_lib.load_melt()` 每次 1–3 分钟，迭代核对时不要反复整载 ——
用 `tools/snap.py` 载一次落成 facts 快照，再用 `tools/verify_fast.py` 秒级断言；
需要熔件的端到端断言（`experiments/verify_zhou.py`）只在里程碑跑一次。

## 对照表

| 文件 | 编码 | PowerShell 7 读取 | Python 打开参数 |
| --- | --- | --- | --- |
| Python 源码 / JSON 数据 / 日志 / output 产物 | UTF-8 | `Get-Content -Encoding UTF8` | `encoding="utf-8"` |
| CK3 存档信封头 | UTF-8 | — | `decode("utf-8", "replace")` |
| `.bat` 批处理 / ANSI 旧文本 | GBK (cp936) | `Get-Content -Encoding 936` | `encoding="gbk"` |
