# Plan: Harris County floor-height pilot

Status: **PLAN — GIS review APPROVED WITH CHANGES (2026-10-03); all 15 binding recommendations are
folded in and tagged `[GIS n]`.** Nothing is built. A separate session implements this, phase by
phase, against the acceptance criteria. Facts marked *(measured 2026-10-03)* were checked by query
when the plan was written; re-check before relying on them.

## 1. Goal

Find out, on real houses, **how accurately each available method recovers a house's front-door floor
elevation** (FFE, ft NAVD88) and its height above the ground (FFH), at what coverage and cost, using
Harris County's measured door elevations as the answer key. The output is a ranked benchmark and a
recommendation of which method(s) to build into the product. Not a product, not a published dataset.

Questions the pilot must answer:

1. Accuracy of each method (MAE, within 0.5 / 1 ft, bias, 90th-percentile error) on FFE and FFH.
2. Coverage: the share of houses each method can score (imagery present, door visible, ground
   resolvable), and its accuracy when abstentions fall back to the baseline. `[GIS 15]`
3. Where each method fails: foundation type, setback, porch recess, vegetation, image age,
   houses raised since capture.
4. Whether a fused model with calibrated intervals can triage houses into "front-door floor clearly
   above / clearly below the effective BFE / survey needed", how many land in each bucket, and the
   **false-"above" rate** (the costly error). `[GIS 13]`
5. Cost per 1,000 houses (API calls, model inference, compute; plus the quoted local price of an
   Elevation Certificate for the survey-needed bucket).

Non-goals: building any of this for production; areas outside the three pilot areas; data-sharing
deals (owner decision 2026-10-03); publishing anything derived from Google imagery.

## 2. Pilot areas

Answer-key point counts inside each bounding box *(measured 2026-10-03, HCFCD FeatureServer
layer 23)*.

| Area | Bounding box (lon/lat, CRS84) | Answer-key points | Why |
|---|---|---|---|
| A. Meyerland (inside Houston) | -95.480, 29.670 → -95.440, 29.700 | 7,821 | ELEV-VISION's test area; repeatedly flooded 2015–17; many houses raised or bought out since → tests stale truth. Mostly "Houston Delivery 1", captured Dec 2017–Apr 2018; front-door stated precision ~10 in (loosest). |
| B. Cypress Creek (unincorporated NW) | -95.580, 29.950 → -95.530, 29.990 | 7,740 | Newer suburban stock; "Harris County Delivery 1", captured Nov 2019–Jun 2020; precision ~2–4 in. Subsidence ~1–2 cm/yr nearby (HGSD) — see §4.1. |
| C. Clear Lake (SE, near Galveston Bay) | -95.130, 29.530 → -95.080, 29.570 | 4,825 | Coastal-influenced, mixed raised and slab houses; precision ~1–4 in. |

Structure types in Area A (layer 24): SFR 7,264, MFR 117, COM 95, ZERO 16, AUX ≥ 2,000 (the AUX
count hit the 2,000-row statistics cap) *(measured)*.

## 3. Answer key and context (HCFCD, public ArcGIS FeatureServer)

Service: `https://services7.arcgis.com/NQSCMzARMhPjRo7j/arcgis/rest/services/Structure_Inventory/FeatureServer`
(max 2,000 records per page). Its native spatial reference reports `wkid 103156 / latestWkid 6587`.

**Coordinates `[GIS 1]`.** Read the service's `spatialReference` and confirm whether the native
coordinates and the `X`/`Y` attribute fields are metres (EPSG:6587, NAD83(2011) Texas South
Central) or US survey feet (EPSG:6588 / 2278). Request **`outSR=6344`** (UTM 15N, same NAD83(2011),
no datum operation). If WGS84 output is ever used, treat it as numerically NAD83(2011) and never
apply a NAD83→WGS84 transformation (≈ 1 m shift). Acceptance: round-trip a sample of the `X`/`Y`
attributes through pyproj and agree with the returned geometry to < 1 cm.

