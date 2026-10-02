# -*- coding: utf-8 -*-
"""杂志式人物传记生成器 (biography.py)
====================================
仿 <另一项目>\\magazine.py 的生成流程, 为 CK3 玩家角色写**五篇纪传体传记**:

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
import os
import re
from concurrent.futures import ThreadPoolExecutor

import llm
import cache_lib as cl
import facts as F
import style

# ---------------------------------------------------------------------------
# 提示词与措辞一律取自 style.py (v30 问题11: 文风单独剥离, 便于修改)
#   style.STYLE_PROFILES 两套笔法 / style.RULES 写作规则 /
#   style.SECTION_TITLES + style.SECTION_REQ 篇目板块 /
#   style.PROMPTS 请求包裹模板 / style.FACT_WORDING 事实层措辞
# ---------------------------------------------------------------------------

# 朝局类记忆类型 (朝局风云录用)
POLITICAL_TYPES = {
    "ascended_throne_memory", "lost_title_memory", "imprisoned",
    "released_from_prison_memory", "escaped_from_prison_memory",
    "became_rivals", "became_grudge",
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


def _is_dead(cache, cid, as_of=None):
    """该角色是否已死 (缓存有死亡记录)。
    v26: as_of 传入时, 卒于 as_of 之后者视为在世 (十年传记不把「后来才死的人」
    当已死 — 旧实现让在世优先失效, 田所 890 年仇人池全被判死)。"""
    d = ((cache.get("characters") or {}).get(str(cid), {}) or {}).get("death") or {}
    if not d:
        return False
    if as_of and d.get("date") and cl.date_key(d["date"]) > cl.date_key(as_of):
        return False
    return True


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


def _select_friend(cache, as_of=None):
    """好友: 与主角结友/灵魂伴侣/血盟者中, 在世优先 + 结友最早;
    排除家人 (妻妾/子女/兄弟姊妹 — 手足之情归家室列传)。
    全部已死时回退最早结友者; 无真好友返回 None (由 _pick_friend 走同朝共事者代打)。
    as_of (v16): 十年传记只认该日期前结下的友谊, 防止把后期好友写进早期十年。"""
    pid = cache.get("player_id")
    if pid is None:
        return None
    fam = _family_ids(cache)
    dates = {c: d for c, d in _relation_dates(cache, _friend_types()).items()
             if c not in fam}
    if as_of:
        dates = {c: d for c, d in dates.items()
                 if cl.date_key(d) <= cl.date_key(as_of)}
    if not dates:
        return None
    alive = {c: d for c, d in dates.items()
             if not _is_dead(cache, c, as_of=as_of)}
    pool = alive or dates  # 全部已死时回退最早结友者
    return min(pool, key=lambda c: cl.date_key(pool[c]))


def _select_fallback_friend(cache, as_of=None):
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
        if _is_dead(cache, cid, as_of=as_of):
            continue
        n = len((cache.get("characters") or {}).get(str(cid), {}).get("memories") or [])
        if n > best_score:
            best, best_score = cid, n
    return best


def _pick_friend(cache, as_of=None):
    """好友选择 (v13): 真好友 → 无则同朝共事者代打。返回 (cid, is_fallback)。"""
    f = _select_friend(cache, as_of=as_of)
    if f is not None:
        return f, False
    return _select_fallback_friend(cache, as_of=as_of), True


def _enemy_dates(cache):
    """{cid: 最早与主角结仇/结怨/死敌日期} (含死者, 双通道, 见 _relation_dates)。"""
    return _relation_dates(cache, _enemy_types())


def _select_enemies(cache):
    """所有与主角结仇/结怨/死敌的对手 id 集合。"""
    return set(_enemy_dates(cache))


ENEMY_MIN_DEEDS = 2  # v26: 仇人候选池事迹分门槛 (素材太少写不出列传)

# v41 (问题7): **与主角的互动分** — 仇人列传的传主应先看「与主角之间发生过什么」,
# 再看传主自己生平是否丰富。旧稿只数候选人自己的记忆 (_ENEMY_DEED_TYPES), 实测
# 选中希温托博尔·波美拉尼亚 (主角侧仅 4 条: 一次结仇 + 同场加冕两日 + 死讯),
# 其事迹分 36 全场第一, 靠的全是他自己的三任妻子/战争/生子; 而与他只结过一次仇,
# 与主角有囚禁/拷打/夺地之实的福尔科·埃斯特等人反被压下去。
# 权重分三档: 3 = 施加于对方或夺其所有 (战争/囚禁/拷打/谋杀/夺位/夺地/决裂);
# 2 = 受其施加或双方共同卷入 (被囚/被拷/获释/助战/战果/性事); 1 = 关系本身
# (结仇/结友/相恋/婚配/同场观礼/生育/亲属亡故)。
_SHARED_HISTORY_WEIGHTS = {
    3: ("successful_murder", "imprisoned_other", "torturer_memory",
        "offensive_war", "war_won", "defensive_war", "war_lost",
        "lost_title_memory", "ascended_throne_memory", "broke_up_lovers",
        "became_grudge", "became_nemesis", "faction_demand"),
    2: ("imprisoned", "tortured_memory", "released_from_prison_memory",
        "escaped_from_prison_memory", "joined_allys_war",
        "battle_won_memory", "battle_lost_memory", "stopped_being_friends",
        "stopped_being_rivals", "saved_from_assault_memory",
        "ignored_assault_memory"),
}
# 性事/强迫类记忆 (Carnalitas had_sex_* 与 had_sex) 一并计 2 分
_SHARED_HISTORY_SEX_WEIGHT = 2
# 其余「参与者含对方」的关系类记忆计 1 分 (became_rivals/became_friends/
# became_lovers/married/witnessed_a_coronation_memory/child_born/rival_died…)


def _shared_history_score(cache, cid, as_of=None, since=None):
    """候选人与主角的互动分 (v41, 问题7): 双向记忆里「参与者含对方」者加权计数。

    双向 = 主角侧记忆 (participants 含 cid) + 候选人侧记忆 (participants 含 pid),
    同一类型两者各计一次 (对等事件确实各留一条)。可按 as_of / since 截断。"""
    pid = cache.get("player_id")
    if pid is None or cid is None:
        return 0
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return 0
    if cid == pid:
        return 0
    w3 = set(_SHARED_HISTORY_WEIGHTS[3])
    w2 = set(_SHARED_HISTORY_WEIGHTS[2])
    chars = cache.get("characters") or {}
    ak = cl.date_key(as_of) if as_of else None
    sk = cl.date_key(since) if since else None
    score = 0
    for a, b in ((pid, cid), (cid, pid)):
        for m in (chars.get(str(a)) or {}).get("memories") or []:
            parts = m.get("participants") or {}
            if b not in [v for v in parts.values() if isinstance(v, int)]:
                continue
            d = m.get("creation_date")
            if d:
                dk = cl.date_key(d)
                if ak is not None and dk > ak:
                    continue
                if sk is not None and dk < sk:
                    continue
            t = str(m.get("type") or "")
            if t in w3:
                score += 3
            elif t in w2 or t == "had_sex" or t.startswith(F._SEX_MEM_PREFIX):
                score += _SHARED_HISTORY_SEX_WEIGHT
            else:
                score += 1
    return score

# v26: 仇人候选的「事迹分」类型集 — 主动作为型记忆计 1 分 (登位/战争/谋杀/婚配/
# 生育/结友/囚禁/受质/科考/朝觐/成人礼…); 丧亲/患病/失和等被动背景不计。
# 旧门槛只数记忆条数, 菅原类子 (12 条全是被动) 因而压过秦皇帝崔慎由。
_ENEMY_DEED_TYPES = {
    "ascended_throne_memory", "lost_title_memory", "successful_murder",
    "offensive_war", "defensive_war", "war_won", "war_lost",
    "joined_allys_war", "battle_won_memory", "battle_lost_memory",
    "married", "grand_wedding_completed_guest", "became_lovers",
    "child_born", "first_born", "twins_born", "became_friends",
    "became_soulmates", "became_blood_brother", "imprisoned_other",
    "hostage_created_hostage", "hostage_created_warden", "torturer_memory",
    "became_acclaimed", "witnessed_a_coronation_memory",
    "held_a_coronation_memory", "passed_provincial_exam_memory",
    "passed_metropolitan_exam_memory", "passed_palace_exam_memory",
    "completed_hajj_memory", "ward_education_completed",
    "completed_rites_of_passage", "completed_adult_education",
    "faith_changed",
}


def _enemy_deeds(cache, cid, as_of=None, since=None):
    """候选人事迹分 (v26): 只数 _ENEMY_DEED_TYPES 记忆, 可按 as_of/since 截断。"""
    rec = (cache.get("characters") or {}).get(str(cid)) or {}
    n = 0
    for mem in rec.get("memories") or []:
        if mem.get("type") not in _ENEMY_DEED_TYPES:
            continue
        d = mem.get("creation_date")
        if as_of and d and cl.date_key(d) > cl.date_key(as_of):
            continue
        if since and d and cl.date_key(d) < cl.date_key(since):
            continue
        n += 1
    return n


def _enemy_has_cause(facts, cid, rel_date):
    """候选仇人是否有**可用的结仇/死敌缘由** (v47, 用户拍板3)。

    缘由只有两个程序来源:
      ① 游戏 `opinions.active_opinions.scripted_relations.reason` 的本地化句
         (`facts.relation_reasons`);
      ② 直算因由 (`facts.relation_cause_lines`: 亲属被主角谋杀 / 配偶与主角
         私通 / 托卵承嗣)。
    两者皆无者**不进仇人池** —— 否则模型手里只有一个日期, 只能自造
    (诺兰档 赖因霍尔德 1126.12.4 一例: 缘由键随对方死亡被游戏清掉, 成稿里
    第 1 篇自编「起于粮道」、第 3 篇整篇《列传》写「史载极简」并穷举猜测;
    见 docs/研究_v47_结仇缘由缺失.md §3)。"""
    gi = facts.get("_facts") if isinstance(facts, dict) else None
    if gi is None:
        return True          # 无事实层 (旧快照/纯缓存调用) 时不设此门槛
    try:
        if gi.relation_reasons(int(cid), ("rival", "grudge", "nemesis")):
            return True
    except Exception:
        pass
    try:
        if rel_date and F.relation_cause_lines(gi, int(cid), rel_date):
            return True
    except Exception:
        pass
    return False


def _select_primary_enemy(cache, as_of=None, since=None, allow=None):
    """主仇人 (v11/v26): 与主角结仇/结怨/死敌的对手, 先按「与本篇相关」筛 —
    在世 (卒于 as_of 之后) 或 本十年内有作为 (since ≤ 事迹日 ≤ as_of); 再按
    总事迹分降序, 同分在世优先、结怨最早。
    v26: 原「记忆条数 >5 + 在世优先」让无事迹的在世路人胜出 (田所 890 年选中
    只有丧亲记忆的菅原类子, 而非结怨更早且六次登位的秦皇帝崔慎由)。
    v47: `allow(cid, rel_date)` 为可选硬门槛 —— 无因由者出池 (见
    `_enemy_has_cause`)。
    since 为十年传记窗口下界 (终传为 None)。"""
    dates = _enemy_dates(cache)
    if allow is not None:
        dates = {c: d for c, d in dates.items() if allow(c, d)}
    if as_of:
        dates = {c: d for c, d in dates.items()
                 if cl.date_key(d) <= cl.date_key(as_of)}
    if not dates:
        return None
    relevant = {c: d for c, d in dates.items()
                if not _is_dead(cache, c, as_of=as_of)
                or _enemy_deeds(cache, c, as_of=as_of, since=since) > 0}
    pool = relevant or dates
    rich = {c: d for c, d in pool.items()
            if _enemy_deeds(cache, c, as_of=as_of) >= ENEMY_MIN_DEEDS}
    pool = rich or pool

    # v41 (问题7, 用户拍板「软口径」): 先看**与主角的互动分**, 再看候选人自己的
    # 事迹分 (共享史为 0 者仍可凭事迹分入选 —— 不设硬门槛)。
    shared = {c: _shared_history_score(cache, c, as_of=as_of) for c in pool}
    shared_dec = {c: _shared_history_score(cache, c, as_of=as_of, since=since)
                  for c in pool}

    def _key(c):
        return (-shared.get(c, 0), -shared_dec.get(c, 0),
                -_enemy_deeds(cache, c, as_of=as_of),
                1 if _is_dead(cache, c, as_of=as_of) else 0,
                cl.date_key(pool[c]))

    return min(pool, key=_key)


def _enemy_for_facts(facts, cache):
    """仇人人选 — 文章标题与正文共用同一入口 (防标题/正文不一致)。
    十年传记传窗口下界 since, 终传/在世传记不传。
    v47: 加「无因由者出池」硬门槛 (用户拍板3, 见 `_enemy_has_cause`)。"""
    as_of = facts.get("as_of")
    since = None
    if as_of and facts.get("decade"):
        try:
            since = f"{int(str(as_of).split('.')[0]) - 10}.1.1"
        except Exception:
            since = None
    allow = None
    if facts.get("_facts") is not None:
        allow = lambda c, d: _enemy_has_cause(facts, c, d)   # noqa: E731
    return _select_primary_enemy(cache, as_of=as_of, since=since, allow=allow)


def _family_ids(cache):
    """主角家人 id 集 (妻室/前妻/子女/兄弟姊妹 — v13 加同胞: 手足归家室列传,
    不入好友列传)。
    v60 (问题3): 配偶一侧改用 `ever_spouses` (跨档闩存的全部婚配), 旧键在
    死亡档被游戏清空时不再导致家室列传无素材。"""
    pid = cache.get("player_id")
    if pid is None:
        return set()
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    fam = rec.get("family") or {}
    out = set()
    for key in ("primary_spouse", "spouse", "former_spouses", "ever_spouses",
                "concubine", "former_concubines", "child", "siblings"):
        for x in fam.get(key) or []:
            if isinstance(x, int):
                out.add(int(x))
    return out


def _sec_key(section):
    """板块 key (缺省视为开篇)。"""
    return (section or {}).get("key") or "lead"


def _murder_link_line(facts, key=None, section_key=None):
    """v27: 本纪/朝局纪事已按用户决策排除「谋害人命」模块 (该模块在终传里
    占 71/117 条, 且《刺客列传》整块承载), 由程序在**被排除的那个板块**补一行
    索引 —— 一行三十字换掉七十余条重复素材。剧本未生成《刺客列传》时不排除,
    本行也返回空。"""
    if key is not None and (key, section_key) not in F.MODULE_EXCLUDE:
        return ""
    if not _has_assassins(facts):
        return ""
    n = F.murder_module_count(facts.get("timeline") or [])
    if not n:
        return ""
    return f"另有谋杀{n}人，详见《刺客列传·刀下诸魂》。"


def _has_assassins(facts):
    """本剧是否会生成《刺客列传》(本统计周期内主角击杀 ≥1 人)。

    v52 (问题4, 用户拍板): 门槛由「>5」改为「≥1」—— 十年窗口内只杀一人的十年
    同样要为刀下之鬼立传 (斯卡利茨第 3 个十年 5 人, 旧口径整篇不生成)。"""
    return len(facts.get("killed") or []) >= 1


def _family_ids_by_kind(cache, kind):
    """家室二分 (v27): kind='spouse' 取妻妾 (含前妻前妾),
    kind='child' 取子女与同胞。
    v60 (问题3): 配偶一侧补 `ever_spouses` —— 与 `_family_ids` 同源。"""
    pid = cache.get("player_id")
    if pid is None:
        return set()
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    fam = rec.get("family") or {}
    keys = (("primary_spouse", "spouse", "former_spouses", "ever_spouses",
             "concubine", "former_concubines") if kind == "spouse"
            else ("child", "siblings"))
    return {int(x) for k in keys for x in (fam.get(k) or [])
            if isinstance(x, int) or str(x).isdigit()}


def _consort_affair_lines(facts, cache):
    """妻室情事脉络块 (v31, 问题4): 逐情人给**完整档案** + 关系弧一行。

    档案取 `_profile_lines` (姓名/族属/信仰/生年/廷中身份/为人/亲缘),
    关系弧取 facts.consort_affairs (私通→相恋→灵魂伴侣→分手/去世)。
    模块: 让「妻子怎么交到情人和灵魂伴侣」有脉络可写。"""
    entries = facts.get("consort_affairs") or []
    if not entries:
        return []
    grouped = {}
    for e in entries:
        grouped.setdefault(e.get("spouse_label") or "", []).append(e)
    out = []
    for slabel, items in grouped.items():
        # 块首用主语句 (v29b 口径: 不用「名词（名词）」式括注, 判据会判违规)
        out.append(f"{slabel}情事脉络：")
        for e in items:
            pid = e.get("partner")
            if pid is not None:
                for x in _profile_lines(facts, pid, with_real_parentage=True):
                    out.append("　" + x)
            arc = e.get("arc") or ""
            if arc:
                out.append(f"　与{slabel}之情：{arc}。")
        out.append("")
    while out and not out[-1]:
        out.pop()
    return out


def _split_span(items, part, total=2):
    """把有序列表按段数二分 (v27): 开篇取前半, 纪事取后半。"""
    n = len(items or [])
    if n == 0:
        return []
    if total <= 1:
        return list(items)
    cut = (n + total - 1) // total
    return list(items)[:cut] if part == 0 else list(items)[cut:]


# v27: 注意力锚点 (Lost in the Middle: 上下文利用呈 U 型, 首尾最好) —
# 从本板块切片里挑 4 条最该写出的日期, 放在消息尾部的要求之前。
_ANCHOR_MODULES = ("起家发迹", "失位让土", "开战兴兵", "战和胜负",
                   "囚禁入狱", "获释出狱", "拥戴加冕", "婚配联姻",
                   "丧偶之痛", "夭折", "谋害人命",
                   # v78-5 (用户 D6): 加冕索求/对抗 —— 宾客在加冕礼上的所得与冲突,
                   # 与「拥戴加冕」同层, 作注意力锚点
                   "加冕索求", "加冕对抗")


def _subject_events(facts, key, events, subject=None):
    """v52 (问题5): 《列传》的大事/年表只收**传主本人**参与的事件。

    旧稿按「与主角相关」取料, 于是主角救阿齐兹 (另一人) 的事件漏进《列传·阿金》
    的【本板块大事】与相关年表, 模型把两个阿拉伯名字合流, 写出「一箭射来…
    阿金由此逃过一劫」。判据: 句面出现传主姓名 (程序给出的称谓一律含姓名);
    传主姓名不可考时整块不收 (宁缺勿串味)。非《列传》篇原样返回。"""
    if key not in ("friend", "enemy") or subject is None:
        return events
    name = ((facts.get("characters") or {}).get(str(subject)) or {}).get("name") or ""
    if not name:
        return []
    return [e for e in events if name in (e.get("text") or "")]


def _key_events_block(facts, key, section, limit=4, subject=None):
    """【本板块大事】卡片 (v27): 本板块切片里含主角名或高戏剧模块的前 N 条,
    按日期升序排列, 置于消息尾部作取材锚点。无切片返回空串。
    v52 (问题5): 《列传》篇先按传主参与过滤 (见 `_subject_events`)。"""
    evs = F.slice_events(facts.get("timeline") or [], key, _sec_key(section),
                         exclude=_has_assassins(facts))
    evs = _subject_events(facts, key, evs, subject)
    if not evs:
        return ""
    pname = (facts.get("protagonist") or {}).get("name") or ""

    def rank(e):
        s = 0
        if pname and pname in (e.get("text") or ""):
            s -= 2
        if (e.get("module") or "") in _ANCHOR_MODULES:
            s -= 1
        return s

    picked = sorted(evs, key=rank)[:limit]
    picked.sort(key=lambda e: e.get("date") or "")
    return "【本板块大事】\n" + "\n".join(e["text"] for e in picked)


_LEAD_QUOTE_RE = re.compile(r"[「『“\"]([^」』”\"]{1,40})[」』”\"]")
_LEAD_LATIN_RE = re.compile(r"[A-Za-z]")
_LEAD_SENT_SPLIT_RE = re.compile(r"(?<=[。！？])")


def _sanitize_lead_digest(digest, facts_text=""):
    """开篇摘要净化 (v53 问题2): 引号内含拉丁字母、且该片段未出现在本请求事实文本
    中的句子整句去掉。幻觉专名 (如「添加IP」) 由此从纪事回灌材料里消失;
    事实里真有的拉丁专名保留。纯函数、幂等。"""
    t = (digest or "").strip()
    if not t:
        return t
    facts = facts_text or ""
    sents = [s for s in _LEAD_SENT_SPLIT_RE.split(t) if s]
    kept = []
    for s in sents:
        drop = False
        for m in _LEAD_QUOTE_RE.finditer(s):
            frag = (m.group(1) or "").strip()
            if not frag or not _LEAD_LATIN_RE.search(frag):
                continue
            if frag not in facts:
                drop = True
                break
        if not drop:
            kept.append(s)
    return "".join(kept).strip()


def _digest_head(t, limit):
    """开篇摘要前缀: 取**整句**直到超过 limit (首句即超限时仍给整句 —— 宁长勿断)。
    v80 点2: 旧稿 `t[:limit]` 是字符硬截, 摘要会把句子/词拦腰切开, 纪事请求拿到
    「…家业遂归妻子一身。妻……田所诚。…」这类碎文本, 模型为补缝写出「——中略——」
    「958年——」等幻觉 (田所定治 十年2 实测)。"""
    out = ""
    for s in _LEAD_SENT_SPLIT_RE.split(t or ""):
        if not s:
            continue
        if out and len(out) + len(s) > limit:
            break
        out += s
    return out.strip()


def _digest_tail(t, tail):
    """开篇摘要结尾: 自尾取**整句**直到超过 tail (末句即超限时仍给整句)。"""
    out = ""
    for s in reversed([s for s in _LEAD_SENT_SPLIT_RE.split(t or "") if s]):
        if out and len(out) + len(s) > tail:
            break
        out = s + out
    return out.strip()


def _lead_digest(text, limit=260, tail=180, facts_text=""):
    """开篇摘要 (v27, 移植 <另一项目> magazine.py:1746): 「前缀 + …… + 结尾」。
    中段不再回贴开篇全文 (实测每请求 1,000~1,800 字符); 保留结尾段,
    防「纯前缀截断切掉案件/事件的结局与主线事实」。
    v53 (问题2): 截取后再净化一次, 幻觉拉丁专名不进纪事请求。
    v80 点2: 前后两端一律**按句对齐** (见 `_digest_head` / `_digest_tail`) ——
    旧稿的字符硬截是「模型照着断句写」的根源。"""
    t = re.sub(r"[#*_>`~\-]", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    # 先净化再截取: 否则引号跨省略号被切开, 幻觉专名漏网。
    t = _sanitize_lead_digest(t, facts_text)
    if len(t) <= limit + tail:
        return t
    head = _digest_head(t, limit)
    tail_t = _digest_tail(t, tail)
    # 两端已覆盖全文 (或前缀恰好套住结尾) 时原样回贴, 不制造重叠与省略号
    if not head or not tail_t or len(head) + len(tail_t) + 3 >= len(t):
        return t
    return head + "……" + tail_t


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

def _feud_sentences(facts, cache, cid, reasons, rel_date):
    """v52 (问题5, 用户拍板): 游戏缘由句 → 带地点与收口的完整句。

    句式: 「在<地>，<游戏缘由句>，<仇家简称>由此与他结怨（<结怨日>）。」
      · 地点取缘由句里**先被点名**的一方当时的驻地 (`facts.station_place`; 只有本档
        玩家有逐档驻地轨迹), 无据则省去「在XX，」;
      · 收口补代词 (仇家与他 = 主角; 性别取缓存) 与结怨记忆日 (无则省括注)。
    无游戏缘由 (缘由只从记忆句来) 时返回 [] —— 调用方保持旧式记忆句。
    """
    gi = (facts or {}).get("_facts")
    pid = cache.get("player_id")
    if gi is None or pid is None or not reasons:
        return []
    plabels = [((cache.get("characters") or {}).get(str(pid)) or {}).get("name_full"),
               ((cache.get("characters") or {}).get(str(pid)) or {}).get("name_zh"),
               gi.person_label(pid, date=rel_date, style="brief"),
               gi.name_with_regnal(pid, rel_date) or "",
               (facts.get("protagonist") or {}).get("name") or ""]
    elabels = [((cache.get("characters") or {}).get(str(cid)) or {}).get("name_full"),
               ((cache.get("characters") or {}).get(str(cid)) or {}).get("name_zh"),
               gi.person_label(cid, date=rel_date, style="brief"),
               gi.name_with_regnal(cid, rel_date) or "",
               ((facts.get("characters") or {}).get(str(cid)) or {}).get("name") or ""]
    plabels = [x for x in plabels if x]
    elabels = [x for x in elabels if x]
    elabel = elabels[0] if elabels else ""
    if not elabel:
        return []
    pfemale = bool(((cache.get("characters") or {}).get(str(pid)) or {}).get("female"))
    date_z = gi.date(rel_date) if rel_date else ""

    def _pos(text, labels):
        best = None
        for lb in labels:
            i = text.find(lb)
            if i != -1 and (best is None or i < best):
                best = i
        return best

    out = []
    for s in reasons:
        body = (s or "").strip().rstrip("。")
        if not body:
            continue
        pp = _pos(body, plabels)
        ep = _pos(body, elabels)
        place = ""
        if pp is not None and (ep is None or pp <= ep):
            place = gi.station_place(pid, rel_date) or ""
        tail = f"{elabel}由此与{'她' if pfemale else '他'}结怨"
        if date_z:
            # v55 (问题2): 结怨日去括注, 作同句分句
            tail += f"，{date_z}"
        out.append(f"{'在' + place + '，' if place else ''}{body}，{tail}。")
    return out


def _house_text(facts, p=None):
    """家族文本: 事实层已按文化/名序组装好的家族称法 (v81)。

    v81 (问题1, 用户 2026-09-29): 组装移进 `facts.house_label` 单一出口 ——
    旧稿在此只用一条规则 (宗族名以「氏」结尾就直连分家名), 「藤原＋北家」成
    「藤原北家」而「平氏＋下北沢」成「平下北沢」。此处只做取值; 旧快照/旧缓存
    无 `house_label` 时退回旧拼法 (向后兼容)。"""
    p = p or {}
    lab = p.get("house_label") or (facts or {}).get("house_label") or ""
    if lab:
        return lab
    h = (facts or {}).get("house") or p.get("house") or ""
    b = (facts or {}).get("house_branch") or p.get("house_branch") or ""
    if h and b:
        if h.endswith("氏"):
            return f"{h[:-1]}{b}"
        return f"{h}，{b}"
    return h


def _num1(v, nd=1):
    """数值 → 一位小数短串 (去尾零), 与主角档案「国库金/月入」同口径 (v26)。"""
    try:
        return f"{float(v):.{nd}f}".rstrip("0").rstrip(".")
    except Exception:
        return ""


def _profile_lines(facts, cid=None, with_real_parentage=False,
                   with_private_chains=False, scope=None, with_death=True,
                   with_court=True):
    """主角或某角色的档案 → 自然语言行列表 (v15: 字段表格改散文, 程序直出不改写)。
    首行为名号句: 官职+姓名 + 家族分家/族属/信仰/出生/家训;
    后续每类事实一句, 缺失字段整句省略。cid=None 时用主角。

    v34 (问题1/5, 用户拍板「不留」): 两档披露 —
      · 公开档 (默认): 不写「实父X」, 只写游戏里的**法理谱系**; 主角的
        「戏剧性事件」只收非揭底链, 揭底链 (托卵承嗣/血脉登基) 改由
        `with_private_chains=True` 放行。
      · 内部档 (`with_real_parentage=True`): 放行「实父X」— 只给《家室列传》
        《阴私录》《妻族传》这些讲门庭内情的篇目。

    v41 (问题1): 名号句里的官职词按**本篇截止日**取 (`facts.as_of`), 不用缓存里的
    现职 —— 封建期的神罗封臣因此写「上洛塔林吉亚公爵」而非行政期的「将军」。

    v45 (档 A): `scope` = 本板块的亲缘定语登记表 (基准人 = 该篇传主)。给了 scope 时
    名号句改走 `kin_attrib_label` —— 该人若与传主有可判亲缘且是**本板块首见**,
    称谓前加定语 (「父亲冯·亚琛氏赫尔曼」)。scope 为 None 时逐字不变。

    v70 (用户 2026-09-27 拍板): `with_court=False` 时不出朝局明细 —— 封臣人数、
    御前会议席位、廷中僚属任职三样整句省略 (《XX历代记》篇专用: 该篇只写王朝历代,
    朝局数字是模型把「封臣226人，御前会议九席」写进正文的直接来源)。直辖地与治所
    保留 (它们是王朝疆域, 与「本朝疆域」行同源)。"""
    if cid is None:
        p = facts["protagonist"]
    else:
        p = (facts["characters"].get(str(cid)) or {})
    lines = []
    name = p.get("name") or p.get("name_zh") or ""
    # ---- 名号句 (官职前置: 瑞典国王崔佛·菲利普; 无官职直接用姓名) ----
    # v28b: 称谓统一 — head 用 facts 组好的 person_label; 旧缓存无 label 时回退旧拼法
    # v41: 按 as_of 重取一次 (缓存里的 label 用的是末档政体)
    _fi = facts.get("_facts")
    _anchor = facts.get("as_of")
    _tid = cid if cid is not None else facts.get("player_id")
    head = ""
    if _fi is not None and cid is not None:
        head = _fi.person_label(cid, date=_anchor, style="brief") or ""
    head = head or p.get("label") or name
    if not p.get("label"):
        if p.get("office"):
            head = f"{p['office']}{name}"
        elif p.get("prince"):
            head = f"{p['prince']}{name}"
    # v45 (档 A1): 亲缘定语只在名号句上出现一次 (名额表内判定)
    if scope is not None and _fi is not None and _tid is not None:
        _tagged = _fi.kin_attrib_label(_tid, date=_anchor, style="brief",
                                       scope=scope, base=head)
        if _tagged:
            head = _tagged
    # v45 (名额判据面): 本档案的家世行 (「父X」「子A、B」「妻室Y」) **已经写明**亲缘 ——
    # 这些人此后在本板块不再重复加定语 (用户拍板: 只有带亲缘词的提及才算已点名)。
    # 只在渲染的档案就是本板块传主时做 (家人档案的家世行讲的是他自己的亲属)。
    if scope is not None and _fi is not None and _tid is not None \
            and _tid == scope.subject:
        scope.seed(p.get("kin_ids"), _fi)
    bits = []
    h = _house_text(None, p)
    # v81 (问题1): 传主本人的名号句不再重复家族词 —— 同一请求的共享前缀已出
    # 【家族】行 (同源同一串); 为他人立传时 (cid 有值) 【家族】行讲的是主角,
    # 该人的家族词是新信息, 照旧保留。
    _dup_house = bool(cid is None and p.get("house_label"))
    # 家族/宗族: 分家存在或家族名不在显示名中才单列 (西方名·姓已含家族, 不重复)
    if h and not _dup_house and (p.get("house_branch") or h not in name):
        bits.append(h)
    if p.get("culture"):
        bits.append(p["culture"])
    if p.get("faith"):
        bits.append(f"信{p['faith']}")
    if p.get("birth"):
        bits.append(f"生于{p['birth']}")
    # v31 (问题6): 主角廷中身份 (骑士/廷臣 + 入宫日) — 妻室情人正是廷中骑士,
    # 旧档案里这一身份完全缺席 («乔乔何人…仅存其名» 即由此而来)
    if p.get("court_service"):
        bits.append(p["court_service"])
    if p.get("motto"):
        bits.append(f"家训「{p['motto']}」")
    # v92 (问题1, 用户 2026-10-02): 位分与血缘 (「本为X之外甥女，入侍为其妾」) ——
    # 该人为本篇传主所纳、而本人档案只有家世时, 由 facts.consort_of_line 直出。
    # 写在**名号句**里: 模型对「同族 + 同辈字」的名字极易判成同胞 (两轮成稿都把
    # 传主之甥女写成「传主之姐姐」), 故把这层关系放在最先读到的一行。
    if cid is not None and p.get("consort_rel"):
        bits.append(p["consort_rel"])
    lines.append(f"{head}，{'，'.join(bits)}。" if bits else f"{head}。")
    # ---- v41 (问题6): 共治者身份 (游戏 co_ruler 规则) ----
    # 单列一句: 「共治巴西琉斯，君主神圣罗马帝国巴西琉斯。」——
    # 与名号句同位 (放进 bits 会与族属/信仰句挤在一串逗号里)。
    if p.get("co_ruler"):
        lines.append(p["co_ruler"])
    # ---- v30: 族属变迁句 (问题1 — 「原为哥特人，871年起为诺斯人。」) ----
    if p.get("culture_history"):
        lines.append(p["culture_history"])
    # ---- v44 (问题1): 家格沿革句 (别立家族 / 家族改名) ----
    # 程序直出的完整句, 逐条单列 (「原属诺兰氏，1118年4月2日起别立冯·亚琛氏，…」)
    for ln in (p.get("house_history") or []):
        if ln:
            lines.append(ln)
    # ---- 传主链句 (前任/后任传主与继位日) ----
    for ln in (p.get("succession") or []):
        if not ln:
            continue
        # v57 (问题2a): with_death=False 时连「后任：948年10月6日，其子…继为传主」一并省去
        # —— 该句带着主角卒日, 与死亡句同属「主角卒年数据」, 而《刺客列传》篇用不上
        # (该篇主角恒居凶手位; 后任句见 facts.py 的 succession 生成)。
        if not with_death and str(ln).startswith("后任："):
            continue
        lines.append(ln)
    # ---- v27: 语言句 (母语/兼通) ----
    if p.get("language_line"):
        lines.append(p["language_line"])
    # ---- 性情句 (v31 问题1: facts 已按类别分句 — 「性情…；才具…」) ----
    if p.get("traits"):
        lines.append(f"为人：{p['traits']}。")
    if p.get("trait_history"):
        lines.append(f"特质履历：{p['trait_history']}。")
    # v26: 信仰履历 (改信过程) — 姓名句只写当前信仰, 改信节点在此补出
    if p.get("faith_history"):
        lines.append(f"信仰履历：{p['faith_history']}。")
    # v88 (问题3/P3-A-⑤, 用户 2026-10-01 拍板「把最新快照中的个人教义映射到每个人物
    # 档案中」): 个人教义逐人一行 —— 三段式 (始奉/放弃/改奉) 由 facts 侧程序组好
    # (`facts.personal_tenet_lines`), 有地统治者才带此数据, 无者整句省略。
    if p.get("personal_tenets"):
        lines.append(f"个人教义：{p['personal_tenets']}")
    # ---- 营/政体句 ----
    if p.get("landless"):
        camp_bits = []
        if p.get("camp_name"):
            camp_bits.append(f"营{p['camp_name']}")
        if p.get("camp_laws"):
            camp_bits.append(f"营规{p['camp_laws']}")
        if p.get("camp_strength"):
            camp_bits.append(f"营力{p['camp_strength']}")
        if p.get("camp_county"):
            loc = [f"现驻{p['camp_county']}"]
            if p.get("camp_county_holder"):
                loc.append(f"{p['camp_county_holder']}执掌")
            if p.get("camp_liege_chain"):
                loc.append(f"其上为{p['camp_liege_chain']}")
            if p.get("camp_top_liege"):
                loc.append(f"最高领主为{p['camp_top_liege']}")
            camp_bits.append("，".join(loc))
        if camp_bits:
            lines.append("，".join(camp_bits) + "。")
        elif p.get("government"):
            lines.append(f"以{p['government']}之身行事。")
    else:
        gov = ""
        if p.get("government"):
            gov = f"政体{p['government']}"
        if p.get("ruler_since"):
            gov = (gov + "，" if gov else "") + f"{p['ruler_since']}起执掌一方"
        if p.get("domain"):
            cap = f"，治所{p['capital']}" if p.get("capital") else ""
            gov = (gov + "，" if gov else "") + f"直辖{p.get('domain_count', '')}地：{p['domain']}{cap}"
        if p.get("vassal_count") is not None and with_court:
            gov = (gov + "，" if gov else "") + f"封臣{p['vassal_count']}人"
        # v26: 游牧牧群 (与金钱同口径: 当前值, 一位小数); 口粮非 0 时并写
        # v28: facts 侧已按 domicile 类型门控并去掉 0 值, 此处只做渲染
        # v29: 牧群数值不再下发; 口粮改档位词 (facts.provisions_band)
        if p.get("provisions_word"):
            gov = (gov + "，" if gov else "") + p["provisions_word"]
        if p.get("council") and with_court:
            gov = (gov + "，" if gov else "") + p["council"]
        if gov:
            lines.append(gov + "。")
        # ---- v28: 世族庄园身份 (中国世族/日本武家/家族地产) ----
        # 与「无地冒险者营地」分列: 营地是无地漂泊, 庄园是有家有业的世族根基
        # v41b (用户拍板2): 此句只在**无地/仅持庄园**时下发 (facts 侧判据:
        # 首要头衔为庄园本身) —— 有地领主的主线交给「政体/历任」。
        if p.get("estate_name"):
            # v29b: 持有者称谓改主语句 (「世族庄园「周家族」，主人称乡绅。」),
            # 不用「世族庄园「周家族」（乡绅）」式括注同位语
            # v36 (问题4): 庄园驻地州府一并写出 (庄园在宾州), 与「治所」两处并列
            _place = f"，庄园在{p['estate_place']}" if p.get("estate_place") else ""
            # v41b: 立族日 (晚于主角出生才立的家业写出年头 —— 「1094年5月28日立
            # 世族「诺兰家族」，主人称家主，庄园在亚琛。」)
            _since = f"{p['estate_since']}立" if p.get("estate_since") else ""
            if p.get("estate_holder"):
                lines.append(f"{_since}{p.get('estate_word') or '家族庄园'}"
                             f"「{p['estate_name']}」，主人称{p['estate_holder']}"
                             f"{_place}。")
            else:
                lines.append(f"{_since}{p.get('estate_word') or '家族庄园'}"
                             f"「{p['estate_name']}」{_place}。")
    # ---- 官职句 ----
    # v23: p.court_positions 是主角营/廷内**他人任职**花名册 (雇主=主角,
    # 任职者已在 facts 层按人聚合: 「仲宣任丑角（自…任），又任盗贼大师…」),
    # 标题按营/廷区分 — 弃用「宫廷官职」, 防止被读成主角自身官职履历
    # (郭氏 bug: 花名册被模型当主角 CV, 脑补出「历任之职/众人争相延揽」)。
    if p.get("court_positions") and with_court:
        if cid is None and p.get("landless"):
            lines.append(f"营中僚属任职：{p['court_positions']}。")
        elif cid is None:
            lines.append(f"廷中僚属任职：{p['court_positions']}。")
        else:
            lines.append(f"帐下僚属任职：{p['court_positions']}。")
    if p.get("court_position"):
        lines.append(f"在主角处任{p['court_position']}。")
    # v36 (问题2, 用户拍板3): 主角**自己获授**的朝廷职位 (太师等) — 只出现在传主档案
    # (cid is None 即主角本人), 主语是主角, 与上面的「僚属花名册」方向相反。
    if cid is None and p.get("court_office") and with_court:
        lines.append(f"朝廷职位：{p['court_office']}。")
    # ---- 家庭句 ----
    # v28: 配偶标签按**档案主体的性别**取 — 女性角色的丈夫此前被写成「妻室」
    # (陆氏家室列传: 妻「亮」的档案出现「妻室商州刺史陆荣廷」)。
    fem = bool(p.get("female"))
    spouse_lbl = "夫婿" if fem else "妻室"
    former_lbl = "前夫" if fem else "前妻"
    conc_lbl = "男宠" if fem else "妾"
    former_conc_lbl = "前男宠" if fem else "前妾"
    fam_bits = []
    if p.get("spouses"):
        fam_bits.append(f"{spouse_lbl}{p['spouses']}")
    if p.get("former_spouses"):
        fam_bits.append(f"{former_lbl}{p['former_spouses']}")
    if p.get("concubines"):
        fam_bits.append(f"{conc_lbl}{p['concubines']}")
    if p.get("former_concubines"):
        fam_bits.append(f"{former_conc_lbl}{p['former_concubines']}")
    # v26: 子女按性别分列 (子A、B，女C、D) — 无性别混排会让模型把女儿写成儿子
    if p.get("children_sons"):
        fam_bits.append(f"子{p['children_sons']}")
    if p.get("children_daughters"):
        fam_bits.append(f"女{p['children_daughters']}")
    if p.get("children") and not (p.get("children_sons")
                                  or p.get("children_daughters")):
        fam_bits.append(f"子女{p['children']}")
    if fam_bits:
        lines.append("，".join(fam_bits) + "。")
    # v34 (问题8, 用户拍板): 配偶与他人所出、本人不是其父/母的孩子 —
    # 不进「子/女」行, 单列一句, 供《家室列传》作「配偶的子女」交代
    # (《本纪》不收这条)。写成完整句, 不用括注同位语。
    # v44 (问题3): 措辞按**本人性别**取 —— 本人为女时这些孩子缺的是母亲。
    # v74 (问题3, 用户拍板): 句子改由 `facts.wife_other_children_line` **整句生成**
    # (按生父分人直陈、随生父之氏), 不再由本处拼「此数人之法理父并非主角」——
    # 该措辞把模型推向「丈夫是法理父」的错解 (见 docs/方案_v74_田所三问题.md §3.5)。
    if cid is None and p.get("wife_other_children") and with_real_parentage:
        lines.append(p["wife_other_children"])
    # ---- v27/v28: 言语关系句 (程序已判定相通或须通译, 模型照写) ----
    if p.get("language_relation"):
        lines.append(p["language_relation"])
    if p.get("language_relations"):
        lines.extend(p["language_relations"])
    elif p.get("language_bridge"):
        lines.append(p["language_bridge"])
    # ---- 家世句 ----
    kin_bits = []
    if p.get("father"):
        kin_bits.append(f"父{p['father']}")
    if p.get("mother"):
        kin_bits.append(f"母{p['mother']}")
    if with_real_parentage and p.get("real_father") \
            and p.get("real_father") != p.get("father"):
        kin_bits.append(f"实父{p['real_father']}")
    # v30: 自定义开局曾下发「先世资料未载」一行, 模型逐字照抄成满篇考据按语;
    # 现整行撤除 — 无父母谱系即无料, 无料不下发, 家世写法由《本纪》板块要求
    # 与 custom_note 的正向指引承担 (修复方案_菲利普4.md 问题4)。
    # v90 (问题4, 用户 2026-10-02 拍板): 逐人档案 (家室列传/列传) 不再列「兄弟姊妹」
    # —— 那一栏是与该节各人姓名逐字重复的一份名单 (各家室节的标题就是这些名字),
    # 在「此人是谁」已由名号句写明的档案里没有信息量。主角自己的档案 (cid 为 None,
    # 即各篇共享前缀里的【传主档案】) 仍保留一行 —— 那是他本人的家世, 别处不重复。
    if cid is None and p.get("siblings"):
        kin_bits.append(f"兄弟姊妹{p['siblings']}")
    if kin_bits:
        lines.append("，".join(kin_bits) + "。")
    # ---- v81 (问题6, 用户 2026-09-29): 生卒之地 (男爵领) ----
    # 与《刺客列传》的 victim_place 同一出口; 无料不写, 且 `with_death=False`
    # 的篇目 (《刺客列传》讲主角自己的卒年) 连卒地一并省去。
    # v90 (问题2, 用户 2026-10-02 拍板): 出词改「生于X」「死于X」—— 旧词「生地」
    # 「卒地」是史书档案体, 模型照抄进散文 (「地曰南海」「长安为其卒地」), 与
    # 名号句的「生于<日期>」同式后读来才是一句话。
    _bp = p.get("birth_place") or ""
    _dp = (p.get("death_place") or "") if with_death else ""
    # 死亡句在「凶手为主角」时已自带「，死于X」(见 facts._death_sentence_body),
    # 此处不再重述同一地名 (v81 实测本档 16 例重复)。
    if _dp and _dp in (p.get("death") or ""):
        _dp = ""
    if _bp or _dp:
        _place_bits = []
        if _bp:
            _place_bits.append(f"生于{_bp}")
        if _dp:
            _place_bits.append(f"死于{_dp}")
        lines.append("；".join(_place_bits) + "。")
    # ---- v74 (问题3 C4): 生母另有婚配时, 内宅档补一句「生母为X之妻。」 ----
    # 只讲生母的身份, 不讲孩子的来历 (公开私生不专门写); 独立成句以免与亲缘
    # 名单混读, 也不用括注 (项目铁律: 事实面无「名词（名词）」括注同位语)。
    if with_real_parentage and p.get("mother_note"):
        lines.append(p["mother_note"])
    # ---- v41 (问题5): 宗族宗支句 —— 分家与宗族不同名时点明同宗 ----
    # (「东盎格利亚为布里奥讷宗族的分支」; 初始家族与宗族同名, 不出句)
    if p.get("clan_line"):
        lines.append(p["clan_line"])
    # ---- v41 (问题1): 政体变更句 (改行行政官制等) ----
    if p.get("government_change"):
        lines.append(p["government_change"])
    # ---- 任历句 (v28b: 加冒号断句 — 原「历任867年任X」年月与「历任」粘连) ----
    if p.get("titles_held"):
        lines.append(f"历任：{p['titles_held']}。")
    # ---- v74 (问题1, 用户拍板「腾位置只针对《家室列传》」): 承位句 ----
    # 该角色现任头衔的前任里连续一串死于主角之手者 (「刀下亡魂是为了给我的孩子
    # 腾位置」)。只在**内宅档**下发, 不进《刺客列传》《本纪》等其他篇目。
    if with_real_parentage and p.get("seat_note"):
        lines.append(p["seat_note"])
    # ---- v53 (问题3): 天命局势一行 ----
    if p.get("dynastic_cycle"):
        lines.append(p["dynastic_cycle"] + "。")
    # ---- 现状句 (status 以「年X岁」开头时并入「现」字成散文句) ----
    if p.get("status"):
        st = p["status"]
        lines.append(("现" + st) if st.startswith("年") else f"现状：{st}")
    # ---- 死亡句 ----
    # v84: 死于旅途者, 「启程日 + 自X启程 + 赴Y 干什么 + (途中/返程途中)」已由
    # `facts.Facts.transit_death_clause` **并进这一句** (用户 2026-09-29 拍板:
    # 人都死了, 站数与预计到达不重要) —— 本处不再另出「远行」行。
    if p.get("death") and with_death:
        lines.append(p["death"])
    # ---- 戏剧性事件句 (v34: 揭底链只在内部档放行) ----
    df = list(p.get("dramatic_facts") or [])
    if with_private_chains:
        df += [x for x in (p.get("dramatic_facts_private") or []) if x not in df]
    if df:
        lines.append("戏剧性事件：" + "；".join(
            str(x).rstrip("。") for x in df) + "。")
    return lines


def _subject_facts(facts, cid, scope=None):
    """某角色(好友/仇人)的档案+事件 (公开档: 不写实父)。
    v45: 传 scope 时该档案的家世行据此预占本板块的亲缘名额 (KinScope.seed)。"""
    p = facts["characters"].get(str(cid)) or {}
    lines = _profile_lines(facts, cid, scope=scope)
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


# v78-7 (用户 D5): 年表类事实块的**自然段化**。
# 起因: 用户指出「一生大事」在战争频繁的一生里会变成流水账, 问「传输给模型的文本
# 能否自然段化, 以更好地将重点传递给模型」。旧稿 `_render_block` 把每条事实
# 各占一行、块内无分段 —— 80–150 条平铺时, 模型读到的是一张清单而不是若干事段。
# 口径 (只改**下发材料**的排版, 不改附录/成稿; 附录大事年表仍由 `_appendix_text`
# 程序渲染):
#   · 只处理年表类块 (下列六个);
#   · 「事件行」= 以「YYYY年」开头的行, 其余为**表头行** (家族：X氏 / 恩怨史： / 经历： …)
#     表头行独立成行, 不并入段落;
#   · 连续事件行按「≤4 条」且「相邻年份跨度 ≤5 年」聚成一段, 段内以「；」连缀
#     (日期保留在每句之首), 段与段之间空行;
#   · 逐行先过 `sanitize_fact_text` 再聚合 —— 否则一句含裸键会把整段带走。
_PARAGRAPH_BLOCKS = ("大事年表", "相关年表", "朝局动态", "传主行迹",
                     "本板块大事", "家族恩怨")
_PARA_MAX_LINES = 4
_PARA_MAX_YEAR_GAP = 5
_PARA_EVENT_RE = re.compile(r"^\s*(\d{3,4})年")


def _paragraphize_fact_lines(lines):
    """年表类块的行 → 自然段 (事件行聚段, 表头行独立)。返回行列表 (段间给空串)。"""
    out, buf, last_year, first = [], [], None, True
    _EV = _PARA_EVENT_RE

    def _flush():
        nonlocal buf, last_year
        if buf:
            if not first_flag[0]:
                out.append("")
            seg = []
            for ln in buf:
                t = ln.strip()
                seg.append(t.rstrip("。"))
            out.append("；".join(seg) + "。")
            first_flag[0] = False
        buf, last_year = [], None

    first_flag = [True]
    for ln in lines:
        m = _EV.match(ln or "")
        if not m:
            _flush()
            if (ln or "").strip():
                if not first_flag[0]:
                    out.append("")
                out.append((ln or "").rstrip())
                first_flag[0] = False
            continue
        y = int(m.group(1))
        if buf and (len(buf) >= _PARA_MAX_LINES
                    or (last_year is not None and abs(y - last_year) > _PARA_MAX_YEAR_GAP)):
            _flush()
        buf.append(ln)
        last_year = y
    _flush()
    return out


def _render_block(title, lines):
    """事实块 → 文本 (只收非空行)。
    v29: 出口处过一遍干净事实兜底 (丢含裸键的行并记审计)。
    v78-7: 年表类块按「事段」自然段化 (见 `_paragraphize_fact_lines`)。"""
    body = [x for x in lines if x]
    if not body:
        return ""
    if title in _PARAGRAPH_BLOCKS:
        safe = [F.sanitize_fact_text(x, where=title) for x in body]
        safe = [x for x in safe if x]
        if safe:
            return F.sanitize_fact_text(
                f"{title}\n" + "\n".join(_paragraphize_fact_lines(safe)),
                where=title)
    return F.sanitize_fact_text(f"{title}\n" + "\n".join(body), where=title)


def _set_block(blocks, key, text):
    """v28b: 只在该块确实有料时设键 — 空块不再写「（无X记录）」这类占位串
    (占位串会进提示词, 既费词元又容易被模型照抄进正文)。"""
    if text:
        blocks[key] = text


# v14: 刺客列传新口径 (用户定稿) — 死者名带官职 (「唐皇帝李漼」),
# 只传 亲缘 (父/母/妻/妾) + 婚恋记忆 (成婚/相恋/分手/丧偶), 其余生前经历
# (登位/战争/科考等) 从略 — 研究_戏剧模块化.md 7.3 实测: 46 死者 324 条记忆
# 婚恋类仅 30 条 (9%), 裁掉 294 条与「刀下之魂」叙事无关的杂事。
_MARRIAGE_TYPES = {
    "married", "grand_wedding_completed_guest", "broke_up_lovers",
    "became_lovers", "had_sex", "spouse_died", "divorced",
}
# v20 (B1): 死句中由 _death_sentence 嵌入的「（时主角驻X）」标注; v24 起改为
# 受害者所在地「（死于X）」，v55 起改分句「，死于X」。档案行里标注都改独立行呈现,
# 故先从死句剥离 —— 三种历史形态一并兼容 (旧缓存/旧快照仍可能带括注形态)。
_STATION_RE = re.compile(r"(?:（(?:时主角驻|死于)[^）]*）|，死于[^，。；]*)")


def _strip_station(s):
    return _STATION_RE.sub("", s or "")


def _kin_tag(facts, scope, cid, base, date=None):
    """v45 (档 A): 给称谓 base 加亲缘定语 (本板块首见才加; 缺 scope/cid 原样返回)。

    `base` 由调用方传入 —— 刺客死者的称谓按**卒日**取, 不能在这里重算成 as_of 版。"""
    if scope is None or cid is None or not base:
        return base
    fi = facts.get("_facts")
    if fi is None:
        return base
    return fi.kin_attrib_label(cid, date=date, style="brief", scope=scope,
                               base=base) or base


def _assassin_lead_line(k, facts=None, scope=None):
    """刺客列传开篇名录的一行: 「死者：称谓（渠州起事；死于…，被其烧死。）」。
    v30: 同组血亲并列一行 (问题7)。
    v37 (问题8): 起义领袖补起事州府 — 开篇是独立请求, 无地点则模型会就近安放。
    v45 (档 A3): 死者若是传主的亲属, 首见处加亲缘定语 (「死者：姻亲兄弟X（…）」)。"""
    nm = k.get("name") or ""
    off = k.get("office") or ""
    disp = k.get("label") or (f"{off}{nm}" if off else nm)
    disp = _kin_tag(facts, scope, k.get("id"), disp)
    db = k.get("death") or ""
    for _p in (disp, nm):
        if _p and db.startswith(_p + "死于"):
            db = "死于" + db[len(_p) + 2:]  # 去掉「称谓+死于」前缀
            break
    db = _strip_station(db)  # v20: 开篇压缩名录不带驻地标注
    base = (k.get("uprising") or {}).get("base") or ""
    if base:
        db = f"{base}起事；{db}" if db else f"{base}起事。"
    grp = list(k.get("group") or [])
    if grp:
        disps = [disp] + [g.get("label") or g.get("name") or "" for g in grp]
        disps = [d for d in disps if d]
        note = k.get("kin_note") or ""
        tail = "；".join(x for x in (note, db) if x)
        # v55 (问题2): 死者行去括注 —— 「死者：A、B，俱为X之子女；死于…」
        return f"死者：{'、'.join(disps)}，{tail}" if tail \
            else f"死者：{'、'.join(disps)}"
    return f"死者：{disp}，{db}" if db and not F.is_unknown(db) \
        else f"死者：{disp}"


def _assassin_kill_lines(facts, cache, k, scope=None):
    """一名死者 (或一组同日而死的血亲) 的档案行: 官职名 + 生卒 + 死句 + 亲缘 + 婚恋。
    返回 ['死者：唐皇帝李漼（死于878年4月9日，被其处决。）', …]。
    v16: 死者行带出生日期 — 防止同名/近名角色被误认 (里瓦朗 vs 里瓦尔:
    生于830年的萨洛蒙亲生子不可能被当成869年私通所出之子)。
    v24: 死因不详不再叠双层括号; 地点标注改受害者所在男爵领独立行。
    v27: 亲缘行改用头衔+姓名 (kin_label), 与家室列传同口径。
    v30: 血亲同组合为一行 (问题7); 凶手称谓由 facts 缩为「其」(问题8)。
    v45 (档 A3): 死者行首见处加亲缘定语 (与 facts 侧的「父X」「妻X」行分工:
    同一板块内该人已在别处点过名的不再加)。"""
    lines = []
    grp = list(k.get("group") or [])
    nm = k["name"]
    off = k.get("office") or ""
    # v28b: 死者称谓用 facts 组好的 label (官职/称号+名), 旧缓存回退 office+name
    disp = k.get("label") or (f"{off}{nm}" if off else nm)
    disp = _kin_tag(facts, scope, k.get("id"), disp)
    db = k.get("death") or ""
    for _p in (disp, nm):
        if db.startswith(_p + "死于"):
            db = "死于" + db[len(_p) + 2:]
            break
    db = _strip_station(db)  # v20/v24: 地点标注改独立行呈现
    if grp:
        # v30: 同组血亲并列一行 — 「死者：A、B、C（俱为X之子女；死于…，被其烧死。）」
        disps = [disp] + [g.get("label") or g.get("name") or "" for g in grp]
        disps = [d for d in disps if d]
        note = k.get("kin_note") or ""
        tail = "；".join(x for x in (note, db) if x)
        # v55 (问题2): 去括注, 同 _assassin_kill_line
        lines.append(f"死者：{'、'.join(disps)}，{tail}" if tail
                     else f"死者：{'、'.join(disps)}")
    elif db and not F.is_unknown(db):
        bd = k.get("birth") or ""
        head = f"，生于{bd}，" if bd else "，"
        lines.append(f"死者：{disp}{head}{db}")
    elif k.get("birth"):
        lines.append(f"死者：{disp}，生于{k.get('birth')}")
    else:
        lines.append(f"死者：{disp}")
    # v24: 受害者死前最近可知所在男爵领 — 击杀无案发地点, 以受害者位置为锚
    # 「某某死于X」(X 为男爵领名; 数据无则整行省略)
    for e in [k] + grp:
        vp = (e.get("victim_place") or "").strip()
        if vp:
            lines.append(f"{e.get('name') or ''}死于{vp}。")
    # v37 (问题8): 起义领袖的起事真地点 (起义头衔 capital → 州府) —
    # 独立行「丁文举起于渠州，聚众六州，反抗唐皇朝。」; 数据无则整行省略。
    # 此前事实层从不读它, 死者「无地可依」, 模型只能就近安放到主角家业所在
    # (旧稿「居慈州境内」/ 新稿「宾州人」)。
    for e in [k] + grp:
        ul = (e.get("uprising_line") or "").strip()
        if ul:
            lines.append(ul)
    # 亲缘: 父/母/妻/妾 (从缓存 family 取; v27 带前头衔/现头衔)
    # v30: 同组血亲只写**共同**父/母 (组内各人母亲可能不同 — 五位皇女各出其母,
    # 若照抄组首的母亲会写成「全组同母」), 配偶另按人名分列。
    def _fam_of(e):
        return ((cache.get("characters") or {}).get(str(e.get("id"))) or {}) \
            .get("family") or {}

    def _fids(e, key):
        out = set()
        for x in (_fam_of(e).get(key) or []):
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                continue
        return out

    # v63 (问题5): 亲缘行的取词与补注
    #   · 配偶位按**死者性别**取词 (旧稿写死「妻/前妻/妾」, 女性死者因此被写成
    #     「妻藤原范宗」—— 实测本篇 19 条亲缘行里 4 条如此);
    #   · 父/母附生年, 并补「子/女」位 —— 事实面自己把方向说明白, 相邻两条记录
    #     才不会被串成「其父藤原敬子时年三岁」。
    _fi = facts.get("_facts")

    def _gword(subject, other, kind):
        if _fi is not None:
            return _fi.kin_word_gendered(subject, other, kind)
        return {"spouse": "妻", "former": "前妻",
                "concubine": "妾", "f_concubine": "前妾"}.get(kind, "")

    def _byear(cid):
        """生年 (int|None) —— 缓存优先, 熔件兜底。"""
        rec = (cache.get("characters") or {}).get(str(cid)) or {}
        b = rec.get("birth")
        if not b and _fi is not None:
            b = (getattr(_fi, "_chars", {}) or {}).get(str(cid), {}).get("birth")
        try:
            return int(str(b).split(".")[0])
        except (TypeError, ValueError):
            return None

    def _with_year(cid, name):
        """父/母附生年 —— 用**行文**而非括注 (v63 问题5)。

        项目铁律 (v55 拍板) 是「事实层括注一律自然语言化」, 故生年写成
        「父X，787年生」这种并列短句, 不用 `（787年生）` —— 括注形态会被
        `verify_fast` 的「无「名词（名词）」括注同位语」判为违规。
        目的仍是消掉方向歧义: 生年摆在名号旁, 「父比子女晚出生」在事实面上
        就不可读错 (同类矛盾另有 `facts.audit_kin_lines` 兜底)。"""
        y = _byear(cid)
        return f"{name}，{y}年生" if y else name

    bits = []
    seen_bits = set()
    if grp:
        for key, label in (("father", "父"), ("mother", "母")):
            sets = [s for s in (_fids(e, key) for e in [k] + grp) if s]
            common = set.intersection(*sets) if sets else set()
            for x in sorted(common):
                bits.append(f"{label}{_with_year(x, _kin_or(facts, cache, x))}")
        for e in [k] + grp:
            _seen_sp = set()      # v70: 同一配偶只挂一个关系词 (见下单体分支注释)
            for key, kind in (("primary_spouse", "spouse"), ("spouse", "spouse"),
                              ("former_spouses", "former"),
                              ("concubine", "concubine")):
                for x in (_fam_of(e).get(key) or []):
                    try:
                        x = int(x)
                    except (TypeError, ValueError):
                        continue
                    if x in _seen_sp:
                        continue
                    _seen_sp.add(x)
                    b = f"{e.get('name')}之{_gword(e.get('id'), x, kind)}" \
                        f"{_kin_or(facts, cache, x)}"
                    if b not in seen_bits:
                        seen_bits.add(b)
                        bits.append(b)
    else:
        fam = _fam_of(k)
        for key, label in (("father", "父"), ("mother", "母")):
            for x in (fam.get(key) or []):
                try:
                    x = int(x)
                except (TypeError, ValueError):
                    continue
                bits.append(f"{label}{_with_year(x, _kin_or(facts, cache, x))}")
        _seen_sp = set()
        # v70 (用户 2026-09-27 拍板: 「姐姐姐姐一类的重复一起改掉」): 同一人只挂
        # 一个配偶关系词 —— 存档 `family_data.former_spouses` 会把现配偶一并列出
        # (实测 温映娘: 「夫瓯王愚者韩元佶、夫韦鲁、前夫韦鲁、前夫瓯王愚者韩元佶」
        # 前后两份互为倒序), 旧稿按整串去重 (b 串带关系词、不相等) 故两份都留下。
        # 取词优先序即循环序: 正妻/正夫 → 现配偶 → 前配偶 → 妾。
        for key, kind in (("primary_spouse", "spouse"), ("spouse", "spouse"),
                          ("former_spouses", "former"),
                          ("concubine", "concubine")):
            for x in (fam.get(key) or []):
                try:
                    x = int(x)
                except (TypeError, ValueError):
                    continue
                if x in _seen_sp:
                    continue
                _seen_sp.add(x)
                lbl = _gword(k.get("id"), x, kind)
                b = f"{lbl}{_kin_or(facts, cache, x)}"
                if b not in seen_bits:
                    seen_bits.add(b)
                    bits.append(b)
    # 子女 (v63 问题5): 与父/母同位并读 —— 「夫藤原范宗、女藤原敬子」使
    # 「敬子是丰子的女儿」在同一条记录内成立, 与下一条敬子的「父范宗、母丰子」互证。
    for e in [k] + grp:
        kids = _fids(e, "child")
        if not kids:
            continue
        if _fi is not None:
            try:
                kids = set(F._asof_ids(_fi, sorted(kids)))
            except Exception:
                pass
        for x in sorted(kids):
            kf = ((cache.get("characters") or {}).get(str(x)) or {}).get("female")
            lbl = "女" if kf else "子"
            b = f"{lbl}{_kin_or(facts, cache, x)}"
            if b not in seen_bits:
                seen_bits.add(b)
                bits.append(b)
    if bits:
        lines.append("亲缘：" + "、".join(bits))
    # 婚恋记忆: 只收婚恋类 (过滤 k["events"], 其文本带日期前缀)
    # v56 (§10): 按**记忆型**过滤 (`facts._killed_by_player` 下发的 `event_types`
    # 与 events 逐位对应) —— 旧稿按句面关键词匹配, 而相恋句改出游戏缘由句
    # (「…在地牢里相爱了」) 后「相恋」二字不再出现, 该行会整条从《刺客列传》消失。
    # `event_types` 缺失时 (旧快照) 回退关键词, 行为与旧稿一致。
    # v63 (问题3, 用户拍板): 性事族 (`had_sex_*`, 由 facts.is_sex_memory 判定) 一并
    # 收录 —— 用户明确「只需要补埃德伯的强奸记忆, 只有仇人/好友列传需要加」,
    # 刺客列传是唯一承载被主角杀死者生平的名录, 其婚恋行即该篇的性事出口。
    _MAR_TYPES = ("married", "became_lovers", "became_lovers_spouse",
                  "had_sex", "had_sex_spouse", "broke_up_lovers", "spouse_died")
    _MAR_WORDS = ("成婚", "相恋", "私情", "分手", "丧偶", "离婚", "强迫", "半推半就")
    mar = []
    for e in [k] + grp:
        ev = e.get("events") or []
        et = e.get("event_types") or []
        for i, x in enumerate(ev):
            if i < len(et):
                if et[i] in _MAR_TYPES or F.is_sex_memory(et[i]):
                    mar.append(x)
            elif any(m in x for m in _MAR_WORDS):
                mar.append(x)
    # v63 (问题5): 逐人最多 3 条 —— 同簇 19 人 × 各自婚恋履历会挤满名录; 取最近 3 条
    if len(mar) > 3:
        mar = mar[-3:]
    if mar:
        lines.append("婚恋与强迫之事：" if any(
            ("强迫" in x or "半推半就" in x) for x in mar) else "婚恋：")
        lines.extend("  " + e for e in mar)
    return lines


def _kin_or(facts, cache, cid):
    """亲属称谓 (v27): 优先 Facts.kin_label (前头衔/现头衔+姓名),
    数据缺失时回退统一显示名链。"""
    try:
        fi = facts.get("_facts")
        if fi is not None:
            nm = fi.kin_label(cid)
            if nm:
                return nm
    except Exception:
        pass
    return _name_or(facts, cache, cid)


def _name_or(facts, cache, cid):
    """角色名 (v19: 档案有则用; 否则走 Facts 统一显示名链 name_with_regnal —
    与档案名同源, 自动带宗族姓/名·姓/绰号/世系, 内部已含 缓存→names→熔件
    全套兜底; 缓存 name_zh 只是纯名 (不含姓), 只作 _facts 缺失时的保守兜底,
    否则有宗族的亲属 (父膺廉→金膺廉/妻师娘→周师娘) 会被纯名短路丢姓)。"""
    try:
        p = (facts.get("characters") or {}).get(str(cid)) or {}
        if p.get("name"):
            return p["name"]
    except Exception:
        pass
    # v19: 统一显示名链 (带姓) — 提到缓存纯名之前
    try:
        fi = facts.get("_facts")
        if fi is not None:
            nm = fi.name_with_regnal(cid)
            if nm:
                return nm
    except Exception:
        pass
    try:
        r = ((cache.get("characters") or {}).get(str(cid)) or {})
        nm = r.get("name_full") or r.get("name_zh") or ""
        if nm:
            return nm
    except Exception:
        pass
    return "某人"


# ---- v45 (档 B): 行内亲缘定语 ----
# 行内「已写明亲缘」的标记 (只收**不会与头衔撞车**的多字词): 记忆句/死句里
# 亲属由 `Facts._kin_word` 出「其父」「其兄」式旁称, 家世行出「妻室」「子」式标记。
# 单字「子/女/父/母」故意不收 —— 头衔里的「皇子」「国皇女」「王子」会把它们撞上。
_KIN_MARKS = (
    "其父", "其母", "其子", "其女", "其兄", "其弟", "其姊", "其妹", "其妻",
    "其夫", "其配偶", "其岳父", "其女婿", "其儿媳", "其姻亲兄弟", "其姻亲姊妹",
    "其继子", "其继女", "妻室", "夫婿", "男宠", "前妻", "前夫", "前妾",
    "前男宠", "子女", "实父", "兄弟姊妹", "岳父", "女婿", "儿媳",
    "姻亲兄弟", "姻亲姊妹", "继子", "继女",
)
# v58 (问题8): 事实层的亡故句现在直接把关系写在句面上（「X的父亲Y去世」），
# 故把亲缘词表里的**多字词**一并算作「已写明关系」，板块期不再插第二次定语
# （单字词 父/子/兄… 故意不收 —— 头衔里的「皇子」「国皇女」会撞上）。
_KIN_MARKS = tuple(sorted(set(_KIN_MARKS) | {w for w in F.kin_texts() if len(w) >= 2},
                          key=len, reverse=True))
# v58 (问题8): 亡故句的**通用/非血亲**关系词也一并算「已写明关系」——
# 旧稿「的亲属X去世」会被再插一次定语，写成「的亲属公公X去世」。
# v63: 补「生父」—— 生育句的「添子X，生父Y。」已写明 Y 与句子的关系。
_KIN_MARKS = tuple(sorted(set(_KIN_MARKS) | {"亲属", "仇人", "友人", "情人",
                                             "灵魂伴侣", "挚友", "死敌", "生父"},
                          key=len, reverse=True))
_KIN_MARK_RE = re.compile("|".join(_KIN_MARKS))


def _names_for_line(facts, line):
    """取该行 facts 侧登记的 (cid, 称谓) 表 + 行内偏移量 (v45 档 B)。

    索引键是**句本体**; 下发时可能被套上「日期，」前缀 (隐事/恩怨/家人行迹),
    故精确命中失败时, 只在标点之后试几段后缀 (最多 24 字)。
    v63: 第三个返回值 = 命中的**句本体** —— 据它查本行主语 (facts 里的
    `line_owner` / `line_stated`, 与 `name_index` 同源同键)。"""
    idx = facts.get("name_index") or {}
    hit = idx.get(line)
    if hit is not None:
        return hit, 0, line
    for i in range(len(line) - 1):
        if i >= 24:
            break
        if line[i] in "，；。、 ":
            hit = idx.get(line[i + 1:])
            if hit is not None:
                return hit, i + 1, line[i + 1:]
    return None, 0, None


def _kin_tag_line(facts, scope, line):
    """v45 (档 B): 行内**首见**人名前加亲缘定语 (无名额/无亲缘/已写明者原样返回)。

    v63 (行内定语基准): 句子有自己的主语时 (家人档案/刺客列传的逐人条目、隐事
    持有人的隐事句 —— facts 侧登记为 `facts["line_owner"]`), 句中**第三方**人名
    (不是本行主语的那个) 的定语按**本行主语**算词。旧稿一律按本篇传主算词, 于是
    「于尔莎受业于西福尔酋长乱发哈拉尔」被插成「受业于**岳父**乱发哈拉尔」——
    乱发哈拉尔是传主的岳父, 却是于尔莎的**生父**, 一句之内与同行家世行「父X」
    相抵, 模型只好写「谱系交错，史家当另作考辨」。本行主语自己的人名仍按传主
    算词 (年表旁称「姻亲姊妹X」即此档)。"""
    if scope is None or not line:
        return line
    fi = facts.get("_facts")
    if fi is None:
        return line
    names, off, key = _names_for_line(facts, line)
    if not names:
        return line
    # v63: 本行主语 (无登记 → None, 回落旧口径「按本篇传主算词」)。表在 facts 字典里
    # (与 `name_index` 同源同键, 由 facts 侧登记) —— 快照重跑时也能照原数据复算。
    owner = (facts.get("line_owner") or {}).get(key) if key else None
    # v63: 句面**已写明关系**的对手方 (成婚/添子/丧偶/夭折) → 不再插定语
    # (否则出「与丈夫X成婚」「得长女女儿X」这类赘语; 妻/夫/妾 是单字, 进不了
    #  `_KIN_MARK_RE` 的「已写明」判据)
    stated = set((facts.get("line_stated") or {}).get(key) or ()) if key else set()
    scan = off
    for cid, label in names:
        if not label:
            continue
        if cid in stated:
            continue
        # v45 拍板: 从不标本篇传主 (传主的事迹遍篇皆是, 加定语只是噪声;
        # v63 换基准后要在此显式挡住 —— 家人条目里传主可能以「句中第三人」出现)
        if cid == scope.subject:
            continue
        i = line.find(label, scan)
        if i < 0:
            # 索引记的是**构造期**的出词, 有的并未留在成句里 (死句把凶手称谓换成
            # 「其」等) —— 该行没出现这个称谓, 不占名额
            continue
        # 行内该处已带亲缘词 (「其父X」/「X的父亲Y」) → 关系已经写明, **不消费名额**,
        # 也不再插第二次词。v58 (问题8): 本判据必须在 `word_for` 之前 —— 否则会
        # 登记一个最终没插进去的词, v45 [2]「标注确实落在本板块文本里」随机 FAIL。
        if _KIN_MARK_RE.search(line[max(off, i - 12):i]):
            scan = i + len(label)
            continue
        # v63: 句中第三方人名 → 按本行主语算词; 本行主语自己 → 按本篇传主算词
        _subj = scope.subject
        if owner is not None and int(cid) != owner:
            _subj = owner
        w = scope.word_for(cid, fi, subject=_subj)
        if not w:
            scan = i + len(label)
            continue
        line = f"{line[:i]}{w}{line[i:]}"
        scan = i + len(w) + len(label)
    return line


def _tag_blocks(facts, scope, blocks):
    """v45 (档 B): 按**块序**给已建块的行内首见人名加定语 (幂等)。

    在 A 点位 (要员名录/死者行) 标记之前先跑一遍, 使名额按**阅读顺序**消费 ——
    年表里已经点名的人, 不会在后面的名录里再抢到这一次定语。"""
    if scope is None:
        return blocks
    for k, v in list(blocks.items()):
        if not isinstance(v, str) or k in scope.tagged:
            continue
        scope.tagged.add(k)
        blocks[k] = "\n".join(_kin_tag_line(facts, scope, ln)
                              for ln in v.split("\n"))
    return blocks


def _article_subject(facts, cache, key):
    """该篇的**传主** id (v45 亲缘定语的基准人): 《列传》即好友/仇人本人, 其余篇为主角。

    不能取 `article["subject"]` —— 那是名字字符串 (见 `build_articles`)。"""
    pid = facts.get("player_id")
    if key == "friend":
        try:
            return _pick_friend(cache, as_of=facts.get("as_of"))[0]
        except Exception:
            return pid
    if key == "enemy":
        try:
            return _enemy_for_facts(facts, cache)
        except Exception:
            return pid
    return pid


def _article_facts(facts, cache, key, section=None):
    """按文章取事实文本块 dict: {块名: 文本}。
    v11: 刺客列传按板块取料 — 开篇给压缩名录 (群像总览), 各纪事给对应时段切片。
    v45: 开头建**本板块专属**的亲缘定语登记表 `KinScope` (局部对象 —— 本函数是
    并发调用的, 挂 Facts 上会串味), 基准人 = 该篇传主。"""
    pid = facts.get("player_id")
    pname = (facts["protagonist"] or {}).get("name") or ""
    blocks = {}
    # ---- v45: 每板块一份亲缘定语登记表 (「首次」语义 S1: 该名字在本板块出现过即消费名额) ----
    subject = _article_subject(facts, cache, key)
    scope = F.KinScope(subject) if subject is not None else None
    # ---- v34 (问题1/5): 主角档案与逐年摘要由共享前缀改为按篇下发 ----
    # 内部档 (含「实父X」与揭底链) 只给讲门庭内情的篇目; 其余篇目拿公开档。
    private_boards = ("jiashi", "secrets", "qizu")
    # v45: 《列传》两篇的「传主档案」由下面分支用传主本人的档案覆盖 (biography.py
    # 好友/仇人分支), 这里不重复生成 —— 否则白算一遍, 还会把主角一家的名字记进
    # 本板块的亲缘名额 (S1 字面语义) 而挤掉真正的首见位。
    if key not in ("friend", "enemy") or subject is None:
        # v73: 《XX历代记》的**纪事各节**不下发传主档案 —— 先世各朝的素材只有
        # 「一人一行」, 而档案里有主角一家的丰富细节 (兄弟姊妹十七人、特质履历、
        # 封臣与直辖), 模型读了两份素材就会把主角的家世搬到先世头上 (实测虚构
        # 「格尔木噶玛之父为顿巴斯部将」). 开篇仍留档案 (写本朝要)。
        _mid_sec = _sec_key(section) not in ("lead", None)
        if not (key == "chaoju" and _mid_sec):
            _set_block(blocks, "传主档案",
                       "\n".join(_protagonist_archive_lines(
                           facts, private=key in private_boards, scope=scope,
                           # v57 (问题2a): 《刺客列传》篇不下发主角卒年 (死亡句/后任句)
                           with_death=(key != "assassins"),
                           # v70 (用户 2026-09-27 拍板): 《XX历代记》篇不下发朝局明细
                           # (封臣人数/御前会议席位/廷中僚属任职)
                           with_court=(key != "chaoju"))))
    if key == "benji":
        # v27: 开篇与纪事按模块切片, 两块料不相交
        # v34 (问题5): 不再附【主角大事摘要】(与下面的【大事年表】逐字重复,
        # 且共享前缀旧稿已注入 14 次); 逐年锚点由【大事年表】承担。
        sk = _sec_key(section)
        # v34 (问题8, 用户拍板): 《本纪》只写主角**自己的子女** —
        # 妻室与他人所出 (含法理上入了主角户籍的) 的出生记载不进本纪,
        # 那些孩子作为「妻子的子女」归《家室列传》与《阴私录》。
        tl_events = [e for e in F.slice_events(facts.get("timeline") or [], key, sk,
                                               exclude=_has_assassins(facts))
                     if e.get("own_birth") is not False]
        tl = [e["text"] for e in tl_events]
        _set_block(blocks, "大事年表", "\n".join(tl))
        link = _murder_link_line(facts, key, sk)
        if link:
            blocks["说明"] = link
    elif key in ("friend", "enemy"):
        sk = _sec_key(section)
        # v45: 复用入口已解析的篇传主 (此前在此重算一次)
        cid = subject
        if cid is not None:
            lines, events = _subject_facts(facts, cid, scope)
            # v27: 开篇只给传主档案 + 关系缘由; 纪事给传主行迹 + 模块切片年表
            # (此前开篇与纪事各拿一整套, 逐字节相同)
            if sk == "lead":
                blocks["传主档案"] = "\n".join(lines)
            else:
                # v29 (问题4): 行迹句省去句首传主名 (块内主语恒为传主)
                _prof = facts.get("characters", {}).get(str(cid)) or {}
                ev = _prof.get("events_subjectless") or events
                _set_block(blocks, "传主行迹", "\n".join(ev))
                # v63 (问题3, 用户拍板): 性事 (强迫/半推半就) 的唯一出口 ——
                # 角色档案与公开年表两侧都按 v59 口径不收, 好友/仇人列传这里单独出块。
                _gi = facts.get("_facts")
                if _gi is not None:
                    try:
                        _sx = _gi.sex_mem_lines(cid, as_of=facts.get("as_of"),
                                                player=facts.get("player_id"))
                    except Exception:
                        _sx = []
                    _set_block(blocks, "强迫之事", "\n".join(_sx))
                tl = F.slice_events(facts.get("timeline") or [], key, sk,
                                    exclude=_has_assassins(facts))
                # v52 (问题5): 传主篇年表只收传主本人参与的事件 (防第三者串味)
                tl = _subject_events(facts, key, tl, cid)
                tl = [e["text"] for e in tl]
                if tl:
                    blocks["相关年表"] = "\n".join(tl)
            # v13: 结友/结仇缘由 (双通道修复后必有记忆; 兜底同朝共事者给说明)
            # v27: 缘由归开篇 (二人关系如何结成), 纪事不再复述
            if sk == "lead" and key == "friend":
                fcid, is_fallback = _pick_friend(cache, as_of=facts.get("as_of"))
                if cid == fcid and is_fallback:
                    blocks["说明"] = ("传主与主角无结友记忆，本传按同朝共事之谊立传，"
                                      "以传主生平为主。")
                else:
                    rs = _relation_reasons(facts, cache, cid, _friend_types())
                    # v16: 游戏自带关系原因优先 (friend/soulmate/blood_brother)
                    gi = facts.get("_facts")
                    gr = []
                    if gi:
                        gr = gi.relation_reasons(
                            cid, ("friend", "best_friend", "soulmate",
                                  "blood_brother"))
                    all_r = gr + [x for x in rs if x not in gr]
                    if all_r:
                        blocks["结友缘由"] = "；".join(all_r)
            elif sk == "lead":
                rs = _relation_reasons(facts, cache, cid, _enemy_types())
                # v16: 仇恨根源 — 游戏原因 (rival/grudge/nemesis) 优先,
                # 程序直算因由 (亲属被谋杀/配偶私通/托卵) 补足死者/通用原因缺失
                gi = facts.get("_facts")
                causes = []
                if gi:
                    rd = _enemy_dates(cache).get(cid)
                    # v52 (问题5, 用户拍板): 缘由句带地点与收口 —
                    # 「在巴尔米拉，亨利在路上抢劫了阿金，阿金由此与他结怨（875年7月28日）。」
                    feud = _feud_sentences(
                        facts, cache, cid,
                        gi.relation_reasons(cid, ("rival", "grudge", "nemesis")),
                        rd)
                    causes.extend(feud)
                    if feud:
                        # 同一桩关系的「X与Y结怨」记忆句已并进上句, 不再并列出
                        rs = [x for x in rs
                              if not re.search(r"(结怨|结仇|死敌)", x or "")]
                    if rd:
                        causes.extend(F.relation_cause_lines(gi, cid, rd))
                all_r = causes + [x for x in rs if x not in causes]
                if all_r:
                    blocks["结仇缘由"] = "；".join(all_r)
    elif key == "jiashi":
        sk = _sec_key(section)
        fam_lines = []
        # v20: 家室列传按 as_of 过滤家人 — 十年传记用新缓存重跑时,
        # 出生晚于十年末的子女不写入 (与人物档案子女行 _asof_ids 同口径)
        fam_ids = _family_ids(cache)
        fi = facts.get("_facts")
        if fi is not None:
            fam_ids = set(F._asof_ids(fi, sorted(fam_ids)))
        # v27: 开篇发妻妾 (结缡与离异), 纪事发子女与同胞 (门庭恩怨)
        # (此前两块各拿全部家人档案, 家室档案 3,243 字符逐字节重复)
        # v63 (问题2, 用户拍板): 纪事**按门庭分组**下发 —— 每个请求只拿
        # 「一位配偶 + 其所出子女」的档案 (见 `facts.household_groups`)。
        members = section.get("members") if isinstance(section, dict) else None
        if members:
            pick = [c for c in members if c in fam_ids]
        else:
            spouse_ids = _family_ids_by_kind(cache, "spouse")
            # v76 (问题2, 用户拍板④): 开篇「结缡与离异」的配偶集同样按本篇窗口裁
            # (终传=一生 ⇒ 恒不裁)
            if fi is not None:
                spouse_ids = set(fi.spouses_in_window(sorted(spouse_ids)))
            pick = ([c for c in sorted(fam_ids) if c in spouse_ids]
                    if sk == "lead"
                    else [c for c in sorted(fam_ids) if c not in spouse_ids])
        # v45 (档 B, 阅读顺序): 先把此前的块 (传主档案等) 行内人名标好, 再标逐人条目头
        _tag_blocks(facts, scope, blocks)
        for cid in pick:
            p = facts["characters"].get(str(cid))
            if not p or not p.get("name"):
                continue
            # v34 (问题1): 家室列传是内宅档 — 子女档案放行「实父X」
            # (《本纪》等公开篇目仍只写法理谱系)
            fam_lines.append("\n".join(
                _profile_lines(facts, cid, with_real_parentage=True,
                               scope=scope)))
            # v90 (问题3, 用户 2026-10-02): 逐人条目改用**省主语版** —— 上面那句
            # 档案名号句已写明此人是谁, 条目里再挂一遍当日官称全名只是重复
            # (「892年12月2日，南诏乡绅洪天曾夺得兰溪。」→「892年12月2日，夺得兰溪。」)。
            ev = p.get("events_subjectless") or p.get("events") or []
            if ev:
                fam_lines.append("  " + "\n  ".join(ev))
        _set_block(blocks, section.get("block_title") or "家室档案",
                   "\n".join(fam_lines))
        # v31 (问题4): 妻室情事脉络 — 逐情人一行 (身份 + 私通→相恋→灵魂伴侣的关系弧),
        # 让「妻子怎么交到情人和灵魂伴侣」有脉络可写 (此前只有孤立日期句)。
        if sk != "lead":
            _set_block(blocks, "妻室情事脉络",
                       "\n".join(_consort_affair_lines(facts, cache)))
            # v32 (问题1): 强纳为妾 — 与监禁对并列即可读出「掳人→囚→强纳为妾」
            # (旧稿无此日期, 模型写成「嫁入年份未见于簿册」而默认先婚后囚)
            _set_block(blocks, "强纳为妾",
                       "\n".join(facts.get("forced_concubines") or []))
            # v60 (问题3): 妾的原有婚配被离断 (原配是游戏指定的那个人, 不是模型
            # 另造的妻子) —— 与「强纳为妾」同块序并读即成完整因果
            _set_block(blocks, "妾室原有婚配",
                       "\n".join(facts.get("concubine_divorces") or []))
        tl = F.slice_timeline(facts.get("timeline") or [], key, sk,
                                 exclude=_has_assassins(facts))
        if tl:
            blocks["相关年表"] = "\n".join(tl)
    elif key == "chaoju":
        # v68 (问题1): 开篇改「王朝历代」(用户拍板) —— 事实层 top_title_history =
        # 主角当前最高头衔从**战役起点**以来的国号沿革与历代持有者 (旧稿用
        # holder_changes 的「相关高位头衔」口径, 同一家族名下四枚被同一套游牧
        # 动态名命名的头衔并列, 国号一行不可见, 模型遂把草原汗位更替写成中国
        # 王朝更替, 并凭空补出「葛元方与石士良争权」这类朝堂戏)。
        # v70 (用户 2026-09-27 拍板): 纪事板块连同它的四块素材 (朝廷职司 / 主角受任 /
        # 廷中僚属任免 / 朝中要员 / 要员隐事) 整块删除 —— 那正是「朝局动态」的复现路径。
        # v73 (用户 2026-09-27 拍板「内容太短 → 扩充 + 分篇并发」): 素材扩到「一人一行」
        # (事实层 `realm["dynasty_chronicle"]`), 并按朝代分节 —— 开篇只发总说, 各纪事
        # 只发**本节**的历代明细与战事 (同请求内素材不重复, v27 铁律)。
        realm = facts.get("realm") or {}
        dashi = []
        if realm.get("liege_chain"):
            dashi.append(f"主角所处疆域：{realm['liege_chain']}")
        dc = realm.get("dynasty_chronicle") or {}
        _segs = (section or {}).get("periods") \
            if _sec_key(section) not in ("lead",) else None
        if _segs:
            rows, wars = [], []
            for _p in _segs:
                _rs = list(_p.get("rows") or [])
                _ds = list(_p.get("rows_detail") or [])
                for _i, _r in enumerate(_rs):
                    if not _r:
                        continue
                    # v82: 行形去「｜」分栏后, 「此行三样俱全 (称号/卒项/即位句)」由事实层
                    # 明文给出 (`rows_detail`); 该键缺失或该位为 None 时 (旧快照) 仍按旧的
                    # 「｜」个数兜底。
                    _d = _ds[_i] if _i < len(_ds) else None
                    _ok = (_r.count("｜") >= 2) if _d is None else bool(_d)
                    if _ok:
                        rows.append(_r)
                wars.extend(_chrono_wars_in(dc, _p, prev_cut=(section or {}).get("prev_cut")))
            if rows:
                _set_block(blocks, "王朝历代·纪事", "\n".join(rows))
            if wars:
                _set_block(blocks, "本朝战事", "\n".join(_chrono_dedup_wars(wars)))
        else:
            # v69 (用户拍板): 事实层改「每朝一行 + 该朝历代(含即位缘由)」的行形
            # (朝代行/历代行不再带「国号沿革：」「历代：」前缀), 故整块按原序发出。
            for ln in (realm.get("top_title_history") or []):
                dashi.append(ln)
            for _x in (dc.get("subs") or []):
                if _x:
                    dashi.append(_x)
            _set_block(blocks, "王朝历代", "\n".join(dashi))
    # ---- v5 新增文章 ----
    elif key == "assassins":
        # v27: 主角档案已在共享前缀, 不再重复
        killed = facts.get("killed") or []
        if killed:
            sec_key = (section or {}).get("key") or ""
            # v30: 篇内点名凶手一次 (问题8) — 各条死句已把凶手称谓缩为「其」,
            # 此处给出唯一一次全称谓作先行词
            plabel = ((facts.get("protagonist") or {}).get("label")
                      or (facts.get("protagonist") or {}).get("name") or "")
            n_victims = sum(1 for k in killed) + sum(len(k.get("group") or [])
                                                     for k in killed)
            head = (style.FACT_WORDING["assassin_lead"].format(
                n=n_victims, killer=plabel) if plabel else "")
            # v53 (问题4): 诛灭世族族级摘要置于名录之前
            purges = facts.get("family_purges") or []
            purge_txt = "；".join(purges) + "。" if purges else ""
            # v45 (档 A3/B, 阅读顺序): 先标此前块的行内人名, 再标死者名录
            _tag_blocks(facts, scope, blocks)
            if sec_key == "lead":
                # v11 开篇: 压缩名录 (死者名 + 生卒死因), 供群像总览, 不再整块铺 168 人档案
                parts = [head] if head else []
                if purge_txt:
                    parts.append(purge_txt)
                for k in killed:
                    parts.append(_assassin_lead_line(k, facts, scope))
                _set_block(blocks, "刀下诸魂", "\n".join(parts))
            else:
                # 各纪事: 按时段切片给完整档案 (v14 新口径: 官职名+亲缘+婚恋;
                # v30: 同组血亲已是单条, 切片以组为单位)
                sl = (section or {}).get("slice")
                picked = killed[sl[0]:sl[1]] if sl else killed
                parts = [head] if head else []
                if purge_txt:
                    parts.append(purge_txt)
                parts += ["\n".join(_assassin_kill_lines(facts, cache, k, scope))
                          for k in picked]
                _set_block(blocks, "刀下诸魂", "\n\n".join(parts))
    elif key == "youxia":
        # v27: 主角档案已在共享前缀; 行纪按前后二分 (开篇萍踪 / 纪事辗转)
        wander = list(facts.get("wandering") or [])
        seg = _split_span(wander, 0 if _sec_key(section) == "lead" else 1)
        _set_block(blocks, "行纪", "\n".join(seg))
    elif key == "qizu":
        # v27: 主角档案已在共享前缀
        imp = facts.get("imperial_spouses") or []
        if imp:
            parts = []
            for e in imp:
                lines = [f"妻族：{e['name']}"]
                if e.get("reasons"):
                    lines.append("门第：" + "、".join(e["reasons"]))
                prof = facts["characters"].get(str(e["id"])) or {}
                # v15: 档案为自然语言, 首行为名号句 (含姓名/家族) — 跳过, 其余全收
                for i, x in enumerate(_profile_lines(facts, e["id"])):
                    if i == 0:
                        continue
                    lines.append(x)
                ev = prof.get("events") or []
                if ev:
                    lines.append("经历：")
                    lines.extend("  " + s for s in ev)
                parts.append("\n".join(lines))
            _set_block(blocks, "帝胄姻亲", "\n\n".join(parts))
    elif key == "qunying":
        # v27: 主角档案已在共享前缀; 朝局动态按模块切片 (排除谋害人命)
        lum = facts.get("luminaries") or []
        _set_block(blocks, "朝堂群英", "、".join(lum))
        tl = F.slice_timeline(facts.get("timeline") or [], key,
                              _sec_key(section),
                              exclude=_has_assassins(facts))
        _set_block(blocks, "朝局动态", "\n".join(tl))
        link = _murder_link_line(facts, key, sk)
        if link:
            blocks["说明"] = link
    # ---- v9 新增文章 ----
    elif key == "feuds":
        # v27: 主角档案已在共享前缀
        feuds = facts.get("house_feuds") or []
        if feuds:
            parts = []
            for fd in feuds:
                # v29b: 「家族：程氏，两族为世仇」— 关系词不再放括注
                parts.append(f"家族：{fd.get('house_label') or fd['house']}，"
                             f"两族为{fd['level']}")
                if fd.get("events"):
                    parts.append("恩怨史：")
                    parts.extend("  " + e for e in fd["events"])
            _set_block(blocks, "家族恩怨", "\n\n".join(parts))
    elif key == "artifacts":
        # v27: 主角档案已在共享前缀
        arts = facts.get("family_artifacts") or []
        _set_block(blocks, "传家重宝", "\n\n".join(arts))
    elif key == "liyi":
        # v86《礼仪志·礼仪与教义》: 传主所受之礼与个人教义 (十年 + 终传都出)
        # v87 (问题2/3/7 + 判定 bug 修复): 板块判定改用 `_sec_key(section)` ——
        # `section` 是 **dict**, 旧稿 `str(section).startswith("mid")` 恒假, 于是
        # 开篇与纪事下发同一批块; 同时删去「圣所与圣髑」块。
        # v88 (问题3/P3-A, 用户 2026-10-01 拍板): 删「礼仪教义」(允许/禁止的礼仪级
        # 静态池), 纪事改用有个人色彩的三样; 开篇与纪事**两块料不相交**:
        #   开篇 = 礼仪档案 + 个人教义沿革 + 亲立修会      (他是谁)
        #   纪事 = 礼仪沿革 + 禁忌个人信条 + 门下教众      (发生何事、他人如何)
        # 无料的块整块不发 (`_set_block` 对空串即跳过), 纪事无料时该篇只出开篇。
        prof = list(facts.get("rite_profile") or [])
        hist = list(facts.get("rite_history") or [])
        pt = list(facts.get("personal_tenets") or [])
        hos = list(facts.get("holy_orders") or [])
        fbs = list(facts.get("forbidden_tenets") or [])
        tcs = list(facts.get("rite_tenet_changes") or [])
        if _sec_key(section) == "lead":
            _set_block(blocks, "礼仪档案", "\n".join(prof) if prof else "")
        else:
            # v89 (问题5): 「门下教众」块删除 (廷臣的个人教义与各人档案行重复, 无收录意义);
            # v89 (问题4): 补「本礼教义沿革」—— 那三条核心教义自身的更替。
            # v90 (问题5, 用户 2026-10-02 拍板): 「个人教义沿革」与「修会」移入纪事 ——
            # 开篇只讲「他是谁」(所奉礼仪的档案面), 凡带年月的沿革与修会全归纪事;
            # 两块料不相交 (v27 口径), 于是本志必有两个板块 (旧稿两者挤在开篇,
            # 又因 `_liyi_has_mid` 不认它们, 天贵福 915 档整篇只剩一个板块)。
            if pt:
                _set_block(blocks, "个人教义沿革", "\n".join(pt))
            if hos:
                _set_block(blocks, "修会", "\n".join(hos))
            if hist:
                _set_block(blocks, "礼仪沿革", "\n".join(hist))
            if tcs:
                _set_block(blocks, "本礼教义沿革", "\n".join(tcs))
            if fbs:
                _set_block(blocks, "禁忌个人信条", "\n".join(fbs))
    elif key == "secrets":
        # v28《阴私录·隐事秘辛》: 主角隐事归开篇, 家人近臣隐事与把柄归纪事
        sec = facts.get("secrets") or {}
        sk = _sec_key(section)
        kin_lines = list(sec.get("kinsmen") or [])
        has_held = bool(sec.get("held"))
        if sk == "lead":
            lines = list(sec.get("held") or [])
            if sec.get("held_murder"):
                lines.append(_murder_index_line(facts, sec))
            if has_held and sec.get("held_unrevealed"):
                lines.append("这些隐事至今无人知晓。")
            # v59 (问题2, 用户拍板): 性事只在《列传·好友》《列传·仇人》里用 ——
            # 「强迫之事」块（v38）撤下；性病传播块**保留**在《阴私录》
            # （它是疾病线, 不是性事行; 性事行本身由年表闸与档案闸全局挡住）。
            # v40: 性病传播 (无源则写「染上」) —— 开篇给前两条
            dis = list(sec.get("disease") or [])
            if dis:
                lines.append(style.FACT_WORDING["std_head"])
                lines.extend(dis[:2])
            # v31 (问题7): 主角无自有隐事时, 开篇改用家人近臣隐事前半 —
            # 旧文本开篇块为空, 模型只能拿共享前缀一行「戏剧性事件」自问自答
            # (「知情者何人？…则其亦必知情」)。
            if not lines and kin_lines:
                lines = _split_span(kin_lines, 0)
            _set_block(blocks, "主角隐事", "\n".join(lines))
        else:
            mid_lines = list(kin_lines if has_held else _split_span(kin_lines, 1))
            mid_lines.extend(sec.get("known") or [])
            # v31 (问题5): 牵制 (把柄维度) — 用户决策: 只随《阴私录》下发。
            # v41 (问题8): 去掉「…的牵制如下：」两条标题行 —— 事实行本身已是
            # 自足句 (「主角握有对X的强牵制「干了我老婆」（1087年起）。」),
            # 标题行只把这一维度引成「由你来列举」的开放清单, 模型据此自行
            # 铺陈御前会议互握把柄等无据情节 (诺兰第四个十年实测)。
            mid_lines.extend(list(sec.get("hooks_held") or []))
            mid_lines.extend(list(sec.get("hooks_over") or []))
            # v35 (问题4): 奴役 (Carnalitas) 与「把柄」分列 —— 「抓人 → 没为奴隶 →
            # 放出牢房」是一层人身关系, 不是握有把柄; 旧稿把它读成「抓了又放」。
            # v38 (问题4): 追加「昔日奴隶」档 —— 被卖掉/获释的人此后仍在事实面上
            # (旧稿一被卖掉就彻底消失, 模型此后再无此人可依)。
            en = list(sec.get("enslaved") or [])
            if en:
                mid_lines.append(style.FACT_WORDING["enslaved_head"])
                mid_lines.extend(en)
            enf = list(sec.get("enslaved_former") or [])
            if enf:
                mid_lines.append(style.FACT_WORDING["enslaved_former_head"])
                mid_lines.extend(enf)
            # v38 (问题1): Carnalitas 事件好感 (强奸/奴役/逼良为娼/前主奴) 与
            # 「近来遭强暴」修正 — 自带 start_date, 补足「不留记忆」的互动。
            cpl = list(sec.get("carnal_opinions") or [])
            if cpl:
                mid_lines.append(style.FACT_WORDING["carnal_opinions_head"])
                mid_lines.extend(cpl)
            cvl = list(sec.get("carnal_victim") or [])
            if cvl:
                mid_lines.extend(cvl)
            # v59 (问题2, 用户拍板): 「强迫之事」块撤下 (性事只在好友/仇人列传里用);
            # 性病传播块保留 (疾病线, 非性事行)。
            # v40: 性病传播全列 (纪事给全部)
            dis = list(sec.get("disease") or [])
            if dis:
                mid_lines.append(style.FACT_WORDING["std_head"])
                mid_lines.extend(dis)
            _set_block(blocks, "家人近臣隐事", "\n".join(mid_lines))
            if sec.get("events"):
                blocks["隐事纪年"] = "\n".join(sec["events"])
    # ---- v45 (档 B): 全板块收尾 —— 按块序给行内首见人名加亲缘定语 ----
    # (A 点位在构建期已标过; 这里补年表/隐事/恩怨等**行内**点名位)
    _tag_blocks(facts, scope, blocks)
    return blocks


def _murder_index_line(facts, sec):
    """谋杀类隐事的索引行: 有《刺客列传》时指向该篇, 否则直出隐事所涉人名
    (只用隐事记录里的人, 不把处决等非隐事击杀混进来)。"""
    n = sec.get("held_murder") or 0
    if _has_assassins(facts):
        return f"另有{n}桩谋杀隐事，详见《刺客列传·刀下诸魂》。"
    names = [x for x in (sec.get("held_murder_names") or []) if x]
    if names:
        return f"另有{n}桩谋杀隐事，涉及{'、'.join(names)}。"
    return f"另有{n}桩谋杀隐事。"


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

def _rule_block(style_name, secret=False):
    """system 规则块 (v30: 文本与顺序见 style.rule_block)。"""
    return style.rule_block(style_name, secret)


def _system_msg(style_name="east", extra="", secret=False):
    return style.PROMPTS["system_head"].format(
        rule_block=_rule_block(style_name, secret)) + extra


def _decade_theme_note(facts):
    """戏剧主题预告 (v14): 数据驱动 Top5 (并列第5名全保留, facts.py
    decade_module_top)。十年传记 (有 as_of) 称「本十年」, 终传/在世称「一生」。
    正向表述指引各篇围绕主题取材。无主题时返回空串。
    v28: 天朝制/行政制 (官职轮转) 的主题显示名按官制换词 (受任迁转/卸任调转),
    内部模块键不变 (MODULE_SLICE 切片依赖原键)。"""
    dm = facts.get("decade_modules") or []
    if not dm:
        return ""
    names = "、".join(_theme_label(m, facts) for m, _s in dm)
    label = "本十年" if facts.get("decade") else "一生"
    return style.PROMPTS["theme_note"].format(label=label, names=names)


def _celestial_like(facts):
    """主角政体是否属官职轮转一类 (天朝制/行政制/选贤/草原行政)。"""
    p = facts.get("protagonist") or {}
    return (p.get("government_key") or "") in F.Facts._CELESTIAL_LIKE_GOVS


def _theme_label(name, facts):
    if name in style.THEME_LABELS and _celestial_like(facts):
        return style.THEME_LABELS[name]
    return name


def _section_req(text, facts):
    """板块要求在官职轮转政体下换词 (受任/卸任/调任), 其余政体原文不动。"""
    if not text or not _celestial_like(facts):
        return text
    for a, b in style.REQ_SWAPS:
        text = text.replace(a, b)
    return text


def _jiashi_variant(facts, cache):
    """《家室列传》素材档 (v60 问题3) → 'spouse' | 'spouse_plain' | 'concubine' | 'none'。

    判据全在程序侧: 主角的配偶集 (含前妻, 已在 `Facts.merge_spouse_latch` 里
    并入婚配闩存) 与妾集孰有孰无。无正妻而只有妾时不得再索要「结缡、离异、
    前妻之死、再娶」; 两者皆无时不得索要妻室子女 —— 否则模型只能编造
    (崔佛档实测: 一生无正妻、无子女, 传记却写出「结缡三次」)。
    v74 (问题3, 用户拍板): 有妻室时再分两档 —— 只有存在**真托卵**
    (`father != real_father`, 由 `facts._villain_chains` 的「托卵承嗣」链判定) 才用
    「子女来历与**血脉之争**」的题面 (托卵按老方案); 公开私生的孩子随生父之氏,
    不是血脉官司, 走 `spouse_plain`。"""
    pid = cache.get("player_id")
    if pid is None:
        return "none"
    fam = ((cache.get("characters") or {}).get(str(pid)) or {}).get("family") or {}
    if fam.get("primary_spouse") or fam.get("spouse") \
            or fam.get("former_spouses"):
        for _mod, _s, _p in (facts.get("villain_chains") or []):
            if str(_mod) == "托卵承嗣":
                return "spouse"
        return "spouse_plain"
    if fam.get("concubine") or fam.get("former_concubines"):
        return "concubine"
    return "none"


def _protagonist_archive_lines(facts, private=False, scope=None, with_death=True,
                               with_court=True):
    """主角档案块 (v34, 问题5): 从共享前缀移出, 按篇下发。
    private=True 放行揭底链 (托卵承嗣/血脉登基) 与「实父」行 —
    只给《家室列传》《阴私录》这类讲门庭内情的篇目。
    v45: scope = 本板块的亲缘定语登记表 (基准人 = 该篇传主)。
    v57 (问题2a): with_death=False 时不出死亡句与「后任」句 (《刺客列传》篇专用,
    该篇人名录恒为死于主角之手者; 主角卒年数据留在篇内会被模型续成名录末条)。
    v70: with_court=False 时不出封臣人数/御前会议席位/廷中僚属任职
    (《XX历代记》篇专用, 见 `_profile_lines` 同源注释)。"""
    return _profile_lines(facts, None, with_real_parentage=private,
                          with_private_chains=private, scope=scope,
                          with_death=with_death, with_court=with_court)


def _shared_facts_block(facts, subject=None, key=None):
    """所有调用共享的事实前缀 (v9 输入缓存优化 + v14 瘦身)。

    v34 (问题5, 用户拍板): 只留**稳定最小身份票** —
    【传主】【家族】【现状】+【概览】+ 按需的【冒险者行踪】【瘟疫】。
    完整【人物档案】与【主角大事摘要】移出共享前缀, 改由 `_article_facts`
    按篇下发 (旧稿把同一份档案与逐年摘要注入每一次请求, 各篇因此车轱辘话)。
    共享前缀仍逐字节一致置于每条 user 消息最前, 供 DeepSeek 前缀缓存命中。

    v56 (问题1a, 用户拍板案 A): `subject` = 该篇**传主**名 (仅《列传·好友》《列传·仇人》
    两篇给出)。给了时首行改称【主角】—— 该篇的传主是别人, 首行若仍写【传主】,
    与本篇紧随的 `subject_note`「【传主】X」正面冲突, 模型据此把主角当成传主。
    其余篇目 subject 为 None, 首行逐字不变 (共享前缀仍是同一条缓存前缀)。

    v57 (问题2a, 用户拍板案 A): `key` = 本篇篇目键。《刺客列传》篇不出**主角卒年行**
    —— 该篇人名录恒为「死于主角之手者」, 主角卒年一旦随前缀下发, 模型会把它续成
    名录的最后一条 (斯卡利茨终传实测 «**秦皇帝撒旦之种施沙米尔**，948年10月6日，
    误食了一些有毒的植物，死于丹徒，年三十七。»); 主角在该篇是凶手位, 卒年用不上。
    同源收紧见 `_profile_lines(with_death=False)`。其余篇目逐字不变。"""
    p = facts["protagonist"]
    name = p.get("name") or "主角"
    house = _house_text(facts)
    death = facts.get("player_death")
    re_end = facts.get("reign_end")            # v76 (问题1): 让位/剃发退位
    if re_end and key != "assassins":
        # ⚠ 不再前置日期: `reason_zh` 由 facts.reign_end_clause 渲染时**已含日期**
        # (「922年7月7日，剃发退位，传位于其子日本关白田所定治」)。
        rz = re_end.get("reason_zh") or "让位"
        life_note = f"【传位】{rz}——此为终传"
    elif re_end:
        life_note = ""
    elif death and key != "assassins":
        rz = death.get("reason_zh") or death.get("reason") or "去世"
        life_note = (f"【卒年】{llm.fmt_cn_date(death.get('date'))}，{rz}"
                     "——此为终传")
    elif death:
        life_note = ""
    elif facts.get("as_of"):
        life_note = f"【现状】在世，截至{llm.fmt_cn_date(facts['as_of'])}"
    else:
        life_note = "【现状】在世，截至最后一份存档"
    # v20 (B3) / v29 (问题2): 【冒险者行踪】— 只记无地冒险者时期的营地阶段与驻地
    stations_txt = ""
    stations = facts.get("protagonist_stations") or []
    if stations:
        stations_txt = _render_block("【冒险者行踪】", stations)
    # v64 (问题1, 用户拍板): 【游牧行踪】— 只记游牧时期**大帐位置的移动**
    # (立帐 + 逐年驻地)。毡帐不作领地进行历任相位 (`facts._primary_group`),
    # 故大帐轨迹另出一块, 与【冒险者行踪】同式同源。
    nomad_txt = ""
    nomad_st = facts.get("nomad_stations") or []
    if nomad_st:
        nomad_txt = _render_block("【游牧行踪】", nomad_st)
    # v29 (问题7): 瘟疫风味 — 游戏给的动态疫名 (李黯之火/撒丁痘), 只在
    # 触及主角封地/所在郡或家人染疫时下发; 远地瘟疫不写
    plague_txt = ""
    pl = (facts.get("plagues") or {}).get("lines") or []
    if pl:
        plague_txt = _render_block("【瘟疫】", pl)
    # v15: 十年/一生概览 (程序直算统计: 结怨9次、谋杀5次…, 给模型数据锚点)
    stats_txt = ""
    ds = facts.get("decade_stats") or []
    if ds:
        label = "本十年" if facts.get("decade") else "一生"
        stats_txt = f"【概览】{label}{'、'.join(ds)}。"
    head = f"【{'主角' if subject else '传主'}】{name}\n【家族】{house}"
    out = [f"{head}\n{life_note}" if life_note else head]
    if stations_txt:
        out.append("\n\n" + stations_txt)
    if nomad_txt:
        out.append("\n\n" + nomad_txt)
    if plague_txt:
        out.append("\n\n" + plague_txt)
    if stats_txt:
        out.append("\n\n" + stats_txt)
    return F.sanitize_fact_text("".join(out), where="共享前缀") + ""


_CN_DIGITS = "零一二三四五六七八九"


def _cn_index(n):
    """篇目序号汉字 (v88 问题1): 1 → 一 … 9 → 九、10 → 十、11 → 十一、21 → 二十一。

    起因: 旧稿 `build_intro_messages` 里写死 `CN_NUMS = "一二三四五六七八九"` (9 字),
    第 3 个十年传记的篇目数正好 **10** (`i == 9`), `CN_NUMS[9]` 抛
    `IndexError: string index out of range` —— 整个十年传记生成在此崩掉
    (2026-10-01 12:11:54 洪氏2 实测, 日志只有一行 `传记生成失败 (将重试)`)。

    与 `facts._count_zh` / `facts._ordinal_zh` 分用: 前者 2 作「两」、后者 <10 带「世」,
    都不适合篇目序号。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if n <= 0:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" + (_CN_DIGITS[n - 10] if n > 10 else "")
    if n < 100:
        t, r = divmod(n, 10)
        return _CN_DIGITS[t] + "十" + (_CN_DIGITS[r] if r else "")
    return str(n)


