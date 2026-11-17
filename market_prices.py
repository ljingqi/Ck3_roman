# -*- coding: utf-8 -*-
"""Market price store (SQLite)
=============================
CK3 1.21 keeps no price in the save: the engine derives a good's buy/sell price from its base
price, the market duchy's prosperity and modifiers, while routes record the price actually paid
(`transactions.price_per_unit`). This module stores both per snapshot in a small SQLite file
next to the player caches (`output/<家族>/data/market_prices.db`):

- `market_good`  : every market x good need/production row plus the computed baseline buy/sell
                   price (`price_source = 'computed_baseline'`);
- `route` / `route_transaction` : every trade route and the price it traded at, so the observed
                   price survives a route that later disappears or changes hands.

The store is rebuilt per (playthrough_id, date): re-ingesting a snapshot replaces that date's
rows, so catch-up and watch runs can both call `ingest_melt` safely.

Usage: python market_prices.py check <data_dir>
"""
import io
import json
import os
import re
import sqlite3
import sys

DB_NAME = "market_prices.db"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(
  key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS snapshot(
  playthrough_id TEXT, date TEXT, game_version TEXT, source TEXT,
  PRIMARY KEY(playthrough_id, date));
CREATE TABLE IF NOT EXISTS market(
  playthrough_id TEXT, market_id INTEGER, location_province INTEGER,
  duchy_title INTEGER, toll_level TEXT,
  PRIMARY KEY(playthrough_id, market_id));
CREATE TABLE IF NOT EXISTS market_good(
  playthrough_id TEXT, date TEXT, market_id INTEGER,
  good_index INTEGER, good_key TEXT,
  need REAL, import_only_need REAL, production REAL, surplus REAL,
  import REAL, export REAL, distribution_import REAL,
  exploitative_exports REAL, total_production REAL, entrepot_production REAL,
  prosperity REAL, buy_price REAL, sell_price REAL,
  price_source TEXT,
  PRIMARY KEY(playthrough_id, date, market_id, good_index));
CREATE INDEX IF NOT EXISTS idx_market_good
  ON market_good(playthrough_id, good_index, date);
CREATE TABLE IF NOT EXISTS route(
  playthrough_id TEXT, date TEXT, route_id INTEGER, owner INTEGER,
  mode TEXT, created TEXT, primary_good TEXT, gold REAL,
  trader INTEGER, commissioner INTEGER, commission_expiration TEXT,
  markets TEXT, path TEXT,
  PRIMARY KEY(playthrough_id, date, route_id));
CREATE TABLE IF NOT EXISTS route_transaction(
  playthrough_id TEXT, date TEXT, route_id INTEGER, market_id INTEGER,
  good_key TEXT, type TEXT, amount REAL, price_per_unit REAL,
  fulfilled_category TEXT,
  PRIMARY KEY(playthrough_id, date, route_id, market_id, good_key, type));
"""

# Defines (common/defines/00_defines.txt): Buy = (base + add) * prosperity * mult * scalar.
_BUY_SCALAR = 0.95
_SELL_SCALAR = 1.0
_BUY_BASELINE = 50.0
_BUY_BELOW_MULT = 0.003
_SELL_BASELINE = 0.0
_SELL_ABOVE_MULT = 0.005


def _connect(data_dir):
    os.makedirs(data_dir, exist_ok=True)
    conn = sqlite3.connect(os.path.join(data_dir, DB_NAME), timeout=30)
    conn.executescript(_SCHEMA)
    return conn


def _good_table(cfg):
    """[(good_key, base_price)] in the game's declaration order (index == position). Mods that
    add goods are appended; a redefined good keeps its first index."""
    import localization as L
    roots = []
    g = L.game_dir(cfg)
    if g:
        roots.append(g)
    roots += L.enabled_mod_dirs(cfg)
    order, base, seen = [], {}, set()
    for root in roots:
        d = os.path.join(root, "common", "trade", "trade_good_types")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with io.open(os.path.join(d, fn), encoding="utf-8-sig",
                             errors="replace") as fp:
                    txt = fp.read()
            except OSError:
                continue
            txt = re.sub(r"#[^\n]*", "", txt)
            for m in re.finditer(r"(?m)^\s*(trade_good_[A-Za-z0-9_]+)\s*=\s*\{", txt):
                key = m.group(1)
                if key in seen:
                    continue
                seen.add(key)
                seg = txt[m.end():m.end() + 400]
                bp = re.search(r"base_price\s*=\s*([0-9.]+)", seg)
                order.append(key)
                base[key] = float(bp.group(1)) if bp else None
    return order, base


_BASE_CACHE = {}


def good_base_prices(cfg=None):
    """{good_key: base_price} from the game/mod declarations, cached per game dir.

    The declaration order is also the save's good index, so callers that only need the
    prices (route material) share this with the ingestion path."""
    import localization as L
    key = (L.game_dir(cfg) or "", tuple(L.enabled_mod_dirs(cfg) or []))
    hit = _BASE_CACHE.get(key)
    if hit is None:
        hit = _good_table(cfg)[1]
        _BASE_CACHE[key] = hit
    return hit


def _duchy_prosperity(melt):
    """{duchy title id: average prosperity of its de jure counties} (missing -> absent)."""
    lts = ((melt.get("landed_titles") or {}).get("landed_titles") or {})
    counties = (melt.get("county_manager") or {}).get("counties") or {}
    out = {}
    for tid, t in lts.items():
        if not isinstance(t, dict) or not str(t.get("key") or "").startswith("d_"):
            continue
        vals = []
        for cid in t.get("de_jure_vassals") or []:
            ct = lts.get(str(cid)) or {}
            ckey = ct.get("key") or ""
            if not str(ckey).startswith("c_"):
                continue
            p = (counties.get(ckey) or {}).get("prosperity")
            if p is not None:
                vals.append(float(p))
        if vals:
            try:
                out[int(tid)] = sum(vals) / len(vals)
            except (TypeError, ValueError):
                continue
    return out


def _prices_of(base, prosperity):
    """(buy, sell) baseline prices, None when the base price or prosperity is unknown."""
    if base is None or prosperity is None:
        return None, None
    buy_mult = max(0.0, 1.0 - _BUY_BELOW_MULT * max(0.0, _BUY_BASELINE - prosperity))
    sell_mult = 1.0 + _SELL_ABOVE_MULT * max(0.0, prosperity - _SELL_BASELINE)
    return base * buy_mult * _BUY_SCALAR, base * sell_mult * _SELL_SCALAR


def _route_transactions(route_id, tx):
    rows = []
    for t in (tx if isinstance(tx, list) else [tx]):
        if not isinstance(t, dict):
            continue
        try:
            mid = int(t.get("trade_market"))
        except (TypeError, ValueError):
            mid = None
        good = t.get("trade_good") or ""
        if isinstance(good, list):
            goods = [str(x) for x in good]
        else:
            goods = [str(good)] if good else []
        for gk in goods:
            rows.append((route_id, mid, gk, t.get("type") or "",
                         t.get("amount"), t.get("price_per_unit"),
                         t.get("fulfilled_category")))
    return rows


def ingest_melt(melt, data_dir, *, cfg=None, source=""):
    """Store one snapshot's markets, goods and routes. Returns the market_good row count."""
    if not isinstance(melt, dict) or not data_dir:
        return 0
    markets = ((melt.get("trade_markets") or {}).get("database") or {})
    routes = ((melt.get("trade_routes") or {}).get("database") or {})
    if not markets and not routes:
        return 0
    pid = str(melt.get("playthrough_id") or "")
    meta = melt.get("meta_data") or {}
    date = meta.get("meta_date") or melt.get("date") or ""
    if not pid or not date:
        return 0
    if cfg is None:
        import llm
        cfg = llm.load_config()
    goods, base_price = _good_table(cfg)
    good_key = {i: k for i, k in enumerate(goods)}
    prosperity = _duchy_prosperity(melt)

    conn = _connect(data_dir)
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('good_index', ?)",
                         (json.dumps(goods, ensure_ascii=False),))
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('game_version', ?)",
                         (str(meta.get("version") or ""),))
            conn.execute("INSERT OR REPLACE INTO snapshot VALUES(?,?,?,?)",
                         (pid, date, str(meta.get("version") or ""), source))
            conn.execute("DELETE FROM market_good WHERE playthrough_id=? AND date=?",
                         (pid, date))
            conn.execute("DELETE FROM route WHERE playthrough_id=? AND date=?",
                         (pid, date))
            conn.execute("DELETE FROM route_transaction WHERE playthrough_id=? AND date=?",
                         (pid, date))

            mg_rows = []
            for mkey, m in markets.items():
                if not isinstance(m, dict):
                    continue
                try:
                    mid = int(mkey)
                except (TypeError, ValueError):
                    continue
                conn.execute(
                    "INSERT OR REPLACE INTO market VALUES(?,?,?,?,?)",
                    (pid, mid, m.get("location"), m.get("duchy"),
                     m.get("toll_level") or ""))
                try:
                    duchy = int(m.get("duchy"))
                except (TypeError, ValueError):
                    duchy = None
                pros = prosperity.get(duchy)
                for gkey, b in (m.get("good_balances") or {}).items():
                    if not isinstance(b, dict):
                        continue
                    try:
                        gi = int(gkey)
                    except (TypeError, ValueError):
                        continue
                    gk = good_key.get(gi)
                    buy, sell = _prices_of(base_price.get(gk), pros)
                    mg_rows.append((
                        pid, date, mid, gi, gk,
                        b.get("need"), b.get("import_only_need"), b.get("production"),
                        b.get("surplus"), b.get("import"), b.get("export"),
                        b.get("distribution_import"), b.get("exploitative_exports"),
                        b.get("total_production"), b.get("entrepot_production"),
                        pros, buy, sell, "computed_baseline"))
            if mg_rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO market_good VALUES("
                    + ",".join("?" * 19) + ")", mg_rows)

            for rkey, r in routes.items():
                if not isinstance(r, dict):
                    continue
                try:
                    rid = int(rkey)
                except (TypeError, ValueError):
                    continue
                tr = r.get("trader") or {}
                conn.execute(
                    "INSERT OR REPLACE INTO route VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, date, rid, r.get("owner"), r.get("mode"), r.get("created"),
                     r.get("primary_good"), r.get("gold"),
                     tr.get("character") if isinstance(tr, dict) else None,
                     r.get("commissioner"), r.get("commission_expiration"),
                     json.dumps(r.get("trade_markets") or []),
                     json.dumps(r.get("path") or [])))
                tx_rows = []
                for trow in _route_transactions(rid, r.get("transactions")):
                    tx_rows.append((pid, date) + trow)
                if tx_rows:
                    conn.executemany(
                        "INSERT OR REPLACE INTO route_transaction VALUES("
                        + ",".join("?" * 9) + ")", tx_rows)
        return len(mg_rows)
    finally:
        conn.close()


