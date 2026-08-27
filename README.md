# CK3 人物传记生成器（《CK3 家传》）

读取《十字军之王3》（CK3）年度自动存档，为**玩家控制的角色**累积一生记忆，
并在**角色死后自动生成一篇杂志式五篇纪传体传记**（DeepSeek LLM 撰写），
按**宗族分文件夹**存放，附带 **index.html 阅读页**（离线双击即可阅读）。

```
CK3 自动存档 (.ck3)  —(watch/continue 只处理启动后写入的新存档)
  → rakaly json 熔化 → output/<宗族>/data/melt_<日期>.json
  → 记忆提取 → output/<宗族>/data/player_<玩家id>.json（每玩家一份，跨年去重）
  → 死亡检测（前代玩家 dead_data 出现即触发，身份校验防误判）
  → LLM 生成 → output/<宗族>/<姓名>_<终传|传记>_<日期>.md
  → htmlview → output/<宗族>/index.html
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
| 2 | 《列传·<好友>》 | 好友传记（无结友记忆时取最紧密同僚） |
| 3 | 《列传·<仇人>》 | 仇人传记（结仇记忆的对手） |
| 4 | 《家室列传》 | 妻室子女的门庭画卷（含妻族门第：妻之父兄等显贵亲眷） |
| 5 | 《朝局风云录》 | 朝局官制沉浮（皇帝/最高领主更替、登位/失土/囚狱，完全数据驱动） |

**干净事实铁律**：模型只收到 facts.py 渲染的中文自然语言事实——
所有角色显示**姓+名**（冯·大马士革巴沙尔、赵阿足、达丽娅…），头衔/文化/信仰/
特质/记忆类型/日期全部中文，**任何内部 id、键、英文枚举一律不进入提示词**。

## v4 能力（本地化 / 无地冒险者 / 亲属 / 特质履历）

- **本地化解析**（localization.py）：解析游戏本体 + 启用 Mod（launcher-v2.sqlite
  活动 playset）的 `localization/simp_chinese|english` YML → `data/localization.json`。
  名字（Daria→达丽娅）、头衔（k_lingxi→岭西）、文化（ashkenazi→阿什肯纳兹族）、
  信仰（ashari→艾什尔里派）、特质、政体、死因、法律全部先查本地化表，中文表兜底。
- **动态层级词**：头衔层级词按政体取（celestial：县=州府、公国=镇、王国=路、
  帝国=大路；administrative：督军/大督军；回退 王国/帝国/公国/县/堡），
  Mod 改了本地化跟着变。如 岭西（路）、关内（路）、鄜州（州府）。
- **无地冒险者**：营地显示营名（复兴党流亡委员会）、现驻郡（经省份→伯爵领映射，
  `data/province_map.json`）、县主、上位链与最高领主、营规、营力。
- **亲属/妻族**：每快照构建全档反向亲属索引（存档子女 family_data 常为空，
  父女关系只在父侧 child 列表），目标集含亲属的亲属；档案输出父/母/兄弟姐妹
  及历任高位头衔（妻父宋帝、妻兄今上均可写出）。
- **特质履历**：每年快照 diff 特质 → trait_history，渲染
  「该特质自某年某月某日起获得 / 至晚自某日起已具 / 自某日后消失」。
- **朝局数据**：realm_history 逐年记录帝国/王国级头衔持有者 →
  《朝局风云录》写皇帝更替（宋：赵曙→赵顼）与群臣浮沉。

## v5 能力（文化名序 / 死角色记忆回溯 / 新文章 / 双文风）

- **文化感知姓名顺序**：按文化 `name_order_convention` 调转姓/名——东方姓在前（赵阿足）、
  西方名·姓（巴沙尔·冯·大马士革）；文化未知（死后清空）回退原拼接。
- **死角色记忆回溯**：角色死亡时游戏清空其记忆 → 从**死前最近一份自动存档**恢复其记忆
  （如 1070.2.22 死的景先，从 1070.1.1 档恢复「与31885结怨、让出领地」），
  列传不再只靠主角单方记忆空写。
- **刺客列传·刀下诸魂**：主角一生杀 >5 人时追加第六篇列传，为每名死者立小传
  （击杀统计 = dead_data.kills ∪ successful_murder 记忆 victim ∪ death.killer==主角）。
- **游侠列传·行纪**：无地冒险者自动追加，依逐年所在地历史写漂泊路线。
- **妻族传·帝胄姻亲**：妻妾含「公主头衔 / 中华皇帝之女·姐妹」时追加（父/兄弟任 h_china 系皇帝）。
- **群英录·朝堂要员**：玩家为行政制角色时追加同朝要员群像。
- **终传附录**：死亡终传末尾附 世系表 + 大事年表（程序直出，不经 LLM）。
- **真正父亲**：`family_data.real_father` + 私生子/血统争议秘密推导，
  与法理父不同时输出「实父：X」。
- **自定义角色家世**：`ruler_designer_characters` 检测，父母描写用「先世无考」通用文本覆盖，
  不再编造「先祖辗转东徙」式家世。
- **双文风**：按玩家所在地**法理顶层帝国**判定——东方（中华/日本/高丽/越南等）用
  中国式纪传体（太史公曰），否则用西式传记（普鲁塔克《名人传》体例，评曰·史家按）。

## 环境准备

1. **Python 依赖**：`python -m pip install -r requirements.txt`（requests）。
2. **Rakaly**：把 `rakaly.exe` 放到 `tools\`（或改 `config.json` 的 `rakaly_path`）。
3. **配置文件**：复制 `config.example.json` 为 `config.json`，填入
   `deepseek_api_key`、`ck3_user_dir`（CK3 用户目录，含 save games）、
   `save_dir`、`ck3_game_dir`（游戏根目录，含 game/localization；留空自动发现）、
   各目录路径。
4. **存档**：游戏开启自动存档（建议每年），存档放 CK3 的 save games 目录。

## 用法

```bat
python build_names.py              :: 重建全档人名表 data/names.json（含姓氏，本地化）
python localization.py build       :: 重建本地化表 data/localization.json（首次自动）
python localization.py province    :: 重建省份映射 data/province_map.json（首次自动）
python pipeline.py watch [秒]      :: 新档监控：新战役新建文件夹（重名 → 哈布斯堡2）
python pipeline.py continue [秒]   :: 旧档续传：自动沿用最新文件夹，补录当前战役后监控
python pipeline.py scan            :: 单次：只补录当前战役（同战役）的新档
python pipeline.py status          :: 打印各玩家缓存状态（家族/来源档/记忆数/生死）
python pipeline.py bio [玩家id]    :: 手动生成传记（在世传记或终传）
python pipeline.py demo-death      :: 模拟主角死亡，演示「死后自动生成」链路
python pipeline.py rebuild-cache   :: 从各战役文件夹熔件重建缓存（迁移/修复）
python pipeline.py migrate         :: v4 迁移：旧 cache/ 移入 output/<家族>/data/ + 重建
python htmlview.py rebuild         :: 重建所有宗族文件夹的 index.html
```

**素材库纪律（只记录新扫描到的存档）**：

- `watch` / `continue` 启动时记录基准时间（最新存档的 mtime），**只处理启动后
  写入的新存档**；目录里已有的老存档（旧战役/历史档）一律不读、不记录。
- `scan` 只补录**当前战役**（playthrough_id 一致或玩家一致）中日期新于缓存的新档。
- 每玩家一份缓存 `output/<宗族>/data/player_<id>.json`（v4 起不再用顶层 `cache/`，
  由 `migrate` 迁移）；主角死亡、继承人继位（同战役新玩家）后自动为新主角建档。
- 死亡检测：新存档中检测到前代玩家（同战役）的 dead_data 即触发；**带身份校验**
  （名字一致 + 死亡日期晚于最后存活档）。每次死亡**只生成一篇终传**。
- **宗族文件夹**：`output/<宗族名>\`（如 `冯·大马士革`、`边氏`）；watch 新战役
  重名自动加数字（哈布斯堡 → 哈布斯堡2），continue 自动沿用该宗族最新文件夹；
  同一战役（playthrough_id 相同，含父死子继）共享文件夹。
  熔化存档（melt）与玩家缓存同在 `output/<宗族>/data/` 内；**游戏内新建家族
  （支系）不改变宗族，文件夹沿用宗族名、不新开文件夹**（v6）。
- 缓存文件夹绑定记录在 `cache.output_folder`，迁移/重建后依然有效。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `pipeline.py` | 主流水线：watch/continue/scan/status/bio/demo-death/rebuild-cache/migrate |
| `cache_lib.py` | 缓存库 v4：每玩家缓存、姓名合并、本地化名字、反向亲属索引、特质履历、朝局历史 |
| `localization.py` | 本地化解析（游戏+启用 Mod YML）、省份→伯爵领映射、政体层级词 |
| `facts.py` | 干净事实渲染层（模型只收中文事实，无裸键值） |
| `biography.py` | 杂志式五篇纪传体传记生成器（并发调 LLM，提示词全正向表述） |
| `llm.py` | 自包含 DeepSeek 调用管线（日志/提示词日志/截断重试） |
| `htmlview.py` | 宗族阅读页生成器（自包含 index.html，离线可读） |
| `build_names.py` | 全档角色名映射表（含姓氏，本地化，供姓名合并兜底） |
| `data/` | 全局表：names.json + localization.json + province_map.json（各战役共用） |
| `output/<宗族>/data/` | 每玩家记忆缓存 + 熔化存档 melt_*.json（v6 起，与缓存同目录） |
| `output/` | 传记输出（按宗族分文件夹） |
| `experiments/` | expck3 的旧实验脚本（历史参考，不入流水线） |

## 已知限制

- 角色死亡时游戏清空其记忆列表 → 必须靠**历年存档缓存**恢复（watch 常驻是硬性要求）。
- 战争只存活跃状态，历史战役靠战役类记忆。
- 出生地不在存档中，未写入传记。
- 特质履历日期为快照粒度（年度存档），首快照已具的特质写「至晚自X起已具」。
- 个别未收录进本地化的名字（Mod 新增）按码点解码或原样显示。
