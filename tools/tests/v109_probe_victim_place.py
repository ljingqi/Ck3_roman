# -*- coding: utf-8 -*-
"""v109 probe: what does `victim_place` resolve to, and is it the victim's real death place?

Read-only. Default mode reads **existing facts snapshots only** (no melt, no cache):
every snapshot that carries `facts.killed` is tabulated entry by entry (victim id, name,
victim_place, the victim's own titles/office/label, the killer, the death wording), then a
deduplicated statistic is printed (empty / consistent-with-the-victim's-own-seat / not).

`--deep` additionally loads one player cache (that is a cache, never a melt) and dumps the
raw location evidence of every victim of that snapshot: `death`, `death.location_province`,
`last_location`, `first_location`, plus the player's `capital_history` and station track.

Usage:
    & tools\\py.ps1 tools\\tests\\v109_probe_victim_place.py
    & tools\\py.ps1 tools\\tests\\v109_probe_victim_place.py --deep
Output:
    logs/v109/v109_victim_place.txt (UTF-8)
"""
import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "logs", "v109_victim_place.txt")
MAX_SNAP_BYTES = 12 * 1024 * 1024      # snapshots are tens of KB..5 MB; skip caches/melts
# Death causes counted as a judicial killing, kept in step with facts.py:18828
# (`_PRISON_EXEC_REASONS`), so the probe can tell which branch of victim_place fired.
_PRISON_EXEC_REASONS = frozenset({"death_execution", "death_punishment", "death_imprisonment",
                                  "death_dungeon", "death_eradicated"})
LINES = []


def _day_gap(d1, d2):
    """Whole days from d1 to d2, or '?' when either date is missing/unparsable."""
    try:
        import datetime
        a = [int(x) for x in str(d1).split(".")[:3]]
        b = [int(x) for x in str(d2).split(".")[:3]]
        return (datetime.date(*b) - datetime.date(*a)).days
    except Exception:
        return "?"


def w(s=""):
    LINES.append(str(s))
    print(s, flush=True)


def _load_small_json(path):
    try:
        if os.path.getsize(path) > MAX_SNAP_BYTES:
            return None
        with open(path, encoding="utf-8") as fp:
            return json.load(fp)
    except Exception as e:
        w("  !! 读取失败 %s: %s" % (path, e))
        return None


def _is_snapshot(d):
    if not isinstance(d, dict):
        return False
    f = d.get("facts")
    return isinstance(f, dict) and isinstance(f.get("killed"), list)


def _find_snapshots():
    """Every snapshot-ish JSON under output/*/data (facts.killed present)."""
    out = []
    for p in sorted(glob.glob(os.path.join(ROOT, "output", "*", "data", "*.json"))):
        d = _load_small_json(p)
        if _is_snapshot(d):
            out.append((p, d))
    return out


def _split_titles(s):
    return [x.strip() for x in str(s or "").replace("、", "；").split("；") if x.strip()]


def _own_text(k, prof):
    """All text that counts as 'the victim's own seat/office/name' for the consistency check."""
    bits = [k.get("office"), k.get("label"), k.get("name"), k.get("house"),
            k.get("house_label")]
    if prof:
        bits += [prof.get("office"), prof.get("label"), prof.get("name"),
                 prof.get("titles_held"), prof.get("seat_note"), prof.get("house")]
    return [str(b) for b in bits if b]


def _last_title(prof):
    """The victim's last recorded title line (his title when he died: profiles stop at death)."""
    tl = _split_titles((prof or {}).get("titles_held"))
    return tl[-1] if tl else ""


def _place_verdict(k, prof):
    """Classify victim_place against the victim's own recorded titles.

    Returns (verdict, detail):
      '空'            – no place at all
      '死亡时封地命中' – the place occurs in his office or in the last title line (his seat at death)
      '生前曾领命中'   – the place occurs only in an earlier title line (a place he held before)
      '不符'          – the place occurs nowhere in his own record
    """
    vp = str(k.get("victim_place") or "").strip()
    if not vp:
        return "空", ""
    office = str((k.get("office") or (prof or {}).get("office") or ""))
    if vp in office:
        return "死亡时封地命中", "office=%r" % office
    last = _last_title(prof)
    if last and vp in last:
        return "死亡时封地命中", "末条封地=%r" % last
    tl = _split_titles((prof or {}).get("titles_held"))
    hit = [x for x in tl if vp in x]
    if hit:
        return "生前曾领命中", "曾领=%r" % hit[-1]
    return "不符", ""



def _victim_rows(snap):
    """[(k, prof, group_members)] for one snapshot."""
    facts = snap.get("facts") or {}
    profs = facts.get("characters") or {}
    rows = []
    for k in facts.get("killed") or []:
        cid = str(k.get("id"))
        prof = profs.get(cid) or {}
        rows.append((k, prof, list(k.get("group") or [])))
    return rows


