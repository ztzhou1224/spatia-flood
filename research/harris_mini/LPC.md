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

## Next round (2026-10-06): newer flight, tree-robust change, finer eave reference, local sample

**Building returns without a building class.** The 2024 flight classifies only ground (2), unclassified (1),
noise (7, 18). In 2018, 95% of class-6 (building) returns are single returns vs 8-12% of medium / tall vegetation
(one C tile). `lpc_features.py AREA FLIGHT single` uses "non-ground single returns >= 5 ft above grade" as the
building. On 2018 it reproduces the class-6 features (median |difference| roof_p50 0.13-0.23 ft, eave_p50 0.08-0.23,
eave_main 0.03; `eval_flights_output.txt`) and benchmark method E (A 0.467 vs 0.463 ft, C 0.554 vs 0.551).

**The newer flight is not more accurate** (`eval_flights.py A C`, E = 5-fold by 1 km block, screened key, one
screen for all feature sets; "unchanged" = roof_p50 and eave_p50 within 1 ft between flights, label-free):

| houses unchanged between flights | A: 2018 class6 / 2024 single | C: 2018 class6 / 2024 single |
|---|---|---|
| E MAE | 0.409 / 0.412 ft (2,778) | 0.494 / 0.513 ft (2,219) |
| E raised MAE | 0.90 / 0.94 ft | 3.21 / 3.72 ft |
| E BFE side | 87.5% / 87.8% | 86.2% / 86.2% |
| same, key captured 2019-20 (nearer 2024) | 0.437 / 0.440 ft (1,131) | 0.658 / 0.696 ft (1,030) |

QL1 roof / eave measures (2024) do not improve heights of houses that did not change. Only the roof / eave side was
swapped: heights are still above the 2018 DEM ground, so whether a denser ground helps is untested. Use
the newest flight to refresh the houses that changed, not as a better measurement of the others.

**Change from single-return roofs** (`eval_flights_output.txt`; "up" = roof_p50 and eave_p50 both up > 3 ft; no
ridge, so trees cleared for construction no longer hide a rebuild):

| | A: single-return roofs / lpc_change rule | C: single-return roofs / lpc_change rule |
|---|---|---|
| rebuilt since 2018 caught | **421 / 170** of 461 | 3 / 0 of 7 |
| same building, foundation changed, up | 39 / 13 | 20 / 15 |
| same building, record unchanged, up | 86 / 29 of 6,072 | 32 / 20 of 3,123 |

The single-return rule catches 91% of Meyerland rebuilds (37% before). It also flags more houses whose records did
not change (1.4% in A, 1.0% in C); whether those are lifts the appraiser missed or noise is not resolved here (an
image check of a sample would settle it).

**A finer reference for eave-minus-stories does not help raised houses** (`eval_eave.py`, output
`eval_eave_output.txt`). Typical slab-house eave per story count over the whole area (as now) vs per year-built band
vs the 15 nearest reference houses: the nearest-neighbour reference tightens the reference spread (IQR 1.4-1.7 ->
0.95-1.2 ft) and the all-house MAE slightly, but raised houses get worse (C median abs 2.02 -> 2.89 ft, biased
-1.6 ft): in raised neighbourhoods the "slab" reference houses are raised too and absorb the lift. Meyerland's raised
houses are mostly two-story crawl-space houses (326 of 583 screened), overestimated by about 1 ft (newer, taller
walls than the reference), and one-story "slab" houses (62) underestimated by 2.6 ft: wall-height variation
(+-1.5 ft) is as large as a 3-5 ft lift, and no label-free reference removes it.

**What does: about 50 measured local houses** (`eval_local.py`, output `eval_local_output.txt`). Model from the
other two areas, refit with a local sample of 30 random unflagged + 20 flagged houses (label-free choice, as for the
bands) weighted 10x; scored on the area's other houses, mean of 20 draws:

| | A: MAE / raised MAE / recall / BFE side | B: MAE / BFE side | C: MAE / raised MAE / recall / BFE side |
|---|---|---|---|
| other areas only (benchmark E) | 0.70 / 2.12 / 0.28 / 78.3% | 0.44 / 87.4% | 0.72 / 4.95 / 0.55 / 82.0% |
| + physical override (benchmark F) | 0.81 / 2.44 / 0.55 / 82.3% | 0.46 / 87.4% | 0.68 / 3.58 / 0.68 / 84.0% |
| + 50 local houses (W 10) | **0.56 / 1.42 / 0.63 / 84.2%** | **0.37 / 92.4%** | **0.60 / 3.44 / 0.70 / 84.4%** |
| + 200 local houses (W 10) | 0.50 / 1.29 / 0.65 / 85.6% | 0.31 / 95.5% | 0.51 / 2.99 / 0.65 / 87.5% |
| within area, all labels (benchmark E) | 0.46 / 1.11 / 0.76 / 86.9% | 0.29 / 94.6% | 0.55 / 3.27 / 0.69 / 86.1% |

