# -*- coding: utf-8 -*-
"""Localization and map data parsing layer (localization.py)
==========================================================
Parses Paradox YML localization from the CK3 base game plus enabled mods into a {key: Chinese}
table that cache_lib / facts / build_names share for name lookups, and builds the province map.

Data sources:
  - Names: game/localization/simp_chinese/names/character_names_l_simp_chinese.yml (Chinese given
    names, keyed by names such as Daria and A_brahA_m)
  - Titles: titles_l_simp_chinese.yml (keys such as k_lingxi and c_fuzhou_5)
  - Government rank words: government_l_simp_chinese.yml keys named
    <government>_salary_rank_<level>_short
  - Province -> county/barony: the b_ titles' `province = N` field in
    game/common/landed_titles/*.txt (mods may override)

Artifacts (static reference tables under data/):
  - data/localization.json : merged {key: Chinese} table
  - data/province_map.json : {province_id: {"county": county_key, "barony": barony_key}}
  - data/trait_names.json  : {traits: {trait_key: base name key}, categories: {trait_key: category},
                              level_names: {trait_key: [XP conditions + rename keys]}}
  - data/trait_tracks.json : {tracks: {trait_key: [{track, levels}, ...]}}
  - data/hook_types.json   : {hook_types: {type_key: {strong, perpetual, expiration_days}}}

Usage: python localization.py  build | mods | province | dynasties | shorts | traits | tracks |
                               hooks | check
"""
import hashlib
import json
import os
import re
import sqlite3
import sys
import time

import llm

HERE = os.path.dirname(os.path.abspath(__file__))

# CK3 localization text cleaning

_TAG_RE = re.compile(r"#[A-Za-z0-9_\-+]+")     # opening tags: #V / #bold / #low ...
_CLOSE_RE = re.compile(r"#!")                  # closing tag
_ICON_RE = re.compile(r"@[A-Za-z0-9_]+!")
_DYN_RE = re.compile(r"\[[^\]]*\]")            # dynamic refs: [concept|E] / [GetX|V0]
_REF_RE = re.compile(r"\$([A-Za-z0-9_]+)\$")

# Dynamic tags kept inside relationship-reason templates (the `reason` keys such as rival_murderer)
# so facts._sub_relation_loc can substitute real values; every other dynamic reference is stripped.
# A tag is `[<role>.<accessor>]`, role optionally with a `|U`-style variant suffix. Roles are the
# three character slots plus PROVINCE, and the game's own misspellings TARGT_CHARACTER /
# TCHARACTER are accepted as the counterpart slot.
#
# Kept accessors (each resolvable from the save or from a table this project already holds):
#   · names        GetShortUIName(Possessive)(NoTooltip), GetUIName, GetName, GetPossessive,
#                  GetFirstName(Possessive), GetTitledFirstName, GetDynastyHouseName(NoTooltip),
#                  GetHouse.GetName, plus the game's misspelled GetShortUI_Name / GetShortUINAME
#                  (best_friend_childhood_ritual, rival_regent_denied_access_to_family)
#   · gender/kin   GetHerHis(Your), GetHerHim, GetSheHe, GetHerselfHimself, GetWomanMan,
#                  GetMotherFather, GetWifeHusband, Custom('GetDaughterSon'),
#                  Custom('child_favorite_toy') (rendered as the generic 「玩具」, as before)
#   · faith/文化    GetFaith.GetName, GetDeathReason, GetCulture.GetLanguage.GetName,
#                  GetCulture.GetCollectiveNoun
#   · province     GetName
#   · activity/trait/title  GetActivityType('X').GetName, GetTrait('X').GetName(scope),
#                  GetTitleByKey('X').GetName (no role prefix — the game calls them on the default
#                  scope)
#   · concepts     [house|E] / [rivalry|E] / [strong_hook|E] … (lowercase refs, resolved through
#                  game_concept_<key>)
#
# Deliberately NOT kept (their values need tables this project does not hold, so they stay stripped
# rather than risk a raw tag reaching a prompt): GetFaith.ReligiousText / HighGodName /
# random_HighGodName / HouseOfWorship, GetLiege.*, GetPrimaryTitle.GetAdjective,
# PROVINCE.Custom('TerrainTypeProvince'), Select_CString(...) and the script custom locs other than
# the two kept above.
_ROLE_RE = (r"(?:TARGET_CHARACTER_2|TARGET_CHARACTER|TARGT_CHARACTER|TCHARACTER"
            r"|CHARACTER|PROVINCE)")
_ACC_RE = (r"(?:"
           r"GetShortUI_?[Nn][Aa][Mm][Ee](?:Possessive)?(?:NoTooltip)?"
           r"|GetUIName|GetName|GetPossessive"
           r"|GetFirstName(?:Possessive)?|GetTitledFirstName"
           r"|GetDynastyHouseName(?:NoTooltip)?"
           r"|GetHouse\.GetName"
           r"|GetHerHis(?:Your)?|GetHerHim|GetSheHe|GetHerselfHimself"
           r"|GetWomanMan|GetMotherFather|GetWifeHusband"
           r"|GetFaith\.GetName|GetDeathReason"
           r"|GetCulture\.GetLanguage\.GetName|GetCulture\.GetCollectiveNoun"
           r"|Custom\('GetDaughterSon'\)"
           r"|Custom\('child_favorite_toy'\)"
           r")")
# Tags that carry no role prefix (the game calls a function on the default scope): an activity
# type's name, a trait's name, and a title looked up by key.
_STANDALONE_RE = (r"(?:"
                  r"GetActivityType\('[A-Za-z0-9_]+'\)\.GetName"
                  r"|GetTrait\('[A-Za-z0-9_]+'\)\.GetName\([^)]*\)"
                  r"|GetTitleByKey\('[A-Za-z0-9_]+'\)\.GetName"
                  r")")
_KEEP_DYN_RE = re.compile(
    r"\[(?:" + _ROLE_RE + r"\." + _ACC_RE + r"(?:\|[A-Za-z0-9_]+)?"
    r"|" + _STANDALONE_RE + r"(?:\|[A-Za-z0-9_]+)?"
    r"|[a-z][a-z0-9_]*(?:\|[A-Za-z0-9_]+)?)\]")


def strip_ck3_format(text):
    """Strip Paradox localization format codes (colour/style tags, icons, dynamic
    references) while keeping the text: '#V +10#!' -> '+10'."""
    if not isinstance(text, str):
        return ""
    out = _TAG_RE.sub("", text)
    out = _CLOSE_RE.sub("", out)
    out = _ICON_RE.sub("", out)
    out = _DYN_RE.sub("", out)
    out = out.replace("\\n", " ").replace('\\"', '"').strip()
    return out


def resolve_refs(text, table, depth=4):
    """Resolve $key$ references up to `depth` levels; unresolved refs stay as-is."""
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
    """YML raw value -> clean Chinese (concept refs expanded, format codes stripped,
    $ref$ resolved, whitespace trimmed)."""
    v = strip_ck3_format(_sub_concepts(raw or "", table))
    if "$" in v:
        v = resolve_refs(v, table)
    return v.strip()


#: Concept ref `[concept|E]` — the key starts lowercase, so character/place
#: accessors (uppercase) are unaffected.
_CONCEPT_REF_RE = re.compile(r"\[([a-z][a-z0-9_]*)(?:\|[A-Za-z0-9_]*)?\]")
#: Concept ref carrying an inline display name, `[Concept('key','name')|E]`: that
#: inline name is used directly instead of the table lookup.
_CONCEPT_INLINE_RE = re.compile(
    r"\[Concept\('([A-Za-z0-9_]+)','([^']*)'\)(?:\|[A-Za-z0-9_]*)?\]")


def _sub_concepts(text, table):
    """`[concept|E]` -> that concept's Chinese name (localization key `game_concept_<key>`).
    When no name is found the ref stays unchanged so strip_ck3_format can still remove it."""
    if not text or "[" not in text:
        return text
    if "Concept(" in text:
        text = _CONCEPT_INLINE_RE.sub(lambda m: m.group(2) or m.group(1), text)
    if not table:
        return text

    def repl(m):
        v = table.get("game_concept_" + m.group(1))
        if isinstance(v, str) and v and not v.startswith(("$", "[")):
            return v
        return m.group(0)

    return _CONCEPT_REF_RE.sub(repl, text)


def relation_template(raw):
    """Relationship-reason raw text -> template: format codes stripped but character-name tags kept
    ([CHARACTER.GetShortUIName], [X.GetHerHisYour], ...) for facts.relation_reasons to substitute."""
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


# YML parsing

_YML_RE = re.compile(r'^([^:#\s][^:]*?):(?:\d+)?\s*"(.*)"\s*(?:#.*)?$')


def parse_yml(path):
    """One Paradox YML file -> {key: raw value}."""
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


# Directory discovery: game install + enabled mods

def _ck3_from_steam_root(steam_root):
    """steamapps/common/Crusader Kings III -> game dir (the one holding localization/)."""
    cand = os.path.join(steam_root, "steamapps", "common", "Crusader Kings III")
    for sub in ("game", ""):
        p = os.path.join(cand, sub)
        if os.path.isdir(os.path.join(p, "localization")):
            return p
    return None


def _steam_library_roots():
    """Steam path from the registry plus every library path listed in libraryfolders.vdf."""
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
    # Fallback for when the registry cannot be read (winreg.OpenKey raises FileNotFoundError in
    # restricted or subprocess environments). Without it game_dir() comes back empty and the table
    # holds only mod localization (~94k keys instead of ~382k), degrading Chinese names and titles to
    # English text or bare keys. Other Steam libraries in libraryfolders.vdf are scanned the same way.
    cands = [steam] if steam else []
    cands += [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    for c in cands:
        if not c:
            continue
        vdf = os.path.join(c, "steamapps", "libraryfolders.vdf")
        if not os.path.isfile(vdf):
            continue
        if c not in roots:
            roots.append(c)
        try:
            with open(vdf, encoding="utf-8", errors="replace") as fp:
                for m in re.finditer(r'"path"\s*"([^"]+)"', fp.read()):
                    p = m.group(1).replace("\\\\", "\\")
                    if p not in roots:
                        roots.append(p)
        except Exception:
            pass
    return roots


def game_dir(cfg):
    """Game root directory (holds localization/ and common/), or "" when not found."""
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
    """Every mod root directory named by the path field of the *.mod files under
    <ck3_user_dir>/mod."""
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
    """Mod root directories enabled in the active playset, in playset load order.
    Falls back to every *.mod when the launcher database cannot be read."""
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


# Source fingerprint
# Any change to the enabled mods or to the game's localization makes the table stale. Staleness comes
# from the fingerprint rather than from the file merely existing: a mod the user enables in game shows
# up in game text, so it must show up here, and a table built before that change would never pick up
# the mod's keys (they would reach the prompt as bare keys).

def _loc_lang_dirs(root, lang):
    """Localization language dirs under one root, in load order: localization/<lang> first
    (additions), then localization/replace/<lang> (overrides), where mods usually put files."""
    out = []
    for sub in ("", "replace"):
        d = os.path.join(root, "localization", sub, lang) if sub \
            else os.path.join(root, "localization", lang)
        if os.path.isdir(d):
            out.append(d)
    return out


def _loc_signature(root, lang):
    """Localization signature of one root in one language: [file count, total bytes,
    newest mtime]."""
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
    """Localization source fingerprint: the game dir plus the ordered enabled mod dirs, each with its
    localization signature for both languages. Stored in data/localization.json; a mismatch rebuilds
    the table, so mod changes and game patches take effect without hand-editing the project."""
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
        # human-readable: which mods took part in this build
        "mods": [path for name, path in roots if name != "game"],
        "game": g or "",
    }


# Localization table build

def _localization_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "localization.json")


