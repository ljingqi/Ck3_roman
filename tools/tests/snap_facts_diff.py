# -*- coding: utf-8 -*-
"""快照事实面对照 (替代缺失的 snapdiff.py): 比较两份 snap_*.json 的 facts / shared / blocks。

用法:
    & tools\\py.ps1 tools\\tests\\snap_facts_diff.py <旧快照> <新快照> [--facts-only] [--top N]

退出码: 0 = 无差异, 1 = 有差异。
"""
import json
import os
import sys

MAX_SHOW = 40


def walk_diff(a, b, path="", out=None):
    """递归收集差异 (path, 旧值, 新值)。"""
    if out is None:
        out = []
    if len(out) >= MAX_SHOW * 4:
        return out
    if type(a) is not type(b):
        out.append((path, a, b))
        return out
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append((path + "/" + str(k), "<缺失>", b[k]))
            elif k not in b:
                out.append((path + "/" + str(k), a[k], "<缺失>"))
            else:
                walk_diff(a[k], b[k], path + "/" + str(k), out)
    elif isinstance(a, list):
        if a != b:
            out.append((path, a, b))
    elif a != b:
        out.append((path, a, b))
    return out


def brief(v, n=160):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    s = s.replace("\n", "⏎")
    return s if len(s) <= n else s[:n] + "…"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 2
    old_p, new_p = args[0], args[1]
    top_n = 10
    for f in flags:
        if f.startswith("--top"):
            top_n = int(f.split("=", 1)[1]) if "=" in f else top_n
    keys = ["facts"] if "--facts-only" in flags else ["facts", "shared", "blocks", "messages"]
    old = json.load(open(old_p, encoding="utf-8"))
    new = json.load(open(new_p, encoding="utf-8"))
    print("旧: %s" % os.path.basename(old_p))
    print("新: %s" % os.path.basename(new_p))
    print("meta 旧: %s" % brief(old.get("meta"), 200))
    print("meta 新: %s" % brief(new.get("meta"), 200))
    total = 0
    only_paths = "--paths" in flags
    if only_paths:
        # 归纳模式: 把形如 characters/<id>/xxx 的路径归并成 characters/*/xxx 并计数
        from collections import Counter
        cnt = Counter()
        for key in keys:
            for path, _a, _b in walk_diff(old.get(key), new.get(key), key):
                parts = path.split("/")
                norm = "/".join("*" if p.isdigit() else p for p in parts[:-1]) \
                    + "/" + parts[-1]
                cnt[norm] += 1
        total = sum(cnt.values())
        print("\n=== 差异路径归纳 (%d 类 / %d 处) ===" % (len(cnt), total))
        for p, c in cnt.most_common():
            print("  %5d  %s" % (c, p))
        return 1 if total else 0
    for key in keys:
        if key not in old and key not in new:
            continue
        d = walk_diff(old.get(key), new.get(key), key)
        total += len(d)
        print("\n=== %s: %d 处差异" % (key, len(d)))
        for path, a, b in d[:top_n]:
            print("  %s\n     旧: %s\n     新: %s" % (path, brief(a), brief(b)))
        if len(d) > top_n:
            print("  … 另有 %d 处 (用 --top=N 调整)" % (len(d) - top_n))
    print("\n合计 %d 处差异" % total)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
