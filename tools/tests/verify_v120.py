# -*- coding: utf-8 -*-
"""v120 专项断言（秒级；纯函数 + 快照，不载熔件）。

用户 2026-10-10 两问（output/田所2，四位传主皆日本文化 119 + 大乘佛教淫梦宗）：
  ① 御前会议席名未动态化：「掌玺大臣/财政总管/军事统帅/间谍首脑/宫廷司祭…主教」
     —— `council_line` 只走键名猜测，没走游戏的 `name = { first_valid = … }` 臂链
     （日本政体应为：律令制 別当/家令/侍/目代，总领制 右笔/奉行/大将/目付）；
     司祭词则因 `_bishop_scope` 读 1.19 的 `religion.faiths`（1.20 已搬到 `faiths.database`）
     而宗教槽位恒空，落到通用 theocrat 臂 = 主教（应为 和尚）。
  ② 老年病被写成先天：「骨质脆弱自944年起获得」需模型自己拿 944 减生年 880，
     「为人」的体况组又只有病名 —— 改为「63岁获得骨质脆弱」。

断言：
  [1] 纯函数：`_age_phrase` 的年龄式与生年缺失时的年份回落
  [2] 纯函数：歧路守卫 —— `L.council_name_desc` 的日本臂链词 vs `L.council_seat_word` 的通用词
  [3] 快照：档案不再有「御前会议N席」「僚属任职」两行
  [4] 快照：特质履历/进阶为年龄式（无「自X年起获得」），且无「名词（名词）」括注
  [5] 快照：提示词面同样只见年龄式
  v122 (user)：两行花名册已删除，席名改挂在本人名字前，故 [3] 的断言改为「行不存在」。

用法：
    & tools\\py.ps1 tools\\tests\\verify_v120.py [快照...]
    （缺省 output/田所2/data/snap_v120_16801324.json）
"""
import glob
import json
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F             # noqa: E402
import localization as L      # noqa: E402

OK = True
H2 = os.path.join(ROOT, "output", "田所2")
DEFAULT = [os.path.join(H2, "data", "snap_v120_16801324_d4.json"),
           os.path.join(H2, "data", "snap_v120_16801324.json"),
           os.path.join(H2, "data", "snap_v120_38990_d1.json"),
           os.path.join(H2, "data", "snap_v120_38990_d2.json")]
# 日本政体应有的席名（键名猜测出的是通用词，见 [2]）
JP_FEUDAL = ("右笔", "奉行", "大将", "目付")
JP_ADMIN = ("別当", "家令", "侍", "目代")
GENERIC = ("掌玺大臣", "财政总管", "军事统帅", "间谍首脑")
# v122 (user): the two roster lines are gone; the .md assertion is on the rendered lines
COUNCIL_LINE = re.compile(r"御前会议[〇零一二三四五六七八九十百]+席")
RETAINER_LINE = re.compile(r"(廷中|营中|帐下)僚属任职")
PAREN = re.compile(r"（[^）]{1,24}）")
AGE_GAIN = re.compile(r"\d+岁获得")
YEAR_GAIN = re.compile(r"自\d{3,4}年起获得")
YEAR_LEVEL = re.compile(r"\d{3,4}年益进")


def check(name, cond, extra=None):
    global OK
    if not cond:
        OK = False
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f"   <- {str(extra)[:300]!r}" if extra is not None and not cond else ""))


