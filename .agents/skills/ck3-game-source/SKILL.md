---
name: ck3-game-source
description: >-
  Use whenever this CK3 biography project (<项目根>) needs to look up a game mechanic, an
  opinion/memory/hook key, a localization string, or any "why does the save say X" question —
  before grepping the game install or the wiki. The rule is: AUH (All Under Heaven / TGP 天命) is
  BASE-GAME content shipped under game/, not a mod, so read game/ directly; and check the existing
  docs/调研_*.md first so the same research is not redone.
---

# 读游戏机制先看这里（ck3-game-source）

本技能用于本项目（`<项目根>`，CK3 家传 · 纪传体传记生成）的**一切游戏机制检索**：
查脚本、查本地化、查「存档里这个键是什么意思」。**先读本技能，再动手 grep。**

## 铁律一：AUH 是游戏本体内容，不是 Mod

**`All Under Heaven`（AUH）= 天命 TGP，是本机游戏本体（1.19）自带的 DLC 内容。**

| 事实 | 值 |
| --- | --- |
| 游戏根 | `<CK3安装目录>\steamapps\common\Crusader Kings III\game` |
| 版本 | **1.19.0**（`clausewitz_branch.txt` = `titus/release/1.19.0`） |
| AUH/TGP 的 DLC 目录 | `game\dlc\dlc029_mp1` |
| AUH 的互动脚本 | `game\common\character_interactions\10_tgp_interactions.txt`、`tgp_east_asia_interactions.txt`、`10_tgp_japan_interactions.txt` |
| AUH 的事件 | `game\events\dlc\tgp\*.txt` |
| AUH 的本地化 | `game\localization\simp_chinese\dlc\tgp\*.yml` |

⇒ **检索机制时直接读 `game/`**，不必去找「哪个 Mod 提供了天命」——
`tgp_` / `celestial_` / `is_noble_family_title` 这些前缀，以及 `game/dlc/dlc*` 目录，
**都是本体**。

Mod 另有其地，不要在那里找 AUH：

* 工坊订阅：`<Steam库>\steamapps\workshop\content\<CK3_appid>\<id>\`；
* 用户 mod 目录：`%USERPROFILE%\Documents\Paradox Interactive\Crusader Kings III\mod\`（本机为空）；
* 实际启用项记在 `…\Documents\Paradox Interactive\Crusader Kings III\launcher-v2.sqlite`；
* 本项目 `localization.py` 已按「模块指纹比对 → 自动重建本地化表」处理启用 Mod 的本地化覆盖，
  查某个键为何不是预期中文时，先看是否是某个启用的 Mod 压掉了本体文案。

## 铁律二：先查已落档的调研，别重跑

**顺序**：① 本项目 `docs/` 下已有调研 → ② CK3 wiki（`https://ck3.paradoxwikis.com/Crusader_Kings_III_Wiki`）
→ ③ `game/` 原文（引用一律给 `文件:行`）。

已落档的调研（**先看这些**）：

| 文档 | 内容 |
| --- | --- |
| `docs/调研_出狱机制与存档留痕.md` | 出狱机制全表（手动/自动/Mod）、13 条「无留痕」清单、诛灭世族脚本逐行、判据优先级 |
| `docs/研究_v47_剪除规则实证.md` | 存档剪除规则 |
| `docs/研究_v47_统治者头衔动态.md` | 头衔持有/更替 |
| `docs/研究_v47_文化信仰存档来源.md` | 文化/信仰的存档来源 |
| `docs/研究_v45_亲缘定语.md` / `研究_v45b_中式亲属.md` | 中式亲属称谓 |
| `docs/研究_v49_加载性能与优化.md` | 熔件加载 |
| `docs/方案_v4x/v5x_*.md` | 各轮问题的根因与判据（含游戏脚本引用） |

## 检索姿势（省时间的几条）

1. **本地化是取词的权威**：脚本里给的是键，中文文案在
   `game/localization/simp_chinese/**/*.yml`。查一个键的中文名用
   `Select-String -Pattern '^\s*<key>:'`，别凭英文猜。
2. **`common/opinion_modifiers/*.txt` 是「谁对谁做了什么」的权威表**：
   一个 modifier 的 `years` / `decaying` / `imprisonment_reason` 等标记决定它在存档里能活多久；
   **带 `decaying` 的评价会过期，持有者一死立即消失** —— 判据设计必须先读这张表。
3. **方向看脚本，不看字段名顺序**：`add_opinion = { target = X }` 写在角色 A 的作用域内 =
   **A 持有对 X 的看法**；`reverse_add_opinion` 方向相反。归档时把 `owner/target` 写清楚。
4. **`common/on_action/*.txt` 决定「记忆是谁、什么时候被创建的」**：
   想判「这件事有没有留痕」，先找对应的 on_action，而不是逐个事件翻。
5. **引用行号会随版本漂移**：本机是 1.19；`docs/` 里别人给的行号先核一遍再用
   （已发生过「用户给的 7600–8700 段其实是 castrate/blind 互动，不是 release_from_prison」这类偏差）。
6. **子代理调研要落档**：派 subagent 去查机制时，要求它把结论写进 `docs/调研_*.md` 并给
   `文件:行` 引用，避免下次重跑。

## 收尾自查

1. 这次查的机制，`docs/` 里真的没有吗？
2. 结论里每条断言都有 `game/` 的 `文件:行` 吗？
3. 有没有把 AUH 当成 Mod 去找？（不需要，读 `game/` 即可）
4. 涉及评价/记忆的判据，有没有核对它的 `years`/`decaying` 与持有者存活期？
