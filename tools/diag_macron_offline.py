# -*- coding: utf-8 -*-
"""读 tools/out_macron 的落盘产物做离线分析（不载熔件）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_macron_offline.py [模式]
模式：tracks | prison | child | find <子串>
"""
import io
import json
import os
import re
import sys

OUT = r"D:\Roman\tools\out_macron"


def j(name):
    with io.open(os.path.join(OUT, name), encoding="utf-8") as fp:
        return json.load(fp)


def tracks():
    g = j("game_trait_tracks.json")
    print(f"带 tracks 的特质 {len(g)} 个：")
    for k, v in g.items():
        tr = {t: list(lv.keys()) for t, lv in v["tracks"].items()}
        lvl = v.get("category")
        print(f"  {k}  category={lvl}")
        for t, ks in tr.items():
            print(f"      {t}: {ks}")
    tc = j("track_chars.json")
    print(f"\n持有带轨道特质的角色 {len(tc)} 人")
    # 对齐关系：traits 与 trait_xp_amounts
    for cid, v in list(tc.items())[:40]:
        tr = v["traits"]
        xp = v["trait_xp_amounts"] or []
        tk = [i for i, t in enumerate(tr) if t in g]
        print(f"  {cid} {v['name']}: traits({len(tr)}) xp({len(xp)}) "
              f"tracked_at={tk} tracked={v['tracked']} xp={xp}")


def prison():
    pm = j("prison_memories.json")
    types = {}
    for mid, e in pm.items():
        types.setdefault(e["type"], []).append((mid, e))
    for t, lst in sorted(types.items()):
        print(f"=== {t}: {len(lst)} 条")
        for mid, e in lst[:6]:
            print(f"    {mid} parts={e['participants']} "
                  f"c={e['creation_date']} end={e['end_date']} "
                  f"exp={e.get('expiration_date')} owners={e['owners'][:3]} "
                  f"vars={e.get('vars')}")
    ku = j("char_key_union.json")
    print("\n角色字段并集：", sorted(ku.keys()))


def child():
    pm = j("prison_memories.json")
    print("child_premature / child_stillborn 参与者槽位抽样：")
    for t in ("child_premature", "child_stillborn", "child_born"):
        pass
    # prison_memories 只含 prison；child 型要看 memory_types，另跑
    print(json.dumps({k: v for k, v in j("memory_types.json").items()
                      if "child" in k}, ensure_ascii=False, indent=1))


def find(sub):
    for name in os.listdir(OUT):
        if not name.endswith(".json"):
            continue
        txt = io.open(os.path.join(OUT, name), encoding="utf-8").read()
        n = txt.count(sub)
        print(f"{name}: {n}")


def raw():
    d = j("raw_chars.json")
    for cid, c in d.items():
        if not c:
            print(cid, "None")
            continue
        print("===", cid, c.get("first_name"), "female", c.get("female"))
        print("   traits:", c.get("traits"))
        print("   trait_xp_amounts:", c.get("trait_xp_amounts"))
        print("   inactive_traits:", c.get("inactive_traits"))
        print("   recessive_traits:", str(c.get("recessive_traits"))[:120])
        print("   alive_data keys:", sorted((c.get("alive_data") or {}).keys()))
        print("   family_data:", json.dumps(c.get("family_data"),
                                            ensure_ascii=False)[:600])


def align():
    """对齐关系分析：trait_xp_amounts 与 traits 的关系。"""
    g = j("game_trait_tracks.json")
    tc = j("track_chars.json")
    # 只挑「恰好一个 tracked 特质」的角色，看 xp 长度与 traits 的关系
    rows = []
    for cid, v in tc.items():
        tr = v["traits"]
        tk = [t for t in tr if t in g]
        if len(tk) != 1:
            continue
        ntrk = len(g[tk[0]]["tracks"])
        rows.append((cid, v["name"], ntrk, v["xp_len"], v["traits_len"], tr,
                     v["trait_xp_amounts"]))
    print(f"恰好一个轨道特质的角色 {len(rows)} 人；按 轨道数 vs xp长度 统计：")
    from collections import Counter
    cnt = Counter((r[2], r[3]) for r in rows)
    for (nt, xl), c in sorted(cnt.items()):
        print(f"  tracks={nt} xp_len={xl}: {c} 人")
    for r in rows[:15]:
        print(f"  {r[0]} {r[1]} tracks={r[2]} xp_len={r[3]} ntraits={r[4]}")
        print(f"      traits={r[5]}")
        print(f"      xp={r[6]}")


def chars():
    """指定角色的轨道特质与当前档位（问题2 渲染目标核对）。"""
    tc = j("track_chars.json")
    scan = j("trait_tracks_scan.json")
    ids = sys.argv[2:] or ["38677", "15682", "12278", "43961"]
    for cid in ids:
        v = tc.get(cid)
        if not v:
            print(cid, "无轨道特质")
            continue
        print("===", cid, v["name"])
        tr, xp = v["traits"], v["trait_xp_amounts"] or []
        cur = 0
        for t in tr:
            if t not in scan:
                continue
            for tk in scan[t]:
                val = xp[cur] if cur < len(xp) else None
                lv = sum(1 for th in tk["levels"]
                         if val is not None and val >= th)
                print(f"   {t} · {tk['track']}  xp={val}  "
                      f"档位={lv}/{len(tk['levels'])} 阈值={tk['levels']}")
                cur += 1


def keys():
    """trait 索引 → 键（配合 track_chars 里 traits 为键名者用）。"""
    tl = j("traits_lookup.json")
    ids = sys.argv[2:] or ["63", "67", "69", "66", "82", "47", "11", "28",
                           "234", "90", "145", "152"]
    scan = j("trait_tracks_scan.json")
    for i in ids:
        k = tl[int(i)] if int(i) < len(tl) else "?"
        print(f"   {i} → {k}" + ("   [有轨道]" if k in scan else ""))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "tracks"
    if mode == "tracks":
        tracks()
    elif mode == "chars":
        chars()
    elif mode == "keys":
        keys()
    elif mode == "prison":
        prison()
    elif mode == "child":
        child()
    elif mode == "raw":
        raw()
    elif mode == "align":
        align()
    elif mode == "find":
        find(sys.argv[2] if len(sys.argv) > 2 else "gallowsbait")
    return 0


if __name__ == "__main__":
    sys.exit(main())
