# Florida benchmark of the core floor method (2026-10-04)

Answer key: 49,102 FDEM Elevation Certificates (cleaned set from the earlier backtest, matched to a
USACE NSI 2022 residential point within 30 m, median 2.9 m). Target: lowest floor (top of bottom floor,
ft NAVD88) and the call "lowest floor at or above the BFE". 86 county/grid groups. Every number is from
`fl_test.py` (`fl_test_output.txt`). Ground here is NSI's 1/3" (~10 m) DEM value, **not** 1 m lidar:
its error against the certificate's lowest adjacent grade is MAE 1.16 ft (median +0.03 ft).

| Method (10% certificates held out as pool) | MAE ft | within 1 ft | above/below BFE right |
|---|---|---|---|
| National default (NSI ground + NSI height) | 2.06 | 45% | 73% |
| + flood-code rule (SFHA and built ≥ 1985: floor ≥ BFE) | 1.92 | 48% | 77% |
| **Model trained on certificates in OTHER counties** | **1.22** | 61% | **83%** |
| Neighbours (10% local certificates) | 1.18 | 64% | 80% |

By building type (county-out model): slab 1.01 ft / 86% right; raised slab 1.15 / 80%; elevated
(diagrams 5–7) 2.37 / 75%; crawlspace 1.60 / 75%. Error is flat across construction eras (1.16–1.36 ft).

Findings:
1. The raw national default fails in Florida as in NYC (2.1 ft, 73% right); NSI's pier/pile default
   (8 ft) also mismatches FEMA's lowest floor, which for an elevated house with an enclosure is the
   enclosure floor (certificate median 1.1–1.4 ft above grade).
2. **A model trained on certificates from other counties is as good as local neighbour certificates**
   (1.22 vs 1.18 ft; 83% vs 80% right). Certificates are needed somewhere in the region to train, not
   next to each house.
3. Ground is now the biggest single error (1.16 ft from the 10 m DEM). 1 m lidar covers 91.5% of
   coastal Florida residents (`COAST.md`); the next test is the same model with 1 m lidar ground.

## Part 2: with 1 m lidar ground (`fl_lidar.py`, `fl_lidar_output.txt`)

8,800 certificates in the 8 USGS 1 m DEM tiles holding the most certificates (Lee, Collier, Broward,
Pinellas, Pasco; 2018 lidar), each with an Overture footprint (release 2026-08-19.0) and a lidar ring
0.5–2.5 m outside it. Floor height above ground from a model trained on certificates in OTHER counties
(national features only). The ring **median** is the reference chosen beforehand in Harris County.

Ground check vs the certificate's lowest adjacent grade: lidar ring median +0.15 ft median, MAE 0.43 ft;
NSI 10 m DEM MAE 0.84 ft (these tiles; 1.16 ft statewide).

| Ground used + model height | MAE ft | within 1 ft | above/below BFE right |
|---|---|---|---|
| NSI 10 m DEM | 0.91 | 73% | 84.5% |
| **1 m lidar ring median** | **0.66** | **83%** | **85.1%** |
| Certificate's own measured ground (best case) | 0.54 | 86% | 87.7% |

By type with lidar median: slab 0.54 ft (89% within 1 ft, 88% right), raised slab 0.76 ft, elevated
1.39 ft, crawlspace 1.11 ft (the ring lowest point fits crawlspaces better: 0.81 ft).

So with 1 m lidar and a model trained on other counties' certificates, the lowest floor is within 1 ft
for 83% of these houses and the above/below-BFE call is right 85% of the time, close to what perfect
ground would give. The remaining error is the floor-height part, mostly elevated houses.
