# -*- coding: utf-8 -*-
"""回填 v81 新增的 `first_location` 闩存（角色**首见快照**的所在）

用法：
    & tools\tools\\py.ps1 tools\\backfill_first_location.py <家族> [pid ...]

为什么要有它：`cache_lib` v81 起在 ingest 时记 `first_location`（**出生地**的唯一依据，
见 `facts.Facts.birth_place` 与 `docs/调研_v81_生卒地点.md`），而既有缓存没有这一键。
整份 `tools/rebuild_folder.py` 要把该战役上百份熔件全量解析一遍；本脚本按用户
2026-09-29 的口径**只回填主角的家族成员**（`facts` 侧也只给这些人的档案写生卒地），
故只流式取每份熔件的 `living` 段（`cache_lib.load_melt_section`），且**收齐即停**。

口径：
  · 目标 = 各传主缓存里的「主角 + 主角 family 各族」（配偶/妾/子女/父母/同胞/前配偶）；
  · 只回填目标缓存里**已有**的角色（不给缓存添新人）；已有 `first_location` 不覆盖（幂等）；
  · 取战役全部档期里最早的观测（跨缓存同值）。
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402

MELT_RE = re.compile(r"melt_(\d+)_(\d{2})_(\d{2})(?:_p\d+)?\.json(?:\.gz|\.xz)?$")
KIN_KEYS = ("primary_spouse", "spouse", "former_spouses", "child", "concubine",
            "former_concubines", "father", "mother", "siblings", "ever_spouses")


def melt_key(fn):
    m = MELT_RE.match(fn)
    return tuple(int(x) for x in m.groups()) if m else (9999, 1, 1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    folder = sys.argv[1]
    want_pids = [int(x) for x in sys.argv[2:] if x.isdigit()]
    data = os.path.join(ROOT, "output", folder, "data")
    if not os.path.isdir(data):
        print("找不到战役目录: %s" % data)
        return 2
    caches = {}
    for fn in sorted(os.listdir(data)):
        if not (fn.startswith("player_") and fn.endswith(".json")):
            continue
        pid = int(fn[7:-5])
        if want_pids and pid not in want_pids:
            continue
        caches[pid] = json.load(io.open(os.path.join(data, fn), encoding="utf-8"))
    if not caches:
        print("没有可回填的缓存")
        return 2
    # 目标 = 各缓存的主角 + 其家族成员 (只取缓存里已有的)
    targets = {}          # cid(str) -> set(pid)
    for pid, c in caches.items():
        ch = c.get("characters") or {}
        ids = {str(pid)}
        rec = ch.get(str(pid)) or {}
        fam = rec.get("family") or {}
        for k in KIN_KEYS:
            ids |= {str(x) for x in (fam.get(k) or []) if isinstance(x, int)}
        for cid in ids:
            if cid in ch:
                targets.setdefault(cid, set()).add(pid)
        print("  pid=%s 家族目标 %d 人" % (pid, len([x for x in ids if x in ch])),
              flush=True)

    melts = sorted((f for f in os.listdir(data) if MELT_RE.match(f)), key=melt_key)
    print("目标角色 %d 名; 熔件 %d 档, 按日期升序扫描 living 段 (收齐即停) …"
          % (len(targets), len(melts)), flush=True)
    found = {}
    for i, fn in enumerate(melts, 1):
        left = set(targets) - set(found)
        if not left:
            print("  已在第 %d 档收齐" % (i - 1), flush=True)
            break
        try:
            liv = cl.load_melt_section(os.path.join(data, fn), "living") or {}
        except Exception as e:
            print("  !! %s: %s" % (fn, e), flush=True)
            continue
        d = "%d.%d.%d" % melt_key(fn)
        for cid in left:
            obj = liv.get(cid)
            if not isinstance(obj, dict):
                continue
            loc = (obj.get("alive_data") or {}).get("location") or {}
            prov = loc.get("location") if isinstance(loc, dict) else loc
            if isinstance(prov, int):
                found[cid] = {"date": d, "province": prov}
        if i % 10 == 0:
            print("  … %d/%d 档, 已得 %d/%d 人"
                  % (i, len(melts), len(found), len(targets)), flush=True)

    n = 0
    for pid, c in caches.items():
        ch = c.get("characters") or {}
        hit = 0
        for cid, fl in found.items():
            if pid not in targets.get(cid, ()):
                continue
            r = ch.get(cid)
            if isinstance(r, dict) and not r.get("first_location"):
                r["first_location"] = dict(fl)
                hit += 1
        n += hit
        path = os.path.join(data, "player_%d.json" % pid)
        with io.open(path, "w", encoding="utf-8") as fh:
            json.dump(c, fh, ensure_ascii=False)
        print("  player_%d.json: 回填 %d 条" % (pid, hit), flush=True)
    print("合计回填 %d 条 first_location (目标 %d 人, 未得 %d 人)"
          % (n, len(targets), len(targets) - len(found)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