def build_localization_table(cfg, lang="simp_chinese", fallback_lang="english"):
    """Merge the game's and the enabled mods' localization -> {key: Chinese}; mods override the game
    and later roots override earlier ones, scanning localization/<lang> and replace/<lang> in each.
    Returns (table, relation-reason templates), the latter keyed by localization key."""
    table = {}
    raw_templates = {}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    # Language is the outer loop and root the inner one, so Chinese from any root
    # beats English from any root; within one language the root order still holds
    # (mods override the base game). Looping per root instead lets a mod's English
    # value overwrite the base game's Chinese name.
    for langdir in (fallback_lang, lang):
        for root in roots:
            if not os.path.isdir(os.path.join(root, "localization")):
                continue
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
        # schema 3 = the language-outer / root-inner merge order. Earlier schemas
        # (<=2) may hold mod-English values that shadowed base-game Chinese, so they
        # are treated as stale and rebuilt once.
        json.dump({"schema": 3, "lang": "simp_chinese", "keys": len(table),
                   "table": table,
                   "relation_templates": raw_templates or {},
                   # source fingerprint at build time (enabled mod list + localization signatures)
                   "fingerprint": fingerprint or {}},
                  fp, ensure_ascii=False)
    return path


# Localization override table: female rank words
# The game writes the female title of a rank as a reference to the male key:
# culture_titles_l_simp_chinese.yml points every female hegemon/emperor key at
# hegemon_celestial_male_chinese, so after parsing the female key equals the male one and its value
# still starts with "$", which L.loc treats as unresolved. This table overrides those keys after
# loading, using the game's own wording, so a female ruler gets her own rank word.
LOC_OVERRIDES = {
    "hegemon_celestial_female_chinese": "女皇",
    "hegemon_female_chinese": "女皇",
    "emperor_female_chinese_independent": "女皇",
    "emperor_celestial_female_chinese_independent": "女皇",
}


def _fill_report(report, state, keys, why=""):
    """Write one load's conclusion into the caller-supplied report (startup self-check). A None
    report stays silent, because lazy loads need no reporting."""
    if report is None:
        return
    report.clear()
    report.update({"state": state, "keys": int(keys), "why": why})


def load_localization_table(cfg, force=False, report=None):
    """Load the localization table -> {key: Chinese}, rebuilding when the file is missing, `force` is
    set, or the fingerprint changed; an empty rebuild keeps the old table. `report`, when not None,
    receives {"state": ok|outdated|rebuilt|kept-old|no-source, "keys": n, "why": text}."""
    path = _localization_path(cfg)
    cached, old_fp, schema_ok = {}, None, False
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 3:
                cached = data.get("table") or {}
                old_fp = data.get("fingerprint") or None
                schema_ok = True
            # schema<=2 tables were merged English-first and Chinese-second, so a
            # mod's English value could shadow the base game's Chinese one; never
            # reuse them, rebuild instead.
        except Exception:
            cached, old_fp, schema_ok = {}, None, False
    why = "表缺失" if not os.path.isfile(path) else (
        "旧版表或文件不可解析" if not schema_ok else "表内容为空")
    if not force and cached:
        try:
            fp = source_fingerprint(cfg)
        except Exception:
            fp = None
        if fp and old_fp and old_fp.get("hash") == fp.get("hash"):
            cached.update(LOC_OVERRIDES)     # overrides apply to a reused table too
            _fill_report(report, "ok", len(cached), "来源指纹一致")
            return cached
        why = "旧版表无来源指纹" if not old_fp else "启用 Mod / 游戏本地化已变化"
        # A fingerprint mismatch does not rebuild automatically: the existing table is
        # used and the user is asked to rebuild by hand. Rebuilding on every startup
        # after a game upgrade or mod change would redo the whole build each time, only
        # for the shrink guard below to possibly refuse to write the result.
        if schema_ok:
            llm.log(f"本地化表已过期 ({why}) —— 本轮沿用现有表; "
                    f"要更新请运行 重建对照表.bat (或 python pipeline.py build-tables)。")
            cached.update(LOC_OVERRIDES)
            _fill_report(report, "outdated", len(cached), why)
            return cached
    table, raw_templates = build_localization_table(cfg)
    if not table:
        # game dir unavailable (different machine / not configured): keep the old table
        llm.log("本地化重建未取到任何键 (游戏目录不可用?), 沿用既有表。")
        cached.update(LOC_OVERRIDES)         # overrides apply to a reused table too
        _fill_report(report, "no-source", len(cached), "游戏目录不可用, 沿用既有表")
        return cached
    # Shrink guard: with the game dir unavailable a rebuild yields a small
    # "mod-keys-only" table (~94k keys vs ~382k), which would overwrite a good table
    # and break Chinese person names, titles and house prefixes wholesale. Refuse to
    # write a new table holding less than 60% of the old table's key count.
    if cached and len(table) < len(cached) * 0.6:
        llm.log(f"本地化重建结果偏小 ({len(table)} 键 < 旧表 {len(cached)} 键的六成) —— "
                f"疑游戏目录不可用, 保留旧表不落盘。若确为游戏更新, 请删 "
                f"{path} 后重建。")
        _fill_report(report, "kept-old", len(cached),
                     f"重建结果偏小 ({len(table)} 键), 保留旧表")
        return cached
    fp = None
    try:
        fp = source_fingerprint(cfg)
    except Exception:
        fp = None
    save_localization_table(cfg, table, raw_templates, path, fingerprint=fp)
    llm.log(f"本地化表已重建: {len(table)} 键"
            + (f", 启用 Mod {len((fp or {}).get('mods') or [])} 个。" if fp else "。"))
    table.update(LOC_OVERRIDES)              # female rank-word overrides (see LOC_OVERRIDES)
    _fill_report(report, "rebuilt", len(table), why)
    return table


# Province -> county/barony map

def _province_map_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "province_map.json")


def _parse_landed_titles(path, out):
    """Parse the `province = N` fields of one landed_titles.txt into
    {province_id: {"barony": b_ key, "county": c_ key}} (the enclosing barony and nearest county)."""
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
    """Game + mod landed_titles -> {province_id: {"barony": b_ key, "county": c_ key}}; mods override
    the game. Old value-only files (a bare county key string) are handled by the load layer."""
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


# "Short name" title table: definite_form = yes in landed_titles
# The in-game "short name" toggle (localization key TITLE_CUSTOMIZATION_DEFINITE_FORM) corresponds
# to `definite_form = yes` in common/landed_titles/*.txt. Such a title's positional name already
# carries the realm/tier word (e_hre, e_byzantium, k_papal_state, h_dar_al_islam), so the game does
# not append `$TIER$`; an unmarked title holds only the place name (k_aquitaine, k_france) and takes
# its tier word from TITLE_TIERED_NAME. The table drives the prince/princess prefix word choice.

def _short_titles_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "short_titles.json")


_TITLE_KEY_PREFIXES = ("h_", "e_", "k_", "d_", "c_", "b_")


def _parse_landed_titles_short(path, out):
    """Collect the `definite_form = yes` title keys from one landed_titles.txt
    (game + mods)."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fp:
            txt = fp.read()
    except Exception:
        return
    stack = []
    for ln in txt.splitlines():
        m = re.match(r"^\s*([a-z0-9_]+)\s*=\s*\{", ln)
        if m:
            stack.append(m.group(1))
            continue
        if "definite_form" in ln and "yes" in ln:
            for k in reversed(stack):
                if k.startswith(_TITLE_KEY_PREFIXES):
                    out.add(k)
                    break
        for ch in ln:
            if ch == "}" and stack:
                stack.pop()


def build_short_titles(cfg):
    """Game + mod landed_titles -> the set of definite_form title keys."""
    out = set()
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
                    _parse_landed_titles_short(os.path.join(dp, fn), out)
    return out


def save_short_titles(cfg, titles, path=None):
    path = path or _short_titles_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"schema": 1, "entries": len(titles),
                   "titles": sorted(titles)}, fp, ensure_ascii=False)
    return path


def load_short_titles(cfg, force=False):
    path = _short_titles_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1:
                return set(data.get("titles") or [])
        except Exception:
            pass
    titles = build_short_titles(cfg)
    save_short_titles(cfg, titles, path)
    return titles


_SHORT_TITLES = None


def short_titles(cfg=None):
    """Set of short-name title keys (module-level singleton; the first call builds the
    table and writes data/short_titles.json)."""
    global _SHORT_TITLES
    if _SHORT_TITLES is None:
        _SHORT_TITLES = load_short_titles(cfg or llm.load_config())
    return _SHORT_TITLES


# Government and title naming rules
# `facts.realm_name` reproduces the engine's house-named realms, which needs two static facts from
# the game files:
#   · common/governments/*.txt : `dynasty_named_realms = yes` marks the governments whose realms
#     are named after the holder's house (clan_government, feudal_government, mandala_government).
#     administrative_government, nomad_government, celestial_government, steppe_admin_government,
#     meritocratic_government and the Japanese administrative governments carry no such key.
#   · common/landed_titles/*.txt : `can_be_named_after_dynasty = no` exempts one title key from
#     the rule (h_dar_al_islam, d_sunni); the default is yes (_landed_titles.info:117-122).

def _governments_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "governments.json")


_TOP_BLOCK_OPEN_RE = re.compile(r"([A-Za-z0-9_]+)\s*=\s*\{")


def _iter_top_block_flags(txt, flag_re):
    """Yield (top-level block key, flag value) for every line matching `flag_re` inside a block,
    comments removed. The flag may sit several levels deep, as `dynasty_named_realms` does inside a
    government's `government_rules` block, and still belongs to the outermost key.

    The depth is counted from the braces of each line, so one line holding several `{` / `}` (or a
    whole block on one line) leaves the next line's depth right; a stack popped once per `}` would
    desync there and later attribute a flag to whichever older key was still on it."""
    depth, cur = 0, ""
    for ln in txt.splitlines():
        code = ln.split("#", 1)[0]
        if depth >= 1:
            m = flag_re.match(code.strip())
            if m:
                yield cur, m.group(1)
        opens, closes = code.count("{"), code.count("}")
        if depth == 0 and opens:
            m = _TOP_BLOCK_OPEN_RE.match(code.strip())
            if m:
                cur = m.group(1)
        depth = max(0, depth + opens - closes)


def _parse_governments(path, out):
    """Collect the government keys carrying `dynasty_named_realms = yes` from one governments file."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fp:
            txt = fp.read()
    except Exception:
        return
    flag_re = re.compile(r"dynasty_named_realms\s*=\s*(\w+)")
    for key, val in _iter_top_block_flags(txt, flag_re):
        if val.lower() in ("yes", "true"):
            out.add(key)


def build_governments(cfg):
    """Game + enabled mods' common/governments/*.txt -> the set of dynasty-named governments."""
    out = set()
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        for dp, _dn, fns in os.walk(root):
            if "governments" not in dp or "localization" in dp:
                continue
            for fn in sorted(fns):
                if fn.endswith(".txt"):
                    _parse_governments(os.path.join(dp, fn), out)
    return out


def save_governments(cfg, keys, path=None):
    path = path or _governments_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"schema": 1, "entries": len(keys),
                   "dynasty_named": sorted(keys)}, fp, ensure_ascii=False)
    return path


def load_governments(cfg=None, force=False):
    cfg = cfg or llm.load_config()
    path = _governments_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1:
                return set(data.get("dynasty_named") or [])
        except Exception:
            pass
    keys = build_governments(cfg)
    save_governments(cfg, keys, path)
    return keys


_GOVERNMENTS = None


def governments(cfg=None):
    """Set of government keys whose realms the engine names after the holder's house
    (module-level singleton; the first call builds and writes data/governments.json)."""
    global _GOVERNMENTS
    if _GOVERNMENTS is None:
        _GOVERNMENTS = load_governments(cfg or llm.load_config())
    return _GOVERNMENTS


def dynasty_named_government(gov, cfg=None):
    """Whether this government key follows the dynasty-named-realms rule."""
    return bool(gov) and str(gov) in governments(cfg)


