# Per-house error bands and what they decide about the BFE (2026-10-06; area A added)

Script `bands.py` (output `bands_output.txt`). Point estimate: benchmark.py method E (lidar + point cloud + records +
eave estimate) or F (E with the physical override for flagged houses). Bands: conformal, Mondrian by a label-free
raised flag (record basement / lower level / two-story crawl space, or estimate > 3 ft), from signed out-of-fold
residuals. "Decided" = the 90% band of the floor elevation lies entirely above or below the BFE (SFHA houses with a
BFE). Numbers below: answer key passing the screen; the "all" rows in the output are within 0.01 of them.

**Within an area (calibrated on the other spatial folds of the same area), method E, 90% bands**

| area | coverage all | coverage flagged | width not flagged / flagged | SFHA decided | decided correct |
|---|---|---|---|---|---|
| A Meyerland | 0.90 | 0.89 | 1.6 / 3.5 ft | 45% | 96% |
| B Cypress Creek | 0.89 | 0.81 | 1.2 / 2.2 ft | 80% | 100% |
| C Clear Lake | 0.90 | 0.84 | 1.3 / 11.4 ft | 57% | 97% |

Bands are honest within an area; flagged raised houses in Clear Lake get very wide bands (11 ft), and the BFE side
is decided for 57% of SFHA houses there with 97% of those calls right; the rest are "too close to call".

Meyerland (A) is almost all SFHA (2,995 of 3,329 screened houses) and its floors sit close to the BFE, so only 45%
are decided even with 1.6 ft bands.

**New area (model and bands from the other two areas pooled)**: 90% coverage 0.80 (A), 0.89 (B), 0.79 (C). The
flagged group is where it breaks, in both directions: C's flagged houses get bands from A+B whose raised houses are
modest, so the band covers only 53% and decided BFE calls are right only 61%; A's flagged houses get C's very wide
raised-house residuals (12.5 ft bands, coverage 0.99, nothing decided). Borrowed bands are wrong for raised houses.
(The first version of this table, with only B and C, gave 0.74 / 0.75 overall.)

**Local calibration sample in the new area** (90% bands recalibrated on k measured local houses, 50 random draws):

| sample | A: coverage all / flagged | A: decided correct | B: coverage all / flagged | C: coverage all / flagged | C: decided correct |
|---|---|---|---|---|---|
| 30 random houses | 0.81 / 0.61 | 89% | 0.84 / 0.39 | 0.83 / 0.50 | 85% |
| 100 random houses | 0.86 / 0.76 | 90% | 0.88 / 0.39 | 0.85 / 0.54 | 86% |
| 30 unflagged + 20 flagged houses | **0.85 / 0.84** | **90%** | **0.85 / 0.81** | **0.84 / 0.81** | **92%** |

(method E, model trained on the other two areas; method F gives the same picture: 30 + 20 gives coverage 0.85 / 0.82
(A), 0.85 / 0.77 (B), 0.84 / 0.82 (C).) Random samples hold too few raised houses, so the flagged group borrows
the narrow residuals of ordinary houses. Choosing 20 of the calibration houses from the flagged list (label-free)
fixes it.

**Product rule.** Ship every estimate with its conformal band. In a new area, calibrate on about 50 measured houses,
20 of them from the raised-flag list; report the BFE side only where the 90% band decides it, otherwise "too close
to call" (and that is where a certificate or a survey pays). Limits: three areas; 30 + 20 still under-covers the
nominal 90% by about 0.05; the C flagged group is one neighbourhood-heavy sample; 50 draws per setting.
