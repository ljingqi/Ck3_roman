# -*- coding: utf-8 -*-
"""文风提示词系统 (style.py)
================================
本项目的**「字」的唯一出口** —— 写给模型的每一句写作指令、每篇的板块标题与要求、
请求包裹文案, 以及事实层的措辞表 (记忆句模板/死因词/统计标签…), 全部集中在此。

设计对齐 `D:\\Journal\\style.py`: 纯数据 + 少量纯函数的**叶子模块** (不 import
本项目其它模块), biography.py / facts.py 反向依赖它。改文风只动这一个文件。

分区
----
1. `STYLE_PROFILES`  东方纪传体 / 西式传记两套笔法与评点收束语
2. `RULES`           写作规则 (正向表述铁律见 .agents/skills/no-negative-prompts)
3. `SECTION_TITLES`  11 篇文章的板块标题
4. `SECTION_REQ`     各篇各板块的取材要求 (含戏剧引导)
5. `THEME_LABELS`    官职轮转政体的主题换词表
6. `PROMPTS`         请求包裹模板 (system 头 / 总纲 / 开篇 / 纪事, 具名槽位)
7. `FACT_WORDING`    事实层措辞 (记忆句模板、死因词表、统计标签、聚合动词)

注意: 新增/修改提示词时遵守两条铁律 ——
  (1) 一律正向表述 (不写「不要/避免/禁止」, 改写为「要做什么」);
  (2) 程序能确定性完成的一律落在程序端, 提示词只承担创作性写作。
`RULES` 里出现过「资料未载/资料未提供/资料不足」这类词, 模型会逐字照抄进正文
(菲利普实测 44 次 → 正文 33 处考据按语), 因此这类「缺料按语」一律不写。
"""

# ---------------------------------------------------------------------------
# 1. 文风档案
# ---------------------------------------------------------------------------
STYLE_PROFILES = {
    "east": {
        "jizhuanti": (
            "「纪传体」笔法: 仿《史记》纪传体——以人物为中心, 按时间次序叙其一生, "
            "客观叙事, 夹叙夹议, 善用细节、对话与场景铺陈; "
            "文章末尾以「太史公曰」作史家评点收束。"
        ),
        "tail_title": "评曰·太史公曰",
        "tail_req": "总评其一生的功过得失与性格命运, 以「太史公曰」收束。",
        "review_mark": "太史公曰",
    },
    "west": {
        "jizhuanti": (
            "「传记体」笔法: 仿西方古典传记 (普鲁塔克《名人传》体例)——以人物一生为纲, "
            "穿插轶事、对话与性格细节, 夹叙夹议, 兼作道德评点与命运省思; "
            "文章末尾以「史家按」作评点收束。"
        ),
        "tail_title": "评曰·史家按",
        "tail_req": "总评其一生的品性功过与命运沉浮, 以「史家按」作结。",
        "review_mark": "史家按",
    },
}
DEFAULT_STYLE = "east"

# ---------------------------------------------------------------------------
# 2. 写作规则 (system 规则块)
# ---------------------------------------------------------------------------
RULES = {
    "nonfiction": (
        "「非虚构铁律」: 资料给出的人名、地名、日期、数字、事件一律按资料原样书写; "
        "人物的心理、对话、场景、细节在资料允许的范围内合情演绎; "
        "叙述依资料可据之处依次推进, 以已知的人事时地把场面写足。"
    ),
    # v30: 曾写「资料未载之处行文径入下一事」— 模型把那几个字照抄成满篇考据按语,
    # 现只写「按资料给出的写法书写」。
    "world_frame": (
        "「平行世界规则」: 本传所写世界完全由本提示词资料构成, 与任何真实历史无关; "
        "所有人物、家族、官职、事件、日期、数字一律按资料给出的写法书写。"
    ),
    "narrative_focus": (
        "「行文落笔」: 每一句都落在具体的人、时、地、事上, 由资料可据之处依次推进; "
        "叙述连贯、史笔简劲, 与所写人物的处境相称。"
    ),
    "plain_word": (
        "「平实用词」: 一切死亡事件一律用现代平实词表达——死于(某年某月某日)、"
        "病逝、去世、逝世、战死、遇害、被杀、被处死。"
        "例:「某年某月某日，某人死于某地」「某人病逝于某年」「某人战死/遇害/被杀」。"
        "帝王、君主、贵胄与庶民一律用同一套词; 全文的死亡表达与这套词完全一致。"
    ),
    "title_consistency": (
        "「称谓一致」: 亲属与相关人物一律用资料给出的称谓书写"
        "(高昌国王毗伽庞特勤、可萨布兰部可敦塔坦尼·布兰、楚国郡主苗映娘); "
        "同一人在全篇各处用同一称谓。"
    ),
    "secret": (
        "「隐事笔法」: 隐事一律按其记载形态书写——至今无人知晓者写其事隐秘、时人未觉; "
        "已有知情者时写明知情之人与此后往来; 各处隐事按资料给出的见载年份落笔。"
    ),
}

