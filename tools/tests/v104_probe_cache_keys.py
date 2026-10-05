# -*- coding: utf-8 -*-
"""v104 probe: byte-scan the 洪氏2 cache for the church-history latches (no full JSON load).

Prints a short window after each wanted key so we can see how many rite/faith ids the
latches hold and what their first/last latch dates are.
"""
import sys

PATH = r"D:\Roman\output\洪氏2\data\player_135480.json"
KEYS = [b'"rite_tenets_history"', b'"rite_doctrine_history"', b'"faith_doctrine_history"',
        b'"played_legacy"', b'"sources"', b'"player_death"']


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else None
    with open(PATH, "rb") as f:
        data = f.read()
    print("size", len(data))
    for k in KEYS:
        if want and want.encode("utf-8") not in k:
            continue
        i = data.find(k)
        print("=" * 70)
        print(k.decode("utf-8"), "first offset", i)
        if i >= 0:
            print(data[i:i + 600].decode("utf-8", "replace"))
        j = data.rfind(k)
        if j != i:
            print("--- last offset", j)
            print(data[j:j + 600].decode("utf-8", "replace"))
    # every occurrence offset (keys may appear nested / once each)
    for k in KEYS[0:3]:
        offs = []
        p = 0
        while True:
            p = data.find(k, p)
            if p < 0:
                break
            offs.append(p)
            p += 1
        print(k.decode("utf-8"), "occurrences", len(offs), offs[:6])


if __name__ == "__main__":
    main()
