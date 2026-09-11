# -*- coding: utf-8 -*-
"""马克龙十问：熔件裸扫描（不解析 JSON，只按字节找键）— 找 hook 相关键。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_macron_scan.py
"""
import re
import sys

PATH = r"D:\Roman\output\马克龙\data\melt_879_01_01.json"


def main():
    pat = re.compile(rb'"[a-z_0-9]*hook[a-z_0-9]*"')
    counts = {}
    with open(PATH, "rb") as fp:
        prev = b""
        while True:
            chunk = fp.read(1 << 22)
            if not chunk:
                break
            data = prev + chunk
            for m in pat.finditer(data):
                k = m.group(0).decode("ascii", "replace")
                counts[k] = counts.get(k, 0) + 1
            prev = data[-64:]
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"{v:8d}  {k}")
    print(f"共 {len(counts)} 种 hook 键")


if __name__ == "__main__":
    sys.exit(main())
