"""Per-building lidar features, the same definitions as the research scripts that method E was trained on.

Ground (research/harris_mini/ground.py, fl_build.py): USGS 1 m DEM, ft NAVD88 (metres / US survey foot):
  lag = min in a 0.5-2.5 m ring outside the footprint (lowest adjacent grade), p10 / med / hag = 10th pct / median /
  max of that ring, inside = median under the footprint, far = median 10-30 m away.
  Masked before any statistic (r1 plan docs/09 C1, review G1 / DA2): cells below WATER_FLOOR_FT ft NAVD88 and cells
  equal to the tile's hydro-flattened water constant (job.water_constants: a tile's most frequent value, when it is
  below 0). ring_n / ring_n_masked count the ring's cells before masking and how many were masked; lag_unmasked is
  the r0 definition (ring minimum with nothing masked), kept for comparison.
Point cloud (research/harris_mini/lpc_features.py, default flight, class-6 rule): heights in ft above lag; classes
7, 9, 10, 14, 17, 18 dropped; returns in a disc around the footprint centroid (Hausdorff radius + 3.5 m).
Units: point-cloud coordinates in US survey feet are scaled to metres by the caller (metric twin CRS).
"""

from __future__ import annotations

import numpy as np
import shapely
from rasterio.features import geometry_mask
from shapely.geometry import mapping

USFT = 1200 / 3937  # m per US survey foot
WATER_FLOOR_FT = -1.5  # ring cells below this (ft NAVD88) are water / seawall toe, never grade (docs/09 C1)
WATER_TOL_M = 1e-4  # a cell within this of the tile's water constant is the flattened water surface
DROP = (7, 9, 10, 14, 17, 18)  # noise, water, rail, wire conductor, bridge deck, high noise
GROUND_COLS = ["lag", "p10", "med", "hag", "inside", "far", "ring_n", "ring_n_masked", "lag_unmasked"]
LPC_COLS = [
    "n_in",
    "pts_m2",
    "bldg_share",
    "roof_p05",
    "roof_p50",
    "roof_p95",
    "eave_p10",
    "eave_p50",
    "eave_main",
    "ridge",
    "ground_in_share",
    "ring_low_share",
    "ring_low_p90",
]
MAX_AREA_M2 = 2000.0  # point-cloud features only for footprints up to this area (the training population)


def ground_stats(g, a: np.ndarray, t, water_m: tuple[float, ...] = ()) -> dict:
    """g: footprint in the DEM CRS; a: DEM window (metres, NaN = nodata) covering g buffered 31 m; t: its transform;
    water_m: the hydro-flattened constants (metres) of the tile(s) the window comes from."""

    def cells(geom):
        v = a[~geometry_mask([mapping(geom)], a.shape, t)]
        return v[np.isfinite(v)]

    def keep(v):
        m = v / USFT >= WATER_FLOOR_FT
        for w in water_m:
            m &= np.abs(v - w) > WATER_TOL_M
        return m

    def stat(geom):
        v = cells(geom)
        return v[keep(v)] / USFT

    rec: dict = {}
    ring = cells(g.buffer(2.5).difference(g.buffer(0.5)))
    k = keep(ring)
    rec.update(ring_n=int(ring.size), ring_n_masked=int((~k).sum()))
    if ring.size >= 5:
        rec["lag_unmasked"] = float(ring.min() / USFT)
    v, vi, vf = ring[k] / USFT, stat(g), stat(g.buffer(30).difference(g.buffer(10)))
    if v.size >= 5:
        rec.update(lag=float(v.min()), p10=float(np.percentile(v, 10)), med=float(np.median(v)), hag=float(v.max()))
    if vi.size >= 5:
        rec["inside"] = float(np.median(vi))
    if vf.size >= 20:
        rec["far"] = float(np.median(vf))
    return rec


def main_eave(v: np.ndarray, bin_ft: float = 0.5, share: float = 0.15) -> float:
    """Highest dominant height cluster of edge returns: the eave of the main (top) roof (lpc_features.main_eave)."""
    if v.size < 20:
        return np.nan
    edges = np.arange(np.floor(v.min()) - 1, np.ceil(v.max()) + 1 + bin_ft, bin_ft)
    cnt, _ = np.histogram(v, edges)
    sm = np.convolve(cnt, [1, 2, 3, 2, 1], mode="same")
    mass = np.convolve(cnt, np.ones(5, dtype=int), mode="same")
    peak = np.r_[False, (sm[1:-1] >= sm[:-2]) & (sm[1:-1] > sm[2:]), False] & (mass >= share * v.size)
    if not peak.any():
        return np.nan
    i = np.where(peak)[0][-1]
    c = (edges[i] + edges[i + 1]) / 2
    return float(np.median(v[np.abs(v - c) <= 1.0]))


def disc_radius(fp) -> float:
    """Search radius: farthest footprint vertex from the centroid + 3.5 m (lpc_features.py: Hausdorff distance from
    the centroid to the exterior, which equals the distance to the farthest convex-hull vertex)."""
    return float(shapely.hausdorff_distance(fp.centroid, fp.convex_hull.boundary)) + 3.5


def lpc_stats(fp, pts: np.ndarray, lag_ft: float) -> dict:
    """fp: footprint (metric CRS of the points); pts: rows x, y, z (m), class + 100 if single return; lag in ft."""
    inner03, inner1 = fp.buffer(-0.3), fp.buffer(-1.0)
    ring3 = fp.buffer(3.0).difference(fp)
    px, py, pz, pc1 = pts[:, 0], pts[:, 1], pts[:, 2], pts[:, 3].astype(int)
    pc = pc1 % 100
    hz = pz / USFT - lag_ft
    ins = shapely.contains_xy(inner03, px, py)
    ng = ins & (pc == 6)
    core = shapely.contains_xy(inner1, px, py) if not inner1.is_empty else ins
    edge = ng & ~core
    ring = shapely.contains_xy(ring3, px, py)
    low = ring & np.isin(pc, (1, 6)) & (hz >= 2) & (hz <= 10)

    def q(v, p):
        return float(np.percentile(v, p)) if v.size >= 5 else np.nan

    return dict(
        n_in=int(ins.sum()),
        pts_m2=float(ins.sum() / max(inner03.area, 1.0)),
        bldg_share=float(ng.sum() / max(ins.sum(), 1)),
        roof_p05=q(hz[ng], 5),
        roof_p50=q(hz[ng], 50),
        roof_p95=q(hz[ng], 95),
        eave_p10=q(hz[edge], 10),
        eave_p50=q(hz[edge], 50),
        eave_main=main_eave(hz[edge]),
        ridge=q(hz[ng], 99),
        ground_in_share=float((core & (pc == 2)).sum() / max(core.sum(), 1)),
        ring_low_share=float(low.sum() / max(ring.sum(), 1)),
        ring_low_p90=q(hz[low], 90),
    )
