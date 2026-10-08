# Data sources, vintages and licences review of pinellas-r0

Work dir: `(session work dir, not committed) ` (scripts `q1.py`..`q4.py`, their `*.out`, fetched pages under `terms/`,
WESM / TNM / EPT listings). Every number below is from a command run in this session; the script or command is named.

## Verdict

The edition is honest about *which* editions it used (the parquet `spatia_flood` metadata pins the six spatia-data
layers by hash and the lidar work unit by date and geoid, and the file's sha256 matches the handoff pin), and the
licence tags on each row are truthful as far as they go. It is **not yet fit to put in front of a buyer** for two
reasons that the table itself does not disclose: (1) **vintage mismatch is silent** — 3,772 modeled rows sit on
buildings the DOR says were built in 2019 or later (2,938 in 2020+), i.e. after the only lidar flight ended on
2019-03-08, yet they carry `ffe_vintage = 2018-12-07/2019-03-08` and 77 of them get a decided `bfe_call`; and 572
"record" rows are certificates issued from construction drawings or during construction, carried as if they were
finished-floor measurements. (2) **The licence position of the sold inputs is unresolved by the owner's own survey**:
Overture footprints are ODbL (share-alike + §4.6 offer obligation on a Publicly Used Derivative Database), and the
FDEM certificate values (7,515 rows) are tagged `terms_unread` while the only terms found (Forerunner's) say
"solely for your internal, non commercial purposes". A floodplain manager can use it with the caveats stated in
`docs/06`; a buyer cannot be sold it until the ODbL / FDEM question is answered and the post-flight buildings are
flagged. Also unreported: FEMA issued a **countywide preliminary FIRM for Pinellas on 2025-05-15** (DFIRM 12103C:
7,287 preliminary flood-hazard polygons, 135 panels, 238 BFE features — after Helene/Milton) and holds **2,212 LOMA
determinations** in the county bbox; the pipeline reads neither, and the table does not say so.

Fix first: (a) add a `stale`/`not_evaluated` rule for `year_built` > flight end (or a `built_after_lidar` flag);
(b) carry FDEM `buildingElevationSource` and refuse `record` class for non-finished certificates; (c) get the legal
read on ODbL + FDEM/Forerunner before any sale, and rename the tag from `terms_unread` to what the survey found.

## Findings

### 1. [major] Buildings built after the lidar flight are modeled from pre-construction lidar and not marked
- What: `pipeline/assemble/assemble.py` (floor block, ~L470-520) models every risk-area residential building with
  `lpc_status == ok`; nothing compares `year_built` (DOR NAL 2025) with the flight window. `lift_or_rebuild_null` is
  `not_evaluated` on all 372,764 rows; the plan's `stale` reason (`docs/06-layer-schema-v1.md`, "not produced in v1")
  is never used.
- Evidence (`work_sources/q1.py` on `buildings_12103.parquet`; second block in the session's local-checks command):
  ```
  year_built non-null 362328  >=2019: 7499  >=2020: 5856  in risk & >=2019: 5277
  year_built>=2019 by ffh_class: modeled 3772, NaN 3317, record 410
  modeled & year_built>=2019: 3772  of which year_built>=2020: 2938
  modeled & year_built>=2020: 2938  bfe_call: not_applicable 2104, too_close 741, above 59, below 18, nan 16
  modeled & year_built>=2020 ffe_vintage: {'2018-12-07/2019-03-08': 2938}
  year_built>=2019 by ffe_class & touches_sfha: modeled/True 1071, record/True 389
  ```
  Lidar window per `wesm_12103.parquet` / metadata: `collect_start 2018-12-07, collect_end 2019-03-08`.
- Why it matters: for these buildings the roof/eave/ground features describe the previous structure or a bare lot
  (the owner's own Harris research says the 2018 answer key is stale for rebuilds: `research/SUMMARY_2026-10-06.md`
  L43, L129-132). 77 decided calls and 741 `too_close` calls in the SFHA are on a floor that did not exist when the
  lidar was flown; a buyer reading `ffe_vintage` would believe the floor was measured in 2018-19. Post-Helene/Milton
  (Sept/Oct 2024) rebuilds cannot be in this count at all (`year_built` max in the table is 2024; `>=2025: 0`).
- Fix: in assemble.py, when `year_built` (or DOR `act_yr_blt`) is later than the lidar `collect_end` year, set
  `ffh_null`/`ffe_null = stale` (or `not_evaluated`) with a `record_note`, keep `roof/eave/ground` but mark their
  vintage as pre-construction; for `record` rows, compare the certificate date with `year_built` too (139 record rows
  have a certificate year earlier than `year_built`: `q1.py`, "vintage year < year_built: 139").

### 2. [major] 572 "record" floors come from certificates that are not finished-construction measurements
- What: `pipeline/train/labels.py` L44 filters FDEM on `verticalDatum == navd_1988` and `buildingUse == residential`
  only; `buildingElevationSource` is never read, and the table has no column for it. `docs/06` describes `ffe_ft`
  record as "certificate first living floor".
- Evidence (`work_sources/q4.py`: 16 live GETs to the FDEM FeatureServer for the 7,515 matched OBJECTIDs, crossed with
  the record rows by the OBJECTID in `ffe_source`):
  ```
  buildingElevationSource (matched 7515): finished_construction 6939, building_under_construction 291,
    construction_drawings 238, (null) 47
  record rows 7461: finished_construction 6889, building_under_construction 289, construction_drawings 236, null 47
    of those not finished_construction: touches_sfha 524; bfe_call above 308, below 210, too_close 2, n/a 48
  ```
- Why it matters: a construction-drawings certificate (FEMA EC C1 "Construction Drawings") is a design elevation, and
  an under-construction one is provisional; FEMA requires a finished-construction EC before the as-built is accepted.
  518 decided SFHA calls rest on them and the row reads as a measured record with no note.
- Fix: fetch `buildingElevationSource` with the labels (it is in the layer: `terms/fdem_layer.json`), store it
  (`ffe_record_stage`), class those rows `record` only when `finished_construction`; otherwise fall back to the model
  with `record_note`. Exclude them from training labels too (`labels.py`) — a scorer should not treat them as truth.

### 3. [major] Licence tags are truthful but the licence position of the sold inputs is unresolved; `provider=public` over-claims
- What: `assemble.py` L70-73 `LIC` and L580-595: every row carries `overture_buildings:ODbL-1.0`; 7,515 rows carry
  `fdem_certificates:terms_unread`; `provider = "public"` on all rows, which spatia-data publishes as "every input of
  the row is public; no paid or restricted provider" (`spatia-data/src/spatia_data/assets/fl_building_first_floor.py`
  L434-435, L903-909). `docs/03-product-b2b.md` §5 lists FDEM and DOR as *unverified*.
- Evidence: table counts (`q1.py`): tags `overture_buildings:ODbL-1.0 372764`, `fdem_certificates:terms_unread 7515`,
  `geocodio:stored_per_terms 727`, `openstreetmap:ODbL-1.0 6`, `provider public 372764`.
  Terms fetched this session (`terms/`, HTTP 200 unless noted):
  - Overture attribution page: "Buildings — License for theme: ODbL © OpenStreetMap contributors"; ODbL 1.0 §4.4a
    "Any Derivative Database that You Publicly Use must be only under the terms of: i. This License…"; §4.6 "you must
    also offer to recipients … a copy in a machine readable form of: a. The entire Derivative Database; or b. A file
    containing all of the alterations". The owner's survey (`docs/phase0-sources-survey.md`, Decisions §4) already
    concludes the sold table "cannot go into a sold building table without accepting ODbL obligations, unless the
    Collective Database route holds" — and the layer keyed on Overture GERS ids with the footprint geometry was
    published anyway (`fl_building_first_floor_footprint`).
  - Forerunner Terms of Use (Last Updated September 4, 2025): "a limited, non-exclusive, revocable right to access and
    use the Services solely for your internal, non commercial purposes. You may not resell, transfer, assign, or
    sublicense…". FDEM ArcGIS item `92fb38b201e0440c83a959970b194973`: `licenseInfo ''`, `accessInformation ''`,
    owner `jtwhite_forerunner`; layer `copyrightText ''`. FDEM portal: disclaimer only ("makes no warranties…").
    `florida.withforerunner.com/terms` returned a 22-character shell (JS app; no text).
  - The tag says `terms_unread`, but the terms WERE read on 2026-10-07 (survey Part B 1a-1d); the honest tag is
    "terms adverse/unsettled", and `provider=public` ("no restricted provider") contradicts an input whose only
    published terms are non-commercial.
  - Geocodio §8.4: "Customer may store, transmit, transform, sell… provided that such uses are permitted by the
    underlying Data Sources". 8 of the 727 Geocodio rows cite source "Loveland" (`assemble_12103.json` addresses;
    `address_source` contains "Loveland"), which does not appear on Geocodio's data-sources page (fetched; it lists
    OSM/ODbL, GeoNames CC-BY, TIGER public domain, OpenAddresses "various licenses", "Local city, county, and state
    datasets"). Those 8 rows carry only `geocodio:stored_per_terms` — the underlying licence is unknown.
  - DOR portal: "publishes assessment rolls in compliance with chapter 119, Florida Statutes"; no redistribution
    clause (matches the survey). USGS copyright page and FEMA website-information page returned HTTP 403 through the
    proxy: not re-verified here (survey quotes stand). Vendor XML for the Pinellas lidar: `accconst` "No restrictions
    apply to these data", `altdatum` "North American Vertical Datum of 1988, Geoid 12B", `altunits` "U.S. Survey Feet".
- Why it matters: `docs/03` §5 says anything sold must be licence-clean; the handoff §7.7 still lists the licence reads
  as a to-do before anything is sold. A buyer's file built from `input_licences` tiers would include ODbL-keyed rows.
- Fix: (a) legal read on ODbL for a GERS-keyed table (survey Decisions §4) and on FDEM-via-Forerunner vs chapter 119;
  (b) rename the tag to `fdem_certificates:terms_unsettled_forerunner_noncommercial` (or similar) and change
  `provider` to a value that does not assert "no restricted provider" for those rows; (c) tag the 8 Loveland rows
  with the underlying source.

### 4. [major] Preliminary FIRM and LOMAs exist for Pinellas and the pipeline does not read either
- What: `assemble.py` reads only effective NFHL (`fema_flood_zones`, `fema_bfe_context`, edition 2026.04). No code in
  `pipeline/` mentions LOMA, LOMR, preliminary or pending (grep: only `research/harris_mini/` and `docs/01` do).
- Evidence (live, read-only GETs to hazards.fema.gov, `where=DFIRM_ID='12103C'&returnCountOnly=true`):
  ```
  PrelimPending/Prelim_NFHL layer 28 (Preliminary Flood Hazard Zones): count 7287
  PrelimPending/Prelim_NFHL layer 3 (Preliminary FIRM Panels):         count 135
  PrelimPending/Prelim_NFHL layer 16 (Preliminary Base Flood Elevations): count 238
  PrelimPending/Pending_NFHL layer 28 / layer 3 (Pending zones / panels):   count 0 / 0
  PrelimPending/Prelim_NFHL layer 0 (Preliminary Data Availability), Pinellas bbox:
      DFIRM_ID 12103C, PRELM_CODE 12103C_20250515, PRELM_ISSUE_DATE 1747306800000 (= 2025-05-15),
      CREATE_DATE 1748343600000 (= 2025-05-27); prelim panels EFF_DATE 1629802800000 (= 2021-08-24, the effective
      FIRM the table uses), VERSION_ID 2.4.3.2
  public/NFHL layer 34 (LOMAs), Pinellas bbox -82.86,27.6,-82.62,28.18: count 2212   (bbox; a few may be neighbours)
  public/NFHL layer 1 (LOMRs), wider bbox -82.95,27.55,-82.4,28.2:        count 51
  ```
  So a **countywide preliminary FIRM for Pinellas was issued 2025-05-15** (after Helene/Milton) and 2,212 LOMA
  determinations (fields `CASENUMBER, STATUS, DETERMINATIONTYPE, OUTCOME, LAT, LON`) sit in the county; `touches_sfha`
  and `bfe_call` ignore both.
- Why it matters: a floodplain manager in Pinellas works against the preliminary map as well as the effective one
  (permitting uses the higher of the two in many communities); a building removed from the SFHA by a LOMA is still
  `touches_sfha = True` here and gets a `below` call. Neither is wrong under "effective NFHL", but the table does not
  say that a preliminary map exists for every row it covers.
- Fix: add a county-level `firm_status` (preliminary available since <date>) to the layer notes now; next release, read
  the Prelim_NFHL zones/BFEs as a second `bfe_*` set and the LOMA layer as a `loma_case` column (both FEMA, public).

### 5. [minor] The inputs that are not spatia-data layers are not pinned in the file's provenance
- What: `assemble.py` L659-665 writes `inputs` = the six spatia-data layers only. The FDEM layer (edited daily:
  `dataLastEditDate 1790845756732` = 2026-10-01 in `terms/fdem_layer.json`), the WESM query, Geocodio (727 lookups)
  and the LLM date cleaning (`gpt-5.5-2026-04-23`) have no edition / fetch date in the parquet metadata.
- Evidence: `prov inputs keys: ['us_counties', 'overture_addresses', 'overture_buildings', 'fema_flood_zones',
  'fema_bfe_context', 'fl_parcels', 'fema_flood_zones_release', 'fema_bfe_context_release']`. The only FDEM trace is
  `pipeline/train/out/labels_12103.json` `fdem_records_statewide: 210888` (no date); `data/fl/ec_all.json` is absent
  locally (not on R2 per handoff §5), so the labels are not reproducible from pinned bytes.
- Fix: record `fdem_layer_edit_date`, `fdem_fetch_date`, record count, `wesm_fetch_date`, `geocodio_date`, LLM model in
  `prov`; keep `ec_all.json` on R2 under `_flood/`.

### 6. [minor] FEMA-lines BFE rows have no `bfe_precision_ft`; static BFEs are all verbatim NAVD88 (good)
- Evidence (`q1.py`): `bfe_datum`: `NAVD88 ft; navd88_verbatim 88274` (83,024 static + 5,250 interpolated); `bfe_method
  × bfe_precision_ft`: `static 0.0 83024`, `interpolated NaN 5250`. So no NGVD29→NAVD88 conversion reached Pinellas
  (consistent with FDEM: `elevationDatum` on matched certs `navd_1988 7441, ngvd_1929 63` for the *BFE* field, B11).
- Note: 63 matched certificates state their BFE in NGVD29 (`q4.py`), but `cert_bfe_ft` is not used in the table, so no
  effect on values.

### 7. [minor] Geoid is stated for lidar only; certificates' geoid is "not stated" and cannot be verified here
- Evidence: `ground_geoid GEOID12B 290540`; `ffe_datum` record rows: "NAVD88 ft (certificate … geoid not stated)" 7461;
  FDEM fields with datum info (`terms/fdem_layer.json`): `verticalDatum`, `elevationDatum`, `baseFloodElevationDatum`,
  `benchmarkUtilized`, `elevationDatumComments`; `q4.py`: `elevationDatumComments` non-empty 8, mentioning "geoid" 0;
  `benchmarkUtilized` non-empty 7,512 (a benchmark name, not a geoid). Pinellas county layer: `VERTICAL_DATUM`
  blank 17,814 of 19,382; `C2_BENCHMARK_VERT_DATUM` NAVD1988 7,430 / NGVD1929 2,465; no geoid field (`q2.py`).
  `pyproj.datadir` has no geoid grids and network is off (`[]`, `is_network_enabled False`), so GEOID12B vs 18
  differences were not computed. Record vs lidar: `record_cert_lag_minus_lidar_ground_median_ft 0.44`
  (`assemble_12103.json`) — a 0.4-0.6 ft systematic offset that is consistent with, but not proven to be, a geoid /
  benchmark difference. Stated vs assumed is correctly labelled in `ffe_datum`; nothing is silently mixed.

### 8. [note] No newer lidar over Pinellas exists in 3DEP; the pipeline could not have found one if it did
- Evidence: `wesm_12103.parquet` has 1 row (query `where project = 'FL_Peninsular_2018_D18'`, `assemble.py` L128-134,
  so a newer work unit would never be returned). The WESM query endpoint returned HTTP 400 "Failed to execute query"
  for every query today, including assemble.py's exact one (`work_sources/wesm_*.json`), so the index was checked via
  TNM: `tnmaccess … datasets=Lidar Point Cloud (LPC)&bbox=-82.95,27.55,-82.4,28.2` → 1,772 products; grouped by project
  (`work_sources/tnm_lpc*.json`): FL_PINELLASCO (2014-09-29 pub; 2007 flight), FL_Peninsular (2021-03-25),
  FL_Peninsular_FDEM (2021-07-07), FL_2018PascoCounty_C22 (2025-12-08), FL_ManateeCounty_B25 (2026-04-29) — the last
  two are neighbouring counties in the bbox. `usgs-lidar-public ?prefix=FL_`: 100 prefixes, Pinellas entries
  `FL_Peninsular_Pinellas_2018/`, `FL_PinellasCo_2007/` only. So no post-2019 and no post-Helene/Milton lidar.
- Fix: query WESM without the project filter and store every work unit over the county (then the "newer flight"
  check becomes part of the gate).

### 9. [note] The Pinellas county EC layer (unused in r0) would add 1,416 labelled buildings, 763 elevated — but ends in 2020
- Evidence (`q2.py`, `q3.py` on `labels_pinellas/raw/2026-10-07/` and the two labels parquets; agrees with
  `pipeline/labels_pinellas/out/build_12103.json`): 19,382 records, 139 fields; any floor value (C2A/C2a_88/C2B/C2b_88)
  18,460; C2F LAG 17,855; `D_DATE` 1960-02-01..2024-12-30 (one 6201 value), years 2017: 1,785, 2018: 1,827, 2019:
  1,517, 2020: 241, 2021: 22, 2022: 31, 2024: 1 — **the county layer stops in mid-2020** (73 records after 2020-06),
  though `LAST_EDITED_DATE` max is 2026-10-04. Matched county labels 5,247 (navd88_native 5,019); buildings not in
  FDEM labels 1,582 (1,416 native); of the 1,416: diagram 5-9 **763**, dh>3 ft 870, either 924. Overlap with FDEM
  3,665 buildings, |ΔFFE| ≤ 0.5 ft on 94.4%. Join is by building_id after the same point-in-footprint / 10 m match
  (`build.py` step 5); FDEM wins unless the county date is strictly later (15 county wins).
  Datum: 9,562 records dropped for no stated datum — checked: only 52 of them have `C2_BENCHMARK_VERT_DATUM =
  NAVD1988` and 0 of those are residential with a valid diagram and C2A, so nothing recoverable (`q3.py`).
  Licence: service `copyrightText ''`, `serviceDescription "Elevation Certs App for Public Works"`; the layer
  description names a county data steward with phone and email (kept in the gitignored `layer.json`; not quoted).
  The layer's `A1_BUILDING_OWNER` / `F_OWNER_OR_AUTH_REPS_NAME` fields exist but were never requested (`fetch.py`
  allowlist, verified `cols fetched` in `q2.out`).

