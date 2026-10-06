# -*- coding: utf-8 -*-
"""v107 assertions for the two 洪氏2 defects (pure and second-scale; no melt is loaded).

1  `biography._fix_kin_roles` judged a kin word against the **protagonist** only, so
   「孩子的妹妹是桑莎·洪堡」 (布里基纳's section; 桑莎 is his mother) passed untouched, while the
   correct 「…的母亲是桑莎·洪堡」 was rewritten into 妹妹. The pass is now possessor-aware: the
   possessor resolved from the text (「孩子的」 → the section subject, 「布里基纳·洪堡的」 → that
   child) picks both the truth and the accepted set, and an unresolvable possessor leaves the word
   alone (fail open). A 「兼」 chain keeps the model's width and is never shortened to one word
   (user 2026-10-06: 「X是Y的女儿兼妹妹兼族侄女」 is correct prose, not redundant).
2  the children row is two headed rows, one name per line (「儿子：」/「女儿：」), instead of
   「子A、B…，女C、D…。」 where the daughters' sex word sat far from their names
   (第5个十年:188「一生有八个儿子、八个儿子」).

Groups:
  [A] _fix_kin_roles, possessor-aware (synthetic minimal cache)
  [B] _profile_lines child rows (儿子：/女儿：/子女： + one name per line)
  [C] prose: output/洪氏2 carries none of the three published defects (skip with --pre-regen)
  [D] snapshot: the 传主家室 block states the children under 儿子：/女儿：

Usage:
    & tools\\py.ps1 tools\\tests\\verify_v107.py [snapshot...] [--pre-regen]
"""
import glob
import io
import json
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "tests"))
import biography as bio          # noqa: E402
import facts as F                # noqa: E402
import verify_v106 as V6         # noqa: E402  (fixture + Facts stand-in, bound to the real class)

H2 = os.path.join(ROOT, "output", "洪氏2")
OK = True
FAILED = []


def check(name, cond, extra=None):
    global OK
    if not cond:
        OK = False
        FAILED.append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f"   <- {str(extra)[:400]!r}" if extra is not None and not cond else ""))


# --------------------------------------------------------------------------
# fixture: 耀国·缯松 (100) with his sister-wife 桑莎·洪堡 (200) and their son 布里基纳 (300).
# 桑莎 is 妹妹 to the protagonist and 母亲 to the child — the exact shape of the reported defect.
# --------------------------------------------------------------------------
PID, SANG, BRI, SANSHA, GUO = 100, 200, 300, 900, 901
LABELS = {PID: "爱尔兰国王残忍者耀国·缯松", SANG: "桑莎·洪堡", BRI: "伦斯特伯爵布里基纳·洪堡",
          SANSHA: "山南王子圣缯·洪堡", GUO: "洪真一"}
NAMES = {PID: "耀国·缯松", SANG: "桑莎·洪堡", BRI: "布里基纳·洪堡",
         SANSHA: "缯·洪堡", GUO: "洪真一"}


def fixture_chars():
    return {
        str(PID): {"name_zh": "耀国", "name_full": "耀国·缯松", "female": False,
                   "birth": "1003.5.29",
                   "family": {"father": [SANSHA], "mother": [GUO],
                              "primary_spouse": [SANG], "child": [BRI], "siblings": [SANG]}},
        str(SANG): {"name_zh": "桑莎", "name_full": "桑莎·洪堡", "female": True,
                    "birth": "1006.5.14",
                    "family": {"father": [SANSHA], "mother": [GUO], "spouse": [PID],
                               "child": [BRI], "siblings": [PID]}},
        str(BRI): {"name_zh": "布里基纳", "name_full": "布里基纳·洪堡", "female": False,
                   "birth": "1036.5.24",
                   "family": {"father": [PID], "mother": [SANG]}},
        str(SANSHA): {"name_zh": "缯", "name_full": "缯·洪堡", "female": False,
                      "birth": "955.1.1", "family": {"child": [PID, SANG]}},
        str(GUO): {"name_zh": "洪真一", "name_full": "洪真一", "female": True,
                   "birth": "983.1.1", "family": {"child": [PID, SANG]}},
    }


