# -*- coding: utf-8 -*-
"""v117 check (item 丙-6): load_melt_section and its melt offset table.

The rewrite must return the same Python objects the byte-level walker returned, for
every suffix (plain/.gz/.xz), for a missing key, for an array-valued top-level key, for
a truncated melt and for corrupt JSON -- and its per-melt offset table must be reused on
the second call and invalidated when the melt's size or mtime changes.

The reference implementation is the pre-rewrite `cache_lib.py`, kept as a snapshot in
logs/v117/_v117_old_cache_lib.py (sha1 ba5592c0..., = git HEAD at the time of the rewrite; the
probe regenerates it from `git show HEAD:cache_lib.py` when it is missing and refuses to
run if what it finds is not the byte-level walker). Once the rewrite is committed, HEAD
no longer holds the old implementation, so the saved snapshot -- not HEAD -- is the
reference; the probe reports the mismatch instead of failing on it. The real melt is
read section-by-section only: no melt is ever loaded whole, re-melted or written, and
nothing is written outside logs/.

Usage:
    & tools\\py.ps1 tools\\tests\\v117_check_melt_section.py
    & tools\\py.ps1 tools\\tests\\v117_check_melt_section.py --big   # also time the 470 MB melt

Evidence report: logs/v117/v117_load_melt_section.txt (UTF-8).
"""
import argparse
import gc
import gzip
import hashlib
import importlib.util
import json
import lzma
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import cache_lib as cl       # noqa: E402

LOG = os.path.join(ROOT, "logs", "v117_load_melt_section.txt")
OLD_PATH = os.path.join(ROOT, "logs", "_v117_old_cache_lib.py")
TMP = os.path.join(ROOT, "logs", "_v117_melt")
# Smallest useful real melt: newest plain melts are 467-470 MB, this archive is 5.6 MB.
REAL = os.path.join(ROOT, "output", "洪氏2", "data", "melt_869_01_01.json.xz")
BIG = os.path.join(ROOT, "output", "洪氏2", "data", "melt_1283_01_01.json")
REAL_KEYS = ("landed_titles", "house_relations", "character_memory_manager", "characters")
SUFFIX_KEYS = ("meta_data", "characters", "wars", "traits", "landed_titles",
               "tail_obj", "only_array", "absent_key")

buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def canon(obj):
    """Short stable digest of an object, for byte-for-byte evidence in the report."""
    txt = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(txt.encode("utf-8")).hexdigest()[:16]


def timed(fn, *a):
    gc.collect()
    t0 = time.perf_counter()
    r = fn(*a)
    return r, time.perf_counter() - t0


def same(old_obj, new_obj):
    """Old and new must return the same Python object, not merely the same digest."""
    if type(old_obj) is not type(new_obj):
        return False
    return old_obj == new_obj


def _git_old_source():
    """Bytes of the last committed cache_lib.py that still holds the byte-level walker.

    After 丙-6 the old implementation lives only in history, so the probe walks back from
    HEAD until the blob carries the `buf += chunk` marker of the walker."""
    try:
        revs = subprocess.run(["git", "rev-list", "-n", "40", "HEAD"], cwd=ROOT,
                              capture_output=True, check=True).stdout.decode().split()
    except Exception:
        return None
    for rev in revs:
        got = subprocess.run(["git", "show", f"{rev}:cache_lib.py"], cwd=ROOT,
                             capture_output=True)
        if got.returncode == 0 and b"buf += chunk" in got.stdout:
            return got.stdout
    return None


