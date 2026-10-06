# -*- coding: utf-8 -*-
"""v108 洪氏家族全角色 · 亲属关系计算器 + 后处理 批量回放（生产口径，只读）

背景（v107 两处缺陷都出在同一段程序上）：
  * `biography._fix_kin_roles` 曾经领属者盲：把「孩子的妹妹是桑莎」放行，又把正确的
    「…的母亲是桑莎」改写成「妹妹」——缺陷由后处理注入并锁定；
  * 亲属关系计算器 `facts.Facts.kin_chain_words_for(cid, subject)` 的**婚姻词**取自
    `self.cache["player_id"]` 而不是参数 `subject`（见 `_spouse_kind_of`），所以同一对
    (cid, subject) 在不同战役、不同段落主语下会算出不同的链。

本脚本把 output/<家族>/ 下**每个战役缓存里的全体家族角色**喂给同一套生产代码，找残留样例：

  [A] 计算器校验（逐条家族边，独立判据表，不看 kin_key 的实现）
      A1 空词   A2 词类   A3 互逆   A4 链条   A5 枢轴不纯   A6 姻亲
      A7 入口不一致（后处理用的 F.kin_word 无反向索引，Facts.kin_word_for 有）
      A8 多重父母（_parent_maps 用 setdefault，只留第一个父/母）  A9 图里缺记录
      A10 链首词与两个入口都不合（排除「婚姻词提前」那条设计）  A11 同名亲属
      读法：A2 带「(双重关系)」的是图里同时有两条边，出词取其一属正常；A4 的「未知词」
      在本语料里全是官职词（御用建筑师/古物研究官），是合规范畴，列出来只为核对。
  [B] 后处理（生产口径，真实传主）
      任何一个计算器作证的词都必须逐字保留；错词必须按领属者自己的真词纠正。
  [C] 枢轴回放：把家族里每个角色轮流当作传主，重跑 [B] 的断言。
  [D] 成稿回放：对 output/<家族>/*.md 逐节重跑 `_fix_kin_roles`，改写点即残留问题候选。
  [E] 兼链宽度：合成族谱问「儿子兼继子兼弟弟兼舅舅」能不能算出来（引用
      tools/tests/v108_probe_chain_width.py）。
  [F] 已知改错复现：把成稿原文里被 `_fix_kin_roles` 改错的五处直接跑一遍
      （tools/tests/v108_probe_d_repro.py）。

只读：不重熔存档、不写 output/、不动缓存。结果落 logs/v108_kin_sweep.txt (+ .json)。

用法：
    & tools\\py.ps1 tools\\tests\\v108_kin_sweep.py [--folder 洪氏2] [--pid 135480]
                                                   [--sample 6] [--no-c] [--no-d] [--no-json]
"""
import argparse
import collections
import copy
import difflib
import glob
import io
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "tests"))
import biography as bio          # noqa: E402
import facts as F                # noqa: E402
import llm                       # noqa: E402

# --- 提速（只影响本测试的耗时，不影响取值）-------------------------------------
# `F.kin_rev_index` 没有记忆化，而 `F.kin_word`/`F.kin_key` 在 rev=None 时每次调用都重建
# 一遍 6.5 万条记录的反向索引（实测单次约 0.2–1.3s）。后处理 `_fix_kin_roles` 走的正是
# 这个无索引入口，所以本脚本按 id(chars) 记忆化——纯函数，取值逐字不变。
_ORIG_REV = F.kin_rev_index
_REV_MEMO = {}


def _cached_rev(chars):
    key = id(chars)
    hit = _REV_MEMO.get(key)
    if hit is None or hit[0] is not chars:
        hit = (chars, _ORIG_REV(chars))
        _REV_MEMO[key] = hit
    return hit[1]


F.kin_rev_index = _cached_rev

# 家族图里出现过的边（与 facts.kin_key 读取的键同名）
PARENT_FIELDS = ("father", "real_father", "mother")
CHILD_FIELDS = ("child",)
SIB_FIELDS = ("siblings",)
SPOUSE_NOW = ("primary_spouse", "spouse")
SPOUSE_PAST = ("ever_spouses", "former_spouses")
CONC_FIELDS = ("concubine", "former_concubines")
KIN_FIELDS = PARENT_FIELDS + CHILD_FIELDS + SIB_FIELDS + SPOUSE_NOW + SPOUSE_PAST + CONC_FIELDS
# 后处理真正会重写的相对人（by_cid 的来源键）
PASS_DOMAIN = SPOUSE_NOW + SPOUSE_PAST + CONC_FIELDS + ("father", "mother", "child", "siblings")

# 独立判据表：这条边在亲缘词层面**应该**落进哪个词族（不引用 kin_key 的实现）
EXPECT = {
    "father": {"father"}, "real_father": {"father"}, "mother": {"mother"},
    "child": {"son", "daughter"},
    "siblings": {"brother_older", "brother_younger", "sister_older", "sister_younger",
                 "brother", "sister"},
    "primary_spouse": {"wife", "husband", "spouse"},
    "spouse": {"wife", "husband", "spouse"},
    "concubine": {"wife", "husband", "spouse"},
    # 已结束的婚姻：图里还剩一条边，但「现在」已不是配偶，允许算不出词
    "ever_spouses": {"wife", "husband", "spouse", ""},
    "former_spouses": {"wife", "husband", "spouse", ""},
    "former_concubines": {"wife", "husband", "spouse", ""},
}
EMPTY_OK = set(SPOUSE_PAST) | {"former_concubines"}
# 互逆关系（A3 只对这几组封闭词族判定，超出即「不可判」）
RECIP = {
    ("father", "son"), ("father", "daughter"), ("mother", "son"), ("mother", "daughter"),
    ("brother_older", "brother_younger"), ("brother_older", "sister_younger"),
    ("sister_older", "brother_younger"), ("sister_older", "sister_younger"),
    ("brother", "brother"), ("brother", "sister"), ("sister", "sister"),
    ("wife", "husband"), ("husband", "wife"), ("spouse", "spouse"),
    ("spouse", "wife"), ("spouse", "husband"), ("wife", "wife"), ("husband", "husband"),
}
# 错词探针候选池（扮演「模型写错的亲缘词」）
DISTRACTORS = ("妹妹", "姐姐", "哥哥", "弟弟", "母亲", "父亲", "儿子", "女儿",
               "姑母", "姨母", "侄女", "族侄女", "堂姐", "表妹")
