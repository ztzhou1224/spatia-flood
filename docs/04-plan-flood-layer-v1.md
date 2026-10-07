# Plan: flood layer v1 (Florida statewide + Harris accuracy proof)

Status: **approved by the owner 2026-10-07 (answers to §8 below); phase 0 started.** Decisions below are the owner's answers of
2026-10-07 to the 19 design questions (chat), unless marked *open*. Research evidence: `research/SUMMARY_2026-10-06.md`,
`research/harris_mini/LPC.md`, `research/harris_mini/BANDS.md`. Every number here names its source; costs from
vendor pages are as read on 2026-10-06/07.

## 1. What v1 is

- **The flood layer**: one row per building, every building in Florida, with the floor-vs-BFE verdict and every
  input that led to it. Harris County is built by the same pipeline as the **accuracy proof** (scored against the
  HCFCD key; not sold).
- **The pipeline** that builds it from public sources, and **rebuilds it** when new data arrives (a certificate
  batch, a county extract, PDFs).
- **An internal map viewer** for the owner and for demos (not customers).
- Out of v1 (owner, 2026-10-07): API server, MCP server, images, NFIP features, national coverage. The schema is
  designed so the API / MCP are thin readers later. What the sold product ships (geometry or not) is decided later;
  v1 makes no geometry promise.

## 2. Decisions (owner, 2026-10-07)

