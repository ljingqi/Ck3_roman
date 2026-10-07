# -*- coding: utf-8 -*-
"""v116 probe (cache only, no melt): the vassal/government history behind the prince word.

User report: 世系写「山南王子洪审礼」，但天朝制下行政制头衔的官员子女不该有 王子/郡主
(游戏表 11_tgp_china_flavorization.txt:1268/1282 = 公子/公女 for a *vassal* kingdom,
:1374/1388 = 王子/郡主 for an *independent* one).

This probe prints, for the named characters, `char_vassal_history` / `char_government_history`
and the entries near the queried dates, so the independence input of `_prince_word` is visible
without loading a melt.

Usage: python -X utf8 tools/tests/v116_probe_vassal.py [name ...]
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

CACHE = os.path.join(ROOT, "output", "洪氏2", "data", "player_207044.json")

WANT_DEFAULT = ["审礼", "仁德", "洪因", "秀全", "天贵福", "缯·洪堡", "易卜拉欣"]


def main():
    wants = sys.argv[1:] or WANT_DEFAULT
    print("载入 %s …" % CACHE, flush=True)
    cache = json.load(io.open(CACHE, encoding="utf-8"))
    chars = cache.get("characters") or {}
    print("缓存人物 %d 名；char_vassal_history 覆盖 %d 名；char_government_history 覆盖 %d 名"
          % (len(chars), len(cache.get("char_vassal_history") or {}),
             len(cache.get("char_government_history") or {})))
    print("player_id=%s  playthrough=%s" % (cache.get("player_id"), cache.get("playthrough_id")))
    vh_all = cache.get("char_vassal_history") or {}
    gh_all = cache.get("char_government_history") or {}
    landed_all = cache.get("landed_titles") or {}
    print("landed_titles 条目 %d" % len(landed_all))
    hits = []
    for cid, rec in chars.items():
        nm = str(rec.get("name_full") or rec.get("name_zh") or rec.get("name") or "")
        if any(w and w in nm for w in wants):
            hits.append(cid)
    for cid in sorted(hits, key=lambda x: int(x)):
        rec = chars[cid]
        dd = (rec.get("death") or {}).get("date")
        print("\n==== cid=%s  %s  生=%s 卒=%s  女=%s"
              % (cid, rec.get("name_full") or rec.get("name_zh"),
                 rec.get("birth"), dd, rec.get("female")))
        print("     family father=%s mother=%s" % ((rec.get("family") or {}).get("father"),
                                                   (rec.get("family") or {}).get("mother")))
        print("     landed=%s" % json.dumps(rec.get("landed"), ensure_ascii=False)[:600])
        vh = vh_all.get(cid)
        print("     char_vassal_history=%s" % json.dumps(vh, ensure_ascii=False)[:900])
        gh = gh_all.get(cid)
        print("     char_government_history=%s" % json.dumps(gh, ensure_ascii=False)[:600])
        if vh and isinstance(vh, list):
            print("     逐条：")
            for h in vh:
                print("       %s liege=%s flags=%s"
                      % (h.get("date"), h.get("liege"), (h.get("flags") or [])))
    # how many cached characters carry a vassal history at all?
    n_liege = sum(1 for v in vh_all.values()
                  if isinstance(v, list) and any(x.get("liege") is not None for x in v
                                                 if isinstance(x, dict)))
    print("\n有「曾为封臣」记录的缓存人物 %d 名" % n_liege)
    return 0


if __name__ == "__main__":
    sys.exit(main())
