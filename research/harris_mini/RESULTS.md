# Harris County mini-pilot (2026-10-03): does the Florida result hold?

A quick, non-image check run before the full pilot (`docs/01-plan-harris-pilot.md`), on two of its
three areas. Every number below is from `evaluate.py` (output in `eval_v2_output.txt`) or the
diagnostics noted. **The image step is in its own section at the end**; rows marked
SIMULATED add a noisy copy of the true height, as in the Florida backtest.

## Setup

- **Areas**: B Cypress Creek (-95.580,29.950 → -95.530,29.990; newer slab subdivisions) and
  C Clear Lake (-95.130,29.530 → -95.080,29.570; older, coastal, some raised houses).
- **Answer key**: HCFCD layer 23 Cyclomedia front-door elevations (`Location = 'Front Door'`), SFR
  via layer 24, captured 2018-03 → 2020-01, ft NAVD88 GEOID12B. Headline = `Ht_Precision` ≤ 6
  (read as inches; tiers A+B). Target is the **front-door floor**, not the FEMA lowest floor.
- **Ground**: USGS 3DEP 1 m DEM, project TX_CoastalRegion_2018_A18 (GEOID12B, EPSG:26915), in a
  0.5–2.5 m ring outside the HCAD 2017 footprint (`ground.py`). Coverage: 98.2% (B), 97% (C) of
  front-door houses.
- **Design, copied from Florida**: a random 10% (or 25%) of houses play "has a certificate"; every
  other house is estimated. Neighbour values come only from that pool, never the house itself.
  Models train on pool houses in other 1 km blocks (5 group folds) and are scored on non-pool houses.
  (A first run that took neighbours only from other blocks was discarded: neighbours ended up
  hundreds of metres away and train/test features differed.)

## Results (MAE in ft, precision A+B, 10% certificate pool)

| Method | Florida backtest (floor − BFE) | B Cypress Creek | C Clear Lake |
|---|---|---|---|
| Neighbour median | 1.00 | 0.58 | 0.98 |
| ML, no ground | 0.86 | 0.61 | 1.24 |
| Lidar ground + typical height (no neighbours) | — | 0.40 | 0.95 |
| Lidar ground + neighbours' height | — | 0.34 | 0.83 |
| ML + lidar ground | 0.56 (ground SIMULATED) | **0.27** (real lidar) | **0.76** (real lidar) |
| ML + lidar + image σ 0.72 ft (SIMULATED) | 0.37 | 0.25 | 0.71 |
| within 1 ft, ML + lidar ground | 87% (sim.) | 98% | 90% |

With a 25% pool: B 0.26, C 0.75 (ML + lidar); neighbour median B 0.45, C 0.87.

## What holds and what changed

1. **Lidar ground is the big step, now with real lidar, not a simulation.** Neighbour-only → ML
   + lidar: B 0.58 → 0.27 ft, C 0.98 → 0.76 ft (within 1 ft: C 73% → 90%).
2. **Neighbour-only accuracy matches Florida in the mixed area** (C 0.98 vs FL 1.00) and is better in
   uniform subdivisions (B 0.58).
3. **ML without new information does not help** (no-ground ML is worse than the plain neighbour
   median in both areas), as in Florida. Once ground features exist, ML beats the simple rules
   (B 0.27 vs 0.34), so "the algorithm barely matters" holds only without ground.
4. **The remaining error is raised houses.** Front door > 3 ft above the lowest adjacent grade:
   1.0% of houses in B, 7.8% in C (4.7% > 5 ft). Lidar and neighbours cannot see them; they drive
   C's error and its −0.3 ft bias. That is the job of the image step.
5. **The simulated image reading helps little here** (C 0.76 → 0.71) because each model trains on only
   ~250 local certified houses; the Florida model had ~50 k. A real reading would also be used
   directly (LAG + measured height) for the raised houses, so this is a lower bound.
6. **Ground epoch matters**: the 2024 QL1 DEM (GEOID18) sits a median 0.19 ft below the 2018 one in
   10–30 m rings around the B houses (subsidence plus the geoid change). A product must name the DEM
   epoch and geoid per value.

## Limits

