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

_BADGE = re.compile(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯] ")

TREE_PATH = os.path.join(ROOT, "output", "洪氏2", "data", "genealogy.json")


def load_tree():
    """The sidecar family tree written by biography.generate_biography."""
    if not os.path.exists(TREE_PATH):
        return None
    return json.load(io.open(TREE_PATH, encoding="utf-8"))


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
        self.gov = ""                # _title_government result
        self.female = True           # _is_female result
        self.word = "公主"           # _prince_word result

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
        return self.gov

    def _name_source_key(self, tid, date=None):
        self.seen.append(("src", date))
        return "dynn_title_tang"

    def _is_independent(self, cid, date=None):
        self.seen.append(("indep", date))
        return True

    # v116 起 `_prince_style_from_title` 走这两个助手取政体/独立性；本档断言记的是 v113 的
    # 冻结口径，所以这里按 v116 之前的读法实现（政体取自头衔、独立性 None 记作独立）
    def _parent_child_government(self, owner, ptid, date, title_gov=None):
        return self._title_government(ptid, date) if title_gov is None else title_gov

    def _parent_child_independent(self, owner, date):
        v = self._is_independent(owner, date)
        return True if v is None else v

    def _is_short_title(self, tid):
        return False

    def realm_name(self, tid):
        return ""

    def _is_female(self, cid):
        return self.female

    def name_with_regnal(self, cid, date=None):
        return ""

    def _prince_word(self, ptier, pgov, independent, female, **kw):
        self.seen.append(("word", kw.get("date")))
        return self.word


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
    print("[1] 父已失位的称号时代（李星雁 → 唐公主，洪天姣 → 天公主）")
    st = _stub()
    got = F.Facts._style_parent_title(st, 14008, "1152.11.13")
    check(got == ("hegemon", 14022, "879.1.2"), "父之头衔回传持有末日", got)
    style = F.Facts._prince_style_from_title(st, got[0], got[1], "1152.11.13", 16797282,
                                             14008, realm_date=got[2])
    check(style == "唐公主", "1152 年补写的唐室公主用唐号", style)
    # only the era name (name + `dynn_` source key) reads the tenure; the word still reads the
    # article date, so a ruling parent's rendering is untouched
    dates = {}
    for kind, d in st.seen:
        dates.setdefault(kind, set()).add(d)
    check(dates.get("name") == {"879.1.2"}, "朝名按持有末日", {k: sorted(v) for k, v in dates.items()})
    check(dates.get("gov") == {"1152.11.13"} and dates.get("word") == {"1152.11.13"}
          and dates.get("indep") == {"1152.11.13"},
          "政体/独立性/称谓词仍按成稿当日", {k: sorted(v) for k, v in dates.items()})
    # the '大' form follows the dynasty of that same era: its source key is read at the tenure end
    st6 = _stub()
    st6.gov = "celestial_government"
    _t, _tid, rd6 = F.Facts._style_parent_title(st6, 14008, "1152.11.13")
    s6 = F.Facts._prince_style_from_title(st6, "hegemon", 14022, "1152.11.13", 16797282, 14008,
                                          realm_date=rd6)
    src = {d for k, d in st6.seen if k == "src"}
    check(s6 == "大唐公主" and src == {"879.1.2"}, "『大』式按持有末日的朝名来源键", (s6, sorted(src)))

    # a son reads the same era with the male word (洪秀全's sons carry 天王子 in the facts)
    for cid, date, want in ((38957, "1126.7.30", "天王子"), (14008, "1152.11.13", "唐王子")):
        stm = _stub()
        stm.female, stm.word = False, "王子"
        if cid == 38957:
            stm.hold[cid] = {14022: [("897.6.5", "904.11.30", "destroyed")]}
        _t, _tid, rdm = F.Facts._style_parent_title(stm, cid, date)
        sm = F.Facts._prince_style_from_title(stm, "hegemon", 14022, date, 44503, cid,
                                              realm_date=rdm)
        check(sm == want, f"{cid} 之子作{want}", sm)

    # the same person through the whole 家谱: every article after the Tang writes 唐公主
    for date in ("904.11.30", "1009.6.26", "1126.7.30", "1152.11.13"):
        st2 = _stub()
        _t, _tid, rd = F.Facts._style_parent_title(st2, 14008, date)
        s = F.Facts._prince_style_from_title(st2, "hegemon", 14022, date, 16797282, 14008,
                                            realm_date=rd)
        check(s == "唐公主", f"{date} 篇作唐公主", s)

    # 洪天姣: her father 洪秀全 held h_china until 904.11.30, when it was already renamed 天
    st5 = _stub()
    st5.hold[38957] = {14022: [("897.6.5", "904.11.30", "destroyed")]}
    _t, _tid, rd5 = F.Facts._style_parent_title(st5, 38957, "1126.7.30")
    check(rd5 == "904.11.30", "洪秀全之头衔回传持有末日", rd5)
    s5 = F.Facts._prince_style_from_title(st5, "hegemon", 14022, "1126.7.30", 44503, 38957,
                                          realm_date=rd5)
    check(s5 == "天公主", "洪天姣作天公主（当日已称天）", s5)

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
    p = path or TREE_PATH
    print(f"[3] 家谱数据 {p}")
    t = load_tree()
    if not t:
        check(False, "家谱数据存在", p)
        return
    nodes = {n["id"]: n for n in t["nodes"]}
    check(t.get("schema") == 1, "schema 1", t.get("schema"))
    check(len(t["chain"]) >= 2, "传主链至少两人", len(t["chain"]))
    for i, c in enumerate(t["chain"], 1):
        check(c["i"] == i and nodes[c["id"]]["subj"] == i, f"第{i}位传主序号", c["name"])
        check(nodes[c["id"]]["note"] == "传主", f"第{i}位传主标注", nodes[c["id"]]["note"])
    gens = [c["gen"] for c in t["chain"]]

    def _is_anc(a, b):
        """Is `a` an ancestor of `b` along the tree's own parent links?"""
        seen = set()
        while b is not None and b not in seen:
            seen.add(b)
            if b == a:
                return True
            b = nodes.get(b, {}).get("parent")
        return False

    # The played line's own 世次 is the game's reckoning and never moves (v113 user 2026-10-07), so it
    # may step back where a junior kinsman took the family over: 洪氏2 has 泰阳·邕州洪 at 八世 right
    # after 洪智深 at 九世, and the printed 世系 heads carry that step as it stands (v119).
    back = [(t["chain"][i - 1], gens[i - 1], t["chain"][i], gens[i])
            for i in range(1, len(gens)) if gens[i] < gens[i - 1]]
    check(not [b for b in back if _is_anc(b[0]["id"], b[2]["id"])],
          "传主世次不倒退（回退者皆为旁支承继）",
          [(b[0]["name"], b[1], b[2]["name"], b[3]) for b in back])
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
    red = {(e[0], e[1]) for e in t["red_edges"]}
    for path in t["pairs"]:
        for u, v in zip(path, path[1:]):
            e = (u, v) if nodes[v]["parent"] == u else ((v, u) if nodes[u]["parent"] == v else None)
            check(e in red, f"红线含 {u}→{v}", e)
    check(all(nodes[b]["gen"] >= nodes[a]["gen"] for a, b, _i in t["red_edges"]),
          "红线由尊及卑")
    check(all(0 <= i <= len(t["chain"]) - 2 for _a, _b, i in t["red_edges"]),
          "红线带相邻传主序号")
    print(f"    节点 {len(t['nodes'])} 人 / 传主 {len(t['chain'])} 位 / 红线 {len(red)} 段 / "
          f"题记 {t.get('summary')}")


