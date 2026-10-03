# Plan: Harris County floor-height pilot

Status: **PLAN — GIS review: see § GIS Expert Review.** Nothing is built. A separate session
implements this, phase by phase, against the acceptance criteria. Facts marked *(measured
2026-10-03)* were checked by query when the plan was written; re-check before relying on them.

## 1. Goal

Find out, on real houses, **how accurately each available method recovers a house's first-floor
elevation** (FFE, NAVD88 ft) and first-floor height above ground (FFH), at what coverage and cost,
using Harris County's measured door elevations as the answer key. The output is a ranked benchmark
and a recommendation of which method(s) to build into the product. Not a product, not a published
dataset.

Questions the pilot must answer:

1. Accuracy of each method (MAE, within 0.5 / 1 ft, bias, 90th-percentile error) on FFE and FFH.
2. Coverage: share of houses each method can score (imagery present, door visible, ground resolvable).
3. Where each method fails: foundation type, setback, vegetation, image age, raised-since-capture.
4. Whether a fused model with calibrated intervals can triage houses into "clearly above / clearly
   below the BFE / survey needed", and how many land in each bucket.
5. Cost per 1,000 houses (API calls, model inference, compute).

Non-goals: building any of this for production; areas outside the three pilot areas; data-sharing
deals (owner decision 2026-10-03); publishing anything derived from Google imagery.

## 2. Pilot areas

Three areas chosen for contrast; counts are answer-key points inside each bounding box *(measured
2026-10-03, HCFCD FeatureServer layer 23)*.

| Area | Bounding box (lon/lat, CRS84) | Answer-key points | Why |
|---|---|---|---|
| A. Meyerland (inside Houston) | -95.480, 29.670 → -95.440, 29.700 | 7,821 | ELEV-VISION's test area (comparability); repeatedly flooded (2015–17), many houses raised since → tests stale-truth handling. Mostly "Houston Delivery 1" points, captured Dec 2017–Apr 2018; mean stated height precision for its front-door points is ~10 in (the loosest). |
| B. Cypress Creek (unincorporated NW) | -95.580, 29.950 → -95.530, 29.990 | 7,740 | Newer suburban stock; "Harris County Delivery 1", captured Nov 2019–Jun 2020; precision ~2–4 in. |
| C. Clear Lake (SE, near Galveston Bay) | -95.130, 29.530 → -95.080, 29.570 | 4,825 | Coastal-influenced, mixed raised and slab houses; precision ~1–4 in. |

Structure types in Area A from layer 24: SFR 7,264, MFR 117, COM 95, ZERO 16, AUX (auxiliary;
never counted) *(measured; the AUX count hit the 2,000-row statistics cap, so treat it as ≥ 2,000)*.

## 3. Answer key and context from HCFCD (public ArcGIS FeatureServer)

Service: `https://services7.arcgis.com/NQSCMzARMhPjRo7j/arcgis/rest/services/Structure_Inventory/FeatureServer`
(native CRS EPSG:6587; request `outSR=4326`; max 2,000 records per page).

| Layer | Use | Key fields |
|---|---|---|
| 23 `Finished_Floor_Elevations (Cyclomedia)` — **the answer key** | FFE truth | `Z` (ft), `Location` (Front Door / Garage Door / Sliding Glass Door / Structure Obstructed / Concrete Slab), `Ht_Precision` (inches), `HCAD_NUM`, `RecordedAt`, `Source` (delivery), `X`, `Y` |
| 24 `STRUCTURE_INVENTORY` | year built, structure type | `YearBuilt`, `WWCStrucType` (SFR/MFR/COM/ZERO/AUX), `HCAD_NUM`, `LiDARElev`, `SuggestFFE` |
| 25 `BUILDING_FOOTPRINTS_LiDAR_2018` | footprints, same epoch as 2018 lidar | polygon |
| 26 `BUILDING_FOOTPRINTS_2017` | HCAD footprints (backup) | polygon |
| 21 / 22 flooded structures (Harvey %, flood events) | context only, reported in results | point |

Answer-key semantics (from the layer description): one point per structure; `Z` is taken **at the
base of the front door** when visible; else at the base of the **garage** door; if neither, at the
**top** of a sliding glass door. Datum NAVD88 **GEOID12B**. Cyclomedia mobile lidar.

Rules:

- **Scoring set** = `Location = 'Front Door'`, structure type SFR (via `HCAD_NUM` → layer 24), not
  AUX. Garage-door points scored separately (a garage slab often sits lower than the floor);
  Sliding Glass Door (top of door), Structure Obstructed and Concrete Slab are excluded.
- **Precision tiers** from `Ht_Precision`: A ≤ 3 in, B 3–6 in, C > 6 in. Headline numbers use A+B;
  C is reported separately.
