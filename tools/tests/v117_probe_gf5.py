# -*- coding: utf-8 -*-
"""v117 取证探针 · 第五段：
  S7  熔件里 44503/38957 到底在哪个人物桶（living / dead_unprunable / characters.dead_prunable），
      各桶里有哪些字段（name_zh / dynasty_house / dead_data.flavor / death）——解释缓存里为什么没有他
  S8  真实 Facts（campaign = 同战役全部 player_*.json）下，改前 / 改后逐代 person_label 对照表
  S9  1283 与 1285 两档熔件上关键头衔区间是否一致（段级读取）
  S10 名字里的「洪」：display_name / name_order 的入口与取值
  S11 建议补丁文本（只打印，不落盘）

用法：& tools\\py.ps1 tools\\tests\\v117_probe_gf5.py [--stub] [--no-full]
输出追加 logs/v117/v117_probe_gf.txt（UTF-8）。
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
CID = 44503
CID_XQ = 38957
AS_OF = "1283.9.11"
CHAIN_IDS = [38957, 44503, 67172818, 16879059, 16878235, 135480, 117484775, 16945142,
             207044, 33725392, 16974237, 226889, 50565938, 17066495]

_buf = []


def P(*a):
    s = " ".join(str(x) for x in a)
    _buf.append(s)
    print(s, flush=True)


def flush():
    with open(OUT, "a", encoding="utf-8") as fp:
        fp.write("\n".join(_buf) + "\n")
    _buf.clear()


def melt_path(name):
    p = os.path.join(DATA, name)
    return cl.melt_file_exists(p) or None


# ---------------------------------------------------------------- S7
def s7():
    P("\n" + "=" * 78)
    P("== [S7] 熔件人物桶里 44503 / 38957 的可见性 ==")
    for mn in ("melt_1283_01_01.json", "melt_1285_01_01.json", "melt_1280_01_01.json"):
        p = melt_path(mn)
        if not p:
            P(f"[S7] 缺 {mn}")
            continue
        P(f"\n[S7] --- {os.path.basename(p)} ---")
        for key in ("living", "dead_unprunable", "characters"):
            try:
                sec = cl.load_melt_section(p, key)
            except Exception as exc:
                P(f"[S7]   {key}: 段读取失败 {exc}")
                continue
            if not isinstance(sec, dict):
                P(f"[S7]   {key}: 非 dict ({type(sec).__name__})")
                continue
            P(f"[S7]   {key}: 顶层键数={len(sec)}  含 dead_prunable={isinstance(sec.get('dead_prunable'), dict)}")
            for cid in (CID, CID_XQ):
                rec = sec.get(str(cid))
                if rec is None and isinstance(sec.get("dead_prunable"), dict):
                    rec = sec["dead_prunable"].get(str(cid))
                    tag = "characters.dead_prunable"
                else:
                    tag = key
                if rec is None:
                    P(f"[S7]     {cid}: 不在 {key}")
                    continue
                if isinstance(rec, list):
                    rec = rec[0] if rec else {}
                if not isinstance(rec, dict):
                    P(f"[S7]     {cid}: 形状异常 {type(rec).__name__}")
                    continue
                P(f"[S7]     {cid} @{tag}: keys={sorted(rec.keys())}")
                P(f"[S7]        name_zh={cl.name_zh(rec)!r} first_name={rec.get('first_name')!r} "
                  f"dynasty_house={rec.get('dynasty_house')!r} culture={rec.get('culture')!r} "
                  f"female={rec.get('female')!r} birth={rec.get('birth')!r}")
                P(f"[S7]        dead_data={json.dumps(rec.get('dead_data'), ensure_ascii=False)[:400]}")
                P(f"[S7]        alive_data? {'alive_data' in rec} "
                  f"house={cl.house_name_zh_from(rec)!r}" if hasattr(cl, "house_name_zh_from") else "")
    flush()


# ---------------------------------------------------------------- S8
def full_campaign():
    camp = {}
    for fn in os.listdir(DATA):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        c = cl.load_cache(os.path.join(DATA, fn))
        if c.get("playthrough_id") == cl.load_cache(os.path.join(DATA, f"player_{PID}.json")
                                                  ).get("playthrough_id"):
            camp[int(m.group(1))] = c
    return camp


def stub_campaign():
    """只留 _gen_end_date / death_date 需要的字段（内存不够时的降级方案）。"""
    main = cl.load_cache(os.path.join(DATA, f"player_{PID}.json"))
    pth = main.get("playthrough_id")
    camp = {}
    for fn in os.listdir(DATA):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        c = cl.load_cache(os.path.join(DATA, fn))
        pid = int(m.group(1))
        if c.get("playthrough_id") != pth:
            continue
        camp[pid] = {
            "player_id": c.get("player_id"), "playthrough_id": pth,
            "last_date": c.get("last_date"), "sources": c.get("sources"),
            "player_death": c.get("player_death"), "reign_end": c.get("reign_end"),
            "characters": {str(pid): (c.get("characters") or {}).get(str(pid)) or {}},
            "realm_history": [],
        }
        del c
    return main, camp


def death_date_new(self, cid):
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
    return ""


def s8(stub=False):
    import facts as F
    P("\n" + "=" * 78)
    P(f"== [S8] 改前 / 改后 person_label(cid, gen_end, 'full') 对照（campaign={'stub' if stub else '全量'}） ==")
    if stub:
        main, camp = stub_campaign()
    else:
        main = cl.load_cache(os.path.join(DATA, f"player_{PID}.json"))
        camp = full_campaign()
    P(f"[S8] campaign 覆盖 {len(camp)} 个传主档：{sorted(camp)}")
    melt = cl.load_melt(melt_path("melt_1283_01_01.json"))
    names = os.path.join(DATA, "names.json")
    if not os.path.isfile(names):
        names = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(main, melt, names, as_of=AS_OF, campaign=camp)
    for cid in CHAIN_IDS:
        rec = (main.get("characters") or {}).get(str(cid)) or {}
        cd = (rec.get("death") or {}).get("date") or ""
        pv = camp.get(cid) or {}
        pd = (pv.get("player_death") or {}).get("date") if isinstance(pv.get("player_death"), dict) else ""
        re_ = (pv.get("reign_end") or {}).get("date") if isinstance(pv.get("reign_end"), dict) else ""
        P(f"[S8]   cid={cid} characters.death={cd!r} campaign.player_death={pd!r} reign_end={re_!r}")
    rows = []
    for cid in CHAIN_IDS:
        end = F._gen_end_date(f, cid) or ""
        if not end:
            continue
        before = f.person_label(cid, end, "full")
        rows.append((cid, end, before, None))

    # ---- 打补丁：_anchor_date 改用 death_date(cid)，_gen_end_date 同源
    F.Facts.death_date = death_date_new
    _orig_anchor = F.Facts._anchor_date

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

    F.Facts._anchor_date = _anchor_new
    F._gen_end_date = lambda ff, c: ff.death_date(c) or ""
    P("\n[S8] cid        终点日      改前                                    改后                                  变?")
    changed = 0
    for i, (cid, end, before, _x) in enumerate(rows):
        f._label_cache.clear()
        after = f.person_label(cid, end, "full")
        flag = "变化" if after != before else "—"
        if after != before:
            changed += 1
        P(f"[S8] {cid:>10} {end:<11} {before!r:<38} {after!r:<38} {flag}")
    P(f"[S8] 结论：{len(rows)} 个传主里 {changed} 处标签发生变化")
    flush()


# ---------------------------------------------------------------- S9
def s9():
    P("\n" + "=" * 78)
    P("== [S9] melt_1283 与 melt_1285 关键头衔区间 / 名称对照 ==")
    tids = ("13265", "14022", "15771", "15769", "15766", "15518", "18232")
    snaps = {}
    for mn in ("melt_1283_01_01.json", "melt_1285_01_01.json"):
        p = melt_path(mn)
        if not p:
            P(f"[S9] 缺 {mn}")
            continue
        lt = cl.load_melt_landed_titles(p)
        snaps[mn] = {}
        P(f"[S9] --- {os.path.basename(p)} ---")
        for tid in tids:
            t = lt.get(tid) or {}
            hist = t.get("history") or {}
            got = {d: e for d, e in hist.items()
                   if any((isinstance(x, dict) and x.get("holder") in (CID, CID_XQ))
                          or x in (CID, CID_XQ) for x in (e if isinstance(e, list) else [e]))}
            P(f"[S9]   tid={tid} key={t.get('key')!r} name_data={json.dumps(t.get('title_name_data'), ensure_ascii=False)[:200]}")
            P(f"[S9]       相关 history={json.dumps(got, ensure_ascii=False)}")
            snaps[mn][tid] = json.dumps(got, ensure_ascii=False, sort_keys=True)
        del lt
    if len(snaps) == 2:
        a, b = list(snaps.values())
        same = all(a[t] == b[t] for t in tids)
        P(f"[S9] 两档熔件在这些头衔上的相关 history 完全一致：{same}")
    flush()


# ---------------------------------------------------------------- S10
def s10():
    P("\n" + "=" * 78)
    P("== [S10] 名字里的「洪」是谁加的 ==")
    main = cl.load_cache(os.path.join(DATA, f"player_{PID}.json"))
    for cid in (CID, CID_XQ):
        rec = (main.get("characters") or {}).get(str(cid)) or {}
        P(f"[S10] 主缓存 characters[{cid}] 存在={bool(rec)} keys={sorted(rec.keys())[:12] if rec else []}")
    names = os.path.join(DATA, "names.json")
    if not os.path.isfile(names):
        names = os.path.join(ROOT, "data", "names.json")
    nm_tab = cl._load_names(names, None)
    for cid in (CID, CID_XQ):
        P(f"[S10] names.json[{cid}] = {json.dumps(nm_tab.get(str(cid)), ensure_ascii=False)}")
    flush()


def main():
    if "--s7" in sys.argv or True:
        s7()
    if "--s8" in sys.argv or True:
        s8(stub=("--stub" in sys.argv))
    s9()
    s10()
    P("\n[S11] 建议补丁（只打印，未落盘）——见最终报告代码块")


if __name__ == "__main__":
    main()
