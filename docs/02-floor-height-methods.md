# Floor-height methods: survey and benchmark shortlist (2026-10-03)

Web research for the Harris County pilot. **V** = paper, abstract, repo or official page opened;
**V-abs** = abstract only (publisher blocked); **U** = could not confirm. Re-check anything marked
U before relying on it.

## Read this first: published numbers are not comparable

The methods below report different targets (FFE/LFE elevation vs FFH height above ground), use
different truth (drone photogrammetry, Elevation Certificates, manual labels) and different metrics
(Xia & Gong's "MAE" is a median, in feet). Most report error only on the houses where they produced
an answer: ELEV-VISION answered 136 of 483. **The pilot scores every method on the same HCFCD
houses, on both error and coverage.** That is the point of the pilot.

## Published methods

**What "LFE" means in these papers.** The street-view papers call their output "lowest floor
elevation" (LFE), but they measure the **bottom of the front door**: ELEV-VISION-SAM takes "the
median of the front door bottom elevations", quotes FEMA's definition ("the lowest floor of the
lowest enclosed area, including a basement but excluding enclosures used for parking, building
access, storage, or flood-resistance") and notes its drone truth "align[s] with the LFE definition
used in street view image-based methods, compared to the definition provided in Elevation
Certificates" ([arXiv 2404.12606](https://arxiv.org/html/2404.12606v1), V). That is the same
quantity as the HCFCD answer key (Z at the base of the front door), so the pilot comparison is
like-for-like — and neither is the FEMA lowest floor, which on a house raised over a ground-level
garage or enclosure can be several feet lower. Read every published "LFE" error in this file as a
front-door-floor error.

| Method | Input | Output | Reported error | Test set | Code / weights | Licence |
|---|---|---|---|---|---|---|
| ELEV-VISION (Ho et al., ACM J. Comput. Sustain. Soc. 2(2), 2024) [V](https://arxiv.org/abs/2306.03050) | GSV panorama + depth map; OneFormer finds door bottom and road edge | LFE, height above street | MAE 0.190 m | Meyerland (Harris Co.): 483 houses → 136 with a door found; drone truth | on request | n/a |
| ELEV-VISION-SAM (Ho, Li, Mostafavi; CACAIE 40(1), 2025) [V](https://arxiv.org/html/2404.12606v1) | GSV panorama; Grounding DINO + SAM ViT-H | LFE | MAE 0.22 m; coverage 33% → 56% (229/409) | Meyerland, 409 buildings, drone truth | on request | components Apache-2.0 |
| Li, Ho, Brody, Mostafavi 2026 (arXiv 2604.01153) [V-abs](https://arxiv.org/abs/2604.01153) | ELEV-VISION + ML imputation | LFE + damage | imputation CV R² 0.159–0.974 | 18 Texas areas, 12,241 structures, 49% direct | appendix only | — |
| Ning et al., IJGIS 36(7), 2022 [V-abs](https://pure.psu.edu/en/publications/exploring-the-vertical-dimension-of-street-view-image-based-on-de) | GSV + depth map + DEM; YOLOv5 doors; known door height | LFE | mean error 0.218 m | test area U (repo ships Hampton Roads doors) | [gladcolor/lowest_floor_elevation](https://github.com/gladcolor/lowest_floor_elevation) (2021) | **non-commercial** |
| Gao et al., EPB 2023/24 [V-abs](https://doi.org/10.1177/23998083231175681) | Ning pipeline | FFE + elevation cost | U | Galveston / Jamaica Beach | no | — |
| Klepac et al., J. Comput. Civ. Eng. 40(4), 2026 [V-abs](https://doi.org/10.1061/JCCEE5.CPENG-6883) | any street image; Detectron2 house + door; 80-in door scale | FFH | MAE 0.28 m (FL), 0.31 m (VA) | Elevation Certificates FL/VA | **yes**: `ffh_predictor_klepac` in [BRAILS++](https://github.com/NHERI-SimCenter/BrailsPlusPlus) | **BSD-3** |
| Sorboni, Wang, Najafi, J. Flood Risk Mgmt 2024 [V-abs](https://doi.org/10.1111/jfr3.12975) | GSV; YOLOv5s door / stairs / basement windows | FFH + basement | RMSE 0.81 m (Toronto), 0.95 m (VA) | GTA, Virginia | no | — |
| Chen et al. (Purdue), J. Comput. Civ. Eng. 2022 [V-abs](https://doi.org/10.1061/(ASCE)CP.1943-5487.0001025) | GSV; multi-task CNN | foundation height + type + stories | height MAE 0.177 m; type F1 78% | coastal Louisiana | no | — |
| Reid, McGrath, Jabari, Can. J. Remote Sens. 2025 [V-abs](https://doi.org/10.1080/07038992.2025.2581695) | vehicle video → SfM aligned to airborne lidar; SAM 2 tracks doors | FFH | MAE 0.21 m | Canada | no | open access |
| Xia & Gong, Autom. Constr. 159, 2024 (mobile lidar) [V](https://par.nsf.gov/servlets/purl/10489340) | mobile-lidar intensity image; YOLOv5-L | FFE | median abs. error 0.20–0.27 ft | 3 NJ towns, 145 ECs | no | — |
| Raja, Li, Gong, Nat. Hazards 2026 [V](https://pmc.ncbi.nlm.nih.gov/articles/PMC13053347/) | lidar FFE + foundation strata; kriging gap-fill | imputed FFH | RMSE 0.99–2.53 ft | 3 NJ towns | no | — |
| BRAILS++ `FoundationElevationClassifier`, `FacadeParser` [V] | GSV (FacadeParser needs GSV depth) | raised yes/no; facade metrics | F1 72% | — | yes | BSD-3 |

Oblique aerial imagery: no peer-reviewed FFH method found, only patents (US11555701,
US11532093) — U.

## Off-the-shelf models (licence from the repo or model card) [V]

| Role | Model | Licence | Note for productizing |
|---|---|---|---|
| detector | Ultralytics YOLOv8 / v11 | **AGPL-3.0** | commercial use needs an enterprise licence |
| detector | RT-DETR (lyuwenyu) | Apache-2.0 | |
| open-vocabulary detector | Grounding DINO | Apache-2.0 | prompt "front door", "stairs", "garage door" |
| open-vocabulary detector | OWLv2 (`google/owlv2-large-patch14-ensemble`) | Apache-2.0 | |
| segmentation | SAM, SAM 2 | Apache-2.0 | SAM 3 has a custom "SAM License" |
| segmentation | Mask2Former, OneFormer | code MIT | Mapillary Vistas / Cityscapes weights inherit research-only dataset terms (U) |
| metric depth | Depth Anything V2 | Small Apache-2.0; **Base/Large/Giant CC-BY-NC-4.0** | metric checkpoints: VKITTI (outdoor, 80 m) / Hypersim (indoor) |
| metric depth | Metric3D v2 | BSD-2 | |
| metric depth | UniDepth | **CC BY-NC 4.0** | estimates intrinsics |
| metric depth | ZoeDepth | MIT | |
| metric depth | Apple Depth Pro | Apple sample-code licence | estimates intrinsics; legal review |
| VLM (zero-shot steps / foundation) | any | provider terms | no published FFH benchmark (U) |

For the pilot (internal research) non-commercial weights are acceptable; anything chosen for the
product must have a commercial-compatible licence.

## Commercial options: pricing and limits (owner, 2026-10-03: commercial models are allowed)

Prices checked 2026-10-03 from the vendors' pages; re-check before committing a budget.

### Vision-language models (M7, and as a helper for M2/M3)

| Model | Input / output per 1M tokens | Image cost | Batch | Limits that matter |
|---|---|---|---|---|
| Claude Opus 5.5 (`claude-opus-5-5`) | $4 / $20 | image tokens = ⌈w/28⌉ × ⌈h/28⌉; high-res tier up to 2576 px long edge / 4,784 tokens | 50% off (Message Batches) | ≤ 600 images per request; > 20 images per request → each ≤ 2000 px; 10 MB per image; thinking can't be disabled (use low effort) |
| Claude Sonnet 5.5 (`claude-sonnet-5-5`) | $2 / $10 | same formula, high-res tier | 50% off | as above |
| Claude Haiku 4.5 (`claude-haiku-4-5`) | $1 / $5 | same formula, standard tier (≤ 1568 px / 1,568 tokens) | 50% off | 100 images per request |
| Gemini 3.8 Flash / 3.7 Flash | $0.75 / $3.75 (intro, to 2026-12-31; then $1.50 / $7.50) | Google's page cites a fixed 560 tokens per input image for some models (U for these) | 50% off | — |
| Gemini 3.1 Pro (preview) | $2 / $12 (≤ 200 k prompt) | as above | 50% off | preview |
| OpenAI GPT-5 / GPT-5.5 | $1.25 / $10 and $5 / $30 (third-party summaries; U) | tokenization not verified | — | verify on openai.com before use |

Sources: Claude vision docs (platform.claude.com/docs/en/build-with-claude/vision), Claude model
price table (claude-api skill, cached 2026-09-25), Gemini pricing (ai.google.dev/gemini-api/docs/pricing),
OpenAI figures from third-party pricing summaries (unverified).

**Budget example (estimate, not measured).** ~20 k houses × 2 views = 40 k calls; a façade crop of
1024 × 768 px = 37 × 28 = **1,036 image tokens** (Claude formula) + ~500 prompt tokens in, ~600
tokens out (incl. low-effort thinking):

| Model | Per call | 40 k calls | With batch (−50%) |
|---|---|---|---|
| Claude Opus 5.5 | ≈ $0.018 | ≈ $740 | ≈ $370 |
| Claude Sonnet 5.5 | ≈ $0.009 | ≈ $370 | ≈ $185 |
| Claude Haiku 4.5 | ≈ $0.005 | ≈ $185 | ≈ $92 |
| Gemini 3.8 Flash (intro price, 560-token image assumed) | ≈ $0.003 | ≈ $120 | ≈ $60 |

Output length dominates the Claude cost: keep the answer to a small structured object (step
count, foundation class, door-bottom pixel row, confidence) and measure real token use on 100 houses
in P0 before scaling. Run the pilot sample first (1,500 houses per area) — roughly a quarter of the
figures above.

### Detectors, segmentation, depth

| Option | Licence / price | Limitation |
|---|---|---|
| Ultralytics YOLOv8 / v11 | AGPL-3.0 free; **Enterprise licence by quote** (not published; one community report ~$5 k/yr, U); platform Pro plan $29/seat/month is still AGPL | needed only if we ship YOLO code/weights in a closed product; RT-DETR (Apache-2.0) or Detectron2 (Apache-2.0) avoid it |
| Grounding DINO, OWLv2, SAM / SAM 2, RT-DETR | Apache-2.0, free | SAM 3 has its own licence (litigation-termination clause) |
| BRAILS++ Klepac FFH predictor | BSD-3, free | weights download from Dropbox |
| Depth Anything V2 Base/Large/Giant, UniDepth | CC-BY-NC, **no public commercial licence** | Small (Apache-2.0) is commercial-safe but weaker; or use Metric3D v2 (BSD-2), ZoeDepth (MIT), Depth Pro (Apple licence, legal review) |
| Ning et al. code | non-commercial | research comparison only |

### Imagery

| Source | Price | Limitation |
|---|---|---|
| Mapillary API v4 | free with a token | 60 k entity / 10 k search requests per minute, 50 k tiles per day; CC BY-SA attribution + logo/link on extracted data; crowd-sourced coverage |
| Bee Maps (Hivemapper) Data API | **$0.005 per image**, self-serve ([pricing](https://beemaps.com/pricing)) | forward-facing dashcam frames (façades oblique); terms ([map products](https://beemaps.com/tos/map-products)): use "solely in connection with" our implementation, no redistribution, Hivemapper owns the data and derivatives — owner must accept before use |
| EagleView Imagery API (oblique aerial) | 30-day free trial for a 2 sq mi area ([announcement](https://www.eagleview.com/blog/eagleview/eagleview-launches-an-early-access-free-imagery-api-trial-to-power-the-next-generation-of-geospatial-applications/)); then quote | aerial obliques, not street level; door visibility under eaves/porches untested |
| Cyclomedia Street Smart (imagery + mobile lidar) | quote only ([developer portal](https://developer.cyclomedia.com/)) | the same vendor and capture that produced the Harris answer key — a gold standard, not an independent method; cm-level measurement tools |
| Nexar Streets / CityStream (dashcam) | quote only ([product](https://data.getnexar.com/product/streets/)) | US property images incl. history; licensed datasets |
| Nearmap (aerial + oblique) | enterprise subscription, quote only | aerial, not street |
| Bing Streetside | retired Oct 2025 (enterprise API access only to 2028-06-30) | not an option |
| Apple Look Around | MapKit only; no bulk/derived-data licence found | not an option (U) |
| KartaView, Panoramax (open, CC BY-SA) | free | small US coverage — check in P0 alongside Mapillary |
| ~~Google Street View~~ | — | **not used (owner, 2026-10-03)**: terms forbid testing/validating ML models on it and storing images |

### Compute

One 24 GB-class cloud GPU for detectors, segmentation and depth; a few dollars per hour on common
clouds (estimate — price it in P0). Storage for the pilot is ~25–50 GB (plan §8).

## Benchmark shortlist (cheapest first), mapped to plan IDs

| Plan ID | Method | Why |
|---|---|---|
| M0 | Prior-only: ground + constant FFH by structure type / era (NSI / HAZUS style) | the floor every image method must beat |
| M1a / M1b | Gradient boosting on non-image features; M1b adds neighbours' measured values | what lidar + parcel data alone buy; M1b = the Florida neighbour-certificate analogue |
| M2 | **Klepac door-scale (BRAILS++ `ffh_predictor_klepac`)** | BSD-3, public weights, any image incl. Mapillary crops; cheapest image method |
| M3 | **ELEV-VISION-SAM reimplementation** on Mapillary panoramas: Grounding DINO + SAM 2 door bottom; FFE = camera elevation + range · tan(angle), range from the **footprint**, camera elevation from Mapillary `computed_altitude` or road ground + mount height | same-county state of the art (0.19–0.22 m) |
| M4 | Footprint ray-cast + metric-depth cross-check (Depth Pro, Metric3D v2) at the door-bottom pixel | isolates what learned depth adds over footprint geometry |
| M5 | Ning tacheometric (door height + depth), depth from metric depth or Mapillary SfM | **research comparison only** (non-commercial code) |
| M6 | Multi-view SfM (Reid style): Mapillary `sfm_cluster` + `atomic_scale`, SAM 2 door tracking across a sequence, triangulate, align to 3DEP | strongest where single views are occluded (0.21 m reported) |
| M7 | Zero-shot VLM: step count × riser height + foundation class | cheap recovery when no door bottom is visible; reported as screening |
| MF | Learned fusion: gradient boosting over M1a features + M2–M7 outputs (optionally a Chen-style multi-task net), kriging gap-fill (Raja 2026), conformal intervals, spatially held-out | expected best |

## Imagery: practical and legal notes

### Mapillary [V]

- Every API request needs a token (`Authorization: OAuth …` or `?access_token=`), from
  mapillary.com/dashboard/developers. Limits: 60 k entity / 10 k search requests per minute,
  50 k tiles per day.
- Image URLs: `thumb_256/512/1024/2048_url`, `thumb_original_url` (size from `width`/`height`).
- Geometry: `is_pano`, `camera_type` (perspective / fisheye / equirectangular),
  `camera_parameters` (focal, k1, k2), `computed_rotation`, `computed_compass_angle`,
  `computed_altitude` ("altitude after image processing, from sea level"), `mesh`, `sfm_cluster`,
  `atomic_scale`. **No camera-height field**: derive it as `computed_altitude − 3DEP ground` and
  measure how good that is (U).
- Terms (updated 2024-02-15): other users' content is CC BY-SA (§3b); extracted data must carry
  the Mapillary logo + link (§11); commercial use incl. "training, and development of … datasets"
  is allowed (§12). Whether numeric FFE values are ShareAlike "adapted material" is a legal
  question (U).
- **Coverage in Harris County is unchecked** — the first thing Phase 0 measures.

### Google Street View [V] — not used (owner decision 2026-10-03); kept for the record

- Price (list updated 2026-09-28): Static Street View 10 k free / month, then $7.00 per 1 k (to
  100 k) … $0.53 per 1 k above 5 M. **Metadata is free** (pano id, location, date, copyright,
  status; no camera height, no depth). Max 640×640 px.
- Terms §3.2.3: no pre-fetching / storing / bulk download (a); no "content based on Google Maps
  Content" (c) — example (v) "construct an index of tree locations within a city from Street View
  imagery", and **example (vii) "use Google Maps Content to improve machine learning and artificial
  intelligence models, including to train, test, validate or fine-tune the models."** Only the
  pano id may be cached.
- Benchmarking image methods on Street View is "testing / validating" models on Google content, and
  a per-house FFE table built from it is "content based on" it. **Treat the Google fallback as a
  legal-review item**; the plan keeps it switched off until the owner signs off (see the plan,
  §4.7 and P0 gate).
- GSV depth maps used by ELEV-VISION and BRAILS++ come from an undocumented endpoint outside the
  API; do not use it.

## Other labelled datasets [V]

- **HCFCD Cyclomedia FFE** (Harris County, 1,185,614 points) — the pilot's answer key; verified by
  query and from the layer description (see plan §3). Licence not stated; confirm with HCFCD
  before anything leaves the pilot.
- **NC Risk Building Footprints** (`FFE_TYP`): 6,657 EC, 3,788 traditional survey, 139,816 laser
  inclinometer (high confidence), 9,274 (low), 21,590 terrestrial lidar (high), 5.01 M aerial-lidar
  derived; plus `FOUND_TYPE`, `LIDAR_LAG`, `LIDAR_HAG`. A second test site after the pilot.
- **NYC Building Elevation & Subgrade**: first-floor and grade elevations (NAVD88), measured from
  vendor street imagery and mobile lidar.
- Florida FDEM Elevation Certificates (~206 k with floor numbers) — the neighbour-certificate
  backtest set (docs/00 §5).
