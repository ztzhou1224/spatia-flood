# Core floor method on New York City (Staten Island east shore), 2026-10-04

Answer key: NYC DCP Building Elevation and Subgrade (BES, NYC Open Data `bsin-59hv`), first-floor and
lowest-adjacent-grade elevations in ft NAVD88 measured from street imagery + mobile lidar. Area
−74.12…−74.06, 40.55…40.59 (Sandy-hit east shore). 6,190 single-family houses (NSI RES1) with a BES
"successfully measured" value, an NYC footprint (joined by BIN) and 2013 3DEP 1 m lidar. Numbers from
`nyc_test.py` (`nyc_test_output.txt`).

Datum check: BES grade − lidar lowest ring grade, median +0.60 ft (q10 0.01, q90 1.94), consistent.

| Method | MAE (ft) | within 1 ft | bias |
|---|---|---|---|
| National: NSI height + lidar median grade (no local data) | 2.26 | 30% | −1.48 |
| NSI only | 2.26 | 31% | −1.44 |
| Model trained in Harris County | 2.67 | 25% | −2.04 |
| Lidar + local constant (10% measured) | 2.04 | 41% | −0.61 |
| Neighbours (10% measured) | **1.58** | 54% | −0.10 |

Raised houses (floor > 6 ft above the ground, 23% of houses): national 4.47 ft MAE (bias −4.44),
neighbours 2.77 ft.

Why it fails here: the first floor sits a median 4.3 ft above the ground (q10 2.2, q90 9.2 ft) — stoops,
basements (44% have subgrade space), and houses raised after Sandy — in every NSI foundation class
(measured median 4.3–5.8 ft whatever NSI says; NSI defaults are 0.75 ft for slab, 2 ft for basement and
crawlspace). The NSI defaults and a Harris-trained model encode Gulf-coast slab housing.

Conclusion: the national default is a Gulf-coast-slab estimate. In Northeast stock it is ~2 ft off and
biased low; even 10% local measurements leave 1.6 ft. These markets need house-specific evidence
(measured inventories such as BES itself, certificates, or a raised/basement/stoop signal per house),
and regional calibration before any estimate is sold.
