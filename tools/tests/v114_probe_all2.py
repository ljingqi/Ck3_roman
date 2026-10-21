# -*- coding: utf-8 -*-
"""v114 取证 II（一次熔件加载）：封圣日期的可行来源、枢机头衔的字号/地名、入赘子女的落点。

用法: & tools\\py.ps1 tools\\tests\\v114_probe_all2.py
输出: logs/v114/v114_all2.txt
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
OUT = os.path.join(ROOT, "logs", "v114_all2.txt")
_buf = []


def w(s=""):
    _buf.append(str(s))
    print(s)


def main():
    cache = json.load(io.open(os.path.join(DATA, f"player_{PID}.json"), encoding="utf-8"))
    names = os.path.join(DATA, "names.json")
    campaign = {}
    for fn in os.listdir(DATA):
        if not (fn.startswith("player_") and fn.endswith(".json") and ".tmp" not in fn):
            continue
        pid = fn[len("player_"):-len(".json")]
        try:
            c = json.load(io.open(os.path.join(DATA, fn), encoding="utf-8"))
        except Exception:
            continue
        if c.get("playthrough_id") == cache.get("playthrough_id"):
            campaign[int(pid)] = c
    w(f"载入熔件 …（{len(campaign)} 份同战役缓存）")
    melt = cl.load_melt(os.path.join(DATA, "melt_1155_01_01.json"))
    facts = F.build_facts(cache, melt, names, as_of=None, campaign=campaign or None)
    f = facts["_facts"]
    tree = facts.get("genealogy_tree") or {}
    nodes = {n["id"]: n for n in tree.get("nodes") or []}
    chars = cache.get("characters") or {}

    # ---------------- ③ canonization date sources ----------------
    w("\n==== ③ 封圣日期的可能来源 ====")
    mchars = (melt.get("characters") or {})
    if isinstance(mchars, dict) and "characters" in mchars:
        mchars = mchars.get("characters") or {}
    for cid in (44503, 45152, 84824, 16878235, 83995743):
        rec = mchars.get(str(cid)) or {}
        w(f"--- {cid} {f.name_or(cid)!r}  熔件角色键 = {sorted(rec.keys())}")
        for key in ("memory", "memories", "character_memory", "variables", "flags",
                    "trait_history", "traits", "dead_data", "alive_data"):
            if key in rec:
                w(f"    {key} = {json.dumps(rec[key], ensure_ascii=False)[:700]}")
        fid = f._faith_id(cid)
        ent = cl.faith_entry(melt, fid) or {}
        reg = ent.get("saints") or []
        w(f"    faith {fid} saints 原样 = {json.dumps(reg, ensure_ascii=False)[:500]}")
        if isinstance(reg, list):
            for e in reg:
                if isinstance(e, dict) and str(cid) in json.dumps(e):
                    w(f"    → 本人在注册表 = {json.dumps(e, ensure_ascii=False)}")
    w("\n-- 圣髑类artifact（模板 pam_saint_relic_template） --")
    arts = ((melt.get("artifacts") or {}).get("artifacts") or {})
    n_hit = 0
    for aid, a in arts.items():
        if not isinstance(a, dict):
            continue
        blob = json.dumps(a, ensure_ascii=False)
        if "pam_saint_relic" in blob or "saint_relic" in blob:
            n_hit += 1
            if n_hit <= 12:
                w(f"    {aid}: created={a.get('creation_date')!r} tmpl={a.get('template')!r} "
                  f"name={f._artifact_name(a.get('name'))!r} owner={a.get('owner')!r}")
    w(f"    共 {n_hit} 件")
    w("-- 熔件里其他 saint 痕迹 --")
    for cid in (44503, 45152, 84824, 16878235, 83995743):
        blob = json.dumps(mchars.get(str(cid)) or {}, ensure_ascii=False)
        for pat in ("canoniz", "saint", "封圣", "圣"):
            if pat in blob:
                i = blob.find(pat)
                w(f"    {cid} 含 {pat!r}: …{blob[max(0,i-120):i+160]}…")
                break

    # ---------------- ⑤ cardinal titles ----------------
    w("\n==== ⑤ 枢机头衔 ====")
    for cid in (98860, 50426865, 67183293, 83949596):
        rec = mchars.get(str(cid)) or {}
        crec = chars.get(str(cid)) or {}
        death = (crec.get("death") or {}).get("date") or (rec.get("dead_data") or {}).get("date")
        w(f"--- {cid} {f.name_or(cid)!r} 卒={death!r}")
        w(f"    缓存 dead_data = {json.dumps(crec.get('dead_data'), ensure_ascii=False)[:300]}")
        try:
            hi = f._hold_intervals(cid, f._anchor_date(cid, death) if death else None)
        except Exception as e:                                    # noqa: BLE001
            hi = {"ERR": repr(e)}
        w(f"    _hold_intervals = {json.dumps({str(k): v for k, v in hi.items()}, ensure_ascii=False)[:900]}")
        for tid in (hi.keys() if isinstance(hi, dict) else []):
            t = f._lt.get(str(tid)) or {}
            key = t.get("key") or ""
            w(f"    tid {tid}: key={key!r} clerical_elector={t.get('clerical_elector')!r} "
              f"capital={t.get('capital')!r}")
            w(f"        title_name_data={json.dumps(t.get('title_name_data'), ensure_ascii=False)}")
            w(f"        name_at_date(死日)={f._name_at_date(tid, death)!r} "
              f"base={f.title_base_name(tid)!r} loc={L.loc(f.table, key)!r}")
            w(f"        _is_cardinal={f._is_cardinal_title(tid)} "
              f"_last_title_place={f._last_title_place(cid, key, date=death)!r}")
        for d in (death, None):
            try:
                w(f"    official_title({d!r}) = {f.official_title(cid, d)!r}")
                w(f"    person_label({d!r})   = {f.person_label(cid, d, 'full')!r}")
            except Exception as e:                                # noqa: BLE001
                w(f"    official_title({d!r}) ERR {e!r}")

    # ---------------- ① uxorilocal placement ----------------
    w("\n==== ① 入赘婚与子女落点 ====")
    w("-- 图上的配珠（spouse_of 非空者） --")
    for x, n in sorted(nodes.items()):
        if n.get("spouse_of"):
            rec = chars.get(str(x)) or {}
            fam = f.merge_spouse_latch(rec.get("family") or {}, f.as_of)
            kids = [k for k in (fam.get("child") or []) if isinstance(k, int)]
            w(f"    {x} {n['name']!r} word={n['spouse_word']!r} 配于 {n['spouse_of']} "
              f"({(nodes.get(n['spouse_of']) or {}).get('name')!r}) 记录子女={len(kids)} "
              f"{[f.name_or(k) for k in kids][:6]}")
    w("-- 每个图节点的父母与落点 --")
    miss = []
    for x, n in sorted(nodes.items()):
        rec = chars.get(str(x)) or {}
        fam = rec.get("family") or {}
        fa = [y for y in (fam.get("father") or []) if isinstance(y, int)]
        mo = [y for y in (fam.get("mother") or []) if isinstance(y, int)]
        fa_t = [y for y in fa if y in nodes]
        mo_t = [y for y in mo if y in nodes]
        if not fa_t and not mo_t:
            continue
        par = n.get("parent")
        why = []
        mat = None
        if fa_t and mo_t:
            mat = f.is_matrilineal(fa_t[0], mo_t[0], before=f.as_of)
        if par is not None:
            why.append("父" if par in fa_t else ("母" if par in mo_t else "?"))
        else:
            why.append("无父")
        # children of the mother that hang elsewhere
        if mo_t:
            for k in (fam.get("child") or []):
                pass
        if par is not None and par in mo_t and fa_t:
            miss.append((x, "母", fa_t[0], mo_t[0], mat))
        w(f"    {x} {n['name']!r}(gen{n['gen']},{n['note']!r}) 父={[f.name_or(y) for y in fa_t]} "
          f"母={[f.name_or(y) for y in mo_t]} → parent={par} ({'、'.join(why)}) "
          f"matrilineal={mat} kids={len(n['kids'])}")
    w(f"-- 挂在母下且父也在图上的节点 = {len(miss)}: {miss}")

    # mother's recorded children vs tree kids
    w("-- 记录有子女但图上无子女的人（父母一方在图上的女性） --")
    for x, n in sorted(nodes.items()):
        rec = chars.get(str(x)) or {}
        fam = f.merge_spouse_latch(rec.get("family") or {}, f.as_of)
        kids = [k for k in (fam.get("child") or []) if isinstance(k, int)]
        if kids and not n.get("kids") and rec.get("female"):
            w(f"    {x} {f.name_or(x)!r} note={n['note']!r} 记录子女={[f.name_or(k) for k in kids]}")
    w("-- 记录有子女但完全不在图上的人 --")
    for x, n in sorted(nodes.items()):
        rec = chars.get(str(x)) or {}
        fam = f.merge_spouse_latch(rec.get("family") or {}, f.as_of)
        kids = [k for k in (fam.get("child") or []) if isinstance(k, int)]
        gone = [k for k in kids if k not in nodes]
        if gone and rec.get("female"):
            w(f"    {x} {f.name_or(x)!r} note={n['note']!r} 不在图上的子女={[f.name_or(k) for k in gone]}")

    io.open(OUT, "w", encoding="utf-8").write("\n".join(_buf))
    print("\n写出:", OUT)


if __name__ == "__main__":
    main()
