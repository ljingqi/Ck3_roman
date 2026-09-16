# -*- coding: utf-8 -*-
"""v44 (问题1/2/4/6) 一次性回填: 家族沿革 / 族属沿革 / 传主链 / 重算译名。

背景（本脚本为何存在）:
  * 家族名与宗族名旧语义是「首见即冻结」(cache_lib.extract_snapshot 只写一次),
    传主别立家族 (阿德尔海德 1118.4.2 别立冯·亚琛氏) 与家族改名 (→ 冯) 全无捕捉;
  * 族属沿革被一行提前赋值废掉 (culture_history 永远只有首点);
  * 传主链 (存档 played_character.legacy) 此前完全未入库;
  * 本地化建表旧序让 Mod 英文顶掉本体中文 (Mathilde → "Matilda"), 缓存里的
    name_zh/name_full 是当时的脏值, 须按修好的表重算。

做法: 按档期顺序重放全部熔件, 只读需要的字段 (纯 json.load, 5s/份;
不走 cl.load_melt —— 它的重复键合并要 15s/份), 与 cache_lib.extract_snapshot
运行期语义一致地重建历史点。

用法:
    & tools\\tools\\py.ps1 tools\\refresh_house_history.py 诺兰 [玩家id] [--dry]
    & tools\\tools\\py.ps1 tools\\refresh_house_history.py 诺兰 --names   # 只按末档重算现值
产物: output/<家族>/data/player_<id>.json 原位更新 (先备份 .bak-v44)。
"""
import io
import json
import os
import re
import shutil
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import cache_lib as cl  # noqa: E402


def _chars_of(m):
    """熔件全角色索引 (living + dead_unprunable + dead_prunable)。"""
    out = {}
    out.update(m.get("living") or {})
    out.update(m.get("dead_unprunable") or {})
    out.update((m.get("characters") or {}).get("dead_prunable") or {})
    return out


def _house_names(m, hid):
    """(家族名, 宗族名) —— 与运行期同源, 均按该档熔件现值解析。"""
    h = cl.house_name_zh(m, hid) or ""
    did = cl.dynasty_id_of(m, hid)
    dn = cl.dynasty_name_zh(m, did) or "" if did is not None else ""
    return h, dn, did


def _date_label(fn):
    lab = fn[len("melt_"):].split("_idx")[0]
    for suf in (".json.gz", ".json"):
        if lab.endswith(suf):
            lab = lab[:-len(suf)]
    lab = re.sub(r"_p\d+$", "", lab)
    return ".".join(str(int(x)) for x in lab.split("_"))


def _melts_in(data):
    return sorted(
        f for f in os.listdir(data)
        if f.startswith("melt_") and "_idx" not in f and f.endswith((".json", ".json.gz"))
        and "_p" not in f)


