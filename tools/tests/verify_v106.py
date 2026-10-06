# -*- coding: utf-8 -*-
"""v106 assertions for the three 洪氏2 defects (pure, second-scale; no melt is loaded).

  1-A the post-pass `biography._fix_kin_roles` rewrote a correct kin word into 父亲, because the
      father's bare `name_zh` (「耀国」) is a substring of his daughter's name; it must now match the
      longest, non-overlapping name span and keep every word the fact layer itself composes for that
      person (the 兼链 「妻子兼妹妹X」) or prints as the row's own marriage word (「配偶X」).
  1-B `facts._consort_row_entry` writes the composed chain in front of the name instead of the
      ambiguous trailing clause 「，本为其妹妹，原为父…之妻」.
  1-C the household half of 传主档案 ships only to the boards that need it.
  2   the archive no longer repeats the protagonist's full appellation.

Groups:
  [A] _fix_kin_roles counter-examples (synthetic cache; the real kin machinery is bound, not stubbed)
  [B] facts._consort_row_entry (兼链 prefix, 前妻/前妾 rows)
  [C] subjectless birth-rank / language rows, father row dedup, profile row heads
  [D] household-board gating (+ snapshot: block key sets)
  [E] prose: the two terminal volumes carry none of the published defects

Usage:
    & tools\\py.ps1 tools\\tests\\verify_v106.py [snapshot...]
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
import biography as bio          # noqa: E402
import facts as F                # noqa: E402

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
# fixture: a miniature 洪氏2 — the father's name_zh 「耀国」 is a bare substring of his daughter's
# name (the trigger), and that daughter is also the subject's wife (妻子兼妹妹).
# --------------------------------------------------------------------------
PID = 1
LABELS = {1: "爱尔兰国王耀国二世·耀国松", 2: "爱尔兰至高王残忍者耀国·缯松",
          3: "爱尔兰公主海伦·耀国斯多蒂尔", 5: "洪琰",
          7: "肯特女公爵埃德伯·索雷德斯多蒂尔", 8: "桑莎·洪堡"}
NAMES = {1: "耀国二世·耀国松", 2: "耀国·缯松", 3: "海伦·耀国斯多蒂尔",
         5: "洪琰", 7: "埃德伯·索雷德斯多蒂尔", 8: "桑莎·洪堡"}


def fixture_chars():
    return {
        "1": {"name_zh": "耀国松", "name_full": "耀国松", "female": False, "birth": "1028.6.3",
              "family": {"father": [2], "primary_spouse": [3, 5], "concubine": [7],
                         "former_spouses": [8], "child": [6], "siblings": [3, 8]}},
        "2": {"name_zh": "耀国", "name_full": "耀国·缯松", "female": False, "birth": "990.1.1",
              "family": {"child": [1, 3, 8]}},
        "3": {"name_zh": "海伦", "name_full": "海伦·耀国斯多蒂尔", "female": True,
              "birth": "1059.9.27", "family": {"father": [2], "primary_spouse": [1],
                                               "siblings": [1, 8]}},
        "5": {"name_zh": "洪琰", "name_full": "洪琰", "female": True, "birth": "1033.3.31",
              "family": {"spouse": [1]}},
        "6": {"name_zh": "比约恩", "name_full": "比约恩·耀国松", "female": False,
              "birth": "1066.1.1", "family": {"father": [1], "mother": [3]}},
        "7": {"name_zh": "埃德伯", "name_full": "埃德伯·索雷德斯多蒂尔", "female": True,
              "birth": "1040.1.1", "family": {"concubine": [1]}},
        "8": {"name_zh": "桑莎", "name_full": "桑莎·洪堡", "female": True, "birth": "1035.2.2",
              "family": {"father": [2], "former_spouses": [1], "siblings": [1, 3]}},
    }


def stub(cache=None, as_of="1085.5.10"):
    """A Facts stand-in carrying only what the pure helpers read (bound from the real class, so the
    kin chain under test is the shipped one)."""
    o = types.SimpleNamespace()
    o.cache = cache if cache is not None else {}
    o.as_of = as_of
    o.decade = None
    o._KIN_CHAIN_BLOOD_MAX = F.Facts._KIN_CHAIN_BLOOD_MAX
    o._chars = {}
    for name in ("_spouse_kind_of", "merge_spouse_latch", "_court_positions_of", "_is_female",
                 "_kin_rev_index", "_spouse_back_index", "_parent_maps", "_ancestor_routes",
                 "blood_kin_words_for", "blood_kin_word_for", "kin_word_for", "kin_chain_words_for",
                 "language_relation_lines"):
        fn = getattr(F.Facts, name, None)
        if fn is None:
            continue
        raw = F.Facts.__dict__.get(name)
        if isinstance(raw, staticmethod):
            setattr(o, name, fn)
        else:
            setattr(o, name, types.MethodType(fn, o))
    o.spouse_latch = None
    o.spouse_latch_rows = lambda as_of=None: []
    o.relation_word_for = lambda cid, subject: ""
    o.kin_label = lambda cid, date=None: LABELS.get(int(cid), "")
    o.name = lambda cid, date=None: NAMES.get(int(cid), "")
    o.name_or = lambda cid, date=None, fallback="某人": NAMES.get(int(cid), fallback)
    o.marriage_lineality_note = lambda a, b, wedding=None, before=None: ""
    return o


def fixture_facts(fi):
    return {"player_id": PID, "as_of": fi.as_of,
            "characters": {str(k): {"name": v} for k, v in NAMES.items()},
            "_facts": fi}


# ------------------------------------------------------------------ [A] the post-pass
def group_a():
    print("[A] _fix_kin_roles")
    chars = fixture_chars()
    cache = {"player_id": PID, "characters": chars, "court_positions": []}
    fi = stub(cache)
    facts = fixture_facts(fi)
    print("   true words:", {c: F.kin_word(cache, PID, c, chars=chars)
                             for c in (2, 3, 5, 7, 8)})
    print("   chains    :", {c: fi.kin_chain_words_for(c, PID) for c in (3, 7, 8)})

    def run(txt):
        return bio._fix_kin_roles(txt, facts, cache)

    # 1-A / 3: every one of these is what the model wrote and the archive agrees with.
    for label, txt in (
        ("council seat 配偶海伦", "御前会议六席：掌玺大臣哈夫丹、军事统帅西蒙·耀国松、"
                                  "配偶爱尔兰公主海伦·耀国斯多蒂尔、间谍首脑乔丹·耀国松。"),
        ("prose 第一位妻室是海伦", "他的第一位妻室是海伦·耀国斯多蒂尔，本为其妹妹，今为其妻。"),
        ("prose 第一位妻室是海伦（短名）", "他的第一位妻室是海伦，本为其妹妹，今为其妻。"),
        ("material 妻子兼妹妹海伦", "妻子兼妹妹爱尔兰公主海伦·耀国斯多蒂尔；妻子洪琰。"),
        ("material 妻子兼妹妹于尔娃", "妻子兼妹妹时尚公主于尔娃·耀国斯多蒂尔；妻子洪琰。"),
        ("archive 妻室海伦", "他的妻室海伦·耀国斯多蒂尔死于1085年。"),
    ):
        out = run(txt)
        check(f"[A] {label} 逐字节不变", out == txt, out)

    # the published corruption must be repaired, not preserved
    out = run("父亲爱尔兰公主海伦·耀国斯多蒂尔")
    check("[A] 已发布的「父亲海伦」被改回档案里的词",
          "父亲" not in out and "海伦·耀国斯多蒂尔" in out, out)
    out = run("他娶了姐姐桑莎·洪堡")
    check("[A] 长幼错误仍然纠正（姐姐→妹妹）",
          "姐姐" not in out and "妹妹桑莎" in out, out)
    out = run("他的兄长耀国·缯松")
    check("[A] 跨族错误仍然纠正（兄长→父亲）", out == "他的父亲耀国·缯松", out)
    out = run("第三位妹妹桑莎·洪堡，本为其妹妹")
    check("[A] 缯松卷素材句不再被改写", out == "第三位妹妹桑莎·洪堡，本为其妹妹", out)
    once = run("他的第一位妻室是海伦·耀国斯多蒂尔")
    check("[A] 幂等", run(once) == once, run(once))
    check("[A] 空文本/空 facts 不炸",
          bio._fix_kin_roles("", facts, cache) == ""
          and bio._fix_kin_roles("父亲海伦", {}, {}) == "父亲海伦")


# ------------------------------------------------------------------ [B] the consort rows
def group_b():
    print("[B] _consort_row_entry")
    cache = {"player_id": PID, "characters": fixture_chars(), "court_positions": []}
    fi = stub(cache)
    wife = F._consort_row_entry(fi, 3)
    check("[B] 妻室行以兼链开头（行首词由链承担）", wife.startswith("妻子兼"), wife)
    check("[B] 兼链带出血缘词且只一个血缘词",
          wife == "妻子兼妹妹" + LABELS[3], wife)
    check("[B] 行内不再写「，本为其」/「，原为父」",
          "本为其" not in wife and "原为父" not in wife, wife)
    plain = F._consort_row_entry(fi, 5)
    check("[B] 无血缘的妻只写婚词", plain == "妻子" + LABELS[5], plain)
    conc = F._consort_row_entry(fi, 7)
    check("[B] 妾行写「妾…」", conc.startswith("妾"), conc)
    former = F._consort_row_entry(fi, 8, kind="前妻")
    check("[B] 前妻行写「前妻兼妹妹…」", former.startswith("前妻兼妹妹"), former)
    former2 = F._consort_row_entry(fi, 5, kind="前夫")
    check("[B] 前夫行（无血缘）写「前夫…」", former2.startswith("前夫"), former2)
    check("[B] 行内不再出现父称",
          "缯松" not in "；".join(F._consort_row_entry(fi, c) for c in (3, 5, 7, 8)), "")


# ------------------------------------------------------------------ [C] dedup + row heads
def group_c():
    print("[C] 传主档案去重")
    chars = fixture_chars()
    cache = {"player_id": PID, "characters": chars}
    fi = stub(cache)
    fi.languages = lambda cid: {"1": ["戈伊德尔语"], "5": ["汉语", "拉丁语"]}.get(str(cid), [])
    fi.person_label = lambda cid, date=None, style=None: LABELS.get(int(cid), "")
    fi.is_matrilineal = lambda a, b, after=None, before=None: False
    line, pw = F._kin_counts_line(fi, PID, chars["1"]["family"], 2, chars["2"]["family"])
    check("[C] 出生排行句无主语（不再重复传主全称）", line == "在父亲子女中排老大。", line)
    check("[C] 排行句仍带父称", pw == "父亲", pw)
    rows = fi.language_relation_lines(PID)
    check("[C] 语言关系句无主语且不重复传主全称",
          len(rows) == 1 and rows[0].startswith("与洪琰无共通语")
          and LABELS[1] not in rows[0] and "他通戈伊德尔语" in rows[0], rows)

    # _profile_lines: row head dropped when the entries carry the marriage word themselves, and the
    # father row carries the bare name once the succession line has given his full appellation.
    facts = {"player_id": PID, "as_of": "1085.5.10", "_facts": None,
             "protagonist": {
                 "name": "耀国二世·耀国松", "label": "爱尔兰国王耀国二世·耀国松",
                 "father": "爱尔兰至高王残忍者耀国·缯松", "father_name": "耀国·缯松",
                 "succession": ["承继：1075年9月8日，其父、前代传主爱尔兰至高王残忍者耀国·缯松于当日疯癫而亡。"],
                 "spouses": "妻子兼妹妹爱尔兰公主海伦·耀国斯多蒂尔；妻子洪琰",
                 "children_sons": "爱尔兰王子比约恩·耀国松",
                 "kin_counts": "在父亲子女中排老大。", "kin_counts_parent": "父亲",
                 "siblings": "爱尔兰公主拉结·耀国斯多蒂尔",
             }}
    lines = bio._profile_lines(facts, None)
    blob = "\n".join(lines)
    check("[C] 妻室行不重复行首类别词", "妻室妻子" not in blob and "妻子兼妹妹" in blob, blob[:200])
    check("[C] 父行只留名（承继行已给全称）", "父耀国·缯松。" in lines, lines)
    check("[C] 传主全称在档案里只出现一次",
          sum(x.count("爱尔兰国王耀国二世·耀国松") for x in lines) <= 1, lines)
    before, house, after = bio._profile_lines(facts, None, household_split=True)
    hh = "\n".join(house)
    check("[C] 家室段含妻室行/父行/排行句",
          "妻子兼妹妹" in hh and "父耀国·缯松。" in hh and "排老大" in hh, hh)
    check("[C] 身份段不含家室行",
          "妻子兼妹妹" not in "\n".join(before) and "妻室" not in "\n".join(before), before)
    # the adjacent-duplicate gate also collapses a word repeated across the 「兼」 of a composed
    # attributive (the model writes 「妻子兼妻子」 when it copies a row loosely)
    check("[C] 「X兼X」折成一个", bio._dedup_adjacent_words("妻子兼妻子桑莎") == "妻子桑莎",
          bio._dedup_adjacent_words("妻子兼妻子桑莎"))
    check("[C] 普通重复仍折", bio._dedup_adjacent_words("妹妹妹妹") == "妹妹", "")
    check("[C] 不同词不折", bio._dedup_adjacent_words("妻子兼妹妹") == "妻子兼妹妹", "")


# ------------------------------------------------------------------ [D] board gating
def group_d(snaps):
    print("[D] 传主家室 块的板块闸")
    hh = ("benji", "jiashi", "secrets", "qizu", "feuds")
    for k in hh:
        check(f"[D] {k} 收家室段", bio._wants_household_block(k, 12345) is True)
    for k in ("friend", "enemy", "artifacts", "liyi", "chaoju", "assassins", "youxia", "qunying"):
        check(f"[D] {k} 不收家室段", bio._wants_household_block(k, 12345) is False)
    check("[D] friend/enemy 无本人档案时退回给家室段",
          bio._wants_household_block("friend", None) is True)
    # the model re-emits the intro's own title and the 【总纲】 placeholder as markdown headings; the
    # programmatic pair is the one that stays (a stray 「## 总纲」 shipped in the 135480 volume once)
    bio.llm.log = lambda *a, **k: None
    intro = ("# 《残忍者耀国·缯松传》\n> 家族：洪氏，洪堡｜人物：残忍者耀国·缯松\n"
             "## 总纲\n残忍者耀国·缯松，洪氏洪堡一脉。")
    check("[D] 总纲开头的「## 总纲」与标题行一并剥掉",
          bio._strip_intro_head(intro) == "残忍者耀国·缯松，洪氏洪堡一脉。",
          bio._strip_intro_head(intro))
    check("[D] 正文首句不被剥",
          bio._strip_intro_head("残忍者耀国·缯松，洪氏洪堡一脉。")
          == "残忍者耀国·缯松，洪氏洪堡一脉。", "")
    for name, snap in snaps:
        blocks = snap.get("blocks") or {}
        if not blocks:
            continue
        bad = []
        for bk, bd in blocks.items():
            if not isinstance(bd, dict):
                continue
            art = bk.split("_")[0]
            got = any("家室" in x for x in bd)
            if got != (art in hh):
                bad.append(f"{bk}:{got}")
        check(f"[D] {name} 家室块只出现在该收的板块", not bad, bad)
        for bk in ("liyi_lead", "artifacts_lead", "chaoju_lead"):
            ident = (blocks.get(bk) or {}).get("传主档案", "")
            bad = [x for x in ident.split("\n")
                   if re.match(r"^(妻子|丈夫|配偶|妻室|妾|男宠|前妻|前夫|前妾|前男宠)[\u4e00-\u9fff]", x)
                   or x.startswith(("子爱尔兰", "女爱尔兰", "儿子：", "女儿：", "子女："))]
            check(f"[D] {name} {bk} 身份段没有妻室/子女行", not bad, bad)


# ------------------------------------------------------------------ [E] snapshots
def load_snaps(argv):
    paths = argv or sorted(glob.glob(os.path.join(H2, "data", "snap_v106*.json"))) \
        or sorted(glob.glob(os.path.join(H2, "data", "v106*.json")))
    out = []
    for p in paths:
        try:
            with io.open(p, encoding="utf-8") as fp:
                out.append((os.path.basename(p), json.load(fp)))
        except Exception as e:                                        # noqa: BLE001
            print("   (skip", p, e, ")")
    return out


def group_e(snaps):
    print("[E] 素材快照")
    if not snaps:
        print("   (no v106 snapshot yet — run tools/tests/snap.py ... --name=v106_<pid>)")
        return
    for name, snap in snaps:
        blocks = snap.get("blocks") or {}
        archive = "\n".join(
            (bd or {}).get("传主档案", "") for bd in blocks.values() if isinstance(bd, dict))
        house = "\n".join(
            (bd or {}).get("传主家室", "") for bd in blocks.values() if isinstance(bd, dict))
        allb = "\n".join(
            x for bd in blocks.values() if isinstance(bd, dict) for x in bd.values())
        check(f"[E] {name} 素材里没有「，本为其」", "，本为其" not in allb,
              [x[:80] for x in allb.split("\n") if "，本为其" in x][:3])
        check(f"[E] {name} 素材里没有「，原为父」", "，原为父" not in allb,
              [x[:80] for x in allb.split("\n") if "，原为父" in x][:3])
        check(f"[E] {name} 兼链写进妻室行", "妻子兼" in house or "妻子兼" in allb,
              [x[:80] for x in house.split("\n") if "妻" in x][:3])
        check(f"[E] {name} 传主档案不重复传主全称",
              all(x.count("爱尔兰国王耀国二世·耀国松") <= 1
                  for x in archive.split("\n") if "爱尔兰国王耀国二世" in x),
              [x[:90] for x in archive.split("\n") if x.count("爱尔兰国王耀国二世") > 1][:3])


# ------------------------------------------------------------------ [F] prose
def group_f():
    print("[F] 成稿")
    vols = [("洪堡卷", "耀国·洪堡(1028)_终传_1085_05_10.md"),
            ("缯松卷", "耀国·缯松(1003)_终传_1075_09_08.md")]
    for label, fn in vols:
        p = os.path.join(H2, fn)
        if not os.path.exists(p):
            print("   (missing", fn, ")")
            continue
        with io.open(p, encoding="utf-8") as fp:
            txt = fp.read()
        for bad in ("父亲爱尔兰公主", "本是他的父亲", "本为耀国松之父亲",
                    "本为妹妹的桑莎", "本为其妹妹的桑莎"):
            check(f"[F] {label} 无「{bad}」", bad not in txt,
                  [x[:70] for x in txt.splitlines() if bad in x][:2])


def main():
    group_a()
    group_b()
    group_c()
    snaps = load_snaps(sys.argv[1:])
    group_d(snaps)
    group_e(snaps)
    group_f()
    print()
    print("FAILED:", len(FAILED), FAILED[:12])
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
