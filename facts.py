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
import hashlib
import random

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

# v24: 中文建制地名 (地名本身以 州/府/京/郡/县 收尾) 不再叠西式/政体层级词 —
# 贝州伯爵领/杭州州府 → 贝州/杭州 (只对伯爵领 c_ 级生效, 公国/王国名不受影响)。
_CN_PLACE_SUFFIX_RE = re.compile(r"[州府京郡县]$")
# v24: CK3 culture_titles 词族 (汉人文化 → 键后缀 chinese: 王/公/侯/伯/将军…)。
_CULTURE_TITLE_FAMILY = {"han": "chinese"}

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
    "battle_won_memory": "{name}打了胜仗。",
    "battle_lost_memory": "{name}吃了败仗。",
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
    "secret_deviant": "性僻",
    "secret_non_believer": "不信教",
    "secret_crypto_religionist": "暗奉异教",
    "secret_witch": "行巫",
    "secret_embezzler": "侵吞库银",
    "secret_siphoned_treasury": "挪用国库",
    "secret_unmarried_illegitimate_child": "血脉存疑",
    "secret_disputed_heritage": "血统有争",
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
    "secret_lover": "私通",
}
# 谋杀类隐事: 正文归《刺客列传》, 篇内只计数 + 索引
SECRET_MURDER_TYPES = {"secret_murder", "secret_murder_attempt"}

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

# v28: 健康/压力档位 — 游戏数值属元信息, 提示词只给档位词 (现代白话)。
# 阈值取自游戏 defines HEALTH_STATE_LEVELS_VALUES {0,1,3,5,7} 与
# script_values (dying 0 / poor 1 / fine 3 / good 5 / excellent 7);
# 压力按 game_concept_stress_level「每 100 压力升一级, 0–3 级」。
_HEALTH_BANDS = ((7.0, "身体康健"), (5.0, "健康良好"), (3.0, "健康尚可"),
                 (1.0, "身体抱恙"), (0.0, "病危"))
_STRESS_BANDS = {1: "压力较轻", 2: "压力较重", 3: "压力极重"}


