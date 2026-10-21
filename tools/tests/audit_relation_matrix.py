# -*- coding: utf-8 -*-
"""v126 关系矩阵 / 向量鲁棒性检查（只读，不调用 LLM）。

目的：不检查成稿文句，而是检查**现有程序算出来的关系**是否自洽：
  * 有向矩阵 M[a,b] = identity_parts(a, b)：a 是 b 的什么；
  * 同一对人的正反两个向量是否互为逆关系；
  * 词本身的性别、长幼是否与被描述者一致；
  * 一个向量里是否同时出现互斥词（母亲 + 儿子、妻子 + 丈夫…）；
  * 是否出现「单向有词、反向无词」的断链。

用法：
  & tools\\py.ps1 tools\\tests\\audit_relation_matrix.py [快照]
  & tools\\py.ps1 tools\\tests\\audit_relation_matrix.py --folder 杨氏 --pid 84537 \
        --as-of 971.1.1 --melt melt_971_01_01.json --pair 57868,84537 --max-people 60

默认快照 output/杨氏/data/snap_v125.json。报告与 TSV 落 logs/v126/。
"""
import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import cache_lib as cl          # noqa: E402
import facts as F               # noqa: E402

OUT_DIR = os.path.join(ROOT, "logs", "v126")
LINES = []
FAIL = 0
WARN = 0
ROWS = []


def w(s=""):
    LINES.append(str(s))
    print(s)


def check(name, ok, detail="", warn=False):
    global FAIL, WARN
    if ok:
        w("  PASS  " + name)
        return
    if warn:
        WARN += 1
        w("  WARN  " + name + (f"   [{detail}]" if detail else ""))
    else:
        FAIL += 1
        w("  FAIL  " + name + (f"   [{detail}]" if detail else ""))


# ---- word tables ---------------------------------------------------------------------------
_MALE_TAIL = ("父", "伯", "叔", "舅", "公", "哥", "弟", "兄", "子", "孙", "婿", "夫", "甥")
_FEMALE_TAIL = ("母", "姑", "姨", "姐", "妹", "女", "妻", "嫂", "媳", "婆")
_NEUTRAL = {"兄弟", "姊妹", "堂兄弟", "堂姊妹", "表兄弟", "表姊妹", "堂表兄弟", "堂表姊妹",
            "再从堂兄弟", "再从堂姊妹", "再从表兄弟", "再从表姊妹", "三从堂兄弟", "三从堂姊妹",
            "三从表兄弟", "三从表姊妹", "同族兄弟", "同族姊妹", "叔舅", "姑姨", "配偶",
            "姻亲兄弟", "姻亲姊妹"}
_SEX_OVERRIDE = {"大姑子": "F", "小姑子": "F", "大伯子": "M", "小叔子": "M",
                 "侄甥": "M", "侄甥女": "F", "妻子": "F", "新妇": "F"}
_OLDER = ("哥哥", "堂兄", "表兄", "再从堂兄", "再从表兄", "三从堂兄", "三从表兄",
          "姐姐", "堂姐", "表姐", "再从堂姐", "再从表姐", "三从堂姐", "三从表姐")
_YOUNGER = ("弟弟", "堂弟", "表弟", "再从堂弟", "再从表弟", "三从堂弟", "三从表弟",
            "妹妹", "堂妹", "表妹", "再从堂妹", "再从表妹", "三从堂妹", "三从表妹")
_SELF_INVERSE = {"兄弟", "姊妹", "配偶", "姻亲兄弟", "姻亲姊妹", "堂兄弟", "堂姊妹",
                 "表兄弟", "表姊妹", "同族兄弟", "同族姊妹",
                 "仇敌", "朋友", "情人", "连襟", "妯娌"}
