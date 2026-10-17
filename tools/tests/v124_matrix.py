"""v124 矩阵：田所2 全部人物两两成对，检查关系词（直接词与路径词）对不对。

一次载熔件，做四件事：

  A. 口径不变性 —— 先跑一遍「禁用路径词」的旧口径，再跑新口径；旧口径每一处标注必须逐字不变
     （路径词只补空白），板块文本的差异只能是路径词插入。
  B. 新增标注 —— 全部是路径词，且只落在旧口径无词的对上。
  C. N×N 矩阵 —— N = 板块里出现过的全部人物（`name_index` ∪ 标注 cid ∪ 死者 ∪ 传主）。
     每个有序对算：首词（直接词，`paths=False`）与路径词。逐项检查
       1 自身/缺省为空；2 路径词结构（2–3 段、末段亲缘或关系）；3 路径词能独立复算（锚点存在）；
       4 路径词只在直接词为空时出现；5 亲缘词的性别蕴含与缓存性别一致；
       6 长幼词与生年一致；7 亲缘/关系两个方向都出词（单向断开即报）。
  D. 落盘 —— `logs/v124_matrix_<家族>.tsv`（只写非空单元）与 `logs/v124_matrix_<家族>.txt`（报告）。

用法：
  & tools\\py.ps1 tools\\tests\\v124_matrix.py [快照] [--max-people=N]
默认快照 output/田所2/data/v122_final4.json。
"""
import collections
import json
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

OUT = []
FAIL = 0
import facts as F                                              # noqa: E402


def w(s=""):
    OUT.append(str(s))
    print(s)


def check(name, ok, detail=""):
    global FAIL
    if not ok:
        FAIL += 1
    w(("  PASS  " if ok else "  FAIL  ") + name + (f"   [{detail}]" if not ok else ""))


# ---- sex / seniority implied by a kin word ------------------------------------------------
_SEX_TOKENS = {
    "male": "M", "female": "F", "brother": "M", "sister": "F", "father": "M", "mother": "F",
    "son": "M", "daughter": "F", "husband": "M", "wife": "F", "uncle": "M", "aunt": "F",
    "nephew": "M", "niece": "F", "grandson": "M", "granddaughter": "F",
    "grandfather": "M", "grandmother": "F",
}
# Sibling words only: their seniority is the named person's age against the reference person
# (姐夫/嫂/内兄 and the like compare against the sibling or the spouse, so they are left out).
_OLDER_WORDS = ("哥哥", "堂兄", "表兄", "再从堂兄", "再从表兄", "三从堂兄", "三从表兄",
                "姐姐", "堂姐", "表姐", "再从堂姐", "再从表姐", "三从堂姐", "三从表姐")
_YOUNGER_WORDS = ("弟弟", "堂弟", "表弟", "再从堂弟", "再从表弟", "三从堂弟", "三从表弟",
                  "妹妹", "堂妹", "表妹", "再从堂妹", "再从表妹", "三从堂妹", "三从表妹")

_SEX_OF_WORD = {}


def _sex_table():
    """{word: 'M'|'F'} built once from the KIN_WORDS keys (each key spells the person's sex)."""
    if not _SEX_OF_WORD:
        for key in F.KIN_WORDS:
            word = F.kin_text(key)
            if not word or word in _SEX_OF_WORD:
                continue
            sex = None
            for tok in key.split("_"):
                if tok in _SEX_TOKENS:
                    sex = _SEX_TOKENS[tok]
            if sex:
                _SEX_OF_WORD[word] = sex
    return _SEX_OF_WORD


def kin_sex_of(word):
    return _sex_table().get(word)


def seniority_of(word):
    if word in _OLDER_WORDS:
        return "older"
    if word in _YOUNGER_WORDS:
        return "younger"
    return None


