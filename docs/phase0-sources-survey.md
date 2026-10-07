# Phase 0 sources survey: Florida Elevation Certificates and input licences

Status: **research only, nothing built.** Retrieved 2026-10-07. Every count below comes from an
ArcGIS REST query, an API response, a directory listing or a downloaded file retrieved on
2026-10-07; the query or URL is given with it. Anything not retrieved is marked *unverified*.
Sample downloads (PDFs) were kept in the session scratchpad only; nothing was added to `data/` or git.

Method notes:

- Counts are `.../query?where=1=1&returnCountOnly=true&f=json` unless another `where` is shown.
- "PDF type" was measured on small samples with poppler (`pdfinfo` for AcroForm/XFA, `pdftotext -l 1`
  for the page-1 text layer, `pdfimages -l 1 -list` for page-1 images). "Image-only" = page 1 has no
  text layer and at least one raster image (a scan). "Text layer" = page 1 has extractable text
  (~2,200 to 2,900 non-space characters for the FEMA form). Samples are small; the shares are not
  population estimates.
- Per-county counts of the FDEM layer were made by a spatial intersect: each Florida county polygon
  from Census TIGERweb (`TIGERweb/State_County/MapServer/1`, `STATE='12'`, generalised with
  `maxAllowableOffset=0.0005` deg) was posted as the query geometry with `returnCountOnly=true`.
  The 67 counts sum to 210,897, 9 more than the layer total of 210,888, so a few records near a
  county line are counted twice. The free-text `nfipCountyName` field was not used for counts: it
  has 566 distinct spellings (e.g. `LEE`, `LEE COUNTY`, `LEE COUNTY, UNINCORPORATED`).

## Part A. Elevation Certificates reachable in Florida

### A1. The FDEM statewide layer (baseline)

Layer: `https://services8.arcgis.com/4L6VuYsPSGSEJ0qe/ArcGIS/rest/services/Public_FDEM_Elevation_Certificates/FeatureServer/0`

| Fact | Value (2026-10-07) | How measured |
|---|---|---|
| Records | **210,888** | `returnCountOnly` |
| Records with a PDF link (`url` not null/empty) | 210,888 | `where=url IS NOT NULL AND url<>''` |
| `url` target | `https://florida.withforerunner.com/view-file/<uuid>` | sample records |
| PDF downloadable without login | yes: 20 of 20 sampled URLs returned HTTP 200 `application/pdf` | curl |
| Bulk download (zip/export) | none found; the layer itself is a complete index of 210,888 per-record PDF URLs (capabilities: `Query`, maxRecordCount 2000) | service JSON |
| ArcGIS item | id `92fb38b201e0440c83a959970b194973`, title "FDEM Public Elevation Certificates", owner `jtwhite_forerunner`, created 2023-06-09, snippet "Extracted Elevation Certificate data from documents uploaded to florida.withforerunner.com." | `sharing/rest/content/items/<id>` |
| `licenseInfo`, `accessInformation`, `copyrightText` | all empty | item + layer JSON |
| Data last edited | 2026-10-01 09:09 UTC (`dataLastEditDate` 1790845756732) | layer JSON |
| `topOfBottomFloor` not null | 206,255 | `where=topOfBottomFloor IS NOT NULL` |
| `topOfBottomFloor` and `lowestAdjacentGrade` not null | 203,925 | |
| `elevationDatum` | navd_1988 173,020; ngvd_1929 37,164; other 347; null 357 | `groupByFieldsForStatistics` |
| `buildingElevationSource` | finished_construction 166,226; building_under_construction 34,958; construction_drawings 8,257; null 1,447 | |
| `formYear` | 2018: 87,396; 2022: 77,122; 2026: 45,250; null 476; 18 other values ≤ 224 each | |
| `issuedAt` | contains invalid dates (min year 202, max year 6201) | `outStatistics` min/max |
| `buildingOwnerName` non-empty | **175,106** (personal data, must be dropped at ingest) | |
| Geometry | multipoint, wkid 3857; all 210,888 intersect a world envelope | |

