# -*- coding: utf-8 -*-
"""v114 断言：① 家谱图的入赘女性与红线；② 世系头行出称谓；③ 封圣年（＋组装给提示词）；
④ 六世带「耀国二世」；⑤ 枢机写驻地。

用法:
    & tools\\py.ps1 tools\\tests\\verify_v114.py            # 读快照（秒级，不载熔件）
    & tools\\py.ps1 tools\\tests\\verify_v114.py --page     # 另核家谱数据与阅读页几何（需已重建）
    & tools\\py.ps1 tools\\tests\\verify_v114.py --melt     # 另用真数据核枢机驻地（载一次熔件）

事实面读 `output/洪氏2/data/snap_v114_207044_final.json`（tools/tests/snap.py 产物）；
②③⑤ 的纯逻辑部分用桩（不读盘），所以默认档不需要熔件。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import facts as F  # noqa: E402

FAIL = []
SNAP = os.path.join(ROOT, "output", "洪氏2", "data", "snap_v114_207044_final.json")

# ① the two beads the leak put under the wrong person, and the marriage the tree must now draw
WRONG_SPONSOR = 67210684            # 洪卡特琳: 11 beads were drawn beside her (the leaked latch)
CHAIN = [38957, 44503, 67172818, 16879059, 16878235, 135480, 117484775, 16945142, 207044]
EXPECT_PAIR2 = [44503, 38957, 45152, 16836925, 67172818]     # 洪天贵福 → 洪秀全 → 洪天香 → 洪地香 → 尼各老
EXPECT_SPOUSE = {38962: 38957, 43488: 44503, 16797282: 38957, 33633911: 67172818,
                 33652404: 67172818, 50427263: 16879059, 99598: 84824, 99599: 84824,
                 50359391: 16878235, 154984: 117484775, 174036: 117484775,
                 143983: 135480, 16924222: 135480, 16932304: 135480,
                 33698274: 135480, 50425741: 135480, 83989859: 135480,
                 16799381: 50403482}
EXPECT_ZHUFU = {17948: 45152, 16796290: 47113, 218995: 195339, 17739: 44308,
                17949: 16819207, 16832964: 16838713, 33602789: 50388317,
                117588739: 50498349, 161369: 134308845}
EXPECT_HEADS = [
    "**一世**　天皇帝穿刺者洪秀全，849年生，867年起为传主，904年11月30日卒",
    "**二世**　天皇帝堕邪者圣洪天贵福，洪秀全之子，869年8月6日生，904年11月30日继为传主，"
    "952年1月29日卒，970年封圣",
    "**四世**　教宗欢乐者尼各老，洪天贵福之外甥孙，917年4月11日生，952年1月29日继为传主，"
    "999年7月7日卒",
    "**四世**　山南王子洪审礼，尼各老之再从表弟，955年10月1日生，999年7月7日继为传主，"
    "1000年6月4日卒",
    "**四世**　山南王子圣缯·洪堡，洪审礼之兄，954年11月6日生，1000年6月4日继为传主，"
    "1009年6月26日卒，1051年封圣",
    "**五世**　爱尔兰至高王残忍者耀国·缯松，缯·洪堡之子，1003年5月29日生，1009年6月26日继为传主，"
    "1075年9月8日卒",
    "**六世**　爱尔兰至高王耀国二世·耀国松，耀国·缯松之子，1028年6月3日生，1075年9月8日继为传主，"
    "1085年5月10日卒",
    "**六世**　通州刺史时尚王子洪易卜拉欣，耀国·耀国松之弟，1059年5月18日生，1085年5月10日继为传主，"
    "1126年7月30日卒",
    "**七世**　鄯州节度使贪婪者洪七公，洪易卜拉欣之子，1109年4月25日生，1126年7月30日继为传主，"
    "1152年11月13日卒",
]
EXPECT_SAINTS = [
    "天皇女圣洪天香（二世）964年封圣",
    "天皇帝堕邪者圣洪天贵福（二世）970年封圣",
    "山南观察使谦卑者圣洪仁德（三世）1074年封圣",
    "山南王子圣缯·洪堡（四世）1051年封圣",
    "阿尔斯特雅尔圣科林布·耀国松（六世）1083年封圣",
]


def check(ok, label, detail=""):
    print(("  PASS " if ok else "  FAIL ") + label + (("  | " + str(detail)) if detail else ""))
    if not ok:
        FAIL.append(label)


def load_snap():
    with io.open(SNAP, encoding="utf-8") as fp:
        return json.load(fp)


class _Stub(F.Facts):
    """`Facts` shell for the pure-logic checks: every save lookup is a recorded constant."""

    def __init__(self, holds=None, names=None, table=None, chars=None, as_of="1152.11.13",
                 cache=None, campaign=None):
        self._lt = {str(t): {"key": k, "clerical_elector": 13} for t, k in (names or {}).items()}
        self._hold_cache = {}
        self._holder_intervals = holds or {}
        self._realm_holder_titles = {}
        self._realm_snaps = []
        self.table = table or {"cardinal_male": "枢机", "cardinal_female": "枢机"}
        self._chars = chars or {}
        self.as_of = as_of
        self.cache = cache or {}
        self.campaign = campaign or {}
        self.melt = {}

    # the save lookups `official_title` / `cardinal_seat` reach for
    def religious_head_word(self, cid):
        return ""

    def japan_top_office(self, cid, date=None):
        return ""

    def _anchor_date(self, cid, date=None):
        return date or self.as_of

    def _ministry_office_at(self, cid, date, include_former=False):
        return ""

    def clerical_region_word(self, cid, date=None):
        return ""

    def _has_current_landed_title(self, cid, date=None):
        return False

    def _dead_flavor_consistent(self, flavor, cid, date):
        return True

    def _generic_tier_flavor(self, flavor):
        return False

    def _name_at_date(self, tid, date=None):
        return (self._lt.get(str(tid)) or {}).get("display") or ""

    def title_base_name(self, tid):
        return ""


STUB_HOLDS = {98860: {"17600": [["986.11.26", None, "destroyed"]]},
              83949596: {"17556": [["1000.10.20", None, "destroyed"]]}}
STUB_NAMES = {17600: "d_cd_santa_agnese", 17556: "d_cd_san_lorenzo"}
STUB_TABLE = {"cardinal_male": "枢机", "cardinal_female": "枢机"}


def t_cardinal_logic():
    print("[5] 枢机驻地（桩：official_title 的两条枢机支路）")
    lt = {str(t): {"key": k, "clerical_elector": 13} for t, k in STUB_NAMES.items()}
    lt["17600"]["display"] = "圣依搦斯"
    lt["17556"]["display"] = "卢奇娜的圣老楞佐"
    st = _Stub(holds=STUB_HOLDS, names=STUB_NAMES, table=STUB_TABLE,
               chars={"98860": {"dead_data": {"flavor": "cardinal_male"}},
                      "83949596": {"dead_data": {"flavor": "cardinal_male"}}},
               as_of="1001.9.15")
    st._lt = lt
    check(st.cardinal_seat(98860, "987.4.13") == "圣依搦斯",
          "持有期内地名取自头衔名", st.cardinal_seat(98860, "987.4.13"))
    check(st.cardinal_seat(98860, "900.1.1") == "",
          "持有期之外不给地名（未获此职）", st.cardinal_seat(98860, "900.1.1"))
    check(st.cardinal_seat(1, "900.1.1") == "", "非枢机者空返回")
    check(st.official_title(98860, "987.4.13") == "圣依搦斯枢机",
          "flavor 支路交出「地名＋枢机」", st.official_title(98860, "987.4.13"))
    check(st.official_title(83949596, "1001.9.15") == "卢奇娜的圣老楞佐枢机",
          "另一位枢机的地名", st.official_title(83949596, "1001.9.15"))
    # no see resolvable → the bare word stays (never an empty title)
    st2 = _Stub(holds={}, names={}, table=STUB_TABLE,
                chars={"98860": {"dead_data": {"flavor": "cardinal_male"}}})
    check(st2.official_title(98860, "987.4.13") == "枢机", "无地名时仍是「枢机」",
          st2.official_title(98860, "987.4.13"))


def t_saint_since():
    print("[3] 封圣年（桩：跨缓存差分 + as_of 闸门）")
    src = {"sources": ["953.1.1", "964.1.1", "965.1.1", "970.1.1", "971.1.1", "999.1.1"],
           "characters": {"44503": {"trait_history": {"saint": [{"from": "971.1.1",
                                                                 "to": None, "first": False}]}}}}
    st = _Stub(as_of="1152.11.13", campaign={67172818: src}, cache={"player_id": 207044})
    check(st.saint_since(44503) == "970年", "相邻两年观测 → 取上一年", st.saint_since(44503))
    st_early = _Stub(as_of="960.1.1", campaign={67172818: src}, cache={"player_id": 207044})
    check(st_early.saint_since(44503) == "", "成稿早于封圣 → 不写", st_early.saint_since(44503))
    gap = {"sources": ["1070.1.1", "1081.1.1"],
           "characters": {"1": {"trait_history": {"saint": [{"from": "1081.1.1", "first": False}]}}}}
    st3 = _Stub(as_of="1152.11.13", campaign={9: gap}, cache={})
    check(st3.saint_since(1) == "1070年至1081年间", "存档相隔多年 → 区间", st3.saint_since(1))
    near = {"sources": ["1070.1.1", "1080.1.1", "1081.1.1"],
            "characters": {"1": {"trait_history": {"saint": [{"from": "1081.1.1",
                                                               "first": False}]}}}}
    st3b = _Stub(as_of="1152.11.13", campaign={9: near}, cache={})
    check(st3b.saint_since(1) == "1080年", "上一次观测在一年前 → 取该年", st3b.saint_since(1))
    first = {"characters": {"1": {"trait_history": {"saint": [{"from": "1127.1.1", "first": True}]}}}}
    st4 = _Stub(as_of="1152.11.13", campaign={9: first}, cache={})
    check(st4.saint_since(1) == "", "只有 first=True 的基线 → 不写", st4.saint_since(1))
    none = {"characters": {"1": {"trait_history": {}}}}
    st5 = _Stub(as_of="1152.11.13", campaign={9: none}, cache={})
    check(st5.saint_since(1) == "", "无特质履历 → 不写")


def heads_of(snap):
    return [ln for ln in (snap["facts"].get("genealogy") or []) if ln.startswith("**")]


def t_heads(snap):
    print("[1] 世系头行（② 称谓 / ④ 耀国二世）")
    heads = heads_of(snap)
    check(len(heads) == len(EXPECT_HEADS), "九位传主一行一位", len(heads))
    chain = (snap["facts"].get("genealogy_tree") or {}).get("chain") or []
    for i, want in enumerate(EXPECT_HEADS):
        got = heads[i] if i < len(heads) else ""
        check(got == want, f"{want.split('　')[0]} 头行逐字", got[:60])
    # generic form of ②: no head may be the bare name (a title, a 前 title or a saint prefix
    # stands in front of it). The regnal numeral sits inside the name (耀国二世·耀国松), so only
    # the last name segment must survive.
    for i, c in enumerate(chain):
        got = heads[i] if i < len(heads) else ""
        label = got.split("　")[-1].split("，")[0] if got else ""
        tail = (c.get("name") or "\0").split("·")[-1]
        check(label != c.get("name") and tail in label, f"{c.get('name')} 头行带称谓", label)
    check("爱尔兰至高王耀国二世·耀国松" in heads[6], "④ 六世带「耀国二世」", heads[6][:40])


def t_saints(snap):
    print("[2] 封圣年落进世系与事实块（③）")
    got = list(snap["facts"].get("saints") or [])
    check(got == EXPECT_SAINTS, "facts['saints'] 五人与年份逐字", got)
    check("，970年封圣" in (EXPECT_HEADS[1]), "二世头行末追加封圣年")
    check("，1051年封圣" in (heads_of(snap)[4] if len(heads_of(snap)) > 4 else ""),
          "四世缯·洪堡头行末追加封圣年")
    # the assembled block ships to the household article's own material
    blocks = snap.get("blocks") or {}
    hit = [k for k, v in blocks.items() if "970年封圣" in json.dumps(v, ensure_ascii=False)]
    check("jiashi_lead" in hit, "【封圣】块进《家室列传》", hit)
    check(all("（" in ln and "世）" in ln for ln in got), "每行带世次", got)


def t_tree(snap):
    print("[4] 家谱数据（① 配珠归位 / 母系红线 / 赘夫）")
    tree = snap["facts"].get("genealogy_tree") or {}
    nodes = {n["id"]: n for n in tree.get("nodes") or []}
    if not nodes:
        check(False, "快照含家谱数据")
        return
    check(not [n for n in tree["nodes"] if n.get("spouse_of") == WRONG_SPONSOR],
          "无配珠挂在洪卡特琳名下（闩存泄漏已修）")
    orphan = [x for x in nodes if x != CHAIN[0] and not nodes[x].get("parent")
              and not nodes[x].get("spouse_of")]
    check(not orphan, "每珠都有归属", [(x, nodes[x]["name"]) for x in orphan])
    for x, want in EXPECT_SPOUSE.items():
        got = (nodes.get(x) or {}).get("spouse_of")
        check(got == want, f"{x} 配于 {want}", got)
    for x, want in EXPECT_ZHUFU.items():
        n = nodes.get(x) or {}
        check(n.get("spouse_of") == want and n.get("spouse_word") == "赘夫",
              f"{n.get('name')} 为赘夫（{want}）", (n.get("spouse_of"), n.get("spouse_word")))
    check(nodes[67172818].get("parent") == 16836925, "尼各老挂母洪地香",
          nodes[67172818].get("parent"))
    p2 = (tree.get("pairs") or [[]])[1]
    check(p2 == EXPECT_PAIR2, "第二段传承走母系（洪天香→洪地香）", p2)
    check(not nodes[33611550].get("kids"), "洪地保不再挂着七名子女",
          nodes[33611550].get("kids"))
    check(set(nodes[16836925].get("kids") or []) >= {67172818}, "洪地香挂着尼各老")
    red = {(e[0], e[1]) for e in tree.get("red_edges") or []}
    for path in tree.get("pairs") or []:
        for u, v in zip(path, path[1:]):
            e = (u, v) if nodes[v].get("parent") == u else (
                (v, u) if nodes[u].get("parent") == v else None)
            check(e in red, f"红线含 {u}→{v}", e)
    check(not tree.get("unreachable"), "八段传承全部可闭合", tree.get("unreachable"))
    print(f"    珠 {len(nodes)} / 传主 {len(tree.get('chain') or [])} / 红线 "
          f"{len(red)} 段 / 赘夫 {len(EXPECT_ZHUFU)} 位")


def t_page():
    print("[6] 阅读页几何（复用 v113 的无头核对）")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import verify_v113 as V
    except Exception as e:                                        # noqa: BLE001
        check(False, "可导入 verify_v113", e)
        return
    before = len(V.FAIL)
    V.t_tree()
    V.t_layout_js()
    check(len(V.FAIL) == before, "v113 家谱几何全过", V.FAIL[before:])


def t_melt():
    print("[7] 枢机驻地（真数据，载一次熔件）")
    import cache_lib as cl
    data = os.path.join(ROOT, "output", "洪氏2", "data")
    cache = cl.load_cache(os.path.join(data, "player_207044.json"))
    melt = cl.load_melt(os.path.join(data, "melt_1155_01_01.json"))
    f = F.Facts(cache, melt, os.path.join(data, "names.json"), as_of=None)
    want = {98860: "圣依搦斯", 50426865: "圣斯德望", 67183293: "圣戴多禄",
            83949596: "卢奇娜的圣老楞佐"}
    for cid, seat in want.items():
        got = f.cardinal_seat(cid)
        check(got == seat, f"{cid} 驻地 {seat}", got)
        title = f.official_title(cid)
        check(title.startswith(seat), f"{cid} 称谓以驻地开头", title)


def main():
    if not os.path.exists(SNAP):
        print(f"缺少快照: {SNAP}\n先跑: python tools/tests/snap.py 洪氏2 207044 final "
              f"--name=snap_v114_207044_final")
        return 2
    snap = load_snap()
    t_heads(snap)
    t_saints(snap)
    t_saint_since()
    t_tree(snap)
    t_cardinal_logic()
    if "--page" in sys.argv:
        t_page()
    if "--melt" in sys.argv:
        t_melt()
    print("\n%s  (%d 项未过)" % ("全部通过" if not FAIL else "有失败", len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
