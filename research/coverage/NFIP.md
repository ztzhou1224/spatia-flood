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

## Terms of use (read 2026-10-04, https://www.fema.gov/about/openfema/terms-conditions)

> "you agree that the data will be used solely for statistical research or as a reporting record. Further you
> agree not to reidentify nor attempt to reidentify the individuals whose data is aggregated."
> "You also agree not to publish or release any facts that may lead to the identification of individuals who
> are the subject of the data."
> "you agree that the data cannot be used to make determinations that might affect an individual's rights or
> eligibility for benefits."

So matching a policy record to a specific house (by lidar ground, BFE, year built) is not allowed, and was
not done. Block-group statistics, as above, are aggregates. Whether a sold product may use even the
aggregates ("solely for statistical research", "determinations that might affect an individual's rights")
needs a legal read before anything built on NFIP data is sold.

## Part 2: prior narrowed by build era and BFE band (still aggregates)

`nfip_group_test.py K`; outputs `nfip_group_k30_output.txt`, `nfip_group_k10_output.txt`. The prior is the
median over the most specific group with >= K policy rows: block group x build era x (BFE - ground) band,
then coarser groups down to the tract. No record is matched to a house (OpenFEMA terms, above). Renewals
repeat rows, so K = 10 rows is only about 4 buildings; K = 30 is the safer aggregate.

Florida, 1 m lidar subset (8,800 certificates), lowest floor error:

| | MAE | above/below BFE right |
|---|---|---|
| model, no prior | 0.646 | 85.2% |
| model + block-group prior | 0.625 | 86.1% |
| model + grouped prior, K 30 | 0.619 | 86.2% |
| model + grouped prior, K 10 | 0.610 | 86.3% |
| ground + block-group median (no model) | 1.431 | 76.3% |
| ground + grouped median, K 30 / K 10 | 1.112 / 0.968 | 79.6% / 81.2% |

NYC (all 6,190 houses; national NSI + lidar 2.28): ground + grouped median 2.48 (K 30, 4,087 houses with
a prior) / 2.42 (K 10, 4,354). Raised houses: block-group median 2.45, grouped 3.08 / 3.06. Not raised:
national 1.49, grouped 2.22 / 2.15.
Harris B (national 0.355): grouped rule 0.388 (K 30) / 0.609 (K 10); Florida model + grouped prior 0.41.
Harris C (national 0.804): grouped rule 1.51 / 1.53 on the 1,013 houses with a prior; Florida model 0.99 / 1.01.

The 'BFE + group median (floor - BFE)' rule is not usable: NFIP BFE values include outliers (Florida K 10:
MAE 5.7, bias -4.0, p90 2.6), and 11 of the 47 NFHL zones over the NYC houses are tagged NGVD29.

Reading: narrowing the group helps only as a model feature in Florida, and only a little (0.625 to 0.61-0.62).
Used directly it beats the plain block-group median but still loses to the model, and in NYC and Harris it
does not beat the national estimate.

What one-to-one matching could add at most (not done; forbidden): in Florida 333,173 single-family policies
with floor and ground were effective in 2025, against 6,363,455 NSI RES1 buildings, so at most about 5.2% of
houses have a policy record that matching could find. All other houses would get nothing from it.