_HARNESS = r"""
import fs from 'fs';
const html = fs.readFileSync(process.argv[2], 'utf8');
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if(!m){ console.log(JSON.stringify({error: 'no script'})); process.exit(0); }
const js = m[1];
function El(){ this.innerHTML = ''; this.style = {}; this.dataset = {}; this.disabled = false;
  this.title = ''; this._s = '';
  this.classList = {add(){}, remove(){}, contains(){ return false; }};
}
El.prototype.querySelectorAll = function(){ return []; };
El.prototype.appendChild = function(){};
El.prototype.setAttribute = function(){};
El.prototype.getAttribute = function(){ return null; };
const byId = {};
['stage','meta-line','toc','tabs','char-sel','tree-btn'].forEach(id => { byId[id] = new El(); });
global.document = { getElementById: id => byId[id] || new El(),
                   createElement: () => new El(), querySelectorAll: () => [],
                   body: new El(), documentElement: new El() };
eval(js + '\nglobalThis.__tree = {renderTree: renderTree, scopeOf: scopeOf, beadOrder: beadOrder, '
        + 'treeKeep: treeKeep, houseState: houseState, TREE: TREE};');
const api = globalThis.__tree;
function hostFor(k){
  const h = new El();
  Object.defineProperty(h, 'innerHTML', { get(){ return h._s; }, set(v){ h._s = v; } });
  h.getAttribute = () => String(k);
  return h;
}
function metrics(k){
  const h = hostFor(k);
  api.renderTree(h, k);
  const s = h._s || '';
  const beads = s.split('<g class="').slice(1).map(c => {
    const cls = c.slice(0, c.indexOf('"'));
    const id = /data-id="(\d+)"/.exec(c);
    const r = /<rect x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)"/.exec(c);
    const tog = />([▶▼])<\/text>/.exec(c);
    return {cls: cls, id: id ? +id[1] : null, x: r ? +r[1] : null, y: r ? +r[2] : null,
            w: r ? +r[3] : null, h: r ? +r[4] : null, tog: tog ? tog[1] : '',
            texts: [...c.matchAll(/>([^<>]*)<\/text>/g)].map(x => x[1])};
  });
  const paths = [...s.matchAll(/<path class="([^"]*)" d="([^"]*)"/g)]
    .map(x => ({cls: x[1], d: x[2]}));
  const sv = /viewBox="0 0 ([\d.]+) ([\d.]+)"/.exec(s);
  /* the 分家 menu's own decision, straight from the page: `treeKeep` is what htmlview renders with,
     so the test can compare its own rule against the page's instead of re-implementing the geometry */
  const hk = hostFor(k), kp = api.treeKeep(api.scopeOf(k), api.houseState(hk)).keep;
  return {k: k, bead_count: beads.length, beads: beads, paths: paths,
          kept: Object.keys(kp).filter(x => kp[x]).map(Number),
          view: sv ? [+sv[1], +sv[2]] : null,
          hosts: (s.match(/class="tree-host"/g) || []).length};
}
const K = (api.TREE && api.TREE.chain ? api.TREE.chain.length : 0);
const out = {K: K, cases: []};
[K, 2, 1].forEach(k => { if(k >= 1) out.cases.push(metrics(k)); });
/* click behaviour without a DOM: `beadOrder` is the whole of it — closing a bead must drop its
   branch, opening it must bring the branch back, and the open-all sweep must reach every node */
function clickProbe(k){
  const sc = api.scopeOf(k);
  const shut = {}, open = {};
  sc.nodes.forEach(n => { shut[n.id] = 1; open[n.id] = 0; });
  const subj = sc.nodes.filter(n => sc.isSubj(n) && (sc.kids[n.id] || []).length)[0];
  let tog = null;
  if(subj){
    const c = {};
    sc.nodes.forEach(n => { c[n.id] = 0; });
    c[subj.id] = 1;
    const closedOrder = api.beadOrder(sc, c);
    c[subj.id] = 0;
    const opened = api.beadOrder(sc, c).length;
    tog = {id: subj.id, name: subj.name, kids: (sc.kids[subj.id] || []).length,
           closed: closedOrder.length, opened: opened,
           keeps_self: closedOrder.indexOf(subj.id) >= 0,
           kids_left: (sc.kids[subj.id] || []).filter(x => closedOrder.indexOf(x) >= 0).length};
  }
  return {k: k, nodes: sc.nodes.length, all_open: api.beadOrder(sc, open).length,
          all_shut: api.beadOrder(sc, shut).length, toggle: tog};
}
out.clicks = [clickProbe(K)];
console.log(JSON.stringify(out));
"""