def probe_snapshots(args):
    snaps = _find_snapshots()
    w("=" * 100)
    w("v109 victim_place 调研 —— 只读快照抽查")
    w("快照目录口径: output/*/data/*.json 且顶层含 facts.killed；单文件上限 %d 字节"
      % MAX_SNAP_BYTES)
    w("命中快照 %d 份" % len(snaps))
    w("=" * 100)
    w()

    # ---- structure dump: what the snapshot actually carries ----
    w("---- 0. 快照结构（取第一份带 killed 的快照）----")
    if snaps:
        _p, d = snaps[0]
        facts = d["facts"]
        w("快照: %s" % os.path.relpath(_p, ROOT))
        w("meta: %s" % json.dumps(d.get("meta") or {}, ensure_ascii=False)[:400])
        w("facts 顶层键: %s" % ", ".join(sorted(facts.keys())))
        k0 = (facts.get("killed") or [{}])[0]
        w("killed[0] 键: %s" % ", ".join(sorted(k0.keys())))
        w("killed[0] 样例行: %s" % json.dumps(k0, ensure_ascii=False)[:500])
        prof0 = (facts.get("characters") or {}).get(str(k0.get("id"))) or {}
        w("characters[%s] 键: %s" % (k0.get("id"), ", ".join(sorted(prof0.keys()))))
    w()

    # ---- per snapshot table ----
    w("---- 1. 逐快照：刺客/凶手条目明细 ----")
    dedup = {}          # (folder, pid, cid) -> (snapshot, k, prof, verdict)
    dup_rows = 0
    for path, d in snaps:
        meta = d.get("meta") or {}
        folder = meta.get("folder") or os.path.basename(os.path.dirname(os.path.dirname(path)))
        pid = meta.get("player_id")
        as_of = meta.get("as_of")
        facts = d["facts"]
        player_name = facts.get("player_name") or (facts.get("protagonist") or {}).get("name")
        w("-" * 100)
        w("快照 %s | 家族=%s pid=%s as_of=%s melt=%s | 传主=%s"
          % (os.path.relpath(path, ROOT), folder, pid, as_of, meta.get("melt"), player_name))
        rows = _victim_rows(d)
        w("  killed 条目 %d 个（含并案组）" % len(rows))
        for k, prof, grp in rows:
            vp = (k.get("victim_place") or "").strip()
            verdict, detail = _place_verdict(k, prof)
            w("  · cid=%-10s %s" % (k.get("id"), k.get("label") or k.get("name")))
            w("      生=%s 卒=%s" % (k.get("birth") or "?", k.get("death_date") or "?"))
            w("      死法句: %s" % (k.get("death") or "")[:150])
            w("      victim_place=%r → %s %s" % (vp, verdict, detail))
            w("      自身官职/头衔: office=%r titles_held=%r label=%r"
              % (k.get("office"), prof.get("titles_held"), k.get("label")))
            w("      死者在世封地档案? profile 存在=%s 死亡地字段=%r"
              % (bool(prof), prof.get("death_place")))
            w("      凶手=传主 %s(%s)；killer_public=%s"
              % (player_name, pid, k.get("killer_public")))
            for g in grp:
                gvp = (g.get("victim_place") or "").strip()
                w("      ├ 并案同死者 cid=%s %s victim_place=%r 卒=%s"
                  % (g.get("id"), g.get("label") or g.get("name"), gvp,
                     g.get("death_date")))
            key = (str(folder), str(pid), str(k.get("id")))
            if key in dedup:
                dup_rows += 1
            dedup[key] = (path, k, prof, verdict)
        w()

    # ---- deduplicated statistics ----
    w("=" * 100)
    w("---- 2. 去重统计（键 = 家族 + pid + 死者 cid，同一死者取最后读到的快照）----")
    w("明细行 %d 条，去重后 %d 个死者，重复覆盖 %d 条" % (len(dedup) + dup_rows, len(dedup), dup_rows))
    counts = {}
    miss_list = []
    by_place = {}
    for key, (path, k, prof, verdict) in sorted(dedup.items()):
        vp = (k.get("victim_place") or "").strip()
        counts[verdict] = counts.get(verdict, 0) + 1
        if verdict == "不符":
            miss_list.append((key, path, k, prof))
        by_place[vp or "(空)"] = by_place.get(vp or "(空)", 0) + 1
    w("地点为空              : %d" % counts.get("空", 0))
    w("地点 = 死亡时官职/封地 : %d" % counts.get("死亡时封地命中", 0))
    w("地点 = 生前曾领(非末任): %d" % counts.get("生前曾领命中", 0))
    w("地点 与死者自身记录无关 : %d" % counts.get("不符", 0))
    w()
    # The '不符' rows split into two very different classes: `facts.victim_place` returns the
    # protagonist's capital for a judicial execution (facts.py:16235-16243), so that place recurs
    # across many victims of one campaign; a place used by exactly one victim of a campaign is the
    # `last_location` fallback, i.e. where that man happened to stand at the previous annual
    # snapshot — the class the 蔡偕 case belongs to.
    freq = {}
    for key, (_p, k, _prof, _v) in dedup.items():
        place = (k.get("victim_place") or "").strip()
        if place:
            freq[(key[0], key[1], place)] = freq.get((key[0], key[1], place), 0) + 1
    shared = unique = 0
    camp = {}
    for key, (path, k, prof, verdict) in sorted(dedup.items()):
        place = (k.get("victim_place") or "").strip()
        c = camp.setdefault((key[0], key[1]),
                            {"n": 0, "empty": 0, "own": 0, "shared": 0, "unique": 0,
                             "suspect": []})
        c["n"] += 1
        if not place:
            c["empty"] += 1
        elif verdict != "不符":
            c["own"] += 1
        elif freq[(key[0], key[1], place)] >= 3:
            c["shared"] += 1
            shared += 1
        else:
            c["unique"] += 1
            unique += 1
            c["suspect"].append((key[2], k.get("label") or k.get("name"), place))
    w("  ├ 其中「本战役内多人共用同一地名」(≥3人，符合处决→主角首都那条设计路径): %d" % shared)
    w("  └ 其中「本战役内孤例地名」(多为 last_location 陈旧值): %d" % unique)
    w()
    w("---- 2b. 逐战役小计（家族/pid: 死者数 空 自领 多人共用 孤例）----")
    for (folder, pid), c in sorted(camp.items()):
        w("  %s pid=%-10s n=%-4d 空=%-3d 自领=%-3d 共用=%-4d 孤例=%-4d"
          % (folder, pid, c["n"], c["empty"], c["own"], c["shared"], c["unique"]))
        for cid, label, place in c["suspect"][:6]:
            w("       孤例 cid=%-10s %-24s %s" % (cid, label, place))
    w()
    w("出现过的地点（去重后计数）:")
    for place, n in sorted(by_place.items(), key=lambda x: (-x[1], x[0])):
        w("  %-10s %d" % (place, n))
    w()

    # ---- day-cohort cross-check: victims dying the same day should share one place ----
    w("---- 3. 同日死者地点一致性（同日死于同一手，地点应当相同）----")
    cohorts = {}
    for key, (path, k, prof, verdict) in dedup.items():
        dd = k.get("death_date") or ""
        if not dd or dd.startswith("9999"):
            continue
        cohorts.setdefault((key[0], key[1], dd), []).append((key[2], k, path))
    mixed = 0
    for (folder, pid, dd), members in sorted(cohorts.items()):
        if len(members) < 2:
            continue
        places = {(m[1].get("victim_place") or "").strip() for m in members}
        flag = "一致" if len(places) == 1 else "不一致"
        if len(places) > 1:
            mixed += 1
        w("  %s pid=%s %s: %d 人 %s %s" % (folder, pid, dd, len(members), flag,
                                           sorted(places)))
        for cid, k, _p in members:
            w("      cid=%-10s %-20s victim_place=%r"
              % (cid, k.get("label") or k.get("name"), (k.get("victim_place") or "").strip()))
    w("  同日地点不一致的组: %d" % mixed)
    w()

    # ---- suspicious list ----
    w("---- 4. 地点与死者自身记录完全无关的条目（下轮重点核查对象）----")
    for key, path, k, prof in miss_list:
        w("  %s pid=%s cid=%s %s | victim_place=%r | office=%r | titles_held=%r"
          % (key[0], key[1], key[2], k.get("label") or k.get("name"),
             (k.get("victim_place") or "").strip(), k.get("office"),
             prof.get("titles_held")))
    w()

    if args.deep or args.deep_focus:
        deep_dump(dedup, args.deep_focus)
    return len(snaps)


