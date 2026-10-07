# Pinellas (12103) r1b: county elevation-certificate labels added to r0's method

Date: 2026-10-07. Owner decision 2026-10-07: "keep r0, add labels first". This is a candidate only, not a release.
r0 (`data/flood_v1/train/`) is untouched: the sha256 prefixes of all five files are the same before and after this
work (bands 3c5348599f43d415, difficulty ff050c5a820d4075, labels 00515377a6e1e79d, model 64888472707bc972,
records ac3dbdd2d9bfbdd8). Nothing was committed, pushed or uploaded.

**Recommendation: do not release r1b. Keep r0.** The gate fails. The gate's own test set also leaks in r0's favour (§5).
On the clean houses that neither model trained on, r1b is still worse on coverage and on the elevated-unflagged
subgroup. The county labels for elevated houses are much harder for the model than FDEM's in the same era (§6).

## Commands (every number below comes from one of these)

| # | Command | Output |
|---|---|---|
| C1 | `python pipeline/labels_pinellas/fetch.py 2026-10-07` | `data/flood_v1/labels_pinellas/raw/2026-10-07/` (layer.json, 20 pages, fetch.json) |
| C2 | `python pipeline/labels_pinellas/build.py 12103 pinellas_2018 2026-10-07` | `pipeline/labels_pinellas/out/build_12103.json`; `data/flood_v1/labels_pinellas/labels_pinellas_12103.parquet`, `labels_combined_12103.parquet` |
| C3 | `OMP_NUM_THREADS=1 python pipeline/train/train_r1b.py 12103 pinellas_2018 --labels data/flood_v1/train/labels_12103.parquet --out <scratch>` | reproduction check against r0 |
| C4 | `OMP_NUM_THREADS=1 python pipeline/train/train_r1b.py 12103 pinellas_2018 --labels data/flood_v1/labels_pinellas/labels_combined_12103.parquet --out data/flood_v1/train_r1b` | `data/flood_v1/train_r1b/{model,difficulty,bands,train,split}_12103.*` |
| C5 | `python pipeline/train/gate.py 12103 pinellas_2018 --candidate data/flood_v1/train_r1b --baseline data/flood_v1/train --release pinellas-r1b-fdemlabels` | `out/gate_12103_pinellas-r1b-fdemlabels.json` |
| C6 | the same with `--release pinellas-r1b --labels data/flood_v1/labels_pinellas/labels_combined_12103.parquet` | `out/gate_12103_pinellas-r1b.json` |
| C7 | `OMP_NUM_THREADS=1 python pipeline/train/r1b_eval.py 12103 pinellas_2018 --labels data/flood_v1/labels_pinellas/labels_combined_12103.parquet --r0 data/flood_v1/train --r1b data/flood_v1/train_r1b --r0-labels data/flood_v1/train/labels_12103.parquet` | `out/r1b_eval_12103.json` |
| P | ad-hoc profile of the raw pages before C2 was written: server `groupBy` statistics and a pandas read of the pages | raw-layer facts marked (P) |

## 1. Source and fetch (C1)

- **Layer.** `https://egis.pinellas.gov/gis/rest/services/ElevationCertsApp/ElevationCertsApp/MapServer/0`, named
  "Pinellas Elevation Certificates".
  - Points, native SR 2882, fetched with outSR=4326. maxRecordCount is 1,000.
  - The server count and the records fetched are both **19,382** (20 pages, ordered by OBJECTID).
  - OBJECTID is unique and no geometry is null (P).
- **Fields.**
  - `outFields` is an explicit allowlist of 50 fields. The script asserts that none of them is an owner, address,
    name, contact, licence-number, comment, file-name or editor field, and that the server returned nothing else.
  - A1 owner, A2 address, A3 property description, the D/F/G names and phones, and COMMENTS / FILE_NAME were never
    requested.
  - `STR_PIN` (parcel id) was fetched only to keep one certificate per property. It is not written to any output.
- **Description / licence text.**
  - The `description` and `copyrightText` are the same text: "Public Works Elevation Certificates in Pinellas County,
    Florida.", then a data-steward line with a named person's phone and e-mail (personal contact, not reproduced here),
    then "Data Certification: SILVER".
  - **There is no licence or terms text on the layer.** County rows are therefore tagged
    `pinellas_county_ec:terms_unread`.
  - The survey (`docs/phase0-sources-survey.md`) quotes pinellas.gov: certificates are for "all buildings in the
    unincorporated area constructed in the floodplain since 1992". I did not re-fetch that page.
