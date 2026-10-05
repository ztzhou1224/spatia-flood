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

**Correction (2026-10-05, later the same day).** Experiments 1 and 2 were rerun after fixing the NC flood inputs in
houses_all (coded zone / yes-no flag read as BFE; see research/states/STATES.md). The tables below are the rerun;
first-run values are in the git history. The conclusions hold; the input-only flood and area-of-applicability measures
got weaker. Experiment 3 still shows the FIRST-RUN numbers: its region context needs Open-Meteo, whose daily request
limit was exhausted on 2026-10-05, so it awaits a rerun.

## Experiment 1: which measure picks a good donor region? (MAE ft; local model 1.33, best possible donor 1.52,
random donor 3.23, all donors pooled 1.96; donors >= 100 km: oracle 1.57, pooled 2.22)

| measure | Spearman with transfer error | top-1 donor | top-3 pooled | top-1, donors >= 100 km |
|---|---|---|---|---|
| distance (km) | 0.42 | 1.83 | 1.79 | 2.48 |
| same state | 0.46 | 2.15 | 2.23 | 2.49 |
| foundation mix (NSI) | 0.18 | 2.26 | 2.11 | 2.51 |
| building age | -0.04 | 3.23 | 2.67 | 3.33 |
| flood exposure (SFHA, V, BFE - ground) | 0.18 | 2.47 | 2.24 | 2.77 |
| all descriptors | 0.17 | 2.10 | 1.95 | 2.47 |
| MMD (input distributions) | 0.18 | 2.11 | 1.96 | 2.36 |
| area-of-applicability DI | 0.03 | 2.50 | 2.41 | 2.87 |
| **30 measured houses ('probe')** | **0.96** | **1.60** | **1.60** | **1.65** |

Every input-only measure is weak (Spearman 0.0-0.5); for a new area (donors >= 100 km) none beats simply pooling all
donors (2.22 ft). A 30-house probe ranks donors almost perfectly (0.96).

## Experiment 2: how many measured houses does a new region need? (84 targets, donors >= 100 km; MAE ft)

| method | n=5 | 10 | 20 | 30 | 50 | 100 |
|---|---|---|---|---|---|---|
| pooled donors (n = 0) | 2.30 | | | | | |
| pooled + bias from probe | 2.21 | 2.09 | 2.04 | 2.00 | 1.98 | 1.97 |
| probe-picked donor | 1.98 | 1.86 | 1.73 | 1.69 | 1.67 | 1.64 |
| probe-picked donor + bias | 1.97 | 1.81 | 1.70 | 1.65 | 1.65 | 1.60 |
| model on the probe houses only | | 1.91 | 1.74 | 1.68 | 1.59 | 1.52 |
| local model, up to 3,000 houses | 1.34 | | | | | |

By state at n = 30 (probe-picked + bias vs pooled donors vs local): FL 0.64 / 1.06 / 0.54; HAR 0.68 / 1.82 / 0.48;
NC 2.19 / 2.94 / 1.77; NYC 2.15 / 2.28 / 1.97; VA 1.83 / 2.56 / 1.33.

## Reading

- Floor height differs between places mostly in how the SAME inputs map to height (local practice, freeboard,
  housing style), not in the inputs themselves. Input-only similarity (foundation mix, age, flood exposure, MMD,
  area of applicability) cannot see that, as Ben-David's bound predicts.
- The working definition of similarity is therefore empirical: a donor is similar to a place if its model fits a
  small measured sample there. 20-30 measured houses close most of the gap (2.30 -> 1.65-1.70 ft); beyond about 50
  houses, a model on the local houses alone starts to win.
- Product rule: every new region needs a calibration sample of about 30 measured houses (survey, certificates, or a
  public dataset) to pick and correct the donor model; with none, ship the pooled model with a wide error band.
- Soil, climate, terrain and rule context: tested in Experiment 3 below.

## Experiment 3: physical and regulatory context (2026-10-05; FIRST RUN, before the NC fix — rerun pending)

Scripts `region_context.py` (output `region_context_output.txt`), `context_test.py` (output `context_output.txt`).
Per region: soil from USDA Soil Data Access (water-table depth, poorly drained share, flooding frequency, hydrologic
group D), climate from Open-Meteo ERA5 1991-2020 (freezing index, January mean, precipitation), terrain from NSI
ground (slope to neighbours, relief), rules from the NFIP Community Status Book (CRS class, first FIRM year).
Shrink-swell clay and state freeboard ordinances were not available in a ready national form and are not included.

| measure | Spearman | top-1 donor | top-3 pooled | top-1, donors >= 100 km |
|---|---|---|---|---|
| distance (km) | 0.40 | 1.80 | 1.75 | 2.50 |
| input descriptors | 0.27 | 2.00 | 1.94 | 2.27 |
| soil | 0.37 | 2.20 | 2.13 | 2.29 |
| climate | 0.35 | 2.31 | 2.02 | 2.81 |
| terrain | 0.21 | 2.62 | 2.34 | 2.69 |
| flood rules | 0.16 | 2.28 | 2.04 | 3.37 |
| all context | 0.39 | 1.95 | 1.92 | 2.37 |
| descriptors + context | 0.39 | 1.96 | 1.86 | 2.25 |
| **learned similarity** (GBM on pairwise differences, leave target out) | **0.65** | 1.89 | 1.83 | **1.94** |
| 30 measured houses (Experiment 1) | 0.96 | 1.58 | 1.59 | 1.63 |

Pooled model for a new area (donors >= 100 km): house inputs only 2.18 ft; + region context 2.14; + context and
descriptors 2.10.
Learned-similarity importance (gain): difference in NSI default height (foundation mix) and in freezing index lead,
then V-zone share, terrain slope, BFE - ground, SFHA share, soil flooding frequency.

Reading: no single factor defines similarity; each alone is weak (Spearman 0.1-0.4). Learned from region pairs, the
combination (mainly foundation mix + winter cold + coastal exposure + terrain) ranks donors far better (0.65) and,
for a new area, picks a donor (1.94 ft) better than pooling everything (2.18). 30 measured houses (1.63) are still
clearly better. Context as model features helps only a little (2.18 -> 2.10). Caveat: 102 of the 109 regions are in
NC and FL, so the learned weights mostly reflect those two states.
