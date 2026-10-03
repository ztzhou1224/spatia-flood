# Harris County mini-pilot (2026-10-03): does the Florida result hold?

A quick, non-image check run before the full pilot (`docs/01-plan-harris-pilot.md`), on two of its
three areas. Every number below is from `evaluate.py` (output in `eval_v2_output.txt`) or the
diagnostics noted. **The image step (Mapillary) is not in these numbers yet**; rows marked
SIMULATED add a noisy copy of the true height, as in the Florida backtest.

## Setup

- **Areas**: B Cypress Creek (-95.580,29.950 → -95.530,29.990; newer slab subdivisions) and
  C Clear Lake (-95.130,29.530 → -95.080,29.570; older, coastal, some raised houses).
- **Answer key**: HCFCD layer 23 Cyclomedia front-door elevations (`Location = 'Front Door'`), SFR
  via layer 24, captured 2018-03 → 2020-01, ft NAVD88 GEOID12B. Headline = `Ht_Precision` ≤ 6
  (read as inches; tiers A+B). Target is the **front-door floor**, not the FEMA lowest floor.
- **Ground**: USGS 3DEP 1 m DEM, project TX_CoastalRegion_2018_A18 (GEOID12B, EPSG:26915), in a
  0.5–2.5 m ring outside the HCAD 2017 footprint (`ground.py`). Coverage: 98.2% (B), 97% (C) of
  front-door houses.
- **Design, copied from Florida**: a random 10% (or 25%) of houses play "has a certificate"; every
  other house is estimated. Neighbour values come only from that pool, never the house itself.
  Models train on pool houses in other 1 km blocks (5 group folds) and are scored on non-pool houses.
  (A first run that took neighbours only from other blocks was discarded: neighbours ended up
  hundreds of metres away and train/test features differed.)

## Results (MAE in ft, precision A+B, 10% certificate pool)

| Method | Florida backtest (floor − BFE) | B Cypress Creek | C Clear Lake |
|---|---|---|---|
| Neighbour median | 1.00 | 0.58 | 0.98 |
| ML, no ground | 0.86 | 0.61 | 1.24 |
| Lidar ground + typical height (no neighbours) | — | 0.40 | 0.95 |
| Lidar ground + neighbours' height | — | 0.34 | 0.83 |
| ML + lidar ground | 0.56 (ground SIMULATED) | **0.27** (real lidar) | **0.76** (real lidar) |
| ML + lidar + image σ 0.72 ft (SIMULATED) | 0.37 | 0.25 | 0.71 |
| within 1 ft, ML + lidar ground | 87% (sim.) | 98% | 90% |

With a 25% pool: B 0.26, C 0.75 (ML + lidar); neighbour median B 0.45, C 0.87.

## What holds and what changed

1. **Lidar ground is the big step, now with real lidar, not a simulation.** Neighbour-only → ML
   + lidar: B 0.58 → 0.27 ft, C 0.98 → 0.76 ft (within 1 ft: C 73% → 90%).
2. **Neighbour-only accuracy matches Florida in the mixed area** (C 0.98 vs FL 1.00) and is better in
   uniform subdivisions (B 0.58).
3. **ML without new information does not help** (no-ground ML is worse than the plain neighbour
   median in both areas), as in Florida. Once ground features exist, ML beats the simple rules
   (B 0.27 vs 0.34), so "the algorithm barely matters" holds only without ground.
4. **The remaining error is raised houses.** Front door > 3 ft above the lowest adjacent grade:
   1.0% of houses in B, 7.8% in C (4.7% > 5 ft). Lidar and neighbours cannot see them; they drive
   C's error and its −0.3 ft bias. That is the job of the image step.
5. **The simulated image reading helps little here** (C 0.76 → 0.71) because each model trains on only
   ~250 local certified houses; the Florida model had ~50 k. A real reading would also be used
   directly (LAG + measured height) for the raised houses, so this is a lower bound.
6. **Ground epoch matters**: the 2024 QL1 DEM (GEOID18) sits a median 0.19 ft below the 2018 one in
   10–30 m rings around the B houses (subsidence plus the geoid change). A product must name the DEM
   epoch and geoid per value.

## Limits

- Two areas, one county, front-door target. Ground epoch 2018 vs truth 2018–2020. No stale-truth
  (raised since capture) screening; no BFE triage yet (needs the FIRM join).
- Pool membership is random; real certificates are not (Florida's are self-selected).

## Reproduce

```
python fetch_hcfcd.py B -95.580 29.950 -95.530 29.990   # and C -95.130 29.530 -95.080 29.570
# download the 1 m DEM tiles listed by the TNM API for each bbox into data/harris_mini/<area>/
python ground.py B ; python ground.py C
python evaluate.py B C
```
