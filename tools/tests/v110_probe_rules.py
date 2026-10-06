# -*- coding: utf-8 -*-
"""v110 规则实验台：在缓存面比较「候选选择规则」对血缘词的影响（只读 · 不用熔件）。

`Facts.blood_kin_words_for` 的 v110 改动是把每个祖先的**全部路线签名**纳入候选。
本探针把三种规则放在同一批 (传主, 亲属) 有序对上比：

    old  只留每祖先的最短路线（v109 口径）
    R1   全部路线签名（当前实现）
    R2   old ∪ 「同辈路线」（ds == dc）—— 只补堂/表/从这些精确的平辈词

用法：
    & tools\\py.ps1 tools\\tests\\v110_probe_rules.py <folder> <pid> [pid…]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "tools", "tests"))
from v110_kin_table import family_ids, ancestor_set  # noqa: E402


def old_routes(x, fath, moth, banned, maxd=F._DEEP_MAXD):
    """The pre-v110 walk: the first (shortest) route to each ancestor wins."""
    out = {x: (0, True)}
    frontier = [(x, 0, True)]
    while frontier:
        nxt = []
        for node, d, male in frontier:
            if d >= maxd:
                continue
            for parents, is_father in ((fath.get(node), True), (moth.get(node), False)):
                for parent in (parents or ()):
                    if parent in banned or parent in out:
                        continue
                    out[parent] = (d + 1, male and is_father)
                    nxt.append((parent, d + 1, male and is_father))
        frontier = nxt
    return out


def sigs_of(routes, croutes):
    out = set()
    for anc, sroutes in routes.items():
        c_routes = croutes.get(anc)
        if not c_routes:
            continue
        for ds, ms in sroutes:
            for dc, mc in c_routes:
                if ds == 0 and dc == 0:
                    continue
                out.add((ds + dc, ds, dc, ms, mc))
    return out


def old_sigs_of(routes, croutes):
    out = set()
    for anc, (ds, ms) in routes.items():
        hc = croutes.get(anc)
        if hc is None or (ds == 0 and hc[0] == 0):
            continue
        out.add((ds + hc[0], ds, hc[0], ms, hc[1]))
    return out


def words_of(sigs, primary, cfemale, older, limit=3, pred=None, coarse_only=None):
    words = [primary] if primary else []
    for tot, ds, dc, ms, mc in sorted(sigs):
        if pred and not pred(tot, ds, dc, ms, mc):
            continue
        w = F.kin_text(F._kin_key_of_route(ds, dc, ms, mc, cfemale, older))
        if not w or w in words:
            continue
        if coarse_only is not None and _coarse(w) != coarse_only:
            continue
        words.append(w)
        if len(words) >= limit:
            break
    return words


def _coarse(w):
    """Whether a word is the vocabulary's clan fallback tier (族X / 同族X) rather than a
    line-specific term (父亲/姑母/姨母/堂姐…)."""
    return w.startswith("族") or w.startswith("同族")


def min_depth_sigs(routes, croutes):
    """「每祖先最短路线」的放宽版：同一最短深度下的全部 all_male 变体都算（v110 拟用实现）。"""
    out = set()
    for anc, sr in routes.items():
        cr = croutes.get(anc)
        if not cr:
            continue
        ds_min = min(d for d, _m in sr)
        dc_min = min(d for d, _m in cr)
        if ds_min == 0 and dc_min == 0:
            continue
        for d, ms in sr:
            if d != ds_min:
                continue
            for d2, mc in cr:
                if d2 != dc_min:
                    continue
                out.add((ds_min + dc_min, ds_min, dc_min, ms, mc))
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    folder, pids = sys.argv[1], [int(x) for x in sys.argv[2:]]
    data = os.path.join(ROOT, "output", folder, "data")
    print("=" * 92)
    print("v110 血缘路线候选规则比较（只读 · 缓存面 · 不用熔件）")
    print("=" * 92)
    print("""比对基准：`old` = v109 口径（每祖先只留最短路线）。各候选规则的新增/丢失以 old 为基。
  R1  全部路线签名（最初的 v110 实现）
  R2  old ∪ 同辈路线（ds == dc）
  R3  old ∪ 「词具体」的路线（词不以 族/同族 开头）  ← 采用
  R4  「每祖先最短深度（含该深度全部 all_male 变体）」∪「词具体」的路线（R3 的本地可算写法）
  R5  只要「词具体」的路线，不再保留 old（用于验证 old 必须保留）
