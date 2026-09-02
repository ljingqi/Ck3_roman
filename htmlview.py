# -*- coding: utf-8 -*-
"""阅读页生成器 (htmlview.py) — CK3 人物传记版
============================================
把 output/<家族>/ 下的传记 Markdown 汇总成一个自包含的 index.html:
  - 同一页面内可切换各篇传记 (按人物/日期);
  - 全部样式与脚本内嵌, 不依赖任何外部资源, 离线双击即可阅读。

用法:
  python htmlview.py rebuild [家族名 ...]   生成/更新指定家族阅读页 (缺省全部)
"""
import html
import json
import os
import re
import sys
import threading

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


# ---------------------------------------------------------------------------
# Markdown → HTML (覆盖传记输出实际用到的语法子集)
# ---------------------------------------------------------------------------

def _inline(text):
    """行内语法: 先转义 HTML, 再处理粗体/斜体/行内代码。"""
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
    """连续列表行 (可能含前导空格缩进) → 按缩进层级构建嵌套 <ul>。
    例: ['- 1070年', '  - 4月', '    - 9日：事件'] → 三层嵌套 <ul>。"""
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
    """整篇 Markdown → (HTML 片段, 章节清单)。
    章节清单: [{level, text, id}] — 供左侧章节栏用 markdown 标题跳转 (v14)。"""
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
            # v14: 标题锚点 id (章节栏跳转用)
            hd_count += 1
            hd_id = f"hd-{hd_count}"
            out.append(f'<h{level} id="{hd_id}"{cls}>{_inline(htext)}</h{level}>')
            # 仅收录 1-3 级标题进章节栏; h1 为传名 (一篇只一个, 作目录根)
            if level <= 3:
                # v14: 正则去重 — 同一标题语义只留第一个 (旧文件可能带模型
                # 误输出的短版重复/文章标题重复, 程序侧兜底, 不动提示词)。
                # 归一化: 去数字序号/书名号/已知板块前缀 (开篇·纪事·列传·本纪·…),
                # 短版重复 (开篇·家世与交游 vs 家世与交游) 与 文章标题混入 归同键。
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


# ---------------------------------------------------------------------------
# 家族阅读页 (index.html)
# ---------------------------------------------------------------------------

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
    """从 md 头部注释解析 人物/人物ID/出生/篇目/十年 (v8, v20)。"""
    out = {}
    for ln in (text or "").split("\n"):
        if not ln.strip().startswith("<!--"):
            continue
        m = re.search(r"人物:\s*([^|]+)", ln)
        p = re.search(r"篇目:\s*([^|]+)", ln)
        d = re.search(r"十年:\s*(\d+)", ln)
        i = re.search(r"人物ID:\s*(\d+)", ln)
        b = re.search(r"出生:\s*(\d+)年", ln)
        t = re.search(r"战役ID:\s*([^|]+)", ln)
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
        break
    return out


_FILENAME_PERSON_RE = re.compile(r"^(.*?)\((\d+)\)$")
_EPITHET_SUFFIX_RE = re.compile(r'[“"][^”"]*[”"]\s*$')
# v21: 昵称改前缀式 (欺诈者郭靖 / 秃头仲宣) — 旧格式靠引号后缀识别,
# 新格式无引号, 用启发式剥「以 者/头 等结尾的 1–4 字前缀」(仅兜底; 主路径
# 靠文件名基名/人物ID 归并, 见 _person_identity)。
_EPITHET_PREFIX_RE = re.compile(
    r'^([\u4e00-\u9fff]{1,4}(?:者|头|狂|痴))([\u4e00-\u9fff]{2,})$')


def _strip_epithet(name):
    """去显示名里的绰号 (旧格式 名“绰号” 后缀 / 新格式 绰号名前缀; 无则原样)。"""
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
    """文件名回退角色名: 去 家族前缀 与 (生年) 后缀。返回 (基名, 生年|None)。
    文件名来自缓存纯名 (name_full/name_zh), 不带绰号, 是稳定的身份线索。"""
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


