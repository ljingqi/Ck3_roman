# -*- coding: utf-8 -*-
"""主角一生记忆缓存 + 死后传记生成 流水线 v3.1 (移植自 expck3/pipeline.py)

**素材库纪律 (与 Journal 报纸 Mod 的 watch/continue 一致)**:
  - `watch`  / `continue`: 启动时记录基准 (当前最新存档的 mtime), **只处理本程序
    启动后写入的新存档**; 目录里已有的老存档(旧战役/历史档)一律不读、不记录。
  - `scan`: 单次补录——只补录**当前战役**(playthrough_id 一致或玩家一致)中日期
    新于缓存且 mtime 晚于缓存文件的新档; 其它战役的存档一律跳过。
  - 每次玩家角色死亡只生成一篇「终传」(`bio_generated` 标记); 死亡跨查带
    **身份校验**(名字一致 + 死亡日期晚于最后存活档), 防跨战役 id 撞号误判。

工作流:
  1. 检测新存档 (watch: mtime > 基准; scan: 同战役且日期新于缓存)
  2. rakaly json 熔化 → output/<家族>/data/melt_<日期>.json
  3. cache_lib.extract_snapshot → output/<家族>/data/player_<玩家id>.json
     (每玩家一份, 跨年去重; 文件夹按宗族名; watch 每次运行一律新建编号文件夹
      哈布斯堡→哈布斯堡2, continue 沿用最新文件夹)
  4. 死亡检测 → 自动生成终传 → output/<家族>/<姓名>_终传_<日期>.md + 刷新 index.html

用法:
  python pipeline.py watch [秒]          # 新档监控: 只处理启动后保存的新存档 (每次运行一律新建文件夹 菲利普→菲利普2)
  python pipeline.py continue [秒]       # 旧档续传: 沿用最新文件夹, 补录当前战役新档后进入监控
  python pipeline.py scan                # 单次: 只补录当前战役的新档
  python pipeline.py status              # 打印各玩家缓存状态
  python pipeline.py bio [玩家id]        # 手动生成传记 (在世传记或终传)
  python pipeline.py demo-death          # 模拟主角死亡, 演示「死后自动生成」链路
  python pipeline.py rebuild-cache       # 从各战役文件夹熔件重建缓存 (迁移/修复)
  python pipeline.py index-melts         # 预建全部熔件的记忆归档边车 (回溯加速)
  python pipeline.py migrate             # 迁移 v4: 旧文件夹更名 + 缓存移入 output/<家族>/data/ + 重建
"""
import json
import os
import re
import subprocess
import sys
import threading
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
    """(兼容旧布局) 根 data 目录下的日期熔件路径。"""
    return os.path.join(cfg.get("data_dir", ""), f"melt_{cl.date_filekey(date)}.json")


def campaign_data_dir(cfg, folder):
    """战役文件夹的 data 目录: output/<家族>/data/。"""
    return os.path.join(cfg.get("output_dir", ""), folder, "data")


def melt_file_in(cfg, folder, date, player_id=None):
    """战役文件夹内该日期的熔件路径: 本玩家既有 _p 文件优先, 否则日期文件。"""
    d = campaign_data_dir(cfg, folder)
    key = cl.date_filekey(date)
    if player_id is not None:
        p = os.path.join(d, f"melt_{key}_p{player_id}.json")
        if os.path.isfile(p):
            return p
    return os.path.join(d, f"melt_{key}.json")


def melt_player_id(path):
    """熔件所属玩家 id (读文件找玩家); 解析失败返回 None。"""
    try:
        return cl.find_player(cl.load_melt(path))
    except Exception:
        return None


def temp_melt_path(cfg, date):
    """熔化中间文件 (定玩家/战役文件夹前): 根 data 目录, 进程唯一。"""
    return os.path.join(cfg.get("data_dir", ""),
                        f".tmp_melt_{cl.date_filekey(date)}_{os.getpid()}.json")


def _melt_save_into(cfg, folder, date, player_id, save_path):
    """把存档熔化写入战役文件夹 (日期文件被他人占用时改用 _p 后缀)。
    返回实际熔件路径。"""
    d = campaign_data_dir(cfg, folder)
    os.makedirs(d, exist_ok=True)
    key = cl.date_filekey(date)
    target = os.path.join(d, f"melt_{key}.json")
    if os.path.isfile(target) and player_id is not None:
        other = melt_player_id(target)
        if other is not None and other != player_id:
            target = os.path.join(d, f"melt_{key}_p{player_id}.json")
    melt_save(cfg, save_path, target)
    return target


def _move_melt_into(cfg, folder, date, player_id, tmp_path):
    """把临时熔件归入战役文件夹; 日期文件被他人占用时改用 _p 后缀;
    本玩家同日期熔件已存在则复用 (丢弃临时)。返回实际熔件路径。"""
    d = campaign_data_dir(cfg, folder)
    os.makedirs(d, exist_ok=True)
    key = cl.date_filekey(date)
    target = os.path.join(d, f"melt_{key}.json")
    if os.path.isfile(target):
        other = melt_player_id(target)
        if other is not None and other != player_id:
            target = os.path.join(d, f"melt_{key}_p{player_id}.json")
    if os.path.isfile(target):
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    else:
        os.replace(tmp_path, target)
    return target


def melt_path_for_cache(cfg, cache, date):
    """缓存战役文件夹内的熔件路径 (优先战役文件夹, 兼容旧根目录布局)。"""
    folder = cache.get("output_folder")
    if folder:
        p = melt_file_in(cfg, folder, date, cache.get("player_id"))
        if os.path.isfile(p):
            return p
    return melt_path(cfg, date)


def load_latest_melt(cfg, cache):
    """取缓存最后一份存档的 melt (dict); 缺失返回 None。
    优先战役文件夹 output/<家族>/data/, 兼容旧根目录布局。
    最后日期熔件缺失 (损坏/被清理) 时, 按 sources 降序回退到该会话文件夹
    最近一份现存熔件 (保证传记/十年传记仍可生成), 全无则返回 None。"""
    last = cache.get("last_date")
    if not last:
        return None
    p = melt_path_for_cache(cfg, cache, last)
    if os.path.isfile(p):
        return cl.load_melt(p)
    for d in sorted(cache.get("sources") or [], key=cl.date_key, reverse=True):
        p2 = melt_path_for_cache(cfg, cache, d)
        if os.path.isfile(p2):
            llm.log(f"  [回退] {last} 熔件缺失, 用最近现存熔件 {d} 生成")
            return cl.load_melt(p2)
    return None


# ---------------------------------------------------------------------------
# 缓存管理 (v4: 缓存位于 output/<家族>/data/)
# ---------------------------------------------------------------------------

def _session_folder_seq(folder):
    """会话文件夹序号: '菲利普' → ('菲利普', 0), '菲利普2' → ('菲利普', 2)。"""
    m = re.match(r"^(.*?)(\d+)$", str(folder or ""))
    return (m.group(1), int(m.group(2))) if m else (str(folder or ""), 0)


def _cache_pick_key(path, cache):
    """同玩家多份会话缓存的优先级键 (越大越优先):
    当前 watch 会话文件夹 > 会话文件夹编号大 (菲利普2 > 菲利普) > last_date 新 > mtime 新。
    重开老档后新会话日期 (883) 小于旧会话 (886), 故不能只看 last_date;
    会话文件夹编号 (determine_folder 递增) 才是「最新会话」的稳定判据。"""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        mt = 0.0
    dkey = cl.date_key(cache.get("last_date") or "0.0.0")
    folder = cache.get("output_folder") or ""
    if (_WATCH_SESSION["active"] and _WATCH_SESSION["folder"]
            and folder == _WATCH_SESSION["folder"]):
        return (2, 0, dkey, mt)
    _base, seq = _session_folder_seq(folder)
    return (1, seq, dkey, mt)


def find_cache_path(cfg, player_id, playthrough_id=None):
    """查找玩家缓存现有路径 (output 树 + 旧 cache/); 无则返回 None。
    v18: 可传 playthrough_id — 玩家 id 跨战役复用 (867 自定义角色恒为
    38701) 时按战役过滤, 只找同战役的缓存; 未传时保持旧行为 (取最新会话)。
    同玩家同战役多会话副本 (菲利普 / 菲利普3) 取最新会话 (_cache_pick_key,
    对齐 D:\\Journal _latest_session_folder_by_tag)。"""
    base = cfg.get("output_dir", "")
    best = None
    if os.path.isdir(base):
        for dp, _dn, fns in os.walk(base):
            p = os.path.join(dp, f"player_{player_id}.json")
            if os.path.isfile(p):
                cache = cl.load_cache(p)
                # 空缓存 (损坏文件被 load_cache 改名留证后返回的空缓存) 不参与选路,
                # 否则会以 seq=0 落选后把新档误并进旧会话文件夹 (2026-08-28 事件)
                if not cache.get("player_id"):
                    continue
                if playthrough_id is not None \
                        and cache.get("playthrough_id") != playthrough_id:
                    continue  # 跨战役同 id 缓存一律排除
                if best is None or _cache_pick_key(p, cache) > _cache_pick_key(best[0], best[1]):
                    best = (p, cache)
    if best:
        return best[0]
    legacy = os.path.join(cfg.get("cache_dir", ""), f"player_{player_id}.json")
    if os.path.isfile(legacy):
        cache = cl.load_cache(legacy)
        if cache.get("player_id") and (playthrough_id is None
                or cache.get("playthrough_id") == playthrough_id):
            return legacy
    return None


