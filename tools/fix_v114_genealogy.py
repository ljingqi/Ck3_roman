# -*- coding: utf-8 -*-
"""v114 一次性文本手术：把成稿附录 `### 世系` 的程序产物重同步到当前代码的输出。

正文一字不动（用户定规：绝不用模型重生成既有正文），只改程序产物——附录世系整块都是
`facts._genealogy_parts` 的输出：头行是 `person_label(cid, date, "full")` ＋（已封圣者）
「，〈年〉年封圣」，亲属行里的称谓（例：枢机带驻地「圣依搦斯枢机洪宓」）也来自同一处。
本工具拿快照 `snap_v114_207044_final.json` 的 `facts["genealogy"]` 作准，逐块比对，
**只替换真的不一样的行**（`difflib` 对齐；出现行数增减则整篇跳过并报数），
逐篇保留只在那一篇成立的行（「家格：」那一行随篇而变，快照里没有）。

用法：
    python -X utf8 tools/fix_v114_genealogy.py --dry
    python -X utf8 tools/fix_v114_genealogy.py --apply
    python -X utf8 tools/fix_v114_genealogy.py --restore
    python -X utf8 tools/fix_v114_genealogy.py --tree        # 由快照写 data/genealogy.json

--tree 只写阅读页用的家谱数据（`biography._write_genealogy_tree` 的同一份内容），
不碰任何 .md。
"""
import difflib
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
PER_FILE_RE = re.compile(r"家格：")


def snap_facts():
    with io.open(SNAP, encoding="utf-8") as fp:
        return json.load(fp)["facts"]


def printed_block(facts):
    """The snapshot's own 世系 lines, prefixed like the article prints them."""
    return ["- " + ln for ln in (facts.get("genealogy") or [])]


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


def targets():
    return [fn for fn in sorted(os.listdir(BASE)) if fn.endswith(".md")]


def read_lines(path):
    """(lines, line ending) — the ending is preserved so the diff stays on the changed lines."""
    with io.open(path, encoding="utf-8", newline="") as fp:
        raw = fp.read()
    eol = "\r\n" if "\r\n" in raw else "\n"
    return raw.splitlines(), eol


def write_lines(path, lines, eol):
    with io.open(path, "w", encoding="utf-8", newline="") as fp:
        fp.write(eol.join(lines) + eol)


def load_backup():
    if os.path.exists(BACKUP):
        try:
            return json.load(io.open(BACKUP, encoding="utf-8"))
        except Exception:                                         # noqa: BLE001
            return {}
    return {}


def save_backup(data):
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with io.open(BACKUP, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=1)


def resync(old, new):
    """(new block, [(index, before, after)]) reusing per-file lines of `old`; (None, []) on drift.

    Only wording is exchanged. A structural change — a line count that cannot be explained by the
    per-file lines (`家格：`) or by blank lines — means the article's block and the snapshot's block
    have drifted apart, and reporting that is better than guessing."""
    out, edits = [], []
    sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        olds, news = old[i1:i2], new[j1:j2]
        if tag == "equal":
            out.extend(olds)
            continue
        if tag == "delete":
            if all(PER_FILE_RE.search(ln) or not ln.strip() for ln in olds):
                out.extend(olds)
                continue
            return None, []
        if tag == "insert":
            out.extend(news)
            continue
        # replace: per-file lines keep their own text, everything else takes the snapshot's wording
        rest = [ln for ln in olds if not PER_FILE_RE.search(ln)]
        if len(rest) != len(news):
            return None, []
        merged, k = [], 0
        for ln in olds:
            if PER_FILE_RE.search(ln):
                merged.append(ln)
            else:
                merged.append(news[k])
                k += 1
        if merged != olds:
            edits.append((i1, olds, merged))
        out.extend(merged)
    return out, edits


def do_apply(dry=False):
    new = printed_block(snap_facts())
    if len(new) < 2:
        print("快照里没有世系行，放弃")
        return 1
    backup = load_backup()
    blocks = backup.setdefault("block", {}) if not dry else {}
    changed, skipped = 0, []
    for fn in targets():
        path = os.path.join(BASE, fn)
        lines, eol = read_lines(path)
        span = block_span(lines)
        if span is None:
            continue
        s, e = span
        old = lines[s:e]
        out, edits = resync(old, new)
        if out is None:
            skipped.append(fn)
            print(f"  跳过 {fn}: 世系块与快照行数不符（{len(old)} vs {len(new)}）")
            continue
        if out == old:
            continue
        changed += 1
        print(f"  {fn}: {sum(1 for _i, a, b in edits for x, y in zip(a, b) if x != y)} 行")
        for _i, a, b in edits:
            for n in range(max(len(a), len(b))):
                x = a[n] if n < len(a) else ""
                y = b[n] if n < len(b) else ""
                if x == y:
                    continue
                print(f"    - {x[:110]}")
                print(f"    + {y[:110]}")
        if dry:
            continue
        blocks[fn] = old
        lines[s:e] = out
        write_lines(path, lines, eol)
    if not dry and blocks:
        save_backup(backup)
    print(f"{'将' if dry else '已'}改 {changed} 篇"
          + (f"，跳过 {len(skipped)} 篇" if skipped else "")
          + ("" if dry else f"；旧世系块已存 {BACKUP}"))
    return 0


def do_restore():
    backup = load_backup()
    blocks = backup.get("block") or {}
    heads = backup.get("head") or ({} if not blocks else {})
    if not blocks and not heads and isinstance(backup, dict):
        heads = {k: v for k, v in backup.items() if isinstance(v, list)}   # legacy flat form
    if not blocks and not heads:
        print(f"没有备份: {BACKUP}")
        return 1
    for fn in sorted(set(blocks) | set(heads)):
        path = os.path.join(BASE, fn)
        if not os.path.exists(path):
            continue
        lines, eol = read_lines(path)
        span = block_span(lines)
        if span is None:
            continue
        s, e = span
        if fn in blocks:
            if len(blocks[fn]) != e - s:
                print(f"  跳过 {fn}: 现块 {e - s} 行 ≠ 备份 {len(blocks[fn])} 行")
                continue
            lines[s:e] = blocks[fn]
        if fn in heads:
            idx = [k for k in range(s, e) if HEAD_RE.match(lines[k])]
            if len(idx) != len(heads[fn]):
                print(f"  跳过 {fn}: 头行 {len(idx)} ≠ 备份 {len(heads[fn])}")
                continue
            for k, h in zip(idx, heads[fn]):
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