def names_only(folder, caches, dry=False):
    """快修模式 (`--names`): 只按**末档熔件**重算现值, 不重放历史。

    用途: 首次回填只补了沿革点, 现值 (dynasty_house / house_name / dynasty_name /
    name_zh / name_full / 顶层家族名) 仍需按末档对齐 —— 传主换过家族时尤其要紧
    (阿德尔海德缓存里 dynasty_house 仍是 12371 诺兰, 名号于是仍是「诺兰阿德尔海德」)。
    只读最后一份熔件, 秒级完成。"""
    data = os.path.join(ROOT, "output", folder, "data")
    melts = _melts_in(data)
    if not melts:
        print("无熔件:", data)
        return 2
    with cl.open_melt_text(os.path.join(data, melts[-1])) as fp:
        last_melt = json.load(fp)
    allc = _chars_of(last_melt)
    print(f"快修模式: 末档熔件 {melts[-1]}, 缓存 {caches}")
    for cf in caches:
        path = os.path.join(data, cf)
        cache = json.load(open(path, encoding="utf-8"))
        recs = cache.get("characters") or {}
        targets = {int(cid) for cid in recs if str(cid).isdigit()}
        moved = 0
        for cid in targets:
            c = allc.get(str(cid))
            if not isinstance(c, dict):
                continue
            hid = c.get("dynasty_house")
            if isinstance(hid, int) and recs[str(cid)].get("dynasty_house") != hid:
                recs[str(cid)]["dynasty_house"] = hid
                moved += 1
        stat = {"house": 0, "culture": 0, "faith": 0, "name": 0, "legacy": 0}
        _refresh_names(cache, last_melt, targets, stat)
        lg = ((last_melt.get("played_character") or {}).get("legacy") or [])
        chain = [{"cid": e.get("character"), "date": e.get("date")}
                 for e in lg if isinstance(e, dict) and isinstance(e.get("character"), int)]
        if chain:
            cache["played_legacy"] = chain
            stat["legacy"] = len(chain)
        pid = cache.get("player_id")
        prec = recs.get(str(pid)) or {}
        if prec.get("house_name"):
            cache["house_name"] = prec["house_name"]
        if prec.get("dynasty_name"):
            cache["dynasty_name"] = prec["dynasty_name"]
        if isinstance(prec.get("dynasty_house"), int):
            did = cl.dynasty_id_of(last_melt, prec["dynasty_house"])
            if did is not None:
                cache["dynasty_id"] = did
        _pin_bio_pname(cache, folder)
        print(f"  {cf}: 家族 id 对齐 {moved} 人; 译名重算 {stat['name']} 人; "
              f"传主 {prec.get('name_full')!r} house={cache.get('house_name')!r} "
              f"dynasty={cache.get('dynasty_name')!r} bio_pname={cache.get('bio_pname')!r}")
        if dry:
            continue
        bak = path + ".bak-v44"
        if not os.path.isfile(bak):
            shutil.copy2(path, bak)
        cl.save_cache(cache, path)
        print(f"   已写入 {path}")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    folder = sys.argv[1]
    dry = "--dry" in sys.argv
    pid_arg = None
    for a in sys.argv[2:]:
        if a.isdigit():
            pid_arg = int(a)
    data = os.path.join(ROOT, "output", folder, "data")
    if not os.path.isdir(data):
        print("无此战役文件夹:", data)
        return 2
    melts = _melts_in(data)
    if not melts:
        print("无熔件:", data)
        return 2
    caches = sorted(f for f in os.listdir(data)
                    if f.startswith("player_") and f.endswith(".json"))
    if pid_arg is not None:
        caches = [f"player_{pid_arg}.json"] if f"player_{pid_arg}.json" in caches else []
    if "--names" in sys.argv:
        return names_only(folder, caches, dry=dry)
    print(f"战役 {folder}: 熔件 {len(melts)} 份 ({melts[0]} … {melts[-1]}); 缓存 {caches}")
    t_all = time.time()
    for cf in caches:
        path = os.path.join(data, cf)
        cache = json.load(open(path, encoding="utf-8"))
        chars = cache.get("characters") or {}
        if not chars:
            continue
        targets = {int(cid) for cid in chars if str(cid).isdigit()}
        # 每个目标的历史 (从空起算; 熔件里首见即首点)
        hh = {}
        ch = {}
        fh = {}
        last_seen = {}
        print(f"== {cf}: 目标角色 {len(targets)}", flush=True)
        for i, fn in enumerate(melts, 1):
            label = _date_label(fn)
            p = os.path.join(data, fn)
            t0 = time.time()
            try:
                with cl.open_melt_text(p) as fp:
                    m = json.load(fp)
            except Exception as e:
                print(f"   [{label}] 载入失败: {e}")
                continue
            allc = _chars_of(m)
            cultures = ((m.get("culture_manager") or {}).get("cultures") or {})
            for cid in targets:
                c = allc.get(str(cid))
                if not isinstance(c, dict):
                    continue
                last_seen[cid] = (label, c)
                # ---- 家族沿革 ----
                hid = c.get("dynasty_house")
                if isinstance(hid, int):
                    hname, dname, did = _house_names(m, hid)
                    if not hname and not dname:
                        hname, dname, did = "", "", None
                    pts = hh.setdefault(cid, [])
                    cur = (hid, hname, dname)
                    if not pts or (pts[-1]["house_id"], pts[-1]["house_name"],
                                   pts[-1]["dynasty_name"]) != cur:
                        d = label
                        if not pts or pts[-1]["house_id"] != hid:
                            fd = cl.house_found_date(m, hid)
                            if fd:
                                d = fd
                        pts.append({"from": d, "house_id": hid,
                                    "house_name": hname, "dynasty_id": did,
                                    "dynasty_name": dname})
                # ---- 族属沿革 ----
                cul = c.get("culture")
                if cul is not None and (str(cul) in cultures or not ch.get(cid)):
                    pts = ch.setdefault(cid, [])
                    if not pts or pts[-1]["culture"] != cul:
                        pts.append({"from": label, "culture": cul})
                # ---- 信仰沿革 (旧实现已正常, 顺手对齐) ----
                fid = c.get("faith")
                if fid is not None:
                    pts = fh.setdefault(cid, [])
                    if not pts or pts[-1]["faith"] != fid:
                        pts.append({"from": label, "faith": fid})
            if i % 10 == 0 or i == len(melts):
                print(f"   已扫 {i}/{len(melts)} ({label}, {time.time() - t0:.1f}s/份)",
                      flush=True)
        # ---- 写回 ----
        stat = {"house": 0, "culture": 0, "faith": 0, "name": 0, "legacy": 0}
        for cid in targets:
            rec = chars.get(str(cid)) or {}
            if not rec:
                continue
            pts = hh.get(cid) or []
            if pts and pts != (rec.get("house_history") or []):
                rec["house_history"] = pts
                stat["house"] += 1
            pts = ch.get(cid) or []
            if pts and pts != (rec.get("culture_history") or []):
                rec["culture_history"] = pts
                stat["culture"] += 1
            pts = fh.get(cid) or []
            if pts and pts != (rec.get("faith_history") or []):
                rec["faith_history"] = pts
                stat["faith"] += 1
            # 家族/宗族末档现值 + 译名重算 由 _refresh_names 统一做 (需末档熔件)
        # 家族/宗族名与译名按**末档熔件**统一重算 (本地化表已修)
        with cl.open_melt_text(os.path.join(data, melts[-1])) as fp:
            last_melt = json.load(fp)
        _refresh_names(cache, last_melt, targets, stat)
        # ---- 传主链 ----
        lg = ((last_melt.get("played_character") or {}).get("legacy") or [])
        chain = [{"cid": e.get("character"), "date": e.get("date")}
                 for e in lg if isinstance(e, dict) and isinstance(e.get("character"), int)]
        if chain and chain != (cache.get("played_legacy") or []):
            cache["played_legacy"] = chain
            stat["legacy"] = len(chain)
        # ---- 顶层家族名 (【家族】/文件夹绑定用) ----
        pid = cache.get("player_id")
        prec = chars.get(str(pid)) or {}
        if prec.get("house_name"):
            cache["house_name"] = prec["house_name"]
        if prec.get("dynasty_name"):
            cache["dynasty_name"] = prec["dynasty_name"]
        did = cl.dynasty_id_of(last_melt, prec.get("dynasty_house")) \
            if isinstance(prec.get("dynasty_house"), int) else None
        if did is not None:
            cache["dynasty_id"] = did
        # ---- 文件名锚点 (改名后不让早先十年的文件失配) ----
        _pin_bio_pname(cache, folder)
        print(f"   回填统计: 家族沿革 {stat['house']} 人, 族属 {stat['culture']} 人, "
              f"信仰 {stat['faith']} 人, 译名重算 {stat['name']} 人, "
              f"传主链 {stat['legacy']} 环")
        if dry:
            print("   --dry: 未写盘")
            continue
        bak = path + ".bak-v44"
        if not os.path.isfile(bak):
            shutil.copy2(path, bak)
        cl.save_cache(cache, path)      # 原子写 + 与运行期同格式 (indent=1)
        print(f"   已写入 {path} (备份 {os.path.basename(bak)})")
    print(f"总耗时 {time.time() - t_all:.0f}s")
    return 0


