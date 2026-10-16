# -*- coding: utf-8 -*-
"""Campaign epilogue: the closing assessment of a sealed campaign.

Part 1 reads the first chapter of every 终传 of the campaign (`## 1、《本纪·…》`) and reviews the whole
line of protagonists in generation order; part 2 lists the same-dynasty rulers alive in the latest
save — who they are, which branch they belong to, how they are related to the protagonist the campaign
closed on, and what they are like — and the model writes them up from the roster this module builds.
Both parts share one system prompt, so the prefix cache hits for the second call.

Everything the program can settle deterministically (dates, names, titles, seats, kin words, the canon
of protagonists) is settled here and handed over as material; the model turns it into prose.
"""
import io
import os
import re

import cache_lib as cl
import llm
import style

FINAL_RE = re.compile(r"^(.+)_终传_(.+)$")
HEADER_RE = re.compile(r"<!--(.*?)-->", re.S)
H_PERSON = re.compile(r"人物:\s*([^|]+)")
H_ID = re.compile(r"人物ID:\s*(\d+)")
H_REIGN = re.compile(r"执政:\s*([\d.]+)")
H_PIECE = re.compile(r"篇目:\s*([^|]+)")
FIRST_RE = re.compile(r"^## 1、《(.+?)》\s*\n(.+?)(?=\n## |\Z)", re.M | re.S)
PIECE_RE = re.compile(r"^## \d+、《(.+?)》", re.M)
EPILOGUE_RE = re.compile(r"^(.+)_封档总评_(\d{4}_\d{2}_\d{2})\.md$")


def _cn(date_str):
    """A game date as the reader sees it (`llm.fmt_cn_date`: 1121.1.1 -> 1121年). Every date this
    module writes into a part, a byline or an appendix heading goes through here; only the
    machine-readable header field (`存档: 1121.1.1`) and the file name keep the game format,
    since the tools and `v119_check_epilogue` parse them."""
    return llm.fmt_cn_date(date_str) if date_str else ""


def chapters(folder_dir):
    """The campaign's 终传 in generation order, each with its first chapter (《本纪》).

    rows: [{file, person, cid, reign, end, piece, pieces, first_title, first, chars}]; the reign date
    in the header gives the order, since the file names carry the end date.
    """
    rows = []
    for fn in sorted(os.listdir(folder_dir)):
        if not fn.endswith(".md"):
            continue
        m = FINAL_RE.match(fn)
        if not m:
            continue
        try:
            with io.open(os.path.join(folder_dir, fn), encoding="utf-8") as fp:
                text = fp.read()
        except OSError:
            continue
        head = HEADER_RE.search(text)
        head = head.group(1) if head else ""
        person = H_PERSON.search(head)
        cid = H_ID.search(head)
        reign = H_REIGN.search(head)
        piece = H_PIECE.search(head)
        first = FIRST_RE.search(text)
        rows.append({
            "file": fn,
            "person": (person.group(1).strip() if person else m.group(1)),
            "cid": int(cid.group(1)) if cid else None,
            "reign": reign.group(1) if reign else "",
            "end": m.group(2).replace(".md", "").replace("_", "."),
            "piece": piece.group(1).strip() if piece else "",
            "pieces": PIECE_RE.findall(text),
            "first_title": first.group(1) if first else "",
            "first": " ".join((first.group(2) if first else "").split()),
            "chars": len(text),
        })
    rows.sort(key=lambda r: (cl.date_key(r["reign"]) if r["reign"] else cl.date_key(r["end"]),
                             r["file"]))
    return {"rows": rows, "chars": sum(len(r["first"]) for r in rows)}


def epilogue_file(folder_dir):
    """Newest existing 封档总评 of a folder: (path, date slug) or (None, None)."""
    best = None
    for fn in os.listdir(folder_dir):
        m = EPILOGUE_RE.match(fn)
        if m and (best is None or m.group(2) > best[1]):
            best = (os.path.join(folder_dir, fn), m.group(2))
    return best if best else (None, None)


# ---------------------------------------------------------------------------
# Part 2 roster: same-dynasty holders alive in the latest save
# ---------------------------------------------------------------------------

