# -*- coding: utf-8 -*-
"""v116 规模评估（只用缓存 + 成稿）：成稿里「XX王子／郡主」的持有父母是否行政制封臣。

判据（全部取自存档自有字段，不猜）：
  * 父/母的 `death.liege`：等于本人 = 独立君主；他人 = 封臣
  * 父/母的 `death.liege_title`：其君主的最高头衔 id（14022 = h_china 天朝）
按 (称号前缀, 词) 汇总，给出「若按行政制封臣支改为 公子/公女」会动到的串。

用法: python -X utf8 tools/tests/v116_scope_scan.py
"""
import collections
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
CACHE = os.path.join(ROOT, "output", "洪氏2", "data", "player_207044.json")
OUT = os.path.join(ROOT, "output", "洪氏2")

PAT = re.compile(r"([\u4e00-\u9fff]{2,4})(王子|郡主)([\u4e00-\u9fff·]{2,8})")


def main():
    cache = json.load(io.open(CACHE, encoding="utf-8"))
    ch = cache["characters"]
    byname = collections.defaultdict(set)
    for cid, r in ch.items():
        for k in ("name_full", "name_zh"):
            v = r.get(k)
            if v:
                byname[str(v)].add(int(cid))
    rows = []
    files = [f for f in sorted(os.listdir(OUT)) if f.endswith(".md")]
    for fn in files:
        t = io.open(os.path.join(OUT, fn), encoding="utf-8").read()
        for m in PAT.finditer(t):
            rows.append((fn, m.group(1), m.group(2), m.group(3), m.start()))
    print("成稿 %d 篇，命中「前缀+王子/郡主+人名」 %d 处" % (len(files), len(rows)))

    stat = collections.Counter()
    detail = collections.defaultdict(list)
    unknown_name = collections.Counter()
    for fn, pre, word, nm, pos in rows:
        cands = byname.get(nm) or set()
        # 取父/母信息：任一候选的 father/mother 里出现与本人同姓者优先（不造判据，只取第一条）
        cls = "名不可考"
        if cands:
            cid = sorted(cands)[0]
            fam = (ch.get(str(cid)) or {}).get("family") or {}
            pars = [x for x in (fam.get("father") or []) + (fam.get("mother") or [])
                    if isinstance(x, int)]
            if not pars:
                cls = "无父母记录"
            else:
                tags = []
                for p in pars:
                    pr = ch.get(str(p)) or {}
                    d = pr.get("death") or {}
                    lig, lt = d.get("liege"), d.get("liege_title")
                    if lig is None:
                        tags.append("父母无卒档")
                    elif int(lig) == int(p):
                        tags.append("独立")
                    else:
                        tags.append("封臣@%s" % lt)
                cls = "/".join(sorted(set(tags)))
        else:
            unknown_name[nm] += 1
        stat[(pre + word, cls)] += 1
        detail[pre + word].append((fn, nm, cls))

    print("\n== 按「前缀+词」与父母身份分类（次数）")
    agg = collections.defaultdict(collections.Counter)
    for (form, cls), n in stat.items():
        agg[form][cls] += n
    for form in sorted(agg, key=lambda k: -sum(agg[k].values())):
        print("  %-8s %s" % (form, dict(agg[form])))

    print("\n== 名字对不上的（前 20）")
    for k, v in unknown_name.most_common(20):
        print("  %-10s %d" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
