# NYC street images: stairs, door and windows as a ruler for a floor-height range (2026-10-04)

Scripts: `nyc_views.py` (Mapillary views), `nyc_detect.py` (Grounding DINO tiny: front door, stairs, window,
garage door, house), `nyc_eval.py` (rules + scoring); output `nyc_eval_output.txt`.
Answer key (scorer only): BES first floor minus BES grade, Staten Island east shore, 6,190 houses.

Method: in a level view aimed at the house, the front door is the ruler (80 in). Height above ground =
(bottom of the stairs leading to the door, else bottom of the house box - door bottom) / door height x 6.67 ft.
A garage door or windows below the front-door bottom are taken as evidence of a raised floor.
v1 rules were fixed before scoring. v2 was revised after looking at 9 drawn views (snowbanks and road
detected as 'stairs', garage-level doors picked on raised houses): plausible stairs only, highest door
with stairs, no upper-floor doors.

Coverage: Mapillary has 9,627 images in the area (2015-2022; the 2022 panoramas were shot in snow).
467 houses (7.5%) have a usable view; 313-328 (5.1-5.3%) get a ruler estimate.

| houses with a ruler estimate | v1 | v2 | national NSI (same houses) |
|---|---|---|---|
| floor height MAE (ft) | 2.66 | 2.41 | 2.40 / 2.33 |
| within 1 ft | 27% | 31% | 23% |
| band right (0-2 / 2-4 / 4-8 / 8+ ft) | 34% | 35% | 14% |
| raised (> 6 ft): recall / precision | 35% / 26% | 21% / 29% | 0% / - |
| floor elevation MAE with lidar ground (ft) | 2.62 | 2.24 | 1.89 / 1.85 |

Range: the fixed range rule (+-25%) held the truth for 46% of houses. A range calibrated on half the houses
(even BIN) and tested on the other half reaches 80% (v1) / 74% (v2) with a median width of 5.4-5.5 ft; the same
calibration around the national NSI height gives 71-72% with a 5.3-5.7 ft width. So the image range is not
narrower than a range around the national default.

Reading: zero-shot detection of stairs and doors in these images is too noisy to measure floor height, even as
a range: stairs are confused with snowbanks and pavement, doors at garage level are picked, and the camera often
sees the house obliquely or behind cars and trees. It only beats the national default at saying which band a
house is in (35% vs 14%), and it covers 5% of houses. Images are not the fix for NYC raised houses with
today's open imagery and a zero-shot detector.
