# -*- coding: utf-8 -*-
"""v117 check (item 4b): a predecessor missing from the cache must still keep his surname.

`cl.display_name` needs the character's culture (name order), his house/dynasty name and his given
name. For cid 44503 none of it is in 洪光通's cache (the record is absent), so the surname 「洪」
was lost and the label read 「天皇帝堕邪者圣天贵福」. This prints every source the name path reads
and asserts the surname survives.

Usage: & tools\\py.ps1 tools\\tests\\v117_check_name.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl       # noqa: E402
import facts as F            # noqa: E402

FOLDER = "洪氏2"
PID = 17066495
MELT = "melt_1283_01_01.json"
AS_OF = "1283.9.11"
CID = 44503
DATE = "952.1.28"
LOG = os.path.join(ROOT, "logs", "v117_check_name.txt")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def main():
    data = os.path.join(ROOT, "output", FOLDER, "data")
    cache = json.load(open(os.path.join(data, f"player_{PID}.json"), encoding="utf-8"))
    melt = cl.load_melt(os.path.join(data, MELT))
    names = os.path.join(data, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, melt, names, as_of=AS_OF, decade=None, campaign=None)
    key = str(CID)
    rec = (cache.get("characters") or {}).get(key) or {}
    c = f._chars.get(key) or {}
    nj = (cl._load_names(names, melt) or {}).get(key) or {}
    w(f"[sources for cid {CID}]")
    w(f"  cache record present = {bool(rec)}"
      + (f"  name_zh={rec.get('name_zh')!r} culture={rec.get('culture')!r}"
         f" dynasty_house={rec.get('dynasty_house')!r}" if rec else ""))
    w(f"  melt character fields: culture={c.get('culture')!r} dynasty_house={c.get('dynasty_house')!r}"
      f" name={{'name_zh': {c.get('name_zh')!r}, 'name_full': {c.get('name_full')!r}}}"
      f" dead_data.date={(c.get('dead_data') or {}).get('date')!r}")
    w(f"  names.json entry: {nj}")
    hid = c.get("dynasty_house") or rec.get("dynasty_house")
    w(f"  resolved house={hid} house_name={cl.house_name_zh(melt, hid)!r}"
      f" dynasty_name={cl.dynasty_name_zh(melt, cl.dynasty_id_of(melt, hid))!r}")
    cult = c.get("culture") or rec.get("culture")
    conv = ((melt.get("culture_manager") or {}).get("cultures") or {}).get(str(cult)) or {}
    w(f"  culture {cult} -> name_order_convention={conv.get('name_order_convention')!r}"
      f" template={conv.get('culture_template')!r}")

    order = cl.resolved_name_order(cache, CID, melt=melt, chars=f._chars,
                                   memo={}, date=DATE)
    w(f"  resolved_name_order = {order!r}")
    nm = cl.display_name(cache, CID, melt=melt, names_path=names, chars=f._chars, date=DATE)
    w(f"  display_name({DATE}) = {nm!r}")
    w(f"  Facts.name({DATE}) = {f.name(CID, date=DATE)!r}")
    w(f"  person_label(full) = {f.person_label(CID, DATE, 'full')!r}")

    ok = "洪" in nm
    w(f"\n  [{'PASS' if ok else 'FAIL'}] 44503 的姓名带姓氏「洪」: {nm!r}")
    with open(LOG, "w", encoding="utf-8") as fp:
        fp.write("\n".join(buf) + "\n")
    w(f"[report] {LOG}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
