# -*- coding: utf-8 -*-
"""v125 断言（杨氏六问）：只读一份 facts 快照，秒级。

用法：
    & tools\\py.ps1 tools\\tests\\verify_v125.py [快照路径]
不给路径时取 output\\杨氏\\data\\ 下最新的 snap_38932_*snap_v125*.json。

断言组与《方案_v125_杨氏_六问.md》§九 一一对应：
    V125-1 「兼X兼X」重复（两个出口写出同一个词）
    V125-2 上皇出词、亲王不再用于做过天皇的人
    V125-3 895 那条记忆句以杨白劳为行主语（「杨白劳与妻子韩吉娘」），无「岳母兼儿媳」
    V125-4 游戏 UI 措辞不再进正文（社会规范／在结婚之后／令人分心的关系）
    V125-5 枢密使只写一次
    V125-6 后任句用并称（「其妻兼孙女…继为传主」）
    V125-7 纯函数 _join_office_words 三条口径
    V125-8 七条 REASON_REWRITE 渲染后不含游戏术语
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import facts as F      # noqa: E402
import style           # noqa: E402

FOLDER, PID = "杨氏", 38932

_fail = []
_pass = []


def ck(name, ok, detail=""):
    (("PASS", _pass) if ok else ("FAIL", _fail))[1].append(f"[{name}] {detail}")
    print(("PASS" if ok else "FAIL"), name, detail)


def _latest():
    pats = [os.path.join(ROOT, "output", FOLDER, "data",
                         f"snap_{PID}_*snap_v125*.json"),
            os.path.join(ROOT, "output", FOLDER, "data", "snap_v125*.json")]
    cands = [p for pat in pats for p in glob.glob(pat)]
    cands = sorted(set(cands), key=os.path.getmtime)
    return cands[-1] if cands else ""


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else _latest()
    if not path or not os.path.exists(path):
        print("找不到快照，先跑 tools/tests/snap.py 杨氏 38932 912.10.6 --name=snap_v125")
        return 2
    snap = json.load(open(path, encoding="utf-8"))
    blocks = snap.get("blocks") or {}
    parts = []

    def _walk(v):
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                _walk(x)
        elif isinstance(v, list):
            for x in v:
                _walk(x)
    _walk(blocks)
    text = "\n".join(parts)
    msgs = "\n".join(f"{m.get('system', '')}\n{m.get('user', '')}"
                     for m in (snap.get("messages") or {}).values())
    facts = snap.get("facts") or {}
    print(f"快照: {os.path.basename(path)}  blocks={len(blocks)}  text={len(text)} 字")

    # V125-1 两个出口写出同一个词
    dup = sorted({m.group(0) for m in re.finditer(r"兼([^兼，。、；：（）]{1,8})兼\1", text)})
    ck("V125-1", not dup, f"重复并称 {dup}")

    # V125-2 上皇（其他日本皇族仍可称亲王，所以只钉「阵前俘获」那一条与本人）
    allt = text + "\n" + msgs
    ck("V125-2a", "俘获上皇" in allt, "阵前俘获上皇")
    ck("V125-2b", not re.search(r"(大历|惟仁)亲王|俘获亲王", allt),
       "本人不再称亲王（其他皇族的亲王词照旧）")

    # V125-3 行主语 = 杨白劳
    ck("V125-3a", "妻子兼情人韩吉娘再叙情好" in allt, "895 句基准为杨白劳")
    ck("V125-3b", "岳母兼儿媳" not in allt, "无 岳母兼儿媳")

    # V125-4 措辞
    for w in ("社会规范", "在结婚之后", "令人分心的关系"):
        ck(f"V125-4[{w}]", w not in allt, w)

    # V125-5 枢密使
    ck("V125-5a", "枢密使英勇者杨尚昆" in allt, "世系/年表单写枢密使")
    ck("V125-5b", "枢密使兼枢密使" not in allt, "无 枢密使兼枢密使")

    # V125-6 后任句并称
    succ = " ".join(facts.get("succession") or [])
    ck("V125-6a", "其妻兼孙女" in succ, "后任句并称")
    ck("V125-6b", "杨丹霞继为传主" in succ, "后任句原样收尾")

    # V125-7 纯函数
    j = F._join_office_words
    ck("V125-7a", j("枢密使", ["枢密使"]) == "枢密使", "同名座次不重出")
    ck("V125-7b", j("", ["枢密使"]) == "枢密使", "无本衔时直接出座次")
    ck("V125-7c", j("关白", ["枢密使"]) == "关白兼枢密使", "异名座次照旧并称")

    # V125-8 措辞表本身
    bad = re.compile(r"规范|按照|在.{0,4}之后，|令人分心|关系")
    hits = [k for k, v in style.REASON_REWRITE.items() if bad.search(v)]
    ck("V125-8a", not hits, f"未收净 {hits}")
    ck("V125-8b", len(style.REASON_REWRITE) == 7,
       f"七条齐全（实 {len(style.REASON_REWRITE)}）")

    print(f"\n通过 {len(_pass)} 条，失败 {len(_fail)} 条")
    for line in _fail:
        print("  ", line)
    return 0 if not _fail else 1


if __name__ == "__main__":
    sys.exit(main())
