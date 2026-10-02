# -*- coding: utf-8 -*-
"""v91 回归 (秒级; 不载熔件): 改信/改礼的**精确**变更点 + 信仰的完整称法。

用法: & tools\\py.ps1 tools\\tests\\verify_v91.py [快照...]
      | 缺省取 output/洪氏2/data/snap_v91_gf_d1.json

对应 docs/方案_v91_洪氏2信仰沿革.md (用户 2026-10-02 报告):
  1 主角的宗教改了好几次, 《本纪》里却没写 —— 根因: 信仰/礼仪沿革旧稿只走
    缓存逐档差分, 而**每份缓存只覆盖该传主在位的那几档** (玩家 44503 的缓存
    sources = 905.1.1–922.1.1), 天贵福 885 改礼 / 894 改信 / 895 复归都落在
    窗口之外 ⇒ `faith_history_lines` 恒空。现并入游戏自己的
    `converted_faith_memory` / `converted_rite_memory` (缓存 memories 带 vars,
    精确到日), 三源合一。
  2 当前信仰一律写「宗教 + 礼仪」(如「迦克墩基督教拜上帝会」)。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

_DEFAULT = (os.path.join(ROOT, "output", "洪氏2", "data",
                         "snap_v91_gf_d1.json"),)
_OK = True
# 同年退化的病句 (v91 修): 「894年至894年」
_SAME_YEAR = re.compile(r"(\d{3,4})年至\1年")


def check(name, cond, detail=""):
    global _OK
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (("  — " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _OK = False


# ---------------------------------------------------------------------------
# 合成件: 只造命名要用到的两段 (faiths.database / rites.database)
# ---------------------------------------------------------------------------
MELT = {
    "faiths": {"database": {
        "12": {"name": "迦克墩基督教"},
        "31": {"name": "儒家"},
        "9": {"name": "大乘佛教"},
    }},
    "rites": {"database": {
        "0": {"faith": 12, "data": {"name": "罗马礼"}},
        "5": {"faith": 12, "data": {"name": "加洛林礼"}},
        "6": {"faith": 12, "data": {"name": "希腊礼"}},
        "32": {"faith": 31, "data": {"name": "经学"}},
        "67": {"faith": 9, "data": {"name": "华严宗"}},
        "154": {"faith": 12, "data": {"name": "拜上帝会"}},
    }},
}


def _facts(recs, as_of="915.1.1"):
    f = F.Facts.__new__(F.Facts)      # 不跑 __init__: 只测纯函数分支
    f.cache = {"characters": recs}
    f.melt = MELT
    f.table = {}
    f.as_of = as_of
    f._chars = {}
    return f


def _mem(t, d, **vars_):
    return {"type": t, "creation_date": d,
            "vars": [{"flag": k, "identity": v} for k, v in vars_.items()]}


# 天贵福 (44503) 的三点: 885.6.4 改礼 / 894.7.21 改信 / 895.5.27 复归
GF = {
    "faith": 12, "rite": 154,
    "faith_history": [{"from": "905.1.1", "faith": 12}],
    "rite_history": [{"from": "905.1.1", "rite": 154}],
    "memories": [
        _mem("converted_rite_memory", "885.6.4",
             childhood_memory=1, new_rite=154, old_rite=None),
        _mem("converted_faith_memory", "894.7.21",
             new_rite=32, new_faith=31, old_faith=12),
        _mem("converted_faith_memory", "895.5.27",
             new_rite=154, new_faith=12, old_faith=31),
        _mem("became_friends", "900.1.1"),
    ],
}
# 伊戈尔类: 宗教不变、礼仪改 (差分点, 无记忆)
IGOR = {
    "faith": 12, "rite": 5,
    "faith_history": [{"from": "905.1.1", "faith": 12}],
    "rite_history": [{"from": "905.1.1", "rite": 6},
                     {"from": "917.1.1", "rite": 5}],
    "memories": [_mem("converted_rite_memory", "873.6.5",
                      childhood_memory=1, new_rite=6, old_rite=None)],
}
# 达里娅类: 改信记忆的日期比差分点早一档 (911.6.15 vs 912.1.1)
DARIA = {
    "faith": 12, "rite": 154,
    "faith_history": [{"from": "910.1.1", "faith": 9},
                      {"from": "912.1.1", "faith": 12}],
    "rite_history": [{"from": "910.1.1", "rite": 67},
                     {"from": "912.1.1", "rite": 154}],
    "memories": [_mem("converted_faith_memory", "911.6.15",
                      childhood_memory=1, new_rite=154, new_faith=12,
                      old_faith=9)],
}


def unit_checks():
    print("[U] 纯函数")
    f = _facts({"44503": GF, "44804": IGOR, "67135364": DARIA})

    # ---- 1. 记忆 → 精确变更点 ----
    cp = f.conversion_points("44503")
    check("U1a 改信/改礼记忆读成精确变更点 (fid 由 new_rite 反查)",
          cp == {"885.6.4": (12, 154), "894.7.21": (31, 32),
                 "895.5.27": (12, 154)}, cp)
    check("U1b 非改信记忆不入点",
          all(v != (None, None) for v in cp.values()) and len(cp) == 3, cp)
    check("U1c 无此类记忆返回空",
          f.conversion_points("99999") == {}, f.conversion_points("99999"))

    # ---- 2. 三源合一 (记忆优先 + 相邻同值合并) ----
    pts = f.faith_rite_history("44503")
    check("U2a 记忆点并入缓差点、同日取记忆、相邻同值合并",
          pts == [("885.6.4", 12, 154), ("894.7.21", 31, 32),
                  ("895.5.27", 12, 154)], pts)
    check("U2b 只有缓差点的人沿革不变 (两轴各自取值, 与记忆点合并去重)",
          f.faith_rite_history("44804")
          == [("873.6.5", 12, 6), ("917.1.1", 12, 5)],
          f.faith_rite_history("44804"))
    check("U2c 记忆点比差分点早一档时取记忆日",
          f.faith_rite_history("67135364")
          == [("910.1.1", 9, 67), ("911.6.15", 12, 154)],
          f.faith_rite_history("67135364"))

    # ---- 3. 信仰 = 宗教 + 礼仪 ----
    check("U3a 完整称法 = 宗教+礼仪",
          f._faith_rite_label(12, 154) == "迦克墩基督教拜上帝会",
          f._faith_rite_label(12, 154))
    check("U3b 同名不重复", f._faith_rite_label(12, None) == "迦克墩基督教"
          and f._faith_rite_label(None, 154) == "拜上帝会",
          (f._faith_rite_label(12, None), f._faith_rite_label(None, 154)))
    check("U3c faith(cid) 出完整称法, 且按篇截止日取",
          f.faith("44503") == "迦克墩基督教拜上帝会"
          and f.faith("44804") == "迦克墩基督教希腊礼"
          and f.faith("44804", "920.1.1") == "迦克墩基督教加洛林礼",
          (f.faith("44503"), f.faith("44804"),
           f.faith("44804", "920.1.1")))

    # ---- 4. 信仰履历句 ----
    rows = f.faith_history_lines("44503")
    check("U4a 履历含全部三点 (885 改礼也算, 当前信仰写全称)",
          rows == ["885年至893年信迦克墩基督教拜上帝会", "894年信儒家经学",
                   "自895年起改信迦克墩基督教拜上帝会"], rows)
    check("U4b 无同年退化病句", not any(_SAME_YEAR.search(r) for r in rows), rows)
    check("U4c 记忆日取代晚一档的差分日 (911 而非 912)",
          f.faith_history_lines("67135364")
          == ["910年信大乘佛教华严宗", "自911年起改信迦克墩基督教拜上帝会"],
          f.faith_history_lines("67135364"))
    check("U4d 窗口内看不到变更时不出句 (as_of=915 时 917 那次改礼还没发生)",
          _facts({"44804": IGOR}, as_of="922.1.1").faith_history_lines("44804")
          == ["873年至916年信迦克墩基督教希腊礼",
              "自917年起改信迦克墩基督教加洛林礼"]
          and _facts({"44804": IGOR}, as_of="915.1.1")
          .faith_history_lines("44804") == [],
          _facts({"44804": IGOR}, as_of="915.1.1").faith_history_lines("44804"))

    # ---- 5. 礼仪沿革句 (礼仪轴) ----
    rrows = f.rite_history_lines("44503", "915.1.1")
    check("U5a 早于首档的改礼补出 (885)",
          rrows == ["885年至893年奉拜上帝会", "894年奉经学",
                    "自895年起改奉拜上帝会"], rrows)
    check("U5b 礼仪轴相邻同礼合并 (伊戈尔 873 童年改礼合并掉 905 那点)",
          f.rite_history_lines("44804", "922.1.1")
          == ["873年至916年奉希腊礼", "自917年起改奉加洛林礼"],
          f.rite_history_lines("44804", "922.1.1"))
    check("U5c 无同年退化病句",
          not any(_SAME_YEAR.search(x) for x in rrows), rrows)

    # ---- 6. 不越权: 日期取值的旧口径没被动 ----
    d = _facts({"67135364": DARIA})
    check("U6a _faith_id 仍按缓存沿革取当日值 (记忆点不入该链)",
          d._faith_id("67135364", "910.5.1") == 9
          and d._faith_id("67135364", "912.5.1") == 12,
          (d._faith_id("67135364", "910.5.1"),
           d._faith_id("67135364", "912.5.1")))
    check("U6b _CONV_MEM_TYPES 只收两个改信/改礼型",
          F.Facts._CONV_MEM_TYPES == ("converted_faith_memory",
                                      "converted_rite_memory"),
          F.Facts._CONV_MEM_TYPES)
    check("U6c cache_lib 的取词口未被改名",
          cl.faith_name_of(MELT, 12) == "迦克墩基督教"
          and cl.rite_name_of(MELT, 154) == "拜上帝会"
          and cl.faith_id_of_rite(MELT, 154) == 12, "")


def snap_checks(path):
    with open(path, encoding="utf-8") as fp:
        snap = json.load(fp)
    facts = snap.get("facts") or {}
    pid = str((snap.get("meta") or {}).get("player_id"))
    prot = facts.get("protagonist") or {}
    print(f"[S] {os.path.basename(path)} pid={pid} "
          f"as_of={(snap.get('meta') or {}).get('as_of')}")
    rite = facts.get("rite") or ""
    check("S1 传主当前信仰 = 宗教 + 礼仪",
          bool(rite) and rite in str(prot.get("faith") or "")
          and str(prot.get("faith")) != rite, (rite, prot.get("faith")))
    fh = str(prot.get("faith_history") or "")
    check("S2 《本纪》传主档案有信仰履历 (v91 问题1)",
          fh.count("；") >= 1, fh)
    check("S3 履历无同年退化病句", not _SAME_YEAR.search(fh), fh)
    rh = facts.get("rite_history") or []
    check("S4 《礼仪志》礼仪沿革非空且无同年退化病句",
          len(rh) >= 2 and not any(_SAME_YEAR.search(x) for x in rh), rh)
    blocks = snap.get("blocks") or {}
    mid = blocks.get("liyi_mid")
    keys = set(mid.keys()) if isinstance(mid, dict) else set()
    check("S5 礼仪志纪事含「礼仪沿革」块",
          "礼仪沿革" in keys, sorted(keys))
    # 传主自己的档案行: 信仰必带礼仪, 不许出现「信迦克墩基督教，」这种半截标签
    lead = blocks.get("benji_lead")
    own = ""
    if isinstance(lead, dict):
        own = str((lead.get("传主档案") or ""))
    check("S6 传主档案行不写半截信仰 (宗教后必接礼仪)",
          bool(own) and f"信{prot.get('faith')}" in own
          and "信迦克墩基督教，" not in own
          and "信迦克墩基督教。" not in own, own[:120])


def main():
    unit_checks()
    paths = sys.argv[1:] or list(_DEFAULT)
    for p in paths:
        if os.path.isfile(p):
            snap_checks(p)
        else:
            print(f"  [SKIP] 快照不在: {p}")
    print("\n" + ("全部通过" if _OK else "有失败项"))
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
