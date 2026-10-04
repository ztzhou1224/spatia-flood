# How much of the US coast can the core method cover? (2026-10-04)

Core method (from `RESULTS.md`): floor = 3DEP lidar ground + NSI foundation height (+ certificates /
measured inventories where they exist); water = FEMA maps + NOAA coastal layers (+ modelled depth grids
where they exist). Here we measure the national inputs' coverage of the coast.

**Coast** = the 474 counties with FEMA National Risk Index coastal-flooding expected annual loss > 0
(`fema_nri_county.CFLD_EALT > 0`; includes Great Lakes shores); 464 of them have residents in the grid
below. **Weight** = night-time residents on H3 r10 cells (`us_population_h3.pop_night`, 9.19 M cells,
137.7 M residents). Every number is from `coast_cov.py` / `coast_fema.py` (spatia-data layers read from
R2; outputs `coast_coverage.csv`, `coast_fema.csv`).

## Coverage of coastal residents

| Input | Share of coastal residents covered | Notes |
|---|---|---|
| Any 3DEP lidar (USGS WESM project areas) | **99.0%** | `us_3dep_lidar_availability` |
| 3DEP lidar QL0–2 with a 1 m DEM that meets spec | **96.9%** | gaps: Mississippi coast 0.3%, Oregon 49%, Alaska 79%, Washington 87%, Florida 92% |
| NSI building inventory | all states (national USACE inventory) | foundation defaults; matched 94–97% of houses in the Harris test |
| FEMA digital flood map (NFHL) in the county | **461 of 464 counties** (~100% of residents) | zone + BFE; unshaded Zone X is often not drawn, so cell-level "mapped" share (71%) understates it |
| NOAA Sea Level Rise Viewer footprint | **83.5%** | `noaa_slr_inundation_footprint`; no Great Lakes; Oregon 54%, Alaska 74% |
| NOAA hurricane surge maps (SLOSH MOM, Cat 1–5) | Texas → Maine, Puerto Rico, USVI, Hawaii, S. California | not Great Lakes, not WA/OR/AK, not N. California (NHC national surge page) |
| Measured floors (certificates / inventories) | Florida ~206 k ECs + ~60 k local; North Carolina 5.19 M buildings (~181 k measured); Harris County 1.19 M; NYC 0.86 M | earlier verification (`docs/00-summary.md` §7) |

Largest coastal states by residents (share with QL0–2 1 m lidar / NOAA SLR footprint):
CA 26.4 M (99.7% / 100%), FL 18.4 M (91.5% / 99.9%), NY 16.5 M (100% / 83.2%), NJ 8.4 M (100% / 100%),
TX 8.2 M (97.6% / 89.2%), WA 6.0 M (86.7% / 100%), VA 5.5 M (100% / 85.2%), MD 5.5 M (100% / 80.8%),
MA 5.4 M (100% / 100%), LA 3.3 M (100% / 98.5%). Full table: `coast_coverage.csv`.

## What this means

- **Floor estimation (lidar + NSI) can cover ~97% of coastal residents today** at the quality tested in
  Harris County (0.36–0.80 ft MAE without certificates). The gaps are specific and listed (MS coast,
  Oregon, parts of AK/WA/FL), where older or non-spec lidar would need a coarser fallback and wider bands.
- **Water: FEMA maps everywhere; NOAA still-water (SLR) for 84% and hurricane surge for the Gulf and
  Atlantic coasts.** These cover the regulatory and coastal-surge questions. Inland and rain flooding
  inside coastal counties (what drove Harvey) still needs modelled depth grids (FEMA/county studies or our
  own model), which is the open item in `../water/`.
- **Measured floors exist for FL, NC, Harris County and NYC** — the training and calibration base; they
  cover a large share of the hurricane coast's single-family stock but not most of it.

Limits: population is a proxy for housing; WESM areas are project extents (data voids inside a project
are not visible here); the coastal definition includes Great Lakes counties.
