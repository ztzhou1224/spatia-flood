"""r1b candidate: train.py's method UNCHANGED, on a different label file, artefacts to a different directory.

Owner decision 2026-10-07 ("keep r0, add labels first"): r1b = r0's method on FDEM + Pinellas County certificate labels
(pipeline/labels_pinellas/build.py, labels_combined_<FIPS>.parquet). train.main hard-codes data/flood_v1/train for its
labels and artefacts (r0's release directory, never written here), so its body is repeated below with only those two
paths as parameters; every function it calls (features, fit, abs_q, score) and every constant (P, FEATS, C) is
imported from train.py. Split: 1 km blocks of the LABELS GIVEN, seed 0 (new label blocks change the shuffle, so the
split is not r0's). Reproduction check: run with --labels data/flood_v1/train/labels_<FIPS>.parquet to a scratch
directory and the artefacts equal r0's.
Outputs (r0's file layout): <out>/model_<FIPS>.txt, difficulty_<FIPS>.txt, bands_<FIPS>.json, train_<FIPS>.txt
(the report train.py writes to pipeline/train/out/), plus split_<FIPS>.parquet (building_id, part) for the r1b report.
Usage: python pipeline/train/train_r1b.py 12103 pinellas_2018 --labels FILE --out DIR
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train import FEATS, C, P, abs_q, features, fit, score


def main(fips: str, run: str, labels: Path, outd: Path) -> None:
    outd.mkdir(parents=True, exist_ok=True)
    f = features(fips, run)
    lab = pd.read_parquet(labels)
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

    rep = [
        f"# {fips} ({run}): floor model, held-out 20% by 1 km block",
        "",
        f"labels: {labels}",
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
    (outd / f"train_{fips}.txt").write_text("\n".join(rep) + "\n")
    print("\n".join(rep))
    model.booster_.save_model(str(outd / f"model_{fips}.txt"))
    diff.booster_.save_model(str(outd / f"difficulty_{fips}.txt"))
    (outd / f"bands_{fips}.json").write_text(
        json.dumps(
            {
                "q": q,
                "c": C,
                "features": FEATS,
                "n_fit": len(fit_d),
                "n_cal": len(cal_d),
                "n_test": len(test_d),
                "test_blocks": sorted(test_b),
                "labels": str(labels),
            },
            indent=1,
        )
    )
    pd.DataFrame({"building_id": d.building_id, "part": part}).to_parquet(outd / f"split_{fips}.parquet", index=False)


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("run")
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    main(a.fips, a.run, a.labels, a.out)
