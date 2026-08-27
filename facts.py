# -*- coding: utf-8 -*-
"""干净事实渲染层 (facts.py)
============================
把 缓存(cache) + 最新熔化档(melt) 渲染成**只含中文自然语言**的事实清单,
供 biography.py 拼提示词。铁律: **任何内部 id / 键 / 英文枚举一律不进入提示词**。

覆盖的清理项 (对应「小传泄漏键值」问题):
  - 角色 id → 姓+名 (边诚 / 孙浣 / 王铎 ...)
  - 头衔 id / key (k_shannan 等) → 中文名 + 层级词 (山南（王国）)
  - 文化 / 信仰 id → 汉族 / 经学
  - 特质 id → 轻信 / 急躁 ...
  - 记忆类型枚举 → 结仇 / 丧偶 / 失土 ...
  - 死亡原因枚举 → 处决 / 寿终 ...
  - 日期 869.2.22 → 869年2月22日
"""
import json
import os
import re

import llm
import cache_lib as cl

# ---------------------------------------------------------------------------
# 中文映射表
# ---------------------------------------------------------------------------

TRAIT_ZH = {
    "trusting": "轻信", "impatient": "急躁", "vengeful": "睚眦必报",
    "education_learning_3": "学识（教育三级）", "whole_of_body": "身心合一",
    "governor": "治理者", "ambitious": "雄心勃勃", "brave": "勇敢",
    "craven": "怯懦", "greedy": "贪婪", "lustful": "好色", "gluttonous": "饕餮",
    "wrathful": "暴怒", "paranoid": "多疑", "deceitful": "狡诈",
    "honest": "诚实", "shy": "羞怯", "arrogant": "傲慢", "patient": "坚忍",
    "diligent": "勤勉", "slothful": "懒惰", "compassionate": "慈悲",
    "sadistic": "残忍", "callous": "冷酷", "just": "公正", "generous": "慷慨",
    "stubborn": "固执", "fickle": "善变", "gregarious": "合群",
    "humble": "谦逊", "torturer": "严刑", "organizer": "统筹",
    "education_intrigue_3": "权谋（教育三级）", "education_martial_2": "戎略（教育二级）",
    "education_diplomacy_2": "辞令（教育二级）", "education_stewardship_2": "治财（教育二级）",
    "education_learning_2": "学识（教育二级）", "education_intrigue_2": "权谋（教育二级）",
    "education_martial_3": "戎略（教育三级）", "education_diplomacy_3": "辞令（教育三级）",
    "education_stewardship_3": "治财（教育三级）",
}

CULTURE_TEMPLATE_ZH = {"han": "汉"}
FAITH_TYPE_ZH = {"jingxue": "经学"}

LEVEL_ZH = {"e_": "帝国", "k_": "王国", "d_": "公国", "c_": "县", "b_": "堡"}

DEATH_REASON_ZH = {
    "death_execution": "处决", "death_murder": "谋杀", "death_duel": "决斗",
    "death_accident": "意外", "death_stress": "忧惧而亡", "death_wounds": "伤重不治",
    "death_punishment": "刑罚", "death_poison": "毒杀", "death_snake": "蛇噬",
    "death_dungeon": "囚毙", "death_fight": "斗殴", "death_old_age": "寿终",
    "death_natural_causes": "寿终", "death_heart_attack": "心疾",
    "death_broken_bones": "骨碎", "death_drinking_passive": "酗酒",
    "death_disappearance": "失踪而亡", "death_plotting": "密谋致死",
    "death_battle": "战殁", "death_imprisonment": "囚毙",
}

GOVERNMENT_ZH = {
    "celestial_government": "天朝官制", "feudal_government": "封建采邑制",
    "clan_government": "部族宗法制", "tribal_government": "部落制",
    "republic_government": "共和制", "theocracy_government": "教权制",
}

