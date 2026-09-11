# -*- coding: utf-8 -*-
"""游戏 flavorization 解析器 (v30)
=================================
CK3 的**统治者称呼**与**头衔名后缀**由 `common/flavorization/*.txt` 定义: 每个条目
给出 type(character/title)、tier、gender、priority, 以及 governments / name_lists /
heritages / faiths / religions 等条件 —— 取「优先级最高且全部条件命中」者, 其
**块名即本地化键**。

为什么要有它 (修复方案_菲利普4.md 问题2)
-----------------------------------------
Norse 段的块名叫 `count_feudal_male_norse`, 但块内写的是 `tier = duchy`、
`priority = 30`; 通用的 `duke_tribal_male`(大酋长) 只有 26。存档信封实测:

    melt_878  meta_title_name = 罗加兰酋邦        meta_player_name = 酋长崔佛
    melt_888  meta_title_name = 居拉辛斯勒格雅尔国  meta_player_name = 雅尔崔佛

而 facts/localization 的层级词从不查这张表 (只硬编码了 chinese 一族 + 政体通用词),
于是把公国级诺斯人写成「居拉辛斯勒格大酋长」「居拉辛斯勒格公国」。

产物: data/flavorization.json (游戏 + 启用 Mod 合并, Mod 同名块整体覆盖)。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm                 # noqa: E402
import localization as L    # noqa: E402

_SCHEMA = 1
_TABLE = None


def _path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "flavorization.json")


def _strip_comments(text):
    """去掉 `#` 行内注释 (引号内除外)。

    flavorization 文件里有大量注释掉的示例条目, 注释里的 `{`/`}` 会让
    localization._top_blocks 的深度计数错位 (实测 00_title_holders.txt 会多出
    2400 余个「顶层块」)。此处先剥注释再解析。"""
    out = []
    for line in (text or "").split("\n"):
        q = False
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '"':
                q = not q
            elif ch == "#" and not q:
                break
            i += 1
        out.append(line[:i])
    return "\n".join(out)


def _list_of(items, key):
    """`key = { a b c }` → ['a','b','c']; 单值 `key = a` 亦收; 缺失 → []。
    (L._script_items 把 `= { … }` 记为 op='block', 故块体存在 '_'+key 下。)"""
    v = items.get("_" + key)
    if v is None:
        v = items.get(key)
    if not isinstance(v, str) or not v.strip():
        return []
    return [x for x in v.replace(",", " ").split() if x]


def _rules_of(items):
    """flavourization_rules 子块 → {规则: bool}。"""
    raw = items.get("_flavourization_rules") or ""
    out = {}
    for k, op, v in L._script_items(raw):
        if op == "block":
            continue
        out[k] = str(v).strip().lower() in ("yes", "true")
    return out


def build_flavorization(cfg):
    """游戏 + 启用 Mod 的 common/flavorization/*.txt → 条目表。"""
    entries = {}
    roots = []
    g = L.game_dir(cfg)
    if g:
        roots.append(g)
    roots += L.enabled_mod_dirs(cfg)
    for root in roots:
        d = os.path.join(root, "common", "flavorization")
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
            for key, body in L._top_blocks(txt):
                items = {}
                for a, op, v in L._script_items(body):
                    if op == "block":
                        items["_" + a] = v
                    else:
                        items[a] = v
                typ = (items.get("type") or "").strip()
                if typ not in ("character", "title"):
                    continue          # domicile 等类型本项目不渲染
                tier = (items.get("tier") or "").strip()
                if not tier or tier == "none":
                    continue          # 无层级条目不参与层级词取词 (性能与准确性)
                special = (items.get("special") or "holder").strip()
                rules = _rules_of(items)
                # 评估不了的条件一律标 unsupported: 宁可不取词, 也不误用他人称谓。
                # 实测 00_title_holders.txt 里有 76 处 `titles = { d_brittany }`
                # 这类**限定头衔**的条目 (不判就会让全欧公爵都叫「布列塔尼公爵」),
                # 另有 flag / holding / domicile_type / 契约义务旗标 / de_jure_liege /
                # council_position / 单值 faith 等条件。
                unsupported = bool(
                    items.get("flag") or items.get("domicile_type")
                    or items.get("holding") or items.get("council_position")
                    or items.get("faith")
                    or items.get("_subject_contract_obligation_flags")
                    or items.get("_de_jure_liege"))
                if special not in ("holder", ""):
                    unsupported = True   # 教宗/议员/太后/王子等由既有分支渲染
                try:
                    prio = int(float(items.get("priority") or 0))
                except (TypeError, ValueError):
                    prio = 0
                entries[key] = {
                    "key": key, "type": typ, "tier": tier,
                    "gender": (items.get("gender") or "").strip(),
                    "priority": prio, "special": special,
                    "governments": _list_of(items, "governments"),
                    "name_lists": _list_of(items, "name_lists"),
                    "heritages": _list_of(items, "heritages"),
                    "faiths": _list_of(items, "faiths"),
                    "religions": _list_of(items, "religions"),
                    "titles": _list_of(items, "titles"),
                    "rules": rules,
                    "unsupported": unsupported,
                }
    return {"schema": _SCHEMA, "entries": entries}


def save_flavorization(cfg, data):
    path = _path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)
    return path


def load_flavorization(cfg=None, force=False):
    """载入条目表; 缺失或强制时由游戏/Mod 文件重建。"""
    cfg = cfg or llm.load_config()
    path = _path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == _SCHEMA and data.get("entries"):
                return data
        except Exception:
            pass
    data = build_flavorization(cfg)
    if data.get("entries"):
        save_flavorization(cfg, data)
    return data


def table(cfg=None):
    """模块级单例 (facts 每篇只取一次)。"""
    global _TABLE
    if _TABLE is None:
        try:
            _TABLE = load_flavorization(cfg)
        except Exception:
            _TABLE = {"schema": _SCHEMA, "entries": {}}
    return _TABLE


def resolve(kind, tier, gender, *, government="", name_list="", heritage="",
            faith="", religion="", title_key="", independent=True, top=None,
            cfg=None):
    """按游戏规则取词: 返回**本地化键** (块名) 或 ''。

    与游戏同序: priority 高者先试, 全部条件命中即取 (governments / name_lists /
    heritages / faiths / religions 为空视为不限; special 非 holder 与含 flag 的
    条目在建表时已标 unsupported)。`titles` 是**限定头衔**条件 — 只有传入的
    title_key 在其中时才命中 (不传即跳过这类条目)。`independent` 用于
    only_vassals/only_independent 两条规则; `top` 传入最高领主的同名字段后,
    未显式写 `top_liege = no` 的条目改按最高领主判定 (游戏默认行为)。"""
    fl = table(cfg)
    ents = (fl.get("entries") or {})
    if not ents:
        return ""
    best_key, best_pri = "", None
    for e in ents.values():
        if e.get("type") != kind or e.get("tier") != tier:
            continue
        if e.get("unsupported"):
            continue
        tls = e.get("titles") or []
        if tls and title_key not in tls:
            continue
        if e.get("gender") and e["gender"] != gender:
            continue
        prio = e.get("priority") or 0
        if best_pri is not None and prio <= best_pri:
            continue
        rules = e.get("rules") or {}
        # top_liege 默认 yes: 封臣按最高领主的政体/文化判定 (显式 no 者按自身)
        use_top = bool(top) and rules.get("top_liege", True) is not False
        gov_x = (top.get("government") or government) if use_top else government
        nl_x = (top.get("name_list") or name_list) if use_top else name_list
        hs_x = (top.get("heritage") or heritage) if use_top else heritage
        fa_x = (top.get("faith") or faith) if use_top else faith
        re_x = (top.get("religion") or religion) if use_top else religion
        govs = e.get("governments") or []
        if govs and gov_x not in govs:
            continue
        nls = e.get("name_lists") or []
        if nls and nl_x not in nls:
            continue
        hs = e.get("heritages") or []
        if hs and hs_x not in hs:
            continue
        fs = e.get("faiths") or []
        if fs and fa_x not in fs:
            continue
        rs = e.get("religions") or []
        if rs and re_x not in rs:
            continue
        if rules.get("only_independent") and not independent:
            continue
        if rules.get("only_vassals") and independent:
            continue
        best_key, best_pri = e["key"], prio
    return best_key


def coverage(cfg=None):
    """自检用: 按 (type, tier) 统计条目数, 并列出覆盖到的 culture 名系/heritage。"""
    fl = table(cfg)
    out = {}
    nls, hss, govs = set(), set(), set()
    for e in (fl.get("entries") or {}).values():
        out.setdefault((e.get("type"), e.get("tier")), 0)
        out[(e.get("type"), e.get("tier"))] += 1
        nls.update(e.get("name_lists") or [])
        hss.update(e.get("heritages") or [])
        govs.update(e.get("governments") or [])
    return {"counts": {f"{k[0]}/{k[1]}": v for k, v in sorted(out.items())},
            "name_lists": sorted(nls), "heritages": sorted(hss),
            "governments": sorted(govs)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = llm.load_config()
    data = load_flavorization(cfg, force=True)
    print("条目数:", len(data.get("entries") or {}))
    cov = coverage(cfg)
    for k, v in cov["counts"].items():
        print("  %-22s %d" % (k, v))
    print("覆盖 name_lists %d 个 / heritages %d 个 / governments %d 个"
          % (len(cov["name_lists"]), len(cov["heritages"]),
             len(cov["governments"])))
    print("落盘:", _path(cfg))
