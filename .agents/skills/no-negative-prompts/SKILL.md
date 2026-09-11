---
name: no-negative-prompts
description: Use whenever writing, editing, or auditing prompts for this CK3 biography project's LLM generation (biography.py, facts.py, cache_lib.py, pipeline.py prompt strings) or any other prompt in this session — every instruction to the model must be phrased positively, stating what to do, with forbidden-phrasing (不要/避免/禁止/切勿/不得/请勿) converted to positive equivalents, and every requirement the program can satisfy deterministically must be implemented in code or data instead of being written into the prompt.
---

# 提示词正向表述铁律（no-negative-prompts）

本技能适用于本项目（CK3 家传 · 纪传体传记生成）以及本会话中写给模型的任何提示词。**铁律一：任何时候都不使用负向提示词。** 给模型的指令一律用「要做什么」表述，把「不要做什么」改写为正向行为。

## 什么是负向提示词

- 明确禁令词：`不要`、`请勿`、`勿`、`禁止`、`避免`、`切勿`、`不得`、`别`、`严禁`、`不可`、`不再` 等；
- 否定句式：`不要写X`、`避免出现Y`、`禁止使用Z`、`不得虚构数字`；
- 对模型行为的否定约束（即使没有禁令词，如「以资料为准，不要自己编」的后半句仍属负向）。

## 为什么必须正向

1. 模型对否定词执行不可靠：越强调「不要写X」，越容易把注意力钉在 X 上（抑制失效），输出反而更常出现 X；
2. 负向表述留给模型「自我判断空间」，不同轮次行为漂移；正向表述把唯一正确做法写死，输出稳定；
3. 负向措辞容易让模型把禁令当作「可以绕过的前提」，正向表述则是「事实即标准」。

## 正向改写方法

1. **先想清楚「正确做法是什么」**，直接写出那个做法；
2. **给可执行的锚点**：数据来源、字段名、格式、时态、字数；
3. **把「不要编造」改为「以资料给出者为限」**；把「不要写元信息」改为「以资料给出的档位词书写」；
4. 改完后通读一遍，出现任何否定词就重写。

### 对照表（本项目实例）

| 负向写法 | 正向写法 |
| --- | --- |
| 不要写出内部键值 | （程序端渲染期查不到本地化即整句省略，提示词不出现键值话题） |
| 不要编造官职名 | 官职与职位一律按资料给出的显示名书写 |
| 避免模型自行判断语言同异 | （程序端比对语言集，只下发「无共通语，须借通译」这一种情形） |
| 不要虚构伤亡数字 | 伤亡、处决、囚禁一律使用资料给出的日期与死法 |
| 禁止出现「数据缺失」 | 资料不足的内容简写或略去，以已知事实含蓄写作 |
| 不要用表格 | 正文使用自然语言段落，Markdown 分段 |

## 程序优先铁律（prompt-last）

本项目的第二条铁律：**凡程序能确定性完成的事情，一律由程序（代码或数据文件）完成，提示词只承担程序做不到的创作性写作。** 提示词是最后手段，不是第一手段。

### 判定方法

写提示词之前先问一句：**这条要求能否用代码/数据确定性实现？** 能，就改代码或数据；不能（需要文风、叙事、取舍判断），才写进提示词。

### 程序端职责清单（本项目已归程序，新增提示词前先对照）

| 需求 | 程序端做法 | 位置 |
| --- | --- | --- |
| 内部 id / 裸键 / 英文枚举不进提示词 | 渲染期一律查本地化表或兜底表，查不到即整句省略；行级裸键兜底再过滤一层 | `facts.py _clean_ck3_loc` / `_trait_name` / `_death_reason` / `sanitize_fact_text` |
| 同一人全篇同一称谓 | 唯一出词口 `Facts.person_label`（full/brief/event/office 四式） | `facts.py person_label`、`biography._profile_lines` |
| 头衔层级词随政体/Mod 变 | 按政体查本地化键，逐级回退通用表 | `localization.tier_word` |
| 数量类元信息（健康/压力/虔诚/威望/影响力/功勋） | 程序换算档位词，数值不下发 | `facts.health_state_zh` / `stress_state_zh` / `level_word` |
| 货币数值（国库/月入/牧群） | 程序判定是否下发；国库金、月入、牧群数值一律不出现 | `facts._currency_bits` |
| 某人之间能否交谈 | 程序比对语言集，直给「无共通语，须借通译」结论 | `Facts.language_relation_line` |
| 隐事的是非方向（谁在谁主持的考试里舞弊） | 程序按同快照考试记忆判定主考与级别 | `Facts.secret_topic` |
| 职位显示名（私人医生 → 医学博士） | 解析游戏 `court_position_asset.trigger → localization_key` 变体表择名 | `localization.build_court_positions` / `Facts.court_position_word` |
| 启用 Mod 的本地化生效 | 模块指纹比对 → 自动重建本地化表 | `localization.load_localization_table` |
| 恩怨史等游戏原文不可读 | 判为无料后用缓存记忆程序重建该日事件句 | `Facts._feud_event_fallback` |
| 空块 / 占位串（「（无X记录）」） | 无料即不下发该块 | `biography._set_block` |
| 板块增删（无某类素材就不生成该篇） | 程序按数据门槛决定篇目 | `biography.build_articles` |
| 同请求内不重复同块 | 开篇/纪事按模块切片二分 | `facts.MODULE_SLICE` / `biography._article_facts` |
| 死亡表述统一 | 程序出死亡句 | `facts.death_clause` / `_death_sentence` |

### 反例与正例

- 反例：在板块提示词里写「不要写出内部键值」——过滤是程序可做的确定性工作，写进提示词等于把确定性交给模型自觉。
- 正例：渲染期把 `house_relations.history.change_reason` 的不可读占位串判为无料，改由缓存记忆程序重建该日恩怨句。
- 反例：提示词里写「语言相通与否由资料判定」——正例：程序比对语言集，只下发「无共通语，须借通译」这一种情形。
- 反例：提示词里写「职位名按游戏显示书写」——正例：解析 `localization_key` 变体表，程序按雇主政体/层级/传承择名。

### 收尾自查

1. 新增的每条提示词要求，标注它为什么不能在程序端实现；
2. 能在程序端实现的，改成代码/数据改动，并把对应提示词句子删掉；
3. 事实层的确定性改写（改名、换算、替换、去重）优先做在渲染期，输出侧与提示词侧同时受益。

## 本项目排查清单（改完提示词后自查）

在 `biography.py` / `facts.py`（提示词常量与 `SECTION_REQ`）中搜索以下模式，命中处一律改正向：

```
不要|请勿|勿|禁止|避免|切勿|不得|别 |严禁|不可|不再|没有.*才|除非
```

注意误报：`避免` 出现在程序注释/文档中不违规，只有**发给模型的提示词字符串**（`sys_msg` / `user_msg` / `*_RULE` / `SECTION_REQ`）受本规则约束。历史基线：commit `f5c9209 删除负向提示词` 已做过一轮全量清理，新增提示词不得回退。

## 范围界定

- 约束对象：**写给 LLM 的提示词**（`biography.py` 的规则常量、板块要求、user/sys 消息）。
- 不约束：程序注释、文档、日志（但注释里描述模型行为的负向措辞建议一并改写，防止后人抄进提示词）。
- 数据事实层的自然语言不是提示词，不适用；但**事实文本本身也要消除模型误读**——把歧义交给程序端改写（改写措辞、补足方向、换成游戏档位词），比在提示词里写「不要把 A 理解成 B」可靠。
