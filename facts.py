# -*- coding: utf-8 -*-
"""干净事实渲染层 (facts.py)
============================
把 缓存(cache) + 最新熔化档(melt) 渲染成**只含中文自然语言**的事实清单,
供 biography.py 拼提示词。铁律: **任何内部 id / 键 / 英文枚举一律不进入提示词**。

v4 变更:
  - 名字/姓氏/头衔/文化/信仰/特质/政体/死因 全部先查 localization.py 本地化表
    (Daria → 达丽娅; 文化 ashkenazi → 阿什肯纳兹; 信仰 ashari → 艾什尔里派)。
  - 头衔层级词按政体动态取 (celestial: 路/大路/镇/州府; 回退 王国/帝国/公国/县/堡)。
  - 无地冒险者分支: 营地现驻郡 + 县主 + 上位链 + 最高领主 (经省份→伯爵领映射)。
  - 亲属/妻族: 父/母/兄弟姐妹 + 曾任头衔 (经 realm_history 反查, 妻父宋帝/妻兄今上)。
  - 特质履历: trait_history 渲染「自某日起获得 / 自某日后消失」。
  - 朝局数据: 帝国/王国级头衔持有者逐年变化, 供《朝局风云录》。
"""
import json
import os
import re

import llm
import cache_lib as cl
import localization as L

# ---------------------------------------------------------------------------
# 中文映射表 (本地化缺失时的兜底)
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
    "education_martial_5": "戎略（教育五级）", "education_diplomacy_5": "辞令（教育五级）",
    "education_stewardship_5": "治财（教育五级）", "education_intrigue_5": "权谋（教育五级）",
    "education_learning_5": "学识（教育五级）",
    "military_engineer": "军事工程师", "beauty_good_3": "倾国倾城",
    "gallowsbait": "不法之徒", "murderer": "谋杀犯", "reclusive": "蛰居",
    "reckless": "鲁莽", "ill": "患病", "pregnant": "有孕",
    "tourney_participant": "比武大会参与者",
}

CULTURE_TEMPLATE_ZH = {"han": "汉"}
FAITH_TYPE_ZH = {"jingxue": "经学"}

GOVERNMENT_ZH = {
    "celestial_government": "天朝官制", "feudal_government": "封建采邑制",
    "clan_government": "部族宗法制", "tribal_government": "部落制",
    "republic_government": "共和制", "theocracy_government": "教权制",
    "landless_adventurer_government": "冒险者",
    "administrative_government": "行政官制",
}

