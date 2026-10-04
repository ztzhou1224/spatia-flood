"""Year built, 'built after the local flood map' (post-FIRM) and permit flags as floor-height signals.

Under NFIP rules a house built in the flood zone after its community's first Flood Insurance Rate Map must have
its lowest floor at or above the BFE. New inputs (all public, none from the answer key):
  firm_year       initial FIRM date of the NFIP community (OpenFEMA NfipCommunityStatusBook)
  post_firm       house year built >= firm_year;  yrs_after_firm = year built - firm_year
  eff_minus_act   Florida only: parcel effective year - actual year built (major renovation)
  NYC permits     elevation / flood filing or post-Sandy new building (research/nyc_permits)
Community: Florida from the certificate's NFIP community number (in a product: the community polygon holding the
house); NYC is one community (360497).

Florida: GBM floor height (floor - LAG) trained on OTHER counties (GroupKFold by county), base features as
fl_lidar.py vs + the new ones; FFE = lidar ring median + height on the 1 m lidar subset.
NYC: no NYC labels used. (a) code rule: in an SFHA with a BFE (NFHL, NGVD29 converted to NAVD88 with VDatum) and post-FIRM or
permit-flagged, floor = max(national estimate, BFE + 1 ft); (b) a portable GBM trained on ALL Florida certificates
(NSI type / height / stories, house year built, post_firm, yrs_after_firm, SFHA, V zone, BFE - NSI ground),
with and without the new features, applied to NYC.
Answer keys (scorer only): FL certificate floor; NYC BES z_floor and z_floor - z_grade.
Usage: python postfirm_test.py
"""
import json
import sys
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
import requests
from sklearn.model_selection import GroupKFold

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fl_lidar  # noqa: E402

ROOT = HERE.parents[1]
D = ROOT / "data"
P = dict(objective="l1", n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=50, subsample=0.8,
         subsample_freq=1, colsample_bytree=0.8, verbose=-1)
NYC_CID = "360497"
SFHA = ("A", "AE", "AH", "AO", "A99", "AR", "V", "VE")


def csb(state):
    p = D / "nfip" / f"csb_{state}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    r = requests.get("https://www.fema.gov/api/open/v1/NfipCommunityStatusBook",
                     params={"$filter": f"state eq '{state}'", "$top": 10000, "$format": "json"}, timeout=300).json()
    d = pd.DataFrame(r["NfipCommunityStatusBook"])[["communityIdNumber", "communityName", "initialFloodInsuranceRateMap"]]
    d["firm_year"] = pd.to_datetime(d.initialFloodInsuranceRateMap, errors="coerce").dt.year
    d.to_parquet(p)
    return d


def nyc_zones(h):
    p = D / "nyc" / "nfhl_zones.parquet"
    if not p.exists():
        url = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
        x0, y0, x1, y1 = h.longitude.min() - .002, h.latitude.min() - .002, h.longitude.max() + .002, h.latitude.max() + .002
        r = requests.get(url, params=dict(f="geojson", where="1=1", outFields="FLD_ZONE,STATIC_BFE,V_DATUM", returnGeometry="true",
                                          geometry=f"{x0},{y0},{x1},{y1}", geometryType="esriGeometryEnvelope", inSR=4326,
                                          outSR=4326, spatialRel="esriSpatialRelIntersects"), timeout=300).json()
        pd.DataFrame([{"zone": f["properties"]["FLD_ZONE"], "bfe": f["properties"]["STATIC_BFE"], "datum": f["properties"]["V_DATUM"],
                       "gj": json.dumps(f["geometry"])} for f in r["features"] if f["geometry"]]).to_parquet(p)
    z = pd.read_parquet(p)
    con = duckdb.connect(); con.execute("LOAD spatial")
    con.register("z", z)
    con.register("pts", pd.DataFrame({"i": np.arange(len(h)), "lon": h.longitude.values, "lat": h.latitude.values}))
    j = con.execute("""select pts.i, z.zone, z.bfe, z.datum from pts join z
                       on ST_Intersects(ST_GeomFromGeoJSON(z.gj), ST_Point(pts.lon, pts.lat))""").df()
    j["sfha"] = j.zone.isin(SFHA)
    # NFHL tags these BFEs NGVD29. NOAA VDatum (NAD27 / NGVD29 -> NAD83(2011) / NAVD88, US ft) at three Staten Island
    # points (-74.09 40.57, -74.07 40.59, -74.115 40.555) turns 10 ft into 8.917 / 8.904 / 8.927 ft, so -1.08 ft.
    # A static BFE above 40 ft (one AE polygon carries 271) is treated as a data error and dropped.
    j["bfe_ok"] = np.where((j.bfe > -9000) & (j.bfe <= 40), j.bfe - np.where(j.datum == "NGVD29", 1.08, 0.0), np.nan)
    g = j.groupby("i").agg(sfha=("sfha", "max"), ve=("zone", lambda s: s.isin(["V", "VE"]).any()), bfe=("bfe_ok", "max"))
    return g.reindex(range(len(h)))


