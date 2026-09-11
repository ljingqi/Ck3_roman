# -*- coding: utf-8 -*-
"""读取 snap 快照的可读视图（不载熔件）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_snap_read.py [快照路径] [节名...]
默认打印 meta / protagonist / blocks 键表 / melt_tables；给节名则打印该节全文。
"""
import json
import os
import sys

ROOT = r"D:\Roman"
OUT = os.path.join(ROOT, "tools", "out_macron")


def dump(name, text):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as fp:
        fp.write(text)
    print(f"  写入 {p} ({len(text)} 字符)")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "output", "马克龙", "data", "snap_38677_878.1.1_d1.json")
    snap = json.load(open(path, encoding="utf-8"))
    want = sys.argv[2:]

    lines = [f"== meta ==\n{json.dumps(snap['meta'], ensure_ascii=False, indent=1)}"]
    facts = snap.get("facts") or {}
    lines.append("== facts 键 ==\n" + ", ".join(sorted(facts.keys())))
    lines.append("== protagonist ==\n" + json.dumps(
        facts.get("protagonist"), ensure_ascii=False, indent=1))
    lines.append("== blocks 键 ==\n" + ", ".join(sorted((snap.get("blocks") or {}).keys())))
    lines.append("== melt_tables ==\n" + json.dumps(
        snap.get("melt_tables"), ensure_ascii=False, indent=1)[:4000])
    lines.append("== shared ==\n" + (snap.get("shared") or ""))
    dump("snap_overview.txt", "\n\n".join(lines))

    for w in want:
        if w in (snap.get("blocks") or {}):
            dump(f"snap_block_{w}.txt", snap["blocks"][w])
        if w in (snap.get("messages") or {}):
            m = snap["messages"][w]
            dump(f"snap_msg_{w}.txt",
                 f"===== SYSTEM =====\n{m['system']}\n\n===== USER =====\n{m['user']}")
        if w in facts:
            dump(f"snap_fact_{w}.txt", json.dumps(facts[w], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    sys.exit(main())