### 10. [note] Certificate vintages straddle the lidar flight and 1,193 post-date Helene
- Evidence (`q1.py`, record rows 7,461): point-dated 7,201, LLM windows 260; by year 2017: 1,141, 2018: 1,103, 2019:
  1,102, 2020: 685, 2021: 793, 2022: 563, 2023: 389, 2024: 330, 2025: 815, 2026: 248; before 2018-12-07: 2,215; within
  the flight: 231; after 2019-03-08: 4,755; ≥ 2024-09-26: 1,193. FIRM dates: `firm_effective_date` 2021-08-24 365,809,
  2003-09-03 5,126, 2009-08-18 1,817, null 12; `bfe_vintage` 2021-08-24 85,579, 2003-09-03 1,447, 2009-08-18 1,248.
  The 1,193 post-Helene certificates are the only post-2024 input in the pipeline; they are correctly dated per row.

### 11. [note] Personal data and secrets: clean
- `git ls-files` 239 files; grep for `own_name|buildingOwnerName|A1_BUILDING_OWNER|owner_name|taxpayer|mailing`: only
  `pipeline/assemble/check.py:16 FORBIDDEN`. Emails: one county office address in `docs/phase0-sources-survey.md:83`
  (an office, not a person). Secrets / presigned (`X-Amz-|Signature=|token=|apikey|sk-|AKIA|Bearer`): one doc
  sentence in `docs/02` describing an API. Absolute paths: 4 hits (`research/coverage/coast_*.py` ×2,
  `pipeline/train/out/r1_save_12103.log`, `pipeline/train/out/gate_12103_pinellas-r1b-fdemlabels.json`) — cosmetic.
  Parquet columns: buildings (96) and parcels (12) have no name/contact column (`q1.py`, column list; `q2` schemas).
  `pipeline/assemble/out/dates_clean_12103.csv` (tracked, 39 KB) holds OBJECTID + dates + LLM reason only.
  `clean_dates.py` sends `objectid, issuedAt_raw, formYear, firmPanelEffectiveDate, buildingElevationSource,
  buildingDiagramNumber` to OpenAI (`gpt-5.5-2026-04-23`); OpenAI's data page: abuse-monitoring logs "retained for up
  to 30 days" (fetched). Viewer footer attributes Overture (ODbL), FDEM, OSM; it loads `tile.openstreetmap.org` raster
  tiles directly (`viewer/public/app.js:145`) — OSM tile policy requires a valid User-Agent/Referer and forbids heavy
  use; internal + basic-auth is low volume, so a note only.

