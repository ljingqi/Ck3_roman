---
name: commit-before-destructive
description: Use whenever a change to this CK3 biography project (D:\Roman) touches production code or regenerable-but-expensive artifacts — editing facts.py / biography.py / cache_lib.py / pipeline.py / localization.py / style.py / llm.py / htmlview.py, rebuilding data/*.json or output/**/data/*.json, running rebuild-cache / migrate / rebuild, or deleting or overwriting existing files. The rule is: commit the current working tree as a checkpoint first, so every later step can be rolled back cleanly.
---

# 破坏性改动前先 commit（commit-before-destructive）

本技能用于本项目（`D:\Roman`，CK3 家传 · 纪传体传记生成）以及本会话中的一切代码改动。
核心规则：**动手改生产代码或重建产物之前，先把当前工作树提交为一个检查点；改动分步进行，每步一个提交。**

## 什么是「破坏性改动」

命中任意一条即属本技能的适用范围：

- 编辑生产代码：`facts.py`、`biography.py`、`cache_lib.py`、`pipeline.py`、
  `localization.py`、`style.py`、`llm.py`、`htmlview.py`、`build_names.py`、`flavorization.py`；
- 重建静态表：`data/localization.json`、`data/trait_names.json`、`data/trait_tracks.json`、
  `data/court_positions.json`、`data/council_tasks.json`、`data/currency_levels.json`、
  `data/names.json`、`data/dynasties.json`、`data/province_map.json`、`data/hook_types.json`、
  `data/doctrine_parameters.json`；
- 重建战役数据：`output/<家族>/data/player_*.json`、`melt_*.json`、`snap_*.json`；
- 覆盖或删除既有文件；批量改名；`pipeline.py rebuild-cache` / `migrate` / `htmlview.py rebuild`。

## 执行顺序

1. **看工作树**：`git status --short` 与 `git diff --stat`。
2. **有未提交改动 → 先提交检查点**：
   `git add -A && git commit -m "checkpoint: <一句话说明当前状态>"`。
   这一步的价值在于：任何后续一步走坏，都能用 `git checkout <该提交> -- <文件>` 干净回退。
3. **工作树干净 → 记下回退点**：`git rev-parse HEAD`，把该哈希写进本轮工作记录。
4. **动手改动**，一步一个提交，提交信息写清「改了什么 + 哪条验证通过」，例如
   `fix(v34): 共享前缀剥离实父通道 — verify_v34 第 1 条通过`。
5. **每步提交后立即验证**：跑对应断言（`tools/verify_fast.py`、`experiments/verify_v34.py`、
   或该步的专项脚本），把结论写进提交信息或方案文档。
6. **回退口径**：源码 `git checkout <checkpoint> -- <file>`；
   缓存与产物（`data/*.json`、`output/**/data/*.json`）可由熔件重跑，
   但**源码永远从 git 取回**，靠重生成产物来复原。

## 加速口径（本项目的实际痛点）

- 熔件 `output/<家族>/data/melt_*.json` 有 100–125MB，`cache_lib.load_melt()` 每次 1–3 分钟。
  迭代核对时先用 `tools/snap.py <家族> <玩家id> <as_of> [十年] --assert` 落一份 facts 快照
  （几十到几百 KB），随后用 `tools/verify_fast.py` 秒级断言；
  只在里程碑跑一次整载熔件的端到端断言。
- 提交前用 `git status --short` 确认没有把大体积缓存误加进来：
  `.gitignore` 已覆盖 `output/**/data/`、`cache/`、`logs/`。

## 与既有纪律的关系

`README.md`「代码纪律（2026-09-10 用户定规）」已写「每次破坏性改动前必须先 commit」，
本技能是它的可执行版本：触发条件、动作顺序、回退口径三件事写死在技能里，
新会话读到本技能即可照做。

## 收尾自查

1. 本轮动手前，检查点提交存在吗？记下它的哈希了吗？
2. 本轮每一步都有独立提交吗？提交信息里有验证结论吗？
3. 有没有把生产代码的改动混在「重建产物」的提交里？
4. 若某步走坏，`git checkout <checkpoint> -- <file>` 能把它整段撤掉吗？
