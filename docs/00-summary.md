# Summary: how we got here (2026-10-02 / 03)

This records what was investigated and measured in the spatia-report / spatia-data session that led to
this repo. Every figure below was produced by a command or query run in that session; the scripts
for the backtests are in `research/`.

## 1. The question that started it

Stored spatia-report report `rpt_e61922f0ebe0` — 27536 Riverbank Dr, Bonita Springs, FL 34134
(parcel 334725B10290A0260, Lee County). The buyer asked: *is the house elevated above the flood
level?* The report could not answer.

What the report had:

| Fact | Value | Grade |
|---|---|---|
| FEMA zone | 100% Zone AE | DETERMINATION, HIGH |
| BFE | 10 ft NAVD88 (static BFE on the covering polygon) | SCREENING |
| Ground (USGS 3DEP 1/3″, ~10 m) | mean 7.4 ft, lowest cell 5.7 ft | SCREENING, LOW |
| Error band of that DEM | ±5.5 ft (1.96 × USGS's national 0.82 m RMSE) | — |
| Elevation Certificate on file (FDEM inventory) | none for this address | SCREENING |
| Year built | 1999 (FL DOR `act_yr_blt`) | — |

Why it could not answer:

1. It measured **ground, not the floor**. "Elevated above flood level" is about the lowest floor.
2. Both ground figures sat inside the ±5.5 ft band, so even the ground side was undeterminable.
   Lee County's real lidar is far better than the national figure, but the 10 m product does not say
   which survey covers a spot.
3. The certificate inventory deliberately publishes **no numbers** (spatia-data excluded them: "the
   source extraction does not establish a reliable unit contract").

When ground alone *does* answer: if the **lowest** ground (or the ground at the structure) is above
the BFE by more than the error band, there is no below-grade floor, the zone is not V / Coastal A,
and both are in the same datum — then the structure is above the BFE (that is FEMA's structure LOMA
test on lowest adjacent grade).

## 2. Elevation Certificates (ECs): the data exists

- FDEM's public FeatureServer (built on Forerunner) carries the numeric fields that spatia-data
  dropped: `topOfBottomFloor` (206,255 of 210,888 rows filled), `lowestAdjacentGrade` (205,241),
  `baseFloodElevation` (169,133), `buildingDiagramNumber`, `verticalDatum`, FIRM panel dates.
  Data quality: 4,847 rows have a floor > 100 ft (unit/entry errors), so a plausibility filter is
  required. Datums: NAVD88 156,745; NGVD29 50,575.
- Neighbours of the subject: 27516 Riverbank (2026 form, finished construction) floor **9.7 ft vs
  BFE 10**, LAG 8.1; 27591 Riverbank (2022) floor **10.3 vs BFE 11** (2008 map), LAG 7.2. Typical
  local floors sit right at the BFE.
- `propertyId` in that layer is a document-portal UUID, never a parcel number (the report's search
  had matched a parcel ID against it). Fix to the column descriptions is on spatia-data branch
  `fix/ec-propertyid-description` (commit 51b2572, not merged).

## 3. Engine plans written (spatia-report, branch `plans/ec-match-and-construction-era`)

Both passed the GIS expert review **with changes** (folded in). Neither is built; both wait on
spatia-data declarations.

- `records_at_address`: candidates within 100 m of the parcel outline (projected metres), identity
  by address — deterministic comparator first, Typesafe `jev` only for non-exact cases (MEDIUM cap),
  fail closed until spatia-data declares site-address columns (`ColumnHint.site_address_part`).
- Construction era vs flood map: relates year built to the FIRM. GIS corrections: the CSB
  `originalEntryDate` is the **CRS** entry date (NFIP entry is `regularEmergencyProgramDate`);
  Bonita Springs incorporated 1999-12-31, so a 1999 house was permitted by Lee County → the
  "built after the first FIRM" record is NOT_DETERMINABLE there. Needs a new
  `nfip_community_status` layer (OpenFEMA Community Status Book) and a `quantity_kind` column token.
- spatia-data's flood-context plan Phase 4 (`fl_parcel_ground_lidar`, `fl_building_ground_lidar`:
  1 m lidar ground per parcel and in a ring around each footprint, lidar quality level per row) is
  approved and unblocked; it is the "survey method per parcel" error band.

## 4. Insurance and cost facts

- **Risk Rating 2.0** (2021–22): the flood zone is no longer a rating factor; FEMA estimates
  first-floor height itself; an EC is optional and lowers the price only if the floor is higher than
  FEMA assumed. The zone still decides the **lender's mandatory-purchase requirement**, which turns
  on the **building** (any part of it in the SFHA), not the parcel.
- EC from Bonita Springs: free online search (permits from 2008-06-01; Lee County permits from
  2002-08-16 archived); a 1999 house's EC would sit with Lee County. New EC from a surveyor: about
  $400–800 (Florida, advertised).
- OpenFEMA **NFIP Redacted Policies v3** (74.7 M records; `censusGeoid` = block group; lat/lon
  rounded to 0.1°). Bonita Springs (community 120680), single-family, Zone AE, ZIP 34134, built
  1995–2003, 956 policies effective 2025–26: median **paid $2,926 / yr**, median **full-risk
  $7,694 / yr** (the glide path gap a buyer may inherit or lose). `elevationDifference` on 615 of
  them: median 0 ft (10th pct −1, 90th +2).

## 5. Neighbour-certificate estimate: backtest on Florida ECs

Data: FDEM ECs, cleaned (finished construction, residential, NAVD88, zones AE/AH/A, diagrams 1A/1B/5–8,
plausible values, one per property) → **59,590**; joined to `fl_parcels` for year built → **49,817**
single-family. Leave-one-out; spatial 5-fold (0.1° blocks) for trained models; results reweighted to
the age mix of the 2.73 M single-family homes in the same neighbourhoods. Target: floor − BFE.

| Method | MAE | within 1 ft | above/below right |
|---|---|---|---|
| Floor = BFE (code minimum) | 2.14 ft | 34% | 64% |
| Median of 5 neighbours within 300 m (floor−BFE) | 1.00 ft | 69% | 80% |
| LightGBM, no ground | **0.86 ft** | 72% | 84% |
| + lidar-grade ground (σ 0.33 ft, simulated) | **0.56 ft** | 87% | 89% |
| + street-view foundation type (85% right, simulated) | 0.53 ft | 89% | 90% |
| + street-view floor-height reading (σ 0.72 ft, simulated) | **0.37 ft** | 96% | 93% |
| same, pessimistic reading σ 1.5 ft | 0.43 ft | 92% | 91% |
| reading σ 0.72 ft but only 10 m DEM ground (σ 2.7 ft) | 0.72 ft | 76% | 86% |

Findings:

- Older houses are only mildly harder (pre-1975 MAE 1.05 ft vs 0.70 ft for 2012+, neighbour median).
- Algorithm choice barely matters (HGB / LightGBM / random forest / residual kriging all within
  0.04 ft). **New information is what moves accuracy: lidar ground, then a direct floor-height
  reading.** Image floor height needs lidar ground to become an elevation.
- With lidar-grade ground the model can triage: ~42% of houses "almost certainly above BFE" (99%
  right), ~27% "almost certainly below" (96%), the rest "close — get a survey". Its nominal 80%
  interval covered 77% (needs conformal calibration).
- Caveats: ECs are self-selected; foundation type and street-view readings were simulated from EC
  values with Gaussian noise; real imagery errors are correlated (occlusion, angle, setback).

## 6. Competitors and the market

- Floor-height vendors sell to insurers: True Flood Risk, FloodVision (street imagery + lidar),
  RiskFootprint (Google Street View, 300 M+ properties). First Street is free for consumers
  ($100/property commercial). Research: ELEV-VISION, 0.19 m MAE on 483 houses in Meyerland, Harris
  County.
- A True Flood Risk report (16 Golf View Dr, Englewood FL) was compared with our data. They give a
  building floor height/elevation, LAG/HAG, basement and roof type, a street-flooding scenario and a
  cost-benefit table. They **missed** that the parcel is 0.5% Zone AE (BFE 12.1 ft NAVD88), 40.6%
  shaded X, and touches the SFHA; their numbers are internally inconsistent (FFH 0.48 vs "0.59 ft
  above ground"), carry no sources or error bands, and the dollar figures are unexplained. FEMA data
  for that ZIP (34223) shows 2,100 claims in 2024 alone.
- Likely buyers, most to least: private-flood insurers/MGAs; local governments (substantial-damage
  triage, CRS); surveyors/agents/elevation contractors as lead buyers; home buyers via agents as part
  of a pre-offer report. A stand-alone consumer estimate is the weakest sale.

## 7. Where house-level floor data is public (verified 2026-10-02)

- **EC numbers in bulk**: Florida statewide (FDEM, ~206 k) plus ~60 k in local layers (Pinellas,
  Monroe, Orange, Sarasota city, Key West FL; Hampton Roads and Roanoke VA; Bossier, Kenner,
  Lafayette LA; Lincoln NE; Bryan Co. GA; Dorchester MD; a Monmouth NJ re-publication).
- **Measured first-floor inventories (not ECs)**: North Carolina statewide (5.19 M buildings; ~181 k
  field- or EC-measured, rest lidar-modelled), **Harris County TX (1,185,614 Cyclomedia mobile-lidar
  door elevations)**, NYC (861,876 buildings, z_grade / z_floor). Counts re-verified by query.
- National fallbacks: NFIP Redacted Policies (block-group level), USACE NSI (`found_ht` is a default
  by foundation type, not a measurement).
- ~131 Forerunner community portals hold ECs as documents with no bulk feed. **Decision: no data
  deals for now; pilot first.**
- `research/ec_sources/forerunner_portals.txt` lists the portals found.

## 8. Ways to measure floor height (summary)

Surveyor EC (~0.1 ft, $400–800) · mobile lidar (Harris County did 1.19 M) · laser inclinometer field
crews (NC, ~149 k) · owner's phone measurement (lidar / AR) · oblique aerial imagery (licensed) ·
street panorama + geometry (ELEV-VISION 0.19 m MAE) · vision-language model step/foundation reading
· aerial lidar + default offset (NC's 5 M). Image methods measure height above ground or street;
lidar ground turns that into an elevation.

## 9. Decisions carried into the pilot

1. Pilot in **Harris County**, because its measured door elevations are a free, dense answer key and
   ELEV-VISION was tested there.
2. Build **1 m lidar ground only for the pilot area**.
3. Imagery: **Mapillary first**; **Bee Maps** (paid, $0.005/image) where Mapillary has nothing.
   **No Google Street View** (owner, 2026-10-03; its terms forbid testing ML models on it).
4. Benchmark **many** floor-height methods side by side (see `docs/02-floor-height-methods.md`).
5. Plan only here; a separate session implements.
6. **The product is B2B** (owner, 2026-10-03): a data licence (self-hosted), an API and a flood
   portal over one per-building table. Florida first, core tier (no imagery) first. See
   `docs/03-product-b2b.md`.
