# Implementation (code correctness) review of pinellas-r0

Work dir: `(session work dir, not committed) ` (scripts `s01`..`s07`, outputs `s02.out`, `s03.out`, `retrain/`,
`fdem_dl/`). All numbers below come from those scripts run in this session on the local run13 data.

## Verdict

The assembly arithmetic is sound: every stored derived value I recomputed from the table's own columns (modeled
`ffe = ground + ffh`, both bands, `floor_minus_bfe` and its band, the `bfe_call` rule of docs/06, `raised_flag`,
`touches_sfha`, `sfha_share`, `zone_main`, `in_risk_area`, the 5,250 interpolated BFEs) matched with 0 mismatches,
the training artefacts rebuild byte-identically (same `model_version`), and the units/CRS chain (ftUS, EPSG:6442 metres,
EPSG:3086 areas, EPSG:26917 DEM ring) is consistent. It is fit to show a floodplain manager as a pilot with the
docs/06 caveats. The things to fix before the next release: (1) the certificate-selection rule in
`pipeline/train/labels.py` is not "latest wins": an undated certificate beats a dated one and same-date ties are
broken by an unstable sort, which changes the record FFE of ~52 buildings and the sign of `floor_minus_bfe` for 10
(the county-EC script already carries the fix); (2) the parcel table has 192 duplicated `parcel_key`s; (3) sliver
SFHA overlaps (754 buildings with < 1 m² of footprint in the SFHA) drive BFE and calls while the `zones` list shows
`share: 0.0` for 99 of them; plus there is no lint config and no test at all.

## Findings

### 1. [major] "Latest certificate wins" is not what `labels.py` does: undated certificates win, same-date ties are arbitrary
- Where: `pipeline/train/labels.py:45` and `:66` — `sort_values("issuedAt").drop_duplicates(..., keep="last")`.
  pandas' default `na_position="last"` puts a certificate with no `issuedAt` AFTER every dated one, so it is the one
  kept; the default `kind="quicksort"` is not stable, so among equal dates the kept one depends on input order.
  `pipeline/labels_pinellas/build.py:158,186` (r1b, unused in r0) already uses `na_position="first"`, so the author
  knew; r0 was built with the old rule. Same pattern in `phase0/{risk_area,measure_fl,records_gap}.py` (counts only).
- Evidence: `s05_fdem_fetch.py` fetched the FDEM public layer for the run bbox (10,668 residential NAVD88 certificates,
  no owner/address fields), `s06_labels_dedupe.py` re-ran labels.py's exact selection: it reproduces the r0 label set
  exactly ("same cert as r0 label for the same building: 7515 of 7515"), so the comparison is on the real population.
  Output: "buildings with >1 matched certificate: 144"; "(a) buildings where labels.py keeps an UNDATED certificate
  although a dated one exists: 8" (47 at the propertyId stage, of 1,432 properties with a dated sibling);
  "(c) buildings with >=2 candidate certificates on the SAME issuedAt: 69 … tied certificates disagree on ffe by
  >0.1 ft: 18 | >1 ft: 7"; "chosen certificate differs between quicksort and mergesort (same rule): 298".
  `s07_tie_effect.py`: "as-written vs na_first+stable: certificate differs 344; ffe differs >0.1 ft 52; of those
  record-class in layer 51; sign of floor_minus_bfe would flip 10; |dffe| quantiles {0.5: 0.0, 0.9: 0.4, 0.99: 7.04,
  1.0: 58.5}". The 8 undated-kept buildings are all `ffe_class = record` in the layer (6 `above`, 1 `below`), and 1
  differs from the latest dated certificate by 3.4 ft.
- Why it matters: the record FFE (the value a floodplain manager trusts most) is chosen by an accident of sort order
  for ~300 buildings; for 8 the older-looking undated form overrides a dated one, and the LLM date estimate
  (`record_vintage_note`) is then applied to a certificate that had a dated sibling. The label set used to train and
  gate the model is affected the same way (344 of 7,515 labels).
- Fix: `sort_values(["issuedAt", "OBJECTID"], na_position="first", kind="stable")` in both places (and in the
  phase0 counters); document the tie rule (highest OBJECTID on equal dates) in docs/06; rebuild labels → train → gate.

