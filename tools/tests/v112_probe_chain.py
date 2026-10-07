# -*- coding: utf-8 -*-
"""v112 只读探针：把一份缓存里的玩家传承链（played_legacy）逐代摊开。

每代打印：cid、姓名、生卒、与上一代的亲属词（facts.kin_word 的口径无法在此复现，
只用父母 id 与上一代比对，给出「儿子/女儿/本人同辈」的最粗判断）。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_chain.py [缓存文件]
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(ROOT, "output", "洪氏2", "data", "player_207044.json")
    with io.open(path, encoding="utf-8") as fp:
        cache = json.load(fp)
    chars = cache.get("characters") or {}
    chain = cache.get("played_legacy") or []
    pid = cache.get("player_id")
    print("缓存 %s  player_id=%s  链 %d 代" % (os.path.basename(path), pid, len(chain)))
    prev = None
    for i, e in enumerate(chain):
        cid = e.get("cid")
        rec = chars.get(str(cid)) or {}
        fam = rec.get("family") or {}
        d = rec.get("death") or {}
        parents = [int(x) for x in (fam.get("father") or []) + (fam.get("mother") or [])]
        rel = ""
        if prev is not None:
            pfam = (chars.get(str(prev)) or {}).get("family") or {}
            pchild = {int(x) for x in (pfam.get("child") or [])}
            psib = {int(x) for x in (pfam.get("siblings") or [])}
            if int(cid) in pchild:
                rel = "上一代之子"
            elif int(cid) in psib:
                rel = "上一代之兄弟姊妹"
            elif prev in parents:
                rel = "上一代之父/母"
            else:
                rel = "（非直系）"
        print("%2d. %-10s %-14s 生%-12s 卒%-12s %-8s %s"
              % (i + 1, cid, rec.get("name_full") or rec.get("name_zh") or "?",
                 rec.get("birth") or "?", d.get("date") or "（在世）",
                 "(在链中)" if cid == pid else "", rel))
        prev = cid
    return 0


if __name__ == "__main__":
    sys.exit(main())
