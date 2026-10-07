"""Phase 0 of the flood-layer v1 plan (docs/04-plan-flood-layer-v1.md): measure Florida, per county.

1. Structures (USACE NSI 2022, data/fl/nsi_fl.parquet): all, residential (occtype RES*), and in the SFHA by NSI's
   own `firmzone` (A* / V* / AO / AH; NSI leaves non-SFHA structures blank, so the 0.2% zone and the 500 m buffer
   of the risk area are NOT measurable here: they need the NFHL polygons, next step).
2. Elevation certificates (FDEM public layer, data/fl/ec_all.json): residential, NAVD88, latest per property;
   by building diagram group. Scorer / label source only.
3. Lidar point clouds (USGS TNM products API, dataset "Lidar Point Cloud (LPC)"): tiles and GB per project for
   each county's bounding box (a box over-counts tiles outside the county; the per-county mask comes later).
County assignment: point in TIGER 2020 county polygon (data/tiger/tl_2020_us_county.zip, STATEFP 12).
Output: pipeline/phase0/out/fl_counties.csv and fl_lidar_projects.csv; summary printed.
Usage: python pipeline/phase0/measure_fl.py [--no-lidar]
"""
import json
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
TNM = "https://tnmaccess.nationalmap.gov/api/v1/products"


def con():
    c = duckdb.connect()
    c.execute("LOAD spatial")
    c.execute(f"""CREATE TABLE county AS SELECT GEOID AS fips, NAME AS name, geom FROM
        ST_Read('/vsizip/{ROOT}/data/tiger/tl_2020_us_county.zip/tl_2020_us_county.shp') WHERE STATEFP = '12'""")
    return c


def structures(c):
    c.execute(f"CREATE TABLE nsi AS SELECT x, y, occtype, firmzone FROM read_parquet('{ROOT}/data/fl/nsi_fl.parquet')")
    return c.execute("""
        SELECT k.fips, count(*) AS structures,
               count(*) FILTER (WHERE n.occtype LIKE 'RES%') AS residential,
               count(*) FILTER (WHERE n.firmzone SIMILAR TO '(A|V).*') AS sfha_nsi,
               count(*) FILTER (WHERE n.occtype LIKE 'RES%' AND n.firmzone SIMILAR TO '(A|V).*') AS sfha_residential_nsi
        FROM nsi n JOIN county k ON ST_Intersects(k.geom, ST_Point(n.x, n.y)) GROUP BY 1""").df()


def certificates(c):
    d = pd.DataFrame(json.loads((ROOT / "data" / "fl" / "ec_all.json").read_text()))
    d = d[(d.verticalDatum == "navd_1988") & (d.buildingUse == "residential") & d.lon.notna()]
    d = d.sort_values("issuedAt").drop_duplicates("propertyId", keep="last")
    dg = d.buildingDiagramNumber.astype(str).str.strip().str.upper()
    d = pd.DataFrame({"lon": d.lon.values, "lat": d.lat.values,
                      "slab": dg.isin(["1A", "1B"]).values, "elevated": dg.str[0].isin(list("56789")).values})
    c.register("ec", d)
    return c.execute("""
        SELECT k.fips, count(*) AS certificates, sum(slab::INT) AS cert_slab, sum(elevated::INT) AS cert_elevated
        FROM ec e JOIN county k ON ST_Intersects(k.geom, ST_Point(e.lon, e.lat)) GROUP BY 1""").df()


def lidar(c):
    rows = []
    for fips, name, x0, y0, x1, y1 in c.execute(
            "SELECT fips, name, ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom) FROM county ORDER BY fips").fetchall():
        off, items = 0, []
        while True:
            for attempt in range(4):
                try:
                    r = requests.get(TNM, params={"datasets": "Lidar Point Cloud (LPC)", "bbox": f"{x0},{y0},{x1},{y1}",
                                                  "max": 1000, "offset": off}, timeout=120)
                    r.raise_for_status()
                    d = r.json()
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(2 ** attempt)
            else:
                raise RuntimeError(f"TNM failed for {fips}")
            items += d.get("items", [])
            off += 1000
            if off >= d.get("total", 0):
                break
        for it in items:
            url = it.get("downloadURL") or ""
            proj = url.split("/Projects/")[1].split("/")[0] if "/Projects/" in url else "other"
            rows.append({"fips": fips, "county": name, "project": proj, "bytes": it.get("sizeInBytes") or 0,
                         "pub_date": it.get("publicationDate")})
        print(f"{fips} {name}: {len(items)} LPC tiles", flush=True)
    return pd.DataFrame(rows)


def main():
    OUT.mkdir(exist_ok=True)
    c = con()
    k = c.execute("SELECT fips, name FROM county").df()
    k = k.merge(structures(c), on="fips", how="left").merge(certificates(c), on="fips", how="left").fillna(0)
    if "--no-lidar" not in sys.argv:
        lp = lidar(c)
        lp.to_csv(OUT / "fl_lidar_projects.csv", index=False)
        g = lp.groupby("fips").agg(lpc_tiles=("bytes", "size"), lpc_gb=("bytes", lambda b: b.sum() / 1e9),
                                   lpc_projects=("project", "nunique"))
        k = k.merge(g, on="fips", how="left")
    k = k.sort_values("sfha_residential_nsi", ascending=False)
    k.to_csv(OUT / "fl_counties.csv", index=False)
    tot = k.drop(columns=["fips", "name"]).sum(numeric_only=True)
    print("\nFlorida totals:", {c_: round(float(v), 1) for c_, v in tot.items()})
    print(k.head(20).round(1).to_string(index=False))


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main()