# system 规则块的下发顺序 (隐事笔法只随携带隐事事实的板块下发)
_RULE_ORDER = ("nonfiction", "world_frame", "narrative_focus", "plain_word",
               "title_consistency")
# 携带隐事事实的板块 (secrets 篇与朝局篇的要员隐事)
SECRET_BOARDS = ("secrets", "chaoju")


def rule_block(style=DEFAULT_STYLE, secret=False):
    """system 规则块文本。"""
    prof = STYLE_PROFILES.get(style) or STYLE_PROFILES[DEFAULT_STYLE]
    out = "\n".join([prof["jizhuanti"]] + [RULES[k] for k in _RULE_ORDER])
    if secret:
        out += "\n" + RULES["secret"]
    return out


# ---------------------------------------------------------------------------
# 3/4. 篇目板块标题与取材要求
# ---------------------------------------------------------------------------
SECTION_TITLES = {
    "benji":   {"lead": "开篇·家世与出身", "mid": "纪事·一生大事", "tail": None},
    "friend":  {"lead": "开篇·家世与交游", "mid": "纪事·一生际遇", "tail": None},
    "enemy":   {"lead": "开篇·仇家身世",   "mid": "纪事·一生行迹", "tail": None},
    "jiashi":  {"lead": "开篇·结缡与离异", "mid": "纪事·门庭恩怨", "tail": None},
    "chaoju":  {"lead": "开篇·天下大势",   "mid": "纪事·朝局浮沉", "tail": None},
    "assassins": {"lead": "开篇·刀下之魂",
                  "mid": "纪事·诸魂行迹",
                  "mid1": "纪事·诸魂行迹·上",
                  "mid2": "纪事·诸魂行迹·中",
                  "mid3": "纪事·诸魂行迹·下",
                  "tail": None},
    "youxia":  {"lead": "开篇·萍踪浪迹",   "mid": "纪事·辗转行迹", "tail": None},
    "qizu":    {"lead": "开篇·帝胄姻亲",   "mid": "纪事·门第荣枯", "tail": None},
    "qunying": {"lead": "开篇·朝堂群英",   "mid": "纪事·要员浮沉", "tail": None},
    "feuds":   {"lead": "开篇·世仇渊薮",   "mid": "纪事·恩怨始末", "tail": None},
    "artifacts": {"lead": "开篇·传家重宝", "mid": "纪事·流转始末", "tail": None},
    "secrets": {"lead": "开篇·隐事之始",   "mid": "纪事·阴私秘辛", "tail": None},
}

