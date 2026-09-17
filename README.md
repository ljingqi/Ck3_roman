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

生成流程与 `<另一项目>\magazine.py` 同构：

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

## v7 能力（崩溃容错 / 文化信仰直读 / 宫廷官职 / 家族家训）

- **存档空值容错**：rakaly 会把 Clausewitz 的 `= none` 渲染成字符串 `'none'`（实测单档 6938 处，
  含 living/dead/头衔/宫廷职位等段落），旧代码的 `x or {}` 防护对真值字符串无效导致
  `'str' object has no attribute 'get'` 崩溃。v7 起 `load_melt` 递归把 `'none'` 清洗为 `None`，
  关键循环再加类型防护——任何存档不再因此崩溃。
- **死亡→终传链路加固**：watch 每轮都检查待生成终传（不再依赖当轮有新档并入）；
  每份存档独立容错（单档失败记日志、下轮自动重试，不再中断整轮并跳过终传触发点）；
  终传生成移到**后台线程**，生成数分钟期间 watch 轮询照常检测新存档，不再单线程卡死。
- **文化/信仰直读**：角色文化/信仰每快照有值即更新（覆盖文化改信）；死后游戏清空该字段
  （实测死档约半数被清，含前代玩家），缓存保留存活期直接读到的值，渲染层缓存优先——
  死者不再一律「族属不详」，与游戏内所见一致。
- **宫廷/营地官职**：读取 `court_positions.database`（玩家宫廷职位 + 营地军官，实测 41 种
  职位类型本地化全覆盖），逐年记录 `cache.court_positions`，渲染最新任职与任免变化——
  语义是「主角营/廷内**僚属**任职」（雇主=玩家，任职者另有其人），渲染**主语=任职者**
  （「西比尔任军需官（自872年3月18日任）」「880年1月1日：营中厄瓦尔卸任搬运工头」；
  v23 起弃用「宫廷官职：职位：人名」式履历错觉，防被读成主角自身官职）。
- **家族家训**：读取 `dynasty_house[<id>].motto`（字符串或模板 dict，`$1$/$2$` 变量填充 +
  本地化），渲染进《本纪》《家室列传》《朝局风云录》档案。

## v8 能力（十年传记 / 死亡记忆直读 / 击杀统计 / 阅读页重构 / 妾 / 头衔合并）

- **十年传记模式**：角色每满 10 年数据（以缓存起始年为刻度）自动生成一篇
  「第N个十年传记」（后台线程），素材读取**全部累计数据**（统治 40 年即读取 40 年数据）；
  死亡后生成终传的逻辑不变；已生成十年序号记入 `cache.bio_decades`。
- **死亡记忆直读**：死者 `alive_data` 被移除，但**曾为玩家（was_playable）的角色**其记忆
  保留在 `dead_data.memories`（实测崔佛死档 6 条全在）——游戏角色窗可见记忆即来源于此。
  缓存读取改为双源（alive_data → dead_data 回退）；普通死者的死前档回溯仍作兜底。
- **击杀统计五源合一**：`alive_data.kills` ∪ `dead_data.kills`（跨年累积入缓存）∪
  `player_death.kills`（死亡检测时入库）∪ `successful_murder` 记忆 ∪ 熔件受害者反查，
  刺客列传（杀 >5 人）判定随之修正。
- **妾**：读取 `family_data.concubine`/`former_concubines` + 反向 `concubinist` 扫描
  （正向字段常只列 1 人，反向才完整），渲染「妾：」行与世系。
- **提示词换行修复**：`clean_number_spaces` 只删空格类字符（半角/全角空格、制表符），
  不再把汉字↔数字间的换行当空格吃掉（此前「营力209妻室」「此为终传6篇」漏换行即由此）。
- **阅读页重构**：右上角色下拉切换，左上显示该角色的十年传记/终传列表
  （第N个十年/终传·死于X），按 md 头部注释 `人物|出生|篇目|十年` 分组。
- **头衔合并与层级词**：`布列塔尼（公国）` → `布列塔尼公国`（名字已含层级词不追加，
  如 神圣罗马帝国）；欧洲伯爵领不再显示「县」。
- **DLC 领地层级词（v8.3）**：天朝制层级词按 DLC「All Under Heaven」文化头衔取
  县/州府/镇/路/行台/皇朝（唐·宋剧本同一套），不再用俸禄词（大路）；欧洲仍用
  通用词（帝国/王国/公国/伯爵领/堡）。
- **伊斯兰动态国名（v8.2）**：最高领主为伊斯兰统治者时按游戏同规则显示
  「家族+层级词」——王国级 `埃及王国`→`图伦苏丹国`，帝国级兼任哈里发→`阿拔斯哈里发国`、
  否则→`{家族}帝国`；动态国名不存于存档（k_egypt 静态名仍为「埃及」），由
  持有者信仰→伊斯兰 + 家族名 + religious_head 头衔（d_sunni）持有者判定复现。
  家族名解析补 house key 回退（house_abbasid → dynn_Abbasid → 阿拔斯）。
- **行政制「大督军」条件**：行政制帝国词仅在其上有霸权头衔（h_）时出现
  （拜占庭帝国无上位霸权 → 显示「拜占庭帝国」而非「大督军」）。
- **死因中文化**：总纲【卒年】不再泄漏英文死因 key（黑死病而非 death_bubonic_plague）。

## v14 能力（AUH 东亚人名正常化 / 宗族-家族分层）

- **东亚人名分层显示**：按游戏规则——东方名序（`dynasty_always_first`/`japanese`）的姓取
  **宗族（dynasty）名**（中国李金、日本藤原/源、韩国崔金，`$DYNASTY$$NAME$` 模板）；
  西方仍取**家族（house）名**（`$NAME$·$HOUSE$`）。此前项目把家族名当姓用，日式分家
  （北家/一条）与中韩本贯式家族（交州金/庆州崔）被误作姓（北家道长/庆州崔文王），
  现已正常化为 藤原道长/崔文王，家族名降为风味补充。
- **宗族/家族定义表**：`data/dynasties.json` 解析 游戏+启用 Mod 的
  `common/dynasties/*.txt`（宗族 key→dynn 名，如 japanese_fujiwara→藤原）与
  `common/dynasty_houses/*.txt`（家族 key→dynn 名，如 house_fujiwara_kajuji→勧修寺）；
  `python localization.py dynasties` 重建；存档只存 key，显示名靠此表回查。
- **旧缓存自愈**：`extract_snapshot` 对缺失 `dynasty_name` 的旧缓存按家族 id 记忆化补解析；
  渲染期 `display_name` 另有惰性解析兜底（同 house 记忆化），旧战役不重建缓存也正确。
- **风味双字段**：档案给出 宗族（藤原氏）与 家族/分家（北家/庆州崔，与宗族不同时列出），
  自然语言渲染「家族：藤原北家」（v29b：直连不再用括注；非「氏」结尾时以逗号并列）；
  `build_names.py` 的 names.json 增 `dynasty_name`。
- **死者官职地名兜底**：title history 被存档剪除时（b_lantian 无 history），官职地名
  （蓝田县令）回退到死者 `dead_data.domain` 死时辖地解析，不再退化成「县令…史料不详」。
- **元注释清零**：渲染层不再向模型泄露内部 id/裸键——`_name_or` 亲缘兜底改走熔件全量
  角色（父玄景，而非「角色22707」）；家族恩怨/宝物流转/职司/短命皇朝等兜底一律改自然词
  （某家族/一件宝物/某职司）或略去；记忆句模板雅化（「完成教化」→「学业有成」、
  「完成成人学业」→「完成深造」）。
- 穆斯林动态国名（图伦苏丹国）同步改按宗族名（与游戏一致）。

## v17 能力（十年聚焦 / 干净事实加固 / 日式官职）

- **十年聚焦**：十年传记只讲本十年——`build_facts` 传 `decade`，时间线/概览统计/戏剧主题/
  本纪年表/刺客列传统一收 `(as_of−10年, as_of]` 窗口（`_decade_lower_bound`），终传保持全期；
  「本十年/一生」标签改用显式 `facts["decade"]` 判定（终传不再误标「本十年」）。
- **摘要按年聚合**：`_year_summary` 一年一行——谋杀/添丁合并人名（≤3 全列 + 等N人），
  其余事件去月日保留动词原句，出生年括注不写；十年摘要 89 行 → 约 10 行，
  好友/仇人列传相关年表改按传主名过滤，不再整份复述主角年表（仿 <另一项目> 按板块取料）。
- **干净事实加固**：`_clean_ck3_loc` 正则 `[A-Z]`→`[A-Z_]+`（`LANDED_TITLE` 不再漏键）、
  头衔链接块 `ONCLICK:TITLE,id TOOLTIP:LANDED_TITLE,id L; 名称` 整体剥离、`L;` 标记清除。
- **日式官职（AUH 日本）**：`japan_administrative_government` 分支查游戏本地化键——
  `e_japan`（日本帝国）之主=关白、王国=帅、郡县=国司、堡=郡司；
  天皇座（k_chrysanthemum_throne）持有人=天皇（此前错渲染成「日本皇帝/高御座国王」）。
