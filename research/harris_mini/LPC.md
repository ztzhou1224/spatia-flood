# What the lidar point cloud sees of each house (Clear Lake, 2026-10-05)

Scripts `lpc_features.py C`, `eval_lpc.py C` (output `eval_lpc_output.txt`). Every number below is from that output.

**Question.** Lidar ground (the DEM) gives the ground next to a house but not the floor. Does the point cloud itself,
the 2018 3DEP flight that the DEM was made from, show which houses are raised and how high the door sits?
It is house-specific evidence (an observation of that building), public domain, and covers the whole county.

**Data.** USGS LPC TX_CoastalRegion_2018_A18, 16 tiles (1.69 GB) over area C, EPSG:6344 + NAVD88 GEOID12B,
about 8.4 returns/m² on roofs, classified (ground 2, vegetation 3-5, building 6). Per HCAD 2017 footprint:
building-return heights above the DEM lowest adjacent grade (roof p05/p50/p95, eave band = within 1 m of the
footprint edge), ground returns under the roof, and low non-vegetation returns within 3 m (stairs, decks).
The roof was seen for all 3,259 front-door houses. Answer key: HCFCD front-door FFE, tiers A+B (2,539 houses,
198 with the door > 3 ft above ground), scorer only.

**Results** (LightGBM, 5 folds by 1 km block (27 blocks), no neighbour certificates):

| | MAE (ft) | within 1 ft | raised houses MAE (n 198) | others MAE | raised flagged: precision / recall |
|---|---|---|---|---|---|
| DEM ground + NSI + year, footprint area | 0.728 | 88.1% | 4.90 | 0.376 | 0.56 / 0.56 |
| + point-cloud measures | **0.610** | 90.8% | **3.57** | 0.359 | **0.78 / 0.68** |

(Correction, same day: the first version of `eval_lpc.py` overwrote the UTM `y` column with the target, so its
"1 km blocks" were 1 km easting strips; first-run numbers 0.745 / 0.637 ft, raised 5.02 / 3.80 ft. Fixed and rerun.)

Single measures as raised-house detectors (ROC AUC): eave p50 0.90, roof p50 0.87, roof p95 0.85, roof p05 0.84,
eave p10 0.82; DEM median under the footprint 0.85; NSI foundation height 0.60. Median eave height above ground:
raised 20.5 ft, not raised 10.5 ft. Ground returns under the roof and low structures in the ring do not help (AUC
0.62 and 0.39: lidar from above rarely sees under an elevated house, and stairs are thin).

**Reading.**
- The point cloud is real evidence of elevation: it finds raised houses far better than the national inventory
  (AUC 0.90 vs 0.60) and cuts the raised-house error by about a quarter (4.9 -> 3.6 ft).
- It cannot finish the job alone: a tall eave means a raised one-story OR a two-story on a slab. The remaining
  3.6 ft error on raised houses is mostly that ambiguity.
- That makes it a triage step. Flag the houses the model puts above 3 ft (here 171 of 2,539, 78% truly raised) and
  spend imagery (Bee Maps frames, several per house) on those only, to read steps / door / piers. Stories from
  the appraisal district would also separate the two cases.
- Limits: one area, 27 one-km blocks; 2018 flight vs 2018-2020 answer key; front-door target, not the FEMA lowest
  floor.

## Stories from the appraisal records: eave minus story height (2026-10-05)

Scripts `hcad_buildings.py 2018` (HCAD 2018 building file: stories from upper living area, lower-level areas,
foundation type; no owner or notes fields), `eval_stories.py C` (output `eval_stories_output.txt`). HCAD has a
building record for 99.4% of the scored houses.

**Records alone.** HCAD's own codes flag raised houses: any basement, any lower level (BAL base area lower, FGL
garage lower, ...) or a two-story house on a crawl space. That flag picks 94 houses, 77% of them raised (precision
0.77, recall 0.36). In Clear Lake a "basement" is an elevated lower level: 26 of 26 two-story houses with a full
basement and a lower level are raised. One-story slab houses with no lower level are 3% raised (60 of 1,864).

**Eave minus stories** (no answer key: the typical eave of slab houses without a lower level, per story count,
+ 1 ft NSI slab height). Typical eave p50: 10.25 ft (one story), 14.28 ft (two stories): only 4 ft apart, because a
two-story house also has first-floor porch and garage roofs in its eave band.

| | MAE (ft) | raised MAE | others MAE | raised flagged: precision / recall |
|---|---|---|---|---|
| eave p10 - typical (stories) | 1.33 | 4.92 | 1.03 | 0.42 / 0.52 |
| eave p50 - typical (stories) | 1.83 | 4.44 | 1.62 | 0.30 / 0.75 |
| GBM DEM + point cloud | 0.610 | 3.57 | 0.359 | 0.78 / 0.68 |
| + records | 0.614 | 3.67 | 0.356 | 0.79 / 0.67 |
| + records + eave estimate | **0.589** | **3.40** | 0.351 | **0.81 / 0.69** |

On raised houses, the eave p50 estimate is good for ONE-story houses (median absolute error 1.51 ft, median signed
error +0.17 ft) and poor for two-story houses (4.11 ft).

**Reading.**
- The idea works where the roof is simple: a raised one-story house is measured to about 1.5 ft from public
  lidar plus the story count, with no imagery and no answer key in the calibration.
- It fails on two-story and mixed-roof houses: the eave band mixes the upper eave with first-floor porch and
  garage roofs. The fix is to find the main (highest) eave line per footprint, not a percentile of all edge
  returns; not done yet.
- As a stand-alone estimate for every house it is too noisy (1.3-1.8 ft MAE vs 0.6 ft for the model): use it only
  where the model says raised, and let imagery settle the two-story cases.
- The records are evidence of their own: an appraiser-recorded lower level or basement is the cheapest raised flag
  (77% precision), available county-wide.
