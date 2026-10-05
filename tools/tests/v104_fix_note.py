# -*- coding: utf-8 -*-
"""Fix the appended correction note in docs/调研_v104_大公会议主持与地点.md (PowerShell ate the backticks)."""
import io
import os

P = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                 "docs", "调研_v104_大公会议主持与地点.md")
MARK = "## 补记（主代理 2026-10-05 复核"
NOTE = """## 补记（主代理 2026-10-05 复核，纠正本文件「② 地点无痕」的结论）

本文件②的「无痕」是**只查了 1057.1.1 一档**得出的，结论**不成立**。主代理在 **melt_1060_01_01.json.xz** 的
`activity_manager.database` 里直接取到了 **1059.12.5 图尔大公会议的活动对象**（取证 `logs/v104_melt1060_council.txt:17`）：

```
{"type":"activity_ecumenical_council","host":50431299,
 "log":[{"character":50431299,"date":"1059.12.5","title":"大公会议开始","province":1785}],
 "creation_date":"1059.12.5","active_start_date":"1061.4.25",
 "variables":{"data":[{"flag":"ec_throttled_faith","data":{"type":"faith","identity":13}}]},
 "phases":[{"phase":"ecumenical_council_phase_summons","province":1785,…},…]}
```

⇒ 地点字段是 **`phases[].province` / `log[].province`**；`province 1785` 即本文件自己也认定的 `b_santiago/c_santiago`「圣地亚哥」。
⇒ 正确定性应为：**「有快照落在会议存活期时可读，否则无痕」**——1059 那次可读，1056.1.25 那次不可读
（1056.1.1 早于 `creation_date`，1057.1.1 已按 `00_defines.txt:1716 = 90` 清空，且 `ecumenical_council.txt:334 is_single_location = yes` 说明四个 phase 同址）。
另：`host`（50431299）与流水的 `character` 完全一致，是「谁召集」的独立校验源。
本轮采用口径见 `docs/方案_v104_洪氏2六问题.md` §1.4 / §2.4。
"""

with io.open(P, encoding="utf-8") as f:
    txt = f.read()
i = txt.find(MARK)
if i >= 0:
    txt = txt[:i].rstrip() + "\n\n---\n\n" + NOTE
else:
    txt = txt.rstrip() + "\n\n---\n\n" + NOTE
with io.open(P, "w", encoding="utf-8", newline="\n") as f:
    f.write(txt)
print("ok", len(txt))
