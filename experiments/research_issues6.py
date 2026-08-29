# -*- coding: utf-8 -*-
"""研究第六波: 青徐王子溯源, 语言中文值, 文化存储, 富兰克林历任(title history), 刺客块大小。"""
import json
import sys
import re

sys.path.insert(0, r"D:\Roman")
import localization as L
import llm

MELT931 = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"
MELT882 = r"D:\Roman\output\菲利普3\data\melt_882_01_01.json"
PROMPTS = r"D:\Roman\logs\prompts.log"
CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"

def load(path):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)

def all_chars(melt):
    out = {}
    for sec in ("living", "dead_unprunable", "dead_prunable"):
        for cid, c in (melt.get(sec) or {}).items():
            if isinstance(c, dict):
                out.setdefault(cid, c)
    return out

def main():
    m931 = load(MELT931)
    m882 = load(MELT882)
    cache = load(CACHE)
    table = L.table()
    chars931 = all_chars(m931)

    # ---- A) 青徐王子 原文搜索 ----
    print("== A) 青徐王子 溯源 ==")
    with open(MELT931, "r", encoding="utf-8") as fp:
        raw = fp.read(128 * 1024 * 1024)
    idx = raw.find("青徐王子")
    print("   melt931 含'青徐王子':", idx >= 0)
    if idx >= 0:
        print("   上下文:", raw[idx - 100:idx + 100])
    # 孙子 nickname_text
    g = chars931.get("16836221") or {}
    print("   孙子 nickname_text:", g.get("nickname_text"))
    # 孙子 heir 字段
    ad = g.get("alive_data") or {}
    print("   孙子 heir:", ad.get("heir"), "| pretender:", ad.get("pretender"))
    # 富兰克林 nickname
    f = chars931.get("16820097") or {}
    print("   富兰克林 nickname_text:", f.get("nickname_text"))
    # 找 16836221 的 court_position / title display: 看是否有 "title" 类字段
    print("   孙子 顶层键:", list(g.keys()))
    ld = g.get("landed_data") or {}
    print("   孙子 landed_data:", {k: ld.get(k) for k in ("domain", "government", "realm_capital", "primary_title") if k in ld})

    # ---- B) 语言中文 ----
    print("\n== B) language_* 中文值 ==")
    for k in ("language_norse", "language_arabic", "language_sayhadic",
              "language_japonic", "language_anglic", "language_chinese",
              "language_han", "language_old_norse"):
        print("   ", k, "=", L.loc(table, k) or "(无)")

    # ---- C) 文化存储方式 ----
    print("\n== C) 文化存储 (melt931 顶层角色字段) ==")
    for cid in ("38725", "16836221", "16820097"):
        c = chars931.get(cid) or {}
        print("   ", cid, "ethnicity:", c.get("ethnicity"))
    # 玩家在缓存中的 culture
    prec = (cache.get("characters") or {}).get("38725") or {}
    print("   玩家缓存 culture:", prec.get("culture"))
    # culture_manager 里 norse 文化条目
    cm = (m931.get("culture_manager") or {}).get("cultures") or {}
    print("   culture_manager 条目数:", len(cm))
    for cid, e in cm.items():
        if isinstance(e, dict) and (e.get("culture_template") or "") in ("norse", "han", "arabic"):
            print("   ", cid, e.get("culture_template"), "| name_order:", e.get("name_order_convention"))

    # ---- D) 富兰克林 title history ----
    print("\n== D) 富兰克林 16820097 在 title.history 中的任职 ==")
    lt931 = (m931.get("landed_titles") or {}).get("landed_titles") or {}
    rows = []
    for tid, t in lt931.items():
        if not isinstance(t, dict):
            continue
        hist = t.get("history") or {}
        if not isinstance(hist, dict):
            continue
        for d, ev in hist.items():
            h = ev.get("holder") if isinstance(ev, dict) else ev
            if h == 16820097:
                key = t.get("key") or ""
                tnd = t.get("title_name_data") or {}
                nm = (tnd.get("custom") or "").strip() or (tnd.get("name") or "").strip()
                if not nm:
                    nm = L.loc(table, key)
                rows.append((d, tid, key, nm,
                             ev.get("type") if isinstance(ev, dict) else ""))
    rows.sort(key=lambda x: x[0])
    print("   记录数:", len(rows))
    for r in rows[:30]:
        print("   ", r)

    # ---- E) 埃斯泰因 称号: 验证 prince_title 对无头衔(死)角色的行为 ----
    print("\n== E) 埃斯泰因(死) 在 931 的 landed:",
          (chars931.get("16830252") or {}).get("landed_data") if "16830252" in chars931 else "?")
    # 找埃斯泰因
    for cid, c in chars931.items():
        if c.get("first_name") == "埃斯泰因":
            print("   埃斯泰因:", cid, "| dead:", bool(c.get("dead_data")),
                  "| landed:", (c.get("landed_data") or {}).get("domain"))
            break

    # ---- F) 刺客列传 prompt 块 (完整统计) ----
    print("\n== F) prompts.log 刀下诸魂 块统计 (最后一次出现) ==")
    with open(PROMPTS, "r", encoding="utf-8") as fp:
        txt = fp.read()
    idxs = [m.start() for m in re.finditer(r"刀下诸魂\n", txt)]
    print("   出现次数:", len(idxs))
    if idxs:
        i = idxs[-1]
        block = txt[i:i + 6000]
        n_dead = len(re.findall(r"死者：", block))
        print("   块内死者数:", n_dead)
        lines = block.splitlines()
        print("   前 30 行:")
        for ln in lines[:30]:
            if ln.strip():
                print("     ", ln[:90])

    # ---- G) fmt_cn_date ----
    print("\n== G) llm.fmt_cn_date('931.6.7') =", llm.fmt_cn_date("931.6.7"))

if __name__ == "__main__":
    main()
