# CK3 人物传记生成器（《CK3 家传》）

读取《十字军之王3》（CK3）年度自动存档，为**玩家控制的角色**累积一生记忆，
并在**角色死后自动生成一篇杂志式五篇纪传体传记**（DeepSeek LLM 撰写），
按**家族分文件夹**存放，附带 **index.html 阅读页**（离线双击即可阅读）。

```
CK3 自动存档 (.ck3)  —(watch/continue 只处理启动后写入的新存档)
  → rakaly json 熔化 → data/melt_<日期>.json
  → 记忆提取 → cache/player_<玩家id>.json（每玩家一份，跨年去重）
  → 死亡检测（前代玩家 dead_data 出现即触发，身份校验防误判）
  → LLM 生成 → output/<家族>/<姓名>_<终传|传记>_<日期>.md
  → htmlview → output/<家族>/index.html
```

## 传记形式（仿报纸 Mod 的杂志格式）

生成流程与 `D:\Journal\magazine.py` 同构：

```
① 总纲（1次调用）：一生总览 + 五篇预告
② 五篇文章首段（5次并发）——纪传体开篇
③ 每篇中段+尾段（10次并发）——纪事 + 「太史公曰」评点
④ 组装为 Markdown
```

五篇文章（纪传体，仿《史记》）：

| # | 篇名 | 内容 |
| --- | --- | --- |
| 1 | 《本纪·<主角>》 | 人物生平（家世/受任/大事/现状） |
| 2 | 《列传·<好友>》 | 好友传记（无结友记忆时取最紧密同僚，如王铎） |
| 3 | 《列传·<仇人>》 | 仇人传记（结仇记忆的对手，如孙浣） |
| 4 | 《家室列传》 | 妻室子女的门庭画卷 |
| 5 | 《山南风云录》 | 朝局官制沉浮（登位/失土/囚狱） |

**干净事实铁律**：模型只收到 facts.py 渲染的中文自然语言事实——
所有角色显示**姓+名**（边诚、孙浣、王铎…），头衔/文化/信仰/特质/记忆类型/日期
全部中文，**任何内部 id、键、英文枚举一律不进入提示词**。

## 环境准备

1. **Python 依赖**：`python -m pip install -r requirements.txt`（requests）。
2. **Rakaly**：把 `rakaly.exe` 放到 `tools\`（或改 `config.json` 的 `rakaly_path`）。
3. **配置文件**：复制 `config.example.json` 为 `config.json`，填入
   `deepseek_api_key`、`ck3_user_dir`（CK3 用户目录，含 save games）、
   `save_dir`、各目录路径。
4. **存档**：游戏开启自动存档（建议每年），存档放 CK3 的 save games 目录。

## 用法

```bat
python build_names.py              :: 重建全档人名表 data/names.json（含姓氏）
python pipeline.py watch [秒]      :: 新档监控：只处理本程序启动后保存的新存档
python pipeline.py continue [秒]   :: 旧档续传：补录当前战役新档后进入监控
python pipeline.py scan            :: 单次：只补录当前战役（同战役）的新档
python pipeline.py status          :: 打印各玩家缓存状态（家族/来源档/记忆数/生死）
python pipeline.py bio [玩家id]    :: 手动生成传记（在世传记或终传）
python pipeline.py demo-death      :: 模拟主角死亡，演示「死后自动生成」链路
python pipeline.py rebuild-cache   :: 从 data/melt_*.json 重建缓存（迁移/修复）
python htmlview.py rebuild         :: 重建所有家族文件夹的 index.html
```

**素材库纪律（只记录新扫描到的存档）**：

- `watch` / `continue` 启动时记录基准时间（最新存档的 mtime），**只处理启动后
  写入的新存档**；目录里已有的老存档（旧战役/历史档）一律不读、不记录——
  与报纸 Mod 的 watch/continue 语义一致。
- `scan` 只补录**当前战役**（playthrough_id 一致或玩家一致）中日期新于缓存的新档，
  其它战役的存档按信封角色名直接跳过，不熔化、不记录。
- 每玩家一份缓存 `cache/player_<id>.json`：主角死亡、继承人继位（同战役新玩家）
  后自动为新主角建档，长局可累积多位角色的传记。
- 死亡检测：新存档中检测到前代玩家（同战役）的 dead_data 即触发；**带身份校验**
  （名字一致 + 死亡日期晚于最后存活档），杜绝跨战役角色 id 撞号误判。
  每次死亡**只生成一篇终传**（`bio_generated` 标记）。
- **家族文件夹**：`output\<家族名>\`（如 `边氏`），家族内每篇传记一个 md，
  `index.html` 一键切换阅读。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `pipeline.py` | 主流水线：watch（新档监控）/ continue（续传）/ scan（补录）/ status / bio / demo-death / rebuild-cache |
| `cache_lib.py` | 缓存库 v3：每玩家缓存、姓名合并（姓+名）、码点解码、宗族解析 |
| `facts.py` | 干净事实渲染层（模型只收中文事实，无裸键值） |
| `biography.py` | 杂志式五篇纪传体传记生成器（并发调 LLM） |
| `llm.py` | 自包含 DeepSeek 调用管线（日志/提示词日志/截断重试） |
| `htmlview.py` | 家族阅读页生成器（自包含 index.html，离线可读） |
| `build_names.py` | 全档角色名映射表（含姓氏，供姓名合并兜底） |
| `data/` | melt JSON + names.json（melt 可由 scan 重新熔化） |
| `cache/` | 每玩家记忆缓存（可由 scan / rebuild-cache 重建） |
| `output/` | 传记输出（按家族分文件夹） |
| `experiments/` | expck3 的旧实验脚本（历史参考，不入流水线） |

## 已知限制

- 角色死亡时游戏清空其记忆列表 → 必须靠**历年存档缓存**恢复（watch 常驻是硬性要求）。
- 战争只存活跃状态，历史战役靠战役类记忆。
- 出生地不在存档中，未写入传记。
- 部分角色名（如未本地化的 `Song`）按存档原样显示。
