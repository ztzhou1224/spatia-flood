"""Score the Mapillary + VLM front-door reading against the HCFCD answer key, beside lidar + neighbours.

Reuses evaluate.py's design: a random 10% of houses (seed 0, drawn per area) play "has a certificate";
neighbour features come only from that pool, never the house itself; models train on pool houses in
other 1 km blocks (5 group folds) and are scored on non-pool houses. Here scoring is restricted to the
random image sample (mapillary_views.py) minus pool houses. The answer key (ffe) is read only as the
target, as pool neighbour labels, and by the scorer.

Per house, the image reading is the highest-confidence view that saw the door and gave a height; if
none did, the foundation comes from the highest-confidence view that saw the house.
Usage: python eval_image.py AREA [AREA ...]
"""
import sys
import numpy as np, pandas as pd, lightgbm as lgb
from sklearn.model_selection import GroupKFold
from evaluate import BASE, GROUND, P, D, load, nb_feats

RAISED = {"raised_crawlspace", "piers_or_stilts"}
DENSITY = 0.10


def house_reads(area: str) -> pd.DataFrame:
    v = pd.read_parquet(D / area / "views.parquet")
    r = pd.read_parquet(D / area / "vlm_reads.parquet").merge(
        v[["oid", "image_id", "captured", "is_pano", "dist_m"]], on=["oid", "image_id"])
    r = r[r.parse_ok]
    r["has_h"] = r.front_door_visible & r.house_visible & r.door_threshold_height_above_ground_ft.notna()
    out = []
    for oid, g in r.groupby("oid"):
        g = g.sort_values("confidence", ascending=False)
        gh, gv = g[g.has_h], g[g.house_visible]
        best = gh.iloc[0] if len(gh) else (gv.iloc[0] if len(gv) else None)
        row = dict(oid=oid, n_views=len(g), any_visible=bool(g.house_visible.any()),
                   any_door=bool((g.house_visible & g.front_door_visible).any()), any_h=len(gh) > 0)
        if best is not None:
            row.update(vlm_h=best.door_threshold_height_above_ground_ft if len(gh) else np.nan,
                       vlm_steps=best.steps_to_door if len(gh) else np.nan,
                       vlm_found=best.foundation, vlm_encl=bool(best.lower_level_enclosure_visible),
                       vlm_conf=best.confidence, vlm_image=best.image_id, vlm_captured=best.captured,
                       vlm_pano=best.is_pano, vlm_notes=best.notes)
        out.append(row)
    return pd.DataFrame(out)


def run(h: pd.DataFrame, rd: pd.DataFrame):
    rng = np.random.default_rng(0)
    pool = pd.Series(rng.random(len(h)) < DENSITY, index=h.index)
    nb = nb_feats(h[pool], h)
    hv = h.merge(rd, on="oid", how="left").set_index(h.index)
    img = pd.DataFrame(index=h.index)
    img["vlm_h"] = hv.vlm_h
    img["vlm_steps"] = pd.to_numeric(hv.vlm_steps, errors="coerce")
    img["vlm_raised"] = hv.vlm_found.map(lambda f: np.nan if not isinstance(f, str) or f == "unknown"
                                         else float(f in RAISED))
    names = ["G1 lidar LAG + neighbour height", "GBM + lidar ground", "Direct: lidar LAG + VLM height",
             "Direct, fallback GBM + lidar", "GBM + lidar + VLM features",
             "GBM + lidar + VLM, fallback GBM + lidar", "GBM + lidar, VLM override only if VLM says raised"]
    pred = {k: pd.Series(np.nan, index=h.index) for k in names}
    Xb = lambda d: pd.concat([d[BASE + GROUND], nb.loc[d.index, ["nb_ffh_med", "nb_ffh_idw", "nb_ffh_std", "nb_n", "nb_dist"]]], axis=1)
    ntrain_img = []
    for tr_i, te_i in GroupKFold(5).split(h, groups=h.block):
        tr, te = h.iloc[tr_i], h.iloc[te_i]
        tr, te = tr[pool[tr.index]], te[~pool[te.index]]
        gffh = tr.ffh.median()
        n = nb.loc[te.index]
        pred[names[0]][te.index] = te.e2018_lag + n.nb_ffh_med.fillna(gffh)
        m = lgb.LGBMRegressor(**P).fit(Xb(tr), tr.ffh)
        g = te.e2018_lag + m.predict(Xb(te))
        pred[names[1]][te.index] = g
        direct = te.e2018_lag + img.vlm_h[te.index]
        pred[names[2]][te.index] = direct
        pred[names[3]][te.index] = direct.fillna(g)
        m2 = lgb.LGBMRegressor(**P).fit(Xb(tr).join(img.loc[tr.index]), tr.ffh)
        ntrain_img.append(int(img.vlm_h[tr.index].notna().sum()))
        gi = te.e2018_lag + m2.predict(Xb(te).join(img.loc[te.index]))
        has = img.vlm_h[te.index].notna() | img.vlm_raised[te.index].notna()
        pred[names[4]][te.index] = gi.where(has)
        pred[names[5]][te.index] = gi.where(has, g)
        says_raised = (img.vlm_h[te.index] > 3) | (img.vlm_raised[te.index] == 1)
        pred[names[6]][te.index] = g.where(~(says_raised & img.vlm_h[te.index].notna()), direct)
    return pred, pool, img, hv, ntrain_img


