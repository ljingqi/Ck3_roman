# -*- coding: utf-8 -*-
"""研究第八波: ①主要头衔历任(仅 d_+/营地, 含任/失, 按日期命名) ②各时期头衔(as-of)
③刺客列传 3 分块切点 ④提示词体积实测。只读。"""
import json
import sys
import re
from collections import Counter

sys.path.insert(0, r"D:\Roman")
import localization as L
import llm
import cache_lib as cl

CACHE = r"D:\Roman\output\菲利普3\data\player_38725.json"
MELT931 = r"D:\Roman\output\菲利普3\data\melt_931_01_01.json"
PROMPTS = r"D:\Roman\logs\prompts.log"

def load(path):
    with open(path, "r", encoding="utf-8") as fp:
        return json.load(fp)

TIER_RANK = {"h_": 6, "e_": 5, "k_": 4, "d_": 3, "c_": 2, "b_": 1, "x_": 0}

def main():
    cache = load(CACHE)
    m931 = load(MELT931)
    lt931 = (m931.get("landed_titles") or {}).get("landed_titles") or {}
    table = L.table()
    pid = cache.get("player_id")

    def title_name_at(tid, date):
        """头衔在 date 的名称 (title_history_names 最近一次更名 + 层级词)。"""
        t = lt931.get(str(tid)) or {}
        tnd = t.get("title_name_data") or {}
        thn = tnd.get("title_history_names") or []
        best = None
        for h in thn:
            if h.get("date") and cl.date_key(str(h["date"])) <= cl.date_key(str(date)):
                best = h["name"]
        if best is not None:
            nm = str(best)
            # 本地化键 (dynn_title_zhou / k_henan / h_china) vs 直写名 (青徐)
            if nm.startswith(("h_", "e_", "k_", "d_", "c_", "b_", "x_")):
                v = L.loc(table, nm) or nm
                nm = v
            else:
                v = L.loc(table, nm) or nm
                nm = v
        else:
            tnd2 = t.get("title_name_data") or {}
            nm = (tnd2.get("custom") or "").strip() or (tnd2.get("name") or "").strip()
            if not nm:
                nm = L.loc(table, t.get("key") or "") or t.get("key") or ""
        # 层级词 (简化: 用当前政体词)
        key = t.get("key") or ""
        if key.startswith("h_"):
            w = L.loc(table, "hegemony_celestial_chinese") or "皇朝"
            if not nm.endswith(w):
                nm = nm + w
        elif key.startswith("k_"):
            w = L.loc(table, "kingdom_celestial_chinese") or "路"
            if not nm.endswith(w):
                nm = nm + w
        elif key.startswith("d_"):
            # 公国/镇: 用通用词, 保持简单
            pass
        return nm

    # ---- 1) 玩家主要头衔 (d_+ / x_营地, 排除 x_nf_ 家族头衔) 变迁 ----
    print("== 1) 玩家 %s 主要头衔变迁 (title history, d_+/营地) ==" % pid)
    events = []  # (date_key, date, tid, key, nm, type, holder)
    for tid, t in lt931.items():
        if not isinstance(t, dict):
            continue
        hist = t.get("history") or {}
        if not isinstance(hist, dict):
            continue
        key = t.get("key") or ""
        # 只收主要头衔: h_/e_/k_/d_ + x_ 营地 (排除 x_nf_ 家族头衔)
        pfx = key[:2]
        if pfx in ("h_", "e_", "k_", "d_"):
            pass
        elif pfx == "x_" and "nomad" in key:
            pass
        else:
            continue
        for d, ev in hist.items():
            h = ev.get("holder") if isinstance(ev, dict) else ev
            typ = ev.get("type") if isinstance(ev, dict) else ""
            if h == pid:
                events.append((cl.date_key(d), d, tid, key, title_name_at(tid, d), typ))
    events.sort(key=lambda x: x[0])
    print("   主要头衔任职事件数:", len(events))
    for e in events:
        print("   ", e[1], e[4], "| type:", e[5], "| tid:", e[2], e[3])
    # 按日期合并成「任/失」叙事
    print("\n   合并后历任草稿:")
    # 重新构造: 每头衔跟踪 holder 序列, 输出 得/失
    for tid, t in lt931.items():
        if not isinstance(t, dict):
            continue
        hist = t.get("history") or {}
        if not isinstance(hist, dict):
            continue
        key = t.get("key") or ""
        pfx = key[:2]
        if pfx not in ("h_", "e_", "k_", "d_") and not (pfx == "x_" and "nomad" in key):
            continue
        seq = sorted(hist.items(), key=lambda x: cl.date_key(x[0]))
        prev = None
        for d, ev in seq:
            h = ev.get("holder") if isinstance(ev, dict) else ev
            typ = ev.get("type") if isinstance(ev, dict) else ""
            if h == pid and prev != pid:
                print(f"   {llm.fmt_cn_date(d)} 得{title_name_at(tid, d)} (type={typ})")
            elif prev == pid and h != pid:
                print(f"   {llm.fmt_cn_date(d)} 失{title_name_at(tid, d)} (type={typ}, 新主={h})")
            prev = h

    # ---- 2) 各时期 as-of 头衔 ----
    print("\n== 2) 玩家在各时期的头衔 (as-of) ==")
    for date in ("882.1.1", "892.1.1", "902.1.1", "912.1.1", "922.1.1", "931.6.7"):
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
                if pfx in ("h_", "e_", "k_", "d_") or (pfx == "x_" and "nomad" in key):
                    held.append((cl.date_key(key), key, title_name_at(tid, date)))
        # 主头衔 = 最高层级
        order = {"h_": 6, "e_": 5, "k_": 4, "d_": 3, "x_": 0}
        held.sort(key=lambda x: -order.get(x[1][:2], 0))
        print("   %s: %s" % (date, [h[2] for h in held[:6]]))

    # ---- 3) 刺客列传: 168 人死亡日期分布 ----
    print("\n== 3) 168 击杀死亡日期分布 ==")
    kills = set((cache.get("characters") or {}).get(str(pid), {}).get("kills") or [])
    pd = cache.get("player_death") or {}
    kills |= set(pd.get("kills") or [])
    chars = cache.get("characters") or {}
    rows = []
    for cid in kills:
        rec = chars.get(str(cid)) or {}
        d = (rec.get("death") or {}).get("date") or "9999.9.9"
        rows.append((cl.date_key(d), d, cid))
    rows.sort()
    n = len(rows)
    print("   总数:", n)
    third = n // 3
    print("   三等分: 前%d人 → %s; 中%d人 → %s; 后%d人 → %s" % (
        third, rows[third - 1][1], third, rows[2 * third - 1][1], n - 2 * third, rows[-1][1]))
    # 按主角人生阶段: 起家 867-898.3.2(毁营地), 扩张 899-918, 帝业 919-931
    for label, lo, hi in (("起家<899", "0.0.0", "898.12.31"), ("扩张899-918", "899.1.1", "918.12.31"), ("帝业919+", "919.1.1", "9999.9.9")):
        c = sum(1 for k, d, cid in rows if cl.date_key(lo) <= k <= cl.date_key(hi))
        print("   %s: %d 人" % (label, c))
    # 每份块字符估算
    total_chars = 0
    for cid in kills:
        rec = chars.get(str(cid)) or {}
        est = 60
        est += len(rec.get("name_zh") or "") * 2
        est += len((rec.get("death") or {}).get("reason") or "") * 3
        est += min(len(rec.get("memories") or []) * 30, 300)
        total_chars += est
    print("   全部 168 人估字符: ~%d (每人均 %d)" % (total_chars, total_chars // n))
    print("   三等分每块估字符: ~%d" % (total_chars // 3))

    # ---- 4) 提示词体积实测 ----
    print("\n== 4) prompts.log 体积实测 ==")
    with open(PROMPTS, "r", encoding="utf-8") as fp:
        txt = fp.read()
    # 找一次完整的 assassins lead 调用: 【主角大事年表】块长度 + 刀下诸魂块长度
    i = txt.find("刀下诸魂")
    seg = txt[i:i + 60000]
    m = re.search(r"【主角大事年表】\n(.*?)(?:\n\n|刀下诸魂)", txt)
    if m:
        print("   【主角大事年表】块字符数:", len(m.group(1)))
    m2 = re.search(r"刀下诸魂\n(.*?)(?:\n\n  |=====)", txt)
    if m2:
        print("   刀下诸魂块字符数:", len(m2.group(1)))
    # 完整 user 消息大小: 从"【传主】"到"请撰写"
    m3 = re.search(r"【传主】崔佛.*?刀下诸魂", txt, re.S)
    if m3:
        print("   从【传主】到刀下诸魂字符数:", len(m3.group(0)))

    # ---- 5) 富兰克林 / 延嗣 / 觉 / 文举 主要头衔 ----
    print("\n== 5) 其他角色主要头衔 ==")
    for cid, name in ((16820097, "富兰克林"), (40880, "延嗣"), (15557, "觉"), (16801893, "文举")):
        rows2 = []
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
                    if key[:2] in ("h_", "e_", "k_", "d_"):
                        rows2.append((cl.date_key(d), d, title_name_at(tid, d)))
        rows2.sort()
        print("   %s(%s):" % (name, cid), rows2[:10])

if __name__ == "__main__":
    main()
