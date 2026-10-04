# -*- coding: utf-8 -*-
"""CK3 biography generator: five Record-style articles per player character (life, friend,
enemy, household, politics); prompts carry only the clean Chinese facts facts.py renders."""
import os
import re
from concurrent.futures import ThreadPoolExecutor

import llm
import cache_lib as cl
import facts as F
import style

# ---------------------------------------------------------------------------
# prompt text lives in style.py: RULES, SECTION_TITLES + SECTION_REQ, PROMPTS
# ---------------------------------------------------------------------------

POLITICAL_TYPES = {
    "ascended_throne_memory", "lost_title_memory", "imprisoned",
    "released_from_prison_memory", "escaped_from_prison_memory",
    "became_rivals", "became_grudge",
    "became_nemesis", "stopped_being_rivals", "offensive_war",
    "defensive_war", "war_won", "war_lost", "joined_allys_war",
    "battle_won_memory", "battle_lost_memory",
}


# ---------------------------------------------------------------------------
# protagonist / friend / enemy / household selection
# ---------------------------------------------------------------------------

def _friend_types():
    return {"became_friends", "became_soulmates", "became_blood_brother"}


def _enemy_types():
    return {"became_rivals", "became_grudge", "became_nemesis"}


def _is_dead(cache, cid, as_of=None):
    """True when the cache holds a death record. With as_of passed in, a death dated
    after as_of counts as still alive, so a decade article keeps its contemporaries."""
    d = ((cache.get("characters") or {}).get(str(cid), {}) or {}).get("death") or {}
    if not d:
        return False
    if as_of and d.get("date") and cl.date_key(d["date"]) > cl.date_key(as_of):
        return False
    return True


def _relation_dates(cache, types):
    """{cid: earliest date the protagonist befriended or feuded with them}, from other characters'
    memories and the protagonist's own (whose participants hold only the other id)."""
    pid = cache.get("player_id")
    out = {}
    if pid is None:
        return out

    def add(cid, d):
        try:
            cid = int(cid)
        except (TypeError, ValueError):
            return
        if cid == pid:
            return
        dk = cl.date_key(d or "9999.9.9")
        if cid not in out or dk < cl.date_key(out[cid]):
            out[cid] = d

    for cid, rec in (cache.get("characters") or {}).items():
        for mem in rec.get("memories") or []:
            if mem.get("type") not in types:
                continue
            parts = mem.get("participants") or {}
            if any(isinstance(v, int) and v == pid for v in parts.values()):
                add(cid, mem.get("creation_date"))
    prec = (cache.get("characters") or {}).get(str(pid)) or {}
    for mem in prec.get("memories") or []:
        if mem.get("type") not in types:
            continue
        for v in (mem.get("participants") or {}).values():
            if isinstance(v, int):
                add(v, mem.get("creation_date"))
    return out


def _select_friend(cache, as_of=None):
    """Earliest-befriended living friend/soulmate/blood-brother; kin excluded (household article);
    all dead -> earliest, none -> None (see _pick_friend). as_of drops later friendships."""
    pid = cache.get("player_id")
    if pid is None:
        return None
    fam = _family_ids(cache)
    dates = {c: d for c, d in _relation_dates(cache, _friend_types()).items()
             if c not in fam}
    if as_of:
        dates = {c: d for c, d in dates.items()
                 if cl.date_key(d) <= cl.date_key(as_of)}
    if not dates:
        return None
    alive = {c: d for c, d in dates.items()
             if not _is_dead(cache, c, as_of=as_of)}
    pool = alive or dates
    return min(pool, key=lambda c: cl.date_key(pool[c]))


def _select_fallback_friend(cache, as_of=None):
    """Fallback with no real friend: the living court colleague (court office holder or
    politics-event participant) with the most memories; the prompt notes the substitution."""
    pid = cache.get("player_id")
    if pid is None:
        return None
    fam = _family_ids(cache)
    enemies = _select_enemies(cache)
    candidates = set()
    for h in cache.get("court_positions") or []:
        for p in h.get("positions") or []:
            if isinstance(p.get("employee"), int):
                candidates.add(p["employee"])
    for cid, rec in (cache.get("characters") or {}).items():
        for mem in rec.get("memories") or []:
            if mem.get("type") in POLITICAL_TYPES:
                for v in (mem.get("participants") or {}).values():
                    if isinstance(v, int) and v != pid:
                        candidates.add(v)
    best, best_score = None, -1
    for cid in candidates:
        cid = int(cid)
        if cid == pid or cid in fam or cid in enemies:
            continue
        if _is_dead(cache, cid, as_of=as_of):
            continue
        n = len((cache.get("characters") or {}).get(str(cid), {}).get("memories") or [])
        if n > best_score:
            best, best_score = cid, n
    return best


def _pick_friend(cache, as_of=None):
    """True friend, else the court-colleague fallback. Returns (cid, is_fallback)."""
    f = _select_friend(cache, as_of=as_of)
    if f is not None:
        return f, False
    return _select_fallback_friend(cache, as_of=as_of), True


def _enemy_dates(cache):
    """{cid: earliest feud date with the protagonist} (dead included; see _relation_dates)."""
    return _relation_dates(cache, _enemy_types())


def _select_enemies(cache):
    """Ids of every rival, grudge or nemesis of the protagonist."""
    return set(_enemy_dates(cache))


ENEMY_MIN_DEEDS = 2  # minimum deed score for an enemy candidate (sparse material writes nothing)

# Interaction with the protagonist outranks the subject's own deeds. Tiers: 3 = inflicted on the
# other side or taking his property; 2 = suffered from him or jointly involved; 1 = the relation itself.
_SHARED_HISTORY_WEIGHTS = {
    3: ("successful_murder", "imprisoned_other", "torturer_memory",
        "offensive_war", "war_won", "defensive_war", "war_lost",
        "lost_title_memory", "ascended_throne_memory", "broke_up_lovers",
        "became_grudge", "became_nemesis", "faction_demand"),
    2: ("imprisoned", "tortured_memory", "released_from_prison_memory",
        "escaped_from_prison_memory", "joined_allys_war",
        "battle_won_memory", "battle_lost_memory", "stopped_being_friends",
        "stopped_being_rivals", "saved_from_assault_memory",
        "ignored_assault_memory"),
}
# carnal or forced memories (Carnalitas had_sex_* and had_sex) also score 2
_SHARED_HISTORY_SEX_WEIGHT = 2


def _shared_history_score(cache, cid, as_of=None, since=None):
    """Weighted count of memories in which either side lists the other as a participant; a
    symmetric event leaves one memory on each side, so both are counted. as_of/since clip it."""
    pid = cache.get("player_id")
    if pid is None or cid is None:
        return 0
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return 0
    if cid == pid:
        return 0
    w3 = set(_SHARED_HISTORY_WEIGHTS[3])
    w2 = set(_SHARED_HISTORY_WEIGHTS[2])
    chars = cache.get("characters") or {}
    ak = cl.date_key(as_of) if as_of else None
    sk = cl.date_key(since) if since else None
    score = 0
    for a, b in ((pid, cid), (cid, pid)):
        for m in (chars.get(str(a)) or {}).get("memories") or []:
            parts = m.get("participants") or {}
            if b not in [v for v in parts.values() if isinstance(v, int)]:
                continue
            d = m.get("creation_date")
            if d:
                dk = cl.date_key(d)
                if ak is not None and dk > ak:
                    continue
                if sk is not None and dk < sk:
                    continue
            t = str(m.get("type") or "")
            if t in w3:
                score += 3
            elif t in w2 or t == "had_sex" or t.startswith(F._SEX_MEM_PREFIX):
                score += _SHARED_HISTORY_SEX_WEIGHT
            else:
                score += 1
    return score

# deed types scoring for an enemy candidate: active doing counts, passive background does not.
_ENEMY_DEED_TYPES = {
    "ascended_throne_memory", "lost_title_memory", "successful_murder",
    "offensive_war", "defensive_war", "war_won", "war_lost",
    "joined_allys_war", "battle_won_memory", "battle_lost_memory",
    "married", "grand_wedding_completed_guest", "became_lovers",
    "child_born", "first_born", "twins_born", "became_friends",
    "became_soulmates", "became_blood_brother", "imprisoned_other",
    "hostage_created_hostage", "hostage_created_warden", "torturer_memory",
    "became_acclaimed", "witnessed_a_coronation_memory",
    "held_a_coronation_memory", "passed_provincial_exam_memory",
    "passed_metropolitan_exam_memory", "passed_palace_exam_memory",
    "completed_hajj_memory", "ward_education_completed",
    "completed_rites_of_passage", "completed_adult_education",
    "faith_changed",
}


def _enemy_deeds(cache, cid, as_of=None, since=None):
    """Deed score: counts only _ENEMY_DEED_TYPES memories, clipped by as_of/since."""
    rec = (cache.get("characters") or {}).get(str(cid)) or {}
    n = 0
    for mem in rec.get("memories") or []:
        if mem.get("type") not in _ENEMY_DEED_TYPES:
            continue
        d = mem.get("creation_date")
        if as_of and d and cl.date_key(d) > cl.date_key(as_of):
            continue
        if since and d and cl.date_key(d) < cl.date_key(since):
            continue
        n += 1
    return n


def _enemy_has_cause(facts, cid, rel_date):
    """True when the feud has a program-supplied cause (facts.relation_reasons, facts.relation_cause_lines);
    without one the candidate leaves the pool, so the model cannot invent a cause from a bare date."""
    gi = facts.get("_facts") if isinstance(facts, dict) else None
    if gi is None:
        return True          # no fact layer (cache-only call): no such gate
    try:
        if gi.relation_reasons(int(cid), ("rival", "grudge", "nemesis")):
            return True
    except Exception:
        pass
    try:
        if rel_date and F.relation_cause_lines(gi, int(cid), rel_date):
            return True
    except Exception:
        pass
    return False


def _select_primary_enemy(cache, as_of=None, since=None, allow=None):
    """Primary enemy: the relevant feud (alive past as_of, or active in [since, as_of]) with the
    highest deed score. allow(cid, rel_date) is an optional hard gate; since = decade window bound."""
    dates = _enemy_dates(cache)
    if allow is not None:
        dates = {c: d for c, d in dates.items() if allow(c, d)}
    if as_of:
        dates = {c: d for c, d in dates.items()
                 if cl.date_key(d) <= cl.date_key(as_of)}
    if not dates:
        return None
    relevant = {c: d for c, d in dates.items()
                if not _is_dead(cache, c, as_of=as_of)
                or _enemy_deeds(cache, c, as_of=as_of, since=since) > 0}
    pool = relevant or dates
    rich = {c: d for c, d in pool.items()
            if _enemy_deeds(cache, c, as_of=as_of) >= ENEMY_MIN_DEEDS}
    pool = rich or pool

    # soft criterion: shared history outranks the candidate's own deeds; zero shared can still win.
    shared = {c: _shared_history_score(cache, c, as_of=as_of) for c in pool}
    shared_dec = {c: _shared_history_score(cache, c, as_of=as_of, since=since)
                  for c in pool}

    def _key(c):
        return (-shared.get(c, 0), -shared_dec.get(c, 0),
                -_enemy_deeds(cache, c, as_of=as_of),
                1 if _is_dead(cache, c, as_of=as_of) else 0,
                cl.date_key(pool[c]))

    return min(pool, key=_key)


def _enemy_for_facts(facts, cache):
    """Enemy pick shared by the article title and body, so the two cannot disagree; decade
    articles pass the window lower bound since, lifetime ones do not (_enemy_has_cause gates)."""
    as_of = facts.get("as_of")
    since = None
    if as_of and facts.get("decade"):
        try:
            since = f"{int(str(as_of).split('.')[0]) - 10}.1.1"
        except Exception:
            since = None
    allow = None
    if facts.get("_facts") is not None:
        allow = lambda c, d: _enemy_has_cause(facts, c, d)   # noqa: E731
    return _select_primary_enemy(cache, as_of=as_of, since=since, allow=allow)


def _family_ids(cache):
    """Family ids (spouses/former spouses/children/siblings); kin belong to the household article.
    Spouse side reads ever_spouses, which survives a death record clearing the older keys."""
    pid = cache.get("player_id")
    if pid is None:
        return set()
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    fam = rec.get("family") or {}
    out = set()
    for key in ("primary_spouse", "spouse", "former_spouses", "ever_spouses",
                "concubine", "former_concubines", "child", "siblings"):
        for x in fam.get(key) or []:
            if isinstance(x, int):
                out.add(int(x))
    return out


def _sec_key(section):
    """Section key; a missing key means the lead section."""
    return (section or {}).get("key") or "lead"


def _murder_link_line(facts, key=None, section_key=None):
    """Index line replacing the murder module this section excludes (the assassins article
    carries it whole). Empty unless (key, section_key) is in F.MODULE_EXCLUDE and kills exist."""
    if key is not None and (key, section_key) not in F.MODULE_EXCLUDE:
        return ""
    if not _has_assassins(facts):
        return ""
    n = F.murder_module_count(facts.get("timeline") or [])
    if not n:
        return ""
    return f"另有谋杀{n}人，详见《刺客列传·刀下诸魂》。"


def _has_assassins(facts):
    """Whether this run generates the assassins article: at least one kill in the window."""
    return len(facts.get("killed") or []) >= 1


def _family_ids_by_kind(cache, kind):
    """Household split: kind='spouse' -> wives and concubines, kind='child' -> children and
    siblings. Same ever_spouses source as _family_ids."""
    pid = cache.get("player_id")
    if pid is None:
        return set()
    rec = (cache.get("characters") or {}).get(str(pid)) or {}
    fam = rec.get("family") or {}
    keys = (("primary_spouse", "spouse", "former_spouses", "ever_spouses",
             "concubine", "former_concubines") if kind == "spouse"
            else ("child", "siblings"))
    return {int(x) for k in keys for x in (fam.get(k) or [])
            if isinstance(x, int) or str(x).isdigit()}


def _consort_affair_lines(facts, cache):
    """Per-lover block for a spouse: _profile_lines plus the arc in facts.consort_affairs."""
    entries = facts.get("consort_affairs") or []
    if not entries:
        return []
    grouped = {}
    for e in entries:
        grouped.setdefault(e.get("spouse_label") or "", []).append(e)
    out = []
    for slabel, items in grouped.items():
        # plain-sentence header: the style checker rejects the "noun (noun)" parenthetical form
        out.append(f"{slabel}情事脉络：")
        for e in items:
            pid = e.get("partner")
            if pid is not None:
                for x in _profile_lines(facts, pid, with_real_parentage=True):
                    out.append("　" + x)
            arc = e.get("arc") or ""
            if arc:
                out.append(f"　与{slabel}之情：{arc}。")
        out.append("")
    while out and not out[-1]:
        out.pop()
    return out


def _split_span(items, part, total=2):
    """Split an ordered list two ways: part 0 = lead half, part 1 = the rest."""
    n = len(items or [])
    if n == 0:
        return []
    if total <= 1:
        return list(items)
    cut = (n + total - 1) // total
    return list(items)[:cut] if part == 0 else list(items)[cut:]


# attention anchors ("Lost in the Middle"): the most writable dates, placed before the closing requirements.
_ANCHOR_MODULES = ("起家发迹", "失位让土", "开战兴兵", "战和胜负",
                   "囚禁入狱", "获释出狱", "拥戴加冕", "婚配联姻",
                   "丧偶之痛", "夭折", "谋害人命",
                   # coronation gains and clashes: same tier as the accession-coronation module
                   "加冕索求", "加冕对抗")


def _subject_events(facts, key, events, subject=None):
    """Friend/enemy articles keep only events naming the subject (protagonist-related events
    merged two people in one sentence); an unknown subject name drops the block."""
    if key not in ("friend", "enemy") or subject is None:
        return events
    name = ((facts.get("characters") or {}).get(str(subject)) or {}).get("name") or ""
    if not name:
        return []
    return [e for e in events if name in (e.get("text") or "")]


def _key_events_block(facts, key, section, limit=4, subject=None):
    """Key-events card: up to limit slice events naming the protagonist or from a high-drama
    module, date-ascending; friend/enemy sections filter by subject first (see _subject_events)."""
    evs = F.slice_events(facts.get("timeline") or [], key, _sec_key(section),
                         exclude=_has_assassins(facts))
    evs = _subject_events(facts, key, evs, subject)
    if not evs:
        return ""
    pname = (facts.get("protagonist") or {}).get("name") or ""

    def rank(e):
        s = 0
        if pname and pname in (e.get("text") or ""):
            s -= 2
        if (e.get("module") or "") in _ANCHOR_MODULES:
            s -= 1
        return s

    picked = sorted(evs, key=rank)[:limit]
    picked.sort(key=lambda e: e.get("date") or "")
    return "【本板块大事】\n" + "\n".join(e["text"] for e in picked)


_LEAD_QUOTE_RE = re.compile(r"[「『“\"]([^」』”\"]{1,40})[」』”\"]")
_LEAD_LATIN_RE = re.compile(r"[A-Za-z]")
_LEAD_SENT_SPLIT_RE = re.compile(r"(?<=[。！？])")


def _sanitize_lead_digest(digest, facts_text=""):
    """Drop whole sentences whose quoted fragment contains Latin letters and does not occur in
    this request's fact text: hallucinated names vanish, real Latin names survive. Idempotent."""
    t = (digest or "").strip()
    if not t:
        return t
    facts = facts_text or ""
    sents = [s for s in _LEAD_SENT_SPLIT_RE.split(t) if s]
    kept = []
    for s in sents:
        drop = False
        for m in _LEAD_QUOTE_RE.finditer(s):
            frag = (m.group(1) or "").strip()
            if not frag or not _LEAD_LATIN_RE.search(frag):
                continue
            if frag not in facts:
                drop = True
                break
        if not drop:
            kept.append(s)
    return "".join(kept).strip()


