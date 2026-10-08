"""Phase 1: train the floor model for one county, calibrate 90% bands, score the held-out 20% (the release gate).

Fixed before the first run (2026-10-07). Inputs: lidar features (lidar/job.py features.parquet, per building),
labels and records (train/labels.py). No NSI, no floor-count or foundation record (owner, 2026-10-07; research
eval_no_records.py "E-lidar").
Target (label only, never a feature): dh = certificate first living floor (ft NAVD88) - lidar lowest adjacent grade
(g_lag, ft NAVD88). Screened labels (research rule): drop when roof_p95 - dh < 6 ft or dh < -1 ft.
Features: ground shape g_p10 / g_med / g_hag / g_inside / g_far minus g_lag; point cloud (12, eval_lpc.LPC); year built
and living area (DOR NAL); footprint area; lidar stories (1 if eave_main < 14 ft else 2); eave estimates
eave - median eave of all county houses with the same lidar stories (label-free) + 1 ft. LightGBM eval_lpc.P, n_jobs 1.
Splits by 1 km block (EPSG:6442, building centroid), seed 0: TEST 20% of blocks (held out, scored once), CAL 20%,
FIT 60%. Bands: normalised split conformal: difficulty model s(x) (LightGBM on |out-of-fold residual| within FIT,
5 folds by block), q = finite-sample 90% quantile of |y - p| / s on CAL (point model trained on FIT); final point
model trained on FIT + CAL; band = p +- q s(x). Raised flag (label-free): p > 3 ft; coverage reported per flag.
Scores on TEST (screened labels): MAE, within 1 ft, raised (dh > 3) MAE / recall, BFE side (certificate zone A* / V*
with a certificate BFE), band coverage (all / flagged / not), median width, BFE decided and decided correct.
Outputs: pipeline/train/out/train_<FIPS>.txt (this report), data/flood_v1/train/model_<FIPS>.txt (point model),
difficulty_<FIPS>.txt, and bands_<FIPS>.json (q, split sizes).
Usage: python pipeline/train/train.py 12103 pinellas_2018
"""

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "flood_v1"
P = dict(
    objective="l1",
    n_estimators=400,
    learning_rate=0.03,
    num_leaves=15,
    min_child_samples=30,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    verbose=-1,
    n_jobs=1,
)  # research eval_lpc.P
LPC = [
    "bldg_share",
    "roof_p05",
    "roof_p50",
    "roof_p95",
    "eave_p10",
    "eave_p50",
    "eave_main",
    "ridge",
    "ground_in_share",
    "ring_low_share",
    "ring_low_p90",
    "pts_m2",
]
GROUND = ["g_p10", "g_med", "g_hag", "g_inside", "g_far"]
FEATS = (
    GROUND + LPC + ["year_built", "living_area", "fp_area_m2", "stories", "est_eave_p50", "est_eave_main", "est_split"]
)
SLAB_FT = 1.0
C = 0.90


def features(fips: str, run: str) -> pd.DataFrame:
    """One row per building in the run, label-free (all buildings, not only labelled ones)."""
    f = pd.read_parquet(DATA / "lidar" / run / "features.parquet")
    b = pd.read_parquet(DATA / "lidar" / run / "buildings.parquet")
    rec = pd.read_parquet(DATA / "train" / f"records_{fips}.parquet")
    f = f.merge(rec[["building_id", "dor_uc", "act_yr_blt", "tot_lvg_ar"]], on="building_id", how="left")
    for c in ("p10", "med", "hag", "inside", "far"):
        f[f"g_{c}"] = f[f"g_{c}"] - f.g_lag
    f["year_built"] = pd.to_numeric(f.act_yr_blt, errors="coerce").where(lambda s: s > 1800)
    f["living_area"] = pd.to_numeric(f.tot_lvg_ar, errors="coerce").where(lambda s: s > 0)
    st = pd.Series(np.where(f.eave_main.isna(), np.nan, np.where(f.eave_main < 14, 1.0, 2.0)), index=f.index)
    f["stories"] = st
    res = f.dor_uc.fillna("999") < "010"
    for e in ("eave_p50", "eave_main"):
        ref = f[res].groupby(st[res])[e].median()
        f[f"est_{e}"] = f[e] - st.map(ref) + SLAB_FT
    f["est_split"] = np.where(st == 1, f.est_eave_p50, f.est_eave_main)
    tr = Transformer.from_crs("EPSG:4326", "EPSG:6442", always_xy=True)
    cen = shapely.centroid(shapely.from_wkb(b.wkb.values))
    x, y = tr.transform(shapely.get_x(cen), shapely.get_y(cen))
    f["block"] = (np.floor(x / 1000).astype(int)).astype(str) + "_" + (np.floor(y / 1000).astype(int)).astype(str)
    return f


def fit(x, y):
    return lgb.LGBMRegressor(**P).fit(x, y)


def abs_q(s, c):
    s = np.sort(np.asarray(s, float)[np.isfinite(s)])
    k = int(np.ceil((len(s) + 1) * c))
    return s[k - 1] if k <= len(s) else np.inf