def _title_name_flags_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "landed_title_flags.json")


def _parse_landed_titles_name_locked(path, out):
    """Collect the `can_be_named_after_dynasty = no` title keys from one landed_titles.txt."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fp:
            txt = fp.read()
    except Exception:
        return
    flag_re = re.compile(r"can_be_named_after_dynasty\s*=\s*(\w+)")
    for key, val in _iter_top_block_flags(txt, flag_re):
        if val.lower() in ("no", "false") and key.startswith(_TITLE_KEY_PREFIXES):
            out.add(key)


def build_title_name_flags(cfg):
    """Game + enabled mods' common/landed_titles/*.txt -> the set of title keys that keep their own
    name (`can_be_named_after_dynasty = no`)."""
    out = set()
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
                    _parse_landed_titles_name_locked(os.path.join(dp, fn), out)
    return out


def save_title_name_flags(cfg, keys, path=None):
    path = path or _title_name_flags_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"schema": 1, "entries": len(keys),
                   "name_locked": sorted(keys)}, fp, ensure_ascii=False)
    return path


def load_title_name_flags(cfg=None, force=False):
    cfg = cfg or llm.load_config()
    path = _title_name_flags_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1:
                return set(data.get("name_locked") or [])
        except Exception:
            pass
    keys = build_title_name_flags(cfg)
    save_title_name_flags(cfg, keys, path)
    return keys


_TITLE_NAME_FLAGS = None


def title_name_flags(cfg=None):
    """Set of title keys that keep their own name (module-level singleton; the first call builds and
    writes data/landed_title_flags.json)."""
    global _TITLE_NAME_FLAGS
    if _TITLE_NAME_FLAGS is None:
        _TITLE_NAME_FLAGS = load_title_name_flags(cfg or llm.load_config())
    return _TITLE_NAME_FLAGS


def title_name_locked(key, cfg=None):
    """Whether this title key is exempt from being named after the holder's house."""
    return bool(key) and str(key) in title_name_flags(cfg)


def load_province_map(cfg, force=False):
    path = _province_map_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") in (1, 2):
                m = {int(k): v for k, v in (data.get("map") or {}).items()}
                if data.get("schema") == 1:
                    # legacy value (bare county key) -> compatibility wrapper; the
                    # barony key stays empty until the map is rebuilt
                    m = {k: {"county": v, "barony": ""} for k, v in m.items()}
                return m
        except Exception:
            pass
    mapping = build_province_map(cfg)
    save_province_map(cfg, mapping, path)
    return mapping


# Dynasty/house definition table
# The save stores only the dynasty/house key (japanese_fujiwara, house_fujiwara_kajuji), so the
# display name has to be looked up in the game files:
#   common/dynasties/*.txt       : key = { name = "dynn_X" }  (dynasty)
#   common/dynasty_houses/*.txt  : key = { name = "dynn_Y" }  (house/branch)

def _dynasties_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "dynasties.json")


def _parse_dynasty_defs(path, out, prefixes=None):
    """Parse one dynasties/dynasty_houses txt into {key: "dynn_X" name}, taking only top-level keys
    and ignoring nested blocks. With `prefixes`, also collects `prefix = "dynnp_X"` (the nobiliary
    particle: di / de / von). Numeric dynasty-id keys and keys with - or . are valid."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fp:
            txt = fp.read()
    except Exception:
        return
    for m in re.finditer(r"^([A-Za-z0-9_][A-Za-z0-9_.\-]*)\s*=\s*\{([^{}]*)\}",
                         txt, re.M):
        key, body = m.group(1), m.group(2)
        nm = re.search(r'name\s*=\s*["\']?(dynn_[A-Za-z0-9_\-]+)', body)
        if nm:
            out[key] = nm.group(1)
        if prefixes is not None:
            pf = re.search(r'prefix\s*=\s*["\']?(dynnp_[A-Za-z0-9_\-]+)', body)
            if pf:
                prefixes[key] = pf.group(1)


def build_dynasty_table(cfg):
    """Game + mod common/dynasties and common/dynasty_houses -> {"dynasties", "houses",
    "dynasty_prefixes", "house_prefixes"} tables of dynn/dynnp names; mods override the game."""
    out = {"dynasties": {}, "houses": {},
           "dynasty_prefixes": {}, "house_prefixes": {}}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        for folder, bucket, pbucket in (("dynasties", "dynasties", "dynasty_prefixes"),
                                        ("dynasty_houses", "houses", "house_prefixes")):
            d = os.path.join(root, "common", folder)
            if not os.path.isdir(d):
                continue
            for dp, _dn, fns in os.walk(d):
                for fn in sorted(fns):
                    if fn.endswith(".txt"):
                        _parse_dynasty_defs(os.path.join(dp, fn), out[bucket],
                                            prefixes=out[pbucket])
    return out


def save_dynasty_table(cfg, table, path=None):
    path = path or _dynasties_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        # schema 2 adds the dynasty_prefixes / house_prefixes tables
        json.dump({"schema": 2,
                   "dynasties": table.get("dynasties") or {},
                   "houses": table.get("houses") or {},
                   "dynasty_prefixes": table.get("dynasty_prefixes") or {},
                   "house_prefixes": table.get("house_prefixes") or {}},
                  fp, ensure_ascii=False)
    return path


def load_dynasty_table(cfg, force=False):
    """Load the dynasty/house table, rebuilding when missing, forced, or when the file has schema<2
    (no prefix tables). Returns {"dynasties", "houses", "dynasty_prefixes", "house_prefixes"}."""
    path = _dynasties_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 2:
                return {"dynasties": data.get("dynasties") or {},
                        "houses": data.get("houses") or {},
                        "dynasty_prefixes": data.get("dynasty_prefixes") or {},
                        "house_prefixes": data.get("house_prefixes") or {}}
        except Exception:
            pass
    table = build_dynasty_table(cfg)
    save_dynasty_table(cfg, table, path)
    return table


# Currency bands: the game's LEVELS_* defines + the localization band words
# Piety/prestige/influence/merit all have numbered bands whose names live in the localization table
# (modifiers_l_simp_chinese.yml: piety_level_0, merit_level_3, ...). Thresholds come from LEVELS_* in
# common/defines/00_defines.txt; the band index is the count of thresholds the value reaches, which
# is exactly the index into the band words (piety 8 bands, prestige 5, influence 5, merit 9).

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
    """Game + enabled mods' common/defines -> {"bands": {kind: [thresholds...]}}; a currency whose
    defines cannot be read falls back to the built-in defaults.

    Only LEVELS_* inside the NCharacter block counts: the NDynasty block defines the same keys for
    dynasty prestige, and mixing them would map a character value onto a nonexistent band word."""
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
                        bands[kind] = vals  # mods override the game (later roots win)
    return {"schema": 1, "bands": bands}


def save_currency_levels(cfg, table):
    path = _currency_levels_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_currency_levels(cfg=None, force=False):
    """Load the band threshold table, rebuilding it when missing or forced."""
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
    """Value -> band index (how many thresholds it reaches); None when unparsable."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not thresholds:
        return None
    return sum(1 for t in thresholds if v >= t)


def level_word(table, bands, kind, value):
    """Value -> its band word from the localization table, '' when unknown. A missing word falls back
    to the next lower band that has one, so modded thresholds never leave the item unwritten."""
    th = (bands or {}).get(kind) or []
    n = level_index(value, th)
    if n is None:
        return ""
    for i in range(n, -1, -1):
        w = loc(table, f"{kind}_level_{i}")
        if w:
            return w
    return ""


# Court position display-name variants: court_position_asset.trigger -> localization_key
# The save stores only the position type key (court_physician_court_position); the game picks one
# localization_key among the court_position_asset variants from the employer's government,
# independence, tier and culture heritage, so one office can have several names. Recognised trigger
# shapes: government_has_flag / is_independent_ruler / highest_held_title_tier / has_cultural_pillar
# / culture_has_*_heritage_pillar_trigger / OR, AND, NOT, NOR; an unknown condition never matches.

_TIER_NUM = {"barony": 1, "county": 2, "duchy": 3, "kingdom": 4,
             "empire": 5, "hegemony": 6}


def _script_items(text):
    """CK3 script block content -> [(key, op, value|body)], order preserved, comments
    dropped."""
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
    """Every `<key> = { ... }` block body, in order."""
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
    """Top-level `key = { ... }` -> [(key, body)], in order."""
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
    """scripted_triggers entries named culture_has_*_heritage_pillar_trigger ->
    {trigger key: [heritage pillar keys]}."""
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


def _cond_block(items, groups, op="all", religions=None, split_inline=False):
    """Trigger items -> a condition tree {"op": all|any|none, "children": [leaf or subtree]}, order
    preserved. An empty block returns {} (always true); an unrecognised leaf becomes
    {"unknown": key} and never matches, which discards that variant and falls back to the position
    type key's default name. `split_inline=True` first spreads out items sharing a line."""
    children = []

    def _items(body):
        return _script_items(_split_inline_items(body) if split_inline else body)

    for key, kop, val in items:
        k = (key or "").lower()
        # ---- condition leaves needed by the GetActualBishopTitle and council-seat
        # ---- name chains
        # Must come before the generic block branches (religion = { ... } is a block too)
        if key == "religion" and kop == "block":
            # religion = { is_in_family = rf_pagan } -> religion family
            fam = ""
            for k2, _o2, v2 in _script_items(val):
                if k2 == "is_in_family":
                    fam = str(v2)
            children.append({"religion_family": fam} if fam else {"unknown": key})
            continue
        if key == "religion":
            rk = _religion_key(val, religions)
            children.append({"religion": rk} if rk else {"unknown": key})
            continue
        if key == "faith.religion":
            rk = _faith_religion_key(val, religions)
            children.append({"religion": rk} if rk else {"unknown": key})
            continue
        elif key == "has_doctrine":
            children.append({"doctrine": str(val)})
            continue
        # `rite = rite:roman_rite` / `rite_has_doctrine = doctrine_x`: used by the
        # council-seat name chains in common/council_positions/00_council_positions.txt,
        # evaluated against the scope's rite / rite_doctrines, which facts fills in from
        # the character's rite.
        if key == "rite":
            if kop == "block":
                # block form `rite = { rite_has_doctrine = X }`, used by the NOR arm of
                # GetActualDukeTheocracyTitle; only the scalar form is recognised otherwise
                children.append(_cond_block(_items(val), groups, "all", religions,
                                            split_inline))
                continue
            rk = str(val or "").strip()
            if rk.startswith("rite:"):
                rk = rk[len("rite:"):]
            children.append({"rite": rk} if rk else {"unknown": key})
            continue
        if key == "rite_has_doctrine":
            children.append({"rite_doctrine": str(val)})
            continue
        # Leaves used by the triggers behind the [CHARACTER.Custom('GetActualDukeTheocracyTitle')]
        # family of custom loc keys (the Christian theocratic office titles in
        # culture_titles_l_simp_chinese.yml): is_female / faith / has_title /
        # any_held_title (tier + has_clerical_region) / has_clerical_region.
        if key == "is_female":
            children.append({"female": str(val).strip().lower() in ("yes", "true")})
            continue
        if key == "faith":
            fk = str(val or "").strip()
            if fk.startswith("faith:"):
                fk = fk[len("faith:"):]
            children.append({"faith": fk} if fk else {"unknown": key})
            continue
        if key == "has_title":
            tk = str(val or "").strip()
            if tk.startswith("title:"):
                tk = tk[len("title:"):]
            children.append({"title_in": [tk]} if tk else {"unknown": key})
            continue
        if key == "any_held_title" and kop == "block":
            children.append({"any_held_title": _cond_block(
                _items(val), groups, "all", religions, split_inline)})
            continue
        # `tier = tier_duchy` (inside any_held_title) and `is_landless_type_title`:
        # without the former, the `duke_theocracy_*_clerical_region*` family of titles
        # (archbishop / metropolitan / patriarch) could never match, because that leaf
        # was recorded as unknown.
        if key == "tier":
            _t = _TIER_NUM.get(str(val).replace("tier_", "").lower())
            if _t is None:
                children.append({"unknown": key})
            else:
                # the two leaves must stay separate: cond_match returns on the first key it hits
                children.append({"tier_min": _t})
                children.append({"tier_max": _t})
            continue
        if key == "is_landless_type_title":
            children.append({"landless":
                             str(val).strip().lower() in ("yes", "true")})
            continue
        if key == "has_clerical_region":
            children.append({"clerical_region":
                             str(val).strip().lower() in ("yes", "true")})
            continue
        # `government_allows` was renamed `government_has_mechanic`; both are synonyms
        # and both map to the gov_flag leaf.
        if key in ("government_allows", "government_has_mechanic"):
            children.append({"gov_flag": str(val).replace("government_is_", "")})
            continue
        if key.startswith("cp:") and kop == "?=":
            fem = None
            for k2, _o2, v2 in _script_items(val):
                if k2 == "is_female":
                    fem = str(v2).lower() in ("yes", "true")
            children.append({"chaplain_female": fem} if fem is not None
                            else {"unknown": key})
            continue
        if kop == "block" and k in ("or", "any"):
            children.append(_cond_block(_items(val), groups, "any", religions,
                                        split_inline))
        elif kop == "block" and k in ("and", "all", "culture", "root.culture"):
            children.append(_cond_block(_items(val), groups, "all", religions,
                                        split_inline))
        elif kop == "block" and k in ("not", "nor", "none"):
            children.append(_cond_block(_items(val), groups, "none", religions,
                                        split_inline))
        elif kop == "block":
            children.append(_cond_block(_items(val), groups, "all", religions,
                                        split_inline))
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
            elif kop == "=":
                children.append({"tier_min": t})
                children.append({"tier_max": t})
            else:
                children.append({"unknown": key})
        else:
            children.append({"unknown": key})
    return {"op": op, "children": children} if children else {}


