"""Can FEMA flood-insurance statistics stand in for the ~50 measured local houses? (aggregates only)

NFIP prior: OpenFEMA NfipPolicies v3, Harris County, single-family policies effective since 2024 with the
elevation-certificate lowest floor (LFE) and lowest adjacent grade (LAG) (research/coverage/fetch_nfip.py;
data/nfip/harris.parquet). Per 2020 census block group: records, median / p25 / p75 of LFE - LAG, share elevated
(foundation 4-6), crawlspace, basement; the tract's values when the block group has < 10 records
(research/coverage/nfip_test.py, same cleaning). No record is ever matched to a house (OpenFEMA terms; NFIP.md):
houses only receive the statistics of the area they lie in. A test house's own certificate may be one of the
records behind its block group's numbers (renewals repeat it); rows restricted to block groups with >= 30 records
are reported as a check.
Tests, areas A, B, C (screened answer key, scorer only), benchmark method E features:
  0) coverage, and do the NFIP block-group numbers describe the neighbourhood? (block-group share elevated and median
     LFE - LAG vs the answer key's share of doors > 3 ft and median door height in the same block group: aggregate vs
     aggregate, block groups with >= 10 records and >= 10 scored houses)
  1) new area (model from the other two areas): E vs E + NFIP features; and each + 50 measured local houses
     (30 unflagged + 20 flagged, weight 10, mean of 20 draws, as eval_local.py)
  2) within the area (5-fold by 1 km block): E vs E + NFIP features
Usage: python eval_nfip.py
"""
import sys
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "coverage"))
from nfip_test import NF, stats  # noqa: E402

import eval_lpc as el  # noqa: E402
from bands import flag_raised  # noqa: E402
from benchmark import SETS  # noqa: E402
from eval_transfer import load  # noqa: E402

D = HERE.parents[1] / "data"
COLS = SETS["E + eave estimate"]
P1 = {**el.P, "n_jobs": 1}
DRAWS = 20


def load_nfip():
    """As nfip_test.load_nfip, Harris file only."""
    d = pd.read_parquet(D / "nfip" / "harris.parquet").drop_duplicates("id")
    d = d[d.buildingDescriptionCode.isna() | d.buildingDescriptionCode.isin([1, 20])]
    d["ffh"] = d.lowestFloorElevation - d.lowestAdjacentGrade
    d = d[d.ffh.between(-15, 30) & d.lowestFloorElevation.between(-20, 1500) & d.lowestAdjacentGrade.between(-20, 1500)]
    ft = d.foundationType.astype(str).str.strip()
    d["elev"], d["crawl"], d["bsmt"] = ft.isin(["4", "5", "6"]), ft.eq("3"), ft.eq("2")
    d["tract"] = d.censusGeoid.str[:11]
    return d


def attach(df, nf):
    """2020 block group of each house (TIGER TX), then the NFIP area statistics (tract when < 10 records)."""
    con = duckdb.connect()
    con.execute("LOAD spatial")
    pts = pd.DataFrame({"i": np.arange(len(df)), "lon": df.lon.values.astype(float), "lat": df.lat.values.astype(float)})
    con.register("pts", pts)
    j = con.execute(f"""select pts.i, b.GEOID from pts join ST_Read('/vsizip/{D}/tiger/tl_2020_48_bg.zip/tl_2020_48_bg.shp') b
                        on ST_Intersects(b.geom, ST_Point(pts.lon, pts.lat))""").df()
    geoid = pd.Series(pd.NA, index=range(len(df)), dtype="string")
    geoid.loc[j.i.values] = j.GEOID.values
    bg, tr = stats(nf, "censusGeoid"), stats(nf, "tract")
    a = bg.reindex(geoid.values).reset_index(drop=True)
    b = tr.reindex(geoid.str[:11].values).reset_index(drop=True)
    use_bg = a.nf_n.fillna(0) >= 10
    out = pd.DataFrame({c: np.where(use_bg, a[c], b[c]) for c in a.columns})
    out["nf_level"] = np.where(use_bg, "block group", np.where(b.nf_n.notna(), "tract", "none"))
    out["bg"] = geoid.values
    out.index = df.index
    return pd.concat([df, out], axis=1)


