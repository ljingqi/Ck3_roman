# -*- coding: utf-8 -*-
"""v107 probe: why the "孩子的妹妹是桑莎·洪堡" class survives every kin-word fix.

Read-only. Streams the family block of a handful of characters out of
output/洪氏2/data/player_135480.json (244MB) -- the cache is never loaded whole -- then:
  (a) prints the true kin word of 桑莎 (16895643) relative to the protagonist 耀国·缯松 (135480);
  (b) runs the real biography._fix_kin_roles on the shipped defective sentence and on a
      corrected variant, showing whether the post-pass can see the slip at all;
  (c) asserts the material rows the model actually received, by line number, in logs/prompts.log.

Output: logs/v107_kin_subject.txt (UTF-8).
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

    # the request whose title line is 《诸子行迹·布里基纳·耀国松》
    head = None
    for i, s in enumerate(L, 1):
        if s.startswith("家室档案·布里基纳·耀国松"):
            head = i
    claim(head == 1955, "logs/prompts.log:1955 是「家室档案·布里基纳·耀国松」块头（实测 %s）" % head)
    for ln, need, tag in ((1964, "母桑莎·洪堡。", "布里基纳档案自带「母」行"),
                          (1967, "1038年1月5日，母亲桑莎·洪堡去世。", "事件行亦称「母亲」")):
        s = at(ln)
        claim(need in s, "prompts.log:%d 含「%s」（%s）→ %s" % (ln, need, tag, s.strip()))
    # the same request also labels 桑莎 as the protagonist's sister, twice
    for ln, need, tag in ((2043, "妻子兼妹妹桑莎·洪堡", "传主家室：妻室行"),
                          (2049, "兄弟姊妹桑莎·洪堡，曾为其妻。", "传主档案：兄弟姊妹行")):
        s = at(ln)
        claim(need in s, "prompts.log:%d 含「%s」（%s）" % (ln, need, tag))
    claim("母桑莎·洪堡" in at(1964) and "妻子兼妹妹桑莎·洪堡" in at(2043),
          "同一请求内 桑莎 同时以「母」（对布里基纳）与「妹妹」（对传主）出现")
    w()
    w("  该请求里 桑莎 的三种写法：")
    for ln, tag in ((1964, "布里基纳档案（对象=布里基纳）"),
                    (1967, "布里基纳事件行（对象=布里基纳）"),
                    (2043, "传主家室（对象=传主）"),
                    (2049, "传主档案（对象=传主）")):
        w("    prompts.log:%-5d [%s] %s" % (ln, tag, at(ln).strip()))
    w()
    # the children run itself
    kids = at(2044)
    w("  子女行（prompts.log:2044，一行两段，无逐人母系）：")
    w("    " + kids)
    m = re.match(r"^子(.*?)，女(.*)。$", kids)
    claim(bool(m), "prompts.log:2044 是「子…，女…」单行两句式（子/女 用「，」相接）")
    if m:
        sons = [x for x in m.group(1).split("、") if x]
        daus = [x for x in m.group(2).split("、") if x]
        w("    → 子 %d 人、女 %d 人；桑莎的三个儿子正是子列表的前三名：%s"
          % (len(sons), len(daus), "、".join(sons[:3])))
        claim(all("桑莎" not in x for x in sons + daus),
              "子女行内没有任何一处写出「桑莎」或母系，子/女的归属只能靠行外信息")
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
        _chain = types.SimpleNamespace(
            kin_chain_words_for=lambda cid, subj: (["妻子", "妹妹"] if int(cid) == SANG else []))
        facts_live = {"_facts": _chain, "characters": {}}
        for label, txt in CASES:
            out = bio._fix_kin_roles(txt, facts, cache)
            out_live = bio._fix_kin_roles(txt, facts_live, cache)
            w("  == %s" % label)
            w("     in       : %s" % txt)
            w("     out(stub) : %s" % out)
            w("     out(live) : %s" % out_live)
            w("     changed   : stub=%s live=%s" % (out != txt, out_live != txt))
            w()
        cur = bio._fix_kin_roles(CASES[0][1], facts_live, cache)
        claim(cur == CASES[0][1], "成稿原句经 _fix_kin_roles 后逐字不变（后处理看不见这处错）")
        cur3 = bio._fix_kin_roles(CASES[2][1], facts_live, cache)
        claim(cur3 == CASES[2][1], "第 6 个十年原句经 _fix_kin_roles 后逐字不变")
        fix_me = bio._fix_kin_roles(CASES[3][1], facts_live, cache)
        claim("布里基纳·耀国松的妹妹是桑莎" in fix_me,
              "对照：正确句「布里基纳的母亲是桑莎·洪堡」被后处理改写成「…的妹妹是桑莎·洪堡」"
              "（后处理会**制造**这类病句）→ %s" % fix_me)

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
    cite(bio_src, "biography.py", 'child_bits.append(f"子{p[\'children_sons\']}")')
    cite(bio_src, "biography.py", 'child_bits.append(f"女{p[\'children_daughters\']}")')
    cite(bio_src, "biography.py", 'lines.append("，".join(child_bits) + "。")')
    w("    ⇒ 子组与女组共用**一行**，行内用「，」相接；组内用「、」。没有任何")
    w("      代码产出「儿子：/女儿：」这种带头、分行、逐人一行的形态。")
    w()
    w("  (b) 终传附录世系走的是另一套（facts._genealogy），连子/女都没分：")
    cite(fa_src, "facts.py", '("child", "子女"), ("siblings", "兄弟姊妹")')
    w("    ⇒ 档案面与附录面各写一遍，两处都不是用户要的格式。")
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
