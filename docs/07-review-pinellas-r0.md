# Review of the first edition: Pinellas `pinellas-r0` (2026-10-08)

Status: **review complete; nothing fixed yet.** The owner decides which findings go into r1 (§6). The edition reviewed is
assemble run13, `data/flood_v1/assemble/buildings_12103.parquet`, sha256 `ecea7173…d6a93b7` (the handoff §10 wrote
`…a6d93b7`, a transposition), published 2026-10-08 as spatia-data `fl_building_first_floor` / `_footprint`.

## 1. How the review was done

Five independent reviews, each in a clean context with one angle, each bound by the repo rule that every number comes
from a command actually run (the reports and every script and output are committed under `review/pinellas-r0/`):

| Angle | Report | What it covered |
|---|---|---|
| Data sources, vintages, licences | `review/pinellas-r0/sources.md` | every input and its edition, terms pages fetched, vintage mismatches, the unused county certificate layer, FEMA preliminary / LOMA data, personal data and secrets in git |
| Methodology and statistics | `review/pinellas-r0/methodology.md` | gate reproduction from the saved artefacts, conformal validity, subgroup coverage, label selection, the call rules, BFE interpolation, the gate's power, the raised flag |
| Implementation | `review/pinellas-r0/implementation.md` | every pipeline file and the viewer; arithmetic recomputed from the table's own columns; units and CRS; joins; null reasons; a byte-identical retrain; lint and tests |
| GIS domain | `review/pinellas-r0/gis.md` | datum / geoid chain, projected CRSs, DEM ring vs surveyed grade, FEMA zone semantics (AO, VE, LiMWA, slivers, FIRM dates), interpolation geometry, footprints, coverage map |
| Live data audit | `review/pinellas-r0/data_audit.md` | 89 numeric claims in the handoff / schema / outputs checked against the table; row-level consistency; distributions; spatial patterns; a fresh held-out score against the Pinellas county certificate layer; viewer data |

Round 2: two verifiers re-derived every blocking / major finding with their own queries (and spot-checked the rest),
settled the contradictions between reviewers, and re-graded severities (`review/pinellas-r0/verification.md`,
`review/pinellas-r0/verification_gis.md`). Of the 37 findings in the first four reports, 31 were confirmed, 5 partly
(framing or a sub-number), 1 refuted (the hash "match"), none fabricated; all 8 GIS findings were confirmed (one partly:
the AO detail), and the GIS verifier added one finding of its own (V1). Severities below are **after** round 2.

Severity: **blocking** = a value or claim that would mislead a floodplain manager or a buyer reaches them today;
**major** = a real defect that changes results or trust; **minor** = drift or gap; **note** = observation.

## 2. Verdict

The edition is internally honest and reproducible: every arithmetic rule holds on all 372,764 rows, the gate numbers
reproduce exactly from the saved artefacts, the training is byte-identical on re-run, the datum / CRS / unit chain is
right, licence and provenance tags are truthful per row, and no personal data or secret is in git. As a **screening
product shown with its caveats, it is fit for a guided demo**.

It is **not yet fit to put in front of a floodplain manager unguided, or in front of a buyer**, for four reasons that
the table itself does not disclose:

1. **The published accuracy is not the accuracy on the population a floodplain manager cares about.** Scored against
   1,282 Pinellas county certificates the model never saw (post-1992 floodplain buildings, mostly elevated), the
   modeled floor has MAE 2.22 ft, 90 % band coverage 0.884 and BFE side 0.861, against the published 1.04 / 0.918 /
   0.898; for elevated houses the model does not flag, the band covers 54 %. The previous session had measured this
   (`pipeline/train/out/r1b_eval_12103.json`) and it reached neither the handoff nor the viewer card.
2. **Three sets of values are presented as what they are not**: lidar "ground" that is the water surface,
   a seawall base or a canal bottom on 770 waterfront buildings (and a ring minimum that sits below the surveyed grade
   on 12.9 % of certificate lots, flagging a third of all "raised" houses on lots that are merely sloped); 572 "record" floors from construction-drawing or under-construction
   certificates; 3,772 modeled floors on buildings built after the lidar flight, dated as if measured in 2018-19.
3. **The call semantics need a column, not a footnote**: `bfe_call` compares the first *living* floor; on 434 of 462
   record `above` calls for elevated-with-enclosure houses the NFIP lowest floor is below the BFE, and 44 % of those
   enclosures are not documented vent-compliant. AO zones (54 buildings) are called against a neighbouring AE sliver's
   BFE. 244 `above` calls rest on certificates the pipeline itself flags as mismatched; `raised_flag` contradicts the
   certificate's own floor height on 708 record rows.
