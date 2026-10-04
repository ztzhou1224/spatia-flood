# Public measured floor-elevation datasets (searched 2026-10-04)

Counts from live queries (ArcGIS REST returnCountOnly / group-by, NYC Socrata) run on 2026-10-04.

| dataset | where | measured buildings | access | licence |
|---|---|---|---|---|
| NYC Building Elevation and Subgrade (bsin-59hv) | NYC, all buildings | 712,333 of 861,875 'successfully measured' (imagery, one-time 2022 capture) | Socrata bulk/API | NYC Open Data: no restrictions on use |
| NC Risk Building Footprints (NCEM) | North Carolina, 5,193,564 buildings | FFE_TYP codes: certificate 6,657; traditional survey 3,788; laser inclinometer high 139,816 / low 9,274; terrestrial lidar high 21,590; aerial-lidar derived (estimate) 5,012,422 | ArcGIS FeatureServer | none stated; attribution + registration of derivatives; ask NCEM about commercial use; datum not in schema |
| Hampton Roads Elevation Certificates (HRPDC / ODU) | 12 VA localities | 5,145 with FFE > 0 (NAVD88 service) | MapServer + data.virginia.gov | 'No License Provided'; last update 2020 |
| Monroe County FL (Keys) Elevation Certificates | Florida Keys | 6,122 with Top_Bottom_Flr | FeatureServer | not stated; may overlap FDEM |
| Kenner LA; USACE Savannah/Tybee; St. Charles Co. MO; USGS surveys (VT, AK, KC) | small | 61 to ~1,259 each (from the search agent, not re-counted) | various | various |

Per-address PDF indexes only (no values): Charleston SC, Miami-Dade, Pinellas, King County WA, Baltimore County,
York County SC, several Louisiana parishes. Not public: NFIP rating certificates; most community certificates
(public-records request); NSI field surveys. No statewide inventory found for TX, NJ, CT, MA, CA.
