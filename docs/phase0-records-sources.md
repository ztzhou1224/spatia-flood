# Floor count and foundation: free Florida sources (survey, 2026-10-07)

**Outcome (owner, 2026-10-07): floor count and foundation are not columns of the layer**, so none of the sources
below is ingested and no RentCast call is made. Kept as a reference.

Why: RentCast for all of Florida was ruled too costly (owner, 2026-10-07); free sources first. The floor estimate
itself does not need these fields (`docs/phase0-florida.md`, `eval_no_records.py`: 0 to 0.03 ft MAE within area);
they matter only as record-class columns in the layer. Survey by a research agent from pages it opened
(WebFetch / WebSearch); rows marked *excerpt* rest on a search excerpt only. Several appraiser sites refused the
fetcher (403 / 503): Pinellas, Brevard, Monroe, St. Lucie, Lake FTP, Okaloosa, Orange. No page opened forbids
commercial use or resale, and none grants a licence: the terms are accuracy / liability disclaimers ("may not be
appropriate for any other use", "as is"); Manatee and Pinellas warn that scraping may end access. A legal read is
needed before selling derived columns. Most files carry owner names: drop them at ingest.

| County | Free bulk | Stories field | Foundation / floor field | Source |
|---|---|---|---|---|
| Sarasota | yes | `storyhgt` | `foundation` (+ `Lookupfoundation`), `primaryfloors` | sarasotapropertyappraiser.gov download-data, `SCPA_Detailed_Data.zip` |
| Polk | yes (nightly FTP) | `STORIES` | `SUBSTRUCT` / `SUBDESC` (foundation), `FLOORTYPE` | polkflpa.gov FTP_BLDFileLayout |
| Citrus | yes | `VD_RESBLD.STORIES` | `VD_RESBLD.FOUNDATION`, `FLOORING` | citruspa.org Downloads, vendor dump |
| Hernando | yes (weekly) | STRU field 56 "Stories" | structural-element codes (PIERS, STILTS, SLAB ...) | hernandocountypa-florida.us Downloads |
| Martin | yes | "Story Height" (column name not seen) | "Foundation" (column name not seen) | pamartinfl.gov data-downloads |
| Lee | footprints REST free; PA files $50 | `MaxStories` per footprint | not found | Lee County Building_Footprints FeatureServer |
| Hillsborough | yes | `tSTORIES` | not found | hcpafl.org Maps-Data |
| Manatee | yes (nightly) | `BLDG_R1_STORIES` | basement code only | manateepao.gov CAMA file |
| Pasco | yes (weekly) | `Bldg_Stories` | not found | downloads.pascopa.com building.zip |
| Indian River | yes | "# of Stories" | not confirmed | indianriverfl-auditor CAMA extract |
| Bay | yes (REST) | `s1stories`, footprints `NUMSTORIES` | not found | gis.baycountyfl.gov |
| Marion | yes (REST) | `STRY` (undefined) | not found | gis.marionfl.org |
| Pinellas | *excerpt*: RP_BUILDING CSV | *excerpt* `STORIES` | *excerpt* `FOUNDATION`, `FLOOR_SYSTEM` | pcpao.gov (403 to the fetcher) |
| Palm Beach, Volusia, Brevard, Duval, Lake, St. Lucie, St. Johns, Osceola | free (Palm Beach by request) | field list not verified | not verified | appraiser download pages |
| Charlotte, Collier | free | none in the layout | none | layouts read |
| Miami-Dade | PA bulk $50 / file, account | free REST `FLOORS` only for ~15,586 large buildings | not found | bbs.miamidadepa.gov |
| Broward, Orange, Monroe, Escambia, Santa Rosa, Okaloosa, Walton, Franklin | not found | - | - | - |

Statewide / national: Overture `num_floors` (ODbL; 826 of 248,314 Pinellas risk-area houses, `records_gap.py`);
OSM `building:levels` (same data path); FEMA / ORNL USA Structures (CC BY 4.0) has height and ground elevations, no
stories or foundation; FGIO / SFWMD statewide parcels and DOR NAL / SDF have none. NSI 2022 documents its stories and
foundation as derived from Lightbox (commercial) parcels or "randomly assigned" from distributions, so NSI is not a
record of either.

**Paid lookups that would remain** (only if record-class floors / foundation are wanted): the 11 counties with no
free source hold 2,175,682 NSI residential structures (`pipeline/phase0/out/fl_counties.csv`; Miami-Dade, Broward,
Orange, Collier, Charlotte, Monroe and five panhandle counties). At 500 records per RentCast request: 4,352-8,703
requests, $199-310 on the Growth plan for one month. The 8 unverified counties and 35 unsurveyed (smaller) counties
are checked before any call.
