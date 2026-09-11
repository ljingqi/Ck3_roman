# -*- coding: utf-8 -*-
"""打印指定游戏/Mod 特质定义里的 track/tracks 原文块。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_traitdef.py lifestyle_traveler architect
"""
import glob
import io
import os
import re
import sys

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
                return txt[i:j + 1]
    return txt[i:]


def main():
    wanted = sys.argv[1:] or ["lifestyle_traveler", "architect"]
    found = {}
    for d in [GAME] + MODS:
        for f in glob.glob(os.path.join(d, "common", "traits", "*.txt")):
            try:
                txt = io.open(f, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for m in re.finditer(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\{", txt, re.M):
                key = m.group(1)
                if key not in wanted or key in found:
                    continue
                body = block(txt, m.end() - 1)
                mt = re.search(r"^(\s*)(track|tracks)\s*=\s*\{", body, re.M)
                found[key] = (f, block(body, mt.end() - 1) if mt else None)
    for k in wanted:
        f, b = found.get(k, (None, None))
        print(f"===== {k}   ({f})")
        print(b if b else "   （定义里没有 track/tracks 块）")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
