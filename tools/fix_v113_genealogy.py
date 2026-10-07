# -*- coding: utf-8 -*-
"""v113 一次性迁移（两个方向）：

  默认（正向）  终传附录的「### 世系」→「### 家谱」
  --restore     终传附录的「### 家谱」→「### 世系」（用户 2026-10-07 改主意：世系放回原位，
                家谱图只留在阅读页的「家谱」按钮后面）

改动只落在程序生成的附录段（凡例/世系/家格行），LLM 正文一字不动。家谱图由阅读页从
`data/genealogy.json` 绘出（`biography._write_genealogy_tree` 在实跑路径写这份数据）。

用法：
    & tools\\py.ps1 tools\\fix_v113_genealogy.py                 # 试跑，只列将改之处
    & tools\\py.ps1 tools\\fix_v113_genealogy.py --apply         # 落盘
    & tools\\py.ps1 tools\\fix_v113_genealogy.py --restore --apply
    ｜ --snapshot=<文件>  从既有 facts 快照取家谱数据/世系文本（默认自动找该族最新的 *_final 快照）
    ｜ --tree=<文件>      指定家谱数据文件
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402

FOLDER = "洪氏2"
HEAD_RE = re.compile(r"^### 世系\s*$", re.M)
TREE_HEAD_RE = re.compile(r"^### 家谱\s*$", re.M)
NEXT_RE = re.compile(r"^#{2,3} ", re.M)


def load_snapshot(data_dir):
    """(tree, facts, filename) of the newest snapshot that carries a genealogy tree."""
    cands = []
    for fn in sorted(os.listdir(data_dir)):
        if not (fn.startswith("snap_") and fn.endswith(".json")):
            continue
        try:
            with io.open(os.path.join(data_dir, fn), encoding="utf-8") as f:
                snap = json.load(f)
        except Exception:
            continue
        facts = snap.get("facts") or {}
        t = facts.get("genealogy_tree") or {}
        if t.get("nodes"):
            cands.append((len(t.get("chain") or []), fn, t, facts))
    if not cands:
        return {}, {}, ""
    cands.sort(key=lambda x: x[0])
    _n, fn, t, facts = cands[-1]
    return t, facts, fn


def tree_from_snapshot(data_dir, out_path):
    """Write the family tree sidecar from the newest facts snapshot that carries one.

    A snapshot holds the facts the article was built from, so its `genealogy_tree` is the same dict
    `biography` would write; this keeps the migration free of another melt load."""
    if os.path.exists(out_path):
        return out_path
    t, _facts, fn = load_snapshot(data_dir)
    if not t:
        return ""
    with io.open(out_path, "w", encoding="utf-8") as f:
        json.dump(t, f, ensure_ascii=False)
    print(f"  家谱数据取自快照 {fn} → {os.path.basename(out_path)}（{len(t['nodes'])} 人）")
    return out_path


def summary_for(tree, k):
    """The caption a piece with a chain `k` long would print (mirrors `_appendix_text`)."""
    chain = (tree.get("chain") or [])[:k]
    gens = [c.get("gen") or 1 for c in chain] or [1]
    n = len([x for x in tree.get("nodes") or [] if (x.get("from_k") or 1) <= k])
    span = F._gen_word(1) if gens[-1] <= 1 else f"{F._gen_word(1)}至{F._gen_word(gens[-1])}"
    return (f"本谱{span}，凡{F._tree_count_zh(len(chain))}位传主、"
            f"{F._tree_count_zh(n)}人；家谱图见阅读页。")


def rewrite(text, tree, k):
    """(new text, changed?) — the appendix's 世系 section becomes the 家谱 caption."""
    m = HEAD_RE.search(text)
    if not m:
        return text, False
    nxt = NEXT_RE.search(text, m.end())
    end = nxt.start() if nxt else len(text)
    block = text[m.end():end]
    # keep the house-history rows: 家格 is a record of the clan, not part of the 世系 figure
    keep = [ln for ln in block.splitlines() if ln.startswith("- 家格")]
    head = ["### 家谱",
            "- " + F._GENEALOGY_FANLI,
            "- " + summary_for(tree, k)]
    out = "\n".join(head + keep) + "\n\n"
    return text[:m.start()] + out + text[end:], True


def restore(text, gen):
    """(new text, changed?) — the 家谱 caption goes back to the printed 世系 the article had before.

    The lines are the ones `biography._appendix_text` writes again (v113 user 2026-10-07): the 谱例,
    the chain figure, every household block, then the house history. The house-history rows are the
    ones already in this article (`家格`), not the snapshot's: a snapshot only carries its own
    piece's protagonist, while each article keeps its own clan record."""
    m = TREE_HEAD_RE.search(text)
    if not m:
        return text, False
    nxt = NEXT_RE.search(text, m.end())
    end = nxt.start() if nxt else len(text)
    keep = [ln for ln in text[m.end():end].splitlines() if ln.startswith("- 家格")]
    out = ["### 世系"] + ["- " + g for g in gen] + keep
    return text[:m.start()] + "\n".join(out) + "\n\n" + text[end:], True


def main():
    apply = "--apply" in sys.argv
    back = "--restore" in sys.argv
    data_dir = os.path.join(ROOT, "output", FOLDER, "data")
    tree_path = os.path.join(data_dir, "genealogy.json")
    for a in sys.argv[1:]:
        if a.startswith("--tree="):
            tree_path = a.split("=", 1)[1]
    if not os.path.exists(tree_path):
        tree_path = tree_from_snapshot(data_dir, tree_path)
    if not tree_path or not os.path.exists(tree_path):
        print("找不到家谱数据（先跑 tools/tests/snap.py 生成带 genealogy_tree 的快照）")
        return 2
    with io.open(tree_path, encoding="utf-8") as f:
        tree = json.load(f)
    pieces = {int(k): int(v) for k, v in (tree.get("pieces") or {}).items()}
    gen = None
    if back:
        _t, facts, fn = load_snapshot(data_dir)
        gen = list(facts.get("genealogy") or [])
        if not gen:
            print("快照里没有 genealogy 文本，无法还原世系")
            return 2
        print(f"  世系文本取自快照 {fn}（{len(gen)} 行）")
    base = os.path.join(ROOT, "output", FOLDER)
    changed = 0
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(".md") or "终传" not in fn:
            continue
        path = os.path.join(base, fn)
        with io.open(path, encoding="utf-8") as f:
            text = f.read()
        pid = None
        m = re.search(r"人物ID:\s*(\d+)", text)
        if m:
            pid = int(m.group(1))
        k = pieces.get(pid)
        if not k:
            print(f"  {fn}: 未在传主链上（人物ID {pid}），跳过")
            continue
        if back:
            new, ok = restore(text, gen)
            what = "家谱段 → 世系段"
        else:
            new, ok = rewrite(text, tree, k)
            what = f"世系段 → 家谱段（第 {k} 位传主，题记「{summary_for(tree, k)}」）"
        if not ok:
            print(f"  {fn}: 无可改的段，跳过")
            continue
        if new == text:
            print(f"  {fn}: 已是目标形态")
            continue
        changed += 1
        print(f"  {fn}: {what}")
        if apply:
            with io.open(path, "w", encoding="utf-8") as f:
                f.write(new)
    print(f"{'已落盘' if apply else '试跑（加 --apply 落盘）'}: {changed} 篇待改")
    return 0


if __name__ == "__main__":
    sys.exit(main())
