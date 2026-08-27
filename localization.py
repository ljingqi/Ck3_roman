# -*- coding: utf-8 -*-
"""本地化与地图数据解析层 (localization.py)
==========================================
把 CK3 游戏本体 + 启用 Mod 的 Paradox YML 本地化解析成 {key: 中文} 表,
供 cache_lib / facts / build_names 统一查名; 另构建 省份→伯爵领 映射。

数据来源 (实测):
  - 名字: game/localization/simp_chinese/names/character_names_l_simp_chinese.yml
    (如 Daria:"达丽娅", Yehoshua:"约书亚", A_brahA_m:"亚伯拉罕")
  - 头衔: titles_l_simp_chinese.yml (k_lingxi:"岭西", c_fuzhou_5:"鄜州")
  - 政体层级词: government_l_simp_chinese.yml 的 <政体>_salary_rank_<层级>_short
    (celestial: 路/大路/镇/州府; administrative: 督军/大督军/军区; 无则回退通用表)
  - 省份→伯爵领: game/common/landed_titles/*.txt 的 b_ 标题 province = N (Mod 覆盖)

产物 (静态参考表, 存 data/):
  - data/localization.json   : {key: 中文} 合并表
  - data/province_map.json   : {省份id: 伯爵领key}

用法:
  python localization.py build        # 重建本地化表
  python localization.py province     # 重建省份映射
  python localization.py check        # 抽查关键键 (Daria/岭西/层级词/桂州)
"""
import json
import os
import re
import sqlite3
import sys

import llm

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# CK3 本地化文本清理
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"#[A-Za-z0-9_\-+]+")     # #V / #bold / #low ... 开标签
_CLOSE_RE = re.compile(r"#!")
_ICON_RE = re.compile(r"@[A-Za-z0-9_]+!")
_DYN_RE = re.compile(r"\[[^\]]*\]")            # [concept|E] / [GetX|V0]
_REF_RE = re.compile(r"\$([A-Za-z0-9_]+)\$")


def strip_ck3_format(text):
    """去掉 Paradox 本地化格式码: 颜色/样式标签、图标、动态引用; 保留正文。
    '#V +10#!' → '+10'; '#bold 天朝#!' → '天朝'。"""
    if not isinstance(text, str):
        return ""
    out = _TAG_RE.sub("", text)
    out = _CLOSE_RE.sub("", out)
    out = _ICON_RE.sub("", out)
    out = _DYN_RE.sub("", out)
    out = out.replace("\\n", " ").replace('\\"', '"').strip()
    return out


def resolve_refs(text, table, depth=4):
    """解析 $key$ 引用 (最多 depth 层); 引用缺失时保留原样。"""
    if depth <= 0 or not text or "$" not in text:
        return text
    def repl(m):
        key = m.group(1)
        v = table.get(key)
        if v is None:
            return m.group(0)
        return resolve_refs(v, table, depth - 1)
    return _REF_RE.sub(repl, text)


def clean_loc_value(raw, table):
    """YML 值 → 干净中文 (去格式码 + 解 $ref$ + 去空白)。"""
    v = strip_ck3_format(raw or "")
    if "$" in v:
        v = resolve_refs(v, table)
    return v.strip()


# ---------------------------------------------------------------------------
# YML 解析
# ---------------------------------------------------------------------------

_YML_RE = re.compile(r'^([^:#\s][^:]*?):(?:\d+)?\s*"(.*)"\s*(?:#.*)?$')


def parse_yml(path):
    """一份 Paradox YML → {key: 原始值}。"""
    out = {}
    try:
        with open(path, encoding="utf-8-sig") as fp:
            for ln in fp:
                s = ln.strip()
                if not s or s.startswith("#") or s.startswith("l_"):
                    continue
                m = _YML_RE.match(s)
                if m:
                    key = m.group(1).strip()
                    out[key] = m.group(2).replace(r"\\", "\\").replace(r"\"", '"')
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# 目录发现: 游戏本体 + 启用 Mod
# ---------------------------------------------------------------------------

def _ck3_from_steam_root(steam_root):
    """steamapps/common/Crusader Kings III → game 目录 (含 localization/)。"""
    cand = os.path.join(steam_root, "steamapps", "common", "Crusader Kings III")
    for sub in ("game", ""):
        p = os.path.join(cand, sub)
        if os.path.isdir(os.path.join(p, "localization")):
            return p
    return None


def _steam_library_roots():
    """Steam 注册表路径 + libraryfolders.vdf 里所有库路径。"""
    roots = []
    steam = None
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            with winreg.OpenKey(hive, key) as k:
                steam = winreg.QueryValueEx(k, "SteamPath")[0]
                if steam:
                    break
    except Exception:
        pass
    if steam:
        roots.append(steam)
        vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as fp:
                for m in re.finditer(r'"path"\s*"([^"]+)"', fp.read()):
                    roots.append(m.group(1).replace("\\\\", "\\"))
        except Exception:
            pass
    return roots


