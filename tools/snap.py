# -*- coding: utf-8 -*-
"""facts 快照（提速基建）：载一次熔件，把「核对所需的一切」落成小 JSON。

用法：
    & D:\\Roman\\tools\\py.ps1 tools\\snap.py <家族文件夹> <玩家id> <as_of> [十年序号] [--assert] [--pin-last-date]
    ｜ as_of 传 final 表示终传/在世传（as_of=None）
    ｜ --assert 顺手跑 tools/verify_fast.py — 一次熔件加载同时拿到快照与回归结论，
      省掉「为看一眼结果再整载一次」的反覆（本会话最大的时间浪费）
    ｜ --pin-last-date 把 cache.last_date 钉到 as_of（复现当初生成该篇时的提示词面：
      facts 的 skip_detail 以 last_date 判定「as_of 早于末档」而略去直辖明细）
    例：& tools\\py.ps1 tools\\snap.py 周氏 38673 888.1.1 2 --assert

产物（output/<家族>/data/，与 melt/cache 同目录，已被 .gitignore 覆盖）：
    snap_<pid>_<as_of>[_d<N>].json   事实 + 各篇 blocks + 逐请求 messages + 少量熔件小表

为什么要有它：熔件 100–125MB，`load_melt()` 每次要 1–3 分钟；迭代核对时反复整载是
本会话最大的时间浪费（见 tools/enc.ps1 顶部与 verify_fast.py 的说明）。快照只有
几十到几百 KB，`tools/verify_fast.py` 可秒级断言事实面与提示词面。
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import biography as bio  # noqa: E402
import cache_lib as cl   # noqa: E402
import facts as F        # noqa: E402
import llm               # noqa: E402
import localization as L  # noqa: E402

_CODE_FILES = ("facts.py", "biography.py", "cache_lib.py", "localization.py",
               "llm.py", "style.py", "flavorization.py")


def _code_meta():
    out = {}
    for fn in _CODE_FILES:
        p = os.path.join(ROOT, fn)
        try:
            st = os.stat(p)
            out[fn] = [int(st.st_size), int(st.st_mtime)]
        except OSError:
            pass
    return out


def _melt_tables(f, facts):
    """核对需要的小表（避免为了一个字段再整载熔件）。"""
    melt = f.melt
    pid = f.cache.get("player_id")
    rec = (f.cache.get("characters") or {}).get(str(pid)) or {}
    ld = rec.get("landed") or {}
    caps = {}
    for t in (ld.get("domain") or []):
        cap = (f._lt.get(str(t)) or {}).get("capital")
        if isinstance(cap, int):
            caps[str(t)] = cap
    epi = {}
    for eid, e in ((melt.get("epidemics") or {}).get("database") or {}).items():
        if not isinstance(e, dict):
            continue
        epi[str(eid)] = {
            "name": e.get("name"), "type": e.get("type"),
            "intensity": e.get("intensity"), "creation_date": e.get("creation_date"),
            "start_province": e.get("start_province"),
            "num_infected_provinces": e.get("num_infected_provinces"),
            "infections": sorted((e.get("infections") or {}).keys(), key=str)[:400],
        }
    act = {}
    for sid in (ld.get("council") or []):
        e = ((melt.get("council_task_manager") or {}).get("active") or {}).get(str(sid))
        if isinstance(e, dict):
            act[str(sid)] = {"type": e.get("type"), "owner": e.get("owner"),
                             "court_owner": e.get("court_owner")}
    return {
        "player_provinces": sorted(
            ({caps[k] for k in caps}
             | {ld.get("domicile_province"), f.character_location_province(pid)})
            - {None}),
        "domain_capitals": caps,
        "epidemics": epi,
        "council_active": act,
        "cp_scope": f.court_position_scope(),
        "council_seats": [
            {"type": (act.get(sid) or {}).get("type"),
             "word": f.council_seat_word((act.get(sid) or {}).get("type") or ""),
             "owner": (act.get(sid) or {}).get("owner")}
            for sid in (ld.get("council") or [])],
    }


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_assert = "--assert" in sys.argv
    pin_last = "--pin-last-date" in sys.argv
    if len(argv) < 3:
        print(__doc__)
        return 2
    folder, pid = argv[0], int(argv[1])
    as_of = None if argv[2] in ("final", "none", "-") else argv[2]
    decade = int(argv[3]) if len(argv) > 3 else None
    data = os.path.join(ROOT, "output", folder, "data")
    cache_path = os.path.join(data, f"player_{pid}.json")
    melts = sorted(x for x in os.listdir(data)
                   if x.startswith("melt_") and "_idx" not in x and x.endswith(".json"))
    if not melts:
        print(f"找不到熔件: {data}")
        return 2
    melt_name = melts[-1]
    melt_path = os.path.join(data, melt_name)
    names = os.path.join(data, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    cache = json.load(open(cache_path, encoding="utf-8"))
    # --pin-last-date: 复现「当初生成这篇传记时的缓存状态」——facts 的 skip_detail
    # 以 last_date 判定「as_of 早于末档」而丢掉直辖/封臣明细, 缓存推进后再跑旧 as_of
    # 就看不到那几行了; 把 last_date 钉到 as_of 即可重现原始提示词面 (仅诊断用)。
    if pin_last and as_of:
        cache["last_date"] = as_of
        print(f"  --pin-last-date: last_date → {as_of}", flush=True)
    print(f"载入熔件 {melt_name} …", flush=True)
    melt = cl.load_melt(melt_path)
    facts = F.build_facts(cache, melt, names, as_of=as_of, decade=decade)
    f = facts["_facts"]
    cfg = {"max_tokens": 12800}
    articles = bio.build_articles(facts, cache, cfg)
    intro = "总纲从略。"
    blocks, messages = {}, {}
    for a in articles:
        for sec in a["sections"]:
            key = f"{a['key']}_{sec['key']}"
            blocks[key] = bio._article_facts(facts, cache, a["key"], sec)
            if sec["key"] == "lead":
                msgs = bio.build_lead_messages(a, facts, cache, intro, cfg)
            else:
                msgs = bio.build_section_messages(a, sec, facts, cache, intro, cfg)
            messages[key] = {"system": msgs[0]["content"], "user": msgs[1]["content"]}
    snap = {
        "schema": 1,
        "meta": {
            "folder": folder, "player_id": pid, "as_of": as_of, "decade": decade,
            "melt": melt_name,
            "melt_size": os.path.getsize(melt_path),
            "cache_size": os.path.getsize(cache_path),
            "loc_fingerprint": (L.source_fingerprint(llm.load_config()) or {}).get("hash"),
            "code": _code_meta(),
            "articles": [a["key"] for a in articles],
        },
        "facts": {k: v for k, v in facts.items() if k != "_facts"},
        "shared": bio._shared_facts_block(facts),
        "blocks": blocks,
        "messages": messages,
        "melt_tables": _melt_tables(f, facts),
    }
    stem = f"snap_{pid}_{as_of or 'final'}" + (f"_d{decade}" if decade else "")
    out_path = os.path.join(data, stem + ".json")
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(snap, fp, ensure_ascii=False)
    size = os.path.getsize(out_path)
    digest = hashlib.sha1(open(out_path, "rb").read()).hexdigest()[:12]
    print(f"快照已写入: {out_path} ({size:,} 字节, {digest})")
    print(f"  请求 {len(messages)} 个; 共享前缀 {len(snap['shared'])} 字符; "
          f"blocks {len(blocks)} 块; 熔件 {melt_name}")
    if do_assert:
        import subprocess
        print("  --assert: 跑 tools/verify_fast.py …", flush=True)
        rc = subprocess.call([sys.executable,
                              os.path.join(ROOT, "tools", "verify_fast.py"),
                              out_path])
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
