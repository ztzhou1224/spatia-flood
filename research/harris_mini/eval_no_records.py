"""Do floor count and foundation records matter? Method E without NSI and without records (2026-10-07).

Question (owner, 2026-10-07): RentCast's per-house records (foundation type, floor count) cost too much for all of
Florida; free sources first. NSI (stories, foundation type / height) is withheld from any sold build (USACE terms
unread; built partly from commercial inputs), and Florida's DOR roll has no stories / foundation. So: how much
accuracy is lost if the model sees no stories / foundation source at all?

Feature sets (fixed before the first run; LightGBM eval_lpc.P, n_jobs 1):
  E        method E as fl_eval.py method 4 / benchmark.py E (NSI + records where the area has them)
  E-free   E minus every NSI column (nsi_ft, nsi_found_ht, nsi_stories) and every stories / foundation record
           (Harris REC; Florida mapped stories). Kept: DEM ground, point cloud, year built, footprint area, living area
           (HCAD im_sq_ft / DOR tot_lvg_ar, both free public records). Eave estimates with ONE reference (median
           eave of all houses in the area, label-free), no story split.
  E-lidar  E-free + lidar stories: 1 if eave_main < 14 ft else 2 (threshold fixed here, not tuned), used as the
           stories feature and for the eave-estimate split (reference per lidar story count, all houses).
Evaluations: within area, 5 folds by 1 km block (A, B, C, P); across areas, train on the other Harris areas (A, B, C)
and on A + B + C for P. Screened houses (key_ok), scorer = door / living floor height above the DEM LAG.
Output: eval_no_records_output.txt.  Usage: python eval_no_records.py
"""
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eval_lpc as el  # noqa: E402
from benchmark import SETS  # noqa: E402
from eval_stories import SLAB_FT  # noqa: E402
from eval_transfer import DEM, REC, load  # noqa: E402
from fl_eval import florida  # noqa: E402

P1 = {**el.P, "n_jobs": 1}
E = SETS["E + eave estimate"]
NSI = ["nsi_ft", "nsi_found_ht", "nsi_stories"]
EST = ["est_eave_p50", "est_eave_main", "est_split"]
FREE = [c for c in DEM if c not in NSI] + el.LPC + ["im_sq_ft"] + EST
LIDAR = FREE + ["stories"]


def variants(f: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out = {"E": f}
    g = f.copy()
    for c in NSI + [c for c in REC if c != "im_sq_ft"]:  # living area stays: a free public record in both states
        if c in g:
            g[c] = np.nan
    for e in ("eave_p50", "eave_main"):
        g[f"est_{e}"] = g[e] - g[e].median() + SLAB_FT
    g["est_split"] = g.est_eave_p50
    out["E-free"] = g
    h = g.copy()
    st = pd.Series(np.where(h.eave_main.isna(), np.nan, np.where(h.eave_main < 14, 1.0, 2.0)), index=h.index)
    h["stories"] = st
    for e in ("eave_p50", "eave_main"):
        h[f"est_{e}"] = h[e] - st.map(h.groupby(st)[e].median()) + SLAB_FT
    h["est_split"] = np.where(st == 1, h.est_eave_p50, h.est_eave_main)
    out["E-lidar"] = h
    return out


COLS = {"E": E, "E-free": FREE, "E-lidar": LIDAR}


def fit(x, y):
    return lgb.LGBMRegressor(**P1).fit(x, y)


def score(f, p):
    m = f.key_ok.values & np.isfinite(p)
    y, e = f.dh.values[m], p[m] - f.dh.values[m]
    r = y > 3
    s = (f.zone.values[m] == "SFHA") & f.bfe.notna().values[m]
    lag, bfe = f.e2018_lag.values[m][s], f.bfe.values[m][s]
    return {"n": int(m.sum()), "MAE": np.abs(e).mean(), "within 1 ft": (np.abs(e) <= 1).mean(),
            "raised MAE": np.abs(e[r]).mean() if r.any() else np.nan,
            "raised recall": (p[m][r] > 3).mean() if r.any() else np.nan,
            "BFE side": ((lag + y[s] >= bfe) == (lag + p[m][s] >= bfe)).mean() if s.any() else np.nan}


def block(f):
    return (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)


def main():
    areas = {k: load(k) for k in ("A", "B", "C")}
    areas["P"] = florida(True)
    v = {k: variants(f) for k, f in areas.items()}
    rows = {}
    for k in areas:
        for name, cols in COLS.items():
            f = v[k][name]
            p = np.full(len(f), np.nan)
            for a, b in GroupKFold(5).split(f, groups=block(f)):
                p[b] = fit(f.loc[a, cols], f.dh.iloc[a]).predict(f.loc[b, cols])
            rows[(f"{k} within (5-fold 1 km block)", name)] = score(f, p)
    for k in areas:
        train = [t for t in ("A", "B", "C") if t != k]
        for name, cols in COLS.items():
            tr = pd.concat([v[t][name] for t in train], ignore_index=True)
            rows[(f"{k} from {'+'.join(train)}", name)] = score(v[k][name], fit(tr[cols], tr.dh).predict(v[k][name][cols]))
    t = pd.DataFrame(rows).T
    print(t.round(3).to_markdown())
    print("\nlidar stories vs record stories (Harris HCAD; P: NSI) where both exist:")
    for k in areas:
        h = v[k]["E-lidar"]
        rec = areas[k]["stories"] if k != "P" else pd.to_numeric(areas[k].nsi_stories, errors="coerce")
        both = h.stories.notna() & rec.notna()
        print(f"  {k}: n {int(both.sum())}, agree {(h.stories[both] == rec[both].clip(1, 2)).mean():.1%}")


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    main()
