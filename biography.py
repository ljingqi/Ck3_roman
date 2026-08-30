# -*- coding: utf-8 -*-
"""杂志式人物传记生成器 (biography.py)
====================================
仿 D:\\Journal\\magazine.py 的生成流程, 为 CK3 玩家角色写**五篇纪传体传记**:

  ① 总纲 (1次调用, 400~600字)      —— 相当于杂志导言, 总览一生 + 预告五篇
  ② 五篇文章首段 (5次并发)         —— 每篇开篇板块, 立起人物与场景
  ③ 每篇中段+尾段 (10次并发)       —— 纪事 + 「太史公曰」评点
  ④ 组装为 Markdown

五篇文章 (纪传体, 仿《史记》):
  1. 《本纪·<主角>》  人物生平
  2. 《列传·<好友>》  好友传记 (无结友记忆时取最紧密同僚)
  3. 《列传·<仇人>》  仇人传记 (结仇记忆的对手)
  4. 《家室列传》     妻室子女 (前妻/正妻/子女)
  5. 《朝局风云录》   朝局官制沉浮 (帝位更替/登位/失土/囚狱等朝局大事)

铁律: 提示词只含 facts.py 渲染的**干净中文事实**, 不含任何内部 id/键/英文枚举。
"""
import datetime
import os
import re
from concurrent.futures import ThreadPoolExecutor

import llm
import cache_lib as cl
import facts as F

# ---------------------------------------------------------------------------
# 写作规则 (system 静态内容) — v5 双文风
# ---------------------------------------------------------------------------

# 文风: east=中国式纪传体 (《史记》), west=西式传记 (普鲁塔克《名人传》体例)
STYLE_RULES = {
    "east": {
        "jizhuanti": (
            "「纪传体」笔法: 仿《史记》纪传体——以人物为中心, 按时间次序叙其一生, "
            "客观叙事, 夹叙夹议, 善用细节、对话与场景铺陈; "
            "文章末尾以「太史公曰」作史家评点收束。"
        ),
        "tail_title": "评曰·太史公曰",
        "tail_req": "总评其一生的功过得失与性格命运, 以「太史公曰」收束。",
    },
    "west": {
        "jizhuanti": (
            "「传记体」笔法: 仿西方古典传记 (普鲁塔克《名人传》体例)——以人物一生为纲, "
            "穿插轶事、对话与性格细节, 夹叙夹议, 兼作道德评点与命运省思; "
            "文章末尾以「史家按」作评点收束。"
        ),
        "tail_title": "评曰·史家按",
        "tail_req": "总评其一生的品性功过与命运沉浮, 以「史家按」作结。",
    },
}

NONFICTION_RULE = (
    "「非虚构铁律」: 资料给出的人名、地名、日期、数字、事件一律按资料原样书写; "
    "人物的心理、对话、场景、细节在资料允许的范围内合情演绎; "
    "资料未提供的内容简写或略去。"
)

WORLD_FRAME_RULE = (
    "「平行世界规则」: 本传所写世界完全由本提示词资料构成, 与任何真实历史无关; "
    "所有人物、家族、官职、事件、日期、数字一律以资料为准, 资料未提供的视为不存在或未知。"
)

# 各篇文章的板块名 (首段/中段/尾段) — tail 按文风取
SECTION_TITLES = {
    "benji":   {"lead": "开篇·家世与出身", "mid": "纪事·一生大事", "tail": None},
    "friend":  {"lead": "开篇·家世与交游", "mid": "纪事·一生际遇", "tail": None},
    "enemy":   {"lead": "开篇·仇家身世",   "mid": "纪事·一生行迹", "tail": None},
    "jiashi":  {"lead": "开篇·结缡与离异", "mid": "纪事·门庭恩怨", "tail": None},
    "chaoju":  {"lead": "开篇·天下大势",   "mid": "纪事·朝局浮沉", "tail": None},
    # v5 新增
    "assassins": {"lead": "开篇·刀下之魂",
                  "mid": "纪事·诸魂行迹",
                  "mid1": "纪事·诸魂行迹·上",
                  "mid2": "纪事·诸魂行迹·中",
                  "mid3": "纪事·诸魂行迹·下",
                  "tail": None},
    "youxia":  {"lead": "开篇·萍踪浪迹",   "mid": "纪事·辗转行迹", "tail": None},
    "qizu":    {"lead": "开篇·帝胄姻亲",   "mid": "纪事·门第荣枯", "tail": None},
    "qunying": {"lead": "开篇·朝堂群英",   "mid": "纪事·要员浮沉", "tail": None},
    # v9 新增
    "feuds":   {"lead": "开篇·世仇渊薮",   "mid": "纪事·恩怨始末", "tail": None},
    "artifacts": {"lead": "开篇·传家重宝", "mid": "纪事·流转始末", "tail": None},
}

