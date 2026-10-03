# -*- coding: utf-8 -*-
"""Model-facing prompt text for the biography generator.

Single source of truth for everything the model reads: the writing profiles,
the system rule block, the article board titles and their requirements, the
request wrappers, and the fact-layer wording tables used by facts.py.

Pure data plus a few pure functions: this module imports nothing from the
project, and biography.py / facts.py depend on it.

Layout
------
1. STYLE_PROFILES   prose profile per biography style
2. RULES            writing rules (system rule block)
3. SECTION_TITLES   board titles of every article
4. SECTION_REQ      per-board material requirements
5. THEME_LABELS     module wording for office-rotation governments
6. PROMPTS          request wrappers with named slots
7. FACT_WORDING     fact-layer wording (consumed by facts.py)

Two standing rules for new prompt text:
  (1) state what to do, and keep negative phrasing out
      (see .agents/skills/no-negative-prompts);
  (2) keep every deterministic concern in code and leave only creative writing
      to the prompt (prompt-last).
"""

# ---------------------------------------------------------------------------
# 1. Prose profile
# ---------------------------------------------------------------------------
# Both profiles ask for modern standard Chinese; they differ only in the
# biographical tradition the prose follows.
STYLE_PROFILES = {
    "east": {
        "jizhuanti": (
            "「传记笔法」：以人物为中心，按时间顺序讲述他的一生，"
            "客观叙述与夹叙夹议并行，善用细节、对话与场景描写；"
            "全文使用现代汉语书面语写作。"
        ),
    },
    "west": {
        "jizhuanti": (
            "「传记笔法」：以人物一生为主线，穿插轶事、对话与性格细节，"
            "边叙述边作评议，兼写品行与命运的起落；"
            "全文使用现代汉语书面语写作。"
        ),
    },
}
DEFAULT_STYLE = "east"

# ---------------------------------------------------------------------------
# 2. Writing rules (system rule block)
# ---------------------------------------------------------------------------
RULES = {
    # Deterministic concerns stay in code: names, titles, dates and numbers are
    # rendered by the facts layer, and anything the program can enforce is kept
    # out of the prompt.
    "nonfiction": (
        "「写作依据」：人物、家族、官职、事件、日期与数字，一律照本篇给出的写法书写；"
        "由本篇人事生发的心理、对话与场景要写足，"
        "每一句都落到具体的人、时间、地点与事件上。"
    ),
    "narrative_focus": (
        "「行文焦点」：每一句都落在具体的人、时间、地点与事件上，"
        "按事情的先后依次推进；叙述连贯，笔墨简洁有力，与所写人物的处境相称。"
    ),
    "secret": (
        "「秘密写法」：写出该秘密的知情人、参与者和发生的时间。"
    ),
    "narrative": (
        "「一篇一题」：每篇先立一个主题与一个决定性时刻，"
        "整篇内容都围绕这个主题推进。"
    ),
}

# Order of the rules sent in the system message.
_RULE_ORDER = ("nonfiction", "narrative", "narrative_focus")
# Boards that carry secret facts and therefore also receive the secret rule.
SECRET_BOARDS = ("secrets",)


def rule_block(style=DEFAULT_STYLE, secret=False):
    """Return the system rule block text for one prose style."""
    prof = STYLE_PROFILES.get(style) or STYLE_PROFILES[DEFAULT_STYLE]
    out = "\n".join([prof["jizhuanti"]] + [RULES[k] for k in _RULE_ORDER])
    if secret:
        out += "\n" + RULES["secret"]
    return out


# ---------------------------------------------------------------------------
# 3/4. Board titles and per-board requirements
# ---------------------------------------------------------------------------
SECTION_TITLES = {
    "benji":   {"lead": "开篇·家世与出身", "mid": "纪事·一生大事", "tail": None},
    "friend":  {"lead": "开篇·家世与交游", "mid": "纪事·一生际遇", "tail": None},
    "enemy":   {"lead": "开篇·仇家身世",   "mid": "纪事·一生行迹", "tail": None},
    "jiashi":  {"lead": "开篇·结缡与离异", "mid": "纪事·门庭恩怨", "tail": None},
    "chaoju":  {"lead": "开篇·王朝历代",
                "mid1": "纪事·王朝历代·上",
                "mid2": "纪事·王朝历代·中",
                "mid3": "纪事·王朝历代·下",
                "mid4": "纪事·王朝历代·续篇",
                "family_lead": "开篇·家族先世",
                "family_mid": "纪事·家族历代",
                "tail": None},
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
    "liyi":    {"lead": "开篇·所奉礼仪", "mid": "纪事·礼仪与教义沿革",
                "tail": "纪事·枢机团与教宗选举"},
}

# Household article wording follows the material actually available: with no
# spouse and no children, asking for marriage, divorce and childbirth pushes the
# model to invent a family. The program picks the variant (see
# biography._jiashi_variant) and every variant is phrased positively.
JIASHI_VARIANTS = {
    # Spouse or former spouse present.
    "spouse": {
        "lead_title": "开篇·结缡与离异",
        "mid_title": "纪事·门庭恩怨",
        "theme": "妻室子女的家庭画卷",
        "focus": "写家中的内情：结婚、感情脉络、子女来历与血脉之争",
        "lead": "写主角的婚配始末：结婚、离异、前妻去世、再婚，描绘出家庭的画卷；"
                "妻族的门第（妻子的父兄等地位显赫的亲戚）一并展开。",
        "mid": "写家中的恩怨：前妻与仇家的情事、其他妇人的怨气，以及妻妾的聚散离合 —— "
               "结婚、离异、生子、夭折的日期与情境。本板块只写本组这一房夫妻"
               "与其家门之事；成年子女的受任、婚配与子嗣归《诸子行迹》各节。",
        "kid": "写本节所写子女的成年行迹，逐人一段：何时受任何职、为谁所任或承谁之位、"
               "与何人成婚、其配偶门第、已育子女，以及其与父母兄弟的往来。"
               "承位一句已经写明去向时，照写其前任与前任的结局 —— 这个位置从谁手里"
               "辗转而来、几任前任怎样接连死在任上。",
    },
    # Concubines only, no spouse.
    "spouse_plain": {
        "lead_title": "开篇·结缡与离异",
        "mid_title": "纪事·门庭恩怨",
        "theme": "妻室子女的家庭画卷",
        "focus": "写家中的内情：结婚、感情脉络、子女来历与行迹",
        "lead": "写主角的婚配始末：结婚、离异、前妻去世、再婚，描绘出家庭的画卷；"
                "妻族的门第（妻子的父兄等地位显赫的亲戚）一并展开。",
        "mid": "写家中的恩怨：前妻与仇家的情事、其他妇人的怨气，以及妻妾的聚散离合 —— "
               "结婚、离异、生子、夭折的日期与情境。本板块只写本组这一房夫妻"
               "与其家门之事；成年子女的受任、婚配与子嗣归《诸子行迹》各节。",
        "kid": "写本节所写子女的成年行迹，逐人一段：何时受任何职、为谁所任或承谁之位、"
               "与何人成婚、其配偶门第、已育子女，以及其与父母兄弟的往来。"
               "承位一句已经写明去向时，照写其前任与前任的结局 —— 这个位置从谁手里"
               "辗转而来、几任前任怎样接连死在任上。",
    },
    # Concubines only, no spouse.
    "concubine": {
        "lead_title": "开篇·纳妾与门庭",
        "mid_title": "纪事·门庭人事",
        "theme": "家中的诸人与人事",
        "focus": "写家中的内情：纳妾始末、妾室的门第与原配、亲戚与属下的聚散",
        "lead": "写主角家中的收纳始末：哪一年纳了何人、其人门第与原有婚配、"
                "进门的缘由与经过；没有正妻时，以家中诸事与亲戚往来描绘出家庭的画卷。",
        "mid": "写家中的人事：妾室的来历与原配的去留、亲戚与属下的聚散、"
               "家中的诸般事情。本篇写出各人的日期与情境，依据本篇给出的人事与年代写出。",
    },
    # No marriage material at all.
    "none": {
        "lead_title": "开篇·门庭与家计",
        "mid_title": "纪事·门中人事",
        "theme": "家庭与生计",
        "focus": "写家庭与生计：父母同胞、亲戚与属下、家业与生计的变动",
        "lead": "写主角的家庭与生计：父母同胞、亲戚与属下、家业与生计，"
                "依据本篇给出的人事与年代写出，表现他日常生活的底色。",
        "mid": "写家中的人事：亲戚往来、属下聚散、家业与生计的变动，"
               "依据本篇给出的人事与年代写出。",
    },
}

