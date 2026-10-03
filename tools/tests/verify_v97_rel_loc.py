# -*- coding: utf-8 -*-
"""v97 单测：关系缘由模板的占位符替换（纯函数，秒级，不碰熔件）。

校验 `facts._sub_relation_loc` 对每一类被保留的标签都能取值，且**绝不**把 `[...]` 漏出去；
取不到值时整句丢弃（返回 ''）而不是留洞。

用法：& tools\\py.ps1 tools\\tests\\verify_v97_rel_loc.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import facts as F          # noqa: E402
import localization as L   # noqa: E402

OK = True


def check(name, cond, extra=None):
    global OK
    if not cond:
        OK = False
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f"   ← {extra!r}" if extra is not None else ""))


def _real_table():
    """真实本地化表（17 万键）：概念/活动/语言名都靠它，替身不能空着。"""
    with open(os.path.join(ROOT, "data", "localization.json"), encoding="utf-8") as fp:
        return json.load(fp)["table"]


class Stub:
    """最小 Facts 替身：只提供 _sub_relation_loc 会碰到的出口。"""

    def __init__(self):
        self.as_of = "963.1.1"
        self.cache = {"characters": {
            "11": {"name_zh": "思忠", "death": {"reason": "death_murder"}},
            "22": {"name_zh": "处恭"},
            "33": {"name_zh": "翊", "death": {"reason": "death_execution"}},
        }}
        self._chars = {}
        self.melt = {"dynasties": {"dynasty_house": {"7": {"localized_name": "洪"}}}}
        self.table = _real_table()
        self.title_table = {"e_latin_empire": 1234}

    def name_or(self, cid, fallback="某人", date=None):
        return {11: "尼各老", 22: "阮处恭", 33: "洪翊"}.get(cid, fallback)

    def _is_female(self, cid):
        return False

    def _house_of_cid(self, cid):
        return 7

    def person_label(self, cid, date=None, style="brief"):
        return {11: "教宗尼各老", 22: "刺史阮处恭", 33: "洪翊"}.get(cid, "")

    def faith(self, cid, date=None):
        return "天主教拜上帝会"

    def culture_template(self, cid):
        return "han"

    def _culture_language_id(self, cid, date=None):
        return "language_chinese"

    def title_by_key(self, key):
        return self.title_table.get(key)

    def title(self, tid, date=None):
        return "拉丁帝国" if tid == 1234 else ""

    def _json_safe(self):
        return None


def main():
    f = Stub()
    tpl = L.relation_templates()

    print("[1] 姓名/第三人")
    s = tpl.get("rival_house_feud_vengeance")
    out = F._sub_relation_loc(f, s, 22, 11, extra=33)
    check("第三人全名 GetUIName 换成真名", "洪翊" in out, out)
    check("无 [ ] 残留", "[" not in out and "]" not in out, out)
    out0 = F._sub_relation_loc(f, s, 22, 11, extra=None)
    check("第三人缺失 → 整句丢弃", out0 == "", out0)

    print("[2] 死法/信仰/语言/教义/活动")
    for key, want in (("rival_killed_heir", "处决"),
                      ("rival_ruined_notes", "天主教拜上帝会"),
                      ("lover_language", "汉语"),
                      ("friend_learned_my_language", "院校访学"),
                      ("nemesis_killed_family", "家族"),
                      ("rival_generic_coerced_with_strong_hook", "强牵制"),
                      ("rival_rejected_culture_influence", "汉"),
                      ("rival_house_feud_vengeance", "洪"),
                      ("rival_latin_emp_refused_alliance_corresponding", "拉丁帝国")):
        s = tpl.get(key)
        if not s:
            check(f"{key} 模板存在", False)
            continue
        out = F._sub_relation_loc(f, s, 22, 11, extra=33)
        check(f"{key} 无 [ ] 残留", "[" not in out and "]" not in out, out)
        if want:
            check(f"{key} 含 {want}", want in out, out)

    print("[3] 性别/亲属词")
    out = F._sub_relation_loc(f, "[CHARACTER.GetWifeHusband]与[TARGET_CHARACTER.GetMotherFather]",
                              22, 11)
    check("妻/夫 与 母/父", out == "夫与父", out)
    out = F._sub_relation_loc(
        f, "[CHARACTER.GetHerselfHimself]与[TARGET_CHARACTER.GetWomanMan]"
           "及[TARGET_CHARACTER_2.Custom('GetDaughterSon')]", 22, 11, extra=33)
    check("她自己/女/儿子", out == "他自己与男及儿子", out)
    out = F._sub_relation_loc(f, "[CHARACTER.GetFirstName]的[TARGET_CHARACTER.GetFirstName]",
                              22, 11)
    check("本名（不含姓）", out == "处恭的思忠", out)

    print("[4] 取值失败 → 丢句（不发明）")
    class NoData(Stub):
        def faith(self, cid, date=None):
            return ""
    out = F._sub_relation_loc(NoData(), tpl.get("rival_ruined_notes"), 22, 11, extra=33)
    check("信仰取不到 → 返回空串", out == "", out)

    print("[5] 教义/特质（GetTrait 无角色前缀）")
    out = F._sub_relation_loc(f, "[CHARACTER.GetUIName]被[GetTrait('faith_warrior').GetName( CHARACTER )]"
                                 "感召", 22, 11)
    check("特质名取到且无残留", out and "[" not in out and "信" in out, out)

    print("\n" + ("ALL OK" if OK else "HAS FAILURES"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
