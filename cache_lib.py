# -*- coding: utf-8 -*-
"""CK3 memory cache library.

Save structure and the reason this cache exists:
  - character_memory_manager.database maps memory id -> memory object
    (memory ids come from the same id pool as characters).
  - alive_data.memories on each character lists that character's memory ids.
  - Both the list and the memory objects are dropped when the character dies,
    so memories are only recoverable from yearly snapshots taken before death.

Records also carry localized names (localization.py), trait date ranges
(rec["trait_history"]), a reverse kinship index (rec["family"] father/mother/
siblings, needed because family_data is often empty while the parent side of a
marriage keeps the child list), title/realm history, and the session's
output folder.
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
import style as _style   # hook whitelist predicate (style.hook_type_kept) and wording tables

# ---------------------------------------------------------------------------
# Name decoding
# ---------------------------------------------------------------------------

_CP_RE = re.compile(r"_([0-9A-Fa-f]{3,5})(?=_|$)")

# Common traditional -> simplified map (surname and given-name characters).
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
    """Convert traditional/mixed text to simplified via the _SIMPLIFY table."""
    if not s:
        return s
    out = []
    i = 0
    n = len(s)
    while i < n:
        # Two-character entries (compound surnames) first, then single characters.
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
    """Return the characters spelled by the key's hex codepoints ('Cheng_8AA0' -> the
    character 8AA0 denotes), or the key unchanged when it has no codepoints or spells
    no Chinese."""
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
    """Name key -> Chinese display name: localization table, then codepoint decode,
    then the key unchanged."""
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
    """Character object's first_name key -> Chinese given name."""
    fn = (char_obj or {}).get("first_name") or ""
    return zh(loc_name(fn))


def _dynn_lookup(table, name):
    """'abbasid' -> 'dynn_Abbasid' localization key -> name (case-insensitive).
    CK3 family name keys look like dynn_<Name> (dynn_Abbasid/dynn_Tulunid)."""
    if not name:
        return ""
    global _DYNN_INDEX
    if _DYNN_INDEX is None:
        _DYNN_INDEX = {k.lower(): v for k, v in table.items()
                       if k.startswith("dynn_")}
    return _DYNN_INDEX.get("dynn_" + str(name).lower()) or ""


_DYNN_INDEX = None


# ---------------------------------------------------------------------------
# Dynasty/house definition-table parsing (the save stores only a key)
# ---------------------------------------------------------------------------

def _dynasty_name_of_dynn(nm, table):
    """dynn_X key -> Chinese, localization table first, then key codepoints.
    Same chain as house_name_zh: a table value wins over in-key codepoints."""
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
    """Dynasty key (japanese_fujiwara) -> Chinese dynasty name via the game
    definition table; '' when unknown."""
    if not key:
        return ""
    nm = (localization.dynasty_table().get("dynasties") or {}).get(str(key)) or ""
    return _dynasty_name_of_dynn(nm, localization.table())


def house_name_of_key(key):
    """House key (house_fujiwara_kajuji) -> Chinese house name via the game
    definition table; '' when unknown."""
    if not key:
        return ""
    nm = (localization.dynasty_table().get("houses") or {}).get(str(key)) or ""
    return _dynasty_name_of_dynn(nm, localization.table())


# ---------------------------------------------------------------------------
# Nobility place-name prefixes (Italian di, French de, German von...)
# ---------------------------------------------------------------------------
# The game writes them as prefix = "dynnp_X" in common/dynasty_houses|dynasties/*.txt with
# the wording under localization/, and the save's dynasty_house[].prefix wins.

_PREFIX_ZH_CACHE = {}


def _prefix_zh(pkey, table=None):
    """dynnp_X -> Chinese prefix; '' when missing, a placeholder or untranslated.
    Trailing layout spaces are trimmed."""
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
    """Prefix key from the house/dynasty definition table; kind is "house" or
    "dynasty"; '' when unknown."""
    if not key:
        return ""
    tb = localization.dynasty_table()
    bucket = "house_prefixes" if kind == "house" else "dynasty_prefixes"
    return (tb.get(bucket) or {}).get(str(key)) or ""


def house_prefix_zh(melt, house_id):
    """House id -> Chinese prefix: the saved dynasty_house[].prefix first, then the
    game definition table; '' for houses without a prefix."""
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
    """Dynasty id -> Chinese prefix: the saved dynasties[].prefix first, then the
    game definition table."""
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
    """House id -> Chinese surname, trying in order:
      1) dynasty_house[<id>].localized_name carried by the save
      2) the game house definition table (house key -> dynn_Y -> localization)
      3) the localization table (a table value beats in-key codepoints, because a
         hand-made key such as dynn_Dou_9B26 can spell a wrong character)
      4) codepoint decoding of .name when the table lacks the key
      5) the .key field as dynn_<Key> (house_abbasid -> dynn_Abbasid)
    '' when every step fails."""
    if house_id is None:
        return ""
    try:
        dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
        e = dh.get(str(house_id)) or {}
        loc_name = e.get("localized_name") or ""
        if loc_name and any("\u3400" <= ch <= "\u9fff" for ch in loc_name):
            return zh(loc_name)
        hkey = e.get("key")
        if isinstance(hkey, str):
            v = house_name_of_key(hkey)
            if v:
                return v
        name = e.get("name") or ""
        t = localization.table()
        for cand in (name, name[len("dynn_"):] if name.startswith("dynn_") else name):
            v = localization.loc(t, cand)
            if v and v != cand:
                return v
        if name.startswith("dynn_"):
            dec = zh(decode_codepoints(name[len("dynn_"):]))
            if dec and any("\u3400" <= ch <= "\u9fff" for ch in dec):
                return dec
        if isinstance(hkey, str) and hkey.startswith("house_"):
            v = _dynn_lookup(t, hkey[len("house_"):])
            if v:
                return v
        return ""
    except Exception:
        return ""


def house_found_date(melt, house_id):
    """House id -> dynasty_house[<id>].found_date; '' when absent.

    Yearly diffing only sees a new house in the following snapshot, while the
    saved found_date is the authoritative day, so the house timeline uses it."""
    if house_id is None:
        return ""
    try:
        dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
        return (dh.get(str(house_id)) or {}).get("found_date") or ""
    except Exception:
        return ""


def dynasty_id_of(melt, house_id):
    """House id -> owning dynasty id (dynasty_house[<id>].dynasty); None when absent."""
    if house_id is None:
        return None
    try:
        dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
        return dh.get(str(house_id), {}).get("dynasty")
    except Exception:
        return None


# Per-melt memo slot for the dynasty/house name lookup chains: thread-local and
# single-slot, so it is dropped as soon as the melt changes (see _dyn_caches).
_TL = threading.local()


def dynasty_name_zh(melt, dynasty_id):
    """Dynasty id -> Chinese dynasty name, trying in order:
      1) dynasties[<id>].localized_name (carried by the save)
      2) the game dynasty definition table (key -> dynn_X -> localization; the
         save stores only the key, the display name is in common/dynasties/*.txt)
      3) .name -> localization table
      4) .key -> localization table (dynn_<key> / <key>)
      5) the earliest-founded house of the dynasty
    '' when every step fails, so callers fall back to the house name.

    Step 5 scans the whole dynasty_house table, and this function runs tens of
    thousands of times per snapshot, so both the dynasty -> earliest-house index
    and the per-id results are memoized per melt in a thread-local single slot
    (see _dyn_caches)."""
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
        ln = e.get("localized_name") or ""
        if ln and any("\u3400" <= ch <= "\u9fff" for ch in ln):
            val = zh(ln)
        else:
            t = localization.table()
            key = e.get("key")
            if isinstance(key, str):
                val = dynasty_name_of_key(key)
            if not val:
                name = e.get("name") or ""
                if isinstance(name, str):
                    val = _dynasty_name_of_dynn(name, t)
            if not val and isinstance(key, str):
                for cand in ("dynn_" + key, key):
                    v = localization.loc(t, cand)
                    if v and v != cand:
                        val = v
                        break
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
    """This thread's (melt, dynasty -> earliest house index, dynasty -> name memo).

    Single slot keyed on the melt object's identity, so a new melt rebuilds it.
    Thread-local, so the pipeline's background biography thread and the main
    thread keep separate state."""
    c = getattr(_TL, "dyn", None)
    if c is None or c[0] is not melt:
        c = [melt, None, {}]
        _TL.dyn = c
    return c


def clear_dyn_caches():
    """Drop this thread's cached melt reference (called when switching snapshots)."""
    _TL.dyn = None


def _earliest_house_index(melt, c):
    """{dynasty id: id of that dynasty's earliest-founded house}; built once per melt."""
    if c[1] is None:
        dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
        best = {}
        for hid, h in dh.items():
            if not isinstance(h, dict):     # guard against a "none" entry
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
# Loading
# ---------------------------------------------------------------------------

def _sanitize_none(o):
    """Recursively replace the Clausewitz empty-value string 'none' with None.

    rakaly renders `= none` as the string 'none', which defeats the `x or {}` guards
    ('none' is truthy) and makes the next .get() crash. The cleanup is folded into
    _merge_dup_pairs' pass now; this function stays for external scripts."""
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
    """Replace the string 'none' with None inside a list, recursing into nested lists."""
    for i, v in enumerate(lst):
        t = type(v)
        if t is str:
            if v == "none":
                lst[i] = None
        elif t is list:
            _clean_none_list(v)


# ---------------------------------------------------------------------------
# Duplicate character-block repair (CK3 1.20 saves)
# ---------------------------------------------------------------------------
# 1.20 writes every dead_unprunable block twice, which rakaly copies verbatim into JSON.
# _merge_dup_pairs turns such a character object into [obj, obj] (some keys need list
# semantics) while 20+ call sites expect a dict, so these values are collapsed here.
_CHAR_BUCKETS = ("living", "dead_unprunable")


def _char_buckets(melt):
    """(name, bucket) pairs for living, dead_unprunable and characters.dead_prunable."""
    out = []
    for name in _CHAR_BUCKETS:
        b = (melt or {}).get(name)
        if type(b) is dict:
            out.append((name, b))
    b = ((melt or {}).get("characters") or {}).get("dead_prunable")
    if type(b) is dict:
        out.append(("characters.dead_prunable", b))
    return out


def _collapse_char_value(v):
    """One value in a character bucket: a duplicate-key list -> a single dict.

    Identical copies keep the first; differing copies are shallow-merged, later copies
    only filling empty values (None / '' / [] / {}); other shapes are returned as-is."""
    if type(v) is not list:
        return v
    parts = [p for p in v if type(p) is dict]
    if not parts or len(parts) != len(v):
        return v          # unexpected shape (non-dict element): keep for the caller
    first = parts[0]
    if all(p == first for p in parts[1:]):
        return first
    out = dict(first)
    for p in parts[1:]:
        for k, val in p.items():
            cur = out.get(k)
            if cur is None or cur == "" or cur == [] or cur == {}:
                out[k] = val
    return out


def _collapse_char_buckets(melt):
    """Collapse duplicate-key lists back to dicts in the three buckets; returns how many."""
    n = 0
    for _name, bucket in _char_buckets(melt):
        c = 0
        for k, v in bucket.items():
            nv = _collapse_char_value(v)
            if nv is not v:
                bucket[k] = nv
                c += 1
        n += c
    if n:
        llm.log(f"角色桶校正: 并回 {n} 个重复块 (1.20 存档同键双写)", detail=True)
    return n


def _as_char(v):
    """Character entry -> dict; an unexpected shape gives {} so callers lose one
    fact instead of failing the whole snapshot."""
    return v if type(v) is dict else {}


def _merge_dup_pairs(pairs):
    """json object_pairs_hook: merge duplicate keys and clean empty values in one pass.

    Clausewitz/rakaly renders the same key several times (agent_slots, family_data.spouse,
    temporary_opinion, variables.item ...) and json.load would keep only the last one, so
    duplicates become a list in encounter order while singly-seen keys stay unchanged. The
    fast path relies on a C-level dict(pairs) plus a key-count check, since only a couple
    of percent of objects really have duplicates. The same pass replaces the value 'none'
    with None (which the `x or {}` guards rely on); lists of dicts are covered by
    _clean_none_list."""
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
    """Open a melt/sidecar file as text, accepting .json, .json.gz and .json.xz; callers
    that want a dict use the faster binary readers below."""
    low = str(path).lower()
    if low.endswith(".xz"):
        return lzma.open(path, "rt", encoding="utf-8")
    if low.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, encoding="utf-8")


