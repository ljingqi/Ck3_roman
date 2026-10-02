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
  - data/trait_names.json    : {traits: {trait_key: 基础名键}, categories: {trait_key: 类别},
                                level_names: {trait_key: [按 XP 换名的条件与键]}} (v31/v32)
  - data/trait_tracks.json   : {tracks: {trait_key: [{track, levels}, …]}} (v32)
  - data/hook_types.json     : {hook_types: {类型键: {strong, perpetual, expiration_days}}} (v31)

用法:
  python localization.py build        # 重建本地化表
  python localization.py mods         # 列启用 Mod 的本地化覆盖与来源指纹 (v29)
  python localization.py province     # 重建省份映射
  python localization.py dynasties    # 重建宗族/家族定义表 (v14)
  python localization.py shorts       # 重建「简称」头衔表 (v52: definite_form=yes)
  python localization.py traits       # 重建特质显示名/类别表 + 轨道表 (v29/v31/v32)
  python localization.py tracks       # 只重建特质 XP 轨道表 (v32)
  python localization.py hooks        # 重建牵制类型表 (v31)
  python localization.py check        # 抽查关键键 (Daria/岭西/层级词/桂州)
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

# ---------------------------------------------------------------------------
# CK3 本地化文本清理
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"#[A-Za-z0-9_\-+]+")     # #V / #bold / #low ... 开标签
_CLOSE_RE = re.compile(r"#!")                  # 关标签
_ICON_RE = re.compile(r"@[A-Za-z0-9_]+!")
_DYN_RE = re.compile(r"\[[^\]]*\]")            # [concept|E] / [GetX|V0]
_REF_RE = re.compile(r"\$([A-Za-z0-9_]+)\$")

# v16: 关系原因模板保留的角色名标签 (rival_murderer 等 reason 键) —
# 其余动态引用照旧剥除, 这些标签供 facts._sub_relation_loc 替换名字。
# v56 (问题3 续, 用户拍板「一并修」):
#   ① `GetShortUINamePossessive` 此前**没认** `|U` 后缀 —— `[X.GetShortUIName
#      Possessive|U]` 整段被剥, 句子的主语/宾语丢失 (friend_pedagogy 渲染成
#      「对…细致教育和看护种下了持久的友谊种子」)。现改为「访问器 + 任意 |变体」,
#      并认 `GetHerHis` (旧式, 无 Your)。
#   ② 新增 `PROVINCE.GetName` —— 60 个 reason 键用 (72 处), 此前剥掉后模板成病句
#      (「…在的酒馆中共享了一顿美餐…」); facts 侧早有「当地」兜底, 却因标签已被
#      剥掉而永远走不到。现保留, 由 facts 解析成**真实地名**。
# v63 (第五轮, 2026-09-24 用户报告「仇敌结仇原因没传过去」):
#   ③ 新增 `GetDynastyHouseName(?:NoTooltip)?` —— 78 处 (37+37+4)。旧表把它剥掉后,
#      `rival_house_feud_start_of_feud` 的中文模板 (「[house]家族和[house]家族爆发
#      世仇后，A和B成为了仇敌。」) 渲染成「**家族和家族**爆发世仇后…」——
#      因由整句变成无信息量的病句, 模型遂自造「因海关/关税结仇」。现保留, 由
#      facts 解析成真实家族名 (埃德伯案 → 「威塞克斯家族和菲利普家族」)。
#      (同类未认标签还有 `GetName`/`GetFirstName`/`GetPossessive`, 各 1–2 处, 不在
#       本次报告范围内, 暂维持旧行为。)
_KEEP_DYN_RE = re.compile(
    r"\[(?:(?:TARGET_CHARACTER_2|TARGET_CHARACTER|CHARACTER)\."
    r"(?:GetShortUIName(?:Possessive)?(?:NoTooltip)?|GetHerHis(?:Your)?"
    r"|GetDynastyHouseName(?:NoTooltip)?)"
    r"|PROVINCE\.GetName)"
    r"(?:\|[A-Za-z0-9_]+)?\]")


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
    """YML 值 → 干净中文 (概念引用换算 + 去格式码 + 解 $ref$ + 去空白)。"""
    v = strip_ck3_format(_sub_concepts(raw or "", table))
    if "$" in v:
        v = resolve_refs(v, table)
    return v.strip()


#: 概念引用 `[concept|E]` (小写开头的键名; 角色/地名访问器是大写开头, 不受影响)
_CONCEPT_REF_RE = re.compile(r"\[([a-z][a-z0-9_]*)(?:\|[A-Za-z0-9_]*)?\]")
#: 带内联中文名的概念引用 `[Concept('great_project','集体礼仪皈依')|E]` —— 直接用内联名
_CONCEPT_INLINE_RE = re.compile(
    r"\[Concept\('([A-Za-z0-9_]+)','([^']*)'\)(?:\|[A-Za-z0-9_]*)?\]")


def _sub_concepts(text, table):
    """`[concept|E]` → 该概念的**中文名** (`game_concept_<key>`)。

    v86: 1.20 的教会/礼仪文案大量用概念引用 (如
    `catalyst_the_christian_church_clerical_region_created_desc` =
    「创建新[clerical_region|E]」)。旧稿在建表时把整段剥掉 (见
    `strip_ck3_format` 的 `_DYN_RE`), 于是渲染出「创建新。」这类残句。
    取不到概念名时保持原样, 随后仍由 `strip_ck3_format` 剥除 (与旧行为一致)。"""
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
    # v58 (§0.1): 注册表读不到 (受限/子进程环境实测 `winreg.OpenKey` 抛
    # FileNotFoundError) 时退到常见安装路径, 否则 game_dir() 为空 →
    # build_localization_table 只读得到 Mod 本地化 (实测 94,734 键 vs 完整
    # 382,330 键), 中文人名/头衔整片退化成英文或裸键。libraryfolders.vdf 里
    # 的其它库路径同样扫一遍。
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
    # v44 (问题6): **语言在外层、根在内层** —— 旧顺序 (根外层/语言内层) 让后加载
    # Mod 的 english 覆盖本体的 simp_chinese (实测 Mod longju_exent 的
    # `Mathilde:0 "Matilda"` / `Marie:0 "Marry"` 把游戏本体的
    # `Mathilde: "玛蒂尔德"` / `Marie: "玛丽"` 顶掉, 传记里出现 `Matilda·萨伏依`)。
    # 现在任何根的中文都压过任何根的英文; 同语言内仍按根序 (Mod 覆盖本体)。
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
        # v44 (问题6): schema 3 = 「语言外层、根内层」的合并序 —— 旧表 (schema<=2)
        # 含 Mod 英文覆盖中文的脏值, 读到即视为过期, 自动重建一次。
        json.dump({"schema": 3, "lang": "simp_chinese", "keys": len(table),
                   "table": table,
                   "relation_templates": raw_templates or {},
                   # v29: 建表时的来源指纹 (启用 Mod 清单 + 本地化签名)
                   "fingerprint": fingerprint or {}},
                  fp, ensure_ascii=False)
    return path


