# Plan: Pinellas `pinellas-r1` (the fixes the review requires before anyone outside sees the map)

Status: **approved by the owner 2026-10-08** ("Agree to all": every §2 default and E13's cap, as written).
Built from `docs/07-review-pinellas-r0.md` (five reviews, verified in round 2)
and `docs/08-outreach-program.md` §2 (preconditions P1-P6). Every number here is the review's, cited by finding id; the
plan adds none of its own. Where the review left a decision to the owner (`docs/07` §6), this plan **proposes** a
default; the owner accepted all of them on 2026-10-08, and §2 now records them as decisions.

## 1. What r1 is

The second edition of the Pinellas table: same pipeline, same county, fixing what the review found in the first
edition's **definitions, population and disclosure** (its arithmetic, datum chain and provenance held up, `docs/07` §4).
It is accepted when the outreach preconditions P1-P4 are true of the published table and the gate (new form, §4)
passes. It ships as a new spatia-data pin of the same two pilot layers (one more pass of that repo's harness, `docs/05`
§10).

Not in r1: other counties (plan `docs/04` phase 2), NFHL `DEPTH` / `WTR_NM` / preliminary-FIRM / LOMA **data** (needs
spatia-data layer changes, §6), the legal reads (owner's, §6), new lidar (none exists in 3DEP for Pinellas, S8).

## 2. Decisions

| # | Question (`docs/07` §6) | Decision (owner, 2026-10-08) | Why |
|---|---|---|---|
| Q1 | Which floor is the product's floor? | **both, named per row.** `floor_definition` on every row (`first_living_floor` / `lowest_floor`); `ffe_ft` and `bfe_call` stay the first living floor (the insurance "first floor height" sense, and the only floor the model can predict); record rows add `lowest_floor_ft` (certificate C2a) and `bfe_call_lowest_floor`; modeled rows get `bfe_call_lowest_floor = null, not_determinable` | M1: 434 of 462 checkable `above` calls on elevated-with-enclosure houses are `below` on the lowest floor; a floodplain manager's question is the lowest floor, a buyer's is the living floor |
| Q2 | Does a certificate that fails the lidar screen produce a call? | **no.** `bfe_call = null`, `bfe_call_null = not_determinable`, value kept in `ffe_ft` with `record_note`; basis token `record_lidar_conflict` retired | M3: 244 `above` vs 2 `below` from conflict rows; on the 63 test labels the screen removes, model MAE is 19 ft: these are not this footprint's floors. `too_close` would assert a nearness that is not known |
| Q3 | Ground definition | **ring median**, water and sentinel cells masked. `ground_ft` = ring median; `ground_ring_min_ft`, `ground_ring_range_ft`, `ground_suspect` published; model target retrained on `ffe − g_med` | G1: surveyed LAG vs ring median MAE 0.51 ft, vs ring minimum 0.81 ft; 12.9 % of surveyed LAGs sit below the minimum; the minimum is the canal on 770 waterfront lots and drives 35 % of all raised flags on sloped lots |
| Q4 | Rebuild r0 now for the label sort (I1) and stage filter (S2), or carry to r1? | **carry to r1**: one re-pin, one spatia-data harness pass. The disclosure items (§3 A) ship to the viewer and docs now without a re-pin | a re-pin costs a full harness pass; r1 is weeks, not months (§5) |
| Q5 | Is a construction-drawings / under-construction certificate ever `record`? | **no.** `record` only for `finished_construction`; the other stages are kept as `record_stage` + `record_note` and the row falls back to the model (as rejected certificates do today); excluded from labels | S2: 572 such rows, 524 in the SFHA, calls above 308 / below 210 on values that are designs, not measurements |
| Q6 | ODbL and FDEM / Forerunner legal read | owner's; **tags made honest now**: `fdem_certificates:terms_unread` → `fdem_certificates:forerunner_internal_noncommercial` (what the survey found), `provider` must not read `public` on those rows | S3 |
| Q7 | Preliminary FIRM in r1? | a **county-level note now** (`firm_status` column: `effective 2021-08-24; preliminary 2025-05-15 pending; 3 effective dates in county`), the data in the release after r1 (§6) | S4, G4 |
| Q8 | Freeze the r0 test blocks? | **yes, as a permanent benchmark**, plus a stable hash split for every new block (§4) | M7, r1b report §5: redrawing the split put 1,139 of 1,782 gate houses in blocks r0 had trained on |
| Q9 | Can spatia-data carry NFHL `DEPTH` and `WTR_NM`? | ask (§6); r1 does not wait: AO → `bfe_null = not_evaluated`; interpolation gets the review's own rule that needs no new column (segment inside the building's SFHA polygon) | G2, M4 / G3 |
| Q10 | Certificate OBJECTIDs in the viewer record? | **drop from the browser JSON** (kept in the table); also drop `parcel_id_native` from the browser record | I6: resolvable to owner names on the public FDEM layer |

Still the owner's, unchanged from `docs/04` §8 and `docs/05` §9: no floor-count / foundation columns, FDEM values
published with tags, model and interpolation allowed, FEMA parents declared (withdraw before a FEMA release).

## 3. Work, in the review's order (`docs/07` §5)

Progress (2026-10-08, first batch): A1-A5 shipped to the r0 viewer and docs (the spatia-data sidecar note of A1 is
the one open piece); B1-B3 and B5's FDEM extract (`fetch_fdem.py`, on R2) are in `labels.py`; E2, E3, E7 and E10 are
in `assemble.py`, checked on a dev build with the r0 model (`--model-dir data/flood_v1/train_r0 --out
data/flood_v1/assemble_dev`): every `check.py` rule passes, 0 `record_lidar_conflict` calls (307 nulled), 0
`raised_flag` contradictions on record rows, records only from finished-construction certificates (571 fall back).
r0's training artefacts are frozen in `data/flood_v1/train_r0/` (the gate baseline and the benchmark's source).
Then: F1 (ruff clean), D1 (`split_12103.json`; r0's 102 test blocks reproduced byte-equal), D2 (gate v2; self-test:
same model passes, halved q fails), B4 (combined labels finished-only: 8,231; county "ACTUAL" stage excluded, not shown
to mean finished). A1's spatia-data note is written and reviewed (spatia-data branch `claude/zen-wright-m851wi`,
`09f1d36`) but its `refresh-metadata` is refused: the live manifest is at contract 2.29, published 2026-10-08 20:09 UTC
from another session's unmerged branch (`claude/issue-resolution-fewdn8`), and this checkout is 2.28. It runs once
2.29 is on spatia-data `main`.

