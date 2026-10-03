# Who flooded in Harvey: FEMA zone vs floor vs water (2026-10-03)

Question (owner, 2026-10-03): is the FEMA zone enough to identify flood risk, or is the floor the
key? We test it on what actually happened in Hurricane Harvey (Aug 2017) in the two mini-pilot
areas: **B Cypress Creek** and **C Clear Lake**. Every number is from `harvey.py`
(`harvey_output.txt`) or `harvey_depth.py` (`harvey_depth_output.txt`) unless noted.

## Data

- **Who flooded**: HCFCD layer 22 "Flooded Structures" (Harvey, Allison 2001, Tax Day 2016, …;
  sources: county, city, FEMA claims/IA, phone bank). Most records carry no parcel number, so each
  point is matched to the nearest single-family footprint within 25 m (88% of points in B, 89% in C
  matched; the rest are other building types or unlocated). Street addresses are dropped at ingest.
  The list is incomplete: not every flooded house reported.
- **FEMA zones**: current effective NFHL (layer 28), footprint any-touch. **Not the map in force
  during Harvey everywhere**: B's panels are effective 2013-10-16 (LOMRs 2014, 2018 ×2, 2021); C's
  13 panels span three county DFIRMs, eight of them effective 2019-08-15 (after Harvey).
- **Floor**: the HCFCD Cyclomedia front-door elevation (captured 2018-03 → 2020-01, after Harvey),
  and our **estimated** floor: 2018 lidar ground + median door height of the 5 nearest houses from a
  random 10% pool (the house's own value never used).
- **Water**: PRIMo hindcast of Harvey (Schubert, Luke, AghaKouchak, Sanders; UC Irvine;
  Zenodo record 7011402, CC0): simulated maximum depth 2017-08-26 → 30, ~3 m grid, NAVD88. Water
  level at a house = median of (depth + 2018 lidar ground) over wet cells within 10 m of the
  footprint. It is a model, not observed water. USGS surveyed high-water marks were too sparse to
  use (3 in B, 10 in C).

## 1. The FEMA zone misses most of the flooded houses

| | B Cypress Creek | C Clear Lake |
|---|---|---|
| Harvey-flooded single-family houses (matched) | 445 | 665 |
| … outside the SFHA (current map) | **88%** | **74%** |
| Flood rate inside SFHA / 0.2% zone / minimal-hazard X | 30% / 34% / 4.3% | 20% / 12% / 17% |
| Harvey points outside the SFHA (all building types, point location) | 85% of 614 | 67% of 1,068 |

In B the zone does separate risk (SFHA and 0.2% houses flooded 7–8× as often as minimal-X houses),
but minimal-X houses are so numerous that they hold 61% of the flooded ones. In C the zone barely
separates anything.

## 2. Floor vs the 1% flood level (BFE) predicts nothing for Harvey

"Floor minus BFE" ranks flooded houses no better than chance (AUC 0.50 in B, 0.54 in C; ground
minus BFE 0.51 / 0.66). Harvey was far beyond a 1% event, and the BFE is only one water level.
Single terrain signals are weak (AUC 0.51–0.65), and a logistic model of zone + terrain does not
transfer between 1 km blocks (AUC 0.41–0.56): Harvey flooding followed drainage paths that terrain
statistics do not capture.

## 3. Floor vs the actual (simulated) water level works where the water model is good

| ROC AUC (0.5 = no skill) | B | C |
|---|---|---|
| Simulated depth next to the house | 0.84 | 0.75 |
| Simulated water minus **measured** floor | **0.89** | 0.59 |
| Simulated water minus **estimated** floor (lidar + neighbours) | **0.89** | 0.64 |

Cypress Creek, flood rate by simulated water minus measured floor:

| Water vs floor | Houses | Flooded |
|---|---|---|
| ≥ 1 ft below the floor (or dry) | 4,174 | 1.2% |
| 0–1 ft below | 1,712 | 9.8% |
| 0–0.5 ft above | 151 | 36% |
| 0.5–1 ft above | 32 | 84% |
| 1–2 ft above | 53 | 87% |
| 2–4 ft above | 40 | 75% |

With the estimated floor the same pattern holds (0–2 ft above: 54–78%; 2–4 ft above: 93%).
Calling "water above the floor" a flood gives precision 0.56–0.66, recall 0.44–0.46 in B.

**Clear Lake is weaker**, for two visible reasons:
1. **Houses raised after Harvey.** The floor was measured 2018–2020. Among flooded houses where the
   simulated water stayed ≥ 1 ft below the measured floor (282), 28% have a door > 3 ft above the
   ground, against 7% of the dry houses in the same bin. The 136 houses with a door > 5 ft up
   (median built 1982) flooded at 56%. Many were likely elevated after flooding, so a post-event
   floor understates their Harvey exposure. Dropping houses with a door > 3 ft up only lifts the AUC
   to 0.64, so this is not the whole story.
2. **The water model is less reliable near the bay**: flooded houses there show deeper simulated
   water (median 1.37 ft) than dry houses (0.75 ft), but a water level ≥ 1 ft below their floor.
   Storm-surge and bayou backwater are harder to simulate than Cypress Creek's riverine flooding.

## What this means for the product

1. **The zone alone is not a risk measure.** In these areas 74–88% of the houses that flooded were
   outside the SFHA. Keep the zone for rules (mandatory purchase, permits, the 50% rule), not as the
   risk answer.
2. **Floor height matters, but only against a real water level.** Floor vs the BFE told us nothing
   about Harvey; floor vs a simulated water surface ranked flooded houses at AUC 0.89 in Cypress Creek.
   The product needs **several water levels per house** (10% → 0.2% events, surge, rain ponding),
   not one BFE.
3. **Our estimated floor is good enough for this job**: in B it ranks as well as the measured floor
   (0.889 vs 0.890), with no image and without the house's own measurement.
4. **The weakest link is now the water model**, not the floor (Clear Lake). Candidate sources:
   FEMA Risk MAP depth grids, Harris County's MAAPnext studies, commercial flood models, or our own.
5. **Measured floors go stale after floods**: houses get raised. Every floor value needs its
   capture date.

## Limits

- Two areas, one event; the flooded list is incomplete and mixes sources; the water is a model;
  the floor was measured after the event; the FEMA map is today's, not 2017's, for some C panels.
- AUC measures ranking, not calibrated probabilities.

## Reproduce

```
python fetch_hcfcd.py B -95.580 29.950 -95.530 29.990 21 22   # and C -95.130 29.530 -95.080 29.570 21 22
python fetch_nfhl.py B -95.585 29.945 -95.525 29.995          # and C -95.135 29.525 -95.075 29.575
python harvey.py B C
python harvey_depth.py B C   # reads the hindcast over HTTP range requests (Zenodo 7011402, HU10.tif)
```