SECTION_RE = re.compile(r"^(#{1,4})\s*(.+?)\s*$")
TITLE_BOOK_RE = re.compile(r"[《〈](.+?)[》〉]")

LINES = []
ISSUES = []
COUNTS = collections.Counter()
SHOWN = collections.Counter()          # 本战役已打印的样例行数
SAMPLES = {}
# C 段：只有关系词（仇敌/朋友/封臣…）而没有亲缘词的对。生产后处理**按设计**原样保留这种对
# （`_fix_kin_roles` 只在亲缘/婚姻词表内找错词，也只用 `F.kin_word` 认证的词替换，见
# biography.py「if len(words) != 1: continue」）。它们不是失败，单独计数并在摘要里报出。
REL_ONLY = []

# 允许出现在链里的非亲缘词：关系词 + 官职词（后者运行时从 _court_positions_of 收集）
RELATION_WORDS = set(F.RELATION_WORDS.values())
CHAIN_EXTRA = {"妻室", "妾", "男宠", "配偶"}


def w(s=""):
    LINES.append(s)


def issue(kind, text, data=None, sample=3):
    ISSUES.append({"kind": kind, "text": text, "data": data or {}})
    COUNTS[kind] += 1
    if SHOWN[kind] < sample:
        SHOWN[kind] += 1
        w("    [%s] %s" % (kind, text))


def reset_campaign():
    SHOWN.clear()


# --------------------------------------------------------------------------- 基础

def find_snapshots(data_dir):
    """{pid: [快照路径…]}（新→旧）：meta 在快照最前面。"""
    out = collections.defaultdict(list)
    for p in glob.glob(os.path.join(data_dir, "*.json")):
        b = os.path.basename(p)
        if b.startswith("player_") or ".tmp" in b:
            continue
        try:
            head = io.open(p, encoding="utf-8", errors="replace").read(8000)
        except OSError:
            continue
        if '"meta"' not in head:
            continue
        m = re.search(r'"player_id":\s*(\d+)', head)
        if m:
            out[int(m.group(1))].append(p)
    for k in out:
        out[k].sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return out


def load_facts(snap_path):
    try:
        d = json.load(io.open(snap_path, encoding="utf-8"))
    except Exception:                                     # noqa: BLE001
        return {}
    return dict(d.get("facts") or {})


def as_of_of(cache, facts):
    for v in ((facts or {}).get("as_of"), cache.get("player_death"), cache.get("last_date")):
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict) and v.get("date"):
            return v["date"]
    return None


def name_of(chars, cid):
    rec = chars.get(str(cid)) or {}
    return rec.get("name_full") or rec.get("name_zh") or ""


def pivot(fi, cache, pid, memo):
    """Facts 与 cache 一起换枢轴；characters 图共享，与 player_id 无关的索引沿用。"""
    if pid not in memo:
        c2 = dict(cache)
        c2["player_id"] = pid
        f2 = copy.copy(fi)
        f2.cache = c2
        memo[pid] = (f2, c2)
    return memo[pid]


def family_ids(chars, pid, roster):
    """家族角色集：同宗（dynasty_house / house_name）∪ 这些人的记录在册亲属 ∪ 事实面角色。"""
    p = chars.get(str(pid)) or {}
    dyn_house, house = p.get("dynasty_house"), p.get("house_name")
    out = {int(pid)}
    for k, rec in chars.items():
        if not str(k).isdigit() or not isinstance(rec, dict):
            continue
        if (dyn_house is not None and rec.get("dynasty_house") == dyn_house) \
                or (house and rec.get("house_name") == house):
            out.add(int(k))
    for x in list(out):
        fam = (chars.get(str(x)) or {}).get("family") or {}
        for fld in KIN_FIELDS:
            for y in (fam.get(fld) or []):
                if isinstance(y, int):
                    out.add(y)
    out |= {int(x) for x in roster if str(x).isdigit()}
    return {x for x in out if str(x) in chars}


def edge_kinds(chars, x, y):
    kinds = set()
    for a, b in ((x, y), (y, x)):
        fam = (chars.get(str(a)) or {}).get("family") or {}
        for fld in KIN_FIELDS:
            if b in (fam.get(fld) or []):
                kinds.add(fld)
    return kinds


def kin_family(key):
    if not key:
        return ""
    if key in ("father", "mother"):
        return "up"
    if key in ("son", "daughter", "step_son", "step_daughter"):
        return "down"
    if key in ("wife", "husband", "spouse"):
        return "spouse"
    if "brother" in key or "sister" in key or "sib" in key:
        return "sib"
    return ""


def seniority_flips(key, key2):
    """同一词族的两个词是否互逆自洽：一方 younger、另一方 older（或双方都没有长幼词）。

    v108 起双胞胎按 cid 定长幼，两边必然一长一幼，所以「同族同龄」才是缺陷、一长一幼是正解。"""
    def s(k):
        if k.endswith("_older"):
            return 1
        if k.endswith("_younger"):
            return -1
        return 0
    return s(key) + s(key2) == 0


