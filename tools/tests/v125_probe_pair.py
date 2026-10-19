# -*- coding: utf-8 -*-
"""v125 取证探针（只读，不改生产代码）。

一次性载入 杨氏 的缓存与熔件，把六问涉及的确定性计算逐条打印：
  ② 惟仁亲王的头衔链（为何是「亲王」而不是「上皇」）
  ③ 「岳母兼儿媳」的亲属词是按谁算的（line_owner / identity_parts）
  ⑤ 「枢密使兼枢密使」两个来源（official_title 与 council/court seat）
  ⑥ 后任句为何只有「其妻」（_kin_word 单词 vs kin_chain_words_for 并称）

用法：& tools\\py.ps1 tools\\tests\\probe_v125.py
产物：logs/v125_probe.txt
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402
import llm               # noqa: E402

FOLDER, PID = "杨氏", 38932


def main():
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache = json.load(open(os.path.join(data, f"player_{PID}.json"), encoding="utf-8"))
    melts = [x for x in os.listdir(data)
             if x.startswith("melt_") and "_idx" not in x and x.endswith(".json")]

    def _k(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)
    melt_path = os.path.join(data, max(melts, key=_k))
    names = os.path.join(data, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    melt = cl.load_melt(melt_path)
    campaign = {}
    for fn in os.listdir(data):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        c = json.load(open(os.path.join(data, fn), encoding="utf-8"))
        if c.get("playthrough_id") == cache.get("playthrough_id"):
            campaign[int(m.group(1))] = c
    facts = F.build_facts(cache, melt, names, as_of=None, decade=None,
                          campaign=campaign or None)
    f = facts["_facts"]
    out = []

    def p(*a):
        out.append(" ".join(str(x) for x in a))

    pid = cache.get("player_id")
    chars = cache.get("characters") or {}

    def find(*words, limit=6):
        """cid list whose name/full name contains all `words`."""
        hits = []
        for k, rec in chars.items():
            nm = f"{rec.get('name_zh') or ''}{rec.get('name_full') or ''}"
            if all(w in nm for w in words):
                hits.append(int(k))
                if len(hits) >= limit:
                    break
        return hits

    p("== ids ==")
    for nm in ("杨白劳", "韩吉娘", "杨丹霞", "杨尚昆", "惟仁", "赵昶", "赵若莘"):
        ids = find(nm)
        p(nm, ids, [f.name_or(i) for i in ids])
    p("player", pid, f.name_or(pid))

    def kin_block(a, b):
        p(f"-- pair {a}({f.name_or(a)}) / {b}({f.name_or(b)})")
        k1 = F.kin_key(cache, a, b, spouse_back=f._spouse_back_index(),
                       rev=f._kin_rev_index())
        k2 = F.kin_key(cache, b, a, spouse_back=f._spouse_back_index(),
                       rev=f._kin_rev_index())
        p("   kin_key(a->b)", k1, F.kin_text(k1) if k1 else "",
          "| (b->a)", k2, F.kin_text(k2) if k2 else "")
        for label, fn in (("kin_word_for", f.kin_word_for),
                          ("blood_kin_word_for", f.blood_kin_word_for)):
            try:
                p(f"   {label}(b,a)", fn(b, a) or "",
                  f"| {label}(a,b)", fn(a, b) or "")
            except Exception as e:  # noqa: BLE001
                p(f"   {label} ERR", e)
        p("   _spouse_kind_of(b,a)", f._spouse_kind_of(b, a) or "",
          "| (a,b)", f._spouse_kind_of(a, b) or "")
        for subj in (a, b):
            parts = f.identity_parts(b, subj)
            p(f"   identity_parts(b={b}, subject={subj})",
              [(c, w, s) for c, w, s in parts])
            p(f"   chain(b, subject={subj})", "兼".join(f.kin_chain_words_for(b, subj)))

    p("")
    p("== ③ 韩吉娘 的亲属并称 ==")
    bai = find("杨白劳")
    han = find("韩吉娘")
    dx = find("杨丹霞")
    if bai and han:
        kin_block(bai[0], han[0])
    if dx and han:
        p("-- 丹霞/韩吉娘 (母女) --")
        p("   kin(丹霞<-韩吉娘)", f.kin_word_for(dx[0], han[0]) or "",
          "| kin(韩吉娘<-丹霞)", f.kin_word_for(han[0], dx[0]) or "")
    if dx:
        p("-- 丹霞 对传主 --")
        p("   kin_word_for(dx,pid)", f.kin_word_for(dx[0], pid) or "")
        p("   chain(dx,pid)", "兼".join(f.kin_chain_words_for(dx[0], pid)))
        p("   后任句 _kin_word(pid,dx)", f._kin_word(pid, dx[0]) or "")

    p("")
    p("== ③b 触发句的 line_owner ==")
    for blk, body in (("blocks", facts.get("blocks") or {}),):
        pass
    tl = facts.get("timeline") or []
    targets = []
    for e in tl:
        t = e.get("text") or ""
        if "勾引" in t:
            targets.append(t)
    for t in targets:
        p("   text:", t[:160])
        p("     line_owner:", (facts.get("line_owner") or {}).get(t))
        ni = (facts.get("name_index") or {}).get(t)
        p("     name_index:", ni)
        p("     line_stated:", (facts.get("line_stated") or {}).get(t))

    p("")
    p("== ⑤ 杨尚昆 的官职词 ==")
    sq = find("杨尚昆")
    if sq:
        cid = sq[0]
        p("   official_title:", f.official_title(cid) or "")
        p("   _subject_office_words:", f._subject_office_words(cid, f.as_of))
        p("   _court_positions_of:", f._court_positions_of(cid, date=f.as_of, subject=pid))
        p("   _council_seats_of:", f._council_seats_of(cid, subject=pid, date=f.as_of))
        p("   _ministry_office_at:", f._ministry_office_at(cid, f._anchor_date(cid)))
        p("   person_label brief:", f.person_label(cid, date=f.as_of, style="brief"))
        p("   person_label full :", f.person_label(cid, date=f.as_of, style="full"))
        p("   person_label event:", f.person_label(cid, date=f.as_of, style="event"))
        ivs = f._hold_intervals(cid) or {}
        for tid, iv in ivs.items():
            key = (f._lt.get(str(tid)) or {}).get("key") or ""
            if key:
                p("     held title:", tid, key, iv)

    p("")
    p("== ② 惟仁 的头衔计算 ==")
    wr = find("惟仁")
    if wr:
        cid = wr[0]
        p("   ids:", cid, f.name_or(cid))
        p("   name_with_regnal:", f.name_with_regnal(cid))
        p("   _tenno_prince_word:", f._tenno_prince_word(cid) or "")
        p("   _tenno_prince_name:", f._tenno_prince_name(cid) or "")
        p("   japan_top_office:", f.japan_top_office(cid) or "")
        p("   official_title:", f.official_title(cid) or "")
        p("   person_label brief:", f.person_label(cid, date=f.as_of, style="brief"))
        p("   person_label event:", f.person_label(cid, date=f.as_of, style="event"))
        c = (f._chars.get(str(cid)) or {})
        dd = c.get("dead_data") or {}
        p("   dead_data.flavor:", dd.get("flavor"), "date:", dd.get("date"),
          "reason:", dd.get("reason"))
        p("   _char_flags:", sorted(f._char_flags(cid)))
        p("   government:", f._character_government(cid, f.as_of))
        tier, tid = f._primary_title_at(cid, as_of=f.as_of)
        p("   _primary_title_at:", tier, tid,
          ((f._lt.get(str(tid)) or {}).get("key") if tid is not None else None))
        ivs = f._hold_intervals(cid) or {}
        for t, iv in ivs.items():
            key = (f._lt.get(str(t)) or {}).get("key") or ""
            p("     held:", t, key, iv)
        p("   parents:", f._parents_of_cid(cid))
        for p2 in f._parents_of_cid(cid):
            t2, tid2 = f._primary_title_at(p2, as_of=f.as_of)
            p("     parent", p2, f.name_or(p2), t2, tid2,
              ((f._lt.get(str(tid2)) or {}).get("key") if tid2 is not None else None),
              "ever_throne:", f._ever_held_throne(p2, f.as_of))

    txt = "\n".join(out)
    with open(os.path.join(ROOT, "logs", "v125_probe.txt"), "w", encoding="utf-8") as fp:
        fp.write(txt + "\n")
    print(txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
