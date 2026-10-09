# -*- coding: utf-8 -*-
"""v117 取证探针 · 第三段：各卷缓存里 characters['44503']（洪天贵福）到底有没有 death。

不整载 150–310MB 的缓存：按块扫描原始 JSON，抓 `"44503": {` 之后的一段文本，
筛出含 birth/death/dead_data 的记录块。输出追加 logs/v117_probe_gf.txt。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(ROOT, "output", "洪氏2", "data")
OUT = os.path.join(ROOT, "logs", "v117_probe_gf.txt")

_buf = []


def P(*a):
    s = " ".join(str(x) for x in a)
    _buf.append(s)
    print(s, flush=True)


def scan(path, cid=b"44503", window=900, limit=6):
    pat = b'"' + cid + b'":'
    found = []
    with open(path, "rb") as fp:
        prev = b""
        while len(found) < limit:
            chunk = fp.read(4 << 20)
            if not chunk:
                break
            buf = prev + chunk
            base = 0
            while True:
                i = buf.find(pat, base)
                if i < 0:
                    break
                seg = buf[i:i + window]
                if b'"birth"' in seg or b'"death"' in seg or b'"dead_data"' in seg \
                        or b'"family_data"' in seg:
                    found.append((i, seg))
                base = i + 1
            prev = buf[-(window + 16):]
    return found


def main():
    files = sys.argv[1:] or [
        "player_17066495.json",   # 洪光通（实跑缓存，10/9 12:23）
        "player_44503.json",      # 天贵福本人
        "player_38957.json",      # 秀全本人
        "player_50565938.json",   # 洪希晏（10/8 那卷）
        "player_207044.json",     # 洪七公（10/7 那卷）
        "player_33725392.json",   # 洪大力
        "player_135480.json",     # 耀国·缯松
        "player_67408343.json",   # 10/9 新卷
    ]
    P("\n" + "=" * 78)
    P("== [S6] 各卷缓存 characters['44503'] 的原始记录（有无 death） ==")
    for fn in files:
        p = os.path.join(DATA, fn)
        if not os.path.isfile(p):
            P(f"[S6] 缺 {fn}")
            continue
        hits = scan(p)
        P(f"\n[S6] {fn}  ({os.path.getsize(p)/1048576:.0f}MB)  命中记录块 {len(hits)}")
        seen = set()
        for i, seg in hits:
            txt = seg.decode("utf-8", "replace")
            txt = re.sub(r"\s+", " ", txt)
            key = txt[:120]
            if key in seen:
                continue
            seen.add(key)
            P(f"      @{i}: {txt[:520]}")
    with open(OUT, "a", encoding="utf-8") as fp:
        fp.write("\n".join(_buf) + "\n")


if __name__ == "__main__":
    main()
