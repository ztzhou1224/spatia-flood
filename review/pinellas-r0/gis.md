# GIS domain review of pinellas-r0

Work dir: `(session work dir, not committed) ` (scripts `*.py`, outputs `*.txt`; every number below is in one of them).
Python: `/home/user/spatia-flood/.venv/bin/python -I <script> /home/user/spatia-flood/data/flood_v1`.

## Verdict

The datum and CRS plumbing is sound: every elevation in the table is NAVD88 with the geoid recorded per row, no
NGVD29 value is used anywhere in Pinellas (all 83,024 static BFEs and all 9,832 lines are `navd88_verbatim`, sigma 0;
certificates are filtered to `navd_1988`, never converted), the GEOID12B/GEOID18 mix is worth at most 0.03 ft here,
and every distance and area is computed in metres in a sensible projected CRS. The table is fit to show a floodplain
manager as a **screening** product, with three things to fix first: (1) `ground_ft` is a ring **minimum**, and on
waterfront and sloped lots it is the seawall base or the water surface, not the building's grade: 770 buildings carry
ground below 0 ft NAVD88, and `raised_flag` / modeled `ffh_ft` inherit the error (on lots where the ring spans > 3 ft,
the model flags 92% of houses as raised, while the certificates on the same kind of lot say 50%); (2) AO zones are
given a neighbouring AE polygon's BFE and called against it, which is not how FEMA regulates AO (highest adjacent grade
+ depth); (3) the BFE-line interpolation pairs lines across non-SFHA ground on two thirds of its rows, which the flat
Pinellas creeks forgive numerically but the method does not justify.

## Findings

