# -*- coding: utf-8 -*-
"""v112 收尾批量：按冻结后的代码重建两份快照并重生成两篇终传（顺序执行，逐条打印）。

用法（后台跑，输出重定向到日志）：
    & tools\\py.ps1 tools\\tests\\v112_e2e.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = sys.executable
STEPS = [
    ["tools/tests/snap.py", "洪氏2", "207044", "final",
     "--name=snap_v112_207044_final"],
    ["tools/tests/snap.py", "洪氏2", "135480", "final",
     "--name=snap_v112_135480_final", "--melt=melt_1075_01_01.json.xz"],
    ["pipeline.py", "bio", "207044"],
    ["pipeline.py", "bio", "16945142"],
    ["tools/tests/verify_fast.py",
     "output/洪氏2/data/snap_v112_207044_final.json"],
    ["tools/tests/verify_v112.py"],
    ["tools/tests/verify_fast.py",
     "output/洪氏2/data/snap_v112_135480_final.json"],
]


def main():
    for i, args in enumerate(STEPS, 1):
        cmd = [PY, "-X", "utf8"] + args
        print("\n===== [%d/%d] %s =====" % (i, len(STEPS), " ".join(args)), flush=True)
        rc = subprocess.call(cmd, cwd=ROOT)
        print("----- exit %d -----" % rc, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
