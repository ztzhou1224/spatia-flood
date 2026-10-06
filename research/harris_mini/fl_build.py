"""Out-of-county test area in Florida, built in the Harris layout (independent review, next experiment 1).

Area P (St. Petersburg, Pinellas County; bbox -82.64, 27.78 -> -82.60, 27.84, CRS84). Answer key: FDEM public
Elevation Certificates (data/fl/ec_all.json, research/coverage/FL.md), SCORER ONLY: residential, vertical datum
NAVD 1988, the latest certificate per property. Target = first LIVING floor elevation, the closest thing to the
Harris front-door floor: top of bottom floor for building diagrams 1A / 1B / 5 (slab, raised slab, elevated without
enclosure); top of next higher floor for diagrams 2-4 and 6-9 (basement, split level, enclosure, crawlspace), where
the bottom floor is not a living floor. Feet, NAVD88 (certificate values). Street addresses are dropped.
Inputs built like the Harris areas (no answer-key value is read for any of them):
  footprint  Overture buildings (release 2026-08-19.0, public S3) containing the certificate point, else nearest
             within 10 m; one certificate per footprint (latest); area <= 2,000 m2
  ground     USGS 1 m DEM (FL_Peninsular_2018_D18) in data/harris_mini/P/dem: lowest / 10th pct / median / max in a
             0.5-2.5 m ring, median under the footprint, median 10-30 m away (ft, as harris ground.py)
  NSI        nearest USACE NSI 2022 point within 30 m: foundation type, foundation height, stories, year built
  records    Florida DOR NAL parcel fields joined in data/fl/ec_joined.parquet (by certificate OBJECTID): actual
             year built, living area, use code (single-family only, 001). No stories, foundation, lower level or
             basement fields exist in this schema.
CRS: footprints and points are written in the CRS read from the first point-cloud tile (P/lpc2018); the DEM's CRS
is read from the tif. Outputs: data/harris_mini/P/houses.parquet (for lpc_features.py P) and
coverage_features.parquet (for eval_transfer.load), plus P/records.parquet (NAL fields by oid).
Usage: python fl_build.py
"""
import glob
import json
from pathlib import Path

import duckdb
import laspy
import numpy as np
import pandas as pd
import rasterio
import shapely
from pyproj import CRS, Transformer
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds
from scipy.spatial import cKDTree
from shapely import wkt as swkt
from shapely.geometry import mapping
from shapely.ops import transform as stransform

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "data" / "harris_mini" / "P"
BOX = (-82.64, 27.78, -82.60, 27.84)
USFT = 1200 / 3937
LIVING_BOTTOM = ("1A", "1B", "5")


def certificates():
    d = pd.DataFrame(json.loads((ROOT / "data" / "fl" / "ec_all.json").read_text()))
    d = d[(d.verticalDatum == "navd_1988") & (d.buildingUse == "residential") & d.lon.between(BOX[0], BOX[2])
          & d.lat.between(BOX[1], BOX[3])].copy()
    d = d.sort_values("issuedAt").drop_duplicates("propertyId", keep="last")
    dg = d.buildingDiagramNumber.astype(str).str.strip().str.upper()
    first = dg.str[0]
    d["diagram"] = dg
    d["ffe"] = np.where(dg.isin(LIVING_BOTTOM), d.topOfBottomFloor,
                        np.where(first.isin(list("2346789")), d.topOfNextHigherFloor, np.nan))
    d = d[d.ffe.between(-20, 200)]
    nal = pd.read_parquet(ROOT / "data" / "fl" / "ec_joined.parquet", columns=["OBJECTID", "dor_uc", "act_yr_blt", "tot_lvg_ar"])
    d = d.merge(nal, on="OBJECTID", how="left")
    d = d[(d.dor_uc == "001") | d.dor_uc.isna()]
    return d.drop(columns=["streetAddress", "zipcode", "propertyId"])


def footprints(to_crs):
    c = duckdb.connect()
    c.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2'")
    c.execute("CREATE SECRET anon (TYPE S3, KEY_ID '', SECRET '', REGION 'us-west-2')")
    src = "s3://overturemaps-us-west-2/release/2026-08-19.0/theme=buildings/type=building/*.parquet"
    x0, y0, x1, y1 = BOX[0] - 0.002, BOX[1] - 0.002, BOX[2] + 0.002, BOX[3] + 0.002
    f = c.execute(f"""SELECT id, ST_AsText(ST_Transform(geometry, 'EPSG:4326', '{to_crs}', always_xy := true)) AS wkt
                      FROM read_parquet('{src}', hive_partitioning=1)
                      WHERE bbox.xmin < {x1} AND bbox.xmax > {x0} AND bbox.ymin < {y1} AND bbox.ymax > {y0}""").df()
    return f


