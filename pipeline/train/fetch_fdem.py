"""Fetch the FDEM public Elevation Certificate layer statewide (the label and record source; r1 plan docs/09 B2, B3, B5).

Source: FDEM `Public_FDEM_Elevation_Certificates` FeatureServer layer 0 (ArcGIS Online, edited daily; terms: review
docs/07 S3, tag `fdem_certificates:forerunner_internal_noncommercial`). Fields: the elevation, diagram, stage
(`buildingElevationSource`, B2), lowest floor (C2a `topOfBottomFloor`, B3), the enclosure / garage opening fields (the
A8 / A9 equivalents this layer carries, B3), datum, form year, FIRM fields and the point. Never fetched (personal or
free text): buildingOwnerName, certifierName, certifierLicenseNumber, streetAddress, standardizedAddress, zipcode,
city, url, propertyDescription, comments, elevationDatumComments. `propertyId` is fetched only to pick the latest
certificate per property and is dropped by labels.py before anything is written.
Outputs: data/fl/ec_all.json (list of records with lon / lat) and data/fl/ec_all.meta.json (fetch time, layer
lastEditDate, count, fields), both gzipped to R2 _flood/inputs/fdem/<fetch date>/ so a release can name its extract.
Usage: python pipeline/train/fetch_fdem.py [--no-upload]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import gzip
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAYER = ("https://services8.arcgis.com/4L6VuYsPSGSEJ0qe/arcgis/rest/services/"
         "Public_FDEM_Elevation_Certificates/FeatureServer/0")
FIELDS = ["OBJECTID", "propertyId", "issuedAt", "buildingUse", "buildingDiagramNumber", "nfipCommunityNumber",
          "firmMapNumber", "firmSuffix", "firmPanelEffectiveDate", "floodZone", "baseFloodElevation",
          "baseFloodElevationSource", "baseFloodElevationDatum", "buildingElevationSource", "verticalDatum",
          "elevationDatum", "conversionFactorUsed", "formYear", "topOfBottomFloor", "topOfNextHigherFloor",
          "attachedGarage", "lowestAdjacentGrade", "highestAdjacentGrade", "lowestAdjacentGradeType",
          "breakawayWalls", "crawlspaceSqft", "crawlspaceNumFloodOpenings", "crawlspaceNumEngineeredOpenings",
          "attachedGarageSqft", "attachedGarageNumFloodOpenings", "type"]
PAGE = 2000


def get(url: str, params: dict) -> dict:
    q = urllib.parse.urlencode(params)
    err: Exception | None = None
    for _ in range(4):
        try:
            with urllib.request.urlopen(f"{url}?{q}", timeout=120) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:  # noqa: BLE001 - retried, then re-raised
            err = e
    assert err is not None
    raise err


def page(off: int) -> list[dict]:
    d = get(f"{LAYER}/query", {"where": "1=1", "outFields": ",".join(FIELDS), "orderByFields": "OBJECTID",
                               "resultOffset": off, "resultRecordCount": PAGE, "outSR": 4326,
                               "returnGeometry": "true", "f": "json"})
    out = []
    for f in d["features"]:
        a, g = f["attributes"], f.get("geometry") or {}
        pts = g.get("points") or ([[g["x"], g["y"]]] if "x" in g else [])
        a["lon"], a["lat"] = pts[0] if pts else (None, None)
        out.append(a)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    meta_layer = get(LAYER, {"f": "json"})
    names = {f["name"] for f in meta_layer["fields"]}
    missing = [f for f in FIELDS if f not in names]
    assert not missing, f"FDEM layer no longer has {missing}"
    n = get(f"{LAYER}/query", {"where": "1=1", "returnCountOnly": "true", "f": "json"})["count"]
    started = dt.datetime.now(dt.UTC)
    recs: list[dict] = []
    with cf.ThreadPoolExecutor(8) as ex:
        for part in ex.map(page, range(0, n + PAGE, PAGE)):
            recs.extend(part)
    ids = [r["OBJECTID"] for r in recs]
    assert len(set(ids)) == len(ids), "duplicate OBJECTIDs across pages"
    assert len(recs) == n, f"fetched {len(recs)} of {n} (layer edited during the fetch? re-run)"
    last_edit = meta_layer.get("editingInfo", {}).get("lastEditDate")
    meta = {"source": f"{LAYER} (FDEM Public Elevation Certificates)", "fetched_at": started.isoformat(timespec="seconds"),
            "layer_last_edit": dt.datetime.fromtimestamp(last_edit / 1000, dt.UTC).isoformat(timespec="seconds")
            if last_edit else None,
            "count": len(recs), "fields": FIELDS, "licence": "fdem_certificates:forerunner_internal_noncommercial"}
    out = ROOT / "data" / "fl"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ec_all.json").write_text(json.dumps(recs))
    (out / "ec_all.meta.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta | {"fields": len(FIELDS)}, indent=1))
    if a.no_upload:
        return
    import boto3

    s3 = boto3.client("s3", endpoint_url=os.environ["CLOUDFLARE_R2_ENDPOINT"], region_name="auto",
                      aws_access_key_id=os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"])
    prefix = f"_flood/inputs/fdem/{started.date().isoformat()}"
    for name in ("ec_all.json", "ec_all.meta.json"):
        s3.put_object(Bucket=os.environ["CLOUDFLARE_R2_BUCKET"], Key=f"{prefix}/{name}.gz",
                      Body=gzip.compress((out / name).read_bytes(), 6), ContentType="application/json",
                      ContentEncoding="gzip")
    meta["r2_prefix"] = prefix
    (out / "ec_all.meta.json").write_text(json.dumps(meta, indent=1))
    print(f"uploaded to {prefix}/")


if __name__ == "__main__":
    main()
