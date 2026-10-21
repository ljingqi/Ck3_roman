# -*- coding: utf-8 -*-
"""v110 核对表：全宗族「血缘词 + 兼链」旧法 / 新法逐对比对（只读 · 缓存面）。

为「堂表亲戚读取新方法」做前后对照：同一批 (传主, 亲属) 有序对，先按旧法落一份
`logs/v110/v110_before.json`，改完 facts.py 再落 `logs/v110/v110_after.json`，用
`--diff` 直接打印差异表（新增词 / 丢失词 / 改词），逐条审错。

范围：某个战役缓存里**同一家族（dynasty_house / house_name）∪ 在册亲属**的全体人物，
两两有序对中「有共同祖先」的那些（无共同祖先的对不可能出额外的血缘路线词）。
只走缓存，不载熔件：宫廷 / 会议席位 / 摄政词天然为空，前后一致，不影响比对。

用法：
    & tools\\py.ps1 tools\\tests\\v110_kin_table.py dump <folder> <pid> <out.json>
    & tools\\py.ps1 tools\\tests\\v110_kin_table.py diff <before.json> <after.json> [--top N]
"""
import argparse
import collections
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402

_MAXD = 5


def family_ids(chars, pid):
    """家族角色集：同宗（dynasty_house / house_name）∪ 这些人的在册亲属。"""
    p = chars.get(str(pid)) or {}
    dyn_house, house = p.get("dynasty_house"), p.get("house_name")
    out = set()
    for k, rec in chars.items():
        if not k.isdigit() or not isinstance(rec, dict):
            continue
        if (dyn_house is not None and rec.get("dynasty_house") == dyn_house) \
                or (house and rec.get("house_name") == house):
            out.add(int(k))
    seeds = list(out)
    for cid in seeds:
        fam = ((chars.get(str(cid)) or {}).get("family") or {})
        for val in fam.values():
            for y in (val or []):
                if isinstance(y, int) and str(y) in chars:
                    out.add(y)
    return out


def ancestor_set(x, fath, moth):
    """{ancestor} reachable from x within _MAXD hops (no ban) -- candidate pruning only."""
    seen = {x}
    frontier = [x]
    for _ in range(_MAXD):
        nxt = []
        for n in frontier:
            for p in list(fath.get(n) or ()) + list(moth.get(n) or ()):
                if p not in seen:
                    seen.add(p)
                    nxt.append(p)
        if not nxt:
            break
        frontier = nxt
    seen.discard(x)
    return seen


def _dump_one(folder, pid):
    """One campaign's table: {'pid','roster','pairs':[{s,c,blood,chain}]}."""
    data = os.path.join(ROOT, "output", folder, "data")
    cache_path = os.path.join(data, "player_%d.json" % pid)
    t0 = time.time()
    cache = json.load(open(cache_path, encoding="utf-8"))
    names_path = os.path.join(data, "names.json")
    if not os.path.exists(names_path):
        names_path = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, {}, names_path)
    chars = cache.get("characters") or {}
    fath, moth = f._parent_maps()
    roster = sorted(family_ids(chars, pid))
    print("战役 %s 家族 %d 人（载入 %.1fs）" % (pid, len(roster), time.time() - t0), flush=True)
    anc = {}
    for cid in roster:
        anc[cid] = ancestor_set(cid, fath, moth)
    pairs = []
    t1 = time.time()
    for i, s in enumerate(roster):
        if i and i % 100 == 0:
            print("  …主体 %d/%d（%d 对，%.0fs）"
                  % (i, len(roster), len(pairs), time.time() - t1), flush=True)
        for c in roster:
            if c == s or not (anc[s] & anc[c]):
                continue
            try:
                blood = f.blood_kin_words_for(c, s)
                chain = f.kin_chain_words_for(c, s)
            except Exception as e:                    # 单对异常不该毁掉整张表
                blood, chain = ["<ERR:%s>" % e], []
            pairs.append({"s": s, "c": c, "blood": blood, "chain": chain})
    print("  战役 %s 完成：%d 对（%.0fs）" % (pid, len(pairs), time.time() - t1), flush=True)
    return {"folder": folder, "pid": pid, "roster_size": len(roster), "pairs": pairs}


def dump(folder, pid, out_path):
    out = _dump_one(folder, pid)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("→ %s : %d 对" % (out_path, len(out["pairs"])))
    return out


