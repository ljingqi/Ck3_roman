# -*- coding: utf-8 -*-
"""v116 附带探查 2（只用缓存）：直接调用工程的 kin_key，并打印两人 5 代祖先树。

用法: python -X utf8 tools/tests/v116_probe_kin_pair2.py <cidA> <cidB>
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import facts as F  # noqa: E402

CACHE = os.path.join(ROOT, "output", "洪氏2", "data", "player_207044.json")


def main():
    a, b = int(sys.argv[1]), int(sys.argv[2])
    cache = json.load(io.open(CACHE, encoding="utf-8"))
    ch = cache["characters"]

    def nm(cid):
        r = ch.get(str(cid)) or {}
        return "%s(%s)" % (r.get("name_full") or r.get("name_zh") or "?", cid)

    def fam(cid):
        return (ch.get(str(cid)) or {}).get("family") or {}

    def fath(cid):
        f = fam(cid)
        return [x for x in (f.get("father") or []) + (f.get("real_father") or []) if isinstance(x, int)]

    def moth(cid):
        return [x for x in (fam(cid).get("mother") or []) if isinstance(x, int)]

    print("kin_key(A->B) =", F.kin_key(cache, a, b))
    print("kin_key(B->A) =", F.kin_key(cache, b, a))
    print("kin_word(A->B) =", F.kin_word(cache, a, b))
    print("dynasty_house A=%s B=%s ; dynasty_name A=%s B=%s"
          % (ch[str(a)].get("dynasty_house"), ch[str(b)].get("dynasty_house"),
             ch[str(a)].get("dynasty_name"), ch[str(b)].get("dynasty_name")))

    for tag, x in (("A", a), ("B", b)):
        print("\n%s = %s 的 5 代祖先：" % (tag, nm(x)))
        cur = [(x, True)]
        seen = {x}
        for d in range(1, 6):
            nxt = []
            for p, _pm in cur:
                for f in fath(p):
                    if f not in seen:
                        seen.add(f)
                        nxt.append((f, True))
                for m in moth(p):
                    if m not in seen:
                        seen.add(m)
                        nxt.append((m, False))
            if not nxt:
                break
            print("   第%d代: %s" % (d, "、".join(nm(y) for y, _ in nxt)))
            cur = nxt
    return 0


if __name__ == "__main__":
    sys.exit(main())
