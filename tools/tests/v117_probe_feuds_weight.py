# -*- coding: utf-8 -*-
"""v117 取证（第三轮）：真实 _weight 下，「修好 ③」后宁浦洪氏能否进 HOUSE_FEUDS_MAX=5？

做法（不改任何生产代码）：
  * 整载一次 melt_1283_01_01.json（cache["last_date"]=1283.1.1 对应的正是这一档，即实跑所用档）；
  * 构造真实 facts.Facts(cache, melt, names, as_of="1283.9.11", decade=None)；
  * 用 inspect.getsource 取 **facts.py 里 house_feuds 的真源码**，只把三处替换掉：
        det = any(h in DETECT for h in hs)      # 原：my_houses
        other = [h for h in hs if h not in OWN] # 原：my_houses
    其余（_weight 公式、war/prison 节点、purge 折叠、_merge_and_cap_feuds）一律用生产代码原文；
  * 变体：base(原样) / A(自己的集合 = h0 的 parent_house 祖先链, 检测也用该集合)
          / B(检测仍用 my_houses，other 用祖先链集合)；
  * 把 HOUSE_FEUDS_MAX 临时放大到 1e6，让 _merge_and_cap_feuds 返回**全部**已排序行（带 _w/_n/_first）。

参数：--melt=<文件名> 可换档（默认 melt_1283_01_01.json）。
输出：追加到 logs/v117/v117_probe_feuds.txt。
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


def build_variant(mode):
    """house_feuds 的真源码 + 最小替换（DETECT/OWN）。返回可调用的函数。"""
    src = inspect.getsource(F.Facts.house_feuds)
    src = src.replace("\r\n", "\n")
    # inspect 返回的是带 4 空格缩进的类内方法：只把 def 行顶格，方法体保持原有缩进层级
    src = src.replace("    def house_feuds(self):", "def house_feuds(self):", 1)

    if mode == "base":                      # 生产原样
        det_code, own_code = "set(my_houses)", "set(my_houses)"
    elif mode == "A":                       # 只有 parent_house 祖先链算自家（检测也用）
        det_code = own_code = "set(_own_line)"
    else:                                   # B: 检测仍用全 dynasty，对方用祖先链
        det_code, own_code = "set(my_houses)", "set(_own_line)"

    anchor = """        if not my_houses:
            return []
"""
    assert anchor in src, "house_feuds 源码结构与预期不符（my_houses 空值返回段）"
    inject = anchor + f"""        # ---- v117 探针注入：{mode} ----
        _own_line = set()
        _p = h0 if isinstance(h0, int) else None
        _dh = (self.melt.get("dynasties") or {{}}).get("dynasty_house") or {{}}
        for _ in range(12):
            if _p is None or _p in _own_line:
                break
            _own_line.add(_p)
            _e = _dh.get(str(_p)) or {{}}
            _p = _e.get("parent_dynasty_house")
        DETECT = {det_code}
        OWN = {own_code}
        self._v117_own_line = sorted(_own_line)
        self._v117_detect = sorted(DETECT)
"""
    src = src.replace(anchor, inject)

    a1 = "            if not any(h in my_houses for h in hs):"
    b1 = "            if not any(h in DETECT for h in hs):"
    assert a1 in src, "house_feuds 源码结构与预期不符（① 检测行）"
    src = src.replace(a1, b1)

    a2 = "            other = [h for h in hs if h not in my_houses]"
    b2 = "            other = [h for h in hs if h not in OWN]"
    assert a2 in src, "house_feuds 源码结构与预期不符（③ other 行）"
    src = src.replace(a2, b2)

    # 保留合并前的原始行（探针用），并把 _merge_and_cap_feuds 结尾的 pop 去掉，好读到 _w/_n/_first
    a3 = "        return self._merge_and_cap_feuds(out)"
    assert a3 in src, "house_feuds 源码结构与预期不符（结尾 return）"
    src = src.replace(a3, "        self._v117_raw = list(out)\n"
                          "        return _V117_MERGE(self, out)")

    g = F.__dict__
    ns = {}
    exec(compile(src, f"<house_feuds_v117_{mode}>", "exec"), g, ns)
    return ns["house_feuds"]


def build_merge_variant():
    """_merge_and_cap_feuds 的真源码，只去掉结尾把 _w/_n/_first 弹掉的 4 行。"""
    src = inspect.getsource(F.Facts._merge_and_cap_feuds).replace("\r\n", "\n")
    src = src.replace("    def _merge_and_cap_feuds(self, rows):",
                      "def _merge_and_cap_feuds(self, rows):", 1)
    a = """        for r in out:
            r.pop("_first", None)
            r.pop("_w", None)
            r.pop("_n", None)
