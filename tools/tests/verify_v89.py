# -*- coding: utf-8 -*-
"""v89 七问题回归 (秒级; 不载熔件)。

用法: & tools\\py.ps1 tools\\tests\\verify_v89.py [快照...]
      ｜ 缺省取 output/洪氏2/data/snap_v89_{d1,d3,final}.json

对应 docs/方案_v89_洪氏2七问题.md:
  1 上游排队超时: llm 单次尝试墙钟上限 + 排队超时可重试 (纯函数断言;
    端到端假上游断言见 tools/tests/probe_v89_llm.py)
  2 教省首座出词「江宁总主教」+ 臂表 exists/tier/landless 叶子
  3 教义/修会名去〈〉(全项目)
  4 本礼核心教义自身的更替 (缓存逐档锁存 + 差分, 写出当时的礼仪领袖)
  5 删门下教众; 修会 = 亲立 / 领地内同信仰, 补现任之长
  6 灵性满足用游戏官方等级名
  7 删提示词「自足之世」
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F          # noqa: E402
import llm                # noqa: E402
import localization as L  # noqa: E402
import style              # noqa: E402

_DEFAULT = tuple(os.path.join(ROOT, "output", "洪氏2", "data", n)
                 for n in ("snap_v89_d1.json", "snap_v89_d3.json",
                           "snap_v89_final.json"))
_OK = True
_LEVEL_RE = re.compile(r"^(?:christian|default)_fulfillment_level_\d+$")


def check(name, cond, detail=""):
    global _OK
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (("  — " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _OK = False


def unit_checks():
    print("[U] 纯函数")
    # [7] 删「自足之世」
    check("U1a RULES 无 world_frame", "world_frame" not in style.RULES)
    check("U1b _RULE_ORDER 无 world_frame",
          "world_frame" not in style._RULE_ORDER)
    check("U1c 规则块无「自足之世」", "自足之世" not in style.rule_block("east"))
    # [6] 灵性满足分档表
    tb = L.spiritual_fulfillment()
    check("U2a 分档表两套 (christian 7 档 / default 5 档)",
          [t["key"] for t in tb["types"]] == ["christian_fulfillment",
                                              "default_fulfillment"]
          and [len(t["levels"]) for t in tb["types"]] == [7, 5],
          str([(t["key"], len(t["levels"])) for t in tb["types"]]))
    ch = L.sf_type_for(tb, "christianity_religion")
    df = L.sf_type_for(tb, "rf_pagan")
    check("U2b 基督教按 religion 命中 christian_fulfillment",
          ch.get("key") == "christian_fulfillment")
    check("U2c 其余宗教落 default_fulfillment 兜底",
          df.get("key") == "default_fulfillment")
    cases = [(-100, 0), (-95, 0), (-94.9, 0), (-65, 1), (-30, 2), (-0.1, 2),
             (0, 3), (29.9, 3), (30, 4), (65, 5), (78.155, 5), (95, 6),
             (100, 6)]
    bad = [(v, L.sf_level_index(ch["levels"], v), w)
           for v, w in cases if L.sf_level_index(ch["levels"], v) != w]
    check("U2d 基督教 7 档阈值 (含 -95/0/65/95 边界)", not bad, str(bad))
    dcases = [(-100, 0), (-65, 0), (-64, 0), (0, 2), (30, 3), (64, 3),
              (65, 4), (100, 4)]
    dbad = [(v, L.sf_level_index(df["levels"], v), w)
            for v, w in dcases if L.sf_level_index(df["levels"], v) != w]
    check("U2e 兜底 5 档阈值", not dbad, str(dbad))
    # [1] 排队超时识别
    check("U3a 排队超时正则命中 DeepSeek 原文",
          bool(llm._QUEUE_TIMEOUT_RE.search(
              "We were unable to start processing your request within the "
              "900-second timeout limit. Please try again later.")))
    check("U3b 正常体不误判", not llm._QUEUE_TIMEOUT_RE.search(
        '{"choices":[{"message":{"content":"x"}}]}'))
    check("U3c 单次尝试墙钟上限已设",
          isinstance(llm.ATTEMPT_DEADLINE_SECONDS, int)
          and llm.ATTEMPT_DEADLINE_SECONDS > 0,
          str(llm.ATTEMPT_DEADLINE_SECONDS))
    check("U3d 流式读体函数在位", callable(getattr(llm, "_read_body", None)))
    # [2] 臂表叶子 (新解析器产出的表里不该再有 `tier` 的 unknown 叶子)
    arms = (F.Facts.__dict__.get("_HOLY_SEAT_KEYS") is not None)
    check("U4a 教省首座常量在位", arms)
    import localization as _L
    _tb = _L.load_bishop_titles()
    _cr = [a for a in (_tb.get("arms") or [])
           if "clerical_region" in json.dumps(a, ensure_ascii=False)]
    check("U4b 主教臂表含 clerical_region 臂且已解析 tier (schema 4)",
          _tb.get("schema") == 4 and bool(_cr)
          and all("unknown" not in json.dumps(a, ensure_ascii=False).split(
              "clerical_region")[0][-60:] for a in _cr[:1]),
          str(_tb.get("schema")))
    _tt = _L.load_theocracy_titles()
    check("U4c 神权臂表 schema 2", _tt.get("schema") == 2, str(_tt.get("schema")))


def snap_checks(path):
    snap = json.load(open(path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    meta = snap.get("meta") or {}
    txt = json.dumps([facts, blocks], ensure_ascii=False)
    print(f"[S] pid={meta.get('player_id')} as_of={meta.get('as_of')} "
          f"decade={meta.get('decade')} ({os.path.basename(path)})")
    if "rite_tenet_changes" not in facts:
        print("  [SKIP] 非 v89 传输面快照")
        return
    # [3] 括号
    check("S1 事实面与板块面无〈〉", "〈" not in txt,
          str([x for x in re.findall(r".{0,12}〈.{0,12}", txt)][:3]))
    # [6] 灵性满足用游戏等级名
    prof = " ".join(facts.get("rite_profile") or [])
    m = re.search(r"灵性满足：([^。]+)。", prof)
    _lvl_keys = [k for k in L.load_localization_table().keys()
                 if _LEVEL_RE.match(k)] if False else []
    _tb = L.spiritual_fulfillment()
    _names = set()
    for t in _tb.get("types") or []:
        for i in range(len(t.get("levels") or [])):
            v = L.loc(F.Facts.__new__(F.Facts).__dict__.get("table") or {},
                      f"{t['key']}_level_{i}") if False else None
    _ent = json.load(open(os.path.join(ROOT, "data", "localization.json"),
                          encoding="utf-8"))["table"]
    for t in _tb.get("types") or []:
        for i in range(len(t.get("levels") or [])):
            v = _ent.get(f"{t['key']}_level_{i}")
            if v:
                _names.add(v)
    check("S2 灵性满足是游戏等级名", bool(m) and m.group(1) in _names,
          f"{m.group(1) if m else None} 不在 {sorted(_names)}")
    # [2] 礼仪领袖
    lm = re.search(r"礼仪领袖：([^。]+)。", prof)
    check("S3 礼仪领袖无「前…职司」式兜底",
          bool(lm) and "前礼部尚书" not in (lm.group(1) if lm else ""),
          prof[:120])
    if str(meta.get("as_of")).startswith("904"):
        check("S3b 终传礼仪领袖 = 江宁总主教恺",
              bool(lm) and lm.group(1) == "江宁总主教恺",
              lm.group(1) if lm else None)
    # [4] 本礼教义更替
    tcs = facts.get("rite_tenet_changes") or []
    check("S4a 无括注同位语", all("（" not in x and "(" not in x for x in tcs), tcs)
    if tcs:
        check("S4b 每行写明当时的礼仪领袖",
              all("礼仪领袖" in x for x in tcs), tcs[:2])
        check("S4c 每行写「换出…换成…」或增/减",
              all(("换成" in x or "增定" in x or "去" in x) for x in tcs), tcs[:2])
        check("S4d 每行自「N年起」开头",
              all(re.match(r"^\d{3,4}年起", x) for x in tcs), tcs[:2])
    if str(meta.get("as_of")).startswith("898"):
        check("S4e 898 档含 887 年那次更替 (圣人敬礼→圣洁自然)",
              any("887年起" in x and "圣人敬礼换成圣洁自然" in x for x in tcs),
              tcs)
    if str(meta.get("as_of")).startswith("904"):
        check("S4f 终传含 887 与 901 两次更替",
              any("887年起" in x for x in tcs) and any("901年起" in x for x in tcs)
              and any("圣洁自然换成基督的精兵" in x for x in tcs), tcs)
        check("S4g 901 年那次记为传主本人",
              any("901年起" in x and "洪秀全" in x for x in tcs), tcs)
    # [5] 修会
    check("S5a facts 无 vassal_tenets 键", "vassal_tenets" not in facts)
    check("S5b 无「门下教众」块",
          all("门下教众" not in (blocks.get(k) or {})
              for k in ("liyi_lead", "liyi_mid")))
    ho = facts.get("holy_orders") or []
    check("S5c 修会行 ≤ 6", len(ho) <= 6, str(len(ho)))
    check("S5d 每行有关系词 (他立/领地之内/庇护者)",
          all(("他立" in x or "在其领地之内" in x or "庇护者" in x)
              for x in ho), ho[:1])
    check("S5e 每行有现任之长", all("现任之长" in x for x in ho), ho[:2])
    check("S5f 修会行无括注", all("（" not in x for x in ho), ho[:2])
    lead = blocks.get("liyi_lead") or {}
    mid = blocks.get("liyi_mid") or {}
    if lead or mid:
        if int(snap.get("schema") or 1) >= 5:
            # v90 (问题5): 开篇只留礼仪档案, 修会与个人教义沿革移入纪事
            check("S6a 修会块在纪事 (v90 问题5)", "修会" in mid, str(list(mid)))
            check("S6b 本礼教义沿革在纪事",
                  tcs == [] or "本礼教义沿革" in mid, str(list(mid)))
            check("S6c 纪事只含纪事类块",
                  set(mid) <= {"传主档案", "个人教义沿革", "修会", "礼仪沿革",
                               "禁忌个人信条", "本礼教义沿革"}, str(list(mid)))
        else:
            check("S6a 修会块在开篇 (v89 口径)", "修会" in lead, str(list(lead)))
            check("S6b 本礼教义沿革在纪事",
                  tcs == [] or "本礼教义沿革" in mid, str(list(mid)))
            check("S6c 纪事只含纪事类块",
                  set(mid) <= {"传主档案", "礼仪沿革", "禁忌个人信条",
                               "本礼教义沿革"}, str(list(mid)))


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
    print("v89 断言:" + (" 全部通过" if _OK else " **有失败**") + f" (快照 {found} 份)")
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