def build_intro_messages(facts, cfg, articles=None):
    """总纲提示词 (共享前缀 + 篇目预告)。v11: 输出头改为 生卒; 明确以「太史公曰」作结。"""
    p = facts["protagonist"]
    name = p.get("name") or "主角"
    house = _house_text(facts)
    style_name = facts.get("bio_style") or "east"
    birth = p.get("birth") or ""
    death = facts.get("player_death")
    re_end = facts.get("reign_end")            # v76 (问题1): 让位/剃发退位
    if re_end:
        # v76 (问题1): 让位者**在世** —— 不写「生卒」(生卒意为生–死), 改「生平…（剃发退位）」,
        # 与共享前缀的【传位】行同口径。
        span_cn = (f"生平：{birth}–{llm.fmt_cn_date(re_end.get('date'))}"
                   f"（{re_end.get('word_zh') or '让位'}）" if birth else "")
    elif death:
        span_cn = f"生卒：{birth}–{llm.fmt_cn_date(death.get('date'))}"
    else:
        span_cn = f"生于{birth}" if birth else ""
    sys_msg = style.PROMPTS["intro_system"].format(
        rule_block=_rule_block(style_name))
    shared = _shared_facts_block(facts)
    # v34 (问题5): 总纲是唯一点评一生大势的篇目, 主角档案随总纲下发
    # (共享前缀已不再注入档案); 总纲讲的是全局, 用公开档 — 揭底隐情归
    # 《家室列传》《阴私录》, 由篇目预告点出而不在此处说破。
    # v45 (档 A): 总纲的档案块另建一份亲缘定语登记表 (基准人 = 主角; 本人名号句不
    # 加定语)。与各篇的 scope 互不相干 —— 总纲是独立请求。
    shared = _render_block("【人物档案】",
                           _protagonist_archive_lines(
                               facts, scope=F.KinScope(facts.get("player_id")))) \
        + "\n\n" + shared
    # 文章预告: 用实际文章标题 (好友/仇人姓名已定; v5 支持任意篇数)
    # v88 (问题1): 序号改走 `_cn_index` —— 旧稿写死 9 个汉字, 篇目到 10 就抛
    # `IndexError: string index out of range` (第 3 个十年传记整篇失败)。
    if articles:
        preview = "\n".join(
            f"{_cn_index(i + 1)}、《{a['title']}》——{a.get('focus') or a.get('theme') or a['key']}"
            for i, a in enumerate(articles))
        n_articles = len(articles)
    else:
        preview = style.PROMPTS["preview_fallback"].format(name=name)
        n_articles = 5
    user_msg = style.PROMPTS["intro_user"].format(
        shared=shared, theme=_decade_theme_note(facts), n_articles=n_articles,
        preview=preview, name=name, house=house, span_cn=span_cn)
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def build_lead_messages(article, facts, cache, intro, cfg):
    """五篇文章的首段提示词 (共享前缀 + 总纲 + 文章专属, 输入缓存友好)。"""
    key = article["key"]
    sec = article["sections"][0]
    title = article["title"]
    style_name = facts.get("bio_style") or "east"
    blocks = _article_facts(facts, cache, key, sec)
    sys_msg = style.PROMPTS["system_head"].format(
        rule_block=_rule_block(style_name, key in style.SECRET_BOARDS))
    facts_txt = "\n\n".join(_render_block(k, v.split("\n")) for k, v in blocks.items())
    subject_note = _subject_note(article, facts)
    custom_note = ""
    if key == "benji" and (facts["protagonist"] or {}).get("custom_start"):
        # v30: 曾写「本篇传主的先世资料未载」+「以资料载明者为限」, 前者被逐字照抄;
        # 现只写「怎么写」——自定义开局的谱系在档案里本就没有父/母行, 程序端已是无料。
        custom_note = style.PROMPTS["custom_start_note"]
    events_block = _key_events_block(facts, key, sec,
                                     subject=_article_subject(facts, cache, key))
    # v70 (用户 2026-09-27 拍板「移除朝局动态」): 《XX历代记》不注入【总纲】全文 ——
    # 总纲的【人物档案】带朝局明细 (「…直辖5地…封臣226人，御前会议九席…」), 而
    # 各篇开篇请求都会带上总纲全文; 尼克终传实测该篇正文照抄成「…治所定于长安县，
    # 封臣二百二十六人，御前会议九席分掌诸曹」—— 板块与档案两处裁剪都被它绕过。
    # 本篇素材自足 (王朝历代 + 本朝疆域 + 任期), 不依赖总纲的叙述框架。
    # 其余篇目逐字不变 (intro_block 与旧模板拼出的串完全相同)。
    intro_block = "" if key == "chaoju" else f"【总纲】\n{intro}\n\n"
    user_msg = style.PROMPTS["lead_user"].format(
        shared=_shared_facts_block(facts, subject=article.get("subject"), key=key),
        theme=_decade_theme_note(facts),
        intro=intro, intro_block=intro_block,
        custom_note=custom_note, subject_note=subject_note,
        facts=facts_txt,
        events=(f"{events_block}\n\n" if events_block else ""),
        title=title, focus=article.get("focus") or article.get("theme") or "",
        sec_title=sec["title"], sec_req=sec["req"])
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def _subject_note(article, facts):
    """传主类文章 (好友/仇人列传) 的叙述中心提示。

    v56 (问题1a, 用户拍板案 A): 共享前缀对有传主的篇目改称【主角】(见
    `_shared_facts_block`), 本篇传主之名由这里**一次**立下 (行首【传主】X)。"""
    subj = article.get("subject")
    if not subj:
        return ""
    return style.PROMPTS["subject_note"].format(
        subject=subj, protagonist=(facts["protagonist"] or {}).get("name") or "")


