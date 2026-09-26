# -*- coding: utf-8 -*-
"""用 git HEAD 版源码跑任意**只读探针** (对照用), 用完原样恢复工作树。

与 `tools/snap_at_head.py` 同源 (那份是专给 snap.py 用的), 这份服务一切
`tools\\verify_*.py` / `tools\\tmp_probe_*.py`: 先把工作树的 7 个生产源文件备份到
`cache/_head_restore`, 再用 `git show HEAD:<file>` 覆盖它们, 跑探针, 最后无论成败
都把备份恢复回去 (含未提交改动)。

用法:
    & tools\\py.ps1 tools\\at_head.py tools\\verify_v68_title_name.py head
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CODE = ("facts.py", "biography.py", "cache_lib.py", "localization.py",
         "llm.py", "style.py", "flavorization.py")


def git(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT,
                          capture_output=True, text=True)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    script, args = sys.argv[1], sys.argv[2:]
    if not os.path.isfile(os.path.join(ROOT, script)):
        print("找不到探针脚本: %s" % script)
        return 2

    tmp = os.path.join(ROOT, "cache", "_head_restore")
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    for fn in _CODE:
        p = os.path.join(ROOT, fn)
        if os.path.isfile(p):
            shutil.copy2(p, os.path.join(tmp, fn))
    print("已备份工作树源码 → %s" % tmp)

    rc = 1
    try:
        for fn in _CODE:
            r = git("show", "HEAD:%s" % fn)
            if r.returncode != 0:
                continue
            with open(os.path.join(ROOT, fn), "w", encoding="utf-8",
                      newline="") as fp:
                fp.write(r.stdout)
        print("已用 HEAD 版源码覆盖工作树, 开始跑 %s …" % script)
        rc = subprocess.call([sys.executable, os.path.join(ROOT, script)] + args,
                             cwd=ROOT)
    finally:
        for fn in _CODE:
            src = os.path.join(tmp, fn)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(ROOT, fn))
        shutil.rmtree(tmp, ignore_errors=True)
        print("已恢复工作树 (含未提交改动)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
