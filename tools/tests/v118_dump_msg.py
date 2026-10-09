"""v118 probe: dump one snapshot request (messages) to a UTF-8 text file.

Usage: & tools\\py.ps1 tools\\tests\\v118_dump_msg.py <key> [snapshot] [outfile]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "output" / "洪氏2" / "data" / "v117_c1_1283.json"


def main():
    key = sys.argv[1]
    snap_path = Path(sys.argv[2]) if len(sys.argv) > 2 else SNAP
    if not snap_path.is_absolute():
        snap_path = ROOT / snap_path
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    msgs = snap["messages"][key]
    if isinstance(msgs, str):
        msgs = {"user": msgs}
    if isinstance(msgs, dict):
        msgs = [{"role": k, "content": v} for k, v in msgs.items()]
    parts = []
    for m in msgs:
        if isinstance(m, dict):
            parts.append(f"########## {m.get('role')} ##########")
            parts.append(str(m.get("content")))
        else:
            parts.append("########## ? ##########")
            parts.append(str(m))
    text = "\n".join(parts)
    out = ROOT / (sys.argv[3] if len(sys.argv) > 3 else f"logs/v118_msg_{key}.txt")
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text)} chars)")


if __name__ == "__main__":
    main()
