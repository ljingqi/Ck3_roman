# -*- coding: utf-8 -*-
"""v104 probe 4: 傀儡链定向取证。

1) 找出「傀儡主 = 135480」的所有傀儡（alive_data.variables.list 的 puppeteers 项），
   并回溯每条所在角色条目的 id 与名字；
2) 看 puppet 类型（theological_agent_puppet / external_...）在存档里落在哪；
3) 看 scripted_relations / opinions 的容器形状。

用法: & tools\\py.ps1 tools\\tests\\v104_probe_puppets.py <melt> <puppeteer-cid>
"""
import json
import lzma
import re
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"
DEFAULT_CID = "135480"
ENTRY_RE = re.compile(rb'"(\d{1,12})":\{"first_name":')


def load_bytes(path):
    if path.endswith(".xz"):
        with lzma.open(path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        return f.read()


def owner_of(data, off, back=400000):
    """从 off 往回找最近的 '<id>":{"first_name":'，返回该 id（角色条目的开始）。"""
    seg = data[max(0, off - back):off]
    hits = list(ENTRY_RE.finditer(seg))
    if not hits:
        return None
    return hits[-1].group(1).decode()


def name_of(data, cid, window=1200):
    p = data.find(b'"' + cid.encode() + b'":{"first_name":')
    if p < 0:
        return None
    return data[p:p + window]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    cid = (sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CID).encode()
    data = load_bytes(path)
    print("melt", path, "bytes", len(data))

    print("=" * 72)
    print("[A] 谁把 %s 当傀儡主（puppeteers 列表命中）" % cid.decode())
    pat = b'"puppeteers","item":{"type":"char","identity":' + cid + b"}"
    offs, p = [], 0
    while True:
        p = data.find(pat, p)
        if p < 0:
            break
        offs.append(p)
        p += 1
    print("命中", len(offs))
    seen = []
    for o in offs:
        owner = owner_of(data, o)
        frag = data[max(0, o - 700):o + 200].decode("utf-8", "replace")
        print("-" * 60, "at", o, "owner(条目起点)=", owner)
        print("   ", frag.replace("\n", " ")[-900:])
        # 该傀儡自身是否有「名字/头衔/职位」线索
        if owner and owner not in seen:
            seen.append(owner)
            nm = name_of(data, owner)
            if nm:
                print("    [傀儡档案]", nm.decode("utf-8", "replace")[:400])
    print("涉及傀儡条目:", seen)

    print("=" * 72)
    print("[B] puppet 类型串出现在哪")
    for needle in [b'theological_agent_puppet', b'"puppets"', b'"puppeteer"']:
        print("-" * 60, needle.decode(), "count", data.count(needle))
        q, shown = 0, 0
        while shown < 3:
            q = data.find(needle, q)
            if q < 0:
                break
            print("   at", q, "|", data[max(0, q - 250):q + 250]
                  .decode("utf-8", "replace").replace("\n", " "))
            q += 1
            shown += 1

    print("=" * 72)
    print("[C] scripted_relations 形状（样例）")
    q = data.find(b'"scripted_relations"')
    print(data[max(0, q - 200):q + 500].decode("utf-8", "replace"))

    print("=" * 72)
    print("[D] living / characters 容器边界")
    for k in [b'"living"', b'"characters":{"dead_prunable']:
        q = data.find(k)
        print(k.decode(), "at", q, "|", data[q:q + 300].decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
