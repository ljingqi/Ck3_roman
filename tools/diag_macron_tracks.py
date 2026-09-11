# -*- coding: utf-8 -*-
"""马克龙（新两问）一次性熔件侦查：特质轨道（tracks/trait_xp_amounts）+ 监狱数据。

熔件 100MB 载一次 1-3 分钟，本脚本一次载入、分题落盘，之后用落盘 JSON 秒级复核。
产物（tools/out_macron/）：
  traits_lookup.json      索引→特质键 全表
  game_trait_tracks.json  游戏/Mod 特质定义里带 tracks 的特质 → {category, tracks:{轨道:[阈值]}}
  track_chars.json        持有「带轨道特质」的角色原始片段（traits/trait_xp_amounts/…）
  char_key_union.json     全档角色字段并集（找 prison / track / xp 相关字段名）
  prison_memories.json    记忆库中 prison 相关记忆 + 持有者
  raw_chars.json          指定角色的原始对象（主角/妻/安乔/乔乔）
用法：& D:\\Roman\\tools\\py.ps1 tools\\diag_macron_tracks.py [melt] [角色id...]
"""
import io
import json
import os
import re
import sys
import glob

ROOT = r"D:\Roman"
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402

OUT = os.path.join(ROOT, "tools", "out_macron")
MELT = sys.argv[1] if len(sys.argv) > 1 else \
    r"D:\Roman\output\马克龙\data\melt_879_01_01.json"
EXTRA_IDS = [int(x) for x in sys.argv[2:]] or [38677, 15682, 12278, 43961]

GAME = r"F:\SteamLibrary\steamapps\common\Crusader Kings III\game"
MODS = [
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\3594634592",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\2273832430",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\2227658180",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\2997587648",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\2823178539",
    r"C:\Users\Maoha\Documents\Paradox Interactive\Crusader Kings III\mod\deviants_mask_mod",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\2978257885",
    r"F:\SteamLibrary\steamapps\workshop\content\1158310\3595290446",
]


def dump(name, obj):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with io.open(p, "w", encoding="utf-8") as fp:
        json.dump(obj, fp, ensure_ascii=False, indent=1)
    print(f"  写入 {p}", flush=True)
    return p


# ---------------------------------------------------------------------------
# 游戏侧：特质定义里的 tracks
# ---------------------------------------------------------------------------

def _block(txt, i):
    """从 '{' 起做花括号配平，返回块内文本。"""
    depth = 0
    for j in range(i, len(txt)):
        if txt[j] == "{":
            depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0:
                return txt[i + 1:j]
    return txt[i + 1:]