- **动态国名按卒期（v25）**：死者官职地名取**卒日**国号（`_last_title_place` / `_anchor_date`），
  在世角色取 as_of。李漼卒于唐（874.8.15）→「唐皇帝」，不随 875.6.25 崔氏改国号而写作「秦皇帝」。
  此口径取代 v24 的「按游戏当前显示」（王言卒时国号「翟」→「翟王」，原「秦王」）。
- **戏剧性事件去出生年**：`_villain_chains` 四处出生年括注删除（亲缘标签已消歧）；
  消歧保留在 时间线谋杀行 与 刺客列传死者行（里瓦朗/里瓦尔场景）。
- **世系编号（II/III 二世标记）**：编号不存存档，按「首要头衔 title history 同名前任数 + 1」
  动态计算（`regnal_number` / `name_with_regnal` / `_last_high_title_before`），
  中文渲染（二世…九世带「世」，十起不带——路易十一）；应用于恩怨史/时间线/死亡句/
  刺客列传/人物档案，鲁斯兰父子 → 鲁斯兰·克里维奇 与 鲁斯兰二世·克里维奇。
  **编号紧跟名（史书惯例：路易十四/查理二世），不给姓冠编号**——鲁斯兰二世·克里维奇、
  洛泰尔二世·加洛林；**仅西方名序（名·家名）标编号，东方人名（姓+名）与单段名无编号**；
  **有绰号时编号让位于绰号**（见下，不再标「二世」）。
- **昵称**：读熔件 `nickname_text`（直接是中文昵称，v18 起按中文史传惯例渲染）——
  西方名序 绰号前置、去引号（秃头查理·加洛林 / 青年路易·加洛林 / 征服者威廉·诺曼底），
  有绰号即不标世系编号；东方名序维持 姓+名“绰号”（大和惟条“秃头”）。

## v18 能力（跨战役玩家 id 复用 / 昵称史传化）

- **跨战役玩家 id 复用防护**：CK3 的自定义角色 id 与开局年代绑定——**所有 867 开局
  的自定义角色恒为 38701**，新战役必然与旧战役缓存撞号。v18 起缓存选择整体改为
  **战役感知**（`all_caches` 键 = `(player_id, playthrough_id)`，`find_cache_path`
  支持按战役过滤，`active_cache`/`step_bio`/`_process_save` 全部按 playthrough 判定）：
  - 新战役首档按 playthrough 找不到旧缓存 → 从空缓存重建，文件夹按新档宗族名新建
    （修复 2026-08-31 事件：汤利缓存被按新档宗族表误解析成「沙逊」）；
  - 旧战役的记忆/头衔历史/死亡检测（`_cross_check_deaths` 身份校验）绝不进入新战役；
  - 后台终传/十年队列键含战役 `((pid, pt), kind, decade)`，回写落在该战役自己的缓存。
- **昵称史传化**（用户决策 2026-08-31）：有绰号的角色不再标「二世」——西方名序
  绰号前置、去引号（青年路易·加洛林、秃头查理·加洛林，中文史传惯例）；
  东方名序维持 姓+名“绰号”（大和惟条“秃头”）。
- **编号史传化**（用户决策 2026-08-31）：无绰号角色的世系编号紧跟名、家名在后
  （鲁斯兰二世·克里维奇），不再把编号缀在姓上；东方人名（姓+名）与单段名不标编号。

## v26 能力（性别 / 仇人权重 / 动态头衔 / 牧群 / 信仰履历 / 囚禁时长）

排查与决策见 `docs/排查_田所2六问题.md`，确定性验证 `python experiments/verify_tadokoro2.py`。

- **性别（女儿不再写成儿子）**：缓存 `char_record` 补 `female` 字段并在 `extract_snapshot`
  持久化（熔件只在女性身上存 `female`）；`Facts._is_female` 统一入口（缓存优先、熔件兜底）。
  出生记忆按孩子性别换模板（`child_born_female` 添女 / `first_born_female` 得长女 /
  `twins_born_female` 得孪生女 / `twins_born_mixed` 得龙凤胎）；档案与家室档案的子女
  按性别分列（「子A、B，女C、D」）；`_year_summary` 出生分「添子/添女」两组。
- **动态头衔（游戏内显示名）**：`_name_at_date` / `title` / `title_base_name` /
  `_title_name_at` 一律优先存档里游戏算好的 `title_name_data.specific_title_name`
  （游牧「可萨田所部」、宗族命名「马扎尔」），无该字段时才走 `title_history_names`
  更名史（h_china 唐→秦、k_guannei→秦 仍由更名史承担，v25 卒日国号口径不变）；
  带动态名时不再叠层级词。实测 melt_900 全档 800 个动态名与 `Facts.title()` 逐条一致。
- **游牧官职词**：`_office_word` 增游牧/牧民/部落分支，按游戏 flavorization 顺序取词
  ——`<tier>_nomad_{male|female}_<heritage>`（突厥：叶护/颉利发）→
  `<tier>_tribal_{male|female}`（count_tribal_male=酋长 / duke_tribal_male=大酋长）→
  `<tier>_herder_*`（牧主）。游牧政体不适用伊斯兰动态国名（`realm_name` 加政体门）。
  游牧毡帐 `x_c_nomad_*` 不再当作「无地冒险者营地」，也不挤掉领地头衔的历任阶段。
- **牧群**：`domiciles.database` 的 `herd`/`provisions` 由 `extract_snapshot` 提取进
  `landed`；档案政体句按金钱同口径写「牧群715.7」（只给当前值，取 as_of 熔件的毡帐）。
- **信仰履历（改信过程）**：缓存增 `faith_history` 逐档差分（游戏不给改信留记忆），
  档案增「信仰履历：法华宗（880–895年）；艾什尔里派（自896年起）」，时间线增
  「896年，X改信艾什尔里派。」（归「信仰皈依」模块）。
- **囚禁时长**：`Facts.imprison_duration`（受害者 `imprisoned` / `released_from_prison_memory`
  记忆，主角 `imprisoned_other` 兜底）——卒时已囚满一年者，处决写「囚禁4年7个月后被X斩首」，
  狱死写「…而死，囚禁5年1个月」；主角囚禁期间死亡者（凶手未必记为主角）也入刺客列传。
- **日期折叠**：`llm.fmt_cn_date` 把 1月1日渲染为「NNNN年」——游戏「出生日期不详」与
  年度快照日都是 1月1日，月/日无信息量（大事件年表同样只写年份）。
- **仇人权重**：`_select_primary_enemy` 先按「与本篇相关」筛（在世，或本十年内有作为），
  再按**事迹分**降序（`_ENEMY_DEED_TYPES`：登位/战争/谋杀/婚配/生育/结友/囚禁/科考…），
  同分在世优先、结怨最早；`_is_dead` 支持 as_of（卒于十年末之后者视为在世）。
  `_character_profiles` 修复 `prof.get("memories")` 取空导致的「传主行迹」恒空
  （此前对所有人都是「（无行迹记录）」）。田所2：890 年仇人 → 秦皇帝崔慎由（原为无事迹的
  菅原类子），900 年 → 尤拉特。

## v27 能力（亲属头衔 / 语言风味 / 上下文瘦身）

方案与实测见 `docs/方案_亲属头衔_语言风味_上下文瘦身.md`（2026-09-10 用户定稿）。

- **亲属称谓带头衔**：新增 `Facts.kin_label(cid, date)` 统一出口，亲属行/世系表/
  好友仇人档案的家属行/妻族传/刺客列传亲缘一处不改地全走它。优先级：
  宗教领袖 > 现头衔（`official_title`，含死者 `dead_data.flavor`）> 前头衔
  （**仅层级高于现头衔时**以「前X，」前置，用户定稿形态
  `前拜占庭皇帝，安卡拉伯爵君士坦丁十一`）> 王子/公主称号 > 统一显示名。
  同一头衔今昔两种叫法不算前头衔 —— 塔坦尼·布兰现职「可萨布兰部可敦」，
  不再写成「前可萨布兰部至高女王」。顺带修掉同一个人三处三种写法
  （亲属行丢绰号/世系编号）与**同名歧义**（尤拉特家妻「亚萨尔」与女
  「亚萨尔·布兰」）。
- **`prince_title` 职司缺陷**：朝廷职司（`e_minister_*`）被当成「国」前缀
  （`刘鸣鹤 → 兵部国皇女`）。新增 `_is_landed_title`，父头衔候选与「前头衔」
  一律要求 `h_/e_/k_/d_/c_/b_` 领地头衔，实测 199 个称号中「兵部国」0 例。
- **语言风味**：`Facts.mother_language`（文化→语言；文化 id 被清空时由文化模板
  反查；只通一语者即其母语）/ `language_sentence`（「母语日琉语，兼通乌古尔语。」）/
  `language_bridge_line`（「家中言语：毗伽伊尔盖通共同突厥语。」只列与主角无共通语者）。
  档案逐人渲染语言行；新增 `LANGUAGE_FLAVOR_RULE` / `TITLE_CONSISTENCY_RULE`
  两条**正向**规则进全部 system 提示词（静态文本，缓存友好），
  《列传·好友/仇人》《家室列传》中段增补语言取材要求。
  实测数据基础：124 种语言本地化 100% 覆盖，39 个进提示词角色中 35 个有语言；
  主角与 14 名关键人物中 3 人无共通语（含《列传》两名传主罗元、崔慎由）。
