"""v123 第4问取证: 为什么 d_munster 在「历任」行写成「芒斯特亲王国」而「直辖」行写成「芒斯特大酋邦」。

用 波特 战役 哈利·波特(38950) 的缓存 + melt_878_01_01 构造 Facts(as_of=878.1.1), 逐层打印:
  - f.title(612) 与 f.title(612, date=...) 的三段返回
  - _title_tier_word / _flavor_key / _gov_for_word / _holder_at_or_now 的取词链
  - official_title 与 domain 列表
  - 影响力/功勋/威望/虔诚 四种货币在存档里的值与政体 (v123 第5问)
用法: & tools\py.ps1 tools\tests\v123_probe_munster.py
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402
import localization as L  # noqa: E402

DATA = os.path.join(ROOT, "output", "波特", "data")
PID = 38950
AS_OF = "878.1.1"
MELT = "melt_878_01_01.json"
TID = 612
LOG = os.path.join(ROOT, "logs", "v123_probe_munster.txt")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def main():
    cache = json.load(open(os.path.join(DATA, f"player_{PID}.json"), encoding="utf-8"))
    melt = cl.load_melt(os.path.join(DATA, MELT))
    names = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, melt, names, as_of=AS_OF, decade=None)
    t = f._lt.get(str(TID)) or {}
    w(f"d_munster(612): key={t.get('key')!r} name_data={t.get('title_name_data')!r}")
    w(f"  eff_rank={f._eff_rank(TID)} kind={f.title_kind(TID)!r} base={f.title_base_name(TID)!r}")
    w("")
    for d in (None, "867.1.1", "873.10.10", "878.1.1"):
        w(f"--- date={d!r}")
        holder = f._holder_at_or_now(t, TID, d)
        w(f"  _holder_at_or_now = {holder!r}")
        gov = f._gov_for_word(holder, TID, d)
        w(f"  _gov_for_word = {gov!r}")
        w(f"  _is_independent(holder) = {f._is_independent(holder, d)!r}")
        ce = f._culture_entry(holder, d) if holder is not None else {}
        w(f"  culture name_list = {ce.get('name_list')!r} template={ce.get('culture_template')!r}")
        fk = f._flavor_key("title", "duchy", holder, tid=TID, gov=gov, date=d)
        w(f"  _flavor_key(title,duchy) = {fk!r} -> loc {L.loc(f.table, fk)!r}")
        w(f"  _title_tier_word = {f._title_tier_word('duchy', holder, TID, gov, d)!r}")
        w(f"  title() = {f.title(TID, date=d)!r}")
        w(f"  _tier_word_at = {f._tier_word_at(TID, gov, independent=bool(f._is_independent(holder, d)), cid=holder, date=d)!r}")
    w("")
    w(f"title() no date = {f.title(TID)!r}")
    w(f"L.tier_word(table,'tribal_government','duchy') = {L.tier_word(f.table, 'tribal_government', 'duchy')!r}")
    w(f"L.tier_word(table,'','duchy') = {L.tier_word(f.table, '', 'duchy')!r}")
    for k in ("duchy_tribal", "duchy_clan", "duchy_feudal", "duchy_feudal_independent",
              "duchy_feudal_prince_independent", "title_principality", "county_tribal"):
        w(f"  loc[{k}] = {L.loc(f.table, k)!r}")
    w("")
    w(f"official_title(38950) = {f.official_title(PID)!r}")
    w(f"official_title(38950, 873.10.10) = {f.official_title(PID, '873.10.10')!r}")
    w(f"_character_government(38950, 878.1.1) = {f._character_government(PID, '878.1.1')!r}")
    rec = f._chars.get(str(PID)) or {}
    ld = rec.get("landed_data") or {}
    w(f"landed government = {ld.get('government')!r} domain={ld.get('domain')!r}")
    fam = cache.get("characters") or {}
    ad = (fam.get(str(PID)) or {}).get("ad") or (fam.get(str(PID)) or {}).get("attributes") or {}
    w(f"cache char keys = {sorted((fam.get(str(PID)) or {}).keys())[:40]}")
    w(f"cache char 'ad' = {json.dumps(ad, ensure_ascii=False)[:600]}")
    c0 = f._chars.get(str(PID)) or {}
    w("melt char currency-ish fields:")
    for key in ("piety", "prestige", "influence", "merit", "herd", "currency", "provisions"):
        if key in c0:
            w(f"  melt[{key}] = {json.dumps(c0.get(key), ensure_ascii=False)[:300]}")
    w(f"  melt char keys = {sorted(c0.keys())}")
    w("")
    w("--- 名册两三个人的房名/亲属关系源")
    for cid in (38950, 13740, 16113):
        try:
            dn, hn = f._house_names_at(cid, AS_OF)
        except Exception as e:                                       # noqa: BLE001
            dn, hn = f"ERR {e}", ""
        w(f"  {cid}: dynasty={dn!r} house={hn!r} house_label={f._house_label_at(cid, AS_OF)!r} "
          f"name_with_regnal={f.name_with_regnal(cid, AS_OF)!r} nickname={f.nickname(cid)!r} "
          f"traits={f.traits_sentence(cid, public=True)!r}")
        w(f"    person_label(full) = {f.person_label(cid, AS_OF, 'full')!r}")


main()
io.open(LOG, "w", encoding="utf-8").write("\n".join(buf))
print("written", LOG)
