# -*- coding: utf-8 -*-
"""v108 复现：v107 后处理 `_fix_kin_roles` 曾在成稿里**改错**的三处（反身代词/引语窗口）。

素材全部取自 output/洪氏2 的成稿原文（耀国·缯松 终传/家室列传/阴私录），
用生产事实面（v107.json + player_135480.json）与生产段落主语直接调用生产函数：
  ① 「…父亲圣缯·洪堡被…勒死。他的妹妹桑莎·洪堡，时年三岁」 妹妹 → 女儿   （应保留 妹妹）
  ② 「问了一句：“父亲还会醒吗？”洪真一说不会。」             父亲 → 母亲   （应保留 父亲）
  ③ 「…布里基纳的信条——…。他的儿子耀国·耀国松继位。」       儿子 → 兄长   （应保留 儿子）
共同根因：①③ 是 `_reflexive_antecedent`（biography.py）在「他/自己」所在小句没有人名时
退回**上一句的第一个名字**，而那个名字往往是上一句的宾语（圣缯/布里基纳），不是代词真正的
先行语（段主语＝传主）；②是窗口问题：名字前 12 字里的亲缘词即使隔着引号、句号也被当成该名字
的定语。v108 已修：回退改为「上一句**以人名开头**才采信」，窗口不再跨越句末与右引号。
①b 是同一句换段主语（布里基纳）：那一句并不属于他的段落，此时 圣缯=祖父、桑莎=母亲 是该段的
正解，因此它检查的是「按段主语正确重判」，不是「逐字保留」。

被 tools/tests/v108_kin_sweep.py 的 [F] 段引用。只读；单独运行写 logs/v108_repro_final.txt。
"""
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import biography as bio          # noqa: E402
import facts as F                # noqa: E402

OUT = os.path.join(ROOT, "logs", "v108_repro_final.txt")
PID, SE_ZENG, ZY2, BRI, ZHEN_YI = 135480, 16878235, 117484775, 33706092, 33666563

S1 = ("第一桩婚配始于1009年，那年他六岁，父亲圣缯·洪堡被岭西郡主祁无尘用丝绳勒死。"
      "他的妹妹桑莎·洪堡，时年三岁，尚在布尔戈斯。")
S2 = ("孩子磕完头站起来，问了一句：“父亲还会醒吗？”洪真一说不会。")
S3 = ("叶尔德尔的私通、于尔娃的巫术、布里基纳的信条——在他死后去了哪里？没有人知道。"
      "他的儿子耀国·耀国松继位。")
S4 = "他的妹妹桑莎·洪堡，时年三岁，尚在布尔戈斯。"

CASES = [
    ("① 家室列传·开篇（生产段落主语=传主）", S1, [PID], "他的妹妹桑莎·洪堡"),
    ("①b 同一句（段落主语=布里基纳，按段主语重判）", S1, [BRI],
     "祖父圣缯·洪堡被岭西郡主祁无尘用丝绳勒死。他的母亲桑莎·洪堡"),
    ("② 洪真一篇（生产段落主语=洪真一）", S2, [ZHEN_YI], "“父亲还会醒吗？”"),
    ("②b 同上（段落主语=传主）", S2, [PID], "“父亲还会醒吗？”"),
    ("③ 阴私录（生产段落主语=传主）", S3, [PID], "他的儿子耀国·耀国松继位"),
    ("④ 对照：上一句没有人名时逐字不变", S4, [PID], "他的妹妹桑莎·洪堡"),
]


def load():
    data = os.path.join(ROOT, "output", "洪氏2", "data")
    cache = json.load(io.open(os.path.join(data, "player_135480.json"), encoding="utf-8"))
    snap = json.load(io.open(os.path.join(data, "v107.json"), encoding="utf-8"))
    facts = dict(snap["facts"])
    fi = F.Facts(cache, {}, None, as_of=facts.get("as_of"))
    facts["_facts"] = fi
    return cache, facts


def run():
    """→ [(label, src, subs, out, changed, keep)]：`keep` 是应当逐字保留的片段。"""
    cache, facts = load()
    out = []
    for label, src, subs, keep in CASES:
        got = bio._fix_kin_roles(src, facts, cache, subject_ids=subs)
        out.append((label, src, subs, got, got != src, keep))
    return out


def main():
    lines = ["=" * 84,
             "v108 复现：成稿里被 `_fix_kin_roles` 改错的三处（反身代词回指 / 引语窗口）",
             "=" * 84]
    bad = 0
    for label, src, subs, got, changed, keep in run():
        ok = keep in got
        bad += 0 if ok else 1
        lines.append("=" * 84)
        lines.append("%s   段落主语=%s   %s" % (label, subs, "逐字保留 OK" if ok else "★被改错"))
        lines.append("  in : " + src)
        lines.append("  out: " + got)
        lines.append("  应保留片段：%s" % keep)
    lines.append("=" * 84)
    lines.append("被改错的用例：%d / %d" % (bad, len(CASES)))
    lines.append("①③ 已修：`_reflexive_antecedent` 的无名句回退改为「上一句以人名开头才采信」，")
    lines.append("      小句中途提到的名字（多为宾语）不再夺取先行语。")
    lines.append("② 已修：定语窗口不跨越句末与右引号，引语里的「父亲」不再算作后面那个人名的定语。")
    lines.append("①b 是同一句换段主语（布里基纳）的正解，见脚本 docstring。")
    lines.append("=" * 84)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("wrote %s（被改错 %d / %d）" % (OUT, bad, len(CASES)))
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
