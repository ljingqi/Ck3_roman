# -*- coding: utf-8 -*-
"""v119 probe: the newest save of a campaign — the same-dynasty rulers roster (epilogue part 2) and
the holder word of a landless-adventurer leader (the 世系 head-line bug).

Loads the newest cache + the newest melt once (~175 MB + ~453 MB) and prints raw inputs, the current
`official_title` / `person_label` output, the title keys/ranks, the camp purpose and the roster.
Read-only apart from logs/v119/v119_roster_<folder>.{txt,json}.

Usage:  python tools/tests/v119_probe_roster.py [家族文件夹] [--campaign] [--as-of Y.M.D]
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import cache_lib as cl              # noqa: E402
import facts as F                   # noqa: E402
import llm                          # noqa: E402
import pipeline as P                # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "洪氏2"
WITH_CAMPAIGN = "--campaign" in sys.argv
AS_OF = None
for i, a in enumerate(sys.argv):
    if a == "--as-of" and i + 1 < len(sys.argv):
        AS_OF = sys.argv[i + 1]


def main():
    cfg = llm.load_config()
    out_dir = os.path.join(cfg.get("output_dir", ""), FOLDER)
    data_dir = os.path.join(out_dir, "data")
    index = P.load_caches_index(data_dir)
    # load_caches_index unwraps the {"version", "files"} envelope into {filename: entry}
    metas = [e.get("meta") or {} for e in index.values()]
    metas = [m for m in metas if m.get("player_id") is not None]
    if not metas:
        raise SystemExit(f"{FOLDER}: 索引里没有缓存")
    newest = max(metas, key=lambda m: cl.date_key(str(m.get("last_date"))))
    pid = newest["player_id"]
    as_of = AS_OF or newest["last_date"]
    cache_path = os.path.join(data_dir, f"player_{pid}.json")
    print(f"== {FOLDER}：最新缓存 player_{pid}.json  last={newest['last_date']}  "
          f"as_of={as_of}  战役={newest['playthrough_id']}  人数={newest.get('n_characters')}",
          flush=True)

    t0 = time.time()
    cache = cl.load_cache(cache_path)
    melt_path = P.melt_file_in(cfg, FOLDER, str(newest["last_date"]), pid)
    print(f"   缓存 {time.time() - t0:.1f}s -> {os.path.basename(cache_path)}"
          f"；熔件 {os.path.basename(melt_path or '')}", flush=True)
    t1 = time.time()
    melt = P.load_latest_melt(cfg, cache)
    if melt is None:
        raise SystemExit("无可用 melt")
    print(f"   熔件载入 {time.time() - t1:.1f}s -> {os.path.basename(melt_path or '')}", flush=True)
    campaign = P._campaign_caches(cfg, cache) if WITH_CAMPAIGN else None
    if campaign is not None:
        print(f"   战役缓存 {len(campaign)} 份", flush=True)
    t2 = time.time()
    import biography as B
    facts = F.build_facts(cache, melt, names_path=B._names_path(cfg, cache),
                          as_of=as_of, cfg=cfg, campaign=campaign)
    f = facts["_facts"]
    print(f"   Facts 构建 {time.time() - t2:.1f}s", flush=True)

    report = {"folder": FOLDER, "player_id": pid, "as_of": as_of,
              "playthrough_id": newest["playthrough_id"], "titles": {}, "roster": []}

    # ---- A. the landless-adventurer holder word (世系 head-line bug) ----
    print("\n== A. 无地冒险者持衔词 ==")
    for cid in (67408343, pid):
        rec = (cache.get("characters") or {}).get(str(cid)) or {}
        dead = rec.get("dead_data") or {}
        landed = rec.get("landed") or {}
        ivs = f._hold_intervals(cid, as_of) or {}
        held = []
        for tid, iv in sorted(ivs.items()):
            key = (f._lt.get(str(tid)) or {}).get("key") or ""
            held.append({"tid": tid, "key": key, "rank": f._eff_rank(tid),
                         "kind": f.title_kind(tid),
                         "seg": [[g, l] for (g, l, _lt) in iv]})
        tier, tid = f._primary_title_at(cid, as_of=as_of)
        row = {
            "cid": cid,
            "name": f.name_or(cid),
            "house": rec.get("house_name"), "dynasty": rec.get("dynasty_name"),
            "dead_data_flavor": dead.get("flavor"),
            "dead_data_domain": dead.get("domain"),
            "landed_government": landed.get("government"),
            "landed_laws": [x for x in (landed.get("laws") or [])
                            if str(x).startswith("camp_purpose_")],
            "camp_purpose_at": f._camp_purpose_at(cid, as_of),
            "camp_holder_word": f._camp_holder_word(cid, as_of),
            "camp_holder_word_default": f._camp_holder_word_default(),
            "primary": {"tier": tier, "tid": tid},
            "held": held,
            "official_title": f.official_title(cid, as_of),
            "label_full": f.person_label(cid, as_of, "full"),
            "label_brief": f.person_label(cid, as_of, "brief"),
            "titles_held": f.held_titles(cid),
        }
        if tid is not None:
            row["title_kind"] = f.title_kind(tid)
            row["title_key"] = (f._lt.get(str(tid)) or {}).get("key")
            row["title_name"] = f._title_display_name(tid, as_of, cid=cid)
            row["title_display"] = f.title(tid, as_of)
            row["title_base"] = f.title_base_name(tid)
            row["camp_tier_word"] = f._camp_tier_word(tid)
            row["landless_word"] = f._landless_holder_word(cid, tid, as_of)
        anchor = f._anchor_date(cid, as_of)
        row["anchor"] = anchor
        row["primary_at_anchor"] = list(f._primary_title_at(cid, as_of=anchor))
        row["unlanded_text"] = (f._unlanded_office_text(cid, tid, anchor)
                                if tid is not None else "")
        report["titles"][str(cid)] = row
        print(f"  -- {cid} {row['name']}（{row['house']}／{row['dynasty']}）")
        print(f"     dead_data.flavor={row['dead_data_flavor']!r}  "
              f"landed.gov={row['landed_government']!r}  {row['landed_laws']}")
        print(f"     营地类别={row['camp_purpose_at']!r}  持衔词={row['camp_holder_word']!r}"
              f"（默认 {row['camp_holder_word_default']!r}）")
        print(f"     主衔(按as_of) tier={tier!r} tid={tid!r} key={row.get('title_key')!r} "
              f"kind={row.get('title_kind')!r} 名={row.get('title_name')!r}"
              f" / title()={row.get('title_display')!r}")
        print(f"     anchor={anchor} 主衔(按anchor)={row['primary_at_anchor']}  "
              f"office_text={row['unlanded_text']!r}")
        print(f"     official_title={row['official_title']!r}")
        print(f"     person_label(full)={row['label_full']!r}  (brief)={row['label_brief']!r}")
        print(f"     titles_held={row['titles_held']!r}")

    # ---- B. same-dynasty rulers at as_of ----
    print("\n== B. 同宗族当今统治者 ==")
    my_house = f._house_of_cid(pid)
    my_dyn = cache.get("dynasty_id") or (cl.dynasty_id_of(melt, my_house) if my_house else None)
    print(f"  传主 {pid} 房={my_house} 宗族={my_dyn} ({cl.dynasty_name_zh(melt, my_dyn) if my_dyn else ''})")
    chars = f._chars
    mine, alive = [], 0
    for key, rec in chars.items():
        cid = int(key)
        if f._dynasty_of_cid(cid) != my_dyn:
            continue
        mine.append(cid)
        if not f._alive_at(cid, as_of):
            continue
        alive += 1
        tier, tid = f._primary_title_at(cid, as_of=as_of)
        landed = bool(tid is not None and f._is_landed_title(tid))
        item = {"cid": cid, "label": f.person_label(cid, as_of, "full"),
                "house": f._house_label_at(cid, as_of),
                "alive": True, "tier": tier, "landed": landed,
                "title": f.title(tid, as_of) if tid is not None else "",
                "title_kind": f.title_kind(tid) if tid is not None else "",
                "rank": f._eff_rank(tid) if tid is not None else None,
                "seat": f.artifact_home(cid, as_of),
                "kin": f.kin_word_for(cid, pid) if cid != pid else "传主",
                "gen_delta": f.generation_delta(pid, cid) if cid != pid else 0,
                "independent": f._is_independent(cid, as_of)}
        report["roster"].append(item)
    landed_rows = [r for r in report["roster"] if r["landed"] and r["rank"] >= 2]
    landed_rows.sort(key=lambda r: (-(r["rank"] or 0), r["kin"] or ""))
    print(f"  宗族成员(熔件侧)={len(mine)}  存活={alive}  有地(县级及以上)={len(landed_rows)}")
    for r in landed_rows:
        print(f"   [{r['rank']}] {r['label']}  《{r['title']}》  治所={r['seat']}  "
              f"房={r['house']}  亲属={r['kin']}  独立={r['independent']}")
    others = [r for r in report["roster"] if not (r["landed"] and r["rank"] >= 2)]
    print(f"  -- 其余在世同宗 {len(others)} 人（前 20）")
    for r in others[:20]:
        print(f"   [{r['rank']}] {r['label']}  kind={r['title_kind']} 《{r['title']}》 "
              f"治所={r['seat']} 亲属={r['kin']}")

    report["dynasty"] = {"id": my_dyn, "name": cl.dynasty_name_zh(melt, my_dyn) if my_dyn else "",
                         "house": my_house, "members": len(mine), "alive": alive,
                         "landed_rows": len(landed_rows)}
    base = os.path.join(ROOT, "logs", f"v119_roster_{FOLDER}")
    json.dump(report, open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n已写", base + ".json")


if __name__ == "__main__":
    main()