DEATH_REASON_ZH = {
    "death_execution": "处决", "death_murder": "谋杀", "death_duel": "决斗",
    "death_accident": "意外", "death_stress": "忧惧而亡", "death_wounds": "伤重不治",
    "death_punishment": "刑罚", "death_poison": "毒杀", "death_snake": "蛇噬",
    "death_dungeon": "囚毙", "death_fight": "斗殴", "death_old_age": "寿终",
    "death_natural_causes": "寿终", "death_heart_attack": "心疾",
    "death_broken_bones": "骨碎", "death_drinking_passive": "酗酒",
    "death_disappearance": "失踪而亡", "death_plotting": "密谋致死",
    "death_battle": "战殁", "death_imprisonment": "囚毙",
    "death_bubonic_plague": "黑死病", "death_physique_bad_2": "体弱不支",
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

# 朝局类记忆类型 (群英录/朝局风云录用, 与 biography.POLITICAL_TYPES 同步)
POLITICAL_TYPES_KEYS = {
    "ascended_throne_memory", "lost_title_memory", "imprisoned",
    "released_from_prison_memory", "became_rivals", "became_grudge",
    "became_nemesis", "stopped_being_rivals", "offensive_war",
    "defensive_war", "war_won", "war_lost", "joined_allys_war",
    "battle_won_memory", "battle_lost_memory",
}


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def house_display(h):
    """家族名显示: 单字中文姓加「氏」(边 → 边氏), 其余原样 (冯·大马士革)。"""
    if not h:
        return ""
    if len(h) == 1 and "\u4e00" <= h <= "\u9fff":
        return h + "氏"
    return h


def _trait_name(table, key):
    """特质 key → 中文: trait_<key> → <key> → 兜底表; 未知返回 '' (跳过, 不外泄 key)。"""
    if not key:
        return ""
    for cand in (f"trait_{key}", key):
        v = L.loc(table, cand)
        if v:
            return v
    return TRAIT_ZH.get(key, "")


def _death_reason(table, reason):
    """死因 key → 中文 (本地化值含未解析引用时用兜底表)。"""
    if not reason:
        return "身故"
    v = L.loc(table, reason)
    if v and "[" not in v and "$" not in v and v != "死于":
        return v
    return DEATH_REASON_ZH.get(reason, "身故")


def render_motto(motto, table):
    """家训 → 中文 (v7)。存档 dynasty_house.motto 两种形态:
    1) 字符串: 已渲染中文原样输出; 本地化键查表 (dynn_harrani_motto → 认识自己本质的人...)。
    2) 模板 dict: {key, variables:[{key:'1', value:'motto_friendship'}]} →
       key 查表得模板 (以$1$与$2$之名) → $N$ 按槽位填充 (以坚韧与安全之名) → 剥离动态引用。"""
    if isinstance(motto, str):
        s = motto.strip()
        if not s:
            return ""
        if any("\u3400" <= ch <= "\u9fff" for ch in s):
            return s
        v = L.loc(table, s)
        return v or s
    if isinstance(motto, dict):
        key = motto.get("key") or ""
        tpl = L.loc(table, key)
        if not tpl:
            return ""
        slots = {}
        for v in motto.get("variables") or []:
            if not isinstance(v, dict):
                continue
            sv = v.get("value")
            if not sv:
                continue
            slots[str(v.get("key"))] = L.loc(table, sv) or sv
        text = tpl
        for sk, sv in slots.items():
            text = text.replace("${" + sk + "}", sv)
        text = re.sub(r"\$\d+\$", "", text)  # 未填充的空槽清理
        return L.strip_ck3_format(text).strip()
    return ""


# ---------------------------------------------------------------------------
# Facts 上下文
# ---------------------------------------------------------------------------

class Facts:
    """一次 build_facts 的上下文: 缓存 + melt + 名字/头衔/本地化解析。"""

    def __init__(self, cache, melt, names_path):
        self.cache = cache
        self.melt = melt
        self.names_path = names_path
        self._lt = ((melt.get("landed_titles") or {}).get("landed_titles") or {})
        self._tl = melt.get("traits_lookup") or []
        self._chars = cl.all_characters(melt)
        self.table = L.table()
        self.provmap = L.province_map()
        self._title_by_key = {}
        for tid, t in self._lt.items():
            if not isinstance(t, dict):  # v7: none 条目防护
                continue
            k = t.get("key")
            if k:
                self._title_by_key[k] = int(tid)
        self._gov_cache = {}
        # v8: 全部层级词并集 (通用 + 各政体 + 伊斯兰国名后缀), 用于「名字已含层级词不追加」
        self._rank_words = set(L.GENERIC_TIER_ZH.values()) | {"哈里发国", "苏丹国"}
        for _g in ("celestial", "administrative", "feudal", "clan",
                   "tribal", "theocracy", "republic"):
            for _tier in ("empire", "kingdom", "duchy", "county",
                          "barony", "hegemon"):
                w = L.tier_word(self.table, _g + "_government", _tier)
                if w and not w.startswith("$"):
                    self._rank_words.add(w)
        # v5: 自定义角色 (ruler_designer_characters) — 出身自定, 无谱系
        self._custom_starts = set()
        for x in (melt.get("ruler_designer_characters") or []):
            try:
                self._custom_starts.add(int(x))
            except Exception:
                pass

    # ---- 名字 ----
    def name(self, cid):
        """角色 id → 显示名 (文化名序: 东方姓在前, 西方名·姓); 未知返回 ''。"""
        return cl.name_display(self.cache, cid, melt=self.melt,
                               names_path=self.names_path)

    def name_or(self, cid, fallback="一位人物"):
        n = self.name(cid)
        return n or fallback

    # ---- 头衔 ----
    def _title_government(self, tid):
        """头衔的政体: 持有者政体, 缺失沿 de_facto_liege 上溯。"""
        if tid in self._gov_cache:
            return self._gov_cache[tid]
        gov = ""
        seen = set()
        cur = str(tid)
        while cur and cur not in seen:
            seen.add(cur)
            t = self._lt.get(cur) or {}
            if not t:
                break
            holder = t.get("holder")
            if isinstance(holder, int):
                c = self._chars.get(str(holder)) or {}
                gov = (c.get("landed_data") or {}).get("government") or ""
                if gov:
                    break
            liege = t.get("de_facto_liege")
            cur = str(liege) if liege is not None else None
        self._gov_cache[tid] = gov
        return gov

    def title(self, tid):
        """头衔 id → 中文名 + 动态层级词合并: '复兴党流亡委员会' / '开罗伯爵领' /
        '埃及王国' / '图伦苏丹国' / '阿拔斯哈里发国' / '宋大路' / '中华天朝'(霸权级)。
        名字取值: custom → name → 本地化表 → key; 无地营地 (x_) 只给名字。
        v8: 头衔名与层级词直接合并 (布列塔尼公国), 名字已含层级词时不追加
        (神圣罗马帝国); 霸权级 h_ 仅天朝制启用「天朝」词 (罗马帝国等不加后缀)。
        v8.1: 伊斯兰统治者 (最高领主) 的国名按游戏同规则显示为「家族+层级词」——
        动态国名不存于存档 (k_egypt 静态名仍为「埃及」, 游戏运行时拼出),
        按 持有者信仰→伊斯兰 + 家族名 + 层级 (k_→苏丹国, e_/h_→哈里发国/帝国
        依是否兼任哈里发) 复现。"""
        if tid is None:
            return ""
        t = self._lt.get(str(tid)) or {}
        key = t.get("key") or ""
        tnd = t.get("title_name_data") or {}
        name = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
        if not name:
            name = L.loc(self.table, key)
        if not name:
            name = key
        if key.startswith("x_"):  # 无地营地/教团等特殊头衔: 只给名字
            return name
        rn = self.realm_name(tid)  # v8.1: 伊斯兰统治者动态国名优先
        if rn:
            return rn
        tier = ""
        for pfx, tv in L.TIER_KEY_OF_PREFIX.items():
            if key.startswith(pfx):
                tier = tv
                break
        if tier:
            gov = self._title_government(tid)
            word = L.tier_word(self.table, gov, tier)
            # 霸权级 (h_): 仅天朝制启用「天朝」; 其它政体 h_ 不加后缀
            if key.startswith("h_") and gov != "celestial_government":
                word = ""
            # v8.2: 行政制帝国词「大督军」仅在其上有霸权头衔时出现
            # (拜占庭帝国无上位霸权 → 用通用「帝国」, 实测游戏行为)。
            generic_word = L.tier_word(self.table, "", tier)
            if (gov == "administrative_government" and tier == "empire"
                    and word != generic_word
                    and not self._has_hegemon_above(tid)):
                word = generic_word
            # 名字已含任意层级词 (神圣罗马帝国/大元帝国/逊尼派哈里发国) 或词为空时不追加
            if word and not any(name.endswith(w) for w in self._rank_words):
                return f"{name}{word}"
        return name

    def _has_hegemon_above(self, tid):
        """沿 de_facto_liege 上溯, 是否存在霸权级 (h_) 头衔在上 (v8.2)。"""
        seen = set()
        cur = str(tid)
        while cur and cur not in seen:
            seen.add(cur)
            t = self._lt.get(cur) or {}
            if not t:
                break
            if (t.get("key") or "").startswith("h_"):
                return True
            liege = t.get("de_facto_liege")
            cur = str(liege) if liege is not None else None
        return False

    def title_by_key(self, key):
        if not key:
            return None
        return self._title_by_key.get(key)

    # ---- v8.1: 伊斯兰统治者动态国名 (游戏同规则复现) ----

    _ISLAM_RELIGIONS = {"islam_religion", "sunni_religion",
                        "shia_religion", "ibadi_religion"}
    _NO_RELIGIOUS_HEAD = 4294967295  # 0xFFFFFFFF = 无宗教领袖

    def _faith_id(self, cid):
        """角色信仰 id: 缓存优先, 回退最新熔件角色对象。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fid = rec.get("faith")
        if fid is None:
            c = self._chars.get(str(cid)) or {}
            fid = c.get("faith")
        return fid

    def is_islamic(self, cid):
        """角色是否伊斯兰教统治者: 信仰 → 宗教 → religion_type ∈ 伊斯兰系。"""
        fid = self._faith_id(cid)
        if fid is None:
            return False
        faiths = (self.melt.get("religion") or {}).get("faiths") or {}
        fe = faiths.get(str(fid))
        if not isinstance(fe, dict):
            return False
        rid = fe.get("religion")
        if not isinstance(rid, int):
            return False
        religions = (self.melt.get("religion") or {}).get("religions") or {}
        re = religions.get(str(rid))
        return (isinstance(re, dict)
                and (re.get("religion_type") or "") in self._ISLAM_RELIGIONS)

    def is_caliph(self, cid):
        """是否兼任哈里发: 其信仰的宗教领袖头衔 (faith.religious_head, 如 d_sunni)
        的当前持有者 == 本人。"""
        fid = self._faith_id(cid)
        if fid is None:
            return False
        faiths = (self.melt.get("religion") or {}).get("faiths") or {}
        fe = faiths.get(str(fid))
        if not isinstance(fe, dict):
            return False
        rh = fe.get("religious_head")
        if not isinstance(rh, int) or rh == self._NO_RELIGIOUS_HEAD:
            return False
        t = self._lt.get(str(rh)) or {}
        return isinstance(t, dict) and t.get("holder") == cid

    def dynasty_name(self, cid):
        """角色家族名 (穆斯林国名用): 缓存 house_name → 熔件 dynasty_house 解析。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        if rec.get("house_name"):
            return rec["house_name"]
        c = self._chars.get(str(cid)) or {}
        hid = c.get("dynasty_house")
        if isinstance(hid, int):
            return cl.house_name_zh(self.melt, hid)
        return ""

    def realm_name(self, tid):
        """伊斯兰统治者国名: k_ → {家族}苏丹国; e_/h_ → {家族}哈里发国(兼任哈里发)
        或 {家族}帝国。非伊斯兰 / 非王国帝国级 / 家族名缺失返回 '' (走常规渲染)。"""
        t = self._lt.get(str(tid)) or {}
        key = t.get("key") or ""
        holder = t.get("holder")
        if not key.startswith(("k_", "e_", "h_")) or not isinstance(holder, int):
            return ""
        if not self.is_islamic(holder):
            return ""
        dyn = self.dynasty_name(holder)
        if not dyn:
            return ""
        if key.startswith("k_"):
            return f"{dyn}苏丹国"
        if self.is_caliph(holder):
            return f"{dyn}哈里发国"
        return f"{dyn}帝国"

    # ---- 文化 / 信仰 / 特质 / 政体 ----
    def culture(self, cid):
        """角色文化 (v7 缓存优先): 缓存记录最近已知值 (存活期直接捕获, 死后清空
        也保留), 缺失回退最新熔件角色对象。id → culture_manager → 本地化 → 'X族'。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        cul = rec.get("culture")
        if cul is None:
            c = self._chars.get(str(cid)) or {}
            cul = c.get("culture")
        template = (self.melt.get("culture_manager") or {}).get("cultures") or {}
        e = template.get(str(cul)) if cul is not None else None
        if isinstance(e, str):  # v7: none 条目防护
            e = None
        tpl = (e or {}).get("culture_template") or ""
        name = L.loc(self.table, tpl) or CULTURE_TEMPLATE_ZH.get(tpl) or ""
        if name:
            return f"{name}族"
        return "族属不详"

    def faith(self, cid):
        """角色信仰 (v7 缓存优先): 同 culture, id → religion.faiths → 本地化。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fid = rec.get("faith")
        if fid is None:
            c = self._chars.get(str(cid)) or {}
            fid = c.get("faith")
        faiths = (self.melt.get("religion") or {}).get("faiths") or {}
        e = faiths.get(str(fid)) if fid is not None else None
        if isinstance(e, str):  # v7: none 条目防护
            e = None
        ft = (e or {}).get("faith_type") or ""
        name = L.loc(self.table, ft) or FAITH_TYPE_ZH.get(ft) or ""
        if name:
            return name
        return "信仰不详"

    def traits(self, cid):
        """角色当前特质 id 列表 → 中文 (未知特质跳过)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        ids = rec.get("traits") or []
        out = []
        for t in ids:
            if not isinstance(t, int) or t < 0 or t >= len(self._tl):
                continue
            key = self._tl[t]
            z = _trait_name(self.table, key)
            if z:
                out.append(z)
        return out

    def trait_history_lines(self, cid):
        """特质履历 (v4): 每条 = 「<特质>（自X日起获得 / 至晚自X日起已具 / 自X日后消失…）」"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        th = rec.get("trait_history") or {}
        lines = []
        for key in sorted(th):
            z = _trait_name(self.table, key)
            if not z or z == key:
                continue
            spans = []
            for iv in th[key]:
                d_from = self.date(iv.get("from")) if iv.get("from") else ""
                d_to = self.date(iv.get("to")) if iv.get("to") else ""
                if iv.get("first"):
                    spans.append(f"至晚自{d_from}起已具")
                elif iv.get("from") and not iv.get("to"):
                    spans.append(f"自{d_from}起获得")
                elif iv.get("from") and iv.get("to"):
                    spans.append(f"自{d_from}起获得，自{d_to}后消失")
                elif iv.get("to"):
                    spans.append(f"至{d_to}后消失")
            if spans:
                lines.append(f"{z}（{'；'.join(spans)}）")
        return lines

    def government(self, cid):
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        g = (rec.get("landed") or {}).get("government")
        if not g:
            c = self._chars.get(str(cid)) or {}
            g = (c.get("landed_data") or {}).get("government")
        return L.loc(self.table, g) or GOVERNMENT_ZH.get(g, "官制不详")

    def held_titles(self, cid):
        """角色历任高位头衔 (v4): 经 realm_history 反查, ['1067年1月1日：宋（大路）之主']"""
        out = []
        seen = set()
        for h in self.cache.get("realm_history") or []:
            for tid, holder in (h.get("holders") or {}).items():
                if holder != cid:
                    continue
                tname = self.title(tid)
                if not tname or tname in seen:
                    continue
                seen.add(tname)
                out.append(f"{self.date(h.get('date'))}：任{tname}之主")
        return out

    def motto(self):
        """玩家家族家训 (v7) → 中文。"""
        mot = self.cache.get("house_motto")
        if not mot:
            return ""
        return render_motto(mot, self.table)

    def court_positions_lines(self):
        """玩家宫廷/营地官职 (v7): 返回 (最新职位行, 任免变化行)。
        最新职位每条 = 「职位：人名（自X任）」; 变化行 = 跨快照同职位更替。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return [], []
        hist = self.cache.get("court_positions") or []
        if not hist:
            return [], []
        latest = hist[-1].get("positions") or []
        latest_lines = []
        for p in latest:
            zh = L.loc(self.table, p.get("type")) or ""
            if not zh or zh == p.get("type"):
                continue
            emp = p.get("employee")
            nm = self.name_or(emp, "") if emp is not None else ""
            hire = self.date(p.get("hire_date")) if p.get("hire_date") else ""
            if nm and hire:
                latest_lines.append(f"{zh}：{nm}（自{hire}任）")
            elif nm:
                latest_lines.append(f"{zh}：{nm}")
        # 任免变化: 相邻快照 (type, employee) 集合差集 → 上任/卸任
        change_lines = []
        prev = set()
        for h in hist:
            cur = {(p.get("type"), p.get("employee"))
                   for p in h.get("positions") or [] if p.get("type")}
            if prev and cur != prev:
                for t, emp in sorted(prev - cur):
                    zh = L.loc(self.table, t) or ""
                    if not zh or zh == t:
                        continue
                    nm = self.name_or(emp, "") if emp is not None else "空缺"
                    if nm:
                        change_lines.append(f"{self.date(h.get('date'))}：{nm}卸任{zh}")
                for t, emp in sorted(cur - prev):
                    zh = L.loc(self.table, t) or ""
                    if not zh or zh == t:
                        continue
                    nm = self.name_or(emp, "") if emp is not None else "空缺"
                    if nm:
                        change_lines.append(f"{self.date(h.get('date'))}：{nm}出任{zh}")
            prev = cur
        return latest_lines, change_lines

    # ---- v5: 文化名序 / 文风 ----

    def name_order(self, cid):
        """角色文化名序约定 ('' = 西方; DYNASTY_ALWAYS_FIRST/JAPANESE = 姓在前)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        return cl.name_order_of(self.melt, rec.get("culture"))

    def is_eastern_culture(self, cid):
        """东方文化 (姓在前)? 文化未知按 False (保守回退西方/未知)。"""
        return self.name_order(cid) in cl.EASTERN_NAME_ORDERS

    def is_custom_start(self, cid):
        """是否为自定义角色开局 (ruler_designer_characters)。"""
        return int(cid) in self._custom_starts

    def is_administrative(self, cid):
        """行政制角色? 依据缓存 landed.government。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        return (rec.get("landed") or {}).get("government") == "administrative_government"

    def is_landless(self, cid):
        """无地冒险者?"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        return (rec.get("landed") or {}).get("government") == "landless_adventurer_government"

    def emperor_of(self, cid):
        """角色是否为东方皇帝/中华皇帝之女·姐妹判定辅助:
        返回 (is_emperor, emperor_title)。is_emperor: 现任 h_/e_ 帝国级持有者。"""
        for h in reversed(self.cache.get("realm_history") or []):
            for tid, holder in (h.get("holders") or {}).items():
                if holder != cid:
                    continue
                key = (self._lt.get(str(tid)) or {}).get("key") or ""
                if key.startswith(("h_", "e_")):
                    return True, self.title(tid)
        return False, ""

    def east_empire_keys(self):
        """东方国家帝国 key 集: 中华 (h_china) + 日本/高丽/越南等东亚诸帝国。"""
        return {"h_china", "e_japan", "e_goryeo", "e_viet", "e_great_liao",
                "e_jin", "e_great_yuan", "e_mongol_empire", "e_kara_khitai",
                "e_zhongyuan", "e_yongliang", "e_jingyang", "e_liangyi",
                "e_lingnan", "e_andong", "e_amur", "e_goryeo"}

    def de_jure_top_key(self, county_tid):
        """伯爵领头衔 → 沿 de_jure_liege 上溯至顶层帝国, 返回顶层 title key。"""
        cur = str(county_tid)
        seen = set()
        top_key = ""
        while cur and cur not in seen:
            seen.add(cur)
            t = self._lt.get(cur) or {}
            if not t:
                break
            k = t.get("key") or ""
            if k:
                top_key = k
            dj = t.get("de_jure_liege")
            cur = str(dj) if dj is not None else None
        return top_key

    def player_top_empire_key(self):
        """玩家所在地的法理顶层帝国 key:
        取玩家位置 (location→伯爵领) 或营地 capital → de_jure 上溯。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return ""
        prov = self.character_location_province(pid)
        county = self.county_at_province(prov)
        if county is None:
            rec = (self.cache.get("characters") or {}).get(str(pid)) or {}
            camp = (rec.get("landed") or {}).get("domain") or [None]
            if camp[0] is not None:
                t = self._lt.get(str(camp[0])) or {}
                county = t.get("capital")
        if county is None:
            return ""
        return self.de_jure_top_key(county)

    def bio_style(self):
        """传记文风: 东方 (玩家所在地法理帝国属东方) → 'east' 中国式纪传体;
        否则 → 'west' 西式 (普鲁塔克式)。"""
        top = self.player_top_empire_key()
        if top in self.east_empire_keys():
            return "east"
        return "west"

    # ---- 日期 ----
    def date(self, d):
        return llm.fmt_cn_date(d)

    # ---- 领地链 / 营地 ----
    def liege_chain(self, tid):
        """从 tid 沿 de_facto_liege 上溯至顶: [(title_id, holder_id)]"""
        chain = []
        seen = set()
        cur = str(tid)
        while cur and cur not in seen:
            seen.add(cur)
            t = self._lt.get(cur) or {}
            if not t:
                break
            chain.append((int(cur), t.get("holder")))
            liege = t.get("de_facto_liege")
            cur = str(liege) if liege is not None else None
        return chain

    def county_at_province(self, province):
        """省份 id → 伯爵领头衔 id (经省份映射); 未知返回 None。"""
        if province is None:
            return None
        key = self.provmap.get(int(province))
        if not key:
            return None
        return self.title_by_key(key)

    def character_location_province(self, cid):
        c = self._chars.get(str(cid)) or {}
        loc = (c.get("alive_data") or {}).get("location") or {}
        return loc.get("location") if isinstance(loc, dict) else loc


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
    reason = _death_reason(f.table, d.get("reason"))
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
        "house": house_display(cache.get("house_name")),
        "birth": f.date(rec.get("birth")),
        "culture": f.culture(pid),
        "faith": f.faith(pid),
        "traits": "、".join(f.traits(pid)) or "（特质不详）",
        "government": f.government(pid),
    }
    thl = f.trait_history_lines(pid)
    if thl:
        p["trait_history"] = "；".join(thl)
    # v7: 家族家训 + 宫廷/营地官职
    mot = f.motto()
    if mot:
        p["motto"] = mot
    cpl, _cpch = f.court_positions_lines()
    if cpl:
        p["court_positions"] = "、".join(cpl)
    ld = rec.get("landed") or {}
    gov = ld.get("government")
    if gov == "landless_adventurer_government":
        # ---- 无地冒险者: 营地 ----
        camp_tid = (ld.get("domain") or [None])[0]
        p["landless"] = True
        p["camp_name"] = f.title(camp_tid) if camp_tid else "冒险者营地"
        laws = ld.get("laws") or []
        if laws:
            names = []
            for law in laws:
                v = L.loc(f.table, law) or law
                if v and v != law:
                    names.append(v)
            if names:
                p["camp_laws"] = "、".join(names)
        if ld.get("strength") is not None:
            p["camp_strength"] = str(ld.get("strength"))
        prov = f.character_location_province(pid)
        county_tid = f.county_at_province(prov)
        if county_tid is None and camp_tid:
            # 兜底: 营地头衔 capital 视为所在郡
            t = (f.melt.get("landed_titles") or {}).get("landed_titles") or {}
            cap = (t.get(str(camp_tid)) or {}).get("capital")
            county_tid = cap
        chain = f.liege_chain(county_tid) if county_tid else []
        if county_tid and chain:
            cname = f.title(county_tid)
            p["camp_county"] = cname
            holder = chain[0][1]
            if holder is not None:
                p["camp_county_holder"] = f.name_or(holder)
            mids = chain[1:-1]
            if mids:
                parts = []
                for tid, hid in mids:
                    tn = f.title(tid)
                    hn = f.name_or(hid, "") if hid is not None else ""
                    parts.append(f"{tn}（{hn}）" if hn else tn)
                p["camp_liege_chain"] = "、".join(parts)
            top_tid, top_holder = chain[-1]
            p["camp_top_liege"] = f"{f.title(top_tid)}（{f.name_or(top_holder)}）" \
                if top_holder is not None else f.title(top_tid)
    else:
        # ---- 有地领主 ----
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
            f"{_death_reason(f.table, pd.get('reason'))}"
            + (f"，凶手为{f.name_or(pd.get('killer'))}" if pd.get("killer") else "。")
        )
    # 家庭
    fam = rec.get("family") or {}
    spouse_ids = list(dict.fromkeys(
        (fam.get("primary_spouse") or []) + (fam.get("spouse") or [])))
    p["spouses"] = "、".join(f.name_or(s) for s in spouse_ids if f.name(s))
    p["former_spouses"] = "、".join(f.name_or(s) for s in (fam.get("former_spouses") or []) if f.name(s))
    # v8: 妾 (正向 concubine + 反向 concubinist, 已在缓存合并去重)
    p["concubines"] = "、".join(f.name_or(s) for s in (fam.get("concubine") or []) if f.name(s))
    p["former_concubines"] = "、".join(f.name_or(s) for s in (fam.get("former_concubines") or []) if f.name(s))
    p["children"] = "、".join(f.name_or(c) for c in (fam.get("child") or []) if f.name(c))
    p["father"] = "、".join(f.name_or(x) for x in (fam.get("father") or []) if f.name(x))
    p["mother"] = "、".join(f.name_or(x) for x in (fam.get("mother") or []) if f.name(x))
    p["siblings"] = "、".join(f.name_or(x) for x in (fam.get("siblings") or []) if f.name(x))
    # v5: 自定义角色 (无谱系) — 家世通用文本覆盖
    if f.is_custom_start(pid):
        p["custom_start"] = True
    # v5: 真正父亲 (私生子场景; 与法理父不同才渲染)
    rf = (fam.get("real_father") or [None])[0]
    if rf is not None:
        rfname = f.name_or(rf)
        if rfname:
            p["real_father"] = rfname
    # 主角历任高位头衔
    ht = f.held_titles(pid)
    if ht:
        p["titles_held"] = "；".join(ht)
    return p


def _character_profiles(f):
    """每个缓存角色: 干净档案 + 记忆 + 死亡 + 亲属 + 历任头衔。"""
    out = {}
    for cid, rec in (f.cache.get("characters") or {}).items():
        cid = int(cid)
        name = f.name_or(cid)
        prof = {
            "name": name,
            "house": house_display(rec.get("house_name")),
            "birth": f.date(rec.get("birth")),
            "culture": f.culture(cid),
            "faith": f.faith(cid),
            "traits": "、".join(f.traits(cid)),
        }
        thl = f.trait_history_lines(cid)
        if thl:
            prof["trait_history"] = "；".join(thl)
        # v7: 该角色在玩家宫廷/营地中的官职 (最新快照, 反向取最后一年)
        for h in reversed(f.cache.get("court_positions") or []):
            for p in h.get("positions") or []:
                if p.get("employee") == cid:
                    zh = L.loc(f.table, p.get("type")) or ""
                    if zh and zh != p.get("type"):
                        prof["court_position"] = zh
                    break
            if prof.get("court_position"):
                break
        fam = rec.get("family") or {}
        spouse_ids = list(dict.fromkeys(
            (fam.get("primary_spouse") or []) + (fam.get("spouse") or [])))
        prof["spouses"] = "、".join(f.name_or(s) for s in spouse_ids if f.name(s))
        prof["concubines"] = "、".join(f.name_or(s) for s in (fam.get("concubine") or []) if f.name(s))
        prof["children"] = "、".join(f.name_or(c) for c in (fam.get("child") or []) if f.name(c))
        prof["father"] = "、".join(f.name_or(x) for x in (fam.get("father") or []) if f.name(x))
        prof["mother"] = "、".join(f.name_or(x) for x in (fam.get("mother") or []) if f.name(x))
        prof["siblings"] = "、".join(f.name_or(x) for x in (fam.get("siblings") or []) if f.name(x))
        # v5: 自定义角色 + 真正父亲 (私生子)
        if f.is_custom_start(cid):
            prof["custom_start"] = True
        rf = (fam.get("real_father") or [None])[0]
        if rf is not None:
            rfname = f.name_or(rf)
            if rfname:
                prof["real_father"] = rfname
        ht = f.held_titles(cid)
        if ht:
            prof["titles_held"] = "；".join(ht)
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


def _realm_facts(f):
    """朝局数据 (v4): 玩家上位链 + 帝国/王国级头衔持有者变化。"""
    out = {}
    # 玩家上位链 (最后快照)
    pid = f.cache.get("player_id")
    if pid is not None:
        prov = f.character_location_province(pid)
        county_tid = f.county_at_province(prov)
        chain = f.liege_chain(county_tid) if county_tid else []
        if chain:
            parts = []
            for tid, hid in chain:
                hn = f.name_or(hid, "") if hid is not None else ""
                parts.append(f"{f.title(tid)}（{hn}）" if hn else f.title(tid))
            out["liege_chain"] = " → ".join(parts)
    # 高位头衔持有者变化 (h_/e_ 帝国级 + 王国级相关)
    changes = []
    holder_seq = {}
    for h in f.cache.get("realm_history") or []:
        for tid, holder in (h.get("holders") or {}).items():
            t = (f.melt.get("landed_titles") or {}).get("landed_titles") or {}
            key = (t.get(str(tid)) or {}).get("key") or ""
            if not (key.startswith(("h_", "e_", "k_"))):
                continue
            holder_seq.setdefault(tid, []).append((h.get("date"), holder))
    for tid, seq in holder_seq.items():
        prev = None
        bits = []
        for d, holder in seq:
            if holder == prev:
                continue
            hn = f.name_or(holder, "") if holder is not None else "无"
            bits.append(f"{f.date(d)}：{hn}")
            prev = holder
        if len(bits) > 1:
            changes.append(f"{f.title(tid)}：{'，'.join(bits)}")
    if changes:
        out["holder_changes"] = changes
    return out


def _killed_by_player(f):
    """主角所杀之人 (v8): 五源合一, 去重。
    源: 1) 主角缓存 kills (alive_data.kills ∪ dead_data.kills 跨年累积)
        2) player_death.kills (死亡档 dead_data.kills)
        3) 主角 successful_murder 记忆 victim
        4) 全缓存死亡记录 killer == 主角
        5) 最新熔件中 dead_data.killer == 主角 (受害者不在缓存时兜底)
    返回 [(cid, 档案dict, 死句, 相关事件)] 按死亡日期排序。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    killed = set()
    # 1) 缓存击杀 (跨年累积: alive_data.kills ∪ dead_data.kills)
    prec = (cache.get("characters") or {}).get(str(pid)) or {}
    for k in prec.get("kills") or []:
        killed.add(int(k))
    # 2) player_death.kills (死亡检测时已写入 dead_data.kills)
    dd = cache.get("player_death") or {}
    for k in dd.get("kills") or []:
        killed.add(int(k))
    # 3) 主角 successful_murder 记忆 victim
    for mem in prec.get("memories") or []:
        if mem.get("type") == "successful_murder":
            v = (mem.get("participants") or {}).get("victim")
            if isinstance(v, int):
                killed.add(v)
    # 4) 全缓存死亡记录 killer == 主角
    for cid, rec in (cache.get("characters") or {}).items():
        if int(cid) == pid:
            continue
        d = rec.get("death") or {}
        if d.get("killer") == pid:
            killed.add(int(cid))
    # 5) 最新熔件受害者反查 (dead_data.killer == 主角)
    for cid, c in f._chars.items():
        if not isinstance(c, dict) or int(cid) == pid:
            continue
        d = (c.get("dead_data") or {}).get("killer")
        if d is not None and int(d) == pid:
            killed.add(int(cid))
    # 每个被杀者: 档案 + 死句 + 恢复的记忆事件 (由缓存提供, 死前档回溯已并入)
    out = []
    for cid in killed:
        prof = (f.cache.get("characters") or {}).get(str(cid)) or {}
        # 受害者不在缓存时, 从最新熔件 dead_data 补死句
        ds = _death_sentence(f, cid)
        if not ds:
            mc = f._chars.get(str(cid)) or {}
            mdd = (mc or {}).get("dead_data") or {}
            if mdd and mdd.get("date"):
                reason = _death_reason(f.table, mdd.get("reason"))
                if reason in ("处决", "谋杀", "毒杀", "刑罚", "决斗", "蛇噬", "斗殴"):
                    reason = "被" + reason
                ds = f"{f.name_or(cid)}殁于{f.date(mdd.get('date'))}，{reason}。"
        entry = {
            "id": cid,
            "name": f.name_or(cid),
            "birth": f.date(prof.get("birth")),
            "death": ds or "（死因不详）",
            "death_date": (prof.get("death") or {}).get("date") or "9999.9.9",
            "house": house_display(prof.get("house_name")),
            "culture": f.culture(cid),
            "faith": f.faith(cid),
            "traits": "、".join(f.traits(cid)),
            "events": [],
            "role": "",   # 与主角的关系 (子/友/敌...) 由 biography 侧根据记忆推断
        }
        for mem in prof.get("memories") or []:
            s = _mem_sentence(f, cid, mem)
            if s:
                entry["events"].append(f"{f.date(mem.get('creation_date'))}，{s}")
        entry["events"].sort()
        out.append(entry)
    out.sort(key=lambda e: cl.date_key(e["death_date"]))
    return out


