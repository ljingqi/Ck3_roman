# -*- coding: utf-8 -*-
"""v107 probe: why the "孩子的妹妹是桑莎·洪堡" class survives every kin-word fix.

Read-only. Streams the family block of a handful of characters out of
output/洪氏2/data/player_135480.json (244MB) -- the cache is never loaded whole -- then:
  (a) prints the true kin word of 桑莎 (16895643) relative to the protagonist 耀国·缯松 (135480);
  (b) runs the real biography._fix_kin_roles on the shipped defective sentence and on a
      corrected variant, showing whether the post-pass can see the slip at all;
  (c) asserts the material rows the model actually received, by line number, in logs/prompts.log.

Output: logs/v107/v107_kin_subject.txt (UTF-8).
"""
import io
import json
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import biography as bio           # noqa: E402
import facts as F                 # noqa: E402

SRC = os.path.join(ROOT, "output", "洪氏2", "data", "player_135480.json")
LOG = os.path.join(ROOT, "logs", "prompts.log")
OUT = os.path.join(ROOT, "logs", "v107_kin_subject.txt")

PID = 135480                # 残忍者耀国·缯松
SANG = 16895643             # 桑莎·洪堡（传主之妹兼元配，布里基纳之母）
BRI = 33706092              # 伦斯特伯爵布里基纳·耀国松
KEL = 83995743              # 圣科林布·耀国松

CASES = [
    ("成稿原句（终传 218）",
     "布里基纳·耀国松生于1036年5月24日，盖尔韦堡。孩子的妹妹是桑莎·洪堡——"
     "既是耀国·缯松的妹妹，又是他的第一任儿子。这一重身份，布里基纳自小就弄不明白。"),
    ("同一句的「母/妻」变体",
     "布里基纳·耀国松生于1036年5月24日，盖尔韦堡。孩子的母亲是桑莎·洪堡——"
     "既是耀国·缯松的妹妹，又是他的第一任妻子。"),
    ("成稿原句（第6个十年 182）",
     "他是残忍者耀国·缯松的第三子，妹妹是桑莎·洪堡——那位既是耀国的妹妹又是他元配的女人。"),
    ("对照：把「妹妹」写成「母亲」后仍无救",
     "布里基纳·耀国松的母亲是桑莎·洪堡，本为其妹妹。"),
]

lines = []
FAILS = []


def w(s=""):
    lines.append(s)


def claim(ok, text):
    w(("  [OK]   " if ok else "  [FAIL] ") + text)
    if not ok:
        FAILS.append(text)


def find_key(fp, needle):
    fp.seek(0)
    chunk = 4 << 20
    tail = b""
    off = 0
    while True:
        buf = fp.read(chunk)
        if not buf:
            return -1
        data = tail + buf
        i = data.find(needle)
        if i != -1:
            return off - len(tail) + i
        tail = data[-len(needle):]
        off += len(buf)


def read_object(fp, start):
    fp.seek(start)
    depth = 0
    out = []
    in_str = False
    esc = False
    started = False
    while True:
        buf = fp.read(1 << 16)
        if not buf:
            break
        for ch in buf.decode("utf-8", "replace"):
            out.append(ch)
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
                if started and depth == 0:
                    return "".join(out)
    return "".join(out)


def field(text, key):
    m = re.search(r'"%s":("(?:[^"\\]|\\.)*"|true|false|null|\[[^\]]*\]|\d+)' % re.escape(key),
                  text)
    if not m:
        return ""
    raw = m.group(1)
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except Exception:
            return raw.strip('"')
    return raw


def read_record(fp, cid):
    off = find_key(fp, ('"%d":{' % cid).encode())
    if off < 0:
        return off, None, None
    rec = read_object(fp, off)
    m = re.search(r'"family":\{', rec)
    if m:
        fam_off = off + len(rec[:m.start()].encode("utf-8")) + len('"family":')
        fam = json.loads(read_object(fp, fam_off))
    else:
        fam = {}
    return off, rec, fam


