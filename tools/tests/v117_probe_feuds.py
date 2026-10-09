# -*- coding: utf-8 -*-
"""v117 取证脚本（只读，不改任何生产数据）：

《家族恩怨录》为何没有「宁浦洪氏」——player_id=17066495, as_of=1283.9.11, 家族文件夹 output/洪氏2。

做法：
  * 玩家缓存整载一次（cl.load_cache）；
  * 熔件只做**段级读取**：cl.load_melt_section(path, "dynasties") 与 "house_relations"；
  * 逐条套用 facts.py:11733-11894 house_feuds() 的过滤条件，打印每一步的去留；
  * 输出同时写 logs/v117_probe_feuds.txt (UTF-8)。

用法： & tools\\py.ps1 tools\\tests\\v117_probe_feuds.py
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl        # noqa: E402
import localization as L      # noqa: E402

FOLDER = "洪氏2"
PID = 17066495
AS_OF = "1283.9.11"
# 实跑侧（pipeline.load_latest_melt）取 cache["last_date"] 那一档；目录里最新的档是 1285。
# 先按任务给定的 1283，再对 1285 做同样取证，确认结论与熔件档位无关。
MELTS = ["melt_1283_01_01.json", "melt_1285_01_01.json"]
LOG_PATH = os.path.join(ROOT, "logs", "v117_probe_feuds.txt")

NEG = {"default_house_relation_level_feud",
       "default_house_relation_level_rivalry",
       "default_house_relation_level_quarrel"}
RANK = {"世仇": 3, "敌对": 2, "争吵": 1}

_FEUD_CHAR_RE = __import__("re").compile(r"ONCLICK:CHARACTER,(\d+)")
_PRISON_WORDS = ("囚禁了", "囚禁")

_buf = []


def w(s=""):
    _buf.append(str(s))
    print(str(s), flush=True)


def hr(title):
    w("")
    w("=" * 100)
    w(title)
    w("=" * 100)


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:            # noqa: BLE001
        return f"<ERR {type(e).__name__}: {e}>"


def house_row(melt_part, hid, dh):
    """One house's identifying data as the save/table carries it."""
    e = dh.get(str(hid)) or {}
    return {
        "id": hid,
        "name_zh": _safe(cl.house_name_zh, melt_part, hid),
        "label": _safe(_house_label, melt_part, hid),
        "dynasty": e.get("dynasty"),
        "found_date": e.get("found_date"),
        "key": e.get("key"),
        "loc_name": e.get("localized_name"),
        "parent_house": e.get("parent_dynasty_house"),
        "head": e.get("head_of_house") or e.get("head"),
    }


def _house_label(melt_part, hid):
    nm = cl.house_name_zh(melt_part, hid) or ""
    if not nm:
        did = cl.dynasty_id_of(melt_part, hid)
        nm = (cl.dynasty_name_zh(melt_part, did) or "") if did is not None else ""
    if not nm:
        return ""
    return nm if nm.endswith(("氏", "家", "家族", "部")) else f"{nm}氏"


def fmt_house(melt_part, dh, hid):
    r = house_row(melt_part, hid, dh)
    return (f"house {r['id']}: 名={r['name_zh']!r} 标签={r['label']!r} "
            f"dynasty={r['dynasty']} found={r['found_date']!r} key={r['key']!r} "
            f"loc={r['loc_name']!r} parent_house={r['parent_house']!r}")


