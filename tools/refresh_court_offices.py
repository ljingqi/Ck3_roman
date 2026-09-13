# -*- coding: utf-8 -*-
"""v36 (问题2)：为既有缓存补 `court_office_history`（主角**获授**的朝廷职位）。

背景：v36 起 cache_lib.extract_snapshot 会在每次并档时逐档记录
`court_positions.database` 里 employee==玩家、employer==他人的职位（太师等）。
老缓存建于该版本之前，键不存在 → 事实层不会下发「朝廷职位」。
本脚本按熔件补齐该键（只补这一个键，其余缓存字段一概不动）。

用法：
    & tools\\tools\\py.ps1 tools\\refresh_court_offices.py <家族文件夹> <玩家id>

做法（省时口径）：从最新熔件**逆序**回溯，逐档记录该玩家获授的职位集合；
遇到「已找到过职位、且连续 N 档为空」即停（更早的档不可能再出现职位，
除非职位曾中断又复得 —— 故 N 默认 3，可用 --keep 调大）。
只给**集合发生变化**的档记一条（与 extract_snapshot 的逐档记录等价：
facts 侧只用「最后一次非空档 + 其后一档」推失去时点）。

产物：原地更新 output/<家族>/data/player_<id>.json（先备份 .bak-v36）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl          # noqa: E402

STOP_AFTER_EMPTY = 3


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

    found_any = False
    empty_run = 0
    hist = []          # [(date, offices)] 逆序收集后反转
    for name in reversed(melts):
        date_label = name[5:-5].replace("_", ".")
        melt = cl.load_melt(os.path.join(data, name))
        cpd = (melt.get("court_positions") or {}).get("database") or {}
        offices = []
        for _pos_id, e in cpd.items():
            if not isinstance(e, dict):
                continue
            if e.get("employee") != pid or e.get("employer") is None:
                continue
            ptype = e.get("court_position")
            if not ptype:
                continue
            offices.append({"type": ptype, "employer": int(e["employer"]),
                            "hire_date": e.get("hire_date")})
        offices.sort(key=lambda x: (str(x.get("type")), x["employer"]))
        print(f"  {date_label}: {len(offices)} 桩"
              + (f" — {offices[0]['type']}" if offices else ""), flush=True)
        # 逐档记录 (与 cache_lib.extract_snapshot 同口径): facts 侧靠相邻两档
        # 推任期起讫, 压缩掉中间档会把失去时点推迟一档。
        hist.append({"date": date_label, "offices": offices})
        if offices:
            found_any = True
            empty_run = 0
        else:
            empty_run += 1
            if found_any and empty_run >= keep:
                print(f"  停扫：已见职位, 且连续 {empty_run} 档为空")
                break
    hist.reverse()
    if not hist:
        print("未找到任何熔件，未改动缓存")
        return 1
    cache["court_office_history"] = hist
    bak = cache_path + ".bak-v36"
    if not os.path.exists(bak):
        with open(bak, "w", encoding="utf-8") as fp:
            json.dump(json.load(open(cache_path, encoding="utf-8")), fp,
                      ensure_ascii=False)
        print(f"已备份原缓存 → {os.path.basename(bak)}")
    with open(cache_path, "w", encoding="utf-8") as fp:
        json.dump(cache, fp, ensure_ascii=False)
    print(f"已写入 court_office_history: {len(hist)} 条")
    for h in hist:
        print("   ", h["date"], [f"{o['type']}@{o['employer']}" for o in h["offices"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
