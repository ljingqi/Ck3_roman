# -*- coding: utf-8 -*-
"""v94 回归 (秒级; 不载熔件): 战事句措辞 / 信仰沿革承前 / 对立教宗识别。

用法: & tools\\py.ps1 tools\\tests\\verify_v94.py [快照...]

用户 2026-10-02 四问:
  1 「唐重光以民粹叛乱来攻，天贵福应战，目标为牂牁镇」不文不白 —— 根因在
    `facts._war_start_clause`: 防御战把目标写成句末公文体谓语小句「目标为X」,
    且「来攻」一词本身混用 (盟友来犯 / 主谓倒装); 进攻战在 claimant 与
    war_title 同在时同句点两次目标。修法: 目标改动词短语「兵锋向X」、
    「来攻」改「兴兵」、进攻战删重复句; 并给索取宣称者补亲缘定语。
  2 传记写「885年至893年信天主教拜上帝会」—— 根因在 `Facts.conversion_points`:
    改礼记忆 (converted_rite_memory) 只带 new_rite, 旧稿用**熔件当时**的
    礼仪→信仰挂靠反查; 而礼仪 154 在 929 年从信仰 12 划到 13 (929 年前是
    迦克墩基督教)。修法: 只给 new_rite 的点**承前**取最近的已知信仰。
  3 「为前礼部尚书书吏洪地保索取日本帝国的宣称」—— 对立教宗 (religious head
    challenger) 在事实层零留痕, 故 `official_title` 落到「前朝廷职司」兜底,
    且战事行未经 `name_index` 登记、亲缘定语无从插入。修法: 认头衔变量
    `pam_antipope_office` + 信仰 challenger 列表, 称谓写「X对立教宗」,
    索取宣称者补亲缘定语。
  4 《礼仪志》无宗教领袖 (对立方) —— 同 3 的根因: 旧稿只认 `head_of_rite`;
    修法: `rite_profile_lines` 加「对立教宗」行 (在位者 + 扶立者)。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F  # noqa: E402

_OK = True


def check(name, cond, detail=""):
    global _OK
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (("  — " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _OK = False


# ---------------------------------------------------------------------------
# 一、战事句 (纯函数替身)
# ---------------------------------------------------------------------------
class _WarStub:
    """`_war_start_clause` / `_pair_war_events` 的最小替身。"""

    def __init__(self, kin=""):
        self._kin = kin

    def event_name(self, cid, date=None):
        return {1: "堕邪者洪天贵福", 2: "农民起义领袖唐重光",
                3: "关白源贞", 4: "前礼部尚书书吏洪地保",
                5: "枢密使李萨钦", 6: "民粹暴动领袖苗镠"}.get(cid, "")

    def title(self, tid, date=None, **kw):
        return {15261: "牂牁镇", 13265: "日本帝国"}.get(tid, "")

    def blood_kin_word_for(self, cid, subject):
        return self._kin

    def index_names(self, text, log, owner=None):
        return text


def _ev(t, owner, other=None, **war):
    """战事事件桩: `_war_slots` 读 ident.parts.other_party + ident.war.{cb,title,claimant}。"""
    ident = {"owner": owner}
    if other is not None:
        ident["parts"] = {"other_party": other}
    if war:
        ident["war"] = dict(war)
    return {"type": t, "date": "933.9.16", "ident": ident}


def war_checks():
    print("\n[一] 战事句 (v94 问题1 + 3)")
    f = _WarStub(kin="外甥")
    # 本地化表替身: 战名只测取词通道, 不载真表
    _CB = {"war_memory_cb_populist": "民粹叛乱", "war_memory_cb_claim": "宣称战争"}
    _real_loc = F.L.loc
    F.L.loc = lambda table, key, *a, **k: _CB.get(key, _real_loc(table, key, *a, **k))
    try:
        _war_checks_body(f)
    finally:
        F.L.loc = _real_loc


def _war_checks_body(f):

    # 防御战: 目标改「兵锋向」, 「来攻」改「兴兵」
    got = F._war_start_clause(
        f, _ev("defensive_war", 1, 2, cb="war_memory_cb_populist", title=15261),
        dict(atk=2, dfd=1, cb="war_memory_cb_populist", title=15261))
    check("U1a 防御战: 兴兵 + 应战 + 兵锋向目标",
          got == "农民起义领袖唐重光以民粹叛乱兴兵，堕邪者洪天贵福应战，兵锋向牂牁镇",
          got)
    check("U1b 防御战句面已无「目标为」与「来攻」",
          "目标为" not in got and "来攻" not in got, got)

    # 防御战无目标
    got2 = F._war_start_clause(
        f, _ev("defensive_war", 1, 2, cb="war_memory_cb_populist"),
        dict(atk=2, dfd=1, cb="war_memory_cb_populist", title=None))
    check("U1c 防御战无目标时不追加空小句",
          got2 == "农民起义领袖唐重光以民粹叛乱兴兵，堕邪者洪天贵福应战", got2)

    # 进攻战: claimant 与 war_title 同在 → 只点一次目标 + 亲缘定语
    got3 = F._war_start_clause(
        f, _ev("offensive_war", 1, 3, cb="war_memory_cb_claim", title=13265,
               claimant=4, attacker=1),
        dict(atk=1, dfd=3, cb="war_memory_cb_claim", title=13265, claimant=4))
    check("U1d 进攻战: 索取宣称者带亲缘定语, 目标只点一次",
          got3 == "堕邪者洪天贵福以宣称战争向关白源贞开战，"
                  "为外甥前礼部尚书书吏洪地保索取日本帝国的宣称", got3)
    check("U1e 进攻战句面已无重复的「目标是」",
          "目标是" not in got3, got3)

    # 进攻战无 claimant → 保留「目标是」
    got4 = F._war_start_clause(
        f, _ev("offensive_war", 1, 3, cb="war_memory_cb_claim", title=13265,
               attacker=1),
        dict(atk=1, dfd=3, cb="war_memory_cb_claim", title=13265, claimant=None))
    check("U1f 进攻战无宣称者时仍写目标",
          got4 == "堕邪者洪天贵福以宣称战争向关白源贞开战，目标是日本帝国", got4)

    # 宣称为己 (claimant == owner) → 与旧口径一致: 走「目标是」
    got5 = F._war_start_clause(
        f, _ev("offensive_war", 1, 3, cb="war_memory_cb_claim", title=13265,
               claimant=1, attacker=1),
        dict(atk=1, dfd=3, cb="war_memory_cb_claim", title=13265, claimant=1))
    check("U1g 宣称者即兴兵方时退回「目标是」",
          got5 == "堕邪者洪天贵福以宣称战争向关白源贞开战，目标是日本帝国", got5)

    # 无亲缘可判 → 退回平称, 不写空定语
    g = F._war_start_clause(
        _WarStub(kin=""),
        _ev("offensive_war", 1, 3, cb="war_memory_cb_claim", title=13265,
            claimant=4, attacker=1),
        dict(atk=1, dfd=3, cb="war_memory_cb_claim", title=13265, claimant=4))
    check("U1h 判不出亲缘时不加定语",
          g.endswith("为前礼部尚书书吏洪地保索取日本帝国的宣称"), g)

    # 盟战保留原样
    got6 = F._war_start_clause(
        f, _ev("joined_allys_war", 5, 2, cb="war_memory_cb_populist", ally=1),
        dict(ally=1, enemy=2, atk=2, dfd=1, cb="war_memory_cb_populist"))
    check("U1i 盟战句面不动",
          got6 == "枢密使李萨钦随堕邪者洪天贵福出战，对抗农民起义领袖唐重光，此役为民粹叛乱",
          got6)


# ---------------------------------------------------------------------------
# 二、信仰沿革承前 (缓存桩, 不载熔件)
# ---------------------------------------------------------------------------
def _melt_stub():
    """最小熔件形状: 礼仪 154 在**当下**已划归信仰 13 (天主教) —— 正是问题 2 的陷阱。"""
    return {
        "landed_titles": {"landed_titles": {}},
        "faiths": {"database": {
            "12": {"name": "迦克墩基督教"},
            "13": {"name": "天主教"},
            "31": {"name": "儒家"},
        }},
        "rites": {"database": {
            "154": {"faith": 13, "data": {"name": "拜上帝会"}},
            "32": {"faith": 31, "data": {"name": "经学"}},
        }},
    }


def faith_checks():
    print("\n[二] 信仰沿革 (v94 问题2)")
    # 缓存: 905 起信仰 12, 929 起信仰 13; 885 有一条只带 new_rite 的改礼记忆
    cache = {"characters": {"900": {
        "faith": 13, "rite": 154,
        "faith_history": [{"from": "905.1.1", "faith": 12},
                          {"from": "929.1.1", "faith": 13}],
        "rite_history": [{"from": "905.1.1", "rite": 154}],
        "memories": [
            {"type": "converted_rite_memory", "creation_date": "885.6.4",
             "vars": [{"flag": "new_rite", "identity": 154},
                      {"flag": "old_rite", "identity": None}]},
            {"type": "converted_faith_memory", "creation_date": "894.7.21",
             "vars": [{"flag": "new_faith", "identity": 31},
                      {"flag": "new_rite", "identity": 32},
                      {"flag": "old_faith", "identity": 12}]},
            {"type": "converted_faith_memory", "creation_date": "895.5.27",
             "vars": [{"flag": "new_faith", "identity": 12},
                      {"flag": "new_rite", "identity": 154},
                      {"flag": "old_faith", "identity": 31}]},
        ],
    }}}
    f = F.Facts(cache, _melt_stub(), None, as_of="935.1.1", decade=3)
    cp = f.conversion_points(900)
    check("U2a 只带 new_rite 的记忆点承前取信仰 (885 → 12, 不按当下的 13)",
          cp.get("885.6.4") == (12, 154), cp)
    check("U2b 改信记忆点的信仰不变 (894 → 31)",
          cp.get("894.7.21") == (31, 32), cp)
    check("U2c 复归点取显式 new_faith (895 → 12)",
          cp.get("895.5.27") == (12, 154), cp)
    pts = f.faith_rite_history(900)
    check("U2d 沿革首段写迦克墩基督教拜上帝会 (不是天主教)",
          pts and pts[0] == ("885.6.4", 12, 154), pts)
    rows = f.faith_history_lines(900)
    check("U2e 履历首段 = 「885年至893年信迦克墩基督教拜上帝会」",
          rows and rows[0] == "885年至893年信迦克墩基督教拜上帝会", rows)
    # 最早一点之前的日期: 缓存沿革首点 12 优先于礼仪当下的挂靠 13
    check("U2f 早于缓存首点时取沿革首点 (12), 不取礼仪当下的挂靠",
          f._faith_id(900, "880.1.1") == 12, f._faith_id(900, "880.1.1"))
    check("U2g 窗口内仍按日取沿革值 (930 → 13)",
          f._faith_id(900, "930.1.1") == 13, f._faith_id(900, "930.1.1"))


# ---------------------------------------------------------------------------
# 三、对立教宗识别 (熔件桩, 不载熔件)
# ---------------------------------------------------------------------------
def _antipope_melt():
    """最小熔件: 头衔 20392 = 对立教宗职位 (变量 pam_antipope_office), 名「京兆教廷」;
    33611550 自 929.4.23 在位, 935.8.1 另获 e_japan (「日本帝国」); 赞助者头衔
    h_china (14022) 的持有者是主角 44503。"""
    return {
        "landed_titles": {"landed_titles": {
            "20392": {"key": "x_script_3930", "landless": True, "capital": 14426,
                      "title_name_data": {"name": "京兆教廷"},
                      "variables": {"data": [{"flag": "pam_antipope_office"}]},
                      "history": {"929.4.23": {"type": "created",
                                               "holder": 33611550}}},
            "14426": {"key": "c_jingzhao",
                      "title_name_data": {"name": "京兆"}},
            "13265": {"key": "e_japan", "holder": 33611550,
                      "title_name_data": {"name": "日本",
                                          "title_history_names": [
                                              {"date": "500.1.1",
                                               "name": "e_japan"}]},
                      "history": {"935.8.1": {"type": "conquest_claim",
                                              "holder": 33611550}}},
            "14022": {"key": "h_china", "holder": 44503,
                      "history": {"897.6.5": {"type": "created",
                                              "holder": 44503}}},
            "15261": {"key": "c_zangke", "holder": 2},
        }},
        "faiths": {"database": {
            "13": {"name": "天主教", "religious_head_challengers": [
                {"religious_head_challenger": 20392, "sponsor": 14022}]},
            "12": {"name": "迦克墩基督教"},
        }},
        "rites": {"database": {
            "154": {"faith": 13, "head_of_rite": 16847791,
                    "data": {"name": "拜上帝会"}},
            "158": {"faith": 12, "head_of_rite": 4294967295,
                    "data": {"name": "迦克墩基督教"}},
        }},
    }


_ANT_CACHE = {"player_id": 44503, "characters": {
    "44503": {"faith": 13, "rite": 154, "name_zh": "天贵福",
              "faith_history": [{"from": "905.1.1", "faith": 12},
                                {"from": "929.1.1", "faith": 13}],
              "rite_history": [{"from": "905.1.1", "rite": 154}]},
    "33611550": {"faith": 13, "rite": 154, "name_zh": "地保"},
    "16847791": {"faith": 13, "rite": 154},
}}


def antipope_checks():
    print("\n[三] 对立教宗 (v94 问题3/4)")
    f = F.Facts(_ANT_CACHE, _antipope_melt(), None, as_of="935.1.1", decade=3)
    # 职位集合与在位判定 (含 as_of 截断)
    check("U3a 头衔变量认出对立教宗职位",
          20392 in f._antipope_office_ids(), f._antipope_office_ids())
    check("U3b 在任判定: 933 在位, 929.4.22 未立",
          f.antipope_office_at(33611550, "933.9.16") == 20392
          and f.antipope_office_at(33611550, "929.4.22") is None,
          (f.antipope_office_at(33611550, "933.9.16"),
           f.antipope_office_at(33611550, "929.4.22")))
    check("U3c 非对立教宗者为 None",
          f.antipope_office_at(44503, "933.9.16") is None
          and f.antipope_office_at(16847791, "933.9.16") is None)
    # 称谓: 无更高头衔时取职位所在地 (京兆), 获 e_japan 后取日本
    check("U3d 无更高头衔时定位词取职位所在地 (京兆对立教宗)",
          f.antipope_label(33611550, "933.9.16") == "京兆对立教宗",
          f.antipope_label(33611550, "933.9.16"))
    # 高头衔裸名取词: e_japan 的静态名带层级词 (「日本帝国」), 定位词要裸名 (「日本」);
    # as_of 截断后 (本篇 935.1.1) 该头衔是**篇后**所得, 不进本篇 —— 故此处只证取词口
    check("U3e 高头衔定位词取裸名 (e_japan → 日本)",
          f._title_short_name(13265, "936.1.1") == "日本",
          f._title_short_name(13265, "936.1.1"))
    check("U3e2 as_of 之后的头衔不进本篇 (_hold_intervals 已截断)",
          13265 not in f._hold_intervals(33611550, "933.9.16"),
          sorted(f._hold_intervals(33611550, "933.9.16")))
    check("U3e3 对立教宗职位头衔裸名去掉「教廷」尾词 (京兆教廷 → 京兆)",
          f._title_short_name(20392, "933.9.16") == "京兆",
          f._title_short_name(20392, "933.9.16"))
    check("U3f 非对立教宗者无比称谓",
          f.antipope_label(44503, "933.9.16") == "",
          f.antipope_label(44503, "933.9.16"))
    # 官称出口: 通用口只给概念原词 (不带定位前缀)
    check("U3g religious_head_word 认对立教宗 (概念原词)",
          f.religious_head_word(33611550) == "对立教宗",
          f.religious_head_word(33611550))
    check("U3h 非对立教宗者 religious_head_word 仍为 ''",
          f.religious_head_word(44503) == ""
          and f.religious_head_word(16847791) == "",
          (f.religious_head_word(44503), f.religious_head_word(16847791)))
    check("U3i official_title 走对立教宗, 不再落到「前朝廷职司」",
          f.official_title(33611550, "933.9.16") == "对立教宗",
          f.official_title(33611550, "933.9.16"))
    # 索取宣称者名 (年表用: 完整称谓带定位前缀)
    check("U3j event_name 出「京兆对立教宗」",
          f.event_name(33611550, "933.9.16") == "京兆对立教宗地保",
          f.event_name(33611550, "933.9.16"))
    # 《礼仪志》对立方之首
    lines = f.antipope_lines(44503, "935.1.1")
    check("U4a 礼仪志补出对立教宗行 (含在位日与扶立者)",
          len(lines) == 1 and lines[0].startswith("对立教宗：京兆对立教宗")
          and "929.4.23起" in lines[0] and "扶立" in lines[0], lines)
    check("U4b as_of 早于对立教宗在任日时不出行",
          f.antipope_lines(44503, "929.4.22") == [],
          f.antipope_lines(44503, "929.4.22"))
    # 反向: 礼仪档案仍写正统之首 (对立行只是补出, 不顶替)
    prof = f.rite_profile_lines(44503, "935.1.1")
    check("U4c 礼仪档案仍有「礼仪领袖」行 (正统之首不被顶替)",
          any(x.startswith("礼仪领袖：") for x in prof), prof)
    check("U4d 礼仪档案含「对立教宗」行",
          any(x.startswith("对立教宗：") for x in prof), prof)


def main():
    war_checks()
    faith_checks()
    antipope_checks()
    print("\n" + ("全部通过" if _OK else "**有 FAIL**"))
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