# ---------------------------------------------------------------------------
# 本地化**修正表** (v73): 游戏原文对「女性同一层级」只写模板引用 ($同一键$) 的键
# ---------------------------------------------------------------------------
# 用户 2026-09-27 报: 「霸权级统治者的称号只有皇帝一种, 分不清男女, 女性改为女皇,
# 如元女皇」。根因在游戏原文 —— `game/localization/simp_chinese/culture/
# culture_titles_l_simp_chinese.yml:1228-1237` 把女性键全部写成对男性键的**引用**:
#     hegemon_celestial_male_chinese:             "皇帝"
#     hegemon_celestial_female_chinese:           "$hegemon_celestial_male_chinese$"
#     hegemon_female_chinese:                     "$hegemon_celestial_male_chinese$"
#     emperor_female_chinese_independent:         "$hegemon_celestial_male_chinese$"
#     emperor_celestial_female_chinese_independent: "$hegemon_celestial_male_chinese$"
# 于是解析后女键与男键同形 (`L.loc` 返回的串以 `$` 开头, 上游一律判为未解析),
# 女性霸主的称谓只能落回「皇帝」甚至无条件兜底键 `hegemon` = 「女霸主」(见
# `docs/研究_v47_统治者头衔动态.md` 与 v69 的霸主→皇帝收口)。
# 本表在**载入之后**覆盖这些键, 与 v30 的 `GENERIC_OFFICE_ZH` (empire 已是
# 「皇帝/女皇」两分) 同一口径; 键与值都照游戏词法, 不新造词。
LOC_OVERRIDES = {
    "hegemon_celestial_female_chinese": "女皇",
    "hegemon_female_chinese": "女皇",
    "emperor_female_chinese_independent": "女皇",
    "emperor_celestial_female_chinese_independent": "女皇",
}


def _fill_report(report, state, keys, why=""):
    """把一次载入的结论写进调用方传入的 report (v85 启动自检用)。

    report 为 None 时静默 —— 惰性载入路径 (等到查名字才建表) 无需向外汇报。"""
    if report is None:
        return
    report.clear()
    report.update({"state": state, "keys": int(keys), "why": why})


def load_localization_table(cfg, force=False, report=None):
    """载入本地化表; 缺失、强制、或**来源指纹变化**时重建。返回 {key: 中文}。

    v29: 指纹 = 游戏目录 + 启用 Mod 清单 + 本地化文件数/字节数/mtime。用户启用
    新 Mod 或 Mod 更新后, 本函数自动重建并记日志; 新版表为空 (游戏目录不可用)
    时保留旧表, 不清空已有键。
    v85: 新增 report 出参 —— 启动自检 (ensure_source_tables) 据此区分
    「指纹一致 / 已重建 / 保留旧表」, state ∈ ok / rebuilt / kept-old / no-source。"""
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
            # v44 (问题6): schema<=2 的表按「英文先、中文后」的旧序合并, 含 Mod
            # 英文顶掉本体中文的脏值 (Mathilde → Matilda), 一律不采用, 重建。
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
            cached.update(LOC_OVERRIDES)     # v73: 修正表对**旧表**同样生效
            _fill_report(report, "ok", len(cached), "来源指纹一致")
            return cached
        why = "旧版表无来源指纹" if not old_fp else "启用 Mod / 游戏本地化已变化"
        # v86 (用户 2026-09-30 拍板「启动完全不检查, 只管读表」): 指纹不符时**不再
        # 自动重建**, 只用现有表并提示手动建表 —— 游戏升级/Mod 变动后每次启动都
        # 白跑一遍建表 (还可能被退表保护拒绝落盘) 正是旧口径的痛点。
        if schema_ok:
            llm.log(f"本地化表已过期 ({why}) —— 本轮沿用现有表; "
                    f"要更新请运行 重建对照表.bat (或 python pipeline.py build-tables)。")
            cached.update(LOC_OVERRIDES)
            _fill_report(report, "outdated", len(cached), why)
            return cached
    table, raw_templates = build_localization_table(cfg)
    if not table:
        # 游戏目录不可用 (换机 / 未配置): 保留旧表, 优于空表
        llm.log("本地化重建未取到任何键 (游戏目录不可用?), 沿用既有表。")
        cached.update(LOC_OVERRIDES)         # v73: 修正表对**旧表**同样生效
        _fill_report(report, "no-source", len(cached), "游戏目录不可用, 沿用既有表")
        return cached
    # v58 (§0.1): **退表保护** —— 只在游戏目录不可用时会重建出「只剩 Mod 键」的
    # 小表 (实测 94,734 vs 382,330)。旧稿只挡「空表」, 于是这类退化表会覆盖好的表,
    # 中文人名/头衔/家族前缀整片失效。新表键数不足旧表六成时拒绝落盘。
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
    table.update(LOC_OVERRIDES)              # v73: 女性层级词修正 (见 LOC_OVERRIDES)
    _fill_report(report, "rebuilt", len(table), why)
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


