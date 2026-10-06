# -*- coding: utf-8 -*-
"""v110 probe: 死亡地点逐人前后对照（只读 · 载一次熔件）。

对某个战役缓存里**每一个有死亡记录的人**，落一行证据：
死因/卒日、`death.location_province`、`last_location`(+与卒日相距天数)、
死亡当日所持头衔（含世族庄园）、按新解析器算出的「座位省份/地名」、以及
`Facts.victim_place(cid)` 当前返回的地名。改 facts.py 前后各跑一次，
`diff` 就是死亡地点的完整前后表（谁的地点变了、从什么变成什么、谁从空变有）。

用法：
    & tools\\py.ps1 tools\\tests\\v110_probe_death_place.py dump <folder> <pid> <out.json>
    & tools\\py.ps1 tools\\tests\\v110_probe_death_place.py diff <before.json> <after.json>
"""
import argparse
import datetime
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402
import localization as L    # noqa: E402


def _days(d1, d2):
    try:
        a = [int(x) for x in str(d1).split(".")[:3]]
        b = [int(x) for x in str(d2).split(".")[:3]]
        return (datetime.date(*b) - datetime.date(*a)).days
    except Exception:
        return None


def _melt_path(folder):
    data = os.path.join(ROOT, "output", folder, "data")
    melts = [x for x in os.listdir(data) if x.startswith("melt_") and "_idx" not in x]

    def key(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)

    return os.path.join(data, max(melts, key=key)), data


def _seat_probe(f, cid, date):
    """The seat `Facts._seat_province_at` picks, plus the per-holding rows it chose among.

    The province comes from the production method itself (no local copy, so the probe cannot drift
    from what `victim_place` uses); `seat_tid` is the holding whose province it returned, recovered
    from the rows for display only."""
    prov = f._seat_province_at(cid, date)
    rows = []
    anchor = date or f.as_of
    if anchor:
        ak = cl.date_key(str(anchor))
        for tid, ivs in (f._hold_intervals(cid, anchor) or {}).items():
            rec = f._lt.get(str(tid)) or {}
            key = rec.get("key") or ""
            if not key:
                continue
            cap = rec.get("capital")
            for iv in (ivs or []):
                if not f._iv_covers(iv, ak):
                    continue
                rows.append({"tid": tid, "key": key, "capital": cap,
                             "rank": f._TT_RANK.get(key[:2], 0),
                             "estate": bool(f._is_estate_title(tid)),
                             "prov": f._prov_inv().get(key), "gain": iv[0]})
    tid = next((r["tid"] for r in rows if r["prov"] == prov), None)
    return tid, prov, rows


def dump(folder, pid, out_path):
    data = os.path.join(ROOT, "output", folder, "data")
    melt_path, _ = _melt_path(folder)
    cache = json.load(open(os.path.join(data, "player_%d.json" % pid), encoding="utf-8"))
    print("载入熔件 %s" % os.path.basename(melt_path), flush=True)
    melt = cl.load_melt(melt_path)
    names_path = os.path.join(data, "names.json")
    if not os.path.exists(names_path):
        names_path = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, melt, names_path)
    chars = cache.get("characters") or {}
    rows = []
    for k, rec in chars.items():
        if not str(k).isdigit() or not isinstance(rec, dict):
            continue
        d = rec.get("death") or {}
        if not d.get("date"):
            continue
        cid = int(k)
        ll = rec.get("last_location") or {}
        seat_tid, seat_prov, holdings = _seat_probe(f, cid, d.get("date"))
        rows.append({
            "cid": cid,
            "death": d.get("date"),
            "reason": str(d.get("reason") or ""),
            "killer": d.get("killer"),
            "vp": f.victim_place(cid),
            "death_prov": d.get("location_province"),
            "ll_prov": ll.get("province"),
            "ll_date": ll.get("date"),
            "ll_gap": _days(ll.get("date"), d.get("date")),
            "seat_tid": seat_tid,
            "seat_key": (f._lt.get(str(seat_tid)) or {}).get("key") if seat_tid else None,
            "seat_prov": seat_prov,
            "seat_place": f._place_of_province(seat_prov) if isinstance(seat_prov, int) else "",
            "holdings": holdings,
        })
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"folder": folder, "pid": pid, "dead": rows}, fh,
                  ensure_ascii=False, indent=1)
    print("→ %s : %d 名死者" % (out_path, len(rows)))
    return rows


def show(before_path, after_path):
    b = json.load(open(before_path, encoding="utf-8"))
    a = json.load(open(after_path, encoding="utf-8"))
    bm = {r["cid"]: r for r in b["dead"]}
    am = {r["cid"]: r for r in a["dead"]}
    changed = []
    for cid in sorted(set(bm) & set(am)):
        x, y = bm[cid], am[cid]
        if x["vp"] != y["vp"]:
            changed.append((cid, x, y))
    print("旧 %d 死者 / 新 %d 死者；victim_place 变化 %d 人"
          % (len(bm), len(am), len(changed)))
    n_empty = sum(1 for _c, x, y in changed if x["vp"] and not y["vp"])
    n_fill = sum(1 for _c, x, y in changed if not x["vp"] and y["vp"])
    n_swap = sum(1 for _c, x, y in changed if x["vp"] and y["vp"])
    print("  空→有 %d / 有→空 %d / 换名 %d" % (n_fill, n_empty, n_swap))
    for cid, x, y in changed:
        print("  cid=%-10s %s  卒=%s  原因=%s" % (cid, x["vp"] or "''", x["death"], x["reason"]))
        print("       → %s    (坐席 %s %s / ll %s %s 天前 / death_prov %s)"
              % (y["vp"] or "''", y["seat_key"], y["seat_place"],
                 y["ll_prov"], y["ll_gap"], y["death_prov"]))
    return changed


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("folder")
    d.add_argument("pid", type=int)
    d.add_argument("out")
    df = sub.add_parser("diff")
    df.add_argument("before")
    df.add_argument("after")
    args = ap.parse_args()
    if args.cmd == "dump":
        dump(args.folder, args.pid, args.out)
    else:
        show(args.before, args.after)
    return 0


if __name__ == "__main__":
    sys.exit(main())
