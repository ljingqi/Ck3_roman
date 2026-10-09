# -*- coding: utf-8 -*-
"""v117 check (item 3 / 丙-5): archiving scope and lzma preset.

Runs against a throwaway tree under logs/, so no real melt is touched. Asserts that a background pass
(`scope="current"`) only looks at the newest campaign's newest melts while a manual pass keeps the full
sweep, that preset 3 writes a valid archive with an exact round trip, and measures preset 3 vs 6.

Usage: & tools\\py.ps1 tools\\tests\\v117_check_compact_scope.py
"""
import hashlib
import lzma
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import pipeline as P         # noqa: E402

LOG = os.path.join(ROOT, "logs", "v117_check_compact_scope.txt")
TMP = os.path.join(ROOT, "logs", "_v117_compact")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def build_tree():
    """Three campaigns with four melts each; the newest date sits in 洪氏2, followed by two newer
    melts in 教宗尼各老, so "the campaign of the newest melt" is unambiguous."""
    shutil.rmtree(TMP, ignore_errors=True)
    dates = {"洪氏": ["1200_01_01", "1210_01_01", "1220_01_01", "1230_01_01"],
             "教宗尼各老": ["1240_01_01", "1250_01_01", "1260_01_01", "1270_01_01"],
             "洪氏2": ["1245_01_01", "1255_01_01", "1265_01_01", "1283_09_11"]}
    for folder, ds in dates.items():
        d = os.path.join(TMP, folder, "data")
        os.makedirs(d)
        for date in ds:
            with open(os.path.join(d, f"melt_{date}.json"), "w", encoding="utf-8") as fp:
                fp.write('{"x": 1}')


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    build_tree()
    cfg = {"output_dir": TMP, "data_dir": "", "cache_dir": ""}
    melts = P._iter_melts(cfg)
    w(f"假战役树: {len(melts)} 份熔件, 最新 = {os.path.basename(melts[-1][1])} "
      f"({melts[-1][0]})")

    # [A] background scope: the newest campaign only, newest `_COMPACT_BG_MELTS` melts
    cur = P._compact_scope(melts, "current")
    names = [os.path.basename(p) for _f, p, _d in cur]
    w(f"[A] scope=current: {len(cur)} 份 = {names}")
    ok_a = (len(cur) == P._COMPACT_BG_MELTS
            and all(f == "洪氏2" for f, _p, _d in cur)
            and names[-1] == "melt_1283_09_11.json")

    # [B] manual scope: unchanged full sweep
    allm = P._compact_scope(melts, "all")
    w(f"[B] scope=all: {len(allm)} 份 (共 {len(melts)})")
    ok_b = len(allm) == len(melts) == 12

    # [C] preset 3 archives with an exact round trip and drops the source
    src = os.path.join(TMP, "洪氏2", "data", "melt_1245_01_01.json")
    with open(src, "w", encoding="utf-8") as fp:
        fp.write("[" + ",".join(f'{{"i": {i}, "t": "洪光通第{i}次圣战"}}' for i in range(20000)) + "]")
    before_sha = sha1(src)
    out = P._compress_file(src, "xz", preset=3)
    with lzma.open(out, "rb") as fp:
        got = hashlib.sha1(fp.read()).hexdigest()
    w(f"[C] preset 3: {os.path.basename(out)} "
      f"{os.path.getsize(src) / 1048576:.2f} → {os.path.getsize(out) / 1048576:.2f} MiB, "
      f"往返一致={got == before_sha}, 源文件仍在={os.path.isfile(src)}")
    ok_c = got == before_sha and os.path.isfile(src) and out.endswith(".xz")

    # [D] preset 3 vs 6 on a compressible 24 MiB payload: time and size
    payload = os.path.join(TMP, "payload.json")
    with open(payload, "w", encoding="utf-8") as fp:
        for i in range(120000):
            fp.write(f'{{"id": {i}, "name": "洪光通", "title": "天皇帝", "year": {1200 + i % 90}}}\n')
    size_mb = os.path.getsize(payload) / 1048576
    rows = {}
    for lvl in (6, 3):
        dst = payload + f".{lvl}.xz"
        t = time.perf_counter()
        with open(payload, "rb") as fi, lzma.open(dst, "wb", preset=lvl) as fo:
            shutil.copyfileobj(fi, fo, 8 << 20)
        rows[lvl] = (time.perf_counter() - t, os.path.getsize(dst) / 1048576)
    w(f"[D] 同一份 {size_mb:.1f} MiB 明文:")
    for lvl in (6, 3):
        w(f"      preset {lvl}: {rows[lvl][0]:6.2f} s, {rows[lvl][1]:6.2f} MiB")
    w(f"      preset 3 提速 {rows[6][0] / rows[3][0]:.1f}×, 体积 +{(rows[3][1] / rows[6][1] - 1) * 100:.1f}%")
    ok_d = rows[3][0] < rows[6][0]

    # [E] config override is honoured (compact_lzma_preset)
    src2 = os.path.join(TMP, "洪氏", "data", "melt_1230_01_01.json")
    with open(src2, "w", encoding="utf-8") as fp:
        fp.write("x" * 100000)
    o62 = P._compress_file(src2, "xz", preset=6)
    w(f"[E] preset 覆盖: 显式 preset=6 生成 {os.path.basename(o62)} "
      f"{os.path.getsize(o62) / 1024:.1f} KiB")
    ok_e = o62.endswith(".xz") and os.path.getsize(o62) > 0

    shutil.rmtree(TMP, ignore_errors=True)
    w("")
    for name, ok in (("[A] 后台只压本战役最新 3 份", ok_a),
                     ("[B] 手动 compact 全量不变", ok_b),
                     ("[C] preset 3 往返一致", ok_c),
                     ("[D] preset 3 明显更快", ok_d),
                     ("[E] preset 可覆盖", ok_e)):
        w(f"  {'PASS' if ok else 'FAIL'} {name}")
    ok = all((ok_a, ok_b, ok_c, ok_d, ok_e))
    w(f"\n[{'PASS' if ok else 'FAIL'}] v117 丙-5 compact scope check")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
