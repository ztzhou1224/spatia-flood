"""Florida benchmark of the core floor method against Elevation Certificates.

Answer key (scorer only): FDEM Elevation Certificates, cleaned in the earlier backtest
(research/ec_backtest: finished construction, residential, NAVD88, zones A/AE/AH, diagrams 1A/1B/5-8,
plausible values, one per property; ec_joined.parquet, 59,590 rows, with FL DOR parcel year built).
Target: top of bottom floor (FEMA lowest floor), ft NAVD88; also the call "lowest floor above BFE?".
Inputs used by the estimates (national / public): USACE NSI 2022 Florida (nearest RES building point
within 30 m of the certificate's geocode; foundation type and height, year, stories, NSI ground from the
3DEP 1/3" DEM), the certificate's BFE (= the FEMA map BFE, public), the flood zone, parcel year built.
Estimates (FFE):
  national           NSI ground + NSI foundation height
  + flood-code rule  in an SFHA zone and built >= 1985: max(national, BFE)
  county-out model   GBM trained on certificates in OTHER counties (national features only), applied here
  neighbours         10% of certificates in the county known: NSI ground + median (floor - NSI ground) of the
                     5 nearest pool certificates within 300 m (reference; needs local certificates)
Usage: python fl_test.py
"""
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from pyproj import Transformer
from sklearn.model_selection import GroupKFold
from sklearn.neighbors import KDTree

ROOT = Path(__file__).resolve().parents[2]
EC = ROOT / "data" / "fl" / "ec_joined.parquet"  # written by ec_backtest/join2.py, run in data/fl
NSI = ROOT / "data" / "fl" / "nsi_fl.parquet"
FT = {"S": 0, "C": 1, "B": 2, "P": 3, "I": 4, "W": 5}


def metrics(err, above_true=None, above_hat=None):
    e = pd.Series(err).dropna()
    out = dict(n=len(e), MAE=e.abs().mean(), within_1=(e.abs() <= 1).mean(), within_2=(e.abs() <= 2).mean(),
               p90=e.abs().quantile(0.9), bias=e.mean())
    if above_true is not None:
        m = above_hat.notna() & above_true.notna()
        out["above/below BFE right"] = (above_true[m] == above_hat[m]).mean()
    return out


