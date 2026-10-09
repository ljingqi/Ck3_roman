# -*- coding: utf-8 -*-
"""v119 check: the 封档总评 folder menu — arrow keys, Enter, Q, digits, and the non-console fallback.

No melt, no LLM: the keys are scripted, so the whole interaction is exercised:
    python tools/tests/v119_check_menu.py
"""
import builtins
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import pipeline as P  # noqa: E402

CANDS = [{"folder": "洪氏2", "n": 15, "last_date": "1289.1.1", "player_name": "洪非帝",
          "epilogue": None},
         {"folder": "田所", "n": 15, "last_date": "1007.1.1", "player_name": "业有",
          "epilogue": None},
         {"folder": "斯卡利茨", "n": 6, "last_date": "949.1.1", "player_name": "亚伯拉罕",
          "epilogue": None}]


class KeyStub:
    """msvcrt stand-in: getch returns the scripted console bytes, one press at a time."""

    def __init__(self, keys):
        self.keys = list(keys)

    def getch(self):
        return self.keys.pop(0) if self.keys else b"q"


def run_scripted(keys, expect, label, check):
    sys.modules["msvcrt"] = types.SimpleNamespace(getch=KeyStub(keys).getch)
    os_system, P.os.system = P.os.system, lambda _c: None
    try:
        row = P.epilogue_menu(CANDS)
    finally:
        P.os.system = os_system
        sys.modules.pop("msvcrt", None)
    got = row["folder"] if row else None
    check(got == expect, label, f"得到 {got}, 期望 {expect}")


def main():
    fails = []

    def check(ok, label, extra=""):
        print(f"  {'PASS' if ok else 'FAIL'} {label}" + (f"  {extra}" if extra else ""))
        if not ok:
            fails.append(label)

    run_scripted([b"\xe0", b"P", b"\xe0", b"P", b"\r"], "斯卡利茨", "↓↓ + 回车 选中第三项", check)
    run_scripted([b"\xe0", b"H", b"\r"], "斯卡利茨", "↑ 从首项回首（循环）", check)
    run_scripted([b"j", b"k", b"\r"], "洪氏2", "j/k 等价键位", check)
    run_scripted([b"2", b"\r"], "田所", "数字键直选", check)
    run_scripted([b"q"], None, "q 取消", check)
    run_scripted([b"\x1b"], None, "Esc 取消", check)

    # non-console path: no msvcrt, stdin is not a tty, the number is typed
    sys.modules["msvcrt"] = None
    stdin, builtins.input = sys.stdin, lambda _p="": "3"
    sys.stdin = types.SimpleNamespace(isatty=lambda: False)
    try:
        row = P.epilogue_menu(CANDS)
    finally:
        sys.stdin = stdin
        builtins.input = input
        sys.modules.pop("msvcrt", None)
    check(row and row["folder"] == "斯卡利茨", "无 msvcrt 时退化为数字选择",
          row["folder"] if row else "None")
    print("\n" + ("全部通过" if not fails else f"未过 {len(fails)} 项: " + "、".join(fails)))
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
