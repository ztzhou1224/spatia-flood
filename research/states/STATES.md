# Do we need a separate floor-height model per state? (2026-10-05)

Scripts: `fetch_nc.py`, `fetch_more.py`, `build_table.py`, `cross_state.py`; outputs `build_table_output.txt`,
`cross_state_output.txt`. 261,783 single-family houses with a measured living floor: NC 122,444 (field-measured,
NCEM), NYC 85,447 (Staten Island BES), FL 43,547 (certificates, diagrams 1A/1B/5), HAR 7,661 (HCFCD), VA 2,684
(Hampton Roads certificates). Same national inputs everywhere: NSI foundation type / default height / stories /
median year, the house's year built, FEMA zone, BFE - NSI ground. Target: living floor - ground (ft).
Six small NFHL tiles at Staten Island's west edge failed to download (houses there get no zone/BFE).

Floor height MAE (ft):

| test place | NSI default | trained on the other 4 places | pooled (others + this place) | this place only |
|---|---|---|---|---|
| FL | 1.36 | 2.24 | 0.65 | **0.62** |
| NC | 3.72 | 3.69 | 2.40 | **2.37** |
| VA | 2.81 | 2.61 | 2.04 | **1.39** |
| NYC (Staten Island) | 2.77 | 2.59 | **2.06** | 2.07 |
| HAR | 0.84 | 2.91 | 0.84 | **0.66** |

Pairwise (train on the row, test on the column; diagonal = local 5-fold by 0.05 deg blocks):

| | FL | NC | VA | NYC | HAR |
|---|---|---|---|---|---|
| FL | 0.62 | 3.84 | 2.83 | 3.21 | 0.66 |
| NC | 5.98 | 2.37 | 3.50 | 3.85 | 3.46 |
| VA | 2.38 | 3.49 | 1.39 | 2.27 | 0.69 |
| NYC | 3.35 | 3.26 | 2.77 | 2.07 | 2.84 |
| HAR | 1.62 | 3.26 | 2.03 | 3.20 | 0.66 |

Reading:
- A model trained elsewhere is no better than the NSI default (often worse). Local measured data is what works.
- Pooling all places does not hurt where the local set is large (FL, NC, NYC), but a small local set (VA, HAR)
  is better on its own: the other places pull it toward their own housing.
- Some places transfer: Florida -> Harris 0.66 ft (equal to Harris's own model); Virginia -> Harris 0.69. Similar
  housing (slab-on-grade Gulf / Southeast) shares a model; raised-housing coasts (NC, NYC, VA) do not share with
  each other or with the slab regions.
- Part of the cross-place gap is definitions (front door vs living floor, certificate vs lidar ground), not only
  housing. New Jersey cannot be scored (no public measured floors); NYC -> VA (2.27 vs VA's own 1.39) suggests an
  NYC model would not carry to NJ without some NJ measurements.
