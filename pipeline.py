# -*- coding: utf-8 -*-
"""Main-character memory cache + post-death biography pipeline.

watch/continue process only saves written after startup; scan catches up the current campaign only.
Each player death yields exactly one final biography (`bio_generated`). Saves reach the material as
rakaly JSON melts under output/<house>/data/, merged into player_<player_id>.json by
cache_lib.extract_snapshot.

Usage:
  python pipeline.py watch [sec]        # monitor new saves only; creates a new numbered folder
  python pipeline.py continue [sec]     # reuse the newest folder, catch up, then monitor
  python pipeline.py scan               # one catch-up pass over current-campaign saves
  python pipeline.py status             # print per-player cache status
  python pipeline.py bio [player_id]    # generate a biography by hand (living or final)
  python pipeline.py demo-death         # simulate the player death path
  python pipeline.py rebuild-cache      # rebuild caches from campaign-folder melts
  python pipeline.py index-melts        # pre-build the memory archive sidecar of every melt
  python pipeline.py compact [--gz]     # archive cold melts and sidecars (default xz, ~1.4GB)
  python pipeline.py migrate            # move legacy caches under output/<house>/data/, rebuild
"""
import gzip
import hashlib
import json
import lzma
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm
import cache_lib as cl
import biography as bio

HERE = os.path.dirname(os.path.abspath(__file__))


# --- Save reading ---------------------------------------------------------------

