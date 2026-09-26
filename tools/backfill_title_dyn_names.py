# -*- coding: utf-8 -*-
"""v66 回填：把头衔**动态名逐档沿革**补进既有玩家缓存（不重熔）。

用法：
    & tools\\tools\\py.ps1 tools\\backfill_title_dyn_names.py [家族 [玩家id]] [--dry] [--check]

    家族缺省 = output/ 下全部战役文件夹；玩家 id 缺省 = 该文件夹全部 player_*.json。
    --dry    只报告，不写盘
    --check  对每个缓存**最后一份**熔件用 load_melt 全量载入复核截段读取（逐键相同断言）
报告：logs/backfill_title_dyn_names.txt（同时打印到控制台）

为什么要有它：`cache["title_dyn_names"]`（v66）是逐档闩存的沿革表，而既有缓存
（`output/*/data/player_*.json`）都建于 v66 之前，没有这一格。重熔要 84 档 × 每档
数秒至数分钟；而本表只用熔件的 `landed_titles` 段（起于解压流 3.4 MB 处），流式截段
读取快得多（实测 `.json.xz` 1.5 s vs 全量 7.7 s）。

口径与「重跑 `_extract_snapshot`」**一致**，靠三点保证：
  1. 只回放 `cache["sources"]`（缓存真正并入过的那批档期），不拿整个文件夹的熔件 ——
     `sources` 正是 `_extract_snapshot` 通过玩家一致性校验后记下的档期；
  2. 熔件解析顺序复用 `pipeline.melt_file_in`（`_p<pid>` 优先，其次日期文件）——
     与生产链同一函数；
  3. 闩存走同一个 `cache_lib._latch_title_dyn_names`，故形状、去重、单调护栏都一样。

本键可重复回填：默认**先清空再按 sources 重放**（`--keep` 保留原有内容追加），
故重跑不会产生重复变化点。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl          # noqa: E402
import llm                      # noqa: E402
import pipeline as pipe         # noqa: E402

_lines = []


def w(s=""):
    _lines.append(str(s))
    print(s, flush=True)


def _pids_in(data_dir):
    out = []
    for fn in sorted(os.listdir(data_dir)):
        if fn.startswith("player_") and fn.endswith(".json"):
            try:
                out.append(int(fn[len("player_"):-len(".json")]))
            except ValueError:
                continue
    return out


def _replay(cfg, folder, pid, sources, seed=None):
    """按 sources 顺序回放动态名闩存；返回 (表, 缺档列表, 失败列表, 最后一份熔件)。

    seed 非空时（`--keep`）从既有沿革表续写 —— 走同一个 `_latch_title_dyn_names`，
    故去重与乱序护栏照旧；缺省从空表重放（幂等，重跑不产生重复变化点）。"""
    tmp = {"title_dyn_names": {k: list(v) for k, v in (seed or {}).items()}}
    missing, failed, last = [], [], None
    for date in sorted(sources, key=cl.date_key):
        p = pipe.melt_file_in(cfg, folder, date, pid)
        if not os.path.isfile(p):
            missing.append(date)
            continue
        lt = cl.load_melt_landed_titles(p)
        if not lt:
            failed.append(date)
            continue
        cl._latch_title_dyn_names(tmp, lt, date)
        last = (date, p)
    return tmp.get("title_dyn_names") or {}, missing, failed, last


def _check(cfg, folder, pid, last):
    """截段 vs 全量逐键相同（对一个缓存的最后一份熔件）。"""
    if not last:
        return None
    date, p = last
    section = cl.load_melt_landed_titles(p)
    melt = cl.load_melt(p)
    full = (melt.get("landed_titles") or {}).get("landed_titles") or {}
    ok = section == full
    w(f"      [check] {date} {os.path.basename(p)}: 截段 {len(section)} 条 / "
      f"全量 {len(full)} 条 → 逐键相同 = {ok}")
    del melt, full
    return ok


def backfill_folder(cfg, folder, only_pid, dry, check, keep):
    data_dir = pipe.campaign_data_dir(cfg, folder)
    if not os.path.isdir(data_dir):
        return 0, 0
    pids = [only_pid] if only_pid is not None else _pids_in(data_dir)
    if not pids:
        w(f"[{folder}] 无 player_*.json，跳过")
        return 0, 0
    n_ok = n_skip = 0
    for pid in pids:
        path = os.path.join(data_dir, f"player_{pid}.json")
        if not os.path.isfile(path):
            w(f"[{folder}] player_{pid}.json 不存在，跳过")
            continue
        cache = cl.load_cache(path, fresh=True)
        if cache.get("player_id") not in (None, pid):
            w(f"[{folder}] player_{pid}.json 内 player_id="
              f"{cache.get('player_id')} 与文件名不符，跳过")
            n_skip += 1
            continue
        sources = cache.get("sources") or []
        if not sources:
            w(f"[{folder}] player_{pid}: sources 为空（缓存未并入过档期），跳过")
            n_skip += 1
            continue
        table, missing, failed, last = _replay(
            cfg, folder, pid, sources,
            seed=(cache.get("title_dyn_names") or {}) if keep else None)
        pts = sum(len(v) for v in table.values())
        kb = len(json.dumps(table, ensure_ascii=False,
                            separators=(",", ":"))) / 1024
        w(f"[{folder}] player_{pid}: sources {len(sources)} 档 → "
          f"命中 {len(sources) - len(missing) - len(failed)}，头衔 {len(table)}，"
          f"变化点 {pts}，{kb:.0f} KB")
        if missing:
            w(f"      缺熔件 {len(missing)} 档: {', '.join(missing[:6])}"
              f"{' …' if len(missing) > 6 else ''}")
        if failed:
            w(f"      取段失败 {len(failed)} 档: {', '.join(failed[:6])}")
        if check:
            ok = _check(cfg, folder, pid, last)
            if ok is False:
                w("      [check] 失败 —— 截段与全量不一致，放弃写入")
                n_skip += 1
                continue
        if dry:
            n_ok += 1
            continue
        bak = path + ".bak_v66"
        if not os.path.isfile(bak):
            with open(path, "rb") as src, open(bak, "wb") as dst:
                dst.write(src.read())
            w(f"      已备份 {os.path.basename(bak)}")
        cache["title_dyn_names"] = table
        try:
            cl.save_cache(cache, path)
        except OSError as e:
            # 该缓存正被别的进程打开 (watch 主循环 / 传记线程) 时 Windows 拒绝
            # 原子替换 → 记下并跳过, 不中断整批回填
            w(f"      [跳过] 写盘失败 ({e.__class__.__name__}: {e}) —— "
              f"该缓存可能正被 watch/传记进程占用, 停掉后重跑本工具即可")
            n_skip += 1
            continue
        n_ok += 1
    return n_ok, n_skip


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    folder = args[0] if args else None
    only_pid = int(args[1]) if len(args) > 1 else None
    dry = "--dry" in flags
    check = "--check" in flags
    keep = "--keep" in flags
    cfg = llm.load_config()
    out_dir = cfg.get("output_dir", "")
    folders = [folder] if folder else sorted(
        f for f in os.listdir(out_dir)
        if os.path.isdir(os.path.join(out_dir, f, "data")))
    w(f"# backfill_title_dyn_names v66  dry={dry} check={check} keep={keep} "
      f"folders={len(folders)}")
    tot_ok = tot_skip = 0
    for fol in folders:
        ok, skip = backfill_folder(cfg, fol, only_pid, dry, check, keep)
        tot_ok += ok
        tot_skip += skip
    w(f"# 完成: 写入 {tot_ok} 份缓存, 跳过 {tot_skip} 份"
      f"{'（--dry 未写盘）' if dry else ''}")
    out = os.path.join(ROOT, "logs", "backfill_title_dyn_names.txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        fp.write("\n".join(_lines))
    print(f"报告: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
