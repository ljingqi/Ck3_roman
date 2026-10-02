# -*- coding: utf-8 -*-
"""v92 回归 (秒级; 不载熔件): 洪天美双重亲属 / 入赘婚动词 / 隐事谓语句 / 结仇之由。

用法: & tools\\py.ps1 tools\\tests\\verify_v92.py [快照...]
      缺省取 output/洪氏2/data/snap_v92_gf_d1.json, 回退 snap_v91_gf_d1.json

用户 2026-10-02 四条:
  1 洪天美的亲属关系乱了 —— 存档里她既是传主之妾 (`concubinist` 指针) 又是其
    外甥女 (母洪天姣 = 传主之姊妹); 事实面只写位分, 模型遂写「贵福之姊妹行」
    「外姐姐」与「终生未嫁」。修法: 双重亲属**血缘优先**, 本人档案另补位分行。
  2 入赘婚短语太长 —— 旧「X与Y成婚，是入赘婚。」改作动词「X与Y结入赘婚。」;
    无动词的名单行压到「，入赘」。
  3 隐事要写成「谁做了什么」—— `secret_exam_cheater` 归谓语型:
    「崔穆在天皇帝穿刺者洪秀全主持的乡试中舞弊。」
  4 结仇之由「本传不详」—— 游戏 `scripted_relations.reason` 一直在档
    (`rival_opposed_coronation_openly`), 只是年表没读; 现按日补一行缘由事。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F        # noqa: E402
import style as S        # noqa: E402

_OK = True


def check(name, cond, detail=""):
    global _OK
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (("  — " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _OK = False


# ---------------------------------------------------------------------------
# 一、纯函数
# ---------------------------------------------------------------------------
class _MatriStub:
    """只测 `marriage_verb` / `marriage_lineality_note` 的分支 → 桩掉判据。"""

    def __init__(self, matri):
        self._m = matri

    def wedding_date(self, a, b):
        return ""

    def is_matrilineal(self, a, b, after=None, before=None):
        return self._m


def unit_checks():
    print("\n[一] 纯函数")
    st = _MatriStub(True)
    check("U1a 母系婚动词 = 结入赘婚",
          F.Facts.marriage_verb(st, 1, 2) == "结入赘婚")
    check("U1b 母系婚名单补注 = 「，入赘」(不含「是入赘婚」)",
          F.Facts.marriage_lineality_note(st, 1, 2) == "，入赘",
          F.Facts.marriage_lineality_note(st, 1, 2))
    st2 = _MatriStub(False)
    check("U1c 普通婚动词 = 成婚", F.Facts.marriage_verb(st2, 1, 2) == "成婚")
    check("U1d 普通婚无补注", F.Facts.marriage_lineality_note(st2, 1, 2) == "")

    check("U2a 血亲键判据: 外甥女 = 血亲",
          F.kin_key_is_blood("niece_sister"))
    check("U2b 血亲键判据: 继母/妻子/女婿 = 非血亲",
          not any(F.kin_key_is_blood(k) for k in
                  ("wife", "husband", "step_son", "son_in_law",
                   "brother_in_law_older")))
    check("U2c 空键不算血亲", not F.kin_key_is_blood(""))

    check("U3a 科举舞弊 = 谓语型 (直写谁做了什么)",
          S.secret_topic_is_predicate("secret_exam_cheater"))
    check("U3b 血统类仍走「有隐事」框架",
          not S.secret_topic_is_predicate("secret_disputed_heritage"))

    # 双重亲属: 2 是主角 1 的外甥女 (母 3 = 1 的姊妹), 又被 1 纳为妾;
    # 5 = 3 的丈夫 (主角的妹夫/姐夫 = 姻亲, 非血亲)
    recs = {
        "1": {"id": 1, "name_full": "洪天贵福", "name_zh": "天贵福",
              "first_name": "天贵福", "female": False,
              "family": {"siblings": [3], "concubine": [2]}},
        "2": {"id": 2, "name_full": "洪天美", "name_zh": "天美",
              "first_name": "天美", "female": True,
              "family": {"father": [9], "mother": [3]}},
        "3": {"id": 3, "name_full": "洪天姣", "name_zh": "天姣",
              "first_name": "天姣", "female": True,
              "family": {"siblings": [1], "father": [8], "primary_spouse": [5]}},
        "5": {"id": 5, "name_full": "崔舣", "name_zh": "舣",
              "first_name": "舣", "female": False,
              "family": {"spouse": [3]}},
        "8": {"id": 8, "name_full": "洪秀全", "name_zh": "秀全",
              "first_name": "秀全", "female": False, "family": {"child": [1, 3]}},
        "9": {"id": 9, "name_full": "崔公", "name_zh": "崔公",
              "first_name": "崔公", "female": False, "family": {}},
    }
    f = F.Facts.__new__(F.Facts)
    f.cache = {"player_id": 1, "characters": recs}
    f.melt = {}
    f.table = {}
    f._label_cache = {}
    f._name_cache = {}
    f.names_path = ""
    f._chars = {}
    f.as_of = "915.1.1"
    # 姓名渲染链要整条初始化才能真正出词 —— 本项只验位分行的**组合逻辑**,
    # 故把传主称谓固定 (真档上的称谓由快照断言 S3 覆盖)。
    f.kin_label = lambda cid, date=None: "洪天贵福"
    check("U4a 双重亲属 (妾 + 甥女) 的血缘词 = 外甥女",
          f.blood_kin_word_for(2, 1) == "外甥女",
          f.blood_kin_word_for(2, 1))
    check("U4b 姻亲 (妹夫) 不算血亲, 无血亲词可出",
          f.blood_kin_word_for(5, 1) == "", f.blood_kin_word_for(5, 1))
    check("U4c 普通亲属不受影响 (姊妹仍是姊妹)",
          f.blood_kin_word_for(3, 1) == "姊妹", f.blood_kin_word_for(3, 1))
    ln = f.consort_of_line(2)
    check("U4d 位分行血缘优先", "外甥女" in ln and "妾" in ln, ln)
    check("U4e 位分行不含「终生未嫁」这类否定", "未嫁" not in ln, ln)


# ---------------------------------------------------------------------------
# 二、快照 (事实面)
# ---------------------------------------------------------------------------
def snap_checks(path):
    print(f"\n[二] 快照 {os.path.basename(path)}")
    d = json.load(open(path, encoding="utf-8"))
    blocks = d.get("blocks") or {}
    msgs = d.get("messages") or {}
    blob = json.dumps([blocks, msgs, d.get("facts")], ensure_ascii=False)

    check("S1 全篇无「是入赘婚」(旧短语已撤)",
          "是入赘婚" not in blob)
    check("S2 有「结入赘婚」(母系婚作动词)", "结入赘婚" in blob)

    def _lines(section, sub=None):
        out = []
        for bk, bv in blocks.items():
            if bk != section:
                continue
            for sk, sv in (bv or {}).items():
                if sub and sub not in sk:
                    continue
                out.extend(sv if isinstance(sv, list) else [sv])
        return out

    # 1 洪天美: 传主档案的妾行补血缘; 本人档案补位分行
    lead = "\n".join(_lines("jiashi_lead"))
    check("S3a 传主档案妾行标出洪天美的血缘",
          "洪天美，本为其外甥女" in lead,
          [x for x in _lines("jiashi_lead") if "洪天美" in x][:1])
    check("S3b 家室档案有洪天美位分行 (血缘优先)",
          any("洪天美" in x and "外甥女" in x and "妾" in x
              for x in _lines("jiashi_lead") + _lines("jiashi_mid1")),
          [x for x in _lines("jiashi_lead") if "洪天美" in x][:1])

    # 3 隐事谓语句
    secl = "\n".join(_lines("secrets_lead") + _lines("secrets_mid"))
    check("S4a 科举舞弊写成「谁做了什么」",
          "崔穆在天皇帝穿刺者洪秀全主持的乡试中舞弊" in secl,
          [x for x in secl.split("\n") if "崔穆" in x][:2])
    check("S4b 不再套「有隐事：…乡试中舞弊」",
          "有一桩隐事：在" not in secl)

    # 4 结仇之由并进结仇行
    bm_lines = "\n".join(_lines("benji_mid")).split("\n")
    bm = "\n".join(bm_lines)
    check("S5a 年表补出结仇之由 (加冕礼) 且同句点明结仇",
          any("强烈抵制" in x and "加冕礼" in x and "结仇" in x
              for x in bm_lines),
          [x for x in bm_lines if "抵制" in x][:2])
    check("S5b 缘由行不另起 (不出现只写缘由的孤行)",
          not any("强烈抵制" in x and "结仇" not in x for x in bm_lines))
    check("S5c 结仇计数未被缘由改写 (仍 2 次)",
          "结仇2次" in (d.get("facts", {}).get("decade_stats") or []),
          d.get("facts", {}).get("decade_stats"))
    check("S5d 年表条数未被缘由行顶掉 (仍 80 条)",
          len(d.get("facts", {}).get("timeline") or []) >= 80,
          len(d.get("facts", {}).get("timeline") or []))


def main():
    unit_checks()
    paths = sys.argv[1:]
    if not paths:
        for nm in ("snap_v92_gf_d1.json", "snap_v91_gf_d1.json"):
            p = os.path.join(ROOT, "output", "洪氏2", "data", nm)
            if os.path.exists(p):
                paths = [p]
                break
    for p in paths:
        if os.path.exists(p):
            snap_checks(p)
        else:
            check(f"快照存在: {p}", False)
    print("\n" + ("全部通过" if _OK else "**有 FAIL**"))
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
