# Do we need a separate floor-height model per state? (2026-10-05)

Scripts: `fetch_nc.py`, `fetch_more.py`, `nsi_state.py`, `nc_bfe.py`, `build_table.py`, `cross_state.py`; outputs `build_table_output.txt`,
`cross_state_output.txt`. 261,783 single-family houses with a measured living floor: NC 122,444 (field-measured,
NCEM), NYC 85,447 (Staten Island BES), FL 43,547 (certificates, diagrams 1A/1B/5), HAR 7,661 (HCFCD), VA 2,684
(Hampton Roads certificates). Same national inputs everywhere: NSI foundation type / default height / stories /
median year, the house's year built, FEMA zone, BFE - NSI ground. Target: living floor - ground (ft).
Six small NFHL tiles at Staten Island's west edge failed to download (houses there get no zone/BFE).

**Correction (2026-10-05, later the same day).** The first version of this table read two NC fields wrongly:
the NC layer's `FLD_ZONE` is a coded domain (1001 = AE, 1009 = VE, 4002 = X) and `STATIC_BFE` is a yes/no
confidence flag (1000 / 1010), not an elevation. NC houses were flagged in the SFHA only where the code happened to be
a plain zone name (6% instead of 58%), and their "BFE - ground" was about 1,000 ft. `build_table.py` now uses the
decoded zone and the FEMA static BFE (`nc_bfe.py`, spatia-data `fema_flood_zones`; 33% of NC houses have one, as
riverine AE reaches have no single static BFE). Every number below is the rerun; cells not involving NC came out
identical to the first run, so all changes are from the fix. First-run values are in the git history.

Floor height MAE (ft):

| test place | NSI default | trained on the other 4 places | pooled (others + this place) | this place only |
|---|---|---|---|---|
| FL | 1.36 | 2.91 | 0.78 | **0.62** |
| NC | 3.72 | 3.90 | 2.66 | **2.45** |
| VA | 2.81 | 2.28 | 2.00 | **1.39** |
| NYC (Staten Island) | 2.77 | 2.26 | **2.06** | 2.07 |
| HAR | 0.84 | 2.09 | 0.89 | **0.66** |

Pairwise (train on the row, test on the column; diagonal = local 5-fold by 0.05 deg blocks):

| | FL | NC | VA | NYC | HAR |
|---|---|---|---|---|---|
| FL | 0.62 | 4.74 | 2.83 | 3.21 | 0.66 |
| NC | 3.39 | 2.45 | 2.16 | 2.26 | 3.37 |
| VA | 2.38 | 3.55 | 1.39 | 2.27 | 0.69 |
| NYC | 3.35 | 3.32 | 2.77 | 2.07 | 2.84 |
| HAR | 1.62 | 3.99 | 2.03 | 3.20 | 0.66 |

Reading (revised after the fix):
- Local measured data is what works: each place's own model is best (NYC ties with pooling).
- A model trained on the other places beats the NSI default for VA and NYC (2.28 vs 2.81; 2.26 vs 2.77) but is
  worse for FL, NC and Harris. Pooling now costs a little even where the local set is large (FL 0.78 vs 0.62,
  NC 2.66 vs 2.45), and more for the small sets (VA, HAR).
- Slab-on-grade Gulf / Southeast places share a model: Florida -> Harris 0.66 ft (equal to Harris's own model),
  Virginia -> Harris 0.69. With its flood inputs fixed, the NC model also carries to the other raised-housing coasts:
  NC -> NYC 2.26 (NYC's own 2.07), NC -> VA 2.16 (VA's own 1.39, NSI 2.81). Before the fix NC looked isolated
  (NC -> NYC 3.85, NC -> VA 3.50); that was the bug, not the housing.
- Part of the cross-place gap is definitions (front door vs living floor, certificate vs lidar ground), not only
  housing. New Jersey cannot be scored (no public measured floors); NYC -> VA (2.27 vs VA's own 1.39) suggests an
  NYC model would not carry to NJ without some NJ measurements.