def read_save_envelope(path):
    """Read the plaintext SAV envelope header: (magic, meta_date, meta_player_name)."""
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
    """Melt a save to out_path with `rakaly json` and return out_path. stdout streams into
    the file, so the ~244 MiB JSON is never held in memory; stderr is captured for errors."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    rakaly = cfg.get("rakaly_path") or ""
    if not rakaly or not os.path.isfile(rakaly):
        raise RuntimeError(f"rakaly 不存在: {rakaly} (请在 config.json 配置 rakaly_path)")
    with open(out_path, "wb") as fp:
        proc = subprocess.run([rakaly, "json", save_path], stdout=fp,
                              stderr=subprocess.PIPE, timeout=900)
    if proc.returncode != 0:
        raise RuntimeError(f"rakaly 失败: {proc.stderr.decode('utf-8', 'replace')[:200]}")
    return out_path


def scan_saves(save_dir):
    """List the saves in save_dir as [{path, date, player, magic, mtime}], sorted by date."""
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
    """Date-keyed melt path in the root data dir (legacy layout)."""
    return os.path.join(cfg.get("data_dir", ""), f"melt_{cl.date_filekey(date)}.json")


def campaign_data_dir(cfg, folder):
    """Campaign folder data dir: output/<house>/data/."""
    return os.path.join(cfg.get("output_dir", ""), folder, "data")


def melt_file_in(cfg, folder, date, player_id=None):
    """Melt path for this date in a campaign folder: an existing `_p` file of this player wins,
    else the date file; an archived `.json.gz`/`.json.xz` variant is returned when it exists."""
    d = campaign_data_dir(cfg, folder)
    key = cl.date_filekey(date)
    if player_id is not None:
        p = cl.melt_file_exists(os.path.join(d, f"melt_{key}_p{player_id}.json"))
        if p:
            return p
    p = cl.melt_file_exists(os.path.join(d, f"melt_{key}.json"))
    if p:
        return p
    return os.path.join(d, f"melt_{key}.json")


def melt_player_id(path):
    """Player id owning a melt file (read from its contents); None if parsing fails."""
    try:
        return cl.find_player(cl.load_melt(path))
    except Exception:
        return None


def temp_melt_path(cfg, date):
    """Intermediate melt before the player/campaign folder is known: root data dir, per process."""
    return os.path.join(cfg.get("data_dir", ""),
                        f".tmp_melt_{cl.date_filekey(date)}_{os.getpid()}.json")


def _melt_save_into(cfg, folder, date, player_id, save_path):
    """Melt a save into the campaign folder and return the lasting path; when the
    date file already belongs to another player the `_p` suffixed name is used."""
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
    """Move a temp melt into the campaign folder and return its lasting path; the `_p` suffix is
    used when the date file belongs to another player, and an existing same-date melt is reused."""
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
        cl.melt_memo_move(tmp_path, target)  # keep the melt memo on the final path
        os.replace(tmp_path, target)
    return target


def melt_path_for_cache(cfg, cache, date):
    """Melt path inside the cache's campaign folder, falling back to the legacy root layout,
    which validates the campaign first so a leftover root melt of another campaign is refused."""
    folder = cache.get("output_folder")
    if folder:
        p = melt_file_in(cfg, folder, date, cache.get("player_id"))
        if os.path.isfile(p):
            return p
    p = melt_path(cfg, date)
    p = cl.melt_file_exists(p) or p
    if cache.get("playthrough_id") and os.path.isfile(p):
        try:
            pt = cl.load_melt(p).get("playthrough_id")
        except Exception:
            pt = None
        if pt and str(pt) != str(cache["playthrough_id"]):
            llm.log(f"  [跳过] 根目录熔件 {os.path.basename(p)} 属其它战役 "
                    f"({pt}), 不用于本战役 ({cache['playthrough_id']})")
            return ""
    return p


def load_latest_melt(cfg, cache):
    """Melt dict of the cache's last save, or None. Prefers the campaign folder over the legacy
    root layout and, when the last-date melt is gone, falls back to the newest surviving source
    melt so biographies can still be produced; a melt of another campaign is discarded."""
    last = cache.get("last_date")
    if not last:
        return None

    def _load(path, label=""):
        try:
            melt = cl.load_melt(path)
        except Exception as e:
            llm.log(f"  熔件读取失败 ({path}): {e}")
            return None
        cpt = cache.get("playthrough_id")
        mpt = melt.get("playthrough_id")
        if cpt and mpt and str(cpt) != str(mpt):
            llm.log(f"  [跳过] {label or os.path.basename(path)} 属其它战役 "
                    f"({mpt}), 本缓存战役为 {cpt}")
            return None
        return melt

    p = melt_path_for_cache(cfg, cache, last)
    if os.path.isfile(p):
        melt = _load(p, last)
        if melt is not None:
            return melt
    for d in sorted(cache.get("sources") or [], key=cl.date_key, reverse=True):
        p2 = melt_path_for_cache(cfg, cache, d)
        if os.path.isfile(p2):
            melt = _load(p2, d)
            if melt is None:
                continue
            llm.log(f"  [回退] {last} 熔件缺失, 用最近现存熔件 {d} 生成")
            return melt
    return None


# --- Cache management (caches live in output/<house>/data/) ---------------------

def _session_folder_seq(folder):
    """Session folder sequence: 'name' -> ('name', 0), 'name2' -> ('name', 2)."""
    m = re.match(r"^(.*?)(\d+)$", str(folder or ""))
    return (m.group(1), int(m.group(2))) if m else (str(folder or ""), 0)


def _cache_pick_key(path, cache):
    """Priority key among several session caches of one player (larger wins): this watch run's
    folder > higher session folder sequence > newer last_date > newer mtime. A restarted old save
    has an earlier last_date, so the folder sequence is the stable "newest session" test."""
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
    """Existing cache path of a player in the output tree, then the legacy cache/; None when
    absent. playthrough_id filters by campaign because player ids are reused across campaigns;
    several sessions of one player and campaign resolve to the newest session."""
    base = cfg.get("output_dir", "")
    best = None
    if os.path.isdir(base):
        for dp, _dn, fns in os.walk(base):
            p = os.path.join(dp, f"player_{player_id}.json")
            if os.path.isfile(p):
                cache = cl.load_cache(p)
                # An empty cache (a corrupt file renamed aside by load_cache) must not route
                # new saves into the old session folder.
                if not cache.get("player_id"):
                    continue
                if playthrough_id is not None \
                        and cache.get("playthrough_id") != playthrough_id:
                    continue  # a cache of the same id from another campaign is excluded
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
    """All player caches as {(player_id, playthrough_id): (path, cache)}. The tuple key keeps
    caches of one id in different campaigns apart (ids are reused across campaigns), while
    several session folders of one campaign collapse to the newest session."""
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
                    continue  # a corrupt cache (renamed by load_cache) joins no campaign
                key = (cache.get("player_id") or pid,
                       cache.get("playthrough_id"))
                prev = out.get(key)
                if prev is None or _cache_pick_key(path, cache) > \
                        _cache_pick_key(prev[0], prev[1]):
                    out[key] = (path, cache)
    return out


def cache_path_for(cfg, player_id, playthrough_id=None):
    """Player cache path (legacy call site); None when it does not exist."""
    return find_cache_path(cfg, player_id, playthrough_id)


def folder_display(name):
    """Folder display name: a single-character CJK name gets the clan suffix, other names stay as is."""
    if len(name) == 1 and "\u4e00" <= name <= "\u9fff":
        return name + "氏"
    return name


def session_folder_name(cache):
    """Name basis for a session folder: house name (clan convention), then dynasty name, then
    character name. It deliberately takes the first house-history entry (the name at save start)
    and ignores a later rename, which would open a second folder on the next watch round."""
    pid = cache.get("player_id")
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    hist = [h for h in (rec.get("house_history") or []) if h.get("from")]
    name = ""
    if hist:
        name = hist[0].get("dynasty_name") or hist[0].get("house_name") or ""
    name = name or cache.get("dynasty_name") or cache.get("house_name") or ""
    if not name:
        pn = cache.get("player_name") or f"玩家{cache.get('player_id')}"
        name = pn
    return sanitize_folder_name(folder_display(name))


def sanitize_folder_name(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(name)).strip().strip(".") or "未知家族"


def determine_folder(name, output_dir):
    """Suffix a counter to a clashing folder name: base, base2, base3... The counter is the highest
    existing number plus one, since a lower number would break the "higher number = newer session"
    rule that find_latest_session_folder and _cache_pick_key rely on. An unnumbered base counts as 1."""
    base = sanitize_folder_name(name)
    max_seq = 0
    if os.path.isdir(output_dir):
        if os.path.isdir(os.path.join(output_dir, base)):
            max_seq = 1  # an unnumbered base folder counts as 1
        for fn in os.listdir(output_dir):
            m = re.match(re.escape(base) + r"(\d+)$", fn)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
    return f"{base}{max_seq + 1}" if max_seq else base


def find_latest_session_folder(name, output_dir):
    """Newest numbered session folder existing for this family (base -> base2), or None."""
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


# Watch-run session folder: one watch run is one new save period, so the first new save opens a
# freshly numbered folder, the same player keeps it, and a new player opens another one.
_WATCH_SESSION = {"active": False, "folder": None, "player_key": None}

# Console heartbeat interval for idle monitoring, in 60 s poll rounds (~half an hour at 30).
IDLE_HEARTBEAT_ROUNDS = 30


def resolve_output_folder(cfg, cache, continue_mode=False):
    """Session folder this cache should use (pure function). continue reuses the bound folder, the
    same playthrough's folder or the newest one and creates a folder only when none exists; watch
    always creates a newly numbered folder, since a run or a new player is a new save period."""
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
    # watch mode: the same player keeps this run's folder. A player change (succession or a new
    # game) reuses the folder of an existing cache of the same playthrough_id, else creates one.
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
    # Outside a watch run (standalone bio/rebuild): reuse the binding or the folder
    # of the same campaign, else create one.
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
    """Resolve the session folder, bind it into cache["output_folder"] and return the name."""
    folder = resolve_output_folder(cfg, cache, continue_mode)
    cache["output_folder"] = folder
    return folder


def session_data_path(cfg, cache, folder=None):
    """Cache file path: output/<house>/data/player_<id>.json."""
    folder = folder or resolve_output_folder(cfg, cache, True)
    return os.path.join(cfg.get("output_dir", ""), folder, "data",
                        f"player_{cache.get('player_id')}.json")


def save_session_cache(cfg, cache, continue_mode=False):
    """Write the cache into its session folder and persist the folder binding. bio_decades and
    bio_generated are merged from disk first, so flags set by the background biography thread
    between this read and write are not lost and a decade cannot run twice."""
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
    """Sort scalar of a 'y.m.d' date (year*372 + month*31 + day) for timeline gaps."""
    y, m, d = cl.date_key(s)
    return y * 372 + m * 31 + d


def active_cache(cfg):
    """(player_id, cache) of the campaign the newest save (by mtime) belongs to, matched by the
    envelope character name, then the save date among a cache's sources (closest timeline wins, since
    the largest last_date would drift to an old campaign), one melt for playthrough_id, then date."""
    caches = all_caches(cfg)  # {(pid, playthrough_id): (path, cache)}
    if not caches:
        return None, None

    def best(keys):
        return max(keys, key=lambda k: cl.date_key(caches[k][1].get("last_date") or ""))

    def campaign_pick(keys, newest_date):
        """Pick the current campaign among candidate caches: entries without a last_date rank
        last, then last_date >= the newest save, then the smallest gap, then the newer mtime."""
        ad = _date_scalar(newest_date or "")
        def key(k):
            path, c = caches[k]
            mt = _cache_mtime(path)
            ld = c.get("last_date")
            if not ld:
                return (-2, 0, mt)  # empty or broken cache ranks last
            v = _date_scalar(ld)
            behind = 1 if v < ad else 0  # behind the newest save -> lower priority
            return (-behind, -abs(ad - v), mt)
        return max(keys, key=key)

    try:
        saves = scan_saves(cfg.get("save_dir", ""))
    except Exception:
        saves = []
    if saves:
        newest = max(saves, key=lambda s: s["mtime"])
        hit = []
        # a) envelope character name -> cache (same normalization as the _catchup prefilter)
        nm = player_char_name(newest["player"])
        if nm:
            hit = [k for k, (_pp, c) in caches.items()
                   if player_char_name(c.get("player_name")) == nm]
        if not hit:
            # b) the save's date is already among a cache's sources; ties by timeline closeness
            hit = [k for k, (_pp, c) in caches.items()
                   if newest["date"] in (c.get("sources") or [])]
        if not hit:
            # c) melt the newest save once and match caches by playthrough_id (new player)
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
            if pt:  # within the campaign take the newest cache (the new ruler after succession)
                key = best([k for k, (_pp, c) in caches.items()
                            if c.get("playthrough_id") == pt])
            return key[0], caches[key][1]
    # d) nothing matched: fall back to the cache with the newest last_date
    key = best(list(caches))
    return key[0], caches[key][1]


def same_campaign(cache, melt, player_id):
    """Whether a save belongs to the campaign recorded by the cache: by playthrough_id
    when both sides have one, otherwise by player id."""
    pt = melt.get("playthrough_id")
    cpt = cache.get("playthrough_id")
    if cpt and pt:
        return cpt == pt
    if not cpt and not pt:
        return cache.get("player_id") == player_id
    # Only one side carries a playthrough id: the campaign cannot be confirmed, so differ
    return False


def player_char_name(name):
    """Character name after the last comma of an envelope name (a title may precede it)."""
    if not name:
        return ""
    return str(name).rsplit("，", 1)[-1].rsplit(",", 1)[-1].strip()


def _pending_catchup_saves(cfg, cache):
    """Saves of the current campaign still to catch up on (envelope-prefiltered, not yet melted)."""
    pid = cache.get("player_id")
    my_name = player_char_name(cache.get("player_name"))
    save_dir = cfg.get("save_dir", "")
    cache_path = find_cache_path(cfg, pid, cache.get("playthrough_id"))
    cache_mtime = os.path.getmtime(cache_path) if cache_path else 0.0
    last_dk = cl.date_key(cache.get("last_date") or "0.0.0")
    sources = set(cache.get("sources") or [])
    out = []
    for s in scan_saves(save_dir):
        if s["date"] in sources:
            continue
        if cl.date_key(s["date"]) <= last_dk:
            continue
        if cache_mtime and s["mtime"] <= cache_mtime:
            continue
        if my_name and player_char_name(s["player"]) != my_name:
            llm.log(f"  [跳过] {s['date']} {s['player']} 非本战役人物, 不读")
            continue
        out.append(s)
    return out


def _catchup(cfg, cache, continue_mode=False):
    """Catch up on the current campaign's new saves and return how many were merged. Only saves whose
    envelope character name equals the cached player name are melted, and a new save must be dated
    after the cache's last_date and written after the cache file, so earlier runs are not rescanned.
    The total is counted up front and each save logs its index and a rough ETA."""
    pid = cache.get("player_id")
    pending = _pending_catchup_saves(cfg, cache)
    total = len(pending)
    if total:
        llm.log(f"补录开始: 待处理 {total} 档")
    processed = 0
    t0 = time.time()
    for i, s in enumerate(pending, 1):
        eta = ""
        if processed:
            elapsed = time.time() - t0
            remain = elapsed / processed * (total - i + 1)
            eta = f", 约剩 {remain / 60:.0f} 分钟" if remain >= 60 else f", 约剩 {remain:.0f} 秒"
        # melt into the campaign folder output/<house>/data/, shared by successive players
        folder = resolve_output_folder(cfg, cache, continue_mode)
        mp = melt_file_in(cfg, folder, s["date"], pid)
        if os.path.isfile(mp) and melt_player_id(mp) not in (None, pid):
            mp = None  # the date file belongs to another campaign, so melt again
        if not mp or not os.path.isfile(mp):
            llm.log(f"  补录 {i}/{total} 熔化 {os.path.basename(s['path'])} "
                    f"({s['magic']}){eta} ...")
            try:
                mp = _melt_save_into(cfg, folder, s["date"], pid, s["path"])
            except Exception as e:
                llm.log(f"  熔化失败: {e}")
                continue
        else:
            llm.log(f"  补录 {i}/{total} 读取 {s['date']}{eta} ...")
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
                pid = player_id
            _prebuild_melt_index(mp, melt)   # later backfills read the sidecar directly
            new_deaths = []
            if cl.extract_snapshot(cache, melt, s["date"], _new_deaths=new_deaths):
                _recover_dead_memories(cfg, cache, new_deaths)
                save_session_cache(cfg, cache, continue_mode)
                processed += 1
                llm.log(f"  补录 {i}/{total} 并入 {s['date']}: "
                        f"相关人物 {len(cache['characters'])}")
                _cross_check_lineage(cfg, melt, player_id)
        except Exception as e:
            llm.log(f"  [跳过] {s['date']} 处理失败: {e}")
            continue
    return processed


# --- Biography generation and output -------------------------------------------

def _bio_pname(cache):
    """Identifier of the subject in biography file names: display name plus birth year, e.g.
    "<name>(844)", the year separating same-name kin so decade file names cannot collide. It is pinned
    into cache["bio_pname"] on first use, because name_full changes with a house founding or rename
    and a following file name would no longer match the earlier decades and regenerate them."""
    pinned = cache.get("bio_pname")
    if pinned:
        return pinned
    pid = cache.get("player_id")
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    pname = rec.get("name_full") or rec.get("name_zh") or f"玩家{pid}"
    birth = rec.get("birth") or ""
    by = str(birth).split(".")[0] if birth else ""
    name = f"{pname}({by})" if by and by.isdigit() else pname
    cache["bio_pname"] = name
    return name


def _reign_end(cache):
    """The subject's end-of-reign record, in which abdication (reign_end) outranks death
    (player_death): the final biography's file name and cutoff date stay pinned to the abdication
    date, so a death found later neither renames the file nor writes a second biography."""
    re_ = cache.get("reign_end") or {}
    if re_.get("date"):
        return re_
    return {}


def output_paths(cfg, cache, continue_mode=False, decade=None):
    """(folder, output file name) of a biography: the session folder plus the file name. A non-empty
    decade names the decade biography on its own, so it cannot clash with a living biography of the
    same date and be skipped; end of reign is reign_end (abdication) first, then player_death."""
    folder = resolve_output_folder(cfg, cache, continue_mode)
    pname = _bio_pname(cache)
    re_end = _reign_end(cache)
    death = cache.get("player_death")
    end_date = re_end.get("date") or (death or {}).get("date")
    if end_date:
        kind = "终传"                     # abdication keeps the same file kind
        dkey = cl.date_filekey(end_date)
    else:
        kind = "传记"
        dkey = cl.date_filekey(cache.get("last_date") or "")
    if decade:
        # A decade biography is dated by its data cutoff (the decade end), not by last_date.
        dkey = cl.date_filekey(_decade_cutoff(cache, decade) or cache.get("last_date") or "")
        fname = f"{pname}_传记_第{decade}个十年_{dkey}.md"
    else:
        fname = f"{pname}_{kind}_{dkey}.md"
    return folder, fname


def _decade_cutoff(cache, decade):
    """Data cutoff of the decade-th decade: start year + decade*10, January 1st, capped at last_date."""
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
    """Data cutoff of a biography: the decade end for a decade biography, otherwise the end of reign
    or the last save date. None means no truncation; reign_end outranks player_death."""
    if not decade:
        re_end = _reign_end(cache)
        death = cache.get("player_death") or {}
        return re_end.get("date") or death.get("date") or cache.get("last_date")
    return _decade_cutoff(cache, decade)


def tail_melt_candidate(cfg, cache):
    """Path of the earliest melt after the end date, or None. The end of reign falls between two yearly
    autosaves, so that melt is the only one recording the end-of-reign state (death date, cause, place,
    flags). _backfill_tail_deaths and tools/tests/snap.py share it, so snapshots and runs agree."""
    folder = cache.get("output_folder") or ""
    d = os.path.join(cfg.get("output_dir", ""), folder, "data")
    pat = re.compile(r"^melt_(\d+_\d{2}_\d{2})\.json(?:\.gz|\.xz)?$")
    cands = []
    if os.path.isdir(d):
        for fn in os.listdir(d):
            m = pat.match(fn)
            if m:
                date = ".".join(str(int(x)) for x in m.group(1).split("_"))
                cands.append((cl.date_key(date), os.path.join(d, fn)))
    last = cl.date_key(cache.get("last_date") or "0.0.0")
    cands = sorted((k, p) for k, p in cands if k > last)
    return cands[0][1] if cands else None


def tail_state_applies(cache):
    """Whether this biography needs the end state from the melt after the end date: an end date
    exists (abdication first, then death) and is later than cache["last_date"]."""
    if not cache:
        return False
    end = ((cache.get("reign_end") or {}).get("date")
           or (cache.get("player_death") or {}).get("date") or "")
    if not end:
        return False
    return cl.date_key(end) > cl.date_key(cache.get("last_date") or "0.0.0")


def _backfill_tail_deaths(cfg, cache):
    """Backfill the death records of characters who died in the final year, because they appear only in
    the save after their death once the subject dies after the last snapshot merge (January 1st). The
    earliest melt after cache["last_date"] supplies them for characters already on file with an empty
    death and a matching name. Returns (number backfilled, that melt or None), the melt also serving
    _merge_tail_title_flags."""
    p_tail = tail_melt_candidate(cfg, cache)
    if not p_tail:
        return 0, None
    try:
        melt = cl.load_melt(p_tail)
    except Exception as e:
        llm.log(f"  [终传回填失败] 载入死亡后档失败: {e}")
        return 0, None
    pid = cache.get("player_id")
    chars = cache.get("characters") or {}
    # Backfill threshold: characters who died after last_date.
    last = cl.date_key(cache.get("last_date") or "0.0.0")
    dead = list((melt.get("dead_unprunable") or {}).items())
    dead += list(((melt.get("characters") or {}).get("dead_prunable") or {}).items())
    n = 0
    for cid2, c2 in dead:
        if not isinstance(c2, dict):  # guard against a `none` entry
            continue
        cid2 = str(cid2)
        if pid is not None and cid2 == str(pid):
            continue
        rec = chars.get(cid2)
        if not rec or rec.get("death"):
            continue
        dd = c2.get("dead_data") or {}
        ddate = dd.get("date")
        if not ddate or cl.date_key(ddate) <= last:
            continue
        # identity check: the names must agree, so colliding ids cannot match
        cn = rec.get("name_zh") or rec.get("name_full") or ""
        dn = cl.name_zh(c2)
        if cn and dn and cl.zh(cn) != cl.zh(dn):
            continue
        rec["death"] = {
            "date": ddate,
            "reason": dd.get("reason"),
            "killer": dd.get("killer"),
            "liege": dd.get("liege"),
            "liege_title": dd.get("liege_title"),
            "named_title": dd.get("named_title"),
        }
        if (rec.get("last_location") or {}).get("province") is not None:
            rec["death"]["location_province"] = rec["last_location"]["province"]
        n += 1
    if n:
        path = find_cache_path(cfg, cache.get("player_id"),
                               cache.get("playthrough_id"))
        if path:
            cl.save_cache(cache, path)
        llm.log(f"  [终传回填] 尾年死者死亡记录 {n} 条写入 "
                f"{cache.get('output_folder') or cache.get('player_id')}")
    return n, melt


def _landed_titles_of(melt):
    """Landed title dict from a melt or from cache_lib.load_melt_landed_titles, both of which nest
    titles two levels deep (`melt["landed_titles"]["landed_titles"][tid]`, as Facts._lt reads)."""
    if not isinstance(melt, dict):
        return {}
    seg = melt.get("landed_titles")
    if isinstance(seg, dict):
        inner = seg.get("landed_titles")
        return inner if isinstance(inner, dict) else seg
    return melt


def _merge_tail_title_flags(melt, tail):
    """Merge the title flags of the melt after the end date into the melt being rendered: a final
    biography's as_of is the end date while load_latest_melt returns the melt of cache["last_date"], and
    `shogun_flag` on `e_japan` appears only in the melt after the death. Only
    `landed_titles[*].variables` is merged (the sole source of flags, read by `Facts._title_flags`);
    holder and vassal state keep following the `last_date` melt."""
    if not isinstance(melt, dict) or not isinstance(tail, dict):
        return 0
    lt = _landed_titles_of(melt)
    tlt = _landed_titles_of(tail)
    n = 0
    for tid, t in tlt.items():
        if not isinstance(t, dict):
            continue
        cur = lt.get(tid)
        if not isinstance(cur, dict):
            continue
        v = t.get("variables")
        if v is None or cur.get("variables") == v:
            continue
        cur["variables"] = v
        n += 1
    if n:
        llm.log(f"  [终了状态] 头衔旗标 {n} 枚按死后那一档 ({tail.get('date')}) 并入")
    return n


def generate_bio(cfg, cache, force=False, decade=None, continue_mode=False):
    """Generate a biography (final, living or the decade-th decade one) for a player and refresh the
    family's index.html; returns (output path, facts) or None. The background biography thread passes
    continue_mode=True, which resolves the output folder from the cache binding or the same campaign
    and never creates a folder, so a death during a watch run cannot corrupt the binding."""
    melt = load_latest_melt(cfg, cache)
    if melt is None:
        llm.log(f"玩家 {cache.get('player_id')} 无可用 melt, 跳过生成")
        return None
    as_of = _bio_as_of(cache, decade)
    # A death and an abdication can both fall after the last snapshot merge: backfill the records.
    pd = cache.get("player_death") or {}
    _re_end = _reign_end(cache)
    _end_date = _re_end.get("date") or pd.get("date")
    if tail_state_applies(cache):
        _n_tail, _tail_melt = _backfill_tail_deaths(cfg, cache)
        # The melt after the end date carries flags that exist only there (shogun_flag, joko_flag).
        _merge_tail_title_flags(melt, _tail_melt)
    # A decade biography uses the nickname of its own era, so the era-end melt overrides it (an empty
    # nickname included) and a nickname earned later cannot leak into an early decade. The cache's
    # nickname_history is preferred, since reading one string from the melt meant loading the whole
    # era-end file (6-18 s for 244 MiB); a cache without that history falls back to the melt.
    nickname_override = None
    if decade and as_of:
        last = cache.get("last_date")
        if last and cl.date_key(as_of) < cl.date_key(last):
            pid = cache.get("player_id")
            rec = (cache.get("characters") or {}).get(str(pid)) or {}
            nick = cl.nickname_at(rec, as_of)
            src = "缓存沿革"
            if nick is None:
                src = "时代熔件"
                try:
                    p_era = melt_path_for_cache(cfg, cache, as_of)
                    if os.path.isfile(p_era):
                        era = cl.load_melt(p_era)
                        raw = ((era.get("living") or {}).get(str(pid)) or {}).get(
                            "nickname_text")
                        nick = str(raw).strip() if raw is not None else ""
                except Exception as e:
                    llm.log(f"  按时代取绰号失败: {e}")
                    nick = None
            if nick is not None:
                nickname_override = {pid: str(nick).strip()}
                llm.log(f"  按时代取绰号 ({as_of}, {src}): {nick!r}")
    house, fname = output_paths(cfg, cache, continue_mode=continue_mode, decade=decade)
    out_dir = os.path.join(cfg.get("output_dir", ""), house)
    out_path = os.path.join(out_dir, fname)
    if not force:
        if decade:
            # Decade file names carry a moving date, so existence comes from any matching file on disk.
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
                                                 nickname_override=nickname_override,
                                                 campaign=_campaign_caches(cfg, cache))
    # Persist the folder binding, binding only: an existing output_folder whose directory still exists
    # keeps it, since rewriting it would point later lookups at a folder without cache or melts.
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


# --- Single-save processing and death cross-checks ------------------------------

def _process_save(cfg, save, continue_mode=False):
    """Melt and merge one save (watch path): a temp melt, then the player/campaign folder; returns
    (player_id, playthrough_id) or None. A merge exception cleans up the temp melt and is re-raised,
    so the caller records the failure and retries next round."""
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
        # Filter by campaign: player ids are reused, and without it an old campaign's cache loads.
        path0 = find_cache_path(cfg, player_id, melt_pt)
        cache = cl.load_cache(path0 or "", fresh=True)  # an independent copy for extraction
        # Last gate: a campaign that still disagrees rebuilds the cache empty, so no memory or title
        # history of the old campaign enters the new one.
        if cache.get("player_id") is not None and not same_campaign(cache, melt, player_id):
            llm.log(f"  {date}: 缓存战役与存档战役不一致 (玩家id复用/新局), "
                    f"从空缓存重建")
            cache = cl.new_cache()
        # Dedup: with continue a date already among the sources drops the temp melt and is skipped,
        # while a watch run is a new save period and always merges into a newly numbered folder;
        # repeats inside one run are caught by the mtime and date checks in step_watch.
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
        # First save of a new session: a folder differing from the cache's own means the old session
        # data is dropped and the cache rebuilt empty from this save, with nothing stitched across.
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
        mp = _move_melt_into(cfg, folder, date, player_id, tmp)
        _prebuild_melt_index(mp, melt)   # later backfills read the sidecar directly
        _recover_dead_memories(cfg, cache, new_deaths)
        save_session_cache(cfg, cache, continue_mode)
        llm.log(f"  并入 {date}: 玩家 {cache.get('player_name')} (id={cache.get('player_id')}), "
                f"相关人物 {len(cache['characters'])}")
        _cross_check_lineage(cfg, melt, player_id)
        return player_id, melt_pt
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _prebuild_melt_index(mp, melt):
    """Build the memory archive sidecar of a melt while it is being merged. Backfill reads the save just
    before a death, so X's sidecar is needed once X+1 merges, and building it here avoids a second full
    parse (18.2 s for 244 MiB against 4 s to build and store). An existing sidecar is kept, and a
    failure is only logged because the sidecar is derived and falls back to the lazy path."""
    if not mp or not melt or not os.path.isfile(mp):
        return None
    try:
        if any(os.path.isfile(p) for p in cl._melt_index_variants(mp)):
            return None
        t0 = time.time()
        path = cl.save_melt_index(mp, melt)
        llm.log(f"  [边车] {os.path.basename(mp)} 记忆归档已预建 "
                f"({time.time() - t0:.0f}s)")
        return path
    except Exception as e:
        llm.log(f"  [边车] {os.path.basename(mp)} 预建失败: {e}")
        return None


def _recover_dead_memories(cfg, cache, new_deaths=None):
    """Restore the memories of cached characters that are dead with none left (the game clears them on
    death, while the autosave before it still holds them); returns the number restored.

    new_deaths limits the work to the ids found dead by this merge, so the scan does not grow with the
    campaign, and the sidecar archive (~20 MB) is preferred over a full old melt of up to 160 MB."""
    sources = cache.get("sources") or []
    # candidates: dead, no memories left, and (when new_deaths is given) newly dead here
    pending = []
    for cid, rec in (cache.get("characters") or {}).items():
        d = rec.get("death") or {}
        ddate = d.get("date")
        if not ddate or rec.get("memories"):
            continue
        if new_deaths is not None and int(cid) not in new_deaths:
            continue
        # save before the death: the newest source dated earlier than the death
        before = [s for s in sources if cl.date_key(s) < cl.date_key(ddate)]
        if not before:
            continue
        mp = melt_path_for_cache(cfg, cache, before[-1])
        if not os.path.isfile(mp):
            continue
        pending.append((cid, mp, ddate, before[-1], rec))
    if not pending:
        return 0
    # group by source save, so each melt (or its archive) is read once
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
                            f"死于{ddate}, 从{src}档{('归档' if via_index else '')}恢复 {n} 条记忆",
                            detail=True)
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
        chars = cl.all_characters(melt)  # build the all-character index once per melt
        for cid, ddate, src, rec in items:
            try:
                n = cl.recover_dead_memories_from(melt, cache, int(cid), chars=chars)
                if n:
                    llm.log(f"  [回溯] 角色 {cid} ({rec.get('name_zh') or rec.get('name_full') or ''}) "
                            f"死于{ddate}, 从{src}档恢复 {n} 条记忆", detail=True)
                    recovered += 1
            except Exception as e:
                llm.log(f"  [回溯失败] 角色 {cid}: {e}")
        try:
            # build and persist the archive lazily, so later backfills read the sidecar
            cl.save_melt_index(mp, melt)
            llm.log(f"  [归档] {os.path.basename(mp)} 记忆归档已生成", detail=True)
        except Exception as e:
            llm.log(f"  [归档失败] {os.path.basename(mp)}: {e}")
    if recovered:
        llm.log(f"死角色记忆回溯: {recovered} 个角色补全记忆")
    return recovered


def _cross_check_deaths(cfg, melt, current_player):
    """Look for a previous player character's death among this save's dead_unprunable, verifying
    identity by name (ids are reused across campaigns) and by a death date after that character's last
    living save. Caches are indexed by id once, and a same-campaign cache is preferred."""
    caches = all_caches(cfg)  # {(player_id, playthrough_id): (path, cache)}
    melt_pt = melt.get("playthrough_id")
    for cid, c in (melt.get("dead_unprunable") or {}).items():
        if not isinstance(c, dict):  # guard against a `none` entry (broken or half-written save)
            continue
        cid = int(cid)
        if cid == current_player:
            continue
        hits = [v for k, v in caches.items() if k[0] == cid]
        if not hits:
            continue
        hits.sort(key=lambda hv: hv[1].get("playthrough_id") != melt_pt)
        for path, prev in hits:
            # Another campaign's cache never takes this death record: character ids are reused, and
            # same-campaign caches sort first, so only other campaigns remain here.
            prev_pt = prev.get("playthrough_id")
            if melt_pt and prev_pt and str(prev_pt) != str(melt_pt):
                continue
            dd = c.get("dead_data") or {}
            if not dd.get("date"):
                continue
            if prev.get("player_death") is not None:
                continue
            # identity check: the names must agree
            rec = (prev.get("characters") or {}).get(str(cid)) or {}
            cached_name = rec.get("name_zh") or rec.get("name_full") or ""
            dead_name = cl.name_zh(c)
            if cached_name and dead_name and cl.zh(cached_name) != cl.zh(dead_name):
                continue  # colliding id, not the same person
            # the death date must be later than that character's last living save
            if cl.date_key(dd.get("date")) <= cl.date_key(prev.get("last_date") or "0.0.0"):
                continue
            prev["player_death"] = {
                "date": dd.get("date"),
                "reason": dd.get("reason"),
                "killer": dd.get("killer"),
                "kills": dd.get("kills") or [],  # one data source of the assassin chapter
            }
            # A final biography triggers only once the newest save's played character is no longer the
            # previous subject, so this save's legacy chain must already hold the successor; copying it
            # into the previous cache is what lets that final biography name the successor.
            _lg = (melt.get("played_character") or {}).get("legacy") or []
            _chain = [{"cid": e.get("character"), "date": e.get("date")}
                      for e in _lg
                      if isinstance(e, dict) and isinstance(e.get("character"), int)]
            if _chain:
                prev["played_legacy"] = _chain
            cl.save_cache(prev, path)
            llm.log(f"  [检测] 前代玩家 {cid} ({cached_name}) 死于 {dd.get('date')}, "
                    f"原因 {dd.get('reason')} — 待生成终传")
            break


def _cross_check_lineage(cfg, melt, current_player):
    """Detect both ways a subject's tenure can end: first a death
    (_cross_check_deaths), then a change of subject that ends the reign while the former
    one lives (abdication, tonsure and retirement, deposition, loss of all land)."""
    _cross_check_deaths(cfg, melt, current_player)
    return _cross_check_reign_ends(cfg, melt, current_player)


# --- A reign ends without a death: the subject changes while the former one lives ---
# A Japanese Buddhist decision ("seek the pure land") makes the character tonsure and abdicate;
# `tgp_renounce_estate_effect` hands the headship and titles to the heir and calls
# `set_player_character`
# (game/common/scripted_effects/10_dlc_tgp_japan_scripted_effects.txt), leaving the former character
# alive, so a trigger chain that only writes player_death on an actual death misses the biography.
# Per-decision special cases are not an option: `set_player_character` appears in dozens of places
# across the game (dynastic rise and fall, usurpation, landless adventurers, nomadic kurultai, great
# holy war land grants, RICE files) and keeps growing, so only the shape is tested: the succession
# chain changed hands while the previous character is still alive.
_REIGN_END_WORD = {
    "tonsured": "剃发退位",      # Buddhist "seek the pure land": add_trait = devoted + give up the estate
    "abdicated": "退隐让位",     # generic "renounce head of house": only adds ep3_renounced_estate
    "landless": "去位转无地",    # lost all land
    "unknown": "让位",           # abdication without an attributed cause
}


def _lineage_chain(melt):
    """This save's `played_character.legacy` as [(cid, date), ...] in order, the last entry
    being the character currently played."""
    out = []
    for e in ((melt.get("played_character") or {}).get("legacy") or []):
        if not isinstance(e, dict):
            continue
        cid = e.get("character")
        if isinstance(cid, int):
            out.append((cid, e.get("date") or ""))
    return out


def _char_has_trait(melt, c, name):
    """Whether a character entry carries the trait `name`, looked up in the melt's top-level
    `traits_lookup` array."""
    tl = melt.get("traits_lookup") or []
    for t in (c.get("traits") or []):
        if isinstance(t, int) and 0 <= t < len(tl) and tl[t] == name:
            return True
    return False


def _reign_end_kind(melt, c):
    """Nature of an abdication, from save fields only: the `devoted` trait means `tonsured`, only the
    `ep3_renounced_estate` modifier means `abdicated`, no domain left means `landless`, anything else is
    `unknown`. Landlessness cannot be the criterion, since a character may abdicate and keep land, so it
    is only the fallback."""
    if _char_has_trait(melt, c, "devoted"):
        return "tonsured"
    if "ep3_renounced_estate" in cl._char_modifier_names(c):
        return "abdicated"
    if not ((c.get("landed_data") or {}).get("domain") or []):
        return "landless"
    return "unknown"


def _cross_check_reign_ends(cfg, melt, current_player):
    """Record a previous subject whose reign ended without a death as prev["reign_end"], copying the
    succession chain into that cache so its final biography can name the successor; returns how many
    entries were written.

    All criteria come from save fields, never a decision id: this save's played_character.legacy dates
    the succession, the former subject is still in `living` (so it is no death), death wins when the
    subject sits in `dead_unprunable`, and the date must follow the cache's last_date with matching
    names. Absence from `dead_unprunable` proves nothing, since the dead are pruned into
    `characters.dead_prunable`; with no `living` entry either, nothing is written."""
    rows = _lineage_chain(melt)
    if len(rows) < 2:
        return 0
    caches = all_caches(cfg)
    melt_pt = melt.get("playthrough_id")
    living = cl._living(melt)
    dead_un = cl._dead_unprunable(melt)
    n = 0
    for i in range(len(rows) - 1):
        cid = rows[i][0]
        succ_cid, succ_date = rows[i + 1]
        if cid == current_player or not succ_date:
            continue
        if str(cid) in dead_un:          # inherited by death -> the existing death path
            continue
        c = living.get(str(cid))
        if not isinstance(c, dict):      # "not dead" cannot be confirmed -> write nothing
            continue
        hits = [v for k, v in caches.items() if k[0] == cid]
        if not hits:
            continue
        hits.sort(key=lambda hv: hv[1].get("playthrough_id") != melt_pt)
        for path, prev in hits:
            prev_pt = prev.get("playthrough_id")
            if melt_pt and prev_pt and str(prev_pt) != str(melt_pt):
                continue
            if prev.get("player_death") is not None \
                    or prev.get("reign_end") is not None:
                continue
            if cl.date_key(succ_date) <= cl.date_key(prev.get("last_date") or "0.0.0"):
                continue
            rec = (prev.get("characters") or {}).get(str(cid)) or {}
            cached_name = rec.get("name_zh") or rec.get("name_full") or ""
            now_name = cl.name_zh(c)
            if cached_name and now_name and cl.zh(cached_name) != cl.zh(now_name):
                continue                 # colliding id, not the same person
            kind = _reign_end_kind(melt, c)
            succ_c = living.get(str(succ_cid)) or dead_un.get(str(succ_cid)) or {}
            prev["reign_end"] = {
                "date": succ_date,       # successor's date = former subject's end of reign
                "kind": kind,            # tonsured / abdicated / landless / unknown
                "alive": True,           # still in this save's living section, so no death
                "successor": int(succ_cid),
                "successor_name": cl.name_zh(succ_c) or "",
                "evidence": "played_character.legacy",
            }
            # copy the succession chain into the previous cache, as on the death path
            prev["played_legacy"] = [{"cid": c_, "date": d_} for c_, d_ in rows]
            cl.save_cache(prev, path)
            llm.log(f"  [更替] 前代玩家 {cid} ({cached_name}) 在位终于 {succ_date}，"
                    f"非死亡（{_REIGN_END_WORD.get(kind, '让位')}），"
                    f"后任 {succ_cid} — 待生成终传")
            n += 1
            break
    return n


_BIO_LOCK = threading.Lock()
_BIO_PENDING = set()        # queued tasks ((pid, pt), kind, decade), deduplicated; "death"/"decade"
_BIO_LAST_TRY = {}          # ((pid, pt), kind, decade) -> time.monotonic() of the last attempt
_BIO_RETRY_SECONDS = 300    # shortest wait before retrying a failed generation
_BIO_WORKER = None
_DECADE_SKIP_LOGGED = set()  # players already logged as "decade complete but dead, skipped"


def _ensure_bio_worker(cfg):
    """Start the background final-biography thread once, shared by watch/continue/scan. Producing a
    biography takes several LLM calls and minutes, so the poll loop never blocks on it."""
    global _BIO_WORKER
    if _BIO_WORKER is None:
        _BIO_WORKER = threading.Thread(target=_bio_worker_loop,
                                       args=(cfg,), daemon=True)
        _BIO_WORKER.start()


def _campaign_caches(cfg, anchor):
    """Player caches of the campaign anchor belongs to (same playthrough_id) as
    {player_id: cache}; an anchor without a playthrough id returns only itself. Callers
    therefore look at the current campaign's players instead of scanning old campaigns."""
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
    """Queue a final biography for every cache whose subject's tenure ended without one, whether by
    death (player_death) or not (reign_end); returns how many were queued. A failure leaves
    bio_generated unset so the next round retries after a backoff; caches limits the scope."""
    _ensure_bio_worker(cfg)
    if caches is None:
        caches = {k: c for k, (_path, c) in all_caches(cfg).items()}
    else:
        # A caller may pass {player_id: cache} (int keys, from _campaign_caches), so the
        # keys are normalized to the (player_id, playthrough_id) tuples worker tasks use
        caches = {(k if isinstance(k, tuple) else (k, c.get("playthrough_id"))): c
                  for k, c in caches.items()}
    queued = 0
    now = time.monotonic()
    with _BIO_LOCK:
        for key, cache in caches.items():
            re_end = _reign_end(cache)
            death = cache.get("player_death")
            if not (re_end or death) or cache.get("bio_generated"):
                continue
            if not cfg.get("auto_bio_on_death", True):
                llm.log(f"[待生成] 玩家 {cache.get('player_name')} (id={key[0]}) 位终于 "
                        f"{re_end.get('date') or death.get('date')}, "
                        f"但 auto_bio_on_death=false, 跳过")
                continue
            qkey = (key, "death", None)
            if qkey in _BIO_PENDING:
                continue
            if now - _BIO_LAST_TRY.get(qkey, 0) < _BIO_RETRY_SECONDS:
                continue
            _BIO_PENDING.add(qkey)
            queued += 1
            if re_end:
                llm.log(f"[触发] 玩家 {cache.get('player_name')} (id={key[0]}) 已于 "
                        f"{re_end.get('date')} 在位终结（非死亡), 后任 "
                        f"{re_end.get('successor_name') or re_end.get('successor')} "
                        f"— 排队生成终传")
            else:
                llm.log(f"[触发] 玩家 {cache.get('player_name')} (id={key[0]}) 已死于 "
                        f"{death.get('date')} — 排队生成终传")
    if queued:
        llm.log(f"待生成 {queued} 篇终传")
    return queued


