"""v122 第3问取证四: 用程序自己的代码追「新罗乡绅」这条标签是怎么拼出来的。

用 岚珠(67220811) 的缓存 + melt_1083_01_01 构造 Facts(as_of=1082.2.16), 逐层打印
金元惠(16912738) 的 primary title / rank / estate 判定 / 官职词。
用法: & tools\py.ps1 tools\tests\v122_probe_label.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

DATA = os.path.join(ROOT, "output", "田所2", "data")
PID = 67220811
CID = 16912738
AS_OF = "1082.2.16"
MELT = "melt_1083_01_01.json"
LOG = os.path.join(ROOT, "logs", "v122_probe_label.txt")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def main():
    cache = json.load(open(os.path.join(DATA, f"player_{PID}.json"), encoding="utf-8"))
    melt = cl.load_melt(os.path.join(DATA, MELT))
    names = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, melt, names, as_of=AS_OF, decade=None)
    rec = f._chars.get(str(CID)) or {}
    w(f"角色 {CID}: name={F.__dict__.get('L') and ''}{rec.get('name_full')} "
      f"dead={bool(rec.get('dead_data') or rec.get('death'))}")
    w(f"  campaign 里有没有该角色缓存: {bool(f.campaign.get(CID)) if getattr(f, 'campaign', None) else None}")

    anchor = f._anchor_date(CID, None)
    w(f"_anchor_date(None) = {anchor!r}")
    w(f"_has_current_landed_title = {f._has_current_landed_title(CID, anchor)}")
    tier, tid = f._primary_title_at(CID, as_of=anchor)
    w(f"_primary_title_at(as_of={anchor}) -> tier={tier!r} tid={tid!r}")
    if tid is not None:
        t = f._lt.get(str(tid)) or {}
        w(f"   title key={t.get('key')!r} holder={t.get('holder')!r} "
          f"eff_rank={f._eff_rank(tid)} kind={f.title_kind(tid)!r} "
          f"is_estate={f._is_estate_title(tid)} base={f.title_base_name(tid)!r} "
          f"display={f._title_display_name(tid, anchor, cid=CID)!r}")
    w("")
    w("他的全部头衔 (来自 _hold_intervals / 缓存 landed_data):")
    ivs = f._hold_intervals(CID, anchor)
    for t_id, segs in sorted(ivs.items(), key=lambda kv: -f._eff_rank(kv[0])):
        t = f._lt.get(str(t_id)) or {}
        w(f"  {t_id} key={t.get('key')!r} rank={f._eff_rank(t_id)} kind={f.title_kind(t_id)!r} "
          f"estate={f._is_estate_title(t_id)} base={f.title_base_name(t_id)!r} segs={segs}")

    w("")
    w(f"culture_template = {f.culture_template(CID)!r}   female={f._is_female(CID)}")
    w(f"gov_for_word(tid={tid}) = {f._gov_for_word(CID, tid, anchor)!r}")
    w(f"_is_independent = {f._is_independent(CID, anchor)!r}")
    w(f"_estate_holder_word = {f._estate_holder_word(CID)!r}")
    if tid is not None:
        fw = f._flavor_key("character", tier, CID, tid=tid, gender="male",
                           gov=f._gov_for_word(CID, tid, anchor), date=anchor)
        w(f"_flavor_key(character, tier={tier!r}, gov, ...) = {fw!r}")
    w(f"official_title = {f.official_title(CID, None)!r}")
    w(f"prince_title = {f.prince_title(CID, anchor)!r}")
    w(f"event_name = {f.event_name(CID, None)!r}")
    w(f"person_label('event') = {f.person_label(CID, None, 'event')!r}")
    # 第二个例子: 金护 (新罗公子)
    for other in (16912738,):
        pass

    # 直接看 localization 里几个 estate 词的取值
    import localization as L  # noqa: E402
    for k in ("estate_holder_male_korean", "estate_holder_female_korean",
              "estate_holder_male_japanese", "celestial_estate_holder_male",
              "game_concept_house_head", "king_male_korean", "king", "prince_male_korean"):
        w(f"loc[{k}] = {L.loc(f.table, k)!r}")


main()
open(LOG, "w", encoding="utf-8").write("\n".join(buf))
print(f"written {LOG}")