# Per-board requirements: each line states what the board must write.
SECTION_REQ = {
    "benji": {
        "lead": "从家世和出身写起：生于哪一年、家族来历、文化与宗教、性情特点，为人物一生立下基调。",
        "mid": "按时间顺序叙述一生的大事：掌管领地、经营营地或世族庄园、接受任命、让出领地、结仇、家中变故、再婚等，依据本篇给出的年代与人事。本篇写出主角即位与失去领地的时刻、战争与入狱的转折，把每个关键日期写成戏剧性的场景。",
        "tail": None,
    },
    "friend": {
        "lead": "写传主与主角的交游渊源：两人怎样相识、同在哪个朝代与地方，以及传主的家世与出身。",
        "mid": "叙述传主一生的经历：婚姻、被囚、失去领地、复起、执政、交友等。本篇写出传主与主角结友的时刻与缘由，以及两人交游中的聚散。",
        "tail": None,
    },
    "enemy": {
        "lead": "写仇家的身世与结仇的原因：传主是谁，为什么与主角结仇。",
        "mid": "叙述仇家一生的行迹：执政、婚姻、感情、结仇、私情等，以客观叙述写出。本篇写出结仇的日期与起因，以及仇怨在何时何地爆发。",
        "tail": None,
    },
    "jiashi": {
        # Same text as JIASHI_VARIANTS['spouse']; biography._jiashi_variant
        # switches to another variant when the material is thin.
        "lead": "写主角的婚配始末：结婚、离异、前妻去世、再婚，描绘出家庭的画卷；妻族的门第（妻子的父兄等地位显赫的亲戚）一并展开。",
        "mid": "写家中的恩怨：前妻与仇家的情事、其他妇人的怨气，以及妻妾的聚散离合 —— 结婚、离异、生子、夭折的日期与情境。本板块只写本组这一房夫妻与其家门之事；成年子女的受任、婚配与子嗣归《诸子行迹》各节。",
        "kid": "写本节所写子女的成年行迹，逐人一段：何时受任何职、为谁所任或承谁之位、与何人成婚、其配偶门第、已育子女，以及其与父母兄弟的往来。承位一句已经写明去向时，照写其前任与前任的结局 —— 这个位置从谁手里辗转而来、几任前任怎样接连死在任上。",
        "tail": None,
    },
    "chaoju": {
        # Material is one line per ruler plus the current dynasty's wars and
        # offices; each mid section covers one slice of dynasties, and the
        # program states that slice's range in the requirement line
        # (biography._chrono_mid_req).
        "lead": "写王朝总说：逐朝写出起止与国号沿革、空位期的起止，并写出本朝疆域所及、治所、所辖与主角在本朝的任期。素材给出的年代、国号、人名与缘由请照原样写出。",
        "mid": "写各朝历代：素材已按「一人一行」给出该节每位统治者的生卒、继位日、继位缘由、在位年数与失位缘由，请逐人写出，继位缘由照素材写清。本节的战事行写出该朝兴兵、应战与胜负的经过，人名、年月与地名照素材给出的写法写出。本节只写素材列出的这几人、这几事，写到本节末位统治者在位终了为止。",
        "mid_last": "写本朝历代：素材已按「一人一行」给出本朝每位统治者的生卒、继位日、继位缘由、在位年数与失位缘由，逐人写出。本朝疆域、治所、所辖、战事与主角在本朝的任期一并写出，收束于传主在位的末年。本节只写素材列出的这几人、这几事（前朝已在其余各节写完）。",
        "family_lead": "写家族先世总说：先世起于何时何地、哪几位曾执掌一方，以及传主这一支的辈分次序。素材给出的年代、人名与头衔照原样写出。",
        "family_mid": "写家族历代：素材已按「一人一行」给出先世每位统治者的继位日、取得头衔与头衔名，按辈分由老到新逐人写出，写到传主本人为止。先世各人的事迹依据素材写出。",
        "tail": None,
    },
    "assassins": {
        "lead": "写被主角杀死的那些人的群像：各人身份、与主角的恩怨由来、死时的情形，以客观叙述写出。死法按本篇给出的具体手法写出。",
        # Single-victim case: a group portrait has nothing to stand on.
        "lead_one": "写被主角杀死的人的小传：其身份、与主角的恩怨由来、死时的情形，以客观叙述写出。死法按本篇给出的具体手法写出。",
        "mid": "按死亡先后为序，为每名死者立一小传：生平行迹、与主角的交集、死因。本篇写出死者生前的家世亲缘与婚恋经历，再写其死时的情形，死法按本篇给出的具体手法写出。",
        "mid1": "按死亡先后为序，为这一时期（最早所诛）的每名死者立一小传：生平行迹、与主角的交集、死因。本篇写出死者生前的家世亲缘与婚恋经历，再写其死时的情形，死法按本篇给出的具体手法写出。",
        "mid2": "按死亡先后为序，为这一时期（中期所诛）的每名死者立一小传：生平行迹、与主角的交集、死因。本篇写出死者生前的家世亲缘与婚恋经历，再写其死时的情形，死法按本篇给出的具体手法写出。",
        "mid3": "按死亡先后为序，为这一时期（暮年所诛）的每名死者立一小传：生平行迹、与主角的交集、死因。本篇写出死者生前的家世亲缘与婚恋经历，再写其死时的情形，死法按本篇给出的具体手法写出。",
        "tail": None,
    },
    "youxia": {
        "lead": "写主角漂泊不定的游侠生涯：起于何地、如何成营、一路辗转，按行纪次序写出。",
        "mid": "按行纪次序叙述漂泊行迹：每至一地的时间、驻扎的地方、与当地势力的交集。",
        "tail": None,
    },
    "qizu": {
        "lead": "写主角妻族的门第：妻妾中皇室姻亲的身世（公主头衔或中华皇帝的女儿、姐妹），以及其父兄辈的显赫。",
        "mid": "写妻族与主角家室的牵连：姻亲的荣耀、门第的变化。",
        "tail": None,
    },
    "qunying": {
        "lead": "写朝堂要员的群像：主角为行政制官员，本篇展开同朝要员的名录与身份。",
        "mid": "依朝局动态叙述要员的起落：登位、结仇、入狱、战争等。",
        "tail": None,
    },
    "feuds": {
        "lead": "写与主角家族关系不和的各个家族：结怨的原因、恩怨始末、当前关系。恩怨之始按战争与领地的次序写出：宣战、胜负、领地易主、对方此后的处境；囚禁与俘虏写在对应战役的过程里。",
        "mid": "按事件的先后顺序叙述各家族的恩怨始末：联姻、囚禁、处决、宣战、反目等。本篇把每段恩怨的起点（宣战与夺地的日期与起因）写到收束，让恩怨链条从开战、战败、失地到对方处境完整可见。",
        "tail": None,
    },
    "artifacts": {
        "lead": "写主角持有的宝物：宝物名称、形制、稀有度。",
        "mid": "依流转史叙述每件宝物的来历与流转。",
        "tail": None,
    },
    "secrets": {
        "lead": "写主角身上的秘密：什么事、牵涉到谁、事情发生在哪一年、有谁知道。",
        "mid": "写家人与近臣的秘密、把柄的所属与流转：逐件交代谁藏着什么秘密、谁已经知情、此后的往来如何。本篇写出各处秘密的年份与知情者的身份。",
        "tail": None,
    },
    "liyi": {
        "lead": "写传主所受之礼：所奉礼仪的名目。"
                "核心教义逐条点名，宗教热情与灵性满足按档位词写出。",
        "mid": "写礼仪与教义的沿革、传主在教门中的作为：依据本篇给出的事实逐块写出，"
               "年月、缘由与涉及的人事照本篇给出的写法书写。",
        # Fallback wording only: biography._liyi_req builds the real requirement
        # per board from the blocks that are actually sent.
        "tail": "写本朝枢机在下届教宗选举中的形势：枢机团席次、本朝封臣入枢机者、"
                "现任教宗、下届推举的人选与票数、派别与奔走，"
                "皆照本篇给出的事实行写出。",
    },
}