def write_harness():
    """Write the headless-DOM harness beside the page so other probes can reuse it."""
    harness = os.path.join(ROOT, "logs", "v113_tree_harness.mjs")
    os.makedirs(os.path.dirname(harness), exist_ok=True)
    with io.open(harness, "w", encoding="utf-8", newline="\n") as f:
        f.write(_HARNESS)
    return harness


def t_layout_js(html_path=None):
    """Run the page's own tree script headlessly and assert the geometry it produces.

    The layout lives in JavaScript, so this is the only check that sees the real thing: beads per
    generation row (始祖 on top, 宝塔式), no overlap inside a row, every edge leaving the father's
    bottom and landing on the child's top, the red line covering the succession pairs, and the
    default collapse state."""
    import subprocess
    p = html_path or os.path.join(ROOT, "output", "洪氏2", "index.html")
    print(f"[5] 宝塔式几何（node 无头核对）{p}")
    if not os.path.exists(p):
        check(False, "阅读页存在", p)
        return
    # the page source is read before the harness runs: its (very large) output leaves this process in a
    # state where a later open() of the same multi-megabyte page reports WinError 6 (v119)
    with io.open(p, encoding="utf-8") as fh:
        html = fh.read()
    tree = load_tree()
    if not tree:
        check(False, "家谱数据存在", TREE_PATH)
        return
    harness = write_harness()
    try:
        raw = subprocess.run(["node", harness, p], capture_output=True, text=True,
                             encoding="utf-8", cwd=ROOT, timeout=180).stdout
    except Exception as e:
        check(False, "node 运行", e)
        return
    try:
        got = json.loads(raw.strip().splitlines()[-1])
    except Exception:
        check(False, "node 输出可解析", raw[:400])
        return
    if got.get("error"):
        check(False, "页面脚本可用", got["error"])
        return

    nodes = {n["id"]: n for n in tree["nodes"]}
    for case in got["cases"]:
        k = case["k"]
        beads = {b["id"]: b for b in case["beads"]}
        red_nodes = set()
        for a, b, i in tree["red_edges"]:
            if i <= k - 2:
                red_nodes.add(a)
                red_nodes.add(b)
        # The page's default view (v119): the houses ticked in the 分家 menu — the protagonist's own
        # houses unless the reader changed them — plus the ancestors that hang those houses off the
        # trunk, with the 配 beads off. htmlview's `keep`/`hidden` pair is the same rule, so the two
        # must agree (nothing is folded on a first visit: the page opens every ticked house's beads).
        chain_houses = {str(h) for h in (tree.get("chain_houses") or [])}

        def ticked(n):
            return (0 < n["subj"] <= k or n["id"] in red_nodes or n.get("house") is None
                    or str(n.get("house")) in chain_houses)

        keep = {n["id"] for n in tree["nodes"] if n.get("spouse_of") is None and ticked(n)}
        # close upwards: an ancestor of a kept bead is kept so a lone cadet house stays connected
        for n in tree["nodes"]:
            if n["id"] not in keep:
                continue
            p, guard = n.get("parent"), 0
            while p is not None and p in nodes and p not in keep and guard < 64:
                keep.add(p)
                p = nodes[p].get("parent")
                guard += 1
        # 配 beads are off until 「含配偶」 is ticked, so none of them is drawn on a first visit — the
        # switch outranks the ancestor closure above, exactly as it does on the page
        keep = {i for i in keep if nodes[i].get("spouse_of") is None}
        spouse_keep = set()
        collapsed = set()
        kids = {}
        for n in tree["nodes"]:
            if n["parent"] is not None and nodes.get(n["parent"]) and not n["spouse_of"]:
                kids.setdefault(n["parent"], []).append(n["id"])
        in_scope = {n["id"] for n in tree["nodes"] if (n["from_k"] or 1) <= k}
        visible = (keep | spouse_keep) & in_scope
        # the rule above and the page's own `treeKeep` must agree, and the chart must draw exactly the
        # beads that rule keeps: a hidden house is absent, a lone cadet house still hangs off the trunk
        check(set(case.get("kept") or []) == visible, f"[k={k}] 分家勾选与页面一致",
              f"{len(case.get('kept') or [])} vs {len(visible)}")
        check(set(beads) == visible, f"[k={k}] 默认可见者吻合", f"{len(beads)} vs {len(visible)}")
        # rows: one row per generation, 始祖 on top and each generation below its father's
        ys = {}
        for b in case["beads"]:
            g = nodes[b["id"]]["gen"]
            ys.setdefault(g, set()).add(b["y"])
        check(all(len(v) == 1 for v in ys.values()), f"[k={k}] 同世同行", ys)
        gl = sorted(ys)
        rowy = {g: sorted(v)[0] for g, v in ys.items()}
        check(all(rowy[gl[i]] < rowy[gl[i + 1]] for i in range(len(gl) - 1)),
              f"[k={k}] 由上而下（始祖在上）", [(g, rowy[g]) for g in gl])
        # every row is stable and no two beads in it touch
        for g in gl:
            xs = sorted(b["x"] for b in case["beads"] if nodes[b["id"]]["gen"] == g)
            gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
            check(all(x >= 134 + 18 - 1 for x in gaps), f"[k={k}] {g}世 行内不重叠", gaps[:6])
        # a father always stands on a higher row than his drawn son
        bad_row = [(nodes[b["id"]]["name"], nodes[p]["gen"], nodes[b["id"]]["gen"])
                   for b in case["beads"] for p in [nodes[b["id"]]["parent"]]
                   if p in beads and nodes[p]["gen"] >= nodes[b["id"]]["gen"]]
        check(not bad_row, f"[k={k}] 父子不同行", bad_row[:4])
        # edges: out of the father's bottom, across the gap, onto the child's top
        edges = []
        for pa in case["paths"]:
            if pa["cls"] not in ("edge", "edge red"):
                continue
            mm = re.fullmatch(r"M([-\d.]+),([-\d.]+) V([-\d.]+) H([-\d.]+) V([-\d.]+)", pa["d"])
            if mm:
                edges.append((float(mm.group(1)), float(mm.group(2)), float(mm.group(3)),
                              float(mm.group(4)), float(mm.group(5)), pa["cls"]))
        check(len(edges) == sum(1 for b in case["beads"] if nodes[b["id"]]["parent"] in beads),
              f"[k={k}] 父子折线数", len(edges))
        parents = {(a, b) for a, b, i in tree["red_edges"] if i <= k - 2}
        red, bad_end, bad_start, bad_bus, bad_colour = 0, [], [], [], []
        shared_row = 0
        for x0, y0, by, x1, y1, cls in edges:
            child = next((b for b in case["beads"]
                          if b["x"] + b["w"] / 2 == x1 and b["y"] == y1), None)
            under = False
            if child is None:   # the under-row form: the child's bottom edge instead of its top
                child = next((b for b in case["beads"]
                              if b["x"] + b["w"] / 2 == x1 and b["y"] + b["h"] == y1), None)
                under = child is not None
                shared_row += 1 if under else 0
            if child is None:
                bad_end.append((x1, y1))
                continue
            pa = nodes[child["id"]]["parent"]
            top = beads.get(pa)
            if top is None or top["x"] + top["w"] / 2 != x0 or top["y"] + top["h"] != y0:
                bad_start.append((x0, y0, pa))
            elif not y0 < by < (y1 + (34 if under else 0)):
                bad_bus.append((y0, by, y1))
            if (cls == "edge red") != ((pa, child["id"]) in parents):
                bad_colour.append((pa, child["id"], cls))
            red += 1 if cls == "edge red" else 0
        check(not bad_end, f"[k={k}] 折线终点落在子女珠上缘", bad_end[:4])
        check(not bad_start, f"[k={k}] 折线起点落在父珠下缘", bad_start[:4])
        check(not bad_bus, f"[k={k}] 折线在父子行之间转折", bad_bus[:4])
        check(shared_row == 0, f"[k={k}] 无父子同行之折线", shared_row)
        check(not bad_colour, f"[k={k}] 红黑归属（红线只走传主传承）", bad_colour[:4])
        check(red == sum(1 for a, b in parents if a in beads and b in beads),
              f"[k={k}] 红线段数与传主传承吻合", red)
        # every bead fits in the canvas
        vw, vh = case["view"]
        check(all(0 <= b["x"] and b["x"] + b["w"] <= vw and 0 <= b["y"] and b["y"] + b["h"] <= vh
                  for b in case["beads"]), f"[k={k}] 珠粒都在画布内", (vw, vh))
        # a collapsible bead shows its marker, and every protagonist wears his number
        no_tog = [b["id"] for b in case["beads"]
                  if (b["tog"] != '') != any(nodes[c]["from_k"] <= k
                                             for c in kids.get(b["id"], []))]
        no_badge = [b["id"] for b in case["beads"]
                    if 0 < nodes[b["id"]]["subj"] <= k and not _BADGE.match(b["texts"][0] or "")]
        check(not no_tog, f"[k={k}] 可折叠者带角标", no_tog[:6])
        check(not no_badge, f"[k={k}] 传主戴徽记", no_badge[:6])
        print(f"    k={k}: 珠粒 {len(beads)} / 折线 {len(edges)} / 红线 {red} / 画布 {vw}×{vh}")

    # click behaviour: collapse hides a branch, expand restores it, 全开 reaches every node
    for c in got.get("clicks") or []:
        k = c["k"]
        n_all = len([n for n in tree["nodes"] if (n["from_k"] or 1) <= k])
        check(c["all_open"] == n_all, f"[k={k}] 全开后每珠都在", f"{c['all_open']} vs {n_all}")
        check(0 < c["all_shut"] < n_all, f"[k={k}] 全收后只剩始祖一层", c["all_shut"])
        t = c["toggle"]
        if t:
            check(t["keeps_self"], f"[k={k}] 折叠的是子女不是本人", t)
            check(t["kids_left"] == 0, f"[k={k}] 收起的传主不吐子女", t)
            check(t["opened"] - t["closed"] >= t["kids"],
                  f"[k={k}] 展开传主见到其整枝", f"{t['opened']}→{t['closed']}, 子女 {t['kids']}")
            check(t["opened"] == c["all_open"], f"[k={k}] 传主默认展开", t["opened"])

    # a long foreign name is squeezed into the bead instead of spilling over it
    check("function fitText" in html, "内联长名缩排")
    long_names = [n for n in tree["nodes"] if len(n["name"]) >= 8]
    if long_names:
        widest = max(long_names, key=lambda n: len(n["name"]))
        check(True, f"最长珠名 {widest['name']}（{len(widest['name'])} 字）",
              len(widest["name"]))