def _completed_decades(cache):
    """Complete decade numbers [1, 2, ...] from the first data year, where decade k spans
    [start + (k-1)*10, start + k*10); the first exists only once the data covers a full 10 years."""
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
    """Decade numbers already generated, read from the decade biography files in the output folder.
    Disk is authoritative because a file name carries its build date and bio_decades can be lost to a
    concurrent write, while files survive a crash and are shared between processes."""
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
    """Queue decade biographies for living players who completed a new decade; returns how many were
    queued. A decade biography draws on all data so far, so 40 years of rule read 40 years of data, and
    a subject whose tenure ended gets no more because the final biography covers the whole life."""
    _ensure_bio_worker(cfg)
    if caches is None:
        caches = {k: c for k, (_path, c) in all_caches(cfg).items()}
    else:
        # normalize to (player_id, playthrough_id) tuple keys, as in _auto_bio
        caches = {(k if isinstance(k, tuple) else (k, c.get("playthrough_id"))): c
                  for k, c in caches.items()}
    queued = 0
    now = time.monotonic()
    with _BIO_LOCK:
        for key, cache in caches.items():
            pid = key[0]
            _re_end = _reign_end(cache)
            if cache.get("player_death") or _re_end:
                ds = _completed_decades(cache)
                if ds and key not in _DECADE_SKIP_LOGGED:
                    _DECADE_SKIP_LOGGED.add(key)
                    llm.log(f"  [十年] 玩家 {cache.get('player_name')} (id={pid}) "
                            f"数据已满十年 {ds} 但已终了"
                            f"（{'让位' if _re_end else '已死亡'}), "
                            f"按设计跳过 (终传覆盖一生)")
                continue
            # generated = cache flags plus files on disk, so a concurrently overwritten
            # bio_decades cannot trigger the same decade twice
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
    """Background loop: take a queued task (final or decade biography), generate it, then set the flag.

    Flags are flipped on the newest cache on disk rather than written from memory, so data merged
    meanwhile survives. The queue key carries (player_id, playthrough_id), because ids are reused
    across campaigns and generation must write to its own campaign's cache."""
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
                re_end = _reign_end(cache)
                if not (death or re_end) or cache.get("bio_generated"):
                    continue
                out = generate_bio(cfg, cache, continue_mode=True)  # background resolves by binding
                if out:
                    out_path, _ = out
                    cur = cl.load_cache(path, fresh=True)  # an independent copy for the write
                    cur["bio_generated"] = True
                    cl.save_cache(cur, path)
                    llm.log(f"终传已生成: {out_path}")
            elif kind == "decade":
                if cache.get("player_death") or _reign_end(cache):
                    continue  # tenure ended (death or abdication): the final biography covers it
                if (decade in (cache.get("bio_decades") or [])
                        or decade in _generated_decades_on_disk(cfg, cache)):
                    continue  # the decade file or flag already exists, so do not generate again
                out = generate_bio(cfg, cache, decade=decade, continue_mode=True)  # by binding
                if out:
                    out_path, _ = out
                    cur = cl.load_cache(path, fresh=True)
                    cur.setdefault("bio_decades", []).append(decade)
                    cl.save_cache(cur, path)
                    llm.log(f"十年传记已生成 (第{decade}个十年): {out_path}")
        except Exception as e:
            # The catch-all also logs the last traceback frames: `str(e)` alone leaves an
            # IndexError such as "string index out of range" with no location at all.
            _tb = traceback.format_exc().strip().split("\n")
            llm.log(f"传记生成失败 (将重试): {e}"
                    + (f" | {_tb[-2].strip()} @ {_tb[-3].strip()}"
                       if len(_tb) >= 3 else ""))
        finally:
            with _BIO_LOCK:
                _BIO_LAST_TRY[key] = time.monotonic()