| Layer | Use | Key fields |
|---|---|---|
| 23 `Finished_Floor_Elevations (Cyclomedia)` — **the answer key** | FFE truth | `Z` (ft), `Location` (Front Door / Garage Door / Sliding Glass Door / Structure Obstructed / Concrete Slab), `Ht_Precision` (in), `HCAD_NUM`, `RecordedAt`, `Source` (delivery), `X`, `Y` |
| 24 `STRUCTURE_INVENTORY` | year built, structure type | `YearBuilt`, `WWCStrucType` (SFR/MFR/COM/ZERO/AUX), `HCAD_NUM`, `LiDARElev`, `SuggestFFE` |
| 25 `BUILDING_FOOTPRINTS_LiDAR_2018` | footprints (roofline, includes eaves) | polygon |
| 26 `BUILDING_FOOTPRINTS_2017` | HCAD footprints (closer to walls) | polygon |
| 21 / 22 flooded structures (Harvey, flood events) | context only | point |

Answer-key semantics (layer description): one point per structure; `Z` at the **base of the front
door** when visible; else base of the **garage** door; if neither, the **top** of a sliding glass
door. NAVD88 via GNSS + **GEOID12B**. Cyclomedia mobile lidar.

**What the truth is `[GIS 2]`.** The base of a front door is the top of the threshold: a proxy for
the first finished floor (about ±1 in), **not the FEMA "lowest floor"**. For an elevated house with
a ground-level enclosure or garage, the front-door floor sits well above the FEMA lowest floor. The
pilot therefore calls its target the **front-door floor elevation**, and every result and triage
bucket is worded that way. `Ht_Precision` is the provider's stated precision, unvalidated (its σ
level is unknown).

Rules:

- **Scoring set** = `Location = 'Front Door'`, SFR (via `HCAD_NUM` → layer 24), not AUX. Garage-door
  points are scored separately; Sliding Glass Door (top of door), Structure Obstructed and Concrete
  Slab are excluded.
