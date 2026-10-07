# -*- coding: utf-8 -*-
"""v114 取证（一次熔件加载，回答五个问题）：

  ① 入赘婚的女子与其子女在家谱图上的落点（子女挂在父还是母、配偶是否入图、红线是否断）
  ② 各代传主的 full 称谓（世系头部该写「头衔+名」还是「前头衔，当前头衔+名」）
  ③ 封圣日期（saint 特质的 from / faiths.saints 注册表 / 记忆）
  ④ 王的世次号（爱尔兰至高王耀国二世）
  ⑤ 枢机头衔的地名（d_cd_* / 动态枢机职的名称）

用法: & tools\\py.ps1 tools\\tests\\v114_probe_all.py
输出: logs/v114_all.txt（UTF-8）并同时打印
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402
import localization as L  # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
PID = 207044
OUT = os.path.join(ROOT, "logs", "v114_all.txt")
_buf = []


def w(s=""):
    _buf.append(str(s))
    print(s)


def main():
    cache = json.load(io.open(os.path.join(DATA, f"player_{PID}.json"), encoding="utf-8"))
    names = os.path.join(DATA, "names.json")
    campaign = {}
    for fn in os.listdir(DATA):
        m = None
        if fn.startswith("player_") and fn.endswith(".json") and ".tmp" not in fn:
            m = fn[len("player_"):-len(".json")]
        if not m:
            continue
        try:
            c = json.load(io.open(os.path.join(DATA, fn), encoding="utf-8"))
        except Exception:
            continue
        if c.get("playthrough_id") == cache.get("playthrough_id"):
            campaign[int(m)] = c
    melt_path = os.path.join(DATA, "melt_1155_01_01.json")
    w(f"载入熔件 {os.path.basename(melt_path)} …")
    melt = cl.load_melt(melt_path)
    facts = F.build_facts(cache, melt, names, as_of=None, decade=None,
                          campaign=campaign or None)
    f = facts["_facts"]
    tree = facts.get("genealogy_tree") or {}
    nodes = {n["id"]: n for n in tree.get("nodes") or []}
    chain = tree.get("chain") or []

    # ---- ②④ each generation's appellation on its own day ----
    w("\n==== ②④ 逐代传主：成稿当日的称谓 ====")
    for c in chain:
        cid = c["id"]
        date = f.as_of if c["i"] == len(chain) else (F._gen_end_date(f, cid) or f.as_of)
        w(f"--- {c['i']} {cid} {c['name']}  （世次 {c['gen']}，读于 {date}）")
        w(f"    name_or            = {f.name_or(cid)!r}")
        w(f"    name_with_regnal   = {f.name_with_regnal(cid, date)!r}")
        w(f"    person_label full  = {f.person_label(cid, date, 'full')!r}")
        w(f"    person_label brief = {f.person_label(cid, date)!r}")
        w(f"    kin_label          = {f.kin_label(cid)!r}")
        w(f"    official_title     = {f.official_title(cid, date)!r}")
        w(f"    prince_title       = {f.prince_title(cid, date)!r}")
        try:
            w(f"    primary_title_at   = {f._primary_title_at(cid, as_of=date)!r}")
        except Exception as e:                                    # noqa: BLE001
            w(f"    primary_title_at   ERR {e!r}")
        try:
            w(f"    former_high_title  = {f._former_high_title(cid, f._anchor_date(cid, date))!r}")
        except Exception as e:                                    # noqa: BLE001
            w(f"    former_high_title  ERR {e!r}")

    # ---- ③ saint / canonization ----
    w("\n==== ③ 封圣：saint 特质的区间、注册表、记忆 ====")
    th_all = {}
    for cid in [c["id"] for c in chain] + sorted(nodes):
        rec = (cache.get("characters") or {}).get(str(cid)) or {}
        th = (rec.get("trait_history") or {}).get("saint") or []
        if th or f._in_saint_register(cid):
            th_all[cid] = th
    w(f"链上/图上带 saint 特质或注册表的人：{len(th_all)}")
    for cid, th in sorted(th_all.items()):
        n = nodes.get(cid) or {}
        w(f"--- {cid} {f.name_or(cid)!r} gen={n.get('gen')} note={n.get('note')!r}")
        w(f"    trait_history['saint'] = {json.dumps(th, ensure_ascii=False)}")
        w(f"    in_saint_register      = {f._in_saint_register(cid)}")
        w(f"    saint_prefix(as_of)    = {f._saint_prefix(cid)!r}")
        w(f"    faith_id / tags        = {f._faith_id(cid)!r} / {f._faith_tags(cid, None)!r}")
        rec = (cache.get("characters") or {}).get(str(cid)) or {}
        mem = rec.get("memories") or []
        hits = [m for m in mem if isinstance(m, dict)
                and any(k in json.dumps(m, ensure_ascii=False).lower()
                        for k in ("saint", "canoniz", "圣", "封圣"))]
        if hits:
            w(f"    记忆(含圣/封圣) = {json.dumps(hits, ensure_ascii=False)[:900]}")
        # any raw key mentioning canonization in the character block
        raw = json.dumps(rec, ensure_ascii=False)
        for pat in ("canoniz", "封圣", "pam_canon"):
            if pat in raw:
                i = raw.find(pat)
                w(f"    原文含 {pat!r}: …{raw[max(0,i-160):i+240]}…")

    # ---- ⑤ cardinal titles ----
    w("\n==== ⑤ 枢机头衔的地名 ====")
    card_ids = [cid for cid, rec in (facts.get("characters") or {}).items()
                if isinstance(rec, dict) and "枢机" in (rec.get("label") or "")]
    card_ids += [n["id"] for n in (tree.get("nodes") or [])
                 if "枢机" in (n.get("label") or "")]
    for cid in sorted(set(card_ids)):
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            continue
        date = F._gen_end_date(f, cid) or f.as_of
        tier, tid = f._primary_title_at(cid, as_of=date) if True else (None, None)
        t = (f._lt.get(str(tid)) or {})
        key = t.get("key") or ""
        w(f"--- {cid} {f.name_or(cid)!r} 读于 {date}")
        w(f"    label            = {f.person_label(cid, date, 'full')!r}")
        w(f"    primary (tier,tid)= {tier!r},{tid!r} key={key!r}")
        w(f"    _is_cardinal     = {f._is_cardinal_title(tid)}")
        w(f"    clerical_elector = {t.get('clerical_elector')!r} landless={t.get('landless')!r}")
        w(f"    title_name_data  = {json.dumps(t.get('title_name_data'), ensure_ascii=False)}")
        w(f"    name_at_date     = {f._name_at_date(tid, date)!r}")
        w(f"    title_base_name  = {f.title_base_name(tid)!r}")
        w(f"    _title_display_name = {f._title_display_name(tid, date, cid=cid)!r}")
        w(f"    loc(key)         = {L.loc(f.table, key)!r}")
        w(f"    official_title   = {f.official_title(cid, date)!r}")

    # ---- ① uxorilocal ----
    w("\n==== ① 入赘（matrilineal）婚与其子女 ====")
    blood_ids = set(nodes)
    seen_pairs = set()
    for x in sorted(blood_ids):
        rec = (cache.get("characters") or {}).get(str(x)) or {}
        fam = f.merge_spouse_latch(rec.get("family") or {}, f.as_of)
        cands = []
        for k in ("primary_spouse", "spouse", "concubine", "former_spouses", "former_concubines"):
            cands += [y for y in (fam.get(k) or []) if isinstance(y, int)]
        for y in sorted(set(cands)):
            if y == x or y in seen_pairs:
                continue
            seen_pairs.add((x, y))
            seen_pairs.add((y, x))
            mat = f.is_matrilineal(x, y, before=f.as_of)
            kids = f._common_children(x, y, before=f.as_of)
            if mat or (kids and (x in blood_ids or y in blood_ids)):
                xn, yn = nodes.get(x) or {}, nodes.get(y) or {}
                w(f"--- {x} {f.name_or(x)!r}(note={xn.get('note')!r},在图上={bool(xn)}) "
                  f"× {y} {f.name_or(y)!r}(note={yn.get('note')!r},在图上={bool(yn)}) "
                  f"matrilineal={mat}")
                w(f"    共同子女 = {[(k, f.name_or(k), (nodes.get(k) or {}).get('note'),
                                     (nodes.get(k) or {}).get('parent')) for k in kids]}")
                w(f"    note    = {f.marriage_lineality_note(x, y, before=f.as_of)!r}")

    io.open(OUT, "w", encoding="utf-8").write("\n".join(_buf))
    print("\n写出:", OUT)


if __name__ == "__main__":
    main()
