# -*- coding: utf-8 -*-
"""v111 回归对照：同一份样本在改动前后的身份词/称谓。

样本 = 熔件里全部「dead_data.flavor 下划线不足 3 段」的死者（正是缺陷类）
     + 每 400 名死者取 1 名的随机面（确认改动没有波及类外的人）。

用法：
    & tools\\py.ps1 tools\\tests\\v111_ab_labels.py <家族> <pid> > logs\\v111_ab_after.txt
改动前后各跑一次，再 diff。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402


def _melt_path(folder):
    data = os.path.join(ROOT, "output", folder, "data")
    melts = [x for x in os.listdir(data) if x.startswith("melt_") and "_idx" not in x]

    def key(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)

    return os.path.join(data, max(melts, key=key)), data


def main():
    folder, pid = sys.argv[1], int(sys.argv[2])
    melt_path, data = _melt_path(folder)
    print("# melt=%s pid=%d" % (os.path.basename(melt_path), pid), flush=True)
    melt = cl.load_melt(melt_path)
    cache = cl.load_cache(os.path.join(data, "player_%d.json" % pid))
    names_path = os.path.join(data, "names.json")
    if not os.path.exists(names_path):
        names_path = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, melt, names_path)

    chars = cl.all_characters(melt)
    sample = []
    every = 0
    for cid, c in sorted(chars.items(), key=lambda kv: str(kv[0])):
        if not isinstance(c, dict):
            continue
        dd = c.get("dead_data") or {}
        if not dd.get("date"):
            continue
        every += 1
        fk = str(dd.get("flavor") or "")
        if fk and len(fk.split("_")) < 3:
            sample.append((cid, fk, dd["date"]))
        elif every % 400 == 0:
            sample.append((cid, fk, dd["date"]))
    print("# 样本 %d 人" % len(sample), flush=True)
    for cid, fk, dd in sample:
        try:
            off = f.official_title(cid, dd)
        except Exception as e:                      # 不让个例打断对照
            off = "!!%s" % e
        try:
            lab = f.kin_label(cid)
        except Exception as e:
            lab = "!!%s" % e
        print("%-10s %-40s %-12s | %s | %s" % (cid, fk, dd, off, lab))
    return 0


if __name__ == "__main__":
    sys.exit(main())