# ---------------------------------------------------------------------------
# 「简称」头衔表 (v52, 问题3): landed_titles 的 definite_form = yes
# ---------------------------------------------------------------------------
# 游戏口径: 头衔界面的「简称」开关 (`TITLE_CUSTOMIZATION_DEFINITE_FORM: "简称"`,
# 英文 "Short Name", 日文「短縮形」) 对应 `common/landed_titles/*.txt` 里的
# `definite_form = yes` —— 这类头衔的定位名**自带国号/层级词** (e_hre=神圣罗马帝国、
# e_byzantium=拜占庭帝国、k_papal_state=教宗国、h_dar_al_islam=达尔·伊斯兰),
# 游戏拼名时**不再**追加 `$TIER$`; 未标记者只有地名 (k_aquitaine=阿基坦,
# k_france=法兰西), 由 `TITLE_TIERED_NAME = "$NAME$$TIER|U$"` 拼出「阿基坦王国」。
# 本表供「公主/王子称号」前缀取词判定用 (v52: 前缀一律省层级词, 简称头衔保持本名)。

def _short_titles_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "short_titles.json")


_TITLE_KEY_PREFIXES = ("h_", "e_", "k_", "d_", "c_", "b_")


def _parse_landed_titles_short(path, out):
    """收一份 landed_titles.txt 里 `definite_form = yes` 的头衔键 (游戏+Mod)。"""
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
    """游戏 + Mod 的 landed_titles → definite_form 头衔键集合 (v52)。"""
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
    """简称头衔键集合 (模块级单例; 首次调用建表并落 data/short_titles.json)。"""
    global _SHORT_TITLES
    if _SHORT_TITLES is None:
        _SHORT_TITLES = load_short_titles(cfg or llm.load_config())
    return _SHORT_TITLES


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


def _parse_dynasty_defs(path, out, prefixes=None):
    """解析一份 dynasties/dynasty_houses txt: key = { name = "dynn_X" } → out[key]。
    忽略嵌套花括号块 (脚本块不在这些文件里), 只取顶层 key。

    v58 (问题4): 同时抓 `prefix = "dynnp_X"`（贵族地面前缀：意大利 di／法兰西 de／
    德意志 von…）→ prefixes[key]。键形放宽两处：
      · 允许**数字键**（游戏本体宗族定义按宗族 id 命名：`101556 = { name = "dynn_Lucca" }`）；
      · 允许键内出现 `-`／`.`（家族键 `house_visconti-somma`）。
    旧正则要求键以字母开头，把这两类定义整条丢掉（本档「卡诺萨为吉贝尔蒂宗族的分支」
    即由此而来，游戏口径是「卢卡」）。"""
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
    """游戏 + Mod 的 common/dynasties 与 common/dynasty_houses →
    {"dynasties": {key: dynn名}, "houses": {house_key: dynn名},
     "dynasty_prefixes": {key: dynnp名}, "house_prefixes": {house_key: dynnp名}}
    (v58 问题4: 后两张是前缀表)。Mod 覆盖游戏。"""
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
        # v58 (问题4): schema 2 = 增 dynasty_prefixes / house_prefixes 两张前缀表
        json.dump({"schema": 2,
                   "dynasties": table.get("dynasties") or {},
                   "houses": table.get("houses") or {},
                   "dynasty_prefixes": table.get("dynasty_prefixes") or {},
                   "house_prefixes": table.get("house_prefixes") or {}},
                  fp, ensure_ascii=False)
    return path


def load_dynasty_table(cfg, force=False):
    """载入宗族/家族定义表; 缺失或强制时重建。
    返回 {"dynasties": …, "houses": …, "dynasty_prefixes": …, "house_prefixes": …}。
    v58: schema<2 (无前缀表) 视为过期 → 重建一次 (重建 <1s)。"""
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


def _cond_block(items, groups, op="all", religions=None, split_inline=False):
    """触发项 → 条件树: {"op": all|any|none, "children": [叶子或子树]} (保序)。

    空块返回 {} (调用方按「无条件 = 恒真」处理); 无法识别的叶子记 {"unknown": key},
    求值恒不命中 → 该变体作废, 退化为职位类型键的默认名。
    `split_inline=True` 时先把「一行多个条件项」摊开 (v80 点5 的新解析器用)。"""
    children = []

    def _items(body):
        return _script_items(_split_inline_items(body) if split_inline else body)

    for key, kop, val in items:
        k = (key or "").lower()
        # ---- v80 (点5): GetActualBishopTitle / 议会席位 name 链所需的条件叶子 ----
        # 必须排在通用 block 分支之前 (religion = { … } 也是 block)
        if key == "religion" and kop == "block":
            # religion = { is_in_family = rf_pagan } → 宗教族
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
        # ---- v86 (1.20): 新条件叶子 ----
        # `rite = rite:roman_rite` / `rite_has_doctrine = doctrine_x`: 1.20 的
        # 议会席位名链新增 (council_positions/00_council_positions.txt:694/705/773),
        # 靠 scope 的 rite / rite_doctrines 求值 (facts 侧按角色礼仪填)。
        if key == "rite":
            if kop == "block":
                # v87: `rite = { rite_has_doctrine = X }` 块形 (GetActualDukeTheocracyTitle
                # 的 NOR 臂用; 旧稿只认标量 `rite = rite:roman_rite`, 块形被判 unknown)
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
        # ---- v87 (问题1): `[CHARACTER.Custom('GetActualDukeTheocracyTitle')]` 一族
        # (基督教神权官称的委托标记; culture_titles_l_simp_chinese.yml:253/238) 的
        # trigger 用到的新叶子 —— is_female / faith / has_title / any_held_title
        # (tier + has_clerical_region) / has_clerical_region。
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
        # v89 (问题2-B): `tier = tier_duchy` (在 any_held_title 内) 与
        # `is_landless_type_title` 两个叶子 —— 旧解析器把前者记成 `unknown`(恒不命中),
        # 于是 `duke_theocracy_*_clerical_region*` 一族 (「总主教」/「都主教」/「牧首」)
        # **永远不可能命中** (实测 logs/v89_probe_fix.txt)。
        if key == "tier":
            _t = _TIER_NUM.get(str(val).replace("tier_", "").lower())
            if _t is None:
                children.append({"unknown": key})
            else:
                # 两个叶子必须分开记: cond_match 命中首个键即返回 (同 highest_held_title_tier)
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
        # `government_allows` 在 1.20 改名为 `government_has_mechanic`
        # (council_positions 10 条臂); 两者同义, 都归到 gov_flag 叶子。
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
    """`religion = religion:buddhism_religion` → 'buddhism_religion' (取不到 '')。"""
    s = str(val or "").strip()
    if s.startswith("religion:"):
        return s[len("religion:"):]
    return ""


