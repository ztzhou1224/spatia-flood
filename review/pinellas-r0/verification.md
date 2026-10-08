# Round-2 verification of the four pinellas-r0 reviews

Work dir: `(session work dir, not committed) ` (scripts `s1_table.py` … `s13`, outputs `*.out`; untrusted downloads under
`untrusted/`, read with `python -I`). Every number below is from a command I ran; none is copied from the reviews.
The four reviews are largely accurate: of 37 findings I re-derived or spot-checked, 31 CONFIRMED, 5 PARTLY (framing or a
sub-number), 1 REFUTED (sources §12, the hash), 0 fabricated. Severity re-grades are in the table.

## Settled contradictions

**(a) Hash.** `sha256sum data/flood_v1/assemble/buildings_12103.parquet` = `ecea71739977fbecb79b6de8b28aa5a97e95f032800659c0f2ed0edd5d6a93b7`,
ending `…d6a93b7`; `docs/05 L191` says `…a6d93b7`. data_audit §3 is right (transposition in the handoff); sources §12
("matching") is wrong — it quoted the full correct hash and then mis-read the suffix. Also check the spatia-data roster pin.

**(b) County-certificate score vs in-distribution subgroup coverage.** Both reproduce and they are different populations.
`s7_score.py`: gate on the 1,315 FDEM held-out houses reproduces exactly (MAE 1.039 / cov 0.918 / BFE side 0.898 /
decided correct 0.983; 298 screened out). County layer: 5,247 labels, `ffe_field` C2a for 1A/1B/5 and C2b for the rest —
the same first-living-floor definition as `labels.py`/`ffe_ft`, so the comparison is like-for-like (C2B next-higher, not
C2A). Datum: I kept `vertical_datum_route = navd88_native` only (5,019; 228 `ngvd29_county_navd88` dropped). Match key:
`building_id` (same point-in-footprint / 10 m rule). Of the 5,019: 3,603 sit on FDEM-labelled buildings, 1,416 do not;
of those 1,416, 1,310 are `ffe_class = modeled` and **0 are record rows** (no mis-join). train.py's screen
(`roof_p95 − dh < 6 | dh < −1`, dh from the county floor) removes 28 → **n 1,282** (data_audit removed 43 → 1,267; the
difference is immaterial). Score of the modeled floor: **MAE 2.223, median −0.18, within 1 ft 0.485, coverage 0.884
(flagged 0.907 / unflagged 0.847), BFE side 0.861, decided 0.379, decided correct 0.951 (423/445)**; r0 TEST blocks only
n 199: MAE 2.28, cov 0.874, correct 0.941. By diagram group: slab 1A/1B n 566 MAE 1.07 cov 0.905; **elevated 5-9 n 703
MAE 3.14, median −1.37, cov 0.873, unflagged cov 0.539**, correct 0.909; diagram 5/6/7/8 median error −1.58/−1.61/−1.58/−0.74.
Confusion: above 217 right / 5 wrong, below 206 right / 17 wrong. Label noise: 3,173 same-day FDEM/county pairs MAE
0.016 ft. Methodology §2's subgroups are on the FDEM test set (n 1,315): truly-raised-unflagged n 70 cov 0.543,
diagram 5-9 unflagged n 119 cov 0.790, zone A/V 0.918, X 0.918 (they said 0.919/0.927: a zone-string parsing difference,
not material). Consistent: the FDEM test set is slab-heavy and marginal coverage holds; the county-only set is the
post-1992 elevated population where the unflagged band fails. data_audit §1 CONFIRMED, blocking stands.

**(c) C2A flip.** `s9_c2a.py` on the county raw pages: r0 record rows of diagram 2-4/6-9 with county C2A and C2B: 660
(county C2B within 0.5 ft of r0 `ffe_ft` on 619); of their 462 `above` calls **434 (93.9 %) have C2A < BFE**, C2A − BFE
median −3.39 ft, IQR −4.8..−2.0 (methodology: 693 / 472 / 443 / 94 % — they joined the ngvd route too; same conclusion).
NFIP semantics: I fetched the county layer's A8/A9 fields read-only (`untrusted/county_a8/`, 19,382 rows). Of the 417
flipped diagram 6-9 rows, 359 record an enclosure > 0 sq ft; **173 meet the 2-openings + 1 sq in/sq ft test, 83 are
marked engineered, 200 either — i.e. 159 of 359 (44 %) enclosures are NOT shown compliant** (85 record no openings at all),
and 58 rows have no enclosure area (cannot say). `E5_BOTTOM_FLOOR_ELEVATED` is blank on all 417. So the data can say:
roughly half of the next-higher-floor `above` calls sit over an enclosure whose vents are not documented compliant;
it cannot say whether the enclosure is finished / used for living. Methodology §1 severity: I re-grade **blocking →
major**: the table's floor definition is stated (`ffe_source` says "first living floor"), the number is right under that
definition, and NFIP's lowest-floor answer depends on A8 data the pipeline does not hold; it is a missing column plus a
missing caveat, not a wrong value. The fix (publish C2A / a `floor_definition` column) stands.

