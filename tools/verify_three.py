# -*- coding: utf-8 -*-
"""v32 三问题确定性回归（马克龙三问：监禁者/出狱方式・特质子轨道・夭折生母）。

用法：
    & D:\\Roman\\tools\\py.ps1 tools\\verify_three.py [快照路径]
    ｜ 缺省不跑快照段；给路径则加跑传输面断言
      （马克龙十年传快照：output/马克龙/data/snap_38677_878.1.1_d1.json）

分层：
    A 纯函数/合成档（不载熔件，秒级）：模板与槽位登记、监禁配对、越狱分词、
      夭折生母（含自指与侧室）、强纳为妾句、特质档位名与子轨道括注。
    B 快照（可选）：传输面里三问的实际出词。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import facts as F          # noqa: E402
import localization as L   # noqa: E402
import style as S          # noqa: E402
from cache_lib import hook_slot_holder as F_hook_slot_holder  # noqa: E402

_OK = True


def check(name, cond, detail=""):
    global _OK
    if not cond:
        _OK = False
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + ("" if cond else f"  | {detail}"))


def mk_facts(chars, pid=None, opinions=None, memories=None, as_of=None,
             trait_xp=None):
    cache = {
        "player_id": pid,
        "characters": {},
        "opinions": opinions or {},
        "hooks": {},
    }
    for cid, r in chars.items():
        rec = {
            "id": cid,
            "name_zh": r.get("name"),
            "first_name": r.get("name"),
            "female": r.get("female", False),
            "traits": r.get("traits") or [],
            "trait_history": r.get("trait_history") or {},
            "trait_xp": trait_xp.get(str(cid), []) if trait_xp else [],
            "family": r.get("family") or {},
            "memories": r.get("memories") or [],
            "death": r.get("death"),
            "landed": {},
        }
        cache["characters"][str(cid)] = rec
    return F.Facts(cache, {"traits_lookup": []}, None, as_of=as_of)


def group_a():
    print("[A1] 三问的登记面 (槽位/模块/切片/模板)")
    for t in ("escaped_from_prison_memory", "child_stillborn", "child_premature"):
        check(f"PARTICIPANT_SLOTS 有 {t}",
              t in F.PARTICIPANT_SLOTS, str(F.PARTICIPANT_SLOTS.get(t)))
    check("模板 imprisoned 用 {other} (监禁者入句)",
          "{other}" in S.MEMORY_TEMPLATES.get("imprisoned", ""),
          S.MEMORY_TEMPLATES.get("imprisoned"))
    check("模板 escaped_from_prison_memory 存在",
          bool(S.MEMORY_TEMPLATES.get("escaped_from_prison_memory")))
    check("MODULE_TABLE 单列「越狱脱逃」",
          "escaped_from_prison_memory" in (F.MODULE_TABLE.get("越狱脱逃") or set()))
    for sec in ("mid",):
        sl = F.MODULE_SLICE.get(("jiashi", sec)) or set()
        check(f"家室列传 {sec} 切片含囚禁/获释/越狱",
              {"囚禁入狱", "获释出狱", "越狱脱逃"} <= sl, str(sorted(sl)))
    lead = F.MODULE_SLICE.get(("jiashi", "lead")) or set()
    check("家室列传开篇不重复囚禁模块 (v27 素材不相交)",
          not ({"囚禁入狱", "获释出狱", "越狱脱逃"} & lead), str(sorted(lead)))
    check("_IDENT_TYPES 含越狱",
          "escaped_from_prison_memory" in F._IDENT_TYPES)
    check("FACT_WORDING 有越狱词条",
          bool(S.FACT_WORDING.get("prison_escaped")))


def group_b():
    print("[B1] 监禁者与出狱方式 (合成档)")
    f = mk_facts({
        1: {"name": "阿甲"},
        2: {"name": "小王"},
        3: {"name": "公主"},
    }, pid=1)
    s = F._mem_sentence(f, 3, {"type": "imprisoned", "creation_date": "868.11.8",
                               "participants": {"imprisoner": 2}})
    check("被囚句点名监禁者", "小王" in (s or "") and "公主" in (s or ""), s)
    s = F._mem_sentence(f, 3, {"type": "escaped_from_prison_memory",
                               "creation_date": "868.12.1",
                               "participants": {"imprisoner": 2}})
    check("越狱句点名监禁者且用「逃脱」",
          (s or "").find("小王") >= 0 and "逃脱" in (s or ""), s)
    s = F._mem_sentence(f, 3, {"type": "imprisoned", "creation_date": "868.11.8",
                               "participants": {}})
    check("无监禁者槽 → 回退「被囚」", (s or "").endswith("被囚。"), s)

    # 同日「被囚 + 越狱」合成一句
    ev = [
        {"date": "869.10.16", "type": "imprisoned", "text": "869年10月16日，小王为阿甲所囚。",
         "ident": {"owner": 2, "parts": {"imprisoner": 1}}},
        {"date": "869.10.16", "type": "escaped_from_prison_memory",
         "text": "869年10月16日，小王自阿甲的监禁中逃脱。",
         "ident": {"owner": 2, "parts": {"imprisoner": 1}}},
    ]
    out = F._pair_imprisonments(ev, f, 1, "")
    txt = " ".join(e.get("text", "") for e in out)
    check("同日囚+逃合为「当日越狱」", "当日越狱" in txt and len(out) == 1, txt)


def group_c():
    print("[C1] 夭折生母 (合成档)")
    f = mk_facts({
        1: {"name": "阿甲", "family": {"spouse": [2], "primary_spouse": [2]}},
        2: {"name": "乙氏", "female": True, "family": {"spouse": [1]}},
        3: {"name": "丙氏", "female": True, "family": {}},
    }, pid=1)
    # 父亲视角: owner=1, participants.mother=妻2
    s = F._mem_sentence(f, 1, {"type": "child_stillborn", "creation_date": "876.8.27",
                               "participants": {"mother": 2}})
    check("夭折句点出正妻", "乙氏" in (s or "") and "之妻" in (s or ""), s)
    # 生母本人视角 (自指) → 无「之妻」
    s = F._mem_sentence(f, 2, {"type": "child_stillborn", "creation_date": "876.8.27",
                               "participants": {"mother": 2}})
    check("生母自指句不出「之妻」", "之妻" not in (s or "") and "乙氏" in (s or ""), s)
    # 侧室
    f2 = mk_facts({
        1: {"name": "阿甲", "family": {"concubine": [3]}},
        3: {"name": "丙氏", "female": True},
    }, pid=1)
    s = F._mem_sentence(f2, 1, {"type": "child_premature", "creation_date": "881.2.2",
                                "participants": {"mother": 3}})
    check("侧室写作「之妾」", "之妾" in (s or "") and "丙氏" in (s or ""), s)


def group_d():
    print("[D1] 强纳为妾 (合成档)")
    cache = {
        "player_id": 1,
        "opinions": {"9>1>forced_me_concubine_marriage_opinion": {
            "owner": 9, "target": 1,
            "modifier": "forced_me_concubine_marriage_opinion",
            "start": "880.1.1", "expiration": "900.1.1",
            "first_seen": "881.1.1", "first": False}},
        "characters": {
            "1": {"id": 1, "name_zh": "阿甲", "memories": []},
            "9": {"id": 9, "name_zh": "戈氏", "female": True,
                  "memories": [{"type": "released_from_prison_memory",
                                "creation_date": "880.1.1",
                                "participants": {"imprisoner": 1}}]},
        },
    }
    f = F.Facts(cache, {"traits_lookup": []}, None, as_of="888.1.1")
    lines = f.forced_concubine_lines()
    check("强纳为妾句成句且带日期", bool(lines) and "戈氏" in lines[0], str(lines))
    check("同日释出写下出狱缘由", "同日自狱中释出" in (lines[0] if lines else ""),
          str(lines))
    f2 = F.Facts(dict(cache, opinions={}), {"traits_lookup": []}, None)
    check("无记录时不发句", f2.forced_concubine_lines() == [])


def group_e():
    print("[E1] 特质档位名与子轨道 (纯函数)")
    tn = L.trait_names()
    check("trait_names schema 3", tn.get("schema") == 3, str(tn.get("schema")))
    check("level_names 非空", bool(tn.get("level_names")))
    tt = (L.trait_track_table().get("tracks") or {})
    check("轨道表含 gallowsbait 五轨",
          len(tt.get("gallowsbait") or []) == 5,
          str(tt.get("gallowsbait")))
    check("零 XP 不取顶档名 (reveler)",
          F._trait_level_name("lifestyle_reveler", {"lifestyle_reveler": 0}) == ""
          and F._trait_name(L.table(), "lifestyle_reveler",
                            xp={"lifestyle_reveler": 0}) == "热切的狂欢者",
          F._trait_name(L.table(), "lifestyle_reveler", xp={"lifestyle_reveler": 0}))
    check("满 XP 取顶档名 (reveler)",
          F._trait_name(L.table(), "lifestyle_reveler",
                        xp={"lifestyle_reveler": 100}) == "传奇的狂欢者")
    check("无 XP 数据 → 基础名 (不取顶档)",
          F._trait_name(L.table(), "lifestyle_reveler") == "热切的狂欢者")
    check("多轨 OR 条件求值 (traveler 双 100)",
          F._trait_level_name("lifestyle_traveler",
                              {"travel": 100, "danger": 0}) == "trait_traveler_3")
    check("多轨 AND 条件求值 (traveler 双 0)",
          F._trait_level_name("lifestyle_traveler",
                              {"travel": 0, "danger": 0}) == "trait_traveler_1")
    # 子轨道括注: 强盗一阶 / 窃贼二阶
    f = mk_facts({"1": {"name": "阿甲"}}, pid=1)
    disp = f._trait_display("gallowsbait", "不法之徒",
                            {"gallowsbait": {"bandit": 20, "thief": 45,
                                             "trickster": 0}})
    check("子轨道括注只列已进档者且带阶数",
          disp == "不法之徒（强盗一阶、窃贼二阶）", disp)
    check("未进档不括注",
          f._trait_display("gallowsbait", "不法之徒",
                           {"gallowsbait": {"bandit": 0}}) == "不法之徒")
    # 进档履历: 同一轨道多次进档并成一行
    cache = {
        "player_id": 1,
        "characters": {"1": {
            "id": 1, "name_zh": "阿甲",
            "traits": [0], "trait_history": {},
            "trait_xp": [
                {"from": "870.1.1", "traits": [0], "xp": [0]},
                {"from": "872.1.1", "traits": [0], "xp": [40]},
                {"from": "874.1.1", "traits": [0], "xp": [70]},
            ],
            "memories": [], "family": {}, "landed": {}},
        },
    }
    tl = ["gallowsbait"] + ["x"] * 200
    f3 = F.Facts(cache, {"traits_lookup": tl}, None, as_of="875.1.1")
    hist = f3.trait_level_history(1)
    check("进档履历同轨道并为一行",
          len(hist) == 1 and hist[0].count("进至") == 2
          and hist[0].startswith("不法之徒·强盗"), str(hist))


def group_f(snap_path):
    print("[F1] 快照传输面")
    s = json.load(open(snap_path, encoding="utf-8"))
    shared = s.get("shared") or ""
    jiashi = (s.get("blocks") or {}).get("jiashi_mid") or ""
    jiashi = jiashi if isinstance(jiashi, str) else json.dumps(jiashi,
                                                               ensure_ascii=False)
    protagonist = ((s.get("facts") or {}).get("protagonist") or {})
    allt = shared + jiashi + json.dumps(s.get("blocks") or {}, ensure_ascii=False)
    check("主角特质无顶档名误写",
          "传奇的狂欢者" not in (protagonist.get("traits") or ""),
          protagonist.get("traits"))
    check("家室列传纪事含囚禁料", "囚" in jiashi)
    check("越狱句进入事实面", "越狱" in allt)
    check("夭折句带生母", ("产下死婴" in allt or "孕期提前结束" in allt))


def group_g():
    """v33: 牵制方向在槽号，不在 first/second（成对编号按 id 规范化）。"""
    print("[G1] 牵制方向 (槽号语义)")
    h = F_hook_slot_holder
    check("槽 0 = first 持有对 second",
          h(38677, 43961, "active_hook_0") == (38677, 43961),
          str(h(38677, 43961, "active_hook_0")))
    check("槽 1 = second 持有对 first",
          h(15982, 38677, "active_hook_1") == (38677, 15982),
          str(h(15982, 38677, "active_hook_1")))
    check("奇偶判定 (槽 2 归 first)",
          h(1, 2, "active_hook_2") == (1, 2))
    check("无槽号后缀时按 0 处理",
          h(1, 2, "active_hook") == (1, 2))


def main():
    group_a()
    group_b()
    group_c()
    group_d()
    group_e()
    group_g()
    if len(sys.argv) > 1:
        group_f(sys.argv[1])
    print("\n" + "=" * 60)
    print("结果:", "全部 PASS" if _OK else "有 FAIL")
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
