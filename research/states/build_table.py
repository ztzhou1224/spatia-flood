"""One table of single-family houses with a MEASURED first living floor, five places, one set of national inputs.

Target y = first living floor - ground next to the house (ft), from each place's own measurement:
  FL   FDEM elevation certificates, diagrams 1A / 1B / 5 only (where 'top of bottom floor' is the living floor);
       ground = certificate lowest adjacent grade
  NC   NC Risk Building Footprints, field-measured FFE (survey, certificate, laser, terrestrial lidar), RES1;
       ground = LIDAR_LAG (aerial lidar lowest adjacent grade)
  VA   Hampton Roads elevation certificates, residential; FFE (first finished floor) - LAG
  NYC  Staten Island, NYC BES measured buildings matched to an NSI RES1 point; z_floor - z_grade
  HAR  Harris County areas B and C (HCFCD front-door floor, precision tiers A+B); ground = 2018 lidar lowest ring
Inputs (the same national sources everywhere, never the answer key): NSI nearest RES1 point within 30 m
(foundation type, default foundation height, stories, median year built, NSI ground), the house's own year built
from parcel / city records where published (else NSI), FEMA flood zone and BFE (FL from the certificate's map BFE,
NC / VA from the published map BFE fields, NYC from NFHL converted NGVD29 -> NAVD88 (-1.08 ft, VDatum),
HAR from NFHL), BFE - NSI ground. Spatial block = 0.05 deg grid cell.
Output: data/states/houses_all.parquet.  Usage: python build_table.py
"""
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from pyproj import Transformer
from sklearn.neighbors import KDTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "coverage"))
sys.path.insert(0, str(HERE.parent / "harris_mini"))
ROOT = HERE.parents[1]
D = ROOT / "data"
S = D / "states"
FT = {"S": 0, "C": 1, "B": 2, "P": 3, "I": 4, "W": 5}
COLS = ["state", "block", "lon", "lat", "y", "nsi_ft", "nsi_fh", "nsi_story", "nsi_year", "year", "sfha", "ve", "bfe_minus_ground"]


def nsi_match(lon, lat, nsi, epsg):
    t = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    n = nsi[nsi.occtype.astype(str).str.startswith("RES1")].reset_index(drop=True)
    nx, ny = t.transform(n.x.values, n.y.values)
    px, py = t.transform(np.asarray(lon, float), np.asarray(lat, float))
    d, i = KDTree(np.c_[nx, ny]).query(np.c_[px, py], k=1)
    m = n.iloc[i[:, 0]].reset_index(drop=True)
    return pd.DataFrame({"nsi_dist": d[:, 0], "nsi_ft": m.found_type.map(FT).values, "nsi_fh": pd.to_numeric(m.found_ht, errors="coerce").values,
                         "nsi_story": pd.to_numeric(m.num_story, errors="coerce").values,
                         "nsi_year": pd.to_numeric(m.med_yr_blt, errors="coerce").values,
                         "nsi_ground": pd.to_numeric(m.ground_elv, errors="coerce").values})


def zone_flags(z):
    z = pd.Series(z).astype(str).str.upper().str.strip()
    return z.str.match(r"^(A|V)").astype(float), z.str.startswith("V").astype(float)


