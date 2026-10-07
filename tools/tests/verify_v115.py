# -*- coding: utf-8 -*-
"""v115 断言：终传附录「世系」的版式 —— 世次只写一次、段落/列表分明、教宗写本名。

用法:
    & tools\\py.ps1 tools\\tests\\verify_v115.py            # 读快照（秒级，不载熔件）
    & tools\\py.ps1 tools\\tests\\verify_v115.py --md       # 另核 9 篇成稿的世系块
    & tools\\py.ps1 tools\\tests\\verify_v115.py --page     # 另核 md→html 与已重建的阅读页

事实面读 `output/洪氏2/data/snap_v115_207044_final.json`；旧版式证据在
`snap_v114_207044_final.json`（verify_v114.py 仍读那一份）。
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

FAIL = []
BASE = os.path.join(ROOT, "output", "洪氏2")
SNAP = os.path.join(BASE, "data", "snap_v115_207044_final.json")

GEN_RE = re.compile(r"^\*\*([一二三四五六七八九十]+)世\*\*$")
CHAIN_RE = re.compile(r"^　")
KIN_RE = re.compile(r"^- ")
BREAK_RE = re.compile(r"^〈")
ZHU = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
EXPECT_HEADS = {
    "一世": "**天皇帝穿刺者洪秀全**，849年生，867年起为传主，904年11月30日卒",
    "二世": "**天皇帝堕邪者圣洪天贵福**，洪秀全之子，869年8月6日生，904年11月30日继为传主，"
            "952年1月29日卒，970年封圣",
    "四世·尼各老": "**教宗欢乐者尼各老**，本名洪思忠，洪天贵福之外甥孙，917年4月11日生，"
                   "952年1月29日继为传主，999年7月7日卒",
    "五世": "**爱尔兰至高王残忍者耀国·缯松**，缯·洪堡之子，1003年5月29日生，1009年6月26日继为传主，"
            "1075年9月8日卒",
    "七世": "**鄯州节度使贪婪者洪七公**，洪易卜拉欣之子，1109年4月25日生，1126年7月30日继为传主，"
            "1152年11月13日卒",
}


def check(ok, label, detail=""):
    print(("  PASS " if ok else "  FAIL ") + label + (("  | " + str(detail)) if detail else ""))
    if not ok:
        FAIL.append(label)


def load_snap():
    with io.open(SNAP, encoding="utf-8") as fp:
        return json.load(fp)


def split_block(gen):
    """(chain rows, [(世次, head, [kin rows])]) in printed order."""
    markers = [ln for ln in gen if GEN_RE.match(ln)]
    heads = [ln for ln in gen if ln.startswith("**") and not GEN_RE.match(ln)]
    chain = [ln for ln in gen if CHAIN_RE.match(ln)]
    return markers, heads, chain


def t_layout(snap):
    print("[1] 版式：世次只写一次，段落/列表分明")
    gen = snap["facts"].get("genealogy") or []
    check(bool(gen) and gen[0].startswith("凡例："), "凡例是首行", gen[:1])
    check(not gen[0].startswith("- "), "凡例不再是列表项", gen[:1])
    check("世系图：" in gen, "有世系图标题行", [x for x in gen if "世系图" in x][:1])
    markers, heads, chain = split_block(gen)
    check(len(chain) == 2 and all(" ─ " in ln for ln in chain),
          "世系图两行、逐人以 ─ 相连", len(chain))
    check(any("四世 洪思忠（尼各老）" in ln for ln in chain),
          "链条写本名（教名在括号里）", chain[0][:60])
    # a 世次 line is printed once per generation, and its number never rides on a head line
    gens = [GEN_RE.match(x).group(1) for x in markers]
    check(len(gens) == len(set(gens)), "世次行每代只一处", gens)
    # the chain names the generation of every protagonist, so its numbers are the same set
    row = [g for ln in chain for g in re.findall(r"([一二三四五六七八九十]+)世 ", ln)]
    check(gens == sorted(set(row), key=lambda g: ZHU.index(g)), "世次行与链条的世代一致", (gens, row))
    check(sum(1 for ln in gen if ln == "**四世**") == 1, "「**四世**」全块只一处")
    check(sum(ln.count("四世") for ln in gen) == 4, "四世共 4 处（链条 3 ＋ 世次 1）",
          sum(ln.count("四世") for ln in gen))
    check(all("　" not in ln for ln in heads), "头行不再带世次前缀", [x for x in heads if "　" in x][:1])
    check(all(re.match(r"^\*\*[^*]+\*\*，", ln) for ln in heads),
          "头行＝粗体称谓＋生平", [x for x in heads if not re.match(r"^\*\*[^*]+\*\*，", x)][:1])
    kin = [ln for ln in gen if KIN_RE.match(ln)]
    check(kin and all("：" in ln for ln in kin), "亲属行是列表项且带冒号", len(kin))
    # blank-line discipline: a paragraph stands alone, a list run is closed by a blank line
    bad = []
    for i, ln in enumerate(gen):
        nxt = gen[i + 1] if i + 1 < len(gen) else ""
        if not ln.strip() or KIN_RE.match(ln):
            continue
        if KIN_RE.match(nxt):
            bad.append((i, ln[:24]))
    check(not bad, "每个段落/世次/头行后面都空一行", bad[:3])
    tail = [x for x in gen if x.strip() and not (CHAIN_RE.match(x) or KIN_RE.match(x)
                                                 or GEN_RE.match(x) or BREAK_RE.match(x)
                                                 or x.startswith("凡例：") or x.startswith("世系图：")
                                                 or x.startswith("**"))]
    check(not tail, "块内没有无法归类的行", tail[:2])


def t_heads(snap):
    print("[2] 九位传主：称谓＋本名＋生卒继任")
    gen = snap["facts"].get("genealogy") or []
    _markers, heads, _chain = split_block(gen)
    check(len(heads) == 9, "九位传主九个头行", len(heads))
    for key, want in EXPECT_HEADS.items():
        check(any(ln == want for ln in heads), f"{key} 头行逐字",
              [ln[:60] for ln in heads if ln.startswith(want.split("**")[1][:0] + "**"
                                                       + want.split("**")[1])][:1])
    check("，本名洪思忠，" in heads[2], "教宗头行写本名（②）", heads[2][:60])
    check(all(("生" in ln and "为传主" in ln and "卒" in ln) for ln in heads[:8]),
          "每位都写生年、继任与卒日")
    check("，970年封圣" in heads[1] and "，1051年封圣" in heads[4], "封圣年仍在头行末（③）")
    sub = snap["facts"].get("genealogy_subject") or []
    check(bool(sub) and GEN_RE.match(sub[0]) is not None, "本代块以世次行开头", sub[:1])
    check(bool(sub) and sub[1] == heads[-1], "本代块的传主行＝末代头行", sub[1:2])
    check(all(ln in gen for ln in sub), "本代块是世系块的子集")


def t_md():
    print("[3] 九篇成稿的世系块（--md）")
    snap = load_snap()
    gen = snap["facts"].get("genealogy") or []
    files = []
    for fn in sorted(os.listdir(BASE)):
        if not fn.endswith("_终传_%s.md" % "1152_11_13"):
            continue
        files.append(fn)
    all_files = [fn for fn in sorted(os.listdir(BASE)) if fn.endswith(".md")]
    checked = 0
    for fn in all_files:
        with io.open(os.path.join(BASE, fn), encoding="utf-8") as fp:
            lines = fp.read().splitlines()
        if "### 世系" not in lines:
            continue
        i = lines.index("### 世系") + 1
        j = i
        while j < len(lines) and not lines[j].startswith("#"):
            j += 1
        block = lines[i:j]
        base = [x for x in block if x.strip()]
        want = [x for x in gen if x.strip()]
        extra = [x for x in base[len(want):] if x.strip()]
        checked += 1
        check(base[:len(want)] == want, f"{fn}: 世系块＝快照输出", base[:1])
        check(all(x.startswith("家格：") for x in extra), f"{fn}: 额外行只是本篇「家格：」",
              extra[:1])
        if "洪七公" in fn:
            check(sum(1 for x in block if x == "**四世**") == 1, f"{fn}: 「**四世**」只一处")
            check(sum(x.count("四世") for x in block) == 4, f"{fn}: 四世 4 处（原 6 处）",
                  sum(x.count("四世") for x in block))
            # the hand-synced block must be exactly what the renderer emits today
            import biography as B
            app = B._appendix_text(snap["facts"]).split("\n")
            s = app.index("### 世系") + 1
            e = app.index("### 大事年表")
            check(app[s:e] == block, f"{fn}: 成稿块＝_appendix_text 现场输出", len(app[s:e]))
    check(checked == 9, "核了 9 篇终传", checked)


def t_page():
    print("[4] 渲染与阅读页（--page）")
    import htmlview
    snap = load_snap()
    gen = snap["facts"].get("genealogy") or []
    text = "### 世系\n" + "\n".join(gen)
    html, _toc = htmlview.md_to_html(text)
    check("<p>凡例：" in html, "凡例渲染成段落", html[:80])
    check("<p><strong>四世</strong></p>" in html, "世次渲染成独立粗体段")
    check("<p><strong>教宗欢乐者尼各老</strong>，本名洪思忠，" in html, "教宗段落带本名")
    check("<li>父：前礼部尚书书吏洪地保</li>" in html, "亲属行渲染成列表项")
    check(html.count("<strong>四世</strong>") == 1, "页面上「四世」世次只一处",
          html.count("<strong>四世</strong>"))
    page = os.path.join(BASE, "index.html")
    if not os.path.isfile(page):
        check(False, "阅读页存在", page)
        return
    with io.open(page, encoding="utf-8") as fp:
        got = fp.read()
    # the page inlines its payload as JSON, so every closing tag reads `<\/…`
    check("本名洪思忠" in got, "阅读页含教宗本名")
    # nine terminal pieces each carry the block once, so one 「四世」 heading apiece
    check(got.count("<p><strong>四世<") == 9, "阅读页九篇各一处世次段落",
          got.count("<p><strong>四世<"))
    check("<li>父：前礼部尚书书吏洪地保" in got, "阅读页亲属行仍是列表项")
    check("<p><strong>教宗欢乐者尼各老<" in got, "阅读页传主行是粗体称谓段落")


def main():
    snap = load_snap()
    t_layout(snap)
    t_heads(snap)
    if "--md" in sys.argv:
        t_md()
    if "--page" in sys.argv:
        t_page()
    print()
    if FAIL:
        print(f"未过 {len(FAIL)} 项: " + "; ".join(FAIL))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
