# CK3 家传 · 纪传体传记生成器

[简体中文](README.md) | [English](README.en.md)

读取《十字军之王3》（CK3）的**年度自动存档**，为你在游戏里扮演的角色积累一生记忆；
角色故去之后，自动用 DeepSeek 写出一篇**杂志式五篇纪传体传记**，按宗族分文件夹存放，
并生成一个**离线阅读页**（双击即可在浏览器里翻）。

```
CK3 年度自动存档 (.ck3)
  → rakaly 熔化为 JSON          output/<宗族>/data/melt_<日期>.json
  → 提取记忆、头衔、亲属、事件   output/<宗族>/data/player_<玩家id>.json（每玩家一份，跨年去重）
  → 检测角色死亡（带身份校验，防误判）
  → DeepSeek 撰写               output/<宗族>/<姓名>_终传_<日期>.md
  → 生成阅读页                  output/<宗族>/index.html
```

程序**只读存档、只写自己的输出目录**，不会改动游戏文件或存档。

---

## 一、准备

| 需要什么 | 说明 |
| --- | --- |
| **Windows** | 脚本与批处理入口按 Windows 编写（路径用反斜杠，`.bat` 为 GBK 编码）。 |
| **Python 3.9+** | 用官方安装包安装，勾选「Add Python to PATH」。 |
| **CK3 游戏本体** | 需要能读到游戏的 `game/localization` 与 `game/common`，用于生成中文名、头衔、文化、信仰等对照表。 |
| **rakaly.exe** | 把 `.ck3` 存档熔化成 JSON 的第三方工具，**不随本项目分发**，需自行下载。 |
| **DeepSeek API Key** | 到 <https://platform.deepseek.com> 申请，生成传记时按量计费。 |

安装 Python 依赖：

```bat
pip install -r requirements.txt
```

获取 rakaly.exe（二选一）：

1. 到 rakaly 的发布页下载 Windows 版 `rakaly.exe`，放进本项目的 `tools\` 目录；
2. 或把它放在任意位置，然后在 `config.json` 里用 `rakaly_path` 指定完整路径。

---

## 二、配置

复制 `config.example.json` 为 **`config.json`**，填写下面几项即可。`config.json` 含 API Key，
已被 `.gitignore` 排除，不会被提交。

```json
{
  "deepseek_api_key": "sk-你的密钥",
  "deepseek_model": "deepseek-chat",
  "ck3_game_dir": "",
  "rakaly_path": "tools/rakaly.exe"
}
```

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `deepseek_api_key` | 空 | **必填**，DeepSeek 密钥。 |
| `deepseek_model` | `deepseek-chat` | 使用的模型名。 |
| `deepseek_base_url` | 官方 chat/completions | 换用兼容接口时才改。 |
| `ck3_user_dir` | 自动取当前用户的 `Documents\Paradox Interactive\Crusader Kings III` | 存档所在目录。 |
| `save_dir` | `ck3_user_dir\save games` | 具体存档目录。 |
| `ck3_game_dir` | 自动发现 | 游戏根目录（含 `game\`）；自动发现失败时手动填写。 |
| `rakaly_path` | `tools\rakaly.exe` | rakaly 可执行文件路径。 |
| `output_dir` | 项目下 `output` | 传记与缓存输出位置。 |
| `log_dir` | 项目下 `logs` | 运行日志与提示词实录。 |
| `poll_interval_seconds` | `3600` | watch 模式的轮询间隔（秒）。 |
| `max_tokens` | `12800` | 单次请求输出上限。 |
| `temperature` | `1.1` | 生成温度。 |
| `llm_max_concurrency` | `6` | 并发请求上限；上游报「资源不足」时调小。 |
| `prompt_log_enabled` | `true` | 是否把每次请求原文写入 `logs/prompts.log`（排错用，超过 5MB 自动轮转）。 |
| `auto_bio_on_death` | `true` | 检测到角色死亡时自动生成终传。 |
| `carnal_opinions` | `false` | 是否把 Carnalitas 的好感事件并入事实面；默认关闭以缩短提示词。 |
| `log_console_detail` | `false` | 置 `true` 时控制台打印逐份归档等高清明细。 |

**第一次运行需要先建表（手动，只此一次）。** 双击项目根目录的 `重建对照表.bat`：
程序会扫描游戏与启用的 Mod，生成全部中文对照表（`data\*.json`，约 30 MB），
本机实测约 11 秒（视磁盘与 Mod 数量而定）。

**平时启动不再自动建表。** 只有这两种情况需要重新跑一次 `重建对照表.bat`：

- 游戏升级（如 1.19 → 1.20）；
- 在启动器里勾选或取消 Mod。

想看三张核心表当前是否与游戏一致，用 `python pipeline.py status`（只读，不重建）。
表过期时程序会沿用现有表并打印一行提示。

---

## 三、使用

### 开始记录

游戏里把自动存档设为**年度**（`年` 或更频繁），然后在本项目目录下双击或运行：

```bat
启动监控.bat
```

它等价于 `python pipeline.py watch`：启动时记录「当前最新存档」为基准，
**只处理此后新写入的存档**——目录里的旧档与别的战役一律不读，因此不会把旧档混进来。
每次运行都会新建一个带编号的输出文件夹（如 `output\哈布斯堡2\`），
这样同一宗族的多次游玩互不干扰。

已经玩了一半、想把历史存档也补录进来，用**续传**：

```bat
启动续传.bat
```

它沿用最新的文件夹，补录当前战役中比缓存更新的存档，然后继续监控。

### 命令行

```bat
python pipeline.py watch [秒]      :: 新档监控：只处理启动之后写入的新存档
python pipeline.py continue [秒]   :: 旧档续传：沿用最新文件夹，补录当前战役新档后继续监控
python pipeline.py scan            :: 单次补录：只补当前战役的新档
python pipeline.py status          :: 查看各玩家缓存的记录进度
python pipeline.py bio [玩家id]    :: 手动生成传记（在世传或终传）
python pipeline.py bio <id> --decade 3
                                   :: 手动生成第 3 个十年传记
