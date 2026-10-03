# -*- coding: utf-8 -*-
"""Parse CK3 ruler-address and title-suffix words from common/flavorization/*.txt: an
entry's block name is the localization key, and the highest-priority entry whose
conditions all match wins. Writes data/flavorization.json (game plus enabled mods,
same-named mod blocks overriding the game's)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm                 # noqa: E402
import localization as L    # noqa: E402

_SCHEMA = 4   # parses the 1.20 `rites` condition (rite) and marks `lessee_*` unsupported
_TABLE = None


def _path(cfg):
    return os.path.join(cfg.get("data_dir", ""), "flavorization.json")


def _strip_comments(text):
    """Strip `#` comments (outside quotes) before parsing: commented-out example entries
    hold `{`/`}` that would throw off the depth counting in localization._top_blocks
    (00_title_holders.txt yields 2400+ spurious top-level blocks otherwise)."""
    out = []
    for line in (text or "").split("\n"):
        q = False
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '"':
                q = not q
            elif ch == "#" and not q:
                break
            i += 1
        out.append(line[:i])
    return "\n".join(out)


def _list_of(items, key):
    """`key = { a b c }` -> ['a','b','c']; a single `key = a` is accepted; missing -> [].
    (L._script_items records `= { … }` as op='block', so the body lives under '_'+key.)"""
    v = items.get("_" + key)
    if v is None:
        v = items.get(key)
    if not isinstance(v, str) or not v.strip():
        return []
    return [x for x in v.replace(",", " ").split() if x]


def _rules_of(items):
    """flavourization_rules sub-block -> {rule: bool}."""
    raw = items.get("_flavourization_rules") or ""
    out = {}
    for k, op, v in L._script_items(raw):
        if op == "block":
            continue
        out[k] = str(v).strip().lower() in ("yes", "true")
    return out


def build_flavorization(cfg):
    """Game plus enabled-mod common/flavorization/*.txt -> entry table."""
    entries = {}
    roots = []
    g = L.game_dir(cfg)
    if g:
        roots.append(g)
    roots += L.enabled_mod_dirs(cfg)
    for root in roots:
        d = os.path.join(root, "common", "flavorization")
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8-sig",
                          errors="replace") as fp:
                    txt = _strip_comments(fp.read())
            except OSError:
                continue
            for key, body in L._top_blocks(txt):
                items = {}
                for a, op, v in L._script_items(body):
                    if op == "block":
                        items["_" + a] = v
                    else:
                        items[a] = v
                typ = (items.get("type") or "").strip()
                if typ not in ("character", "title"):
                    continue          # types such as domicile are not rendered by this project
                tier = (items.get("tier") or "").strip()
                if not tier or tier == "none":
                    continue          # an entry without a tier takes no part in tier-word lookup
                special = (items.get("special") or "holder").strip()
                rules = _rules_of(items)
                # Anything not evaluable is marked unsupported: taking no word beats
                # reusing another ruler's. This covers flag / holding / domicile_type /
                # de_jure_liege / council_position / single-value faith, the `titles`
                # restriction (76 single-title entries in 00_title_holders.txt would
                # otherwise call every European duke a Duke of Brittany), and the
                # `lessee_*` family (only monastery_* uses it, 20_pam_flavorization.txt:382).
                obligation_flags = _list_of(items, "subject_contract_obligation_flags")
                unsupported = bool(
                    items.get("flag") or items.get("domicile_type")
                    or items.get("holding") or items.get("council_position")
                    or items.get("faith")
                    or items.get("_de_jure_liege")
                    or items.get("_lessee_governments")
                    or items.get("_lessee_heritages")
                    or items.get("_lessee_faiths")
                    or items.get("_lessee_rites"))
                # `special = ruler_child` is evaluable: its `governments` list holds no
                # tribal/nomad entry at any tier, so "is there a prince title here" must be
                # asked of the table rather than defaulted. Other `special` values keep
                # their own branches and stay unsupported.
                if special not in ("holder", "", "ruler_child"):
                    unsupported = True
                try:
                    prio = int(float(items.get("priority") or 0))
                except (TypeError, ValueError):
                    prio = 0
                entries[key] = {
                    "key": key, "type": typ, "tier": tier,
                    "gender": (items.get("gender") or "").strip(),
                    "priority": prio, "special": special,
                    "governments": _list_of(items, "governments"),
                    "name_lists": _list_of(items, "name_lists"),
                    "heritages": _list_of(items, "heritages"),
                    "faiths": _list_of(items, "faiths"),
                    "rites": _list_of(items, "rites"),
                    "religions": _list_of(items, "religions"),
                    "titles": _list_of(items, "titles"),
                    "obligation_flags": obligation_flags,
                    "rules": rules,
                    "unsupported": unsupported,
                }
    return {"schema": _SCHEMA, "entries": entries}


def save_flavorization(cfg, data):
    path = _path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False)
    return path


def load_flavorization(cfg=None, force=False):
    """Load the entry table; rebuilt from the game/mod files when missing or forced."""
    cfg = cfg or llm.load_config()
    path = _path(cfg)
    if not force and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fp:
                data = json.load(fp)
            if data.get("schema") == _SCHEMA and data.get("entries"):
                return data
        except Exception:
            pass
    data = build_flavorization(cfg)
    if data.get("entries"):
        save_flavorization(cfg, data)
    return data


def table(cfg=None):
    """Module-level singleton (facts asks for it once per biography piece)."""
    global _TABLE
    if _TABLE is None:
        try:
            _TABLE = load_flavorization(cfg)
        except Exception:
            _TABLE = {"schema": _SCHEMA, "entries": {}}
    return _TABLE


def resolve(kind, tier, gender, *, government="", name_list="", heritage="",
            faith="", religion="", rite="", title_key="", independent=True, top=None,
            obligation_flags=None, cfg=None, special="holder"):
    """Return the winning localization key (block name) or '' under the game's rules.

    Conditions are tried from the highest priority down and all must match; an empty
    governments / name_lists / heritages / faiths / rites / religions list means
    unrestricted, and entries marked unsupported at build time are skipped. `titles` is a
    restricted-title condition (a match only when title_key is among them); `independent`
    drives the only_vassals/only_independent rules; `top` carries the top liege's fields,
    which entries not marked `top_liege = no` are judged against (the game's default).
    `obligation_flags` are the character's decoded contract obligation flags and must
    intersect an entry's own flags; `special` selects the entry class — "holder" by
    default (ruler addresses), "ruler_child" for prince/princess entries, the two classes
    never competing; `rite` is the character's rite_type, and an entry with `rites` cannot
    match when the rite is unknown."""
    fl = table(cfg)
    ents = (fl.get("entries") or {})
    if not ents:
        return ""
    best_key, best_pri, best_rites = "", None, False
    for e in ents.values():
        if e.get("type") != kind or e.get("tier") != tier:
            continue
        if e.get("unsupported"):
            continue
        if (e.get("special") or "holder") != (special or "holder"):
            continue
        tls = e.get("titles") or []
        if tls and title_key not in tls:
            continue
        if e.get("gender") and e["gender"] != gender:
            continue
        prio = e.get("priority") or 0
        rts_e = e.get("rites") or []
        # Word order (game doc `_flavourization.info:143-148`): higher priority wins, an
        # equal priority skips the entry. One deliberate relaxation: a rite-specific entry
        # (one carrying `rites`) beats a religion-generic entry at equal priority. The game
        # gives the Shia and the Islamic theocracy entries the same priority
        # (00_title_holders.txt:1679 and :3142, both 27), so the game's own order is
        # unknowable and the more specific word reads better. Christian words never tie:
        # their `rites` do not match.
        if best_pri is not None:
            if prio < best_pri:
                continue
            if prio == best_pri and not (rts_e and not best_rites):
                continue
        rules = e.get("rules") or {}
        # top_liege defaults to yes: a vassal is judged by the top liege's
        # government/culture unless the entry says `top_liege = no`.
        use_top = bool(top) and rules.get("top_liege", True) is not False
        # `ignore_top_liege_government` (`_flavourization.info:195-202`): when true, every
        # field *except* government still comes from the top liege. Ignoring this rule let
        # administrative words (priority 51/50/29/28) override `duchy_feudal` (27) for
        # feudal vassals, titling them as military-district commands.
        gov_x = (government if (not use_top
                               or rules.get("ignore_top_liege_government"))
                 else (top.get("government") or government))
        nl_x = (top.get("name_list") or name_list) if use_top else name_list
        hs_x = (top.get("heritage") or heritage) if use_top else heritage
        fa_x = (top.get("faith") or faith) if use_top else faith
        rt_x = (top.get("rite") or rite) if use_top else rite
        re_x = (top.get("religion") or religion) if use_top else religion
        govs = e.get("governments") or []
        if govs and gov_x not in govs:
            continue
        nls = e.get("name_lists") or []
        if nls and nl_x not in nls:
            continue
        hs = e.get("heritages") or []
        if hs and hs_x not in hs:
            continue
        fs = e.get("faiths") or []
        if fs and fa_x not in fs:
            continue
        rts = e.get("rites") or []
        if rts and rt_x not in rts:
            continue
        rs = e.get("religions") or []
        if rs and re_x not in rs:
            continue
        if rules.get("only_independent") and not independent:
            continue
        if rules.get("only_vassals") and independent:
            continue
        # Contract-obligation flags: an entry listing flags matches only on an intersection;
        # a character without flags skips such entries.
        want_flags = e.get("obligation_flags") or []
        if want_flags:
            have = set(obligation_flags or [])
            if not have.intersection(want_flags):
                continue
        best_key, best_pri, best_rites = e["key"], prio, bool(rts_e)
    return best_key


# Chinese / celestial word families this project does emit: their name conditions
# (name_lists = name_list_han) are treated as culture-independent, like other celestial and
# administrative titles here, so the culture gate is relaxed for them. Other ruler_child
# entries (guanches, tangut, roman, iberian, iranian, dravidian, southeast_asian) are
# culture-specific native words never emitted here and follow the game's conditions —
# `title_prince_male_guanches` (priority 130) would otherwise let any tribal kingdom-tier
# child through.
_PRINCE_CN_KEYS = frozenset({
    "prince_duchy_chinese", "princess_duchy_chinese",
    "prince_kingdom_feudal_chinese", "princess_kingdom_feudal_chinese",
    "prince_kingdom_celestial_chinese", "princess_kingdom_celestial_chinese",
    "prince_kingdom_celestial_chinese_independent",
    "princess_kingdom_celestial_chinese_independent",
    "prince_empire_chinese", "princess_empire_chinese",
    "prince_empire_celestial_chinese", "princess_empire_celestial_chinese",
    "prince_hegemony_chinese", "princess_hegemony_chinese",
    "prince_male_celestial_chinese", "princess_female_celestial_chinese",
})


def ruler_child_exists(tier, gender, *, government="", name_list="", heritage="",
                       faith="", religion="", rite="", title_key="", independent=True,
                       top=None, obligation_flags=None, cfg=None):
    """Return the prince/princess localization key the game has for (tier x gender x
    government x independent/vassal), or '' when there is none.

    Two deliberate differences from resolve: only `special = ruler_child` entries are
    considered, and the Chinese/celestial families (_PRINCE_CN_KEYS) skip the culture and
    faith conditions, since celestial and administrative titles are treated as
    culture-independent here, while the other culture-specific entries (guanches, tangut,
    roman, iberian, iranian, dravidian, southeast_asian) are judged as the game writes
    them. It exists because `prince`/`princess` governments are exhaustive and hold no
    tribal/nomad entry (00_flavorization.txt:354-400), so tribal and nomadic rulers have no
    such title at any tier and the question must be asked of the table."""
    fl = table(cfg)
    ents = (fl.get("entries") or {})
    if not ents:
        return ""
    best_key, best_pri = "", None
    for e in ents.values():
        if e.get("type") != "character" or e.get("tier") != tier:
            continue
        if (e.get("special") or "holder") != "ruler_child" or e.get("unsupported"):
            continue
        if e.get("gender") and e["gender"] != gender:
            continue
        prio = e.get("priority") or 0
        if best_pri is not None and prio <= best_pri:
            continue
        tls = e.get("titles") or []
        if tls and title_key not in tls:
            continue
        rules = e.get("rules") or {}
        use_top = bool(top) and rules.get("top_liege", True) is not False
        gov_x = (government if (not use_top
                               or rules.get("ignore_top_liege_government"))
                 else (top.get("government") or government))
        govs = e.get("governments") or []
        if govs and gov_x not in govs:
            continue
        if e.get("key") not in _PRINCE_CN_KEYS:
            # culture / faith conditions, except for the Chinese word families (see the docstring)
            nls = e.get("name_lists") or []
            if nls and (top.get("name_list") if use_top else name_list) not in nls:
                continue
            hs = e.get("heritages") or []
            if hs and (top.get("heritage") if use_top else heritage) not in hs:
                continue
            fs = e.get("faiths") or []
            if fs and (top.get("faith") if use_top else faith) not in fs:
                continue
            # `rites` condition (1.20), decided as in resolve; no hit when the rite is unknown
            rts = e.get("rites") or []
            if rts and (top.get("rite") if use_top else rite) not in rts:
                continue
            rs = e.get("religions") or []
            if rs and (top.get("religion") if use_top else religion) not in rs:
                continue
        if rules.get("only_independent") and not independent:
            continue
        if rules.get("only_vassals") and independent:
            continue
        want_flags = e.get("obligation_flags") or []
        if want_flags and not set(obligation_flags or []).intersection(want_flags):
            continue
        best_key, best_pri = e["key"], prio
    return best_key


def is_unconditional(key, cfg=None):
    """Whether the entry has no conditions at all (only type/tier/gender/priority) — a
    generic fallback tier word.

    `duke`/`count`/`king`/`emperor`/`baron`/`hegemon` have every condition field empty and
    are the common exit for any government that fails to match; facts._office_word treats
    such a hit as a miss when the government is unknown, so a generic tier word cannot
    override a culture or government word."""
    e = (table(cfg).get("entries") or {}).get(key) or {}
    if not e:
        return False
    return not any(e.get(k) for k in (
        "governments", "name_lists", "heritages", "faiths", "rites", "religions",
        "titles", "obligation_flags", "rules"))


def coverage(cfg=None):
    """Self-check helper: count entries per (type, tier) and list the covered name_lists,
    heritages and governments."""
    fl = table(cfg)
    out = {}
    nls, hss, govs = set(), set(), set()
    for e in (fl.get("entries") or {}).values():
        out.setdefault((e.get("type"), e.get("tier")), 0)
        out[(e.get("type"), e.get("tier"))] += 1
        nls.update(e.get("name_lists") or [])
        hss.update(e.get("heritages") or [])
        govs.update(e.get("governments") or [])
    return {"counts": {f"{k[0]}/{k[1]}": v for k, v in sorted(out.items())},
            "name_lists": sorted(nls), "heritages": sorted(hss),
            "governments": sorted(govs)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = llm.load_config()
    data = load_flavorization(cfg, force=True)
    print("条目数:", len(data.get("entries") or {}))
    cov = coverage(cfg)
    for k, v in cov["counts"].items():
        print("  %-22s %d" % (k, v))
    print("覆盖 name_lists %d 个 / heritages %d 个 / governments %d 个"
          % (len(cov["name_lists"]), len(cov["heritages"]),
             len(cov["governments"])))
    print("落盘:", _path(cfg))
