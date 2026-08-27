# -*- coding: utf-8 -*-
"""主角一生记忆缓存 + 死后传记生成 流水线 v3 (由 expck3/pipeline.py 移植升级)。

工作流 (对应「每年自动存档读记忆 → 玩家角色死后自动生成一篇传记」):
  1. scan    : 扫描 CK3 存档目录, 找出未并入缓存的存档 (按 meta_date 排序)
  2. melt    : rakaly json 熔化 → data/melt_<日期>.json (自动/手动存档均支持)
  3. extract : cache_lib.extract_snapshot 并入 cache/player_<玩家id>.json (跨年去重,
              每玩家一份缓存, 支持「主角死亡→继承人继位」的长局)
  4. detect  : 检查各缓存 player_death (玩家角色 dead_data 出现即触发)
  5. bio     : 生成传记 → output/<家族>/<姓名>_<终传|传记>_<日期>.md, 并刷新 index.html
  6. watch   : 循环 1-5, 每次玩家角色死亡只生成一篇终传

用法:
  python pipeline.py scan            # 扫描并入新档, 检测死亡, 自动生成终传
  python pipeline.py status          # 打印各玩家缓存状态
  python pipeline.py bio [玩家id]    # 手动生成传记 (在世传记或终传)
  python pipeline.py watch [秒]      # 循环模式
  python pipeline.py demo-death      # 模拟主角死亡, 演示「死后自动生成」链路
  python pipeline.py rebuild-cache   # 从 data/melt_*.json 重建缓存 (迁移/修复用)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm
import cache_lib as cl
import biography as bio
import facts as F

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# 存档读取
# ---------------------------------------------------------------------------

def read_save_envelope(path):
    """读取 SAV 信封明文头: 返回 (magic, meta_date, meta_player_name)。"""
    with open(path, "rb") as fp:
        head = fp.read(65536)
    magic = head[:8].decode("utf-8", "replace")
    def grab(patt):
        m = re.search(patt, head)
        return m.group(1).decode("utf-8", "replace") if m else None
    date = grab(rb"meta_date=([0-9.]+)")
    player = grab(rb'meta_player_name="([^"]*)"')
    return magic, date, player


def melt_save(cfg, save_path, out_path):
    """rakaly json 熔化存档 → out_path。"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    rakaly = cfg.get("rakaly_path") or ""
    if not rakaly or not os.path.isfile(rakaly):
        raise RuntimeError(f"rakaly 不存在: {rakaly} (请在 config.json 配置 rakaly_path)")
    proc = subprocess.run([rakaly, "json", save_path], capture_output=True, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"rakaly 失败: {proc.stderr.decode('utf-8', 'replace')[:200]}")
    with open(out_path, "wb") as fp:
        fp.write(proc.stdout)
    return out_path


def scan_saves(save_dir):
    """返回 [{path, date, player, magic}] 按日期排序。"""
    out = []
    if not os.path.isdir(save_dir):
        return out
    for fn in os.listdir(save_dir):
        if not fn.lower().endswith(".ck3"):
            continue
        p = os.path.join(save_dir, fn)
        try:
            magic, date, player = read_save_envelope(p)
        except Exception:
            continue
        if not date:
            continue
        out.append({"path": p, "date": date, "player": player, "magic": magic})
    out.sort(key=lambda x: cl.date_key(x["date"]))
    return out


def melt_path(cfg, date):
    return os.path.join(cfg.get("data_dir", ""), f"melt_{cl.date_filekey(date)}.json")


def load_latest_melt(cfg, cache):
    """取缓存最后一份存档的 melt (dict); 缺失返回 None。"""
    last = cache.get("last_date")
    if not last:
        return None
    p = melt_path(cfg, last)
    if not os.path.isfile(p):
        return None
    return cl.load_melt(p)


# ---------------------------------------------------------------------------
# 缓存管理
# ---------------------------------------------------------------------------

