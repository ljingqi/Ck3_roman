# -*- coding: utf-8 -*-
"""v105 四问题的快照断言：亲属排行句 / 加冕礼见证去重 / 历代记死因与凶手 / 跨卷人名。

用法： & tools\\py.ps1 tools\\tests\\v105_probe_snap.py <快照路径>…
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def blocks_of(snap):
    return snap.get("blocks") or {}


def facts_of(snap):
    return snap.get("facts") or {}


def all_text(snap):
    """Every material line of the snapshot, tagged by block."""
    out = []
    for bk, bv in sorted(blocks_of(snap).items()):
        if isinstance(bv, dict):
            for sub, txt in sorted(bv.items()):
                for ln in str(txt).split("\n"):
                    if ln.strip():
                        out.append((f"{bk}/{sub}", ln))
        else:
            for ln in str(bv).split("\n"):
                if ln.strip():
                    out.append((bk, ln))
    return out


def check(label, ok, detail=""):
    print(("  PASS " if ok else "  FAIL ") + label + ("  | " + str(detail)[:400] if detail else ""))
    return bool(ok)


def main():
    paths = sys.argv[1:] or [
        os.path.join(ROOT, "output", "洪氏2", "data", "snap_135480_final.json")]
    bad = 0
    for p in paths:
        snap = json.load(open(p, encoding="utf-8"))
        rows = all_text(snap)
        facts = facts_of(snap)
        print("=" * 78)
        print("快照:", os.path.basename(p), " blocks:", len(blocks_of(snap)),
              " 素材行:", len(rows))

        # ---- 问题1：亲属行只留排行句 ----
        print("\n[1] 亲属排行句")
        rank = [r for r in rows if "子女中排" in r[1]]
        for w, ln in rank:
            print("   ", w, "|", ln)
        bad += not check("有「在父亲/母亲子女中排老X」句", bool(rank), rank[:1])
        if rank:
            w, ln = rank[0]
            bad += not check("排行句用家族序数（老幺/老大/老二…）",
                             bool(re.search(r"排老[大一二三四五六七八九十幺]", ln)), ln)
        gone = [r for r in rows if "分属" in r[1] or "个子女" in r[1] or "在诸子女中行" in r[1]]
        bad += not check("子女数/生母数/兄弟姊妹数已退出素材", not gone, gone[:3])
        prof = (facts.get("protagonist") or {})
        print("    facts.protagonist.kin_counts =", repr(prof.get("kin_counts")),
              " parent =", repr(prof.get("kin_counts_parent")))

        # ---- 问题2：一场加冕礼不再既出结仇行又出见证行 ----
        print("\n[2] 加冕礼结仇行与见证行")
        feud = [(w, ln) for w, ln in rows if "抵制" in ln or "结仇" in ln]
        wit = [(w, ln) for w, ln in rows if "见证" in ln and "加冕" in ln]
        print("    结仇/抵制行 %d 条，见证加冕行 %d 条" % (len(feud), len(wit)))
        for w, ln in feud[:6]:
            print("     F", w, "|", ln[:150])
        for w, ln in wit[:6]:
            print("     W", w, "|", ln[:150])
        tl = facts.get("timeline") or []
        pairs = set()
        for w, ln in feud:
            if "抵制" in ln and "的加冕礼" in ln:
                m = re.search(r"抵制(.+?)的加冕礼", ln)
                if m:
                    pairs.add(m.group(1))
        clash = []
        for nm in pairs:
            for w, ln in wit:
                if nm in ln:
                    clash.append((nm, ln[:120]))
        bad += not check("抵制过的人不再出现在同一场加冕的见证行里", not clash, clash[:3])

        # ---- 问题3a：历代记死因带凶手 ----
        print("\n[3a] 历代记死因")
        sacr = [(w, ln) for w, ln in rows if "献祭" in ln]
        for w, ln in sacr[:8]:
            print("   ", w, "|", ln[:180])
        bad += not check("献祭行点名行凶者（被X献祭）",
                         all(re.search(r"被.+?献祭", ln) for w, ln in sacr) if sacr else True,
                         [ln for w, ln in sacr if not re.search(r"被.+?献祭", ln)][:2])

        # ---- 问题3a′：开篇名录带卒讯 ----
        print("\n[3a′] 王朝历代开篇名录")
        lead = blocks_of(snap).get("chaoju_lead") or {}
        gl = lead.get("王朝历代") or ""
        for ln in gl.split("\n")[:12]:
            print("   ", ln[:200])
        items = re.findall(r"（[^）]*）", gl)
        withdeath = [x for x in items if "卒" in x]
        bad += not check("名录条目带卒讯", bool(withdeath), items[:3])
        if withdeath:
            print("    例:", withdeath[0][:200])

        # ---- 问题3b：疆域素材清除 ----
        print("\n[3b] 疆域素材")
        terr = [r for r in rows if r[1].startswith(("本朝所辖：", "本朝疆域：", "主角所处疆域："))]
        bad += not check("所辖/疆域行已退出素材", not terr, terr[:3])
        cap = [r for r in rows if r[1].startswith("治所：")]
        bad += not check("治所行保留", bool(cap), cap[:1])
        ten = [r for r in rows if r[1].startswith("主角本朝任期：")]
        bad += not check("主角本朝任期保留", bool(ten), ten[:1])
        bad += not check("末节块改名 本朝治所与任期",
                         "本朝治所与任期" in (blocks_of(snap).get("chaoju_mid_last")
                                              or blocks_of(snap).get("chaoju_mid3") or {}),
                         sorted(k for k in blocks_of(snap) if k.startswith("chaoju")))

        # ---- 问题4：跨卷人名 ----
        print("\n[4] 人名口径")
        nm = prof.get("name") or ""
        print("    本卷传主名:", nm)
        print("    facts.realm 键:", sorted((facts.get("realm") or {}).keys()))
    print("=" * 78)
    print("FAIL 计数:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