def score(d, p, lo, hi) -> dict:
    y, e = d.dh.values, p - d.dh.values
    r, flag = y > 3, p > 3
    cov = (y >= lo) & (y <= hi)
    s = d.cert_zone.astype(str).str.upper().str[:1].isin(["A", "V"]).values & d.cert_bfe_ft.notna().values
    lag, bfe, ffe = d.g_lag.values[s], d.cert_bfe_ft.values[s], d.ffe_ft.values[s]
    above, below = lag + lo[s] >= bfe, lag + hi[s] < bfe
    dec = above | below
    return {
        "n": len(d),
        "MAE": np.abs(e).mean(),
        "within 1 ft": (np.abs(e) <= 1).mean(),
        "raised n": int(r.sum()),
        "raised MAE": np.abs(e[r]).mean(),
        "raised recall": (p[r] > 3).mean(),
        "SFHA with BFE": int(s.sum()),
        "BFE side": ((ffe >= bfe) == (lag + p[s] >= bfe)).mean(),
        "coverage": cov.mean(),
        "coverage flagged": cov[flag].mean(),
        "coverage not flagged": cov[~flag].mean(),
        "width median not flagged": np.median((hi - lo)[~flag]),
        "width median flagged": np.median((hi - lo)[flag]),
        "BFE decided": dec.mean(),
        "decided correct": ((above & (ffe >= bfe)) | (below & (ffe < bfe)))[dec].mean(),
    }


def main(fips: str, run: str) -> None:
    f = features(fips, run)
    lab = pd.read_parquet(DATA / "train" / f"labels_{fips}.parquet")
    d = lab.merge(f, on="building_id", how="inner")
    d = d[d.g_lag.notna() & (d.lpc_status == "ok")].copy()
    d["dh"] = d.ffe_ft - d.g_lag
    n0 = len(d)
    d = d[~((d.roof_p95 - d.dh < 6) | (d.dh < -1))].reset_index(drop=True)
    blocks = np.array(sorted(d.block.unique()))
    rng = np.random.default_rng(0)
    rng.shuffle(blocks)
    k = len(blocks)
    test_b, cal_b = set(blocks[: round(0.2 * k)]), set(blocks[round(0.2 * k) : round(0.4 * k)])
    part = np.where(d.block.isin(test_b), "test", np.where(d.block.isin(cal_b), "cal", "fit"))
    fit_d, cal_d, test_d = (
        d[part == "fit"].reset_index(drop=True),
        d[part == "cal"].reset_index(drop=True),
        d[part == "test"].reset_index(drop=True),
    )

    oof = np.full(len(fit_d), np.nan)
    for a, b in GroupKFold(5).split(fit_d, groups=fit_d.block):
        oof[b] = fit(fit_d.loc[a, FEATS], fit_d.dh.iloc[a]).predict(fit_d.loc[b, FEATS])
    sx = fit_d[FEATS].assign(p=oof)
    diff = lgb.LGBMRegressor(**{**P, "objective": "l2"}).fit(sx, np.abs(fit_d.dh.values - oof))

    def s_of(x, p):
        return np.maximum(diff.predict(x[FEATS].assign(p=p)), 0.05)

    m_fit = fit(fit_d[FEATS], fit_d.dh)
    pc = m_fit.predict(cal_d[FEATS])
    q = abs_q(np.abs(cal_d.dh.values - pc) / s_of(cal_d, pc), C)
    model = fit(pd.concat([fit_d, cal_d])[FEATS], pd.concat([fit_d, cal_d]).dh)
    pt = model.predict(test_d[FEATS])
    st = s_of(test_d, pt)
    lo, hi = pt - q * st, pt + q * st
    rows = {"all held-out (screened)": score(test_d, pt, lo, hi)}
    dg = test_d.diagram.astype(str)
    for name, m in (
        ("slab 1A/1B", dg.isin(["1A", "1B"]).values),
        ("elevated / enclosed 5-9", dg.str[0].isin(list("56789")).values),
    ):
        rows[name] = score(test_d[m].reset_index(drop=True), pt[m], lo[m], hi[m])
    pf = m_fit.predict(test_d[FEATS])
    rows["FIT-only model (same test)"] = score(test_d, pf, pf - q * s_of(test_d, pf), pf + q * s_of(test_d, pf))

    out = Path(__file__).parent / "out"
    out.mkdir(exist_ok=True)
    rep = [
        f"# {fips} ({run}): floor model, held-out 20% by 1 km block",
        "",
        f"labels joined to lidar features with ground and points: {n0}; after the label screen: {len(d)}; "
        f"blocks {k}: fit {len(fit_d)} / cal {len(cal_d)} / test {len(test_d)} houses",
        f"90% normalised conformal scale q = {q:.3f} (CAL, n = {len(cal_d)})",
        "",
        pd.DataFrame(rows).T.round(3).to_markdown(),
        "",
        "feature importance (gain, final model, top 12): "
        + ", ".join(
            pd.Series(model.booster_.feature_importance("gain"), index=FEATS)
            .sort_values(ascending=False)
            .head(12)
            .index
        ),
    ]
    (out / f"train_{fips}.txt").write_text("\n".join(rep) + "\n")
    print("\n".join(rep))
    model.booster_.save_model(str(DATA / "train" / f"model_{fips}.txt"))
    diff.booster_.save_model(str(DATA / "train" / f"difficulty_{fips}.txt"))
    (DATA / "train" / f"bands_{fips}.json").write_text(
        json.dumps(
            {
                "q": q,
                "c": C,
                "features": FEATS,
                "n_fit": len(fit_d),
                "n_cal": len(cal_d),
                "n_test": len(test_d),
                "test_blocks": sorted(test_b),
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main(*sys.argv[1:3])
