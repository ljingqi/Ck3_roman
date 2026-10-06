# -*- coding: utf-8 -*-
"""v106 probe: why does `_fix_kin_roles` leave a wrong kin word in a terminal biography?

Reads only the byte ranges it needs out of output/洪氏2/data/player_117484775.json (121MB, streamed
with seeks -- the cache is never loaded whole), rebuilds a minimal cache from the protagonist's own
family block, then runs the real `biography._fix_kin_roles` on the published prose lines.
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

SRC = os.path.join(ROOT, "output", "洪氏2", "data", "player_117484775.json")
OUT = os.path.join(ROOT, "logs", "v106_fixkin_probe.txt")
PID = 117484775

CASES = [
    ("御前会议行 (本纪·纪事·一生大事)",
     "御前会议六席：掌玺大臣圣地守护者哈夫丹·拉金、军事统帅伦斯特公爵西蒙·耀国松、"
     "父亲爱尔兰公主海伦·耀国斯多蒂尔、间谍首脑布雷夫讷伯爵乔丹·耀国松。"),
    ("家室列传·开篇",
     "他的第一位妻室，是生于1059年9月27日的海伦·耀国斯多蒂尔——本是他的父亲，"
     "父为爱尔兰至高王残忍者耀国·缯松，母为奥斯勒伊格。"),
    ("门庭恩怨",
     "第三位是时尚公主于尔娃·耀国斯多蒂尔，本是他的父亲，原为父亲残忍者耀国·缯松之妻。"),
    ("正确句（对照）",
     "第一位妹妹是海伦·耀国斯多蒂尔，本是他同父异母的妹妹。"),
]


def find_key(fp, needle):
    """Byte offset of `needle` in the file, streamed (4MB chunks) from the start."""
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
    """Balanced `{...}` text starting at byte `start` (string-aware)."""
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


def main():
    lines = []
    with io.open(SRC, "rb") as fp:
        off = find_key(fp, ('"%d":{' % PID).encode())
        rec = read_object(fp, off)
        m = re.search(r'"family":\{', rec)
        fam_off = off + len(rec[:m.start()].encode("utf-8")) + len('"family":')
        fam_txt = read_object(fp, fam_off) if m else "{}"
        fam = json.loads(fam_txt)
        lines.append("protagonist %d  family keys=%s" % (PID, sorted(fam.keys())))
        wanted = set()
        for k in ("primary_spouse", "spouse", "former_spouses", "ever_spouses",
                  "concubine", "former_concubines", "child", "siblings", "father", "mother"):
            for x in (fam.get(k) or []):
                wanted.add(int(x))
        lines.append("relatives wanted: %d" % len(wanted))

        chars = {str(PID): {"family": fam, "female": False,
                            "name_full": field(rec, "name_full"),
                            "name_zh": field(rec, "name_zh")}}
        meta = {}
        for cid in sorted(wanted):
            o = find_key(fp, ('"%d":{' % cid).encode())
            if o < 0:
                meta[cid] = "ABSENT"
                continue
            r = read_object(fp, o)
            mf = re.search(r'"family":\{', r)
            cf_off = o + len(r[:mf.start()].encode("utf-8")) + len('"family":')
            cf = json.loads(read_object(fp, cf_off) if mf else "{}")
            chars[str(cid)] = {"family": cf, "female": field(r, "female") == "true",
                               "name_full": field(r, "name_full"),
                               "name_zh": field(r, "name_zh"),
                               "first_name": field(r, "first_name")}
            meta[cid] = (field(r, "name_full"), field(r, "name_zh"),
                         set(cf.keys()))
        # who are the spouses by name?
        for k in ("primary_spouse", "spouse", "ever_spouses", "former_spouses"):
            for x in (fam.get(k) or []):
                lines.append("  %-16s %-10s %s" % (k, x, meta.get(int(x))))
        cache = {"player_id": PID, "characters": chars}
        facts = {"_facts": types.SimpleNamespace(), "characters": {}}
        lines.append("")
        for label, txt in CASES:
            out = bio._fix_kin_roles(txt, facts, cache)
            # per-relative truth words
            truths = {}
            for cid in sorted(wanted):
                try:
                    truths[cid] = F.kin_word(cache, PID, cid, chars=chars)
                except Exception as e:
                    truths[cid] = "ERR:%s" % e
            lines.append("== %s" % label)
            lines.append("   in : %s" % txt)
            lines.append("   out: %s" % out)
            lines.append("   changed: %s" % (out != txt))
            lines.append("   truth words: %s"
                         % {k: v for k, v in truths.items() if v})
            lines.append("")
    txt = "\n".join(lines) + "\n"
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(txt)
    sys.stdout.write(txt[:4000])


if __name__ == "__main__":
    main()
