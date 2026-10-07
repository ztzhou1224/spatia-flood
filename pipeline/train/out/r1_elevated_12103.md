# Pinellas (12103) r1 candidate: bands for elevated houses the model does not flag

Date: 2026-10-07. Work approved by the owner on 2026-10-07. Not a release: the candidate is in `data/flood_v1/train_r1/`, and r0
in `data/flood_v1/train/` is untouched (sha256 prefixes unchanged before and after: model 64888472707bc972,
difficulty ff050c5a820d4075, bands 3c5348599f43d415).

The numbers below come from one command:

```
OMP_NUM_THREADS=1 .venv/bin/python pipeline/train/train_r1.py 12103 pinellas_2018 --county --save 'D2 raised90-elevq'
```

The table it writes is `pipeline/train/out/r1_elevated_12103.txt`, and its full stdout (disk re-check, gate rules,
per-group table) is `pipeline/train/out/r1_save_12103.log`. Where another file is the source, it is named.

## 1. The 0.79 figure, reproduced

The 0.79 is the "coverage not flagged" cell of the `elevated / enclosed 5-9` row in `train_12103.txt`. That means TEST
houses with certificate diagram 5-9 and point estimate p <= 3 ft. The subgroup has **n = 119, of which 94 are
covered: 0.790** (Wilson 95% CI 0.708-0.853). The r0 row of the table gives the same value, recomputed from the saved
r0 artefacts.

The brief also offers "or label dh > 3 ft". Under that definition the figure is much worse: **0.543 on n = 70**
(raised-unflagged, r0 row). Both are scored below. The primary target is the diagram 5-9 figure the handoff quotes.

Everything is held fixed except the bands: the split (fit 4,277 / cal 1,595 / test 1,315), the label screen and the
point model. The recomputed final model matches the saved r0 model on TEST with max |diff| = 0.00e+00 ft. As a
result, MAE and BFE side are identical in every option.

## 2. Options (no label at prediction time; calibration on CAL only)

These were defined before any TEST score:

- **A1:** difficulty model with the quantile objective (alpha 0.9).
- **A2:** difficulty model with the raised-classifier score as an extra input.
- **B1:** Mondrian q by flag.
- **B2:** Mondrian q by flag x year built <= 1950.
- **C1:** Mondrian q by flag x raised-classifier score >= t75.
- **C2:** C1 with an asymmetric band.

About the raised classifier:
- It is a LightGBM binary model fit on FIT only.
- Its inputs are FEATS + p.
- Its training target is diagram 5-9 or dh > 3, used as the target only.
- Its out-of-fold AUC among FIT's unflagged houses is 0.890.

C1 reached only 0.832, so the next options were **added after C1/C2 had been scored on TEST**:

- **C3:** 4 score bins.
- **C4:** threshold t90, where the high-score group holds 90% of FIT's unflagged elevated houses (t90 = 0.0703).
- **D1/D2/D3:** C1/C4/C3, but in the high-score group(s) q = max(group q, 90% quantile of |z| over that group's
  elevated CAL houses).

In the D options the diagram is read only at calibration on CAL. The band at prediction depends only on x and p.
Because the D options were chosen after looking at TEST, a TEST-free check is reported for every option: **CAL-CV**,
with q fitted on 4/5 of CAL blocks and scored on the other 1/5.

## 3. Results (TEST, n = 1,315; MAE 1.039 and BFE side 0.898 for all options)

