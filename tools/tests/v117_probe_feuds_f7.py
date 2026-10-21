# -*- coding: utf-8 -*-
"""v117 取证 [F-7]：标签规则写清 + B′（外姓优先，只有两端都在本朝代内才取非自家世系）+ 1245 档对照。

口径（区别只在 ①②③ 三行，其余一律 facts.py 原文 via inspect.getsource）：
  base : ① any(h in my_houses)       ③ other = [h not in my_houses]
  A    : ① any(h in OWN=祖先链)      ③ other = [h not in OWN]
  B    : ① any(h in my_houses)       ③ other = [h not in OWN]      ← 父代理指出的副作用版
  B′   : ① any(h in my_houses)       ③ other = [h not in my_houses] or [h not in OWN]   ← 修正版

输出：追加到 logs/v117/v117_probe_feuds.txt 的 [F-7] 节。
"""
import gc
import inspect
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

FOLDER = "洪氏2"
LOG_PATH = os.path.join(ROOT, "logs", "v117_probe_feuds.txt")

_buf = []


def w(s=""):
    _buf.append(str(s))
    print(str(s), flush=True)


def build_variant(mode):
    src = inspect.getsource(F.Facts.house_feuds).replace("\r\n", "\n")
    src = src.replace("    def house_feuds(self):", "def house_feuds(self):", 1)

    if mode == "base":
        det, own = "set(my_houses)", "set(my_houses)"
    elif mode == "A":
        det = own = "set(_own_line)"
    else:                              # B / B'
        det, own = "set(my_houses)", "set(_own_line)"

    anchor = "        if not my_houses:\n            return []\n"
    assert anchor in src, "结构不符: my_houses 空值返回段"
    inject = anchor + f"""        _own_line = set()
        _p = h0 if isinstance(h0, int) else None
        _dh = (self.melt.get("dynasties") or {{}}).get("dynasty_house") or {{}}
        for _ in range(12):
            if _p is None or _p in _own_line:
                break
            _own_line.add(_p)
            _e = _dh.get(str(_p)) or {{}}
            _p = _e.get("parent_dynasty_house")
        DETECT = {det}
        OWN = {own}
        self._v117_own_line = sorted(_own_line)
"""
    src = src.replace(anchor, inject)

    a1 = "            if not any(h in my_houses for h in hs):"
    assert a1 in src, "结构不符: ① 检测行"
    src = src.replace(a1, "            if not any(h in DETECT for h in hs):")

    a2 = "            other = [h for h in hs if h not in my_houses]"
    assert a2 in src, "结构不符: ③ other 行"
    if mode == "B'":
        src = src.replace(a2, "            other = [h for h in hs if h not in my_houses] \\\n"
                              "                or [h for h in hs if h not in OWN]")
    else:
        src = src.replace(a2, "            other = [h for h in hs if h not in OWN]")

    a3 = "        return self._merge_and_cap_feuds(out)"
    assert a3 in src, "结构不符: 结尾 return"
    src = src.replace(a3, "        self._v117_raw = list(out)\n"
                          "        return _V117_MERGE(self, out)")

    a4 = '            out.append({\n                "house": _hlabel_raw,\n'
    assert a4 in src, "结构不符: out.append 段"
    src = src.replace(a4, '            out.append({\n                "_k": _k,\n'
                          '                "house": _hlabel_raw,\n')

    ns = {}
    exec(compile(src, f"<house_feuds_v117_{mode}>", "exec"), F.__dict__, ns)
    return ns["house_feuds"]


def build_merge_variant():
    src = inspect.getsource(F.Facts._merge_and_cap_feuds).replace("\r\n", "\n")
    src = src.replace("    def _merge_and_cap_feuds(self, rows):",
                      "def _merge_and_cap_feuds(self, rows):", 1)
    a = ('        for r in out:\n'
         '            r.pop("_first", None)\n'
         '            r.pop("_w", None)\n'
         '            r.pop("_n", None)\n')
    assert a in src, "结构不符: pop 段"
    src = src.replace(a, "        # v117 探针：保留 _first/_w/_n\n")
    ns = {}
    exec(compile(src, "<merge_and_cap_v117>", "exec"), F.__dict__, ns)
    return ns["_merge_and_cap_feuds"]


def top_table(rows, title, n=10):
    w("")
    w(f"  {title}")
    w(f"    {'#':>2}  {'house_label':<20} {'level':<5} {'_w':>4} {'_n':>4}  _first")
    for i, r in enumerate(rows[:n], 1):
        w(f"    {i:>2}  {str(r.get('house_label')):<20} {str(r.get('level')):<5} "
          f"{int(r.get('_w') or 0):>4} {int(r.get('_n') or 0):>4}  {r.get('_first')}")
    if len(rows) > n:
        w(f"    … 共 {len(rows)} 行")


