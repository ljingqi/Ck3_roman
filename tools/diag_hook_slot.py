# -*- coding: utf-8 -*-
"""牵制槽位语义验证（v33）：active_hook_0 / active_hook_1 是「方向槽」还是「序号」。

假设 H1（方向槽）：active_hook_0 = `first` 持有对 `second`；active_hook_1 = `second`
持有对 `first`（引擎把成对关系按键规范化 first<second，方向由槽号承载）。
假设 H2（序号）：active_hook_N 只是同一对多条牵制的序号，方向无从得知。

独立判据 —— **家主权（house_head_hook）的持有者必为家主**，而家主通常是同族中年长者
（CK3 角色 id 随时间递增，先出生者 id 更小）。故：
  · 若 H1 成立：槽 0 记录里 first 应显著年长于 second；槽 1 记录里 second 应显著年长；
  · 若 H2 成立：槽 0/1 与年龄差无关（应近随机）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_hook_slot.py [melt]
"""
import io
import os
import sys
from collections import Counter

ROOT = r"D:\Roman"
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

MELT = sys.argv[1] if len(sys.argv) > 1 else \
    r"D:\Roman\output\马克龙\data\melt_879_01_01.json"


def _birth(ch, cid):
    c = ch.get(str(cid)) or {}
    b = c.get("birth")
    if not b:
        return None
    try:
        return int(str(b).split(".")[0])
    except ValueError:
        return None


def main():
    print(f"载入 {MELT} …", flush=True)
    melt = cl.load_melt(MELT)
    ch = cl.all_characters(melt)
    print("载入完成", flush=True)
    ar = (melt.get("relations") or {}).get("active_relations") or []

    both = 0
    slots = Counter()
    stat = {"0": Counter(), "1": Counter()}
    samples = {"0": [], "1": []}
    for e in ar:
        if not isinstance(e, dict):
            continue
        f_, s_ = e.get("first"), e.get("second")
        ks = [k for k in e if str(k).startswith("active_hook")
              and isinstance(e[k], dict)]
        if len(ks) > 1:
            both += 1
        for k in ks:
            n = str(k).rsplit("_", 1)[-1]
            slots[n] += 1
            if n not in stat:
                continue
            bf, bs = _birth(ch, f_), _birth(ch, s_)
            if bf is None or bs is None:
                stat[n]["无生年"] += 1
                continue
            if bf < bs:
                stat[n]["first 年长"] += 1
            elif bf > bs:
                stat[n]["second 年长"] += 1
            else:
                stat[n]["同年"] += 1
            if len(samples[n]) < 6:
                samples[n].append((f_, bf, s_, bs, e[k].get("type"),
                                   "first年长" if bf < bs else "second年长"))
    print(f"\n一对多条槽位的记录数: {both}（若>0，说明同一对可同时存在两条牵制）")
    print("槽名分布:", dict(slots))
    print("\n=== house_head_hook 的槽位 vs 生年（独立判据） ===")
    hh = {"0": Counter(), "1": Counter()}
    hh_both = 0
    for e in ar:
        if not isinstance(e, dict):
            continue
        f_, s_ = e.get("first"), e.get("second")
        ks = [k for k in e if str(k).startswith("active_hook") and isinstance(e[k], dict)]
        n_hh = [k for k in ks if e[k].get("type") == "house_head_hook"]
        if len(n_hh) == 2:
            hh_both += 1
        for k in n_hh:
            n = str(k).rsplit("_", 1)[-1]
            bf, bs = _birth(ch, f_), _birth(ch, s_)
            if bf is None or bs is None:
                hh[n]["无生年"] += 1
            elif bf < bs:
                hh[n]["first 年长(＝first 是家主)"] += 1
            elif bf > bs:
                hh[n]["second 年长(＝second 是家主)"] += 1
            else:
                hh[n]["同年"] += 1
    for n in ("0", "1"):
        print(f"  house_head 槽 {n}: {dict(hh[n])}")
    print(f"  同族双向家主权记录: {hh_both}")
    for n in ("0", "1"):
        print(f"  槽 {n}: {dict(stat[n])}")
    for n in ("0", "1"):
        print(f"  槽 {n} 抽样:")
        for x in samples[n]:
            print("    ", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
