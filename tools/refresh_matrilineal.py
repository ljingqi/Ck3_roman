# -*- coding: utf-8 -*-
"""v43：为既有缓存补 `matrilineal_pairs`（母系婚 / 入赘婚姻对）。

背景：v43 起 cache_lib.extract_snapshot 每次并档都会闩存存档
`relations.active_relations` 里 `{"first":A,"second":B,"matrilineal":true}` 的条目
（这正是 CK3 唯一直接标出「母系婚姻」的地方；游戏简中把这一档写作「切换入赘」，
规则是所生子女属**母方**家族）。老缓存建于该版本之前，键不存在 → 事实层对
「父方无家族」这类子女归属判不出的婚事给不出线系，成婚句只剩普通形态。

本脚本按熔件补齐该键（只补这一个键，其余缓存字段一概不动）。

用法：
    & tools\tools\\py.ps1 tools\\refresh_matrilineal.py <家族文件夹> <玩家id>

做法（省时口径）：从最新熔件**逆序**回溯逐档闩存（key = "<小id>><大id>"，值为
首次见到的档期）；连续 N 档一无所获即停（N 默认 2 —— 关系条目自入库后长期驻留，
越早的档只会补出「此后已消失的婚事」，通常一两档就扫尽）。--keep=N 可调。

产物：原地更新 output/<家族>/data/player_<id>.json（先备份 .bak-v43）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl          # noqa: E402

STOP_AFTER_EMPTY = 2


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    keep = STOP_AFTER_EMPTY
    for a in sys.argv[1:]:
        if a.startswith("--keep="):
            keep = int(a.split("=", 1)[1])
    if len(argv) < 2:
        print(__doc__)
        return 2
    folder, pid = argv[0], int(argv[1])
    data = os.path.join(ROOT, "output", folder, "data")
    cache_path = os.path.join(data, f"player_{pid}.json")
    cache = json.load(open(cache_path, encoding="utf-8"))
    last = cache.get("last_date") or "9999.9.9"

    def _dkey(name):
        return cl.date_key(name[5:-5].replace("_", "."))

    melts = sorted((x for x in os.listdir(data)
                    if x.startswith("melt_") and "_idx" not in x
                    and x.endswith(".json")),
                   key=_dkey)
    melts = [m for m in melts if _dkey(m) <= cl.date_key(last)]
    print(f"缓存最后一档 {last}; 待扫熔件 {len(melts)} 份（逆序, 见停扫规则）")

    before = len(cache.get("matrilineal_pairs") or {})
    empty_run = 0
    scanned = 0
    for name in reversed(melts):
        date_label = name[5:-5].replace("_", ".")
        melt = cl.load_melt(os.path.join(data, name))
        added = cl._latch_matrilineal(cache, melt, date_label)
        scanned += 1
        print(f"  {date_label}: 新增 {added} 对 "
              f"(累计 {len(cache['matrilineal_pairs'])})", flush=True)
        if added:
            empty_run = 0
        else:
            empty_run += 1
            if empty_run >= keep:
                print(f"  停扫：连续 {empty_run} 档无新增")
                break
    total = len(cache.get("matrilineal_pairs") or {})
    if total == before:
        print(f"未新增任何母系婚对（原有 {before} 对），缓存未改写")
        return 0
    bak = cache_path + ".bak-v43"
    if not os.path.exists(bak):
        with open(bak, "w", encoding="utf-8") as fp:
            json.dump(json.load(open(cache_path, encoding="utf-8")), fp,
                      ensure_ascii=False)
        print(f"已备份原缓存 → {os.path.basename(bak)}")
    with open(cache_path, "w", encoding="utf-8") as fp:
        json.dump(cache, fp, ensure_ascii=False)
    print(f"已写入 matrilineal_pairs: {before} → {total} 对 (扫了 {scanned} 档)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