def main():
    ec = pd.read_parquet(EC)
    to = Transformer.from_crs("EPSG:4326", "EPSG:3086", always_xy=True)
    ec["X"], ec["Y"] = to.transform(ec.lon.values, ec.lat.values)
    nsi = pd.read_parquet(NSI)
    nsi = nsi[nsi.occtype.str.startswith("RES")].reset_index(drop=True)
    nsi["X"], nsi["Y"] = to.transform(nsi.x.values, nsi.y.values)
    dist, idx = KDTree(nsi[["X", "Y"]].values).query(ec[["X", "Y"]].values, k=1)
    ec["nsi_dist"] = dist[:, 0]
    for c in ("found_type", "found_ht", "num_story", "med_yr_blt", "ground_elv", "occtype"):
        ec["nsi_" + c] = nsi[c].values[idx[:, 0]]
    ec = ec[ec.nsi_dist <= 30].copy()
    # county where the parcel join found one, else a 0.5-degree grid cell (spatial group for CV)
    ec["county_fips"] = ec.county_fips.astype("string").fillna(
        "g" + (ec.lat // 0.5).astype(int).astype(str) + "_" + (ec.lon // 0.5).astype(int).astype(str))
    ec["floor"] = ec.topOfBottomFloor.astype(float)
    ec["lag"] = ec.lowestAdjacentGrade.astype(float)
    ec["bfe"] = pd.to_numeric(ec.baseFloodElevation, errors="coerce")
    ec["year"] = pd.to_numeric(ec.act_yr_blt, errors="coerce").fillna(pd.to_numeric(ec.nsi_med_yr_blt, errors="coerce"))
    ec["diag"] = ec.buildingDiagramNumber.astype(str).str.upper().str.strip()
    ec["dgroup"] = ec.diag.map(lambda d: "1A slab" if d.startswith("1A") else "1B raised slab" if d.startswith("1B")
                               else "8 crawlspace" if d.startswith("8") else "5-7 elevated" if d[:1] in "567" else "other")
    ec["sfha"] = ec.floodZone.astype(str).str.upper().str.match(r"^(A|V)")
    ec["above_true"] = np.where(ec.bfe.notna(), ec.floor >= ec.bfe, np.nan)
    print(f"certificates with an NSI residential point within 30 m: {len(ec)} "
          f"(median distance {ec.nsi_dist.median():.1f} m); counties {ec.county_fips.nunique()}")
    print(f"ground check: NSI ground (1/3\" DEM) minus certificate LAG, median {np.median(ec.nsi_ground_elv - ec.lag):.2f} ft, "
          f"MAE {np.mean(np.abs(ec.nsi_ground_elv - ec.lag)):.2f} ft")
    print(f"true floor above LAG: q10/50/90 {np.percentile(ec.floor - ec.lag, [10, 50, 90]).round(2)}; "
          f"diagram mix {ec.dgroup.value_counts().to_dict()}; NSI types {ec.nsi_found_type.value_counts().to_dict()}")
    est = pd.DataFrame(index=ec.index)
    est["national (NSI ground + NSI height)"] = ec.nsi_ground_elv + ec.nsi_found_ht
    est["national + flood-code rule"] = np.where(ec.sfha & (ec.year >= 1985) & ec.bfe.notna(),
                                                 np.maximum(est.iloc[:, 0], ec.bfe), est.iloc[:, 0])
    feats = pd.DataFrame({"ft": ec.nsi_found_type.map(FT), "fh": ec.nsi_found_ht, "stories": pd.to_numeric(ec.nsi_num_story, errors="coerce"),
                          "year": ec.year, "bfe_minus_ground": ec.bfe - ec.nsi_ground_elv, "sfha": ec.sfha.astype(float),
                          "ve": ec.floodZone.astype(str).str.upper().str.startswith("V").astype(float),
                          "liv_area": pd.to_numeric(ec.tot_lvg_ar, errors="coerce")}, index=ec.index)
    y = ec.floor - ec.nsi_ground_elv
    p = pd.Series(np.nan, index=ec.index)
    P = dict(objective="l1", n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=50, subsample=0.8,
             subsample_freq=1, colsample_bytree=0.8, verbose=-1)
    for tr, te in GroupKFold(5).split(feats, groups=ec.county_fips):
        m = lgb.LGBMRegressor(**P).fit(feats.iloc[tr], y.iloc[tr])
        p.iloc[te] = m.predict(feats.iloc[te])
    est["county-out model (certificates elsewhere)"] = ec.nsi_ground_elv + p
    rng = np.random.default_rng(0)
    pool = rng.random(len(ec)) < 0.10
    nbv = pd.Series(np.nan, index=ec.index)
    for cty, g in ec.groupby("county_fips"):
        gp = g[pool[ec.index.get_indexer(g.index)]]
        if len(gp) < 5:
            continue
        d, ix = KDTree(gp[["X", "Y"]].values).query(g[["X", "Y"]].values, k=min(6, len(gp)))
        off = (gp.floor - gp.nsi_ground_elv).values
        vals = []
        for gi, (dd, ii) in enumerate(zip(d, ix)):
            keep = [(o, k) for o, k in zip(dd, ii) if o > 0.5][:5]
            v = [off[k] for o, k in keep if o <= 300]
            vals.append(np.median(v) if v else np.nan)
        nbv.loc[g.index] = g.nsi_ground_elv.values + np.array(vals)
    est["neighbours (10% certificates)"] = nbv
    test = ~pd.Series(pool, index=ec.index)
    def table(mask):
        return pd.DataFrame({k: metrics((v - ec.floor)[mask], ec.above_true[mask],
                                        pd.Series(np.where(ec.bfe.notna() & v.notna(), v >= ec.bfe, np.nan), index=ec.index)[mask])
                             for k, v in est.items()}).T.round(3)
    print("\n## Lowest-floor elevation error (ft), certificates not in the 10% pool\n")
    print(table(test).to_markdown())
    for gname in ("1A slab", "1B raised slab", "5-7 elevated", "8 crawlspace"):
        mm = test & (ec.dgroup == gname)
        print(f"\n### {gname}: n {int(mm.sum())}")
        print(table(mm)[["n", "MAE", "within_1", "bias", "above/below BFE right"]].to_markdown())
    era = pd.cut(ec.year, [0, 1975, 1995, 2010, 2100], labels=["<1975", "1975-94", "1995-2009", "2010+"])
    print("\n### MAE by year built (national + rule / county-out model / neighbours)")
    print(pd.DataFrame({k: (est[k] - ec.floor).abs()[test].groupby(era[test], observed=True).mean()
                        for k in ("national + flood-code rule", "county-out model (certificates elsewhere)", "neighbours (10% certificates)")}).round(2).to_markdown())
    print("\nNSI foundation type vs certificate floor above LAG (median ft):")
    print(ec.assign(ffh=ec.floor - ec.lag).groupby("nsi_found_type").agg(n=("ffh", "size"), measured=("ffh", "median"),
          nsi_default=("nsi_found_ht", "median"), elevated_share=("dgroup", lambda s: s.isin(["5-7 elevated", "8 crawlspace", "1B raised slab"]).mean())).round(2).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main()