def _melt_binary(path):
    """Binary handle for a melt/sidecar (.json / .json.gz / .json.xz all accepted)."""
    low = str(path).lower()
    if low.endswith(".xz"):
        return lzma.open(path, "rb")
    if low.endswith(".gz"):
        return gzip.open(path, "rb")
    return open(path, "rb")


def _read_melt_bytes(path):
    """Read a whole melt/sidecar as bytes, so the C parser handles UTF-8 itself."""
    with _melt_binary(path) as fp:
        return fp.read()


def melt_file_exists(path):
    """Return the melt file that exists for a base path (plain, then .gz, then .xz)."""
    for cand in (str(path), str(path) + ".gz", str(path) + ".xz"):
        if os.path.isfile(cand):
            return cand
    return None


def load_melt_section(path, key):
    """Return the top-level `key` object of a melt by streaming only that section.

    A full load_melt() costs 1-3 minutes on a 100-125 MB melt while the section starts a
    few MB into the stream, so streaming is two orders of magnitude faster. The matched
    bytes still go through json.loads with the same object_pairs_hook=_merge_dup_pairs as
    load_melt, making the result key-for-key identical to load_melt(path)[key]; braces are
    matched with JSON string and escape rules. A same-named key is not always a section --
    character blocks also hold array fields such as "wars": [1,1,0,0] -- so candidates are
    checked and non-object values skipped. Returns None when no object section is found."""
    pat = ('"%s":' % key).encode("utf-8")
    buf = b""
    eof = False
    with _melt_binary(path) as fp:

        def _fill():
            nonlocal buf, eof
            chunk = fp.read(1 << 20)
            if not chunk:
                eof = True
                return False
            buf += chunk
            return True

        pos = 0                       # search start in buf, past rejected candidates
        while True:
            i = buf.find(pat, pos)
            if i < 0:
                if _fill():
                    continue
                return None
            j = i + len(pat)
            # Skip whitespace to inspect the value's first character
            while True:
                k = j
                while k < len(buf) and buf[k:k + 1] in (b" ", b"\r", b"\n", b"\t"):
                    k += 1
                if k < len(buf):
                    break
                if not _fill():
                    return None
            if buf[k:k + 1] != b"{":
                pos = i + 1           # same name but an array/scalar: try the next candidate
                continue
            start, depth, i = k, 0, k
            while True:
                while i >= len(buf):
                    if not _fill():
                        return None
                c = buf[i:i + 1]
                if c == b'"':
                    i += 1
                    while True:
                        while i >= len(buf):
                            if not _fill():
                                return None
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
    """Melt -> the landed_titles.landed_titles section (same shape as _db(melt)
    titles); {} when the section is missing."""
    sect = load_melt_section(path, "landed_titles")
    if not isinstance(sect, dict):
        return {}
    return sect.get("landed_titles") or {}


def melt_stem(path):
    """Strip the compression suffix from a melt/sidecar path (x.json.xz -> x.json)."""
    p = str(path)
    low = p.lower()
    for suf in (".xz", ".gz"):
        if low.endswith(suf):
            return p[:-len(suf)]
    return p


# ---------------------------------------------------------------------------
# In-process melt memo
# ---------------------------------------------------------------------------
# One process loads the same melt repeatedly (per article, per final biography, after watch
# moves a merged melt); the cap of 2 matches one large melt's ~1.3 GB working set.
# ROMAN_MELT_MEMO=0 disables it.
_MELT_MEMO = OrderedDict()          # key -> (size, mtime_ns, dict)
_MELT_MEMO_MAX = 2
_MELT_MEMO_ON = os.environ.get("ROMAN_MELT_MEMO", "1").lower() not in ("0", "false", "no")
_MELT_MEMO_LOCK = threading.Lock()


def set_melt_memo(enabled):
    """Enable or disable the melt memo (disabling clears it); returns the new state."""
    global _MELT_MEMO_ON
    _MELT_MEMO_ON = bool(enabled)
    if not _MELT_MEMO_ON:
        melt_memo_clear()
    return _MELT_MEMO_ON


def melt_memo_clear():
    """Clear the melt memo; returns how many entries were dropped."""
    with _MELT_MEMO_LOCK:
        n = len(_MELT_MEMO)
        _MELT_MEMO.clear()
    return n


def melt_memo_stats():
    """(enabled, number of cached melts, cap)."""
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
    """Follow a memo key to a melt's new path after a rename or move.

    Call it *before* os.replace, while the source still exists and its size/mtime can be
    read; returns whether the entry was moved."""
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
    """Drop the memo entry for a path (its key is unreachable once archived)."""
    if not _MELT_MEMO_ON:
        return False
    key = _melt_memo_key(path)
    if key is None:
        return False
    with _MELT_MEMO_LOCK:
        return _MELT_MEMO.pop(key, None) is not None


def load_melt(path, use_memo=True):
    """Read a melt file into a dict; duplicate-key merging and 'none' -> None happen
    inside _merge_dup_pairs.

    Automatic GC is off while parsing, because with a Python object_pairs_hook the C
    scanner calls back once per object and would trigger repeated gen0/1/2 passes over
    tens of millions of nodes, while a pure C parse pays once at the end. The interpreter
    state is restored on return, and JSON has no cycles, so nothing leaks.

    With use_memo the in-process memo is consulted and the same read-only dict is shared
    (see _MELT_MEMO)."""
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
        _collapse_char_buckets(data)   # 1.20 duplicate character blocks -> one dict
    finally:
        if gc_was_on:
            gc.enable()
    if key is not None:
        _melt_memo_put(key, data)
    return data


def _db(melt):
    """Memory database: {memory id (str): {type, participants, creation_date, ...}}"""
    return melt.get("character_memory_manager", {}).get("database") or {}


def _living(melt):
    return melt.get("living") or {}


def _dead_unprunable(melt):
    return melt.get("dead_unprunable") or {}


def _dead_prunable(melt):
    return (melt.get("characters") or {}).get("dead_prunable") or {}


# ---------------------------------------------------------------------------
# Faith / rite accessors (CK3 1.20 moved the faith and rite databases)
# ---------------------------------------------------------------------------
# Before 1.20, faiths live in religion.faiths[<fid>] with a faith id on each character; in
# 1.20 they sit at faiths.database[<fid>] and rites at rites.database[<rid>], with
# characters carrying only rite, so the faith is found via rites.database[rite].faith.
# Display names are already localized in the save, and faith.religious_head is empty in
# 1.20 because a head is recorded in rites.database[rite].head_of_rite.

def faith_entry(melt, fid):
    """Faith definition dict: 1.20 faiths.database, older saves religion.faiths;
    {} when absent."""
    if fid is None:
        return {}
    e = (((melt or {}).get("faiths") or {}).get("database") or {}).get(str(fid))
    if type(e) is dict:
        return e
    e = (((melt or {}).get("religion") or {}).get("faiths") or {}).get(str(fid))
    return e if type(e) is dict else {}


def faith_name_of(melt, fid):
    """Faith display name from the save's own name field (1.20); '' for older saves."""
    return str(faith_entry(melt, fid).get("name") or "")


def rite_entry(melt, rid):
    """Rite definition dict from rites.database (1.20); {} when absent."""
    if rid is None:
        return {}
    e = (((melt or {}).get("rites") or {}).get("database") or {}).get(str(rid))
    return e if type(e) is dict else {}


def rite_data(melt, rid):
    """Rite display block (rites.database[<rid>].data): name/adjective/desc/fervor/tenets..."""
    d = rite_entry(melt, rid).get("data")
    return d if type(d) is dict else {}


def rite_name_of(melt, rid):
    """Rite display name (already localized in the save); '' when absent."""
    d = rite_data(melt, rid)
    return str(d.get("name") or d.get("adjective") or "")


def faith_id_of_rite(melt, rid):
    """id of the faith a rite belongs to (the authoritative faith source in 1.20)."""
    f = rite_entry(melt, rid).get("faith")
    return f if isinstance(f, int) else None


def rite_id_of_char(char_obj):
    """Character's rite id (the 1.20 rite field); None for older saves."""
    r = _as_char(char_obj).get("rite")
    return r if isinstance(r, int) else None


def faith_id_of_char(melt, char_obj):
    """Character's faith id: the faith field in older saves, else via the rite;
    None when neither yields one."""
    c = _as_char(char_obj)
    f = c.get("faith")
    if isinstance(f, int):
        return f
    return faith_id_of_rite(melt, rite_id_of_char(c))


def head_of_rite(melt, rid):
    """Head of the rite, where 1.20 records a religious head: character id, or None
    for the empty value 4294967295."""
    h = rite_entry(melt, rid).get("head_of_rite")
    if isinstance(h, int) and h != 4294967295:
        return h
    return None


def all_characters(melt):
    """Every character in the save (living + dead_unprunable + dead_prunable).

    Each entry goes through _collapse_char_value and _as_char so callers always get
    a dict, even where the 1.20 duplicate-key doubling (see _collapse_char_buckets)
    appears again."""
    out = {}
    for _name, bucket in _char_buckets(melt):
        for k, v in bucket.items():
            out[k] = _as_char(_collapse_char_value(v))
    return out


def mem_ids_of(char_obj):
    """Character's alive_data.memories id list, falling back to dead_data.memories.

    A character who was once playable (was_playable) keeps a copy of the memories
    in dead_data.memories after dying, which is why the fallback exists."""
    c = _as_char(char_obj)
    ids = (c.get("alive_data") or {}).get("memories") or []
    if ids:
        return ids
    return (c.get("dead_data") or {}).get("memories") or []


def nickname_at(rec, as_of=None):
    """The character's nickname at as_of, from the nickname_history change points.

    '' means no nickname at that date; None means no history, or a date before the
    first point (callers fall back to the melt). An empty as_of returns the last
    value, i.e. the current nickname."""
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
    fd = (_as_char(char_obj)).get("family_data") or {}
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
    """Character's kill ids: alive_data.kills while alive, dead_data.kills after death."""
    c = char_obj or {}
    out = list((c.get("alive_data") or {}).get("kills") or [])
    out += list((c.get("dead_data") or {}).get("kills") or [])
    return [int(x) for x in out if isinstance(x, int) or str(x).isdigit()]


def date_key(s):
    """'869.2.22' -> (869, 2, 22); invalid input -> (9999, 0, 0)."""
    try:
        return tuple(int(x) for x in str(s).split("."))
    except Exception:
        return (9999, 0, 0)


def date_filekey(s):
    """'869.2.22' -> '869_02_22' (matches melt file naming)."""
    return "_".join(f"{int(x):02d}" for x in str(s).split("."))


# ---------------------------------------------------------------------------
# Memory entries
# ---------------------------------------------------------------------------

def memory_brief(mem_id, e):
    """Memory object -> compact entry with its id.

    vars keep {flag,type,identity} so related objects resolve, and a var of type "flag"
    also stores its value from data.flag (e.g. the castration markers)."""
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
# Cache library (schema 5: one cache file per player)
# ---------------------------------------------------------------------------