def build_section_messages(article, section, facts, cache, lead_text, cfg):
    """中段提示词。v11: 不再注入【总纲】全文 (防止每篇复述总纲导致雷同);
    承接开篇以正向表述推进新内容; 无尾段 (太史公曰只留总纲)。
    v27: 开篇回贴改「前缀+结尾」摘要 (不再整篇回贴); 素材尾部加【本板块大事】锚点。"""
    key = article["key"]
    title = article["title"]
    style_name = facts.get("bio_style") or "east"
    blocks = _article_facts(facts, cache, key, section)
    sys_msg = style.PROMPTS["system_head"].format(
        rule_block=_rule_block(style_name, key in style.SECRET_BOARDS))
    facts_txt = "\n\n".join(_render_block(k, v.split("\n")) for k, v in blocks.items())
    subject_note = _subject_note(article, facts)
    # v73: 《XX历代记》纪事各节**不发【本板块大事】** —— 年表是主角一生行迹 (先世各朝
    # 的事件本就不在里面), 而它是一张「须写出这些事」的卡片: 与「一人一行」的先世素材
    # 并列时, 模型会为这张卡片现编事件填满 (实测虚构「会稽豪强张氏举兵」「汪吉河畔损兵
    # 三千」)。本篇的取材锚点就是历代行的日期与战事行。
    if key == "chaoju" and _sec_key(section) not in ("lead", None):
        events_block = ""
    else:
        events_block = _key_events_block(facts, key, section,
                                         subject=_article_subject(facts, cache, key))
    # v73: 《XX历代记》的纪事各节是**按朝代分段**的, 与开篇（王朝总说）本不必承接
    # 大段文字 —— 实测摘要给足时模型会把开篇的总说整段重写一遍 (各节自述一遍王朝
    # 更迭)。故本篇摘要收紧到「一句引子 + 一句结尾」。
    _dg_limit, _dg_tail = (120, 90) if key == "chaoju" else (260, 180)
    user_msg = style.PROMPTS["mid_user"].format(
        shared=_shared_facts_block(facts, subject=article.get("subject"), key=key),
        theme=_decade_theme_note(facts),
        subject_note=subject_note, facts=facts_txt,
        events=(f"{events_block}\n\n" if events_block else ""),
        title=title, focus=article.get("focus") or article.get("theme") or "",
        sec_title=section["title"], sec_req=section["req"],
        lead_title=article["sections"][0]["title"],
        lead_digest=_lead_digest(lead_text, limit=_dg_limit, tail=_dg_tail,
                                 facts_text=facts_txt))
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