def _faith_religion_key(val, religions=None):
    """`faith.religion = faith:theravada.religion` → 该信仰所在宗教键 (取不到 '')。

    信仰→宗教的对应表由 `_religion_maps` 从 `common/religion/religion_types/*.txt`
    解析而来 (`{"faiths": {信仰键: 宗教键}}`); 表缺席时返回 ''(该叶恒不命中)。"""
    s = str(val or "").strip()
    tail = ".religion"
    if s.startswith("faith:") and s.endswith(tail):
        fk = s[len("faith:"):-len(tail)]
        return ((religions or {}).get("faiths") or {}).get(fk) or ""
    return ""


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
        # v89 (问题2-B): 原来写 `not in (None, "")` —— 于是 False/0/[] 这些"存在但为假"
        # 的值也算"存在", `exists = clerical_elector_title` 遂对所有公国级神权统治者
        # 判真 ⇒ 一律命中 cardinal 臂 (「枢机」)。改为真值语义 (与游戏 exists 一致)。
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
        # v80 (点5): `has_cultural_pillar` 可指任何文化桩 (heritage_/language_/ethos_/
        # tradition_) —— scope 带 `pillars` 集合时按集合判; 不带时维持旧的单值语义。
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
    # ---- v80 (点5): 主教称谓 / 议会席位 name 链的条件叶子 ----
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
    # ---- v87 (问题1): 自定义本地化臂的新叶子 ----
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
        # any_held_title 语义: 持有头衔中**任一**满足子条件即真
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
# 主教称谓臂表 (v80 点5): common/customizable_localization 的 GetActualBishopTitle
# ---------------------------------------------------------------------------
# 游戏把「宫廷司祭」的教会词交给 GetActualBishopTitle
# (`00_divinity_custom_loc.txt:659`), 那是一串**保序**的
# `text = { trigger = … localization_key = … }` 臂, 先命中先取 —— 日本佛教臂
# (culture 带 language_japonic + religion = buddhism_religion →
# `councillor_court_chaplain_japanese_buddhism_religion` = 和尚, `:1126-1133`)
# 排在通用佛教/印度系臂 (`…_buddhism_religion_empire` = 摩诃罗阇上师, `:1236-1247`)
# 之前。旧稿 `facts.chaplain_title` 自己用键名正则复刻取词 (`_CHAPLAIN_WORD_RE`),
# 只按「宗教组 × 层级」索引, 永远取不到**无层级后缀**的日/越/汉/藏/高丽键, 于是
# 田所定治档输出「宫廷司祭日本摩诃罗阇上师」(游戏作「日本和尚」)。
# 此处改为**解析游戏数据**, 与 `build_court_positions` 同法。


def _data_roots(cfg):
    """取表用的根目录序列 (本体在前, 启用 Mod 在后 —— 后者覆盖前者)。"""
    roots = []
    g = game_dir(cfg)
    if g:
        roots.append(g)
    roots += enabled_mod_dirs(cfg)
    return roots


def _strip_comments(txt):
    """删去 CK3 脚本里的**整行注释**。

    块扫描器只看花括号配对, 于是被注释掉的 `text = { … }` 臂也会被当成真臂 ——
    `GetActualBishopTitle` 里恰有一个被注释的 `ruler_title_name` 臂
    (`00_divinity_custom_loc.txt:671-676`), 它一旦进表就以**空 trigger** 排在
    第二位、恒命中 (实测把日本佛教档压成兜底词)。"""
    out = []
    for ln in (txt or "").split("\n"):
        if ln.lstrip().startswith("#"):
            continue
        out.append(ln)
    return "\n".join(out)


# 行内「键 运算符」的起头 (用于把一行多个条件项摊成一行一项)
_INLINE_ITEM_RE = re.compile(
    r"(?<=\S)\s+(?=[A-Za-z_][A-Za-z0-9_.:]*(?:\s*(?:>=|<=|!=|\?=|=|>|<)))")


def _split_inline_items(txt):
    """把「一行多个条件项」摊成一行一项。

    CK3 脚本常把两三个条件写在同一行 (如 `highest_held_title_tier >= tier_empire
    faith.religion = faith:ashari.religion`); 项目既有的 `_script_items` 会把后半个
    条件吞进前一项的值里, 层级条件于是变成 `unknown` 而恒不命中 (实测伊斯兰诸臂
    全废、退到 theocrat 兜底词「主教」)。只在新解析器 (主教臂表 / 席位名链) 里启用,
    以免改动既有法院职位表的既定行为。"""
    return _INLINE_ITEM_RE.sub("\n", txt or "")