def _prov_namer():
    """province id -> 'b_x=<中文男爵领>, c_y=<中文郡>' via data/province_map.json + 本地化表.

    Neither source is the melt, so the probe stays melt-free."""
    try:
        import llm
        import localization as L
        pm = L.province_map(llm.load_config())
        tbl = L.table()
    except Exception as e:
        w("  (省名解码不可用: %s)" % e)
        return lambda prov: ""

    def name(prov):
        e = pm.get(int(prov)) or {}
        if not isinstance(e, dict):
            e = {"county": e}
        bits = []
        for kind in ("barony", "county"):
            key = e.get(kind)
            if key:
                bits.append("%s=%s" % (key, tbl.get(key) or ""))
        return ", ".join(bits)

    return name


def deep_dump(dedup, focus=None):
    """Targeted cache dig (a cache, never a melt): the raw location evidence per victim.

    `focus` = [folder, pid] limits the dig to one campaign, so the probe never has to open
    every 100–280 MB player cache of every family."""
    w("=" * 100)
    w("---- 5. 定点缓存取证（player_<pid>.json，非熔件）----")
    targets = {}
    for (folder, pid, cid), (path, k, prof, _v) in dedup.items():
        targets.setdefault((folder, pid), []).append((cid, k, path))
    for (folder, pid), victims in sorted(targets.items()):
        if focus and [str(folder), str(pid)] != [str(focus[0]), str(focus[1])]:
            continue
        cpath = os.path.join(ROOT, "output", folder, "data", "player_%s.json" % pid)
        if not os.path.isfile(cpath):
            w("  (缺缓存 %s)" % cpath)
            continue
        w("-" * 100)
        w("缓存 %s (%.1f MB)" % (os.path.relpath(cpath, ROOT),
                                 os.path.getsize(cpath) / 1048576.0))
        try:
            with open(cpath, encoding="utf-8") as fp:
                cache = json.load(fp)
        except Exception as e:
            w("  !! 缓存读取失败: %s" % e)
            continue
        prec = (cache.get("characters") or {}).get(str(pid)) or {}
        namer = _prov_namer()
        w("  player_id=%s player_name=%s last_date=%s"
          % (cache.get("player_id"), cache.get("player_name"), cache.get("last_date")))
        w("  capital_history=%s" % json.dumps(cache.get("capital_history") or [],
                                              ensure_ascii=False)[:600])
        w("  landed.realm_capital=%s"
          % ((prec.get("landed") or {}).get("realm_capital")))
        w("  player station track (last 4)=%s"
          % json.dumps((cache.get("player_locations") or [])[-4:], ensure_ascii=False))
        for cid, k, path in sorted(victims):
            rec = (cache.get("characters") or {}).get(str(cid)) or {}
            w("  · cid=%s %s (来自 %s)" % (cid, k.get("label") or k.get("name"),
                                           os.path.relpath(path, ROOT)))
            w("      快照里的 victim_place=%r" % (k.get("victim_place") or ""))
            for fld in ("birth", "death", "last_location", "first_location",
                        "landed", "dynasty_name", "house_name"):
                v = rec.get(fld)
                if fld == "death" and isinstance(v, dict):
                    v = dict(v)
                if fld == "landed" and isinstance(v, dict):
                    v = dict(v)
                    v.pop("domain", None)
                    v.pop("vassals", None)
                    v.pop("council", None)
                w("      %-16s %s" % (fld, json.dumps(v, ensure_ascii=False)[:300]))
            # decode every province id the record mentions → the barony/county Chinese name
            provs = []
            for holder, key in ((rec.get("death") or {}, "location_province"),
                                (rec.get("last_location") or {}, "province"),
                                (rec.get("first_location") or {}, "province")):
                if isinstance(holder.get(key), int):
                    provs.append((key, holder[key], (holder.get("date") or "")))
            for key, prov, date in provs:
                w("      省解码 %-18s prov=%-8s %s %s"
                  % (key, prov, date, namer(prov)))
            # which source `victim_place` took: the exec branch, the cached death record, or the
            # cross-campaign `last_location` (see facts.py:16548-16266)
            dd = rec.get("death") or {}
            ll = rec.get("last_location") or {}
            exec_ = (dd.get("killer") == int(pid)
                     and str(dd.get("reason") or "") in _PRISON_EXEC_REASONS)
            gap = _day_gap(ll.get("date"), dd.get("date"))
            w("      分支判定: reason=%s 处决集命中=%s killer==pid=%s → `_executed_by`=%s；"
              "②location_province=%s；③last_location=%s（距卒 %s 天）"
              % (dd.get("reason"), str(dd.get("reason") or "") in _PRISON_EXEC_REASONS,
                 dd.get("killer") == int(pid), exec_, dd.get("location_province"),
                 ll.get("date"), gap))
            w("      记录的封地/官衔字段: %s"
              % json.dumps({x: rec.get(x) for x in ("titles", "held_titles", "offices",
                                                    "primary_title") if x in rec},
                           ensure_ascii=False)[:300])
            w("      监狱史(末2)=%s" % json.dumps((rec.get("prison_history") or [])[-2:],
                                                 ensure_ascii=False)[:300])
            w("      记忆中的死亡相关: %s"
              % json.dumps([m for m in (rec.get("memories") or [])
                            if "death" in str(m.get("type")) or "kill" in str(m.get("type"))],
                           ensure_ascii=False)[:400])
    w()


