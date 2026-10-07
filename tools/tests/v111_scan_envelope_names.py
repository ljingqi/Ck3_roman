# -*- coding: utf-8 -*-
"""v111 同类问题取证：游戏在存档封套里写的头衔显示名，落在哪一类名字上？

对每个家族目录的每份熔件，取封套 `meta_data.meta_title_name`（游戏自己写的显示名），
分类为：
  - 静态头衔名（本地化表里某个 b_/c_/d_/k_/e_/h_ 键的文本，即 title_name_data.name 那一类）；
  - 族名（某个 `<culture>_collective_noun` 键的文本，即「室韦人」那一类人群名）；
  - 其它（自定义名、家族庄园名等）。
落进「族名」且不在「静态头衔名」里的样本，就证明游戏确实会显示族名——否则说明族名不是显示名。

用法：
    & tools\\py.ps1 tools\\tests\\v111_scan_envelope_names.py [<家族> ...]
"""
import collections
import json
import lzma
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import localization as L          # noqa: E402

TITLE_KEY = re.compile(r"^(b|c|d|k|e|h|x)_")


def _meta_title(path):
    opener = lzma.open if path.endswith(".xz") else open
    with opener(path, "rb") as fp:
        s = fp.read(400000).decode("utf-8", "replace")
    m = re.search(r'"meta_title_name"\s*:\s*"((?:[^"\\]|\\.)*)"', s)
    if not m:
        return None
    try:
        return json.loads('"%s"' % m.group(1))
    except ValueError:
        return m.group(1)


def main():
    table = L.table()
    static, people = set(), {}
    for k, v in (table or {}).items():
        if not isinstance(v, str) or not v.strip():
            continue
        v = v.strip()
        if k.endswith("_collective_noun"):
            people[v] = k
        if TITLE_KEY.match(k):
            static.add(v)
    print("本地化表：静态头衔名 %d 个，族名 %d 个" % (len(static), len(people)))

    fams = sys.argv[1:] or ["洪氏2", "斯卡利茨", "田所", "洪氏", "教宗尼各老"]
    hits = collections.Counter()
    examples = []
    per_fam = collections.Counter()
    for fam in fams:
        data = os.path.join(ROOT, "output", fam, "data")
        if not os.path.isdir(data):
            continue
        for fn in sorted(os.listdir(data)):
            if not fn.startswith("melt_") or "_idx" in fn:
                continue
            y = fn.split("_")[1]
            nm = _meta_title(os.path.join(data, fn))
            if not nm:
                continue
            if nm in people and nm not in static:
                per_fam[fam + ":族名"] += 1
                hits[nm] += 1
                if len(examples) < 40:
                    examples.append((fam, y, nm, people[nm]))
            elif nm in people:
                per_fam[fam + ":族名(同静态)"] += 1
            elif nm in static:
                per_fam[fam + ":静态名"] += 1
            else:
                per_fam[fam + ":其它"] += 1
                if len(examples) < 40:
                    examples.append((fam, y, nm, "其它"))
    print("\n#### 分类计数")
    for k, n in sorted(per_fam.items()):
        print("   %-28s %d" % (k, n))
    print("\n#### 族名命中（游戏显示 = 族名）%s" % dict(hits))
    for fam, y, nm, key in examples:
        print("   %s %s  %s  (%s)" % (fam, y, nm, key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