def all_caches(cfg):
    """{player_id: (path, cache)} 全部玩家缓存。"""
    out = {}
    d = cfg.get("cache_dir", "")
    if not os.path.isdir(d):
        return out
    for fn in os.listdir(d):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        pid = int(m.group(1))
        path = os.path.join(d, fn)
        out[pid] = (path, cl.load_cache(path))
    return out


def cache_path_for(cfg, player_id):
    return os.path.join(cfg.get("cache_dir", ""), f"player_{player_id}.json")


# ---------------------------------------------------------------------------
# 传记生成与输出
# ---------------------------------------------------------------------------

def output_paths(cfg, cache):
    """(家族文件夹, 输出文件名) — 以家族划分文件夹。"""
    house = cache.get("house_name") or ""
    if not house:
        # 兜底: 用玩家名 (去掉头衔部分)
        pn = cache.get("player_name") or f"player_{cache.get('player_id')}"
        house = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "", pn).strip().strip(".") or "未知家族"
    pname = ""
    rec = (cache.get("characters") or {}).get(str(cache.get("player_id"))) or {}
    pname = rec.get("name_full") or rec.get("name_zh") or f"玩家{cache.get('player_id')}"
    death = cache.get("player_death")
    if death:
        kind = "终传"
        dkey = cl.date_filekey(death.get("date") or cache.get("last_date") or "")
    else:
        kind = "传记"
        dkey = cl.date_filekey(cache.get("last_date") or "")
    fname = f"{pname}_{kind}_{dkey}.md"
    return house, fname


def generate_bio(cfg, cache, force=False):
    """为一名玩家生成传记 (终传或在世传记), 刷新家族 index.html。
    返回 (输出路径, facts) 或 None。"""
    melt = load_latest_melt(cfg, cache)
    if melt is None:
        llm.log(f"玩家 {cache.get('player_id')} 无可用 melt, 跳过生成")
        return None
    house, fname = output_paths(cfg, cache)
    out_dir = os.path.join(cfg.get("output_dir", ""), house)
    out_path = os.path.join(out_dir, fname)
    if os.path.exists(out_path) and not force:
        llm.log(f"已存在, 跳过 (加 --force 重新生成): {out_path}")
        return out_path, None
    md, facts, articles = bio.generate_biography(cache, melt, cfg, out_path=out_path)
    # 刷新家族阅读页
    try:
        import htmlview
        page = htmlview.rebuild_folder(cfg.get("output_dir", ""), house)
        if page:
            llm.log(f"阅读页已更新: {page}")
    except Exception as e:
        llm.log(f"更新阅读页失败: {e}")
    return out_path, facts


# ---------------------------------------------------------------------------
# 流水线步骤
# ---------------------------------------------------------------------------

