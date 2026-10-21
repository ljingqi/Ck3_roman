# -*- coding: utf-8 -*-
"""v117 取证探针：洪希晏（cid=50565938）1205 年夺取彼刻拉里亚系的头衔，在熔件
landed_titles.history 里的 type 到底是什么？「圣战」信息在存档里存在哪？

只读，不改任何生产代码。输出同时写 logs/v117/v117_probe_holywar.txt（UTF-8）。

阶段：
  S1  段级读熔件 landed_titles（不整载 470MB），打印 1205-01-10 当天全部事件，
      以及 cid=50565938 全部头衔的 date/holder/type
  S2  标题字段（key / tier / de_facto_liege / 完整 history 片段）
  S3  段级读熔件 wars，找与该角色/这些头衔相关的战争，打印 casus_belli.type 等
  S4  读熔件内存档 sidecar（melt_*_idx.json.gz），打印该角色 ascended_throne_memory
      的 reason（与 hist type 互为佐证）
  S5  段级读缓存 war_history（player_50565938 / player_17066495），打印相关行

用法：& tools\py.ps1 tools\tests\v117_probe_holywar.py
"""
import os
import sys
import json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import cache_lib as cl  # noqa: E402

FOLDER = "洪氏2"
DATA = os.path.join(ROOT, "output", FOLDER, "data")
OUT = os.path.join(ROOT, "logs", "v117_probe_holywar.txt")

CID = 50565938                    # 屠夫洪希晏
PID_CAMPAIGN = 17066495           # 洪氏2 现役玩家（洪光通）
COMTAS = None                     # 科米塔斯·设拉子-法尔斯，稍后从数据里找
DAY = "1205.1.10"
KNOWN_TIDS = []                   # 由 S1 收集

MELT_NAMES = ["melt_1283_01_01.json"]

_lines = []


def P(*a):
    s = " ".join(str(x) for x in a)
    _lines.append(s)
    print(s, flush=True)


def melt_path(name):
    for cand in (name, name + ".xz", name + ".gz"):
        p = os.path.join(DATA, cand)
        if os.path.isfile(p):
            return p
    return None


def ev_list(ev):
    return ev if isinstance(ev, list) else [ev]


def norm(ev):
    """history 条目 -> (holder, type)"""
    if isinstance(ev, dict):
        return ev.get("holder"), (ev.get("type") or "")
    return ev, ""


