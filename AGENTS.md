# Instructions for AI assistants

This file is for any AI assistant working on this repository (Claude, Claude Code, Codex, Copilot, Cursor, …).
`CLAUDE.md` imports it, so Claude Code reads it automatically.

The owner reviews every GitHub issue with an AI assistant **before** an assistant builds it. The goal of a review is an
issue that an assistant can build without guessing: every behaviour decision is made by the owner and written down,
and the issue says where in the code the change goes and how it is checked.

## The project in one paragraph

pmcp brings the CarPlay (and Android Auto) map and the native VW route guidance to the Active Info Display (AID) of
**one** car: VW Passat B8, Discover Pro MHI2 **MU1161**, AID part **791**. Most features are patches on the unit's own
Java HMI classes or on its iAP2 driver, installed from an SD card through the GEM engineering menu. The last check
for every feature is a drive in the car. Code paths already tested in the car are safer than paths that were never
tried on AID 791.

| Directory | What it is |
|---|---|
| `rg/` | Native route guidance (package `rg`): maneuver arrow, distance, lanes, distance bar, street name, ETA, for CarPlay and Android Auto. See `rg/README.md`. |
| `aa/` | Android Auto on the AID (feeder, hooks, MOST output). |
| `bridge/` | pmcp-most, our build of the CarPlay MOST bridge (experimental). |
| `hmiextras/` | Steering-wheel zoom and day/night for the AID map. |
| `nowplaying/` | CarPlay track title and artist on the AID. |
| `navactiveignore/` | NavActiveIgnore from the unit's own firmware classes. |
| `speedlimit/` | Native VW speed limits on the AID. |
| `ui/` | Settings page in the head unit menu (App-Connect > Settings). |
| `installer/`, `release/` | SD card, GEM scripts, rescue card, release packing. |
| `patches/`, `profiles/` | `core.so` patch, firmware profile (pinned hashes). |
| `docs/en/`, `docs/pl/` | Documentation (English and Polish). |

## Repository conventions (a build issue must respect these)

- **Nothing from VW firmware and no unpinned binaries in the repository.** Inputs live in a workspace next to the
  repository (`upstream/`, `backup/MU1161/`, `archives/`, see "Building" in `README.md`) and are checked by SHA-256.
- **Upstream files are pinned and copied unchanged.** Our changes to them are Python patch scripts that make counted
  text replacements on staged copies (each replacement must match exactly once), e.g. `rg/lanes/maneuvers.py`,
  `rg/lanes/v146.py`, `rg/lanes/component.py`. A new feature in `rg/` is a new script of this kind, registered in
  `rg/build.sh`, with a new build ID.
- **Every feature has a host test** that prints a `<NAME>_PASS` line, run by the component's `build.sh`. Existing tests
  keep passing unchanged unless the issue says which expectation changes and why.
- **Run Python with `python3 -I`.**
- **Documentation in two languages:** the component's `README.md` (English) and `README.pl.md` (Polish), and a line in
  `CHANGELOG.md` under "Unreleased".
