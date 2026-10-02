# -*- coding: utf-8 -*-
"""快速回归（提速基建）：无熔件、秒级；纯函数 + facts 快照。

用法：
    & tools\\py.ps1 tools\\tests\\verify_fast.py [快照路径]
    ｜ 缺省自动取 output/周氏/data/snap_38673_889.1.1_d2.json

分层原则（本会话教训）：
    · 纯函数（兜底/取词/档位/席位/主语剥离/括注判据）→ 本脚本，**不需要熔件**；
    · 需要熔件的端到端断言 → experiments/verify_zhou.py，只在里程碑跑一次；
    · 快照由 tools/tests/snap.py 生成（载一次熔件），本脚本对它做**传输面**断言。

覆盖：
    A 纯函数：裸键兜底 / 职位条件树 / 档位词 / 席位取词 / 句首主语剥离 / 口粮档 / 健康压力
    B 快照：传输面无裸键、无括注同位语、无「言语相通」、无货币数值、席位动态名、
            传主行迹省主语、家世去重、冒险者行踪、隐事方向、快照新鲜度
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F          # noqa: E402
import localization as L   # noqa: E402
import style              # noqa: E402

DEFAULT_SNAP = os.path.join(ROOT, "output", "周氏", "data", "snap_38673_889.1.1_d2.json")
_OK = True
_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]{2,}(?![A-Za-z0-9_])")
_PAREN_RE = re.compile(r"（([^）]{1,24})）")
# v55 (问题2): 事实层括注一律自然语言化 (用户 2026-09-19 拍板「除白名单外全改」),
# 白名单只剩「去掉括注反而含混」的四类 —— 数值型/日期型补注 (旧稿放行的 \d、于、
# 涉及、生父、同年、原为、见载、封臣、入赘婚 等) 一律不再放行, 残留即 FAIL。
# 另有第五类「特质轨道枚举」(不法之徒（强盗、窃贼、掠夺者）) 由 _track_names() 放行。
_NOTE_OK_RE = re.compile(
    r"(教育[一二三四五]级"   # 教育特质档位名 (特质名的后缀, 去括号会与特质名粘连)
    r"|^外$"                 # 「（外）孙」「（外）孙女」—— 词形本身
    r"|名讳不详"             # 占位符常量
    r"|死因不详"             # player_death 的字段值, 不是句子
    r")")
# v69 (用户 2026-09-27 拍板): 《XX历代记》按用户给的样例出「唐皇朝（868年至887年）」
# 「李漼（859年9月13日从李忱处受任命继位，随后于887年1月2日失去天命）」—— 这两类
# 括注是**程序按游戏 `history.type` 生成的结构化字段** (朝代年代区间 / 即位缘由),
# 不是模型自撰的「名词（名词）」式补注, 故按形态放行 (形态收得很窄: 日期 + 缘由词表)。
_V69_SPAN_PARA_RE = re.compile(
    r"^\d+年(?:\d+月)?(?:至\d+年(?:\d+月)?|至今)$")
_V69_SUCC_PARA_RE = re.compile(
    r"^\d+年(?:\d+月(?:\d+日)?)?"
    r"(?:从[^（）]{1,20}处)?"
    r"(?:受任命继位|受禅继位|被派系拥立|被选举继位|受封头衔|受任命|征服夺取|凭宣称夺取"
    r"|借圣战夺取|借民粹叛乱夺取|篡夺继位|率部迁徙入主|因前任下台而继位|收回头衔"
    r"|承租头衔|收回租约|自立建国|重建天命|建立天命|重建头衔|自立|收回|宣誓效忠"
    r"|继位|起在位)"
    r"(?:，随后于\d+年\d+月\d+日(?:失去天命|失去头衔))?$")
# v69: 空位期 (天命毁弃) 的说明行也按同一口径写出 (事实层原文, 不含括注)
_V69_VACANCY_RE = re.compile(r"^(?:\d+年\d+月\d+日)?天命中绝，天下无主$|^其间无主$")


def check(name, cond, detail=""):
    global _OK
    if not cond:
        _OK = False
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + ("" if cond else f"  | {detail}"))


_TRACK_NAMES = None


def _track_names():
    """已知特质轨道名集合 (v52)。

    「不法之徒（强盗、骗子、窃贼、掠夺者）」是**数据层出词** (游戏
    `trait_track_*` 显示名的枚举), 不是「名词（名词）」式同位语 gloss ——
    与 v29b 禁的那类不同, 故按词表放行 (旧稿靠 `…阶` 白名单侥幸通过)。"""
    global _TRACK_NAMES
    if _TRACK_NAMES is None:
        names = set()
        try:
            table = L.table()
            for rows in (L.trait_track_table().get("tracks") or {}).values():
                for r in rows or []:
                    v = L.loc(table, "trait_track_" + str(r.get("track")))
                    if v:
                        names.add(v)
        except Exception:
            pass
        _TRACK_NAMES = names
    return _TRACK_NAMES


def _short_title_names():
    """游戏「简称」头衔的定位名集合 (v52-3)。

    这类名字**自带**层级词 (神圣罗马帝国/西哥特王国/博斯普鲁斯王国…), 故
    「神圣罗马帝国皇女」「西哥特王国公主」是正确写法, 断言时放行。"""
    global _SHORT_NAMES
    if _SHORT_NAMES is None:
        names = set()
        try:
            table = L.table()
            for k in L.short_titles():
                v = L.loc(table, k)
                if v and len(v) >= 2:
                    names.add(v)
        except Exception:
            pass
        _SHORT_NAMES = names
    return _SHORT_NAMES


_SHORT_NAMES = None


def _prince_tier_hits(text):
    """公主/王子称号叠层级词的违规清单 (简称头衔自带层级词者除外)。

    判据: 层级词收尾处 (王子/公主词起点) 若正好是某个简称头衔定位名的结尾
    (「神圣罗马帝国」+皇女 / 「西哥特王国」+公主), 则该层级词是名字的一部分, 放行。"""
    bad = []
    names = _short_title_names()
    for m in _PRINCE_TIER_RE.finditer(text or ""):
        te = m.start(2)
        if any(text[max(0, te - len(n)):te] == n for n in names):
            continue
        bad.append(m.group(0))
    return sorted(set(bad))


def _paren_violations(text):
    """传输面里「名词（名词）」式括注同位语清单。"""
    bad = []
    for m in _PAREN_RE.finditer(text or ""):
        c = m.group(1)
        if _NOTE_OK_RE.search(c):
            continue
        # v69: 《XX历代记》的朝代年代区间与即位缘由 (程序按 history.type 生成)
        if _V69_SPAN_PARA_RE.match(c) or _V69_SUCC_PARA_RE.match(c):
            continue
        # v52: 特质轨道枚举 (全部条目都是已知轨道名) 放行
        items = [x for x in re.split(r"[、,，]", c) if x.strip()]
        if items and all(x.strip() in _track_names() for x in items):
            continue
        bad.append(c)
    return sorted(set(bad))


_FACTS_CACHE = {}


def _facts_from_snap(snap):
    """按快照元信息重建 Facts 实例 (v41: 断言政体时效取词)。

    读同目录的 player_<pid>.json 与快照记录的熔件; 结果按 (pid, as_of) 缓存,
    同一进程内只建一次 (每次约数十秒)。读不到返回 None。"""
    meta = snap.get("meta") or {}
    facts = snap.get("facts") or {}
    pid = meta.get("player_id")
    as_of = facts.get("as_of") or meta.get("as_of")
    key = (pid, as_of)
    if key in _FACTS_CACHE:
        return _FACTS_CACHE[key]
    folder = meta.get("folder") or ""
    melt_name = meta.get("melt") or ""
    data = os.path.join(ROOT, "output", folder, "data")
    cache_path = os.path.join(data, f"player_{pid}.json")
    melt_path = os.path.join(data, melt_name)
    names = os.path.join(data, "names.json")
    if not (os.path.isfile(cache_path) and os.path.isfile(melt_path)):
        _FACTS_CACHE[key] = None
        return None
    try:
        import cache_lib as cl
        cache = json.load(open(cache_path, encoding="utf-8"))
        melt = cl.load_melt(melt_path)
        f = F.Facts(cache, melt, names if os.path.isfile(names) else None,
                    as_of=as_of, decade=facts.get("decade"))
    except Exception as e:            # noqa: BLE001
        print(f"  （重建 Facts 失败, 跳过该组: {e}）")
        f = None
    _FACTS_CACHE[key] = f
    return f


def group_a():
    print("[A1] 裸键兜底 (sanitize_fact_text / loc_text_ok)")
    s = F.sanitize_fact_text("【块】\n882年4月8日，MAX_RECURSIVE_DEPTH\n882年4月8日，程氏结仇。")
    check("哨兵串行被丢弃", "MAX_RECURSIVE_DEPTH" not in s and "程氏结仇" in s, s)
    check("trait_ 键行被丢弃",
          "trait_foo" not in F.sanitize_fact_text("x\ntrait_foo 中文"), "trait_foo")
    check("正常中文行保留", F.sanitize_fact_text("母语泰语，兼通汉语。") == "母语泰语，兼通汉语。")
    check("loc_text_ok: 纯英文判不可读", not F.loc_text_ok("some_raw_key"))
    check("loc_text_ok: 中文判可读", F.loc_text_ok("程氏结仇。"))

    print("[A2] 职位条件树 (cond_match / 变体表)")
    cps = L.court_positions().get("positions") or {}
    phys = cps.get("court_physician_court_position") or []
    def pick(scope):
        for v in phys:
            if L.cond_match(v.get("when") or {}, scope):
                return v.get("loc_key") or ""
        return ""
    celestial_vassal = {"gov_flag": "celestial", "tier": 2, "independent": False,
                        "heritage": "heritage_tai"}
    celestial_emperor = {"gov_flag": "celestial", "tier": 5, "independent": True,
                         "heritage": "heritage_chinese"}
    tribal = {"gov_flag": "tribal", "tier": 2, "independent": True, "heritage": ""}
    check("天朝制非帝国 → court_physician_celestial",
          pick(celestial_vassal) == "court_physician_celestial", pick(celestial_vassal))
    check("天朝制帝国 → court_physician_celestial_imperial",
          pick(celestial_emperor) == "court_physician_celestial_imperial",
          pick(celestial_emperor))
    check("部落 → 默认名 (无 localization_key)", pick(tribal) == "", pick(tribal))
    check("OR 组合求值 (tribal|nomadic)",
          L.cond_match({"op": "all", "children": [
              {"op": "any", "children": [{"gov_flag": "tribal"}, {"gov_flag": "nomadic"}]}]},
              tribal) is True)
    check("未知条件不命中", L.cond_match({"op": "all", "children": [{"unknown": "x"}]},
                                        celestial_vassal) is False)
    check("空条件恒真 (无 trigger 的变体)", L.cond_match({}, celestial_vassal) is True)

    print("[A3] 档位词 (level_word)")
    table, bands = L.table(), (L.currency_levels().get("bands") or {})
    for kind, val, want in (("piety", -865.8, "戴罪之人"), ("prestige", 1863.2, "崭露头角"),
                            ("influence", 534, "人微言轻"), ("merit", 2176.4, "七品"),
                            ("merit", 4524.4, "六品"), ("prestige", 40000, "传奇人物")):
        got = L.level_word(table, bands, kind, val)
        check(f"{kind} {val} → {want}", got == want, got)
    check("阈值取自 NCharacter 块 (prestige 5 档)", len(bands.get("prestige") or []) == 5,
          bands.get("prestige"))

    print("[A4] 议会席位取词 (council_seat_word)")
    tasks = L.council_tasks()
    cases = (("task_collect_taxes", "celestial_government", False, "司户"),
             ("task_collect_taxes", "celestial_government", True, "户部尚书"),
             ("task_collect_taxes", "feudal_government", False, "财政总管"),
             ("task_disrupt_schemes", "celestial_government", False, "察事"),
             ("task_foreign_affairs", "feudal_government", False, "掌玺大臣"))
    for t, gov, imp, want in cases:
        got = L.council_seat_word(table, tasks, t, gov, imp)
        check(f"{t}+{gov}{'(帝国)' if imp else ''} → {want}", got == want, got)

    print("[A5] 句首主语剥离 / 口粮档 / 健康压力")
    check("剥传主名 + 「的」",
          F._strip_subject_prefix("868年9月25日，勇敢者程岩的亲属程士庸去世。", "勇敢者程岩")
          == "868年9月25日，亲属程士庸去世。")
    check("保日期前缀",
          F._strip_subject_prefix("872年4月11日，勇敢者程岩与桑蜂成婚。", "勇敢者程岩")
          == "872年4月11日，与桑蜂成婚。")
    check("无可删处原样返回", F._strip_subject_prefix("添子周挖心。", "周立齐") == "添子周挖心。")
    check("口粮档位", F.provisions_band(120) == "口粮充盈"
          and F.provisions_band(40) == "口粮尚足" and F.provisions_band(3) == "口粮将尽",
          (F.provisions_band(120), F.provisions_band(40), F.provisions_band(3)))
    check("健康档位", F.health_state_zh(5.5) == "健康良好" and F.health_state_zh(0.5) == "病危")

    print("[A6] 括注判据 (本脚本的过滤器自身)")
    check("放行白名单式括注 (v55: 只剩去不掉的四类)",
          not _paren_violations("学识（教育三级）戎略（教育一级）（外）孙（名讳不详）"
                                "（死因不详）"),
          _paren_violations("学识（教育三级）（外）孙（死因不详）"))
    check("拦截已自然语言化的旧式括注 (v55 收紧)",
          set(_paren_violations(
              "死于龙编（死于龙编）（自872年起获得）（822年生，汉人）"
              "（被褫夺环州）（涉及唐皇帝李漼，自876年见载）（同年）（截至889年）"
              "（入赘婚）（唐皇朝封臣）（共7人）（危世）"))
          == {"死于龙编", "自872年起获得", "822年生，汉人", "被褫夺环州",
              "涉及唐皇帝李漼，自876年见载", "同年", "截至889年",
              "入赘婚", "唐皇朝封臣", "共7人", "危世"},
          _paren_violations("（自872年起获得）（822年生，汉人）"))
    check("拦截同位语式括注",
          set(_paren_violations("长史（延寿）周家族乡绅（世族庄园）宝物：X（名望级）"))
          == {"延寿", "世族庄园", "名望级"},
          _paren_violations("长史（延寿）周家族乡绅（世族庄园）"))
    print("[A6b] 《XX历代记》v69 结构化括注 (朝代年代区间 / 即位缘由)")
    check("放行朝代年代区间与即位缘由",
          not _paren_violations(
              "唐皇朝（868年至887年）李漼（859年9月13日从李忱处受任命继位，"
              "随后于887年1月2日失去天命）毕皇朝（963年1月至963年12月）"
              "元皇朝（972年至今）奄美珉（950年6月1日重建天命）"
              "奄美靖（953年6月6日被派系拥立）尼克·卡尔松（972年10月10日建立天命）"),
          _paren_violations("唐皇朝（868年至887年）李漼（859年9月13日继位）"))
    check("仍拦近形自撰补注",
          set(_paren_violations("（868年）朱元璋（明太祖）（被拥立）"
                                "（950年6月1日重建天命者）"))
          == {"868年", "明太祖", "被拥立", "950年6月1日重建天命者"},
          _paren_violations("朱元璋（明太祖）"))

    print("[A7] flavorization 取词 (问题2 — 与存档信封 meta_player_name 对照)")
    import flavorization as FZ
    norse = dict(government="tribal_government", name_list="name_list_norse",
                 heritage="heritage_north_germanic")
    asx = dict(government="feudal_government", name_list="name_list_anglo_saxon",
               heritage="heritage_west_germanic")
    han_i = dict(government="feudal_government", name_list="name_list_han",
                 independent=True)
    han_v = dict(government="feudal_government", name_list="name_list_han",
                 independent=False)
    check("诺斯 部落 公国 → count_feudal_male_norse (雅尔)",
          FZ.resolve("character", "duchy", "male", **norse)
          == "count_feudal_male_norse",
          FZ.resolve("character", "duchy", "male", **norse))
    check("诺斯 公国头衔名 → county_feudal_norse (雅尔国)",
          FZ.resolve("title", "duchy", "male", **norse) == "county_feudal_norse",
          FZ.resolve("title", "duchy", "male", **norse))
    check("汉 独立 公国 → duke_independent_male_feudal_chinese (王)",
          FZ.resolve("character", "duchy", "male", **han_i)
          == "duke_independent_male_feudal_chinese",
          FZ.resolve("character", "duchy", "male", **han_i))
    check("汉 封臣 公国 → duke_male_feudal_chinese (公)",
          FZ.resolve("character", "duchy", "male", **han_v)
          == "duke_male_feudal_chinese",
          FZ.resolve("character", "duchy", "male", **han_v))
    check("盎格鲁-撒克逊 女伯爵 → count_feudal_female_english",
          FZ.resolve("character", "county", "female", **asx)
          == "count_feudal_female_english",
          FZ.resolve("character", "county", "female", **asx))
    kb = FZ.resolve("character", "duchy", "male", government="feudal_government",
                    name_list="name_list_akan")
    check("限定头衔条目 (titles) 不外泄", kb != "duke_feudal_brittany", kb)
    check("flavorization 表非空", bool(FZ.coverage()["counts"]))

    print("[A8] 缺失陈述词汇不进模型 (v80 点2 — 拦截已移除, 改在源头清词)")
    import biography as bio
    import style as _style
    check("考据按语拦截已移除 (v80 点2 用户拍板)",
          not hasattr(bio, "_strip_meta_notes"), "biography 仍有 _strip_meta_notes")
    _rules = _style.rule_block("east", True) + "\n" + _style.rule_block("west", False)
    _bad_rules = [w for w in ("资料", "记载", "见载", "未载", "档案", "史册",
                              "不详", "不可考") if w in _rules]
    check("规则块不含资料/记载/未载类词", not _bad_rules, _bad_rules)
    _fw = "\n".join(str(v) for v in getattr(_style, "FACT_WORDING", {}).values())
    _bad_fw = [w for w in ("未载", "见载", "不再见于记载", "不详", "不可考")
               if w in _fw]
    check("事实层措辞表不含缺席陈述词", not _bad_fw, _bad_fw)


def group_b(snap_path):
    print(f"[B] 快照传输面 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, f"缺 {snap_path}（先跑 tools/tests/snap.py）")
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    meta, facts = snap["meta"], snap["facts"]
    p = facts["protagonist"]
    # 事实面 = 共享前缀 + 各篇 blocks（**不含**提示词指令文本：板块要求里的
    # 「(毒杀、缢杀…)」之类括注属提示词写法，不在本判据范围）
    fact_surface = snap["shared"] + "\n" + "\n".join(
        "\n".join(v.values()) if isinstance(v, dict) else str(v)
        for v in snap["blocks"].values())
    # 全请求面 = 事实面 + 指令面（只查裸键，不查括注）
    surface = snap["shared"] + "".join(
        f"{m['system']}\n{m['user']}" for m in snap["messages"].values())

    # 快照新鲜度：核心代码比快照新 → 提示重跑 snap.py（不判失败，避免卡流程）
    newer = [fn for fn, (_sz, mt) in (meta.get("code") or {}).items()
             if mt > os.path.getmtime(snap_path)]
    if newer:
        print(f"  WARN 快照可能过期（这些文件更新在后：{'、'.join(newer)}）"
              f"，建议重跑 tools/tests/snap.py")

    check("传输面无裸键 token", not _KEY_RE.search(surface),
          _KEY_RE.findall(surface)[:3])
    check("传输面无 MAX_RECURSIVE_DEPTH", "MAX_RECURSIVE_DEPTH" not in surface)
    badp = _paren_violations(fact_surface)
    check("事实面无「名词（名词）」括注同位语", not badp, badp[:8])
    check("无「言语相通」", "言语相通" not in surface)
    check("无「国库金/月入」", "国库金" not in surface and "月入" not in surface)
    check("无「牧群+数字」", not re.search(r"牧群\s*\d", surface),
          re.findall(r"牧群.{0,6}", surface)[:2])
    # 以下断言按周氏（38673）数据结构写就 — 其它家族快照只跑上面的通用面
    if meta.get("player_id") != 38673:
        print(f"  SKIP 周氏专属断言 (player_id={meta.get('player_id')}); "
              f"家族专属面见 group_c")
        return
    check("现状句含档位词", all(w in (p.get("status") or "")
                              for w in ("虔诚", "威望", "影响力", "功勋")), p.get("status"))
    check("御前会议席位为动态官职名 (长史/司户/…)",
          bool(p.get("council")) and "席：" in p["council"]
          and "（" not in p["council"], p.get("council"))
    check("【主角处境】已消失 / 无定居期驻地块",
          "【主角处境】" not in surface
          and not (facts.get("protagonist_stations") or []), facts.get("protagonist_stations"))
    cry = (facts.get("characters") or {}).get("11772") or {}
    evs = cry.get("events_subjectless") or []
    label = cry.get("label") or ""
    check("传主行迹省主语", bool(evs) and not any(
        x.split("，", 1)[-1].startswith(label) for x in evs), evs[:2])
    # 家世去重：主角子女的档案里不应再有 兄弟姊妹 / 父(主角)
    profs = facts.get("characters") or {}
    cache = json.load(open(os.path.join(
        ROOT, "output", meta["folder"], "data",
        f"player_{meta['player_id']}.json"), encoding="utf-8"))
    pchildren = {str(x) for x in
                 ((cache.get("characters", {}).get(str(meta["player_id"]), {})
                   .get("family", {}) or {}).get("child") or [])}
    offenders = [cid for cid in pchildren
                 if (profs.get(cid) or {}).get("siblings")
                 or (profs.get(cid) or {}).get("father")]
    check("子女档案无兄弟姊妹/父(主角)", not offenders, offenders[:5])
    held = " ".join((snap.get("facts", {}).get("secrets") or {}).get("held") or [])
    check("科举舞弊写主考与级别", "主持的乡试中舞弊" in held or not held, held)
    feuds = " ".join(e for fd in (facts.get("house_feuds") or []) for e in fd["events"])
    check("恩怨史无裸键、有重建句", "MAX_RECURSIVE_DEPTH" not in feuds, feuds[:80])


# ---------------------------------------------------------------------------
# C 菲利普4 (v30) 传输面断言 — 与家族无关, 任何快照都可跑
# ---------------------------------------------------------------------------

# 缺料按语 (提示词与事实层一律不得出现; 见 修复方案_菲利普4.md 问题4)
_ABSENCE_RE = re.compile(
    r"资料未载|资料不载|资料未提供|资料不足|史无可考|史料不详|"
    r"族属不详|信仰不详|官制不详|特质不详|（无[^）]{1,8}记录）")
# 游戏 UI 口语战绩词 (问题3)
_UI_WORD_RE = re.compile(r"打了胜仗|吃了败仗")
# v52 (问题6, 用户拍板「直接删」): 特质轨道档位序数词 —— 游戏无此术语
# (游戏概念只有「特质路线 / 特质经验」), 提示词与事实层一律不得出现
_TRAIT_LEVEL_WORD_RE = re.compile(r"[一二三四五六七八九十\d]阶")
# v52 (问题3): 公主/王子称号不得叠「王国/帝国」层级词; 亦不得出现双重后缀
_PRINCE_TIER_RE = re.compile(r"(王国|帝国)(公主|王子|皇女|皇子|郡主|公女)")
_PRINCE_DOUBLE_RE = re.compile(r"帝国国|帝国帝国|王国国|王国王国")
# 男性官职词 (女性持有者的称谓不得落在这些词上; 问题9)
# v60: 判据改用「同一称谓里该词之前出现过『女』字」—— 旧写法 `(?<!女)`
# 只回看一个字, 于是游戏自己的女性变体词「女大酋长」被误判 (崔佛档
# 15179 埃尔梅辛达即此); 而「松恩伯爵」「不来梅公爵」这类真阳性照旧命中。
_MALE_WORD_RE = re.compile(r"(伯爵|公爵|国王|男爵|酋长|皇帝)")
_FEMALE_MARK = "女"


def _male_word_offender(office):
    """女性称谓里是否含男性官职词 (带「女」标记的女性变体词不算)。"""
    off = str(office or "")
    for m in _MALE_WORD_RE.finditer(off):
        if _FEMALE_MARK not in off[:m.start()]:
            return m.group(1)
    return ""


def _surface(snap):
    fact = snap["shared"] + "\n" + "\n".join(
        "\n".join(v.values()) if isinstance(v, dict) else str(v)
        for v in snap["blocks"].values())
    instr = "".join(f"{m['system']}\n{m['user']}"
                    for m in snap["messages"].values())
    return fact, instr


def group_c(snap_path):
    print(f"[C] v30 传输面 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    facts = snap["facts"]
    meta = snap.get("meta") or {}
    fact_surface, instr = _surface(snap)
    surface = fact_surface + instr

    bad = _ABSENCE_RE.findall(surface)
    check("无缺料按语 (资料未载/不详/无X记录)", not bad, bad[:5])
    lv = _TRAIT_LEVEL_WORD_RE.findall(surface)
    check("无特质档位序数词 (一阶/二阶…)", not lv, lv[:5])
    ui = _UI_WORD_RE.findall(surface)
    check("无游戏口语战绩词 (打了胜仗/吃了败仗)", not ui, ui[:5])
    # 「无共通语」只在程序真判定为不通语时才可出现 (问题10)
    if "无共通语" not in fact_surface:
        check("事实面无不通语 → 提示词也不提「无共通语」",
              "无共通语" not in instr)
    else:
        check("「无共通语」有事实依据", "无共通语" in fact_surface)
    # 女性持有者的官职词
    offenders = []
    for cid, rec in (facts.get("characters") or {}).items():
        if not rec.get("female"):
            continue
        label = rec.get("label") or ""
        off = rec.get("office") or ""
        if off and _male_word_offender(off):
            offenders.append((cid, label))
    check("女性无男性官职词", not offenders, offenders[:4])
    # 献祭门: 教义参数表可用 (问题12)
    ten = L.doctrines_granting("human_sacrifice_active")
    check("人祭教义表可用 (doctrines_granting)", bool(ten), sorted(ten))

    # 问题6: 时间线不得再有同一事件的正反两方冗余行
    tl = facts.get("timeline") or []
    byday = {}
    for e in tl:
        byday.setdefault(e.get("date"), []).append(e)
    dup = []
    for d, es in byday.items():
        for i in range(len(es)):
            for j in range(i + 1, len(es)):
                try:
                    if F._mirror_partner(es[i], es[j]):
                        dup.append((d, es[i].get("type"), es[j].get("type")))
                except Exception:
                    pass
    check("时间线无镜像成对行 (战争/战役/刑虐/头衔/出生)", not dup, dup[:4])

    # 问题5: 同一被囚者的入狱与获释不得分立两行。
    # v32 起被囚句形态是「{监禁者}囚禁{被囚者}，…(缘由)。」——旧判据还在找
    # v32 前的「X为Y所囚。」, 故 inpr 恒空、断言永远 PASS 而实际什么都没检查
    # (v42 §3.1 实测)。v42 改为按现形态判定:
    #   ① 释放/越狱/处决/死于狱中一律写在囚禁行**之内**, 不得另有裸「X获释。」行;
    #   ② 每条囚禁行必须带一个收口 (获释/越狱/没为奴隶/处决/死于狱中/未见释放)。
    inpr, rel = [], []
    # v63 (问题1): 入狱行句首动词不再是恒定的「囚禁」—— 有硬证时写「于战阵俘获」
    # 「劫掠中掳走」(或「拘押」), 故判据按**动词族**匹配; 「囚禁」仍是判不出方式时
    # 的默认词形。
    _TAIL_RE = re.compile(
        r"，(.+?)(?:囚禁|于战阵俘获|劫掠中掳走|拘押|以摄政之权拘押)"
        r"(.+?)，(?P<tail>.*?)[。]$")
    for e in tl:
        t = e.get("text") or ""
        m = _TAIL_RE.search(t)
        if m:
            inpr.append((m.group(2), m.group("tail")))
        m2 = re.search(r"，([^，]+?)获释。$", t)
        if m2 and not _TAIL_RE.search(t):
            rel.append(m2.group(1))
    check("入狱与获释已合并 (无同一人分列两行)", not rel, rel[:4])
    # v55: 收口词扩到全部出狱缘由 (改信/交出牵制/放弃宣称/纳赎/驱逐/强征/出家/受刑;
    # 「获释」是「改信获释」等的子串, 故只需另列非「获释」结尾者)。
    # v60 (问题4): 「此后一直未见释放」改为以本档为界的「至{末档|日期}仍在押」
    # (旧措辞把「本传数据窗口内在押」写成无限期断言), 故收口词随之更新。
    _TAIL_OK = ("获释", "越狱", "没为奴隶", "处决", "死于狱中", "仍在押",
                "遭驱逐", "遭强征入仕", "被迫出家获释", "受刑获释",
                # 热修 (2026-09-24): 食人硬证优先于「处决」, 囚期以吃掉收口
                "被其吃掉")
    bad_tail = [v for v, tail in inpr
                if not any(w in tail for w in _TAIL_OK)]
    check("囚禁行皆带出狱/死亡收口", not bad_tail, bad_tail[:4])
    # 热修 (2026-09-24): 囚期死亡收口与死者名录**同源** —— 名录里写「吃掉」的人
    # (Mod「食人赋能」的遗骨硬证), 年表不得再写笼统的「处决」。旧稿两处矛盾:
    # 唐文举 895.1.14 入狱行写「6个月后处决」, 同一个人在同篇名录里写「被其吃掉」。
    # v78 (问题1) 收紧判据: 旧稿按「死句里出现『吃掉』二字」收人, 而**随机处决池**
    # 里也有一款「砍头后吃掉」(style.EXECUTION_OPTIONS 的 devour 档, 见 style.py:1086),
    # 于是被斩首的普通处决者也进了这个集合 —— 年表行写「处决」(正确) 反而被判违规
    # (实测菲利普2: 871.2.7 克约特弗、893.12.3 文室房典 等 5 行)。现只认**硬证**
    # 措辞「，被其吃掉」——随机池那款的文本是「，被其砍头后吃掉」，不会误命中。
    _EATEN_TXT = f"，被其{style.EXECUTION_DEVOUR_BONE[1]}，"
    _eaten = {str(e.get("name") or "").strip()
              for e in (facts.get("killed") or [])
              if _EATEN_TXT in str(e.get("death") or "")}
    _eaten.discard("")
    # v78 (问题1, D2): 折收集群行使本判据必须**按名字定位** —— 一行里可能既有
    # 「5人…被其吃掉」又有「1人…处决」(同一天同监禁者的一簇人结局各异),
    # 旧判据「行里出现名字 且 行里有『处决』」会把与处决无关的被吃者一起报出来。
    # 现只取名字**之后**、到下一个顿号/句号为止的片段判。
    _clash = []
    for v, tail in inpr:
        for nm in _eaten:
            if not nm or nm not in v:
                continue
            seg = re.split(r"[、。]", v.split(nm, 1)[1], 1)[0]
            if "处决" in seg:
                _clash.append((v, tail))
                break
    check("被吃者不在年表里写成「处决」(与名录同源)", not _clash, _clash[:3])

    # 问题7: 同日而死的血亲已合并为一条
    killed = facts.get("killed") or []
    cache_p = os.path.join(ROOT, "output", meta["folder"], "data",
                           f"player_{meta['player_id']}.json")
    pcache = json.load(open(cache_p, encoding="utf-8")) \
        if os.path.isfile(cache_p) else {}
    pchars = pcache.get("characters") or {}

    def _kin(e, key):
        fam = (pchars.get(str(e.get("id"))) or {}).get("family") or {}
        return {int(x) for x in (fam.get(key) or [])
                if isinstance(x, int) or str(x).isdigit()}

    dup_kin = []
    for i in range(len(killed)):
        for j in range(i + 1, len(killed)):
            a, b = killed[i], killed[j]
            if a.get("death") and b.get("death") and \
                    a.get("death_date") != b.get("death_date"):
                continue
            if _kin(a, "father") & _kin(b, "father") or \
                    _kin(a, "mother") & _kin(b, "mother"):
                dup_kin.append((a.get("name"), b.get("name")))
    check("刺客列传同日血亲已合并", not dup_kin, dup_kin[:4])

    # 问题8: 刺客列传每块内**凶手位**的主角全称谓 ≤1 次 (仅篇首点名句)。
    # v42: 旧判据「按任一非刺客块的总计数扣减」在年表不再重复主角头衔之后失效
    # (扣减数从数十降到 3, 于是把起义句/亲缘句里的主角名也算成重复点名)。
    # 现按**凶手位形态**计数: 「（被|死于|为）X」「X谋杀/处决/烧死…」——
    # 篇首「皆死于X之手」是唯一允许的一次, 其余死句一律已缩为「其」。
    plabel = ((facts.get("protagonist") or {}).get("label") or "").strip()
    if plabel:
        blocks = snap.get("blocks") or {}
        _kill_use = re.compile(
            r"(?:被|死于|为)" + re.escape(plabel)
            + r"|" + re.escape(plabel)
            + r"(?:谋杀|处决|烧死|毒杀|暗杀|打死|杀死|屠戮)")
        over = []
        for key, val in blocks.items():
            if not key.startswith("assassins"):
                continue
            txt = "\n".join(val.values()) if isinstance(val, dict) else str(val)
            n = len(_kill_use.findall(txt))
            if n > 1:
                over.append((key, n))
        check("刺客列传每块凶手称谓 ≤1 次 (凶手位计数)", not over, over[:3])


def group_v36(snap_path):
    """v36 六问题（周氏2）传输面断言：称谓体系 / 头衔材料下限 / 朝廷职位。"""
    print(f"[V36] 周氏2 六问题 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    meta = snap.get("meta") or {}
    if meta.get("player_id") != 38670:
        print(f"  SKIP 周氏2 专属断言 (player_id={meta.get('player_id')})")
        return
    facts = snap.get("facts") or {}
    prot = facts.get("protagonist") or {}
    blocks = snap.get("blocks") or {}
    txt = snap.get("shared", "") + "\n" + "\n".join(
        "\n".join(v.values()) if isinstance(v, dict) else str(v)
        for v in blocks.values())

    # [1] 裸层级词不成称谓 → 起义领袖出词 (用户拍板5)
    #    判据按 killed 条目的 office 字段取 — 死者名本身的姓可能是「王」(王伯玉),
    #    文本正则分不出「姓王」与「裸层级词+名」。
    bare = {"王", "公", "侯", "伯", "公爵", "伯爵", "男爵", "国王", "皇帝", "郡王"}
    bad = [(e.get("name"), e.get("office")) for e in (facts.get("killed") or [])
           if (e.get("office") or "") in bare]
    check("死者官称无裸层级词 (王/公爵…)", not bad, bad[:4])
    check("起义领袖出词", "农民起义领袖" in txt)

    # [2] 皇女/皇子: 兄弟为当今皇帝 且 父亦为皇帝 (用户拍板1)
    check("情人带皇女称号", "唐皇朝皇女李丽容" in txt)
    check("无裸名相恋句", "，李丽容与" not in txt)

    # [3] 男爵领不进头衔材料 (用户拍板5)
    check("历任无假男爵相位", "信安县令" not in txt and "吉昌男爵" not in txt)
    dom = prot.get("domain") or ""
    # 十年档 as_of 早于末档 → 直辖明细按设计不下发 (skip_detail), 空则跳过本条
    check("直辖清单无县/男爵领",
          (not dom) or not re.search(r"县|男爵", dom), dom)
    # [4] 庄园驻地州府 (问题4) — 无地/仅持庄园档该有
    # v41b (用户拍板2): 有地领主 (首要头衔为领地) 按定规**不出**庄园句 ——
    # 快照无 estate_name 即属正确行为, 跳过本条 (旧快照仍含该句, 照常断言)。
    if prot.get("estate_name"):
        check("档案含庄园驻地", "庄园在宾州" in txt)
    else:
        print("  SKIP 庄园驻地 (as_of 时为有地领主, 按 2026-09-15 定规不出庄园句)")

    # 以下仅**终传/在世传**面 (十年档 as_of 早于这些事件, 缺项属正确行为)
    if meta.get("decade"):
        print(f"  SKIP 终传专属断言 (十年档 decade={meta.get('decade')})")
        return
    # [5] 朝廷职司优先 + 最高头衔带「前」 (用户拍板2/6)
    check("边诚为前礼部尚书", "前礼部尚书边诚" in txt)
    check("无「江西尚书」合词", "江西尚书" not in txt)
    check("卸任衢州仍在历任", "卸任衢州" in txt)

    # [6] 主角获授朝廷职位 (用户拍板3) — 档案与朝局同时出词
    check("档案含朝廷职位(太师)",
          "朝廷职位" in txt and "太师" in txt and "唐皇帝李漼" in txt)
    realm = facts.get("realm") or {}
    check("朝局含主角朝廷职位", bool(realm.get("protagonist_offices")),
          realm.get("protagonist_offices"))

    # [7] 头衔得失句带授予者 / 去职 (用户拍板4)
    tl = " ".join((e.get("text") or "") for e in (facts.get("timeline") or []))
    check("受任句带授予者", "任命为衢州刺史" in tl, tl[:60])
    check("去职句用辞去", "辞去衢州刺史" in tl, tl[:60])


def group_v37(snap_path):
    """v37（问题8）断言：起义领袖带真实起事州府，死者不再被就近安放到主角家业。"""
    print(f"[V37] 起义起事地 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    meta = snap.get("meta") or {}
    if meta.get("player_id") != 38670:
        print(f"  SKIP 周氏2 专属断言 (player_id={meta.get('player_id')})")
        return
    facts = snap.get("facts") or {}
    killed = facts.get("killed") or []
    # 判据按「凡带起义领袖称谓者皆须有起事州府」取 — 十年档 as_of 截断后死者更少,
    # 用绝对条数会误报 (v37 初版即此错)。
    leaders = [e for e in killed if "农民起义领袖" in (e.get("label") or "")]
    no_base = [e.get("name") for e in leaders
               if not (e.get("uprising") or {}).get("base")]
    check("每名起义领袖死者带起事州府", len(leaders) >= 5 and not no_base,
          (len(leaders), no_base[:4]))
    bad_line = [e.get("name") for e in leaders
                if "起于" not in (e.get("uprising_line") or "")]
    check("起事独立行含「起于」", not bad_line, bad_line[:4])
    misplaced = [(e.get("name"), (e.get("uprising") or {}).get("base"))
                 for e in leaders if (e.get("uprising") or {}).get("base") == "宾州"]
    check("起事州府非主角家业所在", not misplaced, misplaced[:4])
    wby = [e for e in killed if e.get("name") == "王伯玉"]
    check("王伯玉由起义头衔升为领袖",
          bool(wby) and "农民起义领袖" in (wby[0].get("label") or ""),
          (wby[0].get("label") if wby else None))
    # 刺客列传文本不得再把人放进宾州 (扣掉各篇共有的前缀行)
    blocks = snap.get("blocks") or {}
    sample = ""
    for k, val in blocks.items():
        if not k.startswith("assassins"):
            sample = "\n".join(val.values()) if isinstance(val, dict) else str(val)
            break
    shared = sample.count("宾州")
    over = []
    for k, val in blocks.items():
        if not k.startswith("assassins"):
            continue
        t = "\n".join(val.values()) if isinstance(val, dict) else str(val)
        if t.count("宾州") > shared:
            over.append((k, t.count("宾州") - shared))
    check("刺客列传无「宾州」人物句", not over, over[:3])
    assassins = "\n".join(
        "\n".join(v.values()) if isinstance(v, dict) else str(v)
        for k, v in blocks.items() if k.startswith("assassins"))
    check("开篇名录带起事州府", assassins.count("起事") >= len(leaders),
          (assassins.count("起事"), len(leaders)))


def group_v39(snap_path):
    """v39（诺兰测试集三问题）断言：档位词叠词 / 宝物 as_of 归属 / 性事面收口。

    判据全部取自快照传输面 (facts + blocks), 不需要熔件:
      1. `protagonist.status` 不得出现「虔诚虔诚」(piety_level_2 =「虔诚信者」曾与标签拼接);
      2. 十年档里每件宝物的流转年份都不得晚于 as_of 年 (归属须为该时期前已归本宗族);
      3. v59 起性事只在好友/仇人列传里用 —— 秘密篇不得再有「强迫之事如下」块,
         公开年表 (facts.timeline) 里不得出现性事三档的句面
         (旧断言「强迫之事事实行用直白体位词」随该块撤下而改写)。
    """
    print(f"[V39] 诺兰三问题 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    meta = snap.get("meta") or {}
    pid = meta.get("player_id")
    as_of = facts.get("as_of") or meta.get("as_of")
    # [1] 档位词叠词
    st = (facts.get("protagonist") or {}).get("status") or ""
    check("档位词无叠词", "虔诚虔诚" not in st, st)
    # [2] 宝物 as_of 归属
    if as_of:
        try:
            ao_y = int(str(as_of).split(".")[0])
        except ValueError:
            ao_y = None
        if ao_y:
            late = []
            for line in facts.get("family_artifacts") or []:
                for m in re.finditer(r"(\d{3,4})年", line):
                    if int(m.group(1)) > ao_y:
                        late.append((line.splitlines()[0][:24], m.group(1)))
            check(f"宝物不晚于 as_of {ao_y}", not late, late[:4])
            # 诺兰专属: 第一个十年 (as_of=1077) 主角尚无任何名望级宝物
            if pid == 62045 and ao_y <= 1080:
                check("诺兰第一个十年无《宝物志》",
                      not (facts.get("family_artifacts") or []),
                      facts.get("family_artifacts"))
    # [3] 强迫之事措辞 —— v59 (问题2) 起该块已撤下 (性事只在好友/仇人列传里用)。
    # 本组改为断言: 秘密篇里**不得**再出现「强迫之事如下」, 且时间线 (公开年表)
    # 里不得出现性事三档的句面 (自愿/半推半就/强迫)。
    blocks = snap.get("blocks") or {}
    sec = "\n".join(
        "\n".join(v.values()) if isinstance(v, dict) else str(v)
        for k, v in blocks.items() if k.startswith("secrets"))
    check("强迫之事块已撤下 (v59)",
          "强迫之事如下" not in sec, sec[:200])
    _tl = [e.get("text") or "" for e in (facts.get("timeline") or [])]
    # 只取性事记忆句面专有的词, 避开剧情正文里的「强迫」(如「强迫改信」)
    _sexwords = ("性交", "肛交", "口交", "半推半就", "同房", "有私情")
    _bad = [t for t in _tl if any(w in t for w in _sexwords)]
    check("公开年表无性事行 (v59)", not _bad, _bad[:3])


def group_v40(snap_path):
    """v40（性病传播）断言：传输面里「谁把病传给了谁」的形态。

    判据全部取自快照 (facts.timeline + blocks), 不需要熔件:
      1. 凡出现「…把X传染给了Y。」或「…染上X。」的行, 病名必须是**游戏显示名**
         (本地化 trait_lovers_pox / trait_great_pox 等), 且行首带年份;
      2. 这些行不得出现占位称谓 (「某人」);
      3. 《阴私录》「疾病传染如下」块内的每一行都必须同时在时间线里 (同源同格式)。
    """
    print(f"[V40] 性病传播 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    table = L.table()
    names = set()
    for k in ("trait_lovers_pox", "trait_great_pox", "trait_early_great_pox",
              "disease_lovers_pox", "disease_great_pox"):
        v = L.loc(table, k)
        if v and not v.startswith(("$", "[")):
            names.add(v.rstrip("。"))
    tl = [e.get("text") or "" for e in (facts.get("timeline") or [])]
    blk = []
    for v in (snap.get("blocks") or {}).values():
        for s in (v.values() if isinstance(v, dict) else [v]):
            blk += [ln for ln in str(s).splitlines()]
    # v58: 允许「YYYY年M月D日，…」的整日行与行首缩进 (家室档案的行带两个空格;
    # 旧正则只认行首「YYYY年，」→ 这些行常年 FAIL, 属既有误报)。
    pat = re.compile(r"^\s*(\d{3,4})年(\d{1,2}月\d{1,2}日)?，(.+)$")
    rows = [ln for ln in (tl + blk)
            if ("传染给了" in ln or re.search(r"染上[^。]{1,12}。", ln))]
    check("病名为游戏显示名",
          all(any(n and n in ln for n in names) for ln in rows), rows[:3])
    check("传播行带年份", all(pat.match(ln) for ln in rows), rows[:3])
    check("无占位称谓", all("某人" not in ln for ln in rows), rows[:3])
    dis = list((facts.get("secrets") or {}).get("disease") or [])
    check("《阴私录》疾病行同源于时间线",
          all(x in tl for x in dis), dis[:3])


def group_v41(snap_path):
    """v41（诺兰八问题）断言：传输面里可见的程序端改动。

    判据全部取自快照 (facts + blocks), 不需要熔件:
      1. `titles_held` 的阶段行带**取得方式** (攻取/夺得/承袭/创建/受任…),
         且不再出现「年末档日期」而非事件日 (1086 而非 1087);
      2. `secrets.carnal_opinions` 默认不下发 (config `carnal_opinions` 关闭);
      3. `secrets` 的牵制块**无**「…的牵制如下：」标题行 (v41 问题8);
      4. 血统类隐事主题点名实父 (「实父为…」), 不再是裸「血统有争」;
      5. 宗支句不写「主支」;
      6. 共治者身份句 (有 diarchy 记录时) 含「共治」;
      7. 政体词随时点变: 同一人物在封建期档不得出现行政制专有词
         (军区/分区/将军/督军) —— 诺兰 1087–1094 为封建制。
    """
    print(f"[V41] 诺兰八问题 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    meta = snap.get("meta") or {}
    pid = meta.get("player_id")
    as_of = facts.get("as_of") or meta.get("as_of")
    p = facts.get("protagonist") or {}
    # 快照新鲜度 (v41): schema<2 的旧快照不含本轮新键, 本组对它不适用 ——
    # 整组 SKIP (而非误报 FAIL); 需用 tools/tests/snap.py 重建该快照。
    if int(snap.get("schema") or 1) < 2:
        print("  SKIP 快照早于 v41 改动 (schema<2), 请用 tools/tests/snap.py 重建")
        return
    # [1] 历任带取得方式
    th = p.get("titles_held") or ""
    if pid == 62045 and as_of and str(as_of).startswith(("1087", "1097", "1107")):
        check("[1] 历任含头衔取得方式",
              any(w in th for w in ("攻取", "夺得", "自", "承袭", "创建", "开创", "重建", "受任")),
              th)
        check("[1] 夺位日用事件日而非快照日",
              "1086" in th and "1087年任" not in th, th)
    # [2] carnal_opinions 默认关
    check("[2] carnal_opinions 不下发",
          not (facts.get("secrets") or {}).get("carnal_opinions"),
          (facts.get("secrets") or {}).get("carnal_opinions"))
    # [3]+[4] 隐事块
    blocks = snap.get("blocks") or {}
    sec_txt = "\n".join(
        str(s) for v in blocks.values()
        for s in (v.values() if isinstance(v, dict) else [v]))
    check("[3] 牵制块无「如下：」标题行",
          "牵制如下" not in sec_txt,
          [ln for ln in sec_txt.splitlines() if "牵制如下" in ln][:2])
    check("[4] 血统类隐事点名实父",
          ("血统有争" not in sec_txt) or ("实父为" in sec_txt),
          [ln for ln in sec_txt.splitlines() if "血统有争" in ln][:2])
    check("[5] 宗支句不写主支", "主支" not in sec_txt,
          [ln for ln in sec_txt.splitlines() if "主支" in ln][:2])
    # [7] 封建期档的官职称谓不得用行政制专有词。
    # 判据**只取称谓位置**: 逐人(person_label brief)与 HRE 封臣的层级词 ——
    # 全文搜「将军/分区」会误报地名 (「1067年驻卡利波利斯分区」是地名,
    # 「裴罗将军城」是城名), 那不是官职称谓。
    if pid == 62045 and as_of:
        try:
            ao_y = int(str(as_of).split(".")[0])
        except ValueError:
            ao_y = None
        if ao_y and ao_y <= 1090:
            f = _facts_from_snap(snap)
            if f is not None:
                bad = []
                for cid in (38142, 36657, 36664, 36462, 36284,
                            pid):
                    lab = f.person_label(cid, date=as_of, style="brief") or ""
                    if any(w in lab for w in ("将军", "督军", "军区",
                                              "分区长", "分区")):
                        bad.append(lab)
                check(f"[7] 封建期 {ao_y} 档称谓无行政制词", not bad, bad[:3])
    # [8] 政体变更链 (v41b 用户指正): 前身逐条相接 —— 1095 的前身是 1087 的
    # 封建制, 不是 1067 的冒险者; 旧实现取政体史第一条, 使「封建」整段消失。
    # [9] 有地领主不写庄园句 (用户拍板2: 只在无地/仅持庄园时写)。
    if pid == 62045 and str(as_of or "").startswith(("1097", "1107")):
        gc = p.get("government_change") or ""
        check("[8] 政体链含 1087 封建制那一句",
              "1087年" in gc and "改行封建制" in gc, gc)
        check("[8] 1095 前身是封建制", "由封建制改行行政制" in gc, gc)
        check("[8] 不再「由冒险者改行行政」", "由冒险者改行行政" not in gc, gc)
        check("[8] 政体按 as_of 取 (本档=行政制)",
              p.get("government") == "行政制", p.get("government"))
        prof_txt = snap.get("shared", "") + "\n" + sec_txt
        check("[9] 有地领主档案无庄园句",
              not p.get("estate_name") and "庄园在" not in prof_txt,
              [ln for ln in prof_txt.splitlines() if "庄园" in ln][:2])
    print(f"[V41] 完成 ({os.path.basename(snap_path)})")


def group_v42(snap_path):
    """v42（诺兰六问题）断言：判据全部取**快照 + 同一目录的缓存**, 不载熔件。

      1. 隐事乱伦自然语言化: 无 `乱伦：` 标签式, 有 `与…乱伦`;
      2. 「自己」只指记录持有人: 家人近臣隐事 / 把柄行不得出现「与自己私通」
         「与自己乱伦」「实父为自己」(那三句的主语是家人, 不是主角);
      3. 阉割/致盲与释放同日合并: 逐条刑虐记忆都在囚禁行内结清, 且当日无独立刑虐行;
      4. 无须阉人无括注: 传输面不含「自幼」, beardless 行含「在成年前…阉割」;
      5. 年表主角不重复头衔: 大事年表/相关年表/朝局动态三块内不出现「职衔+主角名」,
         且主角名本身仍在 (点名未丢);
      6. 灭门专门死因落地: `death_eradicated` 者行含「连同全族被处决」;
      7. 有死无释的囚禁行以死亡收口 (不写「此后一直未见释放」);
      8. 终传主角档案非空职衔 (§3.6 卒日锚点修复的回归判据)。
    """
    print(f"[V42] 诺兰六问题 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    meta = snap.get("meta") or {}
    blocks = snap.get("blocks") or {}
    pid = meta.get("player_id")
    prot = facts.get("protagonist") or {}
    pname = prot.get("name") or ""
    office = prot.get("office") or ""
    if int(snap.get("schema") or 1) < 2:
        print("  SKIP 快照早于 v41 改动 (schema<2), 请用 tools/tests/snap.py 重建")
        return

    def _txt(v):
        return "\n".join(str(s) for s in
                         (v.values() if isinstance(v, dict) else [v]))

    all_txt = (snap.get("shared") or "") + "\n" + "\n".join(
        _txt(v) for v in blocks.values())
    # 年表类块: 键是请求名 (benji_mid…), 块名在**内层字典**里
    _TL_BLOCKS = ("大事年表", "相关年表", "朝局动态")
    tl_txt = "\n".join(
        str(v[bn]) for v in blocks.values() if isinstance(v, dict)
        for bn in _TL_BLOCKS if bn in v)
    # 时间线本体 (每事件一行, 不受各篇切片重复计数影响) —— [3]/[6]/[7] 用它
    tl_all = "\n".join(e.get("text") or "" for e in (facts.get("timeline") or []))

    # 缓存 (判据用) + 本篇窗口 (十年档只收 (as_of−10, as_of]) ——
    # 各条断言的期望值必须与窗口一致, 否则十年档会把窗口外的事件算成缺失
    cache_p = os.path.join(ROOT, "output", meta.get("folder") or "", "data",
                           f"player_{pid}.json")
    pcache = json.load(open(cache_p, encoding="utf-8")) \
        if os.path.isfile(cache_p) else {}
    pchars = pcache.get("characters") or {}
    prec = pchars.get(str(pid)) or {}
    as_of = facts.get("as_of") or meta.get("as_of")
    decade = facts.get("decade") or meta.get("decade")
    _lo = None
    if as_of and decade:
        try:
            _y = int(str(as_of).split(".")[0])
            _srcs = pcache.get("sources") or []
            _st = int(str(_srcs[0]).split(".")[0]) if _srcs else None
            _lo = f"{max(_y - 10, _st or (_y - 10))}.1.1"
        except (ValueError, TypeError):
            _lo = None

    def _in_win(d):
        """该日期是否落在本篇窗口内 (as_of=None → 全期)。"""
        if not d:
            return as_of is None
        if as_of and F.cl.date_key(str(d)) > F.cl.date_key(str(as_of)):
            return False
        if _lo and F.cl.date_key(str(d)) < F.cl.date_key(_lo):
            return False
        return True

    # [1] 乱伦主题自然化 (问题1)
    inc_lines = [ln for ln in all_txt.splitlines() if "乱伦" in ln]
    check("[1] 隐事无「乱伦：」标签式",
          not [ln for ln in inc_lines if "乱伦：" in ln],
          [ln for ln in inc_lines if "乱伦：" in ln][:2])
    check("[1] 乱伦主题为自然短语",
          not [ln for ln in inc_lines if "乱伦" in ln and "与" not in ln
               and "者" not in ln and "者（" not in ln],
          inc_lines[:2])
    # 期望值只看**本篇相关集** (与 _secrets_facts 同口径: 主角 + 家人近臣),
    # 否则全球任意角色的乱伦隐事都会让这条断言以为「本档应当有乱伦句」
    _scope = {int(k) for k in (facts.get("characters") or {}) if str(k).isdigit()}
    inc_in_win = [r for r in (pcache.get("secrets_history") or {}).values()
                  if isinstance(r, dict) and r.get("type") == "secret_incest"
                  and r.get("owner") in _scope and _in_win(r.get("first_seen"))]
    if pid == 62045 and inc_in_win:
        check("[1] 诺兰档出现「与…乱伦」句",
              bool(re.search(r"与[^，。；]{2,20}乱伦", all_txt)),
              inc_lines[:2])
    elif pid == 62045:
        print("  SKIP [1] 乱伦点名 (本篇窗口内无乱伦隐事)")

    # [2] 「自己」只指记录持有人 (问题2)
    sec = facts.get("secrets") or {}
    subj_other = "\n".join((sec.get("kinsmen") or []) + (sec.get("known") or []))
    bad_self = [w for w in ("与自己私通", "与自己乱伦", "实父为自己")
                if w in subj_other]
    check("[2] 家人/把柄行无「自己」误指", not bad_self, bad_self)
    if pid == 62045 and subj_other.strip():
        check("[2] 诺兰档家人隐事点名主角",
              "实父为邪魔克里斯托弗·诺兰" in subj_other
              or "与邪魔克里斯托弗·诺兰乱伦" in subj_other
              or "与邪魔克里斯托弗·诺兰私通" in subj_other,
              [ln for ln in subj_other.splitlines() if "诺兰" in ln][:2])
    elif pid == 62045:
        print("  SKIP [2] 家人隐事 (本篇窗口内无家人隐事)")

    # [3]/[4] 刑虐与释放同日合并 + 无须无括注 (问题3)
    pun_kinds = {}
    for m in prec.get("memories") or []:
        if str(m.get("type") or "") != "torturer_memory":
            continue
        kind = ""
        for v in m.get("vars") or []:
            if v.get("flag") == "type":
                kind = str(v.get("value") or "")
        if kind in ("castrated", "castrated_beardless", "blind", "blinded") \
                and _in_win(m.get("creation_date")):
            pun_kinds.setdefault(kind, []).append(str(m.get("creation_date")))
    n_pun = sum(len(v) for v in pun_kinds.values())
    tl_lines = tl_all.splitlines()
    merged = [ln for ln in tl_lines
              if ("遭阉割而获释" in ln or "遭剜目而获释" in ln
                  or ("在成年前被" in ln and "阉割" in ln))]
    check(f"[3] 窗口内阉/盲记忆 {n_pun} 条皆在囚禁行内结清",
          len(merged) == n_pun, f"记忆 {n_pun} 条, 合并行 {len(merged)} 条")
    # 同日不得再有独立刑虐行
    _d = re.compile(r"^(\d+年\d+月\d+日)")
    merged_days = {m.group(1) for m in (_d.match(ln.strip()) for ln in merged) if m}
    solo = [ln for ln in tl_lines
            if ("阉割了" in ln or "致盲了" in ln)
            and (m := _d.match(ln.strip())) and m.group(1) in merged_days]
    check("[3] 同日无独立刑虐行", not solo, solo[:3])
    check("[4] 无须阉人无括注", "自幼" not in all_txt,
          [ln for ln in all_txt.splitlines() if "自幼" in ln][:2])
    if pun_kinds.get("castrated_beardless"):
        check("[4] beardless 写「在成年前…阉割」",
              "在成年前" in all_txt and "终身无须" in all_txt,
              [ln for ln in all_txt.splitlines() if "终身无须" in ln][:2])

    # [5] 年表主角不重复头衔 (问题4; 含家族恩怨录 —— 用户拍板2 一并收口)
    _FLOOD_BLOCKS = ("大事年表", "相关年表", "朝局动态", "家族恩怨")
    flood_txt = "\n".join(
        str(v[bn]) for v in blocks.values() if isinstance(v, dict)
        for bn in _FLOOD_BLOCKS if bn in v)
    if office and pname:
        flood = [ln for ln in flood_txt.splitlines()
                 if f"{office}{pname}" in ln]
        check(f"[5] 年表/恩怨录无「{office}{pname}」", not flood, flood[:2])
    check("[5] 年表仍点名主角",
          (not pname) or pname in tl_txt
          # v44: 传主改名 (私生女别立家族/家族改名) 后, 本篇名与事件当日的名不同形
          # (1133 篇作「弗兰肯阿德尔海德」, 1123 年的事件作「阿德尔海德·冯·亚琛」),
          # 故按**给定名**再判一次 —— 这条断言的本意是「传主没被匿名掉」
          or (prot.get("name_zh") or "") in tl_txt,
          [ln for ln in tl_lines[:3]])

    # [6] 灭门专门死因 (问题5)
    dead_names = {r.get("name_full") for r in pchars.values()
                  if (r.get("death") or {}).get("date") and r.get("name_full")}
    dead_names.discard("")

    def _has_record(dead_x):
        return any(dead_x == nm or dead_x.endswith(nm) for nm in dead_names)

    erad = [c for c, r in pchars.items()
            if ((r.get("death") or {}).get("reason") == "death_eradicated"
                and _in_win((r.get("death") or {}).get("date")))]
    if erad:
        check("[6] 灭门死因「连同全族被处决」见于年表",
              "连同全族被处决" in tl_all,
              [ln for ln in tl_lines if "连同全族被处决" in ln][:2])
    else:
        print("  SKIP [6] 本篇窗口内无 death_eradicated 死者")
    gen = []
    for ln in tl_lines:
        m = re.search(r"的(?:仇人|死敌|友人|挚友|亲属|情人|灵魂伴侣)"
                      r"([^，。]{1,30})去世。", ln)
        if m and _has_record(m.group(1)):
            gen.append(ln)
    check("[6] 有死亡记录者不写成通用「…去世」", not gen, gen[:3])

    # [7] 有死无释的囚禁以死亡收口 (问题6)
    imp_by_victim = {}
    for m in prec.get("memories") or []:
        if str(m.get("type") or "") != "imprisoned_other":
            continue
        v = (m.get("participants") or {}).get("imprisoned")
        if isinstance(v, int):
            imp_by_victim.setdefault(v, []).append(
                str(m.get("creation_date") or ""))
    open_names = []
    for cid, r in pchars.items():
        dd = r.get("death") or {}
        dates = imp_by_victim.get(int(cid)) if str(cid).isdigit() else None
        if not dd.get("date") or not dates:
            continue
        first = min(dates, key=F.cl.date_key)
        if F.cl.date_key(str(dd["date"])) < F.cl.date_key(first):
            continue
        if any(str(mm.get("type") or "") in ("released_from_prison_memory",
                                            "escaped_from_prison_memory")
               for mm in r.get("memories") or []):
            continue
        if any(iv.get("to") and F.cl.date_key(str(iv["to"]))
               >= F.cl.date_key(first) for iv in (r.get("prison_history") or [])):
            continue
        nm = r.get("name_full") or ""
        if nm:
            open_names.append(nm)
    # v60 (问题4): 收句改为以本档为界 (「，至末档仍在押」), 旧措辞已废 ——
    # 有死无释者以死亡收口, 不得出现「未见释放」式无限期断言。
    stale = [ln for ln in tl_lines
             if "此后一直未见释放" in ln or "未见释放" in ln]
    bad_open = [ln for ln in stale if any(nm in ln for nm in open_names)]
    check(f"[7] 有死无释者 {len(set(open_names))} 名不再写「未见释放」",
          not bad_open, bad_open[:3])

    # [8] 终传主角档案带职衔 (§3.6)
    if not meta.get("as_of"):
        check("[8] 终传主角档案有职衔", bool(office), repr(prot.get("label")))
    print(f"[V42] 完成 ({os.path.basename(snap_path)})")


def _cjk_proj(s):
    """只留汉字与间隔号 —— 「同句重名」判据的投影。"""
    return "".join(ch for ch in str(s)
                   if "\u4e00" <= ch <= "\u9fff" or ch == "·")


def _longest_repeat(s, min_len=8, ratio=0.3):
    """一句话里出现两次的最长汉字串 (长度 ≥ min_len 且占全句汉字数 ≥ ratio)。

    用于捕捉「A试图谋杀A」「A给A戴了绿帽子」这类施受同名的退化句 —— 游戏侧
    `murder_attempt`/`cuckoldry` 两个 reason 把 TARGET_CHAR 传成 root, root 恰是
    施事者本人时两端就烘焙成同一角色 (见 Facts._rerender_feud_event 的 v43 注释)。
    普通句里 8 字以上的重复串极罕见, 再加占比门槛即不会误报。"""
    t = _cjk_proj(s)
    n = len(t)
    if n < min_len * 2:
        return ""
    best = ""
    for i in range(n):
        for j in range(i + min_len, n + 1):
            sub = t[i:j]
            if len(sub) > len(best) and sub in t[j:]:
                best = sub
    if best and len(best) >= min_len and len(best) / n >= ratio:
        return best
    return ""


def group_v43(snap_path):
    """v43（婚姻线系 / 宝物志跨篇 / 自指恩怨句）断言。

    判据全部取自快照 (facts + blocks), 不需要熔件:
      1. 婚姻线系: 凡「入赘婚」补注都是固定形态「（入赘婚）」(v51 简化: 与普通婚
         一样只写线系名); 诺兰档的四个女儿婚事必须判出, 主角自身两段婚事不得误判;
      2. 宝物志: 十年档不再重复前面十年写过的宝物; 部件宝物带「材质：」行且
         描述已清洗 (无 ONCLICK/TOOLTIP/格式码/裸键); 终传收全量;
      3. 家族恩怨录: 无施受同名句 (存档 change_reason 两端同人的退化条目已降级
         为族级对手方「{对方家族}族人」)。
    """
    print(f"[V43] 婚姻线系/宝物志跨篇/自指恩怨 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    meta = snap.get("meta") or {}
    pid = meta.get("player_id")
    as_of = facts.get("as_of") or meta.get("as_of")
    decade = meta.get("decade")
    blocks = snap.get("blocks") or {}
    all_text = "\n".join(
        "\n".join(v.values()) if isinstance(v, dict) else str(v)
        for v in blocks.values())
    for extra in (facts.get("protagonist") or {}, facts.get("genealogy") or []):
        all_text += "\n" + (json.dumps(extra, ensure_ascii=False)
                            if not isinstance(extra, str) else extra)
    lines = [ln.strip() for ln in all_text.splitlines() if ln.strip()]

    # ---- [1] 婚姻线系 ----
    matri = [ln for ln in lines if "入赘" in ln]
    # v92 (问题2): 现行形态是**动词**「结入赘婚」(成婚句) 与名单补注「，入赘」;
    # 历史快照里还有 v55 分句「，是入赘婚」、v51 短式括注「（入赘婚）」
    # 与更早的长式——各自都算合法, 但同一快照里只许出现一种。
    _VERB = re.compile(r"结入赘婚")
    _LIST = re.compile(r"，入赘(?=[，。；])")
    _NOW = re.compile(r"，是入赘婚")
    _SHORT = re.compile(r"（入赘婚）")
    _LONG = re.compile(r"（入赘婚：所生子女随母方，属[^（）]+）")
    bad_form = [ln for ln in matri
                if not (_VERB.search(ln) or _LIST.search(ln) or _NOW.search(ln)
                        or _SHORT.search(ln) or _LONG.search(ln))]
    check("[1] 入赘婚补注形态统一", not bad_form, bad_form[:3])
    kinds = sorted({"动词式" if _VERB.search(ln) else
                    "名单式" if _LIST.search(ln) else
                    "分句式" if _NOW.search(ln) else
                    "短式" if _SHORT.search(ln) else "长式" for ln in matri})
    check("[1] 同一快照只用一种入赘婚形态", len(kinds) <= 1, kinds)

    class _MatriStub:
        """marriage_lineality_note / marriage_verb 只用到这两个方法 →
        桩即可验现行形态。"""

        def wedding_date(self, a, b):
            return "1100.1.1"

        def is_matrilineal(self, a, b, after=None, before=None):
            return True

    note = F.Facts.marriage_lineality_note(_MatriStub(), 1, 2)
    check("[1] 名单补注现行为「，入赘」(v92 去「是入赘婚」)",
          note == "，入赘", note)
    verb = F.Facts.marriage_verb(_MatriStub(), 1, 2)
    check("[1] 成婚句动词现行为「结入赘婚」(v92)", verb == "结入赘婚", verb)
    arts = facts.get("family_artifacts") or []
    if pid == 62045:
        # 四桩入赘婚 (多萝特娅 1095 / 阿莱克西娅 1103 / 欧金尼娅 1108 / 阿德尔海德
        # 1114 / 尤塔 1108) 全部成婚之后才要求四桩齐备; 更早的十年档只查形态
        _y = 0
        try:
            _y = int(str(as_of).split(".")[0]) if as_of else 0
        except ValueError:
            _y = 0
        if (not as_of) or _y >= 1115:
            check(f"[1] 诺兰入赘婚判出 {len(matri)} 条 (四个女儿)", len(matri) >= 4,
                  matri[:2])
        else:
            print(f"  INFO [1] 本篇 as_of={as_of}, 入赘婚行 {len(matri)} 条 "
                  f"(只查形态)")
        # 主角自身两段婚事 (埃卡泰里妮 / 康斯坦恰) 均为普通婚 —— 只认成婚句与
        # 配偶行形态 (孙辈同名「克里斯托弗·诺兰」不算); v92 起「入赘」有动词式与
        # 名单式两种形态, 故按「该名之后紧跟入赘标记」判, 不逐字列举旧句式。
        _NEAR = re.compile(
            r"(康斯坦恰·皮雅斯特|倾国倾城埃卡泰里妮)[^，。；]{0,8}"
            r"(，入赘|结入赘婚|，是入赘婚|（入赘婚)")
        wrong = [ln for ln in matri if _NEAR.search(ln)]
        check("[1] 主角自身两段婚事不误判为入赘", not wrong, wrong[:2])
    else:
        print(f"  SKIP [1] 诺兰专属入赘断言 (player_id={pid})")

    # ---- [2] 宝物志跨篇去重 / 部件档 / 描述清洗 ----
    joined = "\n".join(arts)
    for bad in ("ONCLICK", "TOOLTIP", "\x15", "high "):
        check(f"[2] 宝物面无残留标记 {bad!r}", bad not in joined,
              [x for x in arts if bad in x][:2])
    if pid == 62045:
        if decade == 2 or (as_of and str(as_of).startswith("1087")):
            check("[2] 诺兰第2个十年仍是五件名望级",
                  len(arts) == 5 and all("名望级" in x for x in arts), arts)
        if as_of and str(as_of).startswith("1097"):
            check("[2] 诺兰第3个十年不重复已写宝物 (篇目省去)", not arts, arts)
        if as_of and str(as_of).startswith("1117"):
            check("[2] 第5个十年收头骨高脚杯", any("头骨高脚杯" in x for x in arts),
                  arts)
            check("[2] 第5个十年不再重复帝国皇冠/铁王冠",
                  not any("帝国皇冠" in x or "伦巴第铁王冠" in x for x in arts),
                  arts)
        if not as_of:
            check("[2] 终传收全量 (五件名望级 + 头骨高脚杯)",
                  sum("名望级" in x for x in arts) >= 5
                  and any("头骨高脚杯" in x for x in arts), arts)
        part = [x for x in arts if "材质：" in x]
        check("[2] 部件宝物带材质行且点名人物",
              all(("头骨" in x or "头颅" in x or "乳牙" in x) for x in part)
              if part else True, part[:2])
    else:
        print(f"  SKIP [2] 诺兰专属宝物断言 (player_id={pid})")

    # ---- [3] 自指恩怨句 ----
    events = []
    for h in facts.get("house_feuds") or []:
        events += list(h.get("events") or [])
    dupes = [(ln, _longest_repeat(ln)) for ln in events if _longest_repeat(ln)]
    check("[3] 恩怨录无施受同名句", not dupes, dupes[:2])
    pat = re.compile(r"(.{4,}?)试图谋杀\1")
    pat2 = re.compile(r"(.{4,}?)给\1戴了绿帽子")
    direct = [ln for ln in events if pat.search(ln) or pat2.search(ln)]
    check("[3] 无「A试图谋杀A」/「A给A戴绿帽子」形态", not direct, direct[:2])
    if pid == 62045:
        kuke = [ln for ln in events if "库克" in ln]
        if kuke:
            check("[3] 库克氏自指条目已降级为族级对手方",
                  any("库克氏族人" in ln for ln in kuke), kuke[:3])
        else:
            print("  SKIP [3] 本篇窗口内无库克氏恩怨")
    print(f"[V43] 完成 ({os.path.basename(snap_path)})")


def _dk(s):
    """'1138.1.1' → (1138, 1, 1) 便于比日期; 解析失败返回 (0, 0, 0)。"""
    try:
        p = [int(x) for x in str(s).split(".")[:3]]
        while len(p) < 3:
            p.append(1)
        return tuple(p)
    except (TypeError, ValueError):
        return (0, 0, 0)


def group_v44(snap_path):
    """v44（传主姓氏沿革 / 传主链 / 亲子字段 / 族属沿革 / 名字本地化）断言。

    判据取自快照 (facts + blocks), 不需要熔件:
      1. 家族沿革: 传主档案有「家格」句 (别立家族 + 改名), 【家族】/名号句取该篇
         截止日之值 (1118-1132 冯·亚琛, 1133 起 冯);
      2. 传主链: 有「承继」句且点名前代传主;
      3. 亲子字段: 女主档的子女进「子/女」行, 不出「法理父并非主角」这种反话;
      4. 族属沿革: 有「族属：」句且含两个文化; 早年篇的族属不取末档;
      5. 名字本地化: 传输面无拉丁字母人名 (`Matilda·萨伏依` 形态);
      6. gz 读取口: cache_lib 的两种后缀解析与透明打开。
    """
    print(f"[V44] 姓氏沿革/传主链/亲子/族属/译名 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    meta = snap.get("meta") or {}
    pid = meta.get("player_id")
    as_of = facts.get("as_of") or meta.get("as_of")
    p = facts.get("protagonist") or {}
    blocks = snap.get("blocks") or {}
    all_text = "\n".join(
        "\n".join(v.values()) if isinstance(v, dict) else str(v)
        for v in blocks.values())
    all_text += "\n" + json.dumps(p, ensure_ascii=False)
    lines = [ln.strip() for ln in all_text.splitlines() if ln.strip()]

    # ---- [6] 归档后缀读取口 (纯函数, 与快照无关, 只跑一次) ----
    if not globals().get("_V44_GZ_DONE"):
        globals()["_V44_GZ_DONE"] = True
        try:
            import cache_lib as cl
            check("[6] 边车路径随熔件后缀 (.json.gz → _idx.json.gz)",
                  cl.melt_index_path("melt_900_01_01.json.gz")
                  == "melt_900_01_01_idx.json.gz", "")
            check("[6] 三种后缀的边车候选都给出",
                  cl._melt_index_variants("melt_900_01_01.json.gz")
                  == ["melt_900_01_01_idx.json", "melt_900_01_01_idx.json.gz",
                      "melt_900_01_01_idx.json.xz"], "")
            check("[V49] 边车路径随 .json.xz (方案①)",
                  cl.melt_index_path("melt_900_01_01.json.xz")
                  == "melt_900_01_01_idx.json.xz", "")
            check("[V49] melt_stem 去压缩后缀",
                  (cl.melt_stem("a/melt_900_01_01.json.xz"),
                   cl.melt_stem("a/melt_900_01_01.json.gz"),
                   cl.melt_stem("a/melt_900_01_01.json"))
                  == ("a/melt_900_01_01.json",) * 3, "")
            import gzip as _gz
            import lzma as _lz
            # 沙箱/权限: 临时文件写在仓库内 (系统 temp 可能被拒)
            _tdir = os.path.join(ROOT, "_tmp_v44_gztest")
            os.makedirs(_tdir, exist_ok=True)
            try:
                gzp = os.path.join(_tdir, "melt_900_01_01.json.gz")
                with _gz.open(gzp, "wt", encoding="utf-8") as fp:
                    json.dump({"date": "900.1.1"}, fp)
                check("[6] load_melt 透明读 .json.gz",
                      (cl.load_melt(gzp) or {}).get("date") == "900.1.1", gzp)
                check("[6] melt_file_exists 找到 .gz",
                      cl.melt_file_exists(os.path.join(_tdir, "melt_900_01_01.json"))
                      == gzp, "")
                # v49 (方案①): .json.xz 同口径
                xzp = os.path.join(_tdir, "melt_901_01_01.json.xz")
                with _lz.open(xzp, "wt", encoding="utf-8") as fp:
                    json.dump({"date": "901.1.1"}, fp)
                check("[V49] load_melt 透明读 .json.xz",
                      (cl.load_melt(xzp) or {}).get("date") == "901.1.1", xzp)
                check("[V49] melt_file_exists 找到 .xz",
                      cl.melt_file_exists(os.path.join(_tdir, "melt_901_01_01.json"))
                      == xzp, "")
                check("[V49] open_melt_text 能读 .json.xz",
                      json.load(cl.open_melt_text(xzp)).get("date") == "901.1.1", "")
            finally:
                try:
                    import shutil as _sh
                    _sh.rmtree(_tdir, ignore_errors=True)
                except Exception:
                    pass
        except Exception as e:            # noqa: BLE001
            check("[6] 归档后缀读取口可用", False, repr(e))

    if pid != 16852591:
        print(f"  SKIP [1-5] 本节为诺兰女主档 (阿德尔海德) 专属 (player_id={pid})")
        print(f"[V44] 完成 ({os.path.basename(snap_path)})")
        return

    # ---- [1] 家族沿革 ----
    hh = p.get("house_history") or []
    check("[1] 传主档案有家格沿革句", bool(hh), hh)
    joined_hh = "；".join(hh)
    check("[1] 家格句含别立家族 (冯·亚琛)", "别立" in joined_hh and "冯·亚琛" in joined_hh,
          joined_hh)
    _y = 0
    try:
        _y = int(str(as_of).split(".")[0]) if as_of else 0
    except ValueError:
        _y = 0
    if (not as_of) or _y >= 1133:
        check("[1] 家格句含家族改名 (1133)", "家族改称冯氏" in joined_hh, joined_hh)
    if (not as_of) or _y >= 1146:
        check("[1] 家格句含宗族改名 (1146)", "宗族改称冯氏" in joined_hh, joined_hh)
    if (not as_of) or _y >= 1146:
        check("[1] 末档家族名为冯 (1146 起宗族亦为冯)",
              (p.get("house") or "").startswith("冯"), p.get("house"))
        check("[1] 末档名号带冯 (东方名序 冯X)", "冯" in (p.get("name") or ""),
              p.get("name"))
    elif (not as_of) or _y >= 1133:
        # 1133–1145: 家族已改称冯, 宗族仍是弗兰肯 —— 东方名序的姓取宗族名
        check("[1] 1133-1145 篇宗族名仍为弗兰肯 (游戏口径)",
              (p.get("house") or "").startswith("弗兰肯"), p.get("house"))
        check("[1] 1133-1145 篇分家为冯", "冯" in (p.get("house_branch") or ""),
              p.get("house_branch"))
    if as_of and _y <= 1132:
        check("[1] 早年篇族名为冯·亚琛", "冯·亚琛" in (p.get("name") or ""),
              p.get("name"))
        check("[1] 早年篇【家族】行不为诺兰 (沿革取值)",
              "诺兰" not in (p.get("house") or ""), p.get("house"))
    # 冻结首见值「诺兰」只允许以**当年正确的西方名序**出现 (1118.4.2 前的事件),
    # 不得再以东方名序的「诺兰X」形态出现
    check("[1] 全篇无「诺兰阿德尔海德」式旧名", "诺兰阿德尔海德" not in all_text, "")

    # ---- [2] 传主链 ----
    sc = p.get("succession") or []
    check("[2] 传主档案有承继句", bool(sc), sc)
    check("[2] 承继句点名前代传主克里斯托弗",
          any("克里斯托弗" in x for x in sc), sc)
    check("[2] 承继句带继位日 1117年6月19日",
          any("1117" in x for x in sc), sc)

    # ---- [3] 亲子字段 ----
    check("[3] 女主档子女进「子/女」行",
          bool(p.get("children_sons") or p.get("children_daughters")),
          (p.get("children_sons"), p.get("children_daughters")))
    check("[3] 女主档无「配偶另育有」反话", not p.get("wife_other_children"),
          p.get("wife_other_children"))
    bad = [ln for ln in lines if "法理父并非主角" in ln or "法理母并非主角" in ln]
    check("[3] 全篇无「法理父并非主角」句", not bad, bad[:2])
    # 本篇截止日前出生的子女都须在册 (骥才 1138.10.19 生, 早于本篇的不强求)
    _kids = p.get("children_sons") or ""
    _girls = p.get("children_daughters") or ""
    _expect = ["路德维希", "卡尔", "阿德尔海德"]
    if (not as_of) or _dk(as_of) >= _dk("1138.10.19"):
        _expect.append("骥才")
    check("[3] 子女行含该截止日前所生全部子女",
          all(k in _kids + _girls for k in _expect),
          (_kids, _girls, _expect))

    # ---- [4] 族属沿革 ----
    ch = p.get("culture_history") or ""
    if (not as_of) or _y >= 1132:
        check("[4] 有族属沿革句", "族属" in ch, ch)
        check("[4] 沿革含法兰克尼亚人与汉人", "法兰克尼亚人" in ch and "汉人" in ch, ch)
    else:
        # 1132 年前尚未改族属 —— 有沿革句反而错
        check("[4] 早年篇无族属沿革句", not ch, ch)
    if as_of and _y <= 1131:
        check("[4] 早年篇族属为法兰克尼亚人", p.get("culture") == "法兰克尼亚人",
              p.get("culture"))
    if (not as_of) or _y >= 1132:
        check("[4] 末档族属为汉人", p.get("culture") == "汉人", p.get("culture"))

    # ---- [5] 名字本地化 (Mod 英文不得进传输面) ----
    latin_name = re.findall(r"[A-Za-z]{3,}·", all_text)
    check("[5] 传输面无拉丁字母人名 (Mathilde/Marie 类)", not latin_name,
          sorted(set(latin_name))[:5])
    for bad_nm in ("Matilda", "Marry", "Freja"):
        check(f"[5] 无 Mod 英文名 {bad_nm}", bad_nm not in all_text, bad_nm)
    print(f"[V44] 完成 ({os.path.basename(snap_path)})")


_SCOPES = []


class _KinRecScope(F.KinScope):
    """记录版 KinScope (v45 断言用): 记下本板块实际加出的每处定语。

    档 A (点位: 名号句/要员名录/死者行) 走 `mark` → `tags`;
    档 B (行内插词: 年表/隐事/恩怨事件句) 走 `word_for` → `words`。
    v63: 档 B 记下**实际算词基准** —— 句中第三方人名按本行主语算 (不再一律按
    本篇传主), 故 `words` 存 (cid, 词, 基准人)。"""

    def __init__(self, subject=None):
        super().__init__(subject)
        self.tags = []          # 档 A: [(cid, 加定语后的整称谓)]
        self.words = []         # 档 B: [(cid, 定语词, 算词基准人)]
        _SCOPES.append(self)

    def mark(self, cid, base, facts, date=None):
        out = super().mark(cid, base, facts, date=date)
        if base and out != base:
            self.tags.append((cid, out))
        return out

    def word_for(self, cid, facts, subject=None):
        w = super().word_for(cid, facts, subject=subject)
        if w:
            self.words.append((cid, w, self.subject if subject is None else subject))
        return w


def group_v45(snap_path):
    """v45（亲缘定语）断言。

    判据三层:
      1. 纯函数: 长幼方向 / 前配偶不算 / 只标一次 / 家世行已写明者不再加 /
         传主本人不标 / 行内插词的确切位置与「已带亲缘词则不插」;
      2. 事实面: 用同目录缓存重建 Facts 后**重跑** `_article_facts` (记录版 scope),
         每处标注复算 `kin_word` 必须一致 (词必可判), 且确实落在本板块文本里;
      3. 素材可复现: 同一板块算两遍逐字相同。
    覆盖率、词频作 INFO 打印 (不 FAIL)。
    """
    print(f"[V45] 亲缘定语 ({os.path.basename(snap_path)})")
    import biography as bio

    # ---- [1] 纯函数: 长幼方向 (固定生年的假 cache) ----
    def _sib(birth_s, birth_c, female_c=False):
        return {"characters": {
            "1": {"birth": birth_s, "family": {"siblings": [2]}},
            "2": {"birth": birth_c, "female": female_c,
                  "family": {"siblings": [1]}}}}

    c = _sib("1100.1.1", "1090.1.1")
    check("[1] 年长同胞 → 兄长", F.kin_word(c, 1, 2) == "兄长", F.kin_word(c, 1, 2))
    c = _sib("1090.1.1", "1100.1.1", female_c=True)
    check("[1] 年幼同胞 → 妹妹", F.kin_word(c, 1, 2) == "妹妹", F.kin_word(c, 1, 2))
    c = _sib("", "")
    check("[1] 无生年 → 兄弟", F.kin_word(c, 1, 2) == "兄弟", F.kin_word(c, 1, 2))
    # 前配偶不算 (former_spouses 只在 family 里, 现配偶字段为空)
    c = {"characters": {"1": {"family": {"former_spouses": [2]}},
                        "2": {"family": {"former_spouses": [1]}}}}
    check("[1] 前配偶 → 不判", F.kin_word(c, 1, 2) == "", F.kin_word(c, 1, 2))
    # 词形两档
    c = {"characters": {"1": {"family": {"father": [2]}},
                        "2": {"family": {"child": [1]}}}}
    check("[1] 定语用双音节 (父亲)", F.kin_word(c, 1, 2) == "父亲", F.kin_word(c, 1, 2))
    check("[1] 旁称用单字 (父)", F.kin_word_short(F.kin_key(c, 1, 2)) == "父", "")

    # ---- [1] 纯函数: KinScope 名额与行内插词 ----
    class _FakeFacts:
        def __init__(self, index=None):
            self._index = index or {}

        def get(self, k, d=None):
            return self._index if k == "name_index" else d

        def name(self, cid, date=None):
            return {1: "主角甲", 2: "受试者乙"}.get(cid, "")

        def kin_word_for(self, cid, subject):
            return "兄长" if (cid, subject) == (2, 1) else ""

    ff = _FakeFacts()
    sc = F.KinScope(1)
    check("[1] 首见加定语", sc.mark(2, "受试者乙", ff) == "兄长受试者乙", "")
    check("[1] 再次不加", sc.mark(2, "受试者乙", ff) == "受试者乙", "")
    sc2 = F.KinScope(1).seed([2], ff)
    check("[1] 家世行已写明 → 点位不再加",
          sc2.mark(2, "受试者乙", ff) == "受试者乙", sc2.held)
    check("[1] 家世行已写明 → 行内也不插词", sc2.word_for(2, ff) == "", "")
    # 档 B: 行内插词的确切位置 (称谓整串之前) 与「行内已带亲缘词则不插」
    def _stub(index):
        d = {"_facts": ff}
        d.update(index)
        return d

    check("[1] 行内首见插在称谓前",
          bio._kin_tag_line(_stub({"name_index": {"1100年1月1日，受试者乙任宰相。":
                                                 [[2, "受试者乙"]]}}),
                            F.KinScope(1), "1100年1月1日，受试者乙任宰相。")
          == "1100年1月1日，兄长受试者乙任宰相。", "")
    check("[1] 行内已带亲缘词 → 不重复插",
          bio._kin_tag_line(_stub({"name_index": {"1100年1月1日，其兄受试者乙卒。":
                                                 [[2, "受试者乙"]]}}),
                            F.KinScope(1), "1100年1月1日，其兄受试者乙卒。")
          == "1100年1月1日，其兄受试者乙卒。", "")
    # 后缀命中 (下发时套了「日期，」前缀, 索引键只有句本体)
    check("[1] 带日期前缀的行也能命中",
          bio._kin_tag_line(_stub({"name_index": {"受试者乙任宰相。":
                                                 [[2, "受试者乙"]]}}),
                            F.KinScope(1), "1100年1月1日，受试者乙任宰相。")
          == "1100年1月1日，兄长受试者乙任宰相。", "")
    check("[1] 传主本人不标", F.KinScope(1).mark(1, "主角甲", ff) == "主角甲", "")

    if not os.path.isfile(snap_path):
        check("[2] 快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    f = _facts_from_snap(snap)
    if f is None:
        print("  SKIP [2-3] 无同目录缓存/熔件, 无法重跑板块")
        print(f"[V45] 完成 ({os.path.basename(snap_path)})")
        return
    meta = snap.get("meta") or {}
    data = os.path.join(ROOT, "output", meta.get("folder") or "", "data")
    cache_path = os.path.join(data, f"player_{meta.get('player_id')}.json")
    # 出词登记必须**按线程**分份: 板块期 `build_lead_messages` 走线程池并发,
    # 别人的出词混进本行就会把定语插错地方
    import threading
    _seen = {}

    def _work(tid):
        with f.log_names() as lg:
            for _i in range(50):
                f._log_label(1000 + tid, f"名{tid}")
            _seen[tid] = list(lg.items)

    _ths = [threading.Thread(target=_work, args=(t,)) for t in (1, 2)]
    for _t in _ths:
        _t.start()
    for _t in _ths:
        _t.join()
    check("[1] 出词登记按线程分开 (并发不串味)",
          sorted(_seen) == [1, 2]
          and all(len(v) == 50 and all(c == 1000 + tid for c, _l in v)
                  for tid, v in _seen.items()), _seen)
    try:
        cache = json.load(open(cache_path, encoding="utf-8"))
        import biography as bio
        facts = dict(snap.get("facts") or {})
        facts["_facts"] = f
        articles = bio.build_articles(facts, cache, {"max_tokens": 12800})
    except Exception as e:               # noqa: BLE001
        check("[2] 重建板块素材", False, repr(e))
        return

    # ---- [2] 重跑各板块, 记录标注 (每次 _article_facts 新建一个 scope) ----
    real = F.KinScope
    F.KinScope = _KinRecScope
    del _SCOPES[:]
    built = []                            # [(板块key, blocks, scope)]
    try:
        for a in articles:
            for sec in a["sections"]:
                key = f"{a['key']}_{sec['key']}"
                n0 = len(_SCOPES)
                blocks = bio._article_facts(facts, cache, a["key"], sec)
                here = _SCOPES[n0:]
                built.append((key, blocks, here[-1] if here else None))
    finally:
        F.KinScope = real

    n_tag, n_word, n_chars, words = 0, 0, 0, {}
    # 词表白名单 = 双音节定语词 ∪ 史传单字 (单一定义处见 facts.kin_texts)
    kin_ok = F.kin_texts()
    bad_word, bad_rep, bad_dup, bad_self, bad_in = [], [], [], [], []
    for key, blocks, sc in built:
        text = "\n".join(v for v in blocks.values() if isinstance(v, str))
        if sc is None:
            continue
        # 档 A (点位) + 档 B (行内) 合起来看「同一人每板块至多一次」
        cids = [cid for cid, _t in sc.tags] + [cid for cid, _w, _s in sc.words]
        if len(set(cids)) != len(cids):
            bad_dup.append((key, "同一人两次", sorted(cids)))
        for cid, out in sc.tags:
            n_tag += 1
            w = f.kin_word_for(cid, sc.subject)
            if not w or w not in kin_ok:
                bad_word.append((key, cid, out))
            if not w or not out.startswith(w) or len(out) <= len(w):
                bad_rep.append((key, cid, out, w))
            if not w:
                continue
            if out not in text:
                bad_in.append((key, out))
            if text.count(out) > 1:
                bad_dup.append((key, out, text.count(out)))
            words[w] = words.get(w, 0) + 1
            n_chars += len(w)
        for cid, w, _subj in sc.words:
            n_word += 1
            if not w or w not in kin_ok:
                bad_word.append((key, cid, w))
            # v63: 词必须能按**实际算词基准**复算 (句中第三方人名按本行主语算)
            elif f.kin_word_for(cid, _subj) != w:
                bad_rep.append((key, cid, w, f"基准{_subj}→"
                                f"{f.kin_word_for(cid, _subj)}"))
            if not w:
                continue
            if f"{w}" not in text:
                bad_in.append((key, f"档B {w}"))
            words[w] = words.get(w, 0) + 1
            n_chars += len(w)
        if sc.subject is not None and sc.subject in cids:
            bad_self.append((key, sc.subject))

    check("[2] 每处标注都能用同目录缓存复算 kin_word", not bad_rep, bad_rep[:3])
    check("[2] 标注词都在词表内", not bad_word, bad_word[:3])
    check("[2] 标注确实落在本板块文本里", not bad_in, bad_in[:3])
    check("[3] 同板块同一人最多标一次 (点位+行内)", not bad_dup, bad_dup[:3])
    check("[4] 从不标本篇传主", not bad_self, bad_self[:3])

    # ---- [3] 素材可复现: 同一板块算两遍逐字相同 ----
    if built:
        key0, blocks0, _sc0 = built[0]
        a0 = next(a for a in articles if key0.startswith(a["key"] + "_"))
        sec0 = next(s for s in a0["sections"]
                    if key0 == f"{a0['key']}_{s['key']}")
        blocks0b = bio._article_facts(facts, cache, a0["key"], sec0)
        check("[3] 同一板块算两遍逐字相同", blocks0 == blocks0b, key0)

    print(f"  INFO 本快照实加定语 {n_tag} 处 (点位) + {n_word} 处 (行内), "
          f"+{n_chars} 字符; 词频 "
          + "、".join(f"{k}×{v}" for k, v in sorted(words.items())))
    print(f"[V45] 完成 ({os.path.basename(snap_path)})")


def group_v45b():
    """v45b（中式亲属细分）断言：纯函数, 假缓存断言十个词族 + 血亲优先序 (序 A)。

    判据见 `docs/研究_v45b_中式亲属.md` §1.2（词表）/§2.1（顺序）。
    不需要快照 —— 这些全是 `kin_key` 的确定性判定。
    """
    print("[V45b] 中式亲属细分 (伯叔舅姑姨/侄甥/孙/堂表/公婆岳母/同胞配偶)")
    ch = {}

    def put(cid, **kw):
        ch[str(cid)] = dict(id=cid, **kw)

    put(1, female=False, birth="1150.1.1",
        family={"father": [10], "mother": [11], "child": [30, 31],
                "siblings": [40, 41, 45], "primary_spouse": [60]})
    put(10, female=False, birth="1120.1.1",
        family={"siblings": [20, 21, 22], "child": [1]})
    put(11, female=True, birth="1122.1.1",
        family={"siblings": [23, 24], "child": [1]})
    put(20, female=False, birth="1110.1.1", family={"child": [50]})   # 父之兄
    put(21, female=False, birth="1130.1.1")                           # 父之弟
    put(22, female=True, birth="1125.1.1", family={"child": [51]})    # 父之妹
    put(23, female=False, birth="1115.1.1", family={"child": [52]})   # 母之兄
    put(24, female=True, birth="1128.1.1")                            # 母之妹
    put(30, female=False, birth="1170.1.1", family={"father": [1], "child": [32]})
    put(31, female=True, birth="1172.1.1", family={"father": [1], "child": [33]})
    put(32, female=False, birth="1195.1.1", family={"father": [30]})
    put(33, female=True, birth="1196.1.1", family={"mother": [31]})
    put(40, female=False, birth="1140.1.1", family={"child": [43]})   # 兄
    put(41, female=True, birth="1160.1.1", family={"child": [44]})    # 妹
    put(45, female=True, birth="1135.1.1", family={"primary_spouse": [46]})
    put(43, female=False, birth="1165.1.1", family={"father": [40]})
    put(44, female=False, birth="1168.1.1", family={"mother": [41]})
    put(50, female=False, birth="1155.1.1", family={"father": [20]})
    put(51, female=False, birth="1145.1.1", family={"mother": [22]})
    put(52, female=True, birth="1152.1.1", family={"father": [23]})
    put(60, female=True, birth="1152.1.1",
        family={"father": [61], "mother": [62], "siblings": [63]})
    put(61, female=False, birth="1120.1.1")
    put(62, female=True, birth="1122.1.1")
    put(63, female=False, birth="1145.1.1")
    put(46, female=False, birth="1133.1.1", family={"primary_spouse": [45]})
    put(47, female=False, birth="1155.1.1",
        family={"siblings": [1], "primary_spouse": [48]})
    put(48, female=True, birth="1157.1.1", family={"primary_spouse": [47]})
    put(2, female=True, birth="1150.1.1", family={"primary_spouse": [70]})
    put(70, female=False, birth="1148.1.1",
        family={"father": [71], "mother": [72]})
    put(71, female=False, birth="1115.1.1")
    put(72, female=True, birth="1117.1.1")
    cache = {"characters": ch}

    def kw(cid, s=1):
        return F.kin_word(cache, s, cid)

    for cid, want, what in (
            (20, "伯父", "父之兄"), (21, "叔父", "父之弟"), (22, "姑母", "父之妹"),
            (23, "舅父", "母之兄"), (24, "姨母", "母之妹"),
            (43, "侄子", "兄之子"), (44, "外甥", "妹之子"),
            (32, "孙子", "子之子"), (33, "外孙女", "女之女"),
            (50, "堂弟", "伯父之子"), (51, "表兄", "姑母之子"), (52, "表妹", "舅父之女"),
            (61, "岳父", "妻之父"), (62, "岳母", "妻之母"),
            (46, "姐夫", "姊之夫"), (48, "弟媳", "弟之妻")):
        check(f"{what} → {want}", kw(cid) == want, kw(cid))
    check("夫之父 → 公公", kw(71, 2) == "公公", kw(71, 2))
    check("夫之母 → 婆婆", kw(72, 2) == "婆婆", kw(72, 2))
    # 序 A: 血亲压过姻亲 (妻之兄同时是姑母之子 → 表兄)
    ch["63"]["family"] = {"mother": [22]}
    check("妻之兄 ∧ 姑母之子 → 表兄 (血亲优先)", kw(63) == "表兄", kw(63))
    # 序 A: 1 度硬边压过旁系 (同胞之妻 ∧ 表亲 → 弟媳)
    ch["48"]["family"] = {"primary_spouse": [47], "mother": [11]}
    check("弟媳 ∧ 姨母之女 → 弟媳 (1 度优先)", kw(48) == "弟媳", kw(48))
    # 长幼缺 → 回落游戏词
    cache2 = {"characters": {
        "1": {"family": {"siblings": [9]}},
        "9": {"female": False, "family": {"primary_spouse": [8]}},
        "8": {"female": True, "family": {"primary_spouse": [9]}},
    }}
    check("同胞无生年 → 同胞配偶回落姻亲姊妹",
          F.kin_word(cache2, 1, 8) == "姻亲姊妹", F.kin_word(cache2, 1, 8))
    check("词表白名单含全部新词",
          all(w in F.kin_texts() for w in
              ("伯父", "叔父", "舅父", "姑母", "姨母", "侄子", "外甥", "孙子",
               "外孙女", "堂姐", "表妹", "岳母", "公公", "婆婆", "嫂", "弟媳",
               "姐夫", "妹夫", "叔舅", "侄甥", "堂表兄弟")), "")
    # v80 (点3, 用户拍板「任何有亲属关系的角色都要有一个词」): 新增词也必须在白名单内
    check("词表白名单含 v80 新增词",
          all(w in F.kin_texts() for w in
              ("祖父", "祖母", "外祖父", "外祖母", "曾祖父", "曾祖母", "外曾祖父",
               "外曾祖母", "伯祖父", "姑祖母", "舅祖父", "姨祖母", "堂伯", "堂叔",
               "堂姑", "表伯", "表叔", "表姑", "表舅", "表姨", "侄孙", "侄孙女",
               "外甥孙", "外甥孙女", "曾孙", "曾孙女", "外曾孙", "外曾孙女")), "")
    print("[V45b] 完成")


def group_v47():
    """v47（统治者头衔动态 + 结仇缘由）断言：纯函数, 假缓存/假熔件, 不载熔件。

    判据见 `docs/研究_v47_统治者头衔动态.md` §4/§5 与
    `docs/研究_v47_文化信仰存档来源.md` §1（存档里 culture/faith 是可选键,
    缺省 = 家族值）。覆盖：
      1. 沿革取值 `_hist_value_at` 的日期语义;
      2. `_culture_entry` 四段取值链 (沿革 → 缓存现值 → 熔件对象 → 家族缺省);
      3. `_faith_id` 同构;
      4. `_character_government` 的「同战役缓存借用政体史」+ 原有闸门不回归;
      5. 仇人池硬门槛: 无结仇/死敌因由者不进池 (`_enemy_has_cause`);
      6. `_sub_relation_loc` 的第三人槽。
    """
    import biography as bio
    print("[V47] 统治者头衔动态 (文化/信仰取回) + 仇人池硬门槛")
    ch = {}

    def put(cid, **kw):
        ch[str(cid)] = dict(id=cid, **kw)

    # 家族 900: 族长链 10, 11, 12 —— 只有末位族长 12 有显式值 (游戏口径: 由近及远)
    put(10, dynasty_house=900)
    put(11, dynasty_house=900)
    put(12, dynasty_house=900, culture=31, faith=31)
    put(20, dynasty_house=901)          # 家族 901 无任何显式值 → 求不出
    put(30, culture=39)                 # 无家族, 显式值
    put(53, dynasty_house=900)          # 家族缺省 (culture=31 greek)
    put(54, dynasty_house=901)
    put(61, dynasty_house=900)          # 家族缺省信仰 (faith=31 orthodox)
    melt = {
        "culture_manager": {"cultures": {
            "31": {"culture_template": "greek", "name_list": "name_list_greek",
                   "heritage": "heritage_byzantine"},
            "39": {"culture_template": "franconian",
                   "name_list": "name_list_franconian",
                   "heritage": "heritage_central_germanic"},
            "47": {"culture_template": "han", "name_list": "name_list_han",
                   "heritage": "heritage_chinese"},
        }},
        "religion": {"faiths": {
            "31": {"faith_type": "orthodox", "religion": 1},
            "49": {"faith_type": "daoxue", "religion": 2},
        }},
        "dynasties": {"dynasty_house": {
            "900": {"historical": [10, 11], "head_of_house": 12},
            "901": {"historical": [20], "head_of_house": 20},
        }},
    }
    # 缓存里 50 只有沿革 (现值已缺省), 51 只有现值, 55 沿革与现值不一致
    cache = {"characters": {
        "50": {"culture": None, "culture_history": [{"from": "1067.1.1", "culture": 31}]},
        "51": {"culture": 39},
        "55": {"culture": 47, "culture_history": [{"from": "1067.1.1", "culture": 39},
                                                 {"from": "1132.1.1", "culture": 47}]},
        "60": {"faith": None, "faith_history": [{"from": "1099.1.1", "faith": 31},
                                                {"from": "1137.1.1", "faith": 49}]},
    }}
    f = F.Facts.__new__(F.Facts)
    f.cache = cache
    f._chars = ch
    f.melt = melt

    # ---- 1. 沿革取值的日期语义 ----
    hist = [{"from": "1067.1.1", "culture": 39}, {"from": "1132.1.1", "culture": 47}]
    check("[1] 沿革中段取当日之值",
          F._hist_value_at(hist, "1120.1.1", "culture") == 39,
          F._hist_value_at(hist, "1120.1.1", "culture"))
    check("[1] 沿革换档日当天即取新值",
          F._hist_value_at(hist, "1132.1.1", "culture") == 47,
          F._hist_value_at(hist, "1132.1.1", "culture"))
    check("[1] 早于首点取首点",
          F._hist_value_at(hist, "1000.1.1", "culture") == 39,
          F._hist_value_at(hist, "1000.1.1", "culture"))
    check("[1] 无日期/无表返回 None",
          F._hist_value_at(hist, None, "culture") is None
          and F._hist_value_at([], "1120.1.1", "culture") is None, "")

    # ---- 2. 文化取值链 ----
    def cname(cid, date="1128.1.1"):
        e = f._culture_entry(cid, date)
        return (e or {}).get("name_list") or ""

    check("[2] 沿革优先 (现值缺省也能取回)",
          cname(50) == "name_list_greek", cname(50))
    check("[2] 无沿革取缓存现值", cname(51) == "name_list_franconian", cname(51))
    check("[2] 无缓存值取熔件对象", cname(30) == "name_list_franconian", cname(30))
    check("[2] 无任何显式值取家族缺省",
          cname(53) == "name_list_greek", cname(53))
    check("[2] 家族也求不出则为空", f._culture_entry(54, "1128.1.1") == {},
          f._culture_entry(54, "1128.1.1"))
    check("[2] 沿革按日期压过现值 (早年不取末档文化)",
          cname(55, "1120.1.1") == "name_list_franconian"
          and cname(55, "1140.1.1") == "name_list_han",
          (cname(55, "1120.1.1"), cname(55, "1140.1.1")))

    # ---- 3. 信仰取值链 (同构) ----
    check("[3] 信仰沿革按日期取值",
          f._faith_id(60, "1128.1.1") == 31 and f._faith_id(60, "1140.1.1") == 49,
          (f._faith_id(60, "1128.1.1"), f._faith_id(60, "1140.1.1")))
    check("[3] 信仰缺省取家族值",
          f._faith_id(61, "1128.1.1") == 31, f._faith_id(61, "1128.1.1"))
    check("[3] 家族信仰求不出返回 None",
          f._faith_id(54, "1128.1.1") is None, f._faith_id(54, "1128.1.1"))

    # ---- 4. 政体史借用 (同战役缓存) + 原闸门 ----
    own = {"characters": {}, "char_government_history": {}, "last_date": "1148.1.1"}
    sib = {"char_government_history": {"62045": [
        {"date": "1067.1.1", "government": "landless_adventurer_government"},
        {"date": "1087.1.1", "government": "feudal_government"},
        {"date": "1095.1.1", "government": "administrative_government"}]}}
    g = F.Facts.__new__(F.Facts)
    g.cache = own
    g._chars = {}
    g.campaign = {62045: sib}
    check("[4] 借用他篇缓存的政体史 (封建期)",
          g._character_government(62045, "1090.1.1") == "feudal_government",
          g._character_government(62045, "1090.1.1"))
    check("[4] 借用他篇缓存的政体史 (行政期)",
          g._character_government(62045, "1100.1.1") == "administrative_government",
          g._character_government(62045, "1100.1.1"))
    g.campaign = {}
    check("[4] 无史可借时仍回退「政体不可知」(不拿末档冒充历史)",
          g._character_government(62045, "1090.1.1") == "",
          g._character_government(62045, "1090.1.1"))

    # ---- 5. 仇人池硬门槛 ----
    class _Stub:
        def __init__(self, reasons):
            self._r = reasons

        def relation_reasons(self, cid, kinds):
            return list(self._r.get(int(cid), []))

    facts = {"_facts": _Stub({1: ["甲与乙结仇。"], 2: [], 3: []})}
    check("[5] 有游戏缘由 → 有因由", bio._enemy_has_cause(facts, 1, "1126.12.4"))
    check("[5] 无缘由且无直算 → 无因由",
          not bio._enemy_has_cause(facts, 2, "1126.12.4"))
    check("[5] 无事实层时不设门槛 (旧快照兼容)",
          bio._enemy_has_cause({}, 2, "1126.12.4"))
    _orig = F.relation_cause_lines
    F.relation_cause_lines = (lambda ff, cid, rd:
                              ["其父X已被主角谋杀"] if int(cid) == 3 else [])
    try:
        check("[5] 直算因由也算有因由",
              bio._enemy_has_cause(facts, 3, "1126.12.4"))
        ecache = {"player_id": 1, "characters": {
            "1": {"memories": []},
            "2": {"memories": [{"type": "became_rivals", "creation_date": "1100.1.1",
                                "participants": {"rival": 1}}]},
            "3": {"memories": [{"type": "became_rivals", "creation_date": "1100.1.1",
                                "participants": {"rival": 1}}]},
        }}
        check("[5] allow 门把无因由者筛出池",
              int(bio._select_primary_enemy(
                  ecache, allow=lambda c, d: int(c) != 2) or 0) == 3,
              bio._select_primary_enemy(ecache, allow=lambda c, d: int(c) != 2))
        check("[5] 全员无因由 → 不出仇人",
              bio._select_primary_enemy(
                  ecache, allow=lambda c, d: False) is None,
              bio._select_primary_enemy(ecache, allow=lambda c, d: False))
        check("[5] 旧行为 (无 allow) 不变",
              int(bio._select_primary_enemy(ecache) or 0) in (2, 3),
              bio._select_primary_enemy(ecache))
        # _enemy_for_facts 在有事实层时确实传了门槛
        ef = dict(facts)
        ef["as_of"] = None
        ef["decade"] = None
        check("[5] _enemy_for_facts 传门槛 (只留 cid=3)",
              int(bio._enemy_for_facts(ef, ecache) or 0) == 3,
              bio._enemy_for_facts(ef, ecache))
    finally:
        F.relation_cause_lines = _orig

    # ---- 6. 关系原因第三人槽 ----
    class _F2:
        def name_or(self, cid, fallback="某人", date=None):
            return {1: "甲", 2: "乙", 3: "丙"}.get(int(cid), fallback)

    raw = ("[TARGET_CHARACTER.GetShortUIName|U]虐待其配偶"
           "[TARGET_CHARACTER_2.GetShortUIName]，后者是"
           "[CHARACTER.GetShortUIName]的亲属。")
    s = F._sub_relation_loc(_F2(), raw, 1, 2, 3)
    check("[6] 第三人槽被替换 (配偶名不再被吃掉)",
          s == "乙虐待其配偶丙，后者是甲的亲属。", s)
    print("[V47] 完成")


def _collect_texts(o, acc):
    """递归收集嵌套常量里的字符串 (v51 提示词常量标点自检用)。"""
    if isinstance(o, str):
        acc.append(o)
    elif isinstance(o, dict):
        for v in o.values():
            _collect_texts(v, acc)
    elif isinstance(o, (list, tuple)):
        for v in o:
            _collect_texts(v, acc)
    return acc


def group_v51(snap_path):
    """v51: 半角标点归正 —— 事实面与现行提示词常量里都没有「汉字旁半角标点」。

    判据直接调 llm.normalize_zh_punct (幂等): 归一后与原文相同的行即干净。
    快照里嵌的提示词可能是改动前生成的 (仍带半角), 故此处只查**事实面**与
    **现行源码常量**两处, 不追溯旧快照的 messages。"""
    import llm
    print(f"[V51] 半角标点归正 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    fact_surface, _instr = _surface(snap)
    surface = fact_surface + "\n" + json.dumps(snap.get("facts") or {},
                                               ensure_ascii=False)
    bad = [ln.strip()[:90] for ln in surface.splitlines()
           if ln.strip() and llm.normalize_zh_punct(ln) != ln]
    check("[V51] 事实面无汉字旁半角标点", not bad, bad[:3])

    import style
    texts = [style.rule_block("east", False), style.rule_block("west", True)]
    for table in (style.SECTION_REQ, style.STYLE_PROFILES, style.PROMPTS,
                  style.SECTION_TITLES):
        _collect_texts(table, texts)
    bad_src = [t[:90] for t in texts if llm.normalize_zh_punct(t) != t]
    check("[V51] 现行提示词常量无汉字旁半角标点", not bad_src, bad_src[:3])
    print(f"[V51] 完成 ({os.path.basename(snap_path)})")


def group_v52(snap_path):
    """v52 (斯卡利茨六问题): 公主/王子称号、营地头衔、刺客列传门槛。

    断言 (全部按**通用形态**判, 不绑该档人名):
      1. 公主/王子称号不再叠「王国/帝国」层级词 (皇朝级为「大X」), 也无双重后缀;
      2. 无地冒险者营地名/称谓不叠领地层级词与封建官职词 (旧稿「私生子大队公国公爵」);
      3. 本周期内击杀 ≥1 即出《刺客列传》(killed 非空 ⇔ 篇目含 assassins)。"""
    print(f"[V52] 斯卡利茨六问题 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    fact_surface, instr = _surface(snap)
    surface = fact_surface + instr

    bad = _prince_tier_hits(surface)
    check("[V52] 公主/王子称号不叠层级词 (王国/帝国)", not bad, bad[:5])
    bad2 = _PRINCE_DOUBLE_RE.findall(surface)
    check("[V52] 无双重国号 (帝国国/帝国帝国/王国国)", not bad2, bad2[:5])

    pr = facts.get("protagonist") or {}
    if pr.get("landless"):
        blob = (pr.get("camp_name") or "") + "|" + (pr.get("label") or "")
        check("[V52] 无地营地名不叠领地层级词/封建官职词",
              not re.search(r"公国|公爵|王国|国王|帝国|皇帝", blob), blob)
    else:
        print("  SKIP [V52] 主角非无地 (营地头衔断言不适用)")

    killed = facts.get("killed") or []
    has = "assassins" in ((snap.get("meta") or {}).get("articles") or [])
    check("[V52] 击杀≥1 与《刺客列传》篇目一致", bool(killed) == has,
          f"killed={len(killed)} articles_assassins={has}")
    print(f"[V52] 完成 ({os.path.basename(snap_path)})")


def group_v53():
    """v53 (斯卡利茨五问题) 传输面/纯函数: 开创动词、连坐处死不进随机池、义务档解码。

    完整假存档断言见 tools/tests/verify_v53_unit.py。"""
    print("[V53] 斯卡利茨五问题")
    import cache_lib as cl
    import style as S
    check("[V53] 开创动词入表",
          S.TITLE_GAIN_CREATED_VERBS.get("founded") == "开创")
    check("[V53] 连坐处死不进随机处决池",
          "purge" not in dict(S.EXECUTION_OPTIONS))
    check("[V53] 连坐处死专用出口",
          S.EXECUTION_PURGE == ("purge", "连坐处死"))
    flags = cl.vassal_obligation_flags(
        {"contract_group": "celestial_vassal", "levels": [7, {"3": 2}]})
    check("[V53] 缺省份档 → 观察使旗标",
          flags == ["celestial_province_standard"], flags)
    mil = cl.vassal_obligation_flags(
        {"contract_group": "celestial_vassal", "levels": [7, {"2": 3}]})
    check("[V53] levels 2=3 → 经略使旗标",
          mil == ["celestial_province_military"], mil)
    print("[V53] 完成")


def group_v56(snap_path):
    """v56（斯卡利茨四问题）快照面断言 —— 判据全在快照里, 不需要熔件:

      1. 阴私录: 主角全称谓不再逐行刷屏 (「握有…的把柄」「没为…的奴隶」两族行只出名字),
         头衔只在《传主档案》一次立名;
      2. 加冕句: `witnessed_a_coronation_memory` 行带出加冕者 (「见证X的加冕」);
      3. 年表按日期升序 (末道稳定排序; 旧稿封顶后前段主角、后段倒回前代);
      4. 战末俘获行 (`war_capture`) 句面为「战胜X，俘之」, 且与「当日获释」同日不共存;
      5. 列传传主栏: 有本篇传主的篇目共享前缀首行标【主角】, 其余篇目标【传主】。
    """
    print(f"[V56] 斯卡利茨四问 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    if int(snap.get("schema") or 1) < 3:
        print("  SKIP 快照早于 v56 改动 (schema<3), 请用 tools/tests/snap.py 重建")
        return
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    msgs = snap.get("messages") or {}
    p = facts.get("protagonist") or {}
    label = (p.get("label") or "").strip()
    name = (p.get("name") or "").strip()
    tl = facts.get("timeline") or []

    # ---- [1] 阴私录主角称谓去重 ----
    sec_lines = []
    for k, v in blocks.items():
        if not k.startswith("secrets"):
            continue
        if isinstance(v, dict):
            for sub in v.values():
                sec_lines.extend(str(sub).splitlines())
        else:
            sec_lines.extend(str(v).splitlines())
    if sec_lines and label:
        bad = [ln.strip() for ln in sec_lines
               if label in ln and ("握有" in ln or "没为" in ln)]
        check("[1] 把柄/奴役行不出现主角全称谓", not bad, bad[:2])
        ok = [ln for ln in sec_lines if ("握有" in ln and "的把柄" in ln)]
        check("[1] 把柄行仍点名主角 (只出名字)",
              (not name) or any(name in ln for ln in ok), ok[:1])
        check("[1] 传主档案仍一次立名 (未误删头衔)",
              any(label in ln for ln in sec_lines))
    else:
        check("[1] 阴私录篇目存在 (无则跳过本组)", not sec_lines, "")

    # ---- [2] 加冕句带出加冕者 ----
    wit = [e for e in tl if e.get("type") == "witnessed_a_coronation_memory"]
    check("[2] 见证加冕句带出加冕者",
          all(("见证" in e["text"] and "的加冕" in e["text"]) for e in wit),
          [e["text"][:40] for e in wit[:2]])

    # ---- [3] 年表按日期升序 ----
    import cache_lib as _cl
    keys = [_cl.date_key(str(e["date"])) for e in tl if e.get("date")]
    bad_ord = [(tl[i]["date"], tl[i]["text"][:20])
               for i in range(1, len(keys)) if keys[i] < keys[i - 1]]
    check("[3] 年表按日期升序", not bad_ord, bad_ord[:2])

    # ---- [4] 战末俘获行 ----
    cap = [e for e in tl if e.get("type") == "war_capture"]
    check("[4] 俘获行句面为「战胜X，俘之」",
          all("战胜" in e["text"] and "俘之" in e["text"] for e in cap),
          [e["text"][:40] for e in cap[:2]])
    same_day = {e["date"] for e in tl if "当日获释" in (e.get("text") or "")}
    clash = [e["date"] for e in cap if e["date"] in same_day]
    check("[4] 同日不同时留「当日获释」", not clash, sorted(set(clash))[:3])

    # ---- [5] 列传传主栏 ----
    subj_keys = [k for k in msgs if k.split("_")[0] in ("friend", "enemy")]
    if subj_keys:
        bad_head = [k for k in subj_keys
                    if not ((msgs[k] or {}).get("user") or "").startswith("【主角】")]
        check("[5] 列传共享前缀首行标【主角】", not bad_head, bad_head[:2])
        prot_name = (facts.get("protagonist") or {}).get("name") or ""
        bad_note = []
        for k in subj_keys:
            u = (msgs[k] or {}).get("user") or ""
            m = re.search(r"【传主】([^\n]+)", u)
            if not m or m.group(1).strip() == prot_name:
                bad_note.append(k)
        check("[5] 篇内【传主】为他人", not bad_note, bad_note[:2])
    # ---- [6] §10: 关系缘由句的槽位与句面 ----
    # 建表保留的标签必须**全部**被 facts 替换掉: 事实面出现 '[' 即说明 keep-regex
    # 与 _sub_relation_loc 的替换口不同步 (v56 保留 PROVINCE/Possessive|U 之后的口径)。
    all_lines = []
    for k, v in blocks.items():
        if isinstance(v, dict):
            for sub in v.values():
                all_lines.extend(str(sub).splitlines())
        else:
            all_lines.extend(str(v).splitlines())
    tag_leak = [ln.strip() for ln in all_lines if "[" in ln or "]" in ln]
    check("[6] 事实面无未替换的 CK3 标签", not tag_leak, tag_leak[:2])
    bro = [ln.strip() for ln in all_lines
           if "在的" in ln or "在泡过" in ln or "在的一场" in ln]
    check("[6] 无被剥标签后的病句 (「在的…」)", not bro, bro[:2])
    # 死者名录的 events / event_types 必须逐位对齐 (v56 §10 婚恋行按型过滤的前提)
    bad_align = []
    for e in (facts.get("killed") or []):
        if len(e.get("events") or []) != len(e.get("event_types") or []):
            bad_align.append(e.get("name") or e.get("id"))
    check("[6] 死者名录 events 与 event_types 逐位对齐", not bad_align,
          bad_align[:3])
    print("[V56] 完成")


def group_v60(snap_path):
    """v60（崔佛四问题）快照面断言。

    与素材无关的不变量 (任何快照都跑):
      1. 吃掉有专用出口, 不进随机处决池;
      2. 未见释放的收句以本档为界 (不再出现「未见释放」式无限期断言)。
    崔佛档专有 (meta.folder == '崔佛'):
      3. `family_purges` 空 —— 部落制行刑者无诛灭世族机制前提;
      4. 死者名录里被吃者写「吃掉」;
      5. 《宝物志》收录遗骨, 名字干净 (无 `\\x15`/`high`), 材质句为陈述句;
      6. 家室篇无「结缡/离异/妻室」骨架, 有「妾」行与纳妾事实;
      7. 在押行带监禁者交接 (「转归」)。
    """
    print(f"[V60] 崔佛四问 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    import style as S
    check("[V60] 吃掉有专用出口且不进随机池",
          "devour_bone" not in dict(S.EXECUTION_OPTIONS)
          and S.EXECUTION_DEVOUR_BONE == ("devour_bone", "吃掉"))
    snap = json.load(open(snap_path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    meta = snap.get("meta") or {}
    tl_lines = [str(e.get("text") or "") for e in (facts.get("timeline") or [])]
    check("[V60] 囚禁收句不再是无限期断言",
          not any("未见释放" in ln for ln in tl_lines),
          [ln for ln in tl_lines if "未见释放" in ln][:2])
    if (meta.get("folder") or "") != "崔佛":
        print("  SKIP 崔佛档专有断言 (本快照非该战役)")
        return
    check("[V60] 部落制行刑者不判诛灭世族",
          facts.get("family_purges") == [], facts.get("family_purges"))
    check("[V60] 全篇无「诛灭」字样",
          not any("诛灭" in ln for ln in tl_lines),
          [ln for ln in tl_lines if "诛灭" in ln][:2])
    # v61 (问题1): 乙档改「绿色以上」门槛后, 崔佛档的遗骨件数随之变化 ——
    # 终传只剩 1 件 (famed「安达卢斯苏丹穆罕默德·伍麦叶之骨」), 第 1 个十年 0 件
    # (11 件全为 common → 全挡; 《宝物志》篇目随之不生成)。
    # 档位出处: Mod `devour_effects.txt:553-611` (帝国 illustrious / 王国 famed /
    # 公爵 masterwork / 其余 common) + `ARTIFACT_PART_RARITY` (facts.py)。
    _asof = facts.get("as_of")
    _n_bone = 0 if _asof else 1
    arts = facts.get("family_artifacts") or []
    check(f"[V60] 《宝物志》只收绿色以上部件宝物 ({_n_bone} 件)", len(arts) == _n_bone,
          len(arts))
    check("[V61] 事实面无 common 档宝物 (绿色门槛)",
          not any("，常见" in x for x in arts), arts[:1])
    check("[V60] 宝物名无格式码/烘焙短名",
          not any("\x15" in x or "high" in x for x in arts), arts[:1])
    check("[V60] 遗骨材质句为陈述句 (无「被吃掉了」)",
          not any("被吃掉了" in x for x in arts), arts[:1])
    _bones = [x for x in arts if "之骨" in x]
    check("[V60] 遗骨流转句写「吃掉X，遗骨成此宝」",
          all("吃掉" in x and "遗骨成此宝" in x for x in _bones), _bones[:1])
    check("[V60] 《宝物志》篇目已生成",
          (bool(_n_bone)) == ("artifacts_lead" in blocks and bool(blocks.get("artifacts_lead"))),
          f"件数 {_n_bone} / 篇目 {sorted(k for k in blocks if k.startswith('artifacts'))}")
    js = " ".join(str(v) for k, v in blocks.items() if k.startswith("jiashi"))
    msgs = snap.get("messages") or {}
    jmsg = " ".join(str((msgs.get(k) or {}).get("user") or "")
                    for k in msgs if k.startswith("jiashi"))
    check("[V60] 家室篇要求不再索要妻室子女",
          ("结缡" not in jmsg) and ("诞育" not in jmsg), jmsg[:120])
    check("[V60] 家室篇转为纳妾门庭题面",
          "纳妾" in jmsg or "收纳" in jmsg, jmsg[:120])
    check("[V60] 家室事实面有妾行",
          bool((facts.get("protagonist") or {}).get("concubines")
               or (facts.get("protagonist") or {}).get("former_concubines")))
    check("[V60] 纳妾事实带日期",
          all(re.match(r"^\d{3,4}年", x)
              for x in (facts.get("forced_concubines") or [])),
          facts.get("forced_concubines"))
    # v60: 强纳与离异都发生在 879.9.1 及以后 —— 第 1 个十年 (cutoff 878.1.1)
    # 这两块本就为空 (时期门), 终传才有。
    if _asof:
        check("[V60] 十年档不穿越 879 年的纳妾",
              not (facts.get("forced_concubines")
                   or facts.get("concubine_divorces")),
              (facts.get("forced_concubines"),
               facts.get("concubine_divorces")))
        check("[V60] 十年档不含末档在押交接",
              not [ln for ln in tl_lines if "转归" in ln],
              [ln for ln in tl_lines if "转归" in ln][:1])
    else:
        check("[V60] 妾的原配离异写成事实",
              bool(facts.get("concubine_divorces"))
              and any("原为" in x for x in (facts.get("concubine_divorces") or [])),
              facts.get("concubine_divorces"))
        held = [ln for ln in tl_lines if "仍在押" in ln]
        check("[V60] 在押行以本档为界", not any("未见释放" in ln for ln in held))
        check("[V60] 在押行带监禁者交接",
              bool(held) and any("转归" in ln for ln in held), held[:2])
    # 22 件遗骨里有 7 名 lowborn 被 `_kill_keep_ids` 滤掉 (刺客列传只留有名有姓者),
    # 故名录里被吃者恒少于遗骨数 —— 这里只断言「遗骨持有者都写成吃掉」。
    devour = [e for e in (facts.get("killed") or [])
              if "吃掉" in str(e.get("death") or "")]
    check("[V60] 死者名录里被吃者写「吃掉」", len(devour) >= 12, len(devour))
    print("[V60] 完成")


def group_v62(snap_path):
    """v62（菲利普2 日本三问）事实面断言。

    与战役无关的不变量 (任何快照都跑):
      1. 事实面/请求面不出现日本最高头衔伪前缀
         (「高御座王子」「高御座公主」「日本王子」「日本公主」—— 游戏侧无此词);
      2. 同一篇里同一顶 e_japan 只有一个词: 有关白则无「日本皇帝」。
    日本相关快照 (事实面出现日本人物时):
      3. e_japan 持有人写「日本关白X」(律令制) —— 同标题同词, 不再按持有者政体史分裂。
    """
    print(f"[V62] 菲利普2 日本三问 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    blobs = [snap.get("shared") or ""]
    for v in (snap.get("blocks") or {}).values():
        blobs.append("\n".join(v.values()) if isinstance(v, dict) else str(v))
    for v in (snap.get("messages") or {}).values():
        if isinstance(v, dict):
            blobs.append((v.get("system") or "") + "\n" + (v.get("user") or ""))
    full = "\n".join(blobs)
    bad = {w: full.count(w) for w in ("高御座王子", "高御座公主", "日本王子", "日本公主")
           if full.count(w)}
    check("[V62] 无日本最高头衔伪前缀 (高御座王子/日本王子…)", not bad, bad)
    check("[V62] 同一顶 e_japan 不混用「关白」与「皇帝」",
          not (full.count("日本关白") and full.count("日本皇帝")),
          {"关白": full.count("日本关白"), "皇帝": full.count("日本皇帝")})
    jp = ("日本关白" in full) or ("源" in full and "藤原" in full)
    if not jp:
        print("  SKIP 日本相关断言 (本快照事实面无日本人物)")
        return
    check("[V62] e_japan 持有人写「日本关白」(律令制政体)",
          "日本关白" in full or "日本皇帝" not in full,
          [ln for ln in full.split("\n") if "日本" in ln][:3])
    print("[V62] 完成")


def v63_audit(facts, f, pairs):
    """v63 核心判据 (非重言式): 逐处插入复算应有的定语**词**与**算词基准**。

    `pairs` = [(本篇传主 id, 未加词的行, 加词后的行, [(cid, 词, 实际基准), …]), …]
    —— 由 [V63] 拦 `biography._kin_tag_line` + `KinScope.word_for` 收集; 单元回归
    也用本函数 (见 `tools/tests/verify_kin_owner_unit.py`)。

    判据: 基准由 facts 字典里登记的**行主语** (`line_owner`, facts 侧独立登记)
    推出, 不看代码怎么算:
      · 该人是**本行主语** → 基准 = 本篇传主 (正史旁称「姻亲姊妹X」即此档)
      · 该人是**句中第三方** → 基准 = 本行主语
    基准或词不符即违规 (「于尔莎受业于**岳父**乱发哈拉尔」即此类 —— 乱发哈拉尔是
    传主的岳父、于尔莎的生父, 应出「父亲」)。返回 [(行, cid, 实际词, 应有词, 基准)]。
    """
    import biography as bio
    bad = []
    for subj, before, after, got in pairs:
        names, _off, key = bio._names_for_line(facts, before)
        owner = (facts.get("line_owner") or {}).get(key) if key else None
        for cid, w, base in got:
            want_base = subj if (owner is None or int(cid) == owner) else owner
            want = f.kin_word_for(cid, want_base)
            if base != want_base or w != want:
                bad.append((before[:60], cid, f"{w}@{base}", f"应={want}@{want_base}"))
                continue
            label = next((lab for c, lab in (names or []) if int(c) == int(cid)), "")
            if label and f"{w}{label}" not in after:
                bad.append((before[:60], cid, w, "未落在该人名之前"))
    return bad


def group_v63(snap_path):
    """v63（行内定语基准）: 句子有自己的主语时, 句中**第三方**人名的亲缘定语
    必须按本行主语算词。

    旧稿一律按本篇传主算词 —— 菲利普2 实测: 家室档案里于尔莎的条目被插成
    「883年10月12日，于尔莎·哈拉尔斯多蒂尔受业于**岳父**西福尔酋长乱发哈拉尔」,
    而乱发哈拉尔正是她的**生父** (同一档案的家世行写着「父西福尔酋长乱发哈拉尔」),
    一句之内自相抵牾, 模型只好写「岳父亦是其生父，此一节谱系交错，史家当另作考辨」。
    """
    import biography as bio
    print(f"[V63] 行内定语基准 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("[V63] 快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    f = _facts_from_snap(snap)
    if f is None:
        print("  SKIP [V63] 无同目录缓存/熔件, 无法重建 Facts")
        return
    facts = dict(snap.get("facts") or {})
    facts["_facts"] = f
    if not facts.get("line_owner"):
        print("  SKIP [V63] 本快照 facts 无行主语登记 (旧版快照; 用 tools/tests/snap.py 重落一份)")
        return
    meta = snap.get("meta") or {}
    data = os.path.join(ROOT, "output", meta.get("folder") or "", "data")
    try:
        cache = json.load(open(os.path.join(
            data, f"player_{meta.get('player_id')}.json"), encoding="utf-8"))
        articles = bio.build_articles(facts, cache, {"max_tokens": 12800})
    except Exception as e:               # noqa: BLE001
        check("[V63] 重建板块素材", False, repr(e))
        return
    pairs, cur = [], []
    real_line, real_scope = bio._kin_tag_line, F.KinScope

    class _Scope(real_scope):
        def word_for(self, cid, fa, subject=None):
            w = real_scope.word_for(self, cid, fa, subject=subject)
            if w:
                cur.append((cid, w, self.subject if subject is None else subject))
            return w

    def _spy(fa, scope, line, _real=real_line):
        del cur[:]
        out = _real(fa, scope, line)
        if cur:
            pairs.append((scope.subject, line, out, list(cur)))
        return out

    F.KinScope = _Scope
    bio._kin_tag_line = _spy
    try:
        for a in articles:
            for sec in a["sections"]:
                bio._article_facts(facts, cache, a["key"], sec)
    finally:
        F.KinScope = real_scope
        bio._kin_tag_line = real_line
    bad = v63_audit(facts, f, pairs)
    check("[V63] 行内定语按句内主语算词 (不把岳父插进讲妻子的句子)", not bad, bad[:3])
    n_all = sum(len(g) for *_x, g in pairs)
    n_own = sum(1 for subj, _b, _a, g in pairs for _c, _w, b in g if b != subj)
    print(f"  INFO 实查插入 {n_all} 处 (其中 {n_own} 处按句内主语算词), "
          f"涉及行 {len(pairs)} 行, 违规 {len(bad)} 处")
    print("[V63] 完成")


def group_v63b(snap_path):
    """[V63b] 菲利普2 五问的**事实面**断言 (2026-09-24 第二轮 v63)。

    与 `[V63]`(行内定语基准) 同属 v63, 但查的是另外三件事:
      1. 宝物名不得含「称号，名字」的逗号 (问题4: 「桂王，唐文举之骨」);
      2. 刺客列传亲缘行的性别自洽 (问题5: 女性死者不得被标「妻/前妻/妾」);
      3. 亲缘关系自检 `facts.audit_kin_lines` 为 0 (问题5: 长辈晚出生/单边亲缘)。
    三问都以**快照里的 blocks/facts** 为输入, 不重跑模型。"""
    import re as _re
    print(f"[V63b] 菲利普2 五问事实面 ({os.path.basename(snap_path)})")
    if not os.path.isfile(snap_path):
        check("[V63b] 快照存在", False, snap_path)
        return
    snap = json.load(open(snap_path, encoding="utf-8"))
    blocks = snap.get("blocks") or {}
    facts = snap.get("facts") or {}
    chars = facts.get("characters") or {}

    # ---- 1) 宝物名无「称号，名字」逗号 ----
    arts = facts.get("family_artifacts") or []
    bad_names = []
    for row in arts:
        for ln in str(row).split("\n"):
            if not ln.startswith("宝物："):
                continue
            # 「宝物：{名}，{稀有度}」—— 名里不应再出现「X，Y」式短称号逗号
            m = _re.match(r"^宝物：(.+?)，(常见|著名|大师级|名望级|传奇级)", ln)
            if m and _re.search(r"[\u4e00-\u9fff]{1,5}，[\u4e00-\u9fff]", m.group(1)):
                bad_names.append(ln)
    check("[V63b] 宝物名无「称号，名字」逗号", not bad_names, bad_names[:3])

    # ---- 2) 刺客列传亲缘行的性别自洽 ----
    female = {int(k) for k, v in chars.items()
              if isinstance(v, dict) and v.get("female")}
    by_name = {v.get("name"): int(k) for k, v in chars.items()
               if isinstance(v, dict) and v.get("name")}
    bad_kin = []
    for key, blk in blocks.items():
        if not str(key).startswith("assassins"):
            continue
        cur = None
        for ln in str(blk.get("刀下诸魂") or "").split("\n"):
            m = _re.match(r"^死者：([^，、]+)", ln)
            if m:
                cur = m.group(1)
                continue
            m2 = _re.match(r"^亲缘：(.+)$", ln)
            if not m2 or cur is None:
                continue
            cid = by_name.get(cur)
            if cid is not None and cid in female \
                    and _re.search(r"(^|、)(妻|前妻|妾)", m2.group(1)):
                bad_kin.append(f"{cur} → {m2.group(1)}")
    check("[V63b] 女性死者不得被标「妻/前妻/妾」", not bad_kin, bad_kin[:3])

    # ---- 3b) v63 问题3: 性事 (强迫/半推半就) 只出现在好友/仇人列传 ----
    # 用户拍板: 「只需要补埃德伯的强奸记忆……只有仇人/好友列传需要加」。
    # 旧稿两道闸 (角色档案 / 公开年表) 互相指认对方出句, 实际谁都没出 —— 本组盯住
    # 新出口 (`Facts.sex_mem_lines` ⇒ 该篇纪事块「强迫之事」)。
    sx_keys, sx_hit = [], []
    for _k, _blk in (blocks or {}).items():
        for _bk, _bv in (_blk or {}).items():
            if "强迫" not in str(_bv) and "半推半就" not in str(_bv):
                continue
            _ks = str(_k)
            sx_keys.append(_ks)
            if _ks.startswith(("friend", "enemy")) \
                    and ("强迫性交" in str(_bv) or "强迫口交" in str(_bv)):
                sx_hit.append(_ks)
    check("[V63b] 性事行只出现在好友/仇人列传",
          all(k.startswith(("friend", "enemy")) for k in sx_keys),
          sorted(set(sx_keys))[:5])
    check("[V63b] 仇人列传含「强迫性交」行 (问题3 埃德伯)",
          bool(sx_hit), sorted(set(sx_hit))[:3] or sorted(set(sx_keys))[:5])

    # ---- 2b) 妾婚不产生姻亲称谓 (问题7) ----
    # 昆伯·阿尔弗雷德斯多赫托尔是主角的**妾** (907.11.5 强纳), 故主角不是
    # 埃德伯的「妹夫」、伯特诺思也不是他的「姻亲兄弟」—— 姻亲只由正妻之婚产生。
    # (「弟媳」这类由**正妻**之婚产生的词不受影响, 故只禁这两个被实证误出的词。)
    _kin_bad = []
    for key, blk in blocks.items():
        txt = "\n".join(f"{k}\n{v}" for k, v in (blk or {}).items())
        for w in ("妹夫", "姻亲"):
            if w in txt:
                _kin_bad.append((key, w))
    check("[V63b] 妾婚不产生姻亲称谓 (问题7: 无妹夫/姻亲)",
          not _kin_bad, _kin_bad[:4])
    # 程序口径: 以埃德伯为基准看主角的定语必须为空 (妾婚不产生妹夫)
    fk = _facts_from_snap(snap)
    if fk is not None:
        try:
            _w = fk.kin_word_for(38665, 44335)
        except Exception as exc:                          # noqa: BLE001
            _w = f"<ERR {exc!r}>"
        check("[V63b] kin_word_for(主角, 埃德伯) 为空 (问题7)",
              _w == "", _w)

    # ---- 3) 亲缘自检为 0 ----
    f = _facts_from_snap(snap)
    if f is None:
        print("  SKIP [V63b] 无同目录缓存/熔件, 无法跑亲缘自检")
    else:
        facts2 = dict(facts)
        facts2["_facts"] = f
        issues = F.audit_kin_lines(facts2)
        check("[V63b] 亲缘自检 0 命中 (长辈晚出生/单边亲缘/亲属当配偶)",
              not issues, issues[:3])
    print("[V63b] 完成")


def main():
    snap = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SNAP
    group_a()
    group_b(snap)
    group_c(snap)
    group_v36(snap)
    group_v37(snap)
    group_v39(snap)
    group_v40(snap)
    group_v41(snap)
    group_v42(snap)
    group_v43(snap)
    group_v44(snap)
    group_v45(snap)
    group_v45b()
    group_v47()
    group_v51(snap)
    group_v52(snap)
    group_v53()
    group_v56(snap)
    group_v60(snap)
    group_v62(snap)
    group_v63(snap)
    group_v63b(snap)
    print("\n" + "=" * 60)
    print("结果: 全部 PASS" if _OK else "结果: 存在 FAIL")
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
