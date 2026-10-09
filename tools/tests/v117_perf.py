# -*- coding: utf-8 -*-
"""v117 性能取证：CK3 家传「存档处理」链路的实测秒数与峰值内存。

只做取证，不修改任何生产代码、不压缩/覆盖/删除任何现有文件。
唯一的写动作：logs/ 下的临时文件（测完自删）。

用法（在项目根目录 D:\\Roman 下执行）：

    & tools\\py.ps1 tools\\tests\\v117_perf.py --items 1,5,6,7
    & tools\\py.ps1 tools\\tests\\v117_perf.py --items 2,3,4,7,8
    & tools\\py.ps1 tools\\tests\\v117_perf.py --all

分项（大内存项请单独开一次进程跑，见 --items）：

    1  缓存加载：json.load(player_17066495.json) / cl.load_cache()
    2  熔件整载：cl.load_melt(melt_1283_01_01.json) + cl.all_characters
    3  段级读取 vs 整载：load_melt_section / load_melt_landed_titles
    4  cl.extract_snapshot(缓存, 熔件, "1283.1.1") 真实一次 + 各 _latch_*/_diff_* 分项
    5  cl.save_cache(缓存, logs 临时文件)
    6  pipeline.all_caches(cfg)（json.load 全部 player_*.json）
    7  扫描类：_iter_melts / _compact_keep_paths / load_melt_index / xz 压缩
    8  cProfile：extract_snapshot 与 facts.build_facts 的 cumulative top-25

输出同时写控制台与 logs/v117_perf.txt（UTF-8，追加）。
"""
import argparse
import cProfile
import ctypes
import gc
import io
import json
import lzma
import os
import pstats
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

CAMPAIGN = "洪氏2"
CACHE_PID = 17066495          # 后期主玩家（洪光通）
MELT_DATE = "1283_01_01"      # 与缓存last_date匹配的后期档
AS_OF = "1283.1.1"

OUT_PATH = os.path.join(ROOT, "logs", "v117_perf.txt")
TMP_PREFIX = "_v117_tmp_"
_FH = None


# ---------------------------------------------------------------------------
# 输出与度量工具
# ---------------------------------------------------------------------------

def log(msg=""):
    line = str(msg)
    print(line, flush=True)
    if _FH is not None:
        _FH.write(line + "\n")
        _FH.flush()


def _open_out(items):
    global _FH
    _FH = open(OUT_PATH, "a", encoding="utf-8")
    _FH.write("\n" + "=" * 78 + "\n")
    _FH.write(f"v117_perf run  {time.strftime('%Y-%m-%d %H:%M:%S')}  items={items}\n")
    _FH.write("=" * 78 + "\n")
    _FH.flush()


# Windows 进程内存：WorkingSetSize / PeakWorkingSetSize，无需 psutil
class _PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


_PSAPI = None
if os.name == "nt":
    try:
        _PSAPI = ctypes.windll.psapi
        _PSAPI.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p,
                                                ctypes.POINTER(_PMC), ctypes.c_ulong]
        ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    except Exception:
        _PSAPI = None


def rss_mb():
    """(当前工作集 MB, 峰值工作集 MB)；取不到返回 (None, None)。"""
    if _PSAPI is None:
        return None, None
    try:
        c = _PMC()
        c.cb = ctypes.sizeof(_PMC)
        h = ctypes.windll.kernel32.GetCurrentProcess()
        if not _PSAPI.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
            return None, None
        return c.WorkingSetSize / 1048576.0, c.PeakWorkingSetSize / 1048576.0
    except Exception:
        return None, None


def _fmt_mb(v):
    return "  n/a " if v is None else f"{v:7.0f}"


def timed(label, fn, *a, **kw):
    """跑一次 fn 并打印 秒数 + 前后 RSS + 峰值 RSS；返回 (结果, 秒数)。"""
    gc.collect()
    w0, _p0 = rss_mb()
    t0 = time.perf_counter()
    res = fn(*a, **kw)
    dt = time.perf_counter() - t0
    w1, p1 = rss_mb()
    log(f"{label:<44} {dt:9.3f} s   RSS {_fmt_mb(w0)} -> {_fmt_mb(w1)} MB   "
        f"峰值 {_fmt_mb(p1)} MB")
    return res, dt


