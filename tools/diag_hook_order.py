# -*- coding: utf-8 -*-
"""查牵制方向（v33）：存档 active_relations 的 first/second 到底是「持有者→对象」
还是**按键规范化**（小 id 在前）？

判据：
  1) 全档 active_hook_* 记录里 first<second 与 first>second 的条数
     —— 若几乎全是 first<second，则 first/second 只是**成对关系的规范序**，
     与持有方向无关（v31「first 即持有者」的推断是单例巧合）。
  2) 抽「干了我老婆」的几对，配 opinions 的当事人指向标记
     （nilaopozhenbang 你老婆真棒 / xiangyongletadeqizi 享用了他的妻子 = 由通奸者指向丈夫）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_hook_order.py [melt] [玩家id]
"""
import io
import json
import os
import sys
from collections import Counter

ROOT = r"D:\Roman"
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

MELT = sys.argv[1] if len(sys.argv) > 1 else \
    r"D:\Roman\output\马克龙\data\melt_879_01_01.json"
PID = int(sys.argv[2]) if len(sys.argv) > 2 else 38677
YEAR_MARKERS = ("nilaopozhenbang_opinion", "xiangyongletadeqizi_opinion",
                "zheshiwomenlianggerendemimi_opinion",
                "beitagandehenshuang_opinion", "rangwogandehenshuang_opinion")


def main():
    print(f"载入 {MELT} …", flush=True)
    melt = cl.load_melt(MELT)
    print("载入完成", flush=True)

    ar = (melt.get("relations") or {}).get("active_relations") or []
    order = Counter()
    types = Counter()
    lvl = Counter()
    samples = {}
    for e in ar:
        if not isinstance(e, dict):
            continue
        f_, s_ = e.get("first"), e.get("second")
        for k, v in e.items():
            if not str(k).startswith("active_hook") or not isinstance(v, dict):
                continue
            tp = str(v.get("type"))
            types[tp] += 1
            lvl[str(k)] += 1
            if isinstance(f_, int) and isinstance(s_, int):
                order["first<second" if f_ < s_ else
                      ("first>second" if f_ > s_ else "equal")] += 1
            samples.setdefault(tp, []).append((f_, s_, str(k), v))
    print("\n=== 全档 active_hook_* 记录 ===")
    print("  first/second 顺序:", dict(order))
    print("  字段名分布:", dict(lvl))
    print("  类型分布:", dict(types.most_common(12)))

    print("\n=== 「干了我老婆」记录（全部字段） ===")
    for f_, s_, k, v in samples.get("ganlewodelaopo_hook", []):
        nm = {cid: cl.display_name_from_melt(melt, cid) if hasattr(
            cl, "display_name_from_melt") else None for cid in (f_, s_)}
        print(f"  first={f_} second={s_} {k} {json.dumps(v, ensure_ascii=False)}"
              f"   玩家参与: {'是' if PID in (f_, s_) else '否'}")

    print("\n=== house_head_hook 抽样（顺序判据用） ===")
    for f_, s_, k, v in samples.get("house_head_hook", [])[:10]:
        print(f"  first={f_} second={s_} {k}  "
              f"{'first<second' if f_ < s_ else 'first>second'}")

    print("\n=== 玩家相关 opinions 的当事人标记 ===")
    ch = cl.all_characters(melt)
    for o in (melt.get("opinions") or {}).get("active_opinions") or []:
        if not isinstance(o, dict):
            continue
        ow, tg = o.get("owner"), o.get("target")
        if PID not in (ow, tg):
            continue
        vals = o.get("temporary_opinion")
        vals = vals if isinstance(vals, list) else [vals]
        for v in vals:
            if isinstance(v, dict) and v.get("modifier") in YEAR_MARKERS:
                print(f"  owner={ow}({_nm(ch, ow)}) → target={tg}({_nm(ch, tg)})"
                      f"  {v.get('modifier')}  {v.get('start_date')}")
    return 0


def _nm(ch, cid):
    c = ch.get(str(cid)) or {}
    return c.get("name") or c.get("first_name") or "?"


if __name__ == "__main__":
    sys.exit(main())