# 板块要求: 每条都写「本篇须写出什么」, 一律正向表述
SECTION_REQ = {
    "benji": {
        "lead": "从家世出身写起: 生于何年、家族渊源、族属信仰、性情特质, 立起人物一生基调。",
        "mid": "按时间次序叙述一生大事: 执掌领地、经营营地或世族庄园、受任官职、让土、结仇、家变、再娶等, 以年表资料为限。本篇写出主角的登位与失土时刻、战争与囚狱转折, 把每个关键日期写成戏剧场景。",
        "tail": None,
    },
    "friend": {
        "lead": "写传主与主角的交游渊源: 二人如何相识、同处何朝何地, 传主的家世与出身。",
        "mid": "叙述传主一生际遇: 婚姻、被囚、失土、起复、登位、结友等, 以资料为限。本篇写出传主与主角结友的时刻与缘由, 以及二人交游中的聚散。",
        "tail": None,
    },
    "enemy": {
        "lead": "写仇家身世与结仇之由: 传主何许人也, 与主角因何成仇。",
        "mid": "叙述仇家一生行迹: 登位、婚姻、情事、结仇、私情等, 以资料为限, 客观平实叙述。本篇写出结仇的日期与由头, 以及仇怨在何时何地爆发。",
        "tail": None,
    },
    "jiashi": {
        "lead": "写主角婚配始末: 结缡、离异、前妻之死、再娶, 立起门庭画卷; 妻族门第 (妻之父兄等显贵亲眷) 若有资料一并铺陈。",
        "mid": "写门庭恩怨: 前妻与仇家之情事、他妇之怨、子女状况, 以资料为限。本篇写出妻妾子女的聚散离合: 结缡、离异、诞育、夭折的日期与情境。",
        "tail": None,
    },
    "chaoju": {
        "lead": "写天下大势: 以最高领主或皇帝及其更替为纲, 铺陈本期朝局格局与主角所处疆域, 以资料为限。",
        "mid": "写朝局浮沉: 依朝局动态与要员名录, 叙述登位、失土、囚狱、结仇、战争等朝局大事, 以资料为限。本篇写出帝位或最高领主的每次更替, 主角在朝局中的升沉。",
        "tail": None,
    },
    "assassins": {
        "lead": "写被主角所杀诸人的群像: 各人身份、与主角的恩怨由、死时情状, 以资料为限, 客观平实。死法按资料所写的具体手法 (毒杀、缢杀、溺毙、失踪等) 写出。",
        "mid": "依死亡先后为序, 为每名死者立一小传: 生平行迹、与主角的交集、死因, 以资料为限。本篇写出死者生前的家世亲缘与婚恋际遇, 再写其死时情状, 死法按资料所写的具体手法 (毒杀、缢杀、溺毙、失踪等) 写出。",
        "mid1": "依死亡先后为序, 为这一时期 (最早所诛) 的每名死者立一小传: 生平行迹、与主角的交集、死因, 以资料为限。本篇写出死者生前的家世亲缘与婚恋际遇, 再写其死时情状, 死法按资料所写的具体手法 (毒杀、缢杀、溺毙、失踪等) 写出。",
        "mid2": "依死亡先后为序, 为这一时期 (中期所诛) 的每名死者立一小传: 生平行迹、与主角的交集、死因, 以资料为限。本篇写出死者生前的家世亲缘与婚恋际遇, 再写其死时情状, 死法按资料所写的具体手法 (毒杀、缢杀、溺毙、失踪等) 写出。",
        "mid3": "依死亡先后为序, 为这一时期 (暮年所诛) 的每名死者立一小传: 生平行迹、与主角的交集、死因, 以资料为限。本篇写出死者生前的家世亲缘与婚恋际遇, 再写其死时情状, 死法按资料所写的具体手法 (毒杀、缢杀、溺毙、失踪等) 写出。",
        "tail": None,
    },
    "youxia": {
        "lead": "写主角萍踪浪迹的游侠生涯: 起于何地、如何成营、一路辗转, 以行纪资料为限。",
        "mid": "按行纪次序叙述漂泊行迹: 每至一地的时间、所驻之地、与当地势力的交集, 以资料为限。",
        "tail": None,
    },
    "qizu": {
        "lead": "写主角妻族门第: 妻妾中帝胄姻亲的身世 (公主头衔或中华皇帝之女/姐妹), 其父兄辈的显赫, 以资料为限。",
        "mid": "写妻族与主角家室的牵连: 姻亲之荣、门第之变, 以资料为限。",
        "tail": None,
    },
    "qunying": {
        "lead": "写朝堂要员群像: 主角为行政制官员, 本篇铺陈同朝要员名录与身位, 以资料为限。",
        "mid": "依朝局动态叙述要员浮沉: 登位、结仇、囚狱、战争等, 以资料为限。",
        "tail": None,
    },
    "feuds": {
        "lead": "写与主角家族关系不和的各家族: 结怨之由、恩怨始末、当前关系档位 (世仇/敌对/争吵), 以资料为限。",
        "mid": "依事件史叙述各家族的恩怨始末: 联姻、囚禁、处决、宣战、反目等, 以资料为限。本篇把每段恩怨的起点 (劫掠/囚禁/处决的日期与由头) 写到收束, 让恩怨链条完整可见。",
        "tail": None,
    },
    "artifacts": {
        "lead": "写主角家族所藏重宝: 宝物名称、形制、稀有度, 立起传家重宝的画卷, 以资料为限。",
        "mid": "依流转史叙述每件宝物的来历与流转: 何人造、何时被何人夺得或继承、现藏何处, 以资料为限。",
        "tail": None,
    },
    "secrets": {
        "lead": "写主角身上的隐事: 何事、涉及何人、自何时见于记载、有谁知情, 以资料为限; 立起「其人其行之外另有隐情」的底色。",
        "mid": "写家人与近臣的隐事、把柄的所属与流转: 谁藏何隐事、谁已知情、此后往来如何, 以资料为限。本篇写出各处隐事的见载年份与知情者的身份。",
        "tail": None,
    },
}
# 纪事板块的统一尾注
MID_TAIL_NOTE = "本篇正文均为客观叙事，史家评点集中于总纲。"

# ---------------------------------------------------------------------------
# 5. 官职轮转政体的主题换词
# ---------------------------------------------------------------------------
THEME_LABELS = {"起家发迹": "受任迁转", "失位让土": "卸任调转"}
# 板块要求里的同义换词 (天朝制/行政制/选贤/草原行政)
REQ_SWAPS = (("登位与失土", "受任与卸任"), ("登位", "受任"),
             ("失土", "卸任"), ("让土", "去职"))

