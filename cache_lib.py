# -*- coding: utf-8 -*-
"""CK3 记忆缓存库 v3 (由 expck3/cache_lib.py v2 升级移植)。

记忆系统真实结构 (经 exp6/exp7/exp8 实测验证):
  - character_memory_manager.database : 键 = **记忆 ID** (与角色共享 id 池)。
  - 每个角色的 alive_data.memories = { 记忆ID列表 } : 角色 → 记忆的多对多映射。
  - 角色**死亡时 memories 列表被清空**, 记忆对象也从 database 移除
    (实测: 868 活有记忆→869 已死 141 人全部清空; 对照活人保留)。
  - 因此必须在角色死前的年度存档里抓取记忆 → 缓存库是唯一可靠方案。

v3 变更 (相对 expck3 v2):
  1. **每玩家一份缓存** (cache/player_<id>.json), 支持「主角死亡→继承人继位」的
     多角色长局; 每次玩家角色死亡只生成一篇终传 (bio_generated 标记)。
  2. **姓名合并**: 角色记录新增 house_name (宗族/姓氏, 如 边) 与 name_full (姓+名,
     如 边诚); 姓氏取自 dynasties.dynasty_house 的码点名 (dynn_Bian_908A → 边)。
  3. 全中文解析: resolve_full_name / house_name_zh 统一收口, 供 facts.py 使用。
"""
import json
import os
import re

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


def name_zh(char_obj):
    """角色对象 first_name (名表键) → 中文名。"""
    fn = (char_obj or {}).get("first_name") or ""
    return zh(decode_codepoints(fn))


def house_name_zh(melt, house_id):
    """宗族 id → 姓氏中文。dynasties.dynasty_house[<id>].name = 'dynn_Bian_908A'
    → '边'; 解析失败返回 ''。"""
    if house_id is None:
        return ""
    try:
        dh = (melt.get("dynasties") or {}).get("dynasty_house") or {}
        e = dh.get(str(house_id)) or {}
        name = e.get("name") or ""
        if name.startswith("dynn_"):
            name = name[len("dynn_"):]
        dec = zh(decode_codepoints(name))
        # 去掉残留的拉丁前缀 (个别情况 name 无码点)
        if dec and any("\u3400" <= ch <= "\u9fff" for ch in dec):
            return dec
        return ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------

def load_melt(path):
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


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
    """角色 alive_data.memories (记忆ID列表)。"""
    return (char_obj or {}).get("alive_data", {}).get("memories") or []


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
                "father", "mother", "siblings"):
        v = fd.get(key)
        if v is None:
            continue
        ids = [int(x) for x in (v if isinstance(v, list) else [v])]
        out[key] = ids
    return out


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
    "schema": 3,
    "player_id": None,
    "player_name": None,
    "house_name": None,       # 家族名 (如 边氏), 输出文件夹名依据
    "playthrough_id": None,   # 战役标识 (存档 playthrough_id; 同一战役的存档共享)
    "game_version": None,
    "sources": [],
    "last_date": None,
    "player_death": None,     # 首次检测到玩家 dead_data 即写入 {date, reason, killer}
    "bio_generated": False,   # 终传是否已生成 (每次玩家角色死亡只生成一篇)
    "characters": {},
    "relations": {},
}


def cache_path_for(cache_dir, player_id):
    return os.path.join(cache_dir, f"player_{player_id}.json")


def load_cache(path):
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                cache = json.load(fp)
            # 兼容旧 schema: 补齐 v3 字段
            for k, v in EMPTY_CACHE.items():
                cache.setdefault(k, v)
            return cache
        except Exception:
            pass
    return dict(EMPTY_CACHE)


def save_cache(cache, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(cache, fp, ensure_ascii=False, indent=1)


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
            "family": {},
            "landed": {},
            "memories": [],
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
# 单档提取 (v3: 每玩家缓存 + 姓名合并)
# ---------------------------------------------------------------------------

def extract_snapshot(cache, melt, date_label):
    """把一个存档快照并入缓存。返回 False 表示玩家不一致被拒绝。"""
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
    cache["last_date"] = date_label

    chars = all_characters(melt)
    db = _db(melt)

    # 玩家死亡检测 (首次写入后不再覆盖)
    if player_id is not None:
        pdead = (chars.get(str(player_id)) or {}).get("dead_data")
        if pdead and cache.get("player_death") is None:
            cache["player_death"] = {
                "date": pdead.get("date"),
                "reason": pdead.get("reason"),
                "killer": pdead.get("killer"),
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

    for cid in sorted(targets):
        c = chars.get(str(cid))
        if c is None:
            continue
        rec = char_record(cache, cid)
        if rec["first_name"] is None:
            rec["first_name"] = c.get("first_name")
            rec["name_zh"] = name_zh(c)
            rec["dynasty_house"] = c.get("dynasty_house")
            # 姓氏 + 姓名合并 (v3)
            if rec["dynasty_house"] is not None:
                h = house_name_zh(melt, rec["dynasty_house"])
                rec["house_name"] = h
                if h and rec["name_zh"]:
                    rec["name_full"] = h + rec["name_zh"]
            rec["birth"] = c.get("birth")
            rec["culture"] = c.get("culture")
            rec["faith"] = c.get("faith")
            rec["traits"] = c.get("traits") or []
        rec["family"] = family_of(c)
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
            }
            # 玩家所属家族名 (输出文件夹依据)
            if rec.get("dynasty_house") is not None:
                h = house_name_zh(melt, rec["dynasty_house"])
                if h:
                    cache["house_name"] = h + "氏"
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