Then (2026-10-08, evening), all measured by the commands named:
- **C1** `lidar/reground.py` → run `pinellas_2018_r1g`: the unmasked minimum reproduces r0's ground on all 290,540
  buildings; two water constants found (−0.60956 m west, −0.24416 m east; the second is −0.80 ft, above the −1.5 ft
  floor, so only the constant rule catches it); 468 rings masked, 81 grounds now `not_determinable`. On 7,483
  certificate lots: certificate LAG vs masked ring median MAE **0.508 ft** (median −0.15), vs r0 ring minimum 0.813
  (median +0.44). Accepted. Open: two tiles have a positive mode (0.78764 m, 0.40614 m; likely flattened lakes) that
  the approved rule does not mask; not yet measured how many rings touch them.
- **C3 / D3** candidates on the new ground (`train.py --out`), gate v2 vs r0 (`pipeline/train/out/gate_12103_r1dev-*.json`),
  benchmark 1,236 FDEM houses: `train_r1m` (combined labels, Mondrian bands): MAE 0.985 vs 0.981 (CI −0.06..+0.08),
  BFE side **0.913 vs 0.899** (CI +0.002..+0.025), coverage **0.902 vs 0.922** (CI −0.030..−0.009), decided correct
  0.983 vs 0.983; truly raised & unflagged coverage 0.657 (n 70) vs 0.485 (n 33) on the combined benchmark; flagged
  band median 12.5 vs 15.3 ft. The coverage fall is the new ground (the FDEM-only candidate shows it too, 0.900), not
  the labels. **The gate fails only on coverage**, because r0 over-covered (0.922 against the 0.90 target).
  → owner decision G-a below.
