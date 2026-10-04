# -*- coding: utf-8 -*-
"""v103 issue-5 preview: protagonist-centered kinship table over EVERY 洪氏 clan member.

Loads only the per-protagonist cache (no melt, no facts build), so it runs in seconds.
For each member of the protagonist's dynasty_house it prints:
  · the raw common-ancestor geometry (up_s = generations subject->ancestor,
    up_c = generations member->ancestor, all_male = whether the subject's path is
    patrilineal, 从数 = min(up)-1 for same-generation cousins)
  · the FINAL word from kin_key (the 12-step cascade first, the new deep-blood
    common-ancestor fallback only on a cascade miss)
  · whether that word came from the NEW fallback (marked «deep»)

The point is to eyeball the 再从/三从/玄孙/族侄 vocabulary before it is approved.
Read-only. Vocabulary lives in facts.KIN_WORDS (Groups M/N/O/P)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
PID = 135480

# keys introduced by the issue-5 fallback (facts.py Groups M/N/O/P)
DEEP_KEYS = {k for k in F.KIN_WORDS if k.startswith(("ancestor", "descendant",
             "cousin2_", "cousin3_", "clan"))}


def _geom(s, c, fath, moth, memo):
    """Raw common-ancestor geometry for the deep fallback, or None when unrelated in range."""
    anc_s = F._deep_anc_index(s, fath, moth, memo)
    anc_c = F._deep_anc_index(c, fath, moth, memo)
    best = None
    for A, (ds, ms) in anc_s.items():
        hc = anc_c.get(A)
        if not hc:
            continue
        dc, mc = hc
        if ds == 0 and dc == 0:
            continue
        cand = (ds + dc, ds, dc, ms, mc, A)
        if best is None or cand[:3] < best[:3]:
            best = cand
    return best


def main():
    cache = json.load(open(os.path.join(DATA, f"player_{PID}.json"), encoding="utf-8"))
    chars = cache.get("characters") or {}
    rev = F.kin_rev_index(chars)
    rev_sib = rev.get("sib") or {}
    rev_kid = rev.get("kid") or {}

    def _ids(fam, key):
        return [k for k in (fam.get(key) or []) if isinstance(k, int)]

    def _fam(x):
        return (chars.get(str(x)) or {}).get("family") or {}

    def _fath(x):
        f = _fam(x)
        return set(_ids(f, "father")) | set(_ids(f, "real_father"))

    def _moth(x):
        return set(_ids(_fam(x), "mother"))

    prec = chars.get(str(PID)) or {}
    house = prec.get("dynasty_house")
    house_name = prec.get("house_name")
    dynasty = prec.get("dynasty_name")

    # names come from display_name (the render path, with the issue-2 culture-name-order fix),
    # NOT the stale cache name_full — so this table also verifies requirement #5.
    melt = cl.load_melt(os.path.join(DATA, "melt_1050_01_01.json"))
    chars_all = cl.all_characters(melt)

    def _label(cid):
        try:
            nm = cl.display_name(cache, cid, melt=melt, chars=chars_all)
        except Exception:
            nm = ""
        return nm or (chars.get(str(cid)) or {}).get("name_zh") or str(cid)

    print(f"传主 {_label(PID)} (pid {PID})  house={house} ({house_name})  dynasty={dynasty}")

    clan = [int(k) for k, r in chars.items()
            if str(k).isdigit() and isinstance(r, dict) and int(k) != PID
            and (r.get("dynasty_name") == dynasty
                 or (house is not None and r.get("dynasty_house") == house))]
    print(f"宗族成员（同 dynasty「{dynasty}」，除传主）: {len(clan)} 人\n")

    memo = {}
    rows = []
    for cid in clan:
        r = chars.get(str(cid)) or {}
        key = F.kin_key(cache, PID, cid, chars=chars, rev=rev, anc_memo=memo)
        word = F.kin_text(key)
        deep = key in DEEP_KEYS
        g = _geom(PID, cid, _fath, _moth, memo)
        if g:
            _tot, up_s, up_c, ms, mc, A = g
            cong = (min(up_s, up_c) - 1) if up_s == up_c else None
            geom = f"up_s={up_s} up_c={up_c} {'堂' if (ms and mc) else '表'}"
            if cong is not None:
                geom += f" 从={cong}"
        else:
            geom = "无共同祖先(≤%d代)" % F._DEEP_MAXD
        rows.append((deep, g[1] if g else 99, g[2] if g else 99, _label(cid),
                     cid, key, word, geom, r.get("female"), r.get("birth")))

    # sort: deep-fallback rows first (the new vocabulary), then by geometry
    rows.sort(key=lambda x: (not x[0], x[1], x[2], str(x[3])))

    print("== 新增深层回退命中（«deep» = 旧 12 步判据算不出、本次扩展补上的）==")
    ndeep = 0
    for deep, us, uc, nm, cid, key, word, geom, fem, birth in rows:
        if not deep:
            continue
        ndeep += 1
        sx = "♀" if fem else ("♂" if fem is False else "?")
        print(f"  «deep» {nm:<16} {sx} ({cid}) {word or '(空)':<10} "
              f"key={key:<24} {geom}")
    print(f"  —— 深层回退命中 {ndeep} 人\n")

    print("== 词面分布（全部宗族成员，按最终词计数）==")
    dist = {}
    for deep, us, uc, nm, cid, key, word, geom, fem, birth in rows:
        w = word or "(空/无词)"
        dist[w] = dist.get(w, 0) + 1
    for w, n in sorted(dist.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {w:<12} {n}")

    print("\n== 无词（cascade 与 deep 都返回空）的宗族成员 ==")
    none_n = 0
    for deep, us, uc, nm, cid, key, word, geom, fem, birth in rows:
        if word:
            continue
        none_n += 1
        sx = "♀" if fem else ("♂" if fem is False else "?")
        print(f"  {nm:<16} {sx} ({cid}) {geom}")
    print(f"  —— 无词 {none_n} 人")

    # requirement #5: an Eastern (surname-first) clan must never render as given·surname
    print("\n== 姓名顺序核验（issue 2 / 需求#5：不得出现「名·姓」倒置）==")
    inverted = [(nm, cid) for _d, _us, _uc, nm, cid, _k, _w, _g, _f, _b in rows
                if "·" in nm]
    subj_nm = _label(PID)
    if "·" in subj_nm:
        inverted.append((subj_nm, PID))
    for nm, cid in inverted[:40]:
        print(f"  倒置 {nm} ({cid})")
    print(f"  —— 含「·」(西式名·姓) 的宗族名 {len(inverted)} 个 / 共 {len(clan) + 1} 人")


if __name__ == "__main__":
    main()