def _digest_head(t, limit):
    """Head of the digest: whole sentences up to limit; a first sentence longer than limit is
    still returned whole rather than cut mid-word."""
    out = ""
    for s in _LEAD_SENT_SPLIT_RE.split(t or ""):
        if not s:
            continue
        if out and len(out) + len(s) > limit:
            break
        out += s
    return out.strip()


def _digest_tail(t, tail):
    """Tail of the digest: whole sentences from the end, up to tail characters."""
    out = ""
    for s in reversed([s for s in _LEAD_SENT_SPLIT_RE.split(t or "") if s]):
        if out and len(out) + len(s) > tail:
            break
        out = s + out
    return out.strip()


def _lead_digest(text, limit=260, tail=180, facts_text=""):
    """Lead digest head + ellipsis + tail, so mid-article requests stop re-sending the whole lead
    and a prefix cut keeps an event's outcome; sanitized, both ends sentence-aligned."""
    t = re.sub(r"[#*_>`~\-]", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    # sanitize before cutting: a quote split by the ellipsis would slip a hallucinated name past the
    # sanitizer, so it would enter the chronicle request.
    t = _sanitize_lead_digest(t, facts_text)
    if len(t) <= limit + tail:
        return t
    head = _digest_head(t, limit)
    tail_t = _digest_tail(t, tail)
    # head+tail already span the text: return it whole, no overlap and no ellipsis
    if not head or not tail_t or len(head) + len(tail_t) + 3 >= len(t):
        return t
    return head + "……" + tail_t


def _relation_reasons(facts, cache, cid, types):
    """Clean Chinese sentences telling why the two are friends or feuds: the protagonist's own
    memories first, the other side's as a fallback, deduplicated."""
    pid = cache.get("player_id")
    out = []
    seen = set()
    fi = facts.get("_facts")  # Facts instance (renders memory sentences)

    def add(s):
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    prec = (cache.get("characters") or {}).get(str(pid)) or {}
    for mem in prec.get("memories") or []:
        if mem.get("type") not in types:
            continue
        parts = mem.get("participants") or {}
        if any(isinstance(v, int) and v == cid for v in parts.values()):
            add(F._mem_sentence(fi, pid, mem))
    crec = (cache.get("characters") or {}).get(str(cid)) or {}
    for mem in crec.get("memories") or []:
        if mem.get("type") not in types:
            continue
        parts = mem.get("participants") or {}
        if any(isinstance(v, int) and v == pid for v in parts.values()):
            add(F._mem_sentence(fi, cid, mem))
    return out


# ---------------------------------------------------------------------------
# fact-block rendering (clean Chinese output only)
# ---------------------------------------------------------------------------

def _feud_sentences(facts, cache, cid, reasons, rel_date):
    """Game-cause memory sentences: "at <place>, <cause>, so <enemy> bears a grudge against him, <date>";
    the place is facts.station_place of whichever side the cause names first. [] when there is no cause."""
    gi = (facts or {}).get("_facts")
    pid = cache.get("player_id")
    if gi is None or pid is None or not reasons:
        return []
    plabels = [((cache.get("characters") or {}).get(str(pid)) or {}).get("name_full"),
               ((cache.get("characters") or {}).get(str(pid)) or {}).get("name_zh"),
               gi.person_label(pid, date=rel_date, style="brief"),
               gi.name_with_regnal(pid, rel_date) or "",
               (facts.get("protagonist") or {}).get("name") or ""]
    elabels = [((cache.get("characters") or {}).get(str(cid)) or {}).get("name_full"),
               ((cache.get("characters") or {}).get(str(cid)) or {}).get("name_zh"),
               gi.person_label(cid, date=rel_date, style="brief"),
               gi.name_with_regnal(cid, rel_date) or "",
               ((facts.get("characters") or {}).get(str(cid)) or {}).get("name") or ""]
    plabels = [x for x in plabels if x]
    elabels = [x for x in elabels if x]
    elabel = elabels[0] if elabels else ""
    if not elabel:
        return []
    pfemale = bool(((cache.get("characters") or {}).get(str(pid)) or {}).get("female"))
    date_z = gi.date(rel_date) if rel_date else ""

    def _pos(text, labels):
        best = None
        for lb in labels:
            i = text.find(lb)
            if i != -1 and (best is None or i < best):
                best = i
        return best

    out = []
    for s in reasons:
        body = (s or "").strip().rstrip("。")
        if not body:
            continue
        pp = _pos(body, plabels)
        ep = _pos(body, elabels)
        place = ""
        if pp is not None and (ep is None or pp <= ep):
            place = gi.station_place(pid, rel_date) or ""
        tail = f"{elabel}由此与{'她' if pfemale else '他'}结怨"
        if date_z:
            tail += f"，{date_z}"
        out.append(f"{'在' + place + '，' if place else ''}{body}，{tail}。")
    return out


def _house_text(facts, p=None):
    """House label of a character, read from facts.house_label (or the profile's cached copy);
    otherwise joins house and branch, directly after a 氏 clan suffix or after a comma."""
    p = p or {}
    lab = p.get("house_label") or (facts or {}).get("house_label") or ""
    if lab:
        return lab
    h = (facts or {}).get("house") or p.get("house") or ""
    b = (facts or {}).get("house_branch") or p.get("house_branch") or ""
    if h and b:
        if h.endswith("氏"):
            return f"{h[:-1]}{b}"
        return f"{h}，{b}"
    return h


def _num1(v, nd=1):
    """Number → one-decimal short string with trailing zeros trimmed; same format the
    protagonist profile uses for treasury gold and monthly income."""
    try:
        return f"{float(v):.{nd}f}".rstrip("0").rstrip(".")
    except Exception:
        return ""


def _profile_lines(facts, cid=None, with_real_parentage=False,
                   with_private_chains=False, scope=None, with_death=True,
                   with_court=True):
    """Profile of the protagonist (cid=None) or of character cid → one prose line per fact class;
    scope = kin register; with_real_parentage/with_private_chains add lineage facts; with_court/with_death suppress court and death data."""
    if cid is None:
        p = facts["protagonist"]
    else:
        p = (facts["characters"].get(str(cid)) or {})
    lines = []
    name = p.get("name") or p.get("name_zh") or ""
    # head comes from the facts-side person_label, re-read at as_of (a cached label reflects the last government form).
    _fi = facts.get("_facts")
    _anchor = facts.get("as_of")
    _tid = cid if cid is not None else facts.get("player_id")
    head = ""
    if _fi is not None and cid is not None:
        head = _fi.person_label(cid, date=_anchor, style="brief") or ""
    head = head or p.get("label") or name
    if not p.get("label"):
        if p.get("office"):
            head = f"{p['office']}{name}"
        elif p.get("prince"):
            head = f"{p['prince']}{name}"
    if scope is not None and _fi is not None and _tid is not None:
        _tagged = _fi.kin_attrib_label(_tid, date=_anchor, style="brief",
                                       scope=scope, base=head)
        if _tagged:
            head = _tagged
    # the profile's kin line already names father, mother, children and spouse, so those relatives claim
    # no further attributive; seed only when the profile is the board subject, not a relative's own profile.
    if scope is not None and _fi is not None and _tid is not None \
            and _tid == scope.subject:
        scope.seed(p.get("kin_ids"), _fi)
    bits = []
    h = _house_text(None, p)
    # the subject's own name line omits the house word, which the shared prefix already carries
    _dup_house = bool(cid is None and p.get("house_label"))
    if h and not _dup_house and (p.get("house_branch") or h not in name):
        bits.append(h)
    if p.get("culture"):
        bits.append(p["culture"])
    if p.get("faith"):
        bits.append(f"信{p['faith']}")
    if p.get("birth"):
        bits.append(f"生于{p['birth']}")
    if p.get("court_service"):
        bits.append(p["court_service"])
    if p.get("motto"):
        bits.append(f"家训「{p['motto']}」")
    # rank and blood relation from facts.consort_of_line, else names sharing a house and a generation character read as siblings
    if cid is not None and p.get("consort_rel"):
        bits.append(p["consort_rel"])
    lines.append(f"{head}，{'，'.join(bits)}。" if bits else f"{head}。")
    # co-ruler identity (game co_ruler rule), own sentence
    if p.get("co_ruler"):
        lines.append(p["co_ruler"])
    if p.get("culture_history"):
        lines.append(p["culture_history"])
    for ln in (p.get("house_history") or []):
        if ln:
            lines.append(ln)
    for ln in (p.get("succession") or []):
        if not ln:
            continue
        # with_death=False drops the successor line too: it carries the protagonist's death date
        if not with_death and str(ln).startswith("后任："):
            continue
        lines.append(ln)
    if p.get("language_line"):
        lines.append(p["language_line"])
    if p.get("traits"):
        lines.append(f"为人：{p['traits']}。")
    if p.get("trait_history"):
        lines.append(f"特质履历：{p['trait_history']}。")
    # conversion steps: the name line carries only the current faith
    if p.get("faith_history"):
        lines.append(f"信仰履历：{p['faith_history']}。")
    # birth name once, for those renamed on accession: every display face uses the new name.
    if p.get("birth_name"):
        lines.append(f"本名：{p['birth_name']}。")
    # personal tenets: sequence assembled in facts (facts.personal_tenet_lines), landed rulers only
    if p.get("personal_tenets"):
        lines.append(f"个人教义：{p['personal_tenets']}")
    if p.get("landless"):
        camp_bits = []
        if p.get("camp_name"):
            camp_bits.append(f"营{p['camp_name']}")
        if p.get("camp_laws"):
            camp_bits.append(f"营规{p['camp_laws']}")
        if p.get("camp_strength"):
            camp_bits.append(f"营力{p['camp_strength']}")
        if p.get("camp_county"):
            loc = [f"现驻{p['camp_county']}"]
            if p.get("camp_county_holder"):
                loc.append(f"{p['camp_county_holder']}执掌")
            if p.get("camp_liege_chain"):
                loc.append(f"其上为{p['camp_liege_chain']}")
            if p.get("camp_top_liege"):
                loc.append(f"最高领主为{p['camp_top_liege']}")
            camp_bits.append("，".join(loc))
        if camp_bits:
            lines.append("，".join(camp_bits) + "。")
        elif p.get("government"):
            lines.append(f"以{p['government']}之身行事。")
    else:
        gov = ""
        if p.get("government"):
            gov = f"政体{p['government']}"
        if p.get("ruler_since"):
            gov = (gov + "，" if gov else "") + f"{p['ruler_since']}起执掌一方"
        if p.get("domain"):
            cap = f"，治所{p['capital']}" if p.get("capital") else ""
            gov = (gov + "，" if gov else "") + f"直辖{p.get('domain_count', '')}地：{p['domain']}{cap}"
        if p.get("vassal_count") is not None and with_court:
            gov = (gov + "，" if gov else "") + f"封臣{p['vassal_count']}人"
        # provisions arrive as a band word from facts.provisions_band (facts gates by domicile, drops zeros).
        if p.get("provisions_word"):
            gov = (gov + "，" if gov else "") + p["provisions_word"]
        if p.get("council") and with_court:
            gov = (gov + "，" if gov else "") + p["council"]
        if gov:
            lines.append(gov + "。")
        # estate identity, kept apart from the camp line (a camp wanders, an estate is rooted)
        if p.get("estate_name"):
            # holder named in a main clause, never a parenthetical appositive (project rule)
            _place = f"，庄园在{p['estate_place']}" if p.get("estate_place") else ""
            _since = f"{p['estate_since']}立" if p.get("estate_since") else ""
            if p.get("estate_holder"):
                lines.append(f"{_since}{p.get('estate_word') or '家族庄园'}"
                             f"「{p['estate_name']}」，主人称{p['estate_holder']}"
                             f"{_place}。")
            else:
                lines.append(f"{_since}{p.get('estate_word') or '家族庄园'}"
                             f"「{p['estate_name']}」{_place}。")
    # p.court_positions is a roster of OTHER people serving under the protagonist; the heading must not read
    # as the protagonist's own office history, so camp and court keep separate headings.
    if p.get("court_positions") and with_court:
        if cid is None and p.get("landless"):
            lines.append(f"营中僚属任职：{p['court_positions']}。")
        elif cid is None:
            lines.append(f"廷中僚属任职：{p['court_positions']}。")
        else:
            lines.append(f"帐下僚属任职：{p['court_positions']}。")
    if p.get("court_position"):
        lines.append(f"在主角处任{p['court_position']}。")
    # court office granted to the protagonist himself, opposite the roster above (cid is None)
    if cid is None and p.get("court_office") and with_court:
        lines.append(f"朝廷职位：{p['court_office']}。")
    # spouse labels follow the profile subject's sex
    fem = bool(p.get("female"))
    spouse_lbl = "夫婿" if fem else "妻室"
    former_lbl = "前夫" if fem else "前妻"
    conc_lbl = "男宠" if fem else "妾"
    former_conc_lbl = "前男宠" if fem else "前妾"
    fam_bits = []
    if p.get("spouses"):
        fam_bits.append(f"{spouse_lbl}{p['spouses']}")
    if p.get("former_spouses"):
        fam_bits.append(f"{former_lbl}{p['former_spouses']}")
    if p.get("concubines"):
        fam_bits.append(f"{conc_lbl}{p['concubines']}")
    if p.get("former_concubines"):
        fam_bits.append(f"{former_conc_lbl}{p['former_concubines']}")
    # children split by sex: a mixed list makes the model promote daughters to sons
    if p.get("children_sons"):
        fam_bits.append(f"子{p['children_sons']}")
    if p.get("children_daughters"):
        fam_bits.append(f"女{p['children_daughters']}")
    if p.get("children") and not (p.get("children_sons")
                                  or p.get("children_daughters")):
        fam_bits.append(f"子女{p['children']}")
    if fam_bits:
        lines.append("，".join(fam_bits) + "。")
    # the spouse's children by another parent: own sentence, household article only (facts.wife_other_children_line)
    if cid is None and p.get("wife_other_children") and with_real_parentage:
        lines.append(p["wife_other_children"])
    # speech relation: intelligibility or interpreter need decided in facts; the model copies it
    if p.get("language_relation"):
        lines.append(p["language_relation"])
    if p.get("language_relations"):
        lines.extend(p["language_relations"])
    elif p.get("language_bridge"):
        lines.append(p["language_bridge"])
    kin_bits = []
    if p.get("father"):
        kin_bits.append(f"父{p['father']}")
    if p.get("mother"):
        kin_bits.append(f"母{p['mother']}")
    if with_real_parentage and p.get("real_father") \
            and p.get("real_father") != p.get("father"):
        kin_bits.append(f"实父{p['real_father']}")
    # per-person profiles omit siblings; the protagonist's own profile keeps the line
    if cid is None and p.get("siblings"):
        kin_bits.append(f"兄弟姊妹{p['siblings']}")
    if kin_bits:
        lines.append("，".join(kin_bits) + "。")
    # barony-level places, same source as the assassin article's victim_place; with_death=False drops the place
    _bp = p.get("birth_place") or ""
    _dp = (p.get("death_place") or "") if with_death else ""
    # a protagonist-killer's death sentence already ends with the place (facts._death_sentence_body)
    if _dp and _dp in (p.get("death") or ""):
        _dp = ""
    if _bp or _dp:
        _place_bits = []
        if _bp:
            _place_bits.append(f"生于{_bp}")
        if _dp:
            _place_bits.append(f"死于{_dp}")
        lines.append("；".join(_place_bits) + "。")
    # birth mother's standing (not the child's origin), inner-household articles only, as its own sentence
    if with_real_parentage and p.get("mother_note"):
        lines.append(p["mother_note"])
    if p.get("clan_line"):
        lines.append(p["clan_line"])
    if p.get("government_change"):
        lines.append(p["government_change"])
    # title history: the colon keeps the years from running into the label
    if p.get("titles_held"):
        lines.append(f"历任：{p['titles_held']}。")
    # seat-clearing note: predecessors who died by the protagonist's hand; inner-household articles only
    if with_real_parentage and p.get("seat_note"):
        lines.append(p["seat_note"])
    if p.get("dynastic_cycle"):
        lines.append(p["dynastic_cycle"] + "。")
    # a status whose text starts with a year merges with the "now" prefix into a prose sentence
    if p.get("status"):
        st = p["status"]
        lines.append(("现" + st) if st.startswith("年") else f"现状：{st}")
    # a death on the road folds departure/origin/destination/purpose into one sentence (transit_death_clause)
    if p.get("death") and with_death:
        lines.append(p["death"])
    # lineage-revealing dramatic facts enter the internal tier only
    df = list(p.get("dramatic_facts") or [])
    if with_private_chains:
        df += [x for x in (p.get("dramatic_facts_private") or []) if x not in df]
    if df:
        lines.append("戏剧性事件：" + "；".join(
            str(x).rstrip("。") for x in df) + "。")
    return lines


def _subject_facts(facts, cid, scope=None):
    """Profile lines plus events for one character (friend/foe), public tier: no real father.
    With scope passed, this profile's lineage line pre-claims the board's kin slots (KinScope.seed)."""
    p = facts["characters"].get(str(cid)) or {}
    lines = _profile_lines(facts, cid, scope=scope)
    events = p.get("events") or []
    return lines, events


def _timeline_texts(facts, names=None, types=None):
    """Timeline texts filtered by person name or event type (ids are never included)."""
    out = []
    for e in facts["timeline"]:
        if types and e["type"] not in types:
            continue
        if names and not any(n and n in e["text"] for n in names):
            continue
        out.append(e["text"])
    return out


# Natural paragraphing of the six year-list fact blocks (sends only; the appendix table is rendered
# by `_appendix_text`): header lines stay alone, event lines group by ≤4 lines and a ≤5-year span,
# joined on a semicolon with the date first; lines are sanitized before grouping.
_PARAGRAPH_BLOCKS = ("大事年表", "相关年表", "朝局动态", "传主行迹",
                     "本板块大事", "家族恩怨")
_PARA_MAX_LINES = 4
_PARA_MAX_YEAR_GAP = 5
_PARA_EVENT_RE = re.compile(r"^\s*(\d{3,4})年")


def _paragraphize_fact_lines(lines):
    """Year-list block lines → paragraphs (event lines grouped, headers left alone).
    Returns a line list, with an empty string between paragraphs."""
    out, buf, last_year, first = [], [], None, True
    _EV = _PARA_EVENT_RE

    def _flush():
        nonlocal buf, last_year
        if buf:
            if not first_flag[0]:
                out.append("")
            seg = []
            for ln in buf:
                t = ln.strip()
                seg.append(t.rstrip("。"))
            out.append("；".join(seg) + "。")
            first_flag[0] = False
        buf, last_year = [], None

    first_flag = [True]
    for ln in lines:
        m = _EV.match(ln or "")
        if not m:
            _flush()
            if (ln or "").strip():
                if not first_flag[0]:
                    out.append("")
                out.append((ln or "").rstrip())
                first_flag[0] = False
            continue
        y = int(m.group(1))
        if buf and (len(buf) >= _PARA_MAX_LINES
                    or (last_year is not None and abs(y - last_year) > _PARA_MAX_YEAR_GAP)):
            _flush()
        buf.append(ln)
        last_year = y
    _flush()
    return out


def _render_block(title, lines):
    """Fact block → text, non-empty lines only, sanitized on the way out (a bare key drops the
    line and audits it); year-list blocks are paragraphized by `_paragraphize_fact_lines`."""
    body = [x for x in lines if x]
    if not body:
        return ""
    if title in _PARAGRAPH_BLOCKS:
        safe = [F.sanitize_fact_text(x, where=title) for x in body]
        safe = [x for x in safe if x]
        if safe:
            return F.sanitize_fact_text(
                f"{title}\n" + "\n".join(_paragraphize_fact_lines(safe)),
                where=title)
    return F.sanitize_fact_text(f"{title}\n" + "\n".join(body), where=title)


def _set_block(blocks, key, text):
    """Set the block key only when there is material: placeholder strings ("no record of
    X") would enter the prompt, cost tokens and get copied into the article."""
    if text:
        blocks[key] = text


# Assassin article scope: a victim is named with his office, plus kin and marriage/love memories only;
# his other life events (accession, war, exams) stay out.
_MARRIAGE_TYPES = {
    "married", "grand_wedding_completed_guest", "broke_up_lovers",
    "became_lovers", "had_sex", "spouse_died", "divorced",
}
# Legacy station annotations inside a death sentence (protagonist's whereabouts; victim's place of
# death) are stripped first, since the archive lines render them on their own; all three historic forms count.
_STATION_RE = re.compile(r"(?:（(?:时主角驻|死于)[^）]*）|，死于[^，。；]*)")


def _strip_station(s):
    return _STATION_RE.sub("", s or "")


def _kin_tag(facts, scope, cid, base, date=None):
    """Adds a kin attributive to the title base, first appearance on this board only; base comes
    from the caller (a victim's title is dated at his death, never recomputed at as_of)."""
    if scope is None or cid is None or not base:
        return base
    fi = facts.get("_facts")
    if fi is None:
        return base
    return fi.kin_attrib_label(cid, date=date, style="brief", scope=scope,
                               base=base) or base


def _assassin_lead_line(k, facts=None, scope=None):
    """One roster line of the assassin article's opening (victim: title, uprising, death); blood
    relatives share a line, an uprising leader carries his home prefecture, first mention gets a kin attributive."""
    nm = k.get("name") or ""
    off = k.get("office") or ""
    disp = k.get("label") or (f"{off}{nm}" if off else nm)
    disp = _kin_tag(facts, scope, k.get("id"), disp)
    db = k.get("death") or ""
    for _p in (disp, nm):
        if _p and db.startswith(_p + "死于"):
            db = "死于" + db[len(_p) + 2:]  # drop the "title + died at" prefix
            break
    db = _strip_station(db)  # the compressed opening roster carries no station annotation
    base = (k.get("uprising") or {}).get("base") or ""
    if base:
        db = f"{base}起事；{db}" if db else f"{base}起事。"
    grp = list(k.get("group") or [])
    if grp:
        disps = [disp] + [g.get("label") or g.get("name") or "" for g in grp]
        disps = [d for d in disps if d]
        note = k.get("kin_note") or ""
        tail = "；".join(x for x in (note, db) if x)
        return f"死者：{'、'.join(disps)}，{tail}" if tail \
            else f"死者：{'、'.join(disps)}"
    return f"死者：{disp}，{db}" if db and not F.is_unknown(db) \
        else f"死者：{disp}"


def _assassin_kill_lines(facts, cache, k, scope=None):
    """Archive lines for one victim (or a kin group): office + name, birth/death, kin, marriage;
    returns 死者：… entries. Grouped kin share a line, and the first mention carries a kin tag."""
    lines = []
    grp = list(k.get("group") or [])
    nm = k["name"]
    off = k.get("office") or ""
    disp = k.get("label") or (f"{off}{nm}" if off else nm)
    disp = _kin_tag(facts, scope, k.get("id"), disp)
    db = k.get("death") or ""
    for _p in (disp, nm):
        if db.startswith(_p + "死于"):
            db = "死于" + db[len(_p) + 2:]
            break
    db = _strip_station(db)  # the place of death is rendered on its own line
    if grp:
        disps = [disp] + [g.get("label") or g.get("name") or "" for g in grp]
        disps = [d for d in disps if d]
        note = k.get("kin_note") or ""
        tail = "；".join(x for x in (note, db) if x)
        lines.append(f"死者：{'、'.join(disps)}，{tail}" if tail
                     else f"死者：{'、'.join(disps)}")
    elif db and not F.is_unknown(db):
        bd = k.get("birth") or ""
        head = f"，生于{bd}，" if bd else "，"
        lines.append(f"死者：{disp}{head}{db}")
    elif k.get("birth"):
        lines.append(f"死者：{disp}，生于{k.get('birth')}")
    else:
        lines.append(f"死者：{disp}")
    # a kill has no scene of its own: anchor on the victim's last known barony, omitted when absent
    for e in [k] + grp:
        vp = (e.get("victim_place") or "").strip()
        if vp:
            lines.append(f"{e.get('name') or ''}死于{vp}。")
    # an uprising's true place (capital → prefecture) on its own line, else the dead move home
    for e in [k] + grp:
        ul = (e.get("uprising_line") or "").strip()
        if ul:
            lines.append(ul)
    # kin from the cache's family records; grouped kin share both parents, spouses are per person
    def _fam_of(e):
        return ((cache.get("characters") or {}).get(str(e.get("id"))) or {}) \
            .get("family") or {}

    def _fids(e, key):
        out = set()
        for x in (_fam_of(e).get(key) or []):
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                continue
        return out

    # kin-line wording: the spouse slot follows the deceased's sex, father/mother carry a birth year and a
    # 子/女 slot
    _fi = facts.get("_facts")

    def _gword(subject, other, kind):
        if _fi is not None:
            return _fi.kin_word_gendered(subject, other, kind)
        return {"spouse": "妻", "former": "前妻",
                "concubine": "妾", "f_concubine": "前妾"}.get(kind, "")

    def _byear(cid):
        """Birth year as int, or None — cache first, melt as fallback."""
        rec = (cache.get("characters") or {}).get(str(cid)) or {}
        b = rec.get("birth")
        if not b and _fi is not None:
            b = (getattr(_fi, "_chars", {}) or {}).get(str(cid), {}).get("birth")
        try:
            return int(str(b).split(".")[0])
        except (TypeError, ValueError):
            return None

    def _with_year(cid, name):
        """Father/mother with birth year, written as prose — a `(born 787)` gloss would
        trip verify_fast's noun-plus-parenthetical appositive ban. No year → name alone."""
        y = _byear(cid)
        return f"{name}，{y}年生" if y else name

    bits = []
    seen_bits = set()
    if grp:
        for key, label in (("father", "父"), ("mother", "母")):
            sets = [s for s in (_fids(e, key) for e in [k] + grp) if s]
            common = set.intersection(*sets) if sets else set()
            for x in sorted(common):
                bits.append(f"{label}{_with_year(x, _kin_or(facts, cache, x))}")
        for e in [k] + grp:
            _seen_sp = set()      # one relationship word per spouse (see single-subject branch)
            for key, kind in (("primary_spouse", "spouse"), ("spouse", "spouse"),
                              ("former_spouses", "former"),
                              ("concubine", "concubine")):
                for x in (_fam_of(e).get(key) or []):
                    try:
                        x = int(x)
                    except (TypeError, ValueError):
                        continue
                    if x in _seen_sp:
                        continue
                    _seen_sp.add(x)
                    b = f"{e.get('name')}之{_gword(e.get('id'), x, kind)}" \
                        f"{_kin_or(facts, cache, x)}"
                    if b not in seen_bits:
                        seen_bits.add(b)
                        bits.append(b)
    else:
        fam = _fam_of(k)
        for key, label in (("father", "父"), ("mother", "母")):
            for x in (fam.get(key) or []):
                try:
                    x = int(x)
                except (TypeError, ValueError):
                    continue
                bits.append(f"{label}{_with_year(x, _kin_or(facts, cache, x))}")
        _seen_sp = set()
        # one relationship word per person: `family_data.former_spouses` also lists current spouses, so
        # dedupe by id (the two built strings differ); pick order is the loop order, primary spouse first.
        for key, kind in (("primary_spouse", "spouse"), ("spouse", "spouse"),
                          ("former_spouses", "former"),
                          ("concubine", "concubine")):
            for x in (fam.get(key) or []):
                try:
                    x = int(x)
                except (TypeError, ValueError):
                    continue
                if x in _seen_sp:
                    continue
                _seen_sp.add(x)
                lbl = _gword(k.get("id"), x, kind)
                b = f"{lbl}{_kin_or(facts, cache, x)}"
                if b not in seen_bits:
                    seen_bits.add(b)
                    bits.append(b)
    # children sit alongside father/mother, so "husband X, daughter Y" holds within one record.
    for e in [k] + grp:
        kids = _fids(e, "child")
        if not kids:
            continue
        if _fi is not None:
            try:
                kids = set(F._asof_ids(_fi, sorted(kids)))
            except Exception:
                pass
        for x in sorted(kids):
            kf = ((cache.get("characters") or {}).get(str(x)) or {}).get("female")
            lbl = "女" if kf else "子"
            b = f"{lbl}{_kin_or(facts, cache, x)}"
            if b not in seen_bits:
                seen_bits.add(b)
                bits.append(b)
    if bits:
        lines.append("亲缘：" + "、".join(bits))
    # romance: match by **memory type** (`event_types`, from facts._killed_by_player), since reworded love
    # sentences drop the keyword and would vanish whole; a missing event_types (old snapshot) falls back to keywords.
    _MAR_TYPES = ("married", "became_lovers", "became_lovers_spouse",
                  "had_sex", "had_sex_spouse", "broke_up_lovers", "spouse_died")
    _MAR_WORDS = ("成婚", "相恋", "私情", "分手", "丧偶", "离婚", "强迫", "半推半就")
    mar = []
    for e in [k] + grp:
        ev = e.get("events") or []
        et = e.get("event_types") or []
        for i, x in enumerate(ev):
            if i < len(et):
                if et[i] in _MAR_TYPES or F.is_sex_memory(et[i]):
                    mar.append(x)
            elif any(m in x for m in _MAR_WORDS):
                mar.append(x)
    # per person, at most 3 lines — 19 people in a cluster would otherwise flood the roster
    if len(mar) > 3:
        mar = mar[-3:]
    if mar:
        lines.append("婚恋与强迫之事：" if any(
            ("强迫" in x or "半推半就" in x) for x in mar) else "婚恋：")
        lines.extend("  " + e for e in mar)
    return lines


def _kin_or(facts, cache, cid):
    """Kin appellation: Facts.kin_label (former/current title + name) first,
    falling back to the unified display-name chain."""
    try:
        fi = facts.get("_facts")
        if fi is not None:
            nm = fi.kin_label(cid)
            if nm:
                return nm
    except Exception:
        pass
    return _name_or(facts, cache, cid)


def _name_or(facts, cache, cid):
    """Character name: archive entry first, then Facts' name_with_regnal (family name / epithet /
    lineage, with its own fallbacks), then the plain cache name last so kin keep their surname."""
    try:
        p = (facts.get("characters") or {}).get(str(cid)) or {}
        if p.get("name"):
            return p["name"]
    except Exception:
        pass
    try:
        fi = facts.get("_facts")
        if fi is not None:
            nm = fi.name_with_regnal(cid)
            if nm:
                return nm
    except Exception:
        pass
    try:
        r = ((cache.get("characters") or {}).get(str(cid)) or {})
        nm = r.get("name_full") or r.get("name_zh") or ""
        if nm:
            return nm
    except Exception:
        pass
    return "某人"


# multi-character words marking "kinship already stated": 「其父」/「其兄」 side references and 「妻室」/「子」
# markers; single characters (子/女/父/母) stay out, since titles like 皇子/国皇女 would collide.
_KIN_MARKS = (
    "其父", "其母", "其子", "其女", "其兄", "其弟", "其姊", "其妹", "其妻",
    "其夫", "其配偶", "其岳父", "其女婿", "其儿媳", "其姻亲兄弟", "其姻亲姊妹",
    "其继子", "其继女", "妻室", "夫婿", "男宠", "前妻", "前夫", "前妾",
    "前男宠", "子女", "实父", "兄弟姊妹", "岳父", "女婿", "儿媳",
    "姻亲兄弟", "姻亲姊妹", "继子", "继女",
)
# the facts side writes the relation into the sentence itself, so every multi-character kin word counts as stated
_KIN_MARKS = tuple(sorted(set(_KIN_MARKS) | {w for w in F.kin_texts() if len(w) >= 2},
                          key=len, reverse=True))
# generic non-blood relation words in death sentences count as stated too
_KIN_MARKS = tuple(sorted(set(_KIN_MARKS) | {"亲属", "仇人", "友人", "情人",
                                             "灵魂伴侣", "挚友", "死敌", "生父"},
                          key=len, reverse=True))
_KIN_MARK_RE = re.compile("|".join(_KIN_MARKS))


def _names_for_line(facts, line):
    """(cid, appellation) pairs registered for this line, the in-line offset and the matched bare
    sentence; a miss retries the suffixes after a punctuation mark (at most 24 chars)."""
    idx = facts.get("name_index") or {}
    hit = idx.get(line)
    if hit is not None:
        return hit, 0, line
    for i in range(len(line) - 1):
        if i >= 24:
            break
        if line[i] in "，；。、 ":
            hit = idx.get(line[i + 1:])
            if hit is not None:
                return hit, i + 1, line[i + 1:]
    return None, 0, None


def _kin_tag_line(facts, scope, line):
    """Prefix the first in-line mention of each name with its kin word (a line out of quota, with no
    kin word, or with the relation stated is unchanged); facts["line_owner"] re-bases third-party words."""
    if scope is None or not line:
        return line
    fi = facts.get("_facts")
    if fi is None:
        return line
    names, off, key = _names_for_line(facts, line)
    if not names:
        return line
    # this line's subject (unregistered → the article subject); the table sits in the facts dict, so a
    # snapshot rerun recomputes the same words from the original data.
    owner = (facts.get("line_owner") or {}).get(key) if key else None
    # counterpart whose relation the sentence already states → no attributive, which would add
    # "married husband X"-style redundancy
    stated = set((facts.get("line_stated") or {}).get(key) or ()) if key else set()
    scan = off
    for cid, label in names:
        if not label:
            continue
        if cid in stated:
            continue
    # entries may mention it as a third party
        if cid == scope.subject:
            continue
        i = line.find(label, scan)
        if i < 0:
            # the index records words as built; some never reach the final sentence, so a miss claims no quota
            continue
        # a kin word already at that spot states the relation: no insert, no quota. Must run before `word_for`
        if _KIN_MARK_RE.search(line[max(off, i - 12):i]):
            scan = i + len(label)
            continue
        # third-party name → relative to the line subject; the line's own subject → the article subject
        _subj = scope.subject
        if owner is not None and int(cid) != owner:
            _subj = owner
        w = scope.word_for(cid, fi, subject=_subj)
        if not w:
            scan = i + len(label)
            continue
        line = f"{line[:i]}{w}{line[i:]}"
        scan = i + len(w) + len(label)
    return line


def _tag_blocks(facts, scope, blocks):
    """Add kin attributives to already-built blocks in block order, idempotently, ahead of the roster
    and victim-line passes, so quotas are consumed in reading order."""
    if scope is None:
        return blocks
    for k, v in list(blocks.items()):
        if not isinstance(v, str) or k in scope.tagged:
            continue
        scope.tagged.add(k)
        blocks[k] = "\n".join(_kin_tag_line(facts, scope, ln)
                              for ln in v.split("\n"))
    return blocks


def _article_subject(facts, cache, key):
    """Subject id behind this article's kin attributives: the friend/enemy themself for a subject
    article, else the protagonist id — not `article["subject"]`, which is a name string."""
    pid = facts.get("player_id")
    if key == "friend":
        try:
            return _pick_friend(cache, as_of=facts.get("as_of"))[0]
        except Exception:
            return pid
    if key == "enemy":
        try:
            return _enemy_for_facts(facts, cache)
        except Exception:
            return pid
    return pid


def _article_facts(facts, cache, key, section=None):
    """Fact text blocks for one article, as {block name: text}; the assassin article slices by board
    (compressed roster for the lead, time slice per chronicle) and keys a local per-call KinScope."""
    pid = facts.get("player_id")
    pname = (facts["protagonist"] or {}).get("name") or ""
    blocks = {}
    subject = _article_subject(facts, cache, key)
    scope = F.KinScope(subject) if subject is not None else None
    # profile and year-by-year digest ship per article; the internal file (「实父X」 plus the reveal chain) goes only to
    # the household-interior articles (jiashi / secrets / qizu), the rest get the public file.
    private_boards = ("jiashi", "secrets", "qizu")
    # the two subject articles override the 「传主档案」 block with their own file
    if key not in ("friend", "enemy") or subject is None:
        # dynasty-chronicle sections get no protagonist profile, else the model moves that household onto the
        # earlier reigns; the lead section keeps the profile.
        _mid_sec = _sec_key(section) not in ("lead", None)
        if not (key == "chaoju" and _mid_sec):
            _set_block(blocks, "传主档案",
                       "\n".join(_protagonist_archive_lines(
                           facts, private=key in private_boards, scope=scope,
                           # the assassin article gets no protagonist death year (death/successor lines)
                           with_death=(key != "assassins"),
                           # the dynasty-chronicle article gets no court details (vassals / council / offices)
                           with_court=(key != "chaoju"))))
    if key == "benji":
        # lead and chronicle sections take disjoint module slices; 【大事年表】 carries the year anchors
        sk = _sec_key(section)
        # 《本纪》 records the protagonist's own children only: a spouse's children by another man belong to
        # 《家室列传》 and 《阴私录》 instead, as the wife's children.
        tl_events = [e for e in F.slice_events(facts.get("timeline") or [], key, sk,
                                               exclude=_has_assassins(facts))
                     if e.get("own_birth") is not False]
        tl = [e["text"] for e in tl_events]
        _set_block(blocks, "大事年表", "\n".join(tl))
        link = _murder_link_line(facts, key, sk)
        if link:
            blocks["说明"] = link
    elif key in ("friend", "enemy"):
        sk = _sec_key(section)
        cid = subject
        if cid is not None:
            lines, events = _subject_facts(facts, cid, scope)
            if sk == "lead":
                blocks["传主档案"] = "\n".join(lines)
            else:
                _prof = facts.get("characters", {}).get(str(cid)) or {}
                ev = _prof.get("events_subjectless") or events
                _set_block(blocks, "传主行迹", "\n".join(ev))
                # the only outlet for sexual matter, which the profile and public timeline blocks exclude
                _gi = facts.get("_facts")
                if _gi is not None:
                    try:
                        _sx = _gi.sex_mem_lines(cid, as_of=facts.get("as_of"),
                                                player=facts.get("player_id"))
                    except Exception:
                        _sx = []
                    _set_block(blocks, "强迫之事", "\n".join(_sx))
                tl = F.slice_events(facts.get("timeline") or [], key, sk,
                                    exclude=_has_assassins(facts))
                # subject articles list only events the subject took part in, so third parties stay out
                tl = _subject_events(facts, key, tl, cid)
                tl = [e["text"] for e in tl]
                if tl:
                    blocks["相关年表"] = "\n".join(tl)
            # reasons for a friendship or feud; how the bond formed belongs to the lead article
            if sk == "lead" and key == "friend":
                fcid, is_fallback = _pick_friend(cache, as_of=facts.get("as_of"))
                if cid == fcid and is_fallback:
                    blocks["说明"] = ("传主与主角没有结友的记录，本传按同朝共事的关系立传，"
                                      "以传主的生平为主。")
                else:
                    rs = _relation_reasons(facts, cache, cid, _friend_types())
                    gi = facts.get("_facts")
                    gr = []
                    if gi:
                        gr = gi.relation_reasons(
                            cid, ("friend", "best_friend", "soulmate",
                                  "blood_brother"))
                    all_r = gr + [x for x in rs if x not in gr]
                    if all_r:
                        blocks["结友缘由"] = "；".join(all_r)
            elif sk == "lead":
                rs = _relation_reasons(facts, cache, cid, _enemy_types())
                # game relation reasons first (rival/grudge/nemesis), then computed causes
                # (kinsman murdered / spouse unfaithful / cuckoo heir) to fill the gaps
                gi = facts.get("_facts")
                causes = []
                if gi:
                    rd = _enemy_dates(cache).get(cid)
                    feud = _feud_sentences(
                        facts, cache, cid,
                        gi.relation_reasons(cid, ("rival", "grudge", "nemesis")),
                        rd)
                    causes.extend(feud)
                    if feud:
                        rs = [x for x in rs
                              if not re.search(r"(结怨|结仇|死敌)", x or "")]
                    if rd:
                        causes.extend(F.relation_cause_lines(gi, cid, rd))
                all_r = causes + [x for x in rs if x not in causes]
                if all_r:
                    blocks["结仇缘由"] = "；".join(all_r)
    elif key == "jiashi":
        sk = _sec_key(section)
        fam_lines = []
        # household article filters kin by as_of (the rule of _asof_ids), so children born after the decade end stay out
        fam_ids = _family_ids(cache)
        fi = facts.get("_facts")
        if fi is not None:
            fam_ids = set(F._asof_ids(fi, sorted(fam_ids)))
        # lead = spouses, chronicles = children and siblings grouped by household (facts.household_groups)
        members = section.get("members") if isinstance(section, dict) else None
        if members:
            pick = [c for c in members if c in fam_ids]
        else:
            spouse_ids = _family_ids_by_kind(cache, "spouse")
            if fi is not None:
                spouse_ids = set(fi.spouses_in_window(sorted(spouse_ids)))
            pick = ([c for c in sorted(fam_ids) if c in spouse_ids]
                    if sk == "lead"
                    else [c for c in sorted(fam_ids) if c not in spouse_ids])
        # reading order: tag names inline in the earlier blocks, then the per-person entry headers
        _tag_blocks(facts, scope, blocks)
        for cid in pick:
            p = facts["characters"].get(str(cid))
            if not p or not p.get("name"):
                continue
            # household article is a private record, so a child's real father is shown
            fam_lines.append("\n".join(
                _profile_lines(facts, cid, with_real_parentage=True,
                               scope=scope)))
            # per-person entries use the subjectless event strings: the profile line above already names
            # the person, so repeating the day's full office and name would only duplicate it.
            ev = p.get("events_subjectless") or p.get("events") or []
            if ev:
                fam_lines.append("  " + "\n  ".join(ev))
        _set_block(blocks, section.get("block_title") or "家室档案",
                   "\n".join(fam_lines))
        # one line per lover (identity plus the affair -> lover -> soulmate arc), so a wife's affairs
        # become writable as a thread instead of isolated date sentences.
        if sk != "lead":
            _set_block(blocks, "妻室情事脉络",
                       "\n".join(_consort_affair_lines(facts, cache)))
            _set_block(blocks, "强纳为妾",
                       "\n".join(facts.get("forced_concubines") or []))
            # the severed prior marriage names the game-designated spouse, not an invented wife; read right
            # after the forced-concubine block it makes the whole cause and effect.
            _set_block(blocks, "妾室原有婚配",
                       "\n".join(facts.get("concubine_divorces") or []))
        tl = F.slice_timeline(facts.get("timeline") or [], key, sk,
                                 exclude=_has_assassins(facts))
        if tl:
            blocks["相关年表"] = "\n".join(tl)
    elif key == "chaoju":
        # data sources: realm.top_title_history (dynasty names and holders) and realm.dynasty_chronicle (one row per ruler)
        realm = facts.get("realm") or {}
        dashi = []
        if realm.get("liege_chain"):
            dashi.append(f"主角所处疆域：{realm['liege_chain']}")
        dc = realm.get("dynasty_chronicle") or {}
        _segs = (section or {}).get("periods") \
            if _sec_key(section) not in ("lead",) else None
        if _segs:
            rows, wars = [], []
            for _p in _segs:
                _rs = list(_p.get("rows") or [])
                _ds = list(_p.get("rows_detail") or [])
                for _i, _r in enumerate(_rs):
                    if not _r:
                        continue
                    _d = _ds[_i] if _i < len(_ds) else None
                    _ok = (_r.count("｜") >= 2) if _d is None else bool(_d)
                    if _ok:
                        rows.append(_r)
                wars.extend(_chrono_wars_in(dc, _p, prev_cut=(section or {}).get("prev_cut")))
            if rows:
                _set_block(blocks, "王朝历代·纪事", "\n".join(rows))
            if wars:
                _set_block(blocks, "本朝战事", "\n".join(_chrono_dedup_wars(wars)))
            if (section or {}).get("is_last"):
                # The closing section's own requirement promises this reign's capital, territory and
                # the protagonist's tenure in it, so those reach the section that has to write them
                # rather than only the opening. The current holder goes with them: the rows stop at the
                # last accession, and without a name on the seat the closing has nothing to go on.
                _close = [x for x in (dc.get("subs") or []) if x]
                _tenure = next((ln for ln in (realm.get("top_title_history") or [])
                                if ln.startswith("主角本朝任期：")), "")
                if _tenure:
                    _close.append(_tenure)
                if _close:
                    _set_block(blocks, "本朝疆域", "\n".join(_close))
                if dc.get("holder_now"):
                    _set_block(blocks, "本朝现任", dc["holder_now"])
        else:
            for ln in (realm.get("top_title_history") or []):
                dashi.append(ln)
            for _x in (dc.get("subs") or []):
                if _x:
                    dashi.append(_x)
            if dc.get("holder_now"):
                dashi.append(dc["holder_now"])
            _set_block(blocks, "王朝历代", "\n".join(dashi))
    elif key == "assassins":
        killed = facts.get("killed") or []
        if killed:
            sec_key = (section or {}).get("key") or ""
            plabel = ((facts.get("protagonist") or {}).get("label")
                      or (facts.get("protagonist") or {}).get("name") or "")
            n_victims = sum(1 for k in killed) + sum(len(k.get("group") or [])
                                                     for k in killed)
            head = (style.FACT_WORDING["assassin_lead"].format(
                n=n_victims, killer=plabel) if plabel else "")
            purges = facts.get("family_purges") or []
            purge_txt = "；".join(purges) + "。" if purges else ""
            _tag_blocks(facts, scope, blocks)
            if sec_key == "lead":
                parts = [head] if head else []
                if purge_txt:
                    parts.append(purge_txt)
                for k in killed:
                    parts.append(_assassin_lead_line(k, facts, scope))
                _set_block(blocks, "刀下诸魂", "\n".join(parts))
            else:
                # chronicles slice by period with full profiles; a blood-kin group is one entry, so offsets count groups
                sl = (section or {}).get("slice")
                picked = killed[sl[0]:sl[1]] if sl else killed
                parts = [head] if head else []
                if purge_txt:
                    parts.append(purge_txt)
                parts += ["\n".join(_assassin_kill_lines(facts, cache, k, scope))
                          for k in picked]
                _set_block(blocks, "刀下诸魂", "\n\n".join(parts))
    elif key == "youxia":
        # profile is in the shared prefix; travel records split in two (lead / chronicles)
        wander = list(facts.get("wandering") or [])
        seg = _split_span(wander, 0 if _sec_key(section) == "lead" else 1)
        _set_block(blocks, "行纪", "\n".join(seg))
    elif key == "qizu":
        imp = facts.get("imperial_spouses") or []
        if imp:
            parts = []
            for e in imp:
                lines = [f"妻族：{e['name']}"]
                if e.get("reasons"):
                    lines.append("门第：" + "、".join(e["reasons"]))
                prof = facts["characters"].get(str(e["id"])) or {}
                for i, x in enumerate(_profile_lines(facts, e["id"])):
                    if i == 0:
                        continue
                    lines.append(x)
                ev = prof.get("events") or []
                if ev:
                    lines.append("经历：")
                    lines.extend("  " + s for s in ev)
                parts.append("\n".join(lines))
            _set_block(blocks, "帝胄姻亲", "\n\n".join(parts))
    elif key == "qunying":
        # court news is sliced per module, with murders excluded
        lum = facts.get("luminaries") or []
        _set_block(blocks, "朝堂群英", "、".join(lum))
        tl = F.slice_timeline(facts.get("timeline") or [], key,
                              _sec_key(section),
                              exclude=_has_assassins(facts))
        _set_block(blocks, "朝局动态", "\n".join(tl))
        link = _murder_link_line(facts, key, sk)
        if link:
            blocks["说明"] = link
    elif key == "feuds":
        feuds = facts.get("house_feuds") or []
        if feuds:
            parts = []
            for fd in feuds:
                parts.append(f"家族：{fd.get('house_label') or fd['house']}，"
                             f"两族为{fd['level']}")
                if fd.get("events"):
                    parts.append("恩怨史：")
                    parts.extend("  " + e for e in fd["events"])
            _set_block(blocks, "家族恩怨", "\n\n".join(parts))
    elif key == "artifacts":
        arts = facts.get("family_artifacts") or []
        _set_block(blocks, "传家重宝", "\n\n".join(arts))
    elif key == "liyi":
        # rite chronicle: lead = rite profile, chronicles = tenets / holy orders / rite history,
        # tail = the church's councils and papal bulls; a block without material is skipped whole,
        # and a dry chronicle leaves the lead alone.
        prof = list(facts.get("rite_profile") or [])
        hist = list(facts.get("rite_history") or [])
        pt = list(facts.get("personal_tenets") or [])
        hos = list(facts.get("holy_orders") or [])
        tcs = list(facts.get("rite_tenet_changes") or [])
        if _sec_key(section) == "lead":
            _set_block(blocks, "礼仪档案", "\n".join(prof) if prof else "")
        elif _sec_key(section) == "tail":
            cc = list(facts.get("church_chronicle") or [])
            _set_block(blocks, "大公会议与教宗诏书", "\n".join(cc) if cc else "")
        else:
            # `rite_tenet_changes` lists changes among the rite's own core tenets; v101 moved them
            # into the church tail block, so the key is empty for a subject that block covers
            if pt:
                _set_block(blocks, "个人教义沿革", "\n".join(pt))
            if hos:
                _set_block(blocks, "修会", "\n".join(hos))
            if hist:
                _set_block(blocks, "礼仪沿革", "\n".join(hist))
            if tcs:
                _set_block(blocks, "本礼教义沿革", "\n".join(tcs))
    elif key == "secrets":
        # secrets: the protagonist's own go to the lead, kin and retainers' secrets to the chronicles.
        sec = facts.get("secrets") or {}
        sk = _sec_key(section)
        kin_lines = list(sec.get("kinsmen") or [])
        has_held = bool(sec.get("held"))
        if sk == "lead":
            lines = list(sec.get("held") or [])
            if sec.get("held_murder"):
                lines.append(_murder_index_line(facts, sec))
            if has_held and sec.get("held_unrevealed"):
                lines.append("这些隐事至今无人知晓。")
            # sexual matter goes to the subject articles only; the disease block stays, the lead showing its first two entries
            dis = list(sec.get("disease") or [])
            if dis:
                lines.append(style.FACT_WORDING["std_head"])
                lines.extend(dis[:2])
            # with no secrets of his own, the lead falls back to the first half of the kin/retainer secrets
            if not lines and kin_lines:
                lines = _split_span(kin_lines, 0)
            _set_block(blocks, "主角隐事", "\n".join(lines))
        else:
            mid_lines = list(kin_lines if has_held else _split_span(kin_lines, 1))
            mid_lines.extend(sec.get("known") or [])
            # hooks travel with this article only; no "the following hooks" heading, which reads as
            # "enumerate these" and invites invented mutual hooks
            mid_lines.extend(list(sec.get("hooks_held") or []))
            mid_lines.extend(list(sec.get("hooks_over") or []))
            # enslavement is a bond of persons, not a hook, so it is listed apart; former slaves stay listed
            en = list(sec.get("enslaved") or [])
            if en:
                mid_lines.append(style.FACT_WORDING["enslaved_head"])
                mid_lines.extend(en)
            enf = list(sec.get("enslaved_former") or [])
            if enf:
                mid_lines.append(style.FACT_WORDING["enslaved_former_head"])
                mid_lines.extend(enf)
            # Carnalitas opinions (rape / forced prostitution / former master) carry their own start_date
            cpl = list(sec.get("carnal_opinions") or [])
            if cpl:
                mid_lines.append(style.FACT_WORDING["carnal_opinions_head"])
                mid_lines.extend(cpl)
            cvl = list(sec.get("carnal_victim") or [])
            if cvl:
                mid_lines.extend(cvl)
            # forced-act material lives in the subject articles; here the disease lines are all sent
            # (the lead shows only the first two).
            dis = list(sec.get("disease") or [])
            if dis:
                mid_lines.append(style.FACT_WORDING["std_head"])
                mid_lines.extend(dis)
            _set_block(blocks, "家人近臣隐事", "\n".join(mid_lines))
            if sec.get("events"):
                blocks["隐事纪年"] = "\n".join(sec["events"])
    # final pass in block order tags the first inline mention of each name (timeline / secrets / feuds).
    _tag_blocks(facts, scope, blocks)
    return blocks


def _murder_index_line(facts, sec):
    """Index line for murder secrets: points at the assassin article when there is one,
    else names the people involved (secret records only, never executions)."""
    n = sec.get("held_murder") or 0
    if _has_assassins(facts):
        return f"另有{n}桩谋杀隐事，详见《刺客列传·刀下诸魂》。"
    names = [x for x in (sec.get("held_murder_names") or []) if x]
    if names:
        return f"另有{n}桩谋杀隐事，涉及{'、'.join(names)}。"
    return f"另有{n}桩谋杀隐事。"


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------

def _rule_block(style_name, secret=False):
    """System rule block; text and order live in style.rule_block."""
    return style.rule_block(style_name, secret)


def _system_msg(style_name="east", extra="", secret=False):
    return style.PROMPTS["system_head"].format(
        rule_block=_rule_block(style_name, secret)) + extra


def _decade_theme_note(facts):
    """Dramatic-theme note: top 5 modules from facts.decade_module_top (ties at 5th kept),
    "this decade" or "a lifetime" label, "" when empty; office-rotation governments relabel display names only (MODULE_SLICE keys stay internal)."""
    dm = facts.get("decade_modules") or []
    if not dm:
        return ""
    names = "、".join(_theme_label(m, facts) for m, _s in dm)
    label = "本十年" if facts.get("decade") else "一生"
    return style.PROMPTS["theme_note"].format(label=label, names=names)


def _celestial_like(facts):
    """True when the protagonist's government belongs to the office-rotation kinds
    (celestial, administrative, meritocratic, steppe administrative)."""
    p = facts.get("protagonist") or {}
    return (p.get("government_key") or "") in F.Facts._CELESTIAL_LIKE_GOVS


def _theme_label(name, facts):
    if name in style.THEME_LABELS and _celestial_like(facts):
        return style.THEME_LABELS[name]
    return name


def _section_req(text, facts):
    """Board requirements are reworded under office-rotation governments (appointment / removal /
    transfer); every other government keeps the text as written."""
    if not text or not _celestial_like(facts):
        return text
    for a, b in style.REQ_SWAPS:
        text = text.replace(a, b)
    return text


def _jiashi_variant(facts, cache):
    """Material variant for the household article: 'spouse' | 'spouse_plain' | 'concubine' | 'none'.
    Spouses (incl. former, latched in Facts.merge_spouse_latch) versus concubines decide what may be requested; 'spouse' needs the 托卵承嗣 chain (facts["villain_chains"]), an openly born bastard gives 'spouse_plain'."""
    pid = cache.get("player_id")
    if pid is None:
        return "none"
    fam = ((cache.get("characters") or {}).get(str(pid)) or {}).get("family") or {}
    if fam.get("primary_spouse") or fam.get("spouse") \
            or fam.get("former_spouses"):
        for _mod, _s, _p in (facts.get("villain_chains") or []):
            if str(_mod) == "托卵承嗣":
                return "spouse"
        return "spouse_plain"
    if fam.get("concubine") or fam.get("former_concubines"):
        return "concubine"
    return "none"


def _protagonist_archive_lines(facts, private=False, scope=None, with_death=True,
                               with_court=True):
    """Protagonist profile lines, sent per article, not in the shared prefix. private adds the
    real-father line and exposure chains; with_death/with_court drop death/successor and court data."""
    return _profile_lines(facts, None, with_real_parentage=private,
                          with_private_chains=private, scope=scope,
                          with_death=with_death, with_court=with_court)


def _shared_facts_block(facts, subject=None, key=None):
    """Fact prefix shared by every call: byte-identical, first in each user message, for prefix-cache hits.
    Stable identity ticket only (subject switches 【传主】 to 【主角】 for friend/enemy); key="assassins" omits the protagonist's death line, so the victim roster cannot continue into it."""
    p = facts["protagonist"]
    name = p.get("name") or "主角"
    house = _house_text(facts)
    death = facts.get("player_death")
    re_end = facts.get("reign_end")            # abdication / tonsure retirement
    if re_end and key != "assassins":
        rz = re_end.get("reason_zh") or "让位"
        life_note = f"【传位】{rz}——此为终传"
    elif re_end:
        life_note = ""
    elif death and key != "assassins":
        rz = death.get("reason_zh") or death.get("reason") or "去世"
        life_note = (f"【卒年】{llm.fmt_cn_date(death.get('date'))}，{rz}"
                     "——此为终传")
    elif death:
        life_note = ""
    elif facts.get("as_of"):
        life_note = f"【现状】在世，截至{llm.fmt_cn_date(facts['as_of'])}"
    else:
        life_note = "【现状】在世，截至最后一份存档"
    # adventurer stations: camp stages and seats for the landless-adventurer period only
    stations_txt = ""
    stations = facts.get("protagonist_stations") or []
    if stations:
        stations_txt = _render_block("【冒险者行踪】", stations)
    # nomad stations: great-camp moves only; a felt tent counts as no holding for the succession phases (facts._primary_group)
    nomad_txt = ""
    nomad_st = facts.get("nomad_stations") or []
    if nomad_st:
        nomad_txt = _render_block("【游牧行踪】", nomad_st)
    # plague flavour uses the game's dynamic plague names, sent only when a plague touches the protagonist's domain or family
    plague_txt = ""
    pl = (facts.get("plagues") or {}).get("lines") or []
    if pl:
        plague_txt = _render_block("【瘟疫】", pl)
    stats_txt = ""
    ds = facts.get("decade_stats") or []
    if ds:
        label = "本十年" if facts.get("decade") else "一生"
        stats_txt = f"【概览】{label}{'、'.join(ds)}。"
    head = f"【{'主角' if subject else '传主'}】{name}\n【家族】{house}"
    out = [f"{head}\n{life_note}" if life_note else head]
    if stations_txt:
        out.append("\n\n" + stations_txt)
    if nomad_txt:
        out.append("\n\n" + nomad_txt)
    if plague_txt:
        out.append("\n\n" + plague_txt)
    if stats_txt:
        out.append("\n\n" + stats_txt)
    return F.sanitize_fact_text("".join(out), where="共享前缀") + ""


_CN_DIGITS = "零一二三四五六七八九"


def _cn_index(n):
    """Article ordinal in Chinese numerals: 1 → 一, 10 → 十, 21 → 二十一. Distinct from
    facts._count_zh (2 as 「两」) and facts._ordinal_zh (below 10 takes 「世」)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if n <= 0:
        return str(n)
    if n < 10:
        return _CN_DIGITS[n]
    if n < 20:
        return "十" + (_CN_DIGITS[n - 10] if n > 10 else "")
    if n < 100:
        t, r = divmod(n, 10)
        return _CN_DIGITS[t] + "十" + (_CN_DIGITS[r] if r else "")
    return str(n)


def build_intro_messages(facts, cfg, articles=None):
    """Intro prompt: shared prefix plus the article preview; the head states birth–death and the closing
    verdict marker is 「太史公曰」."""
    p = facts["protagonist"]
    name = p.get("name") or "主角"
    house = _house_text(facts)
    style_name = facts.get("bio_style") or "east"
    birth = p.get("birth") or ""
    death = facts.get("player_death")
    re_end = facts.get("reign_end")            # abdication / tonsure retirement
    if re_end:
        # an abdicated ruler is still alive, so the "life span (retirement)" form replaces a birth–death span
        span_cn = (f"生平：{birth}–{llm.fmt_cn_date(re_end.get('date'))}"
                   f"（{re_end.get('word_zh') or '让位'}）" if birth else "")
    elif death:
        span_cn = f"生卒：{birth}–{llm.fmt_cn_date(death.get('date'))}"
    else:
        span_cn = f"生于{birth}" if birth else ""
    sys_msg = style.PROMPTS["intro_system"].format(
        rule_block=_rule_block(style_name))
    shared = _shared_facts_block(facts)
    # the intro is the only article judging the whole life, so the public protagonist archive travels with it
    shared = _render_block("【人物档案】",
                           _protagonist_archive_lines(
                               facts, scope=F.KinScope(facts.get("player_id")))) \
        + "\n\n" + shared
    # preview lists the real article titles; numbering goes through `_cn_index` (ten or more articles)
    if articles:
        preview = "\n".join(
            f"{_cn_index(i + 1)}、《{a['title']}》——{a.get('focus') or a.get('theme') or a['key']}"
            for i, a in enumerate(articles))
        n_articles = len(articles)
    else:
        preview = style.PROMPTS["preview_fallback"].format(name=name)
        n_articles = 5
    user_msg = style.PROMPTS["intro_user"].format(
        shared=shared, theme=_decade_theme_note(facts), n_articles=n_articles,
        preview=preview, name=name, house=house, span_cn=span_cn)
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def build_lead_messages(article, facts, cache, intro, cfg):
    """Opening-section prompt for one article: a byte-identical shared prefix (prefix-cache
    hits), the intro block and the article's own fact and event blocks."""
    key = article["key"]
    sec = article["sections"][0]
    title = article["title"]
    style_name = facts.get("bio_style") or "east"
    blocks = _article_facts(facts, cache, key, sec)
    sys_msg = style.PROMPTS["system_head"].format(
        rule_block=_rule_block(style_name, key in style.SECRET_BOARDS))
    facts_txt = "\n\n".join(_render_block(k, v.split("\n")) for k, v in blocks.items())
    subject_note = _subject_note(article, facts)
    custom_note = ""
    if key == "benji" and (facts["protagonist"] or {}).get("custom_start"):
        # a custom-start lineage has no father/mother rows, so the note only says how to write
        custom_note = style.PROMPTS["custom_start_note"]
    events_block = _key_events_block(facts, key, sec,
                                     subject=_article_subject(facts, cache, key))
    # dynasty chronicles get no 【总纲】, which they would copy verbatim; their own material suffices.
    intro_block = "" if key == "chaoju" else f"【总纲】\n{intro}\n\n"
    user_msg = style.PROMPTS["lead_user"].format(
        shared=_shared_facts_block(facts, subject=article.get("subject"), key=key),
        theme=_decade_theme_note(facts),
        intro=intro, intro_block=intro_block,
        custom_note=custom_note, subject_note=subject_note,
        facts=facts_txt,
        events=(f"{events_block}\n\n" if events_block else ""),
        title=title, focus=article.get("focus") or article.get("theme") or "",
        sec_title=sec["title"], sec_req=sec["req"])
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


def _subject_note(article, facts):
    """Narrative-centre note for subject articles (friend/enemy biographies); empty when the
    article has no subject. The subject's name is fixed here once, as a leading 【传主】X."""
    subj = article.get("subject")
    if not subj:
        return ""
    return style.PROMPTS["subject_note"].format(
        subject=subj, protagonist=(facts["protagonist"] or {}).get("name") or "")


def build_section_messages(article, section, facts, cache, lead_text, cfg):
    """Mid-section prompt: the opening section fed back as a prefix+tail digest instead of the full
    【总纲】 text, with 【本板块大事】 anchoring the tail."""
    key = article["key"]
    title = article["title"]
    style_name = facts.get("bio_style") or "east"
    blocks = _article_facts(facts, cache, key, section)
    sys_msg = style.PROMPTS["system_head"].format(
        rule_block=_rule_block(style_name, key in style.SECRET_BOARDS))
    facts_txt = "\n\n".join(_render_block(k, v.split("\n")) for k, v in blocks.items())
    subject_note = _subject_note(article, facts)
    # dynasty chronicle sections send no 【本板块大事】, which invites invented events; the rows' dates anchor the tail
    if key == "chaoju" and _sec_key(section) not in ("lead", None):
        events_block = ""
    else:
        events_block = _key_events_block(facts, key, section,
                                         subject=_article_subject(facts, cache, key))
    # dynasty-split sections need a shorter hand-off, else the model rewrites the whole dynasty summary
    _dg_limit, _dg_tail = (120, 90) if key == "chaoju" else (260, 180)
    user_msg = style.PROMPTS["mid_user"].format(
        shared=_shared_facts_block(facts, subject=article.get("subject"), key=key),
        theme=_decade_theme_note(facts),
        subject_note=subject_note, facts=facts_txt,
        events=(f"{events_block}\n\n" if events_block else ""),
        title=title, focus=article.get("focus") or article.get("theme") or "",
        sec_title=section["title"], sec_req=section["req"],
        lead_title=article["sections"][0]["title"],
        lead_digest=_lead_digest(lead_text, limit=_dg_limit, tail=_dg_tail,
                                 facts_text=facts_txt))
    return [{"role": "system", "content": sys_msg},
            {"role": "user", "content": user_msg}]


# ---------------------------------------------------------------------------
# text normalisation and assembly
# ---------------------------------------------------------------------------

_MAG_HEAD_RE = re.compile(r"^#{1,6}\s+")


# section-tail integrity: truncation mid-sentence leaves a lone opening bracket or unclosed `**`
_DANGLING_OPEN = "「『“【《〈（([{"


def _tail_issue(text):
    """Reason string when a section body looks truncated (lone opening bracket or unclosed
    `**`), else None. Pure function."""
    t = (text or "").rstrip()
    if not t:
        return None
    if t[-1] in _DANGLING_OPEN:
        return f"末字为开括号「{t[-1]}」"
    if t.count("**") % 2:
        return "强调符 ** 未闭合"
    return None


def _trim_dangling_tail(text):
    """Drop trailing lone opening brackets (closing symbols and body untouched); returns
    (text, changed)."""
    t = (text or "").rstrip()
    changed = False
    while t and t[-1] in _DANGLING_OPEN:
        t = t[:-1].rstrip()
        changed = True
    return t, changed


def _strip_markdown_tables(text):
    """Fallback that renders model-emitted Markdown table rows as prose sentences."""
    lines = (text or "").split("\n")
    out = []
    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        if (ln.startswith("|")
                and i + 1 < len(lines)
                and re.match(r"^\s*\|[\s:\-|]+\|\s*$", lines[i + 1])):
            headers = [c.strip() for c in ln.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                pairs = []
                for h, v in zip(headers, cells):
                    if not h or not v or v in ("-", "—", "N/A"):
                        continue
                    pairs.append(f"{h}为{v}")
                rows.append("，".join(pairs) if pairs else "、".join(cells))
                i += 1
            if rows:
                out.append("，".join(rows) + "。")
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _fix_person_names(text, facts, cache):
    """Restore the full name behind a "surname + kin word" string that names no known person
    (F.kin_word confirms one same-surname match); repairs what `_fix_kin_roles` cannot."""
    if not text:
        return text
    chars = (facts or {}).get("characters") or {}
    pid = cache.get("player_id") or (facts or {}).get("player_id")
    by_name, by_sur = {}, {}
    for cid_s, rec in chars.items():
        nm = (rec or {}).get("name") or ""
        if len(nm) < 3 or not re.search(r"[\u3400-\u9fff]", nm):
            continue
        try:
            cid = int(cid_s)
        except (TypeError, ValueError):
            continue
        sur = nm[:-2]
        if len(sur) < 2:
            continue
        by_name.setdefault(nm, cid)
        by_sur.setdefault(sur, {})[nm] = cid
    if not by_sur or pid is None:
        return text
    known = set(by_name)
    words = [w for w in sorted(F.kin_texts(), key=len, reverse=True)
             if len(w) >= 2]
    out = text
    for sur, cands in by_sur.items():
        for w in words:
            bad = sur + w
            if bad in known or bad not in out:
                continue
            hit = ""
            for nm in sorted(cands):
                try:
                    if F.kin_word(cache, pid, cands[nm]) == w:
                        hit = nm
                        break
                except Exception:
                    continue
            if hit:
                out = out.replace(bad, hit)
    return _dedup_adjacent_words(out)


def _fix_kin_roles(text, facts, cache):
    """Rewrite the kin word attached to a name when it disagrees with the archive (last kin
    word in the 12 characters before it). Pure and idempotent; truth is the cache kin graph."""
    if not text:
        return text
    pid = cache.get("player_id")
    fi = (facts or {}).get("_facts")
    if pid is None or fi is None:
        return text
    fam = ((cache.get("characters") or {}).get(str(pid)) or {}).get("family") or {}
    kids = set(fam.get("child") or []) | set(fam.get("siblings") or [])
    others = []
    for key in ("primary_spouse", "spouse", "former_spouses", "ever_spouses",
                "concubine", "former_concubines", "father", "mother"):
        others.extend(fam.get(key) or [])
    others.extend(sorted(kids))
    chars = cache.get("characters") or {}
    # only multi-character kin words are candidates: a single 子/父/母 also occurs inside the replacement (妻子 contains 子)
    all_words = {F.kin_text(k) for k in F.KIN_WORDS}
    all_words = {w for w in all_words if w and len(w) >= 2}
    # 妻室 is the archive word for a spouse, absent from the kin table, so it is added explicitly
    all_words |= {"妻室"}
    out = text
    for other in dict.fromkeys(int(x) for x in others
                               if isinstance(x, int) or str(x).isdigit()):
        rec = chars.get(str(other)) or {}
        names = [rec.get("name_full"), rec.get("name_zh"),
                 (facts.get("characters", {}).get(str(other)) or {}).get("name")]
        names = [n for n in dict.fromkeys(names) if n]
        if not names:
            continue
        try:
            true_word = F.kin_word(cache, pid, other, chars=chars)
        except Exception:
            true_word = ""
        if not true_word:
            continue
        for nm in names:
            i = out.find(nm)
            guard = 0
            while i != -1 and guard < 8:
                guard += 1
                win = out[max(0, i - 12):i]
                best_w, best_p = "", -1
                for w in all_words:
                    if not w or w == true_word:
                        continue
                    j = win.rfind(w)
                    if j < 0:
                        continue        # word absent from the window (rfind -1 must not win)
                    # at equal positions prefer the longest word (伯祖父 ⊃ 祖父), else a precise word gets
                    # replaced by a coarser one (the table holds 42 mutually suffixing pairs).
                    if j > best_p or (j == best_p and len(w) > len(best_w)):
                        best_w, best_p = w, j
                if best_w:
                    at = max(0, i - 12) + best_p
                    out = out[:at] + true_word + out[at + len(best_w):]
                    i = out.find(nm, at + len(true_word) + len(nm))
                else:
                    i = out.find(nm, i + 1)
    # rewriting must not create adjacent duplicates, so it funnels through the same gate as the finished section
    return _dedup_adjacent_words(out)



# adjacent-duplicate gate for finished sections, limited to kin terms, titles, realm names and origin
# words; only a listed word repeated directly after itself is collapsed, so legal reduplication survives.
_DEDUP_WORDS = (
    "姐姐", "妹妹", "哥哥", "弟弟", "兄长", "兄弟", "姊妹", "妻子", "丈夫",
    "母亲", "父亲", "儿子", "女儿", "祖父", "祖母", "伯父", "叔父", "姑母",
    "姨母", "舅父", "舅舅", "外甥女", "外甥", "侄女", "侄子",
    "帝国", "王国", "公国", "侯国", "伯国", "皇朝", "天朝", "王朝", "汗国",
    "苏丹国", "哈里发国", "皇帝", "皇后", "国王", "公爵", "伯爵", "侯爵",
    "男爵", "可汗", "大汗", "酋长", "节度使", "刺史", "宰相", "尚书",
    "庶出", "私生子",
)
_DEDUP_RE = re.compile("(" + "|".join(sorted(_DEDUP_WORDS, key=len, reverse=True))
                       + r")\1")


def _dedup_adjacent_words(text):
    """Collapse a word repeated back-to-back into one; see `_DEDUP_WORDS` for the scope."""
    if not text:
        return text
    return _DEDUP_RE.sub(r"\1", text)


def _normalize_section(text, sec_title, article_title=""):
    """Normalise a section body: headings to "###" (adding the section title when missing),
    Markdown tables to prose, 太史公曰/史家按 commentary and duplicate headings stripped."""
    out = []
    saw = False
    seen_titles = set()
    # short form of the section title (no 开篇·/纪事·/评曰· prefix); the model often emits that same short form again
    short = re.sub(r"^(开篇|纪事|评曰)[··]?", "", sec_title).strip()
    # a title without the 开篇/纪事/评曰 prefix has no short form, so a verbatim heading would be dropped as a duplicate
    if short == sec_title:
        short = ""
    art_plain = re.sub(r"^《|》$", "", article_title or "")
    for raw in (text or "").split("\n"):
        s = raw.strip()
        if not s:
            out.append("")
            continue
        if s.startswith("#"):
            if sec_title in s:
                saw = True
            if re.search(r"太史公曰|史家按", s):
                out.append("")  # commentary heading (### 太史公曰) dropped
                continue
            s = re.sub(r"^(#{1,6})\s+", "### ", s)
            head = s.lstrip("# ").strip()
            # a heading shaped like "<dynasty> (year range)" is demoted to body text.
            if re.match(
                    r"^.+（\d{3,4}年(?:\d{1,2}月\d{0,2}日?)?\s*"
                    r"(?:[至—－-]\s*\d{3,4}年(?:\d{1,2}月\d{0,2}日?)?|至今)）$",
                    head):
                out.append("")
                continue
            if head == short or (art_plain and head == art_plain) \
                    or head in seen_titles:
                out.append("")
                continue
            seen_titles.add(head)
            out.append(s)
            continue
        stripped = s.lstrip("*# \t")
        if stripped.startswith("太史公曰") or stripped.startswith("史家按"):
            out.append("")  # blank line holds the paragraph spacing
            continue
        for marker in ("太史公曰", "史家按"):
            if marker in s:
                s = s.split(marker, 1)[0].rstrip().rstrip("，")
                break
        out.append(s)
    body = _strip_markdown_tables("\n".join(out)).strip()
    body = llm.clean_number_spaces(body)
    # deterministic halfwidth-punctuation fix; also covers opening text pasted back as a section digest
    body = llm.normalize_zh_punct(body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    body = _dedup_adjacent_words(body)
    if not saw and body.strip():
        body = f"### {sec_title}\n\n{body}"
    return body


# roster-entry shape: a name (optionally bold), a comma and a full date; the label excludes punctuation
_ROSTER_ENTRY_RE = re.compile(
    r"^\s*\*{0,2}(?P<label>[^*，,。：:；;！!？?…「」『』《》〈〉“”\"'（）()\[\]【】]"
    r"{1,40}?)\*{0,2}\s*[，,]\s*\d{3,4}年\d{1,2}月\d{1,2}日")
_ARTICLE_HEAD_RE = re.compile(r"^## \d+、")


def _drop_subject_roster_lines(md, facts, articles):
    """Drop roster entries for the protagonist himself inside 《刺客列传》, whose model-appended
    death line is isomorphic to a victim entry; returns (new md, lines removed)."""
    asa = next((i for i, a in enumerate(articles, 1)
                if (a or {}).get("key") == "assassins"), None)
    if asa is None:
        return md, 0
    p = facts.get("protagonist") or {}
    label = str(p.get("label") or "")
    name = str(p.get("name") or "")
    # a two-character name is ambiguous: accept it only through the full label
    idents = [x for x in (label, name) if x and (x == label or len(x) >= 3)]
    if not label and not name:
        return md, 0
    # real victims from the roster (group kin included) stay, even when their label suffix matches the subject.
    victims = set()
    for k in (facts.get("killed") or []):
        for it in [k] + list((k or {}).get("group") or []):
            for key in ("label", "name"):
                v = str((it or {}).get(key) or "")
                if v:
                    victims.add(v)
    head = f"## {asa}、《{(articles[asa - 1] or {}).get('title') or ''}》"
    out, dropped, inside, sample = [], 0, False, ""
    for ln in md.split("\n"):
        if _ARTICLE_HEAD_RE.match(ln):
            inside = (ln.strip() == head)
            out.append(ln)
            continue
        if inside:
            m = _ROSTER_ENTRY_RE.match(ln)
            if m:
                lab = m.group("label")
                if (lab not in victims
                        and any(lab == nm or (len(nm) >= 3 and lab.endswith(nm))
                                for nm in idents)
                        and ("死" in ln or "卒" in ln or "崩" in ln)):
                    dropped += 1
                    sample = sample or ln.strip()
                    continue
        out.append(ln)
    if dropped:
        llm.log(f"【刺客列传】删除传主本人的名录条目 {dropped} 行 "
                f"(本篇名录只列死于主角之手者): {sample[:60]}")
    return "\n".join(out), dropped


# intro_user asks the model for its own title and byline while _assemble prepends the programmatic ones,
# so every finished article opens with two headings; the programmatic pair stays and the model's is stripped.
_INTRO_HEAD_RES = (
    # (1) heading line: optional quote/bold/label prefix wrapping a 《…》 title
    re.compile(r"^[>\-*+\s]*#{0,6}[>\-*+\s]*(?:标题|题目)?\s*[：:]?\s*"
               r"《[^》]{1,60}》[>\-*+\s]*$"),
    # (2) byline line: short line with '｜' plus a role/lifespan field label
    re.compile(r"^[>\-*+]{0,2}\s*\**[^\n｜|]{0,40}[｜|][^\n]{0,8}"
               r"(?:人物|生卒|生平)[：:][^\n]{0,80}$"),
    # (3) short byline starting the line with the house or person field
    re.compile(r"^[>\-*+]{0,2}\s*\**(?:家族|人物)[：:][^\n]{0,120}$"),
    # (4) prompt placeholder echoed verbatim as a bare label line
    re.compile(r"^[>\-*+]{0,2}\s*\**(?:总纲正文|总纲|正文|传记正文)\s*[：:…]*$"),
)


def _strip_intro_head(intro):
    """Strip model-written title/byline lines from the start of the intro (idempotent):
    at most 4 blank-skipping lines drop, the scan stops at the first non-matching line."""
    intro = intro or ""
    lines = intro.split("\n")
    i, dropped, sample = 0, 0, ""
    while i < len(lines) and dropped < 4:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if not any(r.match(s) for r in _INTRO_HEAD_RES):
            break
        sample = sample or s
        dropped += 1
        i += 1
    if not dropped:
        return intro
    llm.log(f"总纲开头剥掉模型另写的标题/题记行 {dropped} 行 "
            f"(标题与题记由组装侧统一添加): {sample[:60]}")
    return "\n".join(lines[i:]).strip()


def _assemble(facts, intro, leads, sections, articles):
    parts = [f"# 《{facts['protagonist']['name']}传》"]
    p = facts["protagonist"]
    house = _house_text(facts)
    death = facts.get("player_death")
    re_end = facts.get("reign_end")            # abdication/retirement outranks the death record
    span = ""
    if re_end:
        span = f"{re_end.get('reason_zh') or '让位'}，此为终传"
    elif death:
        span = f"死于{llm.fmt_cn_date(death.get('date'))}，此为终传"
    else:
        cutoff = facts.get("as_of") or facts.get("last_date")
        span = f"截至{llm.fmt_cn_date(cutoff or '?')}"
    parts.append(f"> 家族：{house}｜人物：{p.get('name')}｜{span}")
    parts.append("")
    # _strip_intro_head drops the model-written head, leaving the programmatic title and byline above.
    parts.append(_strip_intro_head(intro))
    for i, a in enumerate(articles, 1):
        parts.append("")
        parts.append("---")
        parts.append("")
        parts.append(f"## {i}、《{a['title']}》")
        parts.append("")
        parts.append(leads[a["key"]])
        for s in a["sections"][1:]:
            parts.append("")
            parts.append(sections[(a["key"], s["key"])])
    if death:
        parts.append("")
        parts.append("---")
        parts.append("")
        parts.append(f"## {len(articles) + 1}、终传附录")
        parts.append("")
        parts.append(_appendix_text(facts))
    return "\n".join(parts)


def _appendix_text(facts):
    """Terminal-article appendix (genealogy + timeline) rendered from facts, no LLM call:
    list items with year/month/day folding, protagonist/family events only, deduped by (date, event key)."""
    lines = []
    gen = facts.get("genealogy") or []
    if gen:
        lines.append("### 世系")
        lines.extend("- " + g for g in gen)
        for ln in ((facts.get("protagonist") or {}).get("house_history") or []):
            if ln:
                lines.append("- " + ln)
    names = set()
    p = facts["protagonist"] or {}
    pname = p.get("name") or ""
    if pname:
        names.add(pname)
    # names from genealogy lines: everything after the colon (wife/concubine/children/parents/siblings)
    for ln in gen:
        if "：" in ln:
            for nm in ln.split("：", 1)[1].replace("、", " ").split():
                if nm:
                    names.add(nm)
    # protagonist-related events, grouped by (year, month, day) → semantic key → (priority, text)
    events = [e for e in facts.get("timeline") or []
              if any(n and n in e["text"] for n in names)]
    by_day = {}   # (y, m, d) -> {event key: (priority, text)}
    for e in events:
        y, mo, d = 0, 0, 0
        try:
            y, mo, d = (int(x) for x in str(e.get("date")).split(".")[:3])
        except Exception:
            continue
        body = re.sub(r"^\d+年\d+月\d+日，?", "", e["text"])
        body = re.sub(r"^\d+年，?", "", body)
        key = _timeline_event_key(body)
        if key is None:
            continue
        cur = by_day.setdefault((y, mo, d), {})
        prio = _timeline_event_priority(body, pname)
        old = cur.get(key)
        if old is None or prio > old[0]:
            cur[key] = (prio, body)
    if by_day:
        lines.append("")
        lines.append("### 大事年表")
        n_year, n_month = {}, {}
        for (y, mo, d), evs in by_day.items():
            n_year[y] = n_year.get(y, 0) + len(evs)
            n_month[(y, mo)] = n_month.get((y, mo), 0) + len(evs)
        last_y, last_mo = None, None
        for (y, mo, d) in sorted(by_day):
            bodies = [b for _, b in sorted(by_day[(y, mo, d)].values(),
                                           key=lambda x: -x[0])]
            # 1 Jan is a year-level date (unknown birth date / yearly snapshot): year only
            year_only = (mo == 1 and d == 1)
            if n_year[y] == 1:
                for body in bodies:
                    if year_only:
                        lines.append(f"- {y}年 {body}")
                    else:
                        lines.append(f"- {y}年{mo}月{d}日 {body}")
                continue
            if y != last_y:
                lines.append(f"- {y}年")
                last_y = y
                last_mo = None
            if year_only:
                for body in bodies:
                    lines.append(f"  - {body}")
                last_mo = None
                continue
            if n_month[(y, mo)] == 1:
                for body in bodies:
                    lines.append(f"  - {mo}月{d}日 {body}")
                last_mo = mo
                continue
            if mo != last_mo:
                lines.append(f"  - {mo}月")
                last_mo = mo
            for body in bodies:
                lines.append(f"    - {d}日 {body}")
    return "\n".join(lines)


def _timeline_event_key(body):
    """Semantic key collapsing the several phrasings of one death or birth event into one
    key (the date participates separately); other events key on the raw text."""
    m = re.match(r"^.+?的(?:亲属|友人)(.+去世。)$", body)
    if m:
        return ("亡", m.group(1))
    m = re.match(r"^.+?的仇人(.+去世。)$", body)
    if m:
        return ("亡", m.group(1))
    m = re.match(r"^(.+?)死于(?:\d+年\d+月\d+日|\d+年)", body)
    if m:
        return ("亡", m.group(1) + "去世。")
    m = re.match(r"^.+?(?:得长子|得长女|添子|添女)(.+。)$", body)
    if m:
        return ("生", m.group(1))
    if re.match(r"^.+?得孪生(?:子|女)。$", body):
        return ("生", "孪生子。")
    if re.match(r"^.+?产下死婴。$", body):
        return ("生", "产下死婴。")
    if re.match(r"^.+?流产。$", body):
        return ("生", "流产。")
    if re.match(r"^.+?幼子夭折。$", body):
        return ("生", "幼子夭折。")
    if re.match(r"^.+?婴儿夭折。$", body):
        return ("生", "婴儿夭折。")
    return ("事", body)


def _timeline_event_priority(body, pname):
    """Ranking when several viewpoints of one event compete: death record (fullest) >
    death memory > rest; within a tier, text opening with the protagonist's name wins."""
    if re.search(r"死于(?:\d+年\d+月\d+日|\d+年)", body):
        tier = 2
    elif re.search(r"的(?:亲属|友人|仇人).+?去世。$", body):
        tier = 1
    else:
        tier = 0
    return tier * 10 + (1 if pname and body.startswith(pname) else 0)


# ---------------------------------------------------------------------------
# main flow
# ---------------------------------------------------------------------------

def _assassin_sections(n):
    """Sections of the assassins board: kills split into 1 (<30), 2 (30-59) or 3 (>=60) slices
    in death order; with 1-2 kills the lead uses the single-subject requirement (`lead_one`)."""
    if n >= 60:
        mids = ["mid1", "mid2", "mid3"]
    elif n >= 30:
        mids = ["mid1", "mid2"]
    else:
        mids = ["mid"]
    lead_req = style.SECTION_REQ["assassins"]["lead"]
    if n <= 2:
        lead_req = (style.SECTION_REQ["assassins"].get("lead_one") or lead_req)
    secs = [{"key": "lead", "title": style.SECTION_TITLES["assassins"]["lead"],
             "req": lead_req}]
    chunk = (n + len(mids) - 1) // len(mids)
    for i, k in enumerate(mids):
        lo, hi = i * chunk, min((i + 1) * chunk, n)
        secs.append({"key": k, "title": style.SECTION_TITLES["assassins"][k],
                     "req": style.SECTION_REQ["assassins"][k],
                     "slice": (lo, hi)})
    return secs


def _chrono_mid_req(base_req, idx, total, periods, last=False, family=False):
    """Board requirement for one chronicle chunk: prefixes `base_req` with the chunk's scope
    (reigns, year spans, index/total), taken from the same `dynasty_chronicle` data as the material block."""
    names = [p.get("name") or "" for p in (periods or []) if p.get("name")]
    head = "本请求只写这一节"
    if total > 1:
        head += f"（第{idx + 1}节，共{total}节）"
    head += "。"
    if family:
        head += "本板块写先世各位统治者的辈分次序与事迹：" + "、".join(names) + "。"
    else:
        spans = []
        for p in (periods or []):
            _s = str(p.get("start") or "").split(".", 1)[0]
            _e = str(p.get("end") or "").split(".", 1)[0] if p.get("end") else ""
            if _s:
                spans.append(f"{p.get('name') or ''}（{_s}年至{_e or '今'}）")
        head += "本板块写这几朝：" + "、".join(names) + "。"
        if spans:
            head += "年代区间：" + "、".join(spans) + "。"
    if last:
        head += "本板块是本篇的末节，写到传主在位的最后一年为止。"
    return head + "\n\n" + (base_req or "")


def _chrono_wars_in(dc, period, prev_cut=None):
    """War lines for one chronicle chunk, cut on chunk end years rather than reign spans so
    interregnum wars between reigns are not dropped; the last chunk takes the remainder."""
    wars = [w for w in ((dc or {}).get("wars") or []) if w]
    if not wars:
        return []
    ps = (period or {}).get("periods") or [period or {}]

    def _yr(s):
        """Date string to four-digit year ('868.1.1' -> '868'; empty for a missing value)."""
        return str(s or "").split(".", 1)[0]

    cut = ""
    for p in reversed(ps):
        if p.get("end"):
            cut = _yr(p.get("end"))
            break
    lo = _yr(prev_cut)
    out = []
    for w in wars:
        m = re.match(r"^(\d{3,4})年", w)
        yr = m.group(1) if m else ""
        if not yr:
            continue
        if lo and yr < lo:
            continue
        if cut and yr >= cut:
            continue
        out.append(w)
    return out


def _chrono_dedup_wars(wars):
    """Merge the two sides of one war into a single line, keyed by (campaign start date, sorted
    name pair); a side carrying an outcome is preferred, mirrored outcome phrasings counting as one."""
    _RE = re.compile(r"^(\d{3,4}年\d{1,2}月\d{1,2}日)(.+?)(?:兴兵讨|应战拒)(.+?)；")
    out, idx = [], {}
    for w in wars:
        if not w:
            continue
        m = _RE.match(w)
        if not m:
            out.append(w)
            continue
        key = (m.group(1), tuple(sorted((m.group(2), m.group(3)))))
        tail = w.split("；", 1)[1] if "；" in w else ""
        won = "战胜" in tail
        j = idx.get(key)
        if j is None:
            idx[key] = len(out)
            out.append(w)
        elif won and "战胜" not in out[j].split("；", 1)[1]:
            out[j] = w
    return out


def _same_period(a, b):
    """True when two periods are the same reign, compared by (name, start); after a JSON round
    trip `current` and its twin in `periods` are distinct objects, so an `is` check would double it."""
    if not a or not b:
        return False
    return (a.get("name"), a.get("start")) == (b.get("name"), b.get("start"))


def _chrono_keep_rows(p):
    """One reign with the rows its material gate keeps: `rows` and the three parallel arrays
    (`rows_detail` / `rows_dates` / `rows_ids`) filtered together, so a chunk is never planned around
    a row the fact block will drop. Rows with no recorded flag (`None`, older caches) are kept.

    Returns `p` itself when nothing changes, so the caller's identity checks still work."""
    rows = list(p.get("rows") or [])
    dets = list(p.get("rows_detail") or [])
    if len(dets) < len(rows) or all(d is None for d in dets):
        return p
    keep = [i for i, d in enumerate(dets) if d is None or d]
    if len(keep) == len(rows):
        return p
    out = dict(p)
    out["rows"] = [rows[i] for i in keep]
    out["rows_detail"] = [dets[i] for i in keep]
    for k in ("rows_dates", "rows_ids"):
        arr = list(p.get(k) or [])
        out[k] = [arr[i] for i in keep] if len(arr) >= len(rows) else []
    return out


def _chrono_usable(p):
    """True when a reign can stand as its own chronicle chunk: at least 2 rulers, since one
    ruler leaves nothing beyond accession/birth/death to write and invites invention."""
    return len([r for r in (_chrono_keep_rows(p).get("rows") or []) if r]) >= 2


def _chrono_row_chunks(p, per=None):
    """Split one reign into `per`-row chunks (default F.CHRONICLE_ROWS_PER_SECTION) spread as evenly
    as possible; a whole-reign request overruns one reply, and each chunk ends at the next chunk's
    `rows_dates` accession. Even spreading keeps the last chunk from degenerating into a single row —
    that lone row used to be the biographee's own, and losing it to the material gate left the
    closing section with nothing to write."""
    p = _chrono_keep_rows(p)
    rows = [r for r in (p.get("rows") or [])]
    if not rows:
        return [p]
    per = max(1, int(per or getattr(F, "CHRONICLE_ROWS_PER_SECTION", 4)))
    if len(rows) <= per:
        return [p]
    dates = list(p.get("rows_dates") or [])
    ids = list(p.get("rows_ids") or [])
    dets = list(p.get("rows_detail") or [])
    n = -(-len(rows) // per)                    # ceil: 9 rows / 4 -> 3 chunks of 3
    base, extra = divmod(len(rows), n)
    out, i = [], 0
    for k in range(n):
        m = base + (1 if k < extra else 0)
        chunk = rows[i:i + m]
        seg = dict(p)
        seg["rows"] = chunk
        seg["rows_detail"] = dets[i:i + m] if len(dets) >= len(rows) \
            else [None] * len(chunk)
        seg["rows_dates"] = dates[i:i + m] if len(dates) >= len(rows) else []
        seg["rows_ids"] = ids[i:i + m] if len(ids) >= len(rows) else []
        if seg["rows_dates"]:
            seg["start"] = seg["rows_dates"][0]
        j = i + m
        if j < len(rows) and len(dates) >= j + 1:
            seg["end"] = dates[j]
        out.append(seg)
        i += m
    if out:
        out[-1]["end"] = p.get("end")
    return out


def _chrono_split(periods, cap=None):
    """Split reigns into <= `cap` sections (default `facts.CHRONICLE_MID_MAX`) after cutting long
    reigns by ruler count; a section joins its reign names and takes the span's start/end."""
    ps = []
    for p in (periods or []):
        if _chrono_usable(p):
            ps.extend(_chrono_row_chunks(p))
    if not ps:
        return []
    cap = max(1, int(cap if cap is not None
                     else getattr(F, "CHRONICLE_MID_MAX", 4)))
    n = max(1, min(cap, len(ps)))
    base, extra = divmod(len(ps), n)
    out, i = [], 0
    for k in range(n):
        m = base + (1 if k < extra else 0)
        chunk = ps[i:i + m]
        i += m
        if not chunk:
            continue
        out.append({
            "name": "、".join(p.get("name") or "" for p in chunk),
            "start": chunk[0].get("start"),
            "end": chunk[-1].get("end"),
            "ids": [x for p in chunk for x in (p.get("ids") or [])],
            "rows": [r for p in chunk for r in (p.get("rows") or [])],
            "rows_detail": [d for p in chunk
                            for d in (p.get("rows_detail")
                                      or [None] * len(p.get("rows") or []))],
            "periods": chunk})
    return out


def _mid_req_for_group(base_req, idx, total, group):
    """Board requirement for one household group request: prefixes `base_req` with the
    scope of this group — kind "spouse" one wife's house, kind "child" one group of children."""
    label = (group or {}).get("label") or ""
    kids = list((group or {}).get("children") or [])
    kind = (group or {}).get("kind") or "spouse"
    mates = list((group or {}).get("mates") or [])
    names = [str(x) for x in ((group or {}).get("names") or []) if x]
    who = "、".join(names) if names else label
    head = ""
    if kind == "child":
        head = f"本请求只写这一组子女：{who}"
        if total > 1:
            head += f"（第{idx + 1}节，共{total}节）"
        head += "。"
        if len(kids) > 1:
            head += (f"本组子女共{len(kids)}人，已随本组档案一并给出；"
                     "本板块逐人写出他们的受任、婚配、子嗣与家中的事。")
        else:
            head += ("本板块写这一名子女的成年行迹：受任何职、与何人成婚、"
                     "已育子女，以及与父母的往来。")
    else:
        head = f"本请求只写这一房：{label}"
        if total > 1:
            head += f"（第{idx + 1}节，共{total}节）"
        head += "。"
        head += f"这一房是{who}。"
        if len(mates) > 1:
            head += (f"这一房含{len(mates)}位妻妾，已随本组档案一并给出；"
                     "本板块逐人写出她们的结婚、感情与家中的事。")
        if kids:
            head += (f"这一房所出的未成年子女共{len(kids)}人，"
                     "已随本组档案一并给出；本板块写这一房的夫妻、子女与家中的事。")
        elif len(mates) <= 1:
            head += "本板块写这一房夫妻与家中的事。"
    return head + "\n\n" + (base_req or "")


# ---------------------------------------------------------------------------
# Article cap and material/importance gating
# ---------------------------------------------------------------------------
ARTICLE_MAX = 10
# Friend/enemy gate: events recorded for the subject himself; fewer than 3 leaves only padding.
SUBJECT_ART_MIN_EVENTS = 3
# Article priority (higher kept first), consulted only over the cap; picks keep their original order.
_ARTICLE_PRIO = {
    "benji": 100,      # annals
    "jiashi": 90,      # household
    "assassins": 84,   # assassins
    "secrets": 82,     # secrets
    "friend": 80,      # friend
    "enemy": 80,       # enemy
    "feuds": 76,       # family feuds
    "artifacts": 74,   # artifacts
    "liyi": 72,        # rites
    "chaoju": 70,      # dynasty chronicle (final article only)
    "youxia": 68,      # knights-errant (landless only)
    "qizu": 60,        # wife's kin
    "qunying": 50,     # court notables
}


def _subject_has_material(facts, cid):
    """True when facts.characters[<cid>].events holds at least SUBJECT_ART_MIN_EVENTS
    entries — the same pool the article body draws on; a missing profile counts as none."""
    if cid is None:
        return False
    p = (facts.get("characters") or {}).get(str(cid)) or {}
    return len(p.get("events") or []) >= SUBJECT_ART_MIN_EVENTS


def _liyi_has_material(facts):
    """Gate for the rites article: needs rite/rite_profile and >=2 rite_history entries,
    >=2 personal_tenets or a holy_order; rite_tenet_changes only feeds mid, not the gate."""
    if not (facts.get("rite") or facts.get("rite_profile")):
        return False
    return len(facts.get("rite_history") or []) >= 2 \
        or len(facts.get("personal_tenets") or []) >= 2 \
        or bool(facts.get("holy_orders"))


def _liyi_has_mid(facts):
    """True when the rites mid section has material: personal_tenets, holy_orders,
    rite_history or rite_tenet_changes (disjoint from the lead's rite_profile slice)."""
    return bool(facts.get("personal_tenets")) \
        or bool(facts.get("holy_orders")) \
        or bool(facts.get("rite_history")) \
        or bool(facts.get("rite_tenet_changes"))


def _liyi_has_tail(facts):
    """True when the third rites section (councils and papal bulls) has material:
    facts.church_chronicle, empty for a subject outside the Christian church."""
    return bool(facts.get("church_chronicle"))


def _liyi_req(facts):
    """Rites theme/section requirements built only from blocks actually sent: lead and tail align
    to facts.rite_profile / facts.church_chronicle line prefixes; focus omits holy orders (sent by
    mid alone) and the core-tenet topic (sent by the tail's own request; every section receives
    focus, and the mid carries no core-tenet material since v101)."""
    prof = [str(x) for x in (facts.get("rite_profile") or [])]

    def _has(prefix):
        return any(x.startswith(prefix) for x in prof)

    first = "所奉礼仪的名目"
    if _has("源自"):
        first += "与源流"
    if _has("礼仪领袖"):
        first += "、礼仪领袖为谁"
    tail = []
    if _has("核心教义"):
        tail.append("核心教义逐条点名")
    _fv, _sf = _has("宗教热情"), _has("灵性满足")
    if _fv and _sf:
        tail.append("宗教热情与灵性满足按档位词写出")
    elif _fv:
        tail.append("宗教热情按档位词写出")
    elif _sf:
        tail.append("灵性满足按档位词写出")
    if _has("个人教义"):
        tail.append("个人教义写出当前所奉的条目")
    lead = "写传主所受之礼：" + first + "。" \
        + ("".join(x + "，" for x in tail[:-1]) + tail[-1] + "。" if tail else "")

    mid_bits, focus_bits = [], []
    if facts.get("rite_history"):
        mid_bits.append("受礼、改礼、立礼的年月与缘由")
        focus_bits.append("受礼、改礼、立礼")
    if facts.get("personal_tenets"):
        mid_bits.append("他本人采纳个人信条的更替年份")
        focus_bits.append("个人教义之更替")
    if facts.get("rite_tenet_changes"):
        mid_bits.append("礼仪核心教义的演变")
        focus_bits.append("本礼核心教义之更替")
    if facts.get("holy_orders"):
        mid_bits.append("他建立或庇护的修会，逐所写出立会年份、会规、"
                        "所领教堂领地与现任首领")
    src = style.SECTION_REQ.get("liyi", {})
    # ---- tail: the church's councils and papal bulls ----
    # Only the lines actually sent are requested, matched against facts.church_chronicle.
    cc = [str(x) for x in (facts.get("church_chronicle") or [])]

    def _cc_hit(*needles):
        return any(n in x for x in cc for n in needles)

    tail_bits, tail_focus = [], []
    if cc:
        if any(x.startswith("教会局面") for x in cc):
            tail_bits.append("教会当下的局面")
            tail_focus.append("教会局面")
        if _cc_hit("举行大公会议"):
            tail_bits.append("大公会议的日期与主持者")
            tail_focus.append("大公会议")
        if _cc_hit("颁布教宗诏书"):
            tail_bits.append("教宗诏书的颁布者与日期")
            tail_focus.append("教宗诏书")
        if _cc_hit("教会大分裂", "对立教宗"):
            tail_bits.append("大分裂与对立教宗之立")
        if _cc_hit("异端爆发", "异端礼仪", "异端复兴", "新礼仪", "分歧礼仪"):
            tail_bits.append("异端之兴与新礼之立")
        if _cc_hit("将原先", "将「", "列为", "改为"):
            tail_bits.append("会议与诏书定夺的教义条目、旧新之别与定夺的年月")
            tail_focus.append("会议与诏书所定夺的教义")
        if _cc_hit("改本礼信条", "本礼信条更改"):
            tail_bits.append("本礼信条与禁忌的更替")
            tail_focus.append("本礼信条之更替")
        if _cc_hit("改本礼核心教义", "增定核心教义", "核心教义去"):
            # The tail's own request carries this topic; it stays out of `focus`, which every
            # section of the article receives, and the mid section no longer has core-tenet
            # material (v101 moved it here).
            tail_bits.append("本礼核心教义的更替与定夺者")
        if _cc_hit("大公教会地位"):
            tail_bits.append("本礼失去大公教会地位之事")
        if not tail_focus:
            tail_focus.append("教会局面")
    return {
        "lead": lead or (src.get("lead") or ""),
        "mid": (("写礼仪与教义的沿革、传主在教门中的作为：" + "；".join(mid_bits) + "。")
                if mid_bits else (src.get("mid") or "")),
        "tail": (("写本朝教会的大公会议与教宗诏书：" + "；".join(tail_bits) + "。"
                  "年月与人名一律照本篇给出的事实写出。")
                 if tail_bits else (src.get("tail") or "")),
        "focus": ("写礼仪的沿革与教门中的作为：" + "、".join(focus_bits)
                  + ("；并写大公会议与教宗诏书：" + "、".join(tail_focus)
                     if tail_bits else "")
                  if focus_bits else
                  ("写传主所受之礼、本朝教会的大公会议与教宗诏书"
                   if tail_bits else "写传主所受之礼与其教门中的作为")),
    }


def _apply_article_cap(articles):
    """Drop articles beyond ARTICLE_MAX, keeping the top-scoring ones per _ARTICLE_PRIO and
    logging the rest. Picks are re-sorted by index, so the surviving order is unaltered."""
    n = len(articles)
    if n <= ARTICLE_MAX:
        return articles
    keep = sorted(range(n),
                  key=lambda i: (-_ARTICLE_PRIO.get(articles[i]["key"], 0), i))
    keep = sorted(keep[:ARTICLE_MAX])
    dropped = [articles[i]["title"] for i in range(n) if i not in set(keep)]
    llm.log(f"[篇目] 候选 {n} 篇超过上限 {ARTICLE_MAX}，"
            f"按重要性保留 {ARTICLE_MAX} 篇，略去: {'、'.join(dropped)}")
    return [articles[i] for i in keep]


def build_articles(facts, cache, cfg):
    """Assemble the article list for cfg.bio_sections, gate it on material and cap it at
    ARTICLE_MAX; friend/enemy need SUBJECT_ART_MIN_EVENTS events, rites needs _liyi_has_material."""
    pid = facts.get("player_id")
    pname = (facts["protagonist"] or {}).get("name") or "主角"
    style_name = facts.get("bio_style") or "east"
    friend, friend_fallback = _pick_friend(cache, as_of=facts.get("as_of"))
    if friend is not None and friend_fallback:
        friend = None  # no real friend: a stand-in colleague only retells the protagonist
    enemy = _enemy_for_facts(facts, cache)
    fname = ""
    ename = ""
    if friend is not None:
        fp = facts["characters"].get(str(friend)) or {}
        fname = fp.get("name") or ""
    if enemy is not None:
        ep = facts["characters"].get(str(enemy)) or {}
        ename = ep.get("name") or ""
    sec_keys = [s for s in ("lead", "mid")]  # lead/mid only; the 太史公曰 verdict comes from the outline
    # household article wording varies with the material; decided once, see _jiashi_variant
    facts["_jiashi_variant"] = _jiashi_variant(facts, cache)

    def mk_sections(key):
        titles = style.SECTION_TITLES.get(key, {})
        _var = (style.JIASHI_VARIANTS.get(facts.get("_jiashi_variant") or "")
                if key == "jiashi" else None)
        # rites requirements come per block this article really carries (see _liyi_req)
        _dyn = (facts.get("_liyi_req") or {}) if key == "liyi" else {}
        if _var:
            titles = dict(titles)
            titles["lead"] = _var["lead_title"]
            titles["mid"] = _var["mid_title"]
        defaults = {"lead": "开篇", "mid": "纪事"}
        # Household mid is written group by group from two pools (spouse, child), capped at
        # facts.JIASHI_MID_MAX = 5 sections (6 with the lead), quota split by material weight; no groups → one block.
        if key == "jiashi":
            groups = facts.get("household_groups") or []
            mid_title = titles.get("mid") or defaults["mid"]
            kid_title = "诸子行迹"
            mid_req = _section_req((_var or {}).get("mid")
                                   or style.SECTION_REQ.get(key, {}).get("mid")
                                   or "按传记笔法写作。", facts)
            kid_req = _section_req((_var or {}).get("kid")
                                   or style.SECTION_REQ.get(key, {}).get("kid")
                                   or "按传记笔法写作。", facts)
            secs = [{"key": "lead",
                     "title": titles.get("lead") or defaults["lead"],
                     "req": _section_req(
                         (_var or {}).get("lead")
                         or style.SECTION_REQ.get(key, {}).get("lead")
                         or "按传记笔法写作。", facts)}]
            if groups:
                for i, g in enumerate(groups):
                    _kind = g.get("kind") or "spouse"
                    _is_kid = _kind == "child"
                    secs.append({
                        "key": (f"kid{i + 1}" if _is_kid else f"mid{i + 1}"),
                        "title": "%s·%s" % (
                            (kid_title if _is_kid else mid_title),
                            g.get("label") or ("第%d节" % (i + 1))),
                        "req": _mid_req_for_group(
                            kid_req if _is_kid else mid_req, i, len(groups), g),
                        "members": list(g.get("ids") or []),
                        "block_title": f"家室档案·{g.get('label') or ''}",
                    })
            else:
                secs.append({"key": "mid",
                             "title": mid_title, "req": mid_req})
            return secs
        if key == "chaoju":
            # One row per ruler, split by dynasty into <= facts.CHRONICLE_MID_MAX sections, current dynasty
            # last, each its own concurrent request; a protagonist-only title becomes a family chronicle.
            _dc = (facts.get("realm") or {}).get("dynasty_chronicle") or {}
            _periods = list(_dc.get("periods") or [])
            _fam = bool(_dc.get("family"))
            _src = style.SECTION_REQ.get(key, {})
            _lead_req = _section_req((_var or {}).get("lead") or _src.get("lead")
                                     or "按传记笔法写作。", facts)
            _mid_base = _section_req((_var or {}).get("mid") or _src.get("mid")
                                     or "按传记笔法写作。", facts)
            _ttl = dict(titles)
            if _fam:
                _ttl["lead"] = _ttl.get("family_lead") or _ttl.get("lead")
            secs = [{"key": "lead",
                     "title": _ttl.get("lead") or defaults["lead"],
                     "req": _lead_req}]
            if _fam:
                secs.append({"key": "mid", "title": _ttl.get("family_mid") or "纪事",
                             "req": _mid_base, "periods": _periods})
            else:
                # dynasties split as evenly as possible, the current one reserved for the last section.
                _cur = _dc.get("current") or {}
                _all = [p for p in _periods if _chrono_usable(p)]
                if _cur.get("rows") and _cur not in _all:
                    _all.append(_cur)
                _hist = [p for p in _all
                         if not (_same_period(p, _cur))]
                _cap = max(1, int(getattr(F, "CHRONICLE_MID_MAX", 4)))
                if _cur.get("rows") and _hist:
                    _parts = _chrono_split(_hist, cap=_cap - 1)
                    # the current dynasty is chunked per person too; its last chunk takes mid_last
                    # and closes at the protagonist's final year.
                    for _cp in _chrono_row_chunks(_cur):
                        _parts.append({
                            "name": _cp.get("name"), "start": _cp.get("start"),
                            "end": _cp.get("end"), "ids": list(_cp.get("ids") or []),
                            "rows": list(_cp.get("rows") or []),
                            "rows_detail": list(_cp.get("rows_detail") or []),
                            "rows_dates": list(_cp.get("rows_dates") or []),
                            "periods": [_cp]})
                else:
                    # the current dynasty is the only one: a single mid section, with no earlier split,
                    # else that one dynasty would be written twice.
                    _parts = _chrono_split(_all, cap=_cap)
                _n = len(_parts)
                _prev_cut = None
                for _i, _p in enumerate(_parts):
                    _last = _i == _n - 1
                    _is_last = bool(_last and _n > 1 and _p is _parts[-1]
                                    and _cur.get("rows"))
                    _base = (_section_req(style.SECTION_REQ.get(key, {}).get(
                        "mid_last"), facts) if (_last and _n > 1) else _mid_base)
                    _sec = {
                        "key": "mid%d" % (_i + 1),
                        "title": _ttl.get("mid%d" % (_i + 1)) or f"纪事·王朝历代·{_i + 1}",
                        "req": _chrono_mid_req(_base, _i, _n, [_p], last=_is_last),
                        "periods": [_p], "prev_cut": _prev_cut, "is_last": _is_last}
                    secs.append(_sec)
                    _prev_cut = _p.get("end") or _prev_cut
            return secs
        if key == "liyi":
            # Rites tail: the material gate lives in facts.church_chronicle; an empty mid still
            # gets a tail
            _src = style.SECTION_REQ.get(key, {})
            secs = [{"key": "lead",
                     "title": titles.get("lead") or defaults["lead"],
                     "req": _section_req(_dyn.get("lead") or _src.get("lead")
                                         or "按传记笔法写作。", facts)}]
            if _liyi_has_mid(facts):
                secs.append({"key": "mid",
                             "title": titles.get("mid") or defaults["mid"],
                             "req": _section_req(_dyn.get("mid") or _src.get("mid")
                                                 or "按传记笔法写作。", facts)})
            if _liyi_has_tail(facts):
                secs.append({"key": "tail",
                             "title": titles.get("tail") or "纪事·大公会议与教宗诏书",
                             "req": _section_req(_dyn.get("tail") or _src.get("tail")
                                                 or "按传记笔法写作。", facts)})
            return secs
        return [{
            "key": sk,
            "title": titles.get(sk) or defaults[sk],
            "req": _section_req(
                       _dyn.get(sk)
                       or (_var or {}).get(sk)
                       or style.SECTION_REQ.get(key, {}).get(sk)
                       or "按传记笔法写作。", facts),
        } for sk in sec_keys]
    articles = [
        {"key": "benji", "title": f"本纪·{pname}", "subject": None,
         "theme": "人物生平",
         "focus": "只写公开的行迹：家世、执掌的地方、战争与入狱、家中添丁",
         "sections": mk_sections("benji")},
    ]
    if friend is not None and not _subject_has_material(facts, friend):
        llm.log(f"[篇目] 好友 {friend} 行迹不足 {SUBJECT_ART_MIN_EVENTS} 条，"
                f"《列传·{fname or '好友'}》整篇略去")
        friend = None
    if enemy is not None and not _subject_has_material(facts, enemy):
        llm.log(f"[篇目] 仇人 {enemy} 行迹不足 {SUBJECT_ART_MIN_EVENTS} 条，"
                f"《列传·{ename or '仇人'}》整篇略去")
        enemy = None
    if friend is not None:
        articles.append({"key": "friend", "title": f"列传·{fname or '好友'}",
                         "subject": fname, "theme": "好友传记（最亲近同僚的一生）",
                         "focus": "只写传主的生平，主角只在两人交游处出场",
                         "sections": mk_sections("friend")})
    if enemy is not None:
        articles.append({"key": "enemy", "title": f"列传·{ename or '仇人'}",
                         "subject": ename, "theme": "仇人传记（一生劲敌）",
                         "focus": "只写传主一生的行迹与结仇的起因，叙述客观平实",
                         "sections": mk_sections("enemy")})
    # The household article's theme/focus follow the same material branch as its requirements, else a
    # wifeless, childless protagonist still gets a title promising a wife and children, and the model invents them.
    _jv = style.JIASHI_VARIANTS.get(facts.get("_jiashi_variant") or "") or {}
    articles.extend([
        {"key": "jiashi", "title": "家室列传", "subject": None,
         "theme": _jv.get("theme") or "妻室子女的家庭画卷",
         "focus": _jv.get("focus") or "写家中的内情：结婚、感情脉络、子女来历与血脉之争",
         "sections": mk_sections("jiashi")},
    ])
    # The chronicle article is titled by the protagonist's top title and spans the dynasties since the
    # campaign start; with no obtainable title (an adventurer camp only) the whole article is skipped.
    _rlm = facts.get("realm") or {}
    _dc = _rlm.get("dynasty_chronicle") or {}
    _ttn = _rlm.get("top_title_name") or ""
    # Only the final biography triggers this article (F._is_final_bio_spec: no decade, a death date and a
    # cut-off equal to that death date); the check is repeated here per article.
    try:
        _final = bool(F._is_final_bio_spec(facts))
    except Exception:
        _final = False
    if _final and (_ttn or _dc):
        _fam = bool(_dc.get("family"))
        _ttl = (_dc.get("name") or _ttn) if _fam else _ttn
        _t_fam = "家族历代" if _fam else "王朝的世代更替与改朝换代"
        _f_fam = ("按先世的辈分次序与他们持有的头衔，写家族的世代传承与传主的兴起"
                  if _fam else
                  "按各朝代的起止与历代统治者的继位缘由，写改朝换代、疆域归并与主角的起落")
        articles.append(
            {"key": "chaoju", "title": f"{_ttl}历代记", "subject": None,
             "theme": _t_fam, "focus": _f_fam,
             "sections": mk_sections("chaoju")})
    if facts.get("house_feuds"):
        articles.insert(4, {"key": "feuds", "title": "家族恩怨录",
                            "subject": None,
                            "theme": "与主角家族关系不和的家族恩怨",
                            "focus": "写仇怨的来龙去脉：开战、胜负、夺地、对方的处境与关系档位",
                            "sections": mk_sections("feuds")})
    if facts.get("family_artifacts"):
        articles.insert(5, {"key": "artifacts", "title": "宝物志",
                            "subject": None,
                            "theme": "主角家族所藏重宝的流转历史",
                            "focus": "写每件重宝的来历与流转，借宝物写人",
                            "sections": mk_sections("artifacts")})
    killed = facts.get("killed") or []
    if _has_assassins(facts):
        articles.append({
            "key": "assassins", "title": "刺客列传·刀下诸魂",
            "subject": None, "theme": f"被主角杀死的 {len(killed)} 人的合传",
            "focus": "为每名死者立小传：其生平、与主角的交集、死时的情形",
            "sections": _assassin_sections(len(killed))})
    if facts.get("protagonist", {}).get("landless"):
        articles.append({
            "key": "youxia", "title": "游侠列传·行纪",
            "subject": None, "theme": "漂泊不定的行旅记录",
            "focus": "按行程次序写漂泊：每到一地的时间、驻扎的地方、与当地势力的交集",
            "sections": mk_sections("youxia")})
    if facts.get("imperial_spouses"):
        articles.append({
            "key": "qizu", "title": "妻族传·帝胄姻亲",
            "subject": None, "theme": "妻族门第（公主头衔／中华皇帝之女·姐妹）",
            "focus": "写妻族门第与姻亲牵连（含妻室自身的经历）",
            "sections": mk_sections("qizu")})
    if facts.get("protagonist", {}).get("government") and \
            _is_admin(facts):
        articles.append({
            "key": "qunying", "title": "群英录·朝堂要员",
            "subject": None, "theme": "同朝要员的群像",
            "focus": "写同朝要员的名录与起落，以主角为参照",
            "sections": mk_sections("qunying")})
    # secrets article needs non-murder, family/retainer secrets or leverage; a murder-only run skips it
    if (facts.get("secrets") or {}).get("any"):
        articles.append({
            "key": "secrets", "title": "阴私录·隐事秘辛",
            "subject": None, "theme": "隐事与把柄（主人公不为人知的一面）",
            "focus": "写隐事的揭底：什么事、牵涉到谁、事情发生在哪一年、有谁知道",
            "sections": mk_sections("secrets")})
    # gated by _liyi_has_material: no rite, personal-tenet or holy-order evidence skips the rites article
    if _liyi_has_material(facts):
        # theme and requirements come from _liyi_req, which lists only blocks with data this run.
        _lq = _liyi_req(facts)
        facts["_liyi_req"] = _lq
        _anchor = 0
        for _i, _a in enumerate(articles):
            if _a.get("key") in ("jiashi", "feuds", "artifacts"):
                _anchor = _i + 1
        _secs = mk_sections("liyi")
        articles.insert(_anchor, {"key": "liyi", "title": "礼仪志·礼仪与教义",
                                  "subject": None,
                                  "theme": "传主所受之礼与个人教义的演变"
                                           + ("、本朝教会的大公会议与教宗诏书"
                                              if _lq.get("tail") else ""),
                                  "focus": _lq["focus"],
                                  "sections": _secs})
    elif facts.get("rite_profile"):
        llm.log("[篇目] 宗教面无实据 (无改礼、无信条更替、无修会)，"
                "《礼仪志》整篇略去 (本礼教义更替单独不作门槛, 见 `_liyi_has_material`)")
    # no church article: its material (the_christian_church) exists only in the 867 start.
    # cap: with more candidates than ARTICLE_MAX keep the top N by _ARTICLE_PRIO
    return _apply_article_cap(articles)

def _is_admin(facts):
    """True when the protagonist's government is administrative."""
    gov = (facts["protagonist"] or {}).get("government") or ""
    return gov in ("行政官制", "administrative_government")


def _names_path(cfg, cache):
    """Name-table path: prefers the per-campaign output/<family>/data/names.json over the
    global data/names.json, since character ids only mean anything inside one save."""
    folder = (cache or {}).get("output_folder") or ""
    if folder:
        p = os.path.join(cfg.get("output_dir", ""), folder, "data", "names.json")
        if os.path.isfile(p):
            return p
    return os.path.join(cfg.get("data_dir", ""), "names.json")


def reign_start(cache):
    """Accession date of the protagonist: the date on the player's own entry in
    cache["played_legacy"], used for the md header's reign field; '' when not in the chain."""
    pid = cache.get("player_id")
    if pid is None:
        return ""
    try:
        want = int(pid)
    except (TypeError, ValueError):
        return ""
    for e in cache.get("played_legacy") or []:
        if isinstance(e, dict) and e.get("cid") == want:
            return str(e.get("date") or "")
    return ""


def generate_biography(cache, melt, cfg, out_path=None, decade=None, as_of=None,
                       nickname_override=None, campaign=None):
    """Generate the biography Markdown, write it to out_path, return (md_text, facts, articles).
    decade/as_of pick the data cutoff at a decade end; nickname_override {cid: nickname}; campaign {player_id: cache}."""
    names_path = _names_path(cfg, cache)
    facts = F.build_facts(cache, melt, names_path, as_of=as_of, decade=decade,
                          nickname_override=nickname_override, campaign=campaign)
    articles = build_articles(facts, cache, cfg)

    intro_cfg = dict(cfg)
    intro_cfg["max_tokens"] = min(cfg.get("max_tokens", 12800), 1500)
    intro = llm.call_deepseek(build_intro_messages(facts, cfg, articles),
                              intro_cfg).strip()
    intro = llm.clean_number_spaces(intro)
    intro = llm.normalize_zh_punct(intro)
    # the intro is injected verbatim into every article lead, so kin-word slips are corrected first
    intro = _fix_kin_roles(intro, facts, cache)
    intro = _fix_person_names(intro, facts, cache)

    sec_cfg = dict(cfg)
    sec_cfg["max_tokens"] = min(cfg.get("max_tokens", 12800), 4000)

    def _draft_section(msg, sec_title, article_title):
        """Draft one section body, then check it with _tail_issue: a dangling bracket or
        unclosed emphasis means upstream truncation, so regenerate once, else trim the tail."""
        def _one(text):
            body = _fix_kin_roles(
                _normalize_section(text, sec_title, article_title), facts, cache)
            body = _fix_person_names(body, facts, cache)
            return body, _tail_issue(body)

        body, issue = _one(llm.call_deepseek(msg, sec_cfg).strip())
        if not issue:
            return body
        llm.log(f"板块《{sec_title}》末尾不完整 ({issue}) — 重生成一次")
        body2, issue2 = _one(llm.call_deepseek(msg, sec_cfg).strip())
        if not issue2:
            return body2
        llm.log(f"板块《{sec_title}》重生成后仍不完整 ({issue2}) — 裁尾部残迹, 该板块请复核")
        b1, _ = _trim_dangling_tail(body)
        b2, _ = _trim_dangling_tail(body2)
        return b2 if len(b2) >= len(b1) else b1

    def _gen_lead(article):
        try:
            msg = build_lead_messages(article, facts, cache, intro, cfg)
            body = _draft_section(msg, article["sections"][0]["title"],
                                  article["title"])
            body = re.sub(r"(?<!\n)\n(?!\n)", "\n\n", body)
            return article["key"], body
        except Exception as e:
            llm.log(f"首段《{article['title']}》生成失败: {e}")
            return (article["key"],
                    f"### {article['sections'][0]['title']}\n\n(本板块生成失败)")

    leads = {}
    with ThreadPoolExecutor(max_workers=len(articles)) as ex:
        futures = [ex.submit(_gen_lead, a) for a in articles]
        for fut in futures:
            k, body = fut.result()
            leads[k] = body

    def _gen_section(article, section):
        try:
            msg = build_section_messages(article, section, facts, cache,
                                         leads[article["key"]], cfg)
            body = _draft_section(msg, section["title"], article["title"])
            return article["key"], section["key"], body
        except Exception as e:
            llm.log(f"板块《{section['title']}》生成失败: {e}")
            return (article["key"], section["key"],
                    f"### {section['title']}\n\n(本板块生成失败)")

    sections = {}
    jobs = [(a, s) for a in articles for s in a["sections"][1:]]
    if jobs:
        with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futures = [ex.submit(_gen_section, a, s) for a, s in jobs]
            for fut in futures:
                ak, sk, body = fut.result()
                sections[(ak, sk)] = body

    md = _assemble(facts, intro, leads, sections, articles)
    # post-process fallback (idempotent): drop the protagonist's own roster line from the assassins article
    md, _n_dropped = _drop_subject_roster_lines(md, facts, articles)
    # final punctuation pass over the body only; the machine-readable header keeps its half-width colons
    md = llm.normalize_zh_punct(md)
    # squeeze adjacent duplicate words again over assembly seams; whitelist in _dedup_adjacent_words
    md = _dedup_adjacent_words(md)
    try:
        n = F.L.write_miss_report(cfg)
        if n:
            llm.log(f"本地化未命中键 {n} 个已记入 logs/loc_miss.log")
    except Exception:
        pass
    # unresolved trait display names land in the same audit log, so traits added by a new mod stay visible
    try:
        miss = F.trait_name_miss_report()
        if miss:
            _p = os.path.join(cfg.get("log_dir") or "logs", "loc_miss.log")
            os.makedirs(os.path.dirname(_p), exist_ok=True)
            with open(_p, "a", encoding="utf-8") as _fp:
                _fp.write(f"# 特质显示名未解析 {len(miss)} 个 "
                          f"(计 {sum(miss.values())} 次)\n")
                for _k, _n in sorted(miss.items(), key=lambda kv: (-kv[1], kv[0])):
                    _fp.write(f"{_n}\t{_k}\n")
            llm.log(f"特质显示名未解析 {len(miss)} 个已记入 logs/loc_miss.log")
    except Exception:
        pass
    st = F.sanitize_stats()
    if st.get("lines"):
        llm.log(f"干净事实兜底共丢弃 {st['lines']} 行 (含裸键), 样例: "
                f"{st.get('samples', [])[:3]}")
    # header comment keeps only the fields htmlview needs; a missing reign falls back to the birth year, so
    # the reading page can still sort and label the character.
    pp = facts["protagonist"] or {}
    person = pp.get("name") or facts.get("player_name") or ""
    birth = pp.get("birth") or ""
    reign = reign_start(cache)
    if decade:
        piece = f"第{decade}个十年传记"
    elif facts.get("player_death") or facts.get("reign_end"):
        piece = "终传"                    # abdication save keeps the same piece name
    else:
        piece = "传记"
    header = (f"<!-- 人物: {person} | 人物ID: {facts.get('player_id')}"
              + (f" | 战役ID: {cache.get('playthrough_id')}"
                 if cache.get("playthrough_id") else "")
              + (f" | 出生: {birth}" if birth else "")
              + (f" | 执政: {reign}" if reign else "")
              + f" | 篇目: {piece}"
              + (f" | 十年: {decade}" if decade else "")
              + " -->\n\n")
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(header + md.rstrip() + "\n")
        llm.log(f"传记已生成: {out_path}")
    return md, facts, articles