def score(f, p, m):
    y, e = f.dh.values[m], p[m] - f.dh.values[m]
    r = y > 3
    s = (f.zone.values[m] == "SFHA") & f.bfe.notna().values[m]
    side = ((f.ffe.values[m][s] >= f.bfe.values[m][s]) == (f.e2018_lag.values[m][s] + p[m][s] >= f.bfe.values[m][s])).mean()
    return {"n": int(m.sum()), "MAE": np.abs(e).mean(), "raised MAE": np.abs(e[r]).mean(),
            "raised recall": (p[m][r] > 3).mean(), "BFE side": side}


def main():
    nf = load_nfip()
    print(f"NFIP Harris records used {len(nf)}; block groups {nf.censusGeoid.nunique()}; LFE - LAG q10/50/90 "
          f"{np.percentile(nf.ffh, [10, 50, 90]).round(2).tolist()} ft; share elevated (foundation 4-6) {nf.elev.mean():.3f}")
    a = {k: attach(load(k), nf) for k in ("A", "B", "C")}
    print("\n## 0) coverage and agreement with the neighbourhood (answer key aggregated per block group)\n")
    rows = {}
    for k, f in a.items():
        s = f[f.key_ok]
        g = s[s.nf_level == "block group"].groupby("bg").agg(n=("dh", "size"), key_raised=("dh", lambda d: (d > 3).mean()),
                                                              key_med=("dh", "median"), nf_elev=("nf_elev", "first"),
                                                              nf_med=("nf_med", "first"), nf_n=("nf_n", "first"))
        g = g[g.n >= 10]
        rows[k] = {"houses": len(s), **{f"prior: {lv}": int((s.nf_level == lv).sum()) for lv in ("block group", "tract", "none")},
                   "block groups compared": len(g),
                   "corr share raised (key) vs share elevated (NFIP)": g[["key_raised", "nf_elev"]].corr().iloc[0, 1],
                   "corr median door (key) vs median LFE-LAG (NFIP)": g[["key_med", "nf_med"]].corr().iloc[0, 1],
                   "median key share raised": g.key_raised.median(), "median NFIP share elevated": g.nf_elev.median(),
                   "median key door ft": g.key_med.median(), "median NFIP LFE-LAG ft": g.nf_med.median()}
    print(pd.DataFrame(rows).T.round(3).to_markdown())

    rng = np.random.default_rng(20261006)
    for te, f in a.items():
        tr = pd.concat([a[o] for o in a if o != te], ignore_index=True)
        ok = f.key_ok.values
        big = ok & (f.nf_n.values >= 30) & (f.nf_level.values == "block group")
        res = {}
        p0 = {}
        for nm, cols in (("E", COLS), ("E + NFIP", COLS + NF)):
            p0[nm] = lgb.LGBMRegressor(**P1).fit(tr[cols], tr.dh).predict(f[cols])
            res[(nm, "other areas only")] = score(f, p0[nm], ok)
            res[(nm, "other areas only; block groups >= 30 records")] = score(f, p0[nm], big)
        g = flag_raised(f, p0["E"])
        acc = {}
        for _ in range(DRAWS):
            nfl = min(20, int(g.sum()) // 2)
            cal = np.r_[rng.choice(np.where(g)[0], nfl, replace=False), rng.choice(np.where(~g)[0], 30, replace=False)]
            ev = ok.copy()
            ev[cal] = False
            loc = f.iloc[cal]
            for nm, cols in (("E", COLS), ("E + NFIP", COLS + NF)):
                x = pd.concat([tr[cols], loc[cols]], ignore_index=True)
                sw = np.r_[np.ones(len(tr)), np.full(len(loc), 10.0)]
                p = lgb.LGBMRegressor(**P1).fit(x, np.r_[tr.dh.values, loc.dh.values], sample_weight=sw).predict(f[cols])
                acc.setdefault(nm, []).append(score(f, p, ev))
        for nm, v in acc.items():
            res[(nm, "+ 50 local houses (W 10)")] = pd.DataFrame(v).mean().to_dict()
        f["block"] = (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)
        for nm, cols in (("E", COLS), ("E + NFIP", COLS + NF)):
            p = np.full(len(f), np.nan)
            for tri, tei in GroupKFold(5).split(f, groups=f.block):
                p[tei] = lgb.LGBMRegressor(**P1).fit(f.loc[tri, cols], f.dh.iloc[tri]).predict(f.loc[tei, cols])
            res[(nm, "within area, 5-fold by 1 km block")] = score(f, p, ok)
        print(f"\n## {te}: model from {'+'.join(o for o in a if o != te)} (screened key)\n")
        print(pd.DataFrame(res).T.round(3).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