# --- watch / continue / scan ---------------------------------------------------

def _cleanup_tmp_melts(cfg):
    """Delete leftovers of an abnormal exit: temp melts (.tmp_melt_*.json) and the partial archives of
    an interrupted compaction (melt_*.json.xz.tmp, .gz.tmp, .mig.tmp), which would fake progress."""
    dirs = []
    data_dir = cfg.get("data_dir", "")
    if os.path.isdir(data_dir):
        dirs.append(data_dir)
    out_dir = cfg.get("output_dir", "")
    if os.path.isdir(out_dir):
        for folder in os.listdir(out_dir):
            d = os.path.join(out_dir, folder, "data")
            if os.path.isdir(d):
                dirs.append(d)
    n = 0
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for fn in names:
            low = fn.lower()
            if not ((fn.startswith(".tmp_melt_") and fn.endswith(".json"))
                    or low.endswith(".xz.tmp")
                    or low.endswith(".gz.tmp")
                    or low.endswith(".mig.tmp")):
                continue
            try:
                os.remove(os.path.join(d, fn))
                n += 1
            except OSError:
                pass
    if n:
        llm.log(f"清理残留临时熔件 {n} 份")


def _newest_save(save_dir):
    """The save with the newest mtime, or None. Only it is read: autosave_1/2 are older copies rotated
    out of autosave.ck3 and cannot hold independent new data."""
    saves = scan_saves(save_dir)
    return max(saves, key=lambda s: s["mtime"]) if saves else None


