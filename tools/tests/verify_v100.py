# -*- coding: utf-8 -*-
"""v100 专项断言（秒级；纯函数 + 快照/成稿，不载熔件）。

用户 2026-10-04 三问（洪氏2）：
  ① 官职与绰号之间的「，」回滚 —— 事实面回到「前礼部尚书书吏洪地保」
  ② 《礼仪志》第三板块由「纪事·大公会议与教宗诏书」取代「纪事·枢机团与教宗选举」：
     教会局面 / 大公会议 / 教宗诏书 / 大分裂 / 对立教宗 / 异端 / 新礼 + 本礼教义定夺 +
     本礼信条（禁忌）更替 + 大公教会地位（facts.church_chronicle，枢机团整块删除）
  ③ 伊斯兰氏族制国名改取**家族名**，并加政体门与头衔门 —— 行政制的 e_arabia 用头衔名
     「阿拉伯帝国」，不再写「哈希姆哈里发国」

断言：
  [1] 纯函数：realm_name 的两道门与家族名（含层级词）
  [2] 纯函数：新静态表（dynasty_named 政体 / 头衔冠名豁免 / 教义分组名）
  [3] 纯函数：house_realm_name_zh 的回落链（家族名 → 父家族 → 宗族）
  [4] 纯函数：_liyi_has_tail 只看 church_chronicle；板块名与题面
  [5] 纯函数：_liyi_req 的 tail 要求随教会素材生成，且无负向禁令词
  [6] 快照：① 顿号回滚；② 新板块事实行；③ 允许/禁止行且无 core 更替；
      ④ 无裸键/无标记/无括注；⑤ 无「哈希姆哈里发国」
  [7] 成稿：终传与三篇十年传的 md（存在则断言）

用法：
    & tools\\py.ps1 tools\\tests\\verify_v100.py [快照...]
    （缺省 output/洪氏2/data/snap_v100.json）
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl        # noqa: E402
import facts as F             # noqa: E402
import localization as L      # noqa: E402
import style as S             # noqa: E402
import biography as bio       # noqa: E402

OK = True
H2 = os.path.join(ROOT, "output", "洪氏2")
DEFAULT = [os.path.join(H2, "data", "snap_v100.json")]
NEG = re.compile(r"不要|请勿|禁止|避免|切勿|不得|严禁|不可|不再|勿")
BARE = re.compile(r"(?<![A-Za-z0-9_])(?:special_)?(?:tenet|doctrine)_[a-z0-9_]+")
MARK = re.compile(r"\[[^\]]{0,40}\]|\$[A-Za-z_]+\$")
PAREN = re.compile(r"（[^）]{1,24}）")
TAIL_KEYS = ("大公会议与教宗诏书", "枢机团与教宗选举")   # v100 后的板块键 / 旧板块键


def check(name, cond, extra=None):
    global OK
    if not cond:
        OK = False
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f"   <- {str(extra)[:300]!r}" if extra is not None and not cond else ""))


def surface_of(snap):
    parts = [json.dumps(snap.get("facts") or {}, ensure_ascii=False),
             json.dumps(snap.get("blocks") or {}, ensure_ascii=False),
             json.dumps(snap.get("shared") or {}, ensure_ascii=False)]
    for m in snap.get("messages") or []:
        parts.append(json.dumps(m, ensure_ascii=False))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# [1] realm_name：两道门 + 家族名
# ---------------------------------------------------------------------------
def _realm_stub(gov, key, **flags):
    f = F.Facts.__new__(F.Facts)
    f.as_of = "999.7.7"
    f._lt = {"1": {"key": key, "holder": 42}}
    f._title_government = lambda tid, date=None: gov
    f.is_islamic = lambda cid: flags.get("islamic", True)
    f.is_caliph = lambda cid: flags.get("caliph", True)
    f._realm_house_name = lambda cid: flags.get("house", "阿拔斯")
    return f


def unit_realm_name():
    print("\n[1] realm_name：政体门 / 头衔门 / 家族名 / 层级词")
    f = _realm_stub("clan_government", "e_test")
    check("氏族制 + 持哈里发位 + 帝国级 → 「阿拔斯哈里发国」",
          f.realm_name(1) == "阿拔斯哈里发国", f.realm_name(1))
    check("氏族制 + 王国级 → 「阿拔斯苏丹国」",
          _realm_stub("clan_government", "k_test", caliph=False).realm_name(1) == "阿拔斯苏丹国")
    check("氏族制 + 帝国级 + 非哈里发 → 「阿拔斯帝国」",
          _realm_stub("clan_government", "e_test", caliph=False).realm_name(1) == "阿拔斯帝国")
    check("行政制（e_arabia 本盘政体）→ '' 走头衔名「阿拉伯帝国」",
          _realm_stub("administrative_government", "e_test").realm_name(1) == "")
    check("游牧制 → ''（旧码专设的排除项由政体门接管）",
          _realm_stub("nomad_government", "e_test").realm_name(1) == "")
    check("头衔门：can_be_named_after_dynasty = no 的头衔 → ''",
          _realm_stub("clan_government", "h_dar_al_islam").realm_name(1) == "")
    check("非伊斯兰 → ''",
          _realm_stub("clan_government", "e_test", islamic=False).realm_name(1) == "")
    check("无家族名 → ''",
          _realm_stub("clan_government", "e_test", house="").realm_name(1) == "")
    check("非 k_/e_/h_ 层级 → ''",
          _realm_stub("clan_government", "d_test").realm_name(1) == "")


# ---------------------------------------------------------------------------
# [2] 新静态表
# ---------------------------------------------------------------------------
def unit_tables():
    print("\n[2] 新静态表（政体 / 头衔 / 教义分组）")
    for gov in ("feudal_government", "clan_government", "mandala_government"):
        check(f"政体门放行 {gov}", L.dynasty_named_government(gov) is True)
    for gov in ("administrative_government", "nomad_government", "celestial_government",
                "steppe_admin_government", "meritocratic_government", "tribal_government",
                "japan_administrative_government"):
        check(f"政体门拦下 {gov}", L.dynasty_named_government(gov) is False)
    check("头衔门：h_dar_al_islam", L.title_name_locked("h_dar_al_islam") is True)
    check("头衔门：d_sunni", L.title_name_locked("d_sunni") is True)
    check("头衔门：e_arabia 不在豁免表（由政体门拦下）",
          L.title_name_locked("e_arabia") is False)
    check("教义分组：血亲性关系",
          L.doctrine_group_key("doctrine_consanguinity_unrestricted") == "doctrine_consanguinity"
          and L.doctrine_group_key("doctrine_consanguinity_aunt_nephew_and_uncle_niece")
          == "doctrine_consanguinity")
    t = L.table()
    check("分组中文名 = 血亲性关系", L.loc(t, "doctrine_consanguinity_name") == "血亲性关系")
    check("信条描述名 = 无限制婚姻",
          L.loc(t, "doctrine_consanguinity_unrestricted_descriptive_name") == "无限制婚姻")
    check("信条描述名取「描述名」而非「档位名」（至亲禁忌 / 禁止近亲通婚）",
          L.loc(t, "doctrine_consanguinity_restricted_descriptive_name") == "禁止近亲通婚"
          and L.loc(t, "doctrine_consanguinity_restricted_name") == "至亲禁忌")


# ---------------------------------------------------------------------------
# [3] house_realm_name_zh 的回落链
# ---------------------------------------------------------------------------
def unit_house_chain():
    print("\n[3] house_realm_name_zh：家族名 → 父家族 → 宗族")
    melt = {"dynasties": {
        "dynasty_house": {
            "1": {"localized_name": "内沙布尔", "key": "house_child",
                  "parent_dynasty_house": 2, "dynasty": 9},
            "2": {"name": "dynn_Tahirid", "dynasty": 9},
            "3": {"localized_name": "某地", "dynasty": 9},
            "4": {"name": "dynn_Seljuk", "dynasty": 9},
        },
        "dynasties": {"9": {"name": "dynn_Oghuz"}},
    }}
    own = cl.house_realm_name_zh(melt, 4)
    check("家族自有名 → 家族名（不是宗族名）", own != "" and own != cl.dynasty_name_zh(melt, 9),
          (own, cl.dynasty_name_zh(melt, 9)))
    parent = cl.house_realm_name_zh(melt, 1)
    check("家族无自有名（只有地名 localized_name）→ 父家族名",
          parent != "" and parent == cl.house_realm_name_zh(melt, 2) and parent != "内沙布尔",
          (parent, cl.house_realm_name_zh(melt, 2)))
    dyn = cl.house_realm_name_zh(melt, 3)
    check("父家族也无名 → 回落宗族名", dyn == cl.dynasty_name_zh(melt, 9), (dyn, dyn))


# ---------------------------------------------------------------------------
# [4]/[5] 板块门与要求
# ---------------------------------------------------------------------------
def unit_sections():
    print("\n[4]/[5] 第三板块的门、名与要求")
    check("`_liyi_has_tail` 只看 church_chronicle",
          bio._liyi_has_tail({"church_chronicle": ["x"]}) is True
          and bio._liyi_has_tail({"papal_election": ["x"]}) is False
          and bio._liyi_has_tail({}) is False)
    check("板块名已改名",
          S.SECTION_TITLES["liyi"].get("tail") == "纪事·大公会议与教宗诏书")
    r0 = bio._liyi_req({"rite_profile": ["所奉礼仪：拜上帝会。"]})
    check("无教会素材时 tail 走兜底句，题面不提教会",
          "大公会议" in (r0["tail"] or "") and "大公会议" not in (r0["focus"] or ""), r0["focus"])
    r1 = bio._liyi_req({"rite_profile": ["所奉礼仪：拜上帝会。"],
                        "church_chronicle": [
                            "教会局面：截至999年7月7日，本朝教会处于「协同」之世。",
                            "954年10月11日，欢乐者尼各老举行大公会议。",
                            "975年10月13日，欢乐者尼各老颁布教宗诏书，"
                            "将原先禁止的「华夏综摄主义」改为允许。",
                            "920年2月1日，教会大分裂。",
                            "980年3月20日，厄德·罗贝尔举行大公会议，"
                            "改本礼核心教义：「武装朝圣」换成「圣人敬礼」；"
                            "将原先允许的「华夏综摄主义」改为禁止。",
                            "986年12月18日，欢乐者尼各老举行大公会议，"
                            "改本礼信条：血亲性关系由「交辈旁系亲属婚姻」改为「无限制婚姻」。"]})
    check("tail 逐条索要（局面/会议/诏书/定夺/信条/核心教义/大分裂）",
          all(t in r1["tail"] for t in ("教会当下的局面", "大公会议", "教宗诏书",
                                       "会议与诏书定夺的教义条目", "本礼信条",
                                       "本礼核心教义", "大分裂")), r1["tail"])
    check("题面点出大公会议与教宗诏书",
          "大公会议" in r1["focus"] and "教宗诏书" in r1["focus"], r1["focus"])
    check("要求无负向禁令词 (no-negative-prompts)",
          not any(NEG.search(v or "") for v in (r0["tail"], r0["focus"], r0["lead"], r0["mid"],
                                                r1["tail"], r1["focus"], r1["lead"], r1["mid"])))


# ---------------------------------------------------------------------------
# [6] 快照
# ---------------------------------------------------------------------------
def snap_checks(path):
    if not os.path.isfile(path):
        print(f"\n[6] [SKIP] 缺快照：{path}")
        return
    snap = json.load(open(path, encoding="utf-8"))
    facts = snap.get("facts") or {}
    blocks = snap.get("blocks") or {}
    surf = surface_of(snap)
    cc = [str(x) for x in (facts.get("church_chronicle") or [])]
    tail = blocks.get("liyi_tail") or {}
    tag = os.path.basename(path)
    print(f"\n[6] {tag} schema={snap.get('schema')} as_of={facts.get('as_of')} "
          f"church_chronicle={len(cc)} 行")

    # ① 官职与绰号
    check("① 无「前礼部尚书，书吏」", "前礼部尚书，书吏" not in surf)
    check("① 有「前礼部尚书书吏洪地保」", "前礼部尚书书吏洪地保" in surf,
          re.findall(r".{0,12}前礼部尚书.{0,16}", surf)[:2])

    # ② 板块替换
    check("② facts 无 papal_election 键", "papal_election" not in facts)
    check("② facts.church_chronicle 非空", bool(cc), cc[:2])
    check("② 篇内有 liyi_tail 板块且键为「大公会议与教宗诏书」",
          bool(tail) and "大公会议与教宗诏书" in tail, sorted(tail))
    check("② 旧板块键不再出现", "枢机团与教宗选举" not in surf)

    # ③ 关键行
    joined = "\n".join(cc)
    for want, why in (("954年10月11日", "传主首次举行大公会议"),
                      ("986年12月18日", "传主第二次举行大公会议"),
                      ("975年10月13日", "传主首次颁布教宗诏书"),
                      ("997年12月24日", "传主末次颁布教宗诏书"),
                      ("920年2月1日", "教会大分裂")):
        check(f"③ 含 {want}（{why}）", want in joined, joined[:200])
    check("③ 会议行有主持者", "举行大公会议" in joined and "尼各老" in joined)
    check("③ 诏书行点出颁布者", re.search(r"颁布教宗诏书", joined) is not None)
    check("③ 教会局面行", any(x.startswith("教会局面：") for x in cc), cc[:1])

    # ④ 允许/禁止行，且 core 更替仍只在《礼仪志》中场
    check("④ 有允许/禁止的教义定夺行",
          any(("列为禁止" in x or "列为允许" in x) for x in cc),
          [x for x in cc if "列为" in x][:2])
    check("④ 教会板块不含核心教义更替行（归中场「本礼教义沿革」）",
          not any(("改礼仪核心教义" in x or "为礼仪增定" in x or "礼仪核心教义去" in x
                   or "列为核心教义" in x) for x in cc),
          [x for x in cc if "核心教义" in x][:3])
    check("④ 信条（禁忌）更替行有分组名",
          any("改本礼信条" in x and "血亲性关系" in x for x in cc),
          [x for x in cc if "改本礼信条" in x][:3])

    # ⑤ 传输面卫生
    bare = sorted(set(BARE.findall(joined)))
    check("⑤ 教会行无裸 tenet_/doctrine_ 键", not bare, bare[:3])
    check("⑤ 教会行无 [..] / $..$ 标记", not MARK.search(joined),
          MARK.findall(joined)[:3])
    check("⑤ 教会行无括注", not PAREN.search(joined), PAREN.findall(joined)[:3])

    # ⑥ 国名
    check("⑥ 传输面无「哈希姆哈里发国」", "哈希姆哈里发国" not in surf)
    check("⑥ 传输面出现头衔名「阿拉伯帝国」", "阿拉伯帝国" in surf,
          re.findall(r".{0,10}阿拉伯帝国.{0,10}", surf)[:2])


# ---------------------------------------------------------------------------
# [7] 成稿 md
# ---------------------------------------------------------------------------
def md_checks():
    print("\n[7] 成稿 md")
    paths = sorted(glob.glob(os.path.join(H2, "*.md")))
    if not paths:
        print("  [SKIP] 无成稿")
        return
    for p in paths:
        txt = open(p, encoding="utf-8").read()
        nm = os.path.basename(p)
        check(f"{nm}: 无「哈希姆哈里发国」", "哈希姆哈里发国" not in txt)
        check(f"{nm}: 无「前礼部尚书，书吏」", "前礼部尚书，书吏" not in txt)


def main():
    paths = [a for a in sys.argv[1:] if not a.startswith("--")] or DEFAULT
    unit_realm_name()
    unit_tables()
    unit_house_chain()
    unit_sections()
    for p in paths:
        snap_checks(p)
    if "--md" in sys.argv:
        md_checks()
    print("\n" + ("全部通过" if OK else "**有 FAIL**"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
