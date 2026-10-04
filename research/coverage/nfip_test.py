"""Does a block-group floor-height prior from FEMA flood-insurance policies fix the national floor estimate?

Prior (data/nfip/*.parquet, fetch_nfip.py): NFIP redacted policies since 2024, single-family, with the
elevation-certificate lowest floor (LFE) and lowest adjacent grade (LAG). Per census block group (2020):
records, median / p25 / p75 of LFE - LAG, share elevated (foundation 4-6), crawlspace (3), basement (2).
Where a block group has < 10 records the tract values are used (nf_level says which).
No address is published, so the prior is an area value, never this house's own record. The test house's
own certificate may be one of the records behind its block group's median (renewals repeat it); the
'nf_n >= 30' rows show results where one house is at most ~1/30 of the median's inputs.

Tests (answer keys are scorer only):
  Florida   FDEM elevation certificates; floor height model trained on OTHER counties (GroupKFold by
            county), with and without the prior; on the 1 m lidar subset FFE = lidar ring median + height.
  NYC       BES measured first floors (Staten Island east shore); model trained on ALL Florida certificates
            with portable features only (NSI type / height / stories / year), with and without the prior.
  Harris    HCFCD front-door FFE (areas B, C, precision tiers A+B); same Florida model, and a model trained
            in the other Harris area, each with and without the prior.
  rule      no training at all: ground + block-group median (LFE - LAG).
Usage: python nfip_test.py
"""
import sys
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harris_mini"))
sys.path.insert(0, str(HERE))
import evaluate_cov as ecv  # noqa: E402
import fl_lidar  # noqa: E402

ROOT = HERE.parents[1]
D = ROOT / "data"
P = dict(objective="l1", n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=50, subsample=0.8,
         subsample_freq=1, colsample_bytree=0.8, verbose=-1)
NF = ["nf_med", "nf_p25", "nf_p75", "nf_elev", "nf_crawl", "nf_bsmt", "nf_n"]
PORT = ["ft", "fh", "stories", "nsi_year"]


def load_nfip():
    d = pd.concat([pd.read_parquet(D / "nfip" / f"{n}.parquet") for n in ("FL", "harris", "richmond")]).drop_duplicates("id")
    d = d[d.buildingDescriptionCode.isna() | d.buildingDescriptionCode.isin([1, 20])]
    d["ffh"] = d.lowestFloorElevation - d.lowestAdjacentGrade
    d = d[d.ffh.between(-15, 30) & d.lowestFloorElevation.between(-20, 1500) & d.lowestAdjacentGrade.between(-20, 1500)]
    ft = d.foundationType.astype(str).str.strip()
    d["elev"], d["crawl"], d["bsmt"] = ft.isin(["4", "5", "6"]), ft.eq("3"), ft.eq("2")
    d["tract"] = d.censusGeoid.str[:11]
    return d


def stats(d, key):
    g = d.groupby(key)
    return pd.DataFrame({"nf_n": g.size(), "nf_med": g.ffh.median(), "nf_p25": g.ffh.quantile(0.25), "nf_p75": g.ffh.quantile(0.75),
                         "nf_elev": g.elev.mean(), "nf_crawl": g.crawl.mean(), "nf_bsmt": g.bsmt.mean()})


def attach(df, lon, lat, nf):
    """Block group of each point (TIGER 2020), then the NFIP prior (tract fallback when < 10 records)."""
    con = duckdb.connect(); con.execute("LOAD spatial")
    pts = pd.DataFrame({"i": np.arange(len(df)), "lon": np.asarray(lon, float), "lat": np.asarray(lat, float)})
    con.register("pts", pts)
    bgs = " union all ".join(f"select GEOID, geom from ST_Read('/vsizip/{D}/tiger/tl_2020_{s}_bg.zip/tl_2020_{s}_bg.shp')"
                             for s in ("12", "36", "48"))
    j = con.execute(f"""with b as ({bgs}) select pts.i, b.GEOID from pts join b on ST_Intersects(b.geom, ST_Point(pts.lon, pts.lat))""").df()
    geoid = pd.Series(pd.NA, index=range(len(df)), dtype="string")
    geoid.loc[j.i.values] = j.GEOID.values
    bg, tr = stats(nf, "censusGeoid"), stats(nf, "tract")
    a = bg.reindex(geoid.values).reset_index(drop=True)
    b = tr.reindex(geoid.str[:11].values).reset_index(drop=True)
    use_bg = a.nf_n.fillna(0) >= 10
    out = a.where(use_bg.values[:, None], b)
    out["nf_level"] = np.where(use_bg, "block group", np.where(b.nf_n.notna(), "tract", "none"))
    out.index = df.index
    return pd.concat([df, out], axis=1)


def m(err, mask=None):
    e = pd.Series(err)
    e = (e[mask] if mask is not None else e).dropna()
    return dict(n=len(e), MAE=e.abs().mean(), within_1=(e.abs() <= 1).mean(), p90=e.abs().quantile(0.9), bias=e.mean())


def show(title, rows):
    print(f"\n## {title}\n")
    print(pd.DataFrame(rows).T.round(3).to_markdown())


