# -*- coding: utf-8 -*-
"""v122: inspect a facts snapshot for the five question surfaces (no save data needed).

Usage: & tools\\py.ps1 tools\\tests\\v122_check_snap.py output\\田所2\\data\\v122_dec1.json
"""
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

PATTERNS = {
    "御前会议N席行": re.compile(r"御前会议[〇零一二三四五六七八九十百]+席"),
    "僚属任职行": re.compile(r"(廷中|营中|帐下)僚属任职"),
    "通用席名": re.compile(r"掌玺大臣|军事统帅|财政总管|间谍首脑|宫廷司祭"),
    "受刑获释": re.compile(r"被囚禁[^，。]{0,8}遭到[^，。]{0,6}(阉割|剜目|用刑)[^。]{0,20}"),
    "旧受刑句": re.compile(r"(被其阉割|被其剜目|被其用刑)"),
    "乡绅标签": re.compile(r"乡绅[\u4e00-\u9fff]{2,8}金元惠|金元惠"),    "政体行": re.compile(r"政体[\u4e00-\u9fff]{2,6}"),
    "职名前置样本": re.compile(r"(长史|司户|司马|察事|右笔|奉行|大将|目付|別当|家令|侍|目代)"
                          r"(兼[\u4e00-\u9fff]{2,6})?[\u4e00-\u9fff]{2,4}"),
}


def main():
    path = sys.argv[1]
    snap = json.load(open(path, encoding="utf-8"))
    facts = snap["facts"]
    surface = snap.get("shared", "") + "".join(
        f"\n{m['system']}\n{m['user']}" for m in (snap.get("messages") or {}).values())
    blocks = snap.get("blocks") or {}
    p = facts.get("protagonist") or {}
    print(f"=== {path}")
    print("meta:", {k: snap['meta'].get(k) for k in ("folder", "player_id", "as_of",
                                                     "decade", "melt", "articles")})
    print("protagonist keys:", sorted(p.keys()))
    for k in ("government", "council", "court_positions", "ruler_since", "domain",
              "domain_count", "vassal_count", "capital", "landless"):
        if k in p:
            print(f"  {k} = {p[k]!r}")
    print("\n-- facts top-level keys:", sorted(k for k in facts if k != "_facts"))
    for k in ("player_death", "reign_end", "genealogy", "timeline"):
        v = facts.get(k)
        if isinstance(v, list):
            print(f"  {k}: list[{len(v)}]")
        elif isinstance(v, dict):
            print(f"  {k}: { {kk: v[kk] for kk in list(v)[:8]} }")
        elif v is not None:
            print(f"  {k}: {v!r}")
    print()
    for name, rx in PATTERNS.items():
        hits = rx.findall(surface)
        shown = sorted({(h if isinstance(h, str) else "".join(h)) for h in hits})
        print(f"[{name}] {len(hits)} 命中  {shown[:12]}")
    print("\n-- 命中上下文 --")
    for name in ("受刑获释", "旧受刑句", "通用席名", "御前会议N席行", "僚属任职行"):
        n = 0
        for m in PATTERNS[name].finditer(surface):
            print(f"  {name}: …{surface[max(0, m.start()-50):m.end()+30]}…")
            n += 1
            if n >= 3:
                break
    # timeline / 大事年表 lines carrying a court office prefix
    tl = facts.get("timeline") or []
    if isinstance(tl, list):
        pre = [x for x in tl if isinstance(x, str) and re.search(
            r"(长史|司户|司马|察事|右笔|奉行|大将|目付|別当|家令|目代|掌玺)", x)]
        print(f"\n-- 大事年表带职名的行: {len(pre)}/{len(tl)}")
        for x in pre[:8]:
            print("   " + x[:150])


    # appendix (written by biography._appendix_text from facts only, so it can be rendered here)
    try:
        import biography as bio
        ap = bio._appendix_text(facts)
    except Exception as e:  # noqa: BLE001
        ap = f"(appendix error: {e})"
    print(f"\n-- 终传附录 ({len(ap)} 字符)")
    for ln in ap.split("\n"):
        if re.search(r"传主|卒|去位|退位|让位|剃发", ln):
            print("   " + ln[:180])
    print("   附录含「### 世系」:", "### 世系" in ap, " 含「### 大事年表」:", "### 大事年表" in ap)


if __name__ == "__main__":
    main()
