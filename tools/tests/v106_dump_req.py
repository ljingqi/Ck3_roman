# -*- coding: utf-8 -*-
"""v106 probe: dump the material of one request (matched by logged char count) to a file."""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROMPTS = os.path.join(ROOT, "logs", "prompts.log")
OUT = os.path.join(ROOT, "logs", "v106_req_dump.txt")

want_chars = int(sys.argv[1]) if len(sys.argv) > 1 else 7198
ts_from = sys.argv[2] if len(sys.argv) > 2 else "2026-10-05 23:36"

reqs, cur, role = [], None, None
for ln in io.open(PROMPTS, "r", encoding="utf-8"):
    ln = ln.rstrip("\n")
    if ln.startswith("=====") and ln.endswith("====="):
        if cur:
            reqs.append(cur)
        cur = {"ts": ln.strip("= "), "system": [], "user": []}
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
if cur:
    reqs.append(cur)

sel = []
for r in reqs:
    if r["ts"] < ts_from:
        continue
    n = len("\n".join(r["system"])) + len("\n".join(r["user"]))
    if abs(n - want_chars) <= 3:
        sel.append(r)

buf = []
for r in sel:
    buf.append("===== %s  chars~%d =====" % (r["ts"], want_chars))
    buf.append("--- [user] ---")
    buf.extend(r["user"])
    buf.append("")
if not sel:
    buf.append("no request matched chars~%d from %s" % (want_chars, ts_from))
io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(buf) + "\n")
sys.stdout.write("wrote %s (%d request(s))\n" % (OUT, len(sel)))