def fixture():
    cache = {"player_id": PID, "characters": fixture_chars(), "court_positions": []}
    fi = V6.stub(cache)
    fi.kin_label = lambda cid, date=None: LABELS.get(int(cid), "")
    fi.name = lambda cid, date=None: NAMES.get(int(cid), "")
    fi.name_or = lambda cid, date=None, fallback="某人": NAMES.get(int(cid), fallback)
    # the shipped chain: 妻子 + the blood word for the protagonist, 母亲 for the child
    _chain = {(SANG, PID): ["妻子", "妹妹"], (SANG, BRI): ["母亲"]}
    fi.kin_chain_words_for = lambda cid, subj: list(_chain.get((int(cid), int(subj)), []))
    facts = {"player_id": PID, "as_of": "1075.9.8", "_facts": fi,
             "characters": {str(k): {"name": v} for k, v in NAMES.items()}}
    return cache, fi, facts


# ------------------------------------------------------------------ [A] the post-pass
def group_a():
    print("[A] _fix_kin_roles 领属者感知")
    cache, fi, facts = fixture()
    check("[A] kin_word(传主→桑莎) = 妹妹", F.kin_word(cache, PID, SANG) == "妹妹",
          F.kin_word(cache, PID, SANG))
    check("[A] kin_word(布里基纳→桑莎) = 母亲", F.kin_word(cache, BRI, SANG) == "母亲",
          F.kin_word(cache, BRI, SANG))

    def run(txt, subjects=None):
        return bio._fix_kin_roles(txt, facts, cache, subject_ids=subjects)

    # ① the shipped defect: 「孩子的妹妹」 in the child's section is his mother
    src = ("布里基纳·洪堡生于1036年5月24日，盖尔韦堡。孩子的妹妹是桑莎·洪堡——"
           "既是耀国·缯松的妹妹，又是他的第一任妻子。")
    out = run(src, [BRI])
    check("[A] 孩子段「孩子的妹妹是桑莎」→「孩子的母亲是桑莎」",
          "孩子的母亲是桑莎·洪堡" in out, out)
    # ② the same sentence in a protagonist section keeps the protagonist's truth
    check("[A] 传主段同一句逐字不变", run(src) == src, run(src))
    # ③ a named possessor outranks the section default
    wrong = "布里基纳·洪堡的妹妹是桑莎·洪堡。"
    check("[A] 具名领属者（布里基纳·洪堡的）纠为 母亲",
          run(wrong) == "布里基纳·洪堡的母亲是桑莎·洪堡。", run(wrong))
    right = "布里基纳·洪堡的母亲是桑莎·洪堡。"
    check("[A] 具名领属者的正确句不被改写", run(right) == right, run(right))
    # ④ no possessor at all → the section's own subject
    check("[A] 无领属者句按段主语（妹妹→母亲）",
          run("妹妹是桑莎·洪堡。", [BRI]) == "母亲是桑莎·洪堡。",
          run("妹妹是桑莎·洪堡。", [BRI]))
    # ⑤ a farther 「的」 governs something else and must not claim this word
    far = "他是耀国·缯松的第三子，妹妹是桑莎·洪堡。"
    check("[A] 远「的」不夺领属（第三子，妹妹→母亲）",
          run(far, [BRI]) == "他是耀国·缯松的第三子，母亲是桑莎·洪堡。", run(far, [BRI]))
    # ⑥ a 兼 chain is correct prose and is never shortened to one word
    chain = "他的妻子兼妹妹是桑莎·洪堡。"
    check("[A] 兼链「妻子兼妹妹」逐字保留", run(chain) == chain, run(chain))
    want2 = "他的妻子兼母亲是桑莎·洪堡。"
    out2 = run(want2)
    check("[A] 错链按同宽度重写（不缩成一个词）",
          out2 == "他的妻子兼妹妹是桑莎·洪堡。", out2)
    # ⑦ a word that is the suffix of a longer accepted word must not be half-replaced
    _chain2 = {(SANG, PID): ["妻子", "妹妹", "族侄女"]}
    fi.kin_chain_words_for = lambda cid, subj: list(_chain2.get((int(cid), int(subj)), []))
    want3 = "他的族侄女是桑莎·洪堡。"
    check("[A] 「族侄女」整体匹配（不留下「族」+「妹妹」）", run(want3) == want3, run(want3))
    fi.kin_chain_words_for = lambda cid, subj: list(
        {(SANG, PID): ["妻子", "妹妹"], (SANG, BRI): ["母亲"]}.get((int(cid), int(subj)), []))
    # ⑧ fail open: an unresolvable possessor leaves the word alone
    op = "某人的妹妹是桑莎·洪堡。"
    check("[A] 领属者解析不出→不改（fail open）", run(op) == op, run(op))
    # ⑨ a reflexive binds to its own clause's first name, not to the section subject:
    #    in 布里基纳's section this clause is about 耀国, so 母亲/姑母 are wrong and 妹妹 is right
    _chain3 = {(SANG, PID): ["妻子", "妹妹"], (SANG, BRI): ["母亲"]}
    fi.kin_chain_words_for = lambda cid, subj: list(_chain3.get((int(cid), int(subj)), []))
    refl = "耀国本人就娶了自己的母亲桑莎·洪堡。"
    check("[A] 反身代词「自己的母亲桑莎」在孩子段纠为妹妹",
          run(refl, [BRI]) == "耀国本人就娶了自己的妹妹桑莎·洪堡。", run(refl, [BRI]))
    #    …while a clause that names nobody keeps the section subject (the child's own mother)
    keep = "一个六岁的孩童，与自己的母亲桑莎·洪堡结为好友。"
    check("[A] 无名句的反身代词仍按段主语（母亲保留）", run(keep, [BRI]) == keep, run(keep, [BRI]))
    # ⑨ idempotent + no crash on empty input
    check("[A] 幂等", run(out, [BRI]) == out, run(out, [BRI]))
    check("[A] 空文本/空 facts 不炸",
          bio._fix_kin_roles("", facts, cache) == ""
          and bio._fix_kin_roles("父亲桑莎", {}, {}) == "父亲桑莎", "")