def health_state_zh(value):
    """健康值 → 档位词 (元信息不外泄); 无法解析返回 ''。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    for lo, word in _HEALTH_BANDS:
        if v >= lo:
            return word
    return "垂危"


def stress_state_zh(value):
    """压力值 → 档位词 (0 级 = 无压力, 不写); 无法解析返回 ''。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    return _STRESS_BANDS.get(min(3, int(v // 100)), "")

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
    "successful_murder": "victim",
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
        return "去世"
    v = FLAVOR_DEATH_ZH.get(reason)
    if v:
        return v
    v = L.loc(table, reason)
    if v and "[" not in v and "$" not in v and v != "死于":
        return v
    return DEATH_REASON_ZH.get(reason, "去世")


# v16: 动作型死因 → 施事句式 (原始 reason key → 动词)。有凶手/行刑者/对手
# 记录时, 把施事者直接嵌进句内 (被XXX谋杀 / 被XXX处决 / 与XXX决斗而亡),
# 不再另起「凶手为…」尾巴 — 更短, 也更像自然语言; 战场/意外/病亡的击杀者
# 不是「凶手」, 一律不点名。谋杀分两档: death_murder 是败露的谋杀 (被XXX
# 谋杀), death_mysterious 是未败露的谋杀 (被XXX秘密谋杀)。
_DEATH_KILLER_VERB = {  # 凶手: 被{凶手}{动词}
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
_DEATH_EXECUTOR_VERB = {  # 行刑者: 被{行刑者}{动词}
    "death_execution": "处决",
    "death_punishment": "处决",
    "death_hostage_execution": "处决",
    "death_execution_blood_eagle": "处决",
    "death_crucified": "钉上十字架",
    "death_crucified_by_mob": "钉上十字架",
    "death_burned_witch": "烧死在火刑柱上",
}

# v22: 处决方式 (用户需求 2026-09-02) — 存档不记录行刑者实际选择的方式,
# 受害死因键恒为 death_execution; 依 execute_prisoner_interaction 的
# send_option 可用条件 (见游戏 common/character_interactions/00_prison_interactions.txt),
# 用传记所用熔件/缓存的行刑者状态近似判定可用方式, 再按 (行刑者, 受害者,
# 死亡日期) 稳定伪随机取一 — 不同处决有变化, 同一处决重跑不漂移。
# (顺序即游戏界面顺序; 措辞按 EXECUTION_* 本地化与 death_* 死因雅化。)
_EXECUTION_OPTIONS = (
    ("beheaded",   "斩首"),                     # EXECUTION_BEHEADED 砍头
    ("devour",     "砍头后吃掉"),               # EXECUTION_DEVOUR 砍头……然后吃掉!
    ("burned",     "烧死"),                     # EXECUTION_BURNED 烧死在火刑柱上
    ("sacrifice",  "献祭给神灵"),               # EXECUTION_SACRIFICE 献祭
    ("kennel",     "处以犬决"),                 # EXECUTION_KENNEL 犬决
    ("provisions", "做成神秘的肉充作口粮"),     # EXECUTION_PROVISIONS 做成神秘的肉
)
_EXECUTION_ORDER = {k: i for i, (k, _v) in enumerate(_EXECUTION_OPTIONS)}

# 东亚系文化模板 (近似的 asian heritage 支柱 — 存档不存文化支柱, 用熔件
# culture_manager 实测模板 + 周边族系近似; 实际数据中行刑者以玩家(汉)与
# 欧洲 AI 为主, 误判只影响 斩首/烧死 二选一, 影响有限)。
_ASIAN_HERITAGE_TPL = frozenset({
    # heritage_chinese 系 (熔件实测: han/bai/shatuo)
    "han", "bai", "shatuo", "yue", "wu", "shu", "chinese",
    # heritage_japonic
    "japanese", "ryukyuan",
    # heritage_korean / buyeo
    "korean", "silla", "goryeo", "baekje", "goguryeo", "balhae", "parhae",
    # heritage_qiangic (西夏/党项/羌)
    "qiang", "tangut", "xixia", "dangxiang", "sumpa",
    # heritage_tibetan
    "tibetan", "bodpa", "tsangpa", "wenmo",
    # heritage_viet
    "viet", "vietnamese", "muong",
    # 北亚 (契丹/女真/蒙古)
    "khitan", "jurchen", "manchu", "mongol", "nivkh",
    # 中南半岛
    "burmese", "mon", "shan", "thai", "dai", "lao", "khmer",
})
_DEATH_OPPONENT_VERB = {  # 对手: 与{对手}{动词}而亡
    "death_duel": "决斗",
    "death_fight": "斗殴",
    "death_fight_killer": "斗殴",
    "death_contest_duel_accident": "决斗",
    "death_contest_wrestling_accident": "角力",
}
_DEATH_AGENT_TAIL = {  # 死因自带惨状/情状, 施事者用「凶手/行刑者为…」点出
    "death_head_ripped_off": "凶手",   # 身首异处，凶手为XXX
    "death_eradicated": "行刑者",      # 连同全族被处决，行刑者为XXX
}

# v25: 暗杀死法池 (用户需求 2026-09-08) — 存档对暗杀只记四类泛化死因
# (death_mysterious / death_murder / death_disappearance / death_poison), 传记
# 因此只剩「被X秘密谋杀」「消失无踪」两句。此池以游戏本地化 death_*_killer 文案
# 为主 (data/localization.json 中文原文), 辅以史实手写短语 — 中世纪至文艺复兴
# 东西方暗杀手法的研究见 docs/修复方案_田所两问题.md 2.2。
# 存档已记具体死法者 (death_defenestration 等) 仍按存档原样渲染, 池子只补泛化死因。
#
# 痕迹标签: covert=不留伤痕可伪装病亡 / overt=见血张扬 / vanish=尸骨无踪 / poison=毒杀
# 死因 → 允许的标签集 (方法标签须为其子集):
_METHOD_REASON_TAGS = {
    "death_mysterious":     frozenset({"covert", "vanish", "poison"}),
    "death_disappearance":  frozenset({"vanish"}),
    "death_murder":         frozenset({"covert", "overt", "poison"}),
    "death_murder_known":   frozenset({"covert", "overt", "poison"}),
    "death_assassination":  frozenset({"covert", "overt", "poison"}),
    "death_poison":         frozenset({"poison"}),
}
# 游戏本地化条目: (本地化键, 标签集, 文化圈, 幼童可用) — 短语由本地化表渲染,
# 槽位 [TARGET_CHARACTER.GetUIName(Possessive)] → 凶手名, [CHARACTER.GetHerHis] → 其。
_ASSASSINATION_GAME_KEYS = (
    # 隐蔽 / 毒杀
    ("death_poison_killer",                      frozenset({"covert", "poison"}), "any", True),
    ("death_drowned_killer",                     frozenset({"covert"}), "any", True),
    ("death_smothered_by_downy_robe_killer",     frozenset({"covert"}), "west", True),
    ("death_too_much_dessert_killer",            frozenset({"covert", "poison"}), "west", False),
    ("death_strongest_potion_killer",            frozenset({"covert", "poison"}), "any", False),
    ("death_treatment_killer",                   frozenset({"covert", "poison"}), "any", False),
    ("death_hunting_mysterious_killer",          frozenset({"covert"}), "west", False),
    # 失踪 (尸骨无踪) — 短语均含致死意 (传记句式为「死于…，X」)
    ("death_disappearance_killer",               frozenset({"vanish"}), "any", True),
    ("death_fall_in_hole_killer",                frozenset({"vanish"}), "any", True),
    ("death_nailed_in_cabinet_killer",           frozenset({"covert"}), "any", False),
    ("death_starved_killer",                     frozenset({"covert"}), "any", False),
    # 张扬
    ("death_assassination_killer",               frozenset({"overt"}), "any", False),
    ("death_murder_killer",                      frozenset({"overt"}), "any", False),
    ("death_decapitated_killer",                 frozenset({"overt"}), "any", False),
    ("death_beaten_killer",                      frozenset({"overt"}), "any", False),
    ("death_skull_cracked_open_killer",          frozenset({"overt"}), "any", False),
    ("death_dragged_killer",                     frozenset({"overt"}), "any", False),
    ("death_trampled_killer",                    frozenset({"overt"}), "any", False),
    ("death_whipping_killer",                    frozenset({"overt"}), "any", False),
    ("death_torture_killer",                     frozenset({"overt"}), "any", False),
    ("death_piteously_cut_down_killer",          frozenset({"overt"}), "any", False),
    ("death_revenge_killer",                     frozenset({"overt"}), "any", False),
    ("death_by_artifact_killer",                 frozenset({"overt"}), "any", False),
    ("death_manhunted_killer",                   frozenset({"overt"}), "any", False),
    ("death_ritually_hung_killer",               frozenset({"overt"}), "any", False),
    ("death_scuffle_with_soldiers_killer",       frozenset({"overt"}), "any", False),
    ("death_head_ripped_off_killer",             frozenset({"overt"}), "any", False),
    ("death_heart_ripped_out_killer",            frozenset({"overt"}), "any", False),
    ("death_defenestration_killer",              frozenset({"overt"}), "west", False),
    ("death_bell_killer",                        frozenset({"overt"}), "west", False),
    ("death_burned_killer",                      frozenset({"overt"}), "west", False),
    ("death_viciously_dismembered_killer",       frozenset({"overt"}), "west", False),
    # 需受害者身居高位 (宫廷政变 / 御座 / 凯旋道)
    ("death_murder_feast_killer",                frozenset({"overt"}), "any", False),
    ("death_coup_successful_killer",             frozenset({"overt"}), "any", False),
    ("death_thrown_off_kathisma_killer",         frozenset({"overt"}), "west", False),
    ("death_thrown_onto_chariot_track_killer",   frozenset({"overt"}), "west", False),
)
_METHOD_HIGH_RANK = frozenset({
    "death_murder_feast_killer", "death_coup_successful_killer",
    "death_thrown_off_kathisma_killer",
    "death_thrown_onto_chariot_track_killer",
})
# 史实补充条目: (键, 短语模板 {k}=凶手名, 标签集, 文化圈, 幼童可用)
# 东方手法依据: 《史记·刺客列传》(荆轲图穷匕见/专诸鱼肠剑/豫让)、
# 《资治通鉴》卷十二「使人持酖饮之」(鸩杀); 西方依据见 docs 2.2 所列诸源。
_ASSASSINATION_HISTORY = (
    ("hist_zhen_wine",     "被{k}遣人奉鸩酒赐死",             frozenset({"covert", "poison"}), "east", False),
    ("hist_silk_cord",     "被{k}使人以丝绳缢杀",             frozenset({"covert"}), "east", False),
    ("hist_poison_needle", "被{k}以毒针刺入要穴而亡",         frozenset({"covert", "poison"}), "east", False),
    ("hist_dagger_scroll", "被{k}遣刺客藏匕首于书卷中刺死",   frozenset({"overt"}), "east", False),
    ("hist_fish_sword",    "被{k}遣刺客以鱼肠短剑刺于席间",   frozenset({"overt"}), "east", False),
    ("hist_smother",       "被{k}使人以枕褥闷杀",             frozenset({"covert"}), "east", True),
    ("hist_night_cord",    "被{k}夜入寝帐扼杀",               frozenset({"covert"}), "east", True),
    ("hist_river_drown",   "被{k}使人沉于江中",               frozenset({"vanish"}), "east", True),
    ("hist_herb_poison",   "被{k}使人以断肠草下于汤药",       frozenset({"covert", "poison"}), "east", False),
    ("hist_arsenic",       "被{k}使人以砒霜下于酒食",         frozenset({"covert", "poison"}), "east", False),
    ("hist_fake_edict",    "被{k}矫诏赐死",                   frozenset({"covert"}), "east", False),
    ("hist_borrowed_blade", "被{k}假手他人所杀",              frozenset({"covert", "overt"}), "east", False),
    ("hist_buried_alive",  "被{k}使人活埋",                   frozenset({"vanish", "overt"}), "east", True),
    ("hist_poison_arrow",  "被{k}遣人自暗处以毒箭射杀",       frozenset({"covert", "poison"}), "east", False),
    ("hist_temple_vanished", "被{k}使人缢杀后弃尸荒野，尸骨无踪", frozenset({"vanish"}), "east", False),
    ("hist_poison_ring",   "被{k}以毒戒指将毒药投入酒中",     frozenset({"covert", "poison"}), "west", False),
    ("hist_poison_gloves", "被{k}以浸毒的手套毒杀",           frozenset({"covert", "poison"}), "west", False),
    ("hist_sack_river",    "被{k}装入麻袋沉入河中",           frozenset({"vanish"}), "west", True),
    ("hist_bath_drown",    "被{k}溺毙于浴盆",                 frozenset({"covert"}), "west", False),
    ("hist_church_stab",   "被{k}遣刺客刺杀于教堂",           frozenset({"overt"}), "west", False),
    ("hist_throat_sleep",  "被{k}遣人于睡梦中割喉",           frozenset({"covert"}), "west", True),
    ("hist_crossbow",      "被{k}遣人自窗口以弩箭射杀",       frozenset({"covert"}), "west", False),
    ("hist_snake_basket",  "被{k}以毒蛇置于篮中咬毙",         frozenset({"covert", "poison"}), "west", False),
    ("hist_bravo",         "被{k}雇刺客行刺于街巷",           frozenset({"overt"}), "west", False),
    ("hist_physician",     "被{k}买通医者，于汤药中下毒",     frozenset({"covert", "poison"}), "west", False),
    ("hist_mercury",       "被{k}以水银慢性下毒",             frozenset({"covert", "poison"}), "west", False),
    ("hist_well_drown",    "被{k}推入井中溺毙",               frozenset({"covert", "vanish"}), "west", True),
    ("hist_fake_suicide",  "被{k}使人缢死，伪作自尽",         frozenset({"covert"}), "any", False),
    ("hist_banquet",       "被{k}于酒宴中下毒，归而暴卒",     frozenset({"covert", "poison"}), "any", False),
)


def _render_killer_loc(table, loc_key, kname):
    """本地化死法文案 → 中文短语 (槽位替换凶手名)。
    直接用原始表值 — L.loc 会把 [TARGET_CHARACTER.GetUIName] 一并剥掉; 此处先把
    凶手/受害者槽位换成控制符, 剥完格式码再回填, 未解槽位/模板引用返回 ''。"""
    raw = table.get(str(loc_key))
    if not isinstance(raw, str) or not raw:
        return ""
    s = raw.replace("[CHARACTER.GetHerHis]的", "\x03")
    s = s.replace("[TARGET_CHARACTER.GetUINamePossessive]", "\x01")
    s = s.replace("[TARGET_CHARACTER.GetUIName]", "\x02")
    s = s.replace("[CHARACTER.GetHerHis]", "\x03")
    s = L.clean_loc_value(s, table)
    s = s.replace("\x01", kname).replace("\x02", kname).replace("\x03", "其")
    if "[" in s or "$" in s or "\x01" in s or "\x02" in s or "\x03" in s:
        return ""
    return s


def _death_clause(table, reason_key, killer, name_of):
    """死因 → 自然中文短句 (含施事者嵌入)。

    reason_key: 原始死因 key; killer: 凶手/行刑者/对手角色 id 或 None;
    name_of: 角色 id → 名字。返回「被XXX谋杀」「被XXX秘密谋杀」「与XXX决斗而亡」
    「身首异处，凶手为XXX」或纯死因短句 (无施事或非动作型死因)。"""
    reason = _death_reason(table, reason_key)
    kname = name_of(killer) if killer is not None else ""
    if killer is not None and kname:
        verb = _DEATH_KILLER_VERB.get(reason_key)
        if verb:
            return f"被{kname}{verb}"
        verb = _DEATH_EXECUTOR_VERB.get(reason_key)
        if verb:
            return f"被{kname}{verb}"
        verb = _DEATH_OPPONENT_VERB.get(reason_key)
        if verb:
            return f"与{kname}{verb}而亡"
        role = _DEATH_AGENT_TAIL.get(reason_key)
        if role:
            return f"{reason}，{role}为{kname}"
        return reason  # 战场/意外/病亡的击杀者不是「凶手」, 不点名
    # 无施事: 裸动作死因补「被」字 (被处决/被谋杀/被毒杀)
    if reason in ("处决", "谋杀", "毒杀"):
        reason = "被" + reason
    return reason


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

# v16: 王子词覆盖 — 本地化表把封建王国之女写成「郡主」(唐制亲王之女的东亚
# 封号), 西式王国/帝国之女在传记里一律写「公主」; 天朝制的 皇女/郡主/公女
# 属刻意东亚风味, 不在覆盖之列 (见 _prince_word)。
_PRINCE_WORD_OVERRIDE = {
    "princess_kingdom_feudal_chinese": "公主",
}


class Facts:
    """一次 build_facts 的上下文: 缓存 + melt + 名字/头衔/本地化解析。
    as_of: 传记数据截止日期 (十年传记 = 十年末; 终传/在世 = 最后档期)。
    非空时 官职/称号/历任/时间线/朝局 均只取该日期之前的事实 (v11)。
    decade (v17): 十年传记序号 (1,2,3…), 非空时时间线/概览/摘要/刺客列传
    只收本十年 (as_of−10年, as_of] 的事件 (修复方案_汤利五问题.md 决策 1/2)。"""

    def __init__(self, cache, melt, names_path, as_of=None, decade=None,
                 nickname_override=None):
        self.cache = cache
        self.melt = melt
        self.names_path = names_path
        self.as_of = as_of
        self.decade = decade
        # v20: 按时代绰号覆盖 {cid: 绰号} — 十年传记重跑时绰号取该十年末熔件,
        # 不随最新档漂移 (878 时代「嗜血者」不会被 888 档的「屠狼者」覆盖)
        self._nick_override = dict(nickname_override or {})
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
        self._regnal_cache = {}  # v17: 世系编号 (cid, tid, date) -> 序号
        # v16: 游戏关系原因 (opinions.active_opinions 索引, 惰性构建)
        self._opinion_index = None
        self._rel_reason_cache = {}
        # v11: 语言 → 文化模板列表 反查索引 (同一语言多文化共享, 如 language_norse
        # 同时被 norman/norse 持有; 推断时优先有父名规则的模板)
        self._lang_to_tpl = {}
        for _cid, _e in ((melt.get("culture_manager") or {}).get("cultures") or {}).items():
            if not isinstance(_e, dict):
                continue
            _lg = _e.get("language")
            if _lg:
                self._lang_to_tpl.setdefault(_lg, []).append(_e.get("culture_template") or "")
        # v27: 文化模板 → 语言 反查 (角色 culture id 被清空时, 由模板回推母语)
        self._tpl_to_lang = {}
        for _cid, _e in ((melt.get("culture_manager") or {}).get("cultures") or {}).items():
            if not isinstance(_e, dict):
                continue
            _tpl = _e.get("culture_template")
            _lg = _e.get("language")
            if _tpl and _lg:
                self._tpl_to_lang.setdefault(_tpl, _lg)
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
                # v15: 同日多事件 (destroyed+created 同日期等, 重复键被合并为列表)
                entries = _ev if isinstance(_ev, list) else [_ev]
                for _e in entries:
                    _h = _e.get("holder") if isinstance(_e, dict) else _e
                    _typ = _e.get("type") if isinstance(_e, dict) else ""
                    if _h is None:
                        if cur is not None and gain is not None:
                            self._holder_intervals.setdefault(cur, {}).setdefault(
                                _tid, []).append((gain, _d, _typ or ""))
                        cur, gain = None, None
                        continue
                    try:
                        _hid = int(_h)
                    except (TypeError, ValueError):
                        continue
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

    # ---- v17: 世系编号 (II/III 二世标记) ----
    # 游戏不把编号存进存档, 显示时按「首要头衔 title history 中同名前任数 + 1」
    # 动态计算 (修复方案_汤利五问题.md 问题7, 实测: c_braila 860 年 Ciprian →
    # 893 年 Ciprian 即「奇普里安II」; k_ruthenia 881 年父子两代 Ruslan →
    # 子为「鲁斯兰·克里维奇二世」)。I 不显示。

    def regnal_number(self, cid, tid, date=None):
        """角色 cid 在头衔 tid 上的世系序号: 1 + (登位前同名前任数)。
        同名按熔件 raw first_name 比对 (中文 mod 名同码点串一致)。
        返回 ≥1 的整数。"""
        key = (cid, tid, date)
        v = self._regnal_cache.get(key)
        if v is not None:
            return v
        fn = (self._chars.get(str(cid)) or {}).get("first_name") or ""
        n = 1
        if fn and tid is not None:
            hist = (self._lt.get(str(tid)) or {}).get("history") or {}
            if isinstance(hist, dict) and hist:
                acc = None
                for d in sorted(hist, key=cl.date_key):
                    h = hist[d]
                    hid = h.get("holder") if isinstance(h, dict) else h
                    if hid == cid:
                        acc = d
                        break
                limit = None
                if acc:
                    limit = cl.date_key(acc)
                elif date:
                    limit = cl.date_key(date)
                elif self.as_of:
                    limit = cl.date_key(self.as_of)
                if limit is not None:
                    for d, h in hist.items():
                        hid = h.get("holder") if isinstance(h, dict) else h
                        if hid == cid or not isinstance(hid, int):
                            continue
                        if cl.date_key(d) >= limit:
                            continue
                        if fn == ((self._chars.get(str(hid)) or {}).get("first_name") or ""):
                            n += 1
        self._regnal_cache[key] = n
        return n

    def _last_high_title_before(self, cid, date=None):
        """cid 在 date (含) 前最后持有的最高层级头衔 (v17)。
        头衔在当日已易手 (死日同日继位) 时, `_primary_title_at` 取不到,
        世系编号回退到最近一段高位持有。无则返回 None。"""
        ao = cl.date_key(date) if date else \
            (cl.date_key(self.as_of) if self.as_of else None)
        best_tid, best_rank, best_gain = None, -1, None
        for tid, ivs in self._hold_intervals(cid, date).items():
            key = (self._lt.get(str(tid)) or {}).get("key") or ""
            rank = self._TT_RANK.get(key[:2], 0)
            for (g, _l, _lt) in ivs:
                if not g:
                    continue
                gk = cl.date_key(g)
                if ao is not None and gk > ao:
                    continue
                if rank > best_rank or \
                        (rank == best_rank and best_gain is not None and gk > best_gain):
                    best_tid, best_rank, best_gain = tid, rank, gk
        return best_tid

    def nickname(self, cid):
        """角色昵称 (v17): 熔件 nickname_text 直接就是中文昵称 (勇敢者/铁腕…),
        无则 ''。v20: 按时代覆盖优先 (十年传记重跑时绰号取自该十年末熔件)。"""
        ov = self._nick_override or {}
        if cid in ov:
            return ov[cid] or ""
        c = self._chars.get(str(cid)) or {}
        return (c.get("nickname_text") or "").strip()

    def _insert_nickname(self, nm, nick):
        """把昵称并入显示名 (v21, 用户决策 2026-09-02): 一律绰号前置、去引号 —
        中文史传惯例, 东方人名与西方名序同框架 (欺诈者郭靖 / 秃头仲宣 /
        秃头查理·加洛林 / 征服者威廉·诺曼底), 不再用 名“绰号” 后缀。
        有绰号即不再使用世系编号 (编号让位于绰号)。"""
        return f"{nick}{nm}"

    def name_with_regnal(self, cid, date=None):
        """显示名 + 昵称 + 世系编号 (v21): 有绰号 → 绰号前置形式 (欺诈者郭靖 /
        秃头查理·加洛林), 不追加世系编号 — 编号让位于绰号;
        无绰号 → 仅西方名序 (名·家名) 标编号, 紧跟名 (史书惯例: 路易十四/查理二世,
        鲁斯兰二世·克里维奇, 不给姓冠编号); 东方人名 (姓+名 无分隔) 与单段名无编号;
        十起不带世 (路易十一)。
        v20: 天皇座非统治者子女先走「名+亲王/内亲王」(利永亲王), 不拼宗族姓。"""
        tn = self._tenno_prince_name(cid, date)
        if tn:
            nick = self.nickname(cid)
            if nick:
                return f"{nick}{tn}"
            return tn
        nm = self.name_or(cid)
        if not nm:
            return nm
        nick = self.nickname(cid)
        if nick:
            return self._insert_nickname(nm, nick)
        if "·" not in nm:
            # v18: 东方人名 (姓+名 无分隔) 与单段名没有世系编号
            return nm
        try:
            _tier, tid = self._primary_title_at(cid, as_of=date)
        except Exception:
            return nm
        if tid is None:
            # v17: 死日头衔同日易手时回退到最后持有的高位头衔
            tid = self._last_high_title_before(cid, date)
        if tid is None:
            return nm
        n = self.regnal_number(cid, tid, date)
        if n >= 2:
            # v18: 编号紧跟名, 家名/父名在后 — 不给姓冠编号 (史书惯例)
            head, sep, tail = nm.partition("·")
            return f"{head}{_ordinal_zh(n)}{sep}{tail}"
        return nm

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
            return self._specific_name(tid) or name
        # v13: 朝廷职司 (尚书省六部/御史台/枢密院, e_minister_*) — 官职非诸侯,
        # 只给名字 (吏部/御史台), 不追加「帝国/行台」层级词。
        if key.startswith("e_minister_"):
            return name
        # v26: 动态头衔名 (游牧「可萨田所部」/宗族命名「马扎尔」) 即游戏显示名,
        # 优先于伊斯兰国名与层级词后缀。
        specific = self._specific_name(tid)
        if specific:
            return specific
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
            # v24: 中文建制地名 (地名以州/府/京/郡/县收尾, 贝州/杭州…) —
            # 不再叠「伯爵领/州府」层级词, 直用地名本身; 西式地名 (施派尔…) 照旧。
            if key.startswith("c_") and word and _CN_PLACE_SUFFIX_RE.search(name):
                return name
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

    def _specific_name(self, tid):
        """游戏算好的动态头衔名 (v26): 游牧/宗族命名领域的领域名, 如
        c_khortytsia 的「可萨田所部」、k_croatia 的「马扎尔」。静态 name
        (也勒克河/克罗地亚) 只是地名, 与游戏内显示不符。无则返回 ''。"""
        t = self._lt.get(str(tid)) or {}
        tnd = t.get("title_name_data") or {}
        return (tnd.get("specific_title_name") or "").strip()

    def _name_at_date(self, tid, date):
        """头衔在某日期的名称 (不含层级词), 取值优先级 (v26):
        ① 动态头衔名 specific_title_name (游戏内显示名, 游牧「可萨田所部」/
           宗族命名「马扎尔」);
        ② title_history_names 最近一次更名 (本地化键 dynn_title_zhou / 直写名 青徐);
        ③ 基础名 (custom → name)。
        更名史留在 ②: h_china 唐→秦、k_guannei → 秦 这类动态国号只存在于
        title_history_names (实测无 specific_title_name), 死者按卒日国号取名的
        v25 口径仍由 ② 承担。"""
        t = self._lt.get(str(tid)) or {}
        tnd = t.get("title_name_data") or {}
        specific = self._specific_name(tid)
        if specific:
            return specific
        base = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
        best = None
        if date:
            for h in (tnd.get("title_history_names") or []):
                try:
                    if h.get("date") and cl.date_key(str(h["date"])) <= cl.date_key(str(date)):
                        best = h["name"]
                except Exception:
                    continue
        if best is not None:
            v = L.loc(self.table, str(best))
            if v:
                return v
            s = str(best)
            if re.search(r"[A-Za-z_]", s):
                # v21: 本地化表缺该改名键时回退基础名, 不直出裸 key (防 key 泄漏)
                return base
            return s  # 直写名 (青徐 等) 原样返回
        return base

    def _title_name_at(self, tid, date, cid=None):
        """头衔在某日期的完整名 (v11): 按日期名 + 层级词 (独立王国=国)。
        cid 提供时按该角色当前独立性取词 (历任/朝局用)。"""
        if tid is None:
            return ""
        t = self._lt.get(str(tid)) or {}
        key = t.get("key") or ""
        if key.startswith("x_"):  # 营地/家族等特殊头衔: 只给名字
            return self._name_at_date(tid, date) or L.loc(self.table, key) or key
        # v26: 动态头衔名本身就是游戏显示的完整名 (可萨田所部), 不叠层级词
        specific = self._specific_name(tid)
        if specific:
            return specific
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
        # v28: 与 title() 同口径 — 中文建制地名 (州/府/京/郡/县收尾) 不叠层级词
        # (此前历任写出「阶州州府」「商州州府」这类重复词)
        if key.startswith("c_") and word and _CN_PLACE_SUFFIX_RE.search(nm):
            return nm
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

    def _is_nomad_camp(self, tid):
        """游牧毡帐头衔 (x_c_nomad_*) — 驻地而非领地 (v26)。"""
        return ((self._lt.get(str(tid)) or {}).get("key") or "") \
            .startswith("x_c_nomad_")

    # v28: 无地/家业头衔三分 — 世族庄园 (_nf_) / 无地冒险者营地 (_laamp_ 等) /
    # 游牧毡帐 (x_c_nomad_)。旧代码把一切 x_ 前缀当「无地冒险者营地」, 使
    # 中国世族 (x_nf_552「陆家族」家族庄园) 被写成「无地冒险者营地」。
    _ESTATE_KEY_MARK = "_nf_"
    _CAMP_KEY_PREFIXES = ("x_mc_", "x_script_", "x_ho_")

    def _is_estate_title(self, tid):
        """家族庄园头衔? (x_nf_/c_nf_/d_nf_ — 中国世族、日本武家、家族地产)"""
        if tid is None:
            return False
        return self._ESTATE_KEY_MARK in ((self._lt.get(str(tid)) or {}).get("key") or "")

    def _is_adventurer_camp(self, tid):
        """无地冒险者营地头衔? (x_d_laamp_* 等; 与游牧毡帐/家族庄园区分)"""
        if tid is None:
            return False
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        if self._is_nomad_camp(tid) or self._is_estate_title(tid):
            return False
        return "_laamp_" in key or key.startswith(self._CAMP_KEY_PREFIXES)

    def title_kind(self, tid):
        """无地/家业头衔语义: 'estate' 世族庄园 / 'nomad' 毡帐 / 'camp' 冒险者营地 /
        '' 领地头衔 (含 c_/b_ 州府县堡)。"""
        if tid is None:
            return ""
        if self._is_nomad_camp(tid):
            return "nomad"
        if self._is_estate_title(tid):
            return "estate"
        if self._is_adventurer_camp(tid):
            return "camp"
        return ""

    def estate_kind_word(self, tid, cid=None):
        """庄园的汉文类别词: 天朝制/中华文化 → 世族庄园; 日本 → 武家庄园;
        其余 → 家族庄园 (按头衔政体 + 持有人文化模板判定)。"""
        gov = self._title_government(tid)
        tpl = self.culture_template(cid) if cid is not None else ""
        if gov in self._CELESTIAL_LIKE_GOVS or tpl in ("han", "chinese", "bai", "yi"):
            return "世族庄园"
        if tpl == "japanese":
            return "武家庄园"
        return "家族庄园"

    def _primary_group(self, held):
        """按持有集计算「主要头衔组」[(gain_date, tid)] (v11): held = {tid: gain_date}
        - 州府/县/堡 (c_/b_) 不进组 (如 898-911 的登州伯爵领等);
        - 有 公国(d_) 及以上或营地(x_) 时: 层级 ≥ 王国只留首要; 公国/营地层取
          首要 + 全部营地 (同级营地/庄园并写, 游牧营地/淄青公国);
        - 只有 州府/县 时: 取最高层级单个。
        - v13: 朝廷职司 (e_minister_*) 不进组 (官职非领地, 由官职行呈现)。
        - v26: 游牧毡帐 (x_c_nomad_*) 是驻地不是领地 — 持有任何领地头衔时
          不进 major 组, 否则「伯爵领 + 毡帐」的游牧主角历任只出现营地,
          取得伯爵领一事完全丢失 (田所2: 891 得也勒克河/巴赫穆特两领无记录)。"""
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
        majors = [it for it in items
                  if (it[1] >= 3 or it[1] == 0)
                  and not self._is_nomad_camp(it[0])
                  and not self._is_estate_title(it[0])]
        if not majors:
            # 仅州府/县/堡 (或仅庄园/毡帐): 最高层级最早获得的一个
            # (v28: 有领地时庄园不再占位, 领地阶段照常出现在历任里 —
            #  陆氏 869 受任阶州此前被 x_nf_ 庄园挤掉, 历任只剩一行)
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
        依 title history (精确) + realm_history (兜底)。
        v24: 阶段行用游戏口径统治者称呼 — 营地「东邪吸毒头目（无地冒险者营地）」、
        领地「撒丁尼亚王 / 撒丁王 / 贝州侯」(文化词族×层级×政体), 不再写「任X之主」。
        返回 ['1200年10月18日任东邪吸毒头目（无地冒险者营地）', ...]"""
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
            parts = []
            for t in ids:
                key = (self._lt.get(str(t)) or {}).get("key") or ""
                if key.startswith("x_"):
                    # v24: 营地阶段用游戏口径 (营地宗旨词: 头目/领袖/队长…);
                    # 词取不到时回退旧式「X之主」防失名。
                    # v26: 游牧毡帐 (x_c_nomad_*) 不给冒险者宗旨词, 只写毡帐名。
                    # v28: 家族庄园 (x_nf_*) 是家业而非无地营帐, 用持有者词
                    # (乡绅/当主/户长) 并标注庄园类别。
                    nm = self._name_in_span(t, d, end, cid) or ""
                    if self._is_nomad_camp(t):
                        parts.append(nm)
                        continue
                    if self._is_estate_title(t):
                        ew = self.estate_kind_word(t, cid)
                        w = self._estate_holder_word(cid)
                        base = f"{nm}{w}" if nm and w else (nm or "")
                        parts.append(f"{base}（{ew}）" if base else "")
                        continue
                    w = self._camp_holder_word(cid, d)
                    base = f"{nm}{w}" if nm and w else (f"{nm}之主" if nm else "")
                    parts.append(f"{base}（无地冒险者营地）" if base else "")
                else:
                    # v24: 领地阶段用「头衔地名+统治者称呼词」(游戏口径,
                    # 文化/政体感知: 撒丁尼亚王/撒丁王/贝州侯…), 不再用「X之主」。
                    mid = self._span_mid(d, end)
                    nm = self._name_at_date(t, mid) or self.title_base_name(t)
                    w = self._ruler_word_at(cid, t, d)
                    parts.append(f"{nm}{w}" if nm and w else (f"{nm}之主" if nm else ""))
            parts = [p for p in parts if p]
            if not parts:
                continue
            line = f"{self.date(d)}任{'／'.join(parts)}"
            # 真正失去 (不在持有集) 且此前在组内的头衔
            lost_names = []
            for t in prev_ids:
                if t in ids or t not in lost_now:
                    continue
                lt = loss_types.get((t, cl.date_key(d)))
                nm = self._title_name_at(t, d, cid)
                if not nm:
                    continue
                # v28: 失去缘由按 title history 事件类型出词 (卸任/调任/被褫夺/
                # 失守/转授…), 未知回退旧词「让出」; 毁弃单列。
                verb = "毁弃" if lt == "destroyed" \
                    else TITLE_LOSS_VERBS.get(lt or "", "让出")
                lost_names.append(f"{verb}{nm}")
            prev_ids = ids
            if lost_names:
                line += "（" + "、".join(lost_names) + "）"
            out.append(line)
        return out

    def _span_mid(self, start, end):
        """区间中点日期 (v24, 供阶段稳定命名复用 _name_in_span 的中点口径)。"""
        if start and end:
            try:
                sy = [int(x) for x in str(start).split(".")[:3]]
                ey = [int(x) for x in str(end).split(".")[:3]]
                if len(sy) == 3 and len(ey) == 3:
                    return ".".join(str((a + b) // 2) for a, b in zip(sy, ey))
            except Exception:
                pass
        return start

    def _ruler_word_at(self, cid, tid, date):
        """领地阶段统治者称呼词 (v24): 依 (文化词族 × 层级 × 政体 × 独立 × 性别)
        取游戏口径词 — 与 official_title 同源, 供历任阶段行使用。"""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        tier = ""
        for pfx, tv in L.TIER_KEY_OF_PREFIX.items():
            if key.startswith(pfx):
                tier = tv
                break
        if not tier:
            return ""
        gov = self._title_government(tid)
        female = self._is_female(cid)
        return self._office_word(tier, gov, independent=self._is_independent(cid),
                                 female=female, tid=tid, cid=cid)

    def _camp_purpose_at(self, cid, date=None):
        """角色在某日期的营地宗旨 (camp_purpose_brigands 等 → 'brigands'):
        现职营地 (缓存 landed 政体=landless) 读现行 laws; 过往阶段读
        cache.camp_purposes 位置史 (每次并入记录变化点); 未知返回 ''。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        ld = rec.get("landed") or {}
        if ld.get("government") == "landless_adventurer_government":
            for law in ld.get("laws") or []:
                if str(law).startswith("camp_purpose_"):
                    return str(law).split("_", 2)[2]
        hist = self.cache.get("camp_purposes") or []
        if not hist:
            return ""
        dk = cl.date_key(date) if date else None
        purpose = None
        for h in hist:
            if not h.get("date"):
                continue
            if dk is None or cl.date_key(h["date"]) <= dk:
                purpose = h.get("purpose")
        if purpose is None:
            purpose = (hist[0] or {}).get("purpose")
        return purpose or ""

    def _camp_holder_word(self, cid, date=None):
        """营地持有者称呼词 (v24): 依营地宗旨查游戏键
        (duke_landless_adventurer_camp_brigands=头目 / explorers=领袖 /
        mercenaries=队长…); 宗旨/词取不到返回 ''。"""
        purpose = self._camp_purpose_at(cid, date)
        if not purpose:
            return ""
        female = self._is_female(cid)
        key = f"{'duchess' if female else 'duke'}_landless_adventurer_camp_{purpose}"
        v = L.loc(self.table, key)
        if v and not v.startswith("$") and not v.startswith("["):
            return v
        return ""

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
    # v17: 日式律令制政体 (japan_administrative_government) 官职词 — 按游戏本地化键
    # (修复方案_汤利五问题.md 问题2: e_japan 日本帝国之主是关白, 非皇帝; 天皇另座)。
    _JAPAN_OFFICE_KEYS = {
        "empire":  "emperor_administrative_male_japanese",   # 关白
        "kingdom": "king_administrative_male_japanese",      # 帅
        "duchy":   "duke_administrative_male_japanese",      # 国司
        "county":  "count_administrative_male_japanese",     # 国司
        "barony":  "baron_administrative_male_japanese",     # 郡司
    }
    _TENNO_TITLE_KEYS = {"k_chrysanthemum_throne"}  # 天皇座持有人 → 天皇

    def title_base_name(self, tid):
        """头衔基础名 (不含层级词/官职词): 动态名 → custom → name → 本地化 → key。"""
        if tid is None:
            return ""
        specific = self._specific_name(tid)
        if specific:
            return specific
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

    def _is_female(self, cid):
        """性别 (v26): 缓存持久化的 female 优先 (跨熔件剪除仍可判定),
        旧缓存无该字段时回退熔件全量角色索引。cid 非法返回 False。"""
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return False
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        v = rec.get("female")
        if v is not None:
            return bool(v)
        return bool((self._chars.get(str(cid)) or {}).get("female"))

    def _office_word(self, tier, government, independent=False, female=False, tid=None,
                     cid=None):
        """官职词: (层级, 政体) → 词。天朝/行政/草原行政共用同一套 (刺史/节度使/
        观察使/宣抚使…), 与文化无关 (实测: 诺斯伯爵在中国亦为刺史)。
        独立天朝制统治者用独立词 (皇帝/王/节度使), 不用封臣官职词。
        v14: 独立天朝制改为查游戏真实键 (dlc_tgp_cultural_titles):
          hegemon=hegemon_celestial_male_chinese(皇帝), empire=emperor_..._independent(皇帝),
          kingdom=king_male_chinese(王)/king_female_chinese(女王),
          duchy=duke_male_chinese_independent(节度使), county=count_independent_male_feudal_chinese(将军)。
        旧逻辑查 king_celestial_male_chinese_independent — 游戏本地化表中不存在,
        回退到通用 king「国王」→ 渲染成「粤国王」, 与游戏「桂王/粤王」口径不符 (修复方案_菲利普2.md 问题3)。
        v17: 日式律令制政体 (japan_administrative_government) 单独分支 — 查游戏键
        帝国=关白/王国=帅/郡县=国司/堡=郡司 (修复方案_汤利五问题.md 问题2);
        tid 传入时, 天皇座 (k_chrysanthemum_throne) 持有人直称「天皇」。"""
        gov = government or ""
        if gov == "japan_administrative_government":
            key = self._JAPAN_OFFICE_KEYS.get(tier)
            if tid is not None and \
                    (self._lt.get(str(tid)) or {}).get("key") in self._TENNO_TITLE_KEYS:
                key = "king_tenno_male_japanese"
            if key:
                v = L.loc(self.table, key)
                if v and not v.startswith("$") and not v.startswith("["):
                    return v
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
        # v26: 游牧/牧民/部落政体官职词 (游戏 flavorization 口径):
        #   ① <tier>_nomad_{male|female}_<heritage> (突厥: 叶护/颉利发…)
        #   ② <tier>_tribal_{male|female} (count_tribal_male=酋长 / duke_tribal_male=大酋长)
        #   ③ <tier>_herder_{male|female} (count_herder_male=牧主)
        # 游戏里 nomad_government 的封臣官职词命中 count_tribal_male (priority 16);
        # 非突厥文化无 count_nomad_male 键 — 此前回退 count_feudal_male=伯爵,
        # 田所2 主角因而被写成「也勒克河伯爵」而非「可萨田所部酋长」。
        if gov in self._NOMAD_LIKE_GOVS:
            w = self._nomad_office_word(tier, gov, independent, female, cid)
            if w:
                return w
        # v24: 文化 title 词族 (汉人 → chinese: 王/公/侯/伯/将军…) — 封建/宗族等
        # 非天朝政体下游戏按文化称呼统治者 (实测: 汉人独立公爵/国王皆称「王」,
        # 存档信封 meta_player_name = 王，郭冬临), 此前回退通用 国王/公爵 与游戏不符。
        w = self._culture_office_word(cid, tier, independent, female)
        if w:
            return w
        prefix = re.sub(r"_government$", "", gov)
        for k in (f"{self._TIER_KEY[tier]}_{prefix}_male",
                  f"{self._TIER_KEY[tier]}_feudal_male"):
            v = L.loc(self.table, k)
            if v and not v.startswith("$") and not v.startswith("["):
                return v
        return L.GENERIC_TIER_ZH.get(tier, "")

    # v24: CK3 culture_titles 词族 (dlc_tgp_cultural_titles 的 chinese 族键;
    # 键名与游戏一致: king_male_chinese=王 / duke_independent_male_feudal_chinese=王 /
    # duke_male_feudal_chinese=公 / count_male_feudal_chinese=侯 /
    # count_independent_male_feudal_chinese=将军 / baron_male_feudal_chinese=伯)。
    _CULTURE_OFFICE_KEYS = {
        "hegemon": ("hegemon_male_chinese", None),
        "empire":  ("emperor_male_feudal_chinese", "emperor_female_feudal_chinese"),
        "kingdom": ("king_male_chinese", "king_female_chinese"),
        "duchy":   ("duke_independent_male_feudal_chinese",
                    "duke_independent_female_feudal_chinese"),
        "county":  ("count_independent_male_feudal_chinese",
                    "count_independent_female_feudal_chinese"),
        "barony":  ("baron_male_feudal_chinese", "baron_female_feudal_chinese"),
    }
    _CULTURE_OFFICE_KEYS_VASSAL = {
        "duchy":  ("duke_male_feudal_chinese", "duke_female_feudal_chinese"),
        "county": ("count_male_feudal_chinese", "count_female_feudal_chinese"),
    }

    def _culture_office_word(self, cid, tier, independent, female):
        """文化 title 词族查词; 仅当 cid 文化与词族映射命中时可用。"""
        if cid is None:
            return ""
        tpl = (self.culture_template(cid) or "").lower()
        fam = _CULTURE_TITLE_FAMILY.get(tpl)
        if fam != "chinese":
            return ""
        if tier == "hegemon":
            male, fem = self._CULTURE_OFFICE_KEYS[tier]
        elif independent:
            male, fem = self._CULTURE_OFFICE_KEYS.get(tier, (None, None))
        else:
            male, fem = (self._CULTURE_OFFICE_KEYS_VASSAL.get(tier)
                         or self._CULTURE_OFFICE_KEYS.get(tier, (None, None)))
        for k in (fem if female else male, male):
            if not k:
                continue
            v = L.loc(self.table, k)
            if v and not v.startswith("$") and not v.startswith("["):
                return v
        return ""

    # v26: 游牧/牧民/部落政体 (游戏 flavorization 里 governments 含 nomad_government 的族)
    _NOMAD_LIKE_GOVS = {"nomad_government", "herder_government",
                        "tribal_government", "wanua_government"}
    _NOMAD_TIER_KEY = {"hegemon": "emperor", "empire": "emperor",
                       "kingdom": "king", "duchy": "duke",
                       "county": "count", "barony": "baron"}

    def _heritage_of(self, cid):
        """文化支柱 heritage (heritage_turkic 等), 供游牧官职词按游戏优先级取词。"""
        if cid is None:
            return ""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        cul = rec.get("culture")
        if cul is None:
            cul = (self._chars.get(str(cid)) or {}).get("culture")
        if cul is None:
            return ""
        e = ((self.melt.get("culture_manager") or {}).get("cultures") or {}) \
            .get(str(cul)) or {}
        return (e.get("heritage") or "") if isinstance(e, dict) else ""

    def _nomad_office_word(self, tier, gov, independent, female, cid):
        """游牧/牧民/部落统治者称呼词 — 复现游戏 flavorization 取值顺序:
        ① 文化 heritage 专属游牧词 (突厥: count_nomad_male_turkish 等);
        ② 通用部落词 (<tier>_tribal_male: 酋长/大酋长/国王/至高王);
        ③ 牧民词 (<tier>_herder_male: 牧主)。
        取不到返回 '' (调用方回退后续逻辑)。"""
        g = "female" if female else "male"
        tkey = self._NOMAD_TIER_KEY.get(tier)
        if not tkey:
            return ""
        heritage = (self._heritage_of(cid) or "").replace("heritage_", "")
        cands = []
        if gov == "nomad_government" and heritage:
            if independent and tier == "kingdom":
                cands.append(f"duke_independent_nomad_{g}_{heritage}")
            cands.append(f"{tkey}_nomad_{g}_{heritage}")
        if gov == "herder_government":
            cands.append(f"{tkey}_herder_{g}")
        cands.append(f"{tkey}_tribal_{g}")
        for k in cands:
            v = L.loc(self.table, k)
            if v and not v.startswith("$") and not v.startswith("["):
                return v
        return ""

    def _anchor_date(self, cid, date=None):
        """官职/国号的日期锚点 (v25): 显式 date > 卒日 (已死且在传记窗口内) > as_of。
        死者取卒日 → 卒于唐则为「唐皇帝」(李漼 874.8.15 卒, h_china 875.6.25 才
        由崔氏改国号秦); 卒于 as_of 之后者视为在世, 取 as_of (窗口外国号不外泄)。"""
        if date:
            return date
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        dd = (rec.get("death") or {}).get("date")
        if dd and (not self.as_of or cl.date_key(dd) <= cl.date_key(self.as_of)):
            return dd
        return self.as_of

    def _last_title_place(self, cid, fkey="", date=None):
        """角色官职的地名 (dead_data.flavor 只有官职词无地名 — v13 补全用)。
        取值顺序: ① 与官职层级精确匹配的头衔 (关白=帝国级→日本; 国司=郡级→出云);
        ② 最高层级头衔; ③ 最近一次持有的头衔; ④ v14: 死者 dead_data.domain 的
        头衔名 (title history 被存档剪除时, dead_data 仍带死时辖地 — 蓝田县令)。
        v25: 国号取 date (默认卒日) 时点的名 — 死者按其卒时国号称呼, 不再一律
        取 as_of 现名 (修: 李漼卒于唐而被写作「秦皇帝」)。
        返回 '建宁'/'颍州'/'出云' 等; 无则 ''。"""
        anchor = self._anchor_date(cid, date)
        tier_want = None
        for pfx, rk in (("hegemon_", 6), ("emperor_", 5), ("king_", 4),
                        ("duke_", 3), ("count_", 2), ("baron_", 1)):
            if fkey and fkey.startswith(pfx):
                tier_want = rk
                break

        def _place_nm(tid):
            """头衔的 date (默认卒日) 时点国号 (v25: 死者按卒时国号)。"""
            if tid is None:
                return ""
            t = self._lt.get(str(tid)) or {}
            key = t.get("key") or ""
            if not key or key.startswith(("x_", "e_minister_")):
                return ""
            return self._name_at_date(tid, anchor) or self.title_base_name(tid)

        # v21: 同级多头衔的场合, 优先取「首要头衔」与死档 liege_title (游戏口径),
        # 不再按迭代序取第一个 — 嵬名仁孝同持 k_xia(夏) 与 k_hexi(河西) 时稳定得「夏」
        # (修复: 1179 年「河西宁令嵬名仁孝」应为游戏显示的「夏宁令」)。
        if tier_want is not None:
            _pt, ptid = self._primary_title_at(cid, as_of=anchor)
            if ptid is not None and \
                    self._TT_RANK.get((self._lt.get(str(ptid)) or {}).get("key", "")[:2], 0) == tier_want:
                nm = _place_nm(ptid)
                if nm:
                    return nm
            drec = (self.cache.get("characters") or {}).get(str(cid)) or {}
            ltid = (drec.get("death") or {}).get("liege_title")
            if ltid is not None and int(ltid) != ptid and \
                    self._TT_RANK.get((self._lt.get(str(ltid)) or {}).get("key", "")[:2], 0) == tier_want:
                nm = _place_nm(int(ltid))
                if nm:
                    return nm
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
                # v17: 地名取「当前」国号, 非上任日 (修复方案_汤利五问题.md 问题6
                # — 王言 886 年上任时国号关内, 角色窗显示当时/当前国号)。
                # v25: 「当前」锚点改为 anchor — 死者取卒日国号 (李漼卒于唐 → 唐皇帝)。
                nm = self._name_at_date(tid, anchor) or self.title_base_name(tid)
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

    def official_title(self, cid, date=None):
        """角色官职名: 「头衔名+官职词」(交州刺史/淄青节度使/青徐路观察使)。
        已死角色优先读存档 dead_data.flavor (游戏算好的键, 最准)。
        v13: flavor 只有官职词 (节度使/国司/关白) 无地名 — 用最后持有头衔的地名补全
        (颍州刺史/建宁节度使/出云国司), 与在世角色渲染一致。
        伊斯兰统治者特殊: 家族名+苏丹国/哈里发国 (复用 realm_name)。
        v15: 宗教领袖 (教宗) 优先 — 称谓直达, 不走「X国国王主教」神权词。
        v25: date 锚点 — 默认取卒日 (死者按其卒时国号称呼), 在世取 as_of;
        动态国号 (h_china 唐→秦) 据此按卒期正确落名。"""
        rhw = self.religious_head_word(cid)
        if rhw:
            return rhw
        anchor = self._anchor_date(cid, date)
        c = self._chars.get(str(cid)) or {}
        fkey = (c.get("dead_data") or {}).get("flavor")
        if fkey:
            v = L.loc(self.table, fkey)
            if v and not v.startswith("$") and not v.startswith("["):
                place = self._last_title_place(cid, fkey, date=anchor)
                if place and not v.startswith(place):
                    return f"{place}{v}"
                return v
        tier, tid = self._primary_title_at(cid, as_of=anchor)
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
        name = self._name_at_date(tid, anchor) or self.title_base_name(tid)
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        gov = (rec.get("landed") or {}).get("government") or ""
        if not gov:
            gov = (c.get("landed_data") or {}).get("government") or ""
        word = self._office_word(tier, gov, independent=self._is_independent(cid),
                                 female=self._is_female(cid),
                                 tid=tid, cid=cid)
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
        "e_minister_chancellor": "minister_chancellor",    # 宰相 (政事堂)
    }
    # v28: 官职词候选链 (键缺失/未解析时的后备; 见 _minister_office)
    _MINISTER_OFFICE_FALLBACKS = {
        "minister_revenue": ("councillor_steward_celestial_government_imperial",),
        "minister_rites": ("councillor_court_chaplain_celestial_government_imperial",),
        "minister_censor": ("minister_censor_male",),
        "minister_grand_marshal": ("minister_grand_marshal_male",),
        "minister_chancellor": ("minister_chancellor_male",),
    }

    # v14: 恩怨史事件两端角色重渲染 (修复方案_菲利普2.md 问题3) —
    # change_reason 里游戏只写「国王/王」无国号, 渲染层有头衔能力却绕过了它。
    # 按事件日期查两端角色头衔: 主角侧「瑞典国王崔佛」, 对方侧「粤王范承宗」。
    def _feud_role_title(self, cid, date):
        """事件中某角色的「头衔名+名」: 按事件日期查首要头衔 (国号随年份:
        903 是粤、更早是桂), 无头衔/查不到时回退纯名; v15: 教宗直称「教宗」;
        v17: 名带世系编号 (同名前任 ≥1 时, 奇普里安II)。"""
        rhw = self.religious_head_word(cid)
        if rhw:
            return rhw + self.name_or(cid)
        tier, tid = self._primary_title_at(cid, as_of=date)
        name = self.name_with_regnal(cid, date)
        if tid is None or tier is None:
            return name
        tname = self._name_at_date(tid, date) or self.title_base_name(tid)
        if not tname:
            return name
        # 政体从头衔侧取 (角色 landed 在死者/时点会被清空, 头衔政体更稳)
        gov = self._title_government(tid)
        word = self._office_word(tier, gov, independent=self._is_independent(cid),
                                 female=self._is_female(cid),
                                 tid=tid, cid=cid)
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

    # ------------------------------------------------------------------
    # v27: 亲属标签 — 亲属/世系/妻族一律「头衔 + 姓名」
    # ------------------------------------------------------------------
    # 用户定稿 (2026-09-10): 只在**前头衔层级高于现头衔**时把前头衔前置,
    # 形态「前拜占庭皇帝，安卡拉伯爵君士坦丁十一」; 现头衔缺失时只写
    # 「前高昌国王毗伽庞特勤」。同一头衔 (同一 tid) 的今昔两种叫法不算前头衔 —
    # 塔坦尼·布兰 现职「可萨布兰部可敦」, 其 881–893 年的 3981 就是同一头衔的
    # 前身, 一律只写现职, 不前置「前可萨布兰部至高女王」。

    # v27: 非领地头衔 (朝廷职司 e_minister_* / 无地营地与庄园 x_*) —
    # 既不作王子公主称号的前缀 (修「兵部国皇女」), 也不算「前头衔」。
    _NON_LANDED_KEY_PREFIXES = ("e_minister_", "x_")

    def _is_landed_title(self, tid):
        """该头衔是否为领地头衔 (h_/e_/k_/d_/c_/b_, 且非职司/营地/庄园)。"""
        if tid is None:
            return False
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        if not key:
            return False
        if any(key.startswith(p) for p in self._NON_LANDED_KEY_PREFIXES):
            return False
        return key[:2] in ("h_", "e_", "k_", "d_", "c_", "b_")

    def _current_title_tid(self, cid, date=None):
        """角色现职对应的头衔 tid (用于与前头衔比层级)。
        现职优先取 `_primary_title_at`; 死者/失位者回退到最近一段最高位持有
        (官方称谓可能来自 dead_data.flavor, 但层级以此判定)。"""
        _tier, tid = self._primary_title_at(cid, as_of=date)
        if tid is not None:
            return tid
        return self._last_high_title_before(cid, date)

    def _former_high_title(self, cid, date=None, exclude_tid=None):
        """前头衔: 除现职外层级最高的已失头衔 tid; 无则 None。
        只认领地头衔 (h_/e_/k_/d_/c_/b_), 营地/庄园/职司不计入「前头衔」。"""
        best_tid, best_rank, best_gain = None, 0, None
        for tid, ivs in self._hold_intervals(cid, date).items():
            if exclude_tid is not None and tid == exclude_tid:
                continue
            if not self._is_landed_title(tid):
                continue
            key = (self._lt.get(str(tid)) or {}).get("key") or ""
            rank = self._TT_RANK.get(key[:2], 0)
            if rank <= 0:
                continue
            for (g, _l, _lt) in ivs:
                if not g:
                    continue
                if rank > best_rank or (rank == best_rank
                                        and best_gain is not None
                                        and cl.date_key(g) > best_gain):
                    best_tid, best_rank, best_gain = tid, rank, cl.date_key(g)
                    break
        return best_tid

    def _former_title_text(self, cid, tid, date=None):
        """前头衔中文文本 — 与 held_titles (v24) 同口径: 取任期区间中点的
        头衔地名 + 文化/政体感知的统治者称呼词 (「高昌」+「国王」= 高昌国王),
        不用 title_history_names 的显示名 (那是「高昌王国」, 会叠成
        「高昌王国国王」)。"""
        if tid is None:
            return ""
        gain = None
        for (g, _l, _lt) in (self._hold_intervals(cid, date).get(tid) or []):
            gain = g
            break
        end = date or self.as_of
        mid = self._span_mid(gain, end)
        nm = self._name_at_date(tid, mid) or self._name_at_date(
            tid, end) or self.title_base_name(tid)
        w = self._ruler_word_at(cid, tid, gain)
        if nm and w and not nm.endswith(w):
            return f"{nm}{w}"
        return nm

    def kin_label(self, cid, date=None):
        """亲属/世系/妻族专用称谓 (v27): 「[前X，]现职Y 姓名」。
        ① 宗教领袖 → 「教宗X」;
        ② 现头衔 (official_title, 含死者 dead_data.flavor) → 「可萨布兰部可敦塔坦尼·布兰」;
        ③ 前头衔层级 > 现头衔层级 → 「前拜占庭皇帝，安卡拉伯爵君士坦丁十一」;
        ④ 无头衔者 → 父/母头衔 ≥ 王国时取王子/公主称号 → 「楚国郡主苗映娘」;
        ⑤ 其余 → 统一显示名 (含绰号/世系编号/天皇座称号)。
        长名 (天皇座子女已把称号并入姓名) 不再叠前缀。"""
        nm = self.name_with_regnal(cid, date)
        if not nm:
            return ""
        # 天皇座子女的称号已并入姓名, 不叠任何前缀
        if self._tenno_prince_word(cid, date):
            return nm
        rhw = self.religious_head_word(cid)
        if rhw:
            return f"{rhw}{nm}"
        cur = self.official_title(cid, date)
        # 现职为空时不存在「现头衔」, 不能把「最近一段最高位持有」当成现职排除掉
        # (否则 毗伽庞特勤 的 高昌 会被自己挤掉, 只剩更低的 喀喇沙尔公国)。
        cur_tid = None
        if cur:
            cur_tid = self._current_title_tid(cid, date)
        cur_rank = 0
        if cur_tid is not None:
            key = (self._lt.get(str(cur_tid)) or {}).get("key") or ""
            cur_rank = self._TT_RANK.get(key[:2], 0)
        former_tid = self._former_high_title(cid, date, exclude_tid=cur_tid)
        f_rank = 0
        if former_tid is not None:
            key = (self._lt.get(str(former_tid)) or {}).get("key") or ""
            f_rank = self._TT_RANK.get(key[:2], 0)
        if cur and former_tid is not None and f_rank > cur_rank:
            ft = self._former_title_text(cid, former_tid, date)
            if ft and ft != cur:
                return f"前{ft}，{cur}{nm}"
            return f"{cur}{nm}"
        if cur:
            return f"{cur}{nm}"
        if former_tid is not None:
            ft = self._former_title_text(cid, former_tid, date)
            if ft:
                return f"前{ft}{nm}"
        pw = self.prince_title(cid, date)
        if pw:
            return f"{pw}{nm}"
        return nm


    def _minister_office(self, tid):
        """e_minister_* 头衔的职司官职词; 非职司头衔返回 ''。
        v28: 本地化键按**候选链**取 — 实测 minister_revenue/minister_rites 不在
        本地化表里 (户部/礼部此前取不到官职词), 游戏显示这两个职司用的是
        天朝制御前会议职位键 (councillor_steward/court_chaplain_..._imperial)。"""
        if tid is None:
            return ""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        if not key.startswith("e_minister_"):
            return ""
        loc_key = self._MINISTER_OFFICE_KEYS.get(key)
        cands = []
        if loc_key:
            cands.append(loc_key)
            cands.extend(self._MINISTER_OFFICE_FALLBACKS.get(loc_key, ()))
        for c in cands:
            v = L.loc(self.table, c)
            # 拒收未解析的引用 ($X$ / [X]) 与英文兜底 (纯 ASCII 词)
            if v and not v.startswith("$") and not v.startswith("[") \
                    and not re.search(r"[A-Za-z]{2,}", v):
                return v
        return self.title_base_name(tid) or "尚书"

    # v13: 无地家族/庄园头衔 (x_nf_*) 持有者的官职词, 按文化模板选
    # (游戏本地化键: 日本 当主/女士, 高丽系 户长/夫人, 其余 乡绅/夫人)
    _KOREAN_ESTATE_TPL = {"korean", "silla", "goryeo", "baekje",
                          "goguryeo", "balhae", "khitan"}

    def _estate_holder_word(self, cid):
        female = self._is_female(cid)
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

    def holder_at(self, tid, date=None):
        """头衔在 date 的持有者 id (title history 最后一条 ≤ date 的持有人;
        无记录/已毁弃返回 None)。date 为 None 时取熔件当前 holder。"""
        if tid is None:
            return None
        if date is None:
            h = (self._lt.get(str(tid)) or {}).get("holder")
            return int(h) if isinstance(h, int) else None
        seq = self._title_seqs.get(int(tid)) or []
        if not seq:
            return self.holder_at(tid)
        dk = cl.date_key(date)
        holder = None
        for d, ev in seq:
            if cl.date_key(d) > dk:
                break
            entries = ev if isinstance(ev, list) else [ev]
            for e in entries:
                if isinstance(e, dict):
                    h, typ = e.get("holder"), e.get("type") or ""
                else:
                    h, typ = e, ""
                if typ == "destroyed":
                    holder = None
                    continue
                if h is None:
                    holder = None
                    continue
                try:
                    holder = int(h)
                except (TypeError, ValueError):
                    continue
        return holder

    def _current_ministers(self, date=None):
        """朝廷职司在 date (缺省熔件当前) 的持有者 →
        ['兵部尚书任清', …] (朝局风云录·朝廷职司用)。
        v28: 输出形态改为「官职词+人名」— 此前「兵部：任清（兵部尚书）」把
        「部名」与「官职词」写了两遍。官职词取不到时才退「部名：人名」。
        v28b: **按 as_of 取时任者** — 此前一律取熔件当前 holder, 十年传记会把
        后来的任命写进早期十年 (田所2 @878 写出 883 年才上任的宰相)。"""
        d = date if date is not None else self.as_of
        out = []
        for tid, t in self._lt.items():
            if not isinstance(t, dict):
                continue
            key = t.get("key") or ""
            if not key.startswith("e_minister_"):
                continue
            holder = self.holder_at(int(tid), d)
            if not isinstance(holder, int):
                continue
            nm = self.name_or(holder)
            off = self._minister_office(int(tid))
            # v14: 职司名取不到时用「某职司」, 不直出 e_minister_ key
            base = self.title_base_name(int(tid)) or "某职司"
            if off and off != base:
                out.append(f"{off}{nm}")
            else:
                out.append(f"{base}：{nm}")
        return out

    def minister_ids(self, date=None):
        """朝廷职司 (e_minister_*) 在 date 的持有者 id 列表 (要员隐事取材用)。"""
        d = date if date is not None else self.as_of
        out = []
        for tid, t in self._lt.items():
            if not isinstance(t, dict):
                continue
            if not (t.get("key") or "").startswith("e_minister_"):
                continue
            h = self.holder_at(int(tid), d)
            if isinstance(h, int) and h not in out:
                out.append(h)
        return out

    # ---- v28: 隐事 (secrets) ----

    def _secret_cut(self):
        """隐事的时点截断: as_of 优先, 缺省用缓存末档日期。"""
        return self.as_of or self.cache.get("last_date")

    def secrets_owned_by(self, cid, date=None):
        """某人在 date 时点握有的隐事记录列表 (按首见日期升序)。
        过滤: owner 相符 + first_seen ≤ date + 尚未消失 (lost_at > date)。"""
        if cid is None:
            return []
        cut = date or self._secret_cut()
        ck = cl.date_key(cut) if cut else None
        out = []
        for sid, rec in (self.cache.get("secrets_history") or {}).items():
            if not isinstance(rec, dict) or rec.get("owner") != cid:
                continue
            fs = rec.get("first_seen")
            if ck is not None and fs and cl.date_key(fs) > ck:
                continue
            la = rec.get("lost_at")
            if ck is not None and la and cl.date_key(la) <= ck:
                continue
            out.append(dict(rec, id=str(sid)))
        out.sort(key=lambda r: cl.date_key(r.get("first_seen") or "9999.9.9"))
        return out

    def secret_topic(self, rec):
        """隐事主题短语 (不含持有人): 「科举舞弊（涉及樊骥）」/「谋害叠溪寋」/「与阿足私通」;
        未收录类型回退游戏本地化类型名 (取不到返回 '')。"""
        if not isinstance(rec, dict):
            return ""
        tp = rec.get("type") or ""
        tgt = rec.get("target")
        tname = self.name_or(tgt, "") if isinstance(tgt, int) else ""
        tpl = SECRET_TOPICS.get(tp)
        if tpl:
            if "{target}" in tpl:
                if tname:
                    return tpl.format(target=tname)
                return SECRET_TOPICS_NO_TARGET.get(tp, "隐情")
            # 模板未用对象 (科举舞弊/挪用国库…) 但有对象时并写, 便于区分同类隐事
            return f"{tpl}（涉及{tname}）" if tname else tpl
        z = L.loc(self.table, tp) or ""
        if not z or re.search(r"[A-Za-z_]", z):
            return ""
        return f"{z}（涉及{tname}）" if tname else z

    def secret_sentence(self, rec, owner_label=None):
        """隐事记录 → 中文事实句: 「陆荣廷有隐事：科举舞弊（自873年见载）。」"""
        if not isinstance(rec, dict):
            return ""
        topic = self.secret_topic(rec)
        if not topic:
            return ""
        owner = owner_label if owner_label is not None \
            else self.name_or(rec.get("owner"))
        if not owner:
            return ""
        s = f"{owner}有隐事：{topic}"
        fs = rec.get("first_seen")
        if fs and not rec.get("first"):
            note = f"自{self._year_only(fs)}见载"
            # 主题自带括注时并入同一括号, 避免「（涉及X）（自Y年见载）」
            s = s[:-1] + f"；{note}）" if s.endswith("）") else s + f"（{note}）"
        return s + "。"

    def secret_known_line(self, rec):
        """该隐事的知情情形句: 「至今无人知晓」/「X、Y已知情（自Z年起）」;
        无外人知情返回空串 (由调用方决定是否写「无人知晓」)。"""
        owner = rec.get("owner")
        names = []
        for k in rec.get("known_by") or []:
            kid = k.get("id")
            if not isinstance(kid, int) or kid == owner:
                continue
            nm = self.name_or(kid, "")
            if not nm:
                continue
            frm = k.get("from")
            if frm and not k.get("first"):
                names.append(f"{nm}（自{self._year_only(frm)}起）")
            else:
                names.append(nm)
        if not names:
            return ""
        return "知情者：" + "、".join(names[:6]) + "。"

    def secrets_known_by(self, cid, date=None):
        """cid 知情、但主人不是他的隐事记录 (把柄维度)。"""
        cut = date or self._secret_cut()
        ck = cl.date_key(cut) if cut else None
        out = []
        for sid, rec in (self.cache.get("secrets_history") or {}).items():
            if not isinstance(rec, dict) or rec.get("owner") == cid:
                continue
            for k in rec.get("known_by") or []:
                if k.get("id") != cid:
                    continue
                fs = k.get("from")
                if ck is not None and fs and cl.date_key(fs) > ck:
                    continue
                out.append(dict(rec, id=str(sid)))
                break
        return out

    # v13: 戏剧性事实 — 短命帝国/皇朝在位 (≤30 日即失去/被毁)
    DRAMATIC_TENURE_DAYS = 30

    def dramatic_facts(self, pid):
        """高亮戏剧性事件 (v15): 短命皇朝 (h_/e_ 头衔 ≤30 日在位即失/被毁)。
        (v14 的主角级时间线转折点已并入【主角大事摘要】, 不再逐条重复;
        大奸大恶关系链由 _villain_chains 程序直算, 在 build_facts 并入。)
        返回 ['935年11月4日承袭周皇朝…', …]。"""
        out = []
        if pid is None:
            return out
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
                tname = self._title_name_at(tid, gain, pid)
                if not tname:
                    continue  # v14: 头衔名取不到时不直出 key
                verb = "被毁" if ltype == "destroyed" else "失去"
                out.append(f"{self.date(gain)}承袭{tname}，"
                           f"{self.date(loss)}{verb}，在位仅{span}日")
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
        key = ("princess_kingdom_feudal_chinese" if female
               else "prince_kingdom_feudal_chinese")
        # v16: 本地化表的封建王国之女是「郡主」(唐制亲王之女的东亚封号),
        # 西式王国/帝国之女在传记里一律写「公主」; 天朝制的 皇女/郡主/公女
        # 属刻意东亚风味, 不在覆盖之列
        v = _PRINCE_WORD_OVERRIDE.get(key) or L.loc(self.table, key)
        if v and not v.startswith("$") and not v.startswith("["):
            return v
        return "公主" if female else "王子"

    def _parents_of_cid(self, cid):
        """角色父母 id 列表 (缓存 family → 熔件 family_data 兜底)。"""
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
        return [int(x) for x in parents if isinstance(x, int) or str(x).isdigit()]

    def _tenno_prince_word(self, cid, date=None):
        """天皇座 (k_chrysanthemum_throne) 非统治者子女的称号词 → '亲王'/'内亲王';
        不适用返回 ''。v20: 现实/中文史传口径 — 天皇后代称「惟仁亲王/井上内亲王」,
        名在前、称号在后, 无「高御座」前缀 (高御座是御座名, 游戏模组虚构的家族式前缀)。"""
        try:
            tier0, _ = self._primary_title_at(cid, as_of=date)
            if tier0 is not None:
                return ""  # 自己已有头衔, 不适用
        except Exception:
            return ""
        for pid2 in self._parents_of_cid(cid):
            try:
                _t, ptid = self._primary_title_at(pid2, as_of=date)
            except Exception:
                continue
            if ptid is None:
                continue
            if (self._lt.get(str(ptid)) or {}).get("key") not in self._TENNO_TITLE_KEYS:
                continue
            female = self._is_female(cid)
            key = ("princess_tenno_female_japanese" if female
                   else "prince_tenno_male_japanese")
            w = L.loc(self.table, key)
            if not w or w.startswith("$") or w.startswith("["):
                return ""
            return w
        return ""

    def _tenno_prince_name(self, cid, date=None):
        """天皇座子女的完整名 '利永亲王'/'馨子内亲王' (名+称号, 不带宗族姓);
        无给定名/不适用返回 ''。"""
        word = self._tenno_prince_word(cid, date)
        if not word:
            return ""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        given = rec.get("name_zh") or ""
        if not given:
            c = self._chars.get(str(cid)) or {}
            given = cl.name_zh(c) or ""
        if not given:
            return ""
        return given + word

    def prince_title(self, cid, date=None):
        """王子/公主称号: 角色无头衔, 且父/母首要头衔层级 ∈ {王国,帝国,霸权}
        (王国/帝国/霸权统治者子女都用此模板)。前缀 = 父头衔名+层级词
        (独立天朝制王国=「国」, 如大理国王子; 封臣=「路」, 如青徐路公子;
        伊斯兰: 家族名+苏丹国/哈里发国) + 王子词。
        v20: 天皇座子女的称号已并入显示名 (name_with_regnal), 此处返回 '' 防重复。
        v21: date 参数 — 按指定日期 (死者死亡日) 计算父头衔, 供刺客列传等
        名单型数据使用 (王祦 → 高丽国皇子), 防 as_of 穿越。"""
        if self._tenno_prince_word(cid, date):
            return ""
        tier0, _ = self._primary_title_at(cid, as_of=date)
        if tier0 is not None:
            return ""  # 自己已有头衔, 不适用
        parents = self._parents_of_cid(cid)
        if not parents:
            return ""
        best = None  # (rank, ptier, parent_cid)
        for pid2 in parents:
            pid2 = int(pid2)
            t, _tid = self._primary_title_at(pid2, as_of=date)
            rank = {"hegemon": 6, "empire": 5, "kingdom": 4}.get(t, 0)
            if rank > 0 and self._is_landed_title(_tid):
                if best is None or rank > best[0]:
                    best = (rank, t, pid2)
        if best is None:
            return ""
        _rank, ptier, pparent = best
        _t, ptid = self._primary_title_at(pparent, as_of=date)
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
            pbase = self._name_at_date(ptid, date or self.as_of) or self.title_base_name(ptid)
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
        female = self._is_female(cid)
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
            # v14: 家族名取不到时回退宗族名, 再不济「某家族」— 不泄露家族 id
            _hname = cl.house_name_zh(self.melt, other[0]) or ""
            if not _hname:
                _did = cl.dynasty_id_of(self.melt, other[0])
                if _did is not None:
                    _hname = cl.dynasty_name_zh(self.melt, _did) or ""
            # v14: 关系档位本地化缺失时用自然词, 不直出 key
            _lvl = L.loc(self.table, lvl) or {
                "default_house_relation_level_feud": "世仇",
                "default_house_relation_level_rivalry": "敌对",
                "default_house_relation_level_quarrel": "争吵",
            }.get(lvl, "")
            if not _lvl:
                continue
            out.append({
                "house": _hname or "某家族",
                "level": _lvl,
                "events": [f"{self.date(d)}，{t}" for d, t in events],
            })
        out.sort(key=lambda x: len(x["events"]), reverse=True)
        return out

    # v13: 宝物志只收高稀珍奇; v21: 门槛改为游戏最高档 名望级 (illustrious) —
    # 存档与游戏定义均无「传奇级 (legendary)」档位, 原 (legendary,) 永远筛空,
    # 玩家偷来的宋御玺/帝国皇冠等 (illustrious) 进不了板块; 狩猎战利品类型
    # (毛皮/角/颅骨) 一律剔除 (即使高稀也是凑数); 最多 20 件防提示词膨胀。
    ARTIFACT_RARITY = ("illustrious",)
    ARTIFACT_FILLER_TYPES = {
        "animal_hide", "animal_hide_big", "animal_trinket",
        "animal_skull", "VIET_clutter",
    }
    ARTIFACT_MAX = 20

    def family_artifacts(self):
        """宝物志数据源: 高稀 (名望级起)、相关集持有、且被其他宗族持有过的宝物。
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
            name = a.get("name") or "一件宝物"  # v14: 无名宝物不泄露 id
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
                # v21: 窃得 (玩家/他人盗取) — actor=失主, recipient=得宝者
                elif t == "stolen" and actor and rec2:
                    entries.append(f"{d}，{rec2}自{actor}处窃得")
                elif t == "stolen" and actor:
                    entries.append(f"{d}，{actor}处宝物遭窃")
                elif t == "stolen":
                    entries.append(f"{d}，宝物遭窃")
                # v14: 未知流转类型不直出 key (元注释泄露), 略去
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

    def religious_head_word(self, cid):
        """宗教领袖称谓 (v15): 角色为其信仰的宗教领袖 (持有 faith.religious_head
        头衔, 如教宗国/教皇座) 时返回称谓 — 教宗; 否则 ''。
        修复「教宗国国王主教戈德弗鲁瓦」式错位: 教宗本人应称「教宗」,
        而非神权领主的通用官职词「国王主教」(该词只适用非领袖的神权君主)。
        只对持有宗教领袖头衔者生效, 不影响普通神权领主。"""
        fid = self._faith_id(cid)
        if fid is None:
            return ""
        faiths = (self.melt.get("religion") or {}).get("faiths") or {}
        fe = faiths.get(str(fid))
        if not isinstance(fe, dict):
            return ""
        rh = fe.get("religious_head")
        if not isinstance(rh, int) or rh == self._NO_RELIGIOUS_HEAD:
            return ""
        t = self._lt.get(str(rh)) or {}
        # 任职区间 (title history, 已按 as_of 截断 — 死者/前教宗亦算);
        # 当前持有者只在无 as_of 缺口时兜底 (十年传记不把后期继任教宗泄漏进早期)
        held_rh = rh in (self._hold_intervals(cid) or {})
        melt_date = (self.melt.get("date") or "")
        no_gap = not (self.as_of and cl.date_key(self.as_of) < cl.date_key(melt_date))
        if not held_rh and not (no_gap and isinstance(t, dict) and t.get("holder") == cid):
            return ""
        # 只处理教皇座类头衔 (k_papal_state / d_papacy); 其余宗教领袖
        # (哈里发等) 走既有 realm_name 动态国名路径, 不套用「教宗」。
        tkey = t.get("key") or ""
        if "papal" not in tkey and "papacy" not in tkey:
            return ""
        v = L.loc(self.table, "religiousheadname_pope")
        if v and not v.startswith("$") and not v.startswith("["):
            return v
        return ""

    # ---- v22: 处决方式 (近似复现 execute_prisoner_interaction 的 send_option) ----

    def execution_method(self, killer_id, victim_id, date=None):
        """处决方式: 依行刑者当时状态判定可用 send_option, 稳定伪随机取一。

        存档只存 death_execution, 不存方式; 此函数按游戏可用条件近似复现
        (行刑者状态取传记所用熔件/缓存 — 数据只有年度快照, 不做逐日重建):
          - 斩首: 东亚系文化 (asian heritage 支柱近似) 或 与受害者同信仰;
            文化完全未知时默认可用 (通用处决即斩首)。
          - 烧死: 非东亚系文化 (与斩首互斥方向)。
          - 做成神秘的肉: 无地冒险者政体 + 恐惧税天赋 (fear_tax_perk)。
          - 犬决: 雇有猎犬人 (kennelperson_camp_officer)。
          - 食人: cannibal 特质或 secret_cannibal (信仰教义参数无存档, 略)。
          - 献祭: 需信仰 human_sacrifice_active 教义 (无存档教义表, 暂不判定)。
        返回 (key, 中文短语); killer 缺失或状态不可用回退 ('', '') —
        调用方保持既有「被X处决」。"""
        if killer_id is None:
            return "", ""
        tpl = (self.culture_template(killer_id) or "").lower()
        asian = (not tpl) or tpl in _ASIAN_HERITAGE_TPL
        kf = self._faith_id(killer_id)
        same_faith = kf is not None and kf == self._faith_id(victim_id)
        avail = []
        if asian or same_faith:
            avail.append("beheaded")
        if not asian:
            avail.append("burned")
        # 做成神秘的肉: 无地冒险者 + 恐惧税天赋 (营地口粮系瞬态, 未入传记)
        c = self._chars.get(str(killer_id)) or {}
        gov = (self.cache.get("characters") or {}).get(str(killer_id), {}) \
            .get("landed") or {}
        gv = gov.get("government") or (c.get("landed_data") or {}).get("government") or ""
        if gv == "landless_adventurer_government" and \
                "fear_tax_perk" in ((c.get("alive_data") or {}).get("perk") or []):
            avail.append("provisions")
        # 犬决: 雇有猎犬人廷臣
        cpd = (self.melt.get("court_positions") or {}).get("database") or {}
        if any(isinstance(e, dict) and e.get("employer") == killer_id
               and e.get("court_position") == "kennelperson_camp_officer"
               for e in cpd.values()):
            avail.append("kennel")
        # 食人: cannibal 特质 (依 trait_history 按日期判定, 旧缓存看当前) 或秘密
        if self._has_trait_at(killer_id, "cannibal", date) or \
                self._has_secret(killer_id, "secret_cannibal"):
            avail.append("devour")
        if not avail:
            return "", ""
        avail.sort(key=lambda k: _EXECUTION_ORDER.get(k, 99))
        seed = int(hashlib.md5(
            f"exec::{killer_id}:{victim_id}:{date or ''}".encode("utf-8")
        ).hexdigest()[:12], 16)
        key = random.Random(seed).choice(avail)
        zh = dict(_EXECUTION_OPTIONS).get(key, "")
        return key, zh

    def assassination_method(self, killer_id, victim_id, date=None, reason_key=None):
        """暗杀死法 (v25): 泛化死因按池子取一具体手法, 稳定伪随机不漂移。

        可用门 (见 _METHOD_REASON_TAGS / _ASSASSINATION_GAME_KEYS /
        _ASSASSINATION_HISTORY):
          - 死因: 神秘死亡/失踪/谋杀/毒杀各自的允许标签集, 方法标签须为其子集;
          - 文化圈: 凶手或受害者属东亚系文化 (_ASIAN_HERITAGE_TPL) → 东方池,
            否则西方池; 标 any 者两池通用;
          - 幼童: 受害者卒时不足 8 岁只取幼童可用条目;
          - 高位: 宫廷政变/御座/凯旋道类仅受害者卒时为王国级及以上可用。
        返回 (键, 中文短语); 死因不在池内/池子为空时回 ('', '') — 调用方回退
        既有「被X谋杀」「消失无踪」。"""
        if killer_id is None or not reason_key:
            return "", ""
        tags = _METHOD_REASON_TAGS.get(reason_key)
        if not tags:
            return "", ""
        tpl_k = (self.culture_template(killer_id) or "").lower()
        tpl_v = (self.culture_template(victim_id) or "").lower()
        east = (tpl_k in _ASIAN_HERITAGE_TPL) or (tpl_v in _ASIAN_HERITAGE_TPL)
        sphere = "east" if east else "west"
        kname = self.name_or(killer_id, "某人")
        age = self._age_at_death(victim_id, date)
        child = age is not None and age < 8
        high = self._is_high_rank_at(victim_id, date)
        avail = []
        for loc_key, mtags, msphere, child_ok in _ASSASSINATION_GAME_KEYS:
            if not mtags <= tags or msphere not in ("any", sphere):
                continue
            if child and not child_ok:
                continue
            if loc_key in _METHOD_HIGH_RANK and not high:
                continue
            text = _render_killer_loc(self.table, loc_key, kname)
            if text:
                avail.append((loc_key, text))
        for mkey, tmpl, mtags, msphere, child_ok in _ASSASSINATION_HISTORY:
            if not mtags <= tags or msphere not in ("any", sphere):
                continue
            if child and not child_ok:
                continue
            avail.append((mkey, tmpl.format(k=kname)))
        if not avail:
            return "", ""
        seed = int(hashlib.md5(
            f"assassin::{killer_id}:{victim_id}:{date or ''}:{reason_key}"
            .encode("utf-8")
        ).hexdigest()[:12], 16)
        return random.Random(seed).choice(avail)

    def _age_at_death(self, cid, date=None):
        """角色卒时年龄 (整岁); 生卒缺一返回 None。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        c = self._chars.get(str(cid)) or {}
        birth = rec.get("birth") or c.get("birth")
        death = date or (rec.get("death") or {}).get("date") \
            or (c.get("dead_data") or {}).get("date")
        if not birth or not death:
            return None
        try:
            return int(str(death).split(".")[0]) - int(str(birth).split(".")[0])
        except Exception:
            return None

    def _is_high_rank_at(self, cid, date=None):
        """受害者卒时是否王国级 (k_) 及以上 — 宫廷政变/御座类手法用。"""
        try:
            tier, tid = self._primary_title_at(cid, as_of=date)
        except Exception:
            return False
        if tid is None:
            return False
        rank = self._TT_RANK.get((self._lt.get(str(tid)) or {}).get("key", "")[:2], 0)
        return rank >= 4

    def imprison_duration(self, cid, date=None):
        """卒时仍在狱中时的囚禁时长 (v26), 渲染「N年M个月」; 不足 1 年/已出狱/无记录
        返回 ''。数据源 = 受害者自身 imprisoned / released_from_prison_memory 记忆
        (主角侧 imprisoned_other 兜底); 取死亡日之前最后一次入狱, 其后有释放则不计。
        只到月: 游戏日期为日粒度, 囚禁时长按 (年,月) 差计算。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        if not date:
            date = (rec.get("death") or {}).get("date")
        if not date:
            return ""
        pid = self.cache.get("player_id")

        def _prison_mems(owner):
            ore = (self.cache.get("characters") or {}).get(str(owner)) or {}
            return ore.get("memories") or []

        ins, outs = [], []
        for m in _prison_mems(cid):
            t = m.get("type")
            d = m.get("creation_date")
            if not d:
                continue
            if t == "imprisoned":
                ins.append(d)
            elif t == "released_from_prison_memory":
                outs.append(d)
        if not ins and pid is not None:
            # 受害者记忆被剪除时, 用主角的「囚禁他人」记忆兜底
            for m in _prison_mems(pid):
                if m.get("type") != "imprisoned_other":
                    continue
                parts = m.get("participants") or {}
                if parts.get("imprisoned") == cid and m.get("creation_date"):
                    ins.append(m["creation_date"])
        if not ins:
            return ""
        dk = cl.date_key(str(date))
        start = None
        for d in sorted(ins, key=lambda x: cl.date_key(str(x))):
            if cl.date_key(str(d)) <= dk:
                start = d
        if not start:
            return ""
        if any(cl.date_key(str(o)) > cl.date_key(str(start))
               and cl.date_key(str(o)) <= dk for o in outs):
            return ""  # 死前已出狱
        try:
            y0, m0, d0 = (int(x) for x in str(start).split(".")[:3])
            y1, m1, d1 = (int(x) for x in str(date).split(".")[:3])
        except Exception:
            return ""
        months = (y1 - y0) * 12 + (m1 - m0)
        if d1 < d0:
            months -= 1
        if months < 12:
            return ""
        y, m = divmod(months, 12)
        return f"{y}年" + (f"{m}个月" if m else "")

    def death_clause(self, cid, date=None, reason=None, killer=None, imprison=False):
        """角色死因句 (含施事者): 处决走处决方式池, 暗杀类走暗杀死法池, 其余通用。
        date/reason/killer 显式传入时以传入为准 (受害者不在缓存时的熔件兜底用)。
        v26: imprison=True 时, 卒时已囚满一年者前置「囚禁N年后」— 处决/狱死
        的囚禁时长得以进入传记 (田所2: 库诺·阿恩施泰因囚禁 4 年 7 个月后处决)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        d = rec.get("death") or {}
        if reason is None:
            reason = d.get("reason")
        if killer is None:
            killer = d.get("killer")
        if date is None:
            date = d.get("date")
        out = ""
        if killer is None:
            out = _death_clause(self.table, reason, None, lambda k: "")
        else:
            kname = self.name_or(killer, "某人")
            if reason == "death_execution":
                _k, zh = self.execution_method(killer, cid, date)
                if zh:
                    out = f"被{kname}{zh}"
            if not out:
                _mkey, mzh = self.assassination_method(killer, cid, date, reason)
                if mzh:
                    out = mzh
            if not out:
                out = _death_clause(self.table, reason, killer,
                                    lambda k: self.name_or(k, "某人"))
        if imprison and out:
            dur = self.imprison_duration(cid, date)
            if dur:
                # 死因已含「…后」时改为后置「，囚禁X」, 避免「囚禁X后…后…」
                # 叠床架屋; 其余前置「囚禁X后」。
                if "后" in out:
                    out = f"{out}，囚禁{dur}"
                else:
                    out = f"囚禁{dur}后{out}"
        return out

    def _has_trait_at(self, cid, trait_key, date=None):
        """角色在某日期是否持指定特质: 缓存 trait_history 区间判定
        (from ≤ date < to), 无 history (旧缓存) 回退当前特质。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        th = rec.get("trait_history") or {}
        ivs = th.get(trait_key)
        dk = cl.date_key(date) if date else \
            (cl.date_key(self.as_of) if self.as_of else None)
        if ivs:
            for iv in ivs:
                frm, to = iv.get("from"), iv.get("to")
                if frm and dk is not None and cl.date_key(frm) > dk:
                    continue
                if to and dk is not None and cl.date_key(to) <= dk:
                    continue
                return True
            return False
        for t in rec.get("traits") or []:
            if isinstance(t, int) and 0 <= t < len(self._tl) \
                    and self._tl[t] == trait_key:
                return True
        return False

    def _has_secret(self, cid, secret_type):
        """角色是否持某秘密 (secret_cannibal 等): melt.secrets.secrets owner 命中。"""
        try:
            secs = (self.melt.get("secrets") or {}).get("secrets") or {}
            return any(isinstance(e, dict) and e.get("owner") == cid
                       and e.get("type") == secret_type for e in secs.values())
        except Exception:
            return False

    # ---- v16: 游戏自带的关系原因 (opinions.active_opinions) ----
    # 游戏为每对角色记录 scripted_relations.reason (如 rival_murderer =
    # 「X杀害了Y的亲近之人」), 本地化 542/542 全命中 — 直接读游戏数据,
    # 不再让模型自行揣度「为何结仇/结友」。
    _REL_REASON_KINDS = {
        "rival": ("became_rivals",), "grudge": ("became_grudge",),
        "nemesis": ("became_nemesis",),
        "friend": ("became_friends",), "best_friend": ("became_friends", "became_soulmates"),
        "soulmate": ("became_soulmates",), "blood_brother": ("became_blood_brother",),
        "lover": ("became_lovers", "had_sex"),
    }

    def _player_opinion_index(self):
        """opinions.active_opinions 惰性索引: {(owner, target): scripted_relations}。
        只收与主角有关的对, 一次扫描 (7 万对, <0.1s)。"""
        if self._opinion_index is not None:
            return self._opinion_index
        pid = self.cache.get("player_id")
        idx = {}
        if pid is not None:
            for o in (self.melt.get("opinions") or {}).get("active_opinions") or []:
                if not isinstance(o, dict):
                    continue
                ow, tg = o.get("owner"), o.get("target")
                if ow == pid or tg == pid:
                    sr = o.get("scripted_relations")
                    if isinstance(sr, dict):
                        idx[(ow, tg)] = sr
        self._opinion_index = idx
        return idx

    def _rel_mem_date(self, cid, mem_types):
        """主角↔cid 间某类关系的最早记忆日期 (≤ as_of), 用于游戏原因的时间门 —
        十年传记不把 as_of 之后才形成的关系泄漏进早期。"""
        cache = self.cache
        pid = self.cache.get("player_id")
        if pid is None:
            return None
        chars = cache.get("characters") or {}
        best = None
        ao = cl.date_key(self.as_of) if self.as_of else None
        for cid0, rec in ((pid, chars.get(str(pid)) or {}),
                          (cid, chars.get(str(cid)) or {})):
            for m in rec.get("memories") or []:
                if m.get("type") not in mem_types:
                    continue
                parts = m.get("participants") or {}
                if not any(isinstance(v, int) and v in (pid, cid) and v != cid0
                           for v in parts.values()):
                    continue
                d = m.get("creation_date")
                if not d:
                    continue
                if ao is not None and cl.date_key(d) > ao:
                    continue
                if best is None or cl.date_key(d) < cl.date_key(best):
                    best = d
        return best

    def relation_reasons(self, cid, kinds):
        """游戏自带的关系原因句 (v16): 主角↔cid 的 scripted_relations.reason
        → 本地化中文句 (角色名占位符已替换)。kinds: 关系类型集
        (rival/grudge/nemesis/friend/soulmate/...)。返回去重后的 [句]。
        时间门: 仅当该类型关系有 ≤ as_of 的记忆时才渲染 (防十年泄漏)。"""
        if cid == self.cache.get("player_id"):
            return []
        idx = self._player_opinion_index()
        pid = self.cache.get("player_id")
        out = []
        seen = set()
        for pair in ((cid, pid), (pid, cid)):
            sr = idx.get(pair)
            if not isinstance(sr, dict):
                continue
            for kind, v in sr.items():
                if kind not in kinds or not isinstance(v, dict):
                    continue
                reason = v.get("reason")
                if not reason:
                    continue
                mtypes = self._REL_REASON_KINDS.get(kind)
                if mtypes and not self._rel_mem_date(cid, mtypes):
                    continue  # 该关系在 as_of 前不存在 → 不渲染
                tpl = L.relation_templates().get(reason)
                if not tpl:
                    continue  # 旧版本地化表无模板 (名字槽已剥): 由程序因由/记忆句兜底
                extra = v.get("involved_character")
                if not isinstance(extra, int):
                    extra = None
                s = _sub_relation_loc(self, tpl, pair[0], pair[1], extra)
                s = s.strip("。") + "。" if s else ""
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
        return out

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
        或 {家族}帝国。非伊斯兰 / 非王国帝国级 / 家族名缺失返回 '' (走常规渲染)。
        v26: 游牧政体不适用 — nomad_government 用
        uses_culture_and_house_head_named_realms, 国名走「文化+宗族+部」动态头衔
        (用户指正: 游牧政体下没有伊斯兰统治者的特殊国名)。"""
        t = self._lt.get(str(tid)) or {}
        key = t.get("key") or ""
        holder = t.get("holder")
        if not key.startswith(("k_", "e_", "h_")) or not isinstance(holder, int):
            return ""
        if self._title_government(tid) == "nomad_government":
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
        v11: 缓存/熔件文化均缺失 (死后清空/存档版本无 culture 字段) 时依亲属链/语言反推。
        v28: **亲属链优先于语言反查** —— 同一语言常被多个文化共享 (language_tai 同时
        属 黎/傣/布僮/土家), 语言反查只能任取第一个, 会把「子女随父」的文化判错
        (实测陆裕光: 父布僮、母羌, 只通泰语 → 旧序取到黎人, 应为布僮人)。
        CK3 子女文化沿父系继承, 故顺序为 自身 → 父系线 → 同胞 → 宗族 → 母 → 语言。"""
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
        # v28: 亲属链 (cl._culture_template_of 内部末步即含语言反查) 先于纯语言反查。
        # 传 chars/memo 避免每次重建全角色索引 (同一次 build_facts 内复用)
        tpl = cl._culture_template_of(self.cache, cid, self.melt,
                                      chars=self._chars, memo=self._tpl_memo)
        if tpl:
            return tpl
        # 语言反查 (亲属链全空时的最后兜底): 角色已知语言 → culture_manager.language
        # → 文化模板; 多文化共享同一语言时优先有父名规则的模板
        # (如 language_norse → norse 而非 norman)。
        for lg in self._languages_of(cid):
            cands = self._lang_to_tpl.get(lg) or []
            if not cands:
                continue
            for tpl in cands:
                if tpl in _patronym_rules():
                    return tpl
            return cands[0]
        return None

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

    # ---- v27: 语言风味 (母语 / 兼通 / 言语异同) ----
    def _culture_language_id(self, cid):
        """角色所属文化的语言 id (language_japonic…); 文化缺失时由文化模板回推。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        cul = rec.get("culture")
        if cul is None:
            cul = (self._chars.get(str(cid)) or {}).get("culture")
        if cul is not None:
            e = ((self.melt.get("culture_manager") or {}).get("cultures") or {}) \
                .get(str(cul))
            if isinstance(e, dict) and e.get("language"):
                return str(e["language"])
        # 文化 id 被清空 (玩家/死者): 由文化模板反查语言
        tpl = self.culture_template(cid)
        if tpl:
            lg = self._tpl_to_lang.get(tpl)
            if lg:
                return str(lg)
        return ""

    def mother_language(self, cid):
        """母语 (本族语) 中文名: 文化 → language → 本地化; 未知返回 ''。
        CK3 的角色语言表必然含本族语, 其余为习得语言 (Royal Court 语言系统);
        文化完全不可考而角色只通一语时, 该语即其母语。"""
        lg = self._culture_language_id(cid)
        if lg:
            v = L.loc(self.table, f"{lg}_name") or L.loc(self.table, lg) or ""
            if v:
                return v
        langs = self.languages(cid)
        if len(langs) == 1:
            return langs[0]
        return ""

    def language_sentence(self, cid):
        """语言事实句 (v27): 「母语日琉语，兼通乌古尔语。」/
        「通日琉语、乌古尔语。」(母语不可考时); 无语言记录返回 ''。"""
        langs = self.languages(cid)
        if not langs:
            return ""
        ml = self.mother_language(cid)
        if ml and ml in langs:
            others = [x for x in langs if x != ml]
            if others:
                return f"母语{ml}，兼通{'、'.join(others)}。"
            return f"母语{ml}。"
        return f"通{'、'.join(langs)}。"

    def language_relation_line(self, a, b):
        """两人言语关系句 (v28): 程序直接给出「相通 / 须借通译」的结论,
        模型不必自行判断语言相同或不同。任一方无语言记录返回 ''。

        例: 「陆荣廷与陆裕光共通泰语，言语相通。」
            「亮通氐羌语，与陆荣廷（泰语、汉语）无共通语，交谈须借通译往来。」"""
        la = self.languages(a)
        lb = self.languages(b)
        if not la or not lb:
            return ""
        na = self.name_or(a)
        nb = self.name_or(b)
        if not na or not nb:
            return ""
        common = [x for x in la if x in lb]
        if common:
            return f"{na}与{nb}共通{'、'.join(common)}，言语相通。"
        return (f"{na}通{'、'.join(la)}，与{nb}（{'、'.join(lb)}）无共通语，"
                f"交谈须借通译或以手势、习语往来。")

    def language_relation_lines(self, cid):
        """主角与妻室/子女的言语关系句 (v28): 同语者并成一句, 无共通语者按
        语言分组各成一句; 无语言记录者不列。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fam = rec.get("family") or {}
        ids = list(dict.fromkeys(
            (fam.get("primary_spouse") or []) + (fam.get("spouse") or [])
            + (fam.get("child") or [])))
        pl = self.languages(cid)
        if not pl:
            return []
        na = self.name_or(cid)
        groups = {}   # (是否相通, 语言组) -> [id]
        for x in ids:
            try:
                x = int(x)
            except Exception:
                continue
            lx = self.languages(x)
            if not lx:
                continue
            common = tuple(sorted(set(pl) & set(lx)))
            key = ("same", common) if common else ("diff", tuple(lx))
            groups.setdefault(key, []).append(x)
        out = []
        for key, members in groups.items():
            names = "、".join(self.name_or(m) for m in members)
            if not names:
                continue
            if key[0] == "same":
                out.append(f"{na}与{names}共通{'、'.join(key[1])}，言语相通。")
            else:
                out.append(f"{na}通{'、'.join(pl)}，与{names}（{'、'.join(key[1])}）"
                           f"无共通语，交谈须借通译或以手势、习语往来。")
        return out[:4]

    def language_bridge_line(self, cid):
        """主角与妻室/子女的言语异同 (v27): 只列与主角无共通语者 —
        「家中言语：毗伽伊尔盖通共同突厥语。」; 无此情形返回 ''。
        v28: 保留为兼容出口; 提示词改用 language_relation_lines (含同语结论)。"""
        pl = set(self.languages(cid))
        if not pl:
            return ""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fam = rec.get("family") or {}
        ids = list(dict.fromkeys(
            (fam.get("primary_spouse") or []) + (fam.get("spouse") or [])
            + (fam.get("child") or [])))
        bits = []
        for x in ids:
            try:
                x = int(x)
            except Exception:
                continue
            lang = self.languages(x)
            if not lang or set(lang) & pl:
                continue
            nm = self.kin_label(x)
            bits.append(f"{nm}通{'、'.join(lang)}")
            if len(bits) >= 5:
                break
        if not bits:
            return ""
        return "家中言语：" + "；".join(bits) + "。"

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

    def _faith_name(self, fid):
        """信仰 id → 中文名 (未知返回 '')。"""
        if fid is None:
            return ""
        faiths = (self.melt.get("religion") or {}).get("faiths") or {}
        e = faiths.get(str(fid))
        if isinstance(e, str):  # v7: none 条目防护
            e = None
        ft = (e or {}).get("faith_type") or ""
        return L.loc(self.table, ft) or FAITH_TYPE_ZH.get(ft) or ""

    def faith(self, cid):
        """角色信仰 (v7 缓存优先): 同 culture, id → religion.faiths → 本地化。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fid = rec.get("faith")
        if fid is None:
            c = self._chars.get(str(cid)) or {}
            fid = c.get("faith")
        return self._faith_name(fid) or "信仰不详"

    def faith_history_lines(self, cid):
        """信仰履历 (v26): [{'from','faith'}] → ['法华宗（880–895年）',
        '艾什尔里派（自896年起）']。as_of 截断; 单条/无历史返回 []。
        日期只取年 (快照日一律 1月1日, 改信实际发生在上一档与下一档之间)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        hist = [h for h in (rec.get("faith_history") or []) if h.get("from")]
        if len(hist) < 2:
            return []
        ao = cl.date_key(self.as_of) if self.as_of else None
        rows = []
        for i, h in enumerate(hist):
            dk = cl.date_key(h["from"])
            if ao is not None and dk > ao:
                break
            nm = self._faith_name(h.get("faith"))
            if not nm:
                continue
            start = int(str(h["from"]).split(".")[0])
            if i + 1 < len(hist):
                end = int(str(hist[i + 1]["from"]).split(".")[0]) - 1
                rows.append(f"{nm}（{start}–{end}年）")
            else:
                rows.append(f"{nm}（自{start}年起）")
        return rows

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
        """特质履历 (v4): 每条 = 「<特质>（自X年起获得 / 自X年后消失…）」
        v11: as_of 截断 — 丢弃 as_of 之后才获得的区间。
        v24: 首见即具的区间 (first=True, 数据起点前已存在, 无获得起点) 不再
        渲染「至晚自X年起已具」— 该类特质仍在「为人」列表出现, 信息不丢。
        日期只保留年 (快照差分日期全是 1月1日, 日内粒度无意义)。"""
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
                if iv.get("first"):
                    continue  # v24: 首见即具 — 无信息量, 略去
                d_from = self._year_only(iv.get("from"))
                d_to = self._year_only(iv.get("to"))
                if iv.get("from") and not iv.get("to"):
                    spans.append(f"自{d_from}起获得")
                elif iv.get("from") and iv.get("to"):
                    spans.append(f"自{d_from}起获得，自{d_to}后消失")
                elif iv.get("to"):
                    spans.append(f"至{d_to}后消失")
            if spans:
                lines.append(f"{z}（{'；'.join(spans)}）")
        return lines

    @staticmethod
    def _year_only(d):
        """快照日期年化: '871.1.1' → '871年'。"""
        if not d:
            return ""
        s = str(d)
        return s.split(".")[0] + "年"

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
        """玩家营/廷内他人任职 (v7/v23): 返回 (最新任职行, 任免变化行)。

        语义: cache.court_positions 只收 employer==玩家 的条目 — 即玩家营地/
        宫廷中由**僚属担任**的岗位, **不是玩家自身的官职** (玩家自身官职走
        历任头衔/官职词)。v23: 最新任职按任职者聚合、主语前置 (「仲宣任丑角
        （自…任），又任盗贼大师（自…任）」), 防止模型把花名册读成主角履历
        (郭氏 bug: 「靖历任丑角…众人争相延揽」系由此错读 + 幻觉补全)。
        变化行 = 跨快照同职位更替 (主语已是任职者)。
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
        holder_roles = {}  # 任职者名 -> [角色句]; 保持花名册出现序
        order = []
        for p in latest:
            zh = L.loc(self.table, p.get("type")) or ""
            if not zh or zh == p.get("type"):
                continue
            emp = p.get("employee")
            nm = self._office_name(emp) if emp is not None else ""
            if not nm:
                continue
            hire = self.date(p.get("hire_date")) if p.get("hire_date") else ""
            roles = holder_roles.setdefault(nm, [])
            if not roles:
                order.append(nm)
            roles.append(f"{zh}（自{hire}任）" if hire else zh)
        latest_lines = []
        for nm in order:
            roles = holder_roles[nm]
            # v23: 主语=任职者; 同人多职用「又任」递进, 避免「职位：人名」式
            # 履历错觉 (那会诱导模型把岗位归给主角本人)。
            s = f"{nm}任{roles[0]}"
            for r in roles[1:]:
                s += f"，又任{r}"
            latest_lines.append(s)
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

    def _prov_entry(self, province):
        """省份映射条目: {"county": c_ key, "barony": b_ key} (v24; 兼容旧字符串)。"""
        if province is None:
            return {}
        v = self.provmap.get(int(province))
        if isinstance(v, dict):
            return v
        if isinstance(v, str) and v:
            return {"county": v, "barony": ""}
        return {}

    def county_at_province(self, province):
        """省份 id → 伯爵领头衔 id (经省份映射); 未知返回 None。"""
        key = self._prov_entry(province).get("county") or ""
        if not key:
            return None
        return self.title_by_key(key)

    def barony_at_province(self, province):
        """省份 id → 男爵领 (b_) 头衔 id (v24, 受害者所在地标注用); 未知返回 None。"""
        key = self._prov_entry(province).get("barony") or ""
        if not key:
            return None
        return self.title_by_key(key)

    def character_location_province(self, cid):
        c = self._chars.get(str(cid)) or {}
        loc = (c.get("alive_data") or {}).get("location") or {}
        return loc.get("location") if isinstance(loc, dict) else loc

    def victim_place(self, cid):
        """受害者所在地 (v24): 其死亡前后最近可知的男爵领名。
        取值: ① 时代熔件中仍存活 → alive_data.location (终传尾年死者属此);
        ② 缓存死亡记录 location_province (死亡写入时复制自 last_location);
        ③ 缓存 last_location。解析失败返回 '' — 调用方省略地点标注。"""
        prov = self.character_location_province(cid)
        if prov is None:
            rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
            prov = ((rec.get("death") or {}).get("location_province")
                    or (rec.get("last_location") or {}).get("province"))
        if prov is None:
            return ""
        bid = self.barony_at_province(prov)
        if bid is not None:
            nm = self.title_base_name(bid)
            if nm and not nm.startswith("b_"):
                return nm
        cid2 = self.county_at_province(prov)
        if cid2 is not None:
            nm = self.title_base_name(cid2)
            if nm and not nm.startswith("c_"):
                return nm
        return ""

    def player_station_at(self, date):
        """主角在 date (含) 前最后已知驻地伯爵领名 (v20, B1/B3):
        依 cache.player_locations 位置史 (只记变化点); 无 ≤date 记录时用最早
        一条; 无位置史/映射失败返回 ''。"""
        hist = self.cache.get("player_locations") or []
        if not hist:
            return ""
        dk = cl.date_key(date) if date else None
        prov = None
        for loc in hist:
            if not loc.get("date"):
                continue
            if dk is None or cl.date_key(loc["date"]) <= dk:
                prov = loc.get("province")
        if prov is None:
            prov = (hist[0] or {}).get("province")
        county = self.county_at_province(prov)
        if county is None:
            return ""
        return self.title(county) or ""


# ---------------------------------------------------------------------------
# 事实渲染
# ---------------------------------------------------------------------------

# v21: 刑虐记忆的酷刑类型 → 中文 (存档变量 flag=type 的值; 实测
# torture/castrated/castrated_beardless/blind, 游戏另有 disfigured/maim_arm/
# maim_leg — 一并覆盖, 防新酷刑选项漏渲染; 无标志或未知一律按「折磨」)。
_TORTURE_TORTURER = {
    "torture": "{owner}折磨{other}。",
    "castrated": "{owner}阉割了{other}。",
    "castrated_beardless": "{owner}阉割了{other}（自幼，终身无须）。",
    "blind": "{owner}致盲了{other}。",
    "blinded": "{owner}致盲了{other}。",
    "disfigured": "{owner}毁了{other}的容貌。",
    "maim_arm": "{owner}打断了{other}的手臂。",
    "maim_leg": "{owner}打断了{other}的腿。",
}
_TORTURE_VICTIM = {
    "torture": "{owner}受{other}折磨。",
    "castrated": "{owner}被{other}阉割。",
    "castrated_beardless": "{owner}被{other}阉割（自幼，终身无须）。",
    "blind": "{owner}被{other}致盲。",
    "blinded": "{owner}被{other}致盲。",
    "disfigured": "{owner}被{other}毁容。",
    "maim_arm": "{owner}被{other}打断手臂。",
    "maim_leg": "{owner}被{other}打断腿。",
}
_TORTURE_TORTURER_NO_OTHER = {
    "torture": "{owner}施刑于人。",
    "castrated": "{owner}施以阉刑。",
    "castrated_beardless": "{owner}施以阉刑（自幼）。",
    "blind": "{owner}施以剜目之刑。",
    "blinded": "{owner}施以剜目之刑。",
    "disfigured": "{owner}施以毁容之刑。",
    "maim_arm": "{owner}施以断臂之刑。",
    "maim_leg": "{owner}施以断腿之刑。",
}
_TORTURE_VICTIM_NO_OTHER = {
    "torture": "{owner}受刑。",
    "castrated": "{owner}被施以阉刑。",
    "castrated_beardless": "{owner}被施以阉刑（自幼）。",
    "blind": "{owner}被施以剜目之刑。",
    "blinded": "{owner}被施以剜目之刑。",
    "disfigured": "{owner}被施以毁容之刑。",
    "maim_arm": "{owner}被施以断臂之刑。",
    "maim_leg": "{owner}被施以断腿之刑。",
}


def _torture_kind(f, mem):
    """刑虐记忆的酷刑类型: 优先读缓存 vars.value (v21 起保留), 旧缓存无 value
    时回读熔件记忆库 (存档保留完整变量)。返回 'torture'/'castrated'/
    'castrated_beardless'/'blind'/'disfigured'/'maim_arm'/'maim_leg' 等; 无则 ''。"""
    for v in mem.get("vars") or []:
        if v.get("flag") == "type" and v.get("value"):
            return str(v["value"])
    try:
        db = (f.melt.get("character_memory_manager") or {}).get("database") or {}
        e = db.get(str(mem.get("id"))) or {}
        for var in (e.get("variables") or {}).get("data") or []:
            d = var.get("data") or {}
            if var.get("flag") == "type" and d.get("type") == "flag" and d.get("flag"):
                return str(d["flag"])
    except Exception:
        pass
    return ""


def _mem_sentence(f, owner_id, mem):
    """一条记忆 → 干净中文句。"""
    tpl = MEMORY_TEMPLATES.get(mem.get("type"))
    if not tpl:
        return None
    owner = f.name_with_regnal(owner_id, date=mem.get("creation_date"))
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
    other = (f.name_with_regnal(other_id, date=mem.get("creation_date"))
             if other_id is not None else "")
    # v26: 出生记忆按孩子性别换模板 — 女儿此前一律被写成「添子/得长子」
    # (田所2: 睦、立希均为女儿, 模型据「添子」写成儿子)。
    if mem.get("type") in ("child_born", "first_born", "twins_born"):
        if mem.get("type") == "twins_born":
            kids = [parts.get("child"), parts.get("child_2")]
            fems = [f._is_female(k) for k in kids if isinstance(k, int)]
            if fems and all(fems):
                tpl = MEMORY_TEMPLATES.get("twins_born_female") or tpl
            elif any(fems):
                tpl = MEMORY_TEMPLATES.get("twins_born_mixed") or tpl
        else:
            kid = parts.get("child")
            if isinstance(kid, int) and f._is_female(kid):
                tpl = MEMORY_TEMPLATES.get(mem.get("type") + "_female") or tpl
    # v21: 刑虐记忆按酷刑类型渲染 (阉割/致盲/毁容/断臂/断腿…, 含受害者名) —
    # 大事记/年表此前只写「施刑/受刑」, 具体酷刑事迹丢失 (王晧 1190 被阉)。
    if mem.get("type") in ("torturer_memory", "tortured_memory"):
        kind = _torture_kind(f, mem)
        table = (_TORTURE_TORTURER if mem.get("type") == "torturer_memory"
                 else _TORTURE_VICTIM)
        no_other = (_TORTURE_TORTURER_NO_OTHER if mem.get("type") == "torturer_memory"
                    else _TORTURE_VICTIM_NO_OTHER)
        tpl2 = (table.get(kind) or table.get("torture")) if other \
            else (no_other.get(kind) or no_other.get("torture"))
        return tpl2.format(owner=owner, other=other)
    title = ""
    title_tid = None
    if mem.get("type") in TITLE_VAR_TYPES:
        for v in mem.get("vars") or []:
            if v.get("flag") == "landed_title" and v.get("identity"):
                title_tid = v.get("identity")
                title = f.title(title_tid)
                break
    # v28: 头衔得失按 reason 出词 (受任/承袭/受封/攻取…; 卸任/失守/被褫夺…),
    # reason 缺失时回退旧模板 (登位，得X / 让出X)。
    if mem.get("type") in TITLE_VAR_TYPES and title:
        reason = ""
        for v in mem.get("vars") or []:
            if v.get("flag") == "reason":
                reason = str(v.get("value") or "")
                break
        if mem.get("type") == "ascended_throne_memory":
            verb = TITLE_GAIN_VERBS.get(reason)
            if verb:
                return f"{owner}{verb}{title}。"
        else:
            verb = TITLE_LOSS_VERBS.get(reason)
            if verb:
                return f"{owner}{verb}{title}。"
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
    名字间的逗号 (国王张格本), 防模型模仿出「囚X一」式怪句。
    v17: 修复方案_汤利五问题.md 问题1 — `[A-Z]+` 不匹配 LANDED_TITLE 的下划线
    (`TOOLTIP:LANDED_TITLE,13449` 残留), 且 `L; 名称` 链接标记剥不掉:
    `[A-Z]`→`[A-Z_]+`, 头衔链接块整体剥离, `L` 后允许 `;`。"""
    s = str(s or "").replace("\x15", "")
    # v17: 头衔链接块 (ONCLICK:TITLE,id TOOLTIP:LANDED_TITLE,id L; 名称) 整体剥离
    s = re.sub(r"ONCLICK:TITLE,\d+\s*TOOLTIP:[A-Z_]+,\d+\s*L[; ]?", "", s)
    s = re.sub(r"ONCLICK:[A-Z_]+,\d+\s*", "", s)
    s = re.sub(r"TOOLTIP:[A-Z_]+,\d+\s*", "", s)
    s = re.sub(r"L(?=[;\s])", "", s)   # v17: L 链接标记 (后随 ; 或空格)
    s = re.sub(r"; ", "", s)           # v17: L; 残留的分号分隔 (仅链接位产生)
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
    """角色死亡 → 干净中文句 (死因句含凶手/行刑者/对手嵌入)。
    v22: death_execution 且行刑者已知时, 处决方式按当时可用选项稳定伪随机
    (斩首/做成神秘的肉/犬决/烧死/食人/献祭) — 存档只记「处决」, 不再千篇一律。
    v24: 凶手为主角时附「（死于X）」(X = 受害者死前最近可知男爵领, 数据无则省略);
    弃用 v20 的「时主角驻X」(主角驻地 ≠ 案发地, 误导模型把刺杀安在主角驻地)。
    v25: 死因句统一走 Facts.death_clause — 暗杀类死因按死法池取具体手法。
    v26: imprison=True — 卒时已囚满一年者写「囚禁N年后…」(处决/狱死)。"""
    rec = (f.cache.get("characters") or {}).get(str(cid)) or {}
    d = rec.get("death") or {}
    if not d:
        return None
    name = f.name_with_regnal(cid, date=d.get("date"))
    killer = d.get("killer")
    # 施事者名字缺失时用「某人」 (比默认「一位人物」更像自然语言)
    clause = f.death_clause(cid, date=d.get("date"), imprison=True)
    s = f"{name}死于{f.date(d.get('date'))}，{clause}。"
    pid = f.cache.get("player_id")
    if pid is not None and killer == pid:
        vp = f.victim_place(cid)
        if vp:
            s = s.rstrip("。") + f"（死于{vp}）。"
    return s


# v14: 30 个戏剧性模块 — 十年小传按主题切片的事实组织 (研究_戏剧模块化.md)。
# 每个模块 = {模块名: memory type 集} (另有 4 个专题模块 短命皇朝/天下更替/
# 官职任免/死亡谢幕, 由专门渲染器驱动, 不在本表)。type→模块 为纯数据层映射。
MODULE_TABLE = {
    "起家发迹":   {"ascended_throne_memory"},
    "失位让土":   {"lost_title_memory"},
    "开战兴兵":   {"offensive_war", "defensive_war", "joined_allys_war"},
    "战和胜负":   {"battle_won_memory", "battle_lost_memory", "war_won", "war_lost"},
    "战死负伤":   {"witnessed_death_battle", "became_incapable_due_to_battle_concussion"},
    "人质质任":   {"hostage_created_hostage", "hostage_created_warden", "hostage_created_home_court"},
    "囚禁入狱":   {"imprisoned", "imprisoned_other"},
    "获释出狱":   {"released_from_prison_memory"},
    "刑虐残暴":   {"tortured_memory", "torturer_memory"},
    "受辱含冤":   {"ignored_assault_memory"},
    "结仇结怨":   {"became_rivals", "became_grudge"},
    "死敌之仇":   {"became_nemesis"},
    "化仇解怨":   {"stopped_being_rivals"},
    "仇人死亡":   {"rival_died"},
    "结友知交":   {"became_friends"},
    "挚友血盟":   {"became_soulmates", "became_blood_brother"},
    "丧友之恸":   {"friend_died"},
    "婚配联姻":   {"married", "grand_wedding_completed_guest"},
    "情变私通":   {"became_lovers", "had_sex", "broke_up_lovers"},
    "丧偶之痛":   {"spouse_died"},
    "添丁进口":   {"child_born", "first_born", "twins_born"},
    "夭折":       {"child_premature", "child_stillborn"},
    "丧亲之恸":   {"relative_died"},
    "教化求学":   {"childhood_education_guardian", "childhood_education_no_guardian",
                   "ward_education_completed", "completed_rites_of_passage",
                   "completed_adult_education"},
    "科考功名":   {"passed_child_exam_memory", "failed_child_exam_memory",
                   "passed_provincial_exam_memory", "failed_provincial_exam_memory",
                   "passed_metropolitan_exam_memory", "passed_palace_exam_memory"},
    "拥戴加冕":   {"became_acclaimed", "witnessed_a_coronation_memory"},
    "信仰皈依":   {"completed_hajj_memory", "picked_serenity_aspect_memory",
                   "picked_creation_aspect_memory", "faith_changed"},
    # 死亡记录 (death) 不在此表: 由 _timeline 按死者关系并入 仇人死亡/丧友之恸/
    # 丧偶之痛/丧亲之恸 同键去重 (研究_戏剧模块化.md 模块 28)。
}
_TYPE2MODULE = {}
for _m, _ts in MODULE_TABLE.items():
    for _t in _ts:
        _TYPE2MODULE[_t] = _m


# v27: 板块 → 戏剧模块白名单 (研究_戏剧模块化.md 的切片方案落地)。
# 键 = (文章 key, 板块 key); 未列出的组合不收时间线 (该板块不看年表)。
# 目的: 让同一篇的开篇与纪事拿到**不相交**的素材 (此前 6 篇里 5 篇事实块
# 逐字节相同, 等于同一份料发两遍)。
MODULE_SLICE = {
    # 本纪: 开篇 = 家世/受学/婚姻/添丁; 纪事 = 权力线索 (起家/兵戈/刑狱/恩怨)
    ("benji", "lead"): {"教化求学", "科考功名", "人质质任", "婚配联姻",
                        "添丁进口", "信仰皈依", "拥戴加冕", "丧亲之恸",
                        "夭折", "情变私通"},
    ("benji", "mid"): {"起家发迹", "失位让土", "开战兴兵", "战和胜负",
                       "战死负伤", "囚禁入狱", "获释出狱", "刑虐残暴",
                       "受辱含冤", "拥戴加冕", "结仇结怨", "死敌之仇",
                       "化仇解怨"},
    # 家室: 开篇 = 结缡/情变/丧偶; 纪事 = 生育/夭亡/丧亲/丧友
    ("jiashi", "lead"): {"婚配联姻", "情变私通", "丧偶之痛"},
    ("jiashi", "mid"): {"添丁进口", "夭折", "丧亲之恸", "婚配联姻",
                        "情变私通", "丧友之恸"},
    # 朝局: 开篇 = 天下更替; 纪事 = 兵戈/刑狱/恩怨
    ("chaoju", "lead"): {"起家发迹", "失位让土", "拥戴加冕"},
    ("chaoju", "mid"): {"开战兴兵", "战和胜负", "战死负伤", "囚禁入狱",
                        "获释出狱", "结仇结怨", "死敌之仇", "拥戴加冕",
                        "丧亲之恸"},
    # 群英录纪事: 同朝局纪事口径
    ("qunying", "mid"): {"起家发迹", "失位让土", "开战兴兵", "战和胜负",
                         "囚禁入狱", "获释出狱", "结仇结怨", "死敌之仇",
                         "拥戴加冕"},
    # 列传: 开篇只给传主档案与关系缘由 (不配年表); 纪事给传主行迹 + 模块切片
    ("friend", "lead"): set(),
    ("friend", "mid"): {"结友知交", "挚友血盟", "丧友之恸", "结仇结怨"},
    ("enemy", "lead"): set(),
    ("enemy", "mid"): {"结仇结怨", "死敌之仇", "化仇解怨", "仇人死亡",
                       "情变私通", "结友知交"},
}

# v27: 板块排除模块 (用户决策 2026-09-10) — 本纪/朝局纪事不收「谋害人命」
# (终传里该模块占 71/117 条), 由《刺客列传》整块承载, 程序在板块内补一行索引。
MODULE_EXCLUDE = {
    ("benji", "mid"): {"谋害人命"},
    ("chaoju", "mid"): {"谋害人命"},
    ("qunying", "mid"): {"谋害人命"},
}


def slice_timeline(timeline, key, section_key, names=None, exclude=True):
    """按板块白名单切时间线 (v27), 返回事件文本列表。"""
    return [e["text"] for e in slice_events(timeline, key, section_key,
                                            names=names, exclude=exclude)]


def slice_events(timeline, key, section_key, names=None, exclude=True):
    """按板块白名单切时间线, 返回事件 dict 列表 (v27)。白名单 ∪ **未标注模块
    的事件** (未标注 = 合并时丢字段的历史事件, 一律保留, 保证零丢失)。
    未列入 MODULE_SLICE 的组合返回空 (该板块不以年表为素材)。
    exclude=False 时忽略 MODULE_EXCLUDE (例如剧本未生成《刺客列传》时,
    「谋害人命」必须留在本纪/朝局里, 否则这些事件无处可写)。"""
    mods = MODULE_SLICE.get((key, section_key))
    if mods is None:
        return []
    blocked = MODULE_EXCLUDE.get((key, section_key)) or set()
    # exclude=False 时把被排除的模块并回白名单 (剧本没有《刺客列传》时,
    # 「谋害人命」必须留在本纪/朝局里, 否则这些事件无处可写)
    effective = set(mods) if exclude else (set(mods) | set(blocked))
    out = []
    for e in timeline or []:
        mod = e.get("module") or ""
        if mod and mod not in effective:
            continue
        if names and not any(n and n in e.get("text", "") for n in names):
            continue
        out.append(e)
    return out


def murder_module_count(timeline):
    """时间线里「谋害人命」条数 (供板块索引行)。"""
    return sum(1 for e in (timeline or [])
               if (e.get("module") or "") == "谋害人命")



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
    # v15: 主角情人 (became_lovers/had_sex 参与者, 含已分手) — 情人的婚配/生育/亲属去世
    # 进时间线 (阿尔东萨与国王成婚、诞女、长女被谋杀后去世等, 大奸大恶戏剧的上下文)。
    for m in prec.get("memories") or []:
        if m.get("type") in ("became_lovers", "had_sex"):
            for v in (m.get("participants") or {}).values():
                if isinstance(v, int) and v != pid:
                    out.setdefault(v, 2)
    return out


# v14: death 记录 (类型 "death", 由 _death_sentence 渲染) 的模块标注 —
# 按死者与主角的关系: 仇人→仇人死亡, 友人→丧友之恸, 配偶→丧偶之痛, 其余→丧亲之恸。
def _death_module(f, dead_cid):
    """death 时间线事件归属的戏剧性模块 (按死者关系; v15: 主角所杀者→谋害人命)。"""
    pid = f.cache.get("player_id")
    if pid is None:
        return "丧亲之恸"
    d = ((f.cache.get("characters") or {}).get(str(dead_cid)) or {}).get("death") or {}
    if d.get("killer") == pid:
        return "谋害人命"
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
                    return "仇人死亡"
            if m.get("type") in ("became_friends", "became_soulmates", "became_blood_brother"):
                parts = m.get("participants") or {}
                if any(isinstance(v, int) and v == dead_cid for v in parts.values()) \
                        and any(isinstance(v, int) and v == pid for v in parts.values()):
                    return "丧友之恸"
    return "丧亲之恸"


def _ordinal_zh(n):
    """世系编号中文 (v17): 二世…九世带「世」, 十起不带 (路易十一/路易十四)。
    n ≥ 2 才调用。"""
    digits = "零一二三四五六七八九"
    if n < 10:
        return digits[n] + "世"
    if n < 20:
        return "十" + (digits[n - 10] if n > 10 else "")
    if n < 100:
        t, r = divmod(n, 10)
        return digits[t] + "十" + (digits[r] if r else "")
    return str(n)


def _decade_lower_bound(f):
    """十年传记窗口下界 (v17): as_of 年 − 10 的年初, 不早于缓存起始年。
    返回 'YYYY.1.1' 或 None。"""
    if not f.as_of:
        return None
    try:
        y = int(str(f.as_of).split(".")[0])
    except Exception:
        return None
    start = None
    srcs = f.cache.get("sources") or []
    if srcs:
        try:
            start = int(str(srcs[0]).split(".")[0])
        except Exception:
            start = None
    lo = max(y - 10, start or (y - 10))
    return f"{lo}.1.1"


def _year_summary(timeline, pname):
    """【主角大事摘要】按年聚合 (v17, 修复方案_汤利五问题.md 问题4):
    一年一行 — 同型事件 (谋杀/添子/添女) 合并人名 (≤3 全列 + 等N人),
    其余关键事件 (结怨/结仇/结友/私通/成婚/登位/去世/囚禁…) 去月日保留动词原句;
    出生年括注一律不写。timeline 已按 as_of/十年窗口截断。
    v26: 主语改用实际主角名 — 此前两条正则写死「麦克·汤利」, 其它主角的摘要
    退化成「添子色鬼田所浩二添子田所睦」「谋杀色鬼田所浩二谋杀X」; 出生按
    孩子性别分「添子/添女」。
    返回 [str] (每行 'NNNN年，…。')。"""
    by_year = {}
    for e in timeline or []:
        txt = e.get("text") or ""
        if pname and pname not in txt:
            continue
        d = str(e.get("date") or "")
        y = d.split(".")[0]
        if not y.isdigit():
            continue
        by_year.setdefault(int(y), []).append(e)
    if not by_year:
        return []
    pn = re.escape(pname or "")
    kill_re = re.compile(
        r"^" + pn + r"谋杀(.+?)(?:（\d+年生）)?(?:（死于([^）]*)）)?。$") if pn else None
    birth_re = re.compile(
        r"^" + pn + r"(得长女|得长子|添女|添子)(.+)。$") if pn else None
    lines = []
    for y in sorted(by_year):
        kills, births, rest = [], [], []
        for e in by_year[y]:
            body = e["text"]
            # v26: 1月1日日期已被 fmt_cn_date 折叠成「NNNN年，」, 需一并剥离
            b = re.sub(r"^\d+年\d+月\d+日，?", "", body)
            b = re.sub(r"^\d+年\d+月，?", "", b)
            b = re.sub(r"^\d+年，?", "", b)
            typ = e.get("type") or ""
            m = kill_re.match(b) if kill_re else None
            if typ == "successful_murder" or m:
                if m:
                    kills.append(m.group(1) + (f"（死于{m.group(2)}）"
                                               if m.group(2) else ""))
                else:
                    kills.append(b.rstrip("。"))
                continue
            if typ in ("child_born", "first_born", "twins_born"):
                m = birth_re.match(b) if birth_re else None
                if m:
                    verb = "添女" if "女" in m.group(1) else "添子"
                    births.append((verb, m.group(2)))
                else:
                    rest.append(b)  # 孪生等无名字模板: 原句保留
                continue
            rest.append(b)
        parts = []

        def _names(items, verb):
            if not items:
                return None
            if len(items) <= 3:
                return verb + "、".join(items)
            return verb + "、".join(items[:3]) + f"等{len(items)}人"

        s = _names(kills, "谋杀")
        if s:
            parts.append(s)
        for verb in ("添子", "添女"):
            s = _names([n for v, n in births if v == verb], verb)
            if s:
                parts.append(s)
        # 其余事件: 去句末句号, 由行末统一收句 (防「。；」连接)
        parts.extend(r.rstrip("。") for r in rest)
        body = "；".join(parts)
        lines.append(f"{y}年，{body}。")
    return lines


def _timeline(f):
    """主角相关时间线: 只收 宗族/父母妻儿/孙辈儿媳婿 相关事件 (口径见 _related_ids),
    按人按事去重, 按日期排序。
    每条 = {"date", "type", "text"} (text 为干净中文句, 提示词只用 text)。
    - 路人剔除: 记忆拥有者与参与者都不在相关集内的事件一律不收;
    - 死亡去重: 同一死者只留一条 (死亡记录 > 去世 > 丧偶), 消除「同一人不停地死」;
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
            # 死亡类记忆: 按死者 id 去重 (去世 > 丧偶)
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
            # v15: 主角的成功谋杀记忆 — 按死者 id 去重 (受害者死亡记录优先,
            # 谋杀记忆兜底; 只收主角所谋, 路人谋杀不渲染)
            if mtype == "successful_murder" and cid == pid:
                dead = parts.get("victim")
                if isinstance(dead, int):
                    s = _mem_sentence(f, cid, mem)
                    if s:
                        # v16: 死者出生年限定 — 区分同名/近名角色 (830年生的
                        # 里瓦朗 vs 869年生的里瓦尔, 一字之差模型易混)
                        # v28: 并写族属与信仰 — 存档里 dead_unprunable 一直保留
                        # (游戏中随时可读), 此前小传里完全没有这些信息。
                        drec = (cache.get("characters") or {}).get(str(dead)) or {}
                        by = str(drec.get("birth") or "").split(".")[0] or ""
                        cul = f.culture(dead)
                        fai = f.faith(dead)
                        mark = []
                        if by:
                            mark.append(f"{by}年生")
                        if cul and not cul.endswith("不详"):
                            mark.append(cul)
                        if fai and not fai.endswith("不详"):
                            mark.append(f"信{fai}")
                        if mark:
                            s = s.rstrip("。") + f"（{'，'.join(mark)}）。"
                        # v24: 依谋杀发生日标受害者死前最近可知所在 (男爵领名;
                        # 数据无则省略) — 击杀无案发地点, 以受害者位置为锚,
                        # 不再用主角驻地 (主角驻地 ≠ 案发地)。
                        vp = f.victim_place(dead)
                        if vp:
                            s = s.rstrip("。") + f"（死于{vp}）。"
                        old = deaths.get(dead)
                        if old is None or 2 > old[0]:
                            deaths[dead] = (2, mem.get("creation_date"),
                                            "successful_murder", s)
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
    # 合并 死亡记录 + 去世记忆 + 出生事件
    for cid, (_prio, _d, t, s) in deaths.items():
        # v14: death 记录按死者关系标模块 (仇人死亡/丧友之恸/丧偶之痛/丧亲之恸)
        events.append((_d, t, s, _death_module(f, cid)))
    for _prio, _d, t, s in births.values():
        events.append((_d, t, s, "添丁进口" if t in ("child_born", "first_born", "twins_born") else "夭折"))
    # v26: 改信事件 (游戏不留改信记忆 — 缓存逐档 faith 差分得来)。
    # 只给相关角色 (主角/直系); 首个变化点之前无事件, 从第 2 条起写。
    for cid, rec in (cache.get("characters") or {}).items():
        cid = int(cid)
        if cid not in related:
            continue
        for ch in (rec.get("faith_history") or [])[1:]:
            d = ch.get("from")
            if not d:
                continue
            nm = f.name_with_regnal(cid, date=d)
            fn = f._faith_name(ch.get("faith"))
            if nm and fn:
                events.append((d, "faith_changed", f"{nm}改信{fn}。", "信仰皈依"))
    # v11: as_of 截断 (十年传记只到十年末)
    if f.as_of:
        ao = cl.date_key(f.as_of)
        events = [e for e in events if e[0] and cl.date_key(e[0]) <= ao]
    # v17: 十年窗口 — 十年传记只收本十年 (as_of−10年, as_of], 摘要/本纪年表/
    # 概览统计/戏剧主题/朝局动态等一切以 timeline 为源的数据随之只含本十年
    # (修复方案_汤利五问题.md 决策 1/2; 戏剧性事件 villain_chains 自管 in_span 保持全期)。
    if f.decade and f.as_of:
        lo = _decade_lower_bound(f)
        if lo:
            lok = cl.date_key(lo)
            events = [e for e in events if e[0] and cl.date_key(e[0]) >= lok]
    events.sort(key=lambda x: cl.date_key(x[0]))
    # v15: 十年/一生概览统计 (聚合前原始事件, 程序直算 — 供【概览】块;
    # 只统计主角名在文本中的事件, 家人/路人的添丁结怨不入概览)
    pname0 = f.name_with_regnal(pid)  # v17: 与时间线文本同口径 (主角也可能带世系编号)
    stats = {}
    for _d, t, s, mod in events:
        if pname0 and pname0 not in s:
            continue
        label = _DEATH_STAT_LABEL.get(mod) if t == "death" else _STATS_LABEL.get(t)
        if label:
            stats[label] = stats.get(label, 0) + 1
    f._timeline_stats = stats
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
            # v27: 死亡句自带的日期已在句内 (「X死于YYYY年M月D日，…」),
            # 不再在句首重复一遍日期 (「893年4月28日，塔坦尼·布兰死于893年4月28日…」)
            "text": (s if (t == "death" or not d) else f"{f.date(d)}，{s}"),
        })
    # v11: 同日同型集体事件合并 (见证加冕/出席大婚/被囚/囚禁)
    out = _merge_same_day_events(out, f)
    # v15: 同月同型流水事件聚合 (结怨/结仇/助战…), 聚合后再限量
    out = _merge_same_month_events(out, f)
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
# 主角名在文本中 ×3 否则 ×1); v24: 取 Top5 (用户: 呈现 5 个左右), 与第 5 名
# 并列的模块全保留; 专题模块 (血脉登基等) 先并入再统一切口。
def decade_module_top(timeline, protagonist, top_n=5):
    """十年戏剧主题: [(模块名, 得分)] 按得分降序; 并列第5名全保留 (可能 >5)。
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
    # Top5 + 与第5名并列者
    cutoff = ranked[top_n - 1][1]
    return [r for r in ranked if r[1] >= cutoff]


def _cut_module_top(dm, top_n=5):
    """对 (模块, 得分) 列表重排并截到 Top5 (+与第5名并列), 供专题模块并入后统一收口。"""
    if not dm:
        return []
    ranked = sorted(dm, key=lambda x: -x[1])
    if len(ranked) <= top_n:
        return ranked
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
            # v27: 合并必须携带 module —— 此前只写 date/type/text, 合并后的
            # 事件模块为空, 模块切片会把「被囚」等集体事件整体漏掉。
            out.append({"date": d, "type": typ, "text": merged,
                        "module": entries[0].get("module", "")})
        else:
            out.extend(entries)
    return out


# v15: 概览统计标签 (记忆类型 → 中文标签; death 记录按模块另表)。
# 只统计有戏剧意义的类型, 供【概览】块程序直算「本十年结怨9次、谋杀5次…」。
_STATS_LABEL = {
    "became_rivals": "结仇", "became_grudge": "结怨", "became_nemesis": "结为死敌",
    "child_born": "添丁", "first_born": "添丁", "twins_born": "添丁",
    "child_premature": "夭折", "child_stillborn": "夭折",
    "successful_murder": "谋杀",
    "had_sex": "私通", "became_lovers": "私通",
    "relative_died": "丧亲", "spouse_died": "丧偶", "friend_died": "丧友",
    "rival_died": "仇人死亡",
    "married": "成婚", "broke_up_lovers": "分手",
    "imprisoned": "被囚", "imprisoned_other": "囚禁他人",
    "offensive_war": "开战", "defensive_war": "应战",
    "war_won": "获胜", "war_lost": "战败",
    "battle_won_memory": "胜仗", "battle_lost_memory": "败仗",
    "faith_changed": "改信",
}
_DEATH_STAT_LABEL = {
    "谋害人命": "谋杀", "丧亲之恸": "丧亲", "丧偶之痛": "丧偶",
    "丧友之恸": "丧友", "仇人死亡": "仇人死亡",
}

# v15: 同月同型流水事件聚合 — 只合并单槽可变、结构一致的流水 (结怨/结仇/助战等)。
# style: duo = 「A与B结怨。」双槽; solo = 「A助盟友作战。」单槽。
_AGG_SPEC = {
    "became_grudge":    {"pat": r"^(.+?)与(.+?)结怨。$",     "verb": "结怨",     "style": "duo"},
    "became_rivals":    {"pat": r"^(.+?)与(.+?)结仇。$",     "verb": "结仇",     "style": "duo"},
    "became_nemesis":   {"pat": r"^(.+?)与(.+?)结为死敌。$", "verb": "结为死敌", "style": "duo"},
    "became_friends":   {"pat": r"^(.+?)与(.+?)结为好友。$", "verb": "结为好友", "style": "duo"},
    "joined_allys_war": {"pat": r"^(.+?)助盟友作战。$",      "verb": "助盟友作战", "style": "solo"},
}

# v15: 「私情+相恋」成对合并 (同月同对象的 had_sex 与 became_lovers)
_PAIR_MERGE = {
    "had_sex":        r"^(.+?)与(.+?)有私情。$",
    "became_lovers":  r"^(.+?)与(.+?)相恋。$",
}


def _agg_line(ym, names, verb, tail):
    """聚合行: '870年4月，莱昂、昂盖朗、诺贝特三人先后与麦克·汤利结怨。'
    名字 ≤3 全列加人数词 (二人/三人), >3 收前三加「等N人」。"""
    if not names:
        return None
    y, _, m = ym.partition(".")
    cnt = ""
    if len(names) == 2:
        cnt = "二人"
    elif len(names) == 3:
        cnt = "三人"
    elif len(names) > 3:
        cnt = f"等{len(names)}人"
        names = names[:3]
    joined = "、".join(names) + cnt
    return f"{y}年{int(m)}月，{joined}{tail}{verb}。"


def _merge_same_month_events(events, f=None):
    """同月同型事件聚合 (v15): 「870年4月，莱昂、昂盖朗、诺贝特三人先后与
    麦克·汤利结怨。」— 把同一年月内结构一致、只差一个名字槽的流水事件并成一行,
    省词元并防模型逐条数日期; 关键事件 (婚/丧/子/仇/战) 保留精确日期不聚合。"""
    groups = {}
    order = []
    for e in events:
        d = e.get("date") or ""
        ym = ".".join(str(d).split(".")[:2]) if d else ""   # YYYY.MM
        if not ym:
            continue
        key = (e.get("type"), ym)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(e)
    out = []
    for key in order:
        entries = groups[key]
        typ, ym = key
        spec = _AGG_SPEC.get(typ)
        if spec and len(entries) >= 2:
            pat = spec["pat"]
            slots = []
            ok = True
            for e in entries:
                body = e["text"]
                d0 = e.get("date")
                if d0 and f:
                    prefix = f"{f.date(d0)}，"
                    if body.startswith(prefix):
                        body = body[len(prefix):]
                m = re.match(pat, body)
                if not m:
                    ok = False
                    break
                slots.append(m.groups())
            if ok:
                merged = None
                if spec["style"] == "solo":
                    merged = _agg_line(ym, [s[0] for s in slots],
                                       spec["verb"], "")
                else:
                    s0 = [s[0] for s in slots]
                    s1 = [s[1] for s in slots]
                    if len(set(s1)) == 1:
                        merged = _agg_line(ym, s0, spec["verb"], "先后与" + s1[0])
                    elif len(set(s0)) == 1:
                        merged = _agg_line(ym, s1, spec["verb"], "先后与" + s0[0])
                if merged:
                    out.append({"date": ym, "type": typ, "text": merged,
                                "module": entries[0].get("module", "")})
                    continue
        out.extend(entries)
    return _merge_affair_pairs(out, f)


def _merge_affair_pairs(events, f=None):
    """「私情+相恋」成对合并 (v15): 同一月内同一对的 had_sex 与 became_lovers
    并成一行: '869年1月，麦克·汤利与吉塞勒·加洛林私通相恋。' (成对事件
    拆两行浪费模型注意力, 且两行日期只差一天)。"""
    slots = {}   # (ym, 对象对) -> {type: (去日期前缀正文, 完整原文)}
    for e in events:
        typ = e.get("type")
        pat = _PAIR_MERGE.get(typ)
        if not pat:
            continue
        d = e.get("date") or ""
        ym = ".".join(str(d).split(".")[:2]) if d else ""
        full = e["text"]
        body = full
        if d and f:
            prefix = f"{f.date(d)}，"
            if body.startswith(prefix):
                body = body[len(prefix):]
        m = re.match(pat, body)
        if not m:
            continue
        key = (ym, frozenset((m.group(1), m.group(2))))
        slots.setdefault(key, {})[typ] = (body, full)
    drop = set()
    merged = []   # (ym, text)
    for (ym, _pair), got in slots.items():
        hx = got.get("had_sex")
        lv = got.get("became_lovers")
        if not hx or not lv:
            continue
        hx_body, hx_full = hx
        lv_body, lv_full = lv
        m = re.match(r"^(.+?)与(.+?)有私情。$", hx_body)
        if not m:
            continue
        y, _, mm = ym.partition(".")
        merged.append((ym, f"{y}年{int(mm)}月，{m.group(1)}与{m.group(2)}私通相恋。"))
        drop.add(hx_full)
        drop.add(lv_full)
    if not merged:
        return events
    out = [e for e in events if e["text"] not in drop]
    for ym, text in merged:
        out.append({"date": ym, "type": "became_lovers", "text": text,
                    "module": "情变私通"})
    out.sort(key=lambda e: cl.date_key(e.get("date") or ""))
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
        "name": f.name_with_regnal(pid),  # v17: 主角名带世系编号 (与时间线文本同口径)
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
    # v27: 语言风味 — 母语/兼通 + 与妻室子女的言语异同
    p["language_line"] = f.language_sentence(pid)
    p["language_bridge"] = f.language_bridge_line(pid)
    # v28: 与妻室子女的逐人言语关系句 (程序直给「相通/须通译」结论)
    _lrel = f.language_relation_lines(pid)
    if _lrel:
        p["language_relations"] = _lrel
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
    # v26: 信仰履历 (改信过程 — 游戏无记忆, 逐档 faith 差分)
    fhl = f.faith_history_lines(pid)
    if fhl:
        p["faith_history"] = "；".join(fhl)
    # v7: 家族家训 + 宫廷/营地官职
    mot = f.motto()
    if mot:
        p["motto"] = mot
    cpl, _cpch = f.court_positions_lines()
    if cpl:
        # v23: 主语=任职者 (仲宣任丑角…；德方任私人医生…), 组间以「；」分隔
        p["court_positions"] = "；".join(cpl)
    # v11: as_of 早于末档时, 直辖/封臣/营规等明细是「后期快照」数据, 不进入提示词
    # (只做头衔维度; 明细维度如要按时期需另行逐年快照, 成本高暂不做)
    skip_detail = bool(f.as_of) and cl.date_key(f.as_of) < cl.date_key(
        cache.get("last_date") or f.as_of or "9999.9.9")
    ld = rec.get("landed") or {}
    gov = ld.get("government")
    # v28: 政体原始键 (提示词侧按政体换措辞用: 天朝制/行政制=官职轮转)
    p["government_key"] = gov or ""
    # v11: 无地/有地分支按 as_of 首要头衔判定 (十年传记穿越时, 缓存 landed 是末档数据)
    ptier, ptid = f._primary_title_at(pid)
    # v28: 只有**真·无地冒险者营地** (x_d_laamp_/雇佣团/教团) 才走营地分支;
    # 世族庄园 (x_nf_) 与游牧毡帐 (x_c_nomad_) 是家业/驻地, 不走营地分支。
    if f.title_kind(ptid) == "camp" or gov == "landless_adventurer_government":
        # ---- 无地冒险者: 营地 ----
        p["landless"] = True
        camp_tid = ptid if f.title_kind(ptid) == "camp" \
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
        # ---- 有地领主 / 世族 ----
        # v28: 世族庄园 (x_nf_/c_nf_) — 家业身份, 与「无地冒险者营地」分列;
        # 取 as_of 仍在持有的庄园 (十年传记不回退到末档数据)。
        for _etid, _ivs in (f._hold_intervals(pid) or {}).items():
            if _ivs and _ivs[-1][1] is None and f._is_estate_title(_etid):
                p["estate_name"] = f._title_name_at(_etid, f.as_of) or "家族庄园"
                p["estate_word"] = f.estate_kind_word(_etid, pid)
                p["estate_holder"] = f._estate_holder_word(pid)
                break
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
        # v26: 游牧牧群/口粮 — 与金钱同口径 (只给当前值), 且取 as_of 熔件的毡帐,
        # 不用缓存末档 (十年传记 as_of 早于末档时数值会穿越)。
        # v28: 按 domicile 类型分派 — 牧群只在毡帐 (yurt) 有意义, 口粮只在无地
        # 营地 (camp) 有意义, 庄园/领地两者皆无; 0 值一律省略 (此前天朝制世族
        # 档案写出「牧群0」)。
        if not p.get("landless"):
            _pc = f._chars.get(str(pid)) or {}
            _pld = _pc.get("landed_data") or {}
            _dom = cl.player_domicile(f.melt, _pld.get("domain") or [], pid)
            if _dom is None:
                _dom = ld if ld.get("herd") is not None else None
            _dtype = (_dom or {}).get("domicile_type") or ld.get("domicile_type") or ""
            _is_nomad = _dtype == "yurt" or any(
                f._is_nomad_camp(_t) for _t in (ld.get("domain") or []))
            _is_camp = (not _is_nomad) and (
                _dtype == "camp" or gov == "landless_adventurer_government")

            def _pos(v):
                try:
                    return None if float(v) == 0 else v
                except (TypeError, ValueError):
                    return None

            if _dom and _is_nomad and _dom.get("herd") is not None:
                hv = _pos(_dom.get("herd"))
                if hv is not None:
                    p["herd"] = hv
            if _dom and _is_camp and _dom.get("provisions") is not None:
                pv = _pos(_dom.get("provisions"))
                if pv is not None:
                    p["provisions"] = pv
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
        # v28: 健康/压力只给游戏档位词 (现代白话), 不再直出 5.5/69 这类元信息数值
        hs = health_state_zh(ad.get("health"))
        if hs:
            bits.append(hs)
        ss = stress_state_zh(ad.get("stress"))
        if ss:
            bits.append(ss)
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
    # 死亡 (终传时; v11: as_of 早于死期视为在世, 十年传记不泄漏「死于…」)
    pd = cache.get("player_death")
    if pd and f.as_of and cl.date_key(f.as_of) < cl.date_key(pd.get("date") or "9999.9.9"):
        pd = None
    if pd:
        p["death"] = (
            f"死于{f.date(pd.get('date'))}，"
            f"{f.death_clause(pid, date=pd.get('date'), reason=pd.get('reason'), killer=pd.get('killer'))}。"
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
            nm = f.kin_label(sid)
            if not nm:
                continue
            note = ""
            if father_id is not None and sid != father_id:
                for k, label in (("primary_spouse", "妻"), ("spouse", "妻"),
                                 ("concubine", "妾"), ("former_spouses", "前妻"),
                                 ("former_concubines", "前妾")):
                    if sid in (fd_fam.get(k) or []):
                        note = f"（原为父{f.kin_label(father_id)}之{label}）"
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
    child_ids = [c for c in _asof_ids(f, fam.get("child") or []) if f.name(c)]
    p["children"] = "、".join(f.kin_label(c) for c in child_ids)
    # v26: 子女按性别分列 (「子A、B，女C、D」) — 与 _character_profiles 同口径
    p["children_sons"] = "、".join(
        f.kin_label(c) for c in child_ids if not f._is_female(c))
    p["children_daughters"] = "、".join(
        f.kin_label(c) for c in child_ids if f._is_female(c))
    # v28: 主体性别 (配偶标签「妻室/夫婿」按此取, 见 biography._profile_lines)
    p["female"] = f._is_female(pid)
    p["father"] = "、".join(
        f.kin_label(x) for x in (fam.get("father") or []) if f.name(x))
    p["mother"] = "、".join(
        f.kin_label(x) for x in (fam.get("mother") or []) if f.name(x))
    p["siblings"] = "、".join(
        f.kin_label(x) for x in (fam.get("siblings") or []) if f.name(x))
    # v5: 自定义角色 (无谱系) — 家世通用文本覆盖
    if f.is_custom_start(pid):
        p["custom_start"] = True
    # v5: 真正父亲 (私生子场景; 与法理父不同才渲染)
    rf = (fam.get("real_father") or [None])[0]
    if rf is not None:
        rfname = f.kin_label(rf)
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
    # v28: 主角的谋害对象与被害者 (成功谋杀记忆 ∪ 缓存死亡记录 killer==主角) —
    # 这些人的族属/信仰在存档里一直可读 (dead_unprunable 保留对象字段),
    # 此前只进《刺客列传》(击杀 >5 才生成), 陆氏这类小传里完全读不到。
    prec = (f.cache.get("characters") or {}).get(str(pid)) or {}
    for m in prec.get("memories") or []:
        if m.get("type") == "successful_murder":
            v = (m.get("participants") or {}).get("victim")
            if isinstance(v, int) and v != pid:
                out.setdefault(v, 2)
    for _cid, _rec in (f.cache.get("characters") or {}).items():
        if int(_cid) == pid:
            continue
        if (_rec.get("death") or {}).get("killer") == pid:
            out.setdefault(int(_cid), 2)
    return out


def _character_profiles(f):
    """每个缓存角色: 干净档案 + 记忆 + 死亡 + 亲属 + 历任头衔。
    v13: 只构建进提示词的角色 (见 _profile_needed_ids), 按需计算。"""
    out = {}
    for cid in _profile_needed_ids(f):
        rec = (f.cache.get("characters") or {}).get(str(cid)) or {}
        if not rec:
            continue
        name = f.name_with_regnal(cid)  # v17: 档案名带世系编号 (与时间线文本同口径)
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
        # v27: 语言事实句 (母语/兼通), 供传记渲染「语言」行
        prof["language_line"] = f.language_sentence(cid)
        # v28: 该角色与主角的言语关系句 (程序直给「相通/须借通译」结论) —
        # 《列传·好友/仇人》《家室列传》写二人交谈时照此落笔
        _pid = f.cache.get("player_id")
        if _pid is not None and int(cid) != int(_pid):
            _ln = f.language_relation_line(_pid, cid)
            if _ln:
                prof["language_relation"] = _ln
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
        fhl = f.faith_history_lines(cid)
        if fhl:
            prof["faith_history"] = "；".join(fhl)
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
        # v27: 亲属一律「头衔+姓名」(kin_label), 不再只给姓名
        prof["spouses"] = "、".join(f.kin_label(s) for s in spouse_ids if f.name(s))
        prof["concubines"] = "、".join(
            f.kin_label(s) for s in _asof_ids(f, fam.get("concubine") or []) if f.name(s))
        child_ids = [c for c in _asof_ids(f, fam.get("child") or []) if f.name(c)]
        prof["children"] = "、".join(f.kin_label(c) for c in child_ids)
        # v26: 子女按性别分列 (「子A、B，女C、D」) — 此前只有无性别混排列表,
        # 模型只能靠名字猜 (田所2 睦/立希被写成儿子)。
        prof["children_sons"] = "、".join(
            f.kin_label(c) for c in child_ids if not f._is_female(c))
        prof["children_daughters"] = "、".join(
            f.kin_label(c) for c in child_ids if f._is_female(c))
        # v28: 主体性别 — 配偶标签按此取 (女角色的丈夫不再写成「妻室」)
        prof["female"] = f._is_female(cid)
        prof["father"] = "、".join(
            f.kin_label(x) for x in (fam.get("father") or []) if f.name(x))
        prof["mother"] = "、".join(
            f.kin_label(x) for x in (fam.get("mother") or []) if f.name(x))
        prof["siblings"] = "、".join(
            f.kin_label(x) for x in (fam.get("siblings") or []) if f.name(x))
        # v5: 自定义角色 + 真正父亲 (私生子)
        if f.is_custom_start(cid):
            prof["custom_start"] = True
        rf = (fam.get("real_father") or [None])[0]
        if rf is not None:
            rfname = f.kin_label(rf)
            if rfname:
                prof["real_father"] = rfname
        ht = f.held_titles(cid)
        if ht:
            prof["titles_held"] = "；".join(ht)
        mems = []
        # v26: 取缓存记忆 (此前写 prof.get("memories"), 而 prof 无该键 →
        # 「传主行迹」对所有人恒为「（无行迹记录）」)
        for mem in rec.get("memories") or []:
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
            if isinstance(holder, list):
                # v15: 同日多事件 (destroyed+created 等, 重复键合并成列表)
                for _h2 in holder:
                    if isinstance(_h2, dict):
                        if _h2.get("holder") is not None:
                            seq.append((d, _h2["holder"]))
                    elif _h2 is not None:
                        seq.append((d, _h2))
            elif holder is not None:
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
    # v13: 朝廷职司 (尚书省六部/御史台/枢密院 — as_of 时点的时任者 + 职司官职)
    min_off = f._current_ministers(f.as_of)
    if min_off:
        out["ministers"] = min_off
    # v28: 要员隐事 — 最高领主链 (皇帝/路/王国) 与朝廷职司时任者的隐事
    # (用户 2026-09-10 决策: 《朝局风云录》收录最高统治者的秘密)
    out["secrets"] = _realm_secret_lines(f)
    return out


def _realm_secret_lines(f):
    """要员隐事 (v28): 上位链持有人 (不含主角) + 朝廷职司时任者的隐事句,
    上限 6 条; 无则返回 []。"""
    pid = f.cache.get("player_id")
    owners = []
    try:
        prov = f.character_location_province(pid)
        county = f.county_at_province(prov)
        for _tid, hid in (f.liege_chain(county) if county else []):
            if isinstance(hid, int) and hid != pid:
                owners.append(hid)
    except Exception:
        pass
    for hid in f.minister_ids(f.as_of):
        if hid != pid and hid not in owners:
            owners.append(hid)
    out = []
    for oid in owners:
        for rec in f.secrets_owned_by(oid, f.as_of):
            s = f.secret_sentence(rec)
            if not s:
                continue
            kl = f.secret_known_line(rec)
            out.append(s + kl)
            if len(out) >= 6:
                return out
    return out


# v15: 大奸大恶专题模块 — 由 _villain_chains 程序直算 (非记忆类型映射)。
# 模块名同时参与十年戏剧主题抽取 (build_facts 并入 decade_modules)。
VILLAIN_MODULES = ("谋害人命", "托卵承嗣", "奸夫谋夫", "共谋暗杀", "血亲之刃", "血脉登基")

# 阴谋参与者角色类型 → 中文 (熔件 schemes agent_slots; 本地化缺失时兜底)
_AGENT_ZH = {
    "agent_assassin": "刺客", "agent_lookout": "眼线", "agent_lookout_speed": "眼线",
    "agent_infiltrator": "内应", "agent_thug": "打手", "agent_muscle": "打手",
    "agent_footpad": "暴徒", "agent_thief": "窃贼", "agent_outcast": "亡命徒",
    "agent_sycophant": "谄媚者", "agent_intermediary": "中间人", "agent_amanuensis": "文书",
    "agent_bureaucrat": "僚属", "agent_diplomat": "说客", "agent_scout": "探子",
    "agent_alibi": "伪证者", "agent_poet": "文士", "agent_musician": "乐师",
    "agent_herald": "传令官", "agent_gabbler": "饶舌者", "agent_socialite": "交际花",
    "agent_political_socialite": "政界名流", "agent_shill": "托儿", "agent_courtesan": "名妓",
    "agent_eunuch": "阉人", "agent_bodyguard": "护卫", "agent_decoy": "诱饵",
    "agent_supplier": "供货人", "agent_cleric": "神职人员", "agent_cleric_success": "神职人员",
    "agent_theologian": "神学家", "agent_planner": "谋士", "agent_bailiff": "执达吏",
    "agent_scribe": "书吏", "agent_draughtsman": "画师", "agent_proponent": "拥趸",
}


def _sub_relation_loc(f, s, owner, target, extra=None):
    """关系原因本地化串 → 干净中文句 (替换 CK3 角色/代词占位符)。
    [CHARACTER.*]=记录拥有者, [TARGET_CHARACTER.*]=对方, [TARGET_CHARACTER_2.*]=
    第三人 (involved_character, 如地牢主人); |U 是英文大写变体, 中文忽略;
    Possessive 中文无词形变化, 用原名; 未知标签 (省份/物品) 清空。"""
    oname = f.name_or(owner)
    tname = f.name_or(target)
    xname = f.name_or(extra) if isinstance(extra, int) else ""
    subs = (
        ("[CHARACTER.GetShortUIName|U]", oname),
        ("[CHARACTER.GetShortUIName]", oname),
        ("[TARGET_CHARACTER.GetShortUIName|U]", tname),
        ("[TARGET_CHARACTER.GetShortUIName]", tname),
        ("[TARGET_CHARACTER.GetShortUINameNoTooltip]", tname),
        ("[TARGET_CHARACTER_2.GetShortUINamePossessive]", xname or tname),
        ("[TARGET_CHARACTER.GetShortUINamePossessiveNoTooltip]", tname),
        ("[TARGET_CHARACTER.GetShortUINamePossessive]", tname),
        ("[CHARACTER.GetHerHisYour]", "其"),
        ("[TARGET_CHARACTER.GetHerHisYour]", "其"),
        ("[PROVINCE.GetName]", "当地"),
        ("[PROVINCE.Custom('TerrainTypeProvince')]", ""),
        ("[TARGET_CHARACTER.Custom('child_favorite_toy')]", "玩具"),
    )
    for a, b in subs:
        s = s.replace(a, b)
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = s.replace("  ", " ").strip()
    return s


def _player_murder_map(f):
    """主角谋杀集: {victim_id: 谋杀日期} — successful_murder 记忆 ∪ 死亡记录
    killer==主角 (供 _villain_chains / relation_cause_lines 共用)。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return {}
    chars = cache.get("characters") or {}
    prec = chars.get(str(pid)) or {}
    murders = {}
    for m in prec.get("memories") or []:
        if m.get("type") == "successful_murder":
            v = (m.get("participants") or {}).get("victim")
            if isinstance(v, int) and v != pid:
                d = m.get("creation_date")
                if d:
                    murders.setdefault(v, d)
    for cid, rec in chars.items():
        if int(cid) == pid:
            continue
        d = (rec.get("death") or {}).get("date")
        if d and (rec.get("death") or {}).get("killer") == pid:
            murders.setdefault(int(cid), d)
    return murders


def relation_cause_lines(f, cid, rel_date):
    """关系缘由 (v16, 程序直算): 主角与某角色结仇/结怨的**因由** —
    不满足于「X年X月结仇」, 直算仇恨根源:
    ① 其亲属 (父/母/配偶/子女/兄弟姊妹) 中被主角谋杀者 (死期早于结怨);
    ② 其配偶与主角私通 (夺妻/夺夫之恨);
    ③ 其抚养的子女实为主角血脉 (托卵承嗣)。
    返回 ['其父巴西尔·马其顿已于878年8月1日被麦克·汤利谋杀', …]。
    友缘 (何时结友) 由 biography 侧 _relation_reasons 的结友记忆句承担。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None or cid == pid or not rel_date:
        return []
    rd = cl.date_key(rel_date)
    chars = cache.get("characters") or {}
    cfam = (chars.get(str(cid)) or {}).get("family") or {}
    murders = _player_murder_map(f)
    pname = f.name_or(pid)
    c_female = f._is_female(cid)
    out = []
    # ① 亲属被主角谋杀 (死期早于结怨)
    rel_keys = (("father", "其父"), ("mother", "其母"),
                ("primary_spouse", "其妻"), ("spouse", "其妻"),
                ("former_spouses", "其前妻"), ("child", "其子"),
                ("siblings", "其兄弟姊妹"))
    for key, label in rel_keys:
        for rid in cfam.get(key) or []:
            if not isinstance(rid, int):
                continue
            md = murders.get(rid)
            if not md or cl.date_key(md) >= rd:
                continue
            rname = f.name_or(rid)
            if not rname:
                continue
            if key == "child":
                label = "其女" if f._is_female(rid) else "其子"
            elif key in ("primary_spouse", "spouse"):
                label = "其夫" if c_female else "其妻"
            out.append(f"{label}{rname}已于{f.date(md)}被{pname}谋杀")
            break
    # ② 其配偶与主角私通 (私情/相恋早于结怨)
    lovers = set()
    prec = chars.get(str(pid)) or {}
    for m in prec.get("memories") or []:
        if m.get("type") in ("became_lovers", "had_sex"):
            for v in (m.get("participants") or {}).values():
                if isinstance(v, int) and v != pid:
                    d = m.get("creation_date")
                    if d and cl.date_key(d) < rd:
                        lovers.add(v)
    spouse_label = "其夫" if c_female else "其妻"
    found_spouse = False
    for key in ("primary_spouse", "spouse", "former_spouses"):
        if found_spouse:
            break
        for sid in cfam.get(key) or []:
            if sid in lovers:
                sname = f.name_or(sid)
                if sname:
                    out.append(f"{spouse_label}{sname}与{pname}私通")
                    found_spouse = True
                break
    # ③ 其抚养的子女实为主角血脉 (托卵承嗣, 出生早于结怨)
    for cid2 in cfam.get("child") or []:
        if not isinstance(cid2, int):
            continue
        fam2 = (chars.get(str(cid2)) or {}).get("family") or {}
        rf = (fam2.get("real_father") or [None])[0]
        if rf != pid:
            continue
        c2name = f.name_or(cid2)
        b = (chars.get(str(cid2)) or {}).get("birth")
        if c2name and b and cl.date_key(b) < rd:
            sex = "女" if f._is_female(cid2) else "子"
            out.append(f"其抚养之{c2name}实为{pname}之{sex}")
            break
    return out


def _villain_chains(f):
    """大奸大恶关系链 (v15, 程序直算): [(模块名, 自然语言句)]。
    数据源: 缓存 family/death/memories + 熔件 titles/heir/schemes。
    - 奸夫谋夫: 主角谋杀了某人, 而该人之配偶是主角情人 (遗孀/鳏夫改嫁情形一并写出);
    - 托卵承嗣: 法理父 ≠ 实父 — 法理父抚养了主角之子/女 (或主角抚养他人之子/女);
    - 共谋暗杀: 熔件 active schemes 中 type=murder 且 owner=主角 → agent_slots 参与者;
    - 血亲之刃: 主角谋杀了自己的血亲 (父/母/子女/兄弟姊妹);
    - 血脉登基: 高位头衔 (k_/e_/h_) 第一继承人实为主角之子/女 (私生),
      且同母手足中有被主角谋杀者时一并点出。
    所有条目按 as_of 截断 (十年传记只写该时期内的戏剧)。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    chars = cache.get("characters") or {}
    prec = chars.get(str(pid)) or {}
    pname = f.name_or(pid)
    ao = cl.date_key(f.as_of) if f.as_of else None

    def in_span(d):
        return ao is None or (d and cl.date_key(d) <= ao)

    def is_female(cid):
        return f._is_female(cid)

    # ---- 主角情人集: cid -> 私情/相恋的最早日期 ----
    lovers = {}
    for m in prec.get("memories") or []:
        if m.get("type") in ("became_lovers", "had_sex"):
            for v in (m.get("participants") or {}).values():
                if isinstance(v, int) and v != pid:
                    d = m.get("creation_date") or ""
                    if v not in lovers or (d and (not lovers[v] or d < lovers[v])):
                        lovers[v] = d
    # ---- 主角谋杀集: victim -> 谋杀日期 (记忆 ∪ 死亡记录) ----
    murders = {}
    for m in prec.get("memories") or []:
        if m.get("type") == "successful_murder":
            v = (m.get("participants") or {}).get("victim")
            if isinstance(v, int) and v != pid:
                d = m.get("creation_date")
                if d:
                    murders.setdefault(v, d)
    for cid, rec in chars.items():
        if int(cid) == pid:
            continue
        d = (rec.get("death") or {}).get("date")
        if d and (rec.get("death") or {}).get("killer") == pid:
            murders.setdefault(int(cid), d)

    chains = []
    pfam = prec.get("family") or {}

    # ---- 奸夫谋夫 (谋杀情人配偶 / 配偶改嫁) ----
    for victim, vdate in sorted(murders.items(),
                                key=lambda kv: cl.date_key(kv[1])):
        if not in_span(vdate):
            continue
        vfam = (chars.get(str(victim)) or {}).get("family") or {}
        vname = f.name_or(victim)
        if not vname:
            continue
        for sid in list(dict.fromkeys(
                (vfam.get("primary_spouse") or []) + (vfam.get("spouse") or []))):
            if sid == pid or sid not in lovers:
                continue
            lname = f.name_or(sid)
            if not lname:
                continue
            # 遗孀/鳏夫是否已与主角成婚 (从双方记忆找成婚日期)
            mdate = ""
            for m in prec.get("memories") or []:
                if m.get("type") == "married" and \
                        (m.get("participants") or {}).get("spouse") == sid:
                    mdate = m.get("creation_date") or ""
                    break
            if not mdate:
                for m in (chars.get(str(sid)) or {}).get("memories") or []:
                    if m.get("type") == "married" and \
                            (m.get("participants") or {}).get("spouse") == pid:
                        mdate = m.get("creation_date") or ""
                        break
            sname = "其妻" if not is_female(victim) else "其夫"
            off = f.official_title(victim)
            disp = f"{off}{vname}" if off else vname
            remarry = f"，并于{f.date(mdate)}嫁于{pname}" \
                if mdate and in_span(mdate) else ""
            # v16: 受害者家人也先遭毒手 → 补注 (父子同刃: 萨洛蒙之子
            # 里瓦朗 871年已被杀 — 共享前缀给全篇正确亲缘,
            # 防模型把「X·马布·萨洛蒙」读成萨洛蒙长辈)
            kin_note = ""
            for kid in (vfam.get("child") or []):
                if not isinstance(kid, int) or kid not in murders:
                    continue
                kd = murders[kid]
                if cl.date_key(kd) >= cl.date_key(vdate):
                    continue
                kname = f.name_or(kid)
                if kname:
                    ksex = "女" if is_female(kid) else "子"
                    kin_note = (f"；其{ksex}{kname}"
                                + f"已于{f.date(kd)}被{pname}谋杀")
                break
            chains.append(("奸夫谋夫",
                f"{f.date(vdate)}，{disp}被{pname}谋杀——"
                f"{sname}{lname}正是{pname}的情人{remarry}{kin_note}。"))

    # ---- 托卵承嗣 (法理父 ≠ 实父, 且涉及主角) — 按 (法理父, 实父, 性别) 合并 ----
    cuckoo = {}   # (lf, rf, sex, 方向) -> [child 名]
    for cid, rec in chars.items():
        fam = rec.get("family") or {}
        rf = (fam.get("real_father") or [None])[0]
        lf = (fam.get("father") or [None])[0]
        if rf is None or lf is None or rf == lf:
            continue
        if not in_span(rec.get("birth")):
            continue
        if rf != pid and lf != pid:
            continue
        cname = f.name_or(int(cid))
        if not cname:
            continue
        sex = "女" if is_female(int(cid)) else "子"
        key = (lf, rf, sex)
        cuckoo.setdefault(key, []).append(cname)
    for (lf, rf, sex), items in cuckoo.items():
        lfname = f.name_or(lf)
        rfname = f.name_or(rf)
        if not items or not lfname or not rfname:
            continue
        # v17: 戏剧性事件链不再带出生年括注 (修复方案_汤利五问题.md 问题3 —
        # 亲缘标签已消歧, 出生年吸引注意力; 消歧留在刺客列传死者行/时间线谋杀行)
        joined = "、".join(items)
        if rf == pid:
            chains.append(("托卵承嗣",
                f"{lfname}抚养的{joined}，实为{pname}之{sex}。"))
        else:
            chains.append(("托卵承嗣",
                f"{pname}抚养的{joined}，实为{rfname}之{sex}。"))

    # ---- 共谋暗杀 (熔件 active schemes: 主角主导的谋杀密谋) ----
    schemes = ((f.melt.get("schemes") or {}).get("active") or {})
    for _scid, sc in schemes.items():
        if not isinstance(sc, dict) or sc.get("type") != "murder":
            continue
        owner = sc.get("owner")
        tgt = sc.get("target")
        if isinstance(tgt, dict):
            tgt = tgt.get("target")
        sdate = sc.get("date") or ""
        if sdate and not in_span(sdate):
            continue
        agents = []
        for slot in (sc.get("agent_slots") or []):
            if not isinstance(slot, dict):
                continue
            c = slot.get("character")
            # 4294967295 (0xFFFFFFFF) 是 CK3 空槽占位符, 非真实角色
            if isinstance(c, int) and 0 < c < 4294967295 and c != pid and c != owner:
                an = f.name_or(c)
                if an:
                    t = L.loc(f.table, slot.get("type") or "") or \
                        _AGENT_ZH.get(slot.get("type") or "") or "同谋"
                    agents.append((an, t))
        if owner == pid and isinstance(tgt, int) and tgt != pid:
            tname = f.name_or(tgt)
            if not tname:
                continue
            if agents:
                shown = []
                for an, at in agents[:3]:
                    shown.append(f"{an}（{at}）")
                tail = f"等{len(agents)}人" if len(agents) > 3 else ""
                chains.append(("共谋暗杀",
                    f"密谋刺杀{tname}者以{pname}为首，"
                    f"参与者{'、'.join(shown)}{tail}。"))
            else:
                chains.append(("共谋暗杀",
                    f"{pname}正密谋刺杀{tname}。"))
        elif isinstance(tgt, int) and tgt == pid and isinstance(owner, int) and owner != pid:
            oname = f.name_or(owner)
            if oname:
                chains.append(("共谋暗杀",
                    f"{oname}正密谋刺杀{pname}。"))

    # ---- 血亲之刃 (谋杀自己的血亲) ----
    for victim, vdate in murders.items():
        if not in_span(vdate):
            continue
        rel = ""
        if victim in (pfam.get("child") or []):
            rel = f"自己的{'女' if is_female(victim) else '子'}"
        elif victim in (pfam.get("father") or []):
            rel = "自己的父亲"
        elif victim in (pfam.get("mother") or []):
            rel = "自己的母亲"
        elif victim in (pfam.get("primary_spouse") or []) + (pfam.get("spouse") or []):
            rel = "自己的妻室"
        elif victim in (pfam.get("siblings") or []):
            rel = "自己的兄弟姊妹"
        if rel:
            vname = f.name_or(victim)
            if vname:
                chains.append(("血亲之刃",
                    f"{pname}谋杀了{rel}{vname}。"))

    # ---- 血脉登基 (高位头衔第一继承人是主角私生子女; 同母手足中被谋杀者点出) ----
    melt_date = (f.melt.get("date") or "")
    as_of_gap = bool(f.as_of) and cl.date_key(f.as_of) < cl.date_key(melt_date)
    for tid, t in f._lt.items():
        if not isinstance(t, dict):
            continue
        key = t.get("key") or ""
        if not key.startswith(("k_", "e_", "h_")):
            continue
        heir0 = (t.get("heir") or [None])[0]
        if not isinstance(heir0, int):
            continue
        hrec = chars.get(str(heir0)) or {}
        hfam = hrec.get("family") or {}
        rf = (hfam.get("real_father") or [None])[0]
        mother = (hfam.get("mother") or [None])[0]
        if not (rf == pid or (mother in lovers)):
            continue
        if not in_span(hrec.get("birth")):
            continue
        if as_of_gap:
            # 十年传记且熔件晚于 as_of: 要求 as_of 时点持有者与当前持有者一致,
            # 防止把后期继承变更泄漏进早期十年。
            hist = t.get("history") or {}
            holder_now = t.get("holder")
            holder_at = None
            aok = cl.date_key(f.as_of)
            for hd in sorted(hist, key=cl.date_key):
                if cl.date_key(hd) <= aok:
                    holder_at = hist[hd]
            if holder_at != holder_now:
                continue
        hname = f.name_or(heir0)
        if not hname:
            continue
        # v17: 戏剧性事件链不再带出生日期括注 (修复方案_汤利五问题.md 问题3 —
        # 亲缘标签已消歧, 出生年吸引注意力; 消歧留在刺客列传死者行/时间线谋杀行)
        # 同母手足中被主角谋杀者 → 加注 (血脉登基的戏剧钩子, 附长幼词)
        dead_sib = ""
        for s in (hfam.get("siblings") or []):
            srec = chars.get(str(s)) or {}
            if (srec.get("death") or {}).get("killer") == pid:
                sname = f.name_or(s)
                sdate = (srec.get("death") or {}).get("date")
                if sname:
                    sb = srec.get("birth")
                    older = True
                    if sb and hrec.get("birth"):
                        older = cl.date_key(sb) < cl.date_key(hrec.get("birth"))
                    sfemale = is_female(s)
                    sw = "长姐" if (older and sfemale) else \
                          "长兄" if older else ("妹" if sfemale else "弟")
                    dead_sib = (f"；其同母{sw}{sname}已于{f.date(sdate)}"
                                f"被{pname}谋杀")
                break
        sex = "女" if is_female(heir0) else "子"
        tname = f.title(tid)
        if rf == pid:
            mname = f.name_or(mother) if mother in lovers else ""
            who = (f"{pname}与{mname}之{sex}" if mname
                   else f"{pname}之{sex}")
        else:
            who = f"{pname}情人之{sex}"
        chains.append(("血脉登基",
            f"{hname}为{tname}第一继承人，实为{who}{dead_sib}。"))

    return chains


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
    # 6) v26: 主角囚禁期间死亡者 (狱死/瘐毙, 游戏未必把凶手记成主角) —
    # 只收卒时已囚满一年者 (imprison_duration 有值), 与死句的囚禁时长同门。
    for mem in prec.get("memories") or []:
        if mem.get("type") != "imprisoned_other":
            continue
        v = (mem.get("participants") or {}).get("imprisoned")
        if not isinstance(v, int) or v == pid:
            continue
        vrec = (f.cache.get("characters") or {}).get(str(v)) or {}
        vd = (vrec.get("death") or {}).get("date")
        if vd and f.imprison_duration(v, date=vd):
            killed.add(v)
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
                clause = f.death_clause(cid, date=mdd.get("date"),
                                        reason=mdd.get("reason"),
                                        killer=mdd.get("killer"), imprison=True)
                ds = f"{f.name_or(cid)}死于{f.date(mdd.get('date'))}，{clause}。"
                # v24: 熔件反查兜底同样附受害者所在地 (男爵领; 无则省略)
                if mdd.get("killer") == pid:
                    vp = f.victim_place(cid)
                    if vp:
                        ds = ds.rstrip("。") + f"（死于{vp}）。"
        entry = {
            "id": cid,
            # v17: 死者名带世系编号 (以死期首要头衔计算, 鲁斯兰·克里维奇二世)
            "name": f.name_with_regnal(cid, date=(prof.get("death") or {}).get("date")),
            "birth": f.date(prof.get("birth")),
            "death": ds or "（死因不详）",
            "death_date": (prof.get("death") or {}).get("date") or "9999.9.9",
            # v24: 受害者死前最近可知所在男爵领 (无则 '', 调用方省略标注)
            "victim_place": f.victim_place(cid),
            "house": _dynasty_display(prof.get("dynasty_name"),
                                      prof.get("house_name")),
            "house_branch": _house_branch(prof.get("dynasty_name"),
                                          prof.get("house_name")),
            # v13: 死者官职 (含家族领袖的「XX家族乡绅」, 此前刺客列传无官职信息)
            # v21: 无领地头衔时接王子/公主称号兜底 (按死亡日期算父头衔 —
            # 王祦 → 高丽国皇子, 防模型把无头衔死者臆成平民)
            # v25: 官职国号按卒日 (李漼卒于唐 → 唐皇帝, 不随 as_of 写成秦皇帝)
            "office": f.official_title(
                cid, date=(prof.get("death") or {}).get("date"))
            or f.prince_title(cid, date=(prof.get("death") or {}).get("date")),
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
    # v17: 十年窗口 — 十年传记只收本十年死者 (补下界, 修复方案_汤利五问题.md 问题5:
    # 第 2 个十年不再出现 871 年就死掉的旧死者)。
    if f.as_of:
        ao = cl.date_key(f.as_of)
        out = [e for e in out
               if e["death_date"] == "9999.9.9" or cl.date_key(e["death_date"]) <= ao]
        if f.decade:
            lo = _decade_lower_bound(f)
            if lo:
                lok = cl.date_key(lo)
                out = [e for e in out
                       if e["death_date"] == "9999.9.9"
                       or cl.date_key(e["death_date"]) >= lok]
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
                rel.append(f"父{f.kin_label(fid)}")
        for bid in (fam.get("siblings") or []):
            if int(bid) in china_emperors:
                rel.append(f"兄{f.kin_label(bid)}")
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


def _cn_date_key(s):
    """'867年1月1日任…' 行首中文日期 → date_key; 解析失败返回 None。"""
    m = re.match(r"^(\d+)年(\d+)月(\d+)日", s or "")
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _protagonist_stations(f):
    """主角身份/驻地变化年表 (v20, B3): 头衔阶段 (无地营地显式标注) + 逐年驻地,
    按日期合并排序。十年传记按 as_of 截断。返回干净中文行列表, 上限 40 行。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    items = []  # (date_key, 行文本)
    # 1) 头衔/身份阶段 (held_titles 已带 无地冒险者营地 标注; 本身按 as_of 截断)
    try:
        for ln in f.held_titles(pid):
            dk = _cn_date_key(ln)
            if dk is not None:
                items.append((dk, ln))
    except Exception:
        pass
    # 2) 驻地轨迹 (player_locations → 伯爵领名; 按 as_of 截断)
    hist = cache.get("player_locations") or []
    if f.as_of:
        aok = cl.date_key(f.as_of)
        hist = [loc for loc in hist
                if not loc.get("date") or cl.date_key(loc.get("date")) <= aok]
    seen = set()
    for loc in hist:
        if not loc.get("date"):
            continue
        county = f.county_at_province(loc.get("province"))
        if county is None:
            continue
        cname = f.title(county)
        if not cname:
            continue
        key = (loc.get("date"), cname)
        if key in seen:
            continue
        seen.add(key)
        items.append((cl.date_key(loc["date"]), f"{f.date(loc['date'])}驻{cname}"))
    items.sort(key=lambda x: x[0])
    # 按行文本去重 (同日 头衔阶段+驻地 两行都保留, 只去掉完全重复的行)
    out = []
    seen_line = set()
    for dk, ln in items:
        if ln in seen_line:
            continue
        seen_line.add(ln)
        out.append(ln)
    return out[:40]


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
    """世系 (v5 终传附录): 主角 + 父母 + 妻妾 + 子女 + 兄弟姊妹 谱系行。
    v28: 「配偶」标签按主角性别取 (妻室/夫婿), 且 spouse 减去 primary_spouse —
    CK3 同一位妻子同时存在于两个字段, 此前输出「正妻：亮」+「侧室：亮」两行。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    fam = rec.get("family") or {}
    fem = f._is_female(pid)
    lines = []
    pname = f.name_or(pid)
    lines.append(f"一世 {pname}（{f.date(rec.get('birth'))}生）")
    spouses = [x for x in (fam.get("primary_spouse") or [])]
    side = [x for x in (fam.get("spouse") or []) if x not in set(spouses)]
    rows = [("father", "父"), ("mother", "母")]
    if fem:
        rows += [("primary_spouse_key", "正夫"), ("side_spouse_key", "侧夫")]
    else:
        rows += [("primary_spouse_key", "正妻"), ("side_spouse_key", "侧室")]
    rows += [("concubine", "妾" if not fem else "男宠"),
             ("former_concubines", "前妾" if not fem else "前男宠"),
             ("child", "子女"), ("siblings", "兄弟姊妹"),
             ("former_spouses", "前夫" if fem else "前妻")]
    for key, label in rows:
        if key == "primary_spouse_key":
            ids = spouses
        elif key == "side_spouse_key":
            ids = side
        else:
            ids = fam.get(key) or []
        if not ids:
            continue
        bits = []
        for x in ids:
            n = f.kin_label(x)
            if n:
                bits.append(n)
        if bits:
            lines.append(f"　{label}：{'、'.join(bits)}")
    return lines


def _secrets_facts(f):
    """隐事事实 (v28): 主角/家人近臣的隐事、知情情形、把柄、本十年见载事件。

    返回 {held, held_murder, kinsmen, known, known_by_others, events, any};
    无相关隐事时返回 {} (剧本不生成《阴私录》)。
    """
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return {}
    cut = f._secret_cut()
    mine = f.secrets_owned_by(pid, cut)
    held, murder = [], []
    for rec in mine:
        (murder if rec.get("type") in SECRET_MURDER_TYPES else held).append(rec)
    out = {}
    if held:
        out["held"] = [f.secret_sentence(r) for r in held if f.secret_sentence(r)]
        out["held_known"] = [f.secret_known_line(r) for r in held
                             if f.secret_known_line(r)]
        if not out["held_known"]:
            out["held_unrevealed"] = True      # 至今无人知晓
    if murder:
        out["held_murder"] = len(murder)
    # 家人与廷中僚属的隐事 (亲属 + court_positions 雇员)
    prec = (cache.get("characters") or {}).get(str(pid)) or {}
    fam = prec.get("family") or {}
    kin = []
    for key in ("primary_spouse", "spouse", "former_spouses", "concubine",
                "former_concubines", "child", "father", "mother", "siblings"):
        for x in fam.get(key) or []:
            if isinstance(x, int) and x != pid:
                kin.append(x)
    for h in cache.get("court_positions") or []:
        for p in h.get("positions") or []:
            e = p.get("employee")
            if isinstance(e, int) and e != pid:
                kin.append(e)
    kin_lines = []
    for kid in dict.fromkeys(kin):
        for rec in f.secrets_owned_by(kid, cut):
            s = f.secret_sentence(rec, owner_label=f.kin_label(kid))
            if s:
                kin_lines.append(s)
    if kin_lines:
        out["kinsmen"] = kin_lines[:10]
    # 主角握有的他人把柄
    known = []
    for rec in f.secrets_known_by(pid, cut):
        topic = f.secret_topic(rec)
        owner = f.name_or(rec.get("owner"))
        if topic and owner:
            known.append(f"{f.name_or(pid)}知悉{owner}的隐事：{topic}。")
    if known:
        out["known"] = known[:10]
    # 本十年内首见的隐事 (纪事时间锚点); 终传/在世传记用全期
    lo = _decade_lower_bound(f)
    lok = cl.date_key(lo) if lo else None
    ck = cl.date_key(cut) if cut else None
    events = []
    for sid, rec in (cache.get("secrets_history") or {}).items():
        if not isinstance(rec, dict) or rec.get("first"):
            continue
        if rec.get("type") in SECRET_MURDER_TYPES:
            continue          # 谋杀隐事只计数 (正文归《刺客列传》)
        fs = rec.get("first_seen")
        if not fs:
            continue
        dk = cl.date_key(fs)
        if ck is not None and dk > ck:
            continue
        if lok is not None and dk < lok:
            continue
        owner = rec.get("owner")
        if owner != pid and owner not in kin:
            continue
        s = f.secret_sentence(dict(rec, first=True))
        if s:
            # 事件行前缀已给日期, 句内不再重复「自X年见载」
            events.append(f"{f.date(fs)}，{s}")
    if events:
        out["events"] = sorted(set(events))[:12]
    out["any"] = bool(out.get("held") or out.get("kinsmen") or out.get("known"))
    return out


def build_facts(cache, melt, names_path=None, as_of=None, decade=None,
                nickname_override=None):
    """渲染干净事实集。melt 为 dict (已加载)。
    as_of (v11): 传记数据截止日期; 十年传记传十年末, 官职/历任/时间线/朝局按此截断。
    decade (v17): 十年传记序号 — 时间线/概览/摘要/刺客列传只收本十年
    (as_of−10年, as_of]; 终传/在世传 None 收全期。
    nickname_override (v20): {cid: 绰号} 按时代绰号覆盖 (十年传记重跑用)。"""
    f = Facts(cache, melt, names_path, as_of=as_of, decade=decade,
              nickname_override=nickname_override)
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
        pd["reason_zh"] = f.death_clause(
            cache.get("player_id"), date=pd.get("date"),
            reason=pd.get("reason"), killer=pd.get("killer"))
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
        "decade": decade,
        # v5 新增
        "bio_style": f.bio_style(),
        "killed": _killed_by_player(f),
        "wandering": _wandering_trail(f),
        # v28: 隐事 (主角/家人近臣的隐事、知情情形、把柄) — 《阴私录》数据源
        "secrets": _secrets_facts(f),
        # v20 (B3): 主角身份/驻地变化年表 (共享前缀【主角处境】数据源)
        "protagonist_stations": _protagonist_stations(f),
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
    # v14/v24: 十年戏剧主题 (Top5, 并列第5名全保留) — 模块切片与总纲预告用
    facts["decade_modules"] = decade_module_top(facts.get("timeline") or [],
                                                facts.get("protagonist") or {})
    # v15: 大奸大恶关系链 (程序直算) — 句并入主角【戏剧性事件】(共享前缀
    # 每请求可见), 模块名计入十年戏剧主题; 概览统计一并打包。
    vc = _villain_chains(f)
    facts["villain_chains"] = vc
    if vc:
        dfa = facts["protagonist"].setdefault("dramatic_facts", [])
        for _m, s in vc:
            if s not in dfa:
                dfa.append(s)
        dm = facts.get("decade_modules") or []
        for _m, _s in vc:
            if not any(x[0] == _m for x in dm):
                dm.append((_m, 3))
        # v24: 专题模块并入后再统一收口到 Top5 (此前并入后不再截断, 主题可 >10)
        facts["decade_modules"] = _cut_module_top(dm, top_n=5)
    stats = getattr(f, "_timeline_stats", None) or {}
    if stats:
        # 取计数前 6 的标签, 按计数降序; 供【概览】块渲染「本十年结怨9次…」
        top = sorted(stats.items(), key=lambda kv: -kv[1])[:6]
        facts["decade_stats"] = [f"{k}{v}次" for k, v in top]
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