EMPTY_CACHE = {
    "schema": 5,
    "player_id": None,
    "player_name": None,
    "house_name": None,       # house name (bare, no prefix), used when building the display name
    "dynasty_id": None,       # dynasty id (output folders are grouped by dynasty)
    "dynasty_name": None,     # dynasty name (bare), basis of the output folder name
    "playthrough_id": None,   # playthrough id from the save; one playthrough's saves share it
    "game_version": None,
    "sources": [],
    "last_date": None,
    "player_death": None,     # written when the player's dead_data first appears: {date, reason, killer, kills}
    # Reign ended without death: {date, kind, alive, successor, successor_name,
    # successor_title, evidence} from pipeline._cross_check_lineage; outranks player_death
    "reign_end": None,
    "bio_generated": False,   # whether the final biography is written (once per player death)
    "bio_decades": [],        # decades of the generated ten-year biographies [1,2,...], one per 10 years lived
    "output_folder": None,    # session output folder name, bound by watch/continue (see pipeline)
    "player_title_history": [],  # [{date, name}] changes of the player's primary title name
    "realm_history": [],         # [{date, holders:{title_id: holder_id}}] holders of key titles, year by year
    # Wars of the player, latched per snapshot: war_memory_cb_* covers only part of the 126
    # casus belli, the real CB is only in wars.active_wars[].casus_belli.type, and a war
    # leaves the save when it ends.
    "war_history": [],           # [{id, seen, start_date, cb, attacker, defender, claimant, titles, atk_parts, dfd_parts, name}]
    # Dynamic title names {tid: [{from, name}]}: specific_title_name is a present-day
    # value that only that date's snapshot carries (read by facts._dyn_name_at/_site_name).
    "title_dyn_names": {},
    "court_positions": [],       # [{date, positions:[{type, employee, hire_date, task}]}] the player's court staff, year by year (employer == player, not the player's own office)
    "court_office_history": [],  # [{date, offices:[{type, employer, hire_date}]}] court positions granted TO the protagonist, year by year (employee == player, employer == someone else)
    "house_motto": None,         # player house motto (dynasty_house.motto, a string or a template dict)
    "characters": {},
    "relations": {},
    # Rebel faction leaders for titles; the save holds only current factions, with no dates
    "factions": {},
    # Hooks diffed per snapshot (active_hook_*), kept when the player is holder or target
    "hooks": {},
    # Concubinage opinions diffed per snapshot: forced_me_concubine_marriage_opinion is the
    # only dated record of "taken by raid -> forced concubine"
    "opinions": {},
    # Slave relations diffed per snapshot (scripted_relations.slave): carn_enslave_effect
    # sets release_from_prison = yes at the moment of enslavement, so the save's "released"
    # memory IS that step, and recording all masters traces a resale.
    # key = "<master id>><slave id>".
    "enslavements": {},
    # Carnalitas relation opinions diffed per snapshot (rape, enslavement, prostitution,
    # former slave/owner), which carry start_date and cover memoryless interactions.
    # key = "<holder id>><target id>><modifier>".
    "carnal_opinions": {},
    # Character modifier carn_recently_raped (5 years) diffed per snapshot: the only dated
    # signal on the victim's side (key = "<character id>>carn_recently_raped")
    "carnal_modifiers": {},
    # Matrilineal (uxorilocal) marriage pairs from active_relations
    # {"first":A,"second":B,"matrilineal":true}: children belong to the mother's house, and
    # the entry vanishes when the marriage ends, so it is latched once seen forever.
    "matrilineal_pairs": {},
    # Feud/friendship causes latched during the merge (first sighting wins), since the game
    # keeps scripted_relations.<kind>.reason only while the relation exists.
    # key = "<owner>|<target>|<kind>".
    "relation_reasons": {},
    # Spouse latch: the subject's own family_data is cleared in the death snapshot while the
    # reverse pointer on the other side remains. key = "<subject id>><other id>".
    "spouse_latch": {},
    # Prisoner hand-over latch: {"<prisoner id>": {"from","to","since","first_seen"}}, since
    # the successor's snapshots no longer report the subject as find_player.
    "prison_succession": {},
    # Release-reason latch: {"<prisoner>><jailer>><date>": {"kind","src","first_seen"}} from
    # release opinions (which carry start_date) and favor_hook / indebted_hook (creation =
    # expiry minus 10 calendar years), since such opinions decay within a decade.
    "prison_manners": {},
    # Player succession chain from played_character.legacy: [{cid, date}], the last entry
    # being the current subject with its accession day; kinship cannot reconstruct it.
    "played_legacy": [],
    # Vassal contract change points {cid: [{date, liege, flags}]}
    "char_vassal_history": {},
    # Mandate-of-Heaven cycle phase change points [{date, phase, start}]
    "dynastic_cycle_history": [],
}


def new_cache():
    """A brand-new empty cache (deep copy, so the containers are not shared)."""
    return copy.deepcopy(EMPTY_CACHE)


def cache_path_for(cache_dir, player_id):
    return os.path.join(cache_dir, f"player_{player_id}.json")


# Per-path write mutex: the main thread's merge and the background biography thread can
# write the same cache file at once, and a shared fixed .tmp name would truncate it.
_SAVE_LOCKS = {}
_SAVE_LOCKS_GUARD = threading.Lock()


def _save_lock(path):
    with _SAVE_LOCKS_GUARD:
        lock = _SAVE_LOCKS.get(path)
        if lock is None:
            lock = threading.Lock()
            _SAVE_LOCKS[path] = lock
        return lock


# Cache-file mtime memo: without it every watch poll re-reads all player caches
# (several files of 60-160 MB of JSON).
_CACHE_LOAD_MEMO = {}   # path -> (mtime, cache_dict)


def load_cache(path, fresh=False):
    """Read a player cache (mtime-memoized); fresh=True forces a re-read.

    The returned dict may be modified by the caller, so any path that writes back
    passes fresh=True to get its own copy."""
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
        # older schemas: fill in the fields they lack
        for k, v in EMPTY_CACHE.items():
            cache.setdefault(k, v)
        if not fresh:
            try:
                _CACHE_LOAD_MEMO[path] = (os.path.getmtime(path), cache)
            except OSError:
                pass
        return cache
    except Exception as e:
        # Corrupt cache file: rename it aside and warn, since treating it as empty is
        # worse (an empty cache joins session selection with seq=0 and would merge this
        # session's data into an older folder).
        try:
            corrupt = f"{path}.corrupt.{time.strftime('%Y%m%d_%H%M%S')}"
            os.replace(path, corrupt)
            llm.log(f"[缓存损坏] {path} 解析失败 ({e}) — 已改名 {os.path.basename(corrupt)} "
                    f"留证, 返回空缓存 (请用 rebuild-cache 重建)")
        except Exception:
            llm.log(f"[缓存损坏] {path} 解析失败 ({e}) — 改名失败, 返回空缓存")
    return new_cache()


def save_cache(cache, path):
    """Write a player cache atomically, with compact separators (readers all use
    json.load and do not depend on indentation)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _save_lock(path):
        tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(cache, fp, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)  # atomic replace, prevents torn concurrent reads


def char_record(cache, cid):
    key = str(cid)
    if key not in cache["characters"]:
        cache["characters"][key] = {
            "id": cid,
            "first_name": None,
            "name_zh": None,
            "house_name": None,     # house name; the surname in Western name order
            "dynasty_name": None,   # dynasty name; the surname in Eastern name order
            "name_full": None,      # surname + given name
            "birth": None,
            "death": None,
            "female": False,       # sex: the melt's female field appears only on women
            "dynasty_house": None,
            # [{from, house_id, house_name, dynasty_id, dynasty_name}] house change points;
            # a founding or rename shows up only here, since the game keeps no memory of it.
            "house_history": [],
            "culture": None,
            "culture_history": [],  # [{from, culture}] culture change points (first sighting wins)
            "faith": None,
            "faith_history": [],   # [{from, faith}] conversion change points (first sighting wins)
            # [{from, nickname}] nickname change points (an empty string means none); reading
            # an era's nickname would otherwise need that era's whole melt file.
            "nickname_history": [],
            "traits": [],
            "trait_history": {},    # {trait key: [{from, to, first}]} gained/lost intervals
            "trait_xp": [],         # [{from, traits, xp}] trait-track XP samples (aligned with traits)
            "family": {},           # related-character ids, plus ever_spouses (all spouses in history)
            "court": {},            # {employer, knight, join_court_date} court affiliation
            "landed": {},
            "memories": [],
            "kills": [],        # kill ids (alive_data.kills ∪ dead_data.kills, accumulated across years)
            # Imprisonment intervals [{from, to, imprisoner, type, since}]: a null "to" means
            # still imprisoned, which resolves a missing release memory.
            "prison_history": [],
        }
    return cache["characters"][key]


# ---------------------------------------------------------------------------
# Name resolution
# ---------------------------------------------------------------------------

_NAMES = None
_NAMES_META = {}


def _load_names(names_path, melt=None):
    """Whole-save name table {character id: {name_zh, house_name, dynasty_name}}.

    Character ids are meaningful only inside one save/playthrough, and the table is a
    snapshot of the melt build_names last ran on (payload.source), so the table comes back
    empty when its playthrough_id differs from the melt's."""
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
    """Character id -> full Chinese name, delegating to display_name; kept for existing
    callers such as summarize_relations."""
    return display_name(cache, cid, melt=melt, names_path=names_path)


# ---------------------------------------------------------------------------
# Cultural name order (Eastern surname first, Western given name first)
# ---------------------------------------------------------------------------

EASTERN_NAME_ORDERS = {"DYNASTY_ALWAYS_FIRST", "JAPANESE"}


def name_order_of(melt, culture_id):
    """Culture id -> name_order_convention ('' = Western default;
    DYNASTY_ALWAYS_FIRST / JAPANESE = surname first); '' when unknown."""
    if melt is None or culture_id is None:
        return ""
    cultures = (melt.get("culture_manager") or {}).get("cultures") or {}
    e = cultures.get(str(culture_id)) or {}
    return e.get("name_order_convention") or ""


# Two-stage key order for inferring name order from relatives: the paternal side first
# (the naming culture is inherited through the father, and child is deliberately absent
# because a woman's children carry their father's culture), then the maternal side only if
# the paternal side and the dynasty template both fail.
KIN_ORDER_PATERNAL = ("father", "siblings")
KIN_ORDER_MATERNAL = ("mother", "child", "primary_spouse", "spouse",
                      "former_spouses")


def _family_name_order(cache, rec, melt, chars=None, keys=KIN_ORDER_PATERNAL):
    """Infer the name order from relatives' cultures when the character's own culture is
    missing (cleared at death, not yet recorded, or never set by the game).

    keys defaults to the paternal side only; resolved_name_order asks the maternal side,
    spouses and children later, after the dynasty template. Returns a
    name_order_convention string, or None when none of those relatives has a culture.
    chars is the full-character index held by display_name."""
    if melt is None:
        return None
    cultures = (melt.get("culture_manager") or {}).get("cultures") or {}
    fam = rec.get("family") or {}
    for key in keys:
        for x in (fam.get(key) or []):
            r = (cache.get("characters") or {}).get(str(x)) or {}
            cul = r.get("culture")
            if (cul is None or str(cul) not in cultures) and chars is not None:
                cul = (chars.get(str(x)) or {}).get("culture")
            if cul is None or str(cul) not in cultures:
                continue
            return cultures[str(cul)].get("name_order_convention") or ""
    return None


def resolved_name_order(cache, cid, melt=None, chars=None, memo=None, date=None):
    """Resolve a character's name order (the single chain shared by display_name and
    Facts.name_order).

    Every step asks only whether a culture resolves, never whether the result is Eastern,
    since a Western '' is equally final:

      1) the character's culture at that date (history, then the cached field), giving
         culture_manager's name_order_convention or the Western default;
      2) otherwise the paternal relatives' cultures;
      3) otherwise the dynasty template and the name order of a culture sharing it;
      4) only then the maternal side, spouses and children;
      5) None when nothing resolves, so display_name writes the given name alone.

    Returns '' = Western default, DYNASTY_ALWAYS_FIRST / JAPANESE = surname first, None =
    undecidable."""
    if cid is None:
        return None
    rec = (cache.get("characters") or {}).get(str(cid)) or {}
    cultures = ((melt or {}).get("culture_manager") or {}).get("cultures") or {}
    cul = _culture_id_at_rec(rec, date)
    if cul is None:
        cul = rec.get("culture")
    if cul is not None:
        return (cultures.get(str(cul)) or {}).get("name_order_convention") or ""
    if melt is None:
        return None
    order = _family_name_order(cache, rec, melt, chars=chars,
                               keys=KIN_ORDER_PATERNAL)
    if order is not None:
        return order
    tpl = _culture_template_of(cache, cid, melt, chars=chars, memo=memo)
    if tpl:
        for _e in cultures.values():
            if isinstance(_e, dict) and _e.get("culture_template") == tpl:
                return _e.get("name_order_convention") or ""
    return _family_name_order(cache, rec, melt, chars=chars,
                              keys=KIN_ORDER_MATERNAL)


def name_display(cache, cid, melt=None, names_path=None):
    """Game-rule display name; an alias of display_name kept for compatibility."""
    return display_name(cache, cid, melt=melt, names_path=names_path)


# ---------------------------------------------------------------------------
# Unified name function (same rules as the game) - the single entry point
# ---------------------------------------------------------------------------

_PATRONYM_RULES_CACHE = None


def _patronym_rules_table():
    """Lazily load data/patronym_rules.json (the same file facts reads)."""
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
    """Culture id -> culture_template (norse/han...); '' when unknown."""
    if melt is None or cul is None:
        return ""
    cultures = (melt.get("culture_manager") or {}).get("cultures") or {}
    e = cultures.get(str(cul)) or {}
    return e.get("culture_template") or ""