- **上下文瘦身 + 注意力兼顾**（同一拟真开篇长度、前后同法各测一次）：
  | 场景 | 请求 | 改前 | 改后 | 减量 |
  | --- | --- | --- | --- | --- |
  | 田所2 @900 十年传 | 12 | 67,130 | 49,257 字符 | **−26.6%** |
  | 田所2 @901 终传 | 14 | 106,008 | 81,715 字符 | **−22.9%** |
  | 田所 @879 终传 | 15 | 68,692 | 52,703 字符 | **−23.3%** |

  三项杠杆：**A** 删同消息内重复的【人物档案】（此前与共享前缀逐字节重复）；
  **B** 30 模块表 `MODULE_TABLE` 首次用于板块切片（`MODULE_SLICE`/`MODULE_EXCLUDE`
  + `slice_events`），同篇开篇与纪事素材**不相交**（此前 6 篇里 5 篇逐字节相同），
  家室档案/天下大势/官职任免/行纪按关系或时段二分，本纪/朝局纪事按用户决策
  排除「谋害人命」并由程序补一行「另有谋杀N人，详见《刺客列传》」（剧本无
  刺客列传时自动不排除）；
  **C** 移植 `<另一项目>` 的 `_lead_digest`（前缀 260 + 结尾 180），中段不再回贴开篇全文。
  尾部新增 `【本板块大事】` 锚点（4 条，含主角名/高戏剧模块优先）以对位
  Lost-in-the-Middle 的 U 型注意力。修 `_merge_same_day_events` 合并丢 `module`
  的缺陷（未标注模块事件 80 → 0 条，切片零丢失）。
- **缓存度量**：`llm.call_deepseek` 每次调用落日志
  `token: 输入N = 命中H + 未命中M | 输出O | 字符C (命中率P%)` —— DeepSeek 缓存命中
  单价是未命中的 1/50，**未命中 token 才是验收指标**（此前 usage 从未被读取）。

## v28 能力（跨战役名字防污染 / 世族庄园 / 头衔缘由 / 言语条件化）

方案与证据见 `docs/修复方案_陆氏十二问题.md`（2026-09-10 用户拍板：乡绅 / 全政体按
reason 出词 / 现代白话档位 / 隐藏文档元信息），确定性验证 `python experiments/verify_lushi.py`。

- **跨战役名字防污染**：`data/names.json` 是按角色 id 索引的**跨战役**表（id 只在同一存档内
  有意义）。`display_name` 取值链改为 缓存 → **熔件角色** → names.json，且表内
  `playthrough_id` 与当前熔件不一致即整表弃用（`build_names.py` 写入战役号）。
  实测陆氏档 16293 本名「郑良士」（汉人，宗族郑），此前被另一战役同名 id 顶成「藤原利仁」
  —— 全档 27662/50261 个角色名与自身不符。`_father_name_of` 同步改序。
- **世族庄园（乡绅）**：`x_` 头衔不再一律当「无地冒险者营地」。新增
  `Facts.title_kind`（`estate` 世族庄园 `_nf_` / `nomad` 毡帐 / `camp` 冒险者营地
  `_laamp_`+`x_mc_` / `landed`），`_primary_group` 不再让庄园挤掉领地阶段，
  `held_titles` 写「陆家族乡绅（世族庄园）」，档案增「世族庄园「陆家族」（乡绅）。」。
- **头衔得失按 reason 出词（全政体）**：`TITLE_GAIN_VERBS` / `TITLE_LOSS_VERBS`
  把 `appointment_succession`→受任、`stepped_down`→卸任/接任、`inheritance`→承袭、
  `conquest*`→攻取/失守、`revoked`→被褫夺… 未知 reason 回退旧词（登位/让出）。
  天朝制/行政制下戏剧主题显示名换为「受任迁转/卸任调转」，板块要求同步换词
  （陆氏：867 创建陆家族 → 869 受任阶州 → 872 卸任阶州 → 875 受任商州；
  `created` 于 v34b 由「受封」改为「创建/重建」，见下）。
- **牧群/口粮按 domicile 门控**：牧群只在毡帐（yurt）写、口粮只在无地营地（camp）写，
  0 值一律省略（天朝制世族此前写出「牧群0」）。
- **朝廷职司 = 官职词+人名**：`兵部尚书任清`（原「兵部：任清（兵部尚书）」重复）；
  `minister_revenue`/`minister_rites` 本地化键缺失，改走候选链
  （`councillor_steward/court_chaplain_celestial_government_imperial`），
  政事堂 → 宰相。`_minister_office` 是 `official_title` 共用出口，一并受益。
- **文化随父系**：`culture_template` 改为 自身 → 亲属链（父→同胞→宗族→母）→ 语言反查；
  同语言多文化时优先有父名规则的模板。子女不再因「共享 language_tai」被判成黎人。
- **人物族属/信仰补全**：谋害对象并入档案白名单（`successful_murder` ∪ `killer==主角`），
  时间线谋杀行带「（839年生，羌人，信正一派）」——存档里 `dead_unprunable` 一直保留这些
  字段（游戏随时可读），此前只进《刺客列传》（击杀 >5 才生成）。
- **元信息清零**：档案不再出现「出身自定/自定义出身/史无可考」（改「先世资料未载」），
  健康/压力改现代白话档位（健康良好 / 压力较重…，0 级不写），
  输出文档不再写 `> 存档来源：…` 与「生成时间」，头注释只留 htmlview 要用的字段。
- **言语关系条件化**：`Facts.language_relation_line(s)` 由程序判定「共通X，言语相通」/
  「无共通语，交谈须借通译」并直给，`「语言事实」`规则不再要求模型自行判断语言同异。
- **配偶标签按主体性别**：女性角色的丈夫写「夫婿」（原「妻室商州刺史陆荣廷」）；
  `_genealogy` 的 `spouse` 减去 `primary_spouse`（原「正妻：亮」+「侧室：亮」重复）。
- **行文规则**：`「平行世界规则」`改为「资料未载之处行文径入下一事」，新增
  `「行文落笔」`——治「满篇无可考」（陆氏兜底按语密度 1.79–2.46/千字 → 0）。

## v28b 能力（隐事 / 阴私录 / 要员隐事 / 跨战役加固）

方案与实测见 `docs/方案_秘密入传.md`、`docs/排查_跨战役读取.md`；
验证 `python experiments/verify_secrets.py`（24 断言）、`verify_lushi.py`。

- **跨战役读取加固**：`display_name` 熔件优先；`names.json` 按战役号弃用 + 战役内副本
  （`build_names.py` 写 `output/<家族>/data/names.json`，传记优先读它）；
  `extract_snapshot` 增战役校验（角色 id 跨战役复用，仅凭 player_id 拦不住）；
  `melt_path_for_cache` / `load_latest_melt` 回退前验战役；`_cross_check_deaths`
  不把本战役死亡记录写进他战役缓存。
- **隐事（secrets）逐档差分**：新增 `cache["secrets_history"]`——存档只存「当前秘密」
  且无日期，逐档比对得到「首次见于记载」年份与知情者（`known_by`：谁、自何年知情），
  并记 `lost_at`（不再见于档）。只收与相关集/高位头衔持有人有关的秘密以控体积
  （陆氏 173 条、田所2 1744 条）。
- **《阴私录·隐事秘辛》**（条件生成的第 6–7 篇）：触发＝主角非谋杀隐事 ≥1 ∨
  家人近臣隐事 ≥1 ∨ 主角握他人把柄 ≥1（陆氏触发：2 桩科举舞弊 + 妾灵素不信教；
  田所 27 桩全谋杀 → 不生成，0 额外调用）。谋杀类只计数 + 索引（指向《刺客列传》，
  无该篇时列隐事所涉人名）。隐事笔法规则为正向表述，仅《阴私录》获得隐事事实
  （**不进**主角档案/大事摘要/本纪与朝局的年表切片）。
- **《朝局风云录》要员隐事**：最高领主链（皇帝/路/王国）与朝廷职司时任者的隐事入篇
  （陆氏：枢密使卢彦方科举舞弊、工部尚书张重颖挪用国库；田所：御史大夫郭克勤挪用国库，
  并写出知情者）。
- **朝廷职司按时任**：新增 `Facts.holder_at(tid, date)`，`_current_ministers(date)` 与
  要员隐事一律按 as_of 取时任者——修「十年传记写出后来的任命」（田所2 @878 原写成
  883 年才上任的宰相）。

### v28b：称谓统一 / 隐事省词元 / 文本自然度审计

方案与实测见 `docs/方案_v28b_称谓统一与隐事省词元.md`、自然度清单见
`docs/审计_事实文本自然度.md`；验证 `experiments/verify_label_styles.py`（20 断言）。