A second Forerunner-owned layer, `PUBLIC_FL_Elevation_Certificates_and_Warnings_WFL1/FeatureServer/1`,
has 85,084 records, last edited 2023-04-12; it looks like an older snapshot of the same data.
An FDEM-org copy, `services.arcgis.com/3wFbqsFPLeKqOlIK/.../ElevationCertificates_Submissions_COUNTIES/FeatureServer/0`,
has 201,553 records with the same Forerunner `url` values and a county join. FDEM's older
"Florida Elevation Certificates - Archive" map layer
(`maps.floridadisaster.org/gis/rest/services/Feature/Elevation_Certificates/MapServer/0`) returned
HTTP 403.

**PDF type, FDEM sample (20 records, one every 10,543 OBJECTIDs, 1 to 200,318):**

| Class | Count | Notes |
|---|---|---|
| Text layer on page 1 (born-digital) | 14 | 6 with AcroForm, 1 XFA; producers Acrobat Distiller, LiveCycle, PDFlib, Microsoft, Ghostscript, Nuance |
| Image-only page 1 (scan) | 4 | producers EPSON Scan, Xerox AltaLink, SECnvtToPDF, novaPDF |
| Mixed (XFA, 75 chars + image on page 1; 46,549 chars over 18 pages) | 1 | |
| No text and no image on page 1 (vector-only) | 1 | |

Portal and statute (from `https://www.floridadisaster.org/elevation-certificates/`): the public
search is `https://florida.withforerunner.com/properties`. Since 2023-01-01, s. 472.0366(2), F.S.
requires each surveyor to submit "a digital copy of each elevation certificate that he or she completes"
within 30 days; "The copy must be unaltered, except that the surveyor and mapper may redact the name
of the property owner." (`https://www.flsenate.gov/Laws/Statutes/2025/0472.0366`).

### A2. Per county (the 17 requested)

"FDEM n" = FDEM layer records inside the county polygon (method above).