def finish(d, state):
    d = d.assign(state=state, block=state + "_" + (d.lon // 0.05).astype(int).astype(str) + "_" + (d.lat // 0.05).astype(int).astype(str))
    d["year"] = d.year.where(d.year.between(1800, 2026), d.nsi_year)
    d["bfe_minus_ground"] = d.bfe - d.nsi_ground
    d = d[(d.nsi_dist <= 30) & d.y.between(-3, 25)]
    print(f"{state}: {len(d)} houses; y q10/50/90 {np.percentile(d.y, [10, 50, 90]).round(1)}; raised (> 6 ft) {(d.y > 6).mean():.0%}; "
          f"with BFE {d.bfe.notna().mean():.0%}; own year built {d.year.ne(d.nsi_year).mean():.0%}", flush=True)
    return d[COLS]


def fl():
    import fl_lidar
    ec = fl_lidar.load()
    keep = ec.buildingDiagramNumber.astype(str).str.upper().str.strip().str.match(r"^(1A|1B|5)")
    ec = ec[keep]
    sfha, ve = zone_flags(ec.floodZone)
    d = pd.DataFrame({"lon": ec.lon.values, "lat": ec.lat.values, "y": (ec.floor - ec.lag).values, "year": ec.year.values,
                      "bfe": ec.bfe.values, "sfha": sfha.values, "ve": ve.values,
                      "nsi_dist": ec.nsi_dist.values, "nsi_ft": ec.nsi_found_type.map(FT).values, "nsi_fh": ec.nsi_found_ht.values,
                      "nsi_story": pd.to_numeric(ec.nsi_num_story, errors="coerce").values,
                      "nsi_year": pd.to_numeric(ec.nsi_med_yr_blt, errors="coerce").values, "nsi_ground": ec.nsi_ground_elv.values})
    return finish(d, "FL")


def nc():
    n = pd.read_parquet(S / "nc_measured.parquet")
    n = n[n.OCCUP_TYPE_name.astype(str).str.startswith("RES1")].reset_index(drop=True)
    sfha, ve = zone_flags(n.FLD_ZONE)
    bfe = pd.to_numeric(n.STATIC_BFE, errors="coerce")
    d = pd.DataFrame({"lon": n.lon, "lat": n.lat, "y": n.FFE - n.LIDAR_LAG, "year": pd.to_numeric(n.YEAR_BUILT, errors="coerce"),
                      "bfe": bfe.where(bfe > -9000), "sfha": sfha, "ve": ve})
    d = pd.concat([d, nsi_match(d.lon, d.lat, pd.read_parquet(S / "nsi_37.parquet"), 32617)], axis=1)
    return finish(d, "NC")


def va():
    v = pd.read_parquet(S / "va_ec.parquet")
    v = v[(v.BLDG_USE == "Residential") & v.FFE.gt(0) & v.LAG.gt(-50) & v.LAT.notna() & v.LON.notna()].reset_index(drop=True)
    sfha, ve = zone_flags(v.NEW_FLD_ZONE.fillna(v.EC_FLOOD_ZONE))
    bfe = pd.to_numeric(v.NEW_STATIC_BFE_88, errors="coerce")
    d = pd.DataFrame({"lon": v.LON, "lat": v.LAT, "y": v.FFE - v.LAG, "year": pd.to_numeric(v.RESYRBLT, errors="coerce"),
                      "bfe": bfe.where(bfe > -9000), "sfha": sfha, "ve": ve})
    d = pd.concat([d, nsi_match(d.lon, d.lat, pd.read_parquet(S / "nsi_51.parquet"), 32618)], axis=1)
    return finish(d, "VA")


def nyc():
    b = pd.read_parquet(S / "si_bes.parquet")
    for c in ("z_floor", "z_grade", "latitude", "longitude"):
        b[c] = pd.to_numeric(b[c], errors="coerce")
    b = b.dropna(subset=["z_floor", "z_grade", "latitude", "longitude"]).reset_index(drop=True)
    b["bin"] = pd.to_numeric(b.bin, errors="coerce").astype("Int64").astype(str)
    yr = pd.read_parquet(S / "si_year.parquet")
    yr["bin"] = pd.to_numeric(yr.bin, errors="coerce").astype("Int64").astype(str)
    yr = yr.drop_duplicates("bin").set_index("bin").construction_year
    z = pd.read_parquet(S / "si_nfhl.parquet")
    con = duckdb.connect(); con.execute("LOAD spatial")
    con.register("z", z)
    con.register("pts", pd.DataFrame({"i": np.arange(len(b)), "lon": b.longitude.values, "lat": b.latitude.values}))
    j = con.execute("""select pts.i, z.zone, z.bfe, z.datum from pts join z
                       on ST_Intersects(ST_GeomFromGeoJSON(z.gj), ST_Point(pts.lon, pts.lat))""").df()
    j["sfha"], j["ve"] = zone_flags(j.zone)
    # NFHL tags the Staten Island BFEs NGVD29; NOAA VDatum gives -1.08 ft to NAVD88 here (research/coverage/postfirm_test.py)
    j["bfe88"] = np.where((j.bfe > -9000) & (j.bfe <= 40), j.bfe - np.where(j.datum == "NGVD29", 1.08, 0.0), np.nan)
    g = j.groupby("i").agg(sfha=("sfha", "max"), ve=("ve", "max"), bfe=("bfe88", "max")).reindex(range(len(b)))
    d = pd.DataFrame({"lon": b.longitude, "lat": b.latitude, "y": b.z_floor - b.z_grade,
                      "year": pd.to_numeric(b.bin.map(yr), errors="coerce"), "bfe": g.bfe.values,
                      "sfha": g.sfha.fillna(0).values, "ve": g.ve.fillna(0).values})
    d = pd.concat([d, nsi_match(d.lon, d.lat, pd.read_parquet(S / "si_nsi.parquet"), 32618)], axis=1)
    d = d[d.nsi_dist <= 20]  # BES is a building centroid; keep buildings whose own NSI RES1 point is close
    return finish(d, "NYC")


def har():
    import evaluate_cov as ecv
    out = []
    for a in ("B", "C"):
        t = ecv.load(a)
        t = t[t.tier != "C"]
        sfha, ve = zone_flags(t.zone.astype(str).str.replace("SFHA", "A"))
        out.append(pd.DataFrame({"lon": t.lon.values, "lat": t.lat.values, "y": (t.ffe - t.e2018_lag).values,
                                 "year": pd.to_numeric(t.year_built, errors="coerce").values, "bfe": t.bfe.values,
                                 "sfha": sfha.values, "ve": ve.values, "nsi_dist": 0.0,
                                 "nsi_ft": t.nsi_ft.values, "nsi_fh": pd.to_numeric(t.nsi_found_ht, errors="coerce").values,
                                 "nsi_story": t.nsi_stories.values, "nsi_year": t.nsi_year.values,
                                 "nsi_ground": pd.to_numeric(t.nsi_ground, errors="coerce").values}))
    return finish(pd.concat(out, ignore_index=True), "HAR")


def main():
    t = pd.concat([fl(), nc(), va(), nyc(), har()], ignore_index=True)
    t.to_parquet(S / "houses_all.parquet", index=False)
    print(f"total {len(t)}: {t.state.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
