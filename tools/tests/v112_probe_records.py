# -*- coding: utf-8 -*-
"""v112 只读探针：打印一份战役缓存里若干角色的关键字段。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_records.py <缓存文件> <cid> [cid...]
"""
import io
import json
import os
import sys

FIELDS = ("name_zh", "first_name", "name_full", "birth", "female", "culture",
          "culture_history", "languages", "family", "death")


def main():
    path = sys.argv[1]
    cids = sys.argv[2:]
    with io.open(path, encoding="utf-8") as fp:
        cache = json.load(fp)
    chars = cache.get("characters") or {}
    for c in cids:
        rec = chars.get(str(c)) or {}
        print("\n== %s ==" % c)
        for k in FIELDS:
            print("   %-18s %s" % (k, json.dumps(rec.get(k), ensure_ascii=False)))
        th = rec.get("trait_history") or {}
        print("   %-18s %s" % ("twin?", "twin" in th))
    return 0


if __name__ == "__main__":
    sys.exit(main())