def marital_word(chars, x, y):
    """x 的族谱把 y 记成配偶时 x 该用的婚姻词（男宠/妾/夫/妻）；否则 ''。

    与生产 `_spouse_kind_of` 同口径：两侧记录任一写下这段婚姻即算（v108 起生产就是这个并集，
    A10 否则会把「只有对方记录写了婚姻」误判成链首词无出处）。"""
    rx = chars.get(str(x)) or {}
    kind = F.marriage_slot_of(rx.get("family") or {}, y) \
        or F.marriage_slot_of((chars.get(str(y)) or {}).get("family") or {}, x)
    if kind == "spouse":
        return "丈夫" if rx.get("female") else "妻子"
    if kind == "concubine":
        return "男宠" if rx.get("female") else "妾"
    return ""


def kin_vocab():
    return {F.kin_text(k) for k in F.KIN_WORDS if F.kin_text(k)} | RELATION_WORDS | CHAIN_EXTRA


# --------------------------------------------------------------------------- A

def part_a(camp, fi, cache, fam, say, progress=False):
    chars = cache["characters"]
    pid = camp["pid"]
    memo = {}
    n_edge = 0
    vocab_extra = set()
    for x in fam:
        vocab_extra |= set(fi._court_positions_of(x) or ())
    vocab = kin_vocab() | vocab_extra
    fath, moth = fi._parent_maps()
    n_sib = n_sib_nopar = 0
    for nx, x in enumerate(sorted(fam), 1):
        if progress and nx % 200 == 0:
            print("      …A 段 %d/%d（%d 条边）" % (nx, len(fam), n_edge), flush=True)
        fam_x = (chars.get(str(x)) or {}).get("family") or {}
        # A11 同名亲属：同一个名字在**一个人的亲属里**对应两个以上 id。v108 起后处理按 cid
        # 判同一人（姓名→全部 cid，只有全体同词才改写），所以这是「本语料有多少处歧义」的
        # 统计，不是缺陷；该规则的实际效果由 B/C 段断言。
        byname = collections.defaultdict(set)
        for fld in PASS_DOMAIN:
            for y in (fam_x.get(fld) or []):
                if isinstance(y, int) and str(y) in chars:
                    nm = name_of(chars, y)
                    if len(nm) >= 2 and y != x:
                        byname[nm].add(y)
        self_nm = name_of(chars, x)
        for y in (fam_x.get("primary_spouse") or []) + (fam_x.get("spouse") or []):
            if isinstance(y, int) and str(y) in chars and y != x:
                byname[name_of(chars, y)].add(y)
        for nm, cids in sorted(byname.items()):
            if len(cids) > 1 and nm != self_nm:
                issue("A11同名亲属(信息)",
                      "%s(%s) 的亲属里有 %d 个叫「%s」：%s —— 按 cid 判为不同人，只有全体同词才改写"
                      % (name_of(chars, x), x, len(cids), nm, sorted(cids)),
                      {"campaign": pid, "x": x, "name": nm, "cids": sorted(cids)})
                break
        for fld in ("father", "mother"):
            if len(fam_x.get(fld) or []) > 1:
                issue("A8多重父母",
                      "%s(%s) 的 %s 记了 %s 个：%s（v108 起两条父系边都保留，不再丢线）"
                      % (name_of(chars, x), x, fld, len(fam_x[fld]), fam_x[fld]),
                      {"campaign": pid, "x": x})
        for fld in KIN_FIELDS:
            for y in (fam_x.get(fld) or []):
                if not isinstance(y, int) or y == x:
                    continue
                if str(y) not in chars:
                    issue("A9缺记录", "%s(%s) 的 %s 指向 %s，缓存里没有这条记录"
                          % (name_of(chars, x), x, fld, y), {"campaign": pid, "x": x, "y": y})
                    continue
                n_edge += 1
                # A12（信息）兄弟边却没有共同记录的父母：这种「弟弟」只写在 siblings 字段里，而
                # `_ancestor_routes` 只走父母边，它永远无法成为链里的额外血缘词 —— 复合身份
                # 能不能算出来，这条统计是关键边界。
                if fld == "siblings":
                    n_sib += 1
                    pa = set(fath.get(x, ())) | set(moth.get(x, ()))
                    pb = set(fath.get(y, ())) | set(moth.get(y, ()))
                    if not (pa & pb):
                        n_sib_nopar += 1
                key = F.kin_key(cache, x, y)
                word = F.kin_text(key)
                fi_x = pivot(fi, cache, x, memo)[0]
                chain = fi_x.kin_chain_words_for(y, x)
                w_pass = F.kin_word(cache, x, y)                 # 后处理用的入口（无反向索引）
                w_facts = fi_x.kin_word_for(y, x)                # Facts 入口（带反向索引）
                # A1 空词
                if not key and fld not in EMPTY_OK:
                    issue("A1空词", "%s(%s) 的 %s(%s) 记在 %s，算不出亲缘词"
                          % (name_of(chars, x), x, name_of(chars, y), y, fld),
                          {"campaign": pid, "x": x, "y": y, "fld": fld})
                # A2 词类
                if key and key not in EXPECT[fld]:
                    kinds = edge_kinds(chars, x, y)
                    tag = "A2词类" if len(kinds) <= 1 else "A2词类(双重关系)"
                    issue(tag, "%s(%s) → %s(%s)：边 %s 算得 %s(%s)，边类型集 %s"
                          % (name_of(chars, x), x, name_of(chars, y), y, fld, word, key,
                             sorted(kinds)),
                          {"campaign": pid, "x": x, "y": y, "fld": fld})
                # A3 互逆
                key2 = F.kin_key(cache, y, x)
                if key and key2 and (key, key2) not in RECIP and (key2, key) not in RECIP \
                        and kin_family(key) and kin_family(key) == kin_family(key2) \
                        and not seniority_flips(key, key2):
                    issue("A3互逆", "%s→%s 得 %s，反向得 %s（同词族却不同代）"
                          % (name_of(chars, x), name_of(chars, y), word, F.kin_text(key2)),
                          {"campaign": pid, "x": x, "y": y})
                elif key and not key2 and fld not in EMPTY_OK:
                    issue("A3互逆", "%s→%s 得 %s，反向算不出词"
                          % (name_of(chars, x), name_of(chars, y), word),
                          {"campaign": pid, "x": x, "y": y})
                # A4 链条
                if not chain and (word or w_pass):
                    issue("A4链条", "%s→%s 首词 %s，链为空"
                          % (name_of(chars, x), name_of(chars, y), word or w_pass),
                          {"campaign": pid, "x": x, "y": y})
                else:
                    if len(set(chain)) != len(chain):
                        issue("A4链条", "%s→%s 链内重复 %s"
                              % (name_of(chars, x), name_of(chars, y), chain),
                              {"campaign": pid, "x": x, "y": y})
                    # 官职词的变体随枢轴的宫廷政体变化（见 A5），链是按 fi_x 枢轴算的，
                    # 所以该枢轴下的官职词也要算作已知词
                    bad = [c for c in chain
                           if c not in vocab and c not in set(fi_x._court_positions_of(y) or ())]
                    if bad:
                        issue("A4链条", "%s→%s 链里有未知词 %s（链 %s）"
                              % (name_of(chars, x), name_of(chars, y), bad, chain),
                              {"campaign": pid, "x": x, "y": y})
                # A5 枢轴纯度（官职词除外：官职称谓的变体取决于**雇主**即本战役传主的政体/等级/
                # 文化，cache["court_positions"] 记的也只是传主宫廷的差遣，换枢轴会连带换掉这一
                # 个词形；生产只为每个战役建一个 Facts，不会中途改 player_id，故这一项单列）
                chain_pid = fi.kin_chain_words_for(y, x)
                off = set(fi._court_positions_of(y) or ()) | set(fi_x._court_positions_of(y) or ())
                kin_c = [t for t in chain if t not in off]
                kin_p = [t for t in chain_pid if t not in off]
                if kin_c != kin_p:
                    issue("A5枢轴不纯", "%s→%s：传主枢轴 %s / 领属者枢轴 %s"
                          % (name_of(chars, x), name_of(chars, y), kin_p, kin_c),
                          {"campaign": pid, "x": x, "y": y})
                # A6 姻亲词
                if fld in SPOUSE_NOW + CONC_FIELDS and key in ("wife", "husband", "spouse"):
                    mw = marital_word(chars, x, y)
                    if mw and chain and mw not in chain:
                        issue("A6姻亲", "%s→%s 是配偶，链 %s 里没有「%s」"
                              % (name_of(chars, x), name_of(chars, y), chain, mw),
                              {"campaign": pid, "x": x, "y": y})
                # A7 两个入口不一致（后处理走 F.kin_word：无反向索引；Facts 走带索引的入口）
                if w_pass and w_facts and w_pass != w_facts:
                    issue("A7入口不一致",
                          "%s→%s：F.kin_word=%s / Facts.kin_word_for=%s"
                          % (name_of(chars, x), name_of(chars, y), w_pass, w_facts),
                          {"campaign": pid, "x": x, "y": y})
                # A10 链条首词与两个入口都不合（且不是「婚姻词提前」那条设计）
                head = chain[0] if chain else ""
                if head and head != w_facts and head != marital_word(chars, x, y):
                    issue("A10链首词", "%s→%s：链首词 %s，而 kin_word=%s / Facts=%s"
                          % (name_of(chars, x), name_of(chars, y), head, w_pass, w_facts),
                          {"campaign": pid, "x": x, "y": y})
    say("A 计算器：家族 %d 人 / 家族边 %d 条" % (len(fam), n_edge))
    if n_sib:
        say("A12（信息）siblings 边 %d 条，其中 %d 条双方没有共同记录的父母 —— 这些「兄弟」只在"
            "siblings 字段里，`_ancestor_routes` 走不到，进不了兼链" % (n_sib, n_sib_nopar))