def all_caches(cfg):
    """{(player_id, playthrough_id): (path, cache)} 全部玩家缓存。
    v18: 玩家 id 跨战役复用 (867 自定义角色恒为 38701) — 键改为
    (player_id, playthrough_id), 同 id 不同战役的缓存互不覆盖;
    同战役多会话文件夹 (菲利普 / 菲利普3) 仍只保留最新会话者。"""
    out = {}
    for root in (cfg.get("output_dir", ""), cfg.get("cache_dir", "")):
        if not root or not os.path.isdir(root):
            continue
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                m = re.match(r"player_(\d+)\.json$", fn)
                if not m:
                    continue
                pid = int(m.group(1))
                path = os.path.join(dp, fn)
                cache = cl.load_cache(path)
                if not cache.get("player_id"):
                    continue  # 损坏缓存 (load_cache 已改名留证) 不参与任何战役选路
                key = (cache.get("player_id") or pid,
                       cache.get("playthrough_id"))
                prev = out.get(key)
                if prev is None or _cache_pick_key(path, cache) > \
                        _cache_pick_key(prev[0], prev[1]):
                    out[key] = (path, cache)
    return out


def cache_path_for(cfg, player_id, playthrough_id=None):
    """(兼容旧调用) 玩家缓存路径; 不存在返回 None。"""
    return find_cache_path(cfg, player_id, playthrough_id)


def folder_display(name):
    """文件夹显示名: 单字中文姓加「氏」(边 → 边氏), 其余原样 (冯·大马士革)。"""
    if len(name) == 1 and "\u4e00" <= name <= "\u9fff":
        return name + "氏"
    return name


def session_folder_name(cache):
    """会话文件夹命名基准: 宗族名(氏约定) → 家族名 → 人物名。"""
    name = cache.get("dynasty_name") or cache.get("house_name") or ""
    if not name:
        pn = cache.get("player_name") or f"玩家{cache.get('player_id')}"
        name = pn
    return sanitize_folder_name(folder_display(name))


def sanitize_folder_name(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name)).strip().strip(".") or "未知家族"


def determine_folder(name, output_dir):
    """重名文件夹加数字: 哈布斯堡 → 哈布斯堡2 → 哈布斯堡3... (仿 D:\\Journal)。
    v14: 语义改为「已有编号最大值 + 1」— 磁盘上 菲利普/菲利普3 并存时新会话建 菲利普4,
    不再找最小空号 (旧逻辑在 菲利普3 已存在时新建 菲利普2, 编号倒退破坏
    find_latest_session_folder/_cache_pick_key 的「编号大=最新」判据, 见 修复方案_菲利普2.md 问题1)。
    不带编号的 base 目录视为 1 (菲利普 存在 → 新会话 菲利普2)。"""
    base = sanitize_folder_name(name)
    max_seq = 0
    if os.path.isdir(output_dir):
        if os.path.isdir(os.path.join(output_dir, base)):
            max_seq = 1  # 无编号的 base 目录 = 1
        for fn in os.listdir(output_dir):
            m = re.match(re.escape(base) + r"(\d+)$", fn)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
    return f"{base}{max_seq + 1}" if max_seq else base


def find_latest_session_folder(name, output_dir):
    """返回该家族已存在的编号最大会话文件夹 (哈布斯堡 → 哈布斯堡2); 无则 None。"""
    base = sanitize_folder_name(name)
    found = []
    i = 1
    while True:
        cand = base if i == 1 else f"{base}{i}"
        if os.path.isdir(os.path.join(output_dir, cand)):
            found.append(cand)
            i += 1
            continue
        if i > 1:
            break
        i += 1
    return found[-1] if found else None


# watch 运行级会话文件夹 (对齐 D:\Journal 的 watch 语义):
# 每次 watch 运行 = 新的存档期 — 首个新档一律新建编号文件夹 (菲利普 → 菲利普2),
# 运行内同一玩家沿用本次运行文件夹, 换玩家(新局)再新建; continue 不走此逻辑。
_WATCH_SESSION = {"active": False, "folder": None, "player_key": None}


def resolve_output_folder(cfg, cache, continue_mode=False):
    """纯函数: 该缓存应使用的会话文件夹 (不修改缓存)。

    - continue: 沿用 (缓存绑定 → 同 playthrough → 该家族最新文件夹 → 新建);
    - watch:    一律新建编号文件夹, 绝不进旧文件夹 (对齐 D:\\Journal 会话语义:
                每次 watch 运行/换玩家 = 新存档期, determine_folder → 菲利普2...;
                运行内同玩家沿用本次运行的文件夹)。
    """
    out = cfg.get("output_dir", "")
    if continue_mode:
        cur = cache.get("output_folder")
        if cur and os.path.isdir(os.path.join(out, cur)):
            return cur
        pt = cache.get("playthrough_id")
        if pt:
            for _key, (_path, other) in all_caches(cfg).items():
                if other.get("playthrough_id") == pt and other.get("output_folder") \
                        and os.path.isdir(os.path.join(out, other["output_folder"])):
                    return other["output_folder"]
        name = session_folder_name(cache)
        latest = find_latest_session_folder(name, out)
        if latest:
            return latest
        return determine_folder(name, out)
    # watch 模式: 运行内同玩家沿用本次运行的文件夹; 换玩家(父死子继/新局)时——
    # v14: 先查同 playthrough_id 的既有缓存, 有则沿用其 output_folder (父死子继共享文件夹,
    # 修复方案_菲利普2.md 问题2: 旧逻辑 player_key 一变就 determine_folder 新建 菲利普4,
    # 且后台终传线程又建 菲利普5, 缓存绑定被污染); 无同战役缓存才新建编号文件夹。
    name = session_folder_name(cache)
    key = cache.get("player_id")
    if _WATCH_SESSION["active"]:
        if _WATCH_SESSION["folder"] is not None and _WATCH_SESSION["player_key"] == key:
            return _WATCH_SESSION["folder"]
        if key != _WATCH_SESSION["player_key"] and _WATCH_SESSION["player_key"] is not None:
            pt = cache.get("playthrough_id")
            if pt:
                for _key, (_path, other) in all_caches(cfg).items():
                    if other.get("playthrough_id") == pt and other.get("output_folder") \
                            and os.path.isdir(os.path.join(out, other["output_folder"])):
                        _WATCH_SESSION["folder"] = other["output_folder"]
                        _WATCH_SESSION["player_key"] = key
                        llm.log(f"  续用同战役文件夹: [{other['output_folder']}] (父死子继)")
                        return other["output_folder"]
        folder = determine_folder(name, out)
        _WATCH_SESSION["folder"] = folder
        _WATCH_SESSION["player_key"] = key
        llm.log(f"  新会话文件夹: [{folder}] (本次 watch 运行新建)")
        return folder
    # 非 watch 运行上下文 (独立 bio/rebuild 等): 沿用绑定/同战役, 否则新建
    cur = cache.get("output_folder")
    if cur and os.path.isdir(os.path.join(out, cur)):
        return cur
    pt = cache.get("playthrough_id")
    if pt:
        for _key, (_path, other) in all_caches(cfg).items():
            if other.get("playthrough_id") == pt and other.get("output_folder") \
                    and os.path.isdir(os.path.join(out, other["output_folder"])):
                return other["output_folder"]
    return determine_folder(name, out)


def ensure_output_folder(cfg, cache, continue_mode=False):
    """确定并绑定会话文件夹 (写入 cache.output_folder), 返回文件夹名。"""
    folder = resolve_output_folder(cfg, cache, continue_mode)
    cache["output_folder"] = folder
    return folder


def session_data_path(cfg, cache, folder=None):
    """缓存文件路径: output/<家族>/data/player_<id>.json"""
    folder = folder or resolve_output_folder(cfg, cache, True)
    return os.path.join(cfg.get("output_dir", ""), folder, "data",
                        f"player_{cache.get('player_id')}.json")


def save_session_cache(cfg, cache, continue_mode=False):
    """把缓存写入其会话文件夹并持久化文件夹绑定。
    v8.1: 写前合并磁盘上的 bio_decades/bio_generated — 后台传记线程可能在主线程
    读缓存之后、写缓存之前更新了这两个标记, 主线程整写会把它覆盖丢失
    (实测 15:12:50 覆盖 15:12:48, 导致第2个十年重复触发、重复烧 token)。"""
    folder = ensure_output_folder(cfg, cache, continue_mode)
    path = session_data_path(cfg, cache, folder)
    try:
        disk = cl.load_cache(path)
        bd = set(disk.get("bio_decades") or []) | set(cache.get("bio_decades") or [])
        cache["bio_decades"] = sorted(bd)
        if disk.get("bio_generated"):
            cache["bio_generated"] = True
    except Exception:
        pass
    cl.save_cache(cache, path)
    return path