# ---------------------------------------------------------------------------
# 6. 请求包裹模板 (具名槽位)
# ---------------------------------------------------------------------------
PROMPTS = {
    "system_head": "你是史官, 撰写传记。\n\n{rule_block}",
    "intro_system": (
        "你是史官, 为一位乱世人物修传。\n\n{rule_block}\n\n"
        "撰写传记「总纲」: 概括此人的一生大势, 预告以下各篇文章, "
        "点明其家族与身份。总纲正文控制在400–600字, 以「太史公曰」作结。"
    ),
    "intro_user": (
        "{shared}\n\n{theme}本传共{n_articles}篇, 篇目预告:\n{preview}\n\n"
        "输出格式:\n# 《{name}传》\n"
        "家族：{house}｜人物：{name}｜{span_cn}\n\n"
        "总纲正文…（一段至两段）\n\n请据此撰写总纲。"
    ),
    "preview_fallback": (
        "一、《本纪·{name}》——人物生平\n"
        "二、《列传·好友》——最亲近同僚的一生\n"
        "三、《列传·仇人》——一生劲敌的传记\n"
        "四、《家室列传》——妻室子女的门庭画卷\n"
        "五、《朝局风云录》——朝局官制沉浮"
    ),
    "subject_note": (
        "本篇传主为{subject}。全篇以{subject}为唯一叙述中心；"
        "主角{protagonist}的事迹仅在{subject}与主角交游或结仇的场合出现，"
        "传主生平以本篇资料为准。\n\n"
    ),
    "custom_start_note": (
        "开篇以「起于何时何地、如何发迹」为纲书写其出身，"
        "从其事业之始依次写来；配偶与子女在婚配、家室诸事处出场。\n\n"
    ),
    "lead_user": (
        "{shared}\n\n{theme}【总纲】\n{intro}\n\n"
        "{custom_note}{subject_note}相关事实:\n{facts}\n\n{events}"
        "本篇文章标题已定为《{title}》。\n\n"
        "这是文章的开篇板块《{sec_title}》。要求: {sec_req}\n\n"
        "篇幅要求: 开篇板块正文800–1200字, 立起人物与场景。\n\n"
        "输出格式: 直接输出正文, 正文使用 Markdown, "
        "分2~4个自然段, 段与段之间以空行分隔; 板块标题行由组装侧统一添加。"
    ),
    "mid_user": (
        "{shared}\n\n{theme}{subject_note}"
        "相关事实:\n{facts}\n\n{events}"
        "本篇文章标题已定为《{title}》。\n\n"
        "请撰写板块《{sec_title}》。要求: {sec_req}\n\n"
        "篇幅要求: 板块正文1200–1800字。\n\n"
        "本文开篇板块《{lead_title}》内容(以下为开篇摘要):\n{lead_digest}\n\n"
        "承接开篇所立人物与场景，以本篇相关事实为素材推进新事件与新细节，"
        "撰写板块《{sec_title}》。\n\n"
        "输出格式: 直接输出正文, 正文使用 Markdown。"
    ),
    "theme_note": (
        "{label}戏剧主题: {names}。"
        "各篇正文围绕这些主题取材，主题相关的事件写出戏剧张力，"
        "把每个主题写成具体的场景。\n\n"
    ),
}

# ---------------------------------------------------------------------------
# 7. 事实层措辞 (facts.py 取用)
# ---------------------------------------------------------------------------
FACT_WORDING = {
    # 记忆句/统计/合并动词已在上文以顶层表给出 (MEMORY_TEMPLATES 等),
    # 此处只放零散短语模板。
    # 刺客列传开篇点名句 (v30 问题8: 篇内只点一次全称谓)
    "assassin_lead": "刀下之魂共{n}人，皆死于{killer}之手。",
    # 入狱时长量词
    "prison_same_day": "当日",
    "prison_days": "{n}日",
    "prison_months": "{n}个月",
    "prison_years": "{y}年",
    "prison_years_months": "{y}年{m}个月",
    "prison_released": "，{span}后获释",
    "prison_release_on": "，{date}获释",
    "prison_jailed": "{jailer}囚禁{victim}",
    "prison_held": "{victim}被囚",
    # v31 (问题5): 牵制句 — 强牵制与普通牵制分档 (游戏 [strong_hook] / [hook] 同义);
    # {name} 由 facts 传引号形态 (「干了我老婆」), 本地化查不到时为空串;
    # {since} 为「（自X年见载）」或到期日, 对象只有一个时逐条写, 同类多条归并一行。
    "hook_held_strong": "{actor}握有对{target}的强牵制{name}{since}。",
    "hook_held_weak": "{actor}握有对{target}的牵制{name}{since}。",
    "hook_over_actor_strong": "{holder}握有对{actor}的强牵制{name}{since}。",
    "hook_over_actor_weak": "{holder}握有对{actor}的牵制{name}{since}。",
    "hook_group": "{actor}握有对{names}的{strength}牵制{name}（共{n}人）。",
    "hook_strong_word": "强",
    "hook_since": "（自{year}见载）",
    "hook_expires": "（{date}届满）",
    # v31 (问题2): 配偶同月「同房＋相恋」并作一行
    "affair_pair_spouse": "{y}年{m}月，{a}与{b}夫妻情笃。",
    # v31 (问题4): 妻室情事脉络 — 逐情人一句的关系弧用词 (弧内已点明是「与公主」,
    # 各段不再重复对象名)
    "affair_entry": "{date}私通",
    "affair_lovers": "{date}相恋",
    "affair_soulmates": "{date}结为灵魂伴侣",
    "affair_broke_up": "{date}分手",
    "affair_lover_died": "{date}去世",
    "affair_repeat": "其后{years}屡续私通",
    "affair_joined_court": "自{date}在主角廷中",
    "court_knight": "{actor}廷中骑士",
    "court_member": "{actor}廷臣",
}

