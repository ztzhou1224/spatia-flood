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

**Results** (LightGBM, 5 folds by 1 km block, no neighbour certificates):

| | MAE (ft) | within 1 ft | raised houses MAE (n 198) | others MAE | raised flagged: precision / recall |
|---|---|---|---|---|---|
| DEM ground + NSI + year, footprint area | 0.745 | 88.8% | 5.02 | 0.384 | 0.62 / 0.57 |
| + point-cloud measures | **0.637** | 90.0% | **3.80** | 0.369 | **0.76 / 0.69** |

Single measures as raised-house detectors (ROC AUC): eave p50 0.90, roof p50 0.87, roof p95 0.85, roof p05 0.84,
eave p10 0.82; DEM median under the footprint 0.85; NSI foundation height 0.60. Median eave height above ground:
raised 20.5 ft, not raised 10.5 ft. Ground returns under the roof and low structures in the ring do not help (AUC
0.62 and 0.39: lidar from above rarely sees under an elevated house, and stairs are thin).

**Reading.**
- The point cloud is real evidence of elevation: it finds raised houses far better than the national inventory
  (AUC 0.90 vs 0.60) and cuts the raised-house error by a quarter (5.0 -> 3.8 ft).
- It cannot finish the job alone: a tall eave means a raised one-story OR a two-story on a slab. The remaining
  3.8 ft error on raised houses is that ambiguity.
- That makes it a triage step. Flag the houses whose eave is high (here ~180 of 2,539, 76% truly raised) and
  spend imagery (Bee Maps frames, several per house) on those only, to read steps / door / piers. Stories from
  the appraisal district would also separate the two cases.
- Limits: one area, 12 one-km blocks; 2018 flight vs 2018-2020 answer key; front-door target, not the FEMA lowest
  floor.
