# -*- coding: utf-8 -*-
"""马克龙：从熔件裸文本里抽角色对象 (不解析 JSON，省 1–3 分钟整载)。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_char_slice.py 45136 12278 43961 38679
"""
import re
import sys

PATH = r"D:\Roman\output\马克龙\data\melt_879_01_01.json"


def main():
    ids = sys.argv[1:] or ["45136", "12278", "43961", "38679"]
    with open(PATH, "rb") as fp:
        blob = fp.read()
    for cid in ids:
        pat = re.compile(rb'"' + cid.encode() + rb'":\{')
        for m in pat.finditer(blob):
            seg = blob[m.start():m.start() + 6000].decode("utf-8", "replace")
            if "\"court_data\"" in seg or "\"first_name\"" in seg:
                print(f"===== {cid} @ {m.start()} =====")
                print(seg[:3000])
                print()
                break


if __name__ == "__main__":
    sys.exit(main())
