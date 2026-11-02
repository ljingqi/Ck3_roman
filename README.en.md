# CK3 Family Chronicle · Biographical Saga Generator

[简体中文](README.md) | [English](README.en.md)

Reads your **yearly autosaves** from *Crusader Kings III* (CK3) and builds up a lifetime of
memories for the character you play. After the character dies, it automatically writes a
**five-part, magazine-style biographical saga** with DeepSeek, stores everything in
per-dynasty folders, and generates an **offline reading page** (double-click to browse in
your browser).

```
CK3 yearly autosave (.ck3)
  → melt to JSON with rakaly       output/<dynasty>/data/melt_<date>.json
  → extract memories, titles, kin, events
                                   output/<dynasty>/data/player_<player_id>.json
                                   (one per player, deduplicated across years)
  → detect character death (with identity checks to avoid false positives)
  → write with DeepSeek            output/<dynasty>/<name>_终传_<date>.md
  → generate reading page          output/<dynasty>/index.html
```

The program **only reads save files and writes to its own output directory**; it never
modifies game files or saves.

---

## 1. Prerequisites

| Requirement | Notes |
| --- | --- |
| **Windows** | Scripts and batch entry points are written for Windows (backslash paths; `.bat` files are GBK-encoded). |
| **Python 3.9+** | Install from the official installer and check "Add Python to PATH". |
| **CK3 base game** | The program must be able to read the game's `game/localization` and `game/common` to build lookup tables for Chinese names, titles, cultures, faiths, etc. |
| **rakaly.exe** | Third-party tool that melts `.ck3` saves into JSON. It is **not distributed with this project**; download it yourself. |
| **DeepSeek API Key** | Apply at <https://platform.deepseek.com>. Biography generation is billed per use. |

Install the Python dependencies:

```bat
pip install -r requirements.txt
```

Get rakaly.exe (either way):

1. Download the Windows `rakaly.exe` from rakaly's releases page and put it in this
   project's `tools\` directory;
2. Or put it anywhere and set the full path via `rakaly_path` in `config.json`.

---

## 2. Configuration

Copy `config.example.json` to **`config.json`** and fill in the fields below. `config.json`
contains your API key and is excluded by `.gitignore`, so it will not be committed.

```json
{
  "deepseek_api_key": "sk-your-key",
  "deepseek_model": "deepseek-chat",
  "ck3_game_dir": "",
  "rakaly_path": "tools/rakaly.exe"
}
```

