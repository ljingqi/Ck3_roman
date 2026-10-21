"""v122 第3问取证三: 金元惠(16912738) 在 1057 档 living 里的领地表 + 他每个头衔的 key。

用法: & tools\py.ps1 tools\tests\v122_probe_kim3.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import cache_lib as cl  # noqa: E402

MELT = r"output\田所2\data\melt_1057_01_01.json"
CID = "16912738"
OUT = []


def P(s=""):
    OUT.append(str(s))
    print(s)


living = cl.load_melt_section(MELT, "living") or {}
rec = living.get(CID) or {}
if isinstance(rec, list):
    rec = rec[0]
P(f"角色 {CID} 在 living: {bool(rec)}")
P("顶层键: " + json.dumps(sorted(rec.keys()), ensure_ascii=False))
ld = rec.get("landed_data") or {}
P("landed_data: " + json.dumps(ld, ensure_ascii=False)[:3000])
P("playable_data: " + json.dumps(rec.get("playable_data"), ensure_ascii=False))
P("organization: " + json.dumps(rec.get("organization"), ensure_ascii=False))
tids = []
for k in ("domain", "titles"):
    for t in (ld.get(k) or []):
        if isinstance(t, int):
            tids.append(t)
P(f"域内头衔 id: {tids}")

# 逐个在熔件字节流里找 title 块, 取 key
size = os.path.getsize(MELT)
for tid in tids:
    nb = f'"{tid}":{{"key":'.encode("utf-8")
    found = None
    with open(MELT, "rb") as fp:
        tail = b""
        off = 0
        while True:
            chunk = fp.read(1 << 23)
            if not chunk:
                break
            buf = tail + chunk
            base = off - len(tail)
            i = buf.find(nb)
            while i >= 0:
                w = buf[i:i + 400]
                if b"de_jure_liege" in w or b"holder" in w:
                    found = (base + i, w)
                    break
                i = buf.find(nb, i + 1)
            if found:
                break
            off += len(chunk)
            tail = buf[-40:]
    if found:
        P(f"  {tid}: " + found[1].decode("utf-8", "replace")[:260])
    else:
        P(f"  {tid}: 未在熔件里找到 key 块")

# 该角色的 death 记录 (缓存里) 与标题名
cache = r"output\田所2\data\player_67220811.json"
P()
P("=== 玩家缓存里该角色的死亡与 liege_title ===")
try:
    d = cl.load_cache(cache)
    c = (d.get("characters") or {}).get(CID) or {}
    P("death: " + json.dumps(c.get("death"), ensure_ascii=False))
    P("name_full: " + json.dumps(c.get("name_full"), ensure_ascii=False))
    # 玩家自己的领地史里是否出现这个头衔
    for t in tids:
        pass
except Exception as e:
    P(f"缓存读取失败: {e}")

open(r"logs\v122\v122_probe_kim3.txt", "w", encoding="utf-8").write("\n".join(OUT))
print("written logs/v122/v122_probe_kim3.txt")
