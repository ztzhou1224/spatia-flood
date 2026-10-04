"""NFIP prior narrowed by house characteristics, still as AGGREGATES (no record is matched to a house).

OpenFEMA terms forbid re-identification, so the prior is a statistic over a group of >= K policies, never
one policy. Groups (most specific first, the first with >= K records is used):
  block group x build era x (BFE - ground) band;  block group x era;  block group x band;  block group;
  tract x era x band;  tract x era;  tract.
Build era: <1975, 1975-94, 1995-2009, 2010+ (NFIP originalConstructionDate; house: parcel / city year built,
else NSI). Band of BFE minus ground (ft): < -1, -1..1, 1..3, 3..5, > 5, no BFE (NFIP: BFE - LAG from the
policy; house: map BFE - lidar or NSI ground).
Per group: median floor height (LFE - LAG), median floor minus BFE (LFE - BFE, 'freeboard'), share elevated.
Renewals repeat a building (about 2-3 rows each), so K = 10 rows is about 4 buildings; K = 30 is also shown.

Estimates compared with nfip_test.py's block-group prior:
  rule: ground + group median height;  rule: BFE + group median freeboard (when a BFE exists, else the first);
  GBM (Florida, county-out; NYC / Harris use the model trained on all Florida) with the group features.
Usage: python nfip_group_test.py [K]
"""
import sys
import time
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
import requests
from sklearn.model_selection import GroupKFold

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harris_mini"))
sys.path.insert(0, str(HERE))
import evaluate_cov as ecv  # noqa: E402
import fl_lidar  # noqa: E402
import nfip_test as nt  # noqa: E402

D = nt.D
P = nt.P
ERAS = [0, 1975, 1995, 2010, 2100]
BANDS = [-1000, -1, 1, 3, 5, 1000]
GF = ["gp_med", "gp_fb", "gp_elev", "gp_n", "gp_lvl"]
LEVELS = [("bg", "era", "band"), ("bg", "era"), ("bg", "band"), ("bg",), ("tract", "era", "band"), ("tract", "era"), ("tract",)]


def era(year):
    return pd.cut(pd.to_numeric(year, errors="coerce"), ERAS, right=False, labels=False).astype("Int64").astype(str)


def band(bfe, ground):
    b = pd.cut(pd.to_numeric(bfe, errors="coerce") - pd.to_numeric(ground, errors="coerce"), BANDS, labels=False)
    return b.astype("Int64").astype(str)  # '<NA>' = no BFE


def nfip_groups(nf):
    nf = nf.assign(bg=nf.censusGeoid, era=era(pd.to_datetime(nf.originalConstructionDate, errors="coerce").dt.year),
                   band=band(nf.baseFloodElevation, nf.lowestAdjacentGrade),
                   fb=nf.lowestFloorElevation - nf.baseFloodElevation)
    out = {}
    for lv in LEVELS:
        g = nf.groupby(list(lv))
        out[lv] = pd.DataFrame({"gp_n": g.size(), "gp_med": g.ffh.median(), "gp_fb": g.fb.median(), "gp_elev": g.elev.mean()})
    return out


def block_groups(lon, lat):
    con = duckdb.connect(); con.execute("LOAD spatial")
    pts = pd.DataFrame({"i": np.arange(len(lon)), "lon": np.asarray(lon, float), "lat": np.asarray(lat, float)})
    con.register("pts", pts)
    bgs = " union all ".join(f"select GEOID, geom from ST_Read('/vsizip/{D}/tiger/tl_2020_{s}_bg.zip/tl_2020_{s}_bg.shp')"
                             for s in ("12", "36", "48"))
    j = con.execute(f"with b as ({bgs}) select pts.i, b.GEOID from pts join b on ST_Intersects(b.geom, ST_Point(pts.lon, pts.lat))").df()
    g = pd.Series(pd.NA, index=range(len(lon)), dtype="string")
    g.loc[j.i.values] = j.GEOID.values
    return g.values


def attach_groups(df, lon, lat, year, bfe, ground, groups, k):
    key = pd.DataFrame({"bg": block_groups(lon, lat)}, index=df.index)
    key["tract"], key["era"], key["band"] = key.bg.str[:11], era(year).values, band(bfe, ground).values
    out = pd.DataFrame(np.nan, index=df.index, columns=GF)
    left = pd.Series(True, index=df.index)
    for i, lv in enumerate(LEVELS):
        s = groups[lv]
        s = s[s.gp_n >= k]
        idx = pd.MultiIndex.from_frame(key[list(lv)]) if len(lv) > 1 else key[lv[0]]
        hit = s.reindex(idx)
        hit.index = df.index
        take = left & hit.gp_n.notna()
        out.loc[take, ["gp_med", "gp_fb", "gp_elev", "gp_n"]] = hit.loc[take, ["gp_med", "gp_fb", "gp_elev", "gp_n"]].values
        out.loc[take, "gp_lvl"] = i
        left &= ~take
    return pd.concat([df, out], axis=1)


