# -*- coding: utf-8 -*-
"""v104 probe 4: culture 271 entry, house 20237 entry, the son's language fields.

Read-only byte scan.
"""
import io
import os
import sys

MELT = r"D:\Roman\output\洪氏2\data\melt_1077_01_01.json"
OUT = r"D:\Roman\logs\v104_patronym_probe4.txt"

out = io.StringIO()


def p(*a):
    print(*a, file=out)


def win(off, before, after):
    with open(MELT, "rb") as fp:
        fp.seek(max(0, off - before))
        return fp.read(before + after)


def all_offsets(needle, cap=50):
    res = []
    with open(MELT, "rb") as fp:
        off = 0
        tail = b""
        CH = 8 * 1024 * 1024
        while True:
            buf = fp.read(CH)
            if not buf:
                break
            data = tail + buf
            base = off - len(tail)
            s = 0
            while True:
                k = data.find(needle, s)
                if k < 0:
                    break
                res.append(base + k)
                if len(res) >= cap:
                    return res
                s = k + 1
            tail = data[-len(needle) - 8:]
            off += len(buf)
    return res


def main():
    for label, needle in [
        ("希柏耳尼亚-诺斯", "希柏耳尼亚-诺斯".encode("utf-8")),
        ("洪堡", "洪堡".encode("utf-8")),
        ("name_list_norse", b"name_list_norse"),
        ("缯", "缯".encode("utf-8")),
        ("耀国松", "耀国松".encode("utf-8")),
        ("缯松", "缯松".encode("utf-8")),
    ]:
        hits = all_offsets(needle, cap=40)
        p()
        p(f"=== {label}: {len(hits)} hit(s) (cap 40) ===")
        for h in hits[:8]:
            p(f"  @{h}")
            p("   " + win(h, 700, 900).decode("utf-8", "replace"))

    # the son's record: does it carry `languages`?
    p()
    p("=== son 117484775 alive_data language / father / mother fields ===")
    with open(MELT, "rb") as fp:
        fp.seek(30905033)
        blob = fp.read(40000).decode("utf-8", "replace")
    for key in ('"languages"', '"father"', '"mother"', '"real_father"',
                '"culture_history"', '"dead_data"'):
        p(f'  {key}: count={blob.count(key)}')
    i = blob.find('"alive_data"')
    p("  alive_data at +%d" % i)
    return 0


if __name__ == "__main__":
    main()
    with open(OUT, "w", encoding="utf-8") as fp:
        fp.write(out.getvalue())
    sys.stderr.write(f"written {OUT}\n")