- **称谓统一框架**：`Facts.person_label` 成为全项目人物称谓的唯一出词口
  （`full`/`brief`/`event`/`office` 四式 + 六条不变量 + memo）。时间线、记忆句、
  死句、语言句、亲属行、刺客列传、档案名号句、隐事句一律走它——**同一人全篇同一称谓**
  （「商州刺史陆荣廷」不再与「陆荣廷」并存）。office 式不再去宗族姓（修「唐皇帝漼」）。
- **起义领袖称谓**：新增 `cache["factions"]`（`faction_manager` 逐档差分）与
  `Facts.faction_word`——农民/民粹/游牧起义的领袖写「农民起义领袖叠溪寋」，
  替代原先的裸官职词「领袖」（死者 `dead_data.flavor=faction_leader_*`）。
- **隐事省词元**：同一持有人的多桩隐事并成一行（持有人只写一次「有隐事两桩：…」），
  把柄按对方归并，知情者按年升序且同年只写一次年份；`SECRET_RULE` 收窄为
  只随《阴私录》《朝局风云录》下发（其余板块每次请求少 78 字符）。
  实测陆氏：隐事核心块 100 → 73 字符（−27%）。
- **文本自然度 P0**：空块不再下发「（无X记录）」占位串（`_set_block`，9 处）；
  占位名不再进制（称谓出口返回空串、句子槽位用「某人」）；历任句加冒号断句。
  其余 14 项 P1（性情串、特质履历、营地句、僚属任职、现状数字…）已列入审计文档待分批处理。

## v29 能力（周氏十二问题：程序优先 / Mod 本地化 / 动态名 / 档位化）

方案与证据见 `docs/方案_周氏十二问题.md`，回归 `python experiments/verify_zhou.py`（逐条断言），
自然度清单见 `docs/审计_事实文本自然度.md`（P1 第 5/12/13/14 项本轮完成）。

- **干净事实行级兜底**：`facts.sanitize_fact_text` 在所有事实块出口过滤裸键行
  （含下划线的 ASCII 词 / 全大写哨兵串），命中即丢弃并记 `logs/journal.log`。
  起因：熔件 `house_relations.history.change_reason` 出现 rakaly 哨兵串
  `MAX_RECURSIVE_DEPTH`，旧渲染层原样透传 → 模型照抄进《家族恩怨录》。
- **恩怨事件程序重建**：`_rerender_feud_event` 判不可读后，`Facts._feud_event_fallback`
  用缓存记忆（`house_feud_started/ended_memory` 的 attacker/victim/reason、`became_rivals`）
  重写该日句——882.4.8 现写「程氏因族人安南经略使程士庸被杀，与周氏结为世仇。」。
- **【冒险者行踪】**（原【主角处境】）：只记**无地冒险者时期**的营地阶段与驻地
  （`Facts.camp_intervals` / `in_camp_period`）；定居与世族庄园时期的驻地、旅行落点
  一律不下发，无营地期整块消失（周立齐档该块不再出现）。
- **财务档位化**：虔诚/威望/影响力/功勋取**游戏档位词**（`localization.build_currency_levels`
  解析 `common/defines` 的 NCharacter 块 `LEVELS_*` + 本地化 `<kind>_level_N`）——
  现写「虔诚戴罪之人，威望闻名遐迩，影响力人微言轻，功勋六品」；**国库金、月入、
  牧群数值整项不再下发**（口粮给档位词）。
- **传主行迹省主语**：`events_subjectless` 剥去每句句首的传主称谓
  （「勇敢者程岩的亲属程士庸去世」→「亲属安南经略使程士庸去世」）。
- **家室档案去重**：主角子女的档案不再重复 `兄弟姊妹` 名单与 `父<主角>`
  （同批名单此前按人在家室档案里重复 8 次），保留 `母` 以辨生母。
- **言语关系只传「不通」**：家人/同族之间言语相通属常识，程序只下发
  「无共通语，须借通译」一种情形；母语句只保留主角一人（`LANGUAGE_FLAVOR_RULE` 同步收窄）。
- **科举舞弊方向与级别**：`secret_exam_cheater` 的 target 是主考，级别由**同快照考试记忆**
  判定（868.1.1↔乡试、873.1.1↔会试）→ 写「在幽蓟经略使张朴主持的乡试中舞弊」，
  不再写会被读成「考官协助作弊」的「科举舞弊（涉及X）」。
- **动态瘟疫名**：`cache_lib._diff_epidemics` 逐档记录 `epidemics.database`（存档给的是
  游戏算好的动态名：李黯之火/撒丁痘/卡利甫痢）；`facts._plague_facts` 只在疫情触及
  主角封地/所在郡或家人染疫时落笔（「888年6月1日，檀州痘（天花），重疫，疫及主角封地邕州」）。
- **御前会议动态席位**：`localization.build_council_tasks` 解析 `common/council_tasks/*.txt`
  的 `position`，按政体取变体名 → 「御前会议六席：长史（延寿）、司户（思恭）、察事（裴奉先）…」
  （帝国级为 宰相/户部尚书/御史大夫；封建为 掌玺大臣/财政总管）；解析不到即整句不发。
- **职位显示名动态化**：`localization.build_court_positions` 解析
  `court_position_asset.trigger → localization_key`（含 `OR/NOT/NOR`、政体旗标、独立、
  层级、文化传承九个触发词），按雇主政体/层级/传承择名——私人医生→**医学博士**、
  旅队主管→前驱官、宫廷史官→记室参军、总管→殿中监。
- **Mod 本地化自动生效**：`data/localization.json` 记**来源指纹**（游戏目录 + 有序启用
  Mod + 各本地化目录文件数/字节数/mtime），指纹变化即自动重建（新增
  `localization/replace/<lang>` 遍历）；未命中键记 `logs/loc_miss.log`，
  `python localization.py mods|check` 可查。实测启用 `deviants_mask_mod` 后
  其 12081 条中文键即时可用（`trait_deviants_blackmailvictim`=勒索受害者）。
- **特质显示名键表**：`localization.build_trait_names` 解析 `common/traits` 的 `name` 块
  `desc` 键——旅行者（`lifestyle_traveler` → `trait_traveler_1`）等此前因 `trait_<key>`
  缺键而整条丢失的特质恢复显示。
- **技能同步**：`.agents/skills/no-negative-prompts` 增「程序优先铁律（prompt-last）」
  一节与本项目化的职责清单。
- **括注同位语清理**（v29b，用户决策：现代汉语以「职名连写」为正）：御前会议席位写
  「长史延寿」（空席「长史虚悬」）；历任行的类别词改逗号同位语（「周家族乡绅，世族庄园」）；
  世族庄园行改主语句（「世族庄园「周家族」，主人称乡绅。」）；上位链持有人直连
  （「唐皇朝李漼」，营地句同）；家族恩怨改「家族：程氏，两族为世仇」；宝器「宝物：X，名望级」；
  同谋者角色词前置（「同谋张三」）；宗族+分家直连（藤原氏 + 北家 → 藤原北家）。
  日期、生卒、死地、失位缘由、见载年等**补注**仍用括注（现代汉语正常用法）。

## v32 能力（监禁者与出狱方式 / 特质子轨道 / 夭折生母）

方案与证据见 `docs/方案_马克龙三问题.md`；确定性回归 `tools/verify_three.py`（27 条断言）。

- **被囚句点名监禁者**：被囚记忆的 `imprisoner` 槽此前未进句（模板「{name}被囚。」）——
  家室档案行只写「公主被囚」，模型只好自己猜（旧稿写成「囚禁之人，后世皆指为伯爵本人」）。
  现写「X为Y所囚。」，无槽时回退「被囚。」；传主行迹省主语后仍保留监禁者（「为Y所囚。」）。
- **出狱方式二分**：`released_from_prison_memory`（被释放）与 `escaped_from_prison_memory`
  （逃脱）由引擎互斥建立（`prison_on_actions.txt` 未置逃狱旗标才建 released）；后者此前
  槽位/模板/模块三处皆未登记 → 越狱整条不入事实面（马克龙主角 869.10.16 的越狱即如此）。
  现单列「越狱脱逃」模块，配对句按方式分词（「4个月后获释」/「当日越狱脱身」），
  《家室列传》纪事切片补囚禁模块（v31 §12.6 遗留 1 由此消解），囚禁时长把逃脱计入出狱。
- **强纳为妾带日期**：纳妾本身不留记忆，但 `opinions.active_opinions` 的
  `forced_me_concubine_marriage_opinion` 带 `start_date`（本地化「将我强行纳为侧室」），
  且 `concubine_on_accept_effect` 同一段落 `release_from_prison = yes` ——「掳人→囚→强纳为妾」
  的次序由程序坐实，出句「880年，主角强纳戈迪娜·迭戈斯为妾，同日自狱中释出。」
  （旧稿「嫁入年份未见于簿册」，模型遂默认先婚后囚）。缓存新增 `opinions` 逐档差分（纳妾白名单）。