def size_of(obj):
    """粗略对象体量：dict/list 递归 size（只用于报告数量级，deep 限制 3 层）。"""
    seen = 0
    stack = [(obj, 0)]
    total = 0
    while stack and seen < 4_000_000:
        o, d = stack.pop()
        seen += 1
        try:
            total += sys.getsizeof(o)
        except Exception:
            continue
        if d >= 3:
            continue
        if isinstance(o, dict):
            for k, v in o.items():
                stack.append((k, d + 1))
                stack.append((v, d + 1))
        elif isinstance(o, (list, tuple, set)):
            for v in o:
                stack.append((v, d + 1))
    return total


def clear_memo():
    try:
        cl._CACHE_LOAD_MEMO.clear()
    except Exception:
        pass
    try:
        cl.melt_memo_clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 分项
# ---------------------------------------------------------------------------

def cache_path():
    return os.path.join(ROOT, "output", CAMPAIGN, "data", f"player_{CACHE_PID}.json")


def melt_path():
    d = os.path.join(ROOT, "output", CAMPAIGN, "data")
    plain = os.path.join(d, f"melt_{MELT_DATE}.json")
    if os.path.isfile(plain):
        return plain
    for suf in (".xz", ".gz"):
        if os.path.isfile(plain + suf):
            return plain + suf
    return ""


def item1():
    log("\n[1] 缓存加载 —— json.load 与 cl.load_cache")
    p = cache_path()
    if not os.path.isfile(p):
        log(f"    跳过：{p} 不存在")
        return None
    sz = os.path.getsize(p)
    log(f"    文件 {os.path.relpath(p, ROOT)}  {sz/1048576:.1f} MB "
        f"({sz:,} 字节)")

    def _raw():
        with open(p, encoding="utf-8") as fp:
            return json.load(fp)

    d, t_raw = timed("json.load(cache) [RawCLoad]", _raw)
    n_chars = len((d.get("characters") or {}))
    log(f"    数据规模: characters={n_chars:,}  memories_total="
        f"{sum(len(r.get('memories') or []) for r in d.get('characters', {}).values()):,}  "
        f"sources={len(d.get('sources') or [])}")
    del d
    gc.collect()

    c1, t1 = timed("cl.load_cache(path) [memo miss = 整载]",
                   lambda: cl.load_cache(p))
    c2, t2 = timed("cl.load_cache(path) [memo hit]", lambda: cl.load_cache(p))
    c3, t3 = timed("cl.load_cache(path, fresh=True) [强制整载]",
                   lambda: cl.load_cache(p, fresh=True))
    log(f"    备注: fresh=True 是 _process_save 的路径，每次合并都真解析一遍；"
        f"memo hit/miss = {t2/max(t1,1e-9):.4f}x")
    del c1, c2, c3
    gc.collect()
    return t_raw


def item2():
    log("\n[2] 熔件整载 —— cl.load_melt(后期 470MB 档)")
    p = melt_path()
    if not p:
        log("    跳过：既无明文 melt_1283_01_01.json 也无压缩版")
        return None
    if p.lower().endswith((".xz", ".gz")):
        log(f"    警告：只有压缩态 {os.path.basename(p)}；不自行解压大文件")
    sz = os.path.getsize(p)
    log(f"    文件 {os.path.relpath(p, ROOT)}  {sz/1048576:.1f} MB")

    def _read_bytes():
        with open(p, "rb") as fp:
            return fp.read()

    raw, t_read = timed("磁盘整读 (raw bytes, 无解析)", _read_bytes)
    log(f"    读入字节 {len(raw):,}")
    del raw
    gc.collect()

    t0 = time.perf_counter()
    melt = cl.load_melt(p)
    t_load = time.perf_counter() - t0
    _w, peak = rss_mb()
    log(f"{'cl.load_melt(整载+解析+折叠)':<44} {t_load:9.3f} s   "
        f"RSS {'':>7} -> {'':>7} MB   峰值 {_fmt_mb(peak)} MB")
    log(f"    顶层键 {len(melt)} 个；解析耗时是纯磁盘读的 "
        f"{t_load/max(t_read,1e-9):.1f}x")
    for k in ("living", "dead_unprunable", "landed_titles", "wars",
              "character_memory_manager", "court_positions"):
        v = melt.get(k)
        if isinstance(v, dict):
            log(f"      top-level '{k}': dict, {len(v):,} 子键")
    chars, t_chars = timed("cl.all_characters(melt) [全角色索引]",
                           cl.all_characters, melt)
    log(f"    角色总数 {len(chars):,}")
    del chars
    gc.collect()
    return melt