def score(h, pred, mask):
    rows = []
    for k, p in pred.items():
        e = (p - h.ffe)[mask].dropna()
        rows.append(dict(method=k, n=len(e), MAE=e.abs().mean(), within_05=(e.abs() <= 0.5).mean(),
                         within_1=(e.abs() <= 1).mean(), p90=e.abs().quantile(0.9), bias=e.mean()))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    allerr = []
    for area in sys.argv[1:]:
        h = load(area)
        sample = set(pd.read_csv(D / area / "image_sample.csv").oid)
        rd = house_reads(area)
        pred, pool, img, hv, ntr = run(h, rd)
        s = h.oid.isin(sample)
        print(f"\n## Area {area}: {int(s.sum())} sampled houses ({int((s & pool).sum())} in the 10% pool, "
              f"scored {int((s & ~pool).sum())}); training rows with a VLM height per fold: {ntr}")
        n = int(s.sum()); hs = hv[s]
        print(f"coverage of all {n} sampled: >=1 view {int(hs.n_views.notna().sum())} "
              f"({hs.n_views.notna().mean():.1%}); house visible {int(hs.any_visible.fillna(False).sum())} "
              f"({hs.any_visible.fillna(False).mean():.1%}); door visible {int(hs.any_door.fillna(False).sum())} "
              f"({hs.any_door.fillna(False).mean():.1%}); height read {int(hs.any_h.fillna(False).sum())} "
              f"({hs.any_h.fillna(False).mean():.1%})")
        raised = h.ffh > 3
        print(f"raised (front door > 3 ft above LAG) among sampled: {int((s & raised).sum())}")
        mask = s & ~pool
        for lab, mk in (("all scored sampled houses", mask),
                        ("scored houses WITH a VLM height", mask & img.vlm_h.notna()),
                        ("scored houses, true door > 3 ft above LAG", mask & raised),
                        ("... of which with a VLM height", mask & raised & img.vlm_h.notna())):
            print(f"\n### {area}: {lab}")
            print(score(h, pred, mk).round(3).to_markdown(index=False))
        # raised detection on sampled houses with a visible-house reading
        vis = s & hv.any_visible.fillna(False).astype(bool)
        pr = (hv.vlm_found.isin(RAISED) | (hv.vlm_h > 3)) & vis
        tp, fp, fn = int((pr & raised).sum()), int((pr & ~raised).sum()), int((vis & raised & ~pr).sum())
        print(f"\n### {area}: raised detection (house visible in >=1 view, n={int(vis.sum())}, true raised {int((vis & raised).sum())})")
        print(f"TP {tp} FP {fp} FN {fn}; precision {tp / max(tp + fp, 1):.2f}; recall {tp / max(tp + fn, 1):.2f}; "
              f"recall vs all sampled raised {tp / max(int((s & raised).sum()), 1):.2f}")
        e = (img.vlm_h - h.ffh)[s].dropna()
        allerr.append(pd.DataFrame(dict(area=area, oid=h.oid[e.index], err=e, ffh=h.ffh[e.index],
                                        vlm_h=img.vlm_h[e.index], image=hv.vlm_image[e.index],
                                        captured=hv.vlm_captured[e.index], pano=hv.vlm_pano[e.index],
                                        found=hv.vlm_found[e.index], conf=hv.vlm_conf[e.index],
                                        notes=hv.vlm_notes[e.index],
                                        truth_rec=pd.to_datetime(h.rec[e.index], unit="ms", utc=True))))
    E = pd.concat(allerr)
    rng = np.random.default_rng(0)
    print("\n## VLM height error (VLM height - true FFE + LAG), all sampled houses with a height")
    for lab, g in [("all", E)] + list(E.groupby("area")) + [("true > 3 ft", E[E.ffh > 3]), ("true <= 3 ft", E[E.ffh <= 3])]:
        print(f"{lab}: n {len(g)}, MAE {g.err.abs().mean():.2f}, bias {g.err.mean():+.2f}, SD {g.err.std():.2f}, "
              f"median abs {g.err.abs().median():.2f}, within 1 ft {(g.err.abs() <= 1).mean():.0%}")
    for sg in (0.72, 1.5):
        z = rng.normal(0, sg, 200_000)
        print(f"simulated sigma {sg}: MAE {np.abs(z).mean():.2f}, within 1 ft {(np.abs(z) <= 1).mean():.0%}")
    E["age_years"] = (E.captured - E.truth_rec).dt.days / 365.25
    print("image capture minus answer-key capture (years), quartiles:", E.age_years.quantile([.25, .5, .75]).round(1).tolist())
    print("MAE by image capture year:", E.groupby(E.captured.dt.year).err.agg(lambda x: f"{x.abs().mean():.2f} (n {len(x)})").to_dict())
    print("MAE pano vs perspective:", E.groupby("pano").err.agg(lambda x: f"{x.abs().mean():.2f} (n {len(x)})").to_dict())
    print("\n## 10 worst VLM heights")
    w = E.reindex(E.err.abs().sort_values(ascending=False).index).head(10)
    w["captured"] = w.captured.dt.date
    print(w[["area", "image", "captured", "pano", "ffh", "vlm_h", "err", "found", "conf", "notes"]].round(2).to_markdown(index=False))
    E.drop(columns=["notes"]).to_csv(D / "vlm_height_errors.csv", index=False)
