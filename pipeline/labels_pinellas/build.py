"""Clean Pinellas County elevation certificates, match them to buildings, and combine with the FDEM labels.

Record class, TARGET only (never a feature). Input: the raw pages fetch.py saved (no owner / address / name fields
were ever requested). Steps, each counted in pipeline/labels_pinellas/out/build_<FIPS>.json:

1. Vertical datum (C2a-h; feet NAVD88 only, never converted here):
   - `navd88_native`: the county's paired fields C2a_88 / C2a_29 are filled and C2A equals C2a_88, or (no pair)
     VERTICAL_DATUM = NAVD1988. Values: C2a_88 / C2b_88 (pair) or C2A / C2B (no pair).
   - `ngvd29_county_navd88`: the pair is filled and C2A equals C2a_29: the certificate is recorded as NGVD29 and the
     county's own NAVD88 field (C2a_88, C2b_88) holds a converted value (method not documented; the C2a_29 - C2a_88
     offset is reported). Matched and compared with FDEM and lidar, then EXCLUDED from the combined labels: its
     certificate LAG sits below the native group's against lidar ground in every era (datum_route_lidar_check), and
     where FDEM has the same building FDEM holds the C2a_29 number, so one of the two sources double-shifts.
   - dropped: VERTICAL_DATUM NGVD1929 / NGVD1927 without a NAVD88 field (counted), and no stated C2 datum.
   Geoid model: not stated on the certificates (recorded as unknown).
2. Residential: A4_BUILDING_USE = 'RES' (the field says so). Blank / other uses are dropped (counted).
3. Diagram: upper-case, '-', ' ', ',' removed, leading zeros removed; valid = 1A 1B 2 2A-2D 3 4 5 6 7 8 9.
   First LIVING floor as labels.py: 1A / 1B / 5 top of bottom floor (C2a), 2-4 / 6-9 top of next higher floor (C2b).
   The pre-2003 single "1" is not a labels.py diagram and is dropped (counted).
4. Plausible: ffe not null, not 0.0 (blank placeholder), within labels.py's (-20, 200) ft; ffe minus the
   certificate's own LAG (C2f, same datum route) within [-2, 40] ft when the LAG is present (outside = keying /
   unit error). Issue date = D_DATE (section D signature date); dates after the fetch date or before 1970 are set to
   null (counted).
5. One certificate per property (STR_PIN, latest D_DATE; undated never beats dated), bbox of the run's buildings,
   matched as labels.py: point in footprint, else nearest footprint within 10 m, EPSG:6442; one per building (latest).
6. BFE (cert_bfe_ft): B9 when B11_ELEVATION_DATUM = NAVD1988; the county's BFE_CONVERTED_TO_NAVD88 when B11 is
   NGVD1929 and that field is numeric; else null. Kept within (0, 40] ft.
7. Combine with data/flood_v1/train/labels_<FIPS>.parquet (read only): one label per building. Rule: the county
   certificate replaces the FDEM one only when both issue dates are known and the county's is strictly later;
   otherwise FDEM is kept (FDEM wins ties and missing dates).

Outputs: data/flood_v1/labels_pinellas/labels_pinellas_<FIPS>.parquet (county labels, matched),
labels_combined_<FIPS>.parquet (labels_<FIPS> columns + label_source, county_objectid, vertical_datum_route,
licence), pipeline/labels_pinellas/out/build_<FIPS>.json.
Usage: python pipeline/labels_pinellas/build.py 12103 pinellas_2018 2026-10-07
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "flood_v1"
OUTD = DATA / "labels_pinellas"
LIVING_BOTTOM = ("1A", "1B", "5")
VALID = {"1A", "1B", "2", "2A", "2B", "2C", "2D", "3", "4", "5", "6", "7", "8", "9"}
LIC_COUNTY = "pinellas_county_ec:terms_unread"
LIC_FDEM = "fdem_certificates:terms_unread"  # the tag pipeline/assemble/assemble.py uses for FDEM certificates


def load(day: str) -> pd.DataFrame:
    rows = []
    for p in sorted(glob.glob(str(OUTD / "raw" / day / "page_*.json"))):
        for f in json.loads(Path(p).read_text())["features"]:
            a = dict(f["attributes"])
            a["lon"], a["lat"] = f["geometry"]["x"], f["geometry"]["y"]
            rows.append(a)
    return pd.DataFrame(rows)


def stats(s: pd.Series) -> dict:
    s = s.dropna()
    return {"n": len(s), "median": round(float(s.median()), 3) if len(s) else None,
            "within_0.5ft": round(float((s.abs() <= 0.5).mean()), 3) if len(s) else None,
            "within_1ft": round(float((s.abs() <= 1.0).mean()), 3) if len(s) else None}


def main(fips: str, run: str, day: str) -> None:
    res: dict = {"fips": fips, "run": run, "fetched": day}
    e = load(day)
    res["records"] = len(e)
    fetched_ms = pd.Timestamp(day).value // 10**6

    # 1. datum
    tol = 1e-6
    pair = e.C2a_88.notna()
    nat_pair = pair & ((e.C2A_TOP_BOTTOM_FLOOR_EL - e.C2a_88).abs() < tol)
    from29 = pair & ~nat_pair & ((e.C2A_TOP_BOTTOM_FLOOR_EL - e.C2a_29).abs() < tol)
    vd = e.VERTICAL_DATUM.fillna("").str.strip().str.upper()
    nat_vd = ~pair & (vd == "NAVD1988")
    ngvd_only = ~pair & vd.isin(["NGVD1929", "NGVD1927"])
    e["route"] = np.select([nat_pair, from29, nat_vd], ["navd88_native", "ngvd29_county_navd88", "navd88_native"], "")
    e["bottom"] = np.where(pair, e.C2a_88, e.C2A_TOP_BOTTOM_FLOOR_EL)
    e["next"] = np.where(pair, e.C2b_88, e.C2B_TOP_NEXT_HIGHER_FL_EL)
    e["lag"] = np.where(pair, e.C2f_88, e.C2F_LAG_ELEV)
    off = (e.C2a_29 - e.C2a_88)[pair]
    res["datum"] = {"pair_C2a_29_88_filled": int(pair.sum()),
                    "pair_C2A_equals_C2a_88_navd88_native": int(nat_pair.sum()),
                    "pair_C2A_equals_C2a_29_ngvd29_with_county_navd88": int(from29.sum()),
                    "pair_C2A_equals_neither": int((pair & ~nat_pair & ~from29).sum()),
                    "no_pair_VERTICAL_DATUM_NAVD1988": int(nat_vd.sum()),
                    "no_pair_VERTICAL_DATUM_NGVD1929_or_1927_dropped": int(ngvd_only.sum()),
                    "no_pair_VERTICAL_DATUM_NGVD1929_dropped": int((~pair & (vd == "NGVD1929")).sum()),
                    "no_pair_no_stated_datum_dropped": int((~pair & ~nat_vd & ~ngvd_only).sum()),
                    "ngvd29_total_on_certificates": int(from29.sum() + (~pair & (vd == "NGVD1929")).sum()),
                    "offset_C2a_29_minus_C2a_88_ft": {"min": round(float(off.min()), 3),
                                                      "median": round(float(off.median()), 3),
                                                      "max": round(float(off.max()), 3)}}
    e = e[e.route != ""].copy()
    res["after_datum"] = len(e)

    # 2. residential
    use = e.A4_BUILDING_USE.fillna("").str.strip().str.upper()
    res["use_dropped"] = use[use != "RES"].replace("", "(blank)").value_counts().to_dict()
    e = e[use == "RES"].copy()
    res["after_residential"] = len(e)

    # 3. diagram + first living floor
    dg = e.A7_BUILDING_DIAG_NUM.fillna("").str.upper().str.replace(r"[-\s,]", "", regex=True).str.lstrip("0")
    e["diagram"] = dg
    res["diagram_dropped"] = dg[~dg.isin(VALID)].replace("", "(blank)").value_counts().to_dict()
    e = e[dg.isin(VALID)].copy()
    res["after_diagram"] = len(e)
    bottom = e.diagram.isin(LIVING_BOTTOM)
    e["ffe_ft"] = np.where(bottom, e.bottom, e.next)
    e["ffe_field"] = np.where(bottom, "C2a", "C2b")

    # 4. plausibility
    drops = {}
    m = e.ffe_ft.isna()
    drops["ffe_null"] = int(m.sum())
    e = e[~m]
    m = e.ffe_ft == 0
    drops["ffe_zero"] = int(m.sum())
    e = e[~m]
    m = ~e.ffe_ft.between(-20, 200, inclusive="neither")
    drops["ffe_outside_-20_200"] = int(m.sum())
    e = e[~m]
    lag = e.lag.where(e.lag != 0)
    fl = e.ffe_ft - lag
    m = fl.notna() & ~fl.between(-2, 40)
    drops["ffe_minus_own_lag_outside_-2_40"] = int(m.sum())
    drops["ffe_minus_own_lag_outside_examples"] = fl[m].round(2).head(12).tolist()
    e = e[~m].copy()
    res["plausibility_dropped"] = drops
    res["after_plausibility"] = len(e)
    d = pd.to_numeric(e.D_DATE, errors="coerce")
    bad = d.notna() & ((d > fetched_ms) | (d < 0))
    res["issue_date"] = {"field": "D_DATE", "null": int(d.isna().sum()), "set_null_invalid": int(bad.sum()),
                         "invalid_values": pd.to_datetime(d[bad], unit="ms").dt.date.astype(str).tolist()}
    e["issued_at"] = d.where(~bad).astype(float)
    ok = pd.to_datetime(e.issued_at, unit="ms")
    res["issue_date"] |= {"min": str(ok.min().date()), "max": str(ok.max().date()),
                          "by_5yr": ok.dt.year.floordiv(5).mul(5).value_counts().sort_index()
                          .rename(lambda y: str(int(y))).to_dict()}

    # 5. property dedupe, bbox, match (labels.py method)
    b = pd.read_parquet(DATA / "lidar" / run / "buildings.parquet")
    g = shapely.from_wkb(b.wkb.values)
    x0, y0, x1, y1 = shapely.total_bounds(g)
    e = e.sort_values("issued_at", na_position="first")
    pin = e.STR_PIN.fillna("").str.strip()
    dup = (pin != "") & pin.duplicated(keep="last")
    res["older_certificate_same_property_dropped"] = int(dup.sum())
    e = e[~dup]
    inb = e.lon.between(x0, x1) & e.lat.between(y0, y1)
    res["outside_run_bbox"] = int((~inb).sum())
    e = e[inb].reset_index(drop=True)
    res["to_match"] = len(e)
    tr = Transformer.from_crs("EPSG:4326", "EPSG:6442", always_xy=True)
    gm = shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])
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
    res["matched_within"] = int((kind == "within").sum())
    res["matched_nearest_10m"] = int((kind == "nearest_10m").sum())
    res["unmatched"] = int((match < 0).sum())
    mm = e[e.building_id.notna()].sort_values("issued_at", na_position="first")
    res["older_certificate_same_building_dropped"] = int(mm.building_id.duplicated(keep="last").sum())
    mm = mm.drop_duplicates("building_id", keep="last")

    # 6. BFE in NAVD88
    b11 = mm.B11_ELEVATION_DATUM.fillna("").str.strip().str.upper()
    conv = pd.to_numeric(mm.BFE_CONVERTED_TO_NAVD88, errors="coerce")
    bfe = np.where(b11 == "NAVD1988", mm.B9_BASE_FLOOD_ELEVATION, np.where(b11 == "NGVD1929", conv, np.nan))
    bfe = pd.Series(bfe, index=mm.index, dtype=float)
    res["bfe"] = {"navd88_from_B9": int(((b11 == "NAVD1988") & mm.B9_BASE_FLOOD_ELEVATION.notna()).sum()),
                  "navd88_from_county_conversion": int(((b11 == "NGVD1929") & conv.notna()).sum()),
                  "outside_0_40_set_null": int((bfe.notna() & ~bfe.between(0, 40, inclusive="right")).sum())}
    bfe = bfe.where(bfe.between(0, 40, inclusive="right"))
    lab = pd.DataFrame({"building_id": mm.building_id.values, "cert_objectid": pd.array([pd.NA] * len(mm), "Int64"),
                        "issued_at": mm.issued_at.values, "diagram": mm.diagram.values, "ffe_ft": mm.ffe_ft.values,
                        "cert_zone": mm.B8_FLOOD_ZONE.fillna("").str.strip().str.upper().values,
                        "cert_bfe_ft": bfe.values, "match": mm.match.values})
    lab["label_source"] = "pinellas_county"
    lab["county_objectid"] = pd.array(mm.OBJECTID.values, "Int64")
    lab["vertical_datum_route"] = mm.route.values
    lab["ffe_field"] = mm.ffe_field.values
    lab["licence"] = LIC_COUNTY
    res["county_labels_one_per_building"] = len(lab)
    res["county_labels_by_route"] = lab.vertical_datum_route.value_counts().to_dict()
    res["county_labels_diagrams"] = lab.diagram.value_counts().to_dict()
    lab.to_parquet(OUTD / f"labels_pinellas_{fips}.parquet", index=False)

    # 7. combine with FDEM
    fd = pd.read_parquet(DATA / "train" / f"labels_{fips}.parquet")
    fd = fd.assign(cert_objectid=fd.cert_objectid.astype("Int64"), label_source="fdem",
                   county_objectid=pd.array([pd.NA] * len(fd), "Int64"), vertical_datum_route="navd88_fdem",
                   ffe_field="fdem_rule", licence=LIC_FDEM)
    both = fd.merge(lab, on="building_id", suffixes=("_f", "_c"))
    diff = both.ffe_ft_c - both.ffe_ft_f
    same_day = (both.issued_at_c - both.issued_at_f).abs() < 86400000 * 1.5
    agree = {"buildings_in_both": len(both), "all": stats(diff)}
    for r in ("navd88_native", "ngvd29_county_navd88"):
        agree[r] = stats(diff[both.vertical_datum_route_c == r])
    agree["issue_dates_within_1_day"] = stats(diff[same_day])
    agree["issue_dates_differ"] = stats(diff[~same_day & both.issued_at_c.notna() & both.issued_at_f.notna()])
    agree["same_diagram_share"] = round(float((both.diagram_f == both.diagram_c).mean()), 3)
    agree["median_abs_diff"] = round(float(diff.abs().median()), 3)
    agree["share_abs_diff_le_0.5"] = round(float((diff.abs() <= 0.5).mean()), 3)
    agree["share_abs_diff_le_1"] = round(float((diff.abs() <= 1.0).mean()), 3)
    agree["share_abs_diff_gt_3"] = round(float((diff.abs() > 3).mean()), 3)
    res["fdem_agreement"] = agree
    bf = both[both.vertical_datum_route_c == "ngvd29_county_navd88"].merge(
        e[["OBJECTID", "C2a_29"]], left_on="county_objectid_c", right_on="OBJECTID")
    bb = bf.diagram_c.isin(LIVING_BOTTOM)
    agree["ngvd29_route_bottom_floor_fdem_equals_C2a_29"] = int(((bf.ffe_ft_f - bf.C2a_29).abs() < 0.01)[bb].sum())
    agree["ngvd29_route_bottom_floor_n"] = int(bb.sum())

    # datum route vs lidar ground, by certificate era (certificate LAG through the same route minus lidar g_lag)
    gl = pd.read_parquet(DATA / "lidar" / run / "features.parquet", columns=["building_id", "g_lag"])
    lc = mm[["building_id", "lag", "route", "issued_at"]].merge(gl, on="building_id")
    lc = lc[lc.lag.notna() & (lc.lag != 0) & lc.g_lag.notna()]
    era = pd.cut(pd.to_datetime(lc.issued_at, unit="ms").dt.year, [1900, 2004, 2009, 2014, 2030],
                 labels=["<=2004", "2005-09", "2010-14", ">=2015"])
    res["datum_route_lidar_check"] = {
        f"{k[0]} {k[1]}": {"n": int(v["count"]), "median_cert_lag_minus_lidar_lag_ft": round(float(v["median"]), 3)}
        for k, v in (lc.lag - lc.g_lag).groupby([era, lc.route], observed=True).agg(["count", "median"]).iterrows()}
    lab = lab[lab.vertical_datum_route == "navd88_native"].reset_index(drop=True)
    res["county_labels_used_navd88_native"] = len(lab)
    both = both[both.vertical_datum_route_c == "navd88_native"]
    county_wins = set(both.building_id[both.issued_at_c.notna() & both.issued_at_f.notna()
                                       & (both.issued_at_c > both.issued_at_f)])
    res["overlap_rule"] = "county replaces FDEM only when both dates are known and the county's is strictly later"
    res["overlap_county_kept"] = len(county_wins)
    res["overlap_fdem_kept"] = len(both) - len(county_wins)
    comb = pd.concat([fd[~fd.building_id.isin(county_wins)],
                      lab[~lab.building_id.isin(set(fd.building_id) - county_wins)]], ignore_index=True)
    assert comb.building_id.is_unique
    res["combined"] = {"labels": len(comb), "by_source": comb.label_source.value_counts().to_dict(),
                       "new_buildings_from_county": int((~lab.building_id.isin(set(fd.building_id))).sum())}

    # elevated + train.py screen on the new buildings (lidar g_lag; target only)
    f = pd.read_parquet(DATA / "lidar" / run / "features.parquet",
                        columns=["building_id", "g_lag", "lpc_status", "roof_p95"])
    new = lab[~lab.building_id.isin(set(fd.building_id))].merge(f, on="building_id", how="left")
    new["dh"] = new.ffe_ft - new.g_lag
    lid = new.g_lag.notna() & (new.lpc_status == "ok")
    elev_dg = new.diagram.str[0].isin(list("56789"))
    elev = elev_dg | (new.dh > 3)
    fail = lid & ((new.roof_p95 - new.dh < 6) | (new.dh < -1))
    res["new_county_buildings"] = {
        "n": len(new), "elevated_diagram_5_9": int(elev_dg.sum()), "elevated_dh_gt_3": int((new.dh > 3).sum()),
        "elevated_either": int(elev.sum()), "no_lidar_ground_or_points": int((~lid).sum()),
        "fail_train_screen": int(fail.sum()), "fail_screen_dh_lt_-1": int((lid & (new.dh < -1)).sum()),
        "fail_screen_roof_p95_minus_dh_lt_6": int((lid & (new.roof_p95 - new.dh < 6)).sum()),
        "usable_after_screen": int((lid & ~fail).sum()),
        "usable_elevated_either": int((lid & ~fail & elev).sum()),
        "usable_elevated_diagram_5_9": int((lid & ~fail & elev_dg).sum()),
        "by_route_usable": new[lid & ~fail].vertical_datum_route.value_counts().to_dict()}
    fdj = fd.merge(f, on="building_id", how="left")
    fdj["dh"] = fdj.ffe_ft - fdj.g_lag
    lf = fdj.g_lag.notna() & (fdj.lpc_status == "ok")
    ff = lf & ~((fdj.roof_p95 - fdj.dh < 6) | (fdj.dh < -1))
    res["fdem_reference"] = {"n": len(fd), "usable_after_screen": int(ff.sum()),
                             "usable_elevated_diagram_5_9": int((ff & fdj.diagram.str[0].isin(list("56789"))).sum()),
                             "usable_elevated_either": int((ff & (fdj.diagram.str[0].isin(list("56789"))
                                                                  | (fdj.dh > 3))).sum())}
    comb.to_parquet(OUTD / f"labels_combined_{fips}.parquet", index=False)
    out = Path(__file__).parent / "out"
    out.mkdir(exist_ok=True)
    (out / f"build_{fips}.json").write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main(*sys.argv[1:4])