### 1. [blocking] `ground_ft` (ring minimum) is water / seawall / slope on thousands of lots; `raised_flag` and modeled `ffh_ft` inherit it
- What: `pipeline/lidar/features.py:32` (`lag = min` of the 0.5–2.5 m ring), `assemble.py:355` (`ground_ft = g_lag`),
  `assemble.py:451` (`raised_flag = p > 3`), `assemble.py:489` (modeled `ffh_ft = p`, the model's target is `ffe − g_lag`).
- Evidence (`elev.txt`, `elev2.txt`, `misc.txt`, `raised.txt`, `batch4.txt`, `ground_vs_lag.txt`):
  - `ground_ft` min −4.83 ft NAVD88; 770 buildings < 0 ft, 507 < −1 ft (612 AE, 152 VE). For those 770 the ring
    **median** sits 5.15 ft above the ring minimum (median), ring range 6.28 ft.
  - 31 of them have a certificate: surveyor LAG − `ground_ft` median **+5.88 ft** (cert LAG median 5.0, our ground −1.41,
    ring median 5.07). The ring median is the surveyor's LAG; the ring minimum is the canal.
  - County-wide, on all 7,482 matched certificates with a LAG: cert LAG − ring min median +0.441 ft (p10 −0.07, p90
    +1.62), 22.8% differ by > 1 ft; cert LAG − ring **median** is −0.145 ft median, 9.5% > 1 ft; MAE 0.81 ft (min) vs
    0.51 ft (median) vs 0.58 (p10). 12.9% of certificate LAGs are below the ring minimum, 7.4% above the ring maximum.
  - `raised_flag`: on ground < 0 lots 402 of 403 modeled rows are flagged (median `ffh_ft` 7.28 ft); on lots with ring
    range > 3 ft, 14,197 of 15,365 modeled rows are flagged (median ffh 4.43) = 35% of all 40,061 modeled flags. The 510
    **certificate** rows on such lots: certificate floor − certificate LAG > 3 ft for 253, but floor − ring min > 3 ft for
    468, and the model flags 468. On lots with ring range ≤ 3 ft the two agree (1,293 vs 1,639 of 6,917).
  - `bfe_call`: among 92,243 SFHA buildings, 7,529 have ring range > 3 ft; 1,219 of them are `below`; 531 of those
    would sit at/above the BFE if the ring median replaced the minimum in `ffe = ground + ffh` (crude, model not re-run).
    The model does compensate on average (ground < 0 rows: modeled FFE median 5.98 ft, only 1 < 1 ft), so `ffe_ft` is
    less affected than `ground_ft`, `ffh_ft` and `raised_flag`.
  - Definition mix: record `ffh_ft` = floor − surveyor LAG, modeled `ffh_ft` = floor − ring min; on the 7,427 record
    rows the two grades differ by +0.444 ft median (p90 1.62 ft), so the one column carries two heights.
- Why it matters: a floodplain manager reading `ground_ft = −2.0` next to a slab house, or `raised_flag = true` on a
  seawall lot, will stop trusting the table; a buyer screening for "elevated" houses gets a list that is one third
  seawalls.
- Fix: publish the ring **median** (`g_med`, already in `features.parquet`) as `ground_ft` or alongside it, keep the
  minimum as `ground_ring_min_ft`; add `ground_ring_range_ft` and a `ground_suspect` flag (range > 3 ft or min < 0 ft
  NAVD88 or `ring_low_share` high); compute `raised_flag` and the published `ffh_ft` against the median; retrain the
  model's target on `ffe − g_med` so record and modeled `ffh_ft` share one grade. The schema doc's "lowest 1 m DEM
  cell in a 0.5–2.5 m ring" is honest but a buyer will read "ground".

### 2. [major] AO zones are called against a neighbouring AE polygon's BFE; AO depth is not carried
- What: `assemble.py:284–286` (highest static BFE of any SFHA polygon the footprint overlaps) and `:294–297`
  (`no_coverage` only for zone A); `docs/06` says "SFHA zone A only (FEMA gives no BFE)".
- Evidence (`fema.txt`, `elev2.txt`): NFHL Pinellas has 6 AO polygons, all `withheld_no_elevation`; `zones_12103_raw`
  has no `depth` column. 92 buildings have `zone_main = AO`; 54 carry `bfe_method = static`, `bfe_ft = 8.0`, taken from
  an AE COASTAL FLOODPLAIN element covering 0.24%–36% of the footprint (sample rows: AO share 0.9976 / AE 0.0024, …).
  Calls on AO: 7 `below`, 4 `above`, 40 `too_close`; 16 decided among the 127 buildings touching any AO polygon. The
  other 38 AO rows are `no_coverage`. 4 AH buildings have a BFE (AH carries one: correct).
- Why: in AO the regulatory elevation is the highest adjacent grade plus the depth number (NFHL `DEPTH`), not a
  BFE; a 1 ft AO depth on a lot at 9 ft grade is a 10 ft requirement, which the 8 ft AE BFE understates, and vice versa.
  The 7 `below` / 4 `above` AO calls are not FEMA-meaningful.
- Fix: carry `DEPTH` from S_FLD_HAZ_AR (ask spatia-data `fema_flood_zones` to expose it); for any building whose
  largest SFHA share is AO, set `bfe_null = not_evaluated` with a note, or compute `regulatory_elev = HAG + depth`
  as a distinct method; never let a sliver of AE supply the BFE when the main zone is AO. Fix the doc text.

### 3. [major] BFE-line interpolation pairs lines across non-SFHA ground on two thirds of its rows
- What: `assemble.py:164–204` (`interpolate_bfe`: L2 = nearest line on the opposite side among lines crossing any of the
  building's SFHA polygons within 1 km; no same-reach test; the lines parquet has no stream name).
- Evidence (`interp.txt`, `interp2.txt`): 5,250 interpolated rows, all DFIRM 12103C (AE 4,102, X-main 1,141, A 7);
  L1 median 58 m (p99 270), L2 median 189 m (p99 614 m); segment L1→L2 median 252 m. The straight segment between the
  two nearest points is covered by the SFHA union for only 1,779 of 5,250 (33.9%); 2,051 rows have > 25% of the
  segment outside the SFHA, 1,109 > 50%. Pairs with different panel dates: 85; line panel date ≠ the building
  polygon's panel date: 268 (e.g. 67 rows take a 2003-09-03 line inside a 2021-08-24 polygon). Numerical impact is
  small because Pinellas creeks are flat: |e1−e2| median 0.4 ft (p90 1.0, 31 pairs > 3 ft; 0.3 ft median where the
  segment leaves the SFHA). The handoff's check (124 static-BFE buildings, MAE 0.415) is on coastal/combined polygons
  that happen to carry lines, not on the riverine rows where interpolation is used.
- Why: "linear in distance between two lines" assumes one reach; crossing a ridge into another creek (Cross Bayou vs
  Joe's Creek, Alligator vs Curlew) gives a number that is only right because both are near 10 ft here. Elsewhere
  (Harris County) this will silently fail.
- Fix: require the L1→L2 segment (or the building→line segments) to stay inside the SFHA polygon(s) of the building;
  else `not_determinable`. Ask spatia-data to add `WTR_NM` (S_XS) to `fema_bfe_context` and pair only lines with the
  same source. Report the check on the interpolated population (e.g. hold out lines).

### 4. [minor] Three FIRM effective dates in Pinellas, not one; the docs imply a 2021 countywide map
- Evidence (`fema.txt`, `misc.txt`): `firm_effective_date` 2021-08-24: 365,809; 2003-09-03: 5,126 (interior, lon
  −82.75..−82.67, 1,880 touch the SFHA); 2009-08-18: 1,817 (Pinellas Park, lat 27.81–27.84, 971 in SFHA); null 12.
  Polygons 12103C with pre-2021 panel dates: 658 (mostly X and 0.2%, plus 85 AE, 24 A, 13 floodway). `bfe_vintage` for
  1,320 interpolated and 127 static rows is 2003-09-03.
- Why: a buyer assuming "Pinellas = 2021 coastal restudy" will misread a 2003 riverine BFE as recent.
- Fix: say in `docs/06` and the layer notes that panel dates are per polygon and three dates exist; surface the
  count in the coverage map.

### 5. [minor] "Highest BFE of overlapped polygons" vs "largest-share polygon"
- Evidence (`bfe_rule.txt`): 1,323 buildings overlap > 1 SFHA polygon with a static BFE; for 559 the highest differs
  from the largest-share polygon's BFE (555 AE+VE straddles; median 1 ft, max 4 ft). Calls there: 273 below, 175
  too_close, 28 above; only 1 `below` would move with the largest-share BFE.
- Correct for compliance (the higher applies); disclose that for straddling AE/VE lots the call uses the VE BFE.

### 6. [minor] Overture WGS84 footprints are placed on NAD83(2011) lidar with a null datum shift
- Evidence (`datum_shift.txt`): `Transformer("EPSG:4326"→"EPSG:6442")` uses "NAD83(2011) to WGS 84 (1)" (null,
  accuracy 2 m). If the footprint coordinate is effectively ITRF2014@2020, the true offset at Clearwater is dx +0.64 m,
  dy −0.64 m, |d| 0.90 m: a third of the 0.5–2.5 m ground ring and most of the 0.3 m / 1.0 m inner roof buffers.
  Same for the DEM (EPSG:26917). Overture's own placement error is larger, so this is second order; note it in the
  method and consider a Helmert step when a better footprint source arrives.

### 7. [note] FEMA semantics not represented (document, do not fix in r0)
- LiMWA / Coastal A: NFHL S_FLD_HAZ_AR has no LiMWA; S_Gen_Struct is not read (`grep` over docs/pipeline: no hit).
  AE "COASTAL FLOODPLAIN" rows (74,027 buildings) include the Coastal A strip where V-zone construction applies.
- V zones: 66 `above` calls among 1,744 buildings touching VE. 11 of them have a county certificate with C2c (bottom of
  lowest horizontal member, NAVD88-native): none has C2c below our BFE (C2c − BFE median 3.5 ft; our floor − C2c
  median 1.7 ft) — the documented limit did not flip a call in this sample (`batch4.txt`).
- LOMA / LOMR-F are not in the polygons, so a removed building still reads `touches_sfha`; preliminary FIRMs are not
  considered. `touches_sfha` any-overlap: 1,240 of 92,243 under 1% (2 of them `below`), 2,605 under 5% (`fema.txt`).

### 8. [note] Stacked parcels (condos) are modeled as houses
- Evidence (`misc.txt`): 28,546 buildings with `parcels_at_centroid > 1` (max 1,104); 22,797 get a modeled floor (DOR
  002: 10,222, 004: 8,881), 3,395 are `below`. A condo tower's "first living floor" from a single-family model is a
  different object; the model reviewer owns this, but the GIS join (centroid in a stack) is what admits them.

## Checked and found sound
- **Vertical chain.** WESM work unit `FL_Peninsular_Pinellas_2018`: QL 1, `vert_crs` 6360 (NAVD88 ftUS), GEOID12B;
  `meta.json`: DEM EPSG:26917 metres, EPT z NAVD88 metres, both divided by 1200/3937 (`features.py:17,30`, `:70`):
  `ground_ft`, `roof_ft`, `eave_ft` are US survey feet. `ground_geoid = GEOID12B` on all 290,540 rows,
  `ground_precision_ft` 0.328 ft = 10 cm RMSEz (LBS 1.3 QL1). `ffe_datum` names the geoid (modeled) or says "geoid not
  stated" (record). NFHL: 1,368 polygons `NAVD88 / Feet / navd88_verbatim`, 5,893 `withheld_no_elevation`; no NGVD29
  row in Pinellas, every `bfe_precision_ft` is 0 or null, so the sigma `too_close` path is dead here. Lines: all
  NAVD88 verbatim. Certificates: `labels.py:44` keeps only `verticalDatum == navd_1988` (NGVD29 rows dropped, never
  converted); `fdem_lag` `cert_datum` is `navd_1988` on all 7,515. GEOID12B vs GEOID18 (grids fetched from
  cdn.proj.org, `geoid_diff2.txt`): at 5 Pinellas points the NAVD88 height differs by −0.001 to +0.029 ft. ftUS vs
  international foot: 2 ppm, 0.0002 ft at 100 ft.
- **Horizontal.** GeoParquet `geo` metadata carries an explicit PROJJSON `OGC:CRS84` (lon, lat) on both the building
  and coverage files (`schema.txt`). Areas in EPSG:3086 (areal scale 1.000000; ratio to EPSG:6442 area 0.99999,
  min 0.999944). Distances: certificate 10 m match in EPSG:6442 (metres, `labels.py:39`), 1 km line search / 500 m risk
  buffer / address pick in EPSG:3086 (metres), ground ring in EPSG:26917 (metres); no degree-based distance anywhere
  (`grep_dist.txt`). EPSG:6442 axes are metres; EPT 3857→6442 with `always_xy` (`job.py:222`).
- **Zones.** Distinct zones/subtypes and counts in `fema.txt`; 12 buildings with no polygon; share sums never > 1.01.
  Risk polygon: buffer in 3086, back to CRS84; contains every SFHA building and all but 1 of the 0.2% buildings; open
  water polygons are not SFHA and not 0.2%, so excluded.
- **Coverage map.** `h3.latlng_to_cell(lat, lon, 8)` order correct; 1,225 cells sum to 372,764 / 290,540 / 92,243 /
  7,427 / 240,356; independent recompute: 0 mismatches; swapped order would hit 0 file cells; every cell polygon
  contains its own centre.
- **Footprints.** 1,193 centroids outside their footprint (doc claim confirmed), 0 invalid, 31 multipolygons; area
  p50 202 m², p99 1,719, 2,891 > 2,000 m² (2,373 in the risk area, all `not_evaluated`). Certificate match proxy
  (county EC layer, 19,382 points, WKID 4326, `certmatch.txt`): 86.8% inside a footprint; of the 2,565 outside, 80%
  are within 10 m and 93.7% within 25 m of a footprint, 161 beyond 25 m: unmatched certificates are mostly coordinate
  offsets, not missing footprints.
- **Elevation sanity.** `ground_ft` max 98.2 ft, 14,577 > 60 ft all at lat 27.86–28.09 (Clearwater/Dunedin ridge);
  record FFE 2.28–89.9 ft, modeled 0.33–105.7; 0 rows with `ffe < ground − 1`; record FFE − ground p05 0.64 ft;
  BFE 6–87.9 ft (the 88 ft interpolated BFEs sit on an 85–88 ft ridge pond, consistent); 12 static BFEs > ground + 15
  are VE 14–16 ft lots with ground ≈ −2 ft (finding 1).

## Open questions for the owner
1. Does spatia-data's `fema_flood_zones` keep NFHL `DEPTH` and `VELOCITY`? Without `DEPTH` the AO rows cannot be fixed.
2. Is `fema_bfe_context` able to carry `WTR_NM` (S_XS) so interpolation can pair lines of one flooding source?
3. Should `ground_ft` stay the ring minimum (NFIP "lowest adjacent grade" intent) with a suspect flag, or become the ring
   median (closer to surveyed LAG by every measure here)? The model target must follow the same choice.
4. The DEM tile's own vertical metadata was not read (no rasterio/GDAL in this venv); the GEOID12B claim rests on WESM.

## Method
About 24 tool calls: read CLAUDE.md, handoff, schema doc, `assemble.py`, `labels.py`, `risk_area.py`, `coverage.py`,
`features.py`, `prepare.py`, `ept.py`, `job.py` (grep), `meta.json`, `assemble_12103.json`, `run13.log`; 16 scripts in
`work_gis/` (DuckDB / shapely / pyproj) over the assembled table, zones, lines, features, labels, FDEM LAG, WESM,
coverage and the county EC raw pages; fetched the two NOAA geoid grids from cdn.proj.org. Not checked: FDEM raw
(`data/fl/ec_all.json` absent, so the 624 unmatched FDEM certificates were not sampled; the county layer stood in),
the DEM tile header, NFHL S_Gen_Struct / LiMWA, anything on R2.
