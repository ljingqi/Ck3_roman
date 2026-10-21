# -*- coding: utf-8 -*-
"""v123 probe (issue 2): the same-dynasty ruler roster lines the 封档总评 writes, plus the
reference protagonist and the part-2 prompt block. Loads the newest cache + the newest melt once
(the campaign caches are not needed: kin, houses and traits all come from the cache/melt).

Usage:  python tools/tests/v123_probe_roster.py [家族文件夹]
Writes  logs/v123/v123_roster_<folder>.txt  and prints the tail.
"""
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

import biography as bio        # noqa: E402
import cache_lib as cl         # noqa: E402
import epilogue as E           # noqa: E402
import facts as F              # noqa: E402
import llm                     # noqa: E402
import pipeline as P           # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "田所2"


def main():
    cfg = llm.load_config()
    folder = os.path.join(cfg.get("output_dir", ""), FOLDER)
    cands = [c for c in P.epilogue_candidates(cfg) if c["folder"] == FOLDER]
    if not cands:
        raise SystemExit(f"{FOLDER}: 没有终传")
    row = cands[0]
    ch = E.chapters(folder)
    ref_cid = ch["rows"][-1]["cid"]
    cache = cl.load_cache(P.find_cache_path(cfg, row["pid"], None))
    t0 = time.time()
    melt = P.load_latest_melt(cfg, cache)
    if melt is None:
        raise SystemExit("无可用 melt")
    print(f"熔件载入 {time.time() - t0:.1f}s", flush=True)
    if P.tail_state_applies(cache):
        _n, tail = P._backfill_tail_deaths(cfg, cache)
        P._merge_tail_title_flags(melt, tail)
    facts = F.build_facts(cache, melt, bio._names_path(cfg, cache), cfg=cfg)
    f = facts["_facts"]
    t1 = time.time()
    rep = E.roster(f, ref_cid=ref_cid)
    out = [f"== {FOLDER}  as_of={rep['as_of']}  同宗在世 {rep['alive']} 人  "
           f"有地者 {len(rep['rows'])} 人  其余 {len(rep['others'])} 人",
           f"   名册构建 {time.time() - t1:.1f}s",
           f"   末代传主(亲属基准) ref={rep['ref']}",
           f"   今生传主 protagonist={rep['protagonist']}",
           f"   基准人物原样名 _ref_name = {E._ref_name(f, ref_cid, rep['as_of'])!r}",
           "", "--- 主名册（有地者）新句式 ---"]
    ref_name = rep["ref"]["name"]
    for r in rep["rows"]:
        out.append("   " + E._roster_line(r, ref_name))
    out += ["", "--- 主名册原始字段（前 5 行） ---"]
    for r in rep["rows"][:5]:
        out.append("   %s | label=%r kin=%r branch=%r traits=%r ref=%s cid=%s"
                   % (r["cid"], r["label"], r["kin"], r["house_branch"],
                      (r["traits"] or "")[:40], r["is_ref"], r["cid"]))
    out += ["", "--- 其余在世同宗（前 12 行） ---"]
    for r in rep["others"][:12]:
        out.append("   " + E._roster_line(r, ref_name))
    out += ["", "--- 第二部分提示词（前 24 行） ---"]
    m2 = E.part2_messages(ch, rep, FOLDER, "", roster_override=E.roster_text(rep))
    out += ["   " + ln for ln in m2[1]["content"].split("\n")[:24]]
    out += ["", "--- 成稿骨架 ---"]
    md = E.assemble(FOLDER, ch, rep, "（第一部分）", "（第二部分）", row["pid"])
    out += ["   " + ln[:130] for ln in md.split("\n") if ln.startswith(("#", ">", "<!--"))]
    log = os.path.join(ROOT, "logs", f"v123_roster_{FOLDER}.txt")
    io.open(log, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print("\n".join(out[:6]))
    print("已写", log)


if __name__ == "__main__":
    main()