def _imperial_daughters_sisters(f, spouses):
    """妻妾中「XX公主头衔 或 中华皇帝之女/姐妹」者。
    判定: 1) 该妻妾曾任/现任 h_/e_ 帝国级头衔 (公主/女王头衔);
         2) 其父或兄弟 (family.father/siblings) 中有人为 h_china 或中华系帝国持有者。"""
    pid = f.cache.get("player_id")
    out = []
    # 中华皇帝集: realm_history 中 h_china (及中华法理域帝国) 历任持有者
    china_emperors = set()
    for h in f.cache.get("realm_history") or []:
        for tid, holder in (h.get("holders") or {}).items():
            if holder is None:
                continue
            key = (f._lt.get(str(tid)) or {}).get("key") or ""
            if key == "h_china" or key in ("e_zhongyuan", "e_yongliang",
                                           "e_jingyang", "e_liangyi", "e_lingnan"):
                china_emperors.add(int(holder))
    for sid in spouses:
        rec = (f.cache.get("characters") or {}).get(str(sid)) or {}
        name = f.name_or(sid)
        if not name:
            continue
        reasons = []
        # 1) 自身有公主/女王头衔 (帝国级, 女眷)
        is_emp, etitle = f.emperor_of(sid)
        if is_emp:
            reasons.append(f"自任{etitle}")
        # 2) 父/兄弟为中华皇帝
        fam = rec.get("family") or {}
        rel = []
        for fid in (fam.get("father") or []):
            if int(fid) in china_emperors:
                rel.append(f"父{f.name_or(fid)}")
        for bid in (fam.get("siblings") or []):
            if int(bid) in china_emperors:
                rel.append(f"兄{f.name_or(bid)}")
        if rel:
            reasons.extend(rel)
        if reasons:
            out.append({"id": sid, "name": name, "reasons": reasons})
    return out