def _culture_template_of(cache, cid, melt, chars=None, memo=None):
    """A character's culture template (norse/han...), used for patronymics and name order.

    The naming culture follows the paternal line, so every step reads a character's OWN
    culture and only the paternal line recurses; siblings, mother and house members are
    read without recursing, which keeps in-law and step-parent cultures out. Order: own
    culture, paternal line, siblings, house members, mother, language lookup. chars is the
    prebuilt full-character index, memo the cache for this inference run."""
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
        """Culture template from the character's own culture (cache, then melt)."""
        k = str(x)
        r = (cache.get("characters") or {}).get(k) or {}
        t = _template_of_culture(melt, r.get("culture"))
        if t:
            return t
        return _template_of_culture(melt, (chars.get(k) or {}).get("culture"))

    # 1) the character
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

    # 2) paternal line: father -> grandfather -> great-grandfather, each own culture
    cur = cid
    for _ in range(3):
        fs = fathers_of(cur)
        if not fs:
            break
        cur = fs[0]
        t = self_tpl(cur)
        if t:
            return t
    # 3) siblings, own culture only and no recursion (keeps in-law cultures out)
    for sib in fam_of(cid, ("siblings",)):
        t = self_tpl(sib)
        if t:
            return t
    # 4) house members: the most reliable paternal fallback, ahead of the mother
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
            # Nothing in the cache: widen to every melt character of the same house,
            # building the index lazily inside the shared memo. This resolves name order
            # for characters whose own and relatives' cultures were all cleared.
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
    # 5) mother
    for m in fam_of(cid, ("mother",)):
        t = self_tpl(m)
        if t:
            return t
    # 6) language lookup, the last step when the kinship chain is empty
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
            # Cultures can share one language: prefer the template with patronymic rules
            # (language_norse -> norse, not norman), matching facts.culture_template.
            if tpl in rules:
                return tpl
            fallback = fallback or tpl
        if fallback:
            return fallback
    return ""


def _father_name_of(cache, cid, melt, names_path, chars=None):
    """The father's given name, for patronymic composition: cache, then melt, then names.json."""
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
        # the melt character wins over the cross-playthrough names.json
        fc = (chars if chars is not None else all_characters(melt)).get(str(fid)) or {}
        fn = name_zh(fc) if fc else ""
    if not fn and names_path:
        fn = (_load_names(names_path, melt).get(str(fid)) or {}).get("name_zh") or ""
    return fn


def _patronym_of(cache, cid, melt, names_path, chars=None, memo=None):
    """Patronymic middle name: prefix + father's name + suffix for patronymic cultures
    (a distinct form for sons and for daughters); the culture template comes from the
    kinship chain."""
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
    """(house name, dynasty name) for a date, from rec["house_history"].

    Without history or a date the melt's current values win, since the cached names are
    frozen at first sighting and go stale on a rename."""
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
    """The character's culture id at a date, from the culture change points; None without
    a history or a date. Name order follows the culture, so reading only the last
    snapshot's culture would order every earlier event by the wrong convention."""
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
                 date=None, ignore_regnal=False):
    """The game-rule display name used project-wide.

    A patronymic culture gives "given·patronymic", which replaces the house name;
    otherwise the name order applies, where an Eastern order takes the DYNASTY name as
    surname (the game's $DYNASTY$ template) and a Western order the HOUSE name
    ($HOUSE$). Inference runs along paternal line, siblings, house, mother and language,
    and when it fails only the given name is returned, never a wrongly ordered
    "surname+given".

    Name lookup chain: cache, then the melt character, then names.json (dropped when the
    playthrough differs). date selects the house name of that day and, through the culture
    at that date, which surname is used. chars is the prebuilt full-character index, memo
    the inference cache shared across one build_facts run.

    ignore_regnal=True skips the regnal-name substitution so the BIRTH name is assembled
    with its surname (a pope's "思忠" becomes "洪思忠"): the note beside a regnal name has
    to keep the clan surname, or the biographee looks unrelated to his own house. The
    ordinary call keeps the game's own display rule (the regnal name alone)."""
    if cid is None:
        return ""
    key = str(cid)
    rec = (cache.get("characters") or {}).get(key) or {}
    nm = rec.get("name_zh") or ""
    h = rec.get("house_name") or ""
    dn = rec.get("dynasty_name") or ""
    h, dn = _house_names_at(rec, melt, date, h, dn, memo=memo)
    # The melt character wins over names.json: that table is indexed by character id
    # and may come from another playthrough, where the same id is a different person.
    if not nm:
        c = (chars or {}).get(key) or {}
        if c:
            nm = name_zh(c)
            hid = c.get("dynasty_house")
            if hid is not None:
                # fill in house and dynasty names from the same melt
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
    # A regnal name (papal or monastic) replaces the personal name and drops surname and
    # patronymic, as the game shows it; a key with no wording falls back to the personal name.
    # ignore_regnal keeps the birth name and therefore the surname (see the docstring).
    _rn = rec.get("regnal_name")
    if not _rn:
        _rn = ((chars or {}).get(key) or {}).get("regnal_name")
    if _rn and not ignore_regnal:
        _rz = localization.loc(localization.table(), str(_rn)) or ""
        if _rz and not _rz.startswith("$") and not _rz.startswith("["):
            return _rz
    memo = memo if memo is not None else {}
    # 1) patronymic culture: given·patronymic, written once when it equals the given name
    ptn = _patronym_of(cache, cid, melt, names_path, chars=chars, memo=memo)
    if ptn:
        return nm if ptn == nm else f"{nm}·{ptn}"
    # 2) name order through the single resolved_name_order chain (own culture,
    # paternal side, dynasty template, maternal side), shared with Facts.name_order
    order = resolved_name_order(cache, cid, melt=melt, chars=chars,
                                memo=memo, date=date)
    if order in EASTERN_NAME_ORDERS:
        # Eastern order: the surname is the dynasty name; older caches lacking it resolve
        # it lazily from the melt. A surname equal to the given name is written once. If
        # there is no dynasty name, the house name is used.
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
        # no dynasty name: fall back to the house name
        surname = dn or h
        if surname == nm:
            return nm
        return surname + nm if surname else nm
    # Western order prepends the place-name prefix (Italian di, French de, German von)
    # unless the house name already contains it in its saved localized_name.
    pfx = house_prefix_zh(melt, rec.get("dynasty_house")) if melt is not None else ""
    if pfx and h and (h.startswith(pfx) or h.startswith(pfx.rstrip("·"))):
        pfx = ""

    def _west_surname(surname):
        # a surname identical to the given name is written once
        if surname and surname.strip("·") == nm:
            return nm
        return f"{nm}·{pfx}{surname}" if (surname and pfx) else \
            (f"{nm}·{surname}" if surname else nm)

    if order is not None and order == "":
        # inferred Western default: given·surname
        return _west_surname(h)
    # 3) nothing resolved: the given name alone, rather than a wrong order
    return nm


# ---------------------------------------------------------------------------
# Kinship graph (reverse index)
# ---------------------------------------------------------------------------

def _family_graph(chars):
    """Whole-save characters -> (parent_map, child_map, sibling_map).

    parent_map comes from family_data.child plus the direct father/mother fields,
    child_map from the direct child field plus father/mother back-references, and
    sibling_map from the siblings field (both directions). A child's family_data is
    often empty, so a parent/child link may exist only on the parent's child list."""
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
        if not isinstance(c, dict):  # guard against a "none" entry
            continue
        fd = c.get("family_data") or {}
        for key in ("child", "father", "mother", "siblings"):
            link(int(cid), key, fd.get(key))
    return parent_map, child_map, sibling_map


def _parents_of(chars, cid, parent_map, direct):
    """A character's parents, merging the direct fields with back-references and
    splitting them into father/mother by sex."""
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
    """A character's siblings: the direct field plus those derived from shared parents."""
    out = set(int(x) for x in (direct.get("siblings") or []))
    out.update(sibling_map.get(cid, []))
    for p in parent_map.get(cid, []):
        for s in child_map.get(p, []):
            if s != cid:
                out.add(s)
    return sorted(out)


def _secret_father_candidates(melt):
    """Pre-indexed secret fathers: {target_id: [[candidate father ids...], ...]}.

    The two secret types (secret_unmarried_illegitimate_child /
    secret_disputed_heritage) keep their candidate groups in the original object
    order, with the target itself and the owner already removed, so the return
    semantics match a per-record scan: an empty group is skipped, the first group
    with candidates wins, and a non-female candidate is preferred inside a group.
    real_father_of would otherwise walk every secret for every target character."""
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
        if cands:  # an empty candidate group is skipped, so it is not indexed
            out.setdefault(tgt, []).append(cands)
    return out


def real_father_of(melt, cid, chars=None, sec_candidates=None):
    """A character's real father: the family_data.real_father field, else the secret
    data (secret_unmarried_illegitimate_child / secret_disputed_heritage, whose
    target is the child and whose non-owner male participants are the candidates).

    chars and sec_candidates are prebuilt once by the caller, because
    extract_snapshot calls this for every target character and rebuilding the full
    character dict each time would be quadratic."""
    cid = int(cid)
    if chars is None:
        chars = all_characters(melt)
    c = chars.get(str(cid)) or {}
    fd = c.get("family_data") or {}
    rf = fd.get("real_father")
    if rf is not None:
        return int(rf)
    # From secrets: the non-owner male participants (with the mother as owner, the second
    # participant is the father)
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
# Single-snapshot extraction (per-player cache, name merge, kinship/traits/court)
# ---------------------------------------------------------------------------

# Index order of the celestial_vassal contract group (subject_contract_groups.txt), where
# index 2 = celestial_provinces and each level maps to an obligation tier
_CELESTIAL_PROVINCE_INDEX = 2
_CELESTIAL_PROVINCE_FLAGS = (
    "celestial_province_standard",       # 0 circuit inspector tier
    "celestial_province_industrial",     # 1 circuit inspector tier
    "celestial_province_metropolitan",   # 2 circuit inspector tier
    "celestial_province_military",       # 3 military commissioner tier
    "celestial_province_protectorate",   # 4 protector-general tier
)


def _contract_levels_map(levels):
    """Melt levels [N, {"3": 2}, ...] -> {int index: int value}."""
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
    """One vassal contract -> obligation flags (only celestial_provinces is decoded).

    The melt usually omits the default level, so a missing index 2 means 0
    (celestial_province_standard); any other contract group gives []."""
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
    """This snapshot's vassal contracts -> {vassal_id: {liege, flags}}."""
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
    """Current Mandate-of-Heaven cycle phase {phase, start}; None without a situation.

    Path: the type=dynastic_cycle entry in situation_manager.database, then through
    its sub_region_refs into situation_sub_region_manager.database.<id>.phase."""
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
    """The player's domicile entry: herd and provisions live only in
    domiciles.database and not in landed_data, so the entry is matched by owner_title
    against the player's domain (or by the title's holder being the player). Returns
    a dict or None."""
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


def _war_side_id(side):
    """A war's attacker/defender section -> the leading character id, or None.

    That section is a dict of participants whose first entry leads the side, though a few
    snapshots store a bare id instead."""
    if isinstance(side, int):
        return side
    if isinstance(side, dict):
        for p in (side.get("participants") or []):
            if isinstance(p, dict) and isinstance(p.get("character"), int):
                return p["character"]
    return None


def _war_side_parts(side, cap=32):
    """A war's attacker/defender section -> sorted participant ids (allies included),
    truncated to cap."""
    out = []
    if isinstance(side, dict):
        for p in (side.get("participants") or []):
            if isinstance(p, dict) and isinstance(p.get("character"), int):
                out.append(int(p["character"]))
    elif isinstance(side, int):
        out.append(int(side))
    return sorted(set(out))[:cap]