# ---------------------------------------------------------------------------
# 8. 事实层措辞表 (v30 问题11 自 facts.py 搬入)
# ---------------------------------------------------------------------------
# 与「字」直接相关的死因/头衔/处决用词集中在此; facts.py 以别名引用
# (调用点不变)。游戏键→词的**查表**仍留在 facts/localization (数据映射)。

DEATH_REASON_ZH = {
    "death_execution": "处决", "death_murder": "谋杀", "death_duel": "决斗",
    "death_accident": "意外", "death_stress": "忧惧而亡", "death_wounds": "伤重不治",
    "death_punishment": "刑罚", "death_poison": "毒杀", "death_snake": "蛇噬",
    "death_dungeon": "囚毙", "death_fight": "斗殴", "death_old_age": "寿终",
    "death_natural_causes": "寿终", "death_heart_attack": "心疾",
    "death_broken_bones": "骨碎", "death_drinking_passive": "酗酒",
    "death_disappearance": "失踪而亡", "death_plotting": "密谋致死",
    "death_battle": "战死", "death_imprisonment": "囚毙",
    "death_bubonic_plague": "黑死病", "death_physique_bad_2": "体弱不支",
}


# v11: 游戏 UI 腔/坏文本死因 → 传记雅化 (优先于本地化值, 本地化文案是游戏内
# 通知腔, 如 blind = 「因绊倒坠落而失去的生命」, 直接进传记会读起来像抄游戏)。
# v16: 病弱/疾病类死因的本地化是 [GetTrait(...)] 模板 (查不出中文), 原样进
# 传记会退化成千篇一律的「去世」, 一并雅化为自然短句。
FLAVOR_DEATH_ZH = {
    "blind": "因绊倒坠落而亡",
    "death_fall": "因坠落而亡",
    "death_wounded_1": "伤重不治",
    "death_wounded_2": "伤重不治",
    "death_wounded_3": "伤重不治",
    "death_maimed": "重伤不治",
    "death_head_ripped_off": "身首异处",
    "death_apoplexy": "中风而亡",
    "death_drinking_passive": "酗酒而亡",
    # 成功而未败露的谋杀: 游戏显示「神秘死亡」; v16 起点破为谋杀, 用
    # 「被…秘密谋杀」与明面上败露的「被…谋杀」区分 (施事由 _death_clause 嵌入)
    "death_mysterious": "被秘密谋杀",
    # 病弱/疾病 (本地化为模板或缺失, 原会退化成「去世」)
    "death_depressed": "忧郁而亡",
    "death_ill": "染疾而亡",
    "death_consumption": "染肺痨而亡",
    "death_smallpox": "染天花而亡",
    "death_measles": "染麻疹而亡",
    "death_cancer": "染恶疾而亡",
    "death_sickly": "体弱而亡",
    "death_typhus": "染斑疹伤寒而亡",
    "death_pneumonic": "染肺疾而亡",
    "death_incapable": "瘫痪而亡",
    "death_lunatic": "疯癫而亡",
    "death_leper": "染麻风而亡",
    "death_dysentery": "染痢疾而亡",
    "death_camp_fever": "染疫而亡",
    "death_choked": "窒息而亡",
    "death_great_pox": "染花柳而亡",
    "death_malnourishment": "饥馁而亡",
    "death_starved": "饿死",
    "death_weak": "衰竭而亡",
    "death_gout_ridden": "痛风而亡",
    "death_bubonic_plague": "染黑死病而亡",
    "death_dungeon_passive": "囚毙",
    "death_physique_bad_1": "体弱不支",
    "death_physique_bad_2": "体弱不支",
    "death_physique_bad_3": "体弱不支",
    # 游戏 UI 长句 → 自然短句
    "death_broken_bones": "摔折筋骨而亡",
    "death_stress": "忧惧而亡",
    "death_punishment": "处决",
    "death_eradicated": "连同全族被处决",
    "death_hunted_by_wild_beast": "为野兽所噬而亡",
}


