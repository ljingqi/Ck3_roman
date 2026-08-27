# -*- coding: utf-8 -*-
"""检查 CK3 存档目录: 各存档日期/玩家/zip 内容, 用于确定跨年样本。"""
import io, os, re, sys, zipfile

SAVE_DIR = r"C:\Users\CHINE\Documents\Paradox Interactive\Crusader Kings III\save games"

def inspect(path):
    data = open(path, "rb").read()
    out = {"file": os.path.basename(path), "size": len(data)}
    out["magic"] = data[:8].decode("utf-8", "replace")
    m = re.search(rb"meta_date=([0-9.]+)", data[:40000])
    out["meta_date"] = m.group(1).decode() if m else None
    m2 = re.search(rb'meta_player_name="([^"]*)"', data[:40000])
    out["meta_player_name"] = m2.group(1).decode("utf-8", "replace") if m2 else None
    idx = data.find(b"PK\x03\x04")
    out["zip_offset"] = idx
    if idx > 0:
        zf = zipfile.ZipFile(io.BytesIO(data[idx:]))
        entries = []
        for n in zf.namelist():
            info = zf.getinfo(n)
            entries.append((n, info.file_size, info.compress_type))
        out["zip_entries"] = entries
    return out

def main():
    targets = sys.argv[1:] or [
        "autosave.ck3", "autosave_1.ck3",
        "山南观察使，边诚_869_02_22.ck3",
    ]
    for t in targets:
        p = os.path.join(SAVE_DIR, t)
        if not os.path.isfile(p):
            print(f"[缺] {t}")
            continue
        r = inspect(p)
        print(f"=== {r['file']}  {r['size']/1e6:.1f}MB  日期={r['meta_date']}  玩家={r['meta_player_name']}")
        for n, sz, ct in r.get("zip_entries") or []:
            print(f"    zip: {n!r} 解压后 {sz/1e6:.1f}MB  压缩方式={ct}")

if __name__ == "__main__":
    main()