# ---------------------------------------------------------------------------
# 5. Module wording for office-rotation governments
# ---------------------------------------------------------------------------
# Keys must match the module names in facts.py.
THEME_LABELS = {"起家发迹": "受任与升迁", "失位让土": "卸任与去职"}
# Same substitution applied inside board requirements.
REQ_SWAPS = (("即位与失去领地", "受任与卸任"), ("即位", "受任"),
             ("失去领地", "卸任"), ("让出领地", "去职"))

# ---------------------------------------------------------------------------
# 6. Request wrappers with named slots
# ---------------------------------------------------------------------------
PROMPTS = {
    "system_head": "你是一位传记作家，为人物撰写传记。\n\n{rule_block}",
    "intro_system": (
        "你是一位传记作家，为一位身处乱世的人物撰写传记。\n\n{rule_block}\n\n"
        "撰写传记的「总纲」：概括他一生的整体走势，预告以下各篇文章，"
        "点明他的家族与身份。总纲正文控制在400–600字，"
        "结尾用一段总评收束全篇。"
    ),
    "intro_user": (
        "{shared}\n\n{theme}本传共{n_articles}篇，篇目预告：\n{preview}\n\n"
        "输出格式：\n# 《{name}传》\n"
        "家族：{house}｜人物：{name}｜{span_cn}\n\n"
        "总纲正文…（一段至两段）\n\n请据此撰写总纲。"
    ),
    "preview_fallback": (
        "一、《本纪·{name}》——人物生平\n"
        "二、《列传·好友》——最亲近同僚的一生\n"
        "三、《列传·仇人》——一生劲敌的传记\n"
        "四、《家室列传》——妻室子女的家庭画卷\n"
        "五、《历代记》——王朝历代与本朝人事"
    ),
    "subject_note": (
        "【传主】{subject}\n"
        "本篇的传主是{subject}。全篇以{subject}为唯一的叙述中心；"
        "主角{protagonist}只在与{subject}交游或结仇的场合出现，"
        "传主的生平以本篇给出的人事为准。\n\n"
    ),
    "custom_start_note": (
        "开篇从「起于何时何地、怎样发迹」入手写他的出身，"
        "从他事业的开端依次写出；配偶与子女在婚配与家室诸事处出场。\n\n"
    ),
    "lead_user": (
        "{shared}\n\n{theme}{intro_block}"
        "{custom_note}{subject_note}相关事实：\n{facts}\n\n{events}"
        "本篇文章标题已定为《{title}》，本篇主题：{focus}。\n\n"
        "这是文章的开篇板块《{sec_title}》。要求：{sec_req}\n\n"
        "篇幅要求：开篇板块正文800–1200字，写出人物与场景。\n\n"
        "输出格式：直接输出正文，正文使用 Markdown，"
        "分2~4个自然段，段与段之间以空行分隔；板块标题行由组装侧统一添加。"
    ),
    "mid_user": (
        "{shared}\n\n{theme}{subject_note}"
        "相关事实：\n{facts}\n\n{events}"
        "本篇文章标题已定为《{title}》，本篇主题：{focus}。\n\n"
        "请撰写板块《{sec_title}》。要求：{sec_req}\n\n"
        "篇幅要求：板块正文1200–1800字。\n\n"
        "本文开篇板块《{lead_title}》的内容（以下为开篇摘要）：\n{lead_digest}\n\n"
        "承接开篇所写出的人物与场景，以本篇相关事实为素材推进新事件与新细节，"
        "撰写板块《{sec_title}》。\n\n"
        "输出格式：直接输出正文，正文使用 Markdown。"
    ),
    "theme_note": (
        "{label}的戏剧主题：{names}。"
        "各篇正文围绕这些主题取材，与主题相关的事件写出戏剧张力，"
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
    "prison_released_same_day": "，当日获释",
    # v60 (问题4): 未见释放时的收句 —— 旧措辞「，此后一直未见释放」把
    # 「本传数据窗口内在押」写成一句**无限期**断言 (崔佛 881.1.1 卒, 四名囚犯
    # 此后转归其妾埃尔梅辛达之手)。改以本档为界: {bound} 由 facts 给
    # (十年档给该篇截止日, 终传给「末档」)。
    # v34 (问题7): 程序把「此后如何」说全, 让模型有完整句子可依, 而非留一个
    # 待补的空位 (旧稿此处留白, 模型遂把囚期留白补成「获释」)。
    "prison_still_held": "，至{bound}仍在押",
    # v32 (马克龙问题1): 出狱方式二分的另一支 — 逃脱 (escaped_from_prison_memory)
    "prison_escaped": "，{span}后越狱逃脱",
    "prison_escape_on": "，{date}越狱脱身",
    "prison_escape_same_day": "，当日越狱脱身",
    "prison_jailed": "{jailer}囚禁{victim}",
    "prison_held": "{victim}被囚",
    # v63 (问题1, 用户 2026-09-24 拍板): 囚禁的**获取方式**只写有硬证的那几种。
    # 追加调研的结论是「破城俘虏」与「战败俘虏」在本档**不可区分**(三者共用裸
    # `imprison`, `melt["sieges"]` 只留在进行的攻城, 省份 occupant 只是当前状态),
    # 故判不出时仍走 `prison_jailed` 的裸「囚禁」——**不写方式**, 模型也就没有
    # 「在宴会上擒获」这类自造场景的落点了。
    "prison_captured_battle": "{jailer}于战阵俘获{victim}",
    "prison_captured_diarch": "{jailer}以摄政之权拘押{victim}",
    "prison_batch_seized": "{jailer}拘押{victim}",
    # v63 (问题1 第二轮): ① 未成年人被囚 ⇒ 排除战败俘获 (战败池只有败方主指挥官
    # 与骑士, 必为成年参战者; 正样本 9 处被俘主帅年龄 21–61 无未成年人)。
    # 措辞只写「拘押」＋当时年龄 —— 年龄本身即事实, 且与「妇孺同俘」的场景自然相合。
    "prison_note_age": "{victim}，时年{n}岁",
    # ② 正证劫掠: 监禁者的 `landed_data.last_raid` 与入狱日同日 (游戏写明他那天
    # 在劫掠) —— 这是唯一能确定性判出「劫掠掳人」的字段。
    "prison_raid_captured": "{jailer}劫掠中掳走{victim}",
    # v56 (§10-D): 相恋缘由的**程序兜底** (拿不到游戏 reason 键时) —— 双方同囚于
    # 同一监禁者、同为 house_arrest (软禁)、且关系起始日落在共同在押区间内。
    # 措辞只陈述**可判定的事实** (「同在X的软禁中」), 不冒用游戏 lover_prison
    # 的「地牢」文案。
    "lovers_same_prison": "{name}与{other}同在{jailer}的软禁中相恋",
    "lovers_same_prison_no_jailer": "{name}与{other}同在软禁中相恋",
    # v56 (问题2, 用户拍板案 A): 同日「入狱＋获释」且同日该被囚者的战争结束 ——
    # 这不是「抓了又放」, 而是**战末俘获**。v63 (问题1) 起该档改写为统一的
    # 战阵俘获措辞 (`prison_captured_battle`), 本键停用 (保留仅供旧断言引用)。
    "prison_war_end": "{jailer}战胜{victim}，俘之",
    # v42 (问题3): 阉割/致盲**必然与释放同日**（存档 21/21 例实证）——
    # 刑名不再另起一行, 而是充当出狱缘由并入囚禁句。{sp} = 「当日」或「14日后」。
    "prison_punish_castrated": "，{sp}遭阉割而获释",
    "prison_punish_blinded": "，{sp}遭剜目而获释",
    "prison_punish_beardless":
        "，{sp}其在成年前被{jailer}阉割，终身无须，因而获释",
    "prison_punish_generic": "，{sp}受刑而获释",
    # v42 (问题6): 囚期以**死亡**收口 —— 有死亡记录而无释放/越狱/狱史闭合者,
    # 旧稿一律写「此后一直未见释放」(诺兰 1088 那 10 人其实 6 个月后被杀)。
    "prison_died_executed": "，{sp}处决",
    "prison_died_in_prison": "，{sp}死于狱中",
    # 热修 (2026-09-24, 用户报告): 囚期以**吃掉**收口 —— Mod「食人赋能」把吃掉写成
    # `death_execution`, 遗骨 (`devour_bone_visual`, 见 `Facts._devour_bones`) 是唯一
    # 确证。旧稿收口只判「刑杀/狱死」, 于是同一个人在本篇里年表写「处决」、
    # 死者名录用 `EXECUTION_DEVOUR_BONE` 写「被其吃掉」, 自相矛盾。
    # 「其」= 句首点名的监禁者 (「X囚禁Y，6个月后被其吃掉」), 与名录同词。
    "prison_died_devoured": "，{sp}被其吃掉",
    # v31 (问题5): 牵制句 — 强牵制与普通牵制分档 (游戏 [strong_hook] / [hook] 同义);
    # {name} 由 facts 传引号形态 (「干了我老婆」), 本地化查不到时为空串;
    # {since} 为「（X年起）」或到期日, 对象只有一个时逐条写, 同类多条归并一行。
    "hook_held_strong": "{actor}握有对{target}的强牵制{name}{since}。",
    "hook_held_weak": "{actor}握有对{target}的牵制{name}{since}。",
    "hook_over_actor_strong": "{holder}握有对{actor}的强牵制{name}{since}。",
    "hook_over_actor_weak": "{holder}握有对{actor}的牵制{name}{since}。",
    # 归并行 (同类多对象/多持有者): 方向各自的句式, 名字取前三 + 总人数
    # v55 (问题2): 去括注 —— 「（共N人）」改为主句内的人数定语
    "hook_group_held": "{actor}握有对{names}共{n}人的{strength}牵制{name}。",
    "hook_group_over": "{names}共{n}人握有对{actor}的{strength}牵制{name}。",
    # v41 (问题8): 删去「主角握有的牵制如下：」「他人握有对主角的牵制如下：」
    # 两条块首标题行 —— 每条牵制句已自足, 标题行只会把该维度引成开放清单。
    "hook_strong_word": "强",
    # v55 (问题2): 时间补注去括注 —— 作为句末小句附在牵制句后 (不再「（921年起）」)
    "hook_since": "，自{year}年起",
    "hook_expires": "，{date}届满",
    # v38 (问题2): 牵制**白名单**判据 (见 FACT_WORDING["hook_keep_*"]) —
    # 只下发「背后有一件具体事」的牵制; 通用人情/身份自带类一律不入事实层。
    # 判据由程序在 cache_lib 入库前与 facts 读取时各执行一次 (旧缓存同样生效),
    # 不写进提示词 (no-negative-prompts 的 prompt-last 铁律)。
    "hook_keep_exact": frozenset({
        # —— 勒索: 背后必有一桩隐事 (弱勒索另有 weak_prostitute_blackmail_hook) ——
        "weak_blackmail_hook", "weak_blackmail_hook_no_secret",
        "weak_prostitute_blackmail_hook", "strong_prostitute_blackmail_hook",
        # —— 捏造 / 罪案 / 比试: 各有具体由头 ——
        "fabrication_hook", "minor_crime_accomplice_hook",
        "sumptuary_crime_hook", "trial_by_combat_hook",
        # —— 结拜 (献血为盟是一件具体事) ——
        "blood_brother_hook", "blood_sister_hook",
        # —— Mod 内容牵制 (Carnalitas 奴役 / interracial_takeover 的奴隶 /
        #    缺角作者包的「干了我老婆」) ——
        "carn_slave_hook", "bno_slave_hook", "bno_cum_slave_hook",
        "ganlewodelaopo_hook",
    }),
    # 通用人情类牵制的**族名片段** (含这些片段的类型键一律剔除):
    # 人情 (favor_hook 本地化即「人情」)、义务、蒙恩、支持者、忠诚、威胁、
    # 操控、家主/孝道 (身份自带)、可继承的感恩宣称、契约类。
    "hook_keep_drop_fragments": (
        "favor", "obligation", "indebted", "supporter", "loyalty",
        "threat", "manipulation", "suspicious", "house_head", "filial_piety",
        "oath_claimant", "contact_list", "influence", "hostage", "follower_oath",
    ),
    # 引擎脚本关键字/测试钩子被 hook_types 解析器误收为「牵制类型」的部分:
    # 白名单制天然排除, 此处只用于 `hook_type_name_ok` 判断显示名是否有意义。
    "hook_keep_ignore": frozenset({
        "on_used", "send_interface_toast", "if", "limit", "NOT", "target", "OR",
        "stress_impact", "test_hook", "strong_test_hook", "perpetual_test_hook",
        "add_test_hook",
    }),
    # v35: 奴役 (Carnalitas) — 存档里「释放」记忆正是「没为奴隶」这一步, 故出狱缘由
    # 写「没为奴隶」而不是「获释」; 奴役本身不带日期, 年份取逐档差分的首见档
    # (差分日期与囚期可能差一档, 故不写「同日」)。{year} 取自 Facts._year_only,
    # **已含「年」字** (如「874年」)。
    "prison_enslaved": "，没为奴隶",
    "enslaved_line": "{slave}没为{actor}的奴隶。",
    "enslaved_line_on": "{date}，{slave}没为{actor}的奴隶。",
    # v55 (问题2): 去括注 —— 起年改为句首状语 (「X自874年起没为Y的奴隶。」)
    "enslaved_line_since": "{slave}自{year}起没为{actor}的奴隶。",
    "enslaved_group": "{year}起，{actor}的奴隶有{names}{extra}。",
    "enslaved_group_extra": "等{n}人",
    "enslaved_head": "主角的奴隶如下：",
    # v38 (问题4): 「曾经是主角的奴隶」的收束句 —— 三档各有确定判据
    # (cache_lib._diff_enslavements 的 end_owner / freed / 两者皆无):
    #   _sold  失去那一刻已被**别人**奴役 = 转卖, 带出买家;
    #   _freed 失去那一刻已无人奴役他   = 转为 former_slave (获释);
    #   _lost  其余 (死亡 / 数据中断) — 只写到「没为…的奴隶」为止, 不外推缘由,
    #          也不写「不再见于记载」式按语 (v80 点2: 这类缺席陈述会被模型照抄)。
    # v55 (问题2): {since} 由调用方给成句首状语 (「自874年起，」/ 空串), 不再是括注
    "enslaved_former_sold":
        "{since}{slave}没为{actor}的奴隶，至{year}转归{buyer}。",
    "enslaved_former_freed":
        "{since}{slave}没为{actor}的奴隶，至{year}获释。",
    "enslaved_former_lost":
        "{since}{slave}没为{actor}的奴隶。",
    "enslaved_former_head": "主角昔日的奴隶如下：",
    # v38 (问题1): 角色修正 carn_recently_raped (身上留五年) 的收束句 ——
    # 与性事记忆互为佐证 (记忆给「谁做的」, 修正给「近来仍算近事」这一状态)。
    "carnal_recently_raped": "主角近来遭人强暴，此事五年之内仍算近事。",
    "carnal_opinions_head": "人身侵害与旧主奴关系如下：",
    # v38 (问题1 追修) / v39 的「强迫之事」事实行措辞 (harm_head/harm_line/
    # harm_after_subject/harm_after_none) 已随 **v59 (问题2)** 删除 ——
    # 用户拍板「性事只在《列传·好友》《列传·仇人》里用」, 该块不再下发。
    # v40: 性病 (情人疱疹/大痘) 传播 —— 无源时写「染上」; 有源时写「X把病传染给了Y」。
    # v59: 「补在性行为句末」的 `std_note` 随性事退出年表而停用, 故只留后两条。
    # 病名由本地化表直取 (本体中文: trait_lovers_pox=情人的疱疹 / trait_great_pox=梅毒)。
    "std_line": "{src}把{disease}传染给了{tgt}。",
    "std_line_anon": "{tgt}染上{disease}。",
    "std_head": "疾病传染如下：",
    # v32 (马克龙问题1): 强纳为妾 — 存档唯一带确切日期的纳妾记录
    # (opinions.active_opinions 的 forced_me_concubine_marriage_opinion.start_date);
    # 该脚本同一段落 `release_from_prison = yes`, 故「当日自狱中释出」是程序可断言的。
    "concubine_forced": "{date}，{actor}强纳{name}为妾。",
    "concubine_forced_paroled": "{date}，{actor}强纳{name}为妾，同日自狱中释出。",
    # v60 (问题3): 强纳有夫/有妇之人为妾时, 游戏对**原配**加
    # `forced_spouse_concubine_marriage_opinion` 并 `divorce = scope:recipient`
    # —— 崔佛档三名妾都是他人之妻, 这句把「谁是原配」写成事实, 免得模型
    # 为「离异」另造一位不存在的妻子。
    "concubine_divorced":
        "{date}，{name}原为{ex}之妻，因{actor}纳之为妾而离异。",
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
    # v36 (用户拍板3): 主角**获授**的朝廷职位 (太师/某部尚书…; employee=主角) —
    # 传主档案与《朝局风云录》同时出词; 「至晚」口径与特质履历同源 (快照差分推失去时点)。
    "office_head": "朝廷职位：",
    "office_held": "任{employer}之{word}",
    # v55 (问题2): 去括注 —— 授任日期作句首状语 (「自869年6月28日起任唐皇帝李漼之太师」);
    # 多度受任改「N度受任…，分别在…」; 失去时点本就是分句 (「；至晚自885年起已卸任」)。
    "office_held_since": "自{date}起任{employer}之{word}",
    "office_held_multi": "{n}度受任{employer}之{word}，分别在{dates}",
    "office_lost_late": "；至晚自{year}起已卸任",
    "office_change_gain": "{date}：受{employer}之{gverb}为{word}",
    "office_change_lose": "{date}：已卸任{word}",
    # v76 (问题1): 传主「在位终结但未死亡」的收句 (让位/剃发退位/去位) ——
    # 由 pipeline._cross_check_reign_ends 从 played_character.legacy 接替链判出;
    # 收在终传主角档案与共享前缀的【传位】行, 与「卒」句互斥 (同一人只出其一)。
    "reign_end_line": "{date}，{word}",
    "reign_end_line_successor": "{date}，{word}，传位于{succ}。",
    "reign_end_tonsured": "剃发退位",
    "reign_end_abdicated": "退隐让位",
    "reign_end_landless": "去位，转徙无领地",
    "reign_end_unknown": "让位",
    "reign_end_note": "【传位】",
}


# v36 (用户拍板4): 头衔授予动词 — 按**授予方政体**取词 (天朝/行政=任命, 封建=册封,
# 部落/宗族=授予…)。头衔记忆句补「被谁任命/授予」时用; 取不到政体用「任命」。
TITLE_GRANT_VERBS = {
    "celestial": "任命",
    "administrative": "任命",
    "meritocratic": "任命",
    "steppe_admin": "任命",
    "feudal": "册封",
    "clan": "授予",
    "tribal": "授予",
    "nomad": "授予",
    "herder": "授予",
    "wanua": "授予",
    "mandala": "授予",
}
TITLE_GRANT_VERB_FALLBACK = "任命"
# 去职动词: 自行去职 (stepped_down) 用「辞去」; 被夺 (revoked/usurped) 用「褫夺」/「篡夺」
TITLE_RESIGN_VERB = "辞去"
TITLE_REVOKE_VERB = "褫夺"
TITLE_USURP_VERB = "篡夺"

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


# v95 (问题1): **宣战理由 (Casus Belli) 键 → 史传腔短语**。
#
# 游戏只为 126 个 CB 中的一部分写记忆本地化键 `war_memory_cb_*`
# (`game/common/scripted_effects/03_bp1_scripted_effects.txt:877-996` 的硬编码白名单,
# 中文见 `localization/simp_chinese/memories_l_simp_chinese.yml:981-1009`); 其余
# **56 个 CB 一律落 `war_memory_cb_fallback`**(正文「战争」, 项目按约定丢弃)。
# v95 起事实层改从缓存 `war_history` 回查真 CB 键 (该战进行时从存档闩下), 故这里补
# 一张项目措辞表 —— 键即 `casus_belli_types` 里的 CB 键 (见
# `docs/调研_v95_对立教宗战争理由.md` §5.3 的完整清单)。查不到的键仍按原口径省略
# 「以…」分句 (宁缺不错); `war_memory_cb_*` 键不在此表、仍走游戏本地化表。
WAR_CB_ZH = {
    # ---- By God Alone (pam_*) ----
    "pam_challenge_hof_cb": "扶立对立教宗",     # 扶立者代其对立方挑战信仰领袖 (攻方是对立教宗本人时改「挑战信仰领袖」, 见 facts._war_start_clause)
    "pam_antiking_cb": "废黜对立教宗",
    "pam_humiliation_cb": "折辱之战",
    "pam_investiture_conflict_cb": "叙任权之争",
    # ---- 天命/中国 (tgp_*) ----
    "claim_the_mandate_cb": "争夺天命",
    "chinese_reunification_cb": "统一天下",
    "chinese_consolidation_cb": "一统之战",
    "china_seize_county_cb": "夺取州县",
    "china_seize_duchy_cb": "夺取州郡",
    "china_hegemon_seize_county_cb": "霸主夺地",
    "china_hegemon_seize_duchy_cb": "霸主夺郡",
    "grand_campaign_kingdom_invasion_cb": "大征伐",
    "silk_road_vassalization_cb": "丝路臣服",
    "ceremonial_claimant_faction_war": "拥立之争",
    "imperial_policy_faction_war": "朝政之争",
    "restore_ceremonial_liege_faction_war": "复礼之争",
    "eradicate_house_cb": "灭族之战",
    "mandala_plunder_cb": "掠地之战",
    "mandala_raze_capital_structure_cb": "焚都之战",
    "admin_barbarian_conquest_cb": "征讨蛮夷",
    # ---- 日本/东亚其余 ----
    "raiktor_claim_cb": "夺位之战",
    "raiktor_conquest_cb": "征服之战",
    "mythical_ancestor_war": "先祖之仇",
    "azariqa_rebellion_cb": "阿扎里加叛乱",
    "fp3_zanj_rebellion_war": "桑给叛乱",
    "greek_anarchy_cb": "希腊之乱",
    "ep3_hasan_assassin_war": "讨伐阿萨辛",
    # ---- 通用/行政/游牧/fp3 ----
    "expansion_cb": "拓土之战",
    "duchy_expansion_cb": "拓郡之战",
    "naval_expansion_cb": "海疆拓土",
    "naval_duchy_expansion_cb": "海疆拓郡",
    "influence_war_cb": "权势之战",
    "imperial_expedition_cb": "帝国远征",
    "dissolve_empire_war": "解体帝国",
    "pax_romana_invasion_war": "罗马和平之征",
    "humiliation_cb": "折辱之战",
    "migration_cb": "举族迁徙",
    "nomadic_war": "游牧之战",
    "mpo_nomad_duchy_invasion_cb": "游牧夺郡",
    "mpo_great_war_of_defiance_cb": "抗命之战",
    "ep3_laamp_peasant_war": "镇压民变",
    "ep3_laamp_apprehend_adventurer_cb": "讨伐冒险者",
    "ep3_laamp_raid_contract_cb": "劫掠之约",
    "ep3_pillaging_foray": "劫掠出征",
    "ep3_roman_empire_border_war": "边境之战",
    "legendary_adventure": "传奇远征",
    "leg_demand_fealty_cb": "索求臣服",
    "fp3_free_house_member_cb": "解救族人",
    "fp3_install_loyalist_cb": "扶立忠臣",
    "fp3_unify_house_cb": "统一宗族",
    "fp3_seljuk_invasion_cb": "塞尔柱入侵",
    "fp3_turkic_invasion_cb": "突厥入侵",
    "crusading_claim_cb": "十字军索取",
    "ireland_laudabiliter_conquest_cb": "敕许征服",
}


# v28: 头衔得失动词 — 按 memory vars.reason (游戏给的缘由) 出词。
# 旧口径一律「登位，得X」/「让出X」, 使天朝制/行政制的**官职任命轮转**
# (reason=appointment_succession / stepped_down) 被读成「被人打败、又夺人领地」
# (陆氏: 869 受任阶州、872 卸任阶州、875 受任商州 被写成 登位/让出)。
# 政体无关: 封建的承袭/受封/攻取、行政制的受任/调任 一表覆盖; 未知 reason
# 回退旧词 (登位/让出), 行为与旧版一致。
TITLE_GAIN_VERBS = {
    # v34b (柳特佩特): created = **本人创设头衔** —— 游戏自有文案即
    # `ascended_throne_memory_desc_intro_created = 我创建了[landed_title]`
    # (`game_concept_created = 创建`), 旧词「受封」(v28 为世族庄园所定) 把
    # 玩家自创的萨莱诺亲王国写成受人册封。分两档见 TITLE_GAIN_CREATED_VERBS。
    "created": "创建",
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


# v34b / v53: reason=created 分三档 —
#   first    无前主 → 「创建」(游戏 desc_created_first「作为一个新头衔」)
#   restored 前主同宗族 → 「重建」(真复辟, 游戏 desc_created「在一段废弃期后」)
#   founded  前主异宗族且 hegemon 级 → 「开创」(天朝宣称天命、新朝坐旧头衔)
# 判定入口 Facts.created_verb_kind。
TITLE_GAIN_CREATED_VERBS = {
    "first": "创建",
    "restored": "重建",
    "founded": "开创",   # v53: 异宗族重立 hegemon (h_china 宣称天命)
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
    # v38 (问题1): 双方自愿、但非配偶的床笫之事 (Carnalitas 的 consensual 族) ——
    # 婚姻之外的相与; 配偶那一档仍走 `had_sex_spouse`。
    "had_sex_consensual": "{name}与{other}相与。",
    "became_friends": "{name}与{other}结为好友。",
    "became_soulmates": "{name}与{other}结为灵魂伴侣。",
    "became_blood_brother": "{name}与{other}结为血盟兄弟。",
    "imprisoned_other": "{name}囚禁{other}。",
    # v32 (马克龙问题1): 被囚的记忆带 imprisoner 槽 (participants), 旧句「{name}被囚。」
    # 把监禁者丢掉 —— 家室档案行只写「公主被囚」, 模型只好自己猜是谁囚的。
    # 无对手方槽时回退 `_no_other` 版 (见 facts._mem_sentence 的兜底规则)。
    "imprisoned": "{name}为{other}所囚。",
    "imprisoned_no_other": "{name}被囚。",
    "released_from_prison_memory": "{name}获释。",
    # v32: 越狱 (escaped_from_prison_memory, participants=imprisoner) 此前无模板 →
    # _mem_sentence 返回 None, 越狱整条不入事实面 (主角 869.10.16 即如此)。
    "escaped_from_prison_memory": "{name}从{other}的监禁中逃脱。",
    "escaped_from_prison_memory_no_other": "{name}越狱脱身。",
    "lost_title_memory": "{name}让出{title}。",
    "ascended_throne_memory": "{name}获得{title}。",
    "child_born": "{name}添子{other}。",
    "first_born": "{name}得长子{other}。",
    # v32 (马克龙问题3): 夭折记忆的 participants 是 **mother** —— 旧句只有父名,
    # 模型据此写出「未知其母, 只知为某人之血脉」(主角只一位妻子, 母亲其实早有数据)。
    # 配偶词按持有人性别与关系取 (妻/夫; 妾另表, 见 facts._consort_word);
    # 生母本人持有该记忆 (自指) 时用 `_no_other` 版, 不出「A之妻A」。
    "child_premature": "{name}之{rel}{other}流产。",
    "child_premature_no_other": "{name}流产。",
    "child_stillborn": "{name}之{rel}{other}产下死婴。",
    "child_stillborn_no_other": "{name}产下死婴。",
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
    "childhood_education_guardian": "{name}被{other}教育。",
    "childhood_education_no_guardian": "{name}独自求学。",
    "completed_rites_of_passage": "{name}完成成人礼。",
    "completed_adult_education": "{name}完成深造。",
    "became_acclaimed": "{name}获拥戴。",
    # v56 (问题1b): 加冕类两条此前一条残缺、一条缺模板 ——
    # witnessed 的参与者是 host (受冕者), 旧模板无 {other} 只出「见证加冕」;
    # held (当事人自己受冕) 在表里**没有条目**, _mem_sentence 返回 None,
    # 整件事不进事实面。加冕成的头衔由 facts 按加冕当日首要头衔填入 {title}
    # (游戏文案 held_a_coronation_memory_desc: 「我被[coronator]正式加冕为
    # [owner primary title]的合法[owner title]」)。
    "witnessed_a_coronation_memory": "{name}见证{other}的加冕。",
    "witnessed_a_coronation_memory_no_other": "{name}见证加冕。",
    "held_a_coronation_memory": "{name}受{other}加冕为{title}。",
    "held_a_coronation_memory_no_other": "{name}受加冕为{title}。",
    # v78-5 (用户 D6): 加冕族其余 17 键 —— 旧稿只有上面四条, 故 `_mem_sentence_body`
    # 对其余各键返回 None, 整条记忆不进事实面 (实测 25 份缓存里 22 键共 1640 条,
    # 过 `_related_ids` 闸门后仍有个位数行能进年表)。模板一律正向史书式;
    # 「须 `_no_other`」= 参与者槽可能缺失, 由 `_mem_sentence_body` 的 `_no_other`
    # 回退兜住。详见 `docs/调研_v78_加冕记忆.md` §5.2。
    "crowned_by_hof_memory": "{name}受{other}祝圣，加冕为{title}。",
    "crowned_by_hof_memory_no_other": "{name}受祝圣而加冕为{title}。",
    "coronation_highlighted_memory": "{name}在{other}的加冕礼上领舞。",
    "coronation_highlighted_memory_no_other": "{name}在加冕礼上领舞。",
    "coronation_cultural_acceptance_memory":
        "{name}在{other}的加冕礼上为族人发声，两族由此相知。",
    "coronation_cultural_acceptance_memory_no_other":
        "{name}在加冕礼上为族人发声。",
    "coronation_legitimacy_memory": "{name}出席{other}的加冕礼，获其正统之认。",
    "coronation_legitimacy_memory_no_other": "{name}出席加冕礼，获正统之认。",
    "coronation_friend_memory": "{name}在{other}的加冕礼上许以友谊。",
    "coronation_friend_memory_no_other": "{name}在加冕礼上许以友谊。",
    "coronation_alliance_memory": "{name}在{other}的加冕礼上缔结同盟。",
    "coronation_alliance_memory_no_other": "{name}在加冕礼上缔结同盟。",
    "coronation_hook_memory": "{name}在{other}的加冕礼上得其一诺。",
    "coronation_hook_memory_no_other": "{name}在加冕礼上得其一诺。",
    "coronation_vassal_levies_memory": "{name}在{other}的加冕礼上求得军役之减。",
    "coronation_vassal_levies_memory_no_other": "{name}在加冕礼上求得军役之减。",
    "coronation_vassal_taxes_memory": "{name}在{other}的加冕礼上求得赋税之减。",
    "coronation_vassal_taxes_memory_no_other": "{name}在加冕礼上求得赋税之减。",
    "coronation_claim_memory": "{name}在{other}的加冕礼上获授主张头衔之名。",
    "coronation_claim_memory_no_other": "{name}在加冕礼上获授主张头衔之名。",
    "coronation_faction_discontent_memory": "{name}在{other}的加冕礼上以派系相抗。",
    "coronation_faction_discontent_memory_no_other": "{name}在加冕礼上以派系相抗。",
    "coronation_faction_members_memory": "{name}在{other}的加冕礼上聚党相抗。",
    "coronation_faction_members_memory_no_other": "{name}在加冕礼上聚党相抗。",
    "coronation_magnificence_loss_memory": "{name}在{other}的加冕礼上折其威仪。",
    "coronation_magnificence_loss_memory_no_other": "{name}在加冕礼上折其威仪。",
    "coronation_coup_memory": "{name}的加冕礼为{other}所变。",
    "coronation_coup_memory_no_other": "{name}的加冕礼中途生变。",
    "conquest_oath_memory": "{name}在加冕礼上立下拓土之誓。",
    "reconquest_oath_memory": "{name}在加冕礼上立下复土之誓。",
    "injured_in_crowd_crush_at_coronation_memory":
        "{name}在{other}的加冕礼上遭人群践踏而伤。",
    "injured_in_crowd_crush_at_coronation_memory_no_other":
        "{name}在加冕礼上遭人群践踏而伤。",
    "got_the_city_drunk_memory": "{name}在{other}的加冕宴上使满城尽醉。",
    "got_the_city_drunk_memory_no_other": "{name}在加冕宴上使满城尽醉。",
    "defeated_detractor_in_drinking_contest_memory":
        "{name}在加冕宴的斗酒中胜过{other}。",
    "defeated_detractor_in_drinking_contest_memory_no_other":
        "{name}在加冕宴的斗酒中取胜。",
    "was_caught_cheating_in_drinking_contest_memory":
        "{name}在加冕宴的斗酒中作弊，为{other}发现。",
    "was_caught_cheating_in_drinking_contest_memory_no_other":
        "{name}在加冕宴的斗酒中作弊。",
    # v78-5: 流放/逐出宗族三型 (旧稿零接管; 三型同源, 由
    # `common/events/dlc/mpo/mpo_nomad_events_1.txt` 的事件 .1020 一次写出)
    "exiled_kin_memory": "{name}放逐其亲属{other}，逐之出族。",
    "exiled_by_kin_memory": "{name}为亲属{other}所放逐，去族而居。",
    "defected_from_kin_memory": "{name}率部众离{other}自立，别为一族。",
    "grand_wedding_completed_guest": "{name}出席大婚。",
    "ignored_assault_memory": "{name}受辱未报。",
    # v15: 成功谋杀 (主角视角, 神秘死亡味由受害者死亡记录句负责)
    "successful_murder": "{name}谋杀{other}。",
    # v38 (问题1 顺带): 同期未命中的普通游戏记忆 — 此前整条落不到事实面。
    "saved_from_assault_memory": "{name}自袭击中救下{other}。",
    "stopped_being_friends": "{name}与{other}断绝交谊。",
    "lover_died": "{name}的情人{other}去世。",
    "soulmate_died": "{name}的灵魂伴侣{other}去世。",
    "best_friend_died": "{name}的挚友{other}去世。",
    "nemesis_died": "{name}的死敌{other}去世。",
    "developed_crush": "{name}喜欢上了{other}。",
    "had_a_threesome_memory": "{name}与{other}、{other2}同宿。",
}


# ---------------------------------------------------------------------------
# v38 (问题1) / v39 (诺兰测试集): Carnalitas 性事记忆族 (had_sex_*) 的措辞表
# ---------------------------------------------------------------------------
# 类型键由 Mod 按 `性别关系×主动/被动×体位×射精位置×自愿程度` 组合生成
# (common/scripted_effects/carn_had_sex_memory_effect.txt, 共 24 键), 逐键写模板
# 既不可能也不必要 —— 事实层取「谁对谁做了什么、什么体位、自愿到什么程度」。
#
# 收录范围 (用户拍板 2026-09-14, 诺兰测试集复核): **只记录强迫与非自愿**两类 ——
# 即 `_noncon` (强迫) 与 `_dubcon` (半强迫); `_consensual` 一律仍按旧口径
# (`had_sex` / `had_sex_spouse` / `had_sex_consensual`) 由 `MEMORY_TEMPLATES`
# 处理, 即**自愿的性行为不进事实面**。
#
# 方向铁律 (与 Mod 脚本逐条核对): 类型名里的 `giving_player` 即**施为方**,
# `receiving_player` 即**受害方** —— 与男女无关 (女性施为时 Mod 写 `_fm_desc`
# 「我逆强奸了X」, 仍是 giving 方为主使者)。因此:
#   `_mem_sentence` 先看 `_actor_of_sex_mem()` 判出记忆持有人是施为方还是受害方,
#   再在这里取对应句式。
#
# 体位词 (用户拍板 2026-09-14 二版, 诺兰测试集; v59 改 dubcon 译法): 句式统一为
# 「自愿 / 半推半就 / 强迫 + Mod 体位词」, 不用「强奸/鸡奸」——
#   `_noncon` 施为 = 「X强迫Y性交。」, 受害 = 「Y被X强迫性交。」;
#   `_dubcon` 施为 = 「X半推半就，与Y性交。」, 受害 = 「Y半推半就，与X性交。」。
# 体位词直取 Mod 记忆键: vaginal→性交 / anal→肛交 / oral→口交。
# 女方施为的强迫档另取「逆强奸」句 (Mod 的 `_fm_desc` 文案即「我逆强奸了X」);
# 插入语义只对阴道与肛两档成立, 口交档仍作「强迫…口交」。
# 射精位置 (cum_inside/outside) 仍不进事实面 —— 那是游戏 UI 的露骨描述。
SEX_MEM_WORDING = {
    # 施为方视角: {name}=持有人 (施为者), {other}=受害方
    "actor_noncon": {
        "vaginal": "{name}强迫{other}性交。",
        "anal": "{name}强迫{other}肛交。",
        "oral": "{name}强迫{other}口交。",
        "base": "{name}强迫{other}性交。",
    },
    # v59 (问题1): 措辞按用户 2026-09-23 拍板「保留自愿/半推半就/强迫三档」
    # —— 游戏旗标 `dubcon` 的原义是「对方并不情愿，但也不到强迫」(Mod 自己的
    # 中文文案即「半推半就」), 旧稿译作「半强迫」把配偶之间的床笫之事推成
    # 人身侵害, 与同档位的「同房」(自愿) 并存时自相矛盾 (吉贝尔蒂 1075.5.31)。
    # 故施为档改用「半推半就」—— 与受害档同一套词, 三档仍是
    # 自愿(`同房`/`相与`) < 半推半就 < 强迫(`noncon`)。
    "actor_dubcon": {
        "vaginal": "{name}半推半就，与{other}性交。",
        "anal": "{name}半推半就，与{other}肛交。",
        "oral": "{name}半推半就，与{other}口交。",
        "base": "{name}半推半就，与{other}性交。",
    },
    # 受害方视角: {name}=持有人 (受害者), {other}=施为方
    "victim_noncon": {
        "vaginal": "{name}被{other}强迫性交。",
        "anal": "{name}被{other}强迫肛交。",
        "oral": "{name}被{other}强迫口交。",
        "base": "{name}被{other}强迫性交。",
    },
    "victim_dubcon": {
        "vaginal": "{name}半推半就，与{other}性交。",
        "anal": "{name}半推半就，与{other}肛交。",
        "oral": "{name}半推半就，与{other}口交。",
        "base": "{name}半推半就，与{other}性交。",
    },
    # 女方施为的强迫档 (施为方性别由存档确定性判定, 见 facts._sex_mem_sentence):
    # Mod 的 `_fm_desc` 即「我逆强奸了X, 让他把鸡巴塞进我的小穴/屁眼」。
    "actor_reverse_noncon": {
        "vaginal": "{name}逆强奸{other}，行阴道性交。",
        "anal": "{name}逆强奸{other}，行肛交。",
        "base": "{name}逆强奸{other}。",
    },
    # 归并行 (同一受害者被同一人多次 / 同一施为者多次) — 两句各一
    "group_actor": "{name}对{names}共{n}次行强迫之事。",
    "group_victim": "{name}为{names}共{n}次所强迫。",
}

# v40: 性病 (情人疱疹/大痘) 传播当次的**自愿**性事 —— 用户拍板 2026-09-15:
# 「发生性病传播时, 在性行为后面加上一句（某某把疱疹/大痘传染给了某某）,
#   此时不论该性行为是自愿或非自愿都记录（只有这一个特例）」。
# 故自愿档只在「本次即传播当次」时出体位句, 其余自愿档仍走旧模板 (私情/同房)。
# 措辞**不带方向**: Mod 对同一场性事给双方各写一条 (giving/receiving), 归一后
# 同型同参与者, `_timeline` 的成对去重只留一条 —— 保留哪一条由缓存遍历次序决定。
SEX_MEM_CONSENSUAL = {
    "vaginal": "{name}与{other}性交。",
    "anal": "{name}与{other}行肛交。",
    "oral": "{name}与{other}行口交。",
    "base": "{name}与{other}性交。",
}
SEX_MEM_WORDING["actor_consensual"] = SEX_MEM_CONSENSUAL
SEX_MEM_WORDING["victim_consensual"] = SEX_MEM_CONSENSUAL


# v28: 隐事 (secrets) 主题短语 — 存档 secrets.secrets 的 type → 中文短语。
# 类型名本地化 (L.loc(table, type)) 只是名词 (考试舞弊者/巫师/不信者), 提示词里
# 需要可叙事的短语, 故按类型给模板; 未收录类型回退游戏本地化类型名。
SECRET_TOPICS = {
    "secret_murder": "谋杀{target}",
    "secret_murder_attempt": "谋杀{target}未遂",
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
    # v41 (问题4): 再点名**实父** —— 《家室列传》《阴私录》要靠这一句把
    # 「主角的女儿嫁的正是主角自己的私生子」接起来 (facts.secret_topic 传入
    # {father}; 实父判不出时退 SECRET_TOPICS_NO_FATHER 的简式)。
    "secret_unmarried_illegitimate_child":
        "所出{target}血脉存疑，亲生父亲为{father}",
    "secret_disputed_heritage": "所生{target}血统有争，亲生父亲为{father}",
    # v42 (问题1): 乱伦走自然动词式 —— 旧稿是 facts 里的 `乱伦：与{target}`
    # (全库唯一一条「标签：内容」式隐事主题), 嵌进「有隐事N桩：」成双层冒号;
    # 判不出对象时退 SECRET_TOPICS_NO_TARGET 的「乱伦」。
    "secret_incest": "与{target}乱伦",
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
    # v42 (问题1): 乱伦判不出对方时的简式 (名词即事, 不点名)
    "secret_incest": "乱伦",
}

# v41 (问题4): 血统类隐事判不出实父时的简式 (无料不下发实父位)
SECRET_TOPICS_NO_FATHER = {
    "secret_unmarried_illegitimate_child": "所出{target}血脉存疑",
    "secret_disputed_heritage": "所生{target}血统有争",
}

# v58 (问题2): **谓词型**隐事主题 —— 这些主题本身已是一个谓语短语（「与X私通」
# 「谋害X」「暗行巫术」），再套「{owner}有一桩隐事：{topic}」会读成
# 「玛蒂尔达·卡诺萨有一桩隐事：与阿普利亚公爵狐狸罗贝尔·欧特维尔私通。」
# 故这类直接作谓语出句：「1072年，玛蒂尔达·卡诺萨与阿普利亚公爵狐狸罗贝尔·欧特维尔私通。」
# 其余（名词型：科举舞弊 / 所生X血统有争 / 断袖…）保留原「有隐事」框架
# （它们需要「这是他的隐事」这层语义，直接作谓语不通）。
SECRET_PREDICATE_TYPES = frozenset({
    "secret_lover", "secret_incest", "secret_murder", "secret_murder_attempt",
    "secret_witch", "secret_embezzler", "secret_siphoned_treasury",
    "secret_adultery", "secret_coup_plotter", "secret_cannibal",
    # v92 (用户 2026-10-02 报): 科举舞弊的主题本身就是完整的谓语短语
    # (「在天皇帝穿刺者洪秀全主持的乡试中舞弊」), 套「有隐事：」框架后成为
    # 「崔穆有一桩隐事：在…乡试中舞弊。」—— 用户要的是「谁做了什么」:
    # 「崔穆在天皇帝穿刺者洪秀全主持的乡试中舞弊。」
    "secret_exam_cheater",
})


def secret_topic_is_predicate(tp):
    """该隐事类型的主题短语能否直接作谓语 (v58 问题2)。"""
    return str(tp or "") in SECRET_PREDICATE_TYPES


# v16: 动作型死因 → 施事句式 (原始 reason key → 动词)。有凶手/行刑者/对手
# 记录时, 把施事者直接嵌进句内 (被XXX谋杀 / 被XXX处决 / 与XXX决斗而亡),
# 不再另起「凶手为…」尾巴 — 更短, 也更像自然语言; 战场/意外/病亡的击杀者
# 不是「凶手」, 一律不点名。
# v75 (凶手点名): 该表是**内情档**用词 (《刺客列传》), 不再等于「世人看到的」——
# `death_mysterious` 的世人说法是游戏本地化的「神秘死亡」, 是否点名取决于
# 存档旗标 `dead_data.killer_known` (见 facts.Facts.killer_is_public);
# 旧注「death_murder 是败露的谋杀」在田所 878 年孝子 (death_murder 但未败露,
# 秘密仍在世) 上是错的。
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

# v53 (问题4): 诛灭世族专用, 不进 EXECUTION_OPTIONS 随机池。
EXECUTION_PURGE = ("purge", "连坐处死")
# v60 (问题2): 遗骨存证的**吃掉** —— Mod「食人赋能」的
# `devour_single_character_effect` 是另一条动作 (直接 `death = { reason =
# death_execution }`, 不经处决交互、不斩首), 却因共用死因键落进上面的随机池。
# 该 Mod 的每个受害者都会留下「…之骨」遗骨 (`devour_bone_visual`, 成物时
# recipient = 下口者), 故死法由存档确定性给出, 用本条措辞。
EXECUTION_DEVOUR_BONE = ("devour_bone", "吃掉")

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
    # v32 (马克龙问题1): 越狱单列一档 — 与「被囚」不同, 它是主动脱身
    "escaped_from_prison_memory": "越狱",
    "offensive_war": "开战", "defensive_war": "应战",
    "war_won": "获胜", "war_lost": "战败",
    "battle_won_memory": "取胜", "battle_lost_memory": "失利",
    "faith_changed": "改信",
    # v78-5 (用户 D6): 加冕只计三条 —— 19k 条 `witnessed_*` 若逐条计会把概览撑爆
    "held_a_coronation_memory": "受冕",
    "crowned_by_hof_memory": "受冕",
    "witnessed_a_coronation_memory": "见证加冕",
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


def hook_type_kept(tp):
    """牵制类型是否进入事实层 (v38, 问题2)。

    白名单制 (见 FACT_WORDING["hook_keep_exact"] / `hook_keep_drop_fragments`):
    只有「背后有一件具体事」的牵制才下发 —— 勒索族 (背后是隐事)、捏造、罪案共犯、
    违反禁奢令、比武审判、Mod 内容牵制 (Carnalitas 奴役等), 以及全部以 `strong_`
    开头且不在通用人情类的强牵制 (黑函/重罪共犯/救命恩/血盟/神命/影响力…)。

    通用人情类一律剔除: 人情 (favor)、义务 (obligation)、蒙恩 (indebted)、
    支持者、忠诚、威胁、操控、可疑活动、家主、孝道 —— 这些是「某些角色欠了你
    一个人情」这类机制关系, 不构成叙事事件; 模型拿到它们只能编出「握有把柄」。
    实测德圣塔/周氏档: 全档 7259 条牵制里 `house_head_hook` 5243、`filial_piety_hook`
    1069、`favor_hook` 548, 而涉主角的只有 4 条 (全是这三类)。"""
    t = str(tp or "")
    if not t:
        return False
    if t in FACT_WORDING["hook_keep_ignore"]:
        return False
    if t in FACT_WORDING["hook_keep_exact"]:
        return True
    for frag in FACT_WORDING["hook_keep_drop_fragments"]:
        if frag in t:
            return False
    return t.startswith("strong_")


# v56 (问题3): 出狱缘由的两路数据源 —— `cache_lib._latch_prison_manners` 按这两张表
# 逐档闩存, `facts.Facts.release_manner` 按同一数据读回 (措辞表在 facts 侧的
# `_PRISON_MANNER_MODS` / `_PRISON_KIND_WORD`, 其键集必须与下表一致, 见
# tools/tests/verify_v56_unit.py 的不变量断言)。
# ① 出狱类好感修饰符 (存档自带 start_date, 精确到日; 10 年衰减且随持有者死亡消失);
# ② 赎金·人情分支的牵制 —— 不在 `hook_type_kept` 白名单内 (不下发《阴私录》),
#    只在出狱缘由这一处使用; 其到期日 = 创建日 + 10 个日历年 (实测 15/15 逐日吻合)。
PRISON_MANNER_OPINION_MODS = frozenset({
    "released_from_prison", "merciful_opinion", "ransomed_from_prison",
    "demanded_my_conversion_opinion", "compelled_me_to_convert_opinion",
    "demanded_hook", "demanded_claim_renouncement", "banished_me",
    "demanded_recruitment", "demanded_taking_vows",
})
PRISON_MANNER_HOOK_TYPES = frozenset({"favor_hook", "indebted_hook"})