def roster(facts, rank_min=2, ref_cid=None):
    """Same-dynasty holders alive at `as_of`, highest tier first.

    The clan (宗族/dynasty) is the grouping the user asked for, so every house of it counts. Landed
    titles of county tier and above form the main list; camp leaders, barons and the untitled are kept
    in `others` so the caller can widen the report when `rows` comes out short.

    `ref_cid` is the person the kin words are read against: the last 终传's protagonist, so the
    roster speaks of the family as it stood when the campaign closed. Without it the newest cache's
    player takes that place (the campaign's own protagonist).
    """
    as_of = facts.as_of or facts.cache.get("last_date")
    pid = facts.cache.get("player_id")
    ref = pid if ref_cid is None else ref_cid
    house = facts._house_of_cid(pid)
    dyn = facts.cache.get("dynasty_id") or (cl.dynasty_id_of(facts.melt, house) if house else None)
    rows, others, alive = [], [], 0
    for key in facts._chars:
        cid = int(key)
        if facts._dynasty_of_cid(cid) != dyn:
            continue
        if not facts._alive_at(cid, as_of):
            continue
        alive += 1
        tier, tid = facts._primary_title_at(cid, as_of=as_of)
        landed = bool(tid is not None and facts._is_landed_title(tid))
        item = {
            "cid": cid,
            "label": facts.person_label(cid, as_of, "full"),
            "house": facts._house_label_at(cid, as_of),
            "house_branch": facts.house_branch_label(cid, as_of),
            "traits": facts.traits_sentence(cid, public=True),
            "tier": tier,
            "rank": facts._eff_rank(tid) if tid is not None else 0,
            "landed": landed,
            "title": facts.title(tid, as_of) if tid is not None else "",
            "title_kind": facts.title_kind(tid) if tid is not None else "",
            "seat": facts.artifact_home(cid, as_of),
            "kin": "" if cid == ref else (facts.kin_word_for(cid, ref) or ""),
            "is_ref": cid == ref,
            "gen": facts.generation_delta(pid, cid) if cid != pid else 0,
            "independent": bool(facts._is_independent(cid, as_of)),
        }
        (rows if (landed and item["rank"] >= rank_min) else others).append(item)
    # unknown kin distance (generation_delta None) sorts after the known ones, same tier first
    rows.sort(key=lambda r: (-(r["rank"] or 0),
                             r["gen"] if isinstance(r["gen"], int) else 99, r["label"]))
    others.sort(key=lambda r: (-(r["rank"] or 0), r["label"]))
    prot = (facts.cache.get("characters") or {}).get(str(pid)) or {}
    return {
        "dynasty_id": dyn,
        "dynasty_name": cl.dynasty_name_zh(facts.melt, dyn) if dyn else "",
        "house": house,
        "house_label": facts._house_label_at(pid, as_of) if pid else "",
        "as_of": as_of,
        "rows": rows,
        "others": others,
        "alive": alive,
        "ref": {"cid": ref, "name": _ref_name(facts, ref, as_of)},
        "protagonist": {"cid": pid,
                        "name": facts.person_label(pid, as_of, "full"),
                        "house": prot.get("house") or facts._house_label_at(pid, as_of) or ""},
    }


def _ref_name(facts, cid, date=None):
    """The reference protagonist's name as part 2's roster writes it: no title, the nickname kept,
    and for a western name order the surname dropped once the nickname leads the name — 征服者威廉
    instead of 征服者威廉·诺曼底. '' when the character is unknown."""
    if cid is None:
        return ""
    nm = facts.name_with_regnal(cid, date) or ""
    nick = facts.nickname(cid)
    if nick and nm.startswith(nick):
        head, sep, _tail = nm.partition("·")
        if sep:
            return head
    return nm


def _roster_line(r, ref_name=""):
    """One ruler as one line: <reference protagonist>的<kin><label>，属<house>，为人<traits>。

    The kin word is read against the last 终传's protagonist (see `roster`), so a reader of the
    sealed campaign sees every living ruler through the eyes of the man it closed on. The house
    clause is written only for a branch (see `Facts.house_branch_label`); the reference protagonist
    himself, a ruler whose tie cannot be read, and nameless ties start the line with the label."""
    head = r["label"]
    if ref_name and r.get("kin") and not r.get("is_ref"):
        head = f"{ref_name}的{r['kin']}{head}"
    bits = [head]
    if r.get("house_branch"):
        bits.append(f"属{r['house_branch']}")
    if r.get("traits"):
        bits.append(f"为人{r['traits']}")
    return "- " + "，".join(bits) + "。"


def roster_text(rep):
    ref_name = (rep.get("ref") or {}).get("name") or ""
    return "\n".join(_roster_line(r, ref_name) for r in rep["rows"])


def others_titled(rep, limit=24):
    """The sub-county holders worth printing: those with a title of any kind, capped at `limit`."""
    other = [r for r in rep["others"] if r["rank"] or r["title"]]
    return other[:limit], len(other)


def roster_others_text(rep, limit=24):
    """Untitled or sub-county holders, for the fallback when the landed list is short."""
    other, total = others_titled(rep, limit)
    ref_name = (rep.get("ref") or {}).get("name") or ""
    out = [_roster_line(r, ref_name) for r in other]
    if total > limit:
        out.append(f"（另在世同宗 {len(rep['others']) - limit} 人，多为无地或未受封者）")
    return "\n".join(out)


def _strip_lead_headings(text):
    """Drop the headings the model may open a part with: the assembly writes the part titles."""
    lines = text.strip().split("\n")
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    return "\n".join(lines[i:]).strip()


# ---------------------------------------------------------------------------
# Prompts and file assembly
# ---------------------------------------------------------------------------

