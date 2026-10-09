# -*- coding: utf-8 -*-
"""v119 one-off text surgery: put the missing office word back into the 世系 head line of a 终传.

A landless-adventurer camp leader is rank 0, so `facts.official_title` used to return '' for him and
his 世系 head line read `**外来者洪蒙广**，洪光通之子，…` while the same run's `titles_held` said
「1283年9月11日任洪氏旅行团领袖，无地冒险者营地」. The code fix (`_unlanded_office_text`) makes the
head line read `**洪氏旅行团领袖外来者洪蒙广**，…`.

Existing articles keep the old line, so this tool rewrites it from the facts snapshot rather than from
a hardcoded string: for every character whose snapshot `label` carries no office while `titles_held`
does, the office text is taken from the tenure line and prefixed to the label. The body prose is never
touched (user rule: never regenerate existing prose with the model).

Usage:
    python -X utf8 tools/fix_v119_shixi.py --check      # list the lines that would change
    python -X utf8 tools/fix_v119_shixi.py --apply      # rewrite them (backup first)
    python -X utf8 tools/fix_v119_shixi.py --restore    # restore the backup
    python -X utf8 tools/fix_v119_shixi.py --check 洪氏  # another campaign folder
"""
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

SNAP_NAME = "v118_c1_1283.json"          # facts snapshot of the 1283 era of 洪氏2
BACKUP = os.path.join(ROOT, "logs", "v119_shixi_backup.json")
HEADER_ID_RE = re.compile(r"人物ID:\s*(\d+)")
TENURE_RE = re.compile(r"^(\d+年\d+月\d+日)任(.+?)，")
MODE = next((a for a in sys.argv[1:] if a.startswith("--")), "--check")
FOLDER = next((a for a in sys.argv[1:] if not a.startswith("--")), "洪氏2")
BASE = os.path.join(ROOT, "output", FOLDER)


def head_office():
    """{cid: office text} for the characters whose snapshot label lacks the office they held."""
    path = os.path.join(BASE, "data", SNAP_NAME)
    if not os.path.isfile(path):
        cands = sorted(glob.glob(os.path.join(BASE, "data", "v1*_c1_*.json")))
        if not cands:
            raise SystemExit(f"{FOLDER}: 找不到事实快照（{SNAP_NAME}）")
        path = cands[-1]
    with io.open(path, encoding="utf-8") as fp:
        facts = json.load(fp).get("facts") or {}
    out = {}
    for cid, rec in (facts.get("characters") or {}).items():
        label = rec.get("label") or ""
        held = rec.get("titles_held") or ""
        m = TENURE_RE.match(held.split("；")[0].strip()) if held else None
        office = m.group(2) if m else ""
        if office and label and not label.startswith(office):
            out[int(cid)] = {"label": label, "office": office, "held": held, "snap": path}
    return out


def targets():
    """[(path, line index, old line, new line)] for the head lines to rewrite."""
    cases = head_office()
    rows = []
    for path in sorted(glob.glob(os.path.join(BASE, "*_终传_*.md"))):
        with io.open(path, encoding="utf-8", newline="") as fp:
            raw = fp.read()
        lines = raw.replace("\r\n", "\n").split("\n")
        m = HEADER_ID_RE.search(lines[0] if lines else "")
        if not m:
            continue
        case = cases.get(int(m.group(1)))
        if not case:
            continue
        want = "**" + case["office"] + case["label"] + "**"
        for i, ln in enumerate(lines):
            if ln.startswith("**" + case["label"] + "**"):
                rows.append((path, i, ln, ln.replace("**" + case["label"] + "**", want, 1), case))
                break
    return rows


def backup_paths():
    if os.path.isfile(BACKUP):
        with io.open(BACKUP, encoding="utf-8") as fp:
            return {r["file"]: r for r in json.load(fp)}
    return {}


def main():
    rows = targets()
    if MODE == "--restore":
        saved = backup_paths()
        if not saved:
            print("没有备份可回滚:", BACKUP)
            return 0
        for rel, rec in saved.items():
            path = os.path.join(ROOT, rel)
            with io.open(path, encoding="utf-8", newline="") as fp:
                raw = fp.read()
            nl = "\r\n" if "\r\n" in raw else "\n"
            lines = raw.replace("\r\n", "\n").split("\n")
            lines[rec["line"]] = rec["before"]
            with io.open(path, "w", encoding="utf-8", newline="") as fp:
                fp.write(nl.join(lines))
            print("已回滚:", os.path.basename(path))
        os.remove(BACKUP)
        return 0
    if not rows:
        print("没有需要改动的世系头行（已是新代码的输出）")
        return 0
    print("将改动的世系头行 %d 处：\n" % len(rows))
    for path, i, old, new, case in rows:
        print("  %s:%d" % (os.path.basename(path), i + 1))
        print("    - %s" % old[:100])
        print("    + %s" % new[:100])
        print("    持衔依据(%s): %s" % (os.path.basename(case["snap"]), case["held"][:60]))
    if MODE != "--apply":
        print("\n（--check 模式，未写盘；加 --apply 落盘）")
        return 0
    records = []
    for path, i, old, new, _case in rows:
        with io.open(path, encoding="utf-8", newline="") as fp:
            raw = fp.read()
        nl = "\r\n" if "\r\n" in raw else "\n"
        lines = raw.replace("\r\n", "\n").split("\n")
        if lines[i] != old:
            print("跳过（行已变）:", os.path.basename(path))
            continue
        lines[i] = new
        with io.open(path, "w", encoding="utf-8", newline="") as fp:
            fp.write(nl.join(lines))
        records.append({"file": os.path.relpath(path, ROOT), "line": i, "before": old, "after": new})
        print("已改写:", os.path.basename(path))
    if records:
        with io.open(BACKUP, "w", encoding="utf-8") as fp:
            json.dump(records, fp, ensure_ascii=False, indent=1)
        print("\n备份:", BACKUP)
        print("记得重建阅读页: python -X utf8 -c \"import htmlview,llm;print(htmlview.rebuild_folder(llm.load_config()['output_dir'], %r))\"" % FOLDER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
