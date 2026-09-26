# -*- coding: utf-8 -*-
"""CK3 记忆缓存库 v4 (由 expck3/cache_lib.py v2 升级移植)。

记忆系统真实结构 (经 exp6/exp7/exp8 实测验证):
  - character_memory_manager.database : 键 = **记忆 ID** (与角色共享 id 池)。
  - 每个角色的 alive_data.memories = { 记忆ID列表 } : 角色 → 记忆的多对多映射。
  - 角色**死亡时 memories 列表被清空**, 记忆对象也从 database 移除
    (实测: 868 活有记忆→869 已死 141 人全部清空; 对照活人保留)。
  - 因此必须在角色死前的年度存档里抓取记忆 → 缓存库是唯一可靠方案。

v4 变更 (相对 v3):
  1. **本地化接入**: 名字/姓氏/头衔名查 localization.py 的本地化表
     (Daria → 达丽娅; dynasty_house.localized_name → 冯·大马士革)。
  2. **特质日期**: 每快照 diff 特质 → rec["trait_history"] 记录
     {特质key: [{from, to, first}]} (获得/消失区间, 供「自某日起获得」)。
  3. **反向亲属索引**: 存档子女 family_data 常为空, 父女关系只在父/母侧的
     child 列表 (实测 33367.child 含妻 37898) → 每快照构建全档亲属图,
     补出 rec["family"] 的 father/mother/siblings; 目标集扩展含亲属的亲属,
     保证妻父(宋帝赵曙)/妻兄(今上赵煦)等入缓存。
  4. **头衔/朝局历史**: cache["player_title_history"] 记录玩家主头衔名变化
     (复兴党流亡委员会 1067.6.20 起); cache["realm_history"] 逐年记录
     帝国/王国级头衔与相关角色头衔的持有者, 供《朝局风云录》数据驱动。
  5. **输出文件夹绑定**: cache["output_folder"] 记录会话文件夹,
     watch/continue 据此分文件夹 (重名 → 哈布斯堡2, 见 pipeline)。
"""
import copy
import gc
import gzip
import json
import lzma
import os
import re
import threading
import time
from collections import OrderedDict

import localization
import llm
import style as _style   # v38: 牵制白名单判据 (style.hook_type_kept) 与措辞表

# ---------------------------------------------------------------------------
# 名称解码
# ---------------------------------------------------------------------------

_CP_RE = re.compile(r"_([0-9A-Fa-f]{3,5})(?=_|$)")

# 常见繁体→简体映射 (姓氏与常用名用字; 缺字可在此扩充)
_SIMPLIFY = {
    "誠": "诚", "邊": "边", "師": "师", "綽": "绰", "繫": "系", "係": "系",
    "楊": "杨", "孫": "孙", "張": "张", "蕭": "萧", "羣": "群", "韻": "韵",
    "諷": "讽", "臺": "台", "廣": "广", "萬": "万", "與": "与", "長": "长",
    "開": "开", "關": "关", "門": "门", "國": "国", "會": "会", "來": "来",
    "東": "东", "無": "无", "為": "为", "時": "时", "書": "书", "風": "风",
    "雲": "云", "馬": "马", "魚": "鱼", "鳥": "鸟", "龍": "龙", "鳳": "凤",
    "劉": "刘", "陳": "陈", "鄭": "郑", "趙": "赵", "錢": "钱", "吳": "吴",
    "謝": "谢", "許": "许", "韓": "韩", "馮": "冯", "鄧": "邓", "曹": "曹",
    "彭": "彭", "蔣": "蒋", "蔡": "蔡", "賈": "贾", "田": "田", "范": "范",
    "陸": "陆", "崔": "崔", "盧": "卢", "譚": "谭", "韋": "韦", "羅": "罗",
    "聶": "聂", "莊": "庄", "沈": "沈", "鍾": "钟", "顧": "顾", "龔": "龚",
    "顏": "颜", "魏": "魏", "陶": "陶", "姜": "姜", "蘇": "苏", "潘": "潘",
    "葛": "葛", "奚": "奚", "範": "范", "彭": "彭", "郎": "郎", "魯": "鲁",
    "昌": "昌", "俞": "俞", "任": "任", "袁": "袁", "酆": "酆", "鮑": "鲍",
    "史": "史", "唐": "唐", "費": "费", "廉": "廉", "岑": "岑", "薛": "薛",
    "雷": "雷", "賀": "贺", "倪": "倪", "湯": "汤", "滕": "滕", "殷": "殷",
    "羅": "罗", "畢": "毕", "郝": "郝", "鄔": "邬", "安": "安", "常": "常",
    "樂": "乐", "於": "于", "傅": "傅", "皮": "皮", "卞": "卞", "齊": "齐",
    "康": "康", "伍": "伍", "余": "余", "元": "元", "卜": "卜", "顧": "顾",
    "孟": "孟", "平": "平", "黃": "黄", "和": "和", "穆": "穆", "蕭": "萧",
    "尹": "尹", "姚": "姚", "邵": "邵", "湛": "湛", "汪": "汪", "祁": "祁",
    "毛": "毛", "禹": "禹", "狄": "狄", "米": "米", "貝": "贝", "明": "明",
    "臧": "臧", "計": "计", "伏": "伏", "成": "成", "戴": "戴", "談": "谈",
    "宋": "宋", "茅": "茅", "龐": "庞", "熊": "熊", "紀": "纪", "舒": "舒",
    "屈": "屈", "項": "项", "祝": "祝", "董": "董", "梁": "梁", "杜": "杜",
    "阮": "阮", "藍": "蓝", "閔": "闵", "席": "席", "季": "季", "麻": "麻",
    "強": "强", "賈": "贾", "路": "路", "婁": "娄", "危": "危", "江": "江",
    "童": "童", "顏": "颜", "郭": "郭", "梅": "梅", "盛": "盛", "林": "林",
    "刁": "刁", "鍾": "钟", "徐": "徐", "邱": "邱", "駱": "骆", "高": "高",
    "夏": "夏", "蔡": "蔡", "田": "田", "樊": "樊", "胡": "胡", "凌": "凌",
    "霍": "霍", "虞": "虞", "萬": "万", "支": "支", "柯": "柯", "昝": "昝",
    "管": "管", "盧": "卢", "莫": "莫", "經": "经", "房": "房", "裘": "裘",
    "繆": "缪", "干": "干", "解": "解", "應": "应", "宗": "宗", "丁": "丁",
    "宣": "宣", "賁": "贲", "鄧": "邓", "鬱": "郁", "單": "单", "杭": "杭",
    "洪": "洪", "包": "包", "諸": "诸", "左": "左", "石": "石", "崔": "崔",
    "吉": "吉", "鈕": "钮", "龔": "龚", "程": "程", "嵇": "嵇", "邢": "邢",
    "滑": "滑", "裴": "裴", "陸": "陆", "榮": "荣", "翁": "翁", "荀": "荀",
    "羊": "羊", "於": "于", "惠": "惠", "甄": "甄", "麴": "曲", "家": "家",
    "封": "封", "芮": "芮", "羿": "羿", "儲": "储", "靳": "靳", "汲": "汲",
    "邴": "邴", "糜": "糜", "松": "松", "井": "井", "段": "段", "富": "富",
    "巫": "巫", "烏": "乌", "焦": "焦", "巴": "巴", "弓": "弓", "牧": "牧",
    "隗": "隗", "山": "山", "谷": "谷", "車": "车", "侯": "侯", "宓": "宓",
    "蓬": "蓬", "全": "全", "郗": "郗", "班": "班", "仰": "仰", "秋": "秋",
    "仲": "仲", "伊": "伊", "宮": "宫", "寧": "宁", "仇": "仇", "欒": "栾",
    "暴": "暴", "甘": "甘", "釤": "钐", "厲": "厉", "戎": "戎", "祖": "祖",
    "武": "武", "符": "符", "劉": "刘", "景": "景", "詹": "詹", "束": "束",
    "龍": "龙", "葉": "叶", "幸": "幸", "司": "司", "韶": "韶", "郜": "郜",
    "黎": "黎", "薊": "蓟", "薄": "薄", "印": "印", "宿": "宿", "白": "白",
    "懷": "怀", "蒲": "蒲", "邰": "邰", "從": "从", "鄂": "鄂", "索": "索",
    "鹹": "咸", "籍": "籍", "賴": "赖", "卓": "卓", "藺": "蔺", "屠": "屠",
    "蒙": "蒙", "池": "池", "喬": "乔", "陰": "阴", "鬱": "郁", "胥": "胥",
    "能": "能", "蒼": "苍", "雙": "双", "聞": "闻", "莘": "莘", "党": "党",
    "翟": "翟", "譚": "谭", "貢": "贡", "勞": "劳", "逄": "逄", "姬": "姬",
    "申": "申", "扶": "扶", "堵": "堵", "冉": "冉", "宰": "宰", "酈": "郦",
    "雍": "雍", "卻": "却", "璩": "璩", "桑": "桑", "桂": "桂", "濮": "濮",
    "牛": "牛", "壽": "寿", "通": "通", "邊": "边", "扈": "扈", "燕": "燕",
    "冀": "冀", "郟": "郏", "浦": "浦", "尚": "尚", "農": "农", "溫": "温",
    "別": "别", "莊": "庄", "晏": "晏", "柴": "柴", "瞿": "瞿", "閻": "阎",
    "充": "充", "慕": "慕", "連": "连", "茹": "茹", "習": "习", "宦": "宦",
    "艾": "艾", "魚": "鱼", "容": "容", "向": "向", "古": "古", "易": "易",
    "慎": "慎", "戈": "戈", "廖": "廖", "庾": "庾", "終": "终", "暨": "暨",
    "居": "居", "衡": "衡", "步": "步", "都": "都", "耿": "耿", "滿": "满",
    "弘": "弘", "匡": "匡", "國": "国", "文": "文", "寇": "寇", "廣": "广",
    "祿": "禄", "闕": "阙", "東": "东", "歐": "欧", "殳": "殳", "沃": "沃",
    "利": "利", "蔚": "蔚", "越": "越", "夔": "夔", "隆": "隆", "師": "师",
    "鞏": "巩", "厙": "厍", "聶": "聂", "晁": "晁", "勾": "勾", "敖": "敖",
    "融": "融", "冷": "冷", "訾": "訾", "辛": "辛", "闞": "阚", "那": "那",
    "簡": "简", "饒": "饶", "空": "空", "曾": "曾", "毋": "毋", "沙": "沙",
    "乜": "乜", "養": "养", "鞠": "鞠", "須": "须", "豐": "丰", "巢": "巢",
    "關": "关", "蒯": "蒯", "相": "相", "查": "查", "后": "后", "荊": "荆",
    "紅": "红", "遊": "游", "竺": "竺", "權": "权", "逯": "逯", "蓋": "盖",
    "益": "益", "桓": "桓", "公": "公", "萬": "万", "俟": "俟", "司馬": "司马",
    "上官": "上官", "歐陽": "欧阳", "夏侯": "夏侯", "諸葛": "诸葛", "聞人": "闻人",
    "東方": "东方", "赫連": "赫连", "皇甫": "皇甫", "尉遲": "尉迟", "公羊": "公羊",
    "澹臺": "澹台", "公冶": "公冶", "宗政": "宗政", "濮陽": "濮阳", "淳于": "淳于",
    "單于": "单于", "太叔": "太叔", "申屠": "申屠", "公孫": "公孙", "仲孫": "仲孙",
    "軒轅": "轩辕", "令狐": "令狐", "鍾離": "钟离", "宇文": "宇文", "長孫": "长孙",
    "慕容": "慕容", "鮮于": "鲜于", "閭丘": "闾丘", "司徒": "司徒", "司空": "司空",
    "亓官": "亓官", "司寇": "司寇", "仉督": "仉督", "子車": "子车", "顓孫": "颛孙",
    "端木": "端木", "巫馬": "巫马", "公西": "公西", "漆雕": "漆雕", "樂正": "乐正",
    "壤駟": "壤驷", "公良": "公良", "拓跋": "拓跋", "夾谷": "夹谷", "宰父": "宰父",
    "穀梁": "谷梁", "晉": "晋", "楚": "楚", "閆": "闫", "法": "法", "汝": "汝",
    "鄢": "鄢", "塗": "涂", "欽": "钦", "段干": "段干", "百里": "百里",
    "東郭": "东郭", "南門": "南门", "呼延": "呼延", "歸": "归", "海": "海",
    "羊舌": "羊舌", "微生": "微生", "岳": "岳", "帥": "帅", "緱": "缑", "亢": "亢",
    "況": "况", "後": "后", "有": "有", "琴": "琴", "梁丘": "梁丘", "左丘": "左丘",
    "東門": "东门", "西門": "西门", "商": "商", "牟": "牟", "佘": "佘", "佴": "佴",
    "伯": "伯", "賞": "赏", "南宮": "南宫", "墨": "墨", "哈": "哈", "譙": "谯",
    "笪": "笪", "年": "年", "愛": "爱", "陽": "阳", "佟": "佟", "第五": "第五",
    "言": "言", "福": "福", "百家姓終": "",
    "顔": "颜", "闞": "阚", "都": "都", "郗": "郗", "麴": "曲", "郜": "郜",
    "宰": "宰", "藺": "蔺", "單": "单", "鞏": "巩", "濮": "濮", "逄": "逄",
    "訾": "訾", "軒": "轩", "毅": "毅", "曠": "旷", "郯": "郯", "邛": "邛",
    "詞": "词", "辭": "辞", "惲": "恽", "孃": "娘", "價": "价", "係": "系",
}


def zh(s):
    """繁体/码点混合文本 → 简体 (按 _SIMPLIFY 表逐字替换)。"""
    if not s:
        return s
    out = []
    i = 0
    n = len(s)
    while i < n:
        # 先试双字 (复姓/双字词), 再试单字
        two = s[i:i + 2]
        if two in _SIMPLIFY:
            out.append(_SIMPLIFY[two])
            i += 2
            continue
        ch = s[i]
        out.append(_SIMPLIFY.get(ch, ch))
        i += 1
    return "".join(out)


def decode_codepoints(key):
    """'Cheng_8AA0' → '诚'; 'dynn_Bian_908A' → '边' (只返回码点拼出的汉字;
    无码点或结果非汉字时原样返回)。"""
    if not key:
        return key
    parts = _CP_RE.findall(key)
    if not parts:
        return key
    zh_chars = "".join(chr(int(h, 16)) for h in parts)
    if any("\u3400" <= ch <= "\u9fff" for ch in zh_chars):
        return zh_chars
    return key


def loc_name(fn):
    """名字 key → 中文: 本地化表 → 码点解码 → 原样。
    实测: 'Daria' → '达丽娅'; 'A_zu_963F_8DB3' → '阿足'。"""
    if not fn:
        return fn
    v = localization.loc(localization.table(), fn)
    if v and v != fn:
        return v
    dec = decode_codepoints(fn)
    if dec and dec != fn:
        return dec
    return fn


def name_zh(char_obj):
    """角色对象 first_name (名表键) → 中文名。"""
    fn = (char_obj or {}).get("first_name") or ""
    return zh(loc_name(fn))


def _dynn_lookup(table, name):
    """'abbasid' → 'dynn_Abbasid' → '阿拔斯' (大小写不敏感, v8.2)。
    CK3 家族名本地化键形如 dynn_<Name> (dynn_Abbasid/dynn_Tulunid)。"""
    if not name:
        return ""
    global _DYNN_INDEX
    if _DYNN_INDEX is None:
        _DYNN_INDEX = {k.lower(): v for k, v in table.items()
                       if k.startswith("dynn_")}
    return _DYNN_INDEX.get("dynn_" + str(name).lower()) or ""


_DYNN_INDEX = None


# ---------------------------------------------------------------------------
# 宗族/家族定义表解析 (v14: AUH 东亚人名 — 存档只有 key, 显示名查游戏定义文件)
# ---------------------------------------------------------------------------

def _dynasty_name_of_dynn(nm, table):
    """dynn_X (dynn_Fujiwara / dynn_Li_674E) → 中文 (本地化表 → 码点兜底)。
    与 house_name_zh 取值链一致: 表值优先于键内码点 (游戏造键笔误兼容)。"""
    if not nm:
        return ""
    for cand in (nm, nm[len("dynn_"):] if nm.startswith("dynn_") else nm):
        v = localization.loc(table, cand)
        if v and v != cand:
            return v
    dec = zh(decode_codepoints(nm))
    if dec and any("\u3400" <= ch <= "\u9fff" for ch in dec):
        return dec
    return ""


def dynasty_name_of_key(key):
    """宗族 key (japanese_fujiwara / korean_choe_gyeongju) → 中文宗族名 (藤原 / 崔)。
    key → 游戏定义表 name=dynn_X → 本地化; 未知返回 ''。"""
    if not key:
        return ""
    nm = (localization.dynasty_table().get("dynasties") or {}).get(str(key)) or ""
    return _dynasty_name_of_dynn(nm, localization.table())


def house_name_of_key(key):
    """家族 key (house_fujiwara_kajuji) → 中文家族名 (勧修寺)。
    key → 游戏定义表 name=dynn_X → 本地化; 未知返回 ''。"""
    if not key:
        return ""
    nm = (localization.dynasty_table().get("houses") or {}).get(str(key)) or ""
    return _dynasty_name_of_dynn(nm, localization.table())


# ---------------------------------------------------------------------------
# v58 (问题4): 贵族地面前缀 (意大利 di／法兰西 de／德意志 von…)
# ---------------------------------------------------------------------------
# 游戏把「以地名为氏」的家族/宗族前缀写在 common/dynasty_houses/*.txt 与
# common/dynasties/*.txt 的 `prefix = "dynnp_X"`（如 house_canossa → dynnp_di，
# house_ghiberti → dynnp_de，house_wigeriche 无前缀），中文文案在
# localization/<lang>/dynasties/dynasty_names_l_<lang>.yml（dynnp_di = "迪· "）。
# 存档也会自带（dynasty_house[].prefix / dynasties[].prefix），以存档为准。
# 显示名 = 名 + 「·」+ 前缀 + 家族名（西方名序），即游戏的「罗伯托·迪·卡诺萨」。

_PREFIX_ZH_CACHE = {}


def _prefix_zh(pkey, table=None):
    """dynnp_X → 中文前缀 (迪·/德·/冯·)。取不到 / 占位符 / 未译 → ''。
    值尾的排版空格一律去掉（「迪· 」→「迪·」）。"""
    if not pkey:
        return ""
    if pkey in _PREFIX_ZH_CACHE:
        return _PREFIX_ZH_CACHE[pkey]
    t = table if table is not None else localization.table()
    v = localization.loc(t, pkey) or ""
    if (not v) or v == pkey or "$" in v or "[" in v or re.search(r"[A-Za-z_]", v):
        v = ""
    else:
        v = v.rstrip()
    _PREFIX_ZH_CACHE[pkey] = v
    return v


def _prefix_of_key(kind, key):
    """家族/宗族定义表里的前缀键。kind ∈ {"house", "dynasty"}; 未知返回 ''。"""
    if not key:
        return ""
    tb = localization.dynasty_table()
    bucket = "house_prefixes" if kind == "house" else "dynasty_prefixes"
    return (tb.get(bucket) or {}).get(str(key)) or ""


def house_prefix_zh(melt, house_id):
    """家族 id → 前缀中文 (迪·)。取值链: 存档 dynasty_house[].prefix → 游戏定义表。
    无前缀家族返回 ''。"""
    if house_id is None:
        return ""
    try:
        e = ((melt or {}).get("dynasties") or {}).get("dynasty_house") or {}
        rec = e.get(str(house_id)) or {}
        pkey = rec.get("prefix") or _prefix_of_key("house", rec.get("key"))
        return _prefix_zh(pkey)
    except Exception:
        return ""


def dynasty_prefix_zh(melt, dynasty_id):
    """宗族 id → 前缀中文。取值链: 存档 dynasties[].prefix → 游戏定义表。"""
    if dynasty_id is None:
        return ""
    try:
        e = ((melt or {}).get("dynasties") or {}).get("dynasties") or {}
        rec = e.get(str(dynasty_id)) or {}
        pkey = rec.get("prefix")
        if not pkey:
            key = rec.get("key")
            if isinstance(key, (str, int)):
                pkey = _prefix_of_key("dynasty", str(key))
        return _prefix_zh(pkey)
    except Exception:
        return ""


def house_name_zh(melt, house_id):
    """家族 id → 姓氏中文。取值链 (实测):
      1) dynasty_house[<id>].localized_name  (存档自带, 如 冯·大马士革 / 北家 / 庆州崔)
      2) 游戏家族定义表 (house key → dynn_Y → 本地化, v14: house_fujiwara_kajuji → 勧修寺)
      3) 本地化表 (name / dynn_ 键, 与其他文化一致 — 简体中文显示为准, 如
         dynn_Dou_9B26 → 斗; 表值优先于键内码点, 键码点 9B26=鬦 是游戏造键笔误)
      4) .name 的码点兜底 (dynn_Bian_908A → 边, 表缺键时的最后手段)
      5) .key 字段 (house_abbasid → dynn_Abbasid → 阿拔斯, v8.2)
      全部失败返回 ''。"""
    if house_id is None:
        return ""
    try:
        dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
        e = dh.get(str(house_id)) or {}
        # 1) 存档自带本地化名
        loc_name = e.get("localized_name") or ""
        if loc_name and any("\u3400" <= ch <= "\u9fff" for ch in loc_name):
            return zh(loc_name)
        # 2) 游戏家族定义表 (house key → dynn_Y → 本地化, v14)
        hkey = e.get("key")
        if isinstance(hkey, str):
            v = house_name_of_key(hkey)
            if v:
                return v
        # 3) 本地化表 (与其他文化同名取值链: 表优先)
        name = e.get("name") or ""
        t = localization.table()
        for cand in (name, name[len("dynn_"):] if name.startswith("dynn_") else name):
            v = localization.loc(t, cand)
            if v and v != cand:
                return v
        # 4) name 字段码点兜底 (dynn_ 前缀码点解码; 表缺键时用)
        if name.startswith("dynn_"):
            dec = zh(decode_codepoints(name[len("dynn_"):]))
            if dec and any("\u3400" <= ch <= "\u9fff" for ch in dec):
                return dec
        # 5) house key (house_abbasid → dynn_Abbasid → 阿拔斯, v8.2)
        if isinstance(hkey, str) and hkey.startswith("house_"):
            v = _dynn_lookup(t, hkey[len("house_"):])
            if v:
                return v
        return ""
    except Exception:
        return ""


def house_found_date(melt, house_id):
    """家族 id → 建立日 (dynasty_house[<id>].found_date); 无则 ''。

    v44 (问题1): 私生女别立家族时, 逐档差分只能在**下一档**发现变更, 而
    建立日是存档直给的权威日期 (阿德尔海德 1118.4.2) — 沿革点用它对表。"""
    if house_id is None:
        return ""
    try:
        dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
        return (dh.get(str(house_id)) or {}).get("found_date") or ""
    except Exception:
        return ""


def dynasty_id_of(melt, house_id):
    """家族 id → 所属宗族 id (dynasty_house[<id>].dynasty); 无则 None。"""
    if house_id is None:
        return None
    try:
        dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
        return dh.get(str(house_id), {}).get("dynasty")
    except Exception:
        return None


# v56 (性能): 宗族名/家族名取值链的按档缓存槽 (thread-local, 单槽 —— 换熔件即失效)。
# 见 `dynasty_name_zh` 与 `_dyn_caches`。
_TL = threading.local()


def dynasty_name_zh(melt, dynasty_id):
    """宗族 id → 宗族名中文。取值链 (实测):
      1) dynasties[<id>].localized_name    (Mod 档自带, 如 冯·大马士革 / 崔佛)
      2) 游戏宗族定义表 (key → dynn_X → 本地化, v14: japanese_fujiwara → 藤原;
         存档只存 key, 显示名在 common/dynasties/*.txt)
      3) .name 字段 → 本地化表 (dynn_Lithokristes → 利索克里斯蒂斯)
      4) .key 字符串 → 本地化表 (dynn_<key> / <key>, v8.2)
      5) 创始家族兜底: 同宗族内 found_date 最早的 house 取名 (边 / 奥尔西尼…)
      全部失败返回 '' (由调用方回退家族名)。

    v56 (性能): 5 号兜底原先**每次调用**全表扫 `dynasty_house` (本档 6332 条) ——
    单档重建里本函数调用 2.2 万次即 1.39 亿次 dict.get, cProfile 实测占
    `extract_snapshot` 总时的 **44%**。现按熔件缓存「宗族 → 最早 house」索引与
    逐 id 结果 (thread-local 单槽, 换熔件即失效), 复杂度由 O(宗族数 × house 数)
    降为 O(house 数 + 宗族数)。缓存只持有**当前档**熔件的引用, 由
    `extract_snapshot` 换档时清空 (见 `_dyn_caches`)。"""
    if dynasty_id is None:
        return ""
    c = _dyn_caches(melt)
    memo = c[2]
    if dynasty_id in memo:
        return memo[dynasty_id]
    val = ""
    try:
        dyn = (melt.get("dynasties") or {}).get("dynasties") or {}
        e = dyn.get(str(dynasty_id)) or {}
        # 1) 存档自带本地化名
        ln = e.get("localized_name") or ""
        if ln and any("\u3400" <= ch <= "\u9fff" for ch in ln):
            val = zh(ln)
        else:
            t = localization.table()
            # 2) 游戏宗族定义表 (v14: key → dynn_X → 本地化)
            key = e.get("key")
            if isinstance(key, str):
                val = dynasty_name_of_key(key)
            # 3) name 字段 (dynn_X) → 本地化表 / 码点兜底
            if not val:
                name = e.get("name") or ""
                if isinstance(name, str):
                    val = _dynasty_name_of_dynn(name, t)
            # 4) key 字符串 → 本地化表变体
            if not val and isinstance(key, str):
                for cand in ("dynn_" + key, key):
                    v = localization.loc(t, cand)
                    if v and v != cand:
                        val = v
                        break
            # 5) 创始家族兜底: 同宗族内 found_date 最早的 house (索引化)
            if not val:
                hid = _earliest_house_index(melt, c).get(dynasty_id)
                if hid is not None:
                    val = house_name_zh(melt, int(hid))
            val = val or ""
    except Exception:
        val = ""
    memo[dynasty_id] = val
    return val


