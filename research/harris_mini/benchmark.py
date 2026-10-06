"""Benchmark of every evidence layer for the front-door floor height, Harris areas B (Cypress Creek) and C (Clear Lake).

Target: front-door height above the DEM lowest adjacent grade (HCFCD answer key, tiers A+B; scorer only). FFE estimate
= DEM lowest adjacent grade + estimated height. Methods, each adding one kind of evidence (fixed before scoring):
  A  national default      DEM ground + NSI default foundation height (no model, no local data)
  B  national model        LightGBM on year built, footprint area, DEM ring stats, NSI type / height / stories
  C  + point cloud         + 2018 lidar point-cloud roof / eave measures of the house (lpc_features.py)
  D  + records             + HCAD stories, lower level, basement, foundation (hcad_buildings.py)
  E  + eave estimate       + label-free eave-minus-stories estimates (eval_transfer.load: p50, main, split)
  F  E, physical override  E, but where the house is flagged raised (record basement / lower level / two-story
                           crawl space, or E > 3 ft) and the label-free split estimate is > 3 ft, use that estimate
  G  physical only         label-free split estimate everywhere (no answer key in calibration at all)
Validation: within an area, 5 folds grouped by 1 km block; across areas, train on the other area. Metrics: MAE,
within 1 ft, raised (door > 3 ft) MAE and detection, and for houses in the SFHA with a BFE: share whose estimated FFE
is on the correct side of the BFE. 95% block-bootstrap interval of MAE. Reported on all houses and on houses whose
answer key passes the screen (eval_stories.py). Image evidence covers ~30 houses and is benchmarked separately at
the end (own Qwen3-VL-4B reads; raised detection and stories only).
Usage: python benchmark.py
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
from eval_stories import boot_ci  # noqa: E402
from eval_transfer import DEM, REC, load  # noqa: E402

D = HERE.parents[1] / "data" / "harris_mini"
SETS = {"B national model": DEM, "C + point cloud": DEM + el.LPC, "D + records": DEM + el.LPC + REC,
        "E + eave estimate": DEM + el.LPC + REC + ["est_eave_p50", "est_eave_main", "est_split"]}


def metrics(p, f):
    y, e = f.dh.values, p - f.dh.values
    ok = np.isfinite(e)
    r = y > 3
    out = {"n": int(ok.sum()), "MAE": np.nanmean(np.abs(e)), "within_1": np.nanmean(np.abs(e[ok]) <= 1),
           "raised_MAE": np.nanmean(np.abs(e[r])), "raised_precision": np.nan, "raised_recall": np.nan}
    fl = ok & (p > 3)
    out["raised_precision"] = (fl & r).sum() / max(fl.sum(), 1)
    out["raised_recall"] = (fl & r).sum() / max((ok & r).sum(), 1)
    s = ok & (f.zone == "SFHA").values & f.bfe.notna().values
    if s.sum():
        truth = f.ffe.values[s] >= f.bfe.values[s]
        est = f.e2018_lag.values[s] + p[s] >= f.bfe.values[s]
        out["SFHA_n"] = int(s.sum())
        out["BFE_side_correct"] = (truth == est).mean()
    out.update(boot_ci(e, y, f.block.values))
    return out


def predictions(train, test, same_area):
    preds = {"A national default": test.nsi_found_ht.values}
    for name, cols in SETS.items():
        if same_area:
            p = np.full(len(test), np.nan)
            for tr, te in GroupKFold(5).split(test, groups=test.block):
                p[te] = lgb.LGBMRegressor(**el.P).fit(test.loc[tr, cols], test.dh.iloc[tr]).predict(test.loc[te, cols])
        else:
            p = lgb.LGBMRegressor(**el.P).fit(train[cols], train.dh).predict(test[cols])
        preds[name] = p
    e = preds["E + eave estimate"]
    flag = ((test.basement > 0) | (test.lower_any > 0) | test.foundation.str.contains("Basement", na=False)
            | ((test.foundation == "Crawl Space") & (test.stories == 2))).values | (e > 3)
    phys = test.est_split.values
    preds["F E, physical override"] = np.where(flag & np.isfinite(phys) & (phys > 3), phys, e)
    preds["G physical only"] = phys
    return preds


def image_component():
    """Own-model image reads (Qwen3-VL-4B) on the ~30 Clear Lake houses with a view: raised detection, stories."""
    f = load("C")
    rows = []
    for prov, path in (("Bee Maps", "beemaps_multi_reads_rect_qwen3vl4b.parquet"), ("Mapillary", "mapillary_multi_reads_qwen3vl4b.parquet")):
        p = D / "C" / path
        if not p.exists():
            continue
        rd = pd.read_parquet(p)
        rd = rd[rd.parse_ok & rd.house_visible.fillna(False)]
        rd["vote"] = (rd.foundation.isin(["raised_crawlspace", "piers_or_stilts"]) | rd.lower_level_enclosure_visible.fillna(False)
                      | (rd.door_threshold_height_above_ground_ft > 3)).astype(float)
        g = rd.groupby("oid").agg(vote=("vote", "mean"), img_stories=("living_stories", "median")).reset_index()
        t = g.merge(f, on="oid")
        r = t.dh > 3
        fl = t.vote >= 0.5
        st = t.dropna(subset=["img_stories", "stories"])
        rows.append({"images": prov, "houses": len(t), "raised": int(r.sum()), "image flags raised": int(fl.sum()),
                     "image precision": (fl & r).sum() / max(fl.sum(), 1), "image recall": (fl & r).sum() / max(r.sum(), 1),
                     "stories agree with record": (st.img_stories.round() == st.stories).mean()})
    return pd.DataFrame(rows)


def main():
    a = {k: load(k) for k in ("B", "C")}
    for k, f in a.items():
        f["block"] = (f.x // 1000).astype(int).astype(str) + "_" + (f.y // 1000).astype(int).astype(str)
        print(f"{k}: {len(f)} houses (tiers A+B), raised {int((f.dh > 3).sum())}, SFHA with BFE "
              f"{int(((f.zone == 'SFHA') & f.bfe.notna()).sum())}, answer key fails the screen {int((~f.key_ok).sum())}")
    for test, train, same in (("C", "C", True), ("B", "B", True), ("B", "C", False), ("C", "B", False)):
        f = a[test]
        preds = predictions(a[train], f, same)
        for lab, m in (("all", np.ones(len(f), bool)), ("screened", f.key_ok.values)):
            res = pd.DataFrame({k: metrics(p[m], f[m].reset_index(drop=True)) for k, p in preds.items()}).T
            where = f"{test}, 5-fold by 1 km block" if same else f"trained on {train}, scored on {test}"
            print(f"\n## {where} ({lab} houses)\n")
            print(res.round(3).to_markdown())
    print("\n## Image evidence, own model (Qwen3-VL-4B), Clear Lake houses with a usable view\n")
    print(image_component().round(2).to_markdown(index=False))


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    main()
