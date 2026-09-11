# -*- coding: utf-8 -*-
"""问题2 关键核查：游戏 `name` 块里带 has_trait_xp 条件的特质名（按 XP 换名）。

现状：localization.build_trait_names 只取一个 desc，实测取到**最高档名**
（lifestyle_reveler → trait_reveler_3「传奇的狂欢者」，玩家实际 XP=0）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_trait_levelnames.py
"""
import glob
import io
import json
import os
import re
import sys

ROOT = r"D:\Roman"
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


def main():
    loc = json.load(io.open(os.path.join(ROOT, "data", "localization.json"),
                            encoding="utf-8"))["table"]
    names = json.load(io.open(os.path.join(ROOT, "data", "trait_names.json"),
                              encoding="utf-8"))["traits"]
    scan = json.load(io.open(os.path.join(ROOT, "tools", "out_macron",
                                          "trait_tracks_scan.json"),
                             encoding="utf-8"))
    out = {}
    for d in [GAME] + MODS:
        for f in glob.glob(os.path.join(d, "common", "traits", "*.txt")):
            try:
                txt = io.open(f, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for m in re.finditer(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\{", txt, re.M):
                key = m.group(1)
                if key not in scan:
                    continue
                body = block(txt, m.end() - 1)
                nm = re.search(r"^\s*name\s*=\s*\{", body, re.M)
                if not nm:
                    continue
                nb = block(body, nm.end() - 1)
                if "has_trait_xp" not in nb:
                    continue
                conds = []
                for tm in re.finditer(
                        r"has_trait_xp\s*=\s*\{([^}]*)\}", nb):
                    c = tm.group(1)
                    tr = re.search(r"track\s*=\s*([A-Za-z0-9_]+)", c)
                    vl = re.search(r"value\s*([<>=]+)\s*(\d+)", c)
                    conds.append((tr.group(1) if tr else "?", vl.group(0) if vl else "?"))
                descs = re.findall(r"desc\s*=\s*([A-Za-z0-9_.]+)", nb)
                out[key] = {"conds": conds, "descs": descs,
                            "picked": names.get(key),
                            "picked_zh": loc.get(names.get(key) or ""),
                            "base": loc.get(f"trait_{key}")}
    print(f"带 XP 换名（name 块含 has_trait_xp）的特质 {len(out)} 个\n")
    for k, v in sorted(out.items()):
        print(f"  {k}:")
        print(f"     档位名 desc: {v['descs']}")
        print(f"     条件: {v['conds']}")
        print(f"     现用名: {v['picked']} = {v['picked_zh']}   （基础名 trait_{k} = {v['base']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
