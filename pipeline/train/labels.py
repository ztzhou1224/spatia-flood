"""Phase 1: labels and public records per building for one county (inputs to train.py).

Labels (record class; the TARGET only, never a feature): FDEM public elevation certificates (data/fl/ec_all.json),
residential, vertical datum NAVD 1988, latest certificate per property. Target = first LIVING floor elevation, ft
NAVD88 (research/harris_mini/fl_build.py): top of bottom floor for building diagrams 1A / 1B / 5, top of next higher
floor for 2-4 and 6-9. Matched to the run's buildings (lidar/prepare.py buildings.parquet, Overture footprints):
point in footprint, else nearest footprint within 10 m (EPSG:6442 metres); one certificate per footprint (latest).
Street address, ZIP, owner name and property id are dropped before anything is written.
Records (record class, features): fl_parcels (spatia-data, Florida DOR NAL 2025) parcel containing the building
centroid: DOR use code, actual year built, living area. Owner fields are never selected.
Outputs: data/flood_v1/train/labels_<FIPS>.parquet, records_<FIPS>.parquet; counts in
pipeline/train/out/labels_<FIPS>.json.
Usage: python pipeline/train/labels.py 12103 pinellas_2018
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "phase0"))
from risk_area import connect  # noqa: E402

OUT = ROOT / "data" / "flood_v1" / "train"
LIVING_BOTTOM = ("1A", "1B", "5")
PARCELS = "layers/state/FL/fl_parcels.parquet"


def main(fips: str, run: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (Path(__file__).parent / "out").mkdir(exist_ok=True)
    b = pd.read_parquet(ROOT / "data" / "flood_v1" / "lidar" / run / "buildings.parquet")
    g = shapely.from_wkb(b.wkb.values)
    x0, y0, x1, y1 = shapely.total_bounds(g)
    tr = Transformer.from_crs("EPSG:4326", "EPSG:6442", always_xy=True)
    gm = shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])

    e = pd.DataFrame(json.loads((ROOT / "data" / "fl" / "ec_all.json").read_text()))
    n_all = len(e)
    e = e[(e.verticalDatum == "navd_1988") & (e.buildingUse == "residential") & e.lon.between(x0, x1) & e.lat.between(y0, y1)]
    e = e.sort_values("issuedAt").drop_duplicates("propertyId", keep="last").copy()
    dg = e.buildingDiagramNumber.astype(str).str.strip().str.upper()
    e["diagram"] = dg
    e["ffe_ft"] = np.where(dg.isin(LIVING_BOTTOM), e.topOfBottomFloor,
                           np.where(dg.str[0].isin(list("2346789")), e.topOfNextHigherFloor, np.nan))
    e["ffe_ft"] = pd.to_numeric(e.ffe_ft, errors="coerce")
    e = e[e.ffe_ft.between(-20, 200)].reset_index(drop=True)
    ex, ey = tr.transform(e.lon.values, e.lat.values)
    pts = shapely.points(ex, ey)
    tree = shapely.STRtree(gm)
    pi, fi = tree.query(pts, predicate="within")
    match = np.full(len(e), -1)
    match[pi[::-1]] = fi[::-1]
    kind = np.where(match >= 0, "within", "").astype(object)
    rest = np.where(match < 0)[0]
    if len(rest):
        ri, rf = tree.query_nearest(pts[rest], max_distance=10, return_distance=False, all_matches=False)
        match[rest[ri]] = rf
        kind[rest[ri]] = "nearest_10m"
    e["building_id"] = np.where(match >= 0, b.building_id.values[np.maximum(match, 0)], None)
    e["match"] = kind
    m = e[e.building_id.notna()].sort_values("issuedAt").drop_duplicates("building_id", keep="last")
    keep = ["building_id", "OBJECTID", "issuedAt", "diagram", "ffe_ft", "floodZone", "baseFloodElevation", "match"]
    lab = m[keep].rename(columns={"OBJECTID": "cert_objectid", "issuedAt": "issued_at", "floodZone": "cert_zone",
                                  "baseFloodElevation": "cert_bfe_ft"}).reset_index(drop=True)
    lab["cert_bfe_ft"] = pd.to_numeric(lab.cert_bfe_ft, errors="coerce")
    lab.to_parquet(OUT / f"labels_{fips}.parquet", index=False)

    c, bk = connect()
    pa = c.execute(f"""SELECT parcel_id, dor_uc, act_yr_blt, tot_lvg_ar, ST_AsWKB(geom) AS wkb
                       FROM read_parquet('{bk}/{PARCELS}')
                       WHERE county_fips = '{fips}' AND bbox.xmax >= {x0} AND bbox.xmin <= {x1}
                         AND bbox.ymax >= {y0} AND bbox.ymin <= {y1}""").df()
    cen = shapely.centroid(g)
    bj, pj = shapely.STRtree(shapely.from_wkb(pa.wkb.map(bytes).values)).query(cen, predicate="within")
    first = pd.DataFrame({"b": bj, "p": pj}).drop_duplicates("b")
    rec = pd.DataFrame({"building_id": b.building_id.values[first.b.values]})
    for col in ("parcel_id", "dor_uc", "act_yr_blt", "tot_lvg_ar"):
        rec[col] = pa[col].values[first.p.values]
    rec["parcels_containing"] = pd.Series(bj).value_counts().reindex(first.b.values).values
    rec.to_parquet(OUT / f"records_{fips}.parquet", index=False)

    res = {"fips": fips, "run": run, "buildings": len(b), "fdem_records_statewide": n_all,
           "certificates_residential_navd88_latest_in_bbox_with_target": len(e),
           "matched_within": int((kind == "within").sum()), "matched_nearest_10m": int((kind == "nearest_10m").sum()),
           "unmatched": int((match < 0).sum()), "labels_one_per_building": len(lab),
           "diagrams": lab.diagram.value_counts().head(10).to_dict(),
           "buildings_with_parcel": len(rec), "residential_parcel_000_009": int((rec.dor_uc < "010").sum())}
    (Path(__file__).parent / "out" / f"labels_{fips}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:3])
