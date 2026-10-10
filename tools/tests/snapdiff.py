# -*- coding: utf-8 -*-
"""快照传输面对照：HEAD 基线 vs 本轮（事实面：共享前缀 + 各篇 blocks）。

用法：
    & tools\\py.ps1 tools\\tests\\snapdiff.py <旧快照> <新快照> [--facts-only] [--full]
"""
import difflib
import json
import sys


def _txt(v):
    return "\n".join(str(x) for x in (v.values() if isinstance(v, dict) else [v]))


def _fact_lines(path):
    s = json.load(open(path, encoding="utf-8"))
    out = (s.get("shared") or "").splitlines()
    for v in (s.get("blocks") or {}).values():
        out.extend(_txt(v).splitlines())
    return out


def _msg_lines(path):
    s = json.load(open(path, encoding="utf-8"))
    out = []
    for m in (s.get("messages") or {}).values():
        out.extend(str(m.get("system") or "").splitlines())
        out.extend(str(m.get("user") or "").splitlines())
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 2
    old, new = args[0], args[1]
    old_l, new_l = _fact_lines(old), _fact_lines(new)
    diff = list(difflib.unified_diff(old_l, new_l, "HEAD", "v121", lineterm="", n=0))
    changed = [x for x in diff if x[:1] in "+-" and x[:3] not in ("+++", "---")]
    print(f"事实面: 旧 {len(old_l)} 行 / 新 {len(new_l)} 行 / 变动 {len(changed)} 行")
    seen = set()
    for ln in changed:
        if ln in seen:
            continue
        seen.add(ln)
        print("  " + ln[:170])
    if "--full" in sys.argv:
        om, nm = _msg_lines(old), _msg_lines(new)
        dm = [x for x in difflib.unified_diff(om, nm, lineterm="", n=0)
              if x[:1] in "+-" and x[:3] not in ("+++", "---")]
        print(f"\n提示词面: 旧 {len(om)} 行 / 新 {len(nm)} 行 / 变动 {len(dm)} 行")
        for ln in list(dict.fromkeys(dm))[:60]:
            print("  " + ln[:170])
    return 0


if __name__ == "__main__":
    sys.exit(main())
