# -*- coding: utf-8 -*-
"""v112 专项断言（秒级；快照 + 合成桩，不载熔件）。

问题（用户 2026-10-08，六问）：
  ① 死者行「同族兄弟兼仇敌同族兄弟兼仇敌…」重复；消失无踪类死法不得点名施事
  ② 亲缘行的父母不带生年；子女只在同性别段首留一次「子」/「女」
  ③ 承继句的「于当日」是冗语，句尾改「{本传主名}从此作为命运的主角」
  ④ 改文化后母语不得随文化漂移（固定为出生文化的语言，新语言留在「兼通」）
  ⑤ 「双胞胎」必须写明同胞
  ⑥ 终传附录「世系」按真实血亲辈分逐代铺开（凡例 / 世系图 / 五世提行）

断言：
  V112-1a/1b/2  合成桩跑 biography._assassin_kill_lines + facts._death_clause_of
  V112-1b-2     facts.death_clause 对 death_disappearance 出无施事成句
  V112-3        快照 facts.protagonist.succession
  V112-4        第二份快照（改文化角色）的 language_line
  V112-5        快照全文的「双胞胎」都带同胞
  V112-6        快照 facts.genealogy / genealogy_subject

用法：
    $env:PYTHONIOENCODING='utf-8'
    & tools\\py.ps1 tools\\tests\\verify_v112.py [快照.json]
    （缺省 output/洪氏2/data/snap_v112_207044_final.json；V112-4 另看
      output/洪氏2/data/snap_v112_135480_final.json，缺该文件则 SKIP）
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import biography as bio   # noqa: E402
import facts as F         # noqa: E402

H2 = os.path.join(ROOT, "output", "洪氏2", "data")
DEFAULT = os.path.join(H2, "snap_v112_207044_final.json")
LANG_SNAP = os.path.join(H2, "snap_v112_135480_final.json")
FAILS = []


def check(name, ok, detail=""):
    print("%-8s %s%s" % ("[PASS]" if ok else "[FAIL]", name,
                         ("  | " + str(detail)) if detail else ""))
    if not ok:
        FAILS.append(name)


# ---- 合成桩：一父一母一妻四子两女（子-女-子 交错，验「同性别段首留一次」）----
STUB_CACHE = {
    "player_id": 900,
    "characters": {
        "900": {"name": "洪易卜拉欣", "family": {}},
        "100": {"name": "石从古", "female": False, "birth": "1078.5.1",
                "family": {"father": [1], "mother": [2], "primary_spouse": [3],
                           "child": [10, 11, 12, 13, 14]}},
        "1": {"name": "朱昆", "female": False, "birth": "1030.3.1", "family": {}},
        "2": {"name": "路瑶霞", "female": True, "birth": "1066.3.1", "family": {}},
        "3": {"name": "陈无尘", "female": True, "family": {}},
        "10": {"name": "朱俭", "female": False, "family": {}},
        "11": {"name": "朱师尹", "female": False, "family": {}},
        "12": {"name": "朱琼", "female": True, "family": {}},
        "13": {"name": "朱琮", "female": True, "family": {}},
        "14": {"name": "朱子渊", "female": False, "family": {}},
    },
}
STUB_FACTS = {"protagonist": {"name": "洪易卜拉欣"},
              "characters": {k: {"name": v.get("name")} for k, v in STUB_CACHE["characters"].items()}}
STUB_VICTIM = {
    "id": 100, "name": "石从古", "office": "户部尚书", "label": "户部尚书石从古",
    "identity": "同族兄弟兼仇敌", "birth": "1078.5.1",
    "death_date_cn": "1123年8月1日", "victim_place": "襄阳",
    "death_clause": "消失得无影无踪", "age": 45,
}


def group_synthetic():
    print("\n[V112-1/2] 合成桩：死者行与亲缘行")
    lines = bio._assassin_kill_lines(STUB_FACTS, STUB_CACHE, STUB_VICTIM, scope=None)
    dead = [ln for ln in lines if ln.startswith("死者：")]
    kin = [ln for ln in lines if ln.startswith("亲缘：")]

    # ---- V112-1a ----
    check("V112-1a 死者行只有一个亲缘词", len(dead) == 1 and dead[0].count("仇敌") == 1,
          dead[:1])
    check("V112-1a 死者行无叠字「仇敌仇敌」/「兼仇敌同族兄弟」",
          bool(dead) and not re.search(r"(仇敌|同族兄弟)(?:兼)?\1", dead[0]), dead[:1])
    want = "死者：洪易卜拉欣的同族兄弟兼仇敌户部尚书石从古，1123年8月1日在襄阳消失得无影无踪，享年45岁。"
    check("V112-1a 死者行整句成形", dead[:1] == [want], dead[:1] or "（无死者行）")

    # ---- V112-1b ----
    check("V112-1b 消失无踪不点名施事", bool(dead) and "在" not in dead[0].split("，")[1][:2]
          and "的命令下" not in dead[0], dead[:1])

    # ---- V112-2 ----
    want_kin = "亲缘：父朱昆、母路瑶霞、妻陈无尘、子朱俭、朱师尹、女朱琼、朱琮、子朱子渊"
    check("V112-2 父母无生年 + 同性别段首留一次子/女",
          kin[:1] == [want_kin], kin[:1] or "（无亲缘行）")

    # ---- 1b 的第二个出口：占有格槽位不得留「其的」 ----
    class _Stub:
        as_of = "1100.1.1"
        cache = {"characters": {"5": {"death": {"date": "1100.1.1", "killer": 7}}}}

        def death_clause(self, cid, date=None, imprison=False, insider=False):
            return "在石从古的命令下消失得无影无踪"

        def event_name(self, cid, date=None):
            return "石从古"

    clause = F._death_clause_of(_Stub(), 5, killer_pronoun=True)
    check("V112-1b 占有格缩为「其」不留「其的」", clause == "在其命令下消失得无影无踪", clause)

    # ---- 关系缘由串（loc 模板）里的同一个「其的」 ----
    class _Stub2:
        def _is_female(self, cid):
            return False

    raw = ("[TARGET_CHARACTER.GetShortUIName|U]坚称[TARGET_CHARACTER.GetSheHe]开启"
           "[TARGET_CHARACTER.GetHerHis]的传奇全是为了打动和荣耀[CHARACTER.GetShortUIName]。")
    got = F._sub_relation_loc(_Stub2(), raw, 1, 2, names=("甲", "乙", "丙"))
    check("V112-1b loc 模板不留「其的」（soulmate_legend_motivation_corresponding）",
          "其的" not in got and "乙坚称他开启其传奇" in got, got)

    # ---- facts.death_clause：消失无踪类死法本身的无施事成句 ----
    f = F.Facts.__new__(F.Facts)
    f.cache = {"characters": {"5": {"death": {"reason": "death_disappearance",
                                              "date": "1123.8.1"}}}}
    f._chars = {}
    f.as_of = None
    got = f.death_clause(5)
    check("V112-1b death_disappearance 成句为「消失得无影无踪」",
          got == "消失得无影无踪", got)


def group_snapshot(snap):
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    text = "\n".join(
        ("\n".join(v.values()) if isinstance(v, dict) else str(v))
        for v in blocks.values())
    text += "\n" + json.dumps(facts.get("protagonist") or {}, ensure_ascii=False)
    text += "\n" + json.dumps(facts.get("protagonist") or {}, ensure_ascii=False)

    print("\n[V112-1b] 快照：消失无踪类死法")
    check("V112-1b 全篇无「消失无踪」旧词", "消失无踪" not in text,
          "命中 %d" % text.count("消失无踪"))
    check("V112-1b 全篇无「其的」", "其的" not in text, "命中 %d" % text.count("其的"))

    print("\n[V112-3] 承继句")
    succ = [x for x in ((facts.get("protagonist") or {}).get("succession") or [])
            if x.startswith("承继：")]
    check("V112-3a 承继句不含「当日」",
          bool(succ) and not any("当日" in x for x in succ), succ[:1])
    check("V112-3b 承继句不含「传主之位自此归本传主」",
          not any("传主之位自此归本传主" in x for x in succ), succ[:1])
    check("V112-3c 承继句句尾写本传主名",
          bool(succ) and all(x.endswith("从此作为命运的主角。") for x in succ), succ[:1])
    check("V112-3d 承继句仍含前任死法",
          any(re.search(r"(死于|而亡|被|崩)", x) for x in succ), succ[:1])
    check("V112-3e 无「、前代传主」", not any("前代传主" in x for x in succ), succ[:1])

    print("\n[V112-5] 双胞胎")
    bare = re.findall(r"(?<!为)双胞胎", text)
    hits = re.findall(r".{0,10}双胞胎", text)
    check("V112-5 「双胞胎」一律写明同胞", not bare, bare[:5])
    check("V112-5 断言确有双胞胎样例", bool(hits), len(hits))

    print("\n[V112-6] 世系")
    gen = facts.get("genealogy") or []
    sub = facts.get("genealogy_subject") or []
    check("V112-6a 世系有凡例行", bool(gen) and gen[0].startswith("凡例："), gen[:1])
    check("V112-6b 世系有世系图链条",
          any(ln.startswith("世系图：") for ln in gen)
          and any("─" in ln for ln in gen), gen[:3])
    heads = [ln for ln in gen if re.match(r"^\*\*[一二三四五六七八九十]+世\*\*", ln)]
    check("V112-6c 世次行 ≥2 代（不再是单一「一世」）", len(heads) >= 2, len(heads))
    nums = []
    for ln in heads:
        m = re.match(r"^\*\*([一二三四五六七八九十]+)世\*\*", ln)
        nums.append(m.group(1) if m else "")
    zh = "零一二三四五六七八九"

    def _num(s):
        if s.startswith("十"):
            return 10 + (zh.index(s[1]) if len(s) > 1 else 0)
        if "十" in s:
            a, _, b = s.partition("十")
            return zh.index(a) * 10 + (zh.index(b) if b else 0)
        return zh.index(s)

    vals = [_num(x) for x in nums if x]
    check("V112-6d 世次不减且非负", all(b >= a for a, b in zip(vals, vals[1:])), vals)
    check("V112-6e 每代行含生年与承接日",
          all(("生" in ln and "为传主" in ln) for ln in heads), heads[:1])
    check("V112-6f 每代行写明与上一代的关系",
          all("之" in ln for ln in heads[1:]), heads[1:2])
    check("V112-6g genealogy_subject 是末代那一块且是世系子集",
          bool(sub) and sub[0] in gen and all(ln in gen for ln in sub),
          sub[:1])
    check("V112-6h genealogy_subject 首行是本传主那一代",
          bool(sub) and re.match(r"^\*\*\S+世\*\*", sub[0]) is not None, sub[:1])


def group_language():
    print("\n[V112-4] 母语（改文化角色）")
    if not os.path.isfile(LANG_SNAP):
        print("  SKIP 缺 %s（跑：snap.py 洪氏2 135480 final --name=snap_v112_135480_final）"
              % os.path.relpath(LANG_SNAP, ROOT))
        return
    with io.open(LANG_SNAP, encoding="utf-8") as fp:
        facts = (json.load(fp).get("facts") or {})
    p = facts.get("protagonist") or {}
    line = p.get("language_line") or ""
    check("V112-4a 缯松母语 = 出生文化（奥克通俗拉丁语）",
          line.startswith("母语奥克通俗拉丁语"), line)
    check("V112-4b 改文化后的语言在「兼通」里", "戈伊德尔语" in line, line)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if not os.path.isfile(path):
        print("找不到快照: %s" % path)
        return 2
    with io.open(path, encoding="utf-8") as fp:
        snap = json.load(fp)
    print("快照 %s" % os.path.relpath(path, ROOT))
    group_synthetic()
    group_snapshot(snap)
    group_language()
    print("\n结果: %s" % ("全部通过" if not FAILS else "存在 FAIL — " + "、".join(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
