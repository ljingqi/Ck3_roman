# -*- coding: utf-8 -*-
"""马克龙十问：熔件结构侦察（一次整载，落多份报告）。

用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_macron_melt.py
产物：tools/out_macron/*.json|txt
"""
import json
import os
import sys

ROOT = r"D:\Roman"
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

MELT = r"D:\Roman\output\马克龙\data\melt_879_01_01.json"
OUT = os.path.join(ROOT, "tools", "out_macron")
PLAYER = 38677


def dump(name, obj):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as fp:
        if isinstance(obj, str):
            fp.write(obj)
        else:
            json.dump(obj, fp, ensure_ascii=False, indent=1)
    print(f"  写入 {p}")


def keys_with(obj, word, depth=0, path="", out=None, maxdepth=4):
    if out is None:
        out = []
    if depth > maxdepth:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if word in str(k).lower():
                out.append((path + "/" + str(k), type(v).__name__,
                            (list(v.keys())[:12] if isinstance(v, dict) else
                             (v if isinstance(v, (int, float, str, bool, type(None))) else
                              f"[{type(v).__name__} len={len(v)}]"))))
            keys_with(v, word, depth + 1, path + "/" + str(k), out, maxdepth)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            keys_with(v, word, depth + 1, f"{path}[{i}]", out, maxdepth)
    return out


def main():
    print(f"载入 {MELT} …", flush=True)
    melt = cl.load_melt(MELT)
    print("载入完成", flush=True)

    dump("top_keys.json", sorted(melt.keys()))

    hit = keys_with(melt, "hook")
    dump("hook_paths.txt", "\n".join(f"{a}\t{b}\t{c}" for a, b, c in hit[:400]))
    print(f"  hook 路径 {len(hit)} 条")

    # 玩家角色对象
    for bucket in ("living", "dead_unprunable", "dead_prunable"):
        b = melt.get(bucket) or {}
        if str(PLAYER) in b:
            dump(f"player_{bucket}.json", b[str(PLAYER)])
            print(f"  玩家在 {bucket}")

    # 角色桶结构预览
    for bucket in ("living",):
        b = melt.get(bucket) or {}
        ks = sorted(b.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)
        dump(f"{bucket}_sample_keys.json", ks[:20])
        print(f"  {bucket} 人数 {len(b)}")

    dump("melt_keys_of_interest.txt", "\n".join(
        f"{k}\t{type(v).__name__}" for k, v in sorted(melt.items())))


if __name__ == "__main__":
    sys.exit(main())
