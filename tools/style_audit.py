# -*- coding: utf-8 -*-
"""提示词自查 (tools/style_audit.py)
====================================
扫 style.py 里**发给模型的字符串**, 按两条铁律报错:

  铁律一 (no-negative-prompts): 一律正向表述 —— 命中
    `不要|请勿|勿|禁止|避免|切勿|不得|别 |严禁|不可|不再` 即报错;
  铁律二 (程序优先): 提示词里出现「缺料按语」(资料未载/未提供/不足/史无可考…)
    即报错 —— 这类措辞会被模型逐字照抄进正文 (菲利普实测 44 次 → 正文 33 处)。

用法: & D:\\Roman\\tools\\py.ps1 tools\\style_audit.py [--all]
  --all 连事实层措辞表 (第 8 节) 一起扫 (死因词允许文言, 只扫负向词)。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

NEG_RE = re.compile(r"不要|请勿|勿|禁止|避免|切勿|不得|别 |严禁|不可|不再")
ABSENCE_RE = re.compile(r"资料未载|资料不载|资料未提供|资料不足|史料不详|"
                        r"史无可考|族属不详|信仰不详|官制不详|特质不详")
# 允许出现的「非提示词」字符串 (代码用键、模块名、正则片段)
_WHITELIST_FILES = ()


def is_prompt_text(s):
    """粗判是否写给模型的中文串: 含中日韩字符且非注释。"""
    return bool(re.search(r"[\u3400-\u9fff]", s or ""))


def main():
    all_flag = "--all" in sys.argv
    path = os.path.join(ROOT, "style.py")
    src = io.open(path, encoding="utf-8").read()
    # 只扫字符串字面量 (单/双/三引号), 跳过注释
    lines = src.split("\n")
    bad_neg, bad_abs = [], []
    in_fact_section = False
    for i, ln in enumerate(lines, 1):
        if ln.startswith("# 8. 事实层措辞表"):
            in_fact_section = True
        stripped = ln.strip()
        if stripped.startswith("#"):
            continue
        # 抽出行内的引号字面量
        for m in re.finditer(r'"([^"]*)"|\'([^\']*)\'', ln):
            s = m.group(1) if m.group(1) is not None else m.group(2)
            if not is_prompt_text(s):
                continue
            if NEG_RE.search(s):
                bad_neg.append((i, s[:60]))
            if ABSENCE_RE.search(s) and (all_flag or not in_fact_section):
                bad_abs.append((i, s[:60]))
    print("扫描 %s (%d 行)" % (os.path.basename(path), len(lines)))
    print("\n[负向表述] 命中 %d 处 (铁律一)" % len(bad_neg))
    for i, s in bad_neg:
        print("   L%-5d %s" % (i, s))
    print("\n[缺料按语] 命中 %d 处 (铁律二)" % len(bad_abs))
    for i, s in bad_abs:
        print("   L%-5d %s" % (i, s))
    ok = not bad_neg and not bad_abs
    print("\n结果: %s" % ("PASS 提示词合铁律" if ok else
                          "FAIL 见上 (改法: 正向写出正确做法 / 由程序端省略无料内容)"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
