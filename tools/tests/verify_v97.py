# -*- coding: utf-8 -*-
"""v97 专项断言（秒级，跑在快照上；不载熔件）。

四问：
  ① 教宗本名带姓 —— 传主档案 birth_name 为「洪思忠」（无姓者保持本名）
  ② 教省不当营地 —— 传输面出现「京兆总主教」、不出现「京兆之主」「无地冒险者营地」；
     传主无营地区间（protagonist_stations 为空）
  ③ 枢机虚悬不下发 —— 传输面无「虚悬」；在位枢机行只有席数
  ④ 结仇缘由点名被害人 —— 出现「谋杀了…的弟弟洪翊」、不出现「亲近之人」
回归：
  ⑤ title_kind 分类（纯函数）—— 真营地/教省/雇佣团/骑士团/世族/毡帐 各归各类
  ⑥ 真冒险者快照仍有【冒险者行踪】（斯卡利茨 15403，缺该快照则跳过）

用法：
    & tools\\py.ps1 tools\\tests\\verify_v97.py [快照...]
    （缺省取 output/洪氏2/data/snap_v97_d1.json 与 snap_v97_d3.json）
"""
import inspect
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import facts as F   # noqa: E402

OK = True
H2 = os.path.join(ROOT, "output", "洪氏2", "data")
DEFAULT = [os.path.join(H2, "v97_d1.json"), os.path.join(H2, "v97_d3.json")]
# The final-biography snapshot is optional: the cardinal block is emitted only while the cache's
# last_date is not ahead of the cut-off, so a later save drops it (pre-existing gate).
OPTIONAL = [os.path.join(H2, "v97_gf.json")]
ADV = os.path.join(ROOT, "output", "斯卡利茨", "data", "v97_adv.json")


def check(name, cond, extra=None):
    global OK
    if not cond:
        OK = False
    print(f"  {'OK  ' if cond else 'FAIL'} {name}"
          + (f"   ← {str(extra)[:220]!r}" if extra is not None and not cond else ""))


def surface_of(snap):
    """全请求面 = 事实面 + 各板块 + 逐请求消息（与 verify_fast 同口径）。"""
    parts = [json.dumps(snap.get("facts") or {}, ensure_ascii=False),
             json.dumps(snap.get("blocks") or {}, ensure_ascii=False),
             json.dumps(snap.get("shared") or {}, ensure_ascii=False)]
    for m in snap.get("messages") or []:
        parts.append(json.dumps(m, ensure_ascii=False))
    return "\n".join(parts)


def mk_kind():
    """只带 _lt 的 Facts 替身：title_kind 是纯查表函数。"""
    f = F.Facts.__new__(F.Facts)
    f._lt = {
        "1": {"key": "x_d_laamp_552", "title_name_data": {"name": "私生子大队"}},
        "2": {"key": "x_script_2974", "title_name_data": {"name": "京兆"},
              "clerical_region": {"clerical_region": 53, "domicile": 1952},
              "landless": True},
        "3": {"key": "x_mc_354", "title_name_data": {"name": "中车子国室韦大队"},
              "landless": True},
        "4": {"key": "x_ho_6455", "title_name_data": {"name": "圣伯多禄骑士团"},
              "landless": True},
        "5": {"key": "x_nf_551", "title_name_data": {"name": "洪家族"}, "landless": True},
        "6": {"key": "x_c_nomad_552", "title_name_data": {"name": "美马游牧营地"},
              "landless": True},
        "7": {"key": "c_roma", "title_name_data": {"name": "罗马"}},
        "8": {"key": "d_et_roma", "title_name_data": {"name": "罗马"},
              "clerical_region": {"clerical_region": 0, "domicile": 1}},
        "9": {"key": "c_nf_han", "title_name_data": {"name": "汉家族"}},
    }
    return f