def _dyn_caches(melt):
    """本线程当前的 (melt, 宗族→最早 house 索引, 宗族→名字 memo)。

    单槽: 熔件对象一变即重建 (身份判定 `is`)。thread-local 保证并发重建
    (pipeline 的后台传记线程与主线程) 不互相串味。"""
    c = getattr(_TL, "dyn", None)
    if c is None or c[0] is not melt:
        c = [melt, None, {}]
        _TL.dyn = c
    return c


def clear_dyn_caches():
    """释放本线程缓存的熔件引用 (换档/收尾时调; 见 `extract_snapshot`)。"""
    _TL.dyn = None


def _earliest_house_index(melt, c):
    """{宗族 id: 该宗族 found_date 最早的 house id} —— 每个熔件只扫一遍。"""
    if c[1] is None:
        dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
        best = {}
        for hid, h in dh.items():
            if not isinstance(h, dict):     # v7: none 条目防护
                continue
            did = h.get("dynasty")
            if did is None:
                continue
            fd = h.get("found_date") or "9999.1.1"
            cur = best.get(did)
            if cur is None or fd < cur[0]:
                best[did] = (fd, hid)
        c[1] = {k: v[1] for k, v in best.items()}
    return c[1]


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------

def _sanitize_none(o):
    """递归把 Clausewitz 空值字符串 'none' 替换为 None (v7)。

    rakaly json 把 `= none` 渲染成字符串 'none'; 而代码里的 `x or {}` 防护
    对真值字符串 'none' 无效 ('none' or {} → 'none'), 随后 .get() 即崩溃
    (实测 881.1.11 熔件含 6938 个 'none', living 4508 / dead 262 / 标题 1...)。
    'none' 语义上等同字段缺失, 替换为 None 后所有 or {} 防护恢复正常。

    v49 (O2): 该清扫已折进 `_merge_dup_pairs` 的同一趟遍历 (实测省 2.7 s/档),
    本函数保留供外部脚本对照/兜底, 不再出现在 `load_melt` 的热路径上。"""
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if v == "none":
                o[k] = None
            elif isinstance(v, (dict, list)):
                _sanitize_none(v)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            if v == "none":
                o[i] = None
            elif isinstance(v, (dict, list)):
                _sanitize_none(v)
    return o


def _clean_none_list(lst):
    """把列表元素里的 'none' 换成 None (递归进嵌套列表)。v49 (O2)。"""
    for i, v in enumerate(lst):
        t = type(v)
        if t is str:
            if v == "none":
                lst[i] = None
        elif t is list:
            _clean_none_list(v)


def _merge_dup_pairs(pairs):
    """json object_pairs_hook: 重复键合并 + 空值清扫 (一趟做两件事)。

    v15: Clausewitz/rakaly 常把同一键渲染多遍 (agent_slots / family_data.spouse /
    temporary_opinion / variables.item 等), `json.load` 默认只留最后一个 → 丢数据
    (阴谋参与者即因此全部丢失)。故重复键按出现顺序并成列表, 单次出现的键原样返回。

    v49 (O2) 两处提速 (244 MiB 档实测 13.35 s → 11.9 s):
      - **快路**: 先走 C 级 `dict(pairs)` + 键数判定 —— 实测 3626941 个对象里只有
        75746 个 (2.09%) 真有重复键, 其余不必进 Python 慢路 (旧实现给每个键都建
        list 再收敛);
      - **顺势清扫**: 同一趟把值 'none' 换成 None (v7 的 `x or {}` 防护依赖它),
        取代原先整树重走的 `_sanitize_none` (实测 2.7 s/档)。
    文档根是 dict (熔件必是), 故每个对象都过这里; 字典值构成的列表由
    `_clean_none_list` 递归覆盖 —— 与旧 `_sanitize_none` 覆盖面等价。"""
    d = dict(pairs)
    if len(d) != len(pairs):
        out = {}
        for k, v in pairs:
            out.setdefault(k, []).append(v)
        d = {k: (v[0] if len(v) == 1 else v) for k, v in out.items()}
    for k, v in d.items():
        t = type(v)
        if t is str:
            if v == "none":
                d[k] = None
        elif t is list:
            _clean_none_list(v)
    return d


def open_melt_text(path):
    """以文本模式打开熔件/边车文件 (兼容 `.json` / `.json.gz` / `.json.xz`)。

    v44 (问题5): 冷熔件 gzip 归档后, 全部读取口统一走这里 —— 调用方不必关心
    后缀 (实测 gzip-6 压到 15.3%, 读取只多 0.6s)。
    v49 (方案①): 再加 `.json.xz` (冷档默认压缩格式, 体积为 gzip 的 61.5%,
    解压 1.22 s vs 0.46 s/244 MiB)。
    v49 (O2): 只要 dict 的读取口 (`load_melt` / `load_melt_index`) 改走二进制
    `_read_melt_bytes` (快 0.5 s/档); 需要文本句柄的调用方仍用本函数。"""
    low = str(path).lower()
    if low.endswith(".xz"):
        return lzma.open(path, "rt", encoding="utf-8")
    if low.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def _melt_binary(path):
    """熔件/边车的**二进制**句柄 (`.json` / `.json.gz` / `.json.xz` 都认)。
    v66: 从 `_read_melt_bytes` 里抽出来, 供流式截段 (`load_melt_section`) 复用。"""
    low = str(path).lower()
    if low.endswith(".xz"):
        return lzma.open(path, "rb")
    if low.endswith(".gz"):
        return gzip.open(path, "rb")
    return open(path, "rb")


def _read_melt_bytes(path):
    """二进制整读熔件/边车 (`.json` / `.json.gz` / `.json.xz` 都认)。v49 (O2):
    `json.loads(bytes)` 由 C 解析器自己解 UTF-8, 比文本模式少一层增量解码器
    (实测省 ≈0.5 s/244 MiB 档)。"""
    with _melt_binary(path) as fp:
        return fp.read()


def melt_file_exists(path):
    """给定熔件基准路径 (`...melt_<日期>.json`), 返回**实际存在**的那一份
    (明文优先, 其次 `.gz`, 再次 `.xz`); 都不在返回 None。
    供拼接路径的调用方收口后缀差异 (v49 方案①: 三种后缀)。"""
    for cand in (str(path), str(path) + ".gz", str(path) + ".xz"):
        if os.path.isfile(cand):
            return cand
    return None


def load_melt_section(path, key):
    """只取熔件顶层 `key` 段的 JSON 对象 (流式截段; v66)。

    为什么: 熔件顶层 `landed_titles` 段起于解压流 3.4 MB 处 (全量 206 MB), 只取
    这一段比 `load_melt` (实测 1–3 min/档) 快两个数量级 (0.3 s/档)。逐档回填
    `cache["title_dyn_names"]` 只用到这一段 (见 `_latch_title_dyn_names`), 故单独
    开一个读取口, 而不为 84 档跑 84 次全量载入。

    取法: 先流式找到 `"<key>":`, 再按 JSON 的字符串/转义规则做花括号配对, 截到该
    对象闭合即止; 段落字节仍交 `json.loads` 解析, 且**与 `load_melt` 同一个
    `object_pairs_hook=_merge_dup_pairs`** (Clausewitz 会把同一键渲染多遍, 默认的
    last-wins 会丢数据) —— 故结果与 `load_melt(path)[key]` **逐键相同** (调用方可用
    load_melt 复核, 见 tools/backfill_title_dyn_names.py 的 `--check`)。取不到该段
    返回 None。"""
    pat = ('"%s":' % key).encode("utf-8")
    buf = b""
    off = -1
    with _melt_binary(path) as fp:
        while off < 0:
            chunk = fp.read(1 << 20)
            if not chunk:
                return None
            buf += chunk
            i = buf.find(pat)
            if i >= 0:
                off = i + len(pat)
        i, start, depth = off, -1, 0
        while True:
            while i >= len(buf):
                chunk = fp.read(1 << 20)
                if not chunk:
                    return None
                buf += chunk
            c = buf[i:i + 1]
            if start < 0:
                if c in (b" ", b"\r", b"\n", b"\t"):
                    i += 1
                    continue
                if c != b"{":
                    return None
                start, depth = i, 1
                i += 1
                continue
            if c == b'"':
                i += 1
                while True:
                    while i >= len(buf):
                        chunk = fp.read(1 << 20)
                        if not chunk:
                            return None
                        buf += chunk
                    ch = buf[i:i + 1]
                    if ch == b"\\":
                        i += 2
                        continue
                    if ch == b'"':
                        i += 1
                        break
                    i += 1
                continue
            if c == b"{":
                depth += 1
            elif c == b"}":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
    return json.loads(buf[start:i], object_pairs_hook=_merge_dup_pairs)


def load_melt_landed_titles(path):
    """熔件 → `landed_titles.landed_titles` 段 (v66 便捷口, 与 `_db(melt)` 口径的
    头衔字典同构)。段缺失返回 {}。"""
    sect = load_melt_section(path, "landed_titles")
    if not isinstance(sect, dict):
        return {}
    return sect.get("landed_titles") or {}


def melt_stem(path):
    """熔件/边车路径去掉压缩后缀 (`x.json.xz` → `x.json`; 无后缀原样)。v49。"""
    p = str(path)
    low = p.lower()
    for suf in (".xz", ".gz"):
        if low.endswith(suf):
            return p[:-len(suf)]
    return p


# ---------------------------------------------------------------------------
# v49 (O4): 进程内熔件记忆
# ---------------------------------------------------------------------------
# 同一进程内反复载入**同一份**熔件的路径实测不少:
#   - 后台传记线程对同一位传主的 N 篇十年传记, 每篇都 load_latest_melt 同一份
#     最新档 (5 篇 = 5 × 6 s 白读);
#   - 终传先读 last_date 那一档, 再读"死亡尾年"那一档 (两份不同档, LRU=2 兜住);
#   - watch 刚并入的档 (临时路径 → 归位后路径, 靠 melt_memo_move 跟过去)。
# 键 = (绝对路径, 大小, mtime_ns): 文件被重压/替换/改写后自动失效。
# 上限 2 份: 单份 244 MiB 档的 dict ≈ 1.3 GB 工作集 (实测), 两份 ≈ 2.6 GB。
# 内存吃紧的机器可设环境变量 ROMAN_MELT_MEMO=0 关闭 (或调 set_melt_memo()).
_MELT_MEMO = OrderedDict()          # key -> (size, mtime_ns, dict)
_MELT_MEMO_MAX = 2
_MELT_MEMO_ON = os.environ.get("ROMAN_MELT_MEMO", "1").lower() not in ("0", "false", "no")
_MELT_MEMO_LOCK = threading.Lock()


def set_melt_memo(enabled):
    """开关熔件记忆 (关闭时清空已缓存的两份)。返回新状态。"""
    global _MELT_MEMO_ON
    _MELT_MEMO_ON = bool(enabled)
    if not _MELT_MEMO_ON:
        melt_memo_clear()
    return _MELT_MEMO_ON


def melt_memo_clear():
    """清空熔件记忆, 返回清掉的份数。"""
    with _MELT_MEMO_LOCK:
        n = len(_MELT_MEMO)
        _MELT_MEMO.clear()
    return n


def melt_memo_stats():
    """(是否启用, 已缓存份数, 上限)。"""
    return _MELT_MEMO_ON, len(_MELT_MEMO), _MELT_MEMO_MAX


def _melt_memo_key(path):
    try:
        st = os.stat(os.path.abspath(path))
    except OSError:
        return None
    return (os.path.abspath(path), st.st_size, st.st_mtime_ns)


def _melt_memo_get(key):
    with _MELT_MEMO_LOCK:
        hit = _MELT_MEMO.get(key)
        if hit is None:
            return None
        _MELT_MEMO.move_to_end(key)
        return hit[2]


def _melt_memo_put(key, data):
    with _MELT_MEMO_LOCK:
        _MELT_MEMO[key] = (key[1], key[2], data)
        _MELT_MEMO.move_to_end(key)
        while len(_MELT_MEMO) > _MELT_MEMO_MAX:
            _MELT_MEMO.popitem(last=False)


def melt_memo_move(old_path, new_path):
    """熔件归位/改名后把记忆里的键跟过去 (os.replace 保 mtime 与内容)。

    必须在 `os.replace` **之前**调用 (那时源文件还在, 才能取到 size/mtime)。
    返回是否跟成功。"""
    if not _MELT_MEMO_ON:
        return False
    old_key = _melt_memo_key(old_path)
    if old_key is None:
        return False
    with _MELT_MEMO_LOCK:
        hit = _MELT_MEMO.pop(old_key, None)
        if hit is None:
            return False
        _MELT_MEMO[(os.path.abspath(new_path), old_key[1], old_key[2])] = hit
        _MELT_MEMO.move_to_end((os.path.abspath(new_path), old_key[1], old_key[2]))
    return True


def melt_memo_drop(path):
    """丢掉某路径的熔件记忆 (压缩归档后源文件消失, 键已不可达 —— 顺手释放)。"""
    if not _MELT_MEMO_ON:
        return False
    key = _melt_memo_key(path)
    if key is None:
        return False
    with _MELT_MEMO_LOCK:
        return _MELT_MEMO.pop(key, None) is not None


def load_melt(path, use_memo=True):
    """读熔件 → dict。重复键合并与 'none'→None 都在 `_merge_dup_pairs` 一趟完成。

    v49 (O2): **解析期间关掉自动 GC** —— 干净进程单次加载实测 244 MiB 档
    10.7 s → 5.9 s (峰值内存不变, 2325 MiB)。原因: object_pairs_hook 是 Python
    函数时, C 扫描器要为每个对象建 pair 列表并回调, 途中反复触发 gen0/1/2 回收,
    而此刻对象图已上千万节点, 每次 gen2 都要遍历全图; 纯 C 解析只在末尾承担一次。
    出栈立刻恢复; JSON 无环, 途中产生的都是引用计数即可释放的垃圾, 无泄漏风险。

    v49 (O4): `use_memo` 时走进程内熔件记忆 (命中直接返回同一份 dict, 见
    `_MELT_MEMO` 注释) —— 熔件内容只读 (全树无一处回写), 故可安全共享。"""
    key = _melt_memo_key(path) if (use_memo and _MELT_MEMO_ON) else None
    if key is not None:
        hit = _melt_memo_get(key)
        if hit is not None:
            return hit
    raw = _read_melt_bytes(path)
    gc_was_on = gc.isenabled()
    if gc_was_on:
        gc.disable()
    try:
        data = json.loads(raw, object_pairs_hook=_merge_dup_pairs)
    finally:
        if gc_was_on:
            gc.enable()
    if key is not None:
        _melt_memo_put(key, data)
    return data


def _db(melt):
    """记忆对象库: {记忆ID(str): {type, participants, creation_date, ...}}"""
    return melt.get("character_memory_manager", {}).get("database") or {}


def _living(melt):
    return melt.get("living") or {}


def _dead_unprunable(melt):
    return melt.get("dead_unprunable") or {}


def _dead_prunable(melt):
    return (melt.get("characters") or {}).get("dead_prunable") or {}


def all_characters(melt):
    out = {}
    out.update(_living(melt))
    out.update(_dead_unprunable(melt))
    out.update(_dead_prunable(melt))
    return out


def mem_ids_of(char_obj):
    """角色 alive_data.memories (记忆ID列表); 死者 alive_data 被移除时,
    回退 dead_data.memories (v8: 曾为玩家 was_playable 的角色死亡时,
    游戏把记忆复制进 dead_data.memories 保留, 实测崔佛死档 6 条全在)。"""
    c = char_obj or {}
    ids = (c.get("alive_data") or {}).get("memories") or []
    if ids:
        return ids
    return (c.get("dead_data") or {}).get("memories") or []


def nickname_at(rec, as_of=None):
    """v49 (O5): 该角色在 as_of 时点的绰号 (查 `nickname_history` 变更点)。

    返回 ''=该时点无绰号, None=无沿革/时点早于首点 (调用方回退读熔件)。
    as_of 为空时取沿革末值 (现值)。"""
    nh = (rec or {}).get("nickname_history") or []
    if not nh:
        return None
    if not as_of:
        return nh[-1].get("nickname") or ""
    val = None
    for pt in nh:
        if date_key(pt.get("from") or "0.0.0") <= date_key(as_of):
            val = pt.get("nickname") or ""
        else:
            break
    return val


def find_player(melt):
    cpc = melt.get("currently_played_characters") or []
    if cpc:
        return int(cpc[0])
    pc = melt.get("played_character")
    if isinstance(pc, dict) and pc.get("character"):
        return int(pc["character"])
    return None


def family_of(char_obj):
    fd = (char_obj or {}).get("family_data") or {}
    out = {}
    for key in ("primary_spouse", "spouse", "former_spouses", "child",
                "father", "mother", "siblings", "real_father",
                "concubine", "former_concubines"):
        v = fd.get(key)
        if v is None:
            continue
        ids = [int(x) for x in (v if isinstance(v, list) else [v])]
        out[key] = ids
    return out


def kills_of(char_obj):
    """角色击杀 id 列表: 在世读 alive_data.kills, 死后读 dead_data.kills。"""
    c = char_obj or {}
    out = list((c.get("alive_data") or {}).get("kills") or [])
    out += list((c.get("dead_data") or {}).get("kills") or [])
    return [int(x) for x in out if isinstance(x, int) or str(x).isdigit()]


def date_key(s):
    """'869.2.22' → (869, 2, 22); 非法输入 → (9999, 0, 0)。"""
    try:
        return tuple(int(x) for x in str(s).split("."))
    except Exception:
        return (9999, 0, 0)


def date_filekey(s):
    """'869.2.22' → '869_02_22' (与 melt 文件命名一致)。"""
    return "_".join(f"{int(x):02d}" for x in str(s).split("."))


# ---------------------------------------------------------------------------
# 记忆条目
# ---------------------------------------------------------------------------

def memory_brief(mem_id, e):
    """记忆对象 → 精简条目 (附记忆ID; vars 带 {flag,type,identity} 以便取关联对象)。
    v21: 变量类型为 flag 时补存其值 (data.flag) — 刑虐记忆的
    castrated / castrated_beardless 标志此前被丢弃, 阉割无从渲染。"""
    vars_out = []
    for f in (e.get("variables") or {}).get("data") or []:
        d = f.get("data") or {}
        vars_out.append({
            "flag": f.get("flag"),
            "type": d.get("type"),
            "identity": d.get("identity"),
            "value": d.get("flag") if (d.get("type") or "") == "flag" else None,
        })
    return {
        "id": mem_id,
        "type": e.get("type"),
        "participants": e.get("participants"),
        "creation_date": e.get("creation_date"),
        "end_date": e.get("end_date"),
        "vars": vars_out,
    }


# ---------------------------------------------------------------------------
# 缓存库 (schema 5: 每玩家一份缓存)
# ---------------------------------------------------------------------------

EMPTY_CACHE = {
    "schema": 5,
    "player_id": None,
    "player_name": None,
    "house_name": None,       # 家族名 (边), 姓名字显示用
    "dynasty_id": None,       # 宗族 id (v6: 文件夹按宗族划分)
    "dynasty_name": None,     # 宗族名 (边), 输出文件夹名依据
    "playthrough_id": None,   # 战役标识 (存档 playthrough_id; 同一战役的存档共享)
    "game_version": None,
    "sources": [],
    "last_date": None,
    "player_death": None,     # 首次检测到玩家 dead_data 即写入 {date, reason, killer, kills}
    "bio_generated": False,   # 终传是否已生成 (每次玩家角色死亡只生成一篇)
    "bio_decades": [],        # v8: 已生成的十年传记序号 [1,2,...] (每活满10年一篇)
    "output_folder": None,    # 会话输出文件夹名 (watch/continue 绑定, 见 pipeline)
    "player_title_history": [],  # [{date, name}] 玩家主头衔名变化 (复兴党流亡委员会等)
    "realm_history": [],         # [{date, holders:{title_id: holder_id}}] 关键头衔持有者逐年
    # v66: 头衔动态名沿革 {tid: [{from, name}]} —— `specific_title_name` 是"只有该
    # 日期那一档才有的现值" (v48 §4B 同类), 逐档只记变化点 (实测 84 档 ≈ 215 KB)。
    # 供 facts._dyn_name_at / _site_name 按日期取「用地名」用 (游牧迁移改名)。
    "title_dyn_names": {},
    "court_positions": [],       # [{date, positions:[{type, employee, hire_date, task}]}] 玩家营/廷内僚属任职逐年 (v7; employer==玩家, 非玩家自身官职)
    "court_office_history": [],  # v36 (问题2): [{date, offices:[{type, employer, hire_date}]}] 主角**获授**的朝廷职位逐年 (employee==玩家, employer==他人)
    "house_motto": None,         # 玩家家族家训 (dynasty_house.motto, 字符串或模板 dict) (v7)
    "characters": {},
    "relations": {},
    # v28b: 叛乱派系 (农民/民粹/游牧 起义) 领袖逐档差分 — 称谓用
    # (「农民起义领袖叠溪寋」; 存档只存当前派系, 无起止日期)
    "factions": {},
    # v31: 牵制逐档差分 (relations.active_relations.active_hook_*) — 只收
    # 持有者或对象为玩家者; 存档不给创建日, 逐档差分即得「首次见于记载」。
    "hooks": {},
    # v32: 纳妾类关系好感逐档差分 (opinions.active_opinions 的 temporary_opinion) —
    # 存档里「强行纳为侧室」带确切 start_date (forced_me_concubine_marriage_opinion),
    # 这是「劫掠掳人 → 强纳为妾」唯一带日期的记录 (纳妾本身不留记忆)。
    "opinions": {},
    # v35: 奴役关系逐档差分 (opinions.active_opinions[*].scripted_relations.slave) —
    # Carnalitas 的 carn_enslave_effect 在奴役的同一刻 `release_from_prison = yes`
    # (见 Mod common/scripted_effects/carn_slave_effects.txt), 故存档里那句
    # 「释放」记忆正是「没为奴隶」这一步; 该关系是唯一能把两者区分开的权威数据。
    # v38 (问题4): 记录**全部**主奴关系 (不再只收主角为主的那部分), 并记下每档
    # 每名奴隶的主人 (`owner` 随档刷新) —— 「被卖给谁」由此可查 (见
    # `enslavement_traces`)。key = "<主人id>><奴隶id>"。
    "enslavements": {},
    # v38 (问题4/问题1): Carnalitas 关系好感逐档差分 (强奸/奴役/逼良为娼/前主奴)。
    # 这些好感**自带 start_date** (比逐档差分精确), 且覆盖「不留记忆」的互动:
    # 出售与释放奴隶只留一条 `carn_former_slave_or_slave_owner_opinion`。
    # 只收涉主角者 (key = "<持有者id>><对象id>><modifier>")。
    "carnal_opinions": {},
    # v38 (问题1): 角色修正 `carn_recently_raped`(最近被强奸, 5 年) 逐档差分 —
    # 受害方身上唯一带「何时」的信号 (key = "<角色id>>carn_recently_raped")。
    "carnal_modifiers": {},
    # v43: 母系婚 (入赘) 婚姻对 —— 存档里婚姻线系只在 relations.active_relations
    # 的 `{"first":A,"second":B,"matrilineal":true}` 条目上出现 (游戏简中把这一档
    # 叫「母系婚姻」, 交互界面写作「切换入赘」; 规则: 所生子女属**母方**家族)。
    # 逐档闩存, 一旦见到永久保留 —— 婚姻离异/丧偶后该条目会从存档消失, 而传记要
    # 写的是当年那桩婚事。key = "<小id>><大id>", value = 首次见于记载的档期。
    "matrilineal_pairs": {},
    # v50 (v47 方案 B): 结仇/结交缘由闩存 —— 游戏只在 `opinions.active_opinions`
    # 里为**当前仍存在**的关系保留 `scripted_relations.<kind>.reason` (成因键,
    # 本地化模板见 `data/localization.json` → `relation_templates`), 关系一方死亡
    # 或关系解除后条目连同 reason 一起从存档消失: 诺兰 1126.12.4 的结仇在
    # 1127/1130 档带 `rival_called_me_a_disgrace`, 1143 档 (对象 1142.9.8 卒) 起
    # 0 条; 田所2 战役四对 rival/grudge 的 reason 也分别在 1~13 年后随条目消失。
    # 生成所用熔件恒为**最新**档, 故「结仇早、对方已死」的仇人一律读不到缘由 ——
    # 逐档并入时把涉主角的 reason 闩存 (首见即留, 不覆盖), 生成时作熔件的回退源。
    # key = "<owner>|<target>|<kind>" (方向与存档一致, 互为仇敌时两条各存)。
    "relation_reasons": {},
    # v60 (问题3): 婚配闩存 —— 主角一方的 `family_data` 在死亡档会被清空
    # (崔佛 881/882 档 family_data=[]), 而**对方**身上的反向指针
    # (`concubinist` / `former_concubinists` / `spouse` / `former_spouses`)
    # 逐档在册。逐档扫全角色把「与主角的婚配」闩存下来, 首见即留,
    # 供 facts 在主角自身 family 为空时回读 (见 `_latch_spouses`)。
    # key = "<主角id>><对方id>", value = {"kind","first_seen","source"}。
    "spouse_latch": {},
    # v60 (问题4): 囚禁交接闩存 —— {"<被囚者id>": {"from","to","since","first_seen"}}。
    # 传主死后其在押囚犯的监禁者转归继位者 (崔佛卒于 881.1.1, 四人改归 15179),
    # 而该类档期的 `find_player` 已是继位者 —— 传主这一侧只有靠同战役后继档
    # 闩存, 才能在传记里写出「转归其妾埃尔梅辛达」(见 `_latch_prison_succession`)。
    "prison_succession": {},
    # v56 (问题3): 出狱缘由闩存 — {"<被囚者>><监禁者>><日期>": {"kind","src","first_seen"}}。
    # 源数据 = 出狱当日新得的出狱类好感 (自带 start_date) 与 `favor_hook`/`indebted_hook`
    # (到期日减 10 个日历年即创建日)。出狱类好感 10 年衰减且随持有者死亡消失, 而终传
    # 只载末档熔件 ⇒ 十年前那批释放的缘由只能靠逐档闩存回读 (见 _latch_prison_manners)。
    "prison_manners": {},
    # v44 (问题2): 存档 played_character.legacy = **玩家角色接替链** (有序带日期):
    # [{"cid": 62045, "date": "1066.9.15"}, {"cid": 16852591, "date": "1117.6.19"}]
    # 末条即当前传主, 起算日 = 继位日 (前一任死亡当日)。新版本玩家可从宗族里
    # 挑人继位, 亲缘判定不足以还原「怎么连起来的」, 故此链以存档为准。
    "played_legacy": [],
    # v53 (问题1): 封臣合同变化点 {cid: [{date, liege, flags}]}
    "char_vassal_history": {},
    # v53 (问题3): 天命循环阶段变化点 [{date, phase, start}]
    "dynastic_cycle_history": [],
}