def _cache_mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _date_scalar(s):
    """'869.2.22' → 排序标量 (年*372+月*31+日, 便于算时间线差距)。"""
    y, m, d = cl.date_key(s)
    return y * 372 + m * 31 + d


def active_cache(cfg):
    """当前战役缓存: 取「最新存档(mtime)」所属战役的缓存; 逐级回退。
    a) 信封人物名匹配缓存 (最新档属当前游戏, 名称带称号也能命中, 首选);
    b) 最新档日期已并入某缓存 → 该缓存战役 — 多战役同日期时选「时间线最贴近
       最新档」者 (last_date ≥ 最新档且差距最小, 次按缓存文件 mtime), 不再取
       last_date 最大 — 后者会把锚点漂到跑得最久的旧战役 (2026-08-30 事件:
       continue 误判 菲利普3/菲利普2, 导致汤利第3个十年传记漏生成);
    c) 熔化最新档一次按 playthrough_id 找同战役缓存 (覆盖「新玩家无缓存」);
    d) 回退: 全部缓存中 last_date 最新者。"""
    caches = all_caches(cfg)  # {(pid, playthrough_id): (path, cache)}
    if not caches:
        return None, None

    def best(keys):
        return max(keys, key=lambda k: cl.date_key(caches[k][1].get("last_date") or ""))

    def campaign_pick(keys, newest_date):
        """从候选缓存中选「当前战役」: 无 last_date 者垫底;
        last_date ≥ 最新档者优先, 与最新档差距最小者优先, 同差取缓存 mtime 新者。"""
        ad = _date_scalar(newest_date or "")
        def key(k):
            path, c = caches[k]
            mt = _cache_mtime(path)
            ld = c.get("last_date")
            if not ld:
                return (-2, 0, mt)  # 空/异常缓存垫底
            v = _date_scalar(ld)
            behind = 1 if v < ad else 0  # 落后于最新档 → 次优先
            return (-behind, -abs(ad - v), mt)
        return max(keys, key=key)

    try:
        saves = scan_saves(cfg.get("save_dir", ""))
    except Exception:
        saves = []
    if saves:
        newest = max(saves, key=lambda s: s["mtime"])
        hit = []
        # a) 信封人物名 → 匹配缓存 (与 _catchup 预过滤同一规范化)
        nm = player_char_name(newest["player"])
        if nm:
            hit = [k for k, (_pp, c) in caches.items()
                   if player_char_name(c.get("player_name")) == nm]
        if not hit:
            # b) 该档日期已并入某缓存 → 该缓存所属战役 (零成本); 平局按时间线贴近度
            hit = [k for k, (_pp, c) in caches.items()
                   if newest["date"] in (c.get("sources") or [])]
        if not hit:
            # c) 熔化最新档一次 → 按 playthrough_id 找同战役缓存 (覆盖「新玩家无缓存」)
            try:
                tmp = temp_melt_path(cfg, newest["date"])
                melt_save(cfg, newest["path"], tmp)
                pt = cl.load_melt(tmp).get("playthrough_id")
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                if pt:
                    hit = [k for k, (_pp, c) in caches.items()
                           if c.get("playthrough_id") == pt]
            except Exception:
                hit = []
        if hit:
            key = campaign_pick(hit, newest["date"])
            pt = caches[key][1].get("playthrough_id")
            if pt:  # 同战役内取最新缓存 (继位后锚定新统治者)
                key = best([k for k, (_pp, c) in caches.items()
                            if c.get("playthrough_id") == pt])
            return key[0], caches[key][1]
    # d) 全部失败: 回退原逻辑 (最后日期最新)
    key = best(list(caches))
    return key[0], caches[key][1]


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


def _catchup(cfg, cache, continue_mode=False):
    """补录当前战役的新档 (仅当信封角色名与缓存玩家名一致, 否则不熔化直接跳过)。
    新档 = 日期新于缓存 last_date 且 mtime 晚于缓存文件写入时刻 (上次运行已见过的
    老档一律不扫不记录, 防误读历史战役存档)。返回处理数。"""
    pid = cache.get("player_id")
    my_name = player_char_name(cache.get("player_name"))
    save_dir = cfg.get("save_dir", "")
    # 缓存文件写入时刻 = 上次运行已处理完这些存档的分界; 晚于它的存档才是「新档」
    cache_path = find_cache_path(cfg, pid, cache.get("playthrough_id"))
    cache_mtime = os.path.getmtime(cache_path) if cache_path else 0.0
    processed = 0
    for s in scan_saves(save_dir):
        if s["date"] in (cache.get("sources") or []):
            continue
        if cl.date_key(s["date"]) <= cl.date_key(cache.get("last_date") or "0.0.0"):
            continue
        if cache_mtime and s["mtime"] <= cache_mtime:
            continue  # 上次运行已见过的存档, 不补录
        # 信封级预过滤: 角色名不一致 → 其它战役/其它人物, 不熔化不记录
        if my_name and player_char_name(s["player"]) != my_name:
            llm.log(f"  [跳过] {s['date']} {s['player']} 非本战役人物, 不读")
            continue
        # 熔件入战役文件夹 output/<家族>/data/ (同一战役的继位玩家共用)
        folder = resolve_output_folder(cfg, cache, continue_mode)
        mp = melt_file_in(cfg, folder, s["date"], pid)
        if os.path.isfile(mp) and melt_player_id(mp) not in (None, pid):
            mp = None  # 日期文件属他人战役, 需重新熔化
        if not mp or not os.path.isfile(mp):
            llm.log(f"  熔化 {os.path.basename(s['path'])} ({s['magic']}) ...")
            try:
                mp = _melt_save_into(cfg, folder, s["date"], pid, s["path"])
            except Exception as e:
                llm.log(f"  熔化失败: {e}")
                continue
        try:
            melt = cl.load_melt(mp)
        except Exception as e:
            llm.log(f"  [跳过] {s['date']} 读取熔件失败: {e}")
            continue
        try:
            player_id = cl.find_player(melt)
            if player_id is None:
                continue
            if not same_campaign(cache, melt, player_id):
                llm.log(f"  [跳过] {s['date']} 属其它战役 (playthrough="
                        f"{melt.get('playthrough_id')}), 不记录")
                continue
            if player_id != pid:
                llm.log(f"  [继位] {s['date']}: 同战役玩家变为 {player_id}, 新建缓存")
                cache = cl.load_cache(
                    find_cache_path(cfg, player_id, melt.get("playthrough_id")) or "",
                    fresh=True)
            new_deaths = []
            if cl.extract_snapshot(cache, melt, s["date"], _new_deaths=new_deaths):
                _recover_dead_memories(cfg, cache, new_deaths)
                save_session_cache(cfg, cache, continue_mode)
                processed += 1
                llm.log(f"  并入 {s['date']}: 相关人物 {len(cache['characters'])}")
                _cross_check_deaths(cfg, melt, player_id)
        except Exception as e:
            llm.log(f"  [跳过] {s['date']} 处理失败: {e}")
            continue
    return processed


# ---------------------------------------------------------------------------
# 传记生成与输出
# ---------------------------------------------------------------------------

def _bio_pname(cache):
    """传记文件名用人物标识 (v13): 显示名+生年, 如「崔佛·菲利普(844)」。
    同宗同名 (祖孙都叫崔佛) 靠生年区分, 根治十年判重/文件名撞车。"""
    pid = cache.get("player_id")
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    pname = rec.get("name_full") or rec.get("name_zh") or f"玩家{pid}"
    birth = rec.get("birth") or ""
    by = str(birth).split(".")[0] if birth else ""
    return f"{pname}({by})" if by and by.isdigit() else pname


def output_paths(cfg, cache, continue_mode=False, decade=None):
    """(家族文件夹, 输出文件名) — 会话文件夹 + 传记文件名。
    decade 非空时输出十年传记独立命名, 避免与普通在世传记同日期重名
    被 generate_bio 的 exists 检查误跳过。"""
    folder = resolve_output_folder(cfg, cache, continue_mode)
    pname = _bio_pname(cache)
    death = cache.get("player_death")
    if death:
        kind = "终传"
        dkey = cl.date_filekey(death.get("date") or cache.get("last_date") or "")
    else:
        kind = "传记"
        dkey = cl.date_filekey(cache.get("last_date") or "")
    if decade:
        # 十年传记独立命名: 日期用数据截止日 (十年末, v11: 而非缓存 last_date —
        # 满档重跑时 last_date 是 931, 会误导文件名)
        dkey = cl.date_filekey(_decade_cutoff(cache, decade) or cache.get("last_date") or "")
        fname = f"{pname}_传记_第{decade}个十年_{dkey}.md"
    else:
        fname = f"{pname}_{kind}_{dkey}.md"
    return folder, fname


def _decade_cutoff(cache, decade):
    """第 decade 个十年的数据截止日 (v11): 起始年+decade×10 的年初, 取 min(last_date)。"""
    srcs = cache.get("sources") or []
    last = cache.get("last_date")
    if not srcs:
        return last
    try:
        sy = int(str(srcs[0]).split(".")[0])
        end = f"{sy + decade * 10}.1.1"
    except Exception:
        return last
    if last and cl.date_key(last) < cl.date_key(end):
        return last
    return end