def main():
    t0 = time.time()
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache_path = os.path.join(data, f"player_{PID}.json")
    w(f"# v117 取证：《家族恩怨录》缺失宁浦洪氏 / player={PID} as_of={AS_OF}")
    w(f"# 时间 {time.strftime('%Y-%m-%d %H:%M:%S')}  工作目录 {ROOT}")
    w(f"# 缓存 {cache_path} ({os.path.getsize(cache_path):,} 字节, "
      f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(cache_path)))})")

    w("\n[0] 整载玩家缓存（本脚本只读一次）…")
    cache = cl.load_cache(cache_path)
    w(f"    done in {time.time() - t0:.1f}s")
    chars = cache.get("characters") or {}
    w(f"    player_id={cache.get('player_id')} dynasty_id={cache.get('dynasty_id')} "
      f"dynasty_name={cache.get('dynasty_name')!r} house_name={cache.get('house_name')!r}")
    w(f"    last_date={cache.get('last_date')} playthrough_id={cache.get('playthrough_id')!r}")
    w(f"    sources tail = {(cache.get('sources') or [])[-6:]}")
    prec = chars.get(str(PID)) or {}
    w(f"    主角缓存: name={prec.get('name_full') or prec.get('name_zh')!r} "
      f"dynasty_house={prec.get('dynasty_house')} dynasty_id={prec.get('dynasty_id')} "
      f"death={prec.get('death')}")

    for melt_name in MELTS:
        mp = os.path.join(data, melt_name)
        if not os.path.isfile(mp):
            w(f"\n!! 熔件不存在: {mp}")
            continue
        _probe_melt(mp, melt_name, cache, chars, prec)
    _rank_probe(cache, chars)

    w(f"\n# 总耗时 {time.time() - t0:.1f}s")
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "w", encoding="utf-8") as fp:
        fp.write("\n".join(_buf) + "\n")
    print(f"\n[写盘] {LOG_PATH}")


