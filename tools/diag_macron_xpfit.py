# -*- coding: utf-8 -*-
"""马克龙（问题2）离线拟合：trait_xp_amounts 与 traits 的轨道数是否一一对应。

不载熔件：用 tools/out_macron/track_chars.json（含 3987 个角色的 traits + trait_xp_amounts）
＋ 游戏/Mod 的 common/traits 定义（track 单轨简写 / tracks 多轨，保序）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_macron_xpfit.py
"""
import glob
import io
import json
import os
import re
import sys

OUT = r"D:\Roman\tools\out_macron"
GAME = r"F:\SteamLibrary\steamapps\common\Crusader Kings III\game"
MODS = [
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\3594634592",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\2273832430",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\2227658180",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\2997587648",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\2823178539",
    r"C:\Users\Maoha\Documents\Paradox Interactive\Crusader Kings III\mod\deviants_mask_mod",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\2978257885",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\3595290446",
]


def block(txt, i):
    depth = 0
    for j in range(i, len(txt)):
        if txt[j] == "{":
            depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0:
                return txt[i + 1:j]
    return txt[i + 1:]


SKIP = {"desc", "trigger", "first_valid", "name", "triggered_desc",
        "limit", "trigger_if", "trigger_else_if", "trigger_else", "OR", "AND",
        "NOT", "has_trait_xp", "trait", "track", "value"}

# 命名档位键（游戏里只有 scarred / lifestyle_traveler 等少数特质用）：
# trait_second_level 与 trait_third_level 对应 XP 阈值 50 / 100
# （实证：scarred 的 name 块 has_trait_xp value < 50 → 一级、= 100 → 三级）。
NAMED_LEVELS = {"trait_second_level": 50, "trait_third_level": 100,
                "trait_fourth_level": 150, "trait_fifth_level": 200}


def levels_of(sub):
    """轨道内层块 → 阈值列表（数字键直接用；命名档位键按 NAMED_LEVELS 折算）。"""
    lv = [int(x) for x in re.findall(r"^\s*(\d+)\s*=\s*\{", sub, re.M)]
    lv += [NAMED_LEVELS[k] for k in re.findall(
        r"^\s*(trait_[a-z_]*level)\s*=\s*\{", sub, re.M) if k in NAMED_LEVELS]
    return sorted(lv)


def scan():
    """→ {trait: [(track_name, [阈值...]), ...]} 保序
    （单轨简写 track = {} → 轨道名=特质名）。"""
    out = {}
    for d in [GAME] + MODS:
        for f in glob.glob(os.path.join(d, "common", "traits", "*.txt")):
            try:
                txt = io.open(f, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for m in re.finditer(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\{", txt, re.M):
                key = m.group(1)
                body = block(txt, m.end() - 1)
                names = []
                mt = re.search(r"^\s*tracks\s*=\s*\{", body, re.M)
                if mt:
                    tb = block(body, mt.end() - 1)
                    # 只认「含阈值子块」的键为轨道
                    for tm in re.finditer(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\{",
                                          tb, re.M):
                        tname = tm.group(1)
                        sub = block(tb, tm.end() - 1)
                        if levels_of(sub):
                            names.append((tname, levels_of(sub)))
                else:
                    ms = re.search(r"^\s*track\s*=\s*\{", body, re.M)
                    if ms:
                        sub = block(body, ms.end() - 1)
                        if levels_of(sub):
                            names.append((key, levels_of(sub)))
                if names:
                    out[key] = names
    return out


def main():
    tracks = scan()
    print(f"XP 轨道特质 {len(tracks)} 个")
    simple = {k: [n for n, _ in v] for k, v in tracks.items()}
    lv_of = {k: {n: lv for n, lv in v} for k, v in tracks.items()}
    total_tracks = sum(len(v) for v in simple.values())
    print(f"  轨道总数 {total_tracks}；多轨特质 "
          f"{[(k, [n for n, _ in v]) for k, v in tracks.items() if len(v) > 1]}")

    tc = json.load(io.open(os.path.join(OUT, "track_chars.json"), encoding="utf-8"))
    ok = bad = noxp = 0
    bad_samples = []
    level_stat = {}
    for cid, v in tc.items():
        tr = v["traits"]
        xp = v.get("trait_xp_amounts")
        xl = len(xp) if isinstance(xp, list) else 0
        exp = 0
        cursor = 0
        mapping = []          # [(trait, track, xp)]
        for t in tr:
            if t not in simple:
                continue
            for tn in simple[t]:
                val = xp[cursor] if cursor < xl else None
                mapping.append((t, tn, val))
                cursor += 1
            exp += len(simple[t])
        if exp == 0:
            noxp += 1
            continue
        if exp == xl:
            ok += 1
            for t, tn, val in mapping:
                lv = sum(1 for th in lv_of[t][tn]
                         if val is not None and val >= th)
                level_stat[(t, tn)] = level_stat.get((t, tn), 0) + (1 if lv else 0)
        else:
            bad += 1
            if len(bad_samples) < 12:
                bad_samples.append((cid, v["name"], tr, xp, exp, xl))
    print(f"\n拟合结果：命中 {ok} / 不符 {bad} / 无轨道特质 {noxp}")
    for s in bad_samples:
        print(f"  {s[0]} {s[1]} 预测{s[4]} 实际{s[5]}")
        print(f"     traits={s[2]}")
        print(f"     xp={s[3]}")
    print("\n有 XP 的 (特质,轨道) 计数（>0 即该档确有该子特质经验）：")
    for k, c in sorted(level_stat.items(), key=lambda kv: -kv[1])[:30]:
        print(f"  {k}: {c} 人")

    with io.open(os.path.join(OUT, "trait_tracks_scan.json"), "w",
                 encoding="utf-8") as fp:
        json.dump({k: [{"track": n, "levels": lv} for n, lv in v]
                   for k, v in tracks.items()},
                  fp, ensure_ascii=False, indent=1)
    print("写入 trait_tracks_scan.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
