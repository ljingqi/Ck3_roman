# -*- coding: utf-8 -*-
"""Model-facing prompt text for the biography generator: the single source of truth
for everything the model reads; biography.py and facts.py depend on it.
"""

# Standing rules for new prompt text: state what to do and keep negative phrasing
# out (see .agents/skills/no-negative-prompts); keep every deterministic concern in
# code and leave only creative writing to the prompt (prompt-last).

# ---------------------------------------------------------------------------
# 1. Prose profile
# ---------------------------------------------------------------------------
# Both profiles require modern standard Chinese; they differ only in the
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
    # rendered by the facts layer, and anything the program can enforce stays out
    # of the prompt.
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

# Household wording follows the material available: asked for marriage, divorce and
# childbirth with no spouse and no children, the model invents a family. The program
# picks the variant (biography._jiashi_variant); every variant is phrased positively.
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
        # Material is one line per ruler plus the current dynasty's wars and offices;
        # each mid section covers one slice of dynasties and the requirement line states
        # that slice's range (biography._chrono_mid_req).
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
        "tail": "写本朝枢机在下届教宗选举中的形势：在位枢机席数、本朝封臣入枢机者、"
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
# 7. Fact-layer wording (read by facts.py)
# ---------------------------------------------------------------------------
FACT_WORDING = {
    # Memory sentences, stats and merge verbs live in the top-level tables above
    # (MEMORY_TEMPLATES etc.); this dict holds the loose phrase templates only.
    # Assassin board lead line (the full name is named once per article).
    "assassin_lead": "刀下之魂共{n}人，皆死于{killer}之手。",
    # Imprisonment-duration quantifiers.
    "prison_same_day": "当日",
    "prison_days": "{n}日",
    "prison_months": "{n}个月",
    "prison_years": "{y}年",
    "prison_years_months": "{y}年{m}个月",
    "prison_released": "，{span}后获释",
    "prison_release_on": "，{date}获释",
    "prison_released_same_day": "，当日获释",
    # No release recorded: {bound} comes from facts (the decade archive's cutoff
    # date, or the last archive for the final biography). The program states the
    # whole clause so the model has no blank to fill in.
    "prison_still_held": "，至{bound}仍在押",
    # Other branch of the release split: escape (escaped_from_prison_memory).
    "prison_escaped": "，{span}后越狱逃脱",
    "prison_escape_on": "，{date}越狱脱身",
    "prison_escape_same_day": "，当日越狱脱身",
    "prison_jailed": "{jailer}囚禁{victim}",
    "prison_held": "{victim}被囚",
    # Only capture modes with hard evidence get their own wording: siege and battle
    # capture are indistinguishable in the save (both use the bare `imprison`, and
    # `melt["sieges"]` keeps only ongoing sieges), so the undecidable case keeps the bare
    # wording with no mode stated, leaving the model no room to invent a capture scene.
    "prison_captured_battle": "{jailer}于战阵俘获{victim}",
    "prison_captured_diarch": "{jailer}以摄政之权拘押{victim}",
    "prison_batch_seized": "{jailer}拘押{victim}",
    # A minor prisoner rules out capture in battle: the defeat pool holds only the
    # losing side's main commander and its knights, all adult combatants. The wording
    # states the detention and the age at the time, and nothing more.
    "prison_note_age": "{victim}，时年{n}岁",
    # Positive raid evidence: the jailer's `landed_data.last_raid` falls on the
    # imprisonment date — the only save field that pins down a capture by raiding.
    "prison_raid_captured": "{jailer}劫掠中掳走{victim}",
    # Program fallback for the cause of a love affair (game reason key unavailable):
    # both held by the same jailer under house_arrest, the relationship starting
    # inside their shared detention window. States only determinable facts.
    "lovers_same_prison": "{name}与{other}同在{jailer}的软禁中相恋",
    "lovers_same_prison_no_jailer": "{name}与{other}同在软禁中相恋",
    # Same-day imprison+release on the day the prisoner's war ends means capture at the
    # war's end, not a catch-and-release.
    "prison_war_end": "{jailer}战胜{victim}，俘之",
    # Castration/blinding always falls on the release day (21 of 21 saves), so the
    # punishment becomes the release reason inside the imprisonment sentence instead
    # of a line of its own; {sp} is the elapsed span (same day, or the elapsed days).
    "prison_punish_castrated": "，{sp}遭阉割而获释",
    "prison_punish_blinded": "，{sp}遭剜目而获释",
    "prison_punish_beardless":
        "，{sp}其在成年前被{jailer}阉割，终身无须，因而获释",
    "prison_punish_generic": "，{sp}受刑而获释",
    # Prison terms closed by death: a death record with no release and no escape is
    # written as an execution or a death in prison.
    "prison_died_executed": "，{sp}处决",
    "prison_died_in_prison": "，{sp}死于狱中",
    # Prison terms closed by being eaten: the cannibalism mod records eating as
    # `death_execution`, and the bone object it leaves (`devour_bone_visual`, see
    # `Facts._devour_bones`) is the only proof. The sentence's pronoun is the jailer it
    # names at its start, matching the name roster's wording.
    "prison_died_devoured": "，{sp}被其吃掉",
    # Hook sentence: strong vs ordinary hook (game [strong_hook] / [hook]). {name}
    # comes from facts in quoted form and is empty when localization misses; {since}
    # is a start year or an expiry date. Single targets are written one per line,
    # several of one kind are merged.
    "hook_held_strong": "{actor}握有对{target}的强牵制{name}{since}。",
    "hook_held_weak": "{actor}握有对{target}的牵制{name}{since}。",
    "hook_over_actor_strong": "{holder}握有对{actor}的强牵制{name}{since}。",
    "hook_over_actor_weak": "{holder}握有对{actor}的牵制{name}{since}。",
    # Merged line for many targets or holders: one pattern per direction, the first
    # three names plus the total count carried inside the sentence, not in brackets.
    "hook_group_held": "{actor}握有对{names}共{n}人的{strength}牵制{name}。",
    "hook_group_over": "{names}共{n}人握有对{actor}的{strength}牵制{name}。",
    "hook_strong_word": "强",
    "hook_since": "，自{year}年起",
    "hook_expires": "，{date}届满",
    # Hook whitelist criterion: only hooks with a concrete event behind them reach
    # the fact layer, while generic favors and identity hooks do not. The test runs
    # in cache_lib at ingest and again in facts on read (so old caches follow it too)
    # and never appears in the prompt (prompt-last).
    "hook_keep_exact": frozenset({
        # Blackmail: always backed by a secret (weak blackmail has its own key).
        "weak_blackmail_hook", "weak_blackmail_hook_no_secret",
        "weak_prostitute_blackmail_hook", "strong_prostitute_blackmail_hook",
        # Fabrication / crime / trial by combat: each has a concrete cause.
        "fabrication_hook", "minor_crime_accomplice_hook",
        "sumptuary_crime_hook", "trial_by_combat_hook",
        # Blood brotherhood / sisterhood: a concrete sworn act.
        "blood_brother_hook", "blood_sister_hook",
        # Mod-content hooks (Carnalitas slavery, interracial_takeover slaves,
        # `ganlewodelaopo_hook`).
        "carn_slave_hook", "bno_slave_hook", "bno_cum_slave_hook",
        "ganlewodelaopo_hook",
    }),
    # Type-key fragments of the generic-favor family; any key containing one is
    # dropped: favor, obligation, indebted, supporter, loyalty, threat,
    # manipulation, house head / filial piety (identity-owned), claim, contract.
    "hook_keep_drop_fragments": (
        "favor", "obligation", "indebted", "supporter", "loyalty",
        "threat", "manipulation", "suspicious", "house_head", "filial_piety",
        "oath_claimant", "contact_list", "influence", "hostage", "follower_oath",
    ),
    # Engine script keywords and test hooks that the `hook_types` parser picks up as
    # "hook types"; the whitelist already excludes them, so this set only feeds
    # `hook_type_name_ok` when judging whether a display name is meaningful.
    "hook_keep_ignore": frozenset({
        "on_used", "send_interface_toast", "if", "limit", "NOT", "target", "OR",
        "stress_impact", "test_hook", "strong_test_hook", "perpetual_test_hook",
        "add_test_hook",
    }),
    # Enslavement (Carnalitas): the save's "released" memory is exactly the enslavement
    # step, so the release reason reads as enslavement rather than release. Enslavement
    # carries no date; the year is the first archive a per-archive diff sees it in (diff
    # and prison term may be one archive apart, hence no "same day"). {year} comes from
    # `Facts._year_only` and already contains the year word.
    "prison_enslaved": "，没为奴隶",
    "enslaved_line": "{slave}没为{actor}的奴隶。",
    "enslaved_line_on": "{date}，{slave}没为{actor}的奴隶。",
    "enslaved_line_since": "{slave}自{year}起没为{actor}的奴隶。",
    "enslaved_group": "{year}起，{actor}的奴隶有{names}{extra}。",
    "enslaved_group_extra": "等{n}人",
    "enslaved_head": "主角的奴隶如下：",
    # Closing line for "was once the protagonist's slave"; three branches with definite
    # criteria (`cache_lib._diff_enslavements` end_owner / freed / neither): _sold =
    # resold with the buyer named, _freed = released, _lost = the rest (death or data
    # break), which stops at the enslavement clause and adds no "no longer recorded" note,
    # since the model copies such absence statements. {since} is a sentence-initial
    # adverbial or an empty string.
    "enslaved_former_sold":
        "{since}{slave}没为{actor}的奴隶，至{year}转归{buyer}。",
    "enslaved_former_freed":
        "{since}{slave}没为{actor}的奴隶，至{year}获释。",
    "enslaved_former_lost":
        "{since}{slave}没为{actor}的奴隶。",
    "enslaved_former_head": "主角昔日的奴隶如下：",
    # Closing line for the `carn_recently_raped` character modifier (it stays for
    # five years); corroborates the sex memories — the memory says who, the modifier
    # says it still counts as recent.
    "carnal_recently_raped": "主角近来遭人强暴，此事五年之内仍算近事。",
    "carnal_opinions_head": "人身侵害与旧主奴关系如下：",
    # Venereal disease (lovers' pox / great pox) spread: with a known source "{src} gave
    # the disease to {tgt}", otherwise the target simply caught it. Names come from the
    # localization table (trait_lovers_pox, trait_great_pox).
    "std_line": "{src}把{disease}传染给了{tgt}。",
    "std_line_anon": "{tgt}染上{disease}。",
    "std_head": "疾病传染如下：",
    # Forced concubinage: the save's only concubinage record with an exact date
    # (`opinions.active_opinions`, forced_me_concubine_marriage_opinion.start_date). The
    # same script block sets `release_from_prison = yes`, so "released from prison the
    # same day" is program-assertable.
    "concubine_forced": "{date}，{actor}强纳{name}为妾。",
    "concubine_forced_paroled": "{date}，{actor}强纳{name}为妾，同日自狱中释出。",
    # Forcing a married person into concubinage makes the game add
    # `forced_spouse_concubine_marriage_opinion` and run `divorce = scope:recipient` on
    # the original spouse; this line states who that was, so the model does not invent a
    # wife to divorce.
    "concubine_divorced":
        "{date}，{name}原为{ex}之妻，因{actor}纳之为妾而离异。",
    # Spouse records merge the same-month bedchamber and love memories into one line.
    "affair_pair_spouse": "{y}年{m}月，{a}与{b}夫妻情笃。",
    # Affair arc: one sentence per lover. The arc already names the partner, so the
    # segments do not repeat it.
    "affair_entry": "{date}私通",
    "affair_lovers": "{date}相恋",
    "affair_soulmates": "{date}结为灵魂伴侣",
    "affair_broke_up": "{date}分手",
    "affair_lover_died": "{date}去世",
    "affair_repeat": "其后{years}屡续私通",
    "affair_joined_court": "自{date}在主角廷中",
    "court_knight": "{actor}廷中骑士",
    "court_member": "{actor}廷臣",
    # Court offices granted to the protagonist (employee = the protagonist): used both
    # in the subject dossier and in the court board. The loss date is an inferred
    # "no later than" year taken from snapshot diffs, as the trait history does.
    "office_head": "朝廷职位：",
    "office_held": "任{employer}之{word}",
    "office_held_since": "自{date}起任{employer}之{word}",
    "office_held_multi": "{n}度受任{employer}之{word}，分别在{dates}",
    "office_lost_late": "；至晚自{year}起已卸任",
    "office_change_gain": "{date}：受{employer}之{gverb}为{word}",
    "office_change_lose": "{date}：已卸任{word}",
    # "Reign ended but not dead" closing line (abdication / tonsure / step-down), decided
    # by `pipeline._cross_check_reign_ends` from the `played_character.legacy` succession
    # chain. It appears in the subject dossier and the shared prefix's succession line
    # (FACT_WORDING["reign_end_note"]) and is mutually exclusive with the death line.
    "reign_end_line": "{date}，{word}",
    "reign_end_line_successor": "{date}，{word}，传位于{succ}。",
    "reign_end_tonsured": "剃发退位",
    "reign_end_abdicated": "退隐让位",
    "reign_end_landless": "去位，转徙无领地",
    "reign_end_unknown": "让位",
    "reign_end_note": "【传位】",
}