def _person_identity(fn, folder, text):
    """(分组键, 显示名) — v20 稳定身份:
    - A2: 头部注释有 人物ID (游戏角色 id) → 键 ('id', pid), 最精确;
    - A1: 否则 键 ('name', 去绰号名, 生年) — 生年取头部 出生 或文件名 (849),
      去绰号优先用文件名基名 (缓存纯名), 无则剥头部 名“绰号”后缀 / 绰号前缀。
    同角色因绰号随时代变化 (嗜血者→屠狼者) 也归并到同一键。"""
    h = _parse_header(text)
    person = h.get("person") or ""
    if h.get("person_id"):
        # A2: 人物ID 唯一, 同战役复用同 id 也同页; 战役ID 参与键防跨战役同 id 误并
        return (("id", h["person_id"], h.get("playthrough_id")),
                _strip_epithet(person) or person)
    fbase, fyear = _filename_base_person(fn, folder)
    year = h.get("birth_year")
    if year is None:
        year = fyear
    if person and fbase and fbase in person:
        base = fbase  # 文件名基名是头部名 (带绰号) 的子串 → 取纯名
    else:
        base = _strip_epithet(person) or person or fbase
    return ("name", base, year), base


def _article_label(fn, text, folder=None):
    """标签: 十年传记/终传 语义化 (v8)。返回 (label, meta)。
    - 十年传记: 「第N个十年传记」+「至<日期>」
    - 终传: 「终传」+「死于<日期>」
    - 普通传记: 「传记」+「至<日期>」
    - 旧文件 (无头部注释): 回退文件名/首行标题。"""
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
        break  # 首个非注释非空行不是标题 → 用文件名
    m = re.search(r"_(终传|传记)_(?:第\d+个十年_)?(\d+_\d{2}_\d{2})", fn)
    date = m.group(2).replace("_", ".") if m else ""
    h = _parse_header(text)
    kind = m.group(1) if m else ""
    if h.get("decade") is not None:
        label = f"第{h['decade']}个十年传记"
        return label, f"至{date}" if date else ""
    if h.get("piece") == "终传" or kind == "终传":
        return f"{title}（终传）", f"死于{date}" if date else ""
    if kind == "传记":
        return f"{title}（传记）", f"至{date}" if date else ""
    return title, ""


def rebuild_folder(output_dir, folder):
    """为单个家族文件夹生成/更新 index.html; 无任何 md 时返回 None。
    v8: 按角色分组 — 右上角色菜单, 左上该角色的十年传记/终传列表。"""
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
        label, meta = _article_label(fn, text, folder)
        html_str, toc = md_to_html(text)
        pkey, disp = _person_identity(fn, folder, text)
        entries.append({
            "person": disp,
            "person_key": pkey,
            "label": label,
            "meta": meta,
            "html": html_str,
            "toc": toc,
        })
    if not entries:
        return None
    # 按角色分组 (v20: 稳定身份键 — 人物ID 优先, 否则 去绰号名+生年;
    # 绰号随时代变化 (嗜血者→屠狼者) 不再拆页)
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
    # 同名不同生年 (祖孙同名) 显示名追加 (生年) 消歧, 与文件名口径一致
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
    # person_key 仅分组内部使用, 不进 __DATA__
    for g in groups:
        g.pop("person_key", None)
    title = f"{folder} · 家传阅读页"
    out = (TEMPLATE
           .replace("__TITLE__", html.escape(title))
           .replace("__FOLDER__", html.escape(folder))
           .replace("__DATA__", json.dumps(groups, ensure_ascii=False)))
    path = os.path.join(base, "index.html")
    # 唯一临时名 (主线程与后台传记线程可能并发重建同一阅读页, 共享 .tmp 会互相截断)
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