def _latch_war_history(cache, wars, date_label, player_id=None):
    """Latch the casus belli of the player's wars into cache["war_history"].

    The game writes the war_memory_cb_* memory key for only part of the 126 casus belli
    (a hard-coded whitelist) and uses war_memory_cb_fallback for the rest, whose text is
    just "war" and is discarded (see facts._war_cb_word). The real CB lives only in
    melt["wars"]["active_wars"][<id>].casus_belli.type, and a war leaves active_wars as
    soon as it ends, so it can only be latched while still running.

    Rows are [{id, seen, start_date, cb, attacker, defender, claimant, titles, atk_parts,
    dfd_parts, name}], deduplicated by war id with later snapshots merging in more
    participants, and kept only when either side includes the player.
    attacker/defender/claimant come from casus_belli, since those names in the war section
    are participant dicts; a claimant of 4294967295 is the no-claimant sentinel. name is
    the save's localized war name and is evidence only. Idempotent."""
    if not isinstance(wars, dict) or player_id is None:
        return 0
    aw = wars.get("active_wars") or {}
    if not isinstance(aw, dict) or not aw:
        return 0
    hist = cache.setdefault("war_history", [])
    by_id = {}
    for row in hist:
        if isinstance(row, dict) and row.get("id") is not None:
            by_id[str(row["id"])] = row
    added = 0
    for wid, w in aw.items():
        if not isinstance(w, dict):
            continue
        cb = w.get("casus_belli") if isinstance(w.get("casus_belli"), dict) else {}
        atk_id = cb.get("attacker") if isinstance(cb.get("attacker"), int) \
            else _war_side_id(w.get("attacker"))
        dfd_id = cb.get("defender") if isinstance(cb.get("defender"), int) \
            else _war_side_id(w.get("defender"))
        atk_parts = _war_side_parts(w.get("attacker"))
        dfd_parts = _war_side_parts(w.get("defender"))
        if player_id not in (atk_parts + dfd_parts + [atk_id, dfd_id]):
            continue
        cl_claim = cb.get("claimant")
        if cl_claim in (4294967295, 0):
            cl_claim = None
        row = by_id.get(str(wid))
        if row is None:
            row = {
                "id": str(wid), "seen": date_label,
                "start_date": w.get("start_date"),
                "cb": str(cb.get("type") or ""),
                "attacker": atk_id, "defender": dfd_id,
                "claimant": cl_claim,
                "titles": cb.get("targeted_titles") or None,
                "atk_parts": atk_parts, "dfd_parts": dfd_parts,
                "name": w.get("name"),
            }
            hist.append(row)
            by_id[str(wid)] = row
            added += 1
        else:
            # later snapshot of the same war: leaders and CB are fixed at first
            # sight, so only participants that joined later are merged in
            row["atk_parts"] = sorted(set((row.get("atk_parts") or []) + atk_parts))
            row["dfd_parts"] = sorted(set((row.get("dfd_parts") or []) + dfd_parts))
            if not row.get("cb") and cb.get("type"):
                row["cb"] = str(cb["type"])
    return added


def _latch_title_dyn_names(cache, lt, date_label):
    """Latch dynamic title names per snapshot into cache["title_dyn_names"].

    title_name_data.specific_title_name is a present-day value carried only by the
    snapshot of that date (the game's nomadic/dynasty display name, which follows the
    holder), while the last melt keeps the final version only, so a later rename would be
    applied to earlier events.

    Shape: {tid: [{from, name}]}, appending a point only when the value changes. A name
    DISAPPEARING also gets an empty point, or the old name would stay in force. Only
    dynamic names are recorded; static ones (title_name_data.name) come from the last
    melt."""
    dn = cache.setdefault("title_dyn_names", {})
    dk = date_key(date_label)

    def _push(key, name):
        h = dn.setdefault(key, [])
        if h:
            if date_key(h[-1]["from"]) > dk:
                return          # out-of-order merge: keep the history monotonic
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
    """Record this snapshot's vassal contract change points and Mandate phase.

    Other subjects' melts of the same playthrough also go through here: their early
    contracts exist only in those snapshots, which are skipped wholesale when
    player_id differs, so without this the final biography could not reconstruct that
    period's vassal history."""
    _vassal_now = _vassal_snapshot(melt)
    _phase = dynastic_cycle_phase(melt)
    if _phase:
        _ph = cache.setdefault("dynastic_cycle_history", [])
        if not _ph or _ph[-1].get("phase") != _phase.get("phase"):
            _ph.append({"date": date_label, "phase": _phase.get("phase") or "",
                        "start": _phase.get("start") or date_label})
    _vh_all = cache.setdefault("char_vassal_history", {})
    # Record only this subject, already-cached characters and those with existing
    # vassal history, rather than every celestial vassal.
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
    """Merge one save snapshot into the cache; False when the player does not match.

    _new_deaths: optional list that receives the ids of characters whose death is
    first recorded here, so the caller can backtrack memories for the newly dead
    only instead of rescanning everything.

    Runs inside a window with automatic GC disabled: by the later snapshots the cache
    graph holds tens of millions of nodes and this function creates or rewrites
    hundreds of thousands of objects per snapshot, which would trigger repeated
    gen0/1/2 passes that each walk the whole graph. The data is all dicts and lists
    with no cycles, so reference counting frees it."""
    _gc_was_on = gc.isenabled()
    if _gc_was_on:
        gc.disable()
    try:
        return _extract_snapshot(cache, melt, date_label, _new_deaths)
    finally:
        if _gc_was_on:
            gc.enable()