### 2. [minor] Parcel table: `parcel_key` is not unique (not published, so no customer impact yet)
- Where: `assemble.py:646-651` writes one row per `fl_parcels` row; `parcels_raw_12103.parquet` has 432,360 rows for
  432,087 distinct `parcel_id` (`s04_misc.py`).
- Evidence: "duplicated parcel_key rows: 465 distinct keys: 192 max copies: 11"; "duplicated keys whose copies have
  DIFFERENT geometry groups: 7 of 192"; 54 buildings carry a duplicated key. Copies agree on `any_building_below_bfe`.
- Why: any join on `parcel_key` fans out; the building table's `parcel_key` is advertised as the parcel identity.
- Fix: aggregate `pa` by `parcel_id` (union of geometries or keep the largest) before `read_parcels` caching, or make
  `parcel_key` carry a geometry ordinal; assert uniqueness in `check.py`.

### 3. [minor] Sliver SFHA overlaps drive BFE and calls, and the `zones` list hides them
- Where: `assemble.py:272` rounds shares to 4 dp; `:280-281` `touches_sfha = sfha_share > 0`; `:284` takes the
  highest static BFE of ANY overlapping SFHA polygon; `:308-310` interpolates for any SFHA touch.
- Evidence (`s04_misc.py`): "touches_sfha True but every sfha zone share rounds to 0: 99 … bfe_call {'above': 44,
  'too_close': 40, nan: 15} | bfe_ft set: 92"; "touches_sfha with sfha_share < 0.001: 374 | bfe_call {'above': 154,
  'too_close': 128, 'below': 1}"; "footprint_area_m2 * sfha_share < 1 m2 and touches: 754". `s03`: 7 buildings
  with `zone_main = A` (shares 0.91-0.99 in A, which has no BFE) received an interpolated BFE through a 1.5-9% AE sliver.
- Why: a consumer reading `zones` sees `AE share 0.0` next to `touches_sfha = true` and a BFE; docs/06 says slivers
  count (FEMA rule), but 1 m² is below NFHL digitising accuracy and the resulting call is presented like any other.
- Fix: keep the rule but add `sfha_area_m2` (raw) and flag `sfha_sliver` (< 1 m² or < 0.1%) so the viewer and the
  call basis say so; print shares with enough precision or as area.

### 4. [minor] Null-reason branches that disagree with each other or with the schema
- `assemble.py:496` vs `:517`: a certificate rejected against lidar on a NON-eligible building gets
  `ffe_null = not_determinable` but `ffh_null = not_evaluated` (3 rows, `s04_misc.py`; DOR 010/083/017 in the risk
  area). docs/06 says a rejected certificate "falls back to the model, or null not_determinable".
- `job.py:182`: a building straddling DEM tiles with no tile hit gets `ground_status = not_determinable` (no DEM at
  all → should be `no_coverage`); 0 cases in Pinellas (ground ok 290,540) but wrong for the next county.
- `assemble.py:576` labels the 144 address-less buildings `not_evaluated` "until geocodio.py has run" although it
  has run; all 144 are outside the risk area (consistent with docs/06 only because Geocodio is risk-area-only).
- `assemble.py:598`: `model_version` is set on 7,264 record-class rows and `raised_flag` on 7,297 (documented as
  "every model-eligible building"), and 33 record rows with no usable certificate LAG get `ffh_null =
  not_determinable` although a model `ffh` exists for them (`:496`, documented). A consumer filtering
  `model_version.notna()` will count record rows as modeled.
- Fix: one `why_not` table per row computed once and reused by `ffh/ffe/raised`; `no_coverage` in job.py's straddle
  branch; `address_null = no_coverage` after Geocodio; consider `model_version` only where `ffh_class = modeled`.

### 5. [minor] No lint configuration, 22 lint errors, format check fails on 24 of 26 files, no tests
- Evidence: `ls pyproject.toml ruff.toml setup.cfg mypy.ini tests` → none exist; `.venv/bin/ruff check pipeline viewer`
  → "Found 22 errors" (RUF100 10, I001 4, ISC004 2, C408 2, FURB122, SIM114, S110, F401 1 each; files: job.py 5,
  train_r1b 3, assemble 2, …); `ruff format --check pipeline` → "24 files would be reformatted, 2 files already
  formatted" (default line length 88 vs the code's ~120); `find . -name "test_*.py"` → nothing. CLAUDE.md asks for
  "typed and ruff-clean". `check.py` (the only automated check) passes: 0 violations on all 13 value columns.