- **Layer dates (P).**
  - `CREATED_DATE` and `LAST_EDITED_DATE` are 2026-10-04 16:00:16 on all 19,382 rows: a reload, not the certificate
    dates.
  - `D_DATE` (the certifier's signature date) is filled on 18,563 rows. Raw range 1960-02-01 to 6201-11-22; the latter
    is the same typo FDEM had (handoff §8).

## 2. Cleaning (C2, `build_12103.json`)

| step | rule | kept | dropped (why) |
|---|---|---|---|
| records | | 19,382 | |
| vertical datum | NAVD88 values only | 8,926 | 894 NGVD only (875 NGVD1929 + 19 NGVD1927); 9,562 no stated C2 datum (blank / UNK / OTH / null) |
| residential | `A4_BUILDING_USE = RES` | 7,464 | blank 943, NONRES 408, ACC 50, OTH 29, ADD 27, COM 5 |
| diagram | normalised; valid 1A 1B 2 2A-2D 3-9 | 6,452 | "1" 849 (pre-2003 form; not a labels.py diagram), blank 146, "8&" 10, "ONE" 4, "1*" 1, "5&" 1, "7A8" 1 |
| first living floor | labels.py: 1A/1B/5 → C2a, 2-4/6-9 → C2b | | |
| plausible | | 6,241 | value null 208, zero 1, outside (-20, 200) ft 0, floor minus own certificate LAG outside [-2, 40] ft 2 (40.58, 40.49) |
| one per property | STR_PIN, latest D_DATE | 5,624 | 617 older certificates |
| run bbox | | 5,624 | 0 |
| match (labels.py, EPSG:6442) | in footprint / nearest ≤ 10 m | 4,759 within + 724 nearest | 141 unmatched |
| one per building | latest | **5,247** | 236 older |

**Datum detail (the brief's premise needed refining).**

- `VERTICAL_DATUM` (the datum of C2a-h) is blank on most rows.
- The county instead fills a paired `C2a_29` / `C2a_88` (and b, f, g) on 8,398 rows. `C2a_29 − C2a_88` is median
  0.86 ft (min −0.20, max 0.95).
  - On 6,873 of those rows, C2A equals `C2a_88`: native NAVD88.
  - On 1,525 rows, C2A equals `C2a_29`: the certificate is recorded as NGVD29 and the county supplies a converted
    NAVD88 value.
  - On 0 rows it equals neither.
  - A further 528 rows without the pair say `VERTICAL_DATUM = NAVD1988`.
- **NGVD29 on certificates: 2,400.** That is 1,525 with a county NAVD88 value plus 875 NGVD1929 without one.
  Nothing was converted by me.

The county-converted route (228 of the 5,247 matched labels) was **excluded** from the combined labels on evidence:

- **Against FDEM.** On the 62 buildings both hold, the county value is median −0.86 ft from FDEM, with 1.6% within
  0.5 ft. For 38 of the 40 bottom-floor diagrams, FDEM's "navd_1988" value equals the county's `C2a_29` number.
  So one source double-shifts.
- **Against lidar ground** (certificate LAG minus lidar g_lag, median, by certificate era):

  | era | native | converted |
  |---|---|---|
  | ≤2004 | +0.54 (n 61) | +0.19 (n 150) |
  | 2005-09 | +0.56 (n 361) | +0.73 (n 7) |
  | 2010-14 | +0.58 (n 517) | −0.03 (n 8) |
  | ≥2015 | +0.48 (n 3,963) | −0.33 (n 59) |

  The ≥2015 gap of 0.81 ft is about one datum shift, which suggests the county converted values that were already
  NAVD88. This also means **FDEM's value is probably right** for those 62 buildings.

**Other choices.**

- **BFE.** `cert_bfe_ft` is taken from B9 when `B11_ELEVATION_DATUM = NAVD1988` (4,903). The county's
  `BFE_CONVERTED_TO_NAVD88` is used for NGVD1929 BFEs; that applied to 0 rows after matching. 53 values outside
  (0, 40] ft were set to null.
- **Geoid.** Not stated on the certificates; it is recorded as unknown.
- **Units.** `MEASUREMENT_UNITS` is FT or blank (P); feet were assumed.
- **Issue date** (`D_DATE`, cleaned set of 6,241): 118 null and 1 invalid (6201-11-22) set to null.
  - Range 1974-12-31 to 2020-05-01.
  - By 5-year bin: 2000-04: 294; 2005-09: 483; 2010-14: 632; 2015-19: 4,528; 2020: 180; before 2000: 5.
  - Undated certificates never win "latest". labels.py's FDEM sort lets an undated one win; that is a difference
    from labels.py.

## 3. Agreement with FDEM and the one-label rule (C2)

- **Overlap.** 3,665 buildings have both an FDEM label and a county label.
  - All of them: median diff 0.00 ft, median |diff| 0.00 ft; **94.4% within 0.5 ft**, 96.8% within 1 ft, 2.2% over 3 ft.
  - Same diagram on 96.6%.
  - Native NAVD88 route (n 3,603): 96.0% within 0.5 ft.
  - Issue dates within one day (n 3,222, apparently the same certificate): 98.2% within 0.5 ft.
  - Dates differ (n 318): 56.6% within 0.5 ft.
- **Rule.** One label per building. The county certificate replaces FDEM's only when both issue dates are known and
  the county's is strictly later; otherwise FDEM is kept (FDEM wins ties and missing dates).
  - Native-route overlaps: 15 replaced by the county, 3,588 FDEM kept.
- **Combined.** `labels_combined_12103.parquet` holds 8,931 labels: FDEM 7,500 and county 1,431. Columns:
  - the 8 columns of labels_12103;
  - `label_source` (`fdem` / `pinellas_county`);
  - `county_objectid` (the county OBJECTID);
  - `vertical_datum_route`;
  - `ffe_field`;
  - `licence` (`pinellas_county_ec:terms_unread`, or `fdem_certificates:terms_unread`, the tag assemble.py uses).

  `cert_objectid` is null for county rows, so it can never be mistaken for an FDEM OBJECTID.

## 4. What the county adds (C2)

- **New labelled buildings: 1,416** (not in FDEM). Elevated:
  - 763 have diagram 5-9;
  - 870 have dh > 3 ft against lidar g_lag;
  - **924** meet either test.
- **Label screen** (train.py's): 29 have no lidar ground or points. **37 fail the screen**: 14 with dh < −1 and 23 with
  roof_p95 − dh < 6.
- **Usable: 1,350**, of which 877 are elevated (727 by diagram 5-9).
- **For comparison, FDEM:** 7,187 usable, of which 1,396 have diagram 5-9 and 2,283 meet either test. The county adds
  **+52%** to the usable diagram 5-9 labels.

## 5. r1b training and the release gate

**Reproduction.** `train_r1b.py` repeats `train.main` with only the label path and output directory as parameters,
importing every function and constant from train.py. Run on r0's labels (C3), it writes a **byte-identical** model and
difficulty file, the same q (2.326714506848828) and the same test blocks.

**r1b (C4).**
- 8,872 joined labels; 8,536 after the screen.
- 530 blocks: fit 5,030 / cal 1,724 / test 1,782.
- q = 2.180.
- Own-test MAE 1.473 and coverage 0.897. These are not comparable with r0's table: its test set has 478 elevated
  houses against r0's 226.

**`gate.py` change (backwards compatible).**
- Added `--labels FILE`. The default is unchanged, and the chosen file is recorded in the gate JSON.
- Without `--labels`, the r0 gate re-run gives scores identical to `gate_12103_pinellas-r0.json` (1,315 houses).
- With only FDEM labels, the gate would score r1b's test blocks on FDEM houses only and drop the new county houses.

**Gate results (r1b's 106 test blocks):**

| gate run | n | MAE r1b / r0 | BFE side r1b / r0 | coverage r1b / r0 | decided correct r1b / r0 | result |
|---|---|---|---|---|---|---|
| C5 FDEM labels (as briefed) | 1,472 | 1.272 / 1.098 FAIL | 0.871 / 0.887 FAIL | 0.910 / 0.932 FAIL | 0.973 / 0.973 pass | **FAILED** |
| C6 `--labels` combined | 1,782 | 1.473 / 1.366 FAIL | 0.854 / 0.860 pass | 0.897 / 0.915 FAIL | 0.966 / 0.958 pass | **FAILED** |

**The gate's premise does not hold for a new label batch (C7).**
- The gate assumes the candidate's held-out blocks are held out from the baseline too. But train.py shuffles the
  sorted list of *labelled* blocks with seed 0. 21 new blocks change the whole permutation, so r1b's 106 test blocks
  and r0's 102 share only **35**.
- **1,139 of the gate's 1,782 houses** (957 of its 1,469 FDEM houses) sit in blocks r0 trained or calibrated on. The
  gate as run is biased toward r0.
- The reverse also holds: 887 of r0's 1,526 test houses (combined labels) sit in r1b's FIT/CAL. r0's test set is biased
  toward r1b.
- The fair comparison is the **CLEAN set: 35 blocks held out from both, 639 houses.**

| C7, same houses | n | MAE r0 / r1b | BFE side | coverage r0 / r1b | decided correct | width med. not flagged |
|---|---|---|---|---|---|---|
| CLEAN all | 639 | 1.451 / 1.409 | 0.887 / 0.887 | **0.905 / 0.884** | 0.974 / 0.980 | 1.948 / 1.891 |
| CLEAN FDEM | 512 | 1.123 / 1.122 | 0.905 / 0.901 | 0.922 / 0.906 | 0.980 / 0.987 | 1.863 / 1.841 |
| CLEAN county | 127 | 2.772 / 2.567 | 0.818 / 0.835 | 0.835 / 0.795 | 0.919 / 0.942 | 2.977 / 3.101 |

On the clean set, r1b's coverage drop of −0.021 still exceeds the gate's 0.01 tolerance. Its MAE gain of 0.042 is
within noise.

**Elevated-unflagged coverage** (diagram 5-9 and the model's own p ≤ 3 ft; Wilson 95%):

| houses | r0 | r1b |
|---|---|---|
| r0 TEST, FDEM labels (r0's figure) | **0.790** (n 119; 0.708-0.853) | 0.780 (n 118; 0.697-0.845), leaky toward r1b |
| gate set (r1b TEST), combined | 0.664 (n 116; 0.574-0.743), leaky toward r0 | 0.608 (n 120; 0.519-0.691) |
| gate set, FDEM only | 0.716 (n 95) | 0.653 (n 98) |
| **CLEAN, combined** | **0.655** (n 55; 0.523-0.766) | **0.603** (n 58; 0.475-0.719) |
| CLEAN, unflagged by both (fixed set, n 55) | 0.655 | 0.618 |

More elevated labels did not raise the coverage of elevated houses that the model does not flag. On every set, r1b is
equal or lower (the intervals overlap).

## 6. Why the county labels do not help (C7 diagnostic)

The test is r0's point error on r0's TEST blocks: houses and blocks r0 never trained on.

| source | elevated | era | n | MAE | median error |
|---|---|---|---|---|---|
| FDEM | no | all | 1,089 | 0.811 | +0.10 |
| county | no | all | 114 | 1.284 | +0.42 |
| FDEM | yes | ≥2015 | 221 | 2.134 | −0.84 |
| county | yes | ≥2015 | 30 | 3.178 | −1.82 |
| county | yes | ≤2009 | 39 | 4.021 | −2.02 |

- The county labels are harder within the same era and class. Their errors are biased toward a higher floor than the
  model predicts.
- Where the county and FDEM hold the same certificate, they agree (§3). So the floor rule is not the cause.
- The cause is the population the county adds (1,416 buildings FDEM lacks). That population is not identified.
- **Untested hypotheses:**
  - county point placement (parcel point vs building);
  - multi-unit buildings;
  - certificates older than the 2018 lidar for buildings changed since;
  - post-2018 construction.

## 7. Licence and terms notes

- **County layer:** no licence or terms text; tagged `pinellas_county_ec:terms_unread`. Before any product use, read
  the county's terms or ask Pinellas County Public Works.
- **Personal data:** never fetched (allowlist). The layer description's steward contact is not reproduced.
- **`STR_PIN`:** stays in the raw pages under `data/` (gitignored) only.
- **FDEM rows:** keep r0's handling (`fdem_certificates:terms_unread`).

## 8. Suggested next steps (not done; owner to decide)

1. Make the block split stable across label batches, for example by keeping r0's assignment for existing blocks and
   drawing only new blocks, or by hashing the block id. Until then, the gate compares a candidate against a baseline
   that trained on part of the test set. This affects every future label batch, not only r1b.
2. Before reusing the county labels, find out why the new elevated buildings are harder. Two checks:
   - point-to-footprint placement on a sample;
   - certificate date against the 2018 lidar and the Overture footprint vintage.
3. The 62 FDEM labels where FDEM holds the county's NGVD29 number are probably correct (lidar check, §2). No action on
   r0.