def _wait_save_stable(path, seconds=2.0, attempts=4):
    """Wait until the save file's size and mtime are unchanged across consecutive checks, so
    that melting never starts while the game is still writing and a half-written save is
    never read."""
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
    """watch/continue: take the startup moment as the baseline and process only later saves.

    continue first catches up on the current campaign's newer saves; watch monitors straight away, and
    without a cache the first new save establishes the campaign. Each round handles only the save with
    the newest mtime, because rotated copies such as autosave_1/2 merely repeat autosave.ck3, and waits
    for the file to be stable (_wait_save_stable) before melting. Dedup works by file (the last seen
    mtime) and by date, where the same date may reappear after the player changes; _process_save skips
    a date that is already among the cache's sources in continue mode. A failure never stops the loop
    and the next round retries, and pending final biographies are checked every round in the background
    thread."""
    global _WATCH_SESSION
    # watch opens a new save period and always creates a folder; continue reuses one and
    # keeps the per-run session folder disabled
    _WATCH_SESSION["active"] = not continue_mode
    _WATCH_SESSION["folder"] = None
    _WATCH_SESSION["player_key"] = None
    save_dir = cfg.get("save_dir", "")
    # The baseline is taken first: startup work below can take minutes, and a save written meanwhile
    # still counts as new; taking it later would skip those saves forever.
    baseline = max((s["mtime"] for s in scan_saves(save_dir)), default=0)
    _cleanup_tmp_melts(cfg)
    # Startup performs no localization check and rebuilds no table: tables are built by hand
    # (build-tables), and an outdated one only prints a line when loaded lazily. The baseline order is
    # unchanged (baseline first) so saves written during startup are not missed.
    # Cold melts are archived in the background every 10 minutes; a continue run catches up in bursts,
    # so its archiving thread waits for _catchup and never competes with xz preset 6 for core and disk,
    # while watch starts archiving immediately.
    if not continue_mode:
        _ensure_compact_worker(cfg)
    llm.log("监控存档中 (只处理本程序启动后保存的新存档)...")
    llm.log(f"基准时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(baseline))} "
            f"— 更早的老存档一律不读、不记录")
    # The continue session anchor is resolved once at startup and then follows the player of a newly
    # merged save (succession or new game), instead of a global recomputation every round that could
    # drift to an old campaign.
    continue_anchor = None
    if continue_mode:
        pid, cache = active_cache(cfg)
        if cache:
            llm.log(f"续传模式: 继续战役 {cache.get('player_name')} (id={pid}, "
                    f"家族={cache.get('house_name')}, 最后存档={cache.get('last_date')})")
            n = _catchup(cfg, cache, continue_mode=True)
            if n:
                llm.log(f"补录完成: 并入 {n} 个新档")
            else:
                llm.log("补录完成: 当前战役无新档")
            continue_anchor = cache
        else:
            llm.log("续传模式: 暂无缓存, 等同 watch (首个新存档建立战役)")
        _ensure_compact_worker(cfg)
    # Startup check: continue uses the current campaign's cache; watch has no campaign yet and
    # waits until the first new save establishes one.
    if continue_anchor:
        _auto_bio(cfg, _campaign_caches(cfg, continue_anchor))
        _auto_decade_bios(cfg, _campaign_caches(cfg, continue_anchor))
    # Monitoring loop: newest save only, session dedup, wait for a stable file, and checks
    # scoped to the current campaign
    interval = cfg.get("poll_interval_seconds", 60)
    last_mtime = None      # mtime of the last processed file, so one file is not handled twice
    last_date = None       # last processed date: a re-save or rotated copy of it is not merged again
    last_player = None     # player of the last processed save; a change means a new game, where the
                           # same date may legitimately reappear
    watch_anchor = None    # watch mode: cache built by the first new save; later rounds check only
                           # that campaign
    idle_rounds = 0        # consecutive rounds with no new save; the console reports the first
                           # idle round and then one every IDLE_HEARTBEAT rounds, the rest go to
                           # the log file
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
                    last_date = None  # new game or new player: the same date may appear again
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
                        # Processing finished (merged, or judged duplicate), so remember this file and
                        # date; a failure advances nothing and is retried next round
                        last_mtime = s["mtime"]
                        last_date = s["date"]
                        if nm:
                            last_player = nm
                    except Exception as e:
                        llm.log(f"  处理失败, 下轮重试: {os.path.basename(s['path'])}: {e}")
            if processed:
                llm.log(f"并入 {processed} 个新档")
                idle_rounds = 0
            else:
                # An idle round no longer prints on every poll (60 s apart); the console keeps
                # a heartbeat instead
                idle_rounds += 1
                msg = f"无新存档 (已空转 {idle_rounds} 轮)"
                if idle_rounds == 1 or idle_rounds % IDLE_HEARTBEAT_ROUNDS == 0:
                    llm.log(msg)
                else:
                    llm.log(msg, detail=True)
            # Checks look at the current campaign only: the anchor fixed at startup for continue
            # (following the player of a newly merged save so a succession is not missed), the new
            # saves' campaign for watch. Old campaigns' caches are never scanned.
            anchor = None
            if continue_mode:
                if processed_player:
                    # load filtered by campaign: player ids are reused across campaigns
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
                _auto_bio(cfg, caches)  # every round checks pending final biographies of this campaign
                _auto_decade_bios(cfg, caches)  # every round checks pending decade biographies
        except Exception as e:
            llm.log(f"扫描异常: {e}")
        time.sleep(interval)