SECTION_KEYS = ("landed_titles", "house_relations", "living", "wars",
                "character_memory_manager", "court_positions", "meta_data")


def item3(melt=None):
    log("\n[3] 段级读取 vs 整载")
    p = melt_path()
    if not p:
        log("    跳过：无熔件")
        return
    for key in SECTION_KEYS:
        r, dt = timed(f'cl.load_melt_section(path, "{key}")',
                      cl.load_melt_section, p, key)
        if isinstance(r, dict):
            log(f"      -> dict, {len(r):,} 子键, 体量约 {size_of(r)/1048576:.1f} MB")
        elif r is None:
            log("      -> None (未找到对象段)")
        else:
            log(f"      -> {type(r).__name__}")
        del r
        gc.collect()
    r, _ = timed("cl.load_melt_landed_titles(path)",
                 cl.load_melt_landed_titles, p)
    log(f"      -> {len(r):,} 个头衔")
    del r
    gc.collect()
    if melt is not None:
        t0 = time.perf_counter()
        for key in SECTION_KEYS:
            _ = melt.get(key)
        log(f"{'已载熔件 melt.get(key) x7（对照）':<44} "
            f"{time.perf_counter()-t0:9.6f} s")


HOT_FUNCS = ("_latch_title_dyn_names", "_latch_war_history", "_record_vassal_and_cycle",
             "_diff_secrets", "_diff_factions", "_diff_epidemics", "_diff_disease_edges",
             "_diff_hooks", "_latch_matrilineal", "_diff_enslavements", "_diff_opinions",
             "_latch_relation_reasons", "_latch_spouses", "_latch_prison_manners",
             "_diff_carnal_opinions", "_diff_carnal_modifiers", "_latch_prison_succession",
             "all_characters", "find_player")


class Timer:
    """模块级函数的计时代理：{名字: [累计秒, 调用次数]}。"""

    def __init__(self, mod, names):
        self.mod = mod
        self.stats = {}
        self._orig = {}
        for n in names:
            fn = getattr(mod, n, None)
            if fn is None:
                continue
            self._orig[n] = fn
            self.stats[n] = [0.0, 0]
            setattr(mod, n, self._make(n, fn))

    def _make(self, name, fn):
        stats = self.stats

        def inner(*a, **kw):
            t0 = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                dt = time.perf_counter() - t0
                s = stats[name]
                s[0] += dt
                s[1] += 1
        inner.__name__ = name
        inner.__wrapped__ = fn
        return inner

    def restore(self):
        for n, fn in self._orig.items():
            setattr(self.mod, n, fn)

    def report(self, total):
        log("    --- extract_snapshot 内部各步（按累计秒降序）---")
        rows = sorted(self.stats.items(), key=lambda kv: -kv[1][0])
        acc = 0.0
        for name, (dt, n) in rows:
            acc += dt
            log(f"      {name:<28} {dt:8.3f} s  x{n:<4d} "
                f"({dt/max(total,1e-9)*100:5.1f}% of snapshot)")
        log(f"      {'[被计时子项合计]':<28} {acc:8.3f} s "
            f"({acc/max(total,1e-9)*100:5.1f}%)")
        log(f"      {'[extract_snapshot 总计]':<28} {total:8.3f} s")


def item4(cache, melt):
    log("\n[4] cl.extract_snapshot(真实一次, 1283.1.1)")
    if cache is None or melt is None:
        log("    跳过：需要 item1 的缓存与 item2 的熔件")
        return None
    new_deaths = []
    timer = Timer(cl, HOT_FUNCS)
    try:
        t0 = time.perf_counter()
        ok = cl.extract_snapshot(cache, melt, AS_OF, _new_deaths=new_deaths)
        dt = time.perf_counter() - t0
    finally:
        timer.restore()
    _w, peak = rss_mb()
    log(f"{'cl.extract_snapshot(cache, melt, 1283.1.1)':<44} {dt:9.3f} s   "
        f"峰值 {_fmt_mb(peak)} MB   -> {ok}")
    log(f"    _new_deaths {len(new_deaths)} 人")
    timer.report(dt)
    return dt


