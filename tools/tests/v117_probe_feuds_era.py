# -*- coding: utf-8 -*-
"""v117 取证（第二轮）：1232.12.16「哈德良波利斯洪 × 宁浦洪 爆发世仇」这条关系到底在不在熔件里？

做法：段级读取若干年份熔件的 house_relations 段，找 houses 同时含 22285(宁浦洪) 与 31062(哈德良波利斯洪) 的行；
      再从玩家缓存里打印洪希晏/洪景宪/洪光通等人的 house_history 与 house_feud_* 记忆。
输出：logs/v117/v117_probe_feuds_era.txt (UTF-8)。只读，不写任何生产数据。
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
CACHE = os.path.join(DATA, "player_17066495.json")
LOG_PATH = os.path.join(ROOT, "logs", "v117_probe_feuds_era.txt")

# 宁浦洪 / 哈德良波利斯洪 / 邕州洪
H_NINGPU, H_HADRIAN, H_YONGZHOU = 22285, 31062, 16799492
MELTS = ["melt_1233_01_01.json.xz", "melt_1245_01_01.json.xz"]

# 关键人物：洪希晏(1181)、洪景宪(宁浦洪乡绅)、洪士宁(1269 家主)、洪光通(本传主)
PEOPLE = {50565938: "洪希晏(1181)",
          264109: "洪景宪(宁浦洪, 待确认)",
          67325521: "洪公仅/洪景宪?",
          50586737: "洪士宁(1269 宁浦洪家主)",
          17066495: "洪光通(1236, 本传主)",
          84157669: "洪惠娘",
          50585072: "洪步虚"}

_buf = []


def w(s=""):
    _buf.append(str(s))
    print(str(s), flush=True)


def main():
    t0 = time.time()
    w("# v117 取证（第二轮）：1232.12.16 哈德良波利斯洪×宁浦洪 关系行的存在性")
    w(f"# {time.strftime('%Y-%m-%d %H:%M:%S')}")
    cache = cl.load_cache(CACHE)
    chars = cache.get("characters") or {}
    w(f"[缓存] last_date={cache.get('last_date')} dynasty_id={cache.get('dynasty_id')} "
      f"characters={len(chars)}  载入 {time.time() - t0:.1f}s")

    w("")
    w("=" * 100)
    w("[G] 关键人物：dynasty_house / house_history / house_feud_* 记忆")
    w("=" * 100)
    for cid, who in PEOPLE.items():
        rec = chars.get(str(cid)) or {}
        w("")
        w(f"  cid={cid} {who}: name={rec.get('name_full') or rec.get('name_zh')!r} "
          f"dynasty_house={rec.get('dynasty_house')} dynasty_id={rec.get('dynasty_id')} "
          f"birth={rec.get('birth')} death={rec.get('death')}")
        hh = rec.get("house_history") or []
        for h in hh:
            w(f"      house_history: {h}")
        if not hh:
            w("      house_history: （空）")
        for mem in (rec.get("memories") or []):
            t = str(mem.get("type") or "")
            if t in ("house_feud_started_memory", "house_feud_ended_memory") or "feud" in t:
                w(f"      memory type={t} creation={mem.get('creation_date')} "
                  f"end={mem.get('end_date')} participants={mem.get('participants')} "
                  f"vars={mem.get('vars')}")

    w("")
    w("=" * 100)
    w("[H] 全缓存扫描：所有 house_feud_started_memory / house_feud_ended_memory")
    w("=" * 100)
    n = 0
    for cid, rec in chars.items():
        if not isinstance(rec, dict):
            continue
        for mem in (rec.get("memories") or []):
            t = str(mem.get("type") or "")
            if t in ("house_feud_started_memory", "house_feud_ended_memory"):
                n += 1
                w(f"  cid={cid} ({rec.get('name_full') or rec.get('name_zh')}) type={t} "
                  f"date={mem.get('creation_date')} end={mem.get('end_date')} "
                  f"participants={mem.get('participants')} vars={mem.get('vars')}")
    w(f"  合计 {n} 条")

    for mn in MELTS:
        mp = os.path.join(DATA, mn)
        if not os.path.isfile(mp):
            w(f"\n!! 缺熔件 {mn}")
            continue
        t1 = time.time()
        w("")
        w("=" * 100)
        w(f"[I] 熔件 {mn} 的 house_relations 段：houses 含 22285 与 31062 的行")
        w("=" * 100)
        hrel = cl.load_melt_section(mp, "house_relations") or {}
        db = hrel.get("database") or {}
        w(f"    段级读取完成 {time.time() - t1:.1f}s; database {len(db)} 行")
        pair, ning = [], []
        for k, r in db.items():
            if not isinstance(r, dict):
                continue
            hs = r.get("houses") or []
            if H_NINGPU in hs and H_HADRIAN in hs:
                pair.append((k, r))
            if H_NINGPU in hs:
                ning.append((k, r))
        w(f"    houses 同时含 {H_NINGPU} 与 {H_HADRIAN} 的行: {len(pair)}")
        for k, r in pair:
            w(f"      key={k} level={r.get('level')!r} history={(r.get('history') or []) and len(r['history'])}")
            for e in (r.get("history") or []):
                w(f"        · {e.get('date')} amount={e.get('amount')!r} "
                  f"{str(e.get('change_reason') or '')[:120]!r}")
        w(f"    含 {H_NINGPU}(宁浦洪) 的行共 {len(ning)} 条：")
        for k, r in ning:
            lvl = str(r.get("level") or "")
            hs = r.get("houses") or []
            oth = [h for h in hs if h != H_NINGPU]
            dates = [str(e.get("date") or "") for e in (r.get("history") or [])]
            w(f"      key={k} level={lvl} houses={hs} 对方={oth} "
              f"history={len(dates)} 日期={dates[:12]}{'…' if len(dates) > 12 else ''}")
        # 打印 1232 年附近的条目
        w(f"    上述行中 1232/1233 年附近的条目：")
        for k, r in ning:
            for e in (r.get("history") or []):
                d = str(e.get("date") or "")
                if d.startswith("1232") or d.startswith("1233"):
                    w(f"      key={k} · {d} amount={e.get('amount')!r} "
                      f"{str(e.get('change_reason') or '')[:180]!r}")
        _ = ning

    w(f"\n# 总耗时 {time.time() - t0:.1f}s")
    with open(LOG_PATH, "w", encoding="utf-8") as fp:
        fp.write("\n".join(_buf) + "\n")
    print(f"\n[写盘] {LOG_PATH}")


if __name__ == "__main__":
    main()
