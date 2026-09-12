# -*- coding: utf-8 -*-
"""诊断 (只读): 乱伦隐事 (secret_incest) 的对方是谁 —— 用「同持有人的性/情记忆 + 血亲」判定。

用法: tools\\py.ps1 experiments\\diag_incest_pair.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

DATA = os.path.join(ROOT, "output", "柳特佩特", "data")
MELT = "melt_878_01_01.json"
SEX_TYPES = ("had_sex", "became_lovers", "became_soulmates", "developed_crush")
SLOTS = {"sex_partner", "new_relation", "new_soulmate"}


def main():
    melt = cl.load_melt(os.path.join(DATA, MELT))
    chars = dict(melt.get("living") or {})
    chars.update(melt.get("dead_unprunable") or {})
    db = (melt.get("character_memory_manager") or {}).get("database") or {}
    secs = ((melt.get("secrets") or {}).get("secrets")) or {}

    def name(cid):
        r = chars.get(str(cid)) or {}
        return r.get("first_name") or str(cid)

    def fam(cid):
        return (chars.get(str(cid)) or {}).get("family_data") or {}

    def kin(a, b):
        fa = fam(a)
        fb = fam(b)
        rel = []
        for key in ("father", "mother"):
            if b in (fa.get(key) or []):
                rel.append(f"{name(a)}是{name(b)}的{'父' if key == 'father' else '母'}")
        for key in ("father", "mother"):
            if a in (fb.get(key) or []):
                rel.append(f"{name(b)}是{name(a)}的{'父' if key == 'father' else '母'}")
        for key in ("child",):
            if b in (fa.get(key) or []):
                rel.append(f"{name(b)}是{name(a)}的子女")
            if a in (fb.get(key) or []):
                rel.append(f"{name(a)}是{name(b)}的子女")
        if b in (fa.get("siblings") or []) or a in (fb.get("siblings") or []):
            rel.append("同胞")
        if (fa.get("primary_spouse") == b or fa.get("spouse") == b
                or fb.get("primary_spouse") == a or fb.get("spouse") == a):
            rel.append("配偶")
        return rel

    def sex_partners(cid):
        """该角色记忆里的性/情对象集合 (带日期)。"""
        out = []
        for mid in ((chars.get(str(cid)) or {}).get("alive_data") or {}).get("memories") or []:
            m = db.get(str(mid))
            if not isinstance(m, dict):
                continue
            t = str(m.get("type") or "")
            if not t.startswith(SEX_TYPES):
                continue
            parts = m.get("participants") or {}
            for slot, v in parts.items():
                if slot in SLOTS and isinstance(v, int) and v != cid:
                    out.append((m.get("creation_date"), t, v))
        return out

    print("### secret_incest 记录 —— 逐个推对方")
    for sid, v in secs.items():
        if not isinstance(v, dict) or v.get("type") != "secret_incest":
            continue
        owner = v.get("owner")
        print("-" * 68)
        print(f"secret {sid}: owner={owner} ({name(owner)})")
        for d, t, other in sorted(sex_partners(owner)):
            rel = kin(owner, other)
            mark = "  ★血亲" if rel else ""
            print(f"    性情记忆 {d} {t} → {other} ({name(other)})"
                  f" 亲缘={rel or '无'}{mark}")
        print("    家族:", json.dumps(fam(owner), ensure_ascii=False)[:220])


if __name__ == "__main__":
    main()