def _bio_as_of(cache, decade=None):
    """传记数据截止日期 (v11): 十年传记 = 十年末; 终传/普通传记 = 死亡日或末档日期。
    None 表示不截断。"""
    if not decade:
        death = cache.get("player_death") or {}
        return death.get("date") or cache.get("last_date")
    return _decade_cutoff(cache, decade)


def generate_bio(cfg, cache, force=False, decade=None, continue_mode=False):
    """为一名玩家生成传记 (终传 / 在世传记 / 第decade个十年传记), 刷新家族 index.html。
    返回 (输出路径, facts) 或 None。
    v14: continue_mode — 后台传记线程传 True, 输出文件夹一律按缓存绑定/同战役解析,
    永不新建文件夹 (修复方案_菲利普2.md 问题2: 旧逻辑 watch 运行期间死者终传
    被 resolve 到新文件夹 菲利普5, 缓存绑定被污染)。"""
    melt = load_latest_melt(cfg, cache)
    if melt is None:
        llm.log(f"玩家 {cache.get('player_id')} 无可用 melt, 跳过生成")
        return None
    as_of = _bio_as_of(cache, decade)
    # v20: 十年传记按时代取绰号 — 绰号存于各年熔件 nickname_text, 最新档只是
    # 当前值; 重跑十年1 (as_of=878) 若不覆盖会被 888 档的「屠狼者」漂移。
    # v21: 时代末熔件存在即显式覆盖 (含空绰号) — 该时代无绰号时清空,
    # 防末档绰号泄漏进早期十年 (郭靖 1197 年才得「欺诈者」, 第1个十年
    # as_of=1189 不得出现该绰号)。
    nickname_override = None
    if decade and as_of:
        last = cache.get("last_date")
        if last and cl.date_key(as_of) < cl.date_key(last):
            try:
                p_era = melt_path_for_cache(cfg, cache, as_of)
                if os.path.isfile(p_era):
                    era = cl.load_melt(p_era)
                    pid = cache.get("player_id")
                    nick = ((era.get("living") or {}).get(str(pid)) or {}).get(
                        "nickname_text")
                    nickname_override = {pid: str(nick).strip()}
                    llm.log(f"  按时代取绰号 ({as_of}): {nick!r}")
            except Exception as e:
                llm.log(f"  按时代取绰号失败: {e}")
    house, fname = output_paths(cfg, cache, continue_mode=continue_mode, decade=decade)
    out_dir = os.path.join(cfg.get("output_dir", ""), house)
    out_path = os.path.join(out_dir, fname)
    if not force:
        if decade:
            # 十年传记: 磁盘推导 — 输出目录任一 第N个十年_*.md 已存在即视为已生成。
            # 文件名带 last_date (第2个十年_903 / _912), 直接比精确路径会在日期前进后漏检。
            pname = os.path.basename(fname).split("_传记_", 1)[0]
            pat = re.compile(re.escape(pname)
                             + rf"_传记_第{decade}个十年_.*\.md$")
            if os.path.isdir(out_dir) and any(
                    pat.match(fn) for fn in os.listdir(out_dir)):
                llm.log(f"已存在第{decade}个十年传记, 跳过 (加 --force 重新生成)")
                return out_path, None
        elif os.path.exists(out_path):
            llm.log(f"已存在, 跳过 (加 --force 重新生成): {out_path}")
            return out_path, None
    md, facts, articles = bio.generate_biography(cache, melt, cfg, out_path=out_path,
                                                 decade=decade, as_of=as_of,
                                                 nickname_override=nickname_override)
    # 持久化文件夹绑定 (v14: 只绑定、不覆盖 — output_folder 已存在且目录存在时
    # 不再改写, 修复方案_菲利普2.md 问题2: 旧逻辑把 38696 的绑定从 菲利普2
    # 覆盖成 菲利普5, 但缓存文件与熔件都在 菲利普2, 导致后续按错误绑定找文件夹)
    cur_bind = cache.get("output_folder")
    cur_ok = cur_bind and os.path.isdir(os.path.join(cfg.get("output_dir", ""), cur_bind))
    if not cur_ok and cache.get("output_folder") != house:
        cache["output_folder"] = house
        path = find_cache_path(cfg, cache.get("player_id"), cache.get("playthrough_id"))
        if path:
            cl.save_cache(cache, path)
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

