"""Release gate v2 (r1 plan docs/09 D2 and §4; plan docs/04 §4, decisions 12-13): a rebuilt floor model publishes only
if, on the SAME houses, it is not worse than the release it replaces, by more than the noise of the comparison.

Both models (a directory each: model_<FIPS>.txt, difficulty_<FIPS>.txt, bands_<FIPS>.json, as train.py writes them)
are scored per house with train.score's definitions, on four tables:
  benchmark | fdem       r0's 102 test blocks (split_<FIPS>.json, origin r0, part test), FDEM labels
  benchmark | combined   the same blocks, FDEM + Pinellas County labels (labels_pinellas/build.py)
  held_out  | fdem       every test block of the split (benchmark + blocks hashed into test later)
  held_out  | combined
Each model is scored on its OWN run's features and ground base (bands json `run` / `base`; r0: pinellas_2018, ring
minimum), on the houses both models' train.py screens keep. Every metric is then a floor-elevation comparison
(predicted floor = base + p), so models with different bases compare like for like. "Truly raised" is the
certificate's own floor height (floor - certificate LAG) > 3 ft, model-independent, where the label carries it.
A house either model trained or calibrated on can only be in a FIT / CAL block, so no table holds one.
Pass rule, on the two BENCHMARK tables:
  - paired block bootstrap (resample blocks with replacement, --boot draws, seed 0) of candidate - baseline for MAE,
    BFE side, coverage, decided correct, and the conditional coverage of truly raised & unflagged houses
    (dh > 3 ft, p <= 3 ft): a regression is a 95% interval that excludes zero the wrong way (MAE: lower bound > 0;
    the others: upper bound < 0);
  - r0's fixed tolerances kept as a floor: MAE diff <= +0.05 ft, the others >= -0.01;
  - absolute coverage >= 0.88 on every table (benchmark and held-out, both label sets).
The held-out tables and the conditional-coverage rows (truly raised & unflagged, diagram 5-9 unflagged, slab 1A/1B
truly raised) are printed and stored for every table, with n, and the marginal bootstrap sd of each candidate metric.
With no baseline only the absolute coverage floor applies.
--self-test runs the gate twice with the baseline as candidate: unchanged (must pass) and with q halved (must fail).
Output: pipeline/train/out/gate_<FIPS>_<release>.json (all four tables); exit 1 when the gate (or self-test) fails.
Usage: python pipeline/train/gate.py 12103 pinellas_2018 --candidate DIR [--baseline DIR] --release NAME
           [--labels FILE] [--labels-combined FILE] [--boot 2000] [--self-test]
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
import split
from train import DATA, band_q, feats, features, score

TOL = {"MAE": 0.05, "BFE side": 0.01, "coverage": 0.01, "decided correct": 0.01}
COVERAGE_FLOOR = 0.88
METRICS = ["MAE", "BFE side", "coverage", "decided correct", "raised unflagged coverage"]
LOWER_IS_BETTER = {"MAE"}
COMBINED = DATA / "labels_pinellas" / "labels_combined_12103.parquet"


def load(d: Path, fips: str):
    """A model dir; its bands json names its run and ground base (r0's has neither: pinellas_2018, ring minimum)."""
    bands = json.loads((d / f"bands_{fips}.json").read_text())
    bands.setdefault("run", "pinellas_2018")
    bands.setdefault("base", "lag")
    assert bands["features"] == feats(bands["base"]), f"{d}: model features differ from train.py's for its base"
    return (
        lgb.Booster(model_file=str(d / f"model_{fips}.txt")),
        lgb.Booster(model_file=str(d / f"difficulty_{fips}.txt")),
        bands,
    )


def predict(d: Path, fips: str, t: pd.DataFrame, q_mult: float = 1.0):
    """p, lo, hi for t, which must hold this model's run features (frame())."""
    model, diff, bands = load(d, fips)
    fe = bands["features"]
    p = model.predict(t[fe])
    s = np.maximum(diff.predict(t[fe].assign(p=p)), 0.05)
    q = band_q(bands, p) * q_mult
    return p, p - q * s, p + q * s


def scored(d: Path, fips: str, t: pd.DataFrame) -> dict:
    p, lo, hi = predict(d, fips, t)
    return {k: float(v) for k, v in score(t, p, lo, hi).items()}


def raised_truth(t: pd.DataFrame) -> np.ndarray:
    """Certificate floor minus the certificate's own LAG > 3 ft where the label has it, else dh > 3."""
    if "cert_lag_ft" in t.columns:
        own = t.ffe_ft.values - t.cert_lag_ft.values
        return np.where(np.isnan(own), t.dh.values > 3, own > 3)
    return t.dh.values > 3


def per_house(t: pd.DataFrame, p, lo, hi) -> pd.DataFrame:
    """train.score's quantities per house, so a block bootstrap can re-aggregate them."""
    y = t.dh.values
    s = t.cert_zone.astype(str).str.upper().str[:1].isin(["A", "V"]).values & t.cert_bfe_ft.notna().values
    lag, bfe, ffe = t.g_base.values, t.cert_bfe_ft.values, t.ffe_ft.values
    above, below = s & (lag + lo >= bfe), s & (lag + hi < bfe)
    dec = above | below
    ru = raised_truth(t) & (p <= 3)
    cov = (y >= lo) & (y <= hi)
    return pd.DataFrame(
        {
            "block": t.block.values,
            "n": 1.0,
            "abs_err": np.abs(p - y),
            "s": s.astype(float),
            "side_ok": (s & ((ffe >= bfe) == (lag + p >= bfe))).astype(float),
            "cov": cov.astype(float),
            "dec": dec.astype(float),
            "dec_ok": ((above & (ffe >= bfe)) | (below & (ffe < bfe))).astype(float),
            "ru": ru.astype(float),
            "ru_cov": (ru & cov).astype(float),
        }
    )


def ratios(sums: np.ndarray) -> np.ndarray:
    """sums[..., k] in per_house column order (n, abs_err, s, side_ok, cov, dec, dec_ok, ru, ru_cov) -> METRICS."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.stack(
            [
                sums[..., 1] / sums[..., 0],
                sums[..., 3] / sums[..., 2],
                sums[..., 4] / sums[..., 0],
                sums[..., 6] / sums[..., 5],
                sums[..., 8] / sums[..., 7],
            ],
            axis=-1,
        )


COLS = ["n", "abs_err", "s", "side_ok", "cov", "dec", "dec_ok", "ru", "ru_cov"]


def bootstrap(hc: pd.DataFrame, hb: pd.DataFrame | None, boot: int) -> dict:
    """Paired block bootstrap: the same resampled blocks for both models."""
    bc = hc.groupby("block")[COLS].sum()
    w = np.random.default_rng(0).multinomial(len(bc), np.full(len(bc), 1 / len(bc)), size=boot)
    rc = ratios(w @ bc.values)
    out = {"blocks": len(bc), "candidate_sd": dict(zip(METRICS, np.nanstd(rc, axis=0).round(4).tolist(), strict=True))}
    if hb is not None:
        bb = hb.groupby("block")[COLS].sum().reindex(bc.index)
        d = rc - ratios(w @ bb.values)
        lo, hi = np.nanpercentile(d, 2.5, axis=0), np.nanpercentile(d, 97.5, axis=0)
        out["diff_ci95"] = {
            m: [round(float(a), 4), round(float(b), 4)] for m, a, b in zip(METRICS, lo, hi, strict=True)
        }
        out["diff_sd"] = dict(zip(METRICS, np.nanstd(d, axis=0).round(4).tolist(), strict=True))
    return out


def conditional(t: pd.DataFrame, p, lo, hi) -> dict:
    """Conditional coverage rows. "Truly raised" = certificate floor - the certificate's own LAG > 3 ft where the label
    carries cert_lag_ft (model-independent, so both models are judged on the same houses), else dh > 3."""
    y = t.dh.values
    cov = (y >= lo) & (y <= hi)
    dg = t.diagram.astype(str)
    tr = raised_truth(t)
    rows = {
        "truly raised & unflagged (p <= 3)": tr & (p <= 3),
        "diagram 5-9 unflagged (p <= 3)": dg.str[0].isin(list("56789")).values & (p <= 3),
        "slab 1A/1B truly raised": dg.isin(["1A", "1B"]).values & tr,
    }
    return {
        k: {"n": int(m.sum()), "coverage": round(float(cov[m].mean()), 3) if m.any() else None} for k, m in rows.items()
    }


FRAMES: dict[str, pd.DataFrame] = {}


def frame(fips: str, run: str) -> pd.DataFrame:
    if run not in FRAMES:
        FRAMES[run] = features(fips, run)
    return FRAMES[run]


def paired(lpath: Path, fips: str, cand: Path, base: Path | None):
    """The label set screened on each model's own run, restricted to houses BOTH screens keep, in one order."""
    lab = pd.read_parquet(lpath)
    dc = split.screened(lab, frame(fips, load(cand, fips)[2]["run"]))
    if base is None:
        return dc, None
    db = split.screened(lab, frame(fips, load(base, fips)[2]["run"]))
    ids = sorted(set(dc.building_id) & set(db.building_id))
    dc = dc.set_index("building_id").loc[ids].reset_index()
    db = db.set_index("building_id").loc[ids].reset_index()
    assert (dc.block.values == db.block.values).all()
    return dc, db


def evaluate(a, q_mult: float = 1.0) -> dict:
    s = split.load(a.fips)["blocks"]
    bench = split.benchmark(a.fips)
    held = {b for b, v in s.items() if v["part"] == "test"}
    labels = {"fdem": a.labels, "combined": a.labels_combined}
    tables: dict = {}
    checks: dict[str, bool] = {}
    for lname, lpath in labels.items():
        d, db = paired(lpath, a.fips, a.candidate, a.baseline)
        # blocks the split has not seen (only train.py extends it) belong to no table: counted, never scored
        unknown = set(d.block) - set(s)
        tables[f"{lname}: label blocks not in the split"] = {
            "blocks": len(unknown),
            "houses": int(d.block.isin(unknown).sum()),
        }
        for sname, blocks in (("benchmark", bench), ("held_out", held)):
            m = d.block.isin(blocks).values
            t = d[m].reset_index(drop=True)
            tb = db[m].reset_index(drop=True) if db is not None else None
            pc = predict(a.candidate, a.fips, t, q_mult)
            pb = predict(a.baseline, a.fips, tb) if tb is not None else None
            row: dict = {"houses": len(t), "candidate": {k: float(v) for k, v in score(t, *pc).items()}}
            row["candidate_conditional"] = conditional(t, *pc)
            hc = per_house(t, *pc)
            hb = None
            if pb is not None:
                row["baseline"] = {k: float(v) for k, v in score(tb, *pb).items()}
                row["baseline_conditional"] = conditional(tb, *pb)
                hb = per_house(tb, *pb)
            row["bootstrap"] = bootstrap(hc, hb, a.boot)
            key = f"{sname} | {lname}"
            tables[key] = row
            checks[f"{key}: coverage >= {COVERAGE_FLOOR}"] = row["candidate"]["coverage"] >= COVERAGE_FLOOR
            if pb is None or sname != "benchmark":
                continue
            ci = row["bootstrap"]["diff_ci95"]
            for m in METRICS:
                lo_, hi_ = ci[m]
                regress = lo_ > 0 if m in LOWER_IS_BETTER else hi_ < 0
                checks[f"{key}: {m} no regression (95% CI {lo_:+.4f} .. {hi_:+.4f})"] = not regress
            cand, base = row["candidate"], row["baseline"]
            checks[f"{key}: MAE floor (diff <= +{TOL['MAE']})"] = cand["MAE"] - base["MAE"] <= TOL["MAE"]
            for m in ("BFE side", "coverage", "decided correct"):
                checks[f"{key}: {m} floor (diff >= -{TOL[m]})"] = cand[m] - base[m] >= -TOL[m]
    return {"tables": tables, "checks": checks, "passed": all(checks.values())}


def report(res: dict) -> None:
    cols = ["n", "MAE", "within 1 ft", "BFE side", "coverage", "decided correct", "BFE decided"]
    for key, row in res["tables"].items():
        if "candidate" not in row:
            print(f"\n{key}: {row}")
            continue
        rows = {m: row[m] for m in ("candidate", "baseline") if m in row}
        print(f"\n## {key}: {row['houses']} houses, {row['bootstrap']['blocks']} blocks")
        print(pd.DataFrame(rows).T[cols].round(3).to_markdown())
        cond = {m: {k: f"{v['coverage']} (n {v['n']})" for k, v in row[f"{m}_conditional"].items()} for m in rows}
        print(pd.DataFrame(cond).to_markdown())
        if "diff_ci95" in row["bootstrap"]:
            print("paired bootstrap 95% CI of candidate - baseline:", row["bootstrap"]["diff_ci95"])
        print("marginal sd of the candidate:", row["bootstrap"]["candidate_sd"])
    print()
    for k, ok in res["checks"].items():
        print(f"{'pass' if ok else 'FAIL'} {k}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("run")
    ap.add_argument("--candidate", type=Path)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--release", required=True)
    ap.add_argument("--labels", type=Path, help="FDEM labels (default data/flood_v1/train/labels_<FIPS>.parquet)")
    ap.add_argument("--labels-combined", type=Path, default=COMBINED)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    a.labels = a.labels or DATA / "train" / f"labels_{a.fips}.parquet"
    out = Path(__file__).parent / "out" / f"gate_{a.fips}_{a.release}.json"
    meta = {
        "fips": a.fips,
        "release": a.release,
        "labels": str(a.labels),
        "labels_combined": str(a.labels_combined),
        "boot": a.boot,
        "tolerances_floor": TOL,
        "coverage_floor": COVERAGE_FLOOR,
    }
    if a.self_test:
        assert a.baseline, "--self-test needs --baseline"
        a.candidate = a.baseline
        same, halved = evaluate(a), evaluate(a, q_mult=0.5)
        ok = same["passed"] and not halved["passed"]
        print(
            f"self-test: same model {'passes' if same['passed'] else 'FAILS'}, "
            f"halved q {'fails' if not halved['passed'] else 'PASSES'} -> {'OK' if ok else 'BROKEN'}"
        )
        for k, v in halved["checks"].items():
            if not v:
                print(f"  halved q fails: {k}")
        out.write_text(json.dumps(meta | {"self_test": {"same": same, "halved_q": halved, "ok": ok}}, indent=1))
        sys.exit(0 if ok else 1)
    assert a.candidate, "--candidate is required"
    res = evaluate(a)
    report(res)
    out.write_text(json.dumps(meta | {"candidate": str(a.candidate), "baseline": str(a.baseline)} | res, indent=1))
    print("GATE", "PASSED" if res["passed"] else "FAILED", "->", out)
    sys.exit(0 if res["passed"] else 1)


if __name__ == "__main__":
    main()