def _refresh_names(cache, last_melt, targets, stat):
    """按修好的本地化表重算 name_zh/name_full (末档熔件为准)。"""
    allc = _chars_of(last_melt)
    recs = cache.get("characters") or {}
    house_memo = {}
    name_memo = {}
    for cid in targets:
        rec = recs.get(str(cid)) or {}
        if not rec:
            continue
        hid = rec.get("dynasty_house")
        if isinstance(hid, int):
            if hid not in house_memo:
                house_memo[hid] = _house_names(last_melt, hid)
            hname, dname, _did = house_memo[hid]
            if hname:
                rec["house_name"] = hname
            if dname:
                rec["dynasty_name"] = dname
        c = allc.get(str(cid))
        if isinstance(c, dict) and c.get("first_name"):
            new_zh = cl.zh(cl.loc_name(c["first_name"]))
            if new_zh and new_zh != rec.get("name_zh"):
                stat["name"] += 1
            rec["name_zh"] = new_zh or rec.get("name_zh")
        nm = cl.display_name(cache, cid, melt=last_melt, memo=name_memo)
        if nm:
            rec["name_full"] = nm


def _pin_bio_pname(cache, folder):
    """把传记文件名锚点钉在磁盘上已有的名字上 (改名后旧十年文件不失配)。

    `pipeline._bio_pname` 首次调用即钉存 `cache["bio_pname"]`; 迁移时按输出目录里
    既有的 `<名>(<生年>)_传记_第N个十年_*.md` 反推。**按本人名与生年过滤** ——
    同一战役文件夹里有多个传主 (克里斯托弗/阿德尔海德), 不筛会取到别人的文件名。
    找不到既有文件才用当前 name_full。"""
    if cache.get("bio_pname"):
        return
    out_dir = os.path.join(ROOT, "output", folder)
    pid = cache.get("player_id")
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    name_zh = rec.get("name_zh") or ""
    birth = str(rec.get("birth") or "")
    by = birth.split(".")[0] if birth else ""
    stems = []
    if os.path.isdir(out_dir):
        for fn in os.listdir(out_dir):
            m = re.match(r"^(.+?)_(?:传记_第\d+个十年|终传|传记)_", fn)
            if not m:
                continue
            stem = m.group(1)
            if name_zh and name_zh not in stem:
                continue
            if by and by.isdigit() and f"({by})" not in stem:
                continue
            stems.append(stem)
    if stems:
        from collections import Counter
        cache["bio_pname"] = Counter(stems).most_common(1)[0][0]
        return
    pname = rec.get("name_full") or rec.get("name_zh") or f"玩家{pid}"
    cache["bio_pname"] = f"{pname}({by})" if by and by.isdigit() else pname


if __name__ == "__main__":
    sys.exit(main())
