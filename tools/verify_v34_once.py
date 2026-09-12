# -*- coding: utf-8 -*-
"""v34 一次性验证: **只熔化一次** —— 重建单战役缓存 + 落快照 + 跑全部断言。

用法:
    tools\\py.ps1 tools\\verify_v34_once.py [家族文件夹] [玩家id] [as_of]
    默认: 柳特佩特 38653 878.1.1

设计 (用户要求「熔化一次把所有测试做完」):
  1. 只读本战役文件夹 melt_*.json 各一次 → 重建该玩家缓存 (含 prison_history) 落盘;
  2. 用同一批熔件落 facts 快照 (含 blocks / messages);
  3. 跑 verify_v34 的全部断言 (读快照, 不碰熔件);
  4. 结论同时写 UTF-8 报告文件, 便于反复 read 而不必重跑。
"""
import glob
import io
import json
import os
import sys

def _repo_root():
    """仓库根: 从本文件向上找到含 facts.py 的目录 (兼容 tools/ 或 experiments/ 放置)。"""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        if os.path.isfile(os.path.join(d, "facts.py")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()


ROOT = _repo_root()
sys.path.insert(0, ROOT)
import cache_lib as cl          # noqa: E402
import facts as F               # noqa: E402
import biography as bio         # noqa: E402
import localization as L        # noqa: E402
import llm                      # noqa: E402

FOLDER = sys.argv[1] if len(sys.argv) > 1 else "柳特佩特"
PID = int(sys.argv[2]) if len(sys.argv) > 2 else 38653
ASOF = sys.argv[3] if len(sys.argv) > 3 else "878.1.1"
DATA = os.path.join(ROOT, "output", FOLDER, "data")
CACHE_P = os.path.join(DATA, "player_%d.json" % PID)
NAMES = os.path.join(ROOT, "data", "names.json")
SNAP = os.path.join(DATA, "snap_%d_%s_d1.json" % (PID, ASOF))
REPORT = os.path.join(ROOT, "logs", "verify_v34_report.txt")

report = []


def say(s=""):
    report.append(str(s))


def main():
    cfg = llm.load_config()
    melts = []
    for p in sorted(glob.glob(os.path.join(DATA, "melt_*.json"))):
        if "_idx" in p:
            continue
        m = os.path.basename(p)
        d = m[len("melt_"):-len(".json")].replace("_", ".")
        d = ".".join(str(int(x)) for x in d.split("."))
        melts.append((cl.date_key(d), d, p))
    melts.sort()
    say(f"# v34 一次性验证: {FOLDER}/{PID} as_of={ASOF}")
    say(f"熔件 {len(melts)} 份 (只读一次)")

    # ---- ① 重建缓存 (保留 bio_* 字段) ----
    prev = {}
    if os.path.isfile(CACHE_P):
        try:
            prev = json.load(open(CACHE_P, encoding="utf-8"))
        except Exception:
            prev = {}
    cache = cl.new_cache()
    for k in ("player_death", "bio_generated", "bio_decades", "playthrough_id",
              "output_folder"):
        if prev.get(k):
            cache[k] = prev[k]
    for _dk, d, p in melts:
        melt = cl.load_melt(p)
        cl.extract_snapshot(cache, melt, d)
        del melt
    cache["output_folder"] = FOLDER
    cache["player_id"] = PID
    cl.save_cache(cache, CACHE_P)
    say(f"缓存已重建: {CACHE_P} (相关人物 {len(cache['characters'])}, "
        f"prison_history 记 {sum(1 for r in cache['characters'].values() if r.get('prison_history'))} 人)")

    # ---- ② 落快照 (用同一批熔件里的最后一份) ----
    last = melts[-1][2]
    melt = cl.load_melt(last)
    facts = F.build_facts(cache, melt, NAMES, as_of=ASOF, decade=1)
    articles = bio.build_articles(facts, cache, cfg)
    intro = "（验证模式: 总纲从略）"
    shared = bio._shared_facts_block(facts)
    blocks = {}
    messages = {}
    for a in articles:
        for sec in a["sections"]:
            key = f"{a['key']}_{sec['key']}"
            blk = bio._article_facts(facts, cache, a["key"], sec)
            blocks[key] = blk
            msgs = (bio.build_lead_messages(a, facts, cache, intro, cfg)
                    if sec["key"] == "lead"
                    else bio.build_section_messages(a, sec, facts, cache,
                                                    intro, cfg))
            messages[key] = {"system": msgs[0]["content"],
                             "user": msgs[1]["content"]}
    snap = {"schema": 1,
            "meta": {
                "folder": FOLDER, "player_id": PID, "as_of": ASOF, "decade": 1,
                "melt": os.path.basename(last),
                "melt_size": os.path.getsize(last),
                "cache_size": os.path.getsize(CACHE_P),
                "loc_fingerprint": (L.source_fingerprint(cfg) or {}).get("hash"),
                "articles": [a["key"] for a in articles],
            },
            "facts": {k: v for k, v in facts.items() if k != "_facts"},
            "shared": shared, "blocks": blocks,
            "messages": messages,
            "melt_tables": {"traits": {k: v for k, v in
                                       (L.trait_names().get("traits") or {}).items()
                                       if "dick" in k or k in ("infertile",)}}}
    with open(SNAP, "w", encoding="utf-8") as fp:
        json.dump(snap, fp, ensure_ascii=False)
    say(f"快照已写入: {SNAP} (共享前缀 {len(shared)} 字符, {len(blocks)} 块)")
    del melt

    # ---- ③ 断言 (读快照, 不再碰熔件; 内联调用避免子进程管道) ----
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import verify_v34  # noqa: E402
    ok, stream = verify_v34.run(SNAP)
    say("")
    say("## 断言输出")
    say(stream.getvalue())
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:  # noqa: BLE001
        import traceback
        say("## 异常")
        say(traceback.format_exc())
        code = 2
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with io.open(REPORT, "w", encoding="utf-8") as fp:
        fp.write("\n".join(report) + "\n")
    sys.exit(code)