def step_scan(cfg):
    """One catch-up pass: only current-campaign saves dated after the cache and written after
    the cache file. A save whose envelope character name disagrees is skipped without melting,
    and no other campaign is read."""
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


# --- Other commands ------------------------------------------------------------

def step_status(cfg):
    caches = all_caches(cfg)
    if not caches:
        llm.log("暂无玩家缓存 (运行 watch 或 continue 建立素材库)")
        return
    for key in sorted(caches, key=lambda k: (k[0], str(k[1]))):
        path, cache = caches[key]
        n_mem = sum(len(c.get("memories") or []) for c in cache["characters"].values())
        death = cache.get("player_death")
        dstr = (f"已死于 {death.get('date')} ({death.get('reason')})"
                + (" [终传已生成]" if cache.get("bio_generated") else " [待生成终传]")
                if death else "在世")
        house = cache.get("house_name") or "(家族未定)"
        pt = cache.get("playthrough_id") or "—"
        print(f"玩家 {key[0]}: {cache.get('player_name')} (战役 {pt})")
        print(f"  家族: {house} | 来源档: {cache.get('sources')} | 最后日期: {cache.get('last_date')}")
        print(f"  相关人物: {len(cache['characters'])} | 累计记忆: {n_mem} | 状态: {dstr}")
        print()


