"""Per-house NATIONAL inputs for floor and water, for the coverage test.

Only inputs that exist (or can be computed) almost anywhere in the US:
  NSI (USACE National Structure Inventory): foundation type, default foundation height, year built,
      stories, NSI's own ground elevation.
  3DEP lidar (2018 1 m DEM here): ground around the footprint (from ground.py), depression depth and
      relative elevation (harvey.terrain).
  NHDPlus HR streams / water areas / water bodies: height of the lowest adjacent grade above the
      nearest stream or water surface (REM, "relative elevation model", a HAND-like measure) and distance.
  FEMA NFHL: zone class and BFE (harvey.bfe_at).
  NOAA national storm surge risk maps (SLOSH MOM, high tide), Category 1-5 inundation depth bins.
Labels (scorer only): HCFCD flooded structures (layer 22) matched to footprints within 25 m, by event.
Answer key (HCFCD front-door FFE) is carried for scoring only.
Output: data/harris_mini/<AREA>/coverage_features.parquet
Usage: python features.py AREA [AREA ...]
"""
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from pyproj import Transformer
from shapely import wkt as swkt
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import nearest_points
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harris_mini"))
import harvey  # noqa: E402  (esri_poly, terrain, bfe_at, zone_class)

D = HERE.parents[1] / "data" / "harris_mini"
SURGE = HERE.parents[1] / "data" / "surge"
USFT = 1200 / 3937


def esri_geom(g: str):
    j = json.loads(g)
    if "paths" in j:
        return MultiLineString(j["paths"]) if len(j["paths"]) > 1 else LineString(j["paths"][0])
    if "rings" in j and j["rings"]:
        return Polygon(j["rings"][0], j["rings"][1:]).buffer(0)
    return None


class DEM:
    def __init__(self, area):
        self.srcs = [rasterio.open(f) for f in glob.glob(str(D / area / "*2018*.tif"))]

    def window_vals(self, x, y, r):
        for s in self.srcs:
            b = s.bounds
            if b.left < x - r and x + r < b.right and b.bottom < y - r and y + r < b.top:
                w = rasterio.windows.from_bounds(x - r, y - r, x + r, y + r, s.transform)
                a = s.read(1, window=w.round_offsets().round_lengths(), masked=True).filled(np.nan)
                return a[np.isfinite(a) & (a > -1e5)] / USFT
        return np.array([])


def flooded_by_event(area, si_geoms, si_hcad):
    fl = pd.read_parquet(D / area / "l22.parquet")
    tree = STRtree(si_geoms)
    out = {}
    for x, y, e in zip(fl.gx, fl.gy, fl.Event):
        j = tree.query_nearest(Point(x, y), max_distance=25)
        if len(j):
            out.setdefault(si_hcad[j[0]], set()).add(e)
    return out


