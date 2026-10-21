---
name: log-version-folders
description: >-
  Use whenever writing, moving, or looking up a test/probe/verify script for a new
  iteration of this CK3 biography project — before creating any file under logs/,
  tools/tests/, or experiments/. The rule is: one folder per version (D:\Roman\logs\vXX\),
  the version's scripts AND their outputs live in that same folder, filenames keep the
  `vXX_` prefix, and the logs/ root is reserved for the three runtime logs that llm.py
  writes (journal.log / prompts.log / loc_miss.log).
---

# 一版一夹：版本脚本归入 logs/vXX（log-version-folders）

本技能用于本项目（CK3 家传 · 纪传体传记生成）**每一轮迭代的测试脚本与取证文件**。
2026-10-21（v126 整理）起生效，取代 `snapshot-testing` 旧条款「本轮新证据写 `logs/vNN_*.txt`」与
「测试脚本一律放 `tools/tests/`」。

## 硬规则

1. **位置**：新版本的测试/探针/核对脚本写进 `D:\Roman\logs\vXX\`，`XX` 为该轮版本号
   （与 `docs/方案_vXX_*.md`、`tools/tests/verify_vXX.py` 同号；三位数照写 `v107`，不写成 `v7`）。
   版本夹不存在就先建。
2. **脚本与其输出同夹**：`vXX_probe_<主题>.py` 产出的 `.txt` / `.json` / `.tsv` / `.png`
   写回同一个 `logs\vXX\`，不落 `logs\` 根、不落 `tools\`。
3. **文件名带版本前缀**：`vXX_probe_*.py`、`vXX_check_*.py`、`vXX_<主题>.mjs`。
   没有版本号的临时脚本放 `logs\_unsorted\`；一旦明确属于某轮，就搬进对应版本夹并补前缀。
4. **`logs\` 根只放三个运行时日志**：`journal.log`、`prompts.log`、`loc_miss.log`
   由 `llm.py` 固定路径写入，任何整理都不移动、不删除。
5. **`tools/tests/` 只留基础设施**：`snap.py`、`snap_at_head.py`、`snapdiff.py`、
   `verify_fast.py`、`check_bio_*.py`、`audit_*.py` 这类跨版本复用的工具留在原地；
   一次性探针与专项核对按规则 1 进版本夹。
6. **编码**：`.py` / `.txt` / `.json` 一律 UTF-8（读写两侧显式写 `encoding="utf-8"`），
   `.bat` 才是 GBK —— 详见 `.agents/skills/utf8-gbk-encoding`。

## 脚本模板（路径一次写对）

版本夹 `logs\vXX\` 与 `tools\tests\` **深度相同**（文件 → 夹 → logs/tools → 项目根），
所以三层 `dirname` 的写法两边通用；更稳的写法是从脚本自身位置推：

```python
# -*- coding: utf-8 -*-
"""v126: 只读 XX 段，回答「YY 为什么是 ZZ」。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))   # D:\Roman\logs\v126
ROOT = os.path.dirname(os.path.dirname(HERE))       # D:\Roman
OUT = os.path.join(HERE, "v126_probe_xx.txt")       # 输出落版本夹
sys.path.insert(0, ROOT)

import cache_lib as cl  # noqa: E402
```

- 用 `HERE` 派生输出路径，脚本挪到别处也不会写错目录。
- 引用项目数据用 `os.path.join(ROOT, "output", ...)`，不要写死盘符
  （`r"D:\Roman\..."` 只允许出现在已有一次性脚本里）。
- 跑法：`& tools\py.ps1 logs\v126\v126_probe_xx.py`（在项目根目录执行）。

## 查已有取证：先看版本夹

按版本号找，不要先翻 `logs/` 根：

```powershell
Get-ChildItem logs\v125 | Select-Object Name, Length, LastWriteTime
Select-String -Path logs\v125\*.txt -Pattern '关键词'
```

跨版本找同一主题时，先看 `logs\README.md` 的版本清单（每版夹的文件数、脚本、方案文档链接），
再进具体夹。迁移台账在 `logs\_index\move_manifest.tsv`（旧路径 → 新路径），
旧笔记里若还写着 `logs/v110_after.json`，到台账里查它现在的位置。

## 引用路径：写新路径

- 文档、注释、方案里引取证文件一律写新路径：`logs/v110/v110_death_place_diff.txt`，
  **不要**再写 `logs/v110_death_place_diff.txt`。
- 代码里读写取证文件同样走版本夹，例如 `logs/v122/v122_probe_mem.txt`；
  写新脚本时直接按规则 2 落在本版夹内。
- `logs/_index/unresolved_refs.tsv` 列的 108 条是**迁移前就已失效**的历史引用
  （早期探针输出早已清理），别把它们当成「搬迁搬坏了」去修；重跑对应探针才会重新生成。

## 与本项目其它技能的关系

- **取证与快照**：`.agents/skills/snapshot-testing` 管「用快照不重熔」，本技能管「证据放哪」。
  两份技能的路径条款已对齐：本轮证据在 `logs\vXX\`，不再写 `logs\vNN_*.txt`。
- **动手前先提交**：`.agents/skills/commit-before-destructive`。
  批量搬动/改名/覆盖前先 `git status --short` + 提交检查点。
- **编码与子进程**：`.agents/skills/utf8-gbk-encoding`；跑 Python 用 `tools\py.ps1`。
- `logs/README.md` 是本技能的落地版目录说明，改约定时两处同步。

## 迁移与撤销（2026-10-21 已做）

- 453 个文件 + 2 个目录从 `logs\` 根迁入 `logs\v86…v125\`，台帐
  `logs\_index\move_manifest.tsv` 逐条记录旧路径与新路径。
- 撤销：按台账逆序把「新路径」搬回「旧路径」，没有任何文件被删除。
- 同轮把 350 处旧路径引用改成新路径（git 跟踪 70 文件 / 107 处；`docs/`、`cache/`、
  `experiments/` 为本机未跟踪目录，也一并改了）。

## 收尾自查

1. 新脚本放在 `logs\vXX\` 而不是 `logs\` 根或 `tools\tests\` 吗？
2. 输出是否也落在同一个版本夹，而不是项目根或 `logs\` 根？
3. 文件名带 `vXX_` 前缀、和 `docs/方案_vXX_*.md` 同号吗？
4. 路径是 `HERE`/`ROOT` 派生，还是又写死了 `D:\Roman`？
5. 三个运行时日志有没有被误搬、误覆盖？
6. 引用取证时写的是 `logs/vXX/vXX_*.txt` 新路径吗？
