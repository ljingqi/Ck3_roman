# -*- coding: utf-8 -*-
"""v117 取证探针 · 第二段：实跑用的是哪一档熔件 + 每一步真实返回值。

用法：
  & tools\\py.ps1 tools\\tests\\v117_probe_gf2.py cacheinfo
  & tools\\py.ps1 tools\\tests\\v117_probe_gf2.py melt --melt=1285
  & tools\\py.ps1 tools\\tests\\v117_probe_gf2.py melt --melt=1283

输出追加写 logs/v117_probe_gf.txt（UTF-8）。
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cache_lib as cl  # noqa: E402

FOLDER = "洪氏2"
DATA = os.path.join(ROOT, "output", FOLDER, "data")
OUT = os.path.join(ROOT, "logs", "v117_probe_gf.txt")

PID = 17066495
CID = 44503            # 洪天贵福
CID_XQ = 38957         # 洪秀全
AS_OF = "1283.9.11"
WATCH = ("13265", "15771", "15769", "15766", "14022", "14032", "18232", "14769", "15446", "15310")

_buf = []


def P(*a):
    s = " ".join(str(x) for x in a)
    _buf.append(s)
    print(s, flush=True)


def flush():
    with open(OUT, "a", encoding="utf-8") as fp:
        fp.write("\n".join(_buf) + "\n")


def cache_path(pid):
    return os.path.join(DATA, f"player_{pid}.json")


def cache_summary(tag, pid):
    p = cache_path(pid)
    if not os.path.isfile(p):
        P(f"[{tag}] 缺 {p}")
        return None
    c = cl.load_cache(p)
    ch = (c.get("characters") or {}).get(str(pid)) or {}
    P(f"[{tag}] player_{pid}.json  size={os.path.getsize(p)/1048576:.0f}MB "
      f"last_date={c.get('last_date')!r} playthrough_id={c.get('playthrough_id')!r} "
      f"output_folder={c.get('output_folder')!r}")
    P(f"[{tag}] sources[-4:] = {(c.get('sources') or [])[-4:]}")
    P(f"[{tag}] player_death = {json.dumps(c.get('player_death'), ensure_ascii=False)[:400]}")
    P(f"[{tag}] reign_end    = {json.dumps(c.get('reign_end'), ensure_ascii=False)[:300]}")
    P(f"[{tag}] characters[{pid}].death = {json.dumps(ch.get('death'), ensure_ascii=False)[:300]}")
    P(f"[{tag}] characters[{pid}].dead_data = {json.dumps(ch.get('dead_data'), ensure_ascii=False)[:400]}")
    P(f"[{tag}] realm_history 段数 = {len(c.get('realm_history') or [])} "
      f"首={json.dumps((c.get('realm_history') or [{}])[0], ensure_ascii=False)[:200]} "
      f"末={json.dumps((c.get('realm_history') or [{}])[-1], ensure_ascii=False)[:260]}")
    return c


def melt_choice(cache_main):
    """The melt file the real run picked (pipeline.load_latest_melt 的路径选择）。"""
    import llm
    import pipeline as pl
    cfg = llm.load_config()
    last = cache_main.get("last_date")
    p = pl.melt_path_for_cache(cfg, cache_main, last)
    P(f"[melt] cache last_date={last!r} -> melt_path_for_cache = {os.path.relpath(p, ROOT)} "
      f"exists={os.path.isfile(p)}")
    for d in sorted(cache_main.get("sources") or [], key=cl.date_key, reverse=True)[:4]:
        p2 = pl.melt_path_for_cache(cfg, cache_main, d)
        P(f"[melt]   fallback candidate {d} -> {os.path.relpath(p2, ROOT)} "
          f"exists={os.path.isfile(p2)}")
    return p


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "cacheinfo"
    if mode == "cacheinfo":
        P("\n" + "=" * 78)
        P("== [S4] 实跑缓存与本人缓存的关键字段 ==")
        c_main = cache_summary("S4a 洪光通缓存", PID)
        if c_main:
            melt_choice(c_main)
        del c_main
        cache_summary("S4b 天贵福本人缓存", CID)
        cache_summary("S4c 秀全本人缓存", CID_XQ)
        flush()
        return

    if mode == "melt":
        which = "1285"
        for a in sys.argv[1:]:
            if a.startswith("--melt="):
                which = a.split("=", 1)[1]
        which = which if which.startswith("melt_") else f"melt_{which}_01_01.json"
        p = os.path.join(DATA, which)
        if not os.path.isfile(p):
            p = cl.melt_file_exists(p) or p
        P("\n" + "=" * 78)
        P(f"== [S5] 熔件 {os.path.basename(p)} 上的逐步复算 ==")
        # 段级：目标头衔 history
        lt = cl.load_melt_landed_titles(p)
        for tid in ("13265", "15771", "15769", "15766", "14022"):
            t = lt.get(tid) or {}
            P(f"[S5-lt] tid={tid} key={t.get('key')!r} name_data="
              f"{json.dumps(t.get('title_name_data'), ensure_ascii=False)}")
            P(f"          history={json.dumps(t.get('history') or {}, ensure_ascii=False)[:2500]}")
        del lt

        import facts as F
        c_main = cl.load_cache(cache_path(PID))
        camp = {}
        for x in (CID, CID_XQ):
            cp = cache_path(x)
            if os.path.isfile(cp):
                camp[x] = cl.load_cache(cp)
        P(f"[S5] campaign 缓存 keys={sorted(camp)} (仅为 _gen_end_date 取本人档)")
        P(f"[S5] 整载熔件 {os.path.basename(p)} …")
        melt = cl.load_melt(p)
        f = F.Facts(c_main, melt, os.path.join(DATA, "names.json"), as_of=AS_OF, campaign=camp)
        P(f"[S5] _gen_end_date(44503) = {F._gen_end_date(f, CID)!r}")
        P(f"[S5] _gen_end_date(38957) = {F._gen_end_date(f, CID_XQ)!r}")
        P(f"[S5] cache characters[44503].death = "
          f"{json.dumps(((c_main.get('characters') or {}).get(str(CID)) or {}).get('death'), ensure_ascii=False)}")
        P(f"[S5] realm_history 段数={len(f._realm_snaps)} 日期前6={[s.get('date') for s in f._realm_snaps[:6]]}")
        rh = f._realm_holder_titles.get(CID) or {}
        P(f"[S5] cid=44503 由 realm 快照回退得到的 tid 数={len(rh)} "
          f"其中与目标相关：{ {t: sorted(v) for t, v in rh.items() if str(t) in WATCH} }")

        for label, cid, dts in (("天贵福", CID, ("952.1.29", "952.1.28", "951.12.6", None)),
                                ("秀全", CID_XQ, ("904.11.30", "904.11.29", "904.11.30", None))):
            P(f"\n[S5] ---- {label} cid={cid} ----")
            for date in dts:
                anchor = f._anchor_date(cid, date)
                hold = f._hold_intervals(cid, anchor)
                P(f"  date={date!r} -> _anchor_date={anchor!r}")
                P(f"      _has_current_landed_title={f._has_current_landed_title(cid, anchor)!r}")
                P(f"      _ministry_office_at(former=False)={f._ministry_office_at(cid, anchor)!r} "
                  f"(former=True)={f._ministry_office_at(cid, anchor, include_former=True)!r}")
                P(f"      official_title={f.official_title(cid, date)!r}")
                P(f"      _current_title_tid={f._current_title_tid(cid, anchor)!r} "
                  f"_last_high_title_before={f._last_high_title_before(cid, anchor)!r}")
                P(f"      _former_high_title(no excl)={f._former_high_title(cid, anchor)!r}")
                cur_tid = f._current_title_tid(cid, anchor) if f.official_title(cid, date) else None
                P(f"      _former_high_title(excl={cur_tid!r})="
                  f"{f._former_high_title(cid, anchor, exclude_tid=cur_tid)!r}")
                P(f"      _primary_title_at={f._primary_title_at(cid, as_of=anchor)!r}")
                P(f"      _hold_intervals 目标 tid: "
                  f"{ {t: hold.get(int(t)) for t in WATCH if t in hold} }")
                P(f"      person_label(full)={f.person_label(cid, date, 'full')!r}")
                if cid == CID:
                    off = f.official_title(cid, date)
                    nm = f.name_with_regnal(cid, date)
                    acc = f.accolade_word_at(cid, date)
                    pn = f"{acc}{nm}" if acc else nm
                    P(f"      _full_label(cur={off!r}, nm={pn!r})="
                      f"{f._full_label(cid, date, off, pn)!r}")
            P(f"  _hold_intervals({cid}) 全量 key 与区间：")
            for tid, ivs in sorted(f._hold_intervals(cid).items()):
                key = (f._lt.get(str(tid)) or {}).get("key") or ""
                if key.startswith(("e_", "h_", "x_")):
                    P(f"      tid={tid} key={key!r} ivs={ivs}")
            # 该代结束那天（本人卒日）区间刚好闭合的头衔个数与档位分布
            endd = F._gen_end_date(f, cid)
            if endd:
                closed_same, still_open = [], []
                for tid, ivs in f._hold_intervals(cid, endd).items():
                    key = (f._lt.get(str(tid)) or {}).get("key") or ""
                    if any(iv[1] == endd for iv in ivs):
                        closed_same.append((tid, key))
                    if any(iv[1] is None for iv in ivs):
                        still_open.append((tid, key))
                P(f"  [{label}] 卒日={endd} 恰在该日闭合的头衔 {len(closed_same)} 个（档位 "
                  f"{sorted({k[:2] for _t, k in closed_same})}）；当日仍开放 {len(still_open)} 个 "
                  f"{[ (t,k) for t,k in still_open ]}")
                P(f"  [{label}] 卒日前一天 {f._anchor_date(cid, endd)!r} 的 official_title="
                  f"{f.official_title(cid, endd)!r} vs 前一日 official_title="
                  f"{f.official_title(cid, endd[:-1] + str(int(endd.split('.')[-1])-1) if endd.split('.')[-1].isdigit() and int(endd.split('.')[-1])>1 else endd)!r}")
                # 名字历史（解释 顺皇帝/天皇帝 的差别）
                P(f"  [{label}] h_china(14022) title_name_data="
                  f"{json.dumps((f._lt.get('14022') or {}).get('title_name_data'), ensure_ascii=False)}")
                P(f"  [{label}] _name_at_date(14022, {endd})={f._name_at_date(14022, endd)!r} "
                  f"_ruler_word_at(14022)={f._ruler_word_at(cid, 14022, endd)!r}")
                P(f"  [{label}] _former_title_text(14022, {endd})="
                  f"{f._former_title_text(cid, 14022, endd)!r}")
        P(f"\n[S5] genealogy.json 的 chain 逐代对照（end = 下一位传主的起算日，即该代卒/让位日）：")
        try:
            tree = json.load(io.open(os.path.join(DATA, "genealogy.json"), encoding="utf-8"))
            chain = tree.get("chain") or []
            for k, e in enumerate(chain):
                cid = e.get("id")
                nxt = chain[k + 1]["date"] if k + 1 < len(chain) else None
                dd = F._gen_end_date(f, cid) or nxt or ""
                db = F._day_before(dd) if dd else ""
                P(f"      i={e.get('i')} id={cid} {e.get('name')!r} chain.label={e.get('label')!r}")
                P(f"          gen_end={dd!r} | official_title(gen_end)={f.official_title(cid, dd)!r} "
                  f"| label(gen_end)={f.person_label(cid, dd, 'full')!r}")
                P(f"          gen_end-1={db!r} | official_title={f.official_title(cid, db)!r} "
                  f"| label={f.person_label(cid, db, 'full')!r}")
                P(f"          _has_current_landed_title(gen_end)={f._has_current_landed_title(cid, dd)!r} "
                  f"label(as_of)={f.person_label(cid, f.as_of, 'full')!r}")
        except Exception as exc:
            P(f"      (genealogy.json 对照失败: {exc})")
        flush()
        return

    print(__doc__)


if __name__ == "__main__":
    main()
