# Per-house error bands and what they decide about the BFE (2026-10-06)

Script `bands.py` (output `bands_output.txt`). Point estimate: benchmark.py method E (lidar + point cloud + records +
eave estimate) or F (E with the physical override for flagged houses). Bands: conformal, Mondrian by a label-free
raised flag (record basement / lower level / two-story crawl space, or estimate > 3 ft), from signed out-of-fold
residuals. "Decided" = the 90% band of the floor elevation lies entirely above or below the BFE (SFHA houses with a
BFE). Numbers below: answer key passing the screen; the "all" rows in the output are within 0.01 of them.

**Within an area (calibrated on the other spatial folds of the same area), method E, 90% bands**

| area | coverage all | coverage flagged | width not flagged / flagged | SFHA decided | decided correct |
|---|---|---|---|---|---|
| C Clear Lake | 0.90 | 0.84 | 1.3 / 11.4 ft | 57% | 97% |
| B Cypress Creek | 0.89 | 0.81 | 1.2 / 2.2 ft | 80% | 100% |

Bands are honest within an area; flagged raised houses in Clear Lake get very wide bands (11 ft), and the BFE side
is decided for 57% of SFHA houses there with 97% of those calls right; the rest are "too close to call".

**New area (model and bands from the other area)**: coverage drops to 0.74 (B) and 0.75 (C); for flagged houses in
C the 90% band covers only 51% and decided BFE calls are right only 61%: bands borrowed from an area with few raised
houses are dangerously narrow for raised houses.

**Local calibration sample in the new area** (90% bands recalibrated on k measured local houses, 50 random draws):

| sample | C: coverage all / flagged | C: decided correct | B: coverage all / flagged |
|---|---|---|---|
| 30 random houses | 0.83 / 0.55 | 85% | 0.84 / 0.40 |
| 100 random houses | 0.86 / 0.59 | 85% | 0.87 / 0.38 |
| 30 unflagged + 20 flagged houses | **0.86 / 0.83** | **90%** | **0.84 / 0.81** |

(method E; method F gives the same picture.) Random samples hold too few raised houses, so the flagged group borrows
the narrow residuals of ordinary houses. Choosing 20 of the calibration houses from the flagged list (label-free)
fixes it.

**Product rule.** Ship every estimate with its conformal band. In a new area, calibrate on about 50 measured houses,
20 of them from the raised-flag list; report the BFE side only where the 90% band decides it, otherwise "too close
to call" (and that is where a certificate or a survey pays). Limits: two areas; the C flagged group is one
neighbourhood-heavy sample; 50 draws per setting.
