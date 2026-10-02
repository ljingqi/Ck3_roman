# -*- coding: utf-8 -*-
"""v96 回归 (秒级; 不载熔件): 禁忌个人信条整块删 / 礼仪档案按 as_of 取 / 病名去逗号。

用法: & tools\\py.ps1 tools\\tests\\verify_v96.py [快照...]
      缺省取 output/洪氏2/data/ 下的 snap_v96_final / _d3 / _d4 (缺一则 SKIP)

用户 2026-10-02 三问 (取证见 docs/方案_v96_洪氏2三问题.md, 日志 logs/v96_probe_*.txt):
  1 终传写「其间九三四年、九四五年、九五〇年，三度采纳禁忌信条『你们要生育繁殖、
    恐怖节庆、自然原始主义』」—— 根因是 `forbidden_tenet_lines` 用**末档**的
    允许/禁止分档去配秘密的 `first_seen` 年: 934 年〈你们要生育繁殖〉〈恐怖节庆〉
    都还是 permitted (前者直到 950 年才移入 prohibited), 于是三行教义名互相重叠、
    句式又一律「他采纳…」, 模型并成一句「三度采纳同一组三条」。
    用户拍板: 该秘密不带教义键 (只能反查), 教义名与年份都不可靠 ⇒ **整块删**,
    只留个人教义本身的沿革 (`personal_tenet_lines`)。
  2 「天贵福既为教主」—— 事实面从未出现过「教权」二字, 纪事请求里连「礼仪领袖」
    那一行都没有; 用户拍板**不加**新事实行、**不加**提示词。
  3 病名「皇帝，洪天贵福热」的逗号来自存档 (游戏自渲染的「称号，名字＋病名」,
    实测 16 份缓存 240 场疫情里 4 场带此逗号) ⇒ 出词口去逗号。
  4 附带发现 (用户拍板「一起修」): `rite_profile_lines` 的「礼仪领袖」与「核心教义」
    原读末档现值, 用末档缓存重跑十年篇时把 946 年即位的教宗与 947/950 才换的核心
    教义写进了 935 年 (`洪天贵福(869)_传记_第3个十年_935_01_01.md:312/314`)。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import biography as bio  # noqa: E402
import facts as F        # noqa: E402

_OK = True
_NEG = re.compile(r"不要|请勿|勿|禁止|避免|切勿|不得|别 |严禁|不可|不再|除非")
# 病名被直拼进「染{名}而亡」; 名字里再出现「称号，」即是没去掉的逗号
_BAD_DISEASE = re.compile(r"染[\u4e00-\u9fff]{1,4}，")


def check(name, cond, detail=""):
    global _OK
    print(("  [OK]   " if cond else "  [FAIL] ") + name
          + (("  — " + str(detail)) if (detail and not cond) else ""))
    if not cond:
        _OK = False


def _stub_facts(cache):
    """只带 cache 的 Facts 空壳 (纯函数断言用, 不跑 __init__)。"""
    f = F.Facts.__new__(F.Facts)
    f.cache = cache
    return f


# ---------------------------------------------------------------------------
# 一、纯函数
# ---------------------------------------------------------------------------
def unit_checks():
    print("\n[一] 纯函数")

    # 3 病名逗号
    check("U1a 「称号，名字」逗号去掉",
          F._strip_title_comma("皇帝，洪天贵福热") == "皇帝洪天贵福热"
          and F._strip_title_comma("王，吕嗣宗痢") == "王吕嗣宗痢"
          and F._strip_title_comma("叶护，兀尊尺牟羽热") == "叶护兀尊尺牟羽热",
          F._strip_title_comma("皇帝，洪天贵福热"))
    check("U1b 无逗号者逐字不变",
          F._strip_title_comma("浪漫瘟疫") == "浪漫瘟疫"
          and F._strip_title_comma("") == "")
    check("U1c _clean_ck3_loc 行为不变 (v13 旧例仍是「国王张格本」)",
          F._clean_ck3_loc("国王，张格本") == "国王张格本",
          F._clean_ck3_loc("国王，张格本"))

    # 4 as_of 锁存点
    hist = {"154": [
        {"from": "923.1.1", "head": 1, "tenets": {"core": ["a"], "prohibited": ["x"]}},
        {"from": "950.1.1", "head": 2, "tenets": {"core": ["b"], "prohibited": ["y"]}},
        {"from": "952.1.1", "head": 3, "tenets": {"core": ["c"], "prohibited": ["z"]}},
    ]}
    f = _stub_facts({"rite_tenets_history": hist})
    _p1 = f._rite_point_at(154, "935.1.1") or {}
    _p2 = f._rite_point_at(154, "950.1.1") or {}
    check("U2a as_of 落在中段 ⇒ 取 ≤as_of 的最后锁存点 (含 head)",
          _p1.get("from") == "923.1.1" and _p1.get("head") == 1
          and _p1.get("tenets") == {"core": ["a"], "prohibited": ["x"]}
          and _p2.get("from") == "950.1.1" and _p2.get("head") == 2,
          json.dumps([_p1, _p2], ensure_ascii=False))
    _p3 = f._rite_point_at(154, None) or {}
    check("U2b 终传 (date=None) ⇒ 取末点",
          _p3.get("from") == "952.1.1" and _p3.get("head") == 3)
    _p0 = f._rite_point_at(154, "900.1.1") or {}
    check("U2c date 早于首点 ⇒ 取首点 (早于首点取首点口径)",
          _p0.get("from") == "923.1.1" and _p0.get("head") == 1)
    check("U2d 无史/无该礼 ⇒ None (调用方回退现值)",
          _stub_facts({})._rite_point_at(154, "935.1.1") is None
          and f._rite_point_at(999, "935.1.1") is None)

    # 1/2 禁忌个人信条整块删
    check("U3a forbidden_tenet_lines 已从 Facts 删除",
          not hasattr(F.Facts, "forbidden_tenet_lines"))
    base = {"rite": "罗马礼", "rite_profile": ["所奉礼仪：罗马礼。"]}
    check("U3b 该键即便仍在也不构成出篇/纪事门槛",
          not bio._liyi_has_material(dict(base, forbidden_tenets=["x"]))
          and not bio._liyi_has_mid(dict(base, forbidden_tenets=["x"])))
    rq = bio._liyi_req(dict(base, forbidden_tenets=["x"],
                            personal_tenets=["a", "b"], holy_orders=["h"]))
    check("U3c 要求里不再出现「禁忌」(键仍在也不触发)",
          "禁忌" not in rq["mid"] and "禁忌" not in rq["focus"]
          and "禁忌" not in rq["lead"],
          rq["mid"] + " | " + rq["focus"])
    check("U3d 生成的要求无负向禁令词 (no-negative-prompts)",
          not any(_NEG.search(v) for v in (rq["lead"], rq["mid"], rq["focus"])))


# ---------------------------------------------------------------------------
# 二、快照
# ---------------------------------------------------------------------------
def _lead_line(blocks, prefix):
    for x in (blocks.get("liyi_lead") or {}).get("礼仪档案", "").splitlines():
        if x.startswith(prefix):
            return x
    return ""


def snap_checks(path):
    with open(path, encoding="utf-8") as fp:
        d = json.load(fp)
    facts = d.get("facts") or {}
    blocks = d.get("blocks") or {}
    msgs = d.get("messages") or {}
    meta = d.get("meta") or {}
    tag = "%s (as_of=%s)" % (os.path.basename(path), meta.get("as_of"))
    print(f"\n[二] {tag}")

    check("S0 快照 schema>=7 (v96 传输面)", int(d.get("schema") or 0) >= 7,
          str(d.get("schema")))
    check("S1a facts 无 forbidden_tenets 键", "forbidden_tenets" not in facts)
    # 注意: 「禁忌个人信条」是**游戏**给该秘密类型的名字 (secrets_l_simp_chinese.yml:20),
    # 《阴私录》照写不算错 —— 这里只查《礼仪志》的块名与块面。
    check("S1b 礼仪志无「禁忌个人信条」块",
          all("禁忌个人信条" not in (blocks.get(k) or {})
              for k in ("liyi_lead", "liyi_mid", "liyi_tail")),
          str([k for k in ("liyi_lead", "liyi_mid", "liyi_tail")
               if "禁忌个人信条" in (blocks.get(k) or {})]))
    for k in ("liyi_lead", "liyi_mid", "liyi_tail"):
        _u = (msgs.get(k) or {}).get("user") or ""
        check(f"S1c {k} 请求文本无「禁忌」", "禁忌" not in _u,
              [x for x in _u.splitlines() if "禁忌" in x][:1])
    check("S2 个人教义沿革仍在 (只删禁忌那块)",
          bool(facts.get("personal_tenets"))
          and "个人教义沿革" in (blocks.get("liyi_mid") or {}),
          str(list(facts.get("personal_tenets") or [])[:1]))

    # 3 病名逗号
    _txt = json.dumps(d.get("facts") or {}, ensure_ascii=False)
    _hit = _BAD_DISEASE.findall(_txt)
    check("S3 事实面无「染{称号，…}」式病名", not _hit, _hit[:3])
    check("S3b 含「洪天贵福热」的死亡句已去逗号 (若有)",
          "，洪天贵福热" not in _txt)

    # 4 礼仪档案按 as_of 取
    _head = _lead_line(blocks, "礼仪领袖：")
    _core = _lead_line(blocks, "核心教义：")
    _ao = str(meta.get("as_of") or "")
    if _ao and _ao < "946.1.1":
        # 教宗亚纳大削三世 946.2.24 才即位 —— 此前的篇目写出他就是末档泄漏
        check("S4a 十年篇不写 946 年才即位的教宗",
              bool(_head) and "亚纳大削" not in _head, _head)
    else:
        check("S4a 终传/当代篇的礼仪领袖写现任教宗 (教宗亚纳大削三世)",
              "亚纳大削" in _head, _head)
    if _ao and _ao < "947.1.1":
        # 947 年才换成「宗徒继承、圣人敬礼、基督的精兵」, 950 年再换成现行三条
        check("S4b 十年篇的核心教义按当档取 (非 947/950 才换的那三条)",
              _core == "核心教义：宗徒继承、基督的精兵、华夏综摄主义。", _core)
    else:
        check("S4b 终传的核心教义为现行三条",
              _core == "核心教义：热忱传教、宗徒继承、圣人敬礼。", _core)


def main():
    unit_checks()
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not paths:
        data = os.path.join(ROOT, "output", "洪氏2", "data")
        for nm in ("snap_v96_final.json", "snap_v96_d3.json", "snap_v96_d4.json"):
            p = os.path.join(data, nm)
            if os.path.exists(p):
                paths.append(p)
            else:
                print(f"  [SKIP] 缺快照 {nm}")
    for p in paths:
        if os.path.exists(p):
            snap_checks(p)
        else:
            check(f"快照存在: {p}", False)
    print("\n" + ("全部通过" if _OK else "**有 FAIL**"))
    return 0 if _OK else 1


if __name__ == "__main__":
    sys.exit(main())
