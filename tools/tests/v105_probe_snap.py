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


def _daynum(d):
    """Same approximation facts._date_ord uses, so the window here is the window under test."""
    try:
        y, m, dd = (int(x) for x in str(d).split(".")[:3])
    except (TypeError, ValueError):
        return -10 ** 9
    return y * 372 + (m - 1) * 31 + dd


def main():
    paths = sys.argv[1:] or [
        os.path.join(ROOT, "output", "洪氏2", "data", "snap_135480_final.json")]
    bad = 0
    snaps = [(p, json.load(open(p, encoding="utf-8"))) for p in paths]
    for p, snap in snaps:
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
        tl = [e for e in (facts.get("timeline") or []) if isinstance(e, dict)]
        wit = [e for e in tl if e.get("type") == "witnessed_a_coronation_memory"]
        feud = [e for e in tl if e.get("type") == "became_rivals"
                and "的加冕礼" in (e.get("text") or "")]
        print("    结仇行 %d 条，见证加冕行 %d 条" % (len(feud), len(wit)))
        for e in feud[:6]:
            print("     F", e.get("date"), "|", (e.get("text") or "")[:120])
        for e in wit[:6]:
            print("     W", e.get("date"), "|", (e.get("text") or "")[:120])
        chars = facts.get("characters") or {}

        # The invariant facts._drop_ceremony_witnesses enforces: a witness row goes when the same
        # pair (owner, host) also produced a coronation feud within _ACTIVITY_MERGE_DAYS - and an
        # aggregate row loses just the guests who boycotted that same ceremony.
        clash = []
        names = [(cid, (rec or {}).get("name") or "")
                 for cid, rec in chars.items()]
        names = [(cid, n) for cid, n in names if n]
        for e in wit:
            ident = e.get("ident") or {}
            host = (ident.get("parts") or {}).get("host")
            owner = ident.get("owner")
            hnm = (chars.get(str(host)) or {}).get("name") or ""
            onm = (chars.get(str(owner)) or {}).get("name") or ""
            near = [g for g in feud
                    if abs(_daynum(e.get("date")) - _daynum(g.get("date"))) <= 90]
            for g in near:
                gt = g.get("text") or ""
                if hnm and onm and hnm in gt and onm in gt:
                    clash.append((e.get("date"), onm, hnm, gt[:80]))
                if hnm and hnm in gt:
                    # every other person the feud row names boycotted this ceremony
                    for cid, n in names:
                        if n != hnm and n in gt and n in (e.get("text") or ""):
                            clash.append((e.get("date"), n, hnm, gt[:80]))
        bad += not check("同一场加冕礼（90日内）的抵制者不再出现在见证行里", not clash, clash[:3])
        bad += not check("别场加冕的见证行仍在（未过度删除）", bool(wit),
                         [e.get("date") for e in wit][:4])

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
        chaoju_mids = sorted(k for k in blocks_of(snap)
                             if re.fullmatch(r"chaoju_mid\d+", k))
        last = blocks_of(snap).get(chaoju_mids[-1]) if chaoju_mids else {}
        bad += not check("末节块改名 本朝治所与任期",
                         "本朝治所与任期" in (last or {}),
                         [chaoju_mids, sorted((last or {}).keys())])
        bad += not check("末节之外的历代记节不带治所块",
                         not any("本朝治所与任期" in (blocks_of(snap).get(k) or {})
                                 for k in chaoju_mids[:-1]),
                         chaoju_mids[:-1])

        # ---- 问题4：跨卷人名 ----
        print("\n[4] 人名口径")
        nm = prof.get("name") or ""
        print("    本卷传主名:", nm)
        print("    facts.realm 键:", sorted((facts.get("realm") or {}).keys()))
        # A cross-volume degraded name reads exactly like a relative's, so two distinct people
        # end up sharing one string (135480 耀国·缯松 fell back to 耀国·洪堡).
        chars4 = facts.get("characters") or {}
        by_name = {}
        for cid, rec in chars4.items():
            n2 = (rec or {}).get("name") or ""
            if n2:
                by_name.setdefault(n2, []).append(cid)
        dup = {k: v for k, v in by_name.items() if len(v) > 1}
        if dup:
            print("    同名（供参考，两人可能本就同名）:", list(dup.items())[:6])
        pid4 = str(facts.get("player_id") or "")
        pnm4 = (chars4.get(pid4) or {}).get("name") or nm
        bad += not check("传主的名不与他人相撞（跨卷降级会撞成同名亲属）",
                         pnm4 not in dup, [pnm4, dup.get(pnm4)])

    if len(snaps) > 1:
        print("=" * 78)
        print("[4′] 跨卷同人口径")
        # A volume that only ever saw a man after his death carries no culture for him, so
        # display_name degrades to given+house - which can be word-for-word a relative's name.
        own = {}
        for p, snap in snaps:
            f = facts_of(snap)
            cid = str(f.get("player_id") or "")
            rec = (f.get("characters") or {}).get(cid) or {}
            if cid and rec.get("name"):
                own[cid] = (rec["name"], os.path.basename(p))
        clash4 = []

        def _core(n):
            # A regnal ordinal or an earned nickname is date-dependent (the son is 耀国·耀国松
            # until his father dies, then 耀国二世·耀国松; 残忍者 arrives with the first kill),
            # so neither is a cross-volume disagreement - the given+patronymic core is.
            n = re.sub(r"[一二三四五六七八九十]+世", "", n or "")
            return n.rsplit("·", 1)[-1]

        for p, snap in snaps:
            for cid, rec in (facts_of(snap).get("characters") or {}).items():
                if cid in own and (rec or {}).get("name") \
                        and _core(rec["name"]) != _core(own[cid][0]):
                    clash4.append((cid, rec["name"], own[cid][0], own[cid][1],
                                   os.path.basename(p)))
        bad += not check("他卷传主在本卷的名与其本卷同一个本名（跨卷降级会换成亲属的名）",
                         not clash4, clash4[:6])

    print("=" * 78)
    print("FAIL 计数:", bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
