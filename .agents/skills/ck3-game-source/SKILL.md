---
name: ck3-game-source
description: >-
  Use whenever this CK3 biography project needs to look up a game mechanic, an
  opinion/memory/hook key, a localization string, a merchant/trade question, or any
  "why does the save say X" question — before grepping the game install or the wiki.
  The rule is: AUH (All Under Heaven / TGP 天命) and EP5 (Silk & Silver 丝绸与白银，
  可扮演商人) are BASE-GAME content shipped under game/, not mods, so read game/ directly.
---

# 读游戏机制先看这里（ck3-game-source）

本技能用于本项目（CK3 家传 · 纪传体传记生成）的**一切游戏机制检索**：
查脚本、查本地化、查「存档里这个键是什么意思」。**先读本技能，再动手 grep。**

## 铁律一：AUH 与 EP5 都是游戏本体内容，不是 Mod

**1.20 起可扮演商人来自 EP5《Silk & Silver（丝绸与白银）》；
AUH（All Under Heaven / 天命 TGP）仍是本体 DLC 内容。
两者的脚本都直接铺在 `game/` 下，`game/dlc/dlc*` 目录通常只有美术/音频资产。**

| 事实 | 值 |
| --- | --- |
| 游戏根 | `%CK3_GAME_DIR%`（即 CK3 安装目录下的 `game/`，可由 `config.json` 的 `ck3_game_dir` 指定，留空则自动发现） |
| 版本 | **1.21.0**（`clausewitz_branch.txt` = `titus/release/1.21.0`） |
| AUH/TGP 的 DLC | `DLC022_EP4` = All Under Heaven；目录 `game\dlc\dlc022_ep4`（仅资产，脚本在本体） |
| AUH 的互动脚本 | `game\common\character_interactions\10_tgp_interactions.txt`、`tgp_east_asia_interactions.txt`、`10_tgp_japan_interactions.txt` |
| AUH 的事件 | `game\events\dlc\tgp\*.txt` |
| AUH 的本地化 | `game\localization\simp_chinese\dlc\tgp\*.yml` |
| EP5 的 DLC | `DLC031_EP5` = Silk & Silver；目录 `game\dlc\dlc031_ep5`（仅资产） |
| EP5 的脚本前缀 | **`gdp_`**（内部代号；不要去找 `ep5_` / `silk_`） |
| EP5 的事件 | `game\events\dlc\gdp\*.txt` |
| EP5 的本地化 | `game\localization\simp_chinese\dlc\gdp\*.yml` |
| EP5 的开局书签 | `game\common\bookmarks\bookmarks\00_bookmarks.txt:3948`（`bm_1066_merchants`）、`:4078`（`bm_1178_merchants`），均 `requires_dlc_flag = silk_and_silver` |

> **更正旧记录**：`dlc029_mp1` 是《Songs of the Realm》音乐包，不是 AUH。
> AUH 是 `DLC022_EP4`。查 AUH 机制仍然直接读 `game/`（`tgp_` 前缀）。

⇒ **检索机制时直接读 `game/`**，不必去找「哪个 Mod 提供了天命/商人」——
`tgp_` / `celestial_` / `is_noble_family_title`，以及 `gdp_` / `merchant_company` /
`trade_post` 这些前缀，和 `game/dlc/dlc*` 目录，**都是本体**。

Mod 另有其地：

* 工坊订阅：`<Steam 库>\steamapps\workshop\content\<CK3_appid>\<id>\`；
* 用户 mod 目录：`%USERPROFILE%\Documents\Paradox Interactive\Crusader Kings III\mod\`；
* 实际启用项记在 `…\Documents\Paradox Interactive\Crusader Kings III\launcher-v2.sqlite`；
* 本项目 `localization.py` 已按「模块指纹比对 → 自动重建本地化表」处理启用 Mod 的本地化覆盖，
  查某个键为何不是预期中文时，先看是否是某个启用的 Mod 压掉了本体文案。

## 铁律二：先查已落档的调研，别重跑

**顺序**：① 本项目 `docs/` 下已有的本地调研（该目录只留本机，不进版本库）
→ ② CK3 wiki（`https://ck3.paradoxwikis.com/Crusader_Kings_III_Wiki`）
→ ③ `game/` 原文（引用一律给 `文件:行`）。

已落档的调研（**先看这些**）：本机 `docs/` 目录下按主题分文件存放
（`调研_*.md` 机制取证、`方案_v*_*.md` 各轮问题的根因与判据、`研究_v*_*.md` 专项结论）。
该目录**只留本机、不进版本库**，用 `glob`/`grep` 在 `docs/` 里按关键词找。

商人/贸易专项先看：

* `docs/方案_v150_培根_家训市场商路营规.md` —— 商路存取、商会继承法、议会官职、价格公式；
* `docs/方案_v151_培根_物价与隐事.md` —— 物价与市场快照。

## 商人 / 贸易机制速查（1.20+ / EP5）