# 记忆类型 → 中文 (模板: {name}=记忆拥有者, {other}=参与者, {title}=头衔)
MEMORY_TEMPLATES = {
    "became_rivals": "{name}与{other}结仇。",
    "became_grudge": "{name}与{other}结怨。",
    "became_nemesis": "{name}与{other}结为死敌。",
    "stopped_being_rivals": "{name}与{other}化解仇怨。",
    "rival_died": "{name}的仇人{other}身亡。",
    "friend_died": "{name}的友人{other}亡故。",
    "relative_died": "{name}的亲属{other}亡故。",
    "spouse_died": "{name}丧偶，{other}身亡。",
    "married": "{name}与{other}成婚。",
    "broke_up_lovers": "{name}与{other}分手。",
    "became_lovers": "{name}与{other}相恋。",
    "had_sex": "{name}与{other}有私情。",
    "became_friends": "{name}与{other}结为好友。",
    "became_soulmates": "{name}与{other}结为灵魂伴侣。",
    "became_blood_brother": "{name}与{other}结为血盟兄弟。",
    "imprisoned_other": "{name}囚禁{other}。",
    "imprisoned": "{name}被囚。",
    "released_from_prison_memory": "{name}获释出狱。",
    "lost_title_memory": "{name}让出{title}。",
    "ascended_throne_memory": "{name}登位，得{title}。",
    "child_born": "{name}添子{other}。",
    "first_born": "{name}得长子{other}。",
    "child_premature": "{name}幼子夭折。",
    "child_stillborn": "{name}婴儿夭折。",
    "twins_born": "{name}得孪生子。",
    "passed_child_exam_memory": "{name}童子试及第。",
    "failed_child_exam_memory": "{name}童子试落第。",
    "passed_provincial_exam_memory": "{name}乡试及第。",
    "failed_provincial_exam_memory": "{name}乡试落第。",
    "passed_metropolitan_exam_memory": "{name}会试及第。",
    "passed_palace_exam_memory": "{name}殿试及第。",
    "tortured_memory": "{name}受刑。",
    "torturer_memory": "{name}施刑于人。",
    "battle_won_memory": "{name}打了胜仗。",
    "battle_lost_memory": "{name}吃了败仗。",
    "offensive_war": "{name}主动开战。",
    "defensive_war": "{name}被迫应战。",
    "war_won": "{name}赢得战争。",
    "war_lost": "{name}战败。",
    "joined_allys_war": "{name}助盟友作战。",
    "witnessed_death_battle": "{name}目击战殁。",
    "became_incapable_due_to_battle_concussion": "{name}战伤致残。",
    "completed_hajj_memory": "{name}朝觐归来。",
    "hostage_created_hostage": "{name}为人质。",
    "hostage_created_warden": "{name}看守人质。",
    "hostage_created_home_court": "{name}交出人质。",
    "picked_serenity_aspect_memory": "{name}皈依安详之道。",
    "picked_creation_aspect_memory": "{name}皈依创世之道。",
    "ward_education_completed": "{name}完成教化。",
    "childhood_education_guardian": "{name}受业于{other}。",
    "childhood_education_no_guardian": "{name}独自求学。",
    "completed_rites_of_passage": "{name}完成成人礼。",
    "completed_adult_education": "{name}完成成人学业。",
    "became_acclaimed": "{name}获拥戴。",
    "witnessed_a_coronation_memory": "{name}见证加冕。",
    "grand_wedding_completed_guest": "{name}出席大婚。",
    "ignored_assault_memory": "{name}受辱未报。",
}

# 参与者槽位: 记忆类型 → participants 键 (缺失时取第一个 int 参与者)
PARTICIPANT_SLOTS = {
    "became_rivals": "rival", "became_grudge": "grudge", "became_nemesis": "nemesis",
    "stopped_being_rivals": "rival", "rival_died": "dead_relation",
    "friend_died": "dead_relation", "relative_died": "dead_relation",
    "spouse_died": "dead_relation", "married": "spouse",
    "broke_up_lovers": "old_lover", "became_lovers": "new_relation",
    "had_sex": "sex_partner", "became_friends": "new_relation",
    "became_soulmates": "new_soulmate", "became_blood_brother": "blood_brother",
    "imprisoned_other": "imprisoned", "imprisoned": "imprisoner",
    "released_from_prison_memory": "imprisoner", "lost_title_memory": "new_holder",
    "child_born": "child", "first_born": "child",
    "childhood_education_guardian": "guardian",
}

# 记忆类型 → 取 vars 中的 landed_title (头衔 id)
TITLE_VAR_TYPES = {"lost_title_memory", "ascended_throne_memory"}


