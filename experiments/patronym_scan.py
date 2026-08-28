# -*- coding: utf-8 -*-
"""解析游戏 name_lists: 父名制文化 → (前后缀键), 并本地化中文 (行级解析)。"""
import re
import os
import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
NL = r"F:\Game\steamapps\common\Crusader Kings III\game\common\culture\name_lists"
CULT = r"F:\Game\steamapps\common\Crusader Kings III\game\common\culture\cultures"
LOC = r"F:\Game\steamapps\common\Crusader Kings III\game\localization\simp_chinese"

loc = {}
for dp, _dn, fns in os.walk(LOC):
    for fn in fns:
        if not fn.endswith(".yml"):
            continue
        try:
            for line in open(os.path.join(dp, fn), encoding="utf-8-sig"):
                m = re.match(r"^([A-Za-z0-9_]+):\s*\"(.*)\"\s*$", line.strip())
                if m:
                    loc[m.group(1)] = m.group(2)
        except Exception:
            pass

def zh(key):
    if not key:
        return ""
    v = loc.get(key, "")
    if not v or v.startswith("$"):
        return ""
    return v.replace("#!", "").strip()

rules = {}  # name_list -> (pf_m, pf_f, sf_m, sf_f)
for fn in sorted(os.listdir(NL)):
    if not fn.endswith(".txt"):
        continue
    depth = 0
    top_blk = ""
    pf_m = pf_f = sf_m = sf_f = ""
    for line in open(os.path.join(NL, fn), encoding="utf-8-sig"):
        s = line.strip()
        # 大括号深度
        opens = s.count("{")
        closes = s.count("}")
        if depth == 0 and opens:
            hm = re.match(r"^([a-z_0-9]+)\s*=\s*\{", s)
            if hm:
                top_blk = hm.group(1)
                pf_m = pf_f = sf_m = sf_f = ""
        if depth == 1:
            vm = re.match(r'^(patronym_(?:prefix|suffix)_(?:male|female))\s*=\s*"([^"]+)"', s)
            if vm:
                k = vm.group(1)
                v = vm.group(2)
                if k == "patronym_prefix_male":
                    pf_m = v
                elif k == "patronym_prefix_female":
                    pf_f = v
                elif k == "patronym_suffix_male":
                    sf_m = v
                elif k == "patronym_suffix_female":
                    sf_f = v
        if s == "always_use_patronym = yes" and top_blk:
            rules.setdefault(top_blk, (pf_m, pf_f, sf_m, sf_f))
        depth += opens - closes
        if depth < 0:
            depth = 0

# 文化 -> name_list
cult2nl = {}
for dp, _dn, fns in os.walk(CULT):
    for fn in fns:
        if not fn.endswith(".txt"):
            continue
        txt = open(os.path.join(dp, fn), encoding="utf-8-sig").read()
        for m in re.finditer(r"^([a-z_]+)\s*=\s*\{", txt, re.M):
            cul = m.group(1)
            end = txt.find("\n}", m.end())
            seg = txt[m.end():end] if end > 0 else txt[m.end():m.end() + 400]
            nlm = re.search(r"name_list\s*=\s*([a-z_0-9]+)", seg)
            if nlm:
                cult2nl[cul] = nlm.group(1)

print("== 父名制 name_list 与中文词 ==")
for nl_name, (pm, pf, sm, sf) in sorted(rules.items()):
    print("%-24s 前男=%-20s(%-8s) 前女=%-20s(%-8s) 后男=%-20s(%-8s) 后女=%-20s(%-8s)"
          % (nl_name, pm, zh(pm), pf, zh(pf), sm, zh(sm), sf, zh(sf)))

print()
print("== 使用这些 name_list 的文化 ==")
for cul, nl_name in sorted(cult2nl.items()):
    if nl_name in rules:
        print("  %-18s -> %s" % (cul, nl_name))

out = {}
for cul, nl_name in cult2nl.items():
    if nl_name in rules:
        pm, pf, sm, sf = rules[nl_name]
        out[cul] = {"pm": pm, "pf": pf, "sm": sm, "sf": sf,
                    "pm_zh": zh(pm), "pf_zh": zh(pf),
                    "sm_zh": zh(sm), "sf_zh": zh(sf)}
with open(r"D:\Roman\data\patronym_rules.json", "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=1)
print()
print("已导出 data/patronym_rules.json, 覆盖文化数:", len(out))