def item5(cache):
    log("\n[5] cl.save_cache 写盘（写 logs/ 临时文件，测完删除）")
    if cache is None:
        log("    跳过：无缓存对象")
        return
    tmp = os.path.join(ROOT, "logs", TMP_PREFIX + "cache.json")
    try:
        _r, dt = timed("cl.save_cache(cache, logs 临时路径)",
                       cl.save_cache, cache, tmp)
        if os.path.isfile(tmp):
            sz = os.path.getsize(tmp)
            log(f"    写出体积 {sz/1048576:.1f} MB ({sz:,} 字节)；"
                f"吞吐 {sz/1048576/max(dt,1e-9):.1f} MB/s")
    finally:
        for cand in (tmp,):
            try:
                if os.path.isfile(cand):
                    os.remove(cand)
                    log(f"    已删除临时文件 {os.path.relpath(cand, ROOT)}")
            except OSError as e:
                log(f"    临时文件删除失败: {e}")


def item6():
    log("\n[6] pipeline.all_caches(cfg) —— 遍历并 json.load 全部 player_*.json")
    import llm
    import pipeline
    cfg = llm.load_config()

    files = []
    for root in (cfg.get("output_dir", ""), cfg.get("cache_dir", "")):
        if not root or not os.path.isdir(root):
            continue
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                if fn.startswith("player_") and fn.endswith(".json"):
                    files.append(os.path.join(dp, fn))
    tot = sum(os.path.getsize(f) for f in files)
    log(f"    player_*.json: {len(files)} 个, 合计 {tot/1048576:.1f} MB")

    clear_memo()
    per = {}
    orig = cl.load_cache

    def spy(path, fresh=False):
        t0 = time.perf_counter()
        try:
            return orig(path, fresh=fresh)
        finally:
            try:
                if os.path.getsize(path):
                    per[path] = per.get(path, 0.0) + (time.perf_counter() - t0)
            except OSError:
                pass

    cl.load_cache = spy
    try:
        out, dt = timed("pipeline.all_caches(cfg) [清空memo后]",
                        pipeline.all_caches, cfg)
    finally:
        cl.load_cache = orig
    log(f"    返回 {len(out)} 个战役-玩家条目")
    log("    --- 单个缓存文件的解析耗时（all_caches 遍历到的全部）---")
    for p, s in sorted(per.items(), key=lambda kv: -kv[1]):
        sz = os.path.getsize(p) / 1048576
        log(f"      {os.path.relpath(p, ROOT):<58} {s:7.3f} s  {sz:6.1f} MB")
    log(f"    单档解析合计 {sum(per.values()):.1f} s / all_caches 总耗时 {dt:.1f} s")
    del out
    gc.collect()
    return dt


def item7(cache=None, melt=None):
    log("\n[7] 扫描类与压缩")
    import llm
    import pipeline
    cfg = llm.load_config()

    melts, t_iter = timed("pipeline._iter_melts(cfg)", pipeline._iter_melts, cfg)
    log(f"    熔件 {len(melts)} 份")
    keep, t_keep = timed("pipeline._compact_keep_paths(cfg)",
                         pipeline._compact_keep_paths, cfg)
    log(f"    保持明文 {len(keep)} 份; 扫描开销 = 遍历 {len(melts)} 份目录项")

    # 索引边车（_recover_dead_memories 的快速路径）
    p = melt_path()
    if p:
        idx, t_idx = timed("cl.load_melt_index(melt_1283)", cl.load_melt_index, p)
        if isinstance(idx, dict):
            log(f"    索引 chars={len(idx.get('chars') or {}):,} "
                f"db={len(idx.get('db') or {}):,}")

    # xz 压缩：只压前 50MB，再线性外推
    if p and p.lower().endswith(".json") and os.path.getsize(p) > (50 << 20):
        chunk = 50 << 20
        tmp = os.path.join(ROOT, "logs", TMP_PREFIX + "head50.json.xz")
        try:
            def _compress_head():
                with open(p, "rb") as fi, lzma.open(tmp, "wb", preset=6) as fo:
                    left = chunk
                    while left > 0:
                        buf = fi.read(min(8 << 20, left))
                        if not buf:
                            break
                        left -= len(buf)
                        fo.write(buf)
            _r, t_c = timed(f"xz preset6 压缩前 50MB (实际 {chunk/1048576:.0f}MB)",
                            _compress_head)
            out_sz = os.path.getsize(tmp)
            full = os.path.getsize(p)
            log(f"    50MB -> {out_sz/1048576:.1f} MB ({out_sz/chunk*100:.0f}%)；"
                f"按同速率外推整份 {full/1048576:.0f} MB ≈ "
                f"{t_c*full/chunk:.0f} s ({t_c*full/chunk/60:.1f} min)")
            log("    生产日志对照: logs/journal.log 相邻两条 [N/M] 熔件行间隔 "
                "≈ 172-188 s / 442-447 MB")
        finally:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    # 记忆归档边车构建（需要整载熔件）
    if melt is not None:
        idx, t_build = timed("cl.build_melt_index(melt) [需整载]",
                             cl.build_melt_index, melt)
        tmp = os.path.join(ROOT, "logs", TMP_PREFIX + "idx.json.gz")
        try:
            import gzip

            def _dump_idx():
                with gzip.open(tmp, "wt", encoding="utf-8") as fp:
                    json.dump(idx, fp, ensure_ascii=False, separators=(",", ":"))
            _r, t_dump = timed("索引 json.dump+gzip 落盘", _dump_idx)
            if os.path.isfile(tmp):
                log(f"    索引写出 {os.path.getsize(tmp)/1048576:.1f} MB；"
                    f"建索引+落盘合计 {t_build+t_dump:.1f} s")
        finally:
            try:
                if os.path.isfile(tmp):
                    os.remove(tmp)
            except OSError:
                pass


