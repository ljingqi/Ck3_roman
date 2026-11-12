---
name: research-to-doc
description: >-
  Use whenever a task in this CK3 biography project goes beyond a one-line fix — a new feature,
  a bug diagnosis, a batch of user-listed problems, a「研究一下/调研一下/为什么」question, or any
  delegation of research to a subagent. The rule is: research first, then write the findings and
  the plan into docs/方案_vXXX_<主题>.md (or docs/调研_vXXX_<主题>.md for pure research) before
  touching code, and keep the chat context to that document's conclusion plus its path so later
  turns re-read the file instead of redoing the research.
---

# 调研先落档（research-to-doc）

本技能用于本项目（CK3 家传 · 纪传体传记生成）的**一切调研类任务**。
核心规则：**一轮调研的产物是一份 `docs/` 下的 Markdown 文档；对话里只留结论摘要与文档路径。**

## 为什么（本项目的实际代价）

- 本项目的调研动辄要读上万行代码（`facts.py` 约 1.5MB、`cache_lib.py` 约 240KB、
  `pipeline.py` 约 160KB、`localization.py` 约 155KB），比对多份
  `output/<家族>/data/melt_*.json`（单份 70–125MB）与 `output/<家族>/` 下的成稿，
  原始取证（代码摘录、日志、实测数字）轻易上万字；这些原文留在对话里会挤占上下文窗口，
  后续写代码时反而记不住关键判据。
- `docs/` 已被 `.gitignore` 覆盖（只留本机、不进版本库），正适合放这些含存档数字与用户原话的调研。
- 同一主题常跨多轮（研究 → 施工 → 验证 → 返工）。文档是唯一事实源，后续轮次先读它，
  省掉重复 grep、重复读熔件与重复跑测试。

## 何时必须落档

命中任意一条即触发：

- 用户一次列出两项以上需求 / 问题（测试集反馈、多问题修复）；
- 用户说「研究一下」「调研」「为什么…」「看看能不能」；
- 现象需要定位到具体函数与行号（诊断类）；
- 准备把调研交给 subagent；
- 一轮会话里同一主题的工具调用已超过约 15 次而结论尚未成型。

单点改一行、改错别字、换一个提示词措辞这类一步到位的修改，直接改并跑对应测试即可。

## 文档命名与位置

- **调研 + 方案**（默认）：`docs/方案_vXXX_<主题>.md`，例如
  `docs/方案_v142_妫氏_三项.md`。主题用用户口中的对象命名（家族名、板块名、功能名）。
- **纯机制取证**（只回答「为什么」，不动代码）：`docs/调研_vXXX_<主题>.md`，例如
  `docs/调研_v104_死者记录翻变与家族缺省.md`。
- **版本号与当轮同号**：`docs/方案_vXXX_*`、`logs/vXXX/`、提交信息里的 `vXXX` 三处一致；
  号取 `git log` / `CHANGELOG.md` 里的最新版本号 +1，不补零（照既有写法 `v86`、`v142`）。
- 已有同主题文档时**续写那一份**（追加「第 N 轮」小节并更新日期），保持单一事实源。
- 编码一律 UTF-8（见 `.agents/skills/utf8-gbk-encoding`）。

## 文档骨架（照抄这个结构）