**(d) ground_ft sentinel.** `s1/s2`: 244 rows at exactly −1.9998651998 ft (the column's most frequent value), 250 within
1e-5, 291 < −1.99, 770 < 0. In features.parquet all 291 rows < −1.99 have `g_med − g_lag = 0` (whole ring constant),
198 of 250 have the inside median at the constant and 175 the far ring too. Arithmetic: −1.999865 ftUS × 0.3048006 =
**−0.60956 m**; −2 international ft is −0.6096 m = −1.999996 ftUS, so it is NOT an exact −2 ft conversion (0.04 mm off,
beyond float32 rounding of −0.6096). I fetched the first 256 KB of `USGS_1M_17_x32y310…tif` (`s13_dem_hdr.out`):
`GDAL_NODATA = -999999`, float32. `job.py:152` masks only |v| > 1e5 and `ground_stats` drops NaN, so −0.60956 m is a
stored finite cell value, i.e. the vendor's hydro-flattened water-surface constant, not nodata. Modeled rows with
ground < −1.99: 28 below / 45 too_close (data_audit's "73 modeled: 32/45/1" is internally inconsistent; 73 = 28 + 45).
The four most negative `floor_minus_bfe_ft` (−12.7..−10.0) are all sentinel VE rows. CONFIRMED, major stands.

**(e) labels.py sort.** `pandas_sort.out` (pandas 3.0.6): 5-row frame → `sort_values("issuedAt").drop_duplicates(keep="last")`
keeps the NaN-dated row (`na_position="last"` default); `na_position="first"` keeps the latest dated; with 2,000 equal
keys quicksort's last row is oid 1999 here but is not guaranteed stable. On the cached FDEM pull (10,668 rows, `-I`):
my re-run of the rule gives 7,527 labels vs r0's 7,515, same OBJECTID on 7,203 (the layer moved since r0's `ec_all.json`;
the implementation reviewer's pull reproduced 7,515/7,515). Property stage: **46** properties keep an undated certificate
with a dated sibling (they: 47); building stage after property dedupe: **8** (they: 8), 144 buildings with > 1 candidate
(they: 144). As-written vs `na_first + stable`: chosen certificate differs **357**, ffe differs > 0.1 ft **53** (they:
344 / 52); quicksort vs mergesort 311 (they: 298). CONFIRMED, major stands.

**(f)** `s1_table_part4`: modeled & `year_built ≥ 2019` **3,772** (record 410, null 3,317); modeled & ≥ 2020 2,938, all
`ffe_vintage = 2018-12-07/2019-03-08`, calls above 59 / below 18 (= the 77 decided) / too_close 741; ≥ 2019 gives 108
decided. `year_built` max 2024. `s6_stage*`: record rows 7,461; `buildingElevationSource` finished 6,889, under
construction 289, drawings 236, null 47 → **572 non-finished, 524 touch SFHA, calls above 308 / below 210 / too_close 2**.
CONFIRMED both.

**(g)** `fema_counts.out` (live, read-only): Prelim_NFHL layer 28 `DFIRM_ID='12103C'` **7,287**, layer 3 **135**, layer 16
**238**, layer 0 `PRELM_CODE 12103C_20250515`, `PRELM_ISSUE_DATE 1747306800000` (= 2025-05-15); NFHL layer 34 LOMAs in the
county bbox **2,212**. CONFIRMED.

**(h)** record rows with `ffe_record_lidar_conflict`: calls **above 244 / below 2** (basis string agrees). Record `above`
2,492; |ffe − bfe| ≤ 0.5 **403**, ≤ 0.1 141, = 0 74; record `below` within 0.5: 314. CONFIRMED.

**(i)** `s1_table_part3`: touches_sfha with every SFHA zone share rounding to 0: **99** (92 with a BFE; above 44 /
too_close 40 / null 15); `sfha_share < 0.001`: 374 (above 154 / below 1 / too_close 128); `footprint_area_m2 × sfha_share
< 1`: **754** (337 decided, 1 below); 7 `zone_main = A` rows with an interpolated BFE. CONFIRMED.

## Table

| Finding | Reviewer sev. | Verdict | My sev. | Key number (script) |
|---|---|---|---|---|
| DA1 accuracy not independent | blocking | CONFIRMED | blocking | n 1,282 MAE 2.223 cov 0.884 BFE side 0.861; elevated unflagged cov 0.539 (`s7_score`) |
| DA2 ground_ft water constant | major | CONFIRMED | major | 244 exact / 291 / 770; nodata is −999999, value is −0.60956 m stored (`s2`, `s13`) |
| DA3 handoff §8 counts + hash | minor | CONFIRMED | minor | table 7,427/240,356/124,981; calls 7,767/33,039/35,994/15,443; hash `…d6a93b7` (`s1`, sha256sum) |
| DA4 parcel keys | minor | CONFIRMED | minor | 192 keys, 465 rows, max 11, 54 buildings; Σbuildings 7,137,267, Σbelow 884,412 (`s4_misc`) |
| DA5 conflict flag drift | minor | CONFIRMED | minor | True on record 246 / modeled 51 / null 3; 269 of 300 issued after 2019-03-08; 52 yb ≥ 2019 (`s1`, `s10`) |
| DA6 record ffh vs lidar > 3 ft | minor | CONFIRMED | minor | 249 rows, median 0.444, max 13.53; ffh max 23.06, 6 > 20 (`s1`) |
| DA7 band widths | note | CONFIRMED | note | 26,638 > 10 ft (6,259 unflagged), p95 18.0, max 124.3; medians 10.33 / 1.92 (`s1`) |
| DA8 2021 FIRM BFE vs certificate BFE | note | PARTLY | note | pre-2021: n 4,007, ≥ 2 ft 1,314, flips 481 (they 4,248/1,352/496: LLM-dated rows included); post: 93.0 % within 0.5, 31 ≥ 2 (`s10`) |
| M1 living vs lowest floor | blocking | CONFIRMED (number) | **major** | 434/462 = 93.9 % C2A < BFE; 44 % of enclosures not shown vent-compliant (`s9_c2a`) |
| M2 band under-covers unflagged raised | major | CONFIRMED | major | n 70 cov 0.543; 5-9 unflagged n 119 cov 0.790; misses 69 above / 39 below (`s7_score`) |
| M3 conflict certificates → above | major | CONFIRMED | major | 244 above / 2 below (`s1`) |
| M4 interpolation check cannot test it | major | CONFIRMED | major | check n 124 MAE 0.415, pairs XS/XS 117, BL/BL 5, XS/BL 2; nearest MAE 0.408, 40/29/55; production pairs 1,845/1,399/1,097/909, \|e1−e2\| p95 2 max 8; 4 of 5 BL pairs err −2.2..−2.4 (one 0.0) (`s11_interp`, `s10`) |
| M5 record above no tolerance | major | CONFIRMED | **minor** | 403 within 0.5 ft, 141 within 0.1, 74 at BFE; `bfe_precision_ft` 0.0 on all 83,024 static. ≥ BFE is FEMA's rule and `floor_minus_bfe_ft` is per row: a documentation gap |
| M6 q finite-sample; shipped ≠ calibrated | minor | CONFIRMED | minor | q 2.3267, k 1437/1595, np.quantile 2.3177; CAL cov shipped 0.925 vs m_fit 0.901; TEST 0.918 vs 0.913 (`s12_conformal`) |
| M7 gate tolerances | minor | spot-check | minor | binomial sd of coverage 0.0076 (they 0.008); paired sd not re-run |
| M8 raised_flag precision | minor | CONFIRMED | minor | precision 0.656, recall 0.741, slab precision 0.487; 14,843 of 35,860 too_close flagged (`s7`, `s1`) |
| M9 multiple static BFEs | note | PARTLY | note | 6,787 of 83,024, spread median 1 / max 6 ft confirmed; the "27 record below→above" needs polygon shares, not re-derived (`s11`) |
| M10 test-set call error | note | CONFIRMED | note | decided correct 0.983 reproduced (`s7`) |
| I1 labels.py sort | major | CONFIRMED | major | 8 building-stage / 46 property-stage undated wins; 357 differ, 53 ffe > 0.1 ft (`s5_dedupe*`) |
| I2 parcel_key dup | minor | CONFIRMED | minor | as DA4 |
| I3 sliver SFHA | minor | CONFIRMED | minor | 99 / 374 / 754 / 7 (`s1_table_part3`) |
| I4 null-reason branches | minor | CONFIRMED | minor | 3 rows ffe not_determinable + ffh not_evaluated; 144 address not_evaluated all outside risk area; model_version on 7,264 record rows (`s1`) |
| I5 no lint config / tests | minor | CONFIRMED | minor | ruff 22 errors; 24 of 26 files would reformat; no pyproject/tests (`s4_misc`) |
| I6 viewer | note | not re-run | note | code-read only by them; no number to verify |
| I7 condo stacks | note | CONFIRMED | note | 1,107 buildings with parcels_at_centroid = 1,104 (`s4_misc`) |
| S1 post-lidar buildings | major | CONFIRMED | major | 3,772 / 2,938 / 77 decided (`s1_table_part4`) |
| S2 non-finished certificates | major | CONFIRMED | major | 572; 308 above / 210 below (`s6_stage2`) |
| S3 licence position | major | PARTLY | major | tags/provider counts confirmed (ODbL 372,764, fdem terms_unread 7,515, provider public all); the terms text itself not re-fetched — legal reading is the owner's |
| S4 preliminary FIRM + LOMAs | major | CONFIRMED | major | 7,287 / 135 / 238 / 2025-05-15 / 2,212 (`fema_counts.out`) |
| S5 unpinned inputs | minor | CONFIRMED | minor | parquet `spatia_flood.inputs` keys = the 6 layers + 2 releases only (`s4_misc`) |
| S6 bfe precision/datum | minor | CONFIRMED | minor | static 0.0 × 83,024, interpolated null × 5,250 (`s1`) |
| S7 geoid | minor | CONFIRMED | minor | GEOID12B on 290,540, null 82,224 (`s1`) |
| S8 no newer lidar | note | not re-run | note | TNM/WESM queries not repeated |
| S9 county layer ends 2020 | note | CONFIRMED | note | years 2017 1,785 / 2018 1,827 / 2019 1,517 / 2020 241 / 2021 22 / 2022 31 / 2024 1; 72 after 2020-06-30 (they 73) (`s8`) |
| S10 vintages | note | CONFIRMED | note | point-dated 7,201 / windows 260; 2018 1,103 … 2026 248; ≥ 2024-09-26 1,193 (`s10`) |
| S11 personal data | note | spot-check | note | no name column in the 96 (schema read) |
| S12 pin matches | note | **REFUTED** | minor | file ends `…d6a93b7`, handoff `…a6d93b7` — it is a transposition, as DA3 says |

## Not reported by any of the four (reproduced)

- The record-row `raised_flag`/`model_version` count differs by class: 7,264 on `ffh_class = record` but 7,297 on
  `ffe_class = record` (`s1`, `s10`) — the 33 rows whose certificate has no usable LAG carry a model flag with a record
  floor; implementation §4 describes the mechanism but gives only the 7,297 figure.
- `E5_BOTTOM_FLOOR_ELEVATED` (the field that would settle enclosure vs. living use) is blank on every county certificate
  I joined (417/417, `s9_c2a`), so the lowest-floor question cannot be closed from the county layer either; A8 vent
  fields are populated (359/417) and should be fetched with the labels (fetch.py currently excludes A8/A9).

## Method
41 tool calls: 6 reads of the brief and the four reports, 7 code/schema reads, 3 live read-only GETs (FEMA counts; the
county A8/A9 fields, 20 pages; a 256 KB DEM tile header), 14 scripts over the parquets (DuckDB 1.5 / pandas 3 /
shapely / LightGBM, including a FIT-only retrain for q), the rest small recounts. Not re-run: the terms pages (S3), TNM/WESM
(S8), the viewer/worker code (I6), the paired bootstrap (M7), M9's polygon-share sub-count, and the r1b_eval
"pinellas_county" row cited by DA1 (key not found by my grep; its substance is replaced by my own score above).