# ---------------------------------------------------------------------------
# 文本规范化与组装
# ---------------------------------------------------------------------------

_MAG_HEAD_RE = re.compile(r"^#{1,6}\s+")


# v71 (问题2): 板块尾部完整性 —— 上游把正文拦腰截断时, 残留物常是「末字为开括号」
# 或「强调符只开不合」。实测 (2026-09-24 ~ 09-26 四篇): 板块末字分别为
# `（`(卡尔第1个十年·门庭恩怨)、`“`(卡尔终传·恩怨始末)、`「`(尼克第1个十年·诸魂行迹)、
# `【`(富兰克林终传·开篇); 另有 `**` 未闭合、末句断在词上 (`后世`/`——`) 等同类残迹。
_DANGLING_OPEN = "「『“【《〈（([{"


def _tail_issue(text):
    """板块正文末尾是否被截断: 返回原因串, 正常收尾返回 None (纯函数)。"""
    t = (text or "").rstrip()
    if not t:
        return None
    if t[-1] in _DANGLING_OPEN:
        return f"末字为开括号「{t[-1]}」"
    if t.count("**") % 2:
        return "强调符 ** 未闭合"
    return None


def _trim_dangling_tail(text):
    """裁掉尾部残留的开括号 (成对闭符号与正文一字不动); 返回 (text, 是否裁过)。"""
    t = (text or "").rstrip()
    changed = False
    while t and t[-1] in _DANGLING_OPEN:
        t = t[:-1].rstrip()
        changed = True
    return t, changed


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


