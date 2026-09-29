# -*- coding: utf-8 -*-
"""v84 一次性回填 · 剥掉既有成稿开头「模型另写的标题行/题记行」。

用户 2026-09-29 报告: 每篇 .md 开头标题重复两遍 ——
  ```
  # 《腐化者平盛秀传》
  > 家族：平氏下北沢家｜人物：腐化者平盛秀｜死于1006年8月7日，此为终传

  # 《腐化者平盛秀传》                      <== 模型按总纲提示词另写的
  家族：平氏下北沢家｜人物：腐化者平盛秀｜生卒：956年12月25日–1006年8月7日
  ```
成因与全程修法见 `biography._strip_intro_head` 的注释 (出稿处已修, 新生成不再重复)。
本脚本把**既有**成稿也回填成同一形态: 保留首行机器可读注释 + 程序标题行 + `> 家族：…`
题记行, 其后由模型另写的那几行交给 `bio._strip_intro_head` 剥掉 (逐字同一函数,
故回填结果与新生成的形态一致)。

安全: 逐文件先备份 `.bak_v84pre_<原名>` (output/ 整个目录被 .gitignore 忽略, 没有
版本回退, 必须自己留备份); 已存在同名备份时跳过该文件的备份写入 (幂等, 可重复跑)。
默认**试跑** (只打印将改动的文件); 加 `--apply` 才落盘, 并重建各家族的 index.html。

用法:
  & tools\\py.ps1 tools\\fix_v84_dup_head.py            # 试跑
  & tools\\py.ps1 tools\\fix_v84_dup_head.py --apply    # 落盘 + 重建阅读页
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import biography as bio   # noqa: E402

OUT_DIR = os.path.join(ROOT, "output")
# 首行机器注释 + 程序标题行 + `> 家族：…` 题记行 (+ 其后的空行)
HEAD_RE = re.compile(
    r"\A(?P<head><!--[^\n]*-->\n+[^\n]*#\s*《[^\n]*》\n>[^\n]*\n\n*)"
    r"(?P<rest>.*)\Z", re.S)


def iter_md():
    """只走**现行成稿** (pipeline 命名: <姓名>_终传|传记[_第N个十年]_<日期>.md)。

    `.` 开头的是本项目自己的备份 (`.bak_v81pre_…`), `_` 开头的是历史留档
    (`_v57_before.md` / `_旧_第1个十年_878.md`), 都不在阅读页里, 不改。"""
    for house in sorted(os.listdir(OUT_DIR)):
        d = os.path.join(OUT_DIR, house)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".md") or fn.startswith((".", "_")):
                continue
            if not re.match(r"^.+_(?:终传|传记)(?:_第\d+个十年)?_\d+_\d{2}_\d{2}\.md$", fn):
                continue
            yield house, os.path.join(d, fn)


def main():
    apply = "--apply" in sys.argv
    changed, skipped, n = [], [], 0
    for house, path in iter_md():
        n += 1
        with io.open(path, encoding="utf-8") as fp:
            text = fp.read()
        m = HEAD_RE.match(text)
        if not m:
            skipped.append((os.path.basename(path), "无「注释+标题+题记」头 (人工复核)"))
            continue
        rest = m.group("rest")
        new_rest = bio._strip_intro_head(rest)
        if new_rest == rest:
            continue
        tail = "\n" if text.endswith("\n") else ""
        out = m.group("head") + new_rest.rstrip("\n") + "\n" + tail
        d, fn = os.path.dirname(path), os.path.basename(path)
        bak = os.path.join(d, ".bak_v84pre_" + fn)
        changed.append((house, fn))
        if not apply:
            continue
        if not os.path.exists(bak):
            with io.open(bak, "w", encoding="utf-8") as fp:
                fp.write(text)
        with io.open(path, "w", encoding="utf-8") as fp:
            fp.write(out)
    print("扫描 %d 篇; %s %d 篇" % (n, "已修" if apply else "将修", len(changed)))
    for house, fn in changed:
        print("   %-8s %s" % (house, fn))
    for fn, why in skipped:
        print("   [跳过] %-40s %s" % (fn, why))
    if apply and changed:
        import htmlview
        for house in sorted({h for h, _ in changed}):
            page = htmlview.rebuild_folder(OUT_DIR, house)
            print("   阅读页已更新: %s" % page)


if __name__ == "__main__":
    main()