4. **Context a local reviewer will check first is missing**: the countywide preliminary FIRM FEMA issued on 2025-05-15,
   2,212 LOMAs, and the three FIRM effective dates in the county.

None of these is a bug in the arithmetic; they are definition, population and disclosure problems, which is what a
first edition is for. The fixes are listed in order in §5; the outreach program (`docs/08`) does not start until the
first four ship.

## 3. Findings (verified)

IDs: DA = data audit, M = methodology, I = implementation, S = sources, G = GIS. "Verified" = round-2 verdict.

### Blocking

| ID | Finding | Key numbers (verified) | Fix |
|---|---|---|---|
| DA1 | The accuracy claim (handoff §3/§8/§10, parquet metadata `gate`, viewer card) is the FDEM held-out score; on the independent county-certificate population it is much worse, and the gap is concentrated in elevated houses | county-only modeled rows, train.py screen applied, like-for-like living-floor definition: n 1,282, MAE 2.223, median error −0.18, within 1 ft 0.485, coverage 0.884 (flagged 0.907 / unflagged 0.847), BFE side 0.861, decided 0.379, decided correct 0.951; slab n 566 MAE 1.07 cov 0.905; elevated 5-9 n 703 MAE 3.14, median −1.37 ft, unflagged coverage **0.539**; 17 of 223 `below` calls contradicted by a surveyed certificate. Label noise is not the cause: 3,173 same-day FDEM / county pairs agree to 0.016 ft MAE | publish the county-certificate score next to the FDEM gate in `docs/06`, the parquet `gate` metadata, the spatia-data sidecar and the viewer card; state each score's population; print "band not guaranteed for unflagged elevated houses" until M2 is fixed; make the gate score both sets |
| G1 / DA2 | `ground_ft` is the DEM ring **minimum**; on waterfront and sloped lots it is the water surface, the seawall base or the canal, published as `observed` with 0.33 ft precision and no null reason. Modeled `ffh_ft` and `raised_flag` inherit it (the model's target is `ffe − g_lag`, so `ffe_ft` is largely protected); record and modeled `ffh_ft` use different grades. Round 2: blocking for `raised_flag` and the published `ffh_ft`; the water-constant subset alone is minor | 770 buildings < 0 ft NAVD88 (min −4.83), 507 < −1; 250 at exactly −1.999865 ft (= −0.60956 m, not a round number in any unit, not nodata: the DEM's nodata is −999999 and `job.py` maps it to NaN) — on those the ring median and the footprint interior are the same flat value, median area 73 m², 137 have no parcel, 51 are modeled: over-water structures on a hydro-flattened surface. County-wide on 7,482 certificate rows: certificate LAG − ring min +0.44 ft median, MAE 0.81, 12.9 % of surveyed LAGs sit *below* the ring min; ring **median** −0.15 ft median, MAE 0.51. On lots whose ring spans > 3 ft, 14,197 of 15,365 modeled rows are flagged raised (35 % of all flags) while certificates on 510 such lots show > 3 ft on 253 (228 false raised, 4 missed) | mask the water constant and cells < −1.5 ft out of the ring in `pipeline/lidar/features.py`; publish `ground_ring_min_ft`, `ground_ring_median_ft`, `ground_ring_range_ft` and a `ground_suspect` flag; null `ffh/ffe` where ground is a sentinel; decide the grade definition (§6 Q3) and retrain the target on it so record and modeled `ffh_ft` share one grade |

### Major