- **特质 XP 子轨道（特质集）**：游戏 `track = {}` / `tracks = {}` 把「不法之徒」这类特质拆成
  若干子轨道（强盗/骗子/窃贼/偷猎者/掠夺者，阈值 20/40/60/80/100），按经验分档换效果。
  - 存法破解：角色 `trait_xp_amounts` 是**与 `traits` 顺序对齐的扁平数组，每轨一个数**
    （实测马克龙档 3987/3987 角色全对）；缓存逐档差分落 `trait_xp` 样本。
  - **修正既有 bug**：`build_trait_names` 旧实现取 `name` 块第一个 desc，而游戏把**最高档**名
    写在最前 —— 54 个按 XP 换名的特质全部显示顶档名（主角 reveler 经验 0 却写「传奇的狂欢者」）。
    现 schema 3：基础名 + 类别 + 档位名条件，渲染期按实际 XP 求值（reveler 0→热切的狂欢者、
    100→传奇的狂欢者）。
  - 轨道名走本地化 `trait_track_<key>`（119/119 命中：强盗/窃贼/骗子/后勤师/行军者…），
    已进档者括注于特质名后（「名声不法之徒（强盗一阶、窃贼二阶）」），进档写入履历
    （「组织者·行军者（自874年起进至一阶，自877年起进至二阶，自878年起进至三阶）」）。
  - 数据层：`data/trait_tracks.json`（86 特质 / 121 轨道）＋ `data/trait_names.json` schema 3；
    `python localization.py traits`（一并重建）或 `tracks`（只重建轨道表）。
- **夭折句点出生母**：`child_stillborn` / `child_premature` 的 participants 是**母亲**，
  此前槽位与模板都没用上（「{name}婴儿夭折。」）→ 模型写「未知其母，只知为某人之血脉」
  （主角只一位妻子，母亲其实早有数据）。现写「X之妻Y产下死婴。」，配偶词按关系取
  （妻/妾/情人；女主人称「之夫」），生母本人持有该记忆（自指）时回退「X产下死婴。」；
  逐年摘要剥称谓时一并删配偶词，不留悬空的「之妻」。
- **附带修正**：主角概览的「被囚」只统计本人被囚（受害者侧句子现在点名监禁者，旧判据
  「名在句中」会把主角囚人误计为被囚）；传主行迹与逐年摘要的称谓剥离统一走
  `_strip_subject_prefix`。

## v33 修正（牵制方向）

- **`first`/`second` 不是持有方向**：存档 `relations.active_relations` 把成对关系**按键
  规范化**存储（实测全档 6950 条 `active_hook_*` 记录 `first < second` 恒成立，无一反例），
  方向只由字段名 `active_hook_<N>` 承载：**N 偶 = `first` 持有对 `second`；N 奇 =
  `second` 持有对 `first`**（`cache_lib.hook_slot_holder`）。
  独立判据：`house_head_hook` 的持有者必为家主，槽 0 有 4919/4920 条 `first` 年长、
  槽 1 有 44/55 条 `second` 年长；Mod `longju_exent` 的 8 处
  `add_hook = {target = scope:npc_2}` 全在 `root`（＝丈夫；`npc_1` 为 `random_spouse`、
  `npc_2` 为通奸者）作用域内，且与该档 opinions 的当事人标记
  （通奸者→丈夫的 `xiangyongletadeqizi_opinion`）逐条吻合。
- v31 曾据单例（玩家 id 恰好小于乔乔）推断「`first` 即持有者」，把主角**自己**的四条
  「干了我老婆」里的三条读成了「他人握有对主角的牵制」；v33 起四条均正确读作主角握有。
  回归：`tools/verify_three.py` [G1]＋`tools/verify_macron.py`（「干了我老婆」不得出现在
  `hooks_over`）。

## v34 能力（柳特佩特七问题：披露分级 / 秘密可读 / 政权门槛 / 特质指纹 / 恩怨因果 / 囚禁区间 / 分篇写法）

方案与逐条证据见 `docs/方案_v34_柳特佩特七问题.md`。

- **披露分级（问题1）**：`villain_chains` 第三元标出**揭底链**（托卵承嗣/血脉登基），
  主角档案分公开档与内部档——公开档不写「实父X」、不写子女来历，
  「实父X」只随《家室列传》《阴私录》《妻族传》下发；
  生育能力类特质（`infertile` 等）在**公开档**整体隐去（史官不可知，用户拍板「不留」）。
- **共享前缀瘦身（问题5）**：`_shared_facts_block` 只留【传主】【家族】【现状】【概览】
  （1181 → 78 字符），【人物档案】与逐年摘要改为**按篇下发**；《本纪》开篇/纪事各取
  本板块切片（旧稿两块逐字节相同）。
- **秘密可读（问题2）**：存档 `secret_incest` 不记对方（`target` 为空），
  改由 `Facts._secret_partner` 按「**血亲 ∩ 性/情记忆**」判定（姻亲排除），
  判不出时退不点名形态；对方不再被算作「知情者」。
- **政权门槛（问题3）**：`_current_ministers` / `minister_ids` 只收
  `de_facto_liege ∈ 主角上位链` 的 `e_minister_*` —— 独立领主的《朝局风云录》
  不再挂着别国六部（实测唐六部 9 席的 liege 全为 `h_china`）。
- **特质表指纹（问题4）**：`trait_names.json` / `trait_tracks.json` 记
  `trait_source_fingerprint`（目录 + 各特质文件元信息），指纹不符自动重建；
  解析失败的特质记 `logs/loc_miss.log`（Carnalitas 的「极小阴茎」即由此找回）。
- **恩怨因果（问题6）**：`house_feuds` 补 `_house_war_nodes` —— 宣战（带战争类型）、
  战胜、失守头衔、**沦为无地冒险者**，并取代同日的旧战争句；
  恩怨之始从「绑人」回到「开战 → 战败 → 夺地 → 对方处境」。
- **囚禁区间（问题7）**：缓存逐档记 `alive_data.prison_data` 区间
  （`prison_history: [{from, to, imprisoner, type, since}]`，`to=null` 为在押），
  释放记忆缺失时凭「区间闭合」补证；有在押数据才写持续关押。
- **子女归属（问题8，用户口径）**：《本纪》收**主角是法理父亲**的全部子女
  （非婚生亦在内，句面不写生父）；法理父是别人的孩子（妻室与他人所出）
  不进本纪，归《家室列传》——其出生句带「生父X」，传主档案另加一句
  「妻室另育有X、Y，此数人之法理父并非主角。」。
  存档的出生记忆记在**生母**名下，故出生句只在持有人不是孩子法理父时才补生父，
  免把生母的生育读成持有人得子（法霍·索丹的生父与法理父均为索丹·索丹，
  旧稿《本纪》却把他算作主角之子）。
- **分篇写法（问题5/1）**：`style.RULES` 增「一篇一题」（主题词 + 决定性时刻 +
  他人视角 + 首尾回照）与「互见法」（一料一处，各篇各题）；每篇文章带 `focus`
  下发到开篇/纪事与总纲预告。

回归：`tools/verify_v34.py`（读快照断言，可 `run()` 内联）＋`tools/verify_v34_once.py`
（**熔件只读一次**：重建单战役缓存 + 落快照 + 跑全部断言，报告写
`logs/verify_v34_report.txt`）＋`tools/check_bio_v34.py`（成稿 md 七问自查）；
`tools/verify_fast.py` 全部 PASS。

## v34b 修正（柳特佩特：头衔创建措辞与头衔事件日期）

方案与证据见 `docs/修复方案_v34b_头衔创建措辞.md`。

- **头衔创建（问题：正文写「受封萨莱诺亲王国」）**：`style.TITLE_GAIN_VERBS["created"]`
  由「受封」改「**创建**」，并按游戏自身两档（`ascended_throne_memory_desc_created_first`
  「作为一个新头衔」/ `_desc_created`「在一段废弃期后」）增设
  `TITLE_GAIN_CREATED_VERBS = {"first": "创建", "restored": "重建"}`；判定入口
  `Facts.title_had_other_holder`（= 游戏 trigger `any_past_holder != owner`）。
  实测：`874年4月26日，…潘杜尔夫·柳特佩特受封萨莱诺亲王国。` →
  `874年4月25日，…潘杜尔夫·柳特佩特重建萨莱诺亲王国。`（该公国 872 年废弃、874 年由玩家创设）；
  陆氏 `867 受封陆家族` → `867 创建陆家族`；`granted` 仍「受封」。
- **头衔事件日期**：游戏 `title_event.9900`（cooldown 1 天）次日才落 ascended 记忆，
  `creation_date` 常晚 0~1 天；`Facts.mem_date` 改为按 title history 取事件日
  （`_title_event_date`：先认 `type == reason`，再按持有侧兜底，与记忆日相差 > 31 天视为
  误配回退），并接到时间线/人物档案/刺客列传/恩怨失守节点四处（去重键与句面日期同源）。
- **连带的恩怨节点同日并存**：夺地日与战胜日同日时，旧实现会把同日「战胜X」节点一并删掉
  （v34 问题6 的因果链断在最后一环）；现只在**关系流水**里做同日取代。
- 回归：`tools/verify_v34.py` 新增 `[11]`（9 条断言）；`experiments/verify_lushi.py`
  断言同步（并修掉自 v30 起恒 FAIL 的「先世资料未载」陈旧判据）。