### 12. [note] Pin integrity holds
- `sha256 data/flood_v1/assemble/buildings_12103.parquet` = `ecea71739977fbecb79b6de8b28aa5a97e95f032800659c0f2ed0edd5d6a93b7`
  (`q1.py`), matching the handoff's `ecea7173…a6d93b7`. The parquet metadata `spatia_flood.inputs` equals
  `pipeline/assemble/out/assemble_12103.json` `inputs` hash-for-hash (diffed by eye in `q1.out`).

## Checked and found sound
- Every input the r0 pipeline reads (grep of `pipeline/assemble/*.py`): spatia-data `overture_buildings` and
  `overture_addresses` 2026-09-23.1, `fl_parcels` 2025 (DOR NAL `asmnt_yr` 2025 on 362,328 rows), `us_counties` 2025,
  `fema_flood_zones` + `fema_bfe_context` 2026.04 @ `20260930T082454Z-9c7789f1`; FDEM FeatureServer
  (`services8.arcgis.com/4L6VuYsPSGSEJ0qe/...`), USGS WESM layer 24, USGS EPT `FL_Peninsular_Pinellas_2018`
  (tiles.json), TIGER 2020 zip (risk polygon only; 0 SFHA buildings outside the risk area), Geocodio v1.7 reverse,
  OpenAI chat completions. **NSI is not used in r0** (only `pipeline/phase0/{measure_fl,risk_area,records_gap}.py`).
