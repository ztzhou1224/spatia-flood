"""Main eave from fitted roof planes (point cloud), instead of a height histogram of the footprint edge.

Input: roof_points.parquet (lpc_features.py: building returns inside each footprint; x, y EPSG:6344 m, hz ft above
the DEM lowest adjacent grade). Per house, sequential RANSAC: up to 6 planes hz = a x + b y + c, inliers within
0.5 ft, each plane >= max(30 returns, 8% of the house's returns), least-squares refit on its inliers.
  ridge          99th pct of all building returns
  main planes    planes that reach within 1.5 ft of the ridge (their 95th pct) and hold >= 10% of the returns:
                 the top roof; a first-floor porch or garage roof never reaches the ridge
  eave_plane     lowest edge of the main planes (5th pct of their returns)
  n_planes, main_share, roof_rise = ridge - eave_plane
Evaluation (as eval_transfer.py, label-free): est_plane = eave_plane - typical eave_plane of slab houses without a
lower level for the same story count + 1 ft; median absolute / signed error on raised houses passing the answer-key
screen, per story count, next to the p50 / main / split estimates; both areas.
Output: data/harris_mini/<AREA>/roof_planes.parquet.  Usage: python roof_planes.py B C
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from eval_stories import SLAB_FT  # noqa: E402
from eval_transfer import load  # noqa: E402

D = HERE.parents[1] / "data" / "harris_mini"
TOL, MAXP, ITERS = 0.5, 6, 200


def planes(x, y, z, rng):
    n = len(z)
    if n < 30:
        return []
    minpts = max(30, int(0.08 * n))
    A = np.c_[x - x.mean(), y - y.mean(), np.ones(n)]
    left = np.ones(n, bool)
    out = []
    while left.sum() >= minpts and len(out) < MAXP:
        idx = np.where(left)[0]
        best = None
        for _ in range(ITERS):
            s = rng.choice(idx, 3, replace=False)
            try:
                coef = np.linalg.solve(A[s], z[s])
            except np.linalg.LinAlgError:
                continue
            inl = left & (np.abs(A @ coef - z) < TOL)
            if best is None or inl.sum() > best.sum():
                best = inl
        if best is None or best.sum() < minpts:
            break
        coef, *_ = np.linalg.lstsq(A[best], z[best], rcond=None)
        inl = left & (np.abs(A @ coef - z) < TOL)
        if inl.sum() < minpts:
            break
        zi = z[inl]
        out.append({"n": int(inl.sum()), "p05": np.percentile(zi, 5), "p95": np.percentile(zi, 95),
                    "slope": float(np.hypot(coef[0], coef[1]))})
        left &= ~inl
    return out


def house_features(g, rng):
    x, y, z = g.x.values, g.y.values, g.hz.values.astype(float)
    pl = planes(x, y, z, rng)
    if not pl:
        return {"n_planes": 0, "ridge": np.nan, "eave_plane": np.nan, "main_share": np.nan, "roof_rise": np.nan}
    ridge = np.percentile(z, 99)
    main = [p for p in pl if p["p95"] >= ridge - 1.5 and p["n"] >= 0.10 * len(z)]
    eave = min(p["p05"] for p in main) if main else np.nan
    return {"n_planes": len(pl), "ridge": ridge, "eave_plane": eave,
            "main_share": sum(p["n"] for p in main) / len(z) if main else 0.0, "roof_rise": ridge - eave}


def main(areas):
    rng = np.random.default_rng(20261006)
    for area in areas:
        pts = pd.read_parquet(D / area / "roof_points.parquet")
        feats = pd.DataFrame([{"oid": oid, **house_features(g, rng)} for oid, g in pts.groupby("oid", sort=False)])
        feats.to_parquet(D / area / "roof_planes.parquet", index=False)
        f = load(area).merge(feats, on="oid", how="left")
        ref = f[(f.foundation == "Slab") & (f.has_lower == 0)]
        typ = ref.groupby("stories").eave_plane.median()
        f["est_plane"] = f.eave_plane - f.stories.map(typ) + SLAB_FT
        print(f"\n{area}: {len(feats)} houses with roof points; planes per house median {feats.n_planes.median():.0f}; "
              f"eave_plane found {feats.eave_plane.notna().mean():.1%}; typical eave_plane of slab houses by stories "
              f"{typ.round(2).to_dict()} (eave p50 / main gave {ref.groupby('stories').eave_p50.median().round(2).to_dict()} / "
              f"{ref.groupby('stories').eave_main.median().round(2).to_dict()})")
        r = f[(f.dh > 3) & f.key_ok]
        rows = {}
        for e in ("est_eave_p50", "est_eave_main", "est_split", "est_plane"):
            err = r[e] - r.dh
            for st in (1, 2):
                m = r.stories == st
                rows[(e, f"{st}-story")] = {"n": int(err[m].notna().sum()), "median_abs": err[m].abs().median(),
                                             "median_signed": err[m].median(), "MAE": err[m].abs().mean()}
        print(f"raised houses passing the screen ({area}):\n")
        print(pd.DataFrame(rows).T.round(2).to_markdown())
        allh = f[f.key_ok]
        print(f"\nall screened houses ({area}): MAE est_split {(allh.est_split - allh.dh).abs().mean():.2f}, "
              f"est_plane {(allh.est_plane - allh.dh).abs().mean():.2f} ft")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main(sys.argv[1:])