# v28: 头衔得失动词 — 按 memory vars.reason (游戏给的缘由) 出词。
# 旧口径一律「登位，得X」/「让出X」, 使天朝制/行政制的**官职任命轮转**
# (reason=appointment_succession / stepped_down) 被读成「被人打败、又夺人领地」
# (陆氏: 869 受任阶州、872 卸任阶州、875 受任商州 被写成 登位/让出)。
# 政体无关: 封建的承袭/受封/攻取、行政制的受任/调任 一表覆盖; 未知 reason
# 回退旧词 (登位/让出), 行为与旧版一致。
TITLE_GAIN_VERBS = {
    "created": "受封",                    # 起家/新封 (含世族受封家业)
    "appointment": "受任",
    "appointment_succession": "受任",
    "inheritance": "承袭",
    "granted": "受封",
    "revoked": "夺得",
    "usurped": "篡得",
    "conquest": "攻取",
    "conquest_claim": "攻取",
    "conquest_populist": "攻取",
    "conquest_holy_war": "攻取",
    "migration": "迁得",
    "swear_fealty": "归附得",
    "faction_demand": "迫得",
    "independency": "自立",
    "abdication": "受禅",
    "leased_out": "租得",
    "negotiated": "议得",
    "stepped_down": "接任",
    "destroyed": "重建",
}


TITLE_LOSS_VERBS = {
    "stepped_down": "卸任",
    "appointment": "调任",
    "appointment_succession": "调任",
    "revoked": "被褫夺",
    "usurped": "被篡",
    "conquest": "失守",
    "conquest_claim": "失守",
    "conquest_populist": "失守",
    "conquest_holy_war": "失守",
    "granted": "转授他人",
    "inheritance": "交出",
    "migration": "迁离",
    "abdication": "退位",
    "faction_demand": "让出",
    "swear_fealty": "归附",
    "destroyed": "毁弃",
}


# 记忆类型 → 中文 (模板: {name}=记忆拥有者, {other}=参与者, {title}=头衔)
MEMORY_TEMPLATES = {
    "became_rivals": "{name}与{other}结仇。",
    "became_grudge": "{name}与{other}结怨。",
    "became_nemesis": "{name}与{other}结为死敌。",
    "stopped_being_rivals": "{name}与{other}化解仇怨。",
    "rival_died": "{name}的仇人{other}去世。",
    "friend_died": "{name}的友人{other}去世。",
    "relative_died": "{name}的亲属{other}去世。",
    "spouse_died": "{name}丧偶，{other}去世。",
    "married": "{name}与{other}成婚。",
    "broke_up_lovers": "{name}与{other}分手。",
    "became_lovers": "{name}与{other}相恋。",
    "had_sex": "{name}与{other}有私情。",
    # v31 (问题2): 配偶之间的床笫之事不写作「私通」——婚姻之内, 本无非分之义
    # (旧文本把主角与公主的夫妻之实写成「私通四次」, 太史公曰亦随之失真)。
    "had_sex_spouse": "{name}与{other}同房。",
    "became_friends": "{name}与{other}结为好友。",
    "became_soulmates": "{name}与{other}结为灵魂伴侣。",
    "became_blood_brother": "{name}与{other}结为血盟兄弟。",
    "imprisoned_other": "{name}囚禁{other}。",
    "imprisoned": "{name}被囚。",
    "released_from_prison_memory": "{name}获释。",
    "lost_title_memory": "{name}让出{title}。",
    "ascended_throne_memory": "{name}登位，得{title}。",
    "child_born": "{name}添子{other}。",
    "first_born": "{name}得长子{other}。",
    "child_premature": "{name}幼子夭折。",
    "child_stillborn": "{name}婴儿夭折。",
    "twins_born": "{name}得孪生子。",
    # v26: 出生按孩子性别分版 (女儿此前一律被写成「添子」— 田所2 睦/立希)
    "child_born_female": "{name}添女{other}。",
    "first_born_female": "{name}得长女{other}。",
    "twins_born_female": "{name}得孪生女。",
    "twins_born_mixed": "{name}得龙凤胎。",
    "passed_child_exam_memory": "{name}童子试及第。",
    "failed_child_exam_memory": "{name}童子试落第。",
    "passed_provincial_exam_memory": "{name}乡试及第。",
    "failed_provincial_exam_memory": "{name}乡试落第。",
    "passed_metropolitan_exam_memory": "{name}会试及第。",
    "passed_palace_exam_memory": "{name}殿试及第。",
    "tortured_memory": "{name}受刑。",
    "torturer_memory": "{name}施刑于人。",
    # v30: 战斗胜负改用史笔中性词 (修复方案_菲利普4.md 问题3) — 原「打了胜仗/吃了败仗」
    # 是游戏 UI 口语, 模型逐字照抄进正文 (「他吃了败仗」「佛罗西吃了败仗」);
    # 「主动开战/被迫应战」保留 (用户决策)。
    "battle_won_memory": "{name}取胜。",
    "battle_lost_memory": "{name}失利。",
    "offensive_war": "{name}主动开战。",
    "defensive_war": "{name}被迫应战。",
    "war_won": "{name}赢得战争。",
    "war_lost": "{name}战败。",
    "joined_allys_war": "{name}助盟友作战。",
    "witnessed_death_battle": "{name}目击战死。",
    "became_incapable_due_to_battle_concussion": "{name}战伤致残。",
    "completed_hajj_memory": "{name}朝觐归来。",
    "hostage_created_hostage": "{name}为人质。",
    "hostage_created_warden": "{name}看守人质。",
    "hostage_created_home_court": "{name}交出人质。",
    "picked_serenity_aspect_memory": "{name}皈依安详之道。",
    "picked_creation_aspect_memory": "{name}皈依创世之道。",
    "ward_education_completed": "{name}学业有成。",
    "childhood_education_guardian": "{name}受业于{other}。",
    "childhood_education_no_guardian": "{name}独自求学。",
    "completed_rites_of_passage": "{name}完成成人礼。",
    "completed_adult_education": "{name}完成深造。",
    "became_acclaimed": "{name}获拥戴。",
    "witnessed_a_coronation_memory": "{name}见证加冕。",
    "grand_wedding_completed_guest": "{name}出席大婚。",
    "ignored_assault_memory": "{name}受辱未报。",
    # v15: 成功谋杀 (主角视角, 神秘死亡味由受害者死亡记录句负责)
    "successful_murder": "{name}谋杀{other}。",
}