- **`SuggestFFE` and `LiDARElev` are never features or baselines.** The layer-24 description says
  Cyclomedia FFEs were incorporated for ~63% of its points, so `SuggestFFE` leaks the answer.
- **Stale truth**: a house raised, rebuilt or regraded after `RecordedAt` no longer matches its key.
  Flag it with the 2018→2024 lidar change test (§4.5) and the image date; score flagged houses
  separately and never count them against a method in the headline.
- The answer key is read only by the scorer (`eval/`). No method, feature builder or neighbour
  statistic may read it, except the explicitly labelled neighbour-label method M1b, which uses
  spatially held-out blocks.

## 4. Data layers to build (pilot extent only)

All outputs to `data/` (gitignored) as GeoParquet in OGC:CRS84 plus small CSV summaries in
`results/`. Each layer writes a sidecar JSON: source URLs, dates, CRS, datum, geoid, units, counts.

### 4.1 1 m lidar ground (the only lidar layer built)

Sources *(measured 2026-10-03; TNM API and WESM via spatia-data's `us_3dep_lidar_availability`)*:

| Project | Quality | Collected | Geoid | Horizontal CRS | Tiles per area | Size per area |
|---|---|---|---|---|---|---|
| `TX_CoastalRegion_2018_A18` (primary) | QL2 | 2018-01-13 → 2018-06-11 | GEOID12B | EPSG:6344 (UTM 15N) | 2 | 0.75–0.83 GB |
| `TX_Houston_B24` (change detection) | QL1 | 2024-02-18 → 2025-01-31 | GEOID18 (one work unit GEOID12B) | EPSG:6344 / 6343 | 2 | 0.75–0.83 GB |

Download URLs: `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/<project>/TIFF/USGS_1M_15_x..y.._<project>.tif`
(10 km tiles, float32 metres, bare earth, hydro-flattened). Get the tile list from
`https://tnmaccess.nationalmap.gov/api/v1/products?datasets=Digital%20Elevation%20Model%20(DEM)%201%20meter&bbox=…`.

Rules: read each tile's CRS and nodata from the file; metres → feet by `/ 0.3048` exactly; record
geoid per value. The 2018 project is the primary ground, because it matches the answer key's datum
(GEOID12B) and, for Area A, its capture season. For any comparison between the epochs, convert one
to the other's geoid with NGS tools and state the offset applied; never difference GEOID18 against
GEOID12B silently.

### 4.2 Footprints

HCFCD layer 25 (lidar 2018 footprints) as primary; Overture buildings (spatia-data R2
`layers/national/overture_buildings.parquet`, pinned release) as a cross-check. Match each
answer-key point to a footprint: the footprint whose boundary is nearest the point, within 5 m,
on the same HCAD parcel. Ambiguous or missing matches are excluded and counted.

### 4.3 Ground around each building (from the 1 m DEM)

Per footprint, per lidar epoch: an exterior ring 0–3 m outside the footprint, excluding pixels inside
other footprints; `ring_min`, `ring_p10`, `ring_p50`, `ring_p90`, pixel count. Also `door_ground` =
p10 of ground pixels within 3 m of the answer-key point's projection onto the footprint edge (used
only by the scorer to derive FFH truth), and `front_ground` = p10 of the ring segment facing the
nearest street (usable by methods). Compute in EPSG:6344 metres; coverage weights by pixel area.

FFH truth = `Z − door_ground` (scorer only). FFE truth = `Z`.

### 4.4 Street elevation

Road centrelines (TIGER/Line roads, or spatia-data `tiger_roads_all`). For each footprint: the
nearest road segment, the footprint's facing side, and the 1 m DEM ground along the centreline
within ±15 m of the projected frontage point (min and median). ELEV-VISION-style methods measure the
door height **relative to the street**; this turns that into an elevation.

### 4.5 Change since the answer key (stale-truth flag)

- Ground change: `ring_p50(2024) − ring_p50(2018)` after geoid alignment; flag |Δ| > 0.5 ft.
- Structure raised: from the lidar **point clouds** (LPC; ~1.7–2.9 GB per area per project
  *(measured 2026-10-03)*), roof height = p90 of first returns inside the footprint minus ring
  ground; flag a roof-height increase > 1.0 m between epochs. If LPC processing is too heavy, defer
  to Phase 5 and use imagery dates plus Harvey flooded-structure layers as a weaker flag; say so in
  the results.

### 4.6 Flood context

From spatia-data (R2): `fema_flood_zones` Texas partition → zone, SFHA flag, static BFE (NAVD88)
covering each footprint (largest share and any-touch); FIRM panel date. Used to report the
"above / below BFE" triage for SFHA houses. Year built and structure type from layer 24.

### 4.7 Street imagery index

Mapillary first, Google Street View as a pilot-only fallback.

