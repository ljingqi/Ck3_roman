"""v118 probe: the played chain, the seat succession and the first genealogy heads of a snapshot.

Small-snapshot reads only. Usage:
  & tools\\py.ps1 tools\\tests\\v118_probe_chain.py [snapshot] [n]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "output" / "洪氏2" / "data" / "v117_c1_1283.json"


def main():
    snap_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SNAP
    if not snap_path.is_absolute():
        snap_path = ROOT / snap_path
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    facts = json.loads(snap_path.read_text(encoding="utf-8"))["facts"]
    print("== seat_succession ==")
    print(json.dumps(facts.get("seat_succession"), ensure_ascii=False)[:3000])
    print("\n== succession ==")
    print(json.dumps(facts.get("succession"), ensure_ascii=False)[:1500])
    tree = facts.get("genealogy_tree") or {}
    nodes = tree.get("nodes") if isinstance(tree, dict) else tree
    print(f"\n== genealogy_tree keys={list(tree) if isinstance(tree, dict) else type(tree)} ==")
    if isinstance(nodes, list):
        print(json.dumps(nodes[:n], ensure_ascii=False)[:3000])
    chars = facts.get("characters") or {}
    print(f"\n== characters (facts) n={len(chars)} sample ==")
    for i, (cid, rec) in enumerate(chars.items()):
        if i >= 3:
            break
        print(cid, json.dumps(rec, ensure_ascii=False)[:800])


if __name__ == "__main__":
    main()