def _religion_maps(cfg, roots=None):
    """`common/religion/religion_types/*.txt` + `common/religion/faith_types/*.txt`
    → {"religions": {宗教键: 宗教族}, "faiths": {信仰键: 宗教键}}。

    宗教族用于 `is_in_family = rf_pagan` 这类条件; 信仰表用于把
    `faith.religion = faith:theravada.religion` 折成所在宗教键。

    v86 (1.20): 信仰定义从 religion_types 里**拆到了新的 faith_types/** 目录 ——
    1.20 的 religion_types 里 `faiths = {` 出现 0 次, 而 faith_types 的
    `faith_details` 有 103 处。旧稿只扫 religion_types ⇒ 信仰→宗教映射塌成 0 条
    (1.19 是 244 条), 主教称谓臂里 `faith.religion` 一类叶子全部失配
    (实测含 religion 叶 66→10、unknown 叶 45→116)。现两目录都扫,
    同一 root 内 faith_types 后扫 (Mod 仍整体后扫, 保持「Mod 覆盖本体」口径)。"""
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
                        # faith_types: 每个块是一件信仰, `faith_type = <键>` 是它
                        # 在旧库里的键 (如 christian_faith), `religion = <id/键>`
                        # 指向所属宗教 —— religion 是**块**时取其 tag/religion_type。
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
    """`GetActualBishopTitle` 保序臂表 → {"arms": [{"loc_key", "when"}…],
    "religions": {宗教键: 族}, "faiths": {信仰键: 宗教键}} (保序, Mod 同名块覆盖)。

    v87: schema 2 → 3 —— 条件树解析器新增 v87 的叶子 (`is_female`/`faith`/
    `has_title`/`any_held_title`/块形 `rite`), 旧表须重建方与新解析器一致。"""
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
                arms = []          # Mod 同名定义整体覆盖 (与法院职位同口径)
                for blk in _blocks_of(body, "text"):
                    lk = re.search(r"localization_key\s*=\s*([A-Za-z0-9_]+)", blk)
                    tr = _blocks_of(blk, "trigger")
                    cond = _cond_block(_script_items(_split_inline_items(tr[0])),
                                       groups, religions=rel, split_inline=True) \
                        if tr else {}
                    arms.append({"loc_key": lk.group(1) if lk else "",
                                 "when": cond})
    # v89 (问题2-B): schema 3 → 4 —— 条件树解析器补 `tier = tier_duchy` 与
    # `is_landless_type_title` 两个叶子, 且 `exists` 改真值语义; 旧表里这两个叶子是
    # `unknown` (恒不命中) 且 cardinal 臂恒真, 必须重建。
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
    """载入主教称谓臂表; 缺失或强制时重建 (与本地化表同源的静态表)。"""
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
    """保序臂表首个命中臂的本地化键 (无命中返回 '')。"""
    return pick_arm((table or {}).get("arms") or [], scope)


def pick_arm(arms, scope):
    """保序臂表首个命中臂的本地化键 (无命中返回 ''); 空条件 = 恒真 (游戏 fallback 臂)。"""
    for a in arms or []:
        if cond_match(a.get("when") or {}, scope or {}):
            return a.get("loc_key") or ""
    return ""


# ---------------------------------------------------------------------------
# 灵性满足分档表 (v89 问题6)
# ---------------------------------------------------------------------------
# 游戏本体自带**官方等级名**, 分两套 (按 religion 分派):
#   game\common\spiritual_fulfillment\00_spiritual_fulfillment_types.txt
#     christian_fulfillment = { religions = { christianity_religion } level = { threshold… } … }  # 7 档
#     default_fulfillment   = { level = { threshold… } … }                                        # 5 档 (无 religions = 兜底)
# 等级名 = `<type 键>_level_<i>` (i 从 0 起, 与 level 出现次序一致; 见同目录
# `_spiritual_fulfillment_type.info:8`), 中文原文:
#   christian_fulfillment_level_0..6 = 诅咒之人/离弃之人/忧心之人/悔悟之人/得赦之人/宁定之人/蒙恩之人
#   default_fulfillment_level_0..4   = 茫然无措/上下求索/循规蹈矩/虔诚笃信/从心所欲
# (game\localization\simp_chinese\modifiers\pam_modifiers_l_simp_chinese.yml:2-13)
# 值域 -100…100 (`common\defines\00_defines.txt:889-890`); 取档 = 最后一个
# `threshold ≤ 值` 的 level 下标。


def _spiritual_fulfillment_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "spiritual_fulfillment.json")


def build_spiritual_fulfillment(cfg):
    """→ {"schema": 1, "types": [{"key", "religions": [...], "levels": [{"threshold": …}]}…],
    "religions"/"faiths": 宗教信仰映射 (与主教臂表同源, 供调用方选型)。"""
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
    """载入灵性满足分档表; 缺失/版本不符时重建 (静态表, 与本地化表同源)。"""
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
    """按宗教键取分档类型: 命中 `religions` 者优先; 否则取无 `religions` 的兜底类型。"""
    types = (table or {}).get("types") or []
    for t in types:
        if religion_key and religion_key in (t.get("religions") or []):
            return t
    for t in types:
        if not (t.get("religions") or []):
            return t
    return types[0] if types else {}


def sf_level_index(levels, value):
    """最后一个 `threshold ≤ value` 的下标 (低于首档时给 0)。"""
    idx = 0
    for i, lv in enumerate(levels or []):
        th = (lv or {}).get("threshold")
        if isinstance(th, (int, float)) and value is not None and value >= th:
            idx = i
    return idx


# ---------------------------------------------------------------------------
# 神权官称的自定义本地化臂表 (v87 问题1)
# ---------------------------------------------------------------------------
# 游戏把**基督教神权统治者**的官称整个委托给自定义本地化:
#   duke_theocracy_male_christianity_religion  = "[CHARACTER.Custom('GetActualDukeTheocracyTitle')]"
#   count_theocracy_male_christianity_religion = "[CHARACTER.Custom('GetActualCountTheocracyTitle')]"
#   duke_theocracy_male_*_clerical_region*     = "[CHARACTER.Custom('GetActualBishopTitle')]"
# (culture_titles_l_simp_chinese.yml:238/253; 定义在 common/customizable_localization/
#  00_divinity_custom_loc.txt:2243 / :2294 / :659)
# `localization.loc` 会把 `[...]` 整段剥空 ⇒ 旧稿取不到词, 一路落到通用「公爵」。
# 本表把前两个块解析成保序臂 (`GetActualBishopTitle` 早已由 `bishop_titles` 承担),
# 求值由 `Facts._theocracy_scope` 提供的域 (信仰/礼仪/持有头衔/枢机身份) 完成。

_THEOCRACY_CUSTOM_BLOCKS = ("GetActualDukeTheocracyTitle",
                            "GetActualCountTheocracyTitle")


def _custom_loc_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "theocracy_titles.json")