- **Precision tiers**: A ≤ 3 in, B 3–6 in, C > 6 in. **Headline = A+B; tier C is reported
  separately and never in the headline** (in Meyerland its truth error is a large part of any
  method's error). `[GIS 2]`
- **`SuggestFFE` and `LiDARElev` are never features or baselines**: layer 24 says Cyclomedia FFEs
  were incorporated in ~63% of its points.
- **Datum-consistency sentinel `[GIS 4]`.** Before any scoring, per delivery (`Source`) and area:
  median of (garage-door `Z` − lidar ground at the driveway apron). A garage slab normally sits
  ~0.1–0.5 ft above the apron. A median outside that band, or a step between deliveries, is a datum
  bust that must be resolved (or the delivery excluded) first.
- **Stale truth**: houses raised, rebuilt, demolished (Meyerland buyouts) or regraded after
  `RecordedAt` are flagged by §4.5 and the image dates; scored separately, never in the headline.
- The answer key is read only by the scorer (`eval/`). The only exception is method M1b, which uses
  neighbours' answer-key values from **training folds only** (§6).

## 4. Data layers (pilot extent only)

All outputs to `data/` (gitignored) as GeoParquet in OGC:CRS84 plus small CSVs in `results/`. Every
layer writes a sidecar JSON: source URLs, dates, CRS, vertical datum and geoid, units (declare
`/0.3048` international-foot conversion), counts, and match failures.

### 4.1 1 m lidar ground (the only lidar layer built)

Sources *(measured 2026-10-03; TNM API and WESM via spatia-data `us_3dep_lidar_availability`)*:

| Project | Quality | Collected | Geoid | Horizontal CRS | Tiles per area | DEM size per area | LPC size per area |
|---|---|---|---|---|---|---|---|
| `TX_CoastalRegion_2018_A18` (**primary**) | QL2 | 2018-01-13 → 2018-06-11 | GEOID12B | EPSG:6344 | 2 | 0.75–0.83 GB | 1.7–2.6 GB |
| `TX_Houston_B24` (change detection) | QL1 | 2024-02-18 → 2025-01-31 | GEOID18 (one work unit GEOID12B) | EPSG:6344 / 6343 | 2 | 0.75–0.83 GB | 2.3–2.9 GB |

DEM tiles: `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/<project>/TIFF/…`;
list from the TNM products API with the area bbox (datasets `Digital Elevation Model (DEM) 1 meter`
and `Lidar Point Cloud (LPC)`).

**Use the point clouds, not only the DEM `[GIS 3]`.** Near walls and under eaves the 1 m DEM is
TIN-interpolated (QL2 pulse spacing ≤ 0.71 m), so DEM pixels next to a house are often not measured
ground. Ground statistics come from **LPC class-2 (ground) points** with per-house point counts;
DEM pixels are a flagged fallback only.

**Geoid `[GIS 5]`.** The 2018 project (GEOID12B, same as the answer key) is the primary ground.
Convert 2024 values to GEOID12B through the ellipsoid, `H12B = H18 + N18 − N12B`, with the NGS grids
or VDatum, per pixel/point (or per area if the spread across the area is < 5 mm). Read each tile's
geoid from the **work-unit / project metadata** (XML, project report), not the GeoTIFF CRS, which
often carries only the horizontal CRS. Handle the one GEOID12B work unit inside `TX_Houston_B24`.

**Subsidence (disclosure).** Harris-Galveston Subsidence District reports ~1–2 cm/yr near Area B
(Jersey Village), i.e. ~6–12 cm (0.2–0.4 ft) between 2018 and 2024; lower in A, near zero in C.
Read the HGSD 2018–2022 rate map for each area and record it. Houses subside with their ground, so
FFH is unaffected but GNSS-referenced FFE is.

### 4.2 Footprints and matching

HCFCD layer 25 (2018 lidar roofline) as primary; layer 26 (2017 HCAD, closer to walls) and Overture
as cross-checks. Match each answer-key point to a footprint on the same HCAD parcel, nearest within
5 m. Pitfalls `[GIS Q4]`: corner lots, attached garages, detached AUX buildings on the parcel,
townhome/condo accounts sharing a parcel, structures demolished since capture. **Log every failure
and tie; never drop silently.**

### 4.3 Ground around each building `[GIS 3]`

Per footprint, per epoch, from LPC ground points (DEM fallback flagged):

- **Wall line**: erode the roofline footprint inward by an eave allowance of ~0.5 m, or take the
  layer-26 footprint where it agrees; record which.
- **Exclusions**: water and hydro-breakline areas (bayous, Clear Lake waterfront), pool and fence
  voids, any cell with no ground return.
- **Two FFH truths, declared before scoring** (scorer only):
  - `FFH_LAG` = `Z −` a robust low of ground points within 0–2 m of the wall all round (p5–p10) —
    the Elevation-Certificate LAG analogue; **the headline FFH truth**;
  - `FFH_door` = `Z −` the median of ground points within ~3 m of the door, on the wall line.
- **Method-usable ground** (no answer-key input): ring statistics `ring_min / p10 / p50 / p90`
  around the wall line, and `front_ground` on the side facing the frontage street.
- FFE truth = `Z`.

Watch: doors recessed under porches (2–3 m behind the roofline; the ground there may be a slab),
driveways sloping to the street (pull p10 down), fill pads.

### 4.4 Street elevation

Road centrelines (TIGER/Line or spatia-data `tiger_roads_all`). Frontage street: match the HCAD
situs street name to TIGER (not simply the nearest segment — corner lots). Street elevation: LPC
ground along the centreline within ±15 m of the frontage point (min and median); confirm the samples
are pavement (older TIGER can sit metres off; crown vs gutter differs ~0.1–0.2 m).

### 4.5 Change since the answer key (stale-truth flags) `[GIS 6, 7]`

- **Ground change, relative to the neighbourhood**: `Δ_rel = Δring_p50 − median Δ on stable street
  ground within 300–500 m` (removes subsidence, control and project bias). Flag when
  `|Δ_rel| > max(0.15 m, 3 × robust MAD of Δ_rel across the area)`. QL1/QL2 per-pixel differencing
  alone has σ ≈ 14 cm, so a fixed 0.5 ft threshold is not used.
- **Structure change**: a 1 m max-first-return DSM per epoch; roof height = median of the top-k cells
  inside the footprint eroded by 1 m, minus ring ground; flag `|Δ| > 0.5 m` as "structure changed"
  (raise, second storey, rebuild). Plus the footprint IoU of the 2018 footprint vs a 2024 building
  mask (rebuilds, demolitions); exclude houses with no 2024 structure. Never p90 of raw first
  returns (density-dependent, canopy-contaminated).
- Image capture date vs `RecordedAt`. The lidar epochs only bracket it. `[GIS 8]`

### 4.6 Flood context `[GIS 11, 12]`

- FEMA NFHL (spatia-data `fema_flood_zones` Texas partition; FIRM panel + effective date recorded).
  **SFHA membership by footprint any-touch** (the NFIP building rule); where a footprint spans
  several zones/BFEs, use the most hazardous zone and the highest BFE.
- **BFE**: `STATIC_BFE` is typically −9999 in riverine AE zones (much of A and B). There, derive the
  BFE from the S_XS regulatory water-surface elevations at cross-sections (decimal; preferred) or by
  interpolating between S_BFE lines (whole feet) along the flooding source, per FEMA's BFE mapping
  guidance. Record the method per house. Note pending MAAPnext preliminary maps.
- **Datum realization**: Harris County FIRMs use **NAVD88 (2001 adjustment)**; the answer key and
  lidar are GNSS + GEOID12B. In a subsiding area these differ, by up to several tenths of a foot.
  Quantify the offset near each area from NGS datasheets or HCFCD/HGSD marks carrying both heights;
  apply it with a stated uncertainty or widen the survey-needed band by it. Apply the same treatment
  to the answer-key "truth" calls.
- Year built and structure type from layer 24.

### 4.7 Street imagery index

Mapillary first; Google Street View as an owner-gated fallback.

- **Mapillary (API v4, `MAPILLARY_ACCESS_TOKEN`)**: images within 40 m of each footprint; pull
  `computed_geometry`, `computed_compass_angle`, **`computed_rotation`**, `computed_altitude`,
  `camera_parameters`, `camera_type`, `is_pano`, make/model, `captured_at`, `sequence`,
  `sfm_cluster`, `atomic_scale`, image URLs. `[GIS 9]` Choose up to 3 views per house: camera 8–35 m
  from the facing façade, view within ±30° of the bearing to it (panoramas: any heading), preferring
  the date closest to `RecordedAt` and, separately, the newest.
- **Camera position `[GIS 10]`**: `computed_geometry` can be metres off (plus a ~1 m WGS84 vs
  NAD83(2011) bias). Refine each camera position against the street centreline / footprints before
  use.
- **Google fallback (`GOOGLE_MAPS_API_KEY`) — built, OFF until the owner signs off.** Its terms
  (§3.2.3(c), example vii) forbid using Google Maps content to "train, test, validate or fine-tune"
  ML models, and §3.2.3(a) forbids storing or bulk-downloading imagery (see docs/02). Benchmarking on
  Street View is "testing / validating", so this is a legal-review item.
  - The free **metadata** endpoint (pano id, date, location; no quota) may be used in P0 to *count*
    what Google could cover; only pano ids are cached.
  - Image fetch and scoring stay behind `imagery.google_fallback: false`. Enabling it needs the
    owner's explicit confirmation after reviewing the terms, recorded with its date in
    `docs/03-pilot-results.md`.
  - If enabled: Static images on the fly (heading toward the façade, fov 60–90, ≤ 640 px), not
    stored; every result tagged `provider=google`; nothing Google-derived leaves the pilot or feeds a
    model that does.
  - Never use the undocumented `photometa` depth endpoint that some research code uses.

## 5. Methods to benchmark

Shortlist and sources: `docs/02-floor-height-methods.md`. Every method outputs, per house: FFE
(ft NAVD88 GEOID12B), FFH, an uncertainty (or none), and a coverage flag with a reason when it
abstains. **Every image-derived FFE is anchored to the 2018 ground** (answer-key epoch); a 2024
anchor is only a declared variant with the §4.5 alignment applied. `[GIS 8]`

| ID | Method | Image? | Notes |
|---|---|---|---|
| M0 | Prior only: wall-ring ground + constant FFH by structure type / era | no | the floor every method must beat |
| M0b | NSI / Hazus default foundation height + ground | no | what practitioners use today (GIS advisory) |
| M1a | Gradient boosting on non-image features: ring and front ground, street elevation, year built, type, footprint area, flood zone / BFE | no | no answer-key neighbours |
| M1b | M1a + neighbours' answer-key values, training folds only | no | the Florida "neighbour certificates" analogue (docs/00 §5) |
| M2 | Klepac door-scale (BRAILS++ `ffh_predictor_klepac`, BSD-3) | yes | cheapest image method; use an era-conditioned door-height prior or a width-based scale (36 in), not a fixed 80 in (8 ft doors are common in 2000s+ Cypress) |
| M3 | ELEV-VISION-SAM reimplementation (its "LFE" is the front-door bottom, the same quantity as the answer key — not the FEMA lowest floor): Grounding DINO + SAM 2 door bottom; FFE = camera elevation + range · tan(angle); range from the wall line | yes | same-county state of the art (0.19–0.22 m on drone truth) |
| M4 | Footprint ray-cast + metric depth cross-check (Depth Pro, Metric3D v2) | yes | what learned depth adds over footprint geometry |
| M5 | Ning tacheometric (door height + depth) | yes | research comparison only (non-commercial code) |
| M6 | Multi-view SfM: Mapillary `sfm_cluster` / `atomic_scale`, SAM 2 door tracking across a sequence, triangulate | yes | for occluded single views; heaviest; subsample |
| M7 | Zero-shot VLM: step count × riser height + foundation class | yes | screening fallback when no door bottom is visible |
| MF | Fusion: M1a features + M2–M7 outputs → gradient boosting, kriging gap-fill, conformal intervals | yes | expected best; drives the triage |

**Camera elevation for M3–M6 `[GIS 9]`.** Mapillary does not state the reference of
`computed_altitude`, and OpenSfM ignores the EXIF altitude by default — **never use it as an
absolute height**. Primary: register each SfM cluster vertically to the DEM (fit one vertical offset
per cluster from reconstructed road-surface points, scaled to metres, against 3DEP road ground).
Fallback: road ground at the refined camera position + a mount height estimated per sequence
(SfM road-plane height, camera make/model priors, roof-mounted pano rigs). Correct pitch and roll
from `computed_rotation`. Propagate both into the intervals: mount-height error passes 1:1 into FFE;
a 1° pitch error at 20 m is ~0.35 m.

Licences: Ultralytics YOLO is AGPL-3.0; Depth Anything V2 Base/Large/Giant and UniDepth are
non-commercial — fine for this internal pilot, flagged for any production choice.

## 6. Evaluation

- **Primary target FFE** (front-door floor elevation); secondary `FFH_LAG` (headline) and `FFH_door`.
- Metrics: MAE, RMSE, bias, 90th-percentile absolute error, within 0.5 ft and 1 ft, coverage.
- **Abstention bias `[GIS 15]`**: report (a) every method on the paired intersection of houses all
  methods scored, and (b) every method with an M0 fallback where it abstains, over **all SFR
  structures** in the areas (not only answer-key points), so no method buys accuracy by skipping
  hard houses.
- **Spatial validation `[GIS 14]`**: leave-one-area-out, plus blocks no smaller than whole
  subdivisions or ~1 km with a buffer. M1b neighbours and kriging use training folds only. Intervals
  by Mondrian conformal (by area and precision tier), calibrated on spatially held-out folds;
  report coverage per area.
- **Triage `[GIS 12, 13]`**: for SFHA houses (any-touch), "front-door floor above" only if the
  interval's lower bound is above BFE + datum-offset uncertainty; "below" only if the upper bound is
  below it; otherwise "survey needed". Any house whose garage `Z` or visible enclosure sits well
  below the front door goes to survey-needed. Never "compliant". Headline the false-"above" rate.
  Score the answer key's own calls the same way.
- Slices: area, precision tier, structure type, year-built era, foundation look, image provider,
  image age vs answer key, view distance, porch recess, stale flag, SFHA vs not.
- Cost per 1,000 houses: API calls, VLM tokens, GPU minutes, storage; plus a quoted local EC price
  for the survey-needed bucket.
- Failure gallery: the 30 worst cases per image method with image, detected door/ground, truth.

## 7. Phases and acceptance criteria

| Phase | Work | Done when |
|---|---|---|
| P0 Setup and census | repo scaffold (uv, ruff, mypy), `.env` keys, pull answer key + layer 24 (`outSR=6344`, coordinate round-trip check), Mapillary coverage census, Google **metadata-only** census for the gaps | a table: scoring-set houses per area / with ≥ 1 usable Mapillary view (by image age) / Google-metadata-only / no imagery. **Gate**: the owner decides (a) whether Google image fetch is enabled after reviewing its terms and (b) whether an area with < 20% Mapillary coverage stays in |
| P1 Data layers | §4.1–4.6 for both epochs; datum sentinel; geoid and 2001-adjustment offsets measured; subsidence recorded | sidecars written; LPC ground present for ≥ 95% of matched footprints (DEM fallback counted); datum sentinel inside its band for every delivery kept; a 20-house hand check of matching, wall line and door ground |
| P2 Imagery | §4.7 selection, camera refinement, download | per-house view table with camera-elevation method and its error estimate |
| P3 Non-image methods | M0, M0b, M1a, M1b | scored per §6 |
| P4 Image methods | M2–M7 | each scored, with abstention reasons and fallback results |
| P5 Fusion and report | MF with conformal intervals; triage; stale-truth analysis; `docs/03-pilot-results.md` | ranked table, slices, triage buckets with false-"above" rate, cost per 1,000, failure gallery, recommendation |

If imagery cost is a constraint: all scoring-set houses for M0/M1; a stratified sample of 1,500
houses per area (by precision tier and year-built era) for paid or GPU-heavy image methods; the full
set only for the winners.

## 8. Compute, storage, cost (estimates)

- 1 m DEM: ~0.8 GB per area per project → ~4.8 GB *(measured tile sizes)*.
- LPC (now required for ground and change detection): ~13–14 GB across both epochs *(measured)*.
- Imagery: up to 3 views × ~20 k houses at ~0.3–0.5 MB per 2048-px image ≈ 6–30 GB (estimate).
- GPU: one 24 GB-class GPU for detectors, segmentation and depth at this volume (estimate). VLM:
  budget per image in P0.

## 9. Risks

1. **Stale truth** (Meyerland): raised, rebuilt and bought-out houses. Mitigated by §4.5; report
   with and without flagged houses.
2. **Answer-key precision** varies (~1–10 in, stated not validated); tier C kept out of headlines.
3. **Door ≠ FEMA lowest floor**: worded as front-door floor throughout; enclosures and garages
   below the door go to survey-needed.
4. **Imagery coverage and age** (Mapillary is crowd-sourced). Google fallback very likely outside
   its terms for benchmarking: off by default, owner decision.
5. **Vertical reference**: GEOID12B vs GEOID18 (a few cm, measured per area), subsidence between
   epochs (B), and NAVD88 2001-adj vs GEOID12B under the BFE — all measured and disclosed, none
   assumed zero.
6. **Published accuracies are not comparable** (different truth, metrics, coverage — ELEV-VISION
   scored 136 of 483 houses). Never quote an error without its coverage.
7. **Licences**: HCFCD data has no explicit licence (confirm before anything leaves the pilot);
   Mapillary CC BY-SA (attribution; ShareAlike implications for derived values need checking).

## 10. Repository layout (proposed)

```
configs/pilot_areas.yaml          # bboxes, CRS, lidar projects, flags (imagery.google_fallback)
src/spatia_flood/
  truth/        # HCFCD pulls; scorer-only access; datum sentinel
  lidar/        # TNM lists, DEM + LPC download, ground points, rings, DSM, change flags, geoid
  footprints/   # layers 25/26 + Overture, wall line, truth matching
  streets/      # frontage street match, street elevation
  context/      # flood zones, BFE derivation (static / S_XS / S_BFE), datum offset, year built
  imagery/      # Mapillary + Google index, view selection, camera refinement
  methods/      # m0_prior, m0b_nsi, m1_tabular, m2_klepac, m3_elevvision_sam, m4_depth,
                # m5_ning, m6_sfm, m7_vlm, fusion
  eval/         # scorer, paired/fallback tables, spatial CV, conformal, triage, gallery
results/        # small CSVs committed
docs/03-pilot-results.md
```

## GIS Expert Review

- **Consulted**: 2026-10-03, black-box GIS expert, on the draft plan (questions Q1–Q6: truth
  definition and ground reference; geoid, datum and subsidence; camera elevation; matching and
  rings; stale-truth thresholds; other gaps).
- **Verdict: APPROVED WITH CHANGES.**
- **Binding recommendations adopted** (tag → where):
  1 coordinates / `outSR=6344` / no NAD83→WGS84 shift → §3 · 2 truth named "front-door floor",
  tier C out of headline → §3 · 3 LPC ground points, eave allowance, exclusions, two FFH truths →
  §4.1, §4.3 · 4 datum sentinel on garage slabs → §3 · 5 geoid conversion through the ellipsoid,
  geoid from project metadata → §4.1 · 6 neighbourhood-relative ground change → §4.5 · 7 DSM roof
  test, IoU, demolitions → §4.5 · 8 image FFE anchored to 2018 ground; stale by capture dates →
  §4.5, §5 · 9 camera elevation by cluster-to-DEM registration; `computed_rotation`; error
  propagation → §4.7, §5 · 10 camera position refinement → §4.7 · 11 BFE from S_XS / S_BFE where
  static BFE is missing; any-touch; highest BFE → §4.6 · 12 NAVD88 2001-adj vs GEOID12B offset in
  the triage; wording → §4.6, §6 · 13 interval-based triage, false-"above" headline → §1, §6 ·
  14 spatial blocks ≥ 1 km / subdivision, training-fold neighbours, Mondrian conformal → §6 ·
  15 abstention bias tables → §1, §6.
- **Corrections to the draft**: EPSG:6587 is a metre CRS (ftUS is 6588) — confirm the service;
  riverine AE zones usually have no static BFE; a fixed 0.5 ft / 1.0 m change threshold was below
  noise / density-biased.
- **Pitfalls flagged**: porch-recessed doors; corner lots; TIGER centreline offset; ambiguous
  `HCAD_NUM`; 80-inch door prior wrong for 8 ft entries; truth older than imagery in Meyerland;
  unit drift (metres vs ftUS ≈ 8 m horizontally).
- **Advisories (non-blocking)**: NSI/Hazus baseline (added as M0b); quoted local EC price in the
  cost table (added); Mapillary CC BY-SA fine for research, Google gating correct; if productized,
  any image/lidar FFE is SCREENING-grade — only a surveyed EC is a DETERMINATION.
- **Not verified by the expert** (to be measured in P1): GEOID12B−GEOID18 per area, HGSD rates for
  A and C, the 2001-adj vs GEOID12B offset near each area.
