"""Phase 1: assemble the per-building flood table (and the parcel table) for one county (plan docs/04 §3).

One row per Overture building whose footprint centroid lies in the county (spatia-data us_counties, TIGER 2025);
floor work only for the risk-area
buildings of the lidar run. Every value x carries x_class (record / observed / modeled), x_source, x_vintage, a band
(modeled, 90%) or x_precision_ft (when the source states one), and x_null (reason) when x is null (plan §3.1).
Column meanings: docs/06-layer-schema-v1.md.

Sources (all read here; nothing from NFIP, Bee Maps or any image; no owner field is ever selected):
- footprints: spatia-data overture_buildings; risk-area set and lidar features from the run (lidar/prepare.py, job.py)
- zones and BFE: spatia-data fema_flood_zones (NFHL S_FLD_HAZ_AR); shares of footprint area in EPSG:3086;
  touches_sfha = any SFHA polygon overlaps the footprint with area > 0; BFE = the highest static BFE (NAVD88) of the
  SFHA polygons it overlaps (FEMA rates a building in several zones by the higher one)
- lidar vintage, QL and geoid: USGS WESM work units (3DEPElevationIndex layer 24), building centroid in work unit
- records: Florida DOR NAL via spatia-data fl_parcels (parcel containing the centroid, as train/labels.py)
- floor record: FDEM certificates matched by train/labels.py; the certificate's own lowest adjacent grade fetched by
  OBJECTID (FDEM public layer) so a record floor height never mixes in our lidar ground
- floor model: train/train.py artefacts (point model, difficulty model, q); applied to risk-area buildings on a
  residential parcel (DOR 000-009) with ground and point-cloud features: the population it was trained and
  calibrated on. Before use, the held-out gate score is recomputed from the saved artefacts and must match.
- addresses: Overture address point in the footprint (nearest to the centroid), else the parcel situs address,
  else a Geocodio reverse lookup when data/flood_v1/assemble/geocodio_<FIPS>.parquet exists (geocodio.py)
Outputs: data/flood_v1/assemble/buildings_<FIPS>.parquet (GeoParquet, footprint geometry, CRS84),
parcels_<FIPS>.parquet (attributes, no geometry); counts in pipeline/assemble/out/assemble_<FIPS>.json.
Usage: python pipeline/assemble/assemble.py 12103 pinellas_2018 --release pinellas-r0
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import lightgbm as lgb
import numpy as np
import pandas as pd
import requests
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "phase0"))
sys.path.insert(0, str(ROOT / "pipeline" / "train"))
from risk_area import BLDG, ZONES, connect  # noqa: E402
from train import FEATS, features  # noqa: E402

DATA = ROOT / "data" / "flood_v1"
OUT = DATA / "assemble"
REPORT = Path(__file__).resolve().parent / "out"
PARCELS = "layers/state/FL/fl_parcels.parquet"
ADDR = "layers/national/overture_addresses.parquet"
COUNTIES = "layers/national/us_counties.parquet"
RECORD_FFH_FT = (-1.0, 30.0)  # a certificate floor height outside this is not a plausible first living floor
ZONES_EDITION = ZONES.split("@")[1].split("/")[0]
WESM = "https://index.nationalmap.gov/arcgis/rest/services/3DEPElevationIndex/MapServer/24/query"
FDEM = ("https://services8.arcgis.com/4L6VuYsPSGSEJ0qe/arcgis/rest/services/Public_FDEM_Elevation_Certificates/"
        "FeatureServer/0/query")
ALBERS = "EPSG:3086"
BFE_LINES = "layers/national/fema_bfe_context@20260930T082454Z-9c7789f1/current/data.parquet"
LINE_SEARCH_M = 1000.0
LINES_EDITION = BFE_LINES.split("@")[1].split("/")[0]
BFE_ROUND_FT = 0.5  # FIRM BFEs are whole feet: an interpolated BFE carries +-0.5 ft beyond its two lines
Z90 = 1.645
RAISED_FT = 3.0  # train.py raised flag
FINISHED = "finished_construction"  # the only certificate stage used as a record (docs/09 Q5 / E7)
CONFLICT_LAG_FT = 3.0  # certificate LAG this far from ground_ft: the certificate conflicts with the lidar (docs/09 E2)
QL_RMSEZ_FT = {"QL 0": 5 / 30.48006, "QL 1": 10 / 30.48006, "QL 2": 10 / 30.48006, "QL 3": 20 / 30.48006}  # 3DEP LBS
LIC = {"bldg": "overture_buildings:ODbL-1.0", "nfhl": "fema_nfhl:public", "3dep": "usgs_3dep:public_domain",
       "dor": "fl_dor_nal:public_record", "fdem": "fdem_certificates:forerunner_internal_noncommercial",
       "oaddr": "overture_addresses:FL_public_domain", "geocodio": "geocodio:stored_per_terms",
       "osm": "openstreetmap:ODbL-1.0"}


def projected(g: np.ndarray, crs: str) -> np.ndarray:
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])


def overlay(a: np.ndarray, polys: np.ndarray) -> pd.DataFrame:
    """Pairs (a index, poly index) with their overlap area (> 0), same projected CRS; a polygon that contains the
    shape properly is not intersected (prepared test first)."""
    bi, pi = shapely.STRtree(polys).query(a)  # bounding boxes; exact tests below run on prepared polygons
    shapely.prepare(polys)
    hit = shapely.intersects(polys[pi], a[bi])
    bi, pi = bi[hit], pi[hit]
    full = shapely.contains_properly(polys[pi], a[bi])
    area = shapely.area(a[bi])
    k = ~full
    area[k] = shapely.area(shapely.intersection(a[bi[k]], polys[pi[k]]))
    m = area > 0
    return pd.DataFrame({"a": bi[m], "p": pi[m], "area": area[m]})


def cached(path: Path, make):
    if not path.exists():
        make().to_parquet(path, index=False)
    return pd.read_parquet(path)


def county_buildings(c, bk: str, fips: str) -> pd.DataFrame:
    """Overture footprints whose centroid (the published lon / lat) lies in the county polygon of spatia-data
    us_counties (TIGER 2025, the catalog's county layer, so the layer's coverage footprint and membership agree)."""
    c.execute(f"""CREATE OR REPLACE TABLE county AS SELECT geom FROM read_parquet('{bk}/{COUNTIES}')
                  WHERE GEOID = '{fips}'""")
    x0, y0, x1, y1 = c.execute("SELECT ST_XMin(geom), ST_YMin(geom), ST_XMax(geom), ST_YMax(geom) FROM county").fetchone()
    pad = 0.01  # the stored lon / lat only prefilter; membership is decided on the footprint centroid
    return c.execute(f"""SELECT b.id AS building_id, ST_AsWKB(b.geom) AS wkb
        FROM read_parquet('{bk}/{BLDG}') b, county
        WHERE b.lon BETWEEN {x0 - pad} AND {x1 + pad} AND b.lat BETWEEN {y0 - pad} AND {y1 + pad}
        AND ST_Intersects(county.geom, ST_Centroid(b.geom))""").df().assign(wkb=lambda d: d.wkb.map(bytes))


def catalog(names: tuple[str, ...]) -> dict:
    """version and file_hash of the spatia-data layers read, from the live manifest (provenance of every input)."""
    import os

    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["CLOUDFLARE_R2_ENDPOINT"], region_name="auto",
                      aws_access_key_id=os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"])
    m = json.loads(s3.get_object(Bucket=os.environ["CLOUDFLARE_R2_BUCKET"], Key="manifest.json")["Body"].read())
    return {e["id"]: {"version": e.get("version"), "file_hash": e.get("file_hash"), "storage_path": e.get("storage_path")}
            for e in m["layers"] if e["id"] in names}


def wesm(bounds, project: str) -> pd.DataFrame:
    x0, y0, x1, y1 = bounds
    r = requests.get(WESM, params={"geometry": f"{x0},{y0},{x1},{y1}", "geometryType": "esriGeometryEnvelope",
                                   "inSR": 4326, "outSR": 4326, "spatialRel": "esriSpatialRelIntersects",
                                   "where": f"project = '{project}'", "f": "geojson", "outFields":
                                   "workunit,project,collect_start,collect_end,ql,spec,vert_crs,geoid,lpc_pub_date"},
                     timeout=120)
    r.raise_for_status()
    rows = []
    for f in r.json()["features"]:
        a = f["properties"]
        day = {k: dt.datetime.fromtimestamp(a[k] / 1000, dt.UTC).date().isoformat() if a[k] else None
               for k in ("collect_start", "collect_end", "lpc_pub_date")}
        rows.append({**a, **day, "wkb": shapely.to_wkb(shapely.geometry.shape(f["geometry"]))})
    return pd.DataFrame(rows)


def fdem_lag(ids: list[int]) -> pd.DataFrame:
    rows = []
    for k in range(0, len(ids), 400):
        for attempt in range(4):
            try:
                r = requests.post(FDEM, data={"objectIds": ",".join(map(str, ids[k:k + 400])), "returnGeometry": "false",
                                              "outFields": "OBJECTID,lowestAdjacentGrade,verticalDatum", "f": "json"},
                                  timeout=120)
                r.raise_for_status()
                rows += [f["attributes"] for f in r.json()["features"]]
                break
            except (requests.RequestException, KeyError, ValueError):
                time.sleep(2 ** attempt)
        else:
            raise RuntimeError("FDEM query failed")
    return pd.DataFrame(rows).rename(columns={"OBJECTID": "cert_objectid", "lowestAdjacentGrade": "cert_lag_ft",
                                              "verticalDatum": "cert_datum"})


def interpolate_bfe(cen: np.ndarray, polys_of: dict, zg: np.ndarray, lines: pd.DataFrame, lg: np.ndarray) -> pd.DataFrame:
    """BFE between FEMA BFE lines / cross-sections, per building index in polys_of (building -> SFHA polygon indices).
    Candidates: lines crossing one of the building's SFHA polygons, within LINE_SEARCH_M of its centroid (EPSG:3086).
    L1 = nearest; L2 = nearest line on the other side (vector to its nearest point opposite to L1's). BFE = linear in
    distance between them, band = [min - 0.5, max + 0.5] of the two elevations (BFE_ROUND_FT). No L2: not_determinable; no candidate: no_coverage."""
    need = sorted({q for ps in polys_of.values() for q in ps})
    li, pi = shapely.STRtree(lg).query(zg[need], predicate="intersects")
    by_poly: dict[int, set] = {}
    for k, j in zip(np.asarray(need)[li], pi, strict=True):
        by_poly.setdefault(int(k), set()).add(int(j))
    rows = []
    for a, ps in polys_of.items():
        cand = sorted(set().union(*(by_poly.get(q, set()) for q in ps)))
        c = cen[a]
        if cand:
            d = shapely.distance(c, lg[cand])
            keep = d <= LINE_SEARCH_M
            cand, d = np.asarray(cand)[keep], d[keep]
        if not len(cand):
            rows.append({"a": a, "null": "no_coverage"})
            continue
        near = shapely.get_coordinates(shapely.shortest_line(c, lg[cand]))[1::2] - shapely.get_coordinates(c)
        o = np.argsort(d)
        i1 = o[0]
        e1 = lines.elev.values[cand[i1]]
        if d[i1] == 0:
            i2, e2, f = i1, e1, 0.0
        else:
            opp = [k for k in o[1:] if d[k] > 0 and near[k] @ near[i1] < 0]
            if not opp:
                rows.append({"a": a, "null": "not_determinable"})
                continue
            i2 = opp[0]
            e2 = lines.elev.values[cand[i2]]
            f = d[i1] / (d[i1] + d[i2])
        l1, l2 = lines.iloc[cand[i1]], lines.iloc[cand[i2]]
        rows.append({"a": a, "bfe": e1 + (e2 - e1) * f, "lo": min(e1, e2) - BFE_ROUND_FT, "hi": max(e1, e2) + BFE_ROUND_FT,
                     "src": f"{l1.source_type} {l1.line_id} {e1:g} ft at {d[i1]:.0f} m; {l2.source_type} {l2.line_id} "
                            f"{e2:g} ft at {d[i2]:.0f} m",
                     "dfirm": l1.dfirm_id, "eff": max(l1.eff, l2.eff), "status": l1.status})
    return pd.DataFrame(rows, columns=["a", "bfe", "lo", "hi", "src", "dfirm", "eff", "status", "null"])


def lists(s: pd.Series, idx) -> np.ndarray:
    """s (lists by position) reindexed to idx, with None (not NaN) where missing, as parquet list columns need."""
    v = s.reindex(idx).values
    return np.array([x if isinstance(x, list) else None for x in v], dtype=object)


def nulls(value: pd.Series, reason) -> pd.Series:
    """Null reason per row: '' where value is present, else the reason (scalar or per-row)."""
    r = pd.Series(reason, index=value.index, dtype=object) if not isinstance(reason, pd.Series) else reason.astype(object)
    return r.where(value.isna(), None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("run")
    ap.add_argument("--release", required=True)
    ap.add_argument("--model-dir", type=Path, default=DATA / "train",
                    help="train.py artefacts + the labels they were trained on (default data/flood_v1/train)")
    ap.add_argument("--out", type=Path, default=OUT, help="where the building / parcel tables go (caches stay in OUT)")
    a = ap.parse_args()
    fips, run = a.fips, a.run
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(exist_ok=True)
    rep: dict = {"fips": fips, "run": run, "release": a.release, "built": dt.datetime.now(dt.UTC).date().isoformat()}
    t0 = time.time()
    c, bk = connect()

    # ---------------------------------------------------------------- buildings and the risk-area run
    b = cached(OUT / f"buildings_all_{fips}.parquet", lambda: county_buildings(c, bk, fips))
    runb = pd.read_parquet(DATA / "lidar" / run / "buildings.parquet")
    feat = pd.read_parquet(DATA / "lidar" / run / "features.parquet")
    assert set(runb.building_id) <= set(b.building_id), "run buildings outside the county set"
    b["in_risk_area"] = b.building_id.isin(set(runb.building_id))
    g = shapely.make_valid(shapely.from_wkb(b.wkb.values))
    ga = projected(g, ALBERS)
    b["footprint_area_m2"] = shapely.area(ga)
    cen = shapely.centroid(g)
    b["lon"], b["lat"] = shapely.get_x(cen), shapely.get_y(cen)
    cat = catalog(("overture_buildings", "overture_addresses", "fl_parcels", "us_counties", "fema_flood_zones",
                   "fema_bfe_context"))
    ob = cat["overture_buildings"]
    b["footprint_source"] = (f"Overture buildings release {ob['version']} (spatia-data overture_buildings, "
                             f"file_hash {ob['file_hash'][:12]}); county membership: footprint centroid in us_counties "
                             f"{cat['us_counties']['version']} GEOID {fips}")
    b["footprint_release"] = ob["version"]  # an edition, not a measurement date
    rep["inputs"] = cat | {"fema_flood_zones_release": ZONES_EDITION, "fema_bfe_context_release": LINES_EDITION}
    rep["buildings"] = {"county": len(b), "risk_area": int(b.in_risk_area.sum())}
    print(f"buildings {len(b)} ({b.in_risk_area.sum()} in the risk area), {time.time() - t0:.0f} s", flush=True)

    # ---------------------------------------------------------------- zones and BFE
    z = pd.read_parquet(OUT / f"zones_{fips}_raw.parquet") if (OUT / f"zones_{fips}_raw.parquet").exists() else None
    if z is None:
        x0, y0, x1, y1 = shapely.total_bounds(g)
        z = c.execute(f"""SELECT polygon_id, dfirm_id, fld_zone, zone_subty, sfha_tf, static_bfe_navd88_ft,
            static_bfe_navd88_sigma_ft, static_bfe_navd88_status, firm_panel_eff_date_max, ST_AsWKB(geom) AS wkb
            FROM read_parquet('{bk}/{ZONES}') WHERE xmax >= {x0} AND xmin <= {x1} AND ymax >= {y0} AND ymin <= {y1}""").df()
        z["wkb"] = z.wkb.map(bytes)
        z.to_parquet(OUT / f"zones_{fips}_raw.parquet", index=False)
    zg = projected(shapely.make_valid(shapely.from_wkb(z.wkb.map(bytes).values)), ALBERS)
    pr = overlay(ga, zg)
    pr["share"] = pr.area / b.footprint_area_m2.values[pr.a]
    for col in ("fld_zone", "zone_subty", "static_bfe_navd88_ft", "static_bfe_navd88_sigma_ft", "static_bfe_navd88_status",
                "dfirm_id", "firm_panel_eff_date_max"):
        pr[col] = z[col].values[pr.p]
    pr["sfha"] = (z.sfha_tf.values[pr.p] == "T")
    zl = pr.groupby(["a", "fld_zone", "zone_subty", "sfha"], dropna=False).share.sum().reset_index()
    zl = zl.sort_values(["a", "share"], ascending=[True, False])
    zl["rec"] = [{"zone": fz, "subtype": None if pd.isna(st) else st, "sfha": bool(sf), "share": round(float(sh), 4)}
                 for fz, st, sf, sh in zip(zl.fld_zone, zl.zone_subty, zl.sfha, zl.share, strict=True)]
    b["zones"] = lists(zl.groupby("a").rec.agg(list), range(len(b)))
    share_sum = pr.groupby("a").share.sum().reindex(range(len(b))).fillna(0)
    b["zones_null"] = np.where(share_sum.values > 0, None, "no_coverage")
    first_zone = zl.drop_duplicates("a").set_index("a").reindex(range(len(b)))
    b["zone_main"] = first_zone.fld_zone.values
    b["zone_main_subtype"] = first_zone.zone_subty.values  # same element as zone_main: zones[1]
    b["sfha_share"] = pr[pr.sfha].groupby("a").share.sum().reindex(range(len(b))).fillna(0).clip(upper=1).values
    b["touches_sfha"] = b.sfha_share > 0
    eff = pr.sort_values("share", ascending=False).drop_duplicates("a").set_index("a").firm_panel_eff_date_max
    b["firm_effective_date"] = pd.to_datetime(eff.reindex(range(len(b)))).dt.strftime("%Y-%m-%d").values
    sb = pr[pr.sfha & pr.static_bfe_navd88_ft.notna()].sort_values("static_bfe_navd88_ft", ascending=False).drop_duplicates("a")
    sb = sb.set_index("a").reindex(range(len(b)))
    b["bfe_ft"] = sb.static_bfe_navd88_ft.values
    b["bfe_class"] = np.where(b.bfe_ft.notna(), "record", None)
    b["bfe_method"] = np.where(b.bfe_ft.notna(), "static", None)
    b["bfe_source"] = np.where(b.bfe_ft.notna(), "FEMA NFHL S_FLD_HAZ_AR static BFE, DFIRM " + sb.dfirm_id.astype(str)
                               + f" (spatia-data fema_flood_zones@{ZONES_EDITION})", None)
    b["bfe_vintage"] = np.where(b.bfe_ft.notna(), pd.to_datetime(sb.firm_panel_eff_date_max).dt.date.astype(str), None)
    b["bfe_precision_ft"] = sb.static_bfe_navd88_sigma_ft.values
    b["bfe_datum"] = np.where(b.bfe_ft.notna(), "NAVD88 ft; " + sb.static_bfe_navd88_status.astype(str), None)
    sfha_zones = pr[pr.sfha].groupby("a").fld_zone.agg(set).reindex(range(len(b)))
    only_a = sfha_zones.map(lambda s: isinstance(s, set) and s <= {"A"}).values
    b["bfe_null"] = nulls(b.bfe_ft, pd.Series(np.where(~b.touches_sfha, "not_applicable",
                                                        np.where(only_a, "no_coverage", "not_evaluated")), index=b.index))
    b["bfe_band_lo"], b["bfe_band_hi"] = np.nan, np.nan
    lines = cached(OUT / f"bfe_lines_{fips}.parquet", lambda: c.execute(f"""SELECT line_id, source_type, dfirm_id,
        elev_ft_navd88_ft, elev_ft_navd88_status, firm_panel_eff_date_max, ST_AsWKB(geom) AS wkb
        FROM read_parquet('{bk}/{BFE_LINES}') WHERE dfirm_id IN ({", ".join(f"'{x}'" for x in z.dfirm_id.unique())})""").df())
    lines = lines[lines.elev_ft_navd88_ft.notna()].reset_index(drop=True)
    lines = lines.rename(columns={"elev_ft_navd88_ft": "elev", "elev_ft_navd88_status": "status",
                                  "firm_panel_eff_date_max": "eff"})
    lg = projected(shapely.from_wkb(lines.wkb.map(bytes).values), ALBERS)
    cen_a = shapely.centroid(ga)
    sp = pr[pr.sfha]
    todo = set(np.where(b.bfe_null.values == "not_evaluated")[0])
    polys_of = {int(k): set(v) for k, v in sp[sp.a.isin(todo)].groupby("a").p}
    ip = interpolate_bfe(cen_a, polys_of, zg, lines, lg)
    ok_ = ip[ip.bfe.notna()]
    ia = ok_.a.values.astype(int)
    b.loc[ia, "bfe_ft"] = ok_.bfe.values
    b.loc[ia, "bfe_band_lo"], b.loc[ia, "bfe_band_hi"] = ok_.lo.values, ok_.hi.values
    b.loc[ia, "bfe_class"], b.loc[ia, "bfe_method"] = "modeled", "interpolated"
    b.loc[ia, "bfe_source"] = ("FEMA NFHL BFE lines / cross-sections, DFIRM " + ok_.dfirm.astype(str)
                               + f" (spatia-data fema_bfe_context@{LINES_EDITION}): " + ok_.src).values
    b.loc[ia, "bfe_vintage"] = pd.to_datetime(ok_.eff).dt.strftime("%Y-%m-%d").values
    b.loc[ia, "bfe_datum"] = ("NAVD88 ft; " + ok_.status.astype(str)).values
    b.loc[ia, "bfe_null"] = None
    nn = ip[ip.bfe.isna()]
    b.loc[nn.a.values.astype(int), "bfe_null"] = nn.null.values
    # the same method where a static BFE exists (AE / VE with lines): how close does interpolation get?
    st = np.where((b.bfe_method.values == "static") & b.touches_sfha.values)[0]
    chk = interpolate_bfe(cen_a, {int(k): set(v) for k, v in sp[sp.a.isin(set(st))].groupby("a").p}, zg, lines, lg)
    chk = chk[chk.bfe.notna()]
    err = chk.bfe.values - b.bfe_ft.values[chk.a.values.astype(int)]
    inb = (b.bfe_ft.values[chk.a.values.astype(int)] >= chk.lo.values - 1e-9) & (b.bfe_ft.values[chk.a.values.astype(int)] <= chk.hi.values + 1e-9)
    rep["bfe_interpolation"] = {"lines_with_elevation": len(lines), "buildings_tried": len(polys_of),
                                "interpolated": len(ok_), "null": nn.null.value_counts().to_dict(),
                                "band_width_median_ft": round(float((ok_.hi - ok_.lo).median()), 2) if len(ok_) else None,
                                "check_on_static_bfe": {"n": len(chk), "MAE_ft": round(float(np.abs(err).mean()), 3),
                                                        "within_1ft": round(float((np.abs(err) <= 1).mean()), 3),
                                                        "static_inside_band": round(float(inb.mean()), 3)}}
    print(f"bfe interpolation: {rep['bfe_interpolation']}", flush=True)
    rep["zones"] = {"polygons_read": len(z), "pairs": len(pr), "no_zone_polygon": int((share_sum == 0).sum()),
                    "share_sum_over_1.01": int((share_sum > 1.01).sum()), "touches_sfha": int(b.touches_sfha.sum()),
                    "touches_sfha_share_under_1pct": int(((b.sfha_share > 0) & (b.sfha_share < 0.01)).sum()),
                    "bfe_static": int(b.bfe_ft.notna().sum()), "bfe_null": b.bfe_null.value_counts().to_dict()}
    print(f"zones: {rep['zones']}, {time.time() - t0:.0f} s", flush=True)

    # ---------------------------------------------------------------- lidar: ground, roof, eave (observed)
    project = json.loads((DATA / "lidar" / run / "tiles.json").read_text())["project"]
    wu = cached(OUT / f"wesm_{fips}.parquet", lambda: wesm(shapely.total_bounds(g), project))
    wg = shapely.from_wkb(wu.wkb.values)
    bi, wi = shapely.STRtree(wg).query(cen, predicate="within")
    first = pd.DataFrame({"b": bi, "w": wi}).sort_values(["b", "w"]).drop_duplicates("b")
    w = wu.drop(columns="wkb").iloc[first.w.values].set_index(first.b.values).reindex(range(len(b)))
    lidar_src = ("USGS 3DEP " + w.ql.astype(str) + ", project " + w.project.astype(str) + ", work unit "
                 + w.workunit.astype(str) + ", geoid " + w.geoid.astype(str))
    lidar_vint = w.collect_start.astype(str) + "/" + w.collect_end.astype(str)
    f = b[["building_id"]].merge(feat, on="building_id", how="left")
    risk = b.in_risk_area.values
    lag = pd.Series(np.where(risk, f.g_lag, np.nan))
    b["ground_ft"] = lag  # lidar ring minimum, NOT the Elevation Certificate's Lowest Adjacent Grade
    b["ground_class"] = np.where(lag.notna(), "observed", None)
    b["ground_source"] = np.where(lag.notna(), "lidar 1 m DEM, lowest cell in a 0.5-2.5 m ring outside the footprint "
                                  "(not the Elevation Certificate LAG); " + lidar_src, None)
    b["ground_vintage"] = np.where(lag.notna(), lidar_vint, None)
    b["ground_precision_ft"] = np.where(lag.notna(), w.ql.map(QL_RMSEZ_FT), np.nan)
    b["ground_geoid"] = np.where(lag.notna(), w.geoid, None)
    gnull = f.ground_status.map({"no_coverage": "no_coverage", "not_determinable": "not_determinable"}).fillna("not_determinable")
    b["ground_null"] = nulls(lag, pd.Series(np.where(risk, gnull, "not_evaluated")))
    ok = risk & (f.lpc_status == "ok").values
    lpc_null = f.lpc_status.map({"too_large": "not_evaluated", "no_coverage": "no_coverage", "no_ground": "not_determinable",
                                 "no_points": "not_determinable", "not_determinable": "not_determinable"})
    lpc_null = pd.Series(np.where(risk, lpc_null.fillna("not_determinable"), "not_evaluated"))
    for col, src in (("roof_ft", "ridge"), ("eave_ft", "eave_main")):
        v = pd.Series(np.where(ok, f[src], np.nan))
        b[col] = v
        b[f"{col[:-3]}_class"] = np.where(v.notna(), "observed", None)
        b[f"{col[:-3]}_source"] = np.where(v.notna(), f"point cloud {src}, ft above ground_ft; " + lidar_src, None)
        b[f"{col[:-3]}_vintage"] = np.where(v.notna(), lidar_vint, None)
        b[f"{col[:-3]}_null"] = nulls(v, pd.Series(np.where(ok, "not_determinable", lpc_null)))
    b["lidar_workunit"], b["lidar_ql"] = w.workunit.values, w.ql.values
    rep["lidar"] = {"workunits": wu.drop(columns="wkb").to_dict("records"),
                    "buildings_per_workunit": w.workunit.value_counts(dropna=False).to_dict(),
                    "lag": int(lag.notna().sum()), "roof": int(b.roof_ft.notna().sum()), "eave": int(b.eave_ft.notna().sum()),
                    "roof_null": b.roof_null.value_counts().to_dict(), "eave_null": b.eave_null.value_counts().to_dict()}

    # ---------------------------------------------------------------- parcels and records (DOR NAL)
    def read_parcels():
        x0, y0, x1, y1 = shapely.total_bounds(g)
        p = c.execute(f"""SELECT parcel_id, dor_uc, act_yr_blt, tot_lvg_ar, asmnt_yr, phy_addr1, phy_city, phy_zipcd,
            ST_AsWKB(geom) AS wkb FROM read_parquet('{bk}/{PARCELS}') WHERE county_fips = '{fips}'
            AND bbox.xmax >= {x0} AND bbox.xmin <= {x1} AND bbox.ymax >= {y0} AND bbox.ymin <= {y1}""").df()
        return p.assign(wkb=p.wkb.map(bytes))
    pa = cached(OUT / f"parcels_raw_{fips}.parquet", read_parcels)
    pa = pa[pa.wkb.notna()].reset_index(drop=True)
    pa["parcel_key"] = f"FL-{fips}-" + pa.parcel_id.astype(str)
    pg = shapely.make_valid(shapely.from_wkb(pa.wkb.values))
    bj, pj = shapely.STRtree(pg).query(cen, predicate="within")
    first = pd.DataFrame({"b": bj, "p": pj}).drop_duplicates("b")
    pidx = np.full(len(b), -1)
    pidx[first.b.values] = first.p.values
    has_p = pidx >= 0
    pcol = pa.reindex(np.where(has_p, pidx, -1)).reset_index(drop=True)  # -1 -> all-NaN row
    b["parcel_key"] = pcol.parcel_key.values
    b["parcel_id_native"] = pcol.parcel_id.values
    b["county_fips"] = fips
    b["parcels_at_centroid"] = pd.Series(bj).value_counts().reindex(range(len(b))).fillna(0).astype(int).values
    b["dor_use_code"] = pcol.dor_uc.values
    nal = "Florida DOR NAL " + pcol.asmnt_yr.astype("Int64").astype(str) + " (spatia-data fl_parcels)"
    for col, src, lo in (("year_built", "act_yr_blt", 1800), ("living_area_sqft", "tot_lvg_ar", 0)):
        v = pd.to_numeric(pcol[src], errors="coerce").where(lambda s, lo=lo: s > lo)
        b[col] = v.values
        b[f"{col}_class"] = np.where(v.notna(), "record", None)
        b[f"{col}_source"] = np.where(v.notna(), nal, None)
        b[f"{col}_vintage"] = np.where(v.notna(), pcol.asmnt_yr.astype("Int64").astype(str), None)
        b[f"{col}_null"] = nulls(v, pd.Series(np.where(has_p, "not_determinable", "no_coverage")))
    residential = has_p & (pcol.dor_uc.fillna("999").values < "010")
    rep["parcels"] = {"parcels_read": len(pa), "buildings_with_parcel": int(has_p.sum()),
                      "buildings_on_residential_parcel": int(residential.sum()),
                      "risk_buildings_on_residential_parcel": int((residential & risk).sum())}

    # ---------------------------------------------------------------- floor: model (all eligible) and record
    m = features(fips, run)
    md = a.model_dir
    model = lgb.Booster(model_file=str(md / f"model_{fips}.txt"))
    diff = lgb.Booster(model_file=str(md / f"difficulty_{fips}.txt"))
    bands = json.loads((md / f"bands_{fips}.json").read_text())
    assert bands["features"] == FEATS, "train.py features changed since the model was saved"
    q = bands["q"]
    h = hashlib.sha256()
    for fn in (f"model_{fips}.txt", f"difficulty_{fips}.txt", f"bands_{fips}.json"):
        h.update((md / fn).read_bytes())
    version = f"E-lgbm-{fips}-{h.hexdigest()[:12]}"

    def predict(x: pd.DataFrame):
        p = model.predict(x[FEATS])
        s = np.maximum(diff.predict(x[FEATS].assign(p=p)), 0.05)
        return p, p - q * s, p + q * s

    # gate re-check: the saved artefacts must reproduce train.py's held-out score
    lab = pd.read_parquet(md / f"labels_{fips}.parquet")
    d = lab.merge(m, on="building_id")
    d = d[d.g_lag.notna() & (d.lpc_status == "ok")].copy()
    d["dh"] = d.ffe_ft - d.g_lag
    d = d[~((d.roof_p95 - d.dh < 6) | (d.dh < -1))]
    t = d[d.block.isin(set(bands["test_blocks"]))]
    pt, lo, hi = predict(t)
    rep["gate_recheck"] = {"n": len(t), "MAE": round(float(np.abs(pt - t.dh).mean()), 3),
                           "coverage": round(float(((t.dh >= lo) & (t.dh <= hi)).mean()), 3), "q": q}
    assert len(t) == bands["n_test"], f"held-out set changed: {len(t)} vs {bands['n_test']}"
    print(f"gate re-check from saved artefacts: {rep['gate_recheck']}", flush=True)
    # the accuracy card (docs/09 A1): both populations, from pipeline/train/accuracy.py --no-table for this release
    acc = json.loads((ROOT / "pipeline" / "train" / "out" / f"accuracy_{fips}_{a.release}.json").read_text())
    assert acc["fdem_held_out"]["all"]["n"] == len(t), "accuracy card scored a different held-out set"
    accuracy = {k: acc[k] for k in ("populations", "fdem_held_out", "county_independent")}

    mm = b[["building_id"]].merge(m, on="building_id", how="left")
    elig = risk & residential & (mm.lpc_status == "ok").values & mm.g_lag.notna().values
    p = np.full(len(b), np.nan)
    plo, phi = p.copy(), p.copy()
    p[elig], plo[elig], phi[elig] = predict(mm[elig])
    why_not = np.where(~risk, "not_evaluated", np.where(~has_p, "no_coverage", np.where(~residential, "not_evaluated",
                       lpc_null.values)))

    # records: the latest certificate per building whatever its stage (labels.py certificates_<FIPS>.parquet, which
    # carries the certificate's own LAG and stage); r0 read the labels and fetched the LAG by OBJECTID
    cpath_ = DATA / "train" / f"certificates_{fips}.parquet"
    lab = pd.read_parquet(cpath_) if cpath_.exists() else lab
    if "cert_lag_ft" not in lab.columns:
        lab = lab.merge(cached(OUT / f"fdem_lag_{fips}.parquet", lambda: fdem_lag(sorted(lab.cert_objectid.astype(int)))),
                        on="cert_objectid", how="left")
    if "record_stage" not in lab.columns:
        lab["record_stage"] = FINISHED
    lab["cert_lag_ft"] = pd.to_numeric(lab.cert_lag_ft, errors="coerce").where(lambda s: s.between(-20, 200))
    r = b[["building_id"]].merge(lab, on="building_id", how="left")
    rec = r.ffe_ft.notna().values
    issued = pd.to_datetime(r.issued_at, unit="ms", errors="coerce")
    issued_ok = issued.between(pd.Timestamp("1990-01-01"), pd.Timestamp(rep["built"]))
    issued = issued.dt.strftime("%Y-%m-%d").where(issued_ok, "unknown")  # FDEM issuedAt: missing or invalid dates
    note = pd.Series(None, index=r.index, dtype=object)
    cpath = OUT / f"dates_clean_{fips}.parquet"  # clean_dates.py: LLM estimates for those dates
    if cpath.exists():
        cl = pd.read_parquet(cpath)
        cl = cl[cl.valid].set_index("cert_objectid")
        oid = r.cert_objectid.astype("Int64")
        hit = rec & ~issued_ok.values & oid.isin(cl.index).fillna(False).values
        e = cl.reindex(oid[hit].astype(int))
        issued[hit] = np.where(e.estimate.notna(), e.estimate, e.window_start + "/" + e.window_end)
        note[hit] = ("issue date estimated by LLM (" + e.model + ", " + e.confidence + "): raw issuedAt "
                     + e.issued_raw.fillna("missing") + "; " + e.reason.fillna("")).values
    cert_src = ("FDEM elevation certificate OBJECTID " + r.cert_objectid.astype("Int64").astype(str) + ", diagram "
                + r.diagram.astype(str) + ", first living floor (" + r.match.astype(str) + ")")
    # A certificate is used only if its floor is physically plausible against our independent lidar ground: certificate
    # FFE minus ground_ft within RECORD_FFH_FT (GIS review 2026-10-07: the impossible values are FFEs, not LAGs). A
    # rejected certificate falls back to the model where the building is model-eligible; record_note says why.
    # A certificate that is not a finished-construction survey (drawings, under construction, stage missing) is a design,
    # not a measurement: never a record; the row falls back to the model, record_note says why (docs/09 Q5 / E7).
    ground_v = b.ground_ft.values
    cert_ffe = r.ffe_ft.values
    has_cert = ~np.isnan(cert_ffe)
    stage = r.record_stage.where(pd.Series(has_cert, index=r.index)).values
    staged = has_cert & (stage != FINISHED)
    rec_raw = has_cert & ~staged
    d_ground = cert_ffe - ground_v
    rec = rec_raw & (np.isnan(ground_v) | ((d_ground >= RECORD_FFH_FT[0]) & (d_ground <= RECORD_FFH_FT[1])))
    rejected = rec_raw & ~rec
    b["record_stage"] = np.where(has_cert, pd.Series(stage).fillna("not_stated").values, None)
    ffh_cert = (r.ffe_ft - r.cert_lag_ft).values
    ffh_ok = rec & ~np.isnan(ffh_cert) & (ffh_cert >= RECORD_FFH_FT[0]) & (ffh_cert <= RECORD_FFH_FT[1])
    model_floor = ~rec & elig
    b["ffh_ft"] = np.where(ffh_ok, ffh_cert, np.where(model_floor, p, np.nan))
    b["ffh_class"] = np.where(ffh_ok, "record", np.where(model_floor, "modeled", None))
    b["ffh_source"] = np.where(ffh_ok, cert_src + " minus its own lowest adjacent grade",
                               np.where(model_floor, f"model {version} (lidar + DOR records)", None))
    b["ffh_vintage"] = np.where(ffh_ok, issued, np.where(model_floor, lidar_vint, None))
    b["ffh_band_lo"] = np.where(model_floor, plo, np.nan)
    b["ffh_band_hi"] = np.where(model_floor, phi, np.nan)
    oid_s = r.cert_objectid.astype("Int64").astype(str)
    staged_note = ("FDEM certificate OBJECTID " + oid_s + " not used as a record: its stage is "
                   + pd.Series(stage).fillna("not stated").astype(str).str.replace("_", " ")
                   + " (a design or a survey before completion, not the finished building); its floor "
                   + pd.Series(cert_ffe).round(2).astype(str) + " ft NAVD88")
    b["record_note"] = np.where(staged, staged_note, np.where(
        rejected, "FDEM certificate OBJECTID " + oid_s + " not used: its floor " + pd.Series(cert_ffe).round(2).astype(str)
        + " ft NAVD88 is " + pd.Series(d_ground).round(2).astype(str) + f" ft from the lidar ground (outside "
        f"{RECORD_FFH_FT[0]:g}..{RECORD_FFH_FT[1]:g} ft)",
        np.where(rec & ~ffh_ok & r.cert_lag_ft.isna().values, "certificate has no usable lowest adjacent grade: no record "
                 "floor height (its floor elevation is used)",
                 np.where(rec & ~ffh_ok, "certificate floor minus its own lowest adjacent grade = "
                          + pd.Series(ffh_cert).round(2).astype(str) + f" ft, outside {RECORD_FFH_FT[0]:g}.."
                          f"{RECORD_FFH_FT[1]:g} ft: no record floor height (its floor elevation is used)", None))))
    ffe = np.where(rec, cert_ffe, np.where(model_floor, ground_v + p, np.nan))
    b["ffe_ft"] = ffe
    b["ffe_class"] = np.where(rec, "record", np.where(model_floor, "modeled", None))
    b["ffe_source"] = np.where(rec, cert_src, np.where(model_floor, f"ground_ft + modeled ffh_ft (model {version})", None))
    b["ffe_vintage"] = np.where(rec, issued, np.where(model_floor, lidar_vint, None))
    b["ffe_band_lo"] = np.where(model_floor, ground_v + plo, np.nan)
    b["ffe_band_hi"] = np.where(model_floor, ground_v + phi, np.nan)
    b["record_vintage_note"] = np.where(rec, note, None)
    b["ffe_datum"] = np.where(rec, "NAVD88 ft (certificate, vertical datum filtered to NAVD 1988; geoid not stated)",
                              np.where(model_floor, "NAVD88 ft US survey, " + w.geoid.astype(str), None))
    b["ffe_null"] = np.where(b.ffe_ft.notna(), None, np.where(rejected | staged, "not_determinable", why_not))
    b["ffh_null"] = np.where(b.ffh_ft.notna(), None, np.where(rec | rejected | staged, "not_determinable", why_not))
    # conflict screen (train.py's label screen, plus the certificate's own LAG against our ground, review DA6): a
    # conflicting certificate keeps its value but produces no above / below call (docs/09 Q2 / E2)
    lag_off = np.abs(r.cert_lag_ft.values - ground_v)
    screen = ((mm.roof_p95.values - d_ground < 6) | (d_ground < -1)) & ok
    screen = screen | (~np.isnan(lag_off) & (lag_off > CONFLICT_LAG_FT))
    b["ffe_record_lidar_conflict"] = pd.array(np.where(rejected, True, np.where(rec, screen, pd.NA)), dtype="boolean")
    # raised flag: from the record floor height where there is one (docs/09 E3, review V1), else the model's
    b["raised_flag"] = pd.array(np.where(ffh_ok, ffh_cert > RAISED_FT, np.where(elig, p > RAISED_FT, pd.NA)),
                                dtype="boolean")
    b["raised_flag_source"] = np.where(ffh_ok, "record ffh_ft > 3 ft", np.where(elig, "model point estimate > 3 ft", None))
    b["raised_flag_null"] = np.where(b.raised_flag.notna(), None, why_not)
    b["lift_or_rebuild"] = pd.array([pd.NA] * len(b), dtype="boolean")
    b["lift_or_rebuild_null"] = "not_evaluated"  # one lidar flight (owner answer 3); so no record is marked stale

    # ---------------------------------------------------------------- floor vs BFE
    bfe = b.bfe_ft.values
    blo, bhi = b.bfe_band_lo.fillna(b.bfe_ft).values, b.bfe_band_hi.fillna(b.bfe_ft).values  # static: lo = hi = BFE
    flo, fhi = b.ffe_band_lo.fillna(b.ffe_ft).values, b.ffe_band_hi.fillna(b.ffe_ft).values  # record: lo = hi = FFE
    banded = b.ffe_band_lo.notna().values | b.bfe_band_lo.notna().values
    b["floor_minus_bfe_ft"] = ffe - bfe
    b["floor_minus_bfe_band_lo"] = np.where(banded, flo - bhi, np.nan)
    b["floor_minus_bfe_band_hi"] = np.where(banded, fhi - blo, np.nan)
    sig = np.nan_to_num(b.bfe_precision_ft.values.astype(float))
    have = b.touches_sfha.values & ~np.isnan(bfe) & ~np.isnan(ffe)
    rec_call = np.where(np.abs(ffe - bfe) < Z90 * sig, "too_close",
                        np.where(ffe >= bhi, "above", np.where(ffe < blo, "below", "too_close")))
    mod_call = np.where(flo >= bhi, "above", np.where(fhi < blo, "below", "too_close"))
    call = np.where(~b.touches_sfha.values, "not_applicable", np.where(have, np.where(rec, rec_call, mod_call), None))
    conflict = b.ffe_record_lidar_conflict.fillna(False).values.astype(bool) & rec
    rep["calls_nulled_for_conflict"] = {k: int(((call == k) & conflict).sum()) for k in ("above", "below", "too_close")}
    call = np.where(conflict & have, None, call)
    b["bfe_call"] = call
    b["bfe_call_basis"] = np.where(have & ~conflict, np.where(rec, "record", "modeled_band")
                                   + np.where(b.bfe_method.values == "interpolated", "+interpolated_bfe", ""), None)
    b["bfe_call_null"] = np.where(pd.isna(call), np.where(conflict & have, "not_determinable",
                                                          np.where(np.isnan(bfe), b.bfe_null, b.ffe_null)), None)

    # ---------------------------------------------------------------- addresses
    def read_addr():
        x0, y0, x1, y1 = shapely.total_bounds(g)
        return c.execute(f"""SELECT number, street, coalesce(postal_city, city) AS city, postcode, lon, lat
            FROM read_parquet('{bk}/{ADDR}') WHERE lon BETWEEN {x0} AND {x1} AND lat BETWEEN {y0} AND {y1}""").df()
    ad = cached(OUT / f"addresses_raw_{fips}.parquet", read_addr)
    ai, bi = shapely.STRtree(g).query(shapely.points(ad.lon.values, ad.lat.values), predicate="within")
    tr = Transformer.from_crs("EPSG:4326", ALBERS, always_xy=True)
    ax, ay = tr.transform(ad.lon.values[ai], ad.lat.values[ai])
    bx, by = tr.transform(b.lon.values[bi], b.lat.values[bi])
    pick = pd.DataFrame({"b": bi, "a": ai, "d": np.hypot(ax - bx, ay - by)}).sort_values(["b", "d"])
    n_pts = pick.groupby("b").size()
    pick = pick.drop_duplicates("b")
    ap_ = ad.iloc[pick.a.values]
    line = (ap_.number.fillna("") + " " + ap_.street.fillna("")).str.strip() + ", " + ap_.city.fillna("") + " " + ap_.postcode.fillna("")
    addr = pd.Series(None, index=b.index, dtype=object)
    asrc = addr.copy()
    addr.iloc[pick.b.values] = line.str.strip().values
    asrc.iloc[pick.b.values] = "overture_addresses (point in footprint)"
    situs = pcol.phy_addr1.fillna("").str.strip()
    use = addr.isna().values & (situs != "").values
    addr[use] = (situs + ", " + pcol.phy_city.fillna("") + " " + pcol.phy_zipcd.astype(str).str[:5].fillna(""))[use].str.strip().values
    asrc[use] = "fl_parcels situs address (DOR NAL)"
    gpath = OUT / f"geocodio_{fips}.parquet"
    if gpath.exists():
        gc = pd.read_parquet(gpath).set_index("building_id")
        gi = b.building_id.map(gc.address)
        use = addr.isna().values & gi.notna().values
        addr[use] = gi[use].values
        asrc[use] = ("geocodio reverse (" + b.building_id.map(gc.source).fillna("") + ", "
                     + b.building_id.map(gc.accuracy_type).fillna("") + ")")[use]
    b["address"], b["address_source"] = addr.values, asrc.values
    b["address_points_in_footprint"] = n_pts.reindex(range(len(b))).fillna(0).astype(int).values
    b["address_null"] = np.where(addr.notna(), None, "not_evaluated")  # until geocodio.py has run
    rep["addresses"] = b.address_source.fillna("none").value_counts().to_dict()
    rep["addresses_missing_in_risk_area"] = int((addr.isna().values & risk).sum())

    # ---------------------------------------------------------------- provenance
    lic = []
    for i in range(len(b)):
        s = [LIC["bldg"], LIC["nfhl"]]
        if risk[i]:
            s.append(LIC["3dep"])
        if has_p[i]:
            s.append(LIC["dor"])
        if has_cert[i]:
            s.append(LIC["fdem"])
        src = asrc.iat[i]
        if isinstance(src, str):
            s.append(LIC["oaddr"] if src.startswith("overture") else LIC["geocodio"] if src.startswith("geocodio") else LIC["dor"])
            if "OpenStreetMap" in src:
                s.append(LIC["osm"])
        lic.append(sorted(set(s)))
    b["input_licences"] = lic
    # provider: "public" only when every input is open; else the restricted providers this row used (review S3):
    # FDEM via Forerunner (internal, non-commercial terms) and Geocodio (paid, stored per its terms)
    restricted = [("fdem_forerunner" if LIC["fdem"] in s else "") + ("+geocodio" if LIC["geocodio"] in s else "")
                  for s in lic]
    b["provider"] = [x.strip("+") or "public" for x in restricted]
    b["model_version"] = np.where(elig, version, None)
    b["release"] = a.release

    # ---------------------------------------------------------------- report
    def vc(col):
        return {("<null>" if pd.isna(k) else str(k)): int(v) for k, v in b[col].value_counts(dropna=False).items()}
    sf = b.touches_sfha & b.in_risk_area
    rep["floor"] = {"model_eligible": int(elig.sum()), "record": int(rec.sum()),
                    "record_without_cert_lag": int((rec & r.cert_lag_ft.isna().values).sum()),
                    "certificates_matched": int(has_cert.sum()),
                    "certificates_by_stage": pd.Series(stage[has_cert]).fillna("not_stated").value_counts().to_dict(),
                    "certificates_not_finished_fallback": int(staged.sum()),
                    "certificates_rejected_vs_lidar": int(rejected.sum()),
                    "record_ffh_not_usable": int((rec & ~ffh_ok).sum()),
                    "record_lidar_conflict": int(b.ffe_record_lidar_conflict.sum()),
                    "record_issue_date_unknown": int((rec & ~issued_ok.values).sum()),
                    "record_issue_date_llm_estimate": int((rec & note.notna().values).sum()),
                    "record_issue_date_still_unknown": int((rec & (issued == "unknown").values).sum()), "ffh_class": vc("ffh_class"),
                    "ffh_null": vc("ffh_null"), "raised_flag": vc("raised_flag"),
                    "modeled_band_width_median_ft": round(float(np.nanmedian(phi - plo)), 2),
                    "record_cert_lag_minus_lidar_ground_median_ft": round(float(np.nanmedian(r.cert_lag_ft - ground_v)), 2)}
    rep["bfe_call"] = {"all": vc("bfe_call"), "basis": vc("bfe_call_basis"), "null": vc("bfe_call_null"),
                       "sfha_buildings": int(sf.sum()),
                       "sfha_decided_share": round(float(b.bfe_call[sf].isin(["above", "below"]).mean()), 3)}
    rep["seconds"] = round(time.time() - t0)

    # ---------------------------------------------------------------- parcel table
    pga = projected(pg, ALBERS)
    key = pd.Series(shapely.to_wkb(pg)).map(hash)
    ug = key.drop_duplicates()
    upr = overlay(pga[ug.index.values], zg)
    upr["share"] = upr.area / shapely.area(pga[ug.index.values])[upr.a]
    upr["zone"] = z.fld_zone.values[upr.p]
    upr["sfha"] = z.sfha_tf.values[upr.p] == "T"
    uz = upr.groupby(["a", "zone", "sfha"]).share.sum().reset_index().sort_values(["a", "share"], ascending=[True, False])
    uz["rec"] = [{"zone": zz, "sfha": bool(s), "share": round(float(v), 4)} for zz, s, v in zip(uz.zone, uz.sfha, uz.share, strict=True)]
    gid = pd.Series(range(len(ug)), index=ug.values)
    pa["geom_group"] = key.map(gid).values
    pa["zones"] = lists(uz.groupby("a").rec.agg(list), pa.geom_group.values)
    bp = overlay(ga, pga[ug.index.values])
    bp["share"] = bp.area / b.footprint_area_m2.values[bp.a]
    bp = bp[bp.share >= 0.1]
    spans = bp.groupby("a").size()
    b["spans_parcels"] = (spans.reindex(range(len(b))).fillna(0) > 1).values
    bp = bp.merge(pd.DataFrame({"p": pa.geom_group.values, "parcel_key": pa.parcel_key.values}), on="p")
    bp["call"] = b.bfe_call.values[bp.a]
    bp["area"] = b.footprint_area_m2.values[bp.a]
    agg = pd.crosstab(bp.parcel_key, bp.call.fillna("unknown")).reindex(columns=["below", "above", "too_close"], fill_value=0)
    agg["buildings"] = bp.groupby("parcel_key").size()
    prim = bp.sort_values("area", ascending=False).drop_duplicates("parcel_key").set_index("parcel_key").a
    agg["primary_building_id"] = b.building_id.values[prim.reindex(agg.index).values]
    out_p = pa[["parcel_key", "parcel_id", "dor_uc", "geom_group", "zones"]].rename(columns={"parcel_id": "parcel_id_native"})
    out_p = out_p.merge(agg.reset_index(), on="parcel_key", how="left")
    out_p["buildings"] = out_p.buildings.fillna(0).astype(int)
    out_p["any_building_below_bfe"] = out_p.below.fillna(0) > 0
    out_p["release"] = a.release
    # one row per (parcel_key, geom_group): fl_parcels carries a few exact duplicate units (r0: 254 rows; docs/07 DA4)
    out_p = out_p.drop_duplicates(["parcel_key", "geom_group"]).reset_index(drop=True)
    a.out.mkdir(parents=True, exist_ok=True)
    out_p.to_parquet(a.out / f"parcels_{fips}.parquet", index=False)
    rep["parcel_table"] = {"rows": len(out_p), "distinct_geometries": len(ug), "with_building": int((out_p.buildings > 0).sum()),
                           "any_building_below_bfe": int(out_p.any_building_below_bfe.sum()),
                           "buildings_spanning_parcels": int(b.spans_parcels.sum())}

    gdf = gpd.GeoDataFrame(b.drop(columns="wkb"), geometry=g, crs="OGC:CRS84")
    path = a.out / f"buildings_{fips}.parquet"
    gdf.to_parquet(path, index=False)
    # provenance inside the file itself (so a consumer pinning the file's hash can prove every parent's edition)
    import pyarrow.parquet as pq
    t = pq.read_table(path)
    prov = {"producer": "spatia-flood pipeline/assemble/assemble.py", "fips": fips, "run": run, "release": a.release,
            "built": rep["built"], "model_version": version, "inputs": rep["inputs"],
            "lidar_workunits": rep["lidar"]["workunits"], "gate": rep["gate_recheck"], "accuracy": accuracy}
    t = t.replace_schema_metadata({**(t.schema.metadata or {}), b"spatia_flood": json.dumps(prov, default=str).encode()})
    pq.write_table(t, path)
    (REPORT / f"assemble_{fips}_{a.release}.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str))


if __name__ == "__main__":
    main()
