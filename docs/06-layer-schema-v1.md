# Flood layer v1: column reference (building and parcel tables)

Built by `pipeline/assemble/assemble.py <FIPS> <RUN> --release <name>` (plan `docs/04-plan-flood-layer-v1.md` §3).
One row per Overture building whose footprint centroid lies in the county polygon of spatia-data `us_counties`
(TIGER 2025; the risk polygon itself was cut with TIGER 2020 in phase 0). Floor work only inside the risk area
(SFHA + 0.2% zone + 500 m, `pipeline/phase0/risk_area.py`).

## Value conventions (plan §3.1)

Each value `x` travels with `x_class` (`record` / `observed` / `modeled`), `x_source` (named source and edition),
`x_vintage` (date or date interval of the measurement or record, never of our build), a 90% band `x_band_lo` /
`x_band_hi` (modeled) or `x_precision_ft` (when the source states one), and `x_null` when `x` is null:

| `x_null` | used here for |
|---|---|
| `not_applicable` | BFE outside the SFHA; `bfe_call` outside the SFHA (value `not_applicable`, not null) |
| `no_coverage` | no flood polygon; SFHA zone A only (FEMA gives no BFE); no BFE line within 1 km; no parcel; no lidar work unit |
| `not_determinable` | lidar covers the building but too few returns; BFE lines on one side of the building only; parcel without year built / living area; a certificate without its own lowest adjacent grade (no record floor height) |
| `not_evaluated` | outside the risk area (no floor work); footprint > 2,000 m² (point cloud not run); non-residential parcel (model not trained or calibrated there; owner, 2026-10-07); `lift_or_rebuild` (one flight); address before `geocodio.py` |
| `stale` | not produced in v1: needs a second flight to detect a lift / rebuild |
| `withheld` | not produced in v1: no licence-restricted input is used |

All elevations are feet NAVD88; lidar values are US survey feet with the geoid named in `ground_geoid` (GEOID12B
for Pinellas 2018). Heights (`roof_ft`, `eave_ft`, modeled `ffh_ft`) are feet above `ground_ft`. `ground_ft` is lidar
ground (r1: masked ring median; r0: ring minimum), NOT the Elevation Certificate's Lowest Adjacent Grade (renamed from
`lag_ft` 2026-10-07 for that reason). The file's parquet
key-value metadata `spatia_flood` holds the producer, release, model version, held-out gate, the two-population
accuracy card (from r1 on; see "Accuracy" below) and every input layer's
version + full `file_hash` (Overture buildings / addresses, fl_parcels, us_counties, FEMA zones and BFE lines).

## Building table `buildings_<FIPS>.parquet` (GeoParquet, footprint polygon, OGC:CRS84)