def build_theocracy_titles(cfg):
    """两个神权官称块 → {"blocks": {块名: [臂…]}, "religions"/"faiths": 映射}。"""
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
                arms = []          # Mod 同名定义整体覆盖 (与主教臂表同口径)
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
    # v89 (问题2-B): schema 1 → 2 —— 同 bishop_titles, 条件树解析器补两个叶子 +
    # `exists` 真值语义, 旧表须重建。
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
    """载入神权官称臂表; 缺失或强制时重建 (与主教臂表同源)。"""
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
    """该块保序臂首个命中臂的本地化键 (无表/无命中返回 '')。"""
    return pick_arm(((table or {}).get("blocks") or {}).get(key) or [], scope)


# ---------------------------------------------------------------------------
# 议会席位名链 (v80 点5): common/council_positions 的 `name = { first_valid = … }`
# ---------------------------------------------------------------------------
# 属世神权信仰 (`doctrine_theocracy_temporal`) 与异教族 (`rf_pagan`) 下, 游戏把
# 宫廷司祭席位的**名字**整个交给 `actual_bishop_title`
# (`00_council_positions.txt:649` 的 name 链, 命中臂 `:703-713`), 故正确串是
# 「日本和尚忠盛」, 而不是「宫廷司祭」再叠教会词。


def _council_names_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "council_names.json")


def _name_arms(block, groups, religions, extra=None):
    """`name` 链 → [{"desc": 键或 'actual_bishop_title', "when": 条件树}…] (保序)。

    `desc` 既可以是本地化键, 也可以是 `desc = { first_valid = { … } }` 这样的
    嵌套餐 (与外壳的 trigger 取 AND)。"""
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
    """各议会席位的 `name` 链 → {"positions": {席位键: [臂…]}} (本体 + 启用 Mod)。"""
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
                    positions[key] = arms     # Mod 同名定义整体覆盖
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
    """席位名链首个命中臂的 desc (无表/无命中返回 ''); `actual_bishop_title`
    是游戏侧的**委托标记** —— 调用方据此改用 `Facts.chaplain_title`。"""
    for a in ((table or {}).get("positions") or {}).get(position) or []:
        if cond_match(a.get("when") or {}, scope or {}):
            return a.get("desc") or ""
    return ""


# ---------------------------------------------------------------------------
# 特质显示名键表 (v29): common/traits/*.txt 的 name 块 → desc 键
# ---------------------------------------------------------------------------
# 部分特质 (如旅行者 lifestyle_traveler) 的显示名不走 trait_<key>, 而由特质定义里的
# name = { first_valid = { … desc = trait_traveler_1 } } 指定; Mod 特质更常见。
# 没有这张表时该特质整条被丢弃 (信息丢失, 虽不外泄键)。

def _trait_names_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "trait_names.json")


def _body_at(text, i):
    """i 指向 '{' → 返回配平块体 (不含外层花括号); 未闭合返回余下全文。"""
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
    """删去所有 `<key> = { … }` 块 (留着其余文本), 供取区块里的裸 desc 用。"""
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
    """trigger 块 → {"any": bool, "clauses": [{track, op, value}, …]}; 无 XP 条件 → None。

    只认 `has_trait_xp = { track=… value <op> N }`; `OR = { … }` 内的条款按「任一」求值
    (实测 lifestyle_traveler 的 travel<50 / danger<50 为 AND、travel=100 / danger=100 为 OR)。
    `track` 缺省时由渲染层按该特质的轨道推定 (单轨特质即轨名=特质名)。"""
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
    """游戏 + 启用 Mod 的 common/traits(+/tracks) 下的 .txt 路径。"""
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
    """特质来源指纹 (v34, 问题4): 游戏/Mod 目录 + 各特质文件的 (路径, 大小, mtime)。

    存进 data/trait_names.json; 与当前指纹不符即重建 —
    此前该表只校验 schema, 启用新 Mod (如 Carnalitas) 后**不会**重建,
    于是新 Mod 的特质查不到中文名, 又被静默丢弃 (`dick_small_bad_3` 即此)。
    只取文件元信息, 不读内容 — 建表时才读, 开销可忽略。"""
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
    """游戏 + 启用 Mod 的 common/traits → 特质基础名 + 类别 + 档位名条件表。

    返回::

        {"schema": 4,
         "traits":      {trait_key: loc_key},       # **基础名** (v29/v32)
         "categories":  {trait_key: category},      # 游戏 category (v31)
         "level_names": {trait_key: [{"any": bool,
                                      "clauses": [{track, op, value}, …],
                                      "key": loc_key}, …]}}   # 按 XP 换名 (v32)

    v31: 同一次解析顺带取 `category = personality|education|lifestyle|fame|health|
    commander|childhood|court_type` —— 「为人」句按类分句、体况瞬时特质不进履历都靠它
    (先天特质 (beauty_*/intellect_*/physique_* 等) 游戏未给 category, 归空串)。

    v32 (马克龙问题2): 旧实现取 `name` 块里**第一个** desc, 而游戏把**最高档**名写在最前
    —— 实测 54 个按 XP 换名的特质 (lifestyle_reveler/aggressive_attacker/logistician…)
    全部显示成顶档名 (玩家 reveler XP=0 却写作「传奇的狂欢者」)。现改为:
    基础名取 `first_valid` 里**无 trigger 的裸 desc**, 各档名与其 XP 条件分开落 `level_names`,
    由渲染层按角色实际 XP 求值。"""
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


# ---------------------------------------------------------------------------
# 特质 XP 轨道表 (v32): common/traits 的 track / tracks → 轨道名 + 档位阈值
# ---------------------------------------------------------------------------
# 存档里角色的 `trait_xp_amounts` 是与 `traits` 顺序对齐的扁平数组, 每条轨道一个数
# (多轨特质按定义声明顺序占位; 实测马克龙档 3987/3987 角色 100% 命中)。本表给
# 「哪段数值属于哪条轨道」以及该轨道的档位阈值, 轨道显示名走本地化 `trait_track_<key>`。

def _trait_tracks_path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "trait_tracks.json")


