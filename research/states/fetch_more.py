"""Hampton Roads (VA) elevation certificates + all of Staten Island (BES, NSI, year built, flood zones).

VA: HRPDC / ODU 'Elevation Certificates - Building Footprints (NAVD88)' (geo.hrsd.com), residential only.
    Address, parcel, tax map and value fields are dropped at ingest.
SI: NYC BES (bsin-59hv) borough 5 'Successfully Measured'; NYC BUILDING footprints (5zhs-2jue) BIN + construction
    year; NSI API in 0.01 deg tiles over Staten Island; NFHL flood zones (layer 28) over Staten Island.
Outputs: data/states/{va_ec, si_bes, si_year, si_nsi, si_nfhl}.parquet.  Usage: python fetch_more.py
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests

D = Path(__file__).resolve().parents[2] / "data" / "states"
SI = (-74.26, 40.49, -74.05, 40.65)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "coverage"))
from fetch_nsi import KEEP, get as nsi_get  # noqa: E402


def va():
    u = "https://geo.hrsd.com/hrgeo/rest/services/regionalgis/ElevationCertificatesNAVD88/MapServer/0/query"
    keep = ("OBJECTID,CITY,BLDG_USE,BLDG_DIAGRAM,EC_FLOOD_ZONE,EC_BFE,EC_ELEV_DATUM,TOP_BF,TOP_NHF,LAG,HAG,FFE,FFH,"
            "RESYRBLT,FOUNDATION,STORY,NEW_FLD_ZONE,NEW_STATIC_BFE_88,CURRENT_DATUM,ISSUE_DATE,LAT,LON")
    rows, off = [], 0
    while True:
        r = requests.get(u, params=dict(where="1=1", outFields=keep, returnGeometry="false", resultOffset=off,
                                        resultRecordCount=1000, f="json"), timeout=300).json()
        rows += [f["attributes"] for f in r["features"]]
        if len(r["features"]) < 1000:
            break
        off += 1000
    d = pd.DataFrame(rows)
    d.to_parquet(D / "va_ec.parquet", index=False)
    print(f"VA certificates {len(d)}; use {d.BLDG_USE.value_counts().head(4).to_dict()}; diagrams {d.BLDG_DIAGRAM.value_counts().head(8).to_dict()}")


def soda(ds, params):
    rows, off = [], 0
    while True:
        r = requests.get(f"https://data.cityofnewyork.us/resource/{ds}.json", params={**params, "$limit": 50000, "$offset": off}, timeout=600)
        r.raise_for_status()
        b = r.json(); rows += b
        if len(b) < 50000:
            return pd.DataFrame(rows)
        off += 50000


def si():
    if (D / "si_bes.parquet").exists():
        b = pd.read_parquet(D / "si_bes.parquet")
    else:
        b = soda("bsin-59hv", {"$select": "bin,z_floor,z_grade,subgrade,latitude,longitude",
                               "$where": "borough='5' AND starts_with(notes1,'Property was Successfully Measured')"})
    b.to_parquet(D / "si_bes.parquet", index=False)
    print(f"SI BES measured {len(b)}")
    y = pd.read_parquet(D / "si_year.parquet") if (D / "si_year.parquet").exists() else soda("5zhs-2jue", {"$select": "bin,construction_year", "$where": "bin >= 5000000 AND bin < 6000000"})
    y.to_parquet(D / "si_year.parquet", index=False)
    print(f"SI footprints with BIN {len(y)}")
    if (D / "si_nsi.parquet").exists():
        return nfhl()
    tiles = [(x, yy, min(x + .01, SI[2]), min(yy + .01, SI[3])) for x in np.arange(SI[0], SI[2] - 1e-9, .01)
             for yy in np.arange(SI[1], SI[3] - 1e-9, .01)]
    with ThreadPoolExecutor(6) as ex:
        rows = [f["properties"] for fs in ex.map(nsi_get, tiles) for f in fs]
    n = pd.DataFrame(rows).drop_duplicates("fd_id")
    n[[c for c in KEEP if c in n]].to_parquet(D / "si_nsi.parquet", index=False)
    print(f"SI NSI {len(n)}")
    nfhl()


def nfhl():
    """NFHL MapServer: no pagination, so fetch the object ids, then geometry in batches of 100 ids."""
    import time
    u = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"

    def call(params):
        for a in range(4):
            try:
                r = requests.get(u, params=params, timeout=600).json()
                if "error" not in r:
                    return r
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2 ** a)
        return None
    # no pagination and returnIdsOnly is unreliable: query small tiles (each well under the record cap), dedupe
    feats, seen, failed = [], set(), []

    def tile(b, depth=0):
        r = call(dict(f="geojson", where="1=1", outFields="FLD_AR_ID,FLD_ZONE,STATIC_BFE,V_DATUM", returnGeometry="true",
                      geometry=",".join(map(str, b)), geometryType="esriGeometryEnvelope", inSR=4326, outSR=4326,
                      spatialRel="esriSpatialRelIntersects"))
        if r is None or r.get("exceededTransferLimit"):
            if depth >= 3:
                failed.append(b); return
            x0, y0, x1, y1 = b; xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
            for q in ((x0, y0, xm, ym), (xm, y0, x1, ym), (x0, ym, xm, y1), (xm, ym, x1, y1)):
                tile(q, depth + 1)
            return
        for f in r["features"]:
            k = f["properties"].get("FLD_AR_ID") or json.dumps(f["geometry"])[:200]
            if k not in seen:
                seen.add(k); feats.append(f)
    for x in np.arange(SI[0], SI[2] - 1e-9, .03):
        for y in np.arange(SI[1], SI[3] - 1e-9, .03):
            tile((x, y, min(x + .03, SI[2]), min(y + .03, SI[3])))
    print(f"NFHL tiles that failed after splitting: {len(failed)} {failed[:5]}")
    ids = feats
    z = pd.DataFrame([{"zone": f["properties"]["FLD_ZONE"], "bfe": f["properties"]["STATIC_BFE"], "datum": f["properties"]["V_DATUM"],
                       "gj": json.dumps(f["geometry"])} for f in feats if f["geometry"]])
    z.to_parquet(D / "si_nfhl.parquet", index=False)
    print(f"SI NFHL zones {len(z)} of {len(ids)} ids; datums {z.datum.value_counts().to_dict()}")

if __name__ == "__main__":
    if not (D / "va_ec.parquet").exists():
        va()
    si()
