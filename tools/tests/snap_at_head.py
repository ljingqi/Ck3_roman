# -*- coding: utf-8 -*-
"""用 git HEAD 版源码落一份快照 (对照用)，用完恢复工作树。

用途：验证「本轮改动是否改变了事实面」——把 HEAD（改动前）的 facts/biography/
style/cache_lib/localization/llm/flavorization 取到临时目录，临时替换工作树文件，
跑 tools/tests/snap.py 落一份快照，再原样恢复工作树（含未提交改动）。

用法：
    & tools\\py.ps1 tools\\tests\\snap_at_head.py <家族> <玩家id> <as_of> [十年] [输出名]
    输出落在 output/<家族>/data/<输出名>.json（默认 snap_head_<as_of>.json）
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CODE = ("facts.py", "biography.py", "cache_lib.py", "localization.py",
         "llm.py", "style.py", "flavorization.py")


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT,
                          capture_output=True, text=True)


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if len(argv) < 3:
        print(__doc__)
        return 2
    folder, pid, as_of = argv[0], argv[1], argv[2]
    decade = argv[3] if len(argv) > 3 else None
    # v80: --name= 优先于位置参数与默认名 (旧稿忽略 --name=, 结果落成默认名)
    _nf = next((a for a in flags if a.startswith("--name=")), "")
    out_name = (_nf.split("=", 1)[1] if _nf
                else (argv[4] if len(argv) > 4
                      else f"snap_head_{as_of.replace('.', '_')}"))
    data = os.path.join(ROOT, "output", folder, "data")

    # 1) 备份工作树当前版本
    tmp = os.path.join(ROOT, "cache", "_head_restore")
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    for fn in _CODE:
        p = os.path.join(ROOT, fn)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(tmp, fn))
    print(f"已备份工作树 {len(_CODE)} 个源文件 → {tmp}")

    # 2) 用 HEAD 版覆盖
    try:
        for fn in _CODE:
            r = git("show", f"HEAD:{fn}")
            if r.returncode != 0:
                continue
            with open(os.path.join(ROOT, fn), "w", encoding="utf-8",
                      newline="") as fp:
                fp.write(r.stdout)
        print("已用 HEAD 版源码覆盖工作树，开始落快照 …")
        # v80: snap.py 已在 v77 迁到 tools/tests/; 其余 --x=y 参数原样转发
        # (尤其 --melt=<文件名> —— 默认取末档熔件, 与「该篇生成时用的那一份」常不同)
        cmd = [sys.executable, os.path.join(ROOT, "tools", "tests", "snap.py"),
               folder, pid, as_of, "--name=" + out_name]
        if decade:
            cmd.append(decade)
        cmd += [a for a in flags if not a.startswith("--name=")]
        rc = subprocess.call(cmd, cwd=ROOT)
    finally:
        # 3) 无论如何恢复工作树
        for fn in _CODE:
            src = os.path.join(tmp, fn)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(ROOT, fn))
        shutil.rmtree(tmp, ignore_errors=True)
        print("已恢复工作树（含未提交改动）")
    return rc if rc == 0 else rc


if __name__ == "__main__":
    sys.exit(main())
