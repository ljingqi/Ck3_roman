# -*- coding: utf-8 -*-
"""v93 回归 (秒级; 不载熔件): 礼仪志要求随素材生成 / 修会创立日按 history 截断。

用法: & tools\\py.ps1 tools\\tests\\verify_v93.py [快照...]
      缺省取 output/洪氏2/data/snap_v93_gf_d1.json, 回退 snap_v92_gf_d1.json

用户 2026-10-02 两问:
  1 「礼仪志的第二部分是不是没给相关信息?」—— 是。纪事实际只下发三块
    (个人教义沿革 / 修会 / 礼仪沿革), `rite_tenet_changes` 为空即**没有**本礼
    教义沿革块, 但题面与板块要求是静态文本, 照索「本礼核心教义之更替」, 模型遂
    自造「初以三义而立：曰天父天兄，曰耶稣救赎，曰圣灵运行」, 并把**个人**教义的
    四次更替改写成「本礼核心」的沿革。修法: `biography._liyi_req` 逐块/逐行生成
    题面与要求 (U1–U5), 修会只在纪事要求里点名。
  2 「修会应该还有一个岭南隐修会(南岭隐修院), 为什么没录入?」—— 存档里在, 且其
    首府链落到传主 (`h_china`); 是 as_of 截断取错了键: 取的是
    `landed_titles[].date` (= 头衔**最后一次变更日** = 918.7.7), 而非 `history`
    最早一键 (= 创立日 891.4.16), 于是 915.1.1 的十年传记把它当「尚未创立」整所
    截掉 (906 年立的咏礼会 `date` 恰等于其创立日, 故未暴露)。修法: history 优先。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import biography as bio  # noqa: E402
import style as S        # noqa: E402

_OK = True

# 天贵福 915 档的礼仪档案 (七行俱全 —— 生成的开篇要求应与旧静态文本逐字相同)
PROF_FULL = [
    "所奉礼仪：拜上帝会。",
    "源自罗马礼。",
    "礼仪领袖：文思忠。",
    "核心教义：宗徒继承、基督的精兵、华夏综摄主义。",
    "宗教热情：平稳。",
    "灵性满足：蒙恩之人。",
    "个人教义：你们要生育繁殖、孝道、托钵宣道。",
]
OLD_LEAD_FULL = ("写传主所受之礼：所奉礼仪的名目与源流、礼仪领袖为谁。"
                 "核心教义逐条点名，宗教热情与灵性满足依档位词写来，"
                 "个人教义写出当前所奉的条目。")
_NEG = re.compile(r"不要|请勿|勿|禁止|避免|切勿|不得|别 |严禁|不可|不再|除非")


def check(name, cond, detail=""):
    global _OK
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (("  — " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _OK = False


# ---------------------------------------------------------------------------
# 一、纯函数: 礼仪志要求随素材生成
# ---------------------------------------------------------------------------
def unit_checks():
    print("\n[一] 纯函数 _liyi_req")
    full = dict(rite_profile=PROF_FULL, rite_history=["a", "b"],
                personal_tenets=["x", "y"], rite_tenet_changes=["c"],
                forbidden_tenets=["f"], holy_orders=["h"])
    r_full = bio._liyi_req(full)
    check("U1 全料时开篇要求与旧静态文本逐字相同",
          r_full["lead"] == OLD_LEAD_FULL, r_full["lead"])
    check("U2 全料时纪事要求四条俱全",
          all(t in r_full["mid"] for t in
              ("受礼、改礼、立礼", "个人信条", "核心教义的演变", "修会")),
          r_full["mid"])
    # v96 (问题1/2): 「禁忌信条之起止」那条已删 (键即便还在也不再触发该要求)
    check("U2b 禁忌信条不再进纪事要求 (v96 整块删)",
          "禁忌" not in r_full["mid"] and "禁忌" not in r_full["focus"],
          r_full["mid"] + " | " + r_full["focus"])

    # 天贵福 915 档实况: 无本礼教义沿革块、无禁忌信条
    gf = dict(rite_profile=PROF_FULL, rite_history=["a", "b"],
              personal_tenets=["x", "y"], holy_orders=["h"])
    r_gf = bio._liyi_req(gf)
    check("U3a 无本礼教义沿革块 ⇒ 纪事要求不提核心教义",
          "核心教义" not in r_gf["mid"], r_gf["mid"])
    check("U3b 无本礼教义沿革块 ⇒ 题面不提本礼核心教义之更替",
          "本礼核心教义" not in r_gf["focus"], r_gf["focus"])
    check("U3c 有修会块 ⇒ 纪事要求逐所写来",
          "修会" in r_gf["mid"] and "逐所写出" in r_gf["mid"], r_gf["mid"])
    check("U3d 题面不点修会 (开篇不下发修会料, 免得自造会名)",
          "修会" not in r_gf["focus"] and "修会" not in r_gf["lead"],
          r_gf["focus"] + " | " + r_gf["lead"])
    check("U3e 题面仍点受礼改礼立礼与个人教义之更替",
          "受礼、改礼、立礼" in r_gf["focus"] and "个人教义之更替" in r_gf["focus"],
          r_gf["focus"])

    r_min = bio._liyi_req(dict(rite_profile=["所奉礼仪：经学。"], holy_orders=["h"]))
    check("U4a 档案只有一行 ⇒ 开篇要求只索这一行",
          r_min["lead"] == "写传主所受之礼：所奉礼仪的名目。", r_min["lead"])
    check("U4b 只有修会一块 ⇒ 纪事要求只索修会, 题面回落通用句",
          r_min["mid"].endswith("现任之长。") and "受礼" not in r_min["mid"]
          and r_min["focus"] == "写传主所受之礼与其教门中的作为",
          r_min["mid"] + " | " + r_min["focus"])

    r_no_fervor = bio._liyi_req(dict(rite_profile=[
        "所奉礼仪：拜上帝会。", "核心教义：宗徒继承。", "个人教义：孝道。"]))
    check("U5 档案缺行时对应的分句一并省略 (无「宗教热情」即不索档位词)",
          "宗教热情" not in r_no_fervor["lead"]
          and "灵性满足" not in r_no_fervor["lead"]
          and "核心教义逐条点名" in r_no_fervor["lead"], r_no_fervor["lead"])
    check("U6 生成的要求无负向禁令词 (no-negative-prompts)",
          not any(_NEG.search(v) for v in
                  (r_full["lead"], r_full["mid"], r_full["focus"],
                   r_gf["lead"], r_gf["mid"], r_gf["focus"],
                   r_min["lead"], r_min["mid"], r_min["focus"])),
          r_gf["mid"])
    # 兜底句 (facts 里连行首都对不上时) 也不得含负向词
    check("U7 风格表兜底句无负向词 (S 表)",
          not any(_NEG.search(v)
                  for v in (S.SECTION_REQ["liyi"].get("lead") or "",
                            S.SECTION_REQ["liyi"].get("mid") or "")))


# ---------------------------------------------------------------------------
# 二、快照
# ---------------------------------------------------------------------------
def snap_checks(path):
    print(f"\n[二] 快照 {os.path.basename(path)}")
    d = json.load(open(path, encoding="utf-8"))
    facts = d.get("facts") or {}
    msgs = d.get("messages") or {}
    ho = list(facts.get("holy_orders") or [])
    lm = (msgs.get("liyi_mid") or {}).get("user") or ""
    ll = (msgs.get("liyi_lead") or {}).get("user") or ""

    # 2 修会: 南岭隐修院 (891 年立) 回来了
    check("S1 修会两所俱全 (咏礼会 + 南岭隐修院)",
          len(ho) == 2 and any("南岭隐修院" in x for x in ho)
          and any("洪天贵福咏礼会" in x for x in ho), ho)
    check("S2 南岭隐修院按**创立日** 891 年出词 (非 918 换持有人之年)",
          any(x.startswith("891年") and "南岭隐修院" in x for x in ho), ho)
    check("S3 咏礼会仍按 906 年出词",
          any(x.startswith("906年") and "洪天贵福咏礼会" in x for x in ho), ho)

    # 1 礼仪志要求
    check("S4a 纪事请求不再索要本礼核心教义的演变",
          "核心教义" not in lm, [x for x in lm.splitlines() if "要求" in x][:1])
    check("S4b 纪事请求仍索受礼改礼立礼与个人信条更替",
          "受礼、改礼、立礼" in lm and "个人信条" in lm)
    check("S4c 纪事请求点名修会且要求逐所写出",
          "修会" in lm and "逐所写出" in lm)
    check("S5 开篇请求不点修会 (修会只在纪事)",
          "修会" not in ll)
    check("S6 本档确实没有本礼教义沿革块 (故 S4a 是补正而非削弱)",
          not (facts.get("rite_tenet_changes") or []),
          facts.get("rite_tenet_changes"))


def main():
    unit_checks()
    paths = sys.argv[1:]
    if not paths:
        for nm in ("snap_v93_gf_d1.json", "snap_v92_gf_d1.json"):
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
