# -*- coding: utf-8 -*-
"""审计：游戏关系缘由模板里还有哪些条目把 UI 术语当中文散文（v125 第四问的兜底）。

用法：& tools\\py.ps1 tools\\tests\\audit_reason_wording.py [--all]
    --all  连未命中的条目计数也打印（默认只列命中与「待审清单」）

判据是「这句话读起来像游戏界面，不像史传」的用词：社会规范／按照／违反／在…之后，／
令人分心／关系／浪漫关系／封建契约／理由／契约。已收进 `style.REASON_REWRITE` 的条目
记为「已改写」，其余进「待审清单」——本局只需处理那七条，脚本为后续存档兜底。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import localization as L   # noqa: E402
import style               # noqa: E402

JARGON = ("社会规范", "按照", "违反", "之后，", "令人分心", "浪漫关系",
          "封建契约", "关系", "契约", "理由")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def main():
    tpls = L.relation_templates()
    rows = []
    for key, tpl in (tpls or {}).items():
        if not isinstance(tpl, str) or not _CJK.search(tpl):
            continue
        hit = [w for w in JARGON if w in tpl]
        if hit:
            rows.append((key, tpl, hit))
    fixed = [r for r in rows if r[0] in style.REASON_REWRITE]
    todo = [r for r in rows if r[0] not in style.REASON_REWRITE]
    print(f"relation_templates 共 {len(tpls or {})} 条，命中术语 {len(rows)} 条："
          f"已改写 {len(fixed)}，待审 {len(todo)}")
    print("\n== 已改写（style.REASON_REWRITE）==")
    for key, _tpl, hit in sorted(fixed):
        print(f"  {key}: {style.REASON_REWRITE[key]}")
    print("\n== 待审清单 ==")
    for key, tpl, hit in sorted(todo):
        print(f"  {key}: {tpl}   ← {'/'.join(hit)}")
    if "--all" in sys.argv:
        print("\n== 全部条目 ==")
        for key, tpl in sorted((tpls or {}).items()):
            if isinstance(tpl, str) and _CJK.search(tpl):
                print(f"  {key}: {tpl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