| Group | Column | Meaning |
|---|---|---|
| Identity | `building_id` | Overture GERS id |
| | `parcel_key`, `parcel_id_native`, `county_fips` | parcel containing the footprint centroid (`FL-<FIPS>-<DOR parcel id>`) |
| | `parcels_at_centroid`, `spans_parcels` | stacked parcels at the centroid (condos); footprint with >= 10% of its area in more than one parcel geometry |
| | `lon`, `lat` | footprint centroid, CRS84 |
| | `footprint_area_m2` | EPSG:3086 |
| | `footprint_source`, `footprint_release` | Overture release of the footprint (an edition, not a measurement date; from the live spatia-data manifest) and the county-membership rule |
| | `address`, `address_source`, `address_points_in_footprint`, `address_null` | Overture address point in the footprint (nearest the centroid), else parcel situs, else Geocodio reverse |
| Flood context | `zones` | list of {zone, subtype, sfha, share of footprint area} (NFHL S_FLD_HAZ_AR, EPSG:3086) |
| | `zone_main`, `zone_main_subtype` | FEMA zone and subtype of the first (largest-share) element of `zones`; bare `X` mixes minimal-hazard and 0.2% areas, the subtype separates them |
| | `sfha_share`, `touches_sfha` | largest-share zone; SFHA share; any SFHA overlap with area > 0 (FEMA's building rule) |
| | `firm_effective_date` | FIRM panel effective date of the largest-share polygon |
| | `bfe_ft` (+ `_class`, `_method`, `_source`, `_vintage`, `_band_lo`, `_band_hi`, `_precision_ft`, `_datum`, `_null`) | `static` (record): highest static BFE of the SFHA polygons the footprint overlaps; precision = spatia-data's NGVD29 -> NAVD88 conversion sigma (0 when published in NAVD88). `interpolated` (modeled), where no static BFE exists: linear in distance between the nearest FEMA BFE line / cross-section and the nearest one on the other side of the building, among those crossing its SFHA polygons within 1 km (spatia-data `fema_bfe_context`); band = the two elevations widened by 0.5 ft (FIRM BFEs are whole feet) |
| | `in_risk_area` | centroid in the risk polygon (the lidar run's building set) |
| Ground | `ground_ft` (+ `_class`, `_source`, `_vintage`, `_precision_ft`, `_geoid`, `_null`) | r1: **median** of the 1 m DEM cells in a 0.5-2.5 m ring outside the footprint, with cells below −1.5 ft NAVD88 and the tile's hydro-flattened water surface (the tile's most frequent value, when below 0) masked first (owner, 2026-10-08, `docs/09` Q3 / C1-C2); `not_determinable` when fewer than 5 ring cells survive the mask. r0: the unmasked ring **minimum**, which on waterfront and sloped lots is the water, a seawall toe or the low side (review G1). Never the certificate LAG; precision = the work unit's QL RMSEz from the 3DEP Lidar Base Specification (non-vegetated), not a per-building error |
| | `ground_ring_min_ft`, `ground_ring_range_ft`, `ground_ring_masked_cells`, `ground_suspect` | r1: the masked ring's minimum and max − min, how many ring cells the mask removed, and `ground_suspect` = range > 3 ft, or minimum below 0 ft NAVD88, or any cell masked (a sloped, terraced or waterfront lot: the ground, and every height above it, is less certain there) |
| | `lidar_workunit`, `lidar_ql` | USGS WESM work unit holding the centroid |
| Building | `year_built`, `living_area_sqft` (+ `_class`, `_source`, `_vintage`, `_null`) | DOR NAL via spatia-data `fl_parcels`; `dor_use_code` alongside. No floor count or foundation column (owner, 2026-10-07) |
| Roof / eave | `roof_ft`, `eave_ft` (+ `_class`, `_source`, `_vintage`, `_null`) | point cloud: 99th percentile of building returns (`ridge`), main-roof eave (`eave_main`); ft above `ground_ft` |
| Floor | `ffh_ft` (+ `_class`, `_source`, `_vintage`, `_band_lo`, `_band_hi`, `_null`) | first living floor above grade. A matched FDEM certificate is used only if its floor minus `ground_ft` lies within -1..30 ft; otherwise it is not used (the building falls back to the model, or null `not_determinable`) and `record_note` quotes it. Record: certificate floor minus the certificate's own lowest adjacent grade, also within -1..30 ft (else null `not_determinable` with `record_note`; the certificate FFE stays the record). Modeled: method E with the normalised conformal 90% band (`train.py`) |
| | `ffe_ft` (+ `_class`, `_source`, `_vintage`, `_band_lo`, `_band_hi`, `_datum`, `_null`) | record: certificate first living floor (diagram 1A / 1B / 5: top of bottom floor; 2-4, 6-9: top of next higher floor); modeled: `ground_ft + ffh_ft` |
| | `record_note` | why a matched certificate, or its floor height, is not used |
| | `record_stage` | from r1: stage of the matched FDEM certificate (`finished_construction`, `building_under_construction`, `construction_drawings`, `not_stated`), null without one. Only `finished_construction` is ever a record (owner, 2026-10-08, `docs/09` Q5); the others are designs or surveys before completion: the row falls back to the model (or null `not_determinable`) and `record_note` quotes the certificate. The latest certificate per building wins: ordered by (issue date, OBJECTID), undated first (`labels.py`) |
| | `record_vintage_note` | set when a certificate's issue date was missing or invalid in FDEM and was estimated by `clean_dates.py` (LLM; the vintage is then a date or a `start/end` window, an estimate, not a record) |
| | `ffe_record_lidar_conflict` | the certificate fails train.py's label screen against our lidar (`roof_p95 - dh < 6` or `dh < -1`) or, from r1, its own lowest adjacent grade is more than 3 ft from `ground_ft`: possibly matched to the wrong footprint. The certificate stays the record value (owner, 2026-10-07) but, from r1, produces **no call** (`bfe_call` null `not_determinable`; owner, 2026-10-08, `docs/09` Q2) |
| | `floor_minus_bfe_ft`, `floor_minus_bfe_band_lo`, `floor_minus_bfe_band_hi` | `ffe_ft - bfe_ft`; band = floor band minus BFE band (set when either is modeled) |
| Verdict | `bfe_call`, `bfe_call_basis`, `bfe_call_null` | `above` / `below` / `too_close` / `not_applicable`. Record: `above` when `ffe >= bfe` (at the BFE counts as above), else `below`; `too_close` when closer than 1.645 BFE sigma (never where the BFE is published in NAVD88: sigma 0). Modeled: the 90% FFE band clears the BFE (`above` / `below`) or straddles it (`too_close`). With an interpolated BFE its band is used too: `above` only when the floor (or floor band) clears the BFE band's top, `below` only under its bottom; `bfe_call_basis` then ends in `+interpolated_bfe`. Basis `record_lidar_conflict` (r0 only; retired in r1, where such a certificate gets no call): a record call on a certificate that fails the lidar label screen. **`bfe_call` compares the first living floor**, not the NFIP lowest floor: on an elevated house with an enclosure the lowest floor is usually lower (review M1; r1 adds the lowest floor) |
| | `raised_flag`, `raised_flag_source`, `raised_flag_null` | floor more than 3 ft above grade. From r1: on a record row with a record `ffh_ft`, from that height (`raised_flag_source` = `record ffh_ft > 3 ft`; review V1); else the model point estimate (`model point estimate > 3 ft`), for every model-eligible building. r0 used the model on every row, so 708 record rows were flagged with a record height ≤ 3 ft |
| Change | `lift_or_rebuild`, `lift_or_rebuild_null` | `not_evaluated` (one flight) |
| Provenance | `model_version` | `E-lgbm-<FIPS>-<sha256[:12] of model + difficulty model + bands>` |
| | `release`, `input_licences`, `provider` | release name; licence tags of the inputs used by this row; `provider` = `public` when every input is open, else the restricted providers used, joined by `+`: `fdem_forerunner` (FDEM certificates via Forerunner: "solely for your internal, non commercial purposes"), `geocodio` (paid; stored per its terms). r0 wrote `public` on every row (review S3) |

Licence tags (`input_licences`): `overture_buildings:ODbL-1.0`, `fema_nfhl:public`, `usgs_3dep:public_domain`,
`fl_dor_nal:public_record`, `overture_addresses:FL_public_domain`, `geocodio:stored_per_terms`, `openstreetmap:ODbL-1.0`
(Geocodio results whose source is OpenStreetMap), and `fdem_certificates:forerunner_internal_noncommercial` (r0:
`fdem_certificates:terms_unread`; the terms were read, review S3; the commercial position is the owner's legal read,
`docs/09` §6). `address_source` for a Geocodio row quotes Geocodio's own `source` field as returned. The ODbL position
of the GERS-keyed table is also open (`docs/09` §6).

## Parcel table `parcels_<FIPS>.parquet` (no geometry)

`parcel_key`, `parcel_id_native`, `dor_uc`, `geom_group` (parcels sharing one polygon, e.g. condo units), `zones`
(shares of parcel area), `buildings` (footprints with >= 10% of their area in the parcel), `below` / `above` /
`too_close` (their `bfe_call` counts), `any_building_below_bfe`, `primary_building_id` (largest footprint),
`release`. One row per (`parcel_key`, `geom_group`) from r1 (`check.py` asserts it; r0 carries 254 exact duplicate
rows). **Counts are per parcel, and a condo building is counted once in every unit parcel it sits in**: summing
`buildings` over the table counts a building once per unit (r0: Σ `buildings` 7,137,267 over 432,360 rows), so count
buildings from the building table, never by summing this one.

## Accuracy of modeled floors (two populations; review `docs/07` DA1)

The floor model is scored on two populations, and neither number stands alone. Source:
`python pipeline/train/accuracy.py 12103 pinellas_2018 --model data/flood_v1/train_r0 --release pinellas-r0 --county-labels data/flood_v1/labels_pinellas/r0/labels_pinellas_12103.parquet` (the county labels as r0 matched them, before B1 / B4)
(`pipeline/train/out/accuracy_12103_pinellas-r0.json`). Target = certificate first living floor − lidar ground, the
`train.py` screen applied; BFE side and decided calls are measured against the certificate's own zone and BFE.

| `pinellas-r0` | FDEM held-out (gate set) | County certificates (independent) |
|---|---|---|
| population | FDEM certificates in the model's 102 held-out 1 km blocks | Pinellas County certificate layer, native NAVD88, buildings with no FDEM certificate of any stage, all blocks |
| houses scored | 1,315 | 1,348 |
| MAE / median error (ft) | 1.039 / +0.04 | 2.215 / −0.16 |
| within 1 ft | 0.742 | 0.484 |
| BFE side correct | 0.897 | 0.808 |
| 90 % band coverage (95 % CI) | 0.918 (0.902-0.932) | 0.880 (0.861-0.896) |
| decided calls correct | 0.983 | 0.933 |
| slab 1A / 1B: n, MAE, coverage | 1,079, 0.80, 0.930 | 609, 1.12, 0.897 |
| elevated 5-9: n, MAE, coverage | 226, 2.14, 0.854 | 726, 3.12, 0.872 |
| elevated 5-9 not flagged raised: n, coverage | 119, 0.790 | 100, **0.560** (0.462-0.653) |

**The 90 % band is not guaranteed for elevated houses the model does not flag as raised** (`raised_flag` false): on
county certificates fewer than six in ten of them fall inside it, and the misses are mostly floors higher than the
model says (median error −1.5 ft), i.e. toward a false `below`. On the published table, 28 of the 234 `below` and 5 of
the 222 `above` calls on county-only modeled rows are contradicted by the certificate floor against the table's BFE.
The gap is in elevated houses, not label noise: same-day FDEM / county pairs agree to 0.03 ft MAE (review `s5_county.py`).
r1 adds the county labels and per-regime bands (`docs/09` B4, D3).

## Limits of the call (screening, not a determination)

- `ffe_ft` is the first LIVING floor (certificate diagrams 2-4 and 6-9: the next higher floor). NFIP's lowest floor can
  be lower (a basement in diagrams 2A / 2B), so the call can be "above" where NFIP would rate the basement.
- In V zones NFIP compares the bottom of the lowest horizontal structural member, not the top of the floor; the call
  here compares the floor.
- Record calls use no tolerance on the floor side (the certificate value as published).
- `touches_sfha` is any overlap with area > 0, so slivers count (FEMA's building rule); `sfha_share` shows how much.
  Pinellas: 1,240 of 92,243 touching buildings overlap less than 1% (`assemble_12103.json` run 2026-10-07).
- The footprint centroid drives the parcel, lidar work-unit and address joins; 1,193 Overture centroids lie outside
  their own footprint (spatia-data planner measurement), so a DOR attribute can come from a neighbouring parcel.
