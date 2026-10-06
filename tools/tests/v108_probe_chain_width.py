# -*- coding: utf-8 -*-
"""v108 探针：复合身份（兼链）的可达宽度 —— 亲属关系计算器能不能算出四重身份。

目标链：儿子兼继子兼弟弟兼舅舅（用户 2026-10-06 追加的问题）。
做法：合成最小族谱，让人物 C 相对传主 S 逐条具备身份，再问计算器：
  kin_key / blood_kin_words_for / kin_chain_words_for 各给出什么，链最多几个亲缘词。

被 tools/tests/v108_kin_sweep.py 的 [E] 段引用（`CASES` / `chain_of`）。
只读，不碰缓存；单独运行输出 logs/v108_chain_width.txt（UTF-8）。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import facts as F          # noqa: E402

OUT = os.path.join(ROOT, "logs", "v108_chain_width.txt")
LINES = []

# 固定人物：S 传主；C 相对人；P/M 其父/母；G 外祖父；W 配偶；U 姑母
S, C, P, M, G, W, U = 1, 2, 11, 12, 13, 14, 21

CASES = [
    ("① 儿子（只有这一条边）", "son"),
    ("② 继子（只有这一条边：C 是配偶 W 的子女、不是 S 的子女）", "step"),
    ("③ 弟弟（只有这一条边）", "brother"),
    ("④ 舅舅（只有这一条边：C 是母亲 M 的兄弟）", "uncle"),
    ("⑤ 儿子 + 弟弟 + 舅舅（三重血缘身份）", "all"),
    ("⑥ 儿子 + 弟弟 + 舅舅 + 表兄弟（四条独立血缘线，测上限）", "cap"),
]


def w(s=""):
    LINES.append(s)


def rec(fam=None, female=False, birth="1000.1.1", name=""):
    return {"family": fam or {}, "female": female, "birth": birth,
            "name_full": name, "name_zh": name, "house_name": "洪氏",
            "dynasty_house": 20237, "dynasty_name": "洪"}


def build(kind):
    """按 kind 拼一份 cid=C 相对 S 具备若干身份的族谱。"""
    fam = {
        str(S): {"father": [P], "mother": [M]},
        str(P): {"child": [S]},
        str(M): {"father": [G], "child": [S]},
        str(G): {"child": [M]},
        str(W): {"spouse": [S]},
        str(C): {},
    }

    def add(owner, fld, who):
        fam.setdefault(str(owner), {}).setdefault(fld, [])
        if who not in fam[str(owner)][fld]:
            fam[str(owner)][fld].append(who)

    if kind in ("son", "all", "cap"):
        add(S, "child", C)
        add(C, "father", S)
    if kind in ("step", "all"):
        add(S, "primary_spouse", W)          # 配偶边要写在 S 自己名下，级联才认「继子」
        add(W, "child", C)
        add(C, "mother", W)
    if kind in ("brother", "all", "cap"):
        add(S, "siblings", C)
        add(C, "siblings", S)
    if kind in ("uncle", "all", "cap"):
        add(M, "siblings", C)
        add(C, "siblings", M)
        add(C, "father", G)
    if kind == "cap":                        # 再加一条独立血缘线：姑母 U 之子
        add(P, "siblings", U)
        add(U, "siblings", P)
        add(G, "child", U)
        add(U, "child", C)
        add(C, "mother", U)
    chars = {}
    for k, f in fam.items():
        chars[k] = rec(f, k in (str(M), str(W), str(U)), "1000.1.1", "人" + k)
    chars[str(S)]["birth"] = "1000.1.1"
    chars[str(C)]["birth"] = "1010.1.1"          # C 比 S 小 → 弟弟
    chars[str(M)]["birth"] = "975.1.1"
    chars[str(P)]["birth"] = "970.1.1"
    chars[str(G)]["birth"] = "940.1.1"
    chars[str(W)]["birth"] = "1005.1.1"
    if str(U) in chars:
        chars[str(U)]["birth"] = "972.1.1"
    return {"player_id": S, "characters": chars}


def chain_of(kind):
    """→ {key, word, blood, chain, max}；合成族谱下计算器对 C 相对 S 的全部输出。"""
    cache = build(kind)
    fi = F.Facts(cache, {}, None)
    key = F.kin_key(cache, S, C)
    return {
        "cache": cache, "fi": fi, "key": key, "word": F.kin_text(key),
        "blood": fi.blood_kin_words_for(C, S),
        "chain": fi.kin_chain_words_for(C, S),
        "max": fi._KIN_CHAIN_BLOOD_MAX,
    }


def show(label, kind):
    r = chain_of(kind)
    cache = r["cache"]
    w("=" * 84)
    w("【%s】" % label)
    w("  S 的族谱：child=%s siblings=%s spouse=%s"
      % (cache["characters"][str(S)]["family"].get("child"),
         cache["characters"][str(S)]["family"].get("siblings"),
         cache["characters"][str(S)]["family"].get("primary_spouse")))
    w("  C 的族谱：father=%s mother=%s siblings=%s"
      % (cache["characters"][str(C)]["family"].get("father"),
         cache["characters"][str(C)]["family"].get("mother"),
         cache["characters"][str(C)]["family"].get("siblings")))
    w("  首词 kin_key(S→C)          = %-18r %s" % (r["key"], r["word"]))
    w("  blood_kin_words_for(C, S)  = %s   （%d 个血缘词）" % (r["blood"], len(r["blood"])))
    w("  kin_chain_words_for(C, S)  = %s" % (r["chain"],))
    w("  ⇒ 链宽 %d ；_KIN_CHAIN_BLOOD_MAX = %d" % (len(r["chain"]), r["max"]))
    return r


def main():
    w("=" * 84)
    w("v108 探针：亲属关系计算器对「儿子兼继子兼弟弟兼舅舅」这一复合身份的可达宽度")
    w("（合成最小族谱，只问 facts 计算器；不涉及生成与后处理）")
    w("=" * 84)
    for label, kind in CASES:
        show(label, kind)
    five = "兼".join(show("", "all")["chain"]) if False else "兼".join(chain_of("all")["chain"])
    w()
    w("=" * 84)
    w("结论")
    w("=" * 84)
    w("  1 「儿子」与「继子」互斥：kin_key 第 12 步（facts.py:1183-1186）要求继子是「配偶的子女"
      "且不是我的子女」，")
    w("    两者不可能同时成立；且「继子」属 _KIN_NONBLOOD_KEYS（facts.py:543-550），血缘路线"
      "补不出来，只能当首词。")
    w("  2 血缘词上限 _KIN_CHAIN_BLOOD_MAX = 3（首词本身是血缘词时只剩 2 个额外名额，"
      "facts.py:4837-4845），")
    w("    所以「儿子兼继子兼弟弟兼舅舅」四个亲缘身份结构性做不到。")
    w("  3 实测三重身份（⑤）算出的链是 %s：弟弟、舅舅两条独立血缘线都没出现，" % five)
    w("    因为 `_parent_maps`（facts.py:4718-4736）用 setdefault 只留**每条记录的第一个父亲/"
      "第一个母亲**，")
    w("    而 ⑤ 里 C 的父亲同一次记了两个（S 与 G）；_ancestor_routes 只沿着那一个父亲走，"
      "另外的路线整条丢失。")
    w("  4 ④（只有舅舅一条边）算出的链是「舅父兼族伯叔」：同一条约会路 G 被同时算成" 
      "主级联的舅父与路线表的族伯叔，")
    w("    即在链里**多出一个并不独立的关系词**（`_kin_key_of_route` factors.py:836-842 在 gap>0 时"
      "不看父系/母系，一律给族伯叔/族姑）。")
    w()
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(LINES) + "\n")
    print("wrote %s" % OUT)
    for line in LINES:
        print(line)


if __name__ == "__main__":
    main()