def _profile(label, fn, top=25):
    pr = cProfile.Profile()
    t0 = time.perf_counter()
    pr.enable()
    fn()
    pr.disable()
    dt = time.perf_counter() - t0
    _w, peak = rss_mb()
    buf = io.StringIO()
    st = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
    st.print_stats(top)
    log(f"\n    ===== cProfile: {label} —— 总 {dt:.3f} s, 峰值 {_fmt_mb(peak)} MB =====")
    lines = buf.getvalue().splitlines()
    # 只保留前 25 名（含表头）
    keep = []
    body = [ln for ln in lines if ln.strip()]
    # pstats 输出: 头部若干行 + 表头 + 数据行 + 尾行
    for ln in body:
        if ln.strip().startswith("ncalls") or keep:
            keep.append(ln)
    log("\n".join(keep[:top + 2]))
    del pr
    gc.collect()


def item8(cache, melt):
    log("\n[8] cProfile top-25")
    import llm
    import facts as F
    if cache is None or melt is None:
        log("    跳过：需要缓存与熔件")
        return
    # 8a: extract_snapshot —— 用一份缓存浅拷贝，避免污染后续
    _profile("cl.extract_snapshot(cache, melt, 1283.1.1)",
             lambda: cl.extract_snapshot(cache, melt, AS_OF, _new_deaths=[]))

    # 8b: facts 构建（generate_bio 的第一步）
    names_path = os.path.join(ROOT, "data", "names.json")
    _profile("facts.build_facts(cache, melt, names.json)",
             lambda: F.build_facts(cache, melt, names_path, as_of=None,
                                   decade=None, nickname_override=None,
                                   campaign={CACHE_PID: cache}))


# ---------------------------------------------------------------------------