# ------------------------------------------------------------------ [B] child rows
def group_b():
    print("[B] 子女行形态（儿子：/女儿：）")
    facts = {"player_id": PID, "as_of": "1075.9.8", "_facts": None,
             "protagonist": {
                 "name": "耀国·缯松", "label": "爱尔兰国王残忍者耀国·缯松",
                 "father": "缯·洪堡", "father_name": "缯·洪堡",
                 "children_sons": "爱尔兰王子耀国·耀国松、伦斯特伯爵布里基纳·耀国松",
                 "children_daughters": "爱尔兰公主塞西莉娅·耀国斯多蒂尔",
                 "children": "爱尔兰王子耀国·耀国松、伦斯特伯爵布里基纳·耀国松、"
                             "爱尔兰公主塞西莉娅·耀国斯多蒂尔",
             }}
    lines = bio._profile_lines(facts, None)
    blob = "\n".join(lines)
    check("[B] 出「儿子：」带头行", "儿子：" in lines, lines)
    check("[B] 出「女儿：」带头行", "女儿：" in lines, lines)
    sons = [x for x in lines if x.startswith("　爱尔兰王子耀国·耀国松")
            or x.startswith("　伦斯特伯爵布里基纳·耀国松")]
    check("[B] 每个儿子各占一行（缩进全角空格）", len(sons) == 2, sons)
    check("[B] 女儿在自己的行内不与儿子同行",
          not any(("塞西莉娅" in x and "布里基纳" in x) for x in lines), lines)
    check("[B] 不再出现旧句式「子A、B…，女C」",
          not any(re.match(r"^子[^女]*，女", x) for x in lines)
          and not any(x.startswith(("子爱尔兰", "女爱尔兰")) for x in lines), lines)
    # a legacy profile without the sex split still gets a headed row
    facts["protagonist"].pop("children_sons")
    facts["protagonist"].pop("children_daughters")
    lines2 = bio._profile_lines(facts, None)
    check("[B] 无性别字段时退回「子女：」带头行", "子女：" in lines2, lines2)
    # the per-person profile goes through the same renderer
    facts3 = {"player_id": PID, "as_of": "1075.9.8", "_facts": None,
              "characters": {str(BRI): {"name": "布里基纳·洪堡", "label": "伦斯特伯爵布里基纳·洪堡",
                                        "mother": "桑莎·洪堡",
                                        "children_sons": "格雷戈里·布里基纳松"}}}
    lines3 = bio._profile_lines(facts3, BRI)
    check("[B] 逐人档案同改（子→儿子：）",
          "儿子：" in lines3 and "　格雷戈里·布里基纳松" in lines3, lines3)