# Title-grant verbs keyed by the granting polity (appointment / enfeoffment / grant),
# used when a title memory names who appointed or granted it; an unknown polity falls
# back to the appointment verb.
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
# Resignation verbs: a voluntary step-down uses the resign word, revoked / usurped
# titles use the seize words.
TITLE_RESIGN_VERB = "辞去"
TITLE_REVOKE_VERB = "褫夺"
TITLE_USURP_VERB = "篡夺"

# ---------------------------------------------------------------------------
# 8. Fact-layer wording tables (referenced by facts.py)
# ---------------------------------------------------------------------------
# Death-cause, title and execution wording used by the fact layer is collected
# here; facts.py imports it by alias. Game-key → word lookup tables stay in
# facts/localization (data mapping).

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


# Game-UI-flavored or broken death-cause text is refined here and takes precedence over
# the localization value, which reads like an in-game notification (the `blind` reason,
# for instance). Frail/illness deaths whose localization is an unresolved
# `[GetTrait(...)]` template are refined as well.
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
    # Successful unexposed murder: the game shows it as a mysterious death, so it is
    # worded as a secret murder to set it apart from the exposed "murdered by X" form;
    # the agent is embedded by _death_clause.
    "death_mysterious": "被秘密谋杀",
    # Frailty / illness (localization is a template or missing).
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
    # Long game-UI sentences → short natural ones.
    "death_broken_bones": "摔折筋骨而亡",
    "death_stress": "忧惧而亡",
    "death_punishment": "处决",
    "death_eradicated": "连同全族被处决",
    "death_hunted_by_wild_beast": "为野兽所噬而亡",
}