_MUTEX = [
    {"父亲", "母亲"}, {"儿子", "女儿"},
]
_BASE_INVERSE = {
    "父亲": {"儿子", "女儿"}, "母亲": {"儿子", "女儿"},
    "儿子": {"父亲", "母亲"}, "女儿": {"父亲", "母亲"},
    "哥哥": {"弟弟", "妹妹"}, "弟弟": {"哥哥", "姐姐"},
    "姐姐": {"弟弟", "妹妹"}, "妹妹": {"哥哥", "姐姐"},
    "妻子": {"丈夫"}, "丈夫": {"妻子"},
    "岳母": {"女婿", "儿媳"}, "岳父": {"女婿", "儿媳"},
    "女婿": {"岳母", "岳父"}, "儿媳": {"岳母", "岳父", "公公", "婆婆"},
    "嫂": {"小叔子", "小姑子"}, "小叔子": {"嫂"},
    "堂兄": {"堂弟", "堂妹"}, "堂弟": {"堂兄", "堂姐"},
    "堂姐": {"堂弟", "堂妹"}, "堂妹": {"堂兄", "堂姐"},
    "表兄": {"表弟", "表妹"}, "表弟": {"表兄", "表姐"},
    "表姐": {"表弟", "表妹"}, "表妹": {"表兄", "表姐"},
}


def kin_sex_of(word):
    if not word or word in _NEUTRAL:
        return None
    if word in _SEX_OVERRIDE:
        return _SEX_OVERRIDE[word]
    if word.endswith(_MALE_TAIL):
        return "M"
    if word.endswith(_FEMALE_TAIL):
        return "F"
    return None


def seniority_of(word):
    if word in _OLDER:
        return "older"
    if word in _YOUNGER:
        return "younger"
    return None


def _sex(f, cid):
    try:
        return "F" if f._is_female(int(cid)) else "M"
    except Exception:                                      # noqa: BLE001
        return None


def _year(f, cid):
    try:
        return F._audit_year(f, int(cid))
    except Exception:                                      # noqa: BLE001
        return None


def _nm(f, cid):
    try:
        return F._audit_name(f, int(cid))
    except Exception:                                      # noqa: BLE001
        return str(cid)


