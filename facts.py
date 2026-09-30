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
import datetime
import hashlib
import random
import threading

import llm
import cache_lib as cl
import flavorization as FZ
import localization as L
import style as _style   # v30: 措辞表 (死因/头衔/统计标签) 见 style.py

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









# 谋杀类隐事: 正文归《刺客列传》, 篇内只计数 + 索引
SECRET_MURDER_TYPES = {"secret_murder", "secret_murder_attempt"}




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


# v29: 无游戏档位的量 — 数值一律不下发, 只给档位词 (用户决策 2026-09-11:
# 「其他数量用档位, 金币直接删去」)。国库金/月入/牧群属货币, 整项不写;
# 口粮 (无地营地补给) 给档位词。
_PROVISIONS_BANDS = ((100.0, "口粮充盈"), (30.0, "口粮尚足"), (0.0, "口粮将尽"))


def provisions_band(value):
    """营地口粮 → 档位词; 无法解析返回 ''。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    for lo, word in _PROVISIONS_BANDS:
        if v >= lo:
            return word
    return "口粮将尽"

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
    # v32 (马克龙问题1): 越狱记忆同带 imprisoner 槽, 此前未登记 → 监禁者丢失
    "escaped_from_prison_memory": "imprisoner",
    # v32 (马克龙问题3): 夭折/早产记忆的参与者是**生母** (游戏定义 participants={mother}),
    # 此前未登记 → 「未知其母, 只知为某人之血脉」
    "child_stillborn": "mother", "child_premature": "mother",
    "child_born": "child", "first_born": "child",
    "childhood_education_guardian": "guardian",
    "successful_murder": "victim",
    # v38 (问题1): Carnalitas 性事记忆族 (24 键共用 `sex_partner` 槽;
    # 常量 `_SEX_MEM_PREFIX` 处按前缀族解析, 无需逐键登记)
    "had_a_threesome_memory": "partner_1",
    # v38 (问题1 顺带): 同期未登记槽位的普通游戏记忆 —— 槽名取自游戏本地化
    # 描述里的占位符 ([rescuer]/[old_friend]/[dead_relation]/[new_relation])。
    "saved_from_assault_memory": "rescuer",
    "stopped_being_friends": "old_friend",
    "lover_died": "dead_relation", "soulmate_died": "dead_relation",
    "best_friend_died": "dead_relation", "nemesis_died": "dead_relation",
    "developed_crush": "new_relation",
    # v56 (问题1b): 加冕类记忆 —— host 是加冕礼的主角 (受冕者), coronator 是施礼者。
    # 存档实测 witnessed 的参与者即 `{"host": <受冕者>}` (游戏文案
    # 「我见证了[host]的加冕」); held 的是 `{"coronator": <施礼者>}`。
    # 旧稿两槽都未登记 + 模板无 {other} → 句面只剩「见证加冕」, 加冕者与加冕之事全失。
    # v78-5 (用户 D6): 加冕族其余键的参与者槽 (缺一即取不到 {other} 或取错槽)。
    # `held_a_coronation_memory` 以前**只有模板、没有模块** —— `module == ""` 会被
    # `slice_events` 放行到**所有**板块 (旧稿的漏点), 现随本轮一并登记。
    "witnessed_a_coronation_memory": "host",
    "held_a_coronation_memory": "coronator",
    "crowned_by_hof_memory": "hof",
    "coronation_highlighted_memory": "host",
    "coronation_cultural_acceptance_memory": "host",
    "coronation_legitimacy_memory": "host",
    "coronation_friend_memory": "host",
    "coronation_alliance_memory": "host",
    "coronation_hook_memory": "host",
    "coronation_vassal_levies_memory": "host",
    "coronation_vassal_taxes_memory": "host",
    "coronation_claim_memory": "host",
    "coronation_faction_discontent_memory": "host",
    "coronation_faction_members_memory": "host",
    "coronation_magnificence_loss_memory": "host",
    "coronation_coup_memory": "plotter",
    # 双槽键必须登记: 不登记时「取第一个 int 参与者」会按字典序随机取到 baron
    "got_the_city_drunk_memory": "coronation_host",
    "injured_in_crowd_crush_at_coronation_memory": "coronation_host",
    "defeated_detractor_in_drinking_contest_memory": "detractor",
    "was_caught_cheating_in_drinking_contest_memory": "detractor",
    # v78-5: 流放三型 (各只有一槽, 登记后 {other} 稳定)
    "exiled_kin_memory": "exile",
    "exiled_by_kin_memory": "banisher",
    "defected_from_kin_memory": "kin",
}

# v32 (问题3): 生母本人持有该记忆时 particip[mother] == 持有人 → 视为无对手方,
# 用 `<type>_no_other` 模板 (不出「A之妻A」)。
_SELF_NO_OTHER_TYPES = {"child_stillborn", "child_premature"}

# v63 (行内定语基准): 句面**已把对手方与本行主语的关系写明**的记忆型 —— 成婚事写
# 「与X成婚」、生育写「添子X/得长女X/之{妻}Y产下死婴」、丧偶写「丧偶，X去世」。
# 这些行里的人名不再插亲缘定语 (否则出「与丈夫X成婚」「得长女女儿X」这类赘语;
# 妻/夫/妾 是单字, 进不了 `biography._KIN_MARK_RE` 的「已写明」判据)。
_REL_STATED_TYPES = frozenset({
    "married", "had_sex", "spouse_died", "child_born", "first_born",
    "twins_born", "child_premature", "child_stillborn",
    # v78-5: 流放三型句面已写明亲属关系 (「放逐其亲属X」/「为亲属X所放逐」),
    # 不登记会出「放逐其亲属其堂弟X」这类叠字
    "exiled_kin_memory", "exiled_by_kin_memory", "defected_from_kin_memory",
})

# v32 (问题3): 需带配偶称谓 ({rel}) 的记忆型
_CONSORT_MEM_TYPES = {"child_stillborn", "child_premature"}

# v31 (问题3): 同伴槽位型记忆 — 参与槽与持有者同一人时该记录退化。
# 存档实测: 妻子的 6 条 had_sex 的 `sex_partner` 就是她自己 (游戏未记对方是谁),
# 旧渲染直接取名成句 → 「公主与公主有私情」。这类记录整条丢弃。
_PEER_SLOT_TYPES = {
    "had_sex", "became_lovers", "became_soulmates", "became_friends",
    "became_rivals", "became_grudge", "became_nemesis", "became_blood_brother",
    "broke_up_lovers", "married",
}

# v31 (问题1): 体况瞬时特质 — 得而复失只是状态回摆 (妻子怀孕三段: 868→869 /
# 872→876 / 878→), 不进「特质履历」; **当前持有仍写入「为人」**,
# 「878年公主怀孕」是有用事实, 只有履历噪声要去掉。
_TRANSIENT_TRAITS = {"pregnant", "ill", "wounded_1", "wounded_2", "wounded_3"}
# v35 (问题5): 疫情类疾病特质 —— 取游戏算好的当代疫名而非特质静态名
# (键取自 common/epidemics/00_epidemics.txt 的 `trait =` 行)。
_DISEASE_TRAITS = frozenset({"smallpox", "bubonic_plague", "typhus", "consumption",
                             "measles", "dysentery", "ergotism"})
# v35 (问题5): 疫情类**死因键** → 疾病特质键 (取动态疫名用)。
_DEATH_DISEASE_REASON = {
    "death_typhus": "typhus", "death_smallpox": "smallpox",
    "death_bubonic_plague": "bubonic_plague",
    "death_consumption": "consumption", "death_measles": "measles",
    "death_dysentery": "dysentery", "death_ergotism": "ergotism",
}

# v34 (问题1, 用户拍板「不留」): 生育能力类特质属**史官不可知**的身体隐微 —
# 「不育」写在《本纪》里等于告诉读者主角的生育力, 而史官只见他子女绕膝。
# 这类特质在**公开档案**(surface) 的「为人」句中整体隐去, 只保留在内部版档案里。
_FERTILITY_TRAITS = frozenset({
    "infertile", "infertile_male", "infertile_female", "sterile",
    "fertile", "fecund", "lustful_fertility",
})

# v31 (问题1): 「为人」句的类别顺序与每类上限 (超限加「等」)
_TRAIT_GROUP_ORDER = ("personality", "education", "lifestyle", "commander",
                      "fame", "health", "childhood", "court_type", "")
_TRAIT_GROUP_LIMIT = 5

# v31 (问题4): 妻室情事脉络的取材类型 → 对方所在参与槽
_AFFAIR_SLOTS = {
    "had_sex": "sex_partner",
    "became_lovers": "new_relation",
    "became_soulmates": "new_soulmate",
    "broke_up_lovers": "old_lover",
    "lover_died": "dead_relation",
}

# v31 (问题7): 这些隐事的 target 即对方当事人 (存档 participants 只列持有人),
# 算「当事人」而非第三方知情者
_SECRET_PARTY_TARGET_TYPES = {"secret_lover", "secret_adultery"}

# v34 (问题2): 乱伦隐事在存档里**不记对方** (`target` 恒为空数组, 双方各持一条),
# 但对方可由「持有人的血亲 ∩ 与持有人的性/情记忆」判定。
# 血亲只认**血缘** (父/母/子女/同胞); 姻亲 (配偶) 不算 — 否则夫妻同房会被写成乱伦。
_SEX_MEM_TYPES = ("had_sex", "became_lovers", "became_soulmates", "developed_crush")
_SEX_MEM_OTHER_KEYS = ("sex_partner", "new_relation", "new_soulmate")

# v42 (问题1): 乱伦主题已并入 style.SECRET_TOPICS (`与{target}乱伦`) —— 旧稿在
# 此处另立 `SECRET_INCEST_TOPIC = "乱伦：与{target}"`, 是全库唯一一条「标签：内容」
# 式隐事主题, 嵌进「有隐事N桩：」成双层冒号。

# v42 (问题2): 「自己」的指代基准 = **记录持有人** (即该隐事句的主语)。
# 旧稿以 `self_cid` (主角 id) 为基准, 家人隐事句的主语是家人、基准却是主角,
# 于是「对方＝主角」被写成「自己」: 欧金尼娅·诺兰的三桩隐事成了
# 「乱伦：与自己」「与自己私通」「实父为自己」, 并被子模型逐字抄进正文。

# 记忆类型 → 取 vars 中的 landed_title (头衔 id)
TITLE_VAR_TYPES = {"lost_title_memory", "ascended_throne_memory"}

# 朝局类记忆类型 (群英录/朝局风云录用, 与 biography.POLITICAL_TYPES 同步)
POLITICAL_TYPES_KEYS = {
    "ascended_throne_memory", "lost_title_memory", "imprisoned",
    "released_from_prison_memory", "escaped_from_prison_memory",
    "became_rivals", "became_grudge",
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


def _house_shi(nm):
    """家格句/立家年表行用的家族称法 (「顿巴斯」→「顿巴斯氏」; 已带氏/家/部者原样)。

    v64: 由 `house_history_lines` 内的局部函数提为模块级 —— 家格句与年表事件
    (`_house_founding_events`) 两处同源, 免得一处写「顿巴斯氏」一处写「顿巴斯」。"""
    if not nm:
        return ""
    return nm if nm.endswith(("氏", "家", "家族", "部")) else f"{nm}氏"


def _year_of(d):
    """日期文本 → 四位数年份 (兼容 '872.1.1' 与 '872年' 两式); 取不到返回 ''。"""
    if d is None:
        return ""
    m = re.match(r"\s*(\d{3,4})", str(d))
    return m.group(1) if m else ""


def date_gap_days(d1, d2):
    """两个游戏日期 (Y.M.D) 的整日差 (d2 − d1); 解析失败返回 None。

    v81 (问题6): 只服务「首见快照距出生 ≤ 400 天」这类**粗判** (存档快照日是
    每年 1月1日), 故按月 30 日、年 365 日折算, 不追求历法精确。"""
    try:
        y1, m1, x1 = (int(x) for x in str(d1).split(".")[:3])
        y2, m2, x2 = (int(x) for x in str(d2).split(".")[:3])
    except Exception:
        return None
    return (y2 - y1) * 365 + (m2 - m1) * 30 + (x2 - x1)


# ---------------------------------------------------------------------------
# v45: 亲缘定语 (「父亲X」「姻亲姊妹Y」)
# ---------------------------------------------------------------------------
# 用户 2026-09-16 拍板:
#   · 词形 = 游戏本地化口径, **有双音节词用双音节词** (父亲/岳父, 不用 父/岳);
#   · 「首次」语义 S1 字面 —— 该名字在本板块任何位置出现过即消费名额;
#   · 基准人 = 该篇传主 (《列传》即好友/仇人本人);
#   · 前配偶不算 (配偶集 = primary_spouse ∪ spouse ∪ concubine, 双向闭包);
#   · 零提示词改动 —— 定语在事实面拼。
# 长幼四词 (兄长/弟弟/姐姐/妹妹) 与「配偶」游戏无键, 由本项目自造 (兜底常量)。
KIN_WORDS = {
    "father":            ("relation_father", "父亲"),
    "mother":            ("relation_mother", "母亲"),
    "son":               ("relation_son", "儿子"),
    "daughter":          ("relation_daughter", "女儿"),
    "brother_older":     ("", "兄长"),
    "brother_younger":   ("", "弟弟"),
    "sister_older":      ("", "姐姐"),
    "sister_younger":    ("", "妹妹"),
    "brother":           ("relation_brother", "兄弟"),
    "sister":            ("relation_sister", "姊妹"),
    "wife":              ("relation_wife", "妻子"),
    "husband":           ("relation_husband", "丈夫"),
    "spouse":            ("", "配偶"),
    "father_in_law":     ("", "岳父"),
    "son_in_law":        ("son_in_law", "女婿"),
    "daughter_in_law":   ("daughter_in_law", "儿媳"),
    "brother_in_law":    ("relation_brotherinlaw", "姻亲兄弟"),
    "sister_in_law":     ("relation_sisterinlaw", "姻亲姊妹"),
    "step_son":          ("relation_stepson", "继子"),
    "step_daughter":     ("relation_stepdaughter", "继女"),
    # ---- v45b: 中式亲属细分 (40 词, 判据见 docs/研究_v45b_中式亲属.md §1.2) ----
    # 组 A 父母之同胞: 伯叔按与父母的生年, 舅/姑/姨按父系/母系与性别
    "uncle_pat_older":   ("", "伯父"),
    "uncle_pat_younger": ("", "叔父"),
    "uncle_mat":         ("", "舅父"),
    "aunt_pat":          ("", "姑母"),
    "aunt_mat":          ("", "姨母"),
    "uncle":             ("relation_uncle", "叔舅"),      # 回落: 长幼不可判
    "aunt":              ("relation_aunt", "姑姨"),        # 回落: 父母边不可判
    # 组 B 同胞之子女: 兄弟之子女 → 侄, 姊妹之子女 → 甥
    "nephew_brother":    ("", "侄子"),
    "niece_brother":     ("", "侄女"),
    "nephew_sister":     ("", "外甥"),
    "niece_sister":      ("", "外甥女"),
    "nephew":            ("NEPHEW", "侄甥"),               # 回落: 同胞性别不可判
    "niece":             ("NIECE", "侄甥女"),
    # 组 C 子女之子女: 子之子女 → 孙, 女之子女 → 外孙
    "grandson_son":      ("GRANDSON", "孙子"),
    "granddaughter_son": ("GRANDDAUGHTER", "孙女"),
    "grandson_daughter": ("", "外孙子"),
    "granddaughter_daughter": ("", "外孙女"),
    "grandson":          ("relation_grandson", "（外）孙"),      # 回落: 中间人性别不可判
    "granddaughter":     ("relation_granddaughter", "（外）孙女"),
    # 组 D 堂表 (姑表算表: 只有伯叔之子女为堂)
    "cousin_pat_brother_older":   ("", "堂兄"),
    "cousin_pat_brother_younger": ("", "堂弟"),
    "cousin_pat_sister_older":    ("", "堂姐"),
    "cousin_pat_sister_younger":  ("", "堂妹"),
    "cousin_mat_brother_older":   ("", "表兄"),
    "cousin_mat_brother_younger": ("", "表弟"),
    "cousin_mat_sister_older":    ("", "表姐"),
    "cousin_mat_sister_younger":  ("", "表妹"),
    "cousin_pat_brother": ("", "堂兄弟"),                  # 回落: 长幼不可判
    "cousin_pat_sister":  ("", "堂姊妹"),
    "cousin_mat_brother": ("", "表兄弟"),
    "cousin_mat_sister":  ("", "表姊妹"),
    "cousin_male":        ("COUSIN_MALE", "堂表兄弟"),      # 回落: 堂/表侧不可判
    "cousin_female":      ("relation_cousin_female", "堂表姊妹"),
    # 组 E 配偶之父母 (按配偶性别取词; 游戏无键者自造)
    "mother_in_law":     ("", "岳母"),
    "husband_father":    ("", "公公"),
    "husband_mother":    ("", "婆婆"),
    # 组 F 同胞之配偶 (按同胞性别 + 长幼取词; 游戏无键者自造)
    "sister_in_law_older":   ("", "嫂"),
    "sister_in_law_younger": ("", "弟媳"),
    "brother_in_law_older":  ("", "姐夫"),
    "brother_in_law_younger": ("", "妹夫"),
    # ---- v80 (点3, 用户 2026-09-27 拍板「任何有亲属关系的角色都要有一个词」) ----
    # 规格见 docs/调研_v80_亲属称谓全覆盖.md §1.2 (41 键净增量)。
    # 词源: 有大写关系键的优先取游戏本地化 (GRANDFATHER/…), 其余自造兜底。
    # 组 H 上行直系: 祖辈 + 曾祖辈 (父系/母系按**第一跳**分, 见 kin_key 5b/5d)
    "grandfather_pat":   ("GRANDFATHER", "祖父"),
    "grandmother_pat":   ("GRANDMOTHER", "祖母"),
    "grandfather_mat":   ("", "外祖父"),
    "grandmother_mat":   ("", "外祖母"),
    "grandfather":       ("relation_grandfather", "（外）祖父"),
    "grandmother":       ("relation_grandmother", "（外）祖母"),
    "great_grandfather_pat": ("GREATGRANDFATHER", "曾祖父"),
    "great_grandmother_pat": ("GREATGRANDMOTHER", "曾祖母"),
    "great_grandfather_mat": ("", "外曾祖父"),
    "great_grandmother_mat": ("", "外曾祖母"),
    "great_grandfather": ("relation_great_grandfather", "（外）曾祖父"),
    "great_grandmother": ("relation_great_grandmother", "（外）曾祖母"),
    # 组 I 祖辈同胞 (连接祖辈 = 祖父/祖母; 外祖辈同胞本轮不做, 见规格 §5.2)
    "granduncle_pat":    ("", "伯祖父"),
    "grandaunt_pat":     ("", "姑祖母"),
    "granduncle_mat":    ("", "舅祖父"),
    "grandaunt_mat":     ("", "姨祖母"),
    "granduncle":        ("", "祖辈叔伯"),
    "grandaunt":         ("", "祖辈姑姨"),
    # 组 J 父母之堂表兄弟姊妹 (我的「堂叔/表姑」一辈)
    "uncle_pat_cousin_older":   ("", "堂伯"),
    "uncle_pat_cousin_younger": ("", "堂叔"),
    "uncle_side_older":         ("", "表伯"),
    "uncle_side_younger":       ("", "表叔"),
    "uncle_mat_cousin":         ("", "表舅"),
    "aunt_pat_cousin":          ("", "堂姑"),
    "aunt_mat_cousin":          ("", "表姑"),
    "aunt_mat_cousin2":         ("", "表姨"),
    # 组 K 同胞之孙 (侄孙/外甥孙)
    "grandnephew_brother": ("", "侄孙"),
    "grandniece_brother":  ("", "侄孙女"),
    "grandnephew_sister":  ("", "外甥孙"),
    "grandniece_sister":   ("", "外甥孙女"),
    "grandnephew":         ("", "侄甥孙"),
    "grandniece":          ("", "侄甥孙女"),
    # 组 L 曾孙辈 (下行三代; 中间人性别定 曾孙/外曾孙)
    "great_grandson_son":      ("GREATGRANDSON", "曾孙"),
    "great_granddaughter_son": ("GREATGRANDDAUGHTER", "曾孙女"),
    "great_grandson_daughter":      ("", "外曾孙"),
    "great_granddaughter_daughter": ("", "外曾孙女"),
    "great_grandson":      ("relation_greatgrandson", "（外）曾孙"),
    "great_granddaughter": ("relation_greatgranddaughter", "（外）曾孙女"),
}

_KIN_TEXT_CACHE = {}

# 史传单字对照 (供「其父/其兄」这类旁称; 定语词形另走 kin_text 的双音节口径)
KIN_SHORT = {
    "father": "父", "mother": "母", "son": "子", "daughter": "女",
    "brother_older": "兄", "brother_younger": "弟",
    "sister_older": "姊", "sister_younger": "妹",
    "brother": "兄弟", "sister": "姊妹",
    "wife": "妻", "husband": "夫", "spouse": "配偶",
    "father_in_law": "岳父", "son_in_law": "女婿", "daughter_in_law": "儿媳",
    "brother_in_law": "姻亲兄弟", "sister_in_law": "姻亲姊妹",
    "step_son": "继子", "step_daughter": "继女",
}


def kin_word_short(key):
    """亲缘键 → 旁称单字 (父/母/兄/姊…); 未收录者回落双音节词。"""
    return KIN_SHORT.get(key) or kin_text(key)


def kin_texts():
    """**词表白名单** (v45b): 全部可出定语词形 = 双音节表 ∪ 史传单字表。

    单一定义处 —— 断言 (「标注词都在词表内」) 与实现同源, 扩表时不会漏改判据。"""
    return {kin_text(k) for k in KIN_WORDS} | set(KIN_SHORT.values())


def kin_text(key):
    """KIN_WORDS 键 → 中文词 (游戏本地化优先, 缺失用兜底常量)。"""
    if not key:
        return ""
    if key in _KIN_TEXT_CACHE:
        return _KIN_TEXT_CACHE[key]
    loc_key, fallback = KIN_WORDS.get(key) or ("", "")
    val = fallback
    if loc_key:
        try:
            v = L.loc(L.table(), loc_key)
            if v and v != loc_key:
                val = v
        except Exception:
            val = fallback
    _KIN_TEXT_CACHE[key] = val
    return val


def _fam_of(cache, cid):
    return ((cache.get("characters") or {}).get(str(cid)) or {}).get("family") or {}


def _rec_of(cache, cid):
    return (cache.get("characters") or {}).get(str(cid)) or {}


def _female_rec(rec):
    """记录性别: True/False; 无记载返回 None (调用方据此回落中性词)。"""
    v = (rec or {}).get("female")
    if v is None:
        return None
    return bool(v)


def _older_rec(ra, rb):
    """ra 是否比 rb 年长; 任一方无生年返回 None。"""
    ba, bb = (ra or {}).get("birth"), (rb or {}).get("birth")
    if not ba or not bb:
        return None
    try:
        return cl.date_key(ba) < cl.date_key(bb)
    except Exception:
        return None


def spouses_now_family(fam, chars=None, spouse_back=None):
    """该 family 记录的**现配偶** id 集 (v45): primary_spouse ∪ spouse ∪ concubine。

    前配偶 (former_spouses/former_concubines) **不算** —— 用户 2026-09-16 拍板;
    反向边由调用方用 `spouse_back` 并入 (缓存里配偶边可能只写在对端记录上,
    见 `Facts._spouse_back_index`)。"""
    out = set()
    for k in ("primary_spouse", "spouse", "concubine"):
        for x in (fam.get(k) or []):
            if isinstance(x, int):
                out.add(x)
    return out


def _married(fam_a, a_id, b_id, chars):
    """a、b 是否**当前**配偶 (双向看: 任一方记录里列出对方即成立; 前配偶不算)。"""
    for k in ("primary_spouse", "spouse", "concubine"):
        if b_id in (fam_a.get(k) or []):
            return True
    fb = ((chars or {}).get(str(b_id)) or {}).get("family") or {}
    for k in ("primary_spouse", "spouse", "concubine"):
        if a_id in (fb.get(k) or []):
            return True
    return False


def kin_rev_index(chars):
    """反向边索引 (v45b): {sib: {cid: [对端…]}, kid: {cid: [对端…]}}。

    缓存里同胞/子女边可能只写在对端记录上 (实测同向缺失不少), 故一律**双向并集**;
    建一次 O(N) 供整次 build 复用 (由 `Facts._kin_rev` 持有)。
    纯函数: 只读角色表。

    **子女反查只认法理父/母 (`father`/`mother`), 不含 `real_father`** ——
    与 v34 的公开谱系口径一致 (实父只在《家室列传》《阴私录》等内部档出现):
    被托卵的孩子在公开篇目里不算「儿子」, 否则会与档案的「子A、B」行自相矛盾
    (实测诺兰档: 黑罗尔德·沙特努瓦 real_father=主角而法理父是别人)。"""
    sib, kid = {}, {}
    for k, rec in (chars or {}).items():
        if not str(k).isdigit() or not isinstance(rec, dict):
            continue
        try:
            cid = int(k)
        except ValueError:
            continue
        fam = rec.get("family") or {}
        for x in (fam.get("siblings") or []):
            if isinstance(x, int) and x != cid:
                sib.setdefault(x, []).append(cid)   # x 的同胞里有 cid
        for x in (fam.get("child") or []):
            if isinstance(x, int):
                kid.setdefault(cid, []).append(x)   # cid 的子女里有 x
        for key in ("father", "mother"):
            for x in (fam.get(key) or []):
                if isinstance(x, int):
                    kid.setdefault(x, []).append(cid)   # cid 是 x 的子女
    return {"sib": sib, "kid": kid}


def kin_key(cache, subject, cid, chars=None, spouse_back=None, rev=None):
    """subject 相对 cid 的**亲缘关系键** (v45/v45b): 'father'/'cousin_pat_brother_older'…

    判据见 `docs/研究_v45_亲缘定语.md` §2.3 与 `docs/研究_v45b_中式亲属.md` §1.2/§2.1;
    **判不出返回 ''** (不猜)。纯函数: 只读缓存 (+ 可选的预建反向索引), 不依赖熔件,
    可秒级断言。判定序 = 血亲优先 (序 A):
      1 度 (父母 → 子女 → 同胞 → 配偶) → 孙辈 → 父母之同胞 → 同胞之子女 → 堂表
      → 配偶之父母 → 女婿/儿媳 → 同胞之配偶 / 配偶之同胞 → 继子女
    词形分两档由调用方取: `kin_text(key)` = 双音节定语词 (父亲/伯父/表姐),
    `KIN_SHORT` = 史传单字 (供「其父」「其兄」这类旁称)。
    subject 为 None、cid 为 None、或二者同一人时返回 ''。"""
    if subject is None or cid is None:
        return ""
    try:
        s, c = int(subject), int(cid)
    except (TypeError, ValueError):
        return ""
    if s == c:
        return ""
    chars = chars if chars is not None else (cache.get("characters") or {})
    if rev is None:
        rev = kin_rev_index(chars)
    rev_sib = rev.get("sib") or {}
    rev_kid = rev.get("kid") or {}
    rs = chars.get(str(s)) or {}
    rc = chars.get(str(c)) or {}
    fs = rs.get("family") or {}
    c_female = _female_rec(rc)
    s_female = _female_rec(rs)

    def _fam(x):
        return (chars.get(str(x)) or {}).get("family") or {}

    def _ids(fam, key):
        return [k for k in (fam.get(key) or []) if isinstance(k, int)]

    def _fath(x):
        f = _fam(x)
        return set(_ids(f, "father")) | set(_ids(f, "real_father"))

    def _moth(x):
        return set(_ids(_fam(x), "mother"))

    def _sibs(x):
        out = set(_ids(_fam(x), "siblings")) | set(rev_sib.get(int(x)) or [])
        out.discard(int(x))
        return out

    def _kids(x):
        return set(_ids(_fam(x), "child")) | set(rev_kid.get(int(x)) or [])

    def _sp(x):
        """x 的现配偶集 (含反向边)。"""
        out = spouses_now_family(_fam(x))
        if spouse_back:
            out |= set(spouse_back.get(int(x)) or [])
        return out

    def _female(x):
        return _female_rec(chars.get(str(x)) or {})

    def _older(a, b):
        """a 是否年长于 b (生年比较); 任一方无生年返回 None。"""
        return _older_rec(chars.get(str(a)) or {}, chars.get(str(b)) or {})

    def _cousin(side, female, older):
        """堂/表词形: side ∈ {'pat','mat',None}; female=c 性别; older=c 是否年长于 s。"""
        if female is None:
            return ""
        if side is None:                      # 堂/表侧不可判 (连接人性别无记载)
            return "cousin_female" if female else "cousin_male"
        pat = side == "pat"
        if older is None:
            if pat:
                return "cousin_pat_sister" if female else "cousin_pat_brother"
            return "cousin_mat_sister" if female else "cousin_mat_brother"
        if female:
            if pat:
                return "cousin_pat_sister_older" if older else "cousin_pat_sister_younger"
            return "cousin_mat_sister_older" if older else "cousin_mat_sister_younger"
        if pat:
            return "cousin_pat_brother_older" if older else "cousin_pat_brother_younger"
        return "cousin_mat_brother_older" if older else "cousin_mat_brother_younger"

    def _sib_blood(x):
        """x 的**血缘同胞** (v80 点3 §2.5①): `family.siblings` ∪ 共享父/母者。

        缓存 `siblings` 会把子女也列进来 (CK3 数据如此), 只读它会让「同父异母的
        伯叔」整支漏掉; 故并上「父/母的其它子女」并剔除自己。"""
        out = set(_sibs(x))
        for _p in _fath(x) | _moth(x):
            out |= _kids(_p)
        out.discard(int(x))
        return out

    def _up_excl():
        """旁系候选的排除集 (v80 点3 §2.3②): 我 / 我的同胞 / 我的后代 /
        这些人的后代 / 我的父与母。

        不排除会出现「我的兄长被判成伯父」「我的胞弟被判成祖辈同胞」这类错判
        (规格探针实测: 祖辈同胞候选里混进了我的同胞)。"""
        out = {int(s)} | _sibs(s) | _kids(s) | _fath(s) | _moth(s)
        for _y in list(out):
            out |= _kids(_y)
        return out

    # 1) 父 / 母 (含实父)
    if c in _fath(s):
        return "father"
    if c in _moth(s):
        return "mother"
    # 2) 子 / 女 (正反两向)
    if c in _kids(s):
        if c_female is None:
            return ""            # 性别不可判 → 不标 (子/女二选一必错一半)
        return "daughter" if c_female else "son"
    # 3) 同胞 + 长幼 (生年缺失 → 回落游戏词「兄弟」/「姊妹」)
    if c in _sibs(s):
        older = _older(c, s)                # c 是否年长于 subject
        if older is None:
            return "sister" if c_female else "brother"
        if c_female:
            return "sister_older" if older else "sister_younger"
        return "brother_older" if older else "brother_younger"
    sp_s = _sp(s)
    # 4) 配偶 (妻子/丈夫; 性别不可判 → 配偶) —— 双向看, 前配偶不算
    if _married(fs, s, c, chars):
        if c_female is None:
            return "spouse"
        return "wife" if c_female else "husband"
    # 5) 孙辈 (我的子女的子女; 中间人性别定孙/外孙)
    for k in sorted(_kids(s)):
        if c in _kids(k):
            if c_female is None:
                return ""
            kf = _female(k)
            if kf is None:
                return "granddaughter" if c_female else "grandson"
            if kf:
                return "granddaughter_daughter" if c_female else "grandson_daughter"
            return "granddaughter_son" if c_female else "grandson_son"
    # 5b) 祖父辈 (v80 点3, 用户: 「任何有亲属关系的角色都要有一个词」):
    #     父之父/母 → 祖父/祖母; 母之父/母 → 外祖父/外祖母。
    #     父系/母系只看**第一跳** (父系链上第一跳之后的每一跳男女皆收) ——
    #     若要求整条链都走 father, 「祖母之父」这一整支会漏掉: 田所档定治的
    #     曾祖母纪静子 (11634) 正是经祖母大和珍子 (16005) 的 `mother` 边找到的。
    for p in sorted(_fath(s)):
        if c in _fath(p):
            return "grandfather_pat"
        if c in _moth(p):
            return "grandmother_pat"
    for m in sorted(_moth(s)):
        if c in _fath(m):
            return "grandfather_mat"
        if c in _moth(m):
            return "grandmother_mat"
    # 5c) 祖辈同胞 (v80 点3): 连接祖辈 (祖父/祖母, 以及曾祖辈) 的**血缘同胞**。
    #     连接祖辈为**男** → 其兄弟 = 伯祖父、其姊妹 = 姑祖母;
    #     连接祖辈为**女** → 其兄弟 = 舅祖父、其姊妹 = 姨祖母; 性别不可判 → 回落。
    #     v80 取舍: 规格 (§5.2) 只要求「祖父/祖母」这一层; 为使「任何亲属都有词」
    #     成立, 这里**多走一代** (曾祖辈的同胞也收) —— 该层中文另有叫法
    #     (曾伯祖父/舅公等) 而不在本轮词表内, 故按同一条规则近似出词, 已在
    #     docs/调研_v80_亲属称谓全覆盖.md §3.2 用例 6 标为「未确认」。
    _ex = _up_excl()

    def _grand_sib_word(g):
        """连接祖辈 g 的同胞 → 词 (c 为外部变量)。"""
        _gf = _female(g)
        if c_female is None:
            return ""                    # 目标性别不可判 → 不标 (与子/女同口径)
        if _gf is None:                  # 连接祖辈性别不可判 → 回落
            return "grandaunt" if c_female else "granduncle"
        if c_female:
            return "grandaunt_pat" if _gf is False else "grandaunt_mat"
        return "granduncle_pat" if _gf is False else "granduncle_mat"

    for p in sorted(_fath(s)):
        for g in sorted(_fath(p) | _moth(p)):        # 祖父 / 祖母
            if c in (_sib_blood(g) - _ex):
                return _grand_sib_word(g)
    for m in sorted(_moth(s)):
        for g in sorted(_fath(m) | _moth(m)):        # 外祖父 / 外祖母
            if c in (_sib_blood(g) - _ex):
                return _grand_sib_word(g)
    # 5d) 曾祖辈 (v80 点3): 父/母 → 祖辈 → 其父/母 (上行三代), 同 5b 只看第一跳。
    for p in sorted(_fath(s)):
        for g in sorted(_fath(p) | _moth(p)):
            if c in _fath(g):
                return "great_grandfather_pat"
            if c in _moth(g):
                return "great_grandmother_pat"
    for m in sorted(_moth(s)):
        for g in sorted(_fath(m) | _moth(m)):
            if c in _fath(g):
                return "great_grandfather_mat"
            if c in _moth(g):
                return "great_grandmother_mat"
    # 6) 父母之同胞: 父系 → 伯父/叔父 (比父生年) 或 姑母; 母系 → 舅父/姨母
    for p in sorted(_fath(s)):
        if c in _sibs(p):
            if c_female is None:
                return ""
            if c_female:
                return "aunt_pat"
            older = _older(c, p)            # c 比 p (父) 年长 → 伯父
            if older is None:
                return "uncle"              # 长幼不可判 → 叔舅
            return "uncle_pat_older" if older else "uncle_pat_younger"
    for p in sorted(_moth(s)):
        if c in _sibs(p):
            if c_female is None:
                return ""
            return "aunt_mat" if c_female else "uncle_mat"
    # 6b) 父母之堂表兄弟姊妹 (v80 点3, 用户点名「堂叔」):
    #     t = 祖辈 (祖父/祖母/外祖父/外祖母) 的**血缘同胞之子女** —— 即我父/母的
    #     堂/表兄弟姊妹, 于我则为堂伯/堂叔/堂姑/表伯/表叔/表姑/表舅/表姨。
    #     堂 ⟺ 连接祖辈是**祖父**且该祖辈同胞为**男** (「父系父之兄弟之子女」);
    #     祖父之姊妹 / 祖母 / 外祖父母 各支 → 表。
    #     长幼: 经父者与**父**比生年 (伯/叔), 经母者不比较 (表舅/表姨无长幼);
    #     长幼不可判时按「当作年长」出词 (与 `uncle` 回落到「叔舅」同性质)。
    _fa = sorted(_fath(s))
    _f0 = _fa[0] if _fa else None
    _cands = []
    for p in _fa:                                    # 父之父母 = 祖父 / 祖母
        for g in sorted(_fath(p)):
            for u in sorted(_sib_blood(g)):
                for t in sorted(_kids(u)):
                    _cands.append((t, "tang" if _female(u) is False else "biao_f"))
        for g in sorted(_moth(p)):
            for u in sorted(_sib_blood(g)):
                for t in sorted(_kids(u)):
                    _cands.append((t, "biao_f"))
    for m in sorted(_moth(s)):                       # 母之父母 = 外祖父 / 外祖母
        for g in sorted(_fath(m) | _moth(m)):
            for u in sorted(_sib_blood(g)):
                for t in sorted(_kids(u)):
                    _cands.append((t, "biao_m"))
    for t, kind in sorted(_cands):
        if t != c or t in _ex:
            continue
        if c_female is None:
            return ""
        if kind == "tang":
            if c_female:
                return "aunt_pat_cousin"             # 堂姑
            older = _older(c, _f0) if _f0 is not None else None
            return "uncle_pat_cousin_younger" if older is False \
                else "uncle_pat_cousin_older"
        if kind == "biao_f":
            if c_female:
                return "aunt_mat_cousin"             # 表姑
            older = _older(c, _f0) if _f0 is not None else None
            return "uncle_side_younger" if older is False else "uncle_side_older"
        return "aunt_mat_cousin2" if c_female else "uncle_mat_cousin"
    # 7) 同胞之子女: 兄弟之子女 → 侄; 姊妹之子女 → 甥
    for sb in sorted(_sibs(s)):
        if c in _kids(sb):
            if c_female is None:
                return ""
            sbf = _female(sb)
            if sbf is None:
                return "niece" if c_female else "nephew"
            if sbf:
                return "niece_sister" if c_female else "nephew_sister"
            return "niece_brother" if c_female else "nephew_brother"
    # 7b) 同胞之孙 (v80 点3): 同胞 → 其子女 → 其孙; 同胞性别定 侄孙/外甥孙。
    for sb in sorted(_sibs(s)):
        for kid in sorted(_kids(sb)):
            if c not in _kids(kid):
                continue
            if c_female is None:
                return ""
            sbf = _female(sb)
            if sbf is None:
                return "grandniece" if c_female else "grandnephew"
            if sbf:
                return "grandniece_sister" if c_female else "grandnephew_sister"
            return "grandniece_brother" if c_female else "grandnephew_brother"
    # 8) 堂表: 父母的同胞之子女 (父之兄弟之子女 → 堂; 父之姊妹 / 母系 → 表)
    for p in sorted(_fath(s)):
        for u in sorted(_sibs(p)):
            if u == s or c not in _kids(u):
                continue
            uf = _female(u)
            side = "pat" if uf is False else ("mat" if uf is True else None)
            return _cousin(side, c_female, _older(c, s))
    for p in sorted(_moth(s)):
        for u in sorted(_sibs(p)):
            if u == s or c not in _kids(u):
                continue
            return _cousin("mat", c_female, _older(c, s))
    # 8b) 曾孙辈 (v80 点3): 子女 → 其子女 → 其孙 (下行三代);
    #     中间人 (子女) 性别定 曾孙/外曾孙; 不可判 → 回落「（外）曾孙」。
    for k in sorted(_kids(s)):
        for gk in sorted(_kids(k)):
            if c not in _kids(gk):
                continue
            if c_female is None:
                return ""
            kf = _female(k)
            if kf is None:
                return "great_granddaughter" if c_female else "great_grandson"
            if kf:
                return "great_granddaughter_daughter" if c_female \
                    else "great_grandson_daughter"
            return "great_granddaughter_son" if c_female else "great_grandson_son"
    # 9) 配偶之父母 (按**配偶性别**取词: 女 → 岳父/岳母, 男 → 公公/婆婆)
    for sid in sorted(sp_s):
        sf = _fam(sid)
        father_side = c in _fath(sid)
        if not father_side and c not in _moth(sid):
            continue
        sf_sex = _female(sid)
        if sf_sex is None:
            # 配偶性别不可判 → 取传主性别的反面 (原版 CK3 为一男一女)
            sf_sex = (not s_female) if s_female is not None else None
        if sf_sex is None:
            return ""                       # 两方性别都不可判 → 不标
        if sf_sex:
            return "father_in_law" if father_side else "mother_in_law"
        return "husband_father" if father_side else "husband_mother"
    # 10) 女婿 / 儿媳 (子女的配偶)
    for k in sorted(_kids(s)):
        if _married(_fam(k), k, c, chars):
            return "daughter_in_law" if c_female else "son_in_law"
    # 11) 同胞之配偶 (嫂/弟媳/姐夫/妹夫, 按同胞性别+长幼) 与 配偶之同胞 (姻亲)
    #     v63 (问题7, 用户 2026-09-24 拍板): **姻亲称谓只由正妻之婚产生** ——
    #     妾 (`concubine`) 与侧室 (`spouse`) 不产生「妹夫/姐夫/嫂/弟媳/姻亲」。
    #     实测: 崔佛娶埃德伯之妹昆伯为**妾**, 旧稿因此把崔佛写成埃德伯的「妹夫」
    #     (「英格兰女王埃德伯被妹夫维京人崔佛·菲利普强迫性交」); 妾婚无此关系。
    #     判据 = 双方 `primary_spouse` 互见 (只看正妻键, 双向)。
    def _primary_spouse(a, b):
        if b in _ids(_fam(a), "primary_spouse"):
            return True
        return a in _ids(_fam(b), "primary_spouse")

    def _primary_spouses(x):
        """x 的正妻/正夫集 (反向边只收对端把 x 记在 `primary_spouse` 上的)。"""
        out = set(_ids(_fam(x), "primary_spouse"))
        if spouse_back:
            for y in (spouse_back.get(int(x)) or []):
                if int(x) in _ids(_fam(y), "primary_spouse"):
                    out.add(int(y))
        return out

    for sb in sorted(_sibs(s)):
        if _primary_spouse(sb, c):
            sbf = _female(sb)
            older = _older(sb, s)           # 同胞比 subject 年长?
            if sbf is not None and older is not None:
                if sbf:
                    return "brother_in_law_older" if older else "brother_in_law_younger"
                return "sister_in_law_older" if older else "sister_in_law_younger"
            return "sister_in_law" if c_female else "brother_in_law"
    for sid in sorted(_primary_spouses(s)):
        if c in _sibs(sid):
            return "sister_in_law" if c_female else "brother_in_law"
    # 12) 继子 / 继女 (配偶的子女, 且不是我的子女)
    for sid in sorted(sp_s):
        if c in _kids(sid) and c not in _kids(s):
            return "step_daughter" if c_female else "step_son"
    return ""


def kin_word(cache, subject, cid, chars=None, spouse_back=None, rev=None):
    """`kin_key` 的**双音节定语词**形态 (v45): 父亲/伯父/表姐/姻亲姊妹…

    用户 2026-09-16 拍板「有双音节词用双音节词」—— 定语一律走这一档;
    旁称 (「其父」) 走 `kin_word_short`。判不出返回 '' (不猜)。"""
    return kin_text(kin_key(cache, subject, cid, chars=chars,
                            spouse_back=spouse_back, rev=rev))


class KinScope:
    """**单个板块**的亲缘定语登记表 (v45)。

    `_article_facts` 是并发调用的（每篇一个线程）, 所以这张表只能是**局部对象**,
    绝不能挂 `Facts` 实例 —— 否则板块之间串味、结果不可复现。
    「首次」语义 (用户拍板): 同一人在本板块只加一次定语; **已带亲缘词**的点名
    (传主档案的家世行「父X」「子A、B」「妻室Y」) 视为已交代, 由 `seed` 预先占用
    名额 —— 于是「裸名先行」处 (朝中要员名录/廷中僚属任免/刺客死者行) 照加,
    「子X」这类既有亲缘行则不重复。
    `subject` = 该篇传主 (《列传》即好友/仇人本人); 传主本人不加定语。"""

    __slots__ = ("subject", "seen", "stats", "held", "tagged")

    def __init__(self, subject=None):
        self.subject = int(subject) if subject is not None else None
        self.seen = set()
        self.stats = {}      # 已加定语 {词: 次数} (计量用)
        self.held = {}       # 家世行已交代、因而未再加的 {词: 次数} (计量用)
        self.tagged = set()  # 已做过行内插词的块名 (档 B 幂等用)

    def seed(self, ids, facts=None):
        """预占名额: 这些人的亲缘**已经写明** (档案家世行), 本板块不再重复加定语。

        返回 self 供串写。`facts` 给了才统计 `held` (计量用, 不影响出词)。"""
        for cid in (ids or []):
            if not isinstance(cid, int):
                try:
                    cid = int(cid)
                except (TypeError, ValueError):
                    continue
            if cid == self.subject or cid in self.seen:
                continue
            self.seen.add(cid)
            if facts is not None:
                w = facts.kin_word_for(cid, self.subject)
                if w:
                    self.held[w] = self.held.get(w, 0) + 1
        return self

    def word_for(self, cid, facts, subject=None):
        """首次出现 → 返回该人的亲缘定语词并占名额; 否则返回 ''。

        v45 (档 B) 的行内插词入口 (与 `mark` 共用一张名额表)。
        v63: `subject` 可覆盖算词基准 —— 句子有自己的主语时 (家人档案/刺客列传
        的逐人条目、隐事持有人的隐事句), 句中**第三方**人名的定语按该主语算,
        否则会把「主角的岳父」插进讲妻子的句子里读成「她的岳父」。
        名额 (`seen`) 仍按板块共用 —— 同一人每板块至多一处定语。"""
        subj = self.subject if subject is None else subject
        if cid is None or subj is None:
            return ""
        try:
            cidi = int(cid)
        except (TypeError, ValueError):
            return ""
        if cidi == subj or cidi in self.seen:
            return ""
        self.seen.add(cidi)
        w = facts.kin_word_for(cidi, subj)
        if not w:
            return ""
        self.stats[w] = self.stats.get(w, 0) + 1
        return w

    def mark(self, cid, base, facts, date=None):
        """给 cid 的称谓 base 加定语 (首次才加); 返回最终文本。"""
        if not base or cid is None or self.subject is None:
            return base
        try:
            cidi = int(cid)
        except (TypeError, ValueError):
            return base
        if cidi == self.subject or cidi in self.seen:
            return base
        self.seen.add(cidi)
        w = facts.kin_word_for(cidi, self.subject)
        if not w:
            return base
        self.stats[w] = self.stats.get(w, 0) + 1
        return f"{w}{base}"


def _disease_dynamic_name(f, cid, typ, year):
    """疾病特质 → **游戏算好的当代疫名** (v35, 问题5)。

    游戏为每场疫情随机取名并写进存档 (`epidemics.database[*].name`), 例如伤寒一律
    显示为「平原热」「丘陵热」「露营热」等 (see common/epidemics/00_epidemics.txt 的
    `name` 块, 其中 `epidemic_terrain_fever` 即
    `[ROOT.Epidemic.GetStartingOutbreakProvince.GetTerrain.GetNameNoTooltip|U]热`);
    而特质静态名 `trait_typhus` 只是「伤寒」。旧稿渲染特质履历时用静态名, 于是
    「第一次在法国得伤寒、第二次在瑞典得伤寒」都写成了「伤寒」, 动态名未生效。

    取法: 在 cache["epidemics"] 里找同型 (type == 疾病特质键) 的疫情, 其存续期
    (`creation_date` … `lost_at`) 覆盖该角色患病起点年 `year` 者;
    优先「玩家属地/所在郡曾被该疫感染」的那一场 (`hit_prov`), 否则取同型中
    起始最晚者。判不出返回 '' (调用方回退静态名, 行为与旧版一致)。"""
    hist = f.cache.get("epidemics") or {}
    if not hist or not typ:
        return ""
    ys = _year_of(year)
    if not ys:
        return ""
    yk = int(ys)
    cands = []
    for rec in hist.values():
        if not isinstance(rec, dict) or rec.get("type") != typ:
            continue
        cd = str(rec.get("creation_date") or "")
        cy_s = _year_of(cd)
        if not cy_s:
            continue
        cy = int(cy_s)
        la = str(rec.get("lost_at") or "")
        ly = int(_year_of(la)) if _year_of(la) else None
        if cy > yk:
            continue
        if ly is not None and ly < yk:
            continue
        cands.append((rec, cy))
    if not cands:
        return ""
    mine = _battlefield_provinces(f, cid)
    def _hit(rec):
        inf = {int(x) for x in (rec.get("infections") or [])
               if isinstance(x, int) or str(x).isdigit()}
        return bool(mine & inf)
    hits = [c for c in cands if _hit(c[0])] if mine else []
    pool = hits or cands
    pool.sort(key=lambda c: c[1])
    return str(pool[-1][0].get("name") or "")


def _battlefield_provinces(f, cid):
    """角色相关省份集 (封地首府 + 驻地 + 当前位置); 判疫情是否触及该角色。"""
    out = set()
    rec = (f.cache.get("characters") or {}).get(str(cid)) or {}
    ld = rec.get("landed") or {}
    for t in (ld.get("domain") or []):
        cap = ((f._lt or {}).get(str(t)) or {}).get("capital")
        if isinstance(cap, int):
            out.add(cap)
    for key in ("domicile_province",):
        v = ld.get(key)
        if isinstance(v, int):
            out.add(v)
    ll = rec.get("last_location") or {}
    if isinstance(ll.get("province"), int):
        out.add(ll["province"])
    try:
        loc = f.character_location_province(cid)
        if isinstance(loc, int):
            out.add(loc)
    except Exception:
        pass
    return out


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


# v81 (问题1, 用户 2026-09-29 拍板): 家族名**按文化/名序组装**的单一出口。
# 旧稿只有一条规则 (biography._house_text: 宗族名以「氏」结尾就直连分家名) ——
# 对**家格词**成立 (藤原 + 北家 = 藤原北家; 源 + 黑子 = 源黑子), 对**地名型家名**
# 就出非语 (平 + 下北沢 = 平下北沢; 施 + 斯卡利茨 = 施斯卡利茨)。四档口径:
#   · 日本 (JAPANESE)                 → 本姓 + 氏 + 家名 (+「家」): 平氏下北沢家;
#                                        家名已带家格词尾 (家/流/氏/…) 者不再补「家」:
#                                        藤原氏式家 (藤原氏の式家)
#   · 中华·朝鲜 (DYNASTY_ALWAYS_FIRST) → 家名已含姓者径作「家名＋氏」(庆州金氏 /
#                                        关中李氏 / 庆州崔氏); 未含姓者「家名＋姓＋氏」
#                                        (斯卡利茨施氏)
#   · 西方·伊斯兰 (其余 / 名序未知)    → 「宗族，家族」(菲利普，顿巴斯 —— 现形不变;
#                                        伊斯兰与西方同为名前姓后, 同此一档)
#   · 宗族名与家族名同字 (创始家)      → 只出该名 (田所 / 诺兰 / 陆氏)
_JAPAN_HOUSE_TAILS = ("家", "流", "氏", "門", "门", "宫", "宮", "院", "寺", "方")


def house_label(dn, hn, order=None, template=None):
    """(宗族名, 家族名, 名序约定, 文化模板) → 全篇统一的家族称法 (v81)。

    `order` 取自 `cache_lib.resolved_name_order` ('' = 西方默认, None = 无从判定;
    两者都走西方档); `template` 目前只作记录, 判据全在名序约定上 —— 日本与中华
    用的正是两个**不同**的约定值 (JAPANESE / DYNASTY_ALWAYS_FIRST), 不必再查文化 id。
    判不出 (dn/hn 皆空) 返回 '' —— 调用方整项略去。"""
    dn = str(dn or "").strip()
    hn = str(hn or "").strip()
    if not hn:
        return house_display(dn)
    if not dn or dn == hn:
        return house_display(dn or hn)
    # 上游 (`_house_names_at`) 给的是**显示形** (单字已加「氏」: 平 → 平氏);
    # 本函数自己补「氏」, 故先取回本姓, 免得拼出「平氏氏下北沢家」。
    dn = dn[:-1] if dn.endswith("氏") else dn
    if order not in cl.EASTERN_NAME_ORDERS:
        return f"{house_display(dn)}，{house_display(hn)}"
    if order == "JAPANESE":
        if hn.endswith(_JAPAN_HOUSE_TAILS):
            return f"{dn}氏{hn}"
        return f"{dn}氏{hn}家"
    # DYNASTY_ALWAYS_FIRST: 中华/朝鲜 —— 家名已含姓者不再叠姓 (庆州金氏 / 关中李氏)
    if dn in hn:
        return f"{hn}氏"
    return f"{hn}{dn}氏"


# v30: 事实层「无据」占位词 — 族属不详/信仰不详/官制不详/（特质不详）/（死因不详）等
# 一律视为无料, 由调用方整句略去 (修复方案_菲利普4.md 问题4: 缺料按语一律不进提示词,
# 模型看不到「未载/不详」这类词, 也就无从照抄)。
_UNKNOWN_MARKS = ("不详", "无考", "未载", "不可考", "无从", "失考")


def is_unknown(word):
    """无料判定: 空串或含「不详/无考/未载/不可考/无从/失考」者为无据。"""
    s = str(word or "")
    return (not s) or any(m in s for m in _UNKNOWN_MARKS)


# v29 (问题4): 「传主行迹」句首传主称谓剥离 — 块内主语恒为传主, 名字重复无信息。
# 「868年9月25日，勇敢者程岩的亲属安南经略使程士庸去世。」→「…，亲属安南经略使程士庸去世。」
_SUBJ_DATE_RE = re.compile(r"^\d+年(?:\d+月\d+日)?，")


def _strip_subject_prefix(text, label, alt_labels=None):
    """删去句首传主称谓 (含其后的「的」); 无可删处原样返回。

    v32 (问题3): 夭折句形如「<传主>之妻<生母>产下死婴。」, 只删传主名会留下悬空的
    「之妻…」; 故配偶称谓一并删去, 让生母自己作主语 (「<生母>产下死婴。」)。
    v64 (问题5): `alt_labels` = 备选剥离键 (按序试) —— 勋号随时点变化, 档案称谓
    与事件当日的主语形态可能只差一个勋号前缀, 备选键使那句仍能省主语。"""
    if not text or not label:
        return text
    cands = [label] + [x for x in (alt_labels or []) if x]
    m = _SUBJ_DATE_RE.match(text)
    head = m.group(0) if m else ""
    rest = text[len(head):]
    hit = None
    for cand in cands:
        if rest.startswith(cand):
            hit = cand
            break
    if hit is None:
        return text
    rest = rest[len(hit):]
    if rest.startswith("的"):
        rest = rest[1:]
    else:
        rm = re.match(r"^之(?:妻|夫|妾|情人|男宠)", rest)
        if rm:
            rest = rest[rm.end():]
    return head + rest


# v52 (问题6, 用户拍板): 原 `_LEVEL_WORDS`（"一阶/二阶…"）已删 —— 游戏没有这套
# 档位序数术语（游戏概念只有「特质路线 / 特质经验」），档位由年份跨度与按档改名的
# 特质名承担; 见 `_trait_display` / `trait_level_history`。


def _trait_level_name(key, xp):
    """按角色在该特质各轨道上的 XP 求**当前档名** (v32)。

    条件表来自 `localization.build_trait_names` 的 `level_names` (逐 `triggered_desc`
    把 trigger 的 has_trait_xp 条款与 desc 配对)。条款未写 `track` 时按该特质的轨道
    推定 (单轨简写 `track = {}` 的轨名＝特质键)。求不到返回 `''` (上层回退基础名)。

    起因: 旧实现取 name 块里第一个 desc, 而游戏把**最高档**名写在最前 —— 54 个按 XP
    换名的特质全部显示顶档名 (马克龙主角 reveler XP=0 却写成「传奇的狂欢者」)。"""
    rows = (L.trait_names().get("level_names") or {}).get(key)
    if not rows or not isinstance(xp, dict):
        return ""
    tracks = [r.get("track") for r in
              ((L.trait_track_table().get("tracks") or {}).get(key) or [])]
    for row in rows:
        vals = []
        for c in row.get("clauses") or []:
            tk = c.get("track") or (tracks[0] if len(tracks) == 1 else key)
            try:
                v = float(xp.get(tk) or 0)
            except (TypeError, ValueError):
                v = 0.0
            n = float(c.get("value") or 0)
            op = c.get("op")
            vals.append({">=": v >= n, "<=": v <= n, "=": v == n,
                         "!=": v != n, ">": v > n, "<": v < n}.get(op, False))
        if vals and (any(vals) if row.get("any") else all(vals)):
            return row.get("key") or ""
    return ""


def _trait_name(table, key, xp=None):
    """特质 key → 中文: **当前档名** (v32) → 基础名键 (v29) → trait_<key> → <key> →
    兜底表; 未知返回 '' (跳过, 不外泄 key)。

    v29: 旅行者 (lifestyle_traveler) 等特质的显示名由 common/traits 的 name 块指定
    (desc = trait_traveler_1), 不再因 `trait_<key>` 缺键而整条丢失。
    v32: 有 XP 轨道者先按角色实际 XP 取档名 (无 XP 数据时用基础名, 不再固定顶档名)。
    v34 (问题4): 全链落空时记进 `_TRAIT_NAME_MISSES`, 由 `trait_name_miss_report()`
    落日志 — 此前是静默丢弃, 新 Mod 特质 (Carnalitas) 消失而无从察觉。"""
    if not key:
        return ""
    mapped = (L.trait_names().get("traits") or {}).get(key)
    cands = []
    lv = _trait_level_name(key, xp)
    if lv:
        cands.append(lv)
    if mapped:
        cands.append(mapped)
    cands += [f"trait_{key}", key]
    for cand in cands:
        v = L.loc(table, cand)
        if v and not v.startswith(("$", "[")):
            return v
    fb = TRAIT_ZH.get(key, "")
    if not fb:
        _TRAIT_NAME_MISSES[key] = _TRAIT_NAME_MISSES.get(key, 0) + 1
    return fb


# v34 (问题4): 未解析出中文名的特质 key → 出现次数 (静默丢弃的可见化)
_TRAIT_NAME_MISSES = {}


def trait_name_miss_report(clear=True):
    """未解析出中文名的特质清单 (问题4 的告警出口)。
    返回 {trait_key: 出现次数}; `clear=True` 时清空累计。"""
    out = dict(_TRAIT_NAME_MISSES)
    if clear:
        _TRAIT_NAME_MISSES.clear()
    return out


def _daynum(d):
    """'935.11.5' → 天序号 (年×372+月×31+日, 短跨度够用)。"""
    try:
        y, m, dd = (int(x) for x in str(d).split(".")[:3])
        return y * 372 + m * 31 + dd
    except Exception:
        return 0


def _day_before(d):
    """日期串的前一日 (v42 问题7: 卒日锚点用); 解析失败原样返回。"""
    try:
        y, m, dd = (int(x) for x in str(d).split(".")[:3])
        p = datetime.date(y, m, dd) - datetime.timedelta(days=1)
        return f"{p.year}.{p.month}.{p.day}"
    except Exception:
        return d


def _hist_value_at(hist, date, key):
    """沿革表 `[{from, <key>}]` → date 当日之值 (v47, 供文化/信仰沿革共用)。

    与 `_culture_id_at` 同语义: 早于首点的日期取首点 (族属/信仰沿革的首点即
    已知最早之值); 无日期或无表返回 None (由调用方回退现值)。"""
    pts = [h for h in (hist or []) if h.get("from")]
    if not date or not pts:
        return None
    dk = cl.date_key(date)
    pick = pts[0]
    for h in pts:
        try:
            if cl.date_key(h["from"]) <= dk:
                pick = h
            else:
                break
        except Exception:
            break
    return pick.get(key)


def _death_reason(table, reason, public=False):
    """死因 key → 中文: v11 先查雅化表 (游戏腔/坏文本), 再本地化, 最后兜底表。
    v75: public=True 取**世人的说法** —— 点破式雅化 (如 death_mysterious →
    「被秘密谋杀」) 让位给游戏本地化原词 (`PUBLIC_DEATH_ZH`)。"""
    if not reason:
        return "去世"
    if public:
        v = PUBLIC_DEATH_ZH.get(reason)
        if v:
            return v
    v = FLAVOR_DEATH_ZH.get(reason)
    if v:
        return v
    v = L.loc(table, reason)
    if v and "[" not in v and "$" not in v and v != "死于":
        return v
    return DEATH_REASON_ZH.get(reason, "去世")








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


# v75 (凶手点名): 死因**自带公开性** —— 游戏 `common/deathreasons/*.txt` 里标了
# `public_knowledge = yes` 的死因, 游戏本身就把「谁下的手」算作人人皆知:
#   · death_execution      (00_event_deaths.txt:150-153)
#   · death_murder_known    (:367-368)
# 其余死因 (death_murder / death_mysterious / death_disappearance / death_raid_estate /
# death_hunting_accident) 都没有这一条 —— 它们是否公开取决于存档旗标
# `dead_data.killer_known` (见 `Facts.killer_is_public`)。逐条取证见
# docs/方案_v75_凶手点名收口.md §2.1。
_PUBLIC_DEATH_REASONS = frozenset({"death_execution", "death_murder_known"})

# v75 (凶手点名): **公开档**专用死因文案。v16 的雅化表 (`style.FLAVOR_DEATH_ZH`)
# 是全知视角 —— 它明写「点破为谋杀」(`style.py:640-642`: death_mysterious →
# 「被秘密谋杀」), 只配《刺客列传》。世人在存档里看到的是游戏本地化值
# (death_reasons_l_simp_chinese.yml: death_mysterious = 「神秘死亡」)。
# 只列与世人说法不同的那一条; 其余死因的现有中文不含凶手信息, 原样沿用。
PUBLIC_DEATH_ZH = {
    "death_mysterious": "神秘死亡",
}


def _death_clause(table, reason_key, killer, name_of, public=False):
    """死因 → 自然中文短句 (含施事者嵌入)。
    reason_key: 原始死因 key; killer: 凶手/行刑者/对手角色 id 或 None;
    name_of: 角色 id → 名字。返回「被XXX谋杀」「被XXX秘密谋杀」「与XXX决斗而亡」
    「身首异处，凶手为XXX」或纯死因短句 (无施事或非动作型死因)。
    v75: public=True 取世人说法 (`PUBLIC_DEATH_ZH` 优先于点破式雅化)。"""
    reason = _death_reason(table, reason_key, public=public)
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

# v52 (问题1): 「出身自定、无谱系」的存档 flag (见 Facts.is_custom_start) ——
# 脚本化无地冒险者/自建角色: 存档不给父母, 也没有 ruler_designer_characters 条目。
_NO_GENEALOGY_FLAGS = {
    "do_not_generate_starting_family",
    "special_laamp_char",
    "has_scripted_appearance",
}

# v16: 王子词覆盖 — 本地化表把封建王国之女写成「郡主」(唐制亲王之女的东亚
# 封号), 西式王国/帝国之女在传记里一律写「公主」; 天朝制的 皇女/郡主/公女
# 属刻意东亚风味, 不在覆盖之列 (见 _prince_word)。
_PRINCE_WORD_OVERRIDE = {
    "princess_kingdom_feudal_chinese": "公主",
}


# v55 (问题6): 排序键里「该日期为空」的兜底值 —— 必须与 `cl.date_key` 的返回**同型**
# (元组), 且其序为最大 (空日期排在本组最后)。旧稿三处写整数 `10 ** 12`, 与同组内
# 另有日期的行的元组键相比时抛 `TypeError: '<' not supported between instances of
# 'tuple' and 'int'` (沙米尔 944 第 2 个十年实测: 囚禁集群里同 rank 者一有空 since 即崩,
# facts 构建阶段失败 → 十年传记永不生成)。`cl.date_key` 对非法输入同样返回 (9999,0,0)。
_DATE_KEY_MAX = (9999, 0, 0)


def _date_ord(d):
    """日期近似天序 (year*372 + (month-1)*31 + day)。
    只用于「相差 N 天以内」的宽松判断 (v34b 头衔事件日核对), 不做精确历法运算 —
    月末跨月会多算 1~2 天, 对宽松阈值无影响。非法输入返回极小值。"""
    try:
        y, m, dd = (int(x) for x in str(d).split(".")[:3])
    except (TypeError, ValueError):
        return -10 ** 9
    return y * 372 + (m - 1) * 31 + dd


class Facts:
    """一次 build_facts 的上下文: 缓存 + melt + 名字/头衔/本地化解析。
    as_of: 传记数据截止日期 (十年传记 = 十年末; 终传/在世 = 最后档期)。
    非空时 官职/称号/历任/时间线/朝局 均只取该日期之前的事实 (v11)。
    decade (v17): 十年传记序号 (1,2,3…), 非空时时间线/概览/摘要/刺客列传
    只收本十年 (as_of−10年, as_of] 的事件 (修复方案_汤利五问题.md 决策 1/2)。"""

    def __init__(self, cache, melt, names_path, as_of=None, decade=None,
                 nickname_override=None, cfg=None, campaign=None):
        self.cache = cache
        self.melt = melt
        self.names_path = names_path
        self.as_of = as_of
        self.decade = decade
        # v44 (问题2): 同战役全部传主缓存 {player_id: cache} — 传主链的前任/后任
        # 亲缘与名号由此取; 缺省只有本传主自己 (不影响其余事实)。
        self.campaign = dict(campaign or {})
        if cache.get("player_id") is not None:
            self.campaign.setdefault(cache.get("player_id"), cache)
        # v41: 配置 (开关类口径的唯一来源; 缺省读 config.json)
        self.cfg = cfg if cfg is not None else llm.load_config()
        # v41: Carnalitas 事件好感族是否进事实面 (默认关, 见 llm.DEFAULT_CONFIG)
        self._show_carnal_opinions = bool(
            (self.cfg or {}).get("carnal_opinions"))
        # v20: 按时代绰号覆盖 {cid: 绰号} — 十年传记重跑时绰号取该十年末熔件,
        # 不随最新档漂移 (878 时代「嗜血者」不会被 888 档的「屠狼者」覆盖)
        self._nick_override = dict(nickname_override or {})
        self._lt = ((melt.get("landed_titles") or {}).get("landed_titles") or {})
        self._tl = melt.get("traits_lookup") or []
        self._chars = cl.all_characters(melt)
        self.table = L.table()
        self.provmap = L.province_map()
        # v29: 数值档位表 (虔诚/威望/影响力/功勋的 defines 阈值) 与职位显示名变体表
        self._bands = (L.currency_levels() or {}).get("bands") or {}
        self._cp_variants = L.court_positions()
        # v30: 游戏 flavorization 条目表 (统治者称呼/头衔名后缀的权威来源)
        self._flavor = FZ.table()
        # v30: 授予人祭的教义键集 (处决方式「献祭」的可用门, 见 execution_method)
        try:
            self._sacrifice_doctrines = L.doctrines_granting("human_sacrifice_active")
        except Exception:
            self._sacrifice_doctrines = set()
        self._council_tasks = L.council_tasks()
        # v80 (点5): 主教称谓保序臂表 + 议会席位名链 (游戏 GetActualBishopTitle /
        # `council_positions.name` 的解析结果) —— 宫廷司祭的教会词与席位名的权威来源。
        try:
            self._bishop_titles = L.bishop_titles()
        except Exception:
            self._bishop_titles = {"arms": []}
        try:
            self._council_names = L.council_names()
        except Exception:
            self._council_names = {"positions": {}}
        self._title_by_key = {}
        for tid, t in self._lt.items():
            if not isinstance(t, dict):  # v7: none 条目防护
                continue
            k = t.get("key")
            if k:
                self._title_by_key[k] = int(tid)
        self._gov_cache = {}
        self._regnal_cache = {}  # v17: 世系编号 (cid, tid, date) -> 序号
        self._mem_date_cache = {}  # v34b: 头衔记忆事实日 (tid, cid, d, reason, type)
        self._dyn_hist_cache = {}  # v66: 逐档动态名沿革 (本缓存 + 同战役其它传主)
        self._label_cache = {}   # v28b: 人物称谓 (cid, date, style) -> 文本
        # v45 (档 B): 事件句构造期的称谓出词登记 (见 log_names/index_names)
        # 登记栈**按线程**分份 —— 板块期并发调用 (`biography.py` 的 ThreadPool)
        # 时, 别人的出词不得混进本行 (混进就会把定语插错地方)。
        self._tls = threading.local()
        self.name_index = {}     # 行文本 -> [[cid, label], …] (按出词顺序)
        # v63 (行内定语基准): 行文本 -> **本行主语** cid (句子讲的是谁)。
        # 板块期插亲缘定语时, 句中第三方人名按它算词 —— 否则会把「主角的岳父」
        # 插进讲妻子的句子里, 读成「她的岳父」(菲利普2: 于尔莎受业于岳父乱发哈拉尔,
        # 而乱发哈拉尔正是她的生父)。无主语的行 (年表外的多方言情句等) 不登记,
        # 板块期回落旧口径 (按本篇传主算词)。
        self.line_owner = {}
        # v63: 行文本 -> [已写明关系的对手方 cid, …] —— 句面自带的亲缘 (成婚/添子/
        # 丧偶/夭折), 板块期不再给这些人插定语 (见 `_REL_STATED_TYPES`)。
        self.line_stated = {}
        # v16: 游戏关系原因 (opinions.active_opinions 索引, 惰性构建)
        self._opinion_index = None
        # v50: 缓存里的关系缘由 (cache["relation_reasons"], 惰性构建) —— 熔件里
        # 该关系条目已随一方死亡/关系解除消失时, 用它回退 (见 relation_reasons)
        self._cached_opinion_idx = None
        # v56 (§10): 熔件 opinions 的**全对**索引 (不过滤主角, 第三方对的缘由用)
        self._any_opinion_idx = None
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
        # v53: 日期感知后缓存键改为 (cid, date)
        self._vassal_ids = set()
        for _k, _c in ((melt.get("vassal_contracts") or {}).get("database") or {}).items():
            if isinstance(_c, dict) and _c.get("vassal") is not None:
                try:
                    self._vassal_ids.add(int(_c["vassal"]))
                except Exception:
                    pass
        self._indep_cache = {}
        self._purge_dates_map = {}
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
        # v41 (问题1/2): 头衔**取得方式**与前一持有人 —— 历任阶段行要写
        # 「1086年1月1日自海因里希·萨利安手中夺得神圣罗马帝国巴西琉斯」,
        # 而 _holder_intervals 只保留 (gain, loss, loss_type), gain 的事件类型
        # (conquest/created/inheritance/appointment…) 与失主被丢掉, 于是历任
        # 只剩「1086年任X」, 模型只能自己编登位经过。
        self._gain_reason = {}     # (cid, tid, gain_date) -> reason
        self._gain_prev = {}       # (cid, tid, gain_date) -> 前一持有人 id
        _ao = cl.date_key(as_of) if as_of else None
        for _tid, _seq in self._title_seqs.items():
            cur = None
            gain = None
            prev = None
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
                        cur, gain, prev = None, None, None
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
                            cur, gain, prev = None, None, None
                        continue
                    if cur is not None and gain is not None:
                        self._holder_intervals.setdefault(cur, {}).setdefault(
                            _tid, []).append((gain, _d, _typ or ""))
                    self._gain_reason[(_hid, _tid, _d)] = _typ or ""
                    if prev is not None and prev != _hid:
                        self._gain_prev[(_hid, _tid, _d)] = prev
                    prev = _hid
                    cur, gain = _hid, _d
            if cur is not None and gain is not None:
                self._holder_intervals.setdefault(cur, {}).setdefault(
                    _tid, []).append((gain, None, ""))
        # v41 (问题6): 共治者 (co-ruler) —— 存档 diarchies.database 的
        # co_* 条目 + 角色变量 use_co_ruler_title。两者缺一, 游戏就不把
        # 「共治」加进该人称谓 (common/flavorization/00_title_holders.txt
        # 的 co_ruler_male: flag = use_co_ruler_title)。
        self._diarchies = []
        for _v in ((melt.get("diarchies") or {}).get("database") or {}).values():
            if not isinstance(_v, dict):
                continue
            _t = str(_v.get("type") or "")
            if not _t.startswith("co_"):
                continue
            _l, _d2 = _v.get("liege"), _v.get("diarch")
            if not isinstance(_l, int) or not isinstance(_d2, int):
                continue
            self._diarchies.append({
                "liege": int(_l), "diarch": int(_d2), "type": _t,
                "start": str(_v.get("start_date") or ""),
            })
        self._diarchies.sort(key=lambda x: cl.date_key(x["start"] or "9999.9.9"))
        self._co_ruler_flag = set()   # 带 use_co_ruler_title 的角色 id
        for _cid, _c in self._chars.items():
            if not isinstance(_c, dict):
                continue
            _vars = ((_c.get("alive_data") or {}).get("variables") or {}).get("data")
            for _e in _vars or []:
                if not isinstance(_e, dict) or _e.get("flag") != "use_co_ruler_title":
                    continue
                _dd = _e.get("data")
                if isinstance(_dd, dict) and _dd.get("identity"):
                    try:
                        self._co_ruler_flag.add(int(_cid))
                    except (TypeError, ValueError):
                        pass
                break
        # v41 (问题5): 宗族主支索引 {dynasty_id: house_id} —— **只用于判断
        # 「该角色的分家是否与宗族同名」**(初始家族必与宗族同名), 不写进事实面。
        self._dyn_first_house = {}
        _dyn_house = (melt.get("dynasties") or {}).get("dynasty_house") or {}
        for _h, _e in _dyn_house.items():
            if not isinstance(_e, dict):
                continue
            _did = _e.get("dynasty")
            if _did is None:
                continue
            try:
                _did = int(_did)
            except (TypeError, ValueError):
                continue
            _fd = str(_e.get("found_date") or "9999.9.9")
            _hit = self._dyn_first_house.get(_did)
            if _hit is None or cl.date_key(_fd) < cl.date_key(_hit[1]):
                self._dyn_first_house[_did] = (int(_h), _fd)
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
        # v52 (问题1): 无谱系判据扩展 —— 「自定义开局」之外还有**脚本化无地冒险者**:
        # 斯卡利茨档 15403 既不在 ruler_designer_characters 里, 存档也没有父/母记录,
        # 但 `alive_data.variables` 带 do_not_generate_starting_family / special_laamp_char
        # / has_scripted_appearance 三个 flag。旧判据漏掉这一档, 于是本纪开篇的
        # 「家族渊源」位无料可写 —— 模型把总纲里「孩子的母亲」当成了他的母亲。
        for _cid, _c in self._chars.items():
            if not isinstance(_c, dict):
                continue
            try:
                _i = int(_cid)
            except (TypeError, ValueError):
                continue
            _fd = _c.get("family_data") or {}
            if _fd.get("father") or _fd.get("mother"):
                continue
            _fam = (((self.cache.get("characters") or {}).get(str(_i)) or {})
                    .get("family") or {})
            if _fam.get("father") or _fam.get("mother"):
                continue
            _flags = set()
            for _e in (((_c.get("alive_data") or {}).get("variables") or {})
                       .get("data") or []):
                if isinstance(_e, dict) and _e.get("flag"):
                    _flags.add(str(_e["flag"]))
            if _flags & _NO_GENEALOGY_FLAGS:
                self._custom_starts.add(_i)
        # v13: 姓名渲染缓存 (一次 build_facts 内缓存不可变)
        self._name_cache = {}
        self._tpl_memo = {}

    # ---- 名字 ----
    def name(self, cid, date=None):
        """角色 id → 显示名 (v13 统一出口): 父名制文化 → 名·父名
        (崔佛·富兰克林松, 父名替代家族名); 其余文化按名序 (东方姓在前, 西方名·姓)。
        文化缺失 (玩家/死者) 时经亲属链推断, 详见 cache_lib.display_name。
        v44 (问题1): date 传本篇截止日 → 家族名取该日沿革之值 (私生女另立家族 /
        家族改名后, 早年篇用当年之名, 末档篇用今名); 缺省取熔件现值。
        结果按 (cid, date) 缓存 (同一次 build_facts 内缓存不可变)。"""
        if cid is None:
            return ""
        ck = (cid, date or "")
        c = self._name_cache.get(ck)
        if c is not None:
            return c
        c = cl.display_name(self.cache, cid, melt=self.melt,
                            names_path=self.names_path, chars=self._chars,
                            memo=self._tpl_memo, date=date)
        self._name_cache[ck] = c
        return c

    def name_or(self, cid, fallback="某人", date=None):
        """角色显示名 (取不到时用史书式的「某人」占位 — v28b: 原「一位人物」口语且
        偏现代; 称谓出口 person_label 对占位一律返回 '', 不把占位写进称谓)。"""
        n = self.name(cid, date=date)
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

    # v34b: 头衔历史「另有其主」判定 — 与游戏 character_memories_1.txt 的
    # `var:landed_title = { any_past_holder = { this != scope:owner } }` 同义。
    # 供 reason=created 分档 (首建「创建」/ 废弃后重立「重建」) 与测试断言用。
    def title_had_other_holder(self, tid, cid, date=None):
        """头衔 tid 在 date (含) 之前是否另有主人 (holder 存在且 ≠ cid)。
        history 兼容三种取值: 裸 id / {type, holder} / 同日事件列表;
        holder 为 None (无主 destroyed 条目) 不计。无 history 时返回 False。"""
        return self.title_prev_other_holder(tid, cid, date) is not None

    def title_prev_other_holder(self, tid, cid, date=None):
        """头衔 tid 在 date (含) 之前最后一位 ≠ cid 的持有人 id; 无则 None。"""
        if tid is None or cid is None:
            return None
        hist = (self._lt.get(str(tid)) or {}).get("history")
        if not isinstance(hist, dict) or not hist:
            return None
        limit = cl.date_key(date) if date else None
        found = None
        for d in sorted(hist, key=lambda x: cl.date_key(x)):
            if limit is not None and cl.date_key(d) > limit:
                continue
            v = hist[d]
            for e in (v if isinstance(v, list) else [v]):
                h = e.get("holder") if isinstance(e, dict) else e
                if h is None:
                    continue
                try:
                    hid = int(h)
                except (TypeError, ValueError):
                    continue
                if hid != int(cid):
                    found = hid
        return found

    def created_verb_kind(self, tid, cid, date=None):
        """reason=created 的出词分档 (v53): first / restored / founded。

        无前主 → first「创建」; 前主同宗族 → restored「重建」;
        前主异宗族且 hegemon (h_) → founded「开创」(天朝宣称天命);
        其余有前主的非霸权头衔仍 restored, 以免波及公国创建。"""
        prev = self.title_prev_other_holder(tid, cid, date)
        if prev is None:
            return "first"
        my_d = self._dynasty_of_cid(cid)
        prev_d = self._dynasty_of_cid(prev)
        if my_d is not None and prev_d is not None and my_d == prev_d:
            return "restored"
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        if key.startswith("h_"):
            return "founded"
        return "restored"

    # v54 (问题4): 年表标题记忆闸的两条判据
    _TENURE_ZERO_DAY_TOL = 2   # 记忆日与 title history 事件日的容差 (游戏次日才落记忆)
    _MINISTER_KEY_PREFIX = "e_minister_"

    def is_landless_office_title(self, tid):
        """无地官署头衔? (三省六部/御史台/枢密院, v54)

        游戏定义在 `common/landed_titles/02_china.txt` 写 `landless = yes`，但**存档的
        landed_titles 条目不落该字段**（实测 melt_924：`e_minister_of_rites` 无 landless/
        definite_form 键，而 `x_nf_*` 家业有）—— 故按 key 前缀判定，与 v53 戏剧块同判据。"""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        return key.startswith(self._MINISTER_KEY_PREFIX)

    def title_rank_since_at(self, cid, date):
        """角色在 date 的 (最高头衔层级 rank, 该头衔的执政起始日)。

        v54 (问题3d): 同日囚禁集群折叠后的**取名排序**用 —— 用户规则
        「只显示头衔最高，按执政时间排序前 5 人」。无头衔返回 (0, '')。
        v68 (问题5): 层级走 `_eff_rank` —— 仅持世族庄园者按 0 级 (与营地同档),
        家业不参与与真领地的层级比较。"""
        if cid is None or not date:
            return 0, ""
        try:
            _tier, tid = self._primary_title_at(cid, as_of=date)
        except Exception:
            return 0, ""
        if tid is None:
            return 0, ""
        rank = self._eff_rank(tid)
        since = ""
        for (g, _l, _lt) in (self._hold_intervals(cid, date) or {}).get(tid) or []:
            if g and (not since or cl.date_key(g) > cl.date_key(since)):
                since = g
        return rank, since

    def title_tenure_zero_day(self, cid, tid, date):
        """该头衔在 date 这次取得是否为「零日在位」(v54 问题4)。

        天朝制天子造衔即封人（`create_title_and_vassal_change` → 同日 `change_title_holder`）
        与三省六部置官同形：title history 同日 `created/本人` → `appointment/朝臣`，
        持有区间 gain == loss。这种「在位 0 日」的得衔是**封拜**，不是本人的任期，
        年表不该写「重建X王国」。记忆日与事件日容差 `_TENURE_ZERO_DAY_TOL` 天。"""
        if cid is None or tid is None or not date:
            return False
        for (gain, loss, _lt) in (self._hold_intervals(cid) or {}).get(tid) or []:
            if not gain or not loss:
                continue
            if _date_ord(gain) != _date_ord(loss):
                continue
            if abs(_date_ord(gain) - _date_ord(date)) <= self._TENURE_ZERO_DAY_TOL:
                return True
        return False

    # v34b: 头衔得失句的**事件日** — 游戏在头衔变动次日才落记忆
    # (title_event.9900 的 cooldown=1 天), 故 creation_date 常晚 0~1 天;
    # title history 的条目日期才是事件当天 (柳特佩特: d_salerno 历史 874.4.25 /
    # 记忆 874.4.26)。其余记忆仍以 creation_date 为事实日。
    _TITLE_DATE_NEAR_DAYS = 31   # 事件日与记忆日相差上限 (宽松天序, 防误配久远旧事)

    def mem_date(self, cid, mem):
        """记忆在事实面出句用的日期 (v34b): 头衔得失记忆取 title history 事件日,
        取不到时回退 creation_date; 其余记忆一律 creation_date。"""
        d = mem.get("creation_date") or ""
        mtype = mem.get("type")
        if not d or mtype not in TITLE_VAR_TYPES:
            return d
        tid = None
        reason = ""
        for v in mem.get("vars") or []:
            if v.get("flag") == "landed_title" and v.get("identity"):
                tid = v.get("identity")
            elif v.get("flag") == "reason":
                reason = str(v.get("value") or "")
        if tid is None:
            return d
        if mtype == "lost_title_memory" and reason == "migration":
            # v66: migration 失衔记忆的 `landed_title` 恒记最初那块郡 → 事件日映射不到
            # (相差远超 31 天), 年表只能退到记忆日, 与历任行差一天。先归位再取事件日。
            _rt = self.migration_lost_title(
                cid, d, (mem.get("participants") or {}).get("new_holder"))
            if _rt is not None:
                tid = _rt
        key = (tid, cid, d, reason, mtype)
        hit = self._mem_date_cache.get(key)
        if hit is None:
            hit = self._title_event_date(tid, cid, d, reason,
                                         lost=(mtype == "lost_title_memory")) or d
            self._mem_date_cache[key] = hit
        return hit

    def _title_event_date(self, tid, cid, mem_date, reason="", lost=False):
        """头衔 tid 在 mem_date (含) 前的最近一条历史事件日。
        先认 `type == reason` 的条目 (destroyed 失去条目的 holder 是原主也能命中),
        无同类条目再按持有侧兜底 (得: holder==cid; 失: holder!=cid);
        命中日期与记忆日相差超过 `_TITLE_DATE_NEAR_DAYS` 视为误配, 返回 ''。"""
        hist = (self._lt.get(str(tid)) or {}).get("history")
        if not isinstance(hist, dict) or not hist:
            return ""
        mk = cl.date_key(mem_date)
        typed = side = None
        for d, v in hist.items():
            dk = cl.date_key(d)
            if dk > mk:
                continue
            for e in (v if isinstance(v, list) else [v]):
                h = e.get("holder") if isinstance(e, dict) else e
                typ = (e.get("type") or "") if isinstance(e, dict) else ""
                if reason and typ == reason and (typed is None or dk > typed[0]):
                    typed = (dk, d)
                if h is None:
                    continue
                try:
                    hid = int(h)
                except (TypeError, ValueError):
                    continue
                ok = (hid != int(cid)) if lost else (hid == int(cid))
                if ok and (side is None or dk > side[0]):
                    side = (dk, d)
        for cand in (typed, side):
            if cand and 0 <= _date_ord(mem_date) - _date_ord(cand[1]) \
                    <= self._TITLE_DATE_NEAR_DAYS:
                return cand[1]
        return ""

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
        nm = self.name_or(cid, date=date)
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
    def _title_government(self, tid, date=None):
        """头衔在 date 的政体: **该日时任持有者**的政体; 缺失沿 de_facto_liege
        上溯取该日时任领主的政体。

        v41 (问题1) 关键修正: 旧实现只取持有者**末档**的
        `landed_data.government`, 与 date 无关 —— 于是封建期的神罗封臣
        (1087–1094, 游戏内显示公爵/伯爵) 一律被取成末档的
        `administrative_government`, 层级词与称谓词全变成军区/分区/将军。
        实测 (logs/probe_v41_player_gov_hist.txt): 主角 1087–1094 是
        `feudal_government`, 1095 起才 `administrative_government`;
        游戏自己缓存的渲染串 (autosave.ck3, date=1096.7.5 / 1101.6.2 /
        1101.6.17) 对被囚的蒂埃里II 一律写「伯爵」。
        政体史取自 cache["char_government_history"] (逐档变化点)。"""
        date = date or self.as_of
        ck = (tid, date)
        if ck in self._gov_cache:
            return self._gov_cache[ck]
        gov = ""
        seen = set()
        cur = str(tid)
        while cur and cur not in seen:
            seen.add(cur)
            t = self._lt.get(cur) or {}
            if not t:
                break
            holder = self._holder_at_or_now(t, cur, date)
            if isinstance(holder, int):
                gov = self._character_government_or_earliest(holder, date)
                if gov:
                    break
            liege = t.get("de_facto_liege")
            cur = str(liege) if liege is not None else None
        # v62: 日本最高头衔 (天皇座/日本帝国) 补一层**头衔侧**政体 —— 持有者政体史
        # 取不到时 (藤原良房 858–879 的 e_japan 任期早于缓存窗口) 由头衔自己的
        # history_government 定词: japan_administrative_government = 律令制 (关白),
        # japan_feudal_government = 惣領制 (幕府将军)。**仍是游戏数据的政体值, 不按年代**。
        if gov == "" and \
                ((self._lt.get(str(tid)) or {}).get("key") or "") in self._JAPAN_TOP_TITLE_KEYS:
            gov = self._title_government_hist(tid, date) \
                or (self._lt.get(str(tid)) or {}).get("history_government") or ""
        self._gov_cache[ck] = gov
        return gov

    def _title_government_hist(self, tid, date=None):
        """头衔历史里 date (含) 之前**最后一个显式记录的政体**; 无则 ''。

        v62: 日本最高头衔的政体兜底用它 —— 存档的 title history 条目在政体变更那天会带
        `government` 字段 (本体 `history/titles/e_japan.txt:68-71` 1167 年即 `japan_feudal_government`),
        故即便持有者逐档政体史缺失 (早于缓存窗口), 也能按**游戏自己的政体记录**取词,
        而不是拿末档政体冒充早期、更不是按年代猜。"""
        t = self._lt.get(str(tid)) or {}
        hist = t.get("history") or {}
        if not isinstance(hist, dict):
            return ""
        ao = cl.date_key(date) if date else None
        best_d, best_g = None, ""
        for d, e in hist.items():
            if not isinstance(e, dict):
                continue
            g = e.get("government") or ""
            if not g:
                continue
            dk = cl.date_key(d)
            if ao is not None and dk > ao:
                continue
            if best_d is None or dk >= best_d:
                best_d, best_g = dk, g
        return best_g

    def _gov_for_word(self, cid, tid, date):
        """称谓取词用的政体 (v80 点4 —— 按**游戏口径**重排, 不再上溯领主)。

        游戏侧: 政体是**逐角色**的存档属性 (`landed_data.government` / 逐档
        `char_government_history` / 卒档 `dead_data.government`); flavorization 的
        `governments` 在**持有者本人**身上求值 (`common/flavorization/_flavourization
        .info:210-216`), 日式 `special = holder` 条目一律 `top_liege = no`
        (`10_tgp_japan_flavorization.txt:226-229`), 全库取词**从不**按领主政体给
        封臣取词 (依据见 docs/调研_v80_封臣政体判定.md §1/§3)。

        旧稿①先取头衔侧政体, 而 `_title_government` 会沿 `de_facto_liege` 上溯到
        领主 —— 于是「律令制关白 + 惣領制封臣」组合下, 封臣的称谓按**领主**的律令制
        取词 (田所定治档: 六角继子 902–921 被写成「下总国司」, 游戏作「下总武士团
        女士」; 919 与 923+ 因上溯取不到才落回本人政体, 这就是那个非单调分界)。

        新顺序 (保留既有两层救援):
          ① 本人该日逐档政体 (`_character_government`)
          ② 本人逐档史**最早一档** (早于史起点者按已知最早称呼 —— 海因里希 1056)
          ③ 卒档 `dead_data.government` (已死且无逐档史者, 日期不晚于卒日)
          ④ **仅** 日本最高头衔 (`e_japan` / 高御座) 用头衔自身的政体记录
             (`_title_government_hist` / `history_government`); 那是**头衔**的开局
             政体标量, 不是持有者政体, 只在该头衔上作兜底
          ⑤ 取不到 → '' (调用方退通用层级词)。"""
        gov = self._character_government(cid, date) if cid is not None else ""
        if gov:
            return gov
        hist = self._gov_history(cid)
        if hist:
            # date 早于该角色政体史起点: 按**已知最早**的政体称呼 (与族属沿革
            # `_hist_value_at` 的「早于首点取首点」同口径)。旧实现此处返回通用词,
            # 于是海因里希 1056–1073 的神罗任期被写成「前神圣罗马帝国皇帝」,
            # 而按文化+政体应为 `emperor_feudal_male_german`=凯撒。
            first = hist[0].get("government") or ""
            if first:
                return first
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        dd = (rec.get("death") or {}).get("date")
        if not dd:
            dd = (self._chars.get(str(cid)) or {}).get("death") or {}
            dd = dd.get("date") if isinstance(dd, dict) else None
        if dd and (not date or cl.date_key(date) <= cl.date_key(dd)):
            gov = ((self._chars.get(str(cid)) or {}).get("dead_data") or {}) \
                .get("government") or ""
            if gov:
                return gov
        if tid is not None:
            _t = self._lt.get(str(tid)) or {}
            if (_t.get("key") or "") in self._JAPAN_TOP_TITLE_KEYS:
                gov = self._title_government_hist(tid, date) \
                    or _t.get("history_government") or ""
                if gov:
                    return gov
        return ""

    def _holder_at_or_now(self, title, tid, date):
        """头衔在 date 的持有者; date 晚于末档时用熔件当前 holder。"""
        if date is not None:
            h = self.holder_at(int(tid), date)
            if isinstance(h, int):
                return h
        h = title.get("holder")
        return int(h) if isinstance(h, int) else None

    def _gov_history(self, cid):
        """角色的逐档政体史 (v47; v80 点4 改为**合并**多份缓存的观测)。

        政体史是逐档观测出来的, 每份缓存只记自己经历过的那些人
        (docs/研究_v47_统治者头衔动态.md §3)。旧稿「本缓存有就整份返回」会遮蔽
        **更早**的观测 —— 田所定治档: `player_59838.json` 里六角继子的史起于
        923.1.1, 而同战役 `player_38649.json` 里她的史起于 **902.1.1**; 于是
        902–921 取不到本人政体, 退成领主的律令制词「国司」
        (docs/调研_v80_封臣政体判定.md 额外发现①)。"""
        if cid is None:
            return []
        merged = {}
        for src in [self.cache] + list((self.campaign or {}).values()):
            if not isinstance(src, dict):
                continue
            for h in ((src.get("char_government_history") or {}).get(str(cid))
                      or []):
                if not isinstance(h, dict):
                    continue
                d = h.get("date") or ""
                g = h.get("government") or ""
                if d and g:
                    merged.setdefault(d, g)
        return [{"date": d, "government": merged[d]}
                for d in sorted(merged, key=cl.date_key)]

    def _character_government(self, cid, date=None):
        """角色在 date 的政体 (v41): 逐档政体史优先, 熔件现状兜底。

        史由 cache["char_government_history"] 提供 (cache_lib 逐档记变化点);
        date 早于该角色史起点、且早于末档时, 返回 '' —— 宁可不取词
        (调用方回退通用词), 也不拿末档政体冒充历史。"""
        if cid is None:
            return ""
        hist = self._gov_history(cid)
        if hist and date:
            dk = cl.date_key(date)
            hit = ""
            for h in hist:
                if h.get("date") and cl.date_key(h["date"]) <= dk:
                    hit = h.get("government") or ""
                else:
                    break
            if hit:
                return hit
            # date 早于史起点: 视为该角色史起点前的政体不可知
            if hist[0].get("date") and cl.date_key(hist[0]["date"]) > dk:
                return ""
        # 兜底: 熔件现状 (date 未给, 或该角色无政体史而熔件确有记录)
        if date:
            last = self.cache.get("last_date")
            if last and cl.date_key(date) < cl.date_key(last):
                return ""
        c = self._chars.get(str(cid)) or {}
        return (c.get("landed_data") or {}).get("government") or ""

    def _character_government_or_earliest(self, cid, date):
        """角色在 date 的政体; 早于逐档政体史起点时, **仅当天朝链政体**取已知最早值。

        v54 (问题1b): 斯卡利茨档马丁的 `char_government_history` 起点是 919.1.1，
        而 910/918 的任期全在起点之前 —— `_character_government` 按 v41 纪律返回 ''
        （「宁可不取词, 也不拿末档政体冒充历史」），头衔层级词于是退成通用 王国/帝国，
        与同一天的官职词（`_gov_for_word` 有 v47 兜底，出「节度使/观察使」）自相矛盾。
        天朝制在 TGP 全期是**同一个制度**（不随时间演化），故这一档按已知最早值回填;
        封建→行政这类**会变的**政体仍返回 ''，v41 的诺兰反例不动
        （详见方案 §9 风险处置与 `_dead_flavor_consistent` 的既有纪律）。"""
        gov = self._character_government(cid, date)
        if gov or not date:
            return gov
        hist = self._gov_history(cid)
        if not hist:
            return ""
        first = hist[0].get("government") or ""
        return first if first in self._CELESTIAL_CHAIN_GOVS else ""


    # v80 (点4): 政体前缀归一**只对层级前缀键**生效 ——
    # `count_feudal_male_japanese`(总领) 这类键的政体段与 `japan_feudal_government`
    # 相差一个 `japan_` 前缀, 归一后才能认下; 而 `spouse_administrative_female_japanese`
    # (游戏给「关白之妻」烘的键 = 女士) 这类**非官职**键若也被归一认下,
    # `official_title` 的 flavor 支会返回裸词「女士」(实测 大和忠子 16151 由
    # 「越中国司」退成「女士」) —— 故这类键仍按旧口径判, 落回头衔侧取词。
    _GOV_NORM_RANK_PREFIXES = ("count_", "duke_", "king_", "emperor_",
                               "baron_", "hegemon_")

    @staticmethod
    def _gov_prefix_norm(p):
        """政体前缀归一 (v80 点4)。

        日式两政体的键前缀是 `japan_feudal` / `japan_administrative`, 而
        flavorization 键里的政体段写作 `feudal` / `administrative`
        (`count_feudal_male_japanese` / `count_administrative_male_japanese`) ——
        不归一就会把游戏**自己烘死**的日式职称键一律判成「与政体不自洽」而拒收
        (实测 43829 / 33589170 的 `dead_data.flavor` 全是 `count_feudal_male_japanese`
        = 总领, 却退成律令制「国司」, 见 logs/v80_gov_probe3.txt)。"""
        s = str(p or "")
        return s[len("japan_"):] if s.startswith("japan_") else s

    def _dead_flavor_consistent(self, fkey, cid, date):
        """存档烘死的职称键 (`dead_data.flavor`) 与该日政体是否自洽 (v41, 问题1)。

        键形如 `<层级前缀>_<政体前缀>_<性别>[_文化]` (duke_administrative_male_byzantine_group);
        取键里第一段与第三段之间的政体前缀, 与该日 `_character_government(cid, date)`
        的政体前缀比对。日期缺失或该日政体不可知时**不采信** (返回 False) ——
        该键是角色死亡时按末档政体烘死的, 用在早年就是错词。

        v68 (问题2): 逐档政体史取空时补两条**同源**证据, 二者都只在此人政体史沉默时生效:
        ① **卒时窗口** (anchor 与卒日相差 ≤1 天; `_anchor_date` 把 ≥卒日的日期折到卒前一日)
           → 用同一时刻烘死的 `dead_data.government`;
        ② **头衔侧政体** (仅 `h_` 霸权级, 且该日此人正是该头衔的持有者)
           → 用头衔自己记录的政体 (`_title_government_hist` 或 `history_government`)。
        死亡窗口与霸权级之外一律仍按逐档政体史, v41 的诺兰反例 (1082 事件 ≪ 卒 1101,
        其逐档史在 1073 起就有封建政体) 不受影响。"""
        if not fkey or date is None:
            return False
        parts = str(fkey).split("_")
        if len(parts) < 3:
            return True
        gov_prefix = "_".join(parts[1:-1]) if len(parts) > 3 else parts[1]
        # 键里可能带文化后缀 (…_byzantine_group), 取到 _male/_female 为止
        for anchor_word in ("male", "female"):
            if anchor_word in parts:
                i = parts.index(anchor_word)
                gov_prefix = "_".join(parts[1:i])
                break
        # v80 (点4): 只对层级前缀键做日式政体前缀归一 (见 `_GOV_NORM_RANK_PREFIXES`)
        _norm = str(fkey).startswith(self._GOV_NORM_RANK_PREFIXES)

        def _eq_gov(x, y):
            if _norm:
                return self._gov_prefix_norm(x) == self._gov_prefix_norm(y)
            return x == y

        cur = self._character_government(cid, date)
        dd = (self._chars.get(str(cid)) or {}).get("dead_data") or {}
        ddate = dd.get("date")
        # v69: 卒时窗口内,**烘死的 flavor 与同一时刻烘死的 `dead_data.government`
        # 自洽即可认下** (不必等逐档史取空)。为什么: 逐档政体史对非本缓存角色是
        # 「借用同战役其它传主缓存」的**单份**观测 (`_gov_history`), 若借到的那份
        # 只覆盖早年, 就会把几十年前的旧值当成卒时政体 —— 奄美珉 (66463) 实测:
        # 借用的是 38665 缓存里 919.1.1 的 `feudal_government`, 而他 950.6.1 已建
        # 天命改行天朝制, 卒时键 `hegemon_celestial_male_chinese`(皇帝) 于是被判
        # 不自洽, `_office_word` 落回无条件兜底 `hegemon`(45) = 霸主 —— 《刺客列传》
        # 亲缘行写成「夫和霸主青蛙珉·奄美」。本判据只做**单向**放行 (与 flavor 前缀
        # 相符才 True), 故不会把原本 True 的判成 False; 卒时窗口之外仍只认逐档史。
        if ddate and abs(_date_ord(date) - _date_ord(ddate)) <= 1 \
                and (dd.get("government") or ""):
            if _eq_gov(L.government_prefix(dd["government"]), gov_prefix):
                return True
            if not cur:
                cur = dd["government"]
        # 该日政体不可知 (早于逐档政体史起点) 时不采信烘死的键 ——
        # 它是末档政体算的, 用在早期只会把封建期的公爵写成将军。
        if not cur:
            # v68 (问题2) ①: **卒时窗口**内改用同源的 `dead_data.government` 自证 ——
            # 它与 `dead_data.flavor` 是游戏在卒时一起烘死的一对值, anchor 恰为卒时
            # (或卒前一日) 时用这一对值才是忠实的。奄美珉卒 951.1.14, 本战役缓存的
            # 逐档政体史自 955.1.1 起 (`char_government_history["66463"]` 为空),
            # 逐档史取空 ⇒ 旧稿弃用正确的 `hegemon_celestial_male_chinese`(皇帝),
            # `_office_word` 落到无条件兜底 `hegemon`(45)=霸主; 同期的奄美靖卒 963
            # 落在窗口内, 本来就走 flavor 出「和皇帝」—— 同一头衔只因卒年而异词。
            if ddate and abs(_date_ord(date) - _date_ord(ddate)) <= 1:
                cur = dd.get("government") or ""
        if not cur:
            # v68 (问题2) ②: **头衔侧政体**自证 —— **仅霸权级 (h_)** 且该日此人确实
            # 持有那枚霸权头衔时, 用头衔自己记录的政体 (h_china 全程
            # `history_government = celestial_government`) 认下烘死的键。
            # 为什么需要它: ① 只覆盖「卒时」, 而生前的事迹行 (奄美靖 954.5.3 任命
            # 夔州观察使、格尔木噶玛 963.2.22 任命刑部宣抚使) 按事件日取值,
            # 逐档史同样取空 ⇒ 一律退成「女霸主」, 与游戏显示的「女皇帝」不符。
            # 为什么只认 h_: 层级词还有专属条目 (封建公爵=公爵/行政公爵=将军) 的分叉,
            # 那类必须逐档史说了算 (v41 诺兰反例); 霸权级的无条件兜底条目就是霸主,
            # 故只在 h_ 上补这一层, `title()` 的层级词不受影响 (唐 不会变唐皇朝)。
            want = None
            for pfx, rk in (("hegemon_", 6), ("emperor_", 5), ("king_", 4),
                            ("duke_", 3), ("count_", 2), ("baron_", 1)):
                if str(fkey).startswith(pfx):
                    want = rk
                    break
            if want is not None:
                ptid = None
                try:
                    _pt, ptid = self._primary_title_at(cid, as_of=date)
                except Exception:
                    ptid = None
                if ptid is not None and self._eff_rank(ptid) == want:
                    tt = self._lt.get(str(ptid)) or {}
                    if (tt.get("key") or "").startswith("h_"):
                        cur = self._title_government_hist(ptid, date) \
                            or tt.get("history_government") or ""
        if not cur:
            return False
        return _eq_gov(L.government_prefix(cur), gov_prefix)

    def title(self, tid, date=None, site=False, site_cid=None):
        """头衔 id → 中文名 + 动态层级词合并: '复兴党流亡委员会' / '开罗伯爵领' /
        '埃及王国' / '图伦苏丹国' / '阿拔斯哈里发国' / '宋大路' / '中华天朝'(霸权级)。
        v41: date 锚点 — 层级词按该日持有者政体取 (封建期「公国」/ 行政期「军区」)。
        名字取值: **该日动态名**（specific_title_name → title_history_names 国号 →
        custom → name → 本地化表 → key）; 无地营地 (x_) 只给名字。
        v54 (问题2): 名字改走 `_name_at_date` —— 旧稿只读静态 `custom/name`，
        于是天朝国号（h_china/e_lingnan 的 `title_history_names`）永远取不到，
        918 年该叫「桂」的头衔被写成默认名「岭南」（模型据此写出「受任岭南帝国」）。
        v54 (问题1b): 持有者取**该日期时任者**（旧稿一律用末档 holder），层级词收口到
        `_title_tier_word`（天朝链：皇帝兼领=国 / 臣子受任=路）。
        v8: 头衔名与层级词直接合并 (布列塔尼公国), 名字已含层级词时不追加
        (神圣罗马帝国); 霸权级 h_ 仅天朝制启用「天朝」词 (罗马帝国等不加后缀)。
        v8.1: 伊斯兰统治者 (最高领主) 的国名按游戏同规则显示为「家族+层级词」——
        动态国名不存于存档 (k_egypt 静态名仍为「埃及」, 游戏运行时拼出),
        按 持有者信仰→伊斯兰 + 家族名 + 层级 (k_→苏丹国, e_/h_→哈里发国/帝国
        依是否兼任哈里发) 复现。
        v66 (D1-a/窄口径): `site=True` 时取名口换 `_site_name` (【用地名】, 按档取
        「主角占领它之前那一档」的动态名), 并跳过两处 `specific` 早退; 层级词与其余
        分支逐字不变。**默认 False**, 故既有调用点行为不动 (政权名继续跟人走)。"""
        if tid is None:
            return ""
        t = self._lt.get(str(tid)) or {}
        key = t.get("key") or ""
        tnd = t.get("title_name_data") or {}
        # v54: 动态国号优先 (title_history_names) —— 静态 custom/name 只作兜底
        if site:
            name = self._site_name(tid, cid=site_cid, date=date)
            # v66: 游戏给过显示名 (游牧/宗族命名领域) → 该名即完整显示名, 不叠层级词
            # (与 v26 的 `specific` 早退同口径); 否则照旧走层级词链。
            if self._dyn_named(tid):
                return name
        else:
            name = self._name_at_date(tid, date) \
                or (tnd.get("custom") or "").strip() \
                or (tnd.get("name") or "").strip() \
                or L.loc(self.table, key) or key
        if key.startswith("x_"):  # 无地营地/教团等特殊头衔: 只给名字
            return name if site else (self._specific_name(tid) or name)
        # v68 (问题5): 世族庄园 (`c_nf_`/`d_nf_`) 同判 —— 家业头衔是无地家业,
        # 只给名字, 不叠层级词 (旧稿 `title(16851)` = 「张氏州府」, 家业被当州府)。
        if self._is_estate_title(tid):
            return name
        # v52 (问题2): 无地冒险者营地 (`d_laamp_*`) 的层级词取游戏键
        # `<tier>_landless_adventurer_camp` (= 营地), **任何日期**都不落到通用
        # 「公国」—— 旧稿 866 年取不到政体时写出「私生子大队公国」。
        if self.title_kind(tid) == "camp":
            w = self._camp_tier_word(tid)
            return f"{name}{w}" if w and not _STATE_SUFFIX_RE.search(name) else name
        # v13: 朝廷职司 (尚书省六部/御史台/枢密院, e_minister_*) — 官职非诸侯,
        # 只给名字 (吏部/御史台), 不追加「帝国/行台」层级词。
        if key.startswith("e_minister_"):
            return name
        # v75: 虚位御座只给官职词 (名 + 层级词会写出游戏机械串「高御座府」)
        _tw = self.throne_word(tid)
        if _tw:
            return _tw
        # v26: 动态头衔名 (游牧「可萨田所部」/宗族命名「马扎尔」) 即游戏显示名,
        # 优先于伊斯兰国名与层级词后缀。
        # v66: `site=True` 且该头衔有过动态名时, `_site_name` 已在上方直接返回 ——
        # 末档粘滞名不再抢答; 无动态名者照旧落到下列层级词链 (用地名 + 层级词)。
        if not site:
            specific = self._specific_name(tid)
            if specific:
                return specific
        rn = self.realm_name(tid)  # v8.1: 伊斯兰统治者动态国名优先
        if rn and not site:
            return rn
        tier = ""
        for pfx, tv in L.TIER_KEY_OF_PREFIX.items():
            if key.startswith(pfx):
                tier = tv
                break
        if tier:
            # v54 (问题1b): 层级词按该日**时任持有者**取 (旧稿传末档 holder,
            # 于是 910 年的任期按 924 年的持有者判独立性/文化/最高领主)
            holder = self._holder_at_or_now(t, tid, date)
            # v80 (点4): 政体取**持有者本人**的 (游戏的 flavorization `governments`
            # 在 Context Character 上求值; 旧稿用头衔侧政体会沿 de_facto_liege
            # 上溯到领主, 把惣領制封臣写成律令制词)
            gov = self._gov_for_word(holder, tid, date)
            word = ""
            if not (key.startswith("h_") and gov != "celestial_government"):
                word = self._title_tier_word(tier, holder, tid, gov, date)
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

    # v54 (问题1b): 走「天朝层级词链」的政体 —— 与 `*_celestial_chinese_*` 条目
    # `governments` 列表同集。**不含 administrative_government**：行政制自己有
    # 军区/分区/行省/督军区等带 governments 条件的条目，不该被天朝词覆盖。
    _CELESTIAL_CHAIN_GOVS = {"celestial_government", "meritocratic_government",
                              "steppe_admin_government"}

    def _celestial_chain_word(self, tier, government, independent):
        """天朝层级词链: 皇帝兼领=国 / 臣子受任=路 (v54)。

        游戏 `*_celestial_chinese_independent` 条目带 `name_lists = { name_list_han }`，
        非汉人天子（斯卡利茨档马丁是捷克人）落不进，于是退到无条件通用条目
        `kingdom`(45)=**王国** / `empire`(100)=**帝国** / `duchy`=公国 —— 与 v38
        「皇帝兼领=国、臣子受任=路」的定规冲突，也是用户问题 1b 的直接成因。
        本项目对天朝词早已采「与文化无关」口径（`_office_word`：诺斯伯爵在中国亦为刺史），
        故此处直接查天朝链键，不经 flavorization 的姓名系门。不适用返回 ''。"""
        if government not in self._CELESTIAL_CHAIN_GOVS:
            return ""
        if tier == "hegemon":
            key = "hegemony_celestial_chinese"
        elif independent and tier in ("empire", "kingdom", "duchy"):
            key = f"{tier}_celestial_chinese_independent"
        else:
            key = f"{tier}_celestial_chinese_vassal"
        v = L.loc(self.table, key)
        if v and not v.startswith("$") and not v.startswith("["):
            return v
        return ""

    def _title_tier_word(self, tier, cid, tid, government, date,
                         independent=None):
        """头衔层级词统一收口 (v54)。

        顺序:
          ① flavorization 的**专属**条目（带 `governments` 条件）—— 行政制军区/分区、
             诺斯雅尔国、天朝观察使/都护府、可汗国等，一律按游戏规则优先；
          ② 命中**通用条目**（无 governments，如裸 `kingdom`/`empire`/`duchy`）时，
             政体属天朝链则改用天朝链词（国/路/军/镇/州府/行台/皇朝）—— 见
             `_celestial_chain_word`；
          ③ 本地化表的政体层级词（缺失回退通用 王国/帝国/公国/伯爵领/堡/皇朝）。"""
        if independent is None:
            independent = self._is_independent(cid, date) if cid is not None else True
            if independent is None:
                independent = False
        if cid is not None:
            fk = self._flavor_key("title", tier, cid, tid=tid, gov=government,
                                  date=date)
            if fk:
                e = (FZ.table().get("entries") or {}).get(fk) or {}
                if e.get("governments"):
                    v = L.loc(self.table, fk)
                    if v and not v.startswith("$") and not v.startswith("["):
                        return v
        w = self._celestial_chain_word(tier, government, bool(independent))
        if w:
            return w
        return L.tier_word(self.table, government, tier)

    def _tier_word_at(self, tid, government, independent=False, cid=None, date=None):
        """头衔层级词 (v11): 天朝制独立王国用「国」(青徐国), 其余沿用政体层级词
        (皇朝/路/镇/州府…), 缺失回退通用词。

        v41 (问题1): **先走 flavorization 的 `type = title` 条目**（游戏
        `TITLE_TIERED_NAME = "$NAME$$TIER"` 里的 `$TIER$` 就是它）, 再退
        天朝制独立王国特例与政体层级词表。行政制的「军区／分区／督军区」、
        诺斯的「雅尔国」等文化/政体专属层级词由此按游戏规则取到,
        而不再依赖 `tier_word` 里那张把**封臣契约俸禄档**当层级词的错误回退表
        (见 logs/research_admin_titles.md)。
        v54 (问题1b): 三级顺序收口到 `_title_tier_word`（专属条目 → 天朝链 → 政体词）。"""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        tier = ""
        for pfx, tv in L.TIER_KEY_OF_PREFIX.items():
            if key.startswith(pfx):
                tier = tv
                break
        if not tier:
            return ""
        # v52 (问题2): 营地层级词走游戏键 (营地), 不吃 flavorization 的封建层级词
        if self.title_kind(tid) == "camp":
            return self._camp_tier_word(tid)
        return self._title_tier_word(tier, cid, tid, government, date,
                                     independent=independent)

    def _custom_name(self, tid):
        """玩家自定义头衔名 (v67): `title_name_data.custom`, 无则 ''。

        游戏口径: 自定义头衔窗口的「名称」栏 (`TITLE_NAME_FIELD` = 名称,
        `game/localization/simp_chinese/gui/title_view_l_simp_chinese.yml:154`)
        落在 `custom`, 它就是该头衔的显示名 —— 游戏自己拿它当称名比对
        (`has_custom_title_name` / `custom_title_name`, 见
        `game/common/scripted_triggers/10_tgp_triggers.txt:69-81`), 存档信封的
        `meta_data.meta_title_name` 也认它 (卡尔 932/934 档 = 「葛洛夫帮」)。
        故 `specific_title_name` / `name` 只是**没被自定义时**的生成名。"""
        t = self._lt.get(str(tid)) or {}
        return ((t.get("title_name_data") or {}).get("custom") or "").strip()

    def _has_reign_history(self, tid):
        """该头衔的显示名是否由**国号更名史**给出? (v68 问题3)

        游戏 `$NAME$` 取值顺序 (子代理调研 `docs\\调研_头衔动态名与霸主皇帝.md` §1.4,
        含 `game/` 原文与全档统计) 是:
        `custom` → `localization_key` → `title_history_names[≤date]` → `specific_title_name`
        → 静态 `name`。故带 `dynn_title_*` 更名史 / `localization_key` 非空的头衔
        (h_china 唐→中华→和→毕→越→元、d_ziqing 契丹→元) 的显示名取自国号;
        其 `specific_title_name` 是引擎按**当前持有者宗族**另算的生成名, 在天朝 `h_china`
        上已经过期且不再刷新 (975/976/978 三档逐字未变 = 「库曼顿巴斯部」, 而游戏
        信封 (`meta_title_name`) 显示「元」)。此时生成名整个让位。

        无更名史的游牧毡帐/营地/宗族命名领域 (`k_dzungaria`/`d_chah`/`c_uman`/`x_d_laamp_*`)
        `localization_key` 为空、更名史里无 `dynn_title_*` → 返回 False, 生成名照旧参战
        (v26/v66/v67 的口径与验收全不动)。"""
        tnd = (self._lt.get(str(tid)) or {}).get("title_name_data") or {}
        if (tnd.get("localization_key") or "").strip():
            return True
        for h in (tnd.get("title_history_names") or []):
            if isinstance(h, dict) and \
                    str(h.get("name") or "").startswith("dynn_title_"):
                return True
        return False

    def _specific_name(self, tid):
        """游戏算好的动态头衔名 (v26): 游牧/宗族命名领域的领域名, 如
        c_khortytsia 的「可萨田所部」、k_croatia 的「马扎尔」。静态 name
        (也勒克河/克罗地亚) 只是地名, 与游戏内显示不符。无则返回 ''。

        v67: 该头衔**带自定义名**时返回 '' —— 生成名在游戏里本就不显示 (见
        `_custom_name`), 让调用方回到 custom 与其更名史 (v52「营地本名」口径)。
        v68 (问题3): 该头衔**有国号更名史**时同样返回 '' (见 `_has_reign_history`) ——
        天朝 `h_china` 的显示名是国号 (972.10.11 起「元」), 而生成名停在 973 档落盘的
        「库曼顿巴斯部」不再刷新, 旧稿因此把「元皇帝」写成「库曼顿巴斯部皇帝」。"""
        if self._has_reign_history(tid):
            return ""
        t = self._lt.get(str(tid)) or {}
        tnd = t.get("title_name_data") or {}
        if (tnd.get("custom") or "").strip():
            return ""
        return (tnd.get("specific_title_name") or "").strip()

    def _name_at_date(self, tid, date):
        """头衔在某日期的名称 (不含层级词), 取值优先级 (v26):
        ① 动态头衔名 specific_title_name (游戏内显示名, 游牧「可萨田所部」/
           宗族命名「马扎尔」);
        ② title_history_names 最近一次更名 (本地化键 dynn_title_zhou / 直写名 青徐);
        ③ 基础名 (custom → name)。
        更名史留在 ②: h_china 唐→秦、k_guannei → 秦 这类动态国号只存在于
        title_history_names (实测无 specific_title_name), 死者按卒日国号取名的
        v25 口径仍由 ② 承担。

        v66 (D2-b, 用户 2026-09-27 拍板): ① 改为**按档取** —— 先查逐档沿革表
        (`_dyn_reign_name`: 本缓存 + 同战役其它传主缓存, 且**任期感知**), 命中即用;
        早于首档 / 未覆盖 (未回填的旧缓存) 才退末档 `specific_title_name`。旧稿直接
        读末档现值、与入参 `date` 无关, 于是 936 年的事件套上 954 年才有的名字
        (实测 936 年的 c_kherson 读成「马扎尔迈杰希部」)。`date` 为空时逐字同旧稿。

        v67 (用户 2026-09-27 拍板 D1-a): 该头衔带**自定义名**时 ① 整个让位 ——
        生成名 (逐档动态名 + 末档 specific) 不参战, 落到 ② 自定义名的更名史 /
        ③ custom。为什么: 卡尔营地 `x_d_laamp_4193` 的 `specific_title_name`
        (「持剑骑手」) **在营地活着的 931–934 档里根本不存在**, 首见于 934.4.26
        营毁之后的 935 档; 逐档沿革表又只闩非空值 (`cache_lib._latch_title_dyn_names`),
        于是 931–934 的每个日期都退回末档 sticky 值, 把玩家自定义名「葛洛夫帮」
        (931.5.11 更名, 存档信封同认) 顶替掉。详见 docs/方案_v67_营地自定义名.md。"""
        t = self._lt.get(str(tid)) or {}
        tnd = t.get("title_name_data") or {}
        # v67: ① 只在无自定义名时取值 (带 custom 时 `_specific_name` 亦返回 '',
        # 此处一并闸掉逐档动态名 —— 本档沿革表那一点记的正是营毁后的生成名)
        # v68 (问题3): 同理闸掉**有国号更名史**的头衔 (`_has_reign_history`) ——
        # h_china 的显示名是国号 (唐/中华/和/毕/越/元), 生成名「库曼顿巴斯部」不参战。
        specific = "" if ((tnd.get("custom") or "").strip()
                          or self._has_reign_history(tid)) \
            else (self._dyn_reign_name(tid, date) or self._specific_name(tid))
        if specific:
            return specific
        base = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
        best = self._history_name_at(tid, date)
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

    def _site_cid_for(self, tid, default_cid):
        """【用地名】的锚点角色 (v66): 本篇主角**持有过**该头衔时一律用主角。

        为什么: 同一件事在年表里有两行 (主角迁离 / 对手迁入), 若各自按自己的取得日
        取锚点, 同一块地会出现两个名字 (卡尔「迁离阿扎克」而乌松比凯「迁得库曼顿
        巴斯部」—— 后者是卡尔当时的座位名)。锚到主角后, 一篇之内一块地只有一个
        地方名, 第三人 (对手方) 的行也随主角的叫法。主角从未持有该头衔时用说话人。"""
        pid = self.cache.get("player_id")
        if pid is None or pid == default_cid:
            return default_cid
        ivs = self._hold_intervals(pid) or {}
        if ivs.get(tid) or ivs.get(str(tid)):
            return pid
        return default_cid

    def _dyn_hist(self, tid):
        """该头衔的逐档沿革表 —— **本缓存 + 同战役其它传主缓存**合并后按档排序 (v66)。

        为什么合并: 每份缓存只覆盖自己当玩家的那批档期 (崔佛 868–922 / 卡尔 931–954),
        只读本缓存时, 落在覆盖范围**之后**的事件会把最早那版名字当成"当时的名" ——
        实测崔佛篇附录里 938 年的 `c_itil` 读成 922 年的「马扎尔达维德部」、尼克篇
        读成静态名「阿得」, 而卡尔篇是「马扎尔迈杰希部」: 同一件事在三篇里三个名字。
        合并后同一个头衔在所有传主篇里同名 (本缓存的值优先, 它是本篇的权威档期)。

        跨战役的缓存不混入 (比对 `playthrough_id`); 结果按 tid 记忆化。
        v68 (问题3): 有国号更名史的头衔 (`_has_reign_history` —— h_china 等) 返回空表 ——
        逐档生成名 (库曼顿巴斯部) 与 display 名 (国号) 分属两套, 该头衔归国号一系,
        调用方 (`_dyn_reign_name`/`_dyn_named`/`_site_name`/`_dyn_name_before`) 随之落到
        `_history_name_at` 的国号链上。"""
        if self._has_reign_history(tid):
            return []
        hit = self._dyn_hist_cache.get(tid)
        if hit is not None:
            return hit
        mine = self.cache
        _pt = mine.get("playthrough_id")
        merged = {}
        for src in list((self.campaign or {}).values()) + [mine]:
            if not isinstance(src, dict):
                continue
            if _pt and src.get("playthrough_id") \
                    and str(src.get("playthrough_id")) != str(_pt):
                continue
            tbl = (src.get("title_dyn_names") or {}).get(str(tid))
            if not tbl:
                continue
            for h in tbl:
                if isinstance(h, dict) and h.get("from"):
                    merged[str(h["from"])] = (h.get("name") or "").strip()
        out = [{"from": d, "name": n}
               for d, n in sorted(merged.items(), key=lambda kv: cl.date_key(kv[0]))]
        self._dyn_hist_cache[tid] = out
        return out

    def _dyn_reign_name(self, tid, date):
        """按档取动态名 —— **任期感知** (v66 D2-b; `_name_at_date` 的 ①)。

        年档粒度看不出年中改名: 936.6.23 夺得 `c_azov` 时游戏已把它改成新主的汗国名,
        下一档却要到 937.1.1 才看得到 —— 照实取「≤date 的最近一点」会把 936 全年写成
        上一手的「阿扎克」(历任/称谓跟着错)。故: 该点若**早于该日持有者的任期起点**,
        改用任期起点之后的**第一个非空点** (那次移交的结果); 无持有者 / 无后续点 /
        该点本就在任期内, 一律照实返回。

        与 `_site_name` 的分工: 这里要的是「当时游戏显示什么」(政权名跟人走), 那里要
        的是「他占领它之前它叫什么」(用地名跟地走) —— 后者不适用本修正。"""
        hist = self._dyn_hist(tid)
        if not hist or not date:
            return ""
        dk = cl.date_key(date)
        pick, pick_d = "", ""
        for h in hist:
            d = h.get("from")
            if not d:
                continue
            try:
                if cl.date_key(d) <= dk:
                    pick, pick_d = h.get("name"), d
                else:
                    break
            except Exception:
                break
        if not pick_d:
            return pick
        hid = self.holder_at(tid, date)
        if hid is None:
            return pick
        ivs = self._hold_intervals(hid) or {}
        gain = None
        for iv in (ivs.get(tid) or ivs.get(str(tid)) or []):
            if not iv or not iv[0]:
                continue
            if cl.date_key(iv[0]) <= dk and (not iv[1] or dk <= cl.date_key(iv[1])):
                gain = iv[0]
        if not gain or cl.date_key(pick_d) >= cl.date_key(gain):
            return pick
        gk = cl.date_key(gain)
        for h in hist:                      # 任期起点之后的第一处非空改名
            d = h.get("from")
            if not d:
                continue
            try:
                if cl.date_key(d) <= gk:
                    continue
            except Exception:
                continue
            nm = (h.get("name") or "").strip()
            if nm:
                return nm
        return pick

    def _dyn_name_at(self, tid, date):
        """该头衔在 date 那一档的**动态名** (v66) —— 查逐档变化点沿革表
        (`_dyn_hist`: 本缓存 + 同战役其它传主缓存, 由
        `cache_lib._latch_title_dyn_names` 闩存)。

        为什么不能只读熔件: `specific_title_name` 是「只有该日期那一档才有的现值」
        (《方案 v48》§4 B), 末档只留最后一版 —— 936 年的事件会套上 954 年才有的名字
        (实测 936 年的 c_kherson 读成「马扎尔迈杰希部」)。详见
        docs/方案_v66_游牧迁移用地名.md。

        早于首点 / 无表 / 无记录一律返回 '' (三者都只能退到静态名, 故同处理)。"""
        hist = self._dyn_hist(tid)
        if not hist or not date:
            return ""
        dk = cl.date_key(date)
        pick = ""
        for h in hist:
            d = h.get("from")
            if not d:
                continue
            try:
                if cl.date_key(d) <= dk:
                    pick = h.get("name")
                else:
                    break
            except Exception:
                break
        return (pick or "").strip()

    def _site_ok(self, tid):
        """该头衔是否适用【用地名】(v66) —— 只认**领地**头衔 (c_/d_/k_/b_/e_/h_…);
        营地/毡帐/庄园等无地或家业头衔一律照旧: 它们的名字取自营地宗旨词与家业词
        (v24/v28/v52), 与"那块地当时叫什么"无关, 且冒险者营地的动态名
        (`specific_title_name` = 持剑骑手) 常在他取得之前就已定下, 沿革表锚点取不到。"""
        if tid is None:
            return False
        if self.title_kind(tid):
            return False
        return not ((self._lt.get(str(tid)) or {}).get("key") or "").startswith("x_")

    def _dyn_named(self, tid):
        """该头衔是否有过**非空动态名** (v66) —— 游戏给过显示名 (游牧/宗族命名领域,
        如「库曼顿巴斯部」) 的头衔, 其显示名就是那个名字本身, 不再叠层级词 (与 v26
        `_specific_name` 早退同口径); 从未有过动态名的头衔照旧叠层级词。

        两个来源都认: 沿革表 (逐档, 含同战役其它传主缓存) 与末档熔件 —— 后者兜住
        「沿革表未覆盖」的旧缓存。"""
        hist = self._dyn_hist(tid)
        if hist and any((h.get("name") or "").strip() for h in hist):
            return True
        return bool(self._specific_name(tid))

    def _dyn_name_before(self, tid, before):
        """逐档沿革表里 `before` **之前**的最近一个动态名 (v66); 取不到返回 ''。

        锚点用「最早一次取得日之前」, 故主角自己执政期内那些档天然落在锚点之后,
        不会被取到 —— 重取旧地时不会把他自己上一次给的部名取回来。"""
        hist = self._dyn_hist(tid)
        bk = cl.date_key(before)
        pick = ""
        for h in hist:
            d = h.get("from")
            if not d:
                continue
            try:
                if cl.date_key(d) >= bk:
                    break
            except Exception:
                break
            pick = (h.get("name") or "").strip()
        return pick

    def _site_name(self, tid, cid=None, date=None):
        """【用地名】(v66) —— 一块地在本篇里的称呼, 用于迁移/驻地这类**地点**语境。

        用户 2026-09-27 拍板 D1-a:「读取该头衔**被主角占领的前一年**熔化存档中的
        动态头衔名称」。取法:
          ① cid 持有过该头衔 → 锚到**最早一次取得日之前**那一档的动态名;
          ② 从未持有 / 没给锚点 → 取 date (缺省 as_of) 那一档的动态名;
          ③ ①② 皆空 → 末档动态名 (仅当沿革表完全没覆盖该头衔, 即未回填的旧缓存)
             → title_history_names 该日更名 → custom/name 静态名 → 本地化表 → key。

        同一块地全篇一名 (锚点取最早一次取得), 故「迁得 X / 迁离 X」成对同名, 模型
        不会再把四块不同头衔读成同一块地的反复得失。与 `title()` 的分工:
        **政权名跟人走** (person_label 仍走 `_name_at_date`), **用地名跟地走**。"""
        t = self._lt.get(str(tid)) or {}
        tnd = t.get("title_name_data") or {}
        base = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
        hist = self._dyn_hist(tid)
        before = None
        if cid is not None:
            ivs = self._hold_intervals(cid).get(tid) or []
            gains = [iv[0] for iv in ivs if iv and iv[0]]
            if gains:
                before = min(gains, key=cl.date_key)
        nm = self._dyn_name_before(tid, before) if before \
            else self._dyn_name_at(tid, date or self.as_of)
        if nm:
            return nm
        if not hist:
            sp = self._specific_name(tid)
            if sp:
                return sp
        best = self._history_name_at(tid, date or before)
        if best is not None:
            v = L.loc(self.table, str(best))
            if v:
                return v
            s = str(best)
            if not re.search(r"[A-Za-z_]", s):
                return s      # 直写名 (青徐 等) 原样返回
        if base:
            return base
        return L.loc(self.table, t.get("key") or "") or (t.get("key") or "")

    def migration_lost_title(self, owner_id, date, new_holder, days=3):
        """迁移失衔记忆的头衔**归位** (v66)。

        游戏给 `reason == migration` 的失衔记忆记的 `landed_title` 恒为**最初那块
        郡** —— 实测卡尔 6 条全指 3993=`c_uman` (他 935 年就丢了的那块), 故年表不论
        哪一次迁移都渲染成同一句, 连事件日也映射不到 (见 docs/方案_v65_游牧迁离.md §2)。
        这里改由 title history 反查: 主角在 `date` 前后 `days` 天内、以
        `type == 'migration'` **转出**给 `new_holder` 的那一块。

        候选只在他当时的持有集里找 (便宜且必然命中); 同日多块迁出时按 `new_holder`
        精确认领 (title history 里该日的新主), 取不到或撞车返回 None —— 调用方回退
        记忆自带值, 行为与 v65 前一致。"""
        if owner_id is None or not date:
            return None
        dk = _daynum(date)
        pool = []
        for tid, ivs in (self._hold_intervals(owner_id) or {}).items():
            for iv in ivs or []:
                if not iv or not iv[0] or not iv[1]:
                    continue
                if (iv[2] or "") != "migration":
                    continue
                if abs(_daynum(iv[1]) - dk) > days:
                    continue
                pool.append((tid, iv[1]))
        if not pool:
            return None
        if isinstance(new_holder, int):
            hit = [t for (t, ld) in pool if self.holder_at(t, ld) == new_holder]
            if len(hit) == 1:
                return hit[0]
        if len(pool) == 1:
            return pool[0][0]
        return None

    def _history_name_at(self, tid, date):
        """title_history_names 在 date 生效的键/直写名; 无则 None。

        v53: h_china 宣称天命当日的短暂国号 (桂) 次日即由「国之根基」改定为秦;
        历任/记忆句用次日选定的国号, 不下发 8.2 的「桂」。"""
        t = self._lt.get(str(tid)) or {}
        names = (t.get("title_name_data") or {}).get("title_history_names") or []
        if not date or not names:
            return None
        dk = cl.date_key(str(date))
        best, best_i = None, None
        for i, h in enumerate(names):
            try:
                if h.get("date") and cl.date_key(str(h["date"])) <= dk:
                    best, best_i = h.get("name"), i
            except Exception:
                continue
        key = t.get("key") or ""
        if key == "h_china" and best_i is not None and best_i + 1 < len(names):
            nxt = names[best_i + 1]
            nd = nxt.get("date")
            try:
                if nd and 0 < (_date_ord(nd) - _date_ord(date)) <= 2:
                    best = nxt.get("name")
            except Exception:
                pass
        return best

    def _name_source_key(self, tid, date):
        """头衔在某日期所用名的**来源键** (v52): `title_name_data.title_history_names`
        中该日生效的键 (dynn_title_tang / h_china / 直写名 …); 无更名史返回 ''。

        用途: 判「这个国号是不是宗族/王朝名」—— 中华皇朝 (h_china) 的国号在
        汉/晋/隋/唐/宋… 之间轮转, 只有这类键 (`dynn_title_*`) 才配「大」字前缀。"""
        return str(self._history_name_at(tid, date) or "")

    def _is_short_title(self, tid):
        """游戏「简称」头衔? (landed_titles 的 `definite_form = yes`, v52)

        这类头衔的定位名自带国号/层级词 (神圣罗马帝国/拜占庭帝国/教宗国/达尔·伊斯兰),
        取词时一律用本名, 不再追加层级词。"""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        if not key:
            return False
        try:
            return key in L.short_titles()
        except Exception:
            return False

    def throne_word(self, tid, cid=None, date=None):
        """虚位御座的成稿用词 (v75): 位号不作地名 —— 只给官职词 (天皇 / 国王)。

        `k_chrysanthemum_throne` 是 landless + figurehead 的虚位御座, 它的名字
        「高御座」是**位号**; 游戏自己按 `TITLE_TIERED_NAME` 机械拼出「高御座府」
        (行文里御座成了一个「府」, 成稿不可用)。故凡成稿要写这个头衔, 一律只用
        该头衔的官职词。判不出时返回 '' —— 调用方回退原写法 (逐字不变)。
        cid / date 只作签名兼容 (御座词不分政体、不随年月变)。"""
        if tid is None:
            return ""
        key = ((self._lt.get(str(tid)) or {}).get("key") or "")
        loc_key = self._THRONE_OFFICE_KEYS.get(key)
        if not loc_key:
            return ""
        v = L.loc(self.table, loc_key)
        return v if v and not v.startswith(("$", "[")) else ""

    def _title_name_at(self, tid, date, cid=None, site=False):
        """头衔在某日期的完整名 (v11): 按日期名 + 层级词 (独立王国=国)。
        cid 提供时按该角色当前独立性取词 (历任/朝局用)。

        v38 (问题3): 独立性按该日期**时任持有者**判定 —— 头衔是「国」还是「路」
        取决于它在那一刻是否自成一国。旧稿按区间中点取名, 又用**当前**持有者的
        独立性取词, 于是同一个 k_qingxu 在 872 年 (皇帝兼领) 显示「青徐国」、
        878 年 (臣子受任) 显示「青徐路」, 两条并列读来像两个政权。

        v66: `site=True` 时取名口换 `_site_name` (【用地名】); 该头衔**有过动态名**
        (游戏给过显示名) 时直接返回该名 (与 v26 的 `specific` 早退同口径, 不叠层级
        词); 从未有过动态名者照旧叠层级词 —— 故封建/行政档的「阿扎克伯爵领」这类
        行文逐字不变。默认 False。"""
        if tid is None:
            return ""
        t = self._lt.get(str(tid)) or {}
        key = t.get("key") or ""
        # v75: 虚位御座只给官职词 (名 + 层级词会写出游戏机械串「高御座府」)
        _tw = self.throne_word(tid)
        if _tw:
            return _tw
        if site:
            nm = self._site_name(tid, cid=cid, date=date)
            if self._dyn_named(tid) or key.startswith(("x_", "e_minister_")):
                return nm
        elif key.startswith("x_"):  # 营地/家族等特殊头衔: 只给名字
            return self._name_at_date(tid, date) or L.loc(self.table, key) or key
        else:
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
        # v38 (问题3): 未显式给出 cid 时, 按该日期的时任持有者判独立性
        # (title history 里这一条 holder 即当时之主)
        if cid is None:
            cid = self.holder_at(tid, date)
        # v80 (点4): 政体按**持有者本人**取 (见 `_gov_for_word`)
        gov = self._gov_for_word(cid, tid, date)
        independent = self._is_independent(cid, date) if cid is not None else False
        if independent is None:
            independent = False
        word = self._tier_word_at(tid, gov, bool(independent), cid=cid, date=date)
        # v28: 与 title() 同口径 — 中文建制地名 (州/府/京/郡/县收尾) 不叠层级词
        # (此前历任写出「阶州州府」「商州州府」这类重复词)
        if key.startswith("c_") and word and _CN_PLACE_SUFFIX_RE.search(nm):
            return nm
        if word and not any(nm.endswith(w) for w in self._rank_words):
            return f"{nm}{word}"
        return nm

    def _name_in_span(self, tid, start, end, cid=None):
        """头衔在 [start, end] 区间内的稳定名 (v11)。

        取样点取**任期起点** (而非区间中点): 更名只在任期头尾出现 1~2 天的过渡名
        (鄂路→青徐、青徐→周), 从起点取名正好落在改名之后那一版, 一段任期内
        只有一个名字。v38 (问题3): 旧稿取区间**中点**, 同一段任期里跨过一次改名
        就会在同一条里并写出两个名字 (「青徐国：…，青徐路：…」) —— 模型据此把
        青徐读成两个政权。"""
        if tid is None:
            return ""
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

    # ------------------------------------------------------------------
    # v74 (问题1, 用户拍板「腾位置只针对《家室列传》」): 头衔承位链
    # ------------------------------------------------------------------
    # 存档 `landed_titles[tid].history` 里**同日多人相继时该日的值是列表**
    # (Clausewitz 重复键由 `_merge_dup_pairs` 合并), `_title_seqs` 已按日期排好;
    # 这里把它展开成「谁在何时接谁的位」的序列, 供两条判据使用:
    #   · `seat_note(cid)`       该角色**现任头衔**的前任们若死于主角之手 → 一句承位句
    #                            (只进《家室列传》的子女档案);
    #   · `seat_succession(cid)` 死者之位的后续持有者链 → 顶层事实键 (校验与旁证用)。
    # 实测 (田所档): 加贺国 891.9.17–12.13 之间经 惟条/惟恒/惟彦/行有/源当时/源当元
    # 六人, 皆被主角所杀, 其位终归主角之子 田所久保; 日高见国 894.4.19–8.26 同理。
    # 见 docs/方案_v74_田所三问题.md §1.5/§1.6.1。

    def _title_holder_seq(self, tid):
        """头衔的持有者序列 [(date, holder_id, type), …] (同日列表按序展开)。"""
        if tid is None:
            return []
        out = []
        for d, ev in (self._title_seqs.get(int(tid)) or []):
            for e in (ev if isinstance(ev, list) else [ev]):
                if not isinstance(e, dict):
                    continue
                h = e.get("holder")
                if isinstance(h, int):
                    out.append((str(d), int(h), str(e.get("type") or "")))
        return out

    def _is_landed_tid(self, tid):
        """有地头衔 (排除营地/毡帐/世族庄园/朝廷职司)。"""
        key = ((self._lt.get(str(tid)) or {}).get("key") or "")
        return bool(key) and not key.startswith(("x_", "e_minister_")) \
            and not self._is_estate_title(tid)

    def _seat_killed_ids(self):
        """主角击杀集 (v74): 与 `_killed_by_player` 同源, 但只取 id 集 (轻量、可缓存)。"""
        if getattr(self, "_seat_killed_cache", None) is not None:
            return self._seat_killed_cache
        pid = self.cache.get("player_id")
        out = set()
        if pid is not None:
            prec = (self.cache.get("characters") or {}).get(str(pid)) or {}
            for k in prec.get("kills") or []:
                if isinstance(k, int):
                    out.add(k)
            for k in (self.cache.get("player_death") or {}).get("kills") or []:
                if isinstance(k, int):
                    out.add(k)
            for mem in prec.get("memories") or []:
                if str(mem.get("type") or "") == "successful_murder":
                    v = (mem.get("participants") or {}).get("victim")
                    if isinstance(v, int):
                        out.add(v)
            for cid, rec in (self.cache.get("characters") or {}).items():
                if str(cid).isdigit() and (rec.get("death") or {}).get("killer") == pid:
                    out.add(int(cid))
            for cid, c in self._chars.items():
                if not str(cid).isdigit() or int(cid) == pid:
                    continue
                d = (c or {}).get("dead_data") or {}
                if isinstance(d.get("killer"), int) and d["killer"] == pid:
                    out.add(int(cid))
        self._seat_killed_cache = out
        return out

    def _seat_prior_killed(self, cid, tid, gain):
        """该头衔上**紧邻此人之前、且死于主角之手**的前任链 [(date, id), …]。

        往前走到第一位既不与本人同日、又非主角所杀者即止 (那人是该位的「上一手
        来处」)。**同日的前任视为过手** (田所档 胆泽国 894.8.26 父子同日受官:
        主角先受该位、随即转给其子 田所德川 —— 那位当日过手者不该截断承位链)。
        返回按时间正序。"""
        seq = self._title_holder_seq(tid)
        if not seq:
            return []
        killed = self._seat_killed_ids()
        pid = self.cache.get("player_id")
        idx = None
        for i, (d, h, _t) in enumerate(seq):
            if h == cid and cl.date_key(d) >= cl.date_key(gain):
                idx = i
                break
        if idx is None:
            return []
        prev, j = [], idx - 1
        while j >= 0:
            d, h, _t = seq[j]
            if h == cid:
                j -= 1
                continue
            if cl.date_key(d) >= cl.date_key(gain):
                j -= 1                      # 同日过手 (含主角本人) — 越过
                continue
            if h in killed:
                prev.append((d, h))
                j -= 1
                continue
            break
        prev.reverse()
        return prev

    def _death_info(self, cid):
        """(卒日, 死因, 凶手) — 缓存优先, 熔件 `dead_data` 兜底 (v74)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        d = rec.get("death") or {}
        dd = (self._chars.get(str(cid)) or {}).get("dead_data") or {}
        k = d.get("killer")
        if k is None:
            k = dd.get("killer")
        return (d.get("date") or dd.get("date"), d.get("reason") or dd.get("reason"), k)

    def seat_note(self, cid):
        """承位句 (v74 问题1, 只给《家室列传》的子女档案):
        「承位：加贺国司之任：源能有891年9月17日神秘死亡；
          大和惟条、大和惟恒、大和惟彦、大和行有、源当时、源当元相继居之，未几皆卒；
          891年12月13日归田所久保。」

        判据 (全程序直算): 该角色现任有地头衔的**前任**里, 连续一串死于主角之手的
        那一段 —— 这正是用户说的「刀下亡魂是为了给我的孩子腾位置」。

        v75 (凶手点名, 用户 2026-09-27): 公开档不点名 —— 首位前任的结局走
        `death_clause` 的公开文案 (神秘死亡/失踪而亡…), 其余一串只写「未几皆卒」;
        整串**都**已公开 (killer_known ∨ 死因自带公开性) 时才照旧写「皆死于X之手」
        (用户拍板 D1: 已公开者保留点名)。无此链返回 ''。"""
        pid = self.cache.get("player_id")
        if pid is None or cid is None:
            return ""
        bits = []
        for tid, ivs in (self._hold_intervals(cid) or {}).items():
            if not self._is_landed_tid(tid):
                continue
            spans = [iv for iv in (ivs or []) if iv and iv[0]]
            if not spans:
                continue
            gain = max(iv[0] for iv in spans)
            prev = self._seat_prior_killed(cid, tid, gain)
            if not prev:
                continue
            tname = self.title_office_text(cid, tid, gain) \
                or self._name_at_date(tid, gain) or self.title_base_name(tid)
            if not tname:
                continue
            d0, h0 = prev[0]
            d_death, reason, killer = self._death_info(h0)
            clause = self.death_clause(h0, date=d_death or d0, reason=reason,
                                       killer=killer if killer is not None else pid)
            l0 = self.kin_label(h0) or self.name_or(h0)
            _all_public = all(self.killer_is_public(h) for _d, h in prev)
            head = (f"{l0}{self.date(d_death or d0)}{clause}" if clause
                    else (f"{l0}{self.date(d_death or d0)}死于{self.name_or(pid)}之手"
                          if _all_public
                          else f"{l0}{self.date(d_death or d0)}卒"))
            rest = [self.name_or(h) for _d, h in prev[1:]]
            if rest:
                mid = ("、".join(rest)
                       + (f"相继居之，皆死于{self.name_or(pid)}之手" if _all_public
                          else "相继居之，未几皆卒"))
            else:
                mid = ""
            bits.append(f"承位：{tname}之任：{head}" + (f"；{mid}" if mid else "")
                        + f"；{self.date(gain)}归{self.name_or(cid)}。")
        return "；".join(bits)

    def seat_succession(self, cid):
        """死者之位的后续持有者链 (v74): [{"title", "chain": [...], "settled": {...}}]。

        链从「此人失位/卒后」的下一位算起, 走到**第一位不是主角所杀**的持有者为止;
        与该持有者**同日**相继者一并收入 (田所档 胆泽国 894.8.26 即父子同日受官,
        其位的最终归处是主角之子 田所德川)。全程序直算, 与《家室列传》的承位句
        (`Facts.seat_note`) 共用同一份头衔序列。"""
        out = []
        if cid is None:
            return out
        killed = self._seat_killed_ids()
        pid = self.cache.get("player_id")
        for tid, ivs in (self._hold_intervals(cid) or {}).items():
            if not self._is_landed_tid(tid):
                continue
            ends = [iv[1] for iv in (ivs or []) if iv and iv[0] and iv[1]]
            if not ends:
                continue
            end = max(ends)
            tname = self._name_at_date(tid, end) or self.title_base_name(tid)
            chain, settle, stop = [], None, None
            for d, h, _t in self._title_holder_seq(tid):
                if cl.date_key(d) < cl.date_key(end) or h == cid:
                    continue
                if stop is not None and cl.date_key(d) > cl.date_key(stop):
                    break
                chain.append({"date": d, "holder_id": h,
                              "holder_label": self.kin_label(h) or self.name_or(h),
                              "kin": kin_key(self.cache, pid, h) or ""})
                if h not in killed and settle is None:
                    settle, stop = {"date": d, "holder_id": h}, d
            if chain:
                out.append({"title": tname, "date": end, "chain": chain,
                            "settled": settle})
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

    def _eff_rank(self, tid):
        """头衔的**有效层级** (v68 问题5): 世族庄园 (`_nf_`) 是家业而非领地 —
        层级一律按 0 计, 与无地营地/毡帐同档。游戏侧这三类头衔都带
        `landless = yes` / `noble_family = yes` (`common\\landed_titles\\04_china_noble_families.txt`),
        UI 的领地栏为空; 旧稿按 key 前缀给庄园 `c_`/`d_` 的 2/3 级, 无地世族
        遂以伯爵领身份入选首要头衔, 家业名当领地地名 ⇒「张氏刺史」(实测 973.1.12 死者)。

        与项目既有口径一致: `_has_current_landed_title`(v36) 与 `_primary_group`(v28)
        早已把庄园排除在真领地外, 本函数把其余按前缀算层级处一并收口。"""
        if tid is None:
            return 0
        if self._is_estate_title(tid):
            return 0
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        return self._TT_RANK.get(key[:2], 0)

    def _is_adventurer_camp(self, tid):
        """无地冒险者营地头衔? (x_d_laamp_* 等; 与游牧毡帐/家族庄园区分)"""
        if tid is None:
            return False
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        if self._is_nomad_camp(tid) or self._is_estate_title(tid):
            return False
        return "_laamp_" in key or key.startswith(self._CAMP_KEY_PREFIXES)

    # v29 (问题2): 冒险者（营地）时期区间 — 【冒险者行踪】只记这段时期
    def camp_intervals(self, cid=None, kind="camp"):
        """角色持有该种驻地头衔的区间 [(gain, loss|None)] (按起始日排序)。

        v64 (问题1): `kind` 可取 "camp" (无地冒险者营地) / "nomad" (游牧毡帐) ——
        【冒险者行踪】与【游牧行踪】各取一种; 缺省 "camp" 与旧行为逐字相同。"""
        pid = self.cache.get("player_id") if cid is None else cid
        if pid is None:
            return []
        out = []
        for tid, ivs in (self._hold_intervals(pid) or {}).items():
            if self.title_kind(tid) != kind:
                continue
            for iv in ivs:
                if iv and iv[0]:
                    out.append((iv[0], iv[1] if len(iv) > 1 else None))
        out.sort(key=lambda x: cl.date_key(x[0]))
        return out

    def in_camp_period(self, date, cid=None, kind="camp"):
        """date 是否落在某个驻地头衔持有区间内 (含端点; kind 见 `camp_intervals`)。"""
        dk = cl.date_key(date) if date else None
        if dk is None:
            return False
        for g, l in self.camp_intervals(cid, kind=kind):
            if cl.date_key(g) <= dk and (not l or dk <= cl.date_key(l)):
                return True
        return False

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

    _EAST_ASIAN_ESTATE_TPL = {"han", "chinese", "bai", "yi"}

    def estate_kind_word(self, tid, cid=None, date=None):
        """庄园的汉文类别词 (v41b 用户拍板1: 用游戏原文): 日本 → 武家庄园;
        东亚 (汉/中华/白/彝) 或天朝官制 → 世族庄园; 其余 → 世族
        (`game_concept_noble_family` = 世族, 行政制领地内的强宗头衔)。

        旧实现用「政体 ∈ 中华系 **或** 文化 ∈ 东亚」判定 —— 政体是行政制不等于
        文化是中华, 于是希腊人行政制的世族头衔被写成中华味的「世族庄园」。"""
        tpl = self.culture_template(cid) if cid is not None else ""
        if tpl == "japanese":
            return "武家庄园"
        if tpl in self._EAST_ASIAN_ESTATE_TPL:
            return "世族庄园"
        gov = self._gov_for_word(cid, tid, date or self.as_of)
        if gov == "celestial_government":
            return "世族庄园"
        if tpl in self._KOREAN_ESTATE_TPL:
            return "家族庄园"
        return "世族"

    def _primary_group(self, held, cid=None):
        """按持有集计算「主要头衔组」[(gain_date, tid)] (v11): held = {tid: gain_date}
        - 州府/县/堡 (c_/b_) 不进组 (如 898-911 的登州伯爵领等);
        - 有 公国(d_) 及以上或营地(x_) 时: 层级 ≥ 王国只留首要; 公国/营地层取
          首要 + 全部营地 (同级营地/庄园并写, 游牧营地/淄青公国);
        - 只有 州府/县 时: 取最高层级单个。
        - v13: 朝廷职司 (e_minister_*) 不进组 (官职非领地, 由官职行呈现)。
        - v26: 游牧毡帐 (x_c_nomad_*) 是驻地不是领地 — 持有任何领地头衔时
          不进 major 组, 否则「伯爵领 + 毡帐」的游牧主角历任只出现营地,
          取得伯爵领一事完全丢失 (田所2: 891 得也勒克河/巴赫穆特两领无记录)。
        - v64 (问题1): 毡帐**任何情形**都不占相位 —— 旧稿只排除了 major 组,
          回落的 `cands` 分支仍会把毡帐当相位, 于是游牧者每次 migration 迁离、
          领地清空的那一天都多出一行「任菲利普游牧营地」(实测卡尔 6 行:
          935.2.25 / 936.1.19 / 937.10.17 / 939.10.22 / 945.2.11 / 950.10.18)。
          游戏侧毡帐 `landless: true`, UI 的首要头衔栏本就为空, 故此处返回 []
          (无地可「任」), 当日的失地由 `held_titles` 的空组相位留痕。"""
        if not held:
            return []
        items = []
        for tid, gain in held.items():
            key = (self._lt.get(str(tid)) or {}).get("key") or ""
            if key.startswith("e_minister_"):
                continue
            items.append((tid, self._eff_rank(tid), gain))
        if not items:
            return []  # 仅持朝廷职司 (官职非领地)
        order = self._domain_order(cid) if cid is not None else {}
        majors = [it for it in items
                  if (it[1] >= 3 or it[1] == 0)
                  and not self._is_nomad_camp(it[0])
                  and not self._is_estate_title(it[0])]
        if not majors:
            # 仅州府/县/堡 (或仅庄园/毡帐): 最高层级最早获得的一个
            # (v28: 有领地时庄园不再占位, 领地阶段照常出现在历任里 —
            #  陆氏 869 受任阶州此前被 x_nf_ 庄园挤掉, 历任只剩一行)
            # v36 (用户拍板5): 男爵领 (rank 1) 不入相位 — 头衔材料最低取到州府 (c_);
            # 只剩男爵领时返回 [] (该日不改相位, 由祖业/营地行承担)。
            # v64 (问题1): 游牧毡帐同样不占相位 (理由见 docstring) —— 只剩毡帐
            # 的游牧者返回 [], 由 `held_titles` 出「迁离X」的失地句。
            cands = [it for it in items
                     if it[1] != 1 and not self._is_nomad_camp(it[0])]
            if not cands:
                return []
            t0 = sorted(cands, key=lambda it: (-it[1], order.get(int(it[0]), 10 ** 6),
                                               cl.date_key(it[2])))[0]
            return [(t0[2], t0[0])]
        max_tier = max(r for _t, r, _g in majors)
        tops = sorted([it for it in majors if it[1] == max_tier],
                      key=lambda it: (order.get(int(it[0]), 10 ** 6),
                                      cl.date_key(it[2])))
        if max_tier >= 4:  # k_ 及以上: 只记首要
            t0 = tops[0]
            return [(t0[2], t0[0])]
        camps = [it for it in majors if self.title_kind(it[0]) == "camp"]
        picked = tops[:1] + [c for c in camps if c != tops[0]]
        return [(g, t) for t, _r, g in sorted(picked, key=lambda it: cl.date_key(it[2]))]

    def _domain_order(self, cid):
        """角色「辖地列表」的次序 (v58 问题1) → {tid: 下标}。

        游戏写进的 `domain` 列表把**首要头衔放在首位**（实测: 驼背戈特弗里德
        `dead_data.domain = [879 下洛塔林吉亚, 819 布拉班特, …]`，且他当日的承袭
        记忆 `landed_title` 也是 879；玩家 `domain[0] = d_toscana` 与游戏 UI 一致）。
        旧稿同级并列时只比「取得日」，同日则退化成**头衔 id 序**（819 先于 879），
        于是两条同日到手的公国头衔里取到了布拉班特。

        取值链: 死者的 `dead_data.domain`（死亡时烘死, 最稳）→ 活人
        `landed_data.domain` → 缓存 `landed.domain`（仅玩家有）。取不到返回 {}
        （调用方退回旧口径）。"""
        if cid is None:
            return {}
        key = str(cid)
        memo = getattr(self, "_domain_order_memo", None)
        if memo is None:
            memo = self._domain_order_memo = {}
        if key in memo:
            return memo[key]
        c = self._chars.get(key) or {}
        dom = ((c.get("dead_data") or {}).get("domain")
               or (c.get("landed_data") or {}).get("domain"))
        if not dom:
            dom = (((self.cache.get("characters") or {}).get(key) or {})
                   .get("landed") or {}).get("domain")
        out = {}
        for i, tid in enumerate(dom or []):
            try:
                out[int(tid)] = i
            except (TypeError, ValueError):
                continue
        memo[key] = out
        return out

    def inherit_consumed(self, cid):
        """已被继承合句消费的记忆对象 id 集 (v58 问题8; 与 `inherit_pairs` 同源)。"""
        memo = getattr(self, "_inherit_consumed_memo", None)
        if memo is None:
            memo = self._inherit_consumed_memo = {}
        key = str(cid)
        if key in memo:
            return memo[key]
        ids = set()
        for _line, _ids, _dd in self.inherit_pairs(cid).values():
            ids |= _ids
        memo[key] = ids
        return ids

    # ---- v58 (问题8): 继承合句 (谁去世, 谁从他那里承袭了哪块领地) ----
    #
    # 存档里「父死」与「子承袭」是同日两条独立记忆:
    #   relative_died         participants {dead_relation: <父>}
    #   ascended_throne_memory vars reason=inheritance, landed_title=<头衔>,
    #                          participants {flavor_character: <父>}
    # 旧稿逐条出句 → 「X承袭下洛塔林吉亚公国。」＋「X的亲属Y去世。」两行割裂,
    # 看不出「因为父死, 所以子继承」; 而「亲属」还会被 v45 亲缘定语按**板块传主**
    # 算词插成「亲属公公」。现按 (同日/邻近 + 同一被继承者) 合为一句:
    #   「1074年2月25日，下洛塔林吉亚公爵大胡子戈特弗里德·维格里希去世，
    #     布永伯爵驼背戈特弗里德·维格里希从其手中承袭下洛塔林吉亚公国。」
    # 继承者称谓取**继承前一日**（否则会写成「下洛塔林吉亚公爵X承袭下洛塔林吉亚公国」）。
    _INHERIT_MERGE_DAYS = 3

    def _mem_var(self, mem, flag):
        """记忆 vars 里某 flag 的取值 (identity 优先, 否则 value)。"""
        for v in (mem.get("vars") or []):
            if v.get("flag") == flag:
                return v.get("identity") if v.get("identity") is not None \
                    else v.get("value")
        return None

    def _inherited_title_names(self, cid, prev, date):
        """cid 在 date 从 prev 手中按继承得到的头衔名列表 (title history)。"""
        idx = getattr(self, "_inherit_title_index", None)
        if idx is None:
            idx = {}
            for (hid, tid, d), p in (self._gain_prev or {}).items():
                if p is None:
                    continue
                if self.gain_reason(hid, tid, d) != "inheritance":
                    continue
                idx.setdefault((hid, str(d), p), []).append(tid)
            self._inherit_title_index = idx
        tids = list(idx.get((int(cid), str(date), int(prev))) or [])
        out = []
        for tid in tids:
            nm = self._title_name_at(tid, date, cid)
            if nm:
                out.append(nm)
        return out

    def _inherit_line(self, heir, prev, date, landed_title=None):
        """继承合句正文 (不含日期前缀); 无料返回 ''。"""
        dead = self.person_label(prev, date=date, style="brief") or self.name_or(prev)
        # 继承者称谓取继承前一日 (当天他已戴上新头衔, 会与新得的头衔撞车)
        heir_lbl = self.person_label(heir, date=_day_before(date), style="brief") \
            or self.name_or(heir)
        if not dead or not heir_lbl:
            return ""
        titles = self._inherited_title_names(heir, prev, date)
        if not titles and landed_title:
            nm = self._title_name_at(landed_title, date, heir)
            if nm:
                titles = [nm]
        if not titles:
            return ""
        if len(titles) > 3:
            tname = "、".join(titles[:3]) + f"等{len(titles)}处领地"
        else:
            tname = "、".join(titles)
        return f"{dead}去世，{heir_lbl}从其手中承袭{tname}。"

    def inherit_pairs(self, cid):
        """cid 的 (死讯记忆, 继承记忆) 配对 (按 cid 记忆化)。

        返回 {死讯记忆对象 id: (合句正文, {被消费的记忆对象 id})} —— 调用方
        跳过被消费的记忆、改用合句（日期前缀由调用方补）。"""
        memo = getattr(self, "_inherit_pairs_memo", None)
        if memo is None:
            memo = self._inherit_pairs_memo = {}
        key = str(cid)
        if key in memo:
            return memo[key]
        rec = (self.cache.get("characters") or {}).get(key) or {}
        mems = [m for m in (rec.get("memories") or []) if isinstance(m, dict)]
        deaths = []
        for m in mems:
            if m.get("type") not in _DIED_TYPES:
                continue
            dead = (m.get("participants") or {}).get("dead_relation")
            if isinstance(dead, int):
                deaths.append((self.mem_date(cid, m) or m.get("creation_date"),
                               m, dead))
        out = {}
        for m in mems:
            if m.get("type") != "ascended_throne_memory":
                continue
            if str(self._mem_var(m, "reason") or "") != "inheritance":
                continue
            prev = (m.get("participants") or {}).get("flavor_character")
            if not isinstance(prev, int):
                continue
            d = self.mem_date(cid, m) or m.get("creation_date")
            if not d:
                continue
            for dd, dm, dead in deaths:
                if dead != prev or not dd:
                    continue
                if abs(_daynum(dd) - _daynum(d)) > self._INHERIT_MERGE_DAYS:
                    continue
                body = self._inherit_line(cid, prev, d,
                                          self._mem_var(m, "landed_title"))
                if body:
                    out[id(dm)] = (body, {id(dm), id(m)}, dd)
                break
        memo[key] = out
        return out

    def _primary_title_at(self, cid, as_of=None, held_through=None):
        """角色在 as_of 日期的首要头衔 (tier, tid): 最高层级中最早获得者;
        无头衔 (仅营地) 返回 (None, tid)。
        v36 (用户拍板5): **男爵领 (rank 1) 不入首要头衔** — 头衔材料最低取到州府 (c_),
        男爵领只在「死于X / 生于X」这类地名处使用; 营地/庄园 (rank 0, 见 `_eff_rank`) 照旧保留。

        v41 (问题1) 关键修正: 持有区间按 **as_of 与末档之间**的持有状态算,
        区间起点可能晚于 as_of (福尔科 1078 年的事件里, 他被 1080 年才到手的
        热那亚公爵挤出称谓); 故此处再按 as_of 过滤一次 —— 取得日晚于 as_of 的
        头衔在那一刻**尚未持有**。

        v61 (问题2): `held_through` 非空时改判「**与 held_through 相交**」——
        区间 (gain, loss) 满足 gain <= held_through <= loss 即算持有
        (loss 为空 = 仍持; 卒日当天失去也算持有)。缺省 (None) 行为与 v60 前一致;
        仅**已卒传主**需要它: 卒日当天失去全部头衔, 旧判据「末档仍在持」会判成
        「无头衔」, 使 `_my_realm_tids()` 空集、朝廷职司的政权门槛 fail-open
        (唐六部因此混进别国传记; 实测崔佛终传)。
        v68 (问题5): 层级一律走 `_eff_rank` —— 无地世族庄园 (`c_nf_`/`d_nf_`) 按 0 级,
        仅持庄园者返回 (None, 庄园 tid), 与「仅营地」同态; 称谓由 `official_title`
        的庄园分支出「X氏乡绅」, 家业名不再被当作领地地名 (旧稿出「张氏刺史」)。"""
        held = {}
        ao = cl.date_key(as_of) if as_of else None
        through = cl.date_key(held_through) if held_through else None
        for tid, ivs in self._hold_intervals(cid, as_of).items():
            if through is not None:
                gain = None
                for (g, l, _lt) in ivs:      # 与 held_through 相交的那一段
                    if g and cl.date_key(g) > through:
                        continue
                    if l and cl.date_key(l) < through:
                        continue
                    gain = g
                    break
                if gain is None:
                    continue
            else:
                if not (ivs and ivs[-1][1] is None):
                    continue
                gain = ivs[-1][0]
                if ao is not None and gain and cl.date_key(gain) > ao:
                    continue
            if self._eff_rank(tid) == 1:
                continue
            held[tid] = gain
        if not held:
            return None, None
        items = [(tid, self._eff_rank(tid), g) for tid, g in held.items()]
        max_tier = max(r for _t, r, _g in items)
        tops = sorted([it for it in items if it[1] == max_tier],
                      key=lambda it: (self._domain_order(cid).get(int(it[0]), 10 ** 6),
                                      cl.date_key(it[2])))
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
            # v36 (用户拍板5): 男爵领 (rank 1) 不进历任 — 最低取到州府 (c_);
            # 男爵领只在「死于X / 生于X」处作地名。
            # v68 (问题5): 层级走 `_eff_rank` (庄园按 0 级, 仍进历任 —— 家业是身份)。
            if self._eff_rank(tid) == 1:
                continue
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
            group = self._primary_group(held, cid)
            # v64 (问题1): 只剩游牧毡帐的相位 —— 毡帐不算领地, 故不「任」毡帐,
            # 但当日失去的领地要留痕 (空组相位, 渲染成「935年2月25日迁离库曼顿巴斯部」)。
            # 判据限于「手上仍有毡帐」, 使「被褫夺殆尽」等其它情形逐字不变。
            nomad_only = (not group) and any(
                self.title_kind(t) == "nomad" for t in held)
            if group and group != prev_group:
                phases.append((d, group, set(prev_held) - set(held), False))
                prev_group = group
            elif nomad_only and prev_group:
                phases.append((d, [], set(prev_held) - set(held), True))
                prev_group = group
            prev_held = set(held)
        if not phases:
            return []
        # 阶段终点: 下一阶段开始日 / 无则 as_of (或末档)
        span_end = self.as_of or self.cache.get("last_date")
        out = []
        prev_ids = []
        for i, (d, group, lost_now, nomad_only) in enumerate(phases):
            end = phases[i + 1][0] if i + 1 < len(phases) else span_end
            ids = [tid for _g, tid in group]
            parts = []
            for t in ids:
                key = (self._lt.get(str(t)) or {}).get("key") or ""
                if key.startswith("x_") or self.title_kind(t) in ("camp", "estate"):
                    # v24: 营地阶段用游戏口径 (营地宗旨词: 头目/领袖/队长…);
                    # 词取不到时回退旧式「X之主」防失名。
                    # v26: 游牧毡帐 (x_c_nomad_*) 不给冒险者宗旨词, 只写毡帐名。
                    # v28: 家族庄园 (x_nf_*) 是家业而非无地营帐, 用持有者词
                    # (乡绅/当主/户长) 并标注庄园类别。
                    # v52 (问题2): 无地冒险者营地真键是 `d_laamp_*` (非 x_ 前缀),
                    # 判据改走 `title_kind`; 持有者行只用营地**本名** (不含「营地」
                    # 层级词), 与领地「象州伯爵 / 象州伯爵领」的分工同构。
                    # v66: 毡帐/营地/庄园**不走**用地名 —— 它们的名字取自营地宗旨词与
                    # 家业词 (v24/v28/v52), 与"那块地当时叫什么"无关; 且无地冒险者营地
                    # 的动态名 (`specific_title_name` = 持剑骑手) 常在他取得之前就定下,
                    # 沿革表锚点取不到。逐字保持 v52 行为。
                    # v68 (问题5): 判据由 `x_` 前缀改为 `title_kind` — 无地世族庄园的
                    # 键是 `c_nf_`/`d_nf_` (非 x_ 前缀), 旧稿落进领地支写成
                    # 「952年3月23日受任张氏女伯爵」(实测 73985)。
                    nm = self._name_at_date(t, d) or self.title_base_name(t)
                    if self._is_nomad_camp(t):
                        parts.append(nm)
                        continue
                    if self._is_estate_title(t):
                        ew = self.estate_kind_word(t, cid)
                        w = self._estate_holder_word(cid)
                        base = f"{nm}{w}" if nm and w else (nm or "")
                        # v29b: 类别词改逗号同位语 (「周家族乡绅，世族庄园」)
                        parts.append(f"{base}，{ew}" if base else "")
                        continue
                    w = self._camp_holder_word(cid, d)
                    base = f"{nm}{w}" if nm and w else (f"{nm}之主" if nm else "")
                    parts.append(f"{base}，无地冒险者营地" if base else "")
                else:
                    # v24: 领地阶段用「头衔地名+统治者称呼词」(游戏口径,
                    # 文化/政体感知: 撒丁尼亚王/撒丁王/贝州侯…), 不再用「X之主」。
                    # v66: 地名改走【用地名】(按档取该头衔被主角占领之前的动态名)
                    # —— 旧稿读末档粘滞名, 于是游牧期四块不同头衔全写成
                    # 「库曼顿巴斯部」, 历任读来像同一块地反复得失。
                    # 取样点**照旧**用相位中点 `mid` (v11: 一段任期内只取一个名,
                    # 「k_viet 899.9.5 夺得、次日改称桂」这类年内更名不分裂成两名);
                    # 用地名锚点由 cid 最早取得日给出, 与 mid 无关。
                    # 例外: **承袭**相位照旧读当日的名 —— 继承来的政权名 (宗族命名的
                    # 汗国/苏丹国) 正是那一行要说的东西; 用地名会把「任库曼顿巴斯部
                    # 国王」写成「任高昌国王」(尼克 954.7.12 实测)。
                    mid = self._span_mid(d, end)
                    if self.gain_reason(cid, t, d) == "inheritance":
                        nm = self._name_at_date(t, mid) or self.title_base_name(t)
                    else:
                        nm = self._site_name(t, cid=cid, date=mid) \
                            or self.title_base_name(t)
                    w = self._ruler_word_at(cid, t, d)
                    parts.append(f"{nm}{w}" if nm and w else (f"{nm}之主" if nm else ""))
            parts = [p for p in parts if p]
            # 真正失去 (不在持有集) 且此前在组内的头衔 (v64: 空组相位也要算)
            lost_names = []
            _seen_lost = set()
            for t in prev_ids:
                if t in ids or t not in lost_now:
                    continue
                lt = loss_types.get((t, cl.date_key(d)))
                # v66: 失去句的名字同样走【用地名】(末档粘滞名会让四块不同头衔
                # 写成同一个「库曼顿巴斯部」); 营地/毡帐/庄园不适用 (见 _site_ok)
                nm = self._title_name_at(t, d, cid, site=self._site_ok(t))
                if not nm or nm in _seen_lost:
                    continue
                # v28: 失去缘由按 title history 事件类型出词 (卸任/调任/被褫夺/
                # 失守/转授…), 未知回退旧词「让出」; 毁弃单列。
                # v64 (问题1): 游牧者迁离日, 游戏会自动毁弃其顶层地级头衔
                # (`09_dlc_mpo_scripted_effects.txt` Change 4), 该头衔与该日
                # migration 失去的郡**同名** (动态名 = 文化集合名词+宗族名+部),
                # 故出「迁离」而非「毁弃」, 并按名去重 (毡帐/营地自身的毁弃照旧)。
                # v68 (问题5): 层级走 `_eff_rank` (庄园按 0 级, 与营地同档)。
                _rank = self._eff_rank(t)
                if lt == "destroyed":
                    verb = "迁离" if (nomad_only and _rank >= 2) else "毁弃"
                else:
                    verb = TITLE_LOSS_VERBS.get(lt or "", "让出")
                _seen_lost.add(nm)
                lost_names.append(f"{verb}{nm}")
            if not ids:
                # v64 (问题1): 空组相位 —— 无地可「任」, 只写当日失去的领地
                if lost_names:
                    out.append(self.date(d) + "、".join(lost_names))
                prev_ids = ids
                continue
            if not parts:
                continue
            # v41 (问题1/2): 阶段行写出**取得经过** —— 首要头衔 (组内最高层级者)
            # 的 title history 事件类型 + 失主/授予者, 形如
            # 「1086年1月1日自海因里希·萨利安手中夺得神圣罗马帝国巴西琉斯」。
            # 旧稿只有「1086年任神圣罗马帝国巴西琉斯」, 模型无从知道是战争、
            # 继承还是阴谋 (修复方案_v41 问题2)。
            top = max(ids, key=lambda t: self._eff_rank(t))
            gain = self._gain_clause(cid, top, d)
            # v53: 开创/重建/创建是造衔动词, 宾语是头衔名 (秦皇朝),
            # 不是统治者词 (秦皇帝)。受任/承袭/攻取仍用人称 (江西节度使)。
            reason = self.gain_reason(cid, top, d)
            if gain and reason == "created":
                tname = self._title_name_at(top, d, cid) or parts[0]
                line = f"{self.date(d)}{gain}{tname}"
            elif gain:
                line = f"{self.date(d)}{gain}{'／'.join(parts)}"
            else:
                line = f"{self.date(d)}任{'／'.join(parts)}"
            prev_ids = ids
            if lost_names:
                # v55 (问题2): 失去缘由去括注 (旧稿「…夺得魏博镇（褫夺魏博镇）」)
                line += "，并" + "、".join(lost_names)
            out.append(line)
        return out

    # ---- v41 (问题1/2): 头衔取得方式 / 前一持有人 / 政体变更 ----

    def gain_reason(self, cid, tid, date):
        """头衔在 date 由 cid 取得时 title history 记的事件类型
        (conquest/created/inheritance/appointment/granted/usurped…); 无则 ''。"""
        if cid is None or tid is None or date is None:
            return ""
        return self._gain_reason.get((int(cid), int(tid), str(date)), "")

    def prev_holder(self, tid, date, exclude=None):
        """头衔在 date 的**前一持有人** id (title history 中该日之前最后一条
        holder ≠ exclude); 无记录/无前主返回 None。"""
        if tid is None or date is None:
            return None
        seq = self._title_seqs.get(int(tid)) or []
        lim = cl.date_key(str(date))
        found = None
        for d, ev in seq:
            if cl.date_key(d) > lim:
                break
            for e in (ev if isinstance(ev, list) else [ev]):
                h = e.get("holder") if isinstance(e, dict) else e
                if h is None:
                    continue
                try:
                    hid = int(h)
                except (TypeError, ValueError):
                    continue
                if exclude is not None and hid == int(exclude):
                    continue
                found = hid
        return found

    def _gain_clause(self, cid, tid, date):
        """头衔取得经过短语 (v41): 「自X手中夺得」/「承袭」/「创建」/「受X任命」。
        返回到动词为止的串 (不含「任」), 无据返回 ''。

        与 v36 的记忆句同源 (`style.TITLE_GAIN_VERBS` + `title_had_other_holder`
        的创建/重建分档 + `grant_actor` 的授予者), 但走 **title history 的事件日**
        而非记忆日 —— 历任阶段行的日期与动词由此一致 (1086.1.1 而非快照日 1087.1.1)。"""
        reason = self.gain_reason(cid, tid, date)
        if not reason:
            return ""
        if reason == "created":
            kind = self.created_verb_kind(tid, cid, date)
            verb = _style.TITLE_GAIN_CREATED_VERBS.get(kind) \
                or _style.TITLE_GAIN_VERBS.get("created") or ""
            return verb
        verb = _style.TITLE_GAIN_VERBS.get(reason) or ""
        if not verb:
            return ""
        if reason in _TITLE_TAKE_REASONS:
            ph = self.prev_holder(tid, date, exclude=cid)
            pn = self.person_label(ph, date=date, style="brief") \
                if isinstance(ph, int) else ""
            return f"自{pn}手中{verb}" if pn else verb
        # 受任/受封/承袭自他人: 写明来源 (受X任命为…)
        if reason in _TITLE_FROM_REASONS:
            ph = self.prev_holder(tid, date, exclude=cid)
            pn = self.person_label(ph, date=date, style="brief") \
                if isinstance(ph, int) else ""
            return f"承袭自{pn}" if (pn and reason == "inheritance") else verb
        return verb

    def government_changes(self, cid=None):
        """政体变更事实 (v41, 问题1): 逐档政体变化点 → 每一点一句
        「1087年，诺兰由冒险者改行封建制；此后诸领主依次称公爵、伯爵、专制君主。
          1095年，诺兰由封建制改行行政制；此后诸领主依次称将军、分区长、专制君主。」
        数据源: `cache["char_government_history"][cid]` (cache_lib 逐档为每个入
        目标集角色记录变化点); 旧缓存退 `cache["government_history"]` (玩家专属)。

        v41b (用户 2026-09-15 指正): 前身取**紧邻的上一条**, 早先误取 `hist[0]`
        (最早那条), 于是 1095 年那次变更被写成「由**冒险者**改行行政官制」——
        1087–1094 的封建制整段从稿子里消失, 模型遂以为主角从无地直达行政制。

        无变化 (或只有一次政体) 时返回 '' —— 无料不下发。
        日期用**变化点所在档期** (如 1095.1.1 → 「1095年」), 不用夺位日 ——
        夺位 (1086) 与改行行政制 (1094 年中) 是两件事, 混写会读成因果。
        政体名不用「（原X）」括注形态 (与「名词（名词）」同位语判据冲突)。"""
        pid = self.cache.get("player_id") if cid is None else cid
        if pid is None:
            return ""
        hist = [h for h in self._government_history(pid)
                if isinstance(h, dict) and h.get("date") and h.get("government")]
        # v41: 只看到本篇截止日为止的变化点 —— 否则早期十年会预告「1095 年改行
        # 行政官制」这件尚未发生的事 (as_of 泄漏)。
        if self.as_of:
            _ao = cl.date_key(self.as_of)
            hist = [h for h in hist if cl.date_key(str(h["date"])) <= _ao]
        if len(hist) < 2:
            return ""
        lines = []
        for i in range(1, len(hist)):
            old, new = hist[i - 1], hist[i]
            ngov = self._government_zh(str(new["government"]))
            ogov = self._government_zh(str(old["government"]))
            if not ngov or ngov == ogov:
                continue
            line = f"{self.date(str(new['date']))}，"
            line += (f"{self.name_or(pid)}由{ogov}改行{ngov}" if ogov
                     else f"{self.name_or(pid)}改行{ngov}")
            words = []
            for tier in ("duchy", "county", "kingdom"):
                w = self._office_word(tier, str(new["government"]),
                                      independent=False, female=False, cid=pid,
                                      date=str(new["date"]))
                if w and w not in words:
                    words.append(w)
            if words:
                line += "；此后诸领主依次称" + "、".join(words)
            lines.append(line + "。")
        return "".join(lines)

    def _government_history(self, cid):
        """角色的逐档政体史 [{date, government}] (v41b): 逐角色表优先
        (`char_government_history`, cache_lib 为每个入目标集角色记录);
        旧缓存只有玩家表 (`government_history`)。"""
        ch = self.cache.get("char_government_history") or {}
        hist = ch.get(str(cid))
        if isinstance(hist, list) and hist:
            return hist
        if cid == self.cache.get("player_id"):
            return list(self.cache.get("government_history") or [])
        return []

    def _government_zh(self, gov):
        """政体中文名 (v41b): 与档案里「政体X」同源 —— 本地化表优先, 兜底表其次。"""
        if not gov:
            return ""
        return L.loc(self.table, gov) or GOVERNMENT_ZH.get(gov, "")

    # ---- v41 (问题5): 宗族宗支 ----

    def clan_line(self, cid, date=None):
        """宗族宗支句 (v41, 问题5): 该角色的分家与宗族不同名时给出
        「东盎格利亚为布里奥讷宗族的分支」, 使同一宗族的不同分家能被读成同宗
        (诺兰档: 休·东盎格利亚 与前英格兰国王同属布里奥讷宗族, 旧稿只显示
        分家名「东盎格利亚」, 模型便当他是路人)。

        用户 2026-09-15 定规: **不写「主支为谁」** —— 不点名宗族内哪一支为主。
        宗族名缺失、或分家名与宗族名相同 (即初始家族) 时返回 ''。
        v44 (问题1): 家族名按 date 取沿革之值 —— 家族改名后 (冯·亚琛 → 冯)
        分家名与宗族名同为一字, 此句自然消失, 不再拿旧名说「为X宗族的分支」。
        v81 (问题1, 用户 2026-09-29): 家族称法改由 `house_label` 按文化/名序组装,
        组装形**必含宗族名** (平氏下北沢家 / 斯卡利茨施氏 / 菲利普，顿巴斯) ——
        本句与【家族】行、名号句三重复述同一件事, 故不再出句; 只在**名序判不出**
        (无从组装, 家族词退回旧形) 时保留旧句。"""
        if cid is None:
            return ""
        dn, hn = self._house_names_at(cid, date)
        if not dn or not hn or dn == hn:
            return ""
        if self.name_order(cid) is not None:
            return ""
        return f"{hn}为{dn}宗族的分支。"

    def _house_names_at(self, cid, date=None):
        """(宗族名, 家族名) 按 date 取家族沿革 (v44 问题1) —— **先宗族后家族**。

        返回显示形 (单字加「氏」, 与 `_dynasty_display` 同口径):
        前者为宗族名 ($DYNASTY$, 东方名序的姓), 后者为家族/分家名 ($HOUSE$,
        西方名序的姓)。顺序与 `_dynasty_display(dn, hn)` 的形参一致。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        h, dn = cl._house_names_at(rec, self.melt, date or self.as_of,
                                   rec.get("house_name") or "",
                                   rec.get("dynasty_name") or "",
                                   memo=self._tpl_memo)
        return house_display(dn or h), house_display(h)

    def house_history_lines(self, cid):
        """家格沿革句 (v44 问题1): 别立家族与家族改名只有逐档差分能记。

        数据源 = 缓存 `house_history` (cache_lib 逐档差分: 家族 id 或家族/宗族
        显示名变更点; 别立家族那一点的日期取游戏 `found_date`)。单点/无沿革返回 []。
        例 (阿德尔海德): '家格：原属诺兰氏，1118年4月2日起别立冯·亚琛氏，属弗兰肯宗族；
        1133年起改称冯氏。'"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        hist = [h for h in (rec.get("house_history") or []) if h.get("from")]
        if len(hist) < 2:
            return []
        ao = cl.date_key(self.as_of) if self.as_of else None
        pts = []
        for h in hist:
            try:
                if ao is not None and cl.date_key(h["from"]) > ao:
                    break
            except Exception:
                continue
            hid = h.get("house_id")
            hn = house_display(h.get("house_name") or "")
            dn = house_display(h.get("dynasty_name") or "")
            if not (hn or dn):
                continue
            pts.append((str(h["from"]), hid, hn, dn))
        if len(pts) < 2:
            return []

        segs = []
        for i, (d, hid, hn, dn) in enumerate(pts):
            dm = self.date(d)
            if not dm or "未知" in dm:
                dm = d
            nm = _house_shi(hn or dn)
            if i == 0:
                segs.append(f"原属{nm}")
                continue
            p_hid, p_hn, p_dn = pts[i - 1][1], pts[i - 1][2], pts[i - 1][3]
            new_house = hid != p_hid
            house_changed = hn != p_hn
            dyn_changed = dn != p_dn
            # 宗族名只在「别立家族」或「宗族本身改名」时补出 (避免逐句重复);
            # v81 (问题1): 家族称法已含宗族名 (东方名序的组装形) 时不再补 ——
            # 否则「属平氏宗族」与【家族】行的「平氏下北沢家」两次同义。
            _east = self.name_order(cid) in cl.EASTERN_NAME_ORDERS
            clan = f"，属{dn}宗族" if dn and hn and dn != hn and not _east \
                and (new_house or dyn_changed) else ""
            if new_house:
                segs.append(f"{dm}起别立{nm}{clan}")
            elif house_changed and dyn_changed:
                segs.append(f"{dm}起家族与宗族并称{_house_shi(dn or hn)}")
            elif house_changed:
                segs.append(f"{dm}起家族改称{nm}{clan}")
            elif dyn_changed:
                segs.append(f"{dm}起宗族改称{_house_shi(dn)}")
        return ["家格：" + "，".join(segs) + "。"] if len(segs) > 1 else []

    def _kin_word(self, a, b):
        """a 对 b 的亲缘**旁称** (v44 传主链用): 「其父」「其兄」「其配偶」…

        v45: 委托模块级 `kin_key` (一套判据两处用), 词形取史传单字
        (`kin_word_short`); 前配偶不算 (用户拍板), 故传主链的「配偶」也随之
        收紧为现配偶。判不出返回 ''。"""
        key = kin_key(self.cache, a, b, spouse_back=self._spouse_back_index())
        if not key:
            return ""
        return f"其{kin_word_short(key)}"

    def kin_word_for(self, cid, subject):
        """subject 相对 cid 的亲缘词 (v45 单一出口; 见模块级 `kin_word`)。

        chars 一律取**缓存的**角色表 —— 亲属图由缓存持有 (熔件 family_data 常为空),
        只在缓存缺记录时才由 kin_key 内部回落。"""
        return kin_word(self.cache, subject, cid,
                        spouse_back=self._spouse_back_index(),
                        rev=self._kin_rev_index())

    def _kin_rev_index(self):
        """反向同胞/子女索引 (v45b; 惰性建一次, 供 `kin_key` 双向并集)。"""
        if getattr(self, "_kin_rev", None) is None:
            self._kin_rev = kin_rev_index(self.cache.get("characters") or {})
        return self._kin_rev

    def _spouse_back_index(self):
        """反向配偶索引 {cid: [配偶id…]} (v45): 缓存里配偶边可能只写在对端记录上
        (实测 0.65% 反向缺失), 一次性建好供 `kin_word` 双向并集用。"""
        if getattr(self, "_spouse_back_idx", None) is None:
            idx = {}
            for k, rec in (self.cache.get("characters") or {}).items():
                if not str(k).isdigit() or not isinstance(rec, dict):
                    continue
                fam = rec.get("family") or {}
                for f in ("primary_spouse", "spouse", "concubine"):
                    for x in (fam.get(f) or []):
                        if isinstance(x, int):
                            idx.setdefault(x, []).append(int(k))
            self._spouse_back_idx = idx
        return self._spouse_back_idx

    def spouses_now(self, cid):
        """cid 的现配偶 id 集 (含反向边; 前配偶不算) —— v45 判据用。"""
        fam = _fam_of(self.cache, cid)
        out = spouses_now_family(fam)
        out |= set(self._spouse_back_index().get(int(cid), []))
        return out

    def kin_attrib_label(self, cid, subject=None, date=None, style="brief",
                         scope=None, base=None):
        """称谓 + 亲缘定语 (v45 唯一出词口)。

        scope 为 None 时**行为与 `person_label` 逐字一致** (向后兼容);
        给了 scope 时, 该人若在本板块是首次出现且与 scope.subject 有可判亲缘,
        即在称谓前加定语 (「父亲唐皇帝李漼」「姻亲姊妹X」)。
        `base` 供调用方传入**已算好**的称谓 (如刺客死者按卒日取的 label),
        缺省才现取 person_label。"""
        if base is None:
            base = self.person_label(cid, date, style)
        if scope is None or not base:
            return base
        return scope.mark(cid, base, self, date=date)


    def _older_than(self, a, b):
        """a 是否年长于 b (生年比较); 任一方无生年返回 None。"""
        ra = (self.cache.get("characters") or {}).get(str(a)) or {}
        rb = (self.cache.get("characters") or {}).get(str(b)) or {}
        ba, bb = ra.get("birth"), rb.get("birth")
        if not ba or not bb:
            return None
        try:
            return cl.date_key(ba) < cl.date_key(bb)
        except Exception:
            return None

    # ---- v44 (问题2): 传主链 (前任/后任传主) ----

    def _chain_person(self, cid, date=None):
        """传主链里的一个人 → 名号文本 (本缓存查不到时用其本人缓存兜底)。"""
        nm = self.person_label(cid, date=None, style="brief")
        if not nm:
            other = self.campaign.get(int(cid)) if str(cid).isdigit() else None
            if isinstance(other, dict):
                rec = (other.get("characters") or {}).get(str(cid)) or {}
                nm = rec.get("name_full") or rec.get("name_zh") or ""
            if not nm:
                nm = self.name(cid, date=None)
        return nm or ""

    def reign_end_word(self, re_end):
        """让位性质词 (v76 问题1): 剃发退位 / 退隐让位 / 去位，转徙无领地 / 让位。"""
        kind = str((re_end or {}).get("kind") or "unknown")
        W = _style.FACT_WORDING
        return W.get("reign_end_" + kind) or W.get("reign_end_unknown") or "让位"

    def reign_end_clause(self, cid, re_end):
        """传主「在位终结但未死亡」的收句 (v76 问题1) → 「剃发退位，传位于其子关白田所定治」。

        数据源 = `cache["reign_end"]` (由 `pipeline._cross_check_reign_ends` 从存档
        `played_character.legacy` 接替链判出, 见 `pipeline.py` 该函数注释)。措辞按 `kind`:
        剃发退位 (tonsured, 佛教「寻找净土」) / 退隐让位 (abdicated, 通用「放弃领导家族」) /
        去位转无地 (landless) / 让位 (unknown)。后任称谓走 `_chain_person` + `_kin_word`
        (与前代传主同一套亲属词; 后任不在本缓存时用其本人缓存兜底)。
        返回**不含句末句号**的收句 (调用方按所在行补标点)。"""
        re_end = re_end or {}
        kind = str(re_end.get("kind") or "unknown")
        W = _style.FACT_WORDING
        word = self.reign_end_word(re_end)
        date = self.date(re_end.get("date"))
        succ = re_end.get("successor")
        nm = ""
        if isinstance(succ, int):
            nm = self._chain_person(succ)
            kin = self._kin_word(cid, succ)
            if nm and kin:
                nm = f"{kin}{nm}"
        if date and nm:
            line = (W.get("reign_end_line_successor")
                    or "{date}，{word}，传位于{succ}。").format(
                        date=date, word=word, succ=nm)
        elif date:
            line = (W.get("reign_end_line") or "{date}，{word}").format(
                date=date, word=word)
        else:
            line = f"{word}，传位于{nm}" if nm else word
        return line.rstrip("。")

    def succession_lines(self):
        """传主链事实 (v44 问题2): 前任/后任传主与继位日。

        数据源 = 存档 `played_character.legacy` (逐档入库为 cache["played_legacy"]),
        亲缘由本缓存亲属图判定, 名号走 person_label。
        例: '承继：1117年6月19日，继前代传主邪魔克里斯托弗·诺兰之位（其父，同日崩）。'
            '后任：1152年3月4日，传主之位归于其子X。'
        无链/只有本人时返回 []。"""
        cache = self.cache
        pid = cache.get("player_id")
        chain = [e for e in (cache.get("played_legacy") or [])
                 if isinstance(e, dict) and isinstance(e.get("cid"), int)]
        if pid is None or len(chain) < 2:
            return []
        idx = next((i for i, e in enumerate(chain) if e["cid"] == int(pid)), None)
        if idx is None:
            return []
        out = []
        if idx > 0:
            prev = chain[idx - 1]
            pcid = int(prev["cid"])
            start = chain[idx].get("date") or ""
            nm = self._chain_person(pcid)
            kin = self._kin_word(pid, pcid)
            pv = self.campaign.get(pcid)
            death = ""
            re_end = {}
            if isinstance(pv, dict):
                death = ((pv.get("player_death") or {}).get("date")) or ""
                re_end = pv.get("reign_end") or {}
            # 无括注、无同位语括注 (v29b 口径): 「其父、前代传主X崩于当日」
            lead = f"{kin}、" if kin else ""
            # v76 (问题1): 前代传主**在位终结但未死亡** (让位/剃发退位) 时不能说「崩」
            re_date = re_end.get("date") or ""
            if re_date and start and cl.date_key(re_date) == cl.date_key(start):
                fate = "于是日让位"
            elif re_date:
                fate = f"让位于{self.date(re_date)}"
            elif death and start and cl.date_key(death) == cl.date_key(start):
                fate = "崩于当日"
            elif death:
                fate = f"崩于{self.date(death)}"
            else:
                fate = ""
            if nm and start:
                if fate:
                    out.append(f"承继：{self.date(start)}，{lead}前代传主{nm}{fate}，"
                               f"传主之位自此归本传主。")
                else:
                    out.append(f"承继：{self.date(start)}，本传主继{lead}"
                               f"前代传主{nm}之位。")
            elif nm:
                out.append(f"承继：本传主继{lead}前代传主{nm}之位。")
        if idx + 1 < len(chain):
            nxt = chain[idx + 1]
            ncid = int(nxt["cid"])
            start = nxt.get("date") or ""
            nm = self._chain_person(ncid)
            kin = self._kin_word(pid, ncid)
            if nm:
                body = f"{kin}{nm}继为传主。" if kin else f"传主之位归于{nm}。"
                out.append(f"后任：{self.date(start)}，{body}" if start
                           else f"后任：其后{body}")
        return out

    def protagonist_era(self):
        """本传主**执政起点** (v77 问题1): 存档接替链里「本人成为传主」的那一日。

        返回 `(era_start, has_predecessor)`:
          · `era_start` = `cache["played_legacy"]` 链上本人那一条的 `date`
            (与 `succession_lines` 同一数据源: 存档 `played_character.legacy`);
            无链 / 链上无本人 ⇒ 退回本缓存起点 `sources[0]`;
          · `has_predecessor` = 链上本人之前**还有前代传主**。

        为什么需要它 (`_timeline` 的「传主时代」闸): 继任传主的存档里带着前任
        **整整一朝**的材料 —— 前任的记忆列表在存档中持续存在, 而前任多是本传主的
        父/兄, 故在 `_related_ids` 内全部入表。实测田所久保 (16795838) 终传:
        80 条大事年表里 60 条是父亲浩二 867–891 年的谋杀、姻亲之死与其子女出生,
        模型于是把本纪写成了「关白浩二一生行事, 见诸旧记者血迹斑斑」(见
        `docs/方案_v77_传主时代裁料.md`)。首位传主 (链上无前任) 不设闸:
        他缓存起点之前的零星记忆本就是他开局世界的一部分 —— 既有传记零回归。"""
        cache = self.cache
        pid = cache.get("player_id")
        srcs = [str(s) for s in (cache.get("sources") or []) if s]
        start = srcs[0] if srcs else ""
        has_prev = False
        if pid is None:
            return start, has_prev
        chain = [e for e in (cache.get("played_legacy") or [])
                 if isinstance(e, dict) and isinstance(e.get("cid"), int)]
        idx = next((i for i, e in enumerate(chain) if e["cid"] == int(pid)), None)
        if idx is None:
            return start, has_prev
        return (chain[idx].get("date") or start), idx > 0

    # ---- v41 (问题6): 共治者 (co-ruler) 称谓 ----

    def _co_ruler_hit(self, cid, date=None):
        """该角色在 date 是否为共治者 (diarchy 记录 type=co_*)。
        返回记录 dict 或 None。"""
        if cid is None:
            return None
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return None
        dk = cl.date_key(date) if date else None
        hit = None
        for e in self._diarchies:
            if e["diarch"] != cid:
                continue
            # diarchy 记录只存 start_date (存档里无 end): 以 as_of 为上限
            if dk is not None and e["start"] and cl.date_key(e["start"]) > dk:
                continue
            if e["start"] and (hit is None
                               or cl.date_key(e["start"]) > cl.date_key(hit["start"])):
                hit = e
        return hit

    # 共治类型 → 宫廷职位名词条 (游戏 <diarchy_type>_diarch_title 约定)
    _CO_RULER_TITLE_KEYS = {
        "co_emperorship": "co_emperorship_diarch_title",
        "co_monarchy": "co_monarchy_diarch_title",
        "junior_emperorship": "junior_emperorship_diarch_title",
        "grand_secretariat": "grand_secretariat_diarch_title",
    }

    def co_ruler_title_word(self, cid, date=None):
        """共治者的**职位名** (游戏 `<type>_diarch_title`): 共治皇帝 / 名义共治皇帝;
        取不到返回 ''。"""
        hit = self._co_ruler_hit(cid, date)
        if not hit:
            return ""
        key = self._CO_RULER_TITLE_KEYS.get(hit["type"])
        if not key:
            return ""
        v = L.loc(self.table, key) or ""
        if not v or v.startswith("$") or v.startswith("["):
            return ""
        return v

    def co_ruler_word(self, cid, date=None):
        """共治者的**统治者称谓** (游戏文本原样): 「共治」+ 领主的统治者称谓词。

        游戏键 `co_ruler_male`/`co_ruler_female` (culture_titles) 的规则是
        `"共治" + <领主头衔的统治者称谓>` —— 本档领主 62045 的称谓是
        「巴西琉斯」, 故产出「共治巴西琉斯」, 与游戏自己缓存的渲染文本逐字一致
        (见 logs/research_coemperor.md)。取不到领主称谓时回退职位名 (共治皇帝)。

        共治者身份需同时满足两条 (游戏口径): diarchy 记录 type 属于 co_* 族,
        且角色带变量 `use_co_ruler_title` (否则游戏不加「共治」)。
        十年传记传 date=as_of, 共治尚未开始时返回 ''。"""
        hit = self._co_ruler_hit(cid, date)
        if not hit:
            return ""
        try:
            if int(cid) not in self._co_ruler_flag:
                return ""
        except (TypeError, ValueError):
            return ""
        liege = hit["liege"]
        base = ""
        t, tid = self._primary_title_at(liege, as_of=date)
        if tid is not None and t is not None:
            _indep = self._is_independent(liege, date)
            base = self._office_word(
                t, self._gov_for_word(liege, tid, date),
                independent=bool(_indep) if _indep is not None else True,
                female=self._is_female(liege), tid=tid, cid=liege, date=date)
        if not base:
            return self.co_ruler_title_word(cid, date)
        return "共治" + base

    def co_ruler_note(self, cid, date=None):
        """共治者身份句 (v41, 问题6): 「共治巴西琉斯，君主神圣罗马帝国巴西琉斯。」

        与游戏内文本同源: 「共治」+ 领主的统治者称谓 (co_ruler_male 规则),
        并点明其正职君主, 使「这是共治者」与「谁的共治者」一次给全。
        非共治者返回 ''。"""
        w = self.co_ruler_word(cid, date)
        if not w:
            return ""
        hit = self._co_ruler_hit(cid, date)
        liege = hit["liege"] if hit else None
        ln = self.person_label(liege, date, "brief") if liege is not None else ""
        return f"{w}，君主{ln}。" if ln else f"{w}。"

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
        取游戏口径词 — 与 official_title 同源, 供历任阶段行使用。
        v47: 政体走 `_gov_for_word` (头衔政体 → 本人政体 → 死者卒档政体),
        使「前X」在失去头衔当日也能按本人文化+政体出词。"""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        tier = ""
        for pfx, tv in L.TIER_KEY_OF_PREFIX.items():
            if key.startswith(pfx):
                tier = tv
                break
        if not tier:
            return ""
        gov = self._gov_for_word(cid, tid, date)
        female = self._is_female(cid)
        indep = self._is_independent(cid, date)
        if indep is None:
            indep = False
        return self._office_word(tier, gov, independent=bool(indep),
                                 female=female, tid=tid, cid=cid, date=date)

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

    def _camp_holder_word_default(self, female=False):
        """营地宗旨未知时的持有者词 (v52): 游戏键
        `duke_landless_adventurer_{male|female}_camp` (= 队长)。"""
        for k in (f"duke_landless_adventurer_{'female' if female else 'male'}_camp",
                  "duke_landless_adventurer_male_camp"):
            v = L.loc(self.table, k)
            if v and not v.startswith("$") and not v.startswith("["):
                return v
        return ""

    def _camp_tier_word(self, tid):
        """无地冒险者营地的**层级词** (v52, 问题2): 游戏键
        `<tier>_landless_adventurer_camp` (`duchy_landless_adventurer_camp` = 营地)。
        缺键返回 '' —— 营地头衔一律不叠领地层级词 (旧稿写出「私生子大队公国」)。"""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        tier = ""
        for pfx, tv in L.TIER_KEY_OF_PREFIX.items():
            if key.startswith(pfx):
                tier = tv
                break
        if not tier:
            return ""
        v = L.loc(self.table, f"{tier}_landless_adventurer_camp")
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
    # v80 (点4): 本表**只对律令制生效** —— 惣領制另有 `_JAPAN_SORYO_KEYS`
    # (旧稿把两种政体合流成一张律令制表, 于是 `japan_feudal_government` 的郡级持有者
    # 在 flavorization 未命中时也落 `count_administrative_male_japanese` = 国司,
    # 且女性也出男词; 见 logs/v80_gov_probe3/4 与 docs/调研_v80_封臣政体判定.md)。
    _JAPAN_OFFICE_KEYS = {
        "empire":  "emperor_administrative_male_japanese",   # 关白
        "kingdom": "king_administrative_male_japanese",      # 帅
        "duchy":   "duke_administrative_male_japanese",      # 国司
        "county":  "count_administrative_male_japanese",     # 国司
        "barony":  "baron_administrative_male_japanese",     # 郡司
    }
    # v80 (点4): 惣領制 (japan_feudal_government) 的兜底键表 —— 总领/女士/栋梁/一族
    # (词源 dlc_tgp_cultural_titles_l_simp_chinese.yml:24-32; 「总领」是**男**键)
    _JAPAN_SORYO_KEYS = {
        "county":  ("count_feudal_male_japanese", "count_feudal_female_japanese"),
        "duchy":   ("duke_feudal_male_japanese", "duke_feudal_female_japanese"),
        "kingdom": ("king_feudal_male_japanese", "king_feudal_female_japanese"),
    }
    _TENNO_TITLE_KEYS = {"k_chrysanthemum_throne"}  # 天皇座持有人 → 天皇
    # v62 (问题: 关白/将军): 日本最高头衔的官职词**按政体出词, 不看年代**
    # (用户 2026-09-24 指正: CK3 一局不是史实重演 —— 律令制可能被推翻成惣領制,
    #  也可能被「恢复天皇亲政」翻回律令制, 还可能整局不出现幕府; 故任何按年份分支
    #  的写法都是错的)。判据 = 游戏内的政体值, 与游戏同一组 flavorization:
    #   japan_administrative_government (律令制)
    #     → e_japan: emperor_administrative_male_japanese = 关白
    #       (10_tgp_japan_flavorization.txt:336-347, priority 1000)
    #   japan_feudal_government (惣領制)
    #     → e_japan: emperor_shogun_male_japanese = 幕府将军
    #       (同文件 :398-410, priority 1001, 游戏另需 flag = shogun_flag; 无旗的封建
    #        持有者是 :363 太政大臣 —— 缓存与熔件都不存角色旗标, 故惣領制统一取
    #        「幕府将军」)
    #   k_chrysanthemum_throne → king_tenno_male_japanese = 天皇 (同文件 :591, 不分政体)
    # 政体取值顺序 (见 `_title_government` / `_gov_for_word`): 持有者逐档政体史
    # → 头衔自身的 history_government → 通用词。旧稿只取「该日持有者」的政体,
    # 持有者政体史早于缓存窗口时 (藤原良房卒 879) 取不到, 落通用词「皇帝」,
    # 于是同一顶 e_japan 在源融写「关白」、在藤原良房写「皇帝」。
    _JAPAN_TOP_OFFICE_KEYS = {
        ("e_japan", "japan_administrative_government"): "emperor_administrative_male_japanese",
        ("e_japan", "japan_feudal_government"): "emperor_shogun_male_japanese",
        ("k_chrysanthemum_throne", "japan_administrative_government"): "king_tenno_male_japanese",
        ("k_chrysanthemum_throne", "japan_feudal_government"): "king_tenno_male_japanese",
    }
    # v81 (问题3, 用户 2026-09-29 拍板): 日本最高头衔的官称改走**直表裸词**
    # (「前面不加日本」——「关白某某某」「幕府将军某某某」「上皇某某某」)。
    # 为什么要另立直表, 而不修 flavorization 那条链 (三层实证, 见
    # logs/v81_probe3.txt / v81_probe7.txt):
    #   ① 带 `flag` 的条目 (将军/上皇/幕府) 建表时被标 unsupported
    #      (flavorization.py:126; 游戏原文 10_tgp_japan_flavorization.txt:398/424/435);
    #   ② `_dead_flavor_consistent` 把键中段当政体前缀比对, `shogun`/`joko` 永不等于
    #      `feudal`/`administrative` → 游戏**烘死的正词**被拒收 (盛秀 = 幕府将军被写成
    #      太政大臣、久荫 = 上皇一次也没出现);
    #   ③ `flavorization.resolve` 的 `top_liege` 缺省值让**领主政体**压过持有者政体
    #      —— 律令制的久荫 (964.11.19) 与久保 (919.2.24) 因此被叫「太政大臣」。
    # 表一: 游戏烘死的职称键 → 裸词 (带旗标信息, 是「上皇/幕府将军」唯一可靠来源)。
    # 只在**卒时窗口**内采信 (该键是角色死亡时按卒时状态烘死的, 用在早年就是错词)。
    _JAPAN_OFFICE_FROM_FLAVOR = {
        "emperor_shogun_male_japanese": "幕府将军",
        "emperor_shogun_female_japanese": "幕府将军",
        "emperor_shogun_male_japanese_feudal": "幕府将军",
        "emperor_shogun_female_japanese_feudal": "幕府将军",
        "emperor_joko_male_japanese": "上皇",
        "emperor_joko_female_japanese": "上皇",
        "emperor_administrative_male_japanese": "关白",
        "emperor_administrative_female_japanese": "关白",
        "emperor_daijo_daijin_male_japanese_feudal": "太政大臣",
        "emperor_daijo_daijin_female_japanese_feudal": "太政大臣",
        "emperor_tenno_male_japanese": "天皇",
        "emperor_tenno_female_japanese": "天皇",
        "emperor_tenno_male_japanese_flag": "天皇",
        "emperor_tenno_female_japanese_flag": "天皇",
        "king_tenno_male_japanese": "天皇",
        "king_tenno_female_japanese": "天皇",
    }
    # 表二: (头衔 key, 政体) → 裸词 —— 无烘死词时 (在世者/早年档期) 的判据。
    # 惣領制 + 头衔带 `shogun_flag` (开府) 者另写「幕府将军」(见 `japan_top_office`)。
    _JAPAN_TOP_OFFICE_WORD = {
        ("e_japan", "japan_administrative_government"): "关白",
        ("e_japan", "japan_feudal_government"): "太政大臣",
        ("k_chrysanthemum_throne", "japan_administrative_government"): "天皇",
        ("k_chrysanthemum_throne", "japan_feudal_government"): "天皇",
    }
    _JAPAN_OFFICE_SHOGUN = "幕府将军"
    _JAPAN_OFFICE_JOKO = "上皇"
    _SHOGUN_FLAG = "shogun_flag"
    # v62 (菲利普2 问题1/2): 日本最高头衔 = 天皇座 (高御座) + 日本帝国 (e_japan)。
    # 二者的**头衔名/国号一律不作「王子/公主」称号的前缀** —— 旧稿在父/母已故或已失位时
    # 走「一生最高头衔」兜底, 把它们拼成「高御座王子」「日本王子」, 而游戏侧从无此词:
    #   · 御座名不作人名前缀 (10_tgp_japan_flavorization.txt:634「亲王」只给
    #     special=ruler_child 且 titles={k_chrysanthemum_throne} 的在位天皇子女);
    #   · e_japan 的持有人是关白/幕府将军 (同文件 :336 关白 / :398 幕府将军),
    #     其子女在游戏里无王子/公主词可用 (全文件 prince*/princess*_japanese 仅 :634,644 两条)。
    # 日本皇族的称号只由 _tenno_prince_word 一条路出词。
    _JAPAN_TOP_TITLE_KEYS = {"k_chrysanthemum_throne", "e_japan"}
    # v75 (高御座): **虚位御座** (游戏侧 landless = yes + figurehead = yes) 的名字是
    # **位号**、不是地名 —— 拼层级词会写出游戏的机械串「高御座府」:
    #   · 01_japan.txt:1573-1584 (k_chrysanthemum_throne, landless=yes/figurehead=yes)、
    #     05_goryeo.txt:1126-1137 (k_yongson_throne 龙孙王座, 同形);
    #   · 拼装 = titles_l_simp_chinese.yml:3 `TITLE_TIERED_NAME: "$NAME$$TIER|U$"`;
    #   · 「府」来自 kingdom_administrative_japanese / kingdom_feudal_japanese
    #     (10_tgp_japan_flavorization.txt:204-214 / :321-330),
    #     简中词见 dlc_tgp_cultural_titles_l_simp_chinese.yml:22 与 :32。
    # 故成稿侧这类头衔一律**只用官职词** (天皇 / 国王), 不出「位号 + 层级词」。
    # 官职词直表与 `_JAPAN_TOP_OFFICE_KEYS` 同源 (御座不分政体, 同 :4310)。
    _THRONE_TITLE_KEYS = {"k_chrysanthemum_throne", "k_yongson_throne"}
    _THRONE_OFFICE_KEYS = {
        "k_chrysanthemum_throne": "king_tenno_male_japanese",       # 天皇 (:591 / loc :34)
        "k_yongson_throne": "king_yongson_throne_male_korean",      # 国王 (loc :98)
    }
    # v62 (史实口径 B): 日本皇籍宗族 —— 天皇一家的宗族 (dynn_Yamato = 大和)。
    # 皇族与臣的分界是**臣籍降下 (赐姓源/平)**, 不是「父是否在位」:
    #   · 《大日本史》卷十七 / 维基实测: 惟喬親王 (文德天皇之子) 在父 858 年崩御后
    #     仍以親王身分活到 897 年; 本康親王・人康親王・秀良親王・業良親王同例;
    #   · 受源姓者即入臣籍 (嵯峨弘仁 5 年/814 诏「赐皇子皇女未为亲王者姓源朝臣…除亲王之号」):
    #     源融・源信・源常・源弘・源定・源明・源澄・源昇・源本有・文德源氏 皆为臣。
    # 游戏侧对应机制: `tgp_japan_imperial_branch_decision`「请求皇室本姓」
    # (game/common/decisions/dlc_decisions/tgp/tgp_japan_decisions.txt:826-1005, 皇室 → 源/平)。
    _IMPERIAL_DYNASTY_KEYS = {"japanese_yamato"}
    _IMPERIAL_DYNASTY_NAMES = {"大和"}   # dynn_Yamato 的简中名 (本项目本地化表口径)

    def _imperial_clan_state(self, cid):
        """日本皇籍三态 (v62): 'imperial' 在皇籍 / 'subject' 已臣籍降下 / '' 判不明。

        取值链: ① 本项目统一宗族名链 `dynasty_name` (缓存逐角色字段, 最稳 —
        v44 起每篇按沿革取值, 源/平/藤原/大和 直接可读);
        ② 宗族 key (熔件 `dynasties.dynasties[<id>].key` == japanese_yamato)。
        判不明返回 '', 由调用方**拒绝**出亲王词 (宁可退裸名, 不凭空给皇族称号)。"""
        nm = self.dynasty_name(cid) or ""
        if nm:
            return "imperial" if nm in self._IMPERIAL_DYNASTY_NAMES else "subject"
        did = self._dynasty_of_cid(cid)
        if did is None:
            return ""
        key = (((self.melt.get("dynasties") or {}).get("dynasties") or {})
               .get(str(did)) or {}).get("key") or ""
        if not key:
            return ""
        return "imperial" if key in self._IMPERIAL_DYNASTY_KEYS else "subject"

    def _ever_held_throne(self, cid, date=None):
        """父/母是否**曾**持天皇座 (含已退位/已崩御) —— v62: 親王是终身身分,
        故认「一生持有过」, 不限于取词当日仍在位。"""
        for tid, ivs in (self._hold_intervals(cid, date) or {}).items():
            if ((self._lt.get(str(tid)) or {}).get("key") or "") not in self._TENNO_TITLE_KEYS:
                continue
            for (g, _l, _lt) in ivs:
                if g:
                    return True
        return False

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

    def _vassal_history(self, cid):
        """角色的逐档封臣史 (v53): 本缓存与同战役其他传主缓存按日期合并。

        马丁终传的缓存从继位档才起算, 早年节度使合同只在亨利档里;
        本缓存一旦有「已独立」条目就不能再「空则借用」, 必须按日期拼起来。
        同日以本缓存为准。条目 {date, liege, flags}; liege is None = 该日已非封臣。"""
        if cid is None:
            return []
        by_date = {}
        for src in list((self.campaign or {}).values()) + [self.cache]:
            if not isinstance(src, dict):
                continue
            for h in (src.get("char_vassal_history") or {}).get(str(cid)) or []:
                d = h.get("date")
                if d:
                    by_date[str(d)] = h
        return [by_date[k] for k in sorted(by_date, key=lambda x: cl.date_key(x))]

    def _vassal_entry_at(self, cid, date=None):
        """角色在 date 的封臣史条目; 无史/早于史起点返回 None。"""
        hist = self._vassal_history(cid)
        if not hist:
            return None
        if not date:
            return hist[-1]
        dk = cl.date_key(date)
        hit = None
        for h in hist:
            if h.get("date") and cl.date_key(h["date"]) <= dk:
                hit = h
            else:
                break
        return hit

    def _obligation_flags_at(self, cid, date=None):
        """角色在 date 的封臣合同义务旗标 (celestial_province_*); 独立/无史 → []。

        年中受封: 下一档已是封臣时取下一档旗标 (与 `_is_independent` 前瞻同口径)。"""
        ent = self._vassal_entry_at(cid, date)
        if (not ent or ent.get("liege") is None) and date:
            hist = self._vassal_history(cid)
            dk = cl.date_key(date)
            for h in hist:
                if h.get("date") and cl.date_key(h["date"]) > dk and h.get("liege") is not None:
                    if 0 < (_date_ord(h["date"]) - _date_ord(date)) <= 400:
                        return list(h.get("flags") or [])
                    break
        if not ent or ent.get("liege") is None:
            return []
        return list(ent.get("flags") or [])

    def _is_independent(self, cid, date=None):
        """是否独立 (非他人封臣)。v53: 有日期时按 char_vassal_history 取值;
        日期早于史起点返回 None (调用方回退通用词); 无史回退末档 _vassal_ids。"""
        if cid is None:
            return True
        key = (int(cid), str(date or ""))
        if key in self._indep_cache:
            return self._indep_cache[key]
        hist = self._vassal_history(cid)
        v = None
        if hist and date:
            dk = cl.date_key(date)
            ent = self._vassal_entry_at(cid, date)
            nxt = None
            for h in hist:
                if h.get("date") and cl.date_key(h["date"]) > dk:
                    nxt = h
                    break
            # 年中受封为臣: 上一档尚无合同、下一档 (约一年内) 已是封臣 → 当日按封臣取词
            # (马丁 910.4.18 受任江西, 快照要到 911.1.1 才看见合同)。
            nxt_gap = (_date_ord(nxt.get("date")) - _date_ord(date)) if nxt else None
            if (ent is None or ent.get("liege") is None) \
                    and nxt is not None and nxt.get("liege") is not None \
                    and nxt_gap is not None and 0 < nxt_gap <= 400:
                v = False
            elif hist[0].get("date") and cl.date_key(hist[0]["date"]) > dk \
                    and ent is None:
                v = None
            else:
                v = True if (ent is None or ent.get("liege") is None) else False
        elif hist and not date:
            v = hist[-1].get("liege") is None
        else:
            v = int(cid) not in self._vassal_ids
        self._indep_cache[key] = v
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

    def is_spouse_pair(self, a, b):
        """a、b 是否为夫妻 (v31, 问题2): b 属于 a 的配偶集 (含前配偶与妾)。

        口径: 缓存累积的 `family.ever_spouses` (跨快照并集, 离异/丧偶后仍算) 优先,
        旧缓存无该字段时回退当前 family 的配偶键。ID 非法返回 False。"""
        try:
            a, b = int(a), int(b)
        except (TypeError, ValueError):
            return False
        if a == b:
            return False
        rec = (self.cache.get("characters") or {}).get(str(a)) or {}
        fam = rec.get("family") or {}
        ids = fam.get("ever_spouses")
        if not ids:
            ids = []
            for k in ("primary_spouse", "spouse", "former_spouses",
                      "concubine", "former_concubines"):
                ids += [x for x in (fam.get(k) or []) if isinstance(x, int)]
        return b in {int(x) for x in ids if isinstance(x, int)}

    def kin_word_gendered(self, subject, other, kind):
        """配偶/情偶类亲缘词的**性别化**形态 (v63 问题5)。

        旧稿的《刺客列传》亲缘行把标签写死成男性视角
        (`("primary_spouse","妻"), ("former_spouses","前妻"), ("concubine","妾")`),
        女性死者的配偶因此被写成「妻藤原范宗」(用户实测: 大三轮丰子那行,
        实测该篇 19 条亲缘行里 4 条如此)。这里按**主体性别**取词:

          | kind          | 主体为男 | 主体为女 |
          |---------------|---------|---------|
          | `spouse`      | 妻      | 夫      |
          | `former`      | 前妻    | 前夫    |
          | `concubine`   | 妾      | 男宠    |
          | `f_concubine` | 前妾    | 前男宠  |

        性别不可判 (缓存无 `female` 且熔件无此人) 时回落中性词「配偶」/「前配偶」,
        **不猜**。词形只在这一个出口定义, 供 `biography._assassin_kill_lines` /
        `_assassin_lead_line` 共用 —— 与 `_profile_lines` 的 `spouse_lbl` 同口径
        (`biography.py` 的 `夫婿/妻室` 二档), 避免同一人两套写法。"""
        # 性别不可判 → 中性词 (不猜): 缓存无 female 且熔件也无此人时才会走到这里
        rec = (self.cache.get("characters") or {}).get(str(subject)) or {}
        v = rec.get("female")
        if v is None:
            v = (self._chars.get(str(subject)) or {}).get("female")
        if v is None:
            return "配偶" if kind in ("spouse", "former") else "情偶"
        fem = bool(v)
        if kind == "concubine":
            return "男宠" if fem else "妾"
        if kind == "f_concubine":
            return "前男宠" if fem else "前妾"
        if kind == "former":
            return "前夫" if fem else "前妻"
        return "夫" if fem else "妻"

    def _consort_word(self, owner, other):
        """owner 对 other 的配偶称谓 (v32, 问题3): 妻 / 夫 / 妾 / 情人。

        夭折句要写「X之妻Y产下死婴」—— 侧室不能写成妻、情人不能写成妻, 故按
        缓存亲属集判定: 妾集 (concubine/former_concubines) 优先, 其次配偶对
        (`is_spouse_pair` 含 ever_spouses), 其余为情人。持有人为女性时取「夫」。"""
        try:
            owner, other = int(owner), int(other)
        except (TypeError, ValueError):
            return ""
        fem = self._is_female(owner)
        rec = (self.cache.get("characters") or {}).get(str(owner)) or {}
        fam = rec.get("family") or {}
        conc = set()
        for k in ("concubine", "former_concubines"):
            conc |= {int(x) for x in (fam.get(k) or []) if isinstance(x, int)}
        if other in conc:
            return "夫" if fem else "妾"
        if self.is_spouse_pair(owner, other):
            return "夫" if fem else "妻"
        return "情人"

    # ---- v43: 婚姻线系 (普通婚 / 母系婚·入赘) ----

    def _common_children(self, a, b, after=None, before=None):
        """a、b 的共同子女 id 集 (双方亲属集交集), 可按出生日开闭区间过滤。

        `after` 应为**成婚日** —— 婚前所出 (私生) 一律随母方家族, 与婚姻线系无关,
        拿它当判据会把「主角娶了带私生子的女王」误判成入赘 (诺兰 × 康斯坦恰:
        兹比格涅夫 1111.8.25 生、9.12 才成婚, 随母方皮雅斯特; 婚后的贝利撒留斯
        随父方诺兰 —— 该婚实为普通婚)。"""
        out = set()
        chars = self.cache.get("characters") or {}
        try:
            a, b = int(a), int(b)
        except (TypeError, ValueError):
            return out
        ka = {int(x) for x in (((chars.get(str(a)) or {}).get("family") or {})
                               .get("child") or []) if isinstance(x, int)}
        kb = {int(x) for x in (((chars.get(str(b)) or {}).get("family") or {})
                               .get("child") or []) if isinstance(x, int)}
        out = ka & kb
        if after or before:
            lo = cl.date_key(after) if after else None
            hi = cl.date_key(before) if before else None
            keep = set()
            for k in out:
                birth = cl.date_key((chars.get(str(k)) or {}).get("birth")
                                    or "0.0.0")
                if lo and birth <= lo:
                    continue
                if hi and birth > hi:
                    continue
                keep.add(k)
            out = keep
        return out

    def wedding_date(self, a, b):
        """a、b 的成婚日 (缓存记忆里最早的一条 married; 查不到返回 '')。"""
        try:
            a, b = int(a), int(b)
        except (TypeError, ValueError):
            return ""
        chars = self.cache.get("characters") or {}
        for owner, other in ((a, b), (b, a)):
            for mem in ((chars.get(str(owner)) or {}).get("memories") or []):
                if str(mem.get("type") or "") != "married":
                    continue
                parts = mem.get("participants") or {}
                if parts.get("spouse") != other:
                    continue
                d = str(mem.get("creation_date") or "")
                if d:
                    return d
        return ""

    def _spouses_asof(self, cid, ids):
        """配偶 id 列表按本篇截止日裁剪 (v43)。

        `family.primary_spouse` 是**末档**状态 —— 十年档此前会把八岁女儿的
        未来丈夫写进 1087 年的《家室列传》(诺兰档: 多萝特娅 1095 年才成婚,
        d2 篇却已列「夫婿鲁普雷希特」)。成婚日不可考者保留 (不丢数据)。"""
        ids = list(ids)
        if not self.as_of:
            return ids
        ao = cl.date_key(self.as_of)
        out = []
        for s in ids:
            wd = self.wedding_date(cid, s)
            if wd and cl.date_key(wd) > ao:
                continue
            out.append(s)
        return out

    # ---- v76 (问题2): 婚配的**终了侧** —— 十年档只列窗口内仍在婚的妻妾 ----
    #
    # 现象: 田所第 5 个十年 (窗口 908–918) 里, 867 年娶、880 年已卒的初妻中御门伊子
    # 独占一整节 (1500 字)。根因是三处来源都只有「起」没有「止」: 缓存 `family` 是
    # 逐档并集 (`cache_lib.py:2659-2684`)、婚配闩存只记 `since`、裁剪只判
    # 「成婚日 ≤ as_of」(`_spouses_asof`)。用户 2026-09-27 拍板: **十年档全部篇目的
    # 配偶清单都按窗口裁** (子女不裁)。
    #
    # 终了日的唯一可靠**带日**留痕是家族关系流水里的「离婚」(日精度) —— 死亡不留
    # 结婚/离婚流水, 但卒日本身就是终了日。四个坑 (全部实测, 见
    # `docs/调研_v76_婚配起止与离异留痕.md`):
    #   ① 配偶死亡时引擎**也写**「离婚」流水 (全档 251 条里 60 条发起方当日死亡),
    #      故 date 等于任一方卒日者一律作废;
    #   ② `family_data.former_spouses` 是「离异 ∪ 丧偶」并集、无日期、不分类型;
    #   ③ `active_opinions` 的 `divorced_me_opinion` (50 年) 任一方死即清空, 只作正证;
    #   ④ 全档 171,922 条记忆里 `divorc*` 为 0 —— 没有离婚记忆可用。

    def _house_pair_flows(self):
        """家族关系流水按「角色对」建索引 → `{frozenset({a,b}): [(date, raw), …]}`。

        源 = `melt["house_relations"]["database"][*]["history"][*]` 的 `change_reason`
        (游戏渲染好的整句, 例「…与…离婚」/「…与…结婚」), 两端 id 走 `_FEUD_CHAR_RE`
        (与 `_house_raid_index` 同源同表)。惰性一次扫描; 句面含不可读
        `MAX_RECURSIVE_DEPTH` 的条目**自动不入索引** (两端 id 抽不出), 由卒日兜底。"""
        cached = getattr(self, "_pair_flows_idx", None)
        if cached is not None:
            return cached
        idx = {}
        db = (self.melt.get("house_relations") or {}).get("database") or {}
        for r in db.values():
            if not isinstance(r, dict):
                continue
            for e in (r.get("history") or []):
                if not isinstance(e, dict):
                    continue
                raw = str(e.get("change_reason") or "")
                if "离婚" not in raw and "结婚" not in raw:
                    continue
                ids = [int(x) for x in _FEUD_CHAR_RE.findall(raw)]
                if len(ids) < 2 or ids[0] == ids[1]:
                    continue
                idx.setdefault(frozenset((ids[0], ids[1])), []).append(
                    (str(e.get("date") or ""), raw))
        self._pair_flows_idx = idx
        return idx

    def _char_death_date(self, cid):
        """该角色的卒日 (缓存 `characters[].death`; 主角回读 `player_death`;
        再退回熔件三桶的 `dead_data.date`)。

        v79: 熔件兜底 —— 判「卒日判离」(见 `is_widow_divorce`) 时, 离婚流水两端
        常有一端不在本传主缓存里 (缓存只并入本传主在位的档), 而 `dead_unprunable`
        一直保留亡者对象字段 (`cache_lib._extract_snapshot` 同源读取)。查不到
        一律返回空串 (判据宁缺勿猜), 结果按 id 记忆化。"""
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return ""
        memo = getattr(self, "_death_date_memo", None)
        if memo is None:
            memo = self._death_date_memo = {}
        if cid in memo:
            return memo[cid]
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        d = (rec.get("death") or {}).get("date")
        if not d and cid == self.cache.get("player_id"):
            d = (self.cache.get("player_death") or {}).get("date")
        if not d:
            for bucket in ((self.melt.get("living") or {}),
                           (self.melt.get("dead_unprunable") or {}),
                           ((self.melt.get("characters") or {}).get(
                               "dead_prunable") or {})):
                c = bucket.get(str(cid))
                if isinstance(c, dict):
                    dd = c.get("dead_data") or {}
                    if dd.get("date"):
                        d = dd.get("date")
                        break
        memo[cid] = str(d or "")
        return memo[cid]

    def is_widow_divorce(self, raw, date):
        """该条家族关系流水是否为「卒日引擎判离」(v79, 用户 2026-09-27)。

        引擎在婚配一方**死亡当日**也写一条「…与…离婚」流水 (全档 251 条里
        60 条发起方当日卒、第二端 0 条 —— `docs/调研_v76_婚配起止与离异留痕.md`
        §A.6), 故「日期 == 任一端卒日」的离婚流水一律不是离异, 一切展示面都不得
        采用: 传主侧的配偶清单由 `spouse_end` 的卒日守卫丢弃 (v76), 《家族恩怨录》
        与仇人列传的近因流水由本判据在**渲染前**丢弃 (v79 —— 久保终传里出现
        「919年2月24日浩二与大和春子、大和规子离婚」, 而 919.2.24 正是浩二卒日)。"""
        s = str(raw or "")
        if "离婚" not in s or not date:
            return False
        for _i in _FEUD_CHAR_RE.findall(s):
            try:
                cid = int(_i)
            except (TypeError, ValueError):
                continue
            d = self._char_death_date(cid)
            if d and cl.date_key(d) == cl.date_key(date):
                return True
        return False

    def spouse_end(self, pid, other):
        """该对 (传主 × 配偶) 的婚配终了 → `(date, kind, source, precision)` (v76 问题2)。

        kind ∈ {divorce 离异, widowed 对方卒, player_end 主角卒/让位};
        取「离异流水 / 对方卒日 / 主角卒日或让位日」的**最早者**, 同日优先离异;
        三类都取不到 ⇒ 返回空串 (调用方按开区间保留, 宁多列不漏列)。
        离异流水先过「卒日守卫」(见本节坑①)。"""
        try:
            pid, other = int(pid), int(other)
        except (TypeError, ValueError):
            return "", "", "", ""
        d_other = self._char_death_date(other)
        d_self = self._char_death_date(pid) or (self.cache.get("reign_end") or {}).get("date") or ""
        cands = []
        for date, raw in self._house_pair_flows().get(frozenset((pid, other)), []):
            if not date or "离婚" not in raw:
                continue
            if self.is_widow_divorce(raw, date):
                continue                       # 坑①: 引擎把丧偶也写成「离婚」
            cands.append((cl.date_key(date), date, "divorce", "house_relations", "day"))
        # 其他家族关系流水里「同族通婚」查不到时, 记忆 `married` 只给起日, 不给终了
        if d_other:
            cands.append((cl.date_key(d_other), d_other, "widowed", "death", "day"))
        if d_self:
            cands.append((cl.date_key(d_self), d_self, "player_end", "player_death", "day"))
        if not cands:
            return "", "", "", ""
        # 同日优先离异 (divorce 排在同类日期之前); key 里用 kind 序号保证稳定
        _ord = {"divorce": 0, "widowed": 1, "player_end": 2}
        cands.sort(key=lambda c: (c[0], _ord.get(c[2], 9)))
        _k, date, kind, src, prec = cands[0]
        return date, kind, src, prec

    def _bio_window_start(self):
        """本篇叙事窗口的**起点** (v76 问题2): 十年档 = 上一个十年截止日;
        其余 (终传/在世) = 战役起点 —— 后者使终传与在世传记的裁剪恒为空操作 (零回归)。"""
        srcs = self.cache.get("sources") or []
        if not self.decade:
            return str(srcs[0]) if srcs else ""
        try:
            n = int(self.decade)
        except (TypeError, ValueError):
            return str(srcs[0]) if srcs else ""
        if n <= 1:
            return str(srcs[0]) if srcs else ""
        return self._decade_cutoff(n - 1) or (str(srcs[0]) if srcs else "")

    def spouse_active_in_window(self, other, win_start=None):
        """该配偶在**本篇窗口**内是否仍为传主妻妾 (v76 问题2, 用户口径)。

        窗口 = (win_start, as_of] 半开区间; 婚配区间 = [起, 止):
          · 起日优先 `wedding_date` (精确 `married` 记忆), 次闩存 `since`;
          · 止日取 `spouse_end` (离异/卒/主角终了), 取不到 ⇒ 开区间;
          · 收录 ⟺ 起日 ≤ as_of 且 (无止日 或 止日 > win_start)。
        终传/在世档 win_start = 战役起点 ⇒ 恒真 (不裁, 零回归)。"""
        try:
            other = int(other)
        except (TypeError, ValueError):
            return True
        y0 = win_start if win_start is not None else self._bio_window_start()
        y1 = self.as_of or self.cache.get("last_date") or ""
        start = self.wedding_date(self.cache.get("player_id"), other)
        if not start:
            for r in self.spouse_latch_rows(self.as_of):
                if r.get("other") == other:
                    start = r.get("first_seen") or ""
                    break
        if start and y1 and cl.date_key(start) > cl.date_key(y1):
            return False                       # 窗口末之后才成婚
        end = self.spouse_end(self.cache.get("player_id"), other)[0]
        if end and y0 and cl.date_key(end) <= cl.date_key(y0):
            return False                       # 窗口开始前已终了
        return True

    def spouses_in_window(self, ids, win_start=None):
        """配偶 id 列表 → 只留本篇窗口内仍在婚者 (保持原次序; v76 问题2)。"""
        if not ids:
            return []
        if win_start is None:
            win_start = self._bio_window_start()
        return [x for x in ids if self.spouse_active_in_window(x, win_start)]

    def _matrilineal_pairs_live(self):
        """当前熔件 `relations.active_relations` 里的母系婚对 (惰性建索引, v43)。

        熔件是**当下**最完整的来源 (凡仍存续的母系婚都在), 缓存 `matrilineal_pairs`
        只是逐档闩存的历史 (补「此后已离异/丧偶」的婚事)。"""
        memo = getattr(self, "_matri_live", None)
        if memo is None:
            memo = set()
            for e in (self.melt or {}).get("relations", {}).get(
                    "active_relations") or []:
                if not isinstance(e, dict) or "matrilineal" not in e:
                    continue
                a, b = e.get("first"), e.get("second")
                if isinstance(a, int) and isinstance(b, int) and a != b:
                    memo.add(cl.matrilineal_pair_key(a, b))
            self._matri_live = memo
        return memo

    def is_matrilineal(self, a, b, after=None, before=None):
        """a、b 的这桩婚姻是否为**母系婚 (入赘)**; 返回 True/False/None。

        游戏规则 (本地化原文): `game_concept_matrilineal_desc` = 在母系婚姻中,
        出生的孩子将属于**母亲的家族**而不是父亲的; 交互界面把这一档写作
        「切换入赘」(`MARRIAGE_MATRILINEAL_TOGGLE_TOOLTIP`)。

        判据三级, 全在程序侧:
          ① 当前熔件 `relations.active_relations` 的 matrilineal 标记 (惰性索引);
          ② 缓存 `matrilineal_pairs` —— 同一标记的逐档闩存 (婚姻离异/丧偶后条目
             会从存档消失, 闩存保证当年那桩婚事仍判得出);
          ③ 未见标记时按**婚后所生子女的家族归属**判: 父母各有家族且彼此不同时,
             子女随母方即母系婚 (这正是上述规则的结果), 随父方即普通婚。
             婚前所出不入判据 (`after`), 因私生一律随母方, 与线系无关。
        无子女 / 一方无家族 / 两方同族 / 子女家族混杂 → None (判不出即不下发,
        句面保持普通形态)。"""
        try:
            a, b = int(a), int(b)
        except (TypeError, ValueError):
            return None
        if a == b:
            return None
        key = cl.matrilineal_pair_key(a, b)
        if key in self._matrilineal_pairs_live() \
                or key in (self.cache.get("matrilineal_pairs") or {}):
            return True
        kids = self._common_children(a, b, after=after, before=before)
        if not kids:
            return None
        ha, hb = self._house_of_cid(a), self._house_of_cid(b)
        if ha is None or hb is None or ha == hb:
            return None
        mom, dad = (a, b) if self._is_female(a) else (b, a)
        hm, hd = self._house_of_cid(mom), self._house_of_cid(dad)
        if hm is None or hd is None or hm == hd:
            return None
        n_mom = n_dad = n_other = 0
        for k in kids:
            hk = self._house_of_cid(k)
            if hk == hm:
                n_mom += 1
            elif hk == hd:
                n_dad += 1
            else:
                n_other += 1
        if n_mom and not n_dad and not n_other:
            return True
        if n_dad and not n_mom and not n_other:
            return False
        return None

    def marriage_lineality_note(self, a, b, wedding=None, before=None):
        """成婚句/配偶行的程序补注 (v43 起, v51 简化, v55 去括注): 母系婚补「，是入赘婚」。

        只标异常那一档 (母系婚) —— 与游戏 UI 只对母系婚给出
        `MATRILINEAL_WARNING`「该婚姻所生子将属于X的家族」同一口径; 普通婚与判不
        出者返回 '' (句面即普通形态)。

        v51 (用户拍板): 补注只写线系名 —— 旧稿逐行写全
        「（入赘婚：所生子女随母方，属X氏）」太长, 且把母方家族名重复进每一处;
        「入赘婚」一词本身即含「所生子女随母方」之义 (CK3 简中同用此词),
        故不再另附家族名, 也不再依赖母方家族名解析成功。
        v55 (问题2): 括注改分句 —— 句面成「X与Y成婚，是入赘婚。」(旧稿「…（入赘婚）。」)

        `wedding` = 成婚日 (传日历记忆的日期; 缺省由 `wedding_date` 回查),
        `before` = 本篇截止日 (十年传记不把尚未出生的子女算进判据)。"""
        try:
            a, b = int(a), int(b)
        except (TypeError, ValueError):
            return ""
        if not wedding:
            wedding = self.wedding_date(a, b)
        if not self.is_matrilineal(a, b, after=wedding or None, before=before):
            return ""
        return "，是入赘婚"

    def _office_word(self, tier, government, independent=False, female=False, tid=None,
                     cid=None, date=None):
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
        tid 传入时, 天皇座 (k_chrysanthemum_throne) 持有人直称「天皇」。
        v62: 日本最高头衔另走 `_JAPAN_TOP_OFFICE_KEYS` 直表 —— e_japan **按政体**出词
        (律令制=关白 / 惣領制=幕府将军; 不看年代), 不再落通用词「皇帝」。"""
        gov = government or ""
        # v52 (问题2): 无地冒险者营地的持有者称呼走游戏键
        # (`duke_landless_adventurer_camp_<宗旨>` = 头目/领袖/队长…; 宗旨未知回退
        # `duke_landless_adventurer_male_camp` = 队长), 不再落到封建官职词「公爵」。
        if tid is not None and self.title_kind(tid) == "camp":
            w = self._camp_holder_word(cid, date) if cid is not None else ""
            if not w:
                w = self._camp_holder_word_default(female)
            return w if (w and not w.startswith(("$", "["))) else ""
        # v30: 游戏 flavorization 优先 (修复方案_菲利普4.md 问题2) — 文化专属层级词
        # 压过政体通用词: 诺斯公国 = 雅尔 (count_feudal_male_norse, tier=duchy,
        # priority 30) 而非 duke_tribal_male 大酋长 (26)。未命中才走既有链。
        # v74 (问题2, 用户拍板): 政体不可知 (`gov == ''`) 时, `duke`/`count` 这类
        # **无任何条件**的兜底条目视为未命中 —— 否则它以其 priority 压过后面的
        # 文化/政体链 (且性别词也取不到: 女性公爵会得男性词「公爵」而非「女公爵」)。
        fw_key = self._flavor_key("character", tier, cid, tid=tid,
                                  gender=("female" if female else "male"),
                                  gov=gov, date=date)
        if fw_key and not (not gov and FZ.is_unconditional(fw_key)):
            v = L.loc(self.table, fw_key)
            if v and not v.startswith("$") and not v.startswith("["):
                return v
        if gov in ("japan_administrative_government", "japan_feudal_government"):
            tkey = (self._lt.get(str(tid)) or {}).get("key") or ""
            # v62: 日本最高头衔 (e_japan / 天皇座) 先查 (头衔, 政体) 直表 ——
            # 关白 (律令制) / 幕府将军 (封建期) / 天皇, 不再落通用词「皇帝」。
            key = self._JAPAN_TOP_OFFICE_KEYS.get((tkey, gov))
            if key is None:
                if gov == "japan_feudal_government":
                    # v80 (点4): 惣領制走自己的键表 (总领/女士/栋梁), 且**分性别**
                    _pair = self._JAPAN_SORYO_KEYS.get(tier)
                    key = (_pair[1] if female else _pair[0]) if _pair else ""
                else:
                    key = self._JAPAN_OFFICE_KEYS.get(tier)
                if tkey in self._TENNO_TITLE_KEYS:
                    key = "king_tenno_male_japanese"
            if key:
                v = L.loc(self.table, key)
                if v and not v.startswith("$") and not v.startswith("["):
                    return v
        if gov in self._CELESTIAL_LIKE_GOVS:
            if independent:
                if tier == "hegemon":
                    # v73 (用户 2026-09-27): 女性霸权级统治者称「女皇」(如「元女皇」)
                    # —— 游戏原文的 `hegemon_celestial_female_chinese` 只是对男键的
                    # 模板引用, 与男键同形, 旧稿在此**直写男键**, 女性一律被写成「皇帝」。
                    key = "hegemon_celestial_female_chinese" if female \
                        else "hegemon_celestial_male_chinese"
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
        # v30: 性别入键 (修复方案_菲利普4.md 问题9) — 此前两条键都写死 _male,
        # 女性持有者的官职词一律退化成男性词 (埃尔斯威思 id=15511 female=True
        # 被写成「诺丁汉郡伯爵」, 游戏口径为「诺丁汉郡女伯爵」)。
        # 候选顺序: 政体×性别 → 封建×性别 → 层级×性别 → 封建男性 (旧表兼容)。
        g = "female" if female else "male"
        keys = ([f"{self._TIER_KEY[tier]}_{prefix}_{g}"] if prefix else []) \
            + [f"{self._TIER_KEY[tier]}_feudal_{g}",
               f"{self._TIER_KEY[tier]}_{g}",
               f"{self._TIER_KEY[tier]}_feudal_male"]
        for k in dict.fromkeys(keys):
            v = L.loc(self.table, k)
            if v and not v.startswith("$") and not v.startswith("["):
                return v
        # v30: 通用兜底改查男女分列的官职词表 (GENERIC_TIER_ZH 是头衔名后缀, 不混用)
        pair = L.GENERIC_OFFICE_ZH.get(tier)
        if pair:
            return pair[1] if female else pair[0]
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

    # ---- v30: 游戏 flavorization 取词 (统治者称呼 / 头衔名后缀) ----
    # 见 flavorization.py 与 修复方案_菲利普4.md 问题2: 诺斯公国 = 雅尔
    # (键名 count_feudal_male_norse, 块内 tier = duchy, priority 30) ——
    # 文化专属词优先于政体通用词, 这是游戏的实际规则。

    _FLAVOR_TIER = {"hegemon": "hegemony"}

    # ---- v47: 死者文化/信仰的取回 —— 存档里 culture/faith 是**可选键** ----
    # CK3 官方 wiki (Modding#Contents_of_the_gamestate_file) 明文: 角色记录里
    # `culture=`/`faith=` 在写了 `dynasty_house` 时**可选**, 缺省即取该家族的
    # 文化/信仰; 家族记录本身不带这两个字段, 值沿 `historical` + `head_of_house`
    # 的**族长链由近及远**取第一个显式值 (社区参考实现 CK3-history-extractor
    # `house.rs::get_culture/get_faith` 逐字如此)。所以死者记录里缺 culture
    # 不是「没有」, 而是「等于家族值」—— 这正是游戏总能显示死者文化/信仰的机制。
    # 见 docs/研究_v47_文化信仰存档来源.md §1。
    def _house_of(self, cid):
        """角色家族 id (缓存优先, 熔件角色对象兜底); 无家族返回 None。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        hid = rec.get("dynasty_house")
        if hid is None:
            hid = (self._chars.get(str(cid)) or {}).get("dynasty_house")
        try:
            return int(hid) if hid is not None else None
        except (TypeError, ValueError):
            return None

    def _house_default(self, cid, field):
        """家族缺省值 (游戏口径): 沿族长链由近及远取第一个**显式** `field` 值。

        field = 'culture' / 'faith'。家族值按家族记忆化 (同一家族的成员共用一次
        求解)。取不到返回 None —— 调用方照旧回退「无据」。"""
        hid = self._house_of(cid)
        if hid is None:
            return None
        memo = getattr(self, "_house_memo", None)
        if memo is None:
            memo = {}
            self._house_memo = memo
        per = memo.setdefault(field, {})
        if hid in per:
            return per[hid]
        houses = (self.melt.get("dynasties") or {}).get("dynasty_house") or {}
        h = houses.get(str(hid)) or {}
        leaders = []
        for x in (h.get("historical") or []):
            try:
                leaders.append(int(x))
            except (TypeError, ValueError):
                continue
        head = h.get("head_of_house")
        try:
            head = int(head) if head is not None else None
        except (TypeError, ValueError):
            head = None
        if head is not None and head not in leaders:
            leaders.append(head)
        val = None
        for lid in reversed(leaders):
            v = (self._chars.get(str(lid)) or {}).get(field)
            if v is not None:
                val = v
                break
        per[hid] = val
        return val

    def _culture_entry(self, cid, date=None):
        """角色文化的 culture_manager 条目 (含 name_list / heritage)。

        v47: 值链改为**按日期**取并补上「家族缺省」兜底 ——
          沿革表 (`culture_history`) → 本篇缓存现值 → 熔件角色对象 → 家族缺省。
        旧实现只读本篇缓存的 `culture` 现值: 死者(尤其跨传主引用时)该字段被
        存档剪除, 于是 flavorization 全失配、静默降级成通用称谓词
        (诺兰档实测: 克里斯托弗的「巴西琉斯」→「皇帝」, 见
        docs/研究_v47_统治者头衔动态.md §2)。"""
        if cid is None:
            return {}
        cul = self._culture_id_at(cid, date)
        if cul is None:
            cul = (self._chars.get(str(cid)) or {}).get("culture")
        if cul is None:
            cul = self._house_default(cid, "culture")
        if cul is None:
            return {}
        e = ((self.melt.get("culture_manager") or {}).get("cultures") or {}) \
            .get(str(cul))
        return e if isinstance(e, dict) else {}

    def _faith_tags(self, cid, date=None):
        """角色信仰 → (faith tag, religion tag)。

        v47: 按 date 取 (信仰沿革 `faith_history` → 现值 → 家族缺省) —— 与
        `_culture_entry` 同口径; 死者记录里 `faith` 同样会被存档剪除。"""
        fid = self._faith_id(cid, date) if cid is not None else None
        if fid is None:
            return "", ""
        rel = self.melt.get("religion") or {}
        e = (rel.get("faiths") or {}).get(str(fid))
        if not isinstance(e, dict):
            return "", ""
        ftag = str(e.get("faith_type") or e.get("tag") or "")
        rtag = ""
        rid = e.get("religion")
        if rid is not None:
            re_ = (rel.get("religions") or {}).get(str(rid))
            if isinstance(re_, dict):
                rtag = str(re_.get("tag") or re_.get("religion_type") or "")
        return ftag, rtag

    def _top_liege_of(self, cid, tid):
        """角色沿 de_facto_liege 上溯的最高领主 (自身即最高时返回 (cid, tid))。"""
        seen = set()
        cur = str(tid) if tid is not None else ""
        holder, top_tid = cid, tid
        while cur and cur not in seen:
            seen.add(cur)
            t = self._lt.get(cur) or {}
            if not t:
                break
            h = t.get("holder")
            if isinstance(h, int):
                holder = h
            top_tid = t.get("title") or cur
            liege = t.get("de_facto_liege")
            cur = str(liege) if liege is not None else None
        try:
            top_tid = int(top_tid)
        except (TypeError, ValueError):
            top_tid = tid
        return holder, top_tid

    def _flavor_key(self, kind, tier, cid, tid=None, gender=None, gov=None,
                    date=None, special=None, independent=None):
        """flavorization 取词的本地化键; 未命中/无表返回 ''。
        v41: date 锚点 — 本人与领主的政体均按该日期取 (封建期/行政期词不同)。
        v64 (问题2): `special` 透传给 `FZ.resolve` (缺省 None → holder 类);
        `independent` 可显式覆盖独立性 —— 王子/公主词的「独立/封臣」档看的是
        **父/母** (ruling parent) 的独立性, 而 `cid` 传的是子女本人 (无地,
        `_is_independent` 取不到 ruling parent 的值)。"""
        if not self._flavor or tier is None or cid is None:
            return ""
        tkey = self._FLAVOR_TIER.get(tier, tier)
        if gender is None:
            gender = "female" if self._is_female(cid) else "male"
        if gov is None:
            # v80 (点4): 政体按**持有者本人**取 —— flavorization 的 `governments`
            # 在 Context Character 上求值 (见 `_gov_for_word` 的说明)
            gov = self._gov_for_word(cid, tid, date) if tid is not None else ""
        ce = self._culture_entry(cid, date)
        ftag, rtag = self._faith_tags(cid, date)
        title_key = ""
        if tid is not None:
            title_key = ((self._lt.get(str(tid)) or {}).get("key") or "")
        if independent is None:
            independent = self._is_independent(cid, date)
        if independent is None:
            independent = True
        # 封臣: 未显式 top_liege = no 的条目按最高领主判定 (游戏默认行为)
        top = None
        if not independent and tid is not None:
            lid, ltid = self._top_liege_of(cid, tid)
            if lid is not None and int(lid) != int(cid):
                lce = self._culture_entry(lid, date)
                lft, lrt = self._faith_tags(lid, date)
                top = {"government": (self._gov_for_word(lid, ltid, date)
                                      if ltid else ""),
                       "name_list": lce.get("name_list") or "",
                       "heritage": lce.get("heritage") or "",
                       "faith": lft, "religion": lrt}
        try:
            return FZ.resolve(
                kind, tkey, gender, government=gov or "",
                name_list=ce.get("name_list") or "",
                heritage=ce.get("heritage") or "",
                faith=ftag, religion=rtag, title_key=title_key,
                independent=bool(independent), top=top,
                obligation_flags=self._obligation_flags_at(cid, date),
                special=(special or "holder"))
        except Exception:
            return ""

    def _prince_word_exists(self, ptier, government, independent, cid, tid, date,
                            owner=None):
        """游戏侧**有没有**王子/公主称号 (v64, 问题2) —— 问 `special = ruler_child`
        条目表 (`FZ.ruler_child_exists`): 命中任一 (条件全中、priority 最高者) 即「有」。

        为什么必须问表: tribal_government / nomad_government **在任何层级**都没有
        ruler_child 条目 (`00_flavorization.txt:354-400` 的 prince/princess 是
        `governments = { feudal_government clan_government }` 穷举), 故部落制与
        游牧制的王国级/帝国级无头衔子女在游戏里没有任何称号; 旧稿末档无条件回落
        「王子/公主」, 于是卡尔 15 名子女全带「库曼顿巴斯部王子/公主」。
        仅作**闸门**用: 出词仍走 `_PRINCE_WORD_OVERRIDE` / 本地化表的既有中文口径
        (v16 把西式王国之女的「郡主」写作「公主」等定规不变)。

        **政体取不到时放行** —— 已毁/已剪除的头衔 `_title_government` 为空
        (阿基坦公国、意大利王国等 9 世纪旧衔), 此时先退持有者本人的政体史
        (`_character_government_or_earliest`), 仍取不到就返回 True: 闸门只挡
        「确知游戏不给」的部落制/游牧制, 判不出来的情形一律照旧出词。"""
        if cid is None or ptier is None or not self._flavor:
            return True
        gov = (government or "").strip()
        if not gov and owner is not None:
            try:
                gov = (self._character_government_or_earliest(owner, date) or "")
            except Exception:
                gov = ""
        if not gov:
            return True
        ce = self._culture_entry(cid, date)
        ftag, rtag = self._faith_tags(cid, date)
        title_key = ((self._lt.get(str(tid)) or {}).get("key") or "") \
            if tid is not None else ""
        # 封臣: 未显式 top_liege = no 的条目按最高领主判定 (与 `_flavor_key` 同式)
        top = None
        if not independent and tid is not None:
            lid, ltid = self._top_liege_of(cid, tid)
            if lid is not None and int(lid) != int(cid):
                lce = self._culture_entry(lid, date)
                lft, lrt = self._faith_tags(lid, date)
                top = {"government": (self._gov_for_word(lid, ltid, date)
                                      if ltid else ""),
                       "name_list": lce.get("name_list") or "",
                       "heritage": lce.get("heritage") or "",
                       "faith": lft, "religion": lrt}
        try:
            k = FZ.ruler_child_exists(
                self._FLAVOR_TIER.get(ptier, ptier),
                "female" if self._is_female(cid) else "male",
                government=gov,
                name_list=ce.get("name_list") or "",
                heritage=ce.get("heritage") or "",
                faith=ftag, religion=rtag, title_key=title_key,
                independent=bool(independent), top=top,
                obligation_flags=self._obligation_flags_at(cid, date))
        except Exception:
            return True
        return bool(k)

    def _flavor_word(self, kind, tier, cid, tid=None, gender=None, gov=None,
                     date=None):
        """flavorization 键 → 本地化词 (未命中/未解析返回 '')。"""
        k = self._flavor_key(kind, tier, cid, tid=tid, gender=gender, gov=gov,
                             date=date)
        if not k:
            return ""
        v = L.loc(self.table, k)
        if v and not v.startswith("$") and not v.startswith("["):
            return v
        return ""

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
        """官职/国号的日期锚点 (v25): 显式 date > 卒前一日 (已死且在传记窗口内) > as_of。
        死者取卒前一日 → 卒于唐则为「唐皇帝」(李漼 874.8.15 卒, h_china 875.6.25 才
        由崔氏改国号秦); 卒于 as_of 之后者视为在世, 取 as_of (窗口外国号不外泄)。

        v42 (问题7): 两处收口 ——
        ① **卒日当天头衔已随继承易主**: 头衔史的丢失日就是卒日, 而 `_hold_intervals`
           的 as_of 过滤是「丢失日 > as_of 才算仍持有」, 取卒日会让死者自己的皇位
           落空。改取**卒前一日**, 语义即「按卒前的身分称呼」。
        ② **主角的卒档不在 `characters[pid].death`**: 它记在 `cache["player_death"]`,
           旧稿因此对主角取不到卒日 → 落到 `as_of` (终传为 None → 熔件当前档,
           已是卒后) → 终传里主角自己的 `office`/`label` 退成裸名。此处一并回读。

        v46 (问题1): ①的漏口补上 —— 旧实现 `if date: return date` 让**显式传入**
        的日期绕过卒前一日回退, 于是十年篇 (as_of=1128/1133/1138, 晚于卒日) 里
        已死者被读成「当日不在职」, `_full_label` 再拿他一生最高头衔补成
        「**前**神圣罗马帝国皇帝X」(实测诺兰档 62045 等 8 人)。语义仍是
        「死者按卒时身分称呼」: 显式日期晚于卒日时折到卒前一日。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        dd = (rec.get("death") or {}).get("date")
        if not dd and cid == self.cache.get("player_id"):
            dd = (self.cache.get("player_death") or {}).get("date")
        if date:
            if dd and cl.date_key(date) >= cl.date_key(dd):
                return _day_before(dd)          # v46: 卒日/卒后日期 → 按卒时身分
            return date
        if dd and (not self.as_of or cl.date_key(dd) <= cl.date_key(self.as_of)):
            return _day_before(dd)
        return self.as_of

    def _title_display_name(self, tid, date=None, cid=None):
        """头衔的**显示名** = 名 + 层级词后缀 (v80 点4 B, 方案 §4.3)。

        `title()` 那条链走的是游戏 `TITLE_TIERED_NAME = "$NAME$$TIER$"` 的口径 ——
        日式惣領制伯爵领显示为「下总武士团」; 而 label 出口 (`official_title` /
        `_last_title_place`) 旧稿只用 `_name_at_date` = 「下总」, 于是**同一顶头衔
        在同一份材料里两副面孔**(「承袭下总武士团」vs「下总女士」), 成稿据此写出
        「妻子继为下总国司」这类混串 (用户问题4)。

        **窄口径** (控影响面): 只在层级词来自 `japan_feudal_government` 的
        flavorization 条目时追加 —— 即只解决用户报告的惣領制头衔。理由:
          · 律令制的头衔词是「国」, 而官职词是「国司」, 拼接会叠字
            (「下总**国国**司」), 故律令制**不加** (仍是「下总国司」, 与旧稿一致);
          · 西式/行政制头衔 (军区、雅尔国…) 的拼接影响面未评估, 本轮不动。
        """
        if tid is None:
            return ""
        name = self._name_at_date(tid, date) or self.title_base_name(tid)
        if not name:
            return ""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        tier = ""
        for pfx, tv in L.TIER_KEY_OF_PREFIX.items():
            if key.startswith(pfx):
                tier = tv
                break
        if not tier:
            return name
        if cid is None:
            cid = self._holder_at_or_now(self._lt.get(str(tid)) or {}, tid, date)
        if cid is None:
            return name
        gov = self._gov_for_word(cid, tid, date)
        fk = self._flavor_key("title", tier, cid, tid=tid, gov=gov, date=date)
        if not fk:
            return name
        e = (FZ.table().get("entries") or {}).get(fk) or {}
        if "japan_feudal_government" not in (e.get("governments") or []):
            return name
        v = L.loc(self.table, fk)
        if not v or v.startswith("$") or v.startswith("["):
            return name
        if _STATE_SUFFIX_RE.search(name):
            return name
        return f"{name}{v}"

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
            """头衔的 date (默认卒日) 时点国号 (v25: 死者按卒时国号)。
            v68 (问题5): 世族庄园 (`_nf_`) 与营地/职司同判 —— 家业名不是领地地名
            (否则「张氏」会被拼进官职词, 出「张氏刺史」)。"""
            if tid is None:
                return ""
            if self._is_estate_title(tid):
                return ""
            t = self._lt.get(str(tid)) or {}
            key = t.get("key") or ""
            if not key or key.startswith(("x_", "e_minister_")):
                return ""
            # v80 (点4 B): 惣領制头衔的显示名带「武士团」后缀 (「下总武士团女士」)
            return self._title_display_name(tid, anchor, cid=cid) \
                or self._name_at_date(tid, anchor) or self.title_base_name(tid)

        # v21: 同级多头衔的场合, 优先取「首要头衔」与死档 liege_title (游戏口径),
        # 不再按迭代序取第一个 — 嵬名仁孝同持 k_xia(夏) 与 k_hexi(河西) 时稳定得「夏」
        # (修复: 1179 年「河西宁令嵬名仁孝」应为游戏显示的「夏宁令」)。
        if tier_want is not None:
            _pt, ptid = self._primary_title_at(cid, as_of=anchor)
            if ptid is not None and self._eff_rank(ptid) == tier_want:
                nm = _place_nm(ptid)
                if nm:
                    return nm
            drec = (self.cache.get("characters") or {}).get(str(cid)) or {}
            ltid = (drec.get("death") or {}).get("liege_title")
            if ltid is not None and int(ltid) != ptid and \
                    self._eff_rank(int(ltid)) == tier_want:
                nm = _place_nm(int(ltid))
                if nm:
                    return nm
        intervals = self._hold_intervals(cid)
        best_tier, best_tier_nm = -1, ""
        best_late, best_late_nm = None, ""
        for tid, ivs in intervals.items():
            t = self._lt.get(str(tid)) or {}
            key = t.get("key") or ""
            if not key or key.startswith(("x_", "e_minister_")) \
                    or self._is_estate_title(tid):
                continue
            rank = self._eff_rank(tid)
            for (gain, _loss, _lt) in ivs:
                if not gain:
                    continue
                # v17: 地名取「当前」国号, 非上任日 (修复方案_汤利五问题.md 问题6
                # — 王言 886 年上任时国号关内, 角色窗显示当时/当前国号)。
                # v25: 「当前」锚点改为 anchor — 死者取卒日国号 (李漼卒于唐 → 唐皇帝)。
                # v80 (点4 B): 惣領制头衔同走显示名 (「下总武士团」)
                nm = self._title_display_name(tid, anchor, cid=cid) \
                    or self._name_at_date(tid, anchor) or self.title_base_name(tid)
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
                if not key or key.startswith(("x_", "e_minister_")) \
                        or self._is_estate_title(tid):
                    continue
                rank = self._eff_rank(tid)
                if tier_want is not None and rank == tier_want:
                    nm = self._name_at_date(tid, died)
                    if nm:
                        return nm
            # 无层级精确匹配: 取最高层级辖地
            b_t, b_nm = -1, ""
            for tid in ddom:
                t = self._lt.get(str(tid)) or {}
                key = t.get("key") or ""
                if not key or key.startswith(("x_", "e_minister_")) \
                        or self._is_estate_title(tid):
                    continue
                rank = self._eff_rank(tid)
                nm = self._name_at_date(tid, died)
                if nm and rank > b_t:
                    b_t, b_nm = rank, nm
            return b_nm
        return ""

    # v28b: 派系领袖头衔 (无地名, 单用不成称谓「领袖」) — 称谓交起义分支出词
    _FACTION_LEADER_FLAVORS = ("faction_leader", "faction_leader_male",
                               "faction_leader_female")
    # v36 (问题1): 层级前缀 flavor — 这些键的词是**统治者层级词** (王/国王/公爵/皇帝…),
    # 必须配地名才成称谓; 解不出地名时整词作废 (此前写出裸词「王丁文举」「公爵句就狼莫」)。
    _TIER_FLAVOR_PREFIXES = ("hegemon_", "emperor_", "king_", "duke_", "count_",
                             "baron_", "prince_", "princess_")

    def _has_current_landed_title(self, cid, anchor):
        """锚点仍持有州府 (c_) 以上的**真领地**头衔? (v36 — 朝廷职司「前」字判据)
        营地/庄园/朝廷职司/男爵领都不算真领地。"""
        for tid, ivs in (self._hold_intervals(cid, anchor) or {}).items():
            if not any(iv[1] is None for iv in ivs):
                continue
            key = (self._lt.get(str(tid)) or {}).get("key") or ""
            if key.startswith("e_minister_") or self._is_estate_title(tid):
                continue
            if self._TT_RANK.get(key[:2], 0) >= 2:
                return True
        return False

    def _ministry_office_at(self, cid, anchor, include_former=False):
        """朝廷职司官职词 (v36, 问题6): 在任 → 「礼部尚书」; include_former 且已去职
        → 「前礼部尚书」。多桩取层级最高、再取最晚获得者 (用户拍板2: 用最高头衔)。
        数据源只有 e_minister_* 头衔 — 存档 dead_data.flavor 对礼部/户部只给通用词
        「尚书」(minister_any_male), 部名必须由头衔补。"""
        best = None   # (rank, gain_key, word, still_held)
        for tid, ivs in (self._hold_intervals(cid, anchor) or {}).items():
            key = (self._lt.get(str(tid)) or {}).get("key") or ""
            if not key.startswith("e_minister_"):
                continue
            word = self._minister_office(tid)
            if not word:
                continue
            gains = [cl.date_key(iv[0]) for iv in ivs if iv and iv[0]]
            cand = (self._TT_RANK.get(key[:2], 0),
                    max(gains) if gains else (0, 0, 0), word,
                    any(iv[1] is None for iv in ivs))
            if best is None or (cand[0], cand[1]) > (best[0], best[1]):
                best = cand
        if best is None:
            return ""
        if best[3]:
            return best[2]
        return f"前{best[2]}" if include_former else ""

    def _title_flags(self, tid, date=None):
        """头衔**自身**的旗标集 (v81): 开府 (`shogun_flag`) 就是这样落在 e_japan 上的
        (实测 melt_1007: `landed_titles.13279.variables.data[0]`)。

        只认**当前状态** —— 熔件只存末档的 `variables`, 历史档期的旗标无从得知,
        故历史日期一律返回空集 (宁缺勿错; 用户已拍板不为它加逐档闩存)。"""
        if date is not None:
            last = self.cache.get("last_date")
            if last and cl.date_key(str(date)) < cl.date_key(str(last)):
                return set()
        t = self._lt.get(str(tid)) or {}
        return {str(v.get("flag"))
                for v in (((t.get("variables") or {}).get("data")) or [])
                if isinstance(v, dict) and v.get("flag")}

    def _char_flags(self, cid, date=None):
        """角色自身的旗标集 (v81): 在世者取 `alive_data.variables.data[].flag`
        (实测 melt_1007: 平干有带 `shogun_flag`); 死者存档会清掉 variables,
        故返回空集 —— 死者的词由烘死的 `dead_data.flavor` 承担。
        与 `_title_flags` 同一条「只认当前状态」的口径。"""
        if date is not None:
            last = self.cache.get("last_date")
            if last and cl.date_key(str(date)) < cl.date_key(str(last)):
                return set()
        ad = (self._chars.get(str(cid)) or {}).get("alive_data") or {}
        return {str(v.get("flag"))
                for v in (((ad.get("variables") or {}).get("data")) or [])
                if isinstance(v, dict) and v.get("flag")}

    def japan_top_office(self, cid, date=None):
        """日本最高头衔持有者的**官称裸词** (v81 问题3); 非此类持有者返回 ''。

        判据顺序 (每层都有实测, 见 `_JAPAN_OFFICE_FROM_FLAVOR` 的注释):
          ① 卒时窗口内的游戏烘死键 (`dead_data.flavor`) —— 上皇/幕府将军只有这里能得;
          ② (头衔, 政体) 直表 —— 律令制=关白 / 惣領制=太政大臣;
             另: 惣領制且**头衔带 `shogun_flag`** (已开府) → 幕府将军;
          ③ 在世者本人带 `shogun_flag` → 幕府将军 (头衔旗标缺失时的兜底)。
        返回裸词 (不带国号前缀) —— 用户 2026-09-29 拍板「e_japan 统治者前面不加日本」。"""
        if cid is None:
            return ""
        anchor = self._anchor_date(cid, date)
        _tier, tid = self._primary_title_at(cid, as_of=anchor)
        if not isinstance(tid, int):
            return ""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        if key not in self._JAPAN_TOP_TITLE_KEYS:
            return ""
        c = self._chars.get(str(cid)) or {}
        dd = c.get("dead_data") or {}
        fkey = dd.get("flavor") or ""
        if fkey and anchor and dd.get("date") \
                and abs(_date_ord(anchor) - _date_ord(dd["date"])) <= 1:
            w = self._JAPAN_OFFICE_FROM_FLAVOR.get(fkey)
            if w:
                return w
        gov = self._gov_for_word(cid, tid, anchor) or ""
        if not gov:
            gov = self._title_government_hist(tid, anchor) \
                or (self._lt.get(str(tid)) or {}).get("history_government") or ""
        if gov == "japan_feudal_government" \
                and self._SHOGUN_FLAG in self._title_flags(tid, anchor):
            return self._JAPAN_OFFICE_SHOGUN
        w = self._JAPAN_TOP_OFFICE_WORD.get((key, gov))
        if w:
            return w
        if self._SHOGUN_FLAG in self._char_flags(cid, anchor):
            return self._JAPAN_OFFICE_SHOGUN
        return ""

    def official_title(self, cid, date=None):
        """角色官职名: 「头衔名+官职词」(交州刺史/淄青节度使/青徐路观察使)。
        已死角色优先读存档 dead_data.flavor (游戏算好的键, 最准)。
        v13: flavor 只有官职词 (节度使/国司/关白) 无地名 — 用最后持有头衔的地名补全
        (颍州刺史/建宁节度使/出云国司), 与在世角色渲染一致。
        伊斯兰统治者特殊: 家族名+苏丹国/哈里发国 (复用 realm_name)。
        v15: 宗教领袖 (教宗) 优先 — 称谓直达, 不走「X国国王主教」神权词。
        v25: date 锚点 — 默认取卒日 (死者按其卒时国号称呼), 在世取 as_of;
        动态国号 (h_china 唐→秦) 据此按卒期正确落名。
        v36 (问题6, 用户拍板2): 朝廷职司 (六部/御史台/枢密院) 先行出词 —
        在任给「礼部尚书」, 已去职且无真领地者给「前礼部尚书」, 不再被通用 flavor 截断。
        v36 (问题1, 用户拍板5): 层级前缀 flavor (王/公爵/国王…) 解不出地名时整词作废,
        返回空串; 男爵领已在 _primary_title_at 处排除。"""
        rhw = self.religious_head_word(cid)
        if rhw:
            return rhw
        # v81 (问题3, 用户 2026-09-29 拍板): 日本最高头衔持有者 (e_japan / 高御座)
        # 走直表裸词 —— 「关白X」「太政大臣X」「幕府将军X」「上皇X」「天皇X」,
        # **不加**「日本政权/日本帝国」前缀 (见 `japan_top_office`)。
        _jw = self.japan_top_office(cid, date)
        if _jw:
            return _jw
        anchor = self._anchor_date(cid, date)
        # v36 (问题6, 用户拍板2): ① 在任朝廷职司先行出词 — 存档 flavor 对礼部/户部
        # 只给通用词「尚书」(minister_any_male), 部名要靠头衔补;
        # ② 已去职且锚点无真领地者写「前礼部尚书」。
        mo = self._ministry_office_at(cid, anchor)
        if mo:
            return mo
        if not self._has_current_landed_title(cid, anchor):
            mo = self._ministry_office_at(cid, anchor, include_former=True)
            if mo:
                return mo
        c = self._chars.get(str(cid)) or {}
        fkey = (c.get("dead_data") or {}).get("flavor")
        # v41 (问题1) 关键: `dead_data.flavor` 是游戏在角色死亡时**烘死**的词键,
        # 按末档政体算 (诺兰档: 迪特里希二世死于 1101, flavor 记的是行政制的
        # `duke_administrative_male_byzantine_group` = 将军), 于是他在 1082 年
        # 的封建时期事件里也被写成「上洛塔林吉亚将军」。改为: 先按 date 自身算
        # 职称; 只有当存档 flavor 与本日政体自洽时才采信它 (它仍是最准的
        # 游戏原词), 否则回落到按政体取词的路径。
        # v82 (P2): 日本最高头衔的烘死官称键 (关白/太政大臣/幕府将军/上皇/天皇) **只**从
        # `japan_top_office` 出词 —— 它已按「该日此人是否真持 e_japan/高御座」把关。
        # 通用烘死词通道没有这层门槛: 键是角色**卒时**按末档政体烘死的, 而日本全境的
        # `_character_government` 在整段战役里都是 `japan_administrative_government`,
        # `_dead_flavor_consistent` 只比政体前缀, 于是 874 年只持 `c_kazusa` 的
        # 田所浩二也被写成「日本政权关白」(实测 probe10: `_primary_title_at`=(county,
        # c_kazusa)、`japan_top_office`='' 、`_dead_flavor_consistent`=True)。
        if fkey and fkey not in self._JAPAN_OFFICE_FROM_FLAVOR \
                and self._dead_flavor_consistent(fkey, cid, anchor):
            v = L.loc(self.table, fkey)
            if v and not v.startswith("$") and not v.startswith("["):
                if fkey.startswith(self._TIER_FLAVOR_PREFIXES):
                    # v36 (问题1): 层级词必须配地名 (「新罗」+「国王」= 新罗国王);
                    # 头衔被存档剪除而解不出地名时, 裸层级词不成称谓 → 空串
                    # (由起义领袖/王子称号/显示名分支接管)。
                    place = self._last_title_place(cid, fkey, date=anchor)
                    if not place or v.startswith(place):
                        return ""
                    return f"{place}{v}"
                # v28b: 派系领袖头衔 (faction_leader_male/female「领袖」) 无地名,
                # 单用不成称谓 — 交 person_label 的起义称谓分支出词
                if fkey in self._FACTION_LEADER_FLAVORS:
                    return ""
                return v
        tier, tid = self._primary_title_at(cid, as_of=anchor)
        if tid is None or tier is None:
            # v13: 无地家族/庄园头衔 (x_nf_*「XX家族」) 的持有者官职词 —
            # 按文化选词 (日本: 当主; 高丽系: 户长; 其余天朝/选贤/行政: 乡绅)。
            # 修: 此前返回空, 家族领袖的官职从未传给模型。
            # v68 (问题5): 判据由 `x_nf_` 前缀改为 `_is_estate_title` —— 中国世族的
            # 庄园键是 `c_nf_`/`d_nf_` (伯爵领/公国级键名), 旧判据漏掉, 家业持有者
            # 落进领地支 → 「张氏」+「刺史」=「张氏刺史」(实测 973.1.12 死者 73985);
            # 家业一律称家族乡绅/当主/户长 (用户拍板: 统一称家族乡绅)。
            if tid is not None:
                if self._is_estate_title(tid):
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
        # v80 (点4 B): 惣領制头衔的显示名带「武士团」(「下总武士团女士」);
        # 其余头衔与旧稿逐字相同 (窄口径见 `_title_display_name`)
        name = self._title_display_name(tid, anchor, cid=cid) \
            or self._name_at_date(tid, anchor) or self.title_base_name(tid)
        # v41 (问题1): 政体按 anchor 日取 (逐档政体史) —— 旧稿读缓存里**末档**的
        # 政体, 封建期的神罗封臣因此被写成行政制的督军/将军/分区长。
        # v74 (问题2, 用户拍板): 改走 `_gov_for_word` —— 它比 `_character_government`
        # 多两层**可据的**来源: ① 头衔侧政体 (沿 de_facto_liege 上溯到领主,
        # `_title_government`); ② 死者 `dead_data.government`。旧稿只取持有者逐档
        # 政体史, 而缓存 `char_government_history` 只为**入目标集**的角色逐档记录,
        # 于是一批受害者政体取不到 (`gov=''`) → flavorization 只剩**无任何条件**的
        # `duke` 兜底条目 → 同一顶 `d_hitakami`(日高见国) 写出「日高见公爵」,
        # 而政体取得到的持有者写「日高见国司」。见 docs/方案_v74_田所三问题.md 问题2。
        gov = self._gov_for_word(cid, tid, anchor)
        if not gov:
            rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
            gov = (rec.get("landed") or {}).get("government") or ""
        if not gov:
            gov = (c.get("landed_data") or {}).get("government") or ""
        # v62: 日本最高头衔 (天皇座/e_japan) 的取词政体按**头衔侧**政体补 ——
        # 持有者政体史早于缓存窗口时 (藤原良房卒 879, 政体史 884 起) 上面三项皆空,
        # 旧稿落通用词「皇帝」, 于是同一顶 e_japan 在源融写「关白」、在藤原良房写「皇帝」。
        if ((self._lt.get(str(tid)) or {}).get("key") or "") in self._JAPAN_TOP_TITLE_KEYS:
            gov = self._gov_for_word(cid, tid, anchor) or gov
        _indep = self._is_independent(cid, anchor)
        word = self._office_word(tier, gov,
                                 independent=bool(_indep) if _indep is not None else True,
                                 female=self._is_female(cid),
                                 tid=tid, cid=cid, date=anchor)
        # v28b: 头衔无地名时 (营地/派系等 x_ 头衔) 官职词单用不成称谓 — 返回空串,
        # 由 person_label / 档案层回退显示名 (此前写出裸词「领袖」)
        if name and word:
            return f"{name}{word}"
        return name or ""

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
        """事件中某角色的「头衔名+名」— person_label 的 event 式入口
        (国号随年份: 903 是粤、更早是桂)。
        v42 (问题4, 用户拍板2): 主角改走 `event_name` (只出名字) —— 家族恩怨录的
        关系流水逐行重复「神圣罗马帝国巴西琉斯」, 与年表同一问题。"""
        if cid == self.cache.get("player_id"):
            return self.event_name(cid, date)
        return self.person_label(cid, date, "event")

    def _feud_other_house_phrase(self, cid, houses, fallback_label=""):
        """自指式恩怨句的对手方 → 「{对方家族}族人」(v43)。

        施事者的家族必是该关系对 `houses` 之一 (游戏侧 `HOUSE` 参数即取自
        CHAR 的家族, 见 `change_house_relation_effect`), 故对手方家族 = 另一个。
        判不出 (施事者无家族 / houses 不合规) 时返回 ''，整条略去。"""
        h = self._house_of_cid(cid)
        others = [x for x in (houses or []) if x != h]
        if h is None or len(others) != 1:
            return ""
        label = self._house_label(others[0]) or fallback_label or ""
        return f"{label}族人" if label else ""

    def _rerender_feud_event(self, raw, date, houses=None, other_label=""):
        """change_reason 原文 → 两端角色按日期重渲染的干净中文句。
        保留游戏动词 (劫掠了/囚禁了/处决了/成为朋友…), 只替换两端「称号+名」:
        '\x15ONCLICK:CHARACTER,38696 ... \x15high 国王\x15!，\x15high 崔佛...' →
        '瑞典国王崔佛·菲利普劫掠了粤王范承宗'。
        v29: 结果不可读 (rakaly 哨兵串 'MAX_RECURSIVE_DEPTH' / 未解析键) 时返回 ''。

        v43 (自指式条目): `murder_attempt` 与 `cuckoldry` 这两个 reason 在游戏脚本里
        把 `TARGET_CHAR` 传成了 `root` (`00_murder_effects.txt:709`、
        `00_adultery_effects.txt:129`), 而 root 常就是施事者本人 —— 两端于是烘焙
        成同一个角色, 渲染出「A试图谋杀A」这种句子。第二个人**没有写进存档**
        (关系对象只存已渲染的 change_reason), 事后无法还原, 故降级为族级对手方:
        「A试图谋杀{对方家族}族人」。判不出对方家族时整条略去。"""
        s = str(raw or "")
        if "\x15" not in s or "ONCLICK" not in s:
            return _clean_ck3_loc(s)
        ids = _FEUD_CHAR_RE.findall(s)
        self_ref = len(ids) >= 2 and len(set(ids)) == 1
        other_phrase = ""
        if self_ref:
            other_phrase = self._feud_other_house_phrase(int(ids[0]), houses,
                                                         other_label)
            if not other_phrase:
                return ""
        seen = [0]

        def _repl(m):
            seen[0] += 1
            cid = int(m.group(1))
            if self_ref and seen[0] == 2:
                return other_phrase
            return self._feud_role_title(cid, date)

        s2 = _FEUD_ROLE_RE.sub(_repl, s)
        return _clean_ck3_loc(s2)

    # v29: 恩怨史事件原文不可读时的程序重建 (缓存记忆 → 该日恩怨句)
    _FEUD_MEMORY_TYPES = ("house_feud_started_memory", "house_feud_ended_memory")
    _FEUD_START_TPL = {
        "family_killed": "{other}因族人{victim}被杀，与{my}结为世仇。",
        "family_executed": "{other}因族人{victim}被处决，与{my}结为世仇。",
        "family_imprisoned": "{other}因族人{victim}被囚，与{my}结为世仇。",
        "family_tortured": "{other}因族人{victim}受刑，与{my}结为世仇。",
        "family_title_revoked": "{other}因族人{victim}被褫夺头衔，与{my}结为世仇。",
        "family_land_seized": "{other}因族人{victim}领地见夺，与{my}结为世仇。",
        "family_title_usurped": "{other}因族人{victim}头衔被篡，与{my}结为世仇。",
    }

    def _house_of_cid(self, cid):
        """角色所属家族 id (缓存 → 熔件)。"""
        if not isinstance(cid, int):
            return None
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        h = rec.get("dynasty_house")
        if isinstance(h, int):
            return h
        c = self._chars.get(str(cid)) or {}
        h = c.get("dynasty_house")
        return int(h) if isinstance(h, int) else None

    def _dynasty_of_cid(self, cid):
        """角色所属宗族 id (家族 → dynasty); 查不到返回 None。"""
        hid = self._house_of_cid(cid)
        if hid is None:
            return None
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        did = rec.get("dynasty_id")
        if isinstance(did, int):
            return did
        return cl.dynasty_id_of(self.melt, hid)

    def _house_label(self, house_id):
        """家族名 → 史书式家族称谓 (程 → 程氏)。"""
        nm = (cl.house_name_zh(self.melt, house_id) or "") if house_id is not None else ""
        if not nm:
            did = cl.dynasty_id_of(self.melt, house_id) if house_id is not None else None
            nm = (cl.dynasty_name_zh(self.melt, did) or "") if did is not None else ""
        if not nm:
            return ""
        return nm if nm.endswith(("氏", "家", "家族", "部")) else f"{nm}氏"

    def _house_label_at(self, cid, date=None):
        """某人**在该日**的家族称谓 (v44 问题1): 沿革点优先, 无沿革回退家族 id 现值。

        v51: 入赘婚补注已简化为「，是入赘婚」(v55 起不用括注), 不再随句下发母方家族名 —— 本方法
        暂时没有调用点, 保留以备将来要写「属X氏」时按篇截止日取词 (阿德尔海德
        1118 年别立冯·亚琛氏后, 末档篇不得再写「属诺兰氏」)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        if rec.get("house_history"):
            h, dn = self._house_names_at(cid, date)
            nm = h or dn
        else:
            nm = self._house_label(self._house_of_cid(cid)) if self._house_of_cid(cid) else ""
        if not nm:
            return ""
        return nm if nm.endswith(("氏", "家", "家族", "部")) else f"{nm}氏"

    def _feud_event_fallback(self, my_houses, other_house, date, other_label):
        """恩怨史事件原文不可读时, 由缓存记忆重建该日句 (程序优先) —
        house_feud_started_memory 的 attacker/victim/house_feud_reason 给出
        「谁对谁做了什么」, 加害者在我方、受害者在他方时即本段恩怨之始。"""
        dk = str(date or "")
        my_house = None
        for h in my_houses:
            my_house = h
            break
        my_label = self._house_label(my_house) or "主角家族"
        other = other_label or self._house_label(other_house) or "对方家族"
        for _cid, rec in (self.cache.get("characters") or {}).items():
            if not isinstance(rec, dict):
                continue
            for mem in rec.get("memories") or []:
                if str(mem.get("creation_date") or "") != dk:
                    continue
                t = mem.get("type") or ""
                if t not in self._FEUD_MEMORY_TYPES:
                    continue
                parts = mem.get("participants") or {}
                attacker, victim = parts.get("attacker"), parts.get("victim")
                ah = self._house_of_cid(attacker)
                vh = self._house_of_cid(victim)
                if not ((ah in my_houses and vh == other_house)
                        or (vh in my_houses and ah == other_house)):
                    continue
                if t == "house_feud_ended_memory":
                    return f"{other}与{my_label}的世仇就此化解。"
                if ah not in my_houses:
                    continue                    # 只说本方视角的恩怨之始
                # v42 (问题4): 主角只出名字 (同家族恩怨录其余各行)
                an = self.event_name(attacker, dk) if attacker else ""
                vn = self.event_name(victim, dk) if victim else ""
                reason = ""
                for v in mem.get("vars") or []:
                    if v.get("flag") == "house_feud_reason":
                        reason = str(v.get("value") or "")
                        break
                tpl = self._FEUD_START_TPL.get(reason)
                if tpl and vn:
                    return tpl.format(other=other, victim=vn, my=my_label,
                                      attacker=an)
                if vn:
                    who = f"{vn}遭{an}加害" if an else f"族人{vn}受害"
                    return f"{other}因{who}，与{my_label}结为世仇。"
        # 退一步: 该日两家的结仇记忆
        for _cid, rec in (self.cache.get("characters") or {}).items():
            if not isinstance(rec, dict):
                continue
            for mem in rec.get("memories") or []:
                if str(mem.get("creation_date") or "") != dk:
                    continue
                if mem.get("type") not in ("became_rivals", "became_grudge",
                                           "became_nemesis"):
                    continue
                parts = mem.get("participants") or {}
                ids = [v for v in parts.values() if isinstance(v, int)]
                houses = [self._house_of_cid(v) for v in ids]
                if any(h in my_houses for h in houses) \
                        and any(h == other_house for h in houses):
                    try:
                        s = _mem_sentence(self, int(_cid), mem)
                    except (TypeError, ValueError):
                        s = ""
                    if s and loc_text_ok(s):
                        return s
        return ""

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
        loss = None
        for (g, l, _lt) in (self._hold_intervals(cid, date).get(tid) or []):
            gain, loss = g, l
            break
        end = date or self.as_of
        mid = self._span_mid(gain, end)
        nm = self._name_at_date(tid, mid) or self._name_at_date(
            tid, end) or self.title_base_name(tid)
        # v47: 词取**任期中点**之政体 (名字本来就用中点) —— 任期首日可能还在
        # 无地冒险者政体上 (克里斯托弗 1086.1.1 夺得神罗, 政体史到 1087 才观察到
        # 封建制), 拿首日取词会把「前神圣罗马帝国巴西琉斯」降成通用「皇帝」。
        w = self._ruler_word_at(cid, tid, self._span_mid(gain, loss or end))
        if nm and w and not nm.endswith(w):
            return f"{nm}{w}"
        return nm

    # ------------------------------------------------------------------
    # v28b: 「头衔+姓名」统一组装 — 全项目人物称谓只此一处出词
    # (kin_label / 隐事句 / 要员隐事 / 恩怨事件 / 宫廷僚属行 / 时间线 / 记忆句
    #  都调 person_label, 别处一律不再拼「官职+姓名」)
    # ------------------------------------------------------------------
    # 名不可考的占位串 (name_or / biography._name_or 的兜底) — 不进称谓
    _PLACEHOLDER_NAMES = ("某人", "一位人物", "（名讳不详）")
    # 起义派系 → 称谓词: 游戏本地化键 FACTION_PEASANT_TITLE_NAME「农民叛乱」/
    # FACTION_POPULIST_REVOLT_TITLE_NAME「民粹暴动」/FACTION_NOMADIC_REVOLT_TITLE_NAME
    # 「游牧民叛乱」; 用户定稿 2026-09-10 一律用「起义」(与 peasant_leader_title_name
    # 「X巾起义」同词)。
    _UPRISING_WORDS = {
        "peasant_faction": "农民叛乱",
        "escalated_peasant_faction": "农民起义",
        "populist_faction": "民粹暴动",
        "nomadic_faction": "游牧民叛乱",
    }

    def faction_word(self, cid):
        """角色为起义派系领袖时的起义名 (「农民起义」), 否则 ''。
        数据来自 cache["factions"] (逐档差分 + v37 起义头衔路线; 旧缓存无此字段时返回 '')。"""
        rec = (self.cache.get("factions") or {}).get(str(cid)) or {}
        return self._UPRISING_WORDS.get(rec.get("type") or "", "")

    def uprising_info(self, cid):
        """起义领袖的起事信息 (v37, 问题8): {"base", "counties", "target", "word"} 或 {}。

        - base: 起事州府名 — 起义头衔 `capital` (剧本头衔「农民叛乱」的起事州, 带
          建立日与领袖), 落在 cache["factions"][cid]["base"]["county_name"]; 缺失时
          用 county id 现查头衔名。**这是「死者在哪」的唯一真数据** —— 此前事实层不读,
          无地点的死者被模型就近安放到主角家业所在 (旧稿慈州 / 新稿宾州)。
        - counties: 该次起事参与的州府数 (「聚众N州」), 由 faction title_members 计。
        - target: 反抗对象 — 先取该对象的最高头衔国号 (唐皇朝), 退其称谓 (唐皇帝李漼)。
        """
        rec = (self.cache.get("factions") or {}).get(str(cid)) or {}
        if not rec:
            return {}
        out = {}
        word = self._UPRISING_WORDS.get(rec.get("type") or "", "")
        if word:
            out["word"] = word
        base = rec.get("base") or {}
        nm = (base.get("county_name") or "").strip()
        if not nm and isinstance(base.get("county"), int):
            nm = self.title_base_name(base["county"]) or ""
            if nm.startswith(("c_", "b_", "x_")):
                nm = ""
        if nm:
            out["base"] = nm
        counties = rec.get("counties") or []
        if counties:
            out["counties"] = len(counties)
        tgt = rec.get("target")
        if isinstance(tgt, int):
            _t, tid = self._primary_title_at(tgt)
            rn = self.title(tid) if tid is not None else ""
            if rn and rn.startswith(("c_", "b_", "x_")):
                rn = ""
            out["target"] = rn or self.person_label(tgt, date=self.as_of, style="brief")
        return out

    # v37 (问题8): 「乱连N州」的规模上限 —— 超出者多是 escalated 民变 (存档
    # title_members 动辄 30–40 州, 那是整场民变的波及面, 不是该首领的聚众), 一律不写。
    _UPRISING_COUNT_CAP = 12

    def uprising_line(self, cid, name=None):
        """起义领袖的起事独立行 (v37, 问题8): 「丁文举起于渠州，乱连六州，反抗唐皇朝。」

        与既有「X死于Y。」同形 (独立行, 不用名词括注同位语); 三项皆无返回 ''。"""
        info = self.uprising_info(cid)
        if not info:
            return ""
        who = name or self.name_with_regnal(cid) or self.name_or(cid)
        if not who:
            return ""
        parts = []
        if info.get("base"):
            parts.append(f"起于{info['base']}")
        n = info.get("counties") or 0
        if 2 <= n <= self._UPRISING_COUNT_CAP:
            parts.append(f"乱连{_count_zh(n)}州")
        if info.get("target"):
            parts.append(f"反抗{info['target']}")
        return f"{who}{'，'.join(parts)}。" if parts else ""

    @property
    def _name_logs(self):
        """本线程生效中的出词登记器栈 (可嵌套; 见 `log_names`)。"""
        st = getattr(self._tls, "logs", None)
        if st is None:
            st = []
            self._tls.logs = st
        return st

    def log_names(self):
        """v45 (档 B): 开启本行的称谓出词登记 (上下文管理器, 可嵌套)。

        用法: `with f.log_names() as lg: text = _mem_sentence(...)` →
        `f.index_names(text, lg)` 把这一行与它用到的 (cid, label) 记进 `name_index`。
        有了这张表, 板块期就能把人名**确切地**改写成「定语+人名」, 不必对已烘定
        的字符串做正则猜测 (档 C 的同名子串误插问题由此消失)。"""
        return _NameLog(self)

    def index_names(self, text, log, owner=None):
        """把一行文本与它用到的 (cid, label) 登记进 `name_index`。

        v63: `owner` = 本行**主语** (句子讲的是谁, 一般是记忆/死亡记录的持有人)。
        板块期给句中第三方人名出定语时以它为准 (见 `biography._kin_tag_line`)。"""
        if text and log is not None and log.items:
            self.name_index[text] = [list(x) for x in log.items]
            if owner is not None:
                try:
                    self.line_owner[text] = int(owner)
                except (TypeError, ValueError):
                    pass
        return text

    def _log_label(self, cid, label):
        """`person_label` 出词时向所有生效的登记器各记一条 (v45 档 B)。"""
        if not label or not self._name_logs:
            return
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return
        for lg in self._name_logs:
            lg.items.append((cid, label))

    # ---- v64 (问题5): 勋号骑士称谓 -------------------------------------------
    # 用户 2026-09-25 拍板: 「只在涉及到某个宫廷角色带有勋号时，在名字前面加上勋号」。
    # 故勋号不进独立板块、不加新行, 而是收进**唯一称谓出口** `person_label` ——
    # 谁戴着勋号, 他出现的地方 (档案名号句/年表行/隐事句/亲缘句) 名字前就带勋号。
    #
    # 存档字段 (melt["accolades"]["database"]): `name` 是**已经渲染好的中文串**
    # (「曼苏拉之云雀」「葛洛夫枪手」, 不必拼本地化键); `owner` = 授予的领主;
    # `acclaimed` = 当前勋号骑士; `history` = 新→旧的 [{acclaimed, date}] 更替史
    # (末条 = 立号/首位受勋日), 故「某人在某日戴哪个勋号」可由 history 逐段定日。
    # 时代性: 一律按 date 取 (十年传记不会把十年后的勋号写到十年前的人身上)。
    def _accolade_index(self):
        """{角色id: [(起始日|None, 勋号名), …]} —— 勋号骑士更替史 (惰性建一次)。"""
        if getattr(self, "_acc_idx", None) is not None:
            return self._acc_idx
        idx = {}
        db = (self.melt.get("accolades") or {}).get("database") or {}
        if isinstance(db, dict):
            for _aid, a in db.items():
                if not isinstance(a, dict):
                    continue
                nm = str(a.get("name") or "").strip()
                if not nm:
                    continue
                hist = []
                for h in (a.get("history") or []):
                    if not isinstance(h, dict):
                        continue
                    c, dd = h.get("acclaimed"), h.get("date")
                    if isinstance(c, int) and dd:
                        hist.append((str(dd), c))
                if not hist:
                    # 无更替史 (旧档/脚本授予): 用当前 acclaimed, 无日期 (任何 date 都算)
                    c = a.get("acclaimed")
                    if isinstance(c, int):
                        idx.setdefault(c, []).append((None, nm))
                    continue
                hist.sort(key=lambda x: cl.date_key(x[0]))
                for dd, c in hist:
                    idx.setdefault(c, []).append((dd, nm))
        self._acc_idx = idx
        return idx

    def accolade_word_at(self, cid, date=None):
        """该角色在 date 所戴的**勋号名** (无则 '') —— 供称谓前置。"""
        if cid is None:
            return ""
        try:
            rows = self._accolade_index().get(int(cid)) or []
        except (TypeError, ValueError):
            return ""
        if not rows:
            return ""
        cut = date or self.as_of or self.cache.get("last_date")
        lim = cl.date_key(cut) if cut else None
        best, best_dk = "", None
        for dd, nm in rows:
            if dd is None:            # 无日期的兜底行: 仅在没有带日期的行时生效
                if best_dk is None:
                    best, best_dk = nm, (0, 0, 0)
                continue
            dk = cl.date_key(dd)
            if lim is not None and dk > lim:
                continue
            if best_dk is None or dk >= best_dk:
                best, best_dk = nm, dk
        return best

    def person_label(self, cid, date=None, style="full"):
        """人物称谓统一入口 (v28b)。style:
        - "full": 家室/世系 (kin_label) — 「[前X，]现职Y 姓名」;
        - "brief": 隐事/把柄/要员隐事/时间线 — 「现职Y 姓名」(前头衔不前置);
        - "event": 恩怨史事件 (v14) — 现职按**事件日期**取 (死者按事件时官职);
        - "office": 宫廷僚属行 — 与 brief 同形 (用户决策 2026-09-10:
          姓在前的名一律保留宗族姓, 西方名保留家族姓)。
        ① 宗教领袖 → 「教宗X」; ② 天皇座子女称号已并入姓名, 不叠前缀;
        ③ 起义领袖 (农民/民粹/游牧) 无领地头衔时 → 「农民起义领袖X」;
        ④ 名不可考 (占位串) → 返回 '' 由调用方整条略去;
        ⑤ 无头衔者 → full 式按父/母头衔取王子/公主称号, 其余只给显示名;
        ⑥ v64 (问题5): 戴勋号者 (accolades.database 的 `acclaimed`) → 勋号紧接在
           名字前面 (「葛洛夫枪手贝奥武夫」), 时代按 date 取; 主角的年表行仍只出名字。"""
        if cid is None:
            return ""
        key = (int(cid), date or "", style)
        if key in self._label_cache:
            out = self._label_cache[key]
            self._log_label(cid, out)
            return out
        out = self._person_label_uncached(cid, date, style)
        self._label_cache[key] = out
        self._log_label(cid, out)
        return out

    def _person_label_uncached(self, cid, date, style):
        nm = self.name_with_regnal(cid, date)
        if not nm or nm in self._PLACEHOLDER_NAMES:
            return ""
        # v42 (问题4): 年表事实行 —— 主角只写名字 (「邪魔克里斯托弗·诺兰」)。
        # 头衔已在《传主档案》(office/label + 历任/政体/直辖句) 给足, 年表逐行重复
        # 只耗注意力 (终传 249 条里 241 条带全称谓); 东方名序由 name_with_regnal
        # 直出姓名。其余人仍走 brief 式 (官职/称号+名), 供辨认。
        if style == "timeline" and cid == self.cache.get("player_id"):
            return nm
        if self._tenno_prince_word(cid, date):
            return nm
        # v64 (问题5): 戴勋号者 —— 勋号紧接在**名字前面** (「葛洛夫枪手贝奥武夫」),
        # 与官职/称号并列而不互相顶替; 主角的年表行仍只出名字 (v42 口径)。
        acc = self.accolade_word_at(cid, date)
        pn = f"{acc}{nm}" if acc else nm
        rhw = self.religious_head_word(cid)
        if rhw:
            return f"{rhw}{pn}"
        off = self._event_office(cid, date) if style == "event" \
            else self.official_title(cid, date)
        if not off:
            # v28b: 无领地头衔者按父/母头衔取王子/公主称号 (与档案一致)
            off = self.prince_title(cid, date) or ""
        if not off:
            # v28b: 起义领袖 (无领地头衔) — 以起义名为称谓
            word = self.faction_word(cid)
            if word:
                off = f"{word}领袖"
        if style == "full":
            return self._full_label(cid, date, off, pn)
        return f"{off}{pn}" if off else pn

    def event_name(self, cid, date=None):
        """年表/事实行的**主语名** (v42 问题4): 主角只出名字, 其余人出 brief 称谓。
        单一出口 —— 凡进入 `facts["timeline"]` 或隐事主题/恩怨流水的名字都走这里,
        使「主角头衔逐行泛滥」不再可能; 与《传主档案》的全称谓分工明确:
        档案负责**一次**立名, 年表负责**逐条**叙事。"""
        if cid is None:
            return ""
        return self.person_label(cid, date, style="timeline") \
            or self.name_with_regnal(cid, date)

    def _event_office(self, cid, date):
        """恩怨史事件里的现职 (v14): 按事件日期取「头衔名+官职词」; 政体从头衔侧取
        (角色 landed 在死者/时点会被清空, 头衔政体更稳)。"""
        tier, tid = self._primary_title_at(cid, as_of=date)
        if tid is None or tier is None:
            return ""
        tname = self._name_at_date(tid, date) or self.title_base_name(tid)
        if not tname:
            return ""
        _indep = self._is_independent(cid, date)
        word = self._office_word(tier, self._gov_for_word(cid, tid, date),
                                 independent=bool(_indep) if _indep is not None else True,
                                 female=self._is_female(cid), tid=tid, cid=cid,
                                 date=date)
        return f"{tname}{word}" if word else tname

    def _full_label(self, cid, date, cur, nm):
        """full 式称谓 (v27 用户定稿): 只在**前头衔层级高于现头衔**时把前头衔前置,
        形态「前拜占庭皇帝，安卡拉伯爵君士坦丁十一」; 现头衔缺失时只写
        「前高昌国王毗伽庞特勤」。同一头衔 (同一 tid) 的今昔两种叫法不算前头衔 —
        塔坦尼·布兰 现职「可萨布兰部可敦」, 其 881–893 年的 3981 就是同一头衔的
        前身, 一律只写现职。无头衔者按父/母头衔取王子/公主称号。

        v46 (问题1): 现职/前头衔/前头衔文本**三处共用同一个 anchor**
        (`_anchor_date`, 卒后日期折到卒前一日) —— 旧稿三处各自用入参 date,
        死者于是被读成「当日无现职」而把一生最高头衔提升成「前头衔」。"""
        anchor = self._anchor_date(cid, date)
        # 现职为空时不存在「现头衔」, 不能把「最近一段最高位持有」当成现职排除掉
        # (否则 毗伽庞特勤 的 高昌 会被自己挤掉, 只剩更低的 喀喇沙尔公国)。
        cur_tid = self._current_title_tid(cid, anchor) if cur else None
        cur_rank = 0
        if cur_tid is not None:
            key = (self._lt.get(str(cur_tid)) or {}).get("key") or ""
            cur_rank = self._TT_RANK.get(key[:2], 0)
        former_tid = self._former_high_title(cid, anchor, exclude_tid=cur_tid)
        f_rank = 0
        if former_tid is not None:
            key = (self._lt.get(str(former_tid)) or {}).get("key") or ""
            f_rank = self._TT_RANK.get(key[:2], 0)
        if cur and former_tid is not None and f_rank > cur_rank:
            ft = self._former_title_text(cid, former_tid, anchor)
            if ft and ft != cur:
                return f"前{ft}，{cur}{nm}"
            return f"{cur}{nm}"
        if cur:
            return f"{cur}{nm}"
        if former_tid is not None:
            ft = self._former_title_text(cid, former_tid, anchor)
            if ft:
                return f"前{ft}{nm}"
        pw = self.prince_title(cid, anchor)
        if pw:
            return f"{pw}{nm}"
        return nm

    def kin_label(self, cid, date=None):
        """亲属/世系/妻族专用称谓 (v27) — person_label 的 full 式入口:
        「[前X，]现职Y 姓名」。

        v41 (问题1): date 缺省取 `self.as_of` —— 传记事实一律按本篇截止日取官职词
        (封建期的神罗封臣写「上洛塔林吉亚公爵」, 行政期才写「将军」);
        传入 None 时不再落到缓存里的末档政体。"""
        return self.person_label(cid, date or self.as_of, "full")

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
        """庄园持有人称谓 (v41b 用户拍板1: 用游戏原文)。
        东亚三支取自游戏本地化键 (日本 当主/女士, 高丽系 户长/夫人,
        天朝 乡绅/夫人); 其余 (欧洲/行政制世族) 用 `game_concept_house_head`
        = 家主 —— 「乡绅」只属天朝分支, 加在希腊皇帝身上会把模型带进中华乡绅门第。"""
        female = self._is_female(cid)
        tpl = self.culture_template(cid) or ""
        if tpl == "japanese":
            key = "estate_holder_female_japanese" if female else "estate_holder_male_japanese"
        elif tpl in self._KOREAN_ESTATE_TPL:
            key = "estate_holder_female_korean" if female else "estate_holder_male_korean"
        elif tpl in self._EAST_ASIAN_ESTATE_TPL:
            key = "celestial_estate_holder_female" if female else "celestial_estate_holder_male"
        else:
            key = "game_concept_house_head"
        v = L.loc(self.table, key)
        if v and not v.startswith("$") and not v.startswith("["):
            return v
        if key == "game_concept_house_head":
            return "家主"
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

    def _my_realm_tids(self):
        """主角所处政权的头衔 id 集 (v34, 问题3):
        主角首要头衔 + 其上位链上的全部头衔。朝廷职司 (`e_minister_*`) 的
        `de_facto_liege` 落在这个集合里, 才算「主角所处朝廷的职司」。
        独立领主上位链到顶, 集合即其自身领地头衔 → 别国职司不再混入。

        v61 (问题2): **已卒传主**补一条 `held_through` 路子 —— 终传 (as_of 为空) 取卒日
        (`player_death.date`; 缺则末档日), 十年篇取 as_of。旧稿只认「末档仍在持」,
        传主卒于末档时头衔全带 loss 日 ⇒ 本函数返回空集 ⇒ 下面两处职司门槛
        的 `if mine and …` 被短路 (fail-open), 全图 `e_minister_*` (唐六部) 混入。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return set()
        out = set()
        _tier, ptid = self._primary_title_at(pid)
        if ptid is None:
            cut = (self.as_of
                   or (self.cache.get("reign_end") or {}).get("date")   # v76: 让位日
                   or (self.cache.get("player_death") or {}).get("date")
                   or self.cache.get("last_date"))
            if cut:
                _tier, ptid = self._primary_title_at(pid, held_through=cut)
        if ptid is not None:
            out.add(int(ptid))
            for tid, _h in self.liege_chain(ptid) or []:
                out.add(int(tid))
        if not out:
            # 无地冒险者等无头衔情形: 取玩家营地/庄园头衔
            ld = ((self.cache.get("characters") or {}).get(str(pid)) or {}).get("landed") or {}
            for x in ld.get("domain") or []:
                if isinstance(x, int):
                    out.add(int(x))
        return out

    def _realm_title_set(self):
        """兼容别名 (v34): 见 `_my_realm_tids`。"""
        return self._my_realm_tids()

    def _ever_held_title(self, tid):
        """该高位头衔是否「存在过」(v64, 问题4) —— 三档任一成立即算:

        ① `history` 非空 (有人做过它的主人);
        ② 此刻有 `holder`;
        ③ `realm_history` 快照里曾见非空持有者 —— 项目 v11 已注明 title history
           会被剪除 (「如已毁的王国」), 故 ③ 是不可省的补充判据 (实测本档这一档
           为空集, 但换档即可能出现)。

        用途: 朝局事实面的法理回落 (`_realm_facts._up_liege`) 只许落在存在过的
        头衔上 —— 存档对**从未创建**的空衔同样给 `de_jure_liege` (本档 177 个高位
        空衔: e_tartaria / e_turan / e_britannia / e_scandinavia …), 旧稿照名写出
        「为鞑靼帝国封臣」, 模型据此编出不存在的帝国。"""
        if tid is None:
            return False
        t = self._lt.get(str(tid)) or {}
        if t.get("history") or t.get("holder") is not None:
            return True
        if getattr(self, "_rh_seen_tids", None) is None:
            seen = set()
            for h in (self._realm_snaps or []):
                for _t, _h in (h.get("holders") or {}).items():
                    if _h is None:
                        continue
                    try:
                        seen.add(int(_t))
                    except (TypeError, ValueError):
                        continue
            self._rh_seen_tids = seen
        try:
            return int(tid) in self._rh_seen_tids
        except (TypeError, ValueError):
            return False

    def legal_children(self, cid):
        """cid 的**法理子女** id 集 (v34, 问题8, 用户拍板):
        存档 `family.father` 含 cid 的孩子 — 不论其是否另有实父 (非婚生亦然),
        这些孩子都算 cid 的子女, 归《本纪》与父亲的家门清单。
        法理父是**别人**的孩子 (妻室与他人所出而不入其户籍者) 不在其中,
        归《家室列传》作妻子的子女。
        v44 (问题3): 认亲字段**按本人性别取** —— 女性主角取其子女的 `mother`
        字段。旧实现只认 `father`, 于是女主亲生的子女全被判成「配偶与他人所出」
        (阿德尔海德档四个子女被写成「此数人之法理父并非主角」, 模型由此得出
        「主角的儿子与主角的丈夫没有关系」)。"""
        out, _ = self.legal_children_ex(cid)
        return out

    def legal_children_ex(self, cid):
        """同 `legal_children`, 另返回「是否有家谱数据」。
        无家谱数据时调用方应保留原名单 (不能把无数据当成无子女)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fam = rec.get("family") or {}
        kids = [k for k in (fam.get("child") or []) if isinstance(k, int)]
        if not kids:
            return set(), False
        # v44 (问题3): 本人为母 → 比对孩子 family 的 mother 字段; 为父 → father。
        # 无性别记载时两者都比 (宁取并集, 不把亲生子女判出门外)。
        female = self._is_female(cid)
        want = ["mother"] if female else ["father"]
        if not female and rec.get("female") is None:
            want = ["father", "mother"]
        out = set()
        for k in kids:
            kf = ((self.cache.get("characters") or {}).get(str(k)) or {}).get("family") or {}
            for w in want:
                if cid in [x for x in (kf.get(w) or []) if isinstance(x, int)]:
                    out.add(k)
                    break
        return out, True

    def wife_other_children(self, cid):
        """配偶与他人所出、且**本人不是其父/母**的孩子 (v34, 问题8; v44 问题3):
        这些是《家室列传》里的「配偶的子女」, 不进主角的家门清单。
        本人为女时比对孩子 `mother` (旧实现一律比对 `father`, 女主亲生子女
        因此全落进这里)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fam = rec.get("family") or {}
        legal, has = self.legal_children_ex(cid)
        if not has:
            return set()
        out = set()
        for sid in dict.fromkeys((fam.get("primary_spouse") or [])
                                 + (fam.get("spouse") or [])):
            if not isinstance(sid, int):
                continue
            srec = (self.cache.get("characters") or {}).get(str(sid)) or {}
            for k in (srec.get("family") or {}).get("child") or []:
                if isinstance(k, int) and k not in legal:
                    out.add(k)
        return out

    def wife_other_children_line(self, cid, kids=None):
        """配偶与他人所出的孩子 → **可直接落笔的一句** (v74 问题3, 用户拍板)。

        旧稿由 `biography._profile_lines` 拼成「妻室另育有和气敬子、和气孝成、藤原咲，
        此数人之**法理父**并非主角。」——「法理父」三字把模型推向「丈夫是法理父」的
        错解 (第 1 个十年成稿即写「法理父为浩二，生父则为和气丰永」，与游戏数据相反)。
        游戏口径 (见 docs/调研_v74_大和私生子与法理父.md): 公开私生的孩子
        `father` 直接被置为真父、随生父之氏, **不存在**法理父与生物父的分野。
        故此处**按生父分人直陈**, 全句不出现「法理父」:

            「藤原诸子与和气氏当主和气丰永生子和气敬子、和气孝成；
              与远江国司藤原玄上生女藤原咲。此三人各随生父之氏。」

        单亲查不到生父时退回「<生母>另育有<子女>，随其生父之氏」的简式。
        返回 '' 表示无料 (调用方整句省略)。"""
        chars = self.cache.get("characters") or {}
        kids = list(kids if kids is not None else self.wife_other_children(cid))
        if not kids:
            return ""
        # (生母, 生父) → [孩子 id]，按 (生母首次出现, 生父首次出现) 稳定排序
        groups = {}
        order = []
        for k in sorted(kids, key=lambda x: str(x)):
            rec = chars.get(str(k)) or {}
            kf = rec.get("family") or {}
            mom = (kf.get("mother") or [None])[0]
            dad = (kf.get("real_father") or kf.get("father") or [None])[0]
            key = (mom, dad)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(k)
        parts = []
        total = 0
        _kids_all = []
        prev_mom = None
        for (mom, dad) in order:
            mname = self.kin_label(mom) if isinstance(mom, int) else ""
            dname = self.kin_label(dad) if isinstance(dad, int) else ""
            sons, daughters = [], []
            for k in groups[(mom, dad)]:
                if not self.name(k):
                    continue
                _kids_all.append(k)
                (daughters if self._is_female(k) else sons).append(self.kin_label(k))
            bits = []
            if sons:
                bits.append("子" + "、".join(sons))
            if daughters:
                bits.append("女" + "、".join(daughters))
            if not bits:
                continue
            body = "、".join(bits)
            total += len(sons) + len(daughters)
            if dname:
                if mname and mom == prev_mom:
                    lead = f"又与{dname}生"          # 同一生母的第二个情夫
                elif mname:
                    lead = f"{mname}与{dname}生"
                else:
                    lead = f"与{dname}生"
            else:
                lead = f"{mname}另育有" if mname else "另育有"
            parts.append(f"{lead}{body}")
            prev_mom = mom
        if not parts:
            return ""
        if total == 1:
            n = "此女" if self._is_female(_kids_all[0]) else "此子"
        elif total == 2:
            n = "此二人"
        elif total == 3:
            n = "此三人"
        else:
            n = f"此{total}人"
        return "；".join(parts) + f"。{n}各随生父之氏。"

    def _current_ministers(self, date=None):
        """朝廷职司在 date (缺省熔件当前) 的持有者 →
        ['兵部尚书任清', …] (朝局风云录·朝廷职司用)。
        v28: 输出形态改为「官职词+人名」— 此前「兵部：任清（兵部尚书）」把
        「部名」与「官职词」写了两遍。官职词取不到时才退「部名：人名」。
        v28b: **按 as_of 取时任者** — 此前一律取熔件当前 holder, 十年传记会把
        后来的任命写进早期十年 (田所2 @878 写出 883 年才上任的宰相)。
        v34 (问题3): **只收主角所处政权的职司** — 此前遍历全图所有
        `e_minister_*`, 于是贝内文托亲王的《朝局风云录》里永远挂着唐六部
        (实测 9 个职司的 de_facto_liege 全为 h_china)。
        v61 (问题2): 过滤改 **fail-closed** —— 政权判不明 (`mine` 空) 时一律不收。
        旧写法 `if mine and lc not in mine` 在空集时把整条过滤短路, 于是传主卒于末档时
        唐六部九卿 (与其隐事) 又混进《朝局风云录》。"""
        d = date if date is not None else self.as_of
        mine = self._my_realm_tids()
        out = []
        for tid, t in self._lt.items():
            if not isinstance(t, dict):
                continue
            key = t.get("key") or ""
            if not key.startswith("e_minister_"):
                continue
            lc = t.get("de_facto_liege")
            if lc not in mine:      # v61: mine 空 ⇒ 一律不收 (宁缺勿滥)
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
        """朝廷职司 (e_minister_*) 在 date 的持有者 id 列表 (要员隐事取材用)。
        v34 (问题3): 与 `_current_ministers` 同口径 — 只取主角所处政权的职司。
        v61 (问题2): 同 `_current_ministers` 改 fail-closed (mine 空 ⇒ 不收)。"""
        d = date if date is not None else self.as_of
        mine = self._my_realm_tids()
        out = []
        for tid, t in self._lt.items():
            if not isinstance(t, dict):
                continue
            if not (t.get("key") or "").startswith("e_minister_"):
                continue
            lc = t.get("de_facto_liege")
            if lc not in mine:      # v61: mine 空 ⇒ 一律不收 (宁缺勿滥)
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

    def _first_seen_note(self, rec):
        """隐事年份短语 (v80 点2): 「879年为外人所知」; 无年可给返回 ''。

        v35 之前是「自879年见载」并以括注形态 `（自879年见载）` 进入正文 —— 「见载」
        是数据管道词, 模型照抄成满篇考据按语 (德圣塔实测「何时见载、何时知情, 本篇
        未著其年」)。v35 改成「N年见于记载」仍留着「记载」这个词根, 模型据此正反两用
        (田所定治实测成稿「书上只写…四字」「此事是否已入定治之耳，书中」) —— v80 点2
        改与世界内措辞一致: 只说「N年为外人所知」(与 `RULES["secret"]` 的
        「此事在何年为外人所知」同口径), 不出现「记载/见载/未载」。
        首档即见 (数据起点前已有) 无年份可给 → 返回 ''; 提示词侧不再点名索要年份,
        模型手里没有年份时也就不会去编「未著其年」。"""
        fs = rec.get("first_seen")
        if not fs or rec.get("first"):
            return ""
        return f"{self._year_only(fs)}为外人所知"

    def _blood_kin(self, cid):
        """cid 的**血亲** id 集 (v34, 问题2): 父/母/子女/同胞。
        姻亲 (配偶/前配偶/妾) 一律不算 — 乱伦只认血缘。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fam = rec.get("family") or {}
        out = set()
        for key in ("father", "mother", "child", "siblings"):
            for x in fam.get(key) or []:
                if isinstance(x, int) and x != cid:
                    out.add(x)
        # 自己作为对方 family 里的 father/mother/child/siblings 出现的反向关系
        # (缓存已做反向合并, 此处兜底熔件侧同一字段)
        for _cid, r in (self.cache.get("characters") or {}).items():
            rf = (r.get("family") or {})
            if cid in (rf.get("father") or []) or cid in (rf.get("mother") or []):
                try:
                    out.add(int(_cid))
                except (TypeError, ValueError):
                    continue
        return out

    def _sex_partner_mems(self, cid):
        """cid 的性/情记忆 [(日期, 对方 id)], 按日期升序 (v34, 问题2;
        v38 问题1: 并入 Carnalitas 的 `had_sex_*` 族)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        out = []
        for m in rec.get("memories") or []:
            t = str(m.get("type") or "")
            if t not in _SEX_MEM_TYPES and not t.startswith(_SEX_MEM_PREFIX):
                continue
            parts = m.get("participants") or {}
            other = None
            for slot in _SEX_MEM_OTHER_KEYS:
                v = parts.get(slot)
                if isinstance(v, int) and v != cid:
                    other = v
                    break
            if other is None:
                # 兜底: 取唯一一个非本人的 int 参与者
                cands = [v for v in parts.values()
                         if isinstance(v, int) and v != cid]
                if len(cands) == 1:
                    other = cands[0]
            if other is not None:
                out.append((str(m.get("creation_date") or ""), other))
        out.sort(key=lambda x: cl.date_key(x[0]) if x[0] else (0, 0, 0))
        return out

    def _secret_partner(self, rec):
        """乱伦等「对方不入档」的隐事 → 对方 id (判不出返回 None)。

        v34 (问题2): 存档的 `secret_incest` 只有持有人 (`target` 为空数组),
        对方靠**血亲 ∩ 性/情记忆**判定: 取「与持有人的性/情记忆对象中,
        同时是持有人血亲」的那一个; 多条候选取日期最早者 (关系之始)。
        姻亲不算血亲 — 主角是当事人配偶, 不能被判成乱伦对象。
        """
        if not isinstance(rec, dict):
            return None
        owner = rec.get("owner")
        if not isinstance(owner, int):
            return None
        kin = self._blood_kin(owner)
        if not kin:
            return None
        for d, other in self._sex_partner_mems(owner):
            if other in kin:
                return other
        return None

    def _secret_partner_label(self, rec, self_cid=None):
        """对方称谓 (person_label brief; **持有人本人**写「自己」)。判不出返回 ''。

        v42 (问题2): 「自己」以**记录持有人**为准, 不再以 `self_cid` (主角) 为准 ——
        旧稿让家人隐事句里的对象「主角」被写成「自己」(读成该家人与自己)。
        `self_cid` 仅保留给调用方传主角 id, 用于统一称谓式样。
        """
        o = self._secret_partner(rec)
        if o is None:
            return ""
        owner = rec.get("owner") if isinstance(rec, dict) else None
        if isinstance(owner, int) and o == owner:
            return "自己"
        return self.event_name(o, date=self.as_of) or ""

    def secret_topic(self, rec, self_cid=None):
        """隐事主题短语 (不含持有人): 「在张朴主持的乡试中舞弊」/「谋害叠溪寋」/
        「与阿足私通」; 未收录类型回退游戏本地化类型名 (取不到返回 '')。
        v28b: 涉及对象带官职称谓, **持有人本人**写作「自己」。
        v29 (问题6): 科举舞弊写明**方向与级别** — 存档的 target 是主考 (考试组织者),
        主角是在他主持的考试上作弊; 级别由同一快照的考试记忆判定
        (用户实测: 868.1.1 ↔ 乡试、873.1.1 ↔ 会试)。旧表述「科举舞弊（涉及X）」
        会被读成「考官协助主角作弊」。
        v42 (问题1/2): ① 乱伦并入 style.SECRET_TOPICS 的 `与{target}乱伦`, 不再
        自带「乱伦：」标签; ② 「自己」的基准改为**记录持有人** (rec["owner"]) ——
        隐事句的主语就是持有人, 旧稿以主角 id 为基准, 家人隐事里的主角被写成
        「自己」(「乱伦：与自己」「实父为自己」)。
        涉及对象一律用 `event_name` (主角只出名字, 与年表同式)。"""
        if not isinstance(rec, dict):
            return ""
        tp = rec.get("type") or ""
        tgt = rec.get("target")
        owner = rec.get("owner")

        def _self_or(cid):
            """cid → 「自己」(持有人本人) 或统一称谓。"""
            if not isinstance(cid, int):
                return ""
            if isinstance(owner, int) and cid == owner:
                return "自己"
            return self.event_name(cid, date=self.as_of) or ""

        tname = _self_or(tgt) if isinstance(tgt, int) else ""
        if not tname and tp == "secret_incest":
            # v34 (问题2): 乱伦的 `target` 恒为空数组 (双方各持一条), 对方由
            # 「血亲 ∩ 性/情记忆」判定 (姻亲不算); 判不出时走下面 {target} 缺位
            # 的简式「乱伦」—— 交程序判定, 不给模型发散空间。
            tname = self._secret_partner_label(rec)
        if tp == "secret_exam_cheater":
            lvl = self._exam_level_for_secret(rec.get("owner"), rec.get("first_seen"))
            where = f"{tname}主持的{lvl}" if tname else (lvl or "科考")
            return f"在{where or '科考'}中舞弊" if (tname or lvl) else "科考舞弊"
        if tp in ("secret_disputed_heritage",
                  "secret_unmarried_illegitimate_child"):
            # v41 (问题4): 血统类隐事**点名实父**。旧稿只写「所生X血统有争」,
            # 全篇找不到「X 的实父是谁」时, 模型读不出「主角的女儿嫁的正是
            # 主角自己的私生子」这层关系 —— 断言出处见 修复方案_v41 问题4。
            # 实父取自该子女档案的 real_father (缓存已由秘密推导补全)。
            tpl = SECRET_TOPICS.get(tp)
            if not tpl or not isinstance(tgt, int):
                return ""
            child = self.person_label(tgt, date=self.as_of, style="brief") or ""
            if not child:
                return ""
            crec = (self.cache.get("characters") or {}).get(str(tgt)) or {}
            rf = ((crec.get("family") or {}).get("real_father") or [None])[0]
            rn = _self_or(rf)
            if rn:
                return tpl.format(target=child, father=rn)
            # 实父判不出 → 不带实父位的简式 (无料不下发)
            return SECRET_TOPICS_NO_FATHER.get(tp, "").format(target=child)
        tpl = SECRET_TOPICS.get(tp)
        if tpl:
            if "{target}" in tpl:
                if tname:
                    return tpl.format(target=tname)
                # v34 (问题2): 乱伦等「对方不入档」的隐事判不出对象时退简式
                return SECRET_TOPICS_NO_TARGET.get(tp, "隐情")
            # 模板未用对象 (科举舞弊/挪用国库…) 但有对象时并写, 便于区分同类隐事
            # v55 (问题2): 去括注 —— 「科举舞弊，事涉唐皇帝李漼」
            return f"{tpl}，事涉{tname}" if tname else tpl
        z = L.loc(self.table, tp) or ""
        if not z or re.search(r"[A-Za-z_]", z):
            return ""
        z = re.sub(r"者$", "", z)          # 类型名是名词 (考试舞弊者) — 去「者」成事
        return f"{z}，事涉{tname}" if tname else z

    def _exam_level_for_secret(self, owner, first_seen):
        """科举隐事的考试级别 (v29, 问题6): 取该角色在**同一快照**首见的考试记忆。

        存档的 secret 只有「owner + 主考 + 首次见于记载的快照日」, 级别靠考试记忆
        对齐: 868.1.1 ↔ 乡试 (867.9.17)、873.1.1 ↔ 会试 (872.12.28)。同年未见
        考试记忆时退一步取 ≤ 该年最近的考试记忆; 都取不到返回 ''。"""
        if owner is None:
            return ""
        keys = {"passed_child_exam_memory": "童子试",
                "passed_provincial_exam_memory": "乡试",
                "passed_metropolitan_exam_memory": "会试",
                "passed_palace_exam_memory": "殿试"}
        rec = (self.cache.get("characters") or {}).get(str(owner)) or {}
        exact, same_year, nearest = "", "", ""
        fs = str(first_seen or "")
        fs_year = fs.split(".")[0]
        best_dk = None
        for mem in rec.get("memories") or []:
            lvl = keys.get(mem.get("type") or "")
            if not lvl:
                continue
            seen = str(mem.get("first_seen") or "")
            if fs and seen == fs:
                exact = exact or lvl
            if fs_year and seen.split(".")[0] == fs_year:
                same_year = same_year or lvl
            if fs and seen and cl.date_key(seen) <= cl.date_key(fs):
                dk = cl.date_key(seen)
                if best_dk is None or dk > best_dk:
                    best_dk, nearest = dk, lvl
        return exact or same_year or nearest

    def secret_sentence(self, rec, owner_label=None, self_cid=None):
        """隐事句: 「陆荣廷有一桩隐事：科举舞弊，事涉唐皇帝李漼，873年见于记载。」
        首档即见者不写年份。v55 (问题2): 对象与见载年都不用括注, 依次作同句分句。
        v58 (问题2): **谓词型**主题 (私通/乱伦/谋害/暗行巫术/侵吞库银…) 去壳 ——
        直接写「{owner}{topic}」。旧稿一律套「有一桩隐事：」框架, 于是私通类
        被读成「玛蒂尔达·卡诺萨有一桩隐事：与阿普利亚公爵狐狸罗贝尔·欧特维尔私通。」
        (用户 2026-09-22 报第 2 问: 期望「1072年，玛蒂尔达·卡诺萨与…私通。」)"""
        if not isinstance(rec, dict):
            return ""
        topic = self.secret_topic(rec, self_cid=self_cid)
        if not topic:
            return ""
        owner = owner_label if owner_label is not None \
            else self.name_or(rec.get("owner"))
        if not owner:
            return ""
        if _style.secret_topic_is_predicate(rec.get("type")):
            s = f"{owner}{topic}"
        else:
            s = f"{owner}有一桩隐事：{topic}"
        note = self._first_seen_note(rec)
        if note:
            s += f"，{note}"
        return s + "。"

    def secret_knowers(self, rec, self_cid=None):
        """知情者短语 (无句末句号): 「知情者：卢从度，同年；孙元忠，自873年起」;
        无第三方知情者返回 ''。同年知情者并列共用一个年份 (省词元)。

        v55 (问题2): 去括注 —— 年份改作「，同年」/「，自N年起」的并列分句, 以「；」相隔。

        v31 (问题7): 当事人不算知情者 — 参与者 (做下此事的人) 与持有人本就知道,
        把他们写成「知情者」只能引出同义反复 (「安乔为二子生父, 则其必知情」)。
        知情者 = known_by − 持有人 − 当事人; 为空则不发行 (由「至今无人知晓」承载)。"""
        if not isinstance(rec, dict):
            return ""
        owner = rec.get("owner")
        parties = {x for x in (rec.get("participants") or []) if isinstance(x, int)}
        # v31 (问题7): 私通类隐事的 target 就是对方当事人 (存档 participants 只列
        # 持有人) — 一并排除, 否则「公主与乔乔私通, 知情者：乔乔」又是同义反复。
        if (rec.get("type") or "") in _SECRET_PARTY_TARGET_TYPES \
                and isinstance(rec.get("target"), int):
            parties.add(rec["target"])
        # v34 (问题2): 乱伦的对方不在 target 里, 但已被判出 → 也是当事人,
        # 不能同时出现在「知情者」名单里 (同义反复)。
        if (rec.get("type") or "") == "secret_incest":
            _p = self._secret_partner(rec)
            if isinstance(_p, int):
                parties.add(_p)
        seen = self._year_only(rec.get("first_seen")) if self._first_seen_note(rec) else ""
        groups = []            # [(年份文本 or '', [名, ...])] — 同一年并列
        index = {}
        total = 0
        for k in rec.get("known_by") or []:
            kid = k.get("id")
            if not isinstance(kid, int) or kid == owner or kid in parties:
                continue
            nm = self.name_with_regnal(kid) if kid == self_cid \
                else self.person_label(kid, date=self.as_of, style="brief")
            if not nm:
                continue
            frm = k.get("from")
            yr = self._year_only(frm) if (frm and not k.get("first")) else ""
            g = index.get(yr)
            if g is None:
                g = (yr, [])
                index[yr] = g
                groups.append(g)
            g[1].append(nm)
            total += 1
            if total >= 6:
                break
        if not groups:
            return ""
        # v28b: 按年份升序 (无年份者居前) — 此前按出现次序, 会写出「自875年起、自873年起」
        groups.sort(key=lambda g: (1, cl.date_key(g[0])) if g[0] else (0, (0,)))
        parts = []
        for yr, names in groups:
            who = "、".join(names)
            if not yr:
                parts.append(who)
            elif seen and yr == seen:
                # 年份已在「见载」处写过, 只写一次 (v55: 去括注, 作并列分句)
                parts.append(f"{who}，同年")
            else:
                parts.append(f"{who}，自{yr}起")
        return "知情者：" + "；".join(parts)

    def note_line_stated(self, text, mem, owner_id=None):
        """v63: 句面已写明关系的行 → 登记对手方 (板块期不再给他插亲缘定语)。

        判据是**记忆型 + 参与槽** (不猜措辞): 成婚/同房(配偶)/丧偶/生育/夭折 这些
        模板本身就写着对手方与主语的关系 (「与X成婚」「添子X」「A之妻B产下死婴」),
        故这些人名不再加定语 —— 旧稿实测出「与丈夫金敏恭成婚」「得长女女儿X」。"""
        mtype = str((mem or {}).get("type") or "")
        if not text or mtype not in _REL_STATED_TYPES:
            return
        slot = PARTICIPANT_SLOTS.get(mtype)
        oid = ((mem or {}).get("participants") or {}).get(slot) if slot else None
        if not isinstance(oid, int) or oid == owner_id:
            return
        # 「同房」只在双方确为配偶时才是关系句 (非配偶档走「有私情」, 那句没写关系)
        if mtype == "had_sex" and not self.is_spouse_pair(owner_id, oid):
            return
        self.line_stated[text] = [int(oid)]

    def secret_line(self, rec, owner_label=None, knowers=True, self_cid=None,
                    owner=None):
        """隐事一行 (v28b): 「{owner}有一桩隐事：{topic}，事涉X，Y年见于记载；
        知情者：A，同年；B，自Z年起。」— 隐事与知情者同句, 一眼看出谁知道了哪桩事。
        v45 (档 B): 外层包一层出词登记 (整行一次登记 —— 一行一位持有人)。
        v63: `owner` = 隐事持有人 id (本行主语, 与 owner_label 同一人)。"""
        with self.log_names() as lg:
            out = self._secret_line_body(rec, owner_label=owner_label,
                                         knowers=knowers, self_cid=self_cid)
        return self.index_names(out, lg, owner=owner)

    def _secret_line_body(self, rec, owner_label=None, knowers=True, self_cid=None):
        s = self.secret_sentence(rec, owner_label=owner_label, self_cid=self_cid)
        if not s or not knowers:
            return s
        kl = self.secret_knowers(rec, self_cid=self_cid)
        return s[:-1] + "；" + kl + "。" if kl else s


    def secret_lines(self, recs, owner_label=None, self_cid=None, with_knowers=True,
                     owner=None):
        """同一持有人的隐事合并成一行 (v28b 省词元):

            「陆荣廷有隐事二桩：科举舞弊（涉及樊骥）；会试舞弊
              （涉及唐皇帝李漼，873年见载），知情者：卢从度（自875年起）。」

        持有人只写一次, 每桩自带见载年与自己的知情者; 单桩时与 secret_line 同形
        (「陆荣廷有隐事：…」)。返回 [str] (无可用主题时返回 [])。
        v45 (档 B): 外层包一层出词登记 (每行单独登记, 供板块期插亲缘定语)。
        v63: `owner` = 持有人 id (本行主语) —— 传给同名的单桩出口并登记本行主语。"""
        with self.log_names() as lg:
            out = self._secret_lines_body(recs, owner_label=owner_label,
                                          self_cid=self_cid,
                                          with_knowers=with_knowers, owner=owner)
        for ln in (out or []):
            self.index_names(ln, lg, owner=owner)
        return out

    def _secret_lines_body(self, recs, owner_label=None, self_cid=None,
                           with_knowers=True, owner=None):
        items = [r for r in (recs or []) if isinstance(r, dict)]
        if not items:
            return []
        owner = owner_label
        if owner is None:
            owner = self.name_or(items[0].get("owner"))
        if not owner:
            return []
        if len(items) == 1:
            ln = self.secret_line(items[0], owner_label=owner, self_cid=self_cid,
                                  knowers=with_knowers, owner=owner)
            return [ln] if ln else []
        # v58 (问题2): 谓词型主题逐桩成句 (「X与Y私通，1072年见于记载。」),
        # 名词型仍并成「X有隐事N桩：…」—— 两类混在一起会写出
        # 「有隐事两桩：与X私通；所生Y血统有争」这种半通顺句。
        blocks = []          # [(是否谓词型, [rec…])] 按原次序 (按日期排好的)
        for r in items:
            pred = _style.secret_topic_is_predicate(r.get("type"))
            if blocks and blocks[-1][0] == pred:
                blocks[-1][1].append(r)
            else:
                blocks.append((pred, [r]))
        out = []
        for pred, group in blocks:
            if pred:
                for r in group:
                    ln = self.secret_line(r, owner_label=owner, self_cid=self_cid,
                                          knowers=with_knowers, owner=owner)
                    if ln:
                        out.append(ln)
                continue
            clauses = []
            for r in group:
                topic = self.secret_topic(r, self_cid=self_cid)
                if not topic:
                    continue
                note = self._first_seen_note(r)
                if note:
                    # v55 (问题2): 去括注 —— 见载年作分句接在主题后 (旧稿并入同一括号)
                    topic += f"，{note}"
                kn = self.secret_knowers(r, self_cid=self_cid) if with_knowers else ""
                if kn:
                    topic += "，" + kn
                clauses.append(topic)
            if clauses:
                out.append(f"{owner}有隐事{_count_zh(len(clauses))}桩："
                           + "；".join(clauses) + "。")
        return out

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

    # ------------------------------------------------------------------
    # v31 (问题4/5/6/8): 宫廷身份 / 妻室情事脉络 / 牵制 / 直辖折叠
    # ------------------------------------------------------------------

    def court_service_phrase(self, cid, actor_label=None):
        """宫廷身份短语 (v31, 问题6): 「主角廷中骑士，自869年6月4日在廷」。

        数据源 `court_data` (缓存 `court`): 雇主为玩家时给出, 否则返回 ''。
        「配偶的情人是主角自己的廷臣/骑士」此前完全读不到, 乔乔因此只剩一个名字。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        ct = rec.get("court") or {}
        pid = self.cache.get("player_id")
        if not ct or pid is None or ct.get("employer") != pid:
            return ""
        who = actor_label or "主角"
        key = "court_knight" if ct.get("knight") else "court_member"
        word = _FACT_WORDING[key].format(actor=who)
        jd = ct.get("join_court_date")
        if jd:
            since = _FACT_WORDING["affair_joined_court"].format(date=self.date(jd))
            return f"{word}，{since}"
        return word

    def domain_titles(self, dom):
        """直辖头衔折叠 (v31 问题8 / v54 问题1): 返回 (保留 id 列表, 被折叠的首府男爵领集)。

        伯爵领的首府男爵领 (存档 `capital_barony = true`, 且其 `capital` 即所辖
        伯爵领) 由所辖伯爵领自然蕴含 — 与伯爵领并列会把一处领地写成两处
        (「贝阿恩伯爵领、波城男爵领」)。首府另由「治所」句写一次。

        v36 (用户拍板5): 男爵领 (rank 1) 一律不进直辖清单 — 头衔材料最低取到州府。

        v54 (用户拍板, 2026-09-18): 直辖清单 = **最高头衔**（同最高层级全留）
        + **实控伯爵领**。理由（用户口径）: 公国/王国之下必须有封臣才能产出租税
        与兵员, 只有伯爵领是可直接经营的层级 —— 次级 k_/d_ 头衔不是「实控领地」,
        并列会让档案变成报菜名（马丁 26 地里有 11 王国 + 6 公国）；它们已由
        「历任」与《朝局风云录》承担。
        家业 (`x_nf_*`) 只在**一个伯爵领都没有**时保留 —— 与 v41b「有地领主不写
        庄园句」同纪律（有地时主线走政体/历任，家业另有《家室列传》承担）。"""
        ids = [int(t) for t in (dom or []) if isinstance(t, int)]
        held = set(ids)

        def _rank(tid):
            return self._TT_RANK.get(
                ((self._lt.get(str(tid)) or {}).get("key") or "")[:2], 0)

        keep, folded = [], set()
        for tid in ids:
            t = self._lt.get(str(tid)) or {}
            if _rank(tid) == 1:      # v36: 男爵领由所辖州府蕴含
                folded.add(tid)
                continue
            cap = t.get("capital")
            if t.get("capital_barony") and isinstance(cap, int) \
                    and cap != tid and cap in held:
                folded.add(tid)
                continue
            keep.append(tid)
        # v54: 只留最高层级 + 伯爵领 (家业在无伯爵领时才留)
        top = max((_rank(t) for t in keep), default=0)
        has_county = any(_rank(t) == 2 for t in keep)
        out = []
        for tid in keep:
            rank = _rank(tid)
            if rank == 2 or rank == top:
                out.append(tid)
            elif rank == 0 and not has_county:
                out.append(tid)      # 纯世族: 家业即其全部「地」
            else:
                folded.add(tid)
        return out, folded

    def consort_affairs(self, cid, spouses=None):
        """妻室情事脉络 (v31, 问题4): [{spouse, spouse_label, partner, identity, arc}]。

        逐情人一条: 关系弧由缓存记忆按人聚合 (私通→相恋→灵魂伴侣→分手/情人去世),
        身份短语取 `court_service_phrase` (主角廷中骑士 / 廷臣 + 入宫日)。
        「妻子怎么交到情人和灵魂伴侣」此前无脉络可写, 只有一条条孤立日期。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fam = rec.get("family") or {}
        pid = self.cache.get("player_id")
        if spouses is None:
            spouses = []
            for k in ("primary_spouse", "spouse", "former_spouses",
                      "concubine", "former_concubines"):
                spouses += [x for x in (fam.get(k) or []) if isinstance(x, int)]
        ao = cl.date_key(self.as_of) if self.as_of else None
        out = []
        for sid in dict.fromkeys(spouses):
            if sid == cid:
                continue
            srec = (self.cache.get("characters") or {}).get(str(sid)) or {}
            groups = {}
            for mem in srec.get("memories") or []:
                tp = mem.get("type")
                slot = _AFFAIR_SLOTS.get(tp)
                if not slot:
                    continue
                d = mem.get("creation_date")
                if ao is not None and d and cl.date_key(d) > ao:
                    continue
                other = (mem.get("participants") or {}).get(slot)
                if not isinstance(other, int) or other in (sid, pid, cid):
                    continue
                groups.setdefault(other, []).append((str(d or ""), tp))
            for partner, mems in groups.items():
                mems.sort(key=lambda x: cl.date_key(x[0]))
                parts = []
                seen_first = set()
                repeats = []
                for d, tp in mems:
                    if tp == "had_sex" and "had_sex" in seen_first:
                        repeats.append(str(d).split(".")[0])
                        continue
                    seen_first.add(tp)
                    key = {"had_sex": "affair_entry",
                           "became_lovers": "affair_lovers",
                           "became_soulmates": "affair_soulmates",
                           "broke_up_lovers": "affair_broke_up",
                           "lover_died": "affair_lover_died"}.get(tp)
                    if not key:
                        continue
                    parts.append(_FACT_WORDING[key].format(date=self.date(d)))
                if repeats:
                    yrs = "、".join(f"{y}年" for y in repeats[:4])
                    parts.append(_FACT_WORDING["affair_repeat"].format(years=yrs))
                if not parts:
                    continue
                out.append({
                    "spouse": sid,
                    "spouse_label": self.person_label(sid, date=self.as_of, style="brief")
                                    or self.name_or(sid),
                    "partner": partner,
                    "identity": self.court_service_phrase(partner),
                    "arc": "，".join(parts),
                })
        out.sort(key=lambda e: (e["spouse"], str(e["arc"])))
        return out

    def _hook_meta(self, tp):
        return (L.hook_type_table().get("hook_types") or {}).get(tp or "") or {}

    def _hook_name(self, tp):
        """牵制名的引号形态:「干了我老婆」; 本地化查不到时返回 ''。"""
        nm = L.hook_type(self.table, tp or "")
        return f"「{nm}」" if nm else ""

    def _hook_since(self, rec):
        if rec.get("first") or not rec.get("first_seen"):
            return ""
        return _FACT_WORDING["hook_since"].format(
            year=self._year_only(rec["first_seen"]))

    # v35 (问题3): 家主牵制不入事实层 —— `house_head_hook` 是**家主身份自带**的机制
    # 牵制 (家主对其每个族人天然持有), 不是「握有把柄」这一叙事事件。v31 起
    # `hook_notable` 已把它判为「不足以单开一篇隐事」, 但 `hook_lines` 仍原样下发,
    # 于是《阴私录》里塞满「主角握有对两个儿子的『家主』牵制」(德圣塔档 2 条,
    # 马克龙档曾 8 条), 与用户「强牵制太泛滥」的判断一致。cache_lib 已在入库前跳过
    # (见 `hook_type_kept`), 此处对旧缓存再兜一层。
    # v38 (问题2, 用户拍板): 判据由「排除家主」升级为**白名单** —— 通用人情类
    # (人情/义务/蒙恩/支持者/忠诚/威胁/操控/孝道…) 一律不下发, 判据见
    # `style.hook_type_kept`; 旧缓存里已入库的通用牵制由此同样被拦下。
    def _hook_kept(self, tp):
        return _style.hook_type_kept(tp)

    def hook_lines(self):
        """牵制事实 (v31, 问题5): {"held": [主角握有的], "over": [他人对主角的]}。

        方向: 取缓存已定好的 `holder`/`target`（v33 起由 `cache_lib.hook_slot_holder`
        按 `active_hook_<N>` 槽号判定 —— first/second 只是按键规范化的成对编号）。
        强弱取游戏 `common/hook_types` 的 `strong`; 同型多条归并成一行。
        v38 (问题2): 类型先过 `style.hook_type_kept` 白名单 —— 只有背后有一件具体事
        的牵制才出句 (勒索/捏造/罪案/Mod 内容牵制/强牵制), 通用人情与身份自带类
        (人情/义务/蒙恩/忠诚/威胁/操控/家主/孝道) 一律略去, 见 `_hook_kept`。
        只出 as_of 之前已见、且 as_of 时仍持有者 (逐档差分记录 lost_at)。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return {}
        ao = cl.date_key(self.as_of) if self.as_of else None
        # v56 (问题4): 主角只出名字 (event_name), 头衔在档案一次立名
        plabel = self.event_name(pid, self.as_of) or "主角"
        recs = []
        for rec in (self.cache.get("hooks") or {}).values():
            if not isinstance(rec, dict):
                continue
            if not self._hook_kept(rec.get("type")):
                continue
            fs, la = rec.get("first_seen"), rec.get("lost_at")
            if ao is not None and fs and cl.date_key(fs) > ao:
                continue
            if ao is not None and la and cl.date_key(la) <= ao:
                continue
            if not isinstance(rec.get("holder"), int) \
                    or not isinstance(rec.get("target"), int):
                continue
            recs.append(rec)
        out = {}
        for direction, mine in (("held", True), ("over", False)):
            sel = [r for r in recs if (r["holder"] == pid) == mine]
            groups = {}
            for r in sel:
                groups.setdefault(
                    (r.get("type"), bool(self._hook_meta(r.get("type")).get("strong"))),
                    []).append(r)
            lines = []
            for (tp, strong), rs in groups.items():
                name = self._hook_name(tp)
                word = _FACT_WORDING["hook_strong_word"] if strong else ""
                if len(rs) > 1:
                    # 归并行: 对手方按方向取 (主角握有 → 对象; 他人对主角 → 持有者)
                    ids = [(r["target"] if mine else r["holder"]) for r in rs]
                    names = "、".join(
                        (self.person_label(i, date=self.as_of, style="brief") or "某人")
                        for i in list(dict.fromkeys(ids))[:3])
                    tpl = _FACT_WORDING[
                        "hook_group_held" if mine else "hook_group_over"]
                    lines.append(tpl.format(actor=plabel, names=names, strength=word,
                                            name=name, n=len(rs)))
                    continue
                r = rs[0]
                other = self.person_label(r["target"], date=self.as_of, style="brief") or "某人"
                tpl = _FACT_WORDING[
                    "hook_held_strong" if (mine and strong) else
                    "hook_held_weak" if mine else
                    "hook_over_actor_strong" if strong else
                    "hook_over_actor_weak"]
                since = self._hook_since(r)
                exp = r.get("expiration")
                if exp and str(exp) not in ("9999.1.1", "none"):
                    since = _FACT_WORDING["hook_expires"].format(date=self.date(exp))
                if mine:
                    lines.append(tpl.format(actor=plabel, target=other,
                                            name=name, since=since))
                else:
                    holder = self.person_label(r["holder"], date=self.as_of, style="brief") or "某人"
                    lines.append(tpl.format(actor=plabel, holder=holder,
                                            name=name, since=since))
            if lines:
                out[direction] = lines
        return out

    def _is_slave_of(self, slave, owner=None, date=None):
        """slave 在 date 时点是否为 owner (缺省=主角) 的奴隶 (cache["enslavements"])。

        判据 = 逐档差分记录: first_seen ≤ date 且 (lost_at 为空或 > date)。"""
        pid = self.cache.get("player_id")
        owner = pid if owner is None else owner
        if slave is None or owner is None:
            return False
        rec = (self.cache.get("enslavements") or {}).get(f"{owner}>{slave}")
        if not isinstance(rec, dict):
            return False
        dk = cl.date_key(date) if date else (
            cl.date_key(self.as_of) if self.as_of else None)
        fs, la = rec.get("first_seen"), rec.get("lost_at")
        if dk is not None and fs and cl.date_key(fs) > dk:
            return False
        if dk is not None and la and cl.date_key(la) <= dk:
            return False
        return True

    def enslaved_lines(self):
        """奴役事实 (v35, 问题4): 主角为奴隶主的那些人。

        Carnalitas 的 `carn_enslave_effect` 在奴役的**同一刻**对已被囚的奴隶执行
        `release_from_prison = yes`, 所以存档里那句「释放」记忆正是「没为奴隶」这一步;
        只有这层关系 (`opinions.active_opinions[*].scripted_relations.slave`,
        缓存 `enslavements`) 能把两者区分开。旧稿把「抓人 → 没为奴隶 → 放出牢房」
        整个读成了「抓了又放」, 正是缺了这条。

        返回 {"lines": [...], "former": [...], "head": bool} —
        在册者逐条 = 「X没为Y的奴隶（Z年起）。」(超三人时归并成一行, 与牵制同口径);
        **曾为主角所有、此后不再所有者**进 `former`, 逐条写出关系的收束
        (v38 问题4: 被卖/被释/被夺, 由缓存差分判定) —— 旧稿只写在册的,
        人一被卖掉就从事实面彻底消失, 模型此后再无此人可依。

        v38 (问题4, 用户拍板「全部做完」): 收「曾经是主角奴隶」的全部关系
        (不只看在本档还在册的), 并给出三档收束句:
          · 转卖 → 「X没为Y的奴隶（Z年起），至W年转归他人」;
          · 释放 → 「X没为Y的奴隶（Z年起），至W年获释」;
          · 结局不明 (死亡/数据中断) → 「X没为Y的奴隶（Z年起）」, 不再补缺席按语。
        判据来自 cache_lib._diff_enslavements 记录的 `end_owner` / `freed` /
        `lost_at` (见该处注释)。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return {}
        ao = cl.date_key(self.as_of) if self.as_of else None
        recs = []
        former = []
        for key, rec in (self.cache.get("enslavements") or {}).items():
            if not isinstance(rec, dict):
                continue
            # v38: 只取主角为**某一任**主人的关系 (转卖后关系仍在缓存里)
            owners = [rec.get("owner")] + list(rec.get("prev_owners") or [])
            if pid not in owners:
                continue
            fs, la = rec.get("first_seen"), rec.get("lost_at")
            if ao is not None and fs and cl.date_key(fs) > ao:
                continue
            if not isinstance(rec.get("slave"), int):
                continue
            if ao is not None and la and cl.date_key(la) <= ao:
                # 关系在 as_of 之前就断了 → 曾为主角所有
                former.append(rec)
                continue
            recs.append(rec)
        recs.sort(key=lambda r: cl.date_key(r.get("first_seen") or "9999.9.9"))
        former.sort(key=lambda r: cl.date_key(r.get("lost_at") or "9999.9.9"))
        W = _FACT_WORDING
        # v56 (问题4): 主角只出名字 (event_name), 头衔在档案一次立名
        plabel = self.event_name(pid, self.as_of) or "主角"
        names = []
        for r in recs:
            nm = self.person_label(r["slave"], date=self.as_of, style="brief") or ""
            if nm:
                names.append((r, nm))
        fnames = []
        for r in former:
            nm = self.person_label(r["slave"], date=self.as_of, style="brief") or ""
            if nm:
                fnames.append((r, nm))
        if not names and not fnames:
            return {}
        out = []
        if len(names) > 3:
            first = names[0][0]
            shown = "、".join(nm for _r, nm in names[:3])
            extra = W["enslaved_group_extra"].format(n=len(names))
            out.append(W["enslaved_group"].format(
                actor=plabel, names=shown, extra=extra,
                year=self._year_only(first.get("first_seen"))))
        else:
            for r, nm in names:
                fs = r.get("first_seen")
                if r.get("first") or not fs:
                    # 首档即见: 起年不可知, 只写事 (不给空年份)
                    out.append(W["enslaved_line"].format(
                        slave=nm, actor=plabel))
                else:
                    out.append(W["enslaved_line_since"].format(
                        slave=nm, actor=plabel,
                        year=self._year_only(fs)))
        fout = []
        for r, nm in fnames[:8]:
            fs, la = r.get("first_seen"), r.get("lost_at")
            # v55 (问题2): 起年由括注改为句首状语 (「自874年起，X没为Y的奴隶，至881年…」)
            since = "" if (r.get("first") or not fs) \
                else "自{}起，".format(self._year_only(fs))
            end_y = self._year_only(la) if la else ""
            buyer = r.get("end_owner")
            bname = self.person_label(buyer, date=self.as_of, style="brief") \
                if isinstance(buyer, int) else ""
            if bname:
                fout.append(W["enslaved_former_sold"].format(
                    slave=nm, actor=plabel, since=since, year=end_y,
                    buyer=bname))
            elif r.get("freed"):
                fout.append(W["enslaved_former_freed"].format(
                    slave=nm, actor=plabel, since=since, year=end_y))
            else:
                fout.append(W["enslaved_former_lost"].format(
                    slave=nm, actor=plabel, since=since, year=end_y))
        return {"lines": out, "former": fout}

    def harm_lines(self):
        """强迫/半推半就之事的**事实行** —— v59 起停用 (恒返回 [])。

        v38 (问题1 追修) 曾把「时间线里模块『强暴凌辱』的事件」单列一块, 供
        《阴私录》的事实面使用 (「...X强迫Y性交。（受害方及其亲属由此视其为仇）」)。
        **v59 (问题2, 用户 2026-09-23 拍板): 性事只在《列传·好友》《列传·仇人》
        里用** —— 该块随之停用; 性事行的载体改为好友/仇人两篇的【相关年表】
        (走 `facts["timeline"]` + `MODULE_SLICE` 的 `("friend"/"enemy","mid")`)。

        函数保留为**空实现**: `_secrets_facts` 仍调用它, 但 `out["harm"]` 不再下发
        (见 `_secrets_facts`); 将来若要把强迫之事放进别的专用块, 这里是恢复点
        (`style.FACT_WORDING` 的 `harm_*` 措辞已随本轮删除)。"""
        return []

    def std_lines(self):
        """性病传播的事实行 (v40): 只收当事人属相关集者。

        返回 [「{日期}，{源}把{病}传染给了{的}。」] —— 无源 (卖淫/先天) 时写
        「{的}染上{病}。」。
        v59 (问题2): 「可挂性事」的补注出口随性事退出年表而删除,
        本行成为传播的唯一出口。"""
        related = _related_ids(self)
        out = []
        for when, text, src, tgt in _std_index(self):
            if not when:
                continue
            if not (tgt in related or (isinstance(src, int) and src in related)):
                continue
            out.append(f"{self.date(when)}，{text}")
        return out

    def carnal_opinion_lines(self):
        """Carnalitas 事件好感 → 干净中文句 (v38 问题1/4; v41 问题3 改开关制)。

        数据源 `cache["carnal_opinions"]` (逐档差分, 自带 `start` = 游戏给的
        start_date)。本地化就是一句对对方的评断 —— 实测:

            carn_raped_me                              = 曾强奸我
            carn_raped_my_lover                        = 曾强奸我的情人
            carn_raped_family_member                   = 曾强奸家庭成员
            carn_enslaved_me_opinion                   = 奴役了我
            carn_enslaved_me_crime_opinion             = 非法奴役了我
            carn_enslaved_close_family_opinion         = 奴役了亲族成员
            carn_former_slave_or_slave_owner_opinion   = 曾经是主奴关系
            carn_forced_me_into_prostitution_opinion   = 迫使我卖淫
            carn_demanded_manumission_opinion          = 被要求解放奴隶

        方向: `owner` = 持有该评断的人, `target` = 被评断的人。句式为
        「{owner}视{target}为：{评断词}（{年}）」，即以**持有者的视角**直陈。
        查不到本地化的键整条略去 (不把裸键送进提示词)。

        v41 (问题3, 用户拍板「都移除, 做成配置形式」): **整族由配置开关控制**,
        默认关 (`config.json` 的 `carnal_opinions`)。实测本档 29 条全部是
        `carn_raped_me/_my_lover/_family_member`, 只给「曾强奸我」这类评断,
        无地点、无行为、无具体日, 与性事记忆渲染的强迫之事行
        (「1078年6月21日…强迫尼希莱·卡斯特罗乔瓦尼口交」) 逐条重复,
        只增提示词长度。置 true 时恢复旧行为。
        v59 (问题2): 性事行已退出公开面 (只在好友/仇人列传里用), 本块与它的
        重复面进一步缩小; 开关口径不变。"""
        if not self._show_carnal_opinions:
            return {}
        pid = self.cache.get("player_id")
        if pid is None:
            return {}
        ao = cl.date_key(self.as_of) if self.as_of else None
        out = []
        for rec in (self.cache.get("carnal_opinions") or {}).values():
            if not isinstance(rec, dict):
                continue
            owner, target = rec.get("owner"), rec.get("target")
            if not isinstance(owner, int) or not isinstance(target, int):
                continue
            fs = rec.get("start") or rec.get("first_seen")
            if ao is not None and fs and cl.date_key(fs) > ao:
                continue
            word = L.loc(self.table, str(rec.get("modifier") or ""))
            if not word or not loc_text_ok(word):
                continue
            she = self.person_label(owner, date=self.as_of, style="brief") or ""
            the = self.person_label(target, date=self.as_of, style="brief") or ""
            if not she or not the:
                continue
            year = self._year_only(fs) if fs else ""
            # v55 (问题2): 去括注 —— 起年作句内状语 (「X自874年起视Y为…」)
            since = f"自{year}起" if (year and not rec.get("first")) else ""
            out.append(f"{she}{since}视{the}为{word}。")
        if not out:
            return {}
        return {"lines": sorted(set(out))[:10]}

    def carnal_victim_line(self):
        """主角身上「最近遭强暴」的收束句 (v38, 问题1)。

        数据源 = 逐档差分的角色修正 `carn_recently_raped` (Mod 在受害方身上加
        5 年, health −0.25)。它与性事记忆互为佐证: 记忆给「谁做的」, 修正给
        「此事确实按强迫处理、且五年内仍算近事」这一当下状态。只在主角自己身上
        时出句; 无则返回 ''。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return ""
        rec = (self.cache.get("carnal_modifiers") or {}).get(
            f"{pid}>carn_recently_raped")
        if not isinstance(rec, dict):
            return ""
        ao = cl.date_key(self.as_of) if self.as_of else None
        fs, la = rec.get("first_seen"), rec.get("lost_at")
        if ao is not None and fs and cl.date_key(fs) > ao:
            return ""
        if ao is not None and la and cl.date_key(la) <= ao:
            return ""
        return _FACT_WORDING["carnal_recently_raped"]

    def forced_concubine_lines(self):
        """强纳为妾事实 (v32, 问题1): 逐条 = 「880年1月1日，主角强纳戈迪娜·迭戈斯为妾。」。

        数据源 = `cache["opinions"]` 里 `forced_me_concubine_marriage_opinion` 的
        `start_date` (存档 `opinions.active_opinions`: owner=被纳者, target=施为者)。
        游戏脚本 `concubine_on_accept_effect` 在该人**身陷囹圄或守贞**时给这条好感,
        同一段落紧接着 `release_from_prison = yes` —— 故若同人同日有
        `released_from_prison_memory` 且监禁者同为施为者, 句尾补「同日自狱中释出」,
        「掳人 → 囚 → 强纳为妾」的次序即由程序坐实 (旧文本只能写
        「嫁入年份未见于簿册」, 模型遂默认先婚后囚)。只出 as_of 之前已见者。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return []
        ao = cl.date_key(self.as_of) if self.as_of else None
        W = _FACT_WORDING
        out = []
        for rec in (self.cache.get("opinions") or {}).values():
            if not isinstance(rec, dict):
                continue
            if rec.get("modifier") != "forced_me_concubine_marriage_opinion":
                continue
            owner, target = rec.get("owner"), rec.get("target")
            if not isinstance(owner, int) or not isinstance(target, int):
                continue
            fs, la = rec.get("first_seen"), rec.get("lost_at")
            if ao is not None and fs and cl.date_key(fs) > ao:
                continue
            if ao is not None and la and cl.date_key(la) <= ao:
                continue
            start = rec.get("start") or fs
            if not start:
                continue
            name = self.person_label(owner, date=self.as_of, style="brief") or ""
            if not name:
                continue
            actor = "主角" if target == pid \
                else (self.person_label(target, date=self.as_of, style="brief") or "某人")
            # 同日释放 (脚本 release_from_prison = yes) → 出狱缘由即此
            paroled = False
            for m in (((self.cache.get("characters") or {}).get(str(owner))
                       or {}).get("memories") or []):
                if m.get("type") != "released_from_prison_memory":
                    continue
                if str(m.get("creation_date")) != str(start):
                    continue
                if (m.get("participants") or {}).get("imprisoner") == target:
                    paroled = True
                    break
            tpl = W["concubine_forced_paroled"] if paroled else W["concubine_forced"]
            out.append(tpl.format(date=self.date(start), actor=actor, name=name))
        return sorted(set(out))

    def concubine_divorce_lines(self):
        """「妾的原有婚配被离断」事实 (v60 问题3) —— 逐条形如
        「879年9月1日，希尔德加德原为萨洛蒙之妻，主角强纳为妾而离异。」。

        源 = `cache["opinions"]` 里 `forced_spouse_concubine_marriage_opinion`
        (owner = 被离断的原配, target = 强纳者), 由游戏脚本
        `00_marriage_interaction_effects.txt` 在「强纳有夫/有妇之人为妾」时给予
        原配并 `divorce = scope:recipient`。崔佛档三名妾**都是他人之妻**,
        而模型此前只看到「强纳为妾」一句, 遂把女子的原配关系整段虚构 ——
        这一行把「谁是原配」写成事实。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return []
        ao = cl.date_key(self.as_of) if self.as_of else None
        W = _FACT_WORDING
        out = []
        for rec in (self.cache.get("opinions") or {}).values():
            if not isinstance(rec, dict):
                continue
            if rec.get("modifier") != "forced_spouse_concubine_marriage_opinion":
                continue
            owner, target = rec.get("owner"), rec.get("target")
            if not isinstance(owner, int) or not isinstance(target, int):
                continue
            fs, la = rec.get("first_seen"), rec.get("lost_at")
            if ao is not None and fs and cl.date_key(fs) > ao:
                continue
            if ao is not None and la and cl.date_key(la) <= ao:
                continue
            start = rec.get("start") or fs
            if not start:
                continue
            ex_name = self.person_label(owner, date=self.as_of, style="brief") or ""
            if not ex_name:
                continue
            # 被强纳者 = 原配在本档的前妻/前夫 (缓存亲属集里唯一的新增配偶)
            sp_name = ""
            for x in (((self.cache.get("characters") or {}).get(str(owner)) or {})
                      .get("family") or {}).get("former_spouses") or []:
                if isinstance(x, int) and x != pid:
                    sp_name = self.person_label(x, date=self.as_of, style="brief") or ""
                    break
            if not sp_name:
                continue
            actor = "主角" if target == pid \
                else (self.person_label(target, date=self.as_of, style="brief") or "某人")
            out.append(W["concubine_divorced"].format(
                date=self.date(start), actor=actor, name=sp_name, ex=ex_name))
        return sorted(set(out))

    def hook_notable(self):
        """有「够格入《阴私录》」的牵制 (v31; v38 问题2 收紧判据)。

        门槛即 `style.hook_type_kept` 的白名单: 只有背后有一件具体事的牵制
        (勒索/捏造/罪案/Mod 内容牵制/强牵制) 才算料; 家主、孝道、人情、义务、
        蒙恩这类身份自带或通用人情不单开一篇。"""
        pid = self.cache.get("player_id")
        for rec in (self.cache.get("hooks") or {}).values():
            if not isinstance(rec, dict):
                continue
            if not _style.hook_type_kept(rec.get("type")):
                continue
            if pid in (rec.get("holder"), rec.get("target")):
                return True
        return False

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
            # v53 (问题3): 三省六部是无地官署头衔, 创建当日立刻任命给朝臣,
            # 天子「在位」时长为零 — 不是短命皇朝, 不进戏剧块。
            if key.startswith("e_minister_"):
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

    def _prince_word(self, ptier, government, independent, female,
                     child=None, ptid=None, date=None, owner=None):
        """王子词: 按父头衔层级 × 政体 × 独立/封臣 × 性别。
        天朝制: 皇朝/帝国=皇子/皇女; 独立王国=王子/郡主 (大理国王子);
        封臣王国=公子/公女 (青徐路公子)。封建: 王子/公主。

        v64 (问题2) 闸门: 出词前先问游戏 `special = ruler_child` 条目表
        (`_prince_word_exists`) —— 表里没有该 (层级 × 政体 × 文化/信仰) 组合时
        **游戏本就不给称号**, 此处返回 '' (部落制/游牧制的王国级、帝国级子女即此:
        `prince`/`princess`/`prince_empire` 的 governments 均不含 tribal/nomad)。
        出词口径不变 (仍走中式键 + `_PRINCE_WORD_OVERRIDE`); `child`/`ptid` 缺省
        (旧调用) 时跳过闸门, 行为与 v63 逐字相同。"""
        if child is not None and not self._prince_word_exists(
                ptier, government, independent, child, ptid, date, owner=owner):
            return ""
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
        """天皇座 (k_chrysanthemum_throne) 子女的称号词 → '亲王'/'内亲王';
        不适用返回 ''。v20: 现实/中文史传口径 — 天皇后代称「惟仁亲王/井上内亲王」,
        名在前、称号在后, 无「高御座」前缀 (高御座是御座名, 游戏模组虚构的家族式前缀)。

        v62 (史实口径 B, 用户拍板「按 C 或 B 动工」): 判据由「父/母**当下在位**」
        改为「父/母**一生持有过**天皇座 **且 本人仍在皇籍**」——
          · 親王/内親王是终身身分, 与父退位/崩御无关 (《大日本史》实测: 惟喬親王
            为文德天皇之子, 父 858 年崩御后仍以親王身分活到 897 年; 本康/人康/
            秀良/業良 同例); 旧判据把前代天皇之子全部漏掉, 交给兜底路拼出
            「高御座王子」这种游戏里不存在的词。
          · 判据的另一半是**臣籍降下**: 受源/平之姓者即入臣籍 (源融/源澄/源升/
            源信/源常/源弘/源定/源本有…), 本人宗族不再是皇籍大和 → 不出亲王/内亲王。
        游戏侧旁证: `tgp_japan_imperial_branch_decision`(请求皇室本姓) 把皇室成员
        改为源/平宗族 (game/common/decisions/dlc_decisions/tgp/tgp_japan_decisions.txt:826);
        亲王词本身只给 `special = ruler_child` + `titles = { k_chrysanthemum_throne }`
        (game/common/flavorization/10_tgp_japan_flavorization.txt:634,644)。"""
        try:
            tier0, _ = self._primary_title_at(cid, as_of=date)
            if tier0 is not None:
                return ""  # 自己已有头衔, 不适用
        except Exception:
            return ""
        if self._imperial_clan_state(cid) != "imperial":
            return ""      # v62: 臣籍降下 (源/平/藤原…) 或宗族判不明 → 不出亲王/内亲王
        for pid2 in self._parents_of_cid(cid):
            try:
                _t, ptid = self._primary_title_at(pid2, as_of=date)
            except Exception:
                ptid = None
            on_throne = bool(ptid) and \
                ((self._lt.get(str(ptid)) or {}).get("key") in self._TENNO_TITLE_KEYS)
            if not on_throne:
                # v62: 父/母已崩御或已退位 —— 親王是终身身分, 认一生持有过天皇座
                try:
                    on_throne = self._ever_held_throne(pid2, date)
                except Exception:
                    on_throne = False
            if not on_throne:
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
        名单型数据使用 (王祦 → 高丽国皇子), 防 as_of 穿越。
        v36 (问题3, 用户拍板1/2):
          ① 父/母头衔按**一生最高**取 (父已死或已失位也能解出称号), 政体取头衔侧
             (`_title_government`) —— 「父为前代皇帝」者不再退成裸名;
          ② 新增兄弟路线: **兄弟为当今皇帝 且 其父亦为皇帝** 时, 按当今皇帝的头衔
             给皇子/皇女称号 (李丽容: 父唐宣宗李忱、兄唐懿宗李漼 → 唐皇朝皇女)。"""
        if self._tenno_prince_word(cid, date):
            return ""
        tier0, _ = self._primary_title_at(cid, as_of=date)
        if tier0 is not None:
            return ""  # 自己已有头衔, 不适用
        style = self._parent_prince_style(cid, date)
        if style:
            return style
        return self._emperor_sibling_style(cid, date)

    _EMPEROR_TIERS = ("hegemon", "empire")

    def _style_parent_title(self, parent, date):
        """父/母「给子女称号用」的头衔 (tier, tid) (v36, 用户拍板2):
        现仍持有者优先; 空则退其一生最高头衔 — 父已死/已失位时也能出称号。"""
        t, tid = self._primary_title_at(parent, as_of=date)
        if t is not None and self._is_landed_title(tid):
            return t, tid
        ftid = self._former_high_title(parent, date)
        if ftid is None:
            return None, None
        key = (self._lt.get(str(ftid)) or {}).get("key") or ""
        rank = self._TT_RANK.get(key[:2], 0)
        tier = self._RANK_TIER.get(rank) if rank >= 1 else None
        return (tier, ftid) if tier else (None, None)

    def _prince_style_from_title(self, ptier, ptid, date, child, owner):
        """(层级, 头衔) + 持有人 → 「前缀 + 王子词」 (v36 抽出; 政体取头衔侧,
        独立与否取持有人)。取不到基名返回 ''。

        v52 (问题3, 用户拍板): 前缀**一律用头衔本名, 不再拼层级词** ——
        「西法兰克王国公主」→「西法兰克公主」、「阿基坦王国公主」→「阿基坦公主」、
        「大理国皇子」→「大理皇子」。两处例外:
          · 皇朝级 (h_) 且国号是王朝名 (`title_history_names` 里的 `dynn_title_*`,
            如汉/晋/隋/唐/宋) → 前缀加「大」: 「大唐皇女 / 大唐皇子」(用户拍板例);
          · 游戏「简称」头衔 (`definite_form = yes`, 神圣罗马帝国/拜占庭帝国/教宗国)
            与名称已含国号者保持本名, 不叠词也不加「大」(旧稿曾写出
            「神圣罗马帝国国皇女」「神圣罗马帝国帝国公主」)。

        v62 (菲利普2 问题1/2): 日本最高头衔 (天皇座/日本帝国) 一律不在此出词 ——
        其持有人是「天皇」或「关白/幕府将军」, 子女称号由 `_tenno_prince_word` 专管;
        旧稿把御座名/国号拼成「高御座王子源澄」「日本王子源升」(父已故时的
        一生最高头衔兜底), 属游戏里不存在的词。"""
        if ((self._lt.get(str(ptid)) or {}).get("key") or "") in self._JAPAN_TOP_TITLE_KEYS:
            return ""
        pgov = self._title_government(ptid, date)
        pbase = self._name_at_date(ptid, date or self.as_of) or self.title_base_name(ptid)
        if not pbase:
            return ""
        independent = self._is_independent(owner, date)
        if independent is None:
            independent = True
        rn = self.realm_name(ptid)
        if rn:
            prefix = rn
        elif ptier == "hegemon" and pgov in self._CELESTIAL_LIKE_GOVS \
                and not self._is_short_title(ptid) \
                and not _STATE_SUFFIX_RE.search(pbase) \
                and self._name_source_key(ptid, date).startswith("dynn_"):
            # 中华皇朝: 国号随王朝轮转 (唐/宋/秦…) → 「大唐」「大宋」
            prefix = pbase if pbase.startswith("大") else f"大{pbase}"
        else:
            # v52: 省层级词 (国/路/皇朝/王国/帝国一律不拼), 简称头衔直接用本名
            prefix = pbase
        word = self._prince_word(ptier, pgov, independent, self._is_female(child),
                                 child=child, ptid=ptid, date=date, owner=owner)
        # v64 (问题2): 游戏在此处不给称号 (闸门未命中, word='') → 整句不成立,
        # 防「库曼顿巴斯部王子」退化成只剩前缀的「库曼顿巴斯部」
        if not word:
            return ""
        # 称号已并入显示名时不叠前缀 (绰号「时尚王子」+ 父为国主 → 防「新罗国王子时尚王子金晸」;
        # 与 _tenno_prince_word 的同名守卫同口径)
        if word in (self.name_with_regnal(child, date) or ""):
            return ""
        return prefix + word

    def _parent_prince_style(self, cid, date):
        """父/母为王国级以上统治者时的子女称号 (取层级最高的一位父母)。
        v62: 日本最高头衔 (天皇座/日本帝国) 的父/母**不参与**挑选 —— 他们的子女称号
        只由 `_tenno_prince_word` 出词; 这样另一位父/母若是普通王国之主, 仍能正常出词。"""
        best = None  # (rank, ptier, ptid, parent_cid)
        for pid2 in self._parents_of_cid(cid):
            t, tid = self._style_parent_title(int(pid2), date)
            if ((self._lt.get(str(tid)) or {}).get("key") or "") in self._JAPAN_TOP_TITLE_KEYS:
                continue
            rank = {"hegemon": 6, "empire": 5, "kingdom": 4}.get(t, 0)
            if rank > 0 and (best is None or rank > best[0]):
                best = (rank, t, tid, int(pid2))
        if best is None:
            return ""
        _rank, ptier, ptid, pparent = best
        return self._prince_style_from_title(ptier, ptid, date, cid, pparent)

    def _emperor_sibling_style(self, cid, date):
        """兄弟为当今皇帝 且 父亦为皇帝 → 皇子/皇女称号 (v36, 用户拍板1)。
        两个条件缺一不给 — 免得把「皇帝庶兄弟」一律抬成皇胄。"""
        fam = ((self.cache.get("characters") or {}).get(str(cid)) or {}).get("family") or {}
        sibs = [int(x) for x in (fam.get("siblings") or []) if isinstance(x, int)]
        fathers = [int(x) for x in (fam.get("father") or []) if isinstance(x, int)]
        if not sibs or not fathers:
            return ""
        father_ok = False
        for f2 in fathers:
            t, _tid = self._style_parent_title(f2, date)
            if t in self._EMPEROR_TIERS:
                father_ok = True
                break
        if not father_ok:
            return ""
        for b in sibs:
            t, tid = self._primary_title_at(b, as_of=date)
            if t in self._EMPEROR_TIERS and self._is_landed_title(tid):
                return self._prince_style_from_title(t, tid, date, cid, b)
        return ""

    # ---- 家族恩怨 (house_relations) / 宝物志 (artifacts) ----

    # v55 (问题1c): 出狱缘由 —— **熔件直读**, 不新增缓存字段 (用户 2026-09-19 定规:
    # 本轮不重建缓存)。方向铁律 (存档实测, 见 logs/probe_v55_direction.txt):
    #   `add_opinion = { target = scope:actor }` 写在被囚者作用域内 = **被囚者持有该评价**,
    #   故 owner=被囚者、target=释放者; 唯 `ransomed_from_prison` 的 target 是**付款人**
    #   (可能是第三方亲属), 故另有按 owner 的兜底查询。
    # 生命周期: 出狱类一律 years=10 / decaying (`ransomed_from_prison` 被脚本覆盖为 1 年),
    # 且**随持有者死亡立即从存档消失** —— 读不到就回退「获释」(与 v54 行为一致);
    # v56 (问题3): 再加一层 cache["prison_manners"] 回退 (逐档闩存, 见 cache_lib),
    # 终传因此仍能读到十年前那批释放的缘由。
    # v56 (问题3, 用户拍板): `demanded_hook` 这一档写**中性**的「以人情获释」——
    # 它与 `favor_hook` 同由「赎金·人情分支」与「索取人情后释放」两条互动产生,
    # 存档留痕逐字段相同, 程序分不出「纳赎」与「以人情换释」。
    _PRISON_MANNER_MODS = {
        "released_from_prison":            ("released",  "获释"),
        "merciful_opinion":                ("released",  "获释"),
        "ransomed_from_prison":            ("ransomed",  "纳赎获释"),
        "demanded_my_conversion_opinion":  ("converted", "改信获释"),
        "compelled_me_to_convert_opinion": ("converted", "改信获释"),
        "demanded_hook":                   ("hook",      "以人情获释"),
        "demanded_claim_renouncement":     ("claim",     "被迫放弃宣称获释"),
        "banished_me":                     ("banished",  "遭驱逐"),
        "demanded_recruitment":            ("recruit",   "遭强征入仕"),
        "demanded_taking_vows":            ("vows",      "被迫出家获释"),
    }
    # 折叠行的「缘故词」(v55 问题1d/§3): 结局族 → 计数式里的短语。
    # 多人簇不带时长 (用户拍板), 单人囚禁行照旧带「3日后 / 1个月后」。
    _PRISON_KIND_WORD = {
        "released": "获释", "converted": "改信获释", "hook": "以人情获释",
        "claim": "放弃宣称获释", "ransomed": "纳赎获释", "banished": "遭驱逐",
        "recruit": "遭强征入仕", "vows": "被迫出家获释", "escape": "越狱脱身",
        "enslaved": "没为奴隶", "punished": "受刑获释", "executed": "处决",
        "died_in_prison": "死于狱中",
        # 热修 (2026-09-24): 囚期被**吃掉**收口 —— 与 `executed` 同为死亡族,
        # 但走食人硬证 (`devoured_by`), 措辞与死者名录的「被其吃掉」同词。
        "devoured": "被吃掉",
        # v60 (问题4): 收句以**本档为界** —— 旧措辞「此后一直未见释放」把
        # 「本传数据窗口内在押」写成一句无限期的断言 (崔佛 881.1.1 卒、四名
        # 囚犯此后转归继位者, 传记却读成永远没放)。{bound} 由调用方给:
        # 十年档给该篇截止日, 终传给「末档」(见 `_prison_bound`)。
        "held": "至{bound}仍在押",
    }

    def prison_death_clause(self, victim, date=None):
        """收句用的死亡记录 (v60 问题4) → {date, reason, killer} 或 {};

        缓存优先; 缓存未记 (受害者死在缓存末档之后) 时回退**熔件** `dead_data`
        —— 旧稿只查 `cache["characters"][victim]["death"]`, 于是「死在末档之后、
        只在熔件里」的那批人被写成永远在押。"""
        rec = ((self.cache.get("characters") or {}).get(str(victim)) or {})
        dd = rec.get("death") or {}
        if dd.get("date"):
            return dd
        for seg in ("living", "dead_unprunable"):
            c = (self.melt.get(seg) or {}).get(str(victim))
            if isinstance(c, dict) and (c.get("dead_data") or {}).get("date"):
                return c["dead_data"]
        return {}

    def _death_int(self, v):
        """死亡记录的整数字段 (哨兵 4294967295 = 无 / 0xFFFFFFFF 一律视为缺) → int|None。"""
        if not isinstance(v, int) or v < 0 or v >= 4294967295:
            return None
        return v

    # ------------------------------------------------------------------
    # v78 (问题1): 囚禁结局的**唯一判据出口**
    # ------------------------------------------------------------------
    # 起因 (用户 2026-09-27 报告): 《家族恩怨录》只记囚禁、不记释放, 且把「逐档观测到
    # 不在押」当成「获释」。根因是**两处平行实现**各自拼判据 —— 年表侧
    # `_pair_imprisonments` (释放记忆 → 狱史闭合日; 死亡只在两者皆无时才查) 与
    # 恩怨录侧 `_house_prison_nodes` 同一顺序。而 `prison_history.from/to` 只是
    # **逐档观测界** (cache_lib.py:2611-2645): 区间闭合可能是获释, 也可能是被处决/
    # 死于狱中。实测浩二 902.8.18 那批 45 人里 43 人有死亡记录 (39 人 903.8.21
    # 同日处决), 旧判据却把 45 人全判「获释」, 模型据此写出「尽数获释, 不妄杀一人」。
    #
    # 判据顺序 (用户 2026-09-27 拍板 D2「关押时段写几年/几个月后」的前提):
    #   ① 释放/越狱记忆 (participants.imprisoner 与监禁者一致、日期 ≥ 入狱日) —— 最准;
    #   ② 在押期内没为奴隶 (Carnalitas 奴役与释放同刻建立, 故先于释放结论);
    #   ③ 死亡记录 (死日 ≥ 入狱日; 凶手 == 监禁者 ⇒ 刑杀; 食人硬证优先);
    #   ④ prison_history 区间闭合日 ⇒ 已出狱 (**观测界**, 不当作获释日断言);
    #   ⑤ 皆无 ⇒ held (收口「至{档}仍在押」+ 监禁者交接)。
    # 与旧行为**只差两处**: ③ 现在先于 ④; 死亡早于「释放」记忆时以死亡为准。
    def prison_exit(self, victim, jailer, entry_date):
        """囚禁结局的统一判据 → {"kind", "date", "manner", "source", "reason"}。

        kind ∈ escape / <release_manner 各档> / released / enslaved /
               executed / died_in_prison / devoured / held
        date = 出狱日或死日 (held 时为空); manner = 出狱缘由措辞 (无则空)。"""
        out = {"kind": "held", "date": "", "manner": "", "source": "none",
               "reason": ""}
        if not isinstance(victim, int) or not entry_date:
            return out
        rec = (self.cache.get("characters") or {}).get(str(victim)) or {}
        dk0 = cl.date_key(str(entry_date))
        # 可接受的「释放者」集 —— 含**监禁者交接后的继任者** (v78): 实测田所椅子
        # 902.7.1 被田口晓子囚禁, 903 档起转归 33576669 (prison_history 的
        # `from_imprisoner`/`imprisoner` 一对), 905.5.11 由继任者释放。旧稿只认原
        # 监禁者, 于是把已获释的人写成「至末档仍在押」。
        _jailers = {jailer} if isinstance(jailer, int) else set()
        for iv in rec.get("prison_history") or []:
            if isinstance(iv.get("from_imprisoner"), int) \
                    and iv.get("from_imprisoner") == jailer \
                    and isinstance(iv.get("imprisoner"), int):
                _jailers.add(iv["imprisoner"])
        # 「别次囚禁的监禁者」集 —— 释放者若不是本次监禁者, 只有它**从未**囚禁过此人
        # 才能判为交接后的继任者。`prison_history` 的交接记录只存在于**前任传主**的
        # 缓存 (久保缓存里 田所椅子 的 prison_history 为空), 故这条兜底是必需的:
        # 椅子 902.7.1 被田口晓子囚禁、905.5.11 由继任者 33576669 释放。
        _other_jailers = set()
        for m in rec.get("memories") or []:
            if (m.get("type") or "") != "imprisoned":
                continue
            j2 = (m.get("participants") or {}).get("imprisoner")
            if isinstance(j2, int) and j2 != jailer:
                _other_jailers.add(j2)
        # ① 释放 / 越狱记忆 (取最早一条与本次监禁者一致者)
        rel = None
        for m in rec.get("memories") or []:
            t = m.get("type") or ""
            if t not in ("released_from_prison_memory",
                         "escaped_from_prison_memory"):
                continue
            d = str(m.get("creation_date") or "")
            if not d or cl.date_key(d) < dk0:
                continue
            j = (m.get("participants") or {}).get("imprisoner")
            if isinstance(j, int) and _jailers and j not in _jailers \
                    and j in _other_jailers:
                continue          # 该释放记忆属另一次囚禁, 不归本次
            if rel is None or cl.date_key(d) < cl.date_key(rel[0]):
                rel = (d, t)
        # ④' 狱史区间闭合日先算: 它同时是死亡判定的**上界** —— 闭合日早于死日时,
        # 说明此人先出了狱、日后才死, 那一笔死亡不属本次囚禁 (否则会把「出狱多年后
        # 病故」写成「N年后死于狱中」)。
        hist_to = ""
        for iv in rec.get("prison_history") or []:
            to = str(iv.get("to") or "")
            if to and cl.date_key(to) >= dk0 \
                    and (not hist_to or cl.date_key(to) < cl.date_key(hist_to)):
                hist_to = to
        # ③ 死亡记录先算 —— 给 ① 设「不晚于死日」的闸 (矛盾数据以死亡为准)
        dd = self.prison_death_clause(victim) or {}
        ddate = str(dd.get("date") or "")
        if ddate and cl.date_key(ddate) < dk0:
            dd, ddate = {}, ""
        if ddate and hist_to and cl.date_key(ddate) > cl.date_key(hist_to):
            dd, ddate = {}, ""
        _esc = bool(rel) and rel[1] == "escaped_from_prison_memory"
        # ② 在押期内没为奴隶 (越狱者不在此列 —— 他确实脱身了)
        if not _esc:
            _own = _enslaved_in_span(self, victim, jailer, entry_date,
                                     (ddate or (rel[0] if rel else "")) or None)
            if _own is not None:
                return {"kind": "enslaved", "date": ddate or (rel[0] if rel else ""),
                        "manner": "", "source": "enslavement", "reason": ""}
        if rel is not None:
            d, t = rel
            if not ddate or cl.date_key(d) <= cl.date_key(ddate):
                if t == "escaped_from_prison_memory":
                    return {"kind": "escape", "date": d, "manner": "",
                            "source": "memory", "reason": ""}
                mk, mw = self.release_manner(victim, jailer, d)
                return {"kind": mk or "released", "date": d, "manner": mw,
                        "source": "memory", "reason": ""}
        if ddate:
            killer = self._death_int(dd.get("killer"))
            jail = self._death_int(jailer)
            _exec = (dd.get("reason") in _PRISON_EXEC_REASONS
                     or (killer is not None and jail is not None
                         and killer == jail))
            reason = str(dd.get("reason") or "")
            if _exec and jail is not None and self.devoured_by(jail, victim):
                return {"kind": "devoured", "date": ddate, "manner": "",
                        "source": "death", "reason": reason}
            return {"kind": "executed" if _exec else "died_in_prison",
                    "date": ddate, "manner": "", "source": "death",
                    "reason": reason}
        # ④ 狱史区间闭合日 (观测界: 「哪一档起不在押」; 不当作获释日断言)
        if hist_to:
            return {"kind": "released", "date": hist_to, "manner": "",
                    "source": "history", "reason": ""}
        return out

    def prison_capture_head(self, victim, jailer, date, cluster_n=1):
        """囚禁行的**句首** (谁把谁抓起来, 含获取方式的硬证词) —— v78 共用出口。

        与年表侧 (`_pair_imprisonments`) 同源: 只有硬证才写方式词
        (`Facts.capture_manner`: diarchy 摄政拘押 / raid 劫掠中掳走 / 战阵俘获 /
        batch 群体拘押), 判不出时维持裸「{jailer}囚禁{victim}」——**不写方式**,
        模型也就没有「在宴会上擒获」这类自造场景的落点。
        未成年人档 (`not_battle`) 的年龄补注只用于年表 (那里能取到年龄),
        本出口按裸「囚禁」出词。"""
        W = _style.FACT_WORDING
        jn = self._feud_role_title(jailer, date) if isinstance(jailer, int) else ""
        vn = self._feud_role_title(victim, date) if isinstance(victim, int) else ""
        if not vn:
            return ""
        if not jn:
            return W["prison_held"].format(victim=vn)
        try:
            cm, _note = self.capture_manner(victim, jailer, date,
                                            cluster_n=cluster_n)
        except Exception:
            cm = "unknown"
        if cm == "diarchy":
            return W["prison_captured_diarch"].format(jailer=jn, victim=vn)
        if cm in ("battle", "battle_poi"):
            return W["prison_captured_battle"].format(jailer=jn, victim=vn)
        if cm == "raid":
            return W["prison_raid_captured"].format(jailer=jn, victim=vn)
        if cm == "batch":
            return W["prison_batch_seized"].format(jailer=jn, victim=vn)
        return W["prison_jailed"].format(jailer=jn, victim=vn)

    def prison_tail(self, victim, jailer, entry_date, ex=None, purge=False):
        """囚禁行的**结局小句** (含起首「，」) → `(tail, kind, span)` (v78)。

        判据一律走 `prison_exit` (唯一出口); 措辞与本项目既有词表一致:
        当日 / N日后 / N个月后 / N年后 (用户 2026-09-27 D2: 关押时段写时长,
        不把观测界当获释日断言)。年表侧另有同日「战末俘获 / 刑虐并句」两处附加,
        留在 `_pair_imprisonments` 内不动。"""
        W = _style.FACT_WORDING
        ex = ex or self.prison_exit(victim, jailer, entry_date)
        kind = ex.get("kind") or "held"
        ddate = str(ex.get("date") or "")
        span = _prison_span(entry_date, ddate) if ddate else ""
        same = bool(span) and span == W["prison_same_day"]
        if kind == "held":
            tail = W["prison_still_held"].format(bound=self._prison_bound())
            tail += self.prison_handover_clause(victim, date=entry_date)
            return (tail, "held", "")
        if kind == "enslaved":
            return (W["prison_enslaved"], "enslaved", span)
        if kind == "escape":
            if same:
                t = W["prison_escape_same_day"]
            elif span:
                t = W["prison_escaped"].format(span=span)
            else:
                t = W["prison_escape_on"].format(date=self.date(ddate))
            return (t, "escape", span)
        if kind in ("executed", "died_in_prison", "devoured"):
            key = {"executed": "prison_died_executed",
                   "died_in_prison": "prison_died_in_prison",
                   "devoured": "prison_died_devoured"}[kind]
            sp = (W["prison_same_day"] if same
                  else (f"{span}后" if span else f"至{self.date(ddate)}"))
            return (W[key].format(sp=sp), kind, span)
        # 释放族: released / converted / hook / claim / ransomed / recruit /
        # vows / punished(受刑而获释) —— 诛灭日一律「遭驱逐」(既有口径)
        if purge:
            return ("，遭驱逐", "banished", span)
        mw = str(ex.get("manner") or "")
        if mw:
            if same:
                t = f"{W['prison_same_day']}{mw}"
            elif span:
                t = f"{span}后{mw}"
            elif ddate:
                t = f"{self.date(ddate)}{mw}"
            else:
                t = mw
            return (t if t.startswith("，") else "，" + t, kind, span)
        if same:
            return (W["prison_released_same_day"], "released", span)
        if span:
            return (W["prison_released"].format(span=span), "released", span)
        return (W["prison_release_on"].format(date=self.date(ddate)), "released", span)

    def spouse_latch_rows(self, as_of=None):
        """主角的婚配闩存记录 (v60 问题3) → [{other, kind, first_seen}], 按见载日排序。

        源 = `cache["spouse_latch"]` (逐档扫全角色 `family_data` 的反向指针闩存,
        见 `cache_lib._latch_spouses`)。主角自身的 `family_data` 在死亡档会被游戏
        清空, 这张表是「一生有过哪些妻妾」唯一跨档可靠的来源。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return []
        ck = cl.date_key(as_of) if as_of else None
        out = []
        for key, rec in (self.cache.get("spouse_latch") or {}).items():
            if not isinstance(rec, dict):
                continue
            if rec.get("player") != pid:
                continue
            other = rec.get("other")
            if not isinstance(other, int):
                continue
            fs = rec.get("first_seen")
            st = rec.get("since") or fs
            # v60: `since` 可比首见档更早 (命名类好感自带 start_date) —— 十年档
            # 的时期门按它判, 免得 879 年成的婚被算进第 2 个十年
            if ck is not None and st and cl.date_key(st) > ck:
                continue
            out.append({"other": other, "kind": str(rec.get("kind") or ""),
                        "first_seen": st or fs})
        out.sort(key=lambda r: (cl.date_key(r["first_seen"] or ""), r["other"]))
        return out

    def merge_spouse_latch(self, fam, as_of=None):
        """把婚配闩存并进亲属集 (v60 问题3) —— 就地补 fam, 返回 fam。

        位分按 `spouse_latch.kind` 落到 `primary_spouse` / `spouse` / `concubine`
        与 `former_spouses` / `former_concubines` 五键, 与游戏 `family_data` 的
        键名同构, 下游 (`_protagonist_facts` / `_genealogy` / `biography`) 无需另学
        一套。**只补不覆盖**: 游戏当档给出的键值优先, 闩存只填缺。"""
        rows = self.spouse_latch_rows(as_of)
        if not rows:
            return fam
        fam = fam if isinstance(fam, dict) else {}
        for key in ("primary_spouse", "spouse", "concubine",
                    "former_spouses", "former_concubines"):
            fam.setdefault(key, [])
        # 位分可能随档演进 (妾 → 正妻): 以最强的一位分为准 (rank 见 cache_lib)
        rank = cl._SPOUSE_KIND_RANK
        best = {}
        for r in rows:
            k = r["kind"]
            if k not in rank:
                continue
            if r["other"] not in best or rank[k] < rank[best[r["other"]]]:
                best[r["other"]] = k
        for other, k in best.items():
            slot = {"primary_spouse": "primary_spouse", "spouse": "spouse",
                    "concubine": "concubine", "former_spouse": "former_spouses",
                    "former_concubine": "former_concubines"}[k]
            if other not in fam[slot]:
                fam[slot].append(other)
        # 已成正妻/侧室者不再同时列作妾 (游戏把同一人写在两个字段时,
        # `_consort_word` 判「妾」优先, 会把正妻读成妾)
        _formal = set(fam.get("primary_spouse") or []) | set(fam.get("spouse") or [])
        if _formal:
            fam["concubine"] = [x for x in fam.get("concubine") or []
                                if x not in _formal]
            fam["former_concubines"] = [x for x in fam.get("former_concubines") or []
                                        if x not in _formal]
        ever = set(fam.get("ever_spouses") or [])
        for key in ("primary_spouse", "spouse", "former_spouses",
                    "concubine", "former_concubines"):
            ever.update(int(x) for x in (fam.get(key) or []))
        if ever:
            fam["ever_spouses"] = sorted(ever)
        return fam

    def _prison_bound(self):
        """囚禁收句的观测界 (v60 问题4) → 「{日期}末档」或「末档」。

        十年档以该篇截止日为界 (「878年1月1日末档」), 终传以缓存末档为界
        (「末档」)。措辞里的「末档」二字必须留住 —— 只写日期会被读成获释日。"""
        last = self.cache.get("last_date")
        cut = self.as_of or last
        if not cut:
            return "末档"
        if last and str(cut) == str(last):
            return "末档"
        d = self.date(cut)
        return f"{d}末档" if d else "末档"

    def prison_handover_clause(self, victim, date=None):
        """该囚犯的**监禁者交接**小句 (v60 问题4) → 「，881年1月1日转归埃尔梅辛达」;
        无交接或交接晚于本篇截止日时返回 ''。

        来源二路: ① 同一缓存内逐档观测到的 `from_imprisoner` (传主在世时监禁者
        换人); ② `cache["prison_succession"]` (传主死后囚禁转归继位者 —— 该类
        档期的玩家已不是传主, 由 `cache_lib._latch_prison_succession` 从同战役
        后继档闩存)。"""
        try:
            victim = int(victim)
        except (TypeError, ValueError):
            return ""
        cut = self.as_of or self.cache.get("last_date")
        ck = cl.date_key(cut) if cut else None
        rec = (self.cache.get("prison_succession") or {}).get(str(victim)) or {}
        nxt = rec.get("to") if isinstance(rec.get("to"), int) else None
        when = rec.get("first_seen") or rec.get("since") or ""
        if nxt is None:
            for iv in (((self.cache.get("characters") or {}).get(str(victim)) or {})
                       .get("prison_history") or []):
                if isinstance(iv, dict) and isinstance(iv.get("from_imprisoner"), int) \
                        and isinstance(iv.get("imprisoner"), int):
                    nxt = iv["imprisoner"]
                    when = iv.get("from") or ""
                    break
        if nxt is None:
            return ""
        if date and ck is not None and cl.date_key(date) > ck:
            return ""
        name = self.event_name(nxt, date=self.as_of) or self.name_or(nxt, "")
        if not name:
            return ""
        d = self.date(when) if when else ""
        return f"，{d}转归{name}" if d else f"，转归{name}"

    def _mem_holder_index(self):
        """{记忆 id: 持有者 id} —— 由各角色 `alive_data/dead_data.memories` 反查 (惰性)。

        v63 (问题1) 修: 记忆对象本身**不带** `owner` 字段 (归属由角色侧的
        `memories` 列表记载), 而记忆 id 与角色 id 共用同一个 id 池 —— 旧稿拿
        「记忆 id」当持有人会得到**另一个角色的 id** (实测 20276 这条
        `battle_won_memory` 被读成「持有者 20276」, 而它其实是主角 38665 的记忆,
        于是 871.2.7 那次战阵俘获判不出来)。这里一次性建反查索引。"""
        cached = getattr(self, "_mem_holder", None)
        if cached is not None:
            return cached
        out = {}
        for bucket in (self.melt.get("living") or {},
                       self.melt.get("dead_unprunable") or {},
                       (self.melt.get("characters") or {}).get("dead_prunable") or {}):
            for cid, c in bucket.items():
                if not isinstance(c, dict):
                    continue
                ad = c.get("alive_data") or c.get("dead_data") or {}
                for mid in (ad.get("memories") or []):
                    try:
                        out[int(mid)] = int(cid)
                    except (TypeError, ValueError):
                        continue
        self._mem_holder = out
        return out

    def _battle_by_date(self):
        """{日期: [(类型, loser, winner, owner)]} —— 本档全部战斗/战争记忆 (惰性)。

        用于「同日打了仗且被囚者正是输家 ⇒ 战阵俘获」这一判据 (v63 问题1)。
        来源 = `character_memory_manager.database` 里**任何角色**持有的
        `battle_won_memory` / `battle_lost_memory` / `war_won` / `war_lost`,
        故不依赖「主角当时在不在场」。

        v63 第三轮: 四类**语义不同**, 调用方必须自己筛 —— 只有 `battle_*_memory`
        是「当天打了一仗」; `war_won` / `war_lost` 是**战争结束**记忆 (实测 9 条
        只匹配到 war_* 的「战阵俘获」在押者, 其 `prison_data.type` 全是 dungeon,
        即战争结束 ≠ 沙场被擒)。`capture_manner` 因此只收 `battle_` 前缀的条目。

        胜方判定: 记忆持有人即该记忆的主语 —— `*_won` 的持有人是**胜方**
        (`battle_won_memory` 的 participants 只有 `loser`), `*_lost` 的持有人是
        **败方** (`participants.winner`); 两者互补, 故两条都收录, 由调用方按
        「被囚者是不是 loser」判。"""
        cached = getattr(self, "_battle_idx", None)
        if cached is not None:
            return cached
        out = {}
        holder = self._mem_holder_index()
        db = (self.melt.get("character_memory_manager") or {}).get("database") or {}
        for mid, e in db.items():
            if not isinstance(e, dict):
                continue
            t = e.get("type") or ""
            if t not in ("battle_won_memory", "battle_lost_memory",
                         "war_won", "war_lost"):
                continue
            parts = e.get("participants") or {}
            owner = e.get("owner")
            if owner is None:
                try:
                    owner = holder.get(int(mid))
                except (TypeError, ValueError):
                    owner = None
            d = e.get("creation_date")
            if not d:
                continue
            out.setdefault(str(d), []).append(
                (t, parts.get("loser"), parts.get("winner"), owner))
        self._battle_idx = out
        return out

    @staticmethod
    def _battle_winner(rec):
        """战斗/战争记忆 → (loser, winner); 胜方缺字段时由持有人补。"""
        t, loser, winner, owner = rec
        if winner is None:
            # `*_won` 的持有人就是胜方; `*_lost` 的 participants 应带 winner
            if t.endswith("_won") or "won" in t:
                winner = owner
        return loser, winner

    def _var_flags(self, cid):
        """角色 `alive_data.variables` 的 flag 名集 (死者的 `dead_data` 兜底)。"""
        chars = self.melt.get("living") or {}
        if str(cid) not in chars:
            chars = self.melt.get("dead_unprunable") or {}
        if str(cid) not in chars:
            chars = (self.melt.get("characters") or {}).get("dead_prunable") or {}
        ad = (chars.get(str(cid)) or {}).get("alive_data") \
            or (chars.get(str(cid)) or {}).get("dead_data") or {}
        vs = ad.get("variables")
        items = vs.get("data") if isinstance(vs, dict) else vs
        out = set()
        for it in (items or []):
            if isinstance(it, dict) and it.get("flag"):
                out.add(str(it["flag"]))
        return out

    def _battle_poi_hits(self, jailer, date, victim=None):
        """省份战场兴趣点命中 (v63 问题1 最强判据之一) → 省份 id 列表。

        游戏在「战斗所在省」写 `battle_poi_winner` / `battle_poi_loser`
        / `battle_poi_date_{year,month,day}` / `battle_poi_enemy_commander_imprisoned`
        (`events/war_events/combat_events.txt:2262-2334`), 且写变量的事件
        `combat_event.3000` 与关人的 `combat_event.1001` 由**同一 on_action 同一次
        触发** (`common/on_action/combat_on_actions.txt:12-24`), 故二者严格同场。
        日期三个变量落盘时 ×100000 (实测 year identity 89100000 → 891 年,
        day 2400000 → 24)。覆盖率极窄 (本档实测 9 处), 但一旦命中即确定性。

        v63 第三轮: `battle_poi_enemy_commander_imprisoned` 只在**败方主指挥官**
        进了 `prisoners_of_war` 时才写 (`combat_events.txt:2326-2333`, 判据是
        `this = root.enemy_side.side_primary_participant`), 而 `battle_poi_loser`
        正是同一位败方主指挥官 (`:2274-2276`)。故命中还须 `loser == victim` ——
        同一省同日可能有别场仗, 不比对身份就会把不相干的人算成战阵俘获。"""
        cached = getattr(self, "_poi_idx", None)
        if cached is None:
            cached = {}
            provs = self.melt.get("provinces") or {}
            for pid, p in provs.items():
                if not isinstance(p, dict):
                    continue
                vs = (p.get("variables") or {})
                items = vs.get("data") if isinstance(vs, dict) else vs
                flags = {}
                for it in (items or []):
                    if isinstance(it, dict) and it.get("flag"):
                        d = it.get("data") or {}
                        flags[str(it["flag"])] = d.get("identity")
                if not flags.get("battle_poi_enemy_commander_imprisoned"):
                    continue
                def _div(name):
                    v = flags.get(name)
                    try:
                        return int(v) // 100000
                    except (TypeError, ValueError):
                        return None
                cached[str(pid)] = {
                    "winner": flags.get("battle_poi_winner"),
                    "loser": flags.get("battle_poi_loser"),
                    "year": _div("battle_poi_date_year"),
                    "month": _div("battle_poi_date_month"),
                    "day": _div("battle_poi_date_day"),
                }
            self._poi_idx = cached
        try:
            y, mo, d = (int(x) for x in str(date).split(".")[:3])
        except (TypeError, ValueError):
            return []
        return [pid for pid, v in cached.items()
                if v.get("winner") == jailer and v.get("year") == y
                and v.get("month") == mo and v.get("day") == d
                and (victim is None or v.get("loser") == victim)]

    def imprison_batch_sizes(self):
        """{(日期, 监禁者): 人数} —— 「同日同监禁者囚禁了几人」(惰性)。

        v63 (问题1): 群体俘获判据的数据源。两个来源取**较大值**:
          ① 事件面 (见 `_pair_imprisonments` 的 `_pm["n"]`): 双视角事件计数;
          ② **施囚者侧的 `imprisoned_other` 记忆** —— 这条最耐久: 实测 907.1.16
             那七人里六人已死, 其 `imprisoned` 记忆被引擎连对象一起回收, 事件面
             只能数到几人; 而主角自己的 `imprisoned_other` 七条全在 (记忆时长
             1350 年、不随被囚者死亡消失), 故这一侧才是群体捕获的可靠计数。"""
        cached = getattr(self, "_batch_sizes", None)
        if cached is not None:
            return cached
        out = {}
        holder = self._mem_holder_index()
        db = (self.melt.get("character_memory_manager") or {}).get("database") or {}
        for mid, e in db.items():
            if not isinstance(e, dict) or e.get("type") != "imprisoned_other":
                continue
            try:
                jailer = holder.get(int(mid))
            except (TypeError, ValueError):
                jailer = None
            if jailer is None:
                continue
            key = (str(e.get("creation_date")), jailer)
            out[key] = out.get(key, 0) + 1
        self._batch_sizes = out
        return out

    def _age_at(self, cid, date):
        """该角色在 date 当日的岁数 (int|None)。无生年返回 None。"""
        cy = _audit_year(self, cid)
        if cy is None or not date:
            return None
        try:
            y = int(str(date).split(".")[0])
        except (TypeError, ValueError):
            return None
        return y - cy

    def _last_raid_on(self, jailer, date):
        """监禁者当日是否正在劫掠 → `last_raid` 原值或 None (v63 问题1)。

        游戏把「最近一次劫掠日」写在 `landed_data.last_raid` (本档 410/40429
        在世者有值)。它是「最后一次」而非全史, 故只可**正证**劫掠: 与入狱日相同
        ⇒ 劫掠掳人; 不同 ⇒ 什么都不能排除 (后续劫掠会覆盖)。"""
        if jailer is None or not date:
            return None
        for bucket in (self.melt.get("living") or {},
                       self.melt.get("dead_unprunable") or {},
                       (self.melt.get("characters") or {}).get("dead_prunable") or {}):
            c = bucket.get(str(jailer))
            if isinstance(c, dict):
                lr = (c.get("landed_data") or {}).get("last_raid")
                if lr and str(lr) == str(date):
                    return str(lr)
                break
        return None

    def _house_raid_index(self):
        """家族关系流水里的**劫掠**条目索引 → `{日期: [(raider, target, raw)…]}`
        (惰性, 一次扫描)。

        v63 第四轮 (2026-09-24 用户追加口径「家族记忆里有没有被劫掠相关的」):
        本档**记忆库里没有任何 raid 类记忆** (185 个记忆类型全表普查, 0 命中),
        按日的劫掠留痕只有一个地方 —— `house_relations.database[*].history[*]`
        的 `change_reason`。写入点: 游戏 `common/on_action/army_on_actions.txt:761`
        `on_raid_action_completion` → `:803-816` `change_house_relation_effect = {
        REASON = raid, CHAR = scope:raider, TARGET_CHAR = scope:county.holder }`
        —— 即**劫掠完成当日**, 记「劫掠者劫掠了被劫郡之持有者」。

        句面已本地化且带两端角色块, 两端 id 用 `_FEUD_CHAR_RE` 取; 序为
        (CHAR, TARGET_CHAR) = (劫掠者, 被劫者)。`raided_estate` /
        `raided_estate_attempt` (劫掠庄园) 同样带「劫掠」字样, 一并收 ——
        它们同属「当日正在劫掠此人」的正证。

        本档实测: 5704 对家族关系 / 15671 条流水 / 601 条含劫掠字样;
        主角侧 10 条 (877.7.6 … 916.5.29)。
        **不是全史**: 只有「劫掠改变了家族关系」时才写 (值 `house_relation_damage_minor_value`
        会落盘), 故覆盖面窄 —— 它只能**正证**, 查不到什么都不排除。"""
        cached = getattr(self, "_house_raid_idx", None)
        if cached is not None:
            return cached
        idx = {}
        db = (self.melt.get("house_relations") or {}).get("database") or {}
        for r in db.values():
            if not isinstance(r, dict):
                continue
            for e in (r.get("history") or []):
                if not isinstance(e, dict):
                    continue
                raw = str(e.get("change_reason") or "")
                if not any(k in raw for k in _RAID_WORDS):
                    continue
                ids = [int(x) for x in _FEUD_CHAR_RE.findall(raw)]
                if len(ids) < 2:
                    continue
                idx.setdefault(str(e.get("date")), []).append((ids[0], ids[1], raw))
        self._house_raid_idx = idx
        return idx

    def _house_raid_on(self, jailer, victim, date):
        """监禁者当日的**劫掠流水**是否指向被囚者本人或其同族 → `'own'` /
        `'house'` / None (v63 第四轮)。

        两条判据, 都要求流水两端序为 (劫掠者=监禁者, 被劫者=…):
          · `'own'`  —— 流水第二端**就是被囚者** ⇒ 当局劫掠的对象本人被擒 (硬证);
          · `'house'` —— 流水第二端与被囚者**同族** ⇒ 当日在劫其族之地而擒其人
                        (家族级旁证; 同日两事巧合的概率极低, 但确实弱于上一条)。

        与 `_last_raid_on` 的关系: 后者读 `landed_data.last_raid`, 只记**最后一次**
        劫掠 (主角该字段已被 919.5.19 覆盖, 915.7.2 因此读不到); 本方法读家族流水,
        是**逐日累积**的, 故补上了那一类日子。"""
        if not date or jailer is None or victim is None:
            return None
        try:
            jailer = int(jailer)
            victim = int(victim)
        except (TypeError, ValueError):
            return None
        vhouse = None
        for raider, target, _raw in self._house_raid_index().get(str(date), []):
            if raider != jailer:
                continue
            if target == victim:
                return "own"
            if vhouse is None:
                vhouse = self._house_of_cid(victim)
            if vhouse is not None and self._house_of_cid(target) == vhouse:
                return "house"
        return None

    def house_flow_on(self, house_a, house_b, date):
        """两族关系流水在**该日**的条目 → [渲染句, …] (v63 第五轮)。

        数据源与《家族恩怨录》同 (`house_relations.database[*].history`), 句面走
        `_rerender_feud_event` (两端角色按事件日期重渲染, 与家族恩怨录逐字同源)。
        用途: 仇人列传的「结仇缘由」补**近因** —— 见 `relation_cause_lines` ④。
        该日无条目 / 渲染不出来时返回 []。"""
        if house_a is None or house_b is None or not date:
            return []
        db = (self.melt.get("house_relations") or {}).get("database") or {}
        out = []
        for r in db.values():
            if not isinstance(r, dict):
                continue
            hs = r.get("houses") or []
            if house_a not in hs or house_b not in hs:
                continue
            for e in (r.get("history") or []):
                if not isinstance(e, dict) or str(e.get("date")) != str(date):
                    continue
                raw = str(e.get("change_reason") or "")
                # v79: 卒日判离 (丧偶当日引擎也写「离婚」) 不入结仇近因
                if self.is_widow_divorce(raw, str(e.get("date") or "")):
                    continue
                txt = self._rerender_feud_event(raw, date, houses=hs)
                if txt and txt not in out:
                    out.append(txt)
        return out

    def house_feud_reason_clause(self, house_a, house_b, date):
        """两族世仇缘由式的触发条 → **因果句** (v79, 用户 2026-09-27)。

        `relation_cause_lines` ④ 原样采用同日流水「昆伯被崔佛无理由囚禁」作结仇缘由,
        而那是**结仇升级日**才写的缘由串 (`house_relation_reason_feud_head_*`,
        `house_relations_l_simp_chinese.yml:78-95`) —— 日期不是事发日、且读起来像当天
        又发生了一次 (崔佛终传/第4、5个十年因此写出「是日崔佛又囚昆伯」「昆伯被囚
        将满十年」)。这里改成因果句, 并把同一条关系记录里**事件式**流水记载的
        真实事发日一并写入; 找不到真日期时只写因果, 不写日期。
        无此类条目返回 ''。"""
        if house_a is None or house_b is None or not date:
            return ""
        db = (self.melt.get("house_relations") or {}).get("database") or {}
        for r in db.values():
            if not isinstance(r, dict):
                continue
            hs = r.get("houses") or []
            if house_a not in hs or house_b not in hs:
                continue
            hist = [e for e in (r.get("history") or []) if isinstance(e, dict)]
            for e in hist:
                if str(e.get("date")) != str(date):
                    continue
                raw = str(e.get("change_reason") or "")
                row = _feud_head_kind(raw)
                if not row:
                    continue
                ids = [int(x) for x in _FEUD_CHAR_RE.findall(raw)]
                if len(ids) < 2:
                    continue
                victim, actor = ids[0], ids[1]
                vn = self._feud_role_title(victim, date) or ""
                an = self._feud_role_title(actor, date) or ""
                if not vn or not an:
                    continue
                # 真事发日 = 同记录里「事件式且受害者相同」的最早一条
                real = ""
                for e2 in hist:
                    raw2 = str(e2.get("change_reason") or "")
                    if not raw2 or row[2] not in raw2 or _feud_head_kind(raw2):
                        continue
                    ids2 = [int(x) for x in _FEUD_CHAR_RE.findall(raw2)]
                    if len(ids2) < 2 or ids2[1] != victim:
                        continue
                    d2 = str(e2.get("date") or "")
                    if d2 and (not real or cl.date_key(d2) < cl.date_key(real)):
                        real = d2
                phrase = row[3].format(j=an)
                if real:
                    return f"{vn}于{self.date(real)}{phrase}，两族由此决裂"
                return f"{vn}{phrase}，两族由此决裂"
        return ""

    def _prison_type_fresh(self, cid, date):
        """该角色**当次**入狱的牢房档位 → `'dungeon'` / `'house_arrest'` / None。

        v63 问题1 第三轮 (2026-09-24 代码调研 §11.A): `prison_data.type` 只在
        「这一档就是待判的那次入狱」时才可用, 判据是三个日期全等:

            `date == pd["date"] == pd["imprison_type_date"]`

        ① `pd["date"]` 是**当前**这次囚禁的开始日 —— 与待判日期不同就说明当事人
           后来又被关过一次 (或已出狱), 这一档描述的不是待判的那次;
        ② `imprison_type_date` 是**档位被设定的那天**, 由 `change_prison_type`
           改写 (`common/scripted_effects/00_intrigue_lifestyle_effects.txt:780`
           等三处调用); 两者不等 ⇒ 原始档位已被覆盖 (本档实测 3 例), 一律返回
           None —— 宁可不用, 不猜。

        用途见 `capture_manner` ④': 战阵俘获路径**恒写 `type = house_arrest`**
        (`combat_events.txt:1295-1298`), 故读到 `dungeon` 即可排除战阵俘获。"""
        if cid is None or not date:
            return None
        for bucket in ((self.melt.get("living") or {}),
                       (self.melt.get("dead_unprunable") or {}),
                       ((self.melt.get("characters") or {}).get("dead_prunable") or {})):
            c = bucket.get(str(cid))
            if not isinstance(c, dict):
                continue
            pd = ((c.get("alive_data") or {}).get("prison_data")
                  or (c.get("dead_data") or {}).get("prison_data"))
            if not isinstance(pd, dict):
                return None
            if str(pd.get("date")) != str(date) \
                    or str(pd.get("imprison_type_date")) != str(date):
                return None
            t = pd.get("type")
            return str(t) if t else None
        return None

    def _same_day_imprisoned(self, jailer, date):
        """该 (监禁者, 日) 同日入狱的**记忆 id** 列表 → [mid, …] (惰性缓存)。

        v63 (问题1 第二轮): 「同日同监禁者」这一簇是**一次行动**, 故簇级的
        人口学判据 (有没有未成年人) 要按整簇看, 不能只看当前这一行 ——
        实测 907.1.16 那一簇 7 人里含 9 岁与 11 岁男童, 但被囚者本人可能是
        成年骑士, 只看本人的年龄就会误判成战阵俘获。被囚者 id 由
        `_mem_holder_index()` 反查 (记忆对象本身不带 owner)。"""
        key = (jailer, str(date))
        cache = getattr(self, "_same_day_cache", None)
        if cache is None:
            cache = {}
            self._same_day_cache = cache
        if key in cache:
            return cache[key]
        out = []
        if jailer is not None:
            db = (self.melt.get("character_memory_manager") or {}).get("database") or {}
            for mid, e in db.items():
                if not isinstance(e, dict) or e.get("type") != "imprisoned":
                    continue
                if str(e.get("creation_date")) != str(date):
                    continue
                if (e.get("participants") or {}).get("imprisoner") != jailer:
                    continue
                try:
                    out.append(int(mid))
                except (TypeError, ValueError):
                    continue
        cache[key] = out
        return out

    def _has_minor_victim(self, jailer, date, victim):
        """该日该监禁者的入狱簇里是否有未成年人 (含被囚者本人)。"""
        a = self._age_at(victim, date)
        if a is not None and a < 16:
            return True
        holder = self._mem_holder_index()
        for mid in self._same_day_imprisoned(jailer, date):
            v = holder.get(mid)
            if v is None or v == victim:
                continue
            av = self._age_at(v, date)
            if av is not None and av < 16:
                return True
        return False

    def capture_manner(self, victim, jailer, date, cluster_n=1):
        """该次囚禁的**获取方式** (v63 问题1) → (档位, 证据说明)。

        用户 2026-09-24 口径: 不确定能否区分「破城俘虏」与「战败俘虏」就再查 ——
        追加调研 (`docs/调研_囚禁方式与存档留痕.md` §10) 的结论是:
        **本档无法把任何一次同日多人入狱判成破城或战败**, 因为

          · 战斗俘获 / 城破俘获 / 劫掠掳人 三者最终都是裸 `imprison`
            (`combat_events.txt:1295`; `00_prison_effects.txt:1950/1958`;
            `raid_events.txt:1017`), 存档字段完全一致;
          · `melt["sieges"]` 只保留**存档时点仍在进行**的攻城 (922 档最早
            start_date 只到 918.3.31), 895–915 的六个批次全在窗口之外;
          · 省份 `occupant` 是**当前状态**而非历史;
          · 主角侧六个批次日期没有任何 `battle_won_memory`。

        故这里只给**有硬证**的档位, 其余一律 `unknown` —— 而 `unknown` 的措辞
        不含任何方式词 (这正是「模型自己造出宴会擒获」的缺口被关掉的地方):

          | 档位 | 判据 |
          | --- | --- |
          | `diarchy` | 在押者带 `imprisoned_by_diarch` 变量 (全库唯一 set 点) |
          | `raid` | 监禁者当日劫掠过: ②a `landed_data.last_raid` == 入狱日, 或 ②b 家族关系流水同日一条「劫掠者=监禁者, 被劫者=被囚者本人/同族」(见 `_house_raid_on`)。**排在 `batch` 之前** —— 硬证优先于启发式 |
          | `batch` | 同日同监禁者 ≥3 人 ⇒ 群体俘获, 排除战败俘获 (一次打仗不会同时抓来 3 名以上互不相干的人) |
          | `battle_poi` | 省份战场兴趣点 winner/**loser**/日期与该次入狱三者对齐 (确定性, 覆盖窄) |
          | `battle` | 同日**真·战斗**记忆 (`battle_won_memory` / `battle_lost_memory`): 被囚者是 `loser`、监禁者是胜方 |
          | `not_battle` | 被囚者本人 < 16 岁, 或同簇内有未成年人 ⇒ 排除战败俘获 |
          | `unknown` | 以上皆不成立 → **不写方式** |

        第三条排除战败俘获的硬判据 (第三轮, 见 `_prison_type_fresh`): 待判那次的
        `prison_data.type == dungeon` 且日期三全等 ⇒ **排除战阵俘获**, 于是 `battle`
        与 `battle_poi` 两档都被关掉 (本档实测 147/462 = 31.8% 的在押者可这样排除)。
        依据: 战阵俘获路径恒写 `type = house_arrest` (`combat_events.txt:1295-1298`),
        而裸 `imprison` 的默认档位是 `dungeon`。反向不成立 —— `house_arrest` 并不
        蕴含战阵俘获 (312/462 在押者是 `house_arrest`), 故它**只能否证、不能正证**。
        `raid` 档不受此限 (劫掠掳人走裸 `imprison`, 本就是 dungeon)。

        同一次实验还纠掉了一个**假阳性来源** (第三轮): `war_won` / `war_lost`
        是**战争结束**记忆, 曾经也进 `battle` 档 —— 实测 24 条被判「战阵俘获」的
        在押者里, 9 条只匹配到 war_* (战争结束当天入狱), 这 9 条的 `type` 全是
        `dungeon`。现在 `battle` 档只收 `battle_` 前缀的条目, 战争结束不再被说成
        「战阵俘获」, 那类日子退回裸「囚禁」(方式词只在程序确知时出现)。

        `not_battle` 的依据 (2026-09-24 第二轮追加调研实测): 战败俘获的候选池被
        硬限制为败方**主指挥官**(`combat_events.txt:640-641`)＋ `every_side_knight`
        (`:760-762`), 必为成年参战者; 而城破俘获的池子是**男爵领 holder ＋
        `every_courtier_or_guest`**(`siege_events.txt:115-134`), 含婴幼儿。
        正样本对照: 9 处 `battle_poi_enemy_commander_imprisoned` 的被俘主帅年龄为
        21/35/36/38/45/46/49/52/53/61 —— **无一个未成年人**。
        故「< 16 岁被囚」可高置信排除战败俘获 (措辞只写「拘押」＋当时年龄);
        **反向不成立**: 全成年全男性既不能排除战败, 也不能反推战败 (围城亦可只抓
        成年男性)。注意「有女性 ⇒ 非战败」是**错的** —— 正样本里就有 49 岁的女
        主帅 (16726), 唯一可靠判据是年龄。

        返回 `(tag, note)`; `note` 只作日志/断言用, 不进提示词。"""
        try:
            victim = int(victim)
            jailer = int(jailer) if jailer is not None else None
        except (TypeError, ValueError):
            return ("unknown", "")
        if victim is None or not date:
            return ("unknown", "")
        # ① diarchy 摄政绑架 (确定性)
        if "imprisoned_by_diarch" in self._var_flags(victim):
            return ("diarchy", "imprisoned_by_diarch")
        # ② 正证劫掠 —— 两条判据 (任一成立即判):
        #    ②a 监禁者的 `landed_data.last_raid` == 入狱日 (只记最后一次, 覆盖窄);
        #    ②b **家族关系流水**里同日一条劫掠条目, 劫掠者=监禁者, 被劫者=被囚者
        #        本人或其同族 (逐日累积, 补上 ②a 被覆盖掉的日子 —— 实测 915.7.2
        #        埃德伯正是这一类: 记忆库里两条只有「入狱」, 而家族流水写着
        #        「国王崔佛劫掠了女王埃德伯」)。
        #    第四轮定序: 本档排在 `batch` **之前** —— `batch` 只给一个无方式词的
        #    「拘押」, 它的作用是**阻止**战阵俘获档 (见下), 本身不是方式词; 而劫掠
        #    是有存档硬证的方式, 硬证优先于启发式。全档改判面实测 24 行/11 簇
        #    (皆为 batch→raid), 本战役 915.7.2 那一簇 (埃德伯等 7 人) 即其一。
        if self._last_raid_on(jailer, date):
            return ("raid", f"last_raid={date}")
        _hk = self._house_raid_on(jailer, victim, date)
        if _hk:
            return ("raid", f"house_relation_raid/{_hk}")
        # ③ **同日同监禁者 ≥3 人即为群体俘获** ⇒ 排除战败俘获。
        #    战败俘获的池子是败方主指挥官 ＋ 骑士 (逐人成擒), 一次打仗不会同时
        #    抓来 3 名以上互相不相干的人; 本战役实测 895.1.14 三人全是儿童、
        #    907.1.16 七人含 9/11 岁男童、911.3.20 十一人含 8 名未成年 ——
        #    用户 2026-09-24 的观察 (「多数同日批次不是战败俘虏」) 在六个批次上
        #    全部成立。
        #    `cluster_n` 由调用方给 (见 `_pair_imprisonments` 的 `_pm["n"]`) ——
        #    实测**囚犯侧记忆会被引擎回收** (907.1.16 七人中六人已死, 其
        #    `imprisoned` 记忆全无, 只能靠主角侧 `imprisoned_other` 数出人数),
        #    故不能在这里回查记忆库。
        if cluster_n >= 3:
            return ("batch", f"{cluster_n}人同日")
        # ③' 牢房档位否证 (第三轮): `dungeon` + 日期三全等 ⇒ 排除战阵俘获。
        #     战阵俘获恒写 `type = house_arrest` (`combat_events.txt:1295-1298`),
        #     而裸 `imprison` 默认 dungeon; 故 dungeon 与 battle / battle_poi
        #     两档互斥。**只否证、不正面定档** —— 劫掠(②)不受影响。
        _no_battle = self._prison_type_fresh(victim, date) == "dungeon"
        # ④ 省份战场兴趣点 (确定性, 覆盖窄; 须 winner + loser + 日期三者对齐)
        if jailer is not None and not _no_battle:
            hits = self._battle_poi_hits(jailer, date, victim=victim)
            if hits:
                return ("battle_poi", f"province={hits[0]}")
        # ⑤ 同日**真·战斗**记忆 (只认 `battle_*_memory`) 且被囚者是输家
        #    (监禁者已知时必须同时是胜方 —— 同一天可能有多场仗)。
        #    第三轮修正: `war_won` / `war_lost` 是**战争结束**记忆, 不是战斗 ——
        #    实测 24 条被旧判据判成「战阵俘获」的在押者里, 9 条其实只匹配到
        #    war_* (战争结束那天入狱, 且那一仗的败方是该人), 而这 9 条的
        #    `prison_data.type` **全是 dungeon** —— 正是「战争结束 ≠ 沙场被擒」
        #    的存档铁证 (战阵俘获路径恒写 house_arrest)。故 war_* 不再进本档,
        #    让这类日子退回裸「囚禁」而不声称战阵俘获。
        for rec in (() if _no_battle else self._battle_by_date().get(str(date), [])):
            if not str(rec[0]).startswith("battle_"):
                continue
            loser, winner = self._battle_winner(rec)
            _ok = (loser == victim) and (winner == jailer if jailer is not None
                                         else True)
            if _ok:
                return ("battle", f"{rec[0]} loser={loser} winner={winner}")
        # ⑥ 被囚者本人未成年, 或同簇内有未成年人 ⇒ 排除战败俘获
        #    (战败池只有成年参战者; 城破池含宫廷与家眷)
        _age = self._age_at(victim, date)
        if _age is not None and _age < 16:
            return ("not_battle", f"{_age}岁")
        if self._has_minor_victim(jailer, date, victim):
            return ("not_battle", "同簇含未成年人")
        return ("unknown", "")

    def sex_mem_lines(self, cid, as_of=None, player=None):
        """该角色相关的**强迫/半强迫性事** → [「日期，句」] (v63 问题3, 用户拍板)。

        出口**只有《列传·好友》《列传·仇人》**: 用户 2026-09-24 拍板「只需要补
        埃德伯的强奸记忆……只有仇人/好友列传需要加, 其他的都不需要」。角色档案
        (`_characters` 的「行迹」) 与公开年表 (`_timeline`) 两侧都按 v59 口径
        不收性事, 旧稿因此**两侧互相指认对方出句而实际谁都没出** —— 本方法补上
        这条唯一的出口, 由 `biography._subject_facts` 挂进该篇纪事块。

        两个数据源取并集并按 (日期, 体位, 自愿档, 对方) 去重:
          ① **当事人自己持有的**性事记忆 —— 键名带 `giving/receiving` 即方向,
             受害方那一条直接得「X被Y强迫…」;
          ② **主角持有的**同一次记忆 (`sex_partner == cid`) —— 受害方的记忆会随
             当事人死亡被引擎回收 (见 `docs/调研_Carnalitas性事记忆留痕.md`),
             主角侧那条 (playable 线, 1300+ 年) 才耐久; 这一路按**受害方口径**
             渲染, 免得把「主角强迫埃德伯」写成「埃德伯强迫主角」。

        只收 `noncon` / `dubcon` (用户 2026-09-14 拍板); `as_of` 之后的不出。"""
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return []
        try:
            player = int(player) if player is not None else None
        except (TypeError, ValueError):
            player = None
        db = (self.melt.get("character_memory_manager") or {}).get("database") or {}
        holder = self._mem_holder_index()
        out = {}
        for mid, e in db.items():
            if not isinstance(e, dict):
                continue
            t = str(e.get("type") or "")
            info = sex_mem_info(t)
            if info is None or not info["kept"]:
                continue
            parts = e.get("participants") or {}
            other = parts.get(_SEX_PARTNER_SLOT)
            if not isinstance(other, int):
                continue
            try:
                h = holder.get(int(mid))
            except (TypeError, ValueError):
                h = None
            if h == cid and other != cid:
                s = _sex_mem_sentence(self, cid, e, info)
                key_other = other
            elif player is not None and h == player and other == cid:
                # ② 主角侧反查: 该条记的是「主角 giving」, 但句面要站受害方
                act = info["act"] or "base"
                w = _style.SEX_MEM_WORDING["victim_noncon" if info["consent"] == "noncon"
                                           else "victim_dubcon"]
                nm = self.event_name(cid, date=e.get("creation_date"))
                om = self.event_name(player, date=e.get("creation_date"))
                s = w.get(act, w["base"]).format(name=nm, other=om) if (nm and om) else ""
                # 去重键站**当事人视角**的对方 —— 否则同一次性事的
                # 「自己那条 (sex_partner=主角)」与「主角那条 (sex_partner=自己)」
                # 会算成两条, 同一句话出两遍 (实测 44335 出两行)。
                key_other = player
            else:
                continue
            if not s:
                continue
            _md = self.mem_date(cid, e)
            if as_of and _md and cl.date_key(_md) > cl.date_key(as_of):
                continue
            out[(_md, info["act"], info["consent"], key_other)] = \
                f"{self.date(_md)}，{s}"
        return [out[k] for k in sorted(out, key=lambda x: cl.date_key(str(x[0])))]

    def _prison_opinion_index(self):
        """{(owner, target): [(modifier, start_date)]} + 按 owner 的兜底索引 (惰性)。"""
        cached = getattr(self, "_prison_opinions", None)
        if cached is not None:
            return cached
        by_pair, by_owner = {}, {}
        for o in (self.melt.get("opinions") or {}).get("active_opinions") or []:
            if not isinstance(o, dict):
                continue
            ow, tg = o.get("owner"), o.get("target")
            if not isinstance(ow, int) or not isinstance(tg, int):
                continue
            for v in cl._opinion_values(o):
                mod = str(v.get("modifier") or "")
                if mod not in self._PRISON_MANNER_MODS:
                    continue
                st = str(v.get("start_date") or "")
                by_pair.setdefault((ow, tg), []).append((mod, st))
                by_owner.setdefault(ow, []).append((mod, st))
        self._prison_opinions = (by_pair, by_owner)
        return self._prison_opinions

    def release_manner(self, victim, jailer, out_date):
        """出狱缘由 (v55 问题1c) → (结局族, 措辞); 判不出返回 ('', '')。

        判据 = 该被囚者在**出狱当日**新得的出狱类好感修饰符 (存档自带 start_date,
        比逐档差分精确)。诛灭世族那一档不在这里 —— 由 v54 既有判据单独承担
        (见 `family_purge_victims` / `_purge_dates`, 方案 §1.3-B)。

        v56 (问题3): 熔件里读不到时回退 `cache["prison_manners"]` (逐档闩存) ——
        出狱类好感 10 年衰减、且随持有者死亡立即消失, 终传只载末档熔件,
        十年前那一批释放的缘由否则永久丢失 (斯卡利茨 924 年那批全成「获释」)。"""
        if victim is None or not out_date:
            return ("", "")
        d = str(out_date)
        by_pair, by_owner = self._prison_opinion_index()
        rows = list(by_pair.get((int(victim), int(jailer)), [])) \
            if isinstance(jailer, int) else []
        if not any(st == d for _m, st in rows):
            rows += by_owner.get(int(victim), [])
        for mod, st in rows:
            if st == d:
                return self._PRISON_MANNER_MODS[mod]
        return self._latch_manner(victim, jailer, d)

    def _latch_manner(self, victim, jailer, date):
        """出狱缘由的**缓存回退** (v56 问题3) —— 读 cache["prison_manners"]。

        闩存记录 (见 `cache_lib._latch_prison_manners`) 的 `kind` 有两种形态:
        好感来源记**修饰符名** (demanded_hook / ransomed_from_prison …),
        牵制来源记**结局族名** (hook = 赎金·人情分支的 favor_hook/indebted_hook)。"""
        if not isinstance(jailer, int):
            return ("", "")
        rec = (self.cache.get("prison_manners") or {}).get(
            f"{int(victim)}>{int(jailer)}>{date}")
        if not isinstance(rec, dict):
            return ("", "")
        kind = str(rec.get("kind") or "")
        if kind in self._PRISON_MANNER_MODS:
            return self._PRISON_MANNER_MODS[kind]
        if kind in self._PRISON_KIND_WORD:
            return (kind, self._PRISON_KIND_WORD[kind])
        return ("", "")

    def is_purge_prisoner(self, victim, jailer, date):
        """该次囚禁是否属**诛灭世族** (v55 问题1b) —— 判据取自 `b99d162` (v54)。

        v54 在 `_timeline` 里用的是**双判据**: ①受害者在 `family_purge_victims(监禁者)`
        名单内; ②该日 ∈ `_purge_dates(监禁者)` 且监禁者是主角。年表那一侧只做**丢弃**,
        故①不带日期也安全; 本处是**造行** (族级句), 不带日期的①会把几十年后的事搬到
        当年 —— 实测任宗本 927.8.2 被沙米尔囚禁、933.5.15 才被处决, 却因①在 927.8.2
        造出「诛灭任氏满门」。故此处只取**带日期的②**, 并把「监禁者是主角」按同一口径
        放宽为「监禁者属主角一族」(亨利/马丁/沙米尔三代同族)。

        实测: 诛灭日的逐人监禁记忆与该日诛灭日**同日** (918.4.8 49 条、920.1.24 72 条、
        924.3.25 129 条), ②足以覆盖①在本篇的全部命中面。"""
        return jailer is not None and bool(date) \
            and str(date) in self._purge_dates(jailer)

    def house_purge_pairs(self, house_id, my_houses):
        """该族在**诛灭日**上被处决的 (日期, 行刑者) 对 (v55 问题1b)。

        与 `_house_prison_nodes` 的 purge 判据同源 (`_purge_dates`): 有些族的族人并未
        在诛灭日下狱 (如陶氏/边氏: 917.11.13 下狱、918.4.8 才处决家主), 只认监禁节点会
        漏掉它们的族级行 —— v54 `family_purge_events(15403)` 对同一天给的是
        「诛灭…42 族」, 两处口径必须一致。"""
        out = set()
        for cid, c in self._chars.items():
            if not isinstance(c, dict) or c.get("dynasty_house") != house_id:
                continue
            dd = c.get("dead_data") or {}
            if dd.get("reason") != "death_execution":
                continue
            k = dd.get("killer")
            d = str(dd.get("date") or "")
            if not isinstance(k, int) or not d:
                continue
            k = int(k)
            if k not in my_houses and self._house_of_cid(k) not in my_houses:
                continue
            if d in self._purge_dates(k):
                out.add((d, k))
        return out

    def house_purge_line(self, killer, house_id, date, house_label=""):
        """单族的**诛灭族级行** (v55 问题1b): 「924年3月25日，X诛灭裴氏满门，
        处决家主N人，余族尽数流放」。

        收尾沿用 v54 用户拍板措辞 (凡有地者一律处决, 被流放者必是无地残党, 不列名;
        见 `family_purge_events`)。家主 N = 该日该族被处决者数。"""
        if killer is None or not date:
            return ""
        d = str(date)
        house_label = house_label or self._house_label(house_id) or ""
        if not house_label:
            return ""
        n = 0
        for cid, c in self._chars.items():
            if not isinstance(c, dict):
                continue
            dd = c.get("dead_data") or {}
            if dd.get("reason") != "death_execution" or dd.get("killer") != int(killer):
                continue
            if str(dd.get("date") or "") != d:
                continue
            if c.get("dynasty_house") != house_id:
                continue
            n += 1
        jn = self._feud_role_title(killer, d) or "主角"
        head = f"{jn}诛灭{house_label}满门"
        if n:
            head += f"，处决家主{n}人"
        return head + "，余族尽数流放"

    def _house_prison_nodes(self, other_house, my_houses, as_of,
                            raw_entries=None):
        """族间囚禁节点 (v55 问题1b/1c/1d; **v78 起双向**)。

        返回 [{"date", "victim", "jailer", "vn", "jn", "text", "kind", "sp",
               "purge", "from_history"}]。
        两个方向都做 (用户 2026-09-27 报告: 旧稿只做「我方囚他族」, 于是我方族人
        被他族囚禁时只剩游戏原文流水、永远没有结局句):
          · `我方囚他族`: victim 属 other_house, jailer 属 my_houses;
          · `他族囚我方`: victim 属 my_houses, jailer 属 other_house。
        结局一律走唯一出口 `prison_exit` + `prison_tail` (v78-1), 句首走
        `prison_capture_head` (补「怎么抓」)。
        `raw_entries` = 恩怨史原文里含囚禁词的条目 [{date, ids, text}] ——
        继任传主的缓存里被囚者的 `imprisoned` 记忆常已被引擎回收 (久保缓存
        只有 920–922 三档, 大和好风等四人的记忆全无), 靠原文流水的
        `ONCLICK id` + 缓存死亡记录兜底成节点, 免得那几天只剩「囚禁了X」没有下文。"""
        cache = self.cache
        chars = cache.get("characters") or {}
        W = _style.FACT_WORDING
        out = []

        def _house(cid):
            return self._house_of_cid(cid)

        def _in_span(d):
            return not (as_of and d and cl.date_key(d) > cl.date_key(as_of))

        def _direction(vh, jh):
            """本节点属哪个方向; 与本次恩怨无关返回 None。"""
            if vh == other_house and jh in my_houses:
                return "fwd"          # 我方囚他族
            if vh in my_houses and jh == other_house:
                return "rev"          # 他族囚我方
            return None

        def _build(victim, jailer, d, purge, from_history):
            head = self.prison_capture_head(victim, jailer, d, cluster_n=1)
            if not head:
                return None
            tail, kind, sp = self.prison_tail(victim, jailer, d, purge=purge)
            return {"date": d, "victim": victim, "jailer": jailer,
                    "vn": self._feud_role_title(victim, d),
                    "jn": self._feud_role_title(jailer, d),
                    "text": head + tail, "kind": kind, "sp": sp,
                    "purge": purge, "from_history": from_history}

        out = []
        _seen = set()
        for cid_s, rec in chars.items():
            try:
                cid = int(cid_s)
            except (TypeError, ValueError):
                continue
            vh = _house(cid)
            if vh != other_house and vh not in my_houses:
                continue
            for m in rec.get("memories") or []:
                if (m.get("type") or "") != "imprisoned":
                    continue
                jailer = (m.get("participants") or {}).get("imprisoner")
                if not isinstance(jailer, int):
                    continue
                if _direction(vh, _house(jailer)) is None:
                    continue
                d = str(m.get("creation_date") or "")
                if not _in_span(d):
                    continue
                # v55 (问题1d): 同一人被同一人同日囚禁的重复记忆只留一条
                # (实测王从规 924.2.23 有两条逐字相同的 imprisoned 记忆)
                if (d, cid, jailer) in _seen:
                    continue
                _seen.add((d, cid, jailer))
                node = _build(cid, jailer, d,
                              self.is_purge_prisoner(cid, jailer, d), False)
                if node:
                    out.append(node)
        # 原文流水兜底: 只在该 (日期, 被囚者) 尚无记忆节点时造节点
        for ent in (raw_entries or []):
            d = str(ent.get("date") or "")
            if not d or not _in_span(d):
                continue
            ids = [i for i in (ent.get("ids") or []) if isinstance(i, int)]
            if len(ids) < 2:
                continue
            # v79: 世仇缘由式囚禁流水 (「A被B无理由囚禁」, id 次序 = 被囚者, 施事者;
            # 日期是结仇升级日) 不造节点 —— 该囚禁事实另有事件式专属行与节点。
            _rawtxt = ent.get("raw") or ent.get("text") or ""
            if _is_feud_reason_prison(_rawtxt):
                continue
            # v78: 事件式流水模板恒为「[施事者]囚禁了[对象]」
            # (house_relations_l_simp_chinese.yml:50), 故 id 出现次序即
            # (监禁者, 被囚者) —— 不能按「谁属对方家族」定角色: 反向条目
            # (他族囚我方) 的施事者才是对方族人。
            victim = jailer = None
            _a, _b = ids[0], ids[1]
            _ah, _bh = _house(_a), _house(_b)
            if _ah in my_houses and _bh == other_house:
                jailer, victim = _a, _b
            elif _ah == other_house and _bh in my_houses:
                jailer, victim = _a, _b
            if victim is None or jailer is None:
                continue
            if (d, victim, jailer) in _seen or \
                    any(n["date"] == d and n["victim"] == victim for n in out):
                continue
            node = _build(victim, jailer, d,
                          self.is_purge_prisoner(victim, jailer, d), True)
            if node:
                out.append(node)
        return out

    def _fold_house_prison_nodes(self, nodes):
        """同日同监禁者的囚禁节点折叠 (v55 问题1d)。

        取名沿用 v54 §6.1 规则 (头衔层级降序 → 执政起始日升序 → 前 5 人 + 等N人);
        v78 (D2) 起收口与年表侧同用 `_prison_fold_tail`: 按「结局族 × 时长」计数,
        时长写「N年后」不写终止关押日, 故含处决/狱中亡的簇也照折
        (旧稿是「尽数获释」/「其中3人获释」的多人不带时长口径)。"""
        W = _style.FACT_WORDING
        groups, order = {}, []
        for n in nodes:
            key = (str(n.get("date") or ""), n.get("jailer"))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(n)
        out = []
        for key in order:
            rows = groups[key]
            d, jailer = key
            if len(rows) < 2:
                n = rows[0]
                out.append((n["date"], n["text"]))
                continue
            ranked = []
            for n in rows:
                rank, since = self.title_rank_since_at(n["victim"], d)
                ranked.append((rank, since, n))
            ranked.sort(key=lambda r: (-r[0],
                                       cl.date_key(r[1]) if r[1] else _DATE_KEY_MAX,
                                       r[2]["victim"]))
            names = [r[2].get("vn") or "" for r in ranked]
            names = [x for x in names if x]
            if not names:
                continue
            shown = "、".join(names[:5])
            if len(names) > 5:
                shown += f"等{len(names)}人"
            jn = rows[0].get("jn") or ""
            body = W["prison_jailed"].format(jailer=jn, victim=shown) if jn \
                else W["prison_held"].format(victim=shown)
            body += _prison_fold_tail(
                [{"o": r.get("kind") or "released", "sp": r.get("sp") or ""}
                 for r in rows], self)
            out.append((d, body))
        return out

    def _house_war_nodes(self, other_house, my_houses, as_of):
        """两族之间的**战争因果节点** (v34, 问题6): [(日期, 句)]。

        恩怨史的数据源 `house_relations.history` 只记「关系值变动的那一下」
        (结仇那天的囚禁), 战争胜负与夺地两端全在缓存记忆里 — 于是模型只能把
        围城被俘读成结仇之因 (柳特佩特局: 两次征服战争 → 战败 → 失守那波利
        伯爵领 → 沦为无地冒险者, 旧文案写成「绑了人家族人」)。
        这里按记忆直算四个节点: 宣战 / 战胜 / 夺其头衔 / 对方沦为无地冒险者。"""
        cache = self.cache
        pid = cache.get("player_id")
        if pid is None:
            return []
        chars = cache.get("characters") or {}
        out = []

        def _house(cid):
            return self._house_of_cid(cid)

        def _nm(cid, date=None):
            # v42 (问题4, 用户拍板2): 主角只出名字 (家族恩怨录同样逐行重复头衔)
            return self.event_name(cid, date) if cid else ""

        def _in_span(d):
            return not (as_of and d and cl.date_key(d) > cl.date_key(as_of))

        # ---- ① 主角对该族成员的宣战 / 战胜 (征服战写明「征服」) ----
        prec = chars.get(str(pid)) or {}
        for m in prec.get("memories") or []:
            t = m.get("type") or ""
            if t not in ("offensive_war", "war_won"):
                continue
            d = m.get("creation_date") or ""
            if not _in_span(d):
                continue
            parts = m.get("participants") or {}
            other = parts.get("other_party") if t == "offensive_war" \
                else parts.get("loser")
            if not isinstance(other, int) or _house(other) != other_house:
                continue
            onm = _nm(other, d)
            if t == "offensive_war":
                cb = ""
                for v in m.get("vars") or []:
                    if v.get("flag") == "war_cb":
                        cb = str(v.get("value") or "")
                        break
                kind = "征服战" if "conquest" in cb else "开战"
                # v42 (问题4, 用户拍板2): 主角只出名字 (此处原用 event 式带全头衔)
                out.append((d, f"{self.event_name(pid, d)}向{onm}"
                               f"发动{kind}"))
            else:
                out.append((d, f"{self.event_name(pid, d)}战胜{onm}"))
        # ---- ② 该族成员被**我方家族**囚禁及其出狱情形 ----
        # v55 (问题1b/1c/1d): 监禁侧整段移到 `_house_prison_nodes` —— 判据与措辞都换了
        # (监禁者放宽到我方家族全体; 出狱缘由接入 release_manner; 诛灭日改族级行)。
        # 此处不再出逐人囚禁句, 免得与节点重复。
        # ---- ③ 对方失守头衔 (reason=conquest → 攻取) ----
        lost_titles = []
        for cid, rec in chars.items():
            if _house(int(cid)) != other_house:
                continue
            for m in rec.get("memories") or []:
                if (m.get("type") or "") != "lost_title_memory":
                    continue
                # v34b: 失守日取 title history 事件日 (记忆日常晚一天)
                d = self.mem_date(int(cid), m)
                if not _in_span(d):
                    continue
                parts = m.get("participants") or {}
                if parts.get("new_holder") != pid:
                    continue
                tid = None
                for v in m.get("vars") or []:
                    if v.get("flag") == "landed_title" and v.get("identity"):
                        tid = v.get("identity")
                        break
                tname = self.title(tid) if tid else ""
                nm = _nm(int(cid), d)
                out.append((d, f"{nm}失守{tname}" if tname else f"{nm}失守领地"))
                lost_titles.append((d, int(cid), tname))
        # ---- ③ 对方此后沦为无地冒险者 (问题6 的关键答案: 为什么记恨) ----
        seen_cid = None
        for d, cid, tname in sorted(lost_titles, key=lambda x: cl.date_key(x[0])):
            if self._title_kind_landless(cid, d):
                nm = _nm(cid)
                if nm and cid != seen_cid:
                    out.append((d, f"{nm}自此沦为无地冒险者"))
                    seen_cid = cid
                break
        out.sort(key=lambda x: cl.date_key(x[0]))
        return out

    def _title_kind_landless(self, cid, date):
        """该角色在 date 是否已无领地头衔 (沦为无地冒险者)。"""
        try:
            tier, tid = self._primary_title_at(cid, as_of=date)
        except Exception:
            return False
        if tid is None:
            return True
        return self.title_kind(tid) in ("camp", "estate", "none")

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
        # v78-6 (用户 D6): 十年档只写**该 10 年**内的恩怨流水 (旧稿把入档前的全部
        # 流水一并列出, 与 v77「传主时代闸」同旨); 终传/在世传 (无 decade) 窗口 = 一生。
        # 另: 现档位已回中立、但窗口内有负面流水的族**照样入选** (旧稿只看现档位,
        # 于是「世仇已息」的族整族消失) —— 这类行的档位词写「旧怨」。
        _lo = None
        if getattr(self, "decade", None) and self.as_of:
            try:
                _lo = _decade_lower_bound(self)
            except Exception:
                _lo = None
        _lok = cl.date_key(_lo) if _lo else None
        _hikey = cl.date_key(str(self.as_of)) if self.as_of else None

        def _in_window(d):
            if not d:
                return False
            k = cl.date_key(d)
            if _lok is not None and k < _lok:
                return False
            if _hikey is not None and k > _hikey:
                return False
            return True

        out = []
        for _k, r in db.items():
            if not isinstance(r, dict):
                continue
            hs = r.get("houses") or []
            if not any(h in my_houses for h in hs):
                continue
            lvl = r.get("level") or ""
            _neg_in_win = any(_in_window(str(e.get("date") or ""))
                              and (e.get("amount") or 0) < 0
                              # v79: 卒日判离不是仇怨, 不据此把族拉进恩怨录
                              and not self.is_widow_divorce(
                                  e.get("change_reason") or "",
                                  str(e.get("date") or ""))
                              for e in (r.get("history") or []))
            if lvl not in NEG and not _neg_in_win:
                continue
            other = [h for h in hs if h not in my_houses]
            if not other:
                continue
            # v29: 家族名取不到时回退宗族名, 再不济「某家族」— 不泄露家族 id
            _hname = cl.house_name_zh(self.melt, other[0]) or ""
            if not _hname:
                _did = cl.dynasty_id_of(self.melt, other[0])
                if _did is not None:
                    _hname = cl.dynasty_name_zh(self.melt, _did) or ""
            _hlabel_raw = _hname or "某家族"
            _hlabel = self._house_label(other[0]) or _hlabel_raw
            events = []
            _raw_ids = {}      # (日期, 句面) -> 该条流水里的角色 id 集 (v55; v78 扩到两端)
            _raw_prison = []   # v78: 含囚禁词的流水条目 {date, ids, text} — 节点兜底用
            for e in (r.get("history") or []):
                d = str(e.get("date") or "")
                # v11: as_of 截断 — 十年传记只列该时期前的恩怨事件
                if self.as_of and d and cl.date_key(d) > cl.date_key(self.as_of):
                    continue
                # v78-6 (用户 D6): 十年档的**下界** —— 只写该 10 年内的事件
                if _lok is not None and d and cl.date_key(d) < _lok:
                    continue
                # v14: change_reason 两端角色按事件日期重渲染 (补国号,
                # 修复方案_菲利普2.md 问题3: 游戏原文只写「国王/王」无国号)
                # v43: 传两族 id 与对方族称 —— 自指式条目降级为「{对方家族}族人」
                _raw = e.get("change_reason") or ""
                # v79: 卒日判离 (见 `is_widow_divorce`) —— 引擎在一方亡故当日也写
                # 「离婚」流水, 用户 2026-09-27 报告久保终传据此写出「919年2月24日
                # 浩二与大和春子、大和规子离婚」。整条不入事件、不入节点兜底、
                # 不参与 `_neg_in_win` 入选判据。
                if self.is_widow_divorce(_raw, d):
                    continue
                # v79: 世仇缘由式囚禁 (被动句, id 次序反 + 日期是结仇升级日) 整条
                # 不入事件、不入节点兜底 —— 该囚禁事实另有事件式专属行 (实测 4/4)。
                if _is_feud_reason_prison(_raw):
                    continue
                txt = self._rerender_feud_event(_raw, d,
                                                houses=hs, other_label=_hlabel)
                if not txt:
                    # v29: 原文不可读 (rakaly 哨兵串/未解析键) → 缓存记忆重建
                    txt = self._feud_event_fallback(my_houses, other[0], d, _hlabel)
                if not txt:
                    continue
                _ids = []
                for _i in _FEUD_CHAR_RE.findall(str(_raw)):
                    try:
                        _ic = int(_i)
                    except (TypeError, ValueError):
                        continue
                    # v78: 两端 id 都收 —— 反向囚禁 (他族囚我方) 的节点配对与
                    # 同日原文抑制都要用到我方一侧的 id (旧稿只收对方家族)。
                    # **保持原文出现次序**: 囚禁句的模板是「[施事者]囚禁了[对象]」,
                    # 次序即 (监禁者, 被囚者) —— 排序会把它毁掉。
                    if self._house_of_cid(_ic) is not None and _ic not in _ids:
                        _ids.append(_ic)
                _raw_ids[(d, txt)] = set(_ids)
                if any(_k in txt for _k in _PRISON_KIND_WORDS):
                    _raw_prison.append({"date": d, "ids": list(_ids),
                                        "text": txt, "raw": _raw})
                events.append((d, txt))
            # v34 (问题6): 补战争因果节点 — 宣战/战胜/夺其头衔/沦为无地冒险者。
            # 关系流水的「向X宣战」不带战争类型、「成为X的仇敌」只记结果,
            # 故**同日的战争类旧句由本节点取代** (改写进同一天, 信息更全):
            #   「向X发动征服战」「战胜X」「X失守那地」「X自此沦为无地冒险者」。
            # v34b: 只在**关系流水**里做同日取代 — 本段补的节点彼此同日并存
            # (同日「战胜X」与「X失守那地」是同一场战争的两种事实, 旧实现在
            # 失守日与战胜日同日时会把「战胜X」一并删掉)。
            _hist_events = list(events)
            _node_events = []
            for d, txt in self._house_war_nodes(other[0], my_houses, self.as_of):
                _hist_events = [
                    (ed, et) for ed, et in _hist_events
                    if str(ed) != str(d)
                    or not any(k in et for k in
                               _WAR_KIND_WORDS + _PRISON_KIND_WORDS)]
                if (str(d), txt) not in {(str(ed), et) for ed, et in
                                         _hist_events + _node_events}:
                    _node_events.append((d, txt))
            # v55 (问题1b/1c/1d): 监禁侧改由结构化节点承担 ——
            # ① 诛灭日整簇删去, 代之以**一行族级行** (判据整套继承 v54, 见 is_purge_prisoner);
            # ② 余下的同日同监禁者簇折成一行 (取名规则同 v54 §6.1);
            # ③ 关系流水里已被节点覆盖的「囚禁了X」同日同人条目丢弃 (去掉逐字重复,
            #    且记忆节点的信息更全: 含获取方式与结局); 无据可依者保留原文。
            # v78: 两个方向都出节点 (`raw_entries` 让「我方族人被他族囚禁」也能借
            # 原文流水的 id + 缓存死亡/释放记录成句 —— 久保缓存里大和好风等四人的
            # `imprisoned` 记忆已被引擎回收, 旧稿那几天只有「囚禁了X」没有下文)。
            _nodes = self._house_prison_nodes(other[0], my_houses, self.as_of,
                                              raw_entries=_raw_prison)
            # 族级行 = 诛灭日上「该族有人下狱」∪「该族有人被处决」, 两者判据同源
            _pairs = {(n["date"], n["jailer"]) for n in _nodes if n["purge"]}
            _pairs |= self.house_purge_pairs(other[0], my_houses)
            _purge_days = {d for d, _k in _pairs}
            _node_keys = {(n["date"], n["victim"]) for n in _nodes}
            # v55 (问题1a): 排序权重 = **折叠前**的逐条事件数 —— 折叠会把一整簇并成
            # 一行, 用折叠后的行数排序会让「被诛灭的大族」掉出前五 (934 档 王氏 20 → 5)。
            _weight = len(_hist_events) + len(_node_events) + len(_nodes)
            if _purge_days:
                # 逐 (日期, 行刑者) 出族级行 —— 不可做叉积 (旧稿会把 918.4.8 也记到
                # 尚未即位的马丁名下)
                for _d, _killer in sorted(_pairs, key=lambda x: cl.date_key(x[0])):
                    _line = self.house_purge_line(_killer, other[0], _d, _hlabel)
                    if _line:
                        _node_events.append((_d, _line))
                # 诛灭日的逐人监禁节点与关系流水 (含逐人处决句) 一并抑制 ——
                # 逐人处决已在《本纪》《刺客列传》逐条呈现, 本篇由族级行承担
                _hist_events = [
                    (ed, et) for ed, et in _hist_events
                    if not (str(ed) in _purge_days
                            and any(k in et for k in
                                    _PRISON_KIND_WORDS + ("处决了",)))]
                _nodes = [n for n in _nodes if not n["purge"]]
            # ③ 关系流水里已被节点覆盖的「囚禁了X」同日同人条目丢弃
            #    (逐字重复与信息更全的节点并存没有意义); 无据可依者保留原文。
            #    v78: `_node_keys` 里的 victim 两端都可能是「被囚者」, 而 `_raw_ids`
            #    已收两端 id, 故反向 (他族囚我方) 的原文行同样被节点取代。
            _hist_events = [
                (ed, et) for ed, et in _hist_events
                if not (any(k in et for k in _PRISON_KIND_WORDS)
                        and _raw_ids.get((ed, et))
                        and any((str(ed), _v) in _node_keys
                                for _v in _raw_ids[(ed, et)]))]
            _node_events.extend(self._fold_house_prison_nodes(_nodes))
            events = _hist_events + _node_events
            if not events:
                continue
            events.sort(key=lambda x: cl.date_key(x[0]))
            # v14: 关系档位本地化缺失时用自然词, 不直出 key
            # v78-6: 现档位已回中立、但窗口内有负面流水者 ⇒ 档位词写「旧怨」
            # (旧稿这类族整族不出现; 「两族为旧怨」与「两族为世仇」同式)
            _lvl = L.loc(self.table, lvl) or {
                "default_house_relation_level_feud": "世仇",
                "default_house_relation_level_rivalry": "敌对",
                "default_house_relation_level_quarrel": "争吵",
            }.get(lvl, "")
            if lvl not in NEG:
                _lvl = "旧怨"
            if not _lvl:
                continue
            out.append({
                "house": _hlabel_raw,
                # v29b: 史书式家族称谓 (程氏), 供「家族：程氏，两族为世仇」式行使用
                "house_label": _hlabel,
                "level": _lvl,
                # v55: 内部用 (游戏日期, 渲染句) 对 —— 合并/排序/去重都按游戏日期键,
                # 不用渲染后的「924年3月25日」反解 (那是字符串, date_key 解不了)
                "pairs": [(d, f"{self.date(d)}，{t}") for d, t in events],
                "weight": _weight,
            })
        return self._merge_and_cap_feuds(out)

    # v55 (问题1a, 用户 2026-09-19 拍板): 《家族恩怨录》只显示**五个**家族, 且先合并同名家族。
    # 934 十年档实测 64 条 / 48 个姓氏 —— 同一姓氏下有多个 house id (裴氏×3、邓氏×3、韦氏×3),
    # 不合并则同一姓氏并列成好几段, 模型只能读成一族写一段 (用户: 「家族太泛滥了」)。
    # 排序按**档位降序** (世仇 → 敌对 → 争吵) → 事件数降序 → 首事日期升序 → 姓氏;
    # 用户原话「用档位降序，世仇的事件数必然比更低档位的多」。
    HOUSE_FEUDS_MAX = 5

    def _merge_and_cap_feuds(self, rows):
        """同名家族合并 → 档位/事件数排序 → 取前 HOUSE_FEUDS_MAX 族 (v55 问题1a)。

        输入行的 `pairs` = [(游戏日期, 渲染句)]; 输出行的 `events` = [渲染句] (对外形态)。"""
        rank = {"世仇": 3, "敌对": 2, "争吵": 1}
        merged = {}
        order = []
        for r in rows:
            key = r.get("house_label") or r.get("house") or ""
            if not key:
                continue
            cur = merged.get(key)
            if cur is None:
                merged[key] = {"house": r.get("house") or key,
                               "house_label": r.get("house_label") or key,
                               "level": r.get("level") or "",
                               "pairs": list(r.get("pairs") or []),
                               "weight": int(r.get("weight") or 0)}
                order.append(key)
                continue
            # 档位取最重者; 事件并集按 (日期, 句面) 去重 —— 关系流水里同一人
            # 同日的「囚禁了X」实测有逐字重复条目 (918.4.8 朱思齐 ×2)
            if rank.get(r.get("level") or "", 0) > rank.get(cur["level"], 0):
                cur["level"] = r.get("level") or cur["level"]
            cur["weight"] += int(r.get("weight") or 0)
            cur["pairs"].extend(r.get("pairs") or [])
        out = []
        for key in order:
            r = merged[key]
            seen, pairs = set(), []
            for d, txt in r["pairs"]:
                if (str(d), txt) in seen:
                    continue
                seen.add((str(d), txt))
                pairs.append((d, txt))
            pairs.sort(key=lambda x: cl.date_key(str(x[0])))
            out.append({"house": r["house"], "house_label": r["house_label"],
                        "level": r["level"],
                        "events": [txt for _d, txt in pairs],
                        "_first": cl.date_key(str(pairs[0][0])) if pairs else _DATE_KEY_MAX,
                        "_w": r["weight"], "_n": len(pairs)})
        out.sort(key=lambda x: (-rank.get(x.get("level") or "", 0),
                                -x["_w"], -x["_n"], x["_first"],
                                x.get("house_label") or ""))
        out = out[:self.HOUSE_FEUDS_MAX]
        for r in out:
            r.pop("_first", None)
            r.pop("_w", None)
            r.pop("_n", None)
        return out

    # v13: 宝物志只收高稀珍奇; v21: 门槛改为游戏最高档 名望级 (illustrious) —
    # 存档与游戏定义均无「传奇级 (legendary)」档位, 原 (legendary,) 永远筛空,
    # 玩家偷来的宋御玺/帝国皇冠等 (illustrious) 进不了板块; 狩猎战利品类型
    # (毛皮/角/颅骨) 一律剔除 (即使高稀也是凑数); 最多 20 件防提示词膨胀。
    ARTIFACT_RARITY = ("illustrious",)
    # v61 (问题1, 用户拍板): **部件宝物只收绿色以上**。
    # 游戏档位序 common(白) < masterwork(绿) < famed(蓝) < illustrious(紫) ——
    # `game/common/customizable_localization/ledger_custom_loc.txt:1-30` 的 I–IV 序 +
    # `game/localization/simp_chinese/inventory/inventory_l_simp_chinese.yml:130-137`
    # 的中文名 (大师级/名作级/卓越级); 完整调研见 `docs/调研_宝物稀有度与部件宝物.md`。
    # 旧稿乙档**不限稀有度**, 于是 Mod「食人赋能」按**被吃者头衔档**生成的 common 遗骨
    # 成批入志 (实测: 菲利普2 档 26 件全常见、崔佛档 22 件里 21 常见)。
    # 该 Mod 的映射出处: `workshop\<CK3_appid>\3802979803\common\scripted_effects\
    # devour_effects.txt:553-611` —— 帝国 illustrious / 王国 famed / **公爵 masterwork**
    # / 其余 (伯爵·男爵·无地) common, 故本门槛等价于「只收公爵及以上头衔者的遗骨」。
    ARTIFACT_PART_RARITY = ("masterwork", "famed", "illustrious")
    ARTIFACT_FILLER_TYPES = {
        "animal_hide", "animal_hide_big", "animal_trinket",
        "animal_skull", "VIET_clutter",
    }
    ARTIFACT_MAX = 20
    # v60 (问题2): 部件宝物 (遗骸所制) 的**独立**名额。旧稿甲乙两档共用一个
    # `ARTIFACT_MAX`, 于是一个「批量吃掉」战役里 22 件遗骨会把名望级重宝
    # (帝国皇冠、宋御玺这类) 全挤出去 —— 两档的性质完全不同 (甲档是高稀重宝,
    # 乙档是人物遗骸), 该各自节流。乙档按成物日升序收, 每篇收满为止。
    ARTIFACT_PART_MAX = 30
    # v39: 流转条目 → 「本条之后宝物在谁手里」的角色槽 (逐条语义实测:
    # 诺兰 1093 档 1773 件宝物的 4256 条流转全类型核对)。
    # conquest 的 actor 是失主、recipient 是新主 (128 荆棘冠冕 1086.1.1
    # 海因里希→克里斯托弗); inherited/given/purchased/prize_*/stolen 的新主在
    # recipient; taken_in_battle/taken_in_siege/claimed_by_house/discovered 在 actor;
    # created 的新主在 recipient (旧档无 recipient 时退 actor)。
    # created_before_history 与 reforged 不含归属信息, 不进表 (略过)。
    ARTIFACT_HOLDER_SLOT = {
        "conquest": "recipient",
        "inherited": "recipient",
        "given": "recipient",
        "purchased": "recipient",
        "prize_awarded": "recipient",
        "prize_created": "recipient",
        "stolen": "recipient",
        "taken_in_battle": "actor",
        "taken_in_siege": "actor",
        "claimed_by_house": "actor",
        "discovered": "actor",
        "created": "recipient",
    }

    # v43: 角色部件宝物 —— 以人类遗骸/身体部件制成者。游戏侧: 处决囚犯可得
    # 人类头骨座台宝物 (囚犯为宿敌则必得), 宿敌死亡可得头骨高脚杯
    # (Friends & Foes), 二者都是常见/大师级档 —— 旧的名望级门槛把这类最有
    # 叙事价值的战利品全挡在《宝物志》之外 (诺兰把谋杀的爱沙尼亚国王的头骨
    # 铸成高脚杯, 1111 年即成, 却从未进过任何一篇)。
    ARTIFACT_PART_VISUALS = {"skull_goblet", "human_skull", "devour_bone_visual"}
    ARTIFACT_PART_WORDS = ("头骨", "头颅", "颅骨", "头盖骨", "乳牙",
                           "之骨", "剩的骨头", "被吃掉了")

    # 宝物描述里的数据函数块: \x15ONCLICK:CHARACTER,id \x15TOOLTIP:... \x15L 名字\x15!\x15!\x15!
    _ARTIFACT_REF_RE = re.compile(
        r"\x15ONCLICK:([A-Z_]+),([^\s\x15]+)"
        r"(?:\s*\x15TOOLTIP:[^\s\x15]+)?"
        r"\s*\x15L;?\s*(.*?)\x15!\x15!\x15!", re.S)

    def _artifact_material(self, raw, date=None):
        """宝物描述 → 干净中文「材质」句 (v43)。

        描述里嵌着 `\\x15ONCLICK:CHARACTER,id … \\x15L 名字\\x15!\\x15!\\x15!` 式数据
        函数块 (头骨高脚杯即「用X的头骨制成」)。这里:
          · CHARACTER 块改由本项目 `event_name` 按日期重渲染 —— 写出
            「爱沙尼亚国王特尔·库克」, 而不是游戏烘焙在原文里的短名「特尔」;
          · 其余块 (信仰/文化/家族/地名) 保留游戏已渲染的中文名;
          · 残余格式码就地剥除 —— **不走 `_clean_ck3_loc`**: 它的「称号，名字」
            去逗号规则 (v13) 会把描述里正常的逗号一并吃掉
            (「精致酒杯，用…」→「精致酒杯用…」)。裸键/哨兵串经 `loc_text_ok`
            判不可读即返回 ''。"""
        s = str(raw or "")
        if not s:
            return ""

        # v60 (问题5): Mod 遗骨文案是「[被吃者]被吃掉了，这是[他/她]被吃剩的
        # 骨头。」—— 第二句用人称代词回指, 事实句里读来突兀 (模型会照抄)。
        # 存档里的 `ONCLICK:CHARACTER,<id>` 就是这个「他/她」的所指, 故按 id 取
        # 本项目自己的称谓把代词换掉, 全句改为一句自足的中文。
        _vic = None
        _m0 = re.search(r"ONCLICK:CHARACTER,(\d+)", s)
        if _m0:
            _vic = int(_m0.group(1))
        _ta = "她" if (_vic is not None and self._is_female(_vic)) else "他"

        def _repl(m):
            kind, key, text = m.group(1), m.group(2), (m.group(3) or "").strip()
            if kind == "CHARACTER" and str(key).isdigit():
                nm = self.event_name(int(key), date) or ""
                if nm:
                    return nm
            return text

        s = self._ARTIFACT_REF_RE.sub(_repl, s)
        s = s.replace("\x15", "")
        s = re.sub(r"ONCLICK:[A-Z_]+,[^\s]+", "", s)
        s = re.sub(r"TOOLTIP:[A-Z_]+,[^\s]+", "", s)
        s = re.sub(r"(?<![A-Za-z])L(?=[;\s])", "", s)
        s = re.sub(r"high\s*", "", s)
        s = s.replace("!", "").replace(";", "")
        s = re.sub(r"\s{2,}", " ", s).strip()
        # v63 (问题4): 空格剥离把「·」也当作中文相邻位 —— Mod 遗骨名实测有
        # 「妮克· 阿利尔‑獾」「伊本· 希沙姆」这类「间隔号后多一个空格」的烘焙形态,
        # 旧规则只认汉字-汉字相邻, 于是「· 妮克」的空格原样进了提示词。
        s = re.sub(r"(?<=[\u4e00-\u9fff·]) (?=[\u4e00-\u9fff·])", "", s)
        if _vic is not None:
            vn = self.event_name(_vic, date) or ""
            if vn:
                s = s.replace("被吃掉了", "被吃掉")
                s = s.replace(f"这是{_ta}被吃剩的骨头",
                              f"这是被吃剩的骨头")
                s = s.replace(f"这是{_ta}", "这是")
                s = re.sub(r"这是[他她](?=被)", "这是", s)
        return s.rstrip("。") if loc_text_ok(s) else ""

    def _artifact_text(self, raw, date=None):
        """宝物**名称**或**描述** → 干净中文 (v60 问题2)。

        与 `_artifact_material` 同一套清洗, 但入口统一: 名称此前是一路裸值
        (`a.get("name")`), 而存档里的宝物名同样带数据函数块与烘焙短名 ——
        Mod 遗骨名实测为
        `\\x15high 奥斯塔\\x15!·\\x15high 马格努斯斯多蒂尔\\x15!·\\x15high  赖于马河谷\\x15!之骨`,
        直接下发会把 `\\x15`/`high` 与多余空格写进提示词 (违反「干净事实」口径)。
        名称里的 `\\x15high …\\x15!` 是**修饰片段**而非角色引用, 就地剥除即可。"""
        return self._artifact_material(raw, date)

    def _artifact_name(self, raw, date=None):
        """宝物**名称** → 干净中文 (v63 问题4)。

        与 `_artifact_material` 同一套清洗, 再多一条**只对名称**成立的规则:
        游戏用 `GetUINameNoTooltip` 渲染「称号+名字」时, 中文在称号后带一个全角
        逗号, 于是遗骨名在存档里实测为
        `桂\\x15high 王\\x15!，\\x15high 唐\\x15!\\x15high 文举\\x15!之骨`
        (`3802979803\\localization\\simp_chinese\\devour_l_simp_chinese.yml:5`
        的 `devour_bone_name = "[bone_victim.GetUINameNoTooltip]之骨"`),
        清洗后成「桂王，唐文举之骨」—— 提示词里与「宝物：{名}，{稀有度}」的逗号
        同位语连读, 模型据此把「桂王」当成宝物名 (成稿「此物名唤『桂王』」)。
        故名称把「称号，名字」之间的逗号删去 (与 `_clean_ck3_loc` 的同名规则同源),
        材质句不适用 —— 描述里的逗号是正常行文。"""
        s = self._artifact_material(raw, date)
        if not s:
            return ""
        # 称号 (≤5 汉字) 与紧随其后的汉字之间的逗号 → 删
        # (「桂王，唐文举之骨」→「桂王唐文举之骨」; 「哈兰酋长，阿尔尼之骨」同例)
        return re.sub(r"([\u4e00-\u9fff]{1,5})，(?=[\u4e00-\u9fff])", r"\1", s)

    def _is_part_artifact(self, a, desc=""):
        """是否「以角色部件制成」的宝物: visuals 类型或名字/描述用词任一命中。

        v60 (问题2): 加 `devour_bone_visual` 与「之骨／剩的骨头／被吃掉了」——
        Mod「食人赋能」的遗骨 (`devour_bone_name` = `[…]之骨`,
        `devour_bone_desc` = 「…被吃掉了，这是…被吃剩的骨头。」) 此前整类被挡在
        《宝物志》门外。与 `ARTIFACT_FILLER_TYPES` 的 `animal_skull`(兽类颅骨
        战利品) 不冲突: 动物骨走 filler, 人骨走本档。"""
        vis = ((a.get("visuals") or {}).get("type") or "")
        if vis in self.ARTIFACT_PART_VISUALS:
            return True
        blob = f"{a.get('name') or ''}{desc}"
        return any(w in blob for w in self.ARTIFACT_PART_WORDS)

    def _artifact_ever_own_player(self, hist):
        """流转史里是否**曾**归**主角本人** (v68 问题4; 用户拍板: 只统计主角确实持有的宝物)。

        旧稿按**宗族**判 (`_artifact_ever_own_kin`): 顿巴斯只是菲利普宗族的分支,
        下一位传主伍尔夫克尔·拉玛松 (67155056) 同属该宗族, 于是 141 件遗骨
        (965 档现主全是他) 整批入选; 素材又不写现主, 模型便把 13 副骨头搬进主角的帐
        (实测成稿「王帐东壁的皮囊里…一具一具的人骨」)。判据收紧到 `player_id`:
        崔佛 22 件遗骨 (流转史 actor=38665) 照旧入选, 尼克名下 0 件遗骨。"""
        pid = self.cache.get("player_id")
        if not isinstance(pid, int):
            return False
        for e in hist:
            if not isinstance(e, dict):
                continue
            for key in ("actor", "recipient"):
                if e.get(key) == pid:
                    return True
        return False

    def _artifact_owner_at(self, hist, as_of=None, fallback=None):
        """宝物在 as_of 的持有者 id (v68 问题4): 「现主」行的数据源。

        · as_of 为空 (终传/在世传) → 干脆用存档的 `owner` 字段, 那是**游戏自己写的**
          当前持有者 (最准; 流转史末条未必记到最近一次易手);
        · as_of 非空 (十年传) → 取 ≤as_of 的**最后一条带归属的流转**
          (`ARTIFACT_HOLDER_SLOT` 定槽位, `created` 缺 recipient 时退 actor);
          条目次序不定, 故按日期取最大者, 取不到再回落 `fallback`。"""
        if not as_of and isinstance(fallback, int):
            return fallback
        best_dk, cid = None, None
        ao = cl.date_key(as_of) if as_of else None
        for e in hist:
            if not isinstance(e, dict):
                continue
            t = e.get("type") or ""
            slot = self.ARTIFACT_HOLDER_SLOT.get(t)
            if not slot:
                continue
            d = e.get("date")
            if ao is not None and (not d or cl.date_key(d) > ao):
                continue
            v = e.get(slot)
            if not isinstance(v, int) and t == "created":
                v = e.get("actor")
            if not isinstance(v, int):
                continue
            dk = cl.date_key(d) if d else None
            if best_dk is None or (dk is not None and dk >= best_dk):
                best_dk, cid = dk, v
        if cid is not None:
            return cid
        return fallback if isinstance(fallback, int) else None

    def _capital_title_at(self, date=None):
        """主角在 date 时点的**首都头衔 id** (v81): 逐档 `capital_history` → 末档
        `landed.realm_capital`; 取不到返回 None。

        (与 `_capital_province_at` 同源, 只是保留头衔 id —— 本处要的是**地名**
        显示, 走 `title()` 才与《传主档案》的「治所」逐字一致。)"""
        want = None
        ch = self.cache.get("capital_history") or []
        if ch and date:
            dk = cl.date_key(str(date))
            for pt in ch:
                d = pt.get("date")
                if d and cl.date_key(str(d)) <= dk:
                    want = pt.get("title")
                elif d:
                    break
        if want is None:
            pid = self.cache.get("player_id")
            rec = (self.cache.get("characters") or {}).get(str(pid)) or {}
            want = (rec.get("landed") or {}).get("realm_capital")
        return want if isinstance(want, int) else None

    def artifact_home(self, cid, date=None):
        """宝物所在地 (v81 问题4, 用户 2026-09-29 拍板): 定居统治者 → 其**当时首都**
        的地名 (与《传主档案》的「治所」同一出口); 无地/游牧或取不到 → ''。

        游戏口径「定居统治者的宝物藏于当前首都」, 故这是**存放地**; 流转条目上的
        `location` 是「那次转移发生之地」(持有者行旅时即其行次, 田所档五件宝物
        因此齐齐写成法国布洛涅), 只在取不到首都时由调用方兜底。"""
        if not isinstance(cid, int):
            return ""
        tid = None
        if cid == self.cache.get("player_id"):
            tid = self._capital_title_at(date)
        if tid is None:
            c = self._chars.get(str(cid)) or {}
            ld = c.get("landed_data") or {}
            tid = ld.get("realm_capital")
            if not isinstance(tid, int):
                # 死者: 存档清掉 landed_data 时用卒时辖地之首 (退而求其次)
                dom = (c.get("dead_data") or {}).get("domain") or []
                tid = dom[0] if dom else None
        if not isinstance(tid, int):
            return ""
        nm = self.title(tid, date=date) or ""
        return nm

    def _artifact_dyn_of(self, cid):
        """角色所属宗族 id (熔件 `dynasty_house` → `dynasty`); 查不到返回 None。

        v60 (问题2): 从 `_artifact_candidates` 的内嵌函数提出来 —— 甲档「曾入外族之手」
        判定要用这一份索引 (v68 问题4: 归属判据本身已由宗族收紧到主角本人)。
        (与既有的 `_dynasty_of_cid` 分名: 那一个走缓存并回退 `dynasty_id_of`。)"""
        if not isinstance(cid, int):
            return None
        dh = (self.melt.get("dynasties") or {}).get("dynasty_house") or {}
        c = (self.melt.get("living") or {}).get(str(cid)) \
            or (self.melt.get("dead_unprunable") or {}).get(str(cid)) or {}
        h = c.get("dynasty_house")
        return (dh.get(str(h)) or {}).get("dynasty") if isinstance(h, int) else None

    def _artifact_candidates(self, as_of):
        """《宝物志》选材 (v43) —— 返回 [(aid, kind, a, hist)], 已按 as_of 截断。

        两档 (kind):
          · "relic" 名望级重宝 —— v13/v21 旧口径: 高稀 + 被外族持有过;
          · "part"  角色部件宝物 —— 本宗族持有的遗骸/部件所制之宝, **v61 起只收
            绿色以上** (`ARTIFACT_PART_RARITY`: masterwork/famed/illustrious),
            亦不要求曾入外族之手 (头骨高脚杯是主角自铸的战利品)。
        归属一律按 as_of 判定 (十年传记不穿越; 见 v39 注释)。
        v68 (问题4, 用户拍板「只统计主角确实持有的宝物」): 两档的归属判据都由
        **宗族**收紧到**主角本人** —— 见 `_artifact_ever_own_player` 与 `_held_asof`。"""

        my_dyn = self.cache.get("dynasty_id")
        my_pid = self.cache.get("player_id")

        def _dyn_of(cid):
            """角色所属宗族 id; 查不到返回 None。"""
            return self._artifact_dyn_of(cid)

        def _held_asof(hist, as_of):
            """as_of 之前是否已归**主角本人** (v39; v68 问题4 由宗族收紧到本人)。
            as_of 为空 (终传) 时不做此判定。"""
            if not as_of:
                return True
            ao = cl.date_key(as_of)
            for e in hist:
                d = e.get("date")
                if not d or cl.date_key(d) > ao:
                    continue
                t = e.get("type") or ""
                slot = self.ARTIFACT_HOLDER_SLOT.get(t)
                if not slot:
                    continue
                cid = e.get(slot)
                if not isinstance(cid, int) and t == "created":
                    cid = e.get("actor")
                if isinstance(cid, int) and cid == my_pid:
                    return True
            return False

        art = (self.melt.get("artifacts") or {}).get("artifacts") or {}
        out = []
        for aid, a in art.items():
            if not isinstance(a, dict):
                continue
            if (a.get("type") or "") in self.ARTIFACT_FILLER_TYPES:
                continue
            hist = (a.get("history") or {}).get("entries") or []
            # v39: as_of 归属判定 —— 该时期前未归入本宗族的宝物整件不收
            if not _held_asof(hist, as_of):
                continue
            if not (self._artifact_ever_own_player(hist)
                    or (as_of is None and a.get("owner") == my_pid)):
                continue
            kind = ""
            if a.get("rarity") in self.ARTIFACT_RARITY:
                cross = False
                for e in hist:
                    for key in ("actor", "recipient"):
                        d = _dyn_of(e.get(key))
                        if d is not None and d != my_dyn:
                            cross = True
                            break
                    if cross:
                        break
                if cross:
                    kind = "relic"
            # v61 (问题1): 乙档先过档位门槛 (绿色以上), 再看是否部件宝物 ——
            # 门槛在前, 顺带省掉对 common 遗骨的描述清洗开销。
            if not kind and a.get("rarity") in self.ARTIFACT_PART_RARITY:
                desc = self._artifact_material(a.get("description"), as_of
                                               or self.as_of)
                if self._is_part_artifact(a, desc):
                    kind = "part"
            if kind:
                out.append((aid, kind, a, hist))
        return out

    def _decade_cutoff(self, decade):
        """第 decade 个十年的数据截止日 —— 与 pipeline._decade_cutoff 同式
        (起始年 + decade×10 的年初, 不超过末档), 供跨篇去重回溯复用。"""
        srcs = self.cache.get("sources") or []
        last = self.cache.get("last_date")
        if not srcs:
            return last
        try:
            sy = int(str(srcs[0]).split(".")[0])
            end = f"{sy + decade * 10}.1.1"
        except Exception:
            return last
        if last and cl.date_key(last) < cl.date_key(end):
            return last
        return end

    def _artifacts_written_before(self):
        """本十年之前各十年篇目**已写过**的宝物 id 集 (v43, 纯函数)。

        取「更早的每个十年截止日重跑同一选材规则」的并集 —— 不往缓存里写
        「已用宝物」账本, 重跑 / --force / 并发写都不会漂移。
        终传 (decade 为空) 收全量, 不做此排除 (用户 2026-09-15 拍板:
        十年传记去重, 终传收全量)。"""
        if not self.decade or not self.as_of:
            return set()
        out = set()
        for k in range(1, int(self.decade)):
            cut = self._decade_cutoff(k)
            if not cut:
                continue
            try:
                out |= {c[0] for c in self._artifact_candidates(cut)}
            except Exception:
                continue
        return out

    def family_artifacts(self):
        """《宝物志》数据源 (v43): 甲档名望级重宝 + 乙档角色部件宝物 (v61: 限绿色以上)。
        返回 [多行文本] (名称/稀有度/材质/流转史)。

        v39: 十年传记按 as_of 判归属 (旧逻辑只截断流转条目、归属按最新档判:
        诺兰第一个十年因此带出主角 1086 年才夺得的帝国皇冠/查理曼的御座)。
        v43: 十年传记再排除**前面几个十年已写过**的宝物 —— 诺兰第 2/3/4/5 个十年
        与终传此前是逐字同样的五件, 读多了只剩审美疲劳。"""
        rarity_zh = {"common": "常见", "famed": "著名", "masterwork": "大师级",
                     "illustrious": "名望级", "legendary": "传奇级"}
        written = self._artifacts_written_before()
        rows = []
        for aid, kind, a, hist in self._artifact_candidates(self.as_of):
            if aid in written:
                continue
            # v60 (问题2): 名字同样过清洗 —— 存档宝物名带 `\x15high …\x15!`
            # 数据函数块与烘焙短名 (「奥斯蒂亚\x15high 市长\x15!，…之骨」)。
            # v63 (问题4): 名字另走 `_artifact_name` —— 额外删去「称号，名字」的逗号
            # (「桂王，唐文举之骨」→「桂王唐文举之骨」), 防模型把称号读成宝物名。
            name = self._artifact_name(a.get("name"), self.as_of) or "一件宝物"
            rarity = rarity_zh.get(a.get("rarity")) or a.get("rarity") or ""
            # v29b: 稀有度改逗号同位语 (「宝物：X，名望级」), 不用括注
            lines = [f"宝物：{name}，{rarity}"]
            # v68 (问题4): 「现主 / 现藏」两行 —— 素材此前只有名称/材质/流转三类,
            # 模型读不出「这件现在还在不在主角手上」(成稿把 141 件现属他人宗族的
            # 遗骨写成主角帐中之物)。程序端已能确定性给出, 故不由提示词叮嘱:
            # 现主取 as_of 时点的持有者 (流转史末条归属), 非传主时明标;
            # 现藏见紧下的 v81 口径 (v68 旧稿取流转条目的 location)。            # v81 (问题4, 用户 2026-09-29 拍板): 「现藏」改取**持有者当时的首都** ——
            # 游戏口径是「定居统治者宝物藏于当前首都」, 而旧稿取的是**流转条目上的
            # `location`** (那是「这次转移发生之地」, 常是持有者行旅所在): 田所档
            # 主角 1006 年正从肯特返日途中, 五件宝物的 `location` 全是 2132=布洛涅,
            # 于是「现藏：布洛涅伯爵领」——五件齐刷刷写在法国。现主无地/游牧
            # (宝物随营) 或首都取不到时, 才退回流转条目的 location。
            _own = self._artifact_owner_at(hist, self.as_of, fallback=a.get("owner"))
            _onm = self.name_or(_own, "") if isinstance(_own, int) else ""
            if _onm:
                lines.append(f"现主：{_onm}" if _own == self.cache.get("player_id")
                             else f"现主：{_onm}，非传主")
            _hname = self.artifact_home(_own, self.as_of)
            if not _hname:
                _loc = None
                _ldk = None
                for e in hist:
                    if not isinstance(e, dict) or not isinstance(e.get("location"), int):
                        continue
                    _d = e.get("date")
                    if self.as_of and (not _d or cl.date_key(_d) > cl.date_key(self.as_of)):
                        continue
                    _dk = cl.date_key(_d) if _d else None
                    if _ldk is None or (_dk is not None and _dk >= _ldk):
                        _ldk, _loc = _dk, e.get("location")
                if _loc is not None:
                    _ctid = self.county_at_province(_loc)
                    if _ctid is not None:
                        _hname = self.title(_ctid, self.as_of) or ""
            if _hname:
                lines.append(f"现藏：{_hname}")
            if kind == "part":
                mat = self._artifact_material(a.get("description"), self.as_of)
                if mat:
                    lines.append(f"材质：{mat}")
            _is_bone = self._is_devour_bone(a)
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
                if t == "created" and _is_bone and actor and rec2:
                    # v60 (问题2): 遗骨的成物条目里 actor 是**被吃者本人**
                    # (Mod 的 `creator = $VICTIM$`), 走通用句式会读成
                    # 「斯克迪尔锻造此宝」; 改写为下口者与受害者都在场的一句。
                    entries.append(f"{d}，{rec2}吃掉{actor}，遗骨成此宝")
                elif t == "created" and actor:
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
                    # v81 (问题4, 用户 2026-09-29): 旧稿硬写「克定所得」(成语「攻克
                    # 而定」), 两个字的名形＋「所得」极易被读成一个叫「克定」的人取走
                    # 了它 —— 而本条两端都带名字 (actor=失主, recipient=新主, 见
                    # `ARTIFACT_HOLDER_SLOT`), 直接写成转移句。两端皆无名则整条不发。
                    _win = self.name_or(e.get("recipient"), "") \
                        if isinstance(e.get("recipient"), int) else ""
                    _lose = self.name_or(e.get("actor"), "") \
                        if isinstance(e.get("actor"), int) else ""
                    if _win and _lose:
                        entries.append(f"{d}，{_win}自{_lose}处夺得")
                    elif _win:
                        entries.append(f"{d}，{_win}夺得")
                    elif _lose:
                        entries.append(f"{d}，{_lose}处宝物易主")
                elif t == "created_before_history":
                    # v30: 曾写「年代久远，创制无考」— 属考据按语, 整条略去
                    # (修复方案_菲利普4.md 问题4: 缺料不成句)
                    pass
                # v21: 窃得 (玩家/他人盗取) — actor=失主,  recipient=得宝者
                elif t == "stolen" and actor and rec2:
                    entries.append(f"{d}，{rec2}自{actor}处窃得")
                elif t == "stolen" and actor:
                    entries.append(f"{d}，{actor}处宝物遭窃")
                elif t == "stolen":
                    entries.append(f"{d}，宝物遭窃")
                # v14: 未知流转类型不直出 key (元注释泄露), 略去
            if entries:
                lines.append("流转：" + "；".join(entries))
            # 重宝在前, 部件宝物其次; 档内按流转史丰富度降序
            # (行 = (档位, 排序权重, 宝物id, 宝物对象, 文本行) —— 乙档另按成物日重排)
            rows.append((0 if kind == "relic" else 1, -len(lines), aid, a, lines))
        rows.sort(key=lambda x: (x[0], x[1], x[2]))
        # v60 (问题2): 甲乙两档**各自**限额 —— 见 ARTIFACT_PART_MAX 注释。
        # 部件档内再按成物日升序 (一件件吃下去的顺序), 同日内按流转史丰富度。
        relics = [r for r in rows if r[0] == 0][: self.ARTIFACT_MAX]
        parts = [r for r in rows if r[0] == 1]
        parts.sort(key=lambda r: (self._artifact_created_key(r[3]), r[1], r[2]))
        return ["\n".join(r[4]) for r in relics + parts[: self.ARTIFACT_PART_MAX]]

    def _is_devour_bone(self, a):
        """是否为「吃剩的骨头」遗骨 (v60 问题2)。"""
        return ((a.get("visuals") or {}).get("type") or "") == self._DEVOUR_VISUAL

    def _artifact_created_key(self, a):
        """宝物成物日 → 排序键 (无 created 条目返回最大键, 排到最后)。"""
        for e in ((a.get("history") or {}).get("entries") or []):
            if isinstance(e, dict) and e.get("type") == "created" and e.get("date"):
                return cl.date_key(e["date"])
        return (9999, 0, 0)

    # ---- v8.1: 伊斯兰统治者动态国名 (游戏同规则复现) ----

    _ISLAM_RELIGIONS = {"islam_religion", "sunni_religion",
                        "shia_religion", "ibadi_religion"}
    _NO_RELIGIOUS_HEAD = 4294967295  # 0xFFFFFFFF = 无宗教领袖

    def _faith_id(self, cid, date=None):
        """角色信仰 id: 信仰沿革 (date) → 缓存现值 → 熔件角色对象 → **礼仪反查** → 家族缺省。

        v47: 存档里 `faith` 与 `culture` 同为**可选键** (缺省 = 家族信仰), 死者
        记录里常被剪除。旧实现只读现值, 于是死者的信仰在 flavorization 的
        `faiths`/`religions` 条件里失配、且教义类判定 (人祭等) 一并落空。
        v86: 1.20 角色**不再有 `faith`**, 只有 `rite` —— 信仰由
        `rites.database[rite].faith` 反查 (见 cl.faith_id_of_char)。"""
        if cid is None:
            return None
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fid = _hist_value_at(rec.get("faith_history"), date, "faith")
        if fid is None:
            fid = rec.get("faith")
        if fid is None:
            fid = cl.faith_id_of_char(self.melt, self._chars.get(str(cid)))
        if fid is None:
            fid = cl.faith_id_of_rite(self.melt, self._rite_id(cid, date))
        if fid is None:
            fid = self._house_default(cid, "faith")
        return fid

    def _rite_id(self, cid, date=None):
        """角色所奉**礼仪** id (v86): 礼仪沿革 (date) → 缓存现值 → 熔件角色对象。

        1.20 起角色带 `rite`; 旧档无此字段 → None (调用方回退信仰口径)。"""
        if cid is None:
            return None
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        rid = _hist_value_at(rec.get("rite_history"), date, "rite")
        if rid is None:
            rid = rec.get("rite")
        if rid is None:
            rid = cl.rite_id_of_char(self._chars.get(str(cid)))
        return rid

    def rite_name(self, cid, date=None):
        """传主/某人当时所奉礼仪的中文名 (1.20 存档自带, 如「罗马礼」)。

        旧档 (1.19) 无礼仪库时**回退信仰名** —— 1.20 的「国教」正是由
        State Faith 改称 State Rite, 口径连续。无据返回 ''。"""
        rid = self._rite_id(cid, date)
        if rid is not None:
            nm = cl.rite_name_of(self.melt, rid)
            if nm:
                return nm
        return self._faith_name(self._faith_id(cid, date))

    # =====================================================================
    # v86: 礼仪志 / 教会志 素材 (CK3 1.20 的新宗教系统)
    # =====================================================================
    # 数据源全部已实测确证 (详见 docs/调研_v86_礼仪Rite存档留痕.md 与
    # docs/调研_v86_新宗教系统风味素材.md):
    #   · 礼仪定义    rites.database[<rid>]  (data.name/adjective/desc/fervor/tenets/doctrine)
    #   · 首座        rites.database[<rid>].head_of_rite  (1.20 的宗教领袖, 角色 id)
    #   · 教义状态    data.tenets[].status ∈ core/permitted/prohibited/known/unknown
    #   · 教义名键    `<教义键>_name` (如 tenet_be_fruitful_and_multiply_name)
    #   · 个人教义    characters.<id>.playable_data.tenets  (+ 逐档差分沿革)
    #   · 灵性满足    playable_data.current_spiritual_fulfillment (普通浮点, 不下发数字)
    #   · 圣所与圣髑  religion.holy_sites[<id>] + faiths.database[<fid>].holy_sites/eminent
    #   · 教会情境    situation_manager / situation_sub_region_manager / …participant_group_manager

    _TENET_STATUS_ZH = {"core": "核心", "permitted": "允许", "prohibited": "禁止",
                        "known": "已知", "unknown": "未知"}
    _CHURCH_GROUP_ZH = {
        "christian_clerical_main_power_rulers": "神职主盟",
        "christian_regular_main_power_rulers": "世俗主盟",
        "christian_clerical_secondary_powers_rulers": "神职次盟",
        "christian_regular_secondary_powers_rulers": "世俗次盟",
        "christian_clerical_heretic_rulers": "神职异端",
        "christian_regular_heretic_rulers": "世俗异端",
    }

    def rite_tenets(self, rid):
        """礼仪的教义分档 {status: [教义键…]} (1.20: 教义状态记在**礼仪**上)。"""
        out = {}
        for e in (cl.rite_data(self.melt, rid).get("tenets") or []):
            if not isinstance(e, dict) or not e.get("tenet"):
                continue
            out.setdefault(str(e.get("status") or "known"), []).append(str(e["tenet"]))
        for v in out.values():
            v.sort()
        return out

    def tenet_name(self, key, rid=None):
        """教义键 → 中文名。1.20 的教义名键是 `<教义键>_name`
        (`tenet_be_fruitful_and_multiply_name` = 「你们要生育繁殖」),
        另有按礼/文化的 `_<礼>_name` 变体; 都取不到时回退教义键本身。"""
        if not key:
            return ""
        k = str(key)
        cands = []
        if rid is not None:
            rt = str(cl.rite_entry(self.melt, rid).get("rite_type") or "")
            if rt:
                cands.append(f"{k}_{rt}_name")
        cands.append(f"{k}_name")
        for c in cands:
            v = L.loc(self.table, c)
            if v and v != c:
                return v
        return ""

    def _spiritual_fulfillment(self, cid, date=None):
        """灵性满足现值 (as_of 优先)。无据 → None。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        hist = rec.get("sf_history") or []
        if hist and date:
            ao = cl.date_key(date)
            val = None
            for h in hist:
                if cl.date_key(h.get("from") or "0.0.0") <= ao:
                    val = h.get("value")
            if val is not None:
                return float(val)
        v = rec.get("spiritual_fulfillment")
        return float(v) if isinstance(v, (int, float)) else None

    def _personal_tenets(self, cid, date=None):
        """个人教义键列表 (as_of 优先; 无沿革时取现值)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        hist = [h for h in (rec.get("personal_tenet_history") or []) if h.get("tenet")]
        if hist:
            if date:
                ao = cl.date_key(date)
                return [str(h["tenet"]) for h in hist
                        if cl.date_key(h.get("from") or "0.0.0") <= ao]
            return [str(h["tenet"]) for h in hist]
        return [str(x) for x in (rec.get("personal_tenets") or [])]

    def rite_profile_lines(self, cid, date=None):
        """礼仪档案句 (《礼仪志》开篇): 所奉礼仪 / 礼仪之教 / 源流 / 首座 /
        教义分档与核心 / 礼仪之热 / 灵性满足 / 个人教义。"""
        rid = self._rite_id(cid, date)
        if rid is None:
            return []
        ent = cl.rite_entry(self.melt, rid)
        d = cl.rite_data(self.melt, rid)
        rows = []
        nm = self.rite_name(cid, date)
        if nm:
            rows.append(f"所奉礼仪：{nm}。")
        desc = str(d.get("desc") or "").strip()
        if desc:
            rows.append(f"礼仪之教：{desc}")
        origin = ent.get("origin_rite")
        if isinstance(origin, int) and origin != rid:
            onm = cl.rite_name_of(self.melt, origin)
            if onm:
                rows.append(f"此礼出自{onm}。")
        head = cl.head_of_rite(self.melt, rid)
        if head is not None:
            rows.append("本礼之首：" + ("本人。" if head == cid
                                       else f"{self.event_name(head, date=date)}。"))
        st = self.rite_tenets(rid)
        bits = []
        for k in ("core", "permitted", "known", "prohibited", "unknown"):
            ks = st.get(k) or []
            if ks:
                bits.append(f"{self._TENET_STATUS_ZH.get(k, k)}{len(ks)}条")
        if bits:
            rows.append("礼仪教义：" + "、".join(bits) + "。")
        core = st.get("core") or []
        cnames = [self.tenet_name(k, rid) for k in core]
        cnames = [n for n in cnames if n]
        if cnames:
            rows.append("核心教义：" + "、".join("〈%s〉" % n for n in cnames) + "。")
        fv = d.get("fervor")
        if isinstance(fv, (int, float)):
            rows.append(f"礼仪之热：{_fervor_word(float(fv))}。")
        sf = self._spiritual_fulfillment(cid, date)
        if sf is not None:
            rows.append(f"灵性满足：{_sf_word(sf)}。")
        pt = self._personal_tenets(cid, date)
        if pt:
            names = [self.tenet_name(k, rid) or k for k in pt]
            rows.append("个人教义：" + "、".join("〈%s〉" % n for n in names) + "。")
        return rows

    def rite_history_lines(self, cid, date=None):
        """礼仪沿革句 (《礼仪志》): 逐档差分 ``rite_history`` 得来。

        游戏侧 `converted_rite_memory` (1.20 新增, 带 old_rite/new_rite +
        creation_date) 是更准的来源, 但它只覆盖「记忆尚在」的时点; 缓存差分是
        全期可用的主干, 两者句面同式, 故此处以差分为准 (见调研_v86 报告 §2)。
        as_of 截断; 单点/无沿革返回 []。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        hist = [h for h in (rec.get("rite_history") or [])
                if h.get("from") and h.get("rite") is not None]
        if len(hist) < 2:
            return []
        ao = cl.date_key(date) if date else None
        rows = []
        for i, h in enumerate(hist):
            dk = cl.date_key(h["from"])
            if ao is not None and dk > ao:
                break
            nm = cl.rite_name_of(self.melt, h["rite"])
            if not nm:
                continue
            start = int(str(h["from"]).split(".")[0])
            if i + 1 < len(hist):
                nxt = cl.date_key(hist[i + 1]["from"])
                if ao is not None and nxt > ao:
                    rows.append(f"自{start}年起改奉{nm}")
                else:
                    end = int(str(hist[i + 1]["from"]).split(".")[0]) - 1
                    rows.append(f"{start}年至{end}年奉{nm}")
            else:
                rows.append(f"自{start}年起改奉{nm}" if i else f"自{start}年起奉{nm}")
        return rows

    def personal_tenet_lines(self, cid, date=None):
        """个人教义的**沿革**句: 逐档差分 (游戏无「何时采信」的记忆),
        「自869年起奉〈你们要生育繁殖〉为个人教义」。单点/无沿革返回 []。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        hist = [h for h in (rec.get("personal_tenet_history") or [])
                if h.get("tenet") and h.get("from")]
        if not hist:
            return []
        ao = cl.date_key(date) if date else None
        rows = []
        for h in hist:
            dk = cl.date_key(h["from"])
            if ao is not None and dk > ao:
                break
            rid = self._rite_id(cid, date)
            nm = self.tenet_name(h["tenet"], rid) or ""
            if not nm:
                continue
            rows.append(f"自{int(str(h['from']).split('.')[0])}年起，"
                        f"奉〈{nm}〉为个人教义。")
        return rows if len(rows) >= 1 else []

    def holy_site_lines(self, cid, date=None):
        """圣所与圣髑 (《礼仪志》): 本信仰的圣地/大圣地 + 入龛圣髑件数与珍稀档。"""
        fid = self._faith_id(cid, date)
        if fid is None:
            return []
        fe = cl.faith_entry(self.melt, fid)
        sites = fe.get("holy_sites") or []
        eminent = set(fe.get("eminent_holy_sites") or [])
        db = ((self.melt.get("religion") or {}).get("holy_sites") or {})
        rows = []
        for sid in (sites if isinstance(sites, list) else []):
            e = db.get(str(sid))
            if not isinstance(e, dict):
                continue
            stype = str(e.get("holy_site_type") or "")
            nm = (L.loc(self.table, f"holy_site_{stype}_name")
                  or L.loc(self.table, f"holy_site_{stype}") or "")
            if not nm or nm.startswith("holy_site_"):
                continue
            rank = "大圣地" if sid in eminent else "圣地"
            inv = e.get("inventory") or {}
            eq = inv.get("equipped") or {}
            n = len([k for k in eq if str(k).startswith("holy_relic")])
            rar = e.get("total_artifact_rarity")
            tail = ""
            if n:
                tail = f"，龛中供奉圣髑{n}件"
                if isinstance(rar, (int, float)):
                    tail += f"（珍稀{_rarity_word(float(rar))}）"
            rows.append(f"{rank}{nm}{tail}。")
        return rows

    def _church_situation(self):
        """基督教教会情境的 (id, 情境, 子区) —— 1.20 专有; 无则 (None, {}, {})。"""
        sm = ((self.melt.get("situation_manager") or {}).get("database") or {})
        sr = ((self.melt.get("situation_sub_region_manager") or {}).get("database") or {})
        for sid, sv in (sm.items() if isinstance(sm, dict) else []):
            if isinstance(sv, dict) and sv.get("type") == "the_christian_church":
                try:
                    _sid = int(sid)
                except (TypeError, ValueError):
                    continue
                for _k, sub in (sr.items() if isinstance(sr, dict) else []):
                    if isinstance(sub, dict) and sub.get("situation") == _sid:
                        return _sid, sv, sub
                return _sid, sv, {}
        return None, {}, {}

    def church_state_lines(self):
        """《教会志》素材 (仅终传): 章节 / 领向与进度 / 主流与竞争礼仪 /
        大分裂之势 / 立场分布 / 催化剂流水 (逐条带日期)。取不到返回 []。"""
        sid, sv, sub = self._church_situation()
        if sid is None:
            return []
        rows = []
        ph = (sub or {}).get("phase") or {}
        ch = str(ph.get("type") or "")
        if ch:
            rows.append(f"当今之局：{L.loc(self.table, ch) or ch}。")
        lead = str(ph.get("leading_phase_type") or "")
        if lead:
            ln = L.loc(self.table, lead) or lead
            val = 0
            for fp in (ph.get("future_phases") or []):
                if isinstance(fp, dict) and fp.get("type") == lead:
                    v = fp.get("value")
                    if isinstance(v, (int, float)):
                        val = v
            full = 1250.0            # 章节满值 (common/situation_types)
            word = _progress_word(val / full if full else 0.0)
            rows.append(f"众望所归：{ln}（{word}）。")
        # 大分裂之势: 情境定点变量 ÷ 100000, 阈值 13
        for d in (((sv.get("variables") or {}).get("data")) or []):
            if not isinstance(d, dict):
                continue
            if d.get("flag") == "pam_progress_towards_great_schism":
                ident = ((d.get("data") or {}).get("identity"))
                if isinstance(ident, (int, float)):
                    ratio = (float(ident) / 100000.0) / 13.0
                    rows.append(f"大分裂之势：{_progress_word(ratio)}。")
            elif d.get("flag") == "schism_mainline_rite":
                rid = ((d.get("data") or {}).get("identity"))
                nm = cl.rite_name_of(self.melt, rid) if isinstance(rid, int) else ""
                if nm:
                    rows.append(f"主流之礼：{nm}。")
            elif d.get("flag") == "tcc_main_power_faith":
                # v86: `schism_mainline_rite` 常只有 type 没有 identity (实测 870 档),
                # 此时由「主盟信仰」的 main_rite 反推主流之礼。
                fid = ((d.get("data") or {}).get("identity"))
                if isinstance(fid, int) and not any(
                        r.startswith("主流之礼") for r in rows):
                    mr = cl.faith_entry(self.melt, fid).get("main_rite")
                    nm = cl.rite_name_of(self.melt, mr) if isinstance(mr, int) else ""
                    if nm:
                        rows.append(f"主流之礼：{nm}。")
            elif d.get("flag") == "schism_competitor_rite":
                rid = ((d.get("data") or {}).get("identity"))
                nm = cl.rite_name_of(self.melt, rid) if isinstance(rid, int) else ""
                if nm:
                    rows.append(f"竞争之礼：{nm}。")
        # 立场分布 (六阵营人数)
        pg = ((self.melt.get("situation_participant_group_manager")
               or {}).get("database") or {})
        bits = []
        for _k, g in (pg.items() if isinstance(pg, dict) else []):
            if not isinstance(g, dict) or g.get("situation") != sid:
                continue
            t = str(g.get("type") or "")
            zh = self._CHURCH_GROUP_ZH.get(t) or L.loc(self.table, t)
            n = len(g.get("characters") or [])
            if zh and n:
                bits.append(f"{zh}{n}人")
        if bits:
            rows.append("教廷之众：" + "、".join(bits) + "。")
        # 催化剂流水 (逐条带日期; 取最近 8 条)
        cats = []
        for h in (sv.get("history") or []):
            if not isinstance(h, dict):
                continue
            c = h.get("catalyst") or {}
            key = str(c.get("catalyst") or "")
            date = str(c.get("date") or "")
            if not key or not date:
                continue
            nm = (L.loc(self.table, f"{key}_desc") or L.loc(self.table, key) or "")
            if not nm or nm == key:
                continue
            cats.append((date, nm, c.get("character")))
        cats.sort(key=lambda x: cl.date_key(x[0]))
        for date, nm, who in cats[-8:]:
            rows.append(f"{self.date(date)}，{nm}。")
        return rows

    def faith_doctrines(self, cid):
        """角色信仰的教义键列表 (v30)。

        v86: 信仰定义改走 `cl.faith_entry` (1.20 `faiths.database` → 旧档
        `religion.faiths`); 单条时是字符串, 取不到返回 []。"""
        fid = self._faith_id(cid)
        if fid is None:
            return []
        d = cl.faith_entry(self.melt, fid).get("doctrine")
        if isinstance(d, str):
            return [d]
        return [x for x in (d or []) if isinstance(x, str)]

    def _sacrifice_faith(self, cid):
        """行刑者信仰是否允许人祭 (教义授予 human_sacrifice_active)。"""
        docs = self.faith_doctrines(cid)
        if not docs:
            return False
        return bool(set(docs) & self._sacrifice_doctrines)

    def is_islamic(self, cid):
        """角色是否伊斯兰教统治者: 信仰 → 宗教 → religion_type ∈ 伊斯兰系。

        v86: 信仰定义改走 cl.faith_entry (1.20 在顶层 faiths.database)。"""
        fid = self._faith_id(cid)
        if fid is None:
            return False
        fe = cl.faith_entry(self.melt, fid)
        if not fe:
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
        的当前持有者 == 本人。

        v86: 1.20 的 `faith.religious_head` 已是空值, 领袖改记在
        `rites.database[rite].head_of_rite` ⇒ 加上「本人即本礼之首」且宗教属
        伊斯兰系 的回退判据 (避免把教宗也算成哈里发)。"""
        fid = self._faith_id(cid)
        if fid is None:
            return False
        fe = cl.faith_entry(self.melt, fid)
        rh = fe.get("religious_head")
        if isinstance(rh, int) and rh != self._NO_RELIGIOUS_HEAD:
            t = self._lt.get(str(rh)) or {}
            if isinstance(t, dict) and t.get("holder") == cid:
                return True
        rid = self._rite_id(cid)
        if rid is not None and cl.head_of_rite(self.melt, rid) == cid:
            return self.is_islamic(cid)
        return False

    def _holds_head_seat(self, cid):
        """本人是否持有「教宗座」类头衔 (k_papal_state / d_papacy …)。"""
        for tid in (self._hold_intervals(cid) or {}):
            tkey = (self._lt.get(str(tid)) or {}).get("key") or ""
            if "papal" in tkey or "papacy" in tkey:
                return True
        return False

    def religious_head_word(self, cid):
        """宗教领袖称谓 (v15): 角色为其信仰的宗教领袖 (持有 faith.religious_head
        头衔, 如教宗国/教皇座) 时返回称谓 — 教宗; 否则 ''。
        修复「教宗国国王主教戈德弗鲁瓦」式错位: 教宗本人应称「教宗」,
        而非神权领主的通用官职词「国王主教」(该词只适用非领袖的神权君主)。
        只对持有宗教领袖头衔者生效, 不影响普通神权领主。

        v86: 1.20 的 `faith.religious_head` 空 ⇒ 先走「本人即本礼之首」的
        `rites.head_of_rite` 判据, 再沿用教皇座头衔检查。"""
        fid = self._faith_id(cid)
        if fid is None:
            return ""
        rh = cl.faith_entry(self.melt, fid).get("religious_head")
        if isinstance(rh, int) and rh != self._NO_RELIGIOUS_HEAD:
            t = self._lt.get(str(rh)) or {}
            # 任职区间 (title history, 已按 as_of 截断 — 死者/前教宗亦算);
            # 当前持有者只在无 as_of 缺口时兜底 (十年传记不把后期继任教宗泄漏进早期)
            held_rh = rh in (self._hold_intervals(cid) or {})
            melt_date = (self.melt.get("date") or "")
            no_gap = not (self.as_of and cl.date_key(self.as_of) < cl.date_key(melt_date))
            if not held_rh and not (no_gap and isinstance(t, dict)
                                    and t.get("holder") == cid):
                return ""
            # 只处理教皇座类头衔 (k_papal_state / d_papacy); 其余宗教领袖
            # (哈里发等) 走既有 realm_name 动态国名路径, 不套用「教宗」。
            tkey = t.get("key") or ""
            if "papal" not in tkey and "papacy" not in tkey:
                return ""
        else:
            # v86 (1.20): 领袖记在礼仪上 —— 本人为本礼之首且持有教宗座类头衔
            rid = self._rite_id(cid)
            if rid is None or cl.head_of_rite(self.melt, rid) != cid:
                return ""
            if not self._holds_head_seat(cid):
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
          - 连坐处死 (v53): 同日多族处决 / purged 评价 / 诛灭催化剂命中时固定此项,
            不进随机池。
          - 斩首: 东亚系文化 (asian heritage 支柱近似) 或 与受害者同信仰;
            文化完全未知时默认可用 (通用处决即斩首)。
          - 烧死: 非东亚系文化 (与斩首互斥方向)。
          - 做成神秘的肉: 无地冒险者政体 + 恐惧税天赋 (fear_tax_perk)。
          - 犬决: 雇有猎犬人 (kennelperson_camp_officer)。
          - 食人: cannibal 特质或 secret_cannibal (信仰教义参数无存档, 略)。
          - 献祭: 行刑者信仰的教义授予 human_sacrifice_active (存档
            religion.faiths[fid].doctrine 有教义键列表; 参数名由
            localization.doctrines_granting 从 doctrine_types 的 parameters 生成)。
        返回 (key, 中文短语); killer 缺失或状态不可用回退 ('', '') —
        调用方保持既有「被X处决」。"""
        if killer_id is None:
            return "", ""
        # v60 (问题2/问题1): 食人硬证优先 —— 受害者名下有「…之骨」遗骨, 且该遗骨
        # 成物时收件人就是本行刑者, 即此人被吃掉。死法由存档确定性给出, 不进随机池
        # (崔佛档 25 名死者里 22 人被吃, 旧稿只写对 3 条)。
        if victim_id is not None and self.devoured_by(int(killer_id), int(victim_id)):
            return _style.EXECUTION_DEVOUR_BONE
        # v53 (问题4): 诛灭世族命中的死者, 方式固定「连坐处死」, 不走随机池。
        if victim_id is not None and self.is_family_purge(killer_id, victim_id, date):
            return _style.EXECUTION_PURGE
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
        # 献祭: 信仰教义授予 human_sacrifice_active (v30 修复 — 此前该项从未入池,
        # 因为注释误判「无存档教义表」; 实测 cl.load_melt 的 religion.faiths 带完整
        # doctrine 列表, 玩家信仰 norse_pagan 即含 tenet_gruesome_festivals)
        if self._sacrifice_faith(killer_id):
            avail.append("sacrifice")
        if not avail:
            return "", ""
        avail.sort(key=lambda k: _EXECUTION_ORDER.get(k, 99))
        seed = int(hashlib.md5(
            f"exec::{killer_id}:{victim_id}:{date or ''}".encode("utf-8")
        ).hexdigest()[:12], 16)
        key = random.Random(seed).choice(avail)
        zh = dict(_EXECUTION_OPTIONS).get(key, "")
        return key, zh

    _PURGE_OPINION = ("purged_banishment_opinion", "purged_execution_opinion")
    _PURGE_CATALYST = "catalyst_tyrannical_extinguish_noble_family"
    _PURGE_HOUSE_THRESHOLD = 3
    # v60 (问题1): 互动 `celestial_extinguish_noble_family` 的 `is_shown` 硬门 ——
    # 游戏 `10_tgp_interactions.txt:11172` 要求 `government_has_flag =
    # government_is_celestial`, 而该 flag 在 `00_government_types.txt` 里只出现在
    # `celestial_government` 块内。**只认这一个政体**: 行政制(administrative)、
    # 选贤制(meritocratic)、草原行政(steppe_admin) 都不带此 flag, 它们各自有
    # 自己的灭族互动 (不写 `catalyst_tyrannical_extinguish_noble_family`)。
    # 旧稿四条通道一条都不核对机制前提, 于是部落制的崔佛批量吃掉五名俘虏
    # (Mod「食人赋能」把吃掉写成 death_execution) 就被写成「诛灭三族」。
    _PURGE_GOVS = {"celestial_government"}

    def _dynastic_cycle_history_entries(self):
        """局势史条目 (熔件优先, 缓存变化点兜底)。"""
        sm = (self.melt.get("situation_manager") or {}).get("database") or {}
        for v in sm.values():
            if isinstance(v, dict) and v.get("type") == "dynastic_cycle":
                hist = v.get("history") or []
                if isinstance(hist, list):
                    return hist
        return []

    def _purge_dates(self, killer_id):
        """行刑者诛灭世族的日期集 (v53; v60 加机制门)。

        v60 (问题1) 重写: 旧稿四条通道取「诛灭日」, **没有一条核对机制前提**,
        于是部落制的崔佛把 879.9.1 批量吃掉的五名俘虏 (Mod「食人赋能」把
        `devour_single_character_effect` 写成 `death_execution`) 记成
        「诛灭波埃氏、瓦讷氏、韦尔夫氏」, 又把 869.3.31 中国「崔氏」庄园
        (持有人 10923, 与当日两名死者毫无关系) 的销毁日撞成「诛灭二族」。

        现在两条纪律同时生效:
          · **机制门** —— 该日行刑者政体须为 `celestial_government`
            (与互动 `is_shown` 的 `government_has_flag = government_is_celestial`
            同口径, 见 `_PURGE_GOVS`)。政体不可知时不判 (宁缺勿错, 同 v58 天命闸)。
          · **正证门** —— 除「同名日期」外, 该日还须至少一项机制指纹:
            ① 与该日**受害者同族**的 `_nf_` 世族庄园于该日销毁 (旧稿只做
               「全世界任一庄园销毁日 ∩ 本地处决日」, 与受害者无涉);
            ② 该日新得 `purged_*_opinion` (互动对被驱逐残党留下的唯一痕迹);
            ③ 天命催化剂条目 `catalyst_tyrannical_extinguish_noble_family`
               且 `character == 行刑者` (旧稿 `character` 缺省即放行 —— 全球任意
               天朝灭族日都会塞进任何 killer 的日期集)。
        另: 食人硬证 (该日有 `devour_bone_visual` 宝物成物且 recipient == 行刑者)
        的日期一律排除 —— 吃掉共享 `death_execution` 死因, 但它不是灭族
        (见 `_devour_bones`)。"""
        if killer_id is None:
            return set()
        kid = int(killer_id)
        cached = self._purge_dates_map.get(kid)
        if cached is not None:
            return cached
        # 该日被本行刑者处决者 —— {日期: {house_id: [cid…]}}:
        # 「异族数」与「庄园旧持有人是否属当日受害者之族」共用一份索引
        victims_by_day = {}
        for cid, c in self._chars.items():
            if not isinstance(c, dict):
                continue
            dd = c.get("dead_data") or {}
            if dd.get("reason") != "death_execution":
                continue
            if dd.get("killer") != kid:
                continue
            d = dd.get("date")
            if not d:
                continue
            victims_by_day.setdefault(str(d), {}).setdefault(
                c.get("dynasty_house"), []).append(int(cid))
        if not victims_by_day:
            self._purge_dates_map[kid] = set()
            return set()
        # 日期候选集 (须过机制门)
        cand = {d for d, houses in victims_by_day.items()
                if len([h for h in houses if h is not None])
                >= self._PURGE_HOUSE_THRESHOLD}
        proof = self._purge_opinion_dates(kid)
        cand |= proof
        for e in self._dynastic_cycle_history_entries():
            if not isinstance(e, dict):
                continue
            cat = e.get("catalyst") if isinstance(e.get("catalyst"), dict) else e
            if not isinstance(cat, dict):
                continue
            if cat.get("catalyst") != self._PURGE_CATALYST:
                continue
            # character 必须**就是**本行刑者: 缺 character 的条目归属不明, 丢弃
            if cat.get("character") != kid:
                continue
            if cat.get("date"):
                cand.add(str(cat["date"]))
        dates = {d for d in cand if self._purge_gov_ok(kid, d)}
        if not dates:
            self._purge_dates_map[kid] = dates
            return dates
        devoured = {d for d, _rec, _vid in self._devour_bones().values()}
        # 正证①: 与该日受害者**同族**的世族庄园于该日销毁
        proof = set()
        for tid, t in self._lt.items():
            if not isinstance(t, dict):
                continue
            if not self._is_estate_title(tid):
                continue
            hist = t.get("history") or {}
            if not isinstance(hist, dict):
                continue
            for _hd, v in hist.items():
                for e in (v if isinstance(v, list) else [v]):
                    if not isinstance(e, dict) or e.get("type") != "destroyed":
                        continue
                    d = str(_hd)
                    h = e.get("holder")
                    if not isinstance(h, int):
                        continue
                    if d not in victims_by_day:
                        continue
                    if self._house_of_cid(h) in set(victims_by_day.get(d) or {}):
                        proof.add(d)
        # 正证②: 该日新得 purged_* 好感 (owner/target 任一涉本行刑者)
        proof |= self._purge_opinion_dates(kid)
        self._purge_dates_map[kid] = {
            d for d in dates if d in proof and d not in devoured}
        return self._purge_dates_map[kid]

    def _purge_opinion_dates(self, killer_id):
        """涉本行刑者的 `purged_*` 好感日期集 (v60 问题1 正证②)。

        互动对被驱逐的残党留 `purged_banishment_opinion` / `purged_execution_opinion`
        (自带 `start_date`), 这是「确实发生了一次世族诛灭」的机制指纹之一。"""
        out = set()
        for o in (self.melt.get("opinions") or {}).get("active_opinions") or []:
            if not isinstance(o, dict):
                continue
            if o.get("owner") != killer_id and o.get("target") != killer_id:
                continue
            for v in cl._opinion_values(o):
                if v.get("modifier") in self._PURGE_OPINION and v.get("start_date"):
                    out.add(str(v["start_date"]))
        return out

    def _purge_gov_ok(self, killer_id, date):
        """该日行刑者政体是否具备诛灭世族的机制前提 (v60 问题1)。

        政体**不可知**时返回 True —— 「宁缺勿错」在这里的方向是「不因此改口」:
        早于逐档政体史起点的处决行仍按旧口径参与判定, 由正证门负责收紧;
        只有确知为非天朝制政体时才整日落空 (崔佛 `tribal_government`)。"""
        gov = self._character_government(killer_id, date)
        return (not gov) or gov in self._PURGE_GOVS

    # v60 (问题2/问题1): 食人硬证索引 —— Mod「食人赋能」(`devour_bone_visual` 宝物):
    # 吃掉一个角色会在**同一刻**为该角色造一件「…之骨」遗骨, 成物条目
    # `history.entries` 的 `created` 里 `recipient` 就是下口者。死因本身
    # 只写 `death_execution`(与处决同键), 这件遗骨是存档里唯一能确证「吃掉了」
    # 的物证 —— 旧稿让它闲置: 25 名死者里 22 人被吃, 传记却按伪随机池写成
    # 「斩首／烧死／献祭／溺毙」, 只有恰好抽到 devour 的 3 条写对。
    _DEVOUR_VISUAL = "devour_bone_visual"

    def _devour_bones(self):
        """吃掉硬证 {宝物id: (成物日, 被吃者id)} (v60)。

        只收 `visuals.type == devour_bone_visual` 且 `created` 条目带
        `recipient` 的遗骨; 被吃者 id 取成物条目的 `actor`(即受害者本人,
        描述里的 `ONCLICK:CHARACTER,id` 与之同源), 退回创建者。"""
        memo = getattr(self, "_devour_bones_map", None)
        if memo is not None:
            return memo
        out = {}
        art = (self.melt.get("artifacts") or {}).get("artifacts") or {}
        for aid, a in art.items():
            if not isinstance(a, dict):
                continue
            if ((a.get("visuals") or {}).get("type") or "") != self._DEVOUR_VISUAL:
                continue
            for e in ((a.get("history") or {}).get("entries") or []):
                if not isinstance(e, dict) or e.get("type") != "created":
                    continue
                rec = e.get("recipient")
                if not isinstance(rec, int):
                    continue
                vid = e.get("actor")
                if not isinstance(vid, int):
                    vid = self._artifact_actor_from_name(a.get("description"))
                out[str(aid)] = (str(e.get("date") or ""), rec, vid)
                break
        self._devour_bones_map = out
        return out

    def devoured_by(self, killer_id, victim_id=None):
        """行刑者吃掉的 {被吃者id: 成物日} (v60); 给 victim_id 时返回该人的成物日。

        与 `_devour_bones` 同源 —— 只认「遗骨成物时收件人就是此人」这一条,
        因为 Mod 允许遗骨转赠/继承, 末档 owner 早已易主 (崔佛全部 22 件遗骨
        在 881.1.1 都传给了继位者)。"""
        out = {}
        for _aid, (date, rec, vid) in (self._devour_bones() or {}).items():
            if rec != killer_id:
                continue
            if vid is None:
                continue
            out[int(vid)] = date
        if victim_id is None:
            return out
        return out.get(int(victim_id), "")

    def _artifact_actor_from_name(self, raw):
        """遗骨描述里的 `ONCLICK:CHARACTER,<id>` → 被吃者 id (v60; 查不到返回 None)。"""
        m = self._ARTIFACT_REF_RE.search(str(raw or ""))
        if not m or m.group(1) != "CHARACTER":
            return None
        key = m.group(2)
        return int(key) if str(key).isdigit() else None

    def is_family_purge(self, killer_id, victim_id, date=None):
        """该处决是否属于诛灭世族 (同日旁证命中)。"""
        if killer_id is None or not date:
            return False
        return str(date) in self._purge_dates(killer_id)

    def family_purge_victims(self, killer_id):
        """诛灭世族涉及者 id 集 (v54 问题3): 该日被处决者 + 被驱逐者。

        互动 `celestial_extinguish_noble_family_interaction`（与事件
        `tgp_east_asia_interaction_events.2000`）的实际动作是**先尽囚、后驱逐**：
        对 recipient 的 `every_close_or_extended_family_member` 与 `every_spouse`
        **一律** `imprison = { type = house_arrest }`，随后处死 recipient、其余驱逐
        （存档留 `purged_banishment_opinion`）。所以存档里这一件事同时产出
        36 条处决与 ~94 条囚禁+释放 —— 年表逐人成行会塞满（马丁终传 920.1.24 有 85 行）。"""
        if killer_id is None:
            return set()
        kid = int(killer_id)
        dates = self._purge_dates(kid)
        if not dates:
            return set()
        out = set()
        for cid, c in self._chars.items():
            if not isinstance(c, dict):
                continue
            dd = c.get("dead_data") or {}
            if dd.get("reason") == "death_execution" and dd.get("killer") == kid \
                    and str(dd.get("date") or "") in dates:
                out.add(int(cid))
        for o in (self.melt.get("opinions") or {}).get("active_opinions") or []:
            if not isinstance(o, dict):
                continue
            if o.get("owner") != kid and o.get("target") != kid:
                continue
            for v in cl._opinion_values(o):
                if v.get("modifier") not in self._PURGE_OPINION:
                    continue
                if str(v.get("start_date") or "") not in dates:
                    continue
                for who in (o.get("owner"), o.get("target")):
                    if isinstance(who, int) and who != kid:
                        out.add(int(who))
        return out

    def family_purge_events(self, killer_id):
        """诛灭世族的族级**事实行** [{"date", "text"}] (v54)。

        供两处共用: 年表插入（整件事一行）+《刺客列传》名录前的摘要。
        被驱逐者**不列名** —— 互动里凡有地者一律处决，被流放的必是无地残党，
        逐人开列只是噪声（用户 2026-09-18 拍板：直接写「剩余残党被流放」）。"""
        if killer_id is None:
            return []
        kid = int(killer_id)
        dates = self._purge_dates(kid)
        if not dates:
            return []
        by_day = {}
        for cid, c in self._chars.items():
            if not isinstance(c, dict):
                continue
            dd = c.get("dead_data") or {}
            if dd.get("reason") != "death_execution" or dd.get("killer") != kid:
                continue
            d = str(dd.get("date") or "")
            if d not in dates:
                continue
            hid = c.get("dynasty_house")
            by_day.setdefault(d, []).append((int(cid), hid))
        out = []
        for d in sorted(by_day, key=lambda x: cl.date_key(x)):
            items = by_day[d]
            houses, seen = [], set()
            for _cid, hid in items:
                if hid is None or hid in seen:
                    continue
                seen.add(hid)
                label = self._house_label(hid)
                if label:
                    houses.append(label)
            n = len(seen) or len(items)
            shown = "、".join(houses[:6])
            if n > 6 and shown:
                shown += "等"
            head = f"诛灭{shown} {n} 族" if shown else f"诛灭世族 {n} 族"
            out.append({"date": d,
                        "text": f"{head}，处死家主 {len(items)} 人，剩余残党被流放"})
        return out

    def family_purge_summaries(self, killer_id):
        """族级摘要文本列表 (《刺客列传》名录前用), 见 `family_purge_events`。
        句首带日期 —— 该处不经年表的「句首补日期」组装。"""
        return [f"{self.date(e['date'])}{e['text']}"
                for e in self.family_purge_events(killer_id)]

    _CYCLE_ERA = {
        "situation_dynastic_cycle_phase_stability_expansion":
            ("开疆拓土", "治世"),
        "situation_dynastic_cycle_phase_stability_advancement":
            ("政通人和", "治世"),
        "situation_dynastic_cycle_phase_stability":
            ("国局稳定", "治世"),
        "situation_dynastic_cycle_phase_instability":
            ("局势紧张", "危世"),
        "situation_dynastic_cycle_phase_instability_conquest":
            ("新朝征服", "危世"),
        "situation_dynastic_cycle_phase_chaos":
            ("群雄割据", "乱世"),
    }

    def dynastic_cycle_line(self, date=None):
        """天命局势一行 (v53): 「天命：新朝征服（危世），自919年8月2日」。

        v58 (问题5, 用户拍板「只用政体链」): `dynastic_cycle` 是游戏里
        `is_unique = yes` 的**世界级唯一局势**（`common/situation/situations/
        tgp_dynastic_cycle.txt:7`），作用域是中国 core 子区域
        （同文件 :466-468：`add_dejure_title_to_sub_region = title:h_china` ＋
        `add_character_realm_to_sub_region = title:h_china.holder`）。旧稿无条件
        取用, 于是封建制的托斯卡纳女公爵档案里也写「天命：政通人和，世属治世」。
        现按主角**当时的政体**下闸: 只有天朝链政体（celestial/meritocratic/
        steppe_admin）才下发; 政体不可知时不下发（宁缺勿错, 与 v41 同纪律）。
        参与者名单校验留待后续（用户: 评估性能影响后再加）。"""
        pid = self.cache.get("player_id")
        gov = self._character_government_or_earliest(pid, date) \
            if pid is not None else ""
        if gov not in self._CELESTIAL_CHAIN_GOVS:
            return ""
        hist = self.cache.get("dynastic_cycle_history") or []
        rec = None
        if hist:
            dk = cl.date_key(date) if date else None
            for h in hist:
                if not h.get("date"):
                    continue
                if dk is None or cl.date_key(h["date"]) <= dk:
                    rec = h
                else:
                    break
        if rec is None:
            cur = cl.dynastic_cycle_phase(self.melt)
            if cur:
                rec = {"phase": cur.get("phase"),
                       "start": cur.get("start") or date}
        if not rec:
            return ""
        phase = rec.get("phase") or ""
        pair = self._CYCLE_ERA.get(phase)
        if not pair:
            zh = L.loc(self.table, phase)
            if not zh or zh.startswith(("$", "[")) or re.search(r"[A-Za-z_]", zh):
                return ""
            name, era = zh, ""
        else:
            name, era = pair
        start = rec.get("start") or rec.get("date") or ""
        when = self.date(start) if start else ""
        # v55 (问题2): 去括注 —— 时代类型作并列小句 (旧稿「新朝征服（危世），自919年8月2日」)
        era_clause = f"，世属{era}" if era else ""
        if when:
            return f"天命：{name}{era_clause}，自{when}"
        return f"天命：{name}{era_clause}"

    def assassination_method(self, killer_id, victim_id, date=None, reason_key=None,
                             name_date=None):
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
        # v28b: 凶手/行刑者称谓与全篇一致
        # v42 (问题4): 出口改 `event_name` —— 主角只出名字; 与 _death_sentence 的
        # 「缩为其」替换同源 (两处必须用同一称谓, 否则替换落空)
        # v82 (P2b): `name_date` 给出**事发之日**时按该日取称谓 —— 历代记的历史行
        # (874 年那条) 里凶手不能按本篇末日写成关白 (他 901 年才当关白; 实测 1006 终传
        # 行文「死于关白魔罗之种田所浩二的拙劣治疗」, 模型还替他圆场写「时方微贱」)。
        kname = self.event_name(killer_id, date=name_date or self.as_of) \
            or self.name_or(killer_id, "某人")
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
            elif t in ("released_from_prison_memory",
                       "escaped_from_prison_memory"):
                outs.append(d)  # v32: 越狱亦为出狱, 不再把逃脱者算作仍在囚
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

    def killer_is_public(self, cid):
        """该角色的凶手是否**世人共知** (v75 凶手点名):

        ① 存档旗标 `dead_data.killer_known` —— `set_killer_public` 的落盘
           (全本体只有 3 个调用点, 全在谋杀/暴露链上: 00_murder_effects.txt:433、
           :532, 00_secret_types.txt:410; 另有庄园突袭
           scheme_critical_moments_events.txt:7273-7280);
        ② 死因自带公开性 (`public_knowledge = yes`, 见 `_PUBLIC_DEATH_REASONS`)。

        **不能用 `dead_data.know_of_killer` 判** —— 那是「谁**私下**知道凶手」的
        名单 (`add_knows_of_killer`), 主角自记的 `[38649]` 只表示凶手本人知道。

        数据源取**熔件**而非缓存: 缓存 `death` 是一次性闩存 (cache_lib.py:2773),
        死因日后被 `on_expose` 改写 (00_secret_types.txt:434-467 的
        `set_death_reason`) 也不会更新 —— 实测 12880 熔件为
        `death_murder + killer_known=true`, 而缓存里仍写 `death_mysterious`。"""
        if cid is None:
            return False
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return False
        memo = getattr(self, "_kp_cache", None)
        if memo is None:
            memo = self._kp_cache = {}
        if cid in memo:
            return memo[cid]
        dd = ((self._chars.get(str(cid)) or {}).get("dead_data") or {})
        if dd:
            val = bool(dd.get("killer_known")) \
                or str(dd.get("reason") or "") in _PUBLIC_DEATH_REASONS
        else:                       # 熔件无此人 (早期档被剪除): 退回缓存死因
            rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
            val = str((rec.get("death") or {}).get("reason") or "") \
                in _PUBLIC_DEATH_REASONS
        memo[cid] = val
        return val

    def killer_hidden(self, cid, killer):
        """公开档是否**隐去**该凶手 (v75 凶手点名): 凶手是主角, 且该凶杀未公开。

        只有这一条闸 —— 第三方凶手照旧点名 (本轮不改其口径);
        主角已公开的凶杀 (密谋暴露 / 公开处决 / 已暴露的庄园突袭) 照旧点名
        (用户 2026-09-27 拍板 D1)。"""
        try:
            killer = int(killer)
        except (TypeError, ValueError):
            return False
        pid = self.cache.get("player_id")
        if pid is None or killer != int(pid):
            return False
        return not self.killer_is_public(cid)

    def death_clause(self, cid, date=None, reason=None, killer=None, imprison=False,
                     insider=False, killer_date=None):
        """角色死因句 (含施事者): 处决走处决方式池, 暗杀类走暗杀死法池, 其余通用。
        date/reason/killer 显式传入时以传入为准 (受害者不在缓存时的熔件兜底用)。
        v26: imprison=True 时, 卒时已囚满一年者前置「囚禁N年后」— 处决/狱死
        的囚禁时长得以进入传记 (田所2: 库诺·阿恩施泰因囚禁 4 年 7 个月后处决)。
        v75 (凶手点名): insider=True 取**内情** (点名凶手、用暗杀死法池) —— 只给
        《刺客列传》; 缺省 False = 公开档, 主角未公开的凶杀一律不点名
        (判据见 `Facts.killer_hidden`)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        d = rec.get("death") or {}
        if reason is None:
            reason = d.get("reason")
        if killer is None:
            killer = d.get("killer")
        if date is None:
            date = d.get("date")
        # v75 (凶手点名): 公开档隐去主角的凶手身份 —— 死句退回游戏的公开文案
        # (神秘死亡 / 被谋杀 / 消失无踪), 不带内情手法。insider=True 只给
        # 《刺客列传》(该篇恒以主角为凶手位, 见 biography 侧的 killer_pronoun)。
        _public = False
        if killer is not None and not insider and self.killer_hidden(cid, killer):
            killer = None
            _public = True
        # v35 (问题5): 疫情类死因用游戏算好的当代疫名 (「染丘陵热而亡」),
        # 静态雅化词 (「染斑疹伤寒而亡」) 只在判不出疫情时使用。
        if reason in _DEATH_DISEASE_REASON and killer is None:
            _dyn = _disease_dynamic_name(
                self, cid, _DEATH_DISEASE_REASON[reason], _year_of(date))
            if _dyn:
                return f"染{_dyn}而亡"
        out = ""
        if killer is None:
            out = _death_clause(self.table, reason, None, lambda k: "",
                                public=_public)
        else:
            # v28b: 施事者用统一称谓, 与全篇称谓一致
            # v42 (问题4): 出口改 `event_name` (主角只出名字) —— 刺客列传的
            # killer_pronoun 替换与这里必须同源
            # v81 (问题2): `killer_date` 可显式钉住**事发之日** —— 历代记里
            # 874 年那条死亡句的凶手不能按本篇末日写成「关白魔罗之种田所浩二」
            # (他 901 年才当关白)。
            _kdate = killer_date or self.as_of
            kname = self.event_name(killer, date=_kdate) \
                or self.name_or(killer, "某人")
            if reason == "death_execution":
                _k, zh = self.execution_method(killer, cid, date)
                if zh:
                    out = f"被{kname}{zh}"
            if not out:
                _mkey, mzh = self.assassination_method(killer, cid, date, reason,
                                                       name_date=_kdate)
                if mzh:
                    out = mzh
            if not out:
                out = _death_clause(self.table, reason, killer,
                                    lambda k: self.event_name(k, date=_kdate)
                                    or self.name_or(k, "某人"))
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

    def _cached_opinion_index(self):
        """缓存里的关系缘由 (v50) → 与 `_player_opinion_index` 同形的
        `{(owner, target): {kind: {"reason":…, "involved_character":…}}}`。

        来源 = `cache_lib._latch_relation_reasons` 逐档闩存的
        `cache["relation_reasons"]` (key `"<owner>|<target>|<kind>"`): 游戏只在
        关系存续期写 `scripted_relations.<kind>.reason`, 而关系一方死亡或关系解除
        后条目连缘由一起消失 (v47 §1.3), 生成所用最新熔件因此读不到早年结仇的缘由。
        惰性构建, 只读涉主角的那几条。"""
        if self._cached_opinion_idx is not None:
            return self._cached_opinion_idx
        idx = {}
        for rec in (self.cache.get("relation_reasons") or {}).values():
            if not isinstance(rec, dict):
                continue
            owner, target, kind = rec.get("owner"), rec.get("target"), rec.get("kind")
            reason = rec.get("reason")
            if not isinstance(owner, int) or not isinstance(target, int) \
                    or not kind or not reason:
                continue
            idx.setdefault((owner, target), {})[kind] = {
                "reason": reason,
                "involved_character": rec.get("involved"),
                "province": rec.get("province"),
                "_first_seen": rec.get("first_seen"),
            }
        self._cached_opinion_idx = idx
        return idx

    def _any_opinion_index(self):
        """熔件 `opinions.active_opinions` 的**全对**索引 (v56 §10)。

        与 `_player_opinion_index` 同源, 但**不按主角过滤** —— 第三方对
        (如「郑思齐↔任宗本」) 的 `scripted_relations` 也在其中。只收带
        `scripted_relations` 的条目 (全档约 5.6 万 → 索引更小), 惰性一次扫描。
        用途: `became_lovers` 等关系记忆的缘由句要按**记忆当事人**查, 而不是按主角。"""
        if self._any_opinion_idx is not None:
            return self._any_opinion_idx
        idx = {}
        for o in (self.melt.get("opinions") or {}).get("active_opinions") or []:
            if not isinstance(o, dict):
                continue
            ow, tg = o.get("owner"), o.get("target")
            if not isinstance(ow, int) or not isinstance(tg, int):
                continue
            sr = o.get("scripted_relations")
            if isinstance(sr, dict) and sr:
                idx[(ow, tg)] = sr
        self._any_opinion_idx = idx
        return idx

    def _rel_mem_date(self, cid, mem_types, base=None):
        """a↔cid 间某类关系的最早记忆日期 (≤ as_of), 用于游戏原因的时间门 —
        十年传记不把 as_of 之后才形成的关系泄漏进早期。
        v56 (§10): `base` 指定基准人 (缺省 = 主角) —— 第三方对 (相恋的两人都不是
        主角) 也要能判「关系在 as_of 前是否已存在」。"""
        cache = self.cache
        pid = base if base is not None else self.cache.get("player_id")
        if pid is None or cid is None:
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
        时间门: 仅当该类型关系有 ≤ as_of 的记忆时才渲染 (防十年泄漏)。

        v50 (v47 方案 B): 熔件里查不到该对条目时, 回退读逐档闩存的
        `cache["relation_reasons"]` —— 关系一方死亡或关系解除后, 游戏会把条目
        连同 reason 一起清掉 (v47 §1.3), 而生成只用最新一份熔件, 于是早年结仇的
        缘由本来永久读不到。判据: 同一 kind 上熔件带 reason 时以熔件为准 (最新
        状态), 熔件缺该 kind 或该条目未带 reason 时用闩存补缺。"""
        if cid == self.cache.get("player_id"):
            return []
        idx = self._player_opinion_index()
        cached = self._cached_opinion_index()
        pid = self.cache.get("player_id")
        out = []
        seen = set()
        for pair in ((cid, pid), (pid, cid)):
            # 熔件在前: 它带 reason 的 kind 一律以熔件为准 (键序也保持原样);
            # 熔件缺该 kind 或该条目没带 reason 时, 用闩存的旧缘由补缺
            merged = {}
            for kind, v in (idx.get(pair) or {}).items():
                if kind in kinds and isinstance(v, dict) and v.get("reason"):
                    merged[kind] = v
            for kind, v in (cached.get(pair) or {}).items():
                if kind in kinds and isinstance(v, dict) and kind not in merged:
                    merged[kind] = v
            for kind, v in merged.items():
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
                s = _sub_relation_loc(self, tpl, pair[0], pair[1], extra,
                                      province=v.get("province"))
                s = s.strip("。") + "。" if s else ""
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
        return out

    def relation_reason_for_pair(self, a, b, kinds, styled=False):
        """任意二人对的游戏缘由句 (v56 §10) —— 与 `relation_reasons` 同口径,
        但基准不是主角: 用于**双方都不是主角**的关系对 (如「郑思齐↔任宗本」
        在施沙米尔的地牢里相恋)。

        数据源: 熔件 `opinions` 全对索引 (`_any_opinion_index`) + 逐档闩存的
        `cache["relation_reasons"]` (v56 起收录面已放宽到「双方都在角色表内」)。
        时间门与 `relation_reasons` 同 (关系须在 as_of 前已存在)。返回渲染好的 [句]。
        熔件优先、闩存补缺 (同 `relation_reasons` 的键序与口径)。
        `styled=True` 时三个称谓走 `event_name` (与事实面其余行同口径)。"""
        if not isinstance(a, int) or not isinstance(b, int) or a == b:
            return []
        melt_idx = self._any_opinion_index()
        cached = self._cached_opinion_index()
        out, seen = [], set()
        for pair in ((a, b), (b, a)):
            merged = {}
            for kind, v in (melt_idx.get(pair) or {}).items():
                if kind in kinds and isinstance(v, dict) and v.get("reason"):
                    merged[kind] = v
            for kind, v in (cached.get(pair) or {}).items():
                if kind in kinds and isinstance(v, dict) and kind not in merged:
                    merged[kind] = v
            for kind, v in merged.items():
                reason = v.get("reason")
                if not reason:
                    continue
                mtypes = self._REL_REASON_KINDS.get(kind)
                if mtypes and not self._rel_mem_date(b, mtypes, base=a):
                    continue      # 该关系在 as_of 前不存在 → 不渲染
                tpl = L.relation_templates().get(reason)
                if not tpl:
                    continue
                extra = v.get("involved_character")
                if not isinstance(extra, int):
                    extra = None
                _names = None
                if styled:
                    _names = [
                        self.event_name(pair[0], date=self.as_of) or self.name_or(pair[0]),
                        self.event_name(pair[1], date=self.as_of) or self.name_or(pair[1]),
                        (self.event_name(extra, date=self.as_of) or self.name_or(extra))
                        if isinstance(extra, int) else "",
                    ]
                s = _sub_relation_loc(self, tpl, pair[0], pair[1], extra,
                                      province=v.get("province"), names=_names)
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
        if self._title_government(tid, self.as_of) == "nomad_government":
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
    def _culture_language_id(self, cid, date=None):
        """角色所属文化的语言 id (language_japonic…); 文化缺失时由文化模板回推。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        # v44 (问题4): 文化 id 按 date 取沿革之值 (早年篇的母语与族属须一致)
        cul = self._culture_id_at(cid, date)
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

    def mother_language(self, cid, date=None):
        """母语 (本族语) 中文名: 文化 → language → 本地化; 未知返回 ''。
        CK3 的角色语言表必然含本族语, 其余为习得语言 (Royal Court 语言系统);
        文化完全不可考而角色只通一语时, 该语即其母语。"""
        lg = self._culture_language_id(cid, date)
        if lg:
            v = L.loc(self.table, f"{lg}_name") or L.loc(self.table, lg) or ""
            if v:
                return v
        langs = self.languages(cid)
        if len(langs) == 1:
            return langs[0]
        return ""

    def language_sentence(self, cid, date=None):
        """语言事实句 (v27): 「母语日琉语，兼通乌古尔语。」/
        「通日琉语、乌古尔语。」(母语不可考时); 无语言记录返回 ''。
        v44 (问题4): 母语按 date 取 (早年篇不写后来的族属所对应的母语)。"""
        langs = self.languages(cid)
        if not langs:
            return ""
        ml = self.mother_language(cid, date)
        if ml and ml in langs:
            others = [x for x in langs if x != ml]
            if others:
                return f"母语{ml}，兼通{'、'.join(others)}。"
            return f"母语{ml}。"
        return f"通{'、'.join(langs)}。"

    def language_relation_line(self, a, b):
        """两人言语关系句 (v28/v29): **只说「不通」** — 无共通语时给双方语言清单与
        「须借通译」结论 (用户决策 2026-09-11: 家人之间言语相通属常识, 一律不写)。

        例:「亮通氐羌语，与陆荣廷（泰语、汉语）无共通语，交谈须借通译往来。」
        有共通语时返回 ''; 任一方无语言记录返回 ''。"""
        la = self.languages(a)
        lb = self.languages(b)
        if not la or not lb:
            return ""
        # v28b: 称谓与全篇一致 (person_label, 官职/称号+名)
        na = self.person_label(a, date=self.as_of, style="brief") or self.name_or(a)
        nb = self.person_label(b, date=self.as_of, style="brief") or self.name_or(b)
        if not na or not nb:
            return ""
        if set(la) & set(lb):
            return ""            # v29: 相通即常识, 不下发
        # v31: 语言清单不用括注同位语 (「与X（奥伊通俗拉丁语）无共通语」违 v29b 判据),
        # 改并列分句直陈双方所言
        return (f"{na}通{'、'.join(la)}，{nb}通{'、'.join(lb)}，"
                f"二者无共通语，交谈须借通译或以手势、习语往来。")

    def language_relation_lines(self, cid):
        """主角与妻室/子女的言语关系句 (v28/v29): **只列无共通语者**, 按对方语言
        分组各成一句; 言语相通者一律不写 (用户决策 2026-09-11)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fam = rec.get("family") or {}
        ids = list(dict.fromkeys(
            (fam.get("primary_spouse") or []) + (fam.get("spouse") or [])
            + (fam.get("child") or [])))
        pl = self.languages(cid)
        if not pl:
            return []
        # v28b: 主角与家人称谓与全篇一致 (person_label / kin_label)
        na = self.person_label(cid, date=self.as_of, style="brief") or self.name_or(cid)
        groups = {}   # 对方语言组 -> [id]
        for x in ids:
            try:
                x = int(x)
            except Exception:
                continue
            lx = self.languages(x)
            if not lx:
                continue
            if set(pl) & set(lx):
                continue          # v29: 言语相通者不出句
            groups.setdefault(tuple(lx), []).append(x)
        out = []
        for key, members in groups.items():
            names = "、".join(self.person_label(m, date=self.as_of, style="brief") or self.name_or(m)
                             for m in members)
            if not names:
                continue
            out.append(f"{na}通{'、'.join(pl)}，{names}通{'、'.join(key)}，"
                       f"二者无共通语，交谈须借通译或以手势、习语往来。")
        return out[:4]

    def language_bridge_line(self, cid):
        """主角与妻室/子女的言语异同 (v27): 只列与主角无共通语者 —
        「妻室子女言语：毗伽伊尔盖通共同突厥语。」; 无此情形返回 ''。
        v28: 保留为兼容出口; 提示词改用 language_relation_lines (含同语结论)。
        v31 (附带问题): 旧标签「家中言语」易被读成家世出身 (实测模型据此把妻子
        写成主角之母), 改为「妻室子女言语」点明是姻亲与子嗣的语言。"""
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
        return "妻室子女言语：" + "；".join(bits) + "。"

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

    def _culture_id_at(self, cid, date=None):
        """角色在 date 的文化 id (v44 问题4): 族属沿革点优先, 无沿革取末档现值。

        与 `_character_government` 同口径 —— 十年传记穿越到早年时不得吃末档文化
        (阿德尔海德 1132 年由法兰克尼亚人转汉人, 早年篇须为法兰克尼亚人)。
        v47: 取值体例抽到 `_hist_value_at` (与信仰沿革共用)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        cul = _hist_value_at(rec.get("culture_history"), date, "culture")
        if cul is not None:
            return cul
        return rec.get("culture")

    def culture(self, cid, date=None):
        """角色文化 (v11): 缓存/熔件 culture id → 语言推断 → 本地化 → 'X人'。
        v30: 无据返回 '' — 由调用方整句略去, 不写「族属不详」这类考语。
        v44 (问题4): date 传本篇截止日 → 按族属沿革取该日之值 (早年篇不写末档文化)。"""
        cul = self._culture_id_at(cid, date)
        if cul is not None:
            e = ((self.melt.get("culture_manager") or {}).get("cultures") or {}) \
                .get(str(cul))
            tpl = (e or {}).get("culture_template") if isinstance(e, dict) else None
            if tpl:
                name = L.loc(self.table, tpl) or CULTURE_TEMPLATE_ZH.get(tpl) or ""
                if name:
                    return name if name.endswith("人") else f"{name}人"
        tpl = self.culture_template(cid) or ""
        name = L.loc(self.table, tpl) or CULTURE_TEMPLATE_ZH.get(tpl) or ""
        if name:
            # v11: 族属用「X人」(诺斯人/汉人), 不再用「X族」; 名已以「人」结尾不再追加
            return name if name.endswith("人") else f"{name}人"
        # v30: 无据返回 '' — 由调用方整句略去, 不写「族属不详」这类考语。
        return ""

    def _faith_name(self, fid):
        """信仰 id → 中文名 (未知返回 '')。

        v86: 1.20 的信仰名在存档里**已汉化** (`faiths.database[fid].name`),
        直接取用; 旧档无名字段, 仍走 `faith_type` → 本地化表 / FAITH_TYPE_ZH。"""
        if fid is None:
            return ""
        nm = cl.faith_name_of(self.melt, fid)
        if nm:
            return nm
        ft = (cl.faith_entry(self.melt, fid) or {}).get("faith_type") or ""
        return L.loc(self.table, ft) or FAITH_TYPE_ZH.get(ft) or ""

    def faith(self, cid):
        """角色信仰 (v7 缓存优先): 同 culture, id → religion.faiths → 本地化。
        v30: 无据返回 '' (曾返回「信仰不详」)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        fid = rec.get("faith")
        if fid is None:
            c = self._chars.get(str(cid)) or {}
            fid = c.get("faith")
        return self._faith_name(fid) or ""

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
            # v55 (问题2): 去括注 —— 履历改主谓句 (旧稿「法华宗（880–895年）、
            # 艾什尔里派（自896年起）」), 由调用方以「；」相连
            if i + 1 < len(hist):
                end = int(str(hist[i + 1]["from"]).split(".")[0]) - 1
                rows.append(f"{start}年至{end}年信{nm}")
            else:
                rows.append(f"自{start}年起改信{nm}" if i else f"自{start}年起信{nm}")
        return rows

    def _culture_name_of_id(self, cul):
        """文化 id → 「X人」(不经角色记录; 供族属变迁句用)。"""
        if cul is None:
            return ""
        tpl = cl._template_of_culture(self.melt, cul)
        name = L.loc(self.table, tpl) or CULTURE_TEMPLATE_ZH.get(tpl) or ""
        if name:
            return name if name.endswith("人") else f"{name}人"
        return ""

    def culture_history_lines(self, cid):
        """族属变迁句 (v30, 修复方案_菲利普4.md 问题1)。

        数据源 = 缓存 culture_history (cache_lib 逐档差分; 与 faith_history 同构)。
        单条/无历史返回 []。as_of 截断后 ≥2 点才出句。
        例: ['族属：原为哥特人，871年起为诺斯人。']"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        hist = [h for h in (rec.get("culture_history") or []) if h.get("from")]
        if len(hist) < 2:
            return []
        ao = cl.date_key(self.as_of) if self.as_of else None
        pts = []
        for h in hist:
            if ao is not None and cl.date_key(h["from"]) > ao:
                break
            nm = self._culture_name_of_id(h.get("culture"))
            if nm:
                pts.append((int(str(h["from"]).split(".")[0]), nm))
        if len(pts) < 2:
            return []
        out = [f"原为{pts[0][1]}"]
        for y, nm in pts[1:]:
            out.append(f"{y}年起为{nm}")
        return ["族属：" + "，".join(out) + "。"]

    def traits(self, cid):
        """角色当前特质中文名列表 (未知特质跳过)。
        v11: as_of 截断 — 只取 as_of 前已具且未消失的特质 (十年传记不泄漏后期疾病)。"""
        return [z for _k, z in self.trait_pairs(cid)]

    def trait_xp_map(self, cid):
        """as_of 时点该角色各轨道的 XP: `{特质key: {轨道key: 数值}}` (v32, 问题2)。

        数据源 = 缓存 `rec["trait_xp"]` 样本 (`[{from, traits, xp}]`, 与同档 traits
        顺序对齐); 取 `from ≤ as_of` 的最后一份。旧缓存无样本 → `{}` (渲染层回退
        基础名)。轨道划分查 `data/trait_tracks.json`。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        samples = rec.get("trait_xp") or []
        if not samples:
            return {}
        ao = cl.date_key(self.as_of) if self.as_of else None
        pick = None
        for s in samples:
            if not isinstance(s, dict):
                continue
            if ao is not None and cl.date_key(str(s.get("from"))) > ao:
                break
            pick = s
        if pick is None:
            return {}
        tracks = (L.trait_track_table().get("tracks") or {})
        traits = pick.get("traits") or []
        xp = pick.get("xp") or []
        out, cur = {}, 0
        for t in traits:
            if not isinstance(t, int) or t < 0 or t >= len(self._tl):
                continue
            key = self._tl[t]
            rows = tracks.get(key)
            if not rows:
                continue
            m = {}
            for r in rows:
                if cur < len(xp):
                    m[r["track"]] = xp[cur]
                cur += 1
            if m:
                out[key] = m
        return out

    def _trait_display(self, key, z, xpmap):
        """特质名 + 子轨道括注 (v32, 问题2): 「不法之徒（强盗、窃贼、掠夺者）」。

        只列**已进档**的轨道 (XP ≥ 首个阈值); 一档未进的轨道不写 (否则每个持轨道
        特质的人都拖一串「未入」)。单轨特质不附括注 (轨道名与特质名同源, 写了是重复)。
        v52 (问题6, 用户拍板「直接删」): 不再写「一阶/二阶」等档位序数词 —— 游戏
        没有这套术语 (游戏只有「特质路线/特质经验」概念), 档位由年份跨度与
        按档改名的特质名承担。"""
        if not z:
            return z
        m = (xpmap or {}).get(key) or {}
        rows = (L.trait_track_table().get("tracks") or {}).get(key) or []
        if len(rows) <= 1:
            return z
        bits = []
        for r in rows:
            v = m.get(r["track"])
            if v is None:
                continue
            lv = 0
            for th in (r.get("levels") or []):
                if v >= th:
                    lv += 1
            if lv <= 0:
                continue
            nm = L.loc(self.table, "trait_track_" + str(r["track"])) or ""
            if not nm:
                continue
            bits.append(nm)
        if not bits:
            return z
        return f"{z}（{'、'.join(bits)}）"

    def trait_pairs(self, cid):
        """[(特质 key, 中文名)] — 当前持有特质 (as_of 截断口径同 traits)。
        v31 (问题1): 「为人」分句要按游戏 `category` 归类, 故连 key 一起返回。"""
        if self.as_of:
            return self._trait_pairs_at(cid)
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        ids = rec.get("traits") or []
        xpmap = self.trait_xp_map(cid)
        out = []
        for t in ids:
            if not isinstance(t, int) or t < 0 or t >= len(self._tl):
                continue
            key = self._tl[t]
            z = _trait_name(self.table, key, xp=(xpmap.get(key) or {}))
            if z:
                out.append((key, z))
        return out

    def _trait_pairs_at(self, cid):
        """as_of 时点持有的特质 [(key, 名)]: 依 trait_history 区间 (from ≤ as_of < to)。
        v32: 名称按该时点的轨道 XP 取档名 (旧缓存无 XP 样本时回退基础名)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        th = rec.get("trait_history") or {}
        ao = cl.date_key(self.as_of)
        xpmap = self.trait_xp_map(cid)
        out = []
        seen = set()
        for key in sorted(th):
            for iv in th[key]:
                frm = iv.get("from")
                to = iv.get("to")
                if frm and cl.date_key(frm) > ao:
                    continue
                if to and cl.date_key(to) <= ao:
                    continue
                z = _trait_name(self.table, key, xp=(xpmap.get(key) or {}))
                if z and key not in seen:
                    seen.add(key)
                    out.append((key, z))
        return out

    def _traits_at(self, cid):
        """兼容出口: as_of 时点特质中文名列表 (旧调用点)。"""
        return [z for _k, z in self._trait_pairs_at(cid)]

    def trait_groups(self, cid, public=False):
        """「为人」句的特质分组 (v31, 问题1): [(类别词, [特质名, …], 是否截断), …]。

        类别取游戏 `common/traits` 的 `category` (localization.py 建表), 不靠提示词;
        每组超 `_TRAIT_GROUP_LIMIT` 项取前若干并加「等」— 旧文本把 12 项特质连成
        一顿号串, 模型只能照抄成「报菜名」。顺序见 `_TRAIT_GROUP_ORDER`。
        v32 (问题2): 特质名后按需附子轨道括注 (「不法之徒（强盗一阶）」)。
        v34 (问题1, 用户拍板): `public=True` 时隐去生育能力类特质
        (`_FERTILITY_TRAITS`) — 史官只见子女绕膝, 不见其身体隐微。"""
        cats = (L.trait_names().get("categories") or {})
        xpmap = self.trait_xp_map(cid)
        buckets = {}
        for key, z in self.trait_pairs(cid):
            if public and key in _FERTILITY_TRAITS:
                continue
            buckets.setdefault(cats.get(key, ""), []).append(
                self._trait_display(key, z, xpmap))
        out = []
        for cat in list(_TRAIT_GROUP_ORDER) + sorted(
                set(buckets) - set(_TRAIT_GROUP_ORDER)):
            names = buckets.get(cat) or []
            if not names:
                continue
            word = _TRAIT_GROUP_WORDS.get(cat, "")
            if len(names) > _TRAIT_GROUP_LIMIT:
                out.append((word, names[:_TRAIT_GROUP_LIMIT], True))
            else:
                out.append((word, names, False))
        return out

    def traits_sentence(self, cid, public=False):
        """「为人」句的按类文本 (v31): 「性情野心勃勃、专断；禀赋眉清目秀」;
        无特质返回 ''。类别词为空者直列 (Mod 自造类别)。
        v34: `public=True` 走公开版 (隐去生育能力类特质, 见 `trait_groups`)。"""
        parts = []
        for word, names, truncated in self.trait_groups(cid, public=public):
            body = "、".join(names) + ("等" if truncated else "")
            parts.append(f"{word}{body}" if word else body)
        return "；".join(parts)

    def trait_history_lines(self, cid):
        """特质履历 (v4): 每条 = 「<特质>（自X年起获得 / 自X年后消失…）」
        v11: as_of 截断 — 丢弃 as_of 之后才获得的区间。
        v24: 首见即具的区间 (first=True, 数据起点前已存在, 无获得起点) 不再
        渲染「至晚自X年起已具」— 该类特质仍在「为人」列表出现, 信息不丢。
        v31 (问题1): 体况瞬时特质 (怀孕/患病/受伤) 的得而复失只是状态回摆,
        不进履历 — 生育事实由「添丁进口」记忆承载, 这里只留性情/才具/名声等
        真正构成「履历」的特质。
        日期只保留年 (快照差分日期全是 1月1日, 日内粒度无意义)。
        v35 (问题5): **疾病类特质用游戏算好的当代疫名** —— 伤寒在存档里叫「平原热」
        「丘陵热」「露营热」等 (`epidemics.database[*].name`), 旧稿一律写静态名
        「伤寒」, 于是「第一次在法国得伤寒、第二次在瑞典得伤寒」写成同一句话。
        同型多场疫并存时取「触及本角色属地/所在郡」者, 再取起始最晚者; 判不出
        回归静态名。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        th = rec.get("trait_history") or {}
        ao = cl.date_key(self.as_of) if self.as_of else None
        lines = []
        for key in sorted(th):
            if key in _TRANSIENT_TRAITS:
                continue
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
                # v35: 疾病类特质按当代疫名写 (平原热/丘陵热…), 只在首次出现处换名,
                # 以免同一行里出现两种病名。
                _dyn = ""
                if key in _DISEASE_TRAITS and iv.get("from"):
                    _dyn = _disease_dynamic_name(
                        self, cid, key, _year_of(iv.get("from")))
                if iv.get("from") and not iv.get("to"):
                    spans.append(f"自{d_from}起获得")
                elif iv.get("from") and iv.get("to"):
                    spans.append(f"自{d_from}起获得，自{d_to}后消失")
                elif iv.get("to"):
                    spans.append(f"至{d_to}后消失")
                if _dyn:
                    z = _dyn
            if spans:
                # v55 (问题2): 去括注 —— 「诗人自921年起获得」(旧稿「诗人（自921年起获得）」)
                lines.append(z + "；".join(spans))
        # v32 (问题2) / v52 (问题6): 轨道进档履历 — 「不法之徒·强盗（自872年起）」
        lines.extend(self.trait_level_history(cid))
        return lines

    def _trait_base_name(self, key):
        """特质基础名 (不带档位) — 履历行用, 免与「为人」句的档位名混。"""
        mapped = (L.trait_names().get("traits") or {}).get(key)
        for cand in (mapped, f"trait_{key}", key):
            if not cand:
                continue
            v = L.loc(self.table, cand)
            if v and not v.startswith(("$", "[")):
                return v
        return TRAIT_ZH.get(key, "")

    def trait_level_history(self, cid):
        """轨道进档履历 (v32, 问题2; v52, 问题6): 「<特质>·<轨道>（自X年起，Y年益进）」。

        逐 `rec["trait_xp"]` 样本差分: 某轨道首次跨过下一个阈值即记一条 (as_of 截断)。
        与特质履历同源 (都只到年 — 年度快照日内粒度无意义)。v52 起不再写「进至N阶」
        这类档位序数词 (游戏无此术语)。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        samples = [s for s in (rec.get("trait_xp") or []) if isinstance(s, dict)]
        if not samples:
            return []
        tracks = (L.trait_track_table().get("tracks") or {})
        if not tracks:
            return []
        lv_of = {k: [r.get("levels") or [] for r in rows]
                 for k, rows in tracks.items()}
        ao = cl.date_key(self.as_of) if self.as_of else None
        prev = {}
        out = []
        for s in samples:
            if ao is not None and cl.date_key(str(s.get("from"))) > ao:
                break
            xp = s.get("xp") or []
            cur = 0
            for t in (s.get("traits") or []):
                if not isinstance(t, int) or t < 0 or t >= len(self._tl):
                    continue
                key = self._tl[t]
                rows = tracks.get(key)
                if not rows:
                    continue
                for ri, r in enumerate(rows):
                    if cur >= len(xp):
                        cur += 1
                        continue
                    v = xp[cur]
                    cur += 1
                    lv = 0
                    for th in (lv_of.get(key) or [[]])[ri]:
                        if v >= th:
                            lv += 1
                    if lv > prev.get((key, r["track"]), 0):
                        out.append((key, r["track"], lv, s.get("from")))
                    prev[(key, r["track"])] = lv
        lines = []
        grouped = {}      # (trait, track) -> [(level, from), …] 保序
        for key, tk, lv, frm in out:
            grouped.setdefault((key, tk), []).append((lv, frm))
        for (key, tk), rows in grouped.items():
            base = self._trait_base_name(key)
            tn = L.loc(self.table, "trait_track_" + str(tk)) or ""
            if not base or not tn:
                continue
            steps = []
            for i, (lv, frm) in enumerate(rows):
                yr = self._year_only(frm)
                # v52 (问题6): 只记入轨年份, 不写「进至一阶」这类档位序数词
                steps.append(f"自{yr}起" if i == 0 else f"{yr}益进")
            # 单轨特质的轨道名与特质名同源 (「老练的旅行者·老练的旅行者」) — 不叠
            name = f"{base}·{tn}" if len(tracks.get(key) or []) > 1 else base
            # v55 (问题2): 去括注 —— 「不法之徒·强盗自921年起，924年益进」
            lines.append(name + "，".join(steps))
        return lines

    @staticmethod
    def _year_only(d):
        """快照日期年化: '871.1.1' → '871年'。"""
        if not d:
            return ""
        s = str(d)
        return s.split(".")[0] + "年"

    def government(self, cid, date=None):
        """政体显示名 (v41b: 按 date 取 —— 政体不是恒定的: 主角 1087–1094 封建,
        1095 起行政; 旧实现读缓存末档, 十年传记穿越到早年时把冒险者/封建期
        也写成「行政制」)。
        v30: 无据返回 '' (曾返回「官制不详」)。"""
        g = self._character_government(cid, date or self.as_of)
        if not g and int(self.cache.get("schema") or 1) < 2:
            # 旧缓存 (schema<2) 无逐档政体史: 回退末档, 与 v41 前行为一致
            rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
            g = (rec.get("landed") or {}).get("government") or ""
        return self._government_zh(g)

    def motto(self):
        """玩家家族家训 (v7) → 中文。"""
        mot = self.cache.get("house_motto")
        if not mot:
            return ""
        return render_motto(mot, self.table)

    def _office_name(self, cid):
        """官职名+名: 「交州刺史应偁」 — person_label 的 office 式入口。"""
        return self.person_label(cid, date=self.as_of, style="office")

    def _council_scope(self):
        """议会席位取词用的 (政体, 是否帝国级): 帝国级 = 独立 + 最高头衔 ≥ e_。"""
        pid = self.cache.get("player_id")
        rec = (self.cache.get("characters") or {}).get(str(pid)) or {}
        gov = (rec.get("landed") or {}).get("government") or ""
        return gov, (self._top_rank_now(pid) >= 5
                     and bool(self._is_independent(pid, self.as_of)))

    def _top_rank_now(self, cid, date=None):
        """当前（或 date 时）所持头衔的最高层级 (barony=1…empire=5)。

        v29: 只用 `_primary_title_at` 会在「仅持世族庄园/营地 (x_ 头衔)」时返回 0 —
        游戏里庄园仍属领地层级, 职位/议会变体判定需要层级; 故这里取所有**未失去**
        头衔的最高层级 (x_ 庄园/毡帐记 1, 与游戏 barony 级待遇一致)。"""
        if cid is None:
            return 0
        best = 0
        for tid, ivs in (self._hold_intervals(cid, date) or {}).items():
            if not ivs or ivs[-1][1] is not None:
                continue
            key = (self._lt.get(str(tid)) or {}).get("key") or ""
            rank = self._TT_RANK.get(key[:2], 0)
            if rank == 0 and key.startswith("x_"):
                rank = 1 if self.title_kind(tid) else 0
            best = max(best, rank)
        return best

    def council_line(self):
        """御前会议席位 (v29, 问题10): 用 council_task_manager + council_tasks 解析
        玩家席位的**动态官职名**与大臣 —— 「御前会议六席：长史（某人）、司户（某人）…」
        (天朝制帝国级为 宰相/户部尚书/御史大夫/大将军/礼部尚书; 非帝国为 长史/司户/
        察事/司马/博士; 封建为 掌玺大臣/财政总管…)。

        存档只存任务 id, 故席位名靠 council_tasks.position + 政体变体键取;
        解析不到任何席位时返回 '' — 不再写出「御前会议六席」这种常量串。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return ""
        rec = (self.cache.get("characters") or {}).get(str(pid)) or {}
        seats = (rec.get("landed") or {}).get("council") or []
        if not seats:
            return ""
        gov, imperial = self._council_scope()
        act = (self.melt.get("council_task_manager") or {}).get("active") or {}
        parts = []
        for sid in seats:
            e = act.get(str(sid)) or {}
            if not isinstance(e, dict):
                continue
            owner = e.get("court_owner")
            if isinstance(owner, int) and owner != pid:
                continue          # 别人的议会 (含配偶席) — 不收
            word = L.council_seat_word(self.table, self._council_tasks,
                                       e.get("type") or "", gov, imperial)
            who = e.get("owner")
            nm = self.person_label(who, date=self.as_of, style="brief") if isinstance(who, int) else ""
            # v58 (问题6): 宫廷司祭席带教会称谓 (游戏显示「宫廷司祭佛罗伦萨主教卡利斯托」)
            # v80 (点5): 属世神权信仰 / 异教族下游戏的席位名链整个委托给
            # `actual_bishop_title` (`00_council_positions.txt:703-713`), 此时席位名
            # **就是**教会词 —— 故顶替席位词, 出「日本和尚忠盛」而不是
            # 「宫廷司祭日本和尚忠盛」。
            if (e.get("type") or "") in self._CHAPLAIN_SEAT_TASKS \
                    and isinstance(who, int):
                _ct = self.chaplain_title(who, date=self.as_of)
                if _ct:
                    if self._chaplain_seat_is_bishop_title(e, who):
                        word = ""
                    nm = f"{_ct}{nm}" if nm else _ct
            if word and nm:
                # v29b: 官职与大臣名直连 (「长史延寿」), 不再用「长史（延寿）」
                # 这类括注同位语 — 现代汉语以「职+名」连写为正 (「宰相吴全略」)。
                # v70 (用户 2026-09-27 拍板: 「姐姐姐姐一类的重复一起改掉」):
                # 大臣称谓本身已带同一官职时只写一次 —— brief 称谓形如「御史大夫
                # 欺诈者崔克勤」, 与席位词相连会成「御史大夫御史大夫欺诈者崔克勤」
                # (模型照抄进正文)。
                nm2 = nm[len(word):] if nm.startswith(word) else nm
                parts.append(f"{word}{nm2}")
            elif word:
                parts.append(f"{word}虚悬")
            elif nm:
                parts.append(nm)
        if not parts:
            return ""
        return f"御前会议{_count_zh(len(parts))}席：" + "、".join(parts)

    def council_seat_word(self, task_type):
        """单个议会任务 → 席位官职词 (对外出口, 供回归脚本抽查)。"""
        gov, imperial = self._council_scope()
        return L.council_seat_word(self.table, self._council_tasks, task_type,
                                   gov, imperial)

    def _chaplain_seat_is_bishop_title(self, seat, who=None):
        """该司祭席的**名字**是否由游戏委托给 `actual_bishop_title` (v80 点5)。

        判据 = 解析 `common/council_positions` 的 `name = { first_valid = … }` 臂表,
        首个命中臂的 desc 是否等于 `actual_bishop_title`
        (`00_council_positions.txt:649` 的 name 链 / `:703-713` 的委托臂 ——
        条件为「属世神权信仰 `doctrine_theocracy_temporal` 或异教族 `rf_pagan`」)。"""
        pos = ((self._council_tasks or {}).get("tasks") or {}) \
            .get(seat.get("type") or "") or ""
        if not pos or not self._council_names:
            return False
        liege = seat.get("court_owner")
        if not isinstance(liege, int):
            liege = self.cache.get("player_id")
        if not isinstance(liege, int):
            return False
        scope = self._bishop_scope(liege, who, self.as_of)
        return L.council_name_desc(self._council_names, pos, scope) \
            == "actual_bishop_title"

    # ---- v58 (问题6): 宫廷司祭 (realm priest) 的教会称谓 ----
    #
    # 游戏把司祭的称谓拼成「教会词 + 名」（天主教公国级 = 主教），教会词由
    # `common/customizable_localization/00_divinity_custom_loc.txt:659`
    # `GetActualBishopTitle` 按**宗教组 × 领主的最高头衔层级**取
    # （注释原文 "Religion-By-Religion Titles for Bishops based on Liege's Tier"），
    # 中文在 `localization/simp_chinese/council_l_simp_chinese.yml` 的
    # `councillor_court_chaplain_<宗教组>_{county,duchy,kingdom,empire}`：
    # 天主教 伯爵级=隶属主教 / 公国级=主教 / 王国级=总主教 / 帝国级=牧首。
    # 地名按用户 2026-09-22 给的样本（「托斯卡纳主教里卡尔多」）取**领主首要头衔名**
    # （本档 = 托斯卡纳），与议会席位词拼成「宫廷司祭托斯卡纳主教卡利斯托」。
    _CHAPLAIN_SEAT_TASKS = ("task_religious_relations",)
    _CHAPLAIN_WORD_RE = re.compile(
        r"^councillor_court_chaplain_(?P<rel>.+?)_"
        r"(?P<tier>county|duchy|kingdom|empire)(?P<fem>_female)?$")
    # 宗教组 id/tag → 本地化键里的前缀（游戏两种写法混用，逐个候选试）
    _CHAPLAIN_REL_ALIASES = {
        "christianity_religion": "christian",
        "christianity": "christian",
        "islam_religion": "islam",
        "judaism_religion": "judaism",
        "buddhism": "buddhism_religion",
        "taoism": "taoism_religion",
        "hellenism": "hellenism_religion",
        "paganism_religion": "paganism_religion",
    }

    def _chaplain_words(self):
        """本地化表 → {宗教组前缀: {tier: (中性词, 女性词)}} (惰性建一次)。"""
        idx = getattr(self, "_chaplain_words_index", None)
        if idx is not None:
            return idx
        idx = {}
        for k, v in (self.table or {}).items():
            if not isinstance(v, str) or not v or "$" in v or "[" in v:
                continue
            m = self._CHAPLAIN_WORD_RE.match(k)
            if not m:
                continue
            rel = m.group("rel")
            tier = m.group("tier")
            slot = idx.setdefault(rel, {}).setdefault(tier, ["", ""])
            slot[1 if m.group("fem") else 0] = v
        self._chaplain_words_index = idx
        return idx

    def _chaplain_word(self, rel_id, rel_tag, tier, female=False):
        """宗教组 × 领主层级 → 教会词 (取不到退 `theocrat` 兜底档)。"""
        idx = self._chaplain_words()
        cands = []
        for r in (rel_id, rel_tag):
            s = str(r or "")
            if not s:
                continue
            for c in (s, s.replace("_religion", ""),
                      self._CHAPLAIN_REL_ALIASES.get(s, "")):
                if c and c not in cands:
                    cands.append(c)
        cands.append("theocrat")
        for c in cands:
            slot = (idx.get(c) or {}).get(tier)
            if not slot:
                continue
            w = slot[1] if (female and slot[1]) else slot[0]
            if w:
                return w
        return ""

    def _bishop_scope(self, liege, who=None, date=None):
        """主教称谓臂表 + 议会席位名链的求值域 (v80 点5)。

        对应游戏触发条件用到的槽位: `highest_held_title_tier`(领主层级)、
        `culture = { has_cultural_pillar = … }`(文化支柱)、`government_has_flag`、
        `religion = religion:x` / `faith.religion = faith:y.religion`(宗教键)、
        `religion = { is_in_family = rf_z }`(宗教族)、`has_doctrine`(教义)、
        `NOT = { cp:councillor_court_chaplain ?= { is_female = yes } }`(司祭性别)。"""
        d = date or self.as_of
        scope = {"tier": self._top_rank_now(liege, d),
                 "chaplain_female": (bool(self._is_female(who))
                                     if who is not None else False)}
        rec = (self.cache.get("characters") or {}).get(str(liege)) or {}
        # v80 (点5): `culture = { has_cultural_pillar = X }` 可指 heritage_/language_/
        # ethos_/tradition_ 任何一桩 (游戏 Japanese 臂用的是 `language_japonic`),
        # 故把文化条目的四类桩并成 pillars 集合; heritage 仍单列 (旧调用方的语义)。
        ce = self._culture_entry(liege, d)
        heritage = str(ce.get("heritage") or "")
        pillars = set()
        for _v in (ce.get("heritage"), ce.get("language"), ce.get("ethos")):
            if isinstance(_v, str) and _v:
                pillars.add(_v)
        for _t in (ce.get("traditions") or []):
            if isinstance(_t, str) and _t:
                pillars.add(_t)
        scope["heritage"] = heritage
        scope["pillars"] = pillars
        scope["gov_flag"] = L.government_prefix(
            (rec.get("landed") or {}).get("government") or "")
        maps = self._bishop_titles or {}
        faiths_map = maps.get("faiths") or {}
        rel = self.melt.get("religion") or {}
        fid = self._faith_id(liege, d)
        fe = (rel.get("faiths") or {}).get(str(fid)) or {}
        re_ = (rel.get("religions") or {}).get(str(fe.get("religion"))) or {}
        fkey = str(fe.get("key") or fe.get("tag") or "")
        rkey = str(re_.get("religion_type") or re_.get("tag") or "")
        if fkey and fkey in faiths_map:
            # 信仰键优先折成所在宗教键 (游戏 faith.religion 口径)
            rkey = faiths_map[fkey]
        scope["religion"] = rkey
        scope["religion_family"] = str((maps.get("religions") or {}).get(rkey)
                                       or re_.get("family") or "")
        try:
            scope["doctrines"] = list(self.faith_doctrines(liege) or [])
        except Exception:
            scope["doctrines"] = []
        return scope

    def chaplain_title(self, cid, date=None):
        """宫廷司祭的教会称谓 (v58 问题6) → 「托斯卡纳主教」/「日本和尚」; 无料返回 ''。

        判据: cid 是某领主 (court_owner) 议会「宫廷司祭」席
        (`council_task_manager.active[*].type == task_religious_relations`) 的持有人;
        教会词按该领主 × 该司祭取; 地名取该领主的首要头衔名。
        v80 (点5): 教会词改走游戏**保序臂表** `GetActualBishopTitle`
        (`localization.bishop_titles`) —— 先命中先取, 于是日本佛教档取到
        `councillor_court_chaplain_japanese_buddhism_religion` = 和尚 (旧稿的
        「宗教组 × 层级」索引取不到无层级后缀的键, 落印度系 = 摩诃罗阇上师);
        臂表未命中/缺表时退旧索引 (Mod 与缺数据情形仍出词)。"""
        if cid is None or not self.melt:
            return ""
        act = (self.melt.get("council_task_manager") or {}).get("active") or {}
        liege = None
        for e in act.values():
            if not isinstance(e, dict):
                continue
            if (e.get("type") or "") not in self._CHAPLAIN_SEAT_TASKS:
                continue
            if e.get("owner") == cid:
                liege = e.get("court_owner")
                break
        if not isinstance(liege, int):
            return ""
        d = date or self.as_of
        _tier, tid = self._primary_title_at(liege, d)
        tier = _tier or self._RANK_TIER.get(5)
        place = ""
        if tid is not None:
            place = self._name_at_date(tid, d) or self.title_base_name(tid)
        if not place:
            return ""
        word = ""
        # ① 游戏保序臂表 (先命中先取)
        _k = L.pick_bishop_title(self._bishop_titles,
                                 self._bishop_scope(liege, cid, d))
        if _k:
            v = L.loc(self.table, _k)
            if v and not v.startswith("$") and not v.startswith("["):
                word = v
        # ② 旧兜底: 宗教组 × 层级 索引
        if not word:
            fid = self._faith_id(liege, d)
            rel = self.melt.get("religion") or {}
            fe = (rel.get("faiths") or {}).get(str(fid)) or {}
            re_ = (rel.get("religions") or {}).get(str(fe.get("religion"))) or {}
            rel_id = re_.get("religion_type") or re_.get("tag") or ""
            rel_tag = re_.get("tag") or ""
            word = self._chaplain_word(rel_id, rel_tag, tier,
                                       female=self._is_female(cid))
        if not word:
            return ""
        return f"{place}{word}"

    def court_position_scope(self, cid=None):
        """职位变体求值域 (v29): 雇主政体/独立/顶层层级/文化传承。

        游戏 court_position_asset 的触发条件就这几项 (实测 39 个带 localization_key
        的变体块只用 government_has_flag / is_independent_ruler /
        highest_held_title_tier / has_cultural_pillar)。"""
        pid = self.cache.get("player_id") if cid is None else cid
        rec = (self.cache.get("characters") or {}).get(str(pid)) or {}
        gov = (rec.get("landed") or {}).get("government") or ""
        rank = self._top_rank_now(pid)
        cul = rec.get("culture")
        if cul is None:
            cul = (self._chars.get(str(pid)) or {}).get("culture")
        heritage = ""
        if cul is not None:
            e = ((self.melt.get("culture_manager") or {}).get("cultures") or {}) \
                .get(str(cul))
            if isinstance(e, dict):
                heritage = str(e.get("heritage") or "")
        return {"gov_flag": L.government_prefix(gov), "tier": rank,
                "independent": bool(self._is_independent(pid, self.as_of)),
                "heritage": heritage, "culture": heritage or None}

    def court_position_word(self, type_key, cid=None):
        """职位类型键 → 游戏显示名 (v29, 问题11)。

        存档存的是类型键 (court_physician_court_position), 游戏按雇主政体/独立/
        层级/文化传承择 localization_key 变体 (天朝制非帝国 = 医学博士)。取不到
        变体名时回退类型键的默认本地化 (旧行为)。"""
        if not type_key:
            return ""
        word = L.pick_court_position(self.table, self._cp_variants, type_key,
                                     self.court_position_scope(cid))
        if word:
            return word
        v = L.loc(self.table, type_key) or ""
        return "" if (not v or v == type_key) else v

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
        holder_roles = {}  # 任职者名 -> [(职位词, 授任日期)]; 保持花名册出现序
        order = []
        for p in latest:
            # v29: 职位显示名按游戏变体解析 (私人医生 → 医学博士)
            zh = self.court_position_word(p.get("type")) or ""
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
            roles.append((zh, hire))
        latest_lines = []
        for nm in order:
            roles = holder_roles[nm]
            # v23: 主语=任职者; 同人多职用「又任」递进, 避免「职位：人名」式
            # 履历错觉 (那会诱导模型把岗位归给主角本人)。
            # v55 (问题2): 授任日期去括注, 改为「自X起任…」的句内状语
            # (旧稿「郭季良任虞人（自929年12月24日任），又任太师（自926年8月14日任）」)。
            zh0, hire0 = roles[0]
            s = f"{nm}自{hire0}起任{zh0}" if hire0 else f"{nm}任{zh0}"
            for zh, hire in roles[1:]:
                s += f"，{hire}起又任{zh}" if hire else f"，又任{zh}"
            latest_lines.append(s)
        # 任免变化: 相邻快照 (type, employee) 集合差集 → 上任/卸任
        change_lines = []
        prev = set()
        for h in hist:
            cur = {(p.get("type"), p.get("employee"))
                   for p in h.get("positions") or [] if p.get("type")}
            if prev and cur != prev:
                for t, emp in sorted(prev - cur):
                    zh = self.court_position_word(t) or ""
                    if not zh or zh == t:
                        continue
                    nm = self._office_name(emp) if emp is not None else "空缺"
                    if nm:
                        change_lines.append(f"{self.date(h.get('date'))}：{nm}卸任{zh}")
                for t, emp in sorted(cur - prev):
                    zh = self.court_position_word(t) or ""
                    if not zh or zh == t:
                        continue
                    nm = self._office_name(emp) if emp is not None else "空缺"
                    if nm:
                        change_lines.append(f"{self.date(h.get('date'))}：{nm}出任{zh}")
            prev = cur
        return latest_lines, change_lines

    def court_office_lines(self):
        """主角**获授**的朝廷职位 (v36, 问题2/用户拍板3): 主角为任职者
        (employee=主角, employer=他人 — 太师/某部尚书这类朝廷命官)。

        与 court_positions_lines 方向相反 (那是「我廷中的僚属」); 逐档记录 → 按任期聚合:
        最新行形如「任唐皇帝李漼之太师（两度受任：869年6月28日、881年2月25日；至晚自885年起已卸任）」,
        变化行形如「881年：受唐皇帝李漼之任命为太师」/「885年：卸任太师」。
        失去时点按快照差分推断 (至晚口径, 与 trait_history 同源)。"""
        pid = self.cache.get("player_id")
        if pid is None:
            return [], []
        hist = self.cache.get("court_office_history") or []
        if not hist:
            return [], []
        if self.as_of:
            hist = [h for h in hist
                    if cl.date_key(h.get("date")) <= cl.date_key(self.as_of)]
        if not hist:
            return [], []
        W = _style.FACT_WORDING
        # 逐档 offices 集 → 任期段 [(hire, loss_snapshot_or_None, office)]
        stints = []          # [(hire_date, loss_date|None, office_dict)]
        open_run = {}        # (type, employer) -> office_dict
        for h in hist:
            cur = {(e.get("type"), e.get("employer")): e
                   for e in (h.get("offices") or [])}
            for key, office in cur.items():
                if key not in open_run:
                    open_run[key] = dict(office, _start=office.get("hire_date")
                                         or h.get("date"))
            for key in list(open_run):
                if key not in cur:
                    o = open_run.pop(key)
                    stints.append((o.pop("_start"), h.get("date"), o))
        for key, o in open_run.items():
            stints.append((o.pop("_start"), None, o))
        if not stints:
            return [], []
        stints.sort(key=lambda x: cl.date_key(x[0]))
        # 最新行: 同一 (职位, 雇主) 的多段任期并作一行 (两度受任)
        latest_lines, change_lines = [], []
        by_office = {}
        order = []
        for hire, loss, o in stints:
            word = self.court_position_word(o.get("type"), cid=o.get("employer")) or ""
            if not word or word == o.get("type"):
                continue
            emp = o.get("employer")
            elab = self.person_label(emp, date=hire, style="brief") \
                if isinstance(emp, int) else ""
            key = (word, elab)
            item = by_office.setdefault(key, {"hires": [], "last_loss": None})
            if item is None:
                continue
            if key not in order:
                order.append(key)
            if hire:
                item["hires"].append(self.date(hire))
            if loss:
                item["last_loss"] = self._year_only(loss)
            if hire:
                change_lines.append(W["office_change_gain"].format(
                    date=self.date(hire), employer=elab or "朝廷",
                    gverb=self.grant_verb(emp), word=word))
            if loss:
                change_lines.append(W["office_change_lose"].format(
                    date=self.date(loss), word=word))
        for key in order:
            word, elab = key
            item = by_office[key]
            hires = item["hires"]
            if not hires:
                continue
            held = W["office_held"].format(employer=elab or "朝廷", word=word)
            if len(hires) == 1:
                # v55 (问题2): 去括注 —— 「自869年6月28日起任唐皇帝李漼之太师」
                held = W["office_held_since"].format(
                    date=hires[0], employer=elab or "朝廷", word=word)
            else:
                held = W["office_held_multi"].format(
                    n=_count_zh(len(hires)), employer=elab or "朝廷", word=word,
                    dates="、".join(hires))
            if item["last_loss"]:
                held += W["office_lost_late"].format(year=item["last_loss"])
            latest_lines.append(held)
        # 变化行按日期去重排序
        seen = set()
        out_changes = []
        for ln in sorted(change_lines):
            if ln in seen:
                continue
            seen.add(ln)
            out_changes.append(ln)
        return latest_lines, out_changes

    def estate_place_name(self, cid=None):
        """世族庄园驻地州府名 (v36, 问题4): 缓存 landed.domicile_province → 州府名
        (10282 → 宾州); 缺失时退庄园头衔 capital 所在州府。取不到返回 ''。
        与「治所」(官职驻地, realm_capital) 是两处地方 — 家业在祖籍州府。"""
        pid = self.cache.get("player_id") if cid is None else cid
        rec = (self.cache.get("characters") or {}).get(str(pid)) or {}
        ld = rec.get("landed") or {}
        prov = ld.get("domicile_province")
        if not isinstance(prov, int):
            for t in (ld.get("domain") or []):
                if self._is_estate_title(t):
                    cap = (self._lt.get(str(t)) or {}).get("capital")
                    if isinstance(cap, int):
                        prov = cap
                    break
        if not isinstance(prov, int):
            return ""
        tid = self.county_at_province(prov)
        if tid is None and \
                ((self._lt.get(str(prov)) or {}).get("key") or "").startswith("c_"):
            tid = prov
        if tid is None:
            return ""
        nm = self._name_at_date(tid, self.as_of) or self.title_base_name(tid)
        return nm if nm and not nm.startswith(("c_", "b_")) else ""

    def grant_verb(self, granter_cid, date=None):
        """头衔/职位授予动词 (v36, 用户拍板4): 按**授予方政体**取词
        (天朝/行政=任命, 封建=册封, 部落/宗族=授予…); 取不到用「任命」。
        v41: date 锚点 — 授予方政体按该日期取。"""
        if not isinstance(granter_cid, int):
            return _style.TITLE_GRANT_VERB_FALLBACK
        gov = self._character_government(granter_cid, date)
        if not gov:
            rec = (self.cache.get("characters") or {}).get(str(granter_cid)) or {}
            gov = (rec.get("landed") or {}).get("government") or ""
        if not gov:
            gov = ((self._chars.get(str(granter_cid)) or {}).get("landed_data") or {}) \
                .get("government") or ""
        if not gov:
            # 授予方已死/无地: 退其最高头衔的政体 (皇帝 → 天朝制)
            ftid = self._former_high_title(granter_cid, date) \
                or self._primary_title_at(granter_cid, as_of=date)[1]
            if ftid is not None:
                gov = self._title_government(ftid, date)
        key = L.government_prefix(gov) if gov else ""
        return _style.TITLE_GRANT_VERBS.get(
            key, _style.TITLE_GRANT_VERB_FALLBACK)

    def grant_actor(self, cid, tid, date=None):
        """头衔/职位的**授予者** (v36, 用户拍板4): 该头衔 de_facto_liege 在 date 的
        持有人; 持有人即本人或无人时沿上位链上溯。取不到返回 None。"""
        liege = (self._lt.get(str(tid)) or {}).get("de_facto_liege")
        seen = set()
        while liege is not None and str(liege) not in seen:
            seen.add(str(liege))
            holder = self.holder_at(int(liege), date)
            if isinstance(holder, int) and holder != int(cid):
                if self.name_or(holder, ""):
                    return holder
                return None
            liege = (self._lt.get(str(liege)) or {}).get("de_facto_liege")
        return None

    def revoke_actor(self, cid, tid, date=None, reason=""):
        """头衔的**褫夺者/篡夺者** (v36, 用户拍板4): usurped 取夺位的新持有人;
        revoked 取当时的领主 (de_facto_liege 持有人)。取不到返回 ''。
        v42 (问题4): 出口改走 `event_name` —— 主角只出名字 (返回值是**称谓串**,
        调用方直接嵌句, 勿再当 id 用)。"""
        if tid is None:
            return ""
        if reason == "usurped":
            new_holder = self._next_holder(tid, date, exclude=cid)
            if isinstance(new_holder, int) and new_holder != int(cid):
                return self.event_name(new_holder, date=date)
            return ""
        actor = self.grant_actor(cid, tid, date)
        return self.event_name(actor, date=date) if actor else ""

    def _next_holder(self, tid, date=None, exclude=None):
        """头衔在 date 之后的首位持有人 (title history 序列) — 篡夺者判定用。"""
        seq = self._title_seqs.get(int(tid)) or []
        dk = cl.date_key(date) if date else None
        for d, ev in seq:
            if dk is not None and cl.date_key(d) <= dk:
                continue
            entries = ev if isinstance(ev, list) else [ev]
            for e in entries:
                h = e.get("holder") if isinstance(e, dict) else e
                if isinstance(h, int) and h != exclude:
                    return h
        return None

    def title_office_text(self, cid, tid, date=None):
        """头衔的「地名+官职词」式官称 (衢州刺史/慈州刺史) — 头衔得失句用 (v36)。
        男爵领/营地名/无词者返回 '' (调用方回退头衔显示名)。"""
        if tid is None:
            return ""
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        rank = self._TT_RANK.get(key[:2], 0)
        if rank < 2:            # v36 用户拍板5: 男爵领 (1) 与营地名 (0) 不出官称
            return ""
        tier = self._RANK_TIER.get(rank)
        base = self._name_at_date(tid, date or self.as_of) or self.title_base_name(tid)
        if not base or not tier:
            return ""
        _indep = self._is_independent(cid, date)
        word = self._office_word(tier, self._gov_for_word(cid, tid, date),
                                 independent=bool(_indep) if _indep is not None else True,
                                 female=self._is_female(cid), tid=tid, cid=cid,
                                 date=date)
        return f"{base}{word}" if word else base

    # ---- v5: 文化名序 / 文风 ----

    def name_order(self, cid):
        """角色文化名序约定 ('' = 西方; DYNASTY_ALWAYS_FIRST/JAPANESE = 姓在前)。

        v71: 与 `cl.display_name` **同一条判定链** (`cl.resolved_name_order`:
        本人文化 → 父系侧亲属 → 宗族模板 → 母系/配偶)。旧口径只看缓存 `culture`
        字段, 字段缺失 (实测李氏 82 人中 81 人无该字段) 即静默按西方,
        与成稿侧口径相反。"""
        return cl.resolved_name_order(self.cache, cid, melt=self.melt,
                                      chars=self._chars, memo=self._tpl_memo,
                                      date=self.as_of) or ""

    def is_eastern_culture(self, cid):
        """东方文化 (姓在前)? 文化未知按 False (保守回退西方/未知)。"""
        return self.name_order(cid) in cl.EASTERN_NAME_ORDERS

    def is_custom_start(self, cid):
        """是否「出身自定、无谱系」的角色 (v52 扩展)。

        命中 = 在 `ruler_designer_characters` 里 (玩家自建角色), **或** 存档里既无
        父/母记录、又带脚本化开局 flag (无地冒险者等)。命中者本纪开篇按
        `style.PROMPTS["custom_start_note"]` 写「起于何时何地、如何发迹」。"""
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

    def station_place(self, cid, date=None):
        """角色在某日期所在之地的头衔名 (v52, 问题5: 结仇句的「在XX」)。

        只对**本档玩家**有据 (`cache["player_locations"]` 是逐档并入的驻地轨迹,
        他角色存档不存地点史): 取不晚于 date 的最近一点 → 省份→伯爵领→头衔名。
        无轨迹/无映射返回 '' (调用方省去「在XX，」)。"""
        pid = self.cache.get("player_id")
        if pid is None or cid is None or int(cid) != int(pid):
            return ""
        lim = cl.date_key(str(date)) if date else None
        best = None
        for loc in (self.cache.get("player_locations") or []):
            d = loc.get("date")
            if not d:
                continue
            if lim is not None and cl.date_key(str(d)) > lim:
                continue
            if best is None or cl.date_key(str(d)) >= cl.date_key(str(best.get("date") or "")):
                best = loc
        if best is None:
            return ""
        county = self.county_at_province(best.get("province"))
        if county is None:
            return ""
        return self.title(county) or ""

    def _capital_province_at(self, date=None):
        """v57 (问题3): 主角在 date 时点的首都省份 id (取不到返回 None)。

        首都**会搬** (斯卡利茨实测 924–945 在 b_long_hung/郡口, 946 起 b_dantu/丹徒),
        而 `cache.landed.realm_capital` 只有末档值, 故读逐档闩存的 `capital_history`
        (见 cache_lib)；老缓存无该键时退回末档 realm_capital。头衔 id → key →
        `provmap` 反查省份。"""
        ch = self.cache.get("capital_history") or []
        pid = self.cache.get("player_id")
        want = None
        if ch and date:
            dk = cl.date_key(str(date))
            for pt in ch:
                d = pt.get("date")
                if d and cl.date_key(str(d)) <= dk:
                    want = pt.get("title")
                elif d:
                    break
        if want is None:
            rec = (self.cache.get("characters") or {}).get(str(pid)) or {}
            want = (rec.get("landed") or {}).get("realm_capital")
        if want is None:
            return None
        key = (self._lt.get(str(want)) or {}).get("key") or ""
        prov = self._prov_inv().get(key)
        if isinstance(prov, int):
            return prov
        # 头衔不在（被毁/换 id）时退一步: 取该头衔条目的 capital（其州府头衔）再反查
        cap = (self._lt.get(str(want)) or {}).get("capital")
        key2 = ((self._lt.get(str(cap)) or {}).get("key")
                if isinstance(cap, int) else "")
        prov = self._prov_inv().get(key2)
        return prov if isinstance(prov, int) else None

    def capital_place_at(self, date=None):
        """v57 (问题3): 主角当时首都的地名 (贵族领/州府名; 取不到返回 '')。"""
        prov = self._capital_province_at(date)
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

    @staticmethod
    def _executed_by(rec, pid):
        """v57 (问题3): 该角色是否被 pid **处决** (存档只存 death_execution)。"""
        d = (rec or {}).get("death") or {}
        if d.get("killer") != pid:
            return False
        return str(d.get("reason") or "") in _PRISON_EXEC_REASONS

    @staticmethod
    def _iv_covers(iv, ak):
        """v57 (问题3): 持有区间 (gain, loss, why) 是否覆盖日期标量 ak。"""
        gain = iv[0] if iv else None
        loss = iv[1] if iv and len(iv) > 1 else None
        if not gain:
            return False
        if cl.date_key(str(gain)) > ak:
            return False
        if loss and cl.date_key(str(loss)) < ak:
            return False
        return True

    def _prov_inv(self):
        """v57 (问题3): 头衔 key → 省份索引 的反查表 (惰性建一次, 约 1 万条)。"""
        if getattr(self, "_prov_invmap", None) is None:
            inv = {}
            for prov, v in (self.provmap or {}).items():
                if isinstance(v, dict):
                    for k in ("county", "barony"):
                        key = v.get(k)
                        if key and key not in inv:
                            inv[key] = int(prov)
                elif isinstance(v, str) and v:
                    inv.setdefault(v, int(prov))
            self._prov_invmap = inv
        return self._prov_invmap

    def _primary_landed_at(self, cid, date=None):
        """某人 date 时点**首要领地头衔** id (取不到返回 None)。

        与 `_primary_title_at` 同口径 (男爵领不入首要头衔 —— v36 用户拍板5; 同层级取
        最早获得者), 但两处收紧:
          · **含当日刚失去的头衔** —— 被处死者正是「持有到卒日、卒日终结」, 而旧函数
            只认未结束区间, 于是被处死者一个头衔都取不到 (斯卡利茨 53/53 全空);
          · 世族庄园 (`_nf_`) 与营地/毡帐 (rank 0) 不计。
        v57 (问题4) 借它取「最高头衔层级」, 判行政任免流水 (见 `admin_title_noise`)。"""
        anchor = date or self.as_of
        if not anchor:
            return None
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return None
        ak = cl.date_key(str(anchor))
        best = None      # (rank, gain_key, tid)
        for tid, ivs in (self._hold_intervals(cid, anchor) or {}).items():
            key = (self._lt.get(str(tid)) or {}).get("key") or ""
            if not key or self._is_estate_title(tid):
                continue
            rank = self._TT_RANK.get(key[:2], 0)
            if rank <= 1:      # 男爵领只作地名; 营地/毡帐 (x_, rank 0) 不是治所
                continue
            for iv in (ivs or []):
                if not self._iv_covers(iv, ak):
                    continue
                cur = (rank, cl.date_key(str(iv[0])), tid)
                if best is None or cur[:2] > best[:2]:
                    best = cur
        return best[2] if best else None

    def _celestial_like_at(self, cid, date=None):
        """v57 (问题4): 该角色在该日是否行天朝制/行政制一类政体 (官职轮转, 头衔靠铨选)。"""
        gov = self._character_government(cid, date) or ""
        return gov in self._CELESTIAL_LIKE_GOVS

    def admin_title_noise(self, tid, date=None, pid=None):
        """v57 (问题4, 用户拍板): 该头衔在该日是否属**行政任免流水** (不进年表)。

        用户原话: 「理论上除了最高头衔，其他头衔都是根据选举决定的继承者，只是因为
        没有符合条件的才会给回玩家」—— 故天朝制/行政制政体下, **低于主角首要头衔**的
        头衔得失 (受任/接任/辞去/褫夺/夺得/调任) 不构成传主行迹 (斯卡利茨实测: 这类行
        占《本纪》纪事年表 31.5%、《朝局风云录》开篇 95.8%)。
        最高头衔本身的得失照旧 (受任秦皇帝等); 封建采邑 (继承制) 一律不动。"""
        if tid is None:
            return False
        pid = self.cache.get("player_id") if pid is None else pid
        if pid is None or not self._celestial_like_at(pid, date):
            return False
        top_tid = self._primary_landed_at(pid, date)
        if top_tid is None:
            return False
        top_key = (self._lt.get(str(top_tid)) or {}).get("key") or ""
        top_rank = self._TT_RANK.get(top_key[:2], 0)
        key = (self._lt.get(str(tid)) or {}).get("key") or ""
        if not key:
            return False
        return self._TT_RANK.get(key[:2], 0) < top_rank

    def victim_place(self, cid):
        """受害者所在地 (v24): 其死亡前后最近可知的男爵领名。
        取值: ① 时代熔件中仍存活 → alive_data.location (终传尾年死者属此);
        ② 缓存死亡记录 location_province (死亡写入时复制自 last_location);
        ③ 缓存 last_location。解析失败返回 '' — 调用方省略地点标注。

        v57 (问题3, 用户拍板): **被主角处决者一律在主角当时的首都** —— 处决发生在首都,
        而存档给的是各处行刑地 (诛灭满门那种游戏让他们在自家治所"死", 也有行刑地记在
        别处的); 故不采信这些, 改取 `capital_history` 那一档的 `realm_capital` 地名
        (首都本身会搬: 斯卡利茨实测 924–945 郡口、946 起丹徒)。非「主角处决」者照旧。"""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        d = rec.get("death") or {}
        if self._executed_by(rec, self.cache.get("player_id")):
            nm = self.capital_place_at(d.get("date"))
            if nm:
                return nm
        loc = self.character_location_province(cid)
        if loc is None:
            loc = d.get("location_province")
        if loc is None:
            # v81 (问题6): 跨战役缓存兜底 —— 同一战役里别人那份缓存可能才记着
            # 这个人的末次所在 (实测田所广久 卒957 的 location_province 只在
            # `player_59838.json` 里, 平师久 卒960 的 last_location 只在他自己
            # 那份缓存里), 34/37 → 36/37。
            # 取值优先级: 先全战役找**死亡时复制的** `location_province` (最准),
            # 都无则取 `last_location` 里**日期最晚**的一份 (不是「逢有值即取」)。
            best_dk = None
            for src in [self.cache] + list((self.campaign or {}).values()):
                r = ((src or {}).get("characters") or {}).get(str(cid)) or {}
                cand = (r.get("death") or {}).get("location_province")
                if isinstance(cand, int):
                    loc = cand
                    break
                ll = r.get("last_location") or {}
                if isinstance(ll.get("province"), int) and ll.get("date"):
                    dk = cl.date_key(str(ll["date"]))
                    if best_dk is None or dk > best_dk:
                        best_dk, loc = dk, ll["province"]
        if loc is None:
            return ""
        return self._place_of_province(loc)

    def _place_of_province(self, prov):
        """省份 id → 男爵领名 (取不到退伯爵领名; 皆无返回 '')。

        v81: 由 `victim_place` 的内联逻辑提出 —— 卒地与生地两处必须同一口径。"""
        if not isinstance(prov, int):
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

    # ---- v84: 长途旅行 (travel_plans / activity_manager) ----
    @staticmethod
    def _plan_header(rec):
        """旅行计划记录 → **计划头** (owner/activity/departure_date/destinations…)。

        实测形态 (logs/v84_probe_travel2.txt):
        `database[<id>]` = 运行态 (`state`/`resume_date`/`progress_value`/
        `activity_completed`…) + `data` → `{data: <计划头>, destinations: [...],
        path: {...}}` —— 计划头在**第二层** `data.data`, 不是第一层。"""
        d = (rec or {}).get("data") if isinstance(rec, dict) else None
        if not isinstance(d, dict):
            return {}
        inner = d.get("data")
        if isinstance(inner, dict) and ("owner" in inner or "departure_date" in inner):
            return inner
        return d

    @staticmethod
    def _plan_legs(rec):
        """旅行计划记录 → 逐段行程 [{province, arrival_date, estimated_arrival_date,
        path_index}] (未抵达的段 `arrival_date` = '-1.1.1')。"""
        d = (rec or {}).get("data") if isinstance(rec, dict) else None
        legs = (d or {}).get("destinations") if isinstance(d, dict) else None
        return legs if isinstance(legs, list) else []

    @staticmethod
    def _act_body(rec):
        """活动记录 → 活动对象 (type/host/current_phase/phases…); 兼容 `data` 包装。"""
        if not isinstance(rec, dict):
            return {}
        inner = rec.get("data")
        if isinstance(inner, dict) and ("type" in inner or "host" in inner):
            return inner
        return rec

    @staticmethod
    def _plan_db(melt):
        """熔件 → {plan_id: 记录} (**只留活计划**)。

        该段是熔件顶层段 (v84 实测: 278 MB 档里在 262 MB 处), 而 `Facts.melt` 是整份
        已载入的熔件 ⇒ 零额外 I/O。空槽 (null) 与非 dict 条目一律跳过 —— 实测
        1006 档 625 槽里只有 348 条是活计划。"""
        db = ((melt or {}).get("travel_plans") or {}).get("database") or {}
        return {str(k): v for k, v in db.items()
                if isinstance(v, dict) and isinstance(v.get("data"), dict)}

    def transit_facts(self, cid):
        """该角色在**本篇熔件当刻**仍在走的旅行计划 (v84, 用户 2026-09-29)。

        要解决的问题: 传主若**死在旅途中**, 成稿此前只有「卒于X」, 读不到
        「当时正前往/正返回某地、为参加哪个活动」。存档里有这段 —— 逐条取证见
        `docs/方案_v84_标题重复与旅途留痕.md` §2 与 `logs/v84_probe_travel*.txt`、
        `logs/v84_probe_transit.txt`、`logs/v84_probe_place.txt`:
          · `travel_plans.database[<id>]`: 运行态 (`state`=transit/paused/completed、
            `activity_completed`) + 计划头 (owner/travel_leader/companions/activity/
            departure_date/departure_location/destinations) + 逐段 `destinations[]`
            (province/arrival_date/estimated_arrival_date/path_index) + `path`
            (visited_locations/path/progress);
          · `activity_manager.database[<id>]`: 活动对象 (type/host/phases/attending…)。

        v84 实测定下的三条口径:
          · **计划随死亡消失** (卒于两档之间者, 卒后档 0 条) ⇒ 只能读卒前那一档,
            也就是本篇熔件; 故本函数不另开熔件;
          · 段序 `destinations = [活动地, 回家]` + `activity_completed` ⇒ **去程/回程**
            可判 (引擎不落 `travel_returning_home`/`from_activity` 任何硬标志);
          · 本篇截止日 (`as_of`) 早于熔件当刻、或早于启程日 ⇒ **不下发**
            (与 v81 卒地同闸: 免得未来的行程漏进早年的十年传记)。

        返回数据 dict (无计划返回 None); 句子由 `transit_death_clause` 拼进卒句:
        `{role, plan_state, melt_date, departure_date, departure_place, to_place,
          to_arrived, activity, activity_type, activity_host_self, leg}`
        —— 站数/预计到达/末站**不入 dict**: 用户 2026-09-29 拍板「人都死了,
        历程几个站、预计什么时候到哪根本不重要」。"""
        if cid is None:
            return None
        cid = str(cid)
        best = None                      # (优先级, plan_id, rec)
        for pid, rec in self._plan_db(self.melt).items():
            h = self._plan_header(rec)
            role = ""
            if str(h.get("owner")) == cid:
                role = "owner"
            elif str(h.get("travel_leader")) == cid:
                role = "travel_leader"
            elif any(str((c or {}).get("character")) == cid
                     for c in (h.get("companions") or [])):
                role = "companion"
            if not role:
                continue
            prio = {"owner": 3, "travel_leader": 2, "companion": 1}[role]
            if best is None or prio > best[0]:
                best = (prio, pid, rec, role)
        if best is None:
            return None
        _prio, _pid, rec, role = best
        h = self._plan_header(rec)
        legs = self._plan_legs(rec)
        melt_date = ((self.melt or {}).get("meta_data") or {}).get("meta_date") or ""
        dep = str(h.get("departure_date") or "")
        # ---- 篇章闸 (v81 卒地同旨): 未来信息不进早年篇 ----
        if self.as_of:
            ao = cl.date_key(str(self.as_of))
            if melt_date and cl.date_key(melt_date) > ao:
                return None
            if dep and dep != "-1.1.1" and cl.date_key(dep) > ao:
                return None
        dests = [d for d in (h.get("destinations") or []) if isinstance(d, int)]
        # ---- 活动: 计划头 `activity` → activity_manager ----
        act_name, act_type, act_host_self = "", "", False
        aid = h.get("activity")
        if aid is not None:
            adb = ((self.melt or {}).get("activity_manager") or {}).get("database") or {}
            a = self._act_body(adb.get(str(aid)))
            act_type = str(a.get("type") or "")
            act_name = L.loc(self.table, act_type) or "" if act_type else ""
            act_host_self = str(a.get("host")) == cid
        first = legs[0] if legs else {}
        arrived = str(first.get("arrival_date") or "")
        arrived = "" if arrived in ("-1.1.1", "none") else arrived
        out = {
            "role": role,
            "plan_state": str(rec.get("state") or ""),
            "melt_date": melt_date,          # 出处档 (判据与追溯用)
            "departure_date": dep,
            "departure_place": self._place_of_province(h.get("departure_location")),
            "to_place": self._place_of_province(dests[0]) if dests else "",
            "to_arrived": arrived,
            "activity": act_name,
            "activity_type": act_type,
            "activity_host_self": act_host_self,
            # 去/回: 段序 [活动地, 回家] + `activity_completed` ⇒ 活动办完即回程
            "leg": "回" if rec.get("activity_completed") else "去",
        }
        if not (out["to_place"] or out["departure_place"]):
            return None                  # 地名全取不到 = 无料不下发
        return out

    def transit_death_clause(self, t):
        """卒句的**前半**: 「1002年7月15日自秋田启程，赴坎特伯雷主办院校访学，途中」(v84)。

        用户 2026-09-29 口径: 死于旅途者, 卒句直接给出「启程日 + 自X启程 + 赴Y 干什么 +
        (途中/返程途中)」四样, **不写**已历站数、预计到达日、末站 —— 人都死了,
        行程细节无用。本从句接在 `p["death"]` 之前即成一整句:

          1002年7月15日自秋田启程，赴坎特伯雷主办院校访学，途中死于1006年8月7日，酗酒而亡。

        用户 2026-09-29 口径 (二选一, 已拍板「回来用返程, 去用途中」):
          · `leg == "回"`  ⇒ 「返程途中」 (运行态 `activity_completed` 已置);
          · 其余 (去程, 含 `paused` 滞留、含已抵目的地却仍在办活动者) ⇒ 「途中」。
        `to_arrived` 只作**复核**用 (卒地若正是目的地, 值得回看这一档), 不参与取词。
        取不到启程日或目的地时返回 '' —— 宁可不并, 也不写成半句。"""
        if not t or not t.get("to_place"):
            return ""
        dep = str(t.get("departure_date") or "")
        bits = []
        if dep and dep != "-1.1.1":
            bits.append(f"{self.date(dep)}自{t['departure_place']}启程"
                        if t.get("departure_place") else f"{self.date(dep)}启程")
        seg = f"赴{t['to_place']}"
        if t.get("activity"):
            seg += ("主办" if t.get("activity_host_self") else "参加") + str(t["activity"])
        bits.append(seg)
        bits.append("返程途中" if t.get("leg") == "回" else "途中")
        return "，".join(bits)

    def death_place(self, cid):
        """该角色的**卒地** (男爵领, v81 问题6 用户 2026-09-29 要求)。

        与 `victim_place` 同一个出口 —— 同一件事在《刺客列传》与《人物档案》里
        必须是同一个地名 (被处决者一律算在主角当时的首都, 见 v57 拍板);
        本函数只是给它一个语义清楚的名字, 供档案层调用。取不到返回 ''。"""
        return self.victim_place(cid)

    def birth_place(self, cid):
        """该角色的**生地** (男爵领; v81 问题6, 用户 2026-09-29 要求)。

        存档**不持久化**出生地 —— 游戏侧逐条取证见
        `docs/调研_v81_宝物所在地与出生地游戏口径.md`: 新生儿落在**母亲所在地**
        (`game/common/on_action/child_birth_on_actions.txt:20-24`), 而落盘的出生
        节点只有特质 `born_in_the_purple` (`events/birth_events.txt:3370`), 角色记录
        与出生记忆里都没有地点字段。故本函数只用**本人首见快照的所在**
        (v81 新增闩存 `cache_lib` 的 `first_location`) 且须满足「首见距出生 ≤ 400 天」
        —— 婴幼期不会自行走动, 首见之地即出生之地; 首见远晚于出生者 (先在外邦、
        后因婚配/往来才入档) 一律返回 '' (宁可不下发, 也不张冠李戴)。
        跨战役缓存取**最早**一份观测 (与 `_chrono_rec` 同式)。
        实测 (logs/v81_place2.txt): 田所档案集 97 名窗口内出生者可判 71 人;
        宗族成员 510/512。"""
        if cid is None:
            return ""
        rec = (self.cache.get("characters") or {}).get(str(cid)) or {}
        birth = rec.get("birth") or (self._chars.get(str(cid)) or {}).get("birth")
        if not birth:
            return ""
        if self.as_of and cl.date_key(str(birth)) > cl.date_key(str(self.as_of)):
            return ""                      # 本篇截止日尚未出生
        best = None
        for src in [self.cache] + list((self.campaign or {}).values()):
            r = ((src or {}).get("characters") or {}).get(str(cid)) or {}
            fl = r.get("first_location") or {}
            if not fl.get("date") or not isinstance(fl.get("province"), int):
                continue
            if best is None or cl.date_key(str(fl["date"])) < cl.date_key(str(best["date"])):
                best = fl
        if best is None:
            return ""
        gap = date_gap_days(birth, best["date"])
        if gap is None or gap < 0 or gap > 800:
            return ""
        # 精确闸 (依 docs/调研_v81_生卒地点.md §2.5 [6a]): 出生日与首见日之间
        # **没有别的档期**时, 首见那一档就是出生后的第一次观测 —— 比固定 400 天闸
        # 更贴语义 (本战役缺 869/880/929 三档, 那几档出生者会被 400 天闸误杀)。
        bkey, fkey = cl.date_key(str(birth)), cl.date_key(str(best["date"]))
        if any(bkey < k < fkey for k in self._snapshot_dates()):
            return ""
        return self._place_of_province(best["province"])

    def _snapshot_dates(self):
        """本战役**全部快照日** (升序 date_key; 各传主缓存 `sources` 的并集)。

        v81 (问题6): 供 `birth_place` 判「出生后到首见之间还有没有别的档期」——
        这是「首见所在地＝出生地」这一推断成立的前提。"""
        if getattr(self, "_snap_keys", None) is not None:
            return self._snap_keys
        out = set()
        for src in [self.cache] + list((self.campaign or {}).values()):
            for d in ((src or {}).get("sources") or []):
                try:
                    out.add(cl.date_key(str(d)))
                except Exception:
                    continue
        self._snap_keys = sorted(out)
        return self._snap_keys

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
    # v42 (问题3b): 无须阉人改自然句 —— 旧稿 `{owner}阉割了{other}（自幼，终身无须）。`
    # 把「未满 12 岁被阉」整句塞进括注 (靠 verify_fast 的括注白名单「自幼」放行)。
    # 游戏口径: `castrated_beardless` = Beardless Eunuch, 阉割时未满 12 岁
    # (Traits/Interactions 页: "Castration before puberty…" / "younger than 12 years
    #  old"), 故「在成年前」正合其义。
    "castrated_beardless": "{other}在成年前被{owner}阉割，终身无须。",
    "blind": "{owner}致盲了{other}。",
    "blinded": "{owner}致盲了{other}。",
    "disfigured": "{owner}毁了{other}的容貌。",
    "maim_arm": "{owner}打断了{other}的手臂。",
    "maim_leg": "{owner}打断了{other}的腿。",
}
_TORTURE_VICTIM = {
    "torture": "{owner}受{other}折磨。",
    "castrated": "{owner}被{other}阉割。",
    "castrated_beardless": "{owner}在成年前被{other}阉割，终身无须。",
    "blind": "{owner}被{other}致盲。",
    "blinded": "{owner}被{other}致盲。",
    "disfigured": "{owner}被{other}毁容。",
    "maim_arm": "{owner}被{other}打断手臂。",
    "maim_leg": "{owner}被{other}打断腿。",
}
_TORTURE_TORTURER_NO_OTHER = {
    "torture": "{owner}施刑于人。",
    "castrated": "{owner}施以阉刑。",
    "castrated_beardless": "{owner}在他人成年前施以阉刑，终身无须。",
    "blind": "{owner}施以剜目之刑。",
    "blinded": "{owner}施以剜目之刑。",
    "disfigured": "{owner}施以毁容之刑。",
    "maim_arm": "{owner}施以断臂之刑。",
    "maim_leg": "{owner}施以断腿之刑。",
}
_TORTURE_VICTIM_NO_OTHER = {
    "torture": "{owner}受刑。",
    "castrated": "{owner}被施以阉刑。",
    "castrated_beardless": "{owner}在成年前被阉割，终身无须。",
    "blind": "{owner}被施以剜目之刑。",
    "blinded": "{owner}被施以剜目之刑。",
    "disfigured": "{owner}被施以毁容之刑。",
    "maim_arm": "{owner}被施以断臂之刑。",
    "maim_leg": "{owner}被施以断腿之刑。",
}


# ---------------------------------------------------------------------------
# v78-4 (用户 D3): 人质闭环 —— 起始 (送出/入质/纳质) 与结局 (送还/卒于质所/仍在质)
# ---------------------------------------------------------------------------
# 缺口: `MODULE_TABLE` 只登记了三种 `hostage_created_*`, `hostage_returned_*` 三型与
# `hostage_died` 在 `MEMORY_TEMPLATES` 里**无条目** ⇒ `_mem_sentence_body` 返回 None ⇒
# 连事件都不生成(7 战役实测 ~470 条返回/死亡记忆因此从未进过任何一篇)。
# 槽位 (实测 3 档 244 条 0 例外, owner 不在 participants 内):
#   created/returned_hostage    owner=人质     槽 {home_court, warden}
#   created/returned_warden     owner=监管人   槽 {home_court, hostage}
#   created/returned_home_court owner=原属宫廷 槽 {warden, hostage}
#   hostage_died                owner=监管人   槽 {hostage, home_court} (无 warden 槽)
# 依据: 游戏 `common/character_memory_types/bp2_hostage_memories.txt`、
# `common/on_action/dlc/bp2/bp2_hostage_on_actions.txt`(起始 :9-41 / 结束 :74-152)、
# 本地化 `game/localization/simp_chinese/memories_l_simp_chinese.yml:1077-1119`;
# 详见 `docs/调研_v78_人质闭环.md`。
_HOSTAGE_MEMS = {
    "hostage_created_hostage":    ("hostage", "start", ("home_court", "warden")),
    "hostage_created_warden":     ("warden", "start", ("home_court", "hostage")),
    "hostage_created_home_court": ("home_court", "start", ("warden", "hostage")),
    "hostage_returned_hostage":    ("hostage", "end", ("home_court", "warden")),
    "hostage_returned_warden":     ("warden", "end", ("home_court", "hostage")),
    "hostage_returned_home_court": ("home_court", "end", ("warden", "hostage")),
    "hostage_died":                ("warden", "died", ("hostage", "home_court")),
}
_HOSTAGE_MEM_TYPES = frozenset(_HOSTAGE_MEMS)
# 起始句 (按记忆持有者视角)
_HOSTAGE_START = {
    "home_court": "{owner}送{hostage}至{warden}处为质。",
    "hostage": "{owner}入质于{warden}。",
    "warden": "{owner}纳{home_court}之质{hostage}。",
}
# 送还句 (拼在起始句之后; 起首「，」)
_HOSTAGE_RETURN = {
    "home_court": "，{span}后{hostage}归家。",
    "hostage": "，{span}后归{home_court}。",
    "warden": "，{span}后送还{hostage}。",
}
# 起始记忆被缓存剪除时的**独立送还句**
_HOSTAGE_RETURN_ONLY = {
    "home_court": "{hostage}自{warden}处还归{owner}。",
    "hostage": "{owner}自{warden}处还归{home_court}。",
    "warden": "{owner}送还{hostage}于{home_court}。",
}
_HOSTAGE_DIED = {
    "home_court": "，{date}{hostage}卒于{warden}处。",
    "hostage": "，{date}卒于质所。",
    "warden": "，{date}所质{hostage}卒。",
}
_HOSTAGE_EXEC = {
    "home_court": "，{date}{hostage}见杀于{warden}。",
    "hostage": "，{date}见杀。",
    "warden": "，{date}诛所质{hostage}。",
}
# 「至末档仍在质」——**只用正面硬证** (人质当前宫廷即监管人宫廷、且入宫廷日 == 起始日):
# 作废路径 (`on_hostage_invalidated`) 一条记忆都不写却把人送回家, 故「未见送还」
# 本身不是证据 (调研 §5.3)。
_HOSTAGE_HELD = {
    "home_court": "，至{bound}仍在{warden}处。",
    "hostage": "，至{bound}质于{warden}。",
    "warden": "，至{bound}{hostage}犹在{owner}处。",
}


def _hostage_slots(f, owner_id, mtype, parts, date=None):
    """人质记忆 → (视角角色, {hostage/warden/home_court 的显示名}, {三槽 id})。"""
    spec = _HOSTAGE_MEMS.get(mtype)
    if not spec:
        return None
    role, _phase, slots = spec
    ids = {"hostage": None, "warden": None, "home_court": None}
    ids[role] = owner_id if isinstance(owner_id, int) else None
    for s in slots:
        if isinstance((parts or {}).get(s), int):
            ids[s] = parts[s]
    nms = {k: (f.event_name(v, date=date) or "") if isinstance(v, int) else ""
           for k, v in ids.items()}
    return role, nms, ids


def _hostage_sentence(f, owner_id, mem):
    """单条人质记忆的独立句 (多视角合并见 `_pair_hostages`)。判不出返回 None。"""
    t = mem.get("type")
    spec = _HOSTAGE_MEMS.get(t)
    if not spec:
        return None
    role, nms, _ids = _hostage_slots(f, owner_id, t, mem.get("participants") or {},
                                     mem.get("creation_date"))
    if not nms.get("hostage") and not nms.get("warden"):
        return None
    nms = dict(nms)
    nms["owner"] = nms.get(role) or ""
    phase = spec[1]
    if phase == "start":
        tpl = _HOSTAGE_START.get(role)
    elif phase == "end":
        tpl = _HOSTAGE_RETURN_ONLY.get(role)
    else:
        tpl = _HOSTAGE_DIED.get(role)
    if not tpl or not nms["owner"]:
        return None
    try:
        return tpl.format(**nms)
    except Exception:
        return None


def _hostage_court_held(f, hostage, warden, start_date):
    """正面硬证: 人质当前宫廷即监管人宫廷、且入宫廷日 == 起始日 (调研 §5.3)。"""
    if not isinstance(hostage, int) or not isinstance(warden, int) or not start_date:
        return False
    rec = (f.cache.get("characters") or {}).get(str(hostage)) or {}
    c = rec.get("court") or {}
    return (c.get("employer") == warden
            and str(c.get("join_court_date") or "") == str(start_date))


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


# v38 (问题1): Carnalitas 性事记忆族 (had_sex_*) —— Mod 按
# `(giving|receiving)_player_[(dom|sub)_](vaginal|anal|oral)[_cum_(inside|outside)]_(consensual|dubcon|noncon)`
# 组合出 24 个类型键, 逐键登记进 MEMORY_TEMPLATES 既不现实也无意义。
# 这里按前缀族解析: 方向 (施为/受害)、体位、自愿程度都可从键名确定性读出。
# 用户拍板 (2026-09-14): **只记录强迫 (noncon) 与半强迫 (dubcon)**;
# consensual 仍走旧口径 (`had_sex` / `had_sex_spouse` / `had_sex_consensual`)。
_SEX_MEM_PREFIX = "had_sex_"
_SEX_CONSENT = ("noncon", "dubcon")   # 收录档 (顺序即判定顺序)
_SEX_ACT_OF = (("vaginal", re.compile(r"_vaginal")),
               ("anal", re.compile(r"_anal")),
               ("oral", re.compile(r"_oral")))
# 语境: 判「记忆持有人是施为方还是受害方」——`giving_player` 即施为方
# (与男女无关: 女性施为时 Mod 写 `_fm_desc` 逆强奸, 仍是 giving 方为主使者)。
_SEX_GIVING_RE = re.compile(r"_giving_player")
_SEX_RECEIVING_RE = re.compile(r"_receiving_player")
# 体位/自愿程度的**包含式**匹配 (浮点状态: cum_inside / cum_outside / 无标记)
_SEX_MEM_RE = re.compile(r"^had_sex_")
# v38 (问题1): 性事记忆族的参与槽 — 全部 24 键共用 `sex_partner`
_SEX_PARTNER_SLOT = "sex_partner"
# v38 (问题1 顺带): 三人行 — 两个对象槽
_SEX_THREESOME_TYPE = "had_a_threesome_memory"


def is_sex_memory(mtype):
    """该记忆类型是否属性事 (v59 档案闸用; 含三人行)。

    时间线侧另有按**戏剧模块**判定的 `is_sex_event()` (见下方模块常量区) ——
    那一边要覆盖「自愿档归并成 `had_sex` 后的配偶/非配偶两档」与强迫档。"""
    t = str(mtype or "")
    return bool(_SEX_MEM_RE.match(t)) or t == _SEX_THREESOME_TYPE



def sex_mem_info(mtype):
    """性事记忆类型键 → {role, consent, act, kept} (v38, 问题1)。

    role: 'actor' (持有人为施为方) / 'victim' (持有人为受害方);
    consent: 'noncon' / 'dubcon' / 'consensual' / '';
    act: 'vaginal' / 'anal' / 'oral' / '';
    kept: 是否属用户拍板收录的档 (强迫与半强迫)。
    非性事记忆族返回 None。"""
    t = str(mtype or "")
    if not _SEX_MEM_RE.match(t):
        return None
    if _SEX_RECEIVING_RE.search(t):
        role = "victim"
    elif _SEX_GIVING_RE.search(t):
        role = "actor"
    else:
        role = "actor"
    consent = ""
    for c in _SEX_CONSENT + ("consensual",):
        if t.endswith("_" + c):
            consent = c
            break
    act = ""
    for name, rx in _SEX_ACT_OF:
        if rx.search(t):
            act = name
            break
    return {"role": role, "consent": consent, "act": act,
            "kept": consent in _SEX_CONSENT}


def _sex_mem_sentence(f, owner_id, mem, info):
    """性事记忆 (强迫/半强迫) → 干净中文句 (v38, 问题1; v39 体位措辞)。

    持有人是施为方还是受害方由 `sex_mem_info` 从键名读出 (与男女无关),
    对方取 `sex_partner` 槽。体位 (阴道/肛/口) 与自愿程度 (强迫/半强迫)
    都进句面; v39: 施为方为女性时强迫档另取「逆强奸」句 (Mod 的 `_fm_desc`
    文案即「我逆强奸了X」), 性别取存档 `female` 字段判定。
    射精位置与其余性行为细节不进事实面 (它们是游戏 UI 的露骨描述)。"""
    parts = mem.get("participants") or {}
    other_id = parts.get(_SEX_PARTNER_SLOT)
    if not isinstance(other_id, int) or other_id == owner_id:
        # 参与槽缺失或指向自己 = 存档退化记录 (见 _PEER_SLOT_TYPES 同源判据)
        return None
    # v42 (问题4): 年表事实行 —— 主角只出名字 (见 Facts.event_name)
    owner = f.event_name(owner_id, date=mem.get("creation_date"))
    other = f.event_name(other_id, date=mem.get("creation_date"))
    if not owner or not other:
        return None
    key = f"{info['role']}_{info['consent']}"
    # v39: 女方施为的强迫档 —— 插入语义只对阴道与肛两档成立, 口交档仍作「强迫…口交」
    if info["role"] == "actor" and info["consent"] == "noncon" \
            and info["act"] in ("vaginal", "anal") and f._is_female(owner_id):
        key = "actor_reverse_noncon"
    table = _style.SEX_MEM_WORDING.get(key) or {}
    tpl = table.get(info["act"]) or table.get("base")
    if not tpl:
        return None
    return tpl.format(name=owner, other=other)


def _lovers_in_same_prison(f, a, b, date):
    """相恋缘由的**程序兜底** (v56 §10-D) → 句 或 ''。

    判据: a 与 b 在关系起始日**同囚于同一监禁者、同为 house_arrest (软禁)** ——
    即两人各自 `prison_history` 里都有一个区间满足
    `same imprisoner ∧ type == "house_arrest" ∧ since/from ≤ date ≤ to`。
    出「{A}与{B}同在{J}的软禁中相恋。」(监禁者不可考时省去)。

    为什么需要: 游戏只在**关系条目存续期**写 `reason` (`lover_prison`, 见
    `events/prison_events/house_arrest_ongoing_events.txt` option .d), 关系解除或
    当事人死亡后条目消失; 而闩存只在「并入的那一档」看得到 —— 从较晚的档才开始
    重建时读不到 reason, 此时仍可由在押事实判定这段关系起于狱中。
    判据要求关系起始日**落在共同在押区间内**, 故「先成情人、后同囚」不会被误判;
    有 reason 键时不走这条 (仅兜底)。"""
    if not isinstance(a, int) or not isinstance(b, int) or a == b or not date:
        return ""
    try:
        dk = cl.date_key(str(date))
    except Exception:
        return ""
    chars = f.cache.get("characters") or {}

    def _jailers_in_span(cid):
        out = set()
        for iv in ((chars.get(str(cid)) or {}).get("prison_history") or []):
            if not isinstance(iv, dict) or iv.get("type") != "house_arrest":
                continue
            jailer = iv.get("imprisoner")
            lo, hi = iv.get("since") or iv.get("from"), iv.get("to")
            if not isinstance(jailer, int) or not lo or not hi:
                continue
            try:
                if cl.date_key(str(lo)) <= dk <= cl.date_key(str(hi)):
                    out.add(jailer)
            except Exception:
                continue
        return out

    common = _jailers_in_span(a) & _jailers_in_span(b)
    if not common:
        return ""
    jailer = sorted(common)[0]
    an = f.event_name(a, date=f.as_of) or f.name_or(a)
    bn = f.event_name(b, date=f.as_of) or f.name_or(b)
    if not an or not bn:
        return ""
    W = _FACT_WORDING
    jn = f.event_name(jailer, date=f.as_of) or f.name_or(jailer)
    if jn:
        return W["lovers_same_prison"].format(name=an, other=bn, jailer=jn) + "。"
    return W["lovers_same_prison_no_jailer"].format(name=an, other=bn) + "。"


def _mem_sentence(f, owner_id, mem):
    """一条记忆 → 干净中文句。

    v31: 同伴槽位型记忆的参与槽与持有者同一人时返回 None (退化记录, 见
    `_PEER_SLOT_TYPES`); 配偶之间的 had_sex 改用「同房」模板 (问题2/3)。
    v38 (问题1): Carnalitas 性事族 (had_sex_*) 按前缀族解析 —— 强迫 (noncon)
    与半推半就 (dubcon) 出句, 其余自愿档仍走旧模板。
    v59 (问题2): 三档句面只在角色档案与好友/仇人列传里使用 (公开年表已闸掉);
    v40「性病传播当次的自愿档出体位句 + 句末补注」这一特例随之删除
    (补注只挂在年表性事行上, 该行已不存在)。
    v45 (档 B): 外层包一层出词登记 —— 本句用到的每个 (cid, 称谓) 记进
    `f.name_index[本句]`, 供板块期在**确切位置**插入亲缘定语。
    v63: 同时登记本行主语 (`owner_id` = 记忆持有人, 各模板皆以他起句) —— 句中
    第三方人名的定语按本行主语算词, 不按板块传主 (见 `biography._kin_tag_line`)。"""
    with f.log_names() as lg:
        out = _mem_sentence_body(f, owner_id, mem)
    out = f.index_names(out, lg, owner=owner_id)
    f.note_line_stated(out, mem, owner_id)
    return out


class _NameLog:
    """v45 (档 B): 一行的称谓出词登记器 (栈式 —— 嵌套时各层都收到)。"""

    __slots__ = ("f", "items")

    def __init__(self, f):
        self.f = f
        self.items = []          # [(cid, label), …] 按出词顺序

    def __enter__(self):
        self.f._name_logs.append(self)
        return self

    def __exit__(self, *exc):
        try:
            self.f._name_logs.remove(self)
        except ValueError:
            pass
        return False


def _mem_sentence_body(f, owner_id, mem):
    mtype = mem.get("type")
    # ---- v78-4: 人质族 (三视角各一句; 多视角合并见 `_pair_hostages`) ----
    if mtype in _HOSTAGE_MEM_TYPES:
        return _hostage_sentence(f, owner_id, mem)
    # ---- v38: Carnalitas 性事族 (含多数无逐键模板者) ----
    if isinstance(mtype, str) and mtype.startswith(_SEX_MEM_PREFIX):
        info = sex_mem_info(mtype)
        if info is None:
            return None
        if info["kept"]:
            return _sex_mem_sentence(f, owner_id, mem, info)
        # 其余自愿档: 继续走旧模板 (had_sex / had_sex_spouse / had_sex_consensual)
        mtype = "had_sex"
    # v38 (问题1 顺带): 三人行 —— 两个对象槽 (partner_1/partner_2)
    if mtype == "had_a_threesome_memory":
        parts = mem.get("participants") or {}
        ids = [parts.get(k) for k in ("partner_1", "partner_2")]
        ids = [i for i in ids if isinstance(i, int) and i != owner_id]
        if not ids:
            return None
        owner = f.event_name(owner_id, date=mem.get("creation_date"))
        names = [f.event_name(i, date=mem.get("creation_date")) for i in ids]
        names = [n for n in names if n]
        if not owner or not names:
            return None
        return f"{owner}与{'、'.join(names)}同宿。"
    tpl = MEMORY_TEMPLATES.get(mtype)
    if not tpl:
        return None
    # v75 (凶手点名): 主角的「成功谋杀」记忆是他的**内情** —— 密谋未暴露时,
    # 公开档改写成死者的公开死讯 (世人说法), 不点名凶手。「密谋暴露」者
    # (killer_known ∨ 死因自带公开性) 照旧走模板点名 (用户 2026-09-27 拍板 D1)。
    if mtype == "successful_murder":
        _v = (mem.get("participants") or {}).get("victim")
        if isinstance(_v, int) and f.killer_hidden(_v, owner_id):
            _cl = f.death_clause(_v, imprison=True)
            _vn = f.event_name(_v, date=mem.get("creation_date"))
            return f"{_vn}{_cl}。" if (_vn and _cl) else None
    extra_fname = ""
    owner = f.event_name(owner_id, date=mem.get("creation_date"))
    parts = mem.get("participants") or {}
    slot = PARTICIPANT_SLOTS.get(mtype)
    other_id = None
    if slot and slot in parts and isinstance(parts[slot], int):
        other_id = parts[slot]
    elif slot is None:
        for v in parts.values():
            if isinstance(v, int):
                other_id = v
                break
    # v31 (问题3): 「对象 = 自己」的同伴记忆是存档退化记录 (实测妻子 6 条 had_sex
    # 的 sex_partner 即其本人), 整条丢弃 — 不写「公主与公主有私情」。
    if other_id is not None and other_id == owner_id \
            and mtype in _PEER_SLOT_TYPES:
        return None
    # v32 (问题3): 夭折记忆的生母槽与持有人同一人 (生母自己的那条记忆) — 不是退化记录,
    # 只是「无对手方」, 走 `_no_other` 模板写「X产下死婴。」。
    if other_id is not None and other_id == owner_id \
            and mtype in _SELF_NO_OTHER_TYPES:
        other_id = None
    # v31 (问题2): 配偶之间的床笫之事不写作「私通」
    if mtype == "had_sex" and other_id is not None \
            and f.is_spouse_pair(owner_id, other_id):
        tpl = MEMORY_TEMPLATES.get("had_sex_spouse") or tpl
    other = ""
    if other_id is not None:
        other = f.event_name(other_id, date=f.as_of)
    # v58 (问题8): 关系亡故句 —— 关系词按**句内主语**（记忆持有人）相对死者算，
    # 并把关系直接写进句面。旧稿一律「{name}的亲属{other}去世。」, 再由板块期
    # 按**板块传主**插亲缘定语: 驼背戈特弗里德档案里的「父亲去世」因此被写成
    # 「的亲属公公…去世」(公公是玛蒂尔达对死者的称谓)。
    if mtype in _REL_DIED_TYPES and isinstance(other_id, int) \
            and other and other_id != owner_id:
        _k = kin_key(f.cache, owner_id, other_id,
                     spouse_back=f._spouse_back_index(),
                     rev=f._kin_rev_index())
        _kw = kin_text(_k) if _k else ""
        if _kw:
            return f"{owner}的{_kw}{other}去世。"
    # v32: 无对手方 → 回退 `<type>_no_other` 模板 (被囚/逃脱/夭折三类都有)
    if not other:
        tpl = MEMORY_TEMPLATES.get(f"{mtype}_no_other") or tpl
    # v56 (§10, 用户拍板 A+B+C+D): 「相恋」句优先出**游戏自己的缘由句** ——
    # 「X和Y在Z的地牢里相爱了。」(reason=`lover_prison`, 第三人槽=监禁者)。
    # 记忆本身只有结果 (无 reason/地点/监禁者), 缘由在**关系条目**上: 熔件里查得到就用
    # 熔件, 查不到用逐档闩存的 `cache["relation_reasons"]` (v56 起收录面已放宽到
    # 「双方都在角色表内」, 故两个都不是主角的当事人也有)。两路都没有时按同狱在押
    # 事实兜底 (见 `_lovers_in_same_prison`)。
    if mtype == "became_lovers" and isinstance(other_id, int) \
            and other_id != owner_id:
        _rs = f.relation_reason_for_pair(owner_id, other_id, ("lover",),
                                         styled=True)
        if _rs:
            return _rs[0]
        _fb = _lovers_in_same_prison(f, owner_id, other_id,
                                     mem.get("creation_date"))
        if _fb:
            return _fb
    # v32 (问题3): 夭折句的配偶称谓 (妻/夫/妾/情人) — 由关系数据判定, 不靠措辞猜
    rel = ""
    if mtype in _CONSORT_MEM_TYPES and other_id is not None:
        rel = f._consort_word(owner_id, other_id)
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
        # v34 (问题8, 用户拍板): 「添子」句的持有者若是孩子的**法理父亲**, 句义已明确,
        # 不加血缘补注 (非婚生仍是他的子女, 本纪只写家门);
        # 法理父另有其人时 (句首是生母/他人) 才补「生父X」, 免把生母的生育
        # 读成持有人得子 (法霍·索丹的生父是索丹·索丹, 法理父也是索丹·索丹)。
        kid = parts.get("child")
        if isinstance(kid, int):
            kfam = ((f.cache.get("characters") or {}).get(str(kid)) or {}).get("family") or {}
            kfather = (kfam.get("father") or [None])[0]
            kreal = (kfam.get("real_father") or [None])[0]
            who = kreal if isinstance(kreal, int) else kfather
            if isinstance(who, int) and owner_id is not None \
                    and who != owner_id and kfather != owner_id:
                wname = f.event_name(who, date=f.as_of) or f.name_or(who)
                # v74 (问题3, 用户拍板): 持有人**既非孩子生父亦非生母**时 (典型:
                # 丈夫的 `child_born`/`first_born` 记忆 —— 游戏在妻子受孕时也给丈夫
                # 记一条), 句首改由**生母**作主语, 丈夫只作限定:
                # 「田所浩二之妻藤原诸子生女和气敬子，生父和气丰永。」
                # 旧稿只往句尾追加「，生父X。」而主语仍是丈夫, 于是写出
                # 「田所浩二得长女和气敬子，生父和气丰永。」—— 模型据此把敬子读成
                # 主角之女 (第 1 个十年成稿「敬子遂入田所氏」)。见方案 §3.4。
                kmother = (kfam.get("mother") or [None])[0]
                if isinstance(kmother, int) and kmother != owner_id and wname:
                    mn = f.event_name(kmother, date=f.as_of) or f.name_or(kmother)
                    if mn:
                        word = "女" if f._is_female(kid) else "子"
                        rel_w = f._consort_word(owner_id, kmother)
                        subj = f"{owner}之{rel_w}{mn}" if rel_w else mn
                        return f"{subj}生{word}{other}，生父{wname}。"
                if wname:
                    # v55 (问题2): 去括注 —— 「添子X，生父Y。」
                    tpl = tpl.rstrip("。") + "，生父{fname}。"
                    extra_fname = wname
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
    _td = None
    if mem.get("type") in TITLE_VAR_TYPES:
        # v34b: 头衔得失句用 **title history 事件日** (记忆日常晚一天)
        _td = f.mem_date(owner_id, mem) or mem.get("creation_date")
        _reason = ""
        for v in mem.get("vars") or []:
            if v.get("flag") == "reason":
                _reason = str(v.get("value") or "")
                break
        for v in mem.get("vars") or []:
            if v.get("flag") == "landed_title" and v.get("identity"):
                title_tid = v.get("identity")
                # v66: migration 失衔记忆的 landed_title 恒记最初那块郡, 改由
                # `new_holder` 反查真头衔 (见 Facts.migration_lost_title)
                if mem.get("type") == "lost_title_memory" and _reason == "migration":
                    _rt = f.migration_lost_title(
                        owner_id, _td,
                        (mem.get("participants") or {}).get("new_holder"))
                    if _rt is not None:
                        title_tid = _rt
                # v53/v54: 名字与层级词一律按事件日取 —— `title()` 自 v54 起
                # 读该日动态国号 (title_history_names) 与天朝链层级词,
                # 故 created/appointment/conquest 共用一条取值链, 不再分叉。
                # v66: 名字改走 **用地名** (site=True) —— 末档粘滞名会把游牧期
                # 「迁得/迁离」句全部写成同一个「库曼顿巴斯部」(实测 6 条全指他
                # 935 年就丢了的那块郡); 用地名按档取「主角占领它之前」的名字,
                # 同一块地得/失同名。**只对 migration 生效**: 受封/攻取/创建/承袭
                # 那几档说的是政权 (阿尤布苏丹国由宗族命名), 混用地名会把
                # 「创建阿尤布苏丹国」写成「创建也门王国」(沙蒂永 1179 实测)。
                # 锚点角色: 主角持有过则锚主角 (对手方的行随主角的叫法)。
                _scid = f._site_cid_for(title_tid, owner_id)
                _site = (_reason == "migration")
                title = f.title(title_tid, date=_td, site=_site, site_cid=_scid) \
                    or f.title(title_tid, site=_site, site_cid=_scid)
                break
    elif mem.get("type") in ("held_a_coronation_memory",
                             "crowned_by_hof_memory"):
        # v56 (问题1b): 加冕成的头衔 —— 记忆本身不带 landed_title var, 按**加冕当日**
        # 的首要头衔取 (游戏文案即「正式加冕为[owner.GetPrimaryTitle]的合法[title]」)。
        # v78-5: `crowned_by_hof_memory` (受祝圣而加冕) 同取, 否则句尾「加冕为{title}」
        # 会留空槽。
        _td = f.mem_date(owner_id, mem) or mem.get("creation_date")
        _tier, _tid = f._primary_title_at(owner_id, as_of=_td)
        if _tid is not None:
            title = f.title_office_text(owner_id, _tid, _td) \
                or f.title(_tid, date=_td) or ""
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
            # v34b (柳特佩特): reason=created 是**本人创设头衔** (游戏自有文案
            # 即「我创建了X」), 不是受封; 分档同游戏 desc_created_first /
            # desc_created —— 头衔此前另有主人 (废弃后重立) 写「重建」。
            if reason == "created" and title_tid is not None:
                _kind = f.created_verb_kind(
                    title_tid, owner_id, mem.get("creation_date"))
                verb = TITLE_GAIN_CREATED_VERBS.get(_kind) or verb
            if verb:
                # v36 (用户拍板4): 他人授予的头衔补「被谁任命/授予」(动词按授予方政体)
                if owner_id is not None and title_tid is not None \
                        and reason in _GRANTED_REASONS:
                    gcid = f.grant_actor(owner_id, title_tid, mem.get("creation_date"))
                    gl = f.event_name(gcid, date=mem.get("creation_date")) \
                        if isinstance(gcid, int) else ""
                    if gl:
                        office = f.title_office_text(
                            owner_id, title_tid, mem.get("creation_date")) or title
                        return f"{owner}受{gl}{f.grant_verb(gcid, mem.get('creation_date'))}为{office}。"
                return f"{owner}{verb}{title}。"
        else:
            verb = TITLE_LOSS_VERBS.get(reason)
            if verb:
                # v36 (用户拍板4): 被谁剥夺 / 自愿辞职
                actor = ""
                if reason in ("revoked", "usurped"):
                    actor = f.revoke_actor(owner_id, title_tid,
                                           mem.get("creation_date"), reason)
                if actor:
                    office = f.title_office_text(
                        owner_id, title_tid, mem.get("creation_date")) or title
                    word = _style.TITLE_REVOKE_VERB if reason == "revoked" \
                        else _style.TITLE_USURP_VERB
                    # actor 已是称谓串 (revoke_actor 出口, v42 起主角只出名字)
                    return f"{owner}被{actor}{word}{office}。"
                if reason == "stepped_down":
                    office = f.title_office_text(
                        owner_id, title_tid, mem.get("creation_date")) or title
                    return f"{owner}{_style.TITLE_RESIGN_VERB}{office}。"
                return f"{owner}{verb}{title}。"
    s = tpl.format(name=owner, other=other, title=title, rel=rel,
                   fname=extra_fname)
    # 参与者/头衔缺失时清理悬空占位 (v70: 整段收口到可单测的纯函数)
    s = _fixup_mem_placeholders(s, extra_fname=extra_fname)
    # 未补出父亲时不留空分句 (v55: 补注已由括注改为「，生父X」)
    if not extra_fname:
        s = s.replace("，生父。", "。").replace("，生父", "")
    # v43: 成婚句补婚姻线系 —— 母系婚补「，是入赘婚」,
    # 普通婚与判不出者句面不变 (与游戏 UI 只标母系那一档同口径; v51 简化见
    # marriage_lineality_note; v55 去括注)。
    if mem.get("type") == "married" and other_id is not None:
        note = f.marriage_lineality_note(owner_id, other_id,
                                         wedding=mem.get("creation_date"))
        if note:
            s = s.rstrip("。") + note + "。"
    return s


def _fixup_mem_placeholders(s, extra_fname=""):
    """记忆句的悬空占位收口 (从 `_mem_sentence` 抽出, v70: 便于单测)。

    规则:
      · 参与者缺失 → 「与。」「与，」「与、」的悬空连接词去掉;
      · 头衔缺失的让土句 → 「让出领地。」;
      · 头衔缺失的登位句 → 「{名}登位。」(v70 修: 模板是
        `MEMORY_TEMPLATES['ascended_throne_memory']` = 「{name}登位，得{title}。」,
        旧稿把「得。」整段替换成「登位。」, 于是成「斯韦克·克文登位，登位。」
        —— 实测 13 处, 模型照抄);
      · 加冕句缺头衔 → 「加冕。」; 缺生父 → 去掉「，生父」。"""
    s = s.replace("与。", "。").replace("与，", "，").replace("与、", "、")
    s = s.replace("让出。", "让出领地。")
    s = s.replace("登位，得。", "登位。")
    s = s.replace("得。", "登位。")
    s = s.replace("加冕为。", "加冕。")
    if not extra_fname:
        s = s.replace("，生父。", "。").replace("，生父", "")
    return s


def _fervor_word(v):
    """礼仪热情 (0–100) → 档位词 (数值不下发, 与项目「数量类元信息档位化」同口径)。"""
    if v >= 75:
        return "炽盛"
    if v >= 50:
        return "平稳"
    if v >= 25:
        return "低沉"
    return "衰微"


def _sf_word(v):
    """灵性满足 (可负) → 档位词。"""
    if v >= 75:
        return "充盈"
    if v >= 50:
        return "安稳"
    if v >= 25:
        return "尚可"
    if v >= 0:
        return "微薄"
    return "亏欠"


def _rarity_word(v):
    """圣髑珍稀度 (holy_site.total_artifact_rarity) → 档位词。"""
    if v >= 8:
        return "卓绝"
    if v >= 5:
        return "上品"
    if v >= 3:
        return "中品"
    return "寻常"


def _progress_word(ratio):
    """进度比例 (0–1) → 档位词 (大分裂之势 / 章节进度共用)。"""
    if ratio >= 0.75:
        return "迫近"
    if ratio >= 0.5:
        return "渐盛"
    if ratio >= 0.25:
        return "初萌"
    if ratio > 0:
        return "微动"
    return "未起"


def _clean_ck3_loc(s):
    """剥离 CK3 本地化格式标签: \\x15ONCLICK:... \\x15TOOLTIP:... \\x15L \\x15high ...\\x15!
    (家族关系事件文本用, 产出干净中文)。中文后无词边界, 直接用字符级匹配。
    v13: 部分文本「称号，名字」(国王，张格本) 是 mod 翻译瑕疵 — 删去称号与
    名字间的逗号 (国王张格本), 防模型模仿出「囚X一」式怪句。
    v17: 修复方案_汤利五问题.md 问题1 — `[A-Z]+` 不匹配 LANDED_TITLE 的下划线
    (`TOOLTIP:LANDED_TITLE,13449` 残留), 且 `L; 名称` 链接标记剥不掉:
    `[A-Z]`→`[A-Z_]+`, 头衔链接块整体剥离, `L` 后允许 `;`。
    v29: 结果为不可读文本 (裸键/哨兵串/无中日韩字符) 时返回 '' — 调用方改用
    程序重建的句子 (实测 house_relations 出现 'MAX_RECURSIVE_DEPTH')。"""
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
    return s if loc_text_ok(s) else ""


# ---------------------------------------------------------------------------
# v29: 干净事实的最后一道程序兜底 (问题1)
# ---------------------------------------------------------------------------
# 存档/熔件里偶有未解析的本地化键或 rakaly 哨兵串 (实测
# house_relations.history.change_reason = 'MAX_RECURSIVE_DEPTH'); 任何一路渲染
# 漏掉都会把裸键送进提示词。这里按行兜底: 行内出现键形串 (含下划线的 ASCII 词)
# 或全大写哨兵串即丢弃该行并记审计日志 — 模型侧只收到中文事实。

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
_PLACEHOLDER_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")
_KEY_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]{2,}(?![A-Za-z0-9_])")
_SANITIZE_LOG = {"lines": 0, "samples": []}

# v64 (问题4) 幽灵宗主自检 —— 朝局事实面里凡「宗主」指向一个**从未创建**的高位
# 头衔 (history 空且此刻无 holder) 者, 整条不写并记在此处 (verify_fast 呈现)。
_PHANTOM_LIEGE_LOG = {"lines": 0, "samples": []}


def phantom_liege_stats():
    """幽灵宗主自检统计 (供回归/审计脚本断言与打印)。"""
    return {"lines": _PHANTOM_LIEGE_LOG["lines"],
            "samples": list(_PHANTOM_LIEGE_LOG["samples"])}


def loc_text_ok(s):
    """本地化文本是否可读: 含中日韩字符, 且整体不是裸键/哨兵串。"""
    t = str(s or "").strip()
    if not t:
        return False
    if _PLACEHOLDER_RE.match(t) or _KEY_TOKEN_RE.search(t):
        return False
    return bool(_CJK_RE.search(t))


def sanitize_fact_text(text, where=""):
    """事实文本按行兜底: 丢弃带裸键的行, 记审计 (logs/journal.log + 计数)。"""
    if not text:
        return text
    kept, dropped = [], []
    for ln in str(text).split("\n"):
        if ln.strip() and (_PLACEHOLDER_RE.match(ln.strip())
                           or _KEY_TOKEN_RE.search(ln)):
            dropped.append(ln.strip())
            continue
        kept.append(ln)
    if dropped:
        _SANITIZE_LOG["lines"] += len(dropped)
        for d in dropped[:3]:
            if len(_SANITIZE_LOG["samples"]) < 12:
                _SANITIZE_LOG["samples"].append(d)
        try:
            import llm as _llm
            # v51: 逐块明细只进日志文件 (一次生成可达数十条), 收尾合计见
            # biography.generate_biography 的「干净事实兜底共丢弃 N 行」。
            _llm.log(f"干净事实兜底: 丢弃含裸键的行 {len(dropped)} 条"
                     f" (来自 {where or '未知块'}): {dropped[0][:80]}", detail=True)
        except Exception:
            pass
    return "\n".join(kept)


def sanitize_stats():
    """兜底统计 (供回归/审计脚本断言与打印)。"""
    return {"lines": _SANITIZE_LOG["lines"],
            "samples": list(_SANITIZE_LOG["samples"])}


# ---------------------------------------------------------------------------
# v63 (问题5): 亲缘关系的**程序自检** —— 让「不可能的关系」在事实面就被抓住
# ---------------------------------------------------------------------------
# 用户实测: 「藤原范宗之妻，907年9月6日成婚，其父藤原敬子时年三岁」——
# 事实面本身是对的 (丰子＝范宗之妻; 敬子＝范宗与丰子之女, 生 909), 错在
# 《刺客列传》把女性死者的配偶写成「妻」, 且亲缘行是缺生年的扁平名单, 模型
# 于是把相邻两条记录串成了「其父敬子」。词形一侧由
# `Facts.kin_word_gendered` 修掉; 这里只查**逻辑上不可能**的关系 ——
# 判据一律「后出生者不得是长辈」, 与游戏的实际年龄分布无关, 故零误报:
#
#   K1 亲子不可能: 父/母生年 ≥ 子女生年 (父母比子女晚出生);
#   K2 业师不可能: 童年业师 (`childhood_education_guardian`) 比学生晚出生;
#   K3 单边亲缘:   孩子的 `father`/`mother` 指向 X, 而 X 的 `child` 里没有这个孩子
#                  (或反向: X 的 `family.child` 指向孩子, 孩子两亲里没有 X);
#   K4 亲属当配偶: 互为配偶的两人同时又互为父/母/子女 (伦理与逻辑都不可能)。
#
# 刻意**不查**两类看着像错、其实合法的数据:
#   · 「年龄差过小」: CK3 的业师/父母可以与子女只差一两岁 (实测本档 188 例合法业师
#     年龄差 < 12 年), 那是游戏数据常态;
#   · 「妻比夫年长」: 完全正常。
# 命中即写 logs/journal.log, 并作为 verify_fast 的 FAIL 呈现。

# 配偶位键 (K4 用; 与 `_family_ids_by_kind` 同源)
_SPOUSE_KEYS = ("primary_spouse", "spouse", "former_spouses", "ever_spouses",
                "concubine", "former_concubines")


def _audit_name(f, cid):
    """审计报告里的人名 (失败则退裸 id)。"""
    try:
        return f.name_or(cid) or str(cid)
    except Exception:
        return str(cid)


def _audit_year(f, cid):
    """角色生年 (int); 取不到返回 None。"""
    rec = (f.cache.get("characters") or {}).get(str(cid)) or {}
    b = rec.get("birth")
    if not b:
        b = (getattr(f, "_chars", {}) or {}).get(str(cid), {}).get("birth")
    try:
        return int(str(b).split(".")[0])
    except (TypeError, ValueError):
        return None


def _audit_ids(seq):
    """family 字段 → int id 列表 (跳过 'none'/哨兵)。"""
    out = []
    for x in (seq or []):
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def audit_kin_lines(facts, limit=60):
    """facts 事实集的亲缘自检 (v63 问题5) → [「K1 …」, …]。

    只查**存在于事实集里的角色** (`facts["characters"]`) 及其直系亲属,
    逐条核对生年与反向指针; 返回可读字符串 (最多 limit 条)。
    纯函数、无副作用, 供日志与 `verify_fast` 断言共用。"""
    out = []
    f = facts.get("_facts") if isinstance(facts, dict) else None
    if f is None:
        return out
    chars = facts.get("characters") or {}
    cache_chars = f.cache.get("characters") or {}

    def _push(kind, msg):
        if len(out) < limit:
            out.append(f"{kind} {msg}")

    def _fam(cid):
        return (cache_chars.get(str(cid)) or {}).get("family") or {}

    for cid_s, _prof in chars.items():
        try:
            cid = int(cid_s)
        except (TypeError, ValueError):
            continue
        cy = _audit_year(f, cid)
        fam = _fam(cid)
        # ---- K1 亲子不可能: 长辈比晚辈晚出生 ----
        for key, label in (("father", "父"), ("mother", "母")):
            for p in _audit_ids(fam.get(key)):
                py = _audit_year(f, p)
                if cy is not None and py is not None and py >= cy:
                    _push("K1", f"{label}{_audit_name(f, p)} ({py} 年生) → "
                                f"{_audit_name(f, cid)} ({cy} 年生): 长辈晚出生")
        # ---- K3 单边亲缘 ----
        for key, label in (("father", "父"), ("mother", "母")):
            for p in _audit_ids(fam.get(key)):
                if str(p) not in chars:
                    continue          # 父母不在事实集内 → 本板块不下发, 不判
                if cid not in _audit_ids(_fam(p).get("child")):
                    _push("K3", f"{_audit_name(f, cid)} 记 {label}"
                                f"{_audit_name(f, p)}, 而对方 `child` 无此人")
        for c in _audit_ids(fam.get("child")):
            if str(c) not in chars:
                continue
            cf = _fam(c)
            if cid not in (_audit_ids(cf.get("father"))
                           + _audit_ids(cf.get("mother"))):
                _push("K3", f"{_audit_name(f, cid)} 的 `child` 含 "
                            f"{_audit_name(f, c)} 而其两亲无此人")
        # ---- K4 亲属当配偶 (互为配偶同时又互为父/母/子女) ----
        my_sp = set()
        for k in _SPOUSE_KEYS:
            my_sp |= set(_audit_ids(fam.get(k)))
        my_kin = set(_audit_ids(fam.get("father")) + _audit_ids(fam.get("mother"))
                     + _audit_ids(fam.get("child")))
        for b in sorted(my_sp & my_kin):
            _push("K4", f"{_audit_name(f, cid)} 与 {_audit_name(f, b)} "
                        f"既是配偶又是直系亲属")
    # ---- K2 业师不可能: 业师比学生晚出生 (记忆侧, 不依赖 family) ----
    for cid_s, rec in cache_chars.items():
        try:
            cid = int(cid_s)
        except (TypeError, ValueError):
            continue
        cy = _audit_year(f, cid)
        if cy is None:
            continue
        for mem in (rec.get("memories") or []):
            if (mem.get("type") or "") != "childhood_education_guardian":
                continue
            for v in (mem.get("participants") or {}).values():
                if not isinstance(v, int) or v == cid:
                    continue
                gy = _audit_year(f, v)
                if gy is not None and gy >= cy:
                    _push("K2", f"业师{_audit_name(f, v)} ({gy} 年生) → "
                                f"{_audit_name(f, cid)} ({cy} 年生): 业师晚出生")
                break
    return out


def audit_kin_report(facts, where=""):
    """`audit_kin_lines` 的落盘形态 (v63 问题5): 写 journal.log, 返回条数。

    刻意**不**写进提示词 —— 这是程序能确定性完成的事 (铁律), 且断言可回归。"""
    issues = audit_kin_lines(facts)
    if not issues:
        return 0
    try:
        import llm as _llm
        for s in issues[:12]:
            _llm.log(f"亲缘自检: {s}" + (f" (来自 {where})" if where else ""),
                     detail=True)
    except Exception:
        pass
    return len(issues)



# 恩怨史事件文本中的角色块: \x15ONCLICK:CHARACTER,id \x15TOOLTIP:CHARACTER,id \x15L
# \x15high 称号 \x15!，\x15high 姓 \x15!\x15high 名 \x15!\x15!\x15!\x15!
# (v14 重渲染用 — 只替换两端角色, 保留游戏动词「成为/与/劫掠了…」)
_FEUD_ROLE_RE = re.compile(
    r"\x15ONCLICK:CHARACTER,(\d+)"
    r"(?:\s*\x15TOOLTIP:CHARACTER,\d+)?\s*\x15L\s*"
    r"(?:.*?)\x15!\x15!\x15!\x15!"
)

# v43: change_reason 里出现过的角色 id —— 两端同人即游戏把 TARGET_CHAR 填成 root
# 的退化条目 (见 Facts._rerender_feud_event)。
_FEUD_CHAR_RE = re.compile(r"ONCLICK:CHARACTER,(\d+)")

# v63 第四轮: 家族关系流水里的**劫掠**措辞 —— 游戏本地化
# `house_relation_reason_raid_desc`(劫掠了X)、`_raided_estate_desc`(劫掠了X的庄园)、
# `_raided_estate_attempt_desc`(企图劫掠X的庄园) 三个键共用这三个词根。
# 写入点见 `Facts._house_raid_index` (army_on_actions.txt:761/803-816)。
_RAID_WORDS = ("劫掠", "掠夺", "洗劫")


def _death_sentence(f, cid, killer_pronoun=False, annotated=False, insider=False):
    """角色死亡 → 干净中文句 (死因句含凶手/行刑者/对手嵌入)。

    v45 (档 B): 外层包一层出词登记 (同 `_mem_sentence`)。
    v63: 同时登记本行主语 (`cid` = 死者) —— 行内第三方人名按他算词。
    v75 (凶手点名): insider=True 取内情 (点名凶手) —— 只给《刺客列传》;
    缺省 False = 公开档 (见 `_death_sentence_body`)。"""
    with f.log_names() as lg:
        out = _death_sentence_body(f, cid, killer_pronoun=killer_pronoun,
                                   annotated=annotated, insider=insider)
    return f.index_names(out, lg, owner=cid)


def _death_sentence_body(f, cid, killer_pronoun=False, annotated=False, insider=False):
    """角色死亡 → 干净中文句 (死因句含凶手/行刑者/对手嵌入)。
    v22: death_execution 且行刑者已知时, 处决方式按当时可用选项稳定伪随机
    (斩首/做成神秘的肉/犬决/烧死/食人/献祭) — 存档只记「处决」, 不再千篇一律。
    v24: 凶手为主角时附「（死于X）」(X = 受害者死前最近可知男爵领, 数据无则省略);
    弃用 v20 的「时主角驻X」(主角驻地 ≠ 案发地, 误导模型把刺杀安在主角驻地)。
    v25: 死因句统一走 Facts.death_clause — 暗杀类死因按死法池取具体手法。
    v26: imprison=True — 卒时已囚满一年者写「囚禁N年后…」(处决/狱死)。
    v30: killer_pronoun=True 时凶手称谓缩为「其」— 供《刺客列传》专用 (该篇凶手
    恒为主角, 逐条重复全称谓 14 次; 见 修复方案_菲利普4.md 问题8)。
    v42 (问题5): annotated=True 时并写受害者的**生年/族属/信仰**(凶手为主角时) ——
    年表里「仇人死亡」一条此前只走记忆句「X的仇人Y去世」, 改走死亡记录后
    若不带这些补注, 会丢掉与「谋杀Y（1073年生…）」同等的信息量。
    v75 (凶手点名): insider=True 取内情 (点名凶手) —— 只给《刺客列传》; 缺省
    False = 公开档, 主角未公开的凶杀写成世人的说法「X于<日>死于<地>，神秘死亡。」
    (不点名、不带内情手法), 判据见 `Facts.killer_hidden`。
    """
    rec = (f.cache.get("characters") or {}).get(str(cid)) or {}
    d = rec.get("death") or {}
    if not d:
        return None
    # v42 (问题4): 年表事实行 —— 主角只出名字 (见 Facts.event_name)
    name = f.event_name(cid, date=d.get("date"))
    killer = d.get("killer")
    pid = f.cache.get("player_id")
    # v75: 公开档下主角未公开的凶杀 —— 只写世人看得见的那半句
    hidden = bool(pid is not None and killer is not None and not insider
                  and f.killer_hidden(cid, killer))
    # 施事者名字缺失时用「某人」 (v28b: 统一占位词, 与 name_or 兜底同源)
    clause = f.death_clause(cid, date=d.get("date"), imprison=True, insider=insider)
    if killer_pronoun and killer is not None:
        klabel = f.event_name(killer, date=f.as_of)
        if klabel and klabel in clause:
            clause = clause.replace(klabel, "其")
    if hidden:
        vp = f.victim_place(cid)
        s = (f"{name}于{f.date(d.get('date'))}死于{vp}" if vp
             else f"{name}死于{f.date(d.get('date'))}") + f"，{clause}"
        if annotated:
            note = _victim_marks(f, cid)
            if note:
                s += note
        return s + "。"
    s = f"{name}死于{f.date(d.get('date'))}，{clause}。"
    if pid is not None and killer == pid:
        # v42: 生年/族属/信仰补注 (与 successful_murder 句同式, 见 _timeline)
        if annotated:
            note = _victim_marks(f, cid)
            if note:
                s = s.rstrip("。") + note + "。"
        vp = f.victim_place(cid)
        if vp:
            # v55 (问题2): 去括注 —— 「，死于长安。」
            s = s.rstrip("。") + f"，死于{vp}。"
    return s


def _victim_marks(f, cid):
    """受害者补注「，1073年生，爱沙尼亚人，信东正教」; 无料返回 ''。
    v28 起用于谋杀句, v42 (问题5) 起死亡记录句共用 (两者在年表里互为替代)。
    v55 (问题2): 去括注 —— 补注作同句分句 (旧稿「（1073年生，…）」)。"""
    drec = (f.cache.get("characters") or {}).get(str(cid)) or {}
    by = str(drec.get("birth") or "").split(".")[0] or ""
    cul = f.culture(cid)
    fai = f.faith(cid)
    mark = []
    if by:
        mark.append(f"{by}年生")
    if not is_unknown(cul):
        mark.append(cul)
    if not is_unknown(fai):
        mark.append(f"信{fai}")
    return ("，" + "，".join(mark)) if mark else ""


# v14: 30 个戏剧性模块 — 十年小传按主题切片的事实组织 (研究_戏剧模块化.md)。
# 每个模块 = {模块名: memory type 集} (另有 4 个专题模块 短命皇朝/天下更替/
# 官职任免/死亡谢幕, 由专门渲染器驱动, 不在本表)。type→模块 为纯数据层映射。
MODULE_TABLE = {
    "起家发迹":   {"ascended_throne_memory"},
    "失位让土":   {"lost_title_memory"},
    "开战兴兵":   {"offensive_war", "defensive_war", "joined_allys_war"},
    "战和胜负":   {"battle_won_memory", "battle_lost_memory", "war_won", "war_lost"},
    "战死负伤":   {"witnessed_death_battle", "became_incapable_due_to_battle_concussion",
                   # v78-5: 游戏自己的类别是 negative health injured activity
                   # (不含 coronation) —— 它是一条伤情, 不是加冕事迹
                   "injured_in_crowd_crush_at_coronation_memory"},
    # v78-4 (用户 D3): 人质闭环 —— 旧稿只登记「抓进去」三型, 送还/卒于质所四型
    # 连事件都不生成 (`_hostage_sentence` 现由 facts 侧专表出句)。
    "人质质任":   {"hostage_created_hostage", "hostage_created_warden",
                   "hostage_created_home_court", "hostage_returned_hostage",
                   "hostage_returned_warden", "hostage_returned_home_court",
                   "hostage_died"},
    "囚禁入狱":   {"imprisoned", "imprisoned_other"},
    "获释出狱":   {"released_from_prison_memory"},
    # v32 (马克龙问题1): 越狱单列一档 — 出狱方式二分 (被释放 / 逃脱), 语义不同
    # (游戏 prison_on_actions.txt 与 00_prison_effects.txt 互斥建这两条记忆)
    "越狱脱逃":   {"escaped_from_prison_memory"},
    "刑虐残暴":   {"tortured_memory", "torturer_memory"},
    "受辱含冤":   {"ignored_assault_memory"},
    # v38 (问题1): 强迫/半推半就的性事 —— 用户拍板只收这两档。12 个键 = 施为/受害
    # × (dom/sub) × 体位 (阴道/肛/口) × (noncon/dubcon); Mod 里没有 dom/sub 标记
    # 的旧键也在其中。
    # v59 (问题2, 用户 2026-09-23 拍板): 本模块**只进《列传·好友》《列传·仇人》**
    # (见 MODULE_SLICE 的 ("friend"/"enemy","mid")); 且性事一律不进公开年表
    # (见 `_timeline` 的 `is_sex_event` 闸)。
    "强暴凌辱":   {
        f"had_sex_{side}_player_{dom}{act}_{cons}"
        for side in ("giving", "receiving")
        for dom in ("", "dom_", "sub_")
        for act in ("vaginal_cum_inside", "vaginal_cum_outside", "anal", "oral")
        for cons in ("noncon", "dubcon")
    },
    # v40: 性病传播 (情人疱疹/大痘) —— 传播本身不是性事, 单独成行
    # (本体按期在 lover/consort 之间传播、卖淫、先天)。
    # v59: 「有性事行动可挂的边补在性行为句末」这一档已删除 (载体不存在)。
    "疾病传播":   {"std_transmission"},
    "结仇结怨":   {"became_rivals", "became_grudge"},
    "死敌之仇":   {"became_nemesis"},
    "化仇解怨":   {"stopped_being_rivals"},
    "仇人死亡":   {"rival_died"},
    "结友知交":   {"became_friends"},
    "挚友血盟":   {"became_soulmates", "became_blood_brother"},
    "丧友之恸":   {"friend_died"},
    "婚配联姻":   {"married", "grand_wedding_completed_guest",
                   "had_sex_spouse", "became_lovers_spouse"},
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
    # v78-5 (用户 D6): 加冕族按「主线 / 索求 / 对抗」三档分工, 并把此前**只有模板
    # 没有模块**的 `held_a_coronation_memory` 一并登记 (module=="" 会被 slice_events
    # 放行到所有板块); `injured_in_crowd_crush_at_coronation_memory` 归「战死负伤」
    # (游戏自己的类别是 negative health injured activity, 不含 coronation)。
    "拥戴加冕":   {"became_acclaimed", "witnessed_a_coronation_memory",
                   "held_a_coronation_memory", "crowned_by_hof_memory",
                   "coronation_highlighted_memory", "conquest_oath_memory",
                   "reconquest_oath_memory"},
    "加冕索求":   {"coronation_claim_memory", "coronation_hook_memory",
                   "coronation_alliance_memory", "coronation_friend_memory",
                   "coronation_vassal_levies_memory",
                   "coronation_vassal_taxes_memory",
                   "coronation_cultural_acceptance_memory",
                   "coronation_legitimacy_memory"},
    "加冕对抗":   {"coronation_coup_memory",
                   "coronation_faction_discontent_memory",
                   "coronation_faction_members_memory",
                   "coronation_magnificence_loss_memory"},
    "宴饮失仪":   {"got_the_city_drunk_memory",
                   "defeated_detractor_in_drinking_contest_memory",
                   "was_caught_cheating_in_drinking_contest_memory"},
    # v78-5: 流放/逐出宗族 (旧稿零接管; 与「囚犯遭驱逐」的 `banished` 档口径不同 ——
    # 那一档是「以放逐为条件开释囚犯」, 本档是亲属间放逐/离族, 两者结构互斥)
    "流放逐出":   {"exiled_kin_memory", "exiled_by_kin_memory",
                   "defected_from_kin_memory"},
    "信仰皈依":   {"completed_hajj_memory", "picked_serenity_aspect_memory",
                   "picked_creation_aspect_memory", "faith_changed"},
    # 死亡记录 (death) 不在此表: 由 _timeline 按死者关系并入 仇人死亡/丧友之恸/
    # 丧偶之痛/丧亲之恸 同键去重 (研究_戏剧模块化.md 模块 28)。
}
_TYPE2MODULE = {}
for _m, _ts in MODULE_TABLE.items():
    for _t in _ts:
        _TYPE2MODULE[_t] = _m


# ---------------------------------------------------------------------------
# v59 (问题2, 用户 2026-09-23 拍板): 性事只在《列传·好友》《列传·仇人》里用
# ---------------------------------------------------------------------------
# 用户原话:「保存自愿/半推半就/强迫分类, 但只在好友/仇人列传中使用性交事件」。
# 落实为三道闸 (事实来源一字不改, 变的只是「哪一篇能看到它」):
#   ① `_timeline` 的**年表闸** —— 性事模块不进 `facts["timeline"]`, 于是
#      共享前缀《大事年表》、各篇【本板块大事】、十年主题计数一概不见性事;
#   ② `_character_profiles` 的**档案闸** —— 角色档案的「行迹」不再列性事行;
#   ③ 白名单只给 `("friend","mid")` / `("enemy","mid")` 放行这三个模块。
# 三档分类 (自愿 / 半推半就 / 强迫) 完整保留: 自愿档仍按
# `同房`(配偶) / `相与`(非配偶) 出句, 半推半就与强迫档照 `SEX_MEM_WORDING`。
MODULE_MARRIAGE = "婚配联姻"
MODULE_DUBIOUS = "情变私通"
MODULE_SEXUAL_HARM = "强暴凌辱"
# 性事相关模块集 (年表闸与白名单共用)
MODULE_SEX_MODULES = frozenset({MODULE_MARRIAGE, MODULE_DUBIOUS,
                                MODULE_SEXUAL_HARM})


def is_sex_event(ev_type):
    """该时间线事件类型是否属性事 (按戏剧模块判定, v59)。

    `_timeline` 里自愿档已归并为 `had_sex` (配偶档再换 `had_sex_spouse`),
    两者都在 `MODULE_SEX_MODULES` 内, 故一处判据覆盖三档。"""
    return (_TYPE2MODULE.get(ev_type) or "") in MODULE_SEX_MODULES


# v27: 板块 → 戏剧模块白名单 (研究_戏剧模块化.md 的切片方案落地)。
# 键 = (文章 key, 板块 key); 未列出的组合不收时间线 (该板块不看年表)。
# 目的: 让同一篇的开篇与纪事拿到**不相交**的素材 (此前 6 篇里 5 篇事实块
# 逐字节相同, 等于同一份料发两遍)。
MODULE_SLICE = {
    # 本纪: 开篇 = 家世/受学/信仰; 纪事 = 权力线索 (起家/兵戈/刑狱/恩怨)
    # v59 (问题2): 婚配联姻/情变私通**撤出本纪** —— 与 `研究_戏剧模块化.md`
    # 的模块表 (「18 婚配联姻 → 家室; 19 情变私通 → 家室」) 对齐; 且 v59 起
    # 性事行本就不进年表, 留着这两个模块只会把「成婚/相恋/分手」与权力线索并列。
    # v64 (问题3): `家格宗支` = 别立家族/家族改名的年表事件 (`_house_founding_events`)。
    # 用户 2026-09-25 指认的句子在《本纪·开篇·家世与出身》(「934年5月7日，卡尔别立
    # 顿巴斯氏，为菲利普宗族分支，自成一脉，家格自此改易。」), 故只进本纪开篇;
    # 与纪事不相交 (v27 铁律), 门庭内情仍由《家室列传》承担。
    ("benji", "lead"): {"教化求学", "科考功名", "人质质任",
                        "信仰皈依", "拥戴加冕", "丧亲之恸", "家格宗支"},
    ("benji", "mid"): {"起家发迹", "失位让土", "开战兴兵", "战和胜负",
                       "战死负伤", "囚禁入狱", "获释出狱", "刑虐残暴",
                       "受辱含冤", "拥戴加冕", "结仇结怨", "死敌之仇",
                       "化仇解怨",
                       # v78-5 (用户 D6): 加冕索求/对抗 (宾客在加冕礼上的所得与冲突)
                       # 与流放逐出 (亲属间放逐/离族) 同层进本纪纪事
                       "加冕索求", "加冕对抗", "流放逐出", "宴饮失仪",
                       # v34 (问题8): 添丁是家事也是政治 (继承人/联姻/血统),
                       # 且出生句已带「生父X」——不放进来, 本纪只见子女名单
                       # 而无出生记载, 模型就把生母的生育算成主角得子
                       # (法霍·索丹被写成主角之子即此)。与《家室列传》的分工:
                       # 本纪取年表事实, 家室列传取门庭内情与情事脉络。
                       "添丁进口", "夭折"},
    # 家室: 开篇 = 结缡/情变/丧偶; 纪事 = 生育/夭亡/丧亲/丧友 + 囚禁 (v32 问题1:
    # 公主被囚的监禁者在旧稿里读不到, 模型只能写「后世皆指为伯爵本人」;
    # 只入纪事 — v27 铁律: 同篇开篇与纪事的素材不相交, 开篇的妻妾档案行
    # 本来就带「为X所囚」)
    # 家室: 开篇 = 结缡/情变/丧偶; 纪事 = 生育/夭亡/丧亲/丧友 + 囚禁 (v32 问题1:
    # 公主被囚的监禁者在旧稿里读不到, 模型只能写「后世皆指为伯爵本人」;
    # 只入纪事 — v27 铁律: 同篇开篇与纪事的素材不相交, 开篇的妻妾档案行
    # 本来就带「为X所囚」)
    # v59 (问题2): 这两个模块留在《家室列传》是给**非性事**的关系行用
    # (成婚/相恋/分手/丧偶) —— 门庭内情正是该篇本分; 性事行本身由年表闸全局
    # 挡住 (见 `_timeline`), 不会漏到这里来。
    ("jiashi", "lead"): {"婚配联姻", "情变私通", "丧偶之痛"},
    ("jiashi", "mid"): {"添丁进口", "夭折", "丧亲之恸", "婚配联姻",
                        "情变私通", "丧友之恸", "囚禁入狱", "获释出狱",
                        "越狱脱逃"},
    # 朝局: 开篇 = 天下更替; 纪事 = 兵戈/刑狱/恩怨
    ("chaoju", "lead"): {"起家发迹", "失位让土", "拥戴加冕"},
    ("chaoju", "mid"): {"开战兴兵", "战和胜负", "战死负伤", "囚禁入狱",
                        "获释出狱", "结仇结怨", "死敌之仇", "拥戴加冕",
                        # v78-5 (用户 D6): 同本纪纪事口径
                        "加冕索求", "加冕对抗", "流放逐出",
                        "丧亲之恸"},
    # 群英录纪事: 同朝局纪事口径
    ("qunying", "mid"): {"起家发迹", "失位让土", "开战兴兵", "战和胜负",
                         "囚禁入狱", "获释出狱", "结仇结怨", "死敌之仇",
                         "拥戴加冕",
                         "加冕索求", "加冕对抗", "流放逐出"},
    # 强暴凌辱 (v38, 问题1): 强迫/半推半就的性事 —— 时间线里是「谁对谁做了什么、
    # 在何日」的确定性事实。
    # v59 (问题2, 用户拍板): **只在《列传·好友》《列传·仇人》里用**。故:
    #   · 撤出《阴私录》(旧稿在这里) —— 该篇只留隐事/把柄/知情者;
    #   · 撤出《家室列传》—— 门庭内情仍由「结缡/生育/丧亲」承载,
    #     性事行随年表闸一起不再出现;
    #   · `疾病传播` (v40, 无性事行动可挂的那一档) 同撤 —— 它与性事同源,
    #     留在阴私录等于把性事换个名字写回去。
    ("secrets", "lead"): set(),
    ("secrets", "mid"): set(),
    # 列传: 开篇只给传主档案与关系缘由 (不配年表); 纪事给传主行迹 + 模块切片
    ("friend", "lead"): set(),
    # v59 (问题2): 传主自己的性事 (含配偶同房/私通/强迫) 归其本传纪事 ——
    # 这是全项目唯一使用性事事件的板块。`情变私通` 原就在此, 本轮补三档。
    ("friend", "mid"): {"结友知交", "挚友血盟", "丧友之恸", "结仇结怨",
                        "情变私通", "婚配联姻", "强暴凌辱"},
    ("enemy", "lead"): set(),
    ("enemy", "mid"): {"结仇结怨", "死敌之仇", "化仇解怨", "仇人死亡",
                       "情变私通", "婚配联姻", "强暴凌辱", "结友知交"},
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
    # v38 (问题1): 并入 Carnalitas 的 `had_sex_*` 族 — 强迫/半强迫的受害方与施为方
    # 同属相关角色, 其档案与年表才进得了各篇。
    for m in prec.get("memories") or []:
        _t = str(m.get("type") or "")
        if _t in ("became_lovers", "had_sex") or _t.startswith(_SEX_MEM_PREFIX):
            for v in (m.get("participants") or {}).values():
                if isinstance(v, int) and v != pid:
                    out.setdefault(v, 2)
    return out


# v14: death 记录 (类型 "death", 由 _death_sentence 渲染) 的模块标注 —
# 按死者与主角的关系: 仇人→仇人死亡, 友人→丧友之恸, 配偶→丧偶之痛, 其余→丧亲之恸。
#
# v42 (问题5): 关系集改为**一次扫全库**预算 (`_death_rel_sets`) —— 旧稿每名死者都
# 重扫一次「全库 × 全部记忆」, 而 `*_died` 八类统一进 `deaths` 后死者数增加,
# 逐死者重扫会成倍拉长时间线构建。
def _death_rel_sets(f, pid):
    """主角的仇人/友人 id 集 (按与主角共同出现的相关记忆)。返回 (rivals, friends)。"""
    rivals, friends = set(), set()
    if pid is None:
        return rivals, friends
    for _cid, rec in (f.cache.get("characters") or {}).items():
        for m in rec.get("memories") or []:
            parts = m.get("participants") or {}
            if not any(isinstance(v, int) and v == pid for v in parts.values()):
                continue
            t = m.get("type")
            if t in ("became_rivals", "became_grudge", "became_nemesis"):
                rivals.update(v for v in parts.values() if isinstance(v, int))
            elif t in ("became_friends", "became_soulmates",
                       "became_blood_brother"):
                friends.update(v for v in parts.values() if isinstance(v, int))
    return rivals, friends


def _death_module(f, dead_cid, rivals=None, friends=None):
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
    if rivals is None or friends is None:
        rivals, friends = _death_rel_sets(f, pid)
    if dead_cid in rivals:
        return "仇人死亡"
    if dead_cid in friends:
        return "丧友之恸"
    return "丧亲之恸"


# v42 (问题5): 全部「某人去世」记忆类型 —— 一律按死者 id 归并到死亡记录那一条,
# 不再分「四类走去重 / 四类走通用句」。名单与 style.MEMORY_TEMPLATES 的 `*_died` 同步。
_DIED_TYPES = ("relative_died", "friend_died", "rival_died", "spouse_died",
               "lover_died", "soulmate_died", "best_friend_died", "nemesis_died")

# v58 (问题8): 这几种「亡故」记忆的关系词按**句内主语**算（血亲/姻亲可判者），
# `spouse_died` 另走「丧偶」句形，不入此表。
_REL_DIED_TYPES = ("relative_died", "rival_died", "friend_died", "lover_died",
                   "soulmate_died", "best_friend_died", "nemesis_died")


def _count_zh(n):
    """事物计数中文 (v28b): 一两桩/三桩…十桩/十二桩 (与世系编号 _ordinal_zh 区分)。"""
    digits = "零一二三四五六七八九"
    if n == 2:
        return "两"
    if n < 10:
        return digits[n]
    if n < 20:
        return "十" + (digits[n - 10] if n > 10 else "")
    if n < 100:
        t, r = divmod(n, 10)
        return digits[t] + "十" + (digits[r] if r else "")
    return str(n)


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


# ---------------------------------------------------------------------------
# v30: 正反两方记忆的镜像对识别 (修复方案_菲利普4.md 问题6)
# ---------------------------------------------------------------------------
# 同一件事在存档里有两方各记一条 (甲主动开战/乙被迫应战、胜方赢得战争/败方战败、
# 施刑者行刑/受刑者受刑、新主登位/旧主失位), 文本不同、类型不同, 既有去重键
# (type, date, participants 集) 拦不住, 于是大事年表出现成对重复行。
# 配对一律按**参与者身份**判定 — 菲利普实测 886.12.13 同日有两场互不相干的战斗
# (崔佛↔王景崇 / 帕勒芒↔韦尔尼亚斯), 只按日期+类型会把两场混为一谈。

# 镜像类型对 → 保留优先级 (高者胜, 即「动作发起方」)
_MIRROR_KEEP = {
    "offensive_war": 2, "defensive_war": 1,
    "war_won": 2, "war_lost": 1,
    "battle_won_memory": 2, "battle_lost_memory": 1,
    "torturer_memory": 2, "tortured_memory": 1,
    "ascended_throne_memory": 2, "lost_title_memory": 1,
    # v78-5: 亲属间放逐**同日一对** (放逐者持 exiled_kin / 被放逐者持 exiled_by_kin,
    # 实测 32 条里 20 条成 10 对) —— 不登记会同一件事出两行。
    "exiled_kin_memory": 2, "exiled_by_kin_memory": 1,
    # v56 (§10-E): 相恋双方**各持一条**同型记忆 (participants 互指) —— 旧稿未登记,
    # 于是同一件事出两行正反句 (「郑思齐与任宗本相恋。」+「任宗本与郑思齐相恋。」)。
    "became_lovers": 2,
}
_MIRROR_TYPE_PAIRS = (
    frozenset({"offensive_war", "defensive_war"}),
    frozenset({"war_won", "war_lost"}),
    frozenset({"battle_won_memory", "battle_lost_memory"}),
    frozenset({"torturer_memory", "tortured_memory"}),
    frozenset({"ascended_throne_memory", "lost_title_memory"}),
    frozenset({"became_lovers"}),          # v56 (§10-E): 同型镜像对
    # v78-5: 亲属间放逐同日一对 (放逐者 / 被放逐者各持一条, 槽互指)
    frozenset({"exiled_kin_memory", "exiled_by_kin_memory"}),
)
# 需要带身份槽 (owner + participants) 才能配对/合并的记忆类型
_IDENT_TYPES = frozenset(
    set(_MIRROR_KEEP)
    | {"imprisoned", "imprisoned_other", "released_from_prison_memory",
       "escaped_from_prison_memory",
       "child_born", "first_born", "twins_born", "child_premature",
       "child_stillborn",
       # v78-3 (用户问题2): 盟战与白和也进 ident —— 战事重建 (兴兵↔决胜配对、
       # 补对手/宣战理由/战场) 全靠 ident 里的槽位; 旧稿这三型不在 ident 内,
       # 于是盟战行永远停在「助盟友作战」、白和行连事件都不生成。
       "joined_allys_war", "war_white_peace_attacker",
       "war_white_peace_defender",
       # v78-4: 人质族三视角要 ident 才能归并成一个事件 (`_pair_hostages`)
       "hostage_created_hostage", "hostage_created_warden",
       "hostage_created_home_court", "hostage_returned_hostage",
       "hostage_returned_warden", "hostage_returned_home_court",
       "hostage_died"}
)

_DATE_PREFIX_RE = re.compile(r"^\d+年(?:\d+月\d+日)?，")


def _sex_mirror_partner(a, b):
    """a/b 是否为同一桩性事的正反两方记忆 (v38, 问题1)。

    Carnalitas 的性事记忆对**双方各写一条**: 施为方持 `..._giving_player_...`,
    受害方持 `..._receiving_player_...`, 两条 `sex_partner` 互指且自愿档相同、
    创建日相同 (同一脚本段落内先后创建)。判据即按这三项。
    原始类型键留在 ident["type"] —— 事件本身的 type 已归并为模块档
    (noncon/dubcon 原样, consensual 并为 had_sex)。"""
    ia = sex_mem_info((a.get("ident") or {}).get("type") or a.get("type"))
    ib = sex_mem_info((b.get("ident") or {}).get("type") or b.get("type"))
    if not ia or not ib:
        return False
    if ia["consent"] != ib["consent"]:
        return False
    if ia["role"] == ib["role"]:
        return False          # 同向 (双方都持施为/受害) — 非镜像对
    pa = (a.get("ident") or {}).get("parts") or {}
    pb = (b.get("ident") or {}).get("parts") or {}
    oa = (a.get("ident") or {}).get("owner")
    ob = (b.get("ident") or {}).get("owner")
    va, vb = pa.get(_SEX_PARTNER_SLOT), pb.get(_SEX_PARTNER_SLOT)
    return isinstance(va, int) and isinstance(vb, int) \
        and va == ob and vb == oa


def _mirror_partner(a, b):
    """a/b 是否为同一事件的正反两方记忆 (按参与者身份互指判定)。"""
    ta, tb = a.get("type"), b.get("type")
    # v38 (问题1): 性事记忆对 (双方各一条, 施为方/受害方)
    if _sex_mirror_partner(a, b):
        return True
    if frozenset({ta, tb}) not in _MIRROR_TYPE_PAIRS:
        return False
    pa = (a.get("ident") or {}).get("parts") or {}
    pb = (b.get("ident") or {}).get("parts") or {}
    oa = (a.get("ident") or {}).get("owner")
    ob = (b.get("ident") or {}).get("owner")

    def p(x, k):
        v = x.get(k)
        return int(v) if isinstance(v, int) else None

    if ta == tb == "became_lovers":
        # v56 (§10-E): 同一对相恋的两条记忆 (持有者互为对方记忆的对象槽)
        return p(pa, "new_relation") is not None \
            and p(pa, "new_relation") == ob and p(pb, "new_relation") == oa
    if {ta, tb} == {"offensive_war", "defensive_war"}:
        return p(pa, "other_party") is not None \
            and p(pa, "other_party") == ob and p(pb, "other_party") == oa
    if {ta, tb} == {"war_won", "war_lost"}:
        return p(pa, "winner") is not None and \
            p(pa, "winner") == p(pb, "winner") and \
            p(pa, "loser") == p(pb, "loser")
    if {ta, tb} == {"battle_won_memory", "battle_lost_memory"}:
        w, l = (a, b) if ta == "battle_won_memory" else (b, a)
        pw = (w.get("ident") or {}).get("parts") or {}
        pl = (l.get("ident") or {}).get("parts") or {}
        ow = (w.get("ident") or {}).get("owner")
        ol = (l.get("ident") or {}).get("owner")
        return p(pw, "loser") is not None and p(pw, "loser") == ol \
            and p(pl, "winner") == ow
    if {ta, tb} == {"torturer_memory", "tortured_memory"}:
        t, v = (a, b) if ta == "torturer_memory" else (b, a)
        pt = (t.get("ident") or {}).get("parts") or {}
        pv = (v.get("ident") or {}).get("parts") or {}
        ot = (t.get("ident") or {}).get("owner")
        ov = (v.get("ident") or {}).get("owner")
        return p(pv, "torturer") is not None and p(pv, "torturer") == ot \
            and p(pt, "victim") == ov
    if {ta, tb} == {"ascended_throne_memory", "lost_title_memory"}:
        g, l = (a, b) if ta == "ascended_throne_memory" else (b, a)
        pg = (g.get("ident") or {}).get("parts") or {}
        pl = (l.get("ident") or {}).get("parts") or {}
        og = (g.get("ident") or {}).get("owner")
        ol = (l.get("ident") or {}).get("owner")
        return p(pg, "flavor_character") is not None and \
            p(pg, "flavor_character") == ol and p(pl, "new_holder") == og
    return False


def _mirror_rank(e, pid, pname=""):
    """保留优先级: 主角侧 +2, 其次按发起方 (offensive/won/torturer/登位)。"""
    ident = e.get("ident") or {}
    hero = 0
    if pid is not None and ident.get("owner") == pid:
        hero = 2
    elif pname and _DATE_PREFIX_RE.sub("", e.get("text") or "").startswith(pname):
        hero = 2
    return hero * 10 + _MIRROR_KEEP.get(e.get("type"), 0)


def _drop_mirror_pairs(events, pid, pname=""):
    """删去同一事件的正反两方冗余行 (问题6), 保留主角侧/发起方那一条。"""
    drop = set()
    idx_by_date = {}
    for i, e in enumerate(events):
        if e.get("ident"):
            idx_by_date.setdefault(e.get("date"), []).append(i)
    for _d, idxs in idx_by_date.items():
        for ii in range(len(idxs)):
            i = idxs[ii]
            if i in drop:
                continue
            for jj in range(ii + 1, len(idxs)):
                j = idxs[jj]
                if j in drop:
                    continue
                a, b = events[i], events[j]
                if not _mirror_partner(a, b):
                    continue
                drop.add(i if _mirror_rank(a, pid, pname)
                         < _mirror_rank(b, pid, pname) else j)
                if i in drop:
                    break
    return [e for i, e in enumerate(events) if i not in drop]


# ---------------------------------------------------------------------------
# v78-3 (用户问题2): 战事材料重建 —— 兴兵 ↔ 决胜配对成段, 并补齐
# 对手 / 宣战理由 / 争战目标 / 夺取的领地; 战斗行补地点与对手。
# ---------------------------------------------------------------------------
# 起因: 旧稿用 `style.MEMORY_TEMPLATES` 的七个**单槽**模板 (「{name}主动开战。」
# 「{name}被迫应战。」「{name}赢得战争。」「{name}取胜。」…) —— 记忆里明明带着
# `other_party`/`loser`/`winner`/`war_cb`/`war_title`/`battle_location`,
# 全被丢掉; 且同一次战争的兴兵与决胜是两行互不相认 (`_drop_mirror_pairs` 只按
# **同一日期**配对)。实测菲利普2/崔佛终传: 大事年表 335 条里 75 条是战事行,
# 模型被逼出「失利的对手名, 于本档」「一年之内第七次取胜」这类句子。
# 用户 2026-09-27 拍板 D4 = A 档: **只配对与补细节, 不丢任何事实行**。
_WAR_START_TYPES = ("offensive_war", "defensive_war", "joined_allys_war")
_WAR_END_TYPES = ("war_won", "war_lost",
                  "war_white_peace_attacker", "war_white_peace_defender")
_WAR_MEM_TYPES = frozenset(_WAR_START_TYPES + _WAR_END_TYPES)


def _war_mem_meta(mem):
    """战事记忆的**战略槽** (v78-3): 宣战理由/目标头衔/宣称者/兴兵方/盟友/战场州府。

    建 ident 时顺手摘下 (ident 只带 owner/parts, vars 不带, 配对与出句都要用)。"""
    out = {}
    for v in mem.get("vars") or []:
        fl = v.get("flag")
        ident = v.get("identity")
        if fl == "war_cb":
            out["cb"] = str(v.get("value") or "")
        elif fl == "war_title" and isinstance(ident, int):
            out["title"] = ident
        elif fl == "war_claimant" and isinstance(ident, int):
            out["claimant"] = ident
        elif fl == "war_attacker" and isinstance(ident, int):
            out["attacker"] = ident
        elif fl == "war_ally" and isinstance(ident, int):
            out["ally"] = ident
        elif fl == "battle_location" and isinstance(ident, int):
            out["loc"] = ident
    return out


def _war_cb_word(f, cb):
    """`war_memory_cb_*` → 中文战名 (查本地化表); 查不到返回 '' (宁缺不直出裸键)。"""
    cb = str(cb or "")
    if not cb:
        return ""
    try:
        w = L.loc(getattr(f, "table", None) or {}, cb)
    except Exception:
        w = ""
    if not w or w == "战争":          # `war_memory_cb_fallback` 的正文就是「战争」
        return ""
    return w


def _war_slots(f, ev):
    """战事事件 → {"sides", "atk", "dfd", "cb", …} 或 None (v78-3)。

    `sides` = 交战双方 id 集 (配对键的第一段), `cb` = 宣战理由 (第二段)。"""
    ident = ev.get("ident") or {}
    if not ident:
        return None
    parts = {k: v for k, v in (ident.get("parts") or {}).items()
             if isinstance(v, int)}
    owner = ident.get("owner")
    meta = ident.get("war") or {}
    t = ev.get("type")
    cb = str(meta.get("cb") or "")
    atk_v = meta.get("attacker")
    if t == "offensive_war":
        opp = parts.get("other_party")
        if not isinstance(owner, int) or not isinstance(opp, int):
            return None
        return {"sides": frozenset({owner, opp}), "atk": owner, "dfd": opp,
                "cb": cb, "title": meta.get("title"),
                "claimant": meta.get("claimant")}
    if t == "defensive_war":
        opp = parts.get("other_party")
        if not isinstance(owner, int) or not isinstance(opp, int):
            return None
        atk = atk_v if isinstance(atk_v, int) else opp
        return {"sides": frozenset({owner, opp}), "atk": atk, "dfd": owner,
                "cb": cb, "title": meta.get("title"),
                "claimant": meta.get("claimant")}
    if t == "joined_allys_war":
        ally, enemy = parts.get("ally"), parts.get("enemy")
        if not isinstance(ally, int) or not isinstance(enemy, int):
            return None
        atk = atk_v if isinstance(atk_v, int) else enemy
        return {"sides": frozenset({ally, enemy}), "ally": ally, "enemy": enemy,
                "atk": atk, "dfd": enemy if atk == ally else ally, "cb": cb,
                "title": meta.get("title")}
    if t in ("war_won", "war_lost"):
        w, l = parts.get("winner"), parts.get("loser")
        if not isinstance(w, int):
            w = owner if t == "war_won" and isinstance(owner, int) else None
        if not isinstance(l, int):
            l = owner if t == "war_lost" and isinstance(owner, int) else None
        if not isinstance(w, int) or not isinstance(l, int):
            return None
        return {"sides": frozenset({w, l}), "winner": w, "loser": l,
                "atk": atk_v if isinstance(atk_v, int) else w, "dfd": l, "cb": cb,
                "title": meta.get("title")}
    if t in ("war_white_peace_attacker", "war_white_peace_defender"):
        a, d = parts.get("attacker"), parts.get("defender")
        if not isinstance(a, int):
            a = owner if t == "war_white_peace_attacker" else None
        if not isinstance(d, int):
            d = owner if t == "war_white_peace_defender" else None
        if not isinstance(a, int) or not isinstance(d, int):
            return None
        return {"sides": frozenset({a, d}), "atk": a, "dfd": d, "white": True,
                "cb": cb, "title": meta.get("title")}
    return None


def _war_title_gain(f, winner, loser, d0, d1):
    """胜者从败者手里**取得的头衔名** (v78-3): 败者的 `lost_title_memory`
    的 `new_holder` == 胜者、日期落在 [d0, d1] (与恩怨录的夺地判据同源)。"""
    if not isinstance(winner, int) or not isinstance(loser, int):
        return []
    rec = (f.cache.get("characters") or {}).get(str(loser)) or {}
    out = []
    for m in rec.get("memories") or []:
        if (m.get("type") or "") != "lost_title_memory":
            continue
        if (m.get("participants") or {}).get("new_holder") != winner:
            continue
        d = str(m.get("creation_date") or "")
        if d0 and d and cl.date_key(d) < cl.date_key(d0):
            continue
        if d1 and d and cl.date_key(d) > cl.date_key(str(d1)):
            continue
        tid = next((v.get("identity") for v in (m.get("vars") or [])
                    if v.get("flag") == "landed_title" and v.get("identity")), None)
        nm = f.title(tid) if tid else ""
        if nm and nm not in out:
            out.append(nm)
    return out


def _war_start_clause(f, ev, sl):
    """兴兵小句 (不含日期与句号) —— 对手/战名/争战目标/宣称者按槽位写出。"""
    t = ev.get("type")
    d = ev.get("date")
    owner = (ev.get("ident") or {}).get("owner")
    cb = _war_cb_word(f, sl.get("cb"))
    me = f.event_name(owner, date=d) or ""
    tname = f.title(sl.get("title")) if sl.get("title") else ""
    if t == "offensive_war":
        opp = f.event_name(sl["dfd"], date=d) or ""
        s = f"{me}以{cb}向{opp}开战" if cb else f"{me}向{opp}开战"
        if tname:
            s += f"，目标是{tname}"
        cl = sl.get("claimant")
        if isinstance(cl, int) and cl != owner:
            cn = f.event_name(cl, date=d) or ""
            if cn:
                s += f"，为{cn}索取{tname}的宣称" if tname else f"，为{cn}索取宣称"
        return s
    if t == "defensive_war":
        atk = f.event_name(sl["atk"], date=d) or ""
        s = f"{atk}以{cb}来攻，{me}应战" if cb else f"{atk}来攻，{me}应战"
        if tname:
            s += f"，目标为{tname}"
        return s
    # joined_allys_war
    ally = f.event_name(sl.get("ally"), date=d) or ""
    enemy = f.event_name(sl.get("enemy"), date=d) or ""
    s = f"{me}随{ally}出战，对抗{enemy}"
    if cb:
        s += f"，此役为{cb}"
    return s


def _war_end_clause(f, ev, sl, d0):
    """决胜小句 (不含日期与句号)。"""
    t = ev.get("type")
    d = ev.get("date")
    if t in ("war_won", "war_lost"):
        win = t == "war_won"
        me = f.event_name(sl["winner"] if win else sl["loser"], date=d) or ""
        foe = f.event_name(sl["loser"] if win else sl["winner"], date=d) or ""
        s = f"{me}战胜{foe}" if win else f"{me}败于{foe}"
        d1 = None
        try:
            _y, _m, _dd = (int(x) for x in str(d).split(".")[:3])
            d1 = f"{_y + 2}.{_m}.{_dd}"
        except Exception:
            d1 = None
        gains = _war_title_gain(f, sl["winner"], sl["loser"], d, d1)
        if gains:
            s += ("，夺取" if win else "，失") + "、".join(gains[:2])
            if len(gains) > 2:
                s += f"等{len(gains)}地"
        return s
    # 白和: 双方各自持一条记忆, 以持有者为主语
    owner = (ev.get("ident") or {}).get("owner")
    me = f.event_name(owner, date=d) or ""
    other = sl["dfd"] if owner == sl["atk"] else sl["atk"]
    onm = f.event_name(other, date=d) or ""
    return f"{me}与{onm}以无条件和平结束"


# ---------------------------------------------------------------------------
# v78-4 (用户 D3): 人质闭环的合并
# ---------------------------------------------------------------------------
def _pair_hostages(events, f):
    """人质「送出 → 送还/卒于质所」并成一行; 三视角去重 (v78-4)。

    依据 `docs/调研_v78_人质闭环.md`:
      · 一次为质在同一条 on_action 里连写**三条**视角记忆 (人质/监管人/原属宫廷),
        故必须按 (三元组, 日期) 先归并成一个事件, 否则同一件事出 1–3 行;
      · hold 键 = `(hostage, home_court)` —— 监管人会变 (实测 5 例), 原属宫廷稳定;
      · 重复为质支持 (线性扫描: 上一次送还之后的起始自成新 hold);
      · `hostage_died` 是该 hold 的**结束事件** (只有监管人视角);
      · 收口**只用正面硬证**: 「至末档仍在质」须人质当前宫廷即监管人宫廷、
        且入宫廷日 == 起始日; 否则只写起始句 (作废路径零留痕, 见调研 §5.3)。"""
    if not events:
        return events
    recs = []
    for i, e in enumerate(events):
        t = e.get("type")
        if t not in _HOSTAGE_MEM_TYPES:
            continue
        ident = e.get("ident") or {}
        owner = ident.get("owner")
        parts = ident.get("parts") or {}
        sl = _hostage_slots(f, owner, t, parts, e.get("date"))
        if sl is None:
            continue
        role, nms, ids = sl
        if not isinstance(ids.get("hostage"), int):
            continue
        recs.append({"i": i, "type": t, "role": role, "phase": _HOSTAGE_MEMS[t][1],
                     "date": str(e.get("date") or ""), "ids": ids, "nms": nms,
                     "owner": owner})
    if not recs:
        return events
    pid = f.cache.get("player_id")
    # ① 同 (三元组, 日期, 阶段) 的多视角归并: 主角视角优先, 其次原属宫廷/人质/监管人
    _pref = {"home_court": 0, "hostage": 1, "warden": 2}
    groups = {}
    for r in recs:
        key = (r["date"], r["phase"], tuple(sorted(
            (k, v) for k, v in r["ids"].items() if isinstance(v, int))))
        groups.setdefault(key, []).append(r)
    kept, drop = [], set()
    for key, rows in groups.items():
        rows.sort(key=lambda r: (0 if (pid is not None and r["owner"] == pid) else 1,
                                 _pref.get(r["role"], 9)))
        kept.append(rows[0])
        for r in rows[1:]:
            drop.add(r["i"])
    # ② 按人质分组做线性配对
    kept.sort(key=lambda r: (r["ids"]["hostage"], cl.date_key(r["date"]),
                             0 if r["phase"] == "start" else 1))
    by_hostage = {}
    for r in kept:
        by_hostage.setdefault(r["ids"]["hostage"], []).append(r)
    for _hid, rows in by_hostage.items():
        open_holds = []
        for r in rows:
            if r["phase"] == "start":
                open_holds.append(r)
                continue
            cand = [h for h in open_holds if h["date"] <= r["date"]
                    and h["ids"] == r["ids"]]
            if not cand:
                cand = [h for h in open_holds if h["date"] <= r["date"]
                        and h["ids"].get("home_court") == r["ids"].get("home_court")]
            if not cand:
                cand = [h for h in open_holds if h["date"] <= r["date"]]
            if not cand:
                # 起始记忆被缓存剪除 ⇒ 只写结局句 (独立成行)
                e = events[r["i"]]
                tail_tpl = (_HOSTAGE_RETURN_ONLY if r["phase"] == "end"
                            else _HOSTAGE_DIED).get(r["role"])
                nms = dict(r["nms"], owner=r["nms"].get(r["role"]) or "")
                if tail_tpl and nms["owner"]:
                    e["text"] = f"{f.date(r['date'])}，{tail_tpl.format(**nms)}"
                continue
            hold = max(cand, key=lambda h: cl.date_key(h["date"]))
            open_holds.remove(hold)
            a, z = events[hold["i"]], events[r["i"]]
            nms = dict(hold["nms"], owner=hold["nms"].get(hold["role"]) or "")
            head = (_HOSTAGE_START.get(hold["role"]) or "").format(**nms) if nms["owner"] else ""
            if not head:
                continue
            span = _prison_span(hold["date"], r["date"])
            if r["phase"] == "end":
                tail = (_HOSTAGE_RETURN.get(hold["role"]) or "").format(
                    span=span or f.date(r["date"]), **nms)
            else:
                exec_like = (str((((f.cache.get("characters") or {})
                                   .get(str(hold["ids"]["hostage"])) or {})
                                  .get("death") or {}).get("reason") or "")
                             == "death_hostage_execution")
                tpl = (_HOSTAGE_EXEC if exec_like else _HOSTAGE_DIED).get(hold["role"]) or ""
                tail = tpl.format(date=f.date(r["date"]), **nms)
            a["text"] = f"{f.date(hold['date'])}，{head.rstrip('。')}{tail.rstrip('。')}。"
            drop.add(r["i"])
        # ③ 未被配对的起始: 有宫廷硬证才收「至末档仍在…」, 否则只写起始句
        for hold in open_holds:
            a = events[hold["i"]]
            nms = dict(hold["nms"], owner=hold["nms"].get(hold["role"]) or "")
            if not nms["owner"]:
                continue
            head = (_HOSTAGE_START.get(hold["role"]) or "").format(**nms)
            body = head.rstrip("。")
            if _hostage_court_held(f, hold["ids"].get("hostage"),
                                   hold["ids"].get("warden"), hold["date"]):
                tpl = _HOSTAGE_HELD.get(hold["role"]) or ""
                body += tpl.format(bound=f._prison_bound(), **nms).rstrip("。")
            a["text"] = f"{f.date(hold['date'])}，{body}。"
    if not drop:
        return events
    return [e for i, e in enumerate(events) if i not in drop]


def _pair_war_events(events, f):
    """兴兵 ↔ 决胜配对成一段 + 战斗行补地点与对手 (v78-3, A 档: 只合并与补料)。

    · 配对键 = (交战双方 id 集, 宣战理由); 决胜取**不早于兴兵日的最早一条**;
    · 合成行锚在**兴兵日**, 句式为「{兴兵日}，{兴兵句}；{决胜日}，{决胜句}。」
      (同日则不重复日期); 决胜行整条删去 (它已并入本段);
    · 找不到决胜的战争只写兴兵句 (照旧, **不写**「胜负未见记载」) —— 白和与
      「尚未结束」都在此列, 但白和现在也是可配对的一种结局;
    · 战斗行 (`battle_won_memory`/`battle_lost_memory`) 改写为
      「{name}在{地点}之战中战胜/败于{对手}」 —— 地点取 `battle_location` 州府名。
    """
    starts, ends = [], []
    for i, e in enumerate(events):
        t = e.get("type")
        if t in _WAR_START_TYPES:
            sl = _war_slots(f, e)
            if sl:
                starts.append((i, sl))
        elif t in _WAR_END_TYPES:
            sl = _war_slots(f, e)
            if sl:
                ends.append((i, sl))
    used, drop = set(), set()
    for i, st in starts:
        d0 = str(events[i].get("date") or "")
        best = None
        for j, en in ends:
            if j in used or en["sides"] != st["sides"]:
                continue
            dj = str(events[j].get("date") or "")
            if d0 and dj and cl.date_key(dj) < cl.date_key(d0):
                continue
            if st.get("cb") and en.get("cb") and st["cb"] != en["cb"]:
                continue
            if best is None or cl.date_key(dj) < cl.date_key(
                    str(events[best[0]].get("date") or "")):
                best = (j, en)
        if best is None:
            # 找不到决胜: 只补兴兵句 (对手/战名/目标), **不写**「胜负未见记载」
            head = _war_start_clause(f, events[i], st)
            if head:
                events[i]["text"] = f"{f.date(d0)}，{head}。"
            continue
        j, en = best
        used.add(j)
        drop.add(j)
        head = _war_start_clause(f, events[i], st)
        tail = _war_end_clause(f, events[j], en, d0)
        dj = str(events[j].get("date") or "")
        if dj and dj != d0:
            body = f"{head}；{f.date(dj)}，{tail}"
        else:
            body = f"{head}；{tail}"
        events[i]["text"] = f"{f.date(d0)}，{body}。"
    # 未被配对的决胜行 (兴兵行已定格的镜像、兴兵记忆被回收等) 同样补出对手与得失
    for j, en in ends:
        if j in used:
            continue
        tail = _war_end_clause(f, events[j], en, None)
        dj = str(events[j].get("date") or "")
        if tail:
            events[j]["text"] = f"{f.date(dj)}，{tail}。"
    # 战斗行补地点与对手
    for e in events:
        t = e.get("type")
        if t not in ("battle_won_memory", "battle_lost_memory"):
            continue
        sl = _war_slots(f, e)
        _ = sl
        ident = e.get("ident") or {}
        parts = ident.get("parts") or {}
        meta = ident.get("war") or {}
        owner = ident.get("owner")
        d = e.get("date")
        me = f.event_name(owner, date=d) or ""
        if not me:
            continue
        if t == "battle_won_memory":
            foe = f.event_name(parts.get("loser"), date=d) or ""
            verb = "战胜"
        else:
            foe = f.event_name(parts.get("winner"), date=d) or ""
            verb = "败于"
        loc = _province_label(f, meta.get("loc")) if meta.get("loc") else ""
        if loc and foe:
            e["text"] = f"{f.date(d)}，{me}在{loc}之战中{verb}{foe}。"
        elif foe:
            e["text"] = f"{f.date(d)}，{me}{verb}{foe}。"
        elif loc:
            e["text"] = f"{f.date(d)}，{me}在{loc}之战中{'取胜' if verb == '战胜' else '失利'}。"
    return [e for i, e in enumerate(events) if i not in drop]


# ---------------------------------------------------------------------------
# v30: 入狱与获释合并 (修复方案_菲利普4.md 问题5)
# ---------------------------------------------------------------------------
# 原状是一条监禁拆成两行: 「873年5月13日，埃里克尔·霍达兰被囚。」+
# 「873年5月16日，埃里克尔·霍达兰获释出狱。」(菲利普本轮 7 对)。
# 现按 被囚者 → 其后最近一次获释 配对, 合成为
# 「873年5月13日，崔佛·菲利普囚禁埃里克尔·霍达兰，3日后获释。」
# 双视角 (被囚者自身的 imprisoned / 施囚者的 imprisoned_other) 也只留一条。

def _prison_span(d0, d1):
    """两日期之间的时长词 («当日»/«3日»/«8个月»/«4年3个月»); 非法/逆序返回 ''。
    词形见 style.FACT_WORDING 的 prison_* 项。"""
    W = _style.FACT_WORDING
    try:
        a = datetime.date(*(int(x) for x in str(d0).split(".")[:3]))
        b = datetime.date(*(int(x) for x in str(d1).split(".")[:3]))
    except Exception:
        return ""
    if b < a:
        return ""
    days = (b - a).days
    if days == 0:
        return W["prison_same_day"]
    if days < 31:
        return W["prison_days"].format(n=days)
    months = (b.year - a.year) * 12 + (b.month - a.month) \
        - (1 if b.day < a.day else 0)
    if months < 12:
        return W["prison_months"].format(n=months)
    y, m = divmod(months, 12)
    if m:
        return W["prison_years_months"].format(y=y, m=m)
    return W["prison_years"].format(y=y)


def _enslaved_in_span(f, victim, jailer, d0, d1=None):
    """victim 在囚期 [d0, d1] 内是否被没为奴隶 (v35, 问题4)。

    owner 取监禁者 (`jailer`), 缺省取主角 —— Carnalitas 的「奴役」互动
    (`carn_enslave_interaction`) 只对 `is_imprisoned_by = actor` 的囚犯开放,
    故奴役者恒为监禁者本人。判据用逐档差分的 `cache["enslavements"]`。

    **容差**: 快照日一律是 1 月 1 日, 所以「873 年 6 月囚禁、8 月释放」这条链
    在差分记录里可能落到 874.1.1 那一档 (德圣塔实测: 12 名奴隶全记 874.1.1,
    而囚期是 873.6.2–873.8.1)。因此关系起点晚于出狱日**不超过一年**仍算命中;
    同样, 关系终点早于入狱日不超过一年也仍算命中。超过一年即判不相干。

    命中返回该记录 (调用方只判真假), 未命中返回 None。"""
    if victim is None:
        return None
    owner = jailer
    if owner is None:
        owner = f.cache.get("player_id")
    if owner is None:
        return None
    rec = (f.cache.get("enslavements") or {}).get(f"{owner}>{victim}")
    if not isinstance(rec, dict):
        return None
    lo = cl.date_key(str(d0)) if d0 else None
    hi = cl.date_key(str(d1)) if d1 else None
    fs, la = rec.get("first_seen"), rec.get("lost_at")
    fs_k = cl.date_key(str(fs)) if fs else None
    la_k = cl.date_key(str(la)) if la else None
    # 两端都缺 → 无法判定
    if fs_k is None and la_k is None:
        return None
    # 容差 = 一年 (快照日一律 1 月 1 日, 见上); 两端比较都在年一级做
    if la_k is not None and lo is not None and la_k[0] + 1 < lo[0]:
        return None                 # 囚禁开始前一年多已不是奴隶
    if fs_k is not None and hi is not None and fs_k[0] > hi[0] + 1:
        return None                 # 出狱一年多之后才成为奴隶
    return rec


# v42 (问题3): 刑虐刑名 → 并入囚禁句时的出狱缘由键。阉割与致盲**必然与释放同日**
# (本档 22 条 torturer_memory 实证: castrated 10 + castrated_beardless 2 + blind 9
# 共 21 例全部同日释放; 唯一不同日的是普通 `torture`)。故只在「刑虐日 == 释放日」
# 时并入, 普通折磨/断肢/毁容一律自成一行。
_PUNISH_RELEASE_KEYS = {
    "castrated": "prison_punish_castrated",
    "castrated_beardless": "prison_punish_beardless",
    "blind": "prison_punish_blinded",
    "blinded": "prison_punish_blinded",
    "torture": "prison_punish_generic",
    "disfigured": "prison_punish_generic",
    "maim_arm": "prison_punish_generic",
    "maim_leg": "prison_punish_generic",
}

# v42 (问题6): 「囚期以死亡收口」时判为**刑杀**的死因 (其余写「死于狱中」)
_PRISON_EXEC_REASONS = frozenset({
    "death_execution", "death_punishment", "death_imprisonment",
    "death_dungeon", "death_eradicated",
})


def _punishment_on(events, victim, date):
    """victim 在 date 这一日的刑虐事件 → (FACT_WORDING 的模板键, 事件下标); 无则 None。

    判据只有「被刑者相同 + 日期相同」—— 不硬编码刑名, 于是普通折磨 (诺兰档
    安苏莎 1103.7.16 受折磨、7.19 才获释) 天然落选, 不会把两件事并成一件。"""
    for i, e in enumerate(events):
        if e.get("type") not in ("torturer_memory", "tortured_memory"):
            continue
        if str(e.get("date") or "") != str(date or ""):
            continue
        ident = e.get("ident") or {}
        parts = ident.get("parts") or {}
        owner = ident.get("owner")
        v = parts.get("victim") if e.get("type") == "torturer_memory" \
            else owner
        if isinstance(v, int) and v == victim:
            kind = ident.get("torture_kind") or "torture"
            return (_PUNISH_RELEASE_KEYS.get(kind, "prison_punish_generic"), i)
    return None


def _war_end_with(events, victim, jailer, date):
    """同日「该被囚者的战争结束」事件 (v56 问题2) → (事件下标, 胜者 id) 或 None。

    判据 (用户拍板案 A): 事件日 == 出狱日, 且一侧是 victim、另一侧是 jailer:
      · `war_won`  (胜者视角, parts.loser == victim);
      · `war_lost` (败者视角, owner == victim 且 parts.winner == jailer)。
    两条记忆互为镜像, 年表只留一条 (见 `_MIRROR_KEEP`), 故两侧都认。
    jailer 未知时只认 victim 为败方的战争。
    实测 (斯卡利茨): 全档 469 例同日入狱+获释中 35 例如此, 监禁者全为玩家。"""
    dk = cl.date_key(str(date)) if date else None
    for i, e in enumerate(events):
        t = e.get("type")
        if t not in ("war_won", "war_lost"):
            continue
        if dk is not None and cl.date_key(str(e.get("date"))) != dk:
            continue
        ident = e.get("ident") or {}
        parts = ident.get("parts") or {}
        owner = ident.get("owner")
        winner = parts.get("winner")
        loser = parts.get("loser")
        if t == "war_won":
            if loser == victim and (jailer is None or winner == jailer):
                return (i, winner)
        else:
            if owner == victim and (jailer is None or winner == jailer):
                return (i, winner)
    return None


def _pair_imprisonments(events, f, pid, pname=""):
    """同一被囚者的入狱与获释合成一行 (问题5); 双视角同一囚禁事件只留一条。"""
    ins, outs = [], []
    for i, e in enumerate(events):
        t = e.get("type")
        ident = e.get("ident") or {}
        parts = ident.get("parts") or {}
        owner = ident.get("owner")
        if t in ("imprisoned", "imprisoned_other"):
            victim = owner if t == "imprisoned" else parts.get("imprisoned")
            jailer = parts.get("imprisoner") if t == "imprisoned" else owner
            if isinstance(victim, int):
                ins.append({"idx": i, "victim": victim, "jailer": jailer,
                            "date": e.get("date"), "hero": owner == pid,
                            "actor": t == "imprisoned_other"})
        elif t in ("released_from_prison_memory", "escaped_from_prison_memory"):
            # v32 (问题1): 出狱方式二分 — 被释放 / 逃脱, 两者由引擎互斥建立
            # (prison_on_actions.txt 未置逃狱旗标才建 released)
            if isinstance(owner, int):
                outs.append({"idx": i, "victim": owner,
                             "jailer": parts.get("imprisoner"),
                             "date": e.get("date"),
                             "escape": t == "escaped_from_prison_memory"})
    # v34 (问题7): 释放记忆缺失时的补证 — 逐档 prison_data 区间记下「哪一档起不在押」,
    # 该档日期即出狱日期 (游戏只在囚禁者主动释放时写 released 记忆; 家soft house_arrest
    # 之外的翻档常缺记忆, 旧稿因此把已出狱者写成「一直关押」)。
    for r in ins:
        victim = r["victim"]
        if any(o["victim"] == victim for o in outs):
            continue
        srec = (f.cache.get("characters") or {}).get(str(victim)) or {}
        # v78 (问题1): 区间闭合日只是**观测界** —— `Facts.prison_exit` 已把「死于区间
        # 之内」判为刑杀/狱中死 (死日 > 闭合日者不算, 那人是先出狱、日后才死)。
        # 该情形**不造出狱事件**, 交给下方死亡收口句 (旧稿一律按获释出句: 浩二
        # 902.8.18 那 45 人因此全被写成「尽数获释」, 实为 39 人同日处决)。
        _exit = f.prison_exit(victim, r["jailer"], r["date"])
        if _exit["kind"] in ("executed", "died_in_prison", "devoured"):
            continue
        for iv in srec.get("prison_history") or []:
            if not iv.get("to"):
                continue
            if cl.date_key(str(iv["to"])) < cl.date_key(str(r["date"])):
                continue
            if cl.date_key(str(iv["to"])) > cl.date_key(str(r["date"])):
                outs.append({"idx": -1, "victim": victim,
                             "jailer": iv.get("imprisoner"),
                             "date": iv["to"], "escape": False,
                             "from_prison_data": True})
            break
    if not ins:
        return events
    # v63 (问题1): 同日同监禁者的人数 —— 群体俘获判据 (见 `Facts.capture_manner` ⓪)。
    # 数的是**事件面**里当天入狱的人数 (双视角都算), 而不是回查记忆库: 实测
    # 907.1.16 那七人里六人已死、其 `imprisoned` 记忆被引擎回收, 回查只能数到 1 人。
    _cluster = {}
    for r in ins:
        _cluster[(str(r["date"]), r["jailer"])] = \
            _cluster.get((str(r["date"]), r["jailer"]), 0) + 1
    # v63 (问题1): 与施囚者侧 `imprisoned_other` 记忆的人数取较大值 —— 被囚者
    # 死亡后其 `imprisoned` 记忆被引擎回收, 事件面会少算 (907.1.16 事件面 6 人、
    # 施囚者侧 7 条), 而群体俘获判据正需要这个人数。
    _side = {}
    try:
        _side = f.imprison_batch_sizes()
    except Exception:
        _side = {}
    for r in ins:
        _k = (str(r["date"]), r["jailer"])
        r["n"] = max(_cluster.get(_k, 1), _side.get(_k, 0))
    drop = set()
    by_victim = {}
    for r in ins:
        by_victim.setdefault(r["victim"], []).append(r)
    for victim, rows in by_victim.items():
        # 1) 同一囚禁事件的双视角合一 (主角侧优先, 其次施囚者视角带出囚禁者)
        groups = {}
        for r in rows:
            groups.setdefault((r["date"], r["jailer"]), []).append(r)
        kept = []
        for _key, group in groups.items():
            group.sort(key=lambda r: (0 if r["hero"] else 1,
                                      0 if r["actor"] else 1))
            kept.append(group[0])
            for r in group[1:]:
                drop.add(r["idx"])
        # 2) 入狱 → 其后最近一次获释 (囚禁者两侧一致时更严)
        kept.sort(key=lambda r: cl.date_key(str(r["date"])))
        releases = sorted((o for o in outs if o["victim"] == victim),
                          key=lambda o: cl.date_key(str(o["date"])))
        used = set()
        for r in kept:
            out = None
            for o in releases:
                if o["idx"] in used:
                    continue
                if cl.date_key(str(o["date"])) < cl.date_key(str(r["date"])):
                    continue
                if r["jailer"] is not None and o["jailer"] is not None \
                        and r["jailer"] != o["jailer"]:
                    continue
                out = o
                break
            # v30: 称谓口径与 _mem_sentence 一致 (person_label 不传日期) —
            # 传日期会按事件当日头衔取词, 同篇内同一人出现两种称谓
            # v42 (问题4): 改走 event_name —— 主角只出名字 (旧稿取 as_of 末档头衔,
            # 1075 年的囚禁行因此写成 1117 年才有的「神圣罗马帝国巴西琉斯」)
            vn = f.event_name(victim, date=f.as_of)
            if not vn:
                continue
            jn = ""
            if r["jailer"] is not None:
                jn = f.event_name(r["jailer"], date=f.as_of)
            W = _style.FACT_WORDING
            # v63 (问题1): 有硬证时才写获取方式 (diarchy / 战阵俘获 / 批量擒获),
            # 判不出时维持裸「囚禁」——方式词只在程序确知时出现。
            _cm, _cm_note = ("unknown", "")
            try:
                _cm, _cm_note = f.capture_manner(victim, r["jailer"], r["date"],
                                                 cluster_n=r.get("n") or 1)
            except Exception:
                _cm, _cm_note = ("unknown", "")
            if _cm == "diarchy":
                body = W["prison_captured_diarch"].format(jailer=jn or "其监禁者",
                                                          victim=vn)
            elif _cm in ("battle", "battle_poi"):
                body = W["prison_captured_battle"].format(jailer=jn or "其监禁者",
                                                          victim=vn)
            elif _cm == "raid":
                body = W["prison_raid_captured"].format(jailer=jn or "其监禁者",
                                                        victim=vn)
            elif _cm == "not_battle" and jn:
                # 未成年被囚 ⇒ 非战败俘获; 只写「拘押」并点出当时年龄
                _age = f._age_at(victim, r["date"]) if hasattr(f, "_age_at") else None
                _nm = W["prison_note_age"].format(victim=vn, n=_age) \
                    if _age is not None else vn
                body = W["prison_batch_seized"].format(jailer=jn, victim=_nm)
            elif _cm == "batch" and jn:
                # 批量入狱必为军事/诛族行动 (非司法逮捕), 但破城与战败不可分 ——
                # 措辞到此为止, 不写方式 (见 `capture_manner` 的档位表)。
                body = W["prison_batch_seized"].format(jailer=jn, victim=vn)
            else:
                body = W["prison_jailed"].format(jailer=jn, victim=vn) if jn \
                    else W["prison_held"].format(victim=vn)
            head = body          # v54: 句首「X囚禁Y」—— 尾巴即结局, 折叠按尾巴分组
            o_kind = "other"     # v54: 结局**族** (同日折叠的一致性判据)
            # v78 (D2): 折叠行改按「结局族 × 时长」计数, 故本行必须把时长词带出去
            # (用户拍板: 关押时段写「几年/几个月后」, 不写终止关押日期)。
            _final_span = ""
            # v35 (问题4): 出狱缘由先问「这一步是不是没为奴隶」——
            # Carnalitas 的 carn_enslave_effect 在奴役的同一刻 release_from_prison,
            # 所以那句「释放」记忆常是「没为奴隶」而不是「获释」。
            owned = _enslaved_in_span(f, victim, r["jailer"],
                                      r["date"], out["date"] if out else None)
            if out is not None:
                used.add(out["idx"])
                drop.add(out["idx"])
                span = _prison_span(r["date"], out["date"])
                same = span == W["prison_same_day"]
                _final_span = span
                # v42 (问题3): 阉割/致盲与释放同日 —— 刑名即出狱缘由, 并入本行
                pun = (None if out.get("escape")
                       else _punishment_on(events, victim, out["date"]))
                # v56 (问题2, 用户拍板案 A): 同日「入狱＋获释」且同日该被囚者的
                # 战争结束 —— 此事不是「抓了又放」而是战末俘获, 改写为战胜句并
                # 吃掉同日那条 war_won 行 (两行不再重复)。
                _war = (_war_end_with(events, victim, r["jailer"], out["date"])
                        if same and not out.get("escape") else None)
                if _war is not None:
                    drop.add(_war[0])
                    _wn = f.event_name(_war[1], date=f.as_of) \
                        if isinstance(_war[1], int) else ""
                    # v63 (问题1): 战末俘获并入统一的战阵俘获措辞 —— 旧稿另起
                    # `prison_war_end`(「战胜X，俘之」), 与同日的战阵俘获得出两种
                    # 说法; 语义同为「战中被俘」, 词形收到一处 (仍带「俘」字)。
                    body = W["prison_captured_battle"].format(
                        jailer=_wn or jn or "其监禁者", victim=vn)
                    o_kind = "war_end"
                elif pun is not None:
                    # pun = (W 的模板键, 事件下标) —— 见 _punishment_on;
                    # 同日给「当日」(与「当日获释」同式), 其余给「N日后」
                    drop.add(pun[1])
                    body += W[pun[0]].format(
                        sp=W["prison_same_day"] if same else f"{span}后",
                        jailer=jn)
                    o_kind = "punished"
                elif owned is not None and not out.get("escape"):
                    body += W["prison_enslaved"]
                    o_kind = "enslaved"
                elif out.get("escape"):
                    # v32: 越狱者不在「获释」之列 —— 出狱方式按记忆型分词
                    body += W["prison_escape_same_day"] if same else (
                        W["prison_escaped"].format(span=span) if span
                        else W["prison_escape_on"].format(date=f.date(out["date"])))
                    o_kind = "escape"
                else:
                    # v55 (问题1c/§3): 出狱缘由 (改信/交出牵制/放弃宣称/纳赎/驱逐…) ——
                    # 单人囚禁行**带时长**(「3日后改信获释」), 多人折叠簇不带 (见
                    # `_fold_prison_clusters`, 用户拍板「多人不带」)。
                    _mk, _mw = f.release_manner(victim, r["jailer"], out["date"])
                    if _mw:
                        if same:
                            body += f"，{W['prison_same_day']}{_mw}"
                        elif span:
                            body += f"，{span}后{_mw}"
                        else:
                            body += f"，{f.date(out['date'])}{_mw}"
                        o_kind = _mk
                    elif same:
                        body += W["prison_released_same_day"]
                        o_kind = "released"
                    elif span:
                        body += W["prison_released"].format(span=span)
                        o_kind = "released"
                    else:
                        body += W["prison_release_on"].format(
                            date=f.date(out["date"]))
                        o_kind = "released"
            elif owned is not None:
                # 无释放记忆、但在押期间已没为奴隶 → 出狱缘由即此
                body += W["prison_enslaved"]
                o_kind = "enslaved"
            else:
                # v42 (问题6): 囚期以**死亡**收口 —— 受害者有死亡记录 (日期不早于
                # 入狱日) 而释放/越狱/狱史皆无证据时, 写出死期与死法; 旧稿一律写
                # 「此后一直未见释放」(诺兰 1088.1.16 那 10 人其实 6 个月后被处决,
                # 受害者侧记忆已被引擎剪除, 故此前看不出囚期已终结)。
                # v60 (问题4): 走向 `prison_death_clause` —— 缓存查不到时回退熔件
                # `dead_data` (死在缓存末档之后者旧稿读不到)。
                dd = f.prison_death_clause(victim)
                d_date = dd.get("date")
                if d_date and cl.date_key(str(d_date)) >= cl.date_key(str(r["date"])):
                    # v42: 与释放句同式 —— 同日给「当日」, 其余给「N个月后」,
                    # 日期不可解析时退「至{date}」, 不留空槽
                    _sp = _prison_span(r["date"], d_date)
                    _final_span = _sp
                    sp = W["prison_same_day"] if _sp == W["prison_same_day"] \
                        else (f"{_sp}后" if _sp else f"至{f.date(d_date)}")
                    # 凶手与监禁者同一人 → 刑杀 (`_death_int` 是 Facts 的方法,
                    # 本函数是模块级函数, 故必须经 `f.` 调用; 哨兵 4294967295
                    # 一律视同「无凶手」)
                    _killer_same = (f._death_int(dd.get("killer"))
                                    == f._death_int(r["jailer"]))
                    _exec_like = (dd.get("reason") in _PRISON_EXEC_REASONS
                                  or _killer_same)
                    # 热修 (2026-09-24, 用户报告): 食人硬证优先于笼统的「处决」——
                    # Mod「食人赋能」把吃掉写成 `death_execution`, 遗骨是唯一确证
                    # (`devoured_by`, v60 问题2)。旧稿收口不问硬证, 于是同一份事实里
                    # 年表写「处决」而死者名录用 `execution_method` 写「被其吃掉」
                    # (第 3 个十年: 桂王唐文举 895.1.14 入狱, 6 个月后写「处决」,
                    # 而同一人的遗骨与死句都写「吃掉」)。死因与硬证须一致: 只在
                    # 本已是刑杀、且遗骨确由本监禁者造成时改写, 病故不因此改口。
                    _devour = bool(_exec_like and r["jailer"] is not None
                                   and f.devoured_by(r["jailer"], victim))
                    if _devour:
                        key, o_kind = "prison_died_devoured", "devoured"
                    elif _exec_like:
                        key, o_kind = "prison_died_executed", "executed"
                    else:
                        key, o_kind = "prison_died_in_prison", "died_in_prison"
                    body += W[key].format(sp=sp)
                else:
                    # v34 (问题7): 记得到此为止 — 释放记忆、狱史与死亡记录三者皆无
                    # 时, 程序把「此后如何」说全, 不把沉默留给模型去补
                    # (旧稿此处留白, 模型把囚期留白补成了「获释」)。
                    # v60 (问题4): 界线写到本篇截止日 (十年档) 或末档 (终传),
                    # 并写出监禁者交接 (「881年1月1日转归埃尔梅辛达」)。
                    body += W["prison_still_held"].format(bound=f._prison_bound())
                    body += f.prison_handover_clause(victim)
                    o_kind = "held"
            e = events[r["idx"]]
            e["text"] = f"{f.date(r['date'])}，{body}。"
            e.pop("ident", None)
            if o_kind == "war_end":
                # v56 (问题2): 战末俘获单列一型 —— `_fold_prison_clusters` 只认
                # `imprisoned`, 本行因此不进囚禁集群折叠 (940.6.1 的 7 人各成一行)。
                e["type"] = "war_capture"
                e["module"] = "战和胜负"
                continue
            e["type"] = "imprisoned"
            e["module"] = "囚禁入狱"
            # v54 (问题3d): 留给同日集群折叠用 (被囚者 id / 称谓 / 结局族 / 结局原文);
            # `_fold_prison_clusters` 收口时逐条 pop, 不进最终 facts。
            e["_pm"] = {"v": victim, "vn": vn, "jn": jn,
                        "h": head, "t": body[len(head):], "o": o_kind,
                        "cm": _cm, "sp": _final_span,
                        # v78 (概览口径): 本行是否为**主角本人**把人关起来 ——
                        # 折叠后按「每条/每簇计 1 次」重算「囚禁他人」。
                        "jp": bool(pid is not None and r["jailer"] == pid)}
    # v54 (顺带, v42 口径收口): 未被任何囚禁行消费的释放/越狱记忆不再单独成行 ——
    # v42 定规「释放/越狱一律写在囚禁行**之内**」, 裸「X获释。」行即残留形态。
    # 实测成因 (斯卡利茨 919.8.25 内莫伊): 同一人被囚两次而引擎只留了一条入狱记忆,
    # 多出的那次释放遂无行可挂; 旧稿靠年表 cap=150 把它截掉, 折叠后行数下降才浮出。
    for o in outs:
        if o["idx"] >= 0 and o["idx"] not in used:
            drop.add(o["idx"])
    return [e for i, e in enumerate(events) if i not in drop]


# ---------------------------------------------------------------------------
# v40: 性病 (情人疱疹 / 大痘) 传播 —— 单独成行
# ---------------------------------------------------------------------------
# 数据源: `cache["disease_edges"]` (cache_lib._diff_disease_edges)。
# 用户口径 (2026-09-15): 发生传播时在**性行为**句后补
# 「（某某把疱疹/大痘传染给了某某）」。该补注的载体是年表里的性事行 ——
# **v59 (问题2, 用户 2026-09-23 拍板) 性事不进公开年表**, 补注随之删除;
# 传播本身仍单独成一条事实行, 归「疾病传播」模块。
# 本地化表缺键时的兜底名 (本体中文: 情人疱疹 / 梅毒; 早发档显示同疱疹)
_STD_ZH_FALLBACK = {"lovers_pox": "情人的疱疹", "great_pox": "梅毒",
                    "early_great_pox": "情人的疱疹"}


def _std_disease_zh(f, key):
    """性病键 → 游戏显示名 (本地化表优先, 兜底表次之)。"""
    for cand in (f"trait_{key}", f"disease_{key}"):
        v = L.loc(f.table, cand)
        if v and not v.startswith(("$", "[")):
            return v.rstrip("。")
    return _STD_ZH_FALLBACK.get(key, key)


def _date_obj(s):
    """'1071.2.7' → datetime.date; 非法输入返回 None。"""
    try:
        return datetime.date(*(int(x) for x in str(s).split(".")[:3]))
    except Exception:
        return None


def _std_index(f):
    """cache["disease_edges"] → [(日期, 文本, 源, 的)] (惰性, 只算一次)。(v59 重写)

    v40 原有两个出口: ①「可挂性事」的传播补注, 挂在那一场性事的句末
    (`_std_note_for`); ②无性事行动可挂的传播单独成行。
    **v59 (问题2, 用户拍板) 性事不进公开年表** —— 出口①的载体已不存在,
    故本轮删去补注与 `_std_act_index`/`_std_note_for`/`_std_suffix`,
    只留出口② (性病传播本身不是性事, 仍按 `疾病传播` 模块进年表)。

    去重: 同一病人同一病种**只留一条** —— `health.1200/1201` 会自我重排复检,
    同一次感染在队列里会留下多条边 (日期各异), 且治愈后可再感染;
    取**与复检日最接近**的那一条 (最接近感染时点)。
    """
    if getattr(f, "_std_idx", None) is not None:
        return f._std_idx
    edges = f.cache.get("disease_edges") or {}
    chars = f.cache.get("characters") or {}
    W = _style.FACT_WORDING
    buckets = {}   # (病种, 病人) -> [(排序日, payload)]
    for rec in edges.values():
        if not isinstance(rec, dict):
            continue
        key = str(rec.get("disease") or "")
        zh = _std_disease_zh(f, key)
        tgt, src = rec.get("target"), rec.get("source")
        fire = _date_obj(rec.get("fire_date"))
        if not zh or not isinstance(tgt, int) or fire is None:
            continue
        if str(tgt) not in chars:
            # 病人不在缓存相关集内 —— 这条边进不了任何篇目, 直接跳过 (省索引)
            continue
        # v24 同源口径: 数据起点即见 (first=True) 的传播没有可作实的日期,
        # 不单独成行 (病人仍由其档案/特质可见)。
        if rec.get("first"):
            continue
        # v42 (问题4): 年表事实行 —— 主角只出名字 (见 Facts.event_name)
        tname = f.event_name(tgt, date=f.as_of)
        if not tname:
            continue
        sname = ""
        if isinstance(src, int) and src != tgt and str(src) in chars:
            sname = f.event_name(src, date=f.as_of)
        when = str(rec.get("first_seen") or rec.get("fire_date") or "")
        wd = _date_obj(when) or fire
        if sname:
            text = W["std_line"].format(src=sname, tgt=tname, disease=zh)
            payload = ("line", when, text, src, tgt)
        else:
            text = W["std_line_anon"].format(tgt=tname, disease=zh)
            payload = ("line", when, text, None, tgt)
        buckets.setdefault((key, tgt), []).append((wd, payload))
    out = []
    for _bk, items in buckets.items():
        items.sort(key=lambda x: x[0])
        payload = items[-1][1]
        out.append((payload[1], payload[2], payload[3], payload[4]))
    f._std_idx = out
    return f._std_idx


# ---------------------------------------------------------------------------
# v54 (问题3d): 同日囚禁集群折叠
# ---------------------------------------------------------------------------
_PRISON_CLUSTER_MIN = 5   # 同日同型囚禁行达此数才考虑折叠 (单/双人囚禁不动)
_PRISON_FOLD_TOP = 5      # 折叠行前部列名人数, 其后写「等N人」(用户拍板规则)
# v55 (§3): 可折叠的**结局族** = 全部人都活下来的那些 (获释/改信/牵制/放弃宣称/纳赎/
# 驱逐/征募/出家/越狱/受刑/没为奴隶)。含处决/狱中死/在押的簇**不折** —— v42 用户拍板
# 「诺兰 1088.1.16 那 12 人 10 处决 / 2 获释, 逐人成行留住各自死法」由此保住;
# 而 925.5.1 那 22 人结局各为「获释/改信/交出牵制」(全为生还), 折叠后按缘由计数。
_PRISON_FOLD_KINDS = frozenset({
    "released", "converted", "hook", "claim", "ransomed", "banished",
    "recruit", "vows", "escape", "punished", "enslaved",
    # v78 (问题1, D2, 用户 2026-09-27 拍板): 含处决 / 狱中死 / 被吃 / 在押的簇**也折** ——
    # 收口改按「结局族 × 时长」计数 (见 `_prison_fold_tail`), 各人死亡方式与关押时段的
    # 对应不失, 且被处决的关系人另有独立死亡记录句 (死句自带「囚禁N年后被斩首」)。
    # 旧口径 (v55 §3「全部生还才折」) 与 D2 冲突, 已按用户拍板调整: 浩二 902.8.18
    # 那 45 人若照旧口径会炸成 44 行 (39 人同日处决), 挤掉整篇年表。
    "executed", "died_in_prison", "devoured", "held",
})

# v78 (D2): 折叠收口的出词次序 —— 重结局在前 (吃掉/处决/狱中亡), 其后各出狱缘由,
# 最后「在押」(它自带「至{档}仍在押」, 排在末尾最顺)。只在人数相同时用来定序,
# 人数不同一律多的在前 (沿用 v55 的「人数降序」)。
_PRISON_KIND_ORDER = (
    "devoured", "executed", "died_in_prison", "enslaved", "banished",
    "punished", "escape", "converted", "hook", "claim", "ransomed", "recruit",
    "vows", "released", "held", "other",
)


def _prison_fold_tail(rows, f):
    """同日囚禁簇的收口小句 (含起首「，」) —— 按「结局族 × 时长」计数 (v78 D2)。

    用户拍板原话: 「改为『其中多少人于一年后被处决，一人随后获释』这样，关押时段
    不再写终止关押时间而是写几年/几个月后，因此 903 年被处决的可以合并。」
    故:
      · 时长一律写「N年后」(见 `_prison_span`), 终止关押日**不出现在收口里**;
      · 同一簇内不同结局/不同时长各成一组, 组内计数;
      · 单组写「，尽数{时长}后{词}」; 多组写「，其中A、B、余C」 (沿用 v55 的「余」字);
      · held 组无时长 (收口自带「至{档}仍在押」), 不拼「N后」。
    `rows` = [{"o": 结局族, "sp": 时长词}] (sp 可缺)。"""
    if not rows:
        return ""
    words = getattr(f, "_PRISON_KIND_WORD", {}) or {}

    def _word(kind):
        w = words.get(kind, "获释")
        return w.format(bound=f._prison_bound()) if "{bound}" in w else w

    cnt = {}
    for r in rows:
        k = r.get("o") or "released"
        sp = "" if k == "held" else str(r.get("sp") or "")
        cnt[(k, sp)] = cnt.get((k, sp), 0) + 1
    # 同一结局族的各组保持相邻 (按该族总人数先排), 组内保持原行序
    tot = {}
    for (k, _sp), n in cnt.items():
        tot[k] = tot.get(k, 0) + n

    def _rank(item):
        (k, _sp), n = item
        # 次序: 该结局族总人数 (多者在前) → 结局族次序 → 本组人数 (多者在前);
        # 并列时保持原行序 (原行序已按头衔层级/执政先后排过, 故「余」落在最小一组)。
        return (-tot.get(k, 0),
                _PRISON_KIND_ORDER.index(k) if k in _PRISON_KIND_ORDER else 99,
                -n)

    items = sorted(cnt.items(), key=_rank)

    def _seg(n, kind, sp):
        if sp:
            return f"{n}人{sp}后{_word(kind)}"
        return f"{n}人{_word(kind)}"

    if len(items) == 1:
        (k, sp), _n = items[0]
        return "，尽数" + (f"{sp}后{_word(k)}" if sp else _word(k))
    seg = [_seg(n, k, sp) for (k, sp), n in items[:-1]]
    (lk, lsp), ln = items[-1]
    seg.append("余" + _seg(ln, lk, lsp))
    return "，其中" + "、".join(seg)



def _fold_prison_clusters(events, f):
    """同日囚禁集群折叠 (v54 问题3d, 用户 2026-09-18 拍板取名规则)。

    三条件同时成立才折: ①同一天 ②≥ `_PRISON_CLUSTER_MIN` 人 ③**结局族一致**
    (族见 `_pair_imprisonments` 的 `_pm["o"]`: released/executed/escape/enslaved/
    punished/died_in_prison/held)。结局族不一致时不折 —— 诺兰 1088.1.16 的 12 人
    10 处决 / 2 获释, 属两族, 于是 v42「逐人成行留住各自死法」的拍板不受影响
    (马丁 919.7.14 那 29 人全为 released, 折叠)。

    取名(用户规则): 该日**最高头衔层级降序 → 执政起始日升序**(资格老者在先),
    取前 `_PRISON_FOLD_TOP` 人, 其后写「等N人」; 结局按原文分布写出
    (「其中28人1个月后获释、1人当日获释」), 全一致时直接写结局原文。

    处理完逐条 pop `_pm` —— 私有键不进最终 facts。

    v78: 返回三元组 `(out, saved, jp_kept)` —— `jp_kept` = **折叠后保留的**
    「主角为监禁者」囚禁行数 (折叠簇每簇计 1), 供 `_timeline` 重算概览「囚禁他人」
    (旧口径拿折叠前的双视角行数去扣 `saved`, 折叠面放宽后会直接扣成 0)。"""
    groups, order = {}, []
    for i, e in enumerate(events):
        pm = e.get("_pm")
        if e.get("type") != "imprisoned" or not pm:
            continue
        d = e.get("date")
        if d not in groups:
            groups[d] = []
            order.append(d)
        groups[d].append(i)
    drop, added = set(), []
    saved = 0
    jp_kept = 0
    for d in order:
        idxs = groups[d]
        if len(idxs) < _PRISON_CLUSTER_MIN:
            continue
        kinds = {events[i]["_pm"].get("o") for i in idxs}
        # v55 (§3): 折叠条件由「结局族完全一致」放宽为「**全部生还**」—— 同一天放出来的
        # 人各有缘由 (获释/改信/交出牵制), 旧条件会一款不折而回到报菜名。
        # v78 (D2, 用户 2026-09-27 拍板): 含处决/狱中死/在押的簇**一并折** (见
        # `_PRISON_FOLD_KINDS`) —— 收口改按「结局族 × 时长」计数, 各人死亡方式与关押
        # 时段的对应不失; 被处决的关系人另有独立死亡记录句 (自带「囚禁N年后被斩首」)。
        if not kinds or not kinds <= _PRISON_FOLD_KINDS:
            continue
        rows = []
        for i in idxs:
            pm = events[i]["_pm"]
            rank, since = f.title_rank_since_at(pm.get("v"), d)
            rows.append({"i": i, "rank": rank, "since": since,
                         "cid": pm.get("v") or 0, "vn": pm.get("vn") or "",
                         "jn": pm.get("jn") or "", "tail": pm.get("t") or "",
                         "o": pm.get("o") or "released",
                         "sp": pm.get("sp") or "",
                         "jp": bool(pm.get("jp")),
                         "cm": pm.get("cm") or "unknown"})
        rows.sort(key=lambda r: (-r["rank"],
                                 cl.date_key(r["since"]) if r["since"] else _DATE_KEY_MAX,
                                 r["cid"]))
        named = [r for r in rows if r["vn"]]
        if not named:
            continue
        shown = "、".join(r["vn"] for r in named[:_PRISON_FOLD_TOP])
        if len(named) > _PRISON_FOLD_TOP:
            shown += f"等{len(named)}人"
        jn = named[0]["jn"]
        body = f"{jn}囚禁{shown}" if jn else f"{shown}被囚"
        # v63 (问题1): 簇内若有战斗硬证, 整簇改写为战阵俘获; 否则维持裸「囚禁」
        # —— 破城与战败不可分 (调研 §10), 故不为簇另安方式词。
        if any((r.get("cm") or "") in ("battle", "battle_poi") for r in named):
            body = (f"{jn}于战阵俘获{shown}" if jn else f"{shown}于战阵被俘")
        # v63 第四轮: 簇内有**劫掠硬证** (家族关系流水: 监禁者当日劫掠了簇内某人
        # 或其同族) ⇒ 整簇写「劫掠中掳走」。915.7.2 那一簇 (埃德伯等 7 人) 正是
        # 如此 —— 旧稿此处只有裸「囚禁」, 模型遂自造「以商谈赎金为名」的捕获场景。
        elif jn and any((r.get("cm") or "") == "raid" for r in named):
            body = _style.FACT_WORDING["prison_raid_captured"].format(
                jailer=jn, victim=shown)
        # v78 (D2, 用户 2026-09-27 拍板): 收口改按「结局族 × 时长」计数, 时长写
        # 「N年后」、不写终止关押日期 —— 旧稿 (v55 §3) 是「多人不带时长」的
        # 「尽数获释」/「其中3人获释、余2人以人情获释」, 与本次拍板相反。
        body += _prison_fold_tail(named, f)
        drop.update(idxs)
        saved += len(named) - 1
        if any(r.get("jp") for r in named):
            jp_kept += 1
        added.append({"date": d, "type": "imprisoned", "module": "囚禁入狱",
                      "text": f"{f.date(d)}，{body}。"})
    for i, e in enumerate(events):
        pm = e.get("_pm")
        # v78: 未被折叠且「主角为监禁者」的行各自计 1 次 (概览口径)
        if pm is not None and i not in drop and pm.get("jp"):
            jp_kept += 1
        e.pop("_pm", None)
    if not drop:
        return events, 0, jp_kept
    out = []
    for i, e in enumerate(events):
        if i in drop:
            continue
        out.append(e)
    out.extend(added)
    out.sort(key=lambda e: cl.date_key(e.get("date") or ""))
    return out, saved, jp_kept


# v59 (问题2): `_std_note_for` / `_std_suffix` 已随「性事不进公开年表」删除 ——
# 补注的载体 (年表里的性事行) 不再存在, 性病传播一律走 `_std_index` 的单独成行。


# v54 (问题3): 监禁类记忆 —— 取值一律是「被囚者」id（用于诛灭世族整簇折叠）
_PRISON_MEM_TYPES = frozenset({
    "imprisoned", "imprisoned_other",
    "released_from_prison_memory", "escaped_from_prison_memory"})


def _prison_jailer(owner_id, mem):
    """该条监禁类记忆的**监禁者** id (v54): 入狱记忆按持有者方向分,
    `imprisoned_other` 的持有者即监禁者, 被囚者/获释/越狱侧取 `imprisoner` 槽。"""
    t = mem.get("type")
    if t not in _PRISON_MEM_TYPES:
        return None
    if t == "imprisoned_other":
        return int(owner_id) if isinstance(owner_id, int) else None
    j = (mem.get("participants") or {}).get("imprisoner")
    return int(j) if isinstance(j, int) else None


def _prison_victim(owner_id, mem):
    """该条监禁类记忆的**被囚者** id (v54): 入狱记忆按持有者方向分 (见 PARTICIPANT_SLOTS),
    获释/越狱记忆的持有者即被囚者。非监禁类返回 None。"""
    t = mem.get("type")
    if t not in _PRISON_MEM_TYPES:
        return None
    if t == "imprisoned_other":
        v = (mem.get("participants") or {}).get("imprisoned")
        return int(v) if isinstance(v, int) else None
    return int(owner_id) if isinstance(owner_id, int) else None


def _title_mem_skip(f, owner_id, mem, pid):
    """该条头衔得失记忆是否**不进年表** (v54 问题4)。返回 True 即丢。

    年表是「主角自己的行迹」，而头衔记忆有三类噪声（马丁终传实测 59 条里 38 条）：

    ① **封拜**：`owner` 是他人、`flavor_character` 是主角 —— 主角是**授予方**
       （919.8.3 置三省六部、919.8.22 分封诸王）。这是朝局的材料，不是传主的任期；
    ② **无地官署**：三省六部/御史台/枢密院（`e_minister_*`）。天子置官当即授人，
       本人「在位」时长为零 —— 与 v53 戏剧块的判据同源；
    ③ **零日在位**：造衔即封人（920.1.25 k_henan、920.4.5 k_hunan、922.4.3 k_lingxi
       等），title history 同日 created/本人 → appointment/朝臣。

    其余（真得真失，`owner` 是主角或与主角相关者）照常收录。

    v57 (问题4, 用户拍板): 第四类 —— **天朝制/行政制政体下的行政任免流水**。
    用户原话「理论上除了最高头衔，其他头衔都是根据选举决定的继承者，只是因为没有
    符合条件的才会给回玩家」, 故该政体下低于主角首要头衔的头衔得失一律不收
    (见 `Facts.admin_title_noise`); 受任/辞去/褫夺镜像行 (owner 为他人) 同判。"""
    if mem.get("type") not in TITLE_VAR_TYPES:
        return False
    tid = None
    for v in mem.get("vars") or []:
        if v.get("flag") == "landed_title" and v.get("identity"):
            tid = v.get("identity")
            break
    if tid is None:
        return False
    parts = mem.get("participants") or {}
    if f.admin_title_noise(tid, f.mem_date(owner_id, mem) or mem.get("creation_date"),
                           pid):
        return True
    if owner_id != pid:
        # ① 主角只当授予方的封拜 (owner 为他人 / 相关人)
        return parts.get("flavor_character") == pid
    # ② 无地官署
    if f.is_landless_office_title(tid):
        return True
    # ③ 零日在位
    return f.title_tenure_zero_day(pid, tid, f.mem_date(owner_id, mem))


# v77 (问题1): 本传主的**直系亲属** (父母/妻妾/子女) —— 他们的生卒是本传主生平的一部分
# (母卒于他三十六岁那年、女儿夭折), 故这类事件即便早于本人执政起点也留在他本篇本纪里;
# 姻亲/远亲之死与前代传主的手笔则不然 (见 `_timeline` 的「传主时代」闸)。
def _immediate_ids(f, pid):
    """直系亲属 id 集 (父母/妻妾/子女; 不含本人)。"""
    if pid is None:
        return set()
    rec = (f.cache.get("characters") or {}).get(str(pid)) or {}
    fam = rec.get("family") or {}
    out = set()
    for key in ("father", "mother", "primary_spouse", "spouse", "concubine",
                "former_spouses", "former_concubines", "child"):
        for x in fam.get(key) or []:
            if isinstance(x, int) and x != int(pid):
                out.add(x)
    return out


def _timeline(f):
    """主角相关时间线: 只收 宗族/父母妻儿/孙辈儿媳婿 相关事件 (口径见 _related_ids),
    按人按事去重, 按日期排序。
    每条 = {"date", "type", "text"} (text 为干净中文句, 提示词只用 text)。
    - 路人剔除: 记忆拥有者与参与者都不在相关集内的事件一律不收;
    - 死亡去重: 同一死者只留一条 (死亡记录 > 去世 > 丧偶), 消除「同一人不停地死」;
    - 出生去重: 同一出生只留一条 (玩家/家人视角优先);
    - 成对事件 (双方各自的记忆, 如王铎娶玘/玘嫁王铎) 按 (类型, 日期, 参与者集) 去重;
    - v30 镜像对: 战争/战役/刑虐/头衔更替的正反两方记忆按参与者身份配对, 只留一方;
    - v30 监禁对: 同一被囚者的入狱与获释合为一行 (见 _pair_imprisonments)。"""
    cache = f.cache
    pid = cache.get("player_id")
    related = _related_ids(f)
    # v77 (问题1): 「传主时代」闸 —— 继任传主的存档里带着前任传主整整一朝的材料
    # (前任的记忆列表在存档中持续存在, 且前任是本传主的父/兄, 故在 `related` 内),
    # 于是后任《本纪》的【大事年表】几乎全是前任的事迹 (田所久保 80 条里 60 条是
    # 父亲浩二 867–891 年的谋杀与姻亲之死, 模型照料写出「关白浩二一生行事…」)。
    # 判据: 事件**既非本传主本人**(记忆持有者不是他, 参与者里也没有他), 又落在
    # 「本人成为传主」之前 ⇒ 那是前任传主时代的事, 已在那一任自己的传记里写过,
    # 不进本篇。首位传主 (链上无前任) 不设闸 —— 零回归 (见
    # `Facts.protagonist_era`)。
    _era_start, _era_gate = f.protagonist_era()
    _era_key = cl.date_key(_era_start) if (_era_gate and _era_start) else None
    _close_ids = _immediate_ids(f, pid) if _era_key else set()

    def _pre_era(date, own):
        """该事件是否属「前任传主时代、且与本传主无关」⇒ 不进本篇年表。"""
        return bool(_era_key and not own and date
                    and cl.date_key(str(date)) < _era_key)

    # v54 (问题3): 诛灭世族涉及者 —— 其监禁类记忆不进年表 (整件事由族级行承担)
    purge_victims = f.family_purge_victims(pid) if pid is not None else set()
    purge_dates = f._purge_dates(pid) if pid is not None else set()
    events = []        # (date, type, text)
    idents = {}        # (date, type, text) -> {"owner", "parts"} — 镜像对/监禁对配对用
    seen_keys = set()  # 成对事件去重: (type, creation_date, participants 集)
    deaths = {}        # 死者id -> (优先级, date, type, text)
    births = {}        # (date, 出生键) -> (优先级, date, type, text)
    for cid, rec in (cache.get("characters") or {}).items():
        cid = int(cid)
        # v58 (问题8): 本角色的「死讯＋承袭」配对 (按 cid 记忆化, 只读记忆)
        _ipairs = f.inherit_pairs(cid)
        _consumed = f.inherit_consumed(cid)
        # 本人死亡记录 (信息最全, 优先级最高)
        if cid in related:
            # v42 (问题5): annotated=True —— 主角所杀者并写生年/族属/信仰,
            # 与 `*_died` 分支取死亡记录时的补注同式 (两者同优先级, 谁先写都一样)
            # v77 (问题1): 前任传主时代的关系人死讯 (如浩二 891 年所杀的五位亲王与
            # 姻亲) 全条略去 —— 那是前任的手笔, 不是本传主的事迹; 父母妻儿的死
            # 则是本传主生平的一部分, 即便早于本人执政起点也留 (`_close_ids`)。
            if not _pre_era((rec.get("death") or {}).get("date"),
                            cid == pid or cid in _close_ids):
                ds = _death_sentence(f, cid, annotated=True)
                if ds:
                    # v58 (问题8): 按优先级写 —— 继承合句 (4) 不得被死亡记录顶掉
                    _old = deaths.get(cid)
                    if _old is None or 3 > _old[0]:
                        deaths[cid] = (3, (rec.get("death") or {}).get("date"),
                                       "death", ds)
        for mem in rec.get("memories") or []:
            parts = mem.get("participants") or {}
            owner_rel = cid in related
            part_rel = any(isinstance(v, int) and int(v) in related
                           for v in parts.values())
            if not owner_rel and not part_rel:
                continue  # 路人记忆大事: 剔除
            # v77 (问题1): 「传主时代」闸 (见函数上方) —— 与本传主无关、且发生在他
            # 成为传主之前者, 属前任传主时代 (本传主本人参与的事件一律保留:
            # 出生、受业、受任、添丁、退位这些正是《本纪》要写的一生)。
            mtype = mem.get("type")
            if mtype in _DIED_TYPES:
                # 死讯的当事人是**死者** (记忆持有者只是当事人之一): 唯有死者就是
                # 本传主或其直系亲属时才算「本传主的事」—— 否则前任传主所杀姻亲的
                # 死讯仍会漏进后任本纪 (实测久保年表 80 条里 60 条如此)。
                _keep = (parts.get("dead_relation") == pid
                         or parts.get("dead_relation") in _close_ids)
            else:
                _keep = (cid == pid or pid in parts.values()
                         or parts.get("child") == pid)
            if _pre_era(mem.get("creation_date"), _keep):
                continue
            # v58 (问题8): 继承合句 —— 被配对的死讯改用合句, 承袭记忆不再单独成行
            _ip = _ipairs.get(id(mem)) if _ipairs else None
            # v38 (问题1): 性事记忆族的自愿档归并 —— 强迫/半推半就单独成档
            # (模块「强暴凌辱」), 自愿档与旧的 had_sex 同键同模, 婚姻内的那一支
            # 仍换档为「夫妻之情」(见下方 ev_type)。
            # v59 (问题2): 三档都不进公开年表 (见下方 `is_sex_event` 闸);
            # 归并仍要做 —— 档案/好友仇人列传按 `had_sex*` 与强迫档出句。
            _sxinfo = sex_mem_info(mtype) \
                if isinstance(mtype, str) and mtype.startswith(_SEX_MEM_PREFIX) \
                else None
            norm_type = mtype
            if _sxinfo is not None:
                norm_type = mtype if _sxinfo["kept"] else "had_sex"
            # 死亡类记忆: 按死者 id 去重 (去世 > 丧偶)
            # v42 (问题5): ① 八类 `*_died` 一律进来 (旧稿只列四类, `nemesis_died` /
            # `lover_died` / `soulmate_died` / `best_friend_died` 走通用路径,
            # 于是必出一行通用「去世」且模块为空);
            # ② **先取死者的真实死亡记录** (reason/killer/死法), 取不到才退回记忆句 ——
            # 旧稿只给「相关集」内的人渲染死亡记录, 仇人/死敌的死因 (含世仇灭门的
            # `death_eradicated` = 连同全族被处决) 在年表里退化成「X的仇人Y去世」。
            if mtype in _DIED_TYPES:
                dead = parts.get("dead_relation")
                if isinstance(dead, int):
                    if _ip is not None:
                        # v58 (问题8): 该死讯与新主的承袭同日 → 合为一句
                        _txt = f"{f.date(_ip[2])}，{_ip[0]}"
                        _old = deaths.get(dead)
                        # 同一死者同日有多位继承人 (本档 35087 死日: 墨索里尼承袭
                        # 下洛塔林吉亚、加里波利承袭布拉班特) → 并成一句
                        _head, _sep, _tail = _ip[0].partition("去世，")
                        if (_old is not None and _old[0] == 4 and _sep and _tail
                                and _ip[2] == _old[1]
                                and (_head + "去世，") in _old[3]
                                and _tail.rstrip("。") not in _old[3]):
                            _txt = _old[3].rstrip("。") + "，" + _tail
                        deaths[dead] = (4, _ip[2], "death", _txt)
                        continue
                    ds = _death_sentence(f, dead, annotated=True)
                    if ds:
                        _dd = ((cache.get("characters") or {}).get(str(dead)) or {})
                        # v58 (问题8): 按优先级写 (继承合句 prio 4 不得被顶掉)
                        _old = deaths.get(dead)
                        if _old is None or 3 > _old[0]:
                            deaths[dead] = (3, (_dd.get("death") or {}).get("date"),
                                            "death", ds)
                    else:
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
                        # v42 (问题5): 补注抽成 _victim_marks, 与死亡记录句共用。
                        note = _victim_marks(f, dead)
                        if note:
                            s = s.rstrip("。") + note + "。"
                        # v24: 依谋杀发生日标受害者死前最近可知所在 (男爵领名;
                        # 数据无则省略) — 击杀无案发地点, 以受害者位置为锚,
                        # 不再用主角驻地 (主角驻地 ≠ 案发地)。
                        vp = f.victim_place(dead)
                        if vp:
                            s = s.rstrip("。") + f"，死于{vp}。"
                        old = deaths.get(dead)
                        if old is None or 2 > old[0]:
                            deaths[dead] = (2, mem.get("creation_date"),
                                            "successful_murder", s)
                continue
            # 出生类记忆: 同一出生按 (日期, 出生键) 去重 (玩家/家人视角优先)
            # v30: 出生键改为「孩子 id」(忽略记忆类型), 孩子槽缺失时退化为母亲 id —
            # 修复「崔佛添子富兰克林」/「戈迪娜得长子富兰克林」同日双写, 以及
            # 「崔佛幼子夭折」/「戈迪娜幼子夭折」(child_premature 无 child 槽) 双写
            # (修复方案_菲利普4.md 问题6)。
            if mtype in ("child_born", "first_born", "child_premature",
                         "child_stillborn", "twins_born"):
                child = parts.get("child")
                if isinstance(child, int):
                    child_key = ("生", child)
                else:
                    mother = parts.get("mother")
                    child_key = ("生", int(mother)) if isinstance(mother, int) \
                        else ("生", cid)
                bkey = (mem.get("creation_date"), child_key)
                prio = 2 if cid == pid else (1 if owner_rel else 0)
                s = _mem_sentence(f, cid, mem)
                if s:
                    old = births.get(bkey)
                    if old is None or prio > old[0]:
                        # v34 (问题8): 一并记下孩子 id — 供「是否主角骨血」分类
                        births[bkey] = (prio, mem.get("creation_date"),
                                        mtype, s,
                                        child if isinstance(child, int) else None)
                continue
            # 其余记忆: 成对去重
            # v54 (问题4): 头衔记忆先过闸 —— 封拜他人 / 无地官署 / 零日在位不进年表
            if _title_mem_skip(f, cid, mem, pid):
                continue
            # v58 (问题8): 已被继承合句消费的记忆 (死讯 + 承袭) 不再单独成行
            if _consumed and id(mem) in _consumed:
                continue
            # v54 (问题3): 诛灭世族的「先尽囚、后驱逐」侧 —— 涉及者逐人成行会塞满年表
            # (马丁 920.1.24 有 85 行), 整件事由族级事实行一行承担 (见下方 family_purge)。
            # 两条判据并用: ①受害者在诛灭名单里 (被处决者及其同族);
            # ②该日即诛灭日**且监禁者是主角** —— 被驱逐的残党无地、不在处决名单里,
            # 只认①会漏掉他们 (实测 85 行里 69 行如此)。
            if purge_dates and norm_type in _PRISON_MEM_TYPES:
                _pd = f.mem_date(cid, mem) or mem.get("creation_date")
                if _prison_victim(cid, mem) in purge_victims \
                        or (str(_pd) in purge_dates
                            and _prison_jailer(cid, mem) == pid):
                    continue
            s = _mem_sentence(f, cid, mem)
            if not s:
                continue
            pset = frozenset(v for v in parts.values() if isinstance(v, int)) \
                | {cid}
            # v34b: 头衔得失事件用 title history 事件日 (记忆日常晚一天),
            # 去重键/事件日/句面日期同源, 防止文本与排序两套日期
            _md = f.mem_date(cid, mem)
            key = (norm_type, _md, pset)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            # v30: 镜像对/监禁对需要参与者身份 → 随事件登记 (见 _drop_mirror_pairs)
            # v38 (问题1): 性事记忆对 (施为方/受害方各一条) 同样按身份配对
            # v42 (问题3): 刑虐记忆一并记下刑名 —— _pair_imprisonments 据此把
            # 「阉割/致盲 ⇒ 当日获释」并入囚禁行 (见 _punishment_on)
            if norm_type in _IDENT_TYPES or _sxinfo is not None:
                _ident = {"owner": cid, "parts": dict(parts), "type": mtype}
                if norm_type in ("torturer_memory", "tortured_memory"):
                    _ident["torture_kind"] = _torture_kind(f, mem) or "torture"
                # v78-3: 战事记忆带上战略槽 (宣战理由/目标头衔/宣称者/兴兵方/战场),
                # 供 `_pair_war_events` 配对与出句 —— ident 本身只带 owner/parts。
                if norm_type in _WAR_MEM_TYPES or norm_type in (
                        "battle_won_memory", "battle_lost_memory"):
                    _ident["war"] = _war_mem_meta(mem)
                idents[(_md, norm_type, s)] = _ident
            # v31 (问题2): 配偶之间的情事换档 — 概览记「夫妻之情」, 模块归「婚配联姻」
            # v38 (问题1): 强迫/半强迫档不换 —— 「妻子为丈夫所强迫」仍是强迫之事,
            # 不因婚内就归进「夫妻之情」。
            ev_type = norm_type
            if norm_type in ("had_sex", "became_lovers") \
                    and not (_sxinfo is not None and _sxinfo["kept"]):
                _oth = (parts or {}).get("sex_partner" if norm_type == "had_sex"
                                          else PARTICIPANT_SLOTS.get(norm_type) or "")
                if isinstance(_oth, int) and _oth != cid \
                        and f.is_spouse_pair(cid, _oth):
                    ev_type = norm_type + "_spouse"
            # v59 (问题2, 用户拍板): 性事 (含配偶同房/私通/强迫·半推半就) **不进
            # 公开年表** —— 三条模块的句面只留在角色档案与好友/仇人列传里,
            # 故此处直接丢; 于是共享前缀《大事年表》、各篇【本板块大事】与
            # 十年主题计数里都不会再出现性事。
            if is_sex_event(ev_type):
                continue
            events.append((_md, ev_type, s,
                           _TYPE2MODULE.get(ev_type, "")))
    # v40: 性病传播 —— 无性事行动可挂的边单独成行 (本体按期在 lover/consort
    # 之间传播、卖淫、先天; 不并入任何性行为句)。只收当事人属相关集者。
    for _when, _text, _src, _tgt in _std_index(f):
        if not _when:
            continue
        if not (_tgt in related or (isinstance(_src, int) and _src in related)):
            continue
        # v77 (问题1): 同受「传主时代」闸 (本传主非当事人的前任时代传播行略去)
        if _pre_era(_when, pid in (_src, _tgt)):
            continue
        events.append((_when, "std_transmission", _text, "疾病传播"))
    # 合并 死亡记录 + 去世记忆 + 出生事件
    # v14: death 记录按死者关系标模块 (仇人死亡/丧友之恸/丧偶之痛/丧亲之恸)
    # v42 (问题5): 关系集一次预算, 供全部死者共用 (见 _death_rel_sets)
    _rivals, _friends = _death_rel_sets(f, pid)
    for cid, (_prio, _d, t, s) in deaths.items():
        events.append((_d, t, s, _death_module(f, cid, _rivals, _friends)))
    # v34 (问题8, 用户拍板): 《本纪》收「主角是法理父亲」的全部子女 —
    # 非婚生亦在其中, 且句面不写生父 (本纪写的是他的家门)。
    # 法理父是别人的孩子 (妻室与他人所出) 不进本纪, 归《家室列传》。
    own_birth_kids, _has_fam = (
        f.legal_children_ex(pid) if pid is not None else (set(), False))
    for _prio, _d, t, s, _kid in births.values():
        events.append((_d, t, s, "添丁进口" if t in ("child_born", "first_born", "twins_born") else "夭折",
                       {"own_birth": (_kid is None or _kid in own_birth_kids)}))
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
            # v77 (问题1): 同受「传主时代」闸 (他人的改信若在前任时代, 不进本篇)
            if _pre_era(d, cid == pid):
                continue
            nm = f.event_name(cid, date=d)
            fn = f._faith_name(ch.get("faith"))
            if nm and fn:
                events.append((d, "faith_changed", f"{nm}改信{fn}。", "信仰皈依"))
    # v54 (问题3): 诛灭世族的族级事实行 —— 整件事一行 (被驱逐者不列名),
    # 取代被丢掉的逐人监禁行; 日期由下方 out 组装统一加句首 (与其余事件同式)。
    for _pe in (f.family_purge_events(pid) if pid is not None else []):
        events.append((_pe["date"], "family_purge", _pe["text"], "诛灭世族"))
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
    _jail_pre = 0      # v78: 折叠前逐行计出的「囚禁他人」条数 (折叠后整体重算)
    for _ev in events:
        _d, t, s, mod = _ev[0], _ev[1], _ev[2], _ev[3]
        # v54 (问题3, 用户拍板「按方案做」): 诛灭世族已折成族级行 —— 一次计 1 次
        # 「囚禁他人」; 该行句面不含主角名, 故本支须在名在句中判定之前。
        if t == "family_purge":
            stats["囚禁他人"] = stats.get("囚禁他人", 0) + 1
            continue
        if pname0 and pname0 not in s:
            continue
        # v32 (问题1): 被囚统计只算**主角本人**被囚 —— 受害者侧的记忆句现在会点名
        # 监禁者, 主角恰是那个监禁者时句中也含主角名, 「名在句中」不再等价于被囚
        # (马克龙: 主角囚人四次被误计为「被囚5次」)。方向按记忆持有者判定。
        if t == "imprisoned" and pid is not None:
            if (idents.get((_d, t, s)) or {}).get("owner") != pid:
                continue
        if t == "imprisoned_other":
            # v78: 「囚禁他人」改在**双视角合一 + 同日簇折叠之后**统一计 (见下方) ——
            # 旧口径在折叠前逐行计, 再全额扣掉 `_fold_saved`, 而折叠面放宽到含处决/
            # 在押的簇后会把主角成批大狱直接扣成 0 (浩二 902.8.18 那 44 人)。
            # 此处只**占位** (保住概览的出词次序), 数值随后整体重算。
            stats["囚禁他人"] = stats.get("囚禁他人", 0) + 1
            _jail_pre += 1
            continue
        label = _DEATH_STAT_LABEL.get(mod) if t == "death" else _STATS_LABEL.get(t)
        if label:
            stats[label] = stats.get(label, 0) + 1
    f._timeline_stats = stats
    seen = set()
    out = []
    for _ev in events:
        d, t, s, mod = _ev[0], _ev[1], _ev[2], _ev[3]
        extra = _ev[4] if len(_ev) > 4 else {}
        # v42 (§3.1 续, 顺带): 末道句面去重带上**日期** —— 旧稿只按句面文本去重,
        # 同一被囚者两次入狱的句面逐字相同 (「X为Y所囚。」/「Y获释。」), 后一次
        # 被静默丢弃 (诺兰档 1086.12.2 海因里希第二次被囚即此, 于是 12.17 的
        # 阉割找不到可并入的囚禁行)。同日同句的重复仍照常合并。
        if (d, s) in seen:
            continue
        seen.add((d, s))
        rec = {
            "date": d,
            "type": t,
            # v14: 戏剧性模块标注 (纯数据层, 十年主题抽取/文章切片用)
            "module": mod or _TYPE2MODULE.get(t, ""),
            # v27: 死亡句自带的日期已在句内 (「X死于YYYY年M月D日，…」),
            # 不再在句首重复一遍日期 (「893年4月28日，塔坦尼·布兰死于893年4月28日…」)
            "text": (s if (t == "death" or not d) else f"{f.date(d)}，{s}"),
        }
        # v34 (问题8): 出生事件的骨血标记 — 《本纪》据此只收主角自己的子女
        if "own_birth" in extra:
            rec["own_birth"] = bool(extra["own_birth"])
        ident = idents.get((d, t, s))
        if ident:
            rec["ident"] = ident
        out.append(rec)
    # v30: 镜像对去重 (问题6) — 同一事件的正反两方记忆只留一条
    out = _drop_mirror_pairs(out, pid, pname0)
    # v30: 入狱与获释合并 (问题5) — 双视角与进出狱各自成行的问题一并解决
    out = _pair_imprisonments(out, f, pid, pname0)
    # v54 (问题3d): 同日囚禁集群折叠 —— ≥5 人且结局族一致才折, 取名按头衔高低
    # 与执政先后 (用户规则)。
    # v78: 返回三元组, 第三项 = 折叠后保留的「主角为监禁者」行数 (簇每簇计 1),
    # 概览「囚禁他人」据此重算 —— 旧式「折叠前逐行计再全额扣 `_fold_saved`」
    # 在折叠面放宽后会归零 (见 `_fold_prison_clusters` 的说明)。
    out, _fold_saved, _jp_kept = _fold_prison_clusters(out, f)
    # 概览「囚禁他人」= 诛灭族级行 (占位时已计) + 折叠后保留的逐条/每簇 1 次
    stats["囚禁他人"] = max(0, stats.get("囚禁他人", 0) - _jail_pre) + _jp_kept
    # v78-4: 人质三视角归并 + 送出↔送还配对 (见 `_pair_hostages`)
    out = _pair_hostages(out, f)
    # v78-3 (用户问题2): 战事兴兵 ↔ 决胜配对成一段 + 补对手/宣战理由/争战目标/夺地;
    # 战斗行补地点与对手。放在囚禁两遍处理**之后** —— 年表侧「战末俘获」判据
    # (`_war_end_with`) 要读同日那条 war_won 行, 先合并会把它的型改掉。
    out = _pair_war_events(out, f)
    # v58 (问题7): 同场活动跨日合并 (同一场加冕礼的跨日见证记忆)
    out = _merge_activity_windows(out, f)
    # v11: 同日同型集体事件合并 (见证加冕/出席大婚/被囚/囚禁)
    out = _merge_same_day_events(out, f)
    # v15: 同月同型流水事件聚合 (结怨/结仇/助战…), 聚合后再限量
    out = _merge_same_month_events(out, f)
    # v64 (问题3): 别立家族 / 家族改名 —— 补成**年表事件** (见 `_house_founding_events`)
    out.extend(_house_founding_events(f))
    # v14/v56: 末道稳定排序 + 年表限量 (判据与次序见 `_cap_timeline`)
    return _cap_timeline(out, f)


# v64 (问题3): 「别立家族 / 家族改名」写成年表事件。
#
# 起因 (菲利普2 卡尔): 「934年5月7日，卡尔别立顿巴斯氏，为菲利普宗族分支，自成一脉，
# 家格自此改易」只出现在第 1 个十年正文里, 第 2 个十年与终传都没有。逐请求核对
# `logs/prompts.log` 后确认: 事实面**没丢** —— 「家格：原属菲利普氏，934年5月7日起
# 别立顿巴斯氏，属菲利普宗族。」在三篇的每一次「传主类」请求里都在 (家格=1)。
# 真正缺的是**事件位**: 游戏只为立家留一个 `found_date` (cache 的 house_history),
# 它不是记忆事件, 故时间线 150 条里与立家相关者 0 条 ——
#   · 《本纪》纪事的【大事年表】切片 (module 白名单) 拿不到它;
#   · 终传附录·大事年表由程序渲染自 `facts["timeline"]`, 因此**必然**没有它。
# 补成事件后, 开篇/纪事/附录三处同源, 「别立」不再随该篇材料拥挤程度时有时无。
#
# 约定: module = 起家发迹 (使其进《本纪》开篇切片; 会给该模块在十年主题里 +3 分,
# 语义正确); type = house_founded (不在 `_TYPE2MODULE`/`_STATS_LABEL` 内, 概览统计
# 不受影响); ident.owner = 主角 (使 `_cap_timeline` 判级别 1, 封顶时不被裁)。
def _house_founding_events(f):
    """立家/家族改名/宗族改名的年表事件 (无沿革返回 [])。"""
    pid = f.cache.get("player_id")
    if pid is None:
        return []
    rec = (f.cache.get("characters") or {}).get(str(pid)) or {}
    hist = [h for h in (rec.get("house_history") or []) if h.get("from")]
    if f.as_of:
        ao = cl.date_key(f.as_of)
        hist = [h for h in hist if cl.date_key(str(h["from"])) <= ao]
    if len(hist) < 2:
        return []
    out = []
    for i in range(1, len(hist)):
        cur, prev = hist[i], hist[i - 1]
        d = str(cur["from"])
        hn = _house_shi(house_display(cur.get("house_name") or ""))
        dn_raw = house_display(cur.get("dynasty_name") or "")
        dn = _house_shi(dn_raw)
        p_hn = _house_shi(house_display(prev.get("house_name") or ""))
        p_dn = _house_shi(house_display(prev.get("dynasty_name") or ""))
        nm = f.event_name(pid, d) or f.name_or(pid)
        if not nm:
            continue
        new_house = cur.get("house_id") != prev.get("house_id")
        house_changed = hn != p_hn
        dyn_changed = dn != p_dn
        # 宗族名按家格句的称法 (「属菲利普宗族」, 不带「氏」)
        # v81 (问题1): 家族称法已含宗族名时 (东方名序的组装形「平氏下北沢家」)
        # 不再补 —— 与 `house_history_lines` / `clan_line` 同一条口径,
        # 免得同一件宗族关系在档案行与年表事件里各说一遍。
        _east = f.name_order(pid) in cl.EASTERN_NAME_ORDERS
        clan = f"，属{dn_raw}宗族" if dn_raw and hn and dn != hn and not _east else ""
        if new_house:
            body = f"{nm}别立{hn or dn}{clan}。"
        elif house_changed and dyn_changed:
            body = f"{nm}家族与宗族并称{hn or dn}。"
        elif house_changed:
            body = f"{nm}家族改称{hn}{clan}。"
        elif dyn_changed:
            body = f"{nm}宗族改称{dn}。"
        else:
            continue
        out.append({
            "date": d,
            "type": "house_founded",
            # v64: 专用模块 (只进《本纪》开篇白名单) —— 语义上属「起家发迹」,
            # 但那一档落在本纪**纪事**/朝局开篇, 而用户指认的句子在本纪**开篇**。
            "module": "家格宗支",
            "text": f"{f.date(d)}，{body}",
            "ident": {"owner": pid, "parts": {"owner": pid},
                      "type": "house_founded"},
        })
    return out


# v14: 十年戏剧主题抽取 (研究_戏剧模块化.md 3.2) — 时间线事件按模块计数,
# 主角参与 ×3 / 直系参与 ×2 / 其余 ×1 (时间线已只含直系, 权重简化为
# 主角名在文本中 ×3 否则 ×1); v24: 取 Top5 (用户: 呈现 5 个左右), 与第 5 名
# 并列的模块全保留; 专题模块 (血脉登基等) 先并入再统一切口。
def _cap_timeline(out, f):
    """年表限量 (v14; v56 问题2 附带重写判据与次序)。

    级别3已从源头剔除, 剩余级别1(主角)/级别2(直系); 超限时截断级别2。

    v56 判据: 级别1 按事件自带的 `ident`, 不再靠句面人名匹配 —— 旧稿用
    `name_full in text`, 而主角改名后 (斯卡利茨 947 年宗族改称「施」氏) 现名与
    **事件当日的旧名**不同形: 战争/头衔行按事件日取名
    (「撒旦之种沙米尔·斯卡利茨赢得战争。」), 现名是「施沙米尔」, 于是主角自己
    924–943 年的战争行整批被判成级别2 而在封顶时删光 (终传 150 条里只剩 7 条,
    全是前代马丁朝的)。
      · ident.owner == 主角  → 本人持有的记忆;
      · 主角在 ident.parts 里 → 本人为当事人 (镜像对留存的那条常是对手视角,
        如「敌方赢得战争」而主角是败方 —— 这类正是要留的);
      · 无 ident 的旧型 → 回退句面匹配。
    另: ① 末道按日期**稳定**排序 —— 中间几步 (同月同型聚合、私情配对) 把合并行
    放回该组首次出现的位置, 少数行因此落到更晚的日期之后 (斯卡利茨终传实测 7 处
    逆序); ② 截断**保持原时间序** (旧稿把级别1 全部提到级别2 之前, 封顶后的年表
    因此前段是主角、后段倒回前代, 与板块要求「按时间次序叙述」相悖)。"""
    out.sort(key=lambda _e: cl.date_key(_e.get("date") or ""))
    cap = 80 if f.as_of else 150   # 十年传记(有 as_of) ≤80, 终传/在世 ≤150
    if len(out) <= cap:
        return out
    pid_cap = f.cache.get("player_id")
    pname = (f.cache.get("characters") or {}).get(str(pid_cap), {}).get("name_full") or ""

    def _is_lvl1(_e):
        _ident = _e.get("ident") or {}
        if _ident:
            if _ident.get("owner") == pid_cap:
                return True
            return pid_cap in [v for v in (_ident.get("parts") or {}).values()
                               if isinstance(v, int)]
        return bool(pname) and pname in (_e.get("text") or "")

    _lvl1 = [_e for _e in out if _is_lvl1(_e)]
    _room = max(0, cap - len(_lvl1))
    _keep = {id(_e) for _e in _lvl1}
    for _e in out:                      # 原序遍历, 级别2 按序补足名额
        if _room <= 0:
            break
        if id(_e) not in _keep:
            _keep.add(id(_e))
            _room -= 1
    return [_e for _e in out if id(_e) in _keep]


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
# v42 (§3.1/§3.3, 用户拍板3「保留」): **去掉两条监禁类合并** ——
#   ① `imprisoned` 的正则还是 v32 前的旧形态 `^(.+?)为(.+?)所囚。$`, 早已永不命中
#      (现形态是「{jailer}囚禁{victim}，…」); `imprisoned_other` 的正则也会把
#      「囚禁X，14日后获释」的尾巴当成名字槽 —— 两条都是隐患而非功能;
#   ② 入狱行现在带出狱缘由 (获释/越狱/没为奴隶/处决/死于狱中), 逐人结局不同,
#      合并成「诺兰囚禁A、B…等12人」恰好抹掉每人各自的死法 —— 逐人成行才有意义
#      (诺兰 1088.1.16 的 12 人即此例: 10 人 6 个月后处决, 2 人获释)。
_MERGE_SLOT_RES = {
    # v56 (问题1b): 加冕句补上 host 后, 正则与合并器同步 —— 且**只有 host 相同**
    # (同一场加冕礼) 才合并成一行。条目字段:
    #   pat      —— 提取可变槽的正则 (第 0 组恒为人名, 其余为定值槽)
    #   key      —— None 时整组合并; 给出时按 key(groups) 分小组, 不同键不合并
    #   comb     —— 合并句正文 (入参 = 各行的 m.groups() 元组列表 gs)
    #   cap_verb —— 超过 _MERGE_CAP 人时「…等N人」之后的收尾 (须把定值槽带全)
    "witnessed_a_coronation_memory": {
        "pat": r"^(?P<name>.+?)见证(?P<host>.+?)的加冕。$",
        "key": lambda g: g[1],
        "comb": lambda gs: "、".join(g[0] for g in gs)
                           + "见证" + gs[0][1] + "的加冕。",
        "cap_verb": lambda gs: "见证" + gs[0][1] + "的加冕。",
    },
    "grand_wedding_completed_guest": {
        "pat": r"^(?P<name>.+?)出席大婚。$",
        "comb": lambda gs: "、".join(g[0] for g in gs) + "出席大婚。",
        "cap_verb": lambda gs: "出席大婚。",
    },
}
_MERGE_CAP = 10  # 合并人名上限, 超过收成「…等N人」


# v58 (问题7): **同场活动跨日合并** —— 游戏对同一场加冕礼写两条
# `witnessed_a_coronation_memory`（活动收尾 `common/activities/activity_types/
# coronation.txt:3043` ＋ 宾客告别事件 `coronation_events.0312`
# (`events/activities/coronation_activity/coronation_events.txt:5137`, 只对非 AI
# 宾客触发)），玩家侧于是落在相邻两天（本档 1067.12.22 与 1067.12.23）。
# 同日合并器只认同一天, 跨日的同场事件不合并 → 大事记里同一场加冕礼连出两行。
# 规则: 同 type + 同 host (加冕者) 且在 `_ACTIVITY_MERGE_DAYS` 天窗口内 → 并成一行,
# 日期取**首日**（用户 2026-09-22 拍板「只写第一天」), 见证人取并集。
_ACTIVITY_WINDOW_TYPES = ("witnessed_a_coronation_memory",
                          "grand_wedding_completed_guest")
_ACTIVITY_MERGE_DAYS = 7


def _merge_activity_windows(events, f=None):
    """同场活动跨日合并 (v58 问题7)。仅对 `_ACTIVITY_WINDOW_TYPES` 生效。"""
    if not events:
        return events
    by_type = {}
    for e in events:
        t = e.get("type")
        if t in _ACTIVITY_WINDOW_TYPES:
            by_type.setdefault(t, []).append(e)
    if not by_type:
        return events
    drop = set()
    merged = {}

    for typ, entries in by_type.items():
        spec = _MERGE_SLOT_RES.get(typ)
        if not spec:
            continue
        pat = spec["pat"]

        def _body(e):
            b = e.get("text") or ""
            d = e.get("date")
            pre = f.date(d) + "，" if (d and f) else ""
            return b[len(pre):] if (pre and b.startswith(pre)) else b

        ordered = sorted(entries, key=lambda e: cl.date_key(e.get("date") or ""))
        groups = []            # [(首日, [entry…])]
        for e in ordered:
            m = re.match(pat, _body(e))
            if not m:
                continue
            gkey = spec["key"](m.groups()) if spec.get("key") else "_"
            dk = cl.date_key(e.get("date") or "")
            placed = False
            for g in groups:
                if g[0] == gkey and _daynum(e.get("date")) - _daynum(g[1][0].get("date")) \
                        <= _ACTIVITY_MERGE_DAYS:
                    g[1].append(e)
                    placed = True
                    break
            if not placed:
                groups.append((gkey, [e]))
        for gkey, g in groups:
            if len(g) < 2:
                continue
            # 同一人可能两天各留一条记忆 (本档玛蒂尔达 12.22 与 12.23 各有),
            # 同日那一条的「名字槽」本身也可能是「A、B」多人串 →
            # 逐名拆开去重, 只列一次。定值槽 (host 等) 取首条的。
            _base = re.match(pat, _body(g[0])).groups()
            _names, _seen = [], set()
            for e in g:
                for _nm in str(re.match(pat, _body(e)).groups()[0]).split("、"):
                    _nm = _nm.strip()
                    if not _nm or _nm in _seen:
                        continue
                    _seen.add(_nm)
                    _names.append(_nm)
            gs = [tuple([_nm] + list(_base[1:])) for _nm in _names]
            if len(gs) > _MERGE_CAP:
                body = "、".join(x[0] for x in gs[:_MERGE_CAP]) + \
                    f"等{len(gs)}人" + spec["cap_verb"](gs)
            else:
                body = spec["comb"](gs)
            first = g[0]
            d = first.get("date")
            txt = f"{f.date(d)}，{body}" if (d and f) else body
            merged[id(first)] = dict(first, text=txt, activity_window=True)
            for e in g:
                if e is not first:
                    drop.add(id(e))
    if not drop and not merged:
        return events
    out = []
    for e in events:
        if id(e) in drop:
            continue
        out.append(merged.get(id(e), e))
    return out



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
        if not (spec and len(entries) > 1):
            out.extend(entries)
            continue
        pat = spec["pat"]

        def _body(e):
            b = e["text"]
            if d and f and b.startswith(f.date(d) + "，"):
                b = b[len(f.date(d)) + 1:]
            return b

        # 同一 (日期, 类型) 里可能含**几件不同的事** (同日数场加冕礼) —— 按 key 切块,
        # 不同键各自成行, 不被折成一句。
        if spec.get("key"):
            buckets = {}
            for e in entries:
                m = re.match(pat, _body(e))
                gk = spec["key"](m.groups()) if m else ("_nomatch", id(e))
                buckets.setdefault(gk, []).append(e)
            chunks = list(buckets.values())
        else:
            chunks = [entries]
        for chunk in chunks:
            slots, ok = [], True
            for e in chunk:
                m = re.match(pat, _body(e))
                if not m:
                    ok = False
                    break
                slots.append(m.groups())
            merged = None
            if ok and len(chunk) > 1:
                prefix = f"{f.date(d)}，" if d else ""
                names = [s[0] for s in slots]
                if len(names) > _MERGE_CAP:
                    merged = (prefix + "、".join(names[:_MERGE_CAP])
                              + f"等{len(names)}人" + spec["cap_verb"](slots))
                else:
                    merged = prefix + spec["comb"](slots)
            if merged:
                # v27: 合并必须携带 module —— 此前只写 date/type/text, 合并后的
                # 事件模块为空, 模块切片会把「被囚」等集体事件整体漏掉。
                # v34 (问题8): 骨血标记同型合并后按「全部为本家子女」判定, 不一并丢失。
                _rec = {"date": d, "type": typ, "text": merged,
                        "module": chunk[0].get("module", "")}
                if any("own_birth" in e for e in chunk):
                    _rec["own_birth"] = all(e.get("own_birth") is not False
                                            for e in chunk)
                out.append(_rec)
            else:
                out.extend(chunk)
    return out





# v15: 同月同型流水事件聚合 — 只合并单槽可变、结构一致的流水 (结怨/结仇/助战等)。
# style: duo = 「A与B结怨。」双槽; solo = 「A助盟友作战。」单槽。
_AGG_SPEC = {
    "became_grudge":    {"pat": r"^(.+?)与(.+?)结怨。$",     "verb": "结怨",     "style": "duo"},
    "became_rivals":    {"pat": r"^(.+?)与(.+?)结仇。$",     "verb": "结仇",     "style": "duo"},
    "became_nemesis":   {"pat": r"^(.+?)与(.+?)结为死敌。$", "verb": "结为死敌", "style": "duo"},
    "became_friends":   {"pat": r"^(.+?)与(.+?)结为好友。$", "verb": "结为好友", "style": "duo"},
    # v78-3: 战事重建后盟战行改写成「{名}随{盟友}出战，对抗{敌手}[，此役为{战名}]」，
    # 旧样式的 `^…助盟友作战。$` 不再命中。此处按**富句**重挂聚合: 同一月、同一盟友、
    # 同一敌手、同一战名的一批应召 (同一次战争的各路封臣) 并成一行 —— 细节 (盟友/
    # 敌手/战名) 一字不减, 只把「同一场战争的多次应召」收到一行 (用户 D4 只做 A 档,
    # 但同月同对手的应召并成一行属于「合并」而非「丢料」)。
    "joined_allys_war": {"pat": r"^(.+?)随(.+?)出战，对抗(.+?)(，此役为(.+?))?。$",
                         "verb": "",  "style": "allies"},
}

# v15: 「私情+相恋」成对合并 (同月同对象的 had_sex 与 became_lovers)
# v31 (问题2): 配偶对另用「同房」句形, 合并为「夫妻情笃」(非配偶仍是「私通相恋」)
_PAIR_MERGE = {
    "had_sex":            r"^(.+?)与(.+?)有私情。$",
    "had_sex_spouse":     r"^(.+?)与(.+?)同房。$",
    "became_lovers":      r"^(.+?)与(.+?)相恋。$",
    "became_lovers_spouse": r"^(.+?)与(.+?)相恋。$",
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
                elif spec["style"] == "allies":
                    # v78-3: 同月同盟友同敌手同战名的盟战应召并成一行
                    who = [s[0] for s in slots]
                    allies = {s[1] for s in slots}
                    foes = {s[2] for s in slots}
                    cbs = {(s[4] or "") for s in slots}
                    if len(allies) == 1 and len(foes) == 1:
                        tail = f"随{next(iter(allies))}出战，对抗{next(iter(foes))}"
                        if len(cbs) == 1 and next(iter(cbs)):
                            tail += f"，此役为{next(iter(cbs))}"
                        merged = _agg_line(ym, who, "", tail)
                else:
                    s0 = [s[0] for s in slots]
                    s1 = [s[1] for s in slots]
                    if len(set(s1)) == 1:
                        merged = _agg_line(ym, s0, spec["verb"], "先后与" + s1[0])
                    elif len(set(s0)) == 1:
                        merged = _agg_line(ym, s1, spec["verb"], "先后与" + s0[0])
                if merged:
                    _rec = {"date": ym, "type": typ, "text": merged,
                            "module": entries[0].get("module", "")}
                    if any("own_birth" in e for e in entries):
                        _rec["own_birth"] = all(e.get("own_birth") is not False
                                                for e in entries)
                    out.append(_rec)
                    continue
        out.extend(entries)
    return _merge_affair_pairs(out, f)


def _merge_affair_pairs(events, f=None):
    """「私情+相恋」成对合并 (v15): 同一月内同一对的 had_sex 与 became_lovers
    并成一行: '869年1月，麦克·汤利与吉塞勒·加洛林私通相恋。' (成对事件
    拆两行浪费模型注意力, 且两行日期只差一天)。

    v31 (问题2): 配偶对按 `had_sex_spouse` / `became_lovers_spouse` 句形识别,
    并作「夫妻情笃」一行, 事件类型也换成 `_spouse` 变体 (概览/模块随之改档)。"""
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
        base = typ[:-len("_spouse")] if typ.endswith("_spouse") else typ
        key = (ym, frozenset((m.group(1), m.group(2))))
        slots.setdefault(key, {})[base] = (body, full, typ.endswith("_spouse"))
    drop = set()
    merged = []   # (ym, text, type)
    for (ym, _pair), got in slots.items():
        hx = got.get("had_sex")
        lv = got.get("became_lovers")
        if not hx or not lv:
            continue
        hx_body, hx_full, hx_spouse = hx
        lv_body, lv_full, lv_spouse = lv
        spouse = hx_spouse and lv_spouse
        pat = _PAIR_MERGE["had_sex_spouse" if spouse else "had_sex"]
        m = re.match(pat, hx_body)
        if not m:
            continue
        y, _, mm = ym.partition(".")
        if spouse:
            text = _FACT_WORDING["affair_pair_spouse"].format(
                y=y, m=int(mm), a=m.group(1), b=m.group(2))
            typ_out = "became_lovers_spouse"
        else:
            text = f"{y}年{int(mm)}月，{m.group(1)}与{m.group(2)}私通相恋。"
            typ_out = "became_lovers"
        merged.append((ym, text, typ_out))
        drop.add(hx_full)
        drop.add(lv_full)
    if not merged:
        return events
    out = [e for e in events if e["text"] not in drop]
    for ym, text, typ_out in merged:
        out.append({"date": ym, "type": typ_out, "text": text,
                    "module": _TYPE2MODULE.get(typ_out, "情变私通")})
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
    # v44 (问题1): 家族名按本篇截止日取沿革之值 —— 传主别立家族/家族改名后,
    # 【家族】行、名号句与家格句三处必须同源 (旧稿一律取缓存首见值「诺兰」)。
    _dn, _hn = f._house_names_at(pid, f.as_of)
    p = {
        "name": f.name_with_regnal(pid, f.as_of),  # v17: 带世系编号; v44: 按篇截止日
        "name_zh": rec.get("name_zh") or "",
        # v14: 宗族名 (东方名序的姓) + 家族/分家 (风味补充, 与宗族不同时给出)
        "house": _dynasty_display(_dn, _hn),
        "house_branch": _house_branch(_dn, _hn),
        # v81 (问题1): 按文化/名序组装的全篇唯一家族称法 (平氏下北沢家 /
        # 斯卡利茨施氏 / 菲利普，顿巴斯)
        "house_label": house_label(_dn, _hn, f.name_order(pid),
                                   (f._culture_entry(pid, f.as_of) or {})
                                   .get("culture_template")),
        "birth": f.date(rec.get("birth")),
        "culture": f.culture(pid, f.as_of),
        "faith": f.faith(pid),
        # v31 (问题1): 「为人」按类别分句 (性情/才具/阅历…), 不再一顿号串
        "traits": f.traits_sentence(pid, public=True),
        "government": f.government(pid),
    }
    # v11: 角色语言 (语言：诺斯语、阿拉伯语)
    langs = f.languages(pid)
    if langs:
        p["languages"] = "、".join(langs)
    # v27: 语言风味 — 母语/兼通 + 与妻室子女的言语异同
    # v44 (问题4): 母语按篇截止日取 (早年篇的族属与母语须一致)
    p["language_line"] = f.language_sentence(pid, f.as_of)
    p["language_bridge"] = f.language_bridge_line(pid)
    # v28: 与妻室子女的逐人言语关系句 (程序直给「相通/须通译」结论)
    _lrel = f.language_relation_lines(pid)
    if _lrel:
        p["language_relations"] = _lrel
    # v9: 主角官职名 (v11: 按 as_of 截断日期取)
    poff = f.official_title(pid)
    if poff:
        p["office"] = poff
    # v28b: 称谓统一 — 档案名号句由 facts 一次组好 (biography 不再拼 office+name)
    p["label"] = f.person_label(pid, date=f.as_of, style="brief") or p["name"]
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
    # v30: 族属变迁 (问题1 — 游戏不为改宗留记忆, 逐档 culture 差分)
    chl = f.culture_history_lines(pid)
    if chl:
        p["culture_history"] = "；".join(chl)
    # v44 (问题1): 家格沿革 (别立家族 / 家族改名)
    hhl = f.house_history_lines(pid)
    if hhl:
        p["house_history"] = hhl
    # v44 (问题2): 传主链 (前任/后任传主与继位日)
    scl = f.succession_lines()
    if scl:
        p["succession"] = scl
    # v7: 家族家训 + 宫廷/营地官职
    mot = f.motto()
    if mot:
        p["motto"] = mot
    cpl, _cpch = f.court_positions_lines()
    if cpl:
        # v23: 主语=任职者 (仲宣任丑角…；德方任私人医生…), 组间以「；」分隔
        p["court_positions"] = "；".join(cpl)
    # v36 (问题2, 用户拍板3): 主角**获授**的朝廷职位 (太师等) — 与上面的僚属花名册分列,
    # 同时进《传主档案》与《朝局风云录》(realm facts 侧同源)。
    col, coch = f.court_office_lines()
    if col:
        p["court_office"] = "；".join(col)
    if coch:
        p["court_office_changes"] = "；".join(coch)
    # v11: as_of 早于末档时, 直辖/封臣/营规等明细是「后期快照」数据, 不进入提示词
    # (只做头衔维度; 明细维度如要按时期需另行逐年快照, 成本高暂不做)
    skip_detail = bool(f.as_of) and cl.date_key(f.as_of) < cl.date_key(
        cache.get("last_date") or f.as_of or "9999.9.9")
    ld = rec.get("landed") or {}
    gov = ld.get("government")
    # v11: 无地/有地分支按 as_of 首要头衔判定 (十年传记穿越时, 缓存 landed 是末档数据)
    ptier, ptid = f._primary_title_at(pid)
    # v41b (用户指正: 「认为他直接从无地变成行政制」): `ld` 是缓存**末档**数据,
    # 十年传记穿越到早年时政体读错 (1077 写行政制、1087 写行政制, 实为冒险者/封建制)。
    # 一律按 as_of 取 (逐档政体史), 查不到才回退末档。
    gov_asof = f._character_government(pid, f.as_of) or gov or ""
    # v28: 政体原始键 (提示词侧按政体换措辞用: 天朝制/行政制=官职轮转)
    p["government_key"] = gov_asof
    # v28: 只有**真·无地冒险者营地** (x_d_laamp_/雇佣团/教团) 才走营地分支;
    # 世族庄园 (x_nf_) 与游牧毡帐 (x_c_nomad_) 是家业/驻地, 不走营地分支。
    if f.title_kind(ptid) == "camp" or gov_asof == "landless_adventurer_government":
        # ---- 无地冒险者: 营地 ----
        p["landless"] = True
        camp_tid = ptid if f.title_kind(ptid) == "camp" \
            else (ld.get("domain") or [None])[0]
        if camp_tid is not None:
            p["camp_name"] = f._title_name_at(camp_tid, f.as_of) or "冒险者营地"
        else:
            p["camp_name"] = "冒险者营地"
        # 营地细节仅当缓存 landed 确为营地 (非 as_of 穿越) 时渲染
        if gov_asof == "landless_adventurer_government" and not skip_detail:
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
                        # v29b: 头衔与持有人直连 (「幽蓟路李黯」), 不用括注同位语
                        parts.append(f"{tn}{hn}" if hn else tn)
                    p["camp_liege_chain"] = "、".join(parts)
                top_tid, top_holder = chain[-1]
                p["camp_top_liege"] = f"{f.title(top_tid)}{f.name_or(top_holder)}" \
                    if top_holder is not None else f.title(top_tid)
    else:
        # ---- 有地领主 / 世族 ----
        # v28: 世族庄园 (x_nf_/c_nf_) — 家业身份, 与「无地冒险者营地」分列;
        # 取 as_of 仍在持有的庄园 (十年传记不回退到末档数据)。
        # v41b (用户拍板2: 「只在无地/仅持庄园时写」): 首要头衔为领地 (c_ 及以上)
        # 时**不写**庄园句 —— 诺兰是皇帝, 旧稿把这句无日期的「世族庄园「诺兰家族」，
        # 主人称乡绅，庄园在亚琛」摆进档案, 模型便拿它当了 1048 年的产房与
        # 一生门第; 有地领主的主线由「政体/历任」承担 (冒险者营地 → 帝国)。
        if ptier is None:
            for _etid, _ivs in (f._hold_intervals(pid) or {}).items():
                if _ivs and _ivs[-1][1] is None and f._is_estate_title(_etid):
                    p["estate_name"] = f._title_name_at(_etid, f.as_of) or "家族庄园"
                    p["estate_word"] = f.estate_kind_word(_etid, pid)
                    p["estate_holder"] = f._estate_holder_word(pid)
                    # v36 (问题4): 庄园驻地州府 (家业在宾州 — 与官职治所吉昌县两处地方)
                    _ep = f.estate_place_name(pid)
                    if _ep:
                        p["estate_place"] = _ep
                    # v41b: 立族日 (晚于出生才写出 —— 出生后所立的家业不是他的产房;
                    # 诺兰家族头衔 1094.5.28 created)
                    _eg = _ivs[-1][0]
                    _bd = rec.get("birth")
                    if _eg and _bd and cl.date_key(_eg) > cl.date_key(_bd):
                        p["estate_since"] = f.date(_eg)
                    break
        if ld and not skip_detail:
            p["ruler_since"] = f.date(ld.get("became_ruler_date"))
            # v31 (问题8): 首府男爵领由所辖伯爵领蕴含, 折叠后再出「直辖N地」
            # v54 (问题1, 用户拍板): 直辖 = 最高头衔(同层级全留) + 实控伯爵领;
            # 次级公国/王国不再并列 (见 domain_titles 文档串)
            keep, _folded = f.domain_titles(ld.get("domain") or [])
            dom = []
            for tid in keep:
                t = f.title(tid)
                if t:
                    dom.append(t)
            p["domain"] = "、".join(dom)
            p["domain_count"] = len(keep)
            cap = f.title(ld.get("realm_capital"))
            if cap:
                p["capital"] = cap
            # v81 (问题5, 用户 2026-09-29): 零值不下发 —— 「封臣0人」把模型的注意力
            # 引到「他没有封臣」这件无事发生的事上; 无封臣即不出这一分句。
            _vcount = int(ld.get("vassal_count") or 0)
            if _vcount:
                p["vassal_count"] = _vcount
            # v29: 御前会议席位改用动态官职名 + 大臣名 (解析不到则整句不发)
            cl_line = f.council_line()
            if cl_line:
                p["council"] = cl_line
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
                _dtype == "camp" or gov_asof == "landless_adventurer_government")

            # v29: 牧群 (游牧货币) 数值不下发; 口粮 (营地补给) 改档位词
            if _dom and _is_camp and _dom.get("provisions") is not None:
                w = provisions_band(_dom.get("provisions"))
                if w:
                    p["provisions_word"] = w
    # 现状 (仅在世**且未让位**时; v76: 让位者按「位已终」写收句, 不再报在任现状)
    if not cache.get("player_death") and not cache.get("reign_end"):
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
        # v29: 财务与信仰数值一律档位化 (用户决策 2026-09-11):
        # 国库金、月入、牧群等货币数值整项不下发; 虔诚/威望/影响力/功勋取游戏档位词
        # (defines LEVELS_* + 本地化 <kind>_level_N: 戴罪之人/崭露头角/七品…)。
        for kind, label in (("piety", "虔诚"), ("prestige", "威望"),
                            ("influence", "影响力"), ("merit", "功勋")):
            v = (ad.get(kind) or {}).get("currency")
            w = L.level_word(f.table, f._bands, kind, v)
            if w:
                # v39: 档位词字面已含标签时只出档位词 —— piety_level_2 = 「虔诚信者」,
                # 旧写法拼成「虔诚虔诚信者」(诺兰 22:36 请求实测)。
                bits.append(w if label in w else f"{label}{w}")
        if bits:
            p["status"] = "，".join(bits) + "。"
    # 死亡 (终传时; v11: as_of 早于死期视为在世, 十年传记不泄漏「死于…」)
    # v76 (问题1): 让位 (reign_end) 优先 —— 用户 2026-09-27 拍板「让位即终了,
    # 日后死亡只进缓存给后续篇目的家庭信息用」, 故两档都有时本篇只写让位句。
    re_end = cache.get("reign_end")
    if re_end and f.as_of \
            and cl.date_key(f.as_of) < cl.date_key(re_end.get("date") or "9999.9.9"):
        re_end = None                      # 十年档早于让位日 ⇒ 该档不谈让位
    pd = cache.get("player_death")
    if pd and re_end and cl.date_key(pd.get("date") or "0.0.0") \
            > cl.date_key(re_end.get("date") or "9999.9.9"):
        pd = None                          # 让位之后的死亡不进本篇
    if pd and f.as_of and cl.date_key(f.as_of) < cl.date_key(pd.get("date") or "9999.9.9"):
        pd = None
    if re_end:
        p["reign_end"] = f"{f.reign_end_clause(pid, re_end)}。"
    elif pd:
        p["death"] = (
            f"死于{f.date(pd.get('date'))}，"
            f"{f.death_clause(pid, date=pd.get('date'), reason=pd.get('reason'), killer=pd.get('killer'))}。"
        )
        # v81 (问题6, 用户 2026-09-29): 卒地 (男爵领) —— 与《刺客列传》的
        # `victim_place` 同一出口, 取不到即整项略去 (无料不下发)。
        # ⚠ 必须与 `p["death"]` **同闸** (`elif pd:`) —— 主角自己的
        # `characters[pid]["death"]` 是空的 (死亡只写在 `cache["player_death"]`),
        # 而 `victim_place` 的第三源 `last_location` 不受 as_of 约束; 无条件算会把
        # **未来**的卒地漏进早年的十年传记 (实测 as_of=970.1.1 就多出一行「卒地亚眠」)。
        _dp = f.death_place(pid)
        if _dp:
            p["death_place"] = _dp
        # v84 (用户 2026-09-29 拍板「人都死了, 历程几个站、预计什么时候到哪根本不重要」):
        # 卒前那一档仍在旅途者, 把「启程日 + 自X启程 + 赴Y 干什么 + (途中/返程途中)」
        # 直接**并进卒句**, 不另出一行、不写站数与预计到达:
        #   「1002年7月15日自秋田启程，赴坎特伯雷主办院校访学，途中死于1006年8月7日，酗酒而亡。」
        # 与 `p["death"]` 同闸 (`elif pd:`); 取不到启程日/目的地时 `transit_death_clause`
        # 返回 '' ⇒ 卒句逐字不变 (零回归)。数据见 `Facts.transit_facts`。
        _tr = f.transit_facts(pid)
        if _tr:
            p["transit"] = _tr
            _tc = f.transit_death_clause(_tr)
            if _tc:
                p["death"] = _tc + p["death"]
    # v81 (问题6, 用户 2026-09-29): 生卒之地 (男爵领) —— 卒地与 `p["death"]` 同闸,
    # 生地取本人首见快照 (见 `birth_place` 的判据), 取不到即整项略去。
    _bp = f.birth_place(pid)
    if _bp:
        p["birth_place"] = _bp
    # 家庭 (v11: as_of 截断 — 出生晚于 as_of 的未出生者不列)
    fam = rec.get("family") or {}
    # v60 (问题3): 先并入婚配闩存 —— 主角自身的 family_data 在死亡档被清空,
    # 而配偶/妾的反向指针逐档在册; 不并这一层, 「一生无正妻、只有三名强纳
    # 之妾」在事实面就退化成一片空白, 模型遂自行虚构妻室。
    fam = f.merge_spouse_latch(fam, f.as_of)
    rec["family"] = fam
    # v13: 妻妾与父系婚姻史交叉标注 — 「先为父之妻/妾, 后归子」的戏剧性关系
    father_id = (fam.get("father") or [None])[0]
    fd_fam = {}
    if father_id is not None:
        fd_fam = ((cache.get("characters") or {}).get(str(father_id)) or {}).get("family") or {}

    def _annotate(ids, lineality=False):
        out = []
        noted = False
        for sid in ids:
            nm = f.kin_label(sid, f.as_of)
            if not nm:
                continue
            note = ""
            if father_id is not None and sid != father_id:
                for k, label in (("primary_spouse", "妻"), ("spouse", "妻"),
                                 ("concubine", "妾"), ("former_spouses", "前妻"),
                                 ("former_concubines", "前妾")):
                    if sid in (fd_fam.get(k) or []):
                        # v55 (问题2): 去括注 —— 补注作同句分句, 故并列改用「；」
                        note = (f"，原为父{f.kin_label(father_id, f.as_of)}"
                                f"之{label}")
                        break
            # v43: 母系婚 (入赘) 的配偶行补线系与子女归属
            if lineality:
                note += f.marriage_lineality_note(pid, sid, before=f.as_of)
            if note:
                noted = True
            out.append(nm + note)
        # 有人带补注时并列用「；」, 免与补注内的「，」相混
        return ("；" if noted else "、").join(out)

    spouse_ids = list(dict.fromkeys(
        _asof_ids(f, (fam.get("primary_spouse") or []) + (fam.get("spouse") or []))))
    # v43: 成婚日晚于本篇截止日者不列 (末档配偶状态穿越)
    spouse_ids = f._spouses_asof(pid, spouse_ids)
    # v76 (问题2, 用户拍板④「全部篇目都裁」): 再按**本篇窗口**裁掉窗口内已非妻妾者
    # (十年档窗口 = 上一个十年截止日 → as_of; 终传/在世 = 战役起点 ⇒ 恒不裁)
    spouse_ids = f.spouses_in_window(spouse_ids)
    p["spouses"] = _annotate(spouse_ids, lineality=True)
    # v70 (用户 2026-09-27 拍板: 「姐姐姐姐一类的重复一起改掉」): 同一人只进一个
    # 婚配档 —— 存档 `family_data` 的 `former_spouses`/`former_concubines` 会把
    # **现配偶一并列出** (实测 伍尔夫克尔: 妻室善江·敬直斯多蒂尔, 前妻又列她一人;
    # 温映娘: 「夫瓯王愚者韩元佶、夫韦鲁、前夫韦鲁、前夫瓯王愚者韩元佶」两份互为
    # 倒序), 旧稿四档各自成形, 于是档案行出「妻室X、前妻X」。优先序 = 打印序:
    # 妻室 > 前妻 > 妾 > 前妾。
    _sp_set = set(spouse_ids)
    _former_sp = [x for x in _asof_ids(f, fam.get("former_spouses") or [])
                  if x not in _sp_set]
    _former_sp = f.spouses_in_window(_former_sp)          # v76: 同窗口口径
    p["former_spouses"] = _annotate(_former_sp)
    # v8: 妾 (正向 concubine + 反向 concubinist, 已在缓存合并去重)
    _seen_mar = _sp_set | set(_former_sp)
    _conc = [x for x in _asof_ids(f, fam.get("concubine") or [])
             if x not in _seen_mar]
    _conc = f.spouses_in_window(_conc)                    # v76: 同窗口口径
    p["concubines"] = _annotate(_conc)
    _seen_mar |= set(_conc)
    _fconc = [x for x in _asof_ids(f, fam.get("former_concubines") or [])
              if x not in _seen_mar]
    _fconc = f.spouses_in_window(_fconc)                  # v76: 同窗口口径
    p["former_concubines"] = _annotate(_fconc)
    child_ids = [c for c in _asof_ids(f, fam.get("child") or []) if f.name(c)]
    # v34 (问题8, 用户拍板): 家门清单列**主角是法理父亲的**全部子女
    # (非婚生亦在内); 法理父是别人的孩子 (妻室与他人所出) 不进本纪的门门清单,
    # 由《家室列传》作「妻子的子女」交代。
    # (无家谱数据时保留原名单, 不把「无数据」当成「无子女」。)
    _legal, _has_fam = f.legal_children_ex(pid)
    if _has_fam:
        child_ids = [c for c in child_ids if c in _legal]
    _wife_other = f.wife_other_children(pid)
    _wo_line = f.wife_other_children_line(pid, _wife_other) if _wife_other else ""
    if _wo_line:
        p["wife_other_children"] = _wo_line
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
    # v45 (档 B): 本档案家世行**已点名**的亲属 id 集 —— 板块期据此判定
    # 「此人的亲缘已经写明」, 后面不再重复加定语 (KinScope.seed)。
    p["kin_ids"] = sorted({int(x) for x in (
        list(spouse_ids) + list(_former_sp) + list(_conc) + list(_fconc)
        + list(child_ids) + list(_wife_other or ())
        + list(fam.get("father") or []) + list(fam.get("mother") or [])
        + list(fam.get("siblings") or [])) if isinstance(x, int)})
    # v5: 自定义角色 (无谱系) — 家世通用文本覆盖
    if f.is_custom_start(pid):
        p["custom_start"] = True
    # v5: 真正父亲 (私生子场景; 与法理父不同才渲染)
    # v74 (问题3, 用户拍板): 判据改为**按 id 与法理父比对** —— 公开私生的孩子
    # `real_father == father` (游戏 `on_action/child_birth_on_actions.txt:781-817`
    # 在 `is_bastard = yes` 的同一分支里 `set_father = scope:real_father`), 生父就是父,
    # 不另出「实父」; 只有真托卵 (`father != real_father`, 田所档方子) 才下发。
    # 旧稿无条件写 `p["real_father"]`, 配合「父」行被抑制, 把九位公开私生写成
    # 「另有一个法理父」。见 docs/方案_v74_田所三问题.md §3.3。
    _father_ids = {int(x) for x in (fam.get("father") or [])
                   if isinstance(x, int)}
    rf = (fam.get("real_father") or [None])[0]
    if rf is not None and int(rf) not in _father_ids:
        rfname = f.kin_label(rf)
        if rfname:
            p["real_father"] = rfname
            if isinstance(rf, int):
                p["kin_ids"] = sorted(set(p["kin_ids"]) | {rf})
    # 主角历任 (v11: 主要头衔演进)
    ht = f.held_titles(pid)
    if ht:
        p["titles_held"] = "；".join(ht)
    # v41 (问题1): 政体变更句 (改行行政官制等) — 只在确有变化时出句
    gc = f.government_changes(pid)
    if gc:
        p["government_change"] = gc
    # v41 (问题5): 宗族宗支句 (分家与宗族不同名时)
    cl_ = f.clan_line(pid)
    if cl_:
        p["clan_line"] = cl_
    # v41 (问题6): 共治者括注 (「（共治巴西琉斯）」)
    cor = f.co_ruler_note(pid, date=f.as_of)
    if cor:
        p["co_ruler"] = cor
    # v53 (问题3): 天命局势一行
    dc = f.dynastic_cycle_line(f.as_of)
    if dc:
        p["dynastic_cycle"] = dc
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
    # v31 (问题4/6): 主角配偶的情人/灵魂伴侣 — 妻室情事脉络与情人档案的取材对象
    # (乔乔/佩拉约此前完全不在档案集, 模型只能写「其职衔、族属，仅存其名」)。
    prec = (f.cache.get("characters") or {}).get(str(pid)) or {}
    pfam = prec.get("family") or {}
    for sid in dict.fromkeys(
            [x for x in (pfam.get("primary_spouse") or [])
             + (pfam.get("spouse") or [])
             + (pfam.get("former_spouses") or [])
             + (pfam.get("concubine") or [])
             + (pfam.get("former_concubines") or []) if isinstance(x, int)]):
        srec = (f.cache.get("characters") or {}).get(str(sid)) or {}
        for m in srec.get("memories") or []:
            slot = _AFFAIR_SLOTS.get(m.get("type"))
            if not slot:
                continue
            other = (m.get("participants") or {}).get(slot)
            if isinstance(other, int) and other not in (pid, sid):
                out.setdefault(other, 2)
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
            # v81 (问题1): 按文化/名序组装的全篇唯一家族称法
            "house_label": house_label(rec.get("dynasty_name"),
                                       rec.get("house_name"),
                                       f.name_order(cid),
                                       (f._culture_entry(cid, f.as_of) or {})
                                       .get("culture_template")),
            "birth": f.date(rec.get("birth")),
            "culture": f.culture(cid),
            "faith": f.faith(cid),
            # v31 (问题1): 按类分句 (与主角档案同口径)
            "traits": f.traits_sentence(cid, public=True),
        }
        # v31 (问题6): 主角廷中身份 — 骑士/廷臣 + 入宫日 (乔乔/佩拉约等妻室情人
        # 正是主角廷中骑士; 旧档案里这一身份完全缺席)。玩家**自家人**不写这一句
        # (妻室子女的档案行不必都挂一句「廷臣」)。
        _pid0 = f.cache.get("player_id")
        _is_kin = False
        if _pid0 is not None and int(cid) != int(_pid0):
            _prec0 = (f.cache.get("characters") or {}).get(str(_pid0)) or {}
            _pfam0 = _prec0.get("family") or {}
            _kin = set()
            for _k in ("primary_spouse", "spouse", "former_spouses", "child",
                       "concubine", "former_concubines", "father", "mother",
                       "siblings", "ever_spouses"):
                _kin.update(x for x in (_pfam0.get(_k) or []) if isinstance(x, int))
            _is_kin = int(cid) in _kin
            if not _is_kin:
                _csp = f.court_service_phrase(cid)
                if _csp:
                    prof["court_service"] = _csp
        # v11: 角色语言
        langs = f.languages(cid)
        if langs:
            prof["languages"] = "、".join(langs)
        # v29: 语言事实句 (母语/兼通) 只给主角本人 (用户决策 2026-09-11:
        # 「母语」描写过滥, 家人之间言语相通属常识); 其余角色仅在「与主角无共通语」
        # 时由 language_relation 句带出其语言清单 — 故此处不再写 prof["language_line"]。
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
        # v28b: 称谓统一 — 档案名号句由 facts 一次组好
        prof["label"] = f.person_label(cid, date=f.as_of, style="brief") or name
        # v41 (问题5): 宗族宗支句 (分家与宗族不同名时点明同宗)
        _cl = f.clan_line(cid)
        if _cl:
            prof["clan_line"] = _cl
        # v41 (问题6): 共治者括注 (「（共治巴西琉斯）」)
        _cor = f.co_ruler_note(cid, date=f.as_of)
        if _cor:
            prof["co_ruler"] = _cor
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
        # v30: 族属变迁 (问题1)
        chl = f.culture_history_lines(cid)
        if chl:
            prof["culture_history"] = "；".join(chl)
        # v7: 该角色在玩家宫廷/营地中的官职 (最新快照, 反向取最后一年)
        # v29: 显示名按玩家宫廷的政体变体取 (私人医生 → 医学博士)
        for h in reversed(f.cache.get("court_positions") or []):
            for p in h.get("positions") or []:
                if p.get("employee") == cid:
                    zh = f.court_position_word(p.get("type")) or ""
                    if zh and zh != p.get("type"):
                        prof["court_position"] = zh
                    break
            if prof.get("court_position"):
                break
        fam = rec.get("family") or {}
        spouse_ids = list(dict.fromkeys(
            _asof_ids(f, (fam.get("primary_spouse") or []) + (fam.get("spouse") or []))))
        # v43: 成婚日晚于本篇截止日者不列 (同 _protagonist_facts 口径)
        spouse_ids = f._spouses_asof(cid, spouse_ids)
        # v27: 亲属一律「头衔+姓名」(kin_label), 不再只给姓名
        # v43: 母系婚 (入赘) 的配偶逐人补线系与子女归属
        prof["spouses"] = "、".join(
            f.kin_label(s) + (f.marriage_lineality_note(cid, s, before=f.as_of) or "")
            for s in spouse_ids if f.name(s))
        prof["concubines"] = "、".join(
            f.kin_label(s) for s in _asof_ids(f, fam.get("concubine") or []) if f.name(s))
        _conc_ids = list(_asof_ids(f, fam.get("concubine") or []))
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
        # v29 (问题5): 主角子女的档案不再重复家世名单 —
        #   「兄弟姊妹」与主角其余子女完全同集 (主角档案已列全), 同批名单此前
        #   在家室档案里按人重复 8 次; 「父」为主角时一并省去 (保留「母」以辨生母)。
        _pid = f.cache.get("player_id")
        _prec = (f.cache.get("characters") or {}).get(str(_pid)) or {}
        _pchildren = {int(x) for x in ((_prec.get("family") or {}).get("child") or [])}
        _is_pchild = int(cid) in _pchildren
        _fathers = [x for x in (fam.get("father") or []) if f.name(x)]
        _fids = {int(x) for x in (fam.get("father") or []) if isinstance(x, int)}
        if not (_is_pchild and _pid in _fathers):
            prof["father"] = "、".join(f.kin_label(x) for x in _fathers)
        prof["mother"] = "、".join(
            f.kin_label(x) for x in (fam.get("mother") or []) if f.name(x))
        # v74 (问题3 C4, 用户拍板「公开私生不需要专门写」—— 本条只写**生母的婚配
        # 身份**, 不写孩子是否私生): 生母在**孩子出生时**另有配偶 (该配偶不是孩子的父)
        # 时, 记一句生母的婚配身份 (多家取门第最高的那位), 由 `biography._profile_lines`
        # 只在**内宅档** (with_real_parentage) 追加到「母」行后。
        # 本档最有戏的一层关系即此: 田所浩二的情人 藤原高子 / 大和忠子 都是
        # **前任天皇大和惟仁之妻**, 所生子女随田所氏 (见方案 §3.6)。
        # 「出生时仍在婚」判据 (全由缓存记忆/字段直算, 不猜):
        #   ① 有 `married` 记忆者: 成婚日 ≤ 孩子生日 (成婚日晚于出生的排除);
        #   ② 无 `married` 记忆者 (实测 藤原高子 × 大和惟仁 即此类, 婚姻早于缓存
        #      窗口): 以「该配偶在孩子出生时仍在世」为准 —— 该配偶在孩子出生前已卒
        #      即婚配已终 (藤原珍子 × 橘良根: 良根 871 卒, 其子女皆 874 后出生, 排除)。
        _mom = (fam.get("mother") or [None])[0]
        _birth = str(rec.get("birth") or "")
        if _is_pchild and isinstance(_mom, int) and _birth:
            _chars = f.cache.get("characters") or {}
            _mrec = _chars.get(str(_mom)) or {}
            _mfam = _mrec.get("family") or {}
            _cand = []
            for _s in dict.fromkeys(
                    list(_mfam.get("spouse") or [])
                    + list(_mfam.get("former_spouses") or [])
                    + list(_mfam.get("primary_spouse") or [])):
                if not isinstance(_s, int) or _s in _fids or not f.name(_s):
                    continue
                _wd = f.wedding_date(_mom, _s)
                if _wd and cl.date_key(_wd) > cl.date_key(_birth):
                    continue
                _sd = ((_chars.get(str(_s)) or {}).get("death") or {}).get("date")
                if _sd and cl.date_key(_sd) < cl.date_key(_birth):
                    continue
                _cand.append(_s)
            if _cand:
                def _rank_(sid):
                    _t, _tid = f._primary_title_at(sid, as_of=f.as_of)
                    return f._eff_rank(_tid) if _tid is not None else -1
                _best = max(_cand, key=_rank_)
                _rel = f._consort_word(_best, _mom)
                _bl = f.kin_label(_best)
                if _rel and _bl:
                    # 不带括注 (项目铁律: 事实面无「名词（名词）」括注同位语) ——
                    # 由 `biography._profile_lines` 作为独立一句下发。
                    prof["mother_note"] = f"生母为{_bl}之{_rel}。"
        if not _is_pchild:
            prof["siblings"] = "、".join(
                f.kin_label(x) for x in (fam.get("siblings") or []) if f.name(x))
        # v5: 自定义角色 + 真正父亲 (私生子)
        if f.is_custom_start(cid):
            prof["custom_start"] = True
        # v74 (问题3): 同 `_protagonist_facts` —— 只在**真托卵** (`father != real_father`)
        # 时下发「实父」; 公开私生的 `real_father == father`, 不写「实父」。
        rf = (fam.get("real_father") or [None])[0]
        if rf is not None and int(rf) not in _fids:
            rfname = f.kin_label(rf)
            if rfname:
                prof["real_father"] = rfname
        # v45 (档 B): 本档案家世行已点名的亲属 id 集 (见 _protagonist_facts 同名字段)
        prof["kin_ids"] = sorted({int(x) for x in (
            list(spouse_ids) + list(_conc_ids) + list(child_ids)
            + list(fam.get("father") or []) + list(fam.get("mother") or [])
            + list(fam.get("siblings") or [])
            + ([rf] if isinstance(rf, int) else [])) if isinstance(x, int)})
        ht = f.held_titles(cid)
        if ht:
            prof["titles_held"] = "；".join(ht)
        # v74 (问题1, 用户拍板「腾位置只针对《家室列传》」): 主角子女的**承位句** ——
        # 其现任头衔的前任里, 连续一串死于主角之手的那些人 (「刀下亡魂是为了给
        # 我的孩子腾位置」)。只随子女档案下发 (家室档案/阴私录), 不进《刺客列传》。
        if _is_pchild:
            _sn = f.seat_note(cid)
            if _sn:
                prof["seat_note"] = _sn
        mems = []
        # v26: 取缓存记忆 (此前写 prof.get("memories"), 而 prof 无该键 →
        # 「传主行迹」对所有人恒为「（无行迹记录）」)
        # v58 (问题8): 先做「继承合句」配对 —— 被消费的死讯/承袭记忆不再单独成行
        _ipairs = f.inherit_pairs(cid)
        _iconsumed = set()
        for _line, _ids, _dd in _ipairs.values():
            _iconsumed |= _ids
        for mem in rec.get("memories") or []:
            if id(mem) in _iconsumed:
                continue
            # v59 (问题2, 用户拍板): 性事 (同房/私通/强迫·半推半就) 不进角色档案的
            # 「行迹」 —— 档案是各篇共用的公开数据 (家室档案也在共享前缀里),
            # 性事只在《列传·好友》《列传·仇人》的【相关年表】里出现
            # (那一路走 `facts["timeline"]`, 见 `_timeline` 的闸)。
            if is_sex_memory(mem.get("type")):
                continue
            s = _mem_sentence(f, cid, mem)
            if not s:
                continue
            # v11: as_of 截断 — 十年传记只列该时期前的事件
            # v34b: 日期取事实日 (头衔得失用 title history 事件日)
            _md = f.mem_date(cid, mem)
            if f.as_of and _md and cl.date_key(_md) > cl.date_key(f.as_of):
                continue
            mems.append(f"{f.date(_md)}，{s}")
        for _line, _ids, _dd in _ipairs.values():
            mems.append(f"{f.date(_dd)}，{_line}")
        mems.sort()
        prof["events"] = mems
        # v29 (问题4): 「传主行迹」用省主语版 — 块内主语恒为传主, 重复姓名无信息。
        # v64 (问题5 连带): 剥离键仍取档案称谓 (旧行为逐字不变), 但另备一条
        # **去掉勋号前缀**的同形键 —— 勋号随时点变化 (某人在事件当日还没戴上,
        # 而档案称谓按篇末取), 只用档案称谓做键会剥不掉, 省主语版里于是重新冒出
        # 一个光秃秃的主语名 (实测 5 例: 阿农德尔·塞卡尔 / 富兰克林·崔佛松等)。
        _subj = prof.get("label") or name
        _alts = []
        _acc = f.accolade_word_at(cid, f.as_of)
        if _acc and _acc in _subj:
            _alts.append(_subj.replace(_acc, "", 1))
        prof["events_subjectless"] = [
            _strip_subject_prefix(x, _subj, _alts) for x in mems]
        # v31: 死亡句按 as_of 截断 — 十年传记不写十年末之后的死 (旧文本把 878.3.17
        # 的死写进截至 878.01.01 的十年传; 时间线本有截断, 只有档案漏了)
        _dd = (rec.get("death") or {}).get("date")
        if not (f.as_of and _dd and cl.date_key(_dd) > cl.date_key(f.as_of)):
            ds = _death_sentence(f, cid)
            if ds:
                prof["death"] = ds
            # v81 (问题6, 用户 2026-09-29 拍板): 卒地只写**主角的家族成员** ——
            # 其他人的卒地已由《刺客列传》的 `victim_place` 承担 (那一处早就做了),
            # 档案行不必逐人再挂一遍。
            if _is_kin:
                _dp = f.death_place(cid)
                if _dp:
                    prof["death_place"] = _dp
        # v81 (问题6): 生地同样只写家族成员 —— 本人首见快照所在, 见 `birth_place`
        if _is_kin:
            _bp = f.birth_place(cid)
            if _bp:
                prof["birth_place"] = _bp
        # v75 (凶手点名): 死者档案带公开性旗标 (供板块期与快照复核)
        prof["killer_public"] = f.killer_is_public(cid)
        out[str(cid)] = prof
    return out


def _campaign_start(f):
    """战役起点 (开局日, v68 问题1) —— 本战役各传主缓存 `sources` 首档的最小值。

    为什么不能只看本缓存: 每份缓存只覆盖自己当玩家的那批档期 (实测菲利普2:
    崔佛 868–922 / 富兰克林 923–930 / 卡尔 931–954 / 尼克 955–976 /
    伍尔夫克尔 978.1.1), 只读本缓存时《朝局风云录》的下界被砍到「本缓存首档 − 30 年」
    = 925, h_china 的唐 (—886.1.2) 与中华 (887.1.2–950.6.1) 两段整个落选,
    「改朝换代」一次也看不见 (用户问题1)。无 sources 时返回 None (调用方退回旧口径)。"""
    best = None
    for src in list((f.campaign or {}).values()) + [f.cache]:
        srcs = (src or {}).get("sources") or []
        if not srcs:
            continue
        d = str(srcs[0])
        try:
            if best is None or cl.date_key(d) < cl.date_key(best):
                best = d
        except Exception:
            continue
    return best


# v69 (用户 2026-09-27 拍板): 《XX历代记》每人的**即位缘由** —— 存档 `landed_titles.
# <tid>.history` 每条事件的 `type` 就是游戏自己的继位方式 (子代理取证 `logs/
# probe_v69_succ4.txt`: 20 种取值里除 `destroyed` 外**全部**是「取得」事件, 即事件的
# `holder` 是取得者; `destroyed` 的 `holder` 是失去者)。措辞取自游戏本地化
# (`game/localization/simp_chinese/`: succession_laws 「任命继承制」、
# memories_l_simp_chinese.yml:630-731 的 ascended_throne 各缘由句)。
# 无 type 的裸 holder 条目 = 常规继承 (CK3 存档即以此区分, 全局 32234 条)。
_SUCC_WORD = {
    "appointment_succession": "受任命继位",
    "appointment": "受任命",
    "abdication": "受禅继位",
    "faction_demand": "被派系拥立",
    "election": "被选举继位",
    "granted": "受封头衔",
    "conquest": "征服夺取",
    "conquest_claim": "凭宣称夺取",
    "conquest_holy_war": "借圣战夺取",
    "conquest_populist": "借民粹叛乱夺取",
    "usurped": "篡夺继位",
    "migration": "率部迁徙入主",
    "stepped_down": "因前任下台而继位",
    "revoked": "收回头衔",
    "leased_out": "承租头衔",
    "lease_revoked": "收回租约",
    "independency": "自立",
    "returned": "收回",
    "swear_fealty": "宣誓效忠",
    # v73: 记忆档 (`ascended_throne_memory.vars.reason`) 里有、头衔 history 不落的
    # 五种取法 —— 措辞照游戏原文 (`game/localization/simp_chinese/memories_l_simp_chinese.yml`
    # 的 `ascended_throne_memory_desc_intro_*`): `:633` 我继承了 / `:638` 我被选举来统治 /
    # `:640` 我购买了 / `:637` 我夺取了…的牧场 / 议和得位 (negotiated)。
    "inheritance": "继承",
    "purchased": "买得头衔",
    "seized_pastureland": "夺取牧场",
    "negotiated": "议得头衔",
    "created": "创建",
}
# 这些缘由写「从某某处…」(前任是同一枚头衔的上一任, 继承链可读)
_SUCC_FROM_PREV = (None, "appointment_succession", "abdication")


def _title_hist_events(f, tid, end=None):
    """头衔 history 的事件序列 [(date, holder|None, type|None)] (≤end)。

    `type` = 游戏记的继位方式 (无 = 常规继承); `holder` 为 None 表示该日头衔无主
    (毁弃/待封)。同日多事件 (列表形) 按存档原序展开 (v15 起既有口径)。"""
    t = f._lt.get(str(tid)) or {}
    hist = t.get("history") or {}
    out = []
    if not isinstance(hist, dict):
        return out
    for d, ev in sorted(hist.items(), key=lambda x: cl.date_key(x[0])):
        if end and cl.date_key(d) > cl.date_key(end):
            break
        for e in (ev if isinstance(ev, list) else [ev]):
            if isinstance(e, dict):
                out.append((d, e.get("holder"), e.get("type")))
            else:
                out.append((d, e, None))
    return out


def _title_holder_seq(f, tid, end=None):
    """头衔 history 的持有者序列 [(date, holder|None)] (≤end)。

    `holder` 为 None 表示该日头衔无主 (毁弃/待封), 供调用方截断上一任的任期。"""
    return [(d, h) for d, h, _ty in _title_hist_events(f, tid, end=end)]


def _realm_holder_seq(f, tid, end=None):
    """头衔在**各传主缓存的 realm_history 快照**里的持有者序列 [(date, holder)] (v68)。

    兜底 `_title_holder_seq`: 无地头衔 (游牧毡帐/营地/新创头衔) 的熔件 title history
    常常为空, 而快照逐档记着当时的 holder (旧《朝局风云录》的「库曼顿巴斯部：930年
    1月2日：乞则里…」几行即出自这里)。逐档观测值按日期去重; 相邻同主只留首个。"""
    seen = {}
    for src in list((f.campaign or {}).values()) + [f.cache]:
        for h in (src or {}).get("realm_history") or []:
            d = h.get("date")
            if not d:
                continue
            if end and cl.date_key(d) > cl.date_key(end):
                continue
            hs = h.get("holders") or {}
            if not isinstance(hs, dict):
                continue
            if str(tid) in hs and hs[str(tid)] is not None:
                seen[str(d)] = hs[str(tid)]
    out = []
    for d in sorted(seen, key=cl.date_key):
        if out and out[-1][1] == seen[d]:
            continue
        out.append((d, seen[d]))
    return out


def _estate_court_tid(f, pid):
    """家业持有者的「朝廷」头衔 (v68 问题1, 用户拍板 §7-2: 有庄园则写最高领主的头衔历史)。

    取家业头衔的 `de_facto_liege` 上溯到顶 (中国世族庄园挂在 h_china 之下);
    取不到再走主角所在地的上位链顶。无则 None。"""
    for t in (f._hold_intervals(pid) or {}):
        if not f._is_estate_title(t):
            continue
        l = (f._lt.get(str(t)) or {}).get("de_facto_liege")
        if not isinstance(l, int):
            continue
        top, seen = l, set()
        while top is not None and top not in seen:
            seen.add(top)
            nxt = (f._lt.get(str(top)) or {}).get("de_facto_liege")
            if not isinstance(nxt, int):
                break
            top = nxt
        if top is not None:
            return top
    try:
        prov = f.character_location_province(pid)
        ctid = f.county_at_province(prov)
        chain = f.liege_chain(ctid) if ctid is not None else []
        if chain:
            return chain[-1][0]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# v73: 《XX历代记》扩写素材 (用户 2026-09-27 拍板「内容太短 → 扩充 + 分篇并发」)
# ---------------------------------------------------------------------------
# 设计口径 (取证见 `docs/方案_v73_历代记扩写与并发分篇.md`):
#   · 短在素材不在提示词 —— 旧稿只下发「国号 + 年代 + 名 + 缘由」四样 (7 份快照
#     实测 64–560 字符), 而缓存里本有每人的生卒/年龄/享国/失位缘由/本朝战事;
#   · 一人一行 (旧稿把整朝历代压成一行, 卡尔 941 的 22 位帐汗挤在一行);
#   · 全部由程序成句, 提示词只交代「写哪一段、写什么」(prompt-last 铁律)。

_CHRONICLE_ANCESTOR_MAX = 12     # 家族历代记的上溯位数上限
_CHRONICLE_WAR_MAX = 40          # 单篇战事行上限 (每段再对半切)
CHRONICLE_MID_MAX = 4            # 分篇上限 (与《家室列传》JIASHI_GROUP_MAX 同式)
CHRONICLE_ROWS_PER_SECTION = 4   # v82: 单朝人数多于此数时按人再切段 (见 biography._chrono_row_chunks)
# 天朝 (`h_`) 创建天命时的缘由词 (用户 2026-09-27 拍板):
#   前一段是空位期 (群雄争霸) → 建立天命; 直接顶替在位者 → 取代 (王莽代汉之例)。
# 其余头衔的 `created` 仍走 `created_verb_kind` 三档 (创建/重建/开创)。
_CELLESTIAL_CREATE_VERB = {"vacant": "建立天命", "takeover": "取代"}
# `created` 三档的中文词 (与 style.TITLE_GAIN_CREATED_VERBS 同表; 此处就地重复,
# 免得 facts → style 反向依赖)。
_TITLE_GAIN_CREATED_VERBS_ZH = {"first": "创建", "restored": "重建", "founded": "开创"}


def _war_word(f, reason):
    """战争缘由词 (记忆 `war_cb` 的本地化名)。取不到返回空串, 由调用方省略该分句。"""
    if not reason:
        return ""
    try:
        v = L.loc(f.table, str(reason)) or ""
    except Exception:
        v = ""
    return v if v and not re.search(r"[A-Za-z_]", v) else ""


def _chrono_rec(f, cid):
    """角色记录 (v73: 同战役各传主缓存里取**最完整**的一份)。

    各缓存是同一局游戏不同档期的真实观测: 尼克档记下奄美靖 51 条记忆与卒日,
    崔佛档同期对该人是 0 条 —— 故按记忆条数取最全, 只读不合并写回。"""
    key = str(cid)
    best, best_n = None, -1
    for src in ([f.cache] + list((f.campaign or {}).values())):
        rec = ((src or {}).get("characters") or {}).get(key)
        if not isinstance(rec, dict):
            continue
        n = len(rec.get("memories") or [])
        if n > best_n:
            best, best_n = rec, n
    return best or {}


def _chrono_year_age(birth, date):
    """生日与事件日 → 整年岁 (缺任一返回 None)。"""
    if not birth or not date:
        return None
    try:
        by, bm, bd = (int(x) for x in str(birth).split(".")[:3])
        dy, dm, dd = (int(x) for x in str(date).split(".")[:3])
    except Exception:
        return None
    age = dy - by - (1 if (dm, dd) < (bm, bd) else 0)
    return age if age >= 0 else None


def _chrono_span(gain, loss):
    """在位跨度文本: 「在位10年」/「在位未满一年」; 缺失位日返回空串。"""
    if not gain or not loss:
        return ""
    try:
        gy = int(str(gain).split(".")[0])
        ly = int(str(loss).split(".")[0])
    except Exception:
        return ""
    n = ly - gy
    return "在位未满一年" if n <= 0 else "在位%d年" % n


def _chrono_seqs(f):
    """{(cid, tid): [(date, reason, type)]} —— 登位/失位**记忆**索引 (一次扫描缓存)。

    `ascended_throne_memory.vars.reason` 是游戏自己记的取法 (尼克档 9,875 条
    **全部**带 reason), `lost_title_memory` 同式; `landed_title` 即该记忆对应的头衔。"""
    if getattr(f, "_chrono_idx", None) is not None:
        return f._chrono_idx
    idx = {}
    for _cid, _rec in (f.cache.get("characters") or {}).items():
        try:
            cid = int(_cid)
        except (TypeError, ValueError):
            continue
        for m in (_rec.get("memories") or []):
            ty = m.get("type")
            if ty not in ("ascended_throne_memory", "lost_title_memory"):
                continue
            reason, lt = "", None
            for v in (m.get("vars") or []):
                if v.get("flag") == "reason" and not reason:
                    reason = str(v.get("value") or "")
                elif v.get("flag") == "landed_title" and v.get("identity") is not None:
                    try:
                        lt = int(v.get("identity"))
                    except (TypeError, ValueError):
                        lt = None
            if lt is None:
                continue
            idx.setdefault((cid, lt), []).append(
                (str(m.get("creation_date") or ""), reason, ty))
    for k in idx:
        idx[k].sort(key=lambda x: cl.date_key(x[0]))
    f._chrono_idx = idx
    return idx


def _chrono_accession_reason(f, cid, tid, hist_type, date):
    """该日即位的**缘由** —— 记忆档优先, 头衔 history 兜底。

    天朝 (`h_`) 的 `created` 由调用方按用户判据改写 (空位期后 = 建立天命 / 顶替在位者
    = 取代), 故此处返回空串; 其余一律先取记忆档 (词表更全: 补 inheritance / election /
    purchased / seized_pastureland / negotiated 五档), 记忆缺该头衔时退回头衔 history
    的 `type`。两处都没有返回 "" (该分句整段省略)。"""
    if hist_type == "created":
        return ""
    for (d, reason, _ty) in reversed(_chrono_seqs(f).get((int(cid), int(tid)), [])):
        if not reason:
            continue
        if not date or cl.date_key(d) <= cl.date_key(date):
            return _SUCC_WORD.get(reason, "")
    return _SUCC_WORD.get(hist_type or "", "")


def _chrono_rel_word(f, cid, other):
    """二者亲属关系词 (子/女/父/母/兄/姊/配偶); 无关系返回 ''。"""
    if cid is None or other is None:
        return ""
    fam = (_chrono_rec(f, cid).get("family") or {})
    if other in (fam.get("father") or []):
        return "父"
    if other in (fam.get("mother") or []):
        return "母"
    if other in ((fam.get("spouse") or []) + (fam.get("primary_spouse") or [])
                 + (fam.get("concubine") or []) + (fam.get("former_spouses") or [])):
        return "配偶"
    if other in (fam.get("siblings") or []):
        return "姊" if bool((_chrono_rec(f, other) or {}).get("female")) else "兄"
    ofam = (_chrono_rec(f, other).get("family") or {})
    if cid in (ofam.get("child") or []):
        return "女" if bool((_chrono_rec(f, cid) or {}).get("female")) else "子"
    return ""


def _chrono_nm(f, cid, date=None):
    """事件人名 (v73): 取**受业名** —— 先按熔件 `first_name` 与当地名序拼显示名,
    退到缓存档案的 `name_full`。跨传主缓存取记录时, `name_full` 可能是另一档期算出的
    父名/家名 (富兰克林档实测: 先王记成「比约恩·蒙索」而国号沿革里是「比约恩·朗纳尔松」),
    故受业名优先, 与历代行同一套词。"""
    cc = f._chars.get(str(cid)) or {}
    if isinstance(cc, dict) and cc:
        try:
            nm = f.name(cid, date=date)
        except Exception:
            nm = ""
        if nm:
            return nm
    return _chrono_rec(f, cid).get("name_full") or f.name_or(cid, "") or ""


def _chrono_acc_text(f, cid, date, word, prev, from_prev=False,
                       prev_date=None):
    """即位分句: 「953年6月6日从珉·奄美处被派系拥立」/「874年7月7日自立建国」。

    `from_prev` 只对**继承类**缘由置真 (与 v69 的 `_SUCC_FROM_PREV` 同口径):
    「从X处建立天命」「从X处被派系拥立」都不是通顺句。"""
    d = f.date(date) if date else ""
    if not word:
        return d
    if from_prev and prev is not None and isinstance(prev, int):
        pn = _chrono_nm(f, prev, prev_date or date)
        if pn:
            rel = _chrono_rel_word(f, cid, prev)
            return "%s从%s%s处%s" % (d, rel, pn, word) if rel                 else "%s从%s处%s" % (d, pn, word)
    return d + word


def _chrono_loss_date(f, cid, tid, next_date):
    """该次任职的**真正失位日** (v73): 两位君主先后相继 (前任卒/禅 → 后任即位) 时,
    `history` 的下一事件日只是**继任日**, 不是前任的失位日 —— 旧稿因此把「奄美樽
    951 即位、953 传位其子」写成「随后于 953 年失去天命」, 与 `top_title_history`
    的「从奄美珉处受任命继位」自相矛盾。故只在存档另记失位事件 (`lost_title_memory`)
    或下一事件本身是 `destroyed` 时, 才认这个日期为失位日; 否则返回 None
    (行内只写任期, 不写失位)。"""
    if not next_date:
        return None
    for (d, _reason, ty) in _chrono_seqs(f).get((int(cid), int(tid)), []):
        if ty != "lost_title_memory":
            continue
        if cl.date_key(d) <= cl.date_key(next_date):
            return d
    return None


def _chrono_reign_end(f, cid):
    """该统治者的**让位档** (v81 问题2): 同战役缓存里他当传主时写入的 `reign_end`
    (由 `pipeline._cross_check_reign_ends` 从存档接替链判出, 含种类与继承人)。

    为什么历代记要读它: 失位日旧稿只认 `lost_title_memory`, 而田所久保 922.7.7
    的让位只落在**他自己那份缓存**的 `reign_end` 里 —— 于是 919 即位、922 失位
    (在位 3 年) 的久保被写成「卒于位」(卒 930), 与在位年数自相矛盾。"""
    key = int(cid)
    if f.cache.get("player_id") == key:
        return f.cache.get("reign_end") or {}
    for c in (f.campaign or {}).values():
        if (c or {}).get("player_id") == key:
            return (c or {}).get("reign_end") or {}
    return {}


def _chrono_office(f, cid, date):
    """该日在位者的官称 (v81 问题2/3): 日本最高头衔走 `japan_top_office` 的裸词
    (关白/太政大臣/幕府将军/上皇/天皇), 其余头衔走 `official_title`; 取不到返回 ''。"""
    if not date:
        return ""
    try:
        w = f.japan_top_office(cid, date) or f.official_title(cid, date=date) or ""
    except Exception:
        w = ""
    return w


def _chrono_joko_clause(f, cid, date):
    """「上皇」之由 (v83, 用户 2026-09-29 指正): 「关白之序及身，乃退天皇位，称上皇」。

    机制 (两处脚本, 已在本局数据上核实 —— `logs/v82_probe2.txt`):
      · `common/on_action/title_on_actions.txt:1461-1487` —— 新持有者取得 `e_japan`
        (关白之位) 时, 若 `e_japan.var:administrative_ui_special_title` 所指头衔
        (本局 = 高御座 `k_chrysanthemum_throne`) 仍在他手上, 即触发 9120 号事件;
      · `events/dlc/tgp/tgp_japan_general_events.txt:733-767` —— 该事件让他**退天皇位**
        (高御座交 `player_heir`, 故其持有区间在即位次日终结)、加 `joko_flag` 与
        `former_emperor` ⇒ 称**上皇**: 仍持关白 = 实权摄政, 且先前做过天皇。
    实测 (田所久荫 16851604): 高御座 962.2.27–964.11.20 → e_japan 964.11.19 及身
    → 次日高御座交田所尹秀 ⇒ 上皇之称**始于即位之日**, 不是卒前某日。

    ⇒ 这一句接在即位句后 (行尾不再写「退位上皇」); 查不到「即位日仍持高御座」的
    证据时只写「，称上皇」。"""
    tid = f.title_by_key("k_chrysanthemum_throne")
    date_key = cl.date_key(date) if date else None
    if isinstance(tid, int) and date_key:
        ivs = f._hold_intervals(cid).get(tid)
        if ivs is None:
            ivs = (f._hold_intervals(cid) or {}).get(str(tid))
        for iv in (ivs or []):
            try:
                gain, loss = iv[0], iv[1]
            except (IndexError, TypeError):
                continue
            if gain and loss and cl.date_key(gain) <= date_key < cl.date_key(loss):
                return "，关白之序及身，乃退天皇位，称上皇"
    return "，称上皇"


def _chrono_ruler_line(f, tid, date, cid, hist_type, prev, loss_date,
                       vacant=False, is_h=False, family=False, nm=None,
                       prev_date=None, dtor=False):
    """一位统治者一行 (v73 用户拍板「一人一行」; v81 问题2 立行形; v82 去分栏):

    `关白田所久保，卒930年4月9日，享年55岁，死于心脏病发作；919年2月24日从父田所浩二
      处受任命继位，时年44岁；在位3年，922年7月7日剃发退位，传位于田所定治`
    `上皇田所久荫，卒970年10月30日，享年53岁，死于心脏病发作；…；964年11月19日从田所
      为久处受任命继位，时年47岁，关白之序及身，乃退天皇位，称上皇；在位6年`
    `幕府将军平盛秀，卒1006年8月7日，享年49岁，酗酒而亡；…；在位11年，开府，改称幕府将军`
    `西山阴道一族平有永，995年7月25日受封西山阴道栋梁`   (家族历代记行)

    v81 (用户 2026-09-29 拍板) 立的三处:
      · 去「生X年」(出生日期在这不重要), 改「卒{日}，享年{N}岁，{死因}」;
      · 让位 (reign_end) 优先于 `lost_title_memory` 判失位, 写退位词与继承人;
      · 卒项跨缓存取最全一份记录。
    v82 (用户 2026-09-29 拍板) 改行形:
      · **称号紧贴人名**、不再用「｜」分栏 (「关白田所久保」);
      · 称号取**最后的称号** (久荫=上皇 / 盛秀=幕府将军), 改称只在行内补一句
        (「，开府，改称幕府将军」), 末词不被读成即位时就有。
    v83 (用户 2026-09-29 指正) 两处:
      · 行尾不再写「卒于位」 —— 卒项已在前, 「在位N年，卒于位」是同义重复;
      · 上皇不是「在位若干年后退位」: 关白之序及身时, 时任天皇 (他本人) 退位、
        称上皇 —— 这一句移到即位句后 (见 `_chrono_joko_clause`)。
    `prev`(前任) 与 `vacant`(前一段是空位期) 支撑天朝「建立天命 / 取代」的用户判据。
    返回 "" 表示此行无料可写 (无称号、无卒项、无即位句), 由调用方整行略去。"""

    nm = nm or _chrono_nm(f, cid, date)
    if not nm:
        return "", False
    rec = _chrono_rec(f, cid)
    if family:
        word = _SUCC_WORD.get(hist_type or "", "") or ""
        acq = _chrono_acc_text(f, cid, date, word, None)
        tname = f.title(tid, date=date) if tid is not None else ""
        # v82: 家族行同样去「｜」分栏 —— 称号 (头衔名) 紧贴人名, 后接即位句。
        head = f"{tname}{nm}" if tname else nm
        row = f"{head}，{acq}" if acq else head
        # v82: 明文回报「此行是否三样俱全」(称号/卒项/即位句) —— 旧稿靠数字「｜」个数
        # 判料之有无, 分栏一去就无从判断; 判据仍在事实层, 供纪事块整行略去无料之行。
        return row, bool(tname) and bool(acq)
    birth = rec.get("birth") or ""
    death = (rec.get("death") or {}).get("date") or ""
    # v81: 卒项 = 日 + 享年 + 死因 (死因走既有的 death_clause; 跨缓存取最全一份记录)
    dead_bits = []
    if death:
        dead_bits.append("卒" + f.date(death))
        _age = _chrono_year_age(birth, death)
        if _age is not None:
            dead_bits.append("享年%d岁" % _age)
        _reason = (rec.get("death") or {}).get("reason") or ""
        try:
            # v82: 凶手称谓按**事发前一日**取 (与 `_anchor_date` 的「卒日当天头衔已随
            # 继承易主」同一条口径) —— 大和实世 901.7.30 被杀、浩二同日继位,
            # 按当日取词会写成「被关白…赐死」(那天他才刚当上关白)。
            _clause = f.death_clause(cid, date=death, reason=_reason,
                                     killer=(rec.get("death") or {}).get("killer"),
                                     killer_date=_day_before(death))
        except Exception:
            _clause = ""
        if _clause:
            dead_bits.append(_clause)
    word = _chrono_accession_reason(f, cid, tid, hist_type, date)
    if hist_type == "created":
        if is_h:
            word = _CELLESTIAL_CREATE_VERB["takeover" if not vacant else "vacant"]
        else:
            word = _TITLE_GAIN_CREATED_VERBS_ZH.get(
                f.created_verb_kind(tid, cid, date)) or "创建"
    acq = _chrono_acc_text(f, cid, date, word, prev,
                           from_prev=(hist_type in (None, "", "appointment_succession",
                                                    "abdication", "inheritance")),
                           prev_date=prev_date)
    if not word and prev is not None and isinstance(prev, int):
        # 两源都无线索 (头衔 history 无 type、记忆档也未载) 时, 按**前任相继**写常规
        # 「继位」—— 与 v69 的「无 type = 常规继承」同口径; 首位统治者 (无前任) 则
        # 只写即位日, 不替游戏猜缘由。
        _pn = _chrono_nm(f, prev, prev_date or date)
        if _pn:
            _rel = _chrono_rel_word(f, cid, prev)
            acq = ("%s从%s%s处继位" % (f.date(date), _rel, _pn) if _rel
                   else "%s从%s处继位" % (f.date(date), _pn))
    age = _chrono_year_age(birth, date)
    if age is not None:
        acq += "，时年%d岁" % age
    _real_loss = _chrono_loss_date(f, cid, tid, loss_date)
    if _real_loss is None and dtor:
        _real_loss = loss_date          # 下一事件即毁弃 (holder = 失去者) 时直接认下
    _end = _real_loss or loss_date or death
    span = _chrono_span(date, _end)
    # v82 (用户 2026-09-29 拍板): 称号取**最后的称号** —— 一行一个称号词, 紧贴人名
    # (「关白田所久保」「上皇田所久荫」「幕府将军平盛秀」)。
    # 为什么取最后: 旧稿写「X，后为Y」两词并列, 模型成稿只落第一个
    # (实测 1006 终传: 「太政大臣，后为幕府将军」被写成「为太政大臣」, 上皇整词丢失),
    # 而称号位与行首人名的黏合形式模型必写。
    office = _chrono_office(f, cid, date)
    _o2 = ""
    if _end:
        _a2 = f._anchor_date(cid, _end)
        _t2, _tid2 = f._primary_title_at(cid, as_of=_a2)
        if isinstance(_tid2, int) and _tid2 == tid:
            _o2 = _chrono_office(f, cid, _a2)
    _last = _o2 or office
    # v83: 上皇之称始于即位之日 (关白之序及身 → 退天皇位 → 称上皇), 故这一句接在即位句后。
    _joko = _chrono_joko_clause(f, cid, date) if _last == f._JAPAN_OFFICE_JOKO else ""
    tail = ""
    _re = _chrono_reign_end(f, cid)
    _red = _re.get("date") or ""
    if _red and _end and cl.date_key(_red) == cl.date_key(_end):
        # 让位 (v76 机制): 写退位词与继承人 (继承人只出名字, 与即位句同口径)
        _w = f.reign_end_word(_re)
        _succ = _re.get("successor")
        _snm = _chrono_nm(f, _succ, _red) if isinstance(_succ, int) else ""
        _srel = _chrono_rel_word(f, cid, _succ) if isinstance(_succ, int) else ""
        tail = "，" + f.date(_red) + _w + (f"，传位于{_srel}{_snm}" if _snm else "")
    elif _real_loss and not (death and cl.date_key(death) == cl.date_key(_real_loss)):
        # v83: 失位日与卒日同日 = 在位而终, 行尾不再出词 (旧稿写的「卒于位」与卒项重复)。
        tail = "，随后于" + f.date(_real_loss) + ("失去天命" if is_h else "失去头衔")
    if _o2 and _o2 != office and _o2 != f._JAPAN_OFFICE_JOKO:
        # v82: 在位期间改称 (惣領制 + 头衔带 `shogun_flag` = 开府) —— 称号位只出末词,
        # 改称之由在行内补一句, 免得模型把末词当成即位时就有 (盛秀 995 年即位时是
        # 太政大臣, 开府在他卒前的那一年里)。
        tail = ("，开府，改称幕府将军" if _o2 == f._JAPAN_OFFICE_SHOGUN
                else f"，改称{_o2}") + tail
    bits = [x for x in (acq + _joko, span) if x]
    body = "；".join(bits) + tail
    head = f"{_last}{nm}" if _last else nm
    segs = [x for x in (dead_bits and "，".join(dead_bits), body) if x]
    if not segs:
        return "", False
    row = head + "".join(("，" if i == 0 else "；") + s for i, s in enumerate(segs))
    return row, bool(_last) and bool(dead_bits) and bool(bits)


def _chrono_group(items, max_n):
    """把 items 尽量等分成 ≤max_n 段 (空段不返回)。"""
    items = list(items or [])
    if not items:
        return []
    n = max(1, min(int(max_n), len(items)))
    base, extra = divmod(len(items), n)
    out, i = [], 0
    for k in range(n):
        m = base + (1 if k < extra else 0)
        if m:
            out.append(items[i:i + m])
        i += m
    return out


def _chrono_label(f, cid, date=None):
    """战事行里的人名 (只出名字; 战事行已由本方称谓领起)。"""
    return f.name_with_regnal(cid, date) or f.name_or(cid, "") or ""


def _chrono_war_lines(f, tid):
    """本头衔的战事行 (v73): 兴兵之年 + 对手 + 决胜之年与胜负, 一行成句。

    源: 缓存记忆 `offensive_war` / `defensive_war` 的 `war_title` = 本头衔
    (`war_attacker` = 兴兵方), 胜负取同对手的 `war_won` / `war_lost`。"""
    tid = int(tid)
    wars, wins = [], []
    for _cid, _rec in (f.cache.get("characters") or {}).items():
        try:
            cid = int(_cid)
        except (TypeError, ValueError):
            continue
        for m in (_rec.get("memories") or []):
            ty = m.get("type")
            if ty not in ("offensive_war", "defensive_war", "war_won", "war_lost"):
                continue
            wt, atk = None, None
            for v in (m.get("vars") or []):
                if v.get("flag") == "war_title" and v.get("identity") is not None:
                    try:
                        wt = int(v.get("identity"))
                    except (TypeError, ValueError):
                        wt = None
                elif v.get("flag") == "war_attacker" and v.get("identity") is not None:
                    try:
                        atk = int(v.get("identity"))
                    except (TypeError, ValueError):
                        atk = None
            if wt != tid:
                continue
            d = str(m.get("creation_date") or "")
            parts = m.get("participants") or {}
            if ty in ("offensive_war", "defensive_war"):
                opp = parts.get("other_party")
                if not isinstance(opp, int):
                    opp = atk
                wars.append((d, cid, opp if isinstance(opp, int) else None, ty))
            else:
                opp = parts.get("loser") if ty == "war_won" else parts.get("winner")
                wins.append((d, cid, opp if isinstance(opp, int) else None, ty))
    out, seen = [], set()
    for (d, cid, opp, ty) in sorted(wars, key=lambda x: cl.date_key(x[0])):
        me = f.date(d) + _chrono_label(f, cid)             + ("兴兵" if ty == "offensive_war" else "应战")
        if isinstance(opp, int):
            me += ("讨" if ty == "offensive_war" else "拒")                 + (_chrono_label(f, opp) or "来犯之敌")
        for (wd, wcid, wopp, wty) in wins:
            if wcid != cid or cl.date_key(wd) < cl.date_key(d):
                continue
            if isinstance(opp, int) and isinstance(wopp, int) and opp != wopp:
                continue
            me += "；" + f.date(wd) + ("战胜" if wty == "war_won" else "败于")                 + (_chrono_label(f, wopp) if isinstance(wopp, int) else "对手")
            break
        # v81 (问题5): 找不到决胜时**不再**补「；胜负未见记载」—— 无料分句只会占
        # 模型的注意力 (与 v78 在 `_pair_war_events` 已定的口径一致: 只写兴兵句)。
        me += "。"
        if me in seen:
            continue
        seen.add(me)
        out.append(me)
        if len(out) >= _CHRONICLE_WAR_MAX:
            break
    return out


def _chrono_base_name(f, tid, date=None):
    """头衔**底名** (不含层级词) —— k_qingxu → 「青徐」。
    与 `_realm_facts` 内 `_base_name` 同式 (该处是闭包, 模块级另立一份)。"""
    t = f._lt.get(str(tid)) or {}
    key = t.get("key") or ""
    if not key:
        return ""
    d = date or f.as_of or f.cache.get("last_date")
    nm = f._name_at_date(tid, d) or L.loc(f.table, key) or key
    nm = str(nm).strip()
    return nm if not re.search(r"[A-Za-z_]", nm) else ""


def _chrono_sub_lines(f, tid, pid=None):
    """本朝治所/所辖行 (v73): 治所取传主档案里已算好的 `protagonist.capital`
    (「长安县」—— 与《传主档案》同一出口, 免得两处治所不一致); 所辖列挂在本头衔名下的
    封臣头衔。取不到即整行省略。"""
    out = []
    capname = ""
    if pid is not None:
        capname = (getattr(f, "_protagonist_cache", None) or {}).get("capital") or ""
    if capname:
        out.append("治所：" + str(capname))
    holders = {}
    for h in (f.cache.get("realm_history") or []):
        for k, v in (h.get("holders") or {}).items():
            if v is not None:
                holders[str(k)] = v
    subs = []
    for k in holders:
        t = f._lt.get(str(k)) or {}
        if (t.get("de_facto_liege") or t.get("liege")) == tid:
            nm = _chrono_base_name(f, int(k))
            if nm and nm not in subs:
                subs.append(nm)
    if subs:
        out.append("本朝所辖：" + "、".join(subs[:12]))
    return out


def _chrono_accs(f, tid, as_of):
    """本头衔的取得序列 [(date, holder, type, reign_end, vacant)]。
    头衔 history 为空 (游牧毡帐等) 时退逐档快照, 缘由为空。"""
    evs = _title_hist_events(f, tid, end=as_of)
    if not evs:
        evs = [(d, h, None) for d, h in _realm_holder_seq(f, tid, end=as_of)]
    out, prev, vacant = [], None, False
    for i, (d, h, ty) in enumerate(evs):
        if h is None:
            continue
        if ty == "destroyed":
            prev, vacant = None, True
            continue
        if prev is None or h != prev:
            out.append((d, h, ty, evs[i + 1][0] if i + 1 < len(evs) else None, vacant))
        prev, vacant = h, False
    return out


def _chrono_prev_for(accs, idx):
    """取得序列里该事件的前一任持有者 (继承链可读); 无则 None。"""
    for j in range(idx - 1, -1, -1):
        h = accs[j][1]
        if isinstance(h, int):
            return h
    return None


def _chrono_build(f, tid, pid, is_h, own, periods, tname):
    """《历代记》分篇素材 (v73 用户拍板): 一人一行 + 分篇 + 战事/支系.

    · 该头衔由传主创建且历代只有传主一人 → **家族历代记** (祖上最早一位统治者写到传主);
      此时取不到有头衔的父/母 (自定义角色) → 返回 None, 该篇不生 (用户 2026-09-27 拍板)。
    · 否则按国号段组织历代 (段界 = 各段首位即位日), 每段一人一行。"""
    accs = _chrono_accs(f, tid, f.as_of or f.cache.get("last_date"))
    if len(accs) == 1 and accs[0][1] == pid and (accs[0][2] or "") == "created":
        return _family_chronicle(f, pid, tid, is_h=is_h)
    if not periods:
        return None
    for k, p in enumerate(periods):
        p["end"] = periods[k + 1]["start"] if k + 1 < len(periods) else None
    claimed = set()
    for p in periods:
        for gi, (d, h, ty, end, vac) in enumerate(accs):
            if h not in p["ids"] or gi in claimed:
                continue
            # 归属判据 = **即位日落在本段之前** (该段的即位者可能在战役窗口之前就即位,
            # 如李漼 859 年即位而唐皇朝段自 868 年战役起点起算), 且下一段开始前仍在位。
            claimed.add(gi)
            # v73: 下一事件即「毁弃」(holder = 失去者) 时, 该任的结束日就是真正的失位日
            _dtor = bool(gi + 1 < len(accs) and accs[gi + 1][2] == "destroyed")
            # v82: 行文本与「此行是否三样俱全」的判据同时入库 (一一对应, 空行也占位),
            # 供纪事块略去无料之行 (旧稿靠数字「｜」个数判, 分栏一去即无从判断)。
            _row, _detail = _chrono_ruler_line(
                f, tid, d, h, ty, _chrono_prev_for(accs, gi), end,
                vacant=vac, is_h=is_h, dtor=_dtor,
                prev_date=(accs[gi - 1][0] if gi > 0 else None))
            p["rows"].append(_row)
            p.setdefault("rows_detail", []).append(bool(_detail))
            # v82: 逐行的即位日与人物 id 同样入库 (与 rows 一一对应) —— 分节器按人
            # 切段时要用它算各段的年代区间与所辖诸侯 (见 biography._chrono_row_chunks)。
            p.setdefault("rows_dates", []).append(str(d))
            p.setdefault("rows_ids", []).append(int(h))
    if not any(p["rows"] for p in periods):
        return None
    cur = next((p for p in reversed(periods) if p.get("ids")), None)
    return {
        "name": tname,
        "family": False,
        "tid": int(tid),
        "is_h": bool(is_h),
        "current": cur,
        "periods": periods,
        "wars": _chrono_war_lines(f, tid) if is_h else [],
        "subs": _chrono_sub_lines(f, tid, pid),
    }


def _family_chronicle(f, pid, tid, is_h=False):
    """家族历代记 (v73 用户拍板): 该头衔由传主创建、且历代只有传主一人 → 从**祖上最早的
    一位统治者**写到传主。无有头衔的父/母 (自定义角色, 如诺兰冒险者) → 返回 None, 该篇不生。

    条目 = 同宗族 (`dynasty_id` 一致) 的历代祖先 (父/母链上溯), 各取其**最早**一次持衔;
    按即位日由老到新, 末条 = 传主本人。上限 `_CHRONICLE_ANCESTOR_MAX` 人。"""
    p_dyn = f._dynasty_of_cid(pid)
    seen, queue = set(), []
    fam0 = (_chrono_rec(f, pid).get("family") or {})
    for key in ("father", "mother"):
        for pcid in (fam0.get(key) or []):
            if isinstance(pcid, int) and pcid != pid and pcid not in seen:
                seen.add(pcid)
                queue.append(pcid)
    picked = []
    while queue:
        cid = queue.pop(0)
        if f._dynasty_of_cid(cid) == p_dyn:
            hold = f._holder_intervals.get(cid) or {}
            if hold:
                best = None
                for t, ivs in hold.items():
                    for iv in ivs:
                        if iv and iv[0] and (best is None
                                             or cl.date_key(iv[0]) < cl.date_key(best[0])):
                            best = (iv[0], int(t), iv[1] if len(iv) > 1 else None,
                                    iv[2] if len(iv) > 2 else "")
                if best:
                    picked.append((best[0], cid, best[1], best[2], best[3]))
        fam = (_chrono_rec(f, cid).get("family") or {})
        for key in ("father", "mother"):
            for pcid in (fam.get(key) or []):
                if isinstance(pcid, int) and pcid != cid and pcid not in seen:
                    seen.add(pcid)
                    queue.append(pcid)
    if not picked:
        return None
    picked.sort(key=lambda x: cl.date_key(x[0]))
    picked = picked[-_CHRONICLE_ANCESTOR_MAX:]
    rows, details = [], []
    for idx, (d, cid, atid, loss, _lt2) in enumerate(picked):
        _pv = f._gain_prev.get((cid, atid, d))
        if _pv is None and idx > 0:
            _pv = picked[idx - 1][1]
        line, _det = _chrono_ruler_line(
            f, atid, d, cid, f._gain_reason.get((cid, atid, d), ""),
            _pv, loss, is_h=is_h, family=True,
            nm=_chrono_nm(f, cid, d), prev_date=(picked[idx - 1][0] if idx else None))
        if line:
            rows.append(line)
            details.append(bool(_det))
    ivs = (f._hold_intervals(pid) or {}).get(tid) or []
    own_g = ivs[-1][0] if ivs else None
    own_l = ivs[-1][1] if ivs else None
    own_line, own_det = _chrono_ruler_line(f, tid, own_g, pid, "created",
                                           (picked[-1][1] if picked else None), own_l,
                                           is_h=is_h, family=True,
                                           nm=f.name(pid))
    if own_line:
        rows.append(own_line)
        details.append(bool(own_det))
    if not rows:
        return None
    name = (f.name(pid) or f.cache.get("player_name") or "") + "家"
    _fam_cur = {"name": "家族", "start": (picked[0][0] if picked else own_g),
                "end": own_l, "vacant": False,
                "ids": [p[1] for p in picked] + [pid], "rows": rows,
                "rows_detail": details,
                "rows_dates": [p[0] for p in picked] + [own_g],
                "rows_ids": [p[1] for p in picked] + [pid]}
    return {
        "name": name,
        "family": True,
        "tid": int(tid),
        "is_h": bool(is_h),
        "current": _fam_cur,
        "periods": [_fam_cur],
        "wars": _chrono_war_lines(f, tid) if is_h else [],
        "subs": _chrono_sub_lines(f, tid, pid),
    }


def _is_final_bio(f):
    """本篇是否**终传** (v73 用户 2026-09-27 拍板: 《XX历代记》只在终传触发)。

    判据 = 传主之位已终了 **且** 本篇截止日正是那个终了日:
      · `pipeline._bio_as_of` 给终传传的是终了日 (与终了日同期 ⇒ 终传);
      · 十年传记传的是十年末 (≠ 终了日, 且 decade 有值);
      · 在世传记没有终了日。
    终了 = 死亡 (`player_death`) **或** 在位终结但未死亡 (`reign_end`, v76 问题1:
    剃发退位/让位等换扮演角色; 两档都有时让位日优先, 见 `pipeline._reign_end`)。
    世界末日档 (终了日与叙事末日同期且 decade 有值) 归十年档, 按用户要求不建本篇。"""
    return _is_final_bio_spec({
        "decade": f.decade,
        "as_of": f.as_of,
        "player_death": f.cache.get("player_death"),
        "reign_end": f.cache.get("reign_end"),
    })


def _is_final_bio_spec(facts):
    """`_is_final_bio` 的**事实面**版 (同一判据, 供 `biography.build_articles` 复核)。
    v76: 终了日 = reign_end (让位) 优先, 其次 player_death (卒)。"""
    facts = facts or {}
    if facts.get("decade"):
        return False
    end = ((facts.get("reign_end") or {}).get("date")
           or (facts.get("player_death") or {}).get("date") or "")
    if not end:
        return False
    as_of = facts.get("as_of")
    if not as_of:
        return True
    try:
        _a = (tuple(cl.date_key(str(as_of))) + (1, 1))[:3]
        _b = (tuple(cl.date_key(str(end))) + (1, 1))[:3]
        _d = (_a[0] - _b[0]) * 366 + (_a[1] - _b[1]) * 31 + (_a[2] - _b[2])
        return -7 <= _d <= 7
    except Exception:
        return str(as_of) == str(end)


def _top_title_history(f, group_lines=None):
    """本朝历代 (v68 问题1; 用户拍板 §7-1「篇名《XX历代记》」/§7-2「有庄园写最高领主的
    头衔历史, 冒险者营地略去」; v69 用户追改行形) —— 主角当前最高头衔**从战役起点
    以来**的历代。返回 (篇名用朝代通称, [总说行...], 分篇素材); 无可写对象返回 ("", [], {})。

    块的行序 (v69 用户样例: 每朝一行, 次行由老到新列该朝历代并写明即位缘由):
      本朝：{该日头衔显示名}            (仅家业者写「所附之朝：」; 末行另有主角在位段)
      {国号}{层级词}（{起}至{止}）      例: 唐皇朝（868年至887年）/ 元皇朝（972年至今）
      {名}（{即位日}{缘由}…）、…       例: 奄美靖（953年6月6日被派系拥立）
      群雄争霸（{毁弃日}至{重建日}）    天命毁弃而国号未改的空位期 (用户指定此名)
      {毁弃日}天命中绝，天下无主
      本朝疆域：{同属一廷的封臣头衔} / 主角本朝任期：{起}–{止}
    即位缘由取存档 `history.<date>.type` (见 `_SUCC_WORD`; 无 type = 常规继承),
    失天命/失头衔取 `destroyed` 事件; 全体取证见 `docs/方案_v69_菲利普2历代记.md`。
    为什么要有它: 旧《朝局风云录》的「天下大势」用 `holder_changes` 的「相关高位头衔」
    口径, 同一家族名下被同一套游牧动态名统一命名的四枚头衔并列 (四行同名), 国号
    (唐→中华→和→毕→越→元) 一行不可见 —— 模型于是把草原汗位更替当成中国王朝更替来写。"""
    pid = f.cache.get("player_id")
    if pid is None:
        return "", [], {}
    # v73 (用户 2026-09-27 拍板): 本篇**只在终传触发** —— 在世传记 (尚未卒) 与各十年
    # 传记都不再建《XX历代记》 (历代既已完篇, 不必每十年重述一遍)。
    if not _is_final_bio(f):
        return "", [], {}
    as_of = f.as_of or f.cache.get("last_date")
    start = _campaign_start(f)
    tid, own = None, False
    _t, _tid = f._primary_title_at(pid, as_of=f.as_of)
    if _tid is not None and _t is not None:      # 有真领地 → 主角自己的最高头衔
        tid, own = _tid, True
    else:
        cut = f.as_of or (f.cache.get("reign_end") or {}).get("date") \
            or (f.cache.get("player_death") or {}).get("date") \
            or f.cache.get("last_date")
        if cut:
            _t2, _tid2 = f._primary_title_at(pid, held_through=cut)
            if _tid2 is not None and _t2 is not None:   # 已卒/已让位传主: 按终了日仍在持算
                tid, own = _tid2, True
        if tid is None:                              # 仅家业 → 最高领主之朝
            if any(f._is_estate_title(t) for t in (f._hold_intervals(pid) or {})):
                tid = _estate_court_tid(f, pid)
    if tid is None:                                  # 仅冒险者营地 → 本篇略去
        return "", [], {}
    t = f._lt.get(str(tid)) or {}
    key = t.get("key") or ""
    tnd = t.get("title_name_data") or {}
    _disp = f._name_at_date(tid, as_of) or f.title_base_name(tid) or ""
    tname = f.title(tid, as_of) or _disp
    if not tname:
        return "", [], {}
    # 篇名通称: 有国号更名史者用它自己那一版通称 (h_china → 中华, 覆盖唐宋元…);
    # 其余用该日显示名的底名 (k_norway → 挪威 而非「挪威王国」)。
    common = L.loc(f.table, key) or _disp if f._has_reign_history(tid) else _disp
    if not common:
        common = tname
    lines = [("本朝：" if own else "所附之朝：") + tname]

    # ---- 国号分段 (title_history_names): [名, 起, 止] ----
    segs = []
    names = tnd.get("title_history_names") or []
    for h in names:
        if not isinstance(h, dict) or not h.get("date") or not h.get("name"):
            continue
        d = h.get("date")
        if f.as_of and cl.date_key(d) > cl.date_key(f.as_of):
            break
        raw = str(h.get("name"))
        v = L.loc(f.table, raw) or ""
        if not v or re.search(r"[A-Za-z_]", v):
            v = "" if re.search(r"[A-Za-z_]", raw) else raw
        if not v:
            continue
        segs.append([v, d, None])
    for i in range(len(segs) - 1):
        segs[i][2] = segs[i + 1][1]
    # 只留与 [战役起点, as_of] 相交的国号段 (汉/晋/隋等开局前的古史段整段落选)
    if start:
        segs = [s for s in segs
                if not (s[2] and cl.date_key(s[2]) <= cl.date_key(start))]

    # ---- 历代 (v69 用户 2026-09-27 拍板): 每个朝代**单独一行**「国号（起年至止年）」,
    # 次行由老到新列出该朝历代, 每人附即位缘由 (受任命继位/被派系拥立/正常继位…) 与
    # 失位/失天命; 天命毁弃而国号未改的**空位期**记作「群雄争霸」(用户指定, 不写
    # 「中华皇朝」)。缘由取 history 条目的 `type` (见 `_SUCC_WORD` 与探针取证)。
    # 旧稿把国号链与历代压成两行, 中华段因毁弃无主而把李漼写成该段起首之君,
    # 63 年空位一行不可见, 且全无继位缘由。
    is_h = key.startswith("h_")
    _evs = _title_hist_events(f, tid, end=as_of)
    plain = False
    if not _evs:                    # 无逐档头衔史 (游牧毡帐等) → 逐档快照兜底, 无缘由
        _evs = [(d, h, None) for d, h in _realm_holder_seq(f, tid, end=as_of)]
        plain = True
    accs, losses = [], []           # accs[(date, holder, type, reign_end, 空位中?)]; losses[(date, holder)]
    _prev, _vacant = None, False
    for _i, (_d, _h, _ty) in enumerate(_evs):
        if _h is None:
            continue
        if _ty == "destroyed":      # 毁弃: holder = 失去者 (全局 2983/2985 与前一主相同)
            if _prev is not None and _h == _prev:
                losses.append((_d, _h))
            _prev, _vacant = None, True
            continue
        if _prev is None or _h != _prev:
            accs.append((_d, _h, _ty,
                         _evs[_i + 1][0] if _i + 1 < len(_evs) else None, _vacant,
                         _vacant))
        _prev, _vacant = _h, False

    seg_rows = [[_nm, _s, _e, [], False]
                for _nm, _s, _e in (segs or [[_disp, None, None]])]
    # 国号更名比持有者变更晚 0–3 天落账 (950.6.1 珉·奄美建天命 → 950.6.3 改号「和」;
    # 963.1.9 格尔木噶玛即位 → 963.1.11 改号「毕」), 故即位日落在某国号段起点之后
    # 7 天内的归入**新**段 —— 否则开国之君会被算进上一朝。
    for _gi, (_d, _h, _ty, _end, _vac, _was_vac) in enumerate(accs):
        if start and _end and cl.date_key(_end) <= cl.date_key(start):
            continue                # 开局前就已卸任者不入历代 (汉晋隋唐古史)
        _dk, _pick, _best = _date_ord(_d), 0, None
        for _j, (_nm2, _s2, _e2, _hs2, _v2) in enumerate(seg_rows):
            if not _s2:
                continue
            _sk = _date_ord(_s2)
            if _sk <= _dk + 7 and (_best is None or _sk > _best):
                _best, _pick = _sk, _j
        seg_rows[_pick][3].append((_gi, _d, _h, _ty))
        if _was_vac:
            seg_rows[_pick][4] = True

    def _span(s, e):
        """朝代行的年代区间 (用户样例用年; 同一年内改朝者补月份)。"""
        y1, m1 = str(s).split(".")[0], str(s).split(".")[1]
        if e is None:
            return f"{y1}年至今"
        y2, m2 = str(e).split(".")[0], str(e).split(".")[1]
        if y1 == y2:
            return f"{y1}年{m1}月至{y1}年{m2}月"
        return f"{y1}年至{y2}年"

    # 朝代名 = 国号段名 + 层级后缀。后缀取**叙事末日的显示名**(元皇朝 → 皇朝;
    # 挪威王国 → 王国) 而非各段起始日 —— 天朝 `h_` 的层级词只在持有者行天朝制时
    # 才出「皇朝」(v8 口径), 950/963/972 三段的开国者都还是游牧制, 逐段取会得到
    # 「和」「毕」「元」这样的裸国号, 与「本朝：元皇朝」不一致。
    _base_now = f._name_at_date(tid, as_of) or ""
    _full_now = f.title(tid, as_of) or ""
    _suf = _full_now[len(_base_now):] if (_base_now and _full_now.startswith(_base_now)) else ""

    periods = []
    for _i, (_nm, _s, _e, _hs, _vac0) in enumerate(seg_rows):
        _st = _hs[0][1] if _hs else _s
        if _st is None:
            continue
        if start and _date_ord(_st) < _date_ord(start):
            _st = start                    # 朝代行按战役窗口起算 (用户样例 867→868 口径)
        _nx = (seg_rows[_i + 1][3][0][1] if (_i + 1 < len(seg_rows)
                                             and seg_rows[_i + 1][3])
               else (seg_rows[_i + 1][1] if _i + 1 < len(seg_rows) else None))
        if _nx is not None and start and _date_ord(_nx) < _date_ord(start):
            continue
        _hdr = ((_nm + _suf) if (_suf and _nm and not _nm.endswith(_suf)) else _nm) \
            if _nm else (_full_now or tname)
        if not _hs and is_h:
            _hdr = "群雄争霸"              # 天命毁弃、国号未改的空位期 (用户指定)
        lines.append(_hdr + "（" + _span(_st, _nx) + "）")
        _items = []
        for (_gi, _d, _h, _ty) in _hs:
            _hn = f.name_or(_h, "") or ""
            if not _hn:
                continue
            if plain:
                _txt = f"{_hn}（{f.date(_d)}起在位"
            elif _ty == "created":
                # 空位期后重建 (珉·奄美 950.6.1 续 887 之绝) 与开国 (尼克 972.10.10
                # 从奄美崇业手中另立天命) 是两码事 —— 看**紧邻的上一条事件**是否毁弃。
                _w = ("重建天命" if is_h else "重建头衔") if accs[_gi][4] \
                    else ("建立天命" if is_h else "自立建国")
                _txt = f"{_hn}（{f.date(_d)}{_w}"
            else:
                _w = _SUCC_WORD.get(_ty or "", "继位")
                _pn = (f.name_or(accs[_gi - 1][1], "") or "") \
                    if (_ty in _SUCC_FROM_PREV and _gi > 0) else ""
                _txt = f"{_hn}（{f.date(_d)}" + (f"从{_pn}处{_w}" if _pn else _w)
            for (_ld, _lh) in losses:
                if _lh == _h and _date_ord(_ld) >= _date_ord(_d):
                    _txt += "，随后于" + f.date(_ld) \
                        + ("失去天命" if is_h else "失去头衔")
                    break
            _items.append(_txt + "）")
        periods.append({"name": _hdr, "start": _st, "vacant": bool(_vac0),
                        "ids": [x[2] for x in _hs], "rows": []})
        if _items:
            lines.append("、".join(_items))
        elif is_h:
            _lo = [ld for ld, _lh in losses if _date_ord(ld) <= _date_ord(_st)]
            lines.append((f.date(max(_lo, key=_date_ord)) if _lo else "")
                         + "天命中绝，天下无主")
        else:
            lines.append("其间无主")
    gl = (group_lines or {}).get(tid)
    if gl:
        lines.append("本朝疆域：" + gl.split("：", 1)[-1])
    ivs = (f._hold_intervals(pid) or {}).get(tid) or []
    if own and ivs:
        _g, _l = ivs[-1][0], ivs[-1][1]
        lines.append("主角本朝任期：" + f.date(_g)
                     + ("–" + f.date(_l) if _l else " 至今"))
    return common, lines, _chrono_build(f, tid, pid, is_h, own, periods, tname)


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
                # v29b: 头衔与持有人直连 (「唐皇朝李漼」), 不用括注同位语
                parts.append(f"{f.title(tid)}{hn}" if hn else f.title(tid))
            # v38 (问题3): 链顶是主角自己 → 点明自立, 免得模型把「自己的政权」
            # 与同表里的唐/青徐混为一谈
            top_hid = chain[-1][1]
            tail = "，自立，上无领主" if top_hid == pid else ""
            out["liege_chain"] = " → ".join(parts) + tail
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
    # v38 (问题3): 隶属标注 —— 高位头衔更替原是一行一条、彼此平级 (唐皇朝 / 青徐国
    # 并列), 模型无从知道青徐是唐的封臣王国, 于是写出「唐皇朝以外, 青徐国自成一系」
    # 甚至「李润改元以青徐国为号」。现按熔件的 `de_facto_liege` (跟不动时沿
    # `de_jure_liege` 上溯) 求出每个头衔的**最近帝国/霸主级宗主**, 逐条标注,
    # 并给出「同属一个朝廷」的归组行。实测 k_qingxu 的 de_facto_liege = h_china。
    #
    # v64 (问题4): 法理回落必须落在**存在过的**头衔上 —— 存档里 `de_jure_liege`
    # 对**从未创建**的空衔同样有值 (本档 177 个高位头衔的 `history` 为 null、
    # holder 亦空, 且 realm_history 快照从未见过), 旧稿照名输出, 于是朝局事实面
    # 写出「库曼顿巴斯部：…为鞑靼帝国封臣」, 模型据此编出一个不存在的鞑靼帝国
    # (终传实测「他所属的鞑靼帝国，乃当世屈指可数的巨邦」)。判据见
    # `Facts._ever_held_title` (三档: history / 此刻 holder / realm 快照曾见)。
    def _up_liege(tid):
        seen = set()
        cur = tid
        while cur is not None and cur not in seen:
            seen.add(cur)
            t = f._lt.get(str(cur)) or {}
            nxt = t.get("de_facto_liege")
            if not isinstance(nxt, int):
                cand = t.get("de_jure_liege")
                nxt = cand if (isinstance(cand, int)
                               and f._ever_held_title(cand)) else None
            if not isinstance(nxt, int):
                return cur if cur != tid else None
            cur = nxt
        return None

    liege_of = {}
    for tid in sorted(keep_tids):
        sup = _up_liege(tid)
        if sup is not None and sup != tid:
            # v64 (问题4) 自检: 宗主必须是「存在过的」头衔。de_facto 链理论上只会
            # 指向有人持有的头衔, 此处兜住存档异常, 防幽灵政权 (鞑靼帝国/图兰帝国)
            # 经任何路径再漏进事实面。
            if not f._ever_held_title(sup):
                _PHANTOM_LIEGE_LOG["lines"] += 1
                if len(_PHANTOM_LIEGE_LOG["samples"]) < 12:
                    _PHANTOM_LIEGE_LOG["samples"].append(
                        f"{f.cache.get('player_id')}: 头衔 {tid} 的法理宗主 "
                        f"{sup} ({(f._lt.get(str(sup)) or {}).get('key') or ''}) 从未创建")
                try:
                    llm.log(f"幽灵宗主: 头衔 {tid} 的法理宗主 {sup} "
                            f"({(f._lt.get(str(sup)) or {}).get('key') or ''}) "
                            f"history 空且无持有者 — 不写宗主标注", detail=True)
                except Exception:
                    pass
                continue
            liege_of[tid] = sup
    # 归组: 宗主 → 其下的高层头衔 (下辖层级词按 tier 取)
    vassal_groups = {}
    for tid, sup in liege_of.items():
        vassal_groups.setdefault(sup, []).append(tid)

    def _group_suffix(tid):
        """该头衔的宗主标注: 「，为唐皇朝封臣」; 无宗主 (自成一国) 不给标注。
        v55 (问题2): 去括注, 作同句分句。"""
        sup = liege_of.get(tid)
        if sup is None:
            return ""
        nm = _simple_name(sup)
        return f"，为{nm}封臣" if nm else ""

    def _simple_name(tid):
        """头衔的**宗室/朝廷通称** —— 按 span_end 的时任持有者取 (h_china → 「唐皇朝」)。
        用于宗主标注。"""
        t = f._lt.get(str(tid)) or {}
        if not (t.get("key") or ""):
            return ""
        return f._title_name_at(tid, span_end)

    def _base_name(tid):
        """头衔的**底名** (不含层级词) —— k_qingxu → 「青徐」。
        归组行用它, 免得把「青徐路/福建路」这类**按时任持有者独立性**取的层级词
        (同一头衔在皇帝兼领时叫「国」、臣子受任时叫「路」) 混进同一行。"""
        t = f._lt.get(str(tid)) or {}
        key = t.get("key") or ""
        if not key:
            return ""
        nm = f._name_at_date(tid, span_end) or L.loc(f.table, key) or key
        return str(nm).strip()

    def _tier_tail(name):
        """名字的层级词尾巴 (国/路/州府/皇朝/伯爵领…) —— 用于「同一条里换了层级词」判定。
        「国」是**独立天朝制王国**的层级词 (`_tier_word_at` 查
        `kingdom_celestial_chinese_independent`), 不在 GENERIC_TIER_ZH 里,
        故本地补入。"""
        for w in sorted(f._rank_words | {"国"}, key=len, reverse=True):
            if w and name.endswith(w):
                return w
        return ""

    def _name_stem(name):
        """去掉层级词尾巴的底名 (青徐国 → 青徐)。"""
        t = _tier_tail(name)
        return name[:len(name) - len(t)] if t else name

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
        prev_tail = ""
        bits = []
        for i, (d, holder) in enumerate(dedup):
            if holder == prev:
                continue
            hn = f.name_or(holder, "") if holder is not None else "无"
            end = dedup[i + 1][0] if i + 1 < len(dedup) else span_end
            nm = f._name_in_span(tid, d, end, cid=holder)
            tail = _tier_tail(nm) if nm else ""
            # v38 (问题3): 头衔是「国」还是「路」取决于该任期持有者是否自立 ——
            # 皇帝兼领时显示「青徐国」、臣子受任时显示「青徐路」, 这不是改名。
            # 底名相同而只有层级词不同时, 只留首个 (后文由宗主标注说明归属)。
            if nm and tail and prev_tail and tail != prev_tail \
                    and _name_stem(nm) == _name_stem(prev_nm):
                nm = ""
            if nm and nm != prev_nm:
                bits.append(f"{nm}：{f.date(d)}：{hn}")
                prev_nm = nm
                prev_tail = tail
            else:
                bits.append(f"{f.date(d)}：{hn}")
            prev = holder
        if len(bits) > 1:
            changes.append("，".join(bits) + _group_suffix(tid))
    # v38 (问题3): 同一宗主的头衔归组一行 —— 让「唐皇朝 / 青徐国」并列的两行
    # 一眼看出是同一个朝廷的上下级, 而不是两个并立的政权。
    # v68 (问题1): 归组行按宗主 tid 另存一份, 供「本朝历代」的疆域行复用。
    group_lines = {}
    for sup in sorted(vassal_groups):
        names = []
        for tid in vassal_groups[sup]:
            nm = _base_name(tid)
            if nm and nm not in names:
                names.append(nm)
        if len(names) < 2:
            continue
        snm = _base_name(sup) or _simple_name(sup)
        if not snm:
            continue
        _gln = f"{snm}朝廷所辖，同属一廷：" + "、".join(names)
        changes.append(_gln)
        group_lines[sup] = _gln
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
    # v36 (问题2, 用户拍板3): 主角**获授**的朝廷职位 (太师等) — 《朝局风云录》升沉段用;
    # 只写主角自己受任的职位 (employee=主角), 与廷中僚属花名册分列。
    col, coch = f.court_office_lines()
    if col:
        out["protagonist_offices"] = col
    if coch:
        out["protagonist_office_changes"] = coch
    # v28: 要员隐事 — 最高领主链 (皇帝/路/王国) 与朝廷职司时任者的隐事
    # (用户 2026-09-10 决策: 《朝局风云录》收录最高统治者的秘密)
    out["secrets"] = _realm_secret_lines(f)
    # v68 (问题1): 本朝历代 —— 主角当前最高头衔从**战役起点**以来的国号沿革与历代
    # 持有者 (用户拍板: 篇名《XX历代记》, 移除「朝局动态」块; 有家业者写最高领主的
    # 头衔历史, 仅冒险者营地者本篇略去)。`holder_changes` 保留给其它调用点与既有断言。
    _tt_common, _tt_lines, _tt_chronicle = _top_title_history(
        f, group_lines=group_lines)
    if _tt_lines:
        out["top_title_history"] = _tt_lines
        out["top_title_name"] = _tt_common
    if _tt_chronicle:
        out["dynasty_chronicle"] = _tt_chronicle
    return out


def _realm_secret_lines(f):
    """要员隐事 (v28): 上位链持有人 (不含主角) + 朝廷职司时任者的隐事句,
    上限 6 条; 无则返回 []。v28b: 持有人带官职称谓 (唐皇帝李漼 / 御史大夫郭克勤),
    隐事与其知情者同句。"""
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
            s = f.secret_line(rec, owner_label=f.person_label(oid, date=f.as_of, style="brief"),
                              self_cid=pid, owner=oid)
            if not s:
                continue
            out.append(s)
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


_REL_LOC_TAG_RE = re.compile(
    r"\[(CHARACTER|TARGET_CHARACTER|TARGET_CHARACTER_2|PROVINCE)\."
    r"([A-Za-z_]+?)(?:\|[A-Za-z0-9_]+)?\]")


def _province_label(f, province):
    """省份 id → 地名 (伯爵领名, 取不到退男爵领名); 未知返回 '' (v56)。"""
    if province is None:
        return ""
    try:
        tid = f.county_at_province(province) or f.barony_at_province(province)
    except Exception:
        return ""
    if tid is None:
        return ""
    try:
        return f.title(tid) or ""
    except Exception:
        return ""


def _sub_relation_loc(f, s, owner, target, extra=None, province=None, names=None):
    """关系原因本地化串 → 干净中文句 (替换 CK3 角色/地点/代词占位符)。

    [CHARACTER.*]=记录拥有者, [TARGET_CHARACTER.*]=对方,
    [TARGET_CHARACTER_2.*]=第三人 (involved_character, 如地牢主人),
    [PROVINCE.GetName]=事发地; `|U` 是英文大写变体 (中文忽略);
    Possessive 中文无词形变化, 用原名。

    v56 (问题3 续): 改为**按角色/地点派发**的正则替换 —— 旧稿是逐形列举的替换表,
    认不出 `|U` 与 NoTooltip 的组合形, 落进末尾的清空正则 (主语/宾语被吃掉)。
    另: 模板要用第三人槽而 `extra` 缺失时**整句不出** (返回 '') —— 旧稿把对方名字
    塞进第三人位, 会写成「虐待其配偶，后者是<对方>的亲属」这种错人句;
    实测本档「需第三人∧缺人」= 0 例, 故此改是防守性加固。
    v56 (地点): `[PROVINCE.GetName]` 由 `province` 解析成真实地名 (伯爵领名), 无值时
    退「当地」(旧稿因标签已在建表时被剥, 这句兜底是死代码)。
    v56 (§10): `names` 可显式给出 (owner, target, 第三人) 三个称谓 —— 供事实面走
    `event_name` 口径 (同一人全篇称谓一致), 缺省仍用 `name_or` (保持 v16 起的行为)。
    v63 (第五轮): 新增 `[X.GetDynastyHouseName]` → **真实家族名** (本地化层已保留该
    标签, 见 `localization._KEEP_DYN_RE` ③)。旧表格把它整段剥掉, 于是
    `rival_house_feud_start_of_feud` 渲染成「家族和家族爆发世仇后…」—— 结仇因由
    整句失真, 模型遂自造「因海关/关税结仇」。"""
    if names is not None:
        oname, tname, xname = (list(names) + ["", "", ""])[:3]
    else:
        oname = f.name_or(owner)
        tname = f.name_or(target)
        xname = f.name_or(extra) if isinstance(extra, int) else ""
    pname = _province_label(f, province) if province is not None else ""
    need_x = [False]
    _hcache = {}

    def _hname(cid):
        """角色所属**家族名** (无家族返回空串; 按 id 记忆化)。"""
        if not isinstance(cid, int):
            return ""
        if cid in _hcache:
            return _hcache[cid]
        try:
            hid = f._house_of_cid(cid)
        except Exception:                                 # noqa: BLE001
            hid = None
        nm = (cl.house_name_zh(f.melt, hid) or "") if hid is not None else ""
        if not nm:
            did = cl.dynasty_id_of(f.melt, hid) if hid is not None else None
            nm = (cl.dynasty_name_zh(f.melt, did) or "") if did is not None else ""
        _hcache[cid] = nm
        return nm

    def _rep(m):
        role, acc = m.group(1), m.group(2)
        if role == "PROVINCE":
            return pname or "当地"
        if acc.startswith("GetDynastyHouseName"):
            return _hname({"CHARACTER": owner, "TARGET_CHARACTER": target,
                           "TARGET_CHARACTER_2": extra}.get(role))
        if acc.startswith("GetHerHis"):
            return "其"
        if role == "CHARACTER":
            return oname
        if role == "TARGET_CHARACTER":
            return tname
        if not xname:            # TARGET_CHARACTER_2 缺人 → 整句不出
            need_x[0] = True
            return ""
        return xname

    s = _REL_LOC_TAG_RE.sub(_rep, s)
    if need_x[0]:
        return ""
    # 仍未被认出的具名标签 (Custom(...) 等) 照旧替换/清空
    s = s.replace("[PROVINCE.Custom('TerrainTypeProvince')]", "")
    s = s.replace("[TARGET_CHARACTER.Custom('child_favorite_toy')]", "玩具")
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = s.replace("  ", " ").strip()
    return s


def _player_murder_map(f):
    """主角谋杀集: {victim_id: 谋杀日期} — successful_murder 记忆 ∪ 死亡记录
    killer==主角 (供 _villain_chains / relation_cause_lines 共用)。
    v47: 结果按 Facts 实例记忆化 —— 仇人池的「有无因由」判定会反复问它
    (每次 _enemy_for_facts 一次), 全量扫记忆不必重做。"""
    memo = getattr(f, "_murder_map_memo", None)
    if memo is not None:
        return memo
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        f._murder_map_memo = {}
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
    f._murder_map_memo = murders
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
            out.append(f"{label}{rname}已于{f.date(md)}"
                       + f.death_clause(rid, date=md))
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
    # ④ 同日两族决裂的**触发条** (v63 第五轮, 2026-09-24 用户报告)
    #    埃德伯 907.10.27 那条游戏原因是 `rival_house_feud_start_of_feud`
    #    (「威塞克斯家族和菲利普家族爆发世仇后，A和B成为了仇敌」)—— 它只说
    #    **结果**, 不说世仇因何而起; 而起因就写在**同日**的家族关系流水里
    #    (「昆伯被崔佛无理由囚禁」)。判据: 同日该两族的流水条目中, **点到主角、
    #    没点到仇人本人**的那一条 —— 点到仇人的那条就是「成为仇敌」这一结果本身
    #    (故排除)。措辞与《家族恩怨录》同源 (同一 `_rerender_feud_event`)。
    #    称谓注: 该条流水的两端是**游戏烘焙的短名** (「崔佛」), 未经 v42 的
    #    `event_name` 重渲染, 故同时按全名与名 (「·」前) 两种形态比对。
    #    v79: 触发条本身是**世仇缘由式囚禁**串时, 改用因果句 (`house_feud_reason_
    #    clause` —— 带真实囚禁日), 不再把结仇升级日当囚禁日下发。
    try:
        _cname = f.name_or(cid)
        _pforms = {x for x in (pname, (pname or "").split("·")[0]) if x}
        _clause = f.house_feud_reason_clause(f._house_of_cid(pid),
                                             f._house_of_cid(cid), rel_date)
        if _clause:
            out.append(_clause)
        else:
            for _txt in f.house_flow_on(f._house_of_cid(pid),
                                        f._house_of_cid(cid), rel_date):
                if _cname and _cname in _txt:
                    continue
                if any(x in _txt for x in _pforms):
                    out.append(f"{f.date(rel_date)}，{_txt}")
                    break
    except Exception:
        pass
    return out


# v34 (问题6): 战争类措辞 — 恩怨史补因果节点时, 同日的旧战争句由新节点取代
_WAR_KIND_WORDS = ("宣战", "开战", "应战", "战胜", "战败", "赢得战争")

# v34 (问题7): 囚禁类措辞 — 同日的旧「囚禁了X」由带出狱情形的节点取代
_PRISON_KIND_WORDS = ("囚禁了", "囚禁")

# v79 (用户 2026-09-27): 《家族恩怨录》与仇人列传的数据源是 house_relations 流水原文,
# 同一件事有**两种句式、id 次序相反**, 且缘由式的日期是**结仇升级日** ——
#   · 事件式 (desc, `house_relations_l_simp_chinese.yml:44-51`)
#     「[char]囚禁了[target_char]」/「[char]谋杀了[target_char]」…
#     → id 次序 = (施事者, 受害者), 日期 = 事发日;
#   · 世仇缘由式 (feud head, `:78-95`)
#     「[house_feud_victim]被[house_feud_attacker]无理由囚禁」/「…被…谋杀」/
#     「…被…残忍地折磨」… → id 次序 = (**受害者, 施事者**), 日期 = 结仇升级日。
#     例外: 「绿帽」(`:90`) 是主动句、id 次序与 desc 相同, 故不入本表。
# v78-2 的流水兜底按 id 次序硬读, 于是把「昆伯被崔佛囚禁」读成「昆伯囚禁崔佛」,
# 还给主角挂上「至末档仍在押」的结局 (用户报告: 崔佛从未被囚; 昆伯 1年4个月后即获释)。
# 实测 (`tools/tests/probe_v79_feudprison.py` + `probe_v79_feudreason.py`, 三战役):
# 缘由式条目共 16 条 (囚禁 4 / 折磨 11 / 谋杀 1), 其中 15 条在同一条关系记录里都有
# **同一受害者的事件式专实行** —— 故囚禁侧缘由式整条不入事件、不造节点; 仇人列传的
# 结仇缘由一律改写成**因果句**并把真日期写进去 (`house_feud_reason_clause`)。
_FEUD_HEAD_KINDS = (
    # (类别, 缘由串关键词, 事件式关键词, 因果句句式)
    ("prison", "囚禁", "囚禁了", "为{j}所囚"),
    ("murder", "谋杀", "谋杀了", "被{j}谋杀"),
    ("torture", "折磨", "折磨了", "为{j}所折磨"),
    ("castrate", "阉割", "阉割了", "被{j}阉割"),
    ("blind", "致盲", "致盲了", "被{j}致盲"),
)


def _feud_head_kind(raw):
    """该条流水是否为**世仇缘由式的被动句** → 对应 `_FEUD_HEAD_KINDS` 行, 否则 None。

    判据: 含缘由串关键词、**不含**事件式关键词、且含「被」。`raw` 传
    `house_relations.database[*].history[*].change_reason` 原文 (渲染后的句面同样
    保留「被」, 故两者皆可)。"""
    s = str(raw or "")
    if "被" not in s:
        return None
    for row in _FEUD_HEAD_KINDS:
        if row[1] in s and row[2] not in s:
            return row
    return None


def _is_feud_reason_prison(raw):
    """该条流水是否为**世仇缘由式的囚禁被动句** (id 次序 = 被囚者, 施事者)。

    囚禁侧单独收口: 缘由式整条不入事件、不造节点 (该囚禁事实另有事件式专属行)。"""
    row = _feud_head_kind(raw)
    return bool(row) and row[0] == "prison"

# v34 (问题1, 用户拍板): 这些关系链在句面上写明「谁是谁的亲生子女」,
# 属史官不可知的内宅隐情 — 只进《家室列传》《阴私录》, 不进《本纪》等公开篇目。
_PRIVATE_CHAIN_MODULES = frozenset({"托卵承嗣", "血脉登基"})

CHAIN_PRIVATE = _PRIVATE_CHAIN_MODULES


def _villain_chains(f):
    """大奸大恶关系链 (v15, 程序直算): [(模块名, 自然语言句, 是否揭底链)]。
    数据源: 缓存 family/death/memories + 熔件 titles/heir/schemes。
    - 奸夫谋夫: 主角谋杀了某人, 而该人之配偶是主角情人 (遗孀/鳏夫改嫁情形一并写出);
    - 托卵承嗣: 法理父 ≠ 实父 — 法理父抚养了主角之子/女 (或主角抚养他人之子/女);
    - 共谋暗杀: 熔件 active schemes 中 type=murder 且 owner=主角 → agent_slots 参与者;
    - 血亲之刃: 主角谋杀了自己的血亲 (父/母/子女/兄弟姊妹);
    - 血脉登基: 高位头衔 (k_/e_/h_) 第一继承人实为主角之子/女 (私生),
      且同母手足中有被主角谋杀者时一并点出。
    所有条目按 as_of 截断 (十年传记只写该时期内的戏剧)。

    v34 (问题1, 用户拍板「不留」): 第三条返回值为**揭底链标记** —
    `_PRIVATE_CHAIN_MODULES` 里的链 (托卵承嗣/血脉登基) 把「谁是谁的亲生子」
    写在句面上, 属史官不可知的内宅隐情, 只进《家室列传》《阴私录》;
    《本纪》等公开篇目的档案只收非揭底链。"""
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
            # v28b: 受害者称谓统一 (官职/称号+名, 按卒日锚点)
            disp = f.person_label(victim, date=f.as_of, style="brief") or vname
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
                kname = f.person_label(kid, date=f.as_of, style="brief") or f.name_or(kid)
                if kname:
                    ksex = "女" if is_female(kid) else "子"
                    # v75 (凶手点名): 公开档写世人说法 (未公开者不点名)
                    kin_note = (f"；其{ksex}{kname}已于{f.date(kd)}"
                                + f.death_clause(kid, date=kd))
                break
            # v75 (凶手点名): 受害者本人的结局同理走公开档
            _vcl = f.death_clause(victim, date=vdate)
            chains.append(("奸夫谋夫",
                f"{f.date(vdate)}，{disp}{_vcl}——"
                f"{sname}{lname}正是{pname}的情人{remarry}{kin_note}。", False))

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
                f"{lfname}抚养的{joined}，实为{pname}之{sex}。", True))
        else:
            chains.append(("托卵承嗣",
                f"{pname}抚养的{joined}，实为{rfname}之{sex}。", True))

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
                # v29b: 角色词前置连写 (「同谋张三」), 不用「张三（同谋）」括注同位语;
                # 同角色者并在一处 (同谋张三、李四), 角色不同才并列。
                by_role = {}
                order = []
                for an, at in agents[:3]:
                    if at not in by_role:
                        by_role[at] = []
                        order.append(at)
                    by_role[at].append(an)
                shown = [f"{at}{'、'.join(by_role[at])}" for at in order]
                tail = f"等{len(agents)}人" if len(agents) > 3 else ""
                chains.append(("共谋暗杀",
                    f"密谋刺杀{tname}者以{pname}为首，"
                    f"参与者{'、'.join(shown)}{tail}。", False))
            else:
                chains.append(("共谋暗杀",
                    f"{pname}正密谋刺杀{tname}。", False))
        elif isinstance(tgt, int) and tgt == pid and isinstance(owner, int) and owner != pid:
            oname = f.name_or(owner)
            if oname:
                chains.append(("共谋暗杀",
                    f"{oname}正密谋刺杀{pname}。", False))

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
                # v75 (凶手点名): 公开档写世人的说法 —— 未公开的凶杀
                # `death_clause` 已不点名 (神秘死亡 / 失踪而亡 …)
                chains.append(("血亲之刃",
                    f"{rel}{vname}{f.death_clause(victim, date=vdate)}。", False))

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
                                + f.death_clause(s, date=sdate))
                break
        sex = "女" if is_female(heir0) else "子"
        # v75: 虚位御座 (天皇座) 的继承句写「天皇第一继承人」, 不写游戏机械串
        # 「高御座府第一继承人」(御座是位号, 不是地名)
        tname = f.throne_word(tid) or f.title(tid)
        if rf == pid:
            mname = f.name_or(mother) if mother in lovers else ""
            who = (f"{pname}与{mname}之{sex}" if mname
                   else f"{pname}之{sex}")
        else:
            who = f"{pname}情人之{sex}"
        chains.append(("血脉登基",
            f"{hname}为{tname}第一继承人，实为{who}{dead_sib}。", True))

    return chains


# v41 (问题4): 同父异母联姻 — 主角的合法子女与主角的**非婚生子女**结为夫妻/
# 情人, 或二人生育。三类料此前分散在三处 (「与X私通」在家人隐事、「所生X血统
# 有争」在把柄、「X实为诺兰之子」在戏剧性事件), 模型读不出「女儿嫁的正是自己
# 的私生子」这层关系 (诺兰第四个十年实测「两条生父线, 由同一个男人名氏把一条
# 血脉分成错层」)。此处由程序直算一句连线, 只进内宅档 (private=True)。
_KIN_MARRIAGE_KEYS = ("primary_spouse", "spouse", "former_spouses",
                      "concubine", "former_concubines", "ever_spouses")


def _kin_blood_links(f):
    """[(模块名, 句, 是否揭底链)] — 主角子女与其非婚生同胞的联姻/生育连线。

    判定 (全部由缓存 family 字段确定):
      · S = 主角的子女 (family.child); B = 实父或实母为主角的非婚生子女
        (real_father / real_mother == pid 且 S 的集合不含 B);
      · 触发: S 与 B 互为配偶 (或 S 的配偶是 B), 或 S 与 B 有共同子女。
    日期取双方记忆中最早的婚配/私情日 (取不到则不写日期, 只写关系)。
    按 as_of 截断 (十年传记只写该时期内的)。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    chars = cache.get("characters") or {}
    prec = chars.get(str(pid)) or {}
    pfam = prec.get("family") or {}
    pname = f.name_or(pid)
    ao = cl.date_key(f.as_of) if f.as_of else None

    def in_span(d):
        return ao is None or not d or cl.date_key(d) <= ao

    def fam_of(cid):
        return (chars.get(str(cid)) or {}).get("family") or {}

    def is_female(cid):
        return f._is_female(cid)

    legal = {int(x) for x in (pfam.get("child") or []) if isinstance(x, int)}
    # 主角的非婚生子女 (实父/实母 = 主角, 不在合法子女集内)
    bastards = set()
    for cid, rec in chars.items():
        try:
            icid = int(cid)
        except (TypeError, ValueError):
            continue
        if icid == pid or icid in legal:
            continue
        cf = rec.get("family") or {}
        rf = (cf.get("real_father") or [None])[0]
        rm = (cf.get("real_mother") or [None])[0]
        if rf == pid or rm == pid:
            bastards.add(icid)
    if not legal or not bastards:
        return []
    out = []
    seen = set()
    for b in sorted(bastards):
        bfam = fam_of(b)
        # 配偶档与情人档分开: 「结为夫妇」只用于真婚事, 非配偶写「私通」
        # (v41: 旧稿把私情也写成「结为夫妇」, 模型据此把私生子的情人说成夫妻)
        bsp = {x for x in (bfam.get("primary_spouse") or [])
               + (bfam.get("spouse") or [])
               + (bfam.get("former_spouses") or []) if isinstance(x, int)}
        blov = {x for x in (bfam.get("lover") or []) if isinstance(x, int)}
        for m in (chars.get(str(b)) or {}).get("memories") or []:
            if str(m.get("type") or "") in ("became_lovers", "had_sex") \
                    or str(m.get("type") or "").startswith(_SEX_MEM_PREFIX):
                for v in (m.get("participants") or {}).values():
                    if isinstance(v, int) and v != b:
                        blov.add(v)
        bkids = {x for x in (bfam.get("child") or []) if isinstance(x, int)}
        for s in sorted(legal):
            if s == b:
                continue
            sfam = fam_of(s)
            ssp = {x for x in (sfam.get("primary_spouse") or [])
                   + (sfam.get("spouse") or [])
                   + (sfam.get("former_spouses") or []) if isinstance(x, int)}
            skids = {x for x in (sfam.get("child") or []) if isinstance(x, int)}
            pair = tuple(sorted((b, s)))
            married = (b in ssp) or (s in bsp)
            if not married and b not in blov and s not in blov:
                continue
            # 关系起始日: 婚配优先 (married 记忆), 否则私情记忆; 取最早
            date = ""
            for m in (chars.get(str(s)) or {}).get("memories") or []:
                parts = m.get("participants") or {}
                if b not in [v for v in parts.values() if isinstance(v, int)]:
                    continue
                if (m.get("type") or "") not in (
                        "married", "became_lovers", "had_sex") \
                        and not str(m.get("type") or "").startswith(_SEX_MEM_PREFIX):
                    continue
                d = str(m.get("creation_date") or "")
                if d and (not date or cl.date_key(d) < cl.date_key(date)):
                    date = d
            if not in_span(date):
                continue
            if pair in seen:
                continue
            seen.add(pair)
            sn = f.person_label(s, date=f.as_of, style="brief") or f.name_or(s)
            bn = f.person_label(b, date=f.as_of, style="brief") or f.name_or(b)
            if not sn or not bn:
                continue
            sw = "女" if is_female(s) else "子"
            bw = "女" if is_female(b) else "子"
            mother = (bfam.get("mother") or [None])[0]
            mn = ""
            if isinstance(mother, int) and mother != pid:
                mn = f.person_label(mother, date=f.as_of, style="brief") or ""
            whose = f"{pname}与{mn}之{bw}" if mn else f"{pname}之{bw}"
            date_txt = f"{f.date(date)}，" if date else ""
            rel = "结为夫妇" if married else "私通相恋"
            line = (f"{date_txt}{pname}之{sw}{sn}与{bn}{rel}；"
                    f"{bn}实为{whose}，与{sn}为同父异母兄妹。")
            if married and (bkids & skids):
                kid = sorted(bkids & skids)[0]
                kn = f.person_label(kid, date=f.as_of, style="brief") or f.name_or(kid)
                if kn:
                    line = line.rstrip("。") + f"，二人生有{kn}。"
            out.append(("同父异母联姻", line, True))
    return out


def _kill_family(f, cid):
    """被杀者的 family 字典 (缓存优先)。"""
    return ((f.cache.get("characters") or {}).get(str(cid)) or {}).get("family") or {}


def _kill_kin_ids(f, cid, key):
    """被杀者 family[key] 的 id 集 (含父/母/同胞)。"""
    out = set()
    for x in (_kill_family(f, cid).get(key) or []):
        try:
            out.add(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _kill_kin_note(f, members):
    """同组合并后的血缘按语: 「俱为唐皇帝李漼之子女」/「同胞兄弟姐妹」。"""
    def _common(key):
        sets = [_kill_kin_ids(f, m.get("id"), key) for m in members]
        sets = [s for s in sets if s]
        if not sets:
            return set()
        return set.intersection(*sets)

    for key in ("father", "mother"):
        ids = _common(key)
        if ids:
            pid = sorted(ids)[0]
            nm = f.kin_label(pid) or f.name_with_regnal(pid)
            if nm:
                return f"俱为{nm}之子女"
    return "同胞兄弟姐妹"


def _group_killed_by_kin(entries, f):
    """同日而死的血亲合并为一传 (修复方案_菲利普4.md 问题7)。

    判据: 共父 / 共母 / 一方在另一方 siblings 内 — 同日死者按血缘做并查集,
    组内只留组首条, 组首带 group=[其余成员…] 与 kin_note。组内成员不再单列,
    故《刺客列传》的纪事切片以「组」为单位, 不会把同胞劈到两个板块。"""
    by_date = {}
    for e in entries:
        by_date.setdefault(e.get("death_date"), []).append(e)
    out = []
    for d, group in by_date.items():
        if len(group) < 2 or d == "9999.9.9":
            out.extend(group)
            continue
        n = len(group)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(n):
            for j in range(i + 1, n):
                a, b = group[i], group[j]
                kin = bool(_kill_kin_ids(f, a.get("id"), "father")
                           & _kill_kin_ids(f, b.get("id"), "father")) \
                    or bool(_kill_kin_ids(f, a.get("id"), "mother")
                            & _kill_kin_ids(f, b.get("id"), "mother")) \
                    or b.get("id") in _kill_kin_ids(f, a.get("id"), "siblings") \
                    or a.get("id") in _kill_kin_ids(f, b.get("id"), "siblings")
                if kin:
                    ra, rb = find(i), find(j)
                    if ra != rb:
                        parent[rb] = ra
        comps = {}
        for i in range(n):
            comps.setdefault(find(i), []).append(i)
        for _root, idxs in sorted(comps.items()):
            members = [group[i] for i in idxs]
            if len(members) < 2:
                out.extend(members)
                continue
            members.sort(key=lambda e: e.get("death_date") or "")
            head = members[0]
            head["group"] = members[1:]
            head["kin_note"] = _kill_kin_note(f, members)
            out.append(head)
    out.sort(key=lambda e: cl.date_key(e["death_date"]))
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
        # v30: 凶手称谓缩为「其」— 刺客列传凶手恒为主角 (问题8)
        ds = _death_sentence(f, cid, killer_pronoun=True, insider=True)
        if not ds:
            mc = f._chars.get(str(cid)) or {}
            mdd = (mc or {}).get("dead_data") or {}
            if mdd and mdd.get("date"):
                clause = f.death_clause(cid, date=mdd.get("date"),
                                        reason=mdd.get("reason"),
                                        killer=mdd.get("killer"), imprison=True,
                                        insider=True)
                # v30: 与主路径同口径 — 凶手为主角时称谓缩为「其」(问题8)
                # v42 (问题4): 称谓出口与 death_clause 同源 (event_name)
                kk = mdd.get("killer")
                if kk is not None:
                    klabel = f.event_name(kk, date=f.as_of)
                    if klabel and klabel in clause:
                        clause = clause.replace(klabel, "其")
                ds = f"{f.name_or(cid)}死于{f.date(mdd.get('date'))}，{clause}。"
                # v24: 熔件反查兜底同样附受害者所在地 (男爵领; 无则省略)
                if mdd.get("killer") == pid:
                    vp = f.victim_place(cid)
                    if vp:
                        ds = ds.rstrip("。") + f"，死于{vp}。"
        _ddate = (prof.get("death") or {}).get("date")
        entry = {
            "id": cid,
            # v17: 死者名带世系编号 (以死期首要头衔计算, 鲁斯兰·克里维奇二世)
            "name": f.name_with_regnal(cid, date=(prof.get("death") or {}).get("date")),
            "birth": f.date(prof.get("birth")),
            "death": ds or "（死因不详）",
            "death_date": (prof.get("death") or {}).get("date") or "9999.9.9",
            # v24: 受害者死前最近可知所在男爵领 (无则 '', 调用方省略标注)
            "victim_place": f.victim_place(cid),
            # v75 (凶手点名): 该凶杀是否**世人共知** (killer_known 旗标 ∨ 死因
            # 自带公开性)。快照落盘后 `verify_fast` 免熔件即可复核公开档口径。
            "killer_public": f.killer_is_public(cid),
            # v37 (问题8): 起义领袖的起事信息 (起于X州 / 聚众N州 / 反抗X) —
            # 起义头衔带的真地点, 补上死者「无地可依」的空白
            "uprising": f.uprising_info(cid),
            "uprising_line": f.uprising_line(cid),
            "house": _dynasty_display(prof.get("dynasty_name"),
                                      prof.get("house_name")),
            "house_branch": _house_branch(prof.get("dynasty_name"),
                                          prof.get("house_name")),
            # v81 (问题1): 家族称法按文化/名序组装
            "house_label": house_label(prof.get("dynasty_name"),
                                       prof.get("house_name"),
                                       f.name_order(cid), None),
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
            # v56 (§10): 与 `events` 逐位对应的记忆型 — 《刺客列传》的婚恋行按**型**
            # 过滤, 不再按句面关键词 (相恋句改出游戏缘由句「…相爱了」后, 旧的关键词
            # 过滤匹配不到, 那一行会整条消失)。
            "event_types": [],
            "role": "",   # 与主角的关系 (子/友/敌...) 由 biography 侧根据记忆推断
        }
        # v28b: 称谓统一 — 死者标签 (官职/称号+名) 由 facts 一次组好,
        # biography._assassin_kill_lines / 开篇名录不再自行拼 office+name
        entry["label"] = (f.person_label(cid, date=_ddate, style="brief")
                          or entry["name"])
        for mem in prof.get("memories") or []:
            s = _mem_sentence(f, cid, mem)
            if not s:
                continue
            # v56 (§10-E): 相恋**双方各持一条**同型记忆 (participants 互指) ——
            # 两个当事人都在本名录内时只留一侧 (id 较小者), 免同一件事在
            # 《刺客列传》里出两行正反句 («A和B相爱了» + «B和A相爱了»)。
            # 时间线那一侧由 `_drop_mirror_pairs` 处理 (见 `_MIRROR_TYPE_PAIRS`)。
            if str(mem.get("type") or "") == "became_lovers":
                _oth = (mem.get("participants") or {}).get("new_relation")
                if isinstance(_oth, int) and _oth in killed and _oth < cid:
                    continue
            # v34b: 事实日 (头衔得失用 title history 事件日)
            entry["events"].append(
                f"{f.date(f.mem_date(cid, mem))}，{s}")
            entry["event_types"].append(str(mem.get("type") or ""))
        _pairs = sorted(zip(entry["events"], entry["event_types"]))
        entry["events"] = [p[0] for p in _pairs]
        entry["event_types"] = [p[1] for p in _pairs]
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
    # v30: 同日而死的血亲合并为一传 (问题7) — 放在窗口/低贱者过滤之后,
    # 组内成员此后不再单列 (纪事切片以组为单位)
    return _group_killed_by_kin(out, f)


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
    """【冒险者行踪】(v29, 问题2): 只记**无地冒险者时期**的营地阶段与驻地。

    用户决策 2026-09-11: 定居/世族庄园时期的驻地没有意义 (player_locations 里的
    旅行落点尤甚), 头衔阶段在【人物档案】的历任句里已有; 故本块只保留营地持有
    区间内的「驻X」行与营地阶段行。无营地期一律返回 [] → 整块不下发。
    十年传记按 as_of 截断。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    camps = f.camp_intervals(pid)
    if not camps:
        return []
    items = []  # (date_key, 行文本)
    # 1) 营地阶段行 (游戏口径营地宗旨词; 与 held_titles 同源)
    for tid, ivs in (f._hold_intervals(pid) or {}).items():
        if f.title_kind(tid) != "camp":
            continue
        for iv in ivs:
            g = iv[0] if iv else None
            if not g:
                continue
            if f.as_of and cl.date_key(g) > cl.date_key(f.as_of):
                continue
            end = (iv[1] if len(iv) > 1 else None) or f.as_of \
                or cache.get("last_date")
            # v52 (问题2): 持有者行只用营地本名 (不含「营地」层级词),
            # 与历任阶段行同口径 —— 旧稿此处写出「私生子大队公国头目」。
            nm = f._name_at_date(tid, g) or f.title_base_name(tid) or ""
            w = f._camp_holder_word(pid, g)
            base = f"{nm}{w}" if nm and w else (f"{nm}之主" if nm else "")
            if base:
                items.append((cl.date_key(g),
                              f"{f.date(g)}任无地冒险者营地之{base}"))
    # 2) 驻地轨迹: 只取落在营地区间内的 location (旅行落点一律不收)
    hist = cache.get("player_locations") or []
    if f.as_of:
        aok = cl.date_key(f.as_of)
        hist = [loc for loc in hist
                if not loc.get("date") or cl.date_key(loc["date"]) <= aok]
    seen = set()
    for loc in hist:
        if not loc.get("date") or not f.in_camp_period(loc["date"], pid):
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
    # 按行文本去重 (同日 营地阶段+驻地 两行都保留, 只去掉完全重复的行)
    out = []
    seen_line = set()
    for dk, ln in items:
        if ln in seen_line:
            continue
        seen_line.add(ln)
        out.append(ln)
    return out[:40]


def _nomad_stations(f):
    """【游牧行踪】(v64, 问题1): 游牧时期的**大帐位置**轨迹。

    用户 2026-09-25 拍板: 「和冒险者类似, 只记录大帐位置的移动」。毡帐本身
    `landless: true`, 不作领地进历任 (`_primary_group` 已排除), 故「大帐在哪」
    由本块承担:
      · 立帐行 = 毡帐头衔 (x_c_nomad_*) 的取得日 + 游戏显示名
        (`nomad_title_name` = 宗族名 + 「游牧营地」, 故写作「立菲利普游牧营地」);
      · 驻X 行 = 毡帐持有区间内的逐年 location (只取本档玩家, 旅行落点不收)。
    无游牧毡帐期一律返回 [] → 整块不下发。十年传记按 as_of 截断。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    camps = f.camp_intervals(pid, kind="nomad")
    if not camps:
        return []
    items = []
    for tid, ivs in (f._hold_intervals(pid) or {}).items():
        if f.title_kind(tid) != "nomad":
            continue
        for iv in ivs:
            g = iv[0] if iv else None
            if not g:
                continue
            if f.as_of and cl.date_key(g) > cl.date_key(f.as_of):
                continue
            nm = f._site_name(tid, cid=pid) or f.title_base_name(tid) or ""
            if nm:
                items.append((cl.date_key(g), f"{f.date(g)}立{nm}"))
    hist = cache.get("player_locations") or []
    if f.as_of:
        aok = cl.date_key(f.as_of)
        hist = [loc for loc in hist
                if not loc.get("date") or cl.date_key(loc["date"]) <= aok]
    seen = set()
    for loc in hist:
        if not loc.get("date") or not f.in_camp_period(loc["date"], pid, kind="nomad"):
            continue
        county = f.county_at_province(loc.get("province"))
        if county is None:
            continue
        # v66: 驻X 的名字走【用地名】—— 他持有过的郡与其历任行**同名** (按档取
        # 取得前的动态名), 只是路过 (未持有) 的郡取该年档的名字。旧稿用末档粘滞名,
        # 于是 936 年的一行写成「驻马扎尔迈杰希部」(954 年才有的名字)。
        cname = f.title(county, date=loc.get("date"), site=True, site_cid=pid)
        if not cname:
            continue
        key = (loc.get("date"), cname)
        if key in seen:
            continue
        seen.add(key)
        items.append((cl.date_key(loc["date"]), f"{f.date(loc['date'])}驻{cname}"))
    items.sort(key=lambda x: x[0])
    out = []
    seen_line = set()
    for _dk, ln in items:
        if ln in seen_line:
            continue
        seen_line.add(ln)
        out.append(ln)
    return out[:40]


_PLAGUE_INTENSITY_ZH = {"minor": "轻疫", "major": "重疫", "apocalyptic": "毁灭之疫"}


def _plague_facts(f):
    """瘟疫风味 (v29, 问题7): 读本档 epidemics 的**游戏动态名**与感染范围。

    用户决策 2026-09-11 (方案门槛 A): 只写触及主角封地/所在郡的疫情, 以及主角与
    家人所患疾病的疫情; 远地瘟疫一律不写。名称一律取存档里的 `name`
    (游戏算好: 「李黯之火」「撒丁痘」), 缺失时回退病名本地化 (trait_smallpox=天花)。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return {}
    db = (f.melt.get("epidemics") or {}).get("database") or {}
    if not isinstance(db, dict) or not db:
        return {}
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    ld = rec.get("landed") or {}
    # 主角相关省份: 封地各头衔首府 + 庄园/毡帐驻地 + 现所在郡
    mine = set()
    lt = f._lt
    for t in (ld.get("domain") or []):
        cap = (lt.get(str(t)) or {}).get("capital")
        if isinstance(cap, int):
            mine.add(cap)
    dom_prov = ((rec.get("landed") or {}).get("domicile_province")
                or ld.get("domicile_province"))
    if isinstance(dom_prov, int):
        mine.add(dom_prov)
    loc_prov = f.character_location_province(pid)
    if isinstance(loc_prov, int):
        mine.add(loc_prov)
    if not mine:
        return {}
    fam = rec.get("family") or {}
    kin = [pid]
    for k in ("primary_spouse", "spouse", "former_spouses", "concubine",
              "former_concubines", "child", "father", "mother", "siblings"):
        for x in fam.get(k) or []:
            if isinstance(x, int) and x not in kin:
                kin.append(x)
    lines = []
    for eid, e in db.items():
        if not isinstance(e, dict):
            continue
        typ = e.get("type") or ""
        name = str(e.get("name") or "")
        disease = _trait_name(f.table, typ) if typ else ""
        label = name or disease
        if not label:
            continue
        created = str(e.get("creation_date") or "")
        if f.as_of and created and cl.date_key(created) > cl.date_key(f.as_of):
            continue
        known = cache.get("epidemics") or {}
        hist = known.get(str(eid)) or {}
        if hist.get("lost_at") and f.as_of \
                and cl.date_key(hist["lost_at"]) <= cl.date_key(f.as_of):
            continue            # 该疫已平息
        where = disease if (disease and disease != name) else ""
        intensity = _PLAGUE_INTENSITY_ZH.get(str(e.get("intensity") or ""), "")
        # ① 主角与家人是否染上该疫 (病特质与疫情 type 同名)
        hit_kin = []
        if typ:
            for cid in kin:
                if f._has_trait_at(cid, typ):
                    hit_kin.append(f.kin_label(cid) if cid != pid
                                   else (f.person_label(pid, date=f.as_of, style="brief")
                                         or f.name_or(pid)))
        # ② 主角封地/所在郡是否在其感染之列
        inf = {int(x) for x in (e.get("infections") or {}) if str(x).isdigit()}
        hit_prov = sorted(mine & inf)
        if not hit_kin and not hit_prov:
            continue
        head = f"{f.date(created)}，{label}"
        if where:
            # v55 (问题2): 去括注 —— 「…，赤烈咳，属肺痨，轻疫」
            head += f"，属{where}"
        if intensity:
            head += f"，{intensity}"
        bits = [head]
        if hit_prov:
            ctid = f.county_at_province(hit_prov[0])
            cname = f.title(ctid) if ctid is not None else ""
            bits.append(f"疫及主角封地{cname}" if cname else "疫及主角所居之地")
            n = e.get("num_infected_provinces") or len(inf)
            if n:
                bits.append(f"蔓及{n}州")
        if hit_kin:
            bits.append("、".join(hit_kin) + "染此疫")
        lines.append("，".join(bits) + "。")
    if not lines:
        return {}
    return {"lines": lines[:4]}


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
    # v60 (问题3): 婚配闩存并进世系 —— 与 `_protagonist_facts` 同源
    fam = f.merge_spouse_latch(fam, f.as_of)
    fem = f._is_female(pid)
    lines = []
    pname = f.name_or(pid)
    lines.append(f"一世 {pname}，{f.date(rec.get('birth'))}生")
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
    # v70 (用户拍板: 「姐姐姐姐一类的重复一起改掉」): 同一人只进一行 —— 存档的
    # former_spouses 会把现配偶一并列出 (与 `_protagonist_facts` 同源, 见该处注释)
    _used_mar = set(spouses) | set(side)
    for key, label in rows:
        if key == "primary_spouse_key":
            ids = spouses
        elif key == "side_spouse_key":
            ids = side
        elif key in ("concubine", "former_concubines", "former_spouses"):
            ids = [x for x in (fam.get(key) or []) if x not in _used_mar]
            _used_mar.update(ids)
        else:
            ids = fam.get(key) or []
        if not ids:
            continue
        bits = []
        for x in ids:
            n = f.kin_label(x)
            if not n:
                continue
            # v43: 世系表的配偶行同样标出母系婚 (入赘) 与子女归属
            if key in ("primary_spouse_key", "side_spouse_key"):
                n += f.marriage_lineality_note(pid, x, before=f.as_of)
            bits.append(n)
        if bits:
            lines.append(f"　{label}：{'、'.join(bits)}")
    return lines


def _secrets_facts(f):
    """隐事事实 (v28): 主角/家人近臣的隐事、知情情形、把柄、本十年见载事件。

    返回 {held, held_murder, held_unrevealed, kinsmen, known, events, any};
    无相关隐事时返回 {} (剧本不生成《阴私录》)。
    v28b: 同一持有人的多桩隐事并成一行 (持有人只写一次), 知情者并入同句,
    见载年与知情年同年时只写一次年份; 把柄按对方持有人归并。
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
    # v56 (问题4): 主角称谓与全篇一致 —— 用 event_name (主角只出名字), 头衔只在
    # 《传主档案》一次立名; 旧稿 style="brief" 使「秦皇帝撒旦之种施沙米尔」逐行泛滥。
    plabel = f.event_name(pid, f.as_of) or f.name_or(pid)
    if held:
        # 主角称谓与全篇一致 (时间线/档案同为 event_name)
        lines = f.secret_lines(held, owner_label=plabel, self_cid=pid, owner=pid)
        revealed = any(f.secret_knowers(r, self_cid=pid) for r in held)
        if lines:
            out["held"] = lines
        if not revealed:
            out["held_unrevealed"] = True      # 至今无人知晓
    if murder:
        out["held_murder"] = len(murder)
        names = []
        for rec in murder:
            t = rec.get("target")
            nm = f.person_label(t, date=f.as_of, style="brief") if isinstance(t, int) else ""
            if nm:
                names.append(nm)
        if names:
            out["held_murder_names"] = names[:6]
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
        recs = f.secrets_owned_by(kid, cut)
        if recs:
            # v28b: 同一家人的多桩隐事并成一行
            kin_lines.extend(f.secret_lines(recs, owner_label=f.kin_label(kid),
                                            self_cid=pid, owner=kid))
    if kin_lines:
        out["kinsmen"] = kin_lines[:10]
    # 主角握有的他人把柄 (v28b: 按对方持有人归并, 主角名只写一次)
    # v35 (问题2): 每桩**必须带年份** —— 旧稿此段单排 `secret_topic` 而丢掉
    # `_first_seen_note`, 于是同一块里「艾哈迈德…(自881年见载)」带年、而
    # 「握有贞子的把柄：暗行巫术」不带年; 提示词又要求写出见载年份, 模型只能写
    # 「何时见载、何时知情, 本篇未著其年, 则其见载亦在此数年之间」(德圣塔实测)。
    # 年份由程序给足, 提示词侧不再索要。
    groups = {}
    for rec in f.secrets_known_by(pid, cut):
        o = rec.get("owner")
        if isinstance(o, int):
            groups.setdefault(o, []).append(rec)
    known = []
    for oid, recs in groups.items():
        owner = f.person_label(oid, date=f.as_of, style="brief")
        if not owner:
            continue
        topics = []
        for r in recs:
            t = f.secret_topic(r, self_cid=pid)
            if not t:
                continue
            note = f._first_seen_note(r)
            if note:
                # v55 (问题2): 去括注 —— 见载年作分句接在主题后
                t += f"，{note}"
            topics.append(t)
        if not topics:
            continue
        known.append(f"{plabel}握有{owner}的把柄：" + "；".join(topics) + "。")
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
        # v28b: 事件行同样用统一称谓 (主角/家人)
        olabel = plabel if owner == pid else f.kin_label(owner)
        s = f.secret_line(dict(rec, first=True), owner_label=olabel,
                          knowers=False, self_cid=pid, owner=owner)
        if s:
            # 事件行前缀已给日期, 句内不再重复年份
            events.append(f"{f.date(fs)}，{s}")
    if events:
        out["events"] = sorted(set(events))[:12]
    # v31 (问题5): 牵制 (把柄维度) — 主角握有 / 他人握有对主角的。
    # 用户决策: 牵制只随《阴私录》下发, 不进《本纪》。
    # v35 (问题3) / v38 (问题2): 牵制按白名单过滤 (见 Facts._hook_kept)。
    hl = f.hook_lines()
    if hl.get("held"):
        out["hooks_held"] = hl["held"]
    if hl.get("over"):
        out["hooks_over"] = hl["over"]
    # v35 (问题4): 奴役 (Carnalitas) 单独成块 —— 旧稿把「没为奴隶」整个读成
    # 「抓了又放」, 因为奴役关系从未进过缓存; 现由 cache["enslavements"] 直出。
    # v38 (问题4): 在册与昔日分两档下发 (昔日档写明何时、为何不再是主角的奴隶)。
    en = f.enslaved_lines()
    if en.get("lines"):
        out["enslaved"] = en["lines"]
    if en.get("former"):
        out["enslaved_former"] = en["former"]
    # v38 (问题1): Carnalitas 事件好感 (强奸/奴役/逼良为娼/前主奴) — 自带 start_date,
    # 覆盖「不留记忆」的互动; 与性事记忆互为佐证。
    cp = f.carnal_opinion_lines()
    if cp.get("lines"):
        out["carnal_opinions"] = cp["lines"]
    vl = f.carnal_victim_line()
    if vl:
        out["carnal_victim"] = [vl]
    # v59 (问题2, 用户 2026-09-23 拍板): 性事只在《列传·好友》《列传·仇人》里用 ——
    # 「强迫之事如下」事实块随之撤下 (`harm_lines` 已空实现, 此处不再下发 `harm`)。
    # 性事行的载体改为好友/仇人两篇的【相关年表】(年表闸见 `_timeline`)。
    hl = f.harm_lines()
    if hl:
        out["harm"] = hl
    # v40: 性病传播的事实行 (无源则写「染上」)。
    # v59: 「可挂性事」的补注出口随性事退出年表而停用, 本行成为唯一出口。
    dl = f.std_lines()
    if dl:
        out["disease"] = dl
    out["any"] = bool(out.get("held") or out.get("kinsmen") or out.get("known")
                      or out.get("enslaved") or out.get("enslaved_former")
                      or out.get("carnal_opinions") or out.get("carnal_victim")
                      or out.get("harm") or out.get("disease") or f.hook_notable())
    return out


def build_facts(cache, melt, names_path=None, as_of=None, decade=None,
                nickname_override=None, cfg=None, campaign=None):
    """渲染干净事实集。melt 为 dict (已加载)。
    as_of (v11): 传记数据截止日期; 十年传记传十年末, 官职/历任/时间线/朝局按此截断。
    decade (v17): 十年传记序号 — 时间线/概览/摘要/刺客列传只收本十年
    (as_of−10年, as_of]; 终传/在世传 None 收全期。
    nickname_override (v20): {cid: 绰号} 按时代绰号覆盖 (十年传记重跑用)。
    cfg (v41): 配置 (开关类口径); 缺省读 config.json。
    campaign (v44): 同战役全部传主缓存 {player_id: cache} — 传主链亲缘/名号用。"""
    f = Facts(cache, melt, names_path, as_of=as_of, decade=decade,
              nickname_override=nickname_override, cfg=cfg, campaign=campaign)
    period = ""
    sources = cache.get("sources") or []
    if sources:
        period = f"{sources[0]} – {sources[-1]}"
    cpl, cpch = f.court_positions_lines()
    col, coch = f.court_office_lines()
    # v8: 死因中文化 (总纲【卒年】不再泄漏英文 key, 干净事实铁律)
    # v11: as_of 早于死期 (十年传记) 时视为在世, 不泄漏死亡信息
    # v76 (问题1): 让位 (reign_end) 优先, 且让位之后的死亡不进本篇
    # (用户 2026-09-27 拍板「让位即终了, 日后死亡只进缓存」)。
    re_end = cache.get("reign_end")
    if re_end and as_of \
            and cl.date_key(as_of) < cl.date_key(re_end.get("date") or "9999.9.9"):
        re_end = None
    pd = cache.get("player_death")
    if pd and re_end and cl.date_key(pd.get("date") or "0.0.0") \
            > cl.date_key(re_end.get("date") or "9999.9.9"):
        pd = None
    if pd and as_of and cl.date_key(as_of) < cl.date_key(pd.get("date") or "9999.9.9"):
        pd = None
    if pd:
        pd = dict(pd)
        pd["reason_zh"] = f.death_clause(
            cache.get("player_id"), date=pd.get("date"),
            reason=pd.get("reason"), killer=pd.get("killer"))
    if re_end:
        re_end = dict(re_end)
        re_end["reason_zh"] = f.reign_end_clause(cache.get("player_id"), re_end)
        re_end["word_zh"] = f.reign_end_word(re_end)
    # v44 (问题1): 【家族】行同样按本篇截止日取家族沿革 (传主别立家族/改名后,
    # 共享前缀里的家族名不得停在首见值)
    _pid0 = cache.get("player_id")
    _pdn, _phn = f._house_names_at(_pid0, as_of) if _pid0 is not None else ("", "")
    # v73: 《历代记》的治所行与《传主档案》同一出口 (免得两处治所不一致)
    f._protagonist_cache = _protagonist(f)
    # v74 (问题1): 刀下之魂的**所在之位承继链** —— 顶层键, 供校验与《家室列传》
    # 承位句 (`Facts.seat_note`) 互证; 不单独渲染进任何板块 (用户拍板:
    # 「腾位置只针对《家室列传》」)。
    _killed_list = _killed_by_player(f)
    _seat_succ = []
    for _k in _killed_list:
        try:
            _kid = int(_k.get("id"))
        except (TypeError, ValueError):
            continue
        for _row in f.seat_succession(_kid):
            _seat_succ.append(dict(_row, victim=_kid))
    facts = {
        # v14: 宗族名 (东方名序的姓) + 家族/分家 (风味补充)
        "house": _dynasty_display(_pdn or cache.get("dynasty_name"),
                                  _phn or cache.get("house_name")),
        "house_branch": _house_branch(_pdn or cache.get("dynasty_name"),
                                      _phn or cache.get("house_name")),
        # v81 (问题1): 家族称法按文化/名序组装 (共享前缀【家族】行与名号句同源)
        "house_label": house_label(_pdn or cache.get("dynasty_name"),
                                   _phn or cache.get("house_name"),
                                   f.name_order(_pid0) if _pid0 is not None else None,
                                   ((f._culture_entry(_pid0, as_of) or {})
                                    .get("culture_template")
                                    if _pid0 is not None else None)),
        "player_name": cache.get("player_name"),
        "player_id": cache.get("player_id"),
        "period": period,
        "sources": sources,
        "protagonist": f._protagonist_cache,
        "timeline": _timeline(f),
        "characters": _character_profiles(f),
        # v45 (档 B): 行文本 -> [[cid, 称谓], …] —— 事件句/隐事句的行内出词登记
        # (与 f 同一对象, 后续构建器继续往里记)。板块期据此在确切位置插亲缘定语。
        "name_index": f.name_index,
        # v63 (行内定语基准): 行主语 (句子讲的是谁) 与「句面已写明关系」的对手方 ——
        # 与 f 同一对象。板块期给句中第三方人名出定语时按行主语算词; 落进快照后
        # `verify_fast` 的 [V63] 也能照原数据复算 (与 name_index 同源同键)。
        "line_owner": f.line_owner,
        "line_stated": f.line_stated,
        "realm": _realm_facts(f),
        "player_death": pd,
        # v76 (问题1): 在位终结但未死亡 (剃发退位/让位/去位) —— 与 player_death 同式,
        # 含渲染好的 `reason_zh`; 供养 `_is_final_bio_spec` 与共享前缀【传位】行。
        "reign_end": re_end,
        "last_date": cache.get("last_date"),
        "as_of": as_of,
        "decade": decade,
        # v5 新增
        "bio_style": f.bio_style(),
        "killed": _killed_list,
        # v74 (问题1): 每位刀下之魂所在之位的后续持有者链 (走到第一位不是主角所杀者
        # 为止; 同日多人相继一并收入)。见 `Facts.seat_succession`。
        "seat_succession": _seat_succ,
        # v53 (问题4): 诛灭世族族级摘要 (刺客列传开篇/纪事共用)
        "family_purges": f.family_purge_summaries(cache.get("player_id")),
        "wandering": _wandering_trail(f),
        # v28: 隐事 (主角/家人近臣的隐事、知情情形、把柄) — 《阴私录》数据源
        "secrets": _secrets_facts(f),
        # v29: 瘟疫风味 (游戏动态疫名 + 感染范围; 只收触及主角封地/家人的疫情)
        "plagues": _plague_facts(f),
        # v20 (B3): 主角身份/驻地变化年表 (共享前缀【主角处境】数据源)
        "protagonist_stations": _protagonist_stations(f),
        # v64 (问题1): 游牧时期的大帐位置轨迹 (共享前缀【游牧行踪】数据源) ——
        # 毡帐不占历任相位, 故「大帐在哪」需要独立一块 (与【冒险者行踪】同式)
        "nomad_stations": _nomad_stations(f),
        "luminaries": _court_luminaries(f),
        "genealogy": _genealogy(f),
        # v7 新增: 宫廷/营地官职 + 家族家训
        "court_positions": cpl,
        "court_position_changes": cpch,
        # v36 (问题2, 用户拍板3): 主角获授的朝廷职位 (进《朝局风云录》升沉段)
        "court_office": col,
        "court_office_changes": coch,
        "house_motto": f.motto(),
        # v9: 家族恩怨录 / 宝物志 数据源
        "house_feuds": f.house_feuds(),
        "family_artifacts": f.family_artifacts(),
        # v44 (问题2): 传主链 (前任/后任传主) — 共享前缀与传主档案之外的出口,
        # 供 biography 在《本纪》开篇点出「怎么接上的」
        "succession": f.succession_lines(),
        # ---- v86: 礼仪志 / 教会志 素材 (CK3 1.20 新宗教系统) ----
        # 全部由 Facts 侧渲染成中文事实句; 无料时为空 (biography 按门槛整篇/整块省略)。
        "rite": f.rite_name(cache.get("player_id"), as_of),
        "rite_profile": f.rite_profile_lines(cache.get("player_id"), as_of),
        "rite_history": f.rite_history_lines(cache.get("player_id"), as_of),
        "personal_tenets": f.personal_tenet_lines(cache.get("player_id"), as_of),
        "spiritual_fulfillment": (
            f"灵性满足：{_sf_word(f._spiritual_fulfillment(cache.get('player_id'), as_of))}。"
            if f._spiritual_fulfillment(cache.get("player_id"), as_of) is not None else ""),
        "holy_sites": f.holy_site_lines(cache.get("player_id"), as_of),
        "church_state": f.church_state_lines(),
        # v13: Facts 实例引用 (biography 的关系缘由渲染等需要实例方法)
        "_facts": f,
    }
    # v14/v24: 十年戏剧主题 (Top5, 并列第5名全保留) — 模块切片与总纲预告用
    facts["decade_modules"] = decade_module_top(facts.get("timeline") or [],
                                                facts.get("protagonist") or {})
    # v15/v34: 大奸大恶关系链 (程序直算) — 句并入主角【戏剧性事件】。
    # v34 (问题1, 用户拍板「不留」): 分两档 —
    #   `dramatic_facts`        非揭底链 (暗杀/血亲之刃/奸夫谋夫) — 公开档案可见;
    #   `dramatic_facts_private` 揭底链   (托卵承嗣/血脉登基) — 只在《家室列传》
    #                            《阴私录》下发, 公开篇目 (本纪等) 看不到「实父」。
    vc = _villain_chains(f)
    # v41 (问题4): 同父异母联姻连线 (主角子女 × 主角非婚生子女) — 只进内宅档
    vc = list(vc) + _kin_blood_links(f)
    facts["villain_chains"] = vc
    if vc:
        dfa = facts["protagonist"].setdefault("dramatic_facts", [])
        dfp = facts["protagonist"].setdefault("dramatic_facts_private", [])
        for _m, s, _priv in vc:
            bucket = dfp if _priv else dfa
            if s not in bucket:
                bucket.append(s)
        dm = facts.get("decade_modules") or []
        for _m, _s, _priv in vc:
            if not any(x[0] == _m for x in dm):
                dm.append((_m, 3))
        # v24: 专题模块并入后再统一收口到 Top5 (此前并入后不再截断, 主题可 >10)
        facts["decade_modules"] = _cut_module_top(dm, top_n=5)
    stats = getattr(f, "_timeline_stats", None) or {}
    if stats:
        # 取计数前 6 的标签, 按计数降序; 供【概览】块渲染「本十年结怨9次…」
        # v81 (问题5, 用户 2026-09-29): 只取**正数** —— 「囚禁他人0次」是程序内部
        # 占位键 (`stats["囚禁他人"]` 无条件置 0) 漏出来的, 零次的事不入概览。
        top = [(k, v) for k, v in sorted(stats.items(), key=lambda kv: -kv[1])
               if v > 0][:6]
        facts["decade_stats"] = [f"{k}{v}次" for k, v in top]
    # 妻族传 (仅限公主头衔/中华皇帝之女·姐妹)
    pid = cache.get("player_id")
    if pid is not None:
        rec = (cache.get("characters") or {}).get(str(pid)) or {}
        # v60 (问题3): 配偶集先并入婚配闩存 —— 与 `_protagonist_facts` 同源
        fam = f.merge_spouse_latch(rec.get("family") or {}, f.as_of)
        rec["family"] = fam
        spouse_ids = list(dict.fromkeys(
            (fam.get("primary_spouse") or []) + (fam.get("spouse") or [])
            + (fam.get("former_spouses") or [])))
        # v76 (问题2, 用户拍板④「全部篇目都裁」): 妻族传与情事脉络同用窗口内配偶集
        spouse_ids = f.spouses_in_window(spouse_ids)
        facts["imperial_spouses"] = _imperial_daughters_sisters(f, spouse_ids)
        # v31 (问题4): 妻室情事脉络 (逐情人: 身份 + 私通→相恋→灵魂伴侣的关系弧)
        facts["consort_affairs"] = f.consort_affairs(pid, spouses=spouse_ids)
        # v32 (问题1): 强纳为妾 (存档唯一带确切日期的纳妾记录)
        facts["forced_concubines"] = f.forced_concubine_lines()
        # v60 (问题3): 妾的原有婚配被离断 (原配方留
        # `forced_spouse_concubine_marriage_opinion`)
        facts["concubine_divorces"] = f.concubine_divorce_lines()
    else:
        facts["imperial_spouses"] = []
        facts["consort_affairs"] = []
        facts["forced_concubines"] = []
        facts["concubine_divorces"] = []
    # v63 (问题2, 用户拍板): 《家室列传》纪事按「配偶一（＋其所出子女）→ 配偶二（＋…）」
    # 逐组下发, 每组一个独立请求 (上限见 JIASHI_GROUP_MAX)。
    facts["household_groups"] = household_groups(f, facts)
    return facts


# ---------------------------------------------------------------------------
# v63 (问题2): 《家室列传》的**门庭分组** —— 一组 = 一位配偶 + 其所出子女
# ---------------------------------------------------------------------------
# 用户口径 (2026-09-24): 「按照主角的配偶一，怎么怎么样，有儿子谁谁谁，做了什么；
# 然后配偶二又怎么怎么样这么来分」——即纪事不再是一篇大散文, 而是逐配偶成篇,
# 每位配偶带出她/他所生的子女。
#
# v74 (问题1, 用户 2026-09-27 拍板): 同上再改两处 ——
#   ① 纪事板块总数恒为 `JIASHI_MID_MAX` = 5 (连开篇共 6 篇), 但**在「妻妾池」与
#      「子女池」之间按素材权重分配**: 后代内容多则子女节多, 妻妾内容多则妻妾节多;
#   ② **有事迹的子女各自成节** (《诸子行迹》), 无事迹的婴幼儿随其生母入妻妾节。
#      旧稿把 19 名子女一律挂在生母名下, 于是「长子受任加贺国司 / 次子受任胆泽国司 /
#      三子尚了天皇」全被埋进妻妾的奔丧流水 (田所档实测: 《家室列传》12,389 字里
#      11 名子女合占 2,358 字)。
# 为什么这么做 (实测): 旧稿把 26 名家人 (12 配偶 + 14 子女同胞) 的整档一次性下发,
# `jiashi_mid` 的家室档案实测 **11,895 字符**, 而正文只要求 1200–1800 字 ——
# 平均每人 60–90 字, 模型只能平铺报名字。分组后每组 2–5 人, 素材与篇幅匹配。
JIASHI_MID_MAX = 5
JIASHI_GROUP_MAX = JIASHI_MID_MAX      # v74: 旧名保留 (文档/脚本引用)


def _jiashi_member_weight(facts, cid):
    """门庭成员的**素材权重** (v74 问题1): 事件条数 + 事迹加权。

    事迹 = 头衔/历任(3) + 婚配(2) + 子嗣(2) + 承位句(3)。用于在妻妾池与子女池之间
    分配纪事板块名额 (「后代内容多则给成年子女权重高」)。纯函数, 只读 facts。"""
    p = (facts.get("characters") or {}).get(str(cid)) or {}
    n = len(p.get("events") or [])
    if p.get("titles_held"):
        n += 3
    if p.get("spouses"):
        n += 2
    if p.get("children"):
        n += 2
    if p.get("seat_note"):
        n += 3
    return n


def _jiashi_notable(facts, cid):
    """该子女是否**有地** (持有领地/头衔) — 有地者才各自成节 (v76 用户拍板③)。

    旧口径 (v74) 是「有事迹」: 头衔/婚配/子嗣/承位**任一**即各自成节。用户 2026-09-27
    改口为「**子女: 有地的才单独列一篇**」—— 只有持有领地/头衔者才配一节
    (含家族庄园头衔: `titles_held` 里「受任儿玉家族女士，武家庄园」这类),
    仅以婚配/子嗣/承位见载者并入末个子女节 (《其余子女》)。
    判据 = `titles_held` (历任行; 由 `_character_profiles` 按头衔史渲染, 无头衔者为空),
    与 `_jiashi_member_weight` 的 +3 同一字段 (口径同源)。"""
    p = (facts.get("characters") or {}).get(str(cid)) or {}
    return bool(p.get("titles_held"))


def _balance_segments(seq, weights, k):
    """把序列切成 k 段 (保持次序), 使**各段权重之和的最大值最小** (DP, v74)。

    用于妻妾节: 「配偶一…配偶N」的次序不变, 但每节携带的素材尽量均衡
    (田所档 6 位妻室、2 个妻妾节 → 珍子+伊子+诸子 / 平子+真子+徽子)。"""
    seq, weights = list(seq), list(weights)
    n = len(seq)
    if k <= 1 or n <= k:
        return [[x] for x in seq][:n] if n <= k else [seq]
    # pref[i] = 前 i 项权重和
    pref = [0]
    for w in weights:
        pref.append(pref[-1] + w)
    INF = float("inf")
    # dp[i][j] = 前 i 项切 j 段的最小「最大段和」
    dp = [[INF] * (k + 1) for _ in range(n + 1)]
    cut = [[0] * (k + 1) for _ in range(n + 1)]
    dp[0][0] = 0
    for j in range(1, k + 1):
        for i in range(1, n + 1):
            for p in range(j - 1, i):
                if dp[p][j - 1] == INF:
                    continue
                seg = pref[i] - pref[p]
                v = max(dp[p][j - 1], seg)
                if v < dp[i][j]:
                    dp[i][j] = v
                    cut[i][j] = p
    segs, i, j = [], n, k
    while j > 0:
        p = cut[i][j]
        segs.append(seq[p:i])
        i, j = p, j - 1
    segs.reverse()
    return [s for s in segs if s]


def household_groups(f, facts):
    """门庭分组 (v63 问题2 起; v74 问题1 改造) → [{"label", "ids", "children",
    "kind": "spouse"|"child"|"sib", "mates": […], "n_mates": n}, …]。

    规则 (全部程序判定):
      · 纪事板块总数 = `JIASHI_MID_MAX` (5), 按**素材权重**在妻妾池/子女池之间分配:
        妻妾池 S = Σ 配偶权重, 子女池 K = Σ 子女权重, n_kid = round(5·K/(K+S)),
        两池各保底 1 节 (池空则该池 0 节), n_kid 上限 4;
      · **有地**的子女 (持有领地/头衔, 见 `_jiashi_notable`; v76 用户拍板③) 按权重降序
        **各自成节** (《诸子行迹·<子名>》), 名额用尽后其余子女并入末个子女节 (「其余子女」);
      · 无地 (无头衔) 的子女随其**生母**入妻妾节; 妻妾按 as_of 前首见次序切 n_wife 段
        (素材均衡, 次序不变 —— 与开篇「结缡」次序一致);
      · v76 (问题2, 用户拍板④): 妻妾池先按**本篇窗口**裁掉窗口内已非妻妾者
        (`f.spouses_in_window`) —— 十年档不再给早已卒/离的妇人留节;
        生母被裁掉的无事迹子女落到末尾「其余子女」节 (子女一律不裁);
      · 生母不在配偶集 (情妇已出册, 或 v76 被窗口裁掉) 的无地子女 → 并入末个子女节;
      · 主角的同胞 (`siblings`) 单列一节 (无妻妾则并入子女末节);
      · 每位成员的 id 只出现一次; 空组不产出。"""
    cache = f.cache
    pid = cache.get("player_id")
    if pid is None:
        return []
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    fam = f.merge_spouse_latch(rec.get("family") or {}, f.as_of)
    chars = cache.get("characters") or {}

    def _ids(key):
        return [int(x) for x in (fam.get(key) or [])
                if isinstance(x, int) or str(x).isdigit()]

    # 配偶次序: 正妻/正夫 → 其余现配偶 → 前配偶 → 妾 → 前妾 (去重保序)
    spouses = []
    for key in ("primary_spouse", "spouse", "former_spouses",
                "concubine", "former_concubines"):
        for x in _ids(key):
            if x not in spouses:
                spouses.append(x)
    # 只保留下发给模型的成员 (数据不足的略, 与 `_character_profiles` 同门)
    spouses = [x for x in spouses if str(x) in chars]
    # v76 (问题2): 窗口裁剪 —— 只留本篇窗口内仍在婚的妻妾 (终传=一生, 恒不裁)
    spouses = f.spouses_in_window(spouses)

    # 子女/同胞
    kids = [x for x in _ids("child") if str(x) in chars]
    sibs = [x for x in _ids("siblings") if str(x) in chars]

    # 子女 → 生母 (缓存 family.mother; 取不到则看父系)
    kid_mother = {}
    for c in kids:
        cf = (chars.get(str(c)) or {}).get("family") or {}
        m = [int(x) for x in (cf.get("mother") or [])
             if isinstance(x, int) or str(x).isdigit()]
        kid_mother[c] = m[0] if m else None

    wt = lambda c: _jiashi_member_weight(facts, c)          # noqa: E731
    notable = sorted((c for c in kids if _jiashi_notable(facts, c)),
                     key=lambda c: (-wt(c), str(c)))
    # v74: 名额分配 —— 妻妾池 vs 子女池
    slots = JIASHI_MID_MAX
    S = sum(wt(s) for s in spouses)
    K = sum(wt(c) for c in kids)
    if not kids:
        n_kid = 0
    elif not spouses:
        n_kid = slots
    else:
        share = (float(K) / (K + S)) if (K + S) else 0.0
        n_kid = max(1, min(int(round(slots * share)), slots - 1))
    n_wife = slots - n_kid if spouses else 0
    rest_sibs = [s for s in sibs if str(s) in chars and s not in kids]
    if rest_sibs and n_wife > 0:
        n_wife -= 1                     # 给「同胞手足」留一节
        n_kid = slots - n_wife

    used, out = set(), []
    # ① 妻妾节 (n_wife 段, 素材均衡, 次序不变) —— 各带本段妻妾的**无事迹**子女
    plain = [c for c in kids if c not in set(notable)]
    if n_wife > 0 and spouses:
        segs = _balance_segments(spouses, [wt(s) for s in spouses], n_wife)
        for si, seg in enumerate(segs):
            mem = [m for m in seg if m not in used]
            if not mem:
                continue
            kids_here = [c for c in plain
                         if kid_mother.get(c) in mem and c not in used]
            members = mem + kids_here
            used.update(members)
            names = [((facts["characters"].get(str(m)) or {}).get("name")
                      or f"配偶{m}") for m in mem]
            if len(names) == 1:
                label = names[0]
            elif si == len(segs) - 1 and len(segs) > 1:
                label = "其余妻室"
            else:
                label = f"{names[0]}等{len(names)}房"
            out.append({"label": label, "ids": members,
                        "names": names + [((facts["characters"].get(str(c)) or {})
                                           .get("name") or str(c))
                                          for c in kids_here],
                        "children": kids_here, "mates": mem,
                        "n_mates": len(mem), "kind": "spouse"})
    # ② 子女节 (《诸子行迹》): 有事迹者按权重降序各自成节, 名额用尽后并入末节
    kid_pool = [c for c in (notable + sorted(plain, key=lambda c: (-wt(c), str(c))))
                if c not in used]
    if n_kid > 0 and kid_pool:
        if n_kid == 1:
            chunks = [kid_pool]
        else:
            head = kid_pool[: n_kid - 1]
            tail = kid_pool[n_kid - 1:]
            chunks = [[c] for c in head] + ([tail] if tail else [])
        for chunk in chunks:
            mem = [c for c in chunk if c not in used]
            if not mem:
                continue
            used.update(mem)
            prof = facts["characters"].get(str(mem[0])) or {}
            if len(mem) == 1:
                label = prof.get("name") or f"子女{mem[0]}"
            else:
                label = "其余子女"
            out.append({"label": label, "ids": mem, "children": mem,
                        "names": [((facts["characters"].get(str(c)) or {})
                                   .get("name") or str(c)) for c in mem],
                        "mates": [], "n_mates": 0, "kind": "child"})
    # ③ 同胞手足
    rest_sibs = [s for s in rest_sibs if s not in used]
    if rest_sibs:
        if len(out) >= slots:           # 名额已满 → 并入末节
            out[-1]["ids"] = list(out[-1]["ids"]) + rest_sibs
            out[-1]["label"] = out[-1]["label"] + "与同胞"
        else:
            used.update(rest_sibs)
            out.append({"label": "同胞手足", "ids": rest_sibs, "children": [],
                        "mates": [], "n_mates": 0, "kind": "sib"})
    # 兜底: 仍有未落位者 (极端数据) → 并入末节
    left = [c for c in (kids + rest_sibs) if c not in used]
    if left:
        if out:
            out[-1]["ids"] = list(out[-1]["ids"]) + left
        else:
            out.append({"label": "其余门庭", "ids": left, "children": left,
                        "mates": [], "n_mates": 0, "kind": "child"})
    return out



def facts_to_text(facts, keys=None):
    """把事实集拼成给模型的纯文本 (调试/日志用)。"""
    lines = []
    p = facts["protagonist"]
    # v14: 家族名 + 分家 (自然语言, 无等号); v29b: 直连不用括注 (藤原氏 + 北家 → 藤原北家)
    fam = p.get("house") or ""
    if fam and p.get("house_branch"):
        b = p["house_branch"]
        fam = f"{fam[:-1]}{b}" if fam.endswith("氏") else f"{fam}，{b}"
    lines.append(f"主角：{p.get('name')}，{fam}")
    for k in ("birth", "culture", "faith", "traits", "government"):
        if p.get(k):
            lines.append(f"{k}：{p[k]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# v30 问题11: 事实层措辞表已迁至 style.py, 此处按原名别名, 调用点不变。
# 改词请编辑 style.py 的「8. 事实层措辞表」一节。
# ---------------------------------------------------------------------------
DEATH_REASON_ZH = _style.DEATH_REASON_ZH
FLAVOR_DEATH_ZH = _style.FLAVOR_DEATH_ZH
TITLE_GAIN_VERBS = _style.TITLE_GAIN_VERBS
TITLE_GAIN_CREATED_VERBS = _style.TITLE_GAIN_CREATED_VERBS
TITLE_LOSS_VERBS = _style.TITLE_LOSS_VERBS
# v36 (用户拍板4): 「他人授予」类缘由 — 这些缘由的头衔得失句补授予者
# (appointment/appointment_succession 天朝制任命轮转; granted 封建册封;
#  leased_out/negotiated/swear_fealty 让渡/议得/归附)。
_GRANTED_REASONS = ("appointment", "appointment_succession", "granted",
                    "leased_out", "negotiated", "swear_fealty")
# v41 (问题1/2): 头衔取得缘由三分 — 「夺得」(写明失主) / 「承袭自」(写明被承袭者)
# / 其余走 TITLE_GAIN_VERBS 的裸动词 (受任/受封/自立/受禅/议得…)。
# `TITLE_GAIN_VERBS` 里 revoked/usurped/conquest* 的动词都是夺取义, 一律补失主。
_TITLE_TAKE_REASONS = ("revoked", "usurped", "conquest", "conquest_claim",
                       "conquest_populist", "conquest_holy_war", "migration")
_TITLE_FROM_REASONS = ("inheritance",)
MEMORY_TEMPLATES = _style.MEMORY_TEMPLATES
SECRET_TOPICS = _style.SECRET_TOPICS
SECRET_TOPICS_NO_TARGET = _style.SECRET_TOPICS_NO_TARGET
SECRET_TOPICS_NO_FATHER = _style.SECRET_TOPICS_NO_FATHER
_DEATH_KILLER_VERB = _style.DEATH_KILLER_VERB
_DEATH_EXECUTOR_VERB = _style.DEATH_EXECUTOR_VERB
_DEATH_OPPONENT_VERB = _style.DEATH_OPPONENT_VERB
_DEATH_AGENT_TAIL = _style.DEATH_AGENT_TAIL
_EXECUTION_OPTIONS = _style.EXECUTION_OPTIONS
_EXECUTION_ORDER = _style.EXECUTION_ORDER
_STATS_LABEL = _style.STATS_LABEL
_DEATH_STAT_LABEL = _style.DEATH_STAT_LABEL
_TRAIT_GROUP_WORDS = _style.TRAIT_GROUP_WORDS
_FACT_WORDING = _style.FACT_WORDING