def step_bio(cfg, player_id=None, decade=None):
    """Generate a biography by hand; player_id defaults to the current campaign's player and a non-empty
    decade selects that decade biography instead. Several caches sharing one id prefer the current
    campaign's playthrough_id and otherwise the newest last_date, which the log reports."""
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
        # one id across campaigns: prefer the current campaign (active_cache reads the newest save)
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
    """Walk every melt as (campaign folder or None, absolute path, date). Campaign folders come first,
    the legacy root layout is still accepted, and `.json`, `.json.gz` and `.json.xz` are recognized."""
    pat = re.compile(r"melt_(\d+_\d{2}_\d{2})(?:_p\d+)?\.json(?:\.gz|\.xz)?$")
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
    """Rebuild caches from the melts in the campaign folders, one per player and session folder, into
    output/<house>/data/. The legacy root layout is still accepted, and melts of one player in different
    session folders are rebuilt independently, so nothing is stitched across sessions."""
    melts = _iter_melts(cfg)
    if not melts:
        llm.log("未找到 melt 文件 (战役文件夹 data/ 或根 data/)")
        return
    llm.log(f"重建缓存: {len(melts)} 份 melt")
    built = {}  # player_id -> (folder, cache); another session folder starts a new cache
    for folder, path, date in melts:
        melt = cl.load_melt(path)
        player_id = cl.find_player(melt)
        if player_id is None:
            llm.log(f"  {date}: 无玩家, 跳过")
            continue
        ent = built.get(player_id)
        if not folder:
            # legacy root melt: merge into the previous root cache and resolve the session
            # folder once the first save has been merged
            if ent is None:
                prev = cl.load_cache(
                    find_cache_path(cfg, player_id, melt.get("playthrough_id")) or "")
                cache = cl.new_cache()
                if prev.get("player_death"):
                    cache["player_death"] = prev["player_death"]
                if prev.get("reign_end"):        # an abdication record must not be lost
                    cache["reign_end"] = prev["reign_end"]
                if prev.get("bio_generated"):
                    cache["bio_generated"] = prev["bio_generated"]
                if prev.get("bio_decades"):
                    cache["bio_decades"] = prev["bio_decades"]  # keep the decade flags
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
            # The melt's campaign folder decides; another folder for the same player is another
            # session, rebuilt from that folder's melts only.
            if ent is None or ent[0] != folder:
                prev = cl.load_cache(os.path.join(
                    cfg.get("output_dir", ""), folder, "data",
                    f"player_{player_id}.json"))
                cache = cl.new_cache()
                if prev.get("player_death"):
                    cache["player_death"] = prev["player_death"]
                if prev.get("reign_end"):        # an abdication record must not be lost
                    cache["reign_end"] = prev["reign_end"]
                if prev.get("bio_generated"):
                    cache["bio_generated"] = prev["bio_generated"]
                if prev.get("bio_decades"):
                    cache["bio_decades"] = prev["bio_decades"]  # keep the decade flags
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
    """Migrate to the current layout: legacy cache/*.json move to output/<house>/data/ bound to their old
    folder name, a historical folder takes the house name as fixed later, and caches are rebuilt."""
    out = cfg.get("output_dir", "")
    legacy = cfg.get("cache_dir", "")
    rename_map = {}
    # 1) migrate the legacy caches, binding the old folder name first
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
    # 2) rename the historical folder, data/ included
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
    # 3) rebuild the caches
    step_rebuild_cache(cfg)
    llm.log("迁移完成: 缓存已按 v4 重建")


def _legacy_folder_for(cfg, cache, pid):
    """Session folder for a legacy cache during migration: house name (with and without the
    clan suffix), then character name, then the same campaign, matching an existing folder at
    each step."""
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
    """Simulate the subject's death to exercise the automatic final-biography path."""
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


# --- Main entry points ---------------------------------------------------------

def step_index_melts(cfg):
    """Pre-build the memory archive sidecar (melt_<date>_idx.json) of every melt. Backfill prefers the
    archive and loads a full 160 MB melt only once when it is missing, so this fills in historical melts
    after an upgrade and can be rerun for new ones."""
    melts = _iter_melts(cfg)
    if not melts:
        llm.log("未找到 melt 文件 (战役文件夹 data/ 或根 data/)")
        return
    llm.log(f"预建记忆归档: {len(melts)} 份熔件")
    built = skipped = failed = 0
    for _folder, path, date in melts:
        idx_path = cl.melt_index_path(path)
        # the sidecar may already be archived, so both suffixes count as present
        if any(os.path.isfile(p) for p in cl._melt_index_variants(path)):
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


def _compress_file(path, codec="xz", out_path=None):
    """Archive a cold melt or sidecar: atomic write plus a round-trip sha1 check, deleting the source
    only on success; a path already ending in `.gz`/`.xz` comes back as is unless it is migrated.

    The default codec xz (lzma preset 6) shrinks a 244 MiB melt from 37.1 MB with gzip to 22.8 MB, at
    46 s to compress and 1.22 s to decompress. The round-trip check is not optional, because these melts
    are the only copy of 60 years of saves: a mismatch removes the partial file and raises."""
    p = str(path)
    low = p.lower()
    if out_path is None:
        if low.endswith((".gz", ".xz")):
            return p
        out_path = p + (".xz" if codec == "xz" else ".gz")
    out = str(out_path)
    if os.path.isfile(out):
        return out
    tmp = out + ".tmp"
    use_xz = str(codec).lower() == "xz"
    h_in = hashlib.sha1()
    try:
        with open(p, "rb") as fi:
            opener = (lzma.open(tmp, "wb", preset=6) if use_xz
                      else gzip.open(tmp, "wb", compresslevel=6))
            with opener as fo:
                while True:
                    buf = fi.read(8 << 20)
                    if not buf:
                        break
                    h_in.update(buf)
                    fo.write(buf)
        h_out = hashlib.sha1()
        creader = (lzma.open(tmp, "rb") if use_xz else gzip.open(tmp, "rb"))
        with creader as fc:
            while True:
                buf = fc.read(8 << 20)
                if not buf:
                    break
                h_out.update(buf)
        if h_in.digest() != h_out.digest():
            raise RuntimeError("往返 sha1 不一致")
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, out)
    cl.melt_memo_drop(p)   # the source is archived, so drop its stale memo entry
    return out


def _recompress_file(path, codec="xz"):
    """Archive a cold file or sidecar in the target format for the codec migration and delete the source
    on success: plaintext is compressed directly, a `.gz` file is decompressed to a temporary plaintext
    and compressed to `.xz`, and a file already in the target format comes back as is."""
    p = str(path)
    low = p.lower()
    want = ".xz" if str(codec).lower() == "xz" else ".gz"
    if low.endswith(want):
        return p
    if low.endswith(".xz") and want == ".gz":
        # Upgrading only: `compact --gz` touches plaintext and never inflates an existing .xz.
        return p
    if not low.endswith((".gz", ".xz")):
        out = _compress_file(p, codec)
        if out != p:
            try:
                os.remove(p)
            except OSError:
                pass
        return out
    out = cl.melt_stem(p) + want
    if os.path.isfile(out):
        return out
    tmp_plain = p + ".mig.tmp"
    reader = lzma.open(p, "rb") if low.endswith(".xz") else gzip.open(p, "rb")
    try:
        with reader as fi, open(tmp_plain, "wb") as fo:
            shutil.copyfileobj(fi, fo, 8 << 20)
        got = _compress_file(tmp_plain, codec, out_path=out)
    finally:
        try:
            os.remove(tmp_plain)
        except OSError:
            pass
    if got == out:
        try:
            os.remove(p)
        except OSError:
            pass
        cl.melt_memo_drop(p)   # drop the stale memo entry
    return got


def _compact_keep_paths(cfg):
    """Melt paths that stay plaintext: the newest melt of every campaign folder. Every merge and
    biography generation reads it, so plaintext saves a decompression, while older melts are read only
    by backfill, catch-up and verification."""
    keep = set()
    by_folder = {}
    for folder, path, date in _iter_melts(cfg):
        by_folder.setdefault(folder or "", []).append((cl.date_key(date), path))
    for _f, items in by_folder.items():
        keep.add(max(items)[1])
    return keep


def step_compact(cfg, codec=None, quiet_if_idle=True):
    """Archive cold melts and memory archive sidecars; safe to run repeatedly.

    quiet_if_idle keeps the console silent when there is nothing to do. The codec defaults to xz (lzma
    preset 6), overridable through config.compact_codec or `compact --gz`; existing `.gz` archives are
    recompressed to `.xz` and files already in the target format are skipped, while every reader accepts
    all three suffixes. Returns (files archived, bytes freed)."""
    codec = (codec or cfg.get("compact_codec") or "xz").lower()
    want = ".xz" if codec == "xz" else ".gz"
    melts = _iter_melts(cfg)
    if not melts:
        llm.log("未找到 melt 文件, 无需归档")
        return 0, 0
    keep = _compact_keep_paths(cfg)
    targets = []
    for _folder, path, _date in melts:
        if path not in keep:
            targets.append(path)
        idx = None
        for cand in cl._melt_index_variants(path):
            if os.path.isfile(cand):
                idx = cand
                break
        if idx:
            targets.append(idx)
    done = freed = 0
    # Only pending items are numbered, so the counter never exceeds the total; with nothing to do a
    # manual `compact` asks for one confirming line while the log file always gets a detail line.
    todo = [p for p in targets if not p.lower().endswith(want)]
    if not todo:
        llm.log(f"冷熔件归档 ({codec}): 无需归档 "
                f"(共 {len(targets)} 份已达标或为最新一份)", detail=quiet_if_idle)
        return 0, 0
    llm.log(f"冷熔件归档 ({codec}): 待处理 {len(todo)} 份 "
            f"(已 {want} 的跳过; 最新熔件保持明文)")
    for k, p in enumerate(todo, 1):
        try:
            before = os.path.getsize(p)
            out = _recompress_file(p, codec)
        except Exception as e:
            llm.log(f"  [归档失败] {os.path.basename(p)}: {e}")
            continue
        if out == p:
            continue
        after = os.path.getsize(out)
        done += 1
        freed += max(0, before - after)
        llm.log(f"  [{k}/{len(todo)}] {os.path.basename(out)} "
                f"{before / 1048576:.1f} → {after / 1048576:.1f} MiB "
                f"({after / before * 100:.0f}%)", detail=True)
    llm.log(f"冷熔件归档 ({codec}): {done} 份, 释放 {freed / (1 << 30):.2f} GB "
            f"(最新熔件保持明文, 读取口三种后缀皆认)")
    return done, freed