def main():
    tiles = sorted(glob.glob(str(D / "lpc2018" / "*.laz")))
    with laspy.open(tiles[0]) as f:
        crs = f.header.parse_crs()
    hcrs = crs.sub_crs_list[0] if crs.is_compound else crs
    epsg = hcrs.to_epsg()
    to_crs = f"EPSG:{epsg}"
    print(f"point-cloud CRS: {crs.name} -> footprints in {to_crs}", flush=True)
    ec = certificates()
    print(f"certificates in box: {len(ec)}; diagrams {ec.diagram.value_counts().head(8).to_dict()}", flush=True)
    fp = footprints(to_crs)
    print(f"Overture footprints: {len(fp)}", flush=True)
    geoms = [swkt.loads(w) for w in fp.wkt]
    keep = [i for i, g in enumerate(geoms) if g.geom_type in ("Polygon", "MultiPolygon") and g.area <= 2000]
    geoms = [geoms[i].buffer(0) for i in keep]
    fid = fp.id.values[keep]
    tree = shapely.STRtree(geoms)
    tr = Transformer.from_crs("EPSG:4326", to_crs, always_xy=True)
    ex, ey = tr.transform(ec.lon.values, ec.lat.values)
    rows = []
    for k, (x, y) in enumerate(zip(ex, ey, strict=True)):
        p = shapely.Point(x, y)
        j = tree.query(p, predicate="within")
        if not len(j):
            j = tree.query_nearest(p, max_distance=10)
        if not len(j):
            continue
        g = geoms[j[0]]
        rows.append({"k": k, "fid": fid[j[0]], "x": x, "y": y, "fp_wkt": g.wkt, "fp_area_m2": g.area})
    m = pd.DataFrame(rows)
    h = ec.reset_index(drop=True).iloc[m.k.values].reset_index(drop=True)
    h = pd.concat([h, m.drop(columns="k").reset_index(drop=True)], axis=1)
    h = h.sort_values("issuedAt").drop_duplicates("fid", keep="last").reset_index(drop=True)
    print(f"certificates with a footprint: {len(h)}", flush=True)

    dems = [rasterio.open(t) for t in sorted(glob.glob(str(D / "dem" / "*.tif")))]
    dcrs = CRS.from_user_input(dems[0].crs)
    to_dem = Transformer.from_crs(to_crs, dcrs, always_xy=True).transform
    print(f"DEM CRS: {dcrs.name}", flush=True)
    stats = []
    for w in h.fp_wkt:
        g = stransform(to_dem, swkt.loads(w))
        rec = {}
        for r in dems:
            b = r.bounds
            if not (b.left < g.bounds[0] - 31 and g.bounds[2] + 31 < b.right and b.bottom < g.bounds[1] - 31 and g.bounds[3] + 31 < b.top):
                continue
            win = from_bounds(g.bounds[0] - 31, g.bounds[1] - 31, g.bounds[2] + 31, g.bounds[3] + 31, r.transform).round_offsets().round_lengths()
            a = r.read(1, window=win, masked=True).filled(np.nan).astype("float64")
            a[(a < -1e5) | (a > 1e5)] = np.nan
            t = r.window_transform(win)

            def stat(geom, a=a, t=t):
                v = a[~geometry_mask([mapping(geom)], a.shape, t)]
                v = v[np.isfinite(v)]
                return v / USFT
            v, vi, vf = stat(g.buffer(2.5).difference(g.buffer(0.5))), stat(g), stat(g.buffer(30).difference(g.buffer(10)))
            if v.size >= 5:
                rec.update(e2018_lag=v.min(), e2018_p10=np.percentile(v, 10), e2018_med=np.median(v), e2018_hag=v.max())
            if vi.size >= 5:
                rec["e2018_inside"] = np.median(vi)
            if vf.size >= 20:
                rec["e2018_far"] = np.median(vf)
            break
        stats.append(rec)
    h = pd.concat([h, pd.DataFrame(stats)], axis=1)

    n = pd.read_parquet(ROOT / "data" / "fl" / "nsi_fl.parquet")
    n = n[n.x.between(BOX[0] - 0.01, BOX[2] + 0.01) & n.y.between(BOX[1] - 0.01, BOX[3] + 0.01)].reset_index(drop=True)
    nx, ny = tr.transform(n.x.values, n.y.values)
    dist, j = cKDTree(np.c_[nx, ny]).query(np.c_[h.x, h.y])
    ok = dist <= 30
    for c_out, c_in in (("nsi_found_type", "found_type"), ("nsi_found_ht", "found_ht"), ("nsi_stories", "num_story"), ("nsi_year", "med_yr_blt")):
        h[c_out] = np.where(ok, n[c_in].values[j], None)
    h["oid"] = h.OBJECTID
    h["hcad"] = "none"
    h["loc"] = "Front Door"
    h["prec"] = 0
    h["year_built"] = h.act_yr_blt
    zone = h.floodZone.astype(str).str.upper()
    h["zone"] = np.where(zone.str.startswith(("A", "V")), "SFHA", "X")
    h["bfe"] = pd.to_numeric(h.baseFloodElevation, errors="coerce").where(lambda s: s > -50)
    h = h[h.e2018_lag.notna()].reset_index(drop=True)
    cols = ["oid", "hcad", "loc", "x", "y", "lon", "lat", "ffe", "prec", "year_built", "fp_area_m2", "fp_wkt", "e2018_lag",
            "e2018_p10", "e2018_med", "e2018_hag", "e2018_inside", "e2018_far", "nsi_found_type", "nsi_found_ht",
            "nsi_year", "nsi_stories", "zone", "bfe", "diagram", "issuedAt", "floodZone"]
    h[cols].to_parquet(D / "houses.parquet", index=False)
    h[[c for c in cols if c != "fp_wkt"]].to_parquet(D / "coverage_features.parquet", index=False)
    h[["oid", "act_yr_blt", "tot_lvg_ar", "dor_uc"]].to_parquet(D / "records.parquet", index=False)
    dh = h.ffe - h.e2018_lag
    print(f"P: {len(h)} houses written; NSI matched {ok.mean():.1%} (before ground filter); living floor - DEM LAG (scorer "
          f"view) median {dh.median():.2f} ft, > 3 ft {int((dh > 3).sum())}; SFHA {int((h.zone == 'SFHA').sum())}; "
          f"diagrams {h.diagram.value_counts().head(8).to_dict()}")


if __name__ == "__main__":
    main()