# ---------------------------------------------------------------------------
# 解析小工具
# ---------------------------------------------------------------------------

class Facts:
    """一次 build_facts 的上下文: 缓存 + melt + 名字解析 + 头衔解析。"""

    def __init__(self, cache, melt, names_path):
        self.cache = cache
        self.melt = melt
        self.names_path = names_path
        self._lt = ((melt.get("landed_titles") or {}).get("landed_titles") or {})
        self._tl = melt.get("traits_lookup") or []
        self._chars = cl.all_characters(melt)

    # ---- 名字 ----
    def name(self, cid):
        """角色 id → 完整中文名 (姓+名); 未知返回 ''。"""
        return cl.resolve_full_name(self.cache, cid, names_path=self.names_path,
                                    melt=self.melt)

    def name_or(self, cid, fallback="一位人物"):
        n = self.name(cid)
        return n or fallback

    # ---- 头衔 ----
    def title(self, tid):
        """头衔 id → '山南（王国）'; 未知返回 ''。"""
        if tid is None:
            return ""
        t = self._lt.get(str(tid)) or {}
        key = t.get("key") or ""
        name = ((t.get("title_name_data") or {}).get("name") or "").strip()
        if not name:
            name = key
        lvl = ""
        for pfx, z in LEVEL_ZH.items():
            if key.startswith(pfx):
                lvl = z
                break
        if lvl:
            return f"{name}（{lvl}）"
        return name

    # ---- 文化 / 信仰 / 特质 / 政体 ----
    def culture(self, cid):
        c = self._chars.get(str(cid)) or {}
        template = (self.melt.get("culture_manager") or {}).get("cultures") or {}
        e = template.get(str(c.get("culture"))) if c.get("culture") is not None else None
        tpl = (e or {}).get("culture_template") or ""
        zh_name = CULTURE_TEMPLATE_ZH.get(tpl)
        if zh_name:
            return f"{zh_name}族"
        return "族属不详"

    def faith(self, cid):
        c = self._chars.get(str(cid)) or {}
        faiths = (self.melt.get("religion") or {}).get("faiths") or {}
        e = faiths.get(str(c.get("faith"))) if c.get("faith") is not None else None
        ft = (e or {}).get("faith_type") or ""
        zh_name = FAITH_TYPE_ZH.get(ft)
        if zh_name:
            return zh_name
        return "信仰不详"

    def traits(self, cid):
        """角色特质 id 列表 → 中文 (未知特质跳过)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        ids = rec.get("traits") or []
        out = []
        for t in ids:
            if not isinstance(t, int) or t < 0 or t >= len(self._tl):
                continue
            key = self._tl[t]
            z = TRAIT_ZH.get(key)
            if z:
                out.append(z)
        return out

    def government(self, cid):
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        g = (rec.get("landed") or {}).get("government")
        return GOVERNMENT_ZH.get(g, "官制不详")

    # ---- 日期 ----
    def date(self, d):
        return llm.fmt_cn_date(d)


# ---------------------------------------------------------------------------
# 事实渲染
# ---------------------------------------------------------------------------

def _mem_sentence(f, owner_id, mem):
    """一条记忆 → 干净中文句。"""
    tpl = MEMORY_TEMPLATES.get(mem.get("type"))
    if not tpl:
        return None
    owner = f.name_or(owner_id)
    parts = mem.get("participants") or {}
    slot = PARTICIPANT_SLOTS.get(mem.get("type"))
    other_id = None
    if slot and slot in parts and isinstance(parts[slot], int):
        other_id = parts[slot]
    elif slot is None:
        for v in parts.values():
            if isinstance(v, int):
                other_id = v
                break
    other = f.name_or(other_id, "") if other_id is not None else ""
    title = ""
    if mem.get("type") in TITLE_VAR_TYPES:
        for v in mem.get("vars") or []:
            if v.get("flag") == "landed_title" and v.get("identity"):
                title = f.title(v.get("identity"))
                break
    s = tpl.format(name=owner, other=other, title=title)
    # 参与者/头衔缺失时清理悬空占位
    s = s.replace("与。", "。").replace("与，", "，").replace("与、", "、")
    s = s.replace("让出。", "让出领地。")
    s = s.replace("得。", "登位。")
    return s


def _death_sentence(f, cid):
    """角色死亡 → 干净中文句。"""
    rec = (f.cache.get("characters") or {}).get(str(cid)) or {}
    d = rec.get("death") or {}
    if not d:
        return None
    name = f.name_or(cid)
    reason = DEATH_REASON_ZH.get(d.get("reason"), "身故")
    killer = d.get("killer")
    kstr = ""
    # 动作型死因加「被」字 (被处决/被谋杀/被毒杀/被刑罚/被决斗...)
    action_like = {"处决", "谋杀", "毒杀", "刑罚", "决斗", "蛇噬", "斗殴"}
    if reason in action_like:
        reason = "被" + reason
    if killer is not None:
        if killer == f.cache.get("player_id"):
            kstr = f"，行刑者为{f.name_or(f.cache.get('player_id'))}"
        else:
            kstr = f"，凶手为{f.name_or(killer)}"
    return f"{name}殁于{f.date(d.get('date'))}，{reason}{kstr}。"


def _timeline(f):
    """全缓存时间线: 所有角色的记忆 + 死亡, 按日期排序。
    每条 = {"date", "type", "text"} (text 为干净中文句, 提示词只用 text)。
    成对事件 (双方各自的记忆, 如王铎娶玘/玘嫁王铎) 按 (类型, 日期, 参与者集) 去重。"""
    events = []
    seen_keys = set()
    for cid, rec in (f.cache.get("characters") or {}).items():
        for mem in rec.get("memories") or []:
            s = _mem_sentence(f, int(cid), mem)
            if not s:
                continue
            parts = mem.get("participants") or {}
            pset = frozenset(v for v in parts.values() if isinstance(v, int)) | {int(cid)}
            key = (mem.get("type"), mem.get("creation_date"), pset)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            events.append({"date": mem.get("creation_date"),
                           "type": mem.get("type"),
                           "text": s})
        ds = _death_sentence(f, int(cid))
        if ds:
            d = (rec.get("death") or {}).get("date")
            events.append({"date": d, "type": "death", "text": ds})
    events.sort(key=lambda x: cl.date_key(x["date"]))
    seen = set()
    out = []
    for e in events:
        if e["text"] in seen:
            continue
        seen.add(e["text"])
        out.append({
            "date": e["date"],
            "type": e["type"],
            "text": (f"{f.date(e['date'])}，{e['text']}" if e["date"] else e["text"]),
        })
    return out


def _protagonist(f):
    """主角档案 (干净中文)。"""
    cache = f.cache
    pid = cache.get("player_id")
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    melt = f.melt
    pobj = (melt.get("living") or {}).get(str(pid)) or {}
    ad = pobj.get("alive_data") or {}
    p = {
        "name": f.name_or(pid),
        "house": (cache.get("house_name") or "") + ("" if (cache.get("house_name") or "").endswith("氏") else "氏"),
        "birth": f.date(rec.get("birth")),
        "culture": f.culture(pid),
        "faith": f.faith(pid),
        "traits": "、".join(f.traits(pid)) or "（特质不详）",
        "government": f.government(pid),
    }
    ld = rec.get("landed") or {}
    if ld:
        p["ruler_since"] = f.date(ld.get("became_ruler_date"))
        dom = []
        for tid in (ld.get("domain") or []):
            t = f.title(tid)
            if t:
                dom.append(t)
        p["domain"] = "、".join(dom)
        p["domain_count"] = len(ld.get("domain") or [])
        cap = f.title(ld.get("realm_capital"))
        if cap:
            p["capital"] = cap
        p["vassal_count"] = ld.get("vassal_count", 0)
        p["council"] = "御前会议六席" if ld.get("council") else ""
    # 现状 (仅在世时)
    if not cache.get("player_death"):
        def num(v, nd=1):
            try:
                return f"{float(v):.{nd}f}".rstrip("0").rstrip(".")
            except Exception:
                return None
        bits = []
        age = None
        try:
            by = int((rec.get("birth") or "0.0.0").split(".")[0])
            cy = int((melt.get("date") or "0.0.0").split(".")[0])
            age = cy - by
        except Exception:
            pass
        if age is not None:
            bits.append(f"年{age}岁")
        h = num(ad.get("health"))
        if h is not None:
            bits.append(f"健康{h}")
        st = num(ad.get("stress"))
        if st is not None:
            bits.append(f"压力{st}")
        g = num((ad.get("gold") or {}).get("value"))
        if g is not None:
            bits.append(f"国库金{g}")
        inc = num(ad.get("income"))
        if inc is not None:
            bits.append(f"月入{inc}")
        for key, label in (("piety", "虔诚"), ("prestige", "威望"),
                           ("influence", "影响力"), ("merit", "功勋")):
            v = num((ad.get(key) or {}).get("currency"))
            if v is not None:
                bits.append(f"{label}{v}")
        if bits:
            p["status"] = "，".join(bits) + "。"
    # 死亡 (终传时)
    pd = cache.get("player_death")
    if pd:
        p["death"] = (
            f"殁于{f.date(pd.get('date'))}，"
            f"{DEATH_REASON_ZH.get(pd.get('reason'), '身故')}"
            + (f"，凶手为{f.name_or(pd.get('killer'))}" if pd.get("killer") else "。")
        )
    # 家庭
    fam = rec.get("family") or {}
    spouse_ids = list(dict.fromkeys(
        (fam.get("primary_spouse") or []) + (fam.get("spouse") or [])))
    p["spouses"] = "、".join(f.name_or(s) for s in spouse_ids if f.name(s))
    p["former_spouses"] = "、".join(f.name_or(s) for s in (fam.get("former_spouses") or []) if f.name(s))
    p["children"] = "、".join(f.name_or(c) for c in (fam.get("child") or []) if f.name(c))
    return p


def _character_profiles(f):
    """每个缓存角色: 干净档案 + 记忆 + 死亡。"""
    out = {}
    for cid, rec in (f.cache.get("characters") or {}).items():
        cid = int(cid)
        name = f.name_or(cid)
        prof = {
            "name": name,
            "house": (rec.get("house_name") or "") + "氏" if rec.get("house_name") else "",
            "birth": f.date(rec.get("birth")),
            "culture": f.culture(cid),
            "faith": f.faith(cid),
            "traits": "、".join(f.traits(cid)),
        }
        fam = rec.get("family") or {}
        spouse_ids = list(dict.fromkeys(
            (fam.get("primary_spouse") or []) + (fam.get("spouse") or [])))
        prof["spouses"] = "、".join(f.name_or(s) for s in spouse_ids if f.name(s))
        prof["children"] = "、".join(f.name_or(c) for c in (fam.get("child") or []) if f.name(c))
        mems = []
        for mem in rec.get("memories") or []:
            s = _mem_sentence(f, cid, mem)
            if s:
                mems.append(f"{f.date(mem.get('creation_date'))}，{s}")
        mems.sort()
        prof["events"] = mems
        ds = _death_sentence(f, cid)
        if ds:
            prof["death"] = ds
        out[str(cid)] = prof
    return out


def build_facts(cache, melt, names_path=None):
    """渲染干净事实集。melt 为 dict (已加载)。"""
    f = Facts(cache, melt, names_path)
    period = ""
    sources = cache.get("sources") or []
    if sources:
        period = f"{sources[0]} – {sources[-1]}"
    facts = {
        "house": (cache.get("house_name") or "") + ("氏" if cache.get("house_name")
                                                    and not str(cache.get("house_name")).endswith("氏") else ""),
        "player_name": cache.get("player_name"),
        "player_id": cache.get("player_id"),
        "period": period,
        "sources": sources,
        "protagonist": _protagonist(f),
        "timeline": _timeline(f),
        "characters": _character_profiles(f),
        "player_death": cache.get("player_death"),
        "last_date": cache.get("last_date"),
    }
    return facts


def facts_to_text(facts, keys=None):
    """把事实集拼成给模型的纯文本 (调试/日志用)。"""
    lines = []
    p = facts["protagonist"]
    lines.append(f"主角：{p.get('name')}（{p.get('house')}）")
    for k in ("birth", "culture", "faith", "traits", "government"):
        if p.get(k):
            lines.append(f"{k}：{p[k]}")
    return "\n".join(lines)
