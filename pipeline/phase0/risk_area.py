"""Phase 0: the risk area of one Florida county and what lies in it (docs/04-plan-flood-layer-v1.md, decision 5).

Risk area = (SFHA [sfha_tf = 'T'] UNION 0.2% annual chance zone [zone_subty contains '0.2']) buffered 500 m,
clipped to the county. Polygons: spatia-data fema_flood_zones (state=FL partition on R2, read remotely with
DuckDB; row bbox columns prune the read). The buffer is computed in EPSG:3086 (Florida GDL Albers, metres),
source tag 'EPSG:4326' with always_xy (CLAUDE.md); areas in km2 in EPSG:3086.
Counts inside the risk area: Overture buildings (spatia-data overture_buildings, footprint centroid lon / lat),
NSI 2022 structures, FDEM certificates (residential, NAVD88, latest per property), and USGS LPC tiles whose
bounding box touches the risk area, per lidar project (TNM API).
Output: pipeline/phase0/out/risk_<FIPS>.json; data/flood_v1/risk_<FIPS>.parquet (the risk polygon, CRS84).
Usage: python pipeline/phase0/risk_area.py 12103
"""
import json
import os
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
DATA = ROOT / "data" / "flood_v1"
ZONES = "layers/national/fema_flood_zones@20260930T082454Z-9c7789f1/current/state=FL/data.parquet"
BLDG = "layers/national/overture_buildings.parquet"


def connect():
    c = duckdb.connect()
    c.execute("LOAD spatial; LOAD httpfs")
    ep = os.environ["CLOUDFLARE_R2_ENDPOINT"].replace("https://", "")
    c.execute(f"""CREATE SECRET r2 (TYPE S3, KEY_ID '{os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"]}',
                  SECRET '{os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"]}', ENDPOINT '{ep}', URL_STYLE 'path', REGION 'auto')""")
    return c, f"s3://{os.environ['CLOUDFLARE_R2_BUCKET']}"


def lidar_tiles(bbox, risk_wkt):
    import shapely
    from shapely import wkt as swkt
    risk = swkt.loads(risk_wkt)
    items, off = [], 0
    while True:
        for attempt in range(4):
            try:
                r = requests.get("https://tnmaccess.nationalmap.gov/api/v1/products",
                                 params={"datasets": "Lidar Point Cloud (LPC)", "bbox": ",".join(map(str, bbox)),
                                         "max": 1000, "offset": off}, timeout=120)
                r.raise_for_status()
                d = r.json()
                break
            except Exception:  # noqa: BLE001
                time.sleep(2 ** attempt)
        else:
            raise RuntimeError("TNM query failed")
        items += d.get("items", [])
        off += 1000
        if off >= d.get("total", 0):
            break
    rows = []
    for it in items:
        bb = it.get("boundingBox") or {}
        if not bb:
            continue
        box = shapely.box(bb["minX"], bb["minY"], bb["maxX"], bb["maxY"])
        if not box.intersects(risk):
            continue
        url = it.get("downloadURL") or ""
        rows.append({"project": url.split("/Projects/")[1].split("/")[0] if "/Projects/" in url else "other",
                     "bytes": it.get("sizeInBytes") or 0, "pub_date": it.get("publicationDate")})
    t = pd.DataFrame(rows)
    return t.groupby("project").agg(tiles=("bytes", "size"), gb=("bytes", lambda b: round(b.sum() / 1e9, 1)),
                                    published=("pub_date", "max")).reset_index().to_dict("records")


