# -*- coding: utf-8 -*-
"""v113 probe: which labels the era fix added and which it removed, label by label (no melt).

Extracts every `…公主/皇女/王子/皇子/公女/公子` style label from two snapshots and prints the
count diff, so a side effect on the prince words cannot hide behind a total."""
import collections
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
FILES = ["snap_v112_207044_final.json", "snap_v113_207044_final.json"]
LABEL = re.compile(r"[\u4e00-\u9fff·]{2,12}?(?:公主|皇女|王子|皇子|公女|公子)(?=[\u4e00-\u9fff·，、。；：]|$)")
# a title glued to a name has no separator to anchor on, so the era words are counted as substrings
ERA = re.compile(r"(?:大唐|大邓|大天|唐|天|邓|粤|岭南)(?:公主|皇女|王子|皇子|公女|公子)")


def labels(fn):
    p = os.path.join(ROOT, "output", "洪氏2", "data", fn)
    if not os.path.exists(p):
        return None
    facts = dict(json.load(io.open(p, encoding="utf-8")).get("facts") or {})
    # the tree sidecar was added in v113 and repeats every label; compare the prose facts only
    facts.pop("genealogy_tree", None)
    blob = json.dumps(facts, ensure_ascii=False)
    return collections.Counter(LABEL.findall(blob))


def era(fn):
    p = os.path.join(ROOT, "output", "洪氏2", "data", fn)
    facts = dict(json.load(io.open(p, encoding="utf-8")).get("facts") or {})
    facts.pop("genealogy_tree", None)
    return collections.Counter(ERA.findall(json.dumps(facts, ensure_ascii=False)))


def main():
    old, new = labels(FILES[0]), labels(FILES[1])
    if old is None or new is None:
        print("缺快照")
        return
    gone = {k: v for k, v in (old - new).items() if v}
    added = {k: v for k, v in (new - old).items() if v}
    print(f"v112 标签种类 {len(old)}；v113 {len(new)}")
    print("\n=== 朝名+称谓（按子串数，含贴在人名前的写法）===")
    for tag, c in (("v112", era(FILES[0])), ("v113", era(FILES[1]))):
        print(f"  {tag}: " + "、".join(f"{k}×{v}" for k, v in
                                      sorted(c.items(), key=lambda kv: -kv[1])))
    print("\n=== 消失 ===")
    for k, v in sorted(gone.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  -{v:5d}  {k}   (v113 尚余 {new.get(k, 0)})")
    print("\n=== 新增 ===")
    for k, v in sorted(added.items(), key=lambda kv: -kv[1])[:20]:
        print(f"  +{v:5d}  {k}   (v112 原有 {old.get(k, 0)})")


if __name__ == "__main__":
    main()
