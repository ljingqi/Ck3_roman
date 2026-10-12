"""v122 第1问取证: 178021 在 1119/1120 两档里到底在哪个人物桶, 死没死, 死在哪天。

只读熔件的 living / dead_unprunable / characters.dead_prunable 三段 (load_melt_section),
不整载熔件。用法: & tools\py.ps1 tools\tests\v122_probe_death.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cache_lib as cl  # noqa: E402

DATA = r"output\田所2\data"
CIDS = ["178021", "218169054"]
OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


def where(cid):
    """(bucket, record) for cid across the three character buckets."""
    hits = []
    for name, getter in (("living", cl._living),
                         ("dead_unprunable", cl._dead_unprunable),
                         ("characters.dead_prunable", cl._dead_prunable)):
        yield name, getter


for year in (1119, 1120):
    mp = os.path.join(DATA, f"melt_{year}_01_01.json")
    if not os.path.isfile(mp):
        P(f"### {year}: 熔件缺失 {mp}")
        continue
    P(f"### melt_{year}_01_01.json")
    pc = cl.load_melt_section(mp, "played_character") or {}
    lg = [(e.get("character"), e.get("date")) for e in (pc.get("legacy") or [])
          if isinstance(e, dict)]
    P(f"  played_character.legacy 末三: {lg[-3:]}")
    P(f"  played_character 顶层键: {sorted(pc.keys())}")
    living = cl.load_melt_section(mp, "living") or {}
    dead_un = cl.load_melt_section(mp, "dead_unprunable") or {}
    chars = cl.load_melt_section(mp, "characters") or {}
    dp = (chars.get("dead_prunable") or {}) if isinstance(chars, dict) else {}
    P(f"  桶规模: living={len(living)} dead_unprunable={len(dead_un)} dead_prunable={len(dp)}")
    for cid in CIDS:
        P(f"  -- 角色 {cid}")
        P(f"     living: {'有' if cid in living else '无'}")
        P(f"     dead_unprunable: {'有' if cid in dead_un else '无'}")
        P(f"     dead_prunable: {'有' if cid in dp else '无'}")
        for bucket, rec in (("living", living.get(cid)), ("dead_unprunable", dead_un.get(cid)),
                            ("dead_prunable", dp.get(cid))):
            if not isinstance(rec, dict):
                continue
            dd = rec.get("dead_data") or {}
            P(f"     [{bucket}] name={cl.name_zh(rec)!r} death_date={rec.get('death_date')!r} "
              f"dead_data.date={dd.get('date')!r} reason={dd.get('reason')!r} "
              f"killer={dd.get('killer')!r}")
            dom = ((rec.get("landed_data") or {}).get("domain") or [])
            titles = rec.get("titles") or []
            P(f"     [{bucket}] domain={len(dom)} 枚 titles={len(titles) if isinstance(titles, list) else titles!r} "
              f"modifier_names={cl._char_modifier_names(rec)}")
            P(f"     [{bucket}] 顶层键样例: {sorted(rec.keys())[:40]}")
            P(f"     [{bucket}] 是否兼具 death 字段: alive_flag={rec.get('alive')!r} "
              f"dead_flag={rec.get('dead')!r}")
    P()

open(r"logs\v122_probe_death.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122_probe_death.txt")
