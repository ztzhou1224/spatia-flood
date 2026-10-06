"""Which flight to build heights from, and change detection from roofs alone (no trees).

Feature sets (lpc_features.py; heights above the 2018 DEM lowest adjacent grade, 2024 shifted by the area's median
ground shift):
  2018 class6     TX_CoastalRegion_2018_A18 (QL2), building = class 6  (the benchmark's features)
  2018 single     same flight, building = non-ground single returns >= 5 ft (the rule the 2024 flight needs)
  2024 single     TX_Houston_B24 (QL1, no building class), building = non-ground single returns >= 5 ft
1) Agreement of 2018 single with 2018 class6 (median |difference| of roof / eave measures).
2) Change 2018 -> 2024 from the single-return roofs: d_roof = roof_p50, d_eave = eave_p50 differences. Rule
   "up" = both > 3 ft (no ridge: trees). Checked against HCAD 2018 vs 2025 records (eval_change.rec_class), next to
   the lpc_change.py rule (ridge, roof and eave of all non-ground returns > 3 ft).
3) Scorer: benchmark method E (5-fold by 1 km block) and the label-free split estimate G with each feature set, on
   the screened answer key (one screen for all: the 2018 class6 one): all houses; houses unchanged between the flights (|d_roof| and |d_eave| < 1 ft, label-
   free), where the key holds for both flights; and Harris County key points (captured 2019-11..2020-06, nearer the
   2024 flight) that are unchanged.
Usage: python eval_flights.py A C
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from benchmark import metrics, predictions  # noqa: E402
from eval_change import D, rec_class, records  # noqa: E402
from eval_transfer import load  # noqa: E402

FEATS = {"2018 class6": "lpc_features", "2018 single": "lpc_features_2018_single", "2024 single": "lpc_features_2024_single"}
T = 3.0


def main(areas):
    b = records()
    for area in areas:
        lf = {k: pd.read_parquet(D / area / f"{v}.parquet") for k, v in FEATS.items()}
        m = lf["2018 class6"].merge(lf["2018 single"], on="oid", suffixes=("", "_s18"))
        print(f"\n# {area}\n\n2018 single vs 2018 class6, median |difference| (ft): " + ", ".join(
            f"{c} {(m[c + '_s18'] - m[c]).abs().median():.2f}" for c in ("roof_p50", "eave_p50", "eave_main", "ridge")))
        ch = lf["2018 single"].merge(lf["2024 single"], on="oid", suffixes=("_18", "_24"))
        ch["d_roof"], ch["d_eave"] = ch.roof_p50_24 - ch.roof_p50_18, ch.eave_p50_24 - ch.eave_p50_18
        ch["same"] = (ch.d_roof.abs() < 1) & (ch.d_eave.abs() < 1)
        h = pd.read_parquet(D / area / "houses.parquet", columns=["oid", "hcad"])
        old = pd.read_parquet(D / area / "lpc_change.parquet")
        f = h.merge(ch[["oid", "d_roof", "d_eave", "same"]], on="oid").merge(
            old[["oid", "d_ridge", "d_roof", "d_eave"]].rename(columns=lambda c: c if c == "oid" else c + "_old"), on="oid", how="left")
        f = f.merge(b, left_on="hcad", right_on="acct", how="left")
        f["record"] = rec_class(f)
        f["single-return roofs"] = np.where((f.d_roof > T) & (f.d_eave > T), "up", "not up")
        f["lpc_change rule"] = np.where((f.d_ridge_old > T) & (f.d_roof_old > T) & (f.d_eave_old > T), "up", "not up")
        print(f"\nchange 2018 -> 2024, houses measured in both flights {len(f)}; unchanged (|d| < 1 ft) {f.same.mean():.1%}\n")
        print(pd.crosstab(f.record, [f["single-return roofs"], f["lpc_change rule"]], margins=True).to_markdown())

        screen = load(area)[["oid", "key_ok"]]  # one answer-key screen (2018 class6 roof_p95) for every feature set
        rows = {}
        for k, v in FEATS.items():
            g = load(area, v).drop(columns="key_ok").merge(screen, on="oid")
            g["block"] = (g.x // 1000).astype(int).astype(str) + "_" + (g.y // 1000).astype(int).astype(str)
            p = predictions(g, g, True)
            g = g.merge(ch[["oid", "same"]], on="oid", how="left")
            for nm, mm in (("all", g.key_ok), ("unchanged", g.key_ok & g.same.fillna(False).astype(bool)),
                           ("unchanged, key 2019-20", g.key_ok & g.same.fillna(False).astype(bool)
                            & g.delivery.str.startswith("Harris County"))):
                mm = mm.values
                for meth in ("E + eave estimate", "G physical only"):
                    r = metrics(p[meth][mm], g[mm].reset_index(drop=True))
                    rows[(nm, meth[0], k)] = {c: r.get(c) for c in ("n", "MAE", "within_1", "raised_MAE", "raised_recall",
                                                                     "BFE_side_correct", "MAE_95ci")}
        print(f"\nscorer, {area}: features from each flight / rule (screened key; E = 5-fold by 1 km block, G = label-free)\n")
        print(pd.DataFrame(rows).T.round(3).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main(sys.argv[1:])
