# Methodology and statistical-theory review of pinellas-r0

Work dir: `(session work dir, not committed) ` (scripts `s1_gate.py` … `s7_featshift.py`, outputs `s*_output.txt`,
`subgroups.csv`, `test_scored.parquet`, `c2a_flip.parquet`, `interp_check_linear.parquet`). All numbers below are from
those runs unless marked "doc claims".

## Verdict

The point estimate, the normalised conformal band and the gate numbers are real: I re-scored the 1,315 held-out houses
from the saved artefacts and reproduced MAE 1.039 / coverage 0.918 / BFE side 0.898 / q 2.327 exactly, the quantile is
the finite-sample one, the difficulty model sees only FIT out-of-fold residuals, and every buyer-identifiable subgroup
with n >= 50 is covered >= 0.895. On the modeled side the layer is fit to show as a *screening* product. It is **not yet
fit to put in front of a floodplain manager as a BFE determination**, for one semantic reason and two call-rule
reasons: (1) `ffe_ft` / `bfe_call` are about the first *living* floor; on buildings with an elevated floor over an
enclosure (diagrams 6-9, 1,419 record rows) 94% of the record `above` calls I could check against the county's C2a
field would be `below` on NFIP's lowest floor; (2) 244 `above` calls come from certificates the pipeline itself flags
as conflicting with the lidar (basis `record_lidar_conflict`: 244 above vs 2 below, i.e. the conflict manufactures
"above"); (3) the band provably under-covers raised houses the model does not flag (0.54 on n = 70; 0.79 on diagram 5-9
unflagged, n = 119), and the misses are the ones that produce false `below` calls. Fix before r1: add a lowest-floor
column and per-row floor definition on the call; null the call on conflict certificates; widen or group-calibrate the
band for the borderline raised regime; and replace the 124-building interpolation check, which is 117/124 flat
cross-section pairs and cannot distinguish linear interpolation from "nearest line".

## Findings

### 1. [blocking] `bfe_call` compares the first LIVING floor; on elevated-with-enclosure houses it flips NFIP's lowest-floor answer
- Where: `pipeline/train/labels.py:49-50` (target = C2b for diagrams 2-4, 6-9); `assemble.py:508-536` (call uses that
  `ffe_ft`); `docs/06` "Limits of the call" mentions only basements (2A/2B: 10 rows).
- Evidence (`s2_table.py`): record rows by diagram `1A 4760, 1B 1027, 7 582, 8 466, 6 347, 5 196, 3 46, 9 24, 2A 6,
  2B 4, 4 3`; 1,478 record rows use the next-higher floor, 1,090 of them called `above`. The r0 labels carry no C2a, so
  I joined the Pinellas county certificate layer (same buildings via `labels_pinellas_12103.parquet`): 693 r0 record
  rows of diagram 2-4/6-9 have a county certificate with C2A and C2B (county C2B agrees with the r0 `ffe_ft` within
  0.5 ft on 621). Of those 693, 472 are `above`; **443 (94%) would be `below` on the lowest floor (C2A < BFE)**; C2A -
  BFE median -3.4 ft, IQR -4.8..-2.0. County-wide, next - bottom floor median 9.8 ft (n = 3,456). Scaled to the 1,090
  next-higher-floor `above` calls, ~1,000 flip. Modeled rows learn the same target, so the 1,807 modeled `above`
  calls with `raised_flag = True` mean "living floor above", too.
- Why it matters: a floodplain manager's compliance / substantial-improvement question and NFIP rating are about the
  lowest floor (the enclosure floor when it is finished or non-compliant). The parcel table's `any_building_below_bfe`
  and the `bfe_call` column carry no hint; only the record row's free-text `ffe_source` says "diagram 7, first living
  floor". The modeled rows carry nothing.
- Fix: publish `lowest_floor_ft` (C2a, record) alongside `ffe_ft`; add a `floor_definition` column (`living_floor` /
  `lowest_floor`) on every row; emit `bfe_call_lowest_floor` for records; rename or caveat `bfe_call` in the schema as
  a living-floor call; for modeled `raised_flag = True` rows set the call basis to `modeled_band_living_floor`.

### 2. [major] The 90% band under-covers the raised houses the model does not flag, and the misses point the costly way
- Where: `train.py` applies one normalised band to flagged and unflagged houses (`BANDS.md` "Product rule" and
  `docs/04 §4` say flagged houses keep a per-group band; the deviation is not recorded).
