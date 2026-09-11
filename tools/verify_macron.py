# -*- coding: utf-8 -*-
"""马克龙八问题回归（快照级，秒级）：tools/verify_macron.py [快照路径]

覆盖 v31 八条修复的**传输面**断言（事实块 + 逐请求 system/user 文本）：
  1 特质分类分句（「性情…；禀赋…」）+ 履历不再出现怀孕
  2 夫妻情事不写「私通」（写同房/相恋/夫妻情笃），概览另立「夫妻之情」
  3 自指记录丢弃（全篇不得出现「A 与 A」式句）
  4 妻室情事脉络（情人档案 + 入宫日 + 私通→灵魂伴侣关系弧）
  5 牵制（主角握有 / 他人对主角）只随《阴私录》下发
  6 妻室情人身份（廷中骑士 / 阿肯人 / 克瓦语）
  7 血统隐事的当事人不作为「知情者」
  8 直辖领地折叠首府男爵领（不再与伯爵领并列）
  附带：无「家中言语」旧标签（曾被读成家世出身）

用法：先 `tools/snap.py 马克龙 38677 878.1.1 1 --pin-last-date`，再跑本脚本。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SNAP = os.path.join(ROOT, "output", "马克龙", "data",
                            "snap_38677_878.1.1_d1.json")
_OK = True
# 自指句: 「西法兰克王国公主埃芒特鲁德·加洛林与西法兰克王国公主埃芒特鲁德·加洛林」
_SELF_RE = re.compile(r"([\u4e00-\u9fff·]{2,16})与\1")


def check(name, cond, detail=""):
    global _OK
    if not cond:
        _OK = False
    print(f"  {'PASS' if cond else 'FAIL'} {name}"
          + ("" if cond else f"  | {str(detail)[:220]}"))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SNAP
    if not os.path.isfile(path):
        print(f"找不到快照: {path}\n先跑: tools\\snap.py 马克龙 38677 878.1.1 1 --pin-last-date")
        return 2
    snap = json.load(open(path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    msgs = snap.get("messages") or {}
    p = facts.get("protagonist") or {}
    shared = snap.get("shared") or ""
    all_text = "\n".join(
        [shared] + [str(v) for v in blocks.values()]
        + [m.get("system", "") + "\n" + m.get("user", "") for m in msgs.values()])
    jm = str(blocks.get("jiashi_mid") or "")
    sm = str(blocks.get("secrets_mid") or "")
    sl = str(blocks.get("secrets_lead") or "")
    sec = facts.get("secrets") or {}

    print("[1] 特质: 按类分句 + 履历无瞬时体况")
    check("主角「为人」含类别词", "性情" in (p.get("traits") or ""), p.get("traits"))
    th_all = [str(p.get("trait_history") or "")]
    th_all += [str((c or {}).get("trait_history") or "")
               for c in (facts.get("characters") or {}).values()]
    check("特质履历不含怀孕", all("怀孕" not in x for x in th_all),
          [x for x in th_all if "怀孕" in x][:2])

    print("[2] 夫妻情事不写「私通」")
    check("主角大事摘要无「与…公主…私通」",
          "与西法兰克王国公主埃芒特鲁德·加洛林私通" not in shared
          or "夫妻" in shared, shared[:200])
    check("夫妻情事用同房/夫妻情笃",
          ("夫妻情笃" in all_text) or ("同房" in all_text))
    stats = facts.get("decade_stats") or []
    check("概览另立「夫妻之情」", any("夫妻之情" in s for s in stats), stats)

    print("[3] 自指记录丢弃")
    m = _SELF_RE.search(all_text)
    check("全传输面无「A 与 A」式句", m is None, m.group(0) if m else "")

    print("[4] 妻室情事脉络")
    check("家室列传纪事含脉络块", "情事脉络" in jm, jm[:160])
    check("脉络含关系弧 (私通→灵魂伴侣)",
          "私通" in jm and "灵魂伴侣" in jm)

    print("[5] 牵制 (仅在《阴私录》)")
    check("阴私录含「干了我老婆」强牵制", "干了我老婆" in sm, sm[:200])
    check("阴私录含家主牵制归并行", "家主" in sm)
    check("牵制不进《本纪》", "强牵制" not in str(blocks.get("benji_mid") or ""))
    check("hooks_held 已入 facts", bool(sec.get("hooks_held")), list(sec.keys()))
    # v33: 方向在槽号 —— 该档「干了我老婆」四条**全部**是主角自己的牵制
    # (opinions 的 xiangyongletadeqizi_opinion 逐条指向「通奸者→丈夫=主角」),
    # 不得再出现「他人握有对主角的干了我老婆」式反向句
    _over = list(sec.get("hooks_over") or [])
    check("「干了我老婆」不写作他人对主角的牵制 (v33 方向修正)",
          not any("干了我老婆" in x for x in _over), _over[:3])
    _held = " ".join(sec.get("hooks_held") or [])
    check("「干了我老婆」仍在主角握有之列", "干了我老婆" in _held, _held[:200])

    print("[6] 妻室情人身份")
    check("乔乔身份: 廷中骑士", "廷中骑士" in jm)
    check("乔乔族属: 阿肯人", "阿肯人" in jm)
    check("乔乔语言: 克瓦语", "克瓦语" in jm)
    check("录入宫日", "在主角廷中" in jm)

    print("[7] 隐事知情者")
    bad = []
    for ln in (sl + "\n" + sm).split("\n"):
        if ("血统有争" in ln or "血脉存疑" in ln) and "知情者" in ln:
            bad.append(ln)
    check("血统隐事不把当事人写作知情者", not bad, bad[:1])

    print("[8] 直辖领地折叠")
    dom = p.get("domain") or ""
    check("首府男爵领不并列", ("波城男爵领" not in dom), dom)
    check("直辖计数与列出条数一致",
          int(p.get("domain_count") or 0) == len([x for x in dom.split("、") if x]),
          f"{p.get('domain_count')} vs {dom}")

    print("[附带] 家世口径")
    check("无「家中言语」旧标签", "家中言语" not in all_text)

    print("\n结果:", "全部 PASS" if _OK else "存在 FAIL")
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
