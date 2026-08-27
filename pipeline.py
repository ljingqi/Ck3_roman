# -*- coding: utf-8 -*-
"""主角一生记忆缓存 + 死后传记生成 流水线 v3.1 (移植自 expck3/pipeline.py)

**素材库纪律 (与 Journal 报纸 Mod 的 watch/continue 一致)**:
  - `watch`  / `continue`: 启动时记录基准 (当前最新存档的 mtime), **只处理本程序
    启动后写入的新存档**; 目录里已有的老存档(旧战役/历史档)一律不读、不记录。
  - `scan`: 单次补录——只补录**当前战役**(playthrough_id 一致或玩家一致)中日期
    新于缓存的新档; 其它战役的存档一律跳过。
  - 每次玩家角色死亡只生成一篇「终传」(`bio_generated` 标记); 死亡跨查带
    **身份校验**(名字一致 + 死亡日期晚于最后存活档), 防跨战役 id 撞号误判。

工作流:
  1. 检测新存档 (watch: mtime > 基准; scan: 同战役且日期新于缓存)
  2. rakaly json 熔化 → data/melt_<日期>.json
  3. cache_lib.extract_snapshot → cache/player_<玩家id>.json (每玩家一份, 跨年去重)
  4. 死亡检测 → 自动生成终传 → output/<家族>/<姓名>_终传_<日期>.md + 刷新 index.html

用法:
  python pipeline.py watch [秒]          # 新档监控: 只处理启动后保存的新存档
  python pipeline.py continue [秒]       # 旧档续传: 补录当前战役新档后进入监控
  python pipeline.py scan                # 单次: 只补录当前战役的新档
  python pipeline.py status              # 打印各玩家缓存状态
  python pipeline.py bio [玩家id]        # 手动生成传记 (在世传记或终传)
  python pipeline.py demo-death          # 模拟主角死亡, 演示「死后自动生成」链路
  python pipeline.py rebuild-cache       # 从 data/melt_*.json 重建缓存 (迁移/修复)
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm
import cache_lib as cl
import biography as bio

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
    """返回 [{path, date, player, magic, mtime}] 按日期排序。"""
    out = []
    if not os.path.isdir(save_dir):
        return out
    for fn in os.listdir(save_dir):
        if not fn.lower().endswith(".ck3"):
            continue
        p = os.path.join(save_dir, fn)
        try:
            magic, date, player = read_save_envelope(p)
            mt = os.path.getmtime(p)
        except Exception:
            continue
        if not date:
            continue
        out.append({"path": p, "date": date, "player": player,
                    "magic": magic, "mtime": mt})
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


def active_cache(cfg):
    """当前战役缓存: 最后日期最新的那份。"""
    caches = all_caches(cfg)
    if not caches:
        return None, None
    pid = max(caches, key=lambda p: cl.date_key(caches[p][1].get("last_date") or ""))
    return pid, caches[pid][1]


def same_campaign(cache, melt, player_id):
    """判断存档是否属于缓存所记录的同一战役。
    playthrough_id 都存在时按它判; 否则按玩家 id 判。"""
    pt = melt.get("playthrough_id")
    cpt = cache.get("playthrough_id")
    if cpt and pt:
        return cpt == pt
    if not cpt and not pt:
        return cache.get("player_id") == player_id
    # 一边有 playthrough 一边没有: 无法确认同战役, 视为不同
    return False


def player_char_name(name):
    """'观察使，边诚' → '边诚' (取最后一个逗号后的角色名, 用于信封级预过滤)。"""
    if not name:
        return ""
    return str(name).rsplit("，", 1)[-1].rsplit(",", 1)[-1].strip()


def _catchup(cfg, cache):
    """补录当前战役的新档 (仅当信封角色名与缓存玩家名一致, 否则不熔化直接跳过)。
    返回处理数。"""
    pid = cache.get("player_id")
    my_name = player_char_name(cache.get("player_name"))
    save_dir = cfg.get("save_dir", "")
    processed = 0
    for s in scan_saves(save_dir):
        if s["date"] in (cache.get("sources") or []):
            continue
        if cl.date_key(s["date"]) <= cl.date_key(cache.get("last_date") or "0.0.0"):
            continue
        # 信封级预过滤: 角色名不一致 → 其它战役/其它人物, 不熔化不记录
        if my_name and player_char_name(s["player"]) != my_name:
            llm.log(f"  [跳过] {s['date']} {s['player']} 非本战役人物, 不读")
            continue
        mp = melt_path(cfg, s["date"])
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
            continue
        if not same_campaign(cache, melt, player_id):
            llm.log(f"  [跳过] {s['date']} 属其它战役 (playthrough="
                    f"{melt.get('playthrough_id')}), 不记录")
            continue
        if player_id != pid:
            llm.log(f"  [继位] {s['date']}: 同战役玩家变为 {player_id}, 新建缓存")
            cache = cl.load_cache(cache_path_for(cfg, player_id))
        if cl.extract_snapshot(cache, melt, s["date"]):
            cl.save_cache(cache, cache_path_for(cfg, cache.get("player_id")))
            processed += 1
            llm.log(f"  并入 {s['date']}: 相关人物 {len(cache['characters'])}")
            _cross_check_deaths(cfg, melt, player_id)
    return processed


# ---------------------------------------------------------------------------
# 传记生成与输出
# ---------------------------------------------------------------------------

def output_paths(cfg, cache):
    """(家族文件夹, 输出文件名) — 以家族划分文件夹。"""
    house = cache.get("house_name") or ""
    if not house:
        pn = cache.get("player_name") or f"player_{cache.get('player_id')}"
        house = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "", pn).strip().strip(".") or "未知家族"
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
    try:
        import htmlview
        page = htmlview.rebuild_folder(cfg.get("output_dir", ""), house)
        if page:
            llm.log(f"阅读页已更新: {page}")
    except Exception as e:
        llm.log(f"更新阅读页失败: {e}")
    return out_path, facts


# ---------------------------------------------------------------------------
# 单档处理与死亡跨查
# ---------------------------------------------------------------------------

def _process_save(cfg, save, cache=None, log_prefix=""):
    """熔化并并入一份存档。cache 缺省按存档玩家自动加载/新建。
    返回处理的玩家 id 或 None。"""
    date = save["date"]
    mp = melt_path(cfg, date)
    if not os.path.isfile(mp):
        llm.log(f"  {log_prefix}熔化 {os.path.basename(save['path'])} ({save['magic']}) ...")
        try:
            melt_save(cfg, save["path"], mp)
        except Exception as e:
            llm.log(f"  熔化失败: {e}")
            return None
    melt = cl.load_melt(mp)
    player_id = cl.find_player(melt)
    if player_id is None:
        llm.log(f"  {date}: 存档中无玩家角色, 跳过")
        return None
    if cache is None:
        cache = cl.load_cache(cache_path_for(cfg, player_id))
    ok = cl.extract_snapshot(cache, melt, date)
    if not ok:
        llm.log(f"  {date}: 玩家不一致, 跳过")
        return None
    cl.save_cache(cache, cache_path_for(cfg, cache.get("player_id")))
    llm.log(f"  并入 {date}: 玩家 {cache.get('player_name')} (id={cache.get('player_id')}), "
            f"相关人物 {len(cache['characters'])}")
    _cross_check_deaths(cfg, melt, player_id)
    return player_id


def _cross_check_deaths(cfg, melt, current_player):
    """检查本档 dead_unprunable 中, 是否存在「既有缓存且身份一致」的前代玩家死亡。
    **身份校验**: 名字一致 (防跨战役 id 撞号) + 死亡日期晚于其最后存活档。"""
    for cid, c in (melt.get("dead_unprunable") or {}).items():
        cid = int(cid)
        if cid == current_player:
            continue
        path = cache_path_for(cfg, cid)
        if not os.path.isfile(path):
            continue
        dd = c.get("dead_data") or {}
        if not dd.get("date"):
            continue
        prev = cl.load_cache(path)
        if prev.get("player_death") is not None:
            continue
        # 身份校验: 名字一致
        rec = (prev.get("characters") or {}).get(str(cid)) or {}
        cached_name = rec.get("name_zh") or rec.get("name_full") or ""
        dead_name = cl.name_zh(c)
        if cached_name and dead_name and cl.zh(cached_name) != cl.zh(dead_name):
            continue  # id 撞号, 非同一人
        # 死亡日期必须晚于其最后存活档
        if cl.date_key(dd.get("date")) <= cl.date_key(prev.get("last_date") or "0.0.0"):
            continue
        prev["player_death"] = {
            "date": dd.get("date"),
            "reason": dd.get("reason"),
            "killer": dd.get("killer"),
        }
        cl.save_cache(prev, path)
        llm.log(f"  [检测] 前代玩家 {cid} ({cached_name}) 殁于 {dd.get('date')}, "
                f"原因 {dd.get('reason')} — 待生成终传")


def _auto_bio(cfg):
    """为所有「已死亡且未生成终传」的缓存生成终传 (每次死亡一篇)。"""
    caches = all_caches(cfg)
    generated = []
    for pid, (path, cache) in caches.items():
        death = cache.get("player_death")
        if not death or cache.get("bio_generated"):
            continue
        if not cfg.get("auto_bio_on_death", True):
            llm.log(f"[待生成] 玩家 {cache.get('player_name')} (id={pid}) 殁于 "
                    f"{death.get('date')}, 但 auto_bio_on_death=false, 跳过")
            continue
        llm.log(f"[触发] 玩家 {cache.get('player_name')} (id={pid}) 已殁于 "
                f"{death.get('date')} — 生成终传")
        try:
            out_path, _ = generate_bio(cfg, cache)
            if out_path:
                cache["bio_generated"] = True
                cl.save_cache(cache, path)
                generated.append(out_path)
        except Exception as e:
            llm.log(f"终传生成失败: {e}")
    if generated:
        llm.log(f"自动生成 {len(generated)} 篇终传")
    return generated


# ---------------------------------------------------------------------------
# watch / continue / scan
# ---------------------------------------------------------------------------

def step_watch(cfg, continue_mode=False):
    """watch/continue: 以启动时刻为基准, 只处理启动后写入的新存档。

    - continue: 启动时先补录当前战役的新档 (日期新于缓存), 再进入监控;
    - watch:    直接进入监控 (无缓存时首个新存档建立战役)。
    """
    save_dir = cfg.get("save_dir", "")
    baseline = max((s["mtime"] for s in scan_saves(save_dir)), default=0)
    llm.log("监控存档中 (只处理本程序启动后保存的存档)...")
    llm.log(f"基准时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(baseline))} "
            f"— 更早的老存档一律不读、不记录")
    if continue_mode:
        pid, cache = active_cache(cfg)
        if cache:
            llm.log(f"续传模式: 继续战役 {cache.get('player_name')} (id={pid}, "
                    f"家族={cache.get('house_name')}, 最后存档={cache.get('last_date')})")
            n = _catchup(cfg, cache)
            if n:
                llm.log(f"补录并入 {n} 个新档")
            else:
                llm.log("补录完成: 当前战役无新档")
        else:
            llm.log("续传模式: 暂无缓存, 等同 watch (首个新存档建立战役)")
    _auto_bio(cfg)
    # 监控循环
    seen = set()
    interval = cfg.get("poll_interval_seconds", 60)
    while True:
        try:
            saves = scan_saves(save_dir)
            new = [s for s in saves if s["mtime"] > baseline]
            processed = 0
            for s in new:
                key = (s["path"], round(s["mtime"], 3))
                if key in seen:
                    continue
                seen.add(key)
                llm.log(f"[{time.strftime('%H:%M:%S')}] 检测到新存档: "
                        f"{os.path.basename(s['path'])} ({s['date']})")
                if _process_save(cfg, s):
                    processed += 1
            if processed:
                _auto_bio(cfg)
            else:
                llm.log("无新存档")
        except Exception as e:
            llm.log(f"扫描异常: {e}")
        time.sleep(interval)


def step_scan(cfg):
    """单次补录: 只补录当前战役中日期新于缓存的新档。
    信封角色名不一致的存档直接跳过 (不熔化), 其它战役一律不读。"""
    pid, cache = active_cache(cfg)
    if not cache:
        llm.log("暂无玩家缓存 — 请先运行 watch (新档) 或 continue (旧档) 建立素材库")
        return
    llm.log(f"当前战役: {cache.get('player_name')} (id={pid}, 家族={cache.get('house_name')}, "
            f"最后存档={cache.get('last_date')})")
    n = _catchup(cfg, cache)
    _auto_bio(cfg)
    llm.log(f"补录完成: 处理 {n} 个新档")


# ---------------------------------------------------------------------------
# 其它命令
# ---------------------------------------------------------------------------

def step_status(cfg):
    caches = all_caches(cfg)
    if not caches:
        llm.log("暂无玩家缓存 (运行 watch 或 continue 建立素材库)")
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
        llm.log("暂无玩家缓存 (先运行 watch/continue)")
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
        keep = {}
        if cache.get("player_death"):
            keep["player_death"] = cache["player_death"]
        if cache.get("bio_generated"):
            keep["bio_generated"] = cache["bio_generated"]
        if cache.get("playthrough_id"):
            keep["playthrough_id"] = cache["playthrough_id"]
        cache = dict(cl.EMPTY_CACHE)
        cache.update(keep)
        cl.extract_snapshot(cache, melt, date)
        cl.save_cache(cache, path)
        llm.log(f"  {date}: 玩家 {player_id} → {os.path.basename(path)} "
                f"(相关人物 {len(cache['characters'])})")


def step_demo_death(cfg):
    """模拟主角死亡 → 演示「死后自动生成终传」链路。"""
    pid, cache = active_cache(cfg)
    if not cache:
        llm.log("暂无玩家缓存")
        return
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
    out_path = os.path.join(cfg.get("output_dir", ""), house, f"demo_{fname}")
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
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "watch":
        cfg["poll_interval_seconds"] = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        step_watch(cfg, continue_mode=False)
    elif cmd == "continue":
        cfg["poll_interval_seconds"] = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        step_watch(cfg, continue_mode=True)
    elif cmd == "scan":
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
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