def _probe_melt(mp, melt_name, cache, chars, prec):
    t0 = time.time()
    hr(f"熔件 {melt_name}  ({os.path.getsize(mp):,} 字节, "
       f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(mp)))})")
    w("[1] 段级读取 dynasties / house_relations …")
    dyn = cl.load_melt_section(mp, "dynasties") or {}
    dh = dyn.get("dynasty_house") or {}
    dd = dyn.get("dynasties") or {}
    w(f"    dynasties 段: {len(dd)} 个 dynasty, {len(dh)} 个 house  ({time.time() - t0:.1f}s)")
    t1 = time.time()
    hrel = cl.load_melt_section(mp, "house_relations") or {}
    db = hrel.get("database") or {}
    w(f"    house_relations 段: database {len(db)} 行  ({time.time() - t1:.1f}s)")

    melt_part = {"dynasties": dyn,
                 "dynasty_house": dh} if False else {"dynasties": dyn}
    did = cache.get("dynasty_id")

    # ---------- (A) my_houses ----------
    hr(f"[A] my_houses 的实际集合（facts.py:11693-11702 的算法）  熔件={melt_name}")
    my_houses = set()
    h0 = prec.get("dynasty_house")
    if isinstance(h0, int):
        my_houses.add(h0)
    w(f"    步骤①: prec['dynasty_house'] = {h0!r} → my_houses={sorted(my_houses)}")
    w(f"    cache['dynasty_id'] = {did!r}")
    added = []
    if did is not None:
        for hid, e in dh.items():
            if isinstance(e, dict) and e.get("dynasty") == did:
                my_houses.add(int(hid))
                added.append(int(hid))
    w(f"    步骤②: 遍历 dynasty_house，凡 dynasty == {did!r} 的 house 并入 → 命中 "
      f"{len(added)} 个: {sorted(added)}")
    drec = dd.get(str(did)) or {}
    w(f"    dynasty 记录 {did}: name={drec.get('name')!r} loc={drec.get('localized_name')!r} "
      f"key={drec.get('key')!r} 中文={_safe(cl.dynasty_name_zh, melt_part, did)!r} "
      f"found_date={drec.get('found_date')!r} prefix={drec.get('prefix')!r}")
    w(f"    >>> my_houses = {sorted(my_houses)}  (共 {len(my_houses)} 个)")
    for hid in sorted(my_houses):
        w(f"        {fmt_house(melt_part, dh, hid)}")

    # 同 dynasty 的其它 house 也一并列出（看是否还有别的宗支）
    sibs = [int(k) for k, e in dh.items()
            if isinstance(e, dict) and e.get("dynasty") == did]
    w(f"    同 dynasty({did}) 的全部 house: {sorted(sibs)}")

    # ---------- (B) 牵涉 my_houses 的所有行 ----------
    hr(f"[B] house_relations.database 中牵涉任一 my_houses 成员的行  熔件={melt_name}")
    ids = set()
    hits = []
    for k, r in db.items():
        if not isinstance(r, dict):
            continue
        hs = r.get("houses") or []
        if any(h in my_houses for h in hs):
            hits.append((k, r, hs))
            ids.update(hs)
    w(f"    命中 {len(hits)} 行; 涉及 house ids {sorted(ids)}")
    for k, r, hs in hits:
        lvl = r.get("level") or ""
        hist = r.get("history") or []
        w("")
        w(f"  --- 行 key={k}  level={lvl!r}  houses={hs}  history={len(hist)} 条")
        for h in hs:
            mark = " [自家]" if h in my_houses else ""
            w(f"      {fmt_house(melt_part, dh, h)}{mark}")
        for e in hist:
            d = str(e.get("date") or "")
            w(f"      · {d:<12} amount={e.get('amount')!r} reason={str(e.get('change_reason') or '')[:150]!r}")

    # ---------- (C) 所有「洪」姓家族及洪-洪 关系行 ----------
    hr(f"[C] 熔件里所有名字含「洪」的 house，以及「洪—洪」关系行  熔件={melt_name}")
    hong = {}
    for hid, e in dh.items():
        nm = _safe(cl.house_name_zh, melt_part, hid) or ""
        dnm = _safe(cl.dynasty_name_zh, melt_part, (e or {}).get("dynasty")) or ""
        if "洪" in str(nm) or "洪" in str(dnm):
            hong[int(hid)] = (nm, dnm, (e or {}).get("dynasty"), (e or {}).get("found_date"))
    for hid in sorted(hong):
        nm, dnm, d, fd = hong[hid]
        tag = " [my_houses]" if hid in my_houses else ""
        w(f"    house {hid}: 名={nm!r} dynasty名={dnm!r} dynasty={d} found={fd!r}{tag}")
    w("")
    w("    「洪—洪」关系行（两个 house 都姓洪，无论是否 my_houses）：")
    n_hh = 0
    for k, r in db.items():
        if not isinstance(r, dict):
            continue
        hs = r.get("houses") or []
        hh = [h for h in hs if h in hong]
        if len(hh) >= 2:
            n_hh += 1
            lvl = r.get("level") or ""
            hist = r.get("history") or []
            w("")
            w(f"    === key={k} level={lvl!r} history={len(hist)} 条")
            for h in hs:
                w(f"        {fmt_house(melt_part, dh, h)}"
                  f"{' [自己家]' if h in my_houses else ''}")
            for e in hist:
                w(f"        · {str(e.get('date') or ''):<12} amount={e.get('amount')!r} "
                  f"reason={str(e.get('change_reason') or '')[:150]!r}")
    if not n_hh:
        w("        （无）")

    # ---------- (D) 逐条套用 house_feuds 的过滤链 ----------
    hr(f"[D] 对命中行逐条套用 house_feuds() 的过滤条件  熔件={melt_name}")
    _hikey = cl.date_key(AS_OF)
    lo = None   # 终传（decade=None）→ 下界为空，窗口 = (-inf, as_of]

    def in_window(d):
        if not d:
            return False
        k = cl.date_key(d)
        if lo is not None and k < lo:
            return False
        if _hikey is not None and k > _hikey:
            return False
        return True

    def character_death(cid):
        rec = chars.get(str(cid)) or {}
        d = rec.get("death")
        if isinstance(d, dict):
            return d.get("date") or ""
        if isinstance(d, str):
            return d
        return ""

    def widow_divorce(raw, date):
        s = str(raw or "")
        if "离婚" not in s or not date:
            return False
        for i in _FEUD_CHAR_RE.findall(s):
            d = character_death(int(i))
            if d and cl.date_key(d) == cl.date_key(date):
                return True
        return False

    kept = []
    for k, r, hs in hits:
        lvl = r.get("level") or ""
        hist = r.get("history") or []
        # ① any(h in my_houses)  —— 命中行必然通过
        others = [h for h in hs if h not in my_houses]
        # ② level / 负向流
        neg = []
        for e in hist:
            d = str(e.get("date") or "")
            if in_window(d) and (e.get("amount") or 0) < 0 and not widow_divorce(
                    e.get("change_reason") or "", d):
                neg.append(d)
        pass2 = (lvl in NEG) or bool(neg)
        # ③ other 为空
        pass3 = bool(others)
        # ④ events 为空（此处只能给「可渲染候选」的上界：窗口内且非丧偶离婚、非被动囚禁）
        cand = []
        for e in hist:
            d = str(e.get("date") or "")
            raw = str(e.get("change_reason") or "")
            if not in_window(d) and d:
                continue
            if widow_divorce(raw, d):
                continue
            cand.append((d, raw))
        pass4_upper = bool(cand)
        verdict = "保留" if (pass2 and pass3 and pass4_upper) else "丢弃"
        reason = []
        if not pass2:
            reason.append("② level 非负且窗口内无负向流")
        if not pass3:
            reason.append("③ other 为空（对方也在 my_houses 里）")
        if not pass4_upper:
            reason.append("④ events 为空")
        w("")
        w(f"  key={k} houses={hs} level={lvl!r}")
        w(f"      ① any(h in my_houses) : 通过（该行本就在命中列表里）")
        w(f"      ② level∈NEG={lvl in NEG} / 窗口内负向条目 {len(neg)} 条 "
          f"{neg[:6]} → {'通过' if pass2 else '【丢弃】'}")
        w(f"      ③ other = {others} → {'通过' if pass3 else '【丢弃】other 为空'}")
        w(f"      ④ 窗口内可渲染条目 {len(cand)} 条（上界） → "
          f"{'可能保留' if pass4_upper else '【丢弃】events 为空'}")
        if lvl not in NEG and pass2:
            w(f"      ②b level 非负但有窗口内负向流 → 档位词会被改写成「旧怨」")
        if pass2 and pass3 and pass4_upper:
            _first = min((cl.date_key(d) for d, _x in cand), default=None)
            kept.append({"key": k, "houses": hs, "other": others, "level": lvl,
                         "rank": RANK.get("世仇" if lvl in NEG and lvl.endswith("feud")
                                          else ("旧怨" if lvl not in NEG else "?"), 0),
                         "n": len(cand), "first": _first,
                         "labels": [(_safe(_house_label, melt_part, h)) for h in others]})
        w(f"      ===> {verdict} {('；'.join(reason)) if reason else ''}")

    # ---------- (E) _merge_and_cap_feuds 的合并与上限 ----------
    hr(f"[E] _merge_and_cap_feuds 的合并与 5 家上限（用窗口内条数估算 weight/次序）  熔件={melt_name}")
    w(f"    通过 ①②③④ 的行 {len(kept)} 条；按下述排序取前 HOUSE_FEUDS_MAX=5：")
    for r in kept:
        w(f"      key={r['key']} level={r['level']!r} 对方标签={r['labels']} "
          f"窗口内条目={r['n']} 首条={r['first']}")
    w("")
    w("    说明：真实排序键 = (-level排名, -weight, -条数, 首条日期, house_label)；")
    w("    这里只用「窗口内条目数」当 weight 的近似，用于判断宁浦洪行是否有资格进前 5。")
    w("    最终保留 5 家（按标题）：托格力氏 / 鄂陵潘氏 / 宇文-朝阳氏 / 归善张氏 / 苻氏"
      "（见 output/洪氏2/洪光通(1236)_终传_1283_09_11.md:274-304）")


def _rank_probe(cache, chars):
    """cache 侧的旁证：两个洪氏 house 各自的成员数（说明游戏里是两个不同的 house）。"""
    hr("[F] 旁证：缓存里各洪氏 house 的成员（人物缓存字段 dynasty_house）")
    by_house = {}
    for cid, rec in chars.items():
        if not isinstance(rec, dict):
            continue
        h = rec.get("dynasty_house")
        if isinstance(h, int):
            by_house.setdefault(h, []).append(cid)
    main = [17066495]
    for h in sorted(by_house, key=lambda x: -len(by_house[x]))[:40]:
        nm = (chars.get(by_house[h][0]) or {}).get("house_name")
        if nm and "洪" in str(nm):
            w(f"    house {h}: 成员 {len(by_house[h])} 人  示例={by_house[h][:5]} "
              f"house_name={nm!r}")


if __name__ == "__main__":
    main()
