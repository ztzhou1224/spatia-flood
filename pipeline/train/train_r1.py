"""r1 candidate bands for elevated houses the model does not flag (owner approved the work, 2026-10-07).

r0 (train.py, release pinellas-r0) covers elevated / enclosed houses (certificate diagram 5-9) that it does not flag
(p <= 3 ft) at 0.79 on TEST. This script keeps r0's point model, label screen and FIT / CAL / TEST block split
(seed 0) unchanged and compares band options that use no label at prediction time:
  r0          single q, r0 difficulty model s(x) (LightGBM l2 on |OOF residual|, FEATS + p).
  A1 s-q90    difficulty model with the quantile objective (alpha 0.9); single q; same artefact format as r0.
  A2 s+raised difficulty model with one extra input: the raised classifier's score (below); single q.
  B1 flag     Mondrian q by the r0 flag (p > 3 / p <= 3).
  B2 era      Mondrian q by flag x (year built <= 1950, label-free record; missing year -> later group).
  C1 raised   Mondrian q by flag x raised score >= t: classifier "elevated" (target diagram 5-9 or dh > 3, a
              label used ONLY as the training target, on FIT; inputs FEATS + p), t = score at which the FIT
              out-of-fold group holds 75% of FIT's unflagged elevated houses (fixed before scoring).
  C2 raised-asym  C1 with an asymmetric band in the unflagged high-score group: lower / upper q = 95% finite-sample
              quantiles of -z / z (z = (y - p) / s), so p - q_lo s, p + q_hi s.
  Added after C1 / C2 were scored on TEST (disclosed in out/r1_elevated_<FIPS>.md):
  C3 raised-bins  Mondrian q by flag x 4 score bins (cut at the 50 / 80 / 95% quantiles of FIT OOF unflagged scores).
  C4 raised90 C1 with t90: the score at which the FIT OOF group holds 90% of FIT's unflagged elevated houses.
  D1 / D2 / D3  C1 / C4 / C3, but in the high-score group(s) q = max(group q, 90% quantile of |z| over the group's
              CAL houses with diagram 5-9). The label is read at calibration on CAL only; the group (and so the
              band) at prediction is label-free.
Calibration on CAL only (models fit on FIT, as r0). TEST is scored with train.score plus the coverage of the
elevated-unflagged subgroup (diagram 5-9 and p <= 3, the handoff's 0.79), and of raised-unflagged (dh > 3, p <= 3).
CAL-CV columns: the same q rule fitted on 4/5 of CAL blocks and scored on the other 1/5 (5 folds), a selection
signal that does not look at TEST.
Usage:  python pipeline/train/train_r1.py 12103 pinellas_2018 [--county]      # table -> out/r1_elevated_<FIPS>.txt
        python pipeline/train/train_r1.py 12103 pinellas_2018 --save 'D2 raised90-elevq'  # + artefacts -> data/flood_v1/train_r1/
Never writes to data/flood_v1/train/ (release pinellas-r0).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from train import DATA, FEATS, C, P, abs_q, features, fit, score

OUT = DATA / "train_r1"
ERA_YEAR = 1950
SHARE = 0.75  # C1: share of FIT's unflagged elevated houses the high-score group must hold (out of fold)
CP = {**P, "objective": "binary"}
BIN_Q = [0.5, 0.8, 0.95]  # C3 / D3: score cut points = these quantiles of FIT OOF unflagged scores


def load(fips: str, run: str):
    """Exactly train.main's data, screen and split."""
    f = features(fips, run)
    lab = pd.read_parquet(DATA / "train" / f"labels_{fips}.parquet")
    d = lab.merge(f, on="building_id", how="inner")
    d = d[d.g_lag.notna() & (d.lpc_status == "ok")].copy()
    d["dh"] = d.ffe_ft - d.g_lag
    d = d[~((d.roof_p95 - d.dh < 6) | (d.dh < -1))].reset_index(drop=True)
    blocks = np.array(sorted(d.block.unique()))
    rng = np.random.default_rng(0)
    rng.shuffle(blocks)
    k = len(blocks)
    test_b, cal_b = set(blocks[: round(0.2 * k)]), set(blocks[round(0.2 * k): round(0.4 * k)])
    part = np.where(d.block.isin(test_b), "test", np.where(d.block.isin(cal_b), "cal", "fit"))
    return (d[part == "fit"].reset_index(drop=True), d[part == "cal"].reset_index(drop=True),
            d[part == "test"].reset_index(drop=True), test_b)