- Minimum test set: (a) `nulls()`/`why_not` branch table on a 20-row synthetic frame covering every
  risk × parcel × residential × lpc_status × certificate case; (b) `interpolate_bfe` on two parallel lines (f, band,
  one-side → not_determinable, none → no_coverage); (c) `overlay` on a square straddling two polygons (shares sum to 1,
  contains_properly path); (d) the `bfe_call` truth table (record/modeled × static/interpolated × above/below/straddle,
  equality at the BFE); (e) labels dedupe with an undated and a same-date pair; (f) `features.ground_stats` units on a
  constant DEM (metres in → ftUS out); (g) `check.py` as a pytest; (h) a worker.js path-regex test for `..`, `%2e`, long
  cells.

### 6. [note] Viewer / Worker
- `viewer/src/worker.js`: `same()` is constant in content but its loop length is `max(len)` so it leaks the secret's
  length only; `VIEWER_USER` is a plain var (`wrangler.toml`), if it were unset `TextEncoder.encode(undefined)` would
  accept the literal user "undefined"; fail-closed on a missing password is correct. `DATA_PATH` allows only
  `[A-Za-z0-9._-]+` for the release and a 15-hex cell; `URL.pathname` normalises `.`/`..`/`%2e` segments before the
  regex, and R2 keys are flat, so no escape from `_flood/viewer/<fips>/<release>/`. No CORS headers (same-origin
  only), data `Cache-Control: private, max-age=3600`, gzip passed through with `encodeBody: "manual"`: fine.
