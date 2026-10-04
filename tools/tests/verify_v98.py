# -*- coding: utf-8 -*-
"""v98 专项断言（秒级；纯函数 + 快照，不载熔件）。

问题（用户 2026-10-03）：
  ① 重生成旧十年不得按「末档现值」渲染 —— 三篇十年传都要有《礼仪志》第三板块
  ② 名字按当日 —— 975.9.24 才受任教宗，故 963/973 两篇写「洪思忠」，983 篇才写教名「尼各老」
  ③ as_of 逻辑落地 —— 旧十年用该日那一档熔件 + era_view 截断视图（直辖、政体、教名按当日）

断言：
  [1] player_landed_block（纯函数）：熔件 landed_data → 缓存 landed 块的映射
  [2] era_view（纯函数）：教名按当日、直辖按当日、last_date 钉当日、且不改原缓存
  [3] decade_era_melt（纯函数）：取 cutoff 当日或之前最近的一档熔件
  [4] decade 文件匹配按生年：改名后仍认得出自己写的十年篇
  [5] 快照：三篇十年传的第三板块事实行非空，且署名／直辖按当日
  [6] 回归：非时代路径（终传）与 v97 快照逐字节一致

用法：
    & tools\\py.ps1 tools\\tests\\verify_v98.py [快照...]
    （缺省 output/洪氏2/data/v98_era_d1.json、_d2、_d3，加 v98_gf_check.json 对照）
"""
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import cache_lib as cl   # noqa: E402
import pipeline as pl    # noqa: E402

OK = True
H2 = os.path.join(ROOT, "output", "洪氏2", "data")
SUBJ = 67172818
DEFAULT = [os.path.join(H2, f"v98_era_d{i}.json") for i in (1, 2, 3)]
GF_NEW = os.path.join(H2, "v98_gf_check.json")
GF_OLD = os.path.join(H2, "v97_gf.json")


def check(name, cond, extra=None):
    global OK
    if not cond:
        OK = False
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f"   ← {str(extra)[:220]!r}" if extra is not None and not cond else ""))


def surface_of(snap):
    parts = [json.dumps(snap.get("facts") or {}, ensure_ascii=False),
             json.dumps(snap.get("blocks") or {}, ensure_ascii=False),
             json.dumps(snap.get("shared") or {}, ensure_ascii=False)]
    for m in snap.get("messages") or []:
        parts.append(json.dumps(m, ensure_ascii=False))
    return "\n".join(parts)


def test_landed_block():
    """[1] 熔件 landed_data -> 缓存 landed 块：字段名与派生量逐条对齐 extract_snapshot。"""
    print("[1] player_landed_block（纯函数）")
    melt = {"living": {"7": {"landed_data": {"domain": [19864, 17552],
                                            "became_ruler_date": "945.12.13",
                                            "government": "ecclesiastical_government",
                                            "council": [1, 2, 3],
                                            "laws": ["church_authority_2"],
                                            "succession": [9],
                                            "strength": 105,
                                            "max_power": 9000,
                                            "vassal_contracts": [11, 12, 13, 14]}}},
            "dead_unprunable": {}, "characters": {}}
    b = cl.player_landed_block(melt, 7)
    check("domain 原样带出", b.get("domain") == [19864, 17552], b.get("domain"))
    check("became_ruler_date 原样带出", b.get("became_ruler_date") == "945.12.13")
    check("government 原样带出", b.get("government") == "ecclesiastical_government")
    check("vassal_count = len(vassal_contracts)",
          b.get("vassal_count") == 4, b.get("vassal_count"))
    check("strength/max_power 原样带出",
          (b.get("strength"), b.get("max_power")) == (105, 9000), (b.get("strength"), b.get("max_power")))
    check("无 domicile 时不出 domicile 键", "domicile_type" not in b, sorted(b))
    check("键集稳定",
          set(b) == {"domain", "became_ruler_date", "government", "realm_capital",
                     "vassal_count", "council", "laws", "succession", "strength",
                     "max_power"}, sorted(b))
    # extract_snapshot 必须走同一个出口，否则两条路径又会分叉
    import inspect
    src = inspect.getsource(cl._extract_snapshot)
    check("extract_snapshot 走 player_landed_block", "player_landed_block(melt, cid, ld)" in src)


