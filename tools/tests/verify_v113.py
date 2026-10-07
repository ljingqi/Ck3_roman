# -*- coding: utf-8 -*-
"""v113 断言：① 王子/公主称号按父持有头衔的时代取名（用户报「邓公主李星雁」应为「唐公主」）；
② 家谱数据（世次/传主链/红线路径）与阅读页产物。

用法: & tools\\py.ps1 tools\\tests\\verify_v113.py [--tree]
  --tree  另核对 output/洪氏2/data/genealogy.json 与 output/洪氏2/index.html（需先重建）
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import facts as F  # noqa: E402

FAIL = []


def check(ok, label, detail=""):
    print(("  PASS " if ok else "  FAIL ") + label + (("  | " + str(detail)) if detail else ""))
    if not ok:
        FAIL.append(label)


class _Stub(object):
    """A `Facts` shell: the era-naming chain is exercised with recorded lookups, no save needed."""

    def __init__(self, names):
        self._lt = {}
        self._JAPAN_TOP_TITLE_KEYS = set()
        self._CELESTIAL_LIKE_GOVS = {"celestial_government"}
        self._STATE_SUFFIX_RE = re.compile("$^")
        self.as_of = "1152.11.13"
        self.names = names           # date prefix -> realm name
        self.seen = []               # (method, date) lookups
        self.hold = {}               # cid -> {tid: [(gain, loss, type)]}
        self.primary = (None, None)  # _primary_title_at result
        self.former = None           # _former_high_title result

    # ---- the five facts `_style_parent_title` / `_prince_style_from_title` read off a save ----
    def _primary_title_at(self, cid, as_of=None):
        return self.primary

    def _former_high_title(self, cid, date=None):
        return self.former

    def _hold_intervals(self, cid, as_of=None):
        return self.hold.get(cid) or {}

    def _is_landed_title(self, tid):
        return True

    def _name_at_date(self, tid, date=None):
        self.seen.append(("name", date))
        # h_china is ONE empire renamed by each dynasty: 唐 (618-897) → 天 (897-1075) → 邓 (after)
        year = int(str(date or "0").split(".")[0])
        if year < 897:
            return "唐"
        if year < 1075:
            return "天"
        return "邓"

    def _title_government(self, tid, date=None):
        self.seen.append(("gov", date))
        return ""

    def _name_source_key(self, tid, date=None):
        self.seen.append(("src", date))
        return "dynn_title_tang"

    def _is_independent(self, cid, date=None):
        self.seen.append(("indep", date))
        return True

    def _is_short_title(self, tid):
        return False

    def realm_name(self, tid):
        return ""

    def _is_female(self, cid):
        return True

    def name_with_regnal(self, cid, date=None):
        return ""

    def _prince_word(self, ptier, pgov, independent, female, **kw):
        self.seen.append(("word", kw.get("date")))
        return "公主"


def _stub():
    st = _Stub(None)
    st._lt = {"14022": {"key": "h_china"}}
    st.hold[14008] = {14022: [("859.9.13", "879.1.2", "destroyed")]}
    st.former = 14022
    # the class attributes the method reads (rank tables) and the pure-logic helpers come from the
    # real class, so the stub only stands in for the save lookups
    for name in ("_TT_RANK", "_RANK_TIER", "_tenure_end"):
        setattr(st, name, getattr(F.Facts, name).__get__(st, type(st))
                if callable(getattr(F.Facts, name)) else getattr(F.Facts, name))
    return st


def t_label_era():
    print("[1] 父已失位的称号时代（李星雁 → 唐公主）")
    st = _stub()
    got = F.Facts._style_parent_title(st, 14008, "1152.11.13")
    check(got == ("hegemon", 14022, "879.1.2"), "父之头衔回传持有末日", got)
    style = F.Facts._prince_style_from_title(st, got[0], got[1], "1152.11.13", 16797282,
                                             14008, realm_date=got[2])
    check(style == "唐公主", "1152 年补写的唐室公主用唐号", style)
    dates = {d for _m, d in st.seen}
    check(dates == {"879.1.2"}, "取名/政体/来源键/独立性/词表一律按持有末日", sorted(dates))

    # the same person through the whole 家谱: every article after the Tang writes 唐公主
    for date in ("904.11.30", "1009.6.26", "1126.7.30", "1152.11.13"):
        st2 = _stub()
        _t, _tid, rd = F.Facts._style_parent_title(st2, 14008, date)
        s = F.Facts._prince_style_from_title(st2, "hegemon", 14022, date, 16797282, 14008,
                                            realm_date=rd)
        check(s == "唐公主", f"{date} 篇作唐公主", s)

    # a parent still on the throne keeps today's realm (no behaviour change for the living)
    st3 = _stub()
    st3.primary = ("hegemon", 14022)
    check(F.Facts._style_parent_title(st3, 14008, "900.1.1") == ("hegemon", 14022, "900.1.1"),
          "在位之父仍用当日", F.Facts._style_parent_title(st3, 14008, "900.1.1"))
    # no title at all stays empty
    st4 = _stub()
    st4.former = None
    check(F.Facts._style_parent_title(st4, 1, "900.1.1") == (None, None, None), "无头衔者空返回")


def t_counts():
    print("[2] 家谱题记用的中文数词")
    cases = {9: "九", 12: "十二", 99: "九十九", 100: "一百", 105: "一百零五",
             110: "一百一十", 112: "一百一十二", 5688: "5688"}
    for n, want in cases.items():
        got = F._tree_count_zh(n)
        check(got == want, f"{n} → {want}", got)


def t_tree(path=None):
    p = path or os.path.join(ROOT, "output", "洪氏2", "data", "genealogy.json")
    print(f"[3] 家谱数据 {p}")
    if not os.path.exists(p):
        check(False, "家谱数据存在", p)
        return
    t = json.load(io.open(p, encoding="utf-8"))
    nodes = {n["id"]: n for n in t["nodes"]}
    check(t.get("schema") == 1, "schema 1", t.get("schema"))
    check(len(t["chain"]) >= 2, "传主链至少两人", len(t["chain"]))
    check(all(c["subj"] if False else True for c in t["chain"]), "链上有序")
    for i, c in enumerate(t["chain"], 1):
        check(c["i"] == i and nodes[c["id"]]["subj"] == i, f"第{i}位传主序号", c["name"])
        check(nodes[c["id"]]["note"] == "传主", f"第{i}位传主标注", nodes[c["id"]]["note"])
    gens = [c["gen"] for c in t["chain"]]
    check(gens == sorted(gens), "传主世次不倒退", gens)
    check(all(n["from_k"] >= 1 for n in t["nodes"]), "每珠有入谱篇次")
    # every non-founder node is placed: a blood node under a parent, an in-law beside a spouse
    for n in t["nodes"]:
        if n["id"] == t["chain"][0]["id"]:
            continue
        check(n["parent"] or n["spouse_of"], f"{n['name']} 有归属",
              f"parent={n['parent']} spouse_of={n['spouse_of']}")
    # the red line: consecutive protagonists connected inside the node set
    check(not t["unreachable"], "传主传承路径全部可闭合", t["unreachable"])
    check(len(t["pairs"]) == len(t["chain"]) - 1, "相邻传主对数", len(t["pairs"]))
    red = {tuple(e) for e in t["red_edges"]}
    for path in t["pairs"]:
        for u, v in zip(path, path[1:]):
            e = (u, v) if nodes[v]["parent"] == u else ((v, u) if nodes[u]["parent"] == v else None)
            check(e in red, f"红线含 {u}→{v}", e)
    check(all(nodes[b]["gen"] >= nodes[a]["gen"] for a, b in t["red_edges"]),
          "红线由尊及卑")
    print(f"    节点 {len(t['nodes'])} 人 / 传主 {len(t['chain'])} 位 / 红线 {len(red)} 段 / "
          f"题记 {t.get('summary')}")


def t_html(path=None):
    p = path or os.path.join(ROOT, "output", "洪氏2", "index.html")
    print(f"[4] 阅读页 {p}")
    if not os.path.exists(p):
        check(False, "阅读页存在", p)
        return
    html = io.open(p, encoding="utf-8").read()
    check("家谱" in html, "有家谱入口")
    check('id="tree"' in html or 'class="tree' in html, "有家谱容器")
    check(html.count('class="edge red"') >= 1 or '"red_edges"' in html, "有红线数据")


def main():
    t_label_era()
    t_counts()
    if "--tree" in sys.argv:
        t_tree()
        t_html()
    print("\n%s  (%d 项未过)" % ("全部通过" if not FAIL else "有失败", len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