_COMPACT_THREAD = None


def _compact_loop(cfg):
    """Background archiving thread: one pass at startup, then one every 10 minutes, since the
    previous newest melt turns cold once a newer save is merged."""
    while True:
        try:
            step_compact(cfg)
        except Exception as e:
            llm.log(f"  [归档] 失败: {e}")
        time.sleep(600)


def _ensure_compact_worker(cfg):
    """Start the background archiving thread once, shared by watch/continue and never blocking
    the poll loop."""
    global _COMPACT_THREAD
    if _COMPACT_THREAD is not None:
        return
    _COMPACT_THREAD = threading.Thread(target=_compact_loop, args=(cfg,), daemon=True)
    _COMPACT_THREAD.start()


def _log_loc_source(cfg):
    """Read-only check reporting the localization source (game directory, enabled mods, fingerprint) and
    how the three derived tables (localization, trait display names, trait tracks) compare with it, so
    `status` shows the state at a glance. Nothing is rebuilt here."""
    try:
        import localization as loc
        rep = loc.inspect_source_tables(cfg)
        fp = (rep.get("fingerprints") or {}).get("loc") or {}
        llm.log(f"本地化来源: 游戏 {fp.get('game') or '(未找到)'}, "
                f"启用 Mod {len(fp.get('mods') or [])} 个, "
                f"来源指纹 {str(fp.get('hash'))[:12]}")
        llm.log("本地化自检 (只读): " + "、".join(
            f"{r['name']}{loc.state_text(r['state'])}"
            for r in rep.get("rows") or []) + "。")
    except Exception as e:
        llm.log(f"本地化来源检查失败: {e}")


def _ensure_source_tables(cfg):
    """Fingerprint self-check with rebuild-on-demand, no longer called from the startup path and kept for
    manual use; tables are built through `pipeline.py build-tables` instead."""
    try:
        import localization as loc
        return loc.ensure_source_tables(cfg)
    except Exception as e:
        llm.log(f"本地化自检失败 ({e}) —— 沿用现有表, 程序继续。")
        return None


# --- Manual table building (startup neither checks nor rebuilds any table) ------
# Derived tables (game/mod files -> data/*.json) are rebuilt in full with force here; manual tables
# (maintained by hand, no builder, gone once deleted) are only checked for existence.
# force always writes and only an empty result is refused, because a manual command means the rebuild
# is wanted: a smaller table from a disabled mod must still be written. Old row counts are printed for
# comparison only.
_MANUAL_TABLES = (
    ("宗族名(手工维护·无构建器)", "patronym_rules.json"),
)


def _table_builders():
    """Every game/mod derived table as (display name, current path, builder, writer)."""
    import localization as loc
    import flavorization as fl
    return [
        ("本地化总表", loc._localization_path, loc.build_localization_table,
         lambda cfg, d: loc.save_localization_table(
             cfg, d[0] if isinstance(d, tuple) else d,
             d[1] if isinstance(d, tuple) else None,
             fingerprint=loc.source_fingerprint(cfg))),
        ("特质显示名表", loc._trait_names_path, loc.build_trait_names, loc.save_trait_names),
        ("特质轨道表", loc._trait_tracks_path, loc.build_trait_tracks, loc.save_trait_tracks),
        ("宫廷职位变体", loc._court_positions_path, loc.build_court_positions,
         loc.save_court_positions),
        ("议会任务→席位", loc._council_tasks_path, loc.build_council_tasks,
         loc.save_council_tasks),
        ("议会席位名链", loc._council_names_path, loc.build_council_names,
         loc.save_council_names),
        ("主教称谓臂表", loc._bishop_titles_path, loc.build_bishop_titles,
         loc.save_bishop_titles),
        # theocracy title arms from custom localization (GetActualDuke/CountTheocracyTitle)
        ("神权官称臂表", loc._custom_loc_path, loc.build_theocracy_titles,
         loc.save_theocracy_titles),
        # spiritual fulfillment tiers (common/spiritual_fulfillment/*.txt)
        ("灵性满足分档", loc._spiritual_fulfillment_path,
         loc.build_spiritual_fulfillment, loc.save_spiritual_fulfillment),
        ("宗族与家族名", loc._dynasties_path, loc.build_dynasty_table,
         loc.save_dynasty_table),
        ("牵制类型", loc._hook_types_path, loc.build_hook_types, loc.save_hook_types),
        ("教义/信条参数", loc._doctrine_params_path, loc.build_doctrine_parameters,
         loc.save_doctrine_parameters),
        ("省份→伯爵领", loc._province_map_path, loc.build_province_map,
         loc.save_province_map),
        ("简称头衔", loc._short_titles_path, loc.build_short_titles, loc.save_short_titles),
        ("币种档位", loc._currency_levels_path, loc.build_currency_levels,
         loc.save_currency_levels),
        ("头衔风味规则", fl._path, fl.build_flavorization, fl.save_flavorization),
    ]


def _count_keys(obj):
    """Row count of a table object, read from its primary container; -1 when unavailable. Taking the
    largest container would be skewed by side containers such as `categories` or `fingerprint`, and a
    plain len() would count the province_map shape {province: {county, barony}} as its row count."""
    _PRIMARY = ("table", "entries", "traits", "tracks", "arms", "positions", "tasks",
                "hook_types", "doctrines", "by_parameter", "map", "titles",
                "dynasties", "houses", "rules", "positions")
    if isinstance(obj, tuple):
        obj = obj[0] if obj else {}
    if isinstance(obj, dict):
        for k in _PRIMARY:
            v = obj.get(k)
            if isinstance(v, int):
                return v
            if isinstance(v, (dict, list)):
                return len(v)
        if "schema" in obj:                      # wrapped, primary name absent -> take the largest
            best = -1
            for v in obj.values():
                if isinstance(v, (dict, list)) and len(v) > best:
                    best = len(v)
            return best if best >= 0 else len(obj)
        return len(obj)                          # a plain mapping, such as province_map's map
    if isinstance(obj, (list, set)):
        return len(obj)
    return -1


def step_build_tables(cfg, only=None):
    """Rebuild every game/mod derived table by hand, writing with force.

    python pipeline.py build-tables [--only=loc,traits]
    """
    import json as _json
    only = set(only or ())
    rows = []
    t_all = time.time()
    print("游戏目录:", cfg.get("ck3_game_dir") or "(自动发现)")
    print("建表中…… 每张表都会落盘 (手动命令一律 force)。\n")
    for name, path_fn, build, save in _table_builders():
        try:
            path = path_fn(cfg)
        except Exception:
            path = ""
        key = os.path.splitext(os.path.basename(path or ""))[0]
        if only and key not in only and name not in only:
            continue
        old_n = -1
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fp:
                    old_n = _count_keys(_json.load(fp))
            except Exception:
                old_n = -1
        t0 = time.time()
        try:
            data = build(cfg)
            if isinstance(data, tuple):
                new_n = _count_keys(data[0])
            else:
                new_n = _count_keys(data)
            if new_n == 0:
                rows.append((name, old_n, 0, time.time() - t0, "空结果, 未落盘"))
                print(f"  [跳过] {name}: 重建结果为空 (游戏目录不可用?), 保留旧表")
                continue
            save(cfg, data)
            note = ""
            if old_n >= 0 and new_n < old_n:
                note = f"  (少于旧表 {old_n - new_n} 条: 多为 Mod 停用, 已按手动口径落盘)"
            rows.append((name, old_n, new_n, time.time() - t0, note))
            print(f"  [完成] {name}: {old_n if old_n >= 0 else '—'} → {new_n} 条 "
                  f"({time.time() - t0:.1f} 秒){note}")
        except Exception as e:
            rows.append((name, old_n, -1, time.time() - t0, str(e)))
            print(f"  [失败] {name}: {type(e).__name__}: {e}")
    # manual tables: existence check only
    for name, fn in _MANUAL_TABLES:
        p = os.path.join(cfg.get("data_dir", ""), fn)
        if os.path.isfile(p):
            print(f"  [手工] {name}: 在 ({p})")
        else:
            print(f"  [手工] {name}: **缺失** —— 该表无构建器, 需从版本库取回"
                  f" (git checkout HEAD -- data/{fn})")
    secs = time.time() - t_all
    ok = sum(1 for r in rows if r[2] >= 0)
    print(f"\n建表完成: {ok}/{len(rows)} 张表落盘, 合计 {secs:.1f} 秒。")
    try:
        import localization as loc
        loc.inspect_source_tables(cfg)
    except Exception:
        pass
    return rows


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
        # startup performs no self-check: tables are always handled by hand
        step_scan(cfg)
    elif cmd == "build-tables":
        only = set()
        for a in sys.argv[2:]:
            if a.startswith("--only="):
                only = {x.strip() for x in a.split("=", 1)[1].split(",") if x.strip()}
        step_build_tables(cfg, only=only)
    elif cmd == "status":
        _log_loc_source(cfg)
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
    elif cmd == "compact":
        # default xz; `compact --gz` selects gzip, ~10x faster to compress but 63% larger
        codec = "gz" if "--gz" in sys.argv else None
        # a manual run confirms "nothing to do" with one line; the background thread stays silent
        step_compact(cfg, codec=codec, quiet_if_idle=False)
    elif cmd == "migrate":
        step_migrate(cfg)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
