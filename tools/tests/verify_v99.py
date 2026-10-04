# -*- coding: utf-8 -*-
"""v99 专项断言（秒级，跑在快照上；不载熔件）。

洪氏2 四问 + 顺带两问：
  ① 历代记末节有素材 —— 9 行 rows_detail 全 True；分 3 节各 ≥2 行；末节含治所/主角任期/本朝现任
  ② 官职与绰号直接相连（v100 回滚原「，」写法）—— 「前礼部尚书书吏洪地保」在，
     「前礼部尚书，书吏」不在
  ③ 同侪关系句自带亲缘定语 —— 洪玉英 982 年行有「姻亲兄弟洪惟良」
  ④ 历代记补「本朝现任」—— 含洪氏，且末节板块里有该行
  ⑤ 宝物志收身体部件类宝物 —— 指骨/圣指/圣齿 入「传家重宝」
  ⑥ 勋号按任期取词 —— 已交出的勋号不再挂在旧人身上

用法：
    & tools\\py.ps1 tools\\tests\\verify_v99.py [快照...]
    （缺省取 output/洪氏2/data/snap_v99.json）
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

OK = True
# v100 rolled issue ② back (the office and the nickname meet directly again), so the assertions run
# on the v100 snapshot when it exists; snap_v99.json still holds the comma and fails ② by design.
_V100 = os.path.join(ROOT, "output", "洪氏2", "data", "snap_v100.json")
DEFAULT = [_V100 if os.path.isfile(_V100)
           else os.path.join(ROOT, "output", "洪氏2", "data", "snap_v99.json")]


def check(name, cond, extra=None):
    global OK
    if not cond:
        OK = False
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f"   ← {str(extra)[:300]!r}" if extra is not None and not cond else ""))


def surface_of(snap):
    """全请求面 = 事实面 + 各板块 + 逐请求消息（与 verify_fast 同口径）。"""
    parts = [json.dumps(snap.get("facts") or {}, ensure_ascii=False),
             json.dumps(snap.get("blocks") or {}, ensure_ascii=False),
             json.dumps(snap.get("shared") or {}, ensure_ascii=False)]
    for m in snap.get("messages") or []:
        parts.append(json.dumps(m, ensure_ascii=False))
    return "\n".join(parts)


def blocks_text(snap, prefix):
    out = []
    for k, secs in (snap.get("blocks") or {}).items():
        if not k.startswith(prefix):
            continue
        for _sec, body in (secs or {}).items():
            out.append(body or "")
    return "\n".join(out)


def run(path):
    print(f"\n===== {os.path.relpath(path, ROOT)}")
    snap = json.load(open(path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    surface = surface_of(snap)
    realm = facts.get("realm") or {}
    dc = realm.get("dynasty_chronicle") or {}
    periods = dc.get("periods") or []

    # ① 历代记行与分节
    rows = [r for p in periods for r in (p.get("rows") or [])]
    dets = [d for p in periods for d in (p.get("rows_detail") or [])]
    check("① 历代记有 9 行", len(rows) == 9, len(rows))
    check("① rows_detail 全为 True（末节不会掉素材）",
          bool(dets) and all(dets), dets)
    last = [r for r in rows if "尼各老" in r and "975年9月24日" in r]
    check("① 传主自己的行有卒年、享年、死法与在位年数",
          bool(last) and all(x in last[-1] for x in
                             ("卒999年7月7日", "享年82岁", "中风而亡", "在位24年")),
          last[-1:] or rows[-1:])
    chaoju = [k for k in blocks if k.startswith("chaoju")]
    check("① 历代记分 lead + 3 节纪事",
          sorted(chaoju) == ["chaoju_lead", "chaoju_mid1", "chaoju_mid2", "chaoju_mid3"],
          sorted(chaoju))
    for k in ("chaoju_mid1", "chaoju_mid2", "chaoju_mid3"):
        body = (blocks.get(k) or {}).get("王朝历代·纪事") or ""
        n = len([x for x in body.split("\n") if x.strip()])
        check(f"① {k} 纪事 ≥2 行", n >= 2, n)

    # ④ 末节补齐疆域、任期与现任
    mid3 = blocks.get("chaoju_mid3") or {}
    close = mid3.get("本朝疆域") or ""
    check("④ 末节有治所", "治所：罗马" in close, close[:120])
    check("④ 末节有主角任期且无「至今」",
          "主角本朝任期：975年9月24日–999年7月7日" in close, close[:200])
    holder = mid3.get("本朝现任") or ""
    check("④ 末节有「本朝现任」行且点出洪氏", "洪氏" in holder, holder)
    check("④ 现任行指出其后传主仍归洪氏", "其后传主之位归于洪氏" in holder, holder)
    check("④ 现任行无括注同位语", "（" not in holder, holder)

    # ② 官职与绰号（v100 回滚：983ae6a 的「，」分支撤销，回到直接相连）
    check("② 官职与绰号直接相连", "前礼部尚书书吏洪地保" in surface)
    check("② 不再出现「前礼部尚书，书吏」", "前礼部尚书，书吏" not in surface)
    check("② 教宗与绰号直接相连", "教宗欢乐者尼各老" in surface)

    # ③ 同侪关系句的亲缘定语
    check("③ 洪玉英 982 年行带「姻亲兄弟洪惟良」",
          "982年7月11日，与姻亲兄弟洪惟良结为好友。" in surface)
    check("③ 结仇句的定语按本句主语取词（妻子，非儿媳）",
          "与妻子潘顺谦结仇。" in surface)

    # ⑤ 宝物志收身体部件类宝物
    art = blocks_text(snap, "artifacts")
    for nm in ("圣巴特利爵的指骨", "圣伯多禄的圣指", "圣伯多禄的圣齿"):
        check(f"⑤ 宝物志收「{nm}」", nm in art, art[:200])

    # ⑥ 勋号任期
    check("⑥ 已交出的勋号不再挂在旧人身上", "枢机神之捍卫者道方" not in surface)

    # 全篇：无「负二十一年」式凭空在位年数
    check("回归：传输面无「负」年数", "为负" not in surface)


def main():
    paths = sys.argv[1:] or DEFAULT
    for p in paths:
        if not os.path.isfile(p):
            print(f"跳过（缺快照）：{p}")
            continue
        run(p)
    print("\n" + "=" * 60)
    print("结果: " + ("全部通过" if OK else "存在 FAIL"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