def s1_s2(melt_name):
    p = melt_path(melt_name)
    if not p:
        P(f"[S1] 缺熔件 {melt_name}")
        return None, None
    P(f"\n===== [S1] 熔件 {os.path.basename(p)} ({os.path.getsize(p)/1048576:.0f} MB) =====")
    lt = cl.load_melt_landed_titles(p)
    P(f"[S1] landed_titles 条数 = {len(lt)}")

    # -- 1a 全库 type 分布（见证 conquest_holy_war 这个取值是否真的存在于本存档）
    from collections import Counter
    allt = Counter()
    for tid, t in lt.items():
        if not isinstance(t, dict):
            continue
        for d, ev in (t.get("history") or {}).items():
            for e in ev_list(ev):
                _h, _ty = norm(e)
                allt[_ty or "<无type>"] += 1
    P("[S1] 全库 history.type 取值分布（前 30）：")
    for k, v in allt.most_common(30):
        P(f"        type={k!r:32} count={v}")

    # -- 1b 1205-01-10 当天，全库所有事件
    P(f"\n[S1] === 全库在 {DAY} 的全部 history 事件 ===")
    for tid in sorted(lt, key=lambda x: int(x)):
        t = lt[tid]
        if not isinstance(t, dict):
            continue
        hist = t.get("history") or {}
        if not isinstance(hist, dict):
            continue
        for d in sorted(hist, key=cl.date_key):
            if d != DAY:
                continue
            for e in ev_list(hist[d]):
                h, ty = norm(e)
                P(f"        tid={tid:>8} key={t.get('key')!r:28} name={t.get('name')!r:20} "
                  f"date={d} holder={h} type={ty!r}")

    # -- 1c cid=50565938 出现的所有头衔 + 完整事件序列
    P(f"\n[S1] === cid={CID} 出现在 history 里的全部头衔 ===")
    tids = []
    for tid in sorted(lt, key=lambda x: int(x)):
        t = lt[tid]
        if not isinstance(t, dict):
            continue
        hist = t.get("history") or {}
        if not isinstance(hist, dict) or not hist:
            continue
        hit = False
        for d, ev in hist.items():
            for e in ev_list(ev):
                h, _ty = norm(e)
                if h == CID:
                    hit = True
                    break
            if hit:
                break
        if hit:
            tids.append(tid)
    P(f"[S1] 共 {len(tids)} 个头衔： {tids}")
    for tid in tids:
        t = lt[tid]
        P(f"\n  --- tid={tid} key={t.get('key')!r} name={t.get('name')!r} "
          f"tier={(t.get('key') or '')[:2]!r} de_facto_liege={t.get('de_facto_liege')!r} ---")
        hist = t.get("history") or {}
        for d in sorted(hist, key=cl.date_key):
            for e in ev_list(hist[d]):
                h, ty = norm(e)
                mark = "  <== 洪希晏" if h == CID else ""
                P(f"        date={d:12} holder={str(h):>10} type={ty!r}{mark}")

    # -- 1d 洪希晏拿到的每一段的取得 type（决定性证据）
    P(f"\n[S1] === 洪希晏各次取得头衔的 type（date/holder/type/key）===")
    for tid in tids:
        t = lt[tid]
        hist = t.get("history") or {}
        for d in sorted(hist, key=cl.date_key):
            for e in ev_list(hist[d]):
                h, ty = norm(e)
                if h == CID:
                    P(f"        {d}  holder={h}  type={ty!r}  key={t.get('key')!r}  name={t.get('name')!r}")

    # -- S2 标题原始字段
    P(f"\n===== [S2] 相关头衔原始字段（截断 3000 字）=====")
    for tid in tids:
        P(f"--- tid={tid} ---")
        P(json.dumps(lt[tid], ensure_ascii=False)[:3000])
    return p, lt, tids


def s3_wars(melt_name, tids):
    p = melt_path(melt_name)
    if not p:
        return
    P(f"\n===== [S3] 段级读 {os.path.basename(p)} 的 wars =====")
    wars = cl.load_melt_section(p, "wars")
    if not isinstance(wars, dict):
        P(f"[S3] wars 段为空/非 dict： {type(wars)}")
        return
    P(f"[S3] wars 顶层键： {sorted(wars.keys())}")
    for k, v in wars.items():
        if isinstance(v, dict):
            P(f"        wars[{k!r}] = dict, {len(v)} 项")
        elif isinstance(v, list):
            P(f"        wars[{k!r}] = list, {len(v)} 项")
        else:
            P(f"        wars[{k!r}] = {type(v)} {str(v)[:80]!r}")
    aw = wars.get("active_wars") or {}
    if isinstance(aw, list):
        aw = {str(i): w for i, w in enumerate(aw)}
    P(f"[S3] active_wars 条数 = {len(aw)}")
    tset = set(str(x) for x in tids)
    for wid, w in aw.items():
        if not isinstance(w, dict):
            continue
        cb = w.get("casus_belli") if isinstance(w.get("casus_belli"), dict) else {}
        blob = json.dumps(w, ensure_ascii=False)
        if str(CID) not in blob and not (tset & set(str(x) for x in (cb.get("targeted_titles") or []))):
            continue
        P(f"\n  --- war {wid} ---")
        P(f"      start_date = {w.get('start_date')!r}")
        P(f"      name       = {w.get('name')!r}")
        P(f"      cb.type    = {cb.get('type')!r}")
        P(f"      cb.attacker= {cb.get('attacker')!r}  cb.defender={cb.get('defender')!r} "
          f"cb.claimant={cb.get('claimant')!r}")
        P(f"      cb.targeted_titles = {cb.get('targeted_titles')!r}")
        P(f"      cb 全字段 = {json.dumps(cb, ensure_ascii=False)[:1200]}")
        P(f"      attacker 侧 = {json.dumps(w.get('attacker'), ensure_ascii=False)[:600]}")
        P(f"      defender 侧 = {json.dumps(w.get('defender'), ensure_ascii=False)[:600]}")


