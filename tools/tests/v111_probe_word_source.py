# -*- coding: utf-8 -*-
"""v111 探查：头衔名 / 身份词到底从哪一步来（只读 · 载一次熔件）。

两个已报缺陷都指向「词从哪来」：
  ① 洪七公 1144 年受任的头衔，代码叫「室韦节度使」，游戏里显示「辽西节度使」；
  ② 洪七公之父 16945142 的身份词，代码叫「伯爵」，游戏里是「刺史」。

本探针不做判断，只把每一步的输入输出摊开：头衔 id / key / 各期名 / 名史 /
动态名，人物的政体史、封臣史、主头衔、`official_title`、`_office_word` 走的是
哪一支（flavorization / celestial 独立 / celestial 附庸 / nomad / 文化词 / 通用键）。

用法：
    & tools\\py.ps1 tools\\tests\\v111_probe_word_source.py <folder> <pid> [<pid> ...]
可选环境变量：V111_TITLES=0 不打印头衔表；V111_MELT=<path> 指定熔件。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402
import localization as L    # noqa: E402


def _melt_path(folder):
    data = os.path.join(ROOT, "output", folder, "data")
    if os.environ.get("V111_MELT"):
        return os.environ["V111_MELT"], data
    melts = [x for x in os.listdir(data) if x.startswith("melt_") and "_idx" not in x]

    def key(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)

    return os.path.join(data, max(melts, key=key)), data


def _short(v, n=400):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def dump_titles(f, cid):
    """Every holding of `cid` with all name sources, one line per title."""
    print("  -- 头衔（id / key / 名史 / 动态名 / _name_at_date(起始) / base / office_text）")
    ivs = f._hold_intervals(cid) or {}
    for tid, spans in sorted(ivs.items(), key=lambda kv: str(kv[0])):
        t = f._lt.get(str(tid)) or {}
        tnd = t.get("title_name_data") or {}
        first = (spans or [[None]])[0][0]
        hist = f._history_name_at(tid, first)
        print("   tid=%-8s key=%-24s rank=%s spans=%s" % (
            tid, t.get("key"), f._TT_RANK.get((t.get("key") or "")[:2], 0), _short(spans, 120)))
        print("        tnd=%s" % _short({"name": tnd.get("name"), "custom": tnd.get("custom"),
                                        "specific": tnd.get("specific_title_name")}, 200))
        print("        history_name_at(%s)=%s  has_reign_history=%s" % (
            first, _short(hist, 60), f._has_reign_history(tid)))
        for d in [first] + [s[0] for s in (spans or [])[1:]]:
            print("        @%-12s dyn=%-14s name_at_date=%-14s base=%-14s office=%s" % (
                d, _short(f._dyn_reign_name(tid, d), 14),
                _short(f._name_at_date(tid, d), 14), _short(f.title_base_name(tid), 14),
                _short(f.title_office_text(cid, tid, d), 24)))
        print("        loc(key)=%s" % _short(L.loc(f.table, t.get("key") or ""), 60))
        if hist is not None:
            print("        loc(history_name)=%s" % _short(L.loc(f.table, str(hist)), 60))


def trace_office(f, cid, date):
    """Which branch of `_office_word` supplies the word, and every input of the choice."""
    rec = (f.cache.get("characters") or {}).get(str(cid)) or {}
    dd = ((rec.get("death") or {}).get("date")) or ""
    if dd and date and cl.date_key(date) > cl.date_key(dd):
        date = dd
    tier, tid = f._primary_title_at(cid, as_of=date)
    _c = f._chars.get(str(cid)) or {}
    print("  -- 身份词追溯 cid=%s date=%s（卒 %s）" % (cid, date, dd))
    print("     dead_data=%s" % _short(_c.get("dead_data"), 400))
    print("     anchor=%s  dead_flavor=%r  consistent=%s  last_title_place=%r" % (
        f._anchor_date(cid, date), (_c.get("dead_data") or {}).get("flavor"),
        f._dead_flavor_consistent((_c.get("dead_data") or {}).get("flavor") or "", cid,
                                  f._anchor_date(cid, date)),
        f._last_title_place(cid, (_c.get("dead_data") or {}).get("flavor") or "",
                            date=f._anchor_date(cid, date))))
    print("     primary_title=%s tid=%s key=%s" % (
        tier, tid, ((f._lt.get(str(tid)) or {}).get("key") if tid else None)))
    gh = f._gov_history(cid)
    print("     gov_history=%s" % _short(gh, 300))
    print("     character_government=%s  vassal_history=%s" % (
        f._character_government(cid, date), _short(f._vassal_history(cid), 300)))
    vh = f._vassal_entry_at(cid, date)
    print("     vassal_entry_at=%s  is_independent=%s" % (_short(vh, 200), f._is_independent(cid, date)))
    gov = f._gov_for_word(cid, tid, date)
    print("     gov_for_word=%s  celestial_like=%s" % (gov, gov in f._CELESTIAL_LIKE_GOVS))
    if tid is not None:
        print("     title_government_hist=%s  history_government=%s" % (
            f._title_government_hist(tid, date), (f._lt.get(str(tid)) or {}).get("history_government")))
    print("     flavor_key=%s  = %s" % (
        f._flavor_key("character", tier, cid, tid=tid, gender="male", gov=gov, date=date),
        _short(L.loc(f.table, f._flavor_key("character", tier, cid, tid=tid, gender="male",
                                            gov=gov, date=date) or ""), 40)))
    print("     culture_office_word=%s" % _short(f._culture_office_word(cid, tier, False, False), 40))
    print("     prince_title=%s  accolade=%s  name_with_regnal=%s" % (
        f.prince_title(cid, date), f.accolade_word_at(cid, date), f.name_with_regnal(cid, date)))
    for key in ("%s_celestial_male_chinese_governor" % f._TIER_KEY.get(tier, ""),
                "count_independent_male_feudal_chinese",
                "count_male_feudal_chinese", "county_celestial_chinese_vassal",
                "duchy_celestial_chinese_vassal"):
        v = L.loc(f.table, key)
        if v:
            print("     loc[%s]=%s" % (key, _short(v, 30)))
    print("     official_title=%s" % f.official_title(cid, date))
    # 拟修后的两条路径（只打印，不改生产）：跳过「无地点无政体的裸档位键」后，
    # 头衔路径要能找到死亡当日仍在手的头衔（held_through），据此拼出 <地名><官职词>。
    for _th in (None, f._anchor_date(cid, date)):
        print("     [sim] primary_title_at(held_through=%s)=%s -> %s" % (
            _th, f._primary_title_at(cid, as_of=f._anchor_date(cid, date), held_through=_th),
            f.title_office_text(cid, (f._primary_title_at(cid, as_of=f._anchor_date(cid, date),
                                                         held_through=_th) or (None, None))[1],
                                f._anchor_date(cid, date))))
    print("     [sim] 静态名（游戏封套口径）=%s" % f.title_base_name(
        (f._primary_title_at(cid, as_of=f._anchor_date(cid, date)) or (None, None))[1]))
    print("     person_label(full)=%s brief=%s event=%s" % (
        f.person_label(cid, date, "full"), f.person_label(cid, date, "brief"),
        f.person_label(cid, date, "event")))
    print("     kin_label=%s" % f.kin_label(cid))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    folder, pids = sys.argv[1], [int(x) for x in sys.argv[2:]]
    melt_path, data = _melt_path(folder)
    print("熔件 %s" % os.path.basename(melt_path), flush=True)
    melt = cl.load_melt(melt_path)
    raw_env = os.environ.get("V111_RAW") or ""
    if raw_env:
        lt = ((melt.get("landed_titles") or {}).get("landed_titles") or {})
        for x in raw_env.split(","):
            x = x.strip()
            if x:
                print("\n#### raw title %s = %s" % (x, json.dumps(lt.get(x) or lt.get(int(x)) or {},
                                                                  ensure_ascii=False)[:4000]))
    names_path = os.path.join(data, "names.json")
    if not os.path.exists(names_path):
        names_path = os.path.join(ROOT, "data", "names.json")
    if os.environ.get("V111_SCAN"):
        chars = cl.all_characters(melt)
        lt = ((melt.get("landed_titles") or {}).get("landed_titles") or {})
        import collections
        flav = collections.Counter()
        bare = collections.Counter()
        BARE = {"baron", "count", "duke", "king", "emperor", "hegemon",
                "baron_female", "count_female", "duke_female", "king_female",
                "emperor_female", "hegemon_female"}
        n_dead = 0
        for cid, c in chars.items():
            if not isinstance(c, dict):
                continue
            dd = c.get("dead_data")
            if not isinstance(dd, dict) or not dd.get("date"):
                continue
            n_dead += 1
            fk = str(dd.get("flavor") or "")
            flav[fk] += 1
            if fk in BARE:
                bare[fk] += 1
        print("\n#### 熔件人物 dead_data.flavor 统计：死者 %d 名" % n_dead)
        print("   裸档位键合计 %d：%s" % (sum(bare.values()), dict(bare)))
        print("   最常见的 12 个键：%s" % flav.most_common(12))
        n_named = n_diff = n_diff_hist = 0
        for tid, t in lt.items():
            if not isinstance(t, dict):
                continue
            tnd = t.get("title_name_data") or {}
            nm = (tnd.get("name") or "").strip()
            sp = (tnd.get("specific_title_name") or "").strip()
            if not nm:
                continue
            n_named += 1
            if sp and sp != nm:
                n_diff += 1
                if tnd.get("title_history_names"):
                    n_diff_hist += 1
        print("#### 头衔：有静态 name 的 %d 个，其中 specific_title_name 与 name 不同 %d 个"
              "（且带 title_history_names 的 %d 个）" % (n_named, n_diff, n_diff_hist))
    for pid in pids:
        cache = json.load(open(os.path.join(data, "player_%d.json" % pid), encoding="utf-8"))
        # peers: production passes every player cache of the same playthrough_id
        # (pipeline._campaign_caches). Loading all ten is gigabytes of RAM, so the probe takes an
        # explicit short list instead: V111_PEERS=16945142,33725392
        campaign = {}
        for x in (os.environ.get("V111_PEERS") or "").split(","):
            x = x.strip()
            if not x.isdigit() or int(x) == pid:
                continue
            p = os.path.join(data, "player_%s.json" % x)
            if not os.path.exists(p):
                print("   (缺 %s，跳过)" % p)
                continue
            pc = json.load(open(p, encoding="utf-8"))
            if pc.get("playthrough_id") != cache.get("playthrough_id"):
                print("   (cid=%s 不同战役，跳过)" % x)
                continue
            campaign[int(x)] = pc
        if campaign:
            print("   同伴缓存（同战役）: %s" % sorted(campaign))
        f = F.Facts(cache, melt, names_path, campaign=campaign)
        rec = (cache.get("characters") or {}).get(str(pid)) or {}
        print("\n==== cid=%s name=%s birth=%s death=%s" % (
            pid, rec.get("name"), rec.get("birth"), (rec.get("death") or {}).get("date")))
        fam = rec.get("family") or {}
        print("     family father=%s mother=%s landed=%s" % (
            fam.get("father"), fam.get("mother"), _short(rec.get("landed"), 300)))
        for k in ("char_government_history", "char_vassal_history"):
            v = (cache.get(k) or {}).get(str(pid))
            if v:
                print("     %s=%s" % (k, _short(v, 400)))
        print("     本人身份词：")
        trace_office(f, pid, f.as_of or (rec.get("death") or {}).get("date"))
        for fid in (fam.get("father") or [])[:2]:
            frec = (cache.get("characters") or {}).get(str(fid)) or {}
            fdd = (frec.get("death") or {}).get("date")
            print("\n     父亲 cid=%s name=%s birth=%s death=%s landed=%s" % (
                fid, frec.get("name"), frec.get("birth"), fdd, _short(frec.get("landed"), 300)))
            print("     father.label=%s  father_entries=%s" % (
                _short((frec.get("label")), 80), _short(frec.get("father"), 80)))
            for d in (["1109.4.25", fdd] if fdd else ["1109.4.25"]):
                if d:
                    trace_office(f, fid, d)
        if os.environ.get("V111_DYN"):
            for x in os.environ["V111_DYN"].split(","):
                x = x.strip()
                if not x:
                    continue
                print("\n  #### title_dyn_names[%s]" % x)
                for cid_, c_ in [(pid, cache)] + sorted(campaign.items()):
                    h = (c_.get("title_dyn_names") or {}).get(x)
                    if h is not None:
                        print("     缓存 %s: %s" % (cid_, _short(h, 600)))
                t = f._lt.get(x) or {}
                print("     熔件 title_name_data=%s" % _short(t.get("title_name_data"), 600))
                print("     _dyn_hist=%s" % _short(f._dyn_hist(int(x)), 600))
        if os.environ.get("V111_TITLES", "1") != "0":
            print("     本人头衔表：")
            dump_titles(f, pid)
            for fid in (fam.get("father") or [])[:2]:
                print("     父亲 %s 头衔表：" % fid)
                dump_titles(f, fid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