- Editions in the parquet metadata = `assemble_12103.json` = the row-level `*_source` strings (footprint_release
  2026-09-23.1 on all rows; one lidar work unit, QL 1, GEOID12B, US survey ft, matching the vendor XML).
- Licence tags are assigned per row exactly as the inputs were used (e.g. `usgs_3dep` only on the 290,540 risk-area
  rows; `fl_dor_nal` on the 368,800 rows with a parcel; `fdem` on the 7,515 matched).
- The county EC layer is not used by any r0 code path (grep `labels_pinellas` only in its own scripts, `train_r1b.py`).
- No ground truth leaks into features: `assemble.py` reads certificates only after the model has predicted (`p` is
  computed from `mm[FEATS]` before `lab` is merged).

## Open questions for the owner
1. Has anyone decided the ODbL route (Collective Database vs Derivative Database) for a GERS-keyed sold table? The
   survey's own Decision §4 says it cannot ship without that; the pilot shipped.
2. Will FDEM certificate values be obtained from FDEM under chapter 119 rather than via the Forerunner-hosted layer,
   or has Forerunner been asked whether its terms cover the ArcGIS Online layer?
3. Should a preliminary Pinellas FIRM be surfaced in r1 (a county-level note at minimum)?
4. Is a `construction_drawings` / `under_construction` certificate ever acceptable as `record`?

## Method
About 30 tool calls: 4 Python scripts over the parquets (`q1`-`q4`), one live FDEM attribute fetch (16 paged GETs
inside `q4.py`), ~20 read-only HTTP GETs for terms/metadata (FDEM item/layer/service, Forerunner, Pinellas service,
Geocodio terms + data-sources, Overture attribution, ODbL, DOR, OpenAI, vendor XML, OSM tile policy; USGS copyright
and FEMA website pages returned 403 via the proxy; `florida.withforerunner.com/terms` is an empty JS shell), WESM
(all queries HTTP 400 today), TNM products API, two S3 prefix listings, FEMA Prelim/Pending/LOMA counts, and greps of
the repo, the spatia-data asset and the viewer. Not checked: geoid grid differences (no grids in pyproj), the
Overture `sources` mix for Pinellas footprints (OSM vs Microsoft vs Esri; needs the R2 layer), R2 contents, and the
Pinellas county portal's own terms page (none found on the service).
