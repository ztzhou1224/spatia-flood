"""Export the assembled county for the internal viewer (plan docs/04 §1, decision 16 / 18; owner 2026-10-07).

From data/flood_v1/assemble/: buildings_<FIPS>.parquet, coverage_<FIPS>_r8.parquet, and the county card
(pipeline/assemble/out/coverage_<FIPS>.json). Buildings are split by the H3 cell (resolution CHUNK_RES) of their
centroid into two files per cell: geo/<cell>.json (GeoJSON footprints with the few fields the map styles on) and
rec/<cell>.json (every column of every building, keyed by building_id, for the click-through record). Plus
index.json (cells with their bounding boxes and counts), coverage.json (coverage cells, GeoJSON), county.json.
Written to data/flood_v1/viewer/<FIPS>/<release>/ and uploaded to R2 _flood/viewer/<FIPS>/<release>/ (private
bucket; the viewer Worker reads it server-side). Nothing here is public.
Usage: python pipeline/viewer/export.py 12103 --release pinellas-r0 [--no-upload]
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
from pathlib import Path

import boto3
import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import shapely

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "flood_v1" / "assemble"
CHUNK_RES = 7
MAP_FIELDS = ["building_id", "bfe_call", "ffh_class", "ffh_ft", "floor_minus_bfe_ft", "touches_sfha", "in_risk_area",
              "zone_main"]


def clean(v, nd: int = 3):
    """JSON-safe value; floats rounded to nd decimals (3: 0.001 ft; coordinates use 6)."""
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else round(float(v), nd)
    if isinstance(v, float):
        return round(v, nd)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, np.ndarray):
        return [clean(x) for x in v.tolist()]
    if isinstance(v, list):
        return [clean(x) for x in v]
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if v is pd.NA or v is pd.NaT:
        return None
    return v


def coords(g) -> dict:
    return json.loads(shapely.to_geojson(shapely.set_precision(g, 1e-6)))


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps(obj, separators=(",", ":")).encode(), 6))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("--release", required=True)
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    out = ROOT / "data" / "flood_v1" / "viewer" / a.fips / a.release
    b = gpd.read_parquet(SRC / f"buildings_{a.fips}.parquet")
    b["chunk"] = [h3.latlng_to_cell(la, lo, CHUNK_RES) for la, lo in zip(b.lat, b.lon, strict=True)]
    cols = [c for c in b.columns if c not in ("geometry", "chunk")]
    index = []
    for cell, g in b.groupby("chunk"):
        feats = [{"type": "Feature", "id": i, "geometry": coords(geom),
                  "properties": {k: clean(r[k]) for k in MAP_FIELDS}}
                 for i, (geom, (_, r)) in enumerate(zip(g.geometry.values, g[MAP_FIELDS].iterrows(), strict=True))]
        write(out / "geo" / f"{cell}.json", {"type": "FeatureCollection", "features": feats})
        recs = {r["building_id"]: {k: clean(r[k], 6 if k in ("lon", "lat") else 3) for k in cols}
                for r in g[cols].to_dict("records")}
        write(out / "rec" / f"{cell}.json", recs)
        x0, y0, x1, y1 = shapely.total_bounds(g.geometry.values)
        index.append({"cell": cell, "bbox": [round(x0, 5), round(y0, 5), round(x1, 5), round(y1, 5)], "n": len(g)})
    cov = gpd.read_parquet(SRC / f"coverage_{a.fips}_r8.parquet")
    cov_feats = [{"type": "Feature", "geometry": coords(geom),
                  "properties": {k: clean(v) for k, v in r.items()}}
                 for geom, r in zip(cov.geometry.values, cov.drop(columns="geometry").to_dict("records"), strict=True)]
    write(out / "coverage.json", {"type": "FeatureCollection", "features": cov_feats})
    county = json.loads((ROOT / "pipeline" / "assemble" / "out" / f"coverage_{a.fips}.json").read_text())
    x0, y0, x1, y1 = shapely.total_bounds(b.geometry.values)
    write(out / "county.json", county | {"bbox": [x0, y0, x1, y1], "chunk_res": CHUNK_RES})
    write(out / "index.json", index)
    files = sorted(p for p in out.rglob("*.json"))
    size = sum(p.stat().st_size for p in files)
    print(f"{len(index)} chunks, {len(files)} files, {size / 1e6:.1f} MB gzip -> {out}")
    if a.no_upload:
        return
    s3 = boto3.client("s3", endpoint_url=os.environ["CLOUDFLARE_R2_ENDPOINT"], region_name="auto",
                      aws_access_key_id=os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"])
    for p in files:
        key = f"_flood/viewer/{a.fips}/{a.release}/{p.relative_to(out).as_posix()}"
        s3.upload_file(str(p), os.environ["CLOUDFLARE_R2_BUCKET"], key,
                       ExtraArgs={"ContentType": "application/json", "ContentEncoding": "gzip"})
    print(f"uploaded {len(files)} files to _flood/viewer/{a.fips}/{a.release}/")


if __name__ == "__main__":
    main()