- Evidence (`s1_gate.py`, `subgroups.csv`): groups with n >= 50 and coverage < 0.85: `truly raised (dh > 3) and
  unflagged` n 70 coverage **0.543** (MAE 2.48, median width 3.2 ft); `diagram 5-9 and unflagged` n 119 coverage
  0.790; `slab 1A/1B truly raised` n 130 coverage 0.823; `diagram 5-9 truly raised` n 136 coverage 0.831. Band misses on
  the test set: 69 above the band vs 39 below (`s6_misc.py`), so the model under-predicts raised floors; 10 of the 584
  `below` calls on the test set are wrong (1.7%, CI 0.8-3.1%) vs 2 of 111 `above` (1.8%, CI 0.2-6.4%).
- Why it matters: these groups are defined by the truth, so conformal's marginal 90% is not violated and no row can
  name itself; but a buyer reads 90% per row, and the 28,955 modeled `below` calls include the regime where the band is
  worst. The doc claims 0.79 for 5-9 unflagged (`docs/05 §3`); I measure 0.790, and the sharper 0.543 is not reported.
- Fix: calibrate per group on the *predicted* regime (p in 1.5..3 ft is where most misses sit; `subgroups.csv`), or a
  Mondrian band by `flag`, and print the conditional coverage table in the accuracy card; until then document in
  `docs/06` that coverage is marginal and 0.54 for unflagged houses that are in fact raised.

### 3. [major] 244 `above` calls rest on certificates the pipeline believes are mismatched
- Where: `assemble.py:517-519, 538-540`; owner decision "keep as record, flagged" (`docs/05 §3`).
- Evidence (`s2_table.py`): record calls with `ffe_record_lidar_conflict = True`: `{'above': 244, 'below': 2}`. The
  screen fires when the certificate floor is within 6 ft of the lidar roof or below ground; on the 63 test labels it
  removes, the model's MAE is 19.0 ft and coverage 0.11 (`s1_gate.py`), i.e. these are not real floors of these
  footprints.
- Why: a wrong `above` is the costly error for a buyer; the basis string is per-row, but the value column still says
  `above`.
- Fix: `bfe_call = too_close` (or null `not_determinable`) when `ffe_record_lidar_conflict`, keep the certificate value
  in `ffe_ft` with `record_note`.

### 4. [major] The BFE-line interpolation is validated on a population that cannot test it
- Where: `assemble.py:164-204` (`interpolate_bfe`), `:323-335` (the static check); `docs/05 §3` "MAE 0.415, 96% within 1 ft".
- Evidence (`s3_interp.py`): I reproduce the check exactly (n 124, MAE 0.415, within 1 ft 0.960, inside band 0.960).
  But its pairs are `XS/XS 117, BFE_LINE/BFE_LINE 5, XS/BFE_LINE 2` with |e1 - e2| median 0.2 ft (flat coastal
  cross-sections at the 11-12 ft static BFE), while production pairs (`bfe_source` of the 5,250 interpolated rows) are
  `BFE_LINE/BFE_LINE 1845, XS/XS 1399, XS/BFE_LINE 1097, BFE_LINE/XS 909`, |e1 - e2| 95th pct 2 ft, max 8 ft. On the
  same 124 buildings **nearest-line MAE 0.408 vs linear 0.415** (linear better on 40, worse on 29, tie 55): the check
  cannot tell interpolation from nearest. The only BFE_LINE pairs in the check (5) are the riverine case and all err by
  2.2-2.4 ft, outside the band (e1 34, e2 33, static 36). Code: the second line only has to lie on the opposite side of
  the building (`near[k] @ near[i1] < 0`); no same-reach / same-flooding-source / same-source-type test; distances are
  straight-line, not along the reach (restricting to same `source_type` changes 1 of 124). 671 `above` and 150 `below`
  calls use an interpolated BFE; interpolated band width median 1.4 ft, 451 rows > 2 ft, max 9 ft.
- Why: BFE lines are water-surface contours of one reach; pairing across a tributary junction or a coastal / riverine
  boundary interpolates between two different floods.
- Fix: pair only lines sharing the same `WTR_NM` / study reach (NFHL `S_BFE.WTR_NM`, `S_XS.WTR_NM`; add the column to
  `fema_bfe_context`), interpolate along the stream line (NHDPlus flowline chainage) and validate on a held-out subset
  of riverine BFE_LINE pairs (drop one line, predict it from its neighbours), not on coastal static polygons.

### 5. [major] Record `above` carries no tolerance while modeled `above` must clear the band; 403 record `above` calls are within 0.5 ft
- Where: `assemble.py:531-535`: `rec_call` is `too_close` only inside `1.645 * bfe_precision_ft`, and
  `bfe_precision_ft` is 0.0 for all 83,024 static-BFE SFHA buildings (`s2_table.py`), so the rule never fires on a static
  BFE; modeled rows need `band_lo >= bfe`.
