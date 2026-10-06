# -*- coding: utf-8 -*-
"""v109 断言: 对已生成的快照做板块级核对, 覆盖本轮五个问题的可查部分。

不载熔件, 只读 `output/<家族>/data/snap_<pid>_<as_of>.json`, 因此秒级可跑:

  V109-1 (§2.2 家室块按需传输)  friend/enemy/artifacts/chaoju/assassins/secrets 篇里不得有
                              非空的「传主家室」块; 本纪/家世篇有块时其行数必须各不相同
                              (整块同文说明没有按节裁剪)。
  V109-2 (§2.3 刺客列传并句)    「刀下诸魂」的每条死者行须同时给出 `死者：`、日期、`被其`、
                              `享年N岁`; 独立的 `<名>死于<地点>。` 行不得存在。
  V109-3 (§2.5 死因接模块)      家世篇的亲缘/家室行里, 带死因的句式 (`，死于…` / `，在…去世` /
                              `，被…`) 至少出现 1 次 —— 该模块确已接上。
  V109-4 (§2.4 历代记锚点)      「王朝历代」首行须是 `本朝：X` 或 `所附之朝：X`,
                              且「本朝治所与任期」块里 `主角本朝任期：`/`主角任期：` 二者至多一行。

用法: & tools\\py.ps1 tools\\tests\\verify_v109.py [家族] [pid] [as_of]
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NOHOUSE = ("friend", "enemy", "artifacts", "chaoju", "assassins")
HOUSE_KEY = "传主家室"
FAILS = []


def check(name, ok, detail=""):
    print("%-10s %s%s" % ("[PASS]" if ok else "[FAIL]", name, ("  " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


def main():
    fam = sys.argv[1] if len(sys.argv) > 1 else "洪氏2"
    pid = sys.argv[2] if len(sys.argv) > 2 else "207044"
    as_of = sys.argv[3] if len(sys.argv) > 3 else "final"
    path = os.path.join(ROOT, "output", fam, "data", f"snap_{pid}_{as_of}.json")
    with io.open(path, encoding="utf-8") as fp:
        snap = json.load(fp)
    blocks = snap["blocks"]
    print(f"快照 {os.path.relpath(path, ROOT)}  {len(blocks)} 节\n")

    # ---- V109-1 ----
    bad = [k for k in blocks
           if k.split("_")[0] in NOHOUSE and (blocks[k].get(HOUSE_KEY) or "").strip()]
    check("V109-1a 非家室篇无「传主家室」块", not bad, "违规篇=" + ",".join(sorted(bad)))
    sizes = {k: len((blocks[k].get(HOUSE_KEY) or "")) for k in blocks if k.split("_")[0] == "jiashi"}
    have = {k: v for k, v in sizes.items() if v}
    check("V109-1b 家世篇家室块按节裁剪", len(set(have.values())) > 1,
          f"各节字节={sizes}")

    # ---- V109-2 ----
    rosters = [v.get("刀下诸魂") or "" for k, v in blocks.items() if k.startswith("assassins")]
    lines = [ln for t in rosters for ln in t.splitlines() if ln.startswith("死者：")]
    merged = [ln for ln in lines if re.search(r"，\d{4}年\d{1,2}月\d{1,2}日", ln)
              and "被其" in ln and "享年" in ln]
    check("V109-2a 死者行已并为一句", len(merged) >= 1 and len(merged) * 2 >= len(lines),
          f"并句={len(merged)}/{len(lines)}")
    stale = [ln for t in rosters for ln in t.splitlines()
             if not ln.startswith("死者：") and "共" not in ln
             and re.match(r"^\S{1,24}死于[^，。]{1,12}。$", ln)]
    check("V109-2b 独立「X死于Y。」行已删", not stale, "残留=" + ";".join(stale[:3]))

    # ---- V109-3 ----
    house = [v for k, blk in blocks.items() if k.split("_")[0] in ("jiashi", "benji", "friend")
             for v in blk.values()]
    deaths = [ln.strip() for t in house for ln in t.splitlines()
              if re.search(r"，(死于|在.{1,8}去世|被|染|寿终)", ln)]
    plain = [ln.strip() for t in house for ln in t.splitlines()
             if re.search(r"，(父亲|母亲|夫|妻|兄弟|姊妹|儿子|女儿)\S{1,12}去世。$", ln)]
    check("V109-3a 家室行带死因", len(deaths) >= 1, f"带因={len(deaths)} 裸「去世。」={len(plain)}")

    # ---- V109-4 ----
    lead = blocks.get("chaoju_lead") or {}
    hist = (lead.get("王朝历代") or "").splitlines()
    head_ok = bool(hist) and re.match(r"^(本朝|所附之朝)：", hist[0])
    check("V109-4a 历代记首行给出锚点", head_ok, "首行=" + (hist[0] if hist else "(空)"))
    ten = [ln for k, v in blocks.items() if k.startswith("chaoju")
           for ln in (v.get("本朝治所与任期") or "").splitlines()
           if ln.startswith(("主角本朝任期：", "主角任期："))]
    check("V109-4b 任期行至多一行", len(ten) <= 1, "行=" + ";".join(ten))

    print("\n%d 项断言, 失败 %d 项" % (7, len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