def dump_all(folder, out_path):
    """Every campaign of the folder, one after another (each cache freed before the next)."""
    import glob
    caches = sorted(glob.glob(os.path.join(ROOT, "output", folder, "data", "player_*.json")))
    pids = [int(os.path.basename(p)[7:-5]) for p in caches]
    print("战役 %d 个：%s" % (len(pids), pids), flush=True)
    camps = []
    for pid in pids:
        camps.append(_dump_one(folder, pid))
    out = {"folder": folder, "campaigns": camps}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("→ %s : %d 战役 / %d 对"
          % (out_path, len(camps), sum(len(c["pairs"]) for c in camps)))
    return out


def _key(rec):
    return (rec["s"], rec["c"])


def _load(path):
    """{(pid, s, c): rec} for both the single-campaign and the all-campaigns dump shape."""
    j = json.load(open(path, encoding="utf-8"))
    camps = j["campaigns"] if "campaigns" in j else [j]
    out = {}
    for camp in camps:
        pid = camp["pid"]
        for r in camp["pairs"]:
            out[(pid, r["s"], r["c"])] = r
    return out, camps


def diff(before_path, after_path, top=0, width=40, out_path=None):
    bm, bcamps = _load(before_path)
    am, acamps = _load(after_path)
    added_pairs = sorted(set(am) - set(bm))
    gone_pairs = sorted(set(bm) - set(am))
    stat = collections.Counter()
    rows = []
    for k in sorted(set(bm) & set(am)):
        bw, aw = bm[k]["blood"], am[k]["blood"]
        if bw == aw:
            continue
        stat["血词变化对"] += 1
        new_words = [w for w in aw if w not in bw]
        lost_words = [w for w in bw if w not in aw]
        if new_words:
            stat["新增词对"] += 1
            stat["新增词次"] += len(new_words)
        if lost_words:
            stat["丢失词对"] += 1
            stat["丢失词次"] += len(lost_words)
        if len(aw) > len(bw):
            stat["变长"] += 1
        elif len(aw) < len(bw):
            stat["变短"] += 1
        if set(bw) == set(aw) and bw != aw:
            stat["仅换序"] += 1
            continue
        rows.append((k, bw, aw, new_words, lost_words))
    print("战役 %d 个（旧）/ %d 个（新）" % (len(bcamps), len(acamps)))
    print("旧 %d 对 / 新 %d 对；仅有共同祖先的对参与比对" % (len(bm), len(am)))
    print("新增对 %d / 消失对 %d" % (len(added_pairs), len(gone_pairs)))
    for k in ("血词变化对", "新增词对", "新增词次", "丢失词对", "丢失词次", "变长", "变短", "仅换序"):
        print("  %s: %d" % (k, stat[k]))
    # 新增/丢失的词频次榜（看新增的是不是集中在某一类词）
    nw_freq, lw_freq = collections.Counter(), collections.Counter()
    for _k, _bw, _aw, nw, lw in rows:
        nw_freq.update(nw)
        lw_freq.update(lw)
    print("新增词榜: %s" % nw_freq.most_common(30))
    print("丢失词榜: %s" % lw_freq.most_common(30))
    print("-" * 78)
    lim = top or len(rows)
    text = []
    for k, bw, aw, nw, lw in rows[:lim]:
        pid, s, c = k
        blk = ["campaign=%d s=%d c=%d" % (pid, s, c),
               "   旧 %s" % "、".join(bw),
               "   新 %s" % "、".join(aw)]
        if nw:
            blk.append("   + %s" % "、".join(nw))
        if lw:
            blk.append("   - %s" % "、".join(lw))
        print("\n".join(blk))
        text.append("\n".join(blk))
    if lim < len(rows):
        print("… 其余 %d 对见 JSON" % (len(rows) - lim))
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(text) + "\n")
        print("→ %s" % out_path)
    return rows, stat


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("folder")
    d.add_argument("pid", type=int)
    d.add_argument("out")
    da = sub.add_parser("dump-all")
    da.add_argument("folder")
    da.add_argument("out")
    df = sub.add_parser("diff")
    df.add_argument("before")
    df.add_argument("after")
    df.add_argument("--top", type=int, default=0)
    df.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.cmd == "dump":
        dump(args.folder, args.pid, args.out)
    elif args.cmd == "dump-all":
        dump_all(args.folder, args.out)
    else:
        diff(args.before, args.after, args.top, out_path=args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