def _religion_key(val, religions=None):
    """`religion = religion:buddhism_religion` -> 'buddhism_religion' ('' when unparsable)."""
    s = str(val or "").strip()
    if s.startswith("religion:"):
        return s[len("religion:"):]
    return ""


def _faith_religion_key(val, religions=None):
    """`faith.religion = ...` -> that faith's religion key, '' when unparsable; the map comes from
    _religion_maps (common/religion/religion_types/*.txt) and without it the leaf never matches."""
    s = str(val or "").strip()
    tail = ".religion"
    if s.startswith("faith:") and s.endswith(tail):
        fk = s[len("faith:"):-len(tail)]
        return ((religions or {}).get("faiths") or {}).get(fk) or ""
    return ""


def cond_match(cond, scope):
    """Evaluate a condition tree against scope. An empty condition is always true (a variant
    without a trigger is the default name); an unknown condition never matches."""
    if not isinstance(cond, dict):
        return False
    if not cond:
        return True
    if "unknown" in cond:
        return False
    if "exists" in cond:
        # Truthiness, not mere presence: counting False/0/[] as "exists" made
        # `exists = clerical_elector_title` true for every duke-tier theocratic ruler, so
        # all of them matched the cardinal arm. This matches the game's own `exists`.
        return bool(scope.get(str(cond["exists"])))
    if "landless" in cond:
        return bool(scope.get("landless")) == bool(cond["landless"])
    if "gov_flag" in cond:
        return scope.get("gov_flag") == cond["gov_flag"]
    if "independent" in cond:
        return bool(scope.get("independent")) == bool(cond["independent"])
    if "tier_min" in cond:
        return (scope.get("tier") or 0) >= cond["tier_min"]
    if "tier_max" in cond:
        return 0 < (scope.get("tier") or 0) <= cond["tier_max"]
    if "heritage" in cond:
        # `has_cultural_pillar` can name any cultural pillar (heritage_, language_,
        # ethos_, tradition_): a scope carrying a `pillars` set is tested as a set,
        # otherwise the single-value comparison applies.
        _pl = scope.get("pillars")
        if _pl:
            return cond["heritage"] in _pl
        return scope.get("heritage") == cond["heritage"]
    if "heritage_in" in cond:
        _want = cond["heritage_in"] or []
        if scope.get("heritage") in _want:
            return True
        _pl = scope.get("pillars")
        return bool(_pl) and any(p in _want for p in _pl)
    # ---- condition leaves of the bishop-title / council-seat name chains
    if "religion" in cond:
        return scope.get("religion") == cond["religion"]
    if "religion_family" in cond:
        return scope.get("religion_family") == cond["religion_family"]
    if "doctrine" in cond:
        return str(cond["doctrine"]) in (scope.get("doctrines") or ())
    if "rite" in cond:
        return scope.get("rite") == cond["rite"]
    if "rite_doctrine" in cond:
        return str(cond["rite_doctrine"]) in (scope.get("rite_doctrines") or ())
    if "chaplain_female" in cond:
        return bool(scope.get("chaplain_female")) == bool(cond["chaplain_female"])
    # ---- condition leaves of the custom-localization arms ----
    if "female" in cond:
        return bool(scope.get("female")) == bool(cond["female"])
    if "faith" in cond:
        return scope.get("faith") == cond["faith"]
    if "title_in" in cond:
        want = cond["title_in"] or []
        have = scope.get("title_keys") or ()
        return any(k in have for k in want)
    if "clerical_region" in cond:
        return bool(scope.get("clerical_region")) == bool(cond["clerical_region"])
    if "any_held_title" in cond:
        # any_held_title: true when any held title satisfies the sub-condition
        return any(cond_match(cond["any_held_title"], t)
                   for t in (scope.get("held_titles") or ()))
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
    """Game + enabled mods' court_positions/types/*.txt -> {"positions": {type_key: [{"loc_key",
    "when"}, ...]}}, in order, including default variants that carry no loc_key."""
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
                    positions[key] = variants     # a same-key mod definition replaces the entry
    return {"schema": 1, "heritage_groups": groups, "positions": positions}


def save_court_positions(cfg, table):
    path = _court_positions_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_court_positions(cfg=None, force=False):
    """Load the court position variant table, rebuilding it when missing or forced (a
    static table built from the same sources as the localization table)."""
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
    """First matching variant's display name in court_position_asset order; '' when the variant has no
    localization_key or nothing matches, and the caller then uses the position type key's name."""
    variants = ((positions or {}).get("positions") or {}).get(type_key) or []
    for v in variants:
        if cond_match(v.get("when") or {}, scope or {}):
            k = v.get("loc_key") or ""
            return (loc(table, k) or "") if k else ""
    return ""


# Council seats: the `position` field of common/council_tasks/*.txt
# Every council task block names `position = councillor_steward` (or minister_personnel under an
# administrative government), and that name is resolved per government to a variant key
# (councillor_steward_celestial_government_non_imperial vs _imperial). The save stores only the
# task id, so this table is what lets a seat be written with its office name.

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
    """Game + enabled mods' council_tasks -> {"tasks": {task key: seat key}}."""
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
    """Load the council task -> seat table, rebuilding it when missing or forced."""
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
    """Council task -> that seat's office word per government: <seat>_<government>_government_imperial
    (or _non_imperial), then _government, then the non-celestial variant, then the bare seat key."""
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
        # reject unresolved references ($X$ / [X]) and English fallbacks (pure-ASCII words)
        if v and not v.startswith("$") and not v.startswith("[") \
                and not re.search(r"[A-Za-z]{2,}", v):
            return v
    return ""


# Bishop title arm table: GetActualBishopTitle in common/customizable_localization
# The game hands the court chaplain's church word to GetActualBishopTitle
# (00_divinity_custom_loc.txt): an ordered list of `text = { trigger = ... localization_key = ... }`
# arms where the first match wins, so the Japanese Buddhist arm precedes the generic Buddhist/Indian
# ones. Indexing arms by religion group x tier alone can never reach the keys that carry no tier
# suffix, so they are parsed from the game data as build_court_positions does.


def _data_roots(cfg):
    """Root directory sequence for table builds: base game first, enabled mods after
    (later entries override earlier ones)."""
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    return roots


def _strip_comments(txt):
    """Drop whole-line comments from a CK3 script: the block scanners only pair braces, so a
    commented-out `text = { ... }` arm with an empty trigger would match every scope."""
    out = []
    for ln in (txt or "").split("\n"):
        if ln.lstrip().startswith("#"):
            continue
        out.append(ln)
    return "\n".join(out)


# start of an inline "key operator" pair; used to split several items sharing one line
_INLINE_ITEM_RE = re.compile(
    r"(?<=\S)\s+(?=[A-Za-z_][A-Za-z0-9_.:]*(?:\s*(?:>=|<=|!=|\?=|=|>|<)))")


def _split_inline_items(txt):
    """Spread several condition items sharing one line onto one line each.

    CK3 scripts often put two or three conditions on one line, which `_script_items` would swallow
    into the first item's value. Enabled only for the newer parsers so the court position table keeps
    its established behaviour."""
    return _INLINE_ITEM_RE.sub("\n", txt or "")


def _religion_maps(cfg, roots=None):
    """common/religion/religion_types/*.txt and common/religion/faith_types/*.txt ->
    {"religions": {religion key: family}, "faiths": {faith key: religion key}}. The family map serves
    `is_in_family = rf_pagan`; the faith map folds `faith.religion = ...` into the religion key.

    Both directories are needed because the faith definitions live in faith_types, so religion_types
    alone leaves every `faith.religion` leaf in the bishop arms unmatched. Within one root faith_types
    is scanned last, and mods after the game."""
    religions, faiths = {}, {}
    _DIRS = (("religion_types", "family"), ("faith_types", "religion"))
    for root in (roots if roots is not None else _data_roots(cfg)):
        for sub, link in _DIRS:
            d = os.path.join(root, "common", "religion", sub)
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                if not fn.endswith(".txt"):
                    continue
                try:
                    with open(os.path.join(d, fn), encoding="utf-8-sig",
                              errors="replace") as fp:
                        txt = _strip_comments(fp.read())
                except OSError:
                    continue
                for key, body in _top_blocks(txt):
                    if sub == "religion_types":
                        m = re.search(
                            r"(?<![A-Za-z0-9_])family\s*=\s*([A-Za-z0-9_]+)", body)
                        if m:
                            religions[key] = m.group(1)
                        for fb in _blocks_of(body, "faiths"):
                            for fk, _fbody in _top_blocks(fb):
                                faiths[fk] = key
                    else:
                        # faith_types: each block is one faith; `faith_type = <key>` is
                        # the key it had in the older layout, and `religion = <id/key>`
                        # names the religion it belongs to — when religion is a block,
                        # take its tag/religion_type.
                        fkey = key
                        m = re.search(
                            r"(?<![A-Za-z0-9_])faith_type\s*=\s*([A-Za-z0-9_]+)", body)
                        if m:
                            fkey = m.group(1)
                        rb = _blocks_of(body, "religion")
                        rkey = ""
                        for _rb in rb:
                            mk = re.search(
                                r"(?<![A-Za-z0-9_])(?:tag|religion_type)\s*=\s*"
                                r"([A-Za-z0-9_]+)", _rb)
                            if mk:
                                rkey = mk.group(1)
                                break
                        if not rkey:
                            mk = re.search(
                                r"(?<![A-Za-z0-9_])religion\s*=\s*([A-Za-z0-9_]+)",
                                body)
                            if mk:
                                rkey = mk.group(1)
                        if rkey:
                            faiths[fkey] = rkey
    return {"religions": religions, "faiths": faiths}


def _bishop_titles_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "bishop_titles.json")


