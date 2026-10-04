# NYC building permits as a raised-house signal (2026-10-04)

Script `nyc_permits.py`, output `nyc_permits_output.txt`. NYC DOB job filings (BIS ic3t-wcy2 + DOB NOW w9ak-ipjd,
NYC Open Data, free) matched by BIN to the 6,190 BES houses; no owner or applicant fields downloaded.
Answer key (scorer only): BES floor - grade; raised = > 6 ft (1,198 houses, 19%).

| flag | houses flagged | precision | recall |
|---|---|---|---|
| description mentions elevating / raising the house or flood terms (Build It Back etc.) | 221 | 62% | 12% |
| new-building filing after Hurricane Sandy (2012-11) | 233 | 60% | 12% |
| either | 386 | 58% | 19% |

40% of houses have some DOB filing. Raised houses by year built (NYC footprint construction year): 31% of 1980-99
houses, 58% of 2000-11 and 58% of 2012+ are raised; permits find 111 of 130 raised post-2012 houses but only 9 of
689 raised houses built 1980-2011. Most raised houses were built raised, not lifted later, so a permit trail
misses them; the house's own year built (post-FIRM construction) carries more of the signal.