def _wandering_trail(f):
    """游侠行纪 (v5): 玩家所在地历史 (cache.player_locations) → 中文轨迹。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    out = []
    hist = cache.get("player_locations") or []
    for i, loc in enumerate(hist):
        prov = loc.get("province")
        county = f.county_at_province(prov)
        if county is None:
            continue
        cname = f.title(county)
        holder = ""
        chain = f.liege_chain(county) if county else []
        if chain:
            h = chain[0][1]
            if h is not None:
                holder = f.name_or(h, "")
        bits = [f"{f.date(loc.get('date'))}驻{cname}"]
        if holder:
            bits.append(f"{holder}执掌")
        top = chain[-1] if chain else None
        if top and top[1] is not None:
            bits.append(f"最高领主{f.name_or(top[1])}")
        out.append("，".join(bits) + "。")
    return out


def _court_luminaries(f):
    """群英录 (v5): 行政制玩家时, 朝中要员 (有政治类记忆或历任高位头衔者)。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    names = []
    seen = set()
    for cid, rec in (cache.get("characters") or {}).items():
        if int(cid) == pid:
            continue
        prof = (f.cache.get("characters") or {}).get(cid) or {}
        if not prof.get("name"):
            continue
        # 有政治类记忆 或 历任高位头衔
        has_pol = any(m["type"] in POLITICAL_TYPES_KEYS
                      for m in rec.get("memories") or [])
        if has_pol or prof.get("titles_held"):
            n = prof.get("house") or ""
            nm = prof["name"]
            full = f"{n}{nm}" if n and nm and not nm.startswith(n) else nm
            if full not in seen:
                seen.add(full)
                names.append(full)
    return names


