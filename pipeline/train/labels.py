"""Phase 1: labels and public records per building for one county (inputs to train.py).

Labels (record class; the TARGET only, never a feature): FDEM public elevation certificates (data/fl/ec_all.json from
fetch_fdem.py; its fetch date / layer edit date / count go into the report), residential, vertical datum NAVD 1988.
"Latest wins" (r1 plan docs/09 B1, review I1): certificates are ordered by (issuedAt, OBJECTID), missing issuedAt
first, with a stable sort, and the last one is kept: per property, then per building. So a dated certificate always
beats an undated one, and among equal dates the higher OBJECTID (the later upload) wins; the order is reproducible.
Stage (B2, review S2): `record_stage` = buildingElevationSource. certificates_<FIPS>.parquet keeps the latest
certificate per building whatever its stage (assemble.py shows it, uses it as a record only when finished);
labels_<FIPS>.parquet keeps only those whose stage is finished_construction (a drawing or an under-construction
survey is a design, not a measurement). Each row also carries the lowest floor (C2a `topOfBottomFloor` ->
`lowest_floor_ft`, every diagram), the certificate's own LAG (`cert_lag_ft`) and the enclosure / garage opening fields
(B3). Target = first LIVING floor elevation, ft
NAVD88 (research/harris_mini/fl_build.py): top of bottom floor for building diagrams 1A / 1B / 5, top of next higher
floor for 2-4 and 6-9. Matched to the run's buildings (lidar/prepare.py buildings.parquet, Overture footprints):
point in footprint, else nearest footprint within 10 m (EPSG:6442 metres); one certificate per footprint (latest).
Street address, ZIP, owner name and property id are dropped before anything is written.
Records (record class, features): fl_parcels (spatia-data, Florida DOR NAL 2025) parcel containing the building
centroid: DOR use code, actual year built, living area. Owner fields are never selected.
Outputs: data/flood_v1/train/labels_<FIPS>.parquet, certificates_<FIPS>.parquet, records_<FIPS>.parquet; counts in
pipeline/train/out/labels_<FIPS>.json (with how many buildings' selected certificate changed against --compare, e.g.
r0's labels in data/flood_v1/train_r0/).
Usage: python pipeline/train/labels.py 12103 pinellas_2018 [--compare data/flood_v1/train_r0/labels_12103.parquet]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "phase0"))
from risk_area import connect

OUT = ROOT / "data" / "flood_v1" / "train"
LIVING_BOTTOM = ("1A", "1B", "5")
PARCELS = "layers/state/FL/fl_parcels.parquet"
FINISHED = "finished_construction"
OPENINGS = {
    "crawlspaceSqft": "enclosure_sqft",
    "crawlspaceNumFloodOpenings": "enclosure_flood_openings",
    "crawlspaceNumEngineeredOpenings": "enclosure_engineered_openings",
    "attachedGarageSqft": "garage_sqft",
    "attachedGarageNumFloodOpenings": "garage_flood_openings",
    "breakawayWalls": "breakaway_walls",
}


def latest(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """The last certificate per key under the documented order (issuedAt, OBJECTID), missing issuedAt first."""
    return df.sort_values(["issuedAt", "OBJECTID"], na_position="first", kind="stable").drop_duplicates(
        key, keep="last"
    )


def main(fips: str, run: str, compare: Path | None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (Path(__file__).parent / "out").mkdir(exist_ok=True)
    b = pd.read_parquet(ROOT / "data" / "flood_v1" / "lidar" / run / "buildings.parquet")
    g = shapely.from_wkb(b.wkb.values)
    x0, y0, x1, y1 = shapely.total_bounds(g)
    tr = Transformer.from_crs("EPSG:4326", "EPSG:6442", always_xy=True)
    gm = shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])

    e = pd.DataFrame(json.loads((ROOT / "data" / "fl" / "ec_all.json").read_text()))
    fetch = json.loads((ROOT / "data" / "fl" / "ec_all.meta.json").read_text())
    n_all = len(e)
    assert n_all == fetch["count"], "ec_all.json does not match its meta"
    e = e[
        (e.verticalDatum == "navd_1988")
        & (e.buildingUse == "residential")
        & e.lon.between(x0, x1)
        & e.lat.between(y0, y1)
    ]
    e = latest(e, "propertyId").copy()
    dg = e.buildingDiagramNumber.astype(str).str.strip().str.upper()
    e["diagram"] = dg
    e["ffe_ft"] = np.where(
        dg.isin(LIVING_BOTTOM),
        e.topOfBottomFloor,
        np.where(dg.str[0].isin(list("2346789")), e.topOfNextHigherFloor, np.nan),
    )
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
    m = latest(e[e.building_id.notna()], "building_id")
    keep = [
        "building_id",
        "OBJECTID",
        "issuedAt",
        "diagram",
        "ffe_ft",
        "floodZone",
        "baseFloodElevation",
        "match",
        "buildingElevationSource",
        "topOfBottomFloor",
        "lowestAdjacentGrade",
        "formYear",
        *OPENINGS,
    ]
    cert = (
        m[keep]
        .rename(
            columns={
                "OBJECTID": "cert_objectid",
                "issuedAt": "issued_at",
                "floodZone": "cert_zone",
                "baseFloodElevation": "cert_bfe_ft",
                "buildingElevationSource": "record_stage",
                "topOfBottomFloor": "lowest_floor_ft",
                "lowestAdjacentGrade": "cert_lag_ft",
                "formYear": "form_year",
                **OPENINGS,
            }
        )
        .reset_index(drop=True)
    )
    for col in ("cert_bfe_ft", "lowest_floor_ft", "cert_lag_ft", *OPENINGS.values()):
        cert[col] = pd.to_numeric(cert[col], errors="coerce")
    cert["lowest_floor_ft"] = cert.lowest_floor_ft.where(cert.lowest_floor_ft.between(-20, 200))
    cert["cert_lag_ft"] = cert.cert_lag_ft.where(cert.cert_lag_ft.between(-20, 200))
    cert.to_parquet(OUT / f"certificates_{fips}.parquet", index=False)
    lab = cert[cert.record_stage == FINISHED].reset_index(drop=True)
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

    res = {
        "fips": fips,
        "run": run,
        "buildings": len(b),
        "fdem_records_statewide": n_all,
        "fdem_extract": fetch,
        "selection_rule": "latest by (issuedAt, OBJECTID), missing issuedAt first, stable; per property then building",
        "certificates_residential_navd88_latest_in_bbox_with_target": len(e),
        "matched_within": int((kind == "within").sum()),
        "matched_nearest_10m": int((kind == "nearest_10m").sum()),
        "unmatched": int((match < 0).sum()),
        "certificates_one_per_building": len(cert),
        "certificates_by_stage": cert.record_stage.fillna("null").value_counts().to_dict(),
        "labels_one_per_building_finished_construction": len(lab),
        "certificates_with_lowest_floor": int(cert.lowest_floor_ft.notna().sum()),
        "certificates_with_enclosure_openings": int(cert.enclosure_flood_openings.notna().sum()),
        "diagrams": lab.diagram.value_counts().head(10).to_dict(),
        "buildings_with_parcel": len(rec),
        "residential_parcel_000_009": int((rec.dor_uc < "010").sum()),
    }
    if compare is not None:
        old = pd.read_parquet(compare)[["building_id", "cert_objectid"]]
        j = old.merge(
            cert[["building_id", "cert_objectid", "record_stage"]],
            on="building_id",
            how="outer",
            suffixes=("_old", "_new"),
            indicator=True,
        )
        both = j[j._merge == "both"]
        res["compare"] = {
            "against": str(compare),
            "old_labels": len(old),
            "buildings_in_both": len(both),
            "selected_certificate_changed": int((both.cert_objectid_old != both.cert_objectid_new).sum()),
            "only_old": int((j._merge == "left_only").sum()),
            "only_new_any_stage": int((j._merge == "right_only").sum()),
            "old_labels_now_not_finished": int(both.record_stage.ne(FINISHED).sum()),
        }
    (Path(__file__).parent / "out" / f"labels_{fips}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("run")
    ap.add_argument("--compare", type=Path)
    a = ap.parse_args()
    main(a.fips, a.run, a.compare)