def game_dir(cfg):
    """返回游戏根目录 (含 localization/ 与 common/)。"""
    d = (cfg.get("ck3_game_dir") or "").strip()
    if d:
        for cand in (os.path.join(d, "game"), d):
            if os.path.isdir(os.path.join(cand, "localization")):
                return cand
    for root in _steam_library_roots():
        p = _ck3_from_steam_root(root)
        if p:
            return p
    return ""


def _read_mod_paths(cfg):
    """从 mod 目录 *.mod 文件读所有 Mod 根目录 (路径字段)。"""
    mod_dir = os.path.join(cfg.get("ck3_user_dir", ""), "mod")
    out = []
    if os.path.isdir(mod_dir):
        for fn in sorted(os.listdir(mod_dir)):
            if not fn.endswith(".mod"):
                continue
            try:
                with open(os.path.join(mod_dir, fn), encoding="utf-8-sig") as fp:
                    txt = fp.read()
                m = re.search(r'path\s*=\s*"([^"]+)"', txt)
                if m and os.path.isdir(m.group(1)):
                    out.append(m.group(1))
            except Exception:
                continue
    return out


def enabled_mod_dirs(cfg):
    """启用 Mod 根目录 (按 playset 加载顺序)。读取失败时退回全部 *.mod。"""
    db_path = os.path.join(cfg.get("ck3_user_dir", ""), "launcher-v2.sqlite")
    dirs = []
    try:
        db = sqlite3.connect(db_path)
        cur = db.cursor()
        cur.execute("SELECT id FROM playsets WHERE isActive=1 LIMIT 1")
        row = cur.fetchone()
        if row:
            pid = row[0]
            cur.execute(
                "SELECT pm.position, m.repositoryPath, m.dirPath FROM playsets_mods pm "
                "JOIN mods m ON m.id = pm.modId "
                "WHERE pm.playsetId=? AND pm.enabled=1 ORDER BY pm.position", (pid,))
            for _pos, repo, dpath in cur.fetchall():
                for p in (repo, dpath):
                    if p and os.path.isdir(p):
                        dirs.append(p)
                        break
        db.close()
    except Exception:
        dirs = []
    if dirs:
        return dirs
    return _read_mod_paths(cfg)


# ---------------------------------------------------------------------------
# 本地化表构建
# ---------------------------------------------------------------------------

def _localization_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "localization.json")


def build_localization_table(cfg, lang="simp_chinese", fallback_lang="english"):
    """合并 游戏 + 启用 Mod 的本地化 → {key: 中文}。Mod 覆盖游戏, 后加载覆盖先加载。"""
    table = {}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        loc_root = os.path.join(root, "localization")
        if not os.path.isdir(loc_root):
            continue
        for langdir in (fallback_lang, lang):  # 英文先, 简体中文后 (中文优先)
            d = os.path.join(loc_root, langdir)
            if not os.path.isdir(d):
                continue
            for dp, _dn, fns in os.walk(d):
                for fn in sorted(fns):
                    if not fn.endswith(".yml"):
                        continue
                    for k, v in parse_yml(os.path.join(dp, fn)).items():
                        table[k] = v
    return table


def save_localization_table(cfg, table, path=None):
    path = path or _localization_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"schema": 1, "lang": "simp_chinese", "keys": len(table),
                   "table": table}, fp, ensure_ascii=False)
    return path


def load_localization_table(cfg, force=False):
    """载入本地化表; 缺失或强制时重建。返回 {key: 中文}。"""
    path = _localization_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1:
                return data.get("table") or {}
        except Exception:
            pass
    table = build_localization_table(cfg)
    save_localization_table(cfg, table, path)
    return table


# ---------------------------------------------------------------------------
# 省份 → 伯爵领 映射
# ---------------------------------------------------------------------------

def _province_map_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "province_map.json")


def _parse_landed_titles(path, out):
    """解析一份 landed_titles.txt 的 b_ 标题 province = N → 伯爵领 key。"""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fp:
            txt = fp.read()
    except Exception:
        return
    stack = []
    for ln in txt.splitlines():
        m = re.match(r"^\s*([a-z0-9_]+)\s*=\s*\{", ln)
        if m:
            key = m.group(1)
            lvl = 0
            if key.startswith("e_"):
                lvl = 5
            elif key.startswith(("k_", "h_")):
                lvl = 4
            elif key.startswith("d_"):
                lvl = 3
            elif key.startswith("c_"):
                lvl = 2
            elif key.startswith("b_"):
                lvl = 1
            stack.append((key, lvl))
            continue
        m = re.match(r"^\s*province\s*=\s*(\d+)", ln)
        if m and stack:
            prov = int(m.group(1))
            bkey = ckey = None
            for k, lv in reversed(stack):
                if k.startswith("b_") and bkey is None:
                    bkey = k
                elif k.startswith("c_"):
                    ckey = k
                    break
            if bkey:
                out[prov] = ckey or bkey
        for ch in ln:
            if ch == "}":
                if stack:
                    stack.pop()


