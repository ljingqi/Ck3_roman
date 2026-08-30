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

# v11: 游戏 UI 腔/坏文本死因 → 传记雅化 (优先于本地化值, 本地化文案是游戏内
# 通知腔, 如 blind = 「因绊倒坠落而失去的生命」, 直接进传记会读起来像抄游戏)。
FLAVOR_DEATH_ZH = {
    "blind": "因绊倒坠落而亡",
    "death_fall": "因坠落而亡",
    "death_wounded_1": "伤重不治",
    "death_wounded_2": "伤重不治",
    "death_maimed": "重伤不治",
    "death_head_ripped_off": "身首异处",
    "death_apoplexy": "中风而亡",
    "death_drinking_passive": "酗酒而亡",
    # 成功且未败露的谋杀: 游戏显示「神秘死亡」, 传记直用太怪
    "death_mysterious": "死于一场未曾败露的谋杀",
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

# v11: 刺客列传击杀数超过该阈值时, 剔除 lowborn (无家族且非家人/友/仇) 死者,
# 压缩提示词体积, 保住模型注意力 (168 人 → 142 人)。
KILL_LOWBORN_THRESHOLD = 15


def _kill_keep_ids(cache, pid):
    """击杀者名单里必须保留的角色 id 集: 主角家人 (含前妻/妾) + 结友/结仇者。"""
    keep = set()
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    fam = rec.get("family") or {}
    for k in ("primary_spouse", "spouse", "former_spouses", "child",
              "concubine", "former_concubines"):
        for x in (fam.get(k) or []):
            if isinstance(x, int):
                keep.add(x)
    rel_types = {"became_rivals", "became_grudge", "became_nemesis",
                 "became_friends", "became_soulmates", "became_blood_brother"}
    for cid, r in (cache.get("characters") or {}).items():
        for m in r.get("memories") or []:
            if m.get("type") in rel_types and pid in (m.get("participants") or {}).values():
                keep.add(int(cid))
    return keep


# 父名制规则表 (由 experiments/patronym_scan.py 从游戏 name_lists 生成):
# {文化模板: {pm/pf/sm/sf 键, pm_zh/pf_zh/sm_zh/sf_zh 中文}}
_PATRONYM_RULES = None


def _patronym_rules():
    global _PATRONYM_RULES
    if _PATRONYM_RULES is None:
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "patronym_rules.json")
            with open(p, encoding="utf-8") as fp:
                _PATRONYM_RULES = json.load(fp)
        except Exception:
            _PATRONYM_RULES = {}
    return _PATRONYM_RULES


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


def _dynasty_display(dn, hn):
    """角色宗族显示名 (v14): 宗族名优先 (东方名序的姓 — 藤原/崔/金),
    缺失回退家族名; 单字加「氏」(边氏)。"""
    return house_display(dn or hn)


def _house_branch(dn, hn):
    """角色家族(分家)显示名 (v14 风味): 家族名与宗族名不同时给出
    (北家/庆州崔/交州金 — 游戏只显示宗族姓, 分家作风味补充),
    相同 (创始家=宗族同名) 时返回 ''。"""
    if not dn or not hn or dn == hn:
        return ""
    return house_display(hn)


def _trait_name(table, key):
    """特质 key → 中文: trait_<key> → <key> → 兜底表; 未知返回 '' (跳过, 不外泄 key)。"""
    if not key:
        return ""
    for cand in (f"trait_{key}", key):
        v = L.loc(table, cand)
        if v:
            return v
    return TRAIT_ZH.get(key, "")


def _daynum(d):
    """'935.11.5' → 天序号 (年×372+月×31+日, 短跨度够用)。"""
    try:
        y, m, dd = (int(x) for x in str(d).split(".")[:3])
        return y * 372 + m * 31 + dd
    except Exception:
        return 0


def _death_reason(table, reason):
    """死因 key → 中文: v11 先查雅化表 (游戏腔/坏文本), 再本地化, 最后兜底表。"""
    if not reason:
        return "身故"
    v = FLAVOR_DEATH_ZH.get(reason)
    if v:
        return v
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

# 名字已含国名/层级词后缀时不追加层级词 (v13 扩: 汗国/教宗国/属邦等,
# 修复「黠戛斯汗国帝国」「教宗国王国」式叠加)。
_STATE_SUFFIX_RE = re.compile(
    r"(帝国|王国|汗国|大公国|公国|侯国|伯国|苏丹国|哈里发国|酋长国|"
    r"教宗国|属邦|皇朝|王朝|行台|天朝|国|邦|朝)$")