def build_bishop_titles(cfg):
    """GetActualBishopTitle's ordered arms -> {"arms": [{"loc_key", "when"}...], "religions": {...},
    "faiths": {...}}; a same-named mod block replaces the whole entry.

    schema 4 marks condition trees using the current leaf set (is_female / faith / has_title /
    any_held_title / block-form rite, plus truthiness for `exists`); older tables must be rebuilt."""
    groups = _heritage_groups(cfg)
    roots = _data_roots(cfg)
    rel = _religion_maps(cfg, roots)
    arms = []
    for root in roots:
        d = os.path.join(root, "common", "customizable_localization")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    txt = _strip_comments(fp.read())
            except OSError:
                continue
            for key, body in _top_blocks(txt):
                if key != "GetActualBishopTitle":
                    continue
                arms = []          # a same-named mod block replaces the whole arm list
                for blk in _blocks_of(body, "text"):
                    lk = re.search(r"localization_key\s*=\s*([A-Za-z0-9_]+)", blk)
                    tr = _blocks_of(blk, "trigger")
                    cond = _cond_block(_script_items(_split_inline_items(tr[0])),
                                       groups, religions=rel, split_inline=True) \
                        if tr else {}
                    arms.append({"loc_key": lk.group(1) if lk else "",
                                 "when": cond})
    # schema 4: the arm conditions are parsed with the `tier` and
    # `is_landless_type_title` leaves and with truthiness for `exists`, so tables from
    # earlier schemas, where those leaves stayed unknown, must be rebuilt.
    return {"schema": 4, "arms": arms,
            "religions": rel.get("religions") or {},
            "faiths": rel.get("faiths") or {}}


def save_bishop_titles(cfg, table):
    path = _bishop_titles_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_bishop_titles(cfg=None, force=False):
    """Load the bishop title arm table, rebuilding it when missing or forced (a static
    table built from the same sources as the localization table)."""
    cfg = cfg or llm.load_config()
    path = _bishop_titles_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 4 and data.get("arms"):
                return data
        except Exception:
            pass
    data = build_bishop_titles(cfg)
    save_bishop_titles(cfg, data)
    return data


def pick_bishop_title(table, scope):
    """Localization key of the first matching arm ('' when none match)."""
    return pick_arm((table or {}).get("arms") or [], scope)


def pick_arm(arms, scope):
    """Localization key of the first matching arm, '' when none match; an empty condition
    is always true (the game's fallback arm)."""
    for a in arms or []:
        if cond_match(a.get("when") or {}, scope or {}):
            return a.get("loc_key") or ""
    return ""


# Spiritual fulfillment band table
# The game ships official level names in two sets, dispatched by religion
# (common/spiritual_fulfillment/00_spiritual_fulfillment_types.txt): christian_fulfillment with
# 7 level bands, default_fulfillment with 5 as the fallback. The level name is
# `<type key>_level_<i>`, i counting from 0 in block order, and the words live in
# localization/simp_chinese/modifiers/pam_modifiers_l_simp_chinese.yml. Values span -100..100
# (common/defines/00_defines.txt); the band is the last `threshold <= value`.


def _spiritual_fulfillment_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "spiritual_fulfillment.json")


def build_spiritual_fulfillment(cfg):
    """-> {"schema": 1, "types": [{"key", "religions": [...], "levels": [{"threshold": ...}]}...],
    "religions"/"faiths": the religion/faith maps, from the same source as the bishop arm table."""
    roots = _data_roots(cfg)
    rel = _religion_maps(cfg, roots)
    types = []
    for root in roots:
        d = os.path.join(root, "common", "spiritual_fulfillment")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    txt = _strip_comments(fp.read())
            except OSError:
                continue
            for key, body in _top_blocks(txt):
                m = re.search(r"\breligions\s*=\s*\{([^}]*)\}", body)
                religions = m.group(1).split() if m else []
                levels = []
                for blk in _blocks_of(body, "level"):
                    tm = re.search(r"threshold\s*=\s*(-?\d+(?:\.\d+)?)", blk)
                    if not tm:
                        continue
                    fv = float(tm.group(1))
                    levels.append({"threshold": int(fv) if fv.is_integer() else fv})
                if levels:
                    types.append({"key": key, "religions": religions,
                                  "levels": levels})
    return {"schema": 1, "types": types,
            "religions": rel.get("religions") or {},
            "faiths": rel.get("faiths") or {}}


def save_spiritual_fulfillment(cfg, table):
    path = _spiritual_fulfillment_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_spiritual_fulfillment(cfg=None, force=False):
    """Load the spiritual fulfillment band table, rebuilding it when missing or when the
    schema differs (a static table built from the same sources as the localization table)."""
    cfg = cfg or llm.load_config()
    path = _spiritual_fulfillment_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 1 and data.get("types"):
                return data
        except Exception:
            pass
    data = build_spiritual_fulfillment(cfg)
    if data.get("types"):
        save_spiritual_fulfillment(cfg, data)
    return data


def sf_type_for(table, religion_key):
    """Religion key -> its band type: a type listing that religion wins, otherwise the type
    without a `religions` list (the fallback)."""
    types = (table or {}).get("types") or []
    for t in types:
        if religion_key and religion_key in (t.get("religions") or []):
            return t
    for t in types:
        if not (t.get("religions") or []):
            return t
    return types[0] if types else {}


def sf_level_index(levels, value):
    """Index of the last level whose `threshold <= value` (0 when below the first band)."""
    idx = 0
    for i, lv in enumerate(levels or []):
        th = (lv or {}).get("threshold")
        if isinstance(th, (int, float)) and value is not None and value >= th:
            idx = i
    return idx


# Custom-localization arm tables for theocratic office titles
# The game delegates a Christian theocratic ruler's office title to custom localization (keys in
# culture_titles_l_simp_chinese.yml such as duke_theocracy_male_christianity_religion, defined in
# common/customizable_localization/00_divinity_custom_loc.txt). localization.loc strips a whole
# `[...]` reference, so those titles come from the arms: the two Theocracy blocks are parsed here and
# evaluated against Facts._theocracy_scope.

_THEOCRACY_CUSTOM_BLOCKS = ("GetActualDukeTheocracyTitle",
                            "GetActualCountTheocracyTitle")


def _custom_loc_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "theocracy_titles.json")


def build_theocracy_titles(cfg):
    """The two theocracy title blocks -> {"blocks": {block name: [arms...]},
    "religions"/"faiths": maps}."""
    groups = _heritage_groups(cfg)
    roots = _data_roots(cfg)
    rel = _religion_maps(cfg, roots)
    blocks = {}
    for root in roots:
        d = os.path.join(root, "common", "customizable_localization")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    txt = _strip_comments(fp.read())
            except OSError:
                continue
            for key, body in _top_blocks(txt):
                if key not in _THEOCRACY_CUSTOM_BLOCKS:
                    continue
                arms = []          # a same-named mod block replaces the whole arm list
                for blk in _blocks_of(body, "text"):
                    lk = re.search(r"localization_key\s*=\s*([A-Za-z0-9_]+)", blk)
                    tr = _blocks_of(blk, "trigger")
                    cond = _cond_block(_script_items(_split_inline_items(tr[0])),
                                       groups, religions=rel, split_inline=True) \
                        if tr else {}
                    arms.append({"loc_key": lk.group(1) if lk else "",
                                 "when": cond})
                if arms:
                    blocks[key] = arms
    # schema 2: as in bishop_titles, the arm conditions use the `tier` and
    # `is_landless_type_title` leaves and truthiness for `exists`, so earlier tables must
    # be rebuilt.
    return {"schema": 2, "blocks": blocks,
            "religions": rel.get("religions") or {},
            "faiths": rel.get("faiths") or {}}


def save_theocracy_titles(cfg, table):
    path = _custom_loc_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_theocracy_titles(cfg=None, force=False):
    """Load the theocracy title arm table, rebuilding it when missing or forced (built from
    the same sources as the bishop arm table)."""
    cfg = cfg or llm.load_config()
    path = _custom_loc_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 2 and data.get("blocks"):
                return data
        except Exception:
            pass
    data = build_theocracy_titles(cfg)
    save_theocracy_titles(cfg, data)
    return data


def pick_custom_loc(table, key, scope):
    """Localization key of the first matching arm in that block ('' when the table or the
    block is missing, or when nothing matches)."""
    return pick_arm(((table or {}).get("blocks") or {}).get(key) or [], scope)


# Council seat name chains: `name = { first_valid = ... }` in common/council_positions
# Under a temporal theocracy doctrine (doctrine_theocracy_temporal) or a pagan religion family
# (rf_pagan) the game delegates the whole court chaplain seat NAME to `actual_bishop_title` (the name
# chain in 00_council_positions.txt), so the correct string is a personal bishop name rather than
# "court chaplain" with a church word appended.


def _council_names_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "council_names.json")


def _name_arms(block, groups, religions, extra=None):
    """A `name` chain -> [{"desc": loc key or 'actual_bishop_title', "when": tree}...], in order.
    `desc` may be nested (`desc = { first_valid = { ... } }`) and is ANDed with the outer trigger."""
    out = []
    for blk in _blocks_of(block, "triggered_desc"):
        tr = _blocks_of(blk, "trigger")
        cond = _cond_block(_script_items(_split_inline_items(tr[0])), groups,
                           religions=religions, split_inline=True) if tr else {}
        if extra:
            cond = {"op": "all", "children": [extra, cond]} if cond else extra
        m = re.search(r"desc\s*=\s*([A-Za-z0-9_]+)", blk)
        if m:
            out.append({"desc": m.group(1), "when": cond})
            continue
        db = _blocks_of(blk, "desc")
        if db:
            fv = _blocks_of(db[0], "first_valid")
            src = fv[0] if fv else db[0]
            out.extend(_name_arms(src, groups, religions, extra=cond))
    return out


def build_council_names(cfg):
    """Every council seat's `name` chain -> {"positions": {seat key: [arms...]}}, game plus
    enabled mods."""
    groups = _heritage_groups(cfg)
    roots = _data_roots(cfg)
    rel = _religion_maps(cfg, roots)
    positions = {}
    for root in roots:
        d = os.path.join(root, "common", "council_positions")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    txt = _strip_comments(fp.read())
            except OSError:
                continue
            for key, body in _top_blocks(txt):
                nb = _blocks_of(body, "name")
                if not nb:
                    continue
                fv = _blocks_of(nb[0], "first_valid")
                src = fv[0] if fv else nb[0]
                arms = _name_arms(src, groups, rel)
                if arms:
                    positions[key] = arms     # a same-key mod definition replaces the entry
    return {"schema": 2, "positions": positions}


def save_council_names(cfg, table):
    path = _council_names_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_council_names(cfg=None, force=False):
    cfg = cfg or llm.load_config()
    path = _council_names_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 2 and data.get("positions"):
                return data
        except Exception:
            pass
    data = build_council_names(cfg)
    save_council_names(cfg, data)
    return data


def council_name_desc(table, position, scope):
    """The desc of the first matching arm in that seat's name chain ('' when no table or no
    match). `actual_bishop_title` is the game-side delegation marker for Facts.chaplain_title."""
    for a in ((table or {}).get("positions") or {}).get(position) or []:
        if cond_match(a.get("when") or {}, scope or {}):
            return a.get("desc") or ""
    return ""


# Trait display-name key table: the name block in common/traits/*.txt -> desc key
# Some traits (the traveller lifestyle trait, for instance) do not take their display name from
# trait_<key>; the trait definition supplies it through
# name = { first_valid = { ... desc = ... } }, which is common for mod traits. Without this table such
# a trait is dropped entirely.

def _trait_names_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "trait_names.json")