| ID | Finding | Key numbers (verified) | Fix |
|---|---|---|---|
| M1 | `ffe_ft` / `bfe_call` are about the first living floor (C2b for diagrams 2-4, 6-9); NFIP's lowest-floor answer flips for most elevated-with-enclosure `above` calls; the table has no per-row floor definition and no lowest-floor value (re-graded from blocking: the definition is stated in `ffe_source` and the number is right under it; the flip depends on enclosure data the pipeline lacks) | 1,478 record rows use the next-higher floor, 1,090 called `above`; on the 462 with county C2A: **434 (93.9 %) have C2A < BFE**, C2A − BFE median −3.4 ft; of 417 flipped diagram 6-9 rows, 359 record an enclosure, 159 (44 %) not shown vent-compliant, `E5` blank on all; modeled rows learn the same target (1,807 modeled `above` with `raised_flag`) | add `floor_definition` on every row; publish `lowest_floor_ft` (C2a) for records and `bfe_call_lowest_floor`; fetch A8/A9 vent fields with the labels; caveat `bfe_call` in `docs/06` as a living-floor call; carry `floor_definition` into the viewer card |
| M2 | The one normalised band under-covers raised houses the model does not flag, and the misses point toward false `below` | FDEM test: truly raised & unflagged n 70 coverage **0.543**; diagram 5-9 unflagged n 119 0.790; misses 69 above the band vs 39 below; every feature-identifiable group n ≥ 50 ≥ 0.895 (marginal 90 % holds; the conditional failure is not reported) | Mondrian / per-group band by predicted regime (p 1.5-3 ft), print the conditional-coverage table on the accuracy card; more elevated labels (county layer: 763 new diagram 5-9 buildings) |
| M3 | 244 `above` calls rest on certificates the pipeline flags as conflicting with the lidar | basis `record_lidar_conflict`: above 244 / below 2; on the 63 test labels the screen removes, model MAE 19 ft | `bfe_call = too_close` (or null `not_determinable`) when `ffe_record_lidar_conflict`; keep the value with `record_note` |
| M4 / G3 | BFE-line interpolation is validated on a population that cannot test it, and pairs lines across non-SFHA ground with no same-reach rule | check n 124 MAE 0.415 reproduces, but its pairs are 117 XS/XS flat coastal pairs (|e1−e2| median 0.2 ft) and nearest-line gives 0.408; production pairs 1,845 BL/BL + 1,399 XS/XS + 2,006 mixed, |e1−e2| p95 2 ft, max 8; the 5 riverine BL pairs in the check err 2.2-2.4 ft; only 34-35 % of L1→L2 segments stay inside the SFHA union (2,050 rows > 25 % outside, 1,110 > 50 %); 85 pairs mix panel dates, 268 take a line whose panel date differs from the building's polygon; 671 `above` / 150 `below` calls use an interpolated BFE | require the segment inside the building's SFHA polygon(s), else `not_determinable`; ask spatia-data to carry `WTR_NM` in `fema_bfe_context` and pair only one flooding source; validate by holding out riverine lines |
| S1 | Buildings built after the lidar flight are modeled from pre-construction lidar and dated 2018-19; the plan's `stale` reason is never used | modeled & `year_built` ≥ 2019: **3,772** (≥ 2020: 2,938, all `ffe_vintage` 2018-12-07/2019-03-08); decided calls 77 (≥ 2019: 108), `too_close` 741; 139 record rows have a certificate year before `year_built` | `ffh/ffe_null = stale` (or `not_evaluated`) when `year_built` > flight end; keep roof / eave / ground with a pre-construction note; add a `built_after_lidar` flag |
| S2 | 572 "record" floors come from certificates that are not finished-construction measurements; `buildingElevationSource` is never read | record rows 7,461: finished 6,889, under construction 289, drawings 236, null 47; 524 touch the SFHA; calls above 308 / below 210 | fetch and store the stage (`ffe_record_stage`); `record` class only for `finished_construction`; exclude the rest from labels |
| S3 | Licence position of the sold inputs is unresolved; tags over-claim | all rows `overture_buildings:ODbL-1.0` (ODbL §4.4a share-alike, §4.6 offer obligation; the phase-0 survey's own Decision §4 says a GERS-keyed sold table cannot ship without an ODbL decision); 7,515 rows `fdem_certificates:terms_unread` although the terms were read (Forerunner: "solely for your internal, non commercial purposes"; FDEM item licence empty); `provider = public` on all rows; 8 Geocodio rows cite a source ("Loveland") absent from Geocodio's data-sources page | legal read on ODbL (Collective vs Derivative Database) and on FDEM-via-Forerunner vs chapter 119 (`docs/08` A6); rename the tag to what was found; `provider` must not assert "no restricted provider" for those rows |
| S4 | FEMA issued a countywide preliminary FIRM for Pinellas on 2025-05-15 and holds 2,212 LOMAs in the county; the pipeline reads neither and the table does not say so | Prelim_NFHL DFIRM 12103C: 7,287 zones, 135 panels, 238 BFEs, `PRELM_CODE 12103C_20250515`; NFHL layer 34 LOMAs in bbox 2,212; pending 0 | county-level `firm_status` note now; next release read Prelim_NFHL as a second `bfe_*` set and LOMAs as `loma_case` (`docs/08` A4) |
| G2 | AO zones are called against a neighbouring AE polygon's BFE; AO depth is not carried | 92 `zone_main = AO` buildings, 54 with a static BFE from a sliver of a neighbouring polygon (0.0-49.6 % of footprint): 32 take a **VE** sliver's 10-13 ft, 21 an AE sliver's 8 ft, 1 an AE 10 ft; calls below 7 / above 4 / too_close 40; `zones_12103_raw` has no depth column and spatia-data's flood layers publish no `DEPTH` / `VELOCITY` (its `layer-gotchas.md`) | carry NFHL `DEPTH`; `bfe_null = not_evaluated` when the main zone is AO, or a distinct `HAG + depth` method; never let a sliver supply the BFE for an AO building |
| V1 | `raised_flag` is model-only even on certificate rows, so the table contradicts its own record floor height (found by the GIS verifier; no round-1 review reported it) | across 7,427 record rows, 708 are flagged raised while their own record `ffh_ft` ≤ 3 ft and 381 unflagged while `ffh_ft` > 3 | derive `raised_flag` from the record `ffh_ft` when `ffh_class = record` (one line in `assemble.py`) |
| I1 | "Latest certificate wins" is not what `labels.py` does: an undated certificate beats a dated one (`na_position="last"`) and same-date ties are broken by an unstable sort | re-run of the exact rule on the public FDEM layer reproduces r0's labels; 8 buildings keep an undated certificate over a dated one (46 at the property stage); as-written vs `na_first + stable`: 357 selections differ, 53 record FFEs change > 0.1 ft (max 58.5), 10 flip the sign of `floor_minus_bfe`; the same 344-357 labels trained and gated the model | `sort_values(["issuedAt", "OBJECTID"], na_position="first", kind="stable")` in `labels.py` (and the phase-0 counters); document the tie rule; rebuild labels → train → gate |

### Minor

| ID | Finding | Key numbers (verified) | Fix |
|---|---|---|---|
| DA3 | Handoff §8 counts are run9 and the §10 hash suffix is transposed | table: record 7,427 / modeled 240,356 / null 124,981; conflicts 300; calls 7,767 / 33,039 / 35,994 / 15,443; hash `…d6a93b7` | regenerate §8 from run13; fix the suffix; check the spatia-data roster pin was typed from the file |
| DA4 / I2 | Parcel table `parcel_key` not unique; per-parcel counts are per condo unit | 192 keys on 465 rows (max 11), 54 buildings; Σ buildings 7,137,267 over 432,360 rows | dedupe on (`parcel_key`, `geom_group`); state in `docs/06` that counts are per unit; assert uniqueness in `check.py` |
| DA5 | `ffe_record_lidar_conflict` semantics drift: True on modeled / null rows; mixes wrong matches with rebuilds | True on record 246 / modeled 51 / null 3; 269 of 300 flagged certificates post-date the lidar, 52 with `year_built` ≥ 2019 | say so in `docs/06`; add a `rebuilt_after_lidar` hint from `year_built` |
| DA6 | Record floor heights vs lidar ground disagree by > 3 ft on 249 rows without a flag | median +0.44, max 13.5 ft; record `ffh_ft` up to 23.1 ft | add the LAG-vs-ground test to the conflict screen or `record_note` |
| M5 | Record `above` has no tolerance while modeled `above` must clear the band (re-graded from major: `≥ BFE` is FEMA's rule and `floor_minus_bfe_ft` is per row) | record `above` 2,492: 403 within 0.5 ft, 141 within 0.1, 74 exactly at the BFE; `bfe_precision_ft` 0 on all 83,024 static rows so record `too_close` never fires | carry a certificate precision and a `bfe_margin_ft`; document the two standards of proof |
| M6 | q is calibrated on the FIT-only model but the shipped model is FIT + CAL; the label screen uses the label | q 2.3267 (k 1437 / 1595, finite-sample: correct); CAL coverage shipped 0.925 vs 0.901; TEST 0.918 vs 0.913; screen drops 4.6 % of test labels, all-label coverage ≈ 0.88 | cross-conformal or ship the calibrated model; report coverage on all matched labels too |
| M7 | Gate tolerances (0.05 / 0.01 / 0.01 / 0.01) sit inside marginal noise but outside paired noise; the test blocks are reused across releases | marginal sd MAE 0.047, coverage 0.008; paired sd MAE 0.013, coverage 0.0033 | gate on the paired bootstrap bound; freeze r0 test blocks as a benchmark and hold out 20 % of each new batch |
| M8 | `raised_flag` precision 0.49 on slab houses; flagged bands mostly mean "unknown" | precision 0.656, recall 0.741 (slab 0.487); 14,843 of 35,860 modeled `too_close` are flagged; flagged band median 10.3 ft | publish flag precision / recall on the card; two-sided flag (`p > 3` or `band_hi > 3`) |
| I3 | Sliver SFHA overlaps drive BFE and calls; `zones` shows share 0.0 next to `touches_sfha` | 754 buildings with < 1 m² in the SFHA (337 decided); 99 rows with every SFHA share rounding to 0 (92 with a BFE); 7 zone-A buildings get an interpolated BFE through an AE sliver | keep FEMA's rule but add `sfha_area_m2` and an `sfha_sliver` flag; never interpolate through a sliver |
| I4 | Null-reason branches disagree with each other or the schema | 3 rows `ffe_null = not_determinable` with `ffh_null = not_evaluated`; 144 `address_null = not_evaluated` after Geocodio ran; `model_version` / `raised_flag` set on 7,264 record rows (7,297 by `ffe_class`); `job.py` straddle branch says `not_determinable` where `no_coverage` is meant | one `why_not` table per row reused by every floor column; `model_version` only where `ffh_class = modeled` |
| I5 | No lint config, 22 ruff errors, 24 of 26 files unformatted, zero tests (CLAUDE.md says "typed and ruff-clean") | `ruff check pipeline viewer` 22; `ruff format --check` 24/26; no `pyproject.toml`, no `tests/` | add `pyproject.toml` with ruff / mypy; the minimum test set is listed in `review/pinellas-r0/implementation.md` §5 |
| S5 | Inputs that are not spatia-data layers are not pinned in the provenance; the FDEM extract is not kept | parquet `spatia_flood.inputs` = 6 layers only; FDEM (edited daily), WESM, Geocodio, the LLM model are undated; `data/fl/ec_all.json` absent and not on R2 | record fetch dates / counts / model in `prov`; keep `ec_all.json` under `_flood/` on R2 |
| S6 / S7 | Interpolated rows have no `bfe_precision_ft`; the certificates' geoid is unstated (GEOID12B vs 18 is ≤ 0.03 ft in Pinellas, so not material here) | static precision 0.0 × 83,024, interpolated null × 5,250; `ground_geoid` GEOID12B on 290,540; cert LAG − lidar ground +0.44 ft median is not a geoid effect | set the interpolated precision from the band; keep "geoid not stated" |
| G4 | Three FIRM effective dates in Pinellas, not one | 2021-08-24: 365,809 buildings; 2003-09-03: 5,126 (1,880 in the SFHA); 2009-08-18: 1,817 (971); 1,320 interpolated + 127 static BFEs are 2003 vintage | say so in `docs/06` and the layer notes; show in the coverage map |
| G5 / M9 | "Highest BFE of overlapped polygons" vs the largest-share polygon | 6,787 of 83,024 static buildings overlap > 1 distinct BFE value (1,224 overlap > 1 BFE-bearing polygon; spread median 1 ft, max 6); 559 AE + VE straddles differ; 1 `below` would move | correct for compliance; disclose that straddling lots use the VE BFE |
| G6 | Overture WGS84 footprints are placed on NAD83(2011) lidar with PROJ's null transform | pyproj picks "Inverse of NAD83(2011) to WGS 84 (1)", accuracy 2 m, the only operation available; if the footprint coordinate is ITRF2014@2020 the offset at Clearwater is 0.90 m (a third of the ground ring); Overture's datum is not documented anywhere in the repo | second order next to Overture's own placement error; note in the method |

### Notes

| ID | Observation | Numbers |
|---|---|---|
| DA7 | 26,638 modeled bands are wider than 10 ft (6,259 unflagged), max 124 ft; they resolve to `too_close` but are not usable estimates | cap or null bands above `roof_ft` |
| DA8 | Record calls use the 2021 FIRM BFE, not the certificate's; pre-2021 certificates differ by ≥ 2 ft on 1,314 of 4,007 (481 would flip); post-2021 agree 93 % within 0.5 ft | correct choice; say so in `docs/06` |
| M10 | Expected call error on the FDEM test set: modeled `above` wrong 2 / 111, `below` wrong 10 / 584 | the buyer-facing numbers until DA1 replaces them |
| G7 | LiMWA / Coastal A not represented (S_Gen_Struct not read); VE rule (lowest horizontal member) did not flip any of 11 checked calls; LOMA / LOMR-F and preliminary FIRMs not handled (S4) | document |
| G8 / I7 | 28,546 buildings sit on stacked (condo) parcels; 22,797 are modeled as houses, 3,395 `below`; `parcel_key` for 1,107 of them is an arbitrary unit | the single-family model is the wrong object for a condo tower; flag `parcels_at_centroid > 1` on the card |
| I6 | Viewer: auth fails closed, path regex holds, no CORS; `export.py` puts every column in the browser JSON, including parcel ids and FDEM certificate OBJECTIDs (resolvable to owner names on the public FDEM layer) | drop OBJECTIDs from the browser record before reviewers get logins |
| S8 | No lidar newer than the 2018-19 flight exists in 3DEP for Pinellas; the WESM query is filtered to the one project, so a newer flight could never have been found | query WESM unfiltered; the county's own flight is in `docs/08` A5 |
| S9 | The unused county certificate layer adds 1,416 labelled buildings (763 diagram 5-9) but ends in mid-2020 | ingest for r1; it does not help post-Helene |
| S11 | Personal data and secrets in git: clean (239 tracked files; no name columns in either parquet) | — |

## 4. What holds up

Reproduced by at least two independent passes:

- Gate: MAE 1.039 / coverage 0.918 / BFE side 0.898 / decided correct 0.983 / q 2.3267 from the saved artefacts; `train.py`
  re-runs byte-identically (same `model_version` `E-lgbm-12103-62f502979c3b`); q is the finite-sample quantile; the
  difficulty model sees only FIT out-of-fold residuals; FIT / CAL / TEST disjoint; no certificate field in `FEATS`.
- Arithmetic on every row, 0 mismatches: `ffe = ground + ffh` and its band; `floor_minus_bfe` and its band; `bfe_call`
  and `bfe_call_basis` from the schema rule; `raised_flag = ffh > 3`; `touches_sfha = sfha_share > 0`; `zone_main` =
  largest share; `in_risk_area` = centroid in the risk polygon (290,540); `building_id` unique; all 5,250 interpolated
  BFEs reproduce exactly; every `*_null` within the six reasons; vintages parse.
- Datum / CRS / units: all elevations NAVD88; every static BFE and line `navd88_verbatim` (no NGVD29 in Pinellas);
  certificates filtered to NAVD88, never converted; GEOID12B recorded per row, GEOID12B vs GEOID18 ≤ 0.03 ft at five
  Pinellas points; `ground_ft`, `roof_ft`, `eave_ft` in US survey feet via 1200/3937; EPSG:6442 and 3086 in metres, DEM
  ring in EPSG:26917; `always_xy` everywhere; no `*_Spheroid`; GeoParquet `geo` metadata carries explicit OGC:CRS84.
- 79 of 89 numeric claims in the committed outputs reproduce; the viewer JSON matches the table on 1,395 sampled values;
  no owner or contact field anywhere; 10 random record rows match their certificates 10 / 10; near-margin modeled `above`
  calls are confirmed by county certificates where one exists (n 101 under 1 ft margin).
- Spatial sanity: the > 85 %-below cells are pre-FIRM slab neighbourhoods (BFE − ground 4-6 ft, county certificates
  confirm 206 of 223 below calls), not a datum error; elevated clusters are all coastal; 0 modeled floors below ground.

## 5. What must change, in order

Before any outsider gets a viewer login (`docs/08` §2) and before the next release passes the gate:

1. **Accuracy disclosure (DA1)**: county-certificate score on the card, in `docs/06`, in the parquet `gate` and the
   spatia-data sidecar; the gate scores both label sets from now on.
2. **Ground (G1 / DA2)**: mask water / sentinel cells, publish min / median / range + `ground_suspect`, null floors on
   sentinels; decide the grade definition (§6 Q3) and retrain.
3. **Floor definition (M1)**: `floor_definition` on every row, `lowest_floor_ft` and `bfe_call_lowest_floor` for records;
   fetch A8 / A9 with the labels.
4. **Calls and flags (M3, G2, I3, V1)**: conflict certificates → `too_close`; AO → `not_evaluated` until depth is carried; sliver flag; `raised_flag` from the record floor height on record rows.
5. **Vintage and stage (S1, S2)**: `stale` for post-flight buildings; `record` only for finished-construction
   certificates; a `built_after_lidar` flag.
6. **Labels (I1)**: fix the sort, rebuild labels → train → gate (this changes the roster pin: spatia-data harness again).
7. **Bands (M2, M6)**: per-regime bands; calibrate the shipped model; ingest the county layer's 763 elevated labels.
8. **Context (S4, G4)**: preliminary-FIRM and LOMA notes now; the data in the following release.
9. **Interpolation (M4 / G3)**: same-reach rule; validate on held-out riverine lines.
10. **Docs and hygiene (DA3, DA4, I4, I5, S5)**: regenerate the handoff counts and hash; parcel keys; null reasons; `pyproject.toml`,
    ruff, the minimum tests; pin the non-spatia-data inputs.
11. **Licence (S3)**: the legal read before any sale; honest tags now.

Items 1, 2 (disclosure part), 3, 4 and 5 are table and doc changes a session can ship in r1 without new data; 6 and 7
need a retrain; 8 and 9 need spatia-data layer changes (`DEPTH`, `WTR_NM`, Prelim_NFHL, LOMAs).

## 6. Decisions for the owner

1. **Which floor is the product's floor?** First living floor (insurance "first floor height" sense) or NFIP lowest
   floor? Both can be published; `bfe_call` needs one definition per row (M1).
2. **Should a certificate that fails the lidar screen produce any call?** Today it produces 244 `above` (M3).
3. **Ground definition**: keep the ring minimum (NFIP lowest-adjacent-grade intent) with a suspect flag, or publish the
   ring median, which matches surveyed LAG better by every measure here (MAE 0.51 vs 0.81 ft)? The model target must
   follow (G1).
4. **Rebuild r0 now for the label-sort fix (I1) and the stage filter (S2), or carry both to r1?** Either way the
   roster pin changes and the spatia-data harness runs again.
5. **Is a construction-drawings / under-construction certificate ever `record`?** (S2)
6. **ODbL and FDEM / Forerunner**: who does the legal read, and is FDEM asked under chapter 119 (`docs/08` A6)? (S3)
7. **Surface the 2025-05-15 preliminary FIRM in r1?** A county note at minimum (S4).
8. **Freeze the r0 test blocks as a permanent benchmark** and hold out 20 % of each new batch? (M7)
9. **Can spatia-data carry NFHL `DEPTH` and `WTR_NM`?** Without them AO (G2) and same-reach interpolation (G3) cannot be fixed.
10. **Certificate OBJECTIDs in the viewer record** (I6): drop before reviewers get logins?

## 7. Contradictions between reviewers, settled

- **Hash**: the file ends `…d6a93b7`; the handoff's `…a6d93b7` is a transposition (sources §12 refuted).
- **County score vs subgroup coverage**: both reproduce; different populations (FDEM test set is slab-heavy; the
  county-only set is post-1992 elevated), so marginal 90 % holds and the conditional failure is real.
- **Living vs lowest floor**: number confirmed (434 / 462); re-graded blocking → major because the definition is stated
  per row and the NFIP flip depends on enclosure compliance data the pipeline lacks (44 % not shown compliant).
- **Ground**: the data audit's "sentinel / water" subset and the GIS review's "ring minimum vs surveyed grade" are the
  same defect at two scales; the GIS verifier re-derived both and grades the whole blocking for `raised_flag` and the
  published `ffh_ft` (228 of 510 certificate lots with a sloped ring are falsely flagged), the water-constant subset
  alone minor; treated as one blocking item (G1 / DA2).
- **Sentinel −1.999865 ft**: not −2 international feet (that would be −1.999996 ftUS); it is the vendor's hydro-flattened
  value stored as a finite cell (DEM nodata is −999999).
- **"73 modeled sentinel rows: 32 below / 45 too_close / 1 above"** (data audit) is 28 / 45 on re-count.

## 8. Not checked

Anything on R2 or the published spatia-data layer (no credentials in this session); the live viewer; the raw FDEM
extract r0 used (`data/fl/ec_all.json` absent: the county layer and a fresh public pull stood in); the terms pages'
legal reading; NFHL S_Gen_Struct (LiMWA); the DEM tiles' own vertical metadata beyond one header; the r1b artefacts.