```markdown
# 方案 vXXX · <主题>

> 研究日期：YYYY-MM-DD　|　对象：`output/<家族>`（年份区间）　|
> 涉及文件：`facts.py`、`cache_lib.py`、`biography.py`、`localization.py`、`logs/vXXX/<探针>.py`

状态：调研中 / 已确认并实施（YYYY-MM-DD）。
开工前 HEAD：`<哈希>`。本轮只读既有熔件/快照/成稿/日志，未重熔、未 `rebuild-cache`。

## 0. 一句话结论

1. **<结论>**：……（现象 → 根因 → 修法，各一句）。
2. ……

## 1. 需求对照（用户原话 → 本文小节）

| # | 用户原话（摘要） | 主题 | 验收标准 | 本文 |
| --- | --- | --- | --- | --- |
| 1 | … | … | …（可观测的结果） | [§3.1](#31-) |

## 2. 现状与取证（代码锚点）

- `cache_lib.py:2279` `display_name`：……
- 实测数字：`output/<家族>/data/player_<pid>.json` 的 `<字段>` = ……；
  命令 `& tools\py.ps1 logs\vXXX\vXXX_probe_xx.py` 输出 ……
- 日志：`logs/journal.log` YYYY-MM-DD HH:MM 段 ……

## 3. 根因（逐条裁决）

### 3.1 <现象一句话>

**现象**：……
**根因**：……（指向具体函数与行号）
**证据**：……（命令、数字、文件行号）

## 4. 方案

### 4.1 <改动名>

- 改哪里：`facts.py` `<函数>`
- 怎么改：……
- 为什么在这里改：……（程序优先，见 `no-negative-prompts`）
- 影响面：受影响的成稿/快照/存量缓存

## 5. 验证

| 步骤 | 命令 | 期望 |
| --- | --- | --- |
| 单元/回归 | `& tools\py.ps1 tools\tests\verify_fast.py [快照]` | 全部 PASS |
| 专项 | `& tools\py.ps1 logs\vXXX\vXXX_check_<主题>.py` | 逐条断言通过 |
| 事实面 | `& tools\py.ps1 tools\tests\snapdiff.py <旧快照> <新快照> [--facts-only]` | 无非预期差异 |
| 端到端 | `python pipeline.py bio <玩家id>` | 成稿对应段落变化符合预期 |

## 6. 风险与回退

- 施工前 checkpoint：`git rev-parse HEAD` = ……
- 回退口径：源码 `git checkout <checkpoint> -- <文件>`；
  缓存与产物（`output/**/data/*.json`）由熔件重建（`tools/rebuild_folder.py`），不靠 git 复原。

## 7. 待确认

1. ……（需要用户拍板的选择，每条给出默认建议）
```

## 落档的取证标准

1. 每条断言带锚点：代码给 `文件:行`，数据给文件路径与字段，运行给完整命令与关键输出。
2. 数字写实测值（含年份/单位/币种），推断值明确标「估算」并写算法。
3. 引用代码只摘判定所需的几行，上下文用行号指回源文件。
4. 用户原话保留原句摘要，逐条编号，与文档小节一一对应，防止施工时漏项。
5. 取证文件与探针脚本按 `.agents/skills/log-version-folders` 落 `logs/vXXX/`，
   文档里引用新路径（`logs/vXXX/vXXX_*.txt`），长输出不要贴进对话。

## 上下文纪律

1. **先写文档，再动代码**：文档落盘后，对话里只回「结论 + 方案要点 + 文档路径」，
   单条回复控制在十几行内。
2. **后续轮次先读文档**：同一主题的施工/返工/追问，第一步
   `read docs/方案_vXXX_<主题>.md`，再按需回源文件核对行号。
3. **长材料进文件**：超过二十行的日志、测试输出、代码清单写进文档或 `logs/vXXX/`，
   对话里引用路径与行号。
4. **文档随施工更新**：方案变了同步改文档；施工完成后把「验证结果」与「实际改动文件」
   补进第五节，状态改为「已确认并实施」。
5. **交付时给路径**：回复里用 `docs/方案_vXXX_<主题>.md` 的 Markdown 链接指向文档，
   用户可直接打开复核。

## 子代理调研的落档要求

派 subagent 前，在任务描述里写死三件事：

1. 调研范围与要回答的问题清单；
2. 结论写到 `docs/方案_vXXX_<主题>.md`（或 `docs/调研_vXXX_<主题>.md`），每条带 `文件:行`；
3. 回复只给 5–10 行摘要 + 文档路径，细节留在文档里。

同时交代读数据的纪律：先看 `output/<家族>/data/` 里有没有现成熔件/快照，
用 `tools/tests/snap.py` 落快照，**不重熔、不跑 `rebuild-cache`**（见 `snapshot-testing`）。
子代理返回后，把摘要并入主文档再施工；对话里只留摘要与文档路径。

## 与其它技能的关系

- 施工前 checkpoint 与分步提交：`.agents/skills/commit-before-destructive`。
- 测试与核对走已落盘快照、按需 `snap.py`：`.agents/skills/snapshot-testing`。
- 探针脚本与取证文件放 `logs/vXXX/`、与文档同号：`.agents/skills/log-version-folders`。
- 提示词正向表述、程序优先：`.agents/skills/no-negative-prompts`。
- 查游戏机制 / 本地化键 / 存档字段：`.agents/skills/ck3-game-source`（先看已落档调研索引）。
- 文档编码：`.agents/skills/utf8-gbk-encoding`。

## 收尾自查

1. 本轮调研有没有对应的 `docs/方案_vXXX_*.md`？路径写进回复了吗？
2. 用户原话是否逐条进了「需求对照」表，每条都有验收标准？
3. 根因与方案是否都带 `文件:行` 与实测数字？
4. 文档里的「验证」小节是否给了可直接复制的命令与期望值？
5. 文档里的取证路径是不是 `logs/vXXX/` 新路径，版本号与 `logs/vXXX/`、提交信息一致？
6. 对话里是否只留了结论与路径，细节都落在文档里？
