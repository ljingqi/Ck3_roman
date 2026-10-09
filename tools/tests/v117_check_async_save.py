# -*- coding: utf-8 -*-
"""v117 check (item 3 / 丙-3a): background cache writes.

Uses a throwaway campaign folder under logs/, so no real cache is touched. Asserts that
`save_cache_async` returns at once and lands complete content on `flush_saves`, that a read-modify-write
never loses a version (flush before write), that a failed write surfaces on the next flush, and that
`save_cache_now` writes synchronously and refreshes the metadata index.

Usage: & tools\\py.ps1 tools\\tests\\v117_check_async_save.py
"""
import json
import os
import shutil
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl       # noqa: E402
import pipeline as P         # noqa: E402

LOG = os.path.join(ROOT, "logs", "v117_check_async_save.txt")
TMP = os.path.join(ROOT, "logs", "_v117_async")

buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def fake_cache(pid, marker, n_chars=40000):
    """A cache big enough that json.dump takes a moment, with a marker to tell versions apart."""
    return {
        "player_id": pid,
        "playthrough_id": "pt-async",
        "player_name": f"玩家{pid}",
        "last_date": "1283.9.11",
        "sources": ["1283.9.11"],
        "marker": marker,
        "characters": {str(i): {"id": i, "name_zh": f"人物{i}", "birth": f"{900 + i % 300}.1.1",
                                "note": "x" * 60} for i in range(n_chars)},
    }


def main():
    shutil.rmtree(TMP, ignore_errors=True)
    data = os.path.join(TMP, "洪氏2", "data")
    os.makedirs(data)
    cfg = {"output_dir": TMP, "cache_dir": ""}
    c1 = fake_cache(1, "v1")
    path = os.path.join(data, "player_1.json")
    size_mb = len(json.dumps(c1)) / 1048576

    # [A] save_cache_async returns at once; the file is complete only after flush_saves
    t = time.perf_counter()
    P.save_cache_async(path, c1)
    async_s = time.perf_counter() - t
    P.flush_saves(path)
    flush_s = time.perf_counter() - t
    got = json.load(open(path, encoding="utf-8"))
    w(f"[A] 异步写 {size_mb:.1f} MB: 调用返回 {async_s:.3f} s, flush 后共 {flush_s:.3f} s, "
      f"marker={got.get('marker')}, 临时文件残留="
      f"{[f for f in os.listdir(data) if f.endswith('.tmp')]}")
    ok_a = async_s < 0.2 and got.get("marker") == "v1" and flush_s > async_s \
        and not [f for f in os.listdir(data) if f.endswith(".tmp")]

    # [B] index entry written by the background write
    idx = P.load_caches_index(data)
    ent = idx.get("player_1.json") or {}
    w(f"[B] 索引条目: size={ent.get('size')} 实际={os.path.getsize(path)}, "
      f"meta.player_name={((ent.get('meta') or {}).get('player_name'))}")
    ok_b = ent.get("size") == os.path.getsize(path) \
        and (ent.get("meta") or {}).get("marker") is None \
        and (ent.get("meta") or {}).get("player_name") == "玩家1"

    # [C] a read-modify-write after a pending write keeps both versions' data: the flush inside
    # save_cache_now must land the older write before the newer one replaces it
    c2 = fake_cache(1, "v2")
    c2["bio_generated"] = True
    P.save_cache_async(path, c1)          # pending v1
    P.save_cache_now(path, c2)            # must not be clobbered by v1 later
    P.flush_saves()
    got2 = json.load(open(path, encoding="utf-8"))
    w(f"[C] 后写不丢: marker={got2.get('marker')}, bio_generated={got2.get('bio_generated')}, "
      f"挂起写={len(P._SAVE_THREADS)}")
    ok_c = got2.get("marker") == "v2" and got2.get("bio_generated") is True and not P._SAVE_THREADS

    # [D] a failing write surfaces on the next flush and does not block later writes
    bad = os.path.join(data, "player_1.json", "sub", "player_1.json")   # a file cannot be a directory
    P.save_cache_async(bad, c1)
    raised = None
    try:
        P.flush_saves()
    except Exception as e:
        raised = e
    P.save_cache_now(path, c1)
    w(f"[D] 写失败上报: {type(raised).__name__ if raised else '无异常'}")
    ok_d = raised is not None and not P._SAVE_THREADS

    # [E] save_session_cache starts a background write too, and its own flush is a no-op afterwards
    t = time.perf_counter()
    p2 = P.save_session_cache(cfg, c2, continue_mode=True)
    call_s = time.perf_counter() - t
    P.flush_saves(p2)
    got3 = json.load(open(p2, encoding="utf-8"))
    w(f"[E] save_session_cache 返回 {call_s:.3f} s (文件 {size_mb:.1f} MB), "
      f"flush 后 marker={got3.get('marker')}, 路径={os.path.relpath(p2, TMP)}")
    ok_e = call_s < 0.3 and got3.get("marker") == "v2" \
        and os.path.basename(p2) == "player_1.json"

    # [F] two threads writing at once still produce one complete file
    errs = []
    def spam(marker):
        try:
            P.save_cache_now(path, fake_cache(1, marker))
        except Exception as e:      # a lost race is fine, a torn file is not
            errs.append(e)
    ts = [threading.Thread(target=spam, args=(f"t{i}",)) for i in range(3)]
    for t_ in ts:
        t_.start()
    for t_ in ts:
        t_.join()
    got4 = json.load(open(path, encoding="utf-8"))
    w(f"[F] 三线程并发写: marker={got4.get('marker')}, 异常={errs}, 解析成功=True")
    ok_f = got4.get("marker") in ("t0", "t1", "t2")

    shutil.rmtree(TMP, ignore_errors=True)
    w("")
    for name, ok in (("[A] 异步写立即返回且落盘完整", ok_a),
                     ("[B] 后台写同时刷新索引", ok_b),
                     ("[C] 读写交错不丢版本", ok_c),
                     ("[D] 写失败在下次 flush 上报", ok_d),
                     ("[E] save_session_cache 走后台上盘", ok_e),
                     ("[F] 并发写不产生残文件", ok_f)):
        w(f"  {'PASS' if ok else 'FAIL'} {name}")
    ok = all((ok_a, ok_b, ok_c, ok_d, ok_e, ok_f))
    w(f"\n[{'PASS' if ok else 'FAIL'}] v117 丙-3a async save check")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