# v28: 隐事 (secrets) 主题短语 — 存档 secrets.secrets 的 type → 中文短语。
# 类型名本地化 (L.loc(table, type)) 只是名词 (考试舞弊者/巫师/不信者), 提示词里
# 需要可叙事的短语, 故按类型给模板; 未收录类型回退游戏本地化类型名。
SECRET_TOPICS = {
    "secret_murder": "谋害{target}",
    "secret_murder_attempt": "行刺{target}未遂",
    "secret_exam_cheater": "科举舞弊",
    "secret_lover": "与{target}私通",
    "secret_deviant": "性情怪僻",
    "secret_non_believer": "不信神明",
    "secret_crypto_religionist": "暗奉异教",
    "secret_witch": "暗行巫术",
    "secret_embezzler": "侵吞库银",
    "secret_siphoned_treasury": "挪用国库",
    # v31 (问题7): 血统类隐事指名所涉子女 — 旧文案「血统有争（涉及X）」是名词
    # 括注同位语, 且与「见载年/知情者」的括注叠在一起, 读来含混。
    "secret_unmarried_illegitimate_child": "所出{target}血脉存疑",
    "secret_disputed_heritage": "所生{target}血统有争",
    "secret_incest": "乱伦",
    "secret_homosexual": "断袖",
    "secret_cannibal": "食人",
    "secret_coup_plotter": "谋逆",
    "secret_adultery": "通奸",
}


# 模板需要对象、而存档未给 target 时的简写
SECRET_TOPICS_NO_TARGET = {
    "secret_murder": "谋害人命",
    "secret_murder_attempt": "行刺未遂",
    "secret_lover": "与人私通",
}


# v16: 动作型死因 → 施事句式 (原始 reason key → 动词)。有凶手/行刑者/对手
# 记录时, 把施事者直接嵌进句内 (被XXX谋杀 / 被XXX处决 / 与XXX决斗而亡),
# 不再另起「凶手为…」尾巴 — 更短, 也更像自然语言; 战场/意外/病亡的击杀者
# 不是「凶手」, 一律不点名。谋杀分两档: death_murder 是败露的谋杀 (被XXX
# 谋杀), death_mysterious 是未败露的谋杀 (被XXX秘密谋杀)。
DEATH_KILLER_VERB = {  # 凶手: 被{凶手}{动词}
    "death_murder": "谋杀",
    "death_murder_known": "谋杀",
    "death_mysterious": "秘密谋杀",
    "death_assassination": "暗杀",
    "death_poison": "毒杀",
    "death_plotting": "谋害",
    "death_court_intrigue": "谋害",
    "death_strangled_with_own_intestines": "绞杀",
    "death_smothered_by_downy_robe": "闷杀",
    "death_skull_cracked_open": "打死",
    "death_beaten": "打死",
    "death_cloven_in_half": "劈杀",
    "death_heart_ripped_out": "剖心",
    "death_chopped_to_pieces": "砍成碎块",
    "death_viciously_dismembered": "碎尸",
    "death_ripped_apart_limb_by_limb": "分尸",
    "death_decapitated": "斩首",
    "death_ritually_hung": "缢杀",
    "death_sacrificed_to_gods": "献祭",
    "death_sacrificed_to_ancestor": "献祭",
    "death_burned": "烧死",
    "death_burned_by_mob": "烧死",
}