def _genealogy(f):
    """世系 (v5 终传附录): 主角 + 父母 + 妻妾 + 子女 + 兄弟姊妹 谱系行。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    fam = rec.get("family") or {}
    lines = []
    pname = f.name_or(pid)
    lines.append(f"一世 {pname}（{f.date(rec.get('birth'))}生）")
    for key, label in (("father", "父"), ("mother", "母"),
                       ("primary_spouse", "正妻"), ("spouse", "侧室"),
                       ("concubine", "妾"), ("former_concubines", "前妾"),
                       ("child", "子女"), ("siblings", "兄弟姊妹"),
                       ("former_spouses", "前妻")):
        ids = fam.get(key) or []
        if not ids:
            continue
        bits = []
        for x in ids:
            n = f.name_or(x)
            if n:
                bits.append(n)
        if bits:
            lines.append(f"　{label}：{'、'.join(bits)}")
    return lines


def build_facts(cache, melt, names_path=None):
    """渲染干净事实集。melt 为 dict (已加载)。"""
    f = Facts(cache, melt, names_path)
    period = ""
    sources = cache.get("sources") or []
    if sources:
        period = f"{sources[0]} – {sources[-1]}"
    cpl, cpch = f.court_positions_lines()
    # v8: 死因中文化 (总纲【卒年】不再泄漏英文 key, 干净事实铁律)
    pd = cache.get("player_death")
    if pd:
        pd = dict(pd)
        pd["reason_zh"] = _death_reason(f.table, pd.get("reason"))
    facts = {
        "house": house_display(cache.get("house_name")),
        "player_name": cache.get("player_name"),
        "player_id": cache.get("player_id"),
        "period": period,
        "sources": sources,
        "protagonist": _protagonist(f),
        "timeline": _timeline(f),
        "characters": _character_profiles(f),
        "realm": _realm_facts(f),
        "player_death": pd,
        "last_date": cache.get("last_date"),
        # v5 新增
        "bio_style": f.bio_style(),
        "killed": _killed_by_player(f),
        "wandering": _wandering_trail(f),
        "luminaries": _court_luminaries(f),
        "genealogy": _genealogy(f),
        # v7 新增: 宫廷/营地官职 + 家族家训
        "court_positions": cpl,
        "court_position_changes": cpch,
        "house_motto": f.motto(),
    }
    # 妻族传 (仅限公主头衔/中华皇帝之女·姐妹)
    pid = cache.get("player_id")
    if pid is not None:
        rec = (cache.get("characters") or {}).get(str(pid)) or {}
        fam = rec.get("family") or {}
        spouse_ids = list(dict.fromkeys(
            (fam.get("primary_spouse") or []) + (fam.get("spouse") or [])
            + (fam.get("former_spouses") or [])))
        facts["imperial_spouses"] = _imperial_daughters_sisters(f, spouse_ids)
    else:
        facts["imperial_spouses"] = []
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