| County | FDEM n | Local public EC source found | Local count (2026-10-07) | PDF type (sample) | Access / terms |
|---|---|---|---|---|---|
| Miami-Dade | 14,948 | DERM Environmental Records app `https://ecmrer.miamidade.gov`, backed by `POST https://api-ecmrer.miamidade.gov/derm/documents` with `{"documentType":"ELEVATION CERTIFICATE"}`. Per-document index with folio, address, date and a direct file URL on `stecmrerportal.blob.core.windows.net` (no login). The app code also has a `/zip` download call (not tested). | **112,016** documents (enumerated all 225 pages of 500): 45,287 `.pdf`, 65,567 `.tif`, 1,156 `.bmp`, 6 `.fmp`; folio blank or zero on 36. Document dates: 1980-89 108; 1990-94 5,777; 1995-99 25,472; 2000-04 30,757; 2005-09 21,645; 2010-14 7,047; 2015-19 9,740; 2020-24 8,782; 2025- 2,529; invalid 159 | 8 sampled: 5 TIFF images; of 3 PDFs, 2 image-only, 1 AcroForm with OCR text (Acrobat Paper Capture) | Website disclaimer: "THE SERVICES, INFORMATION, AND DATA MADE AVAILABLE AT THIS WEBSITE ARE PROVIDED 'AS IS' WITHOUT WARRANTIES OF ANY KIND." (`https://www.miamidade.gov/global/disclaimer/disclaimer.page`); no redistribution clause found. The `facilityName` field holds personal names in the sample. |
| Pinellas | 11,222 | (a) `https://egis.pinellas.gov/gis/rest/services/ElevationCertsApp/ElevationCertsApp/MapServer/0`: structured EC fields (A1-G, incl. `C2A_TOP_BOTTOM_FLOOR_EL`, `C2F_LAG_ELEV`, NGVD/NAVD variants); no attachments. (b) AGOL `services.arcgis.com/f5HgUpxURgEzTccH/.../Elevation_Certificates_New_Public/FeatureServer/0` (owner `eGIS_Applications`): same schema with PDF attachments. (c) `.../ElevationCertificatesCityNewest_Redacted/FeatureServer/0`: municipal ECs (Madeira Beach, Pinellas Park, Tarpon Springs seen) with PDF attachments. App: `https://experience.arcgis.com/experience/eca0e234e9c24b239bee3026d2f529b7` | (a) 19,382; C2A not null 18,324; C2A and C2F not null 17,282; `FILE_NAME LIKE '%.pdf'` 1,550. (b) 19,382 (first 20 records: 23 PDF attachments). (c) 1,513 (first 20: 19 PDF attachments) | 4 attachments from (b): all image-only page 1 (2 flagged AcroForm) | Coverage quote: "Pinellas County provides copies of FEMA elevation certificates on all buildings in the unincorporated area constructed in the floodplain since 1992." (`https://pinellas.gov/flood-elevation-certificate/`). Layer description names a data steward; no licence text. |
| Lee | 24,525 | Forerunner portal `https://leecountyfl.withforerunner.com/elevation-certificates`, unincorporated Lee only (`https://www.leegov.com/dcd/buildingpermitservice/searchec`) | not stated | not sampled | per-address search; no bulk option named on the county page. Forerunner terms apply to its sites (Part B1). |
| Collier | 14,266 | AGOL `https://services2.arcgis.com/SlIq32SqARUHIhSx/arcgis/rest/services/Elevation_Certificates_view/FeatureServer/36`: point per EC with a `Certificate` URL to `apps4.collier.gov/visionftp/GMDNorth/fema/ec/*.PDF`, plus `BFE`, permit number | 32,630; all have an `http` link; 32,615 end in `.pdf` | 3 sampled: 2 image-only, 1 image + 730 chars | Copyright text: "The maps and data contained herein are a representation of compiled public information. ... Collier County and its employees make no guarantees, implied or otherwise as to the accuracy or completeness. We therefore do not accept any responsibilities as to its use." |
| Monroe | 6,718 | AGOL `https://services.arcgis.com/D7K7hj5GW1YIVRiA/arcgis/rest/services/Elevation_Certificates/FeatureServer/1` (Monroe County Floodplain Management): structured fields (`Top_Bottom_Flr`, `LAG`, `HAG`, `Vert_Datum`, `Type_Doc`) with PDF attachments. City of Key West: `services3.arcgis.com/aIpcLPHSEqH4LbLl/.../Flood_Certificates_Key_West5_WFL1/FeatureServer/0` | County: 6,989 records (Type_Doc EC_FC 6,710, EC_UC 47, EC_CD 1, other types 231); `Top_Bottom_Flr` not null 6,122; sum of `Count_Attach` 2,964. Key West: 1,489 records (EC 1,111, EC_CD 93, EC_UC 48); sum `Count_Attach` 1,482 | County: 2 of 4 sampled records had no attachment; the 2 PDFs were image-only. Key West: 4 of 4 image-only (3 flagged AcroForm) | Description: "Point Locations of Monroe County properties with recorded Elevation Certificates. Features Updated: April 23, 2025"; copyright "Monroe County, Florida - Floodplain Management Department". No licence text. |
| Broward | 21,604 | No county-wide public EC index found. City of Deerfield Beach: `services1.arcgis.com/yJ4j7ns7W6juha0m/.../Elevation_Certificates_View/FeatureServer/0` with PDF attachments | Deerfield Beach 1,428 | 4 sampled: 3 image-only, 1 text layer (2,191 chars) | no licence text. Other Broward cities *unverified*. |
| Palm Beach | 15,139 | Search results point to a Forerunner site `https://palmbeachcountyfl.withforerunner.com/` and an "Elevation Certificate" layer in My GeoNav; individual PDFs appear under `discover.pbcgov.org/pzb/building/ElevationCertificates/<year> ECs/` | *unverified*: no EC layer found in `gis.pbcgov.org/arcgis/rest/services` folders PZB, FEMA, Flood or `maps.co.palm-beach.fl.us/arcgis/rest/services` folders Flood, PZB, Dynamic; the PDF path redirected (HTTP 302) | not sampled | request line per search result (floodzone@pbcgov.org) *unverified* |
| Hillsborough | 10,381 | Search snippet says EC documents from 2005 on are in the online building-permit records and older ones by email request; the county page retrieved (`https://hcfl.gov/businesses/permits-and-records/reports`) did not state it | *unverified* | not sampled | no GIS EC layer found |
| Sarasota | 10,495 | (a) Open directory `https://ftp.scgov.net/GIS/ElevCerts/` (HTML listing). (b) ArcGIS `https://ags3.scgov.net/server/rest/services/Hosted/FemaElevationCert/FeatureServer/0` with `ecfilename`, permit, property account, flood zone | (a) 7,634 entries: 6,478 `.pdf`, 1,043 `.csv`, 24 `.doc/.docx`, other; total 10.69 GB; file dates 2014-2026 (2017: 2,839). (b) 2,880 records; 2 sampled `ecfilename`s were not in the FTP directory (HTTP 404), so where (b)'s PDFs live is *unverified* | not sampled | no licence text. City of Sarasota EC map *unverified* (its page returned 404). |
| Charlotte | 14,417 | `https://agis3.charlottecountyfl.gov/arcgis/rest/services/Essentials/CCGISLayers/MapServer/13`: "a compilation of data pulled from the Accela Permitting database and old certificate of elevations from the old Perconti system joined to addresses", with `FLOORELEVA`, `LOWESTGRAD`, `BASEFLOODE`, `Datum` and a `LINK` to `data.charlottecountyfl.gov/CCGIS/PDFs/Elevation_Certificates/*.pdf` | 36,894; `LINK` https 36,889, `file://` (internal) 5; `FLOORELEVA` not null 36,258 | PDF host gave intermittent HTTP 522; 3 retrieved: 2 image-only, 1 text layer (2,939 chars) | copyright "Charlotte County"; no licence text |
| Brevard | 2,870 | Search snippet: copies from the Floodplain Administration section, last ten years routinely, older (from 1992) case by case with a possible research fee; county page returned HTTP 403 to fetch | *unverified* (request-only) | n/a | |
| Volusia | 1,822 | `https://maps5.vcgov.org/arcgis/rest/services/AMANDA_Features/MapServer/0` "Elevation Certificates": parcel polygons with `FOLDERLINK` to a `connectlivepermits.org` file download. Town of Ponce Inlet: `services7.arcgis.com/vzinBpSUUhXOqWvK/.../Ponce_Inlet_Elevation_Certificate_View/FeatureServer/0` with attachments | county 3,622; Ponce Inlet 380 | 1 county link sampled: PDF, image-only | no licence text |
| Duval | 7,372 | none found; Jacksonville Beach lists ECs and sends copies by email (search snippet only) | *unverified* | n/a | |
| St. Johns | 9,856 | none found | n/a | n/a | |
| Escambia | 916 | none found | n/a | n/a | |
| Bay | 2,540 | AGOL `https://services1.arcgis.com/QB0VWfqR9MD4lF0F/arcgis/rest/services/Elevation_Certificate/FeatureServer/0`: parcel id, address, date, `PDF` link to `gis.baycountyfl.gov/elevationcertificates/<year>/<address>.pdf`. City of Lynn Haven: `.../City_of_Lynn_Haven_Elevation_Certificates/FeatureServer/0` | county 3,417 (all with a `gis.baycountyfl.gov` PDF link; `DateIssued` 1989-01-04 to 2026-09-03); Lynn Haven 341 | 3 sampled: all image-only | no licence text |
| Okaloosa | 675 | Search snippet: "Archived Elevation Certificates are on file in the planning office" | *unverified* (request-only) | n/a | |

