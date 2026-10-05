# Image pipeline audit: frames per house, processing, house matching, reader model (2026-10-05)

Owner's four questions about the Mapillary + Bee Maps image step. Bee Maps was audited on its frames (Clear Lake,
`beemaps_multi.py` run of today: 43 frames of 21 houses); Mapillary only from its code, because its images and token
are not in this container. Scripts: `audit_beemaps.py C` (projection overlays, `data/.../beemaps_audit/`),
`beemaps_rectify.py C` (rectified views), `vlm_multi.py C beemaps_rect.parquet <tag>` with three models,
`eval_multi.py C <tag>`. Every number below is from those runs. Images and reads stay in `data/` (provider=beemaps).

## 1. Enough images per house?

No, and more frames per house cannot fix it. Any Bee Maps frame within 60 m: 11% of the 317 triage houses (33% of
random controls); a usable frame (8-45 m, unobstructed, house in the camera's field of view): 2.2% / 9.3%. Houses
seen had a median of 2 frames (max 4), all 20-44 m away and 20-41 deg off the driving direction, i.e. at the edge of
a wide-angle dashcam where the door is a few dozen pixels. None of the 164 raised triage houses was seen.
Mapillary (code + earlier outputs in RESULTS.md / M3.md): at most 2 views per house (`MAXV = 2`), 6-18% coverage.

## 2. Were the images processed correctly?

**Bee Maps: no.** `beemaps_multi.py` (and the earlier `beemaps_views.py`) centred the crop with a pinhole formula and
the GPS heading. The Bee camera has strong lens distortion (OpenCV rational + thin-prism + tilt model, k1 2.55, from
`/devices`) and each frame carries its own camera yaw (-7 to +9 deg vs the GPS heading) and pitch / roll. Projecting
the target footprint with the real camera model puts it a median 103 px (up to 266 px) away from the crop centre on a
2,028 px frame: at 30-40 m that is often the neighbouring house. Crops also kept the hood and dashboard.
Fix (`beemaps_rectify.py`): every frame re-rendered as a level, undistorted virtual view aimed at the footprint
centroid, field of view fitted to the footprint. Checked by eye on the overlays and views: the target is centred and
straight. Remaining issue: some frames report pitch 0 with no roll (missing values) although the camera is tilted
(e.g. 1062555: horizon far below the image centre), so those views stay tilted; estimating roll from the image would
be needed.
**Mapillary (code review):** the VLM path uses `computed_compass_angle` (structure-from-motion corrected, better than
a GPS heading) but the same pinhole column crop, ignoring Mapillary's `camera_parameters` k1 / k2; panoramas are
re-projected correctly. The M3 geometric path renders a level virtual view from `computed_rotation` with k1 / k2 and
is correct.

## 3. Are the images matched to the right property?

Mostly yes in geometry, not in what the reader was told. Frame selection uses the HCAD footprint, distance, field of
view and a line-of-sight test against other footprints, and the projection overlays show the target footprint on the
expected building. But the reader was told "the house in the centre" of a crop that was not centred on it (see 2), so
for some frames it read the neighbour (1080885: crop centred between the target and a two-story neighbour).
Attached units (townhouse rows: 1079355 and 1079366 share the same two frames) cannot be told apart from the street;
those reads describe the row, not the unit. The rectified views fix the centring; an explicit marker of the target's
extent would be the next step.

## 4. Is the reader model good enough?

Same rectified views, three Gemini models (answer key = scorer only; none of these houses is raised):

| model | houses called raised (all wrong) | stories agree with the appraisal record | door height MAE (houses) | lidar + records model on the same houses |
|---|---|---|---|---|
| original crops, gemini-2.5-flash | 10 of 21 | 71% (21) | 1.10 ft (15) | 0.24 ft |
| gemini-2.5-flash | 10 | 74% (19) | 1.26 ft (10) | 0.19 ft |
| gemini-2.5-pro | 4 | 85% (20) | 1.15 ft (10) | 0.30 ft |
| gemini-3.1-pro-preview | 0 | 94% (18) | 0.82 ft (7) | 0.30 ft |

- gemini-2.5-flash (used for every image result so far, Mapillary included) is not good enough: it calls half of the
  plain slab houses raised and miscounts stories a quarter of the time. gemini-3.1-pro-preview makes no false raised
  call and matches the records' story count 94% of the time; it also declines more often when the door is hidden.
- On these ordinary houses no model beats the lidar + records model (0.2-0.3 ft). Whether the better model reads RAISED
  houses well cannot be tested here: no raised house has a usable frame. Samples are tiny (7-21 houses).
- Earlier image results (RESULTS.md, M3.md VLM rows, the Bee Maps addendum) used flash and the uncorrected crops, so
  they understate what images can give; the M3 geometric numbers are unaffected.

## What to change before more imagery is bought

1. Rectified, target-centred views (done for Bee Maps; apply the same to Mapillary perspective images with k1 / k2).
2. Reader: gemini-3.1-pro-preview (or 2.5-pro), not flash.
3. Mark the target's extent in the view, and skip attached units or label them as a row.
4. Coverage is the real limit for raised houses: test on an area where they are on driven streets, or use a
   different source (research/coverage/IMAGERY_SOURCES.md).
