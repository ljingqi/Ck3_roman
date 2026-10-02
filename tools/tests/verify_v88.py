# -*- coding: utf-8 -*-
"""v88 专项回归 (秒级; 不载熔件): 篇目上限与序号 / 宝物「曾入外族之手」判据 / 礼仪志改造。

对应 `docs/方案_v88_三问题.md` 的三问与用户 2026-10-01 的六项拍板:
    [1] `_cn_index` 汉字序数到 99 (旧稿 `CN_NUMS` 只有 9 字 ⇒ 第 10 篇抛 IndexError);
        篇目上限 `ARTICLE_MAX=10` 与按重要性出篇 (`_apply_article_cap`);
        好友/仇人列传按行迹条数出篇 (`SUBJECT_ART_MIN_EVENTS`);
    [2] 宝物甲档「曾入外族之手」**未知宗族按外族计** (`Facts._artifact_cross_dyn`);
        跨十年去重口径不变 (先前十年写过的后续不写, 终传重新进池);
    [3] 《礼仪志》删「允许/禁止教义」, 纪事改「礼仪沿革 + 禁忌个人信条 + 本礼教义沿革」
    (v89 问题4/5: 修会移入开篇「修会」块, 门下教众删除);
        开篇加「所立修会」; 个人教义进各角色档案行; 宗教面无实据则整篇不出。

用法:
    & tools\\py.ps1 tools\\tests\\verify_v88.py [快照路径...]
    ｜ 缺省取 output/洪氏2/data/ 的 snap_38957_888.1.1_d2.json 与
      snap_38957_898.1.1_d3.json (schema>=4 的新快照)。
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

_DEFAULT = (
    os.path.join(ROOT, "output", "洪氏2", "data", "snap_38957_878.1.1_d1.json"),
    os.path.join(ROOT, "output", "洪氏2", "data", "snap_38957_888.1.1_d2.json"),
    os.path.join(ROOT, "output", "洪氏2", "data", "snap_38957_898.1.1_d3.json"),
    # v89: 用当前代码重建的三份 (新传输面) + 终传
    os.path.join(ROOT, "output", "洪氏2", "data", "snap_v89_d1.json"),
    os.path.join(ROOT, "output", "洪氏2", "data", "snap_v89_d3.json"),
    os.path.join(ROOT, "output", "洪氏2", "data", "snap_v89_final.json"),
)
_OK = True
_CN = "一二三四五六七八九"


def check(name, cond, detail=""):
    global _OK
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (("  — " + detail) if (detail and not cond) else ""))
    if not cond:
        _OK = False


def unit_checks():
    print("[U] 纯函数")
    # [1] 汉字序数
    exp = {1: "一", 2: "二", 9: "九", 10: "十", 11: "十一", 19: "十九",
           20: "二十", 21: "二十一", 99: "九十九"}
    bad = [f"{k}->{bio._cn_index(k)}" for k, v in exp.items()
           if bio._cn_index(k) != v]
    check("U1a _cn_index 1..99 正确", not bad, "；".join(bad))
    check("U1b _cn_index 对第 10 篇不再越界 (旧稿正是此处崩)",
          bio._cn_index(10) == "十" and "一二三四五六七八九"[9:10] == "")
    check("U1c _cn_index 边界输入不抛异常",
          all(isinstance(bio._cn_index(x), str)
              for x in (0, -1, "x", None, 100, 1000)))
    # [1] 上限与重要性
    check("U2 篇目上限 = 10", bio.ARTICLE_MAX == 10, str(bio.ARTICLE_MAX))
    arts = [{"key": k, "title": f"T{k}"} for k in
            ("benji", "jiashi", "assassins", "secrets", "friend", "enemy",
             "feuds", "artifacts", "liyi", "chaoju", "youxia", "qizu", "qunying")]
    kept = bio._apply_article_cap(list(arts))
    check("U3a 超限时裁到上限", len(kept) == 10, str(len(kept)))
    check("U3b 裁掉的是优先级最低的三篇",
          [a["key"] for a in kept] == [a["key"] for a in arts[:10]],
          str([a["key"] for a in kept]))
    check("U3c 保持原有相对次序 (挑选不重排)",
          [a["key"] for a in kept] == [k for k in
                                       ("benji", "jiashi", "assassins", "secrets",
                                        "friend", "enemy", "feuds", "artifacts",
                                        "liyi", "chaoju")])
    ten = [{"key": k, "title": "T"} for k in
           ("benji", "friend", "enemy", "jiashi", "feuds", "artifacts", "liyi",
            "assassins", "qizu", "secrets")]
    check("U3d 恰好 10 篇时逐字不动",
          [a["key"] for a in bio._apply_article_cap(list(ten))]
          == [a["key"] for a in ten])
    # [1] 列传出篇门槛
    f = {"characters": {"1": {"events": ["x", "y", "z"]},
                        "2": {"events": ["x", "y"]}, "3": {}}}
    check("U4 好友/仇人列传门槛 (≥3 条行迹)",
          bio._subject_has_material(f, 1) and not bio._subject_has_material(f, 2)
          and not bio._subject_has_material(f, 3)
          and not bio._subject_has_material(f, None))
    # [3] 礼仪志门槛
    base = {"rite": "罗马礼", "rite_profile": ["所奉礼仪：罗马礼。"]}
    check("U5a 无改礼/无更替/无修会 ⇒ 不出篇",
          not bio._liyi_has_material(dict(base)))
    check("U5b 有改礼 ⇒ 出篇",
          bio._liyi_has_material(dict(base, rite_history=["a", "b"])))
    check("U5c 有信条更替 ⇒ 出篇",
          bio._liyi_has_material(dict(base, personal_tenets=["a", "b"])))
    check("U5d 有亲立修会 ⇒ 出篇",
          bio._liyi_has_material(dict(base, holy_orders=["880年，他立x。"])))
    check("U5e 纪事门槛: 修会/个人教义沿革/改礼/教义更替任一即成立 (v90)",
          bio._liyi_has_mid(dict(base, holy_orders=["x"]))
          and bio._liyi_has_mid(dict(base, personal_tenets=["a", "b"]))
          and bio._liyi_has_mid(dict(base, rite_history=["a", "b"]))
          and bio._liyi_has_mid(dict(base, rite_tenet_changes=["x"]))
          and not bio._liyi_has_mid(dict(base)))
    # v96 (问题1/2): 「禁忌个人信条」整块删 —— 该键（若旧数据仍在）不再构成门槛
    check("U5f 禁忌个人信条已不作门槛 (v96 整块删)",
          not bio._liyi_has_mid(dict(base, forbidden_tenets=["x"]))
          and not bio._liyi_has_material(dict(base, forbidden_tenets=["x"])))
    # [3] style 文本
    # v89 (问题4/5): 修会整块移入开篇、门下教众删除 ⇒ 纪事改名「纪事·礼仪与教义沿革」
    check("U6 纪事板块名已改「纪事·礼仪与教义沿革」",
          style.SECTION_TITLES.get("liyi", {}).get("mid") == "纪事·礼仪与教义沿革")
    req = style.SECTION_REQ.get("liyi", {}).get("mid") or ""
    check("U6b 纪事要求句已无「允许什么、禁止什么」",
          "允许什么" not in req and "禁止什么" not in req)
    check("U6c 提示词无负向禁令词 (no-negative-prompts)",
          not re.search(r"不要|请勿|勿|禁止|避免|切勿|不得|别 |严禁|不可|不再|除非",
                        req))
    # [2] 宝物判据
    fk = F.Facts.__new__(F.Facts)          # 不跑 __init__, 只测纯函数分支
    check("U7 _artifact_cross_dyn 存在且是方法",
          callable(getattr(F.Facts, "_artifact_cross_dyn", None)))


def _texts(snap):
    return "\n".join([json.dumps(snap.get("facts") or {}, ensure_ascii=False),
                      json.dumps(snap.get("blocks") or {}, ensure_ascii=False),
                      json.dumps(snap.get("messages") or {}, ensure_ascii=False)])


def snap_checks(path):
    with open(path, encoding="utf-8") as fp:
        snap = json.load(fp)
    meta = snap.get("meta") or {}
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    keys = list(meta.get("articles") or [])
    print(f"[S] pid={meta.get('player_id')} as_of={meta.get('as_of')} "
          f"decade={meta.get('decade')} ({os.path.basename(path)})")
    check("S0 快照 schema>=4 (v88 传输面)", int(snap.get("schema") or 1) >= 4,
          str(snap.get("schema")))
    # v89: 只有用 v89 代码重建的快照才断言 v89 传输面 (旧快照是历史基线)
    _v89 = "rite_tenet_changes" in facts
    txt = _texts(snap)
    # [3] 删块
    check("S1 facts 无 rite_tenets 键", "rite_tenets" not in facts)
    check("S2 无「允许教义：」「禁止教义：」", "允许教义" not in txt and "禁止教义" not in txt)
    if int(snap.get("schema") or 1) >= 7:
        # v96 (问题1/2): 「禁忌个人信条」整块删 ⇒ 该键与那块都不再存在
        check("S3 新素材键齐备 (v96)",
              all(k in facts for k in ("holy_orders", "rite_tenet_changes",
                                       "personal_tenets")),
              str([k for k in ("holy_orders", "rite_tenet_changes",
                               "personal_tenets") if k not in facts]))
        check("S3c 禁忌个人信条键已删 (v96)", "forbidden_tenets" not in facts)
        # 只查《礼仪志》三块 —— 「禁忌个人信条」也是**游戏**给该秘密类型的名字
        # (secrets_l_simp_chinese.yml:20), 《阴私录》照写不算错。
        check("S3d 礼仪志的禁忌个人信条块已删 (v96)",
              all("禁忌个人信条" not in (blocks.get(_k) or {})
                  for _k in ("liyi_lead", "liyi_mid", "liyi_tail")),
              str([_k for _k in ("liyi_lead", "liyi_mid", "liyi_tail")
                   if "禁忌个人信条" in (blocks.get(_k) or {})]))
        check("S3b 门下教众键已删 (v89 问题5)", "vassal_tenets" not in facts)
    elif _v89:
        check("S3 新素材键齐备 (v89)",
              all(k in facts for k in ("holy_orders", "forbidden_tenets",
                                       "rite_tenet_changes", "personal_tenets")),
              str([k for k in ("holy_orders", "forbidden_tenets",
                               "rite_tenet_changes", "personal_tenets")
                   if k not in facts]))
        check("S3b 门下教众键已删 (v89 问题5)", "vassal_tenets" not in facts)
    else:
        check("S3 新素材键齐备 (v88 基线)",
              all(k in facts for k in ("holy_orders", "forbidden_tenets",
                                       "vassal_tenets", "personal_tenets")),
              str([k for k in ("holy_orders", "forbidden_tenets", "vassal_tenets",
                               "personal_tenets") if k not in facts]))
    # [1] 篇目
    check("S4 篇目数 ≤ ARTICLE_MAX", len(keys) <= bio.ARTICLE_MAX,
          f"{len(keys)} 篇: {keys}")
    art = [{"key": k, "title": f"T{k}", "focus": ""} for k in keys]
    try:
        msgs = bio.build_intro_messages(facts, {"max_tokens": 1500}, art)
        n = len(keys)
        want = bio._cn_index(n)
        check(f"S5 总纲篇目预告可生成 (n={n}, 末项 {want}、《...》)",
              f"{want}、《" in msgs[1]["content"], msgs[1]["content"][:200])
    except Exception as e:                                    # noqa: BLE001
        check("S5 总纲篇目预告可生成", False, f"{type(e).__name__}: {e}")
    # [3] 礼仪志块面
    lead = blocks.get("liyi_lead") or {}
    mid = blocks.get("liyi_mid") or {}
    if lead or mid:
        if int(snap.get("schema") or 1) >= 5:
            # v90 (问题5, 用户 2026-10-02 拍板): 开篇只留「礼仪档案」;
            # 「个人教义沿革」与「修会」移入纪事 ⇒ 本志恒有两个板块
            _lead_ok = {"传主档案", "礼仪档案"}
            _mid_ok = {"传主档案", "个人教义沿革", "修会", "礼仪沿革",
                       "禁忌个人信条", "本礼教义沿革"}
        elif _v89:
            # v89 (问题4/5): 修会块改「修会」并留在开篇; 纪事加「本礼教义沿革」、删「门下教众」
            _lead_ok = {"传主档案", "礼仪档案", "个人教义沿革", "修会"}
            _mid_ok = {"传主档案", "礼仪沿革", "禁忌个人信条", "本礼教义沿革"}
        else:
            _lead_ok = {"传主档案", "礼仪档案", "个人教义沿革", "所立修会"}
            _mid_ok = {"传主档案", "礼仪沿革", "禁忌个人信条", "门下教众"}
        check("S6a 开篇只含开篇类块", set(lead) <= _lead_ok, str(list(lead)))
        check("S6b 纪事只含纪事类块 (无礼仪档案)",
              set(mid) <= _mid_ok, str(list(mid)))
        if int(snap.get("schema") or 1) >= 5:
            check("S6c 礼仪志必有两个板块 (修会与个人教义沿革在纪事)",
                  bool(mid) and
                  (not (facts.get("holy_orders") or []) or "修会" in mid)
                  and (not (facts.get("personal_tenets") or [])
                       or "个人教义沿革" in mid)
                  and "修会" not in lead, str(list(mid)))
    # [3] 门下教众 (v88 基线) / 修会行 (v89)
    if _v89:
        ho = facts.get("holy_orders") or []
        check("S7 修会行 ≤ 6 行", len(ho) <= 6, str(len(ho)))
        if ho:
            check("S7b 每行含「他立」或「在其领地之内」或「庇护者」",
                  all(("他立" in x or "在其领地之内" in x or "庇护者" in x)
                      for x in ho), ho[0][:80])
    else:
        vt = facts.get("vassal_tenets") or []
        check("S7 门下教众 ≤ 12 行 (v88 基线, 常量已随 v89 删除)",
              len(vt) <= 12, str(len(vt)))
    # [3] 个人教义进档案
    profs = facts.get("characters") or {}
    n_pt = sum(1 for v in profs.values()
               if isinstance(v, dict) and v.get("personal_tenets"))
    check("S8 个人教义已进角色档案 (≥1 人)", n_pt >= 1, f"{n_pt} 人")
    # v95 (问题3, 用户 2026-10-02 拍板「整行删去」): 主角档案不再写「个人教义」——
    # 那一行是 `personal_tenet_lines` 的**沿革**，与《礼仪志》开篇的当前所奉 +
    # 纪事的「个人教义沿革」重复 (终传总纲据此写出「个人教义更迭尤繁…」)。
    # v95 之前的快照 (schema<6) 仍是旧口径, 故按 schema 分支。
    if int(snap.get("schema") or 0) >= 6:
        check("S8b 主角档案不再写个人教义 (v95 问题3: 与《礼仪志》重复)",
              not (facts.get("protagonist") or {}).get("personal_tenets"))
        check("S8c 主角的个人教义仍由《礼仪志》承担 (facts.personal_tenets 未删)",
              bool(facts.get("personal_tenets"))
              or not (facts.get("rite_profile") or []))
    else:
        check("S8b 主角档案含个人教义 (v95 前口径)",
              bool((facts.get("protagonist") or {}).get("personal_tenets")))
    # [2] 宝物 (洪氏2 专项): v88 判据修好后的**跨十年分配**
    # —— 十字架 871 年得, 归第 1 个十年; 秘法直指 880 年得, 归第 2 个十年;
    #    用户在 P2 拍板「先前十年写过的后续不写, 只有终传重新进池」, 故第 2 个十年
    #    之后不再重复十字架, 终传才收全量。
    if str(meta.get("player_id")) == "38957":
        _ao = str(meta.get("as_of") or "")
        _names = " ".join(facts.get("family_artifacts") or [])
        if _ao.startswith("878"):
            check("S9a 第 1 个十年《宝物志》含耶路撒冷十字架 (v88 cross 判据修好)",
                  "耶路撒冷十字架" in _names, _names[:200])
            check("S9a2 第 1 个十年无《礼仪志》(只始奉、无改礼 ⇒ 不出篇)",
                  "liyi" not in keys, str(keys))
        if _ao.startswith("888"):
            check("S9b 第 2 个十年含秘法直指、不重复第 1 个十年写过的十字架",
                  "秘法直指" in _names and "耶路撒冷十字架" not in _names,
                  _names[:200])
        if _ao.startswith("898"):
            check("S9c 第 3 个十年《宝物志》≥4 件 (跨十年去重后)",
                  len(facts.get("family_artifacts") or []) >= 4,
                  str(len(facts.get("family_artifacts") or [])))
            check("S9c2 898 年两所修会都在 (880 立 / 891 立)",
                  len(facts.get("holy_orders") or []) == 2,
                  str(facts.get("holy_orders")))
            if _v89:
                _tcs = facts.get("rite_tenet_changes") or []
                check("S9c3 898 年《礼仪志》纪事含 887 年的本礼教义更替",
                      "本礼教义沿革" in mid
                      and any("887年起" in x and "换成" in x for x in _tcs),
                      json.dumps(_tcs, ensure_ascii=False)[:200])


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
    print("v88 断言:" + (" 全部通过" if _OK else " **有失败**") + f" (快照 {found} 份)")
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