def prices(playthrough_id=None, market_id=None, good_key=None, start=None, end=None,
           *, data_dir):
    """Observed price rows {date, market_id, good_key, prosperity, buy_price, sell_price, …}."""
    conn = _connect(data_dir)
    try:
        conn.row_factory = sqlite3.Row
        q = ("SELECT date, market_id, good_index, good_key, need, production, surplus, "
             "import, export, prosperity, buy_price, sell_price, price_source "
             "FROM market_good WHERE 1=1")
        args = []
        for col, val, op in (("playthrough_id", playthrough_id, "="),
                             ("market_id", market_id, "="),
                             ("good_key", good_key, "="),
                             ("date", start, ">="),
                             ("date", end, "<=")):
            if val is not None:
                q += f" AND {col} {op} ?"
                args.append(val)
        q += " ORDER BY date, market_id, good_index"
        return [dict(r) for r in conn.execute(q, args)]
    finally:
        conn.close()


def route_prices(playthrough_id=None, route_id=None, market_id=None, start=None, end=None, *,
                 data_dir):
    """Route transactions {date, route_id, market_id, good_key, type, amount, price_per_unit}."""
    conn = _connect(data_dir)
    try:
        conn.row_factory = sqlite3.Row
        q = ("SELECT date, route_id, market_id, good_key, type, amount, price_per_unit, "
             "fulfilled_category FROM route_transaction WHERE 1=1")
        args = []
        for col, val, op in (("playthrough_id", playthrough_id, "="),
                             ("route_id", route_id, "="),
                             ("market_id", market_id, "="),
                             ("date", start, ">="),
                             ("date", end, "<=")):
            if val is not None:
                q += f" AND {col} {op} ?"
                args.append(val)
        q += " ORDER BY date, route_id, market_id"
        return [dict(r) for r in conn.execute(q, args)]
    finally:
        conn.close()


def main(argv):
    if len(argv) < 3 or argv[1] != "check":
        print(__doc__)
        return 1
    data_dir = argv[2]
    conn = _connect(data_dir)
    try:
        for t in ("snapshot", "market", "market_good", "route", "route_transaction"):
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"{t}: {n}")
        rows = conn.execute(
            "SELECT date, COUNT(*) FROM market_good GROUP BY date ORDER BY date").fetchall()
        print("按快照:", ", ".join(f"{d}={n}" for d, n in rows))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
