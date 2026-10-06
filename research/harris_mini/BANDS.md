# Per-house error bands and what they decide about the BFE (2026-10-06, corrected after independent review)

Script `bands.py` (output `bands_output.txt`). Point estimate: benchmark.py method E (lidar + point cloud + records +
eave estimate) or F (E with the physical override for flagged houses). Bands: conformal, Mondrian by a label-free
raised flag (record basement / lower level / two-story crawl space, or estimate > 3 ft). "Decided" = the 90% band of
the floor elevation lies entirely above or below the BFE (SFHA houses with a BFE). Numbers: method E, screened key.

**Correction (independent review, 2026-10-06).** The first version of this note used `np.quantile`, which
interpolates between residuals and under-covers on small calibration sets (simulated: 0.82 instead of 0.90 at
n = 20). `bands.py` now uses the finite-sample conformal order statistic (`conf_q`: infinite when the calibration set
is too small, n < 19 at 90%). It also built the "new area" bands from within-area out-of-fold residuals, an easier
regime than a model from elsewhere; they now come from cross-area pseudo-experiments between the training areas. The
earlier claims "30 + 20 local houses give 0.84-0.85 coverage, 90-92% of decided calls right" and "borrowed bands
fail only for raised houses" are withdrawn; the corrected numbers follow.

**Within an area** (cross-conformal, calibration from the other spatial folds; large calibration sets, so the
correction changes little):

| area | coverage all | coverage flagged | median width not flagged / flagged | SFHA decided | decided correct |
|---|---|---|---|---|---|
| A Meyerland | 0.90 | 0.90 | 1.6 / 3.4 ft | 45% | 96% |
| B Cypress Creek | 0.89 | 1.00 (21 houses: band infinite) | 1.2 ft / infinite | 79% | 100% |
| C Clear Lake | 0.91 | 0.91 | 1.3 / 13.1 ft | 56% | 98% |

**New area, model and bands from the other two areas** (pool: model trained on one training area, residuals on the
other, both ways):

| area | coverage all | not flagged | flagged | width not flagged / flagged | SFHA decided | decided correct |
|---|---|---|---|---|---|---|
| A | 0.88 | 0.87 | 0.96 | 1.9 / 13.7 ft | 41% | 91% |
| B | 0.99 | 0.99 | 0.77 | 2.5 / 11.6 ft | 26% | 100% |
| C | 0.84 | 0.86 | **0.66** | 1.7 / 6.0 ft | 61% | **85%** (flagged 63%) |

Borrowed bands are roughly right for ordinary houses (0.86-0.99) and wrong for raised houses in a way that depends on
the area: far too wide where lifts are modest (A), too narrow where they are large (C), where only 63% of the decided
calls on flagged houses are right.

**Local calibration sample in the new area** (model from the other two areas; 90% bands recalibrated on k measured
local houses, label-free choice; mean of 50 draws, scored on the other screened houses):

| sample | A: coverage all / flagged, width not flagged / flagged, decided, correct | B: same | C: same |
|---|---|---|---|
| 30 random | 0.91 / 0.82, 4.0 / 5.2 ft, 16%, 90% | 0.92 / 0.55, 1.8 / 2.2 ft, 60%, 100% | 0.92 / 0.73, 5.0 / 9.5 ft, 44%, 88% |
| 100 random | 0.91 / 0.96, 2.9 ft / inf, 16%, 91% | 0.90 / 0.40, 1.4 / 1.4 ft, 73%, 100% | 0.90 / 0.63, 2.1 ft / inf, 60%, 86% |
| 30 unflagged + 20 flagged (B: 17) | **0.93 / 0.90**, 4.6 / 7.2 ft, 11%, 89% | **0.94 / 1.00**, 1.9 ft / inf, 58%, 100% | **0.94 / 0.91**, 6.4 / 14.6 ft, 31%, 92% |
| 30 unflagged + 60 flagged | 0.93 / 0.90, 4.4 / 6.0 ft, 12%, 89% | (34 flagged houses only) | 0.94 / 0.90, 6.0 / 13.0 ft, 32%, 91% |

(Widths are medians; "inf" = more than half of those bands infinite, i.e. too few calibration houses in the group.)
With the correct quantile, 50 local houses give honest 90% bands, but a 90% band from 30 calibration houses is set
by their largest residuals, so bands are wide and few houses are decided (11-58% of SFHA houses). Random samples
mostly leave the flagged group under-covered (0.40-0.82; A with 100 random: 0.96). More flagged houses (60) narrow the flagged bands only modestly (A 7.2 -> 6.0 ft, C 14.6 -> 13.0 ft); more
unflagged houses (100 random) narrow the unflagged bands (A 4.6 -> 2.9 ft, C 6.4 -> 2.1 ft). The pre-registered
design test (`eval_design.py`, cross-fitted bands from the chosen 50-house design in C) agrees: coverage 0.96,
unflagged width 4.6 ft, flagged bands mostly infinite, 38% decided, 96% of decided calls right.

**Product rule.** Ship every estimate with its conformal band and say how it was calibrated. In a new area:
ordinary houses can carry bands borrowed from other areas (coverage 0.86-0.99 here) until local labels exist; flagged
(likely raised) houses get "too close to call" on the BFE until enough local labels on flagged houses exist; a
local sample of ~50 gives honest but wide bands, and narrow honest bands need on the order of 100+ local labels per
group. Limits: three areas in one county; B has 34 flagged houses and 111 SFHA houses; 50 draws per setting.
