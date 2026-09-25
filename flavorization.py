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

_SCHEMA = 3   # v64: ruler_child (王子/公主) 条目入表并可求值 (special 过滤)
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
                # v53 (问题1): `_subject_contract_obligation_flags` 改可求值,
                # 不再标 unsupported (天朝国王级观察使/经略使/都护靠它分档)。
                obligation_flags = _list_of(items, "subject_contract_obligation_flags")
                unsupported = bool(
                    items.get("flag") or items.get("domicile_type")
                    or items.get("holding") or items.get("council_position")
                    or items.get("faith")
                    or items.get("_de_jure_liege"))
                # v64 (问题2): `special = ruler_child` (王子/公主) 改**可求值** ——
                # 其 `governments` 是穷举, 部落/游牧制在**任何层级**都没有条目,
                # 故「有没有称号」这件事必须问表 (旧稿由 `facts._prince_word` 的
                # 末档无条件回落「王子/公主」兜住, 于是游牧/部落子女凭空得号)。
                # 其余 special (教宗/议员/太后/居所) 仍由各自分支渲染, 保持 unsupported。
                if special not in ("holder", "", "ruler_child"):
                    unsupported = True
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
                    "obligation_flags": obligation_flags,
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
            obligation_flags=None, cfg=None, special="holder"):
    """按游戏规则取词: 返回**本地化键** (块名) 或 ''。

    与游戏同序: priority 高者先试, 全部条件命中即取 (governments / name_lists /
    heritages / faiths / religions 为空视为不限; 含 flag 的条目在建表时已标
    unsupported)。`titles` 是**限定头衔**条件 — 只有传入的 title_key 在其中时才
    命中 (不传即跳过这类条目)。`independent` 用于 only_vassals/only_independent
    两条规则; `top` 传入最高领主的同名字段后, 未显式写 `top_liege = no` 的条目
    改按最高领主判定 (游戏默认行为)。
    v53: `obligation_flags` 是角色当时封臣合同解码出的义务旗标列表
    (如 celestial_province_standard); 条目要求旗标时须有交集才命中。
    v64 (问题2): `special` 过滤条目类别 —— 缺省 "holder" (统治者称谓, 旧行为逐字
    不变); 传 "ruler_child" 时只取 `special = ruler_child` 的王子/公主条目
    (由 `facts._prince_word` 用来判「此处游戏有没有称号」)。两类互不相干:
    不传 special 时 ruler_child 条目一律不参与, 防「王子」压过统治者称谓。"""
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
        if (e.get("special") or "holder") != (special or "holder"):
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
        # top_liege 默认 yes: 封臣按最高领主的政体/文化判定 (显式 no 者按自身)。
        use_top = bool(top) and rules.get("top_liege", True) is not False
        # v41 (问题1) 关键修正: `ignore_top_liege_government` (游戏
        # `_flavourization.info:195-202`) —— 该旗标为真时, **除 government 外**
        # 才改用最高领主。旧实现从未读这条规则, 于是最高领主一转行政制,
        # 封建留守的封臣也去命中 `*_administrative_*_byzantine_group`
        # (priority 51/50/29/28), 压过 `duchy_feudal`(27)/`duke_feudal_male`(26),
        # 把诺兰档封建期 (1087–1094) 的公爵/伯爵写成军区/将军/分区/分区长。
        # 游戏缓存串反证: date=1096.8.15 的封建封臣格哈德II 仍是「公爵」、
        # 其头衔 d_bar 仍是「巴尔公国」 (logs/research_feudal_greek_titles.md §Q5)。
        gov_x = (government if (not use_top
                               or rules.get("ignore_top_liege_government"))
                 else (top.get("government") or government))
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
        # v53 (问题1): 合同义务旗标 — 条目列出的旗标须与角色当时旗标有交集。
        # 条目未列旗标则不限; 角色无旗标时这类条目跳过 (回退无旗标的总督/节度使)。
        want_flags = e.get("obligation_flags") or []
        if want_flags:
            have = set(obligation_flags or [])
            if not have.intersection(want_flags):
                continue
        best_key, best_pri = e["key"], prio
    return best_key