def _fix_person_names(text, facts, cache):
    """v80 (点6, 附带B): 把「姓氏 + 亲属词」式**误写的名字**改回正确全名。

    起因: 田所定治 十年1 总纲把「六角继子」写成「六角**妻子**」——「继子」形似普通
    名词, 模型把它当成了亲属词。总纲要被逐字注入每一篇 (六次), 于是 `_fix_kin_roles`
    改不动 (它只管亲属词改名, 不管名字被改), 一错到底。

    判据 (v80 二稿, 首稿的「同姓唯一」过严 —— 六角一族在材料里有五人, 一处都改不成):
      以本篇事实里的已知人名为准, 取「姓部 + 名(末二字)」。凡正文出现「姓 + 某亲属
      词 W」且该串不是素材里任何人的名字时, 在**同姓者**中找「相对本篇传主的真实
      亲属词 == W」的那一位 (用 `F.kin_word`, 与 `_fix_kin_roles` 同源口径):
        · 恰好一位 → 恢复其全名 (「六角妻子」→「六角继子」, 她是传主之妻);
        · 零位或多位 → 不动 (不猜)。纯函数、幂等。"""
    if not text:
        return text
    chars = (facts or {}).get("characters") or {}
    pid = cache.get("player_id") or (facts or {}).get("player_id")
    by_name, by_sur = {}, {}
    for cid_s, rec in chars.items():
        nm = (rec or {}).get("name") or ""
        if len(nm) < 3 or not re.search(r"[\u3400-\u9fff]", nm):
            continue
        try:
            cid = int(cid_s)
        except (TypeError, ValueError):
            continue
        sur = nm[:-2]
        if len(sur) < 2:
            continue
        by_name.setdefault(nm, cid)
        by_sur.setdefault(sur, {})[nm] = cid
    if not by_sur or pid is None:
        return text
    known = set(by_name)
    words = [w for w in sorted(F.kin_texts(), key=len, reverse=True)
             if len(w) >= 2]
    out = text
    for sur, cands in by_sur.items():
        for w in words:
            bad = sur + w
            if bad in known or bad not in out:
                continue
            hit = ""
            for nm in sorted(cands):
                try:
                    if F.kin_word(cache, pid, cands[nm]) == w:
                        hit = nm
                        break
                except Exception:
                    continue
            if hit:
                out = out.replace(bad, hit)
    # 纠名自身不得造出相邻重复 (与 _fix_kin_roles 同收口)
    return _dedup_adjacent_words(out)


