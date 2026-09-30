# -*- coding: utf-8 -*-
"""v86 回归断言: 1.20 读档 (角色桶重复块校正)。

跑在**既有熔件**上 (不重新熔化、不跑 pipeline 子命令), 秒级~一分钟:
  & tools\py.ps1 tools\tests\verify_v86_save.py [熔件路径]

默认取 data/.tmp_probe_870_01_01.json (本轮唯一 1.20 夹具)。

断言:
  1. 三桶 (living / dead_unprunable / characters.dead_prunable) 无 list 值;
  2. all_characters 条数 == 三桶合并后的去重条数, 且 100% 为 dict;
  3. find_player 取到玩家, mem_ids_of(玩家) 非空;
  4. extract_snapshot 返回 True 且玩家记录已入缓存。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl   # noqa: E402

DEFAULT = os.path.join(ROOT, "data", ".tmp_probe_870_01_01.json")
FAILS = []


def check(name, cond, detail=""):
    mark = "OK  " if cond else "FAIL"
    print("[%s] %s%s" % (mark, name, ("  — " + detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def unit_checks():
    """合成用例 (不需熔件, 秒级): 折叠语义 + 形态异常不猜。"""
    melt = {
        "living": {"1": {"a": 1}},
        "dead_unprunable": {
            "2": [{"b": 2}, {"b": 2}],                    # 全同 → 取首
            "3": [{"c": 3, "d": None}, {"c": 9, "d": 4}],  # 有差异 → 后份只补空值
            "4": ["none"],                                 # 含非 dict → 原样
        },
        "characters": {"dead_prunable": {"5": [{"e": 5}, {"e": 5}]}},
    }
    n = cl._collapse_char_buckets(melt)
    check("合成: 折叠条数 = 3", n == 3, "n=%d" % n)
    check("合成: 全同取首", melt["dead_unprunable"]["2"] == {"b": 2},
          repr(melt["dead_unprunable"]["2"]))
    check("合成: 有差异只补空值", melt["dead_unprunable"]["3"] == {"c": 3, "d": 4},
          repr(melt["dead_unprunable"]["3"]))
    check("合成: 含非 dict 原样保留", melt["dead_unprunable"]["4"] == ["none"],
          repr(melt["dead_unprunable"]["4"]))
    check("合成: dead_prunable 亦折叠", melt["characters"]["dead_prunable"]["5"] == {"e": 5},
          repr(melt["characters"]["dead_prunable"]["5"]))
    chars = cl.all_characters(melt)
    check("合成: all_characters 全为 dict", all(type(v) is dict for v in chars.values()),
          repr(chars.get("4")))
    check("合成: 再跑一次为幂等", cl._collapse_char_buckets(melt) == 0, "")


def main():
    unit_checks()
    print()
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if not os.path.isfile(path):
        print("熔件不存在: %s" % path)
        return 2
    melt = cl.load_melt(path)

    # 1. 三桶无 list 值
    for name, bucket in cl._char_buckets(melt):
        bad = [k for k, v in bucket.items() if type(v) is list]
        check("桶 %s 无 list 条目 (n=%d)" % (name, len(bucket)), not bad,
              ("残留 %d 例, 如 %s" % (len(bad), bad[:3])) if bad else "")

    # 2. all_characters 全为 dict 且条数合理
    chars = cl.all_characters(melt)
    non = [k for k, v in chars.items() if type(v) is not dict]
    buckets = {k for _n, b in cl._char_buckets(melt) for k in b}
    check("all_characters 全为 dict (n=%d)" % len(chars), not non,
          ("非 dict %d 例" % len(non)) if non else "")
    check("all_characters 与三桶键集合一致", set(chars) == buckets,
          "桶 %d / 合并 %d" % (len(buckets), len(chars)))

    # 3. 玩家与记忆
    pid = cl.find_player(melt)
    check("find_player 取到玩家", pid is not None, "id=%s" % pid)
    if pid is not None:
        p = chars.get(str(pid)) or {}
        check("玩家条目为 dict 且有名字", bool(p.get("first_name")),
              "first_name=%r" % p.get("first_name"))
        ids = cl.mem_ids_of(p)
        check("mem_ids_of(玩家) 非空", bool(ids), "%d 条" % len(ids))
        check("family_of 正常返回 dict", isinstance(cl.family_of(p), dict))

    # 4. extract_snapshot 全链路
    if pid is not None:
        cache = cl.new_cache()
        date = ((melt.get("meta_data") or {}).get("meta_date")) or "1.1.1"
        try:
            ok = cl.extract_snapshot(cache, melt, date)
        except Exception as e:            # noqa: BLE001
            ok, err = False, e
        else:
            err = None
        check("extract_snapshot 成功", ok is True,
              ("异常 %s: %s" % (type(err).__name__, err)) if err else
              "characters=%d memories=%d" % (
                  len(cache.get("characters") or {}),
                  sum(len(r.get("memories") or [])
                      for r in (cache.get("characters") or {}).values())))
        rec = (cache.get("characters") or {}).get(str(pid)) or {}
        check("缓存内玩家记录有名字", bool(rec.get("name_zh") or rec.get("name_full")),
              "name_zh=%r" % rec.get("name_zh"))

    print()
    if FAILS:
        print("失败 %d 项: %s" % (len(FAILS), " / ".join(FAILS)))
        return 1
    print("verify_v86_save: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