def load_old_module():
    """Import the pre-rewrite cache_lib from logs/, regenerating it from git history."""
    if not os.path.isfile(OLD_PATH):
        w(f"[setup] 旧实现缺失，从 git 历史生成 {os.path.relpath(OLD_PATH, ROOT)}")
        src = _git_old_source()
        if src is None:
            w("[setup] 严重错误：git 历史里找不到带 buf += chunk 的 cache_lib.py")
            sys.exit(2)
        with open(OLD_PATH, "wb") as fp:
            fp.write(src)
    with open(OLD_PATH, "rb") as fp:
        src = fp.read()
    if b"buf += chunk" not in src or b"def load_melt_section" not in src:
        w("[setup] 旧实现快照不是重写前版本（缺少 buf += chunk 标记），改用 git 历史：")
        src = _git_old_source()
        if src is None:
            w("[setup] 严重错误：git 历史里找不到旧实现，无法对拍")
            sys.exit(2)
        with open(OLD_PATH, "wb") as fp:
            fp.write(src)
    spec = importlib.util.spec_from_file_location("v117_old_cache_lib", OLD_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["v117_old_cache_lib"] = mod
    spec.loader.exec_module(mod)
    return mod, hashlib.sha1(src).hexdigest()


# ---------------------------------------------------------------------------
# Synthetic melts: candidate skipping, nested shadowing, duplicate keys, strings with
# braces and escaped quotes, unusual whitespace, non-ASCII text.
# ---------------------------------------------------------------------------
SYNTH_OBJ = {
    "meta_data": {"meta_player_name": "测试家族", "note": "} { \" 括号与引号",
                  "dup": 1, "dup": 2, "empty": None},
    "characters": {
        "1": {"wars": [1, 1, 0, 0], "traits": {"level": 3}, "text": "内部 { 花括号"}},
    "wars": {"0": {"name": "顶层 wars"}},                 # object, later than the array
    "traits": {"7": {"level": 9}},                        # object, later than the nested one
    "landed_titles": {"landed_titles": {"0": {"key": "c_x"}, "1": {"key": "c_y"}}},
    "only_array": [1, 2, 3],                              # top level array -> None
    "tail_obj": {"pad": "x" * 4000, "deep": {"a": {"b": {"c": [1, 2, {"d": 3}]}}}},
}


def synth_bytes():
    """Synthetic melt bytes.

    json.dumps cannot emit a duplicate key (a Python dict holds one value per key), so
    one is spliced in afterwards; a CRLF + spaces run is spliced after the nested
    "wars" colon to cover whitespace between a name and its value."""
    raw = json.dumps(SYNTH_OBJ, ensure_ascii=False, indent=1).encode("utf-8")
    raw = raw.replace(b'"dup": 2', b'"dup": 1, "dup": 2', 1)
    return raw.replace(b'"wars":', b'"wars":\r\n      ', 1)


def write_suffixes(path_base, raw):
    """Write the same bytes as plain, .gz and .xz melts; return the three paths."""
    with open(path_base, "wb") as fp:
        fp.write(raw)
    with gzip.open(path_base + ".gz", "wb") as fp:
        fp.write(raw)
    with lzma.open(path_base + ".xz", "wb") as fp:
        fp.write(raw)
    return [path_base, path_base + ".gz", path_base + ".xz"]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_real_melt(old):
    """[A] real melt: old and new agree for four sections, and time both."""
    w("\n[A] 真实熔件逐键对拍（段级读取，不整载）")
    if not os.path.isfile(REAL):
        w(f"    跳过：{REAL} 不存在")
        return False, []
    w(f"    熔件 {os.path.relpath(REAL, ROOT)}  "
      f"{os.path.getsize(REAL)/1048576:.2f} MB (压缩后)")
    rows = []
    ok = True
    for key in REAL_KEYS:
        old_obj, t_old = timed(old.load_melt_section, REAL, key)
        cl.melt_section_index_clear()          # cold: index and decompressed text both gone
        new_cold, t_cold = timed(cl.load_melt_section, REAL, key)
        new_hot, t_hot = timed(cl.load_melt_section, REAL, key)
        eq = same(old_obj, new_cold) and same(new_cold, new_hot)
        d_old, d_new = canon(old_obj), canon(new_cold)
        n_sub = len(old_obj) if isinstance(old_obj, dict) else None
        rows.append((key, eq, d_old, d_new, n_sub, t_old, t_cold, t_hot))
        ok = ok and eq and d_old == d_new
        w(f"    {key:26s} 旧==新 {str(eq):5s}  子键 {str(n_sub):>7s}  "
          f"sha1 {d_old}/{d_new}  旧 {t_old:7.3f}s  新冷 {t_cold:7.3f}s  "
          f"新热 {t_hot:7.3f}s")
        del old_obj, new_cold, new_hot
        gc.collect()
    return ok, rows


def check_suffixes(old):
    """[B] plain/.gz/.xz agree with each other and with the reference objects."""
    w("\n[B] 后缀变体（明文/.gz/.xz）")
    raw = synth_bytes()
    paths = write_suffixes(os.path.join(TMP, "synth.json"), raw)
    cl.melt_section_index_clear()

    # Reference objects: the designed expectations, not another run of the code.
    expect = {
        "meta_data": {"meta_player_name": "测试家族", "note": "} { \" 括号与引号",
                      "dup": [1, 2], "empty": None},
        "characters": SYNTH_OBJ["characters"],
        "wars": {"0": {"name": "顶层 wars"}},              # array candidate skipped
        "traits": {"level": 3},                            # first object wins, nested one
        "landed_titles": SYNTH_OBJ["landed_titles"],
        "tail_obj": SYNTH_OBJ["tail_obj"],
        "only_array": None,
        "absent_key": None,
    }
    ok = True
    for key in SUFFIX_KEYS:
        got = []
        for p in paths:
            got.append((os.path.basename(p), old.load_melt_section(p, key),
                        cl.load_melt_section(p, key)))
        agree = all(same(a, b) for _n, a, b in got)
        all_same = all(same(got[0][1], a) and same(got[0][1], b) for _n, a, b in got)
        want = same(got[0][1], expect[key])
        line_ok = agree and all_same and want
        ok = ok and line_ok
        w(f"    {key:26s} 三后缀一致 {str(all_same):5s}  旧==新 {str(agree):5s}  "
          f"==预期 {str(want):5s}  sha1 {canon(got[0][1])}")
    w(f"    明文 {len(raw):,} 字节；内层 \"wars\": [1,1,0,0] 与内层 traits 对象均已覆盖")
    return ok


def check_edge_cases(old):
    """[C] missing key, array value, truncated melt, corrupt JSON, empty file."""
    w("\n[C] 缺失键 / 数组值 / 截断 / 损坏 / 空文件")
    raw = synth_bytes()
    plain = os.path.join(TMP, "edge.json")
    with open(plain, "wb") as fp:
        fp.write(raw)
    ok = True

    # missing key and array-valued top-level key
    for key in ("absent_key", "only_array"):
        a, b = old.load_melt_section(plain, key), cl.load_melt_section(plain, key)
        eq = a is None and b is None
        ok = ok and eq
        w(f"    {key:26s} 旧 {a!r} 新 {b!r}  {'PASS' if eq else 'FAIL'}")

    # truncated inside the last section: that key is gone, earlier keys survive
    cut = raw.rindex(b'"tail_obj"') + 400
    trunc = os.path.join(TMP, "trunc.json")
    with open(trunc, "wb") as fp:
        fp.write(raw[:cut])
    rows = []
    for key in ("tail_obj", "landed_titles", "wars"):
        a, b = old.load_melt_section(trunc, key), cl.load_melt_section(trunc, key)
        rows.append((key, a, b, same(a, b)))
        ok = ok and same(a, b)
    w(f"    截断于 tail_obj 内（第 {cut} 字节）: " +
      "; ".join(f"{k} 旧={'None' if a is None else 'dict'} 新="
                f"{'None' if b is None else 'dict'} {str(e):5s}" for k, a, b, e in rows))

    # corrupt JSON inside the object: both raise JSONDecodeError
    bad = os.path.join(TMP, "bad.json")
    with open(bad, "wb") as fp:
        fp.write(b'{"good": {"a": 1}}\n{"bad": {"a": tru}}')
    ea = eb = None
    try:
        old.load_melt_section(bad, "bad")
    except Exception as exc:                      # noqa: BLE001 - probing the failure mode
        ea = exc
    try:
        cl.load_melt_section(bad, "bad")
    except Exception as exc:                      # noqa: BLE001 - probing the failure mode
        eb = exc
    eq = isinstance(ea, json.JSONDecodeError) and isinstance(eb, json.JSONDecodeError)
    ok = ok and eq
    w(f"    损坏 JSON                 旧 {type(ea).__name__} 新 {type(eb).__name__}  "
      f"{'PASS' if eq else 'FAIL'}")
    a, b = old.load_melt_section(bad, "good"), cl.load_melt_section(bad, "good")
    eq2 = same(a, b)
    ok = ok and eq2
    w(f"    损坏文件内的正常段       旧==新 {str(eq2):5s}  {a!r}")

    # empty file
    empty = os.path.join(TMP, "empty.json")
    open(empty, "wb").close()
    a, b = old.load_melt_section(empty, "meta_data"), cl.load_melt_section(empty, "meta_data")
    eq3 = a is None and b is None
    ok = ok and eq3
    w(f"    空文件                    旧 {a!r} 新 {b!r}  {'PASS' if eq3 else 'FAIL'}")
    return ok


def check_index_reuse(old):
    """[D] the offset table is reused on the second call and invalidated on size+mtime."""
    w("\n[D] 偏移表复用与失效")
    raw = synth_bytes()
    p = os.path.join(TMP, "reuse.json")
    with open(p, "wb") as fp:
        fp.write(raw)
    ok = True

    # spy on the locate helper so "no re-scan" is proven, not inferred from a counter
    calls = []
    real_locate = cl._locate_melt_section

    def spy(data, pat):
        calls.append(pat)
        return real_locate(data, pat)

    cl._locate_melt_section = spy
    try:
        cl.melt_section_index_clear()
        s0 = cl.melt_section_index_stats()
        first = cl.load_melt_section(p, "landed_titles")
        s1 = cl.melt_section_index_stats()
        n_first = len(calls)
        second = cl.load_melt_section(p, "landed_titles")
        n_second = len(calls)
        s2 = cl.melt_section_index_stats()
        reuse = first == second and n_first == 1 and n_second == 1
        ok = ok and reuse
        w(f"    冷读 landed_titles: 定位 {n_first} 次, 表项 {s0['files']}->{s1['files']}, "
          f"lookups {s0['lookups']}->{s1['lookups']}")
        w(f"    热读 landed_titles: 定位 {n_second - n_first} 次, "
          f"lookups {s1['lookups']}->{s2['lookups']}  {'PASS' if reuse else 'FAIL'}")

        # a miss is cached too: the second probe of a missing key does not rescan
        cl.load_melt_section(p, "absent_key")
        n_miss1 = len(calls)
        cl.load_melt_section(p, "absent_key")
        n_miss2 = len(calls)
        miss_cached = n_miss1 == 2 and n_miss2 == 2
        ok = ok and miss_cached
        w(f"    缺失键重复探测: 定位 {n_miss1}->{n_miss2} 次  "
          f"{'PASS' if miss_cached else 'FAIL'}")

        # a different key still needs its own lookup (the table starts cold per file)
        cl.load_melt_section(p, "wars")
        w(f"    换键 wars: 定位 {len(calls) - n_miss2} 次（新键各查一次，符合预期）")

        # same size, new mtime, different content -> must invalidate and return the new text
        raw3 = raw.replace(b"c_x", b"c_z")        # same length, different content
        assert len(raw3) == len(raw)
        with open(p, "wb") as fp:
            fp.write(raw3)
        st = os.stat(p)
        os.utime(p, (st.st_atime, st.st_mtime + 5))
        before = len(calls)
        got = cl.load_melt_section(p, "landed_titles")
        rescanned = len(calls) - before
        changed = got["landed_titles"]["0"]["key"] == "c_z"
        ok = ok and rescanned == 1 and changed
        w(f"    同尺寸+新 mtime 改写: 重新定位 {rescanned} 次, 取到新内容 {str(changed):5s}  "
          f"{'PASS' if (rescanned == 1 and changed) else 'FAIL'}")

        # different size, same mtime second resolution -> invalidates on the size stamp
        raw4 = raw3 + b"\n"
        with open(p, "wb") as fp:
            fp.write(raw4)
        before = len(calls)
        got = cl.load_melt_section(p, "landed_titles")
        grew = len(calls) - before
        ok = ok and grew == 1
        w(f"    尺寸变化改写: 重新定位 {grew} 次  {'PASS' if grew == 1 else 'FAIL'}")

        # unchanged file -> still no lookup at all
        before = len(calls)
        cl.load_melt_section(p, "landed_titles")
        stable = len(calls) == before
        ok = ok and stable
        w(f"    未改动文件再读: 定位 {len(calls) - before} 次  "
          f"{'PASS' if stable else 'FAIL'}")

        s3 = cl.melt_section_index_stats()
        w(f"    统计: files={s3['files']} sections={s3['sections']} "
          f"lookups={s3['lookups']} text_mb={s3['text_mb']}")
    finally:
        cl._locate_melt_section = real_locate
    return ok


def check_big(old):
    """[E] optional: the same four keys on the 470 MB production melt."""
    w("\n[E] 大熔件（生产主链路，可选）")
    if not os.path.isfile(BIG):
        w(f"    跳过：{os.path.relpath(BIG, ROOT)} 不存在")
        return True
    w(f"    {os.path.relpath(BIG, ROOT)}  {os.path.getsize(BIG)/1073741824:.2f} GB")
    ok = True
    cl.melt_section_index_clear()
    for key in REAL_KEYS:
        old_obj, t_old = timed(old.load_melt_section, BIG, key)
        cl.melt_section_index_clear()
        new_cold, t_cold = timed(cl.load_melt_section, BIG, key)
        new_hot, t_hot = timed(cl.load_melt_section, BIG, key)
        eq = same(old_obj, new_cold) and same(new_cold, new_hot)
        ok = ok and eq
        w(f"    {key:26s} 旧==新 {str(eq):5s}  旧 {t_old:8.3f}s  新冷 {t_cold:8.3f}s  "
          f"新热 {t_hot:8.3f}s  sha1 {canon(old_obj)}")
        del old_obj, new_cold, new_hot
        gc.collect()
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--big", action="store_true",
                    help="also compare/time the four keys on the 470 MB production melt")
    args = ap.parse_args()

    shutil.rmtree(TMP, ignore_errors=True)
    os.makedirs(TMP)

    w("=" * 78)
    w("v117 丙-6  load_melt_section 偏移表对拍取证")
    w(f"时间 {time.strftime('%Y-%m-%d %H:%M:%S')}   新实现 cache_lib.load_melt_section")
    w(f"命令行参数 --big={args.big}"
      f"（& tools\\py.ps1 tools\\tests\\v117_check_melt_section.py"
      f"{' --big' if args.big else ''}）")
    w("=" * 78)
    old, old_sha = load_old_module()
    w(f"[setup] 旧实现 logs/v117/_v117_old_cache_lib.py  sha1 {old_sha}")
    try:
        head = subprocess.run(["git", "show", "HEAD:cache_lib.py"], cwd=ROOT,
                              capture_output=True, check=True).stdout
        head_sha = hashlib.sha1(head).hexdigest()
        if head_sha == old_sha:
            w("[setup] 与 git HEAD:cache_lib.py 一致 True（HEAD 仍是重写前版本）")
        else:
            w(f"[setup] 与 git HEAD:cache_lib.py 不一致（HEAD 现在是 {head_sha[:12]}）："
              f"logs/ 里的旧实现是重写前快照，丙-6 落地后 HEAD 已改，属预期；"
              f"对拍基准仍是该快照")
    except Exception as exc:                       # noqa: BLE001 - provenance is best effort
        w(f"[setup] 未能核对 git HEAD: {type(exc).__name__}: {exc}")

    results = {}
    try:
        results["A 真实熔件逐键对拍"] = check_real_melt(old)[0]
        results["B 后缀变体一致"] = check_suffixes(old)
        results["C 缺失/截断/损坏/空"] = check_edge_cases(old)
        results["D 偏移表复用与失效"] = check_index_reuse(old)
        if args.big:
            results["E 大熔件对拍"] = check_big(old)
        else:
            w("\n[E] 大熔件对拍：未运行（加 --big 才在 470 MB 明文熔件上对拍计时）")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

    w("\n" + "-" * 78)
    for name, okv in results.items():
        w(f"  {'PASS' if okv else 'FAIL'} {name}")
    all_ok = all(results.values())
    w(f"\n[{'PASS' if all_ok else 'FAIL'}] v117 丙-6 load_melt_section 偏移表检查")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    print(f"[report] {LOG}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
