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
import localization as L      # noqa: E402

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


class Stub:
    """Facts stand-in for the church helpers: the class constants come from Facts, the state here."""
    _CHURCH_COUNCIL_LAG_DAYS = F.Facts._CHURCH_COUNCIL_LAG_DAYS
    _CHURCH_RULE_KINDS = F.Facts._CHURCH_RULE_KINDS
    _RULING_ORDER = F.Facts._RULING_ORDER
    _church_days = staticmethod(F.Facts._church_days)
    date = staticmethod(lambda d: F.llm.fmt_cn_date(d))

    def _event_line(self, e, clauses=None):
        return F.Facts._event_line(self, e, clauses)

    _merge_rulings = F.Facts._merge_rulings


def ev(date, kind, phrase, actor="欢乐者尼各老"):
    return {"date": date, "kind": kind, "phrase": phrase, "actor": actor,
            "rules": kind in F.Facts._CHURCH_RULE_KINDS}


def row(frm, prev, kind, text, leader="礼仪领袖欢乐者尼各老"):
    return {"from": frm, "prev": prev, "kind": kind, "text": text, "leader": leader}


def test_merge():
    print("[B] 事件↔定夺配对与合写")
    s = Stub()
    # ① 诏书：即时类，落在定夺窗口内 ⇒ 合写（用户样例的形状）
    out = s._merge_rulings(
        [ev("982.12.18", "bull", "颁布教宗诏书")],
        [row("983.1.1", "982.1.1", "tenet", "将原先禁止的「隐修」改为允许")])
    check("诏书与定夺合写一行",
          out == ["982年12月18日，欢乐者尼各老颁布教宗诏书，将原先禁止的「隐修」改为允许。"], out)
    # ② 大公会议：延迟类，允许晚至 3 年
    out = s._merge_rulings(
        [ev("980.3.20", "council", "举行大公会议", actor="里昂总主教区总主教厄德·罗贝尔")],
        [row("982.1.1", "979.1.1", "tenet", "将原先允许的「华夏综摄主义」改为禁止")])
    check("大公会议的定夺归到会议（延迟 1.8 年）",
          out == ["980年3月20日，里昂总主教区总主教厄德·罗贝尔举行大公会议，"
                  "将原先允许的「华夏综摄主义」改为禁止。"], out)
    # ③ 会议超过 3 年不再认领
    out = s._merge_rulings(
        [ev("980.3.20", "council", "举行大公会议", actor="甲")],
        [row("985.1.1", "983.1.1", "tenet", "将「圣洁自然」列为禁止")])
    check("会议滞后超过 3 年则独立成行",
          out == ["980年3月20日，甲举行大公会议。",
                  "985年起，礼仪领袖欢乐者尼各老将「圣洁自然」列为禁止。"], out)
    # ④ 即时类必须在窗口内：晚于锁存点的诏书不认领
    out = s._merge_rulings(
        [ev("978.9.9", "bull", "颁布教宗诏书")],
        [row("978.1.1", "976.1.1", "tenet", "将原先允许的「天主的和平」改为禁止")])
    check("晚于锁存点的诏书不认领",
          out[0] == "978年9月9日，欢乐者尼各老颁布教宗诏书。"
          and out[1].startswith("978年起，"), out)
    # ⑤ 即时类早于上一变更点也不认领
    out = s._merge_rulings(
        [ev("975.10.13", "bull", "颁布教宗诏书")],
        [row("982.1.1", "979.1.1", "tenet", "将原先允许的「华夏综摄主义」改为禁止")])
    check("早于上一变更点的诏书不认领",
          out[1].startswith("982年起，"), out)
    # ⑥ 一个事件可带多条定夺，用「；」连接；核心教义在前
    out = s._merge_rulings(
        [ev("980.3.20", "council", "举行大公会议", actor="厄德·罗贝尔")],
        [row("982.1.1", "979.1.1", "core", "改本礼核心教义：「武装朝圣」换成「圣人敬礼」"),
         row("982.1.1", "979.1.1", "tenet", "将原先允许的「华夏综摄主义」改为禁止"),
         row("982.1.1", "979.1.1", "doctrine", "改本礼信条：丧葬传统由「亲族葬礼」改为「制为木乃伊」")])
    check("多条定夺按 核心→教义→信条 排、以「；」连接",
          out == ["980年3月20日，厄德·罗贝尔举行大公会议，"
                  "改本礼核心教义：「武装朝圣」换成「圣人敬礼」；"
                  "将原先允许的「华夏综摄主义」改为禁止；"
                  "改本礼信条：丧葬传统由「亲族葬礼」改为「制为木乃伊」。"], out)    # ⑦ 无主使人的事件行
    out = s._merge_rulings([ev("973.4.4", "bull", "颁布教宗诏书", actor="")], [])
    check("主使人缺失时只写短语", out == ["973年4月4日，颁布教宗诏书。"], out)


