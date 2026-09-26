# -*- coding: utf-8 -*-
"""用 git HEAD 版源码跑任意**只读探针** (对照用), 用完原样恢复工作树。

与 `tools/snap_at_head.py` 同源 (那份是专给 snap.py 用的), 这份服务一切
`tools\\verify_*.py` / `tools\\tmp_probe_*.py`: 先把工作树的 7 个生产源文件备份到
`cache/_head_restore`, 再用 `git show HEAD:<file>` 覆盖它们, 跑探针, 最后无论成败
都把备份恢复回去 (含未提交改动)。

用法:
    & tools\\py.ps1 tools\\at_head.py tools\\verify_v68_title_name.py head
    & tools\\py.ps1 tools\\at_head.py --ref=64a6216 tools\\snap.py 菲利普2 38665 final --name=base

`--ref=<git 版本>` 指定对照版本 (缺省 HEAD)。注意: 本轮改动一旦提交, HEAD 就等于
改动后 —— 要对照「改动前」必须显式给改动前的提交 (如 checkpoint 提交)。
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
    args = sys.argv[1:]
    ref = "HEAD"
    for a in list(args):
        if a.startswith("--ref="):
            ref = a.split("=", 1)[1]
            args.remove(a)
    if not args:
        print(__doc__)
        return 2
    script, rest = args[0], args[1:]
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
        _n = 0
        for fn in _CODE:
            r = git("show", "%s:%s" % (ref, fn))
            if r.returncode != 0:
                print("  !! git show %s:%s 失败, 该文件保持工作树版本" % (ref, fn))
                continue
            with open(os.path.join(ROOT, fn), "w", encoding="utf-8",
                      newline="") as fp:
                fp.write(r.stdout)
            _n += 1
        print("已用 %s 版源码覆盖工作树 (%d/%d 个文件), 开始跑 %s …"
              % (ref, _n, len(_CODE), script))
        rc = subprocess.call([sys.executable, os.path.join(ROOT, script)] + rest,
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