def rules(ground, bfe, d):
    r = {"rule: ground + group median height": ground + d.gp_med}
    fb = pd.to_numeric(bfe, errors="coerce") + d.gp_fb
    r["rule: BFE + group median (floor - BFE), else ground + height"] = fb.where(fb.notna(), ground + d.gp_med)
    return r


def nyc_bfe(h):
    """FEMA NFHL flood zones (layer 28) over the test houses; the highest static BFE covering each house."""
    url = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
    x0, y0, x1, y1 = h.longitude.min() - 0.002, h.latitude.min() - 0.002, h.longitude.max() + 0.002, h.latitude.max() + 0.002
    feats, off = [], 0
    while True:
        for attempt in range(6):
            try:
                r = requests.get(url, params=dict(f="geojson", where="1=1", outFields="FLD_ZONE,STATIC_BFE,V_DATUM", returnGeometry="true",
                                                  geometry=f"{x0},{y0},{x1},{y1}", geometryType="esriGeometryEnvelope", inSR=4326, outSR=4326,
                                                  spatialRel="esriSpatialRelIntersects", resultOffset=off, resultRecordCount=500),
                                 timeout=300).json()
                if "features" in r:
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2 ** attempt)
        feats += r["features"]
        if len(r["features"]) < 500:
            break
        off += 500
    con = duckdb.connect(); con.execute("LOAD spatial")
    import json
    z = pd.DataFrame([{"bfe": f["properties"]["STATIC_BFE"], "zone": f["properties"]["FLD_ZONE"], "datum": f["properties"]["V_DATUM"],
                       "gj": json.dumps(f["geometry"])} for f in feats if f["geometry"]])
    print(f"NYC NFHL zones: {len(z)}; datums {z.datum.value_counts().to_dict()}")
    con.register("z", z)
    con.register("pts", pd.DataFrame({"i": np.arange(len(h)), "lon": h.longitude.values, "lat": h.latitude.values}))
    j = con.execute("""select pts.i, max(case when z.bfe > -9000 then z.bfe end) bfe from pts join z
                       on ST_Intersects(ST_GeomFromGeoJSON(z.gj), ST_Point(pts.lon, pts.lat)) group by pts.i""").df()
    out = pd.Series(np.nan, index=range(len(h)))
    out.loc[j.i.values] = j.bfe.astype(float).values
    return out.values


