"""Download FEMA NFIP redacted policies (OpenFEMA NfipPolicies v3) that carry the elevation certificate
numbers (lowest floor and lowest adjacent grade), single-family, policies effective since 2024-01-01.
No address or exact location is published: censusGeoid is the block group, lat/lon are rounded to 0.1 deg.
Renewals are separate rows, so one building can appear 2-3 times.
Usage: python fetch_nfip.py NAME "ODATA_SCOPE"            e.g.  harris "startswith(censusGeoid,'48201')"
       python fetch_nfip.py NAME - COUNTY_FIPS_LIST       one query per county (comma list), cached per county
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
URL = "https://www.fema.gov/api/open/v3/NfipPolicies"
COLS = ("id,censusGeoid,propertyState,latitude,longitude,policyEffectiveDate,occupancyType,buildingDescriptionCode,"
        "lowestFloorElevation,lowestAdjacentGrade,baseFloodElevation,elevationDifference,foundationType,"
        "elevatedBuildingIndicator,basementEnclosureCrawlspaceType,numberOfFloorsInInsuredBuilding,"
        "originalConstructionDate,postFIRMConstructionIndicator,ratedFloodZone,floodZoneCurrent,elevationCertificateIndicator")
BASE = ("policyEffectiveDate ge '2024-01-01' and lowestFloorElevation ne null and lowestAdjacentGrade ne null "
        "and (occupancyType eq 1 or occupancyType eq 11)")


def page(flt, skip):
    for _ in range(6):
        try:
            r = requests.get(URL, params={"$filter": flt, "$select": COLS, "$top": 10000, "$skip": skip, "$orderby": "id",
                                          "$metadata": "off", "$format": "json"}, timeout=300)
            r.raise_for_status()
            return r.json()["NfipPolicies"]
        except Exception as e:  # noqa: BLE001
            print("retry", skip, e, flush=True)
    raise RuntimeError(f"page {skip} failed")


def fetch(flt, cache=None):
    if cache is not None and cache.exists():
        return pd.read_parquet(cache).to_dict("records")
    n = requests.get(URL, params={"$filter": flt, "$select": "id", "$top": 1, "$count": "true"}, timeout=300).json()["metadata"]["count"]
    rows = [r for s in range(0, n, 10000) for r in page(flt, s)]
    if cache is not None:
        cache.parent.mkdir(exist_ok=True)
        pd.DataFrame(rows).to_parquet(cache)
        print(f"  {cache.stem}: {len(rows)} of {n}", flush=True)
    return rows


def main(name, scope, counties=None):
    if counties:
        jobs = [(f"startswith(censusGeoid,'{c}') and {BASE}", ROOT / "data" / "nfip" / "parts" / f"{name}_{c}.parquet")
                for c in counties.split(",")]
    else:
        jobs = [(f"{scope} and {BASE}", None)]
    with ThreadPoolExecutor(4) as ex:
        parts = list(ex.map(lambda j: fetch(*j), jobs))
    d = pd.DataFrame([r for p in parts for r in p]).drop_duplicates("id")
    out = ROOT / "data" / "nfip" / f"{name}.parquet"
    d.to_parquet(out)
    print(f"{name}: saved {len(d)} rows from {len(jobs)} queries to {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
