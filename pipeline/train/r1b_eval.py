"""r1b vs r0 on the same houses, with the leakage of the gate's test set made explicit.

gate.py scores both models on the CANDIDATE's held-out blocks. r1b's seed-0 shuffle runs over a different block list
(Pinellas County labels add blocks), so its TEST blocks are not r0's: part of them were r0's FIT / CAL blocks, i.e.
houses the baseline was trained or calibrated on. This script reports, on the screened labels (gate.py's screen):
  - leakage: how many of each test set's houses sit in blocks the OTHER model trained / calibrated on;
  - scores (train.score) of both models on: r1b's test set (the gate's), r0's test set, and the CLEAN set = blocks in
    BOTH test sets (held out from both models), each overall and by label source;
  - r0's point error on r0's TEST blocks by label source x elevated x certificate era (label-quality diagnostic);
  - elevated-unflagged coverage: houses with certificate diagram 5-9 and the model's own p <= 3 ft (r0 report's
    0.790, n 119 definition), with a Wilson 95% interval; and the same on a fixed house set (unflagged by both).
Output: pipeline/train/out/r1b_eval_<FIPS>.json and a markdown table on stdout.
Usage: python pipeline/train/r1b_eval.py 12103 pinellas_2018 --labels FILE --r0 DIR --r1b DIR --r0-labels FILE
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate import load  # noqa: E402
from train import FEATS, features, score  # noqa: E402


def predict(d: Path, fips: str, t: pd.DataFrame):
    model, diff, bands = load(d, fips)
    p = model.predict(t[FEATS])
    s = np.maximum(diff.predict(t[FEATS].assign(p=p)), 0.05)
    return p, p - bands["q"] * s, p + bands["q"] * s


def wilson(k: int, n: int) -> list:
    if n == 0:
        return [None, None]
    z, ph = 1.96, k / n
    c = (ph + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(c - h, 3), round(c + h, 3)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("run")
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--r0", type=Path, required=True)
    ap.add_argument("--r1b", type=Path, required=True)
    ap.add_argument("--r0-labels", type=Path, required=True, help="the labels r0 was trained on")
    a = ap.parse_args()
    lab = pd.read_parquet(a.labels)
    d = lab.merge(features(a.fips, a.run), on="building_id")
    d = d[d.g_lag.notna() & (d.lpc_status == "ok")].copy()
    d["dh"] = d.ffe_ft - d.g_lag
    d = d[~((d.roof_p95 - d.dh < 6) | (d.dh < -1))].reset_index(drop=True)
    r0b, r1b = load(a.r0, a.fips)[2], load(a.r1b, a.fips)[2]
    r0_test, r1_test = set(r0b["test_blocks"]), set(r1b["test_blocks"])
    # blocks each model trained / calibrated on = blocks of ITS screened labels outside its test blocks
    fb = features(a.fips, a.run)
    r0l = pd.read_parquet(a.r0_labels).merge(fb, on="building_id")
    r0l = r0l[r0l.g_lag.notna() & (r0l.lpc_status == "ok")]
    r0l = r0l[~((r0l.roof_p95 - (r0l.ffe_ft - r0l.g_lag) < 6) | ((r0l.ffe_ft - r0l.g_lag) < -1))]
    r0_trained = set(r0l.block) - r0_test
    r1_trained = set(d.block) - r1_test
    res: dict = {"labels": str(a.labels), "r0_test_blocks": len(r0_test), "r1b_test_blocks": len(r1_test),
                 "blocks_in_both_test_sets": len(r0_test & r1_test)}
    sets = {"gate set: r1b TEST": d[d.block.isin(r1_test)], "r0 TEST": d[d.block.isin(r0_test)],
            "CLEAN: both TEST": d[d.block.isin(r0_test & r1_test)]}
    res["leakage"] = {
        "gate set houses in r0 FIT/CAL blocks": int(sets["gate set: r1b TEST"].block.isin(r0_trained).sum()),
        "gate set houses": len(sets["gate set: r1b TEST"]),
        "gate set FDEM houses in r0 FIT/CAL blocks": int(sets["gate set: r1b TEST"].pipe(
            lambda x: x[x.label_source == "fdem"]).block.isin(r0_trained).sum()),
        "r0 TEST houses in r1b FIT/CAL blocks": int(sets["r0 TEST"].block.isin(r1_trained).sum()),
        "r0 TEST houses": len(sets["r0 TEST"])}
    rows = {}
    for sname, t0 in sets.items():
        for src in ("all", "fdem", "pinellas_county"):
            t = (t0 if src == "all" else t0[t0.label_source == src]).reset_index(drop=True)
            if not len(t):
                continue
            preds = {m: predict(dd, a.fips, t) for m, dd in (("r0", a.r0), ("r1b", a.r1b))}
            elev = t.diagram.astype(str).str[0].isin(list("56789")).values
            both_unfl = elev & (preds["r0"][0] <= 3) & (preds["r1b"][0] <= 3)
            for m, (p, lo, hi) in preds.items():
                sc = {k: float(v) for k, v in score(t, p, lo, hi).items()}
                cov = (t.dh.values >= lo) & (t.dh.values <= hi)
                eu = elev & (p <= 3)
                sc |= {"elev 5-9 n": int(elev.sum()), "elev 5-9 coverage": float(cov[elev].mean()),
                       "elev-unflagged n": int(eu.sum()), "elev-unflagged coverage": float(cov[eu].mean()),
                       "elev-unflagged CI95": wilson(int(cov[eu].sum()), int(eu.sum())),
                       "elev-unflagged-by-both n": int(both_unfl.sum()),
                       "elev-unflagged-by-both coverage": float(cov[both_unfl].mean()) if both_unfl.any() else None}
                rows[f"{sname} | {src} | {m}"] = sc
    res["scores"] = rows
    # label diagnostics: r0 point error on r0's TEST blocks (houses AND blocks r0 never trained on), by label source,
    # elevated (diagram 5-9) and certificate era
    t = sets["r0 TEST"].reset_index(drop=True)
    p0 = predict(a.r0, a.fips, t)[0]
    t = t.assign(err=p0 - t.dh.values, elev=t.diagram.astype(str).str[0].isin(list("56789")),
                 era=pd.cut(pd.to_datetime(t.issued_at, unit="ms").dt.year, [1900, 2009, 2014, 2030],
                            labels=["<=2009", "2010-14", ">=2015"]).astype(str))
    diag = {}
    for keys, g in t.groupby(["label_source", "elev", "era"]):
        diag[" | ".join(map(str, keys))] = {"n": len(g), "MAE": round(float(g.err.abs().mean()), 3),
                                            "median_err": round(float(g.err.median()), 3),
                                            "within_1ft": round(float((g.err.abs() <= 1).mean()), 3)}
    for keys, g in t.groupby(["label_source", "elev"]):
        diag[" | ".join(map(str, keys)) + " | all eras"] = {"n": len(g), "MAE": round(float(g.err.abs().mean()), 3),
                                                            "median_err": round(float(g.err.median()), 3),
                                                            "within_1ft": round(float((g.err.abs() <= 1).mean()), 3)}
    res["r0_error_on_r0_test_blocks_by_source_elev_era"] = diag
    out = Path(__file__).parent / "out" / f"r1b_eval_{a.fips}.json"
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "scores"}, indent=1))
    cols = ["n", "MAE", "within 1 ft", "BFE side", "coverage", "decided correct", "BFE decided", "width median not flagged",
            "elev 5-9 n", "elev 5-9 coverage", "elev-unflagged n", "elev-unflagged coverage",
            "elev-unflagged-by-both n", "elev-unflagged-by-both coverage"]
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).T[cols].astype(float).round(3).to_markdown())


if __name__ == "__main__":
    main()
