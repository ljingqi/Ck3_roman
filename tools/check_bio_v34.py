# -*- coding: utf-8 -*-
"""v34 成稿七问自查 (只读生成的传记 md, 不碰熔件/不调 API)。

用法: tools\\py.ps1 tools\\check_bio_v34.py [家族] [md文件名]
默认: 柳特佩特 潘杜尔夫·柳特佩特(848)_传记_878_01_01.md
"""
import io
import os
import re
import sys

def _repo_root():
    """仓库根: 从本文件向上找到含 facts.py 的目录 (兼容 tools/ 或 experiments/ 放置)。"""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        if os.path.isfile(os.path.join(d, "facts.py")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()


ROOT = _repo_root()
FOLDER = sys.argv[1] if len(sys.argv) > 1 else "柳特佩特"
NAME = sys.argv[2] if len(sys.argv) > 2 else "潘杜尔夫·柳特佩特(848)_传记_878_01_01.md"
PATH = os.path.join(ROOT, "output", FOLDER, NAME)

OK = True


def check(name, cond, detail=""):
    global OK
    print(("  PASS " if cond else "  FAIL ") + name
          + (f"  | {detail}" if detail else ""))
    if not cond:
        OK = False


def section(text, title):
    """取某篇 (## N、《标题…》 到下一个 ##) 的正文; 标题按前缀匹配
    (《阴私录·隐事秘辛》用「阴私录」即可命中)。"""
    pat = (r"^##\s*[^\n]*《" + re.escape(title) + r"[^》]*》[^\n]*$"
           r"(.*?)(?=^##\s|\Z)")
    m = re.search(pat, text, re.S | re.M)
    return m.group(1) if m else ""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    benji = section(text, "本纪")
    jiashi = section(text, "家室列传")
    secrets = section(text, "阴私录")
    feuds = section(text, "家族恩怨录")
    chaoju = section(text, "朝局风云录")
    print(f"# 成稿七问自查: {FOLDER}/{NAME} ({len(text)} 字符)")

    print("[1] 本纪不泄底 (问题1)")
    bad = [w for w in ("实为", "实父", "非亲生", "不是亲生", "情夫", "奸夫")
           if w in benji]
    check("本纪无揭底措辞", not bad, bad)
    for n in ("索丹·索丹", "安科马"):
        # 情人可作公开史实出场, 但不得与「之子/所生」同现
        for m in re.finditer(re.escape(n), benji):
            ctx = benji[max(0, m.start() - 40):m.end() + 40]
            if ("之子" in ctx) or ("所生" in ctx) or ("血脉" in ctx):
                check(f"本纪中 {n} 未与「之子/所生」同现", False, ctx)
                break
        else:
            check(f"本纪中 {n} 未与「之子/所生」同现", True)
    check("本纪不含「不育」", "不育" not in benji)

    print("[2] 乱伦写明对象 (问题2)")
    check("阴私录有乱伦句", "乱伦" in secrets)
    # 成稿允许换式 (「与X乱伦」/「乱伦：与X」), 判据取「同句共现」
    sent = ""
    for s in re.split(r"[。；\n]", secrets):
        if "乱伦" in s:
            sent = s
            break
    check("乱伦句带对象", "与" in sent and "查理" in sent, sent[:70])
    check("对象是血亲 (秃头查理)", "查理" in sent, sent[:70])
    check("安科马未被写成乱伦对象",
          not re.search(r"乱伦[^。；]{0,30}安科马", secrets))

    print("[3] 朝局不写别国官职 (问题3)")
    dang = ("唐", "尚书", "节度使", "宰相", "枢密使", "御史大夫")
    hit = [w for w in dang if w in chaoju]
    check("朝局篇无唐制官职", not hit, hit)

    print("[4] 微小阴茎 (问题4)")
    check("成稿提到极小阴茎", "极小阴茎" in text)

    print("[5] 各篇不复述 (问题5)")
    check("阴私录与家室列传并不同文",
          bool(secrets) and bool(jiashi) and secrets.strip()[:60] != jiashi.strip()[:60])
    for a, b, la, lb in ((benji, jiashi, "本纪", "家室列传"),
                         (benji, chaoju, "本纪", "朝局风云录")):
        if not a or not b:
            continue
        sents_a = set(x for x in re.split(r"[。；\n]", a) if len(x) > 14)
        sents_b = set(x for x in re.split(r"[。；\n]", b) if len(x) > 14)
        dup = sents_a & sents_b
        check(f"{la}与{lb}无整句重复", not dup,
              list(dup)[:1])

    print("[6] 恩怨因果 (问题6)")
    check("恩怨篇写战争起因", ("宣战" in feuds) or ("开战" in feuds))
    check("恩怨篇写夺地/失守", ("失守" in feuds) or ("夺" in feuds))
    check("恩怨篇写对方沦为无地冒险者",
          "无地冒险者" in feuds or "无地" in feuds)
    check("恩怨篇未把绑架/囚禁写成结仇之因",
          not re.search(r"(因为|因)[^。]{0,20}(绑|囚禁)[^。]{0,10}(结仇|成仇|反目)",
                        feuds))

    print("[7] 释放口径 (问题7)")
    # 判据: 妮卡蕾忒不得被写成**已获释**; 「此后再未见释放的记载」是正确写法
    bad_rel = []
    for m in re.finditer(r"妮卡蕾忒[^。]{0,24}?(获释|出狱|释放)", text):
        ctx = text[max(0, m.start() - 12):m.end()]
        if re.search(r"(未|无|没有|不见|未见|无由|连)[^，。]{0,12}"
                     r"(获释|出狱|释放)", ctx):
            continue
        bad_rel.append(ctx)
    check("妮卡蕾忒未被写成已释放", not bad_rel, bad_rel[:2])
    check("妮卡蕾忒写明「再未见释放的记载」",
          bool(re.search(r"妮卡蕾忒[^。]{0,40}未见[^。]{0,8}(释放|获释)", text)))
    print()
    print("全 PASS" if OK else "有 FAIL")
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
