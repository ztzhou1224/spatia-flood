"""Floor-level surfaces seen by the lidar just outside the house: decks, landings, porches (evidence for raised houses).

A raised house is usually entered from a landing or deck at floor level. Per house (houses.parquet footprint; tiles in
<AREA>/lpc2018; US-survey-foot tiles scaled to metres as lpc_features.py):
  points    single returns of building (6) or unclassified (1) points in a ring 0.3-4 m outside the footprint
            (single returns keep most vegetation out; classes 3-5, ground and noise excluded)
  cells     1 m x 1 m cells with >= 4 such points whose heights span <= 0.4 ft: flat surfaces; height = cell median,
            ft above the DEM lowest adjacent grade (e2018_lag)
  deck_h    the lowest height cluster (0.5 ft bins, +- 0.5 ft) holding >= 3 flat cells between 2.5 and 16 ft
  deck_n    flat cells in that cluster; flat_n: all flat cells 2.5-16 ft (0 when none)
Never reads the answer key. Output: data/harris_mini/<AREA>/lpc_ring.parquet.  Usage: python lpc_ring.py AREA
"""
import glob
import sys
from pathlib import Path

import laspy
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree
from shapely import wkt as swkt

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
USFT = 1200 / 3937
LO, HI, FLAT, MINPTS = 2.5, 16.0, 0.4, 4


def deck(px, py, hz):
    if len(hz) < MINPTS:
        return {"deck_h": np.nan, "deck_n": 0, "flat_n": 0}
    cx, cy = np.floor(px).astype(np.int64), np.floor(py).astype(np.int64)
    key = (cx - cx.min()) * 100000 + (cy - cy.min())
    df = pd.DataFrame({"k": key, "z": hz})
    g = df.groupby("k").z.agg(["size", "min", "max", "median"])
    flat = g[(g["size"] >= MINPTS) & (g["max"] - g["min"] <= FLAT) & g["median"].between(LO, HI)]["median"].values
    if len(flat) < 3:
        return {"deck_h": np.nan, "deck_n": 0, "flat_n": len(flat)}
    for b in np.arange(LO, HI, 0.5):  # lowest cluster first
        m = np.abs(flat - (b + 0.25)) <= 0.5
        if m.sum() >= 3:
            return {"deck_h": float(np.median(flat[m])), "deck_n": int(m.sum()), "flat_n": len(flat)}
    return {"deck_h": np.nan, "deck_n": 0, "flat_n": len(flat)}


def main(area):
    h = pd.read_parquet(D / area / "houses.parquet", columns=["oid", "loc", "fp_wkt", "e2018_lag"])
    h = h[(h["loc"] == "Front Door") & h.e2018_lag.notna()].reset_index(drop=True)
    fps = [swkt.loads(w) for w in h.fp_wkt]
    ring = [f.buffer(4.0).difference(f.buffer(0.3)) for f in fps]
    rad = np.array([shapely.hausdorff_distance(f.centroid, f.exterior) + 4.5 for f in fps])
    cx, cy = np.array([f.centroid.x for f in fps]), np.array([f.centroid.y for f in fps])
    lag_m = h.e2018_lag.values * USFT
    buf = {i: [] for i in range(len(h))}
    for path in sorted(glob.glob(str(D / area / "lpc2018" / "*.laz"))):
        las = laspy.read(path)
        c = las.header.parse_crs()
        sc = USFT if c is not None and c.axis_info and "foot" in c.axis_info[0].unit_name.lower() else 1.0
        cls = np.asarray(las.classification)
        keep = np.isin(cls, (1, 6)) & (np.asarray(las.number_of_returns) == 1)
        x, y, z = np.asarray(las.x)[keep] * sc, np.asarray(las.y)[keep] * sc, np.asarray(las.z)[keep] * sc
        hit = np.where((cx + rad > x.min()) & (cx - rad < x.max()) & (cy + rad > y.min()) & (cy - rad < y.max()))[0]
        tree = cKDTree(np.c_[x, y])
        for i in hit:
            idx = np.asarray(tree.query_ball_point([cx[i], cy[i]], rad[i]), dtype=int)
            if idx.size:
                buf[i].append(np.c_[x[idx], y[idx], z[idx]])
        print(Path(path).name, "houses touched", len(hit), flush=True)
        del las, x, y, z, tree
    rows = []
    for i, parts in buf.items():
        rec = {"oid": h.oid[i]}
        if parts:
            a = np.vstack(parts)
            m = shapely.contains_xy(ring[i], a[:, 0], a[:, 1])
            rec.update(deck(a[m, 0], a[m, 1], (a[m, 2] - lag_m[i]) / USFT))
        rows.append(rec)
    out = pd.DataFrame(rows)
    out.to_parquet(D / area / "lpc_ring.parquet", index=False)
    print(f"{area}: {len(out)} houses; deck found {out.deck_h.notna().mean():.1%}; deck_h median {out.deck_h.median():.2f} ft")


if __name__ == "__main__":
    main(sys.argv[1])
