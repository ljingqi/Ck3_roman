"""v124 探针：把关系计算器从「直接关系」扩到「关系的关系」（两跳/三词路径）是否可行。

只读、不改生产代码。测量五件事：

  A. 规模与成本 —— 缓存人物数、亲缘边数、`kin_word` / `relation_word_for` 单次耗时；
  B. 事实面标注率 —— 重跑本档全部板块的 `_article_facts`（记录版 KinScope），
     统计「首见第三人」尝试数、实际插入定语数，以及**真正的无词者**（`identity_parts` 为空）；
  C. 路径覆盖 —— 对无词者全量跑路径搜索（锚点=亲缘/关系/领主/职位），
     分类统计形状、歧义度、样例句子与耗时；
  D. 刺客列传 —— 24 名死者的 identity 现状（都是「仇敌」），有多少能细化为「仇敌的哥哥」；
  E. 代价 —— 单目标搜索耗时、每板块新增字符数估计。

用法（熔件只整载一次）：
  & tools\\py.ps1 tools\\tests\\v124_probe_paths.py [快照]
默认快照 output/田所2/data/v122_final4.json。
输出 logs/v124_probe_paths.txt（UTF-8）。
"""
import json
import os
import random
import sys
import time
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

OUT = []


def w(s=""):
    OUT.append(str(s))
    print(s)


# 锚点类别优先级：越靠前越像史书会写的说法（「仇敌的哥哥」优于「哥哥的仇敌」）
_KIND_RANK = {"relation": 0, "liege": 1, "office": 2, "kin": 3}
_HOP2_RANK = {"kin": 0, "relation": 1, "office": 2}