# 命名档位键 → XP 阈值 (游戏里 scarred / lifestyle_traveler 等少数特质不用数字键;
# 实证 scarred 的 name 块: value < 50 → 一级、= 100 → 三级)
_NAMED_LEVELS = {"trait_first_level": 25, "trait_second_level": 50,
                 "trait_third_level": 100, "trait_fourth_level": 150,
                 "trait_fifth_level": 200}


def _track_levels(sub):
    """轨道内层块 → 阈值列表 (数字键直取; 命名档位键按 _NAMED_LEVELS 折算)。"""
    lv = [int(x) for x in re.findall(r"^\s*(\d+)\s*=\s*\{", sub, re.M)]
    lv += [_NAMED_LEVELS[k] for k in
           re.findall(r"^\s*(trait_[a-z_]*level)\s*=\s*\{", sub, re.M)
           if k in _NAMED_LEVELS]
    return sorted(set(lv))


def build_trait_tracks(cfg):
    """游戏 + 启用 Mod 的 common/traits → {"tracks": {trait: [{track, levels}, …]}}。

    多轨 `tracks = { … }` 按声明顺序保序; 单轨简写 `track = { … }` 的轨名 = 特质键
    (`_traits.info`: "If only one track is needed then a short hand is provided which
    creates one track named after the trait itself")。"""
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
    """载入特质轨道表; 缺失/旧版/**来源指纹不符**即重建 (v34, 问题4)。

    v85: report 出参 (启动自检) 与「需重建」日志 —— 见 load_localization_table;
    并补上**退表保护**: 重建结果不足旧表六成时保留旧表不落盘 (游戏目录不可用时
    会重建出空表, 启动自检不该因此抹掉好表)。"""
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
                # v86: 指纹不符只提示, 不自动重建 (建表一律手动 —— 见
                # load_localization_table 同处注释)
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
    """载入特质显示名 + 类别表; 缺失、旧版 (无 categories/level_names) 或
    **来源指纹不符**时重建 (v34, 问题4 — 启用新 Mod 后自动补全)。

    v85: report 出参 (启动自检) 与「需重建」日志 —— 见 load_localization_table;
    并补上**退表保护**: 重建结果不足旧表六成时保留旧表不落盘 (游戏目录不可用时
    会重建出空表, 启动自检不该因此抹掉好表)。"""
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
                # v86: 指纹不符只提示, 不自动重建 (建表一律手动)
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
                   "county": "伯爵领", "hegemon": "皇朝"}