def new_cache():
    """全新空缓存 (深拷贝, 避免 dict(EMPTY_CACHE) 浅拷贝共享 sources/characters 等容器)。"""
    return copy.deepcopy(EMPTY_CACHE)


def cache_path_for(cache_dir, player_id):
    return os.path.join(cache_dir, f"player_{player_id}.json")


# 同路径缓存写互斥锁 (主线程并入 与 后台传记线程回写 可能并发写同一缓存文件,
# 共享固定 .tmp 会互相截断 → 缓存损坏 + WinError 32, 见 2026-08-28 23:30 事件)
_SAVE_LOCKS = {}
_SAVE_LOCKS_GUARD = threading.Lock()


def _save_lock(path):
    with _SAVE_LOCKS_GUARD:
        lock = _SAVE_LOCKS.get(path)
        if lock is None:
            lock = threading.Lock()
            _SAVE_LOCKS[path] = lock
        return lock


# v13 (性能): 缓存文件 mtime 记忆 — watch 每轮 poll 都要重读全部玩家缓存
# (4 份 × 60–160MB JSON), 不变化的缓存直接复用, 避免处理速度赶不上游戏推进。
_CACHE_LOAD_MEMO = {}   # path -> (mtime, cache_dict)


def load_cache(path, fresh=False):
    """读玩家缓存 (v13: mtime 记忆, fresh=True 强制重读 — 提取/写入路径用)。
    注意: 返回的 dict 可能被调用方修改; 修改路径一律传 fresh=True 取独立副本。"""
    if not os.path.isfile(path):
        return new_cache()
    if not fresh:
        try:
            mt = os.path.getmtime(path)
        except OSError:
            mt = None
        hit = _CACHE_LOAD_MEMO.get(path)
        if hit is not None and hit[0] == mt:
            return hit[1]
    try:
        with open(path, encoding="utf-8") as fp:
            cache = json.load(fp)
        # 兼容旧 schema: 补齐 v4 字段
        for k, v in EMPTY_CACHE.items():
            cache.setdefault(k, v)
        if not fresh:
            try:
                _CACHE_LOAD_MEMO[path] = (os.path.getmtime(path), cache)
            except OSError:
                pass
        return cache
    except Exception as e:
        # 缓存文件损坏 (并发写共享 .tmp 遗留): 改名留证并告警, 不再静默当空缓存用
        # (空缓存会以 seq=0 参与选路, 把本会话数据误并进旧会话文件夹, 见 2026-08-28 事件)
        try:
            corrupt = f"{path}.corrupt.{time.strftime('%Y%m%d_%H%M%S')}"
            os.replace(path, corrupt)
            llm.log(f"[缓存损坏] {path} 解析失败 ({e}) — 已改名 {os.path.basename(corrupt)} "
                    f"留证, 返回空缓存 (请用 rebuild-cache 重建)")
        except Exception:
            llm.log(f"[缓存损坏] {path} 解析失败 ({e}) — 改名失败, 返回空缓存")
    return new_cache()