def _setup(data):
    names = os.path.join(data, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    F.__dict__["_V117_MERGE"] = build_merge_variant()
    return names


def run_phase(melt_name, cache_name, as_of, tag, modes, extra_label=None):
    data = os.path.join(ROOT, "output", FOLDER, "data")
    names = _setup(data)
    cache = cl.load_cache(os.path.join(data, cache_name))
    w("")
    w("=" * 100)
    w(f"[{tag}] 熔件 {melt_name}  缓存 {cache_name}  as_of={as_of}")
    w("=" * 100)
    w(f"    cache.last_date={cache.get('last_date')} dynasty_id={cache.get('dynasty_id')} "
      f"player_id={cache.get('player_id')}")
    t0 = time.time()
    melt = cl.load_melt(os.path.join(data, melt_name), use_memo=False)
    w(f"    熔件载入 {time.time() - t0:.1f}s")
    t1 = time.time()
    f = F.Facts(cache, melt, names, as_of=as_of, decade=None)
    w(f"    Facts 就绪 {time.time() - t1:.1f}s")

    prec = (cache.get("characters") or {}).get(str(cache.get("player_id"))) or {}
    h0 = prec.get("dynasty_house")
    did = cache.get("dynasty_id")
    dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
    myh = set()
    if isinstance(h0, int):
        myh.add(h0)
    if did is not None:
        for hid, e in dh.items():
            if isinstance(e, dict) and e.get("dynasty") == did:
                myh.add(int(hid))
    w(f"    主角 dynasty_house={h0}；dynasty={did} 下 house 共 {len(myh)} 个")
    if extra_label:      # 关心的那两家的信息
        for _h in extra_label:
            e = dh.get(str(_h)) or {}
            w(f"    关注 house {_h}: 名={cl.house_name_zh(melt, _h)!r} "
              f"dynasty={e.get('dynasty')} found={e.get('found_date')!r} "
              f"parent={e.get('parent_dynasty_house')} 属 my_houses={'是' if _h in myh else '否'}")

    f.HOUSE_FEUDS_MAX = 10 ** 6
    out = {}
    raws = {}
    for mode in modes:
        fn = build_variant(mode)
        t2 = time.time()
        rows = fn(f)
        out[mode] = rows
        raw = list(getattr(f, "_v117_raw", []))
        raws[mode] = raw
        w("")
        w(f"  ── 口径 {mode}: OWN={getattr(f, '_v117_own_line', None)}  原始行 {len(raw)} → 家族 {len(rows)}"
          f"  ({time.time() - t2:.1f}s)")
        top_table(rows, f"[{tag}/{mode}] 前 10 名")
        w(f"    [{tag}/{mode}] 前 5 名 = {[r.get('house_label') for r in rows[:5]]}")

    # 关心的行（raw 必须取本口径自己的那一份）
    if extra_label:
        w("")
        w(f"    [{tag}] 关注家族（合并前来源 + 合并后名次）：")
        for mode in modes:
            raw = raws[mode]
            rows = out[mode]
            for label in ("宁浦洪氏", "哈德良波利斯洪氏", "苻氏", "托格力氏"):
                src = [r for r in raw if str(r.get("house_label")) == label]
                if not src:
                    continue
                w(f"      [{mode}] {label}: 来源行 "
                  f"{[(r.get('_k'), r.get('level'), r.get('weight'), len(r.get('pairs') or [])) for r in src]}")
                hit = [r for r in rows if str(r.get("house_label")) == label]
                if hit:
                    r = hit[0]
                    w(f"      [{mode}] {label}: 合并后 _w={r.get('_w')} _n={r.get('_n')} "
                      f"level={r.get('level')} _first={r.get('_first')} 第 {rows.index(r) + 1} 名")
    del f, melt
    gc.collect()
    return out


def main():
    w("")
    w("#" * 100)
    w("# [F-7R] 修正打印 bug 后重跑（上一节 [F-7] 的名次/_w/_n 数字正确，只有「合并前来源」那几行")
    w("#        错读了最后一个口径的 raw；本节即权威版）")
    w(f"# 时间 {time.strftime('%Y-%m-%d %H:%M:%S')}")
    w("#" * 100)
    w("  ①②③ 三行的口径（其余逐字用 facts.py 原文）：")
    w("    base : ① any(h in my_houses)   ③ other = [h for h in hs if h not in my_houses]   ← 生产现状")
    w("    A    : ① any(h in OWN)         ③ other = [h for h in hs if h not in OWN]")
    w("           OWN = h0 的 parent_house 祖先链（31062 → 16799492 → 20237 → 12295）")
    w("    B    : ① any(h in my_houses)   ③ other = [h for h in hs if h not in OWN]        ← 有副作用")
    w("    B′   : ① any(h in my_houses)   ③ other = [h for h in hs if h not in my_houses]")
    w("                                          or [h for h in hs if h not in OWN]        ← 修正版")
    w("  注：[F-2] 里标着 base 的那一段是早期版本的打印错误（当时 OWN 一律被当成祖先链，")
    w("      所以 [F-2] 的 base 实为方案 B）；[F-6] 与本节已修正，base 与 B 的差别就是 ③ 的比较集合。")

    # ── 1283 档：base 与 B′ ──
    res = run_phase("melt_1283_01_01.json", "player_17066495.json", "1283.9.11",
                    "F-7A 1283 档", ("base", "B'"), extra_label=(22285, 31062))
    base, bp = res["base"], res["B'"]
    lb = {str(r.get("house_label")) for r in base}
    lp = {str(r.get("house_label")) for r in bp}
    w("")
    w(f"    [F-7A] B′ 相对 base 新增的家族 {sorted(lp - lb)}")
    w(f"    [F-7A] B′ 相对 base 消失的家族 {sorted(lb - lp)}")
    rows = bp
    hit = [r for r in rows if str(r.get("house_label")) == "宁浦洪氏"]
    if hit:
        r = hit[0]
        pos = rows.index(r) + 1
        w("")
        w(f"    [F-7A 关键] B′ 下 宁浦洪氏 第 {pos} 名 level={r.get('level')} _w={r.get('_w')} "
          f"_n={r.get('_n')} _first={r.get('_first')}")
        w(f"    排在它前面的每一家：")
        for i, x in enumerate(rows[:pos - 1], 1):
            w(f"        {i}. {str(x.get('house_label')):<20} {str(x.get('level')):<5} "
              f"_w={x.get('_w')} _n={x.get('_n')} _first={x.get('_first')}")
        w(f"    第 5 名（最后一个名额）= {rows[4].get('house_label')} "
          f"{rows[4].get('level')} _w={rows[4].get('_w')} _n={rows[4].get('_n')}")
        w(f"    ⇒ HOUSE_FEUDS_MAX=5 下宁浦洪氏{'进' if pos <= 5 else '【不进】'}成稿；"
          f"要进榜至少需要 HOUSE_FEUDS_MAX={pos}")
    w(f"    [F-7A] 对照 base 前 5 = {[r.get('house_label') for r in base[:5]]}")
    w(f"    [F-7A] 对照 B' 前 5 = {[r.get('house_label') for r in bp[:5]]}")

    # ── 1245 档（洪希晏 1247 终传）──
    res2 = run_phase("melt_1245_01_01.json.xz", "player_50565938.json", "1247.1.1",
                     "F-7B 1245 档(洪希晏 1247 终传)", ("base", "B'"), extra_label=(22285, 31062))
    for mode in ("base", "B'"):
        rows = res2[mode]
        top5 = [r.get("house_label") for r in rows[:5]]
        w(f"    [F-7B] {mode} 前 5 = {top5}")
        shi = [r for r in rows if str(r.get("house_label")) in ("宁浦洪氏",)]
        for r in shi:
            w(f"    [F-7B] {mode} 宁浦洪氏 第 {rows.index(r) + 1} 名 level={r.get('level')} "
              f"_w={r.get('_w')} _n={r.get('_n')} _first={r.get('_first')}")
    bp2 = res2["B'"]
    hit2 = [r for r in bp2 if str(r.get("house_label")) == "宁浦洪氏"]
    if hit2:
        r = hit2[0]
        pos = bp2.index(r) + 1
        w("")
        w(f"    [F-7B 关键] 1245 档修好 ③(B′) 后 宁浦洪氏 第 {pos} 名 level={r.get('level')} "
          f"_w={r.get('_w')} _n={r.get('_n')} _first={r.get('_first')} "
          f"⇒ HOUSE_FEUDS_MAX=5 下{'进' if pos <= 5 else '不进'}成稿")
        w(f"    排在它前面的每一家：")
        for i, x in enumerate(bp2[:pos - 1], 1):
            w(f"        {i}. {str(x.get('house_label')):<20} {str(x.get('level')):<5} "
              f"_w={x.get('_w')} _n={x.get('_n')} _first={x.get('_first')}")

    with open(LOG_PATH, "a", encoding="utf-8") as fp:
        fp.write("\n".join(_buf) + "\n")
    print(f"\n[追加写盘] {LOG_PATH}")


if __name__ == "__main__":
    main()
