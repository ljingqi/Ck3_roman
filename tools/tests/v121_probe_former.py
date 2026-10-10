# -*- coding: utf-8 -*-
"""v121 探针（十）：「前X」标签的全量体检 —— 有多少个「前」其实那个头衔还握在手里。

判据（照抄 `_full_label` 的决策链）：
    anchor = _anchor_date(cid, self.as_of)
    cur    = official_title(cid, self.as_of)
    cur_tid= _current_title_tid(cid, anchor) if cur else None
    former = _former_high_title(cid, anchor, exclude_tid=cur_tid)
若 former 在 anchor 那一天仍是一个「未失去」的区间（loss is None），则该「前」是错的。

用法：& tools\\py.ps1 tools\\tests\\v121_probe_former.py [家族 玩家id 熔件 标题]
缺省：田所2 72914 melt_972_01_01.json "田所健二终传(as_of=None)"
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "田所2"
PID = int(sys.argv[2]) if len(sys.argv) > 2 else 72914
MELT = sys.argv[3] if len(sys.argv) > 3 else "melt_972_01_01.json"
data = os.path.join(ROOT, "output", FOLDER, "data")
cache = json.load(open(os.path.join(data, f"player_{PID}.json"), encoding="utf-8"))
names = os.path.join(data, "names.json")
if not os.path.exists(names):
    names = os.path.join(ROOT, "data", "names.json")
campaign = {}
for fn in os.listdir(data):
    m = re.match(r"player_(\d+)\.json$", fn)
    if not m:
        continue
    try:
        c = json.load(open(os.path.join(data, fn), encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        continue
    if c.get("playthrough_id") == cache.get("playthrough_id"):
        campaign[int(m.group(1))] = c
print(f"载入熔件 {MELT} …", flush=True)
melt = cl.load_melt(os.path.join(data, MELT))
facts = F.build_facts(cache, melt, names, as_of=None, decade=None,
                      campaign=campaign or None)
f = facts["_facts"]
chars = cache["characters"]

bad, ok, other = [], 0, []
for cid_s, rec in chars.items():
    try:
        cid = int(cid_s)
    except ValueError:
        continue
    if not f.name(cid):
        continue
    label = f.person_label(cid, None, "full")
    if not label or "前" not in label:
        continue
    anchor = f._anchor_date(cid, None)
    cur = f.official_title(cid, None)
    cur_tid = f._current_title_tid(cid, anchor) if cur else None
    ft = f._former_high_title(cid, anchor, exclude_tid=cur_tid)
    if ft is None:
        continue
    ivs = (f._hold_intervals(cid, anchor) or {}).get(ft) or []
    key = (f._lt.get(str(ft)) or {}).get("key") or "?"
    open_iv = [iv for iv in ivs if iv[1] is None]
    ftxt = f._former_title_text(cid, ft, anchor)
    row = (cid, f.name(cid), label, key, f._eff_rank(ft), ftxt,
           [(g, l, t) for (g, l, t) in ivs], cur, bool(open_iv),
           (rec.get("death") or {}).get("date"))
    if l_is_open := bool(open_iv):
        # 还握在手里的头衔被当成「前」
        if ftxt and f"前{ftxt}" in label:
            bad.append(row)
        else:
            other.append(row)
    else:
        ok += 1

print(f"\n带「前」字的角色 {ok + len(bad) + len(other)} 人；"
      f"其中 former 头衔在 anchor 仍「未失去」的 {len(bad) + len(other)} 人")
print("=" * 78)
print("【A】标签里确实写着「前X」、而 X 在 anchor 仍未失去 —— 判定为错")
print("=" * 78)
for (cid, nm, label, key, rank, ftxt, ivs, cur, _o, dd) in bad:
    print(f"- {nm} (id={cid}) 卒={dd} rank={rank}\n    标签={label!r}  current={cur!r}")
    print(f"    former tid={key} 名称={ftxt!r}  区间={ivs}")
print(f"\n【A】共 {len(bad)} 人")
print("=" * 78)
print("【B】former 头衔未失去、但没写进标签（`_full_label` 的层级比较挡掉了）—— 无害")
print("=" * 78)
for (cid, nm, label, key, rank, ftxt, ivs, cur, _o, dd) in other:
    print(f"- {nm} (id={cid}) 标签={label!r}  current={cur!r}  former={key}({ftxt}) rank={rank}")
print(f"\n【B】共 {len(other)} 人")