def _body_at(text, i):
    """i points at '{' -> the balanced block body without the outer braces; an unclosed
    block returns the rest of the text."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j]
    return text[i + 1:]


def _strip_blocks(text, key):
    """Remove every `<key> = { ... }` block while keeping the rest of the text, so the bare
    descs left in a block become reachable."""
    out = text
    while True:
        m = re.search(r"(?<![A-Za-z0-9_])" + re.escape(key) + r"\s*=\s*\{", out)
        if not m:
            return out
        i = m.end() - 1
        j = i
        depth = 0
        while j < len(out):
            if out[j] == "{":
                depth += 1
            elif out[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out = out[:m.start()] + out[j + 1:]


def _xp_clauses(trigger):
    """A trigger block -> {"any": bool, "clauses": [{track, op, value}...]}; None without XP
    conditions. Only `has_trait_xp = { track=... value <op> N }` is recognised and clauses inside
    `OR = { ... }` evaluate as "any"; a missing `track` is inferred by the render layer."""
    spans = []
    for m in re.finditer(r"(?<![A-Za-z0-9_])has_trait_xp\s*=\s*\{", trigger or ""):
        i = m.end() - 1
        clause = _body_at(trigger, i)
        tr = re.search(r"(?<![A-Za-z0-9_])track\s*=\s*([A-Za-z0-9_]+)", clause)
        vm = re.search(r"(?<![A-Za-z0-9_])(value)\s*(>=|<=|!=|=|<|>)\s*(\d+)",
                       clause)
        if not vm:
            continue
        spans.append((m.start(), {"track": tr.group(1) if tr else None,
                                  "op": vm.group(2), "value": int(vm.group(3))}))
    if not spans:
        return None
    or_ranges = []
    for m in re.finditer(r"(?<![A-Za-z0-9_])OR\s*=\s*\{", trigger or ""):
        i = m.end() - 1
        j = i
        depth = 0
        while j < len(trigger):
            if trigger[j] == "{":
                depth += 1
            elif trigger[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        or_ranges.append((i, j))
    any_of = any(any(a <= pos <= b for a, b in or_ranges) for pos, _c in spans)
    return {"any": any_of, "clauses": [c for _p, c in spans]}


def _iter_trait_files(cfg):
    """Paths of the .txt files under common/traits and common/traits/tracks, for the game
    and the enabled mods."""
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
                if fn.endswith(".txt"):
                    yield os.path.join(d, fn)


def trait_source_fingerprint(cfg):
    """Trait source fingerprint: the game/mod dirs plus each trait file's (path, size, mtime), stored
    in data/trait_names.json; a mismatch rebuilds. Schema checks alone would keep a table built before
    a mod was enabled, silently dropping that mod's traits. Only metadata is read here."""
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(("game", g))
    for i, m in enumerate(enabled_mod_dirs(cfg)):
        roots.append((f"mod{i}", m))
    files = []
    for path in _iter_trait_files(cfg):
        try:
            st = os.stat(path)
            files.append([path, int(st.st_size), int(st.st_mtime)])
        except OSError:
            continue
    detail = {"roots": [[n, p] for n, p in roots], "files": sorted(files)}
    blob = json.dumps(detail, ensure_ascii=False, sort_keys=True)
    return {
        "hash": hashlib.sha1(blob.encode("utf-8")).hexdigest(),
        "mods": [p for n, p in roots if n != "game"],
        "game": g or "",
        "files": len(files),
    }


def build_trait_names(cfg):
    """Game + enabled mods' common/traits -> trait base names, categories and XP-level renames:
        {"schema": 4,
         "traits":      {trait_key: loc_key},      # base name
         "categories":  {trait_key: category},     # the game's category field
         "level_names": {trait_key: [{"any": bool,
                                      "clauses": [{track, op, value}, ...],
                                      "key": loc_key}, ...]}}   # rename by XP

    `category` (personality|education|lifestyle|fame|health|commander|childhood|court_type) splits
    the "character" sentences and keeps transient health traits out of the history; inborn traits
    (beauty_*, intellect_*, ...) have no category in the game data and get ''. The base name is the
    bare, trigger-free desc inside `first_valid`; each levelled name keeps its XP condition."""
    out = {}
    cats = {}
    levels = {}
    for path in _iter_trait_files(cfg):
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as fp:
                txt = fp.read()
        except OSError:
            continue
        for key, body in _top_blocks(txt):
            if key.startswith("@"):
                continue
            cb = re.search(r"(?<![A-Za-z_])category\s*=\s*([A-Za-z_]+)", body)
            if cb:
                cats[key] = cb.group(1)
            nb = re.search(r"(?<![A-Za-z0-9_])name\s*=\s*\{", body)
            if not nb:
                m = re.search(r"(?<![A-Za-z_])name\s*=\s*([A-Za-z0-9_.]+)", body)
                if m and not m.group(1).startswith(("$", "[")):
                    out[key] = m.group(1)
                continue
            nbody = _body_at(body, nb.end() - 1)
            fv = _blocks_of(nbody, "first_valid")
            scope = fv[0] if fv else nbody
            rows = []
            for td in _blocks_of(scope, "triggered_desc"):
                dm = re.search(r"(?<![A-Za-z0-9_])desc\s*=\s*([A-Za-z0-9_.]+)", td)
                if not dm or dm.group(1).startswith(("$", "[")):
                    continue
                tm = re.search(r"(?<![A-Za-z0-9_])trigger\s*=\s*\{", td)
                cond = _xp_clauses(_body_at(td, tm.end() - 1)) if tm else None
                if cond:
                    cond["key"] = dm.group(1)
                    rows.append(cond)
            base = re.search(r"(?<![A-Za-z0-9_])desc\s*=\s*([A-Za-z0-9_.]+)",
                             _strip_blocks(scope, "triggered_desc"))
            if base and not base.group(1).startswith(("$", "[")):
                out[key] = base.group(1)
            elif rows:
                out[key] = rows[-1]["key"]
            if rows:
                levels[key] = rows
    return {"schema": 4, "traits": out, "categories": cats,
            "level_names": levels, "fingerprint": trait_source_fingerprint(cfg)}


# Trait XP track table: track / tracks in common/traits -> track name + level thresholds
# A character's `trait_xp_amounts` in the save is a flat array aligned with `traits`, one number per
# track (a multi-track trait occupies several slots in declaration order). This table says which slot
# belongs to which track and what its level thresholds are; a track's display name comes from the
# localization key `trait_track_<key>`.

def _trait_tracks_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "trait_tracks.json")


# Named level keys -> XP thresholds (a few traits such as scarred and lifestyle_traveler use
# named keys instead of numbers; scarred's name block reads value < 50 -> level one,
# = 100 -> level three)
_NAMED_LEVELS = {"trait_first_level": 25, "trait_second_level": 50,
                 "trait_third_level": 100, "trait_fourth_level": 150,
                 "trait_fifth_level": 200}


def _track_levels(sub):
    """Track inner block -> its threshold list (numeric keys taken as they are, named level
    keys converted through _NAMED_LEVELS)."""
    lv = [int(x) for x in re.findall(r"^\s*(\d+)\s*=\s*\{", sub, re.M)]
    lv += [_NAMED_LEVELS[k] for k in
           re.findall(r"^\s*(trait_[a-z_]*level)\s*=\s*\{", sub, re.M)
           if k in _NAMED_LEVELS]
    return sorted(set(lv))