- `pipeline/viewer/export.py:212` puts EVERY column in `rec/<cell>.json`: besides addresses (by design) that is
  `parcel_id_native`, and FDEM certificate OBJECTIDs inside `ffe_source`/`record_note` (e.g. "FDEM elevation
  certificate OBJECTID 203382, …"), which resolve on the public FDEM layer to a record carrying the owner name. No
  owner/name column exists in the table (`check.py` "owner / personal columns: 0").

### 7. [note] Other observations (no wrong value found)
- Stacked condo parcels: `assemble.py:393` `drop_duplicates("b")` keeps whichever parcel the STRtree lists first;
  1,107 buildings have 1,104 parcels at the centroid (`s02`), so their `parcel_key`/`dor_use_code`/`year_built` is one
  arbitrary unit. Deterministic, but meaningless for condos; `parcels_at_centroid` is the only hint.
- `assemble.py:623` uses Python `hash()` on WKB (salted per process); group ids come from first-occurrence order so
  they are stable, but a 64-bit collision would silently merge two parcels.
- 4 situs addresses end with "," (empty city/zip, `s03`); 0 contain "nan"/"None".
- Record-class rows: `ffe_record_lidar_conflict = True` on 54 rejected certificates whose `ffe_class` is modeled/null
  (51/3) — the flag then describes a certificate the row does not show except in `record_note`.
- The held-out gate scores only certificates that pass the lidar screen (`train.py:101`, `assemble.py:438`), so the
  reported MAE/coverage exclude the 298 of 7,485 labels that disagree with lidar (method caveat, other angle).

## Checked and found sound
- Row identity (`s02`): 372,764 rows, `building_id` unique; features/run/labels/fdem_lag/records all unique on their
  keys; run set ⊂ county set; labels all in the run; `fdem_lag` joined 1:1 on `cert_objectid`, datum navd_1988 for
  all 7,515. `check.py`: 0 violations.
- Arithmetic (`s02`), 0 mismatches each: `ffe = ground + ffh` and both `ffe_band` (240,356 modeled); `floor_minus_bfe`
  and its band (set iff a band exists, `lo = flo - bhi`, `hi = fhi - blo`); `bfe_call` recomputed from the docs/06 rule
  (record: `>=` BFE top = above, sigma rule never fires because every static sigma is 0; modeled: band clears; both
  with the interpolated band) against all 372,764 stored calls; `raised_flag == ffh > 3` on modeled rows;
  `touches_sfha == sfha_share > 0`; `sfha_share` = sum of SFHA zone shares (max |d| 1e-4 from rounding);
  `zone_main`/`zone_main_subtype` = `zones[0]`; zones sorted by share; no share sum > 1.01.
- `in_risk_area` (`s03`): centroid-in-risk-polygon = 290,540 = `in_risk_area`, 0 disagreements either way;
  `lon/lat` columns equal the footprint centroid exactly; 1,193 centroids outside their footprint (docs/06 says 1,193).
- BFE interpolation (`s03`): re-running `interpolate_bfe` on the cached zones/lines reproduces all 5,250 values and
  bands exactly; every interpolated BFE lies inside its band; widths median 1.4 ft, 9 over 5 ft; 81 lines without
  elevation are dropped. 9 A-only buildings that lines could interpolate are deliberately `no_coverage` (rule).
- Units/CRS (`s01`): EPSG:6442 is metres (so the 10 m nearest match and 1 km blocks are metres), EPSG:6443 is the
  ftUS twin; EPSG:3086 metres for areas/buffers; DEM EPSG:26917 metres so the 0.5–2.5 m ring and the 10–30 m far ring
  are metres; `features.py` divides DEM metres and EPT z metres by `1200/3937`, so `ground_ft`, roof and eave are US
  survey feet as documented (EPSG:6360 is ftUS). intl-vs-US foot = 2.0 ppm = 6.0e-5 ft at 30 ft: immaterial.
  3857 → 6442 and 4326 → projected transforms all `always_xy=True`; no `*_Spheroid` anywhere; h3 called `(lat, lon)`
  and `cell_to_boundary` swapped to (lon, lat) correctly in coverage.py.
- numpy fixed-width strings: numpy 2.5.3; every branch mixes in `None` (object) or `.astype(object)`; all distinct
  string values in the table are intact (`not_applicable`, `record_lidar_conflict+interpolated_bfe` …). No chained
  assignment that pandas 3.0 CoW would silently drop. `dor_use_code` is a 3-char zero-padded string for all 368,800
  parcelled rows, so `< "010"` selects exactly 000-009 (315,459).
- Dates: `issued_at` float ms, 264 null; stored record vintages 2009-11-16..2026-09-28, none after the build date or
  before 1990; 260 LLM windows, 261 notes; `firm_effective_date` 2003-09-03..2021-08-24 (the 2030 value lives only in
  the certificate field used as LLM context). The -1..30 ft filter is applied twice as documented: certificate FFE
  minus lidar `ground_ft` (ftUS NAVD88, 54 rejected) and FFE minus the certificate's own LAG (34 unusable).
- Training (`retrain/`): re-running `train.py` from the same inputs reproduces `model`, `difficulty` and `bands` with
  identical sha256 and the same `model_version` `E-lgbm-12103-62f502979c3b`, and an identical `train_12103.txt`;
  `gate.py` and assemble's recheck agree (n 1315, MAE 1.039, coverage 0.918). No feature reads a certificate field
  (`FEATS` = ground shape, point cloud, DOR year/area, footprint area, label-free eave medians); the split is seeded.
- Licences/addresses (`s03`): 6 OSM-sourced Geocodio rows carry `openstreetmap:ODbL-1.0`; 727 Geocodio tags; no
  owner column anywhere (`grep` of `own_name|buildingOwnerName|A1_BUILDING_OWNER` hits only docstrings/allowlists).

## Open questions for the owner
1. Finding 1 changes up to 52 record FFEs and 344 labels: rebuild r0 (new roster pin) or carry to r1?
2. Should a < 1 m² SFHA overlap really produce a BFE and a decided call (754 buildings), or a `too_close`/sliver flag?
3. Is the parcel table going to be published? If so finding 2 becomes blocking.
4. Is exposing certificate OBJECTIDs (resolvable to owner names on the FDEM layer) in the viewer record acceptable?

## Method
24 tool calls: 1 read of the brief, ~10 reads of code/docs/outputs, 1 read-only FDEM public-layer fetch (no paid API,
no owner fields), and 9 scripts (`s01`–`s07`, a scratch re-run of `train.py` writing only into the work dir, and
`check.py`/`ruff`). Not checked: the EPT z-metres claim and the 3857→6442 point-level validation (needs the LAZ
tiles), `geocodio.py`/`clean_dates.py` network paths (no keys), `export.py` output (writing under `data/` was not
allowed), the live Worker, and the r1/r1b scripts beyond a leak grep.
