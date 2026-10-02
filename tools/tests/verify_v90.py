# -*- coding: utf-8 -*-
"""v90 五问题 (+1 追加) 回归 (秒级; 不载熔件)。

用法: & tools\\py.ps1 tools\\tests\\verify_v90.py [快照...]
      | 缺省取 output/洪氏2/data/snap_v90_{gf_d1,d3,final}.json

对应 docs/方案_v90_洪氏2五问题.md (用户 2026-10-02 报告):
  1 【概览】「见证加冕180次」—— 加冕见证记忆按**记忆持有人**判方向
    (主角受冕时, 180 位宾客的记忆句都含主角名, 旧判据「名在句中」全计成他的见证)
  2 逐人档案的生卒地出词「生地/卒地」→「生于/死于」
  3 逐人档案条目改**省主语版**(当日官称一并剥去; 别名登记保亲缘定语)
  4 逐人档案去「兄弟姊妹」栏 (主角自己的【传主档案】保留)
  5 《礼仪志》「个人教义沿革」与「修会」移入纪事 ⇒ 本志恒有两个板块
  6 (追加) 逐人档案的**出狱行**带出狱缘由 (改信获释 / 以人情获释 / …)
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import biography as bio   # noqa: E402
import facts as F         # noqa: E402
import style              # noqa: E402

_DEFAULT = tuple(os.path.join(ROOT, "output", "洪氏2", "data", n)
                 for n in ("snap_v90_gf_d1.json", "snap_v90_d3.json",
                           "snap_v90_final.json"))
_OK = True
# 出狱缘由词 (带「缘由」的出狱行才用得到; 裸「获释」是模板兜底)
_MANNER_RE = re.compile(
    r"改信获释|以人情获释|纳赎获释|遭驱逐|遭强征入仕|被迫出家获释|"
    r"被迫放弃宣称获释|亲属斡旋获释|遭阉割而获释")
_DATE_LINE_RE = re.compile(r"^\s*\d+年(?:\d+月\d+日)?，")


def check(name, cond, detail=""):
    global _OK
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (("  — " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _OK = False


class _Stub:
    """`_mem_sentence_body` 的最小替身 (只测出狱行那一条分支)。"""
    as_of = "915.1.1"
    cache = {"characters": {}}

    def __init__(self, manner):
        self._manner = manner

    def event_name(self, cid, date=None):
        return {1: "甲", 2: "乙"}.get(cid, "")

    def release_manner(self, victim, jailer, date):
        return self._manner


def unit_checks():
    print("[U] 纯函数")
    # [3] 省主语剥离: 当日官称前缀
    cases = [
        ("892年12月2日，南诏乡绅洪天曾夺得兰溪。", "冀观察使洪天曾", ["洪天曾"],
         "892年12月2日，夺得兰溪。"),
        ("911年，堕邪者洪天贵福的母亲慧海去世。", "天皇帝堕邪者洪天贵福",
         ["堕邪者洪天贵福"], "911年，母亲慧海去世。"),
        ("885年6月15日，桂郡主洪天姣喜欢上了融州刺史夏彦国。", "天皇女洪天姣",
         ["洪天姣"], "885年6月15日，喜欢上了融州刺史夏彦国。"),
        ("904年11月30日，南诏观察使洪天曾的父亲天皇帝穿刺者洪秀全去世。",
         "冀观察使洪天曾", ["洪天曾"],
         "904年11月30日，父亲天皇帝穿刺者洪秀全去世。"),
    ]
    bad = [(t, F._strip_subject_prefix(t, lab, None, own_names=own))
           for t, lab, own, want in cases
           if F._strip_subject_prefix(t, lab, None, own_names=own) != want]
    check("U1a 当日官称前缀一并剥去 (v90 问题3)", not bad, str(bad))
    check("U1b 他人句首不动",
          F._strip_subject_prefix("877年6月15日，洪天姣与堕邪者洪天贵福结为好友。",
                                  "赵阿九", None, own_names=["赵阿九"])
          == "877年6月15日，洪天姣与堕邪者洪天贵福结为好友。")
    check("U1c 名字前的动词/介词串不剥 (判为非称谓)",
          F._strip_subject_prefix("900年9月19日，他与洪天曾结仇。", "冀观察使洪天曾",
                                  None, own_names=["洪天曾"])
          == "900年9月19日，他与洪天曾结仇。")
    check("U1d 单字名顶格不剥 (防地名撞车)",
          F._strip_subject_prefix("900年1月1日，云州乡绅李某夺得X。", "某乡绅云",
                                  None, own_names=["云"])
          == "900年1月1日，云州乡绅李某夺得X。")
    # [2]/[4] 档案行
    prof = {"label": "冀观察使洪天曾", "name": "洪天曾", "birth": "876年3月11日",
            "culture": "汉人", "faith": "迦克墩基督教", "siblings": "让英、洪天姣",
            "birth_place": "南海", "death_place": "白石"}
    facts = {"as_of": "915.1.1", "player_id": 1, "protagonist": dict(prof),
             "characters": {"2": dict(prof)}}
    kin = "\n".join(bio._profile_lines(facts, 2, with_real_parentage=True))
    own = "\n".join(bio._profile_lines(facts, None))
    check("U2a 逐人档案生卒地出词为「生于/死于」",
          "生于南海" in kin and "死于白石" in kin
          and "生地" not in kin and "卒地" not in kin, kin)
    check("U2b 逐人档案无「兄弟姊妹」栏 (v90 问题4)",
          "兄弟姊妹" not in kin, kin)
    check("U2c 主角自己的传主档案保留「兄弟姊妹」",
          "兄弟姊妹" in own, own)
    # [5] 礼仪志门槛
    base = {"rite": "罗马礼", "rite_profile": ["所奉礼仪：罗马礼。"]}
    check("U3a 纪事门槛含修会与个人教义沿革 (v90 问题5)",
          bio._liyi_has_mid(dict(base, holy_orders=["x"]))
          and bio._liyi_has_mid(dict(base, personal_tenets=["a", "b"]))
          and not bio._liyi_has_mid(dict(base)))
    check("U3b 出篇门槛任一条件都落在纪事里 ⇒ 有本篇必有纪事",
          all(bio._liyi_has_mid(dict(base, **{k: v}))
              for k, v in (("rite_history", ["a", "b"]),
                           ("personal_tenets", ["a", "b"]),
                           ("holy_orders", ["x"]),
                           ("forbidden_tenets", ["x"]))))
    req = style.SECTION_REQ.get("liyi", {})
    check("U3c 提示词无负向禁令词 (no-negative-prompts)",
          not re.search(r"不要|请勿|勿|禁止|避免|切勿|不得|别 |严禁|不可|不再|除非",
                        (req.get("lead") or "") + (req.get("mid") or "")))
    check("U3d 开篇要求不再点名修会 (修会已入纪事)",
          "修会" not in (req.get("lead") or "")
          and "修会" in (req.get("mid") or ""))
    # [1] 加冕见证带 owner 槽
    check("U4 加冕见证记忆已入 _IDENT_TYPES (按持有人判方向)",
          "witnessed_a_coronation_memory" in F._IDENT_TYPES)
    # [6] 档案出狱缘由
    mem = {"type": "released_from_prison_memory", "creation_date": "913.9.10",
           "participants": {"imprisoner": 2}}
    check("U5a 有出狱缘由时档案行带走缘由",
          F._mem_sentence_body(_Stub(("converted", "改信获释")), 1, mem)
          == "甲改信获释。",
          F._mem_sentence_body(_Stub(("converted", "改信获释")), 1, mem))
    check("U5b 无证据时回落裸「获释」",
          F._mem_sentence_body(_Stub(("", "")), 1, mem) == "甲获释。")
    check("U5c released 档不与模板重复",
          F._mem_sentence_body(_Stub(("released", "获释")), 1, mem) == "甲获释。")
    check("U5d 无监禁者时不判 (走模板)",
          F._mem_sentence_body(_Stub(("converted", "改信获释")), 1,
                               {"type": "released_from_prison_memory",
                                "creation_date": "913.9.10"}) == "甲获释。")


def snap_checks(path):
    snap = json.load(open(path, encoding="utf-8"))
    if int(snap.get("schema") or 1) < 5:
        print(f"  [SKIP] 非 v90 传输面快照 (schema<5): {os.path.basename(path)}")
        return
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    meta = snap.get("meta") or {}
    shared = snap.get("shared") or ""
    print(f"[S] pid={meta.get('player_id')} as_of={meta.get('as_of')} "
          f"decade={meta.get('decade')} ({os.path.basename(path)})")
    # [1] 概览
    st = list(facts.get("decade_stats") or [])
    check("S1a 概览无「见证加冕N次」",
          not any(x.startswith("见证加冕") for x in st), str(st))
    check("S1b 概览的次数量级正常 (无 3 位数)",
          all(int(re.sub(r"\D", "", x) or 0) < 100 for x in st), str(st))
    if str(meta.get("player_id")) == "44503":
        check("S1c 主角受冕计入概览「受冕」",
              any(x.startswith("受冕") for x in st), str(st))
    # [2]/[4] 档案面
    profs = facts.get("characters") or {}
    txt = json.dumps([facts, blocks, snap.get("messages") or {}],
                     ensure_ascii=False)
    check("S2a 全篇无「生地」「卒地」出词",
          "生地" not in txt and "卒地" not in txt,
          str(re.findall(r".{0,10}生[地卒].{0,10}", txt)[:3]))
    # 逐人档案块 (家室档案·X) 内不得再有「兄弟姊妹」; 「传主档案」是主角自己的档案,
    # 逐篇共享前缀都带它, 按题 4 的口径**保留**
    bad_blocks = []
    for k, v in blocks.items():
        if not k.startswith("jiashi"):
            continue
        for bk, bv in (v or {}).items():
            if bk.startswith("家室档案") and isinstance(bv, str) \
                    and "兄弟姊妹" in bv:
                bad_blocks.append(f"{k}.{bk}")
    check("S3a 家室档案块无「兄弟姊妹」栏", not bad_blocks, str(bad_blocks))
    _lead = {}
    for k, v in blocks.items():
        if k.endswith("_lead"):
            _lead = (v or {}).get("传主档案") or ""
            break
    check("S3b 主角【传主档案】保留兄弟姊妹行 (有料时)",
          ("兄弟姊妹" in _lead) or not (facts.get("protagonist") or {}).get(
              "siblings"), _lead[:120])
    # [3] 逐人条目省主语: 句首不再出现「(称谓)本人名」，而是直接动词起句
    offenders = []
    for cid, p in profs.items():
        nm = p.get("name") or ""
        if not nm:
            continue
        for ln in (p.get("events_subjectless") or []):
            rest = F._SUBJ_DATE_RE.sub("", ln)
            if F._strip_own_prefix(rest, [nm]) is not None:
                offenders.append((cid, nm, ln))
    check("S4 逐人条目省主语 (句首本人名已剥净)",
          not offenders, f"{len(offenders)} 例: {offenders[:3]}")
    # [5] 礼仪志两个板块
    lead = blocks.get("liyi_lead") or {}
    mid = blocks.get("liyi_mid") or {}
    if lead or mid:
        check("S5a 本志必有两个板块", bool(lead) and bool(mid),
              f"lead={list(lead)} mid={list(mid)}")
        check("S5b 修会与个人教义沿革在纪事、不在开篇",
              "修会" not in lead and "个人教义沿革" not in lead
              and ("修会" in mid or not (facts.get("holy_orders") or []))
              and ("个人教义沿革" in mid
                   or not (facts.get("personal_tenets") or [])),
              f"lead={list(lead)} mid={list(mid)}")
    # [6] 出狱缘由进了逐人档案
    hits = []
    for cid, p in profs.items():
        for ln in (p.get("events") or []):
            if _DATE_LINE_RE.match(ln) and _MANNER_RE.search(ln):
                hits.append((cid, ln))
    if hits:
        check("S6a 逐人档案的出狱行带缘由", True)
    else:
        print("  [SKIP] S6a 本快照的逐人档案无带缘由的出狱行")
    check("S6b facts 无 vassal_tenets 键", "vassal_tenets" not in facts)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    paths = args or list(_DEFAULT)
    unit_checks()
    found = 0
    for p in paths:
        if os.path.isfile(p):
            snap_checks(p)
            found += 1
        else:
            print(f"  [SKIP] 快照不存在: {p}")
    print()
    print("v90 断言:" + (" 全部通过" if _OK else " **有失败**") + f" (快照 {found} 份)")
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
