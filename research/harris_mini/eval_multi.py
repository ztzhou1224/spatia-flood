"""Score the Bee Maps multi-frame readings (vlm_multi.py) against the answer key, next to the lidar + records model.

Per house (frames where the VLM saw the house): views, frames with the door visible, median door height over frames
that give one, raised vote = share of frames reporting piers / crawlspace, a lower enclosure, or a door > 3 ft,
median living stories. Compared on the same houses (rules fixed before scoring; answer key = scorer only):
  model                 out-of-fold prediction of the full lidar + records model (triage.parquet)
  image                 lidar ground + median VLM door height
  image, else model     image where the VLM gave a door height, else the model
  mean of both          average of image and model where both exist
Raised detection (door > 3 ft): model > 3 ft vs raised vote >= 0.5. Stories: VLM vs HCAD record.
The answer-key screen of eval_stories.py (door within 6 ft of the roof top, or > 1 ft below grade) is reported.
Usage: python eval_multi.py AREA [READS_TAG]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"


def mae(e):
    e = np.abs(e.dropna())
    return pd.Series({"n": len(e), "MAE": e.mean(), "within_1": (e <= 1).mean()})


def main(area, tag=""):
    rd = pd.read_parquet(D / area / f"beemaps_multi_reads{'_' + tag if tag else ''}.parquet")
    rd = rd[rd.parse_ok & rd.house_visible.fillna(False)].copy()
    h_ok = rd.front_door_visible.fillna(False) & rd.door_threshold_height_above_ground_ft.notna()
    rd["h"] = rd.door_threshold_height_above_ground_ft.where(h_ok)
    rd["raised_vote"] = (rd.foundation.isin(["raised_crawlspace", "piers_or_stilts"])
                         | rd.lower_level_enclosure_visible.fillna(False) | (rd.h > 3)).astype(float)
    g = rd.groupby("oid").agg(views=("sequence", "size"), door_views=("h", "count"), img_h=("h", "median"),
                              img_h_spread=("h", lambda v: v.max() - v.min() if v.notna().sum() > 1 else np.nan),
                              raised_share=("raised_vote", "mean"), img_stories=("living_stories", "median"))
    v = pd.read_parquet(D / area / "beemaps_multi.parquet")
    tried = v.drop_duplicates("oid")[["oid", "group"]]
    tri = pd.read_parquet(D / area / "triage.parquet")
    f = pd.read_parquet(D / area / "coverage_features.parquet")[["oid", "prec", "ffe", "e2018_lag"]]
    lpc = pd.read_parquet(D / area / "lpc_features.parquet")[["oid", "roof_p95"]]
    t = tried.merge(tri, on="oid").merge(f, on="oid").merge(lpc, on="oid", how="left").merge(g, on="oid", how="left")
    t = t[t.prec <= 6].copy()
    t["dh"] = t.ffe - t.e2018_lag  # scorer only
    t["key_ok"] = ~((t.roof_p95 - t.dh < 6) | (t.dh < -1))
    t["seen"] = t.views.notna()
    print(f"{area}: houses tried {len(t)} {t.groupby('group').size().to_dict()}; house seen in >= 1 frame "
          f"{t.groupby('group').seen.mean().round(3).to_dict()}; door height read "
          f"{t.groupby('group').img_h.apply(lambda s: s.notna().mean()).round(3).to_dict()}; raised (door > 3 ft) "
          f"{t.groupby('group').dh.apply(lambda s: int((s > 3).sum())).to_dict()}")
    s = t[t.seen]
    print(f"seen houses: views per house median {s.views.median():.0f}, max {s.views.max():.0f}; door views median "
          f"{s.door_views.median():.0f}; spread of door-height reads across frames (houses with >= 2): median "
          f"{s.img_h_spread.median():.2f} ft")
    s = s.assign(img=s.img_h, img_else_model=s.img_h.fillna(s.pred), mean_both=(s.img_h + s.pred) / 2)
    for nm, m in (("all", s.index == s.index), ("answer key passes the screen", s.key_ok)):
        x = s[m]
        rows = {}
        for sub, mm in (("houses with an image door height", x.img_h.notna()), ("raised among them", x.img_h.notna() & (x.dh > 3)),
                        ("all seen houses", x.index == x.index), ("raised seen houses", x.dh > 3)):
            for meth in ("pred", "img", "img_else_model", "mean_both"):
                rows[(sub, meth)] = mae(x.loc[mm, meth] - x.loc[mm, "dh"])
        print(f"\n## Door height above ground (ft), {nm}\n")
        print(pd.DataFrame(rows).T.round(3).to_markdown())
    x = s[s.raised_share.notna()]
    out = {}
    for nm, flag in (("model > 3 ft", x.pred > 3), ("image raised vote >= 0.5", x.raised_share >= 0.5),
                     ("either", (x.pred > 3) | (x.raised_share >= 0.5)), ("both", (x.pred > 3) & (x.raised_share >= 0.5))):
        r = x.dh > 3
        out[nm] = {"flagged": int(flag.sum()), "precision": (flag & r).sum() / max(flag.sum(), 1),
                   "recall": (flag & r).sum() / max(r.sum(), 1)}
    print(f"\n## Raised detection on seen houses (n {len(x)}, raised {int((x.dh > 3).sum())})\n")
    print(pd.DataFrame(out).T.round(3).to_markdown())
    y = s[s.img_stories.notna() & s.stories.notna()]
    print(f"\nstories, image vs appraisal record (n {len(y)}): agree {(y.img_stories.round() == y.stories).mean():.0%}; "
          f"crosstab {pd.crosstab(y.stories, y.img_stories.round()).to_dict()}")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main(*sys.argv[1:3])
