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
import json
import os
import re
import threading
import time

import localization
import llm

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


def house_name_zh(melt, house_id):
    """宗族 id → 姓氏中文。取值链 (实测):
      1) dynasty_house[<id>].localized_name  (存档自带, 如 冯·大马士革)
      2) .name 的码点 (dynn_Bian_908A → 边)
      3) 本地化表 (culture_dynasty_title_names / dynasties 键)
      4) .key 字段 (house_abbasid → dynn_Abbasid → 阿拔斯, v8.2)
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
        # 2) name 字段 (dynn_ 前缀码点解码)
        name = e.get("name") or ""
        if name.startswith("dynn_"):
            name = name[len("dynn_"):]
        dec = zh(decode_codepoints(name))
        if dec and any("\u3400" <= ch <= "\u9fff" for ch in dec):
            return dec
        # 3) 本地化表
        t = localization.table()
        for cand in (name, e.get("name") or ""):
            v = localization.loc(t, cand)
            if v and v != cand:
                return v
        # 4) house key (house_abbasid → dynn_Abbasid → 阿拔斯, v8.2)
        hkey = e.get("key")
        if isinstance(hkey, str) and hkey.startswith("house_"):
            v = _dynn_lookup(t, hkey[len("house_"):])
            if v:
                return v
        return ""
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


def dynasty_name_zh(melt, dynasty_id):
    """宗族 id → 宗族名中文。取值链 (实测):
      1) dynasties[<id>].localized_name    (Mod 档自带, 如 冯·大马士革 / 崔佛)
      2) .key 字符串 → 本地化表 (dynn_<key> / <key>)
      3) 创始家族兜底: 同宗族内 found_date 最早的 house 取名 (边 / 奥尔西尼…)
      全部失败返回 '' (由调用方回退家族名)。"""
    if dynasty_id is None:
        return ""
    try:
        dyn = (melt.get("dynasties") or {}).get("dynasties") or {}
        e = dyn.get(str(dynasty_id)) or {}
        # 1) 存档自带本地化名
        ln = e.get("localized_name") or ""
        if ln and any("\u3400" <= ch <= "\u9fff" for ch in ln):
            return zh(ln)
        # 2) key 字符串 → 本地化表变体
        key = e.get("key")
        if isinstance(key, str):
            t = localization.table()
            for cand in ("dynn_" + key, key):
                v = localization.loc(t, cand)
                if v and v != cand:
                    return v
        # 3) 创始家族兜底: 同宗族内 found_date 最早的 house
        dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
        best = None
        for hid, h in dh.items():
            if not isinstance(h, dict):  # v7: none 条目防护
                continue
            if h.get("dynasty") == dynasty_id:
                fd = h.get("found_date") or "9999.1.1"
                if best is None or fd < best[0]:
                    best = (fd, hid)
        if best:
            return house_name_zh(melt, int(best[1]))
        return ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------

def _sanitize_none(o):
    """递归把 Clausewitz 空值字符串 'none' 替换为 None (v7)。

    rakaly json 把 `= none` 渲染成字符串 'none'; 而代码里的 `x or {}` 防护
    对真值字符串 'none' 无效 ('none' or {} → 'none'), 随后 .get() 即崩溃
    (实测 881.1.11 熔件含 6938 个 'none', living 4508 / dead 262 / 标题 1...)。
    'none' 语义上等同字段缺失, 替换为 None 后所有 or {} 防护恢复正常。"""
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


def load_melt(path):
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    return _sanitize_none(data)


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
    """记忆对象 → 精简条目 (附记忆ID; vars 带 {flag,type,identity} 以便取关联对象)。"""
    vars_out = []
    for f in (e.get("variables") or {}).get("data") or []:
        d = f.get("data") or {}
        vars_out.append({
            "flag": f.get("flag"),
            "type": d.get("type"),
            "identity": d.get("identity"),
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
# 缓存库 (schema 3: 每玩家一份缓存)
# ---------------------------------------------------------------------------

EMPTY_CACHE = {
    "schema": 4,
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
    "court_positions": [],       # [{date, positions:[{type, employee, hire_date, task}]}] 玩家宫廷/营地官职逐年 (v7)
    "house_motto": None,         # 玩家家族家训 (dynasty_house.motto, 字符串或模板 dict) (v7)
    "characters": {},
    "relations": {},
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


def load_cache(path):
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                cache = json.load(fp)
            # 兼容旧 schema: 补齐 v4 字段
            for k, v in EMPTY_CACHE.items():
                cache.setdefault(k, v)
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _save_lock(path):
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(cache, fp, ensure_ascii=False, indent=1)
        os.replace(tmp, path)  # 原子替换, 防并发读写撕裂


def char_record(cache, cid):
    key = str(cid)
    if key not in cache["characters"]:
        cache["characters"][key] = {
            "id": cid,
            "first_name": None,
            "name_zh": None,
            "house_name": None,     # 姓氏 (边)
            "name_full": None,      # 姓+名 (边诚)
            "birth": None,
            "death": None,
            "dynasty_house": None,
            "culture": None,
            "faith": None,
            "traits": [],
            "trait_history": {},    # {特质key: [{from, to, first}]} 获得/消失区间 (v4)
            "family": {},
            "landed": {},
            "memories": [],
            "kills": [],        # v8: 击杀 id 列表 (alive_data.kills ∪ dead_data.kills, 跨年累积)
        }
    return cache["characters"][key]


# ---------------------------------------------------------------------------
# 姓名解析
# ---------------------------------------------------------------------------

_NAMES = None


def _load_names(names_path):
    global _NAMES
    if _NAMES is None:
        try:
            with open(names_path, encoding="utf-8") as fp:
                _NAMES = json.load(fp).get("names") or {}
        except Exception:
            _NAMES = {}
    return _NAMES


def resolve_full_name(cache, cid, names_path=None, melt=None):
    """角色 id → 完整中文名 (姓+名)。优先级: 缓存 name_full → 缓存 name_zh+house_name
    → names.json (name_zh+house_name) → '' (未知, 由调用方决定措辞)。"""
    if cid is None:
        return ""
    key = str(cid)
    rec = (cache.get("characters") or {}).get(key)
    if rec:
        if rec.get("name_full"):
            return rec["name_full"]
        nm = rec.get("name_zh")
        if nm:
            h = rec.get("house_name") or ""
            return h + nm if h else nm
    if names_path:
        n = _load_names(names_path).get(key)
        if n:
            nm = n.get("name_zh")
            if nm:
                h = n.get("house_name") or ""
                return h + nm if h else nm
    if melt is not None:
        # 极端兜底: 直接从 melt 取角色对象解码
        c = all_characters(melt).get(key)
        if c:
            nm = name_zh(c)
            if nm:
                h = house_name_zh(melt, c.get("dynasty_house"))
                return h + nm if h else nm
    return ""


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


def _family_name_order(cache, rec, melt):
    """角色自身文化缺失 (死后清空/幼年未录) 时, 依亲属文化推断名序:
    父 → 母 → 同胞 → 子女 → 配偶 (子承父/母文化, 同胞同源; 配偶跨族婚姻参考价值最低, 放最后)。
    返回 name_order_convention 字符串 ('' = 西方默认); 亲属文化全部缺失时返回 None。"""
    if melt is None:
        return None
    cultures = (melt.get("culture_manager") or {}).get("cultures") or {}
    fam = rec.get("family") or {}
    for key in ("father", "mother", "siblings", "child",
                "primary_spouse", "spouse", "former_spouses"):
        for x in (fam.get(key) or []):
            r = (cache.get("characters") or {}).get(str(x)) or {}
            cul = r.get("culture")
            if cul is None or str(cul) not in cultures:
                continue
            return cultures[str(cul)].get("name_order_convention") or ""
    return None


def name_display(cache, cid, melt=None, names_path=None):
    """按文化的显示名: 东方姓在前 (赵阿足), 西方名·姓 (巴沙尔·冯·大马士革)。
    自身文化缺失 (死后 culture 清空/幼年未录) 时依亲属文化推断名序;
    无从推断回退原 name_full (姓+名)。"""
    if cid is None:
        return ""
    key = str(cid)
    rec = (cache.get("characters") or {}).get(key) or {}
    nm = rec.get("name_zh") or ""
    h = rec.get("house_name") or ""
    if not nm and names_path:
        n = _load_names(names_path).get(key)
        if n:
            nm = n.get("name_zh") or ""
            h = h or n.get("house_name") or ""
    if not nm:
        return rec.get("name_full") or ""
    fallback = rec.get("name_full") or (h + nm if h else nm)
    cul = rec.get("culture")
    if cul is None:
        order = _family_name_order(cache, rec, melt)
        if order is None:
            return fallback
        if order in EASTERN_NAME_ORDERS:
            return h + nm if h else nm
        # 亲属文化为西方默认 (order==''): 名·姓
        return f"{nm}·{h}" if h else nm
    order = name_order_of(melt, cul)
    if order in EASTERN_NAME_ORDERS:
        return h + nm if h else nm
    cultures = (melt or {}).get("culture_manager") or {}
    if str(cul) in (cultures.get("cultures") or {}):
        # 文化已知且为西方默认 (order==''): 名·姓
        return f"{nm}·{h}" if h else nm
    return fallback


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

def extract_snapshot(cache, melt, date_label, _new_deaths=None):
    """把一个存档快照并入缓存。返回 False 表示玩家不一致被拒绝。
    _new_deaths: 可选列表, 本次并入「首次记录死亡」的角色 id (int) 会追加进来,
    供调用方只对「新死亡」角色做死档记忆回溯, 避免每轮全量扫描 (v9)。"""
    player_id = find_player(melt)
    if cache["player_id"] is not None and player_id is not None \
            and cache["player_id"] != player_id:
        print(f"  [跳过] 档期 {date_label} 玩家 {player_id} 与缓存玩家 "
              f"{cache['player_id']} 不一致")
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

    # 玩家宫廷/营地官职 (v7): court_positions.database 中 employer == 玩家,
    # 逐年记录 (含宫廷职位与营地军官, 供「每年主角宫廷/营地内的人的官职」)。
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
        # 玩家家族家训 (v7): dynasty_house[<id>].motto (字符串或模板 dict)
        pobj = chars.get(str(player_id))
        if isinstance(pobj, dict) and pobj.get("dynasty_house") is not None:
            dh_ = (melt.get("dynasties") or {}).get("dynasty_house") or {}
            he = dh_.get(str(pobj.get("dynasty_house"))) or {}
            if isinstance(he, dict) and he.get("motto"):
                cache["house_motto"] = he.get("motto")

    # 玩家主头衔名变化 (v4): 主头衔 title_name_data (custom → name) 或信封名
    if player_id is not None:
        tname = ""
        thn = []
        ld = (chars.get(str(player_id)) or {}).get("landed_data") or {}
        dom = ld.get("domain") or []
        if dom:
            t = lt.get(str(dom[0])) or {}
            tnd = t.get("title_name_data") or {}
            tname = tnd.get("custom") or tnd.get("name") or ""
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
                hist.append({"date": d, "name": tname})

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
            # 姓氏 + 姓名合并 (v3/v4)
            if rec["dynasty_house"] is not None:
                h = house_name_zh(melt, rec["dynasty_house"])
                rec["house_name"] = h
                if h and rec["name_zh"]:
                    rec["name_full"] = h + rec["name_zh"]
            rec["birth"] = c.get("birth")
            rec["culture"] = c.get("culture")
            rec["faith"] = c.get("faith")
        # 文化/信仰 (v7): 熔件有值即更新 (覆盖文化改信); 缺失时保留最近已知值。
        # 角色死后游戏清空 culture/faith (实测死档约半数被清, 含前代玩家),
        # 缓存里存活期直接读到的 id 即为最直接的来源, facts 层缓存优先读取。
        if c.get("culture") is not None:
            rec["culture"] = c.get("culture")
        if c.get("faith") is not None:
            rec["faith"] = c.get("faith")
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
        rec["family"] = fam
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
            # 玩家所在地历史 (v5: 游侠列传·行纪用): 只记位置变化点
            loc = (c.get("alive_data") or {}).get("location") or {}
            prov = loc.get("location") if isinstance(loc, dict) else loc
            if isinstance(prov, int):
                hist = cache.setdefault("player_locations", [])
                if not hist or hist[-1].get("province") != prov:
                    hist.append({"date": date_label, "province": prov})
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
    return cache


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


def melt_index_path(melt_path):
    """全量熔件 → 记忆归档边车路径: melt_913_01_01.json → melt_913_01_01_idx.json。
    命名含 _idx, 不会被 _iter_melts / melt_file_in 等按 melt_<日期>(_p<id>)?.json
    匹配的代码误当成全量熔件。"""
    p = str(melt_path)
    return p[:-5] + "_idx.json" if p.lower().endswith(".json") else p + "_idx.json"


def build_melt_index(melt):
    """从全量熔件构建记忆归档 dict (不入库)。"""
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
            vars_out.append([f.get("flag"), d.get("type"), d.get("identity")])
        db[mid] = {
            "type": e.get("type"),
            "participants": e.get("participants"),
            "creation_date": e.get("creation_date"),
            "end_date": e.get("end_date"),
            "vars": vars_out,
        }
    return out


def save_melt_index(melt_path, melt):
    """构建并持久化记忆归档边车 (原子写), 返回边车路径。"""
    path = melt_index_path(melt_path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(build_melt_index(melt), fp, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def load_melt_index(melt_path):
    """读取记忆归档边车; 不存在/损坏返回 None。"""
    try:
        with open(melt_index_path(melt_path), encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return None


def _brief_from_index(mid, e):
    """归档条目 → memory_brief 同构精简条目 (vars 用 [flag,type,identity] 三元组)。"""
    return {
        "id": mid,
        "type": e.get("type"),
        "participants": e.get("participants"),
        "creation_date": e.get("creation_date"),
        "end_date": e.get("end_date"),
        "vars": [{"flag": v[0], "type": v[1], "identity": v[2]}
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
