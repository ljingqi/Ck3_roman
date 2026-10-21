# -*- coding: utf-8 -*-
"""v116 一次性文本手术：把 `output/洪氏2` 成稿里的行政制子女称号换成游戏词表的词。

只改「称号词」两个字（前缀不动）：`山南王子` → `山南公子`、`山南郡主` → `山南公女`、
`天王子` → `天皇子`、`唐公主` → `唐皇女` …（v116 用户裁决：行政制封臣用游戏封臣支
公子/公女；皇帝本人（独立君主）的子女一并按游戏词表 皇子/皇女）。

为什么不重生成：项目定规「绝不用模型重生成既有正文」。所以按 (前缀, 旧词) → (前缀, 新词)
逐串替换，每一处都先在存档上**复算并自校验**：

  * 命中 = 成稿里 `前缀+词`，前缀取自熔件里 rank ≥ kingdom 的头衔名／朝名（含「大X」形）；
  * 词后若有名字（可带绰号/圣号），在缓存姓名表里反查人物 cid；
  * 人物 → 走生产路径 `_style_parent_title` 选排名最高的父/母 → 该父/母的头衔；
  * 旧词 = 旧口径复算（`_title_government(tid, 文章当日)` + `_is_independent(父, 文章当日)`）；
    新词 = 新口径复算（`_parent_child_government` + `_parent_child_independent`）；
  * **旧词必须与成稿里那个词逐字相同**才认这条替换（自校验），否则进「待人工核对」；
  * 绰号／圣号里的字样（如某人绰号「时尚王子」）整条跳过，不参与替换。

用法：
    python -X utf8 tools/fix_v116_prince_word.py --dry      # 只出表（默认）
    python -X utf8 tools/fix_v116_prince_word.py --apply    # 落盘 + 存 logs/v116/v116_prince_backup.json
    python -X utf8 tools/fix_v116_prince_word.py --restore  # 回退
"""
import collections
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402

FOLDER = "洪氏2"
PID = 207044
BASE = os.path.join(ROOT, "output", FOLDER)
BACKUP = os.path.join(ROOT, "logs", "v116_prince_backup.json")
WORDS = ("王子", "郡主", "公主", "皇女", "皇子", "公子", "公女")
FEMALE_WORDS = {"郡主", "公主", "皇女", "公女"}
VOL_RE = re.compile(r"_(\d{1,4})_(\d{2})_(\d{2})\.md$")


def data_dir():
    return os.path.join(BASE, "data")


def melt_path():
    data = data_dir()
    if os.environ.get("V116_MELT"):
        return os.environ["V116_MELT"]
    melts = [x for x in os.listdir(data)
             if x.startswith("melt_") and "_idx" not in x
             and x.endswith((".json", ".json.xz", ".json.gz"))]

    def key(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)

    return os.path.join(data, max(melts, key=key))


def volume_date(fn):
    """文章当日：文件名末尾日期；终传（实跑 as_of=None）返回 None。"""
    m = VOL_RE.search(fn)
    if not m or "终传" in fn:
        return None
    return "%d.%d.%d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def md_files():
    return [fn for fn in sorted(os.listdir(BASE)) if fn.endswith(".md")]