- Evidence: record `above` 2,492; within 0.5 ft of the BFE 403 (16%), within 0.1 ft 141, exactly at it 74; record `below`
  within 0.5 ft 314. Among SFHA test truths, 168 of 1,200 sit within 0.5 ft of the BFE, 14 exactly at it.
- Why: "at or above the BFE complies" is FEMA's rule, so `>=` is defensible as a compliance statement, but a certificate
  reads to 0.1 ft with survey and geoid uncertainty of the same order (`ffe_datum` itself says "geoid not stated"), so
  ~140-400 `above` calls are inside instrument error, and a reader comparing a record row to a modeled neighbour sees two
  different standards of proof. The per-row `floor_minus_bfe_ft` lets a careful reader see it.
- Fix: carry a certificate precision (0.1 ft reporting + conversion sigma when `cert_datum` was converted) in
  `ffe_precision_ft`, and make `too_close` fire when `|ffe - bfe| < 1.645 * sqrt(sig_ffe^2 + sig_bfe^2)`; or keep `>=`
  and add `bfe_margin_ft` to the parcel table.

### 6. [minor] Conformal validity: q is finite-sample and leak-free, but calibrated for a model that is not the one shipped, on a label-screened population
- Evidence (`s4_conformal.py`): q reproduced 2.3267 (saved 2.3267), k = ceil((n+1)·0.9) = 1437 of n 1595 (`np.quantile`
  would give 2.318); test blocks equal the saved list, FIT/CAL/TEST disjoint; the retrained final model matches the saved
  one to 0.0 on test; difficulty model fit on FIT OOF residuals only. But `train.py:122-124` calibrates q with `m_fit`
  (FIT only) and ships `model` (FIT + CAL): CAL coverage of the shipped model 0.925 (in-sample) vs 0.901 for `m_fit`;
  TEST 0.918 vs 0.913. The guarantee holds for `m_fit`; empirically the shipped model is covered slightly better, so
  no harm today, but the exact-coverage property is lost. The screen `roof_p95 - dh < 6 | dh < -1` uses the label
  and removes 63 of 1,378 test labels (4.6%); on them MAE 19.0 ft, coverage 0.11; all-label coverage would be ~0.88.
- Exchangeability: the 90% claim needs future rows exchangeable with CAL. CAL and TEST are 1 km grid blocks drawn at
  random among labelled blocks; 98% of test blocks have a FIT/CAL block among their 8 neighbours, so the gate measures
  within-area interpolation. 72% of modeled rows lie in a block with a screened label (97.6% of SFHA rows, 61.4% of
  non-SFHA), nearest labelled block >= 2 km for 2.0%; in the model's own feature space the modeled median equals the
  labelled median on every feature and 25.7% of modeled rows have any of the 24 features outside the labelled
  1st-99th pct (`s7_featshift.py`; ~38% would be expected under no shift), so feature support is fine. The untestable
  part is selection on y: certificates exist for permitted / insured houses (record rows: 86% zone A, 92% touch the
  SFHA; modeled: 28% / 30%, 61% zone X; `ground_ft` median 5.5 vs 15.3 ft). The 96 X-zone test certificates are covered
  0.927, which is the only evidence for the 170k non-SFHA modeled rows. The "decided correct 0.983" claim is on SFHA
  test houses, whose population matches the 70,090 modeled rows with a call well (any-feature-outside 15.1%, ground
  1.8%; `s5_paired.py`).
- Fix: calibrate q on CAL with the shipped model via cross-conformal (or ship `m_fit`), report coverage on all matched
  labels as well as screened, and add a per-row `band_calibration` note (`local_block` / `county`).

### 7. [minor] Gate tolerances are inside the marginal noise but outside the paired noise; the test set is reused
- Evidence (`s1_gate.py`, `s5_paired.py`): marginal bootstrap sd on the 1,315 houses: MAE 0.047 (block bootstrap 0.068),
  coverage 0.008 (0.011), BFE side 0.009, decided correct 0.005. Paired difference between two models on the same
  houses (shipped vs FIT-only): sd MAE 0.013, coverage 0.0033, BFE side 0.0040, decided correct 0.0019. Tolerances
  (0.05 / 0.01 / 0.01 / 0.01) are 2.5-5 paired sd, so the gate can catch a regression of ~0.05 ft MAE but passes one
  of 0.03 ft; the 0.88 coverage floor is ~5 sd below 0.918 (95% block-bootstrap CI 0.896-0.939). `gate.py` scores on the
  candidate's `test_blocks`, which by design contain the same houses release after release, so the gate also selects on
  the test set over time; `docs/04 §2` says 20% of *each new batch* is held out, which is only true if blocks are redrawn.
- Fix: state the paired sd in `gate.py`'s output, bootstrap the paired difference and gate on its 95% bound; freeze the
  r0 test blocks as a permanent benchmark and add a fresh 20% of each new label batch.

