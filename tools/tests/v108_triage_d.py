# -*- coding: utf-8 -*-
"""D 段分诊：把**世代精确**（生产口径）成稿回放的每一处改写连文件／节／段落主语一起列全，不再按
`issue()` 的采样限额截断，并把命中节的改写句成对列出（每节最多 4 对）。用来把 D 段的「改写候选」
逐条分成「修对了旧稿里的错词」与「新改错」。

用法：py tools/tests/v108_triage_d.py [pid ...]（不传则跑全部战役）；只读，输出 logs/_triage_d.txt。
只列入文件名含该战役 `as_of` 世代的稿（与 tools/tests/v108_kin_sweep.py 的 exact 段同判据）。
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)
import biography as bio          # noqa: E402
import facts as F                # noqa: E402
import llm                       # noqa: E402
import v108_kin_sweep as SW      # noqa: E402

WANT = {int(x) for x in sys.argv[1:]}
data_dir = os.path.join(ROOT, "output", "洪氏2", "data")
out_dir = os.path.join(ROOT, "output", "洪氏2")
snaps = SW.find_snapshots(data_dir)
lines = []
hits = 0
for cpath in sorted(SW.glob.glob(os.path.join(data_dir, "player_*.json"))):
    if "pre_v" in os.path.basename(cpath) or ".tmp" in os.path.basename(cpath):
        continue
    cache = json.load(io.open(cpath, encoding="utf-8"))
    pid = int(cache.get("player_id"))
    if WANT and pid not in WANT:
        continue
    snap = (snaps.get(pid) or [None])[0]
    facts = SW.load_facts(snap) if snap else {}
    as_of = SW.as_of_of(cache, facts)
    fi = F.Facts(cache, {}, None, as_of=as_of, decade=facts.get("decade"))
    facts["_facts"] = fi
    if not facts.get("characters"):
        facts["characters"] = {}
    chars = cache.get("characters") or {}
    birth_tag = "(%s)" % ((((chars.get(str(pid)) or {}).get("birth") or "").split(".") or [""])[0])
    art_map = {}
    try:
        art_map = {a.get("title"): a for a in bio.build_articles(facts, cache, llm.load_config())}
    except Exception as e:                                    # noqa: BLE001
        lines.append("（%s build_articles 失败：%s）" % (pid, e))
    aof = str(as_of or "")
    m = SW.re.match(r"(\d{3,4})\.(\d{1,2})", aof)
    tag = "%s_%02d" % (m.group(1), int(m.group(2))) if m else ""
    for path in sorted(SW.glob.glob(os.path.join(out_dir, "*.md"))):
        base = os.path.basename(path)
        if birth_tag not in base or tag not in base:
            continue
        for art, title, body in SW.sections_of(io.open(path, encoding="utf-8").read()):
            if not body.strip():
                continue
            a = art_map.get(art)
            if a is None:
                continue
            sec = next((s for s in a["sections"] if s.get("title") == title), None)
            subs = list((sec or {}).get("members") or [])
            if not subs:
                best = []
                for s in a["sections"]:
                    mem = s.get("members") or []
                    score = sum(1 for c in mem
                                if len(((facts["characters"].get(str(c)) or {})
                                        .get("name", "")).split("·")[0]) >= 2
                                and ((facts["characters"][str(c)]["name"]).split("·")[0] in title))
                    if score > len(best):
                        best = list(mem)
                subs = best
            if not subs:
                subs = [bio._article_subject(facts, cache, a["key"])]
            out = bio._fix_kin_roles(body, facts, cache, subject_ids=subs)
            if out == body:
                continue
            hits += 1
            names = {str(c): ((facts["characters"].get(str(c)) or {}).get("name")
                              or (chars.get(str(c)) or {}).get("name_zh") or "?") for c in subs}
            lines.append("=" * 100)
            lines.append("[%d] pid=%s %s §%s  主语=%s"
                         % (hits, pid, base, title, {k: names[k] for k in names}))
            lines.append("    主语名=%s" % names)
            for line in SW.pair_sentences(body, out, 4):
                lines.append("  " + line)
lines.append("=" * 100)
lines.append("exact 段改写节数 = %d" % hits)
io.open(os.path.join(ROOT, "logs", "_triage_d.txt"), "w", encoding="utf-8",
        newline="\n").write("\n".join(lines) + "\n")
print("\n".join(lines[-4:]))
