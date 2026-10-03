# -*- coding: utf-8 -*-
"""v95 回归 (秒级; 不载熔件): 洪氏2 六问题 + 追加的教皇教名。

用法: & tools\\py.ps1 tools\\tests\\verify_v95.py [快照...]
     缺省取 output/洪氏2/data/snap_v95_final.json 与 snap_v95_gf_d3.json。

用户 2026-10-02 六问 + 追加一问:
  1 终传未写「对教宗宣战是为扶立对立教宗」—— 记忆 `war_cb` 落
    `war_memory_cb_fallback`(游戏不为该 CB 写专用键), 真 CB 只在战争进行时的
    `wars.active_wars[].casus_belli.type`。修法: 缓存逐档闩存 `war_history`
    (cache_lib._latch_war_history + tools/backfill_war_history.py), 事实层回查
    (facts._war_cb_from_history) + 项目措辞表 (style.WAR_CB_ZH) + pam 专用句。
  2 《礼仪志》第三板块「枢机团与教宗选举」(facts.papal_election_lines)。
  3 本纪/总纲的主角档案去掉「个人教义」演变 (与《礼仪志》重复)。
  4 教育记忆隔日重复折一 (facts._dedupe_education_memories)。
  5 承继句补死法 (「于当日溺死」)。
  6 连坐处死由日级改**人级**判据 (facts.purged_houses)。
  7 教皇「教名」与「本名」并写 (facts.regnal_birth_name) + 转正后不再误标对立教宗。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402
import style as S        # noqa: E402
import biography as bio  # noqa: E402

_OK = True
_NEG = re.compile(r"不要|请勿|禁止|避免|切勿|不得|严禁|不可|不再|勿")


def check(name, cond, detail=""):
    global _OK
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (("  — " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _OK = False


# ---------------------------------------------------------------------------
# 一、纯函数
# ---------------------------------------------------------------------------
class _WarStub:
    """回查逻辑只读 `cache["war_history"]` 与 `table`。"""

    def __init__(self, rows):
        self.cache = {"war_history": rows}
        self.table = {}


WAR_ROWS = [
    {"id": "721420422", "seen": "946.1.1", "start_date": "945.12.27",
     "cb": "pam_challenge_hof_cb", "attacker": 44503, "defender": 70983,
     "atk_parts": [44503, 94644], "dfd_parts": [70983, 81218]},
    {"id": "1", "seen": "933.1.1", "start_date": "933.9.15",
     "cb": "claim_cb", "attacker": 44503, "defender": 60242,
     "atk_parts": [43767, 44503], "dfd_parts": [42587, 60242]},
]


def unit_checks():
    print("\n[一] 纯函数")
    f = _WarStub(WAR_ROWS)
    check("U1a fallback 回查命中真 CB (日期 ±2 天内)",
          F._war_cb_from_history(f, 44503, 70983, "945.12.28") == "pam_challenge_hof_cb")
    check("U1b 攻守方向反过来也命中",
          F._war_cb_from_history(f, 70983, 44503, "945.12.28") == "pam_challenge_hof_cb")
    check("U1c 超出日期容差不命中",
          F._war_cb_from_history(f, 44503, 70983, "946.1.5") == "")
    check("U1d 已映射的键原样保留 (不回查)",
          F._war_cb_resolved(f, "war_memory_cb_claim", 44503, 60242, "933.9.16")
          == "war_memory_cb_claim")
    check("U1e fallback 才回查",
          F._war_cb_resolved(f, "war_memory_cb_fallback", 44503, 70983, "945.12.28")
          == "pam_challenge_hof_cb")
    check("U1f fallback 本身仍被丢弃 (不写「战争」)",
          F._war_cb_word(f, "war_memory_cb_fallback") == "")
    check("U1g 措辞表无空值/无模板串/无负向词",
          all(v and "[" not in v and "$" not in v and not _NEG.search(v)
              for v in S.WAR_CB_ZH.values()))
    check("U1h 措辞表不覆盖记忆键空间",
          not any(k.startswith("war_memory_cb_") for k in S.WAR_CB_ZH))

    # 问4: 教育记忆归并 (合成缓存)
    def _m(t, d, guardian):
        return {"type": t, "creation_date": d,
                "participants": {"guardian": guardian},
                "vars": [{"flag": "education_host_faith", "identity": 12}]}
    cache = {"characters": {"1": {"memories": [_m("childhood_education_guardian", "885.8.7", 5),
                                                _m("childhood_education_guardian", "885.8.8", 9),
                                                _m("childhood_education_guardian", "895.1.1", 7)]},
                            "2": {"memories": [_m("childhood_education_guardian", "900.1.1", 5)]}}}
    n = F._dedupe_education_memories(cache)
    check("U2a 隔日重复折 1 条 (业师不同也折)", n == 1, n)
    check("U2b 保留最早那条 (真监护人)",
          [m["creation_date"] for m in cache["characters"]["1"]["memories"]]
          == ["885.8.7", "895.1.1"],
          [m["creation_date"] for m in cache["characters"]["1"]["memories"]])
    check("U2c 幂等 (再跑折 0 条)", F._dedupe_education_memories(cache) == 0)

    # 问6: 人级诛灭判据 (桩: 一顶世族庄园当日被销毁, 持有人当日被处决)
    fp = F.Facts.__new__(F.Facts)
    fp._lt = {"100": {"key": "c_nf_ki", "history": {"943.11.3": {"type": "destroyed", "holder": 7}}},
              "101": {"key": "c_nf_other", "history": {"943.11.3": {"type": "destroyed", "holder": 8}}}}
    fp._chars = {"7": {"dynasty_house": 5343}, "8": {"dynasty_house": 9999},
                 "9": {"dynasty_house": 9}}
    fp.cache = {}
    fp.melt = {"opinions": {"active_opinions": []}}
    fp._purge_houses_map = {}
    fp._devour_bones_map = {}
    fp._devour_bones = lambda: {}                                  # noqa: E731
    fp._purge_gov_ok = lambda kid, d: True                         # noqa: E731
    # 当日被本行刑者处决者: 7 (纪氏) 与 9 (无关族); 8 的庄园销毁但当日未被处决
    fp._chars.update({
        "7": {"dynasty_house": 5343, "dead_data": {"reason": "death_execution",
                                                   "killer": 5, "date": "943.11.3"}},
        "8": {"dynasty_house": 9999, "dead_data": {"reason": "death_execution",
                                                   "killer": 5, "date": "944.1.1"}},
        "9": {"dynasty_house": 9, "dead_data": {"reason": "death_execution",
                                                "killer": 5, "date": "943.11.3"}},
    })
    ph = fp.purged_houses(5)
    check("U3a 只认「庄园销毁且持有人当日被处决」的族",
          {d: sorted(hs) for d, hs in ph.items()} == {"943.11.3": [5343]},
          {d: sorted(hs) for d, hs in ph.items()})
    check("U3b 同族被杀者判连坐", fp.is_family_purge(5, 7, "943.11.3") is True)
    check("U3c 同日异族被杀者不判连坐", fp.is_family_purge(5, 9, "943.11.3") is False)
    check("U3d 庄园次日才被处决者不参与 (族未入列)", fp.is_family_purge(5, 8, "944.1.1") is False)
    check("U3e 族级行只数被诛族",
          [e["text"] for e in fp.family_purge_events(5)]
          == ["诛灭世族 1 族，处死家主 1 人，剩余残党被流放"]
          or all("1 族" in e["text"] for e in fp.family_purge_events(5)),
          [e["text"] for e in fp.family_purge_events(5)])

    # 问2: 第三板块要求随素材生成
    r0 = bio._liyi_req({"rite_profile": ["所奉礼仪：拜上帝会。"], "holy_orders": ["h"]})
    check("U4a 无枢机素材时 tail 走兜底句",
          "tail" in r0 and "枢机" in (r0["tail"] or "")
          and "枢机" not in (r0["focus"] or ""), r0["focus"])
    r1 = bio._liyi_req({"rite_profile": ["所奉礼仪：拜上帝会。"],
                        "papal_election": ["枢机团：在位枢机 33 席，虚悬 19 席。",
                                           "本朝封臣入枢机者 6 人：阿尔巴诺枢机洪思忠。",
                                           "现任教宗：亚纳大削三世，本名恂，自946年2月24日起。",
                                           "下届选举：33 位枢机推举 3 人 —— 甲 12 票；第一顺位为甲。",
                                           "派别：甲属虔诚派。",
                                           "奔走：26 位枢机在替甲奔走。"]})
    check("U4b 有枢机素材时 tail 逐条索要",
          all(t in r1["tail"] for t in ("席次与空缺", "入枢机者", "现任教宗",
                                       "下届推举", "派别", "奔走")), r1["tail"])
    check("U4c 题面点出枢机团与下届教宗选举",
          "枢机" in r1["focus"] and "教宗选举" in r1["focus"], r1["focus"])
    check("U4d 生成的要求无负向禁令词 (no-negative-prompts)",
          not any(_NEG.search(v or "") for v in
                  (r0["lead"], r0["mid"], r0["tail"], r0["focus"],
                   r1["lead"], r1["mid"], r1["tail"], r1["focus"])))
    check("U4e 板块名与板块键齐备",
          S.SECTION_TITLES["liyi"].get("tail") == "纪事·枢机团与教宗选举"
          and bool(S.SECTION_REQ["liyi"].get("tail")))
    check("U4f `_liyi_has_tail` 只看素材",
          bio._liyi_has_tail({"papal_election": ["x"]}) is True
          and bio._liyi_has_tail({}) is False)


# ---------------------------------------------------------------------------
# 二、快照
# ---------------------------------------------------------------------------
def _blob(facts):
    return json.dumps(facts, ensure_ascii=False)


def _block_text(blocks, key=None):
    out = []
    for k, v in (blocks or {}).items():
        if key and k != key:
            continue
        if isinstance(v, dict):
            for bv in v.values():
                if isinstance(bv, str):
                    out.append(bv)
    return "\n".join(out)


def _lines_with(text, kw):
    return [x.strip() for x in (text or "").split("\n") if kw in x]


PURGE_TRUE = ("夷男", "夏元卿", "曾于亲方", "卫成", "纪宣来子", "隐岐真子",
              "徐华", "徐恕", "李颛")
PURGE_FALSE = ("橘教通", "大江元贤", "和气干成", "白狼景修", "藤原显忠", "橘度义",
               "曾峄", "源雪", "唐弥大", "橘睿子", "多摩政明", "隐岐业行", "魏九龄",
               "藤原仁子", "苫田延光", "石忠恕", "马因", "刘伯成", "李宗愈", "高尚",
               "郭季孙", "王翱", "吴宗古")


def final_checks(path):
    print(f"\n[二] 终传面 {os.path.basename(path)}")
    d = json.load(open(path, encoding="utf-8"))
    facts = d.get("facts") or {}
    blocks = d.get("blocks") or {}
    blob = _blob(facts) + "\n" + _block_text(blocks)
    tl = [x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
          for x in (facts.get("timeline") or [])]

    check("S0 快照 schema>=6 (v95 传输面)", int(d.get("schema") or 0) >= 6,
          d.get("schema"))

    # 问1
    war = [x for x in tl if "克肋孟" in x and ("开战" in x or "兴兵" in x)]
    check("S1 对教宗那一战写出「以扶立对立教宗为名」",
          any("以扶立对立教宗为名" in x for x in war), war[:1])
    check("S1b 全篇无裸本地化模板 (|[A-Z]| 形态)",
          not re.search(r"\|E?\]|\|E\]", blob) and "[seize_peripheral" not in blob,
          re.findall(r"\[[^\]]{0,40}\]", blob)[:3])
    check("S1c 全篇无 fallback 通用词泄漏 (「战争」不作宣战理由)",
          "以战争" not in blob and "以战争向" not in blob)

    # 问2
    tail = (blocks.get("liyi_tail") or {})
    check("S2 终传《礼仪志》有第三板块 (liyi_tail)",
          "枢机团与教宗选举" in tail, sorted(tail))
    pe = "\n".join(str(x) for x in (tail.get("枢机团与教宗选举") or "").split("\n"))
    check("S2b 第三板块六行俱全",
          all(k in pe for k in ("枢机团：在位枢机", "本朝封臣入枢机者", "现任教宗",
                                "下届选举", "派别", "奔走")), pe[:200])
    check("S2c 封臣枢机逐人给出席位名与候选声望",
          "阿尔巴诺枢机洪思忠" in pe and "教宗候选声望" in pe, pe[:200])
    check("S2d 现任教宗并写本名 (v95 问题7)",
          "现任教宗：亚纳大削三世，本名恂" in pe, pe[:200])
    check("S2e 礼仪领袖并写本名",
          "礼仪领袖：教宗亚纳大削三世，本名恂" in _block_text(blocks, "liyi_lead"),
          _lines_with(_block_text(blocks, "liyi_lead"), "礼仪领袖")[:1])
    check("S2g 第三板块无括注 (v55 括注自然语言化)",
          "（本名" not in pe and "（教宗候选声望" not in pe
          and "，本名恂" in pe and "教宗候选声望" in pe, pe[:200])
    check("S2f 转正后不再误标对立教宗 (终传无「罗马对立教宗」)",
          "罗马对立教宗" not in blob)

    # 问3 / 问5
    prof = (blocks.get("benji_lead") or {}).get("传主档案") or ""
    check("S3 主角档案不再写「个人教义」", "个人教义" not in prof)
    check("S3b 《礼仪志》仍承担个人教义 (当前 + 沿革)",
          "个人教义：" in _block_text(blocks, "liyi_lead")
          and "个人教义沿革" in (blocks.get("liyi_mid") or {}))
    succ = _lines_with(prof, "承继：")
    check("S5 承继句含前任传主死法 (「于当日溺死」)",
          bool(succ) and "溺死" in succ[0] and "崩于当日" not in succ[0], succ[:1])

    # 问4
    check("S4 教育记忆不再隔日出两条 (885年8月8日 0 命中)",
          "885年8月8日" not in blob and "885年6月16日" not in blob)

    # 问6
    purged_lines = _lines_with(_block_text(blocks), "连坐处死")
    check("S6a 连坐处死行只含真被诛者",
          bool(purged_lines)
          and not any(n in ln for ln in purged_lines for n in PURGE_FALSE),
          [ln for ln in purged_lines if any(n in ln for n in PURGE_FALSE)][:3])
    check("S6b 真被诛者都在连坐名单里",
          all(any(n in ln for ln in purged_lines) for n in PURGE_TRUE),
          [n for n in PURGE_TRUE if not any(n in ln for ln in purged_lines)])
    fam = _lines_with(_block_text(blocks), "诛灭")
    check("S6c 族级行按族计数 (不再「十六族 / 9 族」)",
          not any(("十六族" in x) or (" 9 族" in x) or ("16 族" in x) for x in fam),
          fam[:3])
    check("S6d 943.11.3 只诛纪氏一族",
          any("943年11月3日诛灭纪氏 1 族" in x for x in fam),
          [x for x in fam if "943年11月3日" in x][:1])
    # v95-6b: 同日同人的「囚禁…当日处决」节点与原文「处决了X」不得并存
    # (人级收窄后 943.11.3 隐岐业行一度两行同现, 成稿读成「处决X并囚之当日处决」)
    dup = []
    for h in (facts.get("house_feuds") or []):
        by_day = {}
        for ln in h.get("events") or []:
            m = re.match(r"(\d+年\d+月\d+日)(.*)", str(ln))
            if not m:
                continue
            by_day.setdefault(m.group(1), []).append(m.group(2))
        for _d, rows in by_day.items():
            killed = set()
            for r in rows:
                mm = re.search(r"处决了(.+)$", r)
                if mm:
                    killed.add(mm.group(1).strip())
            for r in rows:
                if "当日处决" in r and "囚禁" in r:
                    for nm in killed:
                        if nm and nm in r:
                            dup.append(f"{h.get('house_label')} {_d} {nm}")
    check("S6e 囚禁节点不与同日处决句重复 (v95-6b)", not dup, dup[:3])


def d3_checks(path):
    print(f"\n[三] 十年档面 {os.path.basename(path)}")
    d = json.load(open(path, encoding="utf-8"))
    facts = d.get("facts") or {}
    blocks = d.get("blocks") or {}
    blob = _blob(facts) + "\n" + _block_text(blocks)
    check("S7 十年档无第三板块 (选举数据无 history ⇒ 时效闸)",
          "liyi_tail" not in blocks, sorted(blocks))
    check("S7b facts.papal_election 为空", not (facts.get("papal_election") or []))
    check("S7c 935 档对立教宗行仍在 (在位者未被误删)",
          any(str(x).startswith("对立教宗：") for x in (facts.get("rite_profile") or [])),
          facts.get("rite_profile"))
    prof = (blocks.get("benji_lead") or {}).get("传主档案") or ""
    check("S8 十年档主角档案同样无「个人教义」", "个人教义" not in prof)
    check("S8b 十年档承继句同样有死法",
          any("溺死" in x for x in _lines_with(prof, "承继：")))
    check("S8c 十年档教育记忆无隔日重复 (885年6月16日 0 命中)",
          "885年6月16日" not in blob)


def main():
    unit_checks()
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    data = os.path.join(ROOT, "output", "\u6d2a\u6c0f2", "data")
    if not paths:
        for nm, fn in (("snap_v95_final.json", final_checks),
                       ("snap_v95_gf_d3.json", d3_checks)):
            p = os.path.join(data, nm)
            if os.path.exists(p):
                fn(p)
            else:
                print(f"  [SKIP] 缺快照 {nm}")
    else:
        for p in paths:
            if "d1" in p or "d2" in p or "d3" in p:
                d3_checks(p)
            else:
                final_checks(p)
    print("\n" + ("全部通过" if _OK else "**有 FAIL**"))
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