### A3. Other Florida EC layers found in passing (ArcGIS Online search, `"elevation certificate"`)

| Jurisdiction | Layer | Count | Content |
|---|---|---|---|
| Orange County | `services1.arcgis.com/0U8EQ1FrumPeIqDb/.../Updated_Elevation_Certificate_Points_view/FeatureServer/0` | 10,781 | parcel, address, C2a/C2d/C2e/C2f/C2g fields (empty in the 3 sampled rows); no attachments |
| Lake County | `services1.arcgis.com/7LNyA2emK1umjjot/.../Elevation_Certificates_view/FeatureServer/1` | 3,123 | parcel key + PDF attachments; 4 sampled: image-only |
| Nassau County | `services5.arcgis.com/F73IhFZbCCYUexxB/.../Elevation_Certifications/FeatureServer/293` | 913 | address, EC year, owner name field, PDF link on S3 (`ncflpataxcards`) |
| Flagler County | `services3.arcgis.com/hSKL9bYjhP4rHxSD/.../Elevation_Certificate_new/FeatureServer/0` | 215 | attachments |
| Village of Pinecrest | `services3.arcgis.com/0IbOaQdCzMiaAcDv/.../Elevation_Certificates/FeatureServer/0` | 244 | attachments |
| City of Doral; Martin County | `gis.cityofdoral.com/.../ElevationCertificate2`; `services8.arcgis.com/qhgIImgl4UmEEyAS/.../2020_0917_FinishedCerts` | n/a | "Token Required"; `geoweb.martin.fl.us` reset the connection |

(A "City of Margate Elevation Certificates" layer in the search results centres on lon -74.5, lat 39.3,
i.e. Margate City NJ, and is excluded.)

