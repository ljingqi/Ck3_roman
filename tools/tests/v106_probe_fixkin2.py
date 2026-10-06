# -*- coding: utf-8 -*-
"""v106 probe 2: reproduce the 父亲 corruption from `biography._fix_kin_roles`.

Builds a minimal cache from output/洪氏2/data/player_117484775.json (streamed seeks; the 121MB
cache is never loaded whole) plus the rendered character names of the matching snapshot, then runs
the real post-pass on the sentences the model was asked to write.

Cases 1-3 are the *correct* forms; if the pass turns them into 父亲, the defect is program-side.
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
SNAP = os.path.join(ROOT, "output", "洪氏2", "data", "snap_117484775_final.json")
OUT = os.path.join(ROOT, "logs", "v106_fixkin_probe2.txt")
PID = 117484775

CASES = [
    ("1 材料句（妻室行）",
     "妻室爱尔兰公主海伦·耀国斯多蒂尔，本为其妹妹；洪琰，本为其三从堂妹；"
     "时尚公主于尔娃·耀国斯多蒂尔，本为其妹妹；肯特女公爵埃德伯·索雷德斯多蒂尔。"),
    ("2 材料句（御前会议）",
     "御前会议六席：掌玺大臣圣地守护者哈夫丹·拉金、军事统帅伦斯特公爵西蒙·耀国松、"
     "配偶爱尔兰公主海伦·耀国斯多蒂尔、间谍首脑布雷夫讷伯爵乔丹·耀国松。"),
    ("3 成稿句的样子（模型照材料写对）",
     "他的第一位妻室是海伦·耀国斯多蒂尔，本为其妹妹，今为其妻。"
     "第三位妻室是于尔娃·耀国斯多蒂尔，本为其妹妹。"),
    ("4 已发布的病句（对照，看 pass 是否再动它）",
     "军事统帅伦斯特公爵西蒙·耀国松、父亲爱尔兰公主海伦·耀国斯多蒂尔、间谍首脑乔丹·耀国松。"),
    ("5 无 耀国 之名时（对照）",
     "他的第一位妻室是海伦，本为其妹妹，今为其妻。"),
]


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
    depth, out, in_str, esc, started = 0, [], False, False, False
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
    snap = json.load(io.open(SNAP, encoding="utf-8"))
    fchars = snap["facts"].get("characters") or {}
    lines = []
    with io.open(SRC, "rb") as fp:
        off = find_key(fp, ('"%d":{' % PID).encode())
        rec = read_object(fp, off)
        m = re.search(r'"family":\{', rec)
        fam = json.loads(read_object(fp, off + len(rec[:m.start()].encode()) + 9))
        wanted = sorted({int(x) for k in fam for x in (fam.get(k) or [])
                         if isinstance(x, int)})
        chars = {str(PID): {"family": fam, "female": False}}
        for cid in wanted:
            o = find_key(fp, ('"%d":{' % cid).encode())
            if o < 0:
                continue
            r = read_object(fp, o)
            mf = re.search(r'"family":\{', r)
            cf = json.loads(read_object(fp, o + len(r[:mf.start()].encode()) + 9) if mf else "{}")
            chars[str(cid)] = {"family": cf, "female": field(r, "female") == "true",
                               "name_full": field(r, "name_full"),
                               "name_zh": field(r, "name_zh")}
        cache = {"player_id": PID, "characters": chars}
        facts = {"_facts": types.SimpleNamespace(), "characters": fchars}
        lines.append("names the post-pass may match (id, cache name_full, cache name_zh,"
                     " facts name, true word):")
        for cid in wanted:
            rec2 = chars.get(str(cid))
            if not rec2:
                continue
            try:
                tw = F.kin_word(cache, PID, cid, chars=chars)
            except Exception as e:
                tw = "ERR %s" % e
            lines.append("  %-10d %-16s %-10s %-22s %s"
                         % (cid, rec2.get("name_full") or "", rec2.get("name_zh") or "",
                            (fchars.get(str(cid)) or {}).get("name") or "", tw))
        lines.append("")
        for label, txt in CASES:
            out = bio._fix_kin_roles(txt, facts, cache)
            lines.append("== %s" % label)
            lines.append("   in : %s" % txt)
            lines.append("   out: %s" % out)
            lines.append("   changed: %s" % (out != txt))
            lines.append("")
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