DEATH_EXECUTOR_VERB = {  # 行刑者: 被{行刑者}{动词}
    "death_execution": "处决",
    "death_punishment": "处决",
    "death_hostage_execution": "处决",
    "death_execution_blood_eagle": "处决",
    "death_crucified": "钉上十字架",
    "death_crucified_by_mob": "钉上十字架",
    "death_burned_witch": "烧死在火刑柱上",
}


DEATH_OPPONENT_VERB = {  # 对手: 与{对手}{动词}而亡
    "death_duel": "决斗",
    "death_fight": "斗殴",
    "death_fight_killer": "斗殴",
    "death_contest_duel_accident": "决斗",
    "death_contest_wrestling_accident": "角力",
}


DEATH_AGENT_TAIL = {  # 死因自带惨状/情状, 施事者用「凶手/行刑者为…」点出
    "death_head_ripped_off": "凶手",   # 身首异处，凶手为XXX
    "death_eradicated": "行刑者",      # 连同全族被处决，行刑者为XXX
}


# v22: 处决方式 (用户需求 2026-09-02) — 存档不记录行刑者实际选择的方式,
# 受害死因键恒为 death_execution; 依 execute_prisoner_interaction 的
# send_option 可用条件 (见游戏 common/character_interactions/00_prison_interactions.txt),
# 用传记所用熔件/缓存的行刑者状态近似判定可用方式, 再按 (行刑者, 受害者,
# 死亡日期) 稳定伪随机取一 — 不同处决有变化, 同一处决重跑不漂移。
# (顺序即游戏界面顺序; 措辞按 EXECUTION_* 本地化与 death_* 死因雅化。)
EXECUTION_OPTIONS = (
    ("beheaded",   "斩首"),                     # EXECUTION_BEHEADED 砍头
    ("devour",     "砍头后吃掉"),               # EXECUTION_DEVOUR 砍头……然后吃掉!
    ("burned",     "烧死"),                     # EXECUTION_BURNED 烧死在火刑柱上
    ("sacrifice",  "献祭给神灵"),               # EXECUTION_SACRIFICE 献祭
    ("kennel",     "处以犬决"),                 # EXECUTION_KENNEL 犬决
    ("provisions", "做成神秘的肉充作口粮"),     # EXECUTION_PROVISIONS 做成神秘的肉
)


EXECUTION_ORDER = {k: i for i, (k, _v) in enumerate(EXECUTION_OPTIONS)}


# v15: 概览统计标签 (记忆类型 → 中文标签; death 记录按模块另表)。
# 只统计有戏剧意义的类型, 供【概览】块程序直算「本十年结怨9次、谋杀5次…」。
STATS_LABEL = {
    "became_rivals": "结仇", "became_grudge": "结怨", "became_nemesis": "结为死敌",
    "child_born": "添丁", "first_born": "添丁", "twins_born": "添丁",
    "child_premature": "夭折", "child_stillborn": "夭折",
    "successful_murder": "谋杀",
    "had_sex": "私通", "became_lovers": "私通",
    # v31 (问题2): 配偶之间的情事另立一档 — 概览不再把夫妻之实计入「私通」
    "had_sex_spouse": "夫妻之情", "became_lovers_spouse": "夫妻之情",
    "relative_died": "丧亲", "spouse_died": "丧偶", "friend_died": "丧友",
    "rival_died": "仇人死亡",
    "married": "成婚", "broke_up_lovers": "分手",
    "imprisoned": "被囚", "imprisoned_other": "囚禁他人",
    "offensive_war": "开战", "defensive_war": "应战",
    "war_won": "获胜", "war_lost": "战败",
    "battle_won_memory": "取胜", "battle_lost_memory": "失利",
    "faith_changed": "改信",
}


DEATH_STAT_LABEL = {
    "谋害人命": "谋杀", "丧亲之恸": "丧亲", "丧偶之痛": "丧偶",
    "丧友之恸": "丧友", "仇人死亡": "仇人死亡",
}

# v31 (问题1): 特质类别词 — 游戏 common/traits 的 `category` → 中文。
# 空键 = 游戏未给 category 的先天特质 (beauty_*/intellect_*/physique_*/dwarf…)。
TRAIT_GROUP_WORDS = {
    "personality": "性情", "education": "才具", "lifestyle": "阅历",
    "commander": "将略", "fame": "名声", "health": "体况",
    "childhood": "幼性", "court_type": "宫廷", "": "禀赋",
}


MERGE_VERB = {
    "witnessed_a_coronation_memory": "见证加冕。",
    "grand_wedding_completed_guest": "出席大婚。",
    "imprisoned": "被囚。",
}
