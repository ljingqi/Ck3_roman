"""v122 第5问取证: 岚珠(67220811) 在 1082.2.16 的御前会议席名走的是臂链还是键名猜测,
以及她那一日的政体从哪来。

用法: & tools\py.ps1 tools\tests\v122_probe_council.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402
import localization as L  # noqa: E402

DATA = os.path.join(ROOT, "output", "田所2", "data")
PID = 67220811
AS_OF = "1082.2.16"
MELT = "melt_1082_01_01.json"
LOG = os.path.join(ROOT, "logs", "v122_probe_council.txt")
buf = []


def w(s=""):
    buf.append(str(s))
    print(str(s), flush=True)


def main():
    cache = json.load(open(os.path.join(DATA, f"player_{PID}.json"), encoding="utf-8"))
    mp = os.path.join(DATA, MELT)
    if not os.path.isfile(mp):
        mp = os.path.join(DATA, "melt_1083_01_01.json")
    melt = cl.load_melt(mp)
    w(f"熔件: {os.path.basename(mp)}")
    f = F.Facts(cache, melt, os.path.join(ROOT, "data", "names.json"),
                as_of=AS_OF, decade=None)
    rec = (f.cache.get("characters") or {}).get(str(PID)) or {}
    w(f"缓存 landed.government = {(rec.get('landed') or {}).get('government')!r}")
    w(f"缓存 landed.council = {(rec.get('landed') or {}).get('council')!r}")
    w(f"_character_government(cid, as_of) = {f._character_government(PID, AS_OF)!r}")
    w("char_government_history:")
    for h in (cache.get("char_government_history") or {}).get(str(PID)) or []:
        w(f"   {h}")
    w(f"_is_independent(cid, as_of) = {f._is_independent(PID, AS_OF)!r}")
    w(f"_top_rank_now(cid) = {f._top_rank_now(PID)}")
    w(f"culture_template = {f.culture_template(PID)!r} name_list = "
      f"{(f._culture_entry(PID, AS_OF) or {}).get('name_list')!r}")
    w(f"_council_scope() = {f._council_scope()!r}")
    w(f"council_line() = {f.council_line()!r}")
    w("")
    seats = (rec.get("landed") or {}).get("council") or []
    act = (melt.get("council_task_manager") or {}).get("active") or {}
    w("逐席: 臂链词 / 键名猜测词")
    for sid in seats:
        e = act.get(str(sid)) or {}
        if not isinstance(e, dict):
            w(f"  seat {sid}: 无 active 记录")
            continue
        owner = e.get("court_owner")
        sc = f._council_seat_scope(owner if isinstance(owner, int) else PID,
                                   e.get("owner"), AS_OF)
        pos = ((f._council_tasks or {}).get("tasks") or {}).get(e.get("type") or "") or ""
        desc = L.council_name_desc(f._council_names, pos, sc)
        arm = f.council_seat_arm_word(e, PID, AS_OF)
        gov, imperial = f._council_scope()
        fb = L.council_seat_word(f.table, f._council_tasks, e.get("type") or "", gov, imperial)
        w(f"  {e.get('type')} owner={e.get('owner')} court_owner={owner} pos={pos!r}")
        w(f"      scope={sc}")
        w(f"      desc={desc!r} -> arm={arm!r} ; 键名回退={fb!r}")


main()
open(LOG, "w", encoding="utf-8").write("\n".join(buf))
print(f"written {LOG}")