class SaintStub:
    """Facts stand-in for `_saint_prefix`: real trait latch + real localization table."""
    table = L.table()
    _has_trait_at = F.Facts._has_trait_at
    _in_saint_register = F.Facts._in_saint_register
    _saint_prefix_uncached = F.Facts._saint_prefix_uncached
    _faith_id = F.Facts._faith_id
    _tl = []

    def person_label_nm(self, cid, date):
        return F.Facts._person_label_uncached.__name__   # placeholder, unused

    def __init__(self, chars, saints=(), rtag="christianity_religion", as_of="999.1.1",
                 female=False):
        self.cache = {"characters": chars, "player_id": 1}
        self.as_of = as_of
        self._saints = list(saints)
        self._rtag = rtag
        self._female = female

    def _faith_tags(self, cid, date=None):
        return ("catholic", self._rtag)

    def _faith_id(self, cid, date=None):
        return 13

    def _is_female(self, cid):
        return self._female

    def _in_saint_register(self, cid):
        return int(cid) in self._saints

    _saint_prefix = F.Facts._saint_prefix


def test_saint():
    print("[C] 圣人前缀")
    th = {"44503": {"trait_history": {"saint": [{"from": "971.1.1", "to": None,
                                                 "first": False}]},
                    "traits": []}}
    o = SaintStub(th, saints=[44503])
    check("未封圣的篇（963 卷）不带「圣」",
          F.Facts._saint_prefix(SaintStub(th, as_of="963.1.1"), 44503, "940.1.1") == "")
    check("封圣后的篇：基督教圣人 → 圣",
          F.Facts._saint_prefix(o, 44503, "932.3.13") == "圣")
    check("信仰注册表兜底（无特质史）",
          F.Facts._saint_prefix(SaintStub({}, saints=[44503]), 44503, "999.1.1") == "圣")
    check("非圣人 → 空前缀",
          F.Facts._saint_prefix(SaintStub({}, saints=[]), 44503, "999.1.1") == "")
    check("女性圣人取 christian_female_saint → 圣",
          F.Facts._saint_prefix(SaintStub(th, saints=[44503], female=True), 44503,
                                "999.1.1") == "圣")
    mth = {"81124": {"trait_history": {"saint": [{"from": "980.1.1", "to": None,
                                                  "first": False}]}, "traits": []}}
    check("穆斯林圣人 → 吾里",
          F.Facts._saint_prefix(SaintStub(mth, rtag="islam_religion"), 81124, "999.1.1")
          == "吾里")
    check("表内确有该词条（游戏本地化）",
          L.loc(L.table(), "christian_saint") == "圣"
          and L.loc(L.table(), "muslim_saint") == "吾里")


def load_snaps():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        return args
    for name in ("snap_v101.json", "snap_v100.json"):
        p = os.path.join(H2, "data", name)
        if os.path.isfile(p):
            return [p]
    return []