def main(k=10):
    nf = nt.load_nfip()
    groups = nfip_groups(nf)
    print(f"group size K >= {k} records; NFIP rows {len(nf)}")
    one_year = nf[nf.policyEffectiveDate.str[:4] == "2025"]
    nsi = pd.read_parquet(D / "fl" / "nsi_fl.parquet", columns=["occtype"])
    print(f"Florida: NFIP single-family policies with floor + ground effective in 2025: {int((one_year.propertyState == 'FL').sum())}; "
          f"NSI RES1 buildings: {int(nsi.occtype.str.startswith('RES1').sum())}")

    # ---------- Florida ----------
    ec = fl_lidar.load()
    ec = nt.attach(ec, ec.lon, ec.lat, nf)
    ec = attach_groups(ec, ec.lon, ec.lat, ec.year, ec.bfe, ec.nsi_ground_elv, groups, k)
    print(f"Florida certificates {len(ec)}; group level used {ec.gp_lvl.value_counts(dropna=False).sort_index().to_dict()} "
          f"(0 = block group x era x band ... 6 = tract)")
    X = fl_lidar.features(ec).assign(nsi_year=pd.to_numeric(ec.nsi_med_yr_blt, errors="coerce"))
    y = ec.floor - ec.lag
    feats = {"model, no prior": X, "model + block-group prior": pd.concat([X, ec[nt.NF]], axis=1),
             "model + grouped prior": pd.concat([X, ec[nt.NF + GF]], axis=1)}
    pred = {}
    for name, F in feats.items():
        p = pd.Series(np.nan, index=ec.index)
        for tr, te in GroupKFold(5).split(F, groups=ec.county_fips):
            p.iloc[te] = lgb.LGBMRegressor(**P).fit(F.iloc[tr], y.iloc[tr]).predict(F.iloc[te])
        pred[name] = p
    g = pd.read_parquet(D / "fl" / "lidar_ground.parquet")
    t = ec.loc[g.index].join(g)
    ok = t.bfe.notna()

    def fl_rows(mask):
        rows = {}
        est = {k_: t.l_med + v.loc[t.index] for k_, v in pred.items()}
        est["rule: ground + block-group median height"] = t.l_med + t.nf_med
        est.update(rules(t.l_med, t.bfe, t))
        for name, e in est.items():
            r = nt.m(e - t.floor, mask)
            mm = ok & mask & e.notna()
            r["above_below_BFE_right"] = ((e[mm] >= t.bfe[mm]) == (t.floor[mm] >= t.bfe[mm])).mean()
            rows[name] = r
        return rows
    nt.show("Florida 1 m lidar subset: lowest floor elevation error (ft), ground = lidar ring median", fl_rows(pd.Series(True, index=t.index)))
    nt.show(f"Florida 1 m lidar subset, houses whose group has >= 30 records", fl_rows(t.gp_n >= 30))
    for gname in ("1A slab", "1B raised slab", "5-7 elevated", "8 crawlspace"):
        nt.show(f"Florida 1 m lidar subset: {gname}", {k_: {c: v[c] for c in ("n", "MAE", "within_1", "above_below_BFE_right")}
                                                      for k_, v in fl_rows(t.dgroup == gname).items()})

    XP = pd.DataFrame({"ft": X.ft, "fh": X.fh, "stories": X.stories, "nsi_year": X.nsi_year}, index=ec.index)
    port = lgb.LGBMRegressor(**P).fit(pd.concat([XP, ec[nt.NF + GF]], axis=1), y)

    def portable(df):
        xp = pd.DataFrame({"ft": df.nsi_ft, "fh": pd.to_numeric(df.nsi_found_ht, errors="coerce"),
                           "stories": pd.to_numeric(df.nsi_stories, errors="coerce"),
                           "nsi_year": pd.to_numeric(df.nsi_year, errors="coerce")}, index=df.index)
        return port.predict(pd.concat([xp, df[nt.NF + GF]], axis=1))

    # ---------- NYC ----------
    h = pd.read_parquet(D / "nyc" / "nyc_scored.parquet")
    h["bfe"] = nyc_bfe(h)
    h = nt.attach(h, h.longitude, h.latitude, nf)
    h = attach_groups(h, h.longitude, h.latitude, h.year_built, h.bfe, h.e2018_med, groups, k)
    print(f"\nNYC houses {len(h)}; with a map BFE {int(h.bfe.notna().sum())}; group level {h.gp_lvl.value_counts(dropna=False).sort_index().to_dict()}")
    est = {"national: NSI height + lidar median grade (before)": h.e2018_med + h.nsi_found_ht,
           "rule: ground + block-group median height": h.e2018_med + h.nf_med}
    est.update(rules(h.e2018_med, h.bfe, h))
    est["FL model + grouped prior"] = h.e2018_med + portable(h)
    raised = h.ffh > 6
    nt.show("NYC (Staten Island east shore), first floor elevation error (ft)", {k_: nt.m(v - h.ffe) for k_, v in est.items()})
    nt.show("NYC, same houses with a group prior only", {k_: nt.m(v - h.ffe, h.gp_n.notna()) for k_, v in est.items()})
    nt.show("NYC, raised houses (floor > 6 ft above ground)", {k_: nt.m(v - h.ffe, raised) for k_, v in est.items()})
    nt.show("NYC, not raised", {k_: nt.m(v - h.ffe, ~raised) for k_, v in est.items()})

    # ---------- Harris ----------
    for a in ("B", "C"):
        t = ecv.load(a)
        t = t[t.tier != "C"]
        t = nt.attach(t, t.lon, t.lat, nf)
        yr = t.year_built.where(t.year_built > 1800, pd.to_numeric(t.nsi_year, errors="coerce"))
        t = attach_groups(t, t.lon, t.lat, yr, t.bfe, t.e2018_med, groups, k)
        print(f"\nHarris {a}: houses {len(t)}; group level {t.gp_lvl.value_counts(dropna=False).sort_index().to_dict()}")
        est = {"national: NSI height + lidar median grade (before)": t.e2018_med + t.nsi_found_ht,
               "rule: ground + block-group median height": t.e2018_med + t.nf_med}
        est.update(rules(t.e2018_med, t.bfe, t))
        est["FL model + grouped prior"] = t.e2018_med + portable(t)
        nt.show(f"Harris area {a}, front-door floor elevation error (ft)", {k_: nt.m(v - t.ffe) for k_, v in est.items()})
        nt.show(f"Harris area {a}, houses with a group prior", {k_: nt.m(v - t.ffe, t.gp_n.notna()) for k_, v in est.items()})


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