def save_cache(cache, path):
    """原子写玩家缓存。

    v49 (O3): 改紧凑分隔符 (旧为 `indent=1`) —— 实测诺兰 153 MB 缓存
    8.47 s/146.3 MiB → 5.84 s/86.8 MiB (写快 2.6 s, 体积 -40.7%);
    读者一律 json.load, 不依赖缩进。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _save_lock(path):
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(cache, fp, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)  # 原子替换, 防并发读写撕裂


def char_record(cache, cid):
    key = str(cid)
    if key not in cache["characters"]:
        cache["characters"][key] = {
            "id": cid,
            "first_name": None,
            "name_zh": None,
            "house_name": None,     # 家族名 (边 / 北家), v14: 西方名序的姓
            "dynasty_name": None,   # 宗族名 (边 / 藤原), v14: 东方名序的姓
            "name_full": None,      # 姓+名 (边诚)
            "birth": None,
            "death": None,
            "female": False,       # v26: 性别 (熔件 female 字段只在女性身上出现)
            "dynasty_house": None,
            # v44 (问题1): [{from, house_id, house_name, dynasty_id, dynasty_name}]
            # 家族沿革变更点 (首见即记)。私生女另立家族 (如阿德尔海德 1118.4.2
            # 别立冯·亚琛氏) 与家族改名 (冯·亚琛 → 冯) 都只体现在这里 ——
            # 逐档差分是唯一来源, 游戏不为改名留任何记忆。
            "house_history": [],
            "culture": None,
            "culture_history": [],  # v30: [{from, culture}] 族属变更点 (首见即记)
            "faith": None,
            "faith_history": [],   # v26: [{from, faith}] 改信变化点 (首见即记)
            # v49 (O5): [{from, nickname}] 绰号变化点 (首见即记, 含空串 = 无绰号)。
            # 十年传记的「按时代取绰号」原要为此整份载入该时代末档熔件 —— 244 MiB
            # 档实测 6–18 s 只为取一个字符串; 锁存后直接读缓存。实测 living 角色
            # 恒有 nickname_text 键 (空串=无绰号), 故目标集里每人至少一点。
            "nickname_history": [],
            "traits": [],
            "trait_history": {},    # {特质key: [{from, to, first}]} 获得/消失区间 (v4)
            "trait_xp": [],         # v32: [{from, traits, xp}] 轨道 XP 样本 (与 traits 对齐)
            "family": {},           # 亲属 id 集; v31 另积 ever_spouses (历史上所有配偶)
            "court": {},            # v31: {employer, knight, join_court_date} 宫廷身份
            "landed": {},
            "memories": [],
            "kills": [],        # v8: 击杀 id 列表 (alive_data.kills ∪ dead_data.kills, 跨年累积)
            # v34 (问题7): 囚禁区间 [{from, to, imprisoner, type, since}]
            # to 为 null = 仍在押; 释放记忆缺失时凭此判定「已出释」
            "prison_history": [],
        }
    return cache["characters"][key]


# ---------------------------------------------------------------------------
# 姓名解析
# ---------------------------------------------------------------------------

_NAMES = None
_NAMES_META = {}


def _load_names(names_path, melt=None):
    """全档人名表 {角色id: {name_zh, house_name, dynasty_name}}。

    v28: 角色 id 只在**同一存档/战役内**有意义 —— 该表是「某一次 build_names
    时那一份 melt」的快照 (payload.source), 跨战役复用同名 id 会给出别人的名字
    (实测: 陆氏战役 16293 本名「郑良士」, 表里同名 id 是另一战役的「藤原利仁」)。
    故表内 playthrough_id 与当前熔件不一致时返回空表; 两边都有战役号才校验。"""
    global _NAMES, _NAMES_META
    if _NAMES is None:
        payload = {}
        try:
            with open(names_path, encoding="utf-8") as fp:
                payload = json.load(fp) or {}
        except Exception:
            payload = {}
        _NAMES = payload.get("names") or {}
        _NAMES_META = payload
    tbl_pt = _NAMES_META.get("playthrough_id")
    if tbl_pt and melt is not None:
        m_pt = melt.get("playthrough_id")
        if m_pt and str(m_pt) != str(tbl_pt):
            return {}
    return _NAMES


def resolve_full_name(cache, cid, names_path=None, melt=None):
    """角色 id → 完整中文名 (v13: 统一走 display_name, 名序/父名按游戏规则)。
    仅剩调用方兼容 (summarize_relations 等), 新代码一律用 display_name。"""
    return display_name(cache, cid, melt=melt, names_path=names_path)


# ---------------------------------------------------------------------------
# 文化姓名顺序 (v5: 东方姓在前, 西方名在前)
# ---------------------------------------------------------------------------

EASTERN_NAME_ORDERS = {"DYNASTY_ALWAYS_FIRST", "JAPANESE"}


def name_order_of(melt, culture_id):
    """文化 id → name_order_convention ('' = 西方默认; DYNASTY_ALWAYS_FIRST/
    JAPANESE = 姓在前)。melt 缺失或文化未知返回 ''。"""
    if melt is None or culture_id is None:
        return ""
    cultures = (melt.get("culture_manager") or {}).get("cultures") or {}
    e = cultures.get(str(culture_id)) or {}
    return e.get("name_order_convention") or ""


def _family_name_order(cache, rec, melt, chars=None):
    """角色自身文化缺失 (死后清空/幼年未录) 时, 依亲属文化推断名序:
    父 → 母 → 同胞 → 子女 → 配偶 (子承父/母文化, 同胞同源; 配偶跨族婚姻参考价值最低, 放最后)。
    返回 name_order_convention 字符串 ('' = 西方默认); 亲属文化全部缺失时返回 None。
    v19: 亲属不在玩家缓存时兼查熔件全量角色 (chars — display_name 已持有全角色索引)。"""
    if melt is None:
        return None
    cultures = (melt.get("culture_manager") or {}).get("cultures") or {}
    fam = rec.get("family") or {}
    for key in ("father", "mother", "siblings", "child",
                "primary_spouse", "spouse", "former_spouses"):
        for x in (fam.get(key) or []):
            r = (cache.get("characters") or {}).get(str(x)) or {}
            cul = r.get("culture")
            if (cul is None or str(cul) not in cultures) and chars is not None:
                cul = (chars.get(str(x)) or {}).get("culture")
            if cul is None or str(cul) not in cultures:
                continue
            return cultures[str(cul)].get("name_order_convention") or ""
    return None


def name_display(cache, cid, melt=None, names_path=None):
    """(v13 统一出口) 按游戏规则的显示名 — 等价于 display_name, 保留为兼容别名。"""
    return display_name(cache, cid, melt=melt, names_path=names_path)


# ---------------------------------------------------------------------------
# v13: 统一姓名函数 (游戏同规则) — 全项目唯一出口
# ---------------------------------------------------------------------------

_PATRONYM_RULES_CACHE = None


def _patronym_rules_table():
    """data/patronym_rules.json 惰性加载 (facts 同源文件)。"""
    global _PATRONYM_RULES_CACHE
    if _PATRONYM_RULES_CACHE is None:
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "patronym_rules.json")
            with open(p, encoding="utf-8") as fp:
                _PATRONYM_RULES_CACHE = json.load(fp)
        except Exception:
            _PATRONYM_RULES_CACHE = {}
    return _PATRONYM_RULES_CACHE


def _template_of_culture(melt, cul):
    """文化 id → culture_template (norse/han…); 未知返回 ''。"""
    if melt is None or cul is None:
        return ""
    cultures = (melt.get("culture_manager") or {}).get("cultures") or {}
    e = cultures.get(str(cul)) or {}
    return e.get("culture_template") or ""


def _culture_template_of(cache, cid, melt, chars=None, memo=None):
    """角色文化模板 (norse/han…), 供父名与名序推断 (v13)。

    命名文化沿父系继承 (CK3 子女随父文化), 推断优先级 (各步只看「自身 culture」,
    递归只走父系线; 同胞/母/宗族一律取自身, 防姻亲/继亲文化经深链泄漏):
      1) 自身 culture (缓存 → 熔件角色);
      2) 父系线: 父 → 祖父 → 曾祖父 (各自自身 culture);
      3) 同胞 (各自自身 culture — 同父系, 不经子树);
      4) 宗族成员 (同 dynasty_house, 父系血亲最可靠兜底 — 先于母系);
      5) 母 (自身 culture);
      6) 语言反查。
    chars: 预构建的全角色索引 (Facts 已持有), memo: 本次推断的缓存 dict。"""
    if melt is None or cid is None:
        return ""
    memo = memo if memo is not None else {}
    if cid in memo:
        return memo[cid]
    if chars is None:
        chars = all_characters(melt)
    tpl = _culture_template_impl(cache, cid, melt, chars, memo)
    memo[cid] = tpl
    return tpl


def _culture_template_impl(cache, cid, melt, chars, memo):
    def self_tpl(x):
        """自身 culture (缓存 → 熔件) 的文化模板。"""
        k = str(x)
        r = (cache.get("characters") or {}).get(k) or {}
        t = _template_of_culture(melt, r.get("culture"))
        if t:
            return t
        return _template_of_culture(melt, (chars.get(k) or {}).get("culture"))

    # 1) 自身
    t = self_tpl(cid)
    if t:
        return t
    key = str(cid)
    rec = (cache.get("characters") or {}).get(key) or {}

    def fathers_of(x):
        k = str(x)
        r = (cache.get("characters") or {}).get(k) or {}
        f = (r.get("family") or {}).get("father") or []
        if not f:
            c = chars.get(k) or {}
            v = (c.get("family_data") or {}).get("father")
            if v is not None:
                f = v if isinstance(v, list) else [v]
        return [int(y) for y in f]

    def fam_of(x, keys):
        k = str(x)
        r = (cache.get("characters") or {}).get(k) or {}
        out = []
        for kk in keys:
            for y in (r.get("family") or {}).get(kk) or []:
                if isinstance(y, int):
                    out.append(y)
        return out

    # 2) 父系线 (父 → 祖父 → 曾祖父, 各自自身 culture)
    cur = cid
    for _ in range(3):
        fs = fathers_of(cur)
        if not fs:
            break
        cur = fs[0]
        t = self_tpl(cur)
        if t:
            return t
    # 3) 同胞 (各自自身 culture, 不经子树 — 防姻亲/继亲文化泄漏)
    for sib in fam_of(cid, ("siblings",)):
        t = self_tpl(sib)
        if t:
            return t
    # 4) 宗族成员 (同 dynasty_house, 父系血亲最可靠兜底 — 先于母系)
    dh = rec.get("dynasty_house")
    if dh is not None:
        hkey = f"__house_{dh}__"
        if hkey in memo:
            return memo[hkey] or ""
        found = ""
        for _cid2, r2 in (cache.get("characters") or {}).items():
            if r2.get("dynasty_house") == dh:
                t = _template_of_culture(melt, r2.get("culture"))
                if t:
                    found = t
                    break
        if not found and chars is not None:
            # v19: 缓存扫不到时扩展到全量熔件同宗族成员 (惰性建 house→成员索引,
            # 索引放共享 memo 内, 一次 build_facts 只建一遍; 田村子这类
            # 「有宗族、自身/亲属文化全被游戏清空」的角色因此可推回名序)。
            idx_key = "__house_idx__"
            hindex = memo.get(idx_key)
            if hindex is None:
                hindex = {}
                for _cid2, r2 in chars.items():
                    if not isinstance(r2, dict):
                        continue
                    h = r2.get("dynasty_house")
                    if h is not None:
                        hindex.setdefault(h, []).append(_cid2)
                memo[idx_key] = hindex
            for _cid2 in hindex.get(dh, ()):
                t = _template_of_culture(melt, (chars.get(_cid2) or {}).get("culture"))
                if t:
                    found = t
                    break
        memo[hkey] = found
        return found
    # 5) 母 (自身 culture)
    for m in fam_of(cid, ("mother",)):
        t = self_tpl(m)
        if t:
            return t
    # 6) 语言反查 (亲属链全空时的最后一步)
    c = chars.get(str(cid)) or {}
    langs = rec.get("languages") or (c.get("alive_data") or {}).get("languages") or []
    cultures = (melt.get("culture_manager") or {}).get("cultures") or {}
    rules = _patronym_rules_table()
    for lg in langs:
        fallback = ""
        for _e in cultures.values():
            if not isinstance(_e, dict) or _e.get("language") != lg:
                continue
            tpl = _e.get("culture_template")
            if not tpl:
                continue
            # v28: 多文化共享同一语言时优先有父名规则的模板 (language_norse → norse
            # 而非 norman), 与 facts.culture_template 同口径。
            if tpl in rules:
                return tpl
            fallback = fallback or tpl
        if fallback:
            return fallback
    return ""


def _father_name_of(cache, cid, melt, names_path, chars=None):
    """角色父的给定名 (父名拼接用): 缓存 → 熔件 → names.json (v28 顺序)。"""
    if melt is None:
        return ""
    key = str(cid)
    rec = (cache.get("characters") or {}).get(key) or {}
    fathers = (rec.get("family") or {}).get("father") or []
    if not fathers:
        c = (chars if chars is not None else all_characters(melt)).get(key) or {}
        v = (c.get("family_data") or {}).get("father")
        if v is not None:
            fathers = v if isinstance(v, list) else [v]
    if not fathers:
        return ""
    fid = int(fathers[0])
    fr = (cache.get("characters") or {}).get(str(fid)) or {}
    fn = fr.get("name_zh") or ""
    if not fn:
        # v28: 熔件角色优先于跨战役的 names.json
        fc = (chars if chars is not None else all_characters(melt)).get(str(fid)) or {}
        fn = name_zh(fc) if fc else ""
    if not fn and names_path:
        fn = (_load_names(names_path, melt).get(str(fid)) or {}).get("name_zh") or ""
    return fn


def _patronym_of(cache, cid, melt, names_path, chars=None, memo=None):
    """父名 (中间名): 父名制文化且父名已知 → 前缀+父名+后缀 (崔佛松/崔佛斯多蒂尔)。
    文化模板经亲属链推断 (玩家/死者 culture 缺失时经子女等反推)。"""
    if melt is None:
        return ""
    key = str(cid)
    rec = (cache.get("characters") or {}).get(key) or {}
    fathers = (rec.get("family") or {}).get("father") or []
    if not fathers:
        c = (chars if chars is not None else all_characters(melt)).get(key) or {}
        v = (c.get("family_data") or {}).get("father")
        if v is not None:
            fathers = v if isinstance(v, list) else [v]
    if not fathers:
        return ""
    fid = int(fathers[0])
    memo = memo if memo is not None else {}
    tpl = _culture_template_of(cache, cid, melt, chars=chars, memo=memo)
    if not tpl:
        tpl = _culture_template_of(cache, fid, melt, chars=chars, memo=memo)
    rules = _patronym_rules_table().get(tpl or "")
    if not rules:
        return ""
    fname = _father_name_of(cache, cid, melt, names_path, chars=chars)
    if not fname:
        return ""
    c = (chars if chars is not None else all_characters(melt)).get(key) or {}
    female = bool(c.get("female"))
    if female:
        return f"{rules.get('pf_zh') or ''}{fname}{rules.get('sf_zh') or ''}"
    return f"{rules.get('pm_zh') or ''}{fname}{rules.get('sm_zh') or ''}"


def _house_names_at(rec, melt, date, h, dn, memo=None):
    """(家族名, 宗族名) —— 按 date 取家族沿革 (v44 问题1)。

    私生女另立家族 (阿德尔海德 1118.4.2 别立冯·亚琛氏) 与家族改名
    (冯·亚琛 → 冯) 只记在 `rec["house_history"]`; 无沿革 (旧缓存) 或未指定
    日期时取**熔件现值** —— 缓存里的 house_name/dynasty_name 是首见冻结值,
    家族改名后即过期, 只作最后兜底。"""
    hid = rec.get("dynasty_house")
    hist = [e for e in (rec.get("house_history") or []) if e.get("from")]
    pick = None
    if date and hist:
        dk = date_key(date)
        pick = hist[0]
        for e in hist:
            try:
                if date_key(e["from"]) <= dk:
                    pick = e
                else:
                    break
            except Exception:
                break
    if pick is not None:
        return (pick.get("house_name") or h), (pick.get("dynasty_name") or dn)
    if melt is not None and isinstance(hid, int):
        memo = memo if memo is not None else {}
        mk = f"__house_nm_{hid}__"
        if mk not in memo:
            memo[mk] = house_name_zh(melt, hid) or ""
        if memo[mk]:
            h = memo[mk]
        dk2 = f"__dyn_nm_{hid}__"
        if dk2 not in memo:
            did = dynasty_id_of(melt, hid)
            memo[dk2] = (dynasty_name_zh(melt, did) or "") if did is not None else ""
        if memo[dk2]:
            dn = memo[dk2]
    return h, dn


def _culture_id_at_rec(rec, date):
    """角色记录在 date 的文化 id (族属沿革点优先); 无沿革/无日期返回 None。

    v44 (问题4): 名序随文化翻档 —— 阿德尔海德 1132 年由法兰克尼亚人转汉人,
    此前是「名·姓」(阿德尔海德·冯·亚琛), 此后才是「姓+名」(冯阿德尔海德)。
    只按末档文化取名序, 早年事件会一律按东方名序排。"""
    hist = [h for h in (rec.get("culture_history") or []) if h.get("from")]
    if date and hist:
        dk = date_key(date)
        pick = hist[0]
        for h in hist:
            try:
                if date_key(h["from"]) <= dk:
                    pick = h
                else:
                    break
            except Exception:
                break
        if pick.get("culture") is not None:
            return pick["culture"]
    return None


def display_name(cache, cid, melt=None, names_path=None, chars=None, memo=None,
                 date=None):
    """(v13 唯一出口) 按游戏规则的显示名, 全项目统一调用:
    - 父名制文化 (patronym_rules 有模板) → 「名·父名」(富兰克林·崔佛松), 父名替代家族名;
    - 其它文化按名序: 东方姓在前 (藤原道真/边诚/赵阿足), 西方名·姓 (崔佛·菲利普/巴沙尔·冯·大马士革);
    - v14: 东方名序 (dynasty_always_first/japanese) 的姓取**宗族名** (游戏 $DYNASTY$ 模板:
      中国李金/日本藤原/韩国崔, 家族名如 北家/庆州崔/交州金 只作分家不显示);
      西方仍用**家族名** ($HOUSE$ 模板);
    - 文化缺失时沿 父系线→同胞→宗族→母→语言 推断 (玩家/死者均覆盖);
    - 推断失败: 只返回给定名, 绝不输出错序的「姓+名」拼接。
    v28: 名字取值链 = 缓存 → **熔件角色** → names.json (跨战役兜底, 战役不符即弃用)。
    v44 (问题1): date 传本篇截止日 → 家族名按 `house_history` 取该日之值
    (阿德尔海德 1118-1132 作「阿德尔海德·冯·亚琛」, 1133 起「冯阿德尔海德」);
    date 缺省取熔件现值。文化变更 (法兰克尼亚人→汉人) 决定名序取家族名还是宗族名,
    故同一人在东西名序下会换形 (与游戏一致)。
    chars: 预构建的全角色索引 (Facts 已持有), memo: 跨调用共享推断缓存
    (同一次 build_facts 内复用, 避免重复全量宗族扫描)。"""
    if cid is None:
        return ""
    key = str(cid)
    rec = (cache.get("characters") or {}).get(key) or {}
    nm = rec.get("name_zh") or ""
    h = rec.get("house_name") or ""
    dn = rec.get("dynasty_name") or ""
    h, dn = _house_names_at(rec, melt, date, h, dn, memo=memo)
    # v28: **熔件角色优先于 names.json** —— 该表按角色 id 索引且可能来自另一场
    # 战役 (角色 id 只在同一存档内有意义), 熔件里明明有这个人时以本人为准
    # (实测: 陆氏档 16293 本人是汉人「郑良士」, names.json 里同名 id 是
    # 另一战役的「藤原利仁」, 旧顺序会把他写成日本关内路领主)。
    if not nm:
        c = (chars or {}).get(key) or {}
        if c:
            nm = name_zh(c)
            hid = c.get("dynasty_house")
            if hid is not None:
                # v28: 熔件同源补齐家族/宗族名 (旧代码只补家族名且不补宗族名)
                h = h or (house_name_zh(melt, hid) or "")
                if not dn:
                    did = dynasty_id_of(melt, hid)
                    dn = (dynasty_name_zh(melt, did) or "") if did is not None else ""
    if not nm and names_path:
        n = _load_names(names_path, melt).get(key)
        if n:
            nm = n.get("name_zh") or ""
            h = h or n.get("house_name") or ""
            dn = dn or n.get("dynasty_name") or ""
    if not nm:
        return rec.get("name_full") or ""
    memo = memo if memo is not None else {}
    # 1) 父名制文化 → 名·父名 (v70: 与本名同词时只写一次, 同东方/西方姓两条路径)
    ptn = _patronym_of(cache, cid, melt, names_path, chars=chars, memo=memo)
    if ptn:
        return nm if ptn == nm else f"{nm}·{ptn}"
    # 2) 名序: 自身文化 → 亲属推断 → 文化模板反查 (v13)
    # v44 (问题4): date 传本篇截止日时按**族属沿革**取该日文化 —— 名序随文化翻档
    cul = _culture_id_at_rec(rec, date)
    if cul is None:
        cul = rec.get("culture")
    order = name_order_of(melt, cul) if cul is not None else None
    if order is None:
        order = _family_name_order(cache, rec, melt, chars=chars)
    if order is None:
        tpl = _culture_template_of(cache, cid, melt, chars=chars, memo=memo)
        if tpl:
            for _cid2, _e in ((melt.get("culture_manager") or {})
                              .get("cultures") or {}).items():
                if isinstance(_e, dict) and _e.get("culture_template") == tpl:
                    order = _e.get("name_order_convention") or ""
                    break
    if order in EASTERN_NAME_ORDERS:
        # v14: 东方名序姓 = 宗族名 (游戏 $DYNASTY$ 模板: 藤原/崔/金);
        # 缓存/names 缺失时 (旧缓存) 按家族 id 惰性从熔件解析, 同 house 记忆化。
        if not dn and melt is not None:
            hid = rec.get("dynasty_house")
            if hid is not None:
                mkey = f"__dyn_name_{hid}__"
                dn = memo.get(mkey) if memo else ""
                if not dn:
                    did = dynasty_id_of(melt, hid)
                    dn = dynasty_name_zh(melt, did) if did is not None else ""
                    if memo is not None:
                        memo[mkey] = dn
        # 宗族名缺失 (解析失败/无宗族) 回退家族名 (旧行为)
        # v70 (用户 2026-09-27 拍板「姐姐姐姐一类的重复一起改掉」): 姓与名同为
        # 一个词时只写一次 —— 游戏生成的家族名偶尔与该人本名同源 (存美 存美 /
        # 朮里者 朮里者), 旧稿拼成「存美存美」, 模型照抄进正文。
        surname = dn or h
        if surname == nm:
            return nm
        return surname + nm if surname else nm
    # v58 (问题4): 西方名序拼上前缀 (迪·/德·/冯·) —— 游戏显示「罗伯托·迪·卡诺萨」。
    # 家族名若已自带前缀 (存档 localized_name 如「冯·大马士革」) 则不重复加。
    pfx = house_prefix_zh(melt, rec.get("dynasty_house")) if melt is not None else ""
    if pfx and h and (h.startswith(pfx) or h.startswith(pfx.rstrip("·"))):
        pfx = ""

    def _west_surname(surname):
        # v70: 姓与该人本名同词时只写一次 (「朮里者·朮里者」→「朮里者」;
        # 见上 `EASTERN_NAME_ORDERS` 分支同源注释)
        if surname and surname.strip("·") == nm:
            return nm
        return f"{nm}·{pfx}{surname}" if (surname and pfx) else \
            (f"{nm}·{surname}" if surname else nm)

    cultures = (melt or {}).get("culture_manager") or {}
    if cul is not None and str(cul) in (cultures.get("cultures") or {}):
        # 文化已知且西方默认: 名·姓
        return _west_surname(h)
    if order is not None and order == "":
        # 亲属/模板推断为西方默认: 名·姓
        return _west_surname(h)
    # 3) 无从推断: 只给给定名 (宁缺勿错序)
    return nm


# ---------------------------------------------------------------------------
# 亲属图 (v4: 反向亲属索引)
# ---------------------------------------------------------------------------

def _family_graph(chars):
    """全档角色 → (parent_map, child_map, sibling_map)。
    - parent_map: {角色: [父/母 id...]}  由 family_data.child 反查 + 直接 father/mother 字段
    - child_map:  {角色: [子女 id...]}   直接 child 字段 + father/mother 字段反查
    - sibling_map:{角色: [兄弟姐妹 id...]} 直接 siblings 字段 (双向)
    实测: 子女 family_data 常为空, 父女关系只在父侧 child 列表 (33367.child 含妻 37898)。"""
    parent_map = {}
    child_map = {}
    sibling_map = {}

    def link(owner, key, val):
        if val is None:
            return
        ids = [int(x) for x in (val if isinstance(val, list) else [val])]
        for x in ids:
            if key == "child":
                parent_map.setdefault(x, []).append(owner)
                child_map.setdefault(owner, []).append(x)
            elif key in ("father", "mother"):
                parent_map.setdefault(x, []).append(owner)
                child_map.setdefault(owner, []).append(x)
            elif key == "siblings":
                sibling_map.setdefault(owner, []).append(x)
                sibling_map.setdefault(x, []).append(owner)

    for cid, c in chars.items():
        if not isinstance(c, dict):  # v7: none 条目防护
            continue
        fd = c.get("family_data") or {}
        for key in ("child", "father", "mother", "siblings"):
            link(int(cid), key, fd.get(key))
    return parent_map, child_map, sibling_map


def _parents_of(chars, cid, parent_map, direct):
    """角色父母 (直接字段 + 反查合并, 按性别分 father/mother)。"""
    fathers = [int(x) for x in (direct.get("father") or [])]
    mothers = [int(x) for x in (direct.get("mother") or [])]
    for p in parent_map.get(cid, []):
        if p in fathers or p in mothers:
            continue
        c = chars.get(str(p)) or {}
        if c.get("female"):
            mothers.append(p)
        else:
            fathers.append(p)
    return fathers, mothers


def _siblings_of(cid, parent_map, child_map, sibling_map, direct):
    """角色兄弟姐妹: 直接字段 + 共享父母派生。"""
    out = set(int(x) for x in (direct.get("siblings") or []))
    out.update(sibling_map.get(cid, []))
    for p in parent_map.get(cid, []):
        for s in child_map.get(p, []):
            if s != cid:
                out.add(s)
    return sorted(out)


def _secret_father_candidates(melt):
    """预索引秘密生父: {target_id: [[候选父id...], ...]}。

    两类秘密 (secret_unmarried_illegitimate_child / secret_disputed_heritage) 按
    原对象顺序分组保存候选列表; 组内已排除 target 自身与 owner。保持与逐条扫描
    完全相同的返回语义: 首个含候选的秘密组优先, 组内先返回非女性候选人。
    v11: extract_snapshot 主循环对每个目标角色调 real_father_of, 旧实现每次
    全量遍历 secrets → O(目标×秘密), 预建后 O(1) 查询。"""
    out = {}
    sec = (melt.get("secrets") or {}).get("secrets") or {}
    for s in sec.values():
        if not isinstance(s, dict):
            continue
        if s.get("type") not in ("secret_unmarried_illegitimate_child",
                                 "secret_disputed_heritage"):
            continue
        tgt = (s.get("target") or {}).get("identity")
        if tgt is None:
            continue
        tgt = int(tgt)
        owner = s.get("owner")
        cands = [int(x) for x in (s.get("participants") or []) if isinstance(x, int)]
        cands = [x for x in cands if x != tgt]
        if owner is not None and isinstance(owner, int):
            cands = [x for x in cands if x != owner]
        if cands:  # 空候选组在原逻辑中会被跳过, 不建索引
            out.setdefault(tgt, []).append(cands)
    return out


def real_father_of(melt, cid, chars=None, sec_candidates=None):
    """角色真正父亲 (v5): family_data.real_father 直接字段;
    缺失时查秘密 (secret_unmarried_illegitimate_child / secret_disputed_heritage:
    target=子女, participants 中非 owner 的男性候选人)。

    v11: chars / sec_candidates 由调用方预建一次传入 (extract_snapshot 主循环每个
    目标角色调用一次, 旧实现每次重建全角色字典 → O(目标×世界) 二次方,
    实测 913.1.1 并入 129s; 预建后 O(1) 查询)。"""
    cid = int(cid)
    if chars is None:
        chars = all_characters(melt)
    c = chars.get(str(cid)) or {}
    fd = c.get("family_data") or {}
    rf = fd.get("real_father")
    if rf is not None:
        return int(rf)
    # 秘密推导: participants 中非 owner 的男性候选人 (女眷=owner 时第二人为父)
    if sec_candidates is None:
        sec_candidates = _secret_father_candidates(melt)
    for cands in sec_candidates.get(cid, []):
        for cand in cands:
            cc = chars.get(str(cand)) or {}
            if not cc.get("female"):
                return cand
        if cands:
            return cands[0]
    return None


# ---------------------------------------------------------------------------
# 单档提取 (v4: 每玩家缓存 + 姓名合并 + 亲属/特质/朝局)
# ---------------------------------------------------------------------------

# v53 (问题1): 天朝封臣合同组 `celestial_vassal` 的 contracts 顺序
# (subject_contract_groups.txt) — 索引 2 = celestial_provinces。
_CELESTIAL_PROVINCE_INDEX = 2
_CELESTIAL_PROVINCE_FLAGS = (
    "celestial_province_standard",       # 0 观察使
    "celestial_province_industrial",     # 1 观察使
    "celestial_province_metropolitan",   # 2 观察使
    "celestial_province_military",       # 3 经略使
    "celestial_province_protectorate",   # 4 都护
)


def _contract_levels_map(levels):
    """熔件 `levels: [N, {"3": 2}, …]` → {int index: int value}。"""
    out = {}
    if not isinstance(levels, list):
        return out
    for item in levels:
        if not isinstance(item, dict):
            continue
        for k, v in item.items():
            try:
                out[int(k)] = int(v)
            except (TypeError, ValueError):
                continue
    return out


def vassal_obligation_flags(contract):
    """一份封臣合同 → 义务旗标列表 (目前只解码 celestial_provinces)。

    熔件常省略默认档 (index 2 缺失 = 0 = celestial_province_standard)。
    非天朝合同组返回 []。"""
    if not isinstance(contract, dict):
        return []
    group = str(contract.get("contract_group") or "")
    if group != "celestial_vassal":
        return []
    lv = _contract_levels_map(contract.get("levels"))
    idx = lv.get(_CELESTIAL_PROVINCE_INDEX, 0)
    if 0 <= idx < len(_CELESTIAL_PROVINCE_FLAGS):
        return [_CELESTIAL_PROVINCE_FLAGS[idx]]
    return []


def _vassal_snapshot(melt):
    """本档封臣合同 → {vassal_id: {liege, flags}}。"""
    out = {}
    db = (melt.get("vassal_contracts") or {}).get("database") or {}
    for rec in db.values():
        if not isinstance(rec, dict):
            continue
        v = rec.get("vassal")
        if v is None:
            continue
        try:
            vid = int(v)
        except (TypeError, ValueError):
            continue
        liege = rec.get("liege")
        try:
            liege = int(liege) if liege is not None else None
        except (TypeError, ValueError):
            liege = None
        out[vid] = {"liege": liege, "flags": vassal_obligation_flags(rec)}
    return out


def dynastic_cycle_phase(melt):
    """当前天命循环阶段 {phase, start}；无局势返回 None。

    路径: situation_manager.database 里 type=dynastic_cycle 的条目,
    再经 sub_region_refs 落到 situation_sub_region_manager.database.<id>.phase。"""
    sm = (melt.get("situation_manager") or {}).get("database") or {}
    sit_id = None
    for k, v in sm.items():
        if isinstance(v, dict) and v.get("type") == "dynastic_cycle":
            sit_id = k
            refs = v.get("sub_region_refs") or []
            break
    else:
        return None
    srm = (melt.get("situation_sub_region_manager") or {}).get("database") or {}
    rec = None
    if refs:
        rec = srm.get(str(refs[0]))
    if rec is None:
        rec = srm.get(str(sit_id)) if sit_id is not None else None
    if rec is None:
        for v in srm.values():
            if isinstance(v, dict) and v.get("situation") is not None:
                rec = v
                break
    if not isinstance(rec, dict):
        return None
    phase = rec.get("phase") or {}
    if not isinstance(phase, dict):
        return None
    ptype = phase.get("type") or ""
    if not ptype:
        return None
    return {"phase": str(ptype), "start": str(phase.get("start_date") or "")}


def player_domicile(melt, domain, cid):
    """玩家毡帐/庄园条目 (v26): 牧群(herd)/口粮(provisions) 只存于
    domiciles.database, landed_data 里没有 — 按 owner_title 命中玩家领地
    (或该头衔持有人即玩家) 取条目。返回 dict 或 None。"""
    db = (melt.get("domiciles") or {}).get("database") or {}
    domset = {x for x in (domain or []) if isinstance(x, int)}
    lt = (melt.get("landed_titles") or {}).get("landed_titles") or {}
    for v in db.values():
        if not isinstance(v, dict):
            continue
        ot = v.get("owner_title")
        if not isinstance(ot, int):
            continue
        if ot in domset or (lt.get(str(ot)) or {}).get("holder") == cid:
            return v
    return None


def _latch_title_dyn_names(cache, lt, date_label):
    """v66: 头衔**动态名**逐档闩存 (只记变化点) —— `cache["title_dyn_names"]`。

    `title_name_data.specific_title_name` 是**该日期那一档才有的现值** (属《方案 v48》
    §4 B 那一类; 同类的家族/政体/朝职/领地早已闩存)。它是游牧/宗族命名领域的游戏
    显示名「文化集合词+宗族名+部」(如「库曼顿巴斯部」「可萨希西家部」), 随持有者
    逐档变; 而末档熔件只留最后一版 —— 于是同一块地被后来的持有者改名后, 历任/年表/
    驻地会把**后来的名字**用在早年事件上。实测 (卡尔 60836, 84 档): 936 年的
    `c_kherson` 被读成 954 年才有的「马扎尔迈杰希部」; `c_uman` / `d_barsuki` /
    `d_chah` / `k_dzungaria` 四块**不同**头衔全被读成「库曼顿巴斯部」, 模型据此写出
    「四度得库曼顿巴斯部而四度迁离」这类伪史。详见 docs/方案_v66_游牧迁移用地名.md。

    形状随项目既有沿革 (`[{from, name}]`, 同 `culture_history`): 只在**值变化**时
    追加一点, 故体量极小 (实测 84 档 ≈ 215 KB / 6158 点)。名字**消失**也记一次空值,
    否则旧名会一直生效 (取值口要区分「当时无名」与「本档未收」)。

    只记非空动态名 —— 静态地名 (`title_name_data.name`) 不逐档变, 由熔件末档免费提供。"""
    dn = cache.setdefault("title_dyn_names", {})
    dk = date_key(date_label)

    def _push(key, name):
        h = dn.setdefault(key, [])
        if h:
            if date_key(h[-1]["from"]) > dk:
                return          # 乱序并档 (他传主熔件回并): 保沿革表单调
            if h[-1].get("name") == name:
                return
        h.append({"from": date_label, "name": name})

    named = set()
    for tid, t in lt.items():
        if not isinstance(t, dict):
            continue
        sp = (((t.get("title_name_data") or {}).get("specific_title_name"))
              or "").strip()
        if not sp:
            continue
        key = str(tid)
        named.add(key)
        _push(key, sp)
    for key in list(dn):
        if key not in named:
            _push(key, "")


def _record_vassal_and_cycle(cache, melt, date_label):
    """记下本档封臣合同变化点与天命阶段 (v53)。

    同战役他传主熔件也要走这条路: 马丁早年节度使合同只存在于亨利档,
    重建马丁缓存时那些熔件因 player_id 不一致被整档跳过, 不在这里落盘
    终传就拼不出 910 的封臣史。"""
    _vassal_now = _vassal_snapshot(melt)
    _phase = dynastic_cycle_phase(melt)
    if _phase:
        _ph = cache.setdefault("dynastic_cycle_history", [])
        if not _ph or _ph[-1].get("phase") != _phase.get("phase"):
            _ph.append({"date": date_label, "phase": _phase.get("phase") or "",
                        "start": _phase.get("start") or date_label})
    _vh_all = cache.setdefault("char_vassal_history", {})
    # 只记本传主 + 已入库角色 + 已有封臣史的人, 不把全天朝封臣写进缓存。
    want = {int(k) for k in _vh_all if str(k).isdigit()}
    pid = cache.get("player_id")
    if pid is not None:
        try:
            want.add(int(pid))
        except (TypeError, ValueError):
            pass
    for k in (cache.get("characters") or {}):
        try:
            want.add(int(k))
        except (TypeError, ValueError):
            continue
    _vh_ids = want or set(_vassal_now)
    for vid in _vh_ids:
        _vc = _vassal_now.get(vid)
        _v_liege = (_vc or {}).get("liege") if _vc else None
        _v_flags = (_vc or {}).get("flags") or []
        _vh = _vh_all.setdefault(str(vid), [])
        if _vc is not None:
            if (not _vh or _vh[-1].get("liege") != _v_liege
                    or (_vh[-1].get("flags") or []) != _v_flags):
                _vh.append({"date": date_label, "liege": _v_liege,
                            "flags": list(_v_flags)})
        elif _vh and _vh[-1].get("liege") is not None:
            _vh.append({"date": date_label, "liege": None, "flags": []})
    return _vassal_now


def extract_snapshot(cache, melt, date_label, _new_deaths=None):
    """把一个存档快照并入缓存。返回 False 表示玩家不一致被拒绝。
    _new_deaths: 可选列表, 本次并入「首次记录死亡」的角色 id (int) 会追加进来,
    供调用方只对「新死亡」角色做死档记忆回溯, 避免每轮全量扫描 (v9)。

    v56 (性能): 本函数在**关掉自动 GC** 的窗口里跑 (出栈恢复原状态) ——
    缓存对象图到后期上千万节点, 本函数每档新建/改写数十万对象, 途中反复触发
    gen0/1/2, 每次 gen2 都要遍历全图。实测单档 `extract_snapshot`
    7.75 s → 3.22 s (**-58%**, 斯卡利茨 melt_940)。数据全是 dict/list,
    引用计数即可释放, 无环; 与 `load_melt` 的同类处理同源 (v49 O2)。"""
    _gc_was_on = gc.isenabled()
    if _gc_was_on:
        gc.disable()
    try:
        return _extract_snapshot(cache, melt, date_label, _new_deaths)
    finally:
        if _gc_was_on:
            gc.enable()


def _extract_snapshot(cache, melt, date_label, _new_deaths=None):
    """`extract_snapshot` 的实现体 (GC 窗口由外层负责)。"""
    player_id = find_player(melt)
    # v28: 战役校验 — 角色 id 跨战役复用 (867 自定义角色恒为 38701/38682),
    # 仅凭玩家 id 无法拦住「另一场战役的熔件并进本缓存」。两边都有战役号
    # 且不同即拒收 (调用方一律按 playthrough_id 选缓存, 这里是最后一道防线)。
    _cpt = cache.get("playthrough_id")
    _mpt = melt.get("playthrough_id")
    if _cpt and _mpt and str(_cpt) != str(_mpt):
        print(f"  [跳过] 档期 {date_label} 战役 {_mpt} 与缓存战役 {_cpt} 不一致")
        return False
    if cache["player_id"] is not None and player_id is not None \
            and cache["player_id"] != player_id:
        # v53: 同战役他传主熔件仍记封臣史/天命 (马丁终传要用亨利档的早年合同)
        _record_vassal_and_cycle(cache, melt, date_label)
        # v60 (问题4): 同战役**后继玩家**的档也要用来记囚禁交接 ——
        # 传主死后其在押囚犯的监禁者转归继位者, 而那之后的档
        # `find_player` 已换成继位者, 本传主这一侧永远看不到 (崔佛 881/882 档
        # 的 find_player 是 15179, 他的缓存只到 880 档)。
        _latch_prison_succession(cache, melt, date_label)
        return False
    if cache["player_id"] is None:
        cache["player_id"] = player_id
    cache["player_id"] = player_id or cache["player_id"]
    meta = melt.get("meta_data") or {}
    if meta.get("meta_player_name") and not cache.get("player_name"):
        cache["player_name"] = meta["meta_player_name"]
    cache["game_version"] = meta.get("version") or cache["game_version"]
    # 战役标识: 同一战役(含继承人继位)的存档共享 playthrough_id
    if cache.get("playthrough_id") is None and melt.get("playthrough_id"):
        cache["playthrough_id"] = melt.get("playthrough_id")
    if date_label not in cache["sources"]:
        cache["sources"].append(date_label)
    # last_date 单调更新: 防旧档/跨战役误并把日期回拨
    if date_key(date_label) > date_key(cache.get("last_date") or "0.0.0"):
        cache["last_date"] = date_label

    chars = all_characters(melt)
    db = _db(melt)
    lt = (melt.get("landed_titles") or {}).get("landed_titles") or {}
    tl = melt.get("traits_lookup") or []
    # v56 (性能): 换档即释放上一档在 `_TL` 里留下的引用 (宗族名索引/结果 memo)
    clear_dyn_caches()
    # v13: 本快照内共享的姓名推断缓存 (一次 rebuild 数万角色只算一遍)
    _name_memo = {}
    # v14: 宗族名解析记忆化 (旧缓存自愈用)
    # v44: 家族名与宗族名分表记忆化 (house id 与 dynasty id 各自成池, 同表会互撞)
    _hname_memo = {}
    _dname_memo = {}

    def _house_now(hid):
        if hid not in _hname_memo:
            _hname_memo[hid] = house_name_zh(melt, hid) or ""
        return _hname_memo[hid]

    def _dyn_now(did):
        if did is None:
            return ""
        if did not in _dname_memo:
            _dname_memo[did] = dynasty_name_zh(melt, did) or ""
        return _dname_memo[did]

    def trait_key(t):
        if isinstance(t, int) and 0 <= t < len(tl):
            return tl[t]
        return str(t)

    # 玩家死亡检测 (首次写入后不再覆盖; v8: 同时记录 dead_data.kills)
    if player_id is not None:
        pdead = (chars.get(str(player_id)) or {}).get("dead_data")
        if pdead and cache.get("player_death") is None:
            cache["player_death"] = {
                "date": pdead.get("date"),
                "reason": pdead.get("reason"),
                "killer": pdead.get("killer"),
                "kills": pdead.get("kills") or [],
            }
        # v44 (问题2): 玩家角色接替链 (存档 played_character.legacy)。
        # 每档一存 (后档含前档), 条目 = {cid, date}; 末条即当前传主, 其 date =
        # 继位日 = 前任死亡当日。新版本玩家可从宗族里挑人继位, 故此链是
        # 「传主之间怎么连起来的」的唯一权威来源。
        _lg = (melt.get("played_character") or {}).get("legacy") or []
        _chain = []
        for _e in _lg:
            if not isinstance(_e, dict):
                continue
            _cid = _e.get("character")
            if not isinstance(_cid, int):
                continue
            _chain.append({"cid": _cid, "date": _e.get("date")})
        if _chain:
            cache["played_legacy"] = _chain

    # 目标角色集: 玩家 + 家族/家庭 + 记忆参与者 (两轮)
    targets = set()
    if player_id is not None:
        targets.add(player_id)
        p = chars.get(str(player_id))
        if p:
            for ids in family_of(p).values():
                targets.update(ids)
            house = p.get("dynasty_house")
            if house is not None:
                for cid, c in chars.items():
                    if not isinstance(c, dict):  # v7: none 条目防护
                        continue
                    if c.get("dynasty_house") == house:
                        targets.add(int(cid))

    def add_participants(owner_id):
        c = chars.get(str(owner_id))
        if not c:
            return
        for mid in mem_ids_of(c):
            e = db.get(str(mid))
            if not e:
                continue
            for v in (e.get("participants") or {}).values():
                if isinstance(v, int):
                    targets.add(v)

    if player_id is not None:
        add_participants(player_id)
    # 后续轮: 目标集角色的记忆参与者 (三轮扩展, 覆盖同僚圈: 铎妻/狱卒/好友等)
    for _round in range(3):
        snapshot = list(targets)
        for cid in snapshot:
            add_participants(cid)
    # 全库: 记忆参与者含玩家的记忆拥有者 (交叉读取)
    if player_id is not None:
        for cid, c in chars.items():
            for mid in mem_ids_of(c):
                e = db.get(str(mid))
                if not e:
                    continue
                if player_id in (e.get("participants") or {}).values():
                    targets.add(int(cid))
                    for v in (e.get("participants") or {}).values():
                        if isinstance(v, int):
                            targets.add(v)

    # 亲属闭包 (v4): 两轮, 把已收角色的一级亲属 (父母/子女/兄弟姐妹/配偶) 纳入目标,
    # 保证妻父 (宋帝赵曙)/妻兄 (今上赵煦) 等入缓存, 名字可解析。
    parent_map, child_map, sibling_map = _family_graph(chars)
    for _round in range(2):
        snapshot = list(targets)
        for cid in snapshot:
            c = chars.get(str(cid))
            if not c:
                continue
            fam = family_of(c)
            for ids in fam.values():
                targets.update(int(x) for x in ids)
            for p in parent_map.get(cid, []):
                targets.add(p)
                targets.update(child_map.get(p, []))
            targets.update(sibling_map.get(cid, []))

    # 朝局持有者 (v4): 帝国(h_/e_)级头衔 + 相关角色持有的头衔, 逐年记录
    realm_holders = {}
    for tid, t in lt.items():
        if not isinstance(t, dict):  # v7: 空值条目 (none) 防护
            continue
        holder = t.get("holder")
        key = t.get("key") or ""
        if holder is None:
            continue
        hid = int(holder) if not isinstance(holder, list) else None
        if key.startswith(("e_", "h_")):
            realm_holders[tid] = hid
        elif hid is not None and hid in targets:
            realm_holders[tid] = hid
    if realm_holders:
        cache.setdefault("realm_history", []).append(
            {"date": date_label, "holders": realm_holders})

    # v66: 头衔动态名逐档闩存 (与 realm_history 同位 —— 同属"只有该日期那一档才有
    # 的现值"; 见 _latch_title_dyn_names docstring)
    _latch_title_dyn_names(cache, lt, date_label)

    # 玩家营/廷内僚属任职 (v7): court_positions.database 中 employer == 玩家,
    # 逐年记录 (含营地军官与宫廷职位 — 这些岗位由玩家麾下僚属担任, **不是玩家
    # 自身的官职**; 玩家自身官职走 player_title_history/历任头衔, v23 语义重申)。
    if player_id is not None:
        cpd = (melt.get("court_positions") or {}).get("database") or {}
        mine = []
        for _pos_id, e in cpd.items():
            if not isinstance(e, dict):  # v7: none 条目防护
                continue
            try:
                if e.get("employer") is None or int(e.get("employer")) != player_id:
                    continue
            except (TypeError, ValueError):
                continue
            ptype = e.get("court_position")
            if not ptype:
                continue
            emp_id = e.get("employee")
            if isinstance(emp_id, int):
                targets.add(emp_id)  # 官职任职者入目标集, 保证姓名可解析
            mine.append({
                "type": ptype,
                "employee": emp_id,
                "hire_date": e.get("hire_date"),
                "task": e.get("task_type"),
            })
        if mine:
            cache.setdefault("court_positions", []).append(
                {"date": date_label, "positions": mine})
        # v36 (问题2, 用户拍板3): 主角**获授**的朝廷职位 — court_positions.database 中
        # employee == 玩家、employer == 他人 (太师/某部尚书这类朝廷命官)。方向与上面的
        # 「僚属」相反, 故分列一键, 语义互不混: 上面是「谁在我廷中任职」, 这里是
        # 「我在谁的朝中任职」。失去时点在 facts 侧按快照差分推断
        # (太师 881 受任、884 档仍在、885 档已无 → 至晚自885年起已卸任)。
        own = []
        for _pos_id, e in cpd.items():
            if not isinstance(e, dict):
                continue
            try:
                if e.get("employee") is None or int(e.get("employee")) != player_id:
                    continue
                if e.get("employer") is None:
                    continue
                employer = int(e.get("employer"))
            except (TypeError, ValueError):
                continue
            ptype = e.get("court_position")
            if not ptype:
                continue
            targets.add(employer)   # 雇主入目标集, 保证「唐皇帝李漼」这类称谓可解析
            own.append({"type": ptype, "employer": employer,
                        "hire_date": e.get("hire_date")})
        # v36: 逐档都记一条 (空集也记) — 失去时点靠「后一档已无此职位」差分推断
        # (与 court_positions 只在非空时记录不同: 那里是花名册, 这里是任期)。
        cache.setdefault("court_office_history", []).append(
            {"date": date_label, "offices": own})
        # 玩家家族家训 (v7): dynasty_house[<id>].motto (字符串或模板 dict)
        pobj = chars.get(str(player_id))
        if isinstance(pobj, dict) and pobj.get("dynasty_house") is not None:
            dh_ = (melt.get("dynasties") or {}).get("dynasty_house") or {}
            he = dh_.get(str(pobj.get("dynasty_house"))) or {}
            if isinstance(he, dict) and he.get("motto"):
                cache["house_motto"] = he.get("motto")
        # v31: 牵制对手方 (holder/target) 入目标集, 保证姓名/档案可解析
        # (牵制把柄常指向宫廷外角色: 「安乔握有对主角的强牵制」)。
        for _e in (melt.get("relations") or {}).get("active_relations") or []:
            if not isinstance(_e, dict):
                continue
            _h, _t = _e.get("first"), _e.get("second")
            if not isinstance(_h, int) or not isinstance(_t, int):
                continue
            if player_id in (_h, _t):
                targets.add(_h)
                targets.add(_t)
        # v35: 主角的奴隶入目标集 — 否则姓名/宅第/生卒解析不出, 事实层只剩光名
        # (德圣塔档实测: 不进目标集时 9 名奴隶里数人退化成「哈迪雅」这样的单名)。
        targets.update(enslaved_ids(melt, player_id))
        # v35: 隐事的持有人与知情人也入目标集 —— 《阴私录》的「把柄」行要用他们的
        # 全称谓; 不进目标集时 `person_label` 落空, 事实层整行被丢
        # (德圣塔档实测: 贞子的把柄行时有时无)。
        for _sid, _rec in ((melt.get("secrets") or {}).get("secrets") or {}).items():
            if not isinstance(_rec, dict):
                continue
            for _k in (_rec.get("owner"), _rec.get("target")):
                if isinstance(_k, int):
                    targets.add(_k)
            for _p in (_rec.get("participants") or []):
                if isinstance(_p, int):
                    targets.add(_p)

    # 玩家主头衔名变化 (v4): 主头衔 title_name_data (custom → name) 或信封名
    if player_id is not None:
        tname = ""
        thn = []
        ld = (chars.get(str(player_id)) or {}).get("landed_data") or {}
        dom = ld.get("domain") or []
        if dom:
            t = lt.get(str(dom[0])) or {}
            tnd = t.get("title_name_data") or {}
            # v26: 游戏算好的动态头衔名 (游牧/宗族命名领域) 优先 —
            # 「可萨田所部」而不是静态地名「也勒克河」
            tname = (tnd.get("specific_title_name")
                     or tnd.get("custom") or tnd.get("name") or "")
            thn = tnd.get("title_history_names") or []
        if not tname:
            tname = meta.get("meta_title_name") or ""
        if tname:
            hist = cache.setdefault("player_title_history", [])
            if not hist or hist[-1].get("name") != tname:
                d = date_label
                for h in reversed(thn):
                    if h.get("name") == tname and h.get("date"):
                        d = h["date"]
                        break
                # v41 (问题1/2): 改名史与**夺位日**取真事件日 —— 主头衔在
                # title history 里由玩家取得的日期 (1086.1.1) 早于本档快照日
                # (1087.1.1); 旧稿写快照日, 十年传记里的登位年份因此晚一年。
                for _tid in dom:
                    _h = (lt.get(str(_tid)) or {}).get("history") or {}
                    if not isinstance(_h, dict):
                        continue
                    _ev_date = ""
                    for _hd in sorted(_h, key=date_key):
                        if date_key(_hd) > date_key(d):
                            break
                        _ev = _h[_hd]
                        for _e in (_ev if isinstance(_ev, list) else [_ev]):
                            _hh = _e.get("holder") if isinstance(_e, dict) else _e
                            try:
                                _hh = int(_hh) if _hh is not None else None
                            except (TypeError, ValueError):
                                _hh = None
                            if _hh == int(player_id):
                                _ev_date = _hd
                    if _ev_date:
                        d = _ev_date
                        break
                hist.append({"date": d, "name": tname})

    # v41 (问题1): 玩家政体变更史 (改行行政官制等) — 只记变化点 (与
    # player_locations / camp_purposes 同范式, 体量极小); facts 据此出
    # 「1095年，诺兰由封建采邑制改行行政官制」这句事实。
    # 日期取**本档快照日** —— 变更是逐档差分发现的 (实测主角 1087–1094 为
    # feudal_government, 1095.1.1 档起为 administrative_government);
    # 早年曾误取主头衔的夺位日 (1086.1.1), 把「夺得神罗」与「改行政制」混成一天。
    if player_id is not None:
        _ld = (chars.get(str(player_id)) or {}).get("landed_data") or {}
        _gov = _ld.get("government") or ""
        if _gov:
            _gh = cache.setdefault("government_history", [])
            if not _gh or _gh[-1].get("government") != _gov:
                _gh.append({"date": date_label, "government": _gov})

    # v8: 击杀受害者入目标集 (保证刺客列传能取到姓名/档案)
    for _cid in list(targets):
        _c = chars.get(str(_cid))
        for _v in kills_of(_c):
            targets.add(int(_v))

    # v8: 妾的反向索引 {男主id: [妾id...]} (family_data.concubinist);
    # 实测正向 family_data.concubine 只列 1 人, 反向才有 2 人 (崔佛: 艾丽丝+ED_la)。
    concubinist_map = {}
    for _cid, _c in chars.items():
        if not isinstance(_c, dict):
            continue
        _m = (_c.get("family_data") or {}).get("concubinist")
        if isinstance(_m, int):
            concubinist_map.setdefault(_m, []).append(int(_cid))
    # v11: 秘密生父索引预建一次 (real_father_of 对每个目标调用, 避免重复全量扫描)
    sec_candidates = _secret_father_candidates(melt)

    # v37 (问题8): 起义领袖预扫进目标集 —— 他们活着时的所在 (last_location) 必须落库。
    # 此前领袖只在循环**之后**的 _diff_factions 里登记、且不入 targets, 于是死后
    # 「死于X / 起于X」全无数据 (周氏2 实测 12 名死者 11 人无地点, 模型只能把他们
    # 就近安放到主角家业所在 —— 旧稿「居慈州境内」/新稿「宾州人」)。
    for _base in uprising_title_bases(melt).values():
        targets.add(int(_base["holder"]))

    # v53 (问题1/3): 封臣合同 + 天命阶段 (本传主熔件完整并入时也走同一入口)
    _record_vassal_and_cycle(cache, melt, date_label)

    for cid in sorted(targets):
        c = chars.get(str(cid))
        if c is None:
            continue
        rec = char_record(cache, cid)
        first_time = rec["first_name"] is None
        if first_time:
            rec["first_name"] = c.get("first_name")
            rec["name_zh"] = name_zh(c)
            rec["dynasty_house"] = c.get("dynasty_house")
            # 家族名 + 宗族名 (v3/v4; v14: 东方名序的姓取宗族名, 游戏 $DYNASTY$ 模板);
            # v13: name_full 按 display_name 正确名序生成
            if rec["dynasty_house"] is not None:
                h = house_name_zh(melt, rec["dynasty_house"])
                rec["house_name"] = h
                # v14: 宗族名: 家族 → 宗族 → 解析 (存档只存 key, 显示名查游戏定义表)
                _did = dynasty_id_of(melt, rec["dynasty_house"])
                if _did is not None:
                    rec["dynasty_name"] = dynasty_name_zh(melt, _did) or None
                # v44 (问题1): 首见即记家族沿革第一点
                rec["house_history"] = [{
                    "from": date_label,
                    "house_id": rec["dynasty_house"],
                    "house_name": rec.get("house_name") or "",
                    "dynasty_id": _did,
                    "dynasty_name": rec.get("dynasty_name") or "",
                }]
            if rec["name_zh"]:
                # v13: name_full 按 display_name 正确名序生成 (chars/memo 复用本快照索引)
                rec["name_full"] = display_name(cache, cid, melt=melt, chars=chars,
                                                memo=_name_memo) \
                    or (rec.get("house_name", "") + rec["name_zh"])
            rec["birth"] = c.get("birth")
            rec["female"] = bool(c.get("female"))
            rec["culture"] = c.get("culture")
            rec["faith"] = c.get("faith")
            if rec["culture"] is not None:
                rec["culture_history"] = [{"from": date_label,
                                           "culture": rec["culture"]}]
            if rec["faith"] is not None:
                rec["faith_history"] = [{"from": date_label,
                                         "faith": rec["faith"]}]
        # v26: 性别自愈 — 旧缓存无该字段时按熔件补 (女性才有 female 键, 男性补 False)
        if rec.get("female") is None:
            rec["female"] = bool(c.get("female"))
        # v44 (问题1): 家族沿革 — 私生女另立家族 (阿德尔海德 1118.4.2 别立冯·亚琛氏)
        # 与家族/宗族改名 (冯·亚琛 → 冯) 都不是记忆, 逐档差一是唯一来源。
        # 旧语义 (首见冻结) 使改名后全档人名停在旧名, 此处改为「末档现值 + 变更点」。
        _hid_now = c.get("dynasty_house")
        if isinstance(_hid_now, int):
            _h_now = _house_now(_hid_now)
            _did_now = dynasty_id_of(melt, _hid_now)
            _dn_now = _dyn_now(_did_now)
            if _hid_now != rec.get("dynasty_house") \
                    or (_h_now and _h_now != rec.get("house_name")) \
                    or (_dn_now and _dn_now != rec.get("dynasty_name")):
                _new_house = _hid_now != rec.get("dynasty_house")
                rec["dynasty_house"] = _hid_now
                if _h_now:
                    rec["house_name"] = _h_now
                if _dn_now:
                    rec["dynasty_name"] = _dn_now
                # 别立家族那一点用游戏 found_date (逐档差分只能在下一档发现变更,
                # 建立日比快照日精确: 阿德尔海德 1118.4.2 而非 1119.1.1)
                _pt_date = date_label
                if _new_house:
                    _fd = house_found_date(melt, _hid_now)
                    if _fd:
                        _pt_date = _fd
                hh = rec.setdefault("house_history", [])
                if not hh:
                    hh.append({"from": _pt_date, "house_id": rec["dynasty_house"],
                               "house_name": rec.get("house_name") or "",
                               "dynasty_id": _did_now,
                               "dynasty_name": rec.get("dynasty_name") or ""})
                elif hh[-1].get("house_id") != rec.get("dynasty_house") \
                        or hh[-1].get("house_name") != (rec.get("house_name") or "") \
                        or hh[-1].get("dynasty_name") != (rec.get("dynasty_name") or ""):
                    hh.append({"from": _pt_date, "house_id": rec["dynasty_house"],
                               "house_name": rec.get("house_name") or "",
                               "dynasty_id": _did_now,
                               "dynasty_name": rec.get("dynasty_name") or ""})
                if rec.get("name_zh"):
                    _nm_new = display_name(cache, cid, melt=melt, chars=chars,
                                           memo=_name_memo)
                    if _nm_new:
                        rec["name_full"] = _nm_new
        # v14: 旧缓存自愈 — dynasty_name 缺失 (v14 前缓存) 时按当前 dynasty_house
        # 补解析 (东方名序的姓); 按 house 记忆化, 同宗族数千人只解析一次。
        if rec.get("dynasty_name") is None and rec.get("dynasty_house") is not None:
            _hid = rec["dynasty_house"]
            _did = dynasty_id_of(melt, _hid)
            _dn_fix = _dyn_now(_did)
            if _dn_fix:
                rec["dynasty_name"] = _dn_fix
        # 文化/信仰 (v7): 熔件有值即更新 (覆盖文化改信); 缺失时保留最近已知值。
        # 角色死后游戏清空 culture/faith (实测死档约半数被清, 含前代玩家),
        # 缓存里存活期直接读到的 id 即为最直接的来源, facts 层缓存优先读取。
        # v44 (问题4): **此处不再预赋值** —— 预赋值会让紧随其后的差分恒为假,
        # 族属沿革 (culture_history) 于是永远只有首点 (实测阿德尔海德
        # 1132 年法兰克尼亚人→汉人, 缓存里 culture=47 而沿革只有 {1118, 39})。
        # 信仰沿革无此预赋值, 故一直正常 —— 两处对照即根因。
        _cid_cul = c.get("culture")
        if _cid_cul is not None:
            if rec.get("culture") != _cid_cul:
                ch = rec.setdefault("culture_history", [])
                if not ch or ch[-1].get("culture") != _cid_cul:
                    ch.append({"from": date_label, "culture": _cid_cul})
                rec["culture"] = _cid_cul
                if rec.get("name_zh"):
                    _nm_cul = display_name(cache, cid, melt=melt, chars=chars,
                                           memo=_name_memo, date=date_label)
                    if _nm_cul:
                        rec["name_full"] = _nm_cul
        _fid = c.get("faith")
        # v26: 改信记入 faith_history — 游戏不为玩家改信留任何记忆, 逐档差分是唯一
        # 来源 (田所2: 法华宗→艾什尔里派); 快照日一律 1月1日, 渲染只取年份。
        if _fid is not None:
            if rec.get("faith") != _fid:
                fh = rec.setdefault("faith_history", [])
                if not fh or fh[-1].get("faith") != _fid:
                    fh.append({"from": date_label, "faith": _fid})
            rec["faith"] = _fid
        # v49 (O5): 绰号变化点 —— 游戏只在**当前**存档的 nickname_text 里给绰号,
        # 旧档一旦被压缩/清理, 十年前那篇传记就只能拿到末档绰号 (v20/v21 的老问题:
        # 郭靖 1197 年才得「欺诈者」, 第 1 个十年不得出现)。原实现靠"重读该时代
        # 末档熔件"解决, 代价是整份解析; 此处按档锁存, 之后十年传记直接查沿革。
        # 键存在即记 (含空串: 该时代无绰号时清空, 与 v21 同日径)。
        if "nickname_text" in c:
            _nick = c.get("nickname_text")
            _nick = "" if _nick is None else str(_nick)
            _nh = rec.setdefault("nickname_history", [])
            if not _nh or _nh[-1].get("nickname") != _nick:
                _nh.append({"from": date_label, "nickname": _nick})
        # v11: 语言 (alive_data.languages): 同 culture 处理 — 有值即更新,
        # 缺失 (死后 alive_data 被清) 保留最近已知值, 供父名/族属推断与「语言」行。
        langs = (c.get("alive_data") or {}).get("languages") or []
        if langs:
            rec["languages"] = list(langs)
        # v24: 角色最近已知所在省份 (存活期每快照更新; 死亡写入时复制进
        # rec.death.location_province, 供刺客列传/时间线的受害者所在地标注)。
        _loc = (c.get("alive_data") or {}).get("location") or {}
        _prov = _loc.get("location") if isinstance(_loc, dict) else _loc
        if isinstance(_prov, int):
            rec["last_location"] = {"date": date_label, "province": _prov}
        # 特质与 trait_history (v4): 每快照 diff
        new_traits = c.get("traits") or []
        old_traits = rec.get("traits") or []
        if first_time or old_traits != new_traits:
            th = rec.setdefault("trait_history", {})
            if first_time:
                # 角色首见: 全部特质记 first=True (至晚自本档起已具)
                for t in new_traits:
                    k = trait_key(t)
                    if k not in th:
                        th[k] = [{"from": date_label, "to": None, "first": True}]
            else:
                old_set, new_set = set(old_traits), set(new_traits)
                for t in new_set - old_set:
                    k = trait_key(t)
                    if not any(iv.get("to") is None for iv in th.get(k, [])):
                        th.setdefault(k, []).append(
                            {"from": date_label, "to": None, "first": False})
                for t in old_set - new_set:
                    k = trait_key(t)
                    for iv in th.get(k, []):
                        if iv.get("to") is None:
                            iv["to"] = date_label
            rec["traits"] = new_traits
        # v32: 特质 XP 轨道样本 — 存档 `trait_xp_amounts` 是与 traits **顺序对齐**的扁平
        # 数组 (每条轨道一个数, 多轨特质按定义声明顺序占位; 实测马克龙档 3987/3987
        # 角色全对), 故样本必须与同档 traits 成对保存, 否则轨道对不上号。
        # 只在 (traits, xp) 之一变化时追加, 供 as_of 求当时档位名与进档履历。
        new_xp = list(c.get("trait_xp_amounts") or [])
        samples = rec.setdefault("trait_xp", [])
        if new_xp and (not samples
                       or samples[-1].get("traits") != list(new_traits)
                       or samples[-1].get("xp") != new_xp):
            samples.append({"from": date_label, "traits": list(new_traits),
                            "xp": new_xp})
        # v34 (问题7): 囚禁状态区间 — 存档 `alive_data.prison_data` 是「此刻是否在押」
        # 的权威字段 (释放会使它消失/换主), 而 `released_from_prison_memory` 只在
        # 囚禁者主动释放时才有记忆。两者互补: 有 prison_data 才能区分
        # 「仍在押」与「已出释而游戏未记」。
        _pd = (c.get("alive_data") or {}).get("prison_data")
        if isinstance(_pd, dict) and _pd.get("imprisoner") is not None:
            ph = rec.setdefault("prison_history", [])
            cur = {"from": date_label, "to": None,
                   "imprisoner": _pd.get("imprisoner"),
                   "type": _pd.get("type") or "",
                   "since": _pd.get("date") or date_label}
            _same_span = (ph and ph[-1].get("to") is None
                          and ph[-1].get("since") == cur["since"])
            if _same_span and ph[-1].get("imprisoner") == cur["imprisoner"] \
                    and ph[-1].get("type") == cur["type"]:
                # 与上一段同囚禁者/同类型 → 视为同一段 (换档不新开)
                pass
            elif _same_span:
                # v60 (问题4): 同一段囚禁**换了监禁者** —— 前一位监禁者死亡后
                # 囚禁转归其继承人, 游戏把 prison_data.date 留在原入狱日。
                # 崔佛 880.10.20 关押四人, 881.1.1 卒, 四人的监禁者即变为
                # 继位玩家 15179; 旧稿就地改写 imprisoner, 「谁关的→谁接着关」
                # 这条交接在事实面完全消失。改记 `from_imprisoner` 保留下手者,
                # `imprisoner` 仍作「到本档为止的监禁者」。
                ph[-1]["from_imprisoner"] = ph[-1].get("from_imprisoner") \
                    or ph[-1].get("imprisoner")
                ph[-1]["imprisoner"] = cur["imprisoner"]
                ph[-1]["type"] = cur["type"]
            else:
                if ph and ph[-1].get("to") is None:
                    ph[-1]["to"] = date_label
                ph.append(cur)
        elif rec.get("prison_history") and rec["prison_history"][-1].get("to") is None:
            # 本档已无 prison_data → 上一段在此档之前结束 (获释/换主)
            rec["prison_history"][-1]["to"] = date_label
        # 家庭: 直接字段 + 反查亲属 (v4)
        fam = family_of(c)
        fathers, mothers = _parents_of(chars, cid, parent_map, fam)
        if fathers:
            fam["father"] = fathers
        if mothers:
            fam["mother"] = mothers
        sib = _siblings_of(cid, parent_map, child_map, sibling_map, fam)
        if sib:
            fam["siblings"] = sib
        # 真正父亲 (v5): 直接字段 + 秘密推导 (v11: 预建索引, O(1) 查询)
        rf = real_father_of(melt, cid, chars, sec_candidates)
        if rf is not None:
            fam["real_father"] = [rf]
        # v8: 妾 (正向字段 + 反向 concubinist 并集, 去重)
        rev_cons = concubinist_map.get(cid, [])
        if rev_cons:
            fam["concubine"] = list(dict.fromkeys(
                (fam.get("concubine") or []) + rev_cons))
        # v60 (问题3): 亲属集**逐键合并, 空值不覆盖**。
        # 旧稿 `rec["family"] = fam` 无条件覆写: 死亡档的 `family_data` 已被游戏
        # 清空 (崔佛 881/882 档 family_data=[]), 880 档抓到的 `concubine: 15899`
        # 连同 `ever_spouses` 的来源一并丢掉, 模型于是自己造出「结缡三次、离异
        # 两次」的家室列传。亲属集是**曾有过**的事实 (婚配、父母、同胞、子女),
        # 旧值保留正确; 唯 `primary_spouse` 是单值指针 (新档给了新值即换代)。
        # 项目对母系婚/出狱缘由/结仇缘由都有闩存, 唯独婚配没有 —— 此处补齐。
        _fam_prev = rec.get("family") or {}
        _fam_new = dict(_fam_prev)
        for _k, _v in fam.items():
            if not _v:
                continue
            if _k == "primary_spouse" or _k not in _fam_prev:
                _fam_new[_k] = list(_v)
            else:
                _fam_new[_k] = list(dict.fromkeys(
                    list(_fam_prev.get(_k) or []) + list(_v)))
        rec["family"] = _fam_new
        # v31: 历史上所有配偶 (含离异/丧偶后被移出当前字段者) — 婚姻对判定用
        # (「与配偶同房」不写私通; 妻子后来的情人身份对照也靠它)。
        ever = set(rec["family"].get("ever_spouses") or [])
        for _k in ("primary_spouse", "spouse", "former_spouses",
                   "concubine", "former_concubines"):
            ever.update(int(x) for x in (fam.get(_k) or []))
        if ever:
            rec["family"]["ever_spouses"] = sorted(ever)
        # v31: 宫廷身份 (court_data) — 雇主/骑士/入宫日; 存档在角色身上给出,
        # 此前完全未收 («配偶的情人是主角廷中骑士» 这一关键身份无处可取)。
        cd = c.get("court_data") or {}
        if isinstance(cd, dict) and cd:
            cur = rec.get("court") or {}
            emp = cd.get("employer")
            if isinstance(emp, int):
                cur["employer"] = emp
            if cd.get("knight"):
                cur["knight"] = True
            jd = cd.get("join_court_date")
            if jd:
                cur["join_court_date"] = jd
            rec["court"] = cur
        # v41 (问题1): 逐档记录**每个入目标集角色的政体变化点** ——
        # 神罗 1087–1094 是封建制 (领主显示公爵/伯爵), 1095 起才改行政官制
        # (军区/分区/将军); 事实层按 as_of 取词时必须知道当时的政体。
        # 只记变化点 ({cid: [{date, government}]}), 与 camp_purposes 同范式。
        _ld_all = c.get("landed_data") or {}
        _gov_all = _ld_all.get("government") or ""
        if _gov_all:
            _chg = cache.setdefault("char_government_history", {})
            _h = _chg.setdefault(str(cid), [])
            if not _h or _h[-1].get("government") != _gov_all:
                _h.append({"date": date_label, "government": _gov_all})
        # v8: 击杀 (alive_data.kills / dead_data.kills, 跨年累积去重)
        kills = kills_of(c)
        if kills:
            rec["kills"] = sorted(set(rec.get("kills") or []) | set(kills))
        if cid == player_id:
            ld = c.get("landed_data") or {}
            rec["landed"] = {
                "domain": ld.get("domain"),
                "became_ruler_date": ld.get("became_ruler_date"),
                "government": ld.get("government"),
                "realm_capital": ld.get("realm_capital"),
                "vassal_count": len(ld.get("vassal_contracts") or []),
                "council": ld.get("council"),
                "laws": ld.get("laws"),
                "succession": ld.get("succession"),
                "strength": ld.get("strength"),
                "max_power": ld.get("max_power"),
            }
            # v26: 毡帐/庄园 (游牧牧群与口粮) — domiciles.database 条目
            _dom = player_domicile(melt, ld.get("domain"), cid)
            if _dom:
                rec["landed"]["herd"] = _dom.get("herd")
                rec["landed"]["provisions"] = _dom.get("provisions")
                rec["landed"]["domicile_type"] = _dom.get("domicile_type")
                rec["landed"]["domicile_province"] = _dom.get("province")
            # 玩家所在地历史 (v5: 游侠列传·行纪用): 只记位置变化点
            loc = (c.get("alive_data") or {}).get("location") or {}
            prov = loc.get("location") if isinstance(loc, dict) else loc
            if isinstance(prov, int):
                hist = cache.setdefault("player_locations", [])
                if not hist or hist[-1].get("province") != prov:
                    hist.append({"date": date_label, "province": prov})
            # v57 (问题3, 用户拍板): **首都沿革** —— realm_capital 是会搬的 (斯卡利茨实测
            # 924–945 在 b_long_hung/郡口, 946 起 b_dantu/丹徒), 而 cache.landed 只留末档值。
            # 处决地点一律取「主角当时的首都」(见 facts.victim_place), 故按变化点闩存。
            _cap = ld.get("realm_capital")
            if _cap is not None:
                _ch = cache.setdefault("capital_history", [])
                if not _ch or _ch[-1].get("title") != _cap:
                    _ch.append({"date": date_label, "title": _cap})
            # v24: 营地宗旨史 (历任营地阶段称呼词用: 头目/领袖/队长…);
            # 营地宗旨是持有者律法 (camp_purpose_*), 只记变化点防膨胀。
            if ld.get("government") == "landless_adventurer_government":
                _purpose = next(
                    (str(x).split("_", 2)[2] for x in (ld.get("laws") or [])
                     if str(x).startswith("camp_purpose_")), "")
                if _purpose:
                    _ph = cache.setdefault("camp_purposes", [])
                    if not _ph or _ph[-1].get("purpose") != _purpose:
                        _ph.append({"date": date_label, "purpose": _purpose})
            # 玩家所属家族名 (姓名字显示用, v4: 存纯家族名)
            if rec.get("dynasty_house") is not None:
                h = house_name_zh(melt, rec["dynasty_house"])
                if h:
                    cache["house_name"] = h
                # 玩家所属宗族 (v6: 文件夹按宗族划分, 新建家族不新开文件夹)
                did = dynasty_id_of(melt, rec["dynasty_house"])
                if did is not None:
                    cache["dynasty_id"] = did
                    dname = dynasty_name_zh(melt, did)
                    if dname:
                        cache["dynasty_name"] = dname
        dd = c.get("dead_data")
        if dd and rec["death"] is None:
            rec["death"] = {
                "date": dd.get("date"),
                "reason": dd.get("reason"),
                "killer": dd.get("killer"),
                "liege": dd.get("liege"),
                "liege_title": dd.get("liege_title"),
                "named_title": dd.get("named_title"),
            }
            # v24: 死前最近已知所在省份 (存活期快照捕获; 旧缓存/死后才入缓存无则缺省)
            if (rec.get("last_location") or {}).get("province") is not None:
                rec["death"]["location_province"] = rec["last_location"]["province"]
            if _new_deaths is not None:
                _new_deaths.append(cid)
        # 记忆: alive_data.memories → database
        seen = {(m.get("id"), m.get("creation_date")) for m in rec["memories"]}
        for mid in mem_ids_of(c):
            e = db.get(str(mid))
            if not e:
                continue
            b = memory_brief(mid, e)
            key = (b["id"], b.get("creation_date"))
            if key not in seen:
                b["first_seen"] = date_label
                rec["memories"].append(b)
                seen.add(key)
    # v28: 隐事 (secrets) 逐档差分 — 存档只存「当前秘密」, 无日期; 逐档比对即得
    # 「首次见于记载」的年份, 供《阴私录》写时间锚点。只收与相关集/朝廷要员
    # 有关的秘密以控体积 (实测每档相关 4–30 条)。
    _diff_secrets(cache, melt, date_label)
    # v28b: 叛乱派系领袖 (农民/民粹/游牧 起义) — 供人物称谓写
    # 「农民起义领袖叠溪寋」(存档 faction_manager 只存当前派系, 逐档差分)
    _diff_factions(cache, melt, date_label)
    # v29: 瘟疫/疫病 (epidemics) 逐档差分 — 存档给的是**游戏算好的动态名**
    # (「李黯之火」「撒丁痘」「东罗马痘」), 供《本纪》《家室列传》写疫病风味
    _diff_epidemics(cache, melt, date_label)
    # v40: 性病 (情人疱疹/大痘) 传播边逐档差分 —— 存档 triggered_event 队列里
    # 明确记着「谁把病传给了谁」(日精度), 供在性行为句后补「（某某把…传染给了某某）」
    _diff_disease_edges(cache, melt, date_label)
    # v31: 牵制 (hooks) 逐档差分 — 存档只存当前持有的牵制且无创建日
    _diff_hooks(cache, melt, date_label)
    # v43: 母系婚 (入赘) 婚姻对闩存 — 婚姻线系是《家室列传》「谁入谁家、子女随谁」
    # 的唯一依据, 存档只在 active_relations 上给这一个标记
    _latch_matrilineal(cache, melt, date_label)
    # v35: 奴役关系逐档差分 — 把「抓人 → 没为奴隶 → 放出牢房」与「真获释」分开
    _diff_enslavements(cache, melt, date_label)
    # v32: 纳妾类好感 (opinions) 逐档差分 — 「强行纳为侧室」是纳妾唯一带日期的记录
    _diff_opinions(cache, melt, date_label)
    # v50 (v47 方案 B): 结仇/结交缘由闩存 (同一数据源 opinions.active_opinions) —
    # 游戏只在关系存续期保留 `scripted_relations.<kind>.reason`, 关系一方死亡后
    # 条目连同缘由一起消失, 而生成只用最新一份熔件 → 见过即留, 供 facts 回退读
    _latch_relation_reasons(cache, melt, date_label)
    # v60 (问题3): 婚配闩存 —— 主角自身 family_data 在死亡档被清空, 而配偶/妾
    # 身上的反向指针逐档在册; 逐档扫下来, 生成期才有「一生有过哪些妻妾」可依
    _latch_spouses(cache, melt, date_label)
    # v56 (问题3): 出狱缘由闩存 —— 出狱类好感 10 年衰减且随持有者死亡消失, 而终传
    # 只载末档熔件 (斯卡利茨 924 年那批释放的「以人情获释」因此读不到)
    _latch_prison_manners(cache, melt, date_label)
    # v38 (问题1/问题4): Carnalitas 事件好感 (强奸/奴役/逼良为娼/前主奴) 与
    # `carn_recently_raped` 修正逐档差分 — 它们自带 start_date, 也是「出售奴隶」
    # 这种不留记忆的互动唯一的痕迹
    _diff_carnal_opinions(cache, melt, date_label)
    _diff_carnal_modifiers(cache, melt, date_label)
    # v44: 返回 True (此前 return cache —— 调用方 `if not ok:` 靠「非空 dict 恒真」
    # 侥幸成立; 打印/日志里则会把整份缓存 dump 出来)
    return True


# v35: 牵制类型黑名单 —— `house_head_hook`(家主权) 是**身份自带**的机制牵制,
# 不是「握有把柄」这一叙事事件: 家主对每个族人天然持有, 玩家档常见 2~8 条
# (德圣塔对两个儿子各一条)。facts.hook_notable 早已把它判为「不足以单开一篇隐事」,
# 但 hook_lines 仍会原样下发, 两处口径矛盾 → 《阴私录》里塞满「家主牵制」。
# 入库前即跳过, 省体积、省差分, 也杜绝下游复用。
# v38 (问题2, 用户拍板): 黑名单升级为**白名单** —— 判据见 `style.hook_type_kept`。
# 全档 7259 条牵制里 `house_head_hook` 5243、`filial_piety_hook` 1069、
# `favor_hook` 548, 而涉主角的只有 4 条 (全是这三类); 通用人情/身份自带牵制
# 不下发, 模型才不会拿「握有对元宗的牵制『人情』」当把柄去编。
def hook_type_kept(tp):
    """牵制类型是否入库 (v38, 问题2) —— 判据与 facts 侧同源 (style.hook_type_kept)。"""
    return _style.hook_type_kept(tp)


def matrilineal_pair_key(a, b):
    """婚姻对 → 缓存键 (小 id 在前, 与方向无关)。"""
    return f"{min(int(a), int(b))}>{max(int(a), int(b))}"


def _latch_prison_succession(cache, melt, date_label):
    """囚禁交接闩存 (v60 问题4) —— 「甲关的人, 甲死后归乙关」。

    崔佛 880.10.20 把四人下狱; 881.1.1 崔佛卒, 四人的
    `alive_data.prison_data.imprisoner` 随即变成继位者 15179, 而 `date` 仍是
    880.10.20 (游戏只换监禁者, 不改入狱日)。传主这一侧的缓存只并入到 880 档
    (881/882 档 `find_player` 已是继位者), 于是「谁接着关」这条交接在传记里
    完全消失, 只剩一句无限期的「此后一直未见释放」。

    本函数在**传主与熔件玩家不一致**时被调用 (即同战役后继玩家的档), 判据:
    ① 某人在押 (`prison_data.imprisoner` = 乙); ② 其 `imprisoned` 记忆里的
    `imprisoner` = 甲 (本缓存传主)。两条同时成立即记一条交接。

    记录形如::

        cache["prison_succession"]["46208"] = {
            "victim": 46208, "from": 38660, "to": 15179,
            "since": "880.10.20", "first_seen": "881.1.1"}

    首见即留 (不覆盖), 返回本档新增条数。"""
    pid = cache.get("player_id")
    if pid is None:
        return 0
    hist = cache.setdefault("prison_succession", {})
    added = 0
    db = _db(melt)
    for cid, c in all_characters(melt).items():
        if not isinstance(c, dict):
            continue
        pd = (c.get("alive_data") or {}).get("prison_data")
        if not isinstance(pd, dict):
            continue
        to_id = pd.get("imprisoner")
        if not isinstance(to_id, int) or to_id == pid:
            continue
        for mid in mem_ids_of(c):
            e = db.get(str(mid))
            if not isinstance(e, dict) or e.get("type") != "imprisoned":
                continue
            from_id = (e.get("participants") or {}).get("imprisoner")
            if from_id != pid:
                continue
            key = str(cid)
            if key in hist:
                continue
            hist[key] = {"victim": int(cid), "from": int(from_id), "to": int(to_id),
                         "since": str(e.get("creation_date") or ""),
                         "first_seen": date_label}
            added += 1
            break
    return added


def _latch_matrilineal(cache, melt, date_label):
    """母系婚 (入赘) 婚姻对闩存 (v43)。

    存档形如::

        relations.active_relations = [
            {"first": 33219, "second": 34000, "matrilineal": true}, …]

    语义 (游戏本地化原文):
      · `game_concept_matrilineal` = 母系; `MARRIAGE_MATRILINEAL_TOGGLE_TOOLTIP`
        = 「切换入赘」;
      · `game_concept_matrilineal_desc` = 在母系婚姻中, 出生的孩子将属于
        **母亲的家族**而不是父亲的。

    条目只在婚姻存续期出现, 故一律闩存 (见过即留): 离异/丧偶后仍能写出当年那桩
    入赘婚。返回本档新增对数。"""
    pairs = cache.setdefault("matrilineal_pairs", {})
    added = 0
    for e in (melt.get("relations") or {}).get("active_relations") or []:
        if not isinstance(e, dict) or "matrilineal" not in e:
            continue
        a, b = e.get("first"), e.get("second")
        if not isinstance(a, int) or not isinstance(b, int) or a == b:
            continue
        key = matrilineal_pair_key(a, b)
        if key not in pairs:
            pairs[key] = date_label
            added += 1
    return added


# v60 (问题3): 存档 `family_data` 里「关系持有者 → 对方」的键 → 对方所处的位分。
# 方向语义按存档实测 (崔佛档三名强纳之妾): `concubinist` 是**对方键**, 值 = 其
# 主人; 其余键都是**本人键**, 值 = 配偶/前配偶。位分优先序 `_SPOUSE_KIND_RANK`
# 保证同一对关系被两档以不同键记下时, 以最强的一位分为准 (正妻 > 侧室 > 妾 >
# 前配偶 > 前妾), 例如先为妾、后成正妻者最终记「primary_spouse」。
_SPOUSE_LATCH_KEYS = (
    # (键, 对方位分, 是否反向键)
    ("concubinist", "concubine", True),
    ("former_concubinists", "former_concubine", True),
    ("primary_spouse", "primary_spouse", False),
    ("spouse", "spouse", False),
    ("former_spouses", "former_spouse", False),
)

_SPOUSE_KIND_RANK = {
    "primary_spouse": 0, "spouse": 1, "concubine": 2,
    "former_spouse": 3, "former_concubine": 4,
}


def spouse_latch_key(player_id, other_id):
    """婚配闩存键 —— 方向固定为「主角 > 对方」(v60)。"""
    return f"{int(player_id)}>{int(other_id)}"


def _latch_spouses(cache, melt, date_label):
    """主角婚配闩存 (v60 问题3)。

    为什么需要: 主角**自己**的 `family_data` 在死亡档被游戏清空 —— 崔佛 868–879
    各档 `family_data = null`、880 档 `{"concubine": 15899}`、881/882 档 `[]`,
    而生成只用最新一份熔件, 于是「一生有过三名强纳之妾」在事实面变成**一无所有**,
    模型为填满《家室列传》的骨架遂自行虚构妻室 (实测虚构出「阿斯特里德」)。

    真正逐档在册的是**对方身上的反向指针** —— 三名妾在 882 档都写着
    `former_concubinists: [38660]`。故每次并档扫一遍全角色的 `family_data`,
    凡与主角相关者一律闩存; 首见即留 (不覆盖), 位分按 `_SPOUSE_KIND_RANK`
    取最强的一档。

    `since` (v60) 取**最早**的已知日期: `family_data` 只逐档可见, 首见档会
    晚于成婚日最多一年 (崔佛三名妾: 首见 880.1.1/881.1.1, 而成婚在
    879.9.1/880.2.1/880.5.9)。命名类好感 (`forced_me_concubine_marriage_opinion`
    等) 自带 `start_date`, 故同一档里按好感记录把日期前移。

    记录形如::

        cache["spouse_latch"]["38660>15899"] = {
            "player": 38660, "other": 15899, "kind": "concubine",
            "source": "concubinist" | "former_concubinists" | "spouse" | …,
            "since": "879.9.1", "first_seen": "880.1.1"}

    返回本档新增对数。"""
    pid = cache.get("player_id")
    if pid is None:
        return 0
    pid = int(pid)
    latch = cache.setdefault("spouse_latch", {})
    for cid, c in all_characters(melt).items():
        _latch_spouses_of(c, cid, latch, pid, date_label)
    _latch_spouse_dates(latch, melt, pid)
    return sum(1 for v in latch.values() if v.get("first_seen") == date_label)


# 命名类好感 (owner = 被纳者, target = 强纳者) → 与主角的婚配起始日。
# `forced_spouse_concubine_marriage_opinion` 不在本表: 它记在**原配**身上,
# 语义是「原配被离断」, 起始日的所指另算 (见 `_latch_spouse_dates`)。
_SPOUSE_OPINION_START = ("forced_me_concubine_marriage_opinion",
                         "concubine_with_monogamous_faith_opinion")


def _latch_spouse_dates(latch, melt, pid):
    """把命名类好感的 `start_date` 用作婚配起始日 (v60 问题3; 见 `_latch_spouses`)。

    `family_data` 只在年度熔件里出现, 首见档可比真实成婚日晚一年; 而
    `active_opinions` 的 `start_date` 是游戏自记的**当日**。两路取最早者。

    方向须与存档实测一致 (崔佛档三名强纳之妾): 纳妾类好感记在**被纳者**身上
    (`owner` = 被纳者, `target` = 强纳者); 而离断原配那一档记在**原配**身上
    (`owner` = 原配, `target` = 强纳者), 其 `start_date` 是被纳者与他人成婚的日子,
    **不是**与主角的起始日 —— 故那一档反过来取「owner 的配偶」中被纳者。"""
    for o in (melt.get("opinions") or {}).get("active_opinions") or []:
        if not isinstance(o, dict):
            continue
        owner, target = o.get("owner"), o.get("target")
        if not isinstance(owner, int) or not isinstance(target, int):
            continue
        dates = {}
        for v in _opinion_values(o):
            mod = str(v.get("modifier") or "")
            st = str(v.get("start_date") or "")
            if mod in _SPOUSE_OPINION_START and st and mod not in dates:
                dates[mod] = st
        if not dates:
            continue
        if target == pid:
            # 主角强纳 owner 为妾
            rec = latch.get(spouse_latch_key(pid, owner))
            if rec is not None:
                st = min(dates.values(), key=date_key)
                cur = rec.get("since") or rec.get("first_seen") or ""
                if not cur or date_key(st) < date_key(cur):
                    rec["since"] = st
        elif owner != pid:
            # owner 的原配被主角夺走: 取其前配偶中与主角闩存过的那一位
            ex_fd = ((melt.get("living") or {}).get(str(owner))
                     or (melt.get("dead_unprunable") or {}).get(str(owner)) or {})
            ex_fd = ex_fd.get("family_data") or {}
            for partner in (ex_fd.get("former_spouses") or []):
                if not isinstance(partner, int) or partner == pid:
                    continue
                if "forced_spouse_concubine_marriage_opinion" not in dates:
                    continue
                rec = latch.get(spouse_latch_key(pid, partner))
                if rec is None:
                    continue
                st = dates["forced_spouse_concubine_marriage_opinion"]
                cur = rec.get("since") or rec.get("first_seen") or ""
                if not cur or date_key(st) < date_key(cur):
                    rec["since"] = st


def _latch_spouses_of(char_obj, cid, latch, pid, date_label):
    """单个角色的 `family_data` → 婚配闩存 (v60; 见 `_latch_spouses`)。"""
    if not isinstance(char_obj, dict):
        return
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return
    fd = char_obj.get("family_data") or {}
    if not isinstance(fd, dict):
        return
    for key, kind, reverse in _SPOUSE_LATCH_KEYS:
        v = fd.get(key)
        if v is None:
            continue
        ids = [int(x) for x in (v if isinstance(v, list) else [v])
               if isinstance(x, int) or str(x).isdigit()]
        if pid not in ids and cid != pid:
            continue
        for other in ids:
            player, partner = (other, cid) if reverse else (cid, other)
            if player != pid or partner == pid:
                continue
            lk = spouse_latch_key(pid, partner)
            rec = latch.get(lk)
            if rec is None:
                latch[lk] = {"player": pid, "other": partner, "kind": kind,
                             "source": key, "since": date_label,
                             "first_seen": date_label}
                continue
            if _SPOUSE_KIND_RANK.get(kind, 9) \
                    < _SPOUSE_KIND_RANK.get(rec.get("kind") or "", 9):
                rec["kind"] = kind
                rec["source"] = key


def relation_reason_key(owner, target, kind):
    """关系缘由闩存键 (v50) —— 方向与存档一致 (<owner>|<target>|<kind>)。"""
    return f"{int(owner)}|{int(target)}|{kind}"


def _latch_relation_reasons(cache, melt, date_label):
    """关系缘由闩存 (v50, v47 方案 B; 纯程序, 不碰提示词)。

    存档形如::

        opinions.active_opinions = [
            {"owner": 16852591, "target": 33595411,
             "scripted_relations": {"rival": {"flags": "AA==",
                                              "reason": "rival_called_me_a_disgrace"}}}, …]

    `reason` 是游戏自己写下的成因键 (本地化模板见 `data/localization.json` →
    `relation_templates`: `rival_called_me_a_disgrace` = 「X指责Y是他们家族的
    耻辱」), 但它只在**关系存续期**存在: 关系一方死亡或关系解除后, 条目连同
    reason 一起从存档消失 (诺兰 1127/1130 档有、1143 档起无; 田所2 四对
    rival/grudge 实测 reason 分别在 1~13 年后随条目消失)。传记生成只载**最新**
    一份熔件供全部十年使用, 于是「结仇早、对方已死」的缘由永久读不到 —— 故在
    逐档并入时闩存: 首见即留, 之后只刷新 `last_seen`, 不覆盖最早的 reason。

    只收**涉主角**的条目 (控体积: 全档 5.6 万条 scripted_relations, 涉主角个位数);
    无 `reason` 的条目 (potential_rival / elder / disciple 等, 全档约 0.2% 的
    rival 亦无) 不入库 —— 「有因由」与「确无因由」的区别留给生成侧判据。
    返回本档新增条数。

    v56 (§10, 用户拍板「范围 A+B+C+D」): 收录面由「涉主角」放宽为「**双方都在
    本战役角色表内**」—— 缘由不只出现在主角身上: 斯卡利茨 郑思齐↔任宗本 的
    `lover_prison` (「…在X的地牢里相爱了」) 双方都不是玩家, 旧判据一条不收,
    于是传记里只剩「相恋」这个结果。代价实测可控 (本档累计 ≈6320 条 / ≈1.2 MiB)。
    同档一并记下 `province` (事发省份 id) —— v47 方案 B 原本要求, v50 漏落,
    导致 60 个含 `[PROVINCE.GetName]` 的 reason 模板渲染成病句
    (「…在的酒馆中共享了一顿美餐…」)。"""
    pid = cache.get("player_id")
    if pid is None:
        return 0
    chars = cache.get("characters") or {}
    hist = cache.setdefault("relation_reasons", {})
    added = 0
    for o in (melt.get("opinions") or {}).get("active_opinions") or []:
        if not isinstance(o, dict):
            continue
        owner, target = o.get("owner"), o.get("target")
        if not isinstance(owner, int) or not isinstance(target, int):
            continue
        if owner != pid and target != pid \
                and (str(owner) not in chars or str(target) not in chars):
            continue
        srs = o.get("scripted_relations")
        if not isinstance(srs, dict):
            continue
        for kind, v in srs.items():
            if not isinstance(v, dict) or not v.get("reason"):
                continue
            key = relation_reason_key(owner, target, kind)
            rec = hist.get(key)
            if rec is None:
                inv = v.get("involved_character")
                prov = v.get("province")
                hist[key] = {
                    "owner": owner, "target": target, "kind": str(kind),
                    "reason": str(v["reason"]),
                    "involved": inv if isinstance(inv, int) else None,
                    "province": prov if isinstance(prov, int) else None,
                    "first_seen": date_label,
                }
                added += 1
            else:
                rec["last_seen"] = date_label
    return added


def hook_slot_holder(first, second, field):
    """`relations.active_relations` 的一条牵制字段 → (持有者, 对象) (v33)。

    **方向在槽号，不在 first/second**：引擎把成对关系按键规范化存储
    （实测全档 6950 条 `active_hook_*` 记录 **first < second 恒成立**，
    一条反例也没有），方向由字段名 `active_hook_<N>` 承载：
    N 偶 → `first` 持有对 `second`；N 奇 → `second` 持有对 `first`。

    实证（马克龙 879 档）：
      · `house_head_hook`（家主权，持有者必为家主，而家主通常年长）——
        槽 0：4919/4920 条 `first` 年长；槽 1：44/55 条 `second` 年长；
      · Mod `longju_exent` 的 8 处 `add_hook = {target = scope:npc_2}` 全在
        `root`（＝丈夫；`npc_1` 是 `random_spouse`、`npc_2` 是通奸者）作用域内，
        即「干了我老婆」恒由丈夫持有 —— 与该档 opinions 的当事人标记
        （通奸者→丈夫的 `xiangyongletadeqizi_opinion`）逐条吻合：
        玩家(38677)对乔乔(43961)那条落在槽 0，对 15982/10851/12278（id 比玩家小、
        故排在 first）三条落在槽 1，**四条都是玩家自己的牵制**。

    v31 曾据单例推断「first 即持有者」——那只是玩家 id 恰好小于乔乔的巧合，
    导致同一批双向可读的记录里把玩家自己的牵制读成了「他人握有对主角的牵制」。"""
    slot = str(field).rsplit("_", 1)[-1]
    try:
        n = int(slot)
    except ValueError:
        n = 0
    return (first, second) if n % 2 == 0 else (second, first)


def _minus_years(date_str, n):
    """'934.4.2' 减 n 个日历年 → '924.4.2'; 取不到返回 '' (v56 问题3)。

    永久牵制的哨兵到期日 (9999.1.1) 一并返回 '' —— 它不是真日期。"""
    s = str(date_str or "")
    if not s or s.startswith("9999") or s == "none":
        return ""
    try:
        y, m, d = (int(x) for x in s.split(".")[:3])
        return f"{y - n}.{m}.{d}"
    except Exception:
        return ""


def _latch_prison_manners(cache, melt, date_label):
    """出狱缘由闩存 (v56 问题3)。

    为什么需要: `facts.release_manner` 原先只读**当次熔件**的 active_opinions,
    而出狱类好感一律 10 年衰减 (`ransomed_from_prison` 被脚本覆盖为 1 年), 且随
    持有者死亡立即从存档消失 —— 终传只载末档熔件, 十年前那批释放的缘由永久读不到,
    逐条回落「获释」(斯卡利茨 923.11.6 那 12 人于是全成「尽数获释」)。

    两路证据 (口径见 docs/方案_v56_斯卡利茨四问题.md §4):
      ① `opinions.active_opinions` 里的出狱类修饰符 —— 自带 start_date, 精确到日;
         `owner` = 被囚者, `target` = 释放者 (唯赎金那档的 target 是付款人)。
      ② `relations.active_relations` 里的 `favor_hook` / `indebted_hook` ——
         赎金·人情分支的留痕。它**没有创建日**, 但到期日 = 创建日 + 10 个日历年
         (实测 melt_925/927 共 15 条与 ① 的 start_date 逐日吻合), 故按到期日反推。
         这两类牵制不在 `hook_type_kept` 白名单内 (不下发《阴私录》), 只在本闩存里用。

    记录形如::

        cache["prison_manners"]["<被囚者>><监禁者>><日期>"] = {
            "victim": …, "jailer": …, "date": "924.4.2",
            "kind": "demanded_hook" | "hook",   # 好感来源记修饰符名, 牵制来源记结局族
            "src": "opinion" | "hook", "first_seen": "925.1.1"}

    首见即留 (不覆盖) —— 与熔件新旧无关, 故终传也能回读。只收「涉玩家」的条目
    (控体积; 全档涉主角的出狱类好感/牵制各十余条)。返回本档新增条数。"""
    pid = cache.get("player_id")
    if pid is None:
        return 0
    hist = cache.setdefault("prison_manners", {})
    added = 0

    def _put(victim, jailer, date, kind, src):
        nonlocal added
        if not isinstance(victim, int) or not isinstance(jailer, int) or not date:
            return
        key = f"{victim}>{jailer}>{date}"
        if key in hist:
            return
        hist[key] = {"victim": victim, "jailer": jailer, "date": str(date),
                     "kind": kind, "src": src, "first_seen": date_label}
        added += 1

    # ---- ① 出狱类好感修饰符 ----
    for o in (melt.get("opinions") or {}).get("active_opinions") or []:
        if not isinstance(o, dict):
            continue
        ow, tg = o.get("owner"), o.get("target")
        if not isinstance(ow, int) or not isinstance(tg, int):
            continue
        if ow != pid and tg != pid:
            continue
        for v in _opinion_values(o):
            mod = str(v.get("modifier") or "")
            if mod not in _style.PRISON_MANNER_OPINION_MODS:
                continue
            _put(ow, tg, str(v.get("start_date") or ""), mod, "opinion")

    # ---- ② 赎金·人情牵制 (到期日反推创建日) ----
    for e in (melt.get("relations") or {}).get("active_relations") or []:
        if not isinstance(e, dict):
            continue
        first, second = e.get("first"), e.get("second")
        if not isinstance(first, int) or not isinstance(second, int):
            continue
        if first != pid and second != pid:
            continue
        for k, v in e.items():
            if not str(k).startswith("active_hook") or not isinstance(v, dict):
                continue
            if str(v.get("type") or "") not in _style.PRISON_MANNER_HOOK_TYPES:
                continue
            made = _minus_years(v.get("expiration_date"), 10)
            if not made:
                continue
            holder, target = hook_slot_holder(first, second, k)
            _put(target, holder, made, "hook", "hook")
    return added


def _diff_hooks(cache, melt, date_label):
    """把本档牵制并入 cache["hooks"] (逐档差分)。

    存档形如::

        relations.active_relations = [
            {"first": 38677, "second": 43961,
             "active_hook_0": {"type": "ganlewodelaopo_hook",
                               "expiration_date": "9999.1.1"}}, …]

    方向由槽号定（见 `hook_slot_holder`）：槽 0 = first 持有对 second，
    槽 1 = second 持有对 first；first/second 本身只是**按键规范化的成对编号**
    （小 id 在前），不带方向义。
    只收「持有者或对象为玩家」的牵制 (控体积; 全档 6950 条 → 玩家相关 14 条)。
    记录形如::

        {"38677>43961>ganlewodelaopo_hook":
            {"holder": 38677, "target": 43961, "type": "ganlewodelaopo_hook",
             "expiration": "9999.1.1", "first_seen": "870.1.1", "first": false}}

    `first` = 首档即见 (数据起点前已有); 本档消失即记 `lost_at`。"""
    pid = cache.get("player_id")
    if pid is None:
        return
    ar = (melt.get("relations") or {}).get("active_relations") or []
    hist = cache.setdefault("hooks", {})
    first_snap = len(cache.get("sources") or []) <= 1
    want = {}
    for e in ar:
        if not isinstance(e, dict):
            continue
        first, second = e.get("first"), e.get("second")
        if not isinstance(first, int) or not isinstance(second, int):
            continue
        if first != pid and second != pid:
            continue
        for k, v in e.items():
            if not str(k).startswith("active_hook") or not isinstance(v, dict):
                continue
            tp = v.get("type")
            if not tp:
                continue
            if not hook_type_kept(tp):
                continue
            holder, target = hook_slot_holder(first, second, k)
            want[f"{holder}>{target}>{tp}"] = {
                "holder": holder, "target": target, "type": str(tp),
                "expiration": v.get("expiration_date"),
            }
    for key, v in want.items():
        rec = hist.get(key)
        if rec is None:
            hist[key] = dict(v, first_seen=date_label, first=first_snap)
            continue
        rec["expiration"] = v.get("expiration")
        rec.pop("lost_at", None)
        rec["last_seen"] = date_label
    for key, rec in hist.items():
        if key not in want and not rec.get("lost_at"):
            rec["lost_at"] = date_label


def enslaved_ids(melt, owner_id):
    """本档被 owner_id 奴役的角色 id 集 (Carnalitas)。

    存档形如::

        opinions.active_opinions = [
            {"owner": 38670, "target": 14590,
             "scripted_relations": {"slave": {"flags": "AA=="}}}, …]

    `owner` = 奴隶主, `target` = 奴隶 (与 `slave_owner` 成对, 见 Mod
    common/scripted_relations/carnal_slave_relations.txt)。"""
    out = set()
    for o in (melt.get("opinions") or {}).get("active_opinions") or []:
        if not isinstance(o, dict) or o.get("owner") != owner_id:
            continue
        if "slave" in (o.get("scripted_relations") or {}):
            t = o.get("target")
            if isinstance(t, int):
                out.add(t)
    return out


def all_enslavements(melt):
    """本档**全部**主奴关系 {奴隶 id: 主人 id} (v38, 问题4)。

    与 `enslaved_ids` 同源 (`scripted_relations.slave`), 但不再限定主人是玩家 ——
    主角把奴隶卖出后, 奴隶会带着 `slave` 关系转到买家名下, 只有看全档才能读出
    「卖给了谁」; 这也是把「被出售」与「被释放」分开的判据 (被释放者换成
    `former_slave` 特质, 不再有 slave 关系)。"""
    out = {}
    for o in (melt.get("opinions") or {}).get("active_opinions") or []:
        if not isinstance(o, dict):
            continue
        if "slave" not in (o.get("scripted_relations") or {}):
            continue
        owner, target = o.get("owner"), o.get("target")
        if isinstance(owner, int) and isinstance(target, int) and owner != target:
            out[target] = owner
    return out


def _diff_enslavements(cache, melt, date_label):
    """把本档主奴关系并入 cache["enslavements"] (逐档差分)。

    Carnalitas 的 `carn_enslave_effect` 在奴役的**同一刻**对已被囚的奴隶执行
    `release_from_prison = yes` (Mod common/scripted_effects/carn_slave_effects.txt),
    所以存档里那句 `released_from_prison_memory` 正是「没为奴隶」这一步 ——
    只有这层关系能把它与「真获释」区分开。关系本身不带创建日, 逐档差分即得
    「首次见于记载」的档期。

    记录形如::

        {"38670>14590": {"owner": 38670, "slave": 14590,
                         "first_seen": "873.1.1", "first": false,
                         "last_seen": "888.1.1", "lost_at": null}}

    `first` = 首档即见 (数据起点前已为奴隶); 本档不再出现即记 `lost_at`
    (被解放 / 转卖 / 死亡)。

    v38 (问题4, 用户拍板「全部做完」): 三点改动 ——
    ① 收**全部**关系 (不再只收主角为主者): 奴隶被卖出后仍进缓存, 才有痕迹可查;
    ② 主人变化时把前任主人记进 `prev_owners`, `owner` 随档刷新 ——
       「转卖给了谁」由此可考;
    ③ 关系消失时记录 `end_owner` (消失那一刻仍在奴役他的人是买家) 或
       `freed` (那一刻已无人奴役他 = 转为 `former_slave`)。
    """
    pid = cache.get("player_id")
    if pid is None:
        return
    hist = cache.setdefault("enslavements", {})
    first_snap = len(cache.get("sources") or []) <= 1
    cur = all_enslavements(melt)
    want = {}
    for slave, owner in cur.items():
        want[f"{owner}>{slave}"] = {"owner": owner, "slave": slave}
    for key, v in want.items():
        rec = hist.get(key)
        if rec is None:
            hist[key] = dict(v, first_seen=date_label, first=first_snap)
            continue
        if rec.get("owner") != v["owner"]:
            owners = rec.setdefault("prev_owners", [])
            if rec.get("owner") is not None and rec["owner"] not in owners:
                owners.append(rec["owner"])
            rec["owner"] = v["owner"]
        rec.pop("lost_at", None)
        rec.pop("end_owner", None)
        rec.pop("freed", None)
        rec["last_seen"] = date_label
    for key, rec in hist.items():
        if key in want or rec.get("lost_at"):
            continue
        rec["lost_at"] = date_label
        slave = rec.get("slave")
        now_owner = cur.get(slave) if isinstance(slave, int) else None
        if isinstance(now_owner, int):
            rec["end_owner"] = now_owner
        else:
            rec["freed"] = True


# v32: 纳妾类关系好感 — 存档里「强行纳为侧室」唯一带确切日期的记录
# (本地化: forced_me_concubine=将我强行纳为侧室、concubine_with_monogamous_faith=
#  身为侧室却信从一夫一妻、forced_spouse_concubine=将我的配偶强行纳为侧室、
#  stole_concubine=偷走了我的侧室)
_CONCUBINE_OPINIONS = {
    "forced_me_concubine_marriage_opinion",
    "concubine_with_monogamous_faith_opinion",
    "forced_spouse_concubine_marriage_opinion",
    "stole_concubine_opinion",
}

# v38 (问题1/问题4): Carnalitas 关系好感族 — 与前缀/后缀匹配, 只收涉主角者。
# 前缀族取自 Mod common/opinion_modifiers/*.txt:
#   carn_raped_*（曾强奸我/我的情人/我的朋友/家庭成员）— 受害方与其亲友持有;
#   carn_enslaved_*（奴役了我/亲族/近亲/宗族/目标/宾客, 含 crime 变体）;
#   carn_former_slave_or_slave_owner_opinion（曾经是主奴关系）— **出售与释放
#     都留这一条**, 是「人被卖掉之后」在存档里最直接的痕迹。
# 后缀族 (v32 纳妾同表之外单列): 被要求解放、被逼卖淫 —— 两者也都是指向主角的
# 单条事件好感。
_CARNAL_OPINION_PREFIXES = ("carn_raped_", "carn_enslaved_")
_CARNAL_OPINION_SUFFIXES = (
    "carn_former_slave_or_slave_owner_opinion",
    "carn_forced_me_into_prostitution_opinion",
    "carn_demanded_manumission_opinion",
)


def _carnal_opinion_kind(mod):
    """关系好感 modifier 是否属 Carnalitas 事件族 (v38); 是则返回族名。"""
    m = str(mod or "")
    for p in _CARNAL_OPINION_PREFIXES:
        if m.startswith(p):
            return "rape" if p == "carn_raped_" else "enslave"
    for s in _CARNAL_OPINION_SUFFIXES:
        if m == s:
            if "former_slave" in s:
                return "former_slave"
            if "prostitution" in s:
                return "prostitution"
            return "manumission"
    return ""


def _diff_carnal_opinions(cache, melt, date_label):
    """Carnalitas 关系好感逐档差分 → cache["carnal_opinions"] (v38, 问题1/问题4)。

    存档形如::

        opinions.active_opinions = [
            {"owner": 50473, "target": 15601,
             "temporary_opinion": {"modifier": "carn_former_slave_or_slave_owner_opinion",
                                   "start_date": "881.4.17",
                                   "expiration_date": "882.1.12"}}, …]

    方向: `owner` = 持有该好感的人, `target` = 施加者 (与 `_diff_opinions` 同口径)。
    这些好感**自带 start_date**, 比逐档差分精确 —— 出售奴隶那一刻 (881.4.17)
    正是由此坐实。只收 `owner`/`target` 有一方是主角的记录 (控体积):
    全档 7000+ 条好感里 Carnalitas 的不过百余条。"""
    pid = cache.get("player_id")
    if pid is None:
        return
    acts = (melt.get("opinions") or {}).get("active_opinions") or []
    hist = cache.setdefault("carnal_opinions", {})
    first_snap = len(cache.get("sources") or []) <= 1
    want = {}
    for o in acts:
        if not isinstance(o, dict):
            continue
        owner, target = o.get("owner"), o.get("target")
        if not isinstance(owner, int) or not isinstance(target, int):
            continue
        if owner != pid and target != pid:
            continue
        for v in _opinion_values(o):
            mod = v.get("modifier")
            kind = _carnal_opinion_kind(mod)
            if not kind:
                continue
            want[f"{owner}>{target}>{mod}"] = {
                "owner": owner, "target": target, "modifier": str(mod),
                "kind": kind,
                "start": v.get("start_date"),
                "expiration": v.get("expiration_date"),
            }
    for key, v in want.items():
        rec = hist.get(key)
        if rec is None:
            hist[key] = dict(v, first_seen=date_label, first=first_snap)
            continue
        rec["start"] = v.get("start") or rec.get("start")
        rec["expiration"] = v.get("expiration")
        rec.pop("lost_at", None)
        rec["last_seen"] = date_label
    for key, rec in hist.items():
        if key not in want and not rec.get("lost_at"):
            rec["lost_at"] = date_label


def _char_modifier_names(c):
    """角色条目里的**临时修正**名列表 (v38)。

    存档实测 (`alive_data` 段内, 与 stress/gold 同级)::

        modifier={
            modifier=carn_recently_raped        expiration_date=886.8.28
        }

    解析后的 melt 里位于 `alive_data` 下, 键名单复数按 rakaly 归一, 故同时兼容
    `modifiers` / `modifier` / `character_modifiers`。"""
    if not isinstance(c, dict):
        return []
    out = []
    for key in ("modifiers", "modifier", "character_modifiers"):
        v = (c.get("alive_data") or {}).get(key)
        if v is None:
            v = c.get(key)
        if isinstance(v, dict):
            out.extend(str(k) for k in v.keys())
        elif isinstance(v, list):
            for m in v:
                if isinstance(m, dict):
                    for kk in ("modifier", "key", "name"):
                        if m.get(kk):
                            out.append(str(m[kk]))
                            break
                elif m:
                    out.append(str(m))
    return out


def _diff_carnal_modifiers(cache, melt, date_label):
    """角色修正 `carn_recently_raped` 逐档差分 → cache["carnal_modifiers"] (v38)。

    Mod `common/modifiers/carn_rape_modifiers.txt` 的 `carn_recently_raped`
    (本地化「最近被强奸」, health −0.25, **5 年**) 由 `carn_rape_victim_stress_effect`
    加在受害方身上 —— 与性事记忆相比它多一层「此事确实被按强迫处理」的语义,
    且是受害方在无记忆时的兜底信号。只收缓存已知角色与主角 (控体积)。"""
    pid = cache.get("player_id")
    if pid is None:
        return
    hist = cache.setdefault("carnal_modifiers", {})
    first_snap = len(cache.get("sources") or []) <= 1
    known = set(cache.get("characters") or {})
    want = {}
    for cid, c in all_characters(melt).items():
        if "carn_recently_raped" not in _char_modifier_names(c):
            continue
        try:
            cid_i = int(cid)
        except (TypeError, ValueError):
            continue
        if cid_i != pid and str(cid) not in known:
            continue
        want[f"{cid_i}>carn_recently_raped"] = {"character": cid_i}
    for key, v in want.items():
        rec = hist.get(key)
        if rec is None:
            hist[key] = dict(v, first_seen=date_label, first=first_snap)
            continue
        rec.pop("lost_at", None)
        rec["last_seen"] = date_label
    for key, rec in hist.items():
        if key not in want and not rec.get("lost_at"):
            rec["lost_at"] = date_label


def _opinion_values(o):
    """条目里的 temporary_opinion → 列表 (同键重复被 _merge_dup_pairs 并成 list)。"""
    v = o.get("temporary_opinion")
    if isinstance(v, dict):
        return [v]
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return []


def _diff_opinions(cache, melt, date_label):
    """把本档纳妾类关系好感并入 cache["opinions"] (逐档差分)。

    存档形如::

        opinions.active_opinions = [
            {"owner": 17039, "target": 38691,
             "temporary_opinion": {"modifier": "forced_me_concubine_marriage_opinion",
                                   "start_date": "880.1.1",
                                   "expiration_date": "900.1.1", "days": 7300}}, …]

    方向: `owner` = 持有该好感的当事人, `target` = 施加者 (实测菲利普档妾 17039
    → 主角 38691)。`forced_me_concubine_marriage_opinion` 由脚本
    `concubine_on_accept_effect` 在该人**身陷囹圄或守贞**时给予, 同一段脚本紧接着
    `release_from_prison = yes` —— 即「强纳为妾当日即出狱」, 这是「劫掠掳人 →
    强纳为妾」在存档里**唯一带确切日期**的记录 (纳妾本身不留记忆, family_data
    只给当前状态)。只收涉主角者 (控体积)。

    记录形如::

        {"17039>38691>forced_me_concubine_marriage_opinion":
            {"owner": 17039, "target": 38691,
             "modifier": "forced_me_concubine_marriage_opinion",
             "start": "880.1.1", "expiration": "900.1.1",
             "first_seen": "881.1.1", "first": false}}

    `first` = 首档即见 (数据起点前已有); 本档消失即记 `lost_at`。"""
    pid = cache.get("player_id")
    if pid is None:
        return
    acts = (melt.get("opinions") or {}).get("active_opinions") or []
    hist = cache.setdefault("opinions", {})
    first_snap = len(cache.get("sources") or []) <= 1
    want = {}
    for o in acts:
        if not isinstance(o, dict):
            continue
        owner, target = o.get("owner"), o.get("target")
        if not isinstance(owner, int) or not isinstance(target, int):
            continue
        if owner != pid and target != pid:
            continue
        for v in _opinion_values(o):
            mod = v.get("modifier")
            if mod not in _CONCUBINE_OPINIONS:
                continue
            want[f"{owner}>{target}>{mod}"] = {
                "owner": owner, "target": target, "modifier": str(mod),
                "start": v.get("start_date"), "expiration": v.get("expiration_date"),
            }
    for key, v in want.items():
        rec = hist.get(key)
        if rec is None:
            hist[key] = dict(v, first_seen=date_label, first=first_snap)
            continue
        rec["expiration"] = v.get("expiration")
        rec.pop("lost_at", None)
        rec["last_seen"] = date_label
    for key, rec in hist.items():
        if key not in want and not rec.get("lost_at"):
            rec["lost_at"] = date_label


def _diff_epidemics(cache, melt, date_label):
    """把本档 epidemics.database 并入 cache["epidemics"] (逐档差分)。

    记录形如::

        {"83886080": {"name": "卡利甫痢", "type": "dysentery", "intensity": "minor",
                      "start_province": 4248, "provinces": 20,
                      "first_seen": "888.1.1", "first": true, "lost_at": None}}

    `first` = 首档即见 (数据起点前已存在, 因此其起年取游戏给的 creation_date)。"""
    db = (melt.get("epidemics") or {}).get("database") or {}
    hist = cache.setdefault("epidemics", {})
    for eid, e in db.items():
        if not isinstance(e, dict):
            continue
        rec = hist.get(str(eid))
        if rec is None:
            hist[str(eid)] = {
                "name": e.get("name") or "",
                "type": e.get("type") or "",
                "intensity": e.get("intensity") or "",
                "creation_date": e.get("creation_date") or date_label,
                "start_province": e.get("start_province"),
                "provinces": len(e.get("infections") or {}),
                # v35 (问题5): 感染省份集 — 判「这场疫是否触及此人属地/所在郡」,
                # 供疾病特质取该场疫的游戏动态名 (平原热/丘陵热…)。只留前 400 个,
                # 与 tools/snap.py 的 melt_tables 同口径, 控缓存体积。
                "infections": sorted(
                    (int(x) for x in (e.get("infections") or {})
                     if str(x).isdigit()))[:400],
                "first_seen": date_label,
                "first": True,
                "lost_at": None,
            }
            continue
        # 逐档刷新: 名称/规模/强度可能变 (疫情蔓延), 名称按最新档
        for k, v in (("name", e.get("name") or ""), ("intensity", e.get("intensity") or ""),
                     ("provinces", len(e.get("infections") or {}))):
            if v not in (None, ""):
                rec[k] = v
        _inf = sorted(int(x) for x in (e.get("infections") or {})
                      if str(x).isdigit())[:400]
        if _inf:
            rec["infections"] = _inf
        rec["first"] = False
        rec["last_seen"] = date_label
        rec["lost_at"] = None
    # 本档不再出现的疫情 → 记 lost_at (不再在传播)
    ids = {str(k) for k, v in db.items() if isinstance(v, dict)}
    for sid, rec in hist.items():
        if isinstance(rec, dict) and sid not in ids and not rec.get("lost_at"):
            rec["lost_at"] = date_label


# ---------------------------------------------------------------------------
# v40: 性病 (情人疱疹 / 大痘) 传播边 —— 存档 triggered_event 队列
# ---------------------------------------------------------------------------
# 用户 2026-09-15 需求: 「发生性病传播时, 在性行为后面加上一句
# （某某把疱疹/大痘传染给了某某）; 此时不论该性行为是自愿或非自愿都记录
# （只有这一个特例）; 如果不是调用行动传播的则单独在记忆中记录」。
#
# 数据来源: 每条熔件顶层 `triggered_event` (load_melt 后是**列表**) 的隐藏事件::
#
#     {"event": "health.1200",
#      "scope": {"root": {"type": "char", "identity": 50852}, "seed": …,
#                "event_targets": {
#                    "sick_character": {"type": "char", "identity": 74421},
#                    "disease_type": {"type": "flag", "flag": "lovers_pox"},
#                    "infecting_partner": {"type": "char", "identity": 74418}}},
#      "date": "1093.1.6"}
#
# 语义 (游戏 20_health_effects.txt / events/health_events.txt 逐行核对):
#   · Carnalitas 性事当场调 `risk_of_std_from_effect` (carn_had_sex_with_effect:
#     50% 情人疱疹 / 30% 大痘), `contract_*_from` 把**已患病的 partner** 存进
#     `infecting_partner`、病人自己存进 `sick_character`;
#   · 得病后立刻排 `health.1200`(情人疱疹 days={60 1000}) / `health.1201`
#     (大痘 days={250 1500}) 的**复检**, 队列里的 `date` 是复检日, 故
#     感染日 ∈ [复检日−上限, 复检日−下限] (由 facts 侧按病种换算);
#   · 本体的 `health.1200` 也会在 lover/consort 之间**按期**传播 —— 这类没有
#     性事行动, 事实层单独成行 (「不是调用行动传播」那一档)。
# `infecting_partner` 缺省 (卖淫/先天) 或等于 `sick_character` (本人复检) 时
# 不构成传播边; 前者由事实层记「染上X」, 后者丢弃。
_STD_DISEASES = ("lovers_pox", "great_pox", "early_great_pox")


def _iter_triggered(melt):
    """triggered_event → 事件 dict 列表 (load_melt 把重复键并成 list)。"""
    te = melt.get("triggered_event")
    if isinstance(te, list):
        return [e for e in te if isinstance(e, dict)]
    if isinstance(te, dict):   # 兜底: 未合并的单条/字典形
        out = []
        for v in te.values():
            if isinstance(v, dict):
                out.append(v)
            elif isinstance(v, list):
                out += [x for x in v if isinstance(x, dict)]
        return out
    return []


def _char_identity(v):
    """事件槽位 ({"type":"char","identity":N}) → 角色 id; 取不到返回 None。"""
    if isinstance(v, dict):
        i = v.get("identity")
        return i if isinstance(i, int) else None
    return v if isinstance(v, int) else None


def _std_edges_of(melt):
    """本档 triggered_event → [(disease, source, target, fire_date)] (只收真传播边)。

    `sick_character` 缺失的条目 (存档退化) 丢弃。"""
    out = []
    for e in _iter_triggered(melt):
        tgt = ((e.get("scope") or {}).get("event_targets") or {})
        dt = tgt.get("disease_type")
        flag = dt.get("flag") if isinstance(dt, dict) else None
        if flag not in _STD_DISEASES:
            continue
        sick = _char_identity(tgt.get("sick_character"))
        src = _char_identity(tgt.get("infecting_partner"))
        if sick is None:
            continue
        if src is not None and src == sick:
            continue          # 本人按期复检: 不是传播
        out.append((str(flag), src, sick, str(e.get("date") or "")))
    return out


def _diff_disease_edges(cache, melt, date_label):
    """性病传播边逐档差分 → ``cache["disease_edges"]`` (v40)。

    记录形如::

        {"lovers_pox>74418>74421>1092.6.3":
            {"disease": "lovers_pox", "source": 74418, "target": 74421,
             "fire_date": "1092.6.3", "first_seen": "1093.1.1",
             "first": True, "last_seen": "1093.1.1"}}

    同一条边会连续出现在多档 (排期 → 复检), 故按「病种>源>目标>复检日」去重,
    `first_seen`/`last_seen` 记首末次见到的快照日; `first=True` 表示数据起点即见。"""
    hist = cache.setdefault("disease_edges", {})
    for disease, src, tgt, fire in _std_edges_of(melt):
        key = f"{disease}>{src}>{tgt}>{fire}"
        rec = hist.get(key)
        if rec is None:
            hist[key] = {"disease": disease, "source": src, "target": tgt,
                         "fire_date": fire, "first_seen": date_label,
                         "first": True, "last_seen": date_label}
            continue
        rec["first"] = False
        rec["last_seen"] = date_label


def _court_holder_ids(melt):
    """本档高位头衔 (h_/e_/k_) 与朝廷职司 (e_minister_*) 的持有者 id 集
    (《朝局风云录·要员隐事》取材范围)。"""
    out = set()
    lt = (melt.get("landed_titles") or {}).get("landed_titles") or {}
    for t in lt.values():
        if not isinstance(t, dict):
            continue
        key = t.get("key") or ""
        if not key.startswith(("h_", "e_", "k_")):
            continue
        h = t.get("holder")
        if isinstance(h, int):
            out.add(h)
    return out


def _diff_secrets(cache, melt, date_label):
    """把本档 secrets 并入 cache["secrets_history"] (逐档差分)。

    记录形如::

        {"102": {"type": "secret_exam_cheater", "owner": 38682,
                 "target": 10914, "participants": [38682],
                 "first_seen": "868.1.1", "first": true,   # 首档即见 = 之前已有
                 "known_by": [{"id": 38682, "from": "868.1.1", "first": true}],
                 "lost_at": "879.1.1"}}                    # 此后不再见于档
    """
    sec_root = melt.get("secrets") or {}
    secs = sec_root.get("secrets") or {}
    known = sec_root.get("known_secrets") or []
    if not secs:
        return
    related = set()
    for k in (cache.get("characters") or {}):
        try:
            related.add(int(k))
        except (TypeError, ValueError):
            continue
    related |= _court_holder_ids(melt)
    pid = cache.get("player_id")
    if pid is not None:
        related.add(int(pid))
    if not related:
        return
    # 相关判定: owner/target/participant 属相关集, 或相关者知情 (把柄维度)
    want = {}
    for sid, v in secs.items():
        if not isinstance(v, dict):
            continue
        owner = v.get("owner")
        tgt = v.get("target")
        tid = tgt.get("identity") if isinstance(tgt, dict) else None
        parts = [x for x in (v.get("participants") or []) if isinstance(x, int)]
        ids = {x for x in (owner, tid, *parts) if isinstance(x, int)}
        if ids & related:
            want[str(sid)] = v
    knowers = {}
    for e in known:
        o = e.get("owner")
        sid = e.get("secret")
        if not isinstance(o, int) or sid is None:
            continue
        if o not in related:
            continue
        knowers.setdefault(str(sid), []).append(o)
        if str(sid) not in want:
            v = secs.get(str(sid))
            if isinstance(v, dict):
                want[str(sid)] = v
    hist = cache.setdefault("secrets_history", {})
    first_snap = len(cache.get("sources") or []) <= 1
    for sid, v in want.items():
        tgt = v.get("target")
        tid = tgt.get("identity") if isinstance(tgt, dict) else None
        rec = hist.get(sid)
        if rec is None:
            rec = {
                "type": v.get("type") or "",
                "owner": v.get("owner") if isinstance(v.get("owner"), int) else None,
                "target": tid if isinstance(tid, int) else None,
                "participants": [x for x in (v.get("participants") or [])
                                 if isinstance(x, int)],
                "first_seen": date_label,
                "first": first_snap,
                "known_by": [],
            }
            if v.get("relation_type"):
                rec["relation_type"] = v.get("relation_type")
            hist[sid] = rec
        else:
            # 复现/换主: 记录最新 owner 与 target (秘密可因原主死亡转归他人)
            if isinstance(v.get("owner"), int):
                rec["owner"] = v.get("owner")
            if isinstance(tid, int):
                rec["target"] = tid
            rec.pop("lost_at", None)
        known_ids = {x.get("id") for x in rec.get("known_by") or []}
        for o in dict.fromkeys(knowers.get(sid) or []):
            if o in known_ids:
                continue
            rec.setdefault("known_by", []).append({
                "id": o, "from": date_label, "first": first_snap})
            known_ids.add(o)
    # 消失: 本档已不见 -> 记 lost_at (仅在记录仍属相关时)
    for sid, rec in hist.items():
        if sid in want or rec.get("lost_at"):
            continue
        rec["lost_at"] = date_label


# v28b: 起义类派系 (领袖即叛军之首) — 游戏 faction_manager.type 的取值。
# 其余 (independence/claimant/liberty/nation_fracturing/replace_regent) 是
# 封臣派系, 其领袖本身有领地头衔, 不另给起义称谓。
_UPRISING_TYPES = ("peasant_faction", "escalated_peasant_faction",
                   "populist_faction", "nomadic_faction")

# v37 (问题8): 起义头衔名 → 派系类型 (游戏 title_name_data.name 的取值)。
# 起义头衔由剧本创建 (key = x_script_*/x_mc_*), 带 capital (起事州府)、date (起事日)
# 与 holder (领袖); `delete_on_destroy` 使它在领袖死后从存档消失 —— 故必须在
# 其存活期的档里取, 或由 refresh_uprising_bases.py 按时代熔件补档。
_UPRISING_TITLE_NAMES = {
    "农民叛乱": "peasant_faction",
    "民粹暴动": "populist_faction",
    "游牧民叛乱": "nomadic_faction",
    "农民起义": "peasant_faction",
    "民粹起义": "populist_faction",
    "游牧民起义": "nomadic_faction",
}


def _title_name_of(t):
    """头衔显示名: title_name_data.name → key。"""
    tnd = (t or {}).get("title_name_data") or {}
    return (tnd.get("name") or "").strip() or ((t or {}).get("key") or "")


def uprising_title_bases(melt):
    """本档起义头衔 → {holder_cid: base} (v37, 问题8)。

    base = {"holder", "title", "county", "county_name", "name", "type", "from"}:
    头衔 id / 起事州府 id (title.capital, 实为 c_ 头衔 id) / 州府名 / 头衔名
    (农民叛乱…, 也是起义词来源) / 派系类型 / 起事日 (title.date)。
    判据: 头衔键为剧本键 (x_script_/x_mc_/x_ho_) 且头衔名在 _UPRISING_TITLE_NAMES 内。
    """
    lt = (melt.get("landed_titles") or {}).get("landed_titles") or {}
    out = {}
    for tid, t in lt.items():
        if not isinstance(t, dict):
            continue
        key = t.get("key") or ""
        if not key.startswith(("x_script_", "x_mc_", "x_ho_")):
            continue
        name = _title_name_of(t)
        ftype = _UPRISING_TITLE_NAMES.get(name)
        if not ftype:
            continue
        holder = t.get("holder")
        if not isinstance(holder, int):
            continue
        county = t.get("capital")
        county_name = ""
        if isinstance(county, int):
            county_name = _title_name_of(lt.get(str(county)) or {})
        out[str(holder)] = {
            "holder": holder, "title": int(tid), "county": county,
            "county_name": county_name, "name": name, "type": ftype,
            "from": t.get("date"),
        }
    return out


def _diff_factions(cache, melt, date_label):
    """把本档起义派系的**领袖**并入 cache["factions"] (逐档差分)。

    记录形如::

        {"43603": {"type": "peasant_faction", "first_seen": "870.1.1",
                   "last_seen": "871.1.1", "first": false,
                   "target": 10529, "counties": [14534, 14538],
                   "faith": 136, "culture": 166,
                   "base": {"title": 18606, "county": 15246, "county_name": "渠州",
                            "name": "农民叛乱", "from": "870.9.26"}}}

    只收起义类派系 (其余封臣派系领袖本有领地头衔)。存档无派系起止日期,
    首见档即记 first_seen, 最后一次出现记 last_seen。
    领袖一律记录 (不按相关集过滤): 逐档差分是时序的, 叛乱领袖常在身故后才因
    隐事/谋杀进入传主视野 (陆氏 43603 即 870–871 在党、872 才见于隐事档),
    先按相关集过滤会漏掉其起义身份; 每档约 40–55 名领袖, 体积可忽略。

    v37 (问题8): 另并**起义头衔**路线 —— 起义头衔 (x_script_* 且名为「农民叛乱」等)
    带真实 base 州府 (capital)、建立日与持有者; 派系记录缺失者 (周氏2 的王伯玉/
    张知微: 同持「农民叛乱」头衔却无 faction 记录) 由此补上领袖身份与起事地。
    """
    facs = (melt.get("faction_manager") or {}).get("factions") or {}
    hist = cache.setdefault("factions", {})
    first_snap = len(cache.get("sources") or []) <= 1
    for _fid, rec in facs.items():
        if not isinstance(rec, dict):
            continue
        ftype = rec.get("type") or ""
        if ftype not in _UPRISING_TYPES:
            continue
        leader = rec.get("leader")
        if not isinstance(leader, int):
            leader = rec.get("special_character")
        if not isinstance(leader, int):
            continue
        vars_ = {}
        for v in (rec.get("variables") or {}).get("data") or []:
            d = v.get("data") or {}
            if v.get("flag") in ("faction_faith", "faction_culture") \
                    and isinstance(d.get("identity"), int):
                vars_[v["flag"]] = d["identity"]
        counties = [m.get("county") for m in (rec.get("title_members") or [])
                    if isinstance(m, dict) and isinstance(m.get("county"), int)]
        r = hist.get(str(leader))
        if r is None:
            r = {"type": ftype, "first_seen": date_label,
                 "last_seen": date_label, "first": first_snap}
            hist[str(leader)] = r
        else:
            r["type"] = ftype
            r["last_seen"] = date_label
        if isinstance(rec.get("target"), int):
            r["target"] = rec["target"]
        if counties:
            r["counties"] = counties
        if "faction_faith" in vars_:
            r["faith"] = vars_["faction_faith"]
        if "faction_culture" in vars_:
            r["culture"] = vars_["faction_culture"]
    # v37: 起义头衔路线 (含无 faction 记录的领袖)
    for _holder, base in uprising_title_bases(melt).items():
        r = hist.get(str(_holder))
        if r is None:
            r = {"type": base["type"], "first_seen": date_label,
                 "last_seen": date_label, "first": first_snap}
            hist[str(_holder)] = r
        else:
            r.setdefault("type", base["type"])
        r["base"] = {k: base[k] for k in ("title", "county", "county_name",
                                          "name", "from", "type") if k in base}


# ---------------------------------------------------------------------------
# 死角色记忆回溯 (v5: 死后记忆被清空 → 从死前最近一份存档恢复)
# ---------------------------------------------------------------------------

def recover_dead_memories_from(melt, cache, cid, chars=None):
    """从某档 melt 恢复角色 cid 的记忆 (死前最后一份存档)。
    记忆对象存于该档 character_memory_manager.database, 角色 alive_data.memories
    引用之。返回恢复条数。
    v11: chars 由调用方按熔件预建一次传入 (回溯对每个死者调用, 旧实现每次重建
    全角色字典)。"""
    rec = cache["characters"].get(str(cid))
    if rec is None:
        return 0
    if chars is None:
        chars = all_characters(melt)
    c = chars.get(str(cid))
    if c is None:
        return 0
    db = _db(melt)
    seen = {(m.get("id"), m.get("creation_date")) for m in rec["memories"]}
    added = 0
    for mid in mem_ids_of(c):
        e = db.get(str(mid))
        if not e:
            continue
        b = memory_brief(mid, e)
        key = (b["id"], b.get("creation_date"))
        if key not in seen:
            b["first_seen"] = melt.get("date") or "?"
            rec["memories"].append(b)
            seen.add(key)
            added += 1
    return added


# ---------------------------------------------------------------------------
# 记忆归档 (v12: 边车索引, 回溯不再整份加载旧熔件)
# ---------------------------------------------------------------------------
# 死角色记忆回溯需要「死前最近一份存档」里该角色的记忆。旧实现每次回溯都要
# json.load 一份 160 MB 全量熔件 (实测 13 份 ≈ 87s, 占每年合并的大头)。
# 归档 = 每份熔件的瘦身边车 melt_<日期>_idx.json, 只含回溯需要的:
#   - chars: {cid: [记忆ID...]} (alive_data.memories, 死者回退 dead_data.memories)
#   - db:    {记忆ID: 精简条目} (仅 memory_brief 用到的字段)
# 全量熔件仍是权威源 (extract_snapshot/传记/rebuild-cache 继续用), 归档只在
# 回溯缺失时惰性构建一次并持久化, 之后回溯直接读归档 (0.1s 级)。


def _index_stem(melt_path):
    """熔件路径 → 边车命名基准 (去掉压缩后缀与 `.json`)。`a/melt_900_01_01.json.gz`
    → `a/melt_900_01_01`。v49。"""
    p = melt_stem(melt_path)
    return p[:-5] if p.lower().endswith(".json") else p


def _melt_index_variants(melt_path):
    """熔件 → 归档边车的三种可能路径 (`.json` / `.json.gz` / `.json.xz`), 读取时都试。"""
    stem = _index_stem(melt_path)
    return [stem + "_idx.json", stem + "_idx.json.gz", stem + "_idx.json.xz"]


def melt_index_path(melt_path):
    """全量熔件 → 记忆归档边车路径: melt_913_01_01.json → melt_913_01_01_idx.json。
    命名含 _idx, 不会被 _iter_melts / melt_file_in 等按 melt_<日期>(_p<id>)?.json
    匹配的代码误当成全量熔件。
    v44: 熔件为 `.json.gz` 时边车同名 `.json.gz` (归档随熔件一起压)。
    v49 (方案①): `.json.xz` 时边车同名 `.json.xz`。"""
    p = str(melt_path)
    low = p.lower()
    for suf in (".xz", ".gz"):
        if low.endswith(suf):
            return _index_stem(p) + "_idx.json" + suf
    return _index_stem(p) + "_idx.json"


def build_melt_index(melt):
    """从全量熔件构建记忆归档 dict (不入库)。

    v40: 变量元组补上第 4 位 = flag 类变量的值 (`data.flag`) —— 与
    `memory_brief` v21 同口径。旧版只存 [flag, type, identity], 于是**走边车
    恢复的记忆**丢掉 `reason` (头衔授予/丧失缘由) 等标志值, 头衔得失句从
    「受X册封为Y」退化成「登位，得Y」(2026-09-15 诺兰重建实测: 边车一旦生成,
    重建即走 `_brief_from_index` 这条有损路径)。"""
    out = {"date": melt.get("date"), "chars": {}, "db": {}}
    chars = out["chars"]
    db = out["db"]
    for cid, c in all_characters(melt).items():
        if not isinstance(c, dict):
            continue
        ids = mem_ids_of(c)
        if ids:
            chars[cid] = [str(x) for x in ids]
    for mid, e in _db(melt).items():
        if not isinstance(e, dict):
            continue
        vars_out = []
        for f in (e.get("variables") or {}).get("data") or []:
            d = f.get("data") or {}
            vars_out.append([f.get("flag"), d.get("type"), d.get("identity"),
                             d.get("flag") if (d.get("type") or "") == "flag" else None])
        db[mid] = {
            "type": e.get("type"),
            "participants": e.get("participants"),
            "creation_date": e.get("creation_date"),
            "end_date": e.get("end_date"),
            "vars": vars_out,
        }
    return out


def save_melt_index(melt_path, melt):
    """构建并持久化记忆归档边车 (原子写), 返回边车路径。

    v44: 随熔件后缀 —— 熔件是 `.json.gz` 时边车也写 `.json.gz`。
    v49 (O8): 边车是派生件, **一律写压缩档** —— 最新熔件为明文时旧的写法会落下
    一份明文边车 43 MiB (写 2.1 s), 现在写 `.json.gz` (5.6 MiB, 写 1.2 s, 读 +0.07 s);
    冷档的边车随熔件后缀, 之后 compact 后台再升成 xz。
    v49: 紧凑分隔符 (与玩家缓存同口径; 读者一律 json.loads)。"""
    base = melt_index_path(melt_path)
    low = base.lower()
    path = base if low.endswith((".gz", ".xz")) else base + ".gz"
    tmp = path + ".tmp"
    idx = build_melt_index(melt)
    if path.lower().endswith(".xz"):
        with lzma.open(tmp, "wt", encoding="utf-8") as fp:
            json.dump(idx, fp, ensure_ascii=False, separators=(",", ":"))
    else:
        with gzip.open(tmp, "wt", encoding="utf-8") as fp:
            json.dump(idx, fp, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return path


def load_melt_index(melt_path):
    """读取记忆归档边车; 不存在/损坏返回 None。
    v44: 两种后缀都试 —— 归档可能先于熔件被压缩 (或反之)。
    v49 (O2): 改走二进制整读 (省一层解码器)。"""
    for p in _melt_index_variants(melt_path):
        if not os.path.isfile(p):
            continue
        try:
            return json.loads(_read_melt_bytes(p))
        except Exception:
            continue
    return None


def _brief_from_index(mid, e):
    """归档条目 → memory_brief 同构精简条目 (vars 用 [flag,type,identity,value] 元组)。

    v40: 兼容旧边车的三元组 (无 value) —— 缺第 4 位时 value 记 None。"""
    return {
        "id": mid,
        "type": e.get("type"),
        "participants": e.get("participants"),
        "creation_date": e.get("creation_date"),
        "end_date": e.get("end_date"),
        "vars": [{"flag": v[0], "type": v[1], "identity": v[2],
                  "value": v[3] if len(v) > 3 else None}
                 for v in (e.get("vars") or []) if isinstance(v, (list, tuple))],
    }


def recover_dead_memories_from_index(index, cache, cid):
    """从记忆归档恢复角色 cid 的记忆 (与 recover_dead_memories_from 等价,
    数据来自边车索引而非全量熔件)。返回恢复条数。"""
    rec = cache["characters"].get(str(cid))
    if rec is None:
        return 0
    ids = (index.get("chars") or {}).get(str(cid))
    if not ids:
        return 0
    db = index.get("db") or {}
    seen = {(m.get("id"), m.get("creation_date")) for m in rec["memories"]}
    added = 0
    for mid in ids:
        e = db.get(str(mid))
        if not e:
            continue
        b = _brief_from_index(mid, e)
        key = (b["id"], b.get("creation_date"))
        if key not in seen:
            b["first_seen"] = index.get("date") or "?"
            rec["memories"].append(b)
            seen.add(key)
            added += 1
    return added


# ---------------------------------------------------------------------------
# 关系汇总
# ---------------------------------------------------------------------------

def summarize_relations(cache):
    """与主角结仇/结怨/死敌清单 (双方视角)。"""
    pid = cache["player_id"]
    out = []
    if pid is None:
        return out

    def scan(owner_id):
        rec = cache["characters"].get(str(owner_id))
        if not rec:
            return
        for mem in rec.get("memories") or []:
            if mem["type"] not in ("became_rivals", "became_grudge", "became_nemesis"):
                continue
            slot = {"became_rivals": "rival", "became_grudge": "grudge",
                    "became_nemesis": "nemesis"}[mem["type"]]
            other = (mem.get("participants") or {}).get(slot)
            if other is None:
                continue
            out.append({
                "other": other,
                "other_name": resolve_full_name(cache, other),
                "owner": owner_id,
                "type": mem["type"],
                "date": mem.get("creation_date"),
            })
    scan(pid)
    for cid in cache["characters"]:
        if int(cid) != pid:
            scan(int(cid))
    return out
