---
name: snapshot-testing
description: >-
  Use whenever this CK3 biography project (<项目根>) needs to read save data, inspect facts, check
  a playthrough's output, reproduce a prompt, or run any verification during development — before
  running pipeline.py rebuild-cache / migrate / scan, before deleting
  output/<家族>/data/melt_*.json, or before loading a melt. The rule is: look for an existing melt
  and an existing facts snapshot first, reuse them, and load a 100–125MB melt at most once per
  session; never re-melt a save to "get a clean slate".
---

# 测试走快照，不重熔存档（snapshot-testing）

本技能用于本项目（`<项目根>`，CK3 家传 · 纪传体传记生成）的**一切测试与核对动作**。

## 为什么（本项目的实际代价）

- 熔化存档（rakaly）是**唯一**的分钟级瓶颈：德圣塔战役 21 档实测
  `logs/journal.log` 11:46 → 12:16，**约 50 分钟**。
- `cache_lib.load_melt()` 单次 1–3 分钟；熔件 `output/<家族>/data/melt_*.json`
  有 70–125MB。
- `pipeline.py rebuild-cache` 会遍历 `output/` 下**全部**战役文件夹的熔件
  （实测上百份）——迭代时跑它是数小时级的浪费。
- 而**真正的断言只需要几十 KB**：`tools/tests/snap.py` 把「核对所需的一切」落成
  `snap_<pid>_<as_of>[_dN].json`（事实 + 各篇 blocks + 逐请求提示词），
  之后所有断言都是**秒级**。

## 第一步永远是「看有没有」

```powershell
Get-ChildItem output\<家族>\data | Select-Object Name,Length,LastWriteTime
```

| 看到 | 做法 |
| --- | --- |
| `melt_*.json` 已存在 | **直接用**，绝不重熔 |
| `snap_<pid>_<as_of>*.json` 已存在 | 直接对它跑断言 |
| 缺所需时点的快照 | 跑一次 `tools/tests/snap.py`（熔件只载一次，可一条命令连落多个时点） |
| 缺熔件、但游戏里已有存档 | 只跑 `tools/rebuild_folder.py <家族> <pid>`（单战役，**不是** `rebuild-cache`） |

## 成本分级（写死命令，按需选最低一级）

| 级别 | 命令 | 成本 | 何时用 |
| --- | --- | --- | --- |
| 秒级 | `& tools\py.ps1 tools\tests\verify_fast.py [快照]` | <1s | 纯函数 + 传输面（裸键/括注/缺料按语…） |
| 秒级 | `& tools\py.ps1 tools\tests\verify_v34.py [快照]`、`tools\tests\verify_v35.py [快照]` | <1s | 已有快照的专项断言 |
| 秒级 | `& tools\py.ps1 tools\tests\check_bio_v34.py`、`tools\tests\check_bio_v35.py` | <1s | 成稿 md 自查（不碰数据） |
| 秒级 | `& tools\py.ps1 tools\tests\snapdiff.py <旧快照> <新快照> [--facts-only]` | <1s | 改动前后**事实面**是否逐字节一致 |
| 分钟级 | `& tools\py.ps1 tools\tests\snap.py <家族> <pid> <as_of> [十年] [--name=X] [--assert]` | 1–3min（熔件只载一次） | 需要新时点/新战役的快照 |
| 分钟级 | `& tools\py.ps1 tools\tests\snap_at_head.py <家族> <pid> <as_of> [十年]` | 1–3min | 用 git HEAD 版源码落对照快照（验证「本期改动是否动了事实面」） |
| 分钟级 | `& tools\py.ps1 tools\rebuild_folder.py <家族> [pid]` | 5–15min（单战役熔件，不重新熔化） | 缓存 schema 新增字段后需重建该战役缓存 |
| **禁用** | `pipeline.py rebuild-cache` / `pipeline.py migrate` | 遍历上百份熔件 | 仅迁移/修复；测试一律走 `rebuild_folder.py` |

## 铁律

1. **同一会话内，同一熔件最多整载一次**。需要多个时点就一次性 `snap.py` 落齐，
   之后全部在快照上反复断言。
2. **不删 `melt_*.json` 再重熔**。想「回到干净状态」就重建缓存
   （`rebuild_folder.py`）或换一个 `--name=` 的快照，50 分钟的重新熔化换不来任何东西。
3. **改提示词/事实层前先落一份 HEAD 对照快照**（`snap_at_head.py`），改完再落一份新的，
   用 `snapdiff.py` 确认「事实面是否有非预期变化」——比人眼比对快照可靠。
4. **报告落文件**（本轮新证据 `logs/*.txt`，UTF-8）：`... | Out-File -Encoding UTF8 logs\x.txt`，
   一次写入可反复 `read`，避免控制台编码问题导致「跑一遍→乱码→再跑一遍」。
   ⚠ 目录约定（v77 起）：`logs/` 根只放程序自写的三个运行时日志
   （`journal.log`/`prompts.log`/`loc_miss.log`）；**历轮取证**在 `logs/archive/`（文档引用
   一律写 `logs/archive/…`），本轮新证据写 `logs/vNN_*.txt`。
5. **测试/探针/快照脚本一律放 `tools/tests/`**（v77 起，333 个脚本已归拢；`tools/` 顶层只留
   生产与数据工具链）。命令口径：`& tools\py.ps1 tools\tests\<脚本>.py`。
6. **确认熔件真的是本地已有的那份**：`snap.py` 取 `data/` 里排序最后的
   `melt_*.json`，不是重新熔化。

## 与其它技能/文档的关系

- 破坏性改动前的 checkpoint 提交：`.agents/skills/commit-before-destructive`。
- 子进程 stdout 编码与包装脚本：`.agents/skills/utf8-gbk-encoding`。
- **查游戏机制 / 本地化键 / 存档字段含义：`.agents/skills/ck3-game-source`** ——
  `All Under Heaven`（AUH / 天命 TGP）是**游戏本体 1.19 自带的 DLC 内容**（`game/common/character_interactions/10_tgp_*.txt`、
  `game/events/dlc/tgp/*`、`game/dlc/dlc029_mp1`），**不是 Mod**，直接读 `game/` 即可；
  该技能另附「已落档调研」索引，查机制前先看一眼，省得重跑。
- `README.md` 的「提速基建」段与本技能同源，本技能是它的**可执行版本**。

## 收尾自查

1. 这轮测试有没有**因为图省事**去重熔或跑 `rebuild-cache`？
2. 用到的熔件是不是本来就躺在 `output/<家族>/data/` 里？
3. 断言是不是跑在快照上（秒级）而不是跑在全量数据上？
4. 改动的「事实面」有没有用 `snapdiff.py` 与 HEAD 对照过？