def _fix_kin_roles(text, facts, cache):
    """v52 (问题1): 把「亲属词 + 人名」里对不上档案的亲属词改回正确词。

    起因: 总纲是模型文本, 却要被逐字注入每一篇开篇当材料 —— 第 4 个十年总纲把
    妻室写成「母亲阿基坦公主年轻者希尔德加德·加洛林…却为他生下四子二女」,
    本纪开篇据此把她当成了传主的母亲。此处只改**紧贴人名的那个亲属词**
    (窗口 12 字内取最后一个亲属词), 与档案不符才改, 对得上则一字不动; 幂等。

    纯函数 (不依赖熔件): 亲属词表与「人→正确词」都由 cache 亲属图判定。"""
    if not text:
        return text
    pid = cache.get("player_id")
    fi = (facts or {}).get("_facts")
    if pid is None or fi is None:
        return text
    fam = ((cache.get("characters") or {}).get(str(pid)) or {}).get("family") or {}
    kids = set(fam.get("child") or []) | set(fam.get("siblings") or [])
    others = []
    for key in ("primary_spouse", "spouse", "former_spouses", "ever_spouses",
                "concubine", "former_concubines", "father", "mother"):
        others.extend(fam.get(key) or [])
    others.extend(sorted(kids))
    chars = cache.get("characters") or {}
    # v52: 只用**双音节**亲属词做"错词"候选 —— 单字词 (子/父/母…) 会与替换结果
    # 自身重叠 (「妻子」里含「子」), 逐次替换永不收敛 (实测死循环)。
    all_words = {F.kin_text(k) for k in F.KIN_WORDS}
    all_words = {w for w in all_words if w and len(w) >= 2}
    # 「妻室」是本项目档案行用的配偶词 (不在 kin 表内), 也要能纠
    all_words |= {"妻室"}
    out = text
    for other in dict.fromkeys(int(x) for x in others
                               if isinstance(x, int) or str(x).isdigit()):
        rec = chars.get(str(other)) or {}
        names = [rec.get("name_full"), rec.get("name_zh"),
                 (facts.get("characters", {}).get(str(other)) or {}).get("name")]
        names = [n for n in dict.fromkeys(names) if n]
        if not names:
            continue
        try:
            # kin_word(cache, A, B) = 「B 相对 A」的词 (实测口径): 取 other 相对 pid
            true_word = F.kin_word(cache, pid, other, chars=chars)
        except Exception:
            true_word = ""
        if not true_word:
            continue
        for nm in names:
            i = out.find(nm)
            guard = 0
            while i != -1 and guard < 8:
                guard += 1
                win = out[max(0, i - 12):i]
                best_w, best_p = "", -1
                for w in all_words:
                    if not w or w == true_word:
                        continue
                    j = win.rfind(w)
                    if j < 0:
                        continue        # 窗口里没有该词 (rfind 返回 -1, 不得参与比较)
                    # v80 (点3): 同位置取**最长**词 —— 新表有 42 对互为后缀的词
                    # (伯祖父 ⊃ 祖父、侄孙女 ⊃ 孙女、外曾孙女 ⊃ 曾孙女…), 只比位置
                    # 会把「曾祖父X」里的「祖父」当错词, 把更精确的词换成更粗的词。
                    if j > best_p or (j == best_p and len(w) > len(best_w)):
                        best_w, best_p = w, j
                if best_w:
                    at = max(0, i - 12) + best_p
                    out = out[:at] + true_word + out[at + len(best_w):]
                    i = out.find(nm, at + len(true_word) + len(nm))
                else:
                    i = out.find(nm, i + 1)
    # v70: 纠词自身不得造出相邻重复 —— 窗口里已有同词时, 换上去会成「妹妹妹妹」
    # (尼克终传实测「妹妹妹妹之间，卡尔松同西格…」)。收口与成稿闸同一函数。
    return _dedup_adjacent_words(out)



# v70 (用户 2026-09-27 拍板「姐姐姐姐一类的重复一起改掉」): 成稿侧相邻重复词闸。
# 只收**亲属称谓 / 爵职国号 / 出身词**三类 —— 这些词紧邻重复两次在任何语境下都是
# 笔误 (实测模型输出: 「家中姐姐姐姐众多」「有妹妹妹妹七人」「她的妻子妻子还剩…」
# 「神圣罗马帝国帝国公主」)。汉语合法叠词 (人人/一一/常常/渐渐)、数字叠字
# (一一一一年)、以及人名与「X、X」式并列 (「芙蕾雅、芙蕾雅」是军中两名同名者,
# 模型还专门作了解释) 一律不入表, 故闸门只对下表内的词、且只对**直连**形态生效。
_DEDUP_WORDS = (
    # 亲属称谓
    "姐姐", "妹妹", "哥哥", "弟弟", "兄长", "兄弟", "姊妹", "妻子", "丈夫",
    "母亲", "父亲", "儿子", "女儿", "祖父", "祖母", "伯父", "叔父", "姑母",
    "姨母", "舅父", "舅舅", "外甥女", "外甥", "侄女", "侄子",
    # 爵职与国号
    "帝国", "王国", "公国", "侯国", "伯国", "皇朝", "天朝", "王朝", "汗国",
    "苏丹国", "哈里发国", "皇帝", "皇后", "国王", "公爵", "伯爵", "侯爵",
    "男爵", "可汗", "大汗", "酋长", "节度使", "刺史", "宰相", "尚书",
    # 出身词 (游戏特质)
    "庶出", "私生子",
)
_DEDUP_RE = re.compile("(" + "|".join(sorted(_DEDUP_WORDS, key=len, reverse=True))
                       + r")\1")


def _dedup_adjacent_words(text):
    """同一词紧邻出现两次 → 只留一次 (v70)。见 `_DEDUP_WORDS` 的范围说明。"""
    if not text:
        return text
    return _DEDUP_RE.sub(r"\1", text)


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
    # v74: 标题本身**无该前缀**时 (《诸子行迹·<子名>》即此类) 不存在「短版」——
    # 旧稿此处 short == sec_title, 于是模型照抄标题 `### 诸子行迹·X` 时被判成
    # 「短版重复」整行剔掉, 而 `saw` 又已置真 (不再补标题) ⇒ 该板块正文失去标题、
    # 与前一个板块的正文连读 (实测 田所 898: 久保/德川/其余子女三节标题全被吃掉)。
    if short == sec_title:
        short = ""
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
            # v73: 模型把**素材行**当成标题输出 (《历代记》各节的素材里有「元皇朝（972年
            # 至今）」这类朝代行, 实测被抬成 `### 元皇朝（972年至今）` 而与真的分节标题
            # 并列) —— 凡标题与板块标题、文章标题同名, 或形如「某朝（年代区间）」的, 剥成
            # 正文首句不作为标题。
            if re.match(
                    r"^.+（\d{3,4}年(?:\d{1,2}月\d{0,2}日?)?\s*"
                    r"(?:[至—－-]\s*\d{3,4}年(?:\d{1,2}月\d{0,2}日?)?|至今)）$",
                    head):
                out.append("")
                continue
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
    # v51: 半角标点归正 —— 出稿处确定性收口 (模型偶有整篇半角漂移; 此处同时
    # 掐住「开篇正文回贴成纪事摘要」那一路, 见 logs 里 33 处半角的来源)。
    body = llm.normalize_zh_punct(body)
    # 评点剥离后可能残留孤立空行, 压缩
    body = re.sub(r"\n{3,}", "\n\n", body)
    # v70 (用户 2026-09-27 拍板: 「姐姐姐姐一类的重复一起改掉」): 成稿侧相邻重复词闸
    body = _dedup_adjacent_words(body)
    if not saw and body.strip():
        body = f"### {sec_title}\n\n{body}"
    return body


# v57 (问题2b): 名录条目形态 —— 行首「称谓/姓名 (可粗体) + 逗号 + 年月日」。
# 称谓段一律不含句读 (排除「史臣曰：…」这类正文行误命中的可能)。
_ROSTER_ENTRY_RE = re.compile(
    r"^\s*\*{0,2}(?P<label>[^*，,。：:；;！!？?…「」『』《》〈〉“”\"'（）()\[\]【】]"
    r"{1,40}?)\*{0,2}\s*[，,]\s*\d{3,4}年\d{1,2}月\d{1,2}日")
_ARTICLE_HEAD_RE = re.compile(r"^## \d+、")


def _drop_subject_roster_lines(md, facts, articles):
    """v57 (问题2b): 《刺客列传》篇内删掉**传主本人**的名录条目行 (成品兜底, 幂等)。

    该篇人名录恒为「死于主角之手者」, 而传主本人的卒年句与死者条目**同构**
    (粗体称谓 + 日期 + 死因 + 死于 + 年岁), 模型为收束名录会自行续上一条
    (斯卡利茨终传实测: «**秦皇帝撒旦之种施沙米尔**，948年10月6日，误食了一些
    有毒的植物，死于丹徒，年三十七。距其诛席元裕，仅一月又三日。»)。
    事实侧已收根 (`_shared_facts_block` / `_profile_lines` 的 with_death), 此处再保
    一道底线: 只在本篇范围内、且行首为传主称谓或姓名时才删 —— 死者条目、他篇正文
    一字不动。返回 (新 md, 删除行数)。"""
    asa = next((i for i, a in enumerate(articles, 1)
                if (a or {}).get("key") == "assassins"), None)
    if asa is None:
        return md, 0
    p = facts.get("protagonist") or {}
    label = str(p.get("label") or "")
    name = str(p.get("name") or "")
    # 姓名过短 (=2 字) 时只认全称谓, 防「…X甲」这类同名尾缀误伤
    idents = [x for x in (label, name) if x and (x == label or len(x) >= 3)]
    if not label and not name:
        return md, 0
    # 名录内的真死者 (含组内血亲) 一律保留 —— 即便其称谓尾缀与传主姓名相同
    victims = set()
    for k in (facts.get("killed") or []):
        for it in [k] + list((k or {}).get("group") or []):
            for key in ("label", "name"):
                v = str((it or {}).get(key) or "")
                if v:
                    victims.add(v)
    head = f"## {asa}、《{(articles[asa - 1] or {}).get('title') or ''}》"
    out, dropped, inside, sample = [], 0, False, ""
    for ln in md.split("\n"):
        if _ARTICLE_HEAD_RE.match(ln):
            inside = (ln.strip() == head)
            out.append(ln)
            continue
        if inside:
            m = _ROSTER_ENTRY_RE.match(ln)
            if m:
                lab = m.group("label")
                if (lab not in victims
                        and any(lab == nm or (len(nm) >= 3 and lab.endswith(nm))
                                for nm in idents)
                        and ("死" in ln or "卒" in ln or "崩" in ln)):
                    dropped += 1
                    sample = sample or ln.strip()
                    continue
        out.append(ln)
    if dropped:
        llm.log(f"【刺客列传】删除传主本人的名录条目 {dropped} 行 "
                f"(本篇名录只列死于主角之手者): {sample[:60]}")
    return "\n".join(out), dropped


# v84 (用户 2026-09-29 报告「每个 .md 开头标题重复两遍」): 总纲请求按
# `style.PROMPTS["intro_user"]` 的输出格式块, 要求模型**自己**写两行头
# (`# 《X传》` + `家族：…｜人物：…｜生卒：…`), 而本函数随后又按程序口径在正文
# 之前统一加了标题行与 `> 家族：…` 题记行 —— 两者叠在一起, 于是每篇成稿开头
# 出现两遍标题 (v81 及更早的旧稿同样如此, 不是 v83 新引入的回归)。
# 程序口径那两行是权威行 (带「死于…，此为终传」/「<缘由>，此为终传」, 与
# `pipeline.tail_state_applies`、各 verify 断言同一口径), 故保留程序行,
# 只把**总纲开头**由模型另写的那几行剥掉 —— 与 `_normalize_section` v14
# 「正则剔除模型误输出的重复标题 (不动提示词)」同一路数, 逐字相同的条数上限 3 行,
# 且必须形如标题行/题记行, 免得吃掉总纲正文首句。
_INTRO_HEAD_RES = (
    # ① 标题行: 「# 《X传》」/「**《X传》**」/「标题：《X传》」/「## 《X传》」
    re.compile(r"^[>\-*+\s]*#{0,6}[>\-*+\s]*(?:标题|题目)?\s*[：:]?\s*"
               r"《[^》]{1,60}》[>\-*+\s]*$"),
    # ② 题记行: 「家族：…｜人物：…｜…」式 (短行, 且带 ｜…人物：/生卒：/生平：)
    re.compile(r"^[>\-*+]{0,2}\s*\**[^\n｜|]{0,40}[｜|][^\n]{0,8}"
               r"(?:人物|生卒|生平)[：:][^\n]{0,80}$"),
    # ③ 题记行的简版: 整行就以「家族：/人物：」起头
    re.compile(r"^[>\-*+]{0,2}\s*\**(?:家族|人物)[：:][^\n]{0,120}$"),
    # ④ 提示词占位符被模型照抄成的标签行: 「总纲正文：」/「总纲」/「正文」…
    re.compile(r"^[>\-*+]{0,2}\s*\**(?:总纲正文|总纲|正文|传记正文)\s*[：:…]*$"),
)


def _strip_intro_head(intro):
    """剥掉总纲开头模型另写的标题行/题记行 (v84, 幂等)。

    逐行看开头: 空行跳过不计数; 命中「标题行 / 题记行 / 标签行」形状 (①②③④ 之一) 的行
    剥掉, 最多 4 行; 首个非此类行即停 —— 故只动总纲最前面那几行, 正文一字不碰。
    没有可剥的行时原样返回。"""
    intro = intro or ""
    lines = intro.split("\n")
    i, dropped, sample = 0, 0, ""
    while i < len(lines) and dropped < 4:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if not any(r.match(s) for r in _INTRO_HEAD_RES):
            break
        sample = sample or s
        dropped += 1
        i += 1
    if not dropped:
        return intro
    llm.log(f"总纲开头剥掉模型另写的标题/题记行 {dropped} 行 "
            f"(标题与题记由组装侧统一添加): {sample[:60]}")
    return "\n".join(lines[i:]).strip()


def _assemble(facts, intro, leads, sections, articles):
    parts = [f"# 《{facts['protagonist']['name']}传》"]
    p = facts["protagonist"]
    # v14: 家族文本含分家 (藤原氏（北家）)
    house = _house_text(facts)
    death = facts.get("player_death")
    re_end = facts.get("reign_end")            # v76 (问题1): 让位/剃发退位优先
    span = ""
    if re_end:
        span = f"{re_end.get('reason_zh') or '让位'}，此为终传"
    elif death:
        span = f"死于{llm.fmt_cn_date(death.get('date'))}，此为终传"
    else:
        cutoff = facts.get("as_of") or facts.get("last_date")
        span = f"截至{llm.fmt_cn_date(cutoff or '?')}"
    parts.append(f"> 家族：{house}｜人物：{p.get('name')}｜{span}")
    # v28: 不再向读者列出「存档来源：868.1.1 / …（共10份快照）」— 元信息无用
    parts.append("")
    # v84: 总纲开头模型另写的标题行/题记行由 `_strip_intro_head` 剥掉,
    # 只留本函数程序口径的标题行与 `> 家族：…` 题记行 (每篇开头不再重复两遍)。
    parts.append(_strip_intro_head(intro))
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
      「巴沙尔的亲属约书亚去世」/「约书亚死于…」) 按 (日期, 事件语义) 去重, 只保留一条;
      死亡记录优先于亲属去世记忆, 出生事件优先保留主角视角。"""
    lines = []
    gen = facts.get("genealogy") or []
    if gen:
        lines.append("### 世系")
        lines.extend("- " + g for g in gen)
        # v64 (问题3): 家格沿革 (别立家族 / 家族改名) —— 程序直出, 终传附录因此
        # 必然有这一句 (事实面本有 house_history, 旧稿只下发进【传主档案】)。
        for ln in ((facts.get("protagonist") or {}).get("house_history") or []):
            if ln:
                lines.append("- " + ln)
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
        # 事件文本已带「1070年4月9日，」前缀 (v26: 1月1日折叠为「1070年，」),
        # 去掉日期前缀只留事件
        body = re.sub(r"^\d+年\d+月\d+日，?", "", e["text"])
        body = re.sub(r"^\d+年，?", "", body)
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
            # v26: 1月1日 = 年份级日期 (出生日期不详/年度快照), 只写年份
            year_only = (mo == 1 and d == 1)
            if n_year[y] == 1:
                # 全年仅 1 条: 年/月/日合为一行
                for body in bodies:
                    if year_only:
                        lines.append(f"- {y}年 {body}")
                    else:
                        lines.append(f"- {y}年{mo}月{d}日 {body}")
                continue
            if y != last_y:
                lines.append(f"- {y}年")
                last_y = y
                last_mo = None
            if year_only:
                # 年标题已给出, 1月1日不再写月日
                for body in bodies:
                    lines.append(f"  - {body}")
                last_mo = None
                continue
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
    - 去世: 「X的亲属Y去世。」/「X的友人Y去世。」/「X的仇人Y去世。」/「Y死于…」→ ('亡', 'Y去世。')
    - 出生: 「X得长子Y。」/「X添子Y。」/「X得孪生子。」/「X幼子夭折。」→ ('生', 对象)
    - 其余按原文本。"""
    m = re.match(r"^.+?的(?:亲属|友人)(.+去世。)$", body)
    if m:
        return ("亡", m.group(1))
    m = re.match(r"^.+?的仇人(.+去世。)$", body)
    if m:
        return ("亡", m.group(1))
    m = re.match(r"^(.+?)死于(?:\d+年\d+月\d+日|\d+年)", body)
    if m:
        return ("亡", m.group(1) + "去世。")
    m = re.match(r"^.+?(?:得长子|得长女|添子|添女)(.+。)$", body)
    if m:
        return ("生", m.group(1))
    if re.match(r"^.+?得孪生(?:子|女)。$", body):
        return ("生", "孪生子。")
    # v32: 夭折句改写为带生母的「X之妻Y产下死婴。」「X之妻Y孕期提前结束。」
    if re.match(r"^.+?产下死婴。$", body):
        return ("生", "产下死婴。")
    if re.match(r"^.+?流产。$", body):
        return ("生", "流产。")
    if re.match(r"^.+?幼子夭折。$", body):
        return ("生", "幼子夭折。")
    if re.match(r"^.+?婴儿夭折。$", body):
        return ("生", "婴儿夭折。")
    return ("事", body)