- Two areas, one county, front-door target. Ground epoch 2018 vs truth 2018–2020. No stale-truth
  (raised since capture) screening; no BFE triage yet (needs the FIRM join).
- Pool membership is random; real certificates are not (Florida's are self-selected).

## Reproduce

```
python fetch_hcfcd.py B -95.580 29.950 -95.530 29.990   # and C -95.130 29.530 -95.080 29.570
# download the 1 m DEM tiles listed by the TNM API for each bbox into data/harris_mini/<area>/
python ground.py B ; python ground.py C
python evaluate.py B C
```

## Image step (Mapillary + VLM), 2026-10-03

Every number below is from `eval_image.py B C` (full output in `eval_image_output.txt`) or the
script named next to it. Imagery is Mapillary only; no Google Street View (Bee Maps: addendum at the end).

### Setup

- **Reproduction first.** Data re-fetched (`fetch_hcfcd.py`), 1 m DEM tiles from the TNM API, `ground.py`;
  `evaluate.py B C` output is byte-identical to `eval_v2_output.txt`.
- **Index (`mapillary_index.py`).** Graph API `images`, fields as specified. The endpoint returns a
  *partial* set for large boxes, well under its 2000 cap: one 0.01° tile in C gave 1,839 images and
  the same area in 0.005° tiles 3,205. The index is the union of 0.005° and 0.0025° tilings:
  **C 16,005 images** (7,799 pano), **B 67,226** (13,373 pano). Even so, 30 random 0.002° spot checks in
  C found 410 images of which 330 were indexed, so `mapillary_views.py` also queries a small box
  (footprint + 50 m) around every sampled house; that added 605 (C) and 446 (B) images.
- **Capture years in the index**: C: 2012 7,130 (all pano, Microsoft Streetside imported into
  Mapillary), 2018 5,816, 2020 801, 2024 1,067, 2025 669 pano, others < 250. B: 2012 8,930 pano,
  2018 7,874, 2024 1,674, 2025 1,685, **2026 44,064** (dashcam), others < 1,000.
- **Sample (`mapillary_views.py`).** A seeded random permutation (seed 20261003) of headline houses
  (front door, precision tier A+B, lidar ground): the first 800 (C) / 300 (B) are the **core
  sample** for coverage. Because coverage turned out to be 6–18%, the same random order was
  **extended to all headline houses** (C 2,539, B 5,127) to get enough reads for accuracy — a
  deviation from the brief, still random, never chosen on the answer key.
- **Views.** Camera 8–45 m from the HCAD/lidar footprint, the camera→centroid line crossing no other
  building footprint, house in field of view (perspective: within the half-FOV from Mapillary's
  `camera_parameters` focal, −3°; panorama: rectilinear crop ≥ 70° centred on the bearing). Ranked by
  capture date nearest 2019-07-01, then distance nearest 20 m; up to 2 views per house. Crops in
  `data/` only. Selected: **C 336 views** for 171 houses (264 pano; 187 from 2012, 6 from 2018,
  65 from 2024, 77 from 2025), **B 1,549 views** for 838 houses (611 pano; 79 from 2012, 167 from 2015,
  341 from 2021, 962 from 2026). Images near 2019 barely exist where the houses are.
- **VLM (`vlm_read.py`).** `gemini-2.5-flash` (from `GEMINI_MODEL`), REST, temperature 0, JSON schema
  with the requested fields plus a ≤ 20-word `notes`, `mediaResolution` HIGH (1,290 image tokens vs
  258), thinking budget 1,024. The model sees the crop, the camera type and the camera distance; never
  the answer key. Every response cached in `data/`.
- **Scoring (`eval_image.py`)**: evaluate.py's design, 10% certificate pool (seed 0, per area),
  neighbours from the pool only, GBMs trained on pool houses in other 1 km blocks, scored on sampled
  non-pool houses. Per house, the reading is the highest-confidence view that saw the door and gave a
  height.

### Coverage (share of sampled houses)

| Area | sample | ≥ 1 view in FOV | house visible (VLM) | front door visible | height read |
|---|---|---|---|---|---|
| B core | 300 | 55 (18.3%) | 44 (14.7%) | 11 (3.7%) | 11 (3.7%) |
| C core | 800 | 49 (6.1%) | 49 (6.1%) | 20 (2.5%) | 19 (2.4%) |
| B all headline | 5,127 | 838 (16.3%) | 762 (14.9%) | 226 (4.4%) | 215 (4.2%) |
| C all headline | 2,539 | 171 (6.7%) | 169 (6.7%) | 62 (2.4%) | 61 (2.4%) |

Many in-FOV views show the back or side of the lot from an arterial road (rear fences, sound walls),
so the door faces another street. Raised houses are almost absent from the covered set: of 198 raised
sampled houses in C (front door > 3 ft above LAG), 5 had a visible house; in B 5 of 49.

### Accuracy (MAE ft; scored = sampled, non-pool, precision A+B)

| Method | B all (n 4,591) | B with VLM height (n 188) | C all (n 2,277) | C with VLM height (n 59) |
|---|---|---|---|---|
| G1 lidar LAG + neighbour height | 0.344 | 0.351 | 0.805 | 0.485 |
| GBM + lidar ground (existing) | **0.269** | **0.266** | **0.765** | 0.614 |
| Direct: lidar LAG + VLM height | — (n 188: 1.000) | 1.000 | — (n 59: 1.089) | 1.089 |
| Direct, fallback GBM + lidar | 0.299 | 1.000 | 0.777 | 1.089 |
| GBM + lidar + VLM features (n 442 B / 100 C with any VLM field) | 0.290 | 0.267 | 0.522 | 0.614 |
| GBM + lidar + VLM, fallback GBM + lidar | 0.269 | 0.267 | 0.765 | 0.614 |
| GBM + lidar, take VLM height only if VLM says raised | 0.295 | 0.905 | 0.771 | 0.875 |

Within 1 ft on houses with a VLM height: direct VLM 61% (B), 73% (C); GBM + lidar 97% (B), 93% (C).
Bias of direct VLM: +0.61 ft (B), −0.31 ft (C). The C "all" row of GBM + lidar + VLM features (0.522)
is on a different, easier subset (n 100), not an improvement: on the same houses it equals GBM + lidar.
The image features barely enter the GBM because training rows with a VLM height are 16–27 per fold
in B and 1–2 in C.

**Houses whose true front door is > 3 ft above LAG** (scoring only): B n 41, GBM + lidar 1.62 ft,
none of them had a VLM height; C n 175, GBM + lidar 5.73 ft (G1 4.43), 4 had a VLM height and on
those the direct reading was 5.31 ft off (bias −5.31).

### Raised-house detection (VLM foundation raised or height > 3 ft, vs truth > 3 ft)

| Area | houses visible | true raised among them | TP | FP | FN | precision | recall | recall vs all sampled raised |
|---|---|---|---|---|---|---|---|---|
| B | 762 | 5 | 3 | 281 | 2 | 0.01 | 0.60 | 0.06 (of 49) |
| C | 169 | 5 | 3 | 42 | 2 | 0.07 | 0.60 | 0.02 (of 198) |

The VLM over-calls raised foundations: among visible houses it answered `raised_crawlspace` 455
times in B (slab subdivision, 1.0% raised) and 73 times in C.

### Measured VLM height error vs the simulations

VLM height − (true FFE − LAG), all 276 sampled houses with a height: **MAE 1.03 ft, bias +0.41, SD
1.49, median |e| 0.72, within 1 ft 64%** (B: MAE 1.01, bias +0.60; C: MAE 1.08, bias −0.28). True ≤ 3 ft
(n 271): MAE 0.96, bias +0.50. True > 3 ft (n 5): MAE 4.53, bias −4.53. A normal error with σ 0.72 ft
gives MAE 0.58 / 84% within 1 ft; σ 1.5 gives 1.20 / 49%. **The real reading sits close to the σ 1.5
case, not σ 0.72**, and it is biased high on slab houses and badly low on the few raised ones.
MAE by capture year: 2012 1.02 (n 46), 2021 1.12 (n 105), 2026 0.90 (n 102); panorama 1.07 (n 167),
perspective 0.96 (n 109). (The answer key's `RecordedAt` is present for only 57 of the 276, so image
age vs truth is not reported.)

### Cost

1,891 Gemini calls (all HTTP 200; 10 were prompt tests, 6 of them at the low media resolution and not
used): 3,291,551 prompt tokens, 178,828 output tokens, 1,371,318 thinking tokens (from
`data/harris_mini/vlm_calls.jsonl`). At Gemini 2.5 Flash list prices assumed as $0.30/M input and
$2.50/M output incl. thinking (not measured here), ≈ **$4.86**. Mapillary API: free.

### Ten worst VLM heights (image id, capture date, truth vs read, what went wrong)

| # | Area | Mapillary image | captured | true ft | read ft | what went wrong |
|---|---|---|---|---|---|---|
| 1 | C | 778331683049568 | 2012-02-29 pano | 12.2 | 0.5 | 3-storey condo block ("SFR" in HCFCD); the key's door is an upper unit; model read the ground entry (checked by eye) |
| 2 | C | 186605039984429 | 2012-02-29 pano | 1.0 | 8.0 | 2-storey apartment block; model took a 2nd-floor landing as the door (checked by eye) |
| 3 | C | 965968074208068 | 2012-02-29 pano | 12.7 | 7.2 | condo with external stair; right kind of reading, step count too low (checked by eye) |
| 4 | B | 4276312142474940 | 2021-12-24 pano | 0.6 | 6.0 | dusk image with holiday lights; called an enclosed lower level (checked by eye) |
| 5 | C | 306621509052354 | 2024-05-20 | 1.5 | 5.5 | "5 steps", foundation called raised |
| 6 | B | 118335260699544 | 2021-12-24 pano | 0.8 | 4.5 | small windows taken as crawlspace vents |
| 7 | B | 2456142598236320 | 2026-05-10 | −1.2 | 2.5 | very dark, blurry; door "assumed" (model's note) |
| 8 | B | 702664187372868 | 2021-12-24 pano | 0.5 | 4.0 | night; stone-clad base read as a lower level |
| 9 | B | 1451854850304698 | 2026-06-06 | 0.6 | 4.0 | sloped lot read as raised crawlspace |
| 10 | B | 260276042712595 | 2021-12-24 pano | 0.8 | 4.0 | dark; brick base read as raised foundation |

Systematic issues: multi-unit buildings inside the SFR set; the 2021-12-24 B panorama sequence is
dark (285 of 1,549 B reads mention dark/night; 187 of them from that date) although its
`captured_at` is late morning local time, so those timestamps look wrong; brick skirting and slopes
read as raised foundations.

### Verdict

**No: in this test the Mapillary + VLM reading does not improve on lidar + neighbours, for any group
of houses.**

1. **Coverage is the binding limit**: a front-door height for 2.4% (C) to 4.2% (B) of houses, and
   almost none of the raised houses that carry C's error (5 of 198 raised sampled houses had a visible
   house).
2. **Where it reads, it is worse**: direct LAG + VLM is 1.00 ft MAE vs 0.27 (B) and 1.09 vs 0.61 (C)
   for GBM + lidar on the same houses; adding the reading as features or as a fallback leaves the
   GBM unchanged or worse.
3. **The reading's error is ~σ 1.5 ft, not the 0.72 ft the earlier simulation hoped for**, with a
   +0.5 ft bias on slab houses, and raised-house flags are mostly false (precision 0.01–0.07).
4. What would have to change: imagery from the street the door faces, near the truth epoch (Bee Maps
   tested next, below), a filter for multi-unit buildings, rejecting dark images, and a
   calibration of the VLM height on certified houses before it is used.

**Bee Maps**: tested afterwards at the owner's request; see the next section.

**Attribution.** Values derived from Mapillary imagery (the VLM reads and anything computed from them)
are © Mapillary contributors, CC BY-SA 4.0 (https://www.mapillary.com); any published table using
them must carry the Mapillary logo and link, and is shared alike.

### Reproduce (image step)

```
python mapillary_index.py C -95.130 29.530 -95.080 29.570 ; python mapillary_index.py B -95.580 29.950 -95.530 29.990
python mapillary_views.py C 800 2539 ; python mapillary_views.py B 300 5127   # MAPILLARY_ACCESS_TOKEN
python vlm_read.py C B                                                          # GEMINI_API_KEY; cached
python eval_image.py B C
```

## Bee Maps addendum (owner request, 2026-10-03)

Bee Maps (Hivemapper) imagery: paid, licensed only within our implementation, no redistribution,
Hivemapper owns derivatives. The owner asked for it and paid for it; every row is tagged
`provider=beemaps` (`beemaps_views.parquet`, `beemaps_vlm_reads.parquet`), no image or Bee Maps-derived
value leaves `data/` except the aggregate scores below. Outputs: `eval_beemaps_only_output.txt`,
`eval_mapillary_beemaps_output.txt`.

- **Method (`beemaps_views.py`)**: only for sampled houses with no Mapillary door height, in the same
  random order. A `catalog=true` query (`/latest/poly`, response `cost: 0`) over footprint + 50 m;
  view rules as for Mapillary perspective images (8–45 m, no building in between, centroid within the
  device half-FOV from `/devices` focal − 5° of the GPS heading; forward-mounted camera); the signed URL
  from a ~4 m box around the chosen frame; one frame downloaded per house. Same VLM prompt (v2).
- **Spend (from `data/harris_mini/beemaps/my_spend.jsonl`)**: 7,390 catalog queries, 302 URL queries
  (returning 1,161 frames with signed URLs), **256 images downloaded = $1.28 at $0.005 per image
  view**. The owner's dashboard bills "Image view" per frame; if URL issuance were billed too it would
  be 1,161 × $0.005 = $5.81 — to be confirmed on the dashboard. Before that, two non-catalog test
  queries (no frame downloaded). The API's own `credits`/`balance` counter went negative and
  does not track dollars (owner: ignore it). Gemini: 256 more calls (≈ $0.67 at the assumed list
  prices); 2,147 of the 2,500-call budget used in total (≈ $5.53).
- **Coverage**: of 2,478 C houses tried, 157 got a view (34 more had a qualifying frame the URL query
  did not return); of 4,912 B houses, 99 (12 not returned). Captures are 2025-12 → 2026-08, mostly
  2026-06/07 — 6–8 years after the answer key.

| Bee Maps alone | B (all 5,127) | C (all 2,539) |
|---|---|---|
| ≥ 1 view | 99 (1.9%) | 157 (6.2%) |
| front door visible / height read | 10 (0.2%) | 40 (1.6%) |
| scored houses with a height: direct VLM MAE vs GBM + lidar | 1.47 vs 0.21 (n 9) | 0.78 vs 0.28 (n 38) |
| raised detection precision (TP/FP) | 0.03 (1/29) | 0.02 (1/57) |

| Mapillary + Bee Maps | B | C |
|---|---|---|
| height read, core sample | 12/300 (4.0%; Mapillary alone 3.7%) | 39/800 (4.9%; 2.4%) |
| height read, all sampled | 225 (4.4%; 4.2%) | 101 (4.0%; 2.4%) |
| scored houses with a height: direct VLM vs GBM + lidar | 1.02 vs 0.26 (n 197) | 0.97 vs 0.48 (n 97) |
| all scored houses: GBM + lidar / direct with fallback | 0.269 / 0.302 | 0.765 / 0.785 |
| raised houses with a height | 0 of 41 scored | 4 of 175 scored |

VLM height error on Bee Maps images (n 50): MAE 0.94 ft, bias +0.61, within 1 ft 72% (Mapillary n 276:
1.03, +0.41, 64%); C only (n 40) 0.83 ft. Better than Mapillary in C (front-of-house dashcam frames),
still near the σ 1.5 ft simulation and biased high.

**Verdict unchanged.** Bee Maps adds front-facing, recent frames and nearly doubles the share of C
houses with a reading (2.4% → 4.0%), but still reaches almost no raised houses (1 of 198 sampled in C
got a Bee Maps view of a visible house that is raised), and where it reads, the VLM height is worse
than GBM + lidar + neighbours. For this target (front-door height) and this reader (a general VLM,
no calibration), street imagery does not pay in these two areas.
