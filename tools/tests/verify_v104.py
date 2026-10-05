# -*- coding: utf-8 -*-
"""v104 专项断言（纯函数秒级 + 快照/材料面；不载熔件）。

用户 2026-10-05 六问（洪氏2，耀国·洪堡 pid 135480）：
  ① 大公会议/诏书的定夺不再丢（改礼前的礼也要读）
  ② 1057.9.1 那次核心教义宣示要读出来（改的是信仰主线礼）
  ③ 世俗型会议要写出「借…之手」的那个教士（傀儡槽）
  ④ 会议地点（有快照抓到才写，「{地名}大公会议」）
  ⑤ 融合文化经 name_list 反查 template，儿子应写「耀国·耀国松」
  ⑥ 家室材料分句 + roster 分组 + 兼链＝主亲缘→血缘(≤3)→关系(1)→官职(全部)

断言：
  [A] 纯函数：_rite_chain_rids / blood_kin_words_for 多路线 / _kin_key_of_route / 兼链口径
  [B] 快照：教会纪事（①②③④）、姓名面（⑤）、材料面（⑥）
  [C] 成稿：终传与十年 4/5/6（存在则断言）

用法：
    & tools\\py.ps1 tools\\tests\\verify_v104.py [快照...]
    （缺省 glob output/洪氏2/data/snap_v104*.json）
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

OK = True
H2 = os.path.join(ROOT, "output", "洪氏2")
FAILED = []


def check(name, cond, extra=None):
    global OK
    if not cond:
        OK = False
        FAILED.append(name)
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f"   <- {str(extra)[:400]!r}" if extra is not None and not cond else ""))


def stub(cache=None, as_of="1075.9.8"):
    """A Facts stand-in carrying only what the pure helpers read."""
    o = types.SimpleNamespace()
    o.cache = cache if cache is not None else {}
    o.as_of = as_of
    o.decade = None
    for name in ("_rite_chain_rids", "_one_rite_ruling_rows", "_rite_ruling_rows",
                 "_parent_maps", "_ancestor_routes", "blood_kin_words_for",
                 "blood_kin_word_for", "kin_word_for", "kin_chain_words_for",
                 "_spouse_kind_of", "merge_spouse_latch", "_court_positions_of", "_is_female",
                 "_kin_rev_index", "_spouse_back_index", "_faith_label",
                 "_faith_main_rite_rows", "_in_church_window", "_church_days",
                 "_clerical_puppet_at", "_alive_at", "_council_place", "_secular_council_phrase"):
        fn = getattr(F.Facts, name, None)
        if fn is None:
            continue
        raw = F.Facts.__dict__.get(name)
        if isinstance(raw, staticmethod):        # keep it unbound (no implicit self)
            setattr(o, name, fn)
        else:
            setattr(o, name, types.MethodType(fn, o))
    o._church_window = lambda: (None, None)
    o._KIN_CHAIN_BLOOD_MAX = F.Facts._KIN_CHAIN_BLOOD_MAX
    o._PUPPET_LOOKAHEAD_DAYS = F.Facts._PUPPET_LOOKAHEAD_DAYS
    o._COUNCIL_MATCH_DAYS = F.Facts._COUNCIL_MATCH_DAYS
    o._place_of_province = lambda prov: {1785: "圣地亚哥"}.get(prov, "")
    o._chars = {}
    o._is_female = lambda cid: False
    o.spouse_latch_rows = lambda as_of=None: []
    o.spouse_latch = None
    return o


# ------------------------------------------------------------------ [A] pure
def group_a():
    print("[A] pure helpers")
    # -- issue 1: the rite chain holds both rites, oldest first
    st = stub({"rite_tenets_history": {"185": [{"from": "1058.1.1"}],
                                       "154": [{"from": "1010.1.1"}]},
               "rite_doctrine_history": {"185": [{"from": "1058.1.1"}]}})
    check("[1] _rite_chain_rids is oldest-first over both latches",
          st._rite_chain_rids() == ["154", "185"], st._rite_chain_rids())

    # -- issue 6-B: a double blood route yields two words, a single one yields one
    chars = {
        "1": {"family": {"child": [2, 3]}},                       # G: father of F and U
        "2": {"family": {"father": [1], "child": [4]}},            # F: father of the subject
        "3": {"family": {"father": [1], "child": [5]}},            # U: father of C
        "4": {"family": {"father": [2], "primary_spouse": [5], "child": [6]},
              "female": False},                                    # subject S
        "5": {"family": {"father": [3], "spouse": [4], "child": [6]},
              "female": True},                                     # C, wife
        "6": {"family": {"father": [4], "mother": [5]}, "female": True},   # D: S's daughter by C
        "7": {"family": {"father": [4], "mother": [99]}, "female": True},  # V: plain daughter
    }
    st = stub({"characters": chars, "player_id": 4})
    st._is_female = lambda cid: bool((chars.get(str(cid)) or {}).get("female"))
    extra = st.blood_kin_words_for(6, 4)
    check("[6] double-route kin gives a second blood word",
          extra and extra[0] == "女儿" and len(extra) >= 2, extra)
    plain = st.blood_kin_words_for(7, 4)
    check("[6] a single route gives one word only", plain == ["女儿"], plain)
    check("[6] a route through the other person invents nothing",
          "族侄女" not in plain and "族甥女" not in plain, plain)

    # -- issue 6-B: a wife who is also the subject's daughter reads 妻子兼女儿
    chars2 = dict(chars)
    chars2["8"] = {"family": {"father": [4], "spouse": [4]}, "female": True}   # V2: S's daughter
    chars2["4"] = {"family": {"father": [2], "primary_spouse": [8], "child": [6]},
                   "female": False}
    st2 = stub({"characters": chars2, "player_id": 4})
    st2._is_female = lambda cid: bool((chars2.get(str(cid)) or {}).get("female"))
    st2.relation_word_for = lambda cid, subject: ""
    chain = st2.kin_chain_words_for(8, 4)
    check("[6] wife+blood chain reads 妻子 then 女儿", chain[:2] == ["妻子", "女儿"], chain)

    # -- issue 6-B: offices are appended, all of them, after the relation
    st3 = stub({"characters": chars, "player_id": 4, "court_positions": [
        {"date": "1075.1.1", "positions": [
            {"type": "councillor_marshal", "employee": 6, "hire_date": "1060.1.1"},
            {"type": "court_physician", "employee": 6, "hire_date": "1061.1.1"},
            {"type": "councillor_steward", "employee": 9, "hire_date": "1062.1.1"}]}]})
    st3.court_position_word = lambda t, cid=None: {
        "councillor_marshal": "军事总管", "court_physician": "私人医生"}.get(t, "")
    check("[6] the person's own court offices, in roster order",
          st3._court_positions_of(6) == ["军事总管", "私人医生"], st3._court_positions_of(6))
    st4 = stub({"characters": chars2, "player_id": 4})
    st4._is_female = lambda cid: bool((chars2.get(str(cid)) or {}).get("female"))
    st4.relation_word_for = lambda cid, subject: "仇敌"
    st4._court_positions_of = lambda cid, date=None: ["乳母", "处刑人"]
    chain4 = st4.kin_chain_words_for(8, 4)
    check("[6] order = kin, blood, relation, offices",
          chain4[:2] == ["妻子", "女儿"] and chain4[-3:] == ["仇敌", "乳母", "处刑人"], chain4)
    check("[6] blood words stay within three",
          len([x for x in chain4 if x in ("妻子", "女儿", "堂姐", "表妹", "族侄女")]) <= 3, chain4)

    # -- issue 6-B: route -> word mapping
    check("[6] first-cousin route maps to 堂/表 with seniority",
          F.kin_text(F._kin_key_of_route(2, 2, True, True, False, True)) == "堂兄",
          F.kin_text(F._kin_key_of_route(2, 2, True, True, False, True)))
    check("[6] maternal route maps to 表",
          F.kin_text(F._kin_key_of_route(2, 2, True, False, True, False)) == "表妹",
          F.kin_text(F._kin_key_of_route(2, 2, True, False, True, False)))

    # -- issue 3: the puppet lookahead (option b)
    st5 = stub({"puppet_history": [{"from": "1057.1.1",
                                    "puppets": [{"character": 16884508,
                                                 "type": "external_theological_agent_puppet"}]}]})
    st5._church_actor = lambda c, date=None: "教宗酒鬼玛尔定" if c.get("character") else ""
    st5.table = {}
    st5._PUPPET_LOOKAHEAD_DAYS = F.Facts._PUPPET_LOOKAHEAD_DAYS
    nm, tw = st5._clerical_puppet_at("1056.1.25")
    check("[3] a snapshot within the lookahead names the puppet", nm == "教宗酒鬼玛尔定", (nm, tw))
    nm2, _ = stub({"puppet_history": []})._clerical_puppet_at("1056.1.25")
    check("[3] no slot anywhere -> no name", nm2 == "", nm2)


# ------------------------------------------------------- [B] snapshot / material
def load_snaps(argv):
    paths = argv or sorted(glob.glob(os.path.join(H2, "data", "snap_v104*.json"))) \
        or sorted(glob.glob(os.path.join(H2, "data", "v104*.json")))
    out = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fp:
                out.append((os.path.basename(p), json.load(fp)))
        except Exception as e:                                        # noqa: BLE001
            print("   (skip", p, e, ")")
    return out


def all_messages(snap):
    msgs = snap.get("messages") or {}
    return {k: (v.get("system", "") + "\n" + v.get("user", ""))
            for k, v in msgs.items() if isinstance(v, dict)}


def group_b(snaps):
    print("[B] snapshots")
    if not snaps:
        check("[B] a v104 snapshot exists", False, "no snapshot found")
        return
    for name, snap in snaps:
        facts = snap.get("facts") or {}
        cc = facts.get("church_chronicle") or []
        msgs = all_messages(snap)
        blob = "\n".join(msgs.values())
        print(f"  -- {name}: church_chronicle {len(cc)} rows, messages {len(msgs)}")
        if not cc:
            continue
        if any("1057" in x for x in cc):
            line1057 = next((x for x in cc if x.startswith("1057年9月1日")), "")
            check(f"[2] {name} 1057 core declaration carries the swap",
                  "核心教义" in line1057 and "劳作即祈祷" in line1057, line1057)
            line1056 = next((x for x in cc if x.startswith("1056年1月25日")), "")
            check(f"[3] {name} secular council names the cleric",
                  "玛尔定" in line1056, line1056)
            line1059 = next((x for x in cc if x.startswith("1059年12月5日")), "")
            check(f"[4] {name} the 1059 council carries its place",
                  "圣地亚哥" in line1059, line1059)
            early = [x for x in cc if x.startswith(("1014年", "1021年"))]
            check(f"[1] {name} pre-conversion rulings are present",
                  any("改为" in x or "列为" in x for x in early), early)
        # issue 5: the son's name inside the material
        if "117484775" in json.dumps(facts, ensure_ascii=False)[:200000] or True:
            if "耀国·洪堡" in blob:
                check(f"[5] {name} the heir reads 耀国·耀国松",
                      "耀国·耀国松" in blob,
                      [x[:60] for x in re.findall(r"[^\s，。；、]{0,6}耀国·[^\s，。；、]{1,6}", blob)][:8])
        # issue 6-A: roster grouping and split sentences in the material
        if "这一房是" in blob:
            heads = re.findall(r"这一房是[^\n。]{0,120}", blob)
            check(f"[6] {name} the household roster is grouped",
                  any("妻妾：" in h and "子女：" in h for h in heads) if heads else True,
                  heads[:3])
        roster_dup = re.search(r"子女：([^；\n]{4,400})", blob)
        if roster_dup:
            names = [x for x in roster_dup.group(1).split("、") if x]
            check(f"[6] {name} no name repeats inside the child roster",
                  len(names) == len(set(names)), names[:12])


# ------------------------------------------------------------------ [C] prose
def group_c():
    print("[C] prose")
    # The v104 name fix renames the volumes too (耀国·洪堡 -> 耀国·缯松, the patronymic the engine
    # itself renders), so the terminal volume is looked up under either stem.
    final = ""
    for stem in ("耀国·缯松(1003)_终传_1075_09_08.md", "耀国·洪堡(1003)_终传_1075_09_08.md"):
        p = os.path.join(H2, stem)
        if os.path.exists(p):
            final = p
            break
    if not final:
        print("   (no terminal volume)")
        return
    with open(final, encoding="utf-8") as fp:
        txt = fp.read()
    print("   terminal:", os.path.basename(final))
    check("[3] the terminal volume names the cleric", "玛尔定之手" in txt,
          [l for l in txt.splitlines() if "借" in l and "大公会议" in l][:3])
    check("[4] a council place is written", "圣地亚哥大公会议" in txt,
          [l for l in txt.splitlines() if "大公会议" in l][:3])
    check("[2] the 1057 declaration carries its content",
          "1057年9月1日" in txt and "核心教义" in txt, "")
    # The user's own sentence: 于尔娃's marriage written with 安德烈斯 as HER son.
    for bad in ("她与儿子爱尔兰王子安德烈斯", "她嫁给了自己的儿子", "却成了他的女儿"):
        check(f"[6] no misread kinship: {bad}", bad not in txt, "")
    # Residual report (not a verdict): 「儿子」 following a name is still used for a sibling in the
    # children's own sections, where the shared protagonist profile lists his 子… beside the
    # section subject. Recorded in the plan's 6.3 rather than asserted away.
    residual = re.findall(r".{18}儿子[^，。；\n]{0,14}", txt)
    print(f"   (info) 「儿子…」 occurrences: {len(residual)}; sample: "
          f"{[x[-22:] for x in residual[:3]]}")
    check("[5] the heir is named 耀国·耀国松", "耀国·耀国松" in txt,
          [l[:80] for l in txt.splitlines() if "耀国·洪堡" in l][:3])


def main():
    group_a()
    group_b(load_snaps(sys.argv[1:]))
    group_c()
    print()
    print("FAILED:", len(FAILED), FAILED[:12])
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
