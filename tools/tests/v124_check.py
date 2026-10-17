"""v124 断言：关系计算器扩到「关系的关系」（路径词）。

纯函数部分（不载熔件、秒级）：

  1. 词形 —— 单音节同胞改口称（哥哥/妹妹），双音节堂表照旧（堂兄/表兄）；
  2. 领主路径 —— 「领主的女儿」，基准人是封臣时锚点取 `char_vassal_history`；
  3. 最高领主 —— 领主之上再有一层时，顶层锚点用「最高领主」；
  4. 排序 —— 同类同宽时「领主」压过「最高领主」、「关系」压过一切；
  5. 亲缘×亲缘不出词（两步亲缘本就是一个词，`identity_parts` 直接算）；
  6. 三词形状 —— 「门生的狩猎总管的堂弟」（中间跳是锚点的宫廷职位）；
  7. `paths=False` 时一个路径词都不出（后处理口径）；
  8. 同一对两次调用同结果；基准人与目标相同/缺省时空串；
  9. 空熔件 fail-open（大量测试用 `Facts(cache, {})`）。

用法：
  & tools\\py.ps1 tools\\tests\\v124_check.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

FAIL = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        FAIL.append((name, detail))


def build(cache, melt=None):
    import facts as F
    return F.Facts(cache, melt or {}, None, as_of="1119.7.15")


def base_cache():
    """主角 1（封臣），领主 2，领主的女儿 3；主角的同胞弟弟 4、妹妹 5。"""
    return {
        "player_id": 1,
        "characters": {
            "1": {"birth": "1090.1.1", "female": False, "family": {"siblings": [4, 5]}},
            "2": {"birth": "1060.1.1", "female": False,
                  "family": {"child": [3], "siblings": []}},
            "3": {"birth": "1092.1.1", "female": True, "family": {"father": [2]}},
            "4": {"birth": "1095.1.1", "female": False, "family": {"siblings": [1]}},
            "5": {"birth": "1098.1.1", "female": True, "family": {"siblings": [1]}},
        },
        "char_vassal_history": {"1": [{"date": "1114.1.1", "liege": 2, "flags": []}]},
    }


def main():
    import facts as F

    print("[1] 词形")
    check("兄长 → 哥哥", F.kin_text("brother_older") == "哥哥", F.kin_text("brother_older"))
    check("堂兄保持双音节", F.kin_text("cousin_pat_brother_older") == "堂兄",
          F.kin_text("cousin_pat_brother_older"))
    check("表兄保持双音节", F.kin_text("cousin_mat_brother_older") == "表兄",
          F.kin_text("cousin_mat_brother_older"))
    check("妹妹不变", F.kin_text("sister_younger") == "妹妹", F.kin_text("sister_younger"))

    print("[2] 领主路径")
    f = build(base_cache())
    check("直接词仍为空", f.identity_parts(3, 1, paths=False) == [], f.identity_parts(3, 1, paths=False))
    check("领主的女儿", f.path_word_for(3, 1) == "领主的女儿", f.path_word_for(3, 1))
    check("锚点表含 领主=2",
          ("liege", 2, "领主") in f._path_anchors(1), f._path_anchors(1))
    check("反向不成立（领主对主角无比）", f.path_word_for(1, 3) == "", f.path_word_for(1, 3))
    check("同胞词是 弟弟/妹妹",
          (f.kin_word_for(4, 1), f.kin_word_for(5, 1)) == ("弟弟", "妹妹"),
          (f.kin_word_for(4, 1), f.kin_word_for(5, 1)))

    print("[3] 最高领主")
    c = base_cache()
    # 2 的领主是 6，6 独立；6 的女儿 7
    c["characters"]["2"]["family"]["father"] = [6]
    c["characters"]["6"] = {"birth": "1030.1.1", "family": {"child": [2, 7]}}
    c["characters"]["7"] = {"birth": "1070.1.1", "female": True, "family": {"father": [6]}}
    c["char_vassal_history"]["2"] = [{"date": "1110.1.1", "liege": 6, "flags": []}]
    f = build(c)
    anchors = f._path_anchors(1)
    check("两层领主都在锚点表", ("liege", 2, "领主") in anchors
          and ("top_liege", 6, "最高领主") in anchors, anchors)
    check("领主锚点仍压过最高领主（领主的女儿）",
          f.path_word_for(3, 1) == "领主的女儿", f.path_word_for(3, 1))
    check("只经顶层才成立的对写出 最高领主",
          f.path_word_for(7, 1) == "最高领主的女儿", f.path_word_for(7, 1))
    fed = f._path_anchors
    f._path_anchors = lambda subj: ([("top_liege", 6, "最高领主")]
                                    if int(subj) == 1 else [])
    check("只用顶层锚点时词形仍是 最高领主",
          f.path_word_for(7, 1) == "最高领主的女儿", f.path_word_for(7, 1))
    f._path_anchors = fed

    print("[4] 亲缘×亲缘不出词")
    c = base_cache()
    c["characters"]["1"]["family"]["child"] = [8]
    c["characters"]["8"] = {"birth": "1110.1.1", "family": {"father": [1], "mother": [9]}}
    c["characters"]["9"] = {"birth": "1092.1.1", "female": True, "family": {"child": [8]}}
    f = build(c)
    check("儿子的母亲（未记为配偶）→ 无路径词", f.path_word_for(9, 1) == "",
          f.identity_parts(9, 1))
    check("该对身份表为空", f.identity_parts(9, 1) == [], f.identity_parts(9, 1))

    print("[5] 三词形状（中间跳是职位）")
    f = build(base_cache())
    court = [(10, "court_physician_court_position", "1110.1.1")]
    c = base_cache()
    c["characters"]["10"] = {"birth": "1080.1.1", "family": {"child": [11]}}
    c["characters"]["11"] = {"birth": "1110.1.1", "female": False,
                             "family": {"father": [10]}}
    f = build(c)
    f._court_rows = lambda emp: list(court) if int(emp) == 2 else []
    f._office_anchor_word = lambda typ, emp=None: "狩猎总管" if typ else ""
    check("领主的狩猎总管的儿子",
          f.path_word_for(11, 1) == "领主的狩猎总管的儿子", f.path_word_for(11, 1))
    check("三词形状恰好两个「的」",
          len(f.path_word_for(11, 1).split("的")) == 3, f.path_word_for(11, 1))

    print("[6] paths=False 与幂等")
    f = build(base_cache())
    check("paths=False 不出路径词", f.identity_parts(3, 1, paths=False) == [],
          f.identity_parts(3, 1, paths=False))
    check("kin_chain_words_for 默认含路径词",
          f.kin_chain_words_for(3, 1) == ["领主的女儿"], f.kin_chain_words_for(3, 1))
    check("同一对两次同结果", f.path_word_for(3, 1) == f.path_word_for(3, 1), "")
    check("自身为空串", f.path_word_for(1, 1) == "", f.path_word_for(1, 1))
    check("缺省为空串", f.path_word_for(None, 1) == "" and f.path_word_for(3, None) == "", "")

    print("[7] 空熔件 fail-open")
    c = base_cache()
    f = build(c, {})
    check("无熔件时仅亲缘/领主锚点",
          {k for k, _a, _w in f._path_anchors(1)} <= {"kin", "liege", "top_liege"},
          f._path_anchors(1))
    check("无熔件仍出领主路径", f.path_word_for(3, 1) == "领主的女儿", f.path_word_for(3, 1))

    print("[8] 无词的第三人不会被平白加长")
    f = build(base_cache())
    check("有直接词的一对不产生路径词替换", f.identity_parts(4, 1)[0][1] == "弟弟",
          f.identity_parts(4, 1))

    print()
    if FAIL:
        print(f"v124 断言失败 {len(FAIL)} 项：")
        for n, d in FAIL:
            print(f"  - {n}  {d}")
        sys.exit(1)
    print("v124 断言全部通过")


if __name__ == "__main__":
    main()
