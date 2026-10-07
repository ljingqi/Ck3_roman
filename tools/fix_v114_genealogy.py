# -*- coding: utf-8 -*-
"""v114 一次性文本手术：把成稿附录 `### 世系` 的**头行**换成带称谓与封圣年的新行。

正文一字不动（用户定规：绝不用模型重生成既有正文），只改程序产物——附录世系是
`facts._genealogy_parts` 的输出，头行按当前代码应为 `person_label(cid, date, "full")`
＋（已封圣者）「，〈年〉年封圣」。九篇终传的这九行在这批稿子里逐字相同（探针
`tools/tests/v114_probe_shixi*.py` 已核），所以按世次一一对应替换即可，行数或行序不符
则整体放弃。

用法：
    python tools/tests/../fix_v114_genealogy.py --dry
    python tools/tests/../fix_v114_genealogy.py --apply
    python tools/tests/../fix_v114_genealogy.py --restore
    python tools/tests/../fix_v114_genealogy.py --tree        # 由快照写 data/genealogy.json

--tree 只写阅读页用的家谱数据（`biography._write_genealogy_tree` 的同一份内容），
不碰任何 .md。
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.join(ROOT, "output", "洪氏2")
SNAP = os.path.join(BASE, "data", "snap_v114_207044_final.json")
BACKUP = os.path.join(ROOT, "logs", "v114_shixi_backup.json")
HEAD_RE = re.compile(r"^- \*\*[一二三四五六七八九十]+世\*\*　")


def snap_facts():
    with io.open(SNAP, encoding="utf-8") as fp:
        return json.load(fp)["facts"]


def new_heads(facts):
    """The new head lines, in generation order, straight from the snapshot's own 世系."""
    out = []
    for ln in facts.get("genealogy") or []:
        if ln.startswith("**"):
            out.append("- " + ln)
    return out


def block_span(lines):
    """(start, end) of the block after `### 世系` inside one file's lines."""
    try:
        i = lines.index("### 世系")
    except ValueError:
        return None
    j = i + 1
    while j < len(lines):
        ln = lines[j]
        if ln.startswith("### ") or (ln.startswith("#") and not ln.startswith("- ")):
            break
        j += 1
    return i + 1, j


def head_index(lines, start, end):
    return [k for k in range(start, end) if HEAD_RE.match(lines[k])]


def targets():
    out = []
    for fn in sorted(os.listdir(BASE)):
        if not fn.endswith(".md"):
            continue
        out.append(fn)
    return out


def read_lines(path):
    """(lines, line ending) — the ending is preserved so the diff stays on the head lines."""
    with io.open(path, encoding="utf-8", newline="") as fp:
        raw = fp.read()
    eol = "\r\n" if "\r\n" in raw else "\n"
    return raw.splitlines(), eol


def write_lines(path, lines, eol):
    with io.open(path, "w", encoding="utf-8", newline="") as fp:
        fp.write(eol.join(lines) + eol)


def do_apply(dry=False):
    facts = snap_facts()
    heads = new_heads(facts)
    if len(heads) < 2:
        print("快照里没有世系头行，放弃")
        return 1
    backup, changed = {}, 0
    for fn in targets():
        path = os.path.join(BASE, fn)
        lines, eol = read_lines(path)
        span = block_span(lines)
        if span is None:
            continue
        idx = head_index(lines, *span)
        if len(idx) != len(heads):
            print(f"  跳过 {fn}: 头行 {len(idx)} ≠ 新头行 {len(heads)}")
            continue
        old = [lines[k] for k in idx]
        if old == heads:
            continue
        backup[fn] = old
        print(f"  {fn}: {len(idx)} 行")
        for n, k in enumerate(idx):
            if old[n] == heads[n]:
                continue
            print(f"    - {lines[k][:110]}")
            print(f"    + {heads[n][:110]}")
            lines[k] = heads[n]
        changed += 1
        if not dry:
            write_lines(path, lines, eol)
    if not dry and backup:
        os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
        old = {}
        if os.path.exists(BACKUP):
            old = json.load(io.open(BACKUP, encoding="utf-8"))
        old.update(backup)
        with io.open(BACKUP, "w", encoding="utf-8") as fp:
            json.dump(old, fp, ensure_ascii=False, indent=1)
    print(f"{'将' if dry else '已'}改 {changed} 篇"
          + ("" if dry else f"；旧头行已存 {BACKUP}"))
    return 0


def do_restore():
    if not os.path.exists(BACKUP):
        print(f"没有备份: {BACKUP}")
        return 1
    old = json.load(io.open(BACKUP, encoding="utf-8"))
    for fn, heads in old.items():
        path = os.path.join(BASE, fn)
        if not os.path.exists(path):
            continue
        lines, eol = read_lines(path)
        span = block_span(lines)
        if span is None:
            continue
        idx = head_index(lines, *span)
        if len(idx) != len(heads):
            print(f"  跳过 {fn}: 头行 {len(idx)} ≠ 备份 {len(heads)}")
            continue
        for k, h in zip(idx, heads):
            lines[k] = h
        write_lines(path, lines, eol)
        print(f"  已还原 {fn}")
    return 0


def do_tree(dry=False):
    facts = snap_facts()
    tree = facts.get("genealogy_tree") or {}
    if not tree.get("nodes"):
        print("快照里没有家谱数据")
        return 1
    path = os.path.join(BASE, "data", "genealogy.json")
    old = {}
    if os.path.exists(path):
        old = json.load(io.open(path, encoding="utf-8"))
    print(f"旧: 传主 {len(old.get('chain') or [])} 人 节点 {len(old.get('nodes') or [])}")
    print(f"新: 传主 {len(tree.get('chain') or [])} 人 节点 {len(tree.get('nodes') or [])} "
          f"红线 {len(tree.get('red_edges') or [])} 段")
    if dry:
        return 0
    if len(old.get("chain") or []) > len(tree.get("chain") or []):
        print("新树比旧树短，放弃（与 _write_genealogy_tree 同一闸门）")
        return 1
    with io.open(path, "w", encoding="utf-8") as fp:
        json.dump(tree, fp, ensure_ascii=False)
    print(f"已写入 {path}")
    return 0


def main():
    a = sys.argv[1:]
    if "--tree" in a:
        return do_tree("--dry" in a)
    if "--restore" in a:
        return do_restore()
    if "--apply" in a or "--dry" in a:
        return do_apply("--dry" in a)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