- **Mapillary (API v4, needs `MAPILLARY_ACCESS_TOKEN`)**: query images within 40 m of each
  footprint; keep fields id, geometry and computed geometry, compass angle (computed if present),
  captured_at, is_pano, camera type and parameters, sequence id, image URL (2048 px). Choose up to
  3 views per house: camera 8–35 m from the facing façade, view direction within ±30° of the
  bearing to the footprint's facing side (any heading for panoramas, cropped later), preferring the
  date closest to the answer key's `RecordedAt` and, separately, the newest.
- **Google fallback (needs `GOOGLE_MAPS_API_KEY`) — built, but OFF until the owner signs off.**
  The owner asked for Google Street View as the pilot fallback. Its terms (§3.2.3(c), example vii)
  forbid using Google Maps content to "train, test, validate or fine-tune" ML models, and §3.2.3(a)
  forbids storing or bulk-downloading imagery (details in `docs/02-floor-height-methods.md`).
  Benchmarking methods on Street View images is "testing / validating", so this is a legal-review
  item, not just a technical fallback. Implementation:
  - The free **metadata** endpoint (pano id, date, location; no quota) may be used in P0 to
    *count* houses Google could cover. Only pano ids are cached.
  - Image fetch and scoring on Google views stay behind a config flag
    (`imagery.google_fallback: false` by default). Turning it on requires the owner's explicit
    confirmation after reviewing the terms; record that decision with its date in
    `docs/03-pilot-results.md`.
  - If enabled: Static images fetched on the fly (heading toward the façade, fov 60–90, ≤ 640 px),
    not stored; every result tagged `provider=google`; nothing Google-derived leaves the pilot or
    feeds a trained model that does.
  - Never use the undocumented `photometa` depth endpoint some research code uses.
- Record for each chosen view: provider, capture date, distance and angle to the façade, whether
  the date is after the answer key's date (stale-risk), and whether the camera height is known.

## 5. Methods to benchmark

The shortlist and its sources are in `docs/02-floor-height-methods.md`. Every method outputs, per
house: FFE estimate (ft NAVD88), FFH estimate, an uncertainty (or none), and a coverage flag with
a reason when it abstains. Trained components train on two areas and test on the third
(leave-one-area-out), plus spatial block CV inside areas.

| ID | Method | Image? | Notes |
|---|---|---|---|
| M0 | Prior only: `ring_p10 +` constant FFH by structure type / era (NSI / HAZUS style) | no | the floor every method must beat |
| M1a | Gradient boosting on non-image features: ring and front ground, street elevation, year built, type, footprint area, flood zone / BFE | no | no answer-key neighbours |
| M1b | M1a + neighbours' answer-key values (spatially held-out blocks) | no | the Florida "neighbour certificates" analogue (docs/00 §5) |
| M2 | Klepac door-scale (BRAILS++ `ffh_predictor_klepac`, BSD-3, public weights) | yes | cheapest image method; works on Mapillary crops |
| M3 | ELEV-VISION-SAM reimplementation: Grounding DINO + SAM 2 door bottom on panoramas; FFE = camera elevation + range·tan(angle); range from the footprint; camera elevation from Mapillary `computed_altitude` or road ground + mount height | yes | same-county state of the art (published 0.19–0.22 m on drone truth) |
| M4 | Footprint ray-cast + metric depth cross-check (Depth Pro, Metric3D v2) | yes | what learned depth adds over footprint geometry |
| M5 | Ning tacheometric (door height + depth) | yes | **research comparison only** (non-commercial code) |
| M6 | Multi-view SfM: Mapillary `sfm_cluster` / `atomic_scale`, SAM 2 door tracking across a sequence, triangulate, align to 3DEP | yes | for occluded single views; heaviest; run on a subsample |
| M7 | Zero-shot VLM: step count × riser height + foundation class | yes | screening fallback when no door bottom is visible |
| MF | Fusion: M1a features + M2–M7 outputs → gradient boosting, kriging gap-fill, conformal intervals; spatially held-out | yes | expected best; reports triage buckets |

Measurement notes for M3–M6: the camera's elevation is the critical input. Mapillary gives
`computed_altitude` but no camera height; measure its error against 3DEP road ground on the pilot
before trusting it, and fall back to road ground + an assumed mount height (report which was used).
Licences: Ultralytics YOLO is AGPL-3.0; Depth Anything V2 Base/Large/Giant and UniDepth are
non-commercial — fine for this internal pilot, flagged for any production choice.

## 6. Evaluation

- Primary target FFE (what is compared with the BFE); secondary FFH.
- Metrics: MAE, RMSE, bias, 90th-percentile absolute error, within 0.5 ft and 1 ft, coverage.
  Paired comparisons on the **same houses** (intersection of coverage) plus each method on its own
  coverage.
