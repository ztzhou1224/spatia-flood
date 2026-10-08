# Round-2 verification of the GIS review (gis.md) — pinellas-r0

Work dir: `(session work dir, not committed) ` (scripts `v*.py`, outputs `v*.txt`; run as
`/home/user/spatia-flood/.venv/bin/python -I <script> /home/user/spatia-flood/data/flood_v1`). Every number below is
in one of those outputs. I re-derived with my own queries (DuckDB / shapely in EPSG:26917 rather than the reviewer's
EPSG:3086; dissolved SFHA union rather than per-candidate unions).

## Table

| # | Finding | Reviewer sev. | Verdict | My sev. | My key numbers (script) |
|---|---|---|---|---|---|
| 1 | `ground_ft` = ring minimum is water / seawall / slope; `raised_flag`, modeled `ffh_ft` inherit it | blocking | **CONFIRMED** | **blocking** (for `raised_flag` + published `ffh_ft`); the −2.0 ft sentinel subset alone is **minor** | 770 < 0 ft, 507 < −1 ft, min −4.825 (612 AE / 152 VE); 7,482 cert rows: cert LAG − ring min median +0.441 (p10 −0.068, p90 +1.622), MAE 0.813; − ring median −0.147, MAE 0.508; − p10 MAE 0.58; 12.9% of cert LAGs below the ring min, 7.4% above the ring max; ring range > 3 ft: 14,197 of 15,365 modeled flagged; 510 cert rows: 253 cert-raised vs 468 model-raised (confusion: 228 cert-no/model-yes, 4 cert-yes/model-no, 15/240 agree, 23 unflagged); floor − ring **median** > 3: 214 (`v1_ground.py`) |
| 1(iv) | −1.999865 ft constant: nodata sentinel or water? | (part of 1) | **Water (hydro-flattened), not nodata** | minor | 250 `ground_ft` within 1e-5 (244 exact + 2 at −1.9998638); = −0.609560 m = −1.99987 intl ft (not a round number in either unit); `job.py:138,153` turn nodata into NaN (masked read, |v|>1e5) and `features.py:29` drops non-finite, so nodata cannot produce a value; on those 250 rows the ring median is the same constant for 194 and the footprint interior (`g_inside`) for 198, median area 72.8 m², 137 have no DOR parcel, only 51 modeled + 1 record, 19 `below`, `ring_low_share` 0.435 vs 0.135 elsewhere: structures over a flat hydro-flattened water surface (docks / boathouses / over-water buildings). Only 4 values are deeper than the constant. (`v1_ground.py`, `v1_sentinel_detail.txt`) |
| 2 | AO zones called against a neighbouring polygon's static BFE; no depth carried | major | **PARTLY** (core holds; the detail "54 … BFE 8.0 from an AE sliver, 0.24–36%" is wrong) | major | 92 `zone_main=AO`; 54 static, 38 `no_coverage`; calls 7 below / 4 above / 40 too_close / 3 null; 127 touch an AO polygon, 16 decided; 6 AO polygons all `withheld_no_elevation`. The 54 static: **21** at 8.0 ft from an AE sliver (share 0.24–49.6%), **32** at 10–13 ft from a **VE** sliver (share 0.0–47.8%), 1 at 10 ft from AE. `zones_12103_raw` has no depth column (18 cols listed); spatia-data `layer-gotchas.md:2538`: "The flood halves publish no DEPTH / VELOCITY". 4 buildings touch AH, all with a BFE (`v4_misc.py`, `v2_ao_detail.txt`) |
| 3 | Interpolation segments cross non-SFHA ground on two thirds of rows; panel-date mismatches | major | **CONFIRMED** (≈) | major | 5,250 interpolated (AE 4,102 / X 1,141 / A 7); parsed 5,250; my distance-to-L1 vs `bfe_source` max diff 1.07 m; segment L1→L2 median 252 m; segments ≥ 99.9% inside the dissolved SFHA union: **1,831 of 5,250 (34.9%)** vs reviewer 1,779 (33.9%) (≥ 95%: 2,041); > 25% outside 2,050, > 50% outside 1,110 (reviewer 2,051 / 1,109); different panel dates **85**; L1 date ≠ polygon date **268**; |e1−e2| median 0.4, p90 1.0, 31 > 3 ft; 0.3 where < 75% inside vs 0.5 fully inside (`v3_interp.py`) |
| 4 | Three FIRM effective dates | minor | **CONFIRMED** | minor | 2021-08-24: 365,809 (89,392 SFHA); 2003-09-03: 5,126 (1,880); 2009-08-18: 1,817 (971); null 12; 658 pre-2021 12103C polygons (122 SFHA); `bfe_vintage` 2003: 1,320 interpolated + 127 static (`v4_misc.py`) |
| 5 | Highest-BFE vs largest-share polygon | minor | **CONFIRMED** (559 / 1); the "1,323" is a loose count | minor | 1,508 buildings with > 1 SFHA zone element; **1,224** overlap > 1 distinct SFHA polygon carrying a static BFE (reviewer's 1,323 counts any such building with ≥ 1 BFE polygon); highest ≠ largest-share: **559** (median 1 ft, max 4; 555 AE+VE); published `bfe_ft` = highest on 559/559; calls 273 below / 175 too_close / 28 above / 83 null; **1** `below` would be at/above the largest-share BFE (`v5_bferule.py`) |
| 6 | WGS84→NAD83(2011) null transform | minor | **CONFIRMED**; Overture datum **UNVERIFIABLE from the repo** | minor | pyproj picks "Inverse of NAD83(2011) to WGS 84 (1) + SPCS83 Florida West zone (meter)", accuracy **2.0 m** (null Helmert; the only available op); EPSG:26917 path "NAD83 to WGS 84 (1)" accuracy 4.0 m; ITRF2014@2020 → NAD83(2011) offset at Clearwater dx +0.640, dy −0.635, |d| 0.902 m. Repo docs/research mention Overture's licence only (`research/coverage/fl_footprints.py:2`); nothing states Overture's datum, so "effectively ITRF" is the reviewer's assumption, not a repo-documented fact (`v6_datum.py`, `v6_itrf.txt`, `v6_overture_docs.txt`) |
| 7a | GEOID12B vs GEOID18 ≤ 0.029 ft | sound | **CONFIRMED** | — | grids present in `work_gis/grids/` (not re-fetched); NAVD88 height from h = 10 m, GEOID18 − GEOID12B at the 5 points: +0.0232, +0.0110, +0.0039, −0.0013, +0.0285 ftUS; max 0.0285 (`v7_geoid.py`) |
| 7b | Coverage-map cell sum 372,764 | sound | **CONFIRMED** | — | 1,225 cells; sums 372,764 / 290,540 / 92,243 / 7,427 / 240,356; independent `h3.latlng_to_cell(lat, lon, 8)` recount: 1,225 cells, sum 372,764, 0 mismatched cells (`v4_misc.py`) |
| 8 | Condo stacks | note | **CONFIRMED** | note | `parcels_at_centroid > 1`: 28,546 (max 1,104); 22,797 modeled; 3,395 `below`; DOR 002: 10,222 modeled of 13,409, 004: 8,881 of 10,431 (`v4_misc.py`) |

## Opinion on finding 1's severity

The evidence supports **blocking**, but for the derived columns rather than for `ground_ft` itself:

- NFIP's LAG is the lowest ground *touching* the building. A 0.5–2.5 m ring is wider than "touching", and the data
  show it reaches non-building ground in a tail, not everywhere: for the median certificate lot the ring min is only
  0.44 ft below the surveyor's LAG (p10 −0.07), but 22.8% differ by > 1 ft and 12.9% of surveyed LAGs are *below*
  the ring min, so the ring min is neither a faithful LAG nor a reliable lower bound. The ring median is closer by
  every measure here (MAE 0.51 vs 0.81) but biased the other way (−0.15 ft), i.e. it is also not the LAG.
- The sentinel/water subset (250 rows at one exact value, 51 modeled) is small and mostly over-water structures
  without a parcel; by itself it is **minor** (the data auditor's "major" overstates it; the reviewer's blocking
  does not rest on it). The other 520 sub-zero rows are genuine seawall/canal-bank captures at varying values.
- What reaches a customer wrongly is `raised_flag` and the modeled `ffh_ft`: on lots where the ring spans > 3 ft
  the model flags 468 of 487 certificate buildings as raised where the certificate says 253; 228 false "raised"
  against 4 misses. Extrapolated to the 15,365 modeled rows on such lots (14,197 flagged) that is thousands of
  wrong flags, and `ffh_ft` then means "floor above the canal" on those rows while meaning "floor above the
  surveyor's LAG" on record rows. `ffe_ft` is largely protected because the model's target is `ffe − g_lag`
  (`train.py:99`) and it learned the offset. So: blocking for `raised_flag`/`ffh_ft` semantics; `ground_ft`
  itself needs a rename/companion column and a suspect flag rather than a wholesale min→median swap.

## Reproduced things the GIS review did not state

- **`raised_flag` is model-only even on certificate rows** (`assemble.py:451` flags every eligible row from the
  prediction; the certificate is never consulted). Across all 7,427 record rows: 708 flagged raised where the
  certificate's own `ffh_ft` ≤ 3 ft, 381 unflagged where the certificate says > 3 ft (5,049 / 1,126 agree, 163
  null) (`v1_record_raised.txt`). A buyer reading `ffh_ft = 1.1 (record)` next to `raised_flag = true` sees the
  table contradict itself on 708 buildings. Severity: major (it emits contradictory values today; the fix is one
  line: derive `raised_flag` from the published `ffh_ft` when `ffh_class = record`).
- AO lots are given **VE** BFEs (10–13 ft) in 32 of the 54 static cases, not only the AE 8 ft the review names;
  the review understates its own finding.

## Method

15 tool calls: read BRIEF, gis.md and its 16 scripts/outputs, `features.py`, `job.py` (grep), `assemble.py`
(lines 150–215, 270–300, 345–365, 440–500), `train.py` (grep), file schemas; wrote and ran 7 scripts
(`v1_ground.py`, `v2`/`v4_misc.py`, `v3_interp.py`, `v5_bferule.py`, `v6_datum.py` + ITRF snippet, `v7_geoid.py`)
plus two inline DuckDB snippets; grepped spatia-data (`assets/fema*.py`, `layer-gotchas.md`) and spatia-flood docs.
Not checked: the DEM tile header (no `.tif` on disk and no rasterio in the venv, same as the reviewer), anything on
R2, the geoid grids' provenance (reused the reviewer's downloaded files).