def _process_save(cfg, save, continue_mode=False):
    """熔化并并入一份存档 (watch 用): 熔到临时 → 定玩家/战役文件夹 → 归位。
    返回 (玩家 id, playthrough_id) 或 None。并入阶段异常会清理临时熔件后重新抛出,
    由调用方记失败并在下一轮重试 (v7)。"""
    date = save["date"]
    tmp = temp_melt_path(cfg, date)
    llm.log(f"  熔化 {os.path.basename(save['path'])} ({save['magic']}) ...")
    try:
        melt_save(cfg, save["path"], tmp)
    except Exception as e:
        llm.log(f"  熔化失败: {e}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return None
    try:
        melt = cl.load_melt(tmp)
        player_id = cl.find_player(melt)
        if player_id is None:
            llm.log(f"  {date}: 存档中无玩家角色, 跳过")
            return None
        melt_pt = melt.get("playthrough_id")
        # v18: 按战役过滤找缓存 — 玩家 id 跨战役复用 (867 自定义角色恒为 38701),
        # 不加战役过滤会加载到旧战役缓存 (汤利→沙逊事件)。
        path0 = find_cache_path(cfg, player_id, melt_pt)
        cache = cl.load_cache(path0 or "", fresh=True)  # v13: 提取路径独立副本
        # v18: 兜底闸门 — 战役仍不一致 (无 playthrough 的旧缓存等边角) 时
        # 从空缓存重建, 旧战役的记忆/头衔历史绝不进入新战役。
        if cache.get("player_id") is not None and not same_campaign(cache, melt, player_id):
            llm.log(f"  {date}: 缓存战役与存档战役不一致 (玩家id复用/新局), "
                    f"从空缓存重建")
            cache = cl.new_cache()
        # 去重: continue 沿用旧会话 — 该玩家战役已记录过此日期 (轮转副本/同日期重存)
        # → 丢弃临时熔件跳过; watch 每次运行 = 新存档期 (对齐 D:\Journal): 一律新建
        # 编号文件夹并入, 不做跨会话去重, 单次运行内重复由 step_watch 的 mtime/日期兜住。
        if continue_mode and date in (cache.get("sources") or []):
            llm.log(f"  {date}: 已并入过 (轮转副本/重存), 跳过")
            try:
                os.remove(tmp)
            except OSError:
                pass
            return None
        new_deaths = []
        ok = cl.extract_snapshot(cache, melt, date, _new_deaths=new_deaths)
        if not ok:
            llm.log(f"  {date}: 玩家不一致, 跳过")
            return None
        folder = ensure_output_folder(cfg, cache, continue_mode)
        # 新会话首档: watch 定出的会话文件夹 ≠ 缓存所在文件夹 → 丢弃旧会话数据,
        # 用本档从空缓存重建 (防把 菲利普 旧战役数据缝合进 菲利普2, 出现 886 事件)。
        if not continue_mode and path0:
            dir0 = os.path.normpath(os.path.dirname(path0))
            dir1 = os.path.normpath(os.path.join(cfg.get("output_dir", ""), folder, "data"))
            if dir0 != dir1:
                house0 = os.path.basename(os.path.normpath(os.path.dirname(path0)))
                llm.log(f"  {date}: 新会话首档 ({house0} → {folder}), "
                        f"从空缓存重建, 不缝合旧会话数据")
                cache = cl.new_cache()
                cache["output_folder"] = folder
                new_deaths = []
                cl.extract_snapshot(cache, melt, date, _new_deaths=new_deaths)
        _move_melt_into(cfg, folder, date, player_id, tmp)
        _recover_dead_memories(cfg, cache, new_deaths)
        save_session_cache(cfg, cache, continue_mode)
        llm.log(f"  并入 {date}: 玩家 {cache.get('player_name')} (id={cache.get('player_id')}), "
                f"相关人物 {len(cache['characters'])}")
        _cross_check_deaths(cfg, melt, player_id)
        return player_id, melt_pt
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _recover_dead_memories(cfg, cache, new_deaths=None):
    """v5: 为缓存中「已死且记忆为空」的角色, 从死前最近一份存档恢复记忆。
    角色死亡时游戏清空其 memories; 死前最后一份自动存档中记忆完好。

    v9: 传入 new_deaths (本轮并入时新发现的死亡角色 id 列表) 时只处理这些角色,
    避免每次合并全量扫描全部已死角色 (随战役增长而膨胀, 是进程追不上游戏的主因之一);
    按死前档案分组, 同一份 melt 只加载一次, 为组内所有角色恢复。

    v12: 优先读记忆归档边车 (melt_<日期>_idx.json, 瘦身 ~20 MB) 回溯, 不再整份
    json.load 160 MB 旧熔件; 归档缺失时回退全量熔件, 并在回溯后惰性构建持久化
    归档 (下次直接读归档)。返回恢复的角色数。"""
    sources = cache.get("sources") or []
    # 候选: 已死、记忆为空、且 (提供 new_deaths 时) 属本轮新死亡
    pending = []
    for cid, rec in (cache.get("characters") or {}).items():
        d = rec.get("death") or {}
        ddate = d.get("date")
        if not ddate or rec.get("memories"):
            continue
        if new_deaths is not None and int(cid) not in new_deaths:
            continue
        # 死前最近档: sources 中日期 < 死亡日期的最大值
        before = [s for s in sources if cl.date_key(s) < cl.date_key(ddate)]
        if not before:
            continue
        mp = melt_path_for_cache(cfg, cache, before[-1])
        if not os.path.isfile(mp):
            continue
        pending.append((cid, mp, ddate, before[-1], rec))
    if not pending:
        return 0
    # 按死前档分组: 每份 melt (或其归档) 只读一次
    by_melt = {}
    for cid, mp, ddate, src, rec in pending:
        by_melt.setdefault(mp, []).append((cid, ddate, src, rec))
    recovered = 0

    def _recover_items(idx_or_melt, items, via_index):
        nonlocal recovered
        for cid, ddate, src, rec in items:
            try:
                if via_index:
                    n = cl.recover_dead_memories_from_index(idx_or_melt, cache, int(cid))
                else:
                    n = cl.recover_dead_memories_from(idx_or_melt, cache, int(cid))
                if n:
                    llm.log(f"  [回溯] 角色 {cid} ({rec.get('name_zh') or rec.get('name_full') or ''}) "
                            f"殁于{ddate}, 从{src}档{('归档' if via_index else '')}恢复 {n} 条记忆")
                    recovered += 1
            except Exception as e:
                llm.log(f"  [回溯失败] 角色 {cid}: {e}")

    for mp, items in by_melt.items():
        idx = cl.load_melt_index(mp)
        if idx is not None:
            _recover_items(idx, items, via_index=True)
            continue
        try:
            melt = cl.load_melt(mp)
        except Exception as e:
            for cid, _d, _s, _r in items:
                llm.log(f"  [回溯失败] 角色 {cid}: {e}")
            continue
        chars = cl.all_characters(melt)  # v11: 每份熔件只建一次全角色索引
        for cid, ddate, src, rec in items:
            try:
                n = cl.recover_dead_memories_from(melt, cache, int(cid), chars=chars)
                if n:
                    llm.log(f"  [回溯] 角色 {cid} ({rec.get('name_zh') or rec.get('name_full') or ''}) "
                            f"殁于{ddate}, 从{src}档恢复 {n} 条记忆")
                    recovered += 1
            except Exception as e:
                llm.log(f"  [回溯失败] 角色 {cid}: {e}")
        try:
            # v12: 惰性构建并持久化归档 — 今后回溯直接读边车索引
            cl.save_melt_index(mp, melt)
            llm.log(f"  [归档] {os.path.basename(mp)} 记忆归档已生成")
        except Exception as e:
            llm.log(f"  [归档失败] {os.path.basename(mp)}: {e}")
    if recovered:
        llm.log(f"死角色记忆回溯: {recovered} 个角色补全记忆")
    return recovered


def _cross_check_deaths(cfg, melt, current_player):
    """检查本档 dead_unprunable 中, 是否存在「既有缓存且身份一致」的前代玩家死亡。
    **身份校验**: 名字一致 (防跨战役 id 撞号) + 死亡日期晚于其最后存活档。
    v7: 预计算 {pid: (path, cache)} 一次, 避免为每个死亡角色 os.walk 整个 output 树。
    v18: 玩家 id 跨战役复用 (867 自定义角色恒为 38701) — 同 id 可能有多份缓存,
    同战役缓存优先, 其余需身份校验通过才采用。"""
    caches = all_caches(cfg)  # {(pid, pt): (path, cache)}
    melt_pt = melt.get("playthrough_id")
    for cid, c in (melt.get("dead_unprunable") or {}).items():
        if not isinstance(c, dict):  # v9: none 条目防护 (坏/写入中存档)
            continue
        cid = int(cid)
        if cid == current_player:
            continue
        hits = [v for k, v in caches.items() if k[0] == cid]
        if not hits:
            continue
        hits.sort(key=lambda hv: hv[1].get("playthrough_id") != melt_pt)
        for path, prev in hits:
            dd = c.get("dead_data") or {}
            if not dd.get("date"):
                continue
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
                "kills": dd.get("kills") or [],  # v8: 刺客列传数据源之一
            }
            cl.save_cache(prev, path)
            llm.log(f"  [检测] 前代玩家 {cid} ({cached_name}) 殁于 {dd.get('date')}, "
                    f"原因 {dd.get('reason')} — 待生成终传")
            break


_BIO_LOCK = threading.Lock()
_BIO_PENDING = set()        # 待生成任务 ((pid, pt), kind, decade) 去重; kind ∈ {"death","decade"}
_BIO_LAST_TRY = {}          # ((pid, pt), kind, decade) -> time.monotonic() 上次尝试时间 (失败退避)
_BIO_RETRY_SECONDS = 300    # 生成失败后至少间隔多久重试
_BIO_WORKER = None
_DECADE_SKIP_LOGGED = set()  # 已打「满十年但已死, 跳过」日志的玩家 (每会话一次, 防刷屏)


def _ensure_bio_worker(cfg):
    """启动后台终传生成线程 (watch/continue/scan 共用, 只启动一次)。
    终传生成 (多次 LLM 调用, 数分钟) 在后台进行, watch 轮询不阻塞 (v7)。"""
    global _BIO_WORKER
    if _BIO_WORKER is None:
        _BIO_WORKER = threading.Thread(target=_bio_worker_loop,
                                       args=(cfg,), daemon=True)
        _BIO_WORKER.start()


def _campaign_caches(cfg, anchor):
    """与 anchor 同战役 (playthrough_id 一致) 的玩家缓存 {player_id: cache};
    anchor 无 playthrough 时只返回其自身。v10: watch/continue 只检查
    当前战役的玩家, 不再全局扫描旧战役 (对齐 D:\\Journal 会话语义)。"""
    out = {}
    if anchor is None:
        return out
    pt = anchor.get("playthrough_id")
    pid = anchor.get("player_id")
    if not pt:
        if pid is not None:
            out[pid] = anchor
        return out
    for _k, (_path, c) in all_caches(cfg).items():
        if c.get("playthrough_id") == pt:
            out[_k[0]] = c
    return out


def _auto_bio(cfg, caches=None):
    """为「已死亡且未生成终传」的缓存排队生成终传 (后台线程执行, 每次死亡一篇)。
    失败不置 bio_generated, 下轮自动重试 (带退避)。返回本轮排队数。
    v10: caches 限定检查范围 (同战役); 缺省全部 (rebuild 等一次性路径)。"""
    _ensure_bio_worker(cfg)
    if caches is None:
        caches = {k: c for k, (_path, c) in all_caches(cfg).items()}
    else:
        # v18: 调用方可能传 {pid: cache} (int 键, _campaign_caches) — 统一为
        # {(pid, pt): cache} 元组键, 与后台 worker 的 ((pid, pt), kind, decade) 一致
        caches = {(k if isinstance(k, tuple) else (k, c.get("playthrough_id"))): c
                  for k, c in caches.items()}
    queued = 0
    now = time.monotonic()
    with _BIO_LOCK:
        for key, cache in caches.items():
            death = cache.get("player_death")
            if not death or cache.get("bio_generated"):
                continue
            if not cfg.get("auto_bio_on_death", True):
                llm.log(f"[待生成] 玩家 {cache.get('player_name')} (id={key[0]}) 殁于 "
                        f"{death.get('date')}, 但 auto_bio_on_death=false, 跳过")
                continue
            qkey = (key, "death", None)
            if qkey in _BIO_PENDING:
                continue
            if now - _BIO_LAST_TRY.get(qkey, 0) < _BIO_RETRY_SECONDS:
                continue
            _BIO_PENDING.add(qkey)
            queued += 1
            llm.log(f"[触发] 玩家 {cache.get('player_name')} (id={key[0]}) 已殁于 "
                    f"{death.get('date')} — 排队生成终传")
    if queued:
        llm.log(f"待生成 {queued} 篇终传")
    return queued