| Field | Default | Notes |
| --- | --- | --- |
| `deepseek_api_key` | empty | **Required**, your DeepSeek key. |
| `deepseek_model` | `deepseek-chat` | Model name. |
| `deepseek_base_url` | official chat/completions | Change only when using a compatible endpoint. |
| `ck3_user_dir` | current user's `Documents\Paradox Interactive\Crusader Kings III` | Save directory root. |
| `save_dir` | `ck3_user_dir\save games` | Specific save folder. |
| `ck3_game_dir` | auto-detected | Game root (containing `game\`); fill manually if auto-detection fails. |
| `rakaly_path` | `tools\rakaly.exe` | Path to the rakaly executable. |
| `output_dir` | `output` under the project | Where biographies and caches are written. |
| `log_dir` | `logs` under the project | Run logs and prompt transcripts. |
| `poll_interval_seconds` | `3600` | watch-mode polling interval (seconds). |
| `max_tokens` | `12800` | Per-request output limit. |
| `temperature` | `1.1` | Generation temperature. |
| `llm_max_concurrency` | `6` | Maximum concurrent requests; lower it if the upstream reports "insufficient resources". |
| `prompt_log_enabled` | `true` | Write each request verbatim to `logs/prompts.log` (for troubleshooting; rotates after 5 MB). |
| `auto_bio_on_death` | `true` | Automatically generate a final biography when a character death is detected. |
| `carnal_opinions` | `false` | Include Carnalitas opinion events in the facts; off by default to shorten prompts. |
| `log_console_detail` | `false` | When `true`, print detailed archive-by-archive output to the console. |

**The first run requires building the lookup tables once (manual, one time).**
Double-click `重建对照表.bat` in the project root: the program scans the game and enabled
mods and generates all Chinese lookup tables (`data\*.json`, about 30 MB). The time depends
on disk and mod count.

**Subsequent starts do not rebuild tables automatically.** Rerun `重建对照表.bat` only in
these two cases:

- A game update (e.g. 1.19 → 1.20);
- Enabling or disabling mods in the launcher.

To check whether the three core tables match the game, run `python pipeline.py status`
(read-only, no rebuild). If a table is stale, the program keeps using the existing table
and prints a one-line notice.

---

## 3. Usage

### Start recording

Set autosave to **yearly** (`yearly` or more frequent) in the game, then double-click or
run the following in the project directory:

```bat
启动监控.bat
```

It is equivalent to `python pipeline.py watch`: at startup it records the current newest
save as the baseline and **only processes saves written after that**—old saves and other
campaigns in the folder are never read, so old saves cannot slip in. Each run creates a
new numbered output folder (e.g. `output\哈布斯堡2\`), so multiple playthroughs of the same
dynasty do not interfere with each other.

If you are already halfway through and want to backfill historical saves, use **continue**:

```bat
启动续传.bat
```

It reuses the newest folder, backfills saves newer than the cache in the current campaign,
then keeps watching.

### Command line

```bat
python pipeline.py watch [seconds]  :: new-save watch: process only saves written after startup
python pipeline.py continue [seconds]
                                    :: backfill: reuse the newest folder, backfill new saves
                                    :: from the current campaign, then keep watching
python pipeline.py scan             :: one-shot backfill: only new saves in the current campaign
python pipeline.py status           :: show each player's cache progress
python pipeline.py bio [player_id]  :: manually generate a biography (living or final)
python pipeline.py bio <id> --decade 3
                                    :: manually generate the 3rd decade biography
python pipeline.py rebuild-cache    :: rebuild caches from melts in each campaign folder
                                    :: (repair/migration)
python pipeline.py build-tables     :: manually rebuild all game/mod lookup tables
                                    :: (= 重建对照表.bat)
python pipeline.py build-tables --only=loc,traits
                                    :: rebuild only the specified tables
                                    :: (keys are filenames in data\<key>.json)
python pipeline.py index-melts      :: prebuild memory indexes for melts (speeds up lookups)
python pipeline.py compact [--gz]   :: compress archived cold melts (xz by default, smallest)
python pipeline.py migrate          :: migrate old directory layouts
python pipeline.py epilogue [dynasty]
                                    :: closing review: choose a campaign folder with the
                                    :: arrow keys and write a dynasty-wide review
python pipeline.py epilogue 洪氏2 --force
                                    :: specify a folder (--force overwrites an existing review)
```

### Generation cadence

- Every **10 years** (measured from the year recording began), a "decade N biography" is
  generated automatically.
- When a character **dies**, a final biography is generated automatically, ending with a
  program-generated **lineage** (pedigree + lineage chart + generation-by-generation
  lineage) and a **chronology of major events**.
- Both run in background threads; watching continues normally during generation, so no
  new saves are missed.

### Reading

Open `output\<dynasty>\index.html`: use the dropdown at the top right to switch characters;
the left panel lists all biographies for that character (decade N / final biography · died
in year). Everything is local; no internet connection is needed.

The **Family Tree** button at the top right switches to the dynasty-wide family tree: a
**pagoda-style** lineage chart—one generation per row, the founder at the top, flowing
downward like a tower; parent-child links are black lines, and the succession path between
adjacent protagonists and the protagonist beads are red. Use the **Branch N/M** menu in the
toolbar to select branches: each branch gets a row with a headcount and color swatch
(★ marks the protagonist's branch; "Solo" shows only that branch), plus "Select all / Keep
only protagonist's branch / Clear" and an **Include spouses** toggle; selections are
remembered per dynasty in the browser and restored next time. By default only the
protagonist's branch + protagonist line are selected, and its ancestors are kept
automatically so a single selected branch still connects upward to the founder. Click any
bead to collapse/expand its child branches; "All" / "Protagonist & spouse" / "Protagonist
only" / "Zoom in/out" narrow the chart; use "A-/A+" to adjust font size. Each final
biography's appendix still prints the **lineage** text.

After closing a campaign, double-click `封档总评.bat` (= `python pipeline.py epilogue`):
choose a campaign folder with the arrow keys; the program takes the newest save and writes
a **closing review**—part one summarizes the first chapters of the "Basic Annals" of each
protagonist, part two introduces the contemporary dynastic rulers (who they are, where they
rule, and how they are related to the current protagonist), with a program-generated roster
of same-dynasty rulers. Once written, a **Closing Review** button appears at the top right
of the reading page.

---

## 4. Directory layout

```
├── 启动监控.bat / 启动续传.bat   one-click entry points
├── 重建对照表.bat                manual table build (rerun after game update / mod change)
├── 封档总评.bat                  choose a campaign folder and write a dynasty-wide review
├── pipeline.py                   main command-line entry point
├── config.example.json           config template (copy to config.json)
├── data/                         game-side lookup tables (rebuildable)
├── tools/                        helper tools (put rakaly.exe here)
├── output/<dynasty>/             artifacts for each campaign
│   ├── data/                     melts, memory caches, snapshots, genealogy data
│   ├── <name>_终传_<date>.md     finished biography
│   └── index.html                reading page (with family tree)
└── logs/                         run logs
```

`output/`, `logs/`, `config.json`, and `cache/` are never committed.

---

## 5. What the biography looks like

### The five articles

| # | Title | Content |
| --- | --- | --- |
| 1 | *Basic Annals · <protagonist>* | Life story: family background, appointments, major events, current state |
| 2 | *Biographies · <friend>* | Biography of a close friend (if there is no friendship memory, the closest colleague) |
| 3 | *Biographies · <rival>* | Biography of a rival (chosen from rivalry memories) |
| 4 | *Biographies of the Household* | The household panorama of wives and children, including the wife's family standing |
| 5 | *Chronicle of the Court* | Ruler successions and the rise and fall of ministers, driven entirely by save data |

Depending on the data, additional articles may appear: *Biographies of Assassins*
(personally killed many), *Biographies of Wanderers* (landless adventurers), *Biography of
the Wife's Kin · Imperial In-laws*, *Register of Heroes · Court Dignitaries*, *Register of
Secrets · Hidden Affairs*, etc.

**Rite system**: when conditions are met, a *Rite Chronicle · Rites and Doctrines* article
is added. It covers the name and origin of the rite practiced, the rite's head, core
tenets, religious fervor, spiritual satisfaction, personal tenets, the history of personal
tenets and the rite, holy orders, and taboo personal beliefs; when cardinal and papal
election material exists, a "Cardinals and Papal Elections" chronicle is added. **It
appears only when there is evidence.**

### Two prose styles

The style is selected automatically from the character's de jure top-tier empire; both
require **modern written Chinese throughout**:

- **Eastern** (China, Japan, Korea, Vietnam, etc.) → a Chinese-style biography centered on
  the person, told in chronological order;
- **Other** → a Western-style biography interspersed with anecdotes and character detail,
  with commentary woven into the narrative.

The overview ends with an overall assessment; the other sections remain objective narrative.

### Clean facts

The model only receives **Chinese natural-language facts** rendered by the program:
characters are written as "surname + given name"; titles, cultures, faiths, traits, memory
types, and dates are all in Chinese. **No internal IDs, keys, or English enums enter the
prompt**, and none appear in the finished text.

---

## 6. Mods and localization

- The program reads the mods you currently have **enabled** (from the launcher config) and
  merges their localization into the lookup tables, so titles, traits, events, etc. added
  by mods automatically display in Chinese instead of English keys.
- **No manual action is needed after enabling a new mod or updating a mod**: a change in
  the source fingerprint automatically triggers a table rebuild on the **next start**
  (`watch` / `continue` / `scan` all run a self-check first and print the localization
  sources and the self-check result for the three core tables). To check status without
  rebuilding, use `python pipeline.py status`.
- To find out why a key is not showing the expected Chinese:

  ```bat
  python localization.py check      :: compare current source fingerprint with the recorded one
  python localization.py mods       :: list recognized mods and their localization coverage
  ```

- To rebuild a specific table manually (e.g. for troubleshooting):

  ```bat
  python localization.py build      :: localization master table
  python localization.py traits     :: trait names and trait tracks
  python localization.py positions  :: court/camp positions
  python localization.py council    :: council seats
  python localization.py dynasties  :: dynasties and house names
  python localization.py province   :: province → county mapping
  ```

- `All Under Heaven` (Mandate of Heaven / TGP) is **DLC content included with the base
  game**, not a mod; its scripts and localization live in the game's `game\` directory.

---

## 7. FAQ

**Q: Nothing happens after startup?**
A: `watch` only processes saves written **after startup**. Save once in-game (or wait for
the next yearly autosave).

**Q: It says rakaly is missing?**
A: Put `rakaly.exe` in `tools\`, or set the full path via `rakaly_path` in `config.json`.

**Q: The first run is very slow?**
A: Double-click `重建对照表.bat` once to build the tables (the time depends on disk and mod
count); after that, startup only reads the tables and does not rebuild.

**Q: Names are wrong after a game update or mod change?**
A: Double-click `重建对照表.bat` to rerun it; to check status only, use
`python pipeline.py status` (read-only self-check; prints whether the three core tables
match the game source fingerprint).

**Q: Generation stops or reports "upstream insufficient resources"?**
A: Lower `llm_max_concurrency` in `config.json` (e.g. 3) and rerun the same command.

**Q: I want to see exactly what the model received?**
A: `logs\prompts.log` records each request verbatim (controlled by `prompt_log_enabled`).

**Q: I found a factual error halfway through a biography?**
A: First inspect that player's cache and snapshot under `output\<dynasty>\data\`, then
decide whether to rebuild the cache (`python pipeline.py rebuild-cache`) or regenerate one
article (`python pipeline.py bio <player_id>`).

---

## 8. License

This project is released under **GPL-3.0**; see [LICENSE](LICENSE).

*Crusader Kings III* and related content are copyright Paradox Interactive. This tool is
only a helper for secondary creation based on personal saves and contains no original game
assets. rakaly is a third-party tool; follow its own license.