def snap_checks(path):
    print(f"\n[D] {os.path.basename(path)}")
    with open(path, encoding="utf-8") as fp:
        snap = json.load(fp)
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    cc = [str(x) for x in (facts.get("church_chronicle") or [])]
    surf = json.dumps(facts, ensure_ascii=False)
    check("① 教会板块非空", bool(cc), len(cc))
    bad = [x for x in cc if any(x.startswith(y) for y in PRE_952)]
    check("① 无 952 年以前的事件行", not bad, bad[:3])
    check("① 首条事件行是 954 年",
          any(x.startswith("954年") for x in cc) and not any(x.startswith(("920年", "951年"))
                                                             for x in cc))
    check("① 相位行日期不再「未知」",
          any(x.startswith("教会局面") and "未知" not in x for x in cc),
          [x for x in cc if x.startswith("教会局面")])
    check("② 诏书行与定夺合写",
          any(re.match(r"^\d+年\d+月\d+日，.+颁布教宗诏书，将原先", x) for x in cc),
          [x for x in cc if "颁布教宗诏书" in x][:2])
    check("③ 980 年厄德·罗贝尔的会议带上成果",
          any(x.startswith("980年3月20日") and "厄德·罗贝尔" in x and "华夏综摄主义" in x
              for x in cc), [x for x in cc if "980年" in x][:2])
    check("③ 986 年会议带核心教义与信条",
          any(x.startswith("986年12月18日") and "核心教义" in x and "血亲性关系" in x
              for x in cc), [x for x in cc if "986年" in x][:2])
    check("③ 未配到事件的定夺仍独立成行（如有）",
          all(("年起" not in x) or x.endswith("。") for x in cc))
    check("④ rite_tenet_changes 已空（核心教义改由教会板块承载）",
          not (facts.get("rite_tenet_changes") or []), facts.get("rite_tenet_changes"))
    check("④ 传输面出现「圣洪天贵福」", "圣洪天贵福" in surf,
          surf.count("洪天贵福"))
    check("④ 圣人前缀加在名字上而非绰号前", "圣堕邪者" not in surf)
    raw = "\n".join(cc)
    check("⑤ 教会行无裸键/标记/括注",
          not BARE.search(raw) and not MARK.search(raw) and not PAREN.search(raw), raw[:200])
    tail = (blocks.get("liyi_tail") or {})
    check("⑤ 末场板块带教会板块键", "大公会议与教宗诏书" in json.dumps(tail, ensure_ascii=False),
          list(tail.keys())[:3])
    mid = json.dumps(blocks.get("liyi_mid") or {}, ensure_ascii=False)
    check("⑤ 中场不再有「本礼教义沿革」块", "本礼教义沿革" not in mid)
    lq = facts.get("_liyi_req") or {}
    check("⑤ 中场要求不再索要核心教义演变",
          "核心教义" not in (lq.get("mid") or ""), lq.get("mid"))
    check("⑤ 末场要求索要合写的定夺",
          "会议与诏书定夺的教义条目" in (lq.get("tail") or "")
          and "本礼核心教义" in (lq.get("tail") or ""), lq.get("tail"))
    check("⑤ 生成的要求无负向禁令词",
          not any(NEG.search(lq.get(k) or "") for k in ("lead", "mid", "tail", "focus")),
          {k: lq.get(k) for k in ("lead", "mid", "tail", "focus")})


def doc_checks():
    print("\n[E] 成稿（存在则断言）")
    for name in ("尼各老(917)_终传_999_07_07.md",
                 "尼各老(917)_传记_第3个十年_983_01_01.md"):
        p = os.path.join(H2, name)
        if not os.path.isfile(p):
            print(f"  [SKIP] 缺成稿 {name}")
            continue
        text = open(p, encoding="utf-8").read()
        check(f"{name} 无 952 年以前的教会事件",
              not any(f"{y}年3月2日，礼仪分歧过重" in text for y in ("873",))
              and "920年2月1日，教会大分裂" not in text, name)
        check(f"{name} 出现合写的 980 年会议",
              "980年3月20日" in text and "厄德·罗贝尔" in text, name)
        check(f"{name} 出现「圣洪天贵福」", "圣洪天贵福" in text, name)


def main():
    test_window()
    test_merge()
    test_saint()
    snaps = load_snaps()
    print(f"(快照 {len(snaps)} 份：{[os.path.basename(s) for s in snaps]})")
    for p in snaps:
        snap_checks(p)
    doc_checks()
    print("PASS" if OK else "FAIL")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
