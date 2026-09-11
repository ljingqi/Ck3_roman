# -*- coding: utf-8 -*-
"""问题2 数据层核查：轨道名/轨道描述/档位效果在本地化表里的覆盖率。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_track_loc.py
"""
import io
import json
import re
import sys


def main():
    scan = json.load(io.open(r"D:\Roman\tools\out_macron\trait_tracks_scan.json",
                             encoding="utf-8"))
    loc = json.load(io.open(r"D:\Roman\data\localization.json",
                            encoding="utf-8"))["table"]
    names = json.load(io.open(r"D:\Roman\data\trait_names.json",
                              encoding="utf-8"))["traits"]
    miss_name = miss_desc = 0
    rows = []
    for trait, tracks in sorted(scan.items()):
        tn = loc.get(f"trait_{trait}") or loc.get(trait) or names.get(trait)
        for t in tracks:
            tk = t["track"]
            nm = loc.get(f"trait_track_{tk}")
            ds = loc.get(f"trait_track_{tk}_desc")
            if not nm:
                miss_name += 1
            if not ds:
                miss_desc += 1
            rows.append((trait, tn, tk, nm, len(t["levels"]), t["levels"]))
    print(f"轨道总数 {len(rows)}；轨道名缺本地化 {miss_name}；轨道描述缺 {miss_desc}")
    print("\n缺名轨道：")
    for r in rows:
        if not r[3]:
            print(f"   {r[0]} / {r[2]}  (档位 {r[5]})")
    print("\n多轨或档位≥3 的轨道示例（特质名 → 轨道名 档位）：")
    for r in rows:
        if r[4] >= 3:
            print(f"   {r[1]} → {r[3] or r[2]}  档位{r[5]}")
    # 效果修饰符的本地化覆盖
    eff = {}
    for trait, tracks in scan.items():
        pass
    print("\n修饰符本地化抽查：")
    for k in ("martial", "prowess", "diplomacy", "intrigue", "stewardship",
              "learning", "general_opinion", "courtier_and_guest_opinion",
              "barons_and_minor_landholders_opinion", "monthly_prestige",
              "health", "stress_loss_mult", "legitimacy_gain_mult",
              "dread_gain_mult", "attraction_opinion", "child_opinion"):
        print(f"   {k} = {loc.get(k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
