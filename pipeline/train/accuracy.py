"""The accuracy card (r1 plan docs/09 A1, review docs/07 DA1): the released floor model scored on TWO populations, each
with its population stated, so no single score is mistaken for the whole story.

  fdem_held_out   FDEM certificate labels (labels_<FIPS>.parquet in --model, the set it was trained on) in its TEST
                  blocks
                  (bands json `test_blocks`): the release gate's number.
  county_independent  Pinellas County certificate layer (labels_pinellas/labels_pinellas_<FIPS>.parquet), native
                  NAVD88 rows only, on buildings with NO FDEM certificate of any stage (so the table holds no record
                  floor for them and the model never saw them as labels), all blocks; the r0-TEST-block subset is
                  reported beside it.

Both are scored by train.score on the same screened target (dh = certificate first living floor - the model's run
ground base g_base, ring minimum for r0, masked ring median for r1; screen:
roof_p95 - dh < 6 or dh < -1 dropped), with the model's own bands, and certificate zone / BFE for the BFE side. The
county population is the one that is independent of the training labels' source; the FDEM one is the gate's.
Per population: overall, slab (1A / 1B), elevated (diagram 5-9) and elevated not flagged (p <= 3 ft, the band the
review found under-covers: M2), coverage with a Wilson 95% interval. Plus, from the published table on the county
population, how many of its `above` / `below` calls a surveyed certificate contradicts (certificate floor vs the
table's BFE).
Output: pipeline/train/out/accuracy_<FIPS>_<release>.json and a markdown table on stdout.
Usage: python pipeline/train/accuracy.py 12103 pinellas_2018 --model DIR --release NAME [--no-table] [--all-stages]
       (the r0 card: --model data/flood_v1/train_r0 --release pinellas-r0
        --county-labels data/flood_v1/labels_pinellas/r0/labels_pinellas_12103.parquet)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate import load
from train import DATA, features, score, screen

ELEVATED = list("56789")
KEYS = [
    "n",
    "MAE",
    "within 1 ft",
    "BFE side",
    "coverage",
    "coverage flagged",
    "coverage not flagged",
    "BFE decided",
    "decided correct",
    "SFHA with BFE",
    "raised n",
    "raised recall",
]


def wilson(k: int, n: int) -> list:
    if n == 0:
        return [None, None]
    z, ph = 1.96, k / n
    c = (ph + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(float(c - h), 3), round(float(c + h), 3)]


def screened(lab: pd.DataFrame, f: pd.DataFrame) -> pd.DataFrame:
    return screen(lab, f)


def card(d: pd.DataFrame, model, diff, q: float, fe: list[str]) -> dict:
    p = model.predict(d[fe])
    s = np.maximum(diff.predict(d[fe].assign(p=p)), 0.05)
    lo, hi = p - q * s, p + q * s
    cov = (d.dh.values >= lo) & (d.dh.values <= hi)
    elev = d.diagram.astype(str).str[0].isin(ELEVATED).values
    slab = d.diagram.astype(str).isin(["1A", "1B"]).values
    out: dict = {}
    for name, m in (
        ("all", np.ones(len(d), bool)),
        ("slab 1A/1B", slab),
        ("elevated 5-9", elev),
        ("elevated 5-9 not flagged", elev & (p <= 3)),
    ):
        if not m.any():
            continue
        sc = score(d[m].reset_index(drop=True), p[m], lo[m], hi[m])
        r = {k: (round(float(sc[k]), 3) if isinstance(sc[k], float) else int(sc[k])) for k in KEYS}
        r["median error"] = round(float(np.median(p[m] - d.dh.values[m])), 3)
        r["coverage CI95"] = wilson(int(cov[m].sum()), int(m.sum()))
        out[name] = r
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("run")
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--release", required=True)
    ap.add_argument(
        "--no-table",
        action="store_true",
        help="skip the published-table check (run before assemble.py writes the release's table)",
    )
    ap.add_argument(
        "--all-stages",
        action="store_true",
        help="keep county certificates of every stage (the r0 card was scored before stages were read)",
    )
    ap.add_argument("--county-labels", type=Path, default=DATA / "labels_pinellas" / "labels_pinellas_12103.parquet")
    a = ap.parse_args()
    model, diff, bands = load(a.model, a.fips)
    q, test = bands["q"], set(bands["test_blocks"])
    f = features(a.fips, bands["run"])  # the model's own run (its ground base and features)
    fd = pd.read_parquet(a.model / f"labels_{a.fips}.parquet")  # the labels this model was trained on
    co = pd.read_parquet(a.county_labels)
    co_native = co[co.vertical_datum_route == "navd88_native"]
    if "record_stage" in co.columns and not a.all_stages:  # finished construction only (docs/09 B4)
        co_native = co_native[co_native.record_stage == "finished_construction"]
    fdem_any = set(fd.building_id)
    cert = DATA / "train" / f"certificates_{a.fips}.parquet"  # any-stage FDEM certificates (labels.py, r1 on)
    if cert.exists():
        fdem_any |= set(pd.read_parquet(cert, columns=["building_id"]).building_id)
    co_only = co_native[~co_native.building_id.isin(fdem_any)]
    dfd = screened(fd, f)
    dco = screened(co_only, f)
    res: dict = {
        "fips": a.fips,
        "release": a.release,
        "model": str(a.model),
        "q": q,
        "populations": {
            "fdem_held_out": "FDEM certificates (statewide EC layer via Forerunner) in the model's held-out 1 km test "
            f"blocks ({len(test)} blocks); the release gate's set",
            "county_independent": "Pinellas County certificate layer, native NAVD88, buildings with no FDEM label "
            "(never a training label), all blocks; certificate first living floor (C2a for "
            "1A/1B/5, C2b otherwise)",
        },
        "counts": {
            "county labels": len(co),
            "county native NAVD88": len(co_native),
            "county native, no FDEM label": len(co_only),
            "county scored (screened, lidar ok)": len(dco),
        },
        "fdem_held_out": card(dfd[dfd.block.isin(test)].reset_index(drop=True), model, diff, q, bands["features"]),
        "county_independent": card(dco, model, diff, q, bands["features"]),
        "county_independent_r0_test_blocks": card(
            dco[dco.block.isin(test)].reset_index(drop=True), model, diff, q, bands["features"]
        ),
    }
    # the published table's calls on the county population, checked against the surveyed certificate
    out = Path(__file__).parent / "out" / f"accuracy_{a.fips}_{a.release}.json"
    if a.no_table:
        res["table_calls_vs_county_certificate"] = None
    else:
        res["table_calls_vs_county_certificate"] = table_calls(a.fips, a.release, co_only)
    out.write_text(json.dumps(res, indent=1))
    rows = {
        f"{pop} | {g}": v
        for pop in ("fdem_held_out", "county_independent", "county_independent_r0_test_blocks")
        for g, v in res[pop].items()
    }
    pd.set_option("display.width", 250)
    print(json.dumps({k: res[k] for k in ("counts", "table_calls_vs_county_certificate")}, indent=1))
    print(
        pd.DataFrame(rows)
        .T[
            [
                "n",
                "MAE",
                "median error",
                "within 1 ft",
                "coverage",
                "coverage CI95",
                "BFE side",
                "BFE decided",
                "decided correct",
            ]
        ]
        .to_markdown()
    )
    print(f"-> {out}")


def table_calls(fips: str, release: str, co_only: pd.DataFrame) -> dict:
    tb_path = DATA / "assemble" / f"buildings_{fips}.parquet"
    meta = json.loads(pq.read_schema(tb_path).metadata[b"spatia_flood"])
    assert meta["release"] == release, f"{tb_path} is {meta['release']}, not {release} (use --no-table)"
    tb = pd.read_parquet(tb_path, columns=["building_id", "ffh_class", "bfe_call", "bfe_ft", "touches_sfha"])
    t = co_only.merge(tb, on="building_id")
    t = t[(t.ffh_class == "modeled") & t.bfe_call.isin(["above", "below"]) & t.bfe_ft.notna()]
    cert_above = t.ffe_ft >= t.bfe_ft
    return {
        "table": tb_path.name,
        "decided calls on county-only modeled rows": len(t),
        "above": int((t.bfe_call == "above").sum()),
        "above contradicted (certificate floor < table BFE)": int(((t.bfe_call == "above") & ~cert_above).sum()),
        "below": int((t.bfe_call == "below").sum()),
        "below contradicted (certificate floor >= table BFE)": int(((t.bfe_call == "below") & cert_above).sum()),
    }


if __name__ == "__main__":
    main()
