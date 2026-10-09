"""v118 probe: compare the 世系 head lines of several biographies.

Usage: & tools\\py.ps1 tools\\tests\\v118_probe_shixi.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = [
    ROOT / "output/洪氏2/洪光通(1236)_终传_1283_09_11.md",
    ROOT / "logs/v117_before_洪光通终传.md",
    ROOT / "output/洪氏2/洪七公(1109)_终传_1152_11_13.md",
    ROOT / "output/洪氏2/洪秀全(849)_终传_904_11_30.md",
]


def main():
    for p in FILES:
        if not p.is_file():
            print(f"!! missing {p}")
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        try:
            i = next(i for i, ln in enumerate(lines) if ln.strip() == "### 世系")
        except StopIteration:
            print(f"== {p.name}: no 世系 ==")
            continue
        print(f"\n===== {p.name} (line {i + 1}) =====")
        shown = 0
        for ln in lines[i:i + 120]:
            s = ln.strip()
            if s.startswith("### ") and shown:
                break
            if s.startswith("**") or (s and not s.startswith("-") and "：" not in s):
                print("   ", ln)
                shown += 1
            elif s.startswith("　"):     # the 世系图 chain rows
                print("   ", ln)


if __name__ == "__main__":
    main()
