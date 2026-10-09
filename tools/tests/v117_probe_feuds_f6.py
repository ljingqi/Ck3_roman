# -*- coding: utf-8 -*-
"""v117 取证 [F-6]：真实 _weight/_n/_first 下的前 10 名与「宁浦洪氏能否进 5 家」。

四个口径（其余一律用 facts.py 原文，见下）：
  base = 生产现状：DETECT=my_houses(29 家)，other = 非 my_houses
  A    = DETECT=OWN=祖先链{31062,16799492,20237,12295}，other = 非 OWN
  B    = DETECT=my_houses(29 家)，other = 非 OWN（父代理给的方案 B 字面写法）
  C    = 最小改动：other = 非 my_houses，为空时回退到 非 OWN（检测仍用 my_houses）

这些口径的差别只在 ①②③ 两行；`_weight`(_hist_events+_node_events+_nodes)、节点折叠、
`_merge_and_cap_feuds` 的合并/排序全部用 facts.py 原文（inspect.getsource 取源码 + 定点替换，
替换失败即 assert 报错，不会静默走偏）。仅本进程内存，不改 facts.py。

输出：追加到 logs/v117_probe_feuds.txt 的 [F-6] 节。
"""
import inspect
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

FOLDER = "洪氏2"
PID = 17066495
AS_OF = "1283.9.11"
LOG_PATH = os.path.join(ROOT, "logs", "v117_probe_feuds.txt")

_buf = []


def w(s=""):
    _buf.append(str(s))
    print(str(s), flush=True)


def _own_line_snippet():
    return """        # ---- v117 探针注入：OWN/检测口径 ----
        _own_line = set()
        _p = h0 if isinstance(h0, int) else None
        _dh = (self.melt.get("dynasties") or {}).get("dynasty_house") or {}
        for _ in range(12):
            if _p is None or _p in _own_line:
                break
            _own_line.add(_p)
            _e = _dh.get(str(_p)) or {}
            _p = _e.get("parent_dynasty_house")
        DETECT = %s
        OWN = %s
        self._v117_own_line = sorted(_own_line)
        self._v117_detect = sorted(DETECT)
"""