def main():
    w("=" * 78)
    w("v107 取证 · 「孩子的妹妹是桑莎·洪堡」为何改不动")
    w("=" * 78)
    w("对象：output/洪氏2/耀国·缯松(1003)_终传_1075_09_08.md:218；传主 pid 135480。")
    w()

    # ---------------------------------------------------------------- 第 2 层 素材
    w("-" * 78)
    w("第 2 层 · 该请求实发的素材行（logs/prompts.log）")
    w("-" * 78)
    L = io.open(LOG, encoding="utf-8").read().split("\n")

    def at(n):
        return L[n - 1]

    def find(need):
        """First line number holding `need` (logs/prompts.log is rewritten by every run, so the probe
        anchors on content, not on line numbers)."""
        for i, s in enumerate(L, 1):
            if need in s:
                return i, s
        return None, ""

    head, _ = find("家室档案·布里基纳·耀国松")
    claim(head is not None,
          "logs/prompts.log 有「家室档案·布里基纳·耀国松」块头（实测 %s）" % head)
    for need, tag in (("母桑莎·洪堡。", "布里基纳档案自带「母」行"),
                      ("1038年1月5日，母亲桑莎·洪堡去世。", "事件行亦称「母亲」"),
                      ("妻子兼妹妹桑莎·洪堡", "传主家室：妻室行"),
                      ("兄弟姊妹桑莎·洪堡，曾为其妻。", "传主档案：兄弟姊妹行")):
        ln, s = find(need)
        claim(ln is not None, "prompts.log 含「%s」（%s）→ %s" % (need, tag, s.strip()[:110]))
    claim(find("母桑莎·洪堡")[0] is not None and find("妻子兼妹妹桑莎·洪堡")[0] is not None,
          "同一日志内 桑莎 同时以「母」（对布里基纳）与「妹妹」（对传主）出现")
    w()
    w("  日志里 桑莎 的几种写法（行号随重生成变化，按内容锚定）：")
    for need, tag in (("母桑莎·洪堡。", "布里基纳档案（对象=布里基纳）"),
                      ("1038年1月5日，母亲桑莎·洪堡去世。", "布里基纳事件行（对象=布里基纳）"),
                      ("妻子兼妹妹桑莎·洪堡", "传主家室（对象=传主）"),
                      ("兄弟姊妹桑莎·洪堡，曾为其妻。", "传主档案（对象=传主）")):
        ln, s = find(need)
        w("    prompts.log:%-6s [%s] %s" % (ln, tag, s.strip()[:110]))
    w()
    # the children run itself: v107 turned it from one 「子…，女…」 line into 「儿子：」+ one name
    # per line. The log is appended to across generations, so the newest form is the last occurrence.
    kids_ln, old_ln = None, None
    for i, s in enumerate(L, 1):
        if s == "儿子：":
            kids_ln = i
        if "子爱尔兰王子耀国·耀国松" in s:
            old_ln = i
    if kids_ln:
        w("  子女行（prompts.log:%d，v107 形态：带头 + 逐人一行）：" % kids_ln)
        for i in range(kids_ln - 1, min(kids_ln + 3, len(L))):
            w("    " + L[i].strip()[:110])
        claim("　" in L[kids_ln], "prompts.log:%d 的下一行是缩进姓名（全角空格）" % (kids_ln + 1))
        if old_ln:
            w("    （同日志 :%d 还留着更早一版的单行旧形态「子…，女…」，来自旧日志世代）" % old_ln)
    elif old_ln:
        w("  子女行（prompts.log:%d，v106 旧形态：单行「子…，女…」）：" % old_ln)
        w("    " + L[old_ln - 1].strip()[:200])
        claim(False, "日志仍是旧子女行形态（该日志生成于 v107 之前）")
    w()

    # ---------------------------------------------------------------- 第 4 层 事实
    w("-" * 78)
    w("第 4 层 · kin_word(桑莎 相对 传主) 到底是什么（真实缓存，只抽 3 条记录）")
    w("-" * 78)
    with io.open(SRC, "rb") as fp:
        chars = {}
        for cid in (PID, SANG, BRI):
            off, rec, fam = read_record(fp, cid)
            if off < 0:
                continue
            chars[str(cid)] = {"family": fam, "female": field(rec, "female") == "true",
                              "name_full": field(rec, "name_full"),
                              "name_zh": field(rec, "name_zh"),
                              # birth decides 姊/妹 and 兄/弟; without it the archive falls back to
                              # the unordered 姊妹 and the probe would lie about the true word
                              "birth": field(rec, "birth"),
                              "death": {"date": field(rec, "date")},
                              "first_name": field(rec, "first_name")}
        cache = {"player_id": PID, "characters": chars}
        w("  取到记录：%s" % {k: (v.get("name_full"), v.get("name_zh"), v.get("birth"))
                          for k, v in chars.items()})
        fam_p = chars.get(str(PID), {}).get("family") or {}
        w("  传主 family：primary_spouse=%s spouse=%s child=%s siblings=%s father=%s mother=%s"
          % (fam_p.get("primary_spouse"), fam_p.get("spouse"),
             (fam_p.get("child") or [])[:4], fam_p.get("siblings"),
             fam_p.get("father"), fam_p.get("mother")))
        wd = F.kin_word(cache, PID, SANG, chars=chars)
        wd2 = F.kin_word(cache, BRI, SANG, chars=chars)
        w("  kin_word(传主 → 桑莎) = %r" % wd)
        w("  kin_word(布里基纳 → 桑莎) = %r" % wd2)
        claim(wd == "妹妹", "kin_key 把 桑莎 相对传主 判为「妹妹」（血缘压过姻亲），实测 %r" % wd)
        claim(wd2 == "母亲" or wd2 == "母", "kin_key 把 桑莎 相对布里基纳 判为母亲类词，实测 %r" % wd2)

        w()
        w("  于是 _fix_kin_roles 的判据是：名字前 12 字里最后一个亲缘词，必须等于该人**相对传主**的真词。")
        w("  桑莎 相对传主 的真词就是「妹妹」——所以「孩子的妹妹是桑莎」在这道闸门看来完全合规。")
        w()
        facts = {"_facts": types.SimpleNamespace(), "characters": {}}
        # the live run binds a real Facts instance, whose kin_chain_words_for(桑莎, 传主) is
        # [妻子, 妹妹]; these are the words the pass refuses to touch. Emulate it so the proof does
        # not rest on the stub's AttributeError path (which only widens the rewrite).
        _CHAIN = {(SANG, PID): ["妻子", "妹妹", "族侄女"],
                  (SANG, BRI): ["母亲"]}

        def _chain_of(cid, subj):
            return list(_CHAIN.get((int(cid), int(subj)), []))

        _chain = types.SimpleNamespace(kin_chain_words_for=_chain_of)
        facts_live = {"_facts": _chain, "characters": {}}
        # the section's subject: 诸子行迹·布里基纳 runs with members=[布里基纳], so a possessive
        # with no nameable possessor (「孩子」) belongs to that child, not to the protagonist
        for label, txt in CASES:
            out = bio._fix_kin_roles(txt, facts, cache)
            out_live = bio._fix_kin_roles(txt, facts_live, cache)
            out_subj = bio._fix_kin_roles(txt, facts_live, cache, subject_ids=[BRI])
            w("  == %s" % label)
            w("     in            : %s" % txt)
            w("     out(传主段)    : %s" % out_live)
            w("     out(布里基纳段): %s" % out_subj)
            w("     changed       : 传主段=%s 布里基纳段=%s"
              % (out_live != txt, out_subj != txt))
            w()
        cur = bio._fix_kin_roles(CASES[0][1], facts_live, cache)
        claim(cur == CASES[0][1], "成稿原句在传主段经 _fix_kin_roles 后逐字不变（传主视角下「妹妹」合规）")
        fixed = bio._fix_kin_roles(CASES[0][1], facts_live, cache, subject_ids=[BRI])
        claim("孩子的母亲是桑莎·洪堡" in fixed,
              "★主修：成稿原句在布里基纳段被改回「孩子的母亲是桑莎·洪堡」→ %s" % fixed)
        cur3 = bio._fix_kin_roles(CASES[2][1], facts_live, cache, subject_ids=[BRI])
        claim("妹妹是桑莎" not in cur3,
              "第 6 个十年原句在布里基纳段不再写「妹妹是桑莎」→ %s" % cur3)
        fix_me = bio._fix_kin_roles(CASES[3][1], facts_live, cache, subject_ids=[BRI])
        claim("布里基纳·耀国松的母亲是桑莎" in fix_me,
              "对照：正确句「布里基纳的母亲是桑莎·洪堡」在布里基纳段保持逐字不变 → %s" % fix_me)
        # a multi-role chain is correct prose (user 2026-10-06) and is never shortened to one word
        for chain_in in ("他的妻子兼妹妹兼族侄女是桑莎·洪堡。",
                         "他的妻子兼妹妹是桑莎·洪堡。"):
            chain_out = bio._fix_kin_roles(chain_in, facts_live, cache)
            claim(chain_out == chain_in, "兼链逐字保留：%s → %s" % (chain_in, chain_out))

    # ---------------------------------------------------------------- 第 3 层 渲染
    w("-" * 78)
    w("第 3 层 · 子/女 行是谁拼的、为何不是「儿子：」「女儿：」")
    w("-" * 78)
    bio_src = io.open(os.path.join(ROOT, "biography.py"), encoding="utf-8").read().split("\n")
    fa_src = io.open(os.path.join(ROOT, "facts.py"), encoding="utf-8").read().split("\n")

    def cite(src, name, needle, ln=None):
        for i, s in enumerate(src, 1):
            if needle in s and (ln is None or i == ln):
                w("    %s:%d  %s" % (name, i, s.strip()))
                return i
        claim(False, "%s 里找不到「%s」" % (name, needle))
        return None

    w("  (a) 逐人档案的两段式（facts 出字段 → biography 拼行）：")
    cite(fa_src, "facts.py", 'p["children_sons"] = "、".join(')
    cite(fa_src, "facts.py", 'prof["children_sons"] = "、".join(')
    cite(bio_src, "biography.py",
         'for _label, _key in (("儿子", "children_sons"), ("女儿", "children_daughters")):')
    w("    ⇒ v107 起：先出一行「儿子：」，再把该组按「、」拆开、每人一行（全角空格缩进）；")
    w("      女儿组同形另起一行，性别字段缺失时退回「子女：」。v107 之前这里是")
    w("      child_bits 拼「子A、B，女C」的单行形态（本次已删）。")
    w()
    w("  (b) 终传附录世系走的是另一套（facts._genealogy）：")
    cite(fa_src, "facts.py", '("children_by_sex", ""), ("siblings", "兄弟姊妹"),')
    w("    ⇒ v107 起同改带头 + 逐人一行（`_is_female` 分组），档案面与附录面形态一致。")
    w()
    w("  (c) 已写进测试的现状（改格式会打到它们）：")
    for pat in ("children_sons", "children_daughters"):
        for f_ in ("verify_fast.py", "verify_v106.py"):
            p = os.path.join(ROOT, "tools", "tests", f_)
            for i, s in enumerate(io.open(p, encoding="utf-8").read().split("\n"), 1):
                if pat in s:
                    w("    tools/tests/%s:%d  %s" % (f_, i, s.strip()))
    w()

    w("=" * 78)
    w("断言失败 %d 条" % len(FAILS))
    for f_ in FAILS:
        w("  - " + f_)
    w("=" * 78)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    sys.stdout.write("wrote %s (%d lines), FAILS=%d\n" % (OUT, len(lines), len(FAILS)))
    for f_ in FAILS:
        print("  FAIL:", f_)


if __name__ == "__main__":
    main()
