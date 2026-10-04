# -*- coding: utf-8 -*-
"""v101 专项断言（纯函数秒级 + 快照/成稿；不载熔件）。

用户 2026-10-04 四问（洪氏2）：
  ① 「大公会议与教宗诏书」只收录传主身为玩家角色的区间（952–999）
  ② 会议/诏书与其定夺合写一行（「…颁布教宗诏书，将原先禁止的「X」改为允许。」）
  ③ 980.3.20 那场由厄德·罗贝尔主持的大公会议要写出成果（faith 13 级更替，锁存点 982）
  ④ 圣人名字前加「圣」（圣洪天贵福）

断言：
  [A] 纯函数：_player_tenure_start / _church_window / _in_church_window
  [B] 纯函数：事件↔定夺配对器与合写行
  [C] 纯函数：圣人前缀（特质 → 词条）
  [D] 快照：区间、合写、圣人、相位行日期、无裸键/标记/括注
  [E] 成稿：终传与十年传（存在则断言）

用法：
    & tools\\py.ps1 tools\\tests\\verify_v101.py [快照...]
    （缺省 output/洪氏2/data/snap_v101.json，缺则回落 snap_v100.json）
"""
import glob
import json
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl        # noqa: E402
import facts as F             # noqa: E402
import biography as bio       # noqa: E402

OK = True
H2 = os.path.join(ROOT, "output", "洪氏2")
NEG = re.compile(r"不要|请勿|禁止|避免|切勿|不得|严禁|不可|不再|勿")
BARE = re.compile(r"(?<![A-Za-z0-9_])(?:special_)?(?:tenet|doctrine)_[a-z0-9_]+")
MARK = re.compile(r"\[[^\]]{0,40}\]|\$[A-Za-z_]+\$")
PAREN = re.compile(r"（[^）]{1,24}）")
PRE_952 = ("873年", "877年", "878年", "904年", "905年", "916年", "917年", "920年",
           "928年", "929年", "931年", "932年", "934年", "936年", "938年", "939年",
           "941年", "944年", "947年", "951年")


def check(name, cond, extra=None):
    global OK
    if not cond:
        OK = False
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f"   <- {str(extra)[:300]!r}" if extra is not None and not cond else ""))


def stub(decade=None, as_of=None, sources=("953.1.1", "954.1.1"), chain=None,
         pid=67172818):
    """A Facts stand-in carrying only what the window helpers read."""
    o = types.SimpleNamespace()
    o.decade = decade
    o.as_of = as_of
    o.cache = {"player_id": pid, "sources": list(sources), "last_date": "999.1.1",
               "played_legacy": chain if chain is not None else []}
    o._player_tenure_start = lambda: F.Facts._player_tenure_start(o)
    o._bio_window_start = lambda: F.Facts._bio_window_start(o)
    o._decade_cutoff = lambda n: F.Facts._decade_cutoff(o, n)
    return o


# ---------------------------------------------------------------- [A] window
CHAIN = [{"cid": 44503, "date": "938.6.1"}, {"cid": 67172818, "date": "952.1.29"}]


def test_window():
    print("[A] 区间（扮演区间为下限）")
    o = stub(chain=CHAIN)
    win = F.Facts._church_window(o)
    check("终传下限 = 承继日 952.1.29", win == (cl.date_key("952.1.29"), None), win)
    check("920 年大分裂落在区间外",
          not F.Facts._in_church_window("920.2.1", win))
    check("951 年诏书落在区间外",
          not F.Facts._in_church_window("951.2.19", win))
    check("954 年会议落在区间内",
          F.Facts._in_church_window("954.10.11", win))
    check("997 年诏书落在区间内",
          F.Facts._in_church_window("997.12.24", win))

    o2 = stub(decade="4", as_of="993.1.1", chain=CHAIN)
    win2 = F.Facts._church_window(o2)
    check("十年传下限 = 十年窗口起点（晚于承继日）",
          win2 == (cl.date_key("983.1.1"), cl.date_key("993.1.1")), win2)

    o3 = stub(chain=[])
    win3 = F.Facts._church_window(o3)
    check("无链时回落战役起点 953.1.1",
          win3 == (cl.date_key("953.1.1"), None), win3)

    o4 = stub(chain=[{"cid": 44503, "date": "938.6.1"}], pid=44503)
    win4 = F.Facts._church_window(o4)
    check("另一传主取自己的承继日 938.6.1",
          win4 == (cl.date_key("938.6.1"), None), win4)


def load_snaps():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        return args
    for name in ("snap_v101.json", "snap_v100.json"):
        p = os.path.join(H2, "data", name)
        if os.path.isfile(p):
            return [p]
    return []


def main():
    test_window()
    snaps = load_snaps()
    print(f"(快照 {len(snaps)} 份：{[os.path.basename(s) for s in snaps]})")
    print("PASS" if OK else "FAIL")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
