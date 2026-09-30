# -*- coding: utf-8 -*-
"""v87 专项回归（秒级；无熔件）: 礼仪志精简 / 男爵领地名 / 后任称谓 / 个人教义 / 删教会志。

用法：
    & tools\\py.ps1 tools\\tests\\verify_v87.py [快照路径...]
    ｜ 缺省自动取本轮三份快照: 洪氏 872.5.17 (v87_s9_hs)、教宗尼各老 870.1.1 (v87_s9_nkl)、
      洪氏 38941 873.1.1 (继任者本人档, v87_s9_succ), 存在于 output/<家族>/data/ 时逐份断言。

断言（对应 docs/方案_v87_礼仪志精简与用词.md 的 8 个问题）：
    [1] 后任/承继句无「大阿亚图拉」; 洪氏后任句为游戏自渲染名 (教宗 + 汉字世系)
    [2] `礼仪之教：` 不再出现
    [3] 无「圣所/圣髑」字样, 无 facts.holy_sites 键
    [4] 男爵领不再带层级词 (纯函数 + 快照: 无「堡」后缀的地名)
    [5] 无 jiaohui 篇 / 无 facts.church_state 键 / 无「当今之局」「教廷之势」
    [6] 个人教义为「放弃…改奉…」式; 档案行只出当时所奉
    [7] `礼仪教义：核心…条` 计数行不再出现; 允许/禁止教义逐条点名
    [8] 用词: 礼仪领袖 / 宗教热情 / 个人教义沿革; 「本礼之首」「礼仪之热」不再出现
    [附] 板块判定: 开篇拿档案、纪事拿允许/禁止 (不再同块)
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F          # noqa: E402
import localization as L   # noqa: E402
import style              # noqa: E402

_DEFAULT = (("洪氏", "v87_s9_hs.json"), ("教宗尼各老", "v87_s9_nkl.json"),
            ("洪氏", "v87_s9_succ.json"))
_OK = True


def check(name, cond, detail=""):
    global _OK
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (("  — " + detail) if (detail and not cond) else ""))
    if not cond:
        _OK = False


def _texts(snap):
    """快照里所有「进提示词」的文本 (facts + shared + blocks + messages)。"""
    out = []
    facts = snap.get("facts") or {}
    out.append(json.dumps(facts, ensure_ascii=False))
    out.append(json.dumps(snap.get("shared") or "", ensure_ascii=False))
    out.append(json.dumps(snap.get("blocks") or {}, ensure_ascii=False))
    out.append(json.dumps(snap.get("messages") or {}, ensure_ascii=False))
    return "\n".join(out)


def unit_checks():
    print("[U] 纯函数")
    check("U1 GENERIC_TIER_ZH 无 barony 项", "barony" not in L.GENERIC_TIER_ZH)
    check("U2 tier_word(barony) 不为「堡」",
          L.tier_word(L.table(), "feudal_government", "barony") != "堡")
    check("U3 _roman_ordinal_zh: 色尔爵III → 色尔爵三世",
          F._roman_ordinal_zh("教宗色尔爵III") == "教宗色尔爵三世")
    check("U4 _roman_ordinal_zh 不动汉字数字",
          F._roman_ordinal_zh("路易十四") == "路易十四")
    check("U5 灵性满足负档 = 匮乏", F._sf_word(-6) == "匮乏", F._sf_word(-6))
    check("U6 style 无 jiaohui 板块",
          "jiaohui" not in style.SECTION_TITLES
          and "jiaohui" not in style.SECTION_REQ)
    check("U7 礼仪志篇名已改口",
          style.SECTION_TITLES.get("liyi", {}).get("lead") == "开篇·所奉礼仪"
          and style.SECTION_TITLES.get("liyi", {}).get("mid") == "纪事·礼仪沿革")
    check("U8 Facts 无 church_state_lines / holy_site_lines",
          not hasattr(F.Facts, "church_state_lines")
          and not hasattr(F.Facts, "holy_site_lines"))


def snap_checks(path):
    fam = os.path.basename(os.path.dirname(os.path.dirname(path)))
    with open(path, encoding="utf-8") as fp:
        snap = json.load(fp)
    meta = snap.get("meta") or {}
    print(f"[S] {fam} pid={meta.get('player_id')} as_of={meta.get('as_of')} "
          f"({os.path.basename(path)})")
    txt = _texts(snap)
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    pid = str(meta.get("player_id"))

    # [1] 后任称谓
    succ = " ".join(facts.get("succession") or [])
    check("1a 无「大阿亚图拉」", "大阿亚图拉" not in txt)
    check("1b 无「萨比娜」当**称谓** (历任里记其枢机名属史实, 不算)",
          "萨比娜大阿" not in txt and "萨比娜公爵" not in txt)
    if fam == "洪氏" and pid == "38948":
        check("1c 后任句为游戏自渲染名 (教宗 + 汉字世系)",
              "教宗色尔爵三世" in succ, succ)

    # [2] 礼仪之教
    check("2 无「礼仪之教：」", "礼仪之教：" not in txt)
    # [3] 圣所
    check("3a 无「圣所」「圣髑」", "圣所" not in txt and "圣髑" not in txt)
    check("3b 无 facts.holy_sites 键", "holy_sites" not in facts)
    # [4] 男爵领地名
    check("4 无「堡」后缀地名 (罗/法尔法/秋田)",
          not re.search(r"(?:罗马|法尔法|秋田|揖保|维泰博|蒂沃利)堡", txt)
          and "揖保市" not in txt)
    # [5] 教会志
    check("5a 无 jiaohui 篇", "jiaohui" not in (meta.get("articles") or []))
    check("5b 无 facts.church_state 键", "church_state" not in facts)
    check("5c 无教会志词面 (当今之局/教廷之势/众望所归)",
          not any(w in txt for w in ("当今之局", "教廷之势", "众望所归",
                                     "主流之礼", "教廷之众")))
    # [6] 个人教义
    pt = " ".join(facts.get("personal_tenets") or [])
    prof = " ".join(facts.get("rite_profile") or [])
    if pid == "38948":
        check("6a 沿革写「放弃…改奉…」",
              "放弃〈买卖圣职〉" in pt and "改奉〈战争狂人〉" in pt, pt)
        check("6b 档案行只出当时所奉 (个人教义：〈战争狂人〉)",
              "个人教义：〈战争狂人〉。" in prof and "个人教义：〈买卖圣职〉" not in prof,
              prof)
    if pt:
        check("6c 沿革无并列「奉…奉…为个人教义」重复式",
              len(re.findall(r"为个人教义。", pt)) <= len(facts.get("personal_tenets") or []),
              pt)
    # [7] 计数行 / 允许禁止
    check("7a 无「礼仪教义：核心…条」计数行",
          not re.search(r"礼仪教义：核心\d+条", txt))
    check("7b 无「核心3条」「允许18条」计数",
          not re.search(r"(?:核心|允许|已知|禁止)\d+条", txt))
    rt = " ".join(facts.get("rite_tenets") or [])
    if rt:
        check("7c 允许/禁止教义逐条点名",
              "允许教义：" in rt and "禁止教义：" in rt and "〈" in rt, rt[:80])
    else:
        check("7c 允许/禁止教义逐条点名 (有 rite 时应非空)",
              not facts.get("rite_profile"), "rite_tenets 为空")
    # [8] 用词
    check("8a 无「本礼之首」", "本礼之首" not in txt)
    check("8b 无「礼仪之热」", "礼仪之热" not in txt)
    check("8c 有「礼仪领袖」(若档案有该行)",
          ("礼仪领袖" in txt) or not facts.get("rite_profile"))
    check("8d 无「仪轨与教化」", "仪轨与教化" not in txt)
    check("8e 块名 个人教义沿革 / 无 个人教义始奉",
          "个人教义始奉" not in json.dumps(blocks, ensure_ascii=False))
    # [附] 板块判定
    lead = blocks.get("liyi_lead") or {}
    mid = blocks.get("liyi_mid") or {}
    if lead or mid:
        check("附1 开篇有礼仪档案、无礼仪教义",
              ("礼仪档案" in lead) and ("礼仪教义" not in lead))
        check("附2 纪事有礼仪教义、无礼仪档案",
              ("礼仪教义" in mid) and ("礼仪档案" not in mid))
        check("附3 开篇/纪事不再同块",
              {k: v for k, v in lead.items() if k != "传主档案"}
              != {k: v for k, v in mid.items() if k != "传主档案"})


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    paths = args or [os.path.join(ROOT, "output", f, "data", n)
                     for f, n in _DEFAULT]
    unit_checks()
    found = 0
    for p in paths:
        if os.path.isfile(p):
            snap_checks(p)
            found += 1
        else:
            print(f"  [SKIP] 快照不存在: {p}")
    print()
    print("v87 断言:" + (" 全部通过" if _OK else " **有失败**")
          + f" (快照 {found} 份)")
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
