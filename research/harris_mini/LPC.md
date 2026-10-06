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

## Imagery for the triage list: Bee Maps, several frames per house (2026-10-05)

Scripts `beemaps_multi.py C 6 150 3000`, `vlm_multi.py C` (Gemini, prompt v3), `eval_multi.py C` (output
`eval_multi_output.txt`). Houses: the 317 on the triage list (out-of-fold model > 2 ft or an appraisal basement /
lower level; fixed before any image was read; it holds 164 of the 198 raised houses) and 150 random unflagged houses.
Up to 6 diverse forward-camera frames per house (8-45 m, unobstructed, in the field of view). Images and reads stay in
`data/` (provider=beemaps).

- **Coverage is the limit, not price.** Any Bee Maps frame within 60 m: 11% of triage houses, 33% of control houses.
  A usable frame: 7 of 317 triage houses (2.2%) and 14 of 150 controls (9.3%). 56 image views were downloaded in
  total ($0.005 each). Captures 2025-12 to 2026-08.
- **None of the 164 raised houses got a usable frame.** All 21 houses seen are not raised (door <= 3 ft), so the
  imagery cannot be scored on the houses it was meant for.
- On the 15 houses with an image door height (none raised), the reading is worse than the lidar + records model
  (MAE 1.10 vs 0.24 ft); the image "raised" vote flagged 10 of the 21 non-raised houses (false positives). Image story
  count agrees with the appraisal record for 71% (15 of 21).
- Verdict for Clear Lake: Bee Maps dashcam coverage misses the raised neighbourhoods (waterfront and side streets)
  entirely; more frames per house cannot help where there are no frames. The evidence that does reach those houses is
  the lidar point cloud and the appraisal record. Imagery for them needs another source (see
  research/coverage/IMAGERY_SOURCES.md) or field capture.

## Out-of-area test: Cypress Creek (B) (2026-10-05)

Script `eval_transfer.py` (output `eval_transfer_output.txt`); B features from the same 2018 flight (20 tiles,
`lpc_features.py B`). B: 5,127 houses (tiers A+B), 49 raised (door > 3 ft), HCAD record 99.7%.

**The per-story eave choice holds out of sample.** Raised houses passing the answer-key screen, median absolute error
(median signed), ft:

| | B one-story (22) | B two-story (26) | C one-story (77) | C two-story (111) |
|---|---|---|---|---|
| eave p50 - typical | **1.42** (-0.16) | 2.89 (-1.38) | **1.14** (+0.26) | 4.11 (+0.80) |
| eave_main - typical | 1.89 (-0.18) | **2.40** (-2.32) | 2.98 (+0.95) | **2.59** (-0.22) |

So the label-free estimate "eave p50 for one-story, main eave for two-story houses" (column `split`) is what C
suggested and B confirms: about 1.1-1.4 ft on raised one-story and 2.4-2.6 ft on raised two-story houses, calibrated
without the answer key in either area. B's two-story estimates run 2.3 ft low (bias not seen in C). As an estimate
for every house it stays noisy (MAE 1.7-1.9 ft: it is for houses already flagged as raised).

**The trained model does not transfer.** C -> B: MAE 0.502 (DEM + NSI) vs 0.540 ft with the point cloud (precision
of the raised flag 0.15 -> 0.34, recall 0.45 -> 0.37). B -> C: 0.795 vs 0.796 ft, raised MAE 5.45 ft either way: B has
49 raised houses, too few to learn them. A model needs local labels; the physical eave measurement does not.

## Roof planes instead of a histogram (2026-10-06): not better

Script `roof_planes.py C B` (output `roof_planes_output.txt`): sequential RANSAC roof planes on each house's building
returns; main eave = lowest edge of the planes reaching within 1.5 ft of the ridge. Raised houses passing the screen,
median absolute error (n):

| | C one-story | C two-story | B one-story | B two-story |
|---|---|---|---|---|
| split (p50 / main eave), as above | 1.14 (77) | **2.59** (111) | 1.42 (22) | **2.40** (26) |
| roof-plane eave | **0.97** (74) | 4.14 (95) | **0.78** (13) | 3.11 (17) |

Slightly better on one-story houses, worse on two-story ones, and it finds a main roof for only 66% of B houses (96%
in C). The "planes reaching the ridge" rule does not isolate the second-story eave (typical two-story value 16.2 ft
vs 19.7 ft for the histogram main eave). The split estimate stays; a better plane rule (plane adjacency, wall
detection) would be needed to improve two-story houses.

