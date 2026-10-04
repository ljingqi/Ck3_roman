# -*- coding: utf-8 -*-
"""Assertions for the three defects reported on `output/洪氏2` (offline, no melt load).

[A] Display names -- `tools/tests/fixtures/v102_cultures.json` (the melt's culture_manager,
    streamed out by mk_v102_cultures.py) stands in for the melt, so the cache alone is
    enough to compute every display name in the family:
      缯·洪堡 / 洪审礼 / 洪慈顺 / 洪端仁 / 洪端正 / 鸣鹤·洪 / 景思·洪 / 禅心·洪 /
      洪仁德 / 耀国·洪堡 / 桑莎·洪堡
[B] Kinship row -- the snapshot's profile block carries the program-counted family sizes
    (the father's children, the number of mothers, the protagonist's birth rank).
[C] Plague block -- the snapshot facts hold no `plagues` key and the shared prefix no
    【瘟疫】 section.

Usage:
    & tools\\py.ps1 tools\\tests\\verify_v102.py [snapshot]
    The snapshot defaults to output/洪氏2/data/snap_v102.json; when absent, [B][C] report
    SKIP instead of failing.
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

CACHE = os.path.join(ROOT, "output", "洪氏2", "data", "player_16878235.json")
FIXTURE = os.path.join(ROOT, "tools", "tests", "fixtures", "v102_cultures.json")
SNAP_DEFAULT = os.path.join(ROOT, "output", "洪氏2", "data", "snap_v102.json")
AS_OF = "1009.1.1"

# pid -> (label, expected display name)
NAMES = [
    (16878235, "缯（传主）", "缯·洪堡"),
    (16879059, "审礼（前任传主）", "洪审礼"),
    (33626364, "慈顺", "洪慈顺"),
    (50409116, "端仁", "洪端仁"),
    (100719214, "端正", "洪端正"),
    (50417794, "鸣鹤", "鸣鹤·洪"),
    (67133946, "景思", "景思·洪"),
    (67190270, "禅心", "禅心·洪"),
    (84824, "仁德（父）", "洪仁德"),
    (135480, "耀国（子）", "耀国·洪堡"),
    (16895643, "桑莎（女）", "桑莎·洪堡"),
]

FAILS = []


def check(tag, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + tag + (("  " + detail) if detail else ""))
    if not ok:
        FAILS.append(tag)


def part_a():
    print("[A] display names (cache + culture fixture, same culture table as the melt)")
    if not os.path.exists(FIXTURE):
        check("fixture present", False, FIXTURE + " missing; run mk_v102_cultures.py")
        return
    fixture = json.load(io.open(FIXTURE, encoding="utf-8"))
    cache = json.load(io.open(CACHE, encoding="utf-8"))
    for pid, label, want in NAMES:
        got = cl.display_name(cache, pid, melt=fixture, chars={}, date=AS_OF)
        check(f"{label} ({pid}) = {want}", got == want,
              "" if got == want else f"got {got!r}")


def _walk_strings(obj, out):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_strings(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_strings(v, out)


def part_bc(snap_path):
    if not os.path.exists(snap_path):
        print(f"[B][C] SKIP no snapshot at {snap_path} (drop one with snap.py to enable)")
        return
    snap = json.load(io.open(snap_path, encoding="utf-8"))
    texts = []
    _walk_strings(snap.get("blocks") or {}, texts)
    joined = "\n".join(texts)
    print(f"[B] kinship row (blocks of {os.path.basename(snap_path)})")
    check("father's child count in the material", "共八个子女" in joined)
    check("number of mothers in the material", "分属三位母亲" in joined)
    check("protagonist's birth rank in the material", "行四" in joined)
    check("sibling count in the material", "兄弟姊妹七人" in joined)
    print("[C] plague block")
    check("no plagues key in facts", "plagues" not in (snap.get("facts") or {}))
    check("no 【瘟疫】 in the shared prefix", "【瘟疫】" not in (snap.get("shared") or ""))


def main():
    snap_path = sys.argv[1] if len(sys.argv) > 1 else SNAP_DEFAULT
    part_a()
    part_bc(snap_path)
    print(f"\nv102: {'all passed' if not FAILS else '%d failed: %s' % (len(FAILS), FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