python pipeline.py rebuild-cache   :: 由各战役文件夹里的熔件重建缓存（修复/迁移）
python pipeline.py build-tables    :: 手动重建全部游戏/Mod 对照表（= 重建对照表.bat）
python pipeline.py build-tables --only=loc,traits
                                   :: 只重建指定表（键名见 data\<键>.json）
python pipeline.py index-melts     :: 预建熔件的记忆索引（加快日后回溯）
python pipeline.py compact [--gz]  :: 压缩归档冷熔件（默认 xz，体积最小）
python pipeline.py migrate         :: 迁移旧版本目录结构
python pipeline.py epilogue [家族]  :: 封档总评：上下键选战役文件夹，撰写全族总评
python pipeline.py epilogue 洪氏2 --force
                                   :: 指定文件夹（--force 覆盖已有总评）
```

### 生成节奏

- 角色每满 **10 年**（以开始记录的年份为刻度）自动生成一篇「第 N 个十年传记」。
- 角色**死亡**时自动生成一篇终传，末尾附程序直出的**世系**（谱例 + 世系图 + 逐代世系）与**大事年表**。
- 两者都在后台线程生成，生成期间监控照常运行，不会漏掉新存档。

### 阅读

打开 `output\<宗族>\index.html`：右上角下拉切换角色，左上列出该角色的全部传记
（第 N 个十年 / 终传·卒于某年）。所有文件都在本地，无需联网。

右上角的**「家谱」**按钮切到全族家谱：**宝塔式**世系图——世代为一行、始祖在上，自上而下
如塔；父子以黑线相承，相邻两代传主之间的传承路径与传主珠粒均为红色。工具栏的
**「分家 N/M」菜单**逐房勾选：每房一行带人数与色块（★ 为传主所在房，「独」只看此房），
另有「全选／只留传主房／清空」与**「含配偶」**开关；勾选按家族记在浏览器里，下次打开照旧。
默认只勾传主房 + 传主线，其先祖自动保留，使单独勾一房时仍有线上承始祖。点任一珠粒可
折叠／展开其子女分支；「全族」／「传主与配偶」／「只留传主」／「放大缩小」把图收窄；
字号可用「A-／A+」微调。每篇终传的附录照旧印**世系**文本。

封档之后双击 `封档总评.bat`（= `python pipeline.py epilogue`）：上下键选战役文件夹，程序取
最新存档，写出一篇**封档总评**——第一部分综述历代传主的《本纪》首篇，第二部分交代当世同宗的
诸位统治者（谁、据何地、与今生传主是何亲属），附程序直出的同宗统治者名册。写出后阅读页右上角
会多出**「封档总评」**按钮。

---

## 四、目录结构

```
├── 启动监控.bat / 启动续传.bat   一键入口
├── 重建对照表.bat                手动建表（游戏升级/换 Mod 后跑一次）
├── 封档总评.bat                  上下键选战役文件夹，撰写全族封档总评
├── pipeline.py                   命令行主入口
├── config.example.json           配置模板（复制为 config.json 使用）
├── data/                         游戏侧对照表（可自动重建）
├── tools/                        辅助工具（rakaly.exe 放这里）
├── output/<宗族>/                每场战役的产物
│   ├── data/                     熔件、记忆缓存、快照、家谱数据
│   ├── <姓名>_终传_<日期>.md      成稿
│   └── index.html                阅读页（含家谱页）
└── logs/                         运行日志
```

`output/`、`logs/`、`config.json`、`cache/` 都不会进版本库。

---

## 五、传记长什么样

### 五篇文章

| # | 篇名 | 内容 |
| --- | --- | --- |
| 1 | 《本纪·<主角>》 | 人物生平：家世、受任、大事、现状 |
| 2 | 《列传·<好友>》 | 挚友传记（无结友记忆时取关系最紧密的同僚） |
| 3 | 《列传·<仇人>》 | 仇敌传记（由结仇记忆确定人选） |
| 4 | 《家室列传》 | 妻室子女的门庭画卷，含妻族门第 |
| 5 | 《朝局风云录》 | 君主更替与群臣浮沉，完全由存档数据驱动 |

满足条件时还会追加：《刺客列传》（亲手了结多人）、《游侠列传》（无地冒险者）、
《妻族传·帝胄姻亲》、《群英录·朝堂要员》、《阴私录·隐事秘辛》等。

**礼仪系统**：满足条件时会追加一篇《礼仪志·礼仪与教义》，写所奉礼仪的名目与源流、
礼仪领袖、核心教义、宗教热情、灵性满足、个人教义，以及个人教义与礼仪的沿革、修会、
禁忌信条；有枢机团与教宗选举素材时再出「纪事·枢机团与教宗选举」。**有实据才出**。

### 两种文风

按角色所在地的法理顶层帝国自动选择笔法，两套都要求**全文使用现代汉语书面语**：

- **东方**（中华、日本、高丽、越南等）→ 以人物为中心、按时间顺序讲述一生的中国式传记；
- **其他** → 穿插轶事与性格细节、边叙述边评议的西式传记。

总纲结尾写一段总评收束全篇；其余板块保持客观叙述。

### 干净事实

模型只收到程序渲染好的**中文自然语言事实**：角色写「姓+名」，
头衔、文化、信仰、特质、记忆类型、日期一律中文。
**任何内部 id、键名、英文枚举都不会进入提示词**，也不会出现在成稿里。

---

## 六、Mod 与本地化

- 程序会读取你**当前启用**的 Mod（从启动器配置中获知），
  把它们的本地化文本一并并入对照表，因此 Mod 新增的头衔、特质、事件等
  会自动显示为对应的中文，而不是英文键名。
- **启用新 Mod 或 Mod 更新后无需手动操作**：来源指纹变化会在**下次启动时**自动触发
  对照表重建（`watch` / `continue` / `scan` 都先自检一次，并在控制台打印本地化来源
  与三张表的自检结论）。想只看状态不重建，用 `python pipeline.py status`。
- 想检查某个键为何没显示成预期中文：

  ```bat
  python localization.py check      :: 比对当前来源指纹与表内指纹
  python localization.py mods       :: 列出已识别的 Mod 及其本地化覆盖
  ```

- 想要手动重建某张表（例如排查时）：

  ```bat
  python localization.py build      :: 本地化总表
  python localization.py traits     :: 特质名与特质子轨道
  python localization.py positions  :: 宫廷/营地职位
  python localization.py council    :: 御前会议席位
  python localization.py dynasties  :: 宗族与家族名
  python localization.py province   :: 省份→伯爵领映射
  ```

- `All Under Heaven`（天命 / TGP）是**游戏本体自带的 DLC 内容**，不是 Mod，
  相关脚本与本地化都在游戏的 `game\` 目录下。

---

## 七、常见问题

**Q：启动后一直没反应？**
A：`watch` 只处理**启动之后**保存的存档，请先在游戏里存一次档（或等下一次年度自动存档）。

**Q：提示 rakaly 不存在？**
A：把 `rakaly.exe` 放进 `tools\`，或在 `config.json` 里用 `rakaly_path` 指定完整路径。

**Q：第一次运行很慢？**
A：先双击一次 `重建对照表.bat` 建表（本机约 11 秒，视磁盘与 Mod 数量而定）；
之后启动只读表、不再重建。

**Q：游戏升级或换 Mod 之后名字不对了？**
A：双击 `重建对照表.bat` 重跑一次；只想确认状态就用 `python pipeline.py status`
（只读自检，会打印三张核心表与游戏来源指纹是否一致）。

**Q：生成中断或报「上游资源不足」？**
A：调小 `config.json` 里的 `llm_max_concurrency`（例如 3），再重跑同一命令。

**Q：想看清模型到底收到了什么？**
A：`logs\prompts.log` 逐次记录请求原文（由 `prompt_log_enabled` 控制）。

**Q：传记写到一半发现事实不对？**
A：先看 `output\<宗族>\data\` 里该玩家的缓存与快照，再决定是重建缓存
（`python pipeline.py rebuild-cache`）还是单独重生成某篇（`python pipeline.py bio <玩家id>`）。

---

## 八、许可

本项目以 **GPL-3.0** 发布，见 [LICENSE](LICENSE)。

《十字军之王3》及相关内容的著作权归 Paradox Interactive 所有；本工具仅为个人存档的
二次创作辅助，不含任何游戏原始资源。rakaly 为第三方工具，请遵循其自身许可。
