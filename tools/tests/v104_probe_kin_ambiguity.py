# -*- coding: utf-8 -*-
"""v104 取证探针 2：家室歧义（问题 A）与亲缘兼词通道（问题 B）。

只读：不写任何生产文件，不整载 melt_*/player_*.json。
用 prompts.log 的实发素材行 + facts.py/biography.py 的符号锚点 + snap_v103.json 里
已算好的 kin_ids 做断言；另用「按已证实的亲缘边重建的最小 chars」调用纯函数 kin_key，
以确定它返回单值还是多值。

输出：logs/v104_kin_evidence.txt（UTF-8）
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import facts  # noqa: E402

OUT = os.path.join(ROOT, "logs", "v104_kin_evidence.txt")
LOG_REL = "logs/prompts.log"
PROMPTS = os.path.join(ROOT, "logs", "prompts.log")
SNAP = os.path.join(ROOT, "output", "洪氏2", "data", "snap_v103.json")

L = open(PROMPTS, encoding="utf-8").read().split("\n")
FAILS = []
out = []


def w(s=""):
    out.append(s)


def claim(ok, text):
    w(("  [OK]   " if ok else "  [FAIL] ") + text)
    if not ok:
        FAILS.append(text)


def at(n):
    """1-based prompts.log line."""
    return L[n - 1]


def find(pred, lo=1, hi=None):
    hi = hi or len(L)
    for i in range(lo, hi + 1):
        if pred(at(i)):
            return i
    return None


# ------------------------------------------------------------- 源码锚点工具
bio = open(os.path.join(ROOT, "biography.py"), encoding="utf-8").read().split("\n")
fa = open(os.path.join(ROOT, "facts.py"), encoding="utf-8").read().split("\n")


def cite(fname, lineno, expect, lines=None):
    src = lines if lines is not None else (bio if fname == "biography.py" else fa)
    s = src[lineno - 1]
    claim(expect in s, f"{fname}:{lineno} 含「{expect}」→ {s.strip()}")
    return s


# ---------------------------------------------------------------- 第 1 层 成稿
w("=" * 78)
w("第 1 层 · 成稿病句（output/洪氏2）")
w("=" * 78)
PROSE = {
    "output/洪氏2/耀国·洪堡(1003)_终传_1075_09_08.md:198": "她与儿子爱尔兰王子安德烈斯·洪堡成婚",
    "output/洪氏2/耀国·洪堡(1003)_终传_1075_09_08.md:198b": "于尔娃·洪堡又与儿子耀国·洪堡成婚",
    "output/洪氏2/耀国·洪堡(1003)_终传_1075_09_08.md:180": "本为耀国的女儿，1063年12月9日又与父亲成婚",
    "output/洪氏2/耀国·洪堡(1003)_传记_第6个十年_1070_01_01.md:176": "她嫁给了自己的儿子安德烈斯",
    "output/洪氏2/耀国·洪堡(1003)_传记_第6个十年_1070_01_01.md:176b": "她被儿子耀国·洪堡娶作妻室",
    "output/洪氏2/耀国·洪堡(1003)_传记_第6个十年_1070_01_01.md:162": "本是耀国的女儿，1063年12月9日却成了他的女儿",
}
for path, frag in PROSE.items():
    p = os.path.join(ROOT, path.split(":")[0])
    txt = open(p, encoding="utf-8").read()
    claim(frag in txt, f"{path.split(':')[0]}:{path.split(':')[1]} 含「{frag}」")
w()
w("同一篇内自相矛盾：终传:180 写「又与父亲成婚」（对），终传:198 写「与儿子…成婚」（错）。")
w()

# ------------------------------------------------- 第 2 层 素材（prompts.log）
w("=" * 78)
w("第 2 层 · 素材面（logs/prompts.log）")
w("=" * 78)
w("请求分块（`=====` 行）由 tools/tests/v104_probe_prompts.py 落盘，索引见 logs/v104_req_index.txt。")
w()

# 两个《家室列传·纪事·门庭恩怨》请求
REQ = {
    "十年6 · 家室列传 · 纪事·门庭恩怨·扎赫拉·奈特伦洼地等5房": (11222, 11529),
    "终传 · 家室列传 · 纪事·门庭恩怨·拉结·洪堡等9房": (13670, 14132),
}
# 传主档案「妻室…子…女…」行（问题 A 的直接触发素材）
WIFE_LINES = {
    11256: "十年6（截至1070）传主档案",
    13705: "终传 传主档案",
    14848: "终传（另一请求）传主档案",
}
for ln, tag in WIFE_LINES.items():
    s = at(ln)
    w(f"{LOG_REL}:{ln}  [{tag}]")
    w(f"    {s}")
    claim(s.startswith("妻室"), f"prompts.log:{ln} 是「妻室…」行")
    claim("于尔娃" in s, f"prompts.log:{ln} 含于尔娃")
    claim("安德烈斯" in s, f"prompts.log:{ln} 含安德烈斯")
    # 结构判据 1：该行末尾的「子…」列表里同时出现 于尔娃 的两位夫婿（安德烈斯、耀国）
    tail = s.split("，子", 1)
    sons = tail[1].split("，女", 1)[0] if len(tail) > 1 else ""
    claim("子" in s and "安德烈斯" in sons and "耀国·洪堡" in sons,
          f"prompts.log:{ln} 末尾「子…」列表含 于尔娃 的两位夫婿（安德烈斯+耀国）")
    w(f"    → 末尾子列表：子{sons}")
    # 结构判据 2：于尔娃 同现于「妻室」位 与 末尾「女」列表
    wives_part = s.split("，子", 1)[0]
    daus = s.split("，女", 1)[1] if "，女" in s else ""
    claim("于尔娃" in wives_part and "于尔娃" in daus,
          f"prompts.log:{ln} 于尔娃 同现于「妻室」位与「女」列表")
    w(f"    → 于尔娃 在该行出现 {s.count('于尔娃')} 次（妻室位 1 次 + 女列表 1 次 = 2）")
    w(f"    → 妻室段（`,` 子 之前）：{wives_part[-40:]}")
    w()

w("—— 同一请求内的身份自相矛盾（于尔娃 视角）——")
w()
w(f"{LOG_REL}:13901  ← 安德烈斯 只是「夫婿」（无亲缘词）")
w(f"    {at(13901)}")
w(f"{LOG_REL}:13907  ← 同一请求内，安德烈斯 又叫「兄长」（kin_key 算出来的正确词）")
w(f"    {at(13907)}")
w(f"{LOG_REL}:13908 / :13910  ← 两桩婚事都无亲缘词")
w(f"    {at(13908)}")
w(f"    {at(13910)}")
w()
claim(at(13907).find("兄长") >= 0, "prompts.log:13907 kin_key 已给出「兄长」")
claim("兄长" not in at(13901) and "安德烈斯" in at(13901),
      "prompts.log:13901 夫婿行未给亲缘词（同一人被读成两种身份）")
w()
w("—— 于尔娃 自己的档案头（kin_key 的正确血缘词在此）——")
for ln in (13897, 11341):
    w(f"{LOG_REL}:{ln}")
    w(f"    {at(ln)}")
    claim("本为爱尔兰国王残忍者耀国·洪堡之女儿" in at(ln),
          f"prompts.log:{ln} 已声明 于尔娃 是传主之女儿（blood_kin_word_for=女儿）")
    claim("入侍为其妻" not in at(ln) and "为耀国·洪堡之妻" not in at(ln),
          f"prompts.log:{ln} **没有**任何「今为其妻」的表态（只有过去的血缘）")
w()
w("⇒ 触发 3：consort_of_line 在 profile 自带婚姻行时**只写「本为…之女儿」、省掉当前妻号**")
for ln in (4698, 4699, 4700):
    w(f"    facts.py:{ln}  {fa[ln - 1].strip()}")
cite("facts.py", 4699, "if stated:", lines=fa)
w("    于是素材里 于尔娃→耀国 只有「过去的女儿」，`女` 列表又把她再列一次，")
w("    模型只能用同一侧的 `女` 补空，写出「本是他的女儿…却成了他的女儿」（十年6:162）。")
w()
w("—— 每次请求都重复下发同一段素材（同一错误每篇复现一次的机制）——")
wife_hits = [i for i in range(1, len(L) + 1) if at(i).startswith("妻室")
             and "于尔娃" in at(i) and "安德烈斯" in at(i)]
w(f"「妻室…」行含 于尔娃 且含 安德烈斯 的行数：{len(wife_hits)}")
w("   行号：" + ", ".join(str(x) for x in wife_hits))
claim(len(wife_hits) >= 3, "同一「妻室…子…安德烈斯…」句式在多篇请求里重复出现")
w()
w("—— 事件行的日期不是按时间排的（12月8日 排在 8月17日 之前）——")
for ln in range(13904, 13912):
    w(f"{LOG_REL}:{ln}    {at(ln)}")
_dates = [re.match(r"^\s*(\d+)年(\d+)月(\d+)日", at(ln)) for ln in range(13904, 13912)]
_pairs = [(int(m.group(1)), int(m.group(2)), int(m.group(3))) for m in _dates if m]
claim(_pairs != sorted(_pairs), "prompts.log:13904-13911 事件行顺序 ≠ 日期顺序（字符串排序）")
w()

w("—— 板块 roster：妻妾与子女混编成一条「、」列表，无分组标记（触发 2）——")
for ln in (11517, 14120):
    s = at(ln)
    m = re.search(r"这一房是([^。]*)", s)
    roster = m.group(1) if m else ""
    w(f"{LOG_REL}:{ln}")
    w(f"    这一房是{roster}")
    claim(roster.count("于尔娃") >= 2,
          f"prompts.log:{ln} roster 里 于尔娃 出现 {roster.count('于尔娃')} 次（妻妾位+子女位）")
    items = roster.split("、")
    for i, x in enumerate(items):
        if "于尔娃" in x and i + 1 < len(items):
            w(f"    → 于尔娃 之后紧邻的名单项：{items[i + 1]}（无分组标记，可读成她的子嗣）")
            break
    w()
w("拼装处：biography.py `_mid_req_for_group`")
for ln, exp in ((2738, 'who = "、".join(names) if names else label'),
                (2756, 'head += f"这一房是{who}。"')):
    cite("biography.py", ln, exp)
    w(f"    biography.py:{ln}  {bio[ln - 1].strip()}")
w()

# ------------------------------------------------- 第 3 层 板块器 / 渲染
w("=" * 78)
w("第 3 层 · 程序侧：「妻室…子…女…」行是谁拼的")
w("=" * 78)

w()
w("【a】拼行处：biography.py `_profile_lines`")
w()
for ln, exp in ((779, 'spouse_lbl = "夫婿" if fem else "妻室"'),
                (793, 'if p.get("children_sons"):'),
                (794, 'fam_bits.append(f"子{p[\'children_sons\']}")'),
                (795, 'if p.get("children_daughters"):'),
                (796, 'fam_bits.append(f"女{p[\'children_daughters\']}")'),
                (801, '"，".join(fam_bits) + "。"')):
    cite("biography.py", ln, exp)
    w(f"    biography.py:{ln}  {bio[ln - 1].strip()}")
w()
w("⇒ 结论：妻室/前妻/妾 与 子/女 列表用**同一个 `，`** 连成一句（biography.py:801），")
w("  妻室列表内部却用 `；`（见下）——所以「于尔娃，本为其女儿，子A、B…」里")
w("  最后的 `，` 既是列表内分隔又是跨实体的主谓连接，模型把 `子…` 读成 于尔娃 的儿子。")
w()
w("【b】妻室列表与亲缘注：facts.py `_protagonist` 内的闭包 `_annotate`")
w()
for ln, exp in ((20373, "f.blood_kin_word_for(sid, pid)"),
                (20375, 'note = f"，本为其{_bk}"'),
                (20395, '("；" if noted else "、").join(out)')):
    cite("facts.py", ln, exp)
    w(f"    facts.py:{ln}  {fa[ln - 1].strip()}")
w()
w("⇒ 结论：妻室列表的分隔符是 `；`（facts.py:20395，仅当有注时），")
w("  亲缘注固定写成「，本为其X」（facts.py:20375）——**只有血缘词，且只有 1 个，且用「本为」**。")
w()
w("【c】于尔娃 的个人档案头：facts.py `consort_of_line`")
cite("facts.py", 4689, "bk = self.blood_kin_word_for(cid, pid)")
w(f"    facts.py:4689  {fa[4688].strip()}")
cite("facts.py", 4698, 'return f"本为{who}之{bk}" if stated else')
w(f"    facts.py:4698  {fa[4697].strip()}")
w()
w("【d】死亡事件行的亲缘词：facts.py `_mem_sentence`（kin_key 单值出口）")
cite("facts.py", 16422, "kin_key(f.cache, owner_id, other_id")
w(f"    facts.py:16422  {fa[16421].strip()}")
cite("facts.py", 16425, "_kw = kin_text(_k) if _k else \"\"")
w(f"    facts.py:16425  {fa[16424].strip()}")
w()
w("【e】逐人「行迹」的排序：facts.py:20821 是**字符串排序**")
cite("facts.py", 20821, "mems.sort()")
w(f"    facts.py:20821  {fa[20820].strip()}")
_m = sorted(["1063年12月8日，x", "1063年8月17日，y", "1063年9月12日，z"])
w(f"    验证：sorted(['1063年12月8日…','1063年8月17日…','1063年9月12日…']) → {_m}")
claim(_m[0].startswith("1063年12月"), "facts.py:20821 的 mems.sort() 把 12月 排在 8月 前")
w(f"    正确键应为 cl.date_key（cache_lib.date_key，('1063.12.8') -> (1063,12,8)）")
w()

# ------------------------------------------------- 第 4 层 kin_key 断言
w("=" * 78)
w("第 4 层 · kin_key 到底返回什么（单值？多值？）")
w("=" * 78)
w("不整载熔件：仅按快照已证实的亲缘边重建最小 chars 视图，再调用纯函数 kin_key。")
w("pid：耀国 135480｜扎赫拉 16924222｜于尔娃 16917443｜安德烈斯 83993097")
w()
YO, ZA, YU, AN = 135480, 16924222, 16917443, 83993097
CHARS = {
    str(YO): {"female": False, "birth": "1003.5.29",
              "family": {"primary_spouse": [ZA], "spouse": [YU], "child": [AN, YU]}},
    str(ZA): {"female": True, "birth": "1016.8.1",
              "family": {"spouse": [YO], "child": [AN, YU]}},
    str(YU): {"female": True, "birth": "1047.8.16",
              "family": {"father": [YO], "mother": [ZA], "siblings": [AN],
                         "primary_spouse": [AN], "spouse": [YO]}},
    str(AN): {"female": False, "birth": "1044.8.1",
              "family": {"father": [YO], "mother": [ZA], "siblings": [YU],
                         "primary_spouse": [YU]}},
}
CACHE = {"characters": CHARS}


def show(cid, subject, chars=None, tag=""):
    k = facts.kin_key(CACHE, subject, cid, chars=chars)
    wd = facts.kin_text(k) if k else ""
    w(f"    kin_key(subject={subject}, cid={cid}){tag} = {k!r}  →  {wd!r}")
    return k, wd


w("（1）安德烈斯 相对 于尔娃（夫婿边在位）")
show(AN, YU)
w("（2）安德烈斯 相对 于尔娃（先 mask_spouse_edges 抹掉婚姻边）")
_masked = facts.mask_spouse_edges(CHARS, (YU, AN))
k2, w2 = show(AN, YU, chars=_masked)
claim(w2 == "兄长", "抹掉婚姻边后 kin_key(于尔娃→安德烈斯) = 兄长（与 prompts.log:13907 一致）")
w()
w("（3）于尔娃 相对 耀国（夫婿边在位）")
k3, w3 = show(YU, YO)
w("（4）于尔娃 相对 耀国（抹掉婚姻边）—— 即 blood_kin_word_for(于尔娃, 耀国)")
_masked2 = facts.mask_spouse_edges(CHARS, (YU, YO))
k4, w4 = show(YU, YO, chars=_masked2)
claim(w4 == "女儿", "blood_kin_word_for(于尔娃, 耀国) = 女儿（与「本为其女儿」一致）")
w()
w("⇒ 结论：kin_key 返回**单个 key**（facts.py:809-812 文档串：\"Kinship key of cid relative")
w("  to subject …Blood relations win over affinal ones; '' when undecidable\"），")
w("  多词合成不在 kin_key，而在 Facts.kin_chain_words_for。")
w()

w("（5）是否已有多词「兼」通道？")
for ln, exp, where in (
        (4570, "def kin_chain_words_for(self, cid, subject):", fa),
        (4593, "return parts[:3]", fa),
        (1202, "def word_for(self, cid, facts, subject=None):", fa),
        (1221, 'w = "兼".join(parts)', fa),
        (1225, "def mark(self, cid, base, facts, date=None):", fa),
        (4632, 'return f"，曾为其{rank}" if ended else f"，兼为其{rank}"', fa)):
    cite("facts.py", ln, exp, lines=where)
    w(f"    facts.py:{ln}  {fa[ln - 1].strip()}")
w()
w("⇒ 已有：kin_chain_words_for 产出 [血缘词, 主亲缘词, 关系词] 且 **硬截断 parts[:3]**；")
w("  KinScope.word_for/mark 用「兼」连接；_sibling_spouse_note 已按 曾/兼 区分时态。")
w()

w("（6）同一对人物同时走两条血缘路径时，kin_key 只给一个词")
_dual = {
    "900": {"female": False, "birth": "1000.1.1", "family": {"child": [901]}},
    "901": {"female": True, "birth": "1020.1.1",
            "family": {"father": [900], "mother": [905]}},
    "902": {"female": False, "birth": "980.1.1", "family": {"child": [900, 903]}},
    "903": {"female": False, "birth": "1002.1.1", "family": {"father": [902]}},
    "905": {"female": True, "birth": "1002.1.1", "family": {"child": [901], "siblings": [903]}},
}
_dual = {k: v for k, v in _dual.items()}
# 900 的配偶 905 同时是 903 的妹妹 → 901 既是 900 的女儿，又是 900 的表侄女
_dual["900"]["family"]["spouse"] = [905]
_DUALC = {"characters": _dual}
_w6 = facts.kin_text(facts.kin_key(_DUALC, 900, 901))
w(f"    kin_key(subject=900, cid=901) = {_w6!r}（901 既是 900 的女儿，又是其妻方表侄女）")
claim(_w6 == "女儿", "两条血缘路径并存时 kin_key 只返回第一条（女儿），第二条（表侄女）丢失")
w(f"    ⇒ 想要「妻子兼女儿兼堂表妹」这种 3 个血缘词，kin_key 现有返回结构给不出；")
w(f"      需要新增「多条血缘路径枚举」，不能在 kin_key 上改返回值（调用方全是单值语义）。")
w()
w("（7）kin_chain_words_for 只在主词为姻亲/配偶时才补血缘词")
for ln in (4585, 4586, 4587, 4588, 4589):
    w(f"    facts.py:{ln}  {fa[ln - 1].strip()}")
claim("if not kin_key_is_blood(key):" in fa[4584],
      "facts.py:4585 血缘词仅在主词非血缘时追加（血缘+血缘的第二条被丢弃）")
w()

# ------------------------------------------------- 快照：已有 kin_ids
w("=" * 78)
w("第 5 层 · 快照 sidecar 断言（output/洪氏2/data/snap_v103.json，1.09MB，非熔件）")
w("=" * 78)
d = json.load(open(SNAP, encoding="utf-8"))
c = d["facts"]["characters"]
w(f"meta.as_of = {d['meta']['as_of']}｜melt = {d['meta']['melt']}｜characters 条目 {len(c)}")
for pid, nm in ((str(YU), "于尔娃"), (str(AN), "安德烈斯")):
    v = c.get(pid) or {}
    w(f"  {nm} pid={pid}: mother={v.get('mother')!r} spouses={v.get('spouses')!r}")
    w(f"      kin_ids={v.get('kin_ids')}")
ku = set(c.get(str(YU), {}).get("kin_ids") or [])
ka = set(c.get(str(AN), {}).get("kin_ids") or [])
claim(int(YU) in ka and int(AN) in ku, "快照 kin_ids 互含：程序把 于尔娃/安德烈斯 判为亲缘")
w()

w("=" * 78)
w(f"断言失败 {len(FAILS)} 条")
for f_ in FAILS:
    w("  - " + f_)
w("=" * 78)

open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(out))
print("wrote", OUT, len(out), "lines;", "FAILS =", len(FAILS))
for f_ in FAILS:
    print("  FAIL:", f_)