def main(area):
    h = pd.read_parquet(D / area / "houses.parquet")
    h = h[(h["loc"] == "Front Door") & h.e2018_lag.notna()].copy().reset_index(drop=True)
    fps = [swkt.loads(w) for w in h.fp_wkt]
    pts = np.c_[h.x.values, h.y.values]
    # labels (scorer only)
    si = pd.read_parquet(D / area / "l24.parquet")
    si = si[si.WWCStrucType == "SFR"]
    fp26 = pd.read_parquet(D / area / "l26.parquet")
    g26 = {o: harvey.esri_poly(json.dumps({"rings": json.loads(r)})) for o, r in zip(fp26.outline_id, fp26.rings) if r}
    geoms = [g26.get(o) or Point(x, y) for o, x, y in zip(si.outline_id, si.gx, si.gy)]
    ev = flooded_by_event(area, geoms, si.HCAD_NUM.values)
    for name, keys in (("fl_harvey", {"Harvey"}), ("fl_taxday", {"Tax Day 2016"}),
                       ("fl_allison", {"Tropical Storm Allison"}), ("fl_any", None)):
        h[name] = [bool(ev.get(c)) if keys is None else bool(ev.get(c, set()) & keys) for c in h.hcad]
    # NSI: the NSI point inside the footprint, else nearest within 15 m
    nsi = pd.read_parquet(D / area / "nsi.parquet")
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:6344", always_xy=True)
    nx, ny = to_utm.transform(nsi.x.values, nsi.y.values)
    ntree = STRtree([Point(a, b) for a, b in zip(nx, ny)])
    cols = {k: [] for k in ("nsi_found_type", "nsi_found_ht", "nsi_year", "nsi_stories", "nsi_ground", "nsi_occ")}
    for fp in fps:
        j = ntree.query(fp, predicate="contains")
        if not len(j):
            j = ntree.query_nearest(fp, max_distance=15)
        r = nsi.iloc[j[0]] if len(j) else None
        for k, c in (("nsi_found_type", "found_type"), ("nsi_found_ht", "found_ht"), ("nsi_year", "med_yr_blt"),
                     ("nsi_stories", "num_story"), ("nsi_ground", "ground_elv"), ("nsi_occ", "occtype")):
            cols[k].append(r[c] if r is not None else None)
    for k, v in cols.items():
        h[k] = v
    # terrain + FEMA
    h["dep"], h["rel"] = harvey.terrain(area, pts)
    zones = pd.read_parquet(D / area / "nfhl_28.parquet")
    zones["geom"] = [harvey.esri_poly(g) for g in zones.geometry]
    zones = zones[zones.geom.notna()].copy()
    zones["cls"] = zones.apply(harvey.zone_class, axis=1)
    zt = STRtree(list(zones.geom))
    rank = {"SFHA": 0, "X 0.2%": 1, "X minimal": 2}
    h["zone"] = [min((zones.cls.values[k] for k in zt.query(fp, predicate="intersects")), key=rank.get, default="X minimal")
                 for fp in fps]
    h["bfe"] = harvey.bfe_at(area, pts, zones)
    # REM: LAG above the nearest stream / water area / water body surface
    feats = []
    for name in ("nhd_flow", "nhd_area", "nhd_wb"):
        p = D / area / f"{name}.parquet"
        if p.exists():
            feats += [g for g in (esri_geom(s) for s in pd.read_parquet(p).geometry) if g is not None and not g.is_empty]
    wtree = STRtree(feats)
    dem = DEM(area)
    rem, dist = [], []
    for fp, lag in zip(fps, h.e2018_lag):
        c = fp.centroid
        j = wtree.query_nearest(c, max_distance=4000)
        if not len(j):
            rem.append(np.nan); dist.append(np.nan); continue
        g = feats[j[0]]
        q = nearest_points(g, c)[0]
        v = dem.window_vals(q.x, q.y, 30)
        dist.append(c.distance(g))
        rem.append(lag - np.percentile(v, 5) if v.size >= 20 else np.nan)
    h["rem"], h["dist_water_m"] = rem, dist
    # NOAA surge: inundation depth bin (ft above ground) at the footprint centroid, Cat 1..5
    to_ll = Transformer.from_crs("EPSG:6344", "EPSG:4269", always_xy=True)
    lon, lat = to_ll.transform(h.x.values, h.y.values)
    for cat in range(1, 6):
        f = SURGE / f"{area}_cat{cat}.tif"
        with rasterio.open(f) as s:
            v = np.array([x[0] for x in s.sample(list(zip(lon, lat)))]).astype(float)
        v[v == 255] = 0  # 255 = no data / dry land; 0 not used
        h[f"surge{cat}_ft"] = v  # class k = (k-1, k] ft above ground; 0 = dry
    h["surge_min_cat"] = [next((c for c in range(1, 6) if r[f"surge{c}_ft"] > 0), 6) for _, r in h.iterrows()]
    h.drop(columns=["fp_wkt"]).to_parquet(D / area / "coverage_features.parquet", index=False)
    print(area, len(h), "houses; flooded any/Harvey/TaxDay/Allison:",
          int(h.fl_any.sum()), int(h.fl_harvey.sum()), int(h.fl_taxday.sum()), int(h.fl_allison.sum()),
          "| NSI matched", f"{h.nsi_found_ht.notna().mean():.0%}", "| REM", f"{h.rem.notna().mean():.0%}",
          "| surge cat<=5", int((h.surge_min_cat <= 5).sum()))


if __name__ == "__main__":
    for a in sys.argv[1:]:
        main(a)
