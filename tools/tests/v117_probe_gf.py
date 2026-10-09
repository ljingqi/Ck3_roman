# -*- coding: utf-8 -*-
"""v117 取证探针：洪天贵福（cid=44503）终传世系头行为何取到「前工部尚书」。

只读，不改任何生产代码。输出同时写 logs/v117_probe_gf.txt（UTF-8）。

阶段：
  S1  段级读取熔件 landed_titles（不整载 470MB），列出 cid=44503 的全部头衔区间
  S2  只打印相关 tid 的完整字段（key / name / tier / history 片段）
  S3  用 cache + 熔件建 Facts，复算 official_title / _current_title_tid /
      _former_high_title / _former_title_text / person_label("full") / _anchor_date

用法：& tools\py.ps1 tools\tests\v117_probe_gf.py [--melts=1283,1285] [--facts]
"""
import os
import re
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cache_lib as cl  # noqa: E402

FOLDER = "洪氏2"
DATA = os.path.join(ROOT, "output", FOLDER, "data")
OUT = os.path.join(ROOT, "logs", "v117_probe_gf.txt")

CID = 44503
CID_XIUQUAN = 38957
PID = 17066495
AS_OF = "1283.9.11"

_lines = []


def P(*a):
    s = " ".join(str(x) for x in a)
    _lines.append(s)
    print(s, flush=True)


def melt_path(name):
    for cand in (name, name + ".xz", name + ".gz"):
        p = os.path.join(DATA, cand)
        if os.path.isfile(p):
            return p
    return None


def intervals_of(lt, cid):
    """[(tid, key, name, [(date, holder/None, type), ...])] for every title whose history touches cid."""
    out = []
    for tid, t in lt.items():
        if not isinstance(t, dict):
            continue
        hist = t.get("history") or {}
        if not isinstance(hist, dict) or not hist:
            continue
        if not _hist_has(hist, cid):
            continue
        out.append(tid)
    return sorted(out, key=lambda x: int(x))


def _hist_has(hist, cid):
    for _d, ev in hist.items():
        for e in (ev if isinstance(ev, list) else [ev]):
            if isinstance(e, dict) and e.get("holder") == cid:
                return True
    return False


def hold_segments(hist, cid):
    """[(gain, loss, loss_type)] intervals during which cid is the holder."""
    segs = []
    cur = None
    for d in sorted(hist.keys(), key=cl.date_key):
        ev = hist[d]
        for e in (ev if isinstance(ev, list) else [ev]):
            if not isinstance(e, dict):
                e = {"holder": e}
            h = e.get("holder")
            typ = e.get("type") or ""
            if h == cid:
                if cur is None:
                    cur = (d, None, "")
            else:
                if cur is not None:
                    segs.append((cur[0], d, typ))
                    cur = None
    if cur is not None:
        segs.append(cur)
    return segs


