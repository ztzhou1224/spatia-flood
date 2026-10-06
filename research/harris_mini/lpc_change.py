"""Houses raised (or rebuilt) between two lidar flights: heights ABOVE EACH FLIGHT'S OWN GROUND, then the difference.

Per house (HCAD 2017 footprint) and per flight (data/harris_mini/<AREA>/lpc2018, lpc2024): ground = 10th pct of
ground returns (class 2) in a 0.5-2.5 m ring outside the footprint; ridge = 99th pct and roof = 50th pct of building
returns inside the footprint shrunk 0.3 m (all non-ground returns > 2 m above that ground: the 2024 flight has no
building class, so both flights use this rule); eave = median of those returns within 1 m of the edge. All as
metres above that flight's ground, so the vertical datum (GEOID12B vs GEOID18) and subsidence cancel. Both flights
must share the horizontal CRS (checked; EPSG:6344 expected). A whole-house lift raises ridge, roof and eave together;
a rebuild or an added story changes them unevenly or changes the return count.
Output: data/harris_mini/<AREA>/lpc_change.parquet (heights in ft).  Usage: python lpc_change.py AREA
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
FT = 3.28084  # international ft per m (heights are differences within one flight)


def epoch(area, sub, h, fps, rings, inner, rad, cx, cy):
    """Per-house ground / roof statistics from one flight."""
    buf = {i: [] for i in range(len(h))}
    crs = set()
    for path in sorted(glob.glob(str(D / area / sub / "*.laz"))):
        las = laspy.read(path)
        c = las.header.parse_crs()
        crs.add(str(c.to_epsg()) if c is not None and c.to_epsg() else (c.name if c is not None else "none"))
        cls = np.asarray(las.classification)
        keep = np.isin(cls, (1, 2, 3, 4, 5, 6))  # 2024 has no building class: buildings are in class 1
        x, y, z, cls = np.asarray(las.x)[keep], np.asarray(las.y)[keep], np.asarray(las.z)[keep], cls[keep]
        hit = np.where((cx + rad > x.min()) & (cx - rad < x.max()) & (cy + rad > y.min()) & (cy - rad < y.max()))[0]
        tree = cKDTree(np.c_[x, y])
        for i in hit:
            idx = np.asarray(tree.query_ball_point([cx[i], cy[i]], rad[i]), dtype=int)
            if idx.size:
                buf[i].append(np.c_[x[idx], y[idx], z[idx], cls[idx]])
        del las, x, y, z, cls, tree
    rows = []
    for i, parts in buf.items():
        rec = {"oid": h.oid[i]}
        if parts:
            a = np.vstack(parts)
            px, py, pz, pc = a[:, 0], a[:, 1], a[:, 2], a[:, 3].astype(int)
            g = shapely.contains_xy(rings[i], px, py) & (pc == 2)
            if g.sum() < 5:
                rows.append(rec)
                continue
            g0 = np.percentile(pz[g], 10)
            # same rule in both flights: non-ground returns inside the footprint more than 2 m above that flight's
            # ground (the 2024 flight classifies no buildings; trees over a roof add noise in both years)
            ins = shapely.contains_xy(inner[i], px, py) & (pc != 2) & (pz - g0 > 2.0)
            edge = ins & ~shapely.contains_xy(fps[i].buffer(-1.0), px, py)
            if ins.sum() >= 20:
                rec.update(ground=g0, ridge=(np.percentile(pz[ins], 99) - g0) * FT, roof=(np.median(pz[ins]) - g0) * FT,
                           eave=(np.median(pz[edge]) - g0) * FT if edge.sum() >= 5 else np.nan, n_bldg=int(ins.sum()),
                           bldg_m2=ins.sum() / max(inner[i].area, 1.0))
        rows.append(rec)
    return pd.DataFrame(rows), crs


def main(area):
    h = pd.read_parquet(D / area / "houses.parquet", columns=["oid", "loc", "fp_wkt", "e2018_lag"])
    h = h[(h["loc"] == "Front Door") & h.e2018_lag.notna()].reset_index(drop=True)
    fps = [swkt.loads(w) for w in h.fp_wkt]
    rings = [f.buffer(2.5).difference(f.buffer(0.5)) for f in fps]
    inner = [f.buffer(-0.3) for f in fps]
    rad = np.array([shapely.hausdorff_distance(f.centroid, f.exterior) + 3.0 for f in fps])
    cx, cy = np.array([f.centroid.x for f in fps]), np.array([f.centroid.y for f in fps])
    e = {}
    for yr in ("2018", "2024"):
        e[yr], crs = epoch(area, f"lpc{yr}", h, fps, rings, inner, rad, cx, cy)
        print(f"{area} {yr}: horizontal CRS of tiles {crs}; houses measured {e[yr].ridge.notna().sum()}", flush=True)
    m = e["2018"].merge(e["2024"], on="oid", suffixes=("_18", "_24"))
    for c in ("ridge", "roof", "eave"):
        m[f"d_{c}"] = m[f"{c}_24"] - m[f"{c}_18"]
    m["d_ground_m"] = m.ground_24 - m.ground_18  # datum + subsidence + regrading, for the record
    m.to_parquet(D / area / "lpc_change.parquet", index=False)
    ok = m.d_ridge.notna()
    print(f"houses with both flights {int(ok.sum())}; ground shift 2024 - 2018 median {m.d_ground_m.median():.3f} m; "
          f"ridge change median {m.d_ridge.median():.2f} ft, IQR {m.d_ridge.quantile(.25):.2f} to {m.d_ridge.quantile(.75):.2f}")
    for t in (2, 3, 5, 8):
        lift = ok & (m.d_ridge > t) & (m.d_roof > t) & (m.d_eave > t)
        print(f"ridge, roof and eave all up > {t} ft: {int(lift.sum())} houses")


if __name__ == "__main__":
    main(sys.argv[1])
