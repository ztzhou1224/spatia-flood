"""Prepare a lidar feature run for job.py: buildings, tile list, code, and the presigned URLs the box uses.

Buildings: spatia-data overture_buildings (R2) whose centroid lies in the county risk area
(data/flood_v1/risk_<FIPS>.parquet, risk_area.py), or in --bbox for a trial. Tiles: USGS TNM products API, the
named lidar project only (LPC tiles and its 1 m DEM tiles) whose bounding box touches the area.
Outputs under data/flood_v1/lidar/<RUN>/: buildings.parquet (building_id, wkb in CRS84), tiles.json, urls.json
(presigned R2 URLs, valid 7 days: capability links, never printed, never committed).
R2 layout: _flood/lidar/<RUN>/{inputs/buildings.parquet, inputs/tiles.json, inputs/code.tgz,
out/features.parquet, out/meta.json, out/status.json, out/log.txt}.
Usage:
  python pipeline/lidar/prepare.py RUN --fips 12103 [--project FL_Peninsular_2018_D18]
  python pipeline/lidar/prepare.py RUN --bbox -82.64,27.78,-82.60,27.84        # trial area
  add --local DIR to write file:// URLs to local tiles in DIR (a test run on this machine; nothing uploaded)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
import time
from pathlib import Path

import boto3
import requests
import shapely
from shapely import wkt as swkt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "phase0"))
from risk_area import BLDG, connect  # noqa: E402

TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"
DATASETS = {"lpc": "Lidar Point Cloud (LPC)", "dem": "Digital Elevation Model (DEM) 1 meter"}
WEEK = 7 * 24 * 3600


def tnm(dataset: str, bbox, area, project: str) -> list[dict]:
    items, off = [], 0
    while True:
        for attempt in range(5):
            try:
                r = requests.get(TNM, params={"datasets": dataset, "bbox": ",".join(map(str, bbox)), "max": 1000,
                                              "offset": off}, timeout=120)
                r.raise_for_status()
                d = r.json()
                break
            except (requests.RequestException, ValueError):
                time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"TNM query failed: {dataset}")
        items += d.get("items", [])
        off += 1000
        if off >= d.get("total", 0):
            break
    out = {}
    for it in items:
        url, bb = it.get("downloadURL") or "", it.get("boundingBox") or {}
        if f"/Projects/{project}/" not in url or not bb:
            continue
        if shapely.box(bb["minX"], bb["minY"], bb["maxX"], bb["maxY"]).intersects(area):
            out[url] = {"url": url, "bytes": it.get("sizeInBytes"), "published": it.get("publicationDate")}
    return sorted(out.values(), key=lambda t: t["url"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--fips")
    ap.add_argument("--bbox")
    ap.add_argument("--project", default="FL_Peninsular_2018_D18")
    ap.add_argument("--local")
    a = ap.parse_args()
    out = ROOT / "data" / "flood_v1" / "lidar" / a.run
    out.mkdir(parents=True, exist_ok=True)
    c, b = connect()
    if a.bbox:
        x0, y0, x1, y1 = map(float, a.bbox.split(","))
        c.execute(f"CREATE TABLE area AS SELECT ST_MakeEnvelope({x0}, {y0}, {x1}, {y1}) AS geom")
    else:
        c.execute(f"CREATE TABLE area AS SELECT geom FROM read_parquet('{ROOT}/data/flood_v1/risk_{a.fips}.parquet')")
    x0, y0, x1, y1, wkt = c.execute(
        "SELECT ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom), ST_AsText(geom) FROM area").fetchone()
    t0 = time.time()
    bl = c.execute(f"""SELECT b.id AS building_id, ST_AsWKB(b.geom) AS wkb FROM read_parquet('{b}/{BLDG}') b, area
                       WHERE b.lon BETWEEN {x0} AND {x1} AND b.lat BETWEEN {y0} AND {y1}
                         AND ST_Intersects(area.geom, ST_Point(b.lon, b.lat))""").df()
    bl["wkb"] = bl.wkb.map(bytes)
    bl.to_parquet(out / "buildings.parquet", index=False)
    area = swkt.loads(wkt)
    tiles = {k: tnm(v, (x0, y0, x1, y1), area, a.project) for k, v in DATASETS.items()}
    tiles["project"] = a.project
    (out / "tiles.json").write_text(json.dumps(tiles, indent=1))
    gb = sum(t["bytes"] or 0 for t in tiles["lpc"] + tiles["dem"]) / 1e9
    print(f"{a.run}: {len(bl)} buildings ({time.time() - t0:.0f} s); {len(tiles['lpc'])} LPC + {len(tiles['dem'])} "
          f"DEM tiles of {a.project}, {gb:.1f} GB")

    if a.local:
        loc = Path(a.local).resolve()
        for k in ("lpc", "dem"):
            for t in tiles[k]:
                p = loc / k / t["url"].rsplit("/", 1)[1]
                t["url"] = f"file://{p}"
        tiles["lpc"] = [t for t in tiles["lpc"] if Path(t["url"][7:]).exists()]
        tiles["dem"] = [t for t in tiles["dem"] if Path(t["url"][7:]).exists()]
        (out / "tiles_local.json").write_text(json.dumps(tiles, indent=1))
        urls = {"buildings": f"file://{out / 'buildings.parquet'}", "tiles": f"file://{out / 'tiles_local.json'}"}
        urls |= {k: f"file://{out / ('out_' + f)}" for k, f in
                 (("features", "features.parquet"), ("meta", "meta.json"), ("status", "status.json"), ("log", "log.txt"))}
        (out / "urls.json").write_text(json.dumps(urls))
        print(f"local run: {len(tiles['lpc'])} LPC + {len(tiles['dem'])} DEM tiles found in {loc}")
        return

    s3 = boto3.client("s3", endpoint_url=os.environ["CLOUDFLARE_R2_ENDPOINT"], region_name="auto",
                      aws_access_key_id=os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"])
    bucket, pre = os.environ["CLOUDFLARE_R2_BUCKET"], f"_flood/lidar/{a.run}"
    code = io.BytesIO()
    with tarfile.open(fileobj=code, mode="w:gz") as tar:
        for f in ("features.py", "job.py", "run.sh"):
            tar.add(Path(__file__).parent / f, arcname=f)
    s3.put_object(Bucket=bucket, Key=f"{pre}/inputs/code.tgz", Body=code.getvalue())
    s3.upload_file(str(out / "buildings.parquet"), bucket, f"{pre}/inputs/buildings.parquet")
    s3.upload_file(str(out / "tiles.json"), bucket, f"{pre}/inputs/tiles.json")

    def sign(op: str, key: str) -> str:
        return s3.generate_presigned_url(op, Params={"Bucket": bucket, "Key": f"{pre}/{key}"}, ExpiresIn=WEEK)
    urls = {"code": sign("get_object", "inputs/code.tgz"), "buildings": sign("get_object", "inputs/buildings.parquet"),
            "tiles": sign("get_object", "inputs/tiles.json")}
    urls |= {k: sign("put_object", f"out/{f}") for k, f in
             (("features", "features.parquet"), ("meta", "meta.json"), ("status", "status.json"), ("log", "log.txt"))}
    p = out / "urls.json"
    p.write_text(json.dumps(urls))
    p.chmod(0o600)
    print(f"uploaded inputs to r2:{pre}/inputs/; presigned URLs (7 days) in {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