def _extract_snapshot(cache, melt, date_label, _new_deaths=None):
    """Implementation body of extract_snapshot; the wrapper owns the GC window."""
    player_id = find_player(melt)
    # Playthrough check: character ids are reused across playthroughs, so the player id
    # alone cannot stop another playthrough's melt from merging here (last line of defence).
    _cpt = cache.get("playthrough_id")
    _mpt = melt.get("playthrough_id")
    if _cpt and _mpt and str(_cpt) != str(_mpt):
        print(f"  [跳过] 档期 {date_label} 战役 {_mpt} 与缓存战役 {_cpt} 不一致")
        return False
    if cache["player_id"] is not None and player_id is not None \
            and cache["player_id"] != player_id:
        # Another subject's melt of the same playthrough still contributes vassal and
        # Mandate history.
        _record_vassal_and_cycle(cache, melt, date_label)
        # The successor's snapshots also feed the prisoner hand-over latch, since
        # find_player returns the successor from then on.
        _latch_prison_succession(cache, melt, date_label)
        # A successor's snapshot can still carry wars the cached subject took part in
        # (wars span reigns), so latch once more with this cache's player id.
        _latch_war_history(cache, melt.get("wars"), date_label,
                           cache.get("player_id"))
        return False
    if cache["player_id"] is None:
        cache["player_id"] = player_id
    cache["player_id"] = player_id or cache["player_id"]
    meta = melt.get("meta_data") or {}
    if meta.get("meta_player_name") and not cache.get("player_name"):
        cache["player_name"] = meta["meta_player_name"]
    cache["game_version"] = meta.get("version") or cache["game_version"]
    # Playthrough id: a playthrough's saves (succession included) share it.
    if cache.get("playthrough_id") is None and melt.get("playthrough_id"):
        cache["playthrough_id"] = melt.get("playthrough_id")
    if date_label not in cache["sources"]:
        cache["sources"].append(date_label)
    # last_date only moves forward, so a stale or foreign snapshot cannot rewind it
    if date_key(date_label) > date_key(cache.get("last_date") or "0.0.0"):
        cache["last_date"] = date_label

    chars = all_characters(melt)
    db = _db(melt)
    lt = (melt.get("landed_titles") or {}).get("landed_titles") or {}
    tl = melt.get("traits_lookup") or []
    # Release the previous snapshot's references left in _TL (dynasty name index/memo)
    clear_dyn_caches()
    # Name-inference memo shared within this snapshot, so one rebuild computes each once
    _name_memo = {}
    # House and dynasty names use separate memos, since their ids come from different pools
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

    # Player death detection, written once and never overwritten (kills included)
    if player_id is not None:
        pdead = (chars.get(str(player_id)) or {}).get("dead_data")
        if pdead and cache.get("player_death") is None:
            cache["player_death"] = {
                "date": pdead.get("date"),
                "reason": pdead.get("reason"),
                "killer": pdead.get("killer"),
                "kills": pdead.get("kills") or [],
            }
        # Player succession chain (played_character.legacy), taken from every snapshot: the
        # last entry is the current subject, its date the accession day. Since players can
        # pick any dynasty member as successor, kinship cannot reconstruct this chain.
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

    # Target character set: player + house/family + memory participants
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
                    if not isinstance(c, dict):  # guard against a "none" entry
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
    # Further rounds bring in the colleague circle (three rounds of memory participants)
    for _round in range(3):
        snapshot = list(targets)
        for cid in snapshot:
            add_participants(cid)
    # Whole database: memory owners whose participants include the player
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

    # Kinship closure over two rounds: first-degree relatives of collected characters join
    # the target set so their names and records resolve too.
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

    # Realm holders, recorded yearly: empire/kingdom (e_/h_) titles plus titles of related
    # characters
    realm_holders = {}
    for tid, t in lt.items():
        if not isinstance(t, dict):  # guard against a "none" entry
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

    # Dynamic title names latched per snapshot, beside realm_history (both are present-day
    # values only that date carries; see _latch_title_dyn_names)
    _latch_title_dyn_names(cache, lt, date_label)

    # Casus belli of the player's wars, latched per snapshot (see _latch_war_history)
    _latch_war_history(cache, melt.get("wars"), date_label, player_id)

    # Court staff of the player from court_positions.database (employer == player): camp
    # officers and positions held by the player's subordinates, NOT the player's own offices
    if player_id is not None:
        cpd = (melt.get("court_positions") or {}).get("database") or {}
        mine = []
        for _pos_id, e in cpd.items():
            if not isinstance(e, dict):  # guard against a "none" entry
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
                targets.add(emp_id)  # office holder joins the target set, so the name resolves
            mine.append({
                "type": ptype,
                "employee": emp_id,
                "hire_date": e.get("hire_date"),
                "task": e.get("task_type"),
            })
        if mine:
            cache.setdefault("court_positions", []).append(
                {"date": date_label, "positions": mine})
        # Court positions granted TO the protagonist (employee == player, employer == another
        # person): the opposite direction from the staff list above, hence its own key
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
            targets.add(employer)   # employer joins the target set, so titles resolve
            own.append({"type": ptype, "employer": employer,
                        "hire_date": e.get("hire_date")})
        # Every snapshot appends a row, empty set included, since the losing date comes
        # from diffing (court_positions records non-empty lists only: a roster, not a term).
        cache.setdefault("court_office_history", []).append(
            {"date": date_label, "offices": own})
        # Player house motto: dynasty_house[<id>].motto (a string or a template dict)
        pobj = chars.get(str(player_id))
        if isinstance(pobj, dict) and pobj.get("dynasty_house") is not None:
            dh_ = (melt.get("dynasties") or {}).get("dynasty_house") or {}
            he = dh_.get(str(pobj.get("dynasty_house"))) or {}
            if isinstance(he, dict) and he.get("motto"):
                cache["house_motto"] = he.get("motto")
        # Both sides of a hook join the target set so their names and records resolve
        for _e in (melt.get("relations") or {}).get("active_relations") or []:
            if not isinstance(_e, dict):
                continue
            _h, _t = _e.get("first"), _e.get("second")
            if not isinstance(_h, int) or not isinstance(_t, int):
                continue
            if player_id in (_h, _t):
                targets.add(_h)
                targets.add(_t)
        # The protagonist's slaves join the target set, or their names and dates stay bare
        targets.update(enslaved_ids(melt, player_id))
        # Secret owners and knowers join the target set, since the secrets section needs
        # their full labels and person_label would otherwise come up empty
        for _sid, _rec in ((melt.get("secrets") or {}).get("secrets") or {}).items():
            if not isinstance(_rec, dict):
                continue
            for _k in (_rec.get("owner"), _rec.get("target")):
                if isinstance(_k, int):
                    targets.add(_k)
            for _p in (_rec.get("participants") or []):
                if isinstance(_p, int):
                    targets.add(_p)

    # Player primary title name changes: title_name_data (custom -> name) or envelope
    if player_id is not None:
        tname = ""
        thn = []
        ld = (chars.get(str(player_id)) or {}).get("landed_data") or {}
        dom = ld.get("domain") or []
        if dom:
            t = lt.get(str(dom[0])) or {}
            tnd = t.get("title_name_data") or {}
            # The game-computed dynamic title name wins over the static place name
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
                # The rename and accession dates use the real event day from the
                # title history, which can predate this snapshot by up to a year.
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

    # Player government changes (feudal to administrative, etc.), change points only; the
    # date is this snapshot's, since the change is discovered by diffing.
    if player_id is not None:
        _ld = (chars.get(str(player_id)) or {}).get("landed_data") or {}
        _gov = _ld.get("government") or ""
        if _gov:
            _gh = cache.setdefault("government_history", [])
            if not _gh or _gh[-1].get("government") != _gov:
                _gh.append({"date": date_label, "government": _gov})

    # Tenet history of the rite itself: the game records no date for a change (tenets[] holds
    # only {tenet, status} and only the rite's head_of_rite can change it), so the tenets and
    # current head are latched per snapshot and facts.rite_tenet_changes diffs them.
    if player_id is not None:
        _prid = rite_id_of_char(chars.get(str(player_id)))
        if _prid is not None:
            _ten = {}
            for _e in (rite_data(melt, _prid).get("tenets") or []):
                if type(_e) is dict and _e.get("tenet"):
                    _ten.setdefault(str(_e.get("status") or "known"), []).append(
                        str(_e["tenet"]))
            if _ten:
                for _v in _ten.values():
                    _v.sort()
                _th = cache.setdefault("rite_tenets_history", {}) \
                    .setdefault(str(_prid), [])
                _head = head_of_rite(melt, _prid)
                if not _th or _th[-1].get("tenets") != _ten:
                    _th.append({"from": date_label, "tenets": _ten,
                                "head": _head})

    # Kill victims join the target set so their names and records resolve
    for _cid in list(targets):
        _c = chars.get(str(_cid))
        for _v in kills_of(_c):
            targets.add(int(_v))

    # Reverse concubine index {man id: [concubine ids...]} from family_data.concubinist,
    # which is more complete than the forward concubine list
    concubinist_map = {}
    for _cid, _c in chars.items():
        if not isinstance(_c, dict):
            continue
        _m = (_c.get("family_data") or {}).get("concubinist")
        if isinstance(_m, int):
            concubinist_map.setdefault(_m, []).append(int(_cid))
    # Build the secret-father index once, since real_father_of runs per target
    sec_candidates = _secret_father_candidates(melt)

    # Uprising leaders are pre-scanned into the target set so their last_location while
    # alive is stored; registering them afterwards would lose their death and origin.
    for _base in uprising_title_bases(melt).values():
        targets.add(int(_base["holder"]))

    # Vassal contracts and the Mandate phase, through the same entry point as a merge
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
            # House and dynasty names; name_full follows display_name's name order
            if rec["dynasty_house"] is not None:
                h = house_name_zh(melt, rec["dynasty_house"])
                rec["house_name"] = h
                # dynasty name: house -> dynasty lookup (the save stores only keys)
                _did = dynasty_id_of(melt, rec["dynasty_house"])
                if _did is not None:
                    rec["dynasty_name"] = dynasty_name_zh(melt, _did) or None
                # first sighting: the first house-history point
                rec["house_history"] = [{
                    "from": date_label,
                    "house_id": rec["dynasty_house"],
                    "house_name": rec.get("house_name") or "",
                    "dynasty_id": _did,
                    "dynasty_name": rec.get("dynasty_name") or "",
                }]
            if rec["name_zh"]:
                # name_full follows display_name's order, reusing this snapshot's index
                rec["name_full"] = display_name(cache, cid, melt=melt, chars=chars,
                                                memo=_name_memo) \
                    or (rec.get("house_name", "") + rec["name_zh"])
            rec["birth"] = c.get("birth")
            rec["female"] = bool(c.get("female"))
            # The display name's authoritative rename field (see display_name)
            rec["regnal_name"] = (str(c["regnal_name"]) if c.get("regnal_name")
                                  else None)
            rec["culture"] = c.get("culture")
            rec["faith"] = c.get("faith")
            if rec["culture"] is not None:
                rec["culture_history"] = [{"from": date_label,
                                           "culture": rec["culture"]}]
            if rec["faith"] is not None:
                rec["faith_history"] = [{"from": date_label,
                                         "faith": rec["faith"]}]
        # Sex self-heal: older caches lack the field, and only women carry the melt key
        if rec.get("female") is None:
            rec["female"] = bool(c.get("female"))
        # Regnal name sync: the current snapshot's value, since the game can also remove it
        _rn_now = str(c.get("regnal_name") or "")
        if _rn_now != (rec.get("regnal_name") or ""):
            rec["regnal_name"] = _rn_now or None
            # The engine writes the regnal name only in the snapshot where the character takes
            # office, while name_full was set at first sighting, so recompute it here or a
            # fallback through name_full would print the personal name.
            rec["name_full"] = display_name(cache, cid, melt=melt, chars=chars,
                                            memo=_name_memo) \
                or rec.get("name_full") or ""
        # House history: a founding or rename leaves no memory, so only the diff can find it
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
                # A new house uses the game's found_date, exact where the diff would notice it
                # only in the next snapshot
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
        # Self-heal older caches: resolve a missing dynasty_name from the current house
        if rec.get("dynasty_name") is None and rec.get("dynasty_house") is not None:
            _hid = rec["dynasty_house"]
            _did = dynasty_id_of(melt, _hid)
            _dn_fix = _dyn_now(_did)
            if _dn_fix:
                rec["dynasty_name"] = _dn_fix
        # Culture/faith: update when the melt has a value and keep the last known one when it
        # is missing (the game clears both at death); nothing is pre-assigned here, since that
        # would make the diff below always false.
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
        # Conversions go into faith_history, since the game keeps no memory of them
        if _fid is not None:
            if rec.get("faith") != _fid:
                fh = rec.setdefault("faith_history", [])
                if not fh or fh[-1].get("faith") != _fid:
                    fh.append({"from": date_label, "faith": _fid})
            rec["faith"] = _fid
        # Rite history: a 1.20 character carries only rite (the faith comes through
        # rites.database[rite].faith); facts prefers the game's converted_rite_memory.
        _rid = rite_id_of_char(c)
        if _rid is not None:
            _rid_fid = faith_id_of_rite(melt, _rid)
            if _rid_fid is not None:
                # 1.20: the faith comes from the rite, keeping faith/faith_history usable
                if rec.get("faith") != _rid_fid:
                    fh = rec.setdefault("faith_history", [])
                    if not fh or fh[-1].get("faith") != _rid_fid:
                        fh.append({"from": date_label, "faith": _rid_fid})
                rec["faith"] = _rid_fid
            if rec.get("rite") != _rid:
                rh = rec.setdefault("rite_history", [])
                if not rh or rh[-1].get("rite") != _rid:
                    rh.append({"from": date_label, "rite": _rid})
            rec["rite"] = _rid
        # Personal tenets, spiritual fulfillment and religious knowledge (1.20
        # playable_data), carried only by landed rulers and the player.
        _pd = c.get("playable_data")
        if type(_pd) is dict and "tenets" in _pd:
            _pt = [t for t in (_pd.get("tenets") or []) if type(t) is str]
            _old = rec.get("personal_tenets") or []
            if _old != _pt:
                _pth = rec.setdefault("personal_tenet_history", [])
                _seen = {h.get("tenet") for h in _pth}
                for _t in _pt:
                    if _t not in _seen:
                        _pth.append({"from": date_label, "tenet": _t})
                        _seen.add(_t)
                # Change points: personal tenets can be dropped or replaced (slots grow with
                # piety) and the game records no date, so the whole set is stored.
                _psh = rec.setdefault("personal_tenets_history", [])
                if not _psh or list(_psh[-1].get("tenets") or []) != _pt:
                    _psh.append({"from": date_label, "tenets": list(_pt)})
            rec["personal_tenets"] = _pt
        if type(_pd) is dict:
            _kd = _pd.get("known_doctrines")
            if isinstance(_kd, list):
                rec["known_doctrines_n"] = len(_kd)
            _kt = _pd.get("known_tenets")
            if isinstance(_kt, list):
                rec["known_tenets_n"] = len(_kt)
            _sf = _pd.get("current_spiritual_fulfillment")
            if isinstance(_sf, (int, float)) and not isinstance(_sf, bool):
                rec["spiritual_fulfillment"] = float(_sf)
                _sfh = rec.setdefault("sf_history", [])
                if not _sfh or _sfh[-1].get("value") != float(_sf):
                    _sfh.append({"from": date_label, "value": float(_sf)})
        # Nickname change points: the game gives a nickname only in the current save, so an
        # older article would otherwise see the latest one ('' means "no nickname then").
        if "nickname_text" in c:
            _nick = c.get("nickname_text")
            _nick = "" if _nick is None else str(_nick)
            _nh = rec.setdefault("nickname_history", [])
            if not _nh or _nh[-1].get("nickname") != _nick:
                _nh.append({"from": date_label, "nickname": _nick})
        # Languages (alive_data.languages) follow the culture rule: update when present,
        # keep the last known value when the game clears them at death.
        langs = (c.get("alive_data") or {}).get("languages") or []
        if langs:
            rec["languages"] = list(langs)
        # Last known province, copied into the death record for the assassin section
        _loc = (c.get("alive_data") or {}).get("location") or {}
        _prov = _loc.get("location") if isinstance(_loc, dict) else _loc
        if isinstance(_prov, int):
            # The first-sighting province is the only evidence for a birthplace (the game
            # persists none); facts.birth_place uses it only within 400 days of birth.
            if first_time:
                rec["first_location"] = {"date": date_label, "province": _prov}
            rec["last_location"] = {"date": date_label, "province": _prov}
        # Traits and trait_history, diffed per snapshot
        new_traits = c.get("traits") or []
        old_traits = rec.get("traits") or []
        if first_time or old_traits != new_traits:
            th = rec.setdefault("trait_history", {})
            if first_time:
                # First sighting: every trait gets first=True (held at least from here)
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
        # Trait XP samples: trait_xp_amounts is positionally aligned with traits, so a
        # sample must be paired with that snapshot's traits or the tracks misalign.
        new_xp = list(c.get("trait_xp_amounts") or [])
        samples = rec.setdefault("trait_xp", [])
        if new_xp and (not samples
                       or samples[-1].get("traits") != list(new_traits)
                       or samples[-1].get("xp") != new_xp):
            samples.append({"from": date_label, "traits": list(new_traits),
                            "xp": new_xp})
        # Imprisonment intervals: prison_data is the authoritative "currently imprisoned"
        # field while released_from_prison_memory exists only for a voluntary release.
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
                # same jailer and type as the previous span: keep it as one span
                pass
            elif _same_span:
                # The same span under a NEW jailer: a jailer's death passes the prisoners
                # to the successor while the game keeps prison_data.date at the original
                # day, so the first jailer is kept in from_imprisoner.
                ph[-1]["from_imprisoner"] = ph[-1].get("from_imprisoner") \
                    or ph[-1].get("imprisoner")
                ph[-1]["imprisoner"] = cur["imprisoner"]
                ph[-1]["type"] = cur["type"]
            else:
                if ph and ph[-1].get("to") is None:
                    ph[-1]["to"] = date_label
                ph.append(cur)
        elif rec.get("prison_history") and rec["prison_history"][-1].get("to") is None:
            # no prison_data in this snapshot: the previous span ended before it
            rec["prison_history"][-1]["to"] = date_label
        # Family: direct fields plus back-referenced relatives
        fam = family_of(c)
        fathers, mothers = _parents_of(chars, cid, parent_map, fam)
        if fathers:
            fam["father"] = fathers
        if mothers:
            fam["mother"] = mothers
        sib = _siblings_of(cid, parent_map, child_map, sibling_map, fam)
        if sib:
            fam["siblings"] = sib
        # Real father: direct field plus secret derivation, via the prebuilt index
        rf = real_father_of(melt, cid, chars, sec_candidates)
        if rf is not None:
            fam["real_father"] = [rf]
        # Concubines: the forward field unioned with the reverse concubinist map
        rev_cons = concubinist_map.get(cid, [])
        if rev_cons:
            fam["concubine"] = list(dict.fromkeys(
                (fam.get("concubine") or []) + rev_cons))
        # The family set is merged key by key and empty values never overwrite, since a dead
        # character's family_data has been cleared while the set records what once existed.
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
        # All spouses ever held, including those dropped after a divorce or death
        ever = set(rec["family"].get("ever_spouses") or [])
        for _k in ("primary_spouse", "spouse", "former_spouses",
                   "concubine", "former_concubines"):
            ever.update(int(x) for x in (fam.get(_k) or []))
        if ever:
            rec["family"]["ever_spouses"] = sorted(ever)
        # Court affiliation (court_data), stored on the character by the save
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
        # Government change points per target character ({cid: [{date, government}]}), since
        # the wording a date needs depends on the government then in force.
        _ld_all = c.get("landed_data") or {}
        _gov_all = _ld_all.get("government") or ""
        if _gov_all:
            _chg = cache.setdefault("char_government_history", {})
            _h = _chg.setdefault(str(cid), [])
            if not _h or _h[-1].get("government") != _gov_all:
                _h.append({"date": date_label, "government": _gov_all})
        # Kills (alive_data.kills and dead_data.kills), accumulated and deduplicated
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
            # Domicile (nomadic herd and provisions) from domiciles.database
            _dom = player_domicile(melt, ld.get("domain"), cid)
            if _dom:
                rec["landed"]["herd"] = _dom.get("herd")
                rec["landed"]["provisions"] = _dom.get("provisions")
                rec["landed"]["domicile_type"] = _dom.get("domicile_type")
                rec["landed"]["domicile_province"] = _dom.get("province")
            # Player location history, change points only
            loc = (c.get("alive_data") or {}).get("location") or {}
            prov = loc.get("location") if isinstance(loc, dict) else loc
            if isinstance(prov, int):
                hist = cache.setdefault("player_locations", [])
                if not hist or hist[-1].get("province") != prov:
                    hist.append({"date": date_label, "province": prov})
            # Capital history: realm_capital moves while cache.landed keeps only the final
            # value, and an execution place uses the capital of that moment.
            _cap = ld.get("realm_capital")
            if _cap is not None:
                _ch = cache.setdefault("capital_history", [])
                if not _ch or _ch[-1].get("title") != _cap:
                    _ch.append({"date": date_label, "title": _cap})
            # Camp purpose history (stage wording: chief/leader/captain), a holder law
            # (camp_purpose_*) kept as change points only.
            if ld.get("government") == "landless_adventurer_government":
                _purpose = next(
                    (str(x).split("_", 2)[2] for x in (ld.get("laws") or [])
                     if str(x).startswith("camp_purpose_")), "")
                if _purpose:
                    _ph = cache.setdefault("camp_purposes", [])
                    if not _ph or _ph[-1].get("purpose") != _purpose:
                        _ph.append({"date": date_label, "purpose": _purpose})
            # The player's house name (stored bare, used in the display name)
            if rec.get("dynasty_house") is not None:
                h = house_name_zh(melt, rec["dynasty_house"])
                if h:
                    cache["house_name"] = h
                # The player's dynasty: output folders are grouped by dynasty
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
            # Last known province before death, captured from living snapshots
            if (rec.get("last_location") or {}).get("province") is not None:
                rec["death"]["location_province"] = rec["last_location"]["province"]
            if _new_deaths is not None:
                _new_deaths.append(cid)
        # Memories: alive_data.memories -> database
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
    # Secrets, factions, epidemics, disease edges, hooks, marriage pairs, enslavement,
    # opinions, relation reasons, spouse/prison latches and Carnalitas traces: each helper
    # diffs or latches its slice of the snapshot into the cache (see its docstring).
    _diff_secrets(cache, melt, date_label)
    _diff_factions(cache, melt, date_label)
    _diff_epidemics(cache, melt, date_label)
    _diff_disease_edges(cache, melt, date_label)
    _diff_hooks(cache, melt, date_label)
    _latch_matrilineal(cache, melt, date_label)
    _diff_enslavements(cache, melt, date_label)
    _diff_opinions(cache, melt, date_label)
    _latch_relation_reasons(cache, melt, date_label)
    _latch_spouses(cache, melt, date_label)
    _latch_prison_manners(cache, melt, date_label)
    _diff_carnal_opinions(cache, melt, date_label)
    _diff_carnal_modifiers(cache, melt, date_label)
    # Returns True rather than the cache, so callers' "if not ok:" holds and logs stay small
    return True