def build_variant(mode):
    src = inspect.getsource(F.Facts.house_feuds).replace("\r\n", "\n")
    src = src.replace("    def house_feuds(self):", "def house_feuds(self):", 1)

    if mode == "base":
        det, own = "set(my_houses)", "set(my_houses)"
    elif mode == "A":
        det = own = "set(_own_line)"
    else:                                  # B / C 都是「检测用全 dynasty，other 用祖先链」
        det, own = "set(my_houses)", "set(_own_line)"

    anchor = "        if not my_houses:\n            return []\n"
    assert anchor in src, "结构不符: my_houses 空值返回段"
    src = src.replace(anchor, anchor + (_own_line_snippet() % (det, own)))

    a1 = "            if not any(h in my_houses for h in hs):"
    assert a1 in src, "结构不符: ① 检测行"
    src = src.replace(a1, "            if not any(h in DETECT for h in hs):")

    a2 = "            other = [h for h in hs if h not in my_houses]"
    assert a2 in src, "结构不符: ③ other 行"
    if mode == "C":
        # 最小改动：原有语义不动，只在 other 为空时回退到祖先链之外的 house
        src = src.replace(
            a2, "            other = [h for h in hs if h not in my_houses] \\\n"
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
    assert a in src, "结构不符: _merge_and_cap_feuds pop 段"
    src = src.replace(a, "        # v117 探针：保留 _first/_w/_n 供打印\n")
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


def src_rows(raw, labels):
    return [r for r in raw if str(r.get("house_label") or "") in labels]


def main():
    t0 = time.time()
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache_path = os.path.join(data, f"player_{PID}.json")
    names = os.path.join(data, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    melt_path = os.path.join(data, "melt_1283_01_01.json")

    w("")
    w("#" * 100)
    w("# [F-6] 真实 _weight / _n / _first 下的前 10 名：修好 ③ 之后宁浦洪氏能否进 5 家")
    w(f"# 时间 {time.strftime('%Y-%m-%d %H:%M:%S')}  熔件 melt_1283_01_01.json"
      f"（cache.last_date=1283.1.1，即实跑那一档）  as_of={AS_OF}")
    w("#" * 100)
    cache = cl.load_cache(cache_path)
    melt = cl.load_melt(melt_path)
    f = F.Facts(cache, melt, names, as_of=AS_OF, decade=None)
    w(f"    缓存+熔件+Facts 就绪 {time.time() - t0:.1f}s")

    w("")
    w("  _weight 公式（facts.py:11839）：_w = len(_hist_events) + len(_node_events) + len(_nodes)")
    w("    · _hist_events：该行 history 逐条过 ①as_of 截断(11767-11768) ②decade 下界(11769-11770)")
    w("      ③丧偶离婚丢弃(11777) ④被动世仇囚禁行丢弃(11781) ⑤_rerender_feud_event 为空丢弃(11785-11790)")
    w("      ⇒ 窗口内、且渲染成功的条数，**不是 history 全量条数**")
    w("    · _node_events：_house_war_nodes(11813) + purge 行(11840-11846)")
    w("    · _nodes：_house_prison_nodes(11828) 折叠前的个人数")

    f.HOUSE_FEUDS_MAX = 10 ** 6
    F.__dict__["_V117_MERGE"] = build_merge_variant()

    results = {}
    for mode, desc in (("base", "生产现状：检测=29 家 my_houses，other=非 my_houses"),
                       ("A", "方案 A：检测=OWN=祖先链{31062,16799492,20237,12295}"),
                       ("B", "方案 B：检测=29 家 my_houses，other=非 OWN"),
                       ("C", "方案 C(最小改动)：other=非 my_houses，为空才回退到非 OWN")):
        fn = build_variant(mode)
        t1 = time.time()
        rows = fn(f)
        results[mode] = rows
        raw = getattr(f, "_v117_raw", [])
        w("")
        w("=" * 100)
        w(f"[{mode}] {desc}")
        w(f"      OWN={getattr(f, '_v117_own_line', None)}")
        w(f"      DETECT={getattr(f, '_v117_detect', None)}")
        w(f"      合并前原始行 {len(raw)} 条 → 合并后 {len(rows)} 个家族（{time.time() - t1:.1f}s）")
        w("=" * 100)
        top_table(rows, f"[{mode}] 前 10 名（排序键 -rank(level), -_w, -_n, _first, house_label）")
        w(f"    [{mode}] 前 5 名 = {[r.get('house_label') for r in rows[:5]]}")
        w("")
        w(f"    [{mode}] 关注行的合并前来源（key / level / weight / pairs 数 / 首条）：")
        for r in sorted(src_rows(raw, {"宁浦洪氏", "苻氏", "鄂陵潘氏", "邕州洪氏",
                                       "哈德良波利斯洪氏", "闽洪氏", "南昌洪氏"}),
                        key=lambda x: (str(x.get("house_label")), -int(x.get("weight") or 0))):
            w(f"        key={r.get('_k')} label={str(r.get('house_label')):<20} "
              f"level={str(r.get('level')):<5} weight={r.get('weight')} "
              f"pairs={len(r.get('pairs') or [])} 首条={(r.get('pairs') or [('', '')])[0][0]}")
        w("")
        w(f"    [{mode}] 关注行的合并后结果（_w/_n/_first 为真实值）：")
        for label in ("宁浦洪氏", "苻氏", "鄂陵潘氏", "闽洪氏", "南昌洪氏", "邕州洪氏"):
            hit = [r for r in rows if str(r.get("house_label")) == label]
            if not hit:
                w(f"        {label:<12} 未出现")
                continue
            r = hit[0]
            pos = rows.index(r) + 1
            w(f"        {label:<12} 第 {pos} 名 level={r.get('level')} "
              f"_w={r.get('_w')} _n={r.get('_n')} _first={r.get('_first')}")

    # ---- 结论行 ----
    w("")
    w("=" * 100)
    w("[F-6 结论] 5 个名额里宁浦洪氏是否进得去")
    w("=" * 100)
    for mode in ("base", "A", "B", "C"):
        rows = results[mode]
        top5 = [r.get("house_label") for r in rows[:5]]
        hit = [r for r in rows if str(r.get("house_label")) == "宁浦洪氏"]
        if not hit:
            w(f"    {mode}: 宁浦洪氏 不在候选里；前 5 = {top5}")
            continue
        r = hit[0]
        pos = rows.index(r) + 1
        w(f"    {mode}: 宁浦洪氏 第 {pos} 名 level={r.get('level')} _w={r.get('_w')} "
          f"_n={r.get('_n')} _first={r.get('_first')} → 进前5={'是' if pos <= 5 else '否'}")
        w(f"          前 5 = {top5}")
    for mode in ("base", "A", "B", "C"):
        for label in ("苻氏",):
            hit = [r for r in results[mode] if str(r.get("house_label")) == label]
            if hit:
                r = hit[0]
                w(f"    对照 {mode} {label}: 第 {results[mode].index(r) + 1} 名 level={r.get('level')} "
                  f"_w={r.get('_w')} _n={r.get('_n')} _first={r.get('_first')}")

    w(f"\n# [F-6] 耗时 {time.time() - t0:.1f}s")
    with open(LOG_PATH, "a", encoding="utf-8") as fp:
        fp.write("\n".join(_buf) + "\n")
    print(f"\n[追加写盘] {LOG_PATH}")


if __name__ == "__main__":
    main()