# Casus Belli key → historiography-style phrase.
#
# The game writes a `war_memory_cb_*` key for only part of its CB set (hardcoded whitelist,
# `game/common/scripted_effects/03_bp1_scripted_effects.txt`; Chinese in
# `localization/simp_chinese/memories_l_simp_chinese.yml`); the rest fall back to a plain war
# word, discarded here. The fact layer instead reads the real CB key from the cached
# `war_history`, latched from the save while the war ran: the keys below are
# `casus_belli_types` keys, and a missing key omits the reason clause rather than guessing.
WAR_CB_ZH = {
    # ---- By God Alone (pam_*) ----
    "pam_challenge_hof_cb": "扶立对立教宗",     # when the attacker is the antipope himself facts._war_start_clause swaps in its own phrase
    "pam_antiking_cb": "废黜对立教宗",
    "pam_humiliation_cb": "折辱之战",
    "pam_investiture_conflict_cb": "叙任权之争",
    # ---- Mandate of Heaven / China (tgp_*) ----
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
    # ---- Japan / rest of East Asia ----
    "raiktor_claim_cb": "夺位之战",
    "raiktor_conquest_cb": "征服之战",
    "mythical_ancestor_war": "先祖之仇",
    "azariqa_rebellion_cb": "阿扎里加叛乱",
    "fp3_zanj_rebellion_war": "桑给叛乱",
    "greek_anarchy_cb": "希腊之乱",
    "ep3_hasan_assassin_war": "讨伐阿萨辛",
    # ---- Generic / administrative / nomadic / fp3 ----
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


# Title gain verbs taken from the memory's `vars.reason`. One table covers feudal
# inheritance / grant / conquest and administrative appointment / transfer alike;
# an unknown reason falls back to the generic ascension / cession words.
TITLE_GAIN_VERBS = {
    # `created` means this person founded the title themselves; the game's own text is
    # `ascended_throne_memory_desc_intro_created` (and `game_concept_created`).
    # Split into three kinds, see TITLE_GAIN_CREATED_VERBS.
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


# `created` split three ways, entry point `Facts.created_verb_kind`: `first` = no previous
# holder, `restored` = previous holder of the same house, `founded` = another house at
# hegemon level.
TITLE_GAIN_CREATED_VERBS = {
    "first": "创建",
    "restored": "重建",
    "founded": "开创",   # another house re-founding a hegemon (h_china claiming the mandate)
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


# Memory type → Chinese ({name} = memory owner, {other} = participant, {title} = title).
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
    # Sex between spouses is not written as an illicit affair: within a marriage nothing
    # is illicit.
    "had_sex_spouse": "{name}与{other}同房。",
    # Consensual sex outside marriage (the Carnalitas consensual family); spouses
    # still use `had_sex_spouse`.
    "had_sex_consensual": "{name}与{other}相与。",
    "became_friends": "{name}与{other}结为好友。",
    "became_soulmates": "{name}与{other}结为灵魂伴侣。",
    "became_blood_brother": "{name}与{other}结为血盟兄弟。",
    "imprisoned_other": "{name}囚禁{other}。",
    # The imprisonment memory carries the imprisoner in its participants slot; with no
    # counterpart slot it falls back to the `_no_other` version (facts._mem_sentence).
    "imprisoned": "{name}为{other}所囚。",
    "imprisoned_no_other": "{name}被囚。",
    "released_from_prison_memory": "{name}获释。",
    # Escape memory (participants = the imprisoner).
    "escaped_from_prison_memory": "{name}从{other}的监禁中逃脱。",
    "escaped_from_prison_memory_no_other": "{name}越狱脱身。",
    "lost_title_memory": "{name}让出{title}。",
    "ascended_throne_memory": "{name}获得{title}。",
    "child_born": "{name}添子{other}。",
    "first_born": "{name}得长子{other}。",
    # The premature/stillbirth memories carry the **mother** in participants. The consort
    # word follows the holder's sex and relation (wife/husband; concubines have their own
    # table, facts._consort_word), and when the mother holds the memory herself the
    # `_no_other` version avoids a self-referential "A's wife A".
    "child_premature": "{name}之{rel}{other}流产。",
    "child_premature_no_other": "{name}流产。",
    "child_stillborn": "{name}之{rel}{other}产下死婴。",
    "child_stillborn_no_other": "{name}产下死婴。",
    "twins_born": "{name}得孪生子。",
    # Births are split by the child's sex.
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
    # Battle outcomes use neutral historiographic words, because game-UI phrasing gets
    # copied verbatim by the model. The offensive/defensive distinction is kept.
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
    # Coronation: `witnessed_*` takes the crowned person as its participant, and the
    # title in `held_*` is filled by facts from the primary title on the coronation day
    # (game text `held_a_coronation_memory_desc`).
    "witnessed_a_coronation_memory": "{name}见证{other}的加冕。",
    "witnessed_a_coronation_memory_no_other": "{name}见证加冕。",
    "held_a_coronation_memory": "{name}受{other}加冕为{title}。",
    "held_a_coronation_memory_no_other": "{name}受加冕为{title}。",
    # The remaining coronation-family keys, all positive historiographic templates.
    # The `_no_other` pairs cover a missing participant slot through the
    # `_mem_sentence_body` fallback.
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
    # Exile / expulsion from the house: three forms written by one event branch
    # (common/events/dlc/mpo/mpo_nomad_events_1.txt, event .1020).
    "exiled_kin_memory": "{name}放逐其亲属{other}，逐之出族。",
    "exiled_by_kin_memory": "{name}为亲属{other}所放逐，去族而居。",
    "defected_from_kin_memory": "{name}率部众离{other}自立，别为一族。",
    "grand_wedding_completed_guest": "{name}出席大婚。",
    "ignored_assault_memory": "{name}受辱未报。",
    # Successful murder, from the protagonist's view; the mysterious flavour comes
    # from the victim's death record.
    "successful_murder": "{name}谋杀{other}。",
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
# Carnalitas sex-memory family (had_sex_*) wording
# ---------------------------------------------------------------------------
# Type keys are generated by the mod from sex × role × position × ejaculation target ×
# consent (common/scripted_effects/carn_had_sex_memory_effect.txt, 24 keys), so the fact
# layer takes "who did what to whom, in what position, with what degree of consent".
#
# Only the forced and half-willing families are recorded (`_noncon` / `_dubcon`);
# `_consensual` goes through `MEMORY_TEMPLATES` instead, i.e. consensual sex does not reach
# the fact layer, except for the disease case noted below.
#
# Direction: `giving_player` in the type name is the actor and `receiving_player` the victim,
# regardless of sex; `_mem_sentence` resolves the holder's side via `_actor_of_sex_mem()` and
# then picks the pattern here. Position words come from the mod keys (one act word per
# vaginal/anal/oral key); a woman acting in the forced tier gets the reverse-rape pattern,
# and the ejaculation target (cum_inside/outside) never reaches the fact layer.
SEX_MEM_WORDING = {
    # Actor's view: {name} = holder (actor), {other} = victim.
    "actor_noncon": {
        "vaginal": "{name}强迫{other}性交。",
        "anal": "{name}强迫{other}肛交。",
        "oral": "{name}强迫{other}口交。",
        "base": "{name}强迫{other}性交。",
    },
    # The game flag `dubcon` means the other party is reluctant without being forced
    # (the mod's own Chinese text means "half-willing"); the scale stays consensual
    # (bedchamber / consensual partner) < half-willing < forced (`noncon`).
    "actor_dubcon": {
        "vaginal": "{name}半推半就，与{other}性交。",
        "anal": "{name}半推半就，与{other}肛交。",
        "oral": "{name}半推半就，与{other}口交。",
        "base": "{name}半推半就，与{other}性交。",
    },
    # Victim's view: {name} = holder (victim), {other} = actor.
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
    # Reverse-rape forced tier for a female actor (her sex is decided from the save,
    # see facts._sex_mem_sentence).
    "actor_reverse_noncon": {
        "vaginal": "{name}逆强奸{other}，行阴道性交。",
        "anal": "{name}逆强奸{other}，行肛交。",
        "base": "{name}逆强奸{other}。",
    },
    # Merged lines for repeated acts by one actor or against one victim.
    "group_actor": "{name}对{names}共{n}次行强迫之事。",
    "group_victim": "{name}为{names}共{n}次所强迫。",
}

# The one consensual case that is recorded: when a venereal disease is transmitted, a
# sentence naming who infected whom follows the act. The wording carries no direction —
# the mod writes one memory per side and `_timeline`'s pair dedup keeps one.
SEX_MEM_CONSENSUAL = {
    "vaginal": "{name}与{other}性交。",
    "anal": "{name}与{other}行肛交。",
    "oral": "{name}与{other}行口交。",
    "base": "{name}与{other}性交。",
}
SEX_MEM_WORDING["actor_consensual"] = SEX_MEM_CONSENSUAL
SEX_MEM_WORDING["victim_consensual"] = SEX_MEM_CONSENSUAL


# Secret topic phrases: the `type` of save `secrets.secrets` → Chinese phrase. The type
# localization (`L.loc(table, type)`) is only a noun (cheat, witch, non-believer) while the
# prompt needs a narratable phrase, hence a template per type; an unknown type falls back
# to the localized type name.
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
    # Lineage secrets name the child involved and the biological father, so the household
    # and secret boards can connect "the protagonist's daughter married the protagonist's
    # own illegitimate son" (facts.secret_topic passes {father}; an undetermined father
    # falls back to the shorter SECRET_TOPICS_NO_FATHER form).
    "secret_unmarried_illegitimate_child":
        "所出{target}血脉存疑，亲生父亲为{father}",
    "secret_disputed_heritage": "所生{target}血统有争，亲生父亲为{father}",
    # Incest uses a natural verb form; with no determinable counterpart it falls back
    # to the short incest topic in SECRET_TOPICS_NO_TARGET.
    "secret_incest": "与{target}乱伦",
    "secret_homosexual": "断袖",
    "secret_cannibal": "食人",
    "secret_coup_plotter": "谋逆",
    "secret_adultery": "通奸",
}


# Short forms for templates that need a target the save does not supply.
SECRET_TOPICS_NO_TARGET = {
    "secret_murder": "谋害人命",
    "secret_murder_attempt": "行刺未遂",
    "secret_lover": "与人私通",
    "secret_incest": "乱伦",
}

# Lineage secrets with no determinable biological father (that slot is left out).
SECRET_TOPICS_NO_FATHER = {
    "secret_unmarried_illegitimate_child": "所出{target}血脉存疑",
    "secret_disputed_heritage": "所生{target}血统有争",
}

# Predicate-type secret topics: the topic is already a verb phrase (an affair, a killing, a
# witch's rite), so the "{owner} has a secret: {topic}" frame would read badly and these are
# used directly as the predicate. Noun-type topics (exam cheating, disputed lineage,
# same-sex relations…) keep the "has a secret" frame, which they need.
SECRET_PREDICATE_TYPES = frozenset({
    "secret_lover", "secret_incest", "secret_murder", "secret_murder_attempt",
    "secret_witch", "secret_embezzler", "secret_siphoned_treasury",
    "secret_adultery", "secret_coup_plotter", "secret_cannibal",
    # The exam-cheating topic is itself a complete predicate phrase (it names the exam
    # and the cheating act), so it belongs in this set too.
    "secret_exam_cheater",
})


def secret_topic_is_predicate(tp):
    """Whether this secret topic can stand as the predicate itself."""
    return str(tp or "") in SECRET_PREDICATE_TYPES


# Action-type death causes → agent patterns (raw reason key → verb). With a
# killer/executor/opponent on record the agent goes straight into the sentence instead of a
# separate "the killer was…" tail; battlefield, accident and illness deaths name no one.
# This is the insider wording (assassin board), not what the world saw: the public version
# of `death_mysterious` is the game's mysterious-death text, and naming the killer depends on
# the save flag `dead_data.killer_known` (facts.Facts.killer_is_public).
DEATH_KILLER_VERB = {  # agent = the killer, worded in the passive
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


DEATH_EXECUTOR_VERB = {  # agent = the executor, worded in the passive
    "death_execution": "处决",
    "death_punishment": "处决",
    "death_hostage_execution": "处决",
    "death_execution_blood_eagle": "处决",
    "death_crucified": "钉上十字架",
    "death_crucified_by_mob": "钉上十字架",
    "death_burned_witch": "烧死在火刑柱上",
}


DEATH_OPPONENT_VERB = {  # agent = the opponent; "died duelling with X"
    "death_duel": "决斗",
    "death_fight": "斗殴",
    "death_fight_killer": "斗殴",
    "death_contest_duel_accident": "决斗",
    "death_contest_wrestling_accident": "角力",
}


DEATH_AGENT_TAIL = {  # causes that carry their own manner; the agent gets its own clause
    "death_head_ripped_off": "凶手",   # e.g. head ripped off, the killer being XXX
    "death_eradicated": "行刑者",      # e.g. executed with the whole house, the executor being XXX
}


# Execution methods: the save does not record which one the executor chose (the victim's
# reason key is always `death_execution`). Available methods are approximated from the
# executor's state in the biography's melt/cache using the `send_option` conditions of
# `execute_prisoner_interaction` (common/character_interactions/00_prison_interactions.txt),
# then one is picked by a stable hash of (executor, victim, death date), so executions vary
# while a re-run does not drift. Order is the game UI order.
EXECUTION_OPTIONS = (
    ("beheaded",   "斩首"),                     # EXECUTION_BEHEADED
    ("devour",     "砍头后吃掉"),               # EXECUTION_DEVOUR
    ("burned",     "烧死"),                     # EXECUTION_BURNED
    ("sacrifice",  "献祭给神灵"),               # EXECUTION_SACRIFICE
    ("kennel",     "处以犬决"),                 # EXECUTION_KENNEL
    ("provisions", "做成神秘的肉充作口粮"),     # EXECUTION_PROVISIONS
)

# House purge only; not part of the EXECUTION_OPTIONS random pool.
EXECUTION_PURGE = ("purge", "连坐处死")
# Bone-proven eating: the mod's `devour_single_character_effect` sets
# `death = { reason = death_execution }` without going through the execution interaction,
# but shares the reason key and so fell into the random pool above. Every victim leaves a
# bone object named after him (`devour_bone_visual`, its recipient at creation being the
# eater), so the method is proven by the save.
EXECUTION_DEVOUR_BONE = ("devour_bone", "吃掉")

EXECUTION_ORDER = {k: i for i, (k, _v) in enumerate(EXECUTION_OPTIONS)}


# Overview stat labels (memory type → label; death records use another table). Only
# dramatically meaningful types are counted, so the overview block can state its counts
# directly (rivalries this decade, murders, bereavements, …).
STATS_LABEL = {
    "became_rivals": "结仇", "became_grudge": "结怨", "became_nemesis": "结为死敌",
    "child_born": "添丁", "first_born": "添丁", "twins_born": "添丁",
    "child_premature": "夭折", "child_stillborn": "夭折",
    "successful_murder": "谋杀",
    "had_sex": "私通", "became_lovers": "私通",
    # Spousal intimacy has its own tier; the overview does not count it as an affair.
    "had_sex_spouse": "夫妻之情", "became_lovers_spouse": "夫妻之情",
    "relative_died": "丧亲", "spouse_died": "丧偶", "friend_died": "丧友",
    "rival_died": "仇人死亡",
    "married": "成婚", "broke_up_lovers": "分手",
    "imprisoned": "被囚", "imprisoned_other": "囚禁他人",
    # Escape is its own tier: unlike imprisonment it is a voluntary break-out.
    "escaped_from_prison_memory": "越狱",
    "offensive_war": "开战", "defensive_war": "应战",
    "war_won": "获胜", "war_lost": "战败",
    "battle_won_memory": "取胜", "battle_lost_memory": "失利",
    "faith_changed": "改信",
    # Only three coronation keys are counted; counting every `witnessed_*` would blow
    # the overview up.
    "held_a_coronation_memory": "受冕",
    "crowned_by_hof_memory": "受冕",
    "witnessed_a_coronation_memory": "见证加冕",
}


DEATH_STAT_LABEL = {
    "谋害人命": "谋杀", "丧亲之恸": "丧亲", "丧偶之痛": "丧偶",
    "丧友之恸": "丧友", "仇人死亡": "仇人死亡",
}

# Trait category words: `category` in game `common/traits/*.txt` → Chinese. The empty
# key covers innate traits the game gives no category (beauty_*/intellect_*/physique_*/dwarf…).
TRAIT_GROUP_WORDS = {
    "personality": "性情", "education": "才具", "lifestyle": "阅历",
    "commander": "将略", "fame": "名声", "health": "体况",
    "childhood": "幼性", "court_type": "宫廷", "": "禀赋",
}


def hook_type_kept(tp):
    """Whether a hook type reaches the fact layer: whitelist, plus any `strong_` type
    that is not a generic favor (see FACT_WORDING["hook_keep_exact"])."""
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


# Two data sources for release reasons; `cache_lib._latch_prison_manners` latches them per
# archive and `facts.Facts.release_manner` reads them back (the key sets of its
# `_PRISON_MANNER_MODS` / `_PRISON_KIND_WORD` must match the tables here).
# ① release opinion modifiers: the save carries `start_date` to the day, decaying over 10
#    years and vanishing with the holder's death;
# ② ransom/favor hooks: outside the `hook_type_kept` whitelist (so they never reach the
#    secret board), used only for the release reason; expiry = creation date + 10 years.
PRISON_MANNER_OPINION_MODS = frozenset({
    "released_from_prison", "merciful_opinion", "ransomed_from_prison",
    "demanded_my_conversion_opinion", "compelled_me_to_convert_opinion",
    "demanded_hook", "demanded_claim_renouncement", "banished_me",
    "demanded_recruitment", "demanded_taking_vows",
})
PRISON_MANNER_HOOK_TYPES = frozenset({"favor_hook", "indebted_hook"})