def build_province_map(cfg):
    """游戏 + Mod 的 landed_titles → {省份id: 伯爵领key}。Mod 覆盖游戏。"""
    out = {}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        for dp, _dn, fns in os.walk(root):
            if "landed_titles" not in dp or "localization" in dp:
                continue
            for fn in sorted(fns):
                if fn.endswith(".txt"):
                    _parse_landed_titles(os.path.join(dp, fn), out)
    return out


def save_province_map(cfg, mapping, path=None):
    path = path or _province_map_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"schema": 1, "entries": len(mapping), "map": mapping},
                  fp, ensure_ascii=False)
    return path


def load_province_map(cfg, force=False):
    path = _province_map_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1:
                return {int(k): v for k, v in (data.get("map") or {}).items()}
        except Exception:
            pass
    mapping = build_province_map(cfg)
    save_province_map(cfg, mapping, path)
    return mapping


# ---------------------------------------------------------------------------
# 政体层级词 (动态)
# ---------------------------------------------------------------------------

TIER_KEY_OF_PREFIX = {"e_": "empire", "k_": "kingdom", "d_": "duchy",
                      "c_": "county", "b_": "barony"}

GENERIC_TIER_ZH = {"empire": "帝国", "kingdom": "王国", "duchy": "公国",
                   "county": "县", "barony": "堡"}


def government_prefix(government):
    """'celestial_government' → 'celestial'; 其它原样去 _government 后缀。"""
    if not government:
        return ""
    return re.sub(r"_government$", "", government)


def tier_word(table, government, tier):
    """政体下的层级词: 优先 <政体>_salary_rank_<层级>_short 本地化键
    (celestial: 路/大路/镇/州府; administrative: 督军/大督军/军区),
    缺失回退通用表 (王国/帝国/公国/县/堡)。"""
    prefix = government_prefix(government)
    if prefix:
        for key in (f"{prefix}_salary_rank_{tier}_short",
                    f"{prefix}_salary_rank_{tier}"):
            v = table.get(key)
            if v:
                c = clean_loc_value(v, table)
                if c and not c.startswith("$") and not c.startswith("["):
                    return c
    return GENERIC_TIER_ZH.get(tier, "")


# ---------------------------------------------------------------------------
# 模块级单例 (cache_lib / facts 直接查表)
# ---------------------------------------------------------------------------

_TABLE = None
_PROVINCE_MAP = None


def table(cfg=None):
    """本地化表单例 {key: 中文}; 首次调用时载入/重建。"""
    global _TABLE
    if _TABLE is None:
        _TABLE = load_localization_table(cfg or llm.load_config())
    return _TABLE


def province_map(cfg=None):
    """省份→伯爵领 映射单例 {int省份: 伯爵领key}; 首次调用时载入/重建。"""
    global _PROVINCE_MAP
    if _PROVINCE_MAP is None:
        _PROVINCE_MAP = load_province_map(cfg or llm.load_config())
    return _PROVINCE_MAP


# ---------------------------------------------------------------------------
# 查询助手
# ---------------------------------------------------------------------------

def loc(table, key, default=""):
    """按 key 查中文 (去格式码 + 解 $ref$); 缺失返回 default。"""
    if not key:
        return default
    v = table.get(str(key))
    if v is None:
        return default
    return clean_loc_value(v, table)


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def main():
    cfg = llm.load_config()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "build":
        table = build_localization_table(cfg)
        p = save_localization_table(cfg, table)
        print(f"本地化表已重建: {p} ({len(table)} 键)")
    elif cmd == "province":
        m = build_province_map(cfg)
        p = save_province_map(cfg, m)
        print(f"省份映射已重建: {p} ({len(m)} 条)")
    elif cmd == "check":
        g = game_dir(cfg)
        mods = enabled_mod_dirs(cfg)
        print(f"游戏目录: {g or '(未找到, 请在 config.json 配置 ck3_game_dir)'}")
        print(f"启用 Mod: {len(mods)} 个")
        table = load_localization_table(cfg, force=True)
        print(f"本地化键: {len(table)}")
        for k in ("Daria", "Yehoshua", "k_lingxi", "c_fuzhou_5",
                  "landless_adventurer_government", "celestial_government"):
            print(f"  {k} → {loc(table, k)!r}")
        print("层级词 celestial:", {t: tier_word(table, "celestial_government", t)
                                    for t in ("empire", "kingdom", "duchy", "county", "barony")})
        print("层级词 administrative:", {t: tier_word(table, "administrative_government", t)
                                          for t in ("empire", "kingdom", "duchy", "county")})
        pm = load_province_map(cfg, force=True)
        print(f"省份映射: {len(pm)} 条, 10135 → {pm.get(10135)}, 9814 → {pm.get(9814)}")
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
