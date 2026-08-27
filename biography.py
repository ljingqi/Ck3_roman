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
import facts as F

# ---------------------------------------------------------------------------
# 写作规则 (system 静态内容)
# ---------------------------------------------------------------------------

JIZHUANTI_RULE = (
    "「纪传体」笔法: 仿《史记》纪传体——以人物为中心, 按时间次序叙其一生, "
    "客观叙事, 夹叙夹议, 善用细节、对话与场景铺陈; "
    "文章末尾以「太史公曰」作史家评点收束。"
)

NONFICTION_RULE = (
    "「非虚构铁律」: 资料给出的人名、地名、日期、数字、事件一律按资料原样书写; "
    "人物的心理、对话、场景、细节在资料允许的范围内合情演绎; "
    "资料未提供的内容简写或略去。"
)

WORLD_FRAME_RULE = (
    "「平行世界规则」: 本传所写世界完全由本提示词资料构成, 与任何真实历史无关; "
    "所有人物、家族、官职、事件、日期、数字一律以资料为准, 资料未提供的视为不存在或未知。"
)

# 各篇文章的板块名 (首段/中段/尾段)
SECTION_TITLES = {
    "benji":   {"lead": "开篇·家世与出身", "mid": "纪事·一生大事", "tail": "评曰·太史公曰"},
    "friend":  {"lead": "开篇·家世与交游", "mid": "纪事·一生际遇", "tail": "评曰·太史公曰"},
    "enemy":   {"lead": "开篇·仇家身世",   "mid": "纪事·一生行迹", "tail": "评曰·太史公曰"},
    "jiashi":  {"lead": "开篇·结缡与离异", "mid": "纪事·门庭恩怨", "tail": "评曰·太史公曰"},
    "chaoju":  {"lead": "开篇·天下大势",   "mid": "纪事·朝局浮沉", "tail": "评曰·太史公曰"},
}