## v35 能力（德圣塔七问题：考据腔清洗 / 家主牵制 / 奴役语义 / 动态病名 / 文风重构 / 快照纪律）

方案与逐条证据见 `docs/方案_v35_德圣塔七问题.md`。

根因两条：**A. 提示词与事实层把「资料」当叙述话题**（`SECTION_REQ` 20 处「以资料为限」、
`RULES.secret` 的「按资料给出的见载年份落笔」、事实层的「见载 / 【见载年表】 /
此后再未见释放的记载」）→ 模型照抄成「本篇不细载」「未著其年」「档案只此一行」；
**B. 数据该给的没给、提示词却硬要**（事实层给把柄行时丢掉了年份，而提示词要求写出
见载年份）→ 模型只能编「本篇未著其年，则其见载亦在此数年之间」。

- **考据腔清洗（问题1）**：`biography._META_CLAUSE_RE`（新增，整句都是考据话者整句删）
  + `_META_NOTE_RE` 承载词/否定词**双向扩表**（本篇/档案/册上/记事者… ✕ 不细载/未著/
  未署/不着一字/莫得而闻/无从深考…）；删净后只剩标点的整段连标点去掉。提示词侧同步
  剔除「以资料为限／客观平实／别篇」等框架词。
- **见载年由程序给足（问题2）**：《阴私录》的「把柄」段原先单排 `secret_topic` 而丢掉
  年份（同块内「艾哈迈德…（自881年见载）」带年、「握有贞子的把柄：暗行巫术」不带年），
  现统一补 `_first_seen_note`；`_first_seen_note` 改出「N年见于记载」（去「见载」管道词）；
  `focus` 与 `SECTION_REQ["secrets"]` 不再索要「见载年」，只写话题。
- **家主牵制（问题3）**：`house_head_hook`（家主对族人的身份自带牵制）在
  `cache_lib._diff_hooks` **入库前**跳过（`_HOOK_TYPE_SKIP`），`facts.hook_lines` 再兜一层
  —— 此前 `hook_notable` 判它「不算料」而 `hook_lines` 照样下发，德圣塔档塞进 2 条、
  马克龙档曾 8 条。
- **奴役语义（问题4）**：Carnalitas 的 `carn_enslave_effect` 在奴役的**同一刻**执行
  `release_from_prison = yes`，所以存档里那句「释放」记忆正是「没为奴隶」这一步。
  新增 `cache_lib._diff_enslavements` 逐档差分 `opinions.active_opinions[*].scripted_relations.slave`
  → `cache["enslavements"]`（德圣塔 12 条），主教的奴隶入目标集（姓名可解析）；
  `_pair_imprisonments` 先问 `_enslaved_in_span`，是奴役则写「同日没为奴隶」而不再写「获释」；
  《阴私录》新增【奴役】块与「把柄」分列。
- **动态病名（问题5）**：疾病特质（typhus/consumption/smallpox…）渲染时改用**游戏算好的
  当代疫名**（`epidemics.database[*].name`，如「平原热」「丘陵热」），匹配规则＝同型疫情
  存续期覆盖患病起点年、优先「触及该角色属地/所在郡」者、再取起始最晚者，判不出回退
  静态名。实测：主角 872 年伤寒 →「平原热」（疫情 1，870.7.11 起）；家人 880 年伤寒 →
  「丘陵热」（疫情 50331649，878.9.26 起）。`cache["epidemics"]` 增记 `infections`。
- **文风系统重构（问题6）**：删 `MID_TAIL_NOTE`；`RULES` 去「资料」框架
  （`nonfiction`→「落笔所依」、`world_frame`→「自足之世」、`intertext`→「各篇取材」
  不再写「其余各篇以一句指代」「不相复述」）；`SECTION_REQ` 20 处「以资料为限」清空。
- **快照纪律（问题7）**：新技能 `.agents/skills/snapshot-testing/SKILL.md` —— 测试一律走
  快照，同一熔件每会话最多整载一次，`rebuild-cache` 在测试期禁用（改用
  `tools/rebuild_folder.py`），**不删熔件重熔**（本战役 21 档重新熔化实测约 50 分钟）。
- 新增工具：`tools/snapdiff.py`（改动前后**事实面**逐字节对照）、
  `tools/snap_at_head.py`（用 git HEAD 版源码落对照快照）、`tools/snap.py --name=`。

回归：`tools/verify_v35.py`（读快照，七问断言，秒级）＋`tools/check_bio_v35.py`
（成稿 md 自查）；`tools/verify_fast.py` 全部 PASS。

## v41 能力（诺兰八问题：政体时效 / 夺位经过 / 好感开关 / 血脉连线 / 宗支 / 共治者 / 仇人池 / 牵制块）

方案：`docs/方案_v41_诺兰八问题.md`；**问题 1 的口径修正见 `docs/补正1_v41_封建期头衔词.md`**
（我最初判「头衔词没取错」是错的：神罗 1087–1094 是**封建制**，那段时期领主在游戏里
就是公爵/伯爵，程序却按末档的行政制一律取将军/军区/分区）。

程序端八项改动（**0 条新增提示词**）：

1. **政体按日期取，不再一律用末档** —— 三条一起改才生效：
   - `cache_lib` 逐档记录 `cache["char_government_history"]{cid: [{date, government}]}`
     （变化点，与 `camp_purposes` 同范式）；
   - `facts.Facts._character_government(cid, date)` / `_title_government(tid, date)`：
     取该日**时任持有者**的政体；日期早于该角色史起点时返回空（由通用词条兜底），
     `official_title` 读缓存末档政体的旧路径一并改掉（那是错词的直接来源）；
   - `flavorization.resolve` 补上**从未实现**的 `ignore_top_liege_government` 规则
     （游戏 `common/flavorization/_flavourization.info:195-202`：该旗标为真时
     **仅 government** 用本人政体）。缺这一行时，行政制词条会去比最高领主的政体，
     把封建留守封臣一并吞成「将军/军区/分区」。
2. **头衔取得方式** —— `facts._holder_intervals` 建索引时保留 gain 事件类型与前一持有人
   （旧稿只留 `(gain, loss, loss_type)`，gain 缘由被丢），新增 `gain_reason` /
   `prev_holder` / `_gain_clause`：历任阶段行写成
   「1086年1月1日自重臣X手中夺得神圣罗马帝国巴西琉斯」，不再只有裸头衔名。
3. **`cache_lib.player_title_history` 用 title history 事件日**（1086.1.1）
   而非快照日（1087.1.1）。
4. **政体变更事实** —— `facts.government_changes()` 出
   「1086年1月1日改行行政官制（原封建采邑制）」一句。
5. **`carnal_opinions` 改开关制**（`config.json` 的 `carnal_opinions`，默认 **false**）：
   本档 29 条全是「曾强奸我/曾强奸家庭成员」式评断，与性事记忆渲染的「强迫之事」
   行逐条重复；关掉即整族不下发，打开恢复旧行为。
6. **同父异母联姻连线** —— `facts._kin_blood_links()`（只进《家室列传》《阴私录》）：
   「…主角之女安娜与黑罗尔德结为夫妇；黑罗尔德实为主角与奥达·魏玛之子，
   与安娜为同父异母兄妹」。旧稿三条料分居三处，模型读不出这层关系。
   血统类隐事主题同时点名**实父**（`style.SECRET_TOPICS` 增 `{father}` 位）。
7. **宗族宗支句** —— `facts.clan_line()`：「东盎格利亚为布里奥讷宗族的分支。」
   （分家名 ≠ 宗族名才出；按用户定规**不写「主支为谁」**）。
8. **共治者身份** —— 读熔件 `diarchies`（`type=co_*`）+ 角色变量 `use_co_ruler_title`
   双条件（游戏 `00_title_holders.txt:10191-10219` 的 `co_ruler_male`），
   出「共治巴西琉斯，君主神圣罗马帝国巴西琉斯。」（与游戏自缓存渲染串逐字一致）。
9. **仇人池加「与主角的互动分」**（`biography._shared_history_score`，软口径）：
   排序键改为 (共享史分, 本十年共享史分, 候选人自己的事迹分, 在世, 结仇最早)。
   旧稿只数候选人自己的生平，实测会把只与主角结过一次仇、却有三任妻子与多场战争的
   波美拉尼亚国王选成仇人列传传主。
10. **牵制块去掉「…的牵制如下：」两条标题行**（`style.FACT_WORDING` 删
    `hook_head_held` / `hook_head_over`）：每条牵制句本已自足，标题行只会把该维度
    引成开放清单，模型据此自行铺陈「御前会议诸臣互握把柄」等无据情节。

回归：`tools/verify_v41_unit.py`（离线合成数据，**29 PASS / 0 FAIL**）；
`tools/verify_fast.py` 新增 `[V41]` 组（含「封建期档不得出现行政制专有词」断言）；
`tools/verify_v39_unit.py` 49 PASS、`tools/verify_v40_unit.py` 32 PASS、
`experiments/verify_v38_unit.py` 21 PASS（该组显式打开 `carnal_opinions` 以验旧行为）。

