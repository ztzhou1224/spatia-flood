"""Per-house observations from the 3DEP lidar POINT CLOUD (not the DEM): what the 2018 flight saw of each house.

Input: USGS LPC TX_CoastalRegion_2018_A18 tiles (EPSG:6344 UTM 15N m, NAVD88 GEOID12B m) in
data/harris_mini/<AREA>/lpc2018/ (URLs from the TNM API, urls.txt); the house list and HCAD 2017 footprints
from houses.parquet (only oid, footprint and the DEM lowest adjacent grade e2018_lag are read; never the
answer key). Classes 7, 9, 10, 14, 17, 18 dropped (noise, water, rail, wire, bridge). Buildings are class 6. Heights are ft above e2018_lag (US survey ft, as ground.py).
Per house:
  n_in, pts_m2          returns inside the footprint (shrunk 0.3 m) and their density
  bldg_share            share of those returns classed building
  roof_p05/p50/p95      height of building returns inside the footprint
  eave_p10/p50          building returns within 1 m inside the footprint edge (eave line)
  eave_main             highest dominant height cluster of those edge returns (main roof eave, see main_eave)
  ridge                 99th pct height of building returns
  ground_in_share       share of returns inside the footprint (shrunk 1 m) classed ground: open space under the
                        house seen between the floor beams / at the edges
  ring_low_share        returns 0-3 m outside the footprint, classed building or unclassified (not vegetation), that
                        sit 2-10 ft above ground (stairs, decks, porches), as a share of all ring returns
  ring_low_p90          90th pct height of those low ring returns
Output: data/harris_mini/<AREA>/lpc_features.parquet, and roof_points.parquet (building returns inside each
footprint: x, y in EPSG:6344 m, hz ft above the lowest adjacent grade) for roof_planes.py.  Usage: python lpc_features.py AREA

Options (python lpc_features.py AREA FLIGHT RULE; defaults 2018 class6 = the outputs above):
  FLIGHT 2024   TX_Houston_B24 tiles in <AREA>/lpc2024 (NAD83(2011) UTM 15N, NAVD88 GEOID18). Heights stay relative
                to e2018_lag, minus the area's median ground shift 2024 - 2018 from lpc_change.parquet (rings outside
                each footprint; A 0.000 m, C -0.010 m), so GEOID18 vs GEOID12B and subsidence are removed per area.
  RULE single   "building" = non-ground single returns (number_of_returns == 1) at least 5 ft above the lowest
                adjacent grade, instead of class 6. The 2024 flight has no building class (classes 1, 2, 7, 18 only);
                in 2018, 95% of class-6 returns are single returns vs 8-12% of medium / tall vegetation (one C tile).
                ring_low then uses all non-ground classes.
  Output names gain _<FLIGHT>_<RULE> unless both are the defaults.
Units: tiles whose CRS is in US survey feet (Florida area P: NAD83(2011) / Florida West ftUS + NAVD88 US ft) are
scaled to metres on read, so footprints must be in the metric twin of that CRS (P: EPSG:6442; fl_build.py).
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
USFT = 1200 / 3937  # m per US survey foot
DROP = (7, 9, 10, 14, 17, 18)  # noise, water, rail, wire conductor, bridge deck, high noise


def main_eave(v, bin_ft=0.5, share=0.15):
    """Highest dominant height cluster of edge returns: the eave of the main (top) roof, not porch / garage roofs.

    0.5 ft histogram smoothed with a [1 2 3 2 1] kernel; peaks = local maxima holding >= `share` of the returns
    within +-1 ft; the highest peak wins; the value is the median of the returns within 1 ft of it."""
    if v.size < 20:
        return np.nan
    edges = np.arange(np.floor(v.min()) - 1, np.ceil(v.max()) + 1 + bin_ft, bin_ft)
    cnt, _ = np.histogram(v, edges)
    sm = np.convolve(cnt, [1, 2, 3, 2, 1], mode="same")
    mass = np.convolve(cnt, np.ones(5, dtype=int), mode="same")  # +-1 ft
    peak = np.r_[False, (sm[1:-1] >= sm[:-2]) & (sm[1:-1] > sm[2:]), False] & (mass >= share * v.size)
    if not peak.any():
        return np.nan
    i = np.where(peak)[0][-1]
    c = (edges[i] + edges[i + 1]) / 2
    return float(np.median(v[np.abs(v - c) <= 1.0]))


def main(area, flight="2018", rule="class6"):
    tag = "" if (flight, rule) == ("2018", "class6") else f"_{flight}_{rule}"
    h = pd.read_parquet(D / area / "houses.parquet", columns=["oid", "loc", "x", "y", "fp_wkt", "e2018_lag"])
    h = h[(h["loc"] == "Front Door") & h.e2018_lag.notna()].reset_index(drop=True)
    fps = [swkt.loads(w) for w in h.fp_wkt]
    inner03 = [f.buffer(-0.3) for f in fps]
    inner1 = [f.buffer(-1.0) for f in fps]
    ring3 = [f.buffer(3.0).difference(f) for f in fps]
    rad = np.array([shapely.hausdorff_distance(f.centroid, f.exterior) + 3.5 for f in fps])
    cx = np.array([f.centroid.x for f in fps])
    cy = np.array([f.centroid.y for f in fps])
    lag_m = h.e2018_lag.values * USFT
    if flight != "2018":  # datum + subsidence: area median ground shift measured by lpc_change.py
        shift = float(pd.read_parquet(D / area / "lpc_change.parquet").d_ground_m.median())
        lag_m = lag_m + shift
        print(f"{area} {flight}: ground shift vs 2018 applied {shift:+.3f} m", flush=True)
    buf = {i: [] for i in range(len(h))}  # points of each house's search disc, gathered across tile edges
    for path in sorted(glob.glob(str(D / area / f"lpc{flight}" / "*.laz"))):
        las = laspy.read(path)
        c = las.header.parse_crs()
        # tiles in US survey feet (e.g. Florida State Plane ftUS): x, y, z to metres, i.e. the metric twin of the CRS
        sc = USFT if c is not None and c.axis_info and "foot" in c.axis_info[0].unit_name.lower() else 1.0
        cls = np.asarray(las.classification)
        keep = ~np.isin(cls, DROP)
        # single returns carried in the class column as 100 + class (no other code reads it)
        cls = np.where(np.asarray(las.number_of_returns) == 1, cls + 100, cls)[keep]
        x, y, z = np.asarray(las.x)[keep] * sc, np.asarray(las.y)[keep] * sc, np.asarray(las.z)[keep] * sc
        hit = np.where((cx + rad > x.min()) & (cx - rad < x.max()) & (cy + rad > y.min()) & (cy - rad < y.max()))[0]
        tree = cKDTree(np.c_[x, y])
        for i in hit:
            idx = np.asarray(tree.query_ball_point([cx[i], cy[i]], rad[i]), dtype=int)
            if idx.size:
                buf[i].append(np.c_[x[idx], y[idx], z[idx], cls[idx]])
        print(Path(path).name, "houses touched", len(hit), flush=True)
        del las, x, y, z, cls, tree
    rows, roof_pts = {}, []
    for i, parts in buf.items():
        if not parts:
            continue
        a_ = np.vstack(parts)  # overlapping tiles hold different returns (none identical), so keep all
        px, py, pz, pc1 = a_[:, 0], a_[:, 1], a_[:, 2], a_[:, 3].astype(int)
        single, pc = pc1 >= 100, pc1 % 100
        hz = (pz - lag_m[i]) / USFT  # ft above the lowest adjacent grade
        ins = shapely.contains_xy(inner03[i], px, py)
        if rule == "class6":
            ng = ins & (pc == 6)  # building returns (vegetation 3-5 over the roof excluded)
        else:
            ng = ins & (pc != 2) & single & (hz >= 5)
        core = shapely.contains_xy(inner1[i], px, py) if not inner1[i].is_empty else ins
        edge = ng & ~core
        ring = shapely.contains_xy(ring3[i], px, py)
        low = ring & (np.isin(pc, (1, 6)) if rule == "class6" else (pc != 2)) & (hz >= 2) & (hz <= 10)  # structures

        roof_pts.append(pd.DataFrame({"oid": h.oid[i], "x": px[ng], "y": py[ng], "hz": hz[ng].astype("float32")}))

        def q(v, p):
            return float(np.percentile(v, p)) if v.size >= 5 else np.nan
        rows[h.oid[i]] = dict(
            n_in=int(ins.sum()), pts_m2=float(ins.sum() / max(inner03[i].area, 1.0)),
            bldg_share=float(ng.sum() / max(ins.sum(), 1)),
            roof_p05=q(hz[ng], 5), roof_p50=q(hz[ng], 50), roof_p95=q(hz[ng], 95),
            eave_p10=q(hz[edge], 10), eave_p50=q(hz[edge], 50), eave_main=main_eave(hz[edge]),
            ridge=q(hz[ng], 99),
            ground_in_share=float((core & (pc == 2)).sum() / max(core.sum(), 1)),
            ring_low_share=float(low.sum() / max(ring.sum(), 1)), ring_low_p90=q(hz[low], 90))
    out = pd.DataFrame.from_dict(rows, orient="index").rename_axis("oid").reset_index()
    pd.concat(roof_pts, ignore_index=True).to_parquet(D / area / f"roof_points{tag}.parquet", index=False)  # roof_planes.py
    out.to_parquet(D / area / f"lpc_features{tag}.parquet", index=False)
    print(f"{area} {flight} {rule}: {len(out)} of {len(h)} houses; roof seen (>= 5 returns) {out.roof_p50.notna().mean():.0%}")
    print(out.describe().T[["count", "50%", "mean"]].round(2).to_markdown())


if __name__ == "__main__":
    main(*sys.argv[1:4])