def elevated(d: pd.DataFrame) -> np.ndarray:
    """Label-derived (scoring / classifier target only): certificate diagram 5-9."""
    return d.diagram.astype(str).str[0].isin(list("56789")).values


def wilson(k: int, n: int, z: float = 1.96) -> str:
    c, h = (k + z * z / 2) / (n + z * z), z * np.sqrt(k * (n - k) / n + z * z / 4) / (n + z * z)
    return f"{c - h:.3f}-{c + h:.3f}"


def q_asym(z, c):
    a = (1 - c) / 2
    return abs_q(-z, 1 - a), abs_q(z, 1 - a)


class Bands:
    """Group-conditional normalised conformal: groups are label-free (computed from x and p)."""

    def __init__(self, groups, asym=(), elevq=()):
        self.groups, self.asym, self.elevq = groups, set(asym), set(elevq)

    def calibrate(self, y, p, s, g, el):
        """el (certificate diagram 5-9) is read only here, on CAL: in an `elevq` group q is the larger of the
        group's 90% quantile and the 90% quantile of its elevated CAL houses. Prediction never reads it."""
        self.q = {}
        for k in self.groups:
            z = (y[g == k] - p[g == k]) / s[g == k]
            self.q[k] = q_asym(z, C) if k in self.asym else (abs_q(np.abs(z), C),) * 2
            if k in self.elevq:
                m = (g == k) & el
                qe = abs_q(np.abs((y[m] - p[m]) / s[m]), C)
                self.q[k] = (max(self.q[k][0], qe), max(self.q[k][1], qe))
        return self

    def band(self, p, s, g):
        lo, hi = np.full(len(p), np.nan), np.full(len(p), np.nan)
        for k, (ql, qh) in self.q.items():
            m = g == k
            lo[m], hi[m] = p[m] - ql * s[m], p[m] + qh * s[m]
        return lo, hi


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("run")
    ap.add_argument("--save", help="option to write to data/flood_v1/train_r1/")
    ap.add_argument("--county", action="store_true", help="also apply each option to the county's residential houses")
    a = ap.parse_args()
    fit_d, cal_d, test_d, test_b = load(a.fips, a.run)

    # r0's models, recomputed exactly as train.main
    folds = list(GroupKFold(5).split(fit_d, groups=fit_d.block))
    oof = np.full(len(fit_d), np.nan)
    for tr, va in folds:
        oof[va] = fit(fit_d.loc[tr, FEATS], fit_d.dh.iloc[tr]).predict(fit_d.loc[va, FEATS])
    r_fit = np.abs(fit_d.dh.values - oof)
    m_fit = fit(fit_d[FEATS], fit_d.dh)
    model = fit(pd.concat([fit_d, cal_d])[FEATS], pd.concat([fit_d, cal_d]).dh)
    pc, pt = m_fit.predict(cal_d[FEATS]), model.predict(test_d[FEATS])
    r0_saved = lgb.Booster(model_file=str(DATA / "train" / f"model_{a.fips}.txt")).predict(test_d[FEATS])
    same_point = float(np.max(np.abs(pt - r0_saved)))

    # raised classifier: FIT only (out of fold on FIT for the score used to train A2 and to set t)
    yr = (elevated(fit_d) | (fit_d.dh.values > 3)).astype(int)
    xr = fit_d[FEATS].assign(p=oof)
    oof_c = np.full(len(fit_d), np.nan)
    for tr, va in folds:
        oof_c[va] = lgb.LGBMClassifier(**CP).fit(xr.iloc[tr], yr[tr]).predict_proba(xr.iloc[va])[:, 1]
    clf = lgb.LGBMClassifier(**CP).fit(xr, yr)
    unfl_el = (oof <= 3) & elevated(fit_d)
    t = float(np.quantile(oof_c[unfl_el], 1 - SHARE))
    t90 = float(np.quantile(oof_c[unfl_el], 1 - 0.9))
    tb = np.quantile(oof_c[oof <= 3], BIN_Q)  # score bins among FIT OOF unflagged (label-free cut points)
    auc = roc_auc_score(elevated(fit_d)[oof <= 3], oof_c[oof <= 3])

    def craised(x, p):
        return clf.predict_proba(x[FEATS].assign(p=p))[:, 1]

    diffs = {
        "r0": lgb.LGBMRegressor(**{**P, "objective": "l2"}).fit(xr, r_fit),
        "q90": lgb.LGBMRegressor(**{**P, "objective": "quantile", "alpha": 0.9}).fit(xr, r_fit),
        "raised": lgb.LGBMRegressor(**{**P, "objective": "l2"}).fit(xr.assign(raised=oof_c), r_fit),
    }

    def s_of(kind, x, p):
        xx = x[FEATS].assign(p=p)
        if kind == "raised":
            xx = xx.assign(raised=craised(x, p))
        return np.maximum(diffs[kind].predict(xx), 0.05)

    def grp(kind, x, p):
        flag = p > 3
        if kind == "one":
            return np.zeros(len(p), int)
        if kind == "flag":
            return flag.astype(int)
        if kind == "era":
            old = (x.year_built.astype(float) <= ERA_YEAR).fillna(False).values.astype(bool)
            return np.where(flag, 2, np.where(old, 1, 0))
        if kind == "raised":
            return np.where(flag, 2, np.where(craised(x, p) >= t, 1, 0))
        if kind == "raised90":
            return np.where(flag, 2, np.where(craised(x, p) >= t90, 1, 0))
        if kind == "bins":
            return np.where(flag, len(tb) + 1, np.searchsorted(tb, craised(x, p), side="right"))
        raise ValueError(kind)

    nb = len(tb) + 2
    opts = {  # name: (difficulty, groups, n groups, asymmetric groups, elevated-q groups, widened unflagged groups)
        "r0": ("r0", "one", 1, (), (), ()),
        "A1 s-q90": ("q90", "one", 1, (), (), ()),
        "A2 s+raised": ("raised", "one", 1, (), (), ()),
        "B1 flag": ("r0", "flag", 2, (), (), ()),
        "B2 era": ("r0", "era", 3, (), (), (1,)),
        "C1 raised": ("r0", "raised", 3, (), (), (1,)),
        "C2 raised-asym": ("r0", "raised", 3, (1,), (), (1,)),
        "C3 raised-bins": ("r0", "bins", nb, (), (), (nb - 3, nb - 2)),
        "C4 raised90": ("r0", "raised90", 3, (), (), (1,)),
        "D1 raised-elevq": ("r0", "raised", 3, (), (1,), (1,)),
        "D2 raised90-elevq": ("r0", "raised90", 3, (), (1,), (1,)),
        "D3 bins-elevq": ("r0", "bins", nb, (), (nb - 3, nb - 2), (nb - 3, nb - 2)),
    }
    yc, yt = cal_d.dh.values, test_d.dh.values
    el_c, el_t = elevated(cal_d), elevated(test_d)
    cal_folds = list(GroupKFold(5).split(cal_d, groups=cal_d.block))
    rows, fitted = {}, {}
    if a.county:  # approximate assemble.py eligibility (lidar ok, lidar LAG, DOR 000-009); final model, no labels
        cx = features(a.fips, a.run)
        cx = cx[(cx.lpc_status == "ok") & cx.g_lag.notna() & (cx.dor_uc.fillna("999") < "010")].reset_index(drop=True)
        pcx = model.predict(cx[FEATS])
    for name, (dk, gk, ng, asym, elevq, hi_g) in opts.items():
        sc, gc = s_of(dk, cal_d, pc), grp(gk, cal_d, pc)
        bands = Bands(range(ng), asym, elevq).calibrate(yc, pc, sc, gc, el_c)
        st, gt = s_of(dk, test_d, pt), grp(gk, test_d, pt)
        lo, hi = bands.band(pt, st, gt)
        row = score(test_d, pt, lo, hi)
        cov, unfl = (yt >= lo) & (yt <= hi), pt <= 3
        row["elev-unfl n"] = int((el_t & unfl).sum())
        row["elev-unfl coverage"] = cov[el_t & unfl].mean()
        row["elev-unfl 95% CI"] = wilson(int(cov[el_t & unfl].sum()), int((el_t & unfl).sum()))
        row["raised-unfl n"] = int(((yt > 3) & unfl).sum())
        row["raised-unfl coverage"] = cov[(yt > 3) & unfl].mean()
        row["TEST unfl hi-score n"] = int(np.isin(gt, hi_g).sum())
        # CAL-CV: q from 4/5 of CAL blocks, coverage on the other 1/5 (TEST not used)
        cc = np.zeros(len(cal_d), bool)
        for tr, va in cal_folds:
            b = Bands(range(ng), asym, elevq).calibrate(yc[tr], pc[tr], sc[tr], gc[tr], el_c[tr])
            lo_v, hi_v = b.band(pc[va], sc[va], gc[va])
            cc[va] = (yc[va] >= lo_v) & (yc[va] <= hi_v)
        row["CAL-CV coverage"] = cc.mean()
        row["CAL-CV elev-unfl coverage"] = cc[el_c & (pc <= 3)].mean()
        row["q"] = "; ".join(f"g{k}: {ql:.3f}" + (f"/{qh:.3f}" if ql != qh else "") for k, (ql, qh) in bands.q.items())
        if a.county:
            lo_x, hi_x = bands.band(pcx, s_of(dk, cx, pcx), grp(gk, cx, pcx))
            row["county n"] = len(cx)
            row["county widened n"] = int(np.isin(grp(gk, cx, pcx), hi_g).sum())
            row["county width median not flagged"] = np.median((hi_x - lo_x)[pcx <= 3])
            row["county width median all"] = np.median(hi_x - lo_x)
        rows[name], fitted[name] = row, (dk, gk, bands)

    tab = pd.DataFrame(rows).T
    num = [c for c in tab.columns if c not in ("q", "elev-unfl 95% CI")]
    tab[num] = tab[num].astype(float).round(3)
    head = (f"split as train.py: fit {len(fit_d)} / cal {len(cal_d)} / test {len(test_d)}; recomputed final model "
            f"vs saved r0 model on TEST, max |diff| = {same_point:.2e} ft")
    clf_line = (f"raised classifier (FIT, target diagram 5-9 or dh > 3; FIT OOF AUC among unflagged, target diagram "
                f"5-9 = {auc:.3f}): t = {t:.4f} holds {SHARE:.0%} of FIT's unflagged elevated (OOF), "
                f"{int(((oof <= 3) & (oof_c >= t)).sum())} of {int((oof <= 3).sum())} FIT unflagged score >= t; "
                f"t90 = {t90:.4f} holds 90%, {int(((oof <= 3) & (oof_c >= t90)).sum())} score >= t90; bins cut at "
                f"{np.round(tb, 4).tolist()} (FIT OOF unflagged score quantiles {BIN_Q})")
    legend = ("Elevated (diagram 5-9) / raised (dh > 3) houses the model does not flag (p <= 3), TEST; CAL-CV; q per "
              "group. Groups: one q = g0; B1 g0 unflagged, g1 flagged; B2 / C1 / C2 / C4 / D1 / D2 g0 unflagged low, "
              "g1 unflagged high (old / high score), g2 flagged; C3 / D3 g0-g3 unflagged score bins, g4 flagged. "
              "Asymmetric q: lower/upper. 'hi-score n' = TEST unflagged houses in the widened groups.")
    rep = [f"# {a.fips} ({a.run}): r1 band options for elevated houses the model does not flag", "", head, clf_line,
           "", "Main scores (TEST):", "",
           tab[["n", "MAE", "BFE side", "coverage", "coverage flagged", "coverage not flagged",
                "width median not flagged", "width median flagged", "BFE decided", "decided correct"]].to_markdown(),
           "", legend, "",
           tab[["elev-unfl n", "elev-unfl coverage", "elev-unfl 95% CI", "raised-unfl n", "raised-unfl coverage",
                "TEST unfl hi-score n", "CAL-CV coverage", "CAL-CV elev-unfl coverage", "q"]].to_markdown()]
    if a.county:
        rep += ["", ("County residential houses (approx. assemble.py eligibility: lidar ok, lidar LAG, DOR 000-009; "
                     "no labels): same final model, each option's bands"), "",
                tab[["county n", "county widened n", "county width median not flagged",
                     "county width median all"]].to_markdown()]
    out = Path(__file__).parent / "out" / f"r1_elevated_{a.fips}.txt"
    out.write_text("\n".join(rep) + "\n")
    print("\n".join(rep))

    if a.save:
        dk, gk, bands = fitted[a.save]
        assert dk == "r0" and gk in ("one", "raised", "raised90"), "save supports r0's difficulty model, one q or C/D groups"
        OUT.mkdir(parents=True, exist_ok=True)
        model.booster_.save_model(str(OUT / f"model_{a.fips}.txt"))
        diffs[dk].booster_.save_model(str(OUT / f"difficulty_{a.fips}.txt"))
        meta = {"q": bands.q[0][0] if gk == "one" else None, "c": C, "features": FEATS,
                "n_fit": len(fit_d), "n_cal": len(cal_d), "n_test": len(test_d), "test_blocks": sorted(test_b),
                "option": a.save}
        if gk != "one":
            clf.booster_.save_model(str(OUT / f"raised_{a.fips}.txt"))
            gc = grp(gk, cal_d, pc)
            meta["groups"] = {
                "doc": GROUPS_DOC, "threshold": t if gk == "raised" else t90, "flag_ft": 3.0,
                "q_lo": {n: bands.q[k][0] for k, n in enumerate(GROUP_NAMES)},
                "q_hi": {n: bands.q[k][1] for k, n in enumerate(GROUP_NAMES)},
                "n_cal": {n: int((gc == k).sum()) for k, n in enumerate(GROUP_NAMES)},
                "n_cal_elevated": {n: int(((gc == k) & el_c).sum()) for k, n in enumerate(GROUP_NAMES)},
                "elevated_q_groups": [GROUP_NAMES[k] for k in sorted(bands.elevq)],
                "classifier": {"file": f"raised_{a.fips}.txt", "inputs": FEATS + ["p"], "trained_on": "FIT",
                               "target": "certificate diagram 5-9 or dh > 3 ft (training target only)"}}
        (OUT / f"bands_{a.fips}.json").write_text(json.dumps(meta, indent=1))
        # re-read the saved artefacts from disk and re-score TEST, then the gate's checks against r0 (same houses)
        from gate import COVERAGE_FLOOR, TOL
        rows = {}
        for nm, dd in (("candidate (from disk)", OUT), ("baseline r0 (from disk)", DATA / "train")):
            pp, lo, hi, _ = disk_bands(dd, a.fips, test_d)
            rows[nm] = score(test_d, pp, lo, hi)
            cov = (yt >= lo) & (yt <= hi)
            rows[nm]["elev-unfl coverage"] = cov[el_t & (pp <= 3)].mean()
        c, b = rows["candidate (from disk)"], rows["baseline r0 (from disk)"]
        checks = {"coverage >= floor": c["coverage"] >= COVERAGE_FLOOR,
                  "MAE": c["MAE"] <= b["MAE"] + TOL["MAE"],
                  "BFE side": c["BFE side"] >= b["BFE side"] - TOL["BFE side"],
                  "coverage": c["coverage"] >= b["coverage"] - TOL["coverage"],
                  "decided correct": c["decided correct"] >= b["decided correct"] - TOL["decided correct"]}
        print("saved", a.save, "->", OUT)
        print(pd.DataFrame(rows).T[["n", "MAE", "BFE side", "coverage", "decided correct", "BFE decided",
                                    "width median not flagged", "elev-unfl coverage"]].round(3).to_markdown())
        for k, ok in checks.items():
            print(f"{'pass' if ok else 'FAIL'} {k} (gate.py rule, applied with disk_bands)")


