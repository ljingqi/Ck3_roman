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
let ci = 0, ai = 0;
function show(nci, nai){
  ci = nci; ai = nai;
  const ch = DATA[ci];
  const stage = document.getElementById('stage');
  const meta = document.getElementById('meta-line');
  const tocEl = document.getElementById('toc');
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
const sel = document.getElementById('char-sel');
DATA.forEach((ch, i) => {
  const o = document.createElement('option');
  o.value = i; o.textContent = ch.name;
  sel.appendChild(o);
});
sel.onchange = () => show(parseInt(sel.value, 10), 0);
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


def rebuild_folder(output_dir, folder):
    """Build/update index.html for one family folder; returns None when there is no md.
    Entries are grouped per character: character menu top right, that character's pieces
    top left."""
    base = os.path.join(output_dir, folder)
    if not os.path.isdir(base):
        return None
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
    out = (TEMPLATE
           .replace("__TITLE__", html.escape(title))
           .replace("__FOLDER__", html.escape(folder))
           .replace("__DATA__", json.dumps(groups, ensure_ascii=False)))
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