def scan_game_traits():
    out = {}
    files = []
    for d in [GAME] + MODS:
        files += glob.glob(os.path.join(d, "common", "traits", "*.txt"))
    for f in files:
        try:
            txt = io.open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in re.finditer(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\{", txt, re.M):
            key = m.group(1)
            body = _block(txt, m.end() - 1)
            cat = re.search(r"^\s*category\s*=\s*([a-zA-Z_]+)", body, re.M)
            tr = re.search(r"^\s*tracks\s*=\s*\{", body, re.M)
            if not tr:
                continue
            tbody = _block(body, tr.end() - 1)
            tracks = {}
            for tm in re.finditer(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\{", tbody, re.M):
                tname = tm.group(1)
                if tname in ("desc", "trigger", "first_valid", "name"):
                    continue
                tb = _block(tbody, tm.end() - 1)
                lv = {}
                for lm in re.finditer(r"^\s*(\d+)\s*=\s*\{", tb, re.M):
                    lv[lm.group(1)] = _block(tb, lm.end() - 1).strip()
                if lv:
                    tracks[tname] = lv
            if tracks:
                out[key] = {"file": f, "category": cat.group(1) if cat else None,
                            "tracks": tracks}
    return out


def main():
    print(f"读原文取 traits_lookup: {MELT}", flush=True)
    with open(MELT, "rb") as fp:
        blob = fp.read()
    i = blob.find(b'"traits_lookup":[')
    if i < 0:
        print("!! 未找到 traits_lookup")
        return 1
    j = blob.find(b"]", i)
    tl = json.loads(blob[i + len('"traits_lookup":'):j + 1].decode("utf-8"))
    dump("traits_lookup.json", tl)
    print(f"  traits_lookup {len(tl)} 项", flush=True)

    gt = scan_game_traits()
    dump("game_trait_tracks.json", gt)
    print(f"  游戏侧带 tracks 的特质 {len(gt)} 个", flush=True)

    idx2key = {n: k for n, k in enumerate(tl)}
    tracked_idx = {n: k for n, k in idx2key.items() if k in gt}
    print(f"  其中在本档 traits_lookup 里的 {len(tracked_idx)} 个", flush=True)

    print(f"载入熔件 {MELT} …（1-3 分钟）", flush=True)
    melt = cl.load_melt(MELT)
    print("  载入完成", flush=True)

    chars = cl.all_characters(melt)
    key_union = {}
    track_chars = {}
    for cid, c in chars.items():
        if not isinstance(c, dict):
            continue
        for k, v in c.items():
            key_union.setdefault(k, 0)
            key_union[k] += 1
        tr = [x for x in (c.get("traits") or []) if isinstance(x, int)]
        hit = [x for x in tr if x in tracked_idx]
        if hit:
            xp = c.get("trait_xp_amounts")
            track_chars[cid] = {
                "name": c.get("first_name"),
                "traits": [idx2key.get(x, x) for x in tr],
                "tracked": [idx2key[x] for x in hit],
                "trait_xp_amounts": xp,
                "xp_len": len(xp) if isinstance(xp, list) else None,
                "traits_len": len(tr),
                "keys": sorted(c.keys()),
            }
    dump("char_key_union.json", key_union)
    dump("track_chars.json", track_chars)
    print(f"  持有带轨道特质的角色 {len(track_chars)} 人", flush=True)

    # 记忆库：prison 相关
    db = cl._db(melt)
    owners = {}
    for cid, c in chars.items():
        if not isinstance(c, dict):
            continue
        for mid in (cl.mem_ids_of(c) or []):
            owners.setdefault(str(mid), []).append(cid)
    pm = {}
    for mid, e in db.items():
        if not isinstance(e, dict):
            continue
        if "prison" in str(e.get("type") or ""):
            pm[mid] = {"type": e.get("type"), "participants": e.get("participants"),
                       "creation_date": e.get("creation_date"),
                       "end_date": e.get("end_date"),
                       "expiration_date": e.get("expiration_date"),
                       "vars": e.get("variables"),
                       "owners": owners.get(str(mid), [])}
    dump("prison_memories.json", pm)
    print(f"  prison 类记忆 {len(pm)} 条", flush=True)

    # 记忆库：所有类型计数（便于看还有哪些「出狱方式」）
    types = {}
    for mid, e in db.items():
        if isinstance(e, dict):
            t = str(e.get("type"))
            types[t] = types.get(t, 0) + 1
    dump("memory_types.json", dict(sorted(types.items(), key=lambda kv: -kv[1])))

    # 指定角色原始对象（去掉 memories 大列表以免过大）
    raw = {}
    for cid in EXTRA_IDS:
        c = chars.get(str(cid))
        if not isinstance(c, dict):
            raw[str(cid)] = None
            continue
        cc = {k: v for k, v in c.items()}
        for bk in ("alive_data", "dead_data"):
            if isinstance(cc.get(bk), dict) and "memories" in cc[bk]:
                cc[bk] = dict(cc[bk])
                cc[bk]["memories"] = f"<{len(cc[bk]['memories'])} ids>"
        raw[str(cid)] = cc
    dump("raw_chars.json", raw)
    print("完成", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