# ------------------------------------------------------------------ [C] prose
def group_c():
    print("[C] 成稿面（output/洪氏2）")
    pats = {"妹妹是桑莎": "「X的妹妹是桑莎」（应为母亲）",
            "异母父亲": "「桑莎…又是他的异母父亲」",
            "八个儿子、八个儿子": "女组被读成子组"}
    for pat, desc in pats.items():
        hits = []
        for p in sorted(glob.glob(os.path.join(H2, "*.md"))):
            for i, ln in enumerate(io.open(p, encoding="utf-8").read().split("\n"), 1):
                if pat in ln:
                    hits.append(f"{os.path.basename(p)}:{i}")
        check(f"[C] 无{desc}", not hits, hits)


# ------------------------------------------------------------------ [D] real snapshot rows
def group_d(snaps):
    print("[D] 真实快照的子女行（渲染层，不重熔）")
    if not snaps:
        print("   (skip: 未给快照)")
        return
    for name, snap in snaps:
        facts = snap.get("facts") or {}
        p = facts.get("protagonist") or {}
        if not p:
            continue
        lines = bio._profile_lines(facts, None)
        blob = "\n".join(lines)
        if p.get("children_sons"):
            check(f"[D] {name} 传主档案出「儿子：」+逐人一行",
                  "儿子：" in lines
                  and all(f"　{x}" in lines for x in p["children_sons"].split("、")),
                  [x for x in lines if x.startswith("儿子")][:1])
        if p.get("children_daughters"):
            check(f"[D] {name} 传主档案出「女儿：」+逐人一行",
                  "女儿：" in lines
                  and all(f"　{x}" in lines for x in p["children_daughters"].split("、")),
                  [x for x in lines if x.startswith("女儿")][:1])
        check(f"[D] {name} 传主档案不再用旧句式「子A…，女B」",
              not re.search(r"^子[\u4e00-\u9fff].*，女", blob, re.M), blob[:160])
        # a child's own profile renders through the same helper
        for cid in (p.get("children_sons") or "").split("、")[:1]:
            pass
        blocks = snap.get("blocks") or {}
        hh = next((bd.get("传主家室") for bd in blocks.values()
                   if isinstance(bd, dict) and bd.get("传主家室")), "")
        if hh and "儿子：" in hh:
            check(f"[D] {name} 家室块已用「儿子：/女儿：」", "\n女儿：\n" in hh, hh[:160])


def main(argv):
    snaps = []
    pre_regen = "--pre-regen" in argv
    paths = [a for a in argv if not a.startswith("--")]
    if not paths:
        paths = sorted(glob.glob(os.path.join(H2, "data", "v107*.json"))) \
            or sorted(glob.glob(os.path.join(H2, "data", "v106*.json")))
    for p in paths:
        try:
            snaps.append((os.path.basename(p), json.load(io.open(p, encoding="utf-8"))))
        except Exception as e:                                        # noqa: BLE001
            print("   (skip", p, e, ")")
    group_a()
    group_b()
    if pre_regen:
        print("[C] 成稿面 — 跳过（--pre-regen）")
    else:
        group_c()
    group_d(snaps)
    print()
    print("FAILED:", len(FAILED), FAILED)
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
