# -*- coding: utf-8 -*-
"""研究第九波: 非玩家角色 title history 覆盖度 + 范德林帮 as-of + 汝阴路/曹等头衔。"""
import json
import sys
import re

sys.path.insert(0, r"D:\Roman")
import localization as L
import cache_lib as cl

CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"
MELT931 = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"
MELT915 = r"D:\Roman\output\菲利普3\data\melt_915_01_01.json"

def load(path):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)

def main():
    cache = load(CACHE)
    m931 = load(MELT931)
    lt931 = (m931.get("landed_titles") or {}).get("landed_titles") or {}
    table = L.table()

    # ---- 1) 延嗣/文举/觉 在 title history 中的任何任职 ----
    print("== 1) 非玩家角色 title history 覆盖 ==")
    for cid, name in ((40880, "延嗣"), (16801893, "文举"), (15557, "觉"),
                      (16820097, "富兰克林"), (33599939, "卡托内")):
        hits = []
        for tid, t in lt931.items():
            if not isinstance(t, dict):
                continue
            hist = t.get("history") or {}
            if not isinstance(hist, dict):
                continue
            for d, ev in hist.items():
                h = ev.get("holder") if isinstance(ev, dict) else ev
                if h == cid:
                    key = t.get("key") or ""
                    hits.append((d, tid, key))
        print("   %s(%s): %d 条" % (name, cid, len(hits)))
        for h in hits[:6]:
            print("      ", h)

    # ---- 2) 汝阴路 / 相关王国头衔 ----
    print("\n== 2) 汝阴/曹/仁明 相关头衔 ==")
    for tid, t in lt931.items():
        if not isinstance(t, dict):
            continue
        key = t.get("key") or ""
        tnd = t.get("title_name_data") or {}
        nm = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
        if not nm:
            nm = L.loc(table, key)
        if "汝阴" in nm or "ruyin" in key.lower() or "曹" in nm or "仁明" in nm:
            hist = t.get("history") or {}
            seq = sorted(hist.items(), key=lambda x: cl.date_key(x[0])) if isinstance(hist, dict) else []
            print("   ", tid, key, nm, "| holder:", t.get("holder"), "| history条数:", len(seq))
            for d, ev in seq[-4:]:
                print("       ", d, ev)

    # ---- 3) 范德林帮 as-of: 含 x_ 营地 ----
    print("\n== 3) 玩家 as-of 含营地 (x_ 全部) ==")
    pid = cache.get("player_id")
    for date in ("882.1.1", "892.1.1", "898.1.1", "902.1.1"):
        held = []
        for tid, t in lt931.items():
            if not isinstance(t, dict):
                continue
            hist = t.get("history") or {}
            if not isinstance(hist, dict):
                continue
            holder_now = None
            for d, ev in sorted(hist.items(), key=lambda x: cl.date_key(x[0])):
                if cl.date_key(d) > cl.date_key(date):
                    break
                holder_now = ev.get("holder") if isinstance(ev, dict) else ev
            if holder_now == pid:
                key = t.get("key") or ""
                pfx = key[:2]
                if pfx in ("h_", "e_", "k_", "d_") or pfx == "x_":
                    tnd = t.get("title_name_data") or {}
                    nm = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
                    if not nm:
                        nm = L.loc(table, key)
                    held.append((key, nm))
        print("   %s: %s" % (date, held))

    # ---- 4) 现任/历史: 冯·大马士革 对照玩家缓存里其他家族? 不需要 ----
    # ---- 5) 攻陷: 玩家 168 击杀里 lowborn 且有记忆者 (低出身但可写) ----
    print("\n== 4) lowborn 击杀中有记忆者 ==")
    kills = set((cache.get("characters") or {}).get(str(pid), {}).get("kills") or [])
    pd = cache.get("player_death") or {}
    kills |= set(pd.get("kills") or [])
    chars = cache.get("characters") or {}
    for cid in sorted(kills):
        rec = chars.get(str(cid)) or {}
        if not rec.get("house_name") and rec.get("memories"):
            print("   ", cid, rec.get("name_zh"), "| mems:", len(rec.get("memories") or []))

if __name__ == "__main__":
    main()
