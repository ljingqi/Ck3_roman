# -*- coding: utf-8 -*-
"""v116 取证：行政制（天朝制）头衔持有人的子女称号从哪来（载一次熔件）。

用户报：世系写「山南王子洪审礼」，但天朝制下除皇帝本人外，官员子女不该有 王子/郡主。
游戏词表（game/common/flavorization/11_tgp_china_flavorization.txt）：
  :1268/1282 prince/princess_kingdom_celestial_chinese            = 公子/公女（only_vassals）
  :1374/1388 *_kingdom_celestial_chinese_independent              = 王子/郡主（only_independent）
  :1240/1254 *_empire_celestial_chinese                           = 公子/公女（only_vassals）
  :1212/1226 *_empire_chinese                                     = 皇子/皇女（only_independent）
本探针只打印输入与各分支输出，不改生产：
  ① 几组「父持有头衔 → tier / key / 当日政府 / 当日独立性与来源」；
  ② 父为行政制头衔持有者时，子女的旧称号 vs「按父之持有末日 + 存档死亡记录 liege 纠正」后的称号。

用法：python -X utf8 tools/tests/v116_probe_admin_princes.py [--peers=135480,...]
输出：logs/v116_probe_admin_princes.txt（调用方重定向）
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")
import cache_lib as cl      # noqa: E402
import facts as F           # noqa: E402
import localization as L    # noqa: E402

FOLDER = "洪氏2"
PID = 207044
AS_OF = "1152.11.13"
# 关注的父子对：cid 由调用方或下面的名单确定（名字 → cid 写在日志里核对）
INTEREST = [
    84824,        # 洪仁德（山南观察使，卒 973）
    177780,       # 洪因（宰相，曾任淮南观察使）
    44503,        # 洪天贵福（天皇帝）
    38957,        # 洪秀全（天皇帝）
]
CHILD_PROBES = [
    (84824, "审礼·洪"),          # 山南王子洪审礼
    (84824, "圣缯·洪堡"),
    (177780, "美美·洪"),
    (177780, "可久·洪"),
]


def melt_path():
    data = os.path.join(ROOT, "output", FOLDER, "data")
    if os.environ.get("V116_MELT"):
        return os.environ["V116_MELT"], data
    melts = [x for x in os.listdir(data) if x.startswith("melt_") and "_idx" not in x]

    def key(name):
        m = re.match(r"^melt_(\d+)_(\d{2})_(\d{2})", name)
        return tuple(int(g) for g in m.groups()) if m else (0, 0, 0)

    return os.path.join(data, max(melts, key=key)), data


def short(v, n=300):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def titles_of(f, cid):
    """Every title the character ever held, with the government/independence inputs."""
    out = []
    for tid, spans in sorted((f._hold_intervals(cid) or {}).items(), key=lambda kv: str(kv[0])):
        t = f._lt.get(str(tid)) or {}
        key = t.get("key") or ""
        first = (spans or [[None]])[0][0]
        last = (spans or [[None]])[-1][1]
        tier = f._RANK_TIER.get(f._TT_RANK.get(key[:2], 0))
        out.append({
            "tid": tid, "key": key, "tier": tier,
            "gain": first, "loss": last,
            "name_at_gain": f._name_at_date(tid, first or AS_OF),
            "name_at_loss_end": f._name_at_date(tid, f._tenure_end(cid, tid) or AS_OF),
            "gov_at_gain": f._title_government(tid, first or AS_OF),
            "gov_at_tenure_end": f._title_government(tid, f._tenure_end(cid, tid) or AS_OF),
            "gov_hist": short(t.get("history_government"), 40),
            "de_facto_liege": t.get("de_facto_liege"),
            "indep_raw": f._is_independent(cid, AS_OF),
            "indep_anchor": f._is_independent(cid, f._anchor_date(cid, AS_OF)),
        })
    return out


def death_liege(f, cid):
    rec = (f.cache.get("characters") or {}).get(str(cid)) or {}
    d = rec.get("death") or {}
    return d.get("liege"), d.get("liege_title"), d.get("date")


def main():
    peers = {}
    for a in sys.argv[1:]:
        if a.startswith("--peers="):
            for x in a.split("=", 1)[1].split(","):
                x = x.strip()
                if x.isdigit():
                    p = os.path.join(ROOT, "output", FOLDER, "data", "player_%s.json" % x)
                    if os.path.exists(p):
                        peers[int(x)] = json.load(io.open(p, encoding="utf-8"))
    mp, data = melt_path()
    print("熔件 %s" % os.path.basename(mp), flush=True)
    melt = cl.load_melt(mp)
    names_path = os.path.join(data, "names.json")
    if not os.path.exists(names_path):
        names_path = os.path.join(ROOT, "data", "names.json")
    cache = json.load(io.open(os.path.join(data, "player_%d.json" % PID), encoding="utf-8"))
    print("同伴缓存 %s" % sorted(peers), flush=True)
    f = F.Facts(cache, melt, names_path, campaign=peers)
    f.as_of = AS_OF
    ch = cache.get("characters") or {}

    def nm(cid):
        r = ch.get(str(cid)) or {}
        return "%s(%s)" % (r.get("name_full") or r.get("name_zh") or "?", cid)

    print("\n===== ① 关注人物的头衔与政府/独立性输入")
    for cid in INTEREST:
        L_, LT_, DD_ = death_liege(f, cid)
        print("\n-- %s  卒=%s  death.liege=%s (liege_title=%s)  自身=%s"
              % (nm(cid), DD_, L_, LT_, cid))
        print("   _anchor_date(as_of)=%s  _is_independent(as_of)=%s  _is_independent(anchor)=%s"
              % (f._anchor_date(cid, AS_OF), f._is_independent(cid, AS_OF),
                 f._is_independent(cid, f._anchor_date(cid, AS_OF))))
        print("   official_title(as_of)=%s   prince_title(as_of)=%s"
              % (f.official_title(cid, AS_OF), f.prince_title(cid, AS_OF)))
        for row in titles_of(f, cid):
            print("   tid=%(tid)s %(key)s tier=%(tier)s %(gain)s→%(loss)s "
                  "名@取得=%(name_at_gain)s 名@末日=%(name_at_loss_end)s "
                  "gov@取得=%(gov_at_gain)s gov@末日=%(gov_at_tenure_end)s "
                  "gov_hist=%(gov_hist)s liege=%(de_facto_liege)s "
                  "indep_raw=%(indep_raw)s indep_anchor=%(indep_anchor)s" % row)

    print("\n===== ② 子女称号：旧口径 vs 候选修正")
    for pcid, cname in CHILD_PROBES:
        kids = [int(x) for x in (((ch.get(str(pcid)) or {}).get("family") or {}).get("child") or [])
                if isinstance(x, int)]
        print("\n-- 父 %s 的子女 %d 名" % (nm(pcid), len(kids)))
        for cid in kids:
            cnm = ch.get(str(cid)) or {}
            full = cnm.get("name_full") or ""
            if cname and cname not in full:
                continue
            old = f.prince_title(cid, AS_OF)
            # 候选：政府与独立性都按父之持有末日读
            t, tid, rd = f._style_parent_title(pcid, AS_OF)
            new = ""
            if t and tid:
                pgov = f._title_government(tid, rd or AS_OF)
                ind = f._is_independent(pcid, f._anchor_date(pcid, rd or AS_OF))
                dl, _lt, _dd = death_liege(f, pcid)
                ind_src = "vassal_history"
                if ind is None or (ind is True and dl is not None and int(dl) != int(pcid)):
                    ind = (dl is None and True) or (int(dl) == int(pcid))
                    ind_src = "death.liege"
                new = f._prince_style_from_title(t, tid, rd or AS_OF, cid, pcid, realm_date=rd)
                print("   %-24s 旧=%-10s 父tier=%s 父末日=%s gov@末日=%-22s indep=%s(%s)"
                      % (nm(cid), old or "(无)", t, rd, pgov, ind, ind_src))
            else:
                print("   %-24s 旧=%-10s 父无头衔" % (nm(cid), old or "(无)"))
        print("   候选下 _prince_word 需要的原始输入已在上表；新称号需在实现后复算。")

    print("\n===== ③ 熔件里相关头衔记录的原始字段")
    lt = ((melt.get("landed_titles") or {}).get("landed_titles") or {})
    tids = set()
    for cid in INTEREST:
        tids |= set((f._hold_intervals(cid) or {}).keys())
    for tid in sorted(tids, key=lambda x: str(x)):
        t = lt.get(str(tid)) or lt.get(int(tid)) or {}
        if not t:
            continue
        nmv = f._name_at_date(tid, AS_OF) or f.title_base_name(tid)
        print("\n   tid=%s 名=%s key=%s" % (tid, nmv, t.get("key")))
        for k in sorted(t.keys()):
            if k in ("history",):
                print("      %-26s = %s" % (k, short(t[k], 200)))
                continue
            print("      %-26s = %s" % (k, short(t[k], 160)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