| option | coverage | cov. flagged / not | width med. not flagged / flagged | BFE decided | decided correct | **elev-unfl cov.** (n 119) | 95% CI | raised-unfl cov. (n 70) | CAL-CV cov. / elev-unfl | county width med. not flagged |
|---|---|---|---|---|---|---|---|---|---|---|
| r0 | 0.918 | 0.938 / 0.912 | 1.776 / 15.376 | 0.579 | 0.983 | **0.790** | 0.708-0.853 | 0.543 | 0.900 / 0.652 | 1.915 |
| A1 s-q90 | 0.909 | 0.921 / 0.905 | 1.747 / 13.500 | 0.570 | 0.982 | 0.782 | 0.699-0.846 | 0.514 | 0.900 / 0.679 | 1.916 |
| A2 s+raised | 0.908 | 0.938 / 0.899 | 1.756 / 14.427 | 0.583 | 0.986 | 0.748 | 0.663-0.817 | 0.486 | 0.899 / 0.696 | 1.912 |
| B1 flag | 0.916 | 0.921 / 0.914 | 1.845 / 13.971 | 0.574 | 0.984 | 0.798 | 0.717-0.861 | 0.543 | 0.903 / 0.661 | 1.990 |
| B2 era | 0.916 | 0.921 / 0.915 | 1.827 / 13.971 | 0.575 | 0.984 | 0.807 | 0.727-0.868 | 0.557 | 0.901 / 0.679 | 1.975 |
| C1 raised | 0.920 | 0.921 / 0.920 | 1.815 / 13.971 | 0.567 | 0.982 | 0.832 | 0.755-0.888 | 0.600 | 0.900 / 0.741 | 1.989 |
| C2 raised-asym | 0.915 | 0.921 / 0.913 | 1.824 / 13.971 | 0.557 | 0.982 | 0.815 | 0.736-0.875 | 0.629 | 0.898 / 0.759 | 2.009 |
| C3 raised-bins | 0.919 | 0.921 / 0.919 | 1.901 / 13.971 | 0.555 | 0.985 | 0.840 | 0.764-0.895 | 0.600 | 0.903 / 0.750 | 2.129 |
| C4 raised90 | 0.922 | 0.921 / 0.922 | 1.880 / 13.971 | 0.556 | 0.985 | 0.840 | 0.764-0.895 | 0.600 | 0.902 / 0.750 | 2.110 |
| D1 raised-elevq | 0.923 | 0.921 / 0.924 | 1.829 / 13.971 | 0.547 | 0.982 | 0.840 | 0.764-0.895 | 0.629 | 0.906 / 0.786 | 2.025 |
| **D2 raised90-elevq** | **0.933** | 0.921 / 0.937 | **2.015** / 13.971 | **0.486** | 0.985 | **0.908** | 0.842-0.948 | 0.743 | 0.915 / **0.830** | **2.682** |
| D3 bins-elevq | 0.925 | 0.921 / 0.926 | 1.929 / 13.971 | 0.533 | 0.984 | 0.874 | 0.802-0.922 | 0.671 | 0.908 / 0.795 | 2.194 |

"County" covers 247,653 residential houses: lidar ok, lidar LAG present, DOR 000-009, with no labels. This
approximates assemble.py's modeled population, which is 240,305 in `assemble_12103.json`. As a check, r0's county
median band for all houses is 2.148 ft against assemble's recorded `modeled_band_width_median_ft` of 2.15.

D2's groups on TEST:
- **possibly_raised:** 408 of the 1,010 unflagged houses, coverage 0.978, median width 7.03 ft. It holds 109 of the
  119 elevated-unflagged houses, and 106 of them are covered.
- **low-score unflagged:** 602 houses, median width 1.48 ft. It holds the other 10 elevated houses, of which 2 are
  covered.
- **flagged:** 305 houses.

## 4. Choice and rationale

Most options give little:
- A better difficulty model (A1, A2) does not help (0.75-0.78).
- Plain Mondrian groups (B, C) reach at most 0.84, because the possibly-raised group mixes many ordinary houses. Its
  90% group q is then set by those ordinary houses.

Only setting that group's q from its elevated CAL houses (D) moves the subgroup substantially.

**D2 is the only option that meets the brief's criteria on TEST.** It is saved as the r1 candidate:
- Elevated-unflagged coverage is 0.908.
- Overall coverage is 0.933, which is at least 0.90.
- The median unflagged width rises by 0.239 ft (1.776 to 2.015), which is at most 0.3.
- MAE and BFE side are unchanged.
- Decided correct is 0.985 against 0.983.
- Every gate.py rule passes when applied to the saved artefacts.

**Contradictions to the brief and caveats; the owner needs to decide before any release:**