> 缓存需重建一次以带上 `char_government_history`：
> `& tools\py.ps1 tools\rebuild_folder_v38.py 诺兰`

## v43 能力（婚姻线系 / 《宝物志》跨篇与部件档 / 自指式恩怨句）

方案与实施记录：`docs/方案_v43_婚姻线系与宝物志.md`；游戏侧调研：
`logs/research_house_relation_selfref.md`。**0 条新增提示词**，全部程序端。

1. **母系婚（入赘）判定**：CK3 只在存档 `relations.active_relations` 上给出
   `{"first":A,"second":B,"matrilineal":true}` 这一个直接标记（游戏规则原文：
   「在母系婚姻中，出生的孩子将属于**母亲的家族**而不是父亲的」，交互界面写作
   「切换入赘」）。`cache_lib._latch_matrilineal` 逐档**闩存**（离异/丧偶后条目会消失，
   传记要写的却是当年那桩婚事），`facts.is_matrilineal` 三级判据
   （当前熔件 → 缓存闩存 → **婚后**所生子女的家族归属），判不出即不下发。
   四处下发口同出「（入赘婚：所生子女随母方，属X氏）」：年表/档案成婚句、
   主角档案妻室行、《家室列传》亲缘行、终传世系表正妻行。
   *私生一律随母方、与线系无关*，故第三级只看婚后所出（否则诺兰娶波兰女王会被误判入赘）。
   既有缓存补键：`& tools\py.ps1 tools\refresh_matrilineal.py 诺兰 62045`。
2. **《宝物志》跨篇去重 + 角色部件档**：改前第 2/3/4/5 个十年与终传逐字是同样五件名望级
   重宝。现在`_artifacts_written_before()`（纯函数：对更早每个十年截止日重跑同一选材规则
   取并集）让十年篇只写本十年**新得**者，终传收全量；无新宝的十年省去该篇。
   另开乙档「角色部件宝物」（`visuals.type ∈ {skull_goblet, human_skull}` 或描述含
   头骨/头颅/乳牙；不限稀有度、不要求曾被外族持有），描述里的
   `ONCLICK:/TOOLTIP:/L` 数据函数块就地清洗并用本项目称谓重渲染
   （「用爱沙尼亚国王特尔·库克的头骨制成」）。
3. **自指式恩怨句**（`A试图谋杀A`）：游戏脚本 `00_murder_effects.txt:709` 与
   `00_adultery_effects.txt:129` 把 `TARGET_CHAR` 填成 `root`，root 恰是行为者本人时
   两端烘焙成同一角色，第二人**没有写进存档**。渲染层降级为族级对手方：
   「基里雅科·诺兰试图谋杀库克氏族人」。

回归：`tools\snap.py` 五篇快照 + `tools\verify_fast.py`（新增 `[V43]` 组）
final/d2/d4/d5 全 PASS；单测 v39 49 / v40 32 / v41 41 全 PASS。
`d3` 仅 `[V42][3]`（窗口内阉/盲记忆并入囚禁行）FAIL，系**窗口边界**旧疾
（受害者自 1080 年起 house arrest，囚禁记忆在窗口外），与本轮改动无关。

## v44 能力（诺兰六问题：姓氏沿革 / 传主链 / 亲子字段 / 族属沿革 / 冷熔件归档 / 中文名优先）

方案与实施记录：`docs/方案_v44_诺兰六问题.md`。**0 条新增提示词**，六件全部程序端。

1. **家族沿革（私生女别立家族 + 家族/宗族改名）**：阿德尔海德 1118.4.2 别立
   「冯·亚琛氏」（宗族弗兰肯），1133 年家族改称「冯」，1146 年宗族亦改称「冯」——
   旧实现把 `dynasty_house/house_name/dynasty_name/name_full` **首见即冻结**，于是
   她终身被写成「阿德尔海德·诺兰」。现逐档差分记 `house_history`
   （`{from, house_id, house_name, dynasty_id, dynasty_name}`，别立那一点的日期取游戏
   `found_date`），`cache_lib.display_name(..., date=)` 按篇截止日取家族名与**族属名序**
   （1132 年转汉人前是「阿德尔海德·冯·亚琛」，之后才是「冯阿德尔海德」），
   传主档案新增「家格」沿革句。战役文件夹名取沿革**首点**之名（改名不改目录），
   传记文件名 `bio_pname` 首次即钉存 —— 两者都不让改名把已有产物「改名重生成」。
2. **传主链（前任/后任传主）**：新版本玩家死后可从宗族里挑人继位，亲缘判定不足以还原
   「怎么接上的」。存档 `played_character.legacy` 正是**有序带日期的玩家接替链**
   （末条的日期＝继位日＝前任死亡当日），逐档入库 `cache["played_legacy"]`；
   `facts.succession_lines` 出「承继：1117年6月19日，其父、前代传主X崩于当日，
   传主之位自此归本传主。」（亲缘词由亲属图判定，判不出只写「前代传主X」）。
   `pipeline.generate_bio` 把**同战役全部传主缓存**传给 facts（`campaign=`）。
3. **亲子字段按性别取**：`legal_children_ex` 旧实现只认子女的 `father` 字段，女主亲生
   子女因此全被判成「配偶与他人所出」，程序还替模型写好「此数人之法理父并非主角」——
   模型由此写出整段「儿子与丈夫没有关系」的血脉疑云（阿德尔海德档实测）。
   现按本人性别比 `mother`/`father`，措辞亦按性别（「夫婿另有子女X，其法理母并非主角」）。
4. **族属沿革（法兰克尼亚人 → 汉人）**：`extract_snapshot` 里一处**提前赋值**让紧随其后的
   逐档差分恒为假，`culture_history` 永远只有首点（对照 `faith_history` 无此赋值故一直正常）。
   删该行后「族属：原为法兰克尼亚人，1132年起为汉人。」可出；`facts.culture(pid, as_of)`
   与母语句同样按篇截止日取。
5. **冷熔件 gzip 归档**：82 份全量熔件 14.12 GB + 80 份记忆边车 1.92 GB → **2.23 + 0.24 GB**
   （gzip-6 压到 15.3%，读取代价 +0.6s/份；`output/诺兰` 整体 16.31 GB → 2.99 GB）。
   `cache_lib.open_melt_text` / `melt_file_exists` / `_melt_index_variants` 让全部读取口
   （`load_melt`/`load_melt_index`/`melt_file_in`/`_iter_melts`/`_backfill_tail_deaths`/
   `snap.py`）同时认 `.json` 与 `.json.gz`；`pipeline.py compact` 只压「非最新」的熔件与边车
   （最新一份保持明文），watch/continue 启动即由后台线程跑一轮、此后每 10 分钟补一轮。
6. **中文名优先（Mod 英文不得顶掉本体中文）**：建表旧序是「根在外层、语言在内层」，
   于是 Mod `longju_exent` 的 `Mathilde:0 "Matilda"` / `Marie:0 "Marry"` 压掉了游戏本体的
   `Mathilde: "玛蒂尔德"` / `Marie: "玛丽"`，人物写作 `Matilda·萨伏依`。改为
   **语言在外层、根在内层**（任何根的中文压过任何根的英文；同语言内仍是 Mod 覆盖本体），
   `localization.json` schema 升至 3（读到旧表即自动重建）。

回归：`tools\snap.py` 重建快照（阿德尔海德 d1/d2/final + gz 探针、克里斯托弗 final/d4）
→ `tools\verify_fast.py` 新增 `[V44]` 组；克里斯托弗两篇与 `snap_v43_final` **全 PASS**，
阿德尔海德各篇只余**改动前就存在**的旧疾（`[2] 实父为自己`、面向已故主角终传的
`[3]/[6]/[8]` 三条对其在世档不适用）。单元回归 `experiments\verify_v44_unit.py`
（亲子字段/家格句/传主链/族属取值/同胞长幼）与 `experiments\verify_v44_extract.py`
（运行期逐档差分，4 个沿革点全部命中）全 PASS。既有缓存补历史：
`& tools\py.ps1 tools\refresh_house_history.py 诺兰`（纯 `json.load` 重放 82 档，约 48 分钟；
`--names` 为只按末档重算现值的秒级快修）。

## v45 能力（板块期亲缘定语）

方案/研究/实施记录：`docs/研究_v45_亲缘定语.md`（§11 为实施记录）。**0 条新增提示词**。

素材面在**称谓前**加一层亲缘定语：`妻子康斯坦恰·皮雅斯特`、`姻亲兄弟托马什·皮雅斯特`、
`父亲唐皇帝李漼` —— 定语是称谓**之外**的附加层（`person_label` 仍是唯一称谓出词口），
且每个**板块**内同一人只加一次。判据全在程序端：

* 词源：游戏本地化（`relation_father`/`relation_wife`/`relation_brotherinlaw`…）带兜底常量；
  长幼按中文习惯自造（`birth` 判年长→兄长/姐姐，年幼→弟弟/妹妹，缺生年回落游戏「兄弟」/「姊妹」）；
  定语一律用双音节词（父亲/兄长/岳父），史传旁称（传主链的「其父」「其兄」）用单字（`KIN_SHORT`）。