class Facts:
    """一次 build_facts 的上下文: 缓存 + melt + 名字/头衔/本地化解析。
    as_of: 传记数据截止日期 (十年传记 = 十年末; 终传/在世 = 最后档期)。
    非空时 官职/称号/历任/时间线/朝局 均只取该日期之前的事实 (v11)。"""

    def __init__(self, cache, melt, names_path, as_of=None):
        self.cache = cache
        self.melt = melt
        self.names_path = names_path
        self.as_of = as_of
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
        # v11: 语言 → 文化模板列表 反查索引 (同一语言多文化共享, 如 language_norse
        # 同时被 norman/norse 持有; 推断时优先有父名规则的模板)
        self._lang_to_tpl = {}
        for _cid, _e in ((melt.get("culture_manager") or {}).get("cultures") or {}).items():
            if not isinstance(_e, dict):
                continue
            _lg = _e.get("language")
            if _lg:
                self._lang_to_tpl.setdefault(_lg, []).append(_e.get("culture_template") or "")
        # v11: 独立性 O(1): 全量封臣 id 集 + 每角色缓存 (历任/官职大量调用)
        self._vassal_ids = set()
        for _k, _c in ((melt.get("vassal_contracts") or {}).get("database") or {}).items():
            if isinstance(_c, dict) and _c.get("vassal") is not None:
                try:
                    self._vassal_ids.add(int(_c["vassal"]))
                except Exception:
                    pass
        self._indep_cache = {}
        self._hold_cache = {}  # (cid, as_of) -> 持有区间 (历任/官职/称号复用)
        # v11: 头衔 holder 序列预计算 (历任/朝局多次全表扫描用)
        self._title_seqs = {}
        for _tid, _t in self._lt.items():
            if not isinstance(_t, dict):
                continue
            _h = _t.get("history") or {}
            if isinstance(_h, dict) and _h:
                self._title_seqs[int(_tid)] = sorted(
                    _h.items(), key=lambda x: cl.date_key(x[0]))
        # v11: 持有者索引 {cid: {tid: [(gain, loss|None, loss_type), ...]}} —
        # 一次遍历全部 title history 建好, 历任/官职/称号按角色 O(1) 取。
        # 同一 (tid) 同 holder 跨多段 (失而复得) 保留多段; 已按 as_of 截断
        # (事件 > as_of 的丢弃, 开区间自然延伸到 as_of)。
        self._holder_intervals = {}
        _ao = cl.date_key(as_of) if as_of else None
        for _tid, _seq in self._title_seqs.items():
            cur = None
            gain = None
            for _d, _ev in _seq:
                if _ao is not None and cl.date_key(_d) > _ao:
                    break
                _h = _ev.get("holder") if isinstance(_ev, dict) else _ev
                _typ = _ev.get("type") if isinstance(_ev, dict) else ""
                if _h is None:
                    if cur is not None and gain is not None:
                        self._holder_intervals.setdefault(cur, {}).setdefault(
                            _tid, []).append((gain, _d, _typ or ""))
                    cur, gain = None, None
                    continue
                _hid = int(_h)
                if _hid == cur:
                    if _typ == "destroyed":
                        if gain is not None:
                            self._holder_intervals.setdefault(cur, {}).setdefault(
                                _tid, []).append((gain, _d, "destroyed"))
                        cur, gain = None, None
                    continue
                if cur is not None and gain is not None:
                    self._holder_intervals.setdefault(cur, {}).setdefault(
                        _tid, []).append((gain, _d, _typ or ""))
                cur, gain = _hid, _d
            if cur is not None and gain is not None:
                self._holder_intervals.setdefault(cur, {}).setdefault(
                    _tid, []).append((gain, None, ""))
        # v11: realm_history 快照持有者索引 {cid: {tid: [快照下标...]}} —
        # 只补 title history 未覆盖的头衔 (被剪除的王国等)。
        self._realm_snaps = [h for h in (cache.get("realm_history") or [])
                             if not as_of or cl.date_key(h.get("date")) <= cl.date_key(as_of)]
        self._realm_snaps.sort(key=lambda h: cl.date_key(h.get("date")))
        self._realm_holder_titles = {}  # cid -> {tid: set(下标)}
        for _i, _h in enumerate(self._realm_snaps):
            for _tid, _holder in (_h.get("holders") or {}).items():
                if _holder is not None and int(_tid) not in self._holder_intervals.get(int(_holder), {}):
                    self._realm_holder_titles.setdefault(int(_holder), {}).setdefault(
                        int(_tid), set()).add(_i)
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
        # v13: 姓名渲染缓存 (一次 build_facts 内缓存不可变)
        self._name_cache = {}
        self._tpl_memo = {}

    # ---- 名字 ----
    def name(self, cid):
        """角色 id → 显示名 (v13 统一出口): 父名制文化 → 名·父名
        (崔佛·富兰克林松, 父名替代家族名); 其余文化按名序 (东方姓在前, 西方名·姓)。
        文化缺失 (玩家/死者) 时经亲属链推断, 详见 cache_lib.display_name。
        结果按 cid 缓存 (同一次 build_facts 内缓存不可变, 数千次渲染只需算一次)。"""
        if cid is None:
            return ""
        c = self._name_cache.get(cid)
        if c is not None:
            return c
        c = cl.display_name(self.cache, cid, melt=self.melt,
                            names_path=self.names_path, chars=self._chars,
                            memo=self._tpl_memo)
        self._name_cache[cid] = c
        return c

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
        # v13: 朝廷职司 (尚书省六部/御史台/枢密院, e_minister_*) — 官职非诸侯,
        # 只给名字 (吏部/御史台), 不追加「帝国/行台」层级词。
        if key.startswith("e_minister_"):
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
            # 名字已含任意国名/层级词后缀 (神圣罗马帝国/黠戛斯汗国/教宗国) 或词为空时不追加
            if word and not _STATE_SUFFIX_RE.search(name):
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

    # ---- v11: 按日期头衔名 / 历任 (首要头衔演进) ----

    _TT_RANK = {"h_": 6, "e_": 5, "k_": 4, "d_": 3, "c_": 2, "b_": 1, "x_": 0}

    def _tier_word_at(self, tid, government, independent=False):
        """头衔层级词 (v11): 天朝制独立王国用「国」(青徐国), 其余沿用政体层级词
        (皇朝/路/镇/州府…), 缺失回退通用词。"""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        tier = ""
        for pfx, tv in L.TIER_KEY_OF_PREFIX.items():
            if key.startswith(pfx):
                tier = tv
                break
        if not tier:
            return ""
        if government in self._CELESTIAL_LIKE_GOVS and tier == "kingdom" and independent:
            v = L.loc(self.table, "kingdom_celestial_chinese_independent")
            if v and not v.startswith("$") and not v.startswith("["):
                return v
        return L.tier_word(self.table, government, tier)

    def _name_at_date(self, tid, date):
        """头衔在某日期的名称 (不含层级词): title_history_names 最近一次更名
        (本地化键 dynn_title_zhou / 直写名 青徐), 无更名史回退基础名。"""
        t = self._lt.get(str(tid)) or {}
        tnd = t.get("title_name_data") or {}
        best = None
        if date:
            for h in (tnd.get("title_history_names") or []):
                try:
                    if h.get("date") and cl.date_key(str(h["date"])) <= cl.date_key(str(date)):
                        best = h["name"]
                except Exception:
                    continue
        if best is not None:
            return L.loc(self.table, str(best)) or str(best)
        return (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()

    def _title_name_at(self, tid, date, cid=None):
        """头衔在某日期的完整名 (v11): 按日期名 + 层级词 (独立王国=国)。
        cid 提供时按该角色当前独立性取词 (历任/朝局用)。"""
        if tid is None:
            return ""
        t = self._lt.get(str(tid)) or {}
        key = t.get("key") or ""
        if key.startswith("x_"):  # 营地/家族等特殊头衔: 只给名字
            return self._name_at_date(tid, date) or L.loc(self.table, key) or key
        nm = self._name_at_date(tid, date)
        if not nm:
            nm = L.loc(self.table, key)
        if not nm:
            nm = key
        if key.startswith("e_minister_"):  # v13: 朝廷职司只给名字
            return nm
        gov = self._title_government(tid)
        independent = self._is_independent(cid) if cid is not None else False
        word = self._tier_word_at(tid, gov, independent)
        if word and not any(nm.endswith(w) for w in self._rank_words):
            return f"{nm}{word}"
        return nm

    def _name_in_span(self, tid, start, end, cid=None):
        """头衔在 [start, end] 区间中点的完整名 (v11): 取区间中点日期命名,
        避开更名当日的 1-2 天过渡名 (鄂路→青徐、青徐→周), 即任期内的稳定名。"""
        if tid is None:
            return ""
        if start and end:
            try:
                sy = [int(x) for x in str(start).split(".")[:3]]
                ey = [int(x) for x in str(end).split(".")[:3]]
                if len(sy) == 3 and len(ey) == 3:
                    mid = ".".join(str((a + b) // 2) for a, b in zip(sy, ey))
                    return self._title_name_at(tid, mid, cid)
            except Exception:
                pass
        return self._title_name_at(tid, start, cid)

    def _hold_intervals(self, cid, as_of=None):
        """角色持有头衔的时间区间 (v11): {tid: [(gain, loss|None, loss_type), ...]}。
        title history 精确日期为主 (索引 O(1)); realm_history 快照兜底
        (title history 被剪除的头衔, 如已毁的王国)。结果按 (cid, as_of) 缓存。"""
        as_of = as_of or self.as_of
        cache_key = (cid, as_of)
        if cache_key in self._hold_cache:
            return self._hold_cache[cache_key]
        out = {}
        base = self._holder_intervals.get(cid) or {}
        if as_of == self.as_of:
            out = {tid: list(ivs) for tid, ivs in base.items()}
        else:
            # 不同 as_of: 按日期过滤 (开区间折到 as_of)
            ao = cl.date_key(as_of) if as_of else None
            for tid, ivs in base.items():
                kept = []
                for (g, l, lt) in ivs:
                    if ao is not None and cl.date_key(g) > ao:
                        continue
                    if l and ao is not None and cl.date_key(l) > ao:
                        kept.append((g, None, lt))
                    else:
                        kept.append((g, l, lt))
                if kept:
                    out[tid] = kept
        # realm 快照兜底: 连续持有段 → 一段区间 (丢头衔日 = 下个快照日)
        ridx = self._realm_holder_titles.get(cid) or {}
        n_snaps = len(self._realm_snaps)
        for tid, idxs in ridx.items():
            if tid in out:
                continue
            runs = []
            cur_run = None
            prev_i = None
            for i in sorted(idxs):
                if cur_run is None:
                    cur_run = i
                elif i == prev_i + 1:
                    pass
                else:
                    runs.append((cur_run, prev_i))
                    cur_run = i
                prev_i = i
            if cur_run is not None:
                runs.append((cur_run, prev_i))
            for (a, b) in runs:
                gain = self._realm_snaps[a].get("date")
                loss = self._realm_snaps[b + 1].get("date") if b + 1 < n_snaps else None
                out.setdefault(tid, []).append((gain, loss, ""))
        self._hold_cache[cache_key] = out
        return out

    def _primary_group(self, held):
        """按持有集计算「主要头衔组」[(gain_date, tid)] (v11): held = {tid: gain_date}
        - 州府/县/堡 (c_/b_) 不进组 (如 898-911 的登州伯爵领等);
        - 有 公国(d_) 及以上或营地(x_) 时: 层级 ≥ 王国只留首要; 公国/营地层取
          首要 + 全部营地 (同级营地/庄园并写, 游牧营地/淄青公国);
        - 只有 州府/县 时: 取最高层级单个。
        - v13: 朝廷职司 (e_minister_*) 不进组 (官职非领地, 由官职行呈现)。"""
        if not held:
            return []
        items = []
        for tid, gain in held.items():
            key = (self._lt.get(str(tid)) or {}).get("key") or ""
            if key.startswith("e_minister_"):
                continue
            items.append((tid, self._TT_RANK.get(key[:2], 0), gain))
        if not items:
            return []  # 仅持朝廷职司 (官职非领地)
        majors = [it for it in items if it[1] >= 3 or it[1] == 0]  # d_+ 或营地
        if not majors:
            # 仅州府/县/堡: 最高层级最早获得的一个
            t0 = sorted(items, key=lambda it: (-it[1], cl.date_key(it[2])))[0]
            return [(t0[2], t0[0])]
        max_tier = max(r for _t, r, _g in majors)
        tops = sorted([it for it in majors if it[1] == max_tier],
                      key=lambda it: cl.date_key(it[2]))
        if max_tier >= 4:  # k_ 及以上: 只记首要
            t0 = tops[0]
            return [(t0[2], t0[0])]
        camps = [it for it in majors if (self._lt.get(str(it[0])) or {}).get("key", "").startswith("x_")]
        picked = tops[:1] + [c for c in camps if c != tops[0]]
        return [(g, t) for t, _r, g in sorted(picked, key=lambda it: cl.date_key(it[2]))]

    def _primary_title_at(self, cid, as_of=None):
        """角色在 as_of 日期的首要头衔 (tier, tid): 最高层级中最早获得者;
        无头衔 (仅营地) 返回 (None, tid)。"""
        held = {}
        for tid, ivs in self._hold_intervals(cid, as_of).items():
            if ivs and ivs[-1][1] is None:
                held[tid] = ivs[-1][0]
        if not held:
            return None, None
        items = [(tid, self._TT_RANK.get((self._lt.get(str(tid)) or {}).get("key", "")[:2], 0), g)
                 for tid, g in held.items()]
        max_tier = max(r for _t, r, _g in items)
        tops = sorted([it for it in items if it[1] == max_tier],
                      key=lambda it: cl.date_key(it[2]))
        tid = tops[0][0]
        tier = self._RANK_TIER.get(max_tier) if max_tier >= 1 else None
        return tier, tid

    def held_titles(self, cid):
        """历任 (v11): 只记首要头衔的变化; 层级≤公国时同级营地/庄园并写。
        依 title history (精确) + realm_history (兜底); 头衔名按日期 + 独立词
        (独立天朝王国用「国」)。返回 ['867年1月1日任范德林帮之主', ...]"""
        intervals = self._hold_intervals(cid)
        events = []
        loss_types = {}  # (tid, date_key) -> type
        for tid, ivs in intervals.items():
            for (g, l, lt) in ivs:
                events.append((cl.date_key(g), g, tid, 1))
                if l:
                    events.append((cl.date_key(l), l, tid, -1))
                    loss_types[(tid, cl.date_key(l))] = lt
        events.sort(key=lambda x: x[0])
        # 按日批量应用: 同日事件整体生效 (毁营地/建营地/得州府同日, 避免中间态)
        by_day = {}
        for dk, d, tid, delta in events:
            by_day.setdefault(dk, []).append((d, tid, delta))
        held = {}
        phases = []
        prev_group = None
        prev_held = set()
        for dk in sorted(by_day):
            batch = by_day[dk]
            d = batch[0][0]
            for _dd, tid, delta in batch:
                if delta == 1:
                    held[tid] = _dd
                else:
                    held.pop(tid, None)
            group = self._primary_group(held)
            if group and group != prev_group:
                phases.append((d, group, set(prev_held) - set(held)))
                prev_group = group
            prev_held = set(held)
        if not phases:
            return []
        # 阶段终点: 下一阶段开始日 / 无则 as_of (或末档)
        span_end = self.as_of or self.cache.get("last_date")
        out = []
        prev_ids = []
        for i, (d, group, lost_now) in enumerate(phases):
            end = phases[i + 1][0] if i + 1 < len(phases) else span_end
            ids = [tid for _g, tid in group]
            names = [n for n in (self._name_in_span(t, d, end, cid) for t in ids) if n]
            if not names:
                continue
            line = f"{self.date(d)}任{'/'.join(names)}之主"
            # 真正失去 (不在持有集) 且此前在组内的头衔
            lost_names = []
            for t in prev_ids:
                if t in ids or t not in lost_now:
                    continue
                lt = loss_types.get((t, cl.date_key(d)))
                nm = self._title_name_at(t, d, cid)
                if not nm:
                    continue
                lost_names.append(("毁弃" if lt == "destroyed" else "让出") + nm)
            prev_ids = ids
            if lost_names:
                line += "（" + "、".join(lost_names) + "）"
            out.append(line)
        return out

    def title_by_key(self, key):
        if not key:
            return None
        return self._title_by_key.get(key)

    # ---- 官职名 / 王子称号 (v9) ----

    _TIER_KEY = {"hegemon": "hegemon", "empire": "emperor", "kingdom": "king",
                 "duchy": "duke", "county": "count", "barony": "baron"}
    _TIER_RANK = {"h_": 6, "e_": 5, "k_": 4, "d_": 3, "c_": 2, "b_": 1}
    _RANK_TIER = {6: "hegemon", 5: "empire", 4: "kingdom", 3: "duchy",
                  2: "county", 1: "barony"}
    _CELESTIAL_LIKE_GOVS = {"celestial_government", "meritocratic_government",
                            "steppe_admin_government", "administrative_government"}

    def title_base_name(self, tid):
        """头衔基础名 (不含层级词/官职词): custom → name → 本地化 → key。"""
        if tid is None:
            return ""
        t = self._lt.get(str(tid)) or {}
        tnd = t.get("title_name_data") or {}
        name = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
        if not name:
            name = L.loc(self.table, t.get("key") or "")
        if not name:
            name = t.get("key") or ""
        return name

    def _primary_title(self, cid):
        """角色首要头衔 (tier, tid): 最高层级, 同级取 domain 首个 (法兰西国王兼
        阿基坦王国 → 法兰西王国)。无头衔返回 (None, None)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        dom = (rec.get("landed") or {}).get("domain") or []
        if not dom:
            c = self._chars.get(str(cid)) or {}
            dom = (c.get("landed_data") or {}).get("domain") or []
        best_tid, best_rank = None, -1
        for tid in dom:
            key = (self._lt.get(str(tid)) or {}).get("key") or ""
            rank = self._TIER_RANK.get(key[:2], 0)
            if rank > 0 and rank > best_rank:
                best_tid, best_rank = tid, rank
        if best_tid is None:
            return None, None
        return self._RANK_TIER[best_rank], best_tid

    def _is_independent(self, cid):
        """是否独立 (非他人封臣): 预建全量封臣 id 集, O(1) 判定 + 每角色缓存。"""
        if cid is None:
            return True
        v = self._indep_cache.get(cid)
        if v is None:
            v = int(cid) not in self._vassal_ids
            self._indep_cache[cid] = v
        return v

    def _office_word(self, tier, government, independent=False, female=False):
        """官职词: (层级, 政体) → 词。天朝/行政/草原行政共用同一套 (刺史/节度使/
        观察使/宣抚使…), 与文化无关 (实测: 诺斯伯爵在中国亦为刺史)。
        独立天朝制统治者用独立词 (皇帝/王/节度使), 不用封臣官职词。
        v14: 独立天朝制改为查游戏真实键 (dlc_tgp_cultural_titles):
          hegemon=hegemon_celestial_male_chinese(皇帝), empire=emperor_..._independent(皇帝),
          kingdom=king_male_chinese(王)/king_female_chinese(女王),
          duchy=duke_male_chinese_independent(节度使), county=count_independent_male_feudal_chinese(将军)。
        旧逻辑查 king_celestial_male_chinese_independent — 游戏本地化表中不存在,
        回退到通用 king「国王」→ 渲染成「粤国王」, 与游戏「桂王/粤王」口径不符 (修复方案_菲利普2.md 问题3)。"""
        gov = government or ""
        if gov in self._CELESTIAL_LIKE_GOVS:
            if independent:
                if tier == "hegemon":
                    key = "hegemon_celestial_male_chinese"
                elif tier == "empire":
                    key = "emperor_celestial_male_chinese_independent"
                elif tier == "kingdom":
                    key = "king_female_chinese" if female else "king_male_chinese"
                elif tier == "duchy":
                    key = ("duke_female_chinese_independent"
                           if female else "duke_male_chinese_independent")
                elif tier == "county":
                    key = ("count_independent_female_feudal_chinese"
                           if female else "count_independent_male_feudal_chinese")
                else:
                    key = ("baron_female_feudal_chinese"
                           if female else "baron_male_feudal_chinese")
                v = L.loc(self.table, key)
                if v and not v.startswith("$") and not v.startswith("["):
                    return v
                v = L.loc(self.table, self._TIER_KEY[tier])
                if v and not v.startswith("$") and not v.startswith("["):
                    return v
                return L.GENERIC_TIER_ZH.get(tier, "")
            if tier == "hegemon":
                key = "hegemon_celestial_male_chinese"
            elif tier == "kingdom":
                key = "king_celestial_male_chinese_civilian_governor"
            elif tier == "empire":
                key = "emperor_celestial_male_chinese_civilian_governor"
            else:
                key = f"{self._TIER_KEY[tier]}_celestial_male_chinese_governor"
            v = L.loc(self.table, key)
            if v and not v.startswith("$") and not v.startswith("["):
                return v
        prefix = re.sub(r"_government$", "", gov)
        for k in (f"{self._TIER_KEY[tier]}_{prefix}_male",
                  f"{self._TIER_KEY[tier]}_feudal_male"):
            v = L.loc(self.table, k)
            if v and not v.startswith("$") and not v.startswith("["):
                return v
        return L.GENERIC_TIER_ZH.get(tier, "")

    def _last_title_place(self, cid, fkey=""):
        """角色官职的地名 (dead_data.flavor 只有官职词无地名 — v13 补全用)。
        取值顺序: ① 与官职层级精确匹配的头衔 (关白=帝国级→日本; 国司=郡级→出云);
        ② 最高层级头衔; ③ 最近一次持有的头衔; ④ v14: 死者 dead_data.domain 的
        头衔名 (title history 被存档剪除时, dead_data 仍带死时辖地 — 蓝田县令)。
        返回 '建宁'/'颍州'/'出云' 等; 无则 ''。"""
        tier_want = None
        for pfx, rk in (("hegemon_", 6), ("emperor_", 5), ("king_", 4),
                        ("duke_", 3), ("count_", 2), ("baron_", 1)):
            if fkey and fkey.startswith(pfx):
                tier_want = rk
                break
        intervals = self._hold_intervals(cid)
        best_tier, best_tier_nm = -1, ""
        best_late, best_late_nm = None, ""
        for tid, ivs in intervals.items():
            t = self._lt.get(str(tid)) or {}
            key = t.get("key") or ""
            if not key or key.startswith(("x_", "e_minister_")):
                continue
            rank = self._TT_RANK.get(key[:2], 0)
            for (gain, _loss, _lt) in ivs:
                if not gain:
                    continue
                nm = self._name_at_date(tid, gain)
                if not nm:
                    continue
                if tier_want is not None and rank == tier_want:
                    return nm  # 与官职层级精确匹配 → 直接返回
                if rank > best_tier:
                    best_tier, best_tier_nm = rank, nm
                dk = cl.date_key(gain)
                if best_late is None or dk > best_late[0]:
                    best_late = (dk, nm)
        if best_tier_nm:
            return best_tier_nm
        if best_late_nm:
            return best_late_nm
        # v14: title history 缺失 (存档剪除) 时, 死者的 dead_data.domain 仍带
        # 死时辖地 — 用作官职地名兜底 (贾瑾: b_lantian → 蓝田县令)。
        c = self._chars.get(str(cid)) or {}
        dd = c.get("dead_data") or {}
        ddom = dd.get("domain") or []
        if ddom:
            died = dd.get("date")
            for tid in ddom:
                t = self._lt.get(str(tid)) or {}
                key = t.get("key") or ""
                if not key or key.startswith(("x_", "e_minister_")):
                    continue
                rank = self._TT_RANK.get(key[:2], 0)
                if tier_want is not None and rank == tier_want:
                    nm = self._name_at_date(tid, died)
                    if nm:
                        return nm
            # 无层级精确匹配: 取最高层级辖地
            b_t, b_nm = -1, ""
            for tid in ddom:
                t = self._lt.get(str(tid)) or {}
                key = t.get("key") or ""
                if not key or key.startswith(("x_", "e_minister_")):
                    continue
                rank = self._TT_RANK.get(key[:2], 0)
                nm = self._name_at_date(tid, died)
                if nm and rank > b_t:
                    b_t, b_nm = rank, nm
            return b_nm
        return ""

    def official_title(self, cid):
        """角色官职名: 「头衔名+官职词」(交州刺史/淄青节度使/青徐路观察使)。
        已死角色优先读存档 dead_data.flavor (游戏算好的键, 最准)。
        v13: flavor 只有官职词 (节度使/国司/关白) 无地名 — 用最后持有头衔的地名补全
        (颍州刺史/建宁节度使/出云国司), 与在世角色渲染一致。
        伊斯兰统治者特殊: 家族名+苏丹国/哈里发国 (复用 realm_name)。"""
        c = self._chars.get(str(cid)) or {}
        fkey = (c.get("dead_data") or {}).get("flavor")
        if fkey:
            v = L.loc(self.table, fkey)
            if v and not v.startswith("$") and not v.startswith("["):
                place = self._last_title_place(cid, fkey)
                if place and not v.startswith(place):
                    return f"{place}{v}"
                return v
        tier, tid = self._primary_title_at(cid)
        if tid is None or tier is None:
            # v13: 无地家族/庄园头衔 (x_nf_*「XX家族」) 的持有者官职词 —
            # 按文化选词 (日本: 当主; 高丽系: 户长; 其余天朝/选贤/行政: 乡绅)。
            # 修: 此前返回空, 家族领袖的官职从未传给模型。
            if tid is not None:
                key = (self._lt.get(str(tid)) or {}).get("key") or ""
                if key.startswith("x_nf_"):
                    nm = self.title_base_name(tid) or ""
                    sq = self._estate_holder_word(cid)
                    return f"{nm}{sq}" if nm else sq
            return ""  # 无头衔 / 仅营地 (无官职词)
        # v13: 朝廷职司持有者 → 职司官职词 (吏部尚书/御史大夫/枢密使), 非「X皇帝/帝国」
        mo = self._minister_office(tid)
        if mo:
            return mo
        rn = self.realm_name(tid)
        if rn:
            return rn
        name = self._name_at_date(tid, self.as_of) or self.title_base_name(tid)
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        gov = (rec.get("landed") or {}).get("government") or ""
        if not gov:
            gov = (c.get("landed_data") or {}).get("government") or ""
        word = self._office_word(tier, gov, independent=self._is_independent(cid),
                                 female=bool((self._chars.get(str(cid)) or {}).get("female")))
        return f"{name}{word}" if word else name

    # v13: 朝廷职司 (e_minister_*) → 官职词 (游戏本地化键, 六部+御史台+枢密院)
    _MINISTER_OFFICE_KEYS = {
        "e_minister_of_personnel": "minister_personnel",   # 吏部尚书
        "e_minister_of_revenue": "minister_revenue",       # 户部尚书
        "e_minister_of_rites": "minister_rites",           # 礼部尚书
        "e_minister_of_war": "minister_war",               # 兵部尚书
        "e_minister_of_justice": "minister_justice",       # 刑部尚书
        "e_minister_of_works": "minister_works",           # 工部尚书
        "e_minister_censor": "minister_censor",            # 御史大夫
        "e_minister_grand_marshal": "minister_grand_marshal",  # 枢密使
    }

    # v14: 恩怨史事件两端角色重渲染 (修复方案_菲利普2.md 问题3) —
    # change_reason 里游戏只写「国王/王」无国号, 渲染层有头衔能力却绕过了它。
    # 按事件日期查两端角色头衔: 主角侧「瑞典国王崔佛」, 对方侧「粤王范承宗」。
    def _feud_role_title(self, cid, date):
        """事件中某角色的「头衔名+名」: 按事件日期查首要头衔 (国号随年份:
        903 是粤、更早是桂), 无头衔/查不到时回退纯名。"""
        tier, tid = self._primary_title_at(cid, as_of=date)
        name = self.name_or(cid)
        if tid is None or tier is None:
            return name
        tname = self._name_at_date(tid, date) or self.title_base_name(tid)
        if not tname:
            return name
        # 政体从头衔侧取 (角色 landed 在死者/时点会被清空, 头衔政体更稳)
        gov = self._title_government(tid)
        word = self._office_word(tier, gov, independent=self._is_independent(cid),
                                 female=bool((self._chars.get(str(cid)) or {}).get("female")))
        return f"{tname}{word}{name}" if word else f"{tname}{name}"

    def _rerender_feud_event(self, raw, date):
        """change_reason 原文 → 两端角色按日期重渲染的干净中文句。
        保留游戏动词 (劫掠了/囚禁了/处决了/成为朋友…), 只替换两端「称号+名」:
        '\x15ONCLICK:CHARACTER,38696 ... \x15high 国王\x15!，\x15high 崔佛...' →
        '瑞典国王崔佛·菲利普劫掠了粤王范承宗'。"""
        s = str(raw or "")
        if "\x15" not in s or "ONCLICK" not in s:
            return _clean_ck3_loc(s)
        def _repl(m):
            cid = int(m.group(1))
            return self._feud_role_title(cid, date)
        s2 = _FEUD_ROLE_RE.sub(_repl, s)
        return _clean_ck3_loc(s2)


    def _minister_office(self, tid):
        """e_minister_* 头衔的职司官职词; 非职司头衔返回 ''。"""
        if tid is None:
            return ""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        if not key.startswith("e_minister_"):
            return ""
        loc_key = self._MINISTER_OFFICE_KEYS.get(key)
        if loc_key:
            v = L.loc(self.table, loc_key)
            if v and not v.startswith("$") and not v.startswith("["):
                return v
        return self.title_base_name(tid) or "尚书"

    # v13: 无地家族/庄园头衔 (x_nf_*) 持有者的官职词, 按文化模板选
    # (游戏本地化键: 日本 当主/女士, 高丽系 户长/夫人, 其余 乡绅/夫人)
    _KOREAN_ESTATE_TPL = {"korean", "silla", "goryeo", "baekje",
                          "goguryeo", "balhae", "khitan"}

    def _estate_holder_word(self, cid):
        female = bool((self._chars.get(str(cid)) or {}).get("female"))
        tpl = self.culture_template(cid) or ""
        if tpl == "japanese":
            key = "estate_holder_female_japanese" if female else "estate_holder_male_japanese"
        elif tpl in self._KOREAN_ESTATE_TPL:
            key = "estate_holder_female_korean" if female else "estate_holder_male_korean"
        else:
            key = "celestial_estate_holder_female" if female else "celestial_estate_holder_male"
        v = L.loc(self.table, key)
        if v and not v.startswith("$") and not v.startswith("["):
            return v
        return "夫人" if female else "乡绅"

    def _current_ministers(self):
        """朝廷职司现任: e_minister_* 头衔的当前持有者 →
        ['吏部：XXX（吏部尚书）', …] (朝局风云录·朝廷职司用)。"""
        out = []
        for tid, t in self._lt.items():
            if not isinstance(t, dict):
                continue
            key = t.get("key") or ""
            if not key.startswith("e_minister_"):
                continue
            holder = t.get("holder")
            if not isinstance(holder, int):
                continue
            nm = self.name_or(holder)
            off = self._minister_office(int(tid))
            base = self.title_base_name(int(tid)) or key
            out.append(f"{base}：{nm}（{off}）" if off and off != base
                       else f"{base}：{nm}")
        return out

    # v13: 戏剧性事实 — 短命帝国/皇朝在位 (≤30 日即失去/被毁)
    DRAMATIC_TENURE_DAYS = 30

    # v14: 戏剧性事件扩展 (修复方案_菲利普2.md 问题4 修复3) — 除短命皇朝外,
    # 主角级「人生转折点」: 登位/失土/被囚/获释/结仇/结怨/死敌/囚禁他人/战争/
    # 丧子/加冕。从已截断的时间线取主角名在文本中的事件, 按类型白名单抽取,
    # 上限 12 条防膨胀。渲染为【戏剧性事件】独立块 (档案末尾)。
    DRAMATIC_TIMELINE_TYPES = {
        "ascended_throne_memory", "lost_title_memory", "imprisoned",
        "released_from_prison_memory", "became_rivals", "became_grudge",
        "became_nemesis", "imprisoned_other", "offensive_war", "war_won",
        "war_lost", "child_premature", "child_stillborn",
        "witnessed_a_coronation_memory",
    }
    DRAMATIC_TIMELINE_MAX = 12

    def dramatic_facts(self, pid):
        """高亮戏剧性事件 (v14): ① 短命皇朝 (h_/e_ 头衔 ≤30 日在位即失/被毁);
        ② 主角级人生转折点 (登位/失土/被囚/结仇/囚禁/战争/丧子等, 按时间线
        主角级事件抽取, 上限 12 条)。返回 ['935年11月4日承袭周皇朝…', …]。"""
        out = []
        if pid is None:
            return out
        # ① 短命皇朝 (原 v13 逻辑)
        intervals = self._hold_intervals(pid)
        for tid, ivs in intervals.items():
            key = (self._lt.get(str(tid)) or {}).get("key") or ""
            if not key.startswith(("h_", "e_")):
                continue
            for (gain, loss, ltype) in ivs:
                if not gain or not loss:
                    continue
                span = _daynum(loss) - _daynum(gain)
                if span < 0 or span > self.DRAMATIC_TENURE_DAYS:
                    continue
                tname = self._title_name_at(tid, gain, pid) or key
                verb = "被毁" if ltype == "destroyed" else "失去"
                out.append(f"{self.date(gain)}承袭{tname}，"
                           f"{self.date(loss)}{verb}，在位仅{span}日")
        # ② 主角级人生转折点 (从截断时间线取, 主角名在文本中)
        if len(out) < self.DRAMATIC_TIMELINE_MAX:
            pname = self.name_or(pid)
            for e in _timeline(self):
                if e.get("type") not in self.DRAMATIC_TIMELINE_TYPES:
                    continue
                if pname and pname not in e.get("text", ""):
                    continue
                out.append(e["text"])
                if len(out) >= self.DRAMATIC_TIMELINE_MAX:
                    break
        return out

    def _prince_word(self, ptier, government, independent, female):
        """王子词: 按父头衔层级 × 政体 × 独立/封臣 × 性别。
        天朝制: 皇朝/帝国=皇子/皇女; 独立王国=王子/郡主 (大理国王子);
        封臣王国=公子/公女 (青徐路公子)。封建: 王子/公主。"""
        gov = government or ""
        if gov in self._CELESTIAL_LIKE_GOVS:
            if ptier in ("hegemon", "empire"):
                key = "princess_female_celestial_chinese" if female else "prince_male_celestial_chinese"
            elif independent:
                key = ("princess_kingdom_celestial_chinese_independent" if female
                       else "prince_kingdom_celestial_chinese_independent")
            else:
                key = ("princess_kingdom_celestial_chinese" if female
                       else "prince_kingdom_celestial_chinese")
            v = L.loc(self.table, key)
            if v and not v.startswith("$") and not v.startswith("["):
                return v
        v = L.loc(self.table, "princess_kingdom_feudal_chinese" if female
                  else "prince_kingdom_feudal_chinese")
        if v and not v.startswith("$") and not v.startswith("["):
            return v
        return "公主" if female else "王子"

    def prince_title(self, cid):
        """王子/公主称号: 角色无头衔, 且父/母首要头衔层级 ∈ {王国,帝国,霸权}
        (王国/帝国/霸权统治者子女都用此模板)。前缀 = 父头衔名+层级词
        (独立天朝制王国=「国」, 如大理国王子; 封臣=「路」, 如青徐路公子;
        伊斯兰: 家族名+苏丹国/哈里发国) + 王子词。"""
        tier0, _ = self._primary_title_at(cid)
        if tier0 is not None:
            return ""  # 自己已有头衔, 不适用
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        parents = []
        for k in ("father", "mother"):
            parents.extend((rec.get("family") or {}).get(k) or [])
        if not parents:
            c = self._chars.get(str(cid)) or {}
            fd = c.get("family_data") or {}
            for k in ("father", "mother"):
                v = fd.get(k)
                if v is not None:
                    parents.extend(v if isinstance(v, list) else [v])
        if not parents:
            return ""
        best = None  # (rank, ptier, parent_cid)
        for pid2 in parents:
            pid2 = int(pid2)
            t, _tid = self._primary_title_at(pid2)
            rank = {"hegemon": 6, "empire": 5, "kingdom": 4}.get(t, 0)
            if rank > 0 and (best is None or rank > best[0]):
                best = (rank, t, pid2)
        if best is None:
            return ""
        _rank, ptier, pparent = best
        _t, ptid = self._primary_title_at(pparent)
        prec = (self.cache.get("characters") or {}).get(str(pparent)) or {}
        pgov = (prec.get("landed") or {}).get("government") or ""
        if not pgov:
            pc = self._chars.get(str(pparent)) or {}
            pgov = (pc.get("landed_data") or {}).get("government") or ""
        independent = self._is_independent(pparent)
        # 前缀: 伊斯兰特殊 (家族名+苏丹国/哈里发国), 否则 头衔名+层级词
        rn = self.realm_name(ptid)
        if rn:
            prefix = rn
        else:
            pbase = self._name_at_date(ptid, self.as_of) or self.title_base_name(ptid)
            if pgov in self._CELESTIAL_LIKE_GOVS and independent \
                    and ptier in ("kingdom", "empire", "hegemon"):
                # 独立天朝制: 王国/帝国=国, 皇朝=皇朝 (大理国)
                key = {"kingdom": "kingdom_celestial_chinese_independent",
                       "empire": "empire_celestial_chinese_independent",
                       "hegemon": "hegemony_celestial_chinese"}[ptier]
                w = L.loc(self.table, key)
                if w and not w.startswith("$") and not w.startswith("["):
                    prefix = f"{pbase}{w}"
                else:
                    prefix = pbase
            else:
                pword = L.tier_word(self.table, pgov, ptier)
                prefix = f"{pbase}{pword}" if pword else pbase
        female = bool((self._chars.get(str(cid)) or {}).get("female"))
        return prefix + self._prince_word(ptier, pgov, independent, female)

    # ---- 家族恩怨 (house_relations) / 宝物志 (artifacts) ----

    def house_feuds(self):
        """与主角家族关系为 争吵/敌对/世仇 的家族 (v9 家族恩怨录数据源)。
        返回 [{house, level, events:[日期，事件…]}], 按事件数降序。"""
        cache = self.cache
        pid = cache.get("player_id")
        if pid is None:
            return []
        prec = (cache.get("characters") or {}).get(str(pid)) or {}
        my_houses = set()
        h0 = prec.get("dynasty_house")
        if isinstance(h0, int):
            my_houses.add(h0)
        did = cache.get("dynasty_id")
        dh = (self.melt.get("dynasties") or {}).get("dynasty_house") or {}
        if did is not None:
            for hid, e in dh.items():
                if isinstance(e, dict) and e.get("dynasty") == did:
                    my_houses.add(int(hid))
        if not my_houses:
            return []
        db = (self.melt.get("house_relations") or {}).get("database") or {}
        NEG = {"default_house_relation_level_feud",
               "default_house_relation_level_rivalry",
               "default_house_relation_level_quarrel"}
        out = []
        for _k, r in db.items():
            if not isinstance(r, dict):
                continue
            hs = r.get("houses") or []
            if not any(h in my_houses for h in hs):
                continue
            lvl = r.get("level") or ""
            if lvl not in NEG:
                continue
            other = [h for h in hs if h not in my_houses]
            if not other:
                continue
            events = []
            for e in (r.get("history") or []):
                d = str(e.get("date") or "")
                # v11: as_of 截断 — 十年传记只列该时期前的恩怨事件
                if self.as_of and d and cl.date_key(d) > cl.date_key(self.as_of):
                    continue
                # v14: change_reason 两端角色按事件日期重渲染 (补国号,
                # 修复方案_菲利普2.md 问题3: 游戏原文只写「国王/王」无国号)
                txt = self._rerender_feud_event(e.get("change_reason") or "", d)
                if not txt:
                    continue
                events.append((d, txt))
            if not events:
                continue
            events.sort(key=lambda x: cl.date_key(x[0]))
            out.append({
                "house": cl.house_name_zh(self.melt, other[0]) or f"家族{other[0]}",
                "level": L.loc(self.table, lvl) or lvl,
                "events": [f"{self.date(d)}，{t}" for d, t in events],
            })
        out.sort(key=lambda x: len(x["events"]), reverse=True)
        return out

    # v13: 宝物志只收「传奇级」珍奇 (用户定稿); 狩猎战利品类型 (毛皮/角/颅骨)
    # 一律剔除 (即使传奇级也是凑数); 最多 20 件防提示词膨胀。
    ARTIFACT_RARITY = ("legendary",)
    ARTIFACT_FILLER_TYPES = {
        "animal_hide", "animal_hide_big", "animal_trinket",
        "animal_skull", "VIET_clutter",
    }
    ARTIFACT_MAX = 20

    def family_artifacts(self):
        """宝物志数据源: 传奇级、相关集持有、且被其他宗族持有过的宝物。
        返回 [多行文本], 含名称/稀有度/流转史。"""
        related = _related_ids(self)
        art = (self.melt.get("artifacts") or {}).get("artifacts") or {}
        dh = (self.melt.get("dynasties") or {}).get("dynasty_house") or {}
        my_dyn = self.cache.get("dynasty_id")
        rarity_zh = {"common": "常见", "famed": "著名", "masterwork": "大师级",
                     "illustrious": "名望级", "legendary": "传奇级"}
        out = []
        for aid, a in art.items():
            if not isinstance(a, dict):
                continue
            if a.get("rarity") not in self.ARTIFACT_RARITY:
                continue
            if (a.get("type") or "") in self.ARTIFACT_FILLER_TYPES:
                continue
            if a.get("owner") not in related:
                continue
            hist = (a.get("history") or {}).get("entries") or []
            cross = False
            for e in hist:
                for key in ("actor", "recipient"):
                    cid = e.get(key)
                    if not isinstance(cid, int):
                        continue
                    c = (self.melt.get("living") or {}).get(str(cid)) \
                        or (self.melt.get("dead_unprunable") or {}).get(str(cid)) \
                        or {}
                    h = c.get("dynasty_house")
                    d = (dh.get(str(h)) or {}).get("dynasty") if isinstance(h, int) else None
                    if d is not None and d != my_dyn:
                        cross = True
                        break
                if cross:
                    break
            if not cross:
                continue
            name = a.get("name") or f"宝物{aid}"
            rarity = rarity_zh.get(a.get("rarity")) or a.get("rarity") or ""
            lines = [f"宝物：{name}（{rarity}）"]
            entries = []
            for e in reversed(hist):
                # v11: as_of 截断 — 十年传记只列该时期前的流转
                if self.as_of and e.get("date") \
                        and cl.date_key(e.get("date")) > cl.date_key(self.as_of):
                    continue
                t = e.get("type") or ""
                d = self.date(e.get("date")) if e.get("date") else ""
                actor = self.name_or(e.get("actor"), "") if isinstance(e.get("actor"), int) else ""
                rec2 = self.name_or(e.get("recipient"), "") if isinstance(e.get("recipient"), int) else ""
                if t == "created" and actor:
                    entries.append(f"{d}，{actor}锻造此宝")
                elif t == "created":
                    entries.append(f"{d}，创制")
                elif t == "inherited" and rec2:
                    entries.append(f"{d}，传于{rec2}")
                elif t == "taken_in_battle" and actor:
                    entries.append(f"{d}，{actor}自战场夺得")
                elif t == "taken_in_siege" and actor:
                    entries.append(f"{d}，{actor}围攻中夺得")
                elif t == "conquest":
                    entries.append(f"{d}，克定所得")
                elif t == "created_before_history":
                    entries.append("年代久远，创制无考")
                else:
                    entries.append(f"{d}，{t}")
            if entries:
                lines.append("流转：" + "；".join(entries))
            out.append("\n".join(lines))
        # 按流转事件数降序 (流转史丰富者优先) 后限量
        out.sort(key=lambda x: len(x), reverse=True)
        return out[: self.ARTIFACT_MAX]

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
        """角色宗族名 (穆斯林国名用, v14: 游戏用宗族名 — 图伦苏丹国=图伦):
        缓存 dynasty_name → house_name → 熔件 dynasty_house 解析。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        if rec.get("dynasty_name"):
            return rec["dynasty_name"]
        if rec.get("house_name"):
            return rec["house_name"]
        c = self._chars.get(str(cid)) or {}
        hid = c.get("dynasty_house")
        if isinstance(hid, int):
            did = cl.dynasty_id_of(self.melt, hid)
            if did is not None:
                return cl.dynasty_name_zh(self.melt, did) or ""
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
    def culture_template(self, cid):
        """角色文化模板名 (norse/han/balhae…): 缓存 culture id → 熔件 culture_manager。
        v11: 缓存/熔件文化均缺失 (死后清空/存档版本无 culture 字段) 时,
        依语言反查 (language_norse → norse), 供父名推断与族属显示。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        cul = rec.get("culture")
        if cul is None:
            c = self._chars.get(str(cid)) or {}
            cul = c.get("culture")
        if cul is not None:
            e = ((self.melt.get("culture_manager") or {}).get("cultures") or {}) \
                .get(str(cul))
            tpl = (e or {}).get("culture_template") if isinstance(e, dict) else None
            if tpl:
                return tpl
        # 语言反查: 角色已知语言 → culture_manager.language → 文化模板
        # (多文化共享同一语言时, 优先有父名规则的模板, 如 language_norse → norse 而非 norman)
        for lg in self._languages_of(cid):
            cands = self._lang_to_tpl.get(lg) or []
            if not cands:
                continue
            for tpl in cands:
                if tpl in _patronym_rules():
                    return tpl
            return cands[0]
        # v13: 亲属链/宗族兜底 (玩家本人无 culture、死者被清空时, 经子女等反推)
        # 传 chars/memo 避免每次重建全角色索引 (同一次 build_facts 内复用)
        return cl._culture_template_of(self.cache, cid, self.melt,
                                       chars=self._chars, memo=self._tpl_memo) or None

    def _languages_of(self, cid):
        """角色语言 id 列表: 缓存捕获 (跨年保留) 优先, 缺失回退最新熔件 alive_data。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        langs = rec.get("languages") or []
        if not langs:
            c = self._chars.get(str(cid)) or {}
            langs = (c.get("alive_data") or {}).get("languages") or []
        return [str(x) for x in langs]

    def languages(self, cid):
        """角色语言中文名 (v11): language_norse → language_norse_name → 诺斯语。"""
        out = []
        for lg in self._languages_of(cid):
            v = L.loc(self.table, f"{lg}_name") or L.loc(self.table, lg) or ""
            if v:
                out.append(v)
        return out

    def name_zh_of(self, cid):
        """角色名 (名, 不带家族/头衔) — 父名拼接用。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        nm = rec.get("name_zh")
        if not nm:
            c = self._chars.get(str(cid)) or {}
            nm = c.get("first_name")
        return nm or ""

    def _father_id(self, cid):
        """角色父 id; 无则 None。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        parents = (rec.get("family") or {}).get("father") or []
        if not parents:
            c = self._chars.get(str(cid)) or {}
            v = (c.get("family_data") or {}).get("father")
            if v is not None:
                parents = v if isinstance(v, list) else [v]
        return int(parents[0]) if parents else None

    def patronym(self, cid):
        """父名 (中间名): 父名制文化且父名已知 → 前缀+父名+后缀
        (诺斯: 崔佛松/崔佛斯多蒂尔; 威尔士: 阿普·X; 爱尔兰: 麦克·X/妮克·X;
        伊比利亚: X斯; 斯拉夫: X奇; 英: X森…)。父未知/非父名文化 → 空。
        v13: 统一走 cache_lib._patronym_of (文化模板经亲属链推断, 玩家/死者亦覆盖)。"""
        return cl._patronym_of(self.cache, cid, self.melt, self.names_path,
                               chars=self._chars)

    def culture(self, cid):
        """角色文化 (v11): 缓存/熔件 culture id → 语言推断 → 本地化 → 'X人'。"""
        tpl = self.culture_template(cid) or ""
        name = L.loc(self.table, tpl) or CULTURE_TEMPLATE_ZH.get(tpl) or ""
        if name:
            # v11: 族属用「X人」(诺斯人/汉人), 不再用「X族」; 名已以「人」结尾不再追加
            return name if name.endswith("人") else f"{name}人"
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
        """角色当前特质 id 列表 → 中文 (未知特质跳过)。
        v11: as_of 截断 — 只取 as_of 前已具且未消失的特质 (十年传记不泄漏后期疾病)。"""
        if self.as_of:
            return self._traits_at(cid)
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

    def _traits_at(self, cid):
        """as_of 时点持有的特质: 依 trait_history 区间判定 (from ≤ as_of < to)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        th = rec.get("trait_history") or {}
        ao = cl.date_key(self.as_of)
        out = []
        for key in sorted(th):
            for iv in th[key]:
                frm = iv.get("from")
                to = iv.get("to")
                if frm and cl.date_key(frm) > ao:
                    continue
                if to and cl.date_key(to) <= ao:
                    continue
                z = _trait_name(self.table, key)
                if z and z not in out:
                    out.append(z)
        return out

    def trait_history_lines(self, cid):
        """特质履历 (v4): 每条 = 「<特质>（自X日起获得 / 至晚自X日起已具 / 自X日后消失…）」
        v11: as_of 截断 — 丢弃 as_of 之后才获得的区间。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        th = rec.get("trait_history") or {}
        ao = cl.date_key(self.as_of) if self.as_of else None
        lines = []
        for key in sorted(th):
            z = _trait_name(self.table, key)
            if not z or z == key:
                continue
            spans = []
            for iv in th[key]:
                if ao is not None and iv.get("from") and cl.date_key(iv.get("from")) > ao:
                    continue
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

    def motto(self):
        """玩家家族家训 (v7) → 中文。"""
        mot = self.cache.get("house_motto")
        if not mot:
            return ""
        return render_motto(mot, self.table)

    def _office_name(self, cid):
        """官职名+名: 「交州刺史应偁」(官职前缀替换家族前缀; 无官职回退原名)。"""
        off = self.official_title(cid)
        if not off:
            return self.name_or(cid, "")
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        nm = rec.get("name_zh") or ""
        if not nm:
            full = self.name_or(cid, "")
            # v14: 东方名序的姓是宗族名, 先按宗族名剥前缀 (藤原道真 → 道真),
            # 再按家族名 (旧行为, 兼容旧缓存)
            for h in (rec.get("dynasty_name"), rec.get("house_name")):
                if h and full.startswith(h):
                    nm = full[len(h):]
                    break
            else:
                nm = full
        return f"{off}{nm}" if nm else off

    def court_positions_lines(self):
        """玩家宫廷/营地官职 (v7): 返回 (最新职位行, 任免变化行)。
        最新职位每条 = 「职位：人名（自X任）」; 变化行 = 跨快照同职位更替。
        v11: as_of 截断 — 只取 as_of 前最后一个快照的职位。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return [], []
        hist = self.cache.get("court_positions") or []
        if not hist:
            return [], []
        if self.as_of:
            hist = [h for h in hist
                    if cl.date_key(h.get("date")) <= cl.date_key(self.as_of)]
        if not hist:
            return [], []
        latest = hist[-1].get("positions") or []
        latest_lines = []
        for p in latest:
            zh = L.loc(self.table, p.get("type")) or ""
            if not zh or zh == p.get("type"):
                continue
            emp = p.get("employee")
            nm = self._office_name(emp) if emp is not None else ""
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
                    nm = self._office_name(emp) if emp is not None else "空缺"
                    if nm:
                        change_lines.append(f"{self.date(h.get('date'))}：{nm}卸任{zh}")
                for t, emp in sorted(cur - prev):
                    zh = L.loc(self.table, t) or ""
                    if not zh or zh == t:
                        continue
                    nm = self._office_name(emp) if emp is not None else "空缺"
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


def _clean_ck3_loc(s):
    """剥离 CK3 本地化格式标签: \\x15ONCLICK:... \\x15TOOLTIP:... \\x15L \\x15high ...\\x15!
    (家族关系事件文本用, 产出干净中文)。中文后无词边界, 直接用字符级匹配。
    v13: 部分文本「称号，名字」(国王，张格本) 是 mod 翻译瑕疵 — 删去称号与
    名字间的逗号 (国王张格本), 防模型模仿出「囚X一」式怪句。"""
    s = str(s or "").replace("\x15", "")
    s = re.sub(r"ONCLICK:[A-Z]+,\d+\s*", "", s)
    s = re.sub(r"TOOLTIP:[A-Z]+,\d+\s*", "", s)
    s = re.sub(r"L(?=\s)", "", s)   # L 链接标记 (文本为中文, 孤立 L 只可能是标签)
    s = re.sub(r"high\s*", "", s)
    s = s.replace("!", "").replace("  ", " ").strip()
    s = re.sub(r"(?<=[\u4e00-\u9fff]) (?=[\u4e00-\u9fff])", "", s)
    # 称号(≤4字)与名字之间的逗号 → 删 (国王，张格本 → 国王张格本)
    s = re.sub(r"([\u4e00-\u9fff]{1,4})，(?=[\u4e00-\u9fff]{2,})", r"\1", s)
    return s


# 恩怨史事件文本中的角色块: \x15ONCLICK:CHARACTER,id \x15TOOLTIP:CHARACTER,id \x15L
# \x15high 称号 \x15!，\x15high 姓 \x15!\x15high 名 \x15!\x15!\x15!\x15!
# (v14 重渲染用 — 只替换两端角色, 保留游戏动词「成为/与/劫掠了…」)
_FEUD_ROLE_RE = re.compile(
    r"\x15ONCLICK:CHARACTER,(\d+)"
    r"(?:\s*\x15TOOLTIP:CHARACTER,\d+)?\s*\x15L\s*"
    r"(?:.*?)\x15!\x15!\x15!\x15!"
)


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
        # v11: 谋杀类死因用「凶手为」(未被败露的谋杀没有行刑者), 其余用「行刑者/凶手为」
        is_murder = any(w in reason for w in ("谋杀", "毒杀", "暗杀"))
        if killer == f.cache.get("player_id"):
            kstr = (f"，凶手为{f.name_or(f.cache.get('player_id'))}" if is_murder
                    else f"，行刑者为{f.name_or(f.cache.get('player_id'))}")
        else:
            kstr = f"，凶手为{f.name_or(killer)}"
    return f"{name}殁于{f.date(d.get('date'))}，{reason}{kstr}。"


# v14: 30 个戏剧性模块 — 十年小传按主题切片的事实组织 (研究_戏剧模块化.md)。
# 每个模块 = {模块名: memory type 集} (另有 4 个专题模块 短命皇朝/天下更替/
# 官职任免/死亡谢幕, 由专门渲染器驱动, 不在本表)。type→模块 为纯数据层映射。
MODULE_TABLE = {
    "起家发迹":   {"ascended_throne_memory"},
    "失位让土":   {"lost_title_memory"},
    "开战兴兵":   {"offensive_war", "defensive_war", "joined_allys_war"},
    "战和胜负":   {"battle_won_memory", "battle_lost_memory", "war_won", "war_lost"},
    "战殁负伤":   {"witnessed_death_battle", "became_incapable_due_to_battle_concussion"},
    "人质质任":   {"hostage_created_hostage", "hostage_created_warden", "hostage_created_home_court"},
    "囚禁入狱":   {"imprisoned", "imprisoned_other"},
    "获释出狱":   {"released_from_prison_memory"},
    "刑虐残暴":   {"tortured_memory", "torturer_memory"},
    "受辱含冤":   {"ignored_assault_memory"},
    "结仇结怨":   {"became_rivals", "became_grudge"},
    "死敌之仇":   {"became_nemesis"},
    "化仇解怨":   {"stopped_being_rivals"},
    "仇雠消亡":   {"rival_died"},
    "结友知交":   {"became_friends"},
    "挚友血盟":   {"became_soulmates", "became_blood_brother"},
    "丧友之恸":   {"friend_died"},
    "婚配联姻":   {"married", "grand_wedding_completed_guest"},
    "情变私通":   {"became_lovers", "had_sex", "broke_up_lovers"},
    "丧偶之痛":   {"spouse_died"},
    "添丁进口":   {"child_born", "first_born", "twins_born"},
    "幼殇夭折":   {"child_premature", "child_stillborn"},
    "丧亲之恸":   {"relative_died"},
    "教化求学":   {"childhood_education_guardian", "childhood_education_no_guardian",
                   "ward_education_completed", "completed_rites_of_passage",
                   "completed_adult_education"},
    "科考功名":   {"passed_child_exam_memory", "failed_child_exam_memory",
                   "passed_provincial_exam_memory", "failed_provincial_exam_memory",
                   "passed_metropolitan_exam_memory", "passed_palace_exam_memory"},
    "拥戴加冕":   {"became_acclaimed", "witnessed_a_coronation_memory"},
    "信仰皈依":   {"completed_hajj_memory", "picked_serenity_aspect_memory",
                   "picked_creation_aspect_memory"},
    # 死亡记录 (death) 不在此表: 由 _timeline 按死者关系并入 仇雠消亡/丧友之恸/
    # 丧偶之痛/丧亲之恸 同键去重 (研究_戏剧模块化.md 模块 28)。
}
_TYPE2MODULE = {}
for _m, _ts in MODULE_TABLE.items():
    for _t in _ts:
        _TYPE2MODULE[_t] = _m


def _related_ids(f):
    """主角相关角色 id 分级集 (时间线过滤用), 口径 (用户定稿 v14):
    级别1: 主角本人; 级别2: 直系相关 (父母/妻妾/前妻前妾/子女/孙辈/儿媳女婿);
    级别3: 其余宗族 (同 dynasty 但非直系) 与姻亲 — 一律剔除, 不进时间线
    (修复方案_菲利普2.md 问题4 待确认项3: 全部剔除, 不做合计行;
    旧口径把整个宗族 ① 全收, 455 条时间线里 89% 是远亲琐事, 淹没主角戏剧)。
    返回 {cid: 级别}。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return {}
    out = {pid: 1}
    chars = cache.get("characters") or {}

    def add(ids, level):
        for x in ids or []:
            if isinstance(x, int):
                out[x] = level

    prec = chars.get(str(pid)) or {}
    fam = prec.get("family") or {}

    # 级别2: 父母/妻妾/前妻前妾/子女 + 妻妾父母
    add(fam.get("father"), 2)
    add(fam.get("mother"), 2)
    spouses = list(dict.fromkeys(
        (fam.get("primary_spouse") or []) + (fam.get("spouse") or [])
        + (fam.get("concubine") or [])
        + (fam.get("former_spouses") or [])
        + (fam.get("former_concubines") or [])))
    add(spouses, 2)
    cur_wives = list(dict.fromkeys(
        (fam.get("primary_spouse") or []) + (fam.get("spouse") or [])
        + (fam.get("concubine") or [])))
    for sid in cur_wives:
        srec = chars.get(str(sid)) or {}
        add((srec.get("family") or {}).get("father"), 2)
        add((srec.get("family") or {}).get("mother"), 2)
    add(fam.get("child"), 2)

    # 级别2: 孙辈 + 儿媳/女婿
    for cid in (fam.get("child") or []):
        cid = int(cid)
        crec = chars.get(str(cid)) or {}
        cfam = crec.get("family") or {}
        add(cfam.get("child"), 2)
        add(cfam.get("primary_spouse"), 2)
        add(cfam.get("spouse"), 2)
    return out


# v14: death 记录 (类型 "death", 由 _death_sentence 渲染) 的模块标注 —
# 按死者与主角的关系: 仇人→仇雠消亡, 友人→丧友之恸, 配偶→丧偶之痛, 其余→丧亲之恸。
def _death_module(f, dead_cid):
    """death 时间线事件归属的戏剧性模块 (按死者关系)。"""
    pid = f.cache.get("player_id")
    if pid is None:
        return "丧亲之恸"
    rel = (f.cache.get("characters") or {}).get(str(pid)) or {}
    fam = rel.get("family") or {}
    if dead_cid in (fam.get("primary_spouse") or []) + (fam.get("spouse") or []):
        return "丧偶之痛"
    for cid, rec in (f.cache.get("characters") or {}).items():
        for m in rec.get("memories") or []:
            if m.get("type") in ("became_rivals", "became_grudge", "became_nemesis"):
                parts = m.get("participants") or {}
                if any(isinstance(v, int) and v == dead_cid for v in parts.values()) \
                        and any(isinstance(v, int) and v == pid for v in parts.values()):
                    return "仇雠消亡"
            if m.get("type") in ("became_friends", "became_soulmates", "became_blood_brother"):
                parts = m.get("participants") or {}
                if any(isinstance(v, int) and v == dead_cid for v in parts.values()) \
                        and any(isinstance(v, int) and v == pid for v in parts.values()):
                    return "丧友之恸"
    return "丧亲之恸"


def _timeline(f):
    """主角相关时间线: 只收 宗族/父母妻儿/孙辈儿媳婿 相关事件 (口径见 _related_ids),
    按人按事去重, 按日期排序。
    每条 = {"date", "type", "text"} (text 为干净中文句, 提示词只用 text)。
    - 路人剔除: 记忆拥有者与参与者都不在相关集内的事件一律不收;
    - 死亡去重: 同一死者只留一条 (死亡记录 > 亡故/身亡 > 丧偶), 消除「同一人不停地死」;
    - 出生去重: 同一出生只留一条 (玩家/家人视角优先);
    - 成对事件 (双方各自的记忆, 如王铎娶玘/玘嫁王铎) 按 (类型, 日期, 参与者集) 去重。"""
    cache = f.cache
    pid = cache.get("player_id")
    related = _related_ids(f)
    events = []        # (date, type, text)
    seen_keys = set()  # 成对事件去重: (type, creation_date, participants 集)
    deaths = {}        # 死者id -> (优先级, date, type, text)
    births = {}        # (date, 出生键) -> (优先级, date, type, text)
    for cid, rec in (cache.get("characters") or {}).items():
        cid = int(cid)
        # 本人死亡记录 (信息最全, 优先级最高)
        if cid in related:
            ds = _death_sentence(f, cid)
            if ds:
                deaths[cid] = (3, (rec.get("death") or {}).get("date"),
                               "death", ds)
        for mem in rec.get("memories") or []:
            parts = mem.get("participants") or {}
            owner_rel = cid in related
            part_rel = any(isinstance(v, int) and int(v) in related
                           for v in parts.values())
            if not owner_rel and not part_rel:
                continue  # 路人记忆大事: 剔除
            mtype = mem.get("type")
            # 死亡类记忆: 按死者 id 去重 (亡故/身亡 > 丧偶)
            if mtype in ("relative_died", "friend_died", "rival_died",
                         "spouse_died"):
                dead = parts.get("dead_relation")
                if isinstance(dead, int):
                    s = _mem_sentence(f, cid, mem)
                    if s:
                        prio = 2 if mtype != "spouse_died" else 1
                        old = deaths.get(dead)
                        if old is None or prio > old[0]:
                            deaths[dead] = (prio, mem.get("creation_date"),
                                            mtype, s)
                continue
            # 出生类记忆: 同一出生按 (日期, 出生键) 去重 (玩家/家人视角优先)
            if mtype in ("child_born", "first_born", "child_premature",
                         "child_stillborn", "twins_born"):
                child = parts.get("child")
                child_key = (mtype, int(child)) if isinstance(child, int) \
                    else (mtype, cid)
                bkey = (mem.get("creation_date"), child_key)
                prio = 2 if cid == pid else (1 if owner_rel else 0)
                s = _mem_sentence(f, cid, mem)
                if s:
                    old = births.get(bkey)
                    if old is None or prio > old[0]:
                        births[bkey] = (prio, mem.get("creation_date"),
                                        mtype, s)
                continue
            # 其余记忆: 成对去重
            s = _mem_sentence(f, cid, mem)
            if not s:
                continue
            pset = frozenset(v for v in parts.values() if isinstance(v, int)) \
                | {cid}
            key = (mtype, mem.get("creation_date"), pset)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            events.append((mem.get("creation_date"), mtype, s,
                           _TYPE2MODULE.get(mtype, "")))
    # 合并 死亡记录 + 亡故记忆 + 出生事件
    for cid, (_prio, _d, t, s) in deaths.items():
        # v14: death 记录按死者关系标模块 (仇雠消亡/丧友之恸/丧偶之痛/丧亲之恸)
        events.append((_d, t, s, _death_module(f, cid)))
    for _prio, _d, t, s in births.values():
        events.append((_d, t, s, "添丁进口" if t in ("child_born", "first_born", "twins_born") else "幼殇夭折"))
    # v11: as_of 截断 (十年传记只到十年末)
    if f.as_of:
        ao = cl.date_key(f.as_of)
        events = [e for e in events if e[0] and cl.date_key(e[0]) <= ao]
    events.sort(key=lambda x: cl.date_key(x[0]))
    seen = set()
    out = []
    for d, t, s, mod in events:
        if s in seen:
            continue
        seen.add(s)
        out.append({
            "date": d,
            "type": t,
            # v14: 戏剧性模块标注 (纯数据层, 十年主题抽取/文章切片用)
            "module": mod or _TYPE2MODULE.get(t, ""),
            "text": (f"{f.date(d)}，{s}" if d else s),
        })
    # v11: 同日同型集体事件合并 (见证加冕/出席大婚/被囚/囚禁)
    out = _merge_same_day_events(out, f)
    # v14: 年表限量 (修复方案_菲利普2.md 问题4 修复1) — 级别3已从源头剔除,
    # 剩余级别1(主角)/级别2(直系); 超限时级别2截断, 级别1(主角名在文本中)全保留。
    cap = 80 if f.as_of else 150   # 十年传记(有 as_of) ≤80, 终传/在世 ≤150
    if len(out) > cap:
        pname = (f.cache.get("characters") or {}).get(str(f.cache.get("player_id")), {}).get("name_full") or ""
        lvl1 = [e for e in out if pname and pname in e["text"]]
        lvl2 = [e for e in out if not (pname and pname in e["text"])]
        lvl1.extend(lvl2[:max(0, cap - len(lvl1))])
        out = lvl1
    return out


# v14: 十年戏剧主题抽取 (研究_戏剧模块化.md 3.2) — 时间线事件按模块计数,
# 主角参与 ×3 / 直系参与 ×2 / 其余 ×1 (时间线已只含直系, 权重简化为
# 主角名在文本中 ×3 否则 ×1); 取 Top10, 与第10名并列的模块全保留。
def decade_module_top(timeline, protagonist, top_n=10):
    """十年戏剧主题: [(模块名, 得分)] 按得分降序; 并列第10名全保留 (可能 >10)。
    无时间线/无模块事件时返回 []。"""
    pname = (protagonist or {}).get("name") or ""
    score = {}
    for e in timeline or []:
        m = e.get("module") or ""
        if not m:
            continue
        w = 3 if (pname and pname in e.get("text", "")) else 1
        score[m] = score.get(m, 0) + w
    if not score:
        return []
    ranked = sorted(score.items(), key=lambda x: -x[1])
    if len(ranked) <= top_n:
        return ranked
    # Top10 + 与第10名并列者
    cutoff = ranked[top_n - 1][1]
    return [r for r in ranked if r[1] >= cutoff]


# 同日同型可合并事件: type → (提取可变槽的正则, 组合函数)
_MERGE_SLOT_RES = {
    "witnessed_a_coronation_memory": (r"^(.+?)见证加冕。$",
                                      lambda names: "、".join(names) + "见证加冕。"),
    "grand_wedding_completed_guest": (r"^(.+?)出席大婚。$",
                                      lambda names: "、".join(names) + "出席大婚。"),
    "imprisoned": (r"^(.+?)被囚。$",
                   lambda names: "、".join(names) + "被囚。"),
    "imprisoned_other": (r"^(.+?)囚禁(.+?)。$",
                         lambda pairs: pairs[0][0] + "囚禁" + "、".join(p[1] for p in pairs) + "。"),
}
_MERGE_CAP = 10  # 合并人名上限, 超过收成「…等N人」
_MERGE_VERB = {
    "witnessed_a_coronation_memory": "见证加冕。",
    "grand_wedding_completed_guest": "出席大婚。",
    "imprisoned": "被囚。",
}


def _merge_same_day_events(events, f=None):
    """同日同型事件合并 (v11): 集体事件 (多人同日见证加冕/出席大婚/被囚, 或
    同一人同日囚禁多人) 拆成多行会浪费模型注意力, 按 (日期, 类型) 合并为一行。
    仅当句子结构一致且只差一个名字槽时合并 (双槽成婚等事件不受影响)。"""
    groups = {}
    order = []
    for e in events:
        key = (e.get("date"), e.get("type"))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(e)
    out = []
    for key in order:
        entries = groups[key]
        d, typ = key
        spec = _MERGE_SLOT_RES.get(typ)
        merged = None
        if spec and len(entries) > 1:
            pat, comb = spec
            slots = []
            ok = True
            for e in entries:
                body = e["text"]
                if d and f and body.startswith(f.date(d) + "，"):
                    body = body[len(f.date(d)) + 1:]
                m = re.match(pat, body)
                if not m:
                    ok = False
                    break
                slots.append(m.groups())
            if ok:
                prefix = f"{f.date(d)}，" if d else ""
                if typ == "imprisoned_other":
                    # 同一主人 (槽0) 囚禁多人: 只合并主人相同的
                    owners = {s[0] for s in slots}
                    if len(owners) == 1:
                        if len(slots) > _MERGE_CAP:
                            merged = (prefix + slots[0][0] + "囚禁"
                                      + "、".join(s[1] for s in slots[:_MERGE_CAP])
                                      + f"等{len(slots)}人。")
                        else:
                            merged = prefix + comb(slots)
                else:
                    names = [s[0] for s in slots]
                    if len(names) > _MERGE_CAP:
                        merged = (prefix + "、".join(names[:_MERGE_CAP])
                                  + f"等{len(names)}人" + _MERGE_VERB[typ])
                    else:
                        merged = prefix + comb(names)
        if merged:
            out.append({"date": d, "type": typ, "text": merged})
        else:
            out.extend(entries)
    return out


def _asof_ids(f, ids):
    """v11: 按 as_of 过滤家族成员 id 列表 — 出生晚于 as_of 的未出生者不列
    (十年传记不出现 893 年才出生的马乌戈热塔)。as_of 为空时原样返回。"""
    if not f.as_of or not ids:
        return ids or []
    ao = cl.date_key(f.as_of)
    out = []
    for x in ids:
        if not isinstance(x, int):
            continue
        rec = (f.cache.get("characters") or {}).get(str(x)) or {}
        b = rec.get("birth")
        if b and cl.date_key(b) > ao:
            continue
        out.append(x)
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
        "name_zh": rec.get("name_zh") or "",
        # v14: 宗族名 (东方名序的姓) + 家族/分家 (风味补充, 与宗族不同时给出)
        "house": _dynasty_display(rec.get("dynasty_name") or cache.get("dynasty_name"),
                                  rec.get("house_name") or cache.get("house_name")),
        "house_branch": _house_branch(rec.get("dynasty_name") or cache.get("dynasty_name"),
                                      rec.get("house_name") or cache.get("house_name")),
        "birth": f.date(rec.get("birth")),
        "culture": f.culture(pid),
        "faith": f.faith(pid),
        "traits": "、".join(f.traits(pid)) or "（特质不详）",
        "government": f.government(pid),
    }
    # v11: 角色语言 (语言：诺斯语、阿拉伯语)
    langs = f.languages(pid)
    if langs:
        p["languages"] = "、".join(langs)
    # v9: 主角官职名 (v11: 按 as_of 截断日期取)
    poff = f.official_title(pid)
    if poff:
        p["office"] = poff
    # v9.1: 主角父名 (先世无考则无)
    pptn = f.patronym(pid)
    if pptn:
        p["patronym"] = pptn
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
    # v11: as_of 早于末档时, 直辖/封臣/营规等明细是「后期快照」数据, 不进入提示词
    # (只做头衔维度; 明细维度如要按时期需另行逐年快照, 成本高暂不做)
    skip_detail = bool(f.as_of) and cl.date_key(f.as_of) < cl.date_key(
        cache.get("last_date") or f.as_of or "9999.9.9")
    ld = rec.get("landed") or {}
    gov = ld.get("government")
    # v11: 无地/有地分支按 as_of 首要头衔判定 (十年传记穿越时, 缓存 landed 是末档数据)
    ptier, ptid = f._primary_title_at(pid)
    pkey = (f._lt.get(str(ptid)) or {}).get("key") if ptid is not None else ""
    if (ptid is not None and pkey.startswith("x_")) or gov == "landless_adventurer_government":
        # ---- 无地冒险者: 营地 ----
        p["landless"] = True
        camp_tid = ptid if (ptid is not None and pkey.startswith("x_")) \
            else (ld.get("domain") or [None])[0]
        if camp_tid is not None:
            p["camp_name"] = f._title_name_at(camp_tid, f.as_of) or "冒险者营地"
        else:
            p["camp_name"] = "冒险者营地"
        # 营地细节仅当缓存 landed 确为营地 (非 as_of 穿越) 时渲染
        if gov == "landless_adventurer_government" and not skip_detail:
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
        if ld and not skip_detail:
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
            # v11: 十年传记按 as_of 计龄, 不按末档 (防「年87岁」泄漏到 892 年)
            cy_src = (f.as_of or melt.get("date") or "0.0.0")
            cy = int(str(cy_src).split(".")[0])
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
    # 死亡 (终传时; v11: as_of 早于死期视为在世, 十年传记不泄漏「殁于…」)
    pd = cache.get("player_death")
    if pd and f.as_of and cl.date_key(f.as_of) < cl.date_key(pd.get("date") or "9999.9.9"):
        pd = None
    if pd:
        p["death"] = (
            f"殁于{f.date(pd.get('date'))}，"
            f"{_death_reason(f.table, pd.get('reason'))}"
            + (f"，凶手为{f.name_or(pd.get('killer'))}" if pd.get("killer") else "。")
        )
    # 家庭 (v11: as_of 截断 — 出生晚于 as_of 的未出生者不列)
    fam = rec.get("family") or {}
    # v13: 妻妾与父系婚姻史交叉标注 — 「先为父之妻/妾, 后归子」的戏剧性关系
    father_id = (fam.get("father") or [None])[0]
    fd_fam = {}
    if father_id is not None:
        fd_fam = ((cache.get("characters") or {}).get(str(father_id)) or {}).get("family") or {}

    def _annotate(ids):
        out = []
        for sid in ids:
            nm = f.name_or(sid)
            if not nm:
                continue
            note = ""
            if father_id is not None and sid != father_id:
                for k, label in (("primary_spouse", "妻"), ("spouse", "妻"),
                                 ("concubine", "妾"), ("former_spouses", "前妻"),
                                 ("former_concubines", "前妾")):
                    if sid in (fd_fam.get(k) or []):
                        note = f"（原为父{f.name_or(father_id)}之{label}）"
                        break
            out.append(nm + note)
        return "、".join(out)

    spouse_ids = list(dict.fromkeys(
        _asof_ids(f, (fam.get("primary_spouse") or []) + (fam.get("spouse") or []))))
    p["spouses"] = _annotate(spouse_ids)
    p["former_spouses"] = _annotate(_asof_ids(f, fam.get("former_spouses") or []))
    # v8: 妾 (正向 concubine + 反向 concubinist, 已在缓存合并去重)
    p["concubines"] = _annotate(_asof_ids(f, fam.get("concubine") or []))
    p["former_concubines"] = _annotate(_asof_ids(f, fam.get("former_concubines") or []))
    p["children"] = "、".join(f.name_or(c) for c in _asof_ids(f, fam.get("child") or []) if f.name(c))
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
    # 主角历任 (v11: 主要头衔演进)
    ht = f.held_titles(pid)
    if ht:
        p["titles_held"] = "；".join(ht)
    # v13: 戏剧性事实 (一日皇帝等) — 置于档案末尾高亮
    df = f.dramatic_facts(pid)
    if df:
        p["dramatic_facts"] = df
    return p


def _profile_needed_ids(f):
    """v13 (性能): 需要构建档案的角色 id 集 — 只有这些角色会进提示词:
    相关集 (主角/宗族/父母妻儿/孙辈儿媳婿) ∪ 好友仇人 (双通道) ∪ 宫廷任官。
    其余 4 万路人档案不构建 — 按需计算, 对齐 P社开发日志 #187 的
    「只算可见内容」思路 (41k 全量档案 → 数百份, build_facts 大提速)。"""
    out = _related_ids(f)
    pid = f.cache.get("player_id")
    if pid is None:
        return out
    REL = {"became_friends", "became_soulmates", "became_blood_brother",
           "became_rivals", "became_grudge", "became_nemesis"}
    for cid, rec in (f.cache.get("characters") or {}).items():
        for m in rec.get("memories") or []:
            if m.get("type") in REL:
                parts = m.get("participants") or {}
                if any(isinstance(v, int) and v == pid for v in parts.values()):
                    out.setdefault(int(cid), 2)
                    break
    prec = (f.cache.get("characters") or {}).get(str(pid)) or {}
    for m in prec.get("memories") or []:
        if m.get("type") in REL:
            for v in (m.get("participants") or {}).values():
                if isinstance(v, int):
                    out.setdefault(v, 2)
    for h in f.cache.get("court_positions") or []:
        for p in h.get("positions") or []:
            if isinstance(p.get("employee"), int):
                out.setdefault(p["employee"], 2)
    return out


def _character_profiles(f):
    """每个缓存角色: 干净档案 + 记忆 + 死亡 + 亲属 + 历任头衔。
    v13: 只构建进提示词的角色 (见 _profile_needed_ids), 按需计算。"""
    out = {}
    for cid in _profile_needed_ids(f):
        rec = (f.cache.get("characters") or {}).get(str(cid)) or {}
        if not rec:
            continue
        name = f.name_or(cid)
        prof = {
            "name": name,
            "name_zh": rec.get("name_zh") or "",
            # v14: 宗族名 (东方名序的姓) + 家族/分家 (风味补充)
            "house": _dynasty_display(rec.get("dynasty_name"),
                                      rec.get("house_name")),
            "house_branch": _house_branch(rec.get("dynasty_name"),
                                          rec.get("house_name")),
            "birth": f.date(rec.get("birth")),
            "culture": f.culture(cid),
            "faith": f.faith(cid),
            "traits": "、".join(f.traits(cid)),
        }
        # v11: 角色语言
        langs = f.languages(cid)
        if langs:
            prof["languages"] = "、".join(langs)
        # v9: 官职名 (首要头衔+官职词) / 王子称号 (无头衔的王国/帝国/霸权子女)
        off = f.official_title(cid)
        if off:
            prof["office"] = off
        pt = f.prince_title(cid)
        if pt:
            prof["prince"] = pt
        # v9.1: 父名 (诺斯等父名制文化: 崔佛松/崔佛斯多蒂尔)
        ptn = f.patronym(cid)
        if ptn:
            prof["patronym"] = ptn
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
            _asof_ids(f, (fam.get("primary_spouse") or []) + (fam.get("spouse") or []))))
        prof["spouses"] = "、".join(f.name_or(s) for s in spouse_ids if f.name(s))
        prof["concubines"] = "、".join(f.name_or(s) for s in _asof_ids(f, fam.get("concubine") or []) if f.name(s))
        prof["children"] = "、".join(f.name_or(c) for c in _asof_ids(f, fam.get("child") or []) if f.name(c))
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
        for mem in prof.get("memories") or []:
            s = _mem_sentence(f, cid, mem)
            if not s:
                continue
            # v11: as_of 截断 — 十年传记只列该时期前的事件
            if f.as_of and mem.get("creation_date") \
                    and cl.date_key(mem.get("creation_date")) > cl.date_key(f.as_of):
                continue
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
    # 玩家上位链 (最后快照)。v11: as_of 早于末档 (十年传记) 时, 当前熔件的上位链
    # 是末档状态 (周皇朝), 与十年前不符且无法按时期重建 → 省略, 避免「隶属周皇朝」误写。
    pid = f.cache.get("player_id")
    if pid is not None and not (f.as_of and cl.date_key(f.as_of) < cl.date_key(
            f.cache.get("last_date") or f.as_of or "9999.9.9")):
        prov = f.character_location_province(pid)
        county_tid = f.county_at_province(prov)
        chain = f.liege_chain(county_tid) if county_tid else []
        if chain:
            parts = []
            for tid, hid in chain:
                hn = f.name_or(hid, "") if hid is not None else ""
                parts.append(f"{f.title(tid)}（{hn}）" if hn else f.title(tid))
            out["liege_chain"] = " → ".join(parts)
    # 高位头衔持有者变化 (h_/e_/k_): title history 精确日期为主, realm_history 快照兜底;
    # 头衔名按任期 (v11: 唐皇朝 → 周皇朝 更名可见, 882 的「周皇朝」错标即由此根除)。
    # v13: 只收「相关」高位头衔 (上位链 + 相关角色曾任 + 朝廷职司另列), 剔除全球
    # 各国更替噪声; 朝廷职司 (e_minister_*) 不进本表。
    if f.as_of:
        rh = [h for h in f.cache.get("realm_history") or []
              if cl.date_key(h.get("date")) <= cl.date_key(f.as_of)]
    else:
        rh = f.cache.get("realm_history") or []
    # v13: 历史事件只收「首档前 ~30 年」之后 (剔除汉晋隋唐等 25 年古史噪声,
    # 保留本朝更名/夺位叙事: 唐皇朝→周皇朝 919 崔佛·菲利普)
    min_dk = min((cl.date_key(h.get("date")) for h in rh), default=None)
    hist_min_y = (min_dk[0] - 30) if min_dk else None

    # 相关角色集: 家人/好友/仇人/宫廷任官 (高位头衔曾属他们才收录)
    related = _related_ids(f)
    for _cid, _rec in (f.cache.get("characters") or {}).items():
        for _m in _rec.get("memories") or []:
            if _m.get("type") in ("became_friends", "became_soulmates",
                                  "became_blood_brother", "became_rivals",
                                  "became_grudge", "became_nemesis"):
                for _v in (_m.get("participants") or {}).values():
                    if isinstance(_v, int) and _v == pid:
                        related.setdefault(int(_cid), 2)
                        break
    for h in f.cache.get("court_positions") or []:
        for p in h.get("positions") or []:
            if isinstance(p.get("employee"), int):
                related.setdefault(p["employee"], 2)

    # 主角所在上位链头衔 (含最高领主) — 本朝主干
    chain_tids = set()
    try:
        prov = f.character_location_province(pid)
        county_tid = f.county_at_province(prov)
        if county_tid is not None:
            chain_tids.update(int(t) for t, _h in f.liege_chain(county_tid) or [])
    except Exception:
        pass

    # ① title history 精确序列 (主源)
    hist_map = {}  # tid -> [(date, holder), ...]
    for tid, t in f._lt.items():
        if not isinstance(t, dict):
            continue
        key = t.get("key") or ""
        if not key.startswith(("h_", "e_", "k_")):
            continue
        if key.startswith("e_minister_"):  # v13: 朝廷职司另列
            continue
        hist = t.get("history") or {}
        if not isinstance(hist, dict) or not hist:
            continue
        seq = []
        for d, ev in sorted(hist.items(), key=lambda x: cl.date_key(x[0])):
            if f.as_of and cl.date_key(d) > cl.date_key(f.as_of):
                break
            if hist_min_y is not None:
                try:
                    if int(str(d).split(".")[0]) < hist_min_y:
                        continue
                except Exception:
                    pass
            holder = ev.get("holder") if isinstance(ev, dict) else ev
            if holder is not None:
                seq.append((d, holder))
        if seq:
            hist_map[int(tid)] = seq
    # ② realm_history 快照 (仅补 title history 未覆盖的头衔, 消除双源重复)
    for h in rh:
        for tid, holder in (h.get("holders") or {}).items():
            t = f._lt.get(str(tid)) or {}
            key = t.get("key") or ""
            if not key.startswith(("h_", "e_", "k_")):
                continue
            if key.startswith("e_minister_"):
                continue
            if holder is None or int(tid) in hist_map:
                continue
            hist_map.setdefault(int(tid), []).append((h.get("date"), holder))

    # ③ 相关过滤: 上位链头衔 / 相关角色曾任头衔
    keep_tids = set(chain_tids)
    for tid, seq in hist_map.items():
        if tid in keep_tids:
            continue
        if any(int(h) in related for _d, h in seq):
            keep_tids.add(tid)
    span_end = f.as_of or f.cache.get("last_date")
    changes = []
    for tid in sorted(keep_tids):
        seq = sorted(hist_map.get(tid) or [], key=lambda x: cl.date_key(x[0]))
        if not seq:
            continue
        # 去重: 同日同持有者只留一条 (title history 与快照同日重复)
        dedup = []
        seen_k = set()
        for d, holder in seq:
            k = (cl.date_key(d), holder)
            if k in seen_k:
                continue
            seen_k.add(k)
            dedup.append((d, holder))
        prev = None
        prev_nm = None
        bits = []
        for i, (d, holder) in enumerate(dedup):
            if holder == prev:
                continue
            hn = f.name_or(holder, "") if holder is not None else "无"
            end = dedup[i + 1][0] if i + 1 < len(dedup) else span_end
            nm = f._name_in_span(tid, d, end, cid=holder)
            if nm and nm != prev_nm:
                bits.append(f"{nm}：{f.date(d)}：{hn}")
                prev_nm = nm
            else:
                bits.append(f"{f.date(d)}：{hn}")
            prev = holder
        if len(bits) > 1:
            changes.append("，".join(bits))
    # 排序: 上位链头衔在前 (按层级降序), 其余按最后更替日期降序 (近期先)
    def _sort_key(ln):
        nm = ln.split("：", 1)[0]
        for tid in chain_tids:
            if nm.startswith(f.title(tid)):
                return (0, -f._TT_RANK.get((f._lt.get(str(tid)) or {}).get("key", "")[:2], 0))
        return (1, 0)
    changes.sort(key=_sort_key)
    if changes:
        out["holder_changes"] = changes
    # v13: 朝廷职司现任 (尚书省六部/御史台/枢密院 — 当前持有者 + 职司官职)
    min_off = f._current_ministers()
    if min_off:
        out["ministers"] = min_off
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
            "house": _dynasty_display(prof.get("dynasty_name"),
                                      prof.get("house_name")),
            "house_branch": _house_branch(prof.get("dynasty_name"),
                                          prof.get("house_name")),
            # v13: 死者官职 (含家族领袖的「XX家族乡绅」, 此前刺客列传无官职信息)
            "office": f.official_title(cid),
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
    # v11: 击杀人数多时剔除 lowborn (无家族、非家人/友/仇), 保模型注意力;
    # as_of 截断 — 十年传记只收该时期前已死的死者 (892 年不出现 142 人刺客列传);
    # 死亡日期未知 (9999.9.9) 的死者视为不晚于 as_of, 保留。
    if f.as_of:
        ao = cl.date_key(f.as_of)
        out = [e for e in out
               if e["death_date"] == "9999.9.9" or cl.date_key(e["death_date"]) <= ao]
    if len(out) > KILL_LOWBORN_THRESHOLD:
        keep = _kill_keep_ids(cache, pid)
        out = [e for e in out if e["house"] or e["id"] in keep]
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
    # v11: as_of 截断 — 十年传记只列该时期前的行踪
    if f.as_of:
        hist = [loc for loc in hist
                if not loc.get("date") or cl.date_key(loc.get("date")) <= cl.date_key(f.as_of)]
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
    """群英录 (v5): 行政制玩家时, 朝中要员 (主角相关的有政治类记忆或历任高位头衔者)。
    剔除路人 (只收主角/家人/结友结怨者), 截断 60 名防提示词膨胀。
    原实现对缓存记录查 prof.get("name")/"titles_held" (缓存无此键) 恒为空, 此处修正。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    related = _related_ids(f)
    names = []
    seen = set()
    for cid, rec in (cache.get("characters") or {}).items():
        if len(names) >= 60:
            break
        if int(cid) == pid or int(cid) not in related:
            continue
        if not (rec.get("name_full") or rec.get("name_zh")):
            continue
        has_pol = any(m["type"] in POLITICAL_TYPES_KEYS
                      for m in rec.get("memories") or [])
        if has_pol or f.held_titles(int(cid)):
            nm = f.name_or(int(cid))
            if nm and nm not in seen:
                seen.add(nm)
                names.append(nm)
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


def build_facts(cache, melt, names_path=None, as_of=None):
    """渲染干净事实集。melt 为 dict (已加载)。
    as_of (v11): 传记数据截止日期; 十年传记传十年末, 官职/历任/时间线/朝局按此截断。"""
    f = Facts(cache, melt, names_path, as_of=as_of)
    period = ""
    sources = cache.get("sources") or []
    if sources:
        period = f"{sources[0]} – {sources[-1]}"
    cpl, cpch = f.court_positions_lines()
    # v8: 死因中文化 (总纲【卒年】不再泄漏英文 key, 干净事实铁律)
    # v11: as_of 早于死期 (十年传记) 时视为在世, 不泄漏死亡信息
    pd = cache.get("player_death")
    if pd and as_of and cl.date_key(as_of) < cl.date_key(pd.get("date") or "9999.9.9"):
        pd = None
    if pd:
        pd = dict(pd)
        pd["reason_zh"] = _death_reason(f.table, pd.get("reason"))
    facts = {
        # v14: 宗族名 (东方名序的姓) + 家族/分家 (风味补充)
        "house": _dynasty_display(cache.get("dynasty_name"),
                                  cache.get("house_name")),
        "house_branch": _house_branch(cache.get("dynasty_name"),
                                      cache.get("house_name")),
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
        "as_of": as_of,
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
        # v9: 家族恩怨录 / 宝物志 数据源
        "house_feuds": f.house_feuds(),
        "family_artifacts": f.family_artifacts(),
        # v13: Facts 实例引用 (biography 的关系缘由渲染等需要实例方法)
        "_facts": f,
    }
    # v14: 十年戏剧主题 (Top10, 并列第10名全保留) — 模块切片与总纲预告用
    facts["decade_modules"] = decade_module_top(facts.get("timeline") or [],
                                                facts.get("protagonist") or {})
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
    # v14: 家族名 + 分家 (自然语言, 无等号): 藤原氏（北家）
    fam = p.get("house") or ""
    if fam and p.get("house_branch"):
        fam = f"{fam}（{p['house_branch']}）"
    lines.append(f"主角：{p.get('name')}（{fam}）")
    for k in ("birth", "culture", "faith", "traits", "government"):
        if p.get(k):
            lines.append(f"{k}：{p[k]}")
    return "\n".join(lines)
