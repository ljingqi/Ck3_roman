# -*- coding: utf-8 -*-
"""v115 一次性文本手术：把成稿附录 `### 世系` 整块换成新代码的输出。

正文一字不动（用户定规：绝不用模型重生成既有正文），只改程序产物。新块 = 快照
`facts["genealogy"]`（v115 起每行自带 markdown：凡例／世系图／世次／传主是段落，亲属行是列表）
＋该篇自己的「家格：」行（本轮只 `洪易卜拉欣(1059)_终传` 与 `缯·洪堡(954)_终传` 两篇有；旧块里
写作 `- 家格：…`，新版式作段落）。

行数会变（每人省下一行世次、段间补空行），因此**整块替换**而非 v114 的逐行对齐。
每篇替换前都与 v114 快照逐行核对：若该篇旧块与快照不符（历史手改），跳过并报数，不猜。

用法：
    python -X utf8 tools/fix_v115_shixi.py --dry
    python -X utf8 tools/fix_v115_shixi.py --apply
    python -X utf8 tools/fix_v115_shixi.py --restore
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.join(ROOT, "output", "洪氏2")
SNAP = os.path.join(BASE, "data", "snap_v115_207044_final.json")
OLD_SNAP = os.path.join(BASE, "data", "snap_v114_207044_final.json")
BACKUP = os.path.join(ROOT, "logs", "v115_shixi_backup.json")
PER_FILE_RE = re.compile(r"^\s*-?\s*家格：")


def load_facts(path):
    with io.open(path, encoding="utf-8") as fp:
        return json.load(fp)["facts"]


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


def per_file_lines(old_block):
    """Per-article lines kept verbatim: the 「家格：」 row, rewritten as its own paragraph.

    A listed line in the old block carried the same `- ` bullet as everything else; the new layout
    prints prose as prose, so the row loses the marker and keeps its text."""
    out = []
    for ln in old_block:
        if PER_FILE_RE.match(ln):
            out.append(re.sub(r"^\s*-\s*", "", ln).rstrip())
    return out


def old_matches(old_block, old_facts):
    """True when the article's block is the v114 program output (ignoring per-file and blank rows)."""
    want = ["- " + ln for ln in (old_facts.get("genealogy") or [])]
    got = [ln for ln in old_block if ln.strip() and not PER_FILE_RE.match(ln)]
    want = [ln for ln in want if ln.strip()]
    return got == want


def do_apply(dry=False):
    facts = load_facts(SNAP)
    old_facts = load_facts(OLD_SNAP) if os.path.exists(OLD_SNAP) else {}
    gen = facts.get("genealogy") or []
    if len(gen) < 2:
        print(f"快照里没有世系行：{SNAP}")
        return 1
    if os.path.exists(OLD_SNAP):
        old_want = ["- " + ln for ln in (old_facts.get("genealogy") or [])]
        print(f"对照：旧快照 {len(old_want)} 行 / 新快照 {len(gen)} 行")
    backup = load_backup()
    blocks = backup.setdefault("block", {}) if not dry else {}
    changed, skipped, same = 0, [], 0
    for fn in targets():
        path = os.path.join(BASE, fn)
        lines, eol = read_lines(path)
        span = block_span(lines)
        if span is None:
            continue
        s, e = span
        old = lines[s:e]
        if old_facts and not old_matches(old, old_facts):
            skipped.append(fn)
            print(f"  跳过 {fn}: 世系块与 v114 快照不符（历史手改？）")
            continue
        new = list(gen) + [x for x in per_file_lines(old)] + [""]
        if new == old:
            same += 1
            continue
        changed += 1
        print(f"  {fn}: {len(old)} 行 → {len(new)} 行"
              + (f"（保留 {len(per_file_lines(old))} 行本篇独有）"
                 if per_file_lines(old) else ""))
        if dry:
            for ln in new[:14]:
                print(f"    | {ln[:100]}")
            print("    | …")
            continue
        blocks[fn] = old
        lines[s:e] = new
        write_lines(path, lines, eol)
    if not dry and blocks:
        save_backup(backup)
    print(f"{'将' if dry else '已'}改 {changed} 篇"
          + (f"，已是新版式 {same} 篇" if same else "")
          + (f"，跳过 {len(skipped)} 篇" if skipped else "")
          + ("" if dry else f"；旧块已存 {BACKUP}"))
    return 0


def do_restore():
    backup = load_backup()
    blocks = backup.get("block") or {}
    if not blocks:
        print(f"没有备份: {BACKUP}")
        return 1
    n = 0
    for fn, old in sorted(blocks.items()):
        path = os.path.join(BASE, fn)
        if not os.path.exists(path):
            continue
        lines, eol = read_lines(path)
        span = block_span(lines)
        if span is None:
            continue
        s, e = span
        lines[s:e] = old
        write_lines(path, lines, eol)
        n += 1
        print(f"  已还原 {fn}")
    print(f"还原 {n} 篇")
    return 0


def main():
    a = sys.argv[1:]
    if "--restore" in a:
        return do_restore()
    if "--apply" in a or "--dry" in a:
        return do_apply("--dry" in a)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
