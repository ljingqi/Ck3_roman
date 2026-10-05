# -*- coding: utf-8 -*-
"""v104 probe: pull the church situation history rows near a date from the 洪氏2 cache."""
import json
import sys

PATH = r"D:\Roman\output\洪氏2\data\player_135480.json"
NEEDLES = ["catalyst_secular_hosted_ecumenical_council",
           "catalyst_hosted_ecumenical_council",
           "catalyst_pope_declared_popular_core_tenet"]


def main():
    needle = sys.argv[1] if len(sys.argv) > 1 else "catalyst_secular_hosted_ecumenical_council"
    with open(PATH, "rb") as f:
        data = f.read()
    print("cache size", len(data))
    b = needle.encode("utf-8")
    offs, p = [], 0
    while True:
        p = data.find(b, p)
        if p < 0:
            break
        offs.append(p)
        p += 1
    print(needle, "occurrences", len(offs))
    for o in offs:
        print("-" * 60, o)
        print(data[max(0, o - 400):o + 200].decode("utf-8", "replace"))
    # locate the situation history container once and dump the few rows around 1056
    k = data.find(b'"situation_manager"')
    print("situation_manager at", k)
    if k >= 0:
        print(data[k:k + 700].decode("utf-8", "replace"))
    for n in NEEDLES:
        print(n, data.count(n.encode("utf-8")))


if __name__ == "__main__":
    main()
