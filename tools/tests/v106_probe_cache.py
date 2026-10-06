# -*- coding: utf-8 -*-
"""v106 probe: per-request size of the 「传主档案」 block vs. the observed prefix-cache hits.

Reads logs/prompts.log (request bodies) and logs/journal.log (per-call usage lines), maps the
two by the logged character count of a request, and prints one row per request of the run.
Read-only: no melt, no snapshot, no cache rebuild.
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

# block whose size we report: the per-article protagonist dossier
BLOCK_HEAD = re.compile(r"^[【\[]?(传主档案|人物档案)[】\]]?$")


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


def dossier_len(user):
    """Chars of the 传主档案 / 人物档案 block inside this user message (0 when absent)."""
    lines = user.split("\n")
    for i, ln in enumerate(lines):
        if BLOCK_HEAD.match(ln.strip()):
            # block runs to the next blank line, or to the next block head at the same level
            j = i + 1
            while j < len(lines) and lines[j].strip():
                j += 1
            return sum(len(x) + 1 for x in lines[i:j]), i + 1
    return 0, -1


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
    reqs = [r for r in parse_requests() if RUN_FROM <= r["ts"] <= RUN_TO]
    usage = parse_usage()
    # journal timestamps in the same wall-clock window as the run
    usage = [u for u in usage if RUN_FROM[11:] <= u["t"] <= "23:42:00"]
    by_chars = {}
    for u in usage:
        for d in range(0, 4):
            by_chars.setdefault(u["chars"] + d, []).append(u)
            by_chars.setdefault(u["chars"] - d, []).append(u)
    lines = []
    lines.append("run %s .. %s   requests=%d   usage-lines=%d"
                 % (RUN_FROM, RUN_TO, len(reqs), len(usage)))
    lines.append("")
    hdr = "%-46s %8s %7s %7s %7s %7s %6s" % (
        "request", "chars", "dossier", "input", "hit", "miss", "hit%")
    lines.append(hdr)
    tot_in = tot_hit = tot_dos = 0
    matched = 0
    for r in sorted(reqs, key=lambda x: x["ts"]):
        kind = request_kind(r["user"])
        if len(kind) > 44:
            kind = kind[:43] + "~"
        dlen, _ = dossier_len(r["user"])
        cand = by_chars.get(r["chars"])
        u = cand.pop(0) if cand else None
        if u:
            matched += 1
            tot_in += u["inp"]
            tot_hit += u["hit"]
            tot_dos += dlen
            lines.append("%-46s %8d %7d %7d %7d %7d %5d%%"
                         % (kind, r["chars"], dlen, u["inp"], u["hit"], u["miss"],
                            u["hit"] * 100 // u["inp"] if u["inp"] else 0))
        else:
            lines.append("%-46s %8d %7d %8s" % (kind, r["chars"], dlen, "(no usage line)"))
    lines.append("")
    lines.append("matched %d/%d  total input=%d  total hit=%d  total dossier chars=%d"
                 % (matched, len(reqs), tot_in, tot_hit, tot_dos))
    if tot_in:
        lines.append("merged hit rate=%d%%; dossier chars = %.1f%% of all input chars"
                     % (tot_hit * 100 // tot_in,
                        tot_dos * 100.0 / sum(len(r["user"]) + len(r["system"]) for r in reqs)))
    txt = "\n".join(lines) + "\n"
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(txt)
    sys.stdout.write(txt)


if __name__ == "__main__":
    main()