def province_map_audit():
    """Section 5b: is `data/province_map.json` able to name every province of this save?

    `localization._parse_landed_titles` reads `province = N` lines of the game's
    landed_titles with the key regex `^\\s*([a-z0-9_]+)\\s*=\\s*\\{` (localization.py:559).
    AUH-era titles carry uppercase suffixes (b_Liao_Chaoyang / c_LIAO_chaoyang /
    b_FIC_Liao_Huopingan), which that class cannot match; this audit re-parses the same
    files with an uppercase-tolerant class and reports the gap. Game files only — no melt."""
    w("=" * 100)
    w("---- 5b. 省名表覆盖审计（游戏 landed_titles 全量 vs data/province_map.json）----")
    try:
        import glob as _glob
        import re as _re
        import llm
        import localization as L
        g = L.game_dir(llm.load_config())
        pm = L.province_map(llm.load_config())
        files = _glob.glob(os.path.join(g, "common", "landed_titles", "*.txt"))
    except Exception as e:
        w("  (审计不可用: %s)" % e)
        return
    anyk = _re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*\{")
    prov = _re.compile(r"^\s*province\s*=\s*(\d+)")
    tolerant = {}
    for f in files:
        stack = []
        try:
            fh = open(f, encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        with fh:
            for ln in fh:
                m = anyk.match(ln)
                if m:
                    k = m.group(1)
                    lv = (5 if k.startswith("e_") else
                          4 if k.startswith(("k_", "h_")) else
                          3 if k.startswith("d_") else
                          2 if k.startswith("c_") else
                          1 if k.startswith("b_") else 0)
                    stack.append((k, lv))
                    continue
                m2 = prov.match(ln)
                if m2 and stack:
                    p = int(m2.group(1))
                    b = c = ""
                    for k, _lv in reversed(stack):
                        if k.startswith("b_") and not b:
                            b = k
                        elif k.startswith("c_"):
                            c = k
                            break
                    tolerant.setdefault(p, {"barony": b, "county": c})
    missing = [p for p in tolerant if p not in pm]
    upper = [p for p, e in tolerant.items()
             if any(ch.isupper() for ch in (e["barony"] + e["county"]))]
    wrong = [p for p in tolerant if p in pm
             and (pm[p].get("barony") or "") != (tolerant[p]["barony"] or "")]
    w("  游戏 landed_titles 的 `province = N` 条数（大写键宽容解析）: %d" % len(tolerant))
    w("  data/province_map.json 条目数                        : %d" % len(pm))
    w("  完全查不到名字的省份                                 : %d" % len(missing))
    w("  键里含大写字母的省份                                 : %d" % len(upper))
    w("  名字被挂到错误男爵领的省份                           : %d" % len(wrong))
    for lo, hi, tag in ((0, 11000, "本体旧区 province<11000"),
                        (11000, 10 ** 9, "AUH 新增区 province>=11000")):
        tot = [p for p in tolerant if lo <= p < hi]
        mi = [p for p in missing if lo <= p < hi]
        wr = [p for p in wrong if lo <= p < hi]
        if tot:
            w("    %s: 共 %d，缺 %d (%.1f%%)，错 %d (%.1f%%)"
              % (tag, len(tot), len(mi), 100.0 * len(mi) / len(tot),
                 len(wr), 100.0 * len(wr) / len(tot)))
    try:
        import localization as L2
        tbl = L2.table()
    except Exception:
        tbl = {}
    w("  抽查（province → 宽容解析 → 现有 province_map）:")
    for p in (11728, 11759, 11765, 11773, 9521, 9763, 6177):
        tv = tolerant.get(p) or {}
        nm = tbl.get(tv.get("barony") or "") or tbl.get(tv.get("county") or "") or ""
        oval = pm.get(p) or {}
        onm = tbl.get(oval.get("barony") or "") or tbl.get(oval.get("county") or "") or ""
        w("    %-6s 宽容=%-18s/%-18s %-8s  现有表=%-18s %s"
          % (p, tv.get("barony") or "-", tv.get("county") or "-", nm,
             oval.get("barony") or "-", onm))
    w()


def report_tail():
    """Section 6: the actionable report (code trace, game semantics, candidate fixes).

    Kept inside the probe so `logs/v109/v109_victim_place.txt` regenerates as one self-contained
    artefact: evidence sections 0–5 plus this written report."""
    T = [
        "=" * 100,
        "---- 6. 调研报告：victim_place 的来源、正确性、候选修法 ----",
        "=" * 100,
        "",
        "### 6.1 字段来源（逐步，全部给 facts.py / cache_lib.py 行号）",
        "",
        "（行号对应本轮工作树：facts.py 在本轮被并发编辑过、整体下移约 124 行；"
        "后续再动 facts.py 时请按函数名定位，不要死记行号。另注意现树 facts.py:16560-16563 "
        "已把处决分支写成「解析出名字才 return」，空则继续往下走，与本报告的分析口径一致。）",
        "",
        "`Facts.victim_place(cid)` 定义在 facts.py:16548，按下列顺序取第一个能解析出的地名：",
        "",
        "① **处决分支**（facts.py:16560-16563）：`_executed_by(rec, player_id)` 为真时，"
        "回 `capital_place_at(death.date)`＝**主角当时的首都**。",
        "   `_executed_by`（facts.py:16451-16456）要求 `death.killer == player_id` 且 "
        "`death.reason ∈ _PRISON_EXEC_REASONS`（facts.py:19148-19151 = "
        "death_execution / death_punishment / death_imprisonment / death_dungeon / death_eradicated，"
        "即**司法处决**；谋杀类 reason 如 death_murder / death_mysterious 不在其中）。",
        "   `capital_place_at`（facts.py:16432-16448）→ `_capital_province_at`（facts.py:16398-16430）："
        "读 `cache[\"capital_history\"]`（每个档期锁存的 realm_capital，cache_lib.py:3450-3456）里"
        "**不晚于死亡日**的最后一点 → 头衔 key → `_prov_inv()` 反查省份；查不到时用 "
        "`_lt[title][\"capital\"]` 再查一次。",
        "② **死亡记录里的省份**（facts.py:16565-16566）：`cache[\"characters\"][cid][\"death\"]"
        "[\"location_province\"]`。",
        "   cache_lib.py:3479-3491：**第一次**看到该角色的 `dead_data` 时写 death 记录，并把 "
        "`location_province` 从 `rec[\"last_location\"][\"province\"]` 抄来。",
        "③ **跨战役缓存里最新的一条 last_location**（facts.py:16567-16583）：遍历 "
        "`self.campaign` 的各战役缓存，先取任何 int 型 `death.location_province`，否则取 "
        "`last_location` 日期最大者的 province。",
        "④ 三者皆无 → `''`，调用方省略地点行（facts.py:16584-16586）。",
        "",
        "`last_location` 是什么：cache_lib.py:3303-3311 —— 每次并入一档熔件时，若该角色该档 "
        "`alive_data.location`（角色**当档所在省份**，province id）是 int，就把它连同档期写进 "
        "`rec[\"last_location\"]`（`first_location` 只在首次出现时写）。缓存按档期**从早到晚**"
        "依次并入（pipeline.py:1067 逐档 `extract_snapshot`；cache_lib.py:2678-2682 的 "
        "`sources`/`last_date` 只前进），所以 `last_location` = **去世前最后一次「每年 1 月 1 日档」"
        "里该角色的所在省份**。",
        "",
        "然后是省名解析：`victim_place` 走 `_place_of_province`（facts.py:16588 起的出口）："
        "`barony_at_province`（facts.py:16359-16364）→ `title_base_name`；退而 `county_at_province`"
        "（facts.py:16352-16357）；再退 → ''。省份表 `provmap = L.province_map()`（facts.py:2007）"
        "把 province id → {b_/c_ key} 映到 `data/province_map.json`，该表由 localization.py:904-921 "
        "的 `load_province_map` 解析游戏 `common/landed_titles/*.txt` 的 `province = N` 行"
        "（localization.py:549-584）得来。",
        "",
        "结论一句话：**不是「死亡的战场」也不是「死者封地首府」，而是「死者去世前最后一次年度存档"
        "时所在的省份」**；只有司法处决（reason 在处决集里）才换成主角当时的首都。",
        "",
        "### 6.2 游戏侧语义（`game/` 本体，AUH 在本体里）",
        "",
        "* 存档**不保存死亡地点**。角色记录里唯一的位置字段是 `alive_data.location`"
        "（角色当前所在 province）；死亡只写 `dead_data`（date / reason / killer / liege / "
        "liege_title / named_title，见 cache_lib.py:3481-3488 抄出的字段清单）。",
        "* 反证：蔡偕 last_location 停在 **1144.1.1**，而他 1144.12.22 死；缓存最后一档是 "
        "1152.1.1（cache 的 last_date），中间 8 档都没能刷新 `last_location` → 死后各档确实"
        "没有 `alive_data.location`（cache_lib.py:3306 的 `isinstance(_prov, int)` 判据）。",
        "* 游戏只在**战死**时短暂留痕：`save_died_in_battle_variables_effect` 把战场省份写进"
        "角色变量 `battle_death_location`"
        "（game/common/scripted_effects/00_death_management_effects.txt:124-137）。",
        "  该变量在死亡管理事件里被**读走并删除**"
        "（game/events/death_events/death_management_events.txt:135-139），只拷贝给目击者的记忆"
        "变量 `battle_location`（同文件 :2377-2380）。本项目里谋杀/处决死者不是战死，且该变量"
        "用完即删，故**不可得**。",
        "* `location` 在脚本里是**省份作用域**：knight_phase_events 里 "
        "`location = { save_scope_as = battle_location }`、"
        "`LOCATION = scope:combat_side.combat.location`"
        "（game/common/combat_phase_events/00_knight_phase_events.txt:1227、:1241）。",
        "* 存档字段含义的权威是 CK3 Wiki《Modding》→ Save game editing → "
        "Contents of the gamestate file（https://ck3.paradoxwikis.com/Modding）：living 角色模板"
        "里 `alive_data` 含 `location`，dead 角色模板无任何地点字段。",
        "  ⚠ 该页把 location 注为「landed title index」（1.0 期注解）；本项目实测它是 "
        "**province id**：主角 207044 的 `player_locations` 最后一档 1152.1.1 = 6177，"
        "province 6177 解出 b_sakaka=**塞卡凯**/焦夫 —— 正是 prompts.log:5008 洪七公 1152 年"
        "战死之地；同一序列的 9258→强玛/那曲、2577→梵蒂冈/罗马也都成立（见 6.4 复算）。",
        "",
        "### 6.3 抽查结论（证据 = 本文件第 2/2b/3/5 节 + logs/prompts.log:2623-2639）",
        "",
        "1. 蔡偕（cid **16957928**）: `death.reason=death_mysterious`（**不在**处决集）→ "
        "处决分支不触发；`death.location_province = last_location.province = 9521 = "
        "b_guzang 武威 / c_liangzhou 凉州`，`last_location.date = 1144.1.1`，"
        "距卒 **356 天**。",
        "   ⇒ `logs/prompts.log:2625`「蔡偕死于武威」**不是省名错映，而是时间错位**：他看到的是"
        "1144 年元旦档时的所在省份。",
        "2. 他的封地线按时间倒序是「1144.6.1 任奉节蔡家族乡绅（并卸任夏路）← 1123-1144 夏经略使」"
        "（快照 facts.characters.16957928.titles_held），**死前半年才回到奉节**；年度档只到 "
        "1144.1.1，那次迁居没有任何档期覆盖 → 死亡地点**在熔件里不可得**。",
        "3. 同日同刑的三人地点不一致（第 3 节）：1146.12.8 三人同为 `death_execution`、"
        "killer 都是主角，却给出 玉河井 / 空 / 空 —— 说明地点是**逐人**从各自 `last_location` "
        "取的，不是处决现场；蔡偕这一类正是「孤例地名」那一档。",
        "   ⚠ 附加：这三人里的「玉河井」本身还是**错名**（见 6.4 E：他们 `last_location` 的"
        "11773/11765 实际是 b_Liao_Yizhou3 宜州与 b_Liao_Liaozhou **辽州**，被错挂到 "
        "b_cirlzj_yuhejing 玉河井）。也就是说同一篇《刺客列传》里同时存在两种错法："
        "蔡偕＝时间错位（地方对、时间不对），合答黑诸人＝省名错映。",
        "4. 统计（756 名去重死者，193 份快照）：空 29 / 与死者死亡时官职·封地一致 5 / "
        "生前曾领 0 / 与自身记录无关 722（其中 643 条是本战役内 ≥3 人共用的地名＝处决→主角首都"
        "那条设计路径，79 条是战役内**孤例**地名＝last_location 陈旧值，即蔡偕那一类）。"
        "这 29 个空里至少 2 个（洪氏2 pid=207044 的巴基兰/科比亚克）是 E 的解析缺口而非无数据；"
        "79 个孤例里有多少是 E 的错名，快照不带 province id、无法逐条判定，需落地时用熔件复核。",
        "",
        "### 6.4 候选修法（都不重熔、都不跑 rebuild-cache）",
        "",
        "**A（推荐主修）死亡时封地首府优先于 last_location**",
        "* 数据可及性：可。死亡时头衔由 `held_titles` / `_hold_intervals`（facts.py:4303、"
        "16184）＋熔件 `landed_titles` 现算，头衔首府在 `_lt[tid][\"capital\"]`"
        "（本项目 `snapshot.melt_tables.domain_capitals` 即此字段，取值为整数）。",
        "* 实现位置：facts.py `victim_place`（16244 处、②之前插一步）内的私有解析器；"
        "**不动 cache_lib.py**。",
        "* 关键坑：蔡偕死时的头衔是「世族庄园」＝**房产头衔**（`c_nf_*`/`x_nf_*`，"
        "game/common/landed_titles/04_china_noble_families.txt:6-21 的 `landless = yes` + "
        "`noble_family = yes` + `capital = c_<county>`）。`_primary_landed_at`（facts.py:16486-16517）"
        "与 `_eff_rank`（facts.py:3917-3931）**故意跳过**这类头衔，因此新解析器必须显式允许"
        "estate 头衔，再沿 `capital` 取省份（奉节 = province 9763 → b_fengjie 奉节，已复算）。",
        "  ⚠ 未决点：`_lt[tid][\"capital\"]` 在**存档**里存的是 title id 还是 province id，"
        "本轮只从快照看到它是整数（12723 / 12741 / 12745 / 15686），且这些值**不在** "
        "data/province_map.json 里；`_capital_province_at`（facts.py:16424-16429）按 title id 处理。"
        "落地方案时应整载一次熔件确认（父代理手上已有该档）。",
        "* 能修好：蔡偕 → **奉节**（他的乡绅庄园所在）；蓝师颜 → **黑城**（其家族所在，"
        "现在被写成韩南岛昌化/儋州）。",
        "* 修不好：无地死者（本战役 10 名死者里 6 名地点为空，其中 2 名的空是 E 的解析缺口，见下）、"
        "死在任所之外的人（处决于首都、旅途中被杀、在狱中死于他人领地）——那时封地首府是"
        "**另一个**猜测，不比 last_location 更真。",
        "* 代价：只改 facts.py；不需要 `tools/rebuild_folder.py`（头衔区间已在缓存里），"
        "不需要重熔。",
        "",
        "**B（推荐配套）处决分支修准 + 陈旧度闸门**",
        "* B1：把 `_capital_province_at`（facts.py:16398-16430）修准 —— 主角首都解析失败时"
        "现在会**静默回落到 last_location**（本战役 1146.12.8 三人同为 `death_execution`、"
        "killer 都是主角，结果却是 玉河井/空/空，说明 `capital_place_at` 三人全回空、"
        "地点改由各自 `last_location` 决定）；可加兜底：用主角自己的 "
        "`cache[\"player_locations\"]`（同档期站位轨，cache_lib.py:3443-3449）取不晚于死亡日的"
        "最后一点，或直接沿用 B1 的省份反查。",
        "* B2：给 ②/③ 一个时间闸门 —— `last_location.date` 已随省份一起锁存"
        "（cache_lib.py:3311），直接算 `deaths.date - last_location.date`，超过阈值"
        "（如 60 天）就**不出地点**而不是出一个陈旧地名（蔡偕的差距 = 356 天）。",
        "* 能修好：蔡偕这类 79 条「孤例」不再写成错地点（改为省略）。",
        "* 修不好：它只是**删**而不是**改**；处决者的首都若本身也判错（B1 未修时）仍会错。",
        "* 代价：只改 facts.py；`last_location.date` 已在缓存里 → 无需重建缓存、无需重熔。",
        "",
        "**C（保守/措辞方案）把「死于X」降级为「最后见于X」或在无把握时省句**",
        "* 数据可及性：可，零新数据。",
        "* 实现位置：facts.py `_death_sentence_body`（17837 起，内部 17867/17882 调 "
        "`victim_place`）/ facts.py:24418-24420，"
        "以及 biography.py:1100-1104 的独立地点行。",
        "* 能修好：所有地点句都变成**永远为真**的表述（「最后见于武威」）。",
        "* 修不好：用户要的「死于某地」仍然写不出；只是不再说错。",
        "* 代价：改 facts.py/biography.py 的措辞；需重落快照核对，不重熔。",
        "",
        "**D 不可得声明**：真正的「死亡地点」**在现有熔件与缓存里都不存在**"
        "（6.2 已证明存档无该字段）。因此上一轮方案文档 §4.6 里「改用死者在世时最后一条有地点的"
        "记录」**不是修法**——那正是当前行为，正是它给出武威。",
        "",
        "**E（同轮必看：它既造成空地名，也造成错地名）省名表解析器丢大写键、并因此串栈**",
        "* 证据（第 5b 节自动复算）：游戏 `common/landed_titles/*.txt` 里共 **11297** 条 "
        "`province = N`，而 `data/province_map.json` 只有 **10406** 条 → **891 个省份根本"
        "查不到名字**；另有 **150** 个省份被挂到**错误的男爵领**。",
        "* 根因是 localization.py:559 的键正则 `^\\s*([a-z0-9_]+)\\s*=\\s*\\{` **只认小写**，"
        "而 AUH 与部分本体头衔的键带大写字段：`b_Liao_Chaoyang`、`c_LIAO_jinzhou`、"
        "`b_FIC_Liao_Huopingan`、`b_olbia_ETEL`、`b_zarand_PER` …",
        "* **不只是「丢一条」**：这类键**压不进栈**（localization.py:559-574），但它的闭合 `}` "
        "照样在 localization.py:587-590 把栈弹掉一层 —— 于是从该处起整个栈错位，"
        "**邻近的小写男爵领替它背了省份**。可复算的实证（都在 "
        "game/common/landed_titles/00_landed_titles.txt）：",
        "  · 74796-74797 `b_Liao_Liping` 的 `province = 11760`、74791 `b_cirlzj_yuhejing` 的 "
        "`province = 12424`；74815-74816 `b_Liao_Yizhou3` 的 `province = 11773`；"
        "74812 `c_LIAO_jinzhou` 与其后 74820-74821 `b_Liao_Xizhou` 的 `province = 11776`。",
        "  · 项目解析器（`L._parse_landed_titles`）对 11760/11765/11773/11776 **全部**给出 "
        "`b_cirlzj_yuhejing 玉河井`；`province = 11765` 的真正归属是 "
        "`b_Liao_Liaozhou`＝**辽州**（即主角 1147 年直辖四地之一），"
        "11773 的真正归属是 `b_Liao_Yizhou3`＝**宜州**。",
        "  · 反过来 `province = 11759`（朝阳）与 `province = 11728`（火平安/龙化州）"
        "在该处栈里没有 b_ 可挂，**整条丢掉** → 查名字得空串。",
        "* 对本案的影响（同一篇《刺客列传》）：`logs/prompts.log:2632`「孛坚完泽台死于**玉河井**」"
        "应为**辽州**或**宜州**一带（11773）；合阿台（11765）同理；洪氏2 pid=207044 的两名死者"
        "（巴基兰 cid=50526243、科比亚克 cid=218715）`last_location.province = 11728` 明明有值"
        "却解析为空——他们的「地点为空」不是没有数据，而是**解析不到名字**；"
        "主角自己的首都省份 11759（朝阳）同样缺席，这正是 B1 里处决分支回空的一条直接原因。",
        "  ⚠ 蔡偕的武威**不在此列**：9521 在现有表与宽容解析下都是 b_guzang 武威（第 5b 节抽查），"
        "所以那一例确实是时间错位而非错映。",
        "* 实现位置：localization.py:559 的正则放宽为 `[A-Za-z0-9_]+`（**同一正则还复制在 "
        "localization.py:645** 的 `build_short_titles`／definite_form 表里，虽不影响地名也"
        "应当一并改掉；并确认 587-590 的弹栈与单行 `color = { … }` 仍然配平），"
        "然后**重建** `data/province_map.json`"
        "（`load_province_map(force=True)` 或删表重跑；注意该表**没有**指纹自检，"
        "localization.py:2802-2809 的 `_SOURCE_TABLES` 里没有它，所以不会自动失效重建）。",
        "* 代价：不重熔、不重建缓存、秒级建表；但**影响面＝全部地名**（凡引用省份→地名的行都"
        "可能改字），落地前必须用快照/成稿做一次全量对照（见 6.5 第 5 条），宜单独一个提交。",
        "",
        "推荐：**A + B2（B1 作为同一提交的附带修正）**，C 作为兜底措辞备选，"
        "E 作为独立小提交（它同时减少「地点为空」与「地点错名」两类）。",
        "",
        "### 6.5 下一轮如何验证",
        "",
        "1. 复用已有快照（**不要**再整载熔件）：`output/洪氏2/data/snap_207044_final.json`"
        "（父代理 2026-10-06 22:19 落）与本轮 `output/洪氏2/data/snap_v109_207044_1147.json`"
        "（复现 prompts.log:2625 的那一篇，`killed` 4 人、蔡偕 victim_place=武威 逐字一致）。",
        "2. 改后重跑本探针：`& tools\\py.ps1 tools\\tests\\v109_probe_victim_place.py "
        "--deep-focus 洪氏2 207044`，看第 2b 节「洪氏2 pid=207044」的「孤例」由 4 → 0"
        "（或地点改为空），且第 5 节 蔡偕的 `victim_place` 由 武威 变为 奉节；"
        "修 E 后，第 5 节 巴基兰/科比亚克 的空地点应变为 火平安（11728 可解析）。",
        "3. 事实面逐字节对照：`& tools\\py.ps1 tools\\tests\\snap_facts_diff.py <旧快照> <新快照> "
        "--facts-only`（仓库里若无此名，按 docs/方案_v109 §3.2 的既有口径用现有 diff 工具），"
        "确认只有预期的 `killed[].victim_place` 与含地点的死句变了。",
        "4. 新增秒级断言（`tools/tests/verify_v109.py` [D] 组）：对 "
        "`snap_207044_final.json` 断言 蔡偕条目的 `victim_place` ∈ {'奉节',''}，"
        "且语料里**不出现**「死于武威」；对 `snap_v109_207044_1147.json` 断言同上；"
        "对 田所 pid=59838 快照断言处决死者的地点仍等于其首都名（不得回归）。",
        "5. 省名解析回归（本轮已复算，可写成断言）：province 6177 → 塞卡凯、9258 → 强玛、"
        "2577 → 罗马、9521 → 武威、9763 → 奉节 —— 这五条在修 E 前后都应不变（既有行为基线）；"
        "11728 → 火平安、11759 → 朝阳 在修 E **前**应为空、修 E 后应成立；"
        "11765 → **辽州**、11773 → **宜州** 在修 E **前**是「玉河井」（错名）、修 E 后应改字 —— "
        "这四条正是 E 的判据。",
        "",
    ]
    LINES.extend(T)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", action="store_true",
                    help="also open the player cache for a targeted location dump")
    ap.add_argument("--deep-focus", nargs=2, metavar=("FOLDER", "PID"), default=None,
                    help="only dig this one campaign's cache, e.g. --deep-focus 洪氏2 207044")
    args = ap.parse_args()
    n = probe_snapshots(args)
    province_map_audit()
    report_tail()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write("\n".join(LINES) + "\n")
    print("\n已写入 %s (%d 行, %d 份快照)" % (OUT, len(LINES), n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