"""
    assert a in src, "_merge_and_cap_feuds 源码结构与预期不符（pop 段）"
    src = src.replace(a, "        # v117 探针：保留 _first/_w/_n 供打印\n")
    ns = {}
    exec(compile(src, "<merge_and_cap_v117>", "exec"), F.__dict__, ns)
    return ns["_merge_and_cap_feuds"]


def show_rows(rows, title, limit=8):
    w("")
    w(f"  {title}")
    w(f"    {'#':>2}  {'house_label':<20} {'level':<6} {'_w':>4} {'_n':>4} {'_first':<12} house(原标签)")
    for i, r in enumerate(rows[:limit], 1):
        w(f"    {i:>2}  {str(r.get('house_label')):<20} {str(r.get('level')):<6} "
          f"{int(r.get('_w') or 0):>4} {int(r.get('_n') or 0):>4} "
          f"{str(r.get('_first')):<12} {r.get('house')!r}")
    if len(rows) > limit:
        w(f"    … 共 {len(rows)} 行")


def main():
    t0 = time.time()
    melt_name = "melt_1283_01_01.json"
    for a in sys.argv[1:]:
        if a.startswith("--melt="):
            melt_name = a.split("=", 1)[1]
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache_path = os.path.join(data, f"player_{PID}.json")
    names = os.path.join(data, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    melt_path = os.path.join(data, melt_name)

    w("")
    w("#" * 100)
    w(f"# [F 补篇] 真实 _weight 下「修好 ③」后的前八名 —— 熔件 {melt_name}")
    w(f"# 时间 {time.strftime('%Y-%m-%d %H:%M:%S')}  "
      f"({os.path.getsize(melt_path):,} 字节)")
    w("#" * 100)
    cache = cl.load_cache(cache_path)
    w(f"[1] 缓存载入 {time.time() - t0:.1f}s; last_date={cache.get('last_date')} "
      f"dynasty_id={cache.get('dynasty_id')}")
    t1 = time.time()
    melt = cl.load_melt(melt_path)
    w(f"[2] 熔件整载完成 {time.time() - t1:.1f}s（本节是该档唯一一次整载）")
    f = F.Facts(cache, melt, names, as_of=AS_OF, decade=None)
    w(f"[3] Facts 构造完成 {time.time() - t1:.1f}s")

    # ---- 1232.12.16 那条「哈德良波利斯洪 × 宁浦洪」关系行在本档是否还在 ----
    w("")
    w("=" * 100)
    w("[F-0] 本档 house_relations 里，「宁浦洪(22285) × 哈德良波利斯洪(31062)」这条 1232 世仇行还在不在")
    w("=" * 100)
    db = (melt.get("house_relations") or {}).get("database") or {}
    pair = [k for k, r in db.items() if isinstance(r, dict)
            and 22285 in (r.get("houses") or []) and 31062 in (r.get("houses") or [])]
    w(f"    houses 同时含 22285 与 31062 的行: {len(pair)} {pair}")
    w(f"    key=83898143（1233/1245 档里那条 feud 行）在本档: {'在' if '83898143' in db else '【不在】'}")
    near = [(k, e.get("date")) for k, r in db.items() if isinstance(r, dict)
            for e in (r.get("history") or []) if str(e.get("date")) == "1232.12.16"]
    w(f"    全库 history 中日期为 1232.12.16 的条目：{len(near)} {near[:12]}")
    w("    （对照：melt_1233_01_01 与 melt_1245_01_01 里 key=83898143 houses=[31062, 22285] "
      "level=feud 存在，见 logs/v117/v117_probe_feuds_era.txt:119-122,179,196-203,264）")

    # ---- 生产原样 ----
    w("")
    w("=" * 100)
    w("[F-1] 生产原样 house_feuds()（HOUSE_FEUDS_MAX=5）—— 与成篇对照")
    w("=" * 100)
    base_rows = f.house_feuds()
    for r in base_rows:
        w(f"    {r.get('house_label'):<18} level={r.get('level')} 事件 {len(r.get('events') or [])} 条")
    w(f"    首条事件示例: {((base_rows[0].get('events') or [''])[0] if base_rows else '')}")

    # ---- 变体 ----
    f.HOUSE_FEUDS_MAX = 10 ** 6
    F.__dict__["_V117_MERGE"] = build_merge_variant()   # 仅本进程内存，facts.py 文件不动
    results = {}
    for mode in ("base", "A", "B"):
        fn = build_variant(mode)
        t2 = time.time()
        rows = fn(f)
        results[mode] = rows
        raw = getattr(f, "_v117_raw", [])
        interest = [r for r in raw
                    if str(r.get("house_label") or "") in
                    ("宁浦洪氏", "苻氏", "鄂陵潘氏", "邕州洪氏", "哈德良波利斯洪氏",
                     "南昌洪氏", "闽洪氏")]
        w("")
        w(f"    [合并前原始行] label∈{{宁浦洪氏, 苻氏, 鄂陵潘氏, 邕州洪氏}} 的行（{mode}）:")
        for r in sorted(interest, key=lambda x: str(x.get("house_label"))):
            w(f"        {str(r.get('house_label')):<20} level={r.get('level')} "
              f"weight={r.get('weight')} pairs={len(r.get('pairs') or [])} "
              f"首条={((r.get('pairs') or [('', '')])[0][0])}")
        w("")
        w("=" * 100)
        w(f"[F-2] 变体 {mode}: DETECT={f._v117_detect}  OWN={f._v117_own_line}")
        w(f"      通过 ①②③④ 并完成合并的家族行数 = {len(rows)}   ({time.time() - t2:.1f}s)")
        w("=" * 100)
        show_rows(rows, f"按真实排序键 (-level排名, -_w, -_n, _first, label) 的前 8 名（{mode}）")

    # ---- 宁浦洪氏排名 ----
    w("")
    w("=" * 100)
    w("[F-3] 各方案下「宁浦洪氏」的排名")
    w("=" * 100)
    for mode in ("base", "A", "B"):
        rows = results[mode]
        pos = [i for i, r in enumerate(rows, 1)
               if str(r.get("house_label") or "").startswith("宁浦洪")]
        if not pos:
            w(f"    {mode}: 未出现宁浦洪氏")
            continue
        for p in pos:
            r = rows[p - 1]
            w(f"    {mode}: 第 {p} 名  level={r.get('level')} _w={r.get('_w')} "
              f"_n={r.get('_n')} _first={r.get('_first')} 进前5={'是' if p <= 5 else '否'}")
        w(f"        （第 5 名 = {rows[4].get('house_label')} _w={rows[4].get('_w')} "
          f"_n={rows[4].get('_n')} _first={rows[4].get('_first')}）" if len(rows) >= 5 else "")

    # ---- A/B 差异 ----
    w("")
    w("=" * 100)
    w("[F-4] 方案 A 与方案 B 的差异行（合并后按 house_label）")
    w("=" * 100)
    la = {str(r.get("house_label")): r for r in results["A"]}
    lb = {str(r.get("house_label")): r for r in results["B"]}
    only_b = [k for k in lb if k not in la]
    only_a = [k for k in la if k not in lb]
    w(f"    A 独有 {len(only_a)} 个 label: {only_a}")
    for k in only_a:
        r = la[k]
        w(f"        {k}: level={r.get('level')} _w={r.get('_w')} _n={r.get('_n')} "
          f"_first={r.get('_first')} house={r.get('house')!r}")
    w(f"    B 独有（A 里没有）{len(only_b)} 个 label: {only_b}")
    for k in only_b:
        r = lb[k]
        w(f"        {k}: level={r.get('level')} _w={r.get('_w')} _n={r.get('_n')} "
          f"_first={r.get('_first')} house={r.get('house')!r}")
    w(f"    两方案交集 {len(set(la) & set(lb))} 个 label")

    # ---- 4) weight 的窗口性质 ----
    w("")
    w("=" * 100)
    w("[F-5] _weight 到底数的是什么（源码层面的回答）")
    w("=" * 100)
    w("    facts.py:11839  _weight = len(_hist_events) + len(_node_events) + len(_nodes)")
    w("    · _hist_events 来自 facts.py:11761-11806 的 events 列表：逐条 history 先过")
    w("      ① as_of 截断（11767-11768：d > as_of 跳过）② decade 下界（11769-11770）")
    w("      ③ 丧偶离婚丢弃（11777）④ 被动世仇囚禁行丢弃（11781）⑤ 渲染为空则丢弃（11785-11790）")
    w("      —— 所以它数的是**窗口内、且渲染成功**的条数，不是全部 history 条数。")
    w("    · _node_events 来自 _house_war_nodes（11813，as_of 截断）与 purge 行（11840-11846）")
    w("    · _nodes 是 _house_prison_nodes（11828，as_of 截断）**折叠前**的个人数")

    w(f"\n# 本节耗时 {time.time() - t0:.1f}s")
    with open(LOG_PATH, "a", encoding="utf-8") as fp:
        fp.write("\n".join(_buf) + "\n")
    print(f"\n[追加写盘] {LOG_PATH}")


if __name__ == "__main__":
    main()