| # | Decision |
|---|---|
| 1 | Row = building, keyed by our `building_id` (the Overture GERS id); `parcel_key` = state + county + native parcel id, stable across a later parcel-source change |
| 2-3 | Parcels from spatia-data's free state layers (`fl_parcels`, `tx_parcels`). Addresses: Overture / national address points joined spatially first; Geocodio only for buildings left without one (terms to be read). ReportAll / Regrid not bought for v1 |
| 4 | Area: all of Florida; Harris as the accuracy proof |
| 5-6 | Risk area = SFHA + 0.2% zone + 500 m, from NFHL, per county. Every building in the state is in the layer; floor work only inside the risk area |
| 7 | Zones at both footprint and parcel level, with shares, plus `touches_sfha` (FEMA's building rule) |
| 8 | BFE: static BFE polygons first, else interpolated from BFE lines; source and datum per row; NGVD29 converted and flagged |
| 9 | Three evidence classes: **record** (official record: certificate, county inventory, appraiser), **observed** (our sensor measurement: lidar ground, roof / eave, flight change), **modeled** (model estimate, always with a band) |
| 10 | Confidence: modeled = 90% conformal band + BFE call; record / observed = the source's stated precision. No 0-100 score |
| 11 | Vintage per field. **Every null carries a reason** (below), including "stale": a record older than a detected lift / rebuild |
| 12-13 | Rebuilds are manual, behind a release gate (re-score on held-out labels; publish only if accuracy and band coverage do not get worse); 20% of each new label batch held out |
| 14 | PDF certificates: fillable-form read + OCR / own vision model for scans + a human check queue; volumes from the phase-0 survey |
| 15 | v1 uses only inputs with clear terms; the rest are tagged and droppable (`input_licences`, `provider`) |
| 16 | Viewer: internal, owner + demos |
| 17 | Pipeline code in spatia-flood; lidar on a rented box; layer and tiles on R2. **Lidar features are built once and stored** (cheaper than on demand, §6) |
| 18 | Per-area accuracy shown in the viewer |
| 19 | API, MCP, images, NFIP, national: deferred |

## 3. The record

### 3.1 Value conventions (every field)

Each value `x` travels with: `x_class` (`record` / `observed` / `modeled`), `x_source` (named source, edition),
`x_vintage` (date of the measurement or record, not of our build), and either `x_band_lo` / `x_band_hi` (modeled,
90%) or `x_precision_ft` (record / observed, when the source states one). When `x` is null, `x_null` says why:

| `x_null` | Meaning | Example |
|---|---|---|
| `not_applicable` | the question does not apply | BFE outside the SFHA; floor-vs-BFE outside the risk area |
| `no_coverage` | no source covers this building | no lidar flight; no parcel layer |
| `not_determinable` | a source covers it but cannot answer | roof not seen (< 5 returns); footprint unmatched |
| `stale` | a value exists but predates a detected change | certificate from 2015, lidar shows a lift in 2020 |
| `withheld` | value exists, licence does not allow it in this build | Bee Maps-derived, NFIP-derived |
| `not_evaluated` | the pipeline did not run this step here | change detection where only one flight exists |

These map onto spatia-report's gap kinds (`NO_COVERAGE` / `NOT_DETERMINABLE` / `NOT_EVALUATED`), so the report
engine can read the layer without a new grammar.

### 3.2 Building table (draft columns)

| Group | Columns |
|---|---|
| Identity | `building_id`, `parcel_key`, `parcel_id_native`, `county_fips`, `address` (+ source), `lon`, `lat` (centroid, CRS84), `footprint_area_m2` (EPSG:3086), `footprint_source` + date |
| Flood context | `zones` (list of {zone, share of footprint}), `touches_sfha`, `bfe_ft` (NAVD88) + datum note + method (static / interpolated), `firm_effective_date`, `in_risk_area` |
| Ground | `lag_ft` (observed: 1 m lidar DEM, lowest in a 0.5-2.5 m ring), lidar project, QL, flight dates |
| Building | `year_built` (record, DOR NAL), `living_area_sqft` (record). No floor count or foundation column (owner, 2026-10-07) |
| Roof / eave | `roof_ft`, `eave_ft` (observed, point cloud) |
| Floor | `ffh_ft` (record if a certificate / inventory matches, else modeled + band), `ffe_ft`, `floor_minus_bfe_ft` |
| Verdict | `bfe_call` in {`above`, `below`, `too_close`, `not_applicable`}, `bfe_call_basis` (record / modeled band), `raised_flag` (label-free) |
| Change | `lift_or_rebuild` (observed, two flights; `not_evaluated` where one flight) |
| Provenance | `model_version`, `release`, `input_licences`, `provider` |

**Parcel table**: `parcel_key`, zones with shares of parcel area, `any_building_below_bfe`, count of buildings
by call, link to the primary building (largest residential footprint; buildings spanning parcels linked to all
and flagged).

### 3.3 The coverage map (the map to act on)

Per county and per H3 cell (resolution chosen in phase 0): buildings in the risk area, labels held (record class)
and labels on flagged houses, whether bands are locally calibrated, lidar flights and dates, sources missing, and
the share of SFHA buildings with a decided BFE call. It answers "where should I request data next". Rule carried
from research (`BANDS.md`): no locally calibrated band for flagged houses until the area has labels on flagged
houses; bands are never borrowed across states.

## 4. Pipeline

```
sources registry ──► ingest ──► match to buildings ──► features ──► train + calibrate ──► gate ──► assemble ──► publish
 (yaml, licence)      (raw,      (footprint, parcel,    (ground,     (LightGBM method E,   (held-out  (record,     (GeoParquet,
                       dated)     address, label)        lidar,       normalised conformal   labels)   coverage    PMTiles,
                                                         records)     bands per county)               map)        release notes)
```

- **Sources registry** (`pipeline/sources/*.yaml`): one entry per source with URL / path, edition, licence,
  provider, evidence class, and which counties it covers. A new extract from a city is a new entry plus files in
  `data/inbox/<source>/`.
- **Ingest** keeps raw files dated and untouched under `data/raw/`; parsed tables under `data/stage/`.
- **Match**: certificates and inventories to footprints (point in footprint, else nearest within 10 m, one label
  per footprint, latest wins), as `fl_build.py` does today; unmatched rows logged with reasons.
- **Features**: ground from 1 m DEM, roof / eave from the point cloud (`lpc_features.py`, unit-safe for US-ft
  tiles), records from DOR NAL via `fl_parcels`, NSI. Built once per lidar project on the rented box and stored
  per building in R2 (§6); recomputed only when a new flight lands.
- **Train + calibrate**: method E (benchmark.py features) trained on Florida's record-class labels with spatial
  block folds; difficulty model and normalised conformal bands calibrated per county where it has labels
  (`eval_bands2.py`), per-group bands for flagged houses (`BANDS.md` rule).
- **Gate**: 20% of every new label batch is held out; a release publishes only if held-out MAE, BFE-call
  precision and band coverage are no worse than the previous release (thresholds fixed in phase 1).
- **Assemble**: one row per building with the conventions of §3.1; record beats observed beats modeled for the
  same field, and a record older than a detected change is marked `stale`.
- **Publish**: GeoParquet + PMTiles + release notes (what changed per building) to R2, as a spatia-data **pilot**
  layer through its contract (owner, 2026-10-07): withheld from spatia-report runs by `maturity: pilot`; the
  spatia-data side goes through that repo's plan / GIS review / build / live-review harness.

**PDF certificates.** Florida's main certificate volume is already structured: FDEM's public layer has 210,888
records statewide (`data/fl/ec_all.json`). PDFs come from county portals (per-address indexes found 2026-10-04 in
Miami-Dade and Pinellas, `research/coverage/MEASURED_SOURCES.md`) and from records the owner requests. Reader:
(1) AcroForm fields when the PDF is a filled form; (2) OCR plus a self-hosted vision model for scans (no Gemini,
owner rule); (3) a human check queue for any read below a confidence threshold. Nothing read from a PDF is published
without a clean form read or a human check. Phase 0 counts the PDFs actually reachable before the reader is built.

## 5. Phases and acceptance

| Phase | Work | Accepted when |
|---|---|---|
| 0 Measure | Risk-area mask for Florida from NFHL; buildings inside it; lidar projects, flights and tile volume per county; FDEM certificates matched per county; PDF survey (which counties, how many, form vs scan); licence reads list | numbers in this doc replaced by measured ones, each with its command |
| 1 One county end to end | Pinellas: sources, match, features, train, bands, gate, assemble, publish, viewer | every column follows §3.1; held-out scores reported; viewer shows a building's full record and the coverage map |
| 2 Florida | all counties' risk areas on the rented box; statewide model; per-county calibration; coverage map | statewide release with per-county accuracy cards |
| 3 Refresh loop | inbox → rebuild affected counties → gate → release notes; PDF reader with check queue | a new certificate batch changes the layer only where it should, and the release notes say so |
| 4 Harris proof | same pipeline on Harris; scored against HCFCD (scorer only) | accuracy card for Harris matching the research benchmark within noise |

## 6. Costs

| Item | Basis | Estimate |
|---|---|---|
| Rented box | ccx33 (8 vCPU / 32 GB / 240 GB NVMe) $0.266 / hour, billed hourly (spatia-data `hetzner-build-publish` skill) | hours per county measured in phase 1; deleted after each run |
| Lidar download | USGS 3DEP, free | tile volume measured in phase 0 (our boxes: 0.08-0.15 GB / km²) |
| Stored lidar features | ~120 bytes / building (`A/lpc_features.parquet`: 830,942 bytes, 6,782 houses); Florida ~8.4 M structures (NSI) | ~1 GB; R2 $0.015 / GB-month, 10 GB free, no egress fee: **~$0** |
| On demand instead | each lookup re-reads a ~100-180 MB tile (our boxes) | slower and costlier per lookup, and the full table needs every building anyway: **rejected** |
| Addresses | Overture / national address points: free. Geocodio fallback $1 / 1,000 after 2,500 / day free; unlimited plan from $1,350 / month | only for buildings without an address point |
| Parcels | spatia-data free state layers | $0 in v1. ReportAll (quote 2026-10-06) "download and store": $25,000 / year at 1 M records; Regrid self-serve list $0.10-0.15 / record; deferred |

## 7. Licence reads before anything is sold (not blocking the internal v1)

Overture buildings (ODbL share-alike), FDEM certificates (terms unread), Florida DOR NAL (public record; DOR
terms), Geocodio (storage and redistribution), HCFCD key (proof only), NFIP (excluded), Bee Maps (excluded).

## 8. Owner answers (2026-10-07)

1. Publish as a **spatia-data pilot layer**.
2. Viewer: a **hosted page at flood.runspatia.com** (internal + demos).
3. Change detection: `not_evaluated` where only one lidar flight exists.
4. The HCFCD inventory is **record** class.
5. **No floor count or foundation columns** in the layer (2026-10-07). The floor estimate does not need them
   (`research/harris_mini/eval_no_records.py`: 0 to 0.03 ft MAE within area without NSI or any such record), so no
   RentCast calls and no county appraiser downloads for them. Geocodio is approved for buildings without a free
   address (Pinellas: 727, inside the free daily tier).