# --------------------------------------------------------------------------- B/C

def unresolvable_same_name(cache_x, chars, fchars, x, yname, xname, names_map):
    """同名亲属导致「无法判定该改哪一个」时返回说明，否则 ''。

    用户裁决 2026-10-06：同名亲属用 cid 判断是否同一人。姓名指多个 cid 时它们是不同的人，
    后处理只在全体同词时改写，因此这类探针**不该**被改（改哪一个都有一半机会改错）。"""
    xc = [int(v) for v in (names_map.get(xname) or ())]
    if len(xc) > 1:
        return "领属者「%s」同名 %d 人 %s" % (xname, len(xc), sorted(xc))
    fam = (chars.get(str(x)) or {}).get("family") or {}
    ids = {int(x)}
    for fld in PASS_DOMAIN:
        for v in (fam.get(fld) or []):
            if isinstance(v, int):
                ids.add(v)
    hit = []
    for c in sorted(ids):
        rec = chars.get(str(c)) or {}
        names = {rec.get("name_full"), rec.get("name_zh"),
                 (fchars.get(str(c)) or {}).get("name")}
        if yname in names:
            hit.append(c)
    if len(hit) < 2:
        return ""
    ws = {F.kin_word(cache_x, x, c) for c in hit}
    ws.discard("")
    if len(ws) < 2:
        return ""
    return "亲属名「%s」同名 %d 人 %s，对领属者要的词不一致 %s" % (yname, len(hit), hit, sorted(ws))