def load(snap_path, folder, pid, as_of, melt_name, cache_name, decade):
    if snap_path:
        snap = json.load(open(snap_path, encoding="utf-8"))
        meta = snap.get("meta") or {}
        folder = folder or meta.get("folder") or ""
        pid = pid or meta.get("player_id")
        as_of = as_of or meta.get("as_of") or None
        decade = decade if decade is not None else meta.get("decade")
        melt_name = melt_name or meta.get("melt") or ""
        data = os.path.join(ROOT, "output", folder, "data")
        cache_path = os.path.join(data, f"player_{pid}.json")
        melt_path = os.path.join(data, melt_name)
        names = os.path.join(data, "names.json")
    else:
        data = os.path.join(ROOT, "output", folder, "data")
        cache_path = os.path.join(data, cache_name or f"player_{pid}.json")
        melt_path = os.path.join(data, melt_name or "")
        names = os.path.join(data, "names.json")
    if not os.path.isfile(melt_path):
        melt_path = cl.melt_file_exists(melt_path) or melt_path
    cache = json.load(open(cache_path, encoding="utf-8"))
    melt = cl.load_melt(melt_path)
    facts = F.build_facts(cache, melt, names, as_of=as_of, decade=decade, campaign=None)
    return facts, facts["_facts"], folder, pid, as_of


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snap", nargs="?", default="")
    ap.add_argument("--folder", default="")
    ap.add_argument("--pid", type=int, default=None)
    ap.add_argument("--as-of", default="")
    ap.add_argument("--decade", type=int, default=None)
    ap.add_argument("--melt", default="")
    ap.add_argument("--cache", default="")
    ap.add_argument("--pair", nargs="+", default=[])
    ap.add_argument("--max-people", type=int, default=60)
    args = ap.parse_args()
    snap = args.snap or (os.path.join(ROOT, "output", "杨氏", "data", "snap_v125.json")
                         if not args.folder else "")
    facts, f, folder, pid, as_of = load(
        snap, args.folder, args.pid, args.as_of, args.melt, args.cache, args.decade)
    ref = pid or (facts.get("player_id"))
    cast = facts.get("characters") or {}
    ids = []
    for k in cast:
        try:
            cid = int(k)
        except (TypeError, ValueError):
            continue
        if cid not in ids:
            ids.append(cid)
    pair = []
    for token in (args.pair or []):
        for x in str(token).replace(",", " ").split():
            if x.isdigit():
                pair.append(int(x))
    for cid in pair + [ref]:
        if cid is not None and cid not in ids:
            ids.append(cid)
    ids = ids[:max(1, args.max_people)]
    w(f"v126 关系矩阵：{folder}｜存档 {as_of}｜传主 {ref}｜人物 {len(ids)}")
    w(f"矩阵 {len(ids) ** 2:,} 个有序对（直接词，不含路径词）")

    M = {}
    for a in ids:
        for b in ids:
            M[(a, b)] = [wd for _cat, wd, _src in
                         (f.identity_parts(a, b, paths=False, date=as_of) or [])]

    # A. 自反为空
    bad_self = [c for c in ids if M[(c, c)]]
    check("自身关系为空", not bad_self, bad_self[:5])

    # B. 词面、性别、长幼、向量内互斥
    bad_word, bad_sex, bad_age, bad_mutex = [], [], [], []
    for (a, b), words in M.items():
        if not words:
            continue
        for wd in words:
            if not isinstance(wd, str) or not wd or "其" in wd or "的" in wd or "[" in wd:
                bad_word.append((a, b, wd))
                continue
            sx = kin_sex_of(wd)
            if sx and _sex(f, a) and sx != _sex(f, a):
                bad_sex.append((a, b, wd, _sex(f, a)))
            sen = seniority_of(wd)
            ya, yb = _year(f, a), _year(f, b)
            if sen and ya and yb and ya != yb:
                if sen == "older" and ya > yb:
                    bad_age.append((a, b, wd, ya, yb))
                if sen == "younger" and ya < yb:
                    bad_age.append((a, b, wd, ya, yb))
        for pair_words in _MUTEX:
            hit = pair_words & set(words)
            if len(hit) >= 2:
                bad_mutex.append((a, b, tuple(sorted(hit))))
    check("词面干净（无其/的/裸键）", not bad_word, bad_word[:5])
    check("性别蕴含与缓存性别一致", not bad_sex, bad_sex[:5])
    check("长幼词与生年一致", not bad_age, bad_age[:5])
    check("同一向量无互斥词", not bad_mutex, bad_mutex[:5])

    # C. 正反互逆 / 单向断链 / 同词双向
    one_way, bad_inv, same_both = [], [], []
    impossible_both = {"父亲", "母亲", "儿子", "女儿"}
    for (a, b), words in M.items():
        if a >= b:
            continue
        rev = M[(b, a)]
        if words and not rev:
            one_way.append((a, b, words))
        for wd in words:
            if wd in rev and wd in impossible_both:
                same_both.append((a, b, wd))
        for wd in words:
            inv = _BASE_INVERSE.get(wd)
            if inv and rev and not (inv & set(rev)):
                bad_inv.append((a, b, wd, tuple(rev)))
    check("无单向断链", not one_way, one_way[:5], warn=True)
    check("已知逆词在反向向量出现", not bad_inv, bad_inv[:5], warn=True)
    check("直系父母子女词不同时双向", not same_both, same_both[:5])

    # D. 指定传主的向量
    if ref is not None:
        w(f"\n== 传主 {ref} 的亲属向量 ==")
        for cid in ids:
            if cid == ref:
                continue
            words = M[(cid, ref)]
            if words or M[(ref, cid)]:
                w(f"  {_nm(f, cid)} -> {_nm(f, ref)}: {('、'.join(words)) or '—'}"
                  f"   ｜反向：{('、'.join(M[(ref, cid)])) or '—'}")
                if pair and cid in pair:
                    w(f"     [指定对] {_nm(f, cid)} 的向量：{'、'.join(words)}")

    # E. TSV
    tsv = os.path.join(OUT_DIR, "v126_relation_matrix.tsv")
    with open(tsv, "w", encoding="utf-8") as fp:
        fp.write("A\tA名\tB\tB名\t正向词\t反向词\n")
        for (a, b), words in sorted(M.items()):
            if a == b or not (words or M[(b, a)]):
                continue
            fp.write(f"{a}\t{_nm(f, a)}\t{b}\t{_nm(f, b)}\t"
                     f"{'、'.join(words)}\t{'、'.join(M[(b, a)])}\n")
    w(f"\n矩阵写出 {tsv}")
    txt = os.path.join(OUT_DIR, "v126_relation_matrix.txt")
    with open(txt, "w", encoding="utf-8") as fp:
        fp.write("\n".join(LINES) + f"\n\nFAIL = {FAIL}  WARN = {WARN}\n")
    w(f"报告写出 {txt}")
    print(f"\nFAIL = {FAIL}  WARN = {WARN}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