Fifty local houses close most of the gap to a model trained on the whole area, in all three areas; 200 come within
0.04 ft of it (C: better). Equal weight (W 1) helps much less; a model on the local sample alone is better on raised
houses (A 1.25, C 3.23 ft raised MAE) but worse overall in C (0.75 ft).
With local houses the physical override no longer improves MAE (it still adds 1-2 points of BFE side in C). The
same 50 houses calibrate the bands (BANDS.md): one survey sample per new area serves both.

## FEMA flood-insurance statistics instead of (or with) the 50 local houses (2026-10-06)

`eval_nfip.py` (output `eval_nfip_output.txt`). OpenFEMA NFIP policies, Harris County, single-family, effective
since 2024, with the elevation-certificate lowest floor and lowest adjacent grade (`coverage/fetch_nfip.py`; 76,780
rows after cleaning, 1,136 block groups). Each house gets only the statistics of its 2020 block group (tract if the
block group has < 10 records): median / p25 / p75 of LFE - LAG, share elevated, crawlspace, basement, record count.
No record is matched to a house (OpenFEMA terms, `coverage/NFIP.md`).

Coverage decides it. A: 3,140 of 3,329 scored houses have block-group statistics; B: 1,209 of 5,119 (1,221 none);
C: 862 of 2,520 (1,513 none). The Clear Lake gaps are tracts with policies but no certificate elevations (tract
48201340701: 878 policies effective since 2024, 0 with a lowest floor; OpenFEMA API count, 2026-10-06).

| model from the other two areas | A: MAE / raised MAE / recall / BFE side | B: MAE / BFE side | C: MAE / raised MAE / recall / BFE side |
|---|---|---|---|
| E | 0.704 / 2.12 / 0.28 / 78.3% | 0.443 / 87.4% | 0.721 / 4.95 / 0.55 / 82.0% |
| E + NFIP statistics | **0.626 / 1.74 / 0.42 / 80.8%** | 0.437 / 89.2% | 0.729 / 4.72 / 0.65 / 81.2% |
| E + 50 local houses (W 10) | 0.555 / 1.42 / 0.63 / 84.2% | 0.370 / 91.9% | 0.604 / 3.43 / 0.69 / 84.2% |
| E + NFIP + 50 local houses | **0.543 / 1.27 / 0.66 / 84.5%** | **0.324 / 95.9%** | 0.611 / 3.28 / 0.74 / 83.5% |
| within area, all labels: E / E + NFIP | 0.463 / 0.444 | 0.289 / 0.267 | 0.551 / 0.545 |

Where coverage is dense (Meyerland) the statistics recover about half of what 50 measured houses give (MAE 0.70 ->
0.63 vs 0.56) and add a little on top of them. In block groups with >= 30 records the gain is the same (A 0.73 ->
0.65). That argument alone is weak (renewals repeat a building ~2-3 times, so >= 30 records can be ~10 buildings);
own-certificate leakage is not tested in a committed script (the independent review reported a by-size check with no sign
of it). Where coverage is thin (C) they do not move MAE, only raised
recall. The block-group statistics describe insured certified houses, not the neighbourhood: correlation of block-
group share elevated (NFIP) with share of doors > 3 ft (key) is 0.31 (A, 24 block groups) and 0.35 (C, 6).
Reading: a free partial substitute in dense flood-zone neighbourhoods, a useful extra feature everywhere it exists,
not a replacement for a local sample. The licence question in NFIP.md ("solely for statistical research") stands.

## How far does a measured house reach? (the overlapping-circles idea, 2026-10-06)

`eval_reach.py` (output `eval_reach_output.txt`). (1) Out-of-fold residuals of method E are correlated between
houses only nearby: 0.18 / 0.37 / 0.22 (A / B / C) within 100 m, 0.06 / 0.17 / 0.02 at 250-500 m, about 0 beyond
1 km. Adding the mean residual of measured neighbours (other 1 km blocks) does not lower MAE within an area
(A 0.463 -> 0.47-0.52, C 0.551 -> 0.59-0.67; B 0.289 -> 0.27-0.29). (2) The circles case: model from the other two
areas, the west half of the area measured, the east half scored by distance from the measured half:

