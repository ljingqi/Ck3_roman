# -*- coding: utf-8 -*-
"""打印指定特质的 `name` 块原文（问题2 档位名解析用）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_traitname_block.py logistician confucian_education lifestyle_reveler
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
    wanted = sys.argv[1:]
    for d in [GAME] + MODS:
        for f in glob.glob(os.path.join(d, "common", "traits", "*.txt")):
            try:
                txt = io.open(f, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for m in re.finditer(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\{", txt, re.M):
                key = m.group(1)
                if key not in wanted:
                    continue
                body = block(txt, m.end() - 1)
                nm = re.search(r"^\s*name\s*=\s*\{", body, re.M)
                print(f"===== {key}  ({os.path.basename(f)})")
                print(block(body, nm.end() - 1) if nm else "（无 name 块）")
                print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
