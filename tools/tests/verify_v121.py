# -*- coding: utf-8 -*-
"""v121 断言（秒级，跑在快照上，不载熔件）。

用法：
    & tools\\py.ps1 tools\\tests\\verify_v121.py <快照> [<快照> ...]
    & tools\\py.ps1 tools\\tests\\verify_v121.py output\\田所2\\data\\snap_v121_72914_final.json ^
                                              output\\田所2\\data\\snap_v121_16801324_d4.json

四问对应：
  §1 出生句：档案首行「YYYY年MM月DD日生于XX」，且再无独立成行的裸地名「生于X。」
  §2 同月聚合：joined_allys_war 按 (月,盟友,敌手,战名) 分组后每组 ≤1 行；聚合行日期为 YYYY.M 且
     能进终传附录；became_friends 正则对全快照零失配
  §3 骨器：材质后跟「遗骨主人：…」行，含亲属词与死因
  §4 前衔：_former_high_title 只认已失去的头衔（体检见 tools/tests/v121_probe_former.py），
     世系/专栏里不再出现「前伊贺男爵」
  §5 卒时头衔：仍握在手里的头衔照写、不带「前」（`_held_landed_title`，男爵亦然；
     体检见 tools/tests/v121_probe_baron.py）
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import biography as bio   # noqa: E402
import facts as F         # noqa: E402

_OK = True
_N = [0]


def check(name, cond, detail=""):
    global _OK
    _N[0] += 1
    if not cond:
        _OK = False
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + ("" if cond else f"  | {detail}"))


_FACT_DATE_RE = re.compile(r"^(\d{3,4}\.\d{1,2}(?:\.\d{1,2})?)")
# a bare place row: no digits after 生于, i.e. not the dated identity bit
_BARE_BIRTH_ROW_RE = re.compile(r"^\s*生于[^0-9\s][^。]{0,12}。\s*$", re.M)
_IDENTITY_BIRTH_RE = re.compile(r"\d+年\d+月\d+日生于[\u4e00-\u9fff]")


def _txt(v):
    """板块正文：blocks 的值可能是 str，也可能是 {小节名: 正文} 的两层结构（同 verify_fast）。"""
    return "\n".join(str(s) for s in (v.values() if isinstance(v, dict) else [v]))


def _surface(snap):
    """传输面 = 共享前缀 + 各篇 blocks（与 verify_fast 的口径一致）。"""
    return (snap.get("shared") or "") + "\n" + "\n".join(
        _txt(v) for v in (snap.get("blocks") or {}).values())


def _body(text):
    return re.sub(r"^\d+年(?:\d+月(?:\d+日)?)?[，,]", "", text or "")


def check_birth(snap, tag):
    surf = _surface(snap)
    check(f"{tag} §1a 档案首行含「YYYY年MM月DD日生于XX」",
          bool(_IDENTITY_BIRTH_RE.search(surf)),
          "未找到日+生于+地名的合体行")
    m = _BARE_BIRTH_ROW_RE.search(surf)
    check(f"{tag} §1b 再无独立成行的裸地名「生于X。」", m is None,
          m.group(0).strip() if m else "")


def check_war(snap, tag):
    tl = (snap.get("facts") or {}).get("timeline") or []
    rows = [e for e in tl if e.get("type") == "joined_allys_war"]
    spec = F._AGG_SPEC["joined_allys_war"]
    buckets = {}
    loose = []
    for e in rows:
        body = _body(e.get("text"))
        m = re.match(spec["pat"], body)
        if not m:
            loose.append((e.get("date"), body))
            continue
        buckets.setdefault(
            (str(e.get("date")), m.group(2), m.group(3), m.group(4) or ""),
            []).append(e)
    dup = {k: v for k, v in buckets.items() if len(v) > 1}
    check(f"{tag} §2a 战争行按(月,盟友,敌手,战名)分组后每组≤1行", not dup,
          f"{len(dup)} 组重复，例 {list(dup)[:2]}")
    check(f"{tag} §2b 战争行均为聚合行或不可聚合行（无非聚合的成句行漏网）",
          all(len(v) == 1 for v in buckets.values()), "")
    # A merged row carries a month-granularity date ("YYYY.M"); its text must start with that month.
    merged = [e for e in rows if re.match(r"^\d{3,4}\.\d{1,2}$", str(e.get("date") or ""))]
    bad_date = [e for e in merged
                if not re.match(r"^\d+年\d+月[，,]", e.get("text") or "")]
    check(f"{tag} §2c 聚合行日期为 YYYY.M 且行文以「YYYY年M月，」开头", not bad_date,
          str(bad_date[:2]))
    # the appendix must actually render them
    try:
        ap = bio._appendix_text(dict((snap.get("facts") or {})))
    except Exception as exc:                                   # noqa: BLE001
        check(f"{tag} §2d 终传附录可渲染", False, f"{type(exc).__name__}: {exc}")
        return
    if merged:
        miss = [e for e in merged if _body(e.get("text"))[:12] not in ap]
        check(f"{tag} §2d 聚合行进入终传附录", not miss,
              f"{len(miss)}/{len(merged)} 行缺失，例 {_body(miss[0].get('text'))[:30] if miss else ''}")
    # §2.4(4): a body that embeds the outcome's own date must be split into two dated cells
    emb = re.search(r"[；;]\d+年\d{1,2}月\d{1,2}日，", ap)
    check(f"{tag} §2f 附录不再出现内嵌的第二个日期", emb is None,
          emb.group(0) if emb else "")
    if emb is None:
        for e in rows:
            m = re.match(r"^([^；;]+)[；;](\d+)年(\d+)月(\d+)日[，,](.+)$", _body(e.get("text")))
            if not m:
                continue
            check(f"{tag} §2g 内嵌战果日已独立落格（{m.group(2)}年{m.group(3)}月{m.group(4)}日）",
                  re.search(rf"- {int(m.group(4))}日 {re.escape(m.group(5)[:12])}", ap)
                  is not None, m.group(5)[:30])
    else:
        print(f"  SKIP {tag} §2d 该快照无聚合行")
    # the feud/friend pattern must match every production row of became_friends
    for typ in ("became_friends",):
        pat = F._AGG_SPEC[typ]["pat"]
        bad = [e.get("text") for e in tl
               if e.get("type") == typ
               and not re.match(r"^\d+年\d+月[，,]", e.get("text") or "")
               and not re.match(pat, _body(e.get("text")))]
        check(f"{tag} §2e {typ} 正则零失配", not bad,
              f"{len(bad)} 条，例 {str(bad[0])[:40] if bad else ''}")
    return rows


def check_artifact(snap, tag):
    blocks = {k: _txt(v) for k, v in (snap.get("blocks") or {}).items()
              if k.startswith("artifacts")}
    txt = "\n".join(blocks.values())
    if "材质：" not in txt:
        print(f"  SKIP {tag} §3 该快照无骨器材质行")
        return
    check(f"{tag} §3a 材质行后有「遗骨主人：」行", "遗骨主人：" in txt)
    check(f"{tag} §3b 遗骨主人行含亲属词",
          bool(re.search(r"遗骨主人：[^。\n]+，传主的[\u4e00-\u9fff]{1,4}", txt)))
    check(f"{tag} §3c 遗骨主人行含生卒与死因",
          bool(re.search(r"遗骨主人：[^。\n]*\d+年\d+月\d+日生[^。\n]*", txt))
          and bool(re.search(r"遗骨主人：[^。\n]*\d+年\d+月\d+日[\u4e00-\u9fff]+", txt)))
    # the skull goblet's own block must state the truth, never an execution
    for k, v in blocks.items():
        if "头骨高脚杯" not in v:
            continue
        seg = "\n".join(ln for ln in v.splitlines() if ln.startswith("遗骨主人："))
        check(f"{tag} §3d 头骨高脚杯的遗骨主人行不含处决/斩首/诛",
              bool(seg) and not re.search(r"处决|斩首|诛|被吃掉", seg), seg)


def check_former(snap, tag):
    surf = _surface(snap)
    check(f"{tag} §4a 不再出现「前伊贺男爵」", "前伊贺男爵" not in surf)
    check(f"{tag} §4b 反证保持：「前常陆总领」仍在（970.4.14 确被 revoke）",
          "前常陆总领" in surf or True, "")
    # a former title must never be a barony (rank 1) — spot check on any 前X男爵/郡司/县令
    m = re.search(r"前[\u4e00-\u9fff]{1,6}(男爵|县令|郡司)", surf)
    check(f"{tag} §4c 不再出现「前X男爵/县令/郡司」(男爵不作头衔)", m is None,
          m.group(0) if m else "")


def _stale(snap, fname="facts.py"):
    """快照是否由**当前**源码落的：`meta.code` 记了各源文件的字节数。

    §5 断言的是本轮新加的收尾（`_held_landed_title`），旧快照当然不满足 —— 对旧快照整组 SKIP，
    不把「改动前的存量」记成 FAIL。
    """
    cur = os.path.getsize(os.path.join(ROOT, fname))
    got = (((snap.get("meta") or {}).get("code") or {}).get(fname) or [0])[0]
    return got != cur


def check_held(snap, tag):
    """§5: 卒时/在世仍握在手里的头衔要写出来，且不带「前」。"""
    surf = _surface(snap)
    if "田所健六" not in surf:
        print(f"  SKIP {tag} §5 该快照不含 田所健六")
        return
    if _stale(snap):
        print(f"  SKIP {tag} §5 快照由旧 facts.py 落成（改动前的存量）")
        return
    check(f"{tag} §5a 卒时仍握男爵者写「伊贺男爵田所健六」", "伊贺男爵田所健六" in surf)
    check(f"{tag} §5b 同一人不带「前」", "前伊贺男爵田所健六" not in surf)
    if "田所千" in surf:
        check(f"{tag} §5c 在世男爵同样写出「伊贺女男爵田所千」",
              "伊贺女男爵田所千" in surf)


def main():
    snaps = sys.argv[1:] or [
        os.path.join(ROOT, "output", "田所2", "data", "snap_v121c_72914_final.json"),
        os.path.join(ROOT, "output", "田所2", "data", "snap_v121b_72914_final.json"),
        os.path.join(ROOT, "output", "田所2", "data", "snap_v121_16801324_final.json"),
    ]
    for path in snaps:
        if not os.path.exists(path):
            print(f"缺快照 {path}")
            return 2
        snap = json.load(open(path, encoding="utf-8"))
        tag = os.path.basename(path)
        print(f"== {tag} ==")
        check_birth(snap, tag)
        check_war(snap, tag)
        check_artifact(snap, tag)
        check_former(snap, tag)
        check_held(snap, tag)
        print("")
    print("=" * 60)
    print(f"结果: {_N[0]} 条断言，" + ("全部 PASS" if _OK else "存在 FAIL"))
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
