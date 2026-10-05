# Does the flood-elevation rule in force when a house was built predict its floor height? (2026-10-05)

Scripts: `assign_community.py` (output `assign_community_output.txt`), `rules_test.py` (output
`rules_test_output.txt`, `rule_events.csv`). Rule data: `sources/*.json`. House table: research/states houses_all
(261,783 houses with a measured living floor, rebuilt after the NC flood-input fix, see research/states/STATES.md).

## Rule data (sources/)

Collected on 2026-10-05 by research sub-agents from the texts themselves. Each record has a source URL, a verbatim
quote, a confidence and notes. Unknown values were left null, never guessed.

- **Statewide A-zone freeboard** (`state_codes.json`, 17 periods): FL 0 ft until the 6th-edition Florida Building Code,
  then +1 ft (effective 2017-12-31); VA +1 ft from the 2015 VRC (2018); NY State +2 ft from the 2007 Residential Code
  (2008); NYC +2 ft from 1 RCNY 3606-04 (2013-01-31); NC none in force (the 2018 NC code deleted the IRC's +1 ft; the
  2024 code restores it but is delayed); TX none (cities adopt the IRC, which had no A-zone freeboard before 2015).
- **Local freeboard** (`batch_01..11.json`): 66 NFIP communities, all of the 60 with the most measured houses plus
  6 picked from a partial ranking (Palm Beach County, Naples, Marco Island, Hampton VA, Onslow County, St James).
  They hold 81% of the measured houses. Current A-zone freeboard: 0 ft in 14,
  1 ft in 14, 2 ft in 28, 3 ft in 8, 4 ft in 1, unknown in 1. Confidence: high 14, medium 44, low 8.
- **Dating is the weak part.** Only 15 records have a complete history (the year local freeboard began is known).
  For most, the sources show only that a value was in force by some year: Municode's version archive starts around
  2011, American Legal returned 403, and web.archive.org was unreachable. The shared web-search budget also ran out
  midway. `rules_test.py` uses a value only from the year it is documented (earlier years = unknown). That leaves 54
  communities with usable periods, holding 75% of the houses.
- **Rules that are not a fixed height above the BFE are recorded but not modelled:**
  - Harris County (2 ft above the 0.2% elevation since 2018) and Houston (likewise since 2018-09-01) are stored as
    2 ft lower bounds.
  - Charlotte measures from its own "Community BFE" (about 2.2 ft above FEMA's).
  - Some Outer Banks towns set fixed NAVD88 floors (8-12 ft) since 2020.
  - Several Florida communities set minimum heights above the crown of the road.

## Tests (the scorer alone reads the measured floors)

1. **Compliance.** Post-FIRM SFHA houses with a BFE (n 55,418): measured floor height >= the legal minimum
   (BFE - NSI ground + rule) - 1 ft for 84%. By state: FL 77%, HAR 81%, NC 90%, NYC 85%, VA 98%.
2. **Rule changes.** For each dated change in a community, floor above BFE of post-FIRM SFHA houses built 1-5 years
   before vs 1-5 years after (the change year is skipped). Changes with at least 10 houses on each side:

| kind of increase | changes | median rule change (ft) | median floor change (ft) | floor rose in | houses after | floor above BFE before (median) |
|---|---|---|---|---|---|---|
| statewide (22 of FL 2017, NYC 2013) | 23 | 1.0 | -0.01 | 43% | 2,296 | 0.84 |
| local | 6 | 1.5 | +0.58 | 67% | 490 | 1.55 |

   The six local increases (`rule_events.csv`):
   - St. Petersburg 2015, 0 -> 2 ft: floor +2.71 ft.
   - Hampton 2014, 1 -> 3 ft: +1.35 ft.
   - Craven County 2004, 0 -> 2 ft: +0.63 ft.
   - Fort Lauderdale 2014, 0 -> 1 ft: +0.54 ft.
   - Hampton 2010, 0 -> 1 ft: -0.20 ft.
   - Tampa 2009, 0 -> 0.5 ft: -0.34 ft.

   NYC 2013 (0 -> 2 ft) shows +0.69 ft.
3. **Rule features in a model for a new area** (pooled donors >= 100 km away, 109 target regions; features post_firm,
   fb_rule, req_height, years after FIRM): MAE 2.23 ft without, 2.25 ft with.
4. **Leave one state out** (MAE ft, without -> with the rule features): FL 2.93 -> 3.07, NC 3.91 -> 3.86,
   VA 2.28 -> 2.21, NYC 2.26 -> 2.25, HAR 2.51 -> 3.17.

## Reading

- The rule in force is a floor that most houses already clear, not a predictor of their height. 84% of post-FIRM SFHA
  houses meet their legal minimum within 1 ft, and the margin above it varies too much for the rule to place a house.
- Florida's statewide +1 ft (2017) left no visible step in the certificate floors (median change -0.01 ft over 22
  communities), although the median floor was only 0.84 ft above the BFE before it. Larger local increases (1.5-2 ft)
  did move floors (median +0.58 ft; St. Petersburg +2.7, Hampton +1.35). Rules seem to show up only when they exceed
  what builders already do by a clear margin. This rests on six events; it is a lead, not a measurement.
- As model inputs the rule features do not help a model carry to a new area (2.23 -> 2.25 ft). They help slightly in
  NC and VA and hurt in FL and Harris (2.51 -> 3.17, where Houston-area rules are lower bounds tied to the 500-year
  elevation). They add nothing to the 30-house calibration sample rule in research/similarity/SIMILARITY.md.
- Product use: the legal minimum is worth carrying as a check, not a feature. Flag a post-FIRM SFHA estimate that
  falls below BFE + rule in force, and record the rule with its source in the per-building row.

## Caveats

- "Floor above BFE" = measured floor height - (BFE - NSI ground). Floor and ground are measured, but the BFE is
  referenced to the 10 m NSI ground. That adds about +-1-2 ft of noise per house, and pushes some post-FIRM houses
  below their BFE on paper. It cancels in before/after differences only if the ground error does not change with
  build year.
- New maps change BFEs over time, and nothing here separates a rule effect from a map change.
- The Florida 2017 rule took effect on 2017-12-31 but is coded 2017. The before/after test skips the change year;
  the model features misassign houses built in 2017.
- 2020-2025 rules (Outer Banks, Pamlico, Sarasota, Marco Island) have few measured houses after them.
- The state-rule periods treat a statewide code as binding everywhere in the state. TX cities can amend the IRC.

## Also found while rebuilding (fixed, see research/states/STATES.md)

The NC house rows read the NC layer's coded flood zone and its yes/no "STATIC_BFE" flag as if they were a zone name and
an elevation. The house table, the cross-state test and similarity Experiments 1-3 were rerun after the fix.
