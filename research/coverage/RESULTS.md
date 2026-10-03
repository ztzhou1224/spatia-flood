# Coverage strategy test: floor and water from national inputs only (2026-10-03)

Owner (2026-10-03): "the job here is not only to find which way is better, but find a strategy to
cover as much property as possible, because neighbors elevation certificate is not available in
other place." So every method here uses only inputs available (or computable) across the US, and
anything learned comes from the OTHER pilot area. Areas: B Cypress Creek, C Clear Lake (Harris
County). Every number is from `evaluate_cov.py` (`coverage_output.txt`) or the command named.

## Inputs (all national)

| Input | Source | What we take |
|---|---|---|
| Ground | USGS 3DEP 1 m lidar DEM (2018 here) | lowest / median ground beside each footprint, depression depth, relative elevation (1 km window) |
| Building | USACE National Structure Inventory (NSI) API | foundation type, default foundation height, year built, stories, NSI ground; matched to 97% (B) / 94% (C) of houses |
| Streams, water | USGS NHDPlus HR (flowlines, areas, water bodies) | ground above the nearest stream / water surface (a HAND-like "REM"), distance |
| FEMA | NFHL | zone (footprint any-touch), BFE |
| Coastal surge | NOAA NHC National Storm Surge Risk Maps v4 (SLOSH MOM, high tide) | lowest hurricane category that floods the house, depth by category |
| Not national, reference only | PRIMo Harvey hindcast (UC Irvine, Zenodo 7011402) | simulated Harvey water level |

Checked and **not usable** here: NOAA OWP flood-inundation (HAND) datasets on AWS are requester-pays
(need an AWS account); Harris County's MAAPnext draft floodplains cover west/central Houston only
(extent ymax 29.94°, xmax −95.31°), not our two areas; FEMA Base Level Engineering depth grids exist
for much of Region 6 through the estBFE viewer but were not pulled in this round.

Labels: HCFCD flooded structures (Harvey 2017, Tax Day 2016, Allison 2001, …) matched to footprints
within 25 m: B 470 of 6,189 houses flooded in some event (Harvey 389), C 653 of 3,259 (Harvey 633).

## 1. Floor without neighbours

Front-door FFE error, ft (precision A+B). "Neighbours" needs local certificates and is the reference.

| Method | B MAE | B within 1 ft | C MAE | C within 1 ft |
|---|---|---|---|---|
| Neighbours (10% local certificates) + lidar | **0.25** | 98% | **0.73** | 91% |
| NSI foundation height + lidar **median** ground | **0.36** | 96% | 0.80 | 88% |
| NSI ground + NSI foundation height (no lidar work) | 0.35 | 96% | 0.85 | 87% |
| GBM trained in the other area (lidar + NSI features) | 0.45 | 95% | **0.78** | 91% |
| Constant height from the other area + lidar lowest ground | 0.52 | 90% | 1.05 | 80% |
| NSI foundation height + lidar **lowest** ground | 0.76 | 74% | 1.02 | 78% |

- **Without any neighbour certificate, the floor is within ~0.1 ft of the neighbour method**: NSI's
  default foundation height on the median lidar grade gives 0.36 ft (B) and 0.80 ft (C).
- NSI's height is measured from typical grade, not the lowest adjacent grade: adding it to the
  lowest point loses 0.4 ft (B). Use the median ring grade.
- NSI does not know which houses are raised: of houses whose door is > 3 ft above the ground, NSI
  calls 66 of 75 (B) and 151 of 228 (C) slab. Raised houses stay the main floor error everywhere.

## 2. Water: which national signal ranks the houses that flooded?

ROC AUC, flooded in any recorded event (Harvey alone in brackets); 0.5 = no skill.

| Signal | B Cypress Creek | C Clear Lake |
|---|---|---|
| FEMA zone | 0.61 (0.64) | 0.52 (0.52) |
| BFE − floor | 0.32 (0.25), *inverted* | 0.57 (0.57) |
| Ground above nearest stream / water (REM) | 0.48 (0.46) | 0.59 (0.60) |
| Depression depth (lidar) | 0.59 (0.57) | 0.52 (0.51) |
| Relative elevation (1 km) | **0.66 (0.62)** | **0.63 (0.63)** |
| NOAA surge, lowest flooding category | — (inland) | 0.56 (0.56) |
| **Harvey hindcast water − floor** (physical model, event-specific) | (**0.89**) | (0.59) |

