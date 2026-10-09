# -*- coding: utf-8 -*-
"""v117 check (item 3 / 丙-4): the sidecar build is handed to a background worker.

The real `cl.save_melt_index` is replaced by a slow fake, so the test needs no melt: it checks that
`_prebuild_melt_index` returns immediately, that the worker runs the build, that the same path is not
queued twice, and that an existing sidecar or a vanished melt is skipped.

Usage: & tools\\py.ps1 tools\\tests\\v117_check_sidecar_queue.py
"""
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl       # noqa: E402
import pipeline as P         # noqa: E402

LOG = os.path.join(ROOT, "logs", "v117_check_sidecar_queue.txt")
TMP = os.path.join(ROOT, "logs", "_v117_sidecar_probe_melt.json")
TMP_HOLD = os.path.join(ROOT, "logs", "_v117_sidecar_probe_hold_melt.json")
TMP_IDX = os.path.join(ROOT, "logs", "_v117_sidecar_probe_melt_idx.json.gz")
buf = []
calls = []
hold_started = threading.Event()


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def main():
    open(TMP, "w", encoding="utf-8").write("{}")   # a stand-in melt file, never parsed
    open(TMP_HOLD, "w", encoding="utf-8").write("{}")
    real_save = cl.save_melt_index

    def fake_save(mp, melt):
        if isinstance(melt, dict) and melt.get("hold"):
            hold_started.set()                     # the worker is now inside the build
            time.sleep(0.5)
        else:
            time.sleep(0.4)                        # stand in for the 4-6 s build
        calls.append((mp, melt))
        return ""

    cl.save_melt_index = fake_save
    try:
        # [A] the call must not wait for the build
        t0 = time.perf_counter()
        P._prebuild_melt_index(TMP, {"stub": True})
        dt = time.perf_counter() - t0
        w(f"[A] _prebuild_melt_index 返回耗时 {dt*1000:.1f} ms（假构建 400 ms）")
        ok_a = dt < 0.2

        # [B] a second call while the first is pending is deduplicated
        P._prebuild_melt_index(TMP, {"stub": True})
        P._SIDECAR_QUEUE.join()
        w(f"[B] 假构建调用次数 = {len(calls)}（重复入队应被去掉）")
        ok_b = len(calls) == 1

        # [C] an existing sidecar means no build at all
        open(TMP_IDX, "w", encoding="utf-8").write("{}")
        P._prebuild_melt_index(TMP, {"stub": True})
        P._SIDECAR_QUEUE.join()
        w(f"[C] 侧车已存在时调用次数仍为 {len(calls)}")
        ok_c = len(calls) == 1
        os.remove(TMP_IDX)

        # [D] a melt archived away between queueing and the build is skipped, not failed. The worker
        # is held inside the first build, so the removal happens while the second item waits.
        hold_started.clear()
        P._prebuild_melt_index(TMP_HOLD, {"hold": True})
        hold_started.wait(2.0)
        P._prebuild_melt_index(TMP, {"stub": True})
        os.remove(TMP)
        P._SIDECAR_QUEUE.join()
        w(f"[D] 熔件在队列中消失后 TMP 构建次数 = {sum(1 for mp, _m in calls if mp == TMP)}"
          f"（那条应被跳过）")
        ok_d = sum(1 for mp, _m in calls if mp == TMP) == 1

        # [E] the worker rebuilds after a melt reappears, and the pending set empties
        open(TMP, "w", encoding="utf-8").write("{}")
        P._prebuild_melt_index(TMP, {"stub": True})
        P._SIDECAR_QUEUE.join()
        n_tmp = sum(1 for mp, _m in calls if mp == TMP)
        w(f"[E] 重新入队后 TMP 构建次数 = {n_tmp}；pending={sorted(P._SIDECAR_PENDING)}")
        ok_e = n_tmp == 2 and not P._SIDECAR_PENDING
    finally:
        cl.save_melt_index = real_save
        for p in (TMP, TMP_HOLD, TMP_IDX):
            if os.path.isfile(p):
                os.remove(p)

    w("")
    for name, ok in (("[A] 主线程不再等待构建", ok_a),
                     ("[B] 同路径去重", ok_b),
                     ("[C] 已有侧车跳过", ok_c),
                     ("[D] 熔件已归档则跳过", ok_d),
                     ("[E] 去重集合清空、可重建", ok_e)):
        w(f"  {'PASS' if ok else 'FAIL'} {name}")
    ok = all((ok_a, ok_b, ok_c, ok_d, ok_e))
    w(f"\n[{'PASS' if ok else 'FAIL'}] v117 丙-4 sidecar queue check")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
