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

用法:
  python localization.py build        # 重建本地化表
  python localization.py mods         # 列启用 Mod 的本地化覆盖与来源指纹 (v29)
  python localization.py province     # 重建省份映射
  python localization.py dynasties    # 重建宗族/家族定义表 (v14)
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
# 政体层级词 (动态)
# ---------------------------------------------------------------------------

TIER_KEY_OF_PREFIX = {"e_": "empire", "k_": "kingdom", "d_": "duchy",
                      "c_": "county", "b_": "barony", "h_": "hegemon"}

GENERIC_TIER_ZH = {"empire": "帝国", "kingdom": "王国", "duchy": "公国",
                   "county": "伯爵领", "barony": "堡", "hegemon": "皇朝"}


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
