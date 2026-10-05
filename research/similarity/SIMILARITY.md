# What makes two places' housing 'similar' for floor height? (2026-10-05)

Scripts `similarity_test.py`, `probe_curve.py`; outputs `similarity_output.txt`, `probe_curve_output.txt`.
Data: research/states houses_all (measured living floors); 109 regions = 0.25 deg cells with >= 300 houses
(NC 71, FL 31, VA 3, HAR 2, NYC 2). One model per region, applied to every other region.

## Literature (searched by a sub-agent; citations checked on publisher / arXiv pages unless noted)

No paper defines similarity for floor-height transfer. Adjacent work:
- Hazus Inventory Technical Manual 7.0 (FEMA 2025): foundation mix by Census division (RECS), coastal pre/post-FIRM
  and A/V tables; heights are expert-opinion defaults. Division is too coarse (NC and FL share one).
- NSI 2022 technical documentation (USACE HEC): foundation type from parcels where available, else drawn from Hazus
  tables; height is one constant per type. So NSI height carries almost no regional signal.
- Census Survey of Construction / RECS 2020: foundation shares by division (state-level for RECS 2020).
- HRPDC WR20-01 (2020): random forest on York County VA certificates, 0.83 ft MAE vs 1.25 ft Hazus defaults.
- Raja, Li & Gong (2026, Natural Hazards, doi:10.1007/s11069-026-08095-9): NJ floor-height kriging; coastal elevated
  buildings vary most, attributed to discretionary freeboard.
- Meyer & Pebesma (2021, Methods Ecol Evol, doi:10.1111/2041-210X.13650): area of applicability / dissimilarity index.
- Gretton et al. (2012, JMLR): MMD; Ben-David et al. (2010, Machine Learning): target error = source error +
  input divergence + a term for different labelling of the same inputs ('concept shift'), which input-only measures
  cannot see.
- Bourassa et al. (1999, J Housing Econ): data-driven housing submarkets beat a-priori ones.

## Experiment 1: which measure picks a good donor region? (MAE ft; local model 1.32, best possible donor 1.51,
random donor 3.23, all donors pooled 1.80; donors >= 100 km: oracle 1.56, pooled 2.18)

| measure | Spearman with transfer error | top-1 donor | top-3 pooled | top-1, donors >= 100 km |
|---|---|---|---|---|
| distance (km) | 0.40 | 1.80 | 1.75 | 2.50 |
| same state | 0.43 | 2.12 | 2.17 | 2.49 |
| foundation mix (NSI) | 0.19 | 2.28 | 2.11 | 2.51 |
| building age | -0.04 | 3.16 | 2.50 | 3.26 |
| flood exposure (SFHA, V, BFE - ground) | 0.35 | 2.26 | 2.01 | 2.45 |
| all descriptors | 0.27 | 2.00 | 1.94 | 2.27 |
| MMD (input distributions) | 0.33 | 2.05 | 1.92 | 2.36 |
| area-of-applicability DI | 0.31 | 2.03 | 1.97 | 2.37 |
| **30 measured houses ('probe')** | **0.96** | **1.58** | **1.59** | **1.63** |

Every input-only measure is weak (Spearman 0.2-0.4); for a new area (donors >= 100 km) none beats simply pooling all
donors (2.18 ft). A 30-house probe ranks donors almost perfectly (0.96).

## Experiment 2: how many measured houses does a new region need? (84 targets, donors >= 100 km; MAE ft)

| method | n=5 | 10 | 20 | 30 | 50 | 100 |
|---|---|---|---|---|---|---|
| pooled donors (n = 0) | 2.22 | | | | | |
| pooled + bias from probe | 2.05 | 1.95 | 1.91 | 1.88 | 1.86 | 1.85 |
| probe-picked donor | 1.90 | 1.82 | 1.74 | 1.66 | 1.64 | 1.62 |
| probe-picked donor + bias | 1.92 | 1.79 | 1.70 | 1.64 | 1.62 | 1.61 |
| model on the probe houses only | | 1.87 | 1.75 | 1.67 | 1.58 | 1.51 |
| local model, up to 3,000 houses | 1.32 | | | | | |

By state at n = 30 (probe-picked + bias vs pooled donors vs local): FL 0.64 / 0.69 / 0.54; HAR 0.68 / 2.22 / 0.48;
NC 2.18 / 2.96 / 1.74; NYC 2.10 / 2.96 / 1.97; VA 1.89 / 3.01 / 1.33.

## Reading

- Floor height differs between places mostly in how the SAME inputs map to height (local practice, freeboard,
  housing style), not in the inputs themselves. Input-only similarity (foundation mix, age, flood exposure, MMD,
  area of applicability) cannot see that, as Ben-David's bound predicts.
- The working definition of similarity is therefore empirical: a donor is similar to a place if its model fits a
  small measured sample there. 20-30 measured houses close most of the gap (2.22 -> 1.64-1.70 ft); beyond about 50
  houses, a model on the local houses alone starts to win.
- Product rule: every new region needs a calibration sample of about 30 measured houses (survey, certificates, or a
  public dataset) to pick and correct the donor model; with none, ship the pooled model with a wide error band.
- Not tested yet (from the literature list): soil water table / shrink-swell (SSURGO), climate zone / frost, terrain
  slope, and freeboard ordinances as label-free descriptors. Given these results they are unlikely to replace a probe
  sample, but they may improve the pooled model for regions with none.