def check_owner(chars, fi, cache, x, ys, fchars, memo, prod):
    """x 当传主（cache.player_id=x）时逐条断言；返回 (检查数, 失败列表, 无法纠正的相对人数,
    同名不可判数)。

    「错词必纠」只对**后处理看得见**的相对人（by_cid 的取词范围）成立；范围外的相对人
    后处理根本不会改写，单列成「覆盖缺口」而不是失败。同名歧义按 cid 判为不同人而原样保留的，
    单列成「同名不可判」也不是失败。

    「错词必纠」期望的替换词取自 `F.kin_word(cache, 领属者, 相对人)`——生产后处理唯一会用的替换来源；
    若这一对只有关系词（仇敌/朋友/封臣…，v110 补记：campaign 44503 的崔穆/李法台是 former_spouses
    且互为仇敌），后处理按设计原样保留，改记为不计失败的回归项（见模块级 REL_ONLY）。"""
    fi_x, cache_x = pivot(fi, cache, x, memo)
    facts_x = {"_facts": fi_x, "characters": fchars}
    xname = name_of(chars, x)
    fam_x = (chars.get(str(x)) or {}).get("family") or {}
    dom = set()
    for fld in PASS_DOMAIN:
        for y in (fam_x.get(fld) or []):
            if isinstance(y, int):
                dom.add(y)
    n, bad, gap, unres = 0, [], 0, 0
    if not xname:
        return 0, [], 0, 0
    names_map, subjects = bio._possessor_words(cache_x, facts_x, x, [x])
    names_ordered = sorted(names_map.items(), key=lambda kv: -len(kv[0]))
    for y in sorted(ys):
        yname = name_of(chars, y)
        if not yname or y == x:
            continue
        chain = fi_x.kin_chain_words_for(y, x)
        words = list(dict.fromkeys([w for w in
                                    (F.kin_word(cache, x, y), fi_x.kin_word_for(y, x),
                                     chain[0] if chain else "") if w]))
        acc = set(chain) | set(words)
        mw = marital_word(chars, x, y)
        probes = []
        for tw in words:                                   # 计算器作证的每一个词都必须存活
            probes.append(("逐字保留", "%s的%s%s。" % (xname, tw, yname), None, tw))
            probes.append(("逐字保留(无领属者)", "%s%s。" % (tw, yname), None, tw))
        if mw:
            probes.append(("婚姻词保留", "%s的%s%s。" % (xname, mw, yname), None, mw))
            blood = next((t for t in words if t != mw), "")
            if blood:
                probes.append(("兼链保留", "%s的%s兼%s%s。" % (xname, mw, blood, yname),
                               None, blood))
                probes.append(("兼链保留(无领属者)", "%s兼%s%s。" % (mw, blood, yname),
                               None, blood))
        if words:
            if y not in dom:
                gap += 1
            else:
                # 「错词必纠」期望的替换词只能取自后处理真正会用的来源：`F.kin_word(cache, 领属者, 相对人)`
                # （`_fix_kin_roles` 的替换目标；它只在亲缘/婚姻词表里找错词，也只用 kin_word 认证的词替换）。
                # `chain` 里还可能有纯关系词（仇敌/朋友/封臣…）：它们只是「可接受文本」——由逐字保留探针
                # 保证不被破坏——不是替换目标。
                cert = [t for t in (F.kin_word(cache, x, y), fi_x.kin_word_for(y, x)) if t]
                wrong = next((t for t in DISTRACTORS if t not in acc), "")
                if wrong and cert:
                    probes.append(("错词必纠", "%s的%s%s。" % (xname, wrong, yname),
                                   "%s的%s%s。" % (xname, cert[0], yname), wrong))
                elif wrong:
                    # 只有关系词的对（例如 former_spouses 且互为仇敌：崔穆/李法台，campaign 44503）：
                    # 断言改为「原样保留」，把后处理的契约钉成回归项，而不是当成失败。
                    REL_ONLY.append((x, y, wrong, words[0]))
                    probes.append(("关系词对不改写", "%s的%s%s。" % (xname, wrong, yname), None, wrong))
        def cause(word, s):
            """这次失败是「领属者被解析成了别人」还是「后处理压根没管」——同名亲属是主因。"""
            iy = s.find(yname)
            at = s.rfind(word, 0, iy + 1) if iy >= 0 else s.rfind(word)
            if at < 0:
                return "?"
            try:
                poss = bio._possessor_at(s, at, names_ordered, subjects, y)
            except Exception:                             # noqa: BLE001
                return "?"
            if poss is None:
                return "领属者未解析（原样保留）"
            ids = [int(p) for p in poss]
            if ids != [int(x)]:
                return "领属者解析为 %s" % "、".join(name_of(chars, p) or str(p) for p in ids)
            return "领属者正确"

        for tag, line, want, word in probes:
            n += 1
            out = bio._fix_kin_roles(line, facts_x, cache_x, subject_ids=[x])
            ok = (out == line) if want is None else (out == want)
            if not ok:
                why = unresolvable_same_name(cache_x, chars, fchars, x, yname, xname, names_map)
                if why:
                    unres += 1
                    continue
                bad.append((tag, x, y, line, out, want or line, prod, cause(word, line)))
    return n, bad, gap, unres