* 判据 `kin_key(cache, subject, cid)`：直系 → 同胞+长幼 → 配偶（前配偶不算，双向并集，
  反向配偶边由 `Facts._spouse_back_index` 兜住）→ 岳父 → 女婿/儿媳 → 姻亲兄弟姊妹 → 继子女；
  **判不出返回空**（性别不可判不标，宁缺勿错）。纯函数，可用缓存秒级断言。
* 板块登记表 `KinScope` 是 `_article_facts` 内的**局部对象**（该函数并发调用，挂 `Facts`
  上会串味）：`absorb(此前各块文本)` + `mentioned()` 实现「首次」语义，另记 `stats`/`held`
  供计量。基准人＝该篇传主（《列传》即好友/仇人本人），传主本人不加。
* 落地点（档 A）：档案名号句（传主档案 / 家室档案逐人）、朝中要员名录、刺客列传死者行。

**实测（S1 字面语义，`melt_1148_01_01.json`）**：克里斯托弗终传 19 板块实加 2 处（+8 字），
阿德尔海德终传 0 处 —— 因为【传主档案】排在最前、其家世行（「妻室X」「子A、B」）已按 S1
消费掉配偶/子女的名额。真正的覆盖面在**年表/隐事**（档 B，本轮未做），
`docs/研究_v45_亲缘定语.md` §7 的 394 条属**档 A+B**口径。

回归：`tools\verify_fast.py` 新增 `[V45]` 组（标注能用同目录缓存复算 / 词表内 / 落在本板块 /
同板块每人至多一次 / 不标本篇传主 / 同板块算两遍逐字相同 + 6 条纯函数断言）；
`experiments\verify_v45_unit.py`（21 条）与 `verify_v44_unit.py` 全 PASS；
克里斯托弗 v45 快照**全部 PASS**，阿德尔海德只余改动前既有的 5 条旧疾。

## 代码纪律（2026-09-10 用户定规）

- **每次破坏性改动前必须先 commit**：动手改 `facts.py` / `biography.py` / `cache_lib.py` /
  `pipeline.py` / `llm.py` 等生产代码之前，先把当前工作树提交为一个检查点，
  保证任何一步都能干净回退。改动分步进行，每步一个提交。
  可执行细则见技能 `.agents/skills/commit-before-destructive/SKILL.md`。
- **测试走快照，不重熔存档**（v35）：先看 `output/<家族>/data` 有没有现成的
  `melt_*.json` 与 `snap_*.json`，有就直接用；断言跑在快照上（秒级），
  熔件每会话最多整载一次。细则见技能 `.agents/skills/snapshot-testing/SKILL.md`。
- **提示词正向表述**：写给模型的每一句都用「要做什么」表述（见技能 `no-negative-prompts`）。
- **编码**：Python / JSON / 日志 / output 产物一律 UTF-8，`.bat` 用 GBK（见技能 `utf8-gbk-encoding`）。

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
python build_names.py              :: 重建全档人名表 data/names.json（含姓氏/宗族名，本地化）
python localization.py build       :: 重建本地化表 data/localization.json（启用 Mod 变化时自动重建）
python localization.py mods        :: 列出启用 Mod 的本地化覆盖与来源指纹（v29）
python localization.py levels      :: 重建档位阈值表 data/currency_levels.json（v29）
python localization.py positions   :: 重建职位显示名变体表 data/court_positions.json（v29）
python localization.py council     :: 重建议会席位表 data/council_tasks.json（v29）
python localization.py traits      :: 重建特质显示名键表 + 轨道表（v29/v32）
python localization.py tracks      :: 只重建特质 XP 轨道表 data/trait_tracks.json（v32）
python localization.py province    :: 重建省份映射 data/province_map.json（首次自动）
python localization.py dynasties   :: 重建宗族/家族定义表 data/dynasties.json（首次自动）
python pipeline.py watch [秒]      :: 新档监控：新战役新建文件夹（重名 → 哈布斯堡2）
python pipeline.py continue [秒]   :: 旧档续传：自动沿用最新文件夹，补录当前战役后监控
python pipeline.py scan            :: 单次：只补录当前战役（同战役）的新档
python pipeline.py status          :: 打印各玩家缓存状态（家族/来源档/记忆数/生死）
python pipeline.py bio [玩家id]    :: 手动生成传记（在世传记或终传）
python pipeline.py demo-death      :: 模拟主角死亡，演示「死后自动生成」链路
python pipeline.py rebuild-cache   :: 从各战役文件夹熔件重建缓存（迁移/修复）
python pipeline.py migrate         :: v4 迁移：旧 cache/ 移入 output/<家族>/data/ + 重建
python htmlview.py rebuild         :: 重建所有宗族文件夹的 index.html
python tools\verify_v34_once.py 柳特佩特 38653 878.1.1
                                   :: v34 一次性验证: 熔件只读一次 → 重建该战役缓存
                                      + 落快照 + 跑七问断言 (报告 logs/verify_v34_report.txt)
python tools\verify_v34.py         :: 只读已有快照重跑断言 (秒级)
python tools\check_bio_v34.py       :: 成稿 md 七问自查
python tools\verify_v35.py [快照] [--player=38670]
                                   :: v35 七问断言 (读快照, 秒级)
python tools\check_bio_v35.py [家族] [md名]
                                   :: v35 成稿自查 (考据腔/奴役/动态病名)

:: 提速基建（开发/验收用；熔件 100–125MB，载一次要 1–3 分钟，不要反复整载）
:: 纪律见技能 .agents/skills/snapshot-testing —— 先看有没有现成 melt/snap，有就直接用；
:: 断言跑在快照上；rebuild-cache 测试期禁用（改用 rebuild_folder.py）；不删熔件重熔。
& tools\py.ps1 tools\snap.py 周氏 38673 889.1.1 2   :: 落 facts 快照（含各篇 blocks 与逐请求提示词）
& tools\py.ps1 tools\snap.py 德圣塔 38670 888.1.1 2 --name=snap_x  :: 自定义快照名
& tools\py.ps1 tools\verify_fast.py                  :: 快速回归（无熔件，秒级）
& tools\py.ps1 tools\snapdiff.py <旧快照> <新快照> --facts-only  :: 改动前后事实面逐字节对照
& tools\py.ps1 tools\snap_at_head.py 德圣塔 38670 878.1.1 1      :: 用 git HEAD 版源码落对照快照
& tools\py.ps1 tools\rebuild_folder.py 德圣塔 38670              :: 只重建这一个战役的缓存
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
| `pipeline.py` | 主流水线：watch/continue/scan/status/bio/demo-death/rebuild-cache/index-melts/compact/migrate |
| `cache_lib.py` | 缓存库 v4：每玩家缓存、姓名合并、本地化名字、反向亲属索引、特质履历、朝局历史 |
| `localization.py` | 本地化解析（游戏+启用 Mod YML）、省份→伯爵领映射、政体层级词 |
| `facts.py` | 干净事实渲染层（模型只收中文事实，无裸键值） |
| `biography.py` | 杂志式五篇纪传体传记生成器（并发调 LLM，提示词全正向表述） |
| `llm.py` | 自包含 DeepSeek 调用管线（日志/提示词日志/截断重试） |
| `htmlview.py` | 宗族阅读页生成器（自包含 index.html，离线可读） |
| `build_names.py` | 全档角色名映射表（含姓氏，本地化，供姓名合并兜底） |
| `data/` | 全局表：names.json + localization.json（含来源指纹）+ province_map.json + dynasties.json + currency_levels.json + court_positions.json + council_tasks.json + trait_names.json + trait_tracks.json（各战役共用，v29 起启用 Mod 变化即自动重建） |
| `output/<宗族>/data/` | 每玩家记忆缓存 + 熔化存档 melt_*.json（v6 起，与缓存同目录；**v44 起冷熔件与其边车 gzip 归档为 `.json.gz`**，最新一份保持明文） |
| `output/` | 传记输出（按宗族分文件夹） |
| `experiments/` | expck3 的旧实验脚本（历史参考，不入流水线；`verify_lushi.py` / `verify_tadokoro2.py` / `verify_zhou.py` 为确定性回归） |
| `tools/enc.ps1` / `tools/py.ps1` | 开发工具链：统一 UTF-8 子进程输出（免中文乱码往返），`& tools\py.ps1 <脚本>` 跑 Python |
| `tools/snap.py` / `tools/verify_fast.py` | 提速基建（v29b）：熔件载一次落 facts 快照（几十 KB），快速回归秒级跑；端到端仍走 `experiments/verify_zhou.py` |

## 已知限制

- 角色死亡时游戏移除其 `alive_data`（含记忆列表）→ 普通死者靠**历年存档缓存**恢复；
  **曾为玩家（was_playable）的角色**记忆保留在 `dead_data.memories`，死亡档可直接读取。
- 战争只存活跃状态，历史战役靠战役类记忆。
- 出生地不在存档中，未写入传记。
- 特质履历日期为快照粒度（年度存档），首快照已具的特质写「至晚自X起已具」。
- 个别未收录进本地化的名字（Mod 新增）按码点解码或原样显示。