def load_context():
    data = data_dir()
    cache = json.load(io.open(os.path.join(data, "player_%d.json" % PID), encoding="utf-8"))
    melt = cl.load_melt(melt_path())
    campaign = {}
    caches = {}
    for fn in os.listdir(data):
        m = re.match(r"player_(\d+)\.json$", fn)
        if not m:
            continue
        try:
            c = json.load(io.open(os.path.join(data, fn), encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            continue
        caches[int(m.group(1))] = c
        if c.get("playthrough_id") == cache.get("playthrough_id"):
            campaign[int(m.group(1))] = c
    names = os.path.join(data, "names.json")
    if not os.path.exists(names):
        names = os.path.join(ROOT, "data", "names.json")
    f = F.Facts(cache, melt, names, campaign=campaign or None)
    return f, cache, caches, campaign, melt


def name_index(caches):
    """显示名 → cid（成稿用「洪审礼」这样的东方序全名）。先到先得，冲突时取小的 cid。"""
    idx = collections.defaultdict(set)
    for cache in caches.values():
        for cid, r in (cache.get("characters") or {}).items():
            house = r.get("house_name") or ""
            zh = r.get("name_zh") or ""
            full = r.get("name_full") or ""
            cands = [full, zh, (zh + house) if zh and house else "",
                     (house + zh) if zh and house else ""]
            for n in cands:
                if n and len(n) >= 2:
                    idx[n].add(int(cid))
    return idx


def nickname_texts(caches, melt):
    """绰号／圣号文本集合：这些字样在正文里不是称号词（如绰号「时尚王子」）。"""
    out = set()
    for cache in caches.values():
        for r in (cache.get("characters") or {}).values():
            for h in (r.get("nickname_history") or []):
                if isinstance(h, dict) and h.get("nickname"):
                    out.add(str(h["nickname"]))
            if r.get("nickname"):
                out.add(str(r["nickname"]))
    for key in ("accolades",):
        sec = melt.get(key) or {}
        if isinstance(sec, dict):
            for v in sec.values():
                if isinstance(v, dict):
                    for kk in ("name", "text", "loc", "nickname"):
                        if isinstance(v.get(kk), str) and v[kk]:
                            out.add(v[kk])
    return {t for t in out if t}


def prefix_titles(f, dates):
    """rank ≥ kingdom 的头衔：{名字: {tid}}，含朝名与「大X」形。"""
    out = collections.defaultdict(set)
    prefixes = {"h_": 6, "e_": 5, "k_": 4}
    for tid, t in (f._lt or {}).items():
        key = (t or {}).get("key") or ""
        if key[:2] not in prefixes:
            continue
        names = set()
        for d in dates:
            nm = f._name_at_date(tid, d)
            if nm:
                names.add(nm)
        rn = f.realm_name(tid)
        if rn:
            names.add(rn)
        for nm in names:
            if nm:
                out[nm].add(tid)
                if not nm.startswith("大"):
                    out["大" + nm].add(tid)
    return out


def resolve_persons(idx, tail):
    """命中后面文字里最长的缓存姓名 → 候选 cid 列表（同名者全给，交复算与自校验筛）。"""
    for ln in range(min(12, len(tail)), 1, -1):
        cand = tail[:ln]
        if cand in idx:
            return sorted(idx[cand])
    return []


def parents_of(cache, cid):
    fam = ((cache.get("characters") or {}).get(str(cid)) or {}).get("family") or {}
    out = []
    for k in ("father", "mother"):
        out.extend(int(x) for x in (fam.get(k) or []) if isinstance(x, int))
    return out


def labels_for(f, child, date):
    """(旧口径的完整称号, 新口径的完整称号) —— 都走生产入口 `_parent_prince_style`。

    旧口径 = 把两个新助手换成 v115 的读法（政体取自头衔侧、独立性取 `_is_independent`，
    None 记作独立）。这样「旧口径复算」得到的是完整称号串，可与成稿逐字比对。"""
    cur_gov, cur_ind = f._parent_child_government, f._parent_child_independent

    def old_gov(owner, tid, date, title_gov=None):
        return f._title_government(tid, date) if title_gov is None else title_gov

    def old_ind(owner, date):
        v = f._is_independent(owner, date)
        return True if v is None else v

    try:
        f._parent_child_government = old_gov
        f._parent_child_independent = old_ind
        old = f._parent_prince_style(child, date) or ""
    finally:
        f._parent_child_government, f._parent_child_independent = cur_gov, cur_ind
    new = f._parent_prince_style(child, date) or ""
    return old, new


def scan(f, cache, idx, ptitles, nick, explain=()):
    """成稿里所有 `前缀+词(+名字)` 命中，逐条复算并自校验。

    同名人物可能有多个：全部候选都复算，只有「旧口径复算的完整称号 == 成稿那一段」的才算命中；
    新称号还必须仍以同一前缀开头（否则说明选错了同名者）。候选互相矛盾时列进待人工核对。"""
    prefixes = sorted(ptitles, key=len, reverse=True)
    pat = re.compile("(" + "|".join(re.escape(p) for p in prefixes) + ")("
                     + "|".join(WORDS) + ")")
    rows, bad = [], []
    for fn in md_files():
        text = io.open(os.path.join(BASE, fn), encoding="utf-8").read()
        date = volume_date(fn)
        for m in pat.finditer(text):
            pre, word = m.group(1), m.group(2)
            tail = text[m.end():m.end() + 12]
            hit = pre + word
            if any(hit in t for t in nick):
                continue
            rec = {"file": fn, "prefix": pre, "word": word, "date": date, "tail": tail}
            cands = resolve_persons(idx, tail)
            if not cands:
                bad.append(dict(rec, person=None, why="名字取不到"))
                continue
            ok = []
            for person in cands:
                if bool(((cache.get("characters") or {}).get(str(person)) or {})
                        .get("female")) != (word in FEMALE_WORDS):
                    continue
                try:
                    old, new = labels_for(f, person, date)
                except Exception as e:                             # noqa: BLE001
                    bad.append(dict(rec, person=person, why="复算异常 %s" % e))
                    continue
                if explain and any(x in hit for x in explain):
                    print("   [explain] %s %s 候选=%s 旧=%r 新=%r"
                          % (fn[:14], hit, person, old, new))
                if old != hit:
                    continue
                if not new.startswith(pre):
                    bad.append(dict(rec, person=person,
                                    why="新称号换前缀（同名者？）%r" % new))
                    continue
                ok.append(dict(rec, person=person, old=old, new=new,
                               newword=new[len(pre):]))
            if not ok:
                bad.append(dict(rec, person=cands[0], why="候选的旧口径复算都不符"))
                continue
            news = {r["newword"] for r in ok}
            if len(news) > 1:
                bad.append(dict(rec, person=ok[0]["person"],
                                why="同名候选给出不同新词 %s" % sorted(news)))
                continue
            rows.append(ok[0])
    return rows, bad


def per_file_map(rows):
    """每篇自己的 旧称号串 → 新称号串；同篇内互相矛盾时记冲突。"""
    out, conflict = {}, {}
    for r in rows:
        if not r["new"] or r["new"] == r["old"]:
            continue
        k = r["old"]
        v = r["new"]
        fm = out.setdefault(r["file"], {})
        if k in fm and fm[k] != v:
            conflict.setdefault(r["file"], {})[k] = (fm[k], v)
            continue
        fm[k] = v
    return out, conflict


def family_map(fmaps):
    """把所有「逐篇复算通过」的串合成一张全族表：同一旧串在各篇必须给同一新串。

    逐篇表会漏掉那些「本篇里没有一处能反查到人名」的命中（正文里同样的称号串却没人名），
    所以落盘用全族表：某串只要在**任一篇**被自校验通过，就对该族所有篇生效。新旧不一致的
    键（理论上同一前缀同词不该有两种新词）剔除并列出来人工裁决。"""
    out, conflict = {}, {}
    for _fn, fm in sorted(fmaps.items()):
        for k, v in fm.items():
            if k in out and out[k] != v:
                conflict.setdefault(k, {})[_fn] = v
                continue
            out[k] = v
    for k in conflict:
        out.pop(k, None)
    return out, conflict


def apply_map(mp, dry=True):
    """把全族表逐串落到 `output/洪氏2` 的每篇成稿；旧串→新串与处数记进备份。"""
    backup = {}
    files = {}
    if not dry and os.path.exists(BACKUP):
        try:
            backup = json.load(io.open(BACKUP, encoding="utf-8"))
        except Exception:                                          # noqa: BLE001
            backup = {}
    files = backup.setdefault("files", {})
    total = 0
    for fn in md_files():
        if not mp:
            continue
        path = os.path.join(BASE, fn)
        with io.open(path, encoding="utf-8", newline="") as fp:
            raw = fp.read()
        eol = "\r\n" if "\r\n" in raw else "\n"
        text = raw.replace("\r\n", "\n")
        hits = []
        for old, new in sorted(mp.items()):
            n = text.count(old)
            if n:
                text = text.replace(old, new)
                hits.append([old, new, n])
        if not hits:
            continue
        total += sum(h[2] for h in hits)
        print("  %s: %s" % (fn, "、".join("%s→%s×%d" % (a, b, n) for a, b, n in hits)))
        if dry:
            continue
        files[fn] = hits
        with io.open(path, "w", encoding="utf-8", newline="") as fp:
            fp.write(text.replace("\n", eol))
    if not dry:
        backup["map"] = mp
        with io.open(BACKUP, "w", encoding="utf-8") as fp:
            json.dump(backup, fp, ensure_ascii=False, indent=1)
    return total


def patch_sidecar(mp, dry=True):
    """阅读页用的 `data/genealogy.json`（家谱树/传主链）同串替换；原文存进备份以便回退。"""
    path = os.path.join(BASE, "data", "genealogy.json")
    if not mp or not os.path.exists(path):
        return 0, None
    with io.open(path, encoding="utf-8", newline="") as fp:
        raw = fp.read()
    text, n = raw, 0
    for old, new in sorted(mp.items()):
        k = text.count(old)
        if k:
            text = text.replace(old, new)
            n += k
    if dry or not n:
        print("  data/genealogy.json：%d 处" % n)
        return n, None
    with io.open(path, "w", encoding="utf-8", newline="") as fp:
        fp.write(text)
    print("  data/genealogy.json：%d 处（原文已备份）" % n)
    return n, raw


def do_restore():
    """回退：优先按逐篇明细回退；明细缺失时按备份里的全族表反着替换一遍。

    全族表的新串与旧串互不相交（没有「某串既是旧串又是新串」），所以反着替换一遍即可还原，
    偶有「本来就是新串」的写法被反成旧串，重跑 --apply 会再换回来。"""
    if not os.path.exists(BACKUP):
        print("没有备份：%s" % BACKUP)
        return 1
    backup = json.load(io.open(BACKUP, encoding="utf-8"))
    side = backup.get("sidecar")
    if side:
        path = os.path.join(BASE, "data", "genealogy.json")
        with io.open(path, "w", encoding="utf-8", newline="") as fp:
            fp.write(side)
        print("  已还原 data/genealogy.json")
    files = backup.get("files") or {}
    rmap = {v: k for k, v in (backup.get("map") or {}).items()}
    n = 0
    for fn in md_files():
        path = os.path.join(BASE, fn)
        with io.open(path, encoding="utf-8", newline="") as fp:
            raw = fp.read()
        eol = "\r\n" if "\r\n" in raw else "\n"
        text = raw.replace("\r\n", "\n")
        before = text
        if files.get(fn):
            for a, b, _k in files[fn]:
                text = text.replace(b, a)
        elif rmap:
            for new, old in sorted(rmap.items()):
                text = text.replace(new, old)
        if text == before:
            continue
        with io.open(path, "w", encoding="utf-8", newline="") as fp:
            fp.write(text.replace("\n", eol))
        n += 1
        print("  已还原 %s" % fn)
    print("还原 %d 篇" % n)
    return 0


def main():
    a = sys.argv[1:]
    if "--restore" in a:
        return do_restore()
    dry = "--apply" not in a
    explain = [x.split("=", 1)[1] for x in a if x.startswith("--explain=")]
    f, cache, caches, campaign, melt = load_context()
    idx = name_index(caches)
    nick = nickname_texts(caches, melt)
    dates = [volume_date(fn) for fn in md_files()]
    dates = sorted({d for d in dates if d} | {"850.1.1", "900.1.1", "950.1.1", "1000.1.1",
                                              "1050.1.1", "1100.1.1", "1150.1.1"})
    print("战役缓存 %d 份；姓名表 %d 条；绰号/圣号文本 %d 条"
          % (len(campaign), len(idx), len(nick)), flush=True)
    ptitles = prefix_titles(f, dates)
    print("rank ≥ kingdom 的头衔名 %d 个" % len(ptitles), flush=True)
    rows, bad = scan(f, cache, idx, ptitles, nick, explain=explain)
    print("\n== 命中并复算通过 %d 处；待人工核对 %d 处" % (len(rows), len(bad)))
    stat = collections.Counter()
    for r in rows:
        stat[(r["prefix"], r["old"], r["new"])] += 1
    print("\n== (前缀, 旧词) → 新词（按处数，只列会变的）")
    for (pre, old, new), n in stat.most_common():
        if old != new:
            print("  %-10s %-2s → %-2s  %d 处" % (pre, old, new, n))
    fmaps, conflict = per_file_map(rows)
    fmap, xconf = family_map(fmaps)
    print("\n== 全族替换表 %d 串；逐篇（dry，不落盘）" % len(fmap))
    total = apply_map(fmap, dry=dry)
    side_n, side_raw = patch_sidecar(fmap, dry=dry)
    if not dry and (total or side_n):
        bk = {}
        if os.path.exists(BACKUP):
            try:
                bk = json.load(io.open(BACKUP, encoding="utf-8"))
            except Exception:                                      # noqa: BLE001
                bk = {}
        bk["map"] = fmap
        if side_raw is not None:
            bk["sidecar"] = side_raw
        with io.open(BACKUP, "w", encoding="utf-8") as fp:
            json.dump(bk, fp, ensure_ascii=False, indent=1)
    if xconf:
        print("\n!! 跨篇冲突（剔除，人工裁决）:")
        for k, d in sorted(xconf.items()):
            print("   %s: %s" % (k, d))
    if conflict:
        print("\n!! 同篇内冲突（未替换该键，人工裁决）:")
        for fn, d in sorted(conflict.items()):
            for k, v in sorted(d.items()):
                print("   %s %s: %s / %s" % (fn, k, v[0], v[1]))
    if bad:
        print("\n== 待人工核对 %d 处（前 30）" % len(bad))
        for r in bad[:30]:
            print("   %s %s%s 人=%s 日=%s 因: %s 后文=%r"
                  % (r["file"], r["prefix"], r["word"], r["person"], r["date"],
                     r["why"], r["tail"][:10]))
    print("\n%s替换 %d 处%s" % ("将" if dry else "已", total,
                                "" if dry else "；备份 %s" % BACKUP))
    return 0


if __name__ == "__main__":
    sys.exit(main())
