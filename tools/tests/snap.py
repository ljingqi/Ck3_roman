# -*- coding: utf-8 -*-
"""facts 快照（提速基建）：载一次熔件，把「核对所需的一切」落成小 JSON。

用法：
    & tools\\py.ps1 tools\\tests\\snap.py <家族文件夹> <玩家id> <as_of> [十年序号] [--assert] [--pin-last-date]
    ｜ as_of 传 final 表示终传/在世传（as_of=None）
    ｜ --assert 顺手跑 tools/tests/verify_fast.py — 一次熔件加载同时拿到快照与回归结论，
      省掉「为看一眼结果再整载一次」的反覆（本会话最大的时间浪费）
    ｜ --pin-last-date 把 cache.last_date 钉到 as_of（复现当初生成该篇时的提示词面：
      facts 的 skip_detail 以 last_date 判定「as_of 早于末档」而略去直辖明细）
    ｜ v82: 终传类快照自动按 `pipeline.tail_state_applies` 复现实跑面 —— 除载入
      `cache.last_date` 那一档 (传 --melt= 可钉住)，再载入终了日**之后**那一档，
      只把它的头衔旗标 (`_merge_tail_title_flags`) 并进来。不这样做，开府/上皇这类
      只在终了日成立的词在快照里出现、在实跑里缺席（1006 终传「幕府将军」即此例）。
    例：& tools\\py.ps1 tools\\tests\\snap.py 周氏 38673 888.1.1 2 --assert

产物（output/<家族>/data/，与 melt/cache 同目录，已被 .gitignore 覆盖）：
    snap_<pid>_<as_of>[_d<N>].json   事实 + 各篇 blocks + 逐请求 messages + 少量熔件小表

为什么要有它：熔件均值 176MB（最大 245MB），`load_melt()` 单档 ≈6s（v49 提速后；
v44 前是 15–18s，更早的「1–3 分钟」是过时口径，见 docs/研究_v49_加载性能与优化.md），
迭代核对时反复整载仍是可观开销。快照只有
几十到几百 KB，`tools/tests/verify_fast.py` 可秒级断言事实面与提示词面。
"""
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    do_era = "--era" in sys.argv
    # --name=<stem>: 自定义快照名 (对照实验用, 如 snap_head_878)
    out_name = ""
    melt_pick = ""
    for a in sys.argv[1:]:
        if a.startswith("--name="):
            out_name = a.split("=", 1)[1]
        # --melt=<文件名>: 指定熔件 (v36: 终传实跑用的是 cache.last_date 那一份,
        # 而目录里可能有更晚的档 — 核对实跑面时必须能钉住熔件)
        elif a.startswith("--melt="):
            melt_pick = a.split("=", 1)[1]
    if len(argv) < 3:
        print(__doc__)
        return 2
    folder, pid = argv[0], int(argv[1])
    as_of = None if argv[2] in ("final", "none", "-") else argv[2]
    decade = int(argv[3]) if len(argv) > 3 else None
    data = os.path.join(ROOT, "output", folder, "data")
    cache_path = os.path.join(data, f"player_{pid}.json")
    melts = sorted(x for x in os.listdir(data)
                   if x.startswith("melt_") and "_idx" not in x
                   and x.endswith((".json", ".json.gz", ".json.xz")))
    if not melts:
        print(f"找不到熔件: {data}")
        return 2
    melt_name = melt_pick or melts[-1]
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
    # --era: 与 pipeline.generate_bio 的重生成路径同口径 —— 旧十年用该日那一档熔件
    # (decade_era_melt) + era_view 截断视图 (教名/直辖/政体按该日), 快照才等于实跑面。
    era_used = ""
    if do_era and as_of:
        import pipeline as _pl
        p_era, d_era = _pl.decade_era_melt(llm.load_config(), cache, as_of)
        if p_era:
            if not melt_pick:
                melt_path, melt_name = p_era, os.path.basename(p_era)
            era_used = d_era
    print(f"载入熔件 {melt_name} …" + (f" (时代渲染 {era_used})" if era_used else ""),
          flush=True)
    melt = cl.load_melt(melt_path)
    if era_used:
        cache = cl.era_view(cache, melt, era_used)
    # v82: 与 pipeline.generate_bio 同口径 —— 终了日之后那一档的头衔旗标并进来
    # (开府 shunog_flag / 上皇 joko_flag 只在那一档存在)。--melt= 已钉住同一档时跳过。
    tail_used = ""
    try:
        import pipeline as _pl
        _cfg = llm.load_config()
        if _pl.tail_state_applies(cache):
            _tp = _pl.tail_melt_candidate(_cfg, cache)
            if _tp and os.path.abspath(_tp) != os.path.abspath(melt_path):
                # 只取头衔段 (cl.load_melt_landed_titles ≈ 段级读取), 不必整载那一档
                if _pl._merge_tail_title_flags(melt, cl.load_melt_landed_titles(_tp)):
                    tail_used = os.path.basename(_tp)
                    print(f"  终了状态: 头衔旗标按 {tail_used} 并入", flush=True)
    except Exception as e:
        print(f"  终了状态并入失败: {e}", flush=True)
    # v44 (问题2): 同战役全部传主缓存 (传主链事实源) —— 与 pipeline.generate_bio
    # 实跑面一致, 否则快照缺少「承继/后任」行
    campaign = {}
    for fn in os.listdir(data):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        try:
            c = json.load(open(os.path.join(data, fn), encoding="utf-8"))
        except Exception:
            continue
        if c.get("playthrough_id") == cache.get("playthrough_id"):
            campaign[int(m.group(1))] = c
    facts = F.build_facts(cache, melt, names, as_of=as_of, decade=decade,
                          campaign=campaign or None)
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
        # v41: schema 2 = 含 v41 传输面 (政体变更/宗支/共治者键与 secrets 新键集);
        # verify_fast 的 [V41] 组对 schema<2 的旧快照整组 SKIP。
        # v56: schema 3 = 含 v56 传输面 (列传共享前缀改称【主角】/加冕句带 host 与头衔/
        # 战斗俘获行/出狱缘由); 对 schema<3 的旧快照, v56 各组整组 SKIP。
        # v88: schema 4 = 含 v88 传输面 (删「允许/禁止教义」与 rite_tenets 键, 增
        # holy_orders / forbidden_tenets / vassal_tenets, 个人教义进各角色档案行,
        # 礼仪志纪事块改「纪事·修会与教众」); verify_v87 的 [7]/[附] 两组对
        # schema>=4 SKIP, 改由 tools/tests/verify_v88.py 断言。
        # v90: schema 5 = 含 v90 传输面 (概览「见证加冕」按记忆持有人判方向;
        # 档案生卒地出词改「生于/死于」; 逐人档案去「兄弟姊妹」栏、条目改省主语版;
        # 礼仪志「个人教义沿革」与「修会」移入纪事 ⇒ 本事恒有两个板块);
        # verify_v88/v89 的礼仪志块面断言按 schema>=5 分支, 见 tools/tests/verify_v90.py。
        # v95: schema 6 = 含 v95 传输面 (六问) —— ①战事句在记忆 `war_cb` 落 fallback 时
        # 由缓存 `war_history` 回查真 CB (对立教宗那战写「以扶立对立教宗为名」);
        # ②《礼仪志》第三板块「纪事·枢机团与教宗选举」+ facts 新键 `papal_election`;
        # ③主角档案不再写「个人教义」(与《礼仪志》重复, 见 facts.py 该字段注释);
        # ④教育记忆隔日重复折一 (同一次受学不再出两条);
        # ⑤承继句补死法 (「于当日溺死」); ⑥连坐处死由日级改人级判据。
        # verify_v88 S8b / verify_v90 S5 的档案与板块断言按 schema>=6 分支。
        # v96: schema 7 = 含 v96 传输面 (三问) —— ①《礼仪志》删「禁忌个人信条」整块与
        # facts 键 `forbidden_tenets` (该秘密不带教义键, 反查出的教义名与年份都不可靠);
        # ②《礼仪志》开篇的「礼仪领袖」与「核心教义」两行改按 as_of 取 (旧稿取末档现值,
        # 用末档缓存重跑十年篇时会把 946 年即位的教宗与 947/950 才换的教义写进 935 年);
        # ③疾病动态名去「称号，名字」的逗号 (「皇帝，洪天贵福热」→「皇帝洪天贵福热」)。
        # 见 tools/tests/verify_v96.py; verify_v88 S3 按 schema>=7 分支。
        # v100: schema 8 = 含 v100 传输面 (三问) —— ①官职与绰号回滚为直接相连
        # (「前礼部尚书书吏洪地保」, 撤销 v99 的「，」); ②《礼仪志》第三板块由
        # 「纪事·大公会议与教宗诏书」+ facts 键 `church_chronicle` 取代枢机团与教宗选举
        # (会议/诏书/大分裂/异端 + 本礼教义定夺与信条更替, 见 facts.church_chronicle_lines);
        # ③伊斯兰氏族制国名改取**家族名**并加政体门与头衔门 (行政制的 e_arabia 用头衔名
        # 「阿拉伯帝国」, 见 facts.realm_name)。见 tools/tests/verify_v100.py。
        "schema": 8,
        "meta": {
            "folder": folder, "player_id": pid, "as_of": as_of, "decade": decade,
            "melt": melt_name,
            "tail_melt": tail_used,
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
    stem = out_name or (f"snap_{pid}_{as_of or 'final'}"
                        + (f"_d{decade}" if decade else ""))
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
        print("  --assert: 跑 tools/tests/verify_fast.py …", flush=True)
        rc = subprocess.call([sys.executable,
                              os.path.join(ROOT, "tools", "verify_fast.py"),
                              out_path])
        return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
