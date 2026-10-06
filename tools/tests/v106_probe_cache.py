# -*- coding: utf-8 -*-
"""v106 probe: per-request size of the 「传主档案」/「传主家室」 blocks vs. the observed
prefix-cache hits.

Reads logs/prompts.log (request bodies) and logs/journal.log (per-call usage lines), maps the
two by the logged character count of a request, and prints one row per request of the run.
Read-only: no melt, no snapshot, no cache rebuild.

Usage: & tools\\py.ps1 tools\\tests\\v106_probe_cache.py ["YYYY-MM-DD HH:MM" "YYYY-MM-DD HH:MM"] [out.txt]
       (defaults = the 2026-10-05 23:36..23:41 run, the batch the v106 report cites)
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROMPTS = os.path.join(ROOT, "logs", "prompts.log")
JOURNAL = os.path.join(ROOT, "logs", "journal.log")
OUT = os.path.join(ROOT, "logs", "v106_cache_probe.txt")

RUN_FROM = "2026-10-05 23:36"
RUN_TO = "2026-10-05 23:41"

# blocks whose size we report: the identity half and the household half of the dossier
BLOCK_HEAD = re.compile(r"^[【\[]?(传主档案|人物档案)[】\]]?$")
HOME_HEAD = re.compile(r"^[【\[]?传主家室[】\]]?$")


def parse_requests():
    reqs = []
    cur = None
    role = None
    for ln in io.open(PROMPTS, "r", encoding="utf-8"):
        ln = ln.rstrip("\n")
        m = re.match(r"^===== (.*?) =====$", ln)
        if m:
            if cur is not None:
                reqs.append(cur)
            cur = {"ts": m.group(1), "system": [], "user": []}
            role = None
            continue
        if cur is None:
            continue
        if ln == "--- [system] ---":
            role = "system"
            continue
        if ln == "--- [user] ---":
            role = "user"
            continue
        if role:
            cur[role].append(ln)
    if cur is not None:
        reqs.append(cur)
    for r in reqs:
        r["system"] = "\n".join(r["system"])
        r["user"] = "\n".join(r["user"])
        r["chars"] = len(r["system"]) + len(r["user"])
    return reqs


def block_len(user, head_re):
    """Chars of one block inside this user message (0 when absent), and its 1-based line number."""
    lines = user.split("\n")
    for i, ln in enumerate(lines):
        if head_re.match(ln.strip()):
            # block runs to the next blank line, or to the next block head at the same level
            j = i + 1
            while j < len(lines) and lines[j].strip():
                j += 1
            return sum(len(x) + 1 for x in lines[i:j]), i + 1
    return 0, -1


def dossier_len(user):
    """Chars of the 传主档案 / 人物档案 block inside this user message (0 when absent)."""
    return block_len(user, BLOCK_HEAD)


def parse_usage():
    out = []
    for ln in io.open(JOURNAL, "r", encoding="utf-8"):
        m = re.search(r"^\[(\d\d:\d\d:\d\d)\] token: 输入(\d+) = 命中(\d+) \+ 未命中(\d+)"
                      r" \| 输出(\S+) \| 字符(\d+)", ln)
        if m:
            out.append({"t": m.group(1), "inp": int(m.group(2)), "hit": int(m.group(3)),
                        "miss": int(m.group(4)), "out": m.group(5), "chars": int(m.group(6))})
    return out


def request_kind(user):
    m = re.search(r"请撰写板块《(.+?)》", user)
    if m:
        return "mid:" + m.group(1)
    if "请据此撰写总纲" in user:
        return "intro"
    m = re.search(r"这是文章的开篇板块《(.+?)》", user)
    if m:
        return "lead:" + m.group(1)
    return "?"


def main():
    global RUN_FROM, RUN_TO, OUT
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) >= 2:
        RUN_FROM, RUN_TO = args[0], args[1]
    if len(args) >= 3:
        OUT = args[2]
    reqs = [r for r in parse_requests() if RUN_FROM <= r["ts"] <= RUN_TO]
    usage = parse_usage()
    # journal timestamps carry no date, so the run's time-of-day range selects them
    _to_hms = RUN_TO[11:] + ":00" if len(RUN_TO) == 16 else RUN_TO[11:]
    usage = [u for u in usage if RUN_FROM[11:] <= u["t"] <= _to_hms]
    by_chars = {}
    for u in usage:
        for d in range(0, 4):
            by_chars.setdefault(u["chars"] + d, []).append(u)
            by_chars.setdefault(u["chars"] - d, []).append(u)
    lines = []
    lines.append("run %s .. %s   requests=%d   usage-lines=%d"
                 % (RUN_FROM, RUN_TO, len(reqs), len(usage)))
    lines.append("")
    hdr = "%-46s %8s %7s %7s %7s %7s %7s %6s" % (
        "request", "chars", "档案", "家室", "input", "hit", "miss", "hit%")
    lines.append(hdr)
    tot_in = tot_hit = tot_dos = tot_home = 0
    matched = 0
    for r in sorted(reqs, key=lambda x: x["ts"]):
        kind = request_kind(r["user"])
        if len(kind) > 44:
            kind = kind[:43] + "~"
        dlen, _ = dossier_len(r["user"])
        hlen, _ = block_len(r["user"], HOME_HEAD)
        cand = by_chars.get(r["chars"])
        u = cand.pop(0) if cand else None
        if u:
            matched += 1
            tot_in += u["inp"]
            tot_hit += u["hit"]
            tot_dos += dlen
            tot_home += hlen
            lines.append("%-46s %8d %7d %7d %7d %7d %7d %5d%%"
                         % (kind, r["chars"], dlen, hlen, u["inp"], u["hit"], u["miss"],
                            u["hit"] * 100 // u["inp"] if u["inp"] else 0))
        else:
            lines.append("%-46s %8d %7d %7d %8s" % (kind, r["chars"], dlen, hlen, "(no usage line)"))
    lines.append("")
    lines.append("matched %d/%d  total input=%d  total hit=%d  total 档案 chars=%d  家室 chars=%d"
                 % (matched, len(reqs), tot_in, tot_hit, tot_dos, tot_home))
    all_chars = sum(len(r["user"]) + len(r["system"]) for r in reqs)
    if tot_in:
        lines.append("merged hit rate=%d%%; 档案+家室 chars = %.1f%% of all request chars"
                     % (tot_hit * 100 // tot_in, (tot_dos + tot_home) * 100.0 / all_chars))
    txt = "\n".join(lines) + "\n"
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(txt)
    sys.stdout.write(txt)


if __name__ == "__main__":
    main()
