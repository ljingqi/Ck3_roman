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
    """整篇 Markdown → HTML 片段 (不含 <html> 外壳)。"""
    lines = text.split("\n")
    out = []
    i, n = 0, len(lines)
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
            cls = ' class="masthead"' if level == 1 else ""
            out.append(f"<h{level}{cls}>{_inline(m.group(2))}</h{level}>")
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
    return "\n".join(out)


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
#stage{max-width:880px;margin:28px auto 8px;padding:0 14px}
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
<div id="stage"></div>
<div id="meta-line"></div>
<script>
const DATA = __DATA__;
let ci = 0, ai = 0;
function show(nci, nai){
  ci = nci; ai = nai;
  const ch = DATA[ci];
  const stage = document.getElementById('stage');
  const meta = document.getElementById('meta-line');
  if(!ch){ stage.innerHTML = '<div class="empty">（无传记）</div>'; meta.textContent = ''; return; }
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
    """从 md 头部注释解析 人物/出生/篇目/十年 (v8)。"""
    out = {}
    for ln in (text or "").split("\n"):
        if not ln.strip().startswith("<!--"):
            continue
        m = re.search(r"人物:\s*([^|]+)", ln)
        p = re.search(r"篇目:\s*([^|]+)", ln)
        d = re.search(r"十年:\s*(\d+)", ln)
        if m:
            out["person"] = m.group(1).strip()
        if p:
            out["piece"] = p.group(1).strip()
        if d:
            out["decade"] = int(d.group(1))
        break
    return out


def _person_of(fn, folder, text):
    """角色名: 优先头部注释 人物; 回退文件名去 家族前缀 (菲利普崔佛 → 崔佛)。"""
    h = _parse_header(text)
    if h.get("person"):
        return h["person"]
    base = fn
    for sep in ("_终传_", "_传记_"):
        if sep in fn:
            base = fn.split(sep, 1)[0]
            break
    if folder and base.startswith(folder):
        base = base[len(folder):]
    return base or fn


def _article_label(fn, text, folder=None):
    """标签: 十年传记/终传 语义化 (v8)。返回 (label, meta)。
    - 十年传记: 「第N个十年传记」+「至<日期>」
    - 终传: 「终传」+「殁于<日期>」
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
        return f"{title}（终传）", f"殁于{date}" if date else ""
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
        entries.append({
            "person": _person_of(fn, folder, text),
            "label": label,
            "meta": meta,
            "html": md_to_html(text),
        })
    if not entries:
        return None
    # 按角色分组 (保持首次出现顺序)
    groups = []
    by_name = {}
    for e in entries:
        if e["person"] not in by_name:
            by_name[e["person"]] = len(groups)
            groups.append({"name": e["person"], "items": []})
        groups[by_name[e["person"]]]["items"].append(
            {"label": e["label"], "meta": e["meta"], "html": e["html"]})
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
