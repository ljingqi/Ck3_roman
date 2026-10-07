# -*- coding: utf-8 -*-
"""v112 只读探针：不载熔件，只拿缓存构造一个「壳 Facts」，验证三项纯缓存新逻辑。

  · Facts.generation_delta —— 与 v112_probe_generations 的独立 BFS 结果对照
  · Facts.twin_partners / _birth_of —— 双胞胎同胞解析率
  · Facts._birth_culture_id —— 改文化角色的出生文化

用法: & tools\\py.ps1 tools\\tests\\v112_probe_unit.py [缓存文件]
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import facts as F   # noqa: E402


def shell(cache):
    """A Facts instance with only the cache wired up — every helper under test reads nothing else."""
    f = F.Facts.__new__(F.Facts)
    f.cache = cache
    f._chars = {}
    f.as_of = None
    f.campaign = {cache.get("player_id"): cache} if cache.get("player_id") else {}
    return f


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(ROOT, "output", "洪氏2", "data", "player_207044.json")
    with io.open(path, encoding="utf-8") as fp:
        cache = json.load(fp)
    f = shell(cache)
    chars = cache.get("characters") or {}
    chain = [int(e["cid"]) for e in (cache.get("played_legacy") or [])
             if isinstance(e, dict) and isinstance(e.get("cid"), int)]
    pid = cache.get("player_id")
    idx = next((i for i, c in enumerate(chain) if c == pid), len(chain) - 1)
    chain = chain[:idx + 1]

    print("== generation_delta ==")
    gen = 1
    for i, cid in enumerate(chain):
        if i:
            d = f.generation_delta(chain[i - 1], cid)
            gen = max(1, gen + (d if d is not None else 1))
        print("  %2d 世 cid=%-10s %-16s 生%-11s 卒%s"
              % (gen, cid, (chars.get(str(cid)) or {}).get("name_zh") or "?",
                 (chars.get(str(cid)) or {}).get("birth") or "?",
                 ((chars.get(str(cid)) or {}).get("death") or {}).get("date") or "（在世）"))
    print("  自反: delta(x,x)=%s  delta(父,子)=%s"
          % (f.generation_delta(chain[0], chain[0]), f.generation_delta(chain[0], chain[1])))

    print("\n== twin_partners ==")
    holders = [int(k) for k, r in chars.items()
               if str(k).isdigit() and isinstance(r, dict) and r.get("trait_history")
               and "twin" in (r.get("trait_history") or {})]
    ok = 0
    for cid in holders:
        if f.twin_partners(cid):
            ok += 1
    print("  持 twin 特质者 %d 人，可解出同胞 %d 人（%.1f%%）"
          % (len(holders), ok, 100.0 * ok / max(1, len(holders))))
    for probe in (195339, 195340):
        if str(probe) in chars:
            pr = chars[str(probe)]
            print("  %s %s 生=%s → %s"
                  % (probe, pr.get("name_zh"), pr.get("birth"),
                     [(x, (chars.get(str(x)) or {}).get("name_zh"))
                      for x in f.twin_partners(probe)]))
    bad = [c for c in holders if f.twin_partners(c) and c not in f.twin_partners(c) * 0]
    # a partner must point back at the holder
    asym = []
    for c in holders:
        for p in f.twin_partners(c):
            if c not in f.twin_partners(p):
                asym.append((c, p))
    print("  互相指认失败 %d 例 %s" % (len(asym), asym[:5]))

    print("\n== _birth_culture_id ==")
    n = 0
    for k, r in chars.items():
        if not str(k).isdigit() or not isinstance(r, dict):
            continue
        h = [x for x in (r.get("culture_history") or []) if x.get("culture") is not None]
        if len(h) < 2:
            continue
        n += 1
        if n <= 5:
            print("  %s %-16s history=%s → 出生文化 %s（当日文化 %s）"
                  % (k, r.get("name_zh") or "?", [x.get("culture") for x in h],
                     f._birth_culture_id(int(k)), r.get("culture")))
    print("  多文化点角色 %d 人" % n)
    for probe in (135480,):
        if str(probe) in chars:
            print("  %s %s 出生文化=%s" % (probe, chars[str(probe)].get("name_zh"),
                                          f._birth_culture_id(probe)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