def s4_memories(melt_name, tids):
    p = melt_path(melt_name)
    if not p:
        return
    P(f"\n===== [S4] 内存档 sidecar {os.path.basename(p)} 的 {CID} 记忆 =====")
    idx = cl.load_melt_index(p)
    if not isinstance(idx, dict):
        P("[S4] sidecar 缺失/损坏")
        return
    P(f"[S4] sidecar date={idx.get('date')!r} chars={len(idx.get('chars') or {})} db={len(idx.get('db') or {})}")
    ids = (idx.get("chars") or {}).get(str(CID)) or []
    P(f"[S4] chars[{CID}] 记忆 id 数 = {len(ids)}")
    db = idx.get("db") or {}
    tset = set(int(x) for x in tids)
    for mid in ids:
        e = db.get(str(mid)) or {}
        if e.get("type") not in ("ascended_throne_memory", "lost_title_memory"):
            continue
        reason, landed = "", None
        for v in (e.get("vars") or []):
            if not isinstance(v, (list, tuple)):
                continue
            if v and v[0] == "reason" and not reason:
                reason = str(v[3] if len(v) > 3 else "")
            elif v and v[0] == "landed_title" and len(v) > 2 and v[2] is not None:
                try:
                    landed = int(v[2])
                except (TypeError, ValueError):
                    landed = None
        if landed is not None and landed in tset:
            P(f"        mid={mid} type={e.get('type')!r} date={e.get('creation_date')!r} "
              f"landed_title={landed} reason={reason!r}")
    # 兜底：所有 ascended_throne_memory 的 reason 分布
    from collections import Counter
    c = Counter()
    for mid in ids:
        e = db.get(str(mid)) or {}
        if e.get("type") in ("ascended_throne_memory", "lost_title_memory"):
            r = ""
            for v in (e.get("vars") or []):
                if isinstance(v, (list, tuple)) and v and v[0] == "reason":
                    r = str(v[3] if len(v) > 3 else "")
            c[(e.get("type"), r)] += 1
    P(f"[S4] 该角色 ascended/lost 记忆 (type, reason) 分布： {dict(c)}")


def s5_cache():
    for fn in (f"player_{CID}.json", f"player_{PID_CAMPAIGN}.json"):
        p = os.path.join(DATA, fn)
        if not os.path.isfile(p):
            P(f"\n[S5] 缺缓存 {fn}")
            continue
        P(f"\n===== [S5] 缓存 {fn} ({os.path.getsize(p)/1048576:.0f} MB) 的 war_history =====")
        try:
            wh = load_top_key(p, "war_history")
        except Exception as exc:
            P(f"[S5] 段级读失败： {exc!r}")
            continue
        if not isinstance(wh, list):
            P(f"[S5] war_history 非 list： {type(wh)}")
            continue
        P(f"[S5] war_history 条数 = {len(wh)}")
        for row in wh:
            if not isinstance(row, dict):
                continue
            parts = (row.get("atk_parts") or []) + (row.get("dfd_parts") or [])
            if CID not in parts and CID not in (row.get("attacker"), row.get("defender")):
                continue
            P(f"        id={row.get('id')} seen={row.get('seen')} start={row.get('start_date')} "
              f"cb={row.get('cb')!r} atk={row.get('attacker')} dfd={row.get('defender')} "
              f"claimant={row.get('claimant')} titles={row.get('titles')} name={row.get('name')!r}")
        # 也打印 1205 年前后的所有行，看这个战役缓存里最早/最晚有什么
        dates = sorted((str(r.get("start_date") or "") for r in wh if isinstance(r, dict)))
        P(f"[S5] war_history start_date 范围： {dates[0] if dates else None} .. {dates[-1] if dates else None}")