def main():
    nf = load_nfip()
    print(f"NFIP records used: {len(nf)} (FL {int((nf.propertyState == 'FL').sum())}, TX {int((nf.propertyState == 'TX').sum())}, "
          f"NY {int((nf.propertyState == 'NY').sum())}); block groups {nf.censusGeoid.nunique()}; "
          f"LFE - LAG q10/50/90 {np.percentile(nf.ffh, [10, 50, 90]).round(2)}")

    # ---------- Florida ----------
    ec = fl_lidar.load()
    ec = attach(ec, ec.lon, ec.lat, nf)
    X = fl_lidar.features(ec).assign(nsi_year=pd.to_numeric(ec.nsi_med_yr_blt, errors="coerce"))
    XN = pd.concat([X, ec[NF]], axis=1)
    y = ec.floor - ec.lag
    print(f"\nFlorida certificates {len(ec)}; prior level {ec.nf_level.value_counts().to_dict()}")
    pred = {}
    for name, F in (("model, no prior", X), ("model + NFIP prior", XN)):
        p = pd.Series(np.nan, index=ec.index)
        for tr, te in GroupKFold(5).split(F, groups=ec.county_fips):
            p.iloc[te] = lgb.LGBMRegressor(**P).fit(F.iloc[tr], y.iloc[tr]).predict(F.iloc[te])
        pred[name] = p
    pred["rule: NFIP block-group median only"] = ec.nf_med
    pred["NSI default height (reference)"] = ec.nsi_found_ht
    big = ec.nf_n >= 30
    show("Florida, floor height above the certificate's ground (ft), county-out", {k: m(v - y) for k, v in pred.items()})
    show("Florida, same, only houses whose block group has >= 30 NFIP records", {k: m(v - y, big) for k, v in pred.items()})
    for gname in ("1A slab", "1B raised slab", "5-7 elevated", "8 crawlspace"):
        mm = ec.dgroup == gname
        show(f"Florida floor height by type: {gname}", {k: m(v - y, mm) for k, v in pred.items() if "reference" not in k})
    cache = D / "fl" / "lidar_ground.parquet"
    g = pd.read_parquet(cache) if cache.exists() else fl_lidar.lidar_ground(ec).pipe(lambda x: (x.to_parquet(cache), x)[1])
    t = ec.loc[g.index].join(g)
    ok = t.bfe.notna()
    rows = {}
    for k, v in pred.items():
        est = t.l_med + v.loc[t.index]
        r = m(est - t.floor)
        r["above_below_BFE_right"] = ((est[ok] >= t.bfe[ok]) == (t.floor[ok] >= t.bfe[ok])).mean()
        rows[k] = r
    show(f"Florida 1 m lidar subset: lowest floor elevation error (ft), ground = lidar ring median", rows)

    # one portable model trained on ALL Florida certificates
    XP = pd.DataFrame({"ft": X.ft, "fh": X.fh, "stories": X.stories, "nsi_year": X.nsi_year}, index=ec.index)
    port = {"FL model, no prior": lgb.LGBMRegressor(**P).fit(XP, y),
            "FL model + NFIP prior": lgb.LGBMRegressor(**P).fit(pd.concat([XP, ec[NF]], axis=1), y)}

    def portable(df):
        xp = pd.DataFrame({"ft": df.nsi_ft, "fh": pd.to_numeric(df.nsi_found_ht, errors="coerce"),
                           "stories": pd.to_numeric(df.nsi_stories, errors="coerce"),
                           "nsi_year": pd.to_numeric(df.nsi_year, errors="coerce")}, index=df.index)
        return {"FL model, no prior": port["FL model, no prior"].predict(xp),
                "FL model + NFIP prior": port["FL model + NFIP prior"].predict(pd.concat([xp, df[NF]], axis=1))}

    # ---------- NYC ----------
    h = pd.read_parquet(D / "nyc" / "nyc_scored.parquet")
    h = attach(h, h.longitude, h.latitude, nf)
    print(f"\nNYC houses {len(h)}; prior level {h.nf_level.value_counts().to_dict()}")
    est = {"national: NSI height + lidar median grade (before)": h.e2018_med + h.nsi_found_ht,
           "rule: lidar median grade + NFIP block-group median": h.e2018_med + h.nf_med,
           "rule: lidar lowest grade + NFIP block-group median": h.e2018_lag + h.nf_med}
    for k, v in portable(h).items():
        est[k] = h.e2018_med + v
    raised = h.ffh > 6
    show("NYC (Staten Island east shore), first floor elevation error (ft)", {k: m(v - h.ffe) for k, v in est.items()})
    show("NYC, raised houses (floor > 6 ft above ground)", {k: m(v - h.ffe, raised) for k, v in est.items()})
    show("NYC, block groups with >= 30 NFIP records", {k: m(v - h.ffe, h.nf_n >= 30) for k, v in est.items()})

    # ---------- Harris ----------
    H = {a: ecv.load(a) for a in ("B", "C")}
    for a in H:
        H[a] = H[a][H[a].tier != "C"]
        H[a] = attach(H[a], H[a].lon, H[a].lat, nf)
    for a, o in (("B", "C"), ("C", "B")):
        t, s = H[a], H[o]
        print(f"\nHarris {a}: houses {len(t)}; prior level {t.nf_level.value_counts().to_dict()}")
        est = {"national: NSI height + lidar median grade (before)": t.e2018_med + t.nsi_found_ht,
               "rule: lidar median grade + NFIP block-group median": t.e2018_med + t.nf_med,
               "rule: lidar lowest grade + NFIP block-group median": t.e2018_lag + t.nf_med}
        for k, v in portable(t).items():
            est[k] = t.e2018_med + v
        est[f"model trained in area {o}, no prior"] = t.e2018_lag + lgb.LGBMRegressor(**P).fit(s[ecv.NAT], s.ffh).predict(t[ecv.NAT])
        est[f"model trained in area {o} + NFIP prior"] = t.e2018_lag + lgb.LGBMRegressor(**P).fit(s[ecv.NAT + NF], s.ffh).predict(t[ecv.NAT + NF])
        show(f"Harris area {a}, front-door floor elevation error (ft)", {k: m(v - t.ffe) for k, v in est.items()})


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main()
