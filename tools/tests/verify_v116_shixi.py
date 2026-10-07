# -*- coding: utf-8 -*-
"""v116 断言（世系层）：每篇终传的 `### 世系` 块 = 该传主自己的 v116 快照输出。

v115 起世系块是程序产物（`facts["genealogy"]`），v116 只改其中的称号词。这里把成稿的块
与**每个** v116 快照逐行比对，取最像的那份作为该篇的传主快照，然后要求完全一致：

  * 一致 → 该篇的世系与代码输出同步（词已换成游戏词表）；
  * 不一致 → 打印缺/多的行，便于定位（多半是漏替换或换错了传主）。

用法: python -X utf8 tools/tests/verify_v116_shixi.py
"""
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.join(ROOT, "output", "洪氏2")
DATA = os.path.join(BASE, "data")
FAIL = []
PER_FILE_RE = re.compile(r"^\s*-?\s*家格：")


def block_lines(path):
    with io.open(path, encoding="utf-8", newline="") as fp:
        lines = fp.read().replace("\r\n", "\n").split("\n")
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
    body = [ln for ln in lines[i + 1:j] if ln.strip() and not PER_FILE_RE.match(ln)]
    return body


def snapshots():
    out = {}
    for path in sorted(glob.glob(os.path.join(DATA, "snap_v116_*_final.json"))):
        m = re.search(r"snap_v116_(\d+)_final\.json$", os.path.basename(path))
        if not m:
            continue
        with io.open(path, encoding="utf-8") as fp:
            d = json.load(fp)
        gen = [ln for ln in ((d.get("facts") or {}).get("genealogy") or []) if ln.strip()]
        if gen:
            out[int(m.group(1))] = gen
    return out


def score(got, gen):
    """缺/多行数（越小越像）。"""
    missing = [ln for ln in gen if ln not in got]
    extra = [ln for ln in got if ln not in gen]
    return len(missing) + len(extra), missing, extra


def main():
    snaps = snapshots()
    print("v116 快照 %d 份：%s" % (len(snaps), sorted(snaps)))
    if not snaps:
        print("没有快照 → 先跑 snap.py")
        return 1
    files = [fn for fn in sorted(os.listdir(BASE))
             if fn.endswith(".md") and "终传" in fn]
    for fn in files:
        got = block_lines(os.path.join(BASE, fn))
        if got is None:
            FAIL.append("%s 无 世系 块" % fn)
            print("  FAIL %s 无 世系 块" % fn)
            continue
        best = None
        for pid, gen in snaps.items():
            s, missing, extra = score(got, gen)
            if best is None or s < best[0]:
                best = (s, pid, missing, extra, gen)
        s, pid, missing, extra, gen = best
        tag = "PASS" if s == 0 else "FAIL"
        print("  %s %-42s ↔ 快照 %-10s 行数 %d/%d 缺 %d 多 %d"
              % (tag, fn, pid, len(got), len(gen), len(missing), len(extra)))
        if s:
            FAIL.append("%s ↔ %s" % (fn, pid))
            for ln in missing[:4]:
                print("        缺: %s" % ln[:110])
            for ln in extra[:4]:
                print("        多: %s" % ln[:110])
    print("\n%s（%d 篇未过）" % ("全部通过" if not FAIL else "有未过项", len(FAIL)))
    for x in FAIL:
        print("  - %s" % x)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
