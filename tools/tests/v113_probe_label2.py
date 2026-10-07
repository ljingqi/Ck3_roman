# -*- coding: utf-8 -*-
"""v113 probe #2 (one melt load): the exact date that turns `邓公主李星雁` into `唐公主`, and
the node volume of a descendant-closure family tree for the HTML page.

Run:  $env:PYTHONIOENCODING='utf-8'; python -X utf8 tools/tests/v113_probe_label2.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
PID = 207044
MELT = "melt_1155_01_01.json"
STAR = 16797282      # 李星雁, born 874, daughter of 李漼
LICUI = 14008        # 李漼, 唐皇帝
LICUI_FATHER = 11504
H_CHINA = 14022
DATES = ["849.1.1", "859.9.13", "867.1.1", "874.4.6", "879.1.1", "879.1.2", "879.1.3",
         "885.3.2", "886.1.1", "890.4.21", "897.6.5", "904.11.30", "952.1.29",
         "1126.7.30", "1152.11.13"]


def main():
    with open(os.path.join(DATA, f"player_{PID}.json"), encoding="utf-8") as f:
        cache = json.load(f)
    names = os.path.join(DATA, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    print("载入熔件", MELT, flush=True)
    melt = cl.load_melt(os.path.join(DATA, MELT))
    facts = F.build_facts(cache, melt, names, as_of=None, decade=None, campaign=None)
    f = facts["_facts"]
    print("as_of =", f.as_of)
    print("melt top keys:", sorted(melt)[:40])
    print("_TT_RANK:", {k: v for k, v in f._TT_RANK.items() if k[:1] in "hkedc"})
    print("_RANK_TIER:", f._RANK_TIER)

    print("\n=== 李星雁 %d ===" % STAR)
    rec = (cache.get("characters") or {}).get(str(STAR)) or {}
    print("  birth", rec.get("birth"), "death", (rec.get("death") or {}).get("date"))
    print("  family:", json.dumps(rec.get("family") or {}, ensure_ascii=False)[:300])
    print("  in cache:", bool(rec), "| in melt:", bool((f._chars or {}).get(str(STAR))))
    for d in DATES:
        print(f"   {d}: {f.kin_label(STAR, d)!r}")
    print("  parents:", f._parents_of_cid(STAR))
    for p in f._parents_of_cid(STAR):
        print(f"   parent {p} ({f.name_or(p)})")
        for d in ("874.4.6", "879.1.1", "879.1.2", "885.3.2", "904.11.30", "1152.11.13"):
            print(f"     [{d}] _style_parent_title={f._style_parent_title(p, d)} "
                  f"primary={f._primary_title_at(p, as_of=d)} "
                  f"former={f._former_high_title(p, d)}")

    print("\n=== 李漼 %d ===" % LICUI)
    print("  _hold_intervals:", json.dumps(f._hold_intervals(LICUI), ensure_ascii=False)[:600])
    for d in ("867.1.1", "879.1.1", "879.1.2", "885.3.2", "1152.11.13"):
        print(f"   [{d}] primary={f._primary_title_at(LICUI, as_of=d)} "
              f"former={f._former_high_title(LICUI, d)} "
              f"former_text={f._former_title_text(LICUI, f._former_high_title(LICUI, d), d)!r} "
              f"label={f.kin_label(LICUI, d)!r}")
    print("  father %d hold_intervals:" % LICUI_FATHER,
          json.dumps(f._hold_intervals(LICUI_FATHER), ensure_ascii=False)[:400])

    print("\n=== h_china 分段 ===")
    t = f._lt.get(str(H_CHINA)) or {}
    print("  history_government:", json.dumps(t.get("history_government"), ensure_ascii=False)[:400])
    print("  title_name_data:", json.dumps(t.get("title_name_data"), ensure_ascii=False)[:2000])
    for d in DATES:
        print(f"   {d}: name={f._name_at_date(H_CHINA, d)!r} "
              f"src={f._name_source_key(H_CHINA, d)!r} gov={f._title_government(H_CHINA, d)!r} "
              f"hist_gov={f._title_government_hist(H_CHINA, d)!r}")
    print("  _title_seqs tail:",
          json.dumps(f._title_seqs.get(H_CHINA, [])[-14:], ensure_ascii=False))
    print("  _title_seqs len:", len(f._title_seqs.get(H_CHINA, [])))

    print("\n=== 直接模拟修法 (用李漼实际持有期的日期取名与政体) ===")
    for d in ("859.9.13", "867.1.1", "874.4.6", "879.1.2", "885.3.2"):
        try:
            print(f"   name_date={d}: {f._prince_style_from_title('hegemon', H_CHINA, d, STAR, LICUI)!r}")
        except Exception as e:                                # noqa: BLE001
            print(f"   name_date={d}: ERR {e}")
    for d in DATES:
        try:
            print(f"   as_of={d}: {f._prince_style_from_title('hegemon', H_CHINA, d, STAR, LICUI)!r}")
        except Exception as e:                                # noqa: BLE001
            print(f"   as_of={d}: ERR {e}")

    # ---- tree volume: descendant closure from the first chain member -------------
    print("\n=== 子孙闭包体量 ===")
    chain = [int(e["cid"]) for e in (cache.get("played_legacy") or [])
             if isinstance(e, dict) and isinstance(e.get("cid"), int)]
    chars = cache.get("characters") or {}

    def kids_of(cid, date=None):
        r = chars.get(str(cid)) or {}
        return [int(x) for x in ((r.get("family") or {}).get("child") or [])
                if isinstance(x, int)]

    seen, order = set(), []
    stack = [chain[0]] if chain else []
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        order.append(cid)
        for k in kids_of(cid):
            if k not in seen:
                stack.append(k)
    print("  descendant closure size:", len(seen))
    branchy = sum(1 for cid in seen if kids_of(cid))
    print("  nodes with >=1 child:", branchy)
    depth = {}
    for cid in order:
        r = chars.get(str(cid)) or {}
        fam = (r.get("family") or {})
        ps = [int(x) for x in (fam.get("father") or []) + (fam.get("mother") or [])
              if isinstance(x, int)]
        depth[cid] = 1 + max((depth.get(p, 0) for p in ps), default=0)
    from collections import Counter
    print("  depth histogram:", sorted(Counter(depth.values()).items()))
    noname = [cid for cid in seen if not f.name_or(cid)]
    print("  nodes without a name:", len(noname), noname[:5])
    # how many of the closure are in the cache vs melt only
    in_cache = sum(1 for cid in seen if str(cid) in chars)
    print(f"  in cache record: {in_cache}/{len(seen)}")


if __name__ == "__main__":
    main()