def m(e, mask=None):
    e = pd.Series(e)
    e = (e[mask] if mask is not None else e).dropna()
    return dict(n=len(e), MAE=e.abs().mean(), within_1=(e.abs() <= 1).mean(), bias=e.mean())


def show(title, rows):
    print(f"\n## {title}\n")
    print(pd.DataFrame(rows).T.round(3).to_markdown())


def main():
    fl_csb = csb("FL").set_index("communityIdNumber").firm_year
    # ---------- Florida ----------
    ec = fl_lidar.load()
    ec["firm_year"] = ec.nfipCommunityNumber.astype(str).str[:6].map(fl_csb)
    ec["post_firm"] = (ec.year >= ec.firm_year).astype(float).where(ec.firm_year.notna() & ec.year.notna())
    ec["yrs_after_firm"] = ec.year - ec.firm_year
    ec["eff_minus_act"] = pd.to_numeric(ec.eff_yr_blt, errors="coerce") - pd.to_numeric(ec.act_yr_blt, errors="coerce")
    print(f"Florida certificates {len(ec)}; with a community FIRM year {ec.firm_year.notna().mean():.1%}; "
          f"post-FIRM {ec.post_firm.mean():.1%}")
    X = fl_lidar.features(ec)
    XN = X.assign(post_firm=ec.post_firm, yrs_after_firm=ec.yrs_after_firm, eff_minus_act=ec.eff_minus_act)
    y = ec.floor - ec.lag
    pred = {}
    for name, F in (("model (as before)", X), ("model + post-FIRM features", XN)):
        p = pd.Series(np.nan, index=ec.index)
        for tr, te in GroupKFold(5).split(F, groups=ec.county_fips):
            p.iloc[te] = lgb.LGBMRegressor(**P).fit(F.iloc[tr], y.iloc[tr]).predict(F.iloc[te])
        pred[name] = p
    show("Florida floor height above the certificate's ground (ft), county-out", {k: m(v - y) for k, v in pred.items()})
    for gname in ("1A slab", "1B raised slab", "5-7 elevated", "8 crawlspace"):
        show(f"Florida floor height: {gname}", {k: m(v - y, ec.dgroup == gname) for k, v in pred.items()})
    g = pd.read_parquet(D / "fl" / "lidar_ground.parquet")
    t = ec.loc[g.index].join(g)
    ok = t.bfe.notna()
    rows = {}
    for k, v in pred.items():
        est = t.l_med + v.loc[t.index]
        r = m(est - t.floor)
        r["above_below_BFE_right"] = ((est[ok] >= t.bfe[ok]) == (t.floor[ok] >= t.bfe[ok])).mean()
        rows[k] = r
    show("Florida 1 m lidar subset: lowest floor elevation error (ft)", rows)

    # ---------- portable model on all Florida certificates ----------
    def portable(df, year, post, yaf, sfha, ve, bfe_g):
        return pd.DataFrame({"ft": df.nsi_ft, "fh": pd.to_numeric(df.nsi_found_ht, errors="coerce"),
                             "stories": pd.to_numeric(df.nsi_stories, errors="coerce"), "year": year, "post_firm": post,
                             "yrs_after_firm": yaf, "sfha": sfha, "ve": ve, "bfe_minus_ground": bfe_g}, index=df.index)
    fl_p = portable(ec.assign(nsi_ft=ec.nsi_found_type.map(fl_lidar.FT), nsi_stories=ec.nsi_num_story), ec.year, ec.post_firm,
                    ec.yrs_after_firm, ec.sfha.astype(float), ec.floodZone.astype(str).str.upper().str.startswith("V").astype(float),
                    ec.bfe - ec.nsi_ground_elv)
    base_cols = ["ft", "fh", "stories", "year", "sfha", "ve", "bfe_minus_ground"]
    port = {"FL-trained model, no post-FIRM": (base_cols, lgb.LGBMRegressor(**P).fit(fl_p[base_cols], y)),
            "FL-trained model + post-FIRM": (list(fl_p.columns), lgb.LGBMRegressor(**P).fit(fl_p, y))}

    # ---------- NYC ----------
    h = pd.read_parquet(D / "nyc" / "nyc_scored.parquet")
    h["bin"] = pd.to_numeric(h.bin, errors="coerce").astype("Int64").astype(str)
    z = nyc_zones(h)
    h["sfha"], h["ve"], h["bfe"] = z.sfha.fillna(False).astype(float).values, z.ve.fillna(False).astype(float).values, z.bfe.values
    firm = int(csb("NY").set_index("communityIdNumber").firm_year[NYC_CID])
    pm = pd.read_parquet(D / "nyc" / "permits.parquet")
    pm["date"] = pd.to_datetime(pm.pre__filing_date.fillna(pm.filing_date), errors="coerce")
    flag = set(pm.bin[pm.elev_permit | (pm.job_type.fillna("").str.upper().isin(["NB", "NEW BUILDING"]) & (pm.date >= "2012-11-01"))])
    h["permit_flag"] = h.bin.isin(flag)
    yr = pd.to_numeric(h.year_built, errors="coerce")
    h["post_firm"] = (yr >= firm).astype(float).where(yr.notna())
    print(f"\nNYC houses {len(h)}; first FIRM {firm}; post-FIRM {h.post_firm.mean():.0%}; in SFHA {h.sfha.mean():.0%}; "
          f"with a NAVD88 BFE {h.bfe.notna().mean():.0%}; permit-flagged {h.permit_flag.mean():.1%}")
    true_h = h.z_floor - h.z_grade
    nat = h.e2018_med + h.nsi_found_ht
    est = {"national (before)": nat}
    code = (h.sfha > 0) & h.bfe.notna() & ((h.post_firm > 0) | h.permit_flag)
    est["rule: post-FIRM or permit in SFHA -> floor >= BFE + 1"] = np.where(code, np.maximum(nat, h.bfe + 1), nat)
    for name, (cols, mdl) in port.items():
        xp = portable(h, yr, h.post_firm, yr - firm, h.sfha, h.ve, h.bfe - pd.to_numeric(h.nsi_ground, errors="coerce"))
        est[name] = h.e2018_med + mdl.predict(xp[cols])
    best = est["FL-trained model + post-FIRM"]
    est["FL model + post-FIRM, then the code rule"] = np.where(code, np.maximum(best, h.bfe + 1), best)
    raised = true_h > 6
    print(f"houses the code rule applies to: {int(code.sum())}")
    grp = np.where(h.sfha > 0, np.where(h.post_firm > 0, "SFHA, post-FIRM", "SFHA, pre-FIRM or unknown year"),
                   np.where(h.post_firm > 0, "outside SFHA, post-FIRM", "outside SFHA, pre-FIRM or unknown year"))
    print("where the raised houses are:")
    print(pd.DataFrame({"houses": pd.Series(grp).value_counts(), "raised": pd.Series(grp)[raised.values].value_counts()})
          .assign(raised_share=lambda d: (d.raised / d.houses).round(2)).to_markdown())
    show("NYC first floor elevation error (ft), all houses", {k: m(v - h.z_floor) for k, v in est.items()})
    show("NYC raised houses (floor > 6 ft above BES grade)", {k: m(v - h.z_floor, raised) for k, v in est.items()})
    show("NYC not raised", {k: m(v - h.z_floor, ~raised) for k, v in est.items()})
    show("NYC houses the code rule applies to", {k: m(v - h.z_floor, code) for k, v in est.items()})


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main()
