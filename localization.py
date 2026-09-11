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
  - 省份→伯爵领/男爵领: game/common/landed_titles/*.txt 的 b_ 标题 province = N (Mod 覆盖)

产物 (静态参考表, 存 data/):
  - data/localization.json   : {key: 中文} 合并表
  - data/province_map.json   : {省份id: {"county": 伯爵领key, "barony": 男爵领key}}
    (v24: 值由单一伯爵领 key 升级为 county+barony 两键 — 受害者所在地标注用男爵领)
  - data/trait_names.json    : {traits: {trait_key: 显示名键}, categories: {trait_key: 类别}} (v31)
  - data/hook_types.json     : {hook_types: {类型键: {strong, perpetual, expiration_days}}} (v31)

用法:
  python localization.py build        # 重建本地化表
  python localization.py mods         # 列启用 Mod 的本地化覆盖与来源指纹 (v29)
  python localization.py province     # 重建省份映射
  python localization.py dynasties    # 重建宗族/家族定义表 (v14)
  python localization.py traits       # 重建特质显示名/类别表 (v29/v31)
  python localization.py hooks        # 重建牵制类型表 (v31)
  python localization.py check        # 抽查关键键 (Daria/岭西/层级词/桂州)
"""
import hashlib
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
_CLOSE_RE = re.compile(r"#!")                  # 关标签
_ICON_RE = re.compile(r"@[A-Za-z0-9_]+!")
_DYN_RE = re.compile(r"\[[^\]]*\]")            # [concept|E] / [GetX|V0]
_REF_RE = re.compile(r"\$([A-Za-z0-9_]+)\$")

# v16: 关系原因模板保留的角色名标签 (rival_murderer 等 reason 键) —
# 其余动态引用照旧剥除, 这 10 类标签供 facts.relation_reasons 替换名字。
_KEEP_DYN_RE = re.compile(
    r"\[(?:TARGET_CHARACTER_2|TARGET_CHARACTER|CHARACTER)\."
    r"(?:GetShortUIName(?:\|U)?|GetShortUINamePossessive(?:NoTooltip)?|"
    r"GetShortUINameNoTooltip|GetHerHisYour)\]")


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


def relation_template(raw):
    """关系原因原文 → 模板 (v16): 去格式码, 但**保留角色名标签**
    ([CHARACTER.GetShortUIName] / [TARGET_CHARACTER.GetShortUIName] /
    [TARGET_CHARACTER.GetShortUINamePossessive] / [X.GetHerHisYour] 等),
    供 facts.relation_reasons 按 owner/target 替换名字。"""
    if not isinstance(raw, str):
        return ""
    out = _TAG_RE.sub("", raw)
    out = _CLOSE_RE.sub("", out)
    out = _ICON_RE.sub("", out)
    kept = []

    def _keep(m):
        kept.append(m.group(0))
        return f"\x01{len(kept) - 1}\x02"

    out = _KEEP_DYN_RE.sub(_keep, out)
    out = _DYN_RE.sub("", out)
    for i, t in enumerate(kept):
        out = out.replace(f"\x01{i}\x02", t)
    out = out.replace("\\n", " ").replace('\\"', '"').strip()
    return out


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
# 源指纹 (v29): 启用 Mod / 游戏本地化一旦变化 → 本地化表自动重建
# ---------------------------------------------------------------------------
# 用户勾选新 Mod 后, 游戏内能看到 Mod 的中文文本, 程序侧也必须同样看到;
# 旧实现只在 data/localization.json 缺失时才重建 (实测该表停在 2026-08-30,
# 之后启用的 Mod 键一个都查不到 → 键值直落提示词)。

def _loc_lang_dirs(root, lang):
    """某根目录下的本地化语言目录 (含 Mod 常用的 localization/replace/<lang>),
    按加载序返回: 先 localization/<lang> (新增), 后 replace/<lang> (覆盖)。"""
    out = []
    for sub in ("", "replace"):
        d = os.path.join(root, "localization", sub, lang) if sub \
            else os.path.join(root, "localization", lang)
        if os.path.isdir(d):
            out.append(d)
    return out


def _loc_signature(root, lang):
    """某根目录某语言的本地化签名: {文件数, 字节数与最新 mtime 的摘要}。"""
    n = 0
    size = 0
    newest = 0.0
    for d in _loc_lang_dirs(root, lang):
        for dp, _dn, fns in os.walk(d):
            for fn in sorted(fns):
                if not fn.endswith(".yml"):
                    continue
                p = os.path.join(dp, fn)
                n += 1
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                size += int(st.st_size)
                newest = max(newest, float(st.st_mtime))
    return [n, size, int(newest)]


def source_fingerprint(cfg, lang="simp_chinese", fallback_lang="english"):
    """本地化来源指纹 (v29): 游戏目录 + 有序启用 Mod 目录 + 各自本地化签名。

    存进 data/localization.json; 与当前指纹不符即重建本地化表 —
    用户启用/停用 Mod、Mod 更新、游戏打补丁都会自动生效, 无需手工改项目。"""
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(("game", g))
    for i, m in enumerate(enabled_mod_dirs(cfg)):
        roots.append((f"mod{i}", m))
    detail = {
        "lang": lang,
        "fallback_lang": fallback_lang,
        "roots": [[name, path,
                   _loc_signature(path, lang), _loc_signature(path, fallback_lang)]
                  for name, path in roots],
    }
    blob = json.dumps(detail, ensure_ascii=False, sort_keys=True)
    return {
        "hash": hashlib.sha1(blob.encode("utf-8")).hexdigest(),
        # 便于人读: 哪些 Mod 参与了本次建表
        "mods": [path for name, path in roots if name != "game"],
        "game": g or "",
    }


# ---------------------------------------------------------------------------
# 本地化表构建
# ---------------------------------------------------------------------------

def _localization_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "localization.json")


def build_localization_table(cfg, lang="simp_chinese", fallback_lang="english"):
    """合并 游戏 + 启用 Mod 的本地化 → {key: 中文}。Mod 覆盖游戏, 后加载覆盖先加载。
    v16: 附带收集 关系原因模板 (含角色名标签的键) → relation_templates。
    v29: 每根目录遍历 localization/<lang> 与 localization/replace/<lang> 两处。"""
    table = {}
    raw_templates = {}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        if not os.path.isdir(os.path.join(root, "localization")):
            continue
        for langdir in (fallback_lang, lang):  # 英文先, 简体中文后 (中文优先)
            for d in _loc_lang_dirs(root, langdir):
                for dp, _dn, fns in os.walk(d):
                    for fn in sorted(fns):
                        if not fn.endswith(".yml"):
                            continue
                        for k, v in parse_yml(os.path.join(dp, fn)).items():
                            table[k] = v
                            if ("GetShortUIName" in v or "GetHerHisYour" in v) \
                                    and "[" in v:
                                tpl = relation_template(v)
                                if tpl:
                                    raw_templates[k] = tpl
    return table, raw_templates


def save_localization_table(cfg, table, raw_templates=None, path=None,
                            fingerprint=None):
    path = path or _localization_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"schema": 2, "lang": "simp_chinese", "keys": len(table),
                   "table": table,
                   "relation_templates": raw_templates or {},
                   # v29: 建表时的来源指纹 (启用 Mod 清单 + 本地化签名)
                   "fingerprint": fingerprint or {}},
                  fp, ensure_ascii=False)
    return path


def load_localization_table(cfg, force=False):
    """载入本地化表; 缺失、强制、或**来源指纹变化**时重建。返回 {key: 中文}。

    v29: 指纹 = 游戏目录 + 启用 Mod 清单 + 本地化文件数/字节数/mtime。用户启用
    新 Mod 或 Mod 更新后, 本函数自动重建并记日志; 新版表为空 (游戏目录不可用)
    时保留旧表, 不清空已有键。"""
    path = _localization_path(cfg)
    cached, old_fp = {}, None
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") in (1, 2):
                cached = data.get("table") or {}
                old_fp = data.get("fingerprint") or None
        except Exception:
            cached, old_fp = {}, None
    if not force and cached:
        try:
            fp = source_fingerprint(cfg)
        except Exception:
            fp = None
        if fp and old_fp and old_fp.get("hash") == fp.get("hash"):
            return cached
        why = "旧版表无来源指纹" if not old_fp else "启用 Mod / 游戏本地化已变化"
        llm.log(f"本地化表需重建 ({why})。")
    table, raw_templates = build_localization_table(cfg)
    if not table:
        # 游戏目录不可用 (换机 / 未配置): 保留旧表, 优于空表
        llm.log("本地化重建未取到任何键 (游戏目录不可用?), 沿用既有表。")
        return cached
    fp = None
    try:
        fp = source_fingerprint(cfg)
    except Exception:
        fp = None
    save_localization_table(cfg, table, raw_templates, path, fingerprint=fp)
    llm.log(f"本地化表已重建: {len(table)} 键"
            + (f", 启用 Mod {len((fp or {}).get('mods') or [])} 个。" if fp else "。"))
    return table


# ---------------------------------------------------------------------------
# 省份 → 伯爵领 映射
# ---------------------------------------------------------------------------

def _province_map_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "province_map.json")


def _parse_landed_titles(path, out):
    """解析一份 landed_titles.txt 的 b_ 标题 province = N → 伯爵领/男爵领 key。
    v24: 每省份同时记 b_ (男爵领/城堡级) 与最近 c_ (伯爵领) 两级 key。"""
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
                out[prov] = {"barony": bkey, "county": ckey}
        for ch in ln:
            if ch == "}":
                if stack:
                    stack.pop()


def build_province_map(cfg):
    """游戏 + Mod 的 landed_titles → {省份id: {"barony": b_ key, "county": c_ key}}。
    Mod 覆盖游戏; 旧版文件 (值=伯爵领 key 字符串) 由 load 层兼容。"""
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
        json.dump({"schema": 2, "entries": len(mapping), "map": mapping},
                  fp, ensure_ascii=False)
    return path


def load_province_map(cfg, force=False):
    path = _province_map_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") in (1, 2):
                m = {int(k): v for k, v in (data.get("map") or {}).items()}
                if data.get("schema") == 1:
                    # v24: 旧版 (值=伯爵领 key) → 兼容外壳, 男爵领暂缺 (待重建)
                    m = {k: {"county": v, "barony": ""} for k, v in m.items()}
                return m
        except Exception:
            pass
    mapping = build_province_map(cfg)
    save_province_map(cfg, mapping, path)
    return mapping


# ---------------------------------------------------------------------------
# 宗族/家族定义表 (v14: AUH 东亚人名 — 宗族名/家族名分层)
# ---------------------------------------------------------------------------
# 存档只存宗族/家族的 key (japanese_fujiwara / house_fujiwara_kajuji),
# 显示名 (藤原 / 勧修寺) 需回查游戏定义文件:
#   common/dynasties/*.txt       : key = { name = "dynn_X" }  (宗族)
#   common/dynasty_houses/*.txt  : key = { name = "dynn_Y" }  (家族/分家)

def _dynasties_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "dynasties.json")


def _parse_dynasty_defs(path, out):
    """解析一份 dynasties/dynasty_houses txt: key = { name = "dynn_X" } → out[key]。
    忽略嵌套花括号块 (脚本块不在这些文件里), 只取顶层 key。"""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fp:
            txt = fp.read()
    except Exception:
        return
    for m in re.finditer(r"^([A-Za-z][A-Za-z0-9_]*)\s*=\s*\{([^{}]*)\}", txt, re.M):
        key, body = m.group(1), m.group(2)
        nm = re.search(r'name\s*=\s*["\']?(dynn_[A-Za-z0-9_]+)', body)
        if nm:
            out[key] = nm.group(1)


def build_dynasty_table(cfg):
    """游戏 + Mod 的 common/dynasties 与 common/dynasty_houses →
    {"dynasties": {key: dynn名}, "houses": {house_key: dynn名}}。Mod 覆盖游戏。"""
    out = {"dynasties": {}, "houses": {}}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        for folder, bucket in (("dynasties", "dynasties"),
                               ("dynasty_houses", "houses")):
            d = os.path.join(root, "common", folder)
            if not os.path.isdir(d):
                continue
            for dp, _dn, fns in os.walk(d):
                for fn in sorted(fns):
                    if fn.endswith(".txt"):
                        _parse_dynasty_defs(os.path.join(dp, fn), out[bucket])
    return out


def save_dynasty_table(cfg, table, path=None):
    path = path or _dynasties_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"schema": 1, "dynasties": table.get("dynasties") or {},
                   "houses": table.get("houses") or {}}, fp, ensure_ascii=False)
    return path


def load_dynasty_table(cfg, force=False):
    """载入宗族/家族定义表; 缺失或强制时重建。
    返回 {"dynasties": {key: dynn名}, "houses": {house_key: dynn名}}。"""
    path = _dynasties_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1:
                return {"dynasties": data.get("dynasties") or {},
                        "houses": data.get("houses") or {}}
        except Exception:
            pass
    table = build_dynasty_table(cfg)
    save_dynasty_table(cfg, table, path)
    return table


# ---------------------------------------------------------------------------
# 数值档位 (v29): 游戏 defines 的 LEVELS_* + 本地化档位词
# ---------------------------------------------------------------------------
# 虔诚/威望/影响力/功勋在游戏里都有等级档位, 档位名就在本地化表
# (modifiers_l_simp_chinese.yml: piety_level_0=戴罪之人、merit_level_3=七品…)。
# 阈值取自 common/defines/00_defines.txt 的 LEVELS_*; 档 = 「≥阈值的个数」,
# 与阈值个数正好对应档位词下标 (piety 8 档、prestige 5 档、influence 5 档、merit 9 档)。

CURRENCY_KINDS = ("piety", "prestige", "influence", "merit")

_DEFAULT_LEVELS = {
    "piety": [1000, 1500, 2500, 4500, 8500, 13000, 17000, 22500],
    "prestige": [1000, 2000, 5000, 10000, 25000],
    "influence": [1000, 2000, 4000, 8000, 16000],
    "merit": [100, 1000, 2000, 3500, 5500, 8500, 12000, 17000, 23000],
}

_DEFINE_LEVEL_RE = re.compile(r"^\s*(LEVELS_(?:PIETY|PRESTIGE|INFLUENCE|MERIT))\s*=\s*\{([^}]*)\}",
                              re.M)
_DEFINE_NAME_OF = {"LEVELS_PIETY": "piety", "LEVELS_PRESTIGE": "prestige",
                   "LEVELS_INFLUENCE": "influence", "LEVELS_MERIT": "merit"}


def _currency_levels_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "currency_levels.json")


def build_currency_levels(cfg):
    """游戏 + 启用 Mod 的 common/defines → {"bands": {kind: [阈值…]}}。

    只取 **NCharacter 块**内的 LEVELS_* — 同名键在 NDynasty 块里另有定义
    (宗族威望档, 10 档), 混用会让角色威望映射到不存在的档位词。
    取不到 (文件缺失/被改写) 的币种回退内置默认值。"""
    bands = {k: list(v) for k, v in _DEFAULT_LEVELS.items()}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        d = os.path.join(root, "common", "defines")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    txt = fp.read()
            except OSError:
                continue
            for _key, body in _top_blocks(txt):
                if _key != "NCharacter":
                    continue
                for m in _DEFINE_LEVEL_RE.finditer(body):
                    kind = _DEFINE_NAME_OF.get(m.group(1))
                    vals = []
                    for tok in m.group(2).split():
                        try:
                            vals.append(float(tok))
                        except ValueError:
                            pass
                    if kind and vals:
                        bands[kind] = vals  # Mod 覆盖游戏 (后加载覆盖先加载)
    return {"schema": 1, "bands": bands}


def save_currency_levels(cfg, table):
    path = _currency_levels_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_currency_levels(cfg=None, force=False):
    """载入档位阈值表; 缺失或强制时重建。"""
    cfg = cfg or llm.load_config()
    path = _currency_levels_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1 and data.get("bands"):
                return data
        except Exception:
            pass
    data = build_currency_levels(cfg)
    save_currency_levels(cfg, data)
    return data


def level_index(value, thresholds):
    """数值 → 档位下标 (= 阈值中 ≤ value 的个数); 无法解析返回 None。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not thresholds:
        return None
    return sum(1 for t in thresholds if v >= t)


def level_word(table, bands, kind, value):
    """数值 → 游戏档位词 (如 虔诚 -865.8 → 「戴罪之人」); 查不到返回 ''。

    档位词缺失时向下回退到最近一个已有词的档 (防 Mod 改阈值后档位词不配套,
    宁可给略低的档位词, 也不整项不写)。"""
    th = (bands or {}).get(kind) or []
    n = level_index(value, th)
    if n is None:
        return ""
    for i in range(n, -1, -1):
        w = loc(table, f"{kind}_level_{i}")
        if w:
            return w
    return ""


# ---------------------------------------------------------------------------
# 职位显示名变体 (v29): court_position_asset.trigger → localization_key
# ---------------------------------------------------------------------------
# 存档只存职位**类型**键 (court_physician_court_position), 游戏按雇主政体/独立/
# 层级/文化传承在其 court_position_asset 变体里择一 localization_key
# (court_physician_celestial=医学博士 / _imperial=太医)。
# 触发词实测只有 6 类: government_has_flag / is_independent_ruler /
# highest_held_title_tier / has_cultural_pillar / culture_has_*_heritage_pillar_trigger
# / OR·AND·NOT·NOR 组合; 未知条件一律视为不命中 → 回退职位类型键的默认名。

_TIER_NUM = {"barony": 1, "county": 2, "duchy": 3, "kingdom": 4,
             "empire": 5, "hegemony": 6}


def _script_items(text):
    """CK3 脚本块内容 → [(key, op, value|body)] (保序, 去注释)。"""
    out = []
    i, n = 0, len(text or "")
    while i < n:
        ch = text[i]
        if ch in " \t\r\n,":
            i += 1
            continue
        if ch == "#":
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        m = re.match(r"[A-Za-z_][A-Za-z0-9_.]*", text[i:])
        if not m:
            i += 1
            continue
        key = m.group(0)
        i += len(key)
        m2 = re.match(r"\s*(>=|<=|!=|\?=|=|<|>)\s*", text[i:])
        if not m2:
            continue
        op = m2.group(1)
        i += m2.end()
        if i < n and text[i] == "{":
            depth, j = 0, i
            while j < n:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out.append((key, "block", text[i + 1:j]))
            i = j + 1
        else:
            j = text.find("\n", i)
            if j < 0:
                j = n
            out.append((key, op, text[i:j].split("#")[0].strip().strip('"')))
            i = j + 1
    return out


def _blocks_of(text, key):
    """取出所有 `<key> = { … }` 的块体 (保序)。"""
    out = []
    for m in re.finditer(r"(?<![A-Za-z0-9_])" + re.escape(key) + r"\s*=\s*\{", text or ""):
        i = m.end() - 1
        depth, j = 0, i
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(text[i + 1:j])
    return out


def _top_blocks(text):
    """顶层 `key = { … }` → [(key, body)] (保序)。"""
    out = []
    depth = 0
    for m in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{|\{|\}", text or ""):
        tok = m.group(0)
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth = max(0, depth - 1)
        elif depth == 0 and m.group(1):
            i = m.end() - 1
            d2, j = 0, i
            while j < len(text):
                if text[j] == "{":
                    d2 += 1
                elif text[j] == "}":
                    d2 -= 1
                    if d2 == 0:
                        break
                j += 1
            out.append((m.group(1), text[i + 1:j]))
    return out


def _heritage_groups(cfg):
    """scripted_triggers 里的 culture_has_*_heritage_pillar_trigger → {名: [heritage…]}。"""
    out = {}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        d = os.path.join(root, "common", "scripted_triggers")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    txt = fp.read()
            except OSError:
                continue
            for key, body in _top_blocks(txt):
                if "heritage_pillar_trigger" not in key:
                    continue
                hs = sorted(set(re.findall(r"has_cultural_pillar\s*=\s*(heritage_[A-Za-z0-9_]+)",
                                           body)))
                if hs:
                    out[key] = hs
    return out


def _cond_block(items, groups, op="all"):
    """触发项 → 条件树: {"op": all|any|none, "children": [叶子或子树]} (保序)。

    空块返回 {} (调用方按「无条件 = 恒真」处理); 无法识别的叶子记 {"unknown": key},
    求值恒不命中 → 该变体作废, 退化为职位类型键的默认名。"""
    children = []
    for key, kop, val in items:
        k = (key or "").lower()
        if kop == "block" and k in ("or", "any"):
            children.append(_cond_block(_script_items(val), groups, "any"))
        elif kop == "block" and k in ("and", "all", "culture", "root.culture"):
            children.append(_cond_block(_script_items(val), groups, "all"))
        elif kop == "block" and k in ("not", "nor", "none"):
            children.append(_cond_block(_script_items(val), groups, "none"))
        elif kop == "block":
            children.append(_cond_block(_script_items(val), groups, "all"))
        elif key == "exists" or kop == "?=":
            children.append({"exists": val})
        elif key.endswith("heritage_pillar_trigger"):
            hs = groups.get(key)
            children.append({"heritage_in": hs} if hs else {"unknown": key})
        elif key == "has_cultural_pillar":
            children.append({"heritage": val})
        elif key == "government_has_flag":
            children.append({"gov_flag": str(val).replace("government_is_", "")})
        elif key == "is_independent_ruler":
            children.append({"independent": str(val).lower() in ("yes", "true")})
        elif key == "highest_held_title_tier":
            t = _TIER_NUM.get(str(val).replace("tier_", "").lower())
            if t is None:
                children.append({"unknown": key})
            elif kop in (">=", ">"):
                children.append({"tier_min": t + (1 if kop == ">" else 0)})
            elif kop in ("<=", "<"):
                children.append({"tier_max": t - (1 if kop == "<" else 0)})
            else:
                children.append({"unknown": key})
        else:
            children.append({"unknown": key})
    return {"op": op, "children": children} if children else {}


def cond_match(cond, scope):
    """条件树在 scope 上求值。空条件 = 恒真 (游戏里无 trigger 的变体即默认名);
    未知条件恒不命中 (宁可用默认名, 不猜)。"""
    if not isinstance(cond, dict):
        return False
    if not cond:
        return True
    if "unknown" in cond:
        return False
    if "exists" in cond:
        return scope.get(str(cond["exists"])) not in (None, "")
    if "gov_flag" in cond:
        return scope.get("gov_flag") == cond["gov_flag"]
    if "independent" in cond:
        return bool(scope.get("independent")) == bool(cond["independent"])
    if "tier_min" in cond:
        return (scope.get("tier") or 0) >= cond["tier_min"]
    if "tier_max" in cond:
        return 0 < (scope.get("tier") or 0) <= cond["tier_max"]
    if "heritage" in cond:
        return scope.get("heritage") == cond["heritage"]
    if "heritage_in" in cond:
        return scope.get("heritage") in (cond["heritage_in"] or [])
    op = cond.get("op")
    ch = cond.get("children") or []
    if not ch:
        return True
    if op == "any":
        return any(cond_match(c, scope) for c in ch)
    if op == "none":
        return not any(cond_match(c, scope) for c in ch)
    return all(cond_match(c, scope) for c in ch)


def _court_positions_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "court_positions.json")


def build_court_positions(cfg):
    """游戏 + 启用 Mod 的 court_positions/types/*.txt → 职位显示名变体表:
    {"positions": {type_key: [{"loc_key": …, "when": 条件}, …]}} (保序, 含无 loc_key 的默认变体)。"""
    groups = _heritage_groups(cfg)
    positions = {}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        d = os.path.join(root, "common", "court_positions", "types")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    txt = fp.read()
            except OSError:
                continue
            for key, body in _top_blocks(txt):
                variants = []
                for blk in _blocks_of(body, "court_position_asset"):
                    lk = re.search(r"localization_key\s*=\s*([A-Za-z0-9_]+)", blk)
                    tr = _blocks_of(blk, "trigger")
                    cond = _cond_block(_script_items(tr[0]), groups) if tr else {}
                    variants.append({"loc_key": lk.group(1) if lk else "",
                                     "when": cond})
                if variants:
                    positions[key] = variants     # Mod 同名定义整体覆盖
    return {"schema": 1, "heritage_groups": groups, "positions": positions}


def save_court_positions(cfg, table):
    path = _court_positions_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_court_positions(cfg=None, force=False):
    """载入职位变体表; 缺失或强制时重建 (与本地化表同源的静态表)。"""
    cfg = cfg or llm.load_config()
    path = _court_positions_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1 and data.get("positions"):
                return data
        except Exception:
            pass
    data = build_court_positions(cfg)
    save_court_positions(cfg, data)
    return data


def pick_court_position(table, positions, type_key, scope):
    """按游戏 court_position_asset 顺序取首个命中变体的显示名。

    返回 '' 表示「该变体无 localization_key」或「全不命中」→ 调用方用职位类型键
    的默认名 (旧行为)。"""
    variants = ((positions or {}).get("positions") or {}).get(type_key) or []
    for v in variants:
        if cond_match(v.get("when") or {}, scope or {}):
            k = v.get("loc_key") or ""
            return (loc(table, k) or "") if k else ""
    return ""


# ---------------------------------------------------------------------------
# 御前会议席位 (v29): common/council_tasks/*.txt 的 position 字段
# ---------------------------------------------------------------------------
# 每个议会任务块写明 `position = councillor_steward` (或行政制 minister_personnel),
# 位置名再按政体取变体 (天朝制: councillor_steward_celestial_government_non_imperial
# = 司户 / _imperial = 户部尚书)。存档只存任务 id, 故须这张表才能写出席位官职名。

_COUNCIL_POSITION_FALLBACK = {
    "task_foreign_affairs": "councillor_chancellor",
    "task_fabricate_claim": "councillor_chancellor",
    "task_collect_taxes": "councillor_steward",
    "task_develop_county": "councillor_steward",
    "task_increase_control": "councillor_steward",
    "task_organize_levies": "councillor_marshal",
    "task_train_commanders": "councillor_marshal",
    "task_disrupt_schemes": "councillor_spymaster",
    "task_religious_relations": "councillor_court_chaplain",
    "task_conversion": "councillor_court_chaplain",
}


def _council_tasks_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "council_tasks.json")


def build_council_tasks(cfg):
    """游戏 + 启用 Mod 的 council_tasks → {"tasks": {任务键: 席位键}}。"""
    tasks = dict(_COUNCIL_POSITION_FALLBACK)
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        d = os.path.join(root, "common", "council_tasks")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    txt = fp.read()
            except OSError:
                continue
            for key, body in _top_blocks(txt):
                if not key.startswith("task_"):
                    continue
                m = re.search(r"(?<![A-Za-z_])position\s*=\s*([A-Za-z0-9_]+)", body)
                if m:
                    tasks[key] = m.group(1)
    return {"schema": 1, "tasks": tasks}


def save_council_tasks(cfg, table):
    path = _council_tasks_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_council_tasks(cfg=None, force=False):
    """载入议会任务→席位表; 缺失或强制时重建。"""
    cfg = cfg or llm.load_config()
    path = _council_tasks_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1 and data.get("tasks"):
                return data
        except Exception:
            pass
    data = build_council_tasks(cfg)
    save_council_tasks(cfg, data)
    return data


def council_seat_word(table, tasks, task_type, government="", imperial=False):
    """议会任务 → 席位官职词 (按政体取变体)。

    例: task_collect_taxes + celestial_government + 非帝国 → councillor_steward_
    celestial_government_non_imperial = 「司户」; 帝国 → 「户部尚书」;
    非天朝政体 → councillor_steward = 「财政总管」。查不到返回 ''。"""
    seat = ((tasks or {}).get("tasks") or {}).get(task_type) or ""
    if not seat:
        return ""
    cands = []
    pfx = government_prefix(government)
    if seat.startswith("councillor_") and pfx:
        suffix = "imperial" if imperial else "non_imperial"
        cands.append(f"{seat}_{pfx}_government_{suffix}")
        cands.append(f"{seat}_{pfx}_government")
        cands.append(f"{seat}_non_celestial_government_{suffix}")
    cands.append(seat)
    for c in cands:
        v = loc(table, c)
        # 拒收未解析引用 ($X$ / [X]) 与英文兜底 (纯 ASCII 词)
        if v and not v.startswith("$") and not v.startswith("[") \
                and not re.search(r"[A-Za-z]{2,}", v):
            return v
    return ""


# ---------------------------------------------------------------------------
# 特质显示名键表 (v29): common/traits/*.txt 的 name 块 → desc 键
# ---------------------------------------------------------------------------
# 部分特质 (如旅行者 lifestyle_traveler) 的显示名不走 trait_<key>, 而由特质定义里的
# name = { first_valid = { … desc = trait_traveler_1 } } 指定; Mod 特质更常见。
# 没有这张表时该特质整条被丢弃 (信息丢失, 虽不外泄键)。

def _trait_names_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "trait_names.json")


def build_trait_names(cfg):
    """游戏 + 启用 Mod 的 common/traits → 特质显示名键表 + 特质类别表。

    返回::

        {"schema": 2,
         "traits":     {trait_key: loc_key},       # 显示名 (v29)
         "categories": {trait_key: category}}      # 游戏 category (v31)

    v31: 同一次解析顺带取 `category = personality|education|lifestyle|fame|health|
    commander|childhood|court_type` —— 「为人」句按类分句、体况瞬时特质不进履历都靠它
    (先天特质 (beauty_*/intellect_*/physique_* 等) 游戏未给 category, 归空串)。"""
    out = {}
    cats = {}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        for sub in ("common/traits", "common/traits/tracks"):
            d = os.path.join(root, *sub.split("/"))
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".txt"):
                    continue
                try:
                    with open(os.path.join(d, fn), encoding="utf-8-sig",
                              errors="replace") as fp:
                        txt = fp.read()
                except OSError:
                    continue
                for key, body in _top_blocks(txt):
                    if key.startswith("@"):
                        continue
                    cb = re.search(r"(?<![A-Za-z_])category\s*=\s*([A-Za-z_]+)", body)
                    if cb:
                        cats[key] = cb.group(1)
                    nb = _blocks_of(body, "name")
                    if nb:
                        cands = re.findall(r"desc\s*=\s*([A-Za-z0-9_.]+)", nb[0])
                    else:
                        m = re.search(r"(?<![A-Za-z_])name\s*=\s*([A-Za-z0-9_.]+)",
                                      body)
                        cands = [m.group(1)] if m else []
                    for c in cands:
                        if c and not c.startswith(("$", "[")):
                            out[key] = c
                            break
    return {"schema": 2, "traits": out, "categories": cats}


def save_trait_names(cfg, table):
    path = _trait_names_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_trait_names(cfg=None, force=False):
    """载入特质显示名 + 类别表; 缺失、旧版 (无 categories) 或强制时重建。"""
    cfg = cfg or llm.load_config()
    path = _trait_names_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 2 and data.get("traits") \
                    and "categories" in data:
                return data
        except Exception:
            pass
    data = build_trait_names(cfg)
    save_trait_names(cfg, data)
    return data


# ---------------------------------------------------------------------------
# 牵制类型表 (v31): common/hook_types/*.txt → 强弱 + 永久标志
# ---------------------------------------------------------------------------
# 存档 hooks 只给类型键 (favor_hook/house_head_hook/ganlewodelaopo_hook…), 显示名走
# 本地化表同名键 (favor_hook=人情、house_head_hook=家主), 强弱须查类型定义:
# `strong = yes` 为强牵制, `perpetual = yes` / `expiration_days = -1` 为永久。
# Mod 定义 (longju_hook_types.txt 的 ganlewodelaopo_hook = {strong = yes}) 一并生效。

def _hook_types_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "hook_types.json")


def build_hook_types(cfg):
    """游戏 + 启用 Mod 的 common/hook_types → {"hook_types": {key: {...}}}。"""
    out = {}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        d = os.path.join(root, "common", "hook_types")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    txt = fp.read()
            except OSError:
                continue
            for key, body in _top_blocks(txt):
                if key.startswith("@"):
                    continue
                strong = bool(re.search(r"(?<![A-Za-z_])strong\s*=\s*yes", body))
                perpetual = bool(re.search(
                    r"(?<![A-Za-z_])perpetual\s*=\s*yes", body))
                m = re.search(r"(?<![A-Za-z_])expiration_days\s*=\s*(-?\d+)", body)
                days = int(m.group(1)) if m else None
                if days == -1:
                    perpetual = True
                out[key] = {"strong": strong, "perpetual": perpetual,
                            "expiration_days": None if perpetual else days}
    return {"schema": 1, "hook_types": out}


def save_hook_types(cfg, table):
    path = _hook_types_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_hook_types(cfg=None, force=False):
    """载入牵制类型表; 缺失或强制时重建 (与本地化表同源静态表)。"""
    cfg = cfg or llm.load_config()
    path = _hook_types_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1 and data.get("hook_types"):
                return data
        except Exception:
            pass
    data = build_hook_types(cfg)
    save_hook_types(cfg, data)
    return data


def hook_type(table, key):
    """牵制类型键 → 显示名 (本地化同名键; 查不到返回 '')。"""
    v = loc(table, key) or ""
    return "" if (not v or re.search(r"[A-Za-z_]", v)) else v


# ---------------------------------------------------------------------------
# 政体层级词 (动态)
# ---------------------------------------------------------------------------

TIER_KEY_OF_PREFIX = {"e_": "empire", "k_": "kingdom", "d_": "duchy",
                      "c_": "county", "b_": "barony", "h_": "hegemon"}

GENERIC_TIER_ZH = {"empire": "帝国", "kingdom": "王国", "duchy": "公国",
                   "county": "伯爵领", "barony": "堡", "hegemon": "皇朝"}

# v30: 通用**官职词**兜底表 (男, 女) — 与上面的头衔名后缀表分列, 二者语义不同:
# GENERIC_TIER_ZH 是「诺丁汉郡+伯爵领」这类头衔名后缀, GENERIC_OFFICE_ZH 是
# 「诺丁汉郡+女伯爵」这类统治者称呼 (修复方案_菲利普4.md 问题9: 女性词此前无处可取,
# 混用会让头衔名变成「诺丁汉郡女伯爵领」)。
GENERIC_OFFICE_ZH = {
    "hegemon": ("皇朝", "皇朝"),
    "empire":  ("皇帝", "女皇"),
    "kingdom": ("国王", "女王"),
    "duchy":   ("公爵", "女公爵"),
    "county":  ("伯爵", "女伯爵"),
    "barony":  ("男爵", "女男爵"),
}


def government_prefix(government):
    """'celestial_government' → 'celestial'; 其它原样去 _government 后缀。"""
    if not government:
        return ""
    return re.sub(r"_government$", "", government)


def tier_word(table, government, tier):
    """政体下的层级词: 优先 DLC 领地层级词 (culture_titles: 天朝制
    县/州府/镇/路/行台/皇朝), 再 <政体>_salary_rank_<层级>_short 俸禄词
    (celestial: 路/大路/镇/州府; administrative: 督军/大督军/军区),
    缺失回退通用表 (王国/帝国/公国/伯爵领/堡/皇朝)。"""
    prefix = government_prefix(government)
    # v8.3: DLC「All Under Heaven」领地层级词 (culture_titles):
    #   barony_celestial_chinese_vassal=县, county=州府, duchy=镇,
    #   kingdom=路, empire=行台, hegemony_celestial_chinese=皇朝。
    if prefix == "celestial":
        key = ("hegemony_celestial_chinese" if tier == "hegemon"
               else f"{tier}_celestial_chinese_vassal")
        v = table.get(key)
        if v:
            c = clean_loc_value(v, table)
            if c and not c.startswith("$") and not c.startswith("["):
                return c
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
_DYN_TABLE = None
_REL_TPL = None
_LEVELS = None
_COURT_POSITIONS = None
_COUNCIL_TASKS = None
_TRAIT_NAMES = None
_HOOK_TYPES = None


def currency_levels(cfg=None):
    """虔诚/威望/影响力/功勋档位阈值表单例 (v29)。"""
    global _LEVELS
    if _LEVELS is None:
        _LEVELS = load_currency_levels(cfg or llm.load_config())
    return _LEVELS


def court_positions(cfg=None):
    """职位显示名变体表单例 (v29): {"heritage_groups": …, "positions": {type: [变体…]}}。"""
    global _COURT_POSITIONS
    if _COURT_POSITIONS is None:
        _COURT_POSITIONS = load_court_positions(cfg or llm.load_config())
    return _COURT_POSITIONS


def council_tasks(cfg=None):
    """议会任务→席位表单例 (v29): {"tasks": {task_type: councillor_seat}}。"""
    global _COUNCIL_TASKS
    if _COUNCIL_TASKS is None:
        _COUNCIL_TASKS = load_council_tasks(cfg or llm.load_config())
    return _COUNCIL_TASKS


def trait_names(cfg=None):
    """特质显示名 + 类别表单例 (v29/v31):
    {"traits": {trait_key: loc_key}, "categories": {trait_key: category}}。"""
    global _TRAIT_NAMES
    if _TRAIT_NAMES is None:
        _TRAIT_NAMES = load_trait_names(cfg or llm.load_config())
    return _TRAIT_NAMES


def hook_type_table(cfg=None):
    """牵制类型表单例 (v31): {"hook_types": {type: {strong, perpetual, …}}}。"""
    global _HOOK_TYPES
    if _HOOK_TYPES is None:
        _HOOK_TYPES = load_hook_types(cfg or llm.load_config())
    return _HOOK_TYPES


def table(cfg=None):
    """本地化表单例 {key: 中文}; 首次调用时载入/重建。"""
    global _TABLE
    if _TABLE is None:
        _TABLE = load_localization_table(cfg or llm.load_config())
    return _TABLE


def relation_templates(cfg=None):
    """关系原因模板单例 (v16): {reason键: 含角色名标签的原始模板}。
    缺失 (旧版 localization.json) 时返回 {} — 游戏原因功能自动降级。"""
    global _REL_TPL
    if _REL_TPL is None:
        _REL_TPL = {}
        try:
            path = _localization_path(cfg or llm.load_config())
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            _REL_TPL = data.get("relation_templates") or {}
        except Exception:
            pass
    return _REL_TPL


def province_map(cfg=None):
    """省份→伯爵领 映射单例 {int省份: 伯爵领key}; 首次调用时载入/重建。"""
    global _PROVINCE_MAP
    if _PROVINCE_MAP is None:
        _PROVINCE_MAP = load_province_map(cfg or llm.load_config())
    return _PROVINCE_MAP


def dynasty_table(cfg=None):
    """宗族/家族定义表单例 (v14): {"dynasties": {key: dynn名},
    "houses": {house_key: dynn名}}; 首次调用时载入/重建。"""
    global _DYN_TABLE
    if _DYN_TABLE is None:
        _DYN_TABLE = load_dynasty_table(cfg or llm.load_config())
    return _DYN_TABLE


# ---------------------------------------------------------------------------
# 教义参数 (v30): common/religion/doctrine_types/*.txt 的 parameters 块
# ---------------------------------------------------------------------------
# 存档 religion.faiths[fid].doctrine 只给**教义键列表**, 不给教义的功能参数;
# 处决方式里的「献祭」需要 human_sacrifice_active — 该参数写在 doctrine_types 的
# parameters 块里 (实测: tenet_human_sacrifice / tenet_gruesome_festivals /
# tenet_sacrificial_ceremonies 三处), 故此处落成 doctrine → 参数名 的静态表,
# Mod 新增/改写教义时随指纹重建 (修复方案_菲利普4.md 问题12)。

def _doctrine_params_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "doctrine_parameters.json")


def build_doctrine_parameters(cfg):
    """游戏 + 启用 Mod 的 doctrine_types/*.txt → {"doctrines": {教义: [参数…]},
    "by_parameter": {参数: [教义…]}} (Mod 同名教义整体覆盖)。"""
    by_doctrine = {}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        d = os.path.join(root, "common", "religion", "doctrine_types")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    txt = fp.read()
            except OSError:
                continue
            for key, body in _top_blocks(txt):
                params = set()
                for pblk in _blocks_of(body, "parameters"):
                    for pk, op, val in _script_items(pblk):
                        if op == "block":
                            continue
                        if str(val).lower() in ("yes", "true") or \
                                str(val).isdigit():
                            params.add(pk)
                if params:
                    by_doctrine[key] = sorted(params)
    by_param = {}
    for doc, params in by_doctrine.items():
        for p in params:
            by_param.setdefault(p, []).append(doc)
    for p in by_param:
        by_param[p] = sorted(by_param[p])
    return {"schema": 1, "doctrines": by_doctrine, "by_parameter": by_param}


def save_doctrine_parameters(cfg, data):
    path = _doctrine_params_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)
    return path


def load_doctrine_parameters(cfg=None, force=False):
    """载入教义参数字典; 缺失或强制时由游戏/Mod 文件重建。"""
    cfg = cfg or llm.load_config()
    path = _doctrine_params_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1 and data.get("by_parameter"):
                return data
        except Exception:
            pass
    data = build_doctrine_parameters(cfg)
    if data.get("by_parameter"):
        save_doctrine_parameters(cfg, data)
    return data


# 内置兜底: 游戏文件不可读时仍能判定人祭 (三处 parameters = { human_sacrifice_active = yes })
_DOCTRINE_PARAM_FALLBACK = {
    "human_sacrifice_active": ("tenet_human_sacrifice", "tenet_gruesome_festivals",
                               "tenet_sacrificial_ceremonies"),
}


def doctrines_granting(param, cfg=None):
    """授予某教义参数的教义键集合 (表缺失/为空时回退内置表)。"""
    try:
        table = load_doctrine_parameters(cfg)
        keys = (table.get("by_parameter") or {}).get(param) or []
    except Exception:
        keys = []
    return set(keys) or set(_DOCTRINE_PARAM_FALLBACK.get(param, ()))


# ---------------------------------------------------------------------------
# 查询助手
# ---------------------------------------------------------------------------

_MISS = {}


def loc(table, key, default=""):
    """按 key 查中文 (去格式码 + 解 $ref$); 缺失返回 default。

    v29: 未命中的键计入进程内统计 (含逐级回退的中间候选), 由 miss_report /
    write_miss_report 导出——启用 Mod 后哪个键没读进来, 一眼可查。"""
    if not key:
        return default
    v = table.get(str(key))
    if v is None:
        _MISS[str(key)] = _MISS.get(str(key), 0) + 1
        return default
    return clean_loc_value(v, table)


def miss_report(top=40):
    """未命中键统计 (次数降序, 只给前 top 条), 供本地化覆盖审计。"""
    items = sorted(_MISS.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[:top]


def write_miss_report(cfg=None, path=None, top=200):
    """把未命中键统计写到 logs/loc_miss.log (有内容才写)。返回写入条数。"""
    if not _MISS:
        return 0
    cfg = cfg or llm.load_config()
    path = path or os.path.join(cfg.get("log_dir") or "logs", "loc_miss.log")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(f"# 未命中本地化键 {len(_MISS)} 个 "
                     f"(候选键含逐级回退), 计 {sum(_MISS.values())} 次\n")
            for k, n in sorted(_MISS.items(), key=lambda kv: (-kv[1], kv[0]))[:top]:
                fp.write(f"{n}\t{k}\n")
    except Exception:
        return 0
    return min(len(_MISS), top)


# ---------------------------------------------------------------------------
# 命令行
# ---------------------------------------------------------------------------

def _mod_key_counts(root, lang="simp_chinese", fallback_lang="english"):
    """某 Mod 根目录在本地化表里贡献的键数 (逐语言目录统计)。"""
    n = 0
    langs = []
    for langdir in (fallback_lang, lang):
        for d in _loc_lang_dirs(root, langdir):
            for dp, _dn, fns in os.walk(d):
                for fn in fns:
                    if fn.endswith(".yml"):
                        n += len(parse_yml(os.path.join(dp, fn)))
            langs.append(d)
    return n, langs


def main():
    cfg = llm.load_config()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "build":
        table, raw_templates = build_localization_table(cfg)
        if not table:
            print("未取到任何键: 请检查 config.json 的 ck3_game_dir / Mod 目录。")
            return 1
        fp = source_fingerprint(cfg)
        p = save_localization_table(cfg, table, raw_templates, fingerprint=fp)
        print(f"本地化表已重建: {p} ({len(table)} 键, "
              f"关系原因模板 {len(raw_templates)} 条, "
              f"启用 Mod {len(fp.get('mods') or [])} 个)")
    elif cmd == "mods":
        # v29: 启用 Mod 的本地化覆盖审计 (用户勾选 Mod 后先跑这条)
        g = game_dir(cfg)
        mods = enabled_mod_dirs(cfg)
        print(f"游戏目录: {g or '(未找到)'}")
        print(f"活动 playset 启用 Mod: {len(mods)} 个")
        total = 0
        for i, m in enumerate(mods):
            n, dirs = _mod_key_counts(m)
            total += n
            print(f"  [{i}] {m}\n      本地化键 {n} 条; 目录 {dirs or '（无 localization）'}")
        print(f"Mod 路由键合计 (含互相覆盖): {total}")
        fp = source_fingerprint(cfg)
        print(f"来源指纹: {fp.get('hash', '')[:12]}… (mods={len(fp.get('mods') or [])})")
        path = _localization_path(cfg)
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fp_:
                    old = (json.load(fp_).get("fingerprint") or {})
                same = old.get("hash") == fp.get("hash")
                print(f"现有 data/localization.json 指纹: {str(old.get('hash'))[:12]}… "
                      f"{'一致' if same else '不一致 → 下次载入会自动重建'}")
            except Exception as e:
                print(f"读取现有表失败: {e}")
    elif cmd == "levels":
        data = build_currency_levels(cfg)
        p = save_currency_levels(cfg, data)
        print(f"档位阈值表已重建: {p}")
        for k in CURRENCY_KINDS:
            print(f"  {k}: {data['bands'].get(k)}")
    elif cmd == "positions":
        data = build_court_positions(cfg)
        p = save_court_positions(cfg, data)
        pos = data.get("positions") or {}
        print(f"职位变体表已重建: {p} ({len(pos)} 个职位, "
              f"族属分组 {len(data.get('heritage_groups') or {})} 条)")
        table = load_localization_table(cfg)
        for key in ("court_physician_court_position",
                    "travel_leader_court_position",
                    "chronicler_court_position"):
            for v in pos.get(key) or []:
                print(f"  {key} → {v.get('loc_key') or '(默认名)'} "
                      f"[{loc(table, v['loc_key']) if v.get('loc_key') else loc(table, key)}]"
                      f" when={v.get('when')}")
    elif cmd == "council":
        data = build_council_tasks(cfg)
        p = save_council_tasks(cfg, data)
        print(f"议会席位表已重建: {p} ({len(data.get('tasks') or {})} 个任务)")
        table = load_localization_table(cfg)
        for t in ("task_collect_taxes", "task_organize_levies", "task_disrupt_schemes",
                  "task_religious_relations", "task_foreign_affairs", "task_conversion",
                  "task_manage_talent"):
            row = [t, data["tasks"].get(t, "")]
            for gov, imp in (("celestial_government", False),
                             ("celestial_government", True),
                             ("feudal_government", False)):
                row.append(council_seat_word(table, data, t, gov, imp) or "—")
            print("  " + " | ".join(str(x) for x in row))
    elif cmd == "traits":
        data = build_trait_names(cfg)
        p = save_trait_names(cfg, data)
        t = data.get("traits") or {}
        cats = data.get("categories") or {}
        print(f"特质显示名表已重建: {p} ({len(t)} 条, 类别 {len(cats)} 条)")
        table = load_localization_table(cfg)
        for k in ("lifestyle_traveler", "lifestyle_physician", "hunchback", "dwarf",
                  "pregnant", "lustful"):
            lk = t.get(k, "")
            print(f"  {k} [{cats.get(k) or '无类别'}] → "
                  f"{lk or '(trait_<key>)'} = {loc(table, lk or f'trait_{k}')!r}")
    elif cmd == "hooks":
        data = build_hook_types(cfg)
        p = save_hook_types(cfg, data)
        ht = data.get("hook_types") or {}
        table = load_localization_table(cfg)
        strong = sum(1 for v in ht.values() if v.get("strong"))
        print(f"牵制类型表已重建: {p} ({len(ht)} 条, 其中强牵制 {strong} 条)")
        for k in ("favor_hook", "house_head_hook", "indebted_hook",
                  "weak_blackmail_hook", "strong_blackmail_hook",
                  "ganlewodelaopo_hook", "ritual_best_friend_hook"):
            v = ht.get(k)
            if v is None:
                print(f"  {k} → (本档未定义)")
                continue
            print(f"  {k} → {hook_type(table, k) or '(无名)'}"
                  f" [{'强' if v.get('strong') else '弱'}"
                  f"{'/永久' if v.get('perpetual') else ''}]")
    elif cmd == "province":
        m = build_province_map(cfg)
        p = save_province_map(cfg, m)
        print(f"省份映射已重建: {p} ({len(m)} 条)")
    elif cmd == "dynasties":
        t = build_dynasty_table(cfg)
        p = save_dynasty_table(cfg, t)
        print(f"宗族/家族定义表已重建: {p} "
              f"(宗族 {len(t['dynasties'])} 条, 家族 {len(t['houses'])} 条)")
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
        if miss_report(1):
            print(f"本次未命中本地化键: {len(miss_report(10 ** 9))} 个 → TOP:")
            for k, n in miss_report(20):
                print(f"  {n:>5}  {k}")
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
