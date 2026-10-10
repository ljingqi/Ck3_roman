# -*- coding: utf-8 -*-
"""临时取证：熔件顶层结构与「信仰→宗教」键的取法（第1问 chaplain 支线）。"""
import json
import os
import sys

ROOT = r"D:\Roman"
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

DATA = os.path.join(ROOT, "output", "田所2", "data")
MELT = "melt_955_01_01.json"
FID = 9


def main():
    print("载入…", flush=True)
    melt = cl.load_melt(os.path.join(DATA, MELT))
    print("顶层键:", sorted(melt.keys()))
    for k in ("religion", "religions", "faiths", "rites"):
        v = melt.get(k)
        if isinstance(v, dict):
            print("%-10s dict keys=%s" % (k, list(v.keys())[:8]))
            if k in ("religion", "religions"):
                for kk, vv in list(v.items())[:3]:
                    print("   ", kk, type(vv).__name__,
                          (list(vv.keys())[:8] if isinstance(vv, dict) else str(vv)[:80]))
        elif isinstance(v, list):
            print("%-10s list len=%d sample=%s" % (k, len(v), str(v[:2])[:200]))
        else:
            print("%-10s %s %s" % (k, type(v).__name__, str(v)[:120]))
    fe = cl.faith_entry(melt, FID)
    print("faith_entry(%d) keys=%s" % (FID, sorted(fe.keys())))
    print("  religion field:", fe.get("religion"), " faith_type:", fe.get("faith_type"),
          " name:", fe.get("name"))
    rid = fe.get("religion")
    if isinstance(rid, int):
        for path in (("religion", "religions"), ("religions",), ("religion",)):
            cur = melt
            for p in path:
                cur = (cur or {}).get(p) if isinstance(cur, dict) else None
            got = (cur or {}).get(str(rid)) if isinstance(cur, dict) else None
            print("  %s[%d] -> %s" % (".".join(path), rid,
                                      json.dumps(got, ensure_ascii=False)[:200]
                                      if got else got))


if __name__ == "__main__":
    main()