### 8. [minor] `raised_flag` precision is 0.49 on slab houses; 3 ft is a defensible cut for Pinellas
- Evidence (`s1_gate.py`): all n 1315, truly raised 270, flagged 305, precision 0.656, recall 0.741; slab 1A/1B precision
  0.487 (195 flagged, 95 truly raised); diagram 5-9 precision 0.953, recall 0.750. Record `ffh_ft` (certificate FFE -
  certificate LAG): median 1.1 ft, q75 2.4, q90 9.7; 20.8% > 3 ft, 12.0% within 2..4 ft, 5.1% within 2.5..3.5 ft
  (`s5_paired.py`); lidar-based dh: 26.2% > 3, 21.7% within 2..4. The cut sits between the slab mode and the elevated
  mode; the precision loss is the model's, not the threshold's. Flagged bands are 10.3 ft wide at the median in the
  table (unflagged 1.9), and 14,843 of the 35,860 modeled `too_close` calls are flagged: the flag mostly means "unknown".
- Fix: publish the flag with its test precision / recall in the accuracy card; consider a two-sided flag (`p > 3` or
  `band_hi > 3`) so the borderline regime of finding 2 is marked.

### 9. [note] "Highest static BFE" rule: 8.2% of static-BFE buildings overlap several BFEs
- Evidence (`s6_misc.py`): 6,787 of 83,024 overlap > 1 distinct static BFE; spread median 1 ft, max 6 ft; 27 record rows
  called `below` under the highest BFE would be `above` under the largest-share polygon's BFE. Conservative for `above`,
  anti-conservative for `below`; `docs/06` states the rule. Fine for screening; a determination should name the polygon.

### 10. [note] Test-set call error a buyer should expect
- Modeled `above` wrong 2/111 (1.8%, Clopper-Pearson 0.2-6.4%); `below` wrong 10/584 (1.7%, 0.8-3.1%); the two wrong
  `above` calls had `band_lo - bfe` of 0.00 and 0.46 ft. Base rate truly above among SFHA test houses 0.361; the
  modeled SFHA decided share above is 0.154 vs record SFHA 0.383, consistent with certificates being post-FIRM-biased.

## Checked and found sound
- Gate reproduction from saved artefacts on the 1,315 held-out houses: every cell of `train_12103.txt` row 1 and
  `gate_12103_pinellas-r0.json` matches to 4 decimals (`s1_output.txt`).
- `abs_q` is the finite-sample order statistic; difficulty model uses FIT out-of-fold residuals only; no CAL / TEST row
  enters the difficulty model or the point model before q is set; the saved final model retrains bit-identically.
- `FEATS` contain no certificate-derived field; `est_eave_*` reference medians are label-free; `score()` uses the
  certificate BFE only to score.
- Every feature-identifiable subgroup with n >= 50 is covered >= 0.895 (zone A 0.919, X/other 0.927, every decade
  1940-2020 0.896-0.948, ground / footprint / living-area terciles 0.895-0.936, flagged 0.938 / unflagged 0.912).
- The 124-building interpolation check reproduces exactly (n, MAE, within-1-ft, inside-band).
- `bfe_precision_ft` is 0 for every static BFE (all NAVD88-native), so the record `too_close` branch is dead code
  today, as `docs/06` says.

## Open questions for the owner
1. Is the product's floor the first living floor (insurance "first floor height" sense) or NFIP's lowest floor? Both
   can be published; the call needs one definition per row.
2. Should a certificate that fails the lidar screen produce any call at all?
3. Is `fema_bfe_context` able to carry `WTR_NM` / study reach so pairs can be restricted to one flooding source?
4. Will the r0 test blocks be frozen as a permanent benchmark, or redrawn per batch (the plan says both)?

## Method
17 tool calls: 6 reads of code / docs / artefacts, 7 scripts run (`s1` gate + subgroups + bootstrap + raised flag;
`s2` table-level shift, calls, interpolated widths, C2a/C2b; `s3` interpolation reproduction and nearest vs linear;
`s4` conformal retrain, block adjacency, label density; `s5` paired bootstrap, precision CIs, call-population shift,
record ffh; `s6` tail split and multi-BFE overlap; `s7` feature-space shift), plus fixes. Not checked: C2a for the r0
FDEM source itself (`data/fl/ec_all.json` is absent here; the county layer was used as a proxy on 693 buildings);
along-reach interpolation (no flowline / `WTR_NM` in `bfe_lines_12103.parquet`); the r1b gate's paired noise (no
`train_r1b` artefacts present). One of my own checks (q over alternative CAL draws in `s4`) is confounded by the
difficulty model having seen those houses and is not used in any finding.
