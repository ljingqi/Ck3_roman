---
name: readme-changelog
description: >-
  Use whenever editing README.md, README.en.md, or CHANGELOG.md in this CK3 biography
  project, or whenever documenting a version change or deciding where user documentation
  belongs. The rule is: README is a user-facing usage guide only (install, configure, run,
  output, FAQ, license); every version update goes to the local-only CHANGELOG.md, which
  .gitignore excludes from GitHub; README.md and README.en.md are kept in sync.
---

# README 只写使用方法，版本沿革进本机 CHANGELOG（readme-changelog）

本技能用于本项目（CK3 家传 · 纪传体传记生成）的一切用户文档改动。2026-11-03 起生效。

## 硬规则

1. **README 面向使用者**：`README.md`（简体中文）与 `README.en.md`（English）只写：
   这是什么、准备什么、怎么配置、怎么启动/续传/封档、输出在哪、阅读页怎么用、常见问题、许可。
   版本历史、问题编号、旧稿对比、内部实现细节、开发纪律一律不进 README。
2. **版本沿革写 `CHANGELOG.md`**：项目根目录的 `CHANGELOG.md` 是唯一版本更新记录处。
   新条目写在最上面，格式见下；每条写清「改了什么 + 为什么 + 验证」。
3. **`CHANGELOG.md` 只留本机**：`.gitignore` 已排除它；任何情况下都不要 `git add -f`，
   不要把它推到 GitHub，也不要在公开 README 里链接它（读者克隆后并没有这个文件）。
4. **中英同步**：改 `README.md` 必须同步改 `README.en.md`，两篇顶部都保留
   `[简体中文](README.md) | [English](README.en.md)` 语言入口；命令、路径、配置字段名以代码为准。
5. **开发纪律不在 README**：提示词 → `.agents/skills/no-negative-prompts`；
   测试与取证 → `.agents/skills/snapshot-testing`、`.agents/skills/log-version-folders`；
   动手前提交 → `.agents/skills/commit-before-destructive`；提示词与代码注释见附则。

## 版本条目模板

```markdown
## v142（2026-11-03）

- **改了什么**：...
- **为什么**：...
- **验证**：...
```

- 版本号与 `docs/方案_vXX_*.md`、`logs/vXX/`、提交信息同号。
- 新条目写在文件顶部；旧条目不重写，勘误直接改对应条目。
- 历史：v96–v141 的详细方案在 `docs/方案_vXX_*.md`（本机，不入库），提交信息见 `git log`；
  v87–v95 与 1.20 适配的旧 README 段落已于 2026-11-03 原样移入 `CHANGELOG.md`。

## README 的边界

**写**：用途一句话、数据流图、准备清单、配置字段、启动方式、命令行、生成节奏、阅读页操作、
目录结构、篇目介绍、Mod 本地化、常见问题、许可。

**不写**：`vNN` 改动清单、旧稿/新稿对比、内部函数名与字段名（配置字段除外）、
问题编号、本机实测数字、测试/取证流程、开发纪律与提示词规则。

> 判断标准：一位只想安装并使用的玩家需要读到的，才留下；只有维护者需要的，去 skill 或 `docs/`。

## 附则：提示词与代码注释纪律（原 README 第八节，2026-11-03 移入）

**提示词**（`style.py` 的常量、`biography.py` 的内联题面）：

- 一律使用**现代标准汉语**书面语，不用半文半白的措辞；
- 一律**正向表述**（写「要做什么」），禁令式措辞不进提示词
  （铁律与改写方法见 `.agents/skills/no-negative-prompts`）；
- 程序能确定性完成的事情一律落在程序端，提示词只承担创作性写作（prompt-last）。

**代码注释**：

- 注释与 docstring 一律用**英语**书写，只保留读懂当前实现所需的信息：职责、参数、
  返回值、非显然的机制与数据来源、性能提示；
- 版本沿革、问题编号、用户拍板记录、旧稿对比一律不进代码 —— 这些留在 `docs/`
  （本地工作文档，不入版本库）、`CHANGELOG.md` 与 git 提交信息里；
- 改完注释后跑一次 `python tools/tests/verify_comments.py <文件>`：它比对工作树与
  基线的 AST（剥掉 docstring 后比较），确认这一轮只动了注释、没有动代码。

## 收尾自查

1. README 里还有 `vNN`、「旧稿」、版本对比、内部实现细节吗？有就搬进 `CHANGELOG.md`。
2. `CHANGELOG.md` 新条目在顶部吗？写清「改了什么 + 为什么 + 验证」了吗？
3. `.gitignore` 仍排除 `CHANGELOG.md` 吗？有没有误 `git add -f`？
4. 中英两版 README 同步了吗？顶部语言入口还在吗？
5. 公开 README 里有没有链接本机文件（`CHANGELOG.md`、`docs/`、`.agents/skills/`）？
