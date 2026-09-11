# -*- coding: utf-8 -*-
"""读 Mod 的 8 处 add_hook（ganlewodelaopo）所在事件与所在 scope，判定「谁持有」。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_mod_hook_sites.py
"""
import io
import re

SRC = (r"F:\SteamLibrary\steamapps\workshop\content\1158310\2978257885"
       r"\events\longju_shijian_event.txt")


def main():
    txt = io.open(SRC, encoding="utf-8", errors="replace").read()
    lines = txt.splitlines()
    # 事件起始行
    ev_at = {}
    for i, ln in enumerate(lines):
        m = re.match(r"^(longju_shijian\.\d+)\s*=\s*\{", ln.strip())
        if m:
            ev_at[i] = m.group(1)
    evs = sorted(ev_at)
    print(f"事件 {len(evs)} 个")
    for i, ln in enumerate(lines):
        if "ganlewodelaopo_hook" not in ln or "add_hook" not in ln:
            continue
        ev = None
        for s in evs:
            if s < i:
                ev = ev_at[s]
            else:
                break
        # 向上找最近的 scope 行（root = { / scope:npc_2 = { …）
        scope = "?"
        for j in range(i, max(0, i - 40), -1):
            m = re.search(r"(root|scope:npc_1|scope:npc_2)\s*=\s*\{", lines[j])
            if m:
                scope = m.group(1)
                break
        print(f"\n=== 行 {i+1}  事件 {ev}  所在 scope = {scope}")
        print("    " + lines[i].strip())
        for k in range(max(0, i - 12), min(len(lines), i + 8)):
            print("     | " + lines[k].rstrip()[:120])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