# 板块要求 (按文章, 首段/中段/尾段) — 全部数据驱动, 无战役硬编码
# v14: 各篇补「本篇须写出的核心场景/转折」戏剧引导 (修复方案_菲利普2.md 问题4 修复4,
# 正向表述, 仿 D:\Journal 的 SECTION_DEFS)。
SECTION_REQ = {
    "benji": {
        "lead": "从家世出身写起: 生于何年、家族渊源、族属信仰、性情特质, 立起人物一生基调。",
        "mid": "按时间次序叙述一生大事: 执掌领地或经营营地、受任官职、让土、结仇、家变、再娶等, 以年表资料为限。本篇写出主角的登位与失土时刻、战争与囚狱转折, 把每个关键日期写成戏剧场景。",
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
    # v5 新增
    "assassins": {
        "lead": "写被主角所杀诸人的群像: 各人身份、与主角的恩怨由、死时情状, 以资料为限, 客观平实。",
        "mid": "依死亡先后为序, 为每名死者立一小传: 生平行迹、与主角的交集、死因, 以资料为限。本篇写出死者生前的家世亲缘与婚恋际遇, 再写其死时情状。",
        "mid1": "依死亡先后为序, 为这一时期 (最早所诛) 的每名死者立一小传: 生平行迹、与主角的交集、死因, 以资料为限。本篇写出死者生前的家世亲缘与婚恋际遇, 再写其死时情状。",
        "mid2": "依死亡先后为序, 为这一时期 (中期所诛) 的每名死者立一小传: 生平行迹、与主角的交集、死因, 以资料为限。本篇写出死者生前的家世亲缘与婚恋际遇, 再写其死时情状。",
        "mid3": "依死亡先后为序, 为这一时期 (暮年所诛) 的每名死者立一小传: 生平行迹、与主角的交集、死因, 以资料为限。本篇写出死者生前的家世亲缘与婚恋际遇, 再写其死时情状。",
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
    # v9 新增
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
}

# 朝局类记忆类型 (朝局风云录用)
POLITICAL_TYPES = {
    "ascended_throne_memory", "lost_title_memory", "imprisoned",
    "released_from_prison_memory", "became_rivals", "became_grudge",
    "became_nemesis", "stopped_being_rivals", "offensive_war",
    "defensive_war", "war_won", "war_lost", "joined_allys_war",
    "battle_won_memory", "battle_lost_memory",
}


# ---------------------------------------------------------------------------
# 主角/好友/仇人/家室 选择
# ---------------------------------------------------------------------------

def _friend_types():
    return {"became_friends", "became_soulmates", "became_blood_brother"}


def _enemy_types():
    return {"became_rivals", "became_grudge", "became_nemesis"}


def _is_dead(cache, cid):
    """该角色是否已死 (缓存有死亡记录)。"""
    return bool((cache.get("characters") or {}).get(str(cid), {}).get("death"))


def _relation_dates(cache, types):
    """{cid: 最早与主角结友/结仇日期} — 双通道 (v13):
    ① 他人记忆 (participants 含主角 id);
    ② 主角自身记忆 (CK3 结友/结仇记忆挂在主角名下, participants 只存对方 id)。
    修: 旧实现只扫①, 主角自己的结友/结仇全漏 (富兰克林 884/925/930 三次结友
    被漏检 → 好友列传选成零关系路人)。"""
    pid = cache.get("player_id")
    out = {}
    if pid is None:
        return out

    def add(cid, d):
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return
        if cid == pid:
            return
        dk = cl.date_key(d or "9999.9.9")
        if cid not in out or dk < cl.date_key(out[cid]):
            out[cid] = d

    # ① 他人记忆
    for cid, rec in (cache.get("characters") or {}).items():
        for mem in rec.get("memories") or []:
            if mem.get("type") not in types:
                continue
            parts = mem.get("participants") or {}
            if any(isinstance(v, int) and v == pid for v in parts.values()):
                add(cid, mem.get("creation_date"))
    # ② 主角自身记忆
    prec = (cache.get("characters") or {}).get(str(pid)) or {}
    for mem in prec.get("memories") or []:
        if mem.get("type") not in types:
            continue
        for v in (mem.get("participants") or {}).values():
            if isinstance(v, int):
                add(v, mem.get("creation_date"))
    return out


def _select_friend(cache):
    """好友: 与主角结友/灵魂伴侣/血盟者中, 在世优先 + 结友最早;
    排除家人 (妻妾/子女/兄弟姊妹 — 手足之情归家室列传)。
    全部已死时回退最早结友者; 无真好友返回 None (由 _pick_friend 走同朝共事者代打)。"""
    pid = cache.get("player_id")
    if pid is None:
        return None
    fam = _family_ids(cache)
    dates = {c: d for c, d in _relation_dates(cache, _friend_types()).items()
             if c not in fam}
    if not dates:
        return None
    alive = {c: d for c, d in dates.items() if not _is_dead(cache, c)}
    pool = alive or dates  # 全部已死时回退最早结友者
    return min(pool, key=lambda c: cl.date_key(pool[c]))


def _select_fallback_friend(cache):
    """无真好友时 (v13): 同朝共事者 (宫廷任官/朝局事件参与者) 中记忆最多者,
    在世优先; 提示词另行注明「无结友记录, 以同朝共事者代之」。"""
    pid = cache.get("player_id")
    if pid is None:
        return None
    fam = _family_ids(cache)
    enemies = _select_enemies(cache)
    candidates = set()
    for h in cache.get("court_positions") or []:
        for p in h.get("positions") or []:
            if isinstance(p.get("employee"), int):
                candidates.add(p["employee"])
    for cid, rec in (cache.get("characters") or {}).items():
        for mem in rec.get("memories") or []:
            if mem.get("type") in POLITICAL_TYPES:
                for v in (mem.get("participants") or {}).values():
                    if isinstance(v, int) and v != pid:
                        candidates.add(v)
    best, best_score = None, -1
    for cid in candidates:
        cid = int(cid)
        if cid == pid or cid in fam or cid in enemies:
            continue
        if _is_dead(cache, cid):
            continue
        n = len((cache.get("characters") or {}).get(str(cid), {}).get("memories") or [])
        if n > best_score:
            best, best_score = cid, n
    return best


def _pick_friend(cache):
    """好友选择 (v13): 真好友 → 无则同朝共事者代打。返回 (cid, is_fallback)。"""
    f = _select_friend(cache)
    if f is not None:
        return f, False
    return _select_fallback_friend(cache), True


def _enemy_dates(cache):
    """{cid: 最早与主角结仇/结怨/死敌日期} (含死者, 双通道, 见 _relation_dates)。"""
    return _relation_dates(cache, _enemy_types())


def _select_enemies(cache):
    """所有与主角结仇/结怨/死敌的对手 id 集合。"""
    return set(_enemy_dates(cache))


ENEMY_MIN_MEMORIES = 5  # v11: 仇人候选池记忆数门槛 (素材太少写不出列传)


def _select_primary_enemy(cache):
    """主仇人 (v11): 与主角结仇/结怨/死敌的对手中, 记忆数 >5 者才入候选池
    (素材不足的早期路人仇人如卡托内只有 1 条记忆, 列传只能靠臆测充数);
    池内按原规则 (在世优先、结怨最早); 池空时回退原逻辑。"""
    dates = _enemy_dates(cache)
    if not dates:
        return None
    rich = {c: d for c, d in dates.items()
            if len((cache.get("characters") or {}).get(str(c), {}).get("memories") or [])
            > ENEMY_MIN_MEMORIES}
    pool = rich or dates  # 池空回退全部
    alive = {c: d for c, d in pool.items() if not _is_dead(cache, c)}
    pick = alive or pool
    return min(pick, key=lambda c: cl.date_key(pick[c]))


def _family_ids(cache):
    """主角家人 id 集 (妻室/前妻/子女/兄弟姊妹 — v13 加同胞: 手足归家室列传,
    不入好友列传)。"""
    pid = cache.get("player_id")
    if pid is None:
        return set()
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    out = set()
    for key in ("primary_spouse", "spouse", "former_spouses", "child", "siblings"):
        for x in (rec.get("family") or {}).get(key) or []:
            out.add(int(x))
    return out


def _relation_reasons(facts, cache, cid, types):
    """结友/结仇缘由: 主角与该角色的关系记忆 → 干净中文句 (v13)。
    主角自身记忆为准, 对方记忆兜底, 去重。"""
    pid = cache.get("player_id")
    out = []
    seen = set()
    fi = facts.get("_facts")  # Facts 实例 (渲染记忆句用)

    def add(s):
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    prec = (cache.get("characters") or {}).get(str(pid)) or {}
    for mem in prec.get("memories") or []:
        if mem.get("type") not in types:
            continue
        parts = mem.get("participants") or {}
        if any(isinstance(v, int) and v == cid for v in parts.values()):
            add(F._mem_sentence(fi, pid, mem))
    crec = (cache.get("characters") or {}).get(str(cid)) or {}
    for mem in crec.get("memories") or []:
        if mem.get("type") not in types:
            continue
        parts = mem.get("participants") or {}
        if any(isinstance(v, int) and v == pid for v in parts.values()):
            add(F._mem_sentence(fi, cid, mem))
    return out


# ---------------------------------------------------------------------------
# 事实块渲染 (只输出干净中文)
# ---------------------------------------------------------------------------

def _house_text(facts, p=None):
    """家族文本 (v14 自然语言): 宗族名 + 分家 (藤原氏（北家）);
    无分家时只给宗族名 (菲利普 / 边氏)。facts 缺失时回退 p。"""
    p = p or {}
    h = (facts or {}).get("house") or p.get("house") or ""
    b = (facts or {}).get("house_branch") or p.get("house_branch") or ""
    if h and b:
        return f"{h}（{b}）"
    return h


def _profile_lines(facts, cid=None):
    """主角或某角色的档案 → 中文行列表。cid=None 时用主角。"""
    if cid is None:
        p = facts["protagonist"]
    else:
        p = (facts["characters"].get(str(cid)) or {})
    lines = []
    if p.get("patronym"):
        # 父名制文化: 名·父名 (富兰克林·崔佛松); 父名替代家族名
        lines.append(f"姓名：{p.get('name_zh') or p.get('name')}·{p['patronym']}")
    elif p.get("name"):
        lines.append(f"姓名：{p['name']}")
    if p.get("office"):
        lines.append(f"官职：{p['office']}")
    if p.get("prince"):
        lines.append(f"称号：{p['prince']}")
    if p.get("house"):
        lines.append(f"家族：{_house_text(None, p)}")
    # v7: 家族家训
    if p.get("motto"):
        lines.append(f"家训：{p['motto']}")
    if p.get("birth"):
        lines.append(f"生于{p['birth']}")
    if p.get("culture"):
        lines.append(f"族属：{p['culture']}")
    if p.get("faith"):
        lines.append(f"信仰：{p['faith']}")
    if p.get("traits"):
        lines.append(f"为人{p['traits']}")
    if p.get("trait_history"):
        lines.append(f"特质履历：{p['trait_history']}")
    if p.get("government"):
        lines.append(f"政体：{p['government']}")
    # v7: 主角宫廷/营地官职 (最新一年) 与该角色在主角处所任官职
    if p.get("court_positions"):
        lines.append(f"宫廷官职：{p['court_positions']}")
    if p.get("court_position"):
        lines.append(f"在主角处任{p['court_position']}")
    # 无地冒险者: 营地
    if p.get("landless"):
        if p.get("camp_name"):
            lines.append(f"营地：{p['camp_name']}")
        if p.get("camp_county"):
            bits = [f"现驻{p['camp_county']}"]
            if p.get("camp_county_holder"):
                bits.append(f"{p['camp_county_holder']}执掌")
            if p.get("camp_liege_chain"):
                bits.append(f"其上为{p['camp_liege_chain']}")
            if p.get("camp_top_liege"):
                bits.append(f"最高领主为{p['camp_top_liege']}")
            lines.append("，".join(bits) + "。")
        if p.get("camp_laws"):
            lines.append(f"营规：{p['camp_laws']}")
        if p.get("camp_strength"):
            lines.append(f"营力{p['camp_strength']}")
    # 有地领主
    if p.get("ruler_since"):
        lines.append(f"{p['ruler_since']}起执掌一方")
    if p.get("domain"):
        cap = f"；治所{p['capital']}" if p.get("capital") else ""
        lines.append(f"直辖{p.get('domain_count', '')}地：{p['domain']}{cap}")
    if p.get("vassal_count") is not None:
        lines.append(f"封臣{p['vassal_count']}人")
    if p.get("council"):
        lines.append(p["council"])
    if p.get("spouses"):
        lines.append(f"妻室：{p['spouses']}")
    if p.get("former_spouses"):
        lines.append(f"前妻：{p['former_spouses']}")
    # v8: 妾 (正向 concubine + 反向 concubinist 合并)
    if p.get("concubines"):
        lines.append(f"妾：{p['concubines']}")
    if p.get("former_concubines"):
        lines.append(f"前妾：{p['former_concubines']}")
    if p.get("children"):
        lines.append(f"子女：{p['children']}")
    if p.get("father"):
        lines.append(f"父：{p['father']}")
    if p.get("mother"):
        lines.append(f"母：{p['mother']}")
    # v5: 真正父亲 (私生子场景, 与法理父不同才写)
    if p.get("real_father") and p.get("real_father") != p.get("father"):
        lines.append(f"实父：{p['real_father']}")
    # v5: 自定义角色 (无谱系) — 用通用事实覆盖父母描写
    if p.get("custom_start"):
        lines.append("先世：无考（出身自定，史无可考，无父母谱系）")
    if p.get("siblings"):
        lines.append(f"兄弟姊妹：{p['siblings']}")
    if p.get("titles_held"):
        lines.append(f"历任：{p['titles_held']}")
    if p.get("status"):
        lines.append(f"现状：{p['status']}")
    if p.get("death"):
        lines.append(p["death"])
    # v13: 戏剧性事实高亮 (一日皇帝/短命皇朝等) — 档案末尾
    if p.get("dramatic_facts"):
        lines.append("戏剧性事件：" + "；".join(p["dramatic_facts"]))
    return lines


def _subject_facts(facts, cid):
    """某角色(好友/仇人)的档案+事件。"""
    p = facts["characters"].get(str(cid)) or {}
    lines = _profile_lines(facts, cid)
    events = p.get("events") or []
    return lines, events


def _timeline_texts(facts, names=None, types=None):
    """时间线文本: 按人名或事件类型过滤 (均不含 id)。"""
    out = []
    for e in facts["timeline"]:
        if types and e["type"] not in types:
            continue
        if names and not any(n and n in e["text"] for n in names):
            continue
        out.append(e["text"])
    return out


def _render_block(title, lines):
    """事实块 → 文本 (只收非空行)。"""
    body = [x for x in lines if x]
    if not body:
        return ""
    return f"{title}\n" + "\n".join(body)


# v14: 刺客列传新口径 (用户定稿) — 死者名带官职 (「唐皇帝李漼」),
# 只传 亲缘 (父/母/妻/妾) + 婚恋记忆 (成婚/相恋/分手/丧偶), 其余生前经历
# (登位/战争/科考等) 从略 — 研究_戏剧模块化.md 7.3 实测: 46 死者 324 条记忆
# 婚恋类仅 30 条 (9%), 裁掉 294 条与「刀下之魂」叙事无关的杂事。
_MARRIAGE_TYPES = {
    "married", "grand_wedding_completed_guest", "broke_up_lovers",
    "became_lovers", "had_sex", "spouse_died", "divorced",
}


def _assassin_kill_lines(facts, cache, k):
    """一名死者的新口径档案行: 官职名 + 死句 + 亲缘 + 婚恋记忆。
    返回 ['死者：唐皇帝李漼（殁于878年4月9日，被处决，行刑者为崔佛·菲利普。）', …]。"""
    lines = []
    nm = k["name"]
    off = k.get("office") or ""
    disp = f"{off}{nm}" if off else nm
    db = k.get("death") or "（死因不详）"
    if db.startswith(nm + "殁于"):
        db = "殁于" + db[len(nm) + 2:]
    lines.append(f"死者：{disp}（{db}）")
    # 亲缘: 父/母/妻/妾 (从缓存 family 取)
    fam = ((cache.get("characters") or {}).get(str(k.get("id"))) or {}).get("family") or {}
    bits = []
    seen_bits = set()
    for x in (fam.get("father") or []):
        bits.append(f"父{_name_or(facts, cache, x)}")
    for x in (fam.get("mother") or []):
        bits.append(f"母{_name_or(facts, cache, x)}")
    for key, label in (("primary_spouse", "妻"), ("spouse", "妻"),
                       ("former_spouses", "前妻"), ("concubine", "妾")):
        for x in (fam.get(key) or []):
            b = f"{label}{_name_or(facts, cache, x)}"
            if b not in seen_bits:
                seen_bits.add(b)
                bits.append(b)
    if bits:
        lines.append("亲缘：" + "、".join(bits))
    # 婚恋记忆: 只收婚恋类 (过滤 k["events"], 其文本带日期前缀)
    mar = [e for e in (k.get("events") or [])
           if any(m in e for m in ("成婚", "相恋", "私情", "分手", "丧偶", "离婚"))]
    if mar:
        lines.append("婚恋：")
        lines.extend("  " + e for e in mar)
    return lines


def _name_or(facts, cache, cid):
    """角色名 (档案有则用, 否则从缓存原始名取, 不再回退「角色N」)。
    亲缘未必在相关集 (死者父母/配偶多为路人), 直接查缓存 characters。"""
    try:
        p = (facts.get("characters") or {}).get(str(cid)) or {}
        if p.get("name"):
            return p["name"]
    except Exception:
        pass
    try:
        r = ((cache.get("characters") or {}).get(str(cid)) or {})
        nm = r.get("name_zh") or r.get("name_full") or ""
        if nm:
            return nm
    except Exception:
        pass
    return f"角色{cid}"


def _article_facts(facts, cache, key, section=None):
    """按文章取事实文本块 dict: {块名: 文本}。
    v11: 刺客列传按板块取料 — 开篇给压缩名录 (群像总览), 各纪事给对应时段切片。"""
    pid = facts.get("player_id")
    pname = (facts["protagonist"] or {}).get("name") or ""
    blocks = {}
    if key == "benji":
        blocks["人物档案"] = "\n".join(_profile_lines(facts))
        tl = _timeline_texts(facts)
        blocks["大事年表"] = "\n".join(tl) if tl else "（无重大事件记录）"
    elif key in ("friend", "enemy"):
        cid = (_pick_friend(cache)[0] if key == "friend"
               else _select_primary_enemy(cache))
        if cid is not None:
            lines, events = _subject_facts(facts, cid)
            subj_name = (facts["characters"].get(str(cid)) or {}).get("name") or ""
            # 传主档案置顶: 本篇文章以传主为唯一叙述中心
            blocks["传主档案"] = "\n".join(lines)
            blocks["传主行迹"] = "\n".join(events) if events else "（无行迹记录）"
            tl = _timeline_texts(facts, names=[pname, subj_name])
            if tl:
                blocks["相关年表"] = "\n".join(tl)
            # v13: 结友/结仇缘由 (双通道修复后必有记忆; 兜底同朝共事者给说明)
            if key == "friend":
                fcid, is_fallback = _pick_friend(cache)
                if cid == fcid and is_fallback:
                    blocks["说明"] = ("（传主与主角无结友记忆，本传按同朝共事之谊立传，"
                                      "以传主生平为主。）")
                else:
                    rs = _relation_reasons(facts, cache, cid, _friend_types())
                    if rs:
                        blocks["结友缘由"] = "；".join(rs)
            else:
                rs = _relation_reasons(facts, cache, cid, _enemy_types())
                if rs:
                    blocks["结仇缘由"] = "；".join(rs)
    elif key == "jiashi":
        blocks["人物档案"] = "\n".join(_profile_lines(facts))
        fam_lines = []
        fam_names = []
        for cid in sorted(_family_ids(cache)):
            p = facts["characters"].get(str(cid))
            if not p or not p.get("name"):
                continue
            fam_names.append(p["name"])
            fam_lines.append("· ".join(x for x in _profile_lines(facts, cid)))
            ev = p.get("events") or []
            if ev:
                fam_lines.append("  " + "\n  ".join(ev))
        blocks["家室档案"] = "\n".join(fam_lines) if fam_lines else "（无家室档案）"
        tl = _timeline_texts(facts, names=fam_names)
        if tl:
            blocks["相关年表"] = "\n".join(tl)
    elif key == "chaoju":
        blocks["人物档案"] = "\n".join(_profile_lines(facts))
        realm = facts.get("realm") or {}
        dashi = []
        if realm.get("liege_chain"):
            dashi.append(f"主角所处疆域：{realm['liege_chain']}")
        # v13: 天下大势只收相关高位更替 (上位链 + 相关角色曾任), 已剔全球噪声;
        # 上限 30 行防膨胀
        for hc in (realm.get("holder_changes") or [])[:30]:
            dashi.append(hc)
        # v13: 朝廷职司现任 (尚书省六部/御史台/枢密院)
        if realm.get("ministers"):
            dashi.append("朝廷职司：" + "、".join(realm["ministers"]))
        blocks["天下大势"] = "\n".join(dashi) if dashi else "（无天下大势记录）"
        tl = _timeline_texts(facts, types=POLITICAL_TYPES)
        # 朝局动态: 政治类记忆时间线 + 高位头衔更替
        dyn = list(tl)
        blocks["朝局动态"] = "\n".join(dyn) if dyn else "（无朝局动态记录）"
        # v7: 玩家宫廷/营地官职任免 (逐年数据驱动)
        cp_ch = facts.get("court_position_changes") or []
        if cp_ch:
            blocks["官职任免"] = "\n".join(cp_ch)
        # 要员名录: 主角相关角色 (家人/好友/仇人/宫廷任官) 中有政治类记忆或历任高位头衔者
        # (剔除路人; 截断 60 名防提示词膨胀)
        names = []
        related = set()
        for _fid in (_pick_friend(cache)[0], _select_primary_enemy(cache)):
            if _fid is not None:
                related.add(_fid)
        for h in cache.get("court_positions") or []:
            for p in h.get("positions") or []:
                if isinstance(p.get("employee"), int):
                    related.add(p["employee"])
        for cid, rec in (cache.get("characters") or {}).items():
            if len(names) >= 60:
                break
            if int(cid) == pid or int(cid) not in related:
                continue
            prof = facts["characters"].get(cid) or {}
            if not prof.get("name"):
                continue
            if any(m["type"] in POLITICAL_TYPES for m in rec.get("memories") or []) \
                    or prof.get("titles_held"):
                # v13: prof["name"] 已是统一显示名 (名·姓/姓+名/父名), 不再拼家族前缀
                full = prof["name"]
                if full not in names:
                    names.append(full)
        if names:
            blocks["朝中要员"] = "、".join(names)
    # ---- v5 新增文章 ----
    elif key == "assassins":
        blocks["人物档案"] = "\n".join(_profile_lines(facts))
        killed = facts.get("killed") or []
        if killed:
            sec_key = (section or {}).get("key") or ""
            if sec_key == "lead":
                # v11 开篇: 压缩名录 (死者名 + 生卒死因), 供群像总览, 不再整块铺 168 人档案
                parts = []
                for k in killed:
                    nm = k["name"]
                    off = k.get("office") or ""
                    disp = f"{off}{nm}" if off else nm
                    db = k.get("death") or ""
                    if db.startswith(nm + "殁于"):
                        db = "殁于" + db[len(nm) + 2:]  # 去掉「名+殁于」前缀
                    parts.append(f"死者：{disp}（{db}）" if db and db != "（死因不详）"
                                 else f"死者：{disp}")
                blocks["刀下诸魂"] = "\n".join(parts)
            else:
                # 各纪事: 按时段切片给完整档案 (v14 新口径: 官职名+亲缘+婚恋)
                sl = (section or {}).get("slice")
                picked = killed[sl[0]:sl[1]] if sl else killed
                parts = ["\n".join(_assassin_kill_lines(facts, cache, k)) for k in picked]
                blocks["刀下诸魂"] = "\n\n".join(parts)
        else:
            blocks["刀下诸魂"] = "（无刀下诸魂记录）"
    elif key == "youxia":
        blocks["人物档案"] = "\n".join(_profile_lines(facts))
        wander = facts.get("wandering") or []
        if wander:
            blocks["行纪"] = "\n".join(wander)
        else:
            blocks["行纪"] = "（无行纪记录）"
    elif key == "qizu":
        blocks["人物档案"] = "\n".join(_profile_lines(facts))
        imp = facts.get("imperial_spouses") or []
        if imp:
            parts = []
            for e in imp:
                lines = [f"妻族：{e['name']}"]
                if e.get("reasons"):
                    lines.append("门第：" + "、".join(e["reasons"]))
                prof = facts["characters"].get(str(e["id"])) or {}
                for x in _profile_lines(facts, e["id"]):
                    if not x.startswith("姓名") and not x.startswith("家族"):
                        lines.append(x)
                ev = prof.get("events") or []
                if ev:
                    lines.append("经历：")
                    lines.extend("  " + s for s in ev)
                parts.append("\n".join(lines))
            blocks["帝胄姻亲"] = "\n\n".join(parts)
        else:
            blocks["帝胄姻亲"] = "（无帝胄姻亲记录）"
    elif key == "qunying":
        blocks["人物档案"] = "\n".join(_profile_lines(facts))
        lum = facts.get("luminaries") or []
        if lum:
            blocks["朝堂群英"] = "、".join(lum)
        else:
            blocks["朝堂群英"] = "（无要员名录）"
        tl = _timeline_texts(facts, types=POLITICAL_TYPES)
        blocks["朝局动态"] = "\n".join(tl) if tl else "（无朝局动态记录）"
    # ---- v9 新增文章 ----
    elif key == "feuds":
        blocks["人物档案"] = "\n".join(_profile_lines(facts))
        feuds = facts.get("house_feuds") or []
        if feuds:
            parts = []
            for fd in feuds:
                parts.append(f"家族：{fd['house']}（关系：{fd['level']}）")
                if fd.get("events"):
                    parts.append("恩怨史：")
                    parts.extend("  " + e for e in fd["events"])
            blocks["家族恩怨"] = "\n\n".join(parts)
        else:
            blocks["家族恩怨"] = "（无家族恩怨记录）"
    elif key == "artifacts":
        blocks["人物档案"] = "\n".join(_profile_lines(facts))
        arts = facts.get("family_artifacts") or []
        if arts:
            blocks["传家重宝"] = "\n\n".join(arts)
        else:
            blocks["传家重宝"] = "（无传家重宝记录）"
    return blocks


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

def _system_msg(style="east", extra=""):
    rule = STYLE_RULES.get(style, STYLE_RULES["east"])
    return ("你是史官, 撰写传记。\n\n"
            f"{rule['jizhuanti']}\n{NONFICTION_RULE}\n{WORLD_FRAME_RULE}")


def _decade_theme_note(facts):
    """戏剧主题预告 (v14): 数据驱动 Top10 (并列第10名全保留, facts.py
    decade_module_top)。十年传记 (有 as_of) 称「本十年」, 终传/在世称「一生」。
    正向表述指引各篇围绕主题取材。无主题时返回空串。"""
    dm = facts.get("decade_modules") or []
    if not dm:
        return ""
    names = "、".join(m for m, _s in dm)
    label = "本十年" if facts.get("as_of") else "一生"
    return (f"{label}戏剧主题: {names}。"
            "各篇正文围绕这些主题取材，主题相关的事件写出戏剧张力，"
            "资料不足的内容简写或略去。\n\n")


def _shared_facts_block(facts):
    """所有调用共享的事实前缀 (v9 输入缓存优化 + v14 瘦身):
    只留【传主】+【人物档案】+ 主角级事件摘要 (修复方案_菲利普2.md 问题4 修复2:
    全量年表改为按文章取, 不再逐字节重复注入 16 次; 共享前缀仍逐字节一致
    置于每条 user 消息最前, 供 DeepSeek 前缀缓存命中)。
    v11: 删【时期】(起止是快照区间, 不是生卒, 对模型无用);
    卒年自然语言化 (【卒年】931年6月7日，因绊倒坠落而亡——此为终传)。"""
    p = facts["protagonist"]
    name = p.get("name") or "主角"
    # v14: 家族文本含分家 (藤原氏（北家）)
    house = _house_text(facts)
    death = facts.get("player_death")
    if death:
        rz = death.get("reason_zh") or death.get("reason") or "身故"
        life_note = (f"【卒年】{llm.fmt_cn_date(death.get('date'))}，{rz}"
                     "——此为终传")
    elif facts.get("as_of"):
        life_note = f"【现状】在世（截至{llm.fmt_cn_date(facts['as_of'])}）"
    else:
        life_note = "【现状】在世（截至最后一份存档）"
    profile_txt = _render_block("【人物档案】", _profile_lines(facts)) or "（无档案）"
    # v14: 主角级事件摘要 (仅主角名在文本中的事件, 数量小: 十年 50 条 / 1.3K 字符)
    pname = p.get("name") or ""
    own = [e["text"] for e in facts.get("timeline") or []
           if pname and pname in e["text"]]
    own_txt = _render_block("【主角大事摘要】", own) if own else ""
    return (f"【传主】{name}\n【家族】{house}\n{life_note}\n\n"
            f"{profile_txt}"
            + (f"\n\n{own_txt}" if own_txt else ""))


def build_intro_messages(facts, cfg, articles=None):
    """总纲提示词 (共享前缀 + 篇目预告)。v11: 输出头改为 生卒; 明确以「太史公曰」作结。"""
    p = facts["protagonist"]
    name = p.get("name") or "主角"
    house = _house_text(facts)
    style = facts.get("bio_style") or "east"
    rule = STYLE_RULES.get(style, STYLE_RULES["east"])
    birth = p.get("birth") or ""
    death = facts.get("player_death")
    if death:
        span_cn = f"生卒：{birth}–{llm.fmt_cn_date(death.get('date'))}"
    else:
        span_cn = f"生于{birth}" if birth else ""
    sys_msg = (
        "你是史官, 为一位乱世人物修传。\n\n"
        f"{rule['jizhuanti']}\n{NONFICTION_RULE}\n{WORLD_FRAME_RULE}\n\n"
        "撰写传记「总纲」: 概括此人的一生大势, 预告以下各篇文章, "
        "点明其家族与身份。总纲正文控制在400–600字, 以「太史公曰」作结。"
    )
    shared = _shared_facts_block(facts)
    # 文章预告: 用实际文章标题 (好友/仇人姓名已定; v5 支持任意篇数)
    CN_NUMS = "一二三四五六七八九"
    if articles:
        preview = "\n".join(
            f"{CN_NUMS[i]}、《{a['title']}》——{a.get('theme') or a['key']}"
            for i, a in enumerate(articles))
        n_articles = len(articles)
    else:
        preview = (
            f"一、《本纪·{name}》——人物生平\n"
            "二、《列传·好友》——最亲近同僚的一生\n"
            "三、《列传·仇人》——一生劲敌的传记\n"
            "四、《家室列传》——妻室子女的门庭画卷\n"
            "五、《朝局风云录》——朝局官制沉浮"
        )
        n_articles = 5
    user_msg = (
        f"{shared}\n\n"
        f"{_decade_theme_note(facts)}"
        f"本传共{n_articles}篇, 篇目预告:\n{preview}\n\n"
        "输出格式:\n"
        f"# 《{name}传》\n"
        f"家族：{house}｜人物：{name}｜{span_cn}\n\n"
        "总纲正文…（一段至两段）\n\n请据此撰写总纲。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def build_lead_messages(article, facts, cache, intro, cfg):
    """五篇文章的首段提示词 (共享前缀 + 总纲 + 文章专属, 输入缓存友好)。"""
    key = article["key"]
    sec = article["sections"][0]
    title = article["title"]
    style = facts.get("bio_style") or "east"
    rule = STYLE_RULES.get(style, STYLE_RULES["east"])
    blocks = _article_facts(facts, cache, key, sec)
    sys_msg = (
        "你是史官, 撰写传记。\n\n"
        f"{rule['jizhuanti']}\n{NONFICTION_RULE}\n{WORLD_FRAME_RULE}"
    )
    facts_txt = "\n\n".join(_render_block(k, v.split("\n")) for k, v in blocks.items())
    subject_note = ""
    if article.get("subject"):
        subject_note = (
            f"本篇传主为{article['subject']}。全篇以{article['subject']}为唯一叙述中心；"
            f"主角{(facts['protagonist'] or {}).get('name')}的事迹仅在{article['subject']}"
            "与主角交游或结仇的场合出现，传主生平以本篇资料为准。\n\n"
        )
    custom_note = ""
    if key == "benji" and (facts["protagonist"] or {}).get("custom_start"):
        custom_note = (
            "本篇传主为自定义出身，先世无考：资料未载其父母名姓与家世谱系，"
            "开篇以「起于何时何地、如何发迹」为纲书写其出身，"
            "先世父母名姓与事迹以资料载明者为限，未载则省去、以「先世无考」带过。\n\n"
        )
    user_msg = (
        f"{_shared_facts_block(facts)}\n\n"
        f"{_decade_theme_note(facts)}"
        f"【总纲】\n{intro}\n\n"
        + custom_note
        + subject_note
        + f"相关事实:\n{facts_txt}\n\n"
        f"本篇文章标题已定为《{title}》。\n\n"
        f"这是文章的开篇板块《{sec['title']}》。要求: {sec['req']}\n\n"
        f"篇幅要求: 开篇板块正文800–1200字, 立起人物与场景。\n\n"
        "输出格式: 直接输出正文, 正文使用 Markdown, "
        "分2~4个自然段, 段与段之间以空行分隔; 板块标题行由组装侧统一添加。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def build_section_messages(article, section, facts, cache, lead_text, cfg):
    """中段提示词。v11: 不再注入【总纲】全文 (防止每篇复述总纲导致雷同);
    承接开篇以正向表述推进新内容; 无尾段 (太史公曰只留总纲)。"""
    key = article["key"]
    title = article["title"]
    style = facts.get("bio_style") or "east"
    rule = STYLE_RULES.get(style, STYLE_RULES["east"])
    blocks = _article_facts(facts, cache, key, section)
    sys_msg = (
        "你是史官, 撰写传记。\n\n"
        f"{rule['jizhuanti']}\n{NONFICTION_RULE}\n{WORLD_FRAME_RULE}"
    )
    facts_txt = "\n\n".join(_render_block(k, v.split("\n")) for k, v in blocks.items())
    subject_note = ""
    if article.get("subject"):
        subject_note = (
            f"本篇传主为{article['subject']}。全篇以{article['subject']}为唯一叙述中心；"
            f"主角{(facts['protagonist'] or {}).get('name')}的事迹仅在{article['subject']}"
            "与主角交游或结仇的场合出现，传主生平以本篇资料为准。\n\n"
        )
    user_msg = (
        f"{_shared_facts_block(facts)}\n\n"
        f"{_decade_theme_note(facts)}"
        + subject_note
        + f"相关事实:\n{facts_txt}\n\n"
        f"本篇文章标题已定为《{title}》。\n\n"
        f"请撰写板块《{section['title']}》。要求: {section['req']}\n\n"
        f"篇幅要求: 板块正文1200–1800字。\n\n"
        f"本文开篇板块《{article['sections'][0]['title']}》内容(以下为开篇全文):\n"
        f"{lead_text}\n\n"
        f"承接开篇所立人物与场景，以本篇相关事实为素材推进新事件与新细节，"
        f"撰写板块《{section['title']}》。\n\n"
        "输出格式: 直接输出正文, 正文使用 Markdown。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


# ---------------------------------------------------------------------------
# 文本规范化与组装
# ---------------------------------------------------------------------------

_MAG_HEAD_RE = re.compile(r"^#{1,6}\s+")


def _strip_markdown_tables(text):
    """把模型输出的 Markdown 表格行转成自然语言句子 (兜底)。"""
    lines = (text or "").split("\n")
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if (ln.startswith("|")
                and i + 1 < len(lines)
                and re.match(r"^\s*\|[\s:\-|]+\|\s*$", lines[i + 1])):
            headers = [c.strip() for c in ln.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                pairs = []
                for h, v in zip(headers, cells):
                    if not h or not v or v in ("-", "—", "N/A"):
                        continue
                    pairs.append(f"{h}为{v}")
                rows.append("，".join(pairs) if pairs else "、".join(cells))
                i += 1
            if rows:
                out.append("，".join(rows) + "。")
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _normalize_section(text, sec_title, article_title=""):
    """板块正文规范化: 标题统一为 ###, 表格转自然语言, 无标题补 ### 板块名。
    v11: 剥离板块内的「太史公曰/史家按」评点段 (只留总纲的评点, 板块均为客观叙事)。
    v14: 正则剔除模型误输出的重复标题 (不动提示词):
      - 板块标题短版重复: 「### 家世与交游」与板块标题「开篇·家世与交游」去前缀后同名 → 剔;
      - 文章标题混入: 「### 列传·赫罗德加尔·戈迪」与文章标题同名 → 剔;
      - 同一标题出现多次 → 只留第一个。"""
    out = []
    saw = False
    seen_titles = set()
    # 板块标题的短版 (去掉 开篇·/纪事·/评曰· 前缀), 模型常误输出短版重复
    short = re.sub(r"^(开篇|纪事|评曰)[··]?", "", sec_title).strip()
    art_plain = re.sub(r"^《|》$", "", article_title or "")
    for raw in (text or "").split("\n"):
        s = raw.strip()
        if not s:
            out.append("")
            continue
        if s.startswith("#"):
            if sec_title in s:
                saw = True
            if re.search(r"太史公曰|史家按", s):
                out.append("")  # 评点标题 (### 太史公曰) 剥离
                continue
            s = re.sub(r"^(#{1,6})\s+", "### ", s)
            head = s.lstrip("# ").strip()
            # v14: 重复标题剔除 (短版/文章标题/重复出现)
            if head == short or (art_plain and head == art_plain) \
                    or head in seen_titles:
                out.append("")
                continue
            seen_titles.add(head)
            out.append(s)
            continue
        # 评点段整段剥离: 「太史公曰：…」/「**太史公曰**」/「史家按：…」(西式)
        stripped = s.lstrip("*# \t")
        if stripped.startswith("太史公曰") or stripped.startswith("史家按"):
            out.append("")  # 用空行占位, 保持段距
            continue
        # 段中评点截断: 保留「太史公曰/史家按」之前的叙述 (只留总纲的评点)
        for marker in ("太史公曰", "史家按"):
            if marker in s:
                s = s.split(marker, 1)[0].rstrip().rstrip("，")
                break
        out.append(s)
    body = _strip_markdown_tables("\n".join(out)).strip()
    body = llm.clean_number_spaces(body)
    # 评点剥离后可能残留孤立空行, 压缩
    body = re.sub(r"\n{3,}", "\n\n", body)
    if not saw:
        body = f"### {sec_title}\n\n{body}"
    return body


def _assemble(facts, intro, leads, sections, articles):
    parts = [f"# 《{facts['protagonist']['name']}传》"]
    p = facts["protagonist"]
    # v14: 家族文本含分家 (藤原氏（北家）)
    house = _house_text(facts)
    death = facts.get("player_death")
    span = ""
    if death:
        span = f"卒于{llm.fmt_cn_date(death.get('date'))}（终传）"
    else:
        cutoff = facts.get("as_of") or facts.get("last_date")
        span = f"截至{llm.fmt_cn_date(cutoff or '?')}"
    parts.append(f"> 家族：{house}｜人物：{p.get('name')}｜{span}")
    parts.append(f"> 存档来源：{' / '.join(facts.get('sources') or [])}（共{len(facts.get('sources') or [])}份快照）")
    parts.append("")
    parts.append(intro.strip())
    for i, a in enumerate(articles, 1):
        parts.append("")
        parts.append("---")
        parts.append("")
        parts.append(f"## {i}、《{a['title']}》")
        parts.append("")
        parts.append(leads[a["key"]])
        for s in a["sections"][1:]:
            parts.append("")
            parts.append(sections[(a["key"], s["key"])])
    # v5: 终传附录 (世系 + 年表, 程序直出, 不经 LLM)
    if death:
        parts.append("")
        parts.append("---")
        parts.append("")
        parts.append(f"## {len(articles) + 1}、终传附录")
        parts.append("")
        parts.append(_appendix_text(facts))
    return "\n".join(parts)


def _appendix_text(facts):
    """终传附录: 世系表 + 大事年表 (纯数据, 由程序渲染, 不调 LLM)。
    - 条目一律用 Markdown 列表 (- ), 年表按 年→月→日 三级缩进;
    - 某月仅 1 条事件时月/日合写 (8月4日 事件), 某年仅 1 条时年/月/日合写 (1067年6月29日 事件);
    - 年表只收与主角相关的事件 (主角或家人姓名出现者), 无关宗亲条目自然略去;
    - 同一事件的多方视角 (如「赵阿足得长子约书亚」/「巴沙尔·冯·大马士革得长子约书亚」,
      「巴沙尔的亲属约书亚亡故」/「约书亚殁于…」) 按 (日期, 事件语义) 去重, 只保留一条;
      死亡记录优先于亲属亡故记忆, 出生事件优先保留主角视角。"""
    lines = []
    gen = facts.get("genealogy") or []
    if gen:
        lines.append("### 世系")
        lines.extend("- " + g for g in gen)
    # 主角 + 家人姓名集
    names = set()
    p = facts["protagonist"] or {}
    pname = p.get("name") or ""
    if pname:
        names.add(pname)
    # 从世系行提取人名 (正妻/侧室/子女/父母/兄弟姊妹 冒号后)
    for ln in gen:
        if "：" in ln:
            for nm in ln.split("：", 1)[1].replace("、", " ").split():
                if nm:
                    names.add(nm)
    # 主角相关事件, 按 (年, 月, 日) → 事件语义键 → (优先级, 文本) 分组去重
    events = [e for e in facts.get("timeline") or []
              if any(n and n in e["text"] for n in names)]
    by_day = {}   # (y, m, d) → {事件键: (优先级, 文本)}
    for e in events:
        # 日期 '1070.4.9' → (1070, 4, 9)
        y, mo, d = 0, 0, 0
        try:
            y, mo, d = (int(x) for x in str(e.get("date")).split(".")[:3])
        except Exception:
            continue
        # 事件文本已带「1070年4月9日，」前缀, 去掉日期前缀只留事件
        body = re.sub(r"^\d+年\d+月\d+日，?", "", e["text"])
        key = _timeline_event_key(body)
        if key is None:
            continue
        cur = by_day.setdefault((y, mo, d), {})
        prio = _timeline_event_priority(body, pname)
        old = cur.get(key)
        if old is None or prio > old[0]:
            cur[key] = (prio, body)
    if by_day:
        lines.append("")
        lines.append("### 大事年表")
        # 预统计每年/每月事件条数 (单条时折叠换行)
        n_year, n_month = {}, {}
        for (y, mo, d), evs in by_day.items():
            n_year[y] = n_year.get(y, 0) + len(evs)
            n_month[(y, mo)] = n_month.get((y, mo), 0) + len(evs)
        last_y, last_mo = None, None
        for (y, mo, d) in sorted(by_day):
            bodies = [b for _, b in sorted(by_day[(y, mo, d)].values(),
                                           key=lambda x: -x[0])]
            if n_year[y] == 1:
                # 全年仅 1 条: 年/月/日合为一行
                for body in bodies:
                    lines.append(f"- {y}年{mo}月{d}日 {body}")
                continue
            if y != last_y:
                lines.append(f"- {y}年")
                last_y = y
                last_mo = None
            if n_month[(y, mo)] == 1:
                # 当月仅 1 条: 月/日合为一行
                for body in bodies:
                    lines.append(f"  - {mo}月{d}日 {body}")
                last_mo = mo
                continue
            if mo != last_mo:
                lines.append(f"  - {mo}月")
                last_mo = mo
            for body in bodies:
                lines.append(f"    - {d}日 {body}")
    return "\n".join(lines)


def _timeline_event_key(body):
    """事件语义键: 同一事件的多方表述归为同键 (日期另行参与)。
    - 亡故: 「X的亲属Y亡故。」/「X的友人Y亡故。」/「X的仇人Y身亡。」/「Y殁于…」→ ('亡', 'Y亡故。')
    - 出生: 「X得长子Y。」/「X添子Y。」/「X得孪生子。」/「X幼子夭折。」→ ('生', 对象)
    - 其余按原文本。"""
    m = re.match(r"^.+?的(?:亲属|友人)(.+亡故。)$", body)
    if m:
        return ("亡", m.group(1))
    m = re.match(r"^.+?的仇人(.+身亡。)$", body)
    if m:
        return ("亡", m.group(1).replace("身亡。", "亡故。"))
    m = re.match(r"^(.+?)殁于\d+年\d+月\d+日", body)
    if m:
        return ("亡", m.group(1) + "亡故。")
    m = re.match(r"^.+?(?:得长子|添子)(.+。)$", body)
    if m:
        return ("生", m.group(1))
    if re.match(r"^.+?得孪生子。$", body):
        return ("生", "孪生子。")
    if re.match(r"^.+?幼子夭折。$", body):
        return ("生", "幼子夭折。")
    if re.match(r"^.+?婴儿夭折。$", body):
        return ("生", "婴儿夭折。")
    return ("事", body)


def _timeline_event_priority(body, pname):
    """同一事件多视角并存时优先保留哪条: 死亡记录 (信息最全) > 亡故记忆 > 其余;
    同层内主角视角 (文本以主角名开头) 优先。"""
    if re.search(r"殁于\d+年\d+月\d+日", body):
        tier = 2
    elif re.search(r"的(?:亲属|友人|仇人).+?(?:亡故|身亡)。$", body):
        tier = 1
    else:
        tier = 0
    return tier * 10 + (1 if pname and body.startswith(pname) else 0)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _assassin_sections(n):
    """刺客列传板块 (v11): 按击杀数动态拆纪事 — <30 拆 1 个纪事, 30–59 拆 2 个,
    ≥60 拆 3 个; 每个纪事按死亡先后等分切片 (防提示词过大吃掉模型注意力)。"""
    if n >= 60:
        mids = ["mid1", "mid2", "mid3"]
    elif n >= 30:
        mids = ["mid1", "mid2"]
    else:
        mids = ["mid"]
    mid_suffix = "本篇正文均为客观叙事，史家评点集中于总纲。"
    secs = [{"key": "lead", "title": SECTION_TITLES["assassins"]["lead"],
             "req": SECTION_REQ["assassins"]["lead"]}]
    chunk = (n + len(mids) - 1) // len(mids)
    for i, k in enumerate(mids):
        lo, hi = i * chunk, min((i + 1) * chunk, n)
        secs.append({"key": k, "title": SECTION_TITLES["assassins"][k],
                     "req": SECTION_REQ["assassins"][k] + mid_suffix,
                     "slice": (lo, hi)})
    return secs


def build_articles(facts, cache, cfg):
    """按 cfg.bio_sections 组装文章列表 (标题含主角/好友/仇人姓名)。
    v5: 动态追加 刺客列传/游侠列传/妻族传/群英录 (依数据条件)。"""
    pid = facts.get("player_id")
    pname = (facts["protagonist"] or {}).get("name") or "主角"
    style = facts.get("bio_style") or "east"
    friend, _f_fallback = _pick_friend(cache)
    enemy = _select_primary_enemy(cache)
    fname = ""
    ename = ""
    if friend is not None:
        fp = facts["characters"].get(str(friend)) or {}
        fname = fp.get("name") or ""
    if enemy is not None:
        ep = facts["characters"].get(str(enemy)) or {}
        ename = ep.get("name") or ""
    sec_keys = [s for s in ("lead", "mid")]  # v11: 尾段 (评曰) 全部删去, 太史公曰只留总纲
    def mk_sections(key):
        titles = SECTION_TITLES.get(key, {})
        defaults = {"lead": "开篇", "mid": "纪事"}
        mid_suffix = "本篇正文均为客观叙事，史家评点集中于总纲。"
        return [{
            "key": sk,
            "title": titles.get(sk) or defaults[sk],
            "req": (SECTION_REQ.get(key, {}).get(sk)
                    or "按传记笔法写作, 以资料为限。")
                   + (mid_suffix if sk != "lead" else ""),
        } for sk in sec_keys]
    articles = [
        {"key": "benji", "title": f"本纪·{pname}", "subject": None,
         "theme": "人物生平", "sections": mk_sections("benji")},
        {"key": "friend", "title": f"列传·{fname or '好友'}", "subject": fname,
         "theme": "好友传记（最亲近同僚的一生）", "sections": mk_sections("friend")},
        {"key": "enemy", "title": f"列传·{ename or '仇人'}", "subject": ename,
         "theme": "仇人传记（一生劲敌）", "sections": mk_sections("enemy")},
        {"key": "jiashi", "title": "家室列传", "subject": None,
         "theme": "妻室子女的门庭画卷", "sections": mk_sections("jiashi")},
        {"key": "chaoju", "title": "朝局风云录", "subject": None,
         "theme": "朝局官制沉浮", "sections": mk_sections("chaoju")},
    ]
    # v9: 家族恩怨录 / 宝物志 — 插在中间 (家室列传之后, 朝局风云录之前)
    if facts.get("house_feuds"):
        articles.insert(4, {"key": "feuds", "title": "家族恩怨录",
                            "subject": None,
                            "theme": "与主角家族关系不和的家族恩怨",
                            "sections": mk_sections("feuds")})
    if facts.get("family_artifacts"):
        articles.insert(5, {"key": "artifacts", "title": "宝物志",
                            "subject": None,
                            "theme": "主角家族所藏重宝的流转历史",
                            "sections": mk_sections("artifacts")})
    # v5: 刺客列传 (主角杀 >5 人); v11: 按击杀数动态拆纪事板块
    # (<30 不拆 1 个纪事; 30–59 拆 2 个; ≥60 拆 3 个; 已剔除 lowborn)
    killed = facts.get("killed") or []
    if len(killed) > 5:
        articles.append({
            "key": "assassins", "title": "刺客列传·刀下诸魂",
            "subject": None, "theme": f"被主角所杀 {len(killed)} 人的合传",
            "sections": _assassin_sections(len(killed))})
    # v5: 游侠列传 (无地冒险者)
    if facts.get("protagonist", {}).get("landless"):
        articles.append({
            "key": "youxia", "title": "游侠列传·行纪",
            "subject": None, "theme": "萍踪浪迹的漂泊行纪",
            "sections": mk_sections("youxia")})
    # v5: 妻族传 (妻妾含公主头衔/中华皇帝之女·姐妹)
    if facts.get("imperial_spouses"):
        articles.append({
            "key": "qizu", "title": "妻族传·帝胄姻亲",
            "subject": None, "theme": "妻族门第 (公主头衔/中华皇帝之女·姐妹)",
            "sections": mk_sections("qizu")})
    # v5: 群英录 (行政制角色)
    if facts.get("protagonist", {}).get("government") and \
            _is_admin(facts):
        articles.append({
            "key": "qunying", "title": "群英录·朝堂要员",
            "subject": None, "theme": "同朝要员的群像",
            "sections": mk_sections("qunying")})
    return articles


def _is_admin(facts):
    """行政制判定: 主角政府为 administrative (行政官制)。"""
    gov = (facts["protagonist"] or {}).get("government") or ""
    return gov in ("行政官制", "administrative_government")


def generate_biography(cache, melt, cfg, out_path=None, decade=None, as_of=None):
    """生成传记 Markdown 并写入 out_path。返回 (md_text, facts, articles)。
    decade: 十年传记序号 (第N个十年), None 表示终传或普通在世传记。
    as_of (v11): 数据截止日期 — 十年传记传十年末, 官职/历任/时间线/朝局按此截断。"""
    names_path = os.path.join(cfg.get("data_dir", ""), "names.json")
    facts = F.build_facts(cache, melt, names_path, as_of=as_of)
    articles = build_articles(facts, cache, cfg)

    intro_cfg = dict(cfg)
    intro_cfg["max_tokens"] = min(cfg.get("max_tokens", 12800), 1500)
    intro = llm.call_deepseek(build_intro_messages(facts, cfg, articles),
                              intro_cfg).strip()
    intro = llm.clean_number_spaces(intro)

    sec_cfg = dict(cfg)
    sec_cfg["max_tokens"] = min(cfg.get("max_tokens", 12800), 4000)

    def _gen_lead(article):
        try:
            msg = build_lead_messages(article, facts, cache, intro, cfg)
            text = llm.call_deepseek(msg, sec_cfg).strip()
            body = _normalize_section(text, article["sections"][0]["title"],
                                      article["title"])
            body = re.sub(r"(?<!\n)\n(?!\n)", "\n\n", body)
            return article["key"], body
        except Exception as e:
            llm.log(f"首段《{article['title']}》生成失败: {e}")
            return (article["key"],
                    f"### {article['sections'][0]['title']}\n\n(本板块生成失败)")

    leads = {}
    with ThreadPoolExecutor(max_workers=len(articles)) as ex:
        futures = [ex.submit(_gen_lead, a) for a in articles]
        for fut in futures:
            k, body = fut.result()
            leads[k] = body

    def _gen_section(article, section):
        try:
            msg = build_section_messages(article, section, facts, cache,
                                         leads[article["key"]], cfg)
            text = llm.call_deepseek(msg, sec_cfg).strip()
            return article["key"], section["key"], _normalize_section(
                text, section["title"], article["title"])
        except Exception as e:
            llm.log(f"板块《{section['title']}》生成失败: {e}")
            return (article["key"], section["key"],
                    f"### {section['title']}\n\n(本板块生成失败)")

    sections = {}
    jobs = [(a, s) for a in articles for s in a["sections"][1:]]
    if jobs:
        with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futures = [ex.submit(_gen_section, a, s) for a, s in jobs]
            for fut in futures:
                ak, sk, body = fut.result()
                sections[(ak, sk)] = body

    md = _assemble(facts, intro, leads, sections, articles)
    # v8: 头部注释带 人物/出生/篇目/十年, 供 htmlview 分组与十年标注
    pp = facts["protagonist"] or {}
    person = pp.get("name") or facts.get("player_name") or ""
    birth = pp.get("birth") or ""
    if decade:
        piece = f"第{decade}个十年传记"
    elif facts.get("player_death"):
        piece = "终传"
    else:
        piece = "传记"
    header = (f"<!-- 数据来源: CK3 年度存档快照 | 家族: {facts.get('house', '')} | "
              f"人物: {person} | 出生: {birth} | 篇目: {piece}"
              + (f" | 十年: {decade}" if decade else "")
              + f" | 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n")
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(header + md.rstrip() + "\n")
        llm.log(f"传记已生成: {out_path}")
    return md, facts, articles