## 2018 vs 2024 lidar: what changed, and what it does to the answer key (2026-10-06)

Scripts `lpc_change.py A` / `lpc_change.py C` (per house: ground = 10th pct of ground returns in a 0.5-2.5 m ring;
ridge / roof / eave of non-ground returns over the 2017 footprint, each as height above that flight's own ground, so
GEOID12B vs GEOID18 and subsidence cancel) and `eval_change.py A C` (output `eval_change_output.txt`). Flights:
TX_CoastalRegion_2018_A18 (2018-01..06) and TX_Houston_B24 (2024-02..2025-01; no building class, so both flights
use "non-ground > 2 m above ground"). Both flights read NAD83(2011) / UTM 15N; median ground shift 0.000 m (A),
-0.010 m (C). Records: HCAD 2018 vs the 2025 roll (`hcad_buildings.py 2025`). Answer-key capture dates: the HCFCD
`RecordedAt` field (City of Houston points, Feb-Jun 2018 for nearly all); Harris County points carry no date
(2019-11..2020-06 per the layer description). Key and dates used by the scorer only.

**What changed** ("up" = ridge, roof and eave all rose > 3 ft; houses with both flights):

| | A Meyerland | C Clear Lake |
|---|---|---|
| houses | 6,750 | 3,253 |
| up > 3 ft | 237 | 38 |
| rebuilt since 2018 (2025 record: year built >= 2018) | 452 (383 of them 1 -> 2 stories) | 7 |
| rebuilt and up | 170 (eave rise median 17.4 ft) | 0 |
| same building, up (lift in place) | 43 (eave rise median 5.5-6 ft) | 36 (median 9.2-10.5 ft) |
| of which the record changed foundation | 13 | 15 (all slab -> piers 8 ft+) |

Meyerland's change is teardowns: one-story slab houses replaced by elevated two-story houses (eave +17 ft = a story
plus the new floor height). Clear Lake's is lifts in place of about 10 ft. The rule misses many rebuilds because the
"ridge" (99th pct of non-ground returns) catches overhanging trees that construction removed: 282 rebuilds in A are
not "up", with roof +14.1 ft and eave +11.0 ft median but ridge -3.6 ft. A ridge-free rule (roof and eave > 3 ft)
catches 396 of 452 rebuilds in A; it also flags 67 houses in A and 52 in C whose records did not change (lifts the
appraiser missed, or trees: not resolved here).

**Records lag, lidar dates the lift.** In C, 17 scored houses changed from slab (2018 record) to piers (2025) with no
lidar rise: the 2018 point cloud already shows them raised (split estimate median 5.9 ft; key 8.3 ft, 11 of 17
raised). The appraiser recorded a lift that happened before the 2018 flight.

**The answer key is stale for changed houses.** Most A keys and the C Houston keys were captured in Feb 2018, the
same months as the 2018 flight; Harris County keys in 2019-20. Of houses up between the flights, the key shows them
raised for 1 of 55 (A, 2018 key) and 19 of 44 (A, 2019-20 key), 0 of 2 and 12 of 35 (C): where the key predates the
change it describes the old house. Benchmark method E error (5-fold by 1 km block, screened):

| | A: n / MAE / raised MAE | C: n / MAE / raised MAE |
|---|---|---|
| houses not up | 3,229 / 0.45 / 1.05 ft | 2,484 / 0.53 / 3.15 ft |
| houses up 2018 -> 2024 | 100 / 0.88 / 2.94 ft | 36 / 1.81 / 5.28 ft |

Changed houses are 3% (A) and 1.4% (C) of scored houses and carry two to three and a half times the error, but removing them moves the
area MAE by only 0.01-0.02 ft: change since 2018 is not the main error source. Adding the eave rise to the 2018
estimate does not give the new floor height: on changed houses whose key shows them raised it overshoots by a median
1.96 ft in C (11 lifts; E alone 2.84 ft off) and 13.55 ft in A (21 houses, mostly rebuilds whose eave rise includes a
new story). The rise flags the change; the new height must be measured from the new flight.

**Product use.** (1) Build heights from the NEWEST flight, and run the 2018 -> 2024 comparison to flag every house
that changed; a changed house needs a fresh estimate and a wider band. (2) The flag is evidence, not a prediction:
a whole-house rise with an unchanged footprint record is a lift; a rise with a new year built is a rebuild. (3) As
the user expected, it cannot see houses built raised or lifted before 2018 (C: 182 of 193 raised scored houses
show no change); those still rest on the single-flight point cloud and records.