# 板块要求 (按文章, 首段/中段/尾段) — 全部数据驱动, 无战役硬编码
SECTION_REQ = {
    "benji": {
        "lead": "从家世出身写起: 生于何年、家族渊源、族属信仰、性情特质, 立起人物一生基调。",
        "mid": "按时间次序叙述一生大事: 执掌领地或经营营地、受任官职、让土、结仇、家变、再娶等, 以年表资料为限。",
        "tail": "总评其一生的功过得失与性格命运, 以「太史公曰」收束。",
    },
    "friend": {
        "lead": "写传主与主角的交游渊源: 二人如何相识、同处何朝何地, 传主的家世与出身。",
        "mid": "叙述传主一生际遇: 婚姻、被囚、失土、起复、登位、结友等, 以资料为限。",
        "tail": "评点传主之为人与其命运, 以「太史公曰」收束。",
    },
    "enemy": {
        "lead": "写仇家身世与结仇之由: 传主何许人也, 与主角因何成仇。",
        "mid": "叙述仇家一生行迹: 登位、婚姻、情事、结仇、私情等, 以资料为限, 客观平实叙述。",
        "tail": "评点这段恩怨与传主的命运, 以「太史公曰」收束。",
    },
    "jiashi": {
        "lead": "写主角婚配始末: 结缡、离异、前妻之死、再娶, 立起门庭画卷; 妻族门第 (妻之父兄等显贵亲眷) 若有资料一并铺陈。",
        "mid": "写门庭恩怨: 前妻与仇家之情事、他妇之怨、子女状况, 以资料为限。",
        "tail": "评点家室之兴衰与人物命运, 以「太史公曰」收束。",
    },
    "chaoju": {
        "lead": "写天下大势: 以最高领主或皇帝及其更替为纲, 铺陈本期朝局格局与主角所处疆域, 以资料为限。",
        "mid": "写朝局浮沉: 依朝局动态与要员名录, 叙述登位、失土、囚狱、结仇、战争等朝局大事, 以资料为限。",
        "tail": "评点朝局之得失与人物命运, 以「太史公曰」收束。",
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


def _select_friend(cache):
    """好友: 先找与主角结友/灵魂伴侣/血盟的参与者; 无则取非家人非仇人中
    记忆最多者 (优先有结友记忆者)。返回 cid 或 None。"""
    pid = cache.get("player_id")
    if pid is None:
        return None
    # 1) 结友类记忆直接参与者
    for cid, rec in (cache.get("characters") or {}).items():
        cid = int(cid)
        for mem in rec.get("memories") or []:
            if mem["type"] in _friend_types():
                for v in (mem.get("participants") or {}).values():
                    if isinstance(v, int) and v == pid:
                        return cid
    # 2) 兜底: 排除家人与仇人, 取记忆最多者
    enemies = _select_enemies(cache)
    fam = set()
    prec = (cache.get("characters") or {}).get(str(pid)) or {}
    for ids in (prec.get("family") or {}).values():
        fam.update(int(x) for x in ids)
    best, best_score = None, -1
    for cid, rec in (cache.get("characters") or {}).items():
        cid = int(cid)
        if cid == pid or cid in fam or cid in enemies:
            continue
        n = len(rec.get("memories") or [])
        has_friend = any(m["type"] in _friend_types()
                         for m in rec.get("memories") or [])
        score = n + (10 if has_friend else 0)
        if score > best_score:
            best, best_score = cid, score
    return best


def _select_enemies(cache):
    """所有与主角结仇/结怨/死敌的对手 id 集合。"""
    pid = cache.get("player_id")
    out = set()
    if pid is None:
        return out
    for cid, rec in (cache.get("characters") or {}).items():
        for mem in rec.get("memories") or []:
            if mem["type"] in _enemy_types():
                parts = mem.get("participants") or {}
                for v in parts.values():
                    if isinstance(v, int) and v == pid:
                        out.add(int(cid))
    return out


def _select_primary_enemy(cache):
    """主仇人: 与主角结仇的对手中记忆最多者。"""
    pid = cache.get("player_id")
    enemies = _select_enemies(cache)
    best, best_n = None, -1
    for cid in enemies:
        rec = (cache.get("characters") or {}).get(str(cid)) or {}
        n = len(rec.get("memories") or [])
        if n > best_n:
            best, best_n = cid, n
    return best


def _family_ids(cache):
    """主角家人 id 集 (妻室/前妻/子女)。"""
    pid = cache.get("player_id")
    if pid is None:
        return set()
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    out = set()
    for key in ("primary_spouse", "spouse", "former_spouses", "child"):
        for x in (rec.get("family") or {}).get(key) or []:
            out.add(int(x))
    return out


# ---------------------------------------------------------------------------
# 事实块渲染 (只输出干净中文)
# ---------------------------------------------------------------------------

def _profile_lines(facts, cid=None):
    """主角或某角色的档案 → 中文行列表。cid=None 时用主角。"""
    if cid is None:
        p = facts["protagonist"]
    else:
        p = (facts["characters"].get(str(cid)) or {})
    lines = []
    if p.get("name"):
        lines.append(f"姓名：{p['name']}")
    if p.get("house"):
        lines.append(f"家族：{p['house']}")
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
    if p.get("children"):
        lines.append(f"子女：{p['children']}")
    if p.get("father"):
        lines.append(f"父：{p['father']}")
    if p.get("mother"):
        lines.append(f"母：{p['mother']}")
    if p.get("siblings"):
        lines.append(f"兄弟姊妹：{p['siblings']}")
    if p.get("titles_held"):
        lines.append(f"历任：{p['titles_held']}")
    if p.get("status"):
        lines.append(f"现状：{p['status']}")
    if p.get("death"):
        lines.append(p["death"])
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


def _article_facts(facts, cache, key):
    """按文章取事实文本块 dict: {块名: 文本}。"""
    pid = facts.get("player_id")
    pname = (facts["protagonist"] or {}).get("name") or ""
    blocks = {}
    if key == "benji":
        blocks["人物档案"] = "\n".join(_profile_lines(facts))
        tl = _timeline_texts(facts)
        blocks["大事年表"] = "\n".join(tl) if tl else "（两年间无重大事件记录）"
    elif key in ("friend", "enemy"):
        cid = (_select_friend(cache) if key == "friend"
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
        for hc in (realm.get("holder_changes") or []):
            dashi.append(hc)
        blocks["天下大势"] = "\n".join(dashi) if dashi else "（无天下大势记录）"
        tl = _timeline_texts(facts, types=POLITICAL_TYPES)
        # 朝局动态: 政治类记忆时间线 + 高位头衔更替
        dyn = list(tl)
        blocks["朝局动态"] = "\n".join(dyn) if dyn else "（无朝局动态记录）"
        # 要员名录: 有政治类记忆或历任高位头衔的角色
        names = []
        for cid, rec in (cache.get("characters") or {}).items():
            if int(cid) == pid:
                continue
            prof = facts["characters"].get(cid) or {}
            if not prof.get("name"):
                continue
            if any(m["type"] in POLITICAL_TYPES for m in rec.get("memories") or []) \
                    or prof.get("titles_held"):
                n = prof.get("house") or ""
                nm = prof["name"]
                names.append(f"{n}{nm}" if n and nm and not nm.startswith(n) else nm)
        if names:
            blocks["朝中要员"] = "、".join(names)
    return blocks


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

def _system_msg(extra=""):
    return ("你是史官, 撰写纪传体传记。\n\n"
            f"{JIZHUANTI_RULE}\n{NONFICTION_RULE}\n{WORLD_FRAME_RULE}")


def build_intro_messages(facts, cfg, articles=None):
    """总纲提示词。"""
    p = facts["protagonist"]
    name = p.get("name") or "主角"
    house = facts.get("house") or p.get("house") or ""
    period = facts.get("period") or "?"
    death = facts.get("player_death")
    sys_msg = (
        "你是史官, 为一位乱世人物修传。\n\n"
        f"{JIZHUANTI_RULE}\n{NONFICTION_RULE}\n{WORLD_FRAME_RULE}\n\n"
        "撰写传记「总纲」: 概括此人的一生大势, 预告以下五篇文章, "
        "点明其家族与身份。总纲正文控制在400–600字。"
    )
    life_note = ""
    if death:
        life_note = f"【卒年】{death.get('date')}（{death.get('reason')}）——此为终传"
    else:
        life_note = "【现状】在世（截至最后一份存档）"
    profile_txt = _render_block("【人物档案】", _profile_lines(facts)) or "（无档案）"
    timeline_txt = _render_block("【大事年表】",
                                 _timeline_texts(facts) or ["（无重大事件记录）"])
    # 五篇预告: 用实际文章标题 (好友/仇人姓名已定)
    if articles:
        nums = "一二三四五"
        preview = "\n".join(
            f"{nums[i]}、《{a['title']}》——{a.get('theme') or a['key']}"
            for i, a in enumerate(articles[:5]))
    else:
        preview = (
            f"一、《本纪·{name}》——人物生平\n"
            "二、《列传·好友》——最亲近同僚的一生\n"
            "三、《列传·仇人》——一生劲敌的传记\n"
            "四、《家室列传》——妻室子女的门庭画卷\n"
            "五、《朝局风云录》——朝局官制沉浮"
        )
    user_msg = (
        "本期修传对象:\n"
        f"【传主】{name}\n【家族】{house}\n"
        f"【时期】{period}\n{life_note}\n\n"
        f"五篇文章预告:\n{preview}\n\n"
        "输出格式:\n"
        f"# 《{name}传》\n"
        f"家族：{house}｜人物：{name}｜时期：{period}\n\n"
        "总纲正文…（一段至两段）\n\n"
        "以下为唯一事实依据:\n"
        f"{profile_txt}\n\n{timeline_txt}\n\n请据此撰写总纲。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def build_lead_messages(article, facts, cache, intro, cfg):
    """五篇文章的首段提示词。"""
    key = article["key"]
    sec = article["sections"][0]
    title = article["title"]
    blocks = _article_facts(facts, cache, key)
    sys_msg = (
        "你是史官, 撰写纪传体传记。\n\n"
        f"{JIZHUANTI_RULE}\n{NONFICTION_RULE}\n{WORLD_FRAME_RULE}"
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
        subject_note
        + f"本篇文章标题已定为《{title}》。\n\n"
        f"这是文章的开篇板块《{sec['title']}》。要求: {sec['req']}\n\n"
        f"篇幅要求: 开篇板块正文800–1200字, 立起人物与场景。\n\n"
        f"传记总纲:\n{intro}\n\n"
        f"请撰写开篇板块《{sec['title']}》正文, 相关事实如下:\n"
        f"{facts_txt}\n\n"
        "输出格式: 直接输出正文, 正文使用 Markdown, "
        "分2~4个自然段, 段与段之间以空行分隔; 板块标题行由组装侧统一添加。"
    )
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def build_section_messages(article, section, facts, cache, intro, lead_text, cfg):
    """中段/尾段提示词。"""
    key = article["key"]
    title = article["title"]
    blocks = _article_facts(facts, cache, key)
    sys_msg = (
        "你是史官, 撰写纪传体传记。\n\n"
        f"{JIZHUANTI_RULE}\n{NONFICTION_RULE}\n{WORLD_FRAME_RULE}"
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
        subject_note
        + f"本篇文章标题已定为《{title}》。\n\n"
        f"请撰写板块《{section['title']}》。要求: {section['req']}\n\n"
        f"篇幅要求: 板块正文1200–1800字。\n\n"
        f"传记总纲:\n{intro}\n\n"
        f"本文开篇板块《{article['sections'][0]['title']}》内容(以下为开篇全文):\n"
        f"{lead_text}\n\n"
        f"请撰写后续板块《{section['title']}》, 须与开篇呼应。相关事实:\n"
        f"{facts_txt}\n\n"
        "输出格式: 直接输出正文, 正文使用 Markdown; 以「太史公曰」作结的板块请确保"
        "评点在文末。"
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


def _normalize_section(text, sec_title):
    """板块正文规范化: 标题统一为 ###, 表格转自然语言, 无标题补 ### 板块名。"""
    out = []
    saw = False
    for raw in (text or "").split("\n"):
        s = raw.strip()
        if not s:
            out.append("")
            continue
        if s.startswith("#"):
            if sec_title in s:
                saw = True
            s = re.sub(r"^(#{1,6})\s+", "### ", s)
            out.append(s)
            continue
        out.append(s)
    body = _strip_markdown_tables("\n".join(out)).strip()
    body = llm.clean_number_spaces(body)
    if not saw:
        body = f"### {sec_title}\n\n{body}"
    return body


def _assemble(facts, intro, leads, sections, articles):
    parts = [f"# 《{facts['protagonist']['name']}传》"]
    p = facts["protagonist"]
    house = facts.get("house") or p.get("house") or ""
    death = facts.get("player_death")
    span = ""
    if death:
        span = f"卒于{llm.fmt_cn_date(death.get('date'))}（终传）"
    else:
        span = f"截至{llm.fmt_cn_date(facts.get('last_date') or '?')}"
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
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def build_articles(facts, cache, cfg):
    """按 cfg.bio_sections 组装文章列表 (标题含主角/好友/仇人姓名)。"""
    pid = facts.get("player_id")
    pname = (facts["protagonist"] or {}).get("name") or "主角"
    friend = _select_friend(cache)
    enemy = _select_primary_enemy(cache)
    fname = ""
    ename = ""
    if friend is not None:
        fp = facts["characters"].get(str(friend)) or {}
        fname = fp.get("name") or ""
    if enemy is not None:
        ep = facts["characters"].get(str(enemy)) or {}
        ename = ep.get("name") or ""
    sec_keys = [s for s in ("lead", "mid", "tail") if s in (cfg.get("bio_sections") or ["lead", "mid", "tail"])]
    def mk_sections(key):
        titles = SECTION_TITLES.get(key, {})
        return [{
            "key": sk,
            "title": titles.get(sk, {"lead": "开篇", "mid": "纪事", "tail": "评曰"}[sk]),
            "req": SECTION_REQ.get(key, {}).get(sk, "按纪传体笔法写作, 以资料为限。"),
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
    return articles


def generate_biography(cache, melt, cfg, out_path=None):
    """生成传记 Markdown 并写入 out_path。返回 (md_text, facts, articles)。"""
    names_path = os.path.join(cfg.get("data_dir", ""), "names.json")
    facts = F.build_facts(cache, melt, names_path)
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
            body = _normalize_section(text, article["sections"][0]["title"])
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
            msg = build_section_messages(article, section, facts, cache, intro,
                                         leads[article["key"]], cfg)
            text = llm.call_deepseek(msg, sec_cfg).strip()
            return article["key"], section["key"], _normalize_section(
                text, section["title"])
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
    header = (f"<!-- 数据来源: CK3 年度存档快照 | 家族: {facts.get('house', '')} | "
              f"生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} -->\n\n")
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(header + md.rstrip() + "\n")
        llm.log(f"传记已生成: {out_path}")
    return md, facts, articles