1. **The width criterion holds on TEST but not on the county.** On the county, D2 puts **95,836 of 247,653 houses
   (38.7%)** in the wide group. The median unflagged band goes from **1.915 to 2.682 ft (+0.77 ft)**, and the median
   for all houses from 2.148 to 3.732 ft. On TEST, the share of SFHA houses with a decided BFE side falls from
   **0.579 to 0.486**. The certificate sample is not representative of the county's unflagged houses, because the
   county has more old houses with high scores.
2. **The D options were designed after seeing TEST** (12 options scored), and the subgroup is small (n = 119). The
   TEST-free CAL-CV estimate for D2 is **0.830**, against 0.908 on TEST. Expect the true coverage somewhere between,
   below 0.90.
3. **D3 is the balanced alternative.**
   - Elevated-unflagged coverage is 0.874 on TEST (CAL-CV 0.795).
   - The median unflagged width rises by 0.153 ft on TEST and by **0.279 ft on the county**.
   - BFE decided is 0.533.
   - It meets the 0.3 ft criterion on both populations but falls short of 0.90.

   `--save` does not yet support D3's bins format.

**Recommendation:** do not release D2 as is. If coverage of the elevated-unflagged houses matters more than the
decided share, take D2 and accept the cost in item 1. Otherwise take D3. The lasting fix is more elevated labels
(handoff §7.3: Pinellas county EC layer, 19,382 records), which would also make the CAL estimate of the group's q less
noisy (112 elevated-unflagged CAL houses now: 105 in possibly_raised plus 7 in unflagged, per `bands_12103.json`).

## 5. Artefacts and the format change

`data/flood_v1/train_r1/` contains:
- `model_12103.txt` and `difficulty_12103.txt`: byte-identical to r0.
- `raised_12103.txt`: the classifier.
- `bands_12103.json`: holds `test_blocks`, `features` and the split sizes.

In `bands_12103.json`, **`q` is null on purpose**, so that a single-q reader fails. The new `groups` object holds:
- `doc`, `threshold` (0.0703) and `flag_ft` (3).
- `q_lo` / `q_hi` per group: unflagged 2.232, possibly_raised 5.611, flagged 2.114.
- `n_cal` per group (640 / 413 / 542) and `n_cal_elevated`.
- `elevated_q_groups` and `classifier`.

The reference reader is `disk_bands()` in `pipeline/train/train_r1.py`.

**gate.py cannot score r1 as it is.** Running
`gate.py 12103 pinellas_2018 --candidate data/flood_v1/train_r1 --baseline data/flood_v1/train --release pinellas-r1`
stops with `TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'` in `scored()`, and no gate JSON is
written. The gate rules were applied with `disk_bands` instead (log above), and all of them pass.

## 6. Changes needed in gate.py and assemble.py (not made here)

**gate.py**
- `scored()`: replace the single-q band with group-aware bands. Either
  `from train_r1 import disk_bands` and `p, lo, hi, _ = disk_bands(d, fips, t)`, or inline the same logic:
  1. If `bands.get("groups")` is set, load `d / groups["classifier"]["file"]`.
  2. `r = clf.predict(t[FEATS].assign(p=p))`.
  3. Group = `flagged` if `p > flag_ft`, `possibly_raised` if `r >= threshold`, otherwise `unflagged`.
  4. `lo = p - q_lo[group] * s`, `hi = p + q_hi[group] * s`.
  5. Otherwise use `bands["q"]` as now.
- Optionally record per-group q in the gate JSON.

**assemble.py**
- Lines 386-398: load `raised_<FIPS>.txt` when `groups` is present, and give `predict()` the same group logic.
- Line 392: add `raised_<FIPS>.txt` to the version hash.
- Line 410: `gate_recheck["q"]` must take the per-group q (`q` is null).
- It reads `DATA / "train"` hard-coded. Either publish r1 into that directory (and R2 `_flood/train/12103/`) after
  sign-off, or add a train-dir option.
- Optional schema change, which needs the owner (docs/06): a column saying which band group a modeled house is in,
  so a 7 ft band can be explained as "possibly raised".