| east-half houses | A: pooled / refit with west half | B: pooled / refit | C: pooled / refit |
|---|---|---|---|
| 0-500 m away, MAE | 1.15 / 0.74 | 0.36 / 0.33 | 0.49 / 0.50 |
| 1-2 km away, MAE | 0.69 / 0.52 | 0.29 / 0.35 | 0.84 / 0.83 |
| > 2 km away, MAE | 0.39 / 0.34 (55 houses) | 0.27 / 0.45 | 1.75 / 1.84 |
| > 2 km away, raised MAE | 1.55 / 0.63 (2 raised) | 1.24 / 1.23 | 6.15 / 6.60 (110 raised) |

Measured houses next door help where the next stretch holds the same kind of houses (Meyerland: everywhere in the
area). They do not help, or hurt, where it does not: Clear Lake's waterfront east, where most raised houses are,
gains nothing from about 1,260 measured houses in the west half, while 50 houses spread over the whole area (30
random + 20 flagged, eval_local.py) cut raised MAE over the whole area from 4.95 to 3.44 ft (different scored
sets, so a rough comparison). Similarity of houses, not distance,
carries the labels; a sample spread over the kinds of houses beats a contiguous measured patch. Stepping onward with
modelled values in the overlap adds no information (the model would be checked against itself).

## Scattered labels: how few help, and do bands need distance to the nearest label? (2026-10-06)

`eval_sparse.py` (output `eval_sparse_output.txt`). Model from the other two areas + k measured houses of the test
area (weight 10), scored on the area's other houses (screened), mean of 20 draws. Labels arrive at random, mixed
(60% random / 40% from the label-free raised flag), or only from flagged houses (what certificates look like).

| k labels | A: MAE / raised recall (random, flagged-only) | B: MAE (random, flagged-only) | C: raised MAE (random, flagged-only) |
|---|---|---|---|
| 0 | 0.70 / 0.28 | 0.44 | 4.95 |
| 5 | 0.66 / 0.43, 0.64 / 0.41 | 0.43, 0.44 | 4.95, **4.18** |
| 10 | 0.65 / 0.37, 0.61 / 0.53 | 0.41, 0.44 | 4.74, **3.92** |
| 20 | 0.62 / 0.47, 0.58 / 0.58 | 0.40, 0.42 | 4.75, **3.53** |
| 50 | 0.58 / 0.54, 0.56 / 0.59 | 0.35, 0.36 | 4.26, **3.15** |

A handful of labels already moves the model, and BFE side improves in all but one setting (A 78.3% -> 80-84%, B 87.4% -> 89-93%,
C 82.0% -> 81.8-85.7%; 5 random labels in C: 81.8%). Which houses are labelled matters as much as how many: in Clear Lake random labels barely help
raised houses until k = 50 (few random picks are raised), while 5 labels on flagged houses cut raised MAE from 4.95
to 4.18 ft and 50 to 3.15 ft. In Cypress Creek (few raised houses) flagged-only labels lower raised recall (0.33 ->
0.19-0.29): labels should match the houses that matter in the area.

**Bands by distance to the nearest label do not help.** 90% conformal bands, Mondrian by raised flag x distance to
the nearest label (< 250 m, 250-1,000 m, > 1,000 m), residual pool from pseudo-experiments in the other two areas:
coverage and width hardly change with distance (e.g. A not flagged 0.84 / 0.86 / 0.94-0.95 coverage, width
1.55-1.72 ft, at k = 20), consistent with residual correlation vanishing beyond a few hundred metres
(`eval_reach.py`). The flag dominates, and the flagged group is where borrowed bands fail: A flagged bands are
12.5-17.8 ft wide (almost nothing decided), C flagged bands cover only 0.53-0.61 and their BFE calls are right only
55-74%. Raised-house error depends on the area's own history; only local labels on flagged houses calibrate it
(BANDS.md: 30 + 20 flagged local houses -> flagged coverage 0.81-0.84, decided calls right 90-92%).

**Product rule from this.** Estimate everywhere; feed every real number back in (weight 10); for unflagged houses,
bands from the pooled residuals are close to honest; for flagged (likely raised) houses, report "too close to call"
on the BFE until about 20 local labels on flagged houses exist, then calibrate their bands locally. Labels are worth
most on flagged houses in raised neighbourhoods (certificates are exactly that).
