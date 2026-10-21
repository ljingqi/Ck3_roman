# -*- coding: utf-8 -*-
"""v117 取证探针 · 第八段：同一段代码、两份缓存 —— 天贵福那一行「天皇帝 vs 前工部尚书」的对照。

S14  A) 实跑缓存 player_17066495.json（1283, 无 44503 记录）
     B) 旧卷缓存 player_50565938.json（洪希晏 1245/1247, 有 44503 记录）
     两份都用 melt_1283，各自 as_of = 自己的终年，打印：
       characters[44503].death / _anchor_date / official_title / person_label(full)
       display_name（说明「洪」从哪来）/ _saint_lines 封圣行

用法：& tools\\py.ps1 tools\\tests\\v117_probe_gf8.py
输出追加 logs/v117/v117_probe_gf.txt。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import cache_lib as cl  # noqa: E402
import facts as F  # noqa: E402

DATA = os.path.join(ROOT, "output", "洪氏2", "data")
OUT = os.path.join(ROOT, "logs", "v117_probe_gf.txt")
CID = 44503
_buf = []


def P(*a):
    s = " ".join(str(x) for x in a)
    _buf.append(s)
    print(s, flush=True)


def flush():
    with open(OUT, "a", encoding="utf-8") as fp:
        fp.write("\n".join(_buf) + "\n")
    _buf.clear()


def run(label, cache_fn, as_of, melt, names):
    cache = cl.load_cache(os.path.join(DATA, cache_fn))
    rec = (cache.get("characters") or {}).get(str(CID)) or {}
    P(f"\n[S14] ===== {label} =====")
    P(f"[S14] 缓存 {cache_fn}: last_date={cache.get('last_date')!r} "
      f"characters 条数={len(cache.get('characters') or {})} "
      f"player_id={cache.get('player_id')} "
      f"player_death={json.dumps(cache.get('player_death'), ensure_ascii=False)}")
    P(f"[S14] characters[{CID}] 存在={bool(rec)} death={(rec.get('death') or {}).get('date')!r} "
      f"name_zh={rec.get('name_zh')!r} house_name={rec.get('house_name')!r} "
      f"dynasty_name={rec.get('dynasty_name')!r} name_full={rec.get('name_full')!r} "
      f"culture={rec.get('culture')!r}")
    f = F.Facts(cache, melt, names, as_of=as_of)
    for d in ("952.1.29", "952.1.28", None):
        ad = f._anchor_date(CID, d)
        P(f"[S14]   date={d!r} -> _anchor_date={ad!r} official_title={f.official_title(CID, d)!r} "
          f"person_label(full)={f.person_label(CID, d, 'full')!r} "
          f"person_label(brief)={f.person_label(CID, d, 'brief')!r}")
    P(f"[S14]   _gen_end_date(f,{CID})={F._gen_end_date(f, CID)!r}")
    try:
        tree = F.genealogy_tree(f)
        node = next((n for n in (tree or {}).get("nodes") or []
                     if n.get("id") == CID), None)
        P(f"[S14]   家谱节点: {json.dumps(node, ensure_ascii=False)}")
        P(f"[S14]   封圣行: {json.dumps(F._saint_lines(f, tree), ensure_ascii=False)}")
    except Exception as e:  # noqa: BLE001
        P(f"[S14]   家谱/封圣行失败: {e}")
    dn = cl.display_name(cache, CID, melt=melt, names_path=names,
                         chars=f._chars, memo={}, date="952.1.28")
    P(f"[S14]   display_name(952.1.28)={dn!r}")
    flush()
    del f, cache


def main():
    P("\n" + "=" * 78)
    P("== [S14] 同一 melt_1283、两份缓存：天贵福那一行的两种结果 ==")
    melt = cl.load_melt(cl.melt_file_exists(os.path.join(DATA, "melt_1283_01_01.json")))
    names = os.path.join(DATA, "names.json")
    if not os.path.isfile(names):
        names = os.path.join(ROOT, "data", "names.json")
    run("A) 实跑缓存 player_17066495.json（洪光通 终传 1283）",
        "player_17066495.json", "1283.9.11", melt, names)
    run("B) 旧卷缓存 player_50565938.json（洪希晏 终传 1247）",
        "player_50565938.json", "1247.1.1", melt, names)
    flush()


if __name__ == "__main__":
    main()
