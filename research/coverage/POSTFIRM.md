# Year built, post-FIRM construction and permits (2026-10-04)

Script `postfirm_test.py`, output `postfirm_output.txt`. Community first-FIRM dates: OpenFEMA
NfipCommunityStatusBook (NYC 360497: 1983). NYC flood zones: NFHL layer 28; its BFEs are tagged NGVD29 and are
converted with NOAA VDatum (-1.08 ft at three Staten Island points); one AE polygon with a 271 ft BFE is dropped.
NYC permit flags from research/nyc_permits.

Florida (49,102 certificates, model trained on other counties): adding post_firm, years after FIRM and parcel
effective-year changes nothing (floor height MAE 0.704 -> 0.705 ft; 1 m lidar subset FFE 0.659 -> 0.661 ft,
above/below BFE 85.1% -> 85.0%). The model already had the parcel year built, SFHA and BFE - ground.

NYC (6,190 BES houses, no NYC labels used), first floor elevation MAE (ft):

| | all | raised (> 6 ft, 1,198) | not raised | the 966 houses the rule touches |
|---|---|---|---|---|
| national NSI + lidar (before) | 2.28 | 5.10 | 1.60 | 4.18 |
| rule: in SFHA, post-FIRM or permit-flagged -> floor >= BFE + 1 ft | **2.15** | **4.22** | 1.65 | **3.36** |
| Florida-trained model + post-FIRM | 2.91 | 6.41 | 2.07 | 4.86 |

Where the raised houses are: SFHA post-FIRM 437 of 820 (53%); SFHA pre-FIRM / unknown 197 of 1,143 (17%);
outside the SFHA post-FIRM 347 of 882 (39%); outside pre-FIRM 217 of 3,345 (6%). Many Staten Island houses
built after 1983 are raised even outside the flood zone (a local building style), which no flood rule reaches.

Reading: the code rule is a real but partial fix for NYC (2.28 -> 2.15 ft overall, raised 5.10 -> 4.22). It needs
the BFE in NAVD88; a Florida-trained model still does not transfer.