def load_top_key(path, key):
    """同 cl.load_melt_section，但允许顶层值是数组（war_history 是 list，不是 dict）。"""
    pat = ('"%s":' % key).encode("utf-8")
    buf = b""
    eof = False
    with cl._melt_binary(path) as fp:

        def _fill():
            nonlocal buf, eof
            chunk = fp.read(1 << 20)
            if not chunk:
                eof = True
                return False
            buf += chunk
            return True

        pos = 0
        while True:
            i = buf.find(pat, pos)
            if i < 0:
                if _fill():
                    continue
                return None
            j = i + len(pat)
            while True:
                k = j
                while k < len(buf) and buf[k:k + 1] in (b" ", b"\r", b"\n", b"\t"):
                    k += 1
                if k < len(buf):
                    break
                if not _fill():
                    return None
            c = buf[k:k + 1]
            if c not in (b"{", b"["):
                pos = i + 1
                continue
            open_c, close_c = c, (b"}" if c == b"{" else b"]")
            start, depth, i2 = k, 0, k
            while True:
                while i2 >= len(buf):
                    if not _fill():
                        return None
                ch = buf[i2:i2 + 1]
                if ch == b'"':
                    i2 += 1
                    while True:
                        while i2 >= len(buf):
                            if not _fill():
                                return None
                        cc = buf[i2:i2 + 1]
                        if cc == b"\\":
                            i2 += 2
                            continue
                        if cc == b'"':
                            i2 += 1
                            break
                        i2 += 1
                    continue
                if ch == open_c:
                    depth += 1
                elif ch == close_c:
                    depth -= 1
                    if depth == 0:
                        i2 += 1
                        break
                i2 += 1
            return json.loads(buf[start:i2], object_pairs_hook=cl._merge_dup_pairs)


def s3b_wars2(melt_name):
    p = melt_path(melt_name)
    wars = cl.load_melt_section(p, "wars")
    aw = (wars or {}).get("active_wars") or {}
    P(f"\n===== [S3b] active_wars 健在性核查（{os.path.basename(p)}）=====")
    P(f"[S3b] active_wars 条数 = {len(aw)}")
    rows = []
    for wid, w in aw.items():
        if isinstance(w, dict):
            rows.append((str(w.get("start_date")), wid, str(((w.get("casus_belli") or {}).get("type")))))
    rows.sort(key=lambda x: cl.date_key(x[0]))
    P(f"[S3b] start_date 范围： {rows[0][0] if rows else None} .. {rows[-1][0] if rows else None}")
    P(f"[S3b] start_date < 1220 的战争： {[r for r in rows if cl.date_key(r[0]) < cl.date_key('1220.1.1')]}")
    P(f"[S3b] 全部 war start_date 与 cb（前 40）：")
    for r in rows[:40]:
        P(f"        {r[0]}  id={r[1]}  cb={r[2]!r}")
    names = (wars or {}).get("names") or {}
    P(f"[S3b] wars.names（{len(names)} 条，仅战争名注册表，无 CB）： "
      f"{json.dumps(names, ensure_ascii=False)[:800]}")


def main():
    only = ""
    append = False
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            only = a.split("=", 1)[1]
        elif a == "--append":
            append = True
    if append and os.path.isfile(OUT):
        with open(OUT, encoding="utf-8") as fp:
            _lines.extend(fp.read().rstrip("\n").split("\n"))
    if only in ("wars2", "s5"):
        if only == "wars2":
            s3b_wars2(MELT_NAMES[0])
        else:
            s5_cache()
        with open(OUT, "w", encoding="utf-8") as fp:
            fp.write("\n".join(_lines) + "\n")
        print(f"\n[out] {OUT}")
        return
    keep = {}
    for mn in MELT_NAMES:
        r = s1_s2(mn)
        if r and r[1] is not None:
            keep[mn] = r
    if not keep:
        P("[!] 没有可用熔件")
    else:
        mn, (_p, _lt, tids) = sorted(keep.items())[0]
        s3_wars(mn, tids)
        s4_memories(mn, tids)
    s5_cache()

    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write("\n".join(_lines) + "\n")
    print(f"\n[out] {OUT}")


if __name__ == "__main__":
    main()
