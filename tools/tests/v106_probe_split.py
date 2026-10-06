# -*- coding: utf-8 -*-
"""v106 probe: the 传主档案 split, measured at the snapshot's message level.

Compares the pre-v106 snapshot (snap_117484775_final.json, one dossier block per request) with the
post-v106 one (v106_117484775.json, identity half + household half): per-request chars, the size of
each half, which boards receive the household half, and whether the identity half stays byte-identical
across the boards that get it (the request prefix the cache keys on).

Usage: & tools\\py.ps1 tools\\tests\\v106_probe_split.py [old.json] [new.json]
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
H2 = os.path.join(ROOT, "output", "洪氏2", "data")
OUT = os.path.join(ROOT, "logs", "v106_cache_after.txt")
HEADS = ("传主档案", "人物档案")


def block_size(bd, head):
    """Chars of one block (head line included), 0 when absent."""
    txt = (bd or {}).get(head) or ""
    return len(txt) + 1 if txt else 0


def main():
    old_p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(H2, "snap_117484775_final.json")
    new_p = sys.argv[2] if len(sys.argv) > 2 else os.path.join(H2, "v106_117484775.json")
    old = json.load(io.open(old_p, encoding="utf-8"))
    new = json.load(io.open(new_p, encoding="utf-8"))
    ob, nb = old.get("blocks") or {}, new.get("blocks") or {}
    om, nm = old.get("messages") or {}, new.get("messages") or {}
    lines = []
    hdr = "%-24s %8s %8s %7s %7s %7s %6s %s" % (
        "block", "chars_old", "chars_new", "档案旧", "档案新", "家室", "Δ", "half")
    lines.append(hdr)
    t_old = t_new = d_old = d_new = h_new = 0
    idents = {}
    for k in sorted(set(ob) | set(nb)):
        bd_o, bd_n = ob.get(k) or {}, nb.get(k) or {}
        def _head_size(bd):
            for h in HEADS:
                v = block_size(bd, h)
                if v:
                    return v
            return 0
        so, sn = _head_size(bd_o), _head_size(bd_n)
        hn = block_size(bd_n, "传主家室")
        co = len((om.get(k) or {}).get("system", "")) + len((om.get(k) or {}).get("user", ""))
        cn = len((nm.get(k) or {}).get("system", "")) + len((nm.get(k) or {}).get("user", ""))
        half = "家室" if hn else ("身份" if sn else "无档案")
        lines.append("%-24s %8d %8d %7d %7d %7d %+6d %s"
                     % (k, co, cn, so, sn, hn, cn - co, half))
        t_old += co
        t_new += cn
        d_old += so
        d_new += sn
        h_new += hn
        for h in HEADS:
            txt = (bd_n or {}).get(h) or ""
            if txt:
                idents.setdefault(txt, []).append(k)
    lines.append("")
    lines.append("requests=%d  chars old=%d new=%d (%+d)  档案 old=%d new=%d  家室 new=%d"
                 % (len(set(ob) | set(nb)), t_old, t_new, t_new - t_old, d_old, d_new, h_new))
    lines.append("chars saved on requests without the household half: %d" % h_new)
    lines.append("")
    lines.append("identity-half byte-identity across boards: %d distinct text(s)" % len(idents))
    for txt, keys in sorted(idents.items(), key=lambda x: -len(x[1])):
        lines.append("   %3d boards  %d chars  head=%s" % (len(keys), len(txt), txt[:40]))
        lines.append("        %s" % ", ".join(sorted(keys)[:30]))
    txt = "\n".join(lines) + "\n"
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(txt)
    sys.stdout.write(txt)


if __name__ == "__main__":
    main()
