# Evidence from the lidar point cloud and the appraisal records (Clear Lake, 2026-10-05)

Scripts: `lpc_features.py C` (point-cloud measures per house), `hcad_buildings.py 2018` (appraisal records),
`eval_lpc.py C` (output `eval_lpc_output.txt`), `eval_stories.py C` (output `eval_stories_output.txt`). Every number
below is from those outputs. Revised the same day after an independent review (see "Review fixes" at the end).

## Question

Lidar ground (the DEM) gives the ground next to a house but not its floor. Do the point cloud itself (the 2018 3DEP
flight the DEM was made from) and the county appraisal records show which houses are raised and how high the
front door sits? Both are observations or records of the specific building, public, and county-wide.

## Data

- **Point cloud.** USGS LPC TX_CoastalRegion_2018_A18, 16 tiles (1.69 GB) over area C, EPSG:6344 + NAVD88 GEOID12B
  metres, classified (ground 2, vegetation 3-5, building 6); classes 7, 9, 10, 14, 17, 18 dropped. All returns inside
  the shrunk footprint: median 8.4 per m², 86% of them building returns. Per HCAD 2017 footprint, heights in ft above
  the DEM lowest adjacent grade: building-return percentiles (roof p05/p50/p95, ridge p99), the eave band (building
  returns within 1 m inside the footprint edge: p10, p50, and `eave_main`, the highest dominant height cluster),
  ground returns under the roof, and low non-vegetation returns within 3 m. Roof measured for 3,258 of 3,259 houses.
- **Records.** HCAD 2018 building file (public record; building fields only, no owner file, appraiser notes dropped):
  stories (upper living area codes), lower-level and basement areas, foundation type. Record found for 99.4%.
- **Answer key.** HCFCD front-door FFE, precision tiers A+B: 2,539 houses, 198 with the door > 3 ft above ground.
  Scorer only. A scorer-side consistency screen flags 19 answer-key values as implausible (5 raised houses whose
  door is within 6 ft of the roof top, 14 doors more than 1 ft below the adjacent grade); results are reported with
  and without them, and they stay in the training rows.

## Results (LightGBM, 5 folds by 1 km block, 27 blocks; 95% block-bootstrap intervals)

| | MAE (ft), all | MAE, screened (95% CI) | raised MAE, screened (95% CI) | raised flagged: precision / recall (screened) |
|---|---|---|---|---|
| DEM ground + NSI + year + footprint | 0.728 | 0.682 (0.45-0.95) | 4.70 (2.72-5.76) | 0.57 / 0.57 |
| + point-cloud measures | 0.608 | 0.561 (0.41-0.75) | 3.29 (2.09-4.01) | 0.80 / 0.69 |
| + records | 0.612 | 0.565 (0.40-0.77) | 3.42 (2.10-4.31) | 0.81 / 0.70 |
| + records + eave-minus-stories estimates | **0.599** | **0.553 (0.40-0.75)** | **3.26 (2.14-3.90)** | 0.80 / 0.72 |

The intervals are wide because the raised houses are concentrated (the reviewer counted 93 of 198 in one lidar tile):
the raised-house numbers are close to one neighbourhood held out once.

**Single point-cloud measures** as raised detectors (ROC AUC): eave p50 0.90, roof p50 0.87, eave_main 0.86, ridge
0.85, roof p95 0.85; NSI foundation height 0.60. Median eave p50: raised 20.5 ft, not raised 10.5 ft. Ground returns
under the roof and low structures in the ring do not help (AUC 0.62, 0.39): the flight sees roofs, not what is under
an elevated house.

**Records alone.** Any basement, any lower level, or a two-story house on a crawl space: 94 houses flagged,
precision 0.77, recall 0.36. In Clear Lake an appraisal "basement" is an elevated lower level: 31 of 31 two-story
houses with a full basement and a lower level are raised. One-story slab houses with no lower level: 3% raised.

**Eave minus stories** (typical eave of slab houses without a lower level per story count, calibrated without the
answer key, + 1 ft NSI slab height). Typical eave: p50 10.25 / 14.28 ft (one / two stories), only 4 ft apart because a
two-story eave band mixes porch and garage roofs; `eave_main` 10.31 / 19.72 ft, 9.4 ft apart. On raised houses that
pass the screen (median absolute error, median signed error, ft):

| | one story (n 77) | two stories (n 111) |
|---|---|---|
| eave p50 - typical | 1.14 (+0.26) | 4.11 (+0.80) |
| eave_main - typical | 2.98 (+0.95) | 2.59 (-0.22) |

As a stand-alone estimate for every house both are too noisy (MAE 1.3-2.4 ft against 0.55 ft for the model).

## Reading

- The point cloud is real evidence of elevation: it finds raised houses far better than the national inventory
  (AUC 0.90 vs 0.60) and cuts the raised-house error by about 30% (4.7 -> 3.3 ft, screened).
- A tall eave alone cannot tell a raised one-story from a two-story house. The story count from the records plus the
  eave measures each work on one kind of house: eave p50 on raised one-story houses (1.1 ft), the main eave on raised
  two-story houses (2.6 ft). Using each where it works is the obvious next estimate, but that split was chosen after
  seeing these numbers; it has to be confirmed in another area (B) before it is believed.
- The appraisal record is the cheapest raised flag (77% precision, county-wide) and adds little once the point cloud
  is in the model.
- Triage for imagery: houses the model puts above 3 ft, or with a record basement / lower level, or whose eave
  estimate is > 3 ft. Imagery then only has to answer "steps / piers visible, how many stories".
- Limits: one area; raised houses concentrated in a few neighbourhoods; 2018 flight vs 2018-2020 answer key (50%
  of survey dates missing); front-door target, not the FEMA lowest floor.

## Review fixes (independent review, 2026-10-05)

- `eval_lpc.py` first overwrote the UTM `y` column with the target, so its "1 km blocks" were easting strips (first
  run 0.745 -> 0.637 ft). Fixed; numbers above are the rerun.
- HCAD basement codes BFF / BPF end in F and were missed by the lower-level flag; added (no change to the records
  flag, whose basement houses were already flagged by the foundation type).
- Water / rail / wire / bridge returns dropped; a no-op duplicate removal across tile overlaps removed (overlapping
  tiles hold different returns).
- Answer-key screen and block-bootstrap intervals added; detection counted over the houses each method scores.
- Not done yet: roof-plane fitting for a sturdier main eave; 2018 vs 2024 eave differences to find houses raised
  after 2018; per-house uncertainty bands; area B (no point-cloud tiles yet) for an out-of-area test.
