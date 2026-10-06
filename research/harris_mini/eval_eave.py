"""A finer label-free reference for the eave-minus-stories height (the Meyerland weakness: 3-5 ft lifts).

eval_transfer.load computes est = eave - typical eave of reference houses (HCAD 2018: slab, no lower level) with the
same story count over the WHOLE area + SLAB_FT. The typical eave of a slab house varies with plate height (era,
builder) and with local ground / DEM bias, so the reference is refined here, still without the answer key:
  area     as now: median over the area's reference houses with the same stories
  era      median over reference houses with the same stories and year-built band (< 1960, 1960-79, 1980-99, 2000+)
  local    median over the K nearest reference houses with the same stories (the house itself excluded), K = 15
  local_era  K nearest with the same stories and year-built band
Each for eave_p50 (one-story) / eave_main (two-story) = the "split" choice. Spread of the reference itself (IQR of
eave minus its reference, over reference houses) shows how much noise each removes. Scorer: median absolute and
mean absolute error against the answer key, all screened houses and raised houses (door > 3 ft), per area; then the
benchmark E / F with the best reference (within area and new area) next to the current ones.
Usage: python eval_eave.py [FEATURES_TAG]   (tag selects lpc_features<tag>.parquet, e.g. _2018_single; default none)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from eval_stories import SLAB_FT  # noqa: E402

K = 15
ERA = [0, 1960, 1980, 2000, 3000]


def era(y):
    return pd.cut(pd.to_numeric(y, errors="coerce"), ERA, right=False, labels=False)


def reference(f, col, how):
    """Typical eave of reference houses for each house (NaN when no reference)."""
    ref = (f.foundation == "Slab") & (f.has_lower == 0) & f[col].notna()
    out = np.full(len(f), np.nan)
    keys = ["stories"] + (["era"] if how in ("era", "local_era") else [])
    for _, g in f.groupby(keys, dropna=True):
        r = g[ref.loc[g.index]]
        if len(r) < 5:
            continue
        if how in ("area", "era"):
            out[g.index] = r[col].median()
            continue
        tree = cKDTree(np.c_[r.x, r.y])
        k = min(K + 1, len(r))
        _, j = tree.query(np.c_[g.x, g.y], k=k)
        vals = r[col].values[j]
        self_ = r.index.values[j] == g.index.values[:, None]
        vals = np.where(self_, np.nan, vals)
        vals[~self_.any(axis=1), -1] = np.nan  # K neighbours for every house
        out[g.index] = np.nanmedian(vals, axis=1)
    return out


def add_estimates(f):
    f = f.copy()
    f["era"] = era(f.year_built)
    for how in ("area", "era", "local", "local_era"):
        for col in ("eave_p50", "eave_main"):
            f[f"ref_{how}_{col}"] = reference(f, col, how)
        p50 = f.eave_p50 - f[f"ref_{how}_eave_p50"] + SLAB_FT
        main = f.eave_main - f[f"ref_{how}_eave_main"] + SLAB_FT
        f[f"est_{how}"] = np.where(f.stories == 1, p50, main)
    return f


def main(tag=""):
    import eval_transfer as et
    for area in ("A", "B", "C"):
        if not (et.D / "harris_mini" / area / f"lpc_features{tag}.parquet").exists():
            continue
        f = add_estimates(et.load(area, f"lpc_features{tag}"))
        ref = (f.foundation == "Slab") & (f.has_lower == 0)
        rows = {}
        for how in ("area", "era", "local", "local_era"):
            e = f[f"est_{how}"] - f.dh
            s, r = f.key_ok, f.key_ok & (f.dh > 3)
            spread = f[f"est_{how}"][ref]
            rows[how] = {"reference IQR ft": spread.quantile(.75) - spread.quantile(.25),
                         "n": int(e[s].notna().sum()), "median abs": e[s].abs().median(), "MAE": e[s].abs().mean(),
                         "raised n": int(e[r].notna().sum()), "raised median abs": e[r].abs().median(),
                         "raised MAE": e[r].abs().mean(), "raised median signed": e[r].median()}
            for st in (1, 2):
                rr = r & (f.stories == st)
                rows[how][f"raised {st}-story median abs"] = e[rr].abs().median()
        print(f"\n## {area}{' ' + tag if tag else ''}: eave-minus-stories height by reference (screened key)\n")
        print(pd.DataFrame(rows).T.round(2).to_markdown())
        r = f[f.key_ok & (f.dh > 3)].assign(err=lambda x: x.est_area - x.dh)
        print(f"\n{area}: raised houses (screened) by HCAD 2018 stories and foundation, area reference:\n")
        print(r.groupby(["stories", "foundation"]).agg(n=("dh", "size"), key_median=("dh", "median"),
              est_median=("est_area", "median"), median_abs=("err", lambda e: e.abs().median()),
              median_signed=("err", "median")).round(2).to_markdown())


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main(*sys.argv[1:2])