def _chain_line(ch):
    return " → ".join(f"{r['person']}（{_cn(r['reign'] or r['end'])}）" for r in ch["rows"])


def shared_block(ch, rep, folder):
    """The prefix both parts share: the clan, the canon of protagonists and the save in use."""
    prot = rep.get("protagonist") or {}
    fam = prot.get("house") or rep.get("dynasty_name") or folder
    return (f"【家史】{fam}｜宗族：{rep.get('dynasty_name') or '—'}｜传主 {len(ch['rows'])} 代\n"
            f"【历代传主】{_chain_line(ch)}\n"
            f"【存档】{_cn(rep['as_of'])}（最新存档）｜今生传主：{prot.get('name') or '—'}")


def _first_chapters(ch):
    blocks = []
    for i, r in enumerate(ch["rows"], 1):
        blocks.append(f"〔第{i}代〕{r['person']}（{_cn(r['reign'] or r['end'])}继位，{_cn(r['end'])}止）"
                      f"《{r['first_title']}》\n{r['first']}")
    return "\n\n".join(blocks)


def part1_messages(ch, rep, folder, rule_block):
    """[system, user] of part 1: the first chapter of every 终传, in generation order."""
    p = style.PROMPTS
    sys_msg = p["epilogue_system"].format(rule_block=rule_block)
    user = p["epilogue_part1_user"].format(
        shared=shared_block(ch, rep, folder),
        n=len(ch["rows"]),
        chain=_chain_line(ch),
        chapters=_first_chapters(ch))
    return [{"role": "system", "content": sys_msg}, {"role": "user", "content": user}]


def part2_messages(ch, rep, folder, rule_block, roster_override=None):
    """[system, user] of part 2: the program-built roster of same-dynasty holders."""
    p = style.PROMPTS
    sys_msg = p["epilogue_system"].format(rule_block=rule_block)
    table = roster_override if roster_override is not None else roster_text(rep)
    user = p["epilogue_part2_user"].format(
        shared=shared_block(ch, rep, folder),
        protagonist=(rep.get("ref") or {}).get("name")
                    or (rep.get("protagonist") or {}).get("name") or "—",
        dynasty=rep.get("dynasty_name") or "—",
        n=len(table.split("\n")) if table else 0,
        as_of=_cn(rep["as_of"]),
        roster=table or "（本次存档中，同宗在世者皆无领地与头衔）")
    return [{"role": "system", "content": sys_msg}, {"role": "user", "content": user}]


def header_comment(folder, ch, rep, pid):
    """The HTML comment every article carries, so the reading page and the tools can identify it."""
    prot = (rep.get("protagonist") or {}).get("name") or ""
    return (f"<!-- 篇目: 封档总评 | 家族: {folder} | 人物: {prot} | 人物ID: {pid} | "
            f"存档: {rep['as_of']} | 终传: {len(ch['rows'])} 篇 -->")


def assemble(folder, ch, rep, part1, part2, pid):
    """The written Markdown: header, byline, the two parts, and the program's roster as appendix."""
    fam = (rep.get("protagonist") or {}).get("house") or folder
    prot = (rep.get("protagonist") or {}).get("name") or ""
    body = [
        header_comment(folder, ch, rep, pid),
        f"# 《{fam}封档总评》",
        "",
        f"> 家族：{folder}｜宗族：{rep.get('dynasty_name') or '—'}｜传主：{prot}｜"
        f"存档：{_cn(rep['as_of'])}｜终传：{len(ch['rows'])} 篇",
        f"> 历代传主：{_chain_line(ch)}",
        "",
        "---",
        "",
        "## 一、历代总述",
        "",
        _strip_lead_headings(part1),
        "",
        "## 二、当世同宗诸统治者",
        "",
        _strip_lead_headings(part2),
        "",
        "---",
        "",
        f"## 附：同宗统治者名册（{_cn(rep['as_of'])} 存档，程序产物）",
        "",
    ]
    table = roster_text(rep)
    if table:
        body.append(table)
    else:
        body.append("（本存档中同宗在世者皆无领地与头衔）")
    loose, n_title = others_titled(rep)
    if loose:
        body += ["", f"### 其余在世同宗（其中有头衔者 {n_title} 人；同宗在世共 {rep['alive']} 人）",
                 "", roster_others_text(rep)]
    body += ["", f"<!-- 名册依据: {rep.get('dynasty_name') or ''}宗族｜"
                 f"在世 {rep['alive']} 人｜有地者 {len(rep['rows'])} 人 -->", ""]
    return "\n".join(body)


def output_name(folder, as_of):
    """output/<家族>/<家族>_封档总评_<存档 Y_MM_DD>.md"""
    slug = str(as_of or "").replace(".", "_")
    m = re.match(r"^(\d{4})_(\d{1,2})_(\d{1,2})$", slug)
    if m:
        slug = f"{m.group(1)}_{int(m.group(2)):02d}_{int(m.group(3)):02d}"
    return f"{folder}_封档总评_{slug}.md"
