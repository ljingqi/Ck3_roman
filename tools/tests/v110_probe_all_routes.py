# -*- coding: utf-8 -*-
"""v110 dev probe: *all* blood routes (not just the shortest) for one pair.

`Facts._ancestor_routes` keeps the first route to each ancestor, so a pair that shares
an ancestor by two lines of different length sees only one of them. This probe
enumerates every distinct (ancestor, depth, all_male) reachable without passing through
the other person, and reports which extra signatures a multi-route walk would expose.

Usage:
    & tools\\py.ps1 tools\\tests\\v110_probe_all_routes.py <folder> <pid> <subject> <relative> [maxd]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402


def _find(chars, token):
    if token.isdigit():
        return [int(token)] if str(token) in chars else []
    out = []
    for k, rec in chars.items():
        if not k.isdigit() or not isinstance(rec, dict):
            continue
        if token in (rec.get("name"), rec.get("first_name"), rec.get("name_full"),
                     rec.get("name_zh")):
            out.append(int(k))
    return out


def all_routes(x, fath, moth, banned, maxd):
    """{(ancestor, depth, all_male)} over every simple path from x avoiding `banned`."""
    out = set()
    seen_states = set()

    def walk(node, d, male, path):
        key = (node, d, male)
        if key in seen_states:
            return
        seen_states.add(key)
        out.add((node, d, male))
        if d >= maxd:
            return
        for parents, is_father in ((fath.get(node), True), (moth.get(node), False)):
            for p in (parents or ()):
                if p in banned or p in path:
                    continue
                walk(p, d + 1, male and is_father, path | {p})

    walk(x, 0, True, {x})
    return out


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        return 2
    folder, pid, subject, relative = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    maxd = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    data = os.path.join(ROOT, "output", folder, "data")
    cache = json.load(open(os.path.join(data, "player_%d.json" % pid), encoding="utf-8"))
    f = F.Facts(cache, {}, os.path.join(data, "names.json"))
    chars = cache.get("characters") or {}

    def nm(cid):
        r = chars.get(str(cid)) or {}
        return "%s(%s)" % (r.get("name") or "?", cid)

    for sid in _find(chars, subject):
        for cid in _find(chars, relative):
            fath, moth = f._parent_maps()
            rs = all_routes(sid, fath, moth, {cid}, maxd)
            rc = all_routes(cid, fath, moth, {sid}, maxd)
            # (ancestor -> {(depth, all_male)})
            ms_map, mc_map = {}, {}
            for a, d, m in rs:
                ms_map.setdefault(a, set()).add((d, m))
            for a, d, m in rc:
                mc_map.setdefault(a, set()).add((d, m))
            print("=" * 78)
            print("subject %s / relative %s  (maxd=%d)" % (nm(sid), nm(cid), maxd))
            print("ancestors of subject : %d nodes / %d sigs" %
                  (len(ms_map), sum(len(v) for v in ms_map.values())))
            print("ancestors of relative: %d nodes / %d sigs" %
                  (len(mc_map), sum(len(v) for v in mc_map.values())))
            cfemale = f._is_female(cid)
            older = F._older_rec(chars.get(str(cid)) or {}, chars.get(str(sid)) or {}, cid, sid)
            print("-" * 78)
            multi = 0
            for a in sorted(set(ms_map) & set(mc_map)):
                pairs = sorted({(ds, ms) for ds, ms in ms_map[a]} |
                               {(dc, mc) for dc, mc in mc_map[a]})
                got = []
                for ds, ms in sorted(ms_map[a]):
                    for dc, mc in sorted(mc_map[a]):
                        if ds == 0 and dc == 0:
                            continue
                        key = F._kin_key_of_route(ds, dc, ms, mc, cfemale, older)
                        got.append((ds, dc, ms, mc, F.kin_text(key)))
                if len(ms_map[a]) > 1 or len(mc_map[a]) > 1:
                    multi += 1
                    print("  A=%s   s-depth %s   c-depth %s" %
                          (nm(a), sorted(ms_map[a]), sorted(mc_map[a])))
                    for ds, dc, ms_, mc_, word in got:
                        print("       up_s=%d up_c=%d gap=%+d ms=%-5s mc=%-5s -> %s"
                              % (ds, dc, ds - dc, ms_, mc_, word))
            print("  （多路线共同祖先 %d 个）" % multi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