def main(fips):
    OUT.mkdir(exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    c, b = connect()
    c.execute(f"""CREATE TABLE county AS SELECT geom FROM
        ST_Read('/vsizip/{ROOT}/data/tiger/tl_2020_us_county.zip/tl_2020_us_county.shp') WHERE GEOID = '{fips}'""")
    x0, y0, x1, y1 = c.execute("SELECT ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom) FROM county").fetchone()
    t0 = time.time()
    c.execute(f"""CREATE TABLE z AS SELECT sfha_tf, zone_subty, fld_zone, geom FROM read_parquet('{b}/{ZONES}')
                  WHERE xmax >= {x0} AND xmin <= {x1} AND ymax >= {y0} AND ymin <= {y1}""")
    nz = c.execute("SELECT count(*) FROM z").fetchone()[0]
    proj = "ST_Transform(ST_MakeValid(geom), 'EPSG:4326', 'EPSG:3086', always_xy := true)"
    c.execute("""CREATE TABLE cty AS SELECT ST_Transform(geom, 'EPSG:4326', 'EPSG:3086', always_xy := true) AS g FROM county""")
    c.execute(f"""CREATE TABLE sfha AS SELECT ST_Intersection(ST_Union_Agg({proj}), (SELECT g FROM cty)) AS g
                  FROM z WHERE sfha_tf = 'T'""")
    c.execute(f"""CREATE TABLE z02 AS SELECT ST_Intersection(ST_Union_Agg({proj}), (SELECT g FROM cty)) AS g
                  FROM z WHERE zone_subty LIKE '%0.2%'""")
    c.execute("""CREATE TABLE risk AS SELECT ST_Intersection(ST_Buffer(ST_Union(coalesce(s.g, ST_GeomFromText('POLYGON EMPTY')),
                 coalesce(t.g, ST_GeomFromText('POLYGON EMPTY'))), 500), (SELECT g FROM cty)) AS g FROM sfha s, z02 t""")
    areas = c.execute("""SELECT (SELECT ST_Area(g) FROM cty) / 1e6, (SELECT ST_Area(g) FROM sfha) / 1e6,
                         (SELECT ST_Area(g) FROM z02) / 1e6, (SELECT ST_Area(g) FROM risk) / 1e6""").fetchone()
    c.execute("""CREATE TABLE risk84 AS SELECT ST_Transform(g, 'EPSG:3086', 'EPSG:4326', always_xy := true) AS geom FROM risk""")
    c.execute(f"COPY risk84 TO '{DATA}/risk_{fips}.parquet' (FORMAT parquet)")
    rx0, ry0, rx1, ry1, risk_wkt = c.execute(
        "SELECT ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom), ST_AsText(ST_Simplify(geom, 0.0002)) FROM risk84").fetchone()
    print(f"zones read {nz} in {time.time() - t0:.0f} s; areas km2 county / SFHA / 0.2% / risk: {[round(a, 1) for a in areas]}", flush=True)

    c.execute(f"""CREATE TABLE bl AS SELECT id, lon, lat, class, subtype FROM read_parquet('{b}/{BLDG}')
                  WHERE lon BETWEEN {x0} AND {x1} AND lat BETWEEN {y0} AND {y1}""")
    counts = {}
    counts["overture_buildings_in_county"] = c.execute(
        "SELECT count(*) FROM bl, county WHERE ST_Intersects(county.geom, ST_Point(bl.lon, bl.lat))").fetchone()[0]
    counts["overture_buildings_in_risk"] = c.execute(
        "SELECT count(*) FROM bl, risk84 WHERE ST_Intersects(risk84.geom, ST_Point(bl.lon, bl.lat))").fetchone()[0]
    c.execute(f"""CREATE TABLE nsi AS SELECT x, y, occtype FROM read_parquet('{ROOT}/data/fl/nsi_fl.parquet')
                  WHERE x BETWEEN {rx0} AND {rx1} AND y BETWEEN {ry0} AND {ry1}""")
    counts["nsi_structures_in_risk"], counts["nsi_residential_in_risk"] = c.execute(
        """SELECT count(*), count(*) FILTER (WHERE occtype LIKE 'RES%') FROM nsi, risk84
           WHERE ST_Intersects(risk84.geom, ST_Point(nsi.x, nsi.y))""").fetchone()
    d = pd.DataFrame(json.loads((ROOT / "data" / "fl" / "ec_all.json").read_text()))
    d = d[(d.verticalDatum == "navd_1988") & (d.buildingUse == "residential") & d.lon.notna()]
    d = d.sort_values("issuedAt").drop_duplicates("propertyId", keep="last")[["lon", "lat"]]
    c.register("ec", d)
    counts["certificates_in_risk"] = c.execute(
        "SELECT count(*) FROM ec, risk84 WHERE ST_Intersects(risk84.geom, ST_Point(ec.lon, ec.lat))").fetchone()[0]
    res = {"fips": fips, "area_km2": dict(zip(("county", "sfha", "zone_0_2", "risk"), [round(a, 1) for a in areas], strict=True)),
           "flood_polygons_read": nz, **counts, "lidar_projects_touching_risk": lidar_tiles((rx0, ry0, rx1, ry1), risk_wkt)}
    (OUT / f"risk_{fips}.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1])