判据：变化对越少越好；新增精确词越多越好；丢失精确词越少越好；堂/表改判不减。""")
    for pid in pids:
        cache = json.load(open(os.path.join(data, "player_%d.json" % pid), encoding="utf-8"))
        names_path = os.path.join(data, "names.json")
        if not os.path.exists(names_path):
            names_path = os.path.join(ROOT, "data", "names.json")
        f = F.Facts(cache, {}, names_path)
        chars = cache.get("characters") or {}
        fath, moth = f._parent_maps()
        roster = sorted(family_ids(chars, pid))
        anc = {c: ancestor_set(c, fath, moth) for c in roster}
        pairs = [(s, c) for s in roster for c in roster
                 if c != s and (anc[s] & anc[c])]
        stat = {k: {"changed": 0, "add": 0, "lose": 0,
                    "cousin_fix": 0, "add_precise": 0, "lose_precise": 0}
                for k in ("R1", "R2", "R3", "R4", "R5")}
        added = {k: {} for k in ("R1", "R2", "R3", "R4", "R5")}
        for s, c in pairs:
            primary = f.blood_kin_word_for(c, s)
            cfemale, older = f._is_female(c), F._older_rec(
                chars.get(str(c)) or {}, chars.get(str(s)) or {}, c, s)
            oroutes = old_routes(s, fath, moth, {c})
            ocroutes = old_routes(c, fath, moth, {s})
            o_sigs = old_sigs_of(oroutes, ocroutes)
            n_sigs = sigs_of(f._ancestor_routes(s, fath, moth, {c}),
                             f._ancestor_routes(c, fath, moth, {s}))
            old_w = words_of(o_sigs, primary, cfemale, older)

            def w_of(sig):
                return F.kin_text(F._kin_key_of_route(sig[1], sig[2], sig[3], sig[4],
                                                      cfemale, older))

            same_gen = {x for x in n_sigs if x[1] == x[2]}
            precise = {x for x in n_sigs if w_of(x) and not _coarse(w_of(x))}
            cand = {
                "R1": words_of(n_sigs, primary, cfemale, older),
                "R2": words_of(o_sigs | same_gen, primary, cfemale, older),
                "R3": words_of(o_sigs | precise, primary, cfemale, older),
                "R4": words_of(min_depth_sigs(f._ancestor_routes(s, fath, moth, {c}),
                                              f._ancestor_routes(c, fath, moth, {s}))
                               | precise, primary, cfemale, older),
                "R5": words_of(precise, primary, cfemale, older),
            }
            for k, w in cand.items():
                if w == old_w:
                    continue
                st = stat[k]
                st["changed"] += 1
                add = [x for x in w if x not in old_w]
                lose = [x for x in old_w if x not in w]
                st["add"] += len(add)
                st["lose"] += len(lose)
                st["add_precise"] += len([x for x in add if not _coarse(x)])
                st["lose_precise"] += len([x for x in lose if not _coarse(x)])
                if any(x.startswith(("堂", "表")) for x in old_w) \
                        and any(x.startswith(("堂", "表")) for x in w) \
                        and [x for x in old_w if x.startswith(("堂", "表"))] \
                        != [x for x in w if x.startswith(("堂", "表"))]:
                    st["cousin_fix"] += 1
                for x in add:
                    added[k][x] = added[k].get(x, 0) + 1
        print("=" * 78)
        print("战役 %d：家族 %d 人 / 血缘相关对 %d" % (pid, len(roster), len(pairs)))
        for k in ("R1", "R2", "R3", "R4", "R5"):
            st = stat[k]
            top = sorted(added[k].items(), key=lambda x: -x[1])[:12]
            print("  %s 变化对 %-6d 新增词 %-6d 丢失词 %-5d 堂/表改判 %-5d 新增精确 %-5d 丢精确 %-5d"
                  % (k, st["changed"], st["add"], st["lose"], st["cousin_fix"],
                     st["add_precise"], st["lose_precise"]))
            print("     新增词榜 %s" % top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
