# -*- coding: utf-8 -*-
"""临时改写玩家缓存的 last_date（重跑旧十年传时复现原始提示词面）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\set_last_date.py 马克龙 38677 878.1.1
     ｜ 用后务必改回真实末档（重建缓存会写回真值）：
        & tools\\py.ps1 tools\\set_last_date.py 马克龙 38677 879.1.1

为什么：`facts._protagonist` 的 skip_detail 以 `as_of < cache.last_date` 判定
「本篇早于末档」，从而略去直辖/封臣/御前会议明细 —— 重跑一篇旧十年传时若不钉住
last_date，看到的提示词面就与当初不同（v31 §12.5 纪律）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    folder, pid, date = sys.argv[1], sys.argv[2], sys.argv[3]
    path = os.path.join(ROOT, "output", folder, "data", f"player_{pid}.json")
    with open(path, encoding="utf-8") as fp:
        cache = json.load(fp)
    old = cache.get("last_date")
    cache["last_date"] = date
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(cache, fp, ensure_ascii=False)
    os.replace(tmp, path)
    print(f"{path}: last_date {old} → {date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