def _timeline_event_priority(body, pname):
    """同一事件多视角并存时优先保留哪条: 死亡记录 (信息最全) > 去世记忆 > 其余;
    同层内主角视角 (文本以主角名开头) 优先。"""
    if re.search(r"死于(?:\d+年\d+月\d+日|\d+年)", body):
        tier = 2
    elif re.search(r"的(?:亲属|友人|仇人).+?去世。$", body):
        tier = 1
    else:
        tier = 0
    return tier * 10 + (1 if pname and body.startswith(pname) else 0)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _assassin_sections(n):
    """刺客列传板块 (v11): 按击杀数动态拆纪事 — <30 拆 1 个纪事, 30–59 拆 2 个,
    ≥60 拆 3 个; 每个纪事按死亡先后等分切片 (防提示词过大吃掉模型注意力)。
    v52 (问题4): 1–2 人时开篇改用单人立传要求 (`lead_one`) —— 「诸人群像」
    在只有一名死者时无从落笔。"""
    if n >= 60:
        mids = ["mid1", "mid2", "mid3"]
    elif n >= 30:
        mids = ["mid1", "mid2"]
    else:
        mids = ["mid"]
    lead_req = style.SECTION_REQ["assassins"]["lead"]
    if n <= 2:
        lead_req = (style.SECTION_REQ["assassins"].get("lead_one") or lead_req)
    secs = [{"key": "lead", "title": style.SECTION_TITLES["assassins"]["lead"],
             "req": lead_req}]
    chunk = (n + len(mids) - 1) // len(mids)
    for i, k in enumerate(mids):
        lo, hi = i * chunk, min((i + 1) * chunk, n)
        secs.append({"key": k, "title": style.SECTION_TITLES["assassins"][k],
                     "req": style.SECTION_REQ["assassins"][k],
                     "slice": (lo, hi)})
    return secs


def _chrono_mid_req(base_req, idx, total, periods, last=False, family=False):
    """《历代记》纪事**分段请求**的板块要求 (v73)。

    `base_req` = 「纪事·王朝历代」的整段要求; 这里只在前面接一句**本段范围**的正向
    说明 —— 本段是哪几朝、年代区间、共几段。段界与年代全部由程序给出 (与素材块同一份
    `dynasty_chronicle`), 不留空位让模型猜。"""
    names = [p.get("name") or "" for p in (periods or []) if p.get("name")]
    head = "本请求只写这一节"
    if total > 1:
        head += f"（第{idx + 1}节，共{total}节）"
    head += "。"
    if family:
        head += "本板块写先世诸位统治者的世次与其事迹：" + "、".join(names) + "。"
    else:
        spans = []
        for p in (periods or []):
            _s = str(p.get("start") or "").split(".", 1)[0]
            _e = str(p.get("end") or "").split(".", 1)[0] if p.get("end") else ""
            if _s:
                spans.append(f"{p.get('name') or ''}（{_s}年至{_e or '今'}）")
        head += "本板块写这几朝：" + "、".join(names) + "。"
        if spans:
            head += "年代区间：" + "、".join(spans) + "。"
    if last:
        head += "本板块是本篇末节，收束于传主在位的末年。"
    return head + "\n\n" + (base_req or "")


def _chrono_wars_in(dc, period, prev_cut=None):
    """该节的战事行 (v73): 各节按**兴兵年的先后**切分战事 —— 本节的战事 = 兴兵年落在
    [上一节的段止, 本节的段止) 之内的那些, 末节收全部余下。

    因各朝代的年代区间之间夹着空位期 (群雄争霸) 与未被任何朝代覆盖的年份, 按**本朝
    区间**硬切会把空位期的战事整批丢掉 (实测: 尼克档 19 行战事全在 902–947, 落在唐与
    群雄争霸两段里); 故以「各节段止」为界。"""
    wars = [w for w in ((dc or {}).get("wars") or []) if w]
    if not wars:
        return []
    ps = (period or {}).get("periods") or [period or {}]

    def _yr(s):
        """日期串 → 四位年 (『868.1.1』→ 『868』; 空值 → 空串)。"""
        return str(s or "").split(".", 1)[0]

    cut = ""
    for p in reversed(ps):
        if p.get("end"):
            cut = _yr(p.get("end"))
            break
    lo = _yr(prev_cut)
    out = []
    for w in wars:
        m = re.match(r"^(\d{3,4})年", w)
        yr = m.group(1) if m else ""
        if not yr:
            continue
        if lo and yr < lo:
            continue
        if cut and yr >= cut:
            continue
        out.append(w)
    return out


def _chrono_dedup_wars(wars):
    """同一场战事的双方视角合并为一条 (v73, 纯函数便于单测)。

    记忆里同一战事有两侧各记一条 (「A兴兵讨B」在 A 的档里, 「B应战拒A」在 B 的档里),
    胜负句也互为镜像 (A 侧「战胜B」/ B 侧「败于A」)。键 = (兴兵日, 双方名去序),
    同一键只留**有胜负记载**的那一条 (两条都有则留先见者); 无胜负记载的两侧也合并为一条。"""
    _RE = re.compile(r"^(\d{3,4}年\d{1,2}月\d{1,2}日)(.+?)(?:兴兵讨|应战拒)(.+?)；")
    out, idx = [], {}
    for w in wars:
        if not w:
            continue
        m = _RE.match(w)
        if not m:
            out.append(w)
            continue
        key = (m.group(1), tuple(sorted((m.group(2), m.group(3)))))
        tail = w.split("；", 1)[1] if "；" in w else ""
        won = "战胜" in tail
        j = idx.get(key)
        if j is None:
            idx[key] = len(out)
            out.append(w)
        elif won and "战胜" not in out[j].split("；", 1)[1]:
            out[j] = w
    return out


def _same_period(a, b):
    """两段是否同朝 (按段名 + 段起判定)。

    进快照的事实面经 JSON 往返后, `current` 与 `periods` 里那一条**不再是同一个对象**,
    按 `is` 判定会把本朝算成「前方各朝」而把同一朝写两遍 (富兰克林档实测)。"""
    if not a or not b:
        return False
    return (a.get("name"), a.get("start")) == (b.get("name"), b.get("start"))


def _chrono_usable(p):
    """该朝是否够料独立成节 (v73): 「一人一行」下只有一位统治者时, 该节除
    即位/生卒/在位之外无他事可写, 模型必以虚构填满 —— 故要求 ≥2 位统治者
    (用户拍板: 「如果该头衔由主角创建，并且历史只有主角一个人，则同样不生成历代记，
    否则没东西写」, 同一口径推广到先世各朝)。"""
    return len([r for r in (p.get("rows") or []) if r]) >= 2


def _chrono_row_chunks(p, per=None):
    """把一个朝代按**人数**切成 ≤per 人一段 (v82 用户口径: 称号取最后的称号)。

    为什么需要: 分篇旧稿只按**朝代**切, 单朝十六主的档 (田所 日本政权 868–1006)
    于是只成一段 —— 一次请求要写十六个人。实测两种走样: 1007 档那次写到第 11 人
    就收笔 (久荫、宣方、传主本人全都没写), 1006 档这次干脆收成一篇总说
    (传主与久荫的头衔变化「幕府将军 / 上皇」因此一个字也没落到纸上)。
    按人切段后每段 4 人, 与「篇幅要求 1200–1800 字」相称; 各段的年代区间取自
    事实层逐行的即位日 (`rows_dates`), 战事切片 (`_chrono_wars_in`) 随之变准。

    每段沿用该朝之名; 段止取**下一段首人的即位日** (末段沿用该朝段止)。"""
    rows = [r for r in (p.get("rows") or [])]
    if not rows:
        return [p]
    per = max(1, int(per or getattr(F, "CHRONICLE_ROWS_PER_SECTION", 4)))
    if len(rows) <= per:
        return [p]
    dates = list(p.get("rows_dates") or [])
    ids = list(p.get("rows_ids") or [])
    dets = list(p.get("rows_detail") or [])
    out = []
    for i in range(0, len(rows), per):
        chunk = rows[i:i + per]
        seg = dict(p)
        seg["rows"] = chunk
        seg["rows_detail"] = dets[i:i + per] if len(dets) >= len(rows) \
            else [None] * len(chunk)
        seg["rows_dates"] = dates[i:i + per] if len(dates) >= len(rows) else []
        seg["rows_ids"] = ids[i:i + per] if len(ids) >= len(rows) else []
        if seg["rows_dates"]:
            seg["start"] = seg["rows_dates"][0]
        j = i + per
        if j < len(rows) and len(dates) >= j + 1:
            seg["end"] = dates[j]
        out.append(seg)
    if out:
        out[-1]["end"] = p.get("end")
    return out


def _chrono_split(periods, cap=None):
    """把各朝尽量等分成 ≤cap 节 (v73; cap 缺省取 `facts.CHRONICLE_MID_MAX`)。

    v82: 先按人把过长的朝代切段 (`_chrono_row_chunks`), 再按 cap 等分归并。
    返回**合并后的段**: 每段的 `name` 是所含各朝名 (「唐皇朝、群雄争霸」), `start`/`end`
    取该段首尾 (与素材块的段界同源)。只有一段时不再拆。"""
    ps = []
    for p in (periods or []):
        if _chrono_usable(p):
            ps.extend(_chrono_row_chunks(p))
    if not ps:
        return []
    cap = max(1, int(cap if cap is not None
                     else getattr(F, "CHRONICLE_MID_MAX", 4)))
    n = max(1, min(cap, len(ps)))
    base, extra = divmod(len(ps), n)
    out, i = [], 0
    for k in range(n):
        m = base + (1 if k < extra else 0)
        chunk = ps[i:i + m]
        i += m
        if not chunk:
            continue
        out.append({
            "name": "、".join(p.get("name") or "" for p in chunk),
            "start": chunk[0].get("start"),
            "end": chunk[-1].get("end"),
            "ids": [x for p in chunk for x in (p.get("ids") or [])],
            "rows": [r for p in chunk for r in (p.get("rows") or [])],
            # v82: 「此行三样俱全」与 rows 一一对应 (旧快照无此键时按行数补齐 None,
            # 由 `_article_facts` 回退到旧的「｜」个数判据)。
            "rows_detail": [d for p in chunk
                            for d in (p.get("rows_detail")
                                      or [None] * len(p.get("rows") or []))],
            "periods": chunk})
    return out


def _mid_req_for_group(base_req, idx, total, group):
    """《家室列传》纪事**分组请求**的板块要求 (v63 问题2; v74 问题1 分两档)。

    `base_req` = 该类板块的整段要求 (含篇幅与主旨); 这里只在前面接一句**本组范围**
    的正向说明:
      · 妻妾节 (`kind == "spouse"`) —— 本请求只写这一房 (配偶 + 其所出的婴幼儿);
      · 子女节 (`kind == "child"`)  —— 本请求只写这一名/这一组子女的成年行迹。
    人数与关系全部由程序给出, 不留空位让模型猜。"""
    label = (group or {}).get("label") or ""
    kids = list((group or {}).get("children") or [])
    kind = (group or {}).get("kind") or "spouse"
    mates = list((group or {}).get("mates") or [])
    names = [str(x) for x in ((group or {}).get("names") or []) if x]
    who = "、".join(names) if names else label
    head = ""
    if kind == "child":
        head = f"本请求只写这一组子女：{who}"
        if total > 1:
            head += f"（第{idx + 1}节，共{total}节）"
        head += "。"
        if len(kids) > 1:
            head += (f"本组子女共{len(kids)}人，已随本组档案一并给出；"
                     "本板块逐人写其受任、婚配、子嗣与家门之事。")
        else:
            head += ("本板块写这一名子女的成年行迹：受任何职、与何人成婚、"
                     "已育子女，以及其与父母的往来。")
    else:
        head = f"本请求只写这一房：{label}"
        if total > 1:
            head += f"（第{idx + 1}节，共{total}节）"
        head += "。"
        head += f"本房为{who}。"
        if len(mates) > 1:
            head += (f"本房含{len(mates)}位妻妾，已随本组档案一并给出；"
                     "本板块逐人写其结缡、情事与家门之事。")
        if kids:
            head += (f"这一房所出的未成年子女共{len(kids)}人，"
                     "已随本组档案一并给出；本板块写这一房的夫妻、子女与其家门之事。")
        elif len(mates) <= 1:
            head += "本板块写这一房夫妻与其家门之事。"
    return head + "\n\n" + (base_req or "")


# ---------------------------------------------------------------------------
# v88 (问题1/P1): 篇目上限与「按素材量/重要性出篇」
# ---------------------------------------------------------------------------
# 用户 2026-10-01 拍板: 「加入上限, 最多十篇, 按照重要性决定是否生成该板块
# (比如如果仇人和朋友记忆很少就不生成, 没有礼仪写就不写礼仪)」。
#
# `ARTICLE_MAX` = 一传的篇目上限。第 3 个十年传记曾正好凑到 10 篇, 而
# `build_intro_messages` 的序号表只有 9 个汉字 ⇒ 整篇生成失败 (见 `_cn_index`)。
# 上限与序号一并解决: 上限 10 篇, 序号支持到 99。
ARTICLE_MAX = 10
# 好友/仇人列传的**出篇门槛**: 该传主本人（好友或仇人）在档案里的行迹条数。
# 实测 (既有 30 余份快照): 行迹 1–2 条的列传只能靠模型铺陈 —— 斯卡利茨第 1–3 个
# 十年即此例 (仇人行迹 2/1/2 条), 故门槛取 3。
SUBJECT_ART_MIN_EVENTS = 3
# 篇目优先级 (越大越先保留)。只在上限被顶满时起作用; 挑选后仍按原有相对次序排列。
# 次序依据: 本纪/家室是骨, 刺客列传与阴私录是本项目投入最重的两条戏剧线,
# 好友/仇人列传是原始五篇之一; 群英录与朝局/历代记重叠最多, 故排在末位。
_ARTICLE_PRIO = {
    "benji": 100,      # 本纪 (必出)
    "jiashi": 90,      # 家室列传 (必出)
    "assassins": 84,   # 刺客列传·刀下诸魂
    "secrets": 82,     # 阴私录·隐事秘辛
    "friend": 80,      # 列传·好友
    "enemy": 80,       # 列传·仇人
    "feuds": 76,       # 家族恩怨录
    "artifacts": 74,   # 宝物志
    "liyi": 72,        # 礼仪志
    "chaoju": 70,      # XX历代记 (仅终传)
    "youxia": 68,      # 游侠列传 (仅无地)
    "qizu": 60,        # 妻族传·帝胄姻亲
    "qunying": 50,     # 群英录·朝堂要员
}


def _subject_has_material(facts, cid):
    """好友/仇人列传是否有料: 该传主本人的行迹条数 ≥ `SUBJECT_ART_MIN_EVENTS`。

    取的是列传正文实际用的那口 (`facts.characters[<cid>].events`,
    见 `_subject_facts`/`_article_facts`), 不是估计值。档案缺席 (该 id 未进
    `_profile_needed_ids`) 时按无料处理 —— 那一篇本来就无正文可写。"""
    if cid is None:
        return False
    p = (facts.get("characters") or {}).get(str(cid)) or {}
    return len(p.get("events") or []) >= SUBJECT_ART_MIN_EVENTS


def _liyi_has_material(facts):
    """《礼仪志》出篇门槛 (v88 问题3/P3-A, 用户「没有礼仪写就不写礼仪」)。

    要求宗教面有**可系年的事**, 四者任一:
      · 礼仪沿革 ≥2 段 (改礼/立礼 —— 1 段只是「他一直奉某礼」, 不构成事件);
      · 个人教义的变更点 ≥2 (始奉之外还有放弃/改奉);
      · 修会 (亲立/领地内同信仰者, 已按 as_of 截断, 见 `facts.holy_order_lines`);
      · 禁忌个人信条 (见 `facts.forbidden_tenet_lines`)。
    全无者不出该篇 —— 他的个人教义仍会写进自己的档案行 (P3-A-⑤), 信息不丢。

    v89 (问题4): **本礼教义更替不单独作门槛** —— 那三条教义只有本礼礼仪领袖能改,
    可能是别国的礼仪领袖改的 (本档实测 878 年就是教宗色尔爵三世改的罗马礼),
    不是传主本人的行迹; 它只在《礼仪志》已因别的理由立起时, 进纪事当一块料
    (见 `_liyi_has_mid`)。"""
    if not (facts.get("rite") or facts.get("rite_profile")):
        return False
    return len(facts.get("rite_history") or []) >= 2 \
        or len(facts.get("personal_tenets") or []) >= 2 \
        or bool(facts.get("holy_orders")) \
        or bool(facts.get("forbidden_tenets"))


def _liyi_has_mid(facts):
    """《礼仪志》纪事 (mid) 是否有料: 个人教义沿革 / 修会 / 礼仪沿革 / 本礼教义沿革 /
    禁忌个人信条, 五者任一。

    开篇与纪事按模块切片、**两块料不相交** (v27 口径): 开篇给「他是谁」(礼仪档案),
    纪事给「发生了什么事」(个人教义沿革 + 修会 + 礼仪沿革 + 本礼教义沿革 + 禁忌信条)。
    v89 (问题4/5): 加「本礼教义沿革」, 删「门下教众」(廷臣个人教义无收录意义)。
    v90 (问题5, 用户 2026-10-02 拍板): 「个人教义沿革」与「修会」移入纪事, 门槛同步
    —— 出篇门槛 (`_liyi_has_material`) 的任一条件都落在纪事里, 故本事恒有纪事板块。"""
    return bool(facts.get("personal_tenets")) \
        or bool(facts.get("holy_orders")) \
        or bool(facts.get("rite_history")) \
        or bool(facts.get("rite_tenet_changes")) \
        or bool(facts.get("forbidden_tenets"))


def _apply_article_cap(articles):
    """篇目上限 (v88 问题1/P1): 超限时按 `_ARTICLE_PRIO` 留前 N, 其余略去并落日志。

    实现取「按优先级挑下标 → 下标升序还原」: 挑选只决定**去留**, 不改变**
    原有相对次序**, 故未超限时输出与本轮之前逐字相同。"""
    n = len(articles)
    if n <= ARTICLE_MAX:
        return articles
    keep = sorted(range(n),
                  key=lambda i: (-_ARTICLE_PRIO.get(articles[i]["key"], 0), i))
    keep = sorted(keep[:ARTICLE_MAX])
    dropped = [articles[i]["title"] for i in range(n) if i not in set(keep)]
    llm.log(f"[篇目] 候选 {n} 篇超过上限 {ARTICLE_MAX}，"
            f"按重要性保留 {ARTICLE_MAX} 篇，略去: {'、'.join(dropped)}")
    return [articles[i] for i in keep]