# v64 (问题2): 本项目**会出词**的中华/天朝词族 —— 这几条的名字条件 (name_lists =
# name_list_han) 按项目 v54 口径「天朝/行政类称谓与文化无关」处理, 故闸门对它们
# 放宽文化判定 (斯卡利茨档捷克人建岭南照样出皇子/皇女)。
# 其余带 name_lists/heritages/religions 的 ruler_child 条目 (guanches 关契人 /
# tangut 党项 / roman 罗马 / iberian 伊比利亚 / iranian 伊朗 / dravidian 达罗毗荼 /
# southeast_asian 东南亚) 是**文化专属原生词**, 本项目不出这些词, 一律照游戏条件判定
# —— 否则 `title_prince_male_guanches` (governments 含 tribal, priority 130) 会让
# 任何文化的部落制王国级子女都通过闸门。
_PRINCE_CN_KEYS = frozenset({
    "prince_duchy_chinese", "princess_duchy_chinese",
    "prince_kingdom_feudal_chinese", "princess_kingdom_feudal_chinese",
    "prince_kingdom_celestial_chinese", "princess_kingdom_celestial_chinese",
    "prince_kingdom_celestial_chinese_independent",
    "princess_kingdom_celestial_chinese_independent",
    "prince_empire_chinese", "princess_empire_chinese",
    "prince_empire_celestial_chinese", "princess_empire_celestial_chinese",
    "prince_hegemony_chinese", "princess_hegemony_chinese",
    "prince_male_celestial_chinese", "princess_female_celestial_chinese",
})


def ruler_child_exists(tier, gender, *, government="", name_list="", heritage="",
                       faith="", religion="", title_key="", independent=True,
                       top=None, obligation_flags=None, cfg=None):
    """游戏侧在 (层级 × 性别 × 政体 × 独立/封臣) 下**有没有**王子/公主称号 ——
    返回命中的本地化键, 无则 '' (v64, 问题2)。

    与 `resolve` 的两处**刻意不同** (本项目口径, 见 `facts._prince_word` 与 v54):

    ① 只取 `special = ruler_child` 的条目 (与统治者称谓互不相干);
    ② **中华/天朝词族** (`_PRINCE_CN_KEYS`) 不查文化/信仰 —— 项目对天朝类称谓早已采
       「与文化无关」口径 (v54: 诺斯伯爵在中国亦为刺史), 故中华皇朝的非汉人天子
       (斯卡利茨档捷克人建岭南) 照样出皇子/皇女; 其余文化专属条目
       (guanches/tangut/roman/iberian/iranian/dravidian/southeast_asian) 仍按
       name_lists/heritages/faiths/religions 判定。

    为什么需要它: `prince`/`princess`/`prince_empire`/`princess_empire` 的
    `governments` 是**穷举**且不含 tribal/nomad (`00_flavorization.txt:354-400`),
    故部落制/游牧制在任何层级都没有王子/公主称号 —— 「有没有」必须问表, 而不能由
    末档无条件回落「王子/公主」。
    """
    fl = table(cfg)
    ents = (fl.get("entries") or {})
    if not ents:
        return ""
    best_key, best_pri = "", None
    for e in ents.values():
        if e.get("type") != "character" or e.get("tier") != tier:
            continue
        if (e.get("special") or "holder") != "ruler_child" or e.get("unsupported"):
            continue
        if e.get("gender") and e["gender"] != gender:
            continue
        prio = e.get("priority") or 0
        if best_pri is not None and prio <= best_pri:
            continue
        tls = e.get("titles") or []
        if tls and title_key not in tls:
            continue
        rules = e.get("rules") or {}
        use_top = bool(top) and rules.get("top_liege", True) is not False
        gov_x = (government if (not use_top
                               or rules.get("ignore_top_liege_government"))
                 else (top.get("government") or government))
        govs = e.get("governments") or []
        if govs and gov_x not in govs:
            continue
        if e.get("key") not in _PRINCE_CN_KEYS:
            # 文化/信仰条件: 中华词族除外 (见 docstring ②)
            nls = e.get("name_lists") or []
            if nls and (top.get("name_list") if use_top else name_list) not in nls:
                continue
            hs = e.get("heritages") or []
            if hs and (top.get("heritage") if use_top else heritage) not in hs:
                continue
            fs = e.get("faiths") or []
            if fs and (top.get("faith") if use_top else faith) not in fs:
                continue
            rs = e.get("religions") or []
            if rs and (top.get("religion") if use_top else religion) not in rs:
                continue
        if rules.get("only_independent") and not independent:
            continue
        if rules.get("only_vassals") and independent:
            continue
        want_flags = e.get("obligation_flags") or []
        if want_flags and not set(obligation_flags or []).intersection(want_flags):
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
