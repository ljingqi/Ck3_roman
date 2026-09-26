# -*- coding: utf-8 -*-
"""v73 补丁 2: 家族历代记的人名与结构 (受业名 + 段起止 + 字段齐备)。

用法: & tools\\py.ps1 tools\\patch_v73_family.py
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "facts.py")

PAIRS = [
    # 先世各人: 受业名 + 前任亲缘 (家族模式也读得懂继承链)
    ("        line = _chrono_ruler_line(f, atid, d, cid, f._gain_reason.get((cid, atid, d), \"\"),\n"
     "                                  f._gain_prev.get((cid, atid, d)), loss,\n"
     "                                  is_h=is_h, family=True)",
     "        _pv = f._gain_prev.get((cid, atid, d))\n"
     "        if _pv is None and idx > 0:\n"
     "            _pv = picked[idx - 1][1]\n"
     "        line = _chrono_ruler_line(\n"
     "            f, atid, d, cid, f._gain_reason.get((cid, atid, d), \"\"),\n"
     "            _pv, loss, is_h=is_h, family=True,\n"
     "            nm=_chrono_nm(f, cid, d), prev_date=(picked[idx - 1][0] if idx else None))"),
    ("    rows = []\n    for (d, cid, atid, loss, _lt2) in picked:",
     "    rows = []\n    for idx, (d, cid, atid, loss, _lt2) in enumerate(picked):"),
    # 传主本人: 人名取该头衔历代里那一个 (与篇名同源)
    ("    own_line = _chrono_ruler_line(f, tid, own_g, pid, \"created\", None, own_l,\n"
     "                                  is_h=is_h, family=True)",
     "    own_line = _chrono_ruler_line(f, tid, own_g, pid, \"created\",\n"
     "                                  (picked[-1][1] if picked else None), own_l,\n"
     "                                  is_h=is_h, family=True,\n"
     "                                  nm=f.name(pid))"),
    # 家族段: 段起止与 current 字段齐备 (供年代区间与「本朝」判定)
    ("    name = (f.name(pid) or f.cache.get(\"player_name\") or \"\") + \"家\"\n"
     "    return {\n"
     "        \"name\": name,\n"
     "        \"family\": True,\n"
     "        \"tid\": int(tid),\n"
     "        \"is_h\": bool(is_h),\n"
     "        \"current\": {\"dynasty\": \"\", \"span\": \"\", \"ids\": [pid]},\n"
     "        \"periods\": [{\"dynasty\": \"家族\", \"span\": \"\", \"ids\": [p[1] for p in picked] + [pid],\n"
     "                     \"rows\": rows}],\n"
     "        \"wars\": _chrono_war_lines(f, tid) if is_h else [],\n"
     "        \"subs\": _chrono_sub_lines(f, tid, pid),\n"
     "    }",
     "    name = (f.name(pid) or f.cache.get(\"player_name\") or \"\") + \"家\"\n"
     "    _fam_cur = {\"name\": \"家族\", \"start\": (picked[0][0] if picked else own_g),\n"
     "                \"end\": own_l, \"vacant\": False,\n"
     "                \"ids\": [p[1] for p in picked] + [pid], \"rows\": rows}\n"
     "    return {\n"
     "        \"name\": name,\n"
     "        \"family\": True,\n"
     "        \"tid\": int(tid),\n"
     "        \"is_h\": bool(is_h),\n"
     "        \"current\": _fam_cur,\n"
     "        \"periods\": [_fam_cur],\n"
     "        \"wars\": _chrono_war_lines(f, tid) if is_h else [],\n"
     "        \"subs\": _chrono_sub_lines(f, tid, pid),\n"
     "    }"),
]


def main():
    src = io.open(TARGET, encoding="utf-8").read()
    if "for idx, (d, cid, atid, loss, _lt2) in enumerate(picked):" in src:
        print("已打过此补丁 — 无需重复")
        return 0
    for i, (a, b) in enumerate(PAIRS):
        n = src.count(a)
        if n != 1:
            print("PAIRS[%d] 命中 %d 次 (应为 1) — 中止" % (i, n))
            print(a[:200])
            return 1
        src = src.replace(a, b, 1)
    io.open(TARGET, "w", encoding="utf-8", newline="\n").write(src)
    print("facts.py 已打补丁 2: %d 处" % len(PAIRS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