| 想查什么 | 去哪 |
| --- | --- |
| 两种商人政体 | `common\governments\00_government_types.txt:72` `republic_government`（有地贵族共和国）、`:1554` `merchant_government`（无地商会） |
| 商会宅邸 | `common\domiciles\types\00_domicile_types.txt:3223` `merchant_company`；建筑在 `common\domiciles\buildings\00_merchant_company_buildings.txt` |
| 贸易站 | `common\districts\trade_post_districts.txt`、`common\buildings\trade_post_buildings\*.txt` |
| 贸易商品与基价 | `common\trade\trade_good_types\basic_trade_goods.txt` |
| 市场关税档位 | `common\trade\trade_market_toll_levels\00_toll_levels.txt` |
| 共和法 / 议会 | `common\laws\04_republic_laws.txt`（`republic_type_*:15`、`republic_tier_*:747`、`assembly_*:1139`） |
| 共和国选举 / 继任 | `common\succession_appointment\republic_governor.txt:1` |
| 家族雄心 | `common\house_aspirations\gdp_republic_ambitions.txt` |
| 商人互动 | `common\character_interactions\11_gdp_merchant_interactions.txt`、`gdp_republic_interactions.txt`、`00_gdp_guelph_ghibelline_interactions.txt` |
| 事件 / 决策 / on_action | `events\dlc\gdp\*.txt`、`common\decisions\dlc_decisions\gdp\*.txt`、`common\on_action\dlc\gdp\*.txt` |
| 评价（opinion） | `common\opinion_modifiers\11_dlc_gdp_opinions.txt:5`、`gdp_republic_opinions.txt`、`00_gdp_guelph_ghibelline_opinions.txt` |
| 记忆（memory） | `common\character_memory_types\gdp_memories.txt`（如 `:210` `became_merchant_memory`） |
| 商人头衔 | `common\landed_titles\01_patrician_and_merchant_families.txt:12` 起的 `c_merchant_*` |
| 商战 / 共和战争 | `common\casus_belli_types\gdp_merchant_wars.txt`、`gdp_republic_wars.txt` |

判据要点：

1. **商人分两种政体，别混**：`merchant_government` = 无地商会（`landless_playable`、
   `cannot_be_vassal_or_liege`、宅邸 `merchant_company`）；`republic_government` = 有地贵族共和国
   （主城 `city_holding`、`treasury`、议会、家族雄心）。判「是不是商人」看 flag：
   `government_is_merchant` / `government_is_republic` / `government_has_merchant_company`，
   不要只看头衔名。
2. **商人头衔是无地郡级**：`c_merchant_*` 是 `is_landless_type_title` 的伯爵级头衔，
   不要按有地伯爵算领地、继承或城堡。
3. **存档不存商品价格**：1.21 只有市场供需与商路成交价
   （`trade_routes.*.transactions.price_per_unit`）；价格由「基价 + 繁荣 + 修正」现算。
   商品基价读 `common\trade\trade_good_types\basic_trade_goods.txt`，
   实现见 `market_prices.py:88`；熔件顶层字段是 `trade_routes` / `trade_markets`。
4. **「商会」「商站」「商路」不是一件事**：商会 = `merchant_company`（domicile）；
   商站/贸易站 = `trade_post`（district/building）；商路 = `trade_route`（存档顶层数据）。

## 检索姿势（省时间的几条）

1. **本地化是取词的权威**：脚本里给的是键，中文文案在
   `game/localization/simp_chinese/**/*.yml`（商人内容在 `.../dlc/gdp/*.yml`）。
   查一个键的中文名用 `Select-String -Pattern '^\s*<key>:'`，别凭英文猜。
2. **`common/opinion_modifiers/*.txt` 是「谁对谁做了什么」的权威表**：
   一个 modifier 的 `years` / `decaying` / `imprisonment_reason` 等标记决定它在存档里能活多久；
   **带 `decaying` 的评价会过期，持有者一死立即消失** —— 判据设计必须先读这张表。
   商人评价另见 `11_dlc_gdp_opinions.txt`。
3. **方向看脚本，不看字段名顺序**：`add_opinion = { target = X }` 写在角色 A 的作用域内 =
   **A 持有对 X 的看法**；`reverse_add_opinion` 方向相反。归档时把 `owner/target` 写清楚。
4. **`common/on_action/*.txt` 决定「记忆是谁、什么时候被创建的」**：
   想判「这件事有没有留痕」，先找对应的 on_action，而不是逐个事件翻。
   商人专项在 `common/on_action/dlc/gdp/`。
5. **引用行号会随版本漂移**：本机是 **1.21.0**；`docs/` 里 1.19 时代记的行号先核一遍再用
   （已发生过「用户给的 7600–8700 段其实是 castrate/blind 互动，不是 release_from_prison」这类偏差，
   以及 `dlc029_mp1` 被误记成 AUH）。
6. **子代理调研要落档**：派 subagent 去查机制时，要求它把结论写进本机 `docs/调研_*.md` 并给
   `文件:行` 引用，避免下次重跑。
7. **`gdp_` 是 EP5 的内部前缀**：事件、决策、触发、脚本效果都按它命名；
   DLC 目录名却是 `dlc031_ep5`。两套命名都要认。

## 收尾自查

1. 这次查的机制，`docs/` 里真的没有吗？
2. 结论里每条断言都有 `game/` 的 `文件:行` 吗？
3. 有没有把 AUH 或 EP5 的 `gdp_` 内容当成 Mod 去找？
4. 涉及评价/记忆的判据，有没有核对它的 `years`/`decaying` 与持有者存活期？
5. 商人问题有没有区分 `merchant_government`（无地商会）与 `republic_government`（有地共和国）？
6. 是否在存档里找商品价格？（找不到；价格是现算的）
7. 引用行号是否按本机 **1.21.0** 核过？