def item9(cache, melt):
    """合并之后的收尾环节：_cross_check_* 的全表扫描 与 facts.house_feuds 的 O(房数×角色数)。

    只做只读度量：_cross_check_deaths 会 save_cache，故这里只复现它的扫描本体
    （dead_unprunable × 缓存条目），不打它的整函数；house_feuds 本身是纯读。
    """
    log("\n[9] 合并后收尾环节：跨档死亡核对扫描 与 house_feuds")
    import llm
    import facts as F
    import pipeline
    cfg = llm.load_config()
    if melt is None:
        log("    跳过：需要熔件")
        return
    dead = melt.get("dead_unprunable") or {}
    log(f"    dead_unprunable {len(dead):,} 条（_cross_check_deaths 的外层循环规模）")

    # 9a: 复现 _cross_check_deaths 的内层扫描（pipeline.py:1207-1213）
    n_keys = 28          # 实测 all_caches 返回 28 个条目（全 output 树）
    keys = [((i * 1000 + 7, "pt"), (None, None)) for i in range(n_keys)]
    t0 = time.perf_counter()
    hit = 0
    for cid, c in dead.items():
        if not isinstance(c, dict):
            continue
        cid = int(cid)
        hits = [v for k, v in keys if k[0] == cid]
        hit += len(hits)
    dt = time.perf_counter() - t0
    log(f"{'  _cross_check_deaths 内层扫描复现':<44} {dt:9.3f} s   "
        f"({len(dead):,} 死角色 × {n_keys} 缓存条目, 命中 {hit})")
    log("    说明: 该循环每次合并跑 2 遍(_cross_check_deaths + _cross_check_reign_ends "
        "各自的 all_caches)，且其前的 all_caches 本身见 item6")

    # 9b: house_feuds —— 需要 Facts 实例
    if cache is None:
        log("    跳过 house_feuds：无缓存对象")
        return
    names_path = os.path.join(ROOT, "data", "names.json")
    f, t_ctor = timed("facts.Facts(cache, melt, names.json) 构造",
                      F.Facts, cache, melt, names_path)
    db = ((melt.get("house_relations") or {}).get("database") or {})
    log(f"    house_relations.database {len(db):,} 条")
    _r, t_feud = timed("facts.Facts.house_feuds()", f.house_feuds)
    log(f"    结论：house_feuds 单次 {t_feud:.1f} s，占 build_facts 的主要部分")

    # 9c: 单房扫描代价 —— 同一房对反复全表扫描
    prec = (cache.get("characters") or {}).get(str(cache.get("player_id"))) or {}
    my_houses = set()
    h0 = prec.get("dynasty_house")
    if isinstance(h0, int):
        my_houses.add(h0)
    did = cache.get("dynasty_id")
    dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
    if did is not None:
        for hid, e in dh.items():
            if isinstance(e, dict) and e.get("dynasty") == did:
                my_houses.add(int(hid))
    others = []
    for _k, r in db.items():
        if not isinstance(r, dict):
            continue
        hs = r.get("houses") or []
        if any(h in my_houses for h in hs):
            o = [h for h in hs if h not in my_houses]
            if o:
                others.append(o[0])
    log(f"    主角家族 {sorted(my_houses)}；涉及敌对房 {len(others)} 个 "
        f"(去重 {len(set(others))})")
    if others:
        o0 = others[0]
        _r, t_p = timed("  house_purge_pairs(单房)",
                        f.house_purge_pairs, o0, my_houses)
        _r, t_pr = timed("  _house_prison_nodes(单房)",
                         f._house_prison_nodes, o0, my_houses, None)
        _r, t_w = timed("  _house_war_nodes(单房)",
                        f._house_war_nodes, o0, my_houses, None)
        log(f"    单房三件套 {t_p+t_pr+t_w:.3f} s → ×{len(others)} 房 ≈ "
            f"{(t_p+t_pr+t_w)*len(others):.0f} s（与 cProfile 的 house_feuds "
            f"cumtime 同量级）")


ALL = "1,2,3,4,5,6,7,8,9"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", default="1,3,5")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    items = ALL if args.all else args.items
    want = {s.strip() for s in str(items).split(",") if s.strip()}

    _open_out(items)
    t_start = time.perf_counter()
    log(f"项目根 {ROOT}   Python {sys.version.split()[0]}   "
        f"items={sorted(want, key=int)}")
    w, p = rss_mb()
    log(f"起始 RSS {_fmt_mb(w)} MB, 峰值 {_fmt_mb(p)} MB")

    import cache_lib as cl          # noqa: E402
    globals()["cl"] = cl

    cache = None
    melt = None
    if "1" in want:
        item1()
    if "2" in want or "4" in want or "8" in want or "9" in want or ("7" in want and "2" in want):
        if "2" in want:
            melt = item2()
        else:
            pth = melt_path()
            if pth:
                melt, _ = timed("cl.load_melt(供 item4/8/9 使用)", cl.load_melt, pth)
            else:
                log("熔件缺失，item4/8/9 跳过")
    if "5" in want or "4" in want or "8" in want or "9" in want:
        pth = cache_path()
        if os.path.isfile(pth):
            cache, _ = timed("cl.load_cache(供 item4/5/8/9 使用)",
                             lambda: cl.load_cache(pth))
        elif "4" in want or "5" in want or "8" in want or "9" in want:
            log(f"缓存缺失: {pth}")
    if "5" in want:
        item5(cache)
    if "3" in want:
        item3(melt)
    if "4" in want:
        item4(cache, melt)
    if "6" in want:
        item6()
    if "7" in want:
        item7(cache, melt)
    if "8" in want:
        item8(cache, melt)
    if "9" in want:
        item9(cache, melt)

    log(f"\n总耗时 {time.perf_counter()-t_start:.1f} s")
    _w, pk = rss_mb()
    log(f"结束峰值工作集 {_fmt_mb(pk)} MB")
    if _FH is not None:
        _FH.close()


if __name__ == "__main__":
    main()