def build_trait_tracks(cfg):
    """Game + enabled mods' common/traits -> {"tracks": {trait: [{track, levels}, ...]}}. A
    multi-track `tracks = { ... }` keeps declaration order; the `track` shorthand uses the trait key."""
    out = {}
    for path in _iter_trait_files(cfg):
        try:
            with open(path, encoding="utf-8-sig", errors="replace") as fp:
                txt = fp.read()
        except OSError:
            continue
        for key, body in _top_blocks(txt):
            if key.startswith("@"):
                continue
            rows = []
            mt = re.search(r"^\s*tracks\s*=\s*\{", body, re.M)
            if mt:
                tb = _body_at(body, mt.end() - 1)
                for tm in re.finditer(
                        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{", tb, re.M):
                    lv = _track_levels(_body_at(tb, tm.end() - 1))
                    if lv:
                        rows.append({"track": tm.group(1), "levels": lv})
            else:
                ms = re.search(r"^\s*track\s*=\s*\{", body, re.M)
                if ms:
                    lv = _track_levels(_body_at(body, ms.end() - 1))
                    if lv:
                        rows.append({"track": key, "levels": lv})
            if rows:
                out[key] = rows
    return {"schema": 2, "tracks": out,
            "fingerprint": trait_source_fingerprint(cfg)}


def save_trait_tracks(cfg, table):
    path = _trait_tracks_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_trait_tracks(cfg=None, force=False, report=None):
    """Load the trait track table, rebuilding when missing, when the schema is old, or when the
    fingerprint differs. A rebuild yielding under 60% of the cached tracks is discarded, so an
    unavailable game dir cannot wipe a good table; `report` receives the self-check entry."""
    cfg = cfg or llm.load_config()
    path = _trait_tracks_path(cfg)
    cached, why = None, "表缺失"
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                cached = json.load(fp)
        except Exception:
            cached, why = None, "表文件不可解析"
        if cached is not None and not force:
            if cached.get("schema") == 2 and "tracks" in cached:
                cur = trait_source_fingerprint(cfg).get("hash")
                if (cached.get("fingerprint") or {}).get("hash") == cur:
                    _fill_report(report, "ok", len(cached.get("tracks") or {}),
                                 "来源指纹一致")
                    return cached
                # a fingerprint mismatch is only reported, never auto-rebuilt (see the
                # matching note in load_localization_table)
                why = "启用 Mod / 特质定义已变化"
                llm.log(f"特质轨道表已过期 ({why}) —— 本轮沿用现有表; "
                        f"要更新请运行 重建对照表.bat。")
                _fill_report(report, "outdated", len(cached.get("tracks") or {}), why)
                return cached
            else:
                why = "旧版表或文件不可解析"
    llm.log(f"特质轨道表需重建 ({why})。")
    data = build_trait_tracks(cfg)
    new_n = len(data.get("tracks") or {})
    old_n = len((cached or {}).get("tracks") or {})
    if cached and new_n < old_n * 0.6:
        llm.log(f"特质轨道表重建结果偏小 ({new_n} 条 < 旧表 {old_n} 条的六成) —— "
                f"疑游戏目录不可用, 保留旧表不落盘。若确为游戏更新, 请删 {path} 后重建。")
        _fill_report(report, "kept-old", old_n, f"重建结果偏小 ({new_n} 条), 保留旧表")
        return cached
    save_trait_tracks(cfg, data)
    _fill_report(report, "rebuilt", new_n, why)
    return data


def save_trait_names(cfg, table):
    path = _trait_names_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(table, fp, ensure_ascii=False)
    return path


def load_trait_names(cfg=None, force=False, report=None):
    """Load the trait display-name and category table, rebuilding when missing, when its shape is old
    (no categories / level_names), or when the fingerprint differs; a rebuild under 60% is discarded."""
    cfg = cfg or llm.load_config()
    path = _trait_names_path(cfg)
    cached, why = None, "表缺失"
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                cached = json.load(fp)
        except Exception:
            cached, why = None, "表文件不可解析"
        if cached is not None and not force:
            if cached.get("schema") == 4 and cached.get("traits") \
                    and "categories" in cached and "level_names" in cached:
                cur = trait_source_fingerprint(cfg).get("hash")
                if (cached.get("fingerprint") or {}).get("hash") == cur:
                    _fill_report(report, "ok", len(cached.get("traits") or {}),
                                 "来源指纹一致")
                    return cached
                # a fingerprint mismatch is only reported, never auto-rebuilt
                why = "启用 Mod / 特质定义已变化"
                llm.log(f"特质显示名表已过期 ({why}) —— 本轮沿用现有表; "
                        f"要更新请运行 重建对照表.bat。")
                _fill_report(report, "outdated", len(cached.get("traits") or {}), why)
                return cached
            else:
                why = "旧版表或文件不可解析"
    llm.log(f"特质显示名表需重建 ({why})。")
    data = build_trait_names(cfg)
    new_n = len(data.get("traits") or {})
    old_n = len((cached or {}).get("traits") or {})
    if cached and new_n < old_n * 0.6:
        llm.log(f"特质显示名表重建结果偏小 ({new_n} 条 < 旧表 {old_n} 条的六成) —— "
                f"疑游戏目录不可用, 保留旧表不落盘。若确为游戏更新, 请删 {path} 后重建。")
        _fill_report(report, "kept-old", old_n, f"重建结果偏小 ({new_n} 条), 保留旧表")
        return cached
    save_trait_names(cfg, data)
    _fill_report(report, "rebuilt", new_n, why)
    return data


# Hook type table: common/hook_types/*.txt -> the strong and perpetual flags
# A save's hooks carry only the type key (favor_hook, house_head_hook, ...), whose display name
# comes from the localization table. Strength and permanence have to be read from the type
# definition: `strong = yes` marks a strong hook, `perpetual = yes` or `expiration_days = -1` makes
# one permanent. Mod definitions count as well.

def _hook_types_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "hook_types.json")


def build_hook_types(cfg):
    """Game + enabled mods' common/hook_types -> {"hook_types": {key: {strong, perpetual,
    expiration_days}}}."""
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
    """Load the hook type table, rebuilding it when missing or forced (a static table built
    from the same sources as the localization table)."""
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
    """Hook type key -> display name from the localization table under the same key ('' when
    unknown)."""
    v = loc(table, key) or ""
    return "" if (not v or re.search(r"[A-Za-z_]", v)) else v


# Generic tier words (dynamic)

TIER_KEY_OF_PREFIX = {"e_": "empire", "k_": "kingdom", "d_": "duchy",
                      "c_": "county", "b_": "barony", "h_": "hegemon"}

GENERIC_TIER_ZH = {"empire": "帝国", "kingdom": "王国", "duchy": "公国",
                   "county": "伯爵领", "hegemon": "皇朝"}
# No "barony" entry: that word is not game text (no simp_chinese key carries it, and the
# castle_holding type has its own name) but a project-invented place-name suffix that appended a
# fort-like word to place names. A barony therefore keeps only the place name, because
# facts._title_tier_word returns early for barony and GENERIC_OFFICE_ZH has its own rank<2 gate.

# Generic OFFICE word fallback table (male, female), deliberately separate from the title-name suffix
# table above: GENERIC_TIER_ZH is a title-name suffix while GENERIC_OFFICE_ZH is how a ruler is
# addressed. Mixing them would append a female office word to a tier suffix in the title name.
GENERIC_OFFICE_ZH = {
    "hegemon": ("皇朝", "皇朝"),
    "empire":  ("皇帝", "女皇"),
    "kingdom": ("国王", "女王"),
    "duchy":   ("公爵", "女公爵"),
    "county":  ("伯爵", "女伯爵"),
    "barony":  ("男爵", "女男爵"),
}


def government_prefix(government):
    """'celestial_government' -> 'celestial'; anything else just loses the _government
    suffix."""
    if not government:
        return ""
    return re.sub(r"_government$", "", government)


def tier_word(table, government, tier):
    """Tier word under a government: the DLC landed-tier words first (culture_titles keys for the
    celestial government), falling back to the generic table.

    The `<government>_salary_rank_*` keys are deliberately ignored because they label subject
    contract salary ranks, not tier levels. Correct administrative tier words come from
    common/flavorization entries with `type = title`, which facts._tier_word_at queries first."""
    prefix = government_prefix(government)
    # DLC "All Under Heaven" landed-tier keys for the celestial government: the five landed
    # tiers use `<tier>_celestial_chinese_vassal`, while hegemon uses
    # `hegemony_celestial_chinese`.
    if prefix == "celestial":
        key = ("hegemony_celestial_chinese" if tier == "hegemon"
               else f"{tier}_celestial_chinese_vassal")
        v = table.get(key)
        if v:
            c = clean_loc_value(v, table)
            if c and not c.startswith("$") and not c.startswith("["):
                return c
    return GENERIC_TIER_ZH.get(tier, "")


# Module-level singletons (cache_lib / facts read these tables directly)

_TABLE = None
_PROVINCE_MAP = None
_DYN_TABLE = None
_REL_TPL = None
_LEVELS = None
_COURT_POSITIONS = None
_COUNCIL_TASKS = None
_BISHOP_TITLES = None
_THEOCRACY_TITLES = None
_SPIRITUAL_FULFILLMENT = None
_COUNCIL_NAMES = None
_TRAIT_NAMES = None
_TRAIT_TRACKS = None
_HOOK_TYPES = None


def currency_levels(cfg=None):
    """Piety/prestige/influence/merit band threshold table singleton."""
    global _LEVELS
    if _LEVELS is None:
        _LEVELS = load_currency_levels(cfg or llm.load_config())
    return _LEVELS


def court_positions(cfg=None):
    """Court position variant table singleton: {"heritage_groups": ..., "positions":
    {type: [variants...]}}."""
    global _COURT_POSITIONS
    if _COURT_POSITIONS is None:
        _COURT_POSITIONS = load_court_positions(cfg or llm.load_config())
    return _COURT_POSITIONS


def council_tasks(cfg=None):
    """Council task -> seat table singleton: {"tasks": {task_type: councillor_seat}}."""
    global _COUNCIL_TASKS
    if _COUNCIL_TASKS is None:
        _COUNCIL_TASKS = load_council_tasks(cfg or llm.load_config())
    return _COUNCIL_TASKS


def bishop_titles(cfg=None):
    """Bishop title ordered arm table singleton: {"arms": [...], "religions": ...,
    "faiths": ...}."""
    global _BISHOP_TITLES
    if _BISHOP_TITLES is None:
        _BISHOP_TITLES = load_bishop_titles(cfg or llm.load_config())
    return _BISHOP_TITLES


def theocracy_titles(cfg=None):
    """Theocracy office title arm table singleton: {"blocks": {block name: [arms...]}, ...}."""
    global _THEOCRACY_TITLES
    if _THEOCRACY_TITLES is None:
        _THEOCRACY_TITLES = load_theocracy_titles(cfg or llm.load_config())
    return _THEOCRACY_TITLES


def spiritual_fulfillment(cfg=None):
    """Spiritual fulfillment band table singleton: {"types": [{key, religions, levels}...]}."""
    global _SPIRITUAL_FULFILLMENT
    if _SPIRITUAL_FULFILLMENT is None:
        _SPIRITUAL_FULFILLMENT = load_spiritual_fulfillment(cfg or llm.load_config())
    return _SPIRITUAL_FULFILLMENT


def council_names(cfg=None):
    """Council seat name chain singleton: {"positions": {seat key: [arms...]}}."""
    global _COUNCIL_NAMES
    if _COUNCIL_NAMES is None:
        _COUNCIL_NAMES = load_council_names(cfg or llm.load_config())
    return _COUNCIL_NAMES


def trait_names(cfg=None):
    """Trait display-name and category table singleton: {"traits": {trait_key: base name loc_key},
    "categories": {trait_key: category}, "level_names": {trait_key: [{any, clauses, key}, ...]}}."""
    global _TRAIT_NAMES
    if _TRAIT_NAMES is None:
        _TRAIT_NAMES = load_trait_names(cfg or llm.load_config())
    return _TRAIT_NAMES


def trait_track_table(cfg=None):
    """Trait XP track table singleton: {"tracks": {trait_key: [{track, levels}, ...]}}."""
    global _TRAIT_TRACKS
    if _TRAIT_TRACKS is None:
        _TRAIT_TRACKS = load_trait_tracks(cfg or llm.load_config())
    return _TRAIT_TRACKS


def hook_type_table(cfg=None):
    """Hook type table singleton: {"hook_types": {type: {strong, perpetual, ...}}}."""
    global _HOOK_TYPES
    if _HOOK_TYPES is None:
        _HOOK_TYPES = load_hook_types(cfg or llm.load_config())
    return _HOOK_TYPES


def table(cfg=None):
    """Localization table singleton {key: Chinese}; loaded or rebuilt on first call."""
    global _TABLE
    if _TABLE is None:
        _TABLE = load_localization_table(cfg or llm.load_config())
    return _TABLE


def relation_templates(cfg=None):
    """Relationship reason template singleton: {reason key: raw template holding the
    character-name tags}. Returns {} for a file predating that key, degrading the feature."""
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
    """Province map singleton {province_id: {"county": ..., "barony": ...}}; loaded or rebuilt
    on first call."""
    global _PROVINCE_MAP
    if _PROVINCE_MAP is None:
        _PROVINCE_MAP = load_province_map(cfg or llm.load_config())
    return _PROVINCE_MAP


def dynasty_table(cfg=None):
    """Dynasty/house definition table singleton: {"dynasties": {key: dynn name}, "houses":
    {house_key: dynn name}, "dynasty_prefixes": ..., "house_prefixes": ...}."""
    global _DYN_TABLE
    if _DYN_TABLE is None:
        _DYN_TABLE = load_dynasty_table(cfg or llm.load_config())
    return _DYN_TABLE


# Startup self-check: verify the source fingerprints, rebuild once when they differ
# The three derived tables (localization / trait names / trait tracks) are not published with the
# repository (see .gitignore), so a new user starts without them, and enabling or updating a mod or
# patching the game changes the fingerprint. watch / continue / scan therefore check them on startup
# and rebuild whatever is missing or stale; doing that lazily would make the build look like a hang.

# Table manifest: display name / file path / schema / key container inside the file /
# loader / fingerprint / module singleton
_SOURCE_TABLES = (
    {"name": "本地化表", "path": _localization_path, "schema": 3, "keys": "table",
     "load": load_localization_table, "fp": "loc", "singleton": "_TABLE"},
    {"name": "特质显示名表", "path": _trait_names_path, "schema": 4, "keys": "traits",
     "load": load_trait_names, "fp": "trait", "singleton": "_TRAIT_NAMES"},
    {"name": "特质轨道表", "path": _trait_tracks_path, "schema": 2, "keys": "tracks",
     "load": load_trait_tracks, "fp": "trait", "singleton": "_TRAIT_TRACKS"},
)

# Self-check result -> human wording (state values come from _fill_report and _stored_state)
_SELFCHECK_TEXT = {
    "ok": "来源指纹一致",
    "rebuilt": "已重建",
    "kept-old": "保留旧表 (重建结果偏小)",
    "no-source": "无可用来源, 沿用旧表",
    "missing": "表缺失",
    "stale": "旧版表 (schema 过期)",
    "outdated": "已过期 (沿用旧表, 请手动建表)",
    "mismatch": "来源指纹不符",
    "error": "表文件不可解析",
}


def state_text(state):
    """Self-check state -> the short display phrase used by pipeline."""
    return _SELFCHECK_TEXT.get(state, state)


def _source_fingerprints(cfg):
    """The two source fingerprints (localization / trait). A fingerprint that cannot be taken
    is left empty instead of raised, because the self-check must not block startup."""
    out = {}
    for key, fn in (("loc", source_fingerprint), ("trait", trait_source_fingerprint)):
        try:
            out[key] = fn(cfg) or {}
        except Exception as e:
            out[key] = {"hash": None, "game": "", "mods": [], "error": str(e)}
    return out


def _stored_state(path, schema, keys_key, source_hash):
    """Read-only comparison of the table's stored fingerprint against the current one -> (state, entry
    count). Rebuilds themselves always go through the load_* functions, where the shrink guard lives."""
    if not os.path.isfile(path):
        return "missing", 0
    try:
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
    except Exception:
        return "error", 0
    keys = len(data.get(keys_key) or {})
    if data.get("schema") != schema:
        return "stale", keys
    if not source_hash or (data.get("fingerprint") or {}).get("hash") != source_hash:
        return "mismatch", keys
    return "ok", keys


def inspect_source_tables(cfg):
    """Read-only self-check (no rebuild): reports the state of the three derived tables for the
    `pipeline.py status` printout."""
    fps = _source_fingerprints(cfg)
    rows = []
    for t in _SOURCE_TABLES:
        path = t["path"](cfg)
        state, keys = _stored_state(path, t["schema"], t["keys"],
                                    (fps.get(t["fp"]) or {}).get("hash"))
        rows.append({"name": t["name"], "path": path, "state": state, "keys": keys})
    return {"fingerprints": fps, "rows": rows,
            "rebuild_needed": [r["name"] for r in rows if r["state"] != "ok"]}


def ensure_source_tables(cfg):
    """Startup self-check: verify the three derived tables' fingerprints and rebuild each missing /
    outdated / mismatched one, loading the result into the module singletons. Returns
    {"fingerprints", "rows", "seconds", "rebuilt", "warnings"}. Called from pipeline.py's watch /
    continue / scan paths; nothing here raises, and an unavailable game dir keeps the old table."""
    fps = _source_fingerprints(cfg)
    loc_fp = fps.get("loc") or {}
    llm.log(f"本地化来源: 游戏 {loc_fp.get('game') or '(未找到)'}, "
            f"启用 Mod {len(loc_fp.get('mods') or [])} 个, "
            f"来源指纹 {str(loc_fp.get('hash'))[:12]}")
    t_all = time.time()
    rows = []
    for t in _SOURCE_TABLES:
        rep, t0 = {}, time.time()
        try:
            data = t["load"](cfg, report=rep)
        except Exception as e:
            llm.log(f"  {t['name']}载入失败: {e}")
            rows.append({"name": t["name"], "state": "error", "keys": 0,
                         "why": str(e), "seconds": time.time() - t0})
            continue
        globals()[t["singleton"]] = data     # load the singleton so later lookups need no reparse
        state = rep.get("state") or "ok"
        rows.append({"name": t["name"], "state": state, "keys": rep.get("keys", 0),
                     "why": rep.get("why") or "", "seconds": time.time() - t0})
        llm.log(f"  自检 {t['name']}: {_SELFCHECK_TEXT.get(state, state)} "
                f"({rep.get('keys', 0)} 条, {time.time() - t0:.1f} 秒)", detail=True)
    secs = time.time() - t_all
    rebuilt = [r for r in rows if r["state"] == "rebuilt"]
    warn = [r for r in rows if r["state"] not in ("ok", "rebuilt")]
    if warn:
        llm.log(f"本地化自检: {len(rows) - len(warn)} 张表就绪; "
                + "、".join(f"{r['name']}{_SELFCHECK_TEXT.get(r['state'], r['state'])}"
                            for r in warn)
                + f" (合计 {secs:.1f} 秒)。")
    elif rebuilt:
        llm.log(f"本地化自检: 本次重建 {len(rebuilt)} 张表 ("
                + "、".join(f"{r['name']} {r['seconds']:.1f} 秒" for r in rebuilt)
                + f"), 其余 {len(rows) - len(rebuilt)} 张来源指纹一致 "
                f"(合计 {secs:.1f} 秒)。")
    else:
        llm.log(f"本地化自检: {len(rows)} 张表来源指纹一致, 无需重建 "
                f"({secs:.1f} 秒)。")
    return {"fingerprints": fps, "rows": rows, "seconds": secs,
            "rebuilt": [r["name"] for r in rebuilt],
            "warnings": [r["name"] for r in warn]}


# Doctrine parameters: the parameters block in common/religion/doctrine_types/*.txt
# A save's religion.faiths[fid].doctrine gives only the list of doctrine keys, never the doctrine's
# functional parameters; the "sacrifice" execution flavour needs human_sacrifice_active, written in a
# parameters block of the doctrine type files. This static doctrine -> parameter-name table is
# therefore built from the game and mod files.

def _doctrine_params_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "doctrine_parameters.json")