def main():
    snaps = [p for p in sys.argv[1:] if not p.startswith("--")] or (DEFAULT + OPTIONAL)

    print("[③-源代码守卫] 枢机事实行不再产出空缺席数")
    src = inspect.getsource(F.Facts.papal_election_lines)
    check("papal_election_lines 源内无「虚悬」", "虚悬" not in src)
    check("papal_election_lines 仍出「在位枢机」", "在位枢机" in src)

    print("[⑤] title_kind 分类（纯函数）")
    f = mk_kind()
    check("d_laamp_ → camp", f.title_kind(1) == "camp", f.title_kind(1))
    check("x_script_ 教省 → clerical", f.title_kind(2) == "clerical", f.title_kind(2))
    check("d_et_ 教省 → clerical", f.title_kind(8) == "clerical", f.title_kind(8))
    check("x_mc_ 雇佣团 → landless", f.title_kind(3) == "landless", f.title_kind(3))
    check("x_ho_ 骑士团 → landless", f.title_kind(4) == "landless", f.title_kind(4))
    check("x_nf_ 世族庄园 → estate", f.title_kind(5) == "estate", f.title_kind(5))
    check("c_nf_ 世族庄园 → estate", f.title_kind(9) == "estate", f.title_kind(9))
    check("x_c_nomad_ 毡帐 → nomad", f.title_kind(6) == "nomad", f.title_kind(6))
    check("c_ 领地 → ''", f.title_kind(7) == "", f.title_kind(7))
    check("教省不参与首要头衔（_eff_rank=0）", f._eff_rank(2) == 0, f._eff_rank(2))

    for p in snaps:
        if not os.path.isfile(p):
            print(f"[SKIP] 快照不存在: {p}")
            continue
        with open(p, encoding="utf-8") as fp:
            snap = json.load(fp)
        fac = snap.get("facts") or {}
        surf = surface_of(snap)
        tag = os.path.basename(p)
        pid = (snap.get("meta") or {}).get("player_id")
        # ① / ② 营地面 / ④ are about the v97 protagonist (洪思忠); other snapshots run the
        # campaign-independent part of ② and ③ only.
        subj = (pid == 67172818)
        print(f"\n[{tag}] pid={pid} as_of={fac.get('as_of')}"
              + ("（v97 传主）" if subj else "（他人：只跑通用面）"))

        if subj:
            print("  [①] 本名带姓")
            bn = (fac.get("protagonist") or {}).get("birth_name") or ""
            check("birth_name = 洪思忠", bn == "洪思忠", bn)
            check("传输面含「本名：洪思忠」", "本名：洪思忠" in surf)

        print("  [②] 教省不当营地")
        check("无「京兆之主」", "京兆之主" not in surf)
        if subj:
            check("无「无地冒险者营地」", "无地冒险者营地" not in surf)
            check("含「京兆总主教」", "京兆总主教" in surf)
            check("protagonist_stations 为空", not (fac.get("protagonist_stations") or []),
                  (fac.get("protagonist_stations") or [])[:2])
            check("protagonist.landless 不为真",
                  not (fac.get("protagonist") or {}).get("landless"))
            check("历任行见「京兆总主教」",
                  "京兆总主教" in str((fac.get("protagonist") or {}).get("titles_held") or ""),
                  (fac.get("protagonist") or {}).get("titles_held"))

        print("  [③] 枢机虚悬不下发")
        check("无「虚悬」", "虚悬" not in surf)

        if subj:
            print("  [④] 结仇缘由点名被害人")
            check("无「亲近之人」", "亲近之人" not in surf)
            check("含「弟弟洪翊」", "弟弟洪翊" in surf)

    if os.path.isfile(ADV):
        with open(ADV, encoding="utf-8") as fp:
            snap = json.load(fp)
        st = (snap.get("facts") or {}).get("protagonist_stations") or []
        print(f"\n[⑥] 真冒险者回归 {os.path.basename(ADV)}")
        check("【冒险者行踪】仍非空", bool(st), st[:2])
        check("首行仍写营地称呼词", bool(st) and "营地" in st[0], st[:1])
    else:
        print(f"\n[SKIP] 真冒险者快照不存在: {ADV}")

    print("\n" + ("ALL OK" if OK else "HAS FAILURES"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
