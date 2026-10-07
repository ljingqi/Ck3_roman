# -*- coding: utf-8 -*-
"""v112 只读探针：按「真实血亲辈分」给玩家传承链编号。

父母边两个方向都取（子记录里的 father/mother/real_father ∪ 父记录里 child 的反向），
与 facts.kin_rev_index 的口径一致；缺一边会漏掉整条线（本探针第一版即因此把
「其父」算成 +2）。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_generations.py [缓存文件] [--chain N]
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAXD = 5
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def build_parent_map(chars):
    """{cid: {parent, ...}} —— 父母边双向并集。"""
    par = {}
    for k, rec in chars.items():
        if not str(k).isdigit() or not isinstance(rec, dict):
            continue
        cid = int(k)
        fam = rec.get("family") or {}
        for key in ("father", "mother", "real_father"):
            for x in (fam.get(key) or []):
                if isinstance(x, int):
                    par.setdefault(cid, set()).add(x)
        for x in (fam.get("child") or []):
            if isinstance(x, int):
                par.setdefault(x, set()).add(cid)
    return par


def routes(par, x, banned):
    """{祖先: 最短代数}。banned 只用于挡环，**不挡对方本人**：辈分差要的正是直系那条边
    （`_ancestor_routes` 挡对方是为了「同一条线看得更远」不算新关系，辈分不适用该口径）。"""
    out = {int(x): 0}
    frontier = [int(x)]
    for d in range(MAXD):
        nxt = []
        for node in frontier:
            for p in (par.get(node) or ()):
                if p in banned or p in out:
                    continue
                out[p] = d + 1
                nxt.append(p)
        frontier = nxt
    return out


def delta(par, a, b):
    ra = routes(par, a, set())
    rb = routes(par, b, set())
    best = None
    for anc, da in ra.items():
        if anc not in rb:
            continue
        db = rb[anc]
        cand = (da + db, db - da, anc)
        if best is None or cand < best:
            best = cand
    return best


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(ROOT, "output", "洪氏2", "data", "player_207044.json")
    with io.open(path, encoding="utf-8") as fp:
        cache = json.load(fp)
    chars = cache.get("characters") or {}
    par = build_parent_map(chars)
    chain = cache.get("played_legacy") or []
    pid = cache.get("player_id")
    idx = next((i for i, e in enumerate(chain) if e.get("cid") == pid), len(chain) - 1)
    print("缓存 %s  player_id=%s  链 %d 代（截到 idx=%d）  父母表 %d 人"
          % (os.path.basename(path), pid, len(chain), idx, len(par)))
    gen, prev = 1, None
    for i, e in enumerate(chain[:idx + 1]):
        cid = int(e.get("cid"))
        rec = chars.get(str(cid)) or {}
        mark = ""
        if prev is not None:
            best = delta(par, prev, cid)
            if best is None:
                gen += 1
                mark = "（辈分失考，按 +1）"
            else:
                gen = max(1, gen + best[1])
                mark = "Δ%s 共同祖先 %s(合 %d 代)" % (best[1], best[2], best[0])
            try:
                import facts as _F
                _k = _F.kin_key(cache, prev, cid, chars=chars)
                mark += "  亲属词=%s(%s)" % (_F.kin_text(_k) or "?", _k or "?")
            except Exception as exc:                       # noqa: BLE001
                mark += "  亲属词=? (%s)" % exc
        print("  %2d 世  cid=%-10s %-16s 生%-11s 卒%-11s %s"
              % (gen, cid, rec.get("name_full") or rec.get("name_zh") or "?",
                 rec.get("birth") or "?", (rec.get("death") or {}).get("date") or "（在世）", mark))
        prev = cid
    return 0


if __name__ == "__main__":
    sys.exit(main())