def _param_flags(body):
    """A parameter block body -> the set of parameter names. Three syntax shapes occur: `key = yes`,
    a bare flag list with no `=` sign (which _script_items skips), and a sub-block whose name is
    itself the parameter name."""
    flags = set()
    for pk, op, val in _script_items(body):
        if op == "block":
            flags.add(pk)           # the sub-block name is itself a parameter (hostility_levels)
            continue
        if str(val).lower() in ("yes", "true") or str(val).isdigit():
            flags.add(pk)
    # bare flags: strip every `key = value` and `key = { ... }` (one nesting level); the
    # identifiers left over are the flags
    stripped = re.sub(
        r"[A-Za-z_][A-Za-z0-9_.]*\s*(?:>=|<=|!=|\?=|=|<|>)\s*(?:\{[^{}]*\}|[^\s{}]+)",
        " ", body or "")
    for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_.]*", stripped):
        flags.add(m.group(0))
    return flags


def build_doctrine_parameters(cfg):
    """Game + enabled mods' doctrine_types/*.txt and tenet_types/*.txt ->
    {"doctrines": {doctrine: [parameters...]}, "by_parameter": {parameter: [doctrines...]},
     "groups": {doctrine: group}}; a same-named mod doctrine replaces the entry.

    Both directories are scanned because the tenets moved to tenet_types and use a bare flag list
    while doctrines use `special_parameters`; reading only doctrine_types with the `key = value`
    syntax would lose human_sacrifice_active and friends.

    `groups` records each doctrine's `doctrine_group_type`, the slot a doctrine occupies within a
    faith (doctrine_consanguinity holds the near-kin marriage rules), so a doctrine change can be
    written as one slot moving from one value to another."""
    by_doctrine = {}
    groups = {}
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    for root in roots:
        for sub in ("doctrine_types", "tenet_types"):
            d = os.path.join(root, "common", "religion", sub)
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
                    for pkey in ("parameters", "special_parameters"):
                        for pblk in _blocks_of(body, pkey):
                            params |= _param_flags(pblk)
                    if params:
                        by_doctrine[key] = sorted(params)
                    gm = re.search(r"doctrine_group_type\s*=\s*([a-z0-9_]+)", body or "")
                    if gm:
                        groups[key] = gm.group(1)
    by_param = {}
    for doc, params in by_doctrine.items():
        for p in params:
            by_param.setdefault(p, []).append(doc)
    for p in by_param:
        by_param[p] = sorted(by_param[p])
    return {"schema": 3, "doctrines": by_doctrine, "by_parameter": by_param,
            "groups": groups}


def save_doctrine_parameters(cfg, data):
    path = _doctrine_params_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)
    return path


def load_doctrine_parameters(cfg=None, force=False):
    """Load the doctrine parameter dictionary, rebuilding it from the game/mod files when
    missing or forced."""
    cfg = cfg or llm.load_config()
    path = _doctrine_params_path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == 3 and data.get("by_parameter") and data.get("groups"):
                return data
        except Exception:
            pass
    data = build_doctrine_parameters(cfg)
    if data.get("by_parameter"):
        save_doctrine_parameters(cfg, data)
    return data


_DOCTRINE_TABLE = None


def doctrine_table(cfg=None, force=False):
    """The doctrine parameter/group table (module-level singleton; the first call builds and writes
    data/doctrine_parameters.json)."""
    global _DOCTRINE_TABLE
    if _DOCTRINE_TABLE is None or force:
        _DOCTRINE_TABLE = load_doctrine_parameters(cfg or llm.load_config(), force=force)
    return _DOCTRINE_TABLE


def doctrine_group_key(doctrine_key, cfg=None):
    """Group key of a doctrine (`doctrine_consanguinity` for the near-kin marriage rules); '' when
    the game/mod files do not define the doctrine. The group's Chinese name is the localization key
    `<group>_name` (religion_l_simp_chinese.yml)."""
    if not doctrine_key:
        return ""
    try:
        return str((doctrine_table(cfg).get("groups") or {}).get(str(doctrine_key)) or "")
    except Exception:
        return ""


# Built-in fallback so human sacrifice can still be detected when the game files are
# unreadable (three parameters blocks carry human_sacrifice_active)
_DOCTRINE_PARAM_FALLBACK = {
    "human_sacrifice_active": ("tenet_human_sacrifice", "tenet_gruesome_festivals",
                               "tenet_sacrificial_ceremonies"),
}


def doctrines_granting(param, cfg=None):
    """The doctrine keys that grant one doctrine parameter (falls back to the built-in table
    when the loaded table is missing or empty)."""
    try:
        table = load_doctrine_parameters(cfg)
        keys = (table.get("by_parameter") or {}).get(param) or []
    except Exception:
        keys = []
    return set(keys) or set(_DOCTRINE_PARAM_FALLBACK.get(param, ()))


# Lookup helpers

_MISS = {}


def loc(table, key, default=""):
    """Look up Chinese by key (format codes stripped, $ref$ resolved); `default` when missing. A miss
    is counted in an in-process table that miss_report / write_miss_report export."""
    if not key:
        return default
    v = table.get(str(key))
    if v is None:
        _MISS[str(key)] = _MISS.get(str(key), 0) + 1
        return default
    return clean_loc_value(v, table)


def miss_report(top=40):
    """Miss counts by key, highest first, limited to `top` entries; used for localization
    coverage audits."""
    items = sorted(_MISS.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[:top]


def write_miss_report(cfg=None, path=None, top=200):
    """Append the miss counts to logs/loc_miss.log (only when there is something to write).
    Returns the number of entries written."""
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


# Command line

def _mod_key_counts(root, lang="simp_chinese", fallback_lang="english"):
    """Number of localization keys one mod root contributes (counted per language directory)."""
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
        # localization override audit for the enabled mods; run this first after ticking a mod
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
        tr = build_trait_tracks(cfg)
        p2 = save_trait_tracks(cfg, tr)
        t = data.get("traits") or {}
        cats = data.get("categories") or {}
        levels = data.get("level_names") or {}
        tracks = tr.get("tracks") or {}
        print(f"特质显示名表已重建: {p} ({len(t)} 条, 类别 {len(cats)} 条, "
              f"按 XP 换名 {len(levels)} 条)")
        print(f"特质轨道表已重建: {p2} ({len(tracks)} 个特质, "
              f"{sum(len(v) for v in tracks.values())} 条轨道)")
        table = load_localization_table(cfg)
        for k in ("lifestyle_reveler", "lifestyle_traveler", "gallowsbait",
                  "lifestyle_physician", "hunchback", "pregnant", "lustful"):
            lk = t.get(k, "")
            tt = tracks.get(k) or []
            track_txt = "、".join(
                f"{loc(table, 'trait_track_' + r['track']) or r['track']}"
                f"{r['levels']}" for r in tt)
            print(f"  {k} [{cats.get(k) or '无类别'}] → "
                  f"{loc(table, lk or f'trait_{k}')!r}"
                  + (f"  轨道: {track_txt}" if track_txt else ""))
    elif cmd == "tracks":
        tr = build_trait_tracks(cfg)
        p = save_trait_tracks(cfg, tr)
        tracks = tr.get("tracks") or {}
        table = load_localization_table(cfg)
        print(f"特质轨道表已重建: {p} ({len(tracks)} 个特质, "
              f"{sum(len(v) for v in tracks.values())} 条轨道)")
        for k in ("gallowsbait", "lifestyle_hunter", "tourney_participant",
                  "lifestyle_traveler", "logistician", "infirm"):
            rows = tracks.get(k)
            if not rows:
                print(f"  {k} → （无轨道）")
                continue
            for r in rows:
                nm = loc(table, "trait_track_" + r["track"]) or r["track"]
                print(f"  {k} · {r['track']} = {nm}  档位 {r['levels']}")
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
    elif cmd == "shorts":
        s = build_short_titles(cfg)
        p = save_short_titles(cfg, s)
        dist = {}
        for k in s:
            dist[k[:2]] = dist.get(k[:2], 0) + 1
        print(f"简称头衔表已重建: {p} ({len(s)} 个)")
        print("  层级分布: " + "、".join(f"{k}{dist.get(k, 0)}"
                                        for k in _TITLE_KEY_PREFIXES))
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