# Hook type filter: house_head_hook comes with a position rather than a narrative hold
# (a house head holds it over every kinsman), and filial_piety_hook and favor_hook are
# generic obligations; almost every hook in a save is one of those three, so only
# whitelisted types are stored and generic ones never reach the model as leverage.
def hook_type_kept(tp):
    """Whether a hook type is stored; the predicate is style.hook_type_kept, shared with
    facts."""
    return _style.hook_type_kept(tp)


def matrilineal_pair_key(a, b):
    """Marriage pair -> cache key (smaller id first, so direction does not matter)."""
    return f"{min(int(a), int(b))}>{max(int(a), int(b))}"


def _latch_prison_succession(cache, melt, date_label):
    """Prisoner hand-over latch: "the prisoners A jailed, B jails after A's death".

    A jailer's death passes the prisoners to the successor while the game keeps
    prison_data.date at the original day of imprisonment, and those later snapshots
    belong to the successor, so the subject's own cache never sees the transfer.

    Called when the melt's player differs from the cached subject, it records
    cache["prison_succession"]["<victim>"] = {"victim", "from", "to", "since",
    "first_seen"} whenever someone is imprisoned under jailer B while their imprisoned
    memory names jailer A (the cached subject). First sighting wins."""
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
    """Matrilineal (uxorilocal) marriage pairs latched.

    The save shapes them as
    relations.active_relations = [{"first": 33219, "second": 34000,
    "matrilineal": true}, ...], where matrilineal means the children belong to the
    MOTHER's house rather than the father's. An entry exists only while the marriage
    lasts, so every sighting is kept and a later divorce or death still leaves that
    marriage writable. Returns the number of new pairs."""
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


# family_data keys -> the other party's status: concubinist is a reverse key whose value is
# the owner, while the others sit on the person and point at the spouse; the strongest rank
# wins when two snapshots record the same pair under different keys.
_SPOUSE_LATCH_KEYS = (
    # (key, status of the other party, is a reverse key)
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
    """Spouse latch key, always oriented as "subject > other"."""
    return f"{int(player_id)}>{int(other_id)}"


def _latch_spouses(cache, melt, date_label):
    """Spouse latch for the subject.

    The subject's OWN family_data is cleared in the death snapshot while generation reads
    only the newest melt, so a lifetime of marriages would vanish; what survives is the
    reverse pointer on the other party. Every merge scans all characters' family_data and
    latches anything involving the subject, first sighting wins, taking the strongest
    status by _SPOUSE_KIND_RANK.

    Keys are "<subject>><other>" with {player, other, kind, source, since, first_seen};
    since is the EARLIEST known date, since a first sighting can be up to a year late (see
    _latch_spouse_dates). Returns how many pairs this snapshot added."""
    pid = cache.get("player_id")
    if pid is None:
        return 0
    pid = int(pid)
    latch = cache.setdefault("spouse_latch", {})
    for cid, c in all_characters(melt).items():
        _latch_spouses_of(c, cid, latch, pid, date_label)
    _latch_spouse_dates(latch, melt, pid)
    return sum(1 for v in latch.values() if v.get("first_seen") == date_label)


# Naming opinions (owner = the person taken, target = the taker) that date a marriage with
# the subject; forced_spouse_concubine_marriage_opinion sits on the ORIGINAL spouse instead.
_SPOUSE_OPINION_START = ("forced_me_concubine_marriage_opinion",
                         "concubine_with_monogamous_faith_opinion")


def _latch_spouse_dates(latch, melt, pid):
    """Use a naming opinion's start_date as the marriage start date (see _latch_spouses).

    A first sighting can miss the marriage by a year while active_opinions' start_date is
    the exact day the game recorded, so the earlier of the two wins. Concubinage opinions
    sit on the person TAKEN, whereas the one on the original spouse dates the taken person's
    marriage to someone else, so that case looks up the subject's latch instead."""
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
            # the subject took owner as a concubine
            rec = latch.get(spouse_latch_key(pid, owner))
            if rec is not None:
                st = min(dates.values(), key=date_key)
                cur = rec.get("since") or rec.get("first_seen") or ""
                if not cur or date_key(st) < date_key(cur):
                    rec["since"] = st
        elif owner != pid:
            # the owner's original spouse was taken by the subject: use the former spouse
            # that already has a latch with the subject
            ex_fd = _as_char((melt.get("living") or {}).get(str(owner))
                             or (melt.get("dead_unprunable") or {}).get(str(owner)))
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
    """One character's family_data -> spouse latch entries (see _latch_spouses)."""
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
    """Relation-reason latch key, oriented like the save ("<owner>|<target>|<kind>")."""
    return f"{int(owner)}|{int(target)}|{kind}"


def _latch_relation_reasons(cache, melt, date_label):
    """Latch the cause behind feuds and friendships (pure code, no prompt involvement).

    scripted_relations.<kind>.reason is the cause key the game itself wrote (localization
    templates in data/localization.json under relation_templates), but it exists only
    while the relation does: once one side dies or the relation ends, entry and reason
    leave the save, and generation sees only the newest melt, so an early feud would lose
    its cause. Every merge latches it (first sighting wins, later snapshots refresh
    last_seen), keeping rows whose sides are the subject or are both in this
    playthrough's character table -- a lover_prison cause can belong to two non-players.
    Rows without a reason are skipped, leaving "has a cause" versus "has none" to the
    generation side, and province is recorded because some reason templates interpolate a
    province name. Returns the number added."""
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
    """One hook field in relations.active_relations -> (holder, target).

    The DIRECTION comes from the slot number, not from first/second: the engine normalizes
    paired relations so that first < second, and active_hook_<N> carries the direction
    (even N = first holds it over second, odd N = the reverse)."""
    slot = str(field).rsplit("_", 1)[-1]
    try:
        n = int(slot)
    except ValueError:
        n = 0
    return (first, second) if n % 2 == 0 else (second, first)


def _minus_years(date_str, n):
    """'934.4.2' minus n calendar years -> '924.4.2'; '' when it cannot be computed, which
    includes a permanent hook's sentinel expiry (9999.1.1)."""
    s = str(date_str or "")
    if not s or s.startswith("9999") or s == "none":
        return ""
    try:
        y, m, d = (int(x) for x in s.split(".")[:3])
        return f"{y - n}.{m}.{d}"
    except Exception:
        return ""


def _latch_prison_manners(cache, melt, date_label):
    """Latch the reason behind each release from prison.

    facts.release_manner sees only the current melt, but release opinions decay over 10
    years and vanish with their holder, so a decade-old release would fall back to a bare
    "released". Two sources feed the latch: release-type modifiers in
    opinions.active_opinions, which carry start_date to the day (owner = prisoner,
    target = releaser, except the ransom case whose target is the payer), and
    favor_hook / indebted_hook, whose expiry is creation + 10 calendar years (outside
    hook_type_kept's whitelist, so they serve the latch only).

    Keys are "<prisoner>><jailer>><date>" with {victim, jailer, date, kind, src,
    first_seen}; first sighting wins regardless of melt age and only rows involving the
    player are kept."""
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

    # ---- 1) release-type opinions ----
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

    # ---- 2) ransom and favour hooks (creation date derived from the expiry) ----
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
    """Merge this snapshot's hooks into cache["hooks"] (a per-snapshot diff).

    active_hook_<N> entries on relations.active_relations carry {type, expiration_date};
    the direction comes from the slot number (see hook_slot_holder), since first and
    second are only a normalized pair of ids. Keys are "<holder>><target>><type>" with
    {holder, target, type, expiration, first_seen, first, last_seen, lost_at}, kept only
    when the holder or target is the player. first means the hook predates the data."""
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
    """Ids enslaved by owner_id in this snapshot (Carnalitas).

    The save shapes them as opinions.active_opinions entries with
    scripted_relations = {"slave": {...}}, where owner = the slave owner and
    target = the slave (paired with slave_owner; see Mod
    common/scripted_relations/carnal_slave_relations.txt)."""
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
    """Every master/slave relation in this snapshot {slave id: master id}.

    Same source as enslaved_ids (scripted_relations.slave) but not limited to a player
    owner: after a slave is sold the relation follows them to the buyer, so only the
    whole save reveals who they were sold to. This is also what separates "sold" from
    "freed", since a freed person gains the former_slave trait and loses the slave
    relation."""
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
    """Merge this snapshot's master/slave relations into cache["enslavements"].

    Carnalitas' carn_enslave_effect also runs release_from_prison = yes on an already
    imprisoned slave at the exact moment of enslavement (Mod
    common/scripted_effects/carn_slave_effects.txt), so the save's
    released_from_prison_memory IS the enslavement step, and only this relation
    separates it from a genuine release. The relation carries no creation date, so the
    snapshot diff yields the first recorded one.

    Records look like::

        {"38670>14590": {"owner": 38670, "slave": 14590,
                         "first_seen": "873.1.1", "first": false,
                         "last_seen": "888.1.1", "lost_at": null}}

    first means the slave already was one in the first snapshot; a relation that stops
    appearing gets lost_at. Every relation is kept so a sold slave leaves a trace, and
    when the owner changes the previous owner goes into prev_owners while owner tracks
    the current one, which is how a resale is traced. When a relation disappears,
    end_owner records whoever still enslaved them at that moment (the buyer), or freed
    records that nobody did (the former_slave trait)."""
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


# Concubinage opinions (forced_me_concubine, concubine_with_monogamous_faith,
# forced_spouse_concubine, stole_concubine): the only place it carries an exact date
_CONCUBINE_OPINIONS = {
    "forced_me_concubine_marriage_opinion",
    "concubine_with_monogamous_faith_opinion",
    "forced_spouse_concubine_marriage_opinion",
    "stole_concubine_opinion",
}

# Carnalitas opinion families (Mod common/opinion_modifiers/*.txt), matched by prefix or
# suffix: carn_raped_* and carn_enslaved_* cover acts against the subject or their circle,
# carn_former_slave_or_slave_owner_opinion is left by BOTH a sale and a release, and the
# suffixes are single-event opinions (forced prostitution, demanded manumission).
_CARNAL_OPINION_PREFIXES = ("carn_raped_", "carn_enslaved_")
_CARNAL_OPINION_SUFFIXES = (
    "carn_former_slave_or_slave_owner_opinion",
    "carn_forced_me_into_prostitution_opinion",
    "carn_demanded_manumission_opinion",
)


def _carnal_opinion_kind(mod):
    """Whether an opinion modifier belongs to a Carnalitas event family; returns the
    family name or ''."""
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
    """Diff Carnalitas relation opinions into cache["carnal_opinions"].

    Rows are keyed owner>target>modifier and hold {owner, target, modifier, kind, start,
    expiration, first_seen, first, last_seen, lost_at}, with owner holding the opinion as
    in _diff_opinions. These opinions carry start_date, so the moment a slave was sold is
    pinned exactly; only rows with the subject on one side are kept."""
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
    """The temporary modifier names on a character entry.

    They sit inside alive_data beside stress and gold; rakaly normalizes singular and
    plural key names, so all three spellings are accepted."""
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
    """Diff the carn_recently_raped modifier into cache["carnal_modifiers"].

    Mod common/modifiers/carn_rape_modifiers.txt adds carn_recently_raped (health -0.25,
    5 years) to the victim through carn_rape_victim_stress_effect; it shows the act was
    treated as forced and is the victim's fallback signal when no memory exists."""
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
    """An entry's temporary_opinion as a list (duplicate keys merge into one)."""
    v = o.get("temporary_opinion")
    if isinstance(v, dict):
        return [v]
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    return []


def _diff_opinions(cache, melt, date_label):
    """Merge this snapshot's concubinage opinions into cache["opinions"].

    active_opinions entries carry temporary_opinion = {"modifier", "start_date",
    "expiration_date", "days"} where owner holds the opinion and target caused it. The
    script concubine_on_accept_effect gives forced_me_concubine_marriage_opinion to
    someone imprisoned or chaste and then runs release_from_prison = yes, so the day of
    the forced concubinage is the day they left prison -- the only dated record of
    "raided and taken -> forced concubine", since taking a concubine leaves no memory.
    Rows are keyed owner>target>modifier; first marks presence in the first snapshot and a
    row that stops appearing gets lost_at."""
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
    """Merge this snapshot's epidemics.database into cache["epidemics"].

    Rows are keyed by epidemic id and hold {name, type, intensity, creation_date,
    start_province, provinces, infections, first_seen, first, lost_at}. first means the
    epidemic was already present at the data start, so its start year is creation_date."""
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
                # Infected province set, used to decide whether an epidemic reached a
                # person's domain or county and to take its dynamic disease name; only
                # the first 400 are kept to limit the cache size.
                "infections": sorted(
                    (int(x) for x in (e.get("infections") or {})
                     if str(x).isdigit()))[:400],
                "first_seen": date_label,
                "first": True,
                "lost_at": None,
            }
            continue
        # Refresh per snapshot: name, size and intensity change as the epidemic spreads
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
    # An epidemic absent from this snapshot gets lost_at (no longer spreading)
    ids = {str(k) for k, v in db.items() if isinstance(v, dict)}
    for sid, rec in hist.items():
        if isinstance(rec, dict) and sid not in ids and not rec.get("lost_at"):
            rec["lost_at"] = date_label