- **E-items** on a dev build (`assemble.py --model-dir data/flood_v1/train_r1m --out data/flood_v1/assemble_dev`):
  all 79 `check.py` rules pass (E1-E4, E9, E13, C2, parcel key). Stale modeled floors (E6) 3,872; AO BFEs removed
  (E4) 54; calls nulled for conflicts (E2) 161; bands capped at the roof (E13) 3; record rows whose living floor is
  above the BFE and lowest floor below (E1) 750; `ground_suspect` 20,392 (range > 3 ft: 20,353).
- **E8** as written (path inside the building's SFHA, ≤ 1 % outside) keeps 1,384 interpolated BFEs (r0: 5,250).
  Held-out FEMA BFE lines (each predicted from the others) by the limit on the share of path outside the SFHA:

  | limit | buildings interpolated | lines predicted | hold-out MAE ft | within 1 ft |
  |---|---|---|---|---|
  | 0.01 | 1,384 | 99 | 0.395 | 0.909 |
  | 0.10 | 1,826 | 129 | 0.454 | 0.899 |
  | 0.25 | 2,665 | 171 | 0.468 | 0.871 |
  | 0.50 | 3,856 | 270 | 0.453 | 0.878 |
  | none | 5,132 | 450 | 0.440 | 0.882 |

  The error barely moves with the limit; the rule mostly removes coverage. → owner decision G-b below.

Owner decisions, 2026-10-08 (answered after the table above): **G-a: coverage against the target** (option 1;
`gate.py` now passes coverage when the candidate's benchmark coverage >= 0.90 minus its own bootstrap sd and >= 0.88
everywhere; MAE, BFE side, decided correct and truly-raised-unflagged coverage stay baseline-relative). **G-b: E8
limit 0.25.** Re-run: `gate.py --candidate data/flood_v1/train_r1m --baseline data/flood_v1/train_r0` **passes**
(benchmark FDEM coverage 0.902 vs target - sd 0.889; combined 0.896 vs 0.889; truly raised & unflagged coverage CI
on combined +0.003..+0.340); self-test still OK. Dev build with the 0.25 limit: 2,665 interpolated BFEs; held-out FEMA
lines MAE 0.468 ft, 87.1 % within 1 ft, 99.4 % inside the band (n 171); all 79 `check.py` rules pass; SFHA decided
share 0.442.

The questions as they were put:
- **G-a, gate coverage rule.** As approved, any fall in coverage below the baseline is a regression, so a candidate
  calibrated to the 90 % target fails against r0's over-covering 0.922. Options: (1) judge coverage against the target
  (pass when ≥ 0.90 − the bootstrap sd and ≥ the 0.88 floor) instead of against the baseline; (2) keep the rule and
  calibrate r1 to r0's coverage (wider bands); (3) keep the rule and r0.
- **G-b, E8 limit.** Strict (1 %, as written) or a looser limit from the table.

Each item names the finding, the files, and what "done" is. Acceptance numbers are measured by the named command, never
copied from this doc.

### A. Disclosure now (no re-pin; viewer + docs + spatia-data metadata refresh)

| Item | Finding | Change | Accepted when |
|---|---|---|---|
| A1 | DA1 | Accuracy card shows BOTH scores with their populations: FDEM held-out (n 1,315: 1.039 / 0.918 / 0.898 / 0.983) and county-certificate (n 1,282: 2.22 / 0.884 / 0.861 / 0.951; elevated 5-9 MAE 3.14, unflagged coverage 0.539), and the line "band not guaranteed for unflagged elevated houses" until M2 ships. Same in `docs/06`, `assemble.py` parquet `gate` metadata, `coverage.py` county card, and the spatia-data sidecar notes (`refresh-metadata --only fl_building_first_floor`, a small spatia-data pass) | `pipeline/train/r1b_eval.py` re-run writes both score rows; the viewer card and `county.json` carry them; spatia-data sidecar notes quote them from the parquet metadata |
| A2 | DA3 | Handoff §8 regenerated from run13; hash suffix `…d6a93b7`; confirm the spatia-data roster pin was typed from the file | `sha256sum` of the pinned file equals the handoff and `config.FL_BUILDING_FIRST_FLOOR_ROSTER` |
| A3 | I6, Q10 | `pipeline/viewer/export.py`: drop `cert_objectid`-bearing strings (`ffe_source`, `ffh_source`, `record_note` keep the diagram and stage, lose the OBJECTID), `parcel_id_native`, from the browser `rec` JSON | a grep of the exported JSON for `OBJECTID` returns 0 |
| A4 | P5 | Viewer: known-limitations page (the review's §2 four reasons, in plain words), datum / geoid line on every card ("NAVD88 ft, US survey, GEOID12B; certificates: geoid not stated"), "screening, not a determination" on every page, `parcels_at_centroid > 1` shown as "condo / stacked parcel" (G8), a per-building **flag** button that writes to `data/inbox/viewer_flags/` through the Worker (owner-only until logins exist) | Playwright test on the live domain: page present, card lines present, a flag round-trips to R2 |
| A5 | DA4 / I2 | `docs/06`: parcel counts are per unit; `check.py` asserts `(parcel_key, geom_group)` unique | `check.py` passes with the new rule |

### B. Labels (`pipeline/train/labels.py`, `pipeline/labels_pinellas/`)

| Item | Finding | Change | Accepted when |
|---|---|---|---|
| B1 | I1 | "Latest wins" made true: `sort_values(["issuedAt", "OBJECTID"], na_position="first", kind="stable")` at both the property and the building stage; the rule documented in the docstring; the phase-0 counters use the same rule | re-run reports how many selections changed vs r0 (the review measured 357 at this rule; the number is re-measured, not copied) |
| B2 | S2 | Fetch `buildingElevationSource` with the labels; `record_stage` kept per label; **labels = finished_construction only** | labels json reports the stage counts (review: finished 6,889 / under construction 289 / drawings 236 / null 47 on record rows) |
| B3 | M1 | Fetch C2a (`topOfBottomFloor`) for every label regardless of diagram, plus FDEM's enclosure / vent fields where the layer has them (A8 / A9 equivalents; the fetch script lists the field names it found) | labels parquet carries `lowest_floor_ft` and the vent fields (nullable) |
| B4 | S9, M2 | County certificate layer (`pipeline/labels_pinellas/build.py`, already written): combined labels with the dedupe rule (county replaces FDEM only when both dated and county strictly later; FDEM wins ties), native-NAVD88 rows only, finished-construction only | `labels_combined_12103.parquet` rebuilt; counts re-measured (r1b: 8,931 combined, 1,416 new buildings, 763 new diagram 5-9) |
| B5 | S5 | Keep the FDEM extract (`data/fl/ec_all.json`) and the county extract on R2 under `_flood/inputs/` with fetch date and count; record them in the parquet `prov` | `prov.inputs` lists FDEM, county layer, WESM, Geocodio and the LLM model with dates |

### C. Ground (`pipeline/lidar/features.py`, `job.py`; local re-run of the DEM stage)

| Item | Finding | Change | Accepted when |
|---|---|---|---|
| C1 | G1 / DA2 | `ground_stats`: mask ring cells `< −1.5 ft NAVD88` and the hydro-flattened constant (the most frequent value in the tile, when it is below 0) before min / p10 / median / max; emit `ring_n_masked`. Re-run the ground stage locally on the 22 Pinellas DEM tiles (3.46 GB download; 114 s on the box in r0); point-cloud heights are offsets from `lag` and are re-based arithmetically (`h_new = h_old + (lag_old − ground_new)`), no point-cloud re-run | `features.parquet` rebuilt; on the 7,482 certificate lots, surveyed LAG vs new `ground_ft` MAE is reported (review's ring median: 0.51 ft) and must be below the ring-minimum figure (0.81 ft) |
| C2 | G1 | `assemble.py`: `ground_ft` = ring median; new `ground_ring_min_ft`, `ground_ring_range_ft`, `ground_suspect` (range > 3 ft, or min < 0 ft NAVD88, or `ring_n_masked` > 0, or `ring_low_share` high; the rule is stated in `docs/06`); `ground_null = not_determinable` where every ring cell was masked; `ffh / ffe` null on those rows | `check.py` rule: no `observed` ground on a masked ring; counts of `ground_suspect` reported |
| C3 | G1 | Model target = `ffe − g_med` (train.py); record `ffh_ft` stays certificate floor − certificate LAG, so both columns are "floor above the surveyor's grade" | `train.py` docstring states the target; the r1 report shows record-vs-modeled `ffh` grade difference on the labelled rows (r0: +0.44 ft median) |

### D. Train, bands, gate (`pipeline/train/`)

| Item | Finding | Change | Accepted when |
|---|---|---|---|
| D1 | M7, Q8 | **Stable split**: `pipeline/train/split_12103.json` persists each 1 km block's part. r0's blocks keep their r0 assignment (the r0 test blocks become the **benchmark**); every block first seen in a later batch is assigned by a hash of its id (`sha256(block_id)` mod 100: < 20 test, < 40 cal, else fit). `train.py` reads the file, adds new blocks, never changes an existing entry | the r0 benchmark blocks are byte-equal to `bands_12103.json.test_blocks` of r0; the new blocks' split sizes are reported |
| D2 | M7 | **Gate v2** (`gate.py`): scores baseline and candidate on (a) the r0 benchmark houses and (b) all held-out houses, each on FDEM labels and on the combined labels (DA1); reports the **paired block-bootstrap** 95 % bound of each difference and gates on it (a regression is a bound that excludes zero the wrong way), keeping the absolute coverage floor 0.88; prints the marginal sd for reference (review: MAE 0.047, coverage 0.008; paired 0.013 / 0.0033) | self-test as in r0 (same model passes; halved q fails); the r0 → r1 gate json carries all four tables |
| D3 | M2 | Bands by **predicted regime** (Mondrian on p: ≤ 1.5, 1.5-3, > 3 ft; q per group on CAL), the r1b `D` options re-run on the new target and the combined labels; the **conditional-coverage table** (truly raised & unflagged, diagram 5-9 unflagged, slab truly raised, each n) printed by `train.py` and shown on the accuracy card | unflagged truly-raised coverage reported with n (r0: 0.543, n 70); a choice is made by the owner from the table, with its width cost on the county (r1b: D2 widened the median unflagged band from 1.9 to 2.7 ft) |
| D4 | M6 | Ship the model q was calibrated for: either the FIT-only model, or cross-conformal (CV+) q for the FIT + CAL model; report coverage on all matched labels, screened and unscreened | the r1 report states which and the measured cost (r0: FIT-only MAE 1.064 vs 1.039) |
| D5 | M8 | Accuracy card carries `raised_flag` precision / recall from the benchmark (r0: 0.656 / 0.741; slab 0.487); flag definition unchanged (3 ft) unless D3 changes it | printed by `train.py` |

### E. Assemble (`pipeline/assemble/assemble.py`, `docs/06`)

| Item | Finding | Change | Accepted when |
|---|---|---|---|
| E1 | M1, Q1 | `floor_definition`; `lowest_floor_ft` (+ class / source / vintage / null) and `bfe_call_lowest_floor` on record rows; `docs/06` caveats `bfe_call` as a living-floor call; viewer card shows both | `check.py`: `floor_definition` set on every row with a floor; the two calls agree where diagrams 1A / 1B / 5 (one floor) |
| E2 | M3, Q2 | Conflict certificate → `bfe_call` null `not_determinable`; `record_lidar_conflict` basis retired; the screen gains `|cert LAG − ground_ft| > 3 ft` (DA6) | basis counts show 0 `record_lidar_conflict`; the number of calls nulled is reported |
| E3 | V1 | `raised_flag` from the record `ffh_ft` where `ffh_class = record` | 0 record rows where the flag contradicts the record height (r0: 708 + 381) |
| E4 | G2 | `zone_main = AO` → `bfe_null = not_evaluated` (until `DEPTH` exists); never a sliver BFE for an AO building | 0 AO buildings with a BFE from a sliver (r0: 54) |
| E5 | I3 | `sfha_area_m2`, `sfha_sliver` (< 1 m²); FEMA's touch rule kept; no interpolation through a sliver | counts reported (r0: 754 sliver buildings, 7 zone-A through an AE sliver) |
| E6 | S1 | `year_built` > lidar flight end → `ffh / ffe_null = stale`, `built_after_lidar = true`; roof / eave / ground kept with a pre-construction note | r0 measured 3,772 modeled rows; re-measured |
| E7 | S2, Q5 | `record_stage`; `record` only for finished construction; others fall back to the model with `record_note` | stage counts reported |
| E8 | M4 / G3 | Interpolation: the L1→L2 segment must lie inside the building's SFHA polygon(s), else `not_determinable`; prefer same `source_type`; validate by **holding out riverine BFE lines** (drop one line, predict it from its neighbours) and report that error separately from the coastal static check | the new check reports riverine n and MAE; rows lost to the rule are counted (r0: 2,050 rows with > 25 % of the segment outside) |
| E9 | I4 | One `why_not` table per row reused by every floor column; `model_version` only where `ffh_class = modeled` | `check.py`: the 3 / 144 / 7,264 inconsistencies of r0 are 0 |
| E10 | S3, Q6 | Honest licence tags (`fdem_certificates:forerunner_internal_noncommercial`; `provider` not `public` on those rows; Geocodio source strings as returned) | tags listed in `docs/06` |
| E11 | S4, G4, Q7 | `firm_status` (county-level note: effective and preliminary FIRM dates), `firm_effective_date` already per row; `docs/06` names the three effective dates and their counts | column present on every row |
| E12 | S6, G5, DA8, M5 | Interpolated `bfe_precision_ft` from the band; `docs/06` states: highest-BFE rule and that straddling lots use the VE BFE; record calls use the 2021 FIRM BFE, not the certificate's; the two standards of proof (`>=` for record, band for modeled) with `floor_minus_bfe_ft` as the margin | doc lines present; `bfe_precision_ft` non-null on interpolated rows |
| E13 | DA7 | Bands wider than the roof: `ffh_band_hi` capped at `roof_ft` with a note, or the row nulled `not_determinable` (owner, 2026-10-08: cap and note) | 0 bands above the roof |

### F. Hygiene (`pyproject.toml`, `tests/`)

| Item | Finding | Change | Accepted when |
|---|---|---|---|
| F1 | I5 | `pyproject.toml` (ruff line length 120, mypy), `ruff check` and `ruff format --check` clean on `pipeline/` and `viewer/` | both commands exit 0 |
| F2 | I5 | The review's minimum test set (`review/pinellas-r0/implementation.md` §5, a-h): null-reason branches, the call rules, band arithmetic, the label sort, the ground mask (metres in, ftUS out), `check.py` as a pytest, the Worker path regex (`..`, `%2e`, long ids), the gate self-test | `pytest` green in CI-less form (a `make test` / `uv run pytest`) |

### G. Release

| Item | Change | Accepted when |
|---|---|---|
| G1 | `assemble.py … --release pinellas-r1`; `check.py`; `coverage.py`; `export.py`; viewer `RELEASE = pinellas-r1` | every A-F acceptance line holds on the r1 table; the gate v2 report is committed |
| G2 | spatia-data: re-pin the roster (sha256, size, rows, release, model_version), prose counts re-measured, new columns declared (`ColumnDef` for each), both FEMA parents still at the live release, harness: plan amendment → build → review → live-review → publish `--only` + `publish-terms --apply` | published entries `version = pinellas-r1`, certify PASS, `/live-review` LIVE-READY |
| G3 | Handoff §11; `docs/07` §5 items marked shipped with their measured numbers; `docs/08` §2 P1-P6 ticked | — |

## 4. The gate, restated (answers Q8)

- **Benchmark**: the 102 r0 test blocks (`bands_12103.json.test_blocks`, 1,315 FDEM houses + whatever combined labels
  fall in them) are never trained or calibrated on again. Every release reports its score on them: the one number that
  is comparable across releases.
- **New held-out**: every block that first appears with a later label batch is split by hash (20 / 20 / 60), so each
  batch keeps its own 20 % held out (plan `docs/04` decision 13) without reshuffling anyone else's.
- **Pass rule**: on the benchmark, paired block-bootstrap 95 % bound of (candidate − baseline) must not show a regression
  in MAE, BFE side, coverage or decided-correct; absolute coverage ≥ 0.88 on both label sets; the conditional-coverage
  table is printed and the unflagged truly-raised row must not fall. The fixed tolerances of r0's gate are kept as a
  floor, not the test.
- **Both label sets** are scored (FDEM; FDEM + county), each with its population stated.

## 5. Order and timing against `docs/08`

| When | What | Outreach gate |
|---|---|---|
| first | A (disclosure), B1-B2, E2-E3, E10 — table and doc changes, no retrain | guided demos may continue (owner present) |
| then | C (ground re-run), B3-B5, D1-D2 | — |
| then | D3-D5 (retrain), E1, E4-E9, E11-E13, F | — |
| then | G1-G2 (gate passes, re-pin, spatia-data harness) | **P1-P4 true → first reviewer login** (`docs/08` §2) |
| in parallel | §6 external asks | `docs/08` track A letters by 2026-10-31 do not depend on r1 |

No dates are promised here: the review's items are counted, not timed. The ASFPM abstract (2026-11-02) needs A1's two
scores and D3's conditional-coverage table, which exist before r1 ships.

## 6. External asks (not blocking r1)

1. **spatia-data**: `fema_bfe_context` to carry NFHL `WTR_NM` (and `S_XS.WTR_NM`); `fema_flood_zones` to carry `DEPTH`
   and `VELOCITY`; Prelim_NFHL as a second zone set; LOMAs (NFHL layer 34) as a layer. Each is a spatia-data plan of
   its own.
2. **Owner / counsel**: ODbL (Collective vs Derivative Database) and FDEM-via-Forerunner vs chapter 119 (`docs/08` A6).
3. **Pinellas County**: the ch. 119 requests in `docs/08` track A (certificates index, SD determinations, LOMAs, the
   county's own lidar).

## 7. Risks

1. **The retrain moves the benchmark the wrong way.** Changing the target (C3), the labels (B1-B4) and the bands (D3)
   at once makes a regression hard to attribute. Mitigation: D2's gate scores every intermediate model (r0 target +
   new labels; new target + old labels) so the report shows which change moved what.
2. **The ground mask changes `ground_ft` on rows a floodplain manager already saw** in a demo. Mitigation: release
   notes list the count and the viewer shows `ground_ring_min_ft` beside the new value.
3. **spatia-data's FEMA parents move before r1 ships.** Then the pilot must be withdrawn first (`docs/05` §10) and r1
   re-assembled against the new release; the plan's E-items do not change.
4. **The county certificate layer ends mid-2020** (S9), so B4 does not help post-Helene buildings; E6 marks them `stale`
   honestly, and the outreach letters are the only route to newer records.
