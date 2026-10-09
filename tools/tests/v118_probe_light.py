"""v118 probe: inspect one facts snapshot (killed roster + genealogy/appendix lines).

Reads only the small snapshot JSON, never a melt. Usage:
  & tools\\py.ps1 tools\\tests\\v118_probe_light.py [snapshot] [--killed|--gen|--all]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "output" / "洪氏2" / "data" / "v117_c1_1283.json"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    path = Path(args[0]) if args else DEFAULT
    if not path.is_absolute():
        path = ROOT / path
    snap = json.loads(path.read_text(encoding="utf-8"))
    facts = snap["facts"]
    show_all = "--all" in flags or not (flags & {"--killed", "--gen"})
    if show_all or "--killed" in flags:
        killed = facts.get("killed") or []
        print(f"== killed: {len(killed)} ==")
        for i, e in enumerate(killed, 1):
            print(f"{i:3d} id={e.get('id')!s:<12} name={e.get('name')!r} "
                  f"date={e.get('death_date')} house={e.get('house')!r} "
                  f"office={e.get('office')!r} label={e.get('label')!r} "
                  f"identity={e.get('identity')!r}")
            print(f"      death={e.get('death')!r}")
    if show_all or "--gen" in flags:
        print("== genealogy (printed 世系) ==")
        for ln in facts.get("genealogy") or []:
            print(f"  {ln!r}")
        print("== protagonist.house_history ==")
        for ln in ((facts.get("protagonist") or {}).get("house_history") or []):
            print(f"  {ln!r}")
        print("== genealogy_subject ==")
        for ln in facts.get("genealogy_subject") or []:
            print(f"  {ln!r}")


if __name__ == "__main__":
    main()
