# -*- coding: utf-8 -*-
"""v112 只读探针：在一份战役缓存上普查本轮两个问题的事实面。

问题 4（母语随改宗漂移）：缓存里 `culture_history` 有多次改点的角色，第一次文化（=出生文化）
与最后一次文化是否不同；这些人的 `languages` 里是否同时含有两种文化的语言。

问题 5（双胞胎特质不写对象）：`trait_history` 含 `twin` 的角色，能否凭「同一父/母 + 同一生日」
在缓存里找到另一位同胎；能/不能各多少人。

用法: & tools\\py.ps1 tools\\tests\\v112_probe_survey.py [缓存文件]
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(ROOT, "output", "洪氏2", "data", "player_207044.json")
    with io.open(path, encoding="utf-8") as fp:
        cache = json.load(fp)
    chars = cache.get("characters") or {}
    print("缓存 %s  角色 %d 人" % (os.path.basename(path), len(chars)))

    # ---- 问题 4：文化改点 ----
    multi, both_langs, no_lang = [], [], []
    for cid, rec in chars.items():
        if not isinstance(rec, dict):
            continue
        ch = [h for h in (rec.get("culture_history") or []) if h.get("culture") is not None]
        if len(ch) < 2:
            continue
        first, last = ch[0].get("culture"), ch[-1].get("culture")
        if first == last:
            continue
        multi.append((cid, rec.get("name_zh"), ch[0].get("from"), first,
                      ch[-1].get("from"), last, rec.get("languages") or []))
    print("\n[问题4] culture_history 有 ≥2 个不同文化改点的角色: %d 人" % len(multi))
    for row in multi[:15]:
        print("   %s %s  %s(c%s) -> %s(c%s)  langs=%s" % row)

    # ---- 问题 5：双胞胎 ----
    by_birth = {}
    for cid, rec in chars.items():
        if not isinstance(rec, dict) or not rec.get("birth"):
            continue
        by_birth.setdefault(str(rec["birth"]), []).append(cid)
    twins, ok, bad = 0, 0, []
    for cid, rec in chars.items():
        if not isinstance(rec, dict):
            continue
        th = rec.get("trait_history") or {}
        if "twin" not in th:
            continue
        twins += 1
        fam = rec.get("family") or {}
        cands = set()
        for key in ("father", "mother"):
            for p in (fam.get(key) or []):
                prec = chars.get(str(p)) or {}
                cands.update(int(x) for x in ((prec.get("family") or {}).get("child") or []))
        cands.update(int(x) for x in (fam.get("siblings") or []))
        cands.discard(int(cid))
        hit = [c for c in cands
               if (chars.get(str(c)) or {}).get("birth") == rec.get("birth")]
        if hit:
            ok += 1
        else:
            bad.append((cid, rec.get("name_zh"), rec.get("birth"),
                        sorted(cands)[:6]))
    print("\n[问题5] 持 twin 特质者 %d 人；同父/母且同生日可定位 %d 人，定位不到 %d 人"
          % (twins, ok, len(bad)))
    for row in bad[:15]:
        print("   定位不到: %s" % (row,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
