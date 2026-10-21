# -*- coding: utf-8 -*-
"""v109 取证探针（只读快照，秒级，不整载熔件）。

回答三件事：
1) 问题 2：`传主家室` 块下发给哪些板块；该块里的人名在本板块其余素材里出现几个
   （出现 0 个 = 这块对这个板块没有意义）。
2) 问题 3：刺客列传的死者行现状（`死者：…` / `…死于<地点>。` 两行）逐字形态。
3) 问题 4：历代记锚定的头衔是什么（`本朝：` 行 / `主角本朝任期` / 篇题）。

用法：
    & tools\\py.ps1 tools\\tests\\v109_probe_household.py
输出：logs/v109/v109_household.txt（UTF-8）
"""
import glob
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

OUT = io.StringIO()


def w(s=""):
    OUT.write(str(s) + "\n")


SNAP_GLOB = os.path.join(ROOT, "output", "洪氏2", "data", "*.json")
# 只要 v1xx 快照（含 blocks/messages）；事实面 json 也在同目录，用 meta 判定
SNAP_HINT = ("v105b", "v106_", "v107", "snap_117484775_final", "snap_135480_final",
             "snap_v103", "v104.json", "v103_new", "67172818_v105", "snap_v100.json",
             "snap_v101.json", "snap_v95_base_final", "v98_era_d1", "v98_era_d2",
             "v98_era_d3", "v102.json", "v106_117484775")


def load_snap(path):
    try:
        if os.path.getsize(path) > 30 * 1024 * 1024:
            return None
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    if not (isinstance(d, dict) and isinstance(d.get("blocks"), dict)
            and isinstance(d.get("meta"), dict)):
        return None
    if "player_id" not in d["meta"]:
        return None
    return d


def household_names(text, facts):
    """`传主家室` 块里的人名：父母/兄弟姊妹/妻室/子女各行的名字。"""
    out = set()
    chars = (facts or {}).get("characters") or {}
    id2name = {}
    for cid, rec in chars.items():
        nm = (rec or {}).get("name")
        if nm:
            id2name[nm] = cid
    for nm in id2name:
        if nm and nm in text:
            out.add(nm)
    return out


def main():
    w("=" * 90)
    w("v109 探针：传主家室下发面 / 刺客列传死者行 / 历代记锚定头衔")
    w("只读快照（不整载熔件）；来源 output/洪氏2/data/*.json")
    w("=" * 90)
    for path in sorted(glob.glob(SNAP_GLOB)):
        base = os.path.basename(path)
        if not any(h in base for h in SNAP_HINT):
            continue
        d = load_snap(path)
        if d is None:
            continue
        meta = d["meta"]
        blocks = d["blocks"]
        facts = d.get("facts") or {}
        w("")
        w("-" * 90)
        w("[快照] %s  pid=%s as_of=%s decade=%s articles=%s"
          % (base, meta.get("player_id"), meta.get("as_of"), meta.get("decade"),
             meta.get("articles")))
        pid = str(meta.get("player_id"))
        prec = (facts.get("characters") or {}).get(pid) or {}
        pname = prec.get("name") or ""
        w("    传主=%s" % pname)
        # ---- 问题 2：每板块的 传主家室 ----
        for sec, bd in blocks.items():
            if not isinstance(bd, dict) or "传主家室" not in bd:
                continue
            home = bd.get("传主家室") or ""
            others = "\n".join(v for k, v in bd.items() if k != "传主家室")
            lines = [x for x in home.split("\n") if x.strip()]
            # 该块出现的所有人物名（按 facts.characters 里的名字匹配）
            names = household_names(home, facts)
            hit = sorted(n for n in names if n in others)
            miss = sorted(n for n in names if n not in others)
            w("  [%s] 传主家室 %d 行 / %d 字节；人名 %d 个；"
              "在本板块其余素材里出现 %d 个、缺席 %d 个"
              % (sec, len(lines), len(home.encode("utf-8")), len(names),
                 len(hit), len(miss)))
            if miss:
                w("      缺席：%s" % "、".join(miss[:25]))
            # 行级：丢掉「本行没有任何人在其余素材里出现」的家室行后，剩几行
            kept = 0
            for ln in lines:
                hit_ln = any(n in ln and n in others for n in names)
                if hit_ln:
                    kept += 1
            w("      行级过滤：%d 行中 %d 行有出场（丢 %d 行 / %d 字节）"
              % (len(lines), kept, len(lines) - kept,
                 sum(len(x.encode("utf-8")) + 1 for x in lines
                     if not any(n in x and n in others for n in names))))
        # ---- 问题 4：锚定头衔一览 ----
        _prot = facts.get("protagonist") or {}
        _chao = None
        for sec, bd in blocks.items():
            if isinstance(bd, dict) and "王朝历代" in bd:
                _chao = (bd["王朝历代"] or "").split("\n")[0]
                break
        w("  [锚定] 政体=%s ｜ 现任头衔=%s ｜ 王朝历代首行=%s"
          % (_prot.get("government"), _prot.get("label") or _prot.get("name"), _chao))
        for ln in (_prot.get("court_office_changes") or [])[:6]:
            w("      朝廷职位变更：" + str(ln))
        for ln in (_prot.get("succession") or [])[:4]:
            w("      承继：" + str(ln))
        # ---- 问题 3：刺客列传材料 ----
        for sec, bd in blocks.items():
            if not sec.startswith("assassins"):
                continue
            body = (bd or {}).get("刀下诸魂") or ""
            w("  [%s] 刀下诸魂 %d 字节" % (sec, len(body.encode("utf-8"))))
            for ln in body.split("\n"):
                if ln.startswith("死者：") or re.match(r"^.+死于.+。$", ln):
                    w("      | " + ln)
        # ---- 问题 4：历代记锚定 ----
        for sec, bd in blocks.items():
            if not sec.startswith("chaoju"):
                continue
            for key in ("王朝历代", "王朝历代·纪事", "本朝治所与任期", "本朝现任"):
                txt = (bd or {}).get(key)
                if not txt:
                    continue
                first = txt.split("\n")[0]
                w("  [%s] %s：%s" % (sec, key, first[:160]))
            # 篇题
            msgs = (d.get("messages") or {}).get(sec) or {}
            usr = msgs.get("user") or ""
            m = re.search(r"本篇文章标题已定为《([^》]+)》", usr)
            if m:
                w("      [%s] 篇题 = %s" % (sec, m.group(1)))
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    p = os.path.join(ROOT, "logs", "v109_household.txt")
    with open(p, "w", encoding="utf-8") as fp:
        fp.write(OUT.getvalue())
    print("written", p, len(OUT.getvalue()), "bytes")


if __name__ == "__main__":
    main()