A combined logistic model of the national signals:

| | local, 1 km block CV | trained in the other area (a national model) | FEMA zone alone |
|---|---|---|---|
| B, any event | 0.69 | 0.54 | 0.61 |
| B, Harvey | 0.74 | 0.50 | 0.64 |
| C, any event | 0.63 | 0.51 | 0.52 |
| C, Harvey | 0.63 | 0.47 | 0.52 |

- **Static national proxies do not identify who floods.** The best single one (relative elevation)
  reaches AUC 0.63–0.66; FEMA's BFE is even inverted in Cypress Creek, where the recorded flooding was
  mostly away from mapped streams.
- **A statistical risk model learned in one area does not transfer** (AUC 0.47–0.54 in the other area).
  Flooding follows each place's drainage network and storm, not general terrain statistics.
- **A physical water model does** (Harvey hindcast − floor: 0.89 in B), and there the national floor
  estimate works as well as the measured floor (`../harris_mini/HARVEY.md`).

## Strategy this points to

1. **Floor: national, cheap, good enough.** Lidar median grade + NSI foundation height, or a model
   trained where certificates exist, gives 0.35–0.8 ft MAE with no local certificates. Certificates /
   measured inventories (FL, NC, Harris, NYC) refine it where they exist, and are the training data.
   Spend extra floor effort only on finding **raised houses** (NSI misses them).
2. **Water: the coverage problem is here, and it needs physics, not proxies.** Floor height only pays
   once compared with a modelled water surface for several return periods. Options, by cost:
   - public modelled depth grids where they exist: FEMA Risk MAP / BLE depth grids (Region 6 estBFE,
     other states), county studies (Harris MAAPnext), NOAA surge (coast);
   - an open hydrodynamic rain-on-grid model on 3DEP lidar with NOAA Atlas 14 design storms
     (e.g. LISFLOOD-FP, HEC-RAS 2D, TRITON), county by county;
   - a commercial national flood model (First Street, Fathom) under licence.
3. **Static proxies** (relative elevation, depressions, distance to water) are a screening layer and
   explain little on their own; FEMA zone remains a rules layer.

Next test suggested: run an open rain-on-grid model on Cypress Creek's 1 m lidar with an Atlas 14
100-year storm and with Harvey rainfall, and check whether it reproduces the hindcast's ranking
(AUC 0.89). If it does, water becomes buildable anywhere 3DEP lidar exists (~ the whole CONUS).

## Addendum: NOAA Sea Level Rise Viewer inundation (already in spatia-data)

spatia-data publishes `noaa_slr_inundation_h3` (stable; NOAA OCM Sea Level Rise Viewer, ocean-connected
land at 0–10 ft above MHHW in 0.5 ft steps, per H3 r10 cell, Texas partition present). Joined to the
Clear Lake houses by r10 cell (one-off script run 2026-10-03; cells read from R2 over the S3 API):
756 of 3,259 houses sit in a cell connected at ≤ 10 ft above MHHW. Ranking skill on the recorded floods
is low (AUC 0.55, any event and Harvey), but as a flag it separates: houses in cells connected at
≤ 5 ft flooded at 41% (any event) vs 18% elsewhere. It is a coastal still-water screen (no rain, waves
or surge), so it complements the NOAA surge maps on the coast; it does not cover inland rain flooding,
which drove the recorded events here. It is not NOAA OWP's riverine flood-inundation (HAND/FIM) data.

## Limits

Two areas, one county; the flood list is incomplete and event-dominated (Harvey); the floor truth
is the front door, measured after Harvey; NSI fields are modelled defaults; surge maps are
hypothetical hurricanes, while the recorded floods here were rain-driven.

## Reproduce

```
python fetch_nsi.py B -95.580 29.950 -95.530 29.990      # and C
python fetch_arcgis.py B nhd_flow https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/3 -95.62 29.92 -95.49 30.02
#   (also /8 nhd_area, /9 nhd_wb; C with -95.17 29.50 -95.04 29.60)
# NOAA surge: https://www.nhc.noaa.gov/gis/hazardmaps/US_SLOSH_MOM_Inundation_v4.zip, crop Cat 1-5 to data/surge/<AREA>_cat<k>.tif
python features.py B C
python evaluate_cov.py
```
