# -*- coding: utf-8 -*-
"""一次性施工: 用新版 holy_order_lines 替换 facts.py 里的旧方法 (按 def 边界切)。"""
import io

P = r"D:\Roman\facts.py"
NEW = '''    def _holy_order_chain(self, tid):
        """修会头衔**首府县**沿 `de_facto_liege` 上溯的链 [(tid, holder, key)]。

        首府 = `landed_titles[<修会头衔>].capital`, 即游戏 `leader.capital_county`
        (`common\\\\scripted_effects\\\\00_holy_order_effects.txt:5833,5898`); 链上的持有者
        与层级用来判「这个修会落在谁的领地内」与「谁是庇护者」。"""
        cur = ((self._lt.get(str(tid)) or {}).get("capital"))
        out, seen = [], set()
        while isinstance(cur, int) and cur not in seen:
            seen.add(cur)
            t = self._lt.get(str(cur)) or {}
            out.append((cur, t.get("holder"), str(t.get("key") or "")))
            cur = t.get("de_facto_liege")
        return out

    def _title_holder_since(self, tid, holder, date=None):
        """该头衔在 as_of 之前**最后一次**由 holder 获得的日期 (取不到 '')。"""
        hist = ((self._lt.get(str(tid)) or {}).get("history"))
        if not isinstance(hist, dict):
            return ""
        ao = cl.date_key(date) if date else None
        best = ""
        for d, hv in hist.items():
            if not isinstance(hv, dict) or hv.get("holder") != holder:
                continue
            if ao is not None and cl.date_key(d) > ao:
                continue
            if not best or cl.date_key(d) > cl.date_key(best):
                best = str(d)
        return best

    def holy_order_lines(self, cid, date=None):
        """传主**亲立 / 庇护 / 领地内**的修会句 (《礼仪志》开篇; v88 问题3-P3A、v89 问题5)。

        数据源: 熔件顶层 `holy_orders.holy_orders[<id>]`
        = `{rite, title, titles[], founder, worldliness, holy_order_type, tenet}`。

        收录口径 (v89 问题5, 用户 2026-10-02 拍板「领地内同信仰修会」) 二者任一:
        · **亲立**: `founder == cid` (入档、永不变);
        · **领地内同信仰**: 该修会与传主同信仰, 且其首府县沿 `de_facto_liege` 上溯的
          链上出现 cid —— 等价于「庇护者是 cid 本人或他的(次级)封臣」。
          游戏侧 `holy_order_patron` 是**引擎实时算的派生关系、不落存档** (原始 217MB
          存档字节扫描 0 命中; 见 docs/调研_v89_修会庇护者.md §3), 判据 = 与修会同信仰、
          层级 ≥ 公爵、realm 含其首府, **就近**取链上第一个公爵以上的持有者
          (`common\\defines\\00_defines.txt:1312 PATRON_MIN_TIER = 3`)。

        截断: 取该修会**头衔的创立日** (`landed_titles[<title>].date`, 缺则取 `history`
        最早一键) —— 洪氏2 实测 丅形十字骑士团头衔 880.10.6 立、南岭隐修院 891.4.16 立,
        故第 2 个十年 (as_of=888) 只写前者、第 3 个十年 (898) 两个都写。

        **不写成员层** (全档在世 `order_member` 仅 0.11%, 见调研_v88 §2.2), 也**不写**
        `worldliness` (世俗度; 本档 29 个修会全为 0, 且 `MAX_WORLDLINESS` 不在随包
        defines 里 —— 不可作素材)。v89 补「现任之长」(修会头衔当档持有者 + 其取得日;
        旧稿风格要求写了却不给, 模型遂编出「殿中监善德为之副」)。

        名称走 `self.title()` (项目唯一头衔出词口; 存档烘焙名 `title_name_data.name`
        为备选, 同一个修会两者可能是「桂林骑士团教团」/「丅形十字骑士团」)。"""
        if cid is None:
            return []
        ho = (self.melt.get("holy_orders") or {}).get("holy_orders") or {}
        if not ho:
            return []
        ao = cl.date_key(date) if date else None
        my_rite = self._rite_id(cid, date)
        my_faith = self._faith_id(cid, date)
        rows = []
        for _hid, h in ho.items():
            if not isinstance(h, dict):
                continue
            tid = h.get("title")
            if not isinstance(tid, int):
                continue
            is_founder = h.get("founder") == cid
            rid = h.get("rite")
            ofaith = cl.faith_id_of_rite(self.melt, rid) \\
                if isinstance(rid, int) else None
            chain = self._holy_order_chain(tid)
            holders = [x[1] for x in chain]
            in_realm = cid in holders
            patron = None
            for _t2, _hold, _key in chain:
                if isinstance(_hold, int) and self._TT_RANK.get(_key[:2], 0) >= 3:
                    patron = _hold
                    break
            same_faith = (my_faith is not None and ofaith is not None
                          and my_faith == ofaith)
            if not (is_founder or (same_faith and in_realm)):
                continue
            lt = self._lt.get(str(tid)) or {}
            fdate = lt.get("date")
            if not fdate:
                _hist = lt.get("history")
                if isinstance(_hist, dict) and _hist:
                    fdate = min(_hist, key=cl.date_key)
            if ao is not None and (not fdate or cl.date_key(fdate) > ao):
                continue          # 尚未创立 (十年传记不穿越)
            name = self.title(tid, date) or ""
            if not name:
                continue
            year = self._year_only(fdate) if fdate else ""
            if is_founder:
                head = f"{year}，他立{name}" if year else f"他立{name}"
            elif patron == cid:
                head = f"{year}，他是{name}的庇护者" if year \\
                    else f"他是{name}的庇护者"
            else:
                head = f"{year}，{name}在其领地之内" if year \\
                    else f"{name}在其领地之内"
            bits = []
            rname = cl.rite_name_of(self.melt, rid) if isinstance(rid, int) else ""
            if rname and (my_rite is None or rid != my_rite):
                bits.append(f"其礼为{rname}")
            ten = h.get("tenet")
            if ten:
                tn = self.tenet_name(ten, rid if isinstance(rid, int) else None)
                if tn:
                    bits.append(f"会规：{tn}")
            lands = [self.title(t, date) for t in (h.get("titles") or [])
                     if isinstance(t, int)]
            lands = [x for x in lands if x]
            if lands:
                shown = "、".join(lands[:2])
                bits.append(f"领{shown}等{len(lands)}处教堂领地"
                            if len(lands) > 2 else f"领{'、'.join(lands)}")
            if patron is not None and patron != cid:
                pn = self.event_name(patron, date=date)
                if pn:
                    bits.append(f"庇护者是{pn}")
            cur = lt.get("holder")
            if isinstance(cur, int):
                cn = self.event_name(cur, date=date)
                hd = self._title_holder_since(tid, cur, date)
                if cn:
                    bits.append("现任之长" + cn
                                + (f"（自{self._year_only(hd)}年起）" if hd else ""))
            rows.append(head + ("，" + "，".join(bits) if bits else "") + "。")
        return rows

'''

src = io.open(P, encoding="utf-8").read()
a = src.index("    def holy_order_lines(self, cid, date=None):")
b = src.index("    def forbidden_tenet_lines(self, cid, date=None):")
out = src[:a] + NEW + src[b:]
io.open(P, "w", encoding="utf-8", newline="").write(out)
print("replaced", b - a, "chars with", len(NEW))