def step_scan(cfg):
    """扫描存档目录, 并入新档; 检测死亡并自动生成终传。"""
    save_dir = cfg.get("save_dir", "")
    caches = all_caches(cfg)
    saves = scan_saves(save_dir)
    llm.log(f"存档目录: {save_dir}")
    llm.log(f"找到存档 {len(saves)} 个; 已有玩家缓存 {len(caches)} 份: "
            f"{[c.get('player_name') for _, c in caches.values()]}")
    covered = set()
    for pid, (_, c) in caches.items():
        covered.update(c.get("sources") or [])
    new_saves = [s for s in saves if s["date"] not in covered]
    llm.log(f"待并入新存档: {[(s['date'], os.path.basename(s['path'])) for s in new_saves]}")

    touched = set()
    for s in new_saves:
        date = s["date"]
        mp = melt_path(cfg, date)
        if not os.path.isfile(mp):
            llm.log(f"  熔化 {os.path.basename(s['path'])} ({s['magic']}) ...")
            try:
                melt_save(cfg, s["path"], mp)
            except Exception as e:
                llm.log(f"  熔化失败: {e}")
                continue
        melt = cl.load_melt(mp)
        player_id = cl.find_player(melt)
        if player_id is None:
            llm.log(f"  {date}: 存档中无玩家角色, 跳过")
            continue
        cache = cl.load_cache(cache_path_for(cfg, player_id))
        ok = cl.extract_snapshot(cache, melt, date)
        if not ok:
            llm.log(f"  {date}: 玩家不一致, 跳过")
            continue
        cl.save_cache(cache, cache_path_for(cfg, player_id))
        touched.add(player_id)
        llm.log(f"  并入 {date}: 玩家 {cache.get('player_name')} (id={player_id}), "
                f"相关人物 {len(cache['characters'])}")
        # 跨档检查: 本档中已死的「前代玩家」 (玩家易主, 前主角死亡在此档登记)
        deads = (melt.get("dead_unprunable") or {})
        for cid, c in deads.items():
            if int(cid) == player_id:
                continue
            prev_path = cache_path_for(cfg, int(cid))
            if not os.path.isfile(prev_path):
                continue
            dd = c.get("dead_data") or {}
            if not dd:
                continue
            prev = cl.load_cache(prev_path)
            if prev.get("player_death") is None:
                prev["player_death"] = {
                    "date": dd.get("date"),
                    "reason": dd.get("reason"),
                    "killer": dd.get("killer"),
                }
                cl.save_cache(prev, prev_path)
                touched.add(int(cid))
                llm.log(f"  [检测] 前代玩家 {int(cid)} 殁于 {dd.get('date')}, "
                        f"原因 {dd.get('reason')}")

    # 自动生成终传: 每次玩家角色死亡只生成一篇
    auto = cfg.get("auto_bio_on_death", True)
    generated = []
    for pid in sorted(touched):
        path = cache_path_for(cfg, pid)
        cache = cl.load_cache(path)
        death = cache.get("player_death")
        if death and not cache.get("bio_generated"):
            if not auto:
                llm.log(f"[待生成] 玩家 {cache.get('player_name')} (id={pid}) "
                        f"殁于 {death.get('date')}, 但 auto_bio_on_death=false, 跳过")
                continue
            llm.log(f"[触发] 玩家 {cache.get('player_name')} (id={pid}) "
                    f"已殁于 {death.get('date')}, 原因 {death.get('reason')}, "
                    f"凶手 {death.get('killer')} — 生成终传")
            try:
                out_path, _ = generate_bio(cfg, cache)
                if out_path:
                    cache["bio_generated"] = True
                    cl.save_cache(cache, path)
                    generated.append(out_path)
            except Exception as e:
                llm.log(f"终传生成失败: {e}")
    if generated:
        llm.log(f"本次扫描自动生成 {len(generated)} 篇终传")
    else:
        llm.log("本次扫描未触发新的终传")
    return caches


def step_status(cfg):
    caches = all_caches(cfg)
    if not caches:
        llm.log("暂无玩家缓存 (运行 scan 或复制 cache/player_*.json)")
        return
    for pid in sorted(caches):
        path, cache = caches[pid]
        n_mem = sum(len(c.get("memories") or []) for c in cache["characters"].values())
        death = cache.get("player_death")
        dstr = (f"已殁于 {death.get('date')} ({death.get('reason')})"
                + (" [终传已生成]" if cache.get("bio_generated") else " [待生成终传]")
                if death else "在世")
        house = cache.get("house_name") or "(家族未定)"
        print(f"玩家 {pid}: {cache.get('player_name')}")
        print(f"  家族: {house} | 来源档: {cache.get('sources')} | 最后日期: {cache.get('last_date')}")
        print(f"  相关人物: {len(cache['characters'])} | 累计记忆: {n_mem} | 状态: {dstr}")
        print()


