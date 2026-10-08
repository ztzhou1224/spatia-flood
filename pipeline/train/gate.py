"""Release gate (plan docs/04 §4, decisions 12-13): a rebuilt floor model publishes only if, on the SAME held-out
houses, it is no worse than the release it replaces.

Both models (a directory each, holding model_<FIPS>.txt, difficulty_<FIPS>.txt, bands_<FIPS>.json as train.py writes
them) are scored with train.score on one test set: the screened labels in the CANDIDATE's held-out blocks (its
bands json `test_blocks`; train.py draws them from every label batch, so a new batch's 20% is inside). Scoring the
two on the same houses is what makes "no worse" a comparison of models, not of test sets.
Thresholds (fixed in phase 1; tolerances absorb run-to-run noise of one held-out draw):
  MAE              candidate <= baseline + 0.05 ft
  BFE side correct candidate >= baseline - 0.01
  90% coverage     candidate >= baseline - 0.01, and >= 0.88 (never far below the nominal 0.90)
  decided correct  candidate >= baseline - 0.01 (precision of the above / below calls)
With no baseline (the first release), only the absolute coverage floor applies.
Output: the comparison table on stdout and pipeline/train/out/gate_<FIPS>_<release>.json; exit 1 when the gate fails.
Labels: data/flood_v1/train/labels_<FIPS>.parquet by default; --labels FILE scores on another label set with the same
columns (added 2026-10-07 for r1b, whose held-out blocks include Pinellas County certificate labels; omitting it gives
the original behaviour).
Usage: python pipeline/train/gate.py 12103 pinellas_2018 --candidate DIR [--baseline DIR] --release NAME [--labels FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train import DATA, FEATS, features, score

TOL = {"MAE": 0.05, "BFE side": 0.01, "coverage": 0.01, "decided correct": 0.01}
COVERAGE_FLOOR = 0.88


def load(d: Path, fips: str):
    bands = json.loads((d / f"bands_{fips}.json").read_text())
    assert bands["features"] == FEATS, f"{d}: model features differ from train.py's"
    return (
        lgb.Booster(model_file=str(d / f"model_{fips}.txt")),
        lgb.Booster(model_file=str(d / f"difficulty_{fips}.txt")),
        bands,
    )


def scored(d: Path, fips: str, t: pd.DataFrame) -> dict:
    model, diff, bands = load(d, fips)
    p = model.predict(t[FEATS])
    s = np.maximum(diff.predict(t[FEATS].assign(p=p)), 0.05)
    return {k: float(v) for k, v in score(t, p, p - bands["q"] * s, p + bands["q"] * s).items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("run")
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--release", required=True)
    ap.add_argument("--labels", type=Path, help="label parquet (default data/flood_v1/train/labels_<FIPS>.parquet)")
    a = ap.parse_args()
    labels = a.labels or DATA / "train" / f"labels_{a.fips}.parquet"
    lab = pd.read_parquet(labels)
    d = lab.merge(features(a.fips, a.run), on="building_id")
    d = d[d.g_lag.notna() & (d.lpc_status == "ok")].copy()
    d["dh"] = d.ffe_ft - d.g_lag
    d = d[~((d.roof_p95 - d.dh < 6) | (d.dh < -1))]
    test = set(load(a.candidate, a.fips)[2]["test_blocks"])
    t = d[d.block.isin(test)].reset_index(drop=True)
    cand = scored(a.candidate, a.fips, t)
    base = scored(a.baseline, a.fips, t) if a.baseline else None
    checks = {"coverage >= floor": cand["coverage"] >= COVERAGE_FLOOR}
    if base:
        checks |= {
            "MAE": cand["MAE"] <= base["MAE"] + TOL["MAE"],
            "BFE side": cand["BFE side"] >= base["BFE side"] - TOL["BFE side"],
            "coverage": cand["coverage"] >= base["coverage"] - TOL["coverage"],
            "decided correct": cand["decided correct"] >= base["decided correct"] - TOL["decided correct"],
        }
    rows = {"candidate": cand} | ({"baseline": base} if base else {})
    print(f"held-out houses: {len(t)} in {len(test)} blocks (candidate's test split)")
    print(
        pd.DataFrame(rows)
        .T[["n", "MAE", "BFE side", "coverage", "decided correct", "BFE decided"]]
        .round(3)
        .to_markdown()
    )
    for k, ok in checks.items():
        print(f"{'pass' if ok else 'FAIL'} {k}")
    passed = all(checks.values())
    out = Path(__file__).parent / "out" / f"gate_{a.fips}_{a.release}.json"
    out.write_text(
        json.dumps(
            {
                "fips": a.fips,
                "release": a.release,
                "candidate": str(a.candidate),
                "baseline": str(a.baseline) if a.baseline else None,
                "labels": str(labels),
                "n_test": len(t),
                "tolerances": TOL,
                "coverage_floor": COVERAGE_FLOOR,
                "scores": rows,
                "checks": checks,
                "passed": passed,
            },
            indent=1,
        )
    )
    print("GATE", "PASSED" if passed else "FAILED")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
