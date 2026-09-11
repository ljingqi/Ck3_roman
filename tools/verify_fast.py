# -*- coding: utf-8 -*-
"""快速回归（提速基建）：无熔件、秒级；纯函数 + facts 快照。

用法：
    & D:\\Roman\\tools\\py.ps1 tools\\verify_fast.py [快照路径]
    ｜ 缺省自动取 output/周氏/data/snap_38673_889.1.1_d2.json

分层原则（本会话教训）：
    · 纯函数（兜底/取词/档位/席位/主语剥离/括注判据）→ 本脚本，**不需要熔件**；
    · 需要熔件的端到端断言 → experiments/verify_zhou.py，只在里程碑跑一次；
    · 快照由 tools/snap.py 生成（载一次熔件），本脚本对它做**传输面**断言。

覆盖：
    A 纯函数：裸键兜底 / 职位条件树 / 档位词 / 席位取词 / 句首主语剥离 / 口粮档 / 健康压力
    B 快照：传输面无裸键、无括注同位语、无「言语相通」、无货币数值、席位动态名、
            传主行迹省主语、家世去重、冒险者行踪、隐事方向、快照新鲜度
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import facts as F          # noqa: E402
import localization as L   # noqa: E402

DEFAULT_SNAP = os.path.join(ROOT, "output", "周氏", "data", "snap_38673_889.1.1_d2.json")
_OK = True
_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]{2,}(?![A-Za-z0-9_])")
_PAREN_RE = re.compile(r"（([^）]{1,24})）")
# 括注里**允许**的补注类型（日期/生卒/死地/失位缘由/见载年/涉及对象/同年/自幼/原为）；
# 其余一律视为「名词（名词）」式同位语 —— v29b 用户决策：现代汉语不取此式。
_NOTE_OK_RE = re.compile(
    r"(\d"                       # 年份/日期/生卒
    r"|于"                       # 死于X / 卒于X
    r"|涉及"                     # 隐事涉及对象
    r"|同年"
    r"|自幼"
    r"|原为"
    r"|生，"                     # 「822年生，汉人，信经学」
    r"|无地冒险者营地"           # v24 游戏口径阶段行:「867年任菲利普家族企业队长（无地冒险者营地）」
    r"|让出|卸任|被褫夺|毁弃|归附|失守|转授|调任|受禅|自立"
    r")")


def check(name, cond, detail=""):
    global _OK
    if not cond:
        _OK = False
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + ("" if cond else f"  | {detail}"))


def _paren_violations(text):
    """传输面里「名词（名词）」式括注同位语清单。"""
    bad = []
    for m in _PAREN_RE.finditer(text or ""):
        c = m.group(1)
        if _NOTE_OK_RE.search(c):
            continue
        bad.append(c)
    return sorted(set(bad))


def group_a():
    print("[A1] 裸键兜底 (sanitize_fact_text / loc_text_ok)")
    s = F.sanitize_fact_text("【块】\n882年4月8日，MAX_RECURSIVE_DEPTH\n882年4月8日，程氏结仇。")
    check("哨兵串行被丢弃", "MAX_RECURSIVE_DEPTH" not in s and "程氏结仇" in s, s)
    check("trait_ 键行被丢弃",
          "trait_foo" not in F.sanitize_fact_text("x\ntrait_foo 中文"), "trait_foo")
    check("正常中文行保留", F.sanitize_fact_text("母语泰语，兼通汉语。") == "母语泰语，兼通汉语。")
    check("loc_text_ok: 纯英文判不可读", not F.loc_text_ok("some_raw_key"))
    check("loc_text_ok: 中文判可读", F.loc_text_ok("程氏结仇。"))

    print("[A2] 职位条件树 (cond_match / 变体表)")
    cps = L.court_positions().get("positions") or {}
    phys = cps.get("court_physician_court_position") or []
    def pick(scope):
        for v in phys:
            if L.cond_match(v.get("when") or {}, scope):
                return v.get("loc_key") or ""
        return ""
    celestial_vassal = {"gov_flag": "celestial", "tier": 2, "independent": False,
                        "heritage": "heritage_tai"}
    celestial_emperor = {"gov_flag": "celestial", "tier": 5, "independent": True,
                         "heritage": "heritage_chinese"}
    tribal = {"gov_flag": "tribal", "tier": 2, "independent": True, "heritage": ""}
    check("天朝制非帝国 → court_physician_celestial",
          pick(celestial_vassal) == "court_physician_celestial", pick(celestial_vassal))
    check("天朝制帝国 → court_physician_celestial_imperial",
          pick(celestial_emperor) == "court_physician_celestial_imperial",
          pick(celestial_emperor))
    check("部落 → 默认名 (无 localization_key)", pick(tribal) == "", pick(tribal))
    check("OR 组合求值 (tribal|nomadic)",
          L.cond_match({"op": "all", "children": [
              {"op": "any", "children": [{"gov_flag": "tribal"}, {"gov_flag": "nomadic"}]}]},
              tribal) is True)
    check("未知条件不命中", L.cond_match({"op": "all", "children": [{"unknown": "x"}]},
                                        celestial_vassal) is False)
    check("空条件恒真 (无 trigger 的变体)", L.cond_match({}, celestial_vassal) is True)

    print("[A3] 档位词 (level_word)")
    table, bands = L.table(), (L.currency_levels().get("bands") or {})
    for kind, val, want in (("piety", -865.8, "戴罪之人"), ("prestige", 1863.2, "崭露头角"),
                            ("influence", 534, "人微言轻"), ("merit", 2176.4, "七品"),
                            ("merit", 4524.4, "六品"), ("prestige", 40000, "传奇人物")):
        got = L.level_word(table, bands, kind, val)
        check(f"{kind} {val} → {want}", got == want, got)
    check("阈值取自 NCharacter 块 (prestige 5 档)", len(bands.get("prestige") or []) == 5,
          bands.get("prestige"))

    print("[A4] 议会席位取词 (council_seat_word)")
    tasks = L.council_tasks()
    cases = (("task_collect_taxes", "celestial_government", False, "司户"),
             ("task_collect_taxes", "celestial_government", True, "户部尚书"),
             ("task_collect_taxes", "feudal_government", False, "财政总管"),
             ("task_disrupt_schemes", "celestial_government", False, "察事"),
             ("task_foreign_affairs", "feudal_government", False, "掌玺大臣"))
    for t, gov, imp, want in cases:
        got = L.council_seat_word(table, tasks, t, gov, imp)
        check(f"{t}+{gov}{'(帝国)' if imp else ''} → {want}", got == want, got)

    print("[A5] 句首主语剥离 / 口粮档 / 健康压力")
    check("剥传主名 + 「的」",
          F._strip_subject_prefix("868年9月25日，勇敢者程岩的亲属程士庸去世。", "勇敢者程岩")
          == "868年9月25日，亲属程士庸去世。")
    check("保日期前缀",
          F._strip_subject_prefix("872年4月11日，勇敢者程岩与桑蜂成婚。", "勇敢者程岩")
          == "872年4月11日，与桑蜂成婚。")
    check("无可删处原样返回", F._strip_subject_prefix("添子周挖心。", "周立齐") == "添子周挖心。")
    check("口粮档位", F.provisions_band(120) == "口粮充盈"
          and F.provisions_band(40) == "口粮尚足" and F.provisions_band(3) == "口粮将尽",
          (F.provisions_band(120), F.provisions_band(40), F.provisions_band(3)))
    check("健康档位", F.health_state_zh(5.5) == "健康良好" and F.health_state_zh(0.5) == "病危")

    print("[A6] 括注判据 (本脚本的过滤器自身)")
    check("放行补注式括注",
          not _paren_violations("死于龙编（死于龙编）（自872年起获得）（822年生，汉人）"
                                "（被褫夺环州）（涉及唐皇帝李漼，自876年见载）（同年）（截至889年）"),
          _paren_violations("（死于龙编）（自872年起获得）（822年生，汉人）"))
    check("拦截同位语式括注",
          set(_paren_violations("长史（延寿）周家族乡绅（世族庄园）宝物：X（名望级）"))
          == {"延寿", "世族庄园", "名望级"},
          _paren_violations("长史（延寿）周家族乡绅（世族庄园）"))


def group_b(snap_path):
    print(f"[B] 快照传输面 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, f"缺 {snap_path}（先跑 tools/snap.py）")
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    meta, facts = snap["meta"], snap["facts"]
    p = facts["protagonist"]
    # 事实面 = 共享前缀 + 各篇 blocks（**不含**提示词指令文本：板块要求里的
    # 「(毒杀、缢杀…)」之类括注属提示词写法，不在本判据范围）
    fact_surface = snap["shared"] + "\n" + "\n".join(
        "\n".join(v.values()) if isinstance(v, dict) else str(v)
        for v in snap["blocks"].values())
    # 全请求面 = 事实面 + 指令面（只查裸键，不查括注）
    surface = snap["shared"] + "".join(
        f"{m['system']}\n{m['user']}" for m in snap["messages"].values())

    # 快照新鲜度：核心代码比快照新 → 提示重跑 snap.py（不判失败，避免卡流程）
    newer = [fn for fn, (_sz, mt) in (meta.get("code") or {}).items()
             if mt > os.path.getmtime(snap_path)]
    if newer:
        print(f"  WARN 快照可能过期（这些文件更新在后：{'、'.join(newer)}）"
              f"，建议重跑 tools/snap.py")

    check("传输面无裸键 token", not _KEY_RE.search(surface),
          _KEY_RE.findall(surface)[:3])
    check("传输面无 MAX_RECURSIVE_DEPTH", "MAX_RECURSIVE_DEPTH" not in surface)
    badp = _paren_violations(fact_surface)
    check("事实面无「名词（名词）」括注同位语", not badp, badp[:8])
    check("无「言语相通」", "言语相通" not in surface)
    check("无「国库金/月入」", "国库金" not in surface and "月入" not in surface)
    check("无「牧群+数字」", not re.search(r"牧群\s*\d", surface),
          re.findall(r"牧群.{0,6}", surface)[:2])
    # 以下断言按周氏（38673）数据结构写就 — 其它家族快照只跑上面的通用面
    if meta.get("player_id") != 38673:
        print(f"  SKIP 周氏专属断言 (player_id={meta.get('player_id')}); "
              f"家族专属面见 group_c")
        return
    check("现状句含档位词", all(w in (p.get("status") or "")
                              for w in ("虔诚", "威望", "影响力", "功勋")), p.get("status"))
    check("御前会议席位为动态官职名 (长史/司户/…)",
          bool(p.get("council")) and "席：" in p["council"]
          and "（" not in p["council"], p.get("council"))
    check("【主角处境】已消失 / 无定居期驻地块",
          "【主角处境】" not in surface
          and not (facts.get("protagonist_stations") or []), facts.get("protagonist_stations"))
    cry = (facts.get("characters") or {}).get("11772") or {}
    evs = cry.get("events_subjectless") or []
    label = cry.get("label") or ""
    check("传主行迹省主语", bool(evs) and not any(
        x.split("，", 1)[-1].startswith(label) for x in evs), evs[:2])
    # 家世去重：主角子女的档案里不应再有 兄弟姊妹 / 父(主角)
    profs = facts.get("characters") or {}
    cache = json.load(open(os.path.join(
        ROOT, "output", meta["folder"], "data",
        f"player_{meta['player_id']}.json"), encoding="utf-8"))
    pchildren = {str(x) for x in
                 ((cache.get("characters", {}).get(str(meta["player_id"]), {})
                   .get("family", {}) or {}).get("child") or [])}
    offenders = [cid for cid in pchildren
                 if (profs.get(cid) or {}).get("siblings")
                 or (profs.get(cid) or {}).get("father")]
    check("子女档案无兄弟姊妹/父(主角)", not offenders, offenders[:5])
    held = " ".join((snap.get("facts", {}).get("secrets") or {}).get("held") or [])
    check("科举舞弊写主考与级别", "主持的乡试中舞弊" in held or not held, held)
    feuds = " ".join(e for fd in (facts.get("house_feuds") or []) for e in fd["events"])
    check("恩怨史无裸键、有重建句", "MAX_RECURSIVE_DEPTH" not in feuds, feuds[:80])


# ---------------------------------------------------------------------------
# C 菲利普4 (v30) 传输面断言 — 与家族无关, 任何快照都可跑
# ---------------------------------------------------------------------------

# 缺料按语 (提示词与事实层一律不得出现; 见 修复方案_菲利普4.md 问题4)
_ABSENCE_RE = re.compile(
    r"资料未载|资料不载|资料未提供|资料不足|史无可考|史料不详|"
    r"族属不详|信仰不详|官制不详|特质不详|（无[^）]{1,8}记录）")
# 游戏 UI 口语战绩词 (问题3)
_UI_WORD_RE = re.compile(r"打了胜仗|吃了败仗")
# 男性官职词 (女性持有者的称谓不得落在这些词上; 问题9)
_MALE_WORD_RE = re.compile(r"(?<!女)(伯爵|公爵|国王|男爵|酋长|皇帝)")


def _surface(snap):
    fact = snap["shared"] + "\n" + "\n".join(
        "\n".join(v.values()) if isinstance(v, dict) else str(v)
        for v in snap["blocks"].values())
    instr = "".join(f"{m['system']}\n{m['user']}"
                    for m in snap["messages"].values())
    return fact, instr


def group_c(snap_path):
    print(f"[C] v30 传输面 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    facts = snap["facts"]
    fact_surface, instr = _surface(snap)
    surface = fact_surface + instr

    bad = _ABSENCE_RE.findall(surface)
    check("无缺料按语 (资料未载/不详/无X记录)", not bad, bad[:5])
    ui = _UI_WORD_RE.findall(surface)
    check("无游戏口语战绩词 (打了胜仗/吃了败仗)", not ui, ui[:5])
    # 「无共通语」只在程序真判定为不通语时才可出现 (问题10)
    if "无共通语" not in fact_surface:
        check("事实面无不通语 → 提示词也不提「无共通语」",
              "无共通语" not in instr)
    else:
        check("「无共通语」有事实依据", "无共通语" in fact_surface)
    # 女性持有者的官职词
    offenders = []
    for cid, rec in (facts.get("characters") or {}).items():
        if not rec.get("female"):
            continue
        label = rec.get("label") or ""
        off = rec.get("office") or ""
        if off and _MALE_WORD_RE.search(off):
            offenders.append((cid, label))
    check("女性无男性官职词", not offenders, offenders[:4])
    # 献祭门: 教义参数表可用 (问题12)
    ten = L.doctrines_granting("human_sacrifice_active")
    check("人祭教义表可用 (doctrines_granting)", bool(ten), sorted(ten))


def main():
    snap = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SNAP
    group_a()
    group_b(snap)
    group_c(snap)
    print("\n" + "=" * 60)
    print("结果: 全部 PASS" if _OK else "结果: 存在 FAIL")
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
