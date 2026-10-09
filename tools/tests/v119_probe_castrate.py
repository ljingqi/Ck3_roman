# -*- coding: utf-8 -*-
"""v119 probe: who castrated whom in 1232 — the 洪希晏 / 朮赤 case behind the ambiguous 年表 line.

Reads the campaign's per-player cache only (no melt):
    python tools/tests/v119_probe_castrate.py [家族文件夹]
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import llm  # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "洪氏2"
TORTURE = ("torturer_memory", "tortured_memory")
YEARS = ("1232", "1233")


def walk(obj, path=""):
    """Yield dicts that carry a torture type, anywhere in the cache."""
    if isinstance(obj, dict):
        if obj.get("type") in TORTURE:
            yield path, obj
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def main():
    cfg = llm.load_config()
    base = os.path.join(cfg["output_dir"], FOLDER)
    pid = None
    for fn in sorted(os.listdir(base)):
        if fn.startswith("洪希晏") and "_终传_" in fn:
            head = open(os.path.join(base, fn), encoding="utf-8").read(400)
            m = re.search(r"人物ID:\s*(\d+)", head)
            pid = int(m.group(1)) if m else None
            print("终传:", fn, "人物ID:", pid)
    path = os.path.join(base, "data", f"player_{pid}.json")
    print("cache:", os.path.basename(path), f"{os.path.getsize(path) / 1e6:.1f}MB")
    cache = json.load(open(path, encoding="utf-8"))
    chars = cache.get("characters") or {}

    def nm(cid):
        ch = chars.get(str(cid)) or {}
        return f"{ch.get('name') or '?'}({cid})" if cid is not None else "None"

    print("顶层键:", sorted(cache.keys()))
    n = 0
    for p, ev in walk(cache):
        d = str(ev.get("date") or "")
        if d[:4] not in YEARS:
            continue
        ident = ev.get("ident") or {}
        parts = ident.get("parts") or {}
        if not (ident.get("torture_kind") or ev.get("type") in TORTURE):
            continue
        print(f"  {d} type={ev.get('type'):17} owner={nm(ident.get('owner'))} "
              f"victim={nm(parts.get('victim'))} kind={ident.get('torture_kind')} @{p}")
        n += 1
    print(f"{'/'.join(YEARS)} 刑虐事件 {n} 条")

    for cid in sorted(chars):
        ch = chars[cid]
        tr = [t for t in (ch.get("traits") or [])
              if "castrat" in str(t).lower() or "eunuch" in str(t).lower()]
        if tr:
            print(f"  阉割类特质: {nm(int(cid))} {tr}")


if __name__ == "__main__":
    main()
