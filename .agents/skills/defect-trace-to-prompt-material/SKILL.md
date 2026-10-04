---
name: defect-trace-to-prompt-material
description: >-
  Use whenever this CK3 biography project has a defect reported in generated prose under
  output/<家族>/*.md — a wrong number, an invented person or office, a garbled kinship relation,
  an empty or missing section — and the root cause must be established before any fix. The rule
  is: trace four layers in order (prose → logs/prompts.log → the block-builder material threshold
  in biography.py → the fact-layer field in facts.py), prove each layer with a grep hit-count or a
  file:line citation, classify the defect as model invention vs. dropped material row vs. missing
  source field, sample large melts only with grep -o field extraction, and land the result as
  docs/方案_vNN_*.md in the project's fixed section format, then wait for user approval before
  editing code.
---

# 成稿缺陷回溯到提示词素材面（defect-trace-to-prompt-material）

用户报「成稿里这句话不对」时，本技能给出**从病句一路回溯到事实层字段**的固定路径，
以及回溯结论的固定落档格式。目标：每条断言都有 `文件:行` 或 grep 命中数支撑，
改代码之前先证明根因在哪一层。

## 适用范围与分工

本技能只管**回溯路径**与**方案文档格式**。其余交给既有技能，不在此重复：

| 事项 | 归属 |
| --- | --- |
| 快照/熔件成本分级、`snap.py`、`snapdiff.py`、断言跑法 | `.agents/skills/snapshot-testing` |
| prompt-last 铁律、提示词正向措辞 | `.agents/skills/no-negative-prompts` |
| 查游戏机制、本地化键、存档字段含义 | `.agents/skills/ck3-game-source` |
| 破坏性改动前的 checkpoint 提交 | `.agents/skills/commit-before-destructive` |
| 日志/文档编码 | `.agents/skills/utf8-gbk-encoding` |

## 四层回溯（顺序固定，逐层留证）

### 第 1 层 · 成稿：把病句钉到 `文件:行`

```bash
grep -n "病句片段" output/<家族>/*.md
```

记下**篇名 + 节序 + 行号**。终传与十年传分开查；同一缺陷常在多篇复现，
复现范围本身就是线索（全篇复现 → 事实层；单节复现 → 板块器）。

### 第 2 层 · 提示词日志：这个数字/人名到底下发过没有

`logs/prompts.log` 是**唯一**能证明「模型看到的是什麼」的证据。

```bash
grep -c "1020" logs/prompts.log          # 命中数
grep -n "洪托马斯" logs/prompts.log | head -20
```

再定位那一节的素材块，看 `相关事实：` 后面**有没有内容**：

```bash
grep -n "相关事实：" logs/prompts.log
```

> v99 实例：`grep 1020 logs/prompts.log` → **0 命中**，而《教宗国历代记》第 3 节的
> `相关事实：` 后面**什么都没有**，`style.py` 的 `mid_last` 却承诺了生卒/继位/在位年数/
> 疆域/治所/任期五类素材 ⇒ 模型整节凭空编。

### 第 3 层 · 板块器门槛：素材为什么没下发

素材为空几乎都是**门槛把行丢了**，不是数据没有。查这几处（行号会漂移，见下节）：

| 锚点 | 作用 |
| --- | --- |
| `biography.py` `def _set_block` | 无料即不下发该块（空块的来源） |
| `biography.py` `def _chrono_usable` | period 级门槛 |
| `biography.py` `def _chrono_row_chunks` | 行切块；**固定行数切块会让末块只剩一两行** |
| `biography.py` 的 `_ok = ...` 素材门槛 | 逐行决定收不收 |
| `facts.py` `def _chrono_ruler_line` | 行文本与其 `rows_detail` 判据 |

**先过滤还是先切块，是本轮的真根因之一**：固定 4 行切 9 行 → `[0:4][4:8][8:9]`，
末块只有传主自己那一行，再被门槛丢掉 ⇒ 末节 0 行 ⇒ `_set_block` 不被调用 ⇒ `相关事实：` 为空。

### 第 4 层 · 事实层字段：门槛为什么判 False

顺着 `rows_detail` 的判据追到具体字段。v99 的完整链条：

```
facts.py `_chrono_ruler_line` 要求 dead_bits（卒年）
  → 卒年只读 characters[].death
  → pipeline._backfill_tail_deaths 明文跳过玩家（if cid2 == str(pid): continue）
  → 传主之死只在 cache["player_death"] 里
  → facts._char_death_date 已实现回退链，但 _chrono_ruler_line 没用它
```

**「回退链已存在但调用方没用」是本项目的高频根因**——追到字段缺失时，先 grep
一遍是否已有现成的取值函数（`_char_death_date`、`person_label`、`death_clause`），
再决定是补数据还是改调用方。

## 三分判定（第 2 层的产出决定改哪里）

| 证据形态 | 判定 | 改哪一层 |
| --- | --- | --- |
| 病句里的数字/人名在 `prompts.log` **0 命中** | 模型虚构 | 补素材（第 3/4 层），让该节有料可写 |
| `prompts.log` 有料，但那一节 `相关事实：` **为空** | 素材门槛丢行 | 板块器门槛 / 切块顺序 |
| `prompts.log` 有料且该节有料，成稿仍读错 | 素材本身缺字段或措辞歧义 | 事实层字段与渲染 |

判定结果直接决定 `no-negative-prompts` 的 prompt-last 走向：**三种都改程序端**，
提示词一句不加。若追到「存档根本没留这个痕」（如 v99 的婚姻主婚人），
结论是**无事实可补**，据实写进方案文档的「本轮不做」，不要用提示词兜底。

## 熔件只许 `grep -o` 抽样

熔件 `output/<家族>/data/melt_*.json` 实测**已达 287MB**（`snapshot-testing` 记的 70–125MB
是早期口径）。整载一次 1–3 分钟，而**抽字段形态只要几秒**：

```bash
time grep -o '"nickname_text":"[^"]*"' output/<家族>/data/melt_*.json \
  | sort | uniq -c | sort -rn | head -20
```

实测：287MB 熔件上 **5.1 秒**，直接得到 `143898` 条空值 + 「狼/猎人/诚实者…」的分布。

**规矩**：想知道「这个字段在存档里长什么样、有没有值、取值分布如何」，一律 `grep -o` 抽样；
只有在需要跨字段联合断言时才走 `snapshot-testing` 的快照路径。**回溯阶段绝不整载熔件。**

## 锚点一律重新 grep（已实测漂移）

本技能与 `docs/方案_*.md` 里引用的行号**都会随版本漂移**。同一批锚点，
方案文档记 `biography.py:1520` / `facts.py:20635`，本次实测已在
**`biography.py:1524`** / **`facts.py:20630`**。

⇒ 引用前一律重新定位，**引用符号名而不是行号**：

```bash
grep -n "_ok = (_r.count" biography.py
grep -n "dead_bits = \[\]" facts.py
```

落档时给 `文件:行`，但那一行必须是本轮 grep 出来的。

## 落档：`docs/方案_vNN_<家族><N>问题.md`

`docs/` 下已有 **59** 份方案文档，章节格式稳定（v98/v99 完全一致）。新建时照抄骨架：

```markdown
# 方案 vNN · `output/<家族>` <N>问题（短标题 / 斜杠分隔）

用户 <YYYY-MM-DD> 报：
1. <用户原话，逐字引用>
…
对象：`output/<家族>`，传主 <名>（pid <id>），终传 `<文件名>.md`。

**本轮全部改在程序端（事实层 / 板块器 / 渲染），提示词一句不加、不改。**

## 0. 结论速览
| # | 用户看到的话 | 根因 | 落地 |

## 1. 取证
### 1.1 …（每条断言带 logs:行 或 文件:行 引用）

## 2. 方案
### 2.1 修问题 1（…）

## 3. 验证计划（按 `snapshot-testing`，全程秒级断言，不重熔）

## 4. 本轮不做（记录在案）

## 5. 实施记录（定稿后补）
```

配套约定：

- **0 节是速览表**，一行一个问题，`用户看到的话` 用逐字引用，`根因` 写到字段级。
- **1 节每条断言都要有引用**：`logs/prompts.log:3660-3700`、`biography.py:1524`、
  `output/<家族>/<篇>.md:400`。无引用的断言删掉。
- 本轮诊断证据写 `logs/vNN_*.txt`（UTF-8），诊断快照写 `output/<家族>/data/vNN_diag.json`；
  `logs/` 根目录只留程序自写的三个运行时日志，历轮取证在 `logs/archive/`（详见 `snapshot-testing`）。
- **5 节在定稿后补**，记录实际改了什么、验证结果、以及核对时顺带发现的附带修。
- 用户报的原话即使后来发现是同一个根因，也**按用户编号逐条保留**，便于回对。

## 等批准再动工

方案文档写完即停，**等用户批准**再改代码。批准前只做只读动作（grep / read / 快照断言）。

派子代理去查证时，prompt 里必须写死四件事：
**落档路径**（`docs/调研_vNN_*.md` 或 `logs/vNN_*.txt`）、**引用格式**（`文件:行`）、
**不许整载熔件**、**回复字数上限**。

> 本轮教训：后台子代理的产出在上下文压缩后丢失，只能重派。结论**只有落进文件才算存在**，
> 子代理回复正文不是产出。

## 收尾自查

1. 四层是不是每层都留了证据？（`文件:行` / grep 命中数 / 抽样分布）
2. 三分判定选了哪一支，依据是不是 `prompts.log` 的命中数而非直觉？
3. 引用的行号是不是本轮 grep 出来的，不是从旧文档抄的？
4. 回溯过程中有没有整载过熔件？（有就是浪费，改用 `grep -o`）
5. 结论落进 `docs/方案_vNN_*.md` 了吗？子代理的调研落进文件了吗？
6. 是不是**在等用户批准**，没有提前改代码？
