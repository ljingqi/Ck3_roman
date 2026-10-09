# -*- coding: utf-8 -*-
"""v117 取证探针 · 第七段：熔件侧的死亡日期 + 「按熔件 dead_data.date 回退」这一版补丁的回归面。

S12  段级读 dead_unprunable：传主链 14 人的 dead_data.date / prune / was_playable，
     并与实跑缓存 characters[cid].death 的有无对照。
S13  只载 主缓存 + 熔件（campaign=None），把 _anchor_date / _gen_end_date 都改成按
     「缓存 characters.death → campaign.player_death/reign_end → 熔件 dead_data.date」取死亡日，
     打印 14 位传主 改前/改后 person_label。

用法：& tools\\py.ps1 tools\\tests\\v117_probe_gf7.py
输出追加 logs/v117_probe_gf.txt。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cache_lib as cl  # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
OUT = os.path.join(ROOT, "logs", "v117_probe_gf.txt")
PID = 17066495
AS_OF = "1283.9.11"
CHAIN = [(1, 38957), (2, 44503), (3, 67172818), (4, 16879059), (5, 16878235), (6, 135480),
         (7, 117484775), (7, 16945142), (8, 207044), (9, 33725392), (10, 16974237),
         (9, 226889), (10, 50565938), (12, 17066495)]
_buf = []


def P(*a):
    s = " ".join(str(x) for x in a)
    _buf.append(s)
    print(s, flush=True)


def flush():
    with open(OUT, "a", encoding="utf-8") as fp:
        fp.write("\n".join(_buf) + "\n")
    _buf.clear()


def main():
    melt_p = cl.melt_file_exists(os.path.join(DATA, "melt_1283_01_01.json"))
    P("\n" + "=" * 78)
    P("== [S12] 熔件 dead_unprunable 里的传主链死亡日 vs 实跑缓存 characters[].death ==")
    dead = cl.load_melt_section(melt_p, "dead_unprunable") or {}
    main_cache = cl.load_cache(os.path.join(DATA, f"player_{PID}.json"))
    chars = main_cache.get("characters") or {}
    for gen, cid in CHAIN:
        rec = dead.get(str(cid))
        if isinstance(rec, list):
            rec = rec[0] if rec else {}
        rec = rec if isinstance(rec, dict) else {}
        dd = rec.get("dead_data") if isinstance(rec.get("dead_data"), dict) else {}
        cache_dd = ((chars.get(str(cid)) or {}).get("death") or {}).get("date")
        P(f"[S12] 世{gen:<2} cid={cid:>10} 熔件 dead_data.date={dd.get('date')!r} "
          f"prune={dd.get('prune')!r} was_playable={rec.get('was_playable')!r} "
          f"| 实跑缓存 characters.death={cache_dd!r}")
    del dead, chars
    gc_collect = __import__("gc").collect
    gc_collect()

    import facts as F

    def death_date_melt(self, cid):
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        d = (rec.get("death") or {}).get("date") or ""
        if d:
            return d
        pv = self.campaign.get(int(cid)) if str(cid).isdigit() else None
        if isinstance(pv, dict) and pv.get("player_id") == int(cid):
            for key in ("player_death", "reign_end"):
                v = pv.get(key)
                if isinstance(v, dict) and v.get("date"):
                    return v["date"]
        c = self._chars.get(str(cid)) if str(cid).isdigit() else None
        if isinstance(c, dict):
            return ((c.get("dead_data") or {}).get("date")) or ""
        return ""

    P("\n== [S13] 只按熔件 dead_data.date 回退的补丁：改前 / 改后 ==")
    melt = cl.load_melt(melt_p)
    names = os.path.join(DATA, "names.json")
    if not os.path.isfile(names):
        names = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(main_cache, melt, names, as_of=AS_OF)
    F.Facts.death_date = death_date_melt

    def _anchor_new(self, cid, date=None):
        dd = self.death_date(cid)
        if not dd:
            return _orig_anchor(self, cid, date)
        if date:
            if cl.date_key(date) >= cl.date_key(dd):
                return F._day_before(dd)
            return date
        if not self.as_of or cl.date_key(dd) <= cl.date_key(self.as_of):
            return F._day_before(dd)
        return self.as_of

    _orig_anchor = F.Facts._anchor_date
    before_rows = []
    for gen, cid in CHAIN:
        end = death_date_melt(f, cid)
        before_rows.append((gen, cid, end, f.person_label(cid, end, "full") if end else ""))
    F.Facts._anchor_date = _anchor_new
    F._gen_end_date = lambda ff, c: ff.death_date(c) or ""
    P("[S13] 世  cid         终点日        改前                                改后                                变?")
    changed = 0
    for gen, cid, end, before in before_rows:
        if not end:
            P(f"[S13] {gen:<3} {cid:>10} （取不到终点日，跳过）")
            continue
        f._label_cache.clear()
        after = f.person_label(cid, end, "full")
        flag = "变化" if after != before else "—"
        changed += bool(after != before)
        P(f"[S13] {gen:<3} {cid:>10} {end:<13} {before!r:<36} {after!r:<36} {flag}")
    P(f"[S13] 结论：{len(before_rows)} 位传主里 {changed} 处变化（只按熔件回退、campaign=None）")
    flush()


def _gen_end_orig(f, cid):
    """改前口径：_gen_end_date（缓存 death → campaign player_death/reign_end）。"""
    rec = (f.cache.get("characters") or {}).get(str(cid)) or {}
    d = (rec.get("death") or {}).get("date") or ""
    if d:
        return d
    pv = (f.campaign or {}).get(int(cid)) if str(cid).isdigit() else None
    if isinstance(pv, dict):
        for key in ("reign_end", "player_death"):
            v = pv.get(key)
            if isinstance(v, dict) and v.get("date"):
                return v["date"]
    return ""


if __name__ == "__main__":
    main()
