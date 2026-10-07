# -*- coding: utf-8 -*-
"""v116 断言：行政制（天朝制）头衔持有者的子女称号按游戏词表的封臣支/独立支取值。

用户报（2026-10-08）：`山南王子洪审礼` —— 天朝制下除皇帝本人外，官员的子女不会有王子/郡主。
游戏词表 game/common/flavorization/11_tgp_china_flavorization.txt：
  :1268/1282 prince/princess_kingdom_celestial_chinese        = 公子/公女（only_vassals）
  :1374/1388 *_kingdom_celestial_chinese_independent          = 王子/郡主（only_independent）
  :1240/1254 *_empire_celestial_chinese                       = 公子/公女（only_vassals）
  :1212/1226 *_empire_chinese                                 = 皇子/皇女（only_independent）
  :654/663   prince_male/princess_female_celestial_chinese    = 皇子/皇女（hegemony）

三层：
  A 规则层（合成桩，秒级）：政体 + 封臣/独立 → 词；卒档 liege 与卒后封臣史两条纠正。
  B 快照层：output/洪氏2/data/snap_v116_207044_final.json 的世系行（与 v115 快照逐行对照）。
  C 成稿层：9 篇终传的逐串替换结果（logs/v116_prince_backup.json）。

用法: python -X utf8 tools/tests/verify_v116.py [--page]
  --page 另核对 output/洪氏2/index.html（需先 python -X utf8 htmlview.py rebuild 洪氏2）
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import facts as F          # noqa: E402
import localization as L   # noqa: E402

FAIL = []
BASE = os.path.join(ROOT, "output", "洪氏2")
SNAP_NEW = os.path.join(BASE, "data", "snap_v116_207044_final.json")
SNAP_OLD = os.path.join(BASE, "data", "snap_v115_207044_final.json")
BACKUP = os.path.join(ROOT, "logs", "v116_prince_backup.json")
PAGE = os.path.join(BASE, "index.html")


def check(ok, label, detail=""):
    print(("  PASS " if ok else "  FAIL ") + label + (("  | " + str(detail)) if detail else ""))
    if not ok:
        FAIL.append(label)


class Stub(F.Facts):
    """`Facts` 壳：只喂进政体/独立性/卒档所需的字段，不载存档。"""

    def __init__(self, chars=None, vassal=None, gov_hist=None, melt_chars=None,
                 vassal_ids=None, title_gov="", char_gov=""):
        self.cache = {"characters": chars or {}, "player_id": 1,
                      "char_vassal_history": vassal or {},
                      "char_government_history": gov_hist or {},
                      "last_date": None}
        self.campaign = {}
        self.melt = {}
        self._chars = melt_chars or {}
        self.as_of = "1152.11.13"
        self._vassal_ids = set(vassal_ids or [])
        self._indep_cache = {}
        self._lt = {}
        self.table = L.table()
        self._title_gov_value = title_gov
        self._char_gov_value = char_gov

    # 只替换两个来源，复算链其余部分（_anchor_date/_is_independent/_vassal_history/
    # _death_liege/_prince_word 的键与文案）走生产代码
    def _title_government(self, tid, date=None):
        return self._title_gov_value

    def _gov_for_word(self, cid, tid, date):
        return self._char_gov_value


def char(cid, father=None, mother=None, death=None, female=False):
    fam = {}
    if father:
        fam["father"] = [father]
    if mother:
        fam["mother"] = [mother]
    return {"name_full": "x", "name_zh": "x", "female": female, "family": fam,
            "death": death or {}}


def layer_a():
    print("\n[A] 规则层")
    # 政体 × 封臣/独立 × 层级 → 词（游戏词表）
    cases = [
        ("kingdom", "celestial_government", False, False, "公子"),
        ("kingdom", "celestial_government", False, True, "公女"),
        ("kingdom", "celestial_government", True, False, "王子"),
        ("kingdom", "celestial_government", True, True, "郡主"),
        ("empire", "celestial_government", True, False, "皇子"),
        ("empire", "celestial_government", True, True, "皇女"),
        ("empire", "celestial_government", False, False, "公子"),
        ("empire", "celestial_government", False, True, "公女"),
        ("hegemon", "celestial_government", True, False, "皇子"),
        ("hegemon", "celestial_government", True, True, "皇女"),
        ("kingdom", "feudal_government", True, False, "王子"),
        ("kingdom", "feudal_government", True, True, "公主"),
        ("kingdom", "feudal_government", False, True, "公主"),
    ]
    for tier, gov, indep, female, want in cases:
        got = Stub()._prince_word(tier, gov, indep, female) or ""
        check(got == want, "%.6s %-22s 独立=%-5s 女=%-5s → %s" % (tier, gov, indep, female, want),
              "" if got == want else "got %r" % got)

    st = Stub(chars={"2": char(2, father=1)}, vassal={},
              melt_chars={"1": {"dead_data": {"date": "973.3.28", "liege": 9}}})
    check(st._death_liege(1) == 9 and st._death_liege(2) is None,
          "卒档 liege：有卒于缓存者读出（9）、无卒档者取不到",
          "%r / %r" % (st._death_liege(1), st._death_liege(2)))
    # 卒档 liege：他人 = 封臣；本人 = 独立
    check(Stub(chars={"1": char(1, death={"date": "973.3.28", "liege": 9})})
          ._parent_child_independent(1, None) is False, "卒档 liege=他人 → 封臣")
    check(Stub(chars={"1": char(1, death={"date": "973.3.28", "liege": 1})})
          ._parent_child_independent(1, None) is True, "卒档 liege=本人 → 独立")
    # 无封臣史、无卒档 → 维持旧口径（活人按末档封臣集）
    check(Stub(chars={"1": char(1)})._parent_child_independent(1, None) is True,
          "无史无卒档 → 独立（末档封臣集里没有）")
    check(Stub(chars={"1": char(1)}, vassal_ids=[1])._parent_child_independent(1, None) is False,
          "无史无卒档 → 末档封臣集里有时为封臣")
    # 卒后那条 liege=None 不再答话：卒 1147.3.17，1129 封臣，1148 无主
    v = {"1": [{"date": "1129.1.1", "liege": 9, "flags": []},
               {"date": "1148.1.1", "liege": None, "flags": []}]}
    st = Stub(chars={"1": char(1, death={"date": "1147.3.17", "liege": 9})}, vassal=v)
    check(st._is_independent(1, "1152.11.13") is True, "（旧口径）卒后那条读作独立")
    check(st._parent_child_independent(1, "1152.11.13") is False,
          "（新口径）按卒日读 → 封臣")
    # 封臣史起点晚于查询日 → None → 用卒档
    st = Stub(chars={"1": char(1, death={"date": "1147.3.17", "liege": 9})},
              vassal={"1": [{"date": "1129.1.1", "liege": 9, "flags": []}]})
    check(st._is_independent(1, "1100.1.1") is None, "史起点之后无记录 → None")
    check(st._parent_child_independent(1, "1100.1.1") is False,
          "史覆盖不到 → 用卒档 liege → 封臣")
    # 政体加宽：标题侧有值就用；为空时只采纳行政制链的值
    st = Stub(chars={"1": char(1)}, title_gov="", char_gov="celestial_government")
    check(st._parent_child_government(1, 5, None, "") == "celestial_government",
          "标题侧取不到政体 → 采纳卒档/人物侧的 celestial_government")
    st = Stub(chars={"1": char(1)}, title_gov="", char_gov="feudal_government")
    check(st._parent_child_government(1, 5, None, "") == "",
          "标题侧取不到政体，人物侧是封建 → 不采纳（维持现口径）")
    st = Stub(chars={"1": char(1)}, title_gov="administrative_government", char_gov="")
    check(st._parent_child_government(1, 5, None, "administrative_government")
          == "administrative_government", "标题侧有值时原样返回（日期准确）")


def gen_lines(path):
    d = json.load(io.open(path, encoding="utf-8"))
    return d["facts"].get("genealogy") or []


def layer_b():
    print("\n[B] 快照层（世系行）")
    if not os.path.exists(SNAP_NEW):
        check(False, "v116 快照存在（先跑 snap.py）", SNAP_NEW)
        return
    new = gen_lines(SNAP_NEW)
    old = gen_lines(SNAP_OLD) if os.path.exists(SNAP_OLD) else []
    text = "\n".join(new)
    check("**山南公子洪审礼**" in text, "山南王子洪审礼 → 山南公子洪审礼")
    check("山南王子" not in text and "山南郡主" not in text,
          "世系再无 山南王子/山南郡主")
    check("山南公女洪慈顺" in text, "山南郡主 → 山南公女")
    check("山南观察使谦卑者圣洪仁德" in text, "父自身官职词不变（山南观察使）")
    check("天皇子洪仁义" in text and "天王子" not in text, "天王子 → 天皇子")
    check("天皇女洪天姣" in text and "天公主" not in text, "天公主 → 天皇女")
    check("唐皇女李星雁" in text and "唐公主" not in text, "唐公主 → 唐皇女（独立君主支）")
    check("代北公女洪地香" in text, "代北公主 → 代北公女（封臣支）")
    check("岭南公女袁菊芳" in text, "岭南郡主 → 岭南公女（封臣支）")
    if old:
        diff = [i for i, (x, y) in enumerate(zip(old, new)) if x != y]
        check(len(old) == len(new), "世系行数不变（版式未动）", "%d→%d" % (len(old), len(new)))
        check(0 < len(diff) <= 20, "改动只落在称号词上（行数有限）", "%d 行" % len(diff))
        # 行内其余字符必须逐字相同：用手术备份的映射把旧行变换过去，应当等于新行
        mp = {}
        if os.path.exists(BACKUP):
            mp = json.load(io.open(BACKUP, encoding="utf-8")).get("map") or {}
        check(bool(mp), "手术备份里有映射表（改动可解释）", "%d 串" % len(mp))
        bad = []
        for i in diff:
            a, b = old[i], new[i]
            for x, y in mp.items():
                a = a.replace(x, y)
            if a != b:
                bad.append((old[i], new[i]))
        check(not bad, "改动仅为称号词（其余逐字相同）", bad[:2])


def layer_c():
    print("\n[C] 成稿层（逐串替换）")
    files = [fn for fn in sorted(os.listdir(BASE))
             if fn.endswith(".md") and ".bak" not in fn]
    joined = {}
    for fn in files:
        joined[fn] = io.open(os.path.join(BASE, fn), encoding="utf-8").read()
    allt = "\n".join(joined.values())
    check("山南王子" not in allt and "山南郡主" not in allt,
          "洪氏2 成稿里再无 山南王子/山南郡主")
    check("山南公子洪审礼" in allt, "成稿里出现 山南公子洪审礼")
    check("山南观察使谦卑者圣洪仁德" in allt, "父自身写法未被误改")
    check("天王子洪仁义" not in allt, "成稿里再无 天王子")
    # 「时尚王子」是绰号，不是称号词 → 不参与替换
    check("时尚王子" in allt, "绰号「时尚王子」保留（不是称号词）")
    if os.path.exists(BACKUP):
        bk = json.load(io.open(BACKUP, encoding="utf-8"))
        hits = bk.get("files") or {}
        n = sum(h[2] for hs in hits.values() for h in hs)
        check(bool(hits) and n > 0, "备份里有替换记录", "%d 篇 / %d 处" % (len(hits), n))
        # 每一条替换的「新串」都必须在对应文件里出现
        miss = []
        for fn, hs in hits.items():
            for a, b, k in hs:
                if b not in joined.get(fn, ""):
                    miss.append((fn, a, b))
        check(not miss, "所有替换都落在文件里", miss[:2])
    else:
        check(False, "备份文件存在（先 --apply）", BACKUP)


def layer_page():
    print("\n[D] 阅读页")
    if not os.path.exists(PAGE):
        check(False, "index.html 存在（先 rebuild）", PAGE)
        return
    html = io.open(PAGE, encoding="utf-8").read()
    check("山南公子" in html, "阅读页含 山南公子")
    check("山南王子" not in html, "阅读页不含 山南王子")


def main():
    layer_a()
    layer_b()
    layer_c()
    if "--page" in sys.argv:
        layer_page()
    print("\n%s（%d 项未过）" % ("全部通过" if not FAIL else "有未过项", len(FAIL)))
    for x in FAIL:
        print("  - %s" % x)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