def test_era_view():
    """[2] era_view：教名与直辖按当日，原缓存一个字节都不动。"""
    print("[2] era_view（纯函数）")
    cache = {
        "last_date": "984.1.1",
        "player_id": 10,
        "characters": {
            "10": {"name_zh": "思忠", "house_name": "洪", "regnal_name": "Nicolaus",
                   "name_full": "尼各老", "landed": {"domain": [4], "vassal_count": 3}},
            "20": {"name_zh": "山部", "regnal_name": "Kanmu", "name_full": "桓武"},
            "30": {"name_zh": "某某", "regnal_name": "Late", "name_full": "晚名"},
        },
    }
    melt = {
        "living": {"10": {"first_name": "Sizhong_601D_5FE0",
                          "landed_data": {"domain": [19864, 17552],
                                          "became_ruler_date": "945.12.13",
                                          "government": "ecclesiastical_government",
                                          "vassal_contracts": []}},
                   "20": {"first_name": "Yamabe", "regnal_name": "Kanmu"}},
        "dead_unprunable": {},
        "characters": {},
    }
    before = json.dumps(cache, ensure_ascii=False, sort_keys=True)
    view = cl.era_view(cache, melt, "963.1.1")
    check("返回的是新 dict", view is not cache and view["characters"] is not cache["characters"])
    check("原缓存未被改动",
          json.dumps(cache, ensure_ascii=False, sort_keys=True) == before)
    check("last_date 钉到当日", view.get("last_date") == "963.1.1", view.get("last_date"))
    check("当日无教名者：缓存教名被抹去",
          view["characters"]["10"].get("regnal_name") is None,
          view["characters"]["10"].get("regnal_name"))
    check("name_full 随之重算（不再是教名）",
          view["characters"]["10"].get("name_full") != "尼各老",
          view["characters"]["10"].get("name_full"))
    check("直辖按当日重建",
          view["characters"]["10"].get("landed", {}).get("domain") == [19864, 17552],
          view["characters"]["10"].get("landed"))
    check("当日已有教名者：保留",
          view["characters"]["20"].get("regnal_name") == "Kanmu",
          view["characters"]["20"].get("regnal_name"))
    check("当日熔件查无此人：保留缓存值",
          view["characters"]["30"].get("regnal_name") == "Late",
          view["characters"]["30"].get("regnal_name"))
    check("无 era 证据时不复制记录", view["characters"]["30"] is cache["characters"]["30"])
    # 生产路径必须用同一出口
    import inspect
    src = inspect.getsource(pl.generate_bio)
    check("generate_bio 用 decade_era_melt 选熔件", "decade_era_melt(cfg, cache, as_of)" in src)
    check("generate_bio 用 cl.era_view 建视图", "cl.era_view(cache, melt, d_era)" in src)
    check("generate_bio 只在 as_of 早于末档时才走时代路径",
          "cl.date_key(str(as_of)) < cl.date_key(str(last))" in src)
    check("渲染用视图、落盘用原缓存",
          "render_cache" in src and "bio.generate_biography(render_cache" in src)