def t_html(path=None):
    p = path or os.path.join(ROOT, "output", "洪氏2", "index.html")
    print(f"[4] 阅读页 {p}")
    if not os.path.exists(p):
        check(False, "阅读页存在", p)
        return
    html = io.open(p, encoding="utf-8").read()
    check('id="tree-btn"' in html, "工具栏有家谱入口")
    check("function renderTree" in html, "内联宝塔式渲染器")
    check("red_edges" in html, "红线数据随页下发")
    # the whole page dies if the payload closes the inline <script> early
    mm = re.search(r"const DATA = (\{.*?\});\nconst CHARS", html, re.S)
    if not mm:
        check(False, "页面数据段完整", "找不到 const DATA")
    else:
        check("</" not in mm.group(1) and "<!--" not in mm.group(1),
              "内联数据段不含早闭标签", "")
        try:
            payload = json.loads(mm.group(1))
            check(isinstance(payload.get("chars"), list) and len(payload["chars"]) >= 1,
                  "页面数据段可解析", f"{len(payload.get('chars') or [])} 位角色")
        except Exception as e:
            check(False, "页面数据段可解析", e)
    tree = load_tree()
    if tree:
        # the figure lives behind the toolbar button only (user 2026-10-07): the article appendices
        # keep the printed 世系 they always had, and no per-article host is injected
        check(len(re.findall(r'class="tree-host"', html)) == 1,
              "家谱只在阅读页的「家谱」按钮处", len(re.findall(r'class="tree-host"', html)))
        check("宝塔式" in html, "页面自称宝塔式")
        base = os.path.join(ROOT, "output", "洪氏2")
        mds = [f for f in sorted(os.listdir(base)) if f.endswith(".md") and "终传" in f]
        no_tree = [f for f in mds
                   if "### 世系" not in io.open(os.path.join(base, f), encoding="utf-8").read()]
        check(mds and not no_tree, "终传附录的「### 世系」已复原", no_tree[:3])


def main():
    t_label_era()
    t_counts()
    if "--tree" in sys.argv:
        t_tree()
        t_html()
        t_layout_js()
    print("\n%s  (%d 项未过)" % ("全部通过" if not FAIL else "有失败", len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
