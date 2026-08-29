# -*- coding: utf-8 -*-
"""研究: 处决方式 (献祭) 在存档中能否查到。只读。"""
import json
import re
import sys

sys.path.insert(0, r"D:\Roman")

CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"
MELT = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"

def main():
    cache = json.load(open(CACHE, encoding="utf-8"))
    rec = (cache.get("characters") or {}).get(str(cache.get("player_id"))) or {}
    kills = list(rec.get("kills") or [])
    chars = cache.get("characters") or {}
    print("== 受害者 death 记录完整字段 ==")
    for cid in kills[:4]:
        d = (chars.get(str(cid)) or {}).get("death") or {}
        print(cid, (chars.get(str(cid)) or {}).get("name_zh"),
              json.dumps(d, ensure_ascii=False)[:220])
    print()
    print("== 原始熔件文本搜 blot/sacrific ==")
    with open(MELT, "r", encoding="utf-8") as fp:
        chunk = fp.read(256 * 1024 * 1024)
    for pat in ("blot", "sacrific", "execution_blot"):
        idxs = [m.start() for m in re.finditer(pat, chunk)]
        print("  %s: %d 处" % (pat, len(idxs)))
        for i in idxs[:3]:
            print("     ...", chunk[max(0, i - 80):i + 60].replace('"', " ")[:140])
    # 死因分布里有没有 blot/献祭
    t = None
    import localization as L
    t = L.table()
    from collections import Counter
    reasons = Counter()
    for cid in kills:
        d = (chars.get(str(cid)) or {}).get("death") or {}
        reasons[d.get("reason")] += 1
    print("== 全部击杀死因 ==")
    for r, n in reasons.most_common():
        print("  %-32s x%d %s" % (r, n, (t.get(r) or "")[:30]))

if __name__ == "__main__":
    main()