def group_a():
    print("[1] 纯函数：年龄式写法 (_age_phrase)")
    fake = types.SimpleNamespace(_birth_of=lambda cid: "880.8.4",
                                 _year_only=F.Facts._year_only)
    # 亮四：生 880.8.4，特质履历记录日 944.1.1（快照日）→ 63 岁（未过生日）
    check("生880.8.4 × 944.1.1 → 63岁",
          F.Facts._age_phrase(fake, 1, "944.1.1") == "63岁",
          F.Facts._age_phrase(fake, 1, "944.1.1"))
    check("生880.8.4 × 955.1.1 → 74岁",
          F.Facts._age_phrase(fake, 1, "955.1.1") == "74岁")
    nobirth = types.SimpleNamespace(_birth_of=lambda cid: "",
                                    _year_only=F.Facts._year_only)
    check("生年缺失 → 回落年份「944年」",
          F.Facts._age_phrase(nobirth, 1, "944.1.1") == "944年")
    check("日期缺失 → 空串", F.Facts._age_phrase(fake, 1, None) == "")

    print("[2] 纯函数：日本席名的臂链词（歧路守卫）")
    tbl, cn = L.table(), L.council_names()
    tasks = L.council_tasks()
    want = {"japan_feudal": ("右笔", "奉行", "大将", "目付"),
            "japan_administrative": ("別当", "家令", "侍", "目代")}
    for gov, words in want.items():
        scope = {"tier": 3, "independent": True, "landless": False, "gov_flag": gov,
                 "is_governor_or_admin_count": False, "chaplain_female": False}
        got = tuple(L.loc(tbl, L.council_name_desc(
            cn, tasks["tasks"][t], scope))
            for t in ("task_foreign_affairs", "task_collect_taxes",
                      "task_train_commanders", "task_disrupt_schemes"))
        check(f"{gov} 臂链 → {'/'.join(words)}", got == words, got)
        # 键名猜测给的是通用词：正因如此 `council_line` 必须走臂链
        guessed = L.council_seat_word(tbl, tasks, "task_train_commanders",
                                      gov + "_government", False)
        check(f"{gov} 键名猜测仍是通用词（反证）", guessed == "军事统帅", guessed)
    check("司祭词在日本佛教臂下为「和尚」",
          L.loc(tbl, L.pick_bishop_title(
              L.bishop_titles(),
              {"tier": 3, "religion": "buddhism_religion", "religion_family": "rf_eastern",
               "heritage": "heritage_japonic", "pillars": {"language_japonic"},
               "gov_flag": "japan_feudal", "chaplain_female": False, "doctrines": []}))
          == "和尚")


def group_b(snap_path):
    print(f"[3][4][5] 快照传输面 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, f"缺 {snap_path}（先跑 tools/tests/snap.py）")
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    meta, facts = snap["meta"], snap["facts"]
    p = facts.get("protagonist") or {}
    council = p.get("council") or ""
    th = p.get("trait_history") or ""
    if meta.get("folder") != "田所2":
        print(f"  SKIP 田所2 专属断言 (folder={meta.get('folder')})")
        return
    surface = snap["shared"] + "".join(
        f"{m['system']}\n{m['user']}" for m in snap["messages"].values())
    # 两问都不限于传主本人：全事实面不得再出现通用席名（含他人宫廷的司祭席）
    hit = [w for w in GENERIC + ("宫廷司祭",) if w in surface]
    check("全事实面无通用席名", not hit, hit)
    if True:
        # v122 (user): the council roster line is gone from the profile and the seat words ride
        # on the councillors' own names instead, so the line itself must not appear.
        check("档案无「御前会议N席」行", not COUNCIL_LINE.search(surface),
              COUNCIL_LINE.findall(surface)[:2])
        check("档案无「僚属任职」行", not RETAINER_LINE.search(surface),
              RETAINER_LINE.findall(surface)[:2])
    check("特质履历存在", bool(th), th)
    check("特质履历为年龄式", bool(AGE_GAIN.search(th)) and not YEAR_GAIN.search(th), th)
    check("进阶行无年份式", not YEAR_LEVEL.search(th), th)
    check("特质履历无「名词（名词）」括注", not PAREN.search(th), th)
    check("提示词面无「自X年起获得」", not YEAR_GAIN.search(surface),
          YEAR_GAIN.findall(surface)[:3])


def group_c():
    """成稿面：重生成后的 output/田所2/*.md 不得再出现通用席名与「生而骨质脆弱」。

    v122 (user): the council roster line and the retainer roster line are gone from every piece,
    so their seat words no longer have a carrier at all; the assertion is now on the lines
    themselves (a model-written narrative mention of a council stays legitimate).
    「军事统帅」不列入（日常语里也讲得通）；「主教」不单列（「天主教」含此二字）。"""
    print(f"[6] 成稿面 ({os.path.relpath(H2, ROOT)}\\*.md)")
    files = sorted(glob.glob(os.path.join(H2, "*.md")))
    check("成稿存在", bool(files), H2)
    banned = ("宫廷司祭", "生而骨质脆弱")
    for p in files:
        t = open(p, encoding="utf-8").read()
        hits = [w for w in banned if w in t] + YEAR_GAIN.findall(t)
        if COUNCIL_LINE.search(t):
            hits.append("御前会议N席")
        if RETAINER_LINE.search(t):
            hits.append("僚属任职")
        check(f"{os.path.basename(p)} 无席名行/无先天写法/无年份式",
              not hits, hits[:4])


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    group_a()
    for a in argv or DEFAULT:
        if len(argv) > 1:
            print(f"=== {a} ===")
        group_b(os.path.abspath(a))
    if "--snap-only" not in sys.argv:
        group_c()
    print("\n结论: " + ("全部通过" if OK else "有失败项"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