- Slices: area, precision tier, structure type, year-built era, foundation look (from imagery
  labels where available), image provider, image age relative to answer key, view distance, stale
  flag, SFHA vs not.
- For SFHA houses: accuracy of the above/below-BFE call; triage bucket sizes and their accuracy at
  a stated confidence; interval coverage (target nominal ±2 points after conformal calibration).
- Cost per 1,000 houses: API calls (Mapillary, Google), VLM tokens, GPU minutes, storage.
- A failure gallery: 30 worst cases per image method with the image, the detected door/ground, and
  the truth.

## 7. Phases and acceptance criteria

| Phase | Work | Done when |
|---|---|---|
| P0 Setup and census | repo scaffold (uv, ruff, mypy), `.env` keys, pull answer key + layer 24 for the 3 areas, Mapillary coverage census, Google **metadata-only** census for the gaps | a table: houses in scoring set per area / with ≥ 1 usable Mapillary view (by image age) / Google-metadata-only / no imagery. **Gate**: report the table to the owner, who decides (a) whether Google image fetch is enabled after reviewing its terms and (b) whether an area with < 20% Mapillary coverage stays in the pilot |
| P1 Data layers | §4.1–4.6 for both lidar epochs | sidecars written; ring ground present for ≥ 95% of matched footprints; a 20-house hand check of footprint matching and door-ground; geoid handling documented with the offset applied |
| P2 Imagery | §4.7 selection and download (or on-the-fly fetch for Google) | per-house view table; ≥ 1 view for the share measured in P0 |
| P3 Non-image methods | M0, M1a, M1b | scored on the scoring set; leave-one-area-out results |
| P4 Image methods | the shortlist from docs/02 | each method scored, with abstention reasons |
| P5 Fusion and report | MF with conformal intervals; stale-truth analysis (LPC if feasible); write `docs/03-pilot-results.md` | ranked table, slices, triage buckets, cost per 1,000, failure gallery, recommendation |

Suggested sampling if imagery cost is a constraint: all scoring-set houses for M0/M1; a stratified
sample of 1,500 houses per area (by precision tier and year-built era) for paid or GPU-heavy image
methods; the full set only for the winners.

## 8. Compute, storage, cost (estimates)

- 1 m DEM: ~0.8 GB per area per project → ~4.8 GB total *(measured tile sizes)*.
- LPC (optional, change detection): ~13–14 GB total *(measured)*.
- Imagery: up to 3 views × ~20 k houses; at ~0.3–0.5 MB per 2048-px image that is ~6–30 GB
  (estimate). Use the stratified sample for heavy methods.
- GPU: one 24 GB-class GPU is enough for detectors, segmentation and metric depth on this volume
  (estimate). VLM calls: price per image from the provider chosen; budget it in P0.

## 9. Risks

1. **Stale truth** (Meyerland especially): raised houses make a correct method look wrong. Mitigated
   by §4.5 and image dating; report both with and without flagged houses.
2. **Answer-key precision** varies by delivery (~1–10 in); Area A is loosest. Tiered scoring.
3. **Door ≠ lowest floor** for split-level, garage-converted or raised houses with ground-level
   entries; the key measures the door base. Report by structure type; do not claim "lowest floor".
4. **Imagery coverage and age** (Mapillary is crowd-sourced, uneven). The Google fallback is very
   likely outside its terms for benchmarking (§4.7): off by default, owner decision required.
4b. **Published accuracies are not comparable** (different truth, metrics, and coverage — e.g.
   ELEV-VISION scored 136 of 483 houses). The pilot reports error *and* coverage for every method on
   the same houses; never quote a method's error without its coverage.
5. **Geoid mismatch** between epochs (GEOID12B vs GEOID18).
6. **Licences**: the HCFCD data carries no explicit licence; confirm before anything leaves the
   pilot. Mapillary is CC BY-SA 4.0 (attribution; share-alike implications for derived data must be
   checked before publication).

## 10. Repository layout (proposed)

```
configs/pilot_areas.yaml          # the three bboxes, CRS, lidar projects
src/spatia_flood/
  truth/        # HCFCD pulls; scorer-only access
  lidar/        # TNM tile lists, download, mosaic, ring stats, change flags
  footprints/   # layer 25 + Overture, truth matching
  streets/      # road centrelines, street elevation at frontage
  context/      # flood zones, year built, structure type
  imagery/      # Mapillary + Google index, view selection, download
  methods/      # m0_rule, m1_tabular, m2_vlm, m3_geometric, m4_depth, ..., fusion
  eval/         # scorer, slices, conformal, report tables
results/        # small CSVs committed
docs/03-pilot-results.md
```

## GIS Expert Review

Pending — to be completed before handoff.
