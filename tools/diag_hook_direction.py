# -*- coding: utf-8 -*-
"""查「干了我老婆」牵制的方向：Mod 事件用语 + 存档 opinions 的当事人指向。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_hook_direction.py [melt] [玩家id]
"""
import io
import os
import re
import sys

MELT = sys.argv[1] if len(sys.argv) > 1 else \
    r"D:\Roman\output\马克龙\data\melt_879_01_01.json"
PID = sys.argv[2] if len(sys.argv) > 2 else "38677"

# Mod 在 add_hook 前后加的双方好感修饰符（方向即当事人身份）
#   nilaopozhenbang_opinion        你老婆真棒      → 由「通奸者」对「丈夫」
#   zheshiwomenlianggerendemimi    这是我们两个人的秘密 → 由「丈夫」对「通奸者」
#   xiangyongletadeqizi_opinion    享用了他的妻子  → 由「通奸者」对「丈夫」?
#   rangwogandehenshuang_opinion   让我干得很爽    → 由「通奸者」对「妻子」
#   beitagandehenshuang_opinion    被他干得很爽    → 由「妻子」对「通奸者」
MARKERS = ["nilaopozhenbang_opinion", "zheshiwomenlianggerendemimi_opinion",
           "xiangyongletadeqizi_opinion", "rangwogandehenshuang_opinion",
           "beitagandehenshuang_opinion", "ganlewodelaopo_hook"]


def main():
    blob = io.open(MELT, "rb").read()
    print(f"{MELT}  {len(blob):,} 字节")
    for mk in MARKERS:
        b = mk.encode("utf-8")
        n = blob.count(b)
        print(f"\n===== {mk}: {n} 次")
        pos = 0
        shown = 0
        while shown < 8:
            i = blob.find(b, pos)
            if i < 0:
                break
            pos = i + 1
            ctx = blob[max(0, i - 500):i + 200].decode("utf-8", "replace")
            pair = re.findall(r'"owner":(\d+),"target":(\d+)', ctx)
            rel = re.findall(r'\{"first":(\d+),"second":(\d+)', ctx)
            if not pair and not rel:
                continue
            shown += 1
            who = ""
            if PID in " ".join(a + b for a, b in pair + rel):
                who = "  <<< 涉玩家"
            print(f"  opinions owner/target={pair[-1] if pair else None} "
                  f"relations first/second={rel[-1] if rel else None}{who}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
