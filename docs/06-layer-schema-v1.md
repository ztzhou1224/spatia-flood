# Flood layer v1: column reference (building and parcel tables)

Built by `pipeline/assemble/assemble.py <FIPS> <RUN> --release <name>` (plan `docs/04-plan-flood-layer-v1.md` §3).
One row per Overture building whose centroid lies in the county (TIGER 2020). Floor work only inside the risk area
(SFHA + 0.2% zone + 500 m, `pipeline/phase0/risk_area.py`).

## Value conventions (plan §3.1)

Each value `x` travels with `x_class` (`record` / `observed` / `modeled`), `x_source` (named source and edition),
`x_vintage` (date or date interval of the measurement or record, never of our build), a 90% band `x_band_lo` /
`x_band_hi` (modeled) or `x_precision_ft` (when the source states one), and `x_null` when `x` is null:

| `x_null` | used here for |
|---|---|
| `not_applicable` | BFE outside the SFHA; `bfe_call` outside the SFHA (value `not_applicable`, not null) |
| `no_coverage` | no flood polygon; SFHA zone A only (FEMA gives no BFE); no parcel; no lidar work unit |
| `not_determinable` | lidar covers the building but too few returns; parcel without year built / living area; a certificate without its own lowest adjacent grade (no record floor height) |
| `not_evaluated` | outside the risk area (no floor work); footprint > 2,000 m² (point cloud not run); non-residential parcel (model not trained or calibrated there); AE / VE / AH / AO without a static BFE (BFE-line interpolation not built yet); `lift_or_rebuild` (one flight); address before `geocodio.py` |
| `stale` | not produced in v1: needs a second flight to detect a lift / rebuild |
| `withheld` | not produced in v1: no licence-restricted input is used |

All elevations are feet NAVD88; lidar values are US survey feet with the geoid named in `lag_geoid` (GEOID12B for
Pinellas 2018). Heights (`roof_ft`, `eave_ft`) are feet above `lag_ft`.

## Building table `buildings_<FIPS>.parquet` (GeoParquet, footprint polygon, OGC:CRS84)

| Group | Column | Meaning |
|---|---|---|
| Identity | `building_id` | Overture GERS id |
| | `parcel_key`, `parcel_id_native`, `county_fips` | parcel containing the footprint centroid (`FL-<FIPS>-<DOR parcel id>`) |
| | `parcels_at_centroid`, `spans_parcels` | stacked parcels at the centroid (condos); footprint with >= 10% of its area in more than one parcel geometry |
| | `lon`, `lat` | footprint centroid, CRS84 |
| | `footprint_area_m2` | EPSG:3086 |
| | `address`, `address_source`, `address_points_in_footprint`, `address_null` | Overture address point in the footprint (nearest the centroid), else parcel situs, else Geocodio reverse |
| Flood context | `zones` | list of {zone, subtype, sfha, share of footprint area} (NFHL S_FLD_HAZ_AR, EPSG:3086) |
| | `zone_main`, `sfha_share`, `touches_sfha` | largest-share zone; SFHA share; any SFHA overlap with area > 0 (FEMA's building rule) |
| | `firm_effective_date` | FIRM panel effective date of the largest-share polygon |
| | `bfe_ft` (+ `_class`, `_method`, `_source`, `_vintage`, `_precision_ft`, `_datum`, `_null`) | highest static BFE of the SFHA polygons the footprint overlaps; precision = spatia-data's NGVD29 -> NAVD88 conversion sigma (0 when published in NAVD88) |
| | `in_risk_area` | centroid in the risk polygon (the lidar run's building set) |
| Ground | `lag_ft` (+ `_class`, `_source`, `_vintage`, `_precision_ft`, `_geoid`, `_null`) | lowest 1 m DEM cell in a 0.5-2.5 m ring outside the footprint; precision = the work unit's QL RMSEz from the 3DEP Lidar Base Specification (non-vegetated), not a per-building error |
| | `lidar_workunit`, `lidar_ql` | USGS WESM work unit holding the centroid |
| Building | `year_built`, `living_area_sqft` (+ `_class`, `_source`, `_vintage`, `_null`) | DOR NAL via spatia-data `fl_parcels`; `dor_use_code` alongside. No floor count or foundation column (owner, 2026-10-07) |
| Roof / eave | `roof_ft`, `eave_ft` (+ `_class`, `_source`, `_vintage`, `_null`) | point cloud: 99th percentile of building returns (`ridge`), main-roof eave (`eave_main`); ft above `lag_ft` |
| Floor | `ffh_ft` (+ `_class`, `_source`, `_vintage`, `_band_lo`, `_band_hi`, `_null`) | first living floor above grade. Record: certificate floor minus the certificate's own lowest adjacent grade. Modeled: method E with the normalised conformal 90% band (`train.py`) |
| | `ffe_ft` (+ `_class`, `_source`, `_vintage`, `_band_lo`, `_band_hi`, `_datum`, `_null`) | record: certificate first living floor (diagram 1A / 1B / 5: top of bottom floor; 2-4, 6-9: top of next higher floor); modeled: `lag_ft + ffh_ft` |
| | `record_vintage_note` | set when a certificate's issue date was missing or invalid in FDEM and was estimated by `clean_dates.py` (LLM; the vintage is then a date or a `start/end` window, an estimate, not a record) |
| | `ffe_record_lidar_conflict` | the certificate fails train.py's label screen against our lidar (`roof_p95 - dh < 6` or `dh < -1`): possibly matched to the wrong footprint |
| | `floor_minus_bfe_ft`, `floor_minus_bfe_band_lo`, `floor_minus_bfe_band_hi` | `ffe_ft - bfe_ft` |
| Verdict | `bfe_call`, `bfe_call_basis`, `bfe_call_null` | `above` / `below` / `too_close` / `not_applicable`. Record: `above` when `ffe >= bfe` (at the BFE counts as above), else `below`; `too_close` when closer than 1.645 BFE sigma (never where the BFE is published in NAVD88: sigma 0). Modeled: the 90% FFE band clears the BFE (`above` / `below`) or straddles it (`too_close`) |
| | `raised_flag`, `raised_flag_null` | label-free: model point estimate > 3 ft above grade; for every model-eligible building, labelled or not |
| Change | `lift_or_rebuild`, `lift_or_rebuild_null` | `not_evaluated` (one flight) |
| Provenance | `model_version` | `E-lgbm-<FIPS>-<sha256[:12] of model + difficulty model + bands>` |
| | `release`, `input_licences`, `provider` | release name; licence tags of the inputs used by this row; `public` (no paid or restricted provider) |

## Parcel table `parcels_<FIPS>.parquet` (no geometry)

`parcel_key`, `parcel_id_native`, `dor_uc`, `geom_group` (parcels sharing one polygon, e.g. condo units), `zones`
(shares of parcel area), `buildings` (footprints with >= 10% of their area in the parcel), `below` / `above` /
`too_close` (their `bfe_call` counts), `any_building_below_bfe`, `primary_building_id` (largest footprint),
`release`.