def part_bc(camp, fi, cache, facts, fam, say, do_c=True, sample=3):
    chars = cache["characters"]
    pid = camp["pid"]
    memo = {}
    fam_roster = {str(x): {"name": name_of(chars, x)} for x in fam}
    fchars = dict(fam_roster)
    dom = set()
    fam_p = (chars.get(str(pid)) or {}).get("family") or {}
    for fld in PASS_DOMAIN:
        for y in (fam_p.get(fld) or []):
            if isinstance(y, int):
                dom.add(y)
    n, bad, gap, unres = check_owner(chars, fi, cache, pid, dom, fchars, memo, True)
    say("B 后处理(生产口径 传主=%s)：%d 条断言 / 失败 %d ／ 范围外亲属 %d 人（后处理不覆盖）"
        " ／ 同名不可判 %d 条（按 cid 判为不同人，原样保留）"
        % (name_of(chars, pid), n, len(bad), gap, unres))
    for b in bad[:sample]:
        issue("B后处理", "%s（%s）：%s\n        期望 %s\n        实得 %s"
              % (b[0], b[7], b[3], b[5], b[4]),
              {"campaign": pid, "x": b[1], "y": b[2], "tag": b[0], "cause": b[7]})
    if len(bad) > sample:
        w("    … 另有 %d 条" % (len(bad) - sample))
    for b in bad[sample:]:
        issue("B后处理", "%s（%s）：%s" % (b[0], b[7], b[3]),
              {"campaign": pid, "x": b[1], "y": b[2], "tag": b[0], "cause": b[7]},
              sample=0)
    if do_c:
        n2, bad2, owners, gap2, unres2 = 0, [], 0, 0, 0
        rel0 = len(REL_ONLY)
        cap = camp.get("max_c") or 0
        work = [x for x in sorted(fam) if x != pid]
        if cap and len(work) > cap:                    # 家族过大时按 id 抽前 cap 个（省时，注明）
            say("C 枢轴回放：家族 %d 人，超上限，只回放 id 最小的 %d 人" % (len(work), cap))
            work = work[:cap]
        for x in work:
            fam_x = (chars.get(str(x)) or {}).get("family") or {}
            ys = set()
            for fld in KIN_FIELDS:
                for y in (fam_x.get(fld) or []):
                    if isinstance(y, int) and str(y) in chars:
                        ys.add(y)
            if not ys:
                continue
            owners += 1
            a, b, g, u = check_owner(chars, fi, cache, x, ys, fchars, memo, False)
            n2 += a
            bad2 += b
            gap2 += g
            unres2 += u
            if owners % 50 == 0:
                print("      …C 段 %d 个传主（%d 条断言）" % (owners, n2), flush=True)
        say("C 枢轴回放（%d 个家族角色当传主）：%d 条断言 / 失败 %d ／ 范围外亲属 %d 人"
            " ／ 同名不可判 %d 条 ／ 只有关系词的对 %d 对（按契约原样保留）"
            % (owners, n2, len(bad2), gap2, unres2, len(REL_ONLY) - rel0))
        for b in bad2[:sample]:
            issue("C枢轴回放", "%s（%s）：%s（传主=%s → 相对人=%s）\n        期望 %s\n        实得 %s"
                  % (b[0], b[7], b[3], name_of(chars, b[1]), name_of(chars, b[2]), b[5], b[4]),
                  {"campaign": pid, "owner": b[1], "kin": b[2], "tag": b[0], "cause": b[7]})
        if len(bad2) > sample:
            w("    … 另有 %d 条" % (len(bad2) - sample))
        for b in bad2[sample:]:
            issue("C枢轴回放", "%s（%s）：%s" % (b[0], b[7], b[3]),
                  {"campaign": pid, "owner": b[1], "kin": b[2], "tag": b[0], "cause": b[7]},
                  sample=0)


# --------------------------------------------------------------------------- D

def sections_of(md_text):
    """[(篇名, 节标题, 正文)]"""
    out, art, cur, body = [], "", None, []
    for line in md_text.split("\n"):
        m = SECTION_RE.match(line)
        if m:
            if cur is not None:
                out.append((art, cur, "\n".join(body)))
            lvl, title = len(m.group(1)), m.group(2).strip()
            if lvl == 2:
                b = TITLE_BOOK_RE.search(title)
                art = b.group(1) if b else title.strip("0123456789、 ")
                cur, body = None, []
            else:
                cur, body = title, []
            continue
        if cur is not None:
            body.append(line)
    if cur is not None:
        out.append((art, cur, "\n".join(body)))
    return out


def heading_subjects(title, name_index):
    ids, used = [], []
    for nm, cid in name_index:
        j = title.find(nm)
        while j >= 0:
            if not any(j < e and s < j + len(nm) for s, e in used):
                used.append((j, j + len(nm)))
                ids.append(cid)
            j = title.find(nm, j + 1)
    return list(dict.fromkeys(ids))


