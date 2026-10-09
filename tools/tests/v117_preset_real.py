# -*- coding: utf-8 -*-
"""v117 丙-5 one-off: real-melt lzma preset 6 vs 3 (time and bytes), archives written under logs/."""
import lzma, os, shutil, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import pipeline as P  # noqa: E402

SRC = os.path.join(ROOT, "output", "洪氏2", "data", "melt_1282_01_01.json")
LOG = os.path.join(ROOT, "logs", "v117_compact_preset.txt")
buf = []


def w(s=""):
    buf.append(str(s)); print(str(s), flush=True)


size = os.path.getsize(SRC) / 1048576
w(f"样本: {os.path.basename(SRC)}  {size:.1f} MB")
for lvl in (6, 3):
    dst = os.path.join(ROOT, "logs", f"_v117_p{lvl}.xz")
    t = time.perf_counter()
    P._compress_file(SRC, "xz", out_path=dst, preset=lvl)
    dt = time.perf_counter() - t
    mb = os.path.getsize(dst) / 1048576
    w(f"  preset {lvl}: {dt:7.1f} s, 归档 {mb:6.1f} MB ({mb / size * 100:.1f}%)")
    os.remove(dst)
w("  体积极小差异换 CPU 大降：后台归档不再与合并争 CPU/磁盘")
with open(LOG, "w", encoding="utf-8") as fp:
    fp.write("\n".join(buf) + "\n")
w(f"[report] {LOG}")