## Part B. Licences and terms of the inputs

| # | Input | Licence / terms found | Operative text (quoted) | Source (retrieved 2026-10-07) |
|---|---|---|---|---|
| 1a | FDEM public EC layer | **No licence stated**: item `licenseInfo` and `accessInformation` empty, layer `copyrightText` empty | n/a | `arcgis.com/sharing/rest/content/items/92fb38b201e0440c83a959970b194973?f=json` |
| 1b | FDEM EC portal | Disclaimer only | "The Florida Division of Emergency Management makes no warranties or representations to the accuracy of Elevation Certificates available through this website." | `https://www.floridadisaster.org/elevation-certificates/` |
| 1c | Forerunner (hosts the portal and every PDF URL) | Terms of Use, "Last Updated: September 4, 2025" | "These Terms govern your access to and use of our website, https://www.withforerunner.com (the "Site") along with any other products or services offered by us, whether through the Site or otherwise". "Forerunner grants you a limited, non-exclusive, revocable right to access and use the Services solely for your internal, non commercial purposes. You may not resell, transfer, assign, or sublicense your rights under these Terms to any third party or use the Services to run an outsourcing business or provide services for the benefit of any third party." Whether these terms bind a member of the public reading `florida.withforerunner.com` is *unverified*. | `https://withforerunner.com/terms-of-use` |
| 1d | Florida public records (applies to records held by FDEM, counties, DOR) | Case law | "We hold that Skinner has no authority to assert copyright protection in the GIS maps, which are public records." "Since 1905, it has been clear that public records may be used in a commercial, profit-making business without the payment of additional fees." "Florida's Constitution and its statutes do not permit public records to be copyrighted unless the legislature specifically states they can be." (Microdecisions, Inc. v. Skinner, 889 So. 2d 871, Fla. 2d DCA 2004). Whether this reaches surveyor-authored EC PDFs (prepared by private surveyors, then filed with an agency) is *unverified*. | `https://cases.justia.com/florida/second-district-court-of-appeal/2D03-3346.pdf` |
| 2 | Florida DOR NAL and parcel shapefiles | **No licence or redistribution clause found** on the portal pages or in `parcel shapefiles readme.pdf` (2026-02-10) | "The Department of Revenue publishes assessment rolls in compliance with chapter 119, Florida Statutes. The files publicly available through the Department and county property appraisers do not contain confidential records, such as social security numbers and the records of property owners exempt from public records disclosure under section 119.071, Florida Statutes". Commercial use: see 1d. Overture lists Florida county address sources (several "data from Florida Department of Revenue") as "Available under Public domain by judicial decision." | `https://floridarevenue.com/property/Pages/DataPortal_RequestAssessmentRollGISData.aspx`; `.../dataportal/Documents/PTO Data Portal/Map Data/parcel shapefiles readme.pdf`; `https://docs.overturemaps.org/attribution/` |
| 3a | Overture buildings | **ODbL** | "Buildings — License for theme: ODbL © OpenStreetMap contributors. Available under the Open Database License." Other sources listed: Esri Community Maps (CC BY 4.0), "Global ML Building Footprints. Licensed by Microsoft under the Open Database License", Google Open Buildings (CC BY 4.0), USGS 3DEP. "Because it includes OpenStreetMap data, the buildings theme is published under the ODbL license. This requires that any other source included in the theme also be provided under ODbL or a compatible license". | `https://docs.overturemaps.org/attribution/`; `https://docs.overturemaps.org/guides/buildings/` |
| 3b | Overture addresses | Per source; "The addresses data comes from a variety of sources. All carry permissive open licenses. Some have special terms or require attribution." | Florida counties: "Available under Public domain by judicial decision. Distributed by OpenAddresses." United States NAD: "The National Address Database is licensed under the National Address Database Access and Usage License." | `https://docs.overturemaps.org/attribution/` |
| 3c | ODbL 1.0: Derivative Database vs Produced Work | Licence text | "Derivative Database" – "a database based upon the Database ... This includes, but is not limited to, Extracting or Re-utilising the whole or a Substantial part of the Contents in a new Database." "Produced Work" – "a work (such as an image, audiovisual material, text, or sounds) resulting from using the whole or a Substantial part of the Contents (via a search or other query)". §4.4a: "Any Derivative Database that You Publicly Use must be only under the terms of: i. This License; ii. A later version ...; or iii. A compatible license." §4.4c: "A Derivative Database is Publicly Used and so must comply with Section 4.4. if a Produced Work created from the Derivative Database is Publicly Used." §4.5b: "Using this Database ... to create a Produced Work does not create a Derivative Database for purposes of Section 4.4". §4.5c: "Use of a Derivative Database internally within an organisation is not to the public". §4.3: a Publicly Used Produced Work needs a notice such as "Contains information from DATABASE NAME, which is made available here under the Open Database License (ODbL)." §4.6: whoever Publicly Uses a Derivative Database (or a Produced Work from one) "must also offer to recipients ... a copy in a machine readable form of: a. The entire Derivative Database; or b. A file containing all of the alterations ... or the method of making the alterations". "Substantial" includes "repeated and systematic Extraction or Re-utilisation of insubstantial parts". | `https://opendatacommons.org/licenses/odbl/1-0/` |
| 3d | OSMF guidelines on combining non-OSM data (OSM is the ODbL licensor inside Overture buildings) | Collective Database Guideline (endorsed 2016-06-17) | Combination is a Collective Database (no share-alike for the non-OSM data) when "the non-OSM and OSM datasets do not reference each other", or when "a non-OSM database replaces or adds a property of a primary feature, and uses either all OSM data or no OSM data for that property of that primary feature within the same regional cut". "a reference between non-OSM and OSM data can be by a database key or any other method of identifying a specific OSM or non-OSM element that may be used with a database join." Horizontal Map Layers Guideline (2014-06-06) covers Produced Works (maps) only. | `https://osmfoundation.org/wiki/Licence/Community_Guidelines/Collective_Database_Guideline_Guideline`; `.../Horizontal_Map_Layers_-_Guideline` |
| 4 | Geocodio results | Terms of Use §8.4, §7.1 | "Customer may store, transmit, transform, sell, and otherwise use the results provided by the Company as Customer sees fit during and beyond the Term of this Agreement, provided that such uses are permitted by the underlying Data Sources and applicable law. ... Customer understands and agrees that Customer is ultimately responsible for understanding the licenses of underlying Data Sources and providing attribution where required". §7.1 forbids e.g. "service bureau or time-sharing purposes" and accessing the System "to build a competitive product or service". Data sources page: "We return the source information with all of our results." and lists "OpenStreetMap © OpenStreetMap contributors under ODbL", "OpenAddresses data is under various licenses", "TIGER/Line Data and US Census Data are U.S. Government works in the public domain". | `https://www.geocod.io/terms-of-use`; `https://www.geocod.io/data-sources/` |
| 5 | USGS 3DEP lidar | Public domain | "USGS-authored or produced data and information are considered to be in the U.S. Public Domain." Pinellas 2018 lidar vendor metadata: `accconst` "No restrictions apply to these data."; `useconst` "None. ... Acknowledgement of the U.S. Geological Survey would be appreciated for products derived from these data."; vertical datum "North American Vertical Datum of 1988, Geoid 12B", units "U.S. Survey Feet". | `https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits`; `https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/metadata/FL_Peninsular_2018_D18/FL_Peninsular_Pinellas_2018/reports/vendor_provided_xml/Pinellas_Classified.xml` |
| 6 | FEMA NFHL | FEMA site policy; NFHL service metadata carries no licence (`copyrightText`, `licenseInfo` empty) | "Most material on FEMA.gov is free of copyright and may be copied and distributed without permission." NFHL page: "The NFHL can also be used in place of the FIRM for NFIP purposes with appropriate care." | `https://www.fema.gov/about/website-information`; `https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer`; `https://www.fema.gov/flood-maps/national-flood-hazard-layer` |
| 7 | USACE NSI 2022 | **No licence or terms-of-use text found** in the 2022 technical documentation; the NSI API host (`nsi.sec.usace.army.mil`) and the downloader (`nsidownloader.hecdev.net`) returned HTTP 403 from this environment | "The NSI attributes available to the general public are: ..." and "The NSI restricts access to certain fields to Federal users." Inputs listed include CoreLogic, Lightbox parcel data and InfoGroup/Esri business data; `found_ht` "Describes the foundation height of the structure in feet from the ground elevation"; `ground_elv` "Ground elevation (in feet, NAVD88)". A 2026 NSI release also exists ("2026 (latest)"), whose documentation says "individual structure records may contain errors in location, occupancy type, ... foundation type, foundation height". | `https://www.hec.usace.army.mil/confluence/nsi/technicalreferences/2022/technical-documentation`; `.../technicalreferences/latest/technical-documentation` |

