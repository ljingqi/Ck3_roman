# -*- coding: utf-8 -*-
"""v104 probe 10: 傀儡链双向核验 + 传主是否为某信仰/礼仪之首。

A) 传主 135480 是否出现在任何 religious_head / head_of_rite / founder 上；
B) puppets 字段双向核验：puppeteer.puppets[].character == X  <=>  X.variables.list[name=puppeteers].item == puppeteer；
C) 全档 puppets 类型分布。

用法: & tools\\py.ps1 tools\\tests\\v104_probe_puppet_verify.py <melt> [cid]
"""
import gc
import json
import lzma
import re
import sys

DEFAULT = r"D:\Roman\output\洪氏2\data\melt_1057_01_01.json.xz"
CID = "135480"
ENTRY_RE = re.compile(rb'"(\d{1,12})":\{"first_name":')


def load_bytes(path):
    if path.endswith(".xz"):
        with lzma.open(path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        return f.read()


def owner_of(data, off, back=200000):
    seg = data[max(0, off - back):off]
    hits = list(ENTRY_RE.finditer(seg))
    return hits[-1].group(1).decode() if hits else None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    cid = sys.argv[2] if len(sys.argv) > 2 else CID
    data = load_bytes(path)
    print("melt", path, "bytes", len(data))

    print("=" * 78)
    print("[A] 传主是否出现在 faith/rite 的 head / founder 字段")
    for pat in (b'"religious_head":' + cid.encode(),
                b'"head_of_rite":' + cid.encode(),
                b'"founder":' + cid.encode()):
        offs, p = [], 0
        while True:
            p = data.find(pat, p)
            if p < 0:
                break
            offs.append(p)
            p += 1
        print("  ", pat.decode(), "命中", len(offs), offs[:5])
        for o in offs[:3]:
            print("      |", data[max(0, o - 220):o + 80].decode("utf-8", "replace"))

    print("=" * 78)
    print("[B] puppets 双向核验（抽 4 条）")
    pat = re.compile(rb'"puppets":\[\{"character":(\d+),"type":"([a-z_]+)"\}\]')
    n = 0
    for m in pat.finditer(data):
        owner = owner_of(data, m.start())
        puppet = m.group(1).decode()
        ptype = m.group(2).decode()
        # 傀儡侧的 puppeteers 列表
        pn = data.find(b'"' + puppet.encode() + b'":{"first_name":')
        side = "?"
        if pn >= 0:
            window = data[pn:pn + 400000]
            k = window.find(b'"name":"puppeteers"')
            side = ("找到 puppeteers 项" if k >= 0 else "该角色 400KB 内无 puppeteers")
            if k >= 0:
                sub = window[k:k + 400].decode("utf-8", "replace")
                side += " | " + sub[:260]
        print("  puppeteer=%s  puppet=%s  type=%s  ->  %s"
              % (owner, puppet, ptype, side))
        n += 1
        if n >= 4:
            break
    print("  正则命中总数（单傀儡形态）:", len(pat.findall(data)))

    print("=" * 78)
    print("[C] puppets 类型分布")
    types = {}
    for m in re.finditer(rb'"type":"([a-z_]*puppet[a-z_]*)"', data):
        t = m.group(1).decode()
        types[t] = types.get(t, 0) + 1
    print("  ", json.dumps(types, ensure_ascii=False, sort_keys=True))
    print("  \"puppets\":[ 出现", data.count(b'"puppets":['), "次")
    print("  含 theological_agent_puppet 的 puppets 条目",
          data.count(b'"type":"theological_agent_puppet"'),
          "| external:", data.count(b'"type":"external_theological_agent_puppet"'))
    del data
    gc.collect()


if __name__ == "__main__":
    main()