def step_bio(cfg, player_id=None):
    """手动生成传记。player_id 缺省取最后日期最新的玩家。"""
    caches = all_caches(cfg)
    if not caches:
        llm.log("暂无玩家缓存 (先运行 scan)")
        return None
    if player_id is None:
        player_id = max(caches, key=lambda p: cl.date_key(caches[p][1].get("last_date") or ""))
    if player_id not in caches:
        llm.log(f"玩家 {player_id} 无缓存")
        return None
    path, cache = caches[player_id]
    out_path, _ = generate_bio(cfg, cache, force=True)
    return out_path


def step_rebuild_cache(cfg):
    """从 data/melt_*.json 重建缓存 (每玩家一份)。"""
    data_dir = cfg.get("data_dir", "")
    melts = sorted(
        (f for f in os.listdir(data_dir) if re.match(r"melt_\d+_\d{2}_\d{2}\.json$", f)),
        key=lambda f: cl.date_key(f[5:-5].replace("_", ".")))
    if not melts:
        llm.log(f"{data_dir} 下无 melt 文件")
        return
    llm.log(f"重建缓存: {len(melts)} 份 melt")
    for fn in melts:
        date = ".".join(str(int(x)) for x in fn[5:-5].split("_"))
        melt = cl.load_melt(os.path.join(data_dir, fn))
        player_id = cl.find_player(melt)
        if player_id is None:
            llm.log(f"  {date}: 无玩家, 跳过")
            continue
        path = cache_path_for(cfg, player_id)
        cache = cl.load_cache(path)
        # 重建: 清空旧角色集 (保留死亡与生成标记)
        keep = {}
        if cache.get("player_death"):
            keep["player_death"] = cache["player_death"]
        if cache.get("bio_generated"):
            keep["bio_generated"] = cache["bio_generated"]
        cache = dict(cl.EMPTY_CACHE)
        cache.update(keep)
        cl.extract_snapshot(cache, melt, date)
        cl.save_cache(cache, path)
        llm.log(f"  {date}: 玩家 {player_id} → {os.path.basename(path)} "
                f"(相关人物 {len(cache['characters'])})")


def step_demo_death(cfg):
    """模拟主角死亡 → 演示「死后自动生成终传」链路。"""
    caches = all_caches(cfg)
    if not caches:
        llm.log("暂无玩家缓存")
        return
    pid = max(caches, key=lambda p: cl.date_key(caches[p][1].get("last_date") or ""))
    path, cache = caches[pid]
    import copy
    demo = json.loads(json.dumps(cache))
    demo["player_death"] = {
        "date": "869.12.31",
        "reason": "death_old_age",
        "killer": None,
    }
    demo["bio_generated"] = False
    llm.log(f"== 演示: 模拟玩家 {demo.get('player_name')} (id={pid}) 死亡 ==")
    house, fname = output_paths(cfg, demo)
    out_path = os.path.join(cfg.get("output_dir", ""), house,
                            f"demo_{fname}")
    md, facts, articles = bio.generate_biography(demo, load_latest_melt(cfg, cache),
                                                 cfg, out_path=out_path)
    llm.log(f"已生成演示终传: {out_path}")
    print()
    print("\n".join(md.splitlines()[:6]))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    cfg = llm.load_config()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "scan":
        step_scan(cfg)
    elif cmd == "status":
        step_status(cfg)
    elif cmd == "bio":
        pid = int(sys.argv[2]) if len(sys.argv) > 2 else None
        out = step_bio(cfg, pid)
        if out:
            print("已生成:", out)
    elif cmd == "demo-death":
        step_demo_death(cfg)
    elif cmd == "rebuild-cache":
        step_rebuild_cache(cfg)
    elif cmd == "watch":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else cfg.get("poll_interval_seconds", 3600)
        while True:
            try:
                step_scan(cfg)
            except Exception as e:
                llm.log(f"扫描异常: {e}")
            llm.log(f"休眠 {interval}s ...")
            time.sleep(interval)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