- **Building needs the local workspace** (the unit's M.I.B. backup, upstream clones, converted `lsd.jar`, ASM 9.7).
  A cloud assistant cannot build or run the tests; it can write code and tests, and the owner runs the build on the Mac.
  An issue says which of the two is expected.
- Release cards and experimental cards are different: say whether a change is for both or for experimental only.

## How to review an issue

Do the review in the language of the issue (the owner writes issues in Dutch). Do not change the issue on GitHub
yourself unless the owner asks; deliver the review in the conversation. One exception: the **issue type** (see
step 1), which you set yourself when it is missing.

### 1. Read everything first

- The issue, its comments, and every issue or PR it mentions (`#N`), with their status.
- Look for **dependencies between issues**, also circular ones (#1 waits for #2 and #2 waits for #1). Propose an order
  and make each issue buildable on its own: the later issue carries the dependency, the earlier one does not.
- **Check the issue type.** Every issue must have a GitHub issue type (the type field, not a label): `Feature` for
  new or changed behaviour, `Bug` for something that does not work as it should, `Task` for work without a change in
  behaviour (documentation, build, cleanup). Read it with
  `gh api repos/lammert/mhi2-aid-carplay/issues/N --jq '.type.name'`. When it is missing, choose the type from the
  issue text and set it right away with `gh api -X PATCH repos/lammert/mhi2-aid-carplay/issues/N -f type=Feature`
  (or `Bug` / `Task`). When the issue text fits no type clearly, ask the owner instead of guessing. When the type is
  present but looks wrong, do not change it: name it as a finding. Report in the review which type the issue has and
  whether you set it.

### 2. Find the code

- Name the component(s) and read their `README.md`.
- Find the place where the change goes (file, class or method, patch script) and the tests that cover it today.
  Quote what you found, with paths. Never guess a code location: if you cannot find it, say so.
- Note existing behaviour that touches the same output (in `rg/`: arrow, distance, lanes, distance bar, street name,
  HUD, placeholder, reroute / CALC_ROUTE, quiet-route hold, Android Auto path).

### 3. Check the issue against this list

For each point, either the issue already answers it, or you write it down as a finding with your recommendation.

1. **Goal**: is it clear why the change is wanted, in one or two sentences?
2. **Exact behaviour**: thresholds with unit and boundary (`> 5000 m` vs `≥`), which values come from where (phone,
   VW, setting), display units (km / mi).
3. **Choice of symbol, text or field**: when several VW elements could do it, list them and prefer the one already
   tested in the car; mark untested ones as a risk.
4. **Stability**: no flicker around a threshold (hysteresis or latching), behaviour on reroute, on a jump in distance,
   on a lost phone connection.
5. **Side effects on everything else shown**: other fields on the AID, the HUD, lanes, distance bar, street name,
   destination bar. For each: changes, or stays as it is.
6. **Special states**: no valid data, placeholder, recalculating, arrived / destination, quiet hold, phone switch.
7. **Sources**: CarPlay, Android Auto, or both; wired and wireless CarPlay.
8. **Fixed or configurable**: a constant now, a setting on the `ui/` settings page later (usually out of scope).
9. **Acceptance criteria**: concrete, testable, with numbers (a host test case and a drive in the car).
10. **Existing tests**: which must keep passing unchanged; which expectations change, and why.
11. **Implementation hint**: where the change goes and how it follows the conventions above.
12. **Build and test environment**: local build by the owner or code-only by a cloud assistant.
13. **Out of scope**: what this issue deliberately does not do (often: the related issue).
14. **Issue type**: present and fitting (step 1). The issue type replaces type labels such as `enhancement` or `bug`.
15. **Labels**: one component label named after the directory (`rg`, `aa`, `bridge`, `hmiextras`, `installer`,
    `ui`, …).

### 4. Deliver the review

In this order:

1. **Findings**: a short numbered list, the most important first. Each finding says what is missing or unclear, the
   options, and your recommendation. Decisions are the owner's: recommend, do not decide.
2. **Proposed issue text**: the full rewritten issue in one Markdown code block, ready to paste, with your
   recommendations filled in so the owner only edits where they decide otherwise. Use this structure (headings in the
   issue's language; Dutch shown):

   ```markdown
   ## Doel
   ## Gewenst gedrag
   ## Acceptatiecriteria
   - [ ] …
   ## Implementatie (voor de bouwende assistent)
   ## Bouwen
   ## Buiten scope
   ```

3. **Issue type** (already present, or set by you during this review), **labels** to add, and the dependency order
   with related issues.

Keep facts and recommendations apart. Anything you could not check (a symbol never shown on AID 791, a field the phone
may not send) is named as unverified, not stated as fact.

## When building an issue

Build only issues that have been through this review (they have the structure above). Follow the "Implementatie" and
"Bouwen" sections, keep to the repository conventions, and report which acceptance criteria were checked by tests and
which still need the drive in the car.

The owner starts a build with one request and then prepares the test drive from GitHub alone. Work through the steps
below without asking. This works in any assistant:

- **Claude Code**: `/bouw-issue N` (`.claude/commands/bouw-issue.md` points here; `.claude/settings.json` allows the
  commands these steps need).
- **Codex and other assistants**: "Bouw issue #N volgens AGENTS.md". Configure the tool so it may run `git`, `gh` and
  the build scripts in this repository; the limits below apply whatever the tool allows.

**Limits, always:** never commit or push to `main`, never merge, never force-push, never close or edit an issue (only
comment). The owner merges after the test drive.

### Steps

Stop only where a step says so. When you stop, still post the comment of step 8, with the reason and what the owner
has to do.

1. **Read.** `gh issue view N --comments`, plus every issue and PR it mentions (`#N`) with their status. If the issue
   has not been through the review (no "Doel / Gewenst gedrag / Acceptatiecriteria / Implementatie / Bouwen"
   structure), or a behaviour decision is still open: post a comment listing exactly what is missing, then stop.
2. **Branch.** `git fetch origin`, then create `issue-N-<short-slug>` from `origin/main`. If the issue depends on
   another issue whose PR is not merged yet, branch from that PR's branch instead and say so in the PR and the comment.
   If the branch already exists, continue on it.
3. **Plan.** Write a short plan (files, patch script, build ID, tests, logging decision of step 5) and keep it for the
   comment. Do not wait for approval.
4. **Build.** Implement per the issue's "Implementatie" section and the repository conventions (counted replacements,
   new build ID, host test printing `<NAME>_PASS`, `python3 -I`, `README.md` + `README.pl.md`, `CHANGELOG.md`
   "Unreleased").
5. **Logging decision.** Decide whether the test drive needs temporary extra logging, following "Temporary logging for
   the test drive" below. Add it only when the decision says so.
6. **Test.** Run the component's `build.sh` (and `installer/test/run_tests.sh` when the installer changed). Fix and
   rerun until every test passes; existing tests stay unchanged unless the issue says otherwise. If the local workspace
   is missing, write "code-only, not built" everywhere instead of claiming results. After three failed fix attempts on
   the same failure: commit what you have as WIP, post the comment with the failure output, and stop.
7. **Commit and PR.** Small commits with clear messages. `git push -u origin <branch>`, then a draft PR titled
   `#N: <issue title>` whose body ends in `Closes #N` (`gh pr create --draft`).
8. **Report on the issue.** One comment with `gh issue comment N --body-file <file>`, in Dutch, complete without the
   terminal output, with exactly this structure:

   ```markdown
   ## 🔧 Build-rapport
   **Branch:** `…` · **PR:** #… (draft) · **Build-ID:** … · **Kaart:** release / experimenteel
   **Status:** klaar voor proefrit | gestopt: <reden>

   ### Wat is er veranderd
   <2-5 regels, in gewone woorden>

   ### Tests
   - `…_PASS` (nieuw) / bestaande tests ongewijzigd geslaagd: …

   ### Acceptatiecriteria
   | Criterium | Gecontroleerd door |
   |---|---|
   | … | ✅ hosttest `…` / 🚗 proefrit |

   ### Proefrit-checklist
   - [ ] <concreet scenario: bron (CarPlay bedraad/draadloos, Android Auto), situatie, wat je op het AID moet zien>

   ### Tijdelijke logging
   **Ja/Nee** — <waarom>.
   Indien ja: aanzetten: … · bestand: … · uitlezen: … · waar op letten: …
   - [ ] Na de proefrit verwijderen (`grep -rn "TEMP-LOG(#…)"`)

   ### Open punten
   <of "geen">
   ```

Finish with a one-line summary to the owner: branch, PR number, and whether it is ready for the test drive.

### Temporary logging for the test drive

For every build, decide whether the drive needs temporary extra logging, and give the decision and its reason in the
issue comment. Add logging when an acceptance criterion can only be judged in the car and the existing logs would not
show why it failed, for example:

- the behaviour depends on data the phone sends that the host test only simulates (a field Apple Maps or Android Auto
  may not send, wired vs wireless CarPlay);
- a threshold, latch or timer decides what is shown (log the value and the decision at each change, not every message);
- a VW symbol, field or setting is used that was never shown on AID 791 before.

Rules for temporary logging:

- **Reuse what exists first**: `guidance-evidence.txt` (`rg/lanes/GuidanceEvidence.java`, read by `rglast.sh`), the
  `/ramdisk/pmcp-kombi-view.log` pattern (`rg/kv/`), "CP save log" / "AA save log" and the log card
  (`installer/logcard/`). A new file only when none of these fits.
- **Bounded and cheap**: a line per state change, a fixed maximum (rotate to `.1` as `KombiView` does), never on the
  iAP2 receive thread per message, in `/ramdisk` or `/dev/shmem`, never in `/mnt/persist`.
- **Privacy**: never street names, addresses, destination text or coordinates; numbers, states and enums only.
- **Experimental card only**, unless the issue says otherwise.
- **Marked and testable**: every added line carries `TEMP-LOG(#N)` in a comment, and the host test checks the log line
  format so a typo cannot cost a drive.
- **In the comment**: how to switch it on (if gated), which file, how to read it out (GEM button or log card), what to
  look for, and an unchecked box "remove after the test drive" with `grep -rn "TEMP-LOG(#N)"`.