# ---------------------------------------------------------------------------
# Venereal disease transmission edges (lover's pox / great pox) - triggered_event
# ---------------------------------------------------------------------------
# Source: hidden events in each melt's triggered_event list, whose event_targets carry
# sick_character, disease_type (a flag) and infecting_partner plus a date. Carnalitas
# stores the already infected partner in infecting_partner and the patient in
# sick_character, then schedules a recheck (health.1200, days={60 1000} for lover's pox;
# health.1201, days={250 1500} for great pox), so the queue date is the recheck day and the
# infection day falls within [recheck - max, recheck - min], which facts converts per
# disease. An entry without infecting_partner (prostitution or congenital) or equal to
# sick_character (the patient's own recheck) is not an edge.
_STD_DISEASES = ("lovers_pox", "great_pox", "early_great_pox")


def _iter_triggered(melt):
    """triggered_event -> list of event dicts (duplicate keys merge into a list)."""
    te = melt.get("triggered_event")
    if isinstance(te, list):
        return [e for e in te if isinstance(e, dict)]
    if isinstance(te, dict):   # fallback for an unmerged single/dict shape
        out = []
        for v in te.values():
            if isinstance(v, dict):
                out.append(v)
            elif isinstance(v, list):
                out += [x for x in v if isinstance(x, dict)]
        return out
    return []


def _char_identity(v):
    """An event slot ({"type":"char","identity":N}) -> character id; None when absent."""
    if isinstance(v, dict):
        i = v.get("identity")
        return i if isinstance(i, int) else None
    return v if isinstance(v, int) else None


def _std_edges_of(melt):
    """This snapshot's triggered_event -> [(disease, source, target, fire_date)] for real
    transmission edges only; entries missing sick_character are dropped."""
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
            continue          # the patient's own scheduled recheck: not a transmission
        out.append((str(flag), src, sick, str(e.get("date") or "")))
    return out


def _diff_disease_edges(cache, melt, date_label):
    """Diff venereal disease transmission edges into cache["disease_edges"].

    Rows are keyed disease>source>target>fire_date and hold {disease, source, target,
    fire_date, first_seen, last_seen, first}; first=True means the data start showed it."""
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
    """Ids holding a high title (h_/e_/k_) or a court office (e_minister_*) in this
    snapshot: the source range for the court-officials section."""
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
    """Merge this snapshot's secrets into cache["secrets_history"] (a per-snapshot diff).

    Records look like::

        {"102": {"type": "secret_exam_cheater", "owner": 38682,
                 "target": 10914, "participants": [38682],
                 "first_seen": "868.1.1", "first": true,   # seen in the first snapshot
                 "known_by": [{"id": 38682, "from": "868.1.1", "first": true}],
                 "lost_at": "879.1.1"}}                    # no longer in any snapshot
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
    # Relevance: owner/target/participant is in the related set, or a related person knows it
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
            # Reappearing or transferred: a secret can pass to someone else on the owner's death
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
    # Gone from this snapshot: record lost_at
    for sid, rec in hist.items():
        if sid in want or rec.get("lost_at"):
            continue
        rec["lost_at"] = date_label


# Uprising faction types (game faction_manager.type); the others (independence,
# claimant, liberty, nation_fracturing, replace_regent) belong to vassal factions whose
# leaders already hold landed titles.
_UPRISING_TYPES = ("peasant_faction", "escalated_peasant_faction",
                   "populist_faction", "nomadic_faction")

# Uprising title names -> faction type, from the game's title_name_data.name. The game
# creates these from script with a capital, a date and a holder, and delete_on_destroy
# removes the title after the leader dies, so it must be read while the leader lives.
_UPRISING_TITLE_NAMES = {
    "农民叛乱": "peasant_faction",
    "民粹暴动": "populist_faction",
    "游牧民叛乱": "nomadic_faction",
    "农民起义": "peasant_faction",
    "民粹起义": "populist_faction",
    "游牧民起义": "nomadic_faction",
}


def _title_name_of(t):
    """Title display name: title_name_data.name, falling back to key."""
    tnd = (t or {}).get("title_name_data") or {}
    return (tnd.get("name") or "").strip() or ((t or {}).get("key") or "")


def uprising_title_bases(melt):
    """This snapshot's uprising titles -> {holder_cid: base}, where base = {"holder",
    "title", "county", "county_name", "name", "type", "from"}: the title id, the revolt's
    county (title.capital), the title name (which supplies the uprising word), the faction
    type and title.date. A title qualifies when its key is x_script_/x_mc_/x_ho_."""
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
    """Merge this snapshot's uprising LEADERS into cache["factions"].

    Rows are keyed by leader id and hold {type, first_seen, last_seen, first, target,
    counties, faith, culture, base}, where base = {"title", "county", "county_name",
    "name", "from", "type"}. Only uprising factions are kept, since other vassal
    faction leaders already hold landed titles, and the save gives no faction dates, so
    first_seen/last_seen come from the diff.

    Every leader is recorded rather than filtered by relevance: rebel leaders often
    enter the subject's view only after their death, through secrets or murders. Script
    titles whose name is in _UPRISING_TITLE_NAMES are merged in too, which supplies a
    leader identity and a place of origin for leaders absent from the faction records.
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
    # Uprising titles as a second route (covers leaders absent from faction records)
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
# Memory backtracking for dead characters (restored from the last snapshot while alive)
# ---------------------------------------------------------------------------

def recover_dead_memories_from(melt, cache, cid, chars=None):
    """Restore character cid's memories from one melt (the last snapshot before death).

    Memory objects live in that snapshot's character_memory_manager.database and
    alive_data.memories references them; chars is prebuilt once by the caller."""
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
# Memory archive (a sidecar index, so backtracking never loads a whole old melt)
# ---------------------------------------------------------------------------
# Backtracking needs one dead character's memories from the last snapshot before death, and
# loading a full melt each time is the bulk of a yearly merge, so each melt gets a slim
# sidecar melt_<date>_idx.json holding only {chars: {cid: [memory ids...]}, db: {memory id:
# compact entry}} — the fields memory_brief uses. Built lazily once and persisted.


def _index_stem(melt_path):
    """Melt path -> sidecar naming base, without the compression suffix or .json."""
    p = melt_stem(melt_path)
    return p[:-5] if p.lower().endswith(".json") else p


def _melt_index_variants(melt_path):
    """Melt -> the three possible sidecar paths (.json / .json.gz / .json.xz)."""
    stem = _index_stem(melt_path)
    return [stem + "_idx.json", stem + "_idx.json.gz", stem + "_idx.json.xz"]


def melt_index_path(melt_path):
    """Full melt -> memory archive sidecar path (melt_913_01_01.json ->
    melt_913_01_01_idx.json). The _idx keeps code that globs melt_<date>.json from
    mistaking the sidecar for a melt; the sidecar follows the melt's suffix."""
    p = str(melt_path)
    low = p.lower()
    for suf in (".xz", ".gz"):
        if low.endswith(suf):
            return _index_stem(p) + "_idx.json" + suf
    return _index_stem(p) + "_idx.json"


def build_melt_index(melt):
    """Build the memory archive dict from a full melt, without persisting it.

    Each variable tuple keeps a 4th slot, the value of a flag-type variable
    (data.flag), matching memory_brief; without it, memories restored through the
    sidecar lose flag values such as a title-grant reason."""
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
    """Build and persist the memory archive sidecar (atomic write); returns its path.

    A sidecar is always written compressed, since a plain one for the newest melt would
    be tens of MiB; a cold melt's sidecar follows the melt's suffix. Compact separators
    are used, as for player caches."""
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
    """Read the memory archive sidecar; None when it is missing or corrupt.

    All suffixes are tried, since the archive and the melt can be compressed in either
    order, and the bytes are read whole to skip a decoder layer."""
    for p in _melt_index_variants(melt_path):
        if not os.path.isfile(p):
            continue
        try:
            return json.loads(_read_melt_bytes(p))
        except Exception:
            continue
    return None


def _brief_from_index(mid, e):
    """Archive entry -> the same compact entry memory_brief produces, with vars as
    [flag, type, identity, value] tuples; older sidecars store three-element tuples."""
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
    """Restore character cid's memories from the archive.

    Equivalent to recover_dead_memories_from, reading the sidecar index instead of a
    full melt; returns how many were restored."""
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
# Relation summaries
# ---------------------------------------------------------------------------

def summarize_relations(cache):
    """Rival/grudge/nemesis list against the subject, from both points of view."""
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
