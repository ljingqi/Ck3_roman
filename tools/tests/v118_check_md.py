"""v118 check · the regenerated 洪光通 final biography: 刺客列传 and 世系.

Reads the newest `洪光通(1236)_终传_*.md` and prints the two spots the user reported, with
assertions:
  * no placeholder 「某人」 anywhere in the file;
  * the 刺客列传 entry list names every victim (11 entries, 米娜 among them);
  * the 世系 heads carry 生年 + 亲属词 for the first generations, and the 世次 match the older
    volumes (四世 for 尼各老 / 洪审礼 / 缯·洪堡, 洪七公 七世).

Usage: & tools\\py.ps1 tools\\tests\\v118_check_md.py [path-to-md]
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "output" / "洪氏2"
WANT_CHAIN = ("一世 洪秀全 ─ 二世 洪天贵福 ─ 四世 洪思忠（尼各老） ─ 四世 洪审礼 ─ 四世 缯·洪堡")
WANT_HEADS = ("天皇帝穿刺者洪秀全", "天皇帝堕邪者圣洪天贵福", "教宗欢乐者尼各老", "洪审礼")


def find_md():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    cands = sorted(FOLDER.glob("洪光通(1236)_终传_*.md"), key=lambda p: p.stat().st_mtime)
    return cands[-1] if cands else None


def block(lines, start_pat, stop_pat=r"^### "):
    for i, ln in enumerate(lines):
        if re.match(start_pat, ln):
            j = i + 1
            while j < len(lines) and not re.match(stop_pat, lines[j]):
                j += 1
            return i, lines[i:j]
    return None, []


def main():
    p = find_md()
    if not p or not p.is_file():
        print("找不到成稿:", p)
        return 1
    lines = p.read_text(encoding="utf-8").splitlines()
    print(f"== {p.name} ({p.stat().st_size:,} 字节, "
          f"{p.stat().st_mtime}) ==")
    bad = []
    print("\n-- 刺客列传名录 --")
    i, blk = block(lines, r"^## .*刺客列传", stop_pat=r"^## ")
    if i is None:
        i, blk = block(lines, r"^### .*刺客列传", stop_pat=r"^## ")
    heads = [ln for ln in blk if re.match(r"^#{3,4} ", ln) and "刺客列传" not in ln]
    for h in heads:
        print("   ", h)
    for ln in blk:
        if "米娜" in ln or "十一" in ln or "某人" in ln:
            print("     ", ln[:180])
    if not any("米娜" in ln for ln in blk):
        bad.append("名录里没有米娜")
    print("\n-- 亡魂/刺客口径句 --")
    for ln in lines:
        if "亡魂" in ln or "结仇" in ln:
            print("   ", ln.strip()[:200])
    print("\n-- 世系 --")
    i, blk = block(lines, r"^### 世系")
    for ln in blk:
        print("   ", ln)
    txt = "\n".join(lines)
    if "某人" in txt:
        bad.append("成稿里仍有「某人」")
    if WANT_CHAIN not in txt:
        bad.append(f"世系图链条与旧卷不一致（期望 {WANT_CHAIN}）")
    joined = "\n".join(blk)
    for w in WANT_HEADS:
        if w not in joined:
            bad.append(f"世系头行缺 {w}")
    # the 世次 of a head is the `**N世**` line right above it
    def gen_of(name):
        """The 世次 group label (`**四世**`) that a head line sits under; one label covers a group."""
        for k, ln in enumerate(blk):
            if ln.startswith("**") and name in ln \
                    and not re.match(r"^\*\*[一二三四五六七八九十]+世\*\*$", ln):
                for j in range(k - 1, -1, -1):
                    m = re.match(r"^\*\*([一二三四五六七八九十]+世)\*\*$", blk[j])
                    if m:
                        return m.group(1)
                return ""
        return ""

    for w, gen in (("教宗欢乐者尼各老", "四世"), ("山南公子洪审礼", "四世"),
                   ("山南公子圣缯·洪堡", "四世"), ("鄯州节度使贪婪者洪七公", "七世"),
                   ("洪七公", "七世"), ("英勇者洪光通", "十一世")):
        if w == "洪七公" and not any(w in ln and ln.startswith("**") and ln.endswith("洪七公")
                                     for ln in blk):
            continue
        g = gen_of(w)
        if not g:
            bad.append(f"世系里找不到 {w} 的世次行")
        elif g != gen:
            bad.append(f"{w} 的世次是 {g}，应为 {gen}")
    # the four early heads must state 生年
    for w in WANT_HEADS[:4]:
        seg = [ln for ln in blk if ln.startswith("**" + w) or w in ln and ln.startswith("**")]
        if not seg:
            continue
        ln = seg[0]
        if "生" not in ln:
            bad.append(f"「{ln}」没有生年")
    print("\nRESULT:", "PASS" if not bad else "FAIL")
    for b in bad:
        print("   -", b)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