def main():
    want_melts = ["melt_1283_01_01.json", "melt_1285_01_01.json"]
    do_facts = False
    for a in sys.argv[1:]:
        if a.startswith("--melts="):
            want_melts = [f"melt_{x.strip()}_01_01.json" for x in a.split("=", 1)[1].split(",")]
        elif a == "--facts":
            do_facts = True

    # ---------------- S1: 段级读 landed_titles ----------------
    keep_lt = {}
    for mn in want_melts:
        p = melt_path(mn)
        if not p:
            P(f"[S1] 缺熔件 {mn}")
            continue
        P(f"\n===== [S1] 熔件 {os.path.basename(p)} "
          f"({os.path.getsize(p)/1048576:.0f} MB) =====")
        lt = cl.load_melt_landed_titles(p)
        P(f"[S1] landed_titles 条数 = {len(lt)}")
        keep_lt[mn] = lt
        tids = intervals_of(lt, CID)
        P(f"[S1] cid={CID} 出现在 {len(tids)} 个头衔的 history 中： {tids}")
        for tid in tids:
            t = lt[tid]
            key = t.get("key") or ""
            P(f"  tid={tid} key={key!r} name={t.get('name')!r} "
              f"de_facto_liege={t.get('de_facto_liege')!r} tier={t.get('tier')!r} "
              f"gov={t.get('government')!r} title_holders? "
              f"rank={cl_tier_name(t)}")
            for (g, l, typ) in hold_segments(t.get("history") or {}, CID):
                P(f"      hold {g} -> {l}  (loss_type={typ!r}) "
                  f"gain_type={gain_type(t.get('history') or {}, g, CID)!r}")
        # 顺带：洪秀全
        tids2 = intervals_of(lt, CID_XIUQUAN)
        P(f"[S1] cid={CID_XIUQUAN}(秀全) 出现在 {len(tids2)} 个头衔： {tids2}")
        for tid in tids2:
            t = lt[tid]
            P(f"  tid={tid} key={t.get('key')!r} name={t.get('name')!r}")
            for (g, l, typ) in hold_segments(t.get("history") or {}, CID_XIUQUAN):
                P(f"      hold {g} -> {l}  (loss_type={typ!r})")

    # ---------------- S2: 相关标题完整字段 ----------------
    for mn, lt in keep_lt.items():
        P(f"\n===== [S2] {mn} 相关标题完整字段 =====")
        for tid in intervals_of(lt, CID):
            t = lt[tid]
            key = t.get("key") or ""
            if not (key.startswith(("e_", "h_", "x_")) or tid in ("15771", "15769", "15766")):
                continue
            P(f"--- tid={tid} key={key!r} (完整字段) ---")
            slim = {k: v for k, v in t.items() if k != "history"}
            P(json.dumps(slim, ensure_ascii=False)[:1800])
            P("    history: " + json.dumps(t.get("history") or {}, ensure_ascii=False)[:3000])

    # ---------------- S3: Facts 复算 ----------------
    if do_facts:
        import facts as F
        import localization as L  # noqa: F401
        cache_path = os.path.join(DATA, f"player_{PID}.json")
        names = os.path.join(DATA, "names.json")
        if not os.path.isfile(names):
            names = os.path.join(ROOT, "data", "names.json")
        P(f"\n===== [S3] 载入缓存 {os.path.basename(cache_path)} =====")
        cache = cl.load_cache(cache_path)
        for mn in want_melts:
            p = melt_path(mn)
            if not p:
                continue
            P(f"[S3] 整载熔件 {os.path.basename(p)} …")
            melt = cl.load_melt(p)
            f = F.Facts(cache, melt, names, as_of=AS_OF)
            rec = (cache.get("characters") or {}).get(str(CID)) or {}
            P(f"[S3] cache characters[{CID}].death = {json.dumps(rec.get('death'), ensure_ascii=False)}")
            P(f"[S3] name_or={f.name_or(CID)!r} name_with_regnal={f.name_with_regnal(CID, None)!r}")
            P(f"[S3] _gen_end_date({CID}) = {(F._gen_end_date(f, CID) if hasattr(F, '_gen_end_date') else 'n/a')!r}")
            P(f"[S3] dead_data.flavor = {(rec.get('dead_data') or {}).get('flavor')!r}")
            P(f"[S3] _has_current_landed_title(952.1.28) = {f._has_current_landed_title(CID, '952.1.28')!r}")
            P(f"[S3] _ministry_office_at(952.1.28) = {f._ministry_office_at(CID, '952.1.28')!r}")
            P(f"[S3] _ministry_office_at(952.1.28, former) = "
              f"{f._ministry_office_at(CID, '952.1.28', include_former=True)!r}")
            for date in ("952.1.29", "952.1.28", "951.12.6", "951.12.5", None):
                P(f"[S3] date={date!r}")
                P(f"      _anchor_date      = {f._anchor_date(CID, date)!r}")
                P(f"      official_title    = {f.official_title(CID, date)!r}")
                P(f"      _current_title_tid= {f._current_title_tid(CID, f._anchor_date(CID, date))!r}")
                P(f"      _former_high_title= {f._former_high_title(CID, f._anchor_date(CID, date))!r}")
                P(f"      _primary_title_at = {f._primary_title_at(CID, as_of=f._anchor_date(CID, date))!r}")
                P(f"      person_label full = {f.person_label(CID, date, 'full')!r}")
            P(f"[S3] _hold_intervals({CID}) = {json.dumps(_segs_dump(f._hold_intervals(CID)), ensure_ascii=False)}")
            for (tid, key) in _lt_of(f, CID):
                P(f"      tid={tid} key={key!r} landed={f._is_landed_title(tid)} "
                  f"rank={f._TT_RANK.get(key[:2], 0)} eff_rank={f._eff_rank(tid)} "
                  f"base={f.title_base_name(tid)!r}")
            # 秀全对照
            P(f"[S3] 秀全 person_label full(904.11.30) = "
              f"{f.person_label(CID_XIUQUAN, '904.11.30', 'full')!r}")
            P(f"[S3] 秀全 official_title(904.11.30) = {f.official_title(CID_XIUQUAN, '904.11.30')!r}")

    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write("\n".join(_lines) + "\n")
    print(f"\n[out] {OUT}")


def cl_tier_name(t):
    return (t.get("key") or "")[:2]


def gain_type(hist, date, cid):
    ev = hist.get(date)
    for e in (ev if isinstance(ev, list) else [ev]):
        if isinstance(e, dict) and e.get("holder") == cid:
            return e.get("type") or ""
    return ""


def _segs_dump(hold):
    return {str(tid): [[g, l, lt] for (g, l, lt) in ivs] for tid, ivs in hold.items()}


def _lt_of(f, cid):
    out = []
    for tid in f._hold_intervals(cid):
        out.append((tid, (f._lt.get(str(tid)) or {}).get("key") or ""))
    return out


if __name__ == "__main__":
    main()