## Decisions these findings force

1. **FDEM EC PDFs and fields: rights path not settled.** The layer has no licence, and every PDF URL
   is served by Forerunner, whose terms grant use "solely for your internal, non commercial purposes"
   for its "Services". The certificates are records filed with FDEM under s. 472.0366, and Florida
   case law bars agencies from restricting commercial use of public records. Before any EC-derived
   value is sold, someone must decide whether to rely on the Forerunner-hosted copies or to get the
   records from FDEM directly under chapter 119. A legal read is also needed on whether
   surveyor-authored PDFs are agency records free of copyright.
2. **Owner names must be dropped at ingest.** `buildingOwnerName` is filled on 175,106 FDEM records.
   Pinellas `A1_BUILDING_OWNER`, Nassau `buildingownername` and Miami-Dade `facilityName` carry
   names too, as do the PDFs themselves (FEMA form A1). This matches the CLAUDE.md rule.
3. **Local EC sources add PDFs, mostly scans.** Local counts against FDEM's count for the same
   county: Miami-Dade 112,016 documents vs 14,948; Charlotte 36,889 linked PDFs vs 14,417; Collier
   32,630 vs 14,266; Pinellas 19,382 vs 11,222; Sarasota 6,478 PDFs vs 10,495. In Miami-Dade,
   100,546 of the 112,016 documents are dated before 2020 (sum of the date bins up to 2015-19),
   i.e. before the 2023 statewide submission rule; other counties' dates were not measured.
   Overlap with FDEM was not measured. Of the 31 local PDFs sampled across 10 sources, 27 were
   image-only on page 1, and 5 of the 8 Miami-Dade files sampled were TIFF, so using them needs OCR
   or form reading. Charlotte, Pinellas, Monroe, Key West and Orange already publish typed floor and
   grade values. None of these layers states a licence.