def diff_contexts(a, b, n=2, width=46):
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        lo = max(0, i1 - width // 2)
        out.append("…%s【%s → %s】%s…"
                   % (a[lo:i1].replace("\n", " "),
                      a[i1:i2].replace("\n", " ")[:36] or "∅",
                      b[j1:j2].replace("\n", " ")[:36] or "∅",
                      a[i2:i2 + width // 2].replace("\n", " ")))
        if len(out) >= n:
            break
    return out


def pair_sentences(a, b, limit=3, width=170):
    """同一段落到新段落的成对句子（只列真正改动过的），D 段的第一手证据。

    亲缘词只换词、不动句读，所以按句末标点切开后同一序号就是同一句；万一序号对不上
    （理论上不该发生）就返回空，宁可不给证据也不给错位证据。"""
    sa = re.split(r"(?<=[。！？\n])", a)
    sb = re.split(r"(?<=[。！？\n])", b)
    if len(sa) != len(sb):
        return []
    out = []
    for x, y in zip(sa, sb):
        if x == y:
            continue
        out.append("        - %s" % x.strip()[:width])
        out.append("        + %s" % y.strip()[:width])
        if len(out) >= limit * 2:
            break
    return out


def part_d(camp, fi, cache, facts, art_map, say, sample=4):
    """按生产口径逐节重跑 `_fix_kin_roles`。

    段落主语：节的 `members`（家室分组）→ 该篇的主语（`_article_subject`：列传用其传主，
    其余用传主本人）。节名与快照的节名因姓名书写形态可能不同（「伊丽莎白·耀国斯多蒂尔」／
    「伊丽莎白·耀国松」），按成员名是否出现在标题里兜底匹配。

    只有与快照同一世代的那份稿（文件名含 as_of 的 YYYY_MM）是**生产精确**回放；其余世代
    稿件只有传主主语（老代码就是那么跑的，分组无法从快照还原），单列「低置信」。"""
    exact_tag = camp.get("asof_tag") or "\0"
    hits = {"exact": 0, "loose": 0}
    n_sec = {"exact": 0, "loose": 0}
    files = 0
    for path in sorted(glob.glob(os.path.join(camp["dir"], "*.md"))):
        base = os.path.basename(path)
        if camp["birth_tag"] not in base:
            continue
        mode = "exact" if exact_tag in base else "loose"
        files += 1
        for art, title, body in sections_of(io.open(path, encoding="utf-8").read()):
            if not body.strip():
                continue
            a = art_map.get(art)
            if a is None:
                continue
            n_sec[mode] += 1
            subs = []
            if mode == "exact":
                sec = next((s for s in a["sections"] if s.get("title") == title), None)
                subs = list((sec or {}).get("members") or [])
                if not subs:                    # 节名形态不同：按成员名兜底匹配
                    # 稿子的标题用现场姓名形态（「伊丽莎白·耀国斯多蒂尔」），快照的
                    # facts.characters 用另一种（「伊丽莎白·耀国松」），所以按**名的首段**
                    # （· 之前）出现在标题里来认节。
                    best = []
                    for s in a["sections"]:
                        mem = s.get("members") or []
                        score = 0
                        for c in mem:
                            nm = ((facts.get("characters") or {}).get(str(c)) or {}).get("name") or ""
                            given = nm.split("·")[0]
                            if len(given) >= 2 and given in title:
                                score += 1
                        if score > len(best):
                            best = list(mem)
                    subs = best
            if not subs:
                subs = [bio._article_subject(facts, cache, a["key"])]
            out = bio._fix_kin_roles(body, facts, cache, subject_ids=subs)
            if out == body:
                continue
            hits[mode] += 1
            issue("D成稿回放", "[%s] %s §%s：新后处理会改写（段落主语 %s）"
                  % (mode, base, title, subs),
                  {"file": base, "section": title, "subjects": subs, "mode": mode},
                  sample=2 if mode == "exact" else 1)
            for ctx in diff_contexts(body, out, 2):
                w("        %s" % ctx)
            for line in pair_sentences(body, out, 2):
                w(line)
    say("D 成稿回放：%d 个 md ／ 世代精确稿 %d 节改写 %d ／ 其余稿 %d 节改写 %d（低置信）"
        % (files, n_sec["exact"], hits["exact"], n_sec["loose"], hits["loose"]))
    return hits


# --------------------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default="洪氏2")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--sample", type=int, default=3)
    ap.add_argument("--max-c", type=int, default=250, help="枢轴回放的传主上限（家族过大时）")
    ap.add_argument("--no-c", action="store_true")
    ap.add_argument("--no-d", action="store_true")
    ap.add_argument("--no-json", action="store_true")
    args = ap.parse_args()

    data_dir = os.path.join(ROOT, "output", args.folder, "data")
    out_dir = os.path.join(ROOT, "output", args.folder)
    snaps = find_snapshots(data_dir)
    caches = [p for p in sorted(glob.glob(os.path.join(data_dir, "player_*.json")))
              if "pre_v" not in os.path.basename(p) and ".tmp" not in os.path.basename(p)]

    w("=" * 92)
    w("v108 洪氏家族全角色 · 亲属关系计算器 + 后处理 批量回放（生产口径，只读）")
    w("=" * 92)
    w("家族目录 output/%s/ ｜ 战役缓存 %d 份 ｜ %s"
      % (args.folder, len(caches), time.strftime("%Y-%m-%d %H:%M:%S")))
    w("判据：计算器出词必须与边相符（A2 独立判据表）、两个入口必须一致（A7）、"
      "计算器作证的词必须不被后处理改写（B/C）、成稿必须经得起重跑（D）。")
    w()

    for idx, cpath in enumerate(caches, 1):
        t0 = time.time()
        if args.pid:                       # 先读文件头，避免整载不需要的战役
            m = re.search(r'"player_id":\s*(\d+)',
                          io.open(cpath, encoding="utf-8", errors="replace").read(4000))
            if not m or int(m.group(1)) != args.pid:
                continue
        cache = json.load(io.open(cpath, encoding="utf-8"))
        pid = cache.get("player_id")
        chars = cache.get("characters") or {}
        snap = (snaps.get(int(pid)) or [None])[0]
        facts = load_facts(snap) if snap else {}
        as_of = as_of_of(cache, facts)
        fi = F.Facts(cache, {}, None, as_of=as_of, decade=facts.get("decade"))
        facts["_facts"] = fi
        # 事实面角色表只在**真有快照**时才用作家族名册；没有快照时若拿整张缓存（6.5 万人）当名册，
        # 家族集会炸成全存档，A 段会产出几万条「缺记录」假象。
        if not facts.get("characters"):
            facts["characters"] = {}
        roster = {int(k) for k in facts["characters"] if str(k).isdigit()}
        fam = family_ids(chars, pid, roster)
        birth_year = (((chars.get(str(pid)) or {}).get("birth") or "").split(".") or [""])[0]
        birth_tag = "(%s)" % birth_year
        reset_campaign()
        w("-" * 92)
        w("[战役 %d] pid=%s %s ｜ %s ｜ as_of=%s ｜ 家族角色 %d 人 ｜ 事实面 %s"
          % (idx, pid, name_of(chars, pid), os.path.basename(cpath), as_of, len(fam),
             os.path.basename(snap) if snap else "无快照（用缓存自建）"))
        w("-" * 92)
        before = collections.Counter(COUNTS)
        if idx == 1:
            t = time.time()
            _ORIG_REV(chars)
            w("    （实测 kin_rev_index 单次重建 %.3fs；`_fix_kin_roles` 走的 F.kin_word 每次"
              "调用都要重建一遍，本脚本已按 id(chars) 记忆化）" % (time.time() - t))
        part_a({"pid": int(pid)}, fi, cache, fam, w, progress=True)
        a_delta = {k: COUNTS[k] - before.get(k, 0) for k in COUNTS}
        w("    → 本战役 A 段异常 %d 条：%s"
          % (sum(v for k, v in a_delta.items() if k.startswith("A")),
             {k: v for k, v in sorted(a_delta.items()) if k.startswith("A") and v}))
        part_bc({"pid": int(pid), "max_c": args.max_c}, fi, cache, facts, fam, w,
                do_c=not args.no_c, sample=args.sample)
        if not args.no_d:
            art_map = {}
            if snap:
                try:
                    for a in bio.build_articles(facts, cache, llm.load_config()):
                        art_map[a.get("title")] = a
                except Exception as e:                    # noqa: BLE001
                    w("    （build_articles 取段落主语失败：%s）" % e)
            if art_map:
                aof = str(as_of or "")
                m = re.match(r"(\d{3,4})\.(\d{1,2})", aof)
                asof_tag = "%s_%02d" % (m.group(1), int(m.group(2))) if m else ""
                part_d({"dir": out_dir, "birth_tag": birth_tag, "pid": int(pid),
                        "asof_tag": asof_tag}, fi, cache, facts, art_map, w)
            else:
                w("    D 成稿回放：该战役无快照，段落主语无法还原 → 跳过（覆盖缺口）")
        w("  （本战役 %.1fs；累计异常 %d 条）" % (time.time() - t0, len(ISSUES)))
        w()
        del cache, fi, facts

    # ---- E 兼链宽度
    w("-" * 92)
    w("[E] 兼链宽度：能不能算出「儿子兼继子兼弟弟兼舅舅」（合成族谱，见 v108_probe_chain_width.py）")
    w("-" * 92)
    try:
        import v108_probe_chain_width as CW
        for label, kind in CW.CASES:
            r = CW.chain_of(kind)
            w("  %-38s 首词 %-6s 血缘词 %-22s 链 %s"
              % (label, r["word"], "、".join(r["blood"]), "兼".join(r["chain"]) or "（空）"))
            issue("E兼链(信息)", "%s → 链 %s（首词 %s）" % (label, r["chain"], r["word"]), {}, sample=0)
        w("  ⇒ 结论：血缘词上限 _KIN_CHAIN_BLOOD_MAX=%d；「儿子」与「继子」互斥（facts.py:1225-1228）；"
          % CW.chain_of("all")["max"])
        w("     三重身份（⑤）实测只出 %s："
          % "兼".join(CW.chain_of("all")["chain"]))
        w("      - 「弟弟」「舅舅」两条线在合成族谱里只写在 siblings 字段（探针 add(S,'siblings',C) 等），")
        w("        而 `_ancestor_routes`（facts.py:4814-4845）只沿 father/mother 边展开，"
          "siblings 字段不进路线表；")
        w("        真实缓存里这种「无共同记录父母」的兄弟边见 A 段 A12 统计。")
        w("      - 唯一进链的额外词「族伯叔」来自 C 之父 G 同时是 S 的外祖父这条路线"
          "（_kin_key_of_route facts.py:879-884，")
        w("        gap>0 时不看父系/母系，一律给族伯叔/族姑）：④ 单独一条舅舅边也会多出这个词。")
        w("      - v108 已修 `_parent_maps` 的 setdefault（facts.py:4799-4809 现保留全部父/母），"
          "三重身份不再丢线，但仍受上述两条所限。")
    except Exception as e:                                # noqa: BLE001
        w("  （E 段跳过：%s）" % e)
    w()

    # ---- F 已知改错复现
    w("-" * 92)
    w("[F] 已知改错复现：成稿原文里被 `_fix_kin_roles` 改错的五处（反身代词回指／引语窗口／"
      "同位语／领属者）直接跑一遍（tools/tests/v108_probe_d_repro.py）。")
    w("-" * 92)
    try:
        import v108_probe_d_repro as RP
        nbad = 0
        for label, src, subs, got, changed, keep in RP.run():
            ok = keep in got
            nbad += 0 if ok else 1
            w("  %-38s %s" % (label, "逐字保留 OK" if ok else "★被改错"))
            if not ok:
                w("      in : %s" % src)
                w("      out: %s" % got)
                issue("F改错复现", "%s：%s ⇒ %s" % (label, src, got), {"subjects": subs}, sample=0)
        w("  ⇒ 被改错 %d / %d 例（只统计真被改错的）；v108 起窗口不跨句末/右引号、"
          "无名句回退只在上一句以人名开头时采信、词与人名之间夹着别人时不成定语、"
          "无主「的」短语时最近的人名也能为该词作证。" % (nbad, len(RP.CASES)))
    except Exception as e:                                # noqa: BLE001
        w("  （F 段跳过：%s）" % e)
    w()

    w("=" * 92)
    w("汇总：异常 %d 条" % len(ISSUES))
    for k in sorted(COUNTS):
        w("  %-18s %d" % (k, COUNTS[k]))
    w("=" * 92)

    txt = os.path.join(ROOT, "logs", "v108_kin_sweep.txt")
    io.open(txt, "w", encoding="utf-8", newline="\n").write("\n".join(LINES) + "\n")
    if not args.no_json:
        js = os.path.join(ROOT, "logs", "v108_kin_sweep.json")
        io.open(js, "w", encoding="utf-8", newline="\n").write(
            json.dumps({"counts": dict(COUNTS), "issues": ISSUES}, ensure_ascii=False, indent=1))
    print("wrote %s (%d lines)" % (txt, len(LINES)))
    print("counts:", dict(COUNTS))


if __name__ == "__main__":
    main()