def main():
    snap_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "output", "田所2", "data", "v122_final4.json")
    if not os.path.isabs(snap_path):
        snap_path = os.path.join(ROOT, snap_path)

    import facts as F
    import biography as bio
    import cache_lib as cl

    w("v124 探针：关系的关系（路径词）可行性")
    w(f"快照: {snap_path}")
    snap = json.load(open(snap_path, encoding="utf-8"))
    meta = snap.get("meta") or {}
    facts = dict(snap.get("facts") or {})
    pid = meta.get("player_id")
    as_of = facts.get("as_of") or meta.get("as_of")
    data = os.path.join(ROOT, "output", meta.get("folder") or "", "data")
    cache_path = os.path.join(data, f"player_{pid}.json")
    names = os.path.join(data, "names.json")
    melt_path = os.path.join(data, meta.get("melt") or "")
    if not os.path.isfile(melt_path):
        melt_path = cl.melt_file_exists(melt_path) or melt_path
    w(f"家族={meta.get('folder')} pid={pid} as_of={as_of} decade={facts.get('decade')}")

    t0 = time.time()
    cache = json.load(open(cache_path, encoding="utf-8"))
    w(f"缓存载入 {time.time()-t0:.1f}s  人物 {len(cache.get('characters') or {}):,}")
    t0 = time.time()
    melt = cl.load_melt(melt_path)
    w(f"熔件载入 {time.time()-t0:.1f}s  ({os.path.basename(melt_path)})")
    t0 = time.time()
    f = F.Facts(cache, melt, names if os.path.isfile(names) else None,
                as_of=as_of, decade=facts.get("decade"))
    facts["_facts"] = f
    w(f"Facts 构造 {time.time()-t0:.1f}s")
    chars = cache.get("characters") or {}

    # ------------------------------------------------------------ A. 成本
    w("\n== A. 规模与成本 ==")
    par = f._parent_edges()
    w(f"人物 {len(chars):,}，父/母/子边（双向并集）{sum(len(v) for v in par.values()):,}")
    rng = random.Random(124)
    ids = [int(k) for k in chars if str(k).isdigit()]
    t0 = time.time()
    n_kin = n_rel = 0
    for _ in range(1000):
        a1, b1 = rng.choice(ids), rng.choice(ids)
        if f.kin_word_for(b1, a1):
            n_kin += 1
        if f.relation_word_for(b1, a1):
            n_rel += 1
    dt = time.time() - t0
    w(f"kin_word_for+relation_word_for 1000 对 {dt*1000:.0f} ms → {dt/2:.3f} ms/次；"
      f"有亲缘词 {n_kin}、有关系词 {n_rel}")
    t0 = time.time()
    rr = f._any_opinion_index()
    w(f"_any_opinion_index ({len(rr):,} 对) 首建 {time.time()-t0:.1f}s；"
      f"缓存 relation_reasons {len(cache.get('relation_reasons') or {}):,} 条")

    # 宫廷职位 / 领主
    cpos = (melt.get("court_positions") or {}).get("database") or {}
    court_by_emp = collections.defaultdict(list)
    for e in cpos.values():
        if not isinstance(e, dict):
            continue
        emp, pos = e.get("employer"), e.get("court_position")
        if isinstance(emp, int) and pos:
            court_by_emp[emp].append((e.get("employee"), pos))
    word_of_pos = {}

    def office_word(pos):
        if pos not in word_of_pos:
            v = f.court_position_word(pos)
            word_of_pos[pos] = v if (v and v != pos) else ""
        return word_of_pos[pos]

    try:
        vent = f._vassal_entry_at(pid, date=as_of)
    except Exception as e:                                       # noqa: BLE001
        vent = None
        w(f"  (_vassal_entry_at 异常: {e!r})")

    def anchors_of(S):
        """[(kind, anchor, hop1_word)]：基准人 S 的锚点。"""
        out = []
        for x in f._parent_ids(S):
            wd = f.kin_word_for(x, S)
            if wd:
                out.append(("kin", int(x), wd))
        for x in f._child_ids(S):
            wd = f.kin_word_for(x, S)
            if wd:
                out.append(("kin", int(x), wd))
        for x in f._sibling_ids(S):
            wd = f.kin_word_for(x, S)
            if wd:
                out.append(("kin", int(x), wd))
        for x in f.spouses_now(S):
            wd = f.kin_word_for(x, S)
            if wd:
                out.append(("kin", int(x), wd))
        for x in sorted(partners_of(S)):
            wd = rel_word(S, x)
            if wd:
                out.append(("relation", x, wd))
        for emp, pos in (court_by_emp.get(S) or []):
            wd = office_word(pos)
            if wd and isinstance(emp, int):
                out.append(("office", emp, wd))
        if vent and isinstance(vent.get("liege"), int) and S == pid:
            out.append(("liege", int(vent["liege"]), "领主"))
        return out

    # 关系词：按需取词并记忆（生产口径同此：只对用到的对取词，不做全档索引）
    _relmemo = {}

    def rel_word(a, b, base=None):
        """b 相对 a 的角色词（b 是相对人，a 是基准人），与 `Facts.relation_word_for` 同向。"""
        key = (a, b)
        if key in _relmemo:
            return _relmemo[key]
        wd = f.relation_word_for(b, a)
        _relmemo[key] = wd
        return wd

    _partners = {}

    def partners_of(cid):
        """与 cid 有关系（任一方向）的对方 cid。**两个源并集**：本轮熔件的 active_opinions，
        加上缓存里锁存过的 relation_reasons（关系结束/一方身故后只活在锁存里）。"""
        if cid in _partners:
            return _partners[cid]
        out = set()
        for (o, t2) in rr:
            if o == cid:
                out.add(t2)
            elif t2 == cid:
                out.add(o)
        for v in (cache.get("relation_reasons") or {}).values():
            if not isinstance(v, dict):
                continue
            o, t2 = v.get("owner"), v.get("target")
            if o == cid and isinstance(t2, int):
                out.add(t2)
            elif t2 == cid and isinstance(o, int):
                out.add(o)
        out.discard(cid)
        _partners[cid] = out
        return out


    kin_sets = {"父": f._parent_ids(pid), "子": f._child_ids(pid),
                "同胞": f._sibling_ids(pid), "配偶": f.spouses_now(pid)}
    _rel_pid = [x for x in partners_of(pid) if rel_word(pid, x)]
    w("传主锚点：" + "，".join(
        [f"{k}{len(v)}" for k, v in kin_sets.items()]
        + [f"关系{len(_rel_pid)}（"
           + "、".join(f"{k}×{v}" for k, v in
                       collections.Counter(rel_word(pid, x) for x in _rel_pid).most_common())
           + "）",
           f"宫廷{len(court_by_emp.get(pid) or [])}",
           f"领主{1 if vent and vent.get('liege') else 0}"]))
    w("传主宫廷职名词: " + "、".join(
        f"{p}→{office_word(p) or '（无中文）'}"
        for _e, p in (court_by_emp.get(pid) or [])))
    w(f"传主的领主: {vent!r}")

    # ------------------------------------------------------------ B. 标注率
    w("\n== B. 事实面：首见第三人的标注率 ==")
    articles = bio.build_articles(facts, cache, {"max_tokens": 12800})
    scopes = []

    class Rec(F.KinScope):
        def __init__(self, subject=None):
            super().__init__(subject)
            scopes.append(self)
            self.here = []

        def mark(self, cid, base, facts_, date=None):
            out = super(Rec, self).mark(cid, base, facts_, date=date)
            try:
                ci = int(cid)
            except (TypeError, ValueError):
                ci = None
            if base and ci is not None and ci != self.subject:
                self.here.append((ci, out != base))
            return out

        def word_for(self, cid, facts_, subject=None):
            wd = super(Rec, self).word_for(cid, facts_, subject=subject)
            try:
                ci = int(cid)
            except (TypeError, ValueError):
                ci = None
            sub = subject if subject is not None else self.subject
            if ci is not None and ci != sub:
                self.here.append((ci, bool(wd)))
            return wd

    real = F.KinScope
    F.KinScope = Rec
    built = []
    try:
        for a in articles:
            for sec in a["sections"]:
                del scopes[:]
                key = f"{a['key']}_{sec['key']}"
                try:
                    blocks = bio._article_facts(facts, cache, a["key"], sec)
                except Exception as e:                         # noqa: BLE001
                    w(f"  (板块 {key} 失败: {e!r})")
                    continue
                built.append((key, blocks, list(scopes)))
    finally:
        F.KinScope = real

    pairs = {}                       # (S, cid) 首见尝试
    tot = lab = 0
    for key, blocks, scs in built:
        for sc in scs:
            for cid, ok in sc.here:
                pairs[(sc.subject, cid)] = ok
                tot += 1
                lab += 1 if ok else 0
    w(f"板块 {len(built)} 个；首见尝试 {tot} 次，实际插入定语 {lab} 次 "
      f"({100.0*lab/max(1,tot):.1f}%)")
    w("（其余未插入者里，一部分是句子里已经写明关系，见 C 的分类）")
    # 真正的无词者：直接问身份计算器
    t0 = time.time()
    no_word = [(S, c) for (S, c) in pairs if not f.identity_parts(c, S)]
    w(f"不同的（基准人, 人物）对 {len(pairs)}；其中 identity_parts 为空 "
      f"{len(no_word)} 对 ({100.0*len(no_word)/max(1,len(pairs)):.1f}%)，"
      f"现场判词耗时 {time.time()-t0:.1f}s")
    by_people = collections.defaultdict(set)
    for S, c in no_word:
        by_people[c].add(S)
    w(f"无词的不同人物 {len(by_people)} 人")

    # ------------------------------------------------------------ C. 路径
    w("\n== C. 路径覆盖（对无词者全量）==")
    anchor_cache = {}

    def anchored(S):
        if S not in anchor_cache:
            anchor_cache[S] = anchors_of(S)
        return anchor_cache[S]

    shapes = collections.Counter()
    samples = collections.defaultdict(list)
    hit_people = 0
    costs = []
    for X in sorted(by_people):
        for S in sorted(by_people[X]):
            t0 = time.time()
            got = []
            for kind, A, w1 in anchored(S):
                if A in (X, S):
                    continue
                k2 = f.kin_word_for(X, A)
                if k2:
                    got.append((kind, "kin", w1, k2, A))
                r2 = rel_word(A, X)
                if r2:
                    got.append((kind, "relation", w1, r2, A))
                for emp, pos in (court_by_emp.get(A) or []):
                    if emp != X:
                        continue
                    wd = office_word(pos)
                    if wd:
                        got.append((kind, "office", w1, wd, A))
                # 三词：A 的雇员 B，X 是 B 的亲缘
                if kind in ("liege", "relation", "office"):
                    for emp, pos in (court_by_emp.get(A) or [])[:8]:
                        if not isinstance(emp, int) or emp in (X, S, A):
                            continue
                        wd = office_word(pos)
                        if not wd:
                            continue
                        k3 = f.kin_word_for(X, emp)
                        if k3:
                            got.append(("3:" + kind, "office×kin",
                                        f"{w1}{wd}", k3, f"{A}>{emp}"))
            costs.append(time.time() - t0)
            if not got:
                continue
            hit_people += 1
            got.sort(key=lambda g: (len(g[0].split(":")), _KIND_RANK.get(g[0].split(":")[-1], 9),
                                    _HOP2_RANK.get(g[1], 9), g[2], g[4]))
            seen_shapes = set()
            for kind, hop2, w1, w2, A in got:
                sh = (kind.split(":")[-1], hop2)
                seen_shapes.add(sh)
                shapes[sh] += 1
            k0, h0, w10, w20, A0 = got[0]
            nm_x = f.name(X) or str(X)
            nm_s = f.name(S) or str(S)
            nm_a = (f.name(int(str(A0).split(">")[0])) or str(A0)) if ">" in str(A0) \
                else (f.name(A0) or str(A0))
            samples[(k0.split(":")[-1], h0)].append(
                f"{nm_s}的{w10}的{w20}{nm_x}" if "×" not in h0
                else f"{nm_s}的{w10}{nm_x}")
    w(f"无词者 {len(by_people)} 人：{hit_people} 人有路径 "
      f"({100.0*hit_people/max(1,len(by_people)):.0f}%)")
    w(f"单目标搜索耗时：均 {1000*sum(costs)/max(1,len(costs)):.2f} ms，"
      f"最大 {1000*max(costs or [0]):.1f} ms，共 {len(costs)} 次")
    w("路径形状（第一跳×第二跳，候选条数）：")
    for (k1, k2), n in shapes.most_common():
        w(f"  {k1}×{k2}: {n}")
    w("样例（按形状取前几条，第一候选）：")
    for shape in sorted(samples):
        for s in samples[shape][:5]:
            w(f"  [{shape[0]}×{shape[1]}] {s}")

    # ------------------------------------------------------------ D. 死者
    w("\n== D. 刺客列传死者身份细化 ==")
    killed = facts.get("killed") or []
    w(f"死者 {len(killed)} 人；identity 全部非空（`_victim_identity_parts` 兜了「仇敌」）")
    for e in killed[:6]:
        w(f"  现: {e.get('name')} → {e.get('identity')}")
    refined = 0
    for e in killed:
        X = e.get("id")
        if not isinstance(X, int):
            continue
        best = None
        for kind, A, w1 in anchored(pid):
            if A in (X, pid):
                continue
            k2 = f.kin_word_for(X, A)
            if k2 and kind in ("relation", "liege", "office"):
                best = (kind, w1, k2, A)
                break
        if best:
            refined += 1
            if refined <= 10:
                kind, w1, w2, A = best
                w(f"  可细化: {f.name(pid)}的{w1}{f.name(A) or A}的{w2}{e.get('name')}"
                  f"（现 identity={e.get('identity')}）")
    w(f"{len(killed)} 名死者中 {refined} 人可细化为「关系/领主/职位 + 亲缘」路径")

    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    outp = os.path.join(ROOT, "logs",
                        f"v124_probe_paths_{meta.get('folder') or 'x'}.txt")
    open(outp, "w", encoding="utf-8").write("\n".join(OUT) + "\n")
    w(f"\n写出 {outp}")


if __name__ == "__main__":
    main()