def _completed_decades(cache):
    """v8: 以数据起始年为刻度, 返回已满的十年序号列表 [1,2,...]。
    第 k 个十年 = [起始年+(k-1)*10, 起始年+k*10); 数据跨度满 10 年才出第 1 篇。"""
    sources = cache.get("sources") or []
    last = cache.get("last_date")
    if len(sources) < 2 or not last:
        return []
    try:
        start_y = int(str(sources[0]).split(".")[0])
        end_y = int(str(last).split(".")[0])
    except Exception:
        return []
    span = end_y - start_y
    if span < 10:
        return []
    return list(range(1, span // 10 + 1))


def _generated_decades_on_disk(cfg, cache):
    """磁盘推导: 已生成的十年序号 = 输出文件夹中「第N个十年_*.md」的 N 集合。
    以输出文件为准 (十年文件命名含 last_date, 且 bio_decades 会被并发写覆盖丢失),
    跨崩溃/多进程安全。v13: 文件标识含生年 (崔佛·菲利普(844)), 同宗同名不再误判。"""
    folder = cache.get("output_folder") or resolve_output_folder(cfg, cache, True)
    out_dir = os.path.join(cfg.get("output_dir", ""), folder)
    pname = _bio_pname(cache)
    done = set()
    if os.path.isdir(out_dir):
        pat = re.compile(re.escape(pname) + r"_传记_第(\d+)个十年_.*\.md$")
        for fn in os.listdir(out_dir):
            m = pat.match(fn)
            if m:
                done.add(int(m.group(1)))
    return done


def _auto_decade_bios(cfg, caches=None):
    """v8: 为「在世且已满新十年」的玩家排队生成十年传记 (后台线程执行)。
    十年传记素材取全部累计数据 (统治40年即读取40年数据);
    死亡后的角色不再补十年传记 (终传覆盖一生)。返回本轮排队数。
    v10: caches 限定检查范围 (同战役); 缺省全部。"""
    _ensure_bio_worker(cfg)
    if caches is None:
        caches = {k: c for k, (_path, c) in all_caches(cfg).items()}
    else:
        # v18: 统一为 {(pid, pt): cache} 元组键 (同 _auto_bio)
        caches = {(k if isinstance(k, tuple) else (k, c.get("playthrough_id"))): c
                  for k, c in caches.items()}
    queued = 0
    now = time.monotonic()
    with _BIO_LOCK:
        for key, cache in caches.items():
            pid = key[0]
            if cache.get("player_death"):
                ds = _completed_decades(cache)
                if ds and key not in _DECADE_SKIP_LOGGED:
                    _DECADE_SKIP_LOGGED.add(key)
                    llm.log(f"  [十年] 玩家 {cache.get('player_name')} (id={pid}) "
                            f"数据已满十年 {ds} 但已死亡, 按设计跳过 (终传覆盖一生)")
                continue
            # 已生成 = 缓存标记 ∪ 磁盘文件推导 (防 bio_decades 被并发写覆盖后重复触发)
            done = (set(cache.get("bio_decades") or [])
                    | _generated_decades_on_disk(cfg, cache))
            for k in _completed_decades(cache):
                if k in done:
                    continue
                qkey = (key, "decade", k)
                if qkey in _BIO_PENDING:
                    continue
                if now - _BIO_LAST_TRY.get(qkey, 0) < _BIO_RETRY_SECONDS:
                    continue
                _BIO_PENDING.add(qkey)
                queued += 1
                llm.log(f"[触发] 玩家 {cache.get('player_name')} (id={pid}) "
                        f"数据已满第{k}个十年 — 排队生成十年传记")
    if queued:
        llm.log(f"待生成 {queued} 篇十年传记")
    return queued


def _bio_worker_loop(cfg):
    """后台线程: 从队列取任务 (终传 / 十年传记) → 生成 → 置对应标记。
    以磁盘最新缓存为准只翻转标记, 防覆盖主线程刚写入的新档数据。
    v8: 队列项为 (pid, kind, decade), kind ∈ {"death", "decade"};
    v18: 队列键改为 ((pid, playthrough_id), kind, decade) — 玩家 id 跨战役
    复用 (867 自定义角色恒为 38701), 生成/回写必须落在该战役自己的缓存。"""
    while True:
        key = None
        with _BIO_LOCK:
            for k in _BIO_PENDING:
                key = k
                break
            if key is not None:
                _BIO_PENDING.discard(key)
        if key is None:
            time.sleep(2)
            continue
        pkey, kind, decade = key
        pid, pt = pkey
        try:
            path = find_cache_path(cfg, pid, pt)
            if not path:
                continue
            cache = cl.load_cache(path)
            if kind == "death":
                death = cache.get("player_death")
                if not death or cache.get("bio_generated"):
                    continue
                out = generate_bio(cfg, cache, continue_mode=True)  # v14: 后台线程按绑定解析
                if out:
                    out_path, _ = out
                    cur = cl.load_cache(path, fresh=True)  # v13: 写入路径独立副本
                    cur["bio_generated"] = True
                    cl.save_cache(cur, path)
                    llm.log(f"终传已生成: {out_path}")
            elif kind == "decade":
                if cache.get("player_death"):
                    continue  # 已死: 跳过十年传记 (终传覆盖)
                if (decade in (cache.get("bio_decades") or [])
                        or decade in _generated_decades_on_disk(cfg, cache)):
                    continue  # 磁盘上已有该十年文件 (或缓存标记), 不再生成
                out = generate_bio(cfg, cache, decade=decade, continue_mode=True)  # v14
                if out:
                    out_path, _ = out
                    cur = cl.load_cache(path, fresh=True)
                    cur.setdefault("bio_decades", []).append(decade)
                    cl.save_cache(cur, path)
                    llm.log(f"十年传记已生成 (第{decade}个十年): {out_path}")
        except Exception as e:
            llm.log(f"传记生成失败 (将重试): {e}")
        finally:
            with _BIO_LOCK:
                _BIO_LAST_TRY[key] = time.monotonic()


# ---------------------------------------------------------------------------
# watch / continue / scan
# ---------------------------------------------------------------------------

def _cleanup_tmp_melts(cfg):
    """清理残留的临时熔件 (上次异常退出遗留的 .tmp_melt_*.json)。"""
    data_dir = cfg.get("data_dir", "")
    if os.path.isdir(data_dir):
        for fn in os.listdir(data_dir):
            if fn.startswith(".tmp_melt_") and fn.endswith(".json"):
                try:
                    os.remove(os.path.join(data_dir, fn))
                except OSError:
                    pass


def _newest_save(save_dir):
    """存档目录里 mtime 最新的一份存档; 无存档返回 None。
    v9: 只读最新存档 — autosave_1/2 是 autosave.ck3 轮转出的旧副本,
    不可能含独立新数据 (对齐 D:\\Journal find_latest_v3 语义)。"""
    saves = scan_saves(save_dir)
    return max(saves, key=lambda s: s["mtime"]) if saves else None


def _wait_save_stable(path, seconds=2.0, attempts=4):
    """等待存档文件大小/修改时间连续稳定, 避免在游戏写入中途熔化
    (读到写入中的坏存档是 872 事件崩溃的根源; 对齐 D:\\Journal _wait_save_stable)。"""
    try:
        prev = None
        for _ in range(attempts):
            st = os.stat(path)
            sig = (st.st_size, st.st_mtime_ns)
            if prev is not None and sig == prev:
                return True
            prev = sig
            time.sleep(seconds)
    except OSError:
        return False
    return False


def step_watch(cfg, continue_mode=False):
    """watch/continue: 以启动时刻为基准, 只处理启动后写入的新存档。

    - continue: 启动时先补录当前战役的新档 (日期新于缓存), 再进入监控;
    - watch:    直接进入监控 (无缓存时首个新存档建立战役)。

    监控循环 (v9, 对齐 D:\\Journal cmd_watch 语义):
      - 每轮只取存档目录中 mtime 最新的一份存档处理; autosave_1/2 等轮转副本
        只是 autosave.ck3 的旧内容, 不再单独读取;
      - 熔化前等待文件写入稳定 (_wait_save_stable), 根除「读到写入中的坏存档」崩溃;
      - 会话级去重: 同一文件 (mtime 未变) 或同一日期 (重存/轮转副本) 只处理一次;
        换玩家 (新局) 后同日期允许重新出现;
      - _process_save 去重: continue 沿用旧会话时日期已入缓存 sources 则跳过
        (兜住跨会话重启); watch 每次运行 = 新存档期, 一律新建编号文件夹并入,
        不做跨会话去重 (对齐 D:\\Journal);
      - 处理失败不中止循环, 下轮重试 (存档轮转后旧文件自然不再被选中)。

    v7: 每档独立容错 (单档失败不中断本轮其余存档, 下轮重试);
        每轮都检查待生成终传; 终传生成在后台线程, 轮询不阻塞。"""
    global _WATCH_SESSION
    # watch = 新存档期: 一律新建文件夹 (对齐 D:\Journal); continue = 沿用, 不启用会话文件夹
    _WATCH_SESSION["active"] = not continue_mode
    _WATCH_SESSION["folder"] = None
    _WATCH_SESSION["player_key"] = None
    _cleanup_tmp_melts(cfg)
    save_dir = cfg.get("save_dir", "")
    baseline = max((s["mtime"] for s in scan_saves(save_dir)), default=0)
    llm.log("监控存档中 (只处理本程序启动后保存的新存档)...")
    llm.log(f"基准时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(baseline))} "
            f"— 更早的老存档一律不读、不记录")
    # v15: continue 会话锚点 — 启动时解析一次 (active_cache 已修多战役同日期歧义),
    # 监控循环内只在有新档并入时跟随该档玩家 (继位/换局), 不再每轮全局重算,
    # 防锚点漂移到旧战役 (2026-08-30 事件: continue 误判菲利普3/菲利普2,
    # 漏生成 汤利 第3个十年传记)。
    continue_anchor = None
    if continue_mode:
        pid, cache = active_cache(cfg)
        if cache:
            llm.log(f"续传模式: 继续战役 {cache.get('player_name')} (id={pid}, "
                    f"家族={cache.get('house_name')}, 最后存档={cache.get('last_date')})")
            n = _catchup(cfg, cache, continue_mode=True)
            if n:
                llm.log(f"补录并入 {n} 个新档")
            else:
                llm.log("补录完成: 当前战役无新档")
            continue_anchor = cache
        else:
            llm.log("续传模式: 暂无缓存, 等同 watch (首个新存档建立战役)")
    # 启动时检查: continue 用当前战役缓存; watch 无战役不检查 (首个新档建立战役后再查)
    if continue_anchor:
        _auto_bio(cfg, _campaign_caches(cfg, continue_anchor))
        _auto_decade_bios(cfg, _campaign_caches(cfg, continue_anchor))
    # 监控循环 (v9: 只读最新存档 + 会话级去重 + 等写入稳定; v10: 检查限定当前战役)
    interval = cfg.get("poll_interval_seconds", 60)
    last_mtime = None      # 上次已处理文件的 mtime (同一文件不重复处理)
    last_date = None       # 上次已处理日期 (同日期重存/轮转副本不重复并入)
    last_player = None     # 上次处理存档的玩家名 (换玩家 = 新局, 允许同日期重现)
    watch_anchor = None    # watch 模式: 首个新档建立的玩家缓存 (此后每轮只查该战役)
    while True:
        try:
            s = _newest_save(save_dir)
            processed = 0
            processed_player = None
            processed_pt = None
            if s is not None and s["mtime"] > baseline and s["mtime"] != last_mtime:
                nm = player_char_name(s.get("player"))
                if nm and last_player is not None and nm != last_player:
                    last_player = nm
                    last_date = None  # 新局/换玩家: 同日期允许重新出现
                if s["date"] == last_date:
                    llm.log(f"[{time.strftime('%H:%M:%S')}] "
                            f"{os.path.basename(s['path'])} ({s['date']}) 日期未变, 跳过 (避免重复)")
                    last_mtime = s["mtime"]
                else:
                    if not _wait_save_stable(s["path"]):
                        llm.log(f"[{time.strftime('%H:%M:%S')}] "
                                f"{os.path.basename(s['path'])} 仍在写入, 稍后重新检测...")
                        time.sleep(5)
                        continue
                    llm.log(f"[{time.strftime('%H:%M:%S')}] 检测到新存档: "
                            f"{os.path.basename(s['path'])} ({s['date']})")
                    try:
                        ret = _process_save(cfg, s, continue_mode=continue_mode)
                        if ret:
                            processed += 1
                            processed_player, processed_pt = ret
                        # 处理完成 (并入或判定重复/跳过) → 记住该文件与该日期;
                        # 失败 (异常) 不推进, 下轮重试
                        last_mtime = s["mtime"]
                        last_date = s["date"]
                        if nm:
                            last_player = nm
                    except Exception as e:
                        llm.log(f"  处理失败, 下轮重试: {os.path.basename(s['path'])}: {e}")
            if processed:
                llm.log(f"并入 {processed} 个新档")
            else:
                llm.log("无新存档")
            # 后台传记检查只查当前战役:
            # continue = 启动时定死的锚点 (有新档并入时跟随该档玩家, 防继位漏检);
            # watch = 新档建立的战役 (watch_anchor); 旧战役的缓存一律不扫
            # (对齐 D:\\Journal 会话语义; v15: 不再每轮 active_cache 全局重算)
            anchor = None
            if continue_mode:
                if processed_player:
                    # v18: 按战役过滤加载 — 玩家 id 跨战役复用 (867 自定义角色恒为 38701)
                    p = find_cache_path(cfg, processed_player, processed_pt)
                    if p:
                        continue_anchor = cl.load_cache(p)
                anchor = continue_anchor
            elif processed_player:
                p = find_cache_path(cfg, processed_player, processed_pt)
                if p:
                    watch_anchor = cl.load_cache(p)
                anchor = watch_anchor
            else:
                anchor = watch_anchor
            if anchor:
                caches = _campaign_caches(cfg, anchor)
                _auto_bio(cfg, caches)  # v7: 每轮检查待生成终传 (限定当前战役)
                _auto_decade_bios(cfg, caches)  # v8: 每轮检查待生成的十年传记
        except Exception as e:
            llm.log(f"扫描异常: {e}")
        time.sleep(interval)


def step_scan(cfg):
    """单次补录: 只补录当前战役中「日期新于缓存且 mtime 晚于缓存文件」的新档。
    信封角色名不一致的存档直接跳过 (不熔化), 其它战役一律不读。"""
    _cleanup_tmp_melts(cfg)
    pid, cache = active_cache(cfg)
    if not cache:
        llm.log("暂无玩家缓存 — 请先运行 watch (新档) 或 continue (旧档) 建立素材库")
        return
    llm.log(f"当前战役: {cache.get('player_name')} (id={pid}, 家族={cache.get('house_name')}, "
            f"最后存档={cache.get('last_date')})")
    n = _catchup(cfg, cache, continue_mode=True)
    _auto_bio(cfg, _campaign_caches(cfg, cache))
    _auto_decade_bios(cfg, _campaign_caches(cfg, cache))
    llm.log(f"补录完成: 处理 {n} 个新档")


# ---------------------------------------------------------------------------
# 其它命令
# ---------------------------------------------------------------------------

def step_status(cfg):
    caches = all_caches(cfg)
    if not caches:
        llm.log("暂无玩家缓存 (运行 watch 或 continue 建立素材库)")
        return
    for key in sorted(caches, key=lambda k: (k[0], str(k[1]))):
        path, cache = caches[key]
        n_mem = sum(len(c.get("memories") or []) for c in cache["characters"].values())
        death = cache.get("player_death")
        dstr = (f"已殁于 {death.get('date')} ({death.get('reason')})"
                + (" [终传已生成]" if cache.get("bio_generated") else " [待生成终传]")
                if death else "在世")
        house = cache.get("house_name") or "(家族未定)"
        pt = cache.get("playthrough_id") or "—"
        print(f"玩家 {key[0]}: {cache.get('player_name')} (战役 {pt})")
        print(f"  家族: {house} | 来源档: {cache.get('sources')} | 最后日期: {cache.get('last_date')}")
        print(f"  相关人物: {len(cache['characters'])} | 累计记忆: {n_mem} | 状态: {dstr}")
        print()


def step_bio(cfg, player_id=None, decade=None):
    """手动生成传记。player_id 缺省取当前战役 (最新存档所属战役) 的玩家。
    decade 非空时生成第 N 个十年传记 (验证十年功能/补档用)。
    v18: 玩家 id 跨战役复用 (867 自定义角色恒为 38701) — 同 id 多战役
    缓存时优先当前战役 (active_cache 的 playthrough), 无法判定时取
    last_date 最新者并在日志说明。"""
    caches = all_caches(cfg)
    if not caches:
        llm.log("暂无玩家缓存 (先运行 watch/continue)")
        return None
    if player_id is None:
        player_id, _ = active_cache(cfg)
    if player_id is None:
        return None
    cands = {k: v for k, v in caches.items() if k[0] == player_id}
    if not cands:
        llm.log(f"玩家 {player_id} 无缓存")
        return None
    if len(cands) == 1:
        key = next(iter(cands))
    else:
        # 同 id 跨战役: 优先当前战役 (active_cache 按最新存档解析)
        act_pid, act = active_cache(cfg)
        act_pt = act.get("playthrough_id") if act else None
        key = next((k for k in cands if k[1] == act_pt), None)
        if key is None:
            key = max(cands, key=lambda k: cl.date_key(
                cands[k][1].get("last_date") or ""))
            llm.log(f"玩家 {player_id} 存在多战役缓存且未匹配当前战役, "
                    f"取 {cands[key][1].get('player_name')} "
                    f"(last={cands[key][1].get('last_date')})")
    _path, cache = cands[key]
    llm.log(f"生成传记: {cache.get('player_name')} (id={player_id}, "
            f"战役={cache.get('playthrough_id')})")
    out_path, _ = generate_bio(cfg, cache, force=True, decade=decade)
    return out_path


def _iter_melts(cfg):
    """遍历全部熔件: (所属战役文件夹或 None, 绝对路径, 日期)。
    优先战役文件夹 output/<家族>/data/, 兼容旧根目录布局。"""
    pat = re.compile(r"melt_(\d+_\d{2}_\d{2})(?:_p\d+)?\.json$")
    out = []
    out_dir = cfg.get("output_dir", "")
    if os.path.isdir(out_dir):
        for folder in sorted(os.listdir(out_dir)):
            d = os.path.join(out_dir, folder, "data")
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                m = pat.match(fn)
                if m:
                    out.append((folder, os.path.join(d, fn),
                                ".".join(str(int(x)) for x in m.group(1).split("_"))))
    data_dir = cfg.get("data_dir", "")
    if os.path.isdir(data_dir):
        for fn in os.listdir(data_dir):
            m = pat.match(fn)
            if m:
                out.append((None, os.path.join(data_dir, fn),
                            ".".join(str(int(x)) for x in m.group(1).split("_"))))
    out.sort(key=lambda x: cl.date_key(x[2]))
    return out


def step_rebuild_cache(cfg):
    """从各战役文件夹熔件重建缓存 (每玩家每会话文件夹一份, 输出至 output/<家族>/data/)。
    熔件现存放于战役文件夹; 兼容旧根目录布局。
    同玩家跨会话文件夹 (菲利普 / 菲利普2) 的熔件各自独立重建, 防跨会话缝合。"""
    melts = _iter_melts(cfg)
    if not melts:
        llm.log("未找到 melt 文件 (战役文件夹 data/ 或根 data/)")
        return
    llm.log(f"重建缓存: {len(melts)} 份 melt")
    built = {}  # player_id → (folder, cache); 同玩家换会话文件夹 (菲利普→菲利普2) 时另起新缓存
    for folder, path, date in melts:
        melt = cl.load_melt(path)
        player_id = cl.find_player(melt)
        if player_id is None:
            llm.log(f"  {date}: 无玩家, 跳过")
            continue
        ent = built.get(player_id)
        if not folder:
            # 旧根目录熔件 (legacy 布局): 与既有根熔件合并, 首次并入后解析会话文件夹
            if ent is None:
                prev = cl.load_cache(
                    find_cache_path(cfg, player_id, melt.get("playthrough_id")) or "")
                cache = cl.new_cache()
                if prev.get("player_death"):
                    cache["player_death"] = prev["player_death"]
                if prev.get("bio_generated"):
                    cache["bio_generated"] = prev["bio_generated"]
                if prev.get("bio_decades"):
                    cache["bio_decades"] = prev["bio_decades"]  # v8
                if prev.get("playthrough_id"):
                    cache["playthrough_id"] = prev["playthrough_id"]
                built[player_id] = ("", cache)
                ent = built[player_id]
            else:
                cache = ent[1]
            cl.extract_snapshot(cache, melt, date)
            if not ent[0]:
                folder = ensure_output_folder(cfg, cache, continue_mode=True)
                built[player_id] = (folder, cache)
            else:
                folder = ent[0]
        else:
            # 熔件所在战役文件夹为准; 同玩家换文件夹 = 另一会话 (菲利普 / 菲利普2),
            # 各自独立重建 (仅用本文件夹熔件), 防跨会话缝合。
            if ent is None or ent[0] != folder:
                prev = cl.load_cache(os.path.join(
                    cfg.get("output_dir", ""), folder, "data",
                    f"player_{player_id}.json"))
                cache = cl.new_cache()
                if prev.get("player_death"):
                    cache["player_death"] = prev["player_death"]
                if prev.get("bio_generated"):
                    cache["bio_generated"] = prev["bio_generated"]
                if prev.get("bio_decades"):
                    cache["bio_decades"] = prev["bio_decades"]  # v8
                if prev.get("playthrough_id"):
                    cache["playthrough_id"] = prev["playthrough_id"]
                built[player_id] = (folder, cache)
            else:
                cache = ent[1]
            cl.extract_snapshot(cache, melt, date)
        cache["output_folder"] = folder
        path_out = session_data_path(cfg, cache, folder)
        _recover_dead_memories(cfg, cache)
        cl.save_cache(cache, path_out)
        llm.log(f"  {date}: 玩家 {player_id} → {path_out} "
                f"(相关人物 {len(cache['characters'])})")


def step_migrate(cfg):
    """迁移到 v4 布局:
      1) 旧 cache/*.json → output/<家族>/data/ (绑定 output_folder, 用旧文件夹名);
      2) 历史文件夹更名 大师巴沙尔 → 冯·大马士革 (姓氏修复后的家族名), 同步绑定;
      3) 重建缓存 (v4 schema)。"""
    out = cfg.get("output_dir", "")
    legacy = cfg.get("cache_dir", "")
    rename_map = {}
    # 1) 旧缓存迁移 (先用旧文件夹名绑定)
    moved = 0
    if os.path.isdir(legacy):
        for fn in sorted(os.listdir(legacy)):
            m = re.match(r"player_(\d+)\.json$", fn)
            if not m:
                continue
            pid = int(m.group(1))
            src = os.path.join(legacy, fn)
            cache = cl.load_cache(src)
            folder = _legacy_folder_for(cfg, cache, pid)
            cache["output_folder"] = folder
            dst_dir = os.path.join(out, folder, "data")
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, fn)
            if os.path.abspath(src) != os.path.abspath(dst):
                if os.path.exists(dst):
                    os.remove(dst)
                os.replace(src, dst)
            cl.save_cache(cache, dst)
            moved += 1
            llm.log(f"  缓存迁移: {fn} → {os.path.relpath(dst, out)}")
    llm.log(f"旧缓存迁移 {moved} 份 → output/<家族>/data/")
    # 2) 历史文件夹更名 (把 data/ 一起带走)
    old_dir = os.path.join(out, "大师巴沙尔")
    if os.path.isdir(old_dir):
        new_dir = os.path.join(out, "冯·大马士革")
        if not os.path.isdir(new_dir):
            os.rename(old_dir, new_dir)
            rename_map["大师巴沙尔"] = "冯·大马士革"
            llm.log("文件夹更名: 大师巴沙尔 → 冯·大马士革")
        else:
            llm.log("冯·大马士革 已存在, 跳过更名")
    if rename_map:
        for key, (_path, cache) in all_caches(cfg).items():
            f = cache.get("output_folder")
            if f in rename_map:
                cache["output_folder"] = rename_map[f]
                cl.save_cache(cache, find_cache_path(
                    cfg, key[0], cache.get("playthrough_id")) or _path)
    # 3) 重建 (v4)
    step_rebuild_cache(cfg)
    llm.log("迁移完成: 缓存已按 v4 重建")


def _legacy_folder_for(cfg, cache, pid):
    """旧缓存 → 会话文件夹 (v4 迁移): 家族名(兼容氏)/人物名/同战役, 逐级匹配现存文件夹。"""
    out = cfg.get("output_dir", "")
    folder = cache.get("output_folder")
    if folder and os.path.isdir(os.path.join(out, folder)):
        return folder
    if cache.get("house_name"):
        cand = cache["house_name"]
        for f in (cand, cand.rstrip("氏"), cand + "氏"):
            if f and os.path.isdir(os.path.join(out, f)):
                return f
    pn = cache.get("player_name") or f"玩家{pid}"
    f2 = sanitize_folder_name(pn)
    if os.path.isdir(os.path.join(out, f2)):
        return f2
    pt = cache.get("playthrough_id")
    if pt:
        for _key, (_p, other) in all_caches(cfg).items():
            if other.get("playthrough_id") == pt and other.get("output_folder") \
                    and os.path.isdir(os.path.join(out, other["output_folder"])):
                return other["output_folder"]
    return session_folder_name(cache)


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

def step_index_melts(cfg):
    """预建全部熔件的记忆归档边车 (melt_<日期>_idx.json)。

    日常回溯 (死角色记忆补全) 优先读归档, 全量 160 MB 熔件只在归档缺失时加载
    一次 (惰性构建), 之后直接读 ~20 MB 归档。本命令用于升级后一次性补齐历史
    熔件的归档, 也可随时重跑补齐新增熔件。"""
    melts = _iter_melts(cfg)
    if not melts:
        llm.log("未找到 melt 文件 (战役文件夹 data/ 或根 data/)")
        return
    llm.log(f"预建记忆归档: {len(melts)} 份熔件")
    built = skipped = failed = 0
    for _folder, path, date in melts:
        idx_path = cl.melt_index_path(path)
        if os.path.isfile(idx_path):
            skipped += 1
            continue
        t0 = time.time()
        try:
            melt = cl.load_melt(path)
        except Exception as e:
            llm.log(f"  {date}: 加载失败 {e}")
            failed += 1
            continue
        try:
            cl.save_melt_index(path, melt)
        except Exception as e:
            llm.log(f"  {date}: 归档失败 {e}")
            failed += 1
            continue
        built += 1
        llm.log(f"  {date}: 归档完成 ({time.time() - t0:.0f}s)")
    llm.log(f"归档完成: 新建 {built} 份, 已有 {skipped} 份, 失败 {failed} 份")


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
        pid = int(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else None
        decade = None
        if "--decade" in sys.argv:
            i = sys.argv.index("--decade")
            try:
                decade = int(sys.argv[i + 1])
            except (IndexError, ValueError):
                print("--decade 需要数字参数, 如: python pipeline.py bio 38725 --decade 1")
                return
        out = step_bio(cfg, pid, decade=decade)
        if out:
            print("已生成:", out)
    elif cmd == "demo-death":
        step_demo_death(cfg)
    elif cmd == "rebuild-cache":
        step_rebuild_cache(cfg)
    elif cmd == "index-melts":
        step_index_melts(cfg)
    elif cmd == "migrate":
        step_migrate(cfg)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
