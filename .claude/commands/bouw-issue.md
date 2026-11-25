---
description: Build a reviewed GitHub issue end to end - branch, code, tests, PR, and a test-drive report as an issue comment
argument-hint: <issue number>
---

Build GitHub issue #$ARGUMENTS of lammert/mhi2-aid-carplay without asking the owner, following `AGENTS.md`
("When building an issue" and "Temporary logging for the test drive"). Work through these steps in order. Stop only
where a step says so; when you stop, always post the issue comment of step 8 explaining why.

1. **Read.** `gh issue view $ARGUMENTS --comments`, plus every issue and PR it mentions (`#N`) with their status.
   If the issue has not been through the review (no "Doel / Gewenst gedrag / Acceptatiecriteria / Implementatie /
   Bouwen" structure), or a behaviour decision is still open: post a comment listing exactly what is missing, then stop.

2. **Branch.** `git fetch origin`, then create `issue-$ARGUMENTS-<short-slug>` from `origin/main`. If the issue depends
   on another issue whose PR is not merged yet, branch from that PR's branch instead and say so in the PR and comment.
   Never commit to `main`. If the branch already exists, continue on it.

3. **Plan.** Write a short plan (files, patch script, build ID, tests, logging decision of step 5) and keep it for the
   comment. Do not wait for approval.

4. **Build.** Implement per the issue's "Implementatie" section and the repository conventions (counted replacements,
   new build ID, host test printing `<NAME>_PASS`, `python3 -I`, README.md + README.pl.md, CHANGELOG "Unreleased").

5. **Logging decision.** Decide whether the test drive needs temporary extra logging, using the rules in `AGENTS.md`.
   Add it only when the decision says so, marked `TEMP-LOG(#$ARGUMENTS)`.

6. **Test.** Run the component's `build.sh` (and `installer/test/run_tests.sh` when the installer changed). Fix and rerun
   until every test passes; existing tests stay unchanged unless the issue says otherwise. If the local workspace is
   missing, say "code-only, not built" everywhere instead of claiming results. After three failed fix attempts on the
   same failure: commit what you have as WIP, post the comment with the failure output, and stop.

7. **Commit and PR.** Small commits with clear messages. `git push -u origin <branch>`, then
   `gh pr create --draft` with title `#$ARGUMENTS: <issue title>`, body ending in `Closes #$ARGUMENTS`.

8. **Report on the issue.** `gh issue comment $ARGUMENTS --body-file <file>`, in Dutch, with exactly this structure:

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
   Indien ja: aanzetten: … · bestand: … · uitlezen: … · waar op letten: … ·
   - [ ] Na de proefrit verwijderen (`grep -rn "TEMP-LOG(#…)"`)

   ### Open punten
   <of "geen">
   ```

Finish with a one-line summary in the terminal: branch, PR number, and whether it is ready for the test drive.