# v87 (问题4): 删去 `"barony": "堡"` —— 「堡」不是游戏文案 (全 simp_chinese 无任何键
# 的值为「堡」; 领地类型 `castle_holding` 的正式名是「城堡」), 是项目自造的地名后缀,
# 治所因此写出「罗马堡」。男爵领一律只用地名 (`facts._title_tier_word` 入口 barony
# 早退 + `GENERIC_OFFICE_ZH` 的官称另有 rank<2 闸门)。

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
    县/州府/镇/路/行台/皇朝), 缺失回退通用表 (王国/帝国/公国/伯爵领/堡/皇朝)。

    v41 (问题1, 见 logs/research_admin_titles.md): **删去 `<政体>_salary_rank_*`
    一档** —— 那批键是**封臣契约「俸禄等级」的 UI 标签**
    (`common/subject_contracts/contracts/administrative.txt:385-459`), 不是头衔
    层级词; 行政制的「行省/总督区」与「军区/督军区」等正确层级词来自
    `common/flavorization/` 的 `type = title` 条目, 由 `facts._tier_word_at`
    先行查询, 查不到才落到这里的通用表。"""
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
_BISHOP_TITLES = None
_THEOCRACY_TITLES = None
_SPIRITUAL_FULFILLMENT = None
_COUNCIL_NAMES = None
_TRAIT_NAMES = None
_TRAIT_TRACKS = None
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


def bishop_titles(cfg=None):
    """主教称谓保序臂表单例 (v80 点5): {"arms": […], "religions": …, "faiths": …}。"""
    global _BISHOP_TITLES
    if _BISHOP_TITLES is None:
        _BISHOP_TITLES = load_bishop_titles(cfg or llm.load_config())
    return _BISHOP_TITLES


def theocracy_titles(cfg=None):
    """神权官称自定义本地化臂表单例 (v87): {"blocks": {块名: [臂…]}, …}。"""
    global _THEOCRACY_TITLES
    if _THEOCRACY_TITLES is None:
        _THEOCRACY_TITLES = load_theocracy_titles(cfg or llm.load_config())
    return _THEOCRACY_TITLES


def spiritual_fulfillment(cfg=None):
    """灵性满足分档表单例 (v89 问题6): {"types": [{key, religions, levels}…]}。"""
    global _SPIRITUAL_FULFILLMENT
    if _SPIRITUAL_FULFILLMENT is None:
        _SPIRITUAL_FULFILLMENT = load_spiritual_fulfillment(cfg or llm.load_config())
    return _SPIRITUAL_FULFILLMENT


def council_names(cfg=None):
    """议会席位名链单例 (v80 点5): {"positions": {席位键: [臂…]}}。"""
    global _COUNCIL_NAMES
    if _COUNCIL_NAMES is None:
        _COUNCIL_NAMES = load_council_names(cfg or llm.load_config())
    return _COUNCIL_NAMES


def trait_names(cfg=None):
    """特质显示名 + 类别表单例 (v29/v31/v32):
    {"traits": {trait_key: 基础名 loc_key}, "categories": {trait_key: category},
     "level_names": {trait_key: [{any, clauses, key}, …]}}。"""
    global _TRAIT_NAMES
    if _TRAIT_NAMES is None:
        _TRAIT_NAMES = load_trait_names(cfg or llm.load_config())
    return _TRAIT_NAMES


def trait_track_table(cfg=None):
    """特质 XP 轨道表单例 (v32): {"tracks": {trait_key: [{track, levels}, …]}}。"""
    global _TRAIT_TRACKS
    if _TRAIT_TRACKS is None:
        _TRAIT_TRACKS = load_trait_tracks(cfg or llm.load_config())
    return _TRAIT_TRACKS


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
# 启动自检 (v85): 校验来源指纹, 不符即自动重建一次
# ---------------------------------------------------------------------------
# 2026-09-30 定规: 三张派生表 (本地化 / 特质显示名 / 特质轨道) 不再随仓库发布
# (见 .gitignore), 于是**新用户首次运行必然缺表**, 老用户勾选/更新 Mod、游戏打
# 补丁后指纹也会变。原本的重建是**惰性**的 —— 等到首份传记要查名字、查特质才
# 触发, 于是这段等待落在「按下启动后什么都不发生」的窗口里, 像是卡死。
# 现在 watch / continue / scan 启动时先自检一次: 打印本地化来源 (游戏目录 +
# 启用 Mod 个数 + 来源指纹), 逐张比对表内指纹, 缺失/过期/不符者当场重建一次,
# 建好即灌进模块单例 (省去后续再解析一遍 35MB 的 localization.json)。

# 表清单: 显示名 / 表文件 / schema / 表内键容器 / 载入器 / 来源指纹 / 模块单例
_SOURCE_TABLES = (
    {"name": "本地化表", "path": _localization_path, "schema": 3, "keys": "table",
     "load": load_localization_table, "fp": "loc", "singleton": "_TABLE"},
    {"name": "特质显示名表", "path": _trait_names_path, "schema": 4, "keys": "traits",
     "load": load_trait_names, "fp": "trait", "singleton": "_TRAIT_NAMES"},
    {"name": "特质轨道表", "path": _trait_tracks_path, "schema": 2, "keys": "tracks",
     "load": load_trait_tracks, "fp": "trait", "singleton": "_TRAIT_TRACKS"},
)

# 自检结论 → 人话 (状态取值见 _fill_report 与 _stored_state)
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
    """自检状态 → 中文短句 (pipeline 打印用)。"""
    return _SELFCHECK_TEXT.get(state, state)


def _source_fingerprints(cfg):
    """两张来源指纹 (本地化 / 特质): 取不到时留空而不抛 —— 自检不阻断启动。"""
    out = {}
    for key, fn in (("loc", source_fingerprint), ("trait", trait_source_fingerprint)):
        try:
            out[key] = fn(cfg) or {}
        except Exception as e:
            out[key] = {"hash": None, "game": "", "mods": [], "error": str(e)}
    return out


def _stored_state(path, schema, keys_key, source_hash):
    """只读比对: 表里存的来源指纹 vs 当前来源 → (state, 表内条数)。

    只用于只读自检; 真正的重建一律交给 load_* (那里有退表保护)。"""
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
    """只读自检 (不重建): 逐张报告三张派生表的状态, 供 `pipeline.py status` 打印。"""
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
    """启动自检 (v85): 校验三张派生表的来源指纹, 缺失 / 过期 / 不符者**当场重建
    一次**, 结果灌进模块单例, 供本进程后续直接查表。返回自检报告 dict:
    {"fingerprints", "rows", "seconds", "rebuilt", "warnings"}。

    调用点: pipeline.py 的 watch / continue / scan 启动路径 —— 两个启动器 .bat
    (启动监控 = watch、启动续传 = continue) 都走这条路。每张表至多重建一次;
    游戏目录不可用时 localization 侧保留旧表 (见 load_localization_table 的退表
    保护), 此处不抛异常、不阻断启动。"""
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
        globals()[t["singleton"]] = data     # 灌单例: 后续查表不必再解析一遍
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


def _param_flags(body):
    """参数块体 → 参数名集合 (v86, 兼容 1.19 与 1.20 两种写法)。

    1.19 / 教义: `human_sacrifice_active = yes` (布尔或数值)
    1.20 tenets: **裸标志清单** —— `parameters = { human_sacrifice_active  … }`
                 (无 `=` 号, `_script_items` 会整条跳过, 旧稿因此 1.20 下全丢)
    1.20 教义:   `special_parameters = { hostility_levels = { … } }` (子块名即参数名)
    """
    flags = set()
    for pk, op, val in _script_items(body):
        if op == "block":
            flags.add(pk)           # 子块名本身就是一个参数 (hostility_levels 等)
            continue
        if str(val).lower() in ("yes", "true") or str(val).isdigit():
            flags.add(pk)
    # 裸标志: 先抹掉所有 `key = 值` 与 `key = { … }` (含一层嵌套), 剩下的标识符即标志
    stripped = re.sub(
        r"[A-Za-z_][A-Za-z0-9_.]*\s*(?:>=|<=|!=|\?=|=|<|>)\s*(?:\{[^{}]*\}|[^\s{}]+)",
        " ", body or "")
    for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_.]*", stripped):
        flags.add(m.group(0))
    return flags


def build_doctrine_parameters(cfg):
    """游戏 + 启用 Mod 的 doctrine_types/*.txt 与 tenet_types/*.txt
    → {"doctrines": {教义: [参数…]}, "by_parameter": {参数: [教义…]}}
    (Mod 同名教义整体覆盖)。

    v86 (1.20): tenets 从 doctrine_types 拆到新的 `tenet_types/` 目录, 且参数块
    改成**裸标志清单** (如 `game/common/religion/tenet_types/00_tenet_types.txt:3092`
    的 `tenet_human_sacrifice` → `parameters = { human_sacrifice_active … }`),
    教义侧则改用 `special_parameters`。旧稿只扫 doctrine_types 且只认 `key = 值`,
    于是 1.20 下教义参数表从 213 条教义 / 347 个参数塌成 3 / 4,
    `human_sacrifice_active` 等全丢 (处决「献祭」风味随之失效)。
    现两目录、两种参数块 (parameters / special_parameters)、两种写法都收;
    同一 root 内 tenet_types 后扫 (Mod 仍整体后扫, 保持「Mod 覆盖本体」口径)。"""
    by_doctrine = {}
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
    by_param = {}
    for doc, params in by_doctrine.items():
        for p in params:
            by_param.setdefault(p, []).append(doc)
    for p in by_param:
        by_param[p] = sorted(by_param[p])
    return {"schema": 2, "doctrines": by_doctrine, "by_parameter": by_param}


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
            if data.get("schema") == 2 and data.get("by_parameter"):
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