def load(snap_path):
    import cache_lib as cl

    snap = json.load(open(snap_path, encoding="utf-8"))
    meta = snap.get("meta") or {}
    facts = dict(snap.get("facts") or {})
    data = os.path.join(ROOT, "output", meta.get("folder") or "", "data")
    melt_path = os.path.join(data, meta.get("melt") or "")
    if not os.path.isfile(melt_path):
        melt_path = cl.melt_file_exists(melt_path) or melt_path
    cache = json.load(open(os.path.join(data, f"player_{meta.get('player_id')}.json"),
                           encoding="utf-8"))
    t0 = time.time()
    melt = cl.load_melt(melt_path)
    w(f"熔件 {os.path.basename(melt_path)} 载入 {time.time()-t0:.1f}s")
    names = os.path.join(data, "names.json")
    f = F.Facts(cache, melt, names if os.path.isfile(names) else None,
                as_of=facts.get("as_of") or meta.get("as_of"), decade=facts.get("decade"))
    facts["_facts"] = f
    return snap, facts, cache, f


def build_blocks(facts, cache, f, disable_paths=False):
    """[(板块 key, 板块文本, [(基准人, cid, 首词)])]，用记录版 KinScope 重跑全部板块。"""
    import biography as bio

    scopes = []

    class Rec(F.KinScope):
        def __init__(self, subject=None):
            super().__init__(subject)
            self.here = []
            scopes.append(self)

        def _note(self, cid, word):
            try:
                ci = int(cid)
            except (TypeError, ValueError):
                return
            if ci != self.subject and word:
                self.here.append((self.subject, ci, word))

        def word_for(self, cid, facts_, subject=None):
            wd = super().word_for(cid, facts_, subject=subject)
            self._note(cid, wd)
            return wd

        def mark(self, cid, base, facts_, date=None):
            out = super().mark(cid, base, facts_, date=date)
            if out != base and base:
                self._note(cid, out[:len(out) - len(base)])
            return out

    real_scope, real_path = F.KinScope, F.Facts.path_word_for
    F.KinScope = Rec
    if disable_paths:
        F.Facts.path_word_for = lambda self, cid, subject: ""
    out = []
    try:
        for a in bio.build_articles(facts, cache, {"max_tokens": 12800}):
            for sec in a["sections"]:
                key = f"{a['key']}_{sec['key']}"
                del scopes[:]
                try:
                    blocks = bio._article_facts(facts, cache, a["key"], sec)
                except Exception as e:                       # noqa: BLE001
                    w(f"  (板块 {key} 失败: {e!r})")
                    continue
                text = "\n".join(v for v in blocks.values() if isinstance(v, str))
                words = [t for sc in scopes for t in sc.here]
                out.append((key, text, words))
    finally:
        F.KinScope = real_scope
        F.Facts.path_word_for = real_path
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    max_people = None
    for a in sys.argv[1:]:
        if a.startswith("--max-people="):
            max_people = int(a.split("=", 1)[1])
    snap_path = args[0] if args else os.path.join(ROOT, "output", "田所2", "data",
                                                  "v122_final4.json")
    if not os.path.isabs(snap_path):
        snap_path = os.path.join(ROOT, snap_path)
    w(f"v124 矩阵：{snap_path}")
    snap, facts, cache, f = load(snap_path)
    pid = f.cache.get("player_id")
    folder = (snap.get("meta") or {}).get("folder") or "x"

    # ---------------------------------------------------------------- A. 口径不变
    w("\n== A. 口径不变性（旧口径 vs 新口径）==")
    t0 = time.time()
    old = build_blocks(facts, cache, f, disable_paths=True)
    w(f"旧口径重跑 {len(old)} 个板块 {time.time()-t0:.1f}s")
    t0 = time.time()
    new = build_blocks(facts, cache, f)
    w(f"新口径重跑 {len(new)} 个板块 {time.time()-t0:.1f}s")

    old_map = {k: (t, ws) for k, t, ws in old}
    changed = inserted = 0
    bad_old, bad_text = [], []
    for key, t_new, ws_new in new:
        t_old, ws_old = old_map.get(key, ("", []))
        o = {(s, c): wd for s, c, wd in ws_old}
        n = {(s, c): wd for s, c, wd in ws_new}
        ins = []
        for k2, wd in n.items():
            if k2 in o:
                if o[k2] != wd:
                    bad_old.append((key, k2, o[k2], wd))
            else:
                inserted += 1
                ins.append(wd)
        for k2 in o:
            if k2 not in n:
                bad_old.append((key, k2, o[k2], "（消失）"))
        if t_old != t_new:
            changed += 1
            t = t_new
            for wd in ins:
                if t.count(wd) == 1:
                    t = t.replace(wd, "", 1)
            if t != t_old:
                bad_text.append((key, t_old, t_new))
    check("旧口径的每一处标注逐字不变", not bad_old, bad_old[:3])
    check("板块文本差异只能是路径词插入", not bad_text, bad_text[:3])
    w(f"  改动板块 {changed} 个，新增标注 {inserted} 处")

    # ---------------------------------------------------------------- B. 新增标注都是路径词
    w("\n== B. 新增标注的性质 ==")
    all_words = collections.Counter(wd for _k, _t, ws in new for _s, _c, wd in ws)
    path_like = [wd for wd in all_words if "的" in wd]
    check("带「的」的标注都是 2–3 段的路径词",
          all(2 <= len(wd.split("的")) <= 3 for wd in path_like),
          [wd for wd in path_like if not 2 <= len(wd.split("的")) <= 3][:5])
    w("  含「的」的标注（次数）：")
    for wd, n in all_words.most_common():
        if "的" in wd:
            w(f"    {wd} × {n}")

    # ---------------------------------------------------------------- C. N×N 矩阵
    w("\n== C. N×N 矩阵 ==")
    people = {}

    def note(cid):
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return
        if f.name(cid):
            people[cid] = f.name(cid)

    note(pid)
    for _k, _t, ws in new:
        for s, c, _wd in ws:
            note(s)
            note(c)
    for e in (facts.get("killed") or []):
        note(e.get("id"))
    if max_people is None:
        for _line, lst in (f.name_index or {}).items():
            for cid, _label in lst:
                note(cid)
    ids = sorted(people)
    w(f"人物 {len(ids)} 人（矩阵 {len(ids)**2:,} 个有序对）")

    def first_word(cid, subj):
        parts = f.identity_parts(cid, subj, paths=False)
        return parts[0][1] if parts else ""

    t0 = time.time()
    direct = {(s, x): first_word(x, s) for s in ids for x in ids if s != x}
    w(f"直接词 {len(direct):,} 对，{time.time()-t0:.1f}s")

    t0 = time.time()
    path, reachable = {}, {}
    for s in ids:
        todo = set()
        for _kind, a, _w1 in f._path_anchors(s):
            if a in people and a != s:
                todo.add(a)
            for x in (f._parent_ids(a) | f._child_ids(a) | f._sibling_ids(a)
                      | set(f.spouses_now(a)) | f._relation_partners(a)):
                if x in people and x != s:
                    todo.add(x)
            for emp, _typ, _h in f._court_rows_at(a):
                if not isinstance(emp, int):
                    continue
                if emp in people and emp != s:
                    todo.add(emp)
                for x in (f._parent_ids(emp) | f._child_ids(emp) | f._sibling_ids(emp)):
                    if x in people and x != s:
                        todo.add(x)
        reachable[s] = todo
        for x in todo:
            wd = f.path_word_for(x, s)
            if wd:
                path[(s, x)] = wd
    w(f"路径词 {len(path):,} 对（搜索 {sum(len(v) for v in reachable.values()):,} 次），"
      f"{time.time()-t0:.1f}s")

    rng = random.Random(124)
    sample = [(s, x) for s in ids for x in ids if s != x and x not in reachable[s]]
    rng.shuffle(sample)
    bad_sample = [(s, x, f.path_word_for(x, s)) for s, x in sample[:300]
                  if f.path_word_for(x, s)]
    check("不可达的对抽查确实为空", not bad_sample, bad_sample[:3])
    bad_self = [s for s in ids if f.path_word_for(s, s)]
    check("自身路径词为空", not bad_self, bad_self[:3])

    kin_vocab = F.kin_texts()
    rel_vocab = set(F.RELATION_WORDS.values())
    liege_vocab = set(F.PATH_WORDS.values())
    bad_seg, loose_seg = [], []
    for (s, x), wd in path.items():
        segs = wd.split("的")
        if not 2 <= len(segs) <= 3 or not all(segs):
            bad_seg.append(((s, x), wd, "段数"))
            continue
        if segs[-1] not in kin_vocab and segs[-1] not in rel_vocab:
            bad_seg.append(((s, x), wd, f"末段 {segs[-1]}"))
        if segs[0] not in kin_vocab and segs[0] not in rel_vocab and segs[0] not in liege_vocab:
            loose_seg.append(((s, x), wd, f"首段 {segs[0]}"))     # 职位词：只报不断
    check("路径词结构（2–3 段，末段亲缘/关系）", not bad_seg, bad_seg[:5])
    if loose_seg:
        w(f"  INFO 首段为职位词的路径词 {len(loose_seg)} 条，例：{loose_seg[:3]}")

    def recompute(s, x, wd):
        segs = wd.split("的")
        for _kind, a, w1 in f._path_anchors(s):
            if w1 != segs[0]:
                continue
            if len(segs) == 2:
                if segs[1] in (f.kin_word_for(x, a), f.relation_word_for(x, a)):
                    return True
            else:
                for b, typ, _h in f._court_rows_at(a):
                    if f._office_anchor_word(typ, a) != segs[1]:
                        continue
                    if f.kin_word_for(x, b) == segs[2]:
                        return True
        return False

    bad_rec = [(s, x, wd) for (s, x), wd in path.items() if not recompute(s, x, wd)]
    check("路径词可由锚点独立复算", not bad_rec, bad_rec[:5])

    bad_fill = [((s, x), wd) for (s, x), wd in path.items() if direct.get((s, x))]
    check("路径词只出现在直接词为空的对上", not bad_fill, bad_fill[:5])

    bad_sex = []
    for (s, x), wd in list(direct.items()) + list(path.items()):
        want = kin_sex_of(wd.split("的")[-1])
        actual = f._sex_of(x)
        if not want or actual is None:
            continue
        if (want == "M") != (actual is False):
            bad_sex.append((s, x, wd, "实为女" if actual else "实为男"))
    check("亲缘词的性别蕴含与缓存性别一致", not bad_sex, bad_sex[:5])

    bad_age = []
    for (s, x), wd in list(direct.items()) + list(path.items()):
        older = seniority_of(wd.split("的")[-1])
        actual = f._older_ids(x, s) if older else None
        if actual is None:
            continue
        if (older == "older") != bool(actual):
            bad_age.append((s, x, wd, "实际更年长" if actual else "实际更年幼"))
    check("长幼词与生年一致", not bad_age, bad_age[:5])

    bad_sym = [(s, x, wd, direct.get((x, s), "")) for (s, x), wd in direct.items()
               if wd and not direct.get((x, s))]
    check("直接词两个方向都出（单向断开即报）", not bad_sym, bad_sym[:5])

    # ---------------------------------------------------------------- D. 落盘
    w("\n== D. 产出 ==")
    tsv = os.path.join(ROOT, "logs", f"v124_matrix_{folder}.tsv")
    with open(tsv, "w", encoding="utf-8") as fh:
        fh.write("S\tS名\tX\tX名\t直接词\t路径词\n")
        for s in ids:
            for x in ids:
                if s == x:
                    continue
                d = direct.get((s, x), "")
                p = path.get((s, x), "")
                if d or p:
                    fh.write(f"{s}\t{people.get(s, '')}\t{x}\t{people.get(x, '')}\t{d}\t{p}\n")
    w(f"矩阵写出 {tsv}")
    w("路径词样例（前 30）：")
    for (s, x), wd in list(path.items())[:30]:
        w(f"  {people.get(s, s)}的{wd}{people.get(x, x)}   [{s}→{x}]")

    txt = os.path.join(ROOT, "logs", f"v124_matrix_{folder}.txt")
    open(txt, "w", encoding="utf-8").write("\n".join(OUT) + "\n")
    w(f"报告写出 {txt}")
    print(f"\nFAIL = {FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
