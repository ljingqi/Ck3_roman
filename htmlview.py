# -*- coding: utf-8 -*-
"""Build each family's self-contained output/<family>/index.html reading page from its
biography Markdown (styles and scripts inlined, pieces switchable in-page, works offline).
Usage: python htmlview.py rebuild [family ...] — all families when none is given."""
import html
import json
import os
import re
import sys
import threading

import cache_lib as cl   # same date-key convention as cache_lib.date_key; do not add a second parser

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

FILE_RE = re.compile(r"^(.+_(?:终传|传记)(?:_第\d+个十年)?_\d+_\d{2}_\d{2}|demo_.+)\.md$")


def _output_dir():
    try:
        with open(os.path.join(SCRIPT_DIR, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        d = (cfg.get("output_dir") or "").strip()
        if d:
            return os.path.normpath(d)
    except Exception:
        pass
    return os.path.join(SCRIPT_DIR, "output")


# ------------------- Markdown -> HTML (the syntax subset in use) -------------

def _inline(text):
    """Inline syntax: HTML-escape first, then bold / italic / inline code."""
    t = html.escape(text)
    t = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    return t


def _is_table_row(ln):
    s = ln.strip()
    return s.startswith("|") and s.endswith("|")


def _render_table(rows):
    parsed = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    if len(parsed) < 2:
        return ""
    sep = parsed[1]
    if all(re.fullmatch(r"\s*:?-{1,}:?\s*", c) for c in sep):
        header, body = parsed[0], parsed[2:]
    else:
        header, body = parsed[0], parsed[1:]
    ncol = max(len(header), max((len(r) for r in body), default=0))

    def row_html(cells, tag):
        cells = list(cells) + [""] * (ncol - len(cells))
        return "<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>"

    out = ["<table>"]
    out.append("<thead>" + row_html(header, "th") + "</thead>")
    out.append("<tbody>" + "".join(row_html(r, "td") for r in body) + "</tbody>")
    out.append("</table>")
    return "\n".join(out)


def _is_ul(ln):
    return bool(re.match(r"^\s*[-*]\s+", ln))


def _is_ol(ln):
    return bool(re.match(r"^\s*\d+[.)]\s+", ln))


def _render_nested_list(rows):
    """Turn consecutive list lines (leading spaces express nesting) into nested <ul>s."""
    items = []
    for r in rows:
        m = re.match(r"^(\s*)([-*]|\d+[.)])\s+(.*)$", r)
        if not m:
            continue
        items.append((len(m.group(1)), m.group(3).strip()))
    if not items:
        return ""
    out = []
    stack = []  # [(indent, tag)]
    first = True
    for indent, text in items:
        if first:
            out.append("<ul>")
            stack.append((indent, "ul"))
            out.append(f"<li>{_inline(text)}")
            first = False
            continue
        top = stack[-1][0]
        if indent > top:
            out.append("<ul>")
            stack.append((indent, "ul"))
            out.append(f"<li>{_inline(text)}")
        elif indent == top:
            out.append("</li>")
            out.append(f"<li>{_inline(text)}")
        else:
            while stack and indent < stack[-1][0]:
                out.append("</li>")
                out.append(f"</{stack.pop()[1]}>")
            if stack and indent == stack[-1][0]:
                out.append("</li>")
                out.append(f"<li>{_inline(text)}")
            else:
                out.append("<ul>")
                stack.append((indent, "ul"))
                out.append(f"<li>{_inline(text)}")
    while stack:
        out.append("</li>")
        out.append(f"</{stack.pop()[1]}>")
    return "".join(out)


def md_to_html(text):
    """Render a whole Markdown document to (html, sections); sections are
    [{level, text, id}] and drive the sidebar jumps."""
    lines = text.split("\n")
    out = []
    toc = []
    toc_seen = set()
    i, n = 0, len(lines)
    hd_count = 0
    while i < n:
        ln = lines[i]
        s = ln.strip()
        if not s or s.startswith("<!--"):
            i += 1
            continue
        if re.fullmatch(r"-{3,}", s):
            out.append("<hr>")
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            level = len(m.group(1))
            htext = m.group(2).strip()
            cls = ' class="masthead"' if level == 1 else ""
            # heading anchor id, used by the section sidebar for jumps
            hd_count += 1
            hd_id = f"hd-{hd_count}"
            out.append(f'<h{level} id="{hd_id}"{cls}>{_inline(htext)}</h{level}>')
            # Only h1-h3 enter the section sidebar; h1 is the biography title, one per piece
            if level <= 3:
                # Deduplicate headings by a normalized key, keeping the first: numeric
                # prefixes, book-title marks and known section prefixes are stripped first.
                key = re.sub(r"^[0-9、]+", "", htext)
                key = re.sub(r"[《》]", "", key)
                key = re.sub(r"^(?:开篇|纪事|评曰|列传|本纪|家室|朝局|家族|刺客|游侠|妻族|群英|恩怨|宝物)[··]", "", key)
                if key not in toc_seen:
                    toc_seen.add(key)
                    toc.append({"level": level, "text": htext, "id": hd_id})
            i += 1
            continue
        if _is_table_row(ln):
            rows = []
            while i < n and _is_table_row(lines[i]):
                rows.append(lines[i])
                i += 1
            out.append(_render_table(rows))
            continue
        if _is_ul(ln) or _is_ol(ln):
            rows = []
            while i < n and (_is_ul(lines[i]) or _is_ol(lines[i])):
                rows.append(lines[i])
                i += 1
            out.append(_render_nested_list(rows))
            continue
        if s.startswith(">"):
            quotes = []
            while i < n and lines[i].strip().startswith(">"):
                quotes.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            body = _inline(" ".join(q.strip() for q in quotes))
            out.append(f"<blockquote>{body}</blockquote>")
            continue
        para = []
        while i < n:
            s2 = lines[i].strip()
            if (not s2 or s2.startswith("<!--")
                    or s2.startswith("#") or re.fullmatch(r"-{3,}", s2)
                    or _is_table_row(s2) or _is_ul(s2) or _is_ol(s2)
                    or s2.startswith(">")):
                break
            para.append(s2)
            i += 1
        if not para:
            i += 1
            continue
        out.append(f"<p>{_inline(' '.join(para))}</p>")
    return "\n".join(out), toc


# --------------------------- Family reading page -----------------------------

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --paper:#fbf6e9; --paper-edge:#d9cba8; --ink:#2a2118; --ink-soft:#5a4b32;
  --rule:#b7a67e; --accent:#8a3b22; --bar:#262016; --bar-ink:#f0e6d2; --gold:#c8a24a;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{min-height:100%}
body{font-family:"Songti SC","Noto Serif CJK SC","Source Han Serif SC","SimSun",serif;background:#e9e0cb;color:var(--ink)}
#toolbar{position:sticky;top:0;z-index:20;display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:10px 14px;padding:10px 18px;background:var(--bar);color:var(--bar-ink);box-shadow:0 2px 10px rgba(30,22,8,.35)}
#toolbar .left{display:flex;flex-direction:column;gap:8px;min-width:0}
#toolbar .session{font-weight:700;letter-spacing:2px;font-size:17px}
#tabs{display:flex;flex-wrap:wrap;gap:6px}
#tabs button{font:inherit;padding:5px 14px;border:1px solid #8f7d55;background:#3a3121;color:var(--bar-ink);border-radius:5px;cursor:pointer;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#tabs button.active{background:var(--gold);border-color:var(--gold);color:#211a0c;font-weight:700}
#char-box{display:flex;align-items:center;gap:8px;padding:4px 0}
#char-box label{font-size:14px;color:#cbbf9f}
#char-sel{font:inherit;font-size:14px;padding:5px 8px;border:1px solid #8f7d55;border-radius:5px;background:#3a3121;color:var(--bar-ink);cursor:pointer;max-width:200px}
/* v14: 左侧章节栏 — markdown 标题 (1-3 级) 直接跳转章节 */
#wrap{display:flex;align-items:flex-start;gap:0;max-width:1280px;margin:0 auto}
#toc{position:sticky;top:64px;flex:0 0 220px;max-height:calc(100vh - 88px);overflow-y:auto;margin:28px 0 8px;padding:14px 12px;background:var(--bar);color:var(--bar-ink);border-radius:2px;box-shadow:0 6px 22px rgba(60,45,20,.18);font-size:13px}
#toc .toc-root{font-weight:700;letter-spacing:1px;font-size:14px;color:var(--gold);margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #4a3f2b}
#toc a{display:block;color:#cbbf9f;text-decoration:none;line-height:1.7;padding:3px 6px;border-radius:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#toc a:hover{background:#3a3121;color:#fff}
#toc a.lv2{padding-left:16px;font-weight:700;color:#e6d9b8}
#toc a.lv3{padding-left:30px;font-size:12px;color:#a8987a}
#toc a.hl{background:var(--gold);color:#211a0c}
#toc .empty{color:#6f6247;padding:6px;text-align:center}
#main{flex:1 1 auto;min-width:0}
#stage{max-width:880px;margin:28px auto 8px;padding:0 14px}
@media (max-width:860px){#wrap{display:block}#toc{position:static;flex:none;max-height:180px;margin:14px 12px 0}}
.paper{background:var(--paper);border:1px solid var(--paper-edge);box-shadow:0 6px 22px rgba(60,45,20,.18);padding:38px 46px 46px;border-radius:2px}
#meta-line{max-width:880px;margin:10px auto 60px;padding:0 14px;text-align:center;color:#6f6247;font-size:13px}
.empty{color:#8a7a55;text-align:center;padding:60px 0}
p{line-height:2.05;text-align:justify;margin:0 0 14px;font-size:17px}
h1.masthead{font-size:30px;text-align:center;letter-spacing:6px;margin:6px 0 18px;color:var(--accent)}
h2{font-size:22px;margin:26px 0 12px;color:var(--accent);border-bottom:1px solid var(--rule);padding-bottom:6px}
h3{font-size:18px;margin:20px 0 10px;color:var(--ink)}
strong{font-weight:700}
em{font-style:italic}
hr{border:none;border-top:1px solid var(--rule);margin:24px 0}
table{border-collapse:collapse;margin:16px auto 18px;font-size:15px;max-width:100%}
th,td{border:1px solid #b9a883;padding:7px 12px;text-align:center}
th{background:#efe6cd;font-weight:700}
ul,ol{margin:0 0 14px;padding-left:2em;line-height:2}
li{margin-bottom:4px}
blockquote{margin:0 0 14px;padding:10px 18px;border-left:4px solid var(--gold);background:#f3ecd8;color:var(--ink-soft)}
code{background:#efe7d3;border-radius:3px;padding:1px 5px;font-family:Consolas,monospace;font-size:.9em}
/* v113: 家谱 (宝塔式世系图). One row per generation with the ancestor on top, so the clan reads
   downwards like a pagoda (宝塔式); the succession is drawn in red. */
#tree-btn,#epi-btn{font:inherit;padding:5px 14px;border:1px solid #8f7d55;background:#3a3121;color:var(--bar-ink);border-radius:5px;cursor:pointer}
#tree-btn.active,#epi-btn.active{background:var(--gold);border-color:var(--gold);color:#211a0c;font-weight:700}
#tree-btn[disabled]{opacity:.45;cursor:default}
.tree-host{font-family:"HarmonyOS Sans SC","鸿蒙黑体","HarmonyOS Sans","Noto Sans SC","Microsoft YaHei UI","Microsoft YaHei",sans-serif;background:#fdfaf0;border:1px solid var(--paper-edge);border-radius:3px;margin:14px 0 18px}
.tree-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;padding:8px 12px;border-bottom:1px solid #e4d9bd;background:#f6efdd;font-size:13px;color:var(--ink-soft)}
.tree-bar button{font:inherit;font-size:13px;padding:3px 10px;border:1px solid #c0ae86;background:#fffdf6;border-radius:4px;cursor:pointer}
.tree-bar .key{display:inline-flex;align-items:center;gap:5px}
.tree-bar .key i{display:inline-block;width:22px;height:0;border-top:2px solid #4a4238}
.tree-bar .key.red i{border-top-color:#b3352a}
.tree-scroll{overflow:auto;max-height:82vh;padding:6px}
.tree-scroll svg{display:block}
.row-band{fill:#f9f4e6}
.bead rect{fill:#fffdf6;stroke:#8d7f61;stroke-width:1}
.bead.subj rect{fill:#fdf3e2;stroke:#b3352a;stroke-width:1.6}
.bead.kin rect{fill:#f7f4ea}
/* v119: the bead text size comes from the SVG root's font-size, which is set from the monitor
   (see treeFontSize in the script); every other size is relative to it. */
.bead text{font-size:1em;fill:var(--ink);dominant-baseline:middle;text-anchor:middle;cursor:default}
.bead text.yr{font-size:.77em;fill:#8a7a55}
.bead text.tog{font-size:.77em;fill:#6f6247;text-anchor:middle}
.bead{cursor:pointer}
.bead:hover rect{stroke:var(--gold)}
.edge{fill:none;stroke:#4a4238;stroke-width:1.2}
.edge.red{stroke:#b3352a;stroke-width:2}
.edge.dashed{stroke:#b3352a;stroke-width:1.6;stroke-dasharray:5 4}
.spouse-link{fill:none;stroke:#a08a5e;stroke-width:1;stroke-dasharray:2 3}
.gen-head{font-size:1em;fill:#8a7a55;text-anchor:start}
/* v119: the family tree is the one view that wants the whole landscape screen — the essay pages keep
   their 880px measure, the tree drops it and takes whatever the monitor gives. */
body.tree-mode #wrap{max-width:none}
body.tree-mode #stage{max-width:none}
body.tree-mode .paper{padding:18px 20px 22px}
body.tree-mode .tree-scroll{max-height:calc(100vh - 200px)}
@media (max-width:640px){.paper{padding:22px 18px 26px}h1.masthead{font-size:24px}}
</style>
</head>
<body>
<div id="toolbar">
  <div class="left">
    <span class="session">__FOLDER__ · 家传阅读页</span>
    <div id="tabs"></div>
  </div>
  <div id="char-box">
    <button id="epi-btn" title="封档总评" style="display:none">封档总评</button>
    <button id="tree-btn" title="全族家谱">家谱</button>
    <label for="char-sel">角色</label>
    <select id="char-sel"></select>
  </div>
</div>
<div id="wrap">
  <nav id="toc"></nav>
  <div id="main">
    <div id="stage"></div>
    <div id="meta-line"></div>
  </div>
</div>
<script>
const DATA = __DATA__;
const CHARS = DATA.chars || [];
const TREE = DATA.tree || null;
const EPI = DATA.epilogue || null;
let ci = 0, ai = 0;
/* Chapter list of the left column: same shape for an article and for the 封档总评. */
function fillToc(tocEl, toc, rootText){
  tocEl.innerHTML = '';
  if(rootText){
    const r = document.createElement('div');
    r.className = 'toc-root';
    r.textContent = rootText;
    tocEl.appendChild(r);
  }
  if(!(toc || []).length){
    if(!rootText) tocEl.innerHTML = '<div class="empty">（无章节）</div>';
    return;
  }
  toc.forEach(t => {
    const link = document.createElement('a');
    link.href = '#' + t.id;
    link.textContent = t.text;
    link.className = 'lv' + Math.min(t.level, 3);
    link.onclick = (ev) => {
      ev.preventDefault();
      const el = document.getElementById(t.id);
      if(el){ el.scrollIntoView({behavior:'smooth', block:'start'}); }
      tocEl.querySelectorAll('a').forEach(x => x.classList.remove('hl'));
      link.classList.add('hl');
    };
    tocEl.appendChild(link);
  });
}
function showEpilogue(){
  if(!EPI) return;
  document.body.classList.remove('tree-mode');
  document.getElementById('tree-btn').classList.remove('active');
  document.getElementById('epi-btn').classList.add('active');
  const stage = document.getElementById('stage');
  const tocEl = document.getElementById('toc');
  document.getElementById('tabs').innerHTML = '';
  stage.innerHTML = '<div class="paper">' + EPI.html + '</div>';
  document.getElementById('meta-line').textContent = EPI.meta || '封档总评';
  fillToc(tocEl, EPI.toc, '封档总评');
  window.scrollTo({top:0, behavior:'smooth'});
}
function show(nci, nai){
  ci = nci; ai = nai;
  const ch = CHARS[ci];
  const stage = document.getElementById('stage');
  const meta = document.getElementById('meta-line');
  const tocEl = document.getElementById('toc');
  document.getElementById('tree-btn').classList.remove('active');
  document.getElementById('epi-btn').classList.remove('active');
  // essay pages keep their 880px measure; only the family tree takes the whole screen
  document.body.classList.remove('tree-mode');
  if(!ch){ stage.innerHTML = '<div class="empty">（无传记）</div>'; meta.textContent = ''; tocEl.innerHTML = '<div class="empty">（无章节）</div>'; return; }
  const tabs = document.getElementById('tabs');
  tabs.innerHTML = '';
  ch.items.forEach((it, i) => {
    const b = document.createElement('button');
    b.textContent = it.label;
    b.className = i === ai ? 'active' : '';
    b.onclick = () => show(ci, i);
    tabs.appendChild(b);
  });
  const a = ch.items[ai];
  stage.innerHTML = a ? '<div class="paper">' + a.html + '</div>' : '<div class="empty">（无传记）</div>';
  meta.textContent = a ? ch.name + ' ｜ ' + (a.meta || '') : ch.name;
  // v14: 左侧章节栏 — 由 markdown 标题生成, 点击滚动到对应锚点
  tocEl.innerHTML = '';
  const toc = (a && a.toc) || [];
  if(!toc.length){ tocEl.innerHTML = '<div class="empty">（无章节）</div>'; return; }
  toc.forEach(t => {
    const link = document.createElement('a');
    link.href = '#' + t.id;
    link.textContent = t.text;
    link.className = 'lv' + Math.min(t.level, 3);
    link.onclick = (ev) => {
      ev.preventDefault();
      const el = document.getElementById(t.id);
      if(el){ el.scrollIntoView({behavior:'smooth', block:'start'}); }
      tocEl.querySelectorAll('a').forEach(x => x.classList.remove('hl'));
      link.classList.add('hl');
    };
    tocEl.appendChild(link);
  });
}

/* ---- v113 家谱: 宝塔式 — 世代为行、始祖在上, 父子折线黑, 传主传承红 ---- */
const GAP_X = 18, ROW_H = 118, BEAD_W = 134, BEAD_H = 34, PAD_X = 40, PAD_Y = 34, GUT = 60;
const GEN_NUM = ['', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十',
                 '十一', '十二', '十三', '十四', '十五', '十六'];
const SUBJ_NUM = ['', '①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩',
                  '⑪', '⑫', '⑬', '⑭', '⑮'];

function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function yearOf(d){ return d ? String(d).split('.')[0] : ''; }
function lifeSpan(n){
  const b = yearOf(n.birth), d = yearOf(n.death || n.end);
  if(b && d && d !== b) return b + '–' + d;
  if(b) return b + '生';
  if(d) return d + '卒';
  return '';
}
/* SVG text ignores the bead box, so a long foreign name is squeezed into it (full-width glyphs
   take one em, the rest about 0.55) */
function fitText(s, maxPx, size){
  let w = 0;
  for(const ch of String(s || '')) w += (/[\u2e80-\u9fff\u3000-\u303f\uff00-\uffef]/.test(ch) ? 1 : 0.55) * size;
  return w <= maxPx ? '' : ' textLength="' + Math.round(maxPx) + '" lengthAdjust="spacingAndGlyphs"';
}

/* Nodes in scope for a piece whose played chain is `k` long, plus the tree's own child lists.
   An in-law hangs beside the clansman he married (「配」 bead) and never carries the tree edge. */
function scopeOf(k){
  const keep = (TREE.nodes || []).filter(n => (n.from_k || 1) <= k);
  const byId = {};
  keep.forEach(n => { byId[n.id] = n; });
  // 「传主」 is a role of this piece: a successor already on the tree as his father's son is not
  // one until the piece that follows him (v113)
  const isSubj = n => !!(n.subj && n.subj <= k);
  const kids = {}, spouses = {}, child = {};
  keep.forEach(n => {
    const sp = (n.spouse_of != null && byId[n.spouse_of]) ? n.spouse_of : null;
    if(sp != null){ (spouses[sp] = spouses[sp] || []).push(n.id); }
    else if(n.parent != null && byId[n.parent]){ (kids[n.parent] = kids[n.parent] || []).push(n.id); child[n.id] = 1; }
  });
  const roots = keep.filter(n => !child[n.id]).map(n => n.id);
  const red = {}, redNodes = {};
  (TREE.red_edges || []).forEach(e => { if(e[2] <= k - 2){ red[e[0] + '>' + e[1]] = 1; redNodes[e[0]] = 1; redNodes[e[1]] = 1; } });
  (TREE.red_dashed || []).forEach(e => { if(e[2] <= k - 2){ redNodes[e[0]] = 1; redNodes[e[1]] = 1; } });
  return {nodes: keep, byId: byId, kids: kids, spouses: spouses, roots: roots, red: red,
          redNodes: redNodes, isSubj: isSubj};
}

/* Bead order: from the clan's first member, each person, then the 配 beads beside him, then his
   children. A 宝塔式 page reads downwards and left to right, and this order is exactly the row
   order: a father stands before his own children and after his elders, so his 配 beads land next to
   him and his children stay together under him. (`collapsed` hides a branch without dropping the
   person himself; the branch that a collapsed bead hides is marked seen so the safety sweep cannot
   pull it back in.) */
function beadOrder(sc, collapsed){
  const order = [], seen = {};
  const skip = id => {
    if(seen[id]) return;
    seen[id] = 1;
    (sc.spouses[id] || []).forEach(skip);
    (sc.kids[id] || []).forEach(skip);
  };
  const walk = id => {
    if(seen[id]) return;
    seen[id] = 1; order.push(id);
    (sc.spouses[id] || []).forEach(s => { if(!seen[s]){ seen[s] = 1; order.push(s); } });
    if(collapsed[id]){ (sc.kids[id] || []).forEach(skip); return; }
    (sc.kids[id] || []).forEach(walk);
  };
  sc.roots.forEach(walk);
  // a node no walk reached (a broken parent link, never a collapsed branch) still gets a bead
  sc.nodes.forEach(n => { if(!seen[n.id]){ seen[n.id] = 1; order.push(n.id); } });
  return order;
}

/* Bead text size follows the monitor: 13px at 1080p (1920 physical px), 14px at 2K, clamped to
   12-20px. `A-`/`A+` in the tree bar overrule it and the choice is kept in localStorage, so a
   wrong guess (an external monitor, a scaled display) is one click away from being fixed. */
function treeFontSize(){
  let manual = 0;
  try{ manual = parseInt(localStorage.getItem('tree-fs') || '0', 10) || 0; }catch(e){ manual = 0; }
  if(manual >= 12 && manual <= 20) return manual;
  let phys = 1920;
  try{ phys = (screen.width || 1920) * (window.devicePixelRatio || 1); }catch(e){ phys = 1920; }
  return Math.max(12, Math.min(20, Math.round(13 + (phys - 1920) / 640)));
}

/* A-/A+ pick the bead text size by hand and keep it; 12-20px covers a small laptop panel up to a
   scaled 4K display. */
function setTreeFont(v){
  const fs = Math.max(12, Math.min(20, v));
  try{ localStorage.setItem('tree-fs', String(fs)); }catch(e){}
  return fs;
}

/* The played line plus the spouses beside it: the 「传主与配偶」 button narrows the chart to what the
   v119 default used to be, one branch at a time. The chart itself now opens every clansman (see
   `renderTree`), so the other branches are on screen without a click. */
function defaultOpen(sc, n){
  if(sc.isSubj(n) || sc.redNodes[n.id]) return 1;
  const sp = n.spouse_of;
  if(sp == null || !sc.byId[sp]) return 0;
  const p = sc.byId[sp];
  return !!(sc.isSubj(p) || sc.redNodes[sp]);
}

function renderTree(host, k){
  if(!TREE || !k){ host.innerHTML = '<div class="tree-bar">（尚无家谱数据）</div>'; return; }
  const sc = scopeOf(k);
  const collapsed = host._collapsed || (host._collapsed = {});
  if(!host._inited){
    host._inited = 1;
    // Every clansman of every branch is on the chart at the start: the family tree is the page the
    // reader goes to for "who else was in this family", so hiding the cadet branches turned it into a
    // played-line diagram and the other 分家 looked missing. 「传主与配偶」/「只留传主」 narrow it back.
    sc.nodes.forEach(n => { collapsed[n.id] = 0; });
  }
  const z = host._zoom || 1;
  // v119: the canvas takes the full width of the screen (see body.tree-mode), so the wide rows of a
  // fully opened family need less dragging than they did inside the reading column.
  const order = beadOrder(sc, {}).filter(id => !collapsed[id]);
  const drawn = {};
  order.forEach(id => { drawn[id] = 1; });
  const kidsOf = id => (sc.kids[id] || []).filter(x => drawn[x]);
  const spousesOf = id => (sc.spouses[id] || []).filter(x => drawn[x]);
  // text size and bead geometry share one factor, so a bigger font gets a bigger box rather than
  // squeezed glyphs (fitText below measures against the same numbers)
  const FS = treeFontSize(), BEAD_W = 134 * FS / 13, BEAD_H = 34 * FS / 13,
        ROW_H = 118 * FS / 13, GAP_X = 18 * FS / 13, PAD_X = 40 * FS / 13,
        PAD_Y = 34 * FS / 13, GUT = 60 * FS / 13;
  // 宝塔式: one row per generation, 始祖 at the top and each generation below its father's
  const row = {}, genList = {}, rowOf = {};
  order.forEach(id => {
    const g = sc.byId[id].gen || 1;
    if(!genList[g]){ genList[g] = []; }
    genList[g].push(id);
  });
  Object.keys(genList).map(Number).sort((a, b) => a - b).forEach((g, i) => {
    row[g] = genList[g];
    rowOf[g] = i;
  });
  const gens = Object.keys(row).map(Number).sort((a, b) => a - b);
  const xOf = {};
  // 宝塔式 placement: walk each line down, give the leaves the row's next free slot, then put the
  // father over the middle of his children — so a subtree owns a contiguous stretch and the rows
  // stay as narrow as their longest row. Two re-centre + repack rounds settle the overlaps.
  const slot = {};
  const placeNode = id => {
    if(xOf[id] != null) return;
    const g = sc.byId[id].gen || 1;
    const kids = kidsOf(id);
    kids.forEach(placeNode);
    if(kids.length){
      const a = kids.map(k => xOf[k]);
      xOf[id] = a.reduce((s, x) => s + x, 0) / a.length;
    } else {
      xOf[id] = slot[g] || 0;
      slot[g] = xOf[id] + BEAD_W + GAP_X;
    }
    // 配 beads sit beside their husband/wife and take their own room in the row
    spousesOf(id).forEach((s, j) => {
      if(xOf[s] != null) return;
      xOf[s] = xOf[id] + (j + 1) * (BEAD_W + GAP_X);
      slot[g] = Math.max(slot[g] || 0, xOf[s] + BEAD_W + GAP_X);
    });
  };
  sc.roots.filter(id => drawn[id]).forEach(placeNode);
  order.forEach(id => { if(xOf[id] == null){ xOf[id] = slot[sc.byId[id].gen || 1] || 0;
                                             slot[sc.byId[id].gen || 1] = xOf[id] + BEAD_W + GAP_X; } });
  const repack = g => {
    const ids = row[g];
    for(let i = 1; i < ids.length; i++){
      const need = xOf[ids[i - 1]] + BEAD_W + GAP_X;
      if(xOf[ids[i]] < need) xOf[ids[i]] = need;
    }
    for(let i = ids.length - 2; i >= 0; i--){
      const need = xOf[ids[i + 1]] - BEAD_W - GAP_X;
      if(xOf[ids[i]] > need) xOf[ids[i]] = need;
    }
  };
  for(let pass = 0; pass < 2; pass++){
    gens.forEach(g => {
      row[g].forEach(id => {
        const kids = (sc.kids[id] || []).filter(k => xOf[k] != null);
        if(kids.length){
          xOf[id] = kids.reduce((s, k) => s + xOf[k], 0) / kids.length;
        }
      });
      repack(g);
    });
  }
  gens.forEach(repack);
  let minX = Infinity, maxX = -Infinity;
  Object.keys(xOf).forEach(id => { minX = Math.min(minX, xOf[id]); maxX = Math.max(maxX, xOf[id]); });
  if(!isFinite(minX)){ minX = 0; maxX = 0; }
  Object.keys(xOf).forEach(id => { xOf[id] = Math.round(xOf[id] - minX + GUT + PAD_X); });
  const bx = id => xOf[id];
  const y = id => PAD_Y + rowOf[sc.byId[id].gen || 1] * ROW_H;
  const W = Math.round(Math.round(maxX - minX) + BEAD_W + PAD_X * 2 + GUT);
  const H = Math.round(PAD_Y * 2 + gens.length * ROW_H);
  const parts = [];
  gens.forEach(g => {
    const yy = PAD_Y + rowOf[g] * ROW_H;
    parts.push('<rect class="row-band" x="0" y="' + (yy - 9) + '" width="' + W + '" height="'
               + (BEAD_H + 18) + '"/>');
    parts.push('<text class="gen-head" x="12" y="' + (yy + 22) + '">' + (GEN_NUM[g] || g)
               + '世</text>');
    parts.push('<text class="gen-head" x="' + (W - 12) + '" y="' + (yy + 22)
               + '" text-anchor="end">' + (GEN_NUM[g] || g) + '世</text>');
  });
  // 配 beads hang beside their husband/wife behind a dashed couple link
  Object.keys(sc.spouses).forEach(pid => {
    sc.spouses[pid].forEach(sid => {
      if(xOf[pid] == null || xOf[sid] == null) return;
      const a = xOf[pid] + BEAD_W / 2, b = xOf[sid] + BEAD_W / 2;
      const x1 = a < b ? xOf[pid] + BEAD_W : xOf[pid], x2 = a < b ? xOf[sid] : xOf[sid] + BEAD_W;
      parts.push('<path class="spouse-link" d="M' + x1 + ',' + (y(pid) + BEAD_H / 2)
                 + ' H' + x2 + '"/>');
    });
  });
  // 宝塔式 descent: down out of the father, across the gap, then down onto the child. A child that
  // the data still puts on its father's own row (a lifted gen should prevent it) is linked under
  // that row instead, so the line never runs backwards through the beads
  order.forEach(id => {
    const n = sc.byId[id], p = n.parent;
    if(p == null || !sc.byId[p] || xOf[p] == null) return;
    const cls = sc.red[p + '>' + id] ? 'edge red' : 'edge';
    const pxc = xOf[p] + BEAD_W / 2, py = y(p) + BEAD_H;
    const cxc = xOf[id] + BEAD_W / 2;
    if(rowOf[n.gen || 1] > rowOf[sc.byId[p].gen || 1]){
      const cy = y(id), by = py + Math.max(16, (cy - py) / 2 - BEAD_H / 2);
      parts.push('<path class="' + cls + '" d="M' + pxc + ',' + py + ' V' + by + ' H' + cxc
                 + ' V' + cy + '"/>');
    } else {
      const by = py + 16;
      parts.push('<path class="' + cls + '" d="M' + pxc + ',' + py + ' V' + by + ' H' + cxc
                 + ' V' + (y(id) + BEAD_H) + '"/>');
    }
  });
  (TREE.red_dashed || []).forEach(e => {
    if(e[2] > k - 2 || xOf[e[0]] == null || xOf[e[1]] == null) return;
    parts.push('<path class="edge dashed" d="M' + (xOf[e[0]] + BEAD_W / 2) + ','
               + (y(e[0]) + BEAD_H / 2) + ' H' + (xOf[e[1]] + BEAD_W / 2) + '"/>');
  });
  order.forEach(id => {
    const n = sc.byId[id], x = bx(id), yy = y(id);
    const isSpouse = n.spouse_of != null;
    const subj = sc.isSubj(n) ? n.subj : 0;
    const cls = subj ? 'bead subj' : (isSpouse ? 'bead kin' : 'bead');
    const note = isSpouse ? (n.spouse_word || '配') : (subj ? '' : (n.note || ''));
    // ▼ marks a bead whose descendants are drawn, ▶ one whose branch is closed
    const tog = (sc.kids[id] || []).length ? (kidsOf(id).length ? '▼' : '▶') : '';
    const nm = (subj ? SUBJ_NUM[subj] + ' ' : '') + (n.name || '');
    const sub = [lifeSpan(n), note].filter(Boolean).join(' · ');
    parts.push('<g class="' + cls + '" data-id="' + id + '"><title>' + esc(n.label || n.name) + '</title>'
      + '<rect x="' + x + '" y="' + yy + '" width="' + BEAD_W + '" height="' + BEAD_H + '" rx="4"/>'
      + '<text x="' + (x + BEAD_W / 2) + '" y="' + (yy + FS) + '"'
      + fitText(nm, BEAD_W - 12, FS) + '>' + esc(nm) + '</text>'
      + '<text class="yr" x="' + (x + BEAD_W / 2) + '" y="' + (yy + FS * 2) + '"'
      + fitText(sub, BEAD_W - 22, FS * 0.77) + '>' + esc(sub) + '</text>'
      + (tog ? '<text class="tog" x="' + (x + BEAD_W - 9) + '" y="' + (yy + BEAD_H / 2) + '">' + tog + '</text>' : '')
      + '</g>');
  });
  const chain = (TREE.chain || []).slice(0, k);
  const bar = '<div class="tree-bar">'
    + '<span class="key red"><i></i>传主传承</span><span class="key"><i></i>父子相承</span>'
    + '<span>本图 ' + order.length + ' / ' + sc.nodes.length + ' 人 · 传主 ' + chain.length + ' 位'
    + ' · 字号 ' + FS + 'px</span>'
    + '<button data-z="out">缩小</button><button data-z="in">放大</button>'
    + '<button data-z="fit">原大</button><button data-z="open">全族</button>'
    + '<button data-z="def">传主与配偶</button>'
    + '<button data-z="chain">只留传主</button>'
    + '<button data-z="fs-">A-</button><button data-z="fs+">A+</button>'
    + '</div>';
  host.innerHTML = bar + '<div class="tree-scroll">'
    + '<svg xmlns="http://www.w3.org/2000/svg" width="' + Math.round(W * z) + '" height="'
    + Math.round(H * z) + '" viewBox="0 0 ' + W + ' ' + H + '" font-size="' + FS + '">'
    + parts.join('') + '</svg></div>';
  host.querySelectorAll('.bead').forEach(el => {
    el.onclick = () => {
      const id = el.getAttribute('data-id');
      const kids = sc.kids[id] || [];
      if(!kids.length) return;
      // One click opens or closes the whole branch below the bead, so a line is revealed in one
      // go instead of one generation at a time
      const open = !kidsOf(id).length;
      const stack = kids.slice();
      while(stack.length){
        const x = stack.pop();
        collapsed[x] = open ? 0 : 1;
        (sc.kids[x] || []).forEach(c => stack.push(c));
      }
      renderTree(host, k);
    };
  });
  // 宝塔式 reads down from the 始祖, so the first view is centred on him instead of on the left edge
  const scroller = host.querySelectorAll('.tree-scroll')[0];
  if(scroller && !host._scrolled){
    host._scrolled = 1;
    const first = (TREE.chain || [])[0];
    const p0 = (first && xOf[first.id] != null) ? xOf[first.id] : 0;
    scroller.scrollLeft = Math.max(0, (p0 + BEAD_W / 2) * z - (scroller.clientWidth || 900) / 2);
  }
  host.querySelectorAll('.tree-bar button').forEach(b => {
    b.onclick = () => {
      const a = b.getAttribute('data-z');
      if(a === 'in') host._zoom = Math.min(2, z + 0.15);
      else if(a === 'out') host._zoom = Math.max(0.45, z - 0.15);
      else if(a === 'fit') host._zoom = 1;
      else if(a === 'open'){ sc.nodes.forEach(n => { collapsed[n.id] = 0; }); }
      else if(a === 'def'){ sc.nodes.forEach(n => { collapsed[n.id] = defaultOpen(sc, n) ? 0 : 1; }); }
      else if(a === 'chain'){ sc.nodes.forEach(n => { collapsed[n.id] = (sc.isSubj(n) || sc.redNodes[n.id]) ? 0 : 1; }); }
      else if(a === 'fs-') setTreeFont(FS - 1);
      else if(a === 'fs+') setTreeFont(FS + 1);
      renderTree(host, k);
    };
  });
}

function showTree(){
  if(!TREE) return;
  const k = (TREE.chain || []).length;
  const stage = document.getElementById('stage');
  const tocEl = document.getElementById('toc');
  stage.innerHTML = '<div class="paper"><h2>家谱</h2>'
    + '<div class="tree-host" data-k="' + k + '"></div></div>';
  document.getElementById('meta-line').textContent = '全族家谱 ｜ 宝塔式世系图';
  document.getElementById('tabs').innerHTML = '';
  document.getElementById('tree-btn').classList.add('active');
  document.body.classList.add('tree-mode');
  renderTree(stage.querySelector('.tree-host'), k);
  tocEl.innerHTML = '<div class="toc-root">家谱</div>';
  if(TREE.fanli){
    const d = document.createElement('div');
    d.style.cssText = 'color:#cbbf9f;line-height:1.7;padding:2px 6px';
    d.textContent = TREE.fanli;
    tocEl.appendChild(d);
  }
  (TREE.chain || []).forEach(c => {
    const a = document.createElement('a');
    a.textContent = SUBJ_NUM[c.i] + ' ' + c.name;
    a.className = c.i === k ? 'lv2 hl' : 'lv2';
    tocEl.appendChild(a);
  });
}

const sel = document.getElementById('char-sel');
CHARS.forEach((ch, i) => {
  const o = document.createElement('option');
  o.value = i; o.textContent = ch.name;
  sel.appendChild(o);
});
sel.onchange = () => show(parseInt(sel.value, 10), 0);
const treeBtn = document.getElementById('tree-btn');
if(!TREE || !(TREE.chain || []).length){
  treeBtn.disabled = true;
  treeBtn.title = '本族尚无家谱数据（终传出稿后自动带上）';
} else {
  treeBtn.onclick = showTree;
}
// 封档总评 exists only after `pipeline.py epilogue` has written it
const epiBtn = document.getElementById('epi-btn');
if(EPI){
  epiBtn.style.display = '';
  epiBtn.onclick = showEpilogue;
}
show(0, 0);
</script>
</body>
</html>
"""


def _parse_header(text):
    """Parse the Markdown header comment (person / person id / birth year / piece / decade /
    playthrough id / reign date) into a dict. The trailing `-->` is removed first: the last
    field has no following separator, so `[^|]+` would otherwise swallow it."""
    out = {}
    for ln in (text or "").split("\n"):
        if not ln.strip().startswith("<!--"):
            continue
        ln = ln.replace("-->", " ")
        m = re.search(r"人物:\s*([^|]+)", ln)
        p = re.search(r"篇目:\s*([^|]+)", ln)
        d = re.search(r"十年:\s*(\d+)", ln)
        i = re.search(r"人物ID:\s*(\d+)", ln)
        b = re.search(r"出生:\s*(\d+)年", ln)
        t = re.search(r"战役ID:\s*([^|]+)", ln)
        g = re.search(r"执政:\s*(\d+\.\d+\.\d+)", ln)
        if m:
            out["person"] = m.group(1).strip()
        if p:
            out["piece"] = p.group(1).strip()
        if d:
            out["decade"] = int(d.group(1))
        if i:
            out["person_id"] = i.group(1)
        if b:
            out["birth_year"] = int(b.group(1))
        if t:
            out["playthrough_id"] = t.group(1).strip()
        if g:
            out["reign"] = g.group(1)
        break
    return out


_FILENAME_PERSON_RE = re.compile(r"^(.*?)\((\d+)\)$")
_EPITHET_SUFFIX_RE = re.compile(r'[“"][^”"]*[”"]\s*$')
# Nicknames are prefixed rather than quoted, so a heuristic strips a 1-4 character prefix
# ending in a nickname-ish character. Fallback only: the main path merges by filename base
# name or person id (see _person_identity).
_EPITHET_PREFIX_RE = re.compile(
    r'^([\u4e00-\u9fff]{1,4}(?:者|头|狂|痴))([\u4e00-\u9fff]{2,})$')


def _strip_epithet(name):
    """Strip the epithet from a display name (quoted suffix or prefixed nickname); returned
    unchanged when there is none."""
    if not name:
        return name
    s = _EPITHET_SUFFIX_RE.sub("", name).strip()
    if s and s != name:
        return s
    m = _EPITHET_PREFIX_RE.match(s or name)
    if m and not m.group(2).startswith(m.group(1)):
        return m.group(2)
    return s or name


def _filename_base_person(fn, folder):
    """Fallback character name taken from a filename: drop the family prefix and the
    (birth year) suffix; returns (base name, birth year or None). Filenames come from the
    cached plain names (name_full/name_zh), so they carry no epithet and are stable."""
    base = fn
    for sep in ("_终传_", "_传记_"):
        if sep in fn:
            base = fn.split(sep, 1)[0]
            break
    if folder and base.startswith(folder):
        base = base[len(folder):]
    m = _FILENAME_PERSON_RE.match(base)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return base.strip(), None


def _person_identity(fn, folder, text, h=None):
    """Return (group key, display name) for a stable identity: the header person id when
    present (most exact, with the campaign id to avoid cross-campaign merges), else
    (epithet-stripped name, birth year) from the header or filename — so the same character
    keeps one key even as the epithet changes over time."""
    h = h if h is not None else _parse_header(text)
    person = h.get("person") or ""
    if h.get("person_id"):
        # The person id is unique inside a campaign but reused across campaigns, so the key
        # carries the campaign id
        return (("id", h["person_id"], h.get("playthrough_id")),
                _strip_epithet(person) or person)
    fbase, fyear = _filename_base_person(fn, folder)
    year = h.get("birth_year")
    if year is None:
        year = fyear
    if person and fbase and fbase in person:
        base = fbase  # the filename base name is the header name (with epithet) minus the epithet
    else:
        base = _strip_epithet(person) or person or fbase
    return ("name", base, year), base


def _article_label(fn, text, folder=None, h=None):
    """Return (label, meta) for one article: the Chinese label of a decade / final / ordinary
    biography plus its date line; files without a header comment fall back to the filename
    or to the first title line."""
    title = os.path.splitext(fn)[0]
    for ln in (text or "").split("\n"):
        s = ln.strip()
        if not s or s.startswith("<!--"):
            continue
        if s.startswith("# "):
            title = s[2:].strip().strip("《》")
            break
        if s.startswith("#"):
            title = s.lstrip("# ").strip()
            break
        break  # first non-comment, non-blank line is not a title -> fall back to the filename
    m = re.search(r"_(终传|传记)_(?:第\d+个十年_)?(\d+_\d{2}_\d{2})", fn)
    date = m.group(2).replace("_", ".") if m else ""
    h = h if h is not None else _parse_header(text)
    kind = m.group(1) if m else ""
    if h.get("decade") is not None:
        label = f"第{h['decade']}个十年传记"
        return label, f"至{date}" if date else ""
    if h.get("piece") == "终传" or kind == "终传":
        return f"{title}（终传）", f"死于{date}" if date else ""
    if kind == "传记":
        return f"{title}（传记）", f"至{date}" if date else ""
    return title, ""


# --- Reading-page sort keys ---------------------------------------------------
# Never filename lexicographic order: the subject's in-game name (and with it the filename
# prefix) changes with culture and would reorder entries. Semantic keys instead —
# characters by (campaign, reign date, birth year, name), pieces by coverage end date.

# Unknown-date sentinel matching cl.date_key; sort keys stay tuples, since comparing a tuple
# with an int raises TypeError.
_UNKNOWN_KEY = (9999, 0, 0)


def _reign_key(h):
    """Reign-order key for a character: the header reign date written by
    biography.reign_start, else the birth year — an approximation on the same scale, so
    mixed old and new files still keep their generational order."""
    r = h.get("reign")
    if r:
        return cl.date_key(r)
    by = h.get("birth_year")
    return (by, 0, 0) if by else _UNKNOWN_KEY


# Piece-type order when dates tie: living biography -> decade biography -> final biography
_PIECE_KIND = {"传记": 0, "十年": 1, "终传": 2}


def _piece_key(fn, h):
    """Piece-order key: coverage end date ascending (decade end / death date / last
    snapshot date for a living biography), ties broken living -> decade -> final."""
    m = re.search(r"_(\d+)_(\d{2})_(\d{2})\.md$", fn)
    d = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else _UNKNOWN_KEY
    if h.get("decade") is not None:
        kind = _PIECE_KIND["十年"]
    elif h.get("piece") == "终传":
        kind = _PIECE_KIND["终传"]
    else:
        kind = _PIECE_KIND["传记"]
    return (d, kind)


def _entry_sort_key(fn, h, pkey):
    """Total entry order: (campaign id, reign/birth, birth year, character key, piece, filename).

    The character component is the stable identity key from _person_identity, never the
    display name, which follows the in-game name order and would misorder a character's own
    pieces; keys are stringified tuples, so a None birth year cannot be compared with an int."""
    return (h.get("playthrough_id") or "",
            _reign_key(h),
            h.get("birth_year") or 9999,
            tuple("" if x is None else str(x) for x in pkey),
            _piece_key(fn, h),
            fn)


def _load_tree(base):
    """Family tree sidecar for the reading page: data/genealogy*.json, the one reaching furthest.

    `biography` writes this beside the articles (it owns the facts); every 终传 rebuild overwrites
    it only with a tree at least as long, so the file always holds the family's full line."""
    best = None
    ddir = os.path.join(base, "data")
    if not os.path.isdir(ddir):
        return None
    for fn in sorted(os.listdir(ddir)):
        if not (fn.startswith("genealogy") and fn.endswith(".json")):
            continue
        try:
            with open(os.path.join(ddir, fn), encoding="utf-8") as f:
                t = json.load(f)
        except Exception:
            continue
        if not (t.get("nodes") and t.get("chain")):
            continue
        if best is None or len(t.get("chain") or []) > len(best.get("chain") or []):
            best = t
    return best


# 封档总评 (campaign epilogue): a family-level article with its own toolbar button, so it stays out of
# the per-character menu. Written by `pipeline.py epilogue`.
_EPILOGUE_RE = re.compile(r"^(.+)_封档总评_(\d{4})_(\d{2})_(\d{2})\.md$")


def _load_epilogue(base):
    """Newest `<家族>_封档总评_<存档>.md` of a folder as a reading-page entry, or None when absent."""
    best = None
    for fn in os.listdir(base):
        m = _EPILOGUE_RE.match(fn)
        if not m:
            continue
        date = f"{m.group(2)}.{int(m.group(3))}.{int(m.group(4))}"
        if best is None or date > best[0]:
            best = (date, os.path.join(base, fn))
    if best is None:
        return None
    try:
        with open(best[1], encoding="utf-8") as fp:
            text = fp.read()
    except OSError:
        return None
    html_str, toc = md_to_html(text)
    return {"html": html_str, "toc": toc, "file": os.path.basename(best[1]),
            "meta": f"封档总评 ｜ 存档 {best[0]} ｜ {os.path.basename(base)}"}


def rebuild_folder(output_dir, folder):
    """Build/update index.html for one family folder; returns None when there is no md.
    Entries are grouped per character: character menu top right, that character's pieces
    top left."""
    base = os.path.join(output_dir, folder)
    if not os.path.isdir(base):
        return None
    tree = _load_tree(base)
    epilogue = _load_epilogue(base)
    entries = []
    for fn in sorted(os.listdir(base)):
        if not fn.lower().endswith(".md"):
            continue
        if not FILE_RE.match(fn):
            continue
        path = os.path.join(base, fn)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        h = _parse_header(text)
        label, meta = _article_label(fn, text, folder, h)
        html_str, toc = md_to_html(text)
        pkey, disp = _person_identity(fn, folder, text, h)
        entries.append({
            "person": disp,
            "person_key": pkey,
            "label": label,
            "meta": meta,
            "html": html_str,
            "toc": toc,
            "sort_key": _entry_sort_key(fn, h, pkey),
        })
    if not entries:
        return None
    # Semantic ordering, not filename order — see the sort-key note above
    entries.sort(key=lambda e: e["sort_key"])
    for e in entries:
        e.pop("sort_key", None)
    # Group by character using the stable identity key (person id first, else
    # epithet-stripped name + birth year), so a changing epithet does not split a page
    groups = []
    by_key = {}
    for e in entries:
        if e["person_key"] not in by_key:
            by_key[e["person_key"]] = len(groups)
            groups.append({"name": e["person"], "person_key": e["person_key"],
                           "items": []})
        groups[by_key[e["person_key"]]]["items"].append(
            {"label": e["label"], "meta": e["meta"], "html": e["html"],
             "toc": e["toc"]})
    # A name shared across birth years (grandfather and grandson) gets (birth year) appended
    same_name = {}
    for g in groups:
        same_name.setdefault(g["name"], []).append(g)
    for name, gl in same_name.items():
        if len(gl) > 1:
            for g in gl:
                k = g.get("person_key")
                by = k[2] if k and k[0] == "name" else None
                if by:
                    g["name"] = f"{g['name']}({by})"
    # person_key is for grouping only and is not written into __DATA__
    for g in groups:
        g.pop("person_key", None)
    title = f"{folder} · 家传阅读页"
    payload = {"chars": groups, "tree": tree, "epilogue": epilogue}
    # `<\/` is the same JSON string as `</`: escaping it keeps a name from closing the inline
    # <script> early (and from opening an HTML comment)
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out = (TEMPLATE
           .replace("__TITLE__", html.escape(title))
           .replace("__FOLDER__", html.escape(folder))
           .replace("__DATA__", data))
    path = os.path.join(base, "index.html")
    # Unique temp name: the main thread and a biography thread may rebuild the same page at
    # once, and a shared .tmp would truncate each other
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, path)
    return path


def cmd_rebuild(args):
    output_dir = _output_dir()
    if not os.path.isdir(output_dir):
        print(f"输出目录不存在: {output_dir}")
        return 1
    if args:
        targets = list(args)
    else:
        targets = sorted(os.listdir(output_dir))
    total = 0
    for name in targets:
        base = os.path.join(output_dir, name)
        if not os.path.isdir(base):
            continue
        path = rebuild_folder(output_dir, name)
        if path:
            print(f"[{name}] 阅读页已生成: {path}")
            total += 1
    print(f"完成: 生成 {total} 个阅读页")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "rebuild"
    if cmd != "rebuild":
        print("用法: python htmlview.py rebuild [家族名 ...]")
        return 1
    return cmd_rebuild(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