GROUP_NAMES = ["unflagged", "possibly_raised", "flagged"]
GROUPS_DOC = ("r1 group-conditional normalised conformal bands (top-level q is null on purpose: a reader that only "
              "knows one q must fail). p = model_<FIPS>.txt(FEATS); s = max(difficulty_<FIPS>.txt(FEATS + p), 0.05); "
              "r = raised_<FIPS>.txt(FEATS + p), lightgbm Booster.predict (binary: probability). group = 'flagged' if "
              "p > flag_ft, else 'possibly_raised' if r >= threshold, else 'unflagged'. band = [p - q_lo[group] * s, "
              "p + q_hi[group] * s]. q per group: finite-sample 90% quantile of |y - p| / s over the group's CAL "
              "houses; in elevated_q_groups, the larger of that and the same quantile over the group's CAL houses "
              "with certificate diagram 5-9 (the label is read only at calibration, never at prediction).")


def disk_bands(d: Path, fips: str, x: pd.DataFrame):
    """Reference reader for r0 (single q) and r1 (groups) artefacts: what gate.scored and assemble need."""
    bands = json.loads((d / f"bands_{fips}.json").read_text())
    assert bands["features"] == FEATS
    p = lgb.Booster(model_file=str(d / f"model_{fips}.txt")).predict(x[FEATS])
    s = np.maximum(lgb.Booster(model_file=str(d / f"difficulty_{fips}.txt")).predict(x[FEATS].assign(p=p)), 0.05)
    g = bands.get("groups")
    if g is None:
        return p, p - bands["q"] * s, p + bands["q"] * s, np.full(len(p), "all", object)
    r = lgb.Booster(model_file=str(d / g["classifier"]["file"])).predict(x[FEATS].assign(p=p))
    grp = np.where(p > g["flag_ft"], "flagged", np.where(r >= g["threshold"], "possibly_raised", "unflagged"))
    ql, qh = pd.Series(grp).map(g["q_lo"]).values, pd.Series(grp).map(g["q_hi"]).values
    return p, p - ql * s, p + qh * s, grp

if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main()
