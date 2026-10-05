# Imagery that can show a first floor: sources, coverage and licences (2026-10-05)

The question: besides Mapillary and Bee Maps, what imagery shows a house's front door, steps, piers or
foundation, and which of it may we (a) run ML on, (b) use to sell per-building floor heights to third
parties, (c) under what attribution or share-alike terms. Every licence quote below was read from the
document named in its URL on 2026-10-05, unless marked *unverified*. "Search snippet" means the claim comes
from a web-search summary and the underlying page could not be opened (403, or redirected).

Rules that frame this note: CLAUDE.md (no Google Street View; Mapillary CC BY-SA; Bee Maps paid and
internal-use; tag `provider=beemaps`) and `docs/03-product-b2b.md` §5 (selling data is redistribution, so
every input needs a licence check). The image-method patents in `02-floor-height-methods.md` apply to every
source here.

## Summary

| Source | Type | Angle / resolution | Access & price | Harris (Clear Lake) | ML? / sell derived values? | Verdict |
|---|---|---|---|---|---|---|
| **EagleView (Pictometry)** | oblique aerial | ~45°, "3in GSD or better" (county order) | contract (per-county orders; price lines not cleanly readable in the PDF we opened) | not established; no HCAD/H-GAC contract found | standard licence: no automated access, no resale | blocked without a custom data licence |
| **Nearmap** | oblique + vertical aerial | 45° obliques; 5.5 cm vertical | subscription + API | US captures since 2014; Houston *unverified* | MSA bans ML and model training outright | blocked under standard terms |
| **Vexcel** | oblique + ortho aerial (UltraCam) | 45°, 4 directions, 7.5 cm urban | Data Program via resellers / API | "95% US population" plan; Houston *unverified* | ML only in a private instance; derived values "Internal Use" only | blocked for resale under standard EULA; best candidate to negotiate |
| **HxGN Content Program (Leica CityMapper-2)** | oblique + nadir + lidar | 4 obliques, avg 6.7 cm | per-area purchase | Metro HD city list not public; Houston *unverified* | EUAA forbids deriving products for sale "without a license specifically authorizing it" | blocked under standard terms; negotiable |
| **Cyclomedia** | street-level 360° + mobile lidar | 360° panoramas every ~5 m | SaaS / quote | captured Harris County (the answer key's source) | SaaS terms forbid commercial "systematic extraction" | blocked, and it is the answer key's source anyway |
| **USGS coastal oblique photos** | storm oblique aerial (handheld) | ~500 ft altitude, ~1,200 ft offshore | free download | open-coast Texas (Ike 2008, Galveston/Bolivar); not Clear Lake | US federal work; USGS asks for acknowledgment | clear, but beach-front only and too far away |
| **NOAA Emergency Response Imagery** | post-storm aerial, ortho-rectified | 15–30 cm GSD (Helene) | free, AWS bucket | Harvey 2017 collection exists | CC0 | clear, but near-vertical: not useful for floor height |
| **Civil Air Patrol (FEMA)** | post-disaster handheld oblique | variable | free (FEMA S3, HydroShare copy) | Harvey 2017, ~30 k photos SE Texas (HydroShare) | HydroShare copy says CC BY 4.0; source licence *unverified* | usable for QA/flood evidence, not systematic |
| **Panoramax** | street-level (crowd) | per contributor | free API | **256 pictures** in Clear Lake bbox, 2024-05 → 2025-08 | CC BY-SA 4.0 (same question as Mapillary) | small, same share-alike issue as Mapillary |
| **KartaView** | street-level (crowd) | phone/dashcam | free API | photos in 12 of 19 probed 2 km cells; dates seen 2017–2021 | CC BY-SA 4.0 | old, sparse, share-alike |
| **Apple Look Around** | street-level 360° | n/a | MapKit only | n/a | terms ban extraction, derived databases and "training of any model" | blocked |
| **Bing Streetside / Bird's Eye** | street-level / oblique | n/a | removed from Bing Maps | n/a | Bird's Eye "never a permissible source for OSM" | gone |
| **Maxar/Vantor Open Data, OpenAerialMap** | satellite | 0.39–0.78 m GSD near Clear Lake | free | 15 OAM scenes, all satellite | CC BY-NC 4.0 (Maxar); some CC BY 4.0 | too coarse; NC blocks resale |
| **H-GAC regional imagery** | ortho (nadir) | 6 in / 12 in, 4-band | cost-share purchase | yes (13 counties) | no redistribution without H-GAC consent (search snippet) | nadir only; not useful |
| **Zillow / Redfin / MLS photos** | listing photos | n/a | n/a | n/a | terms ban scraping, data mining, commercial use | blocked |

**Bottom line:** no oblique or street-level source we found has standard terms that let us run ML **and**
sell the per-building results. The open ones (USGS, NOAA, CAP) are licence-clean but either near-vertical,
beach-front only, or ad hoc. The commercial oblique vendors all restrict use to the licensee's "internal use",
and Nearmap's MSA also bans ML outright. Oblique aerial can only enter the product through a **negotiated
derived-data licence**, and Vexcel and Hexagon are the vendors whose documents expect that kind of deal.

## Per-source notes

### Commercial oblique aerial

**EagleView / Pictometry.** 45° four-direction obliques. Sumter County FL's 2025 order (LC-10009857) describes
"Reveal Essentials+ Property … measurable oblique and orthogonal imagery … collected at 3in GSD or better"
(the price lines did not extract cleanly from the PDF, so no price is quoted here).
Source: https://www.sumtercountyfl.gov/AgendaCenter/ViewFile/Item/25871?fileID=65436. Its licence terms
(B.I, Restrictions) decide the question:
> "v. You may not offer any part of the Content or Services for commercial resale or commercial redistribution
> in any medium." … "vii. … you may not access such Content or Services (or both) via mechanical,
> programmatic, robotic, scripted or any other automated means. Unless otherwise agreed by EagleView in
> writing, use of such Content and Services is permitted only via manually conducted, discrete,
> human­initiated individual search and retrieval activities."

The online-services grant is "solely for your internal business purposes and not for resale or
redistribution". The terms also forbid making Content available "to Google or its affiliates". County
appraisers show EagleView obliques publicly: Brevard County FL's viewer says "Doors and windows are also
visible because the imagery is taken from an angle"
(https://www.bcpao.us/Docs/misc/Instructions_Picto.pdf). Those viewers are still under the county's licence,
so scraping them is excluded. The website terms (https://www.eagleview.com/terms/) are "internal use only".
The developer Imagery API (https://developer.eagleview.com/documentation) has a trial (search snippet), but
its terms were not read: *unverified*. **Harris County:** no HCAD, H-GAC or Harris County contract with EagleView
was found, so whether one exists is *unverified* (HCAD's public GIS service folders at
`gis.hctx.net/arcgis/rest/services` list no imagery service).

**Nearmap.** 45° obliques in each cardinal direction, plus 5.5 cm vertical imagery. It "regularly capture[s]
urban and regional areas across … the United States … multiple times a year", with "United States image
captures beg[inning] in 2014" (https://help.nearmap.com/kb/articles/105-about-nearmap-content). Houston
coverage was not checked, because the coverage API needs a key: *unverified*. The Master Subscription Agreement
(https://www.nearmap.com/legal/master-subscription-agreement), §2.5, decides it:
> "(f) create an internal or commercial imagery dataset or Derivative Works composed principally of the
> Nearmap Data; … (h) use the Products for the purpose of product development, tuning, training, or
> modification of internal models, generation of aggregated analysis, or creation of data elements related to
> the Products; … (r) utilize any machine learning products, including any open-source products, computer
> vision, large language models, or vision-language models, in connection with the use of the Products"

The only ML carve-out (Product-Specific Terms, "ArcGIS Image Permitted ML") covers **vertical** imagery only,
"for internal use by the Customer". It also bars sharing the outputs: "Share, publish, or otherwise distribute
Permitted ML Outputs" and "Use the Permitted ML Outputs for any commercial … purpose"
(https://www.nearmap.com/legal/product-specific-terms). **Verdict: the worst fit; it bans the method itself.**

**Vexcel.** Four-direction 45° obliques. US collection is "Urban areas: 7.5cm resolution (up to 2 collections
yearly)" and "Wide areas: 15cm", with a library back to 2012
(https://vexceldata.com/countries/united-states/us-collection/). The page names no metro areas, so Houston is
*unverified*. EULA, September 2025 version
(https://vexceldata.com/wp-content/uploads/2025/10/2025.09-EULA-for-vexceldata.pdf):
> "“Derivatives” means works that are created by analyzing the Product and extracting features and
> attributes from the Product, specifically excluding (a) any portion of the images or pixels themselves" …
> "“Commercial Purpose” means redistribution, retransmission, or publication for the benefit of a third
> party, regardless of whether it is done in exchange for a fee" … 2.1 licence to "create Derivatives,
> provided that in all cases of (a)-(c) such use is solely for Licensee’s Internal Use as described in any
> Customer Agreement" … "but in any case no broader than the following"
> 2.2(c) "If … Licensee inputs any Product … into any type of artificial intelligence program that is
> “trained” on information submitted, Licensee may only do so in a private instance of such program"

The EULA also says not to store Product "for more than one week after downloading", requires the notice
"Vexcel Imaging US Inc. © [YEAR]" on all Derivatives, and says all Derivatives are destroyed at termination.
So ML is allowed (in a private instance), and a floor height is exactly a "Derivative". Selling it is a
"Commercial Purpose", which the standard EULA caps out ("no broader than"). We would need a separate
agreement. **Verdict: the most compatible standard terms. Ask for a derived-data / resale licence.**

**HxGN Content Program (Hexagon / Leica CityMapper-2).** One nadir and four obliques per exposure, obliques "on
average 6.7 cm" (https://docs.hxgncontent.com/hxgn-content-program-resources/Latest-version/metro-hd-data-sets).
Metro HD US cities named in 2021 were Dallas and New York (search snippet). Houston, NC and FL are
*unverified*. End User Access Agreement V20240101
(https://bynder.hexagon.com/m/6ddf50a65e636e4f/original/End-User-Access-Agreement-HxGN-Content-Program.pdf):
> "The Authorized End User shall not use any part of the Geospatial Data or the Services to develop or derive
> any other product or service for distribution, disclosure, or commercial sale, whether by hardcopy, digital
> medium or web service, without a license specifically authorizing it to do so"

There is no ML clause in the EUAA or the AUP. The clause says a specific licence can authorise derived
products, so this is negotiable.

**Maxar / Airbus satellite (off-nadir).** Very-high-resolution satellite is about 30–50 cm at best. The 15
OpenAerialMap scenes over Clear Lake are 0.39–0.78 m GSD, all satellite (query below). That cannot resolve
steps or a door sill. Vantor (ex-Maxar) Open Data is "Creative Commons BY-NC 4.0"
(https://vantor.com/company/open-data-program). We did not pursue Airbus. **Not useful for FFH.**

### Government and open aerial

**USGS coastal oblique aerial photographs** (St. Petersburg Coastal and Marine Science Center, NACCH). These are
handheld oblique photos flown "at an altitude of 500 feet (152 meters) and approximately 1,200 feet (366
meters) offshore". Collections include post-Matthew Port St. Lucie FL → Kitty Hawk NC 2016
(https://coastal.er.usgs.gov/data-release/doi-F7154F67/), post-Ike 2008 north Texas coast including Galveston
and Bolivar (https://pubs.usgs.gov/ds/0990/), Irene and Isabel in NC, and Ivan in FL
(https://coastal.er.usgs.gov/hurricanes/data/photos.php). The files are JPEG in 5-minute flight segments with
KML. The GPS position is the aircraft's, not the building's. Use constraint (DS 979 metadata,
https://pubs.usgs.gov/ds/0979/html/ds979_metadata.html):
> "Access_Constraints: None Use_Constraints: The U.S. Geological Survey requests to be acknowledged as
> originator of the data in future products or derivative research."

The licence is clean. But the photos are taken from ~1,200 ft offshore and show only the first row of
beachfront buildings, from far away. Clear Lake (inland on Galveston Bay) is not covered. Possible use:
QA or labels for oceanfront piers and stilts in NC and FL.

**NOAA NGS Emergency Response Imagery.** Helene 2024 metadata (InPort 73570): "The ground sample distance (GSD)
for each image is 15 cm to 30 cm", delivered as "ortho-rectified image tiles and raw unprocessed images". It
is licensed "Creative Commons Zero 1.0 Universal Public Domain Dedication (CC0-1.0)"
(https://www.fisheries.noaa.gov/inportserve/waf/noaa/nos/ngs/iso19115/xml/73570.xml). The `noaa-eri-pds`
bucket has `2017_Hurricane_Harvey/`, `2018_Hurricane_Florence/`, `2022_Hurricane_Ian/`,
`2024_Hurricane_Helene/` and `2024_Hurricane_Milton/` (S3 listing below). The metadata does not state the
orientation, but the products are ortho mosaics, so we read it as near-vertical. That makes it a flood-extent
source, not a floor-height source.

**Civil Air Patrol (FEMA).** CAP aircrews take handheld oblique photos for FEMA. FEMA's public bucket
`fema-cap-imagery` lists 227 prefixes under `Images/` (S3 listing below). A HydroShare copy, "Civil Air Patrol -
Harvey Oblique Aerial Photos", has nearly 30,000 photos, mostly 2017-08/09 in southeast Texas, and states "This
resource is shared under the Creative Commons Attribution CC BY"
(https://www.hydroshare.org/resource/85c5f592e347452a84f552f17a9a05c1/). That licence was set by the uploader
(contributor: NAPSG). CAP's own licence for the originals is *unverified*. The photos are ad hoc, low-altitude
and focused on flooding. They may help as flood-depth evidence, but they are not a systematic floor source.

**State and regional programs.** H-GAC's 2024 program is 6-inch and 12-inch, 4-band **orthoimagery** across 13
counties (search snippet, vendor Surdex). Its licence reportedly says "Licensees shall not reproduce or distribute
the Copyrighted Materials to any other parties without the prior written consent of H-GAC" (search snippet;
h-gac.com returned 403 to us). TxGIO/StratMap and NC OneMap are nadir orthoimagery (the NC 911 Board funds 6-inch
on a 4-year cycle, search snippet). We found no statewide oblique program in TX, NC or FL. Nadir orthos cannot
show floor height.

**OpenAerialMap.** Within bbox -95.20,29.45,-95.00,29.65 it returned 15 scenes, all satellite (Maxar CC BY-NC 4.0,
DigitalGlobe CC BY 4.0), with no drone imagery. Not useful.

### Street-level beyond Mapillary and Bee Maps

**Cyclomedia.** 360° panoramas plus mobile lidar. HCFCD's 1,185,614 FFE points (our answer key,
`docs/01-plan-harris-pilot.md`) come from Cyclomedia mobile lidar. A Cyclomedia blog post says Harris County,
the City of Houston, the appraisal district, HCFCD and METRO deployed its street-level imagery (search snippet;
the page now redirects). Licence: Cyclomedia SaaS Licence Agreement, current version
(https://cdn.prod.website-files.com/69bd3518dd960ca00ae76dcc/69e9c27a3b905536131bd435_Cyclomedia-License-Agreement-(SaaS)-Current.pdf),
Use Guidelines:
> "(vi) systematically download the Image Material and/or the Information Products, (vii) use the Image
> Material and/or the Information Products for systematic extraction, inventory, annotation and/or change
> detection of (characteristics of) objects and 'points of interest' (hereinafter "Data Analysis") for
> commercial purposes of any nature whatsoever, including but not limited to … selling … and allowing third
> parties to use (the results of) the Data Analysis for any purpose whatsoever."

**Verdict: blocked.** Measuring from it would also just reproduce the answer key. We found no public Cyclomedia
viewer for Harris County.

**Panoramax** (federated, started by IGN and OSM France). Pictures carry per-picture licences. The query below
over the Clear Lake bbox returned **256 pictures in 4 collections, all CC-BY-SA-4.0, dated 2024-05-15 →
2025-08-11**. A wider Houston bbox (-95.80,29.50,-95.00,30.10) returned 624 pictures in 146 collections, all
CC-BY-SA-4.0. This raises the same share-alike question as Mapillary (§5), and the volume is small.

**KartaView** (Grab). Images are "Creative Commons Attribution-ShareAlike 4.0" per the OSM wiki
(https://wiki.openstreetmap.org/wiki/KartaView, citing kartaview.org/terms §Open Source License; that terms page
is a JS app and was not readable to us). We probed a 5×5 grid of 2 km radii over Clear Lake. 19 probes
answered: 12 had at least one photo and 7 had none. The first photo returned in each cell was dated 2017–2021.
Six probes failed (HTTP 400 or reset). Old and sparse.

**Apple Look Around.** Apple Maps Terms of Use (https://www.apple.com/legal/internet-services/maps/terms-en.html):
"(vi) copy, extract, scrape or reutilize any portion of the Service, including … creation of any databases
based upon data or content provided through the Service, or training of any model". **Blocked.**

**Bing Streetside and Bird's Eye** (Microsoft's oblique layer). These were removed from Bing Maps, reportedly in
October 2025 (search snippets). An OSM moderator notes Bird's Eye "has never been a permissible source for OSM"
(https://community.openstreetmap.org/t/bing-streetside-discontinued/137189). Not available.

**Nexar** (dashcam). It sells CityStream data subscriptions and training datasets (search snippet). Its terms for
licensees were not read: *unverified*. Forward-facing dashcams rarely frame a front door squarely.

**Real-estate photos.** Redfin's Terms of Use (https://www.redfin.com/about/terms-of-use) say the prohibition
"expressly includes "scraping" … "data mining", or any other activity intended to collect, store, re-organize,
summarize, or manipulate any information", and the MLS owns listing data. Zillow
(https://www.zillow.com/z/corp/terms/) bans "automated queries (including screen and database scraping, spiders,
robots, crawlers …)" and limits brokerage information to "personal, non-commercial purposes". **Blocked.** A direct
MLS (e.g. HAR) data licence would be a separate negotiation and has not been explored.

### Where digital-twin cities get their imagery

| City | Street-level / oblique source | Open? |
|---|---|---|
| Helsinki | Reality mesh built from oblique aerial photos (search snippet: ~50,000 obliques, Microsoft/Vexcel Osprey camera, ~7.5 cm). The city page says the models are "based on aerial photographs" (https://www.hel.fi/en/decision-making/information-on-helsinki/maps-and-geospatial-data/helsinki-3d). | Models are "licensed under CC BY 4.0"; the raw obliques are not found as open data |
| Netherlands (Rotterdam et al.) | 3DNL: Cyclomedia with Hexagon, Leica CityMapper-2 oblique + lidar, flown annually, viewed in Cyclomedia Street Smart (https://leica-geosystems.com/case-studies/reality-capture/3dnl-the-netherlands-from-every-angle) | No: "access … through a subscription" |
| Zurich | City mobile-mapping campaign summer 2020 via iNovitas infra3D (search snippet). The 3D city model has been OGD since 2018 (search snippet). | Model open; street imagery *unverified* |
| Singapore | SLA: aerial photos + lidar, plus a vehicle mobile-mapping survey of 5,500 km of roads with 360° panoramas (search snippet, Bentley case study) | No (government) |
| Las Vegas | Cyclomedia street-level imagery + mobile lidar for right-of-way assets, enterprise licence (search snippet) | No |
| Orlando | Unity regional twin; "satellite data from HERE and Nearmap" (search snippet only, not found in the articles we opened) | No |

The pattern: twins buy oblique aerial (Vexcel/Microsoft Osprey, Leica CityMapper, EagleView, Nearmap) and
mobile mapping (Cyclomedia, infra3D, Leica Pegasus-type) under government enterprise licences. They publish
derived **models** (Helsinki, Zurich) as open data, but not the source imagery. The Helsinki-style route
(a public body buys obliques, then publishes derived models CC BY) is the only open route we found. We found no
US equivalent.

## How the counts were made (commands run 2026-10-05)

- Panoramax: `GET https://api.panoramax.xyz/api/search?bbox=-95.20,29.45,-95.00,29.65&limit=1000`, following `next`
  links. We counted features, collections, `rel=license` titles and min/max `properties.datetime`. Same for the
  Houston bbox.
- KartaView: `GET https://api.openstreetcam.org/2.0/photo/?lat={29.50..29.62 step .03}&lng={-95.18..-95.02 step .04}&radius=2000&itemsPerPage=1`
  (the API caps radius at 2000 m; a bbox sequence query timed out).
- OpenAerialMap: `GET https://api.openaerialmap.org/meta?bbox=-95.20,29.45,-95.00,29.65&limit=100`.
- S3 listings: `https://noaa-eri-pds.s3.amazonaws.com/?list-type=2&delimiter=/` and
  `https://fema-cap-imagery.s3.amazonaws.com/?list-type=2&delimiter=/&prefix=Images/`.
- Licence texts: downloaded with curl (PDFs through `pdftotext`) and searched for the clauses quoted.

## Recommended next steps

1. **Vexcel: ask for a trial and a derived-data addendum.** Ask: (a) Is Clear Lake / Harris County in the 7.5 cm
   urban oblique program, and with which vintages? NC Outer Banks and FL Gulf coast too? (b) Will they license
   resale of extracted per-building attributes (floor height, foundation type) as "Derivatives" for a Commercial
   Purpose, with no pixels redistributed, and does that survive termination? The standard EULA says Derivatives
   are destroyed at termination. (c) Can we relax the one-week storage limit for model training? (d) What do
   the price and attribution requirement look like on a resold value?
2. **Hexagon HxGN Content Program: ask for a quote for "a license specifically authorizing"** derived products
   (the EUAA's own words). Ask: Houston, NC and FL Metro HD coverage and dates; oblique GSD at the facade; whether
   the CityMapper lidar is included (it would also give ground and sill heights); price per km².
3. **EagleView: ask the data-licensing / API team, not the government team,** whether a commercial derived-data
   licence exists. The government and website terms forbid automated access and resale. Also ask HCAD by public
   information request whether it licenses obliques and under what terms. That would only tell us the terms; it
   would not grant us use.

In parallel, at no cost: pull the USGS NC/FL oblique sets and CAP Harvey photos as a **QA and label source**
(public domain or CC BY) for elevated and pier foundations. Skip Nearmap, Cyclomedia, Apple, Zillow/Redfin and
Maxar Open Data for anything that will be sold. Panoramax and KartaView join Mapillary in the CC BY-SA bucket
that needs the lawyer's share-alike answer (§5).