4. **Overture building footprints and IDs cannot go into a sold building table without accepting
   ODbL obligations, unless the Collective Database route holds.** Extracting all or a Substantial
   part of the footprints, or keying our rows to them, makes a Derivative Database. Publicly using
   it (a sold file or API, §4.4c) requires licensing that database under ODbL or a compatible
   licence (§4.4a) and offering the database or the alteration method (§4.6). A map or report image
   is a Produced Work and needs only the §4.3 notice. Internal use is exempt (§4.5c). The OSMF
   Collective Database Guideline gives a way out when an added property "uses ... no OSM data for
   that property"; whether an FFE estimate computed from an OSM-sourced footprint (area, shape,
   location) counts as using no OSM data is not answered by the text and needs a legal read.
   Microsoft ML footprints in Overture are separately ODbL; Esri and Google Open Buildings
   footprints are CC BY 4.0.
5. **Overture addresses for Florida are not share-alike.** Florida county sources are listed as
   "Public domain by judicial decision". The US NAD source has its own licence, to be read before
   use.
6. **Geocodio results may be stored and sold, but each result inherits its source licence.** §8.4
   makes the customer responsible for upstream licences. Geocodio returns the source with every
   result, so the source must be stored per row; OSM-sourced (ODbL) geocodes need the same handling
   as item 4.
7. **3DEP and NFHL are clear for commercial reuse,** with attribution requested by USGS and
   "appreciated" by FEMA. Datum detail matters: the Pinellas 2018 lidar is NAVD88 on GEOID12B in
   US survey feet, so the geoid model must be recorded per value. The FDEM EC layer is 17.6% NGVD29
   (37,164 records), so those values need a datum conversion before comparison.
8. **NSI 2022 cannot be marked licence-clean yet.** No terms were found. Its public fields are built
   partly from licensed commercial inputs (CoreLogic, Lightbox, InfoGroup), and the official access
   points were unreachable from here. NSI-derived values (e.g. `found_ht`) should not ship in a sold
   file until USACE terms are confirmed. A 2026 NSI release exists and should be weighed against
   2022.
9. **Florida DOR NAL: no licence text exists to quote.** Commercial reuse rests on chapter 119 and
   Microdecisions (1d), not on a DOR licence. Owner and mailing columns must be dropped at ingest.
