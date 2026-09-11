# -*- coding: utf-8 -*-
"""打印游戏角色记忆类型定义（含 participants）与相关本地化。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_memdef.py imprisoned released_from_prison_memory escaped_from_prison_memory
"""
import glob
import io
import json
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
    wanted = sys.argv[1:] or ["imprisoned"]
    loc = json.load(io.open(r"D:\Roman\data\localization.json",
                            encoding="utf-8"))["table"]
    for d in [GAME] + MODS:
        for f in glob.glob(os.path.join(d, "common", "character_memory_types",
                                        "*.txt")):
            try:
                txt = io.open(f, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for m in re.finditer(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\{", txt, re.M):
                key = m.group(1)
                if key not in wanted:
                    continue
                body = block(txt, m.end() - 1)
                pt = re.search(r"participants\s*=\s*\{([^}]*)\}", body)
                descs = re.findall(r"desc\s*=\s*([A-Za-z0-9_.]+)", body)
                print(f"===== {key}   ({os.path.basename(f)})")
                print("  participants:",
                      pt.group(1).split() if pt else "（无）")
                for k in descs[:6]:
                    k = k.strip()
                    print(f"  {k} = {loc.get(k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
