# -*- coding: utf-8 -*-
"""v121 探针（十一）：男爵头衔的三种落点 —— 现口径 vs HEAD 口径。

`_full_label` 新增收尾：既没有官职词、也没有「已失去的头衔」时，写 anchor 当天仍握在手里的
领地头衔（含男爵）。HEAD 口径下这类人只剩一个裸名（第4问的 `田所健六`）。

整载一次熔件，把全缓存角色逐一按
    现口径     person_label(full)
    HEAD 口径  把 `_held_landed_title` 短路成 None 后 person_label(full)
对照，列出全部改变的角色，并给出两种口径下带「前」的角色数。
判据：`_former_high_title` 只认已失去的头衔，所以「前」不该出现在仍握在手里的头衔上。

用法：& tools\\py.ps1 tools\\tests\\v121_probe_baron.py [家族 玩家id 熔件]
缺省：田所2 72914 melt_972_01_01.json
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

_HEAD = f._held_landed_title


def label(cid, held):
    """held=True → 现口径；held=False → HEAD（把 `_held_landed_title` 短路成 None）。"""
    f._held_landed_title = _HEAD if held else (lambda c, a: None)
    f._label_cache.clear()
    out = f.person_label(cid, None, "full")
    f._held_landed_title = _HEAD
    return out


changed, bare, qian_new, qian_head = [], [], [], []
total = 0
for cid_s in chars:
    try:
        cid = int(cid_s)
    except ValueError:
        continue
    if not f.name(cid):
        continue
    total += 1
    new = label(cid, True)
    old = label(cid, False)
    if "前" in new:
        qian_new.append((cid, new))
    if "前" in old:
        qian_head.append((cid, old))
    if new != old:
        anchor = f._anchor_date(cid, None)
        tid = f._held_landed_title(cid, anchor)
        key = (f._lt.get(str(tid)) or {}).get("key") or "?"
        changed.append((cid, f.name(cid), (chars[cid_s].get("death") or {}).get("date"),
                        key, f._eff_rank(tid), old, new))
    if new == f.name_with_regnal(cid, None):
        bare.append((cid, new))

print(f"缓存角色 {total} 人（有名字的）")
print("=" * 78)
print("【A】HEAD 口径是裸名、现口径补上仍握在手里的头衔 —— 本次改动命中的人")
print("=" * 78)
for (cid, nm, dd, key, rank, old, new) in sorted(changed, key=lambda r: r[1]):
    print(f"- {new}   (id={cid} 卒={dd} tid={key} rank={rank})\n     HEAD: {old!r}")
print(f"\n【A】共 {len(changed)} 人")
print("=" * 78)
print("【B】两口径下都仍是裸名（无官职、无已失去的头衔、无在手持头衔）")
print("=" * 78)
print(f"【B】共 {len(bare)} 人" + ("" if not bare else "：" + "、".join(
    nm for _c, nm in sorted(bare, key=lambda r: r[1])[:40])))
print("=" * 78)
print("【C】带「前」的角色数：HEAD 口径 %d 人 → 现口径 %d 人" % (len(qian_head), len(qian_new)))
print("=" * 78)
gone = [r for r in qian_head if r[0] not in {c for c, _l in qian_new}]
print(f"【C1】现口径下不再带「前」的 {len(gone)} 人（本改动把在手持头衔从「前」改回不带「前」）")
for cid, lb in sorted(gone, key=lambda r: r[1])[:30]:
    print(f"- {lb}   (id={cid}) → {label(cid, True)!r}")
newq = [r for r in qian_new if r[0] not in {c for c, _l in qian_head}]
print(f"\n【C2】现口径下新增带「前」的 {len(newq)} 人（应为 0）")
for cid, lb in newq[:30]:
    print(f"- {lb}   (id={cid})")
print("=" * 78)
print("【D】点检（第4问当事人与同族男爵）")
print("=" * 78)
for nm, cid in (("田所健六", 50359374), ("田所千", 50430089)):
    anchor = f._anchor_date(cid, None)
    tid = f._held_landed_title(cid, anchor)
    rec = chars.get(str(cid)) or {}
    ivs = (f._hold_intervals(cid, anchor) or {}).get(tid) or []
    print(f"- {nm} (id={cid}) 卒={(rec.get('death') or {}).get('date')} "
          f"anchor={anchor}")
    print(f"    现口径 = {label(cid, True)!r}")
    print(f"    HEAD  = {label(cid, False)!r}")
    print(f"    _held_landed_title = {tid} "
          f"({(f._lt.get(str(tid)) or {}).get('key')!r} rank={f._eff_rank(tid)}) "
          f"区间={ivs} _title_still_his={f._title_still_his(cid, ivs, anchor)}")
    print(f"    _former_high_title = {f._former_high_title(cid, anchor)!r}")