def build_articles(facts, cache, cfg):
    """按 cfg.bio_sections 组装文章列表 (标题含主角/好友/仇人姓名)。
    v5: 动态追加 刺客列传/游侠列传/妻族传/群英录 (依数据条件)。

    v88 (问题1/P1, 用户 2026-10-01 拍板「加入上限, 最多十篇, 按重要性决定是否生成该
    板块」): 本函数末尾统一做两件事 ——
      ① **按素材量出篇**: 好友/仇人列传要求传主本人**至少 `SUBJECT_ART_MIN_EVENTS`
         条行迹**, 《礼仪志》要求宗教面有可系年的事 (`_liyi_has_material`);
      ② **总量上限 `ARTICLE_MAX`**: 候选多于上限时按 `_ARTICLE_PRIO` 取前 N 名,
         被略去的篇目写进日志。取「按优先级挑选 → 再按原有相对次序排列」,
         故不超上限时篇目与次序与本轮之前逐字相同。"""
    pid = facts.get("player_id")
    pname = (facts["protagonist"] or {}).get("name") or "主角"
    style_name = facts.get("bio_style") or "east"
    friend, friend_fallback = _pick_friend(cache, as_of=facts.get("as_of"))
    if friend is not None and friend_fallback:
        friend = None  # v16: 无真好友时列传删去 — 同朝共事者代打只是复述主角故事
    enemy = _enemy_for_facts(facts, cache)
    fname = ""
    ename = ""
    if friend is not None:
        fp = facts["characters"].get(str(friend)) or {}
        fname = fp.get("name") or ""
    if enemy is not None:
        ep = facts["characters"].get(str(enemy)) or {}
        ename = ep.get("name") or ""
    sec_keys = [s for s in ("lead", "mid")]  # v11: 尾段 (评曰) 全部删去, 太史公曰只留总纲
    # v60 (问题3): 《家室列传》按素材改口 —— 判据一次性算好 (见 _jiashi_variant)
    facts["_jiashi_variant"] = _jiashi_variant(facts, cache)

    def mk_sections(key):
        titles = style.SECTION_TITLES.get(key, {})
        _var = (style.JIASHI_VARIANTS.get(facts.get("_jiashi_variant") or "")
                if key == "jiashi" else None)
        if _var:
            titles = dict(titles)
            titles["lead"] = _var["lead_title"]
            titles["mid"] = _var["mid_title"]
        defaults = {"lead": "开篇", "mid": "纪事"}
        # v63 (问题2, 用户拍板): 《家室列传》纪事**按门庭分组**逐组成篇。
        # v74 (问题1, 用户 2026-09-27 拍板): 分组改为两段式 ——
        # 「妻妾节 (门庭恩怨·<配偶>)」与「子女节 (诸子行迹·<子名>)」共
        # `facts.JIASHI_MID_MAX` = 5 节 (连开篇共 6 篇), 名额按素材权重在两池间分配。
        # 无分组 (无配偶无子女) 时回落单块。
        if key == "jiashi":
            groups = facts.get("household_groups") or []
            mid_title = titles.get("mid") or defaults["mid"]
            kid_title = "诸子行迹"
            mid_req = _section_req((_var or {}).get("mid")
                                   or style.SECTION_REQ.get(key, {}).get("mid")
                                   or "按传记笔法写作。", facts)
            kid_req = _section_req((_var or {}).get("kid")
                                   or style.SECTION_REQ.get(key, {}).get("kid")
                                   or "按传记笔法写作。", facts)
            secs = [{"key": "lead",
                     "title": titles.get("lead") or defaults["lead"],
                     "req": _section_req(
                         (_var or {}).get("lead")
                         or style.SECTION_REQ.get(key, {}).get("lead")
                         or "按传记笔法写作。", facts)}]
            if groups:
                for i, g in enumerate(groups):
                    _kind = g.get("kind") or "spouse"
                    _is_kid = _kind == "child"
                    secs.append({
                        "key": (f"kid{i + 1}" if _is_kid else f"mid{i + 1}"),
                        "title": "%s·%s" % (
                            (kid_title if _is_kid else mid_title),
                            g.get("label") or ("第%d节" % (i + 1))),
                        "req": _mid_req_for_group(
                            kid_req if _is_kid else mid_req, i, len(groups), g),
                        "members": list(g.get("ids") or []),
                        "block_title": f"家室档案·{g.get('label') or ''}",
                    })
            else:
                secs.append({"key": "mid",
                             "title": mid_title, "req": mid_req})
            return secs
        if key == "chaoju":
            # v70 (用户 2026-09-27 拍板): 《XX历代记》纪事板块整块删除 (朝局动态的复现
            # 路径), 只留「王朝历代」一个板块。
            # v73 (用户 2026-09-27 拍板「内容太短 → 扩充 + 分篇并发」): 素材扩到「一人
            # 一行」之后**按朝代分节并发** —— 本朝单独成末节 (「续篇」), 前方各朝尽量
            # 等分成 ≤`facts.CHRONICLE_MID_MAX` 节 (上/中/下), 每节一个独立请求,
            # 由 `generate_biography` 既有的第二波 ThreadPool 与其余篇目一起并发发出。
            # 只创建且仅有传主一人的头衔改走**家族历代记** (先世 → 传主), 板块名同步改口。
            _dc = (facts.get("realm") or {}).get("dynasty_chronicle") or {}
            _periods = list(_dc.get("periods") or [])
            _fam = bool(_dc.get("family"))
            _src = style.SECTION_REQ.get(key, {})
            _lead_req = _section_req((_var or {}).get("lead") or _src.get("lead")
                                     or "按传记笔法写作。", facts)
            _mid_base = _section_req((_var or {}).get("mid") or _src.get("mid")
                                     or "按传记笔法写作。", facts)
            _ttl = dict(titles)
            if _fam:
                _ttl["lead"] = _ttl.get("family_lead") or _ttl.get("lead")
            secs = [{"key": "lead",
                     "title": _ttl.get("lead") or defaults["lead"],
                     "req": _lead_req}]
            if _fam:
                secs.append({"key": "mid", "title": _ttl.get("family_mid") or "纪事",
                             "req": _mid_base, "periods": _periods})
            else:
                # 各朝 (含本朝) 按「尽量等分 + 末节留本朝」分节; 只有一段时就是单节。
                _cur = _dc.get("current") or {}
                _all = [p for p in _periods if _chrono_usable(p)]
                if _cur.get("rows") and _cur not in _all:
                    _all.append(_cur)
                _hist = [p for p in _all
                         if not (_same_period(p, _cur))]
                _cap = max(1, int(getattr(F, "CHRONICLE_MID_MAX", 4)))
                if _cur.get("rows") and _hist:
                    _parts = _chrono_split(_hist, cap=_cap - 1)
                    # v82: 本朝同样按人切段 (末段带 mid_last 要求, 收束于传主末年)
                    for _cp in _chrono_row_chunks(_cur):
                        _parts.append({
                            "name": _cp.get("name"), "start": _cp.get("start"),
                            "end": _cp.get("end"), "ids": list(_cp.get("ids") or []),
                            "rows": list(_cp.get("rows") or []),
                            "rows_detail": list(_cp.get("rows_detail") or []),
                            "rows_dates": list(_cp.get("rows_dates") or []),
                            "periods": [_cp]})
                else:
                    # 本朝是唯一的朝代 (单朝单君/单朝多君): 全篇只有一个纪事节,
                    # 不再分出「前方各朝」—— 免得同一朝写两遍 (富兰克林档实测)。
                    _parts = _chrono_split(_all, cap=_cap)
                _n = len(_parts)
                _prev_cut = None
                for _i, _p in enumerate(_parts):
                    _last = _i == _n - 1
                    _base = (_section_req(style.SECTION_REQ.get(key, {}).get(
                        "mid_last"), facts) if (_last and _n > 1) else _mid_base)
                    _sec = {
                        "key": "mid%d" % (_i + 1),
                        "title": _ttl.get("mid%d" % (_i + 1)) or f"纪事·王朝历代·{_i + 1}",
                        "req": _chrono_mid_req(_base, _i, _n, [_p],
                                               last=(_last and _n > 1 and _p is _parts[-1]
                                                     and bool(_cur.get("rows")))),
                        "periods": [_p], "prev_cut": _prev_cut}
                    secs.append(_sec)
                    _prev_cut = _p.get("end") or _prev_cut
            return secs
        return [{
            "key": sk,
            "title": titles.get(sk) or defaults[sk],
            "req": _section_req(
                       (_var or {}).get(sk)
                       or style.SECTION_REQ.get(key, {}).get(sk)
                       or "按传记笔法写作。", facts),
        } for sk in sec_keys]
    articles = [
        {"key": "benji", "title": f"本纪·{pname}", "subject": None,
         "theme": "人物生平",
         "focus": "以公开行迹为限：家世、执掌之地、战和囚狱、家门添丁",
         "sections": mk_sections("benji")},
    ]
    # v88 (问题1/P1): 好友/仇人列传按素材量出篇 —— 该传主本人行迹少于
    # `SUBJECT_ART_MIN_EVENTS` 条时整篇略去 (用户: 「如果仇人和朋友记忆很少就不生成」)。
    if friend is not None and not _subject_has_material(facts, friend):
        llm.log(f"[篇目] 好友 {friend} 行迹不足 {SUBJECT_ART_MIN_EVENTS} 条，"
                f"《列传·{fname or '好友'}》整篇略去")
        friend = None
    if enemy is not None and not _subject_has_material(facts, enemy):
        llm.log(f"[篇目] 仇人 {enemy} 行迹不足 {SUBJECT_ART_MIN_EVENTS} 条，"
                f"《列传·{ename or '仇人'}》整篇略去")
        enemy = None
    if friend is not None:
        articles.append({"key": "friend", "title": f"列传·{fname or '好友'}",
                         "subject": fname, "theme": "好友传记（最亲近同僚的一生）",
                         "focus": "以传主生平为限，主角只在二人交游处出场",
                         "sections": mk_sections("friend")})
    if enemy is not None:
        articles.append({"key": "enemy", "title": f"列传·{ename or '仇人'}",
                         "subject": ename, "theme": "仇人传记（一生劲敌）",
                         "focus": "以传主一生行迹与结仇由头为限，客观平实",
                         "sections": mk_sections("enemy")})
    # v60 (问题3): 家室列传的题面随素材改口 (theme/focus 与板块要求同分支) ——
    # 无正妻、无子女者若仍收「妻室子女的门庭画卷」「子女来历与血脉之争」,
    # 模型照样会为这行题面造出一屋子妻儿。
    _jv = style.JIASHI_VARIANTS.get(facts.get("_jiashi_variant") or "") or {}
    articles.extend([
        {"key": "jiashi", "title": "家室列传", "subject": None,
         "theme": _jv.get("theme") or "妻室子女的门庭画卷",
         "focus": _jv.get("focus") or "写门庭内情：结缡、情事脉络、子女来历与血脉之争",
         "sections": mk_sections("jiashi")},
    ])
    # v68 (问题1, 用户拍板): 《朝局风云录》改为《XX历代记》—— 以主角当前最高头衔
    # (无真领地而有家业者取其最高领主的头衔) 从**战役起点**以来的历代为纲
    # (v69: 每朝一行, 该朝历代由老到新并写明即位缘由)。头衔无从取得 (仅冒险者营地)
    # 时**整篇略去** (事实层不发 top_title_history ⇒ 无处可写, 不留给模型补白)。
    # v73 (用户 2026-09-27 拍板): 该头衔由主角创建且历代只有主角一人 → 改《XX家历代记》
    # (从祖上最早一位统治者写到传主); 此时取不到有头衔的父/母 (自定义角色) → 该篇不生。
    _rlm = facts.get("realm") or {}
    _dc = _rlm.get("dynasty_chronicle") or {}
    _ttn = _rlm.get("top_title_name") or ""
    # v73 (用户 2026-09-27 拍板): 本篇只在**终传**触发 (事实层 `_is_final_bio` 已按
    # 「decade 为空 + 有卒日 + 本篇截止日正是卒日」收口; 此处按篇目复核一道)。
    try:
        _final = bool(F._is_final_bio_spec(facts))
    except Exception:
        _final = False
    if _final and (_ttn or _dc):
        _fam = bool(_dc.get("family"))
        _ttl = (_dc.get("name") or _ttn) if _fam else _ttn
        _t_fam = "家族历代" if _fam else "王朝的历代承继与改朝换代"
        _f_fam = ("以先世的世次与所执头衔为纲，写家世累代与传主的兴起"
                  if _fam else
                  "以各朝代的起止与历代即位缘由为纲，写改朝换代、疆域归并与主角的升沉")
        articles.append(
            {"key": "chaoju", "title": f"{_ttl}历代记", "subject": None,
             "theme": _t_fam, "focus": _f_fam,
             "sections": mk_sections("chaoju")})
    # v9: 家族恩怨录 / 宝物志 — 插在中间 (家室列传之后, 朝局风云录之前)
    if facts.get("house_feuds"):
        articles.insert(4, {"key": "feuds", "title": "家族恩怨录",
                            "subject": None,
                            "theme": "与主角家族关系不和的家族恩怨",
                            "focus": "写仇怨的来龙去脉：开战、胜负、夺地、对方处境与关系档位",
                            "sections": mk_sections("feuds")})
    if facts.get("family_artifacts"):
        articles.insert(5, {"key": "artifacts", "title": "宝物志",
                            "subject": None,
                            "theme": "主角家族所藏重宝的流转历史",
                            "focus": "写每件重宝的来历与流转，以物见人",
                            "sections": mk_sections("artifacts")})
    # v5: 刺客列传 (主角击杀 ≥1 人); v11: 按击杀数动态拆纪事板块
    # (<30 不拆 1 个纪事; 30–59 拆 2 个; ≥60 拆 3 个; 已剔除 lowborn)
    killed = facts.get("killed") or []
    if _has_assassins(facts):
        articles.append({
            "key": "assassins", "title": "刺客列传·刀下诸魂",
            "subject": None, "theme": f"被主角所杀 {len(killed)} 人的合传",
            "focus": "为每名死者立小传：其生平、与主角的交集、死时情状",
            "sections": _assassin_sections(len(killed))})
    # v5: 游侠列传 (无地冒险者)
    if facts.get("protagonist", {}).get("landless"):
        articles.append({
            "key": "youxia", "title": "游侠列传·行纪",
            "subject": None, "theme": "萍踪浪迹的漂泊行纪",
            "focus": "按行纪次序写漂泊：每至一地的时间、所驻之地、与当地势力的交集",
            "sections": mk_sections("youxia")})
    # v5: 妻族传 (妻妾含公主头衔/中华皇帝之女·姐妹)
    if facts.get("imperial_spouses"):
        articles.append({
            "key": "qizu", "title": "妻族传·帝胄姻亲",
            "subject": None, "theme": "妻族门第 (公主头衔/中华皇帝之女·姐妹)",
            "focus": "写妻族门第与姻亲牵连 (含妻室自身的经历)",
            "sections": mk_sections("qizu")})
    # v5: 群英录 (行政制角色)
    if facts.get("protagonist", {}).get("government") and \
            _is_admin(facts):
        articles.append({
            "key": "qunying", "title": "群英录·朝堂要员",
            "subject": None, "theme": "同朝要员的群像",
            "focus": "写同朝要员的名录与浮沉，以主角为坐标",
            "sections": mk_sections("qunying")})
    # v28: 阴私录 (条件生成 — 有非谋杀隐事 / 家人近臣隐事 / 把柄 才开篇,
    # 避免「27 桩谋杀之秘」这类只与《刺客列传》重复的战役白付两次调用)
    if (facts.get("secrets") or {}).get("any"):
        articles.append({
            "key": "secrets", "title": "阴私录·隐事秘辛",
            "subject": None, "theme": "隐事与把柄 (主人公不为人知的一面)",
            # v35 (问题2): 旧 focus 写「自何时见载」, 与板块要求一起逼模型产出
            # 「见载年」这一元数据; 数据给不齐时就编出「本篇未著其年」。现只写话题,
            # 年份由事实层的「N年见于记载」给足。
            "focus": "写隐事的揭底：何事、涉及何人、事在何年、有谁知情",
            "sections": mk_sections("secrets")})
    # v86 (用户 2026-09-30 拍板): 十年传记与终传都出《礼仪志》(传主所奉礼仪 +
    # 个人教义转变 + 宗教热情/灵性满足); v87 起《教会志》整篇删除 (见本节末注释)。
    # v87 (问题3/7): 删圣所圣髑与教义计数行。
    # v88 (问题3/P3-A, 用户 2026-10-01 拍板): **删「允许/禁止教义」整块** (礼仪级
    # 静态池, 非传主所选 —— 见 `_liyi_has_material` 注释), 纪事改用「礼仪沿革 +
    # 禁忌个人信条 + 门下教众的个人教义」; 并加**素材门槛**: 宗教面无实据者整篇不出
    # (用户: 「没有礼仪写就不写礼仪」)。
    if _liyi_has_material(facts):
        # 线序: 紧跟《家室列传》(及其后的恩怨录/宝物志), 在《历代记》之前
        _anchor = 0
        for _i, _a in enumerate(articles):
            if _a.get("key") in ("jiashi", "feuds", "artifacts"):
                _anchor = _i + 1
        # 纪事无料时只出开篇 (开篇/纪事两块料不相交, 见 `_liyi_has_mid`)
        _secs = mk_sections("liyi")
        if not _liyi_has_mid(facts):
            _secs = _secs[:1]
        articles.insert(_anchor, {"key": "liyi", "title": "礼仪志·礼仪与教义",
                                  "subject": None,
                                  "theme": "传主所受之礼与个人教义的演变",
                                  "focus": "写礼仪的沿革与教门中的作为：受礼、改礼、"
                                           "立礼、个人教义之更替、本礼核心教义之更替、"
                                           "他所亲立或庇护的修会",
                                  "sections": _secs})
    elif facts.get("rite_profile"):
        llm.log("[篇目] 宗教面无实据 (无改礼、无信条更替、无修会、无禁忌信条)，"
                "《礼仪志》整篇略去 (本礼教义更替单独不作门槛, 见 `_liyi_has_material`)")
    # v87 (问题5, 用户 2026-09-30 拍板): **删《教会志》整篇** —— 其素材全部来自
    # 基督教教会情境 (`the_christian_church`), 而该局势只在 867 开局出现
    # (游戏 `on_action/game_start.txt` 无其 start_situation; 脚本唯一发端是调试互动
    # `00_debug_interactions.txt:4821`; 局面注释见 `pam_christian_situation.txt:288`),
    # 且「当今之局/众望所归/主流之礼」一层对传记无实义。
    # v88 (问题1/P1): 统一上限 —— 候选多于 `ARTICLE_MAX` 时按 `_ARTICLE_PRIO` 取前 N。
    return _apply_article_cap(articles)

def _is_admin(facts):
    """行政制判定: 主角政府为 administrative (行政官制)。"""
    gov = (facts["protagonist"] or {}).get("government") or ""
    return gov in ("行政官制", "administrative_government")


def _names_path(cfg, cache):
    """人名表路径 (v28): 优先**本战役文件夹**内的一份 (output/<家族>/data/names.json),
    没有才用全局 data/names.json。全局表按角色 id 索引、可能来自另一场战役
    (id 只在同一存档内有意义), 战役内表由 `build_names.py <melt>` 生成。"""
    folder = (cache or {}).get("output_folder") or ""
    if folder:
        p = os.path.join(cfg.get("output_dir", ""), folder, "data", "names.json")
        if os.path.isfile(p):
            return p
    return os.path.join(cfg.get("data_dir", ""), "names.json")


def reign_start(cache):
    """该传主的**即位日** (v55-7): 存档 `played_character.legacy` 链里本人的 date。

    链逐档入库为 `cache["played_legacy"]`, 形如
    `[{cid:15403, date:'867.1.1'}, {cid:33572063, date:'918.10.19'},
      {cid:16801023, date:'923.1.14'}]` —— 本人的 date 即其继位日
    (父崩当日继位者与前任死期同日)。此值写进 md 头部注释的「执政」字段,
    供 htmlview 按**执政顺序**排角色与下拉框 (生年只是兜底近似)。

    缺链 / 本人不在链中 → 返回 '' (头部略去该字段, 阅读页回退生年)。"""
    pid = cache.get("player_id")
    if pid is None:
        return ""
    try:
        want = int(pid)
    except (TypeError, ValueError):
        return ""
    for e in cache.get("played_legacy") or []:
        if isinstance(e, dict) and e.get("cid") == want:
            return str(e.get("date") or "")
    return ""


def generate_biography(cache, melt, cfg, out_path=None, decade=None, as_of=None,
                       nickname_override=None, campaign=None):
    """生成传记 Markdown 并写入 out_path。返回 (md_text, facts, articles)。
    decade: 十年传记序号 (第N个十年), None 表示终传或普通在世传记。
    as_of (v11): 数据截止日期 — 十年传记传十年末, 官职/历任/时间线/朝局按此截断。
    nickname_override (v20): {cid: 绰号} — 十年传记按时代取绰号, 防重跑漂移。
    campaign (v44): 同战役全部传主缓存 {player_id: cache} — 传主链事实源。"""
    names_path = _names_path(cfg, cache)
    facts = F.build_facts(cache, melt, names_path, as_of=as_of, decade=decade,
                          nickname_override=nickname_override, campaign=campaign)
    articles = build_articles(facts, cache, cfg)

    intro_cfg = dict(cfg)
    intro_cfg["max_tokens"] = min(cfg.get("max_tokens", 12800), 1500)
    intro = llm.call_deepseek(build_intro_messages(facts, cfg, articles),
                              intro_cfg).strip()
    intro = llm.clean_number_spaces(intro)
    intro = llm.normalize_zh_punct(intro)
    # v52 (问题1): 总纲要逐字注入各篇开篇 —— 注入前把与人名对不上的亲属词改回
    # (「母亲X」而 X 是妻室 → 「妻子X」), 防一处口误变成全篇 6 次"事实"。
    intro = _fix_kin_roles(intro, facts, cache)
    # v80 (点6, 附带B): 再把被模型改错的名字改回来 (「六角妻子」→「六角继子」)
    intro = _fix_person_names(intro, facts, cache)

    sec_cfg = dict(cfg)
    sec_cfg["max_tokens"] = min(cfg.get("max_tokens", 12800), 4000)

    def _draft_section(msg, sec_title, article_title):
        """生成一个板块正文, 并做 v71 尾部完整性检查 (`_tail_issue`)。

        残句停在开括号 / 强调符未闭合 = 上游把正文截断 (llm 侧已按 finish_reason
        重试过, 见 `llm.call_deepseek`), 此处再整段重生成一次; 仍不完整则只裁掉
        尾部残留的开括号并落日志 —— 半截正文绝不当完成稿静默收下。"""
        def _one(text):
            # v52 (问题1): 成稿正文同做亲属词归正 (紧贴人名的错词才改)
            body = _fix_kin_roles(
                _normalize_section(text, sec_title, article_title), facts, cache)
            # v80 (点6): 同做名字归正 (错名在正文里同样要改回)
            body = _fix_person_names(body, facts, cache)
            return body, _tail_issue(body)

        body, issue = _one(llm.call_deepseek(msg, sec_cfg).strip())
        if not issue:
            return body
        llm.log(f"板块《{sec_title}》末尾不完整 ({issue}) — 重生成一次")
        body2, issue2 = _one(llm.call_deepseek(msg, sec_cfg).strip())
        if not issue2:
            return body2
        llm.log(f"板块《{sec_title}》重生成后仍不完整 ({issue2}) — 裁尾部残迹, 该板块请复核")
        b1, _ = _trim_dangling_tail(body)
        b2, _ = _trim_dangling_tail(body2)
        return b2 if len(b2) >= len(b1) else b1

    def _gen_lead(article):
        try:
            msg = build_lead_messages(article, facts, cache, intro, cfg)
            body = _draft_section(msg, article["sections"][0]["title"],
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
            body = _draft_section(msg, section["title"], article["title"])
            return article["key"], section["key"], body
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
    # v57 (问题2b): 《刺客列传》篇内删掉传主本人的名录条目 (成品兜底, 幂等)
    md, _n_dropped = _drop_subject_roster_lines(md, facts, articles)
    # v51: 成品再收一道 (幂等) —— 兜住终传附录等程序直出段; 只过正文 md,
    # 下面的机器可读头注释 (人物: / 篇目: / 十年:) 保持半角冒号不动。
    md = llm.normalize_zh_punct(md)
    # v70: 同一道成品收口里再压一次相邻重复词 (板块内已过一遍, 此处兜住
    # 组装缝隙与程序直出段; 白名单与判据见 `_dedup_adjacent_words`)。
    md = _dedup_adjacent_words(md)
    # v29: 本地化未命中审计 — 启用 Mod 后哪些键还没读进来, 一次生成后即可查
    try:
        n = F.L.write_miss_report(cfg)
        if n:
            llm.log(f"本地化未命中键 {n} 个已记入 logs/loc_miss.log")
    except Exception:
        pass
    # v34 (问题4): 特质显示名解析失败清单 — 此前静默丢弃 (新 Mod 特质消失),
    # 现随每次生成落同一份审计日志。
    try:
        miss = F.trait_name_miss_report()
        if miss:
            _p = os.path.join(cfg.get("log_dir") or "logs", "loc_miss.log")
            os.makedirs(os.path.dirname(_p), exist_ok=True)
            with open(_p, "a", encoding="utf-8") as _fp:
                _fp.write(f"# 特质显示名未解析 {len(miss)} 个 "
                          f"(计 {sum(miss.values())} 次)\n")
                for _k, _n in sorted(miss.items(), key=lambda kv: (-kv[1], kv[0])):
                    _fp.write(f"{_n}\t{_k}\n")
            llm.log(f"特质显示名未解析 {len(miss)} 个已记入 logs/loc_miss.log")
    except Exception:
        pass
    # 兜底统计 (问题1): 丢弃的裸键行数 — 0 表示全链路干净
    st = F.sanitize_stats()
    if st.get("lines"):
        llm.log(f"干净事实兜底共丢弃 {st['lines']} 行 (含裸键), 样例: "
                f"{st.get('samples', [])[:3]}")
    # v8: 头部注释带 人物/出生/篇目/十年, 供 htmlview 分组与十年标注。
    # v28: 只留 htmlview 真正要用的字段 (人物/人物ID/战役ID/出生/篇目/十年) —
    # 「数据来源: CK3 年度存档快照」与「生成时间」这类元信息不再写入文档。
    # v55-7: 增「执政」= 即位日 (played_legacy 链), 供阅读页按执政顺序排角色;
    # 旧文件无此字段, htmlview 回退生年, 故新旧混排仍有世代序。
    pp = facts["protagonist"] or {}
    person = pp.get("name") or facts.get("player_name") or ""
    birth = pp.get("birth") or ""
    reign = reign_start(cache)
    if decade:
        piece = f"第{decade}个十年传记"
    elif facts.get("player_death") or facts.get("reign_end"):
        piece = "终传"                    # v76: 让位档篇名不变 (用户拍板②)
    else:
        piece = "传记"
    header = (f"<!-- 人物: {person} | 人物ID: {facts.get('player_id')}"
              + (f" | 战役ID: {cache.get('playthrough_id')}"
                 if cache.get("playthrough_id") else "")
              + (f" | 出生: {birth}" if birth else "")
              + (f" | 执政: {reign}" if reign else "")
              + f" | 篇目: {piece}"
              + (f" | 十年: {decade}" if decade else "")
              + " -->\n\n")
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(header + md.rstrip() + "\n")
        llm.log(f"传记已生成: {out_path}")
    return md, facts, articles
