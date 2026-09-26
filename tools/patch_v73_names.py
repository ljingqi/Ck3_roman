# -*- coding: utf-8 -*-
"""v73 补丁: 事件人名取「受业名」(_chrono_nm) —— 一次运行即得, 幂等由命中次数保证。

背景 (取证): 跨传主缓存取记录时 `name_full` 可能是另一档期算出的父名/家名 ——
富兰克林档先王记成「比约恩·蒙索」, 而国号沿革里是「比约恩·朗纳尔松」。
用法: & tools\\py.ps1 tools\\patch_v73_names.py
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "facts.py")

HELPER = '''def _chrono_nm(f, cid, date=None):
    """事件人名 (v73): 取**受业名** —— 先按熔件 `first_name` 与当地名序拼显示名,
    退到缓存档案的 `name_full`。跨传主缓存取记录时, `name_full` 可能是另一档期算出的
    父名/家名 (富兰克林档实测: 先王记成「比约恩·蒙索」而国号沿革里是「比约恩·朗纳尔松」),
    故受业名优先, 与历代行同一套词。"""
    cc = f._chars.get(str(cid)) or {}
    if isinstance(cc, dict) and cc:
        try:
            nm = f.name(cid, date=date)
        except Exception:
            nm = ""
        if nm:
            return nm
    return _chrono_rec(f, cid).get("name_full") or f.name_or(cid, "") or ""


'''

PAIRS = [
    ("def _chrono_acc_text(f, cid, date, word, prev, from_prev=False):",
     HELPER + "def _chrono_acc_text(f, cid, date, word, prev, from_prev=False,\n"
     "                       prev_date=None):"),
    ("        pn = _chrono_rec(f, prev).get(\"name_full\") or f.name_or(prev, \"\") or \"\"",
     "        pn = _chrono_nm(f, prev, prev_date or date)"),
    ("def _chrono_ruler_line(f, tid, date, cid, hist_type, prev, loss_date,\n"
     "                       vacant=False, is_h=False, family=False):",
     "def _chrono_ruler_line(f, tid, date, cid, hist_type, prev, loss_date,\n"
     "                       vacant=False, is_h=False, family=False, nm=None,\n"
     "                       prev_date=None):"),
    ("    nm = f.name_with_regnal(cid, date) or f.name_or(cid, \"\") or \"\"",
     "    nm = nm or _chrono_nm(f, cid, date)"),
    ("                           from_prev=(hist_type in (None, \"\", \"appointment_succession\",\n"
     "                                                    \"abdication\", \"inheritance\")))",
     "                           from_prev=(hist_type in (None, \"\", \"appointment_succession\",\n"
     "                                                    \"abdication\", \"inheritance\")),\n"
     "                           prev_date=prev_date)"),
    ("            p[\"rows\"].append(_chrono_ruler_line(\n"
     "                f, tid, d, h, ty, _chrono_prev_for(accs, gi), end,\n"
     "                vacant=vac, is_h=is_h))",
     "            p[\"rows\"].append(_chrono_ruler_line(\n"
     "                f, tid, d, h, ty, _chrono_prev_for(accs, gi), end,\n"
     "                vacant=vac, is_h=is_h,\n"
     "                prev_date=(accs[gi - 1][0] if gi > 0 else None)))"),
]


def main():
    src = io.open(TARGET, encoding="utf-8").read()
    if "def _chrono_nm(" in src:
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
    print("facts.py 已打补丁: _chrono_nm + %d 处替换" % (len(PAIRS) - 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