def test_decade_era_melt():
    """[3] 取 cutoff 当日或之前最近的一档熔件（就是当年那次生成读到的文件）。"""
    print("[3] decade_era_melt（纯函数）")
    tmp = tempfile.mkdtemp(prefix="v98era_")
    try:
        d = os.path.join(tmp, "out", "洪氏T", "data")
        os.makedirs(d)
        for fn in ("melt_953_01_01.json.xz", "melt_963_01_01.json.xz",
                   "melt_973_01_01.json", "melt_984_01_01.json"):
            open(os.path.join(d, fn), "w").close()
        cfg = {"output_dir": os.path.join(tmp, "out"), "data_dir": os.path.join(tmp, "root")}
        cache = {"output_folder": "洪氏T", "player_id": 1,
                 "sources": ["953.1.1", "963.1.1", "973.1.1", "984.1.1"]}
        p, dt = pl.decade_era_melt(cfg, cache, "963.1.1")
        check("cutoff 当日有档: 取该档", os.path.basename(p) == "melt_963_01_01.json.xz" and dt == "963.1.1",
              (os.path.basename(p), dt))
        p, dt = pl.decade_era_melt(cfg, cache, "973.1.1")
        check("第二十年取 973 档", os.path.basename(p) == "melt_973_01_01.json" and dt == "973.1.1",
              (os.path.basename(p), dt))
        p, dt = pl.decade_era_melt(cfg, cache, "970.1.1")
        check("cutoff 无档: 取之前最近一档", os.path.basename(p) == "melt_963_01_01.json.xz" and dt == "963.1.1",
              (os.path.basename(p), dt))
        p, dt = pl.decade_era_melt(cfg, cache, "900.1.1")
        check("cutoff 之前无档: 返回空", (p, dt) == ("", ""), (p, dt))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_decade_file_pattern():
    """[4] 十年篇文件名按生年认领：教名前后两个名字都算同一人。"""
    print("[4] 十年篇文件名匹配（按生年）")
    tmp = tempfile.mkdtemp(prefix="v98pat_")
    try:
        out = os.path.join(tmp, "out")
        d = os.path.join(out, "洪氏T")
        os.makedirs(d)
        for fn in ("洪思忠(917)_传记_第1个十年_963_01_01.md",
                   "尼各老(917)_传记_第3个十年_983_01_01.md",
                   "洪天贵福(869)_传记_第1个十年_915_01_01.md"):
            open(os.path.join(d, fn), "w").close()
        cfg = {"output_dir": out}
        cache = {"output_folder": "洪氏T", "player_id": 1,
                 "characters": {"1": {"birth": "917.4.11"}}}
        pat = pl._decade_file_pattern(cache, 1)
        check("认出改名前的第1个十年", bool(pat.match("洪思忠(917)_传记_第1个十年_963_01_01.md")))
        check("同一人的第3个十年也算",
              bool(pl._decade_file_pattern(cache, 3).match("尼各老(917)_传记_第3个十年_983_01_01.md")))
        check("不认同族的他人（生年不同）",
              not pat.match("洪天贵福(869)_传记_第1个十年_915_01_01.md"))
        check("_generated_decades_on_disk 认出 {1,3}",
              pl._generated_decades_on_disk(cfg, cache) == {1, 3},
              pl._generated_decades_on_disk(cfg, cache))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_snapshots(snaps):
    """[5] 三篇十年传：第三板块事实行非空，署名与直辖按当日。

    v100 起该板块由「大公会议与教宗诏书」(facts.church_chronicle) 取代枢机团，旧快照仍带
    旧键，故此处两代板块名兼容读取；断言只判「有事实行」与当日口径。"""
    for p in snaps:
        if not os.path.isfile(p):
            print(f"[SKIP] 快照不存在: {p}")
            continue
        snap = json.load(open(p, encoding="utf-8"))
        fac = snap.get("facts") or {}
        dec = fac.get("decade")
        pid = (snap.get("meta") or {}).get("player_id")
        tag = os.path.basename(p)
        if pid != SUBJ or not dec:
            print(f"[SKIP] 非本传主十年快照: {tag}")
            continue
        pe = fac.get("church_chronicle") or fac.get("papal_election") or []
        proto = fac.get("protagonist") or {}
        ch = (fac.get("characters") or {}).get(str(SUBJ)) or {}
        print(f"\n[5] {tag} decade={dec} as_of={fac.get('as_of')}")
        check("《礼仪志》第三板块有事实行", bool(pe), pe[:1])
        check("第三板块首行或为教会局面、或为枢机席数",
              any(ln.startswith(("教会局面：", "枢机团：")) for ln in pe), pe[:1])
        check("无「虚悬」", "虚悬" not in surface_of(snap))
        check("last_date 钉到当日（不再被末档闸门挡掉）",
              fac.get("last_date") == fac.get("as_of"),
              (fac.get("last_date"), fac.get("as_of")))
        if dec in (1, 2):
            print("  按当日：此时尚未受任教宗（975.9.24）")
            check("档案名 = 欢乐者洪思忠", ch.get("name") == "欢乐者洪思忠", ch.get("name"))
            check("主角名 = 欢乐者洪思忠", proto.get("name") == "欢乐者洪思忠", proto.get("name"))
            check("无「本名」补注（彼时无教名）", not ch.get("birth_name"), ch.get("birth_name"))
            check("现任教宗不是传主",
                  not any(("现任教宗：" + str(proto.get("name") or "洪思忠")) in ln for ln in pe),
                  pe[1:2])
            check("直辖按当日（京兆、阿尔巴诺）",
                  proto.get("domain") == "京兆、阿尔巴诺", proto.get("domain"))
            check("族谱按当日名", "洪思忠" in str((fac.get("genealogy") or [""])[0]),
                  (fac.get("genealogy") or [""])[0])
        else:
            print("  按当日：975.9.24 已受任教宗")
            check("档案名 = 欢乐者尼各老", ch.get("name") == "欢乐者尼各老", ch.get("name"))
            check("本名补注 = 洪思忠", ch.get("birth_name") == "洪思忠", ch.get("birth_name"))
            check("现任教宗即传主",
                  any("现任教宗：欢乐者尼各老" in ln for ln in pe), pe[:3])


def test_regression():
    """[6] 非时代路径（终传）与 v97 快照逐字节一致：本次改动不动常规生成面。"""
    print("\n[6] 回归：非时代路径与 v97 快照对照")
    if not (os.path.isfile(GF_NEW) and os.path.isfile(GF_OLD)):
        print(f"[SKIP] 对照快照缺: {os.path.basename(GF_NEW)} / {os.path.basename(GF_OLD)}")
        return
    a = json.load(open(GF_OLD, encoding="utf-8"))
    b = json.load(open(GF_NEW, encoding="utf-8"))
    for key in ("facts", "shared", "blocks", "messages"):
        check(f"{key} 无差异",
              json.dumps(a.get(key), ensure_ascii=False, sort_keys=True)
              == json.dumps(b.get(key), ensure_ascii=False, sort_keys=True))


def main():
    snaps = [p for p in sys.argv[1:] if not p.startswith("--")] or DEFAULT
    test_landed_block()
    test_era_view()
    test_decade_era_melt()
    test_decade_file_pattern()
    test_snapshots(snaps)
    test_regression()
    print("\n" + ("ALL OK" if OK else "HAS FAILURES"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
