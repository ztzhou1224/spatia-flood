# FEMA flood-insurance policies as a floor-height prior (2026-10-04)

Question: FEMA publishes every NFIP policy (OpenFEMA `NfipPolicies` v3, public). Policies rated with an
elevation certificate carry its lowest floor (LFE) and lowest adjacent grade (LAG). Does the local
distribution of these values fix the national floor estimate where no certificates are published?

Scripts: `fetch_nfip.py` (download), `nfip_test.py` (test); output `nfip_test_output.txt`.

## The data

Single-family policies effective since 2024-01-01 with LFE and LAG: Florida 929,083 rows (all 68 county
codes, incl. Miami-Dade 12086), Harris 78,240, Staten Island (Richmond) 3,900. Renewals repeat a building,
so buildings are fewer than rows. Location is the 2020 census block group (99.5% of Harris and 99.8% of
Richmond geoids match TIGER 2020); lat/lon are rounded to 0.1 degree. No address and no building id, so a
policy cannot be matched to a house. After cleaning: 1,003,491 rows in 10,158 block groups; LFE - LAG
q10/50/90 = 0.6 / 1.2 / 6.3 ft.

Two real records (Staten Island and Lee County):

| field | Staten Island | Lee County FL |
|---|---|---|
| block group | 360850112031 | 120710017092 |
| approx. location | 40.6, -74.1 | 26.5, -81.9 |
| foundation | 5 elevated, enclosure, piles | 1 slab |
| lowest floor (ft) | 14.8 | 7.1 |
| lowest adjacent grade (ft) | 5.6 | 6.6 |
| BFE (ft) | 10.0 | 7.0 |
| elevation difference (FEMA field) | -4.0 | 0.0 |
| built | 2009 | 2001 |
| zone | AE | A10 (now AE) |

The FEMA `elevationDifference` field does not always equal LFE - BFE (Staten Island: 14.8 - 10.0 = +4.8,
field -4.0); it is not used.

## Prior

Per block group: records, median / p25 / p75 of LFE - LAG, share elevated (foundation 4-6), crawlspace,
basement. Tract values when the block group has < 10 records.

## Results (ft)

Florida floor height above the certificate's ground, model trained on other counties (49,102 certificates):

| | MAE | within 1 ft |
|---|---|---|
| model, no prior | 0.70 | 81% |
| model + NFIP prior | **0.64** | 84% |
| NFIP block-group median alone | 1.53 | 69% |
| NSI default height | 1.50 | 65% |

By type, with the prior: slab 0.37 to 0.34, raised slab 1.04 to 0.85, elevated 1.65 to 1.63, crawlspace
0.99 to 1.05. With 1 m lidar ground (8,800 certificates): FFE MAE 0.646 to 0.625, above/below BFE right
85.2% to 86.1%. Restricting to block groups with >= 30 records gives the same gain (0.705 to 0.639), so it
is not the test house's own certificate leaking through the median.

NYC (Staten Island east shore, 6,190 measured houses): 1,836 houses have no prior (only 48 Richmond block
groups have records).

| | all MAE | raised houses MAE (1,636) |
|---|---|---|
| national NSI + lidar (before) | 2.28 | 4.46 |
| lidar median + NFIP block-group median | 2.98 | **2.45** |
| model trained in Florida + prior | 2.81 | 5.88 |

Harris (front door, measured): no gain. B: national 0.36, model trained in C 0.455 / with prior 0.49.
C: national 0.80, model trained in B 0.78 / with prior 0.78. Most Harris test houses have only a tract
prior or none (B: 1,215 of 5,127 at block-group level; C: 868 of 2,539).

## Reading

- The prior helps where the model can learn how it relates to the house: in Florida, trained on Florida
  certificates, it cuts the floor-height error about 9% (most for raised slabs).
- Alone it is biased high: policies with a certificate are mostly houses in the flood zone, many of them
  newer or raised, so the block-group median describes insured certified houses, not every house.
  In NYC it fixes raised houses (4.46 to 2.45) but overestimates the rest.
- It does not transfer by itself: the Florida-trained model still fails in NYC, and in Harris the
  national estimate was already good (0.36 ft in B).
- Coverage is uneven: dense in Florida, thin in Staten Island and in Harris neighbourhoods outside the
  flood zone.
