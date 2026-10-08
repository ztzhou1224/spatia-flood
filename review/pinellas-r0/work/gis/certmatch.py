import sys, json, glob, numpy as np, pandas as pd, shapely, pyarrow.parquet as pq
from pyproj import Transformer
D, RAW = sys.argv[1], sys.argv[2]
pages = sorted(glob.glob(f"{RAW}/page_*.json"))
feats, wk = [], None
for p in pages:
    d = json.load(open(p))
    wk = d.get("spatialReference")
    for f in d["features"]:
        g = f.get("geometry") or {}
        a = f["attributes"]
        feats.append((g.get("x"), g.get("y"), a.get("A5_HORIZ_DATUM"), a.get("POINT_TYPE"), a.get("VERTICAL_DATUM"), a.get("D_DATE")))
e = pd.DataFrame(feats, columns=["x","y","hdatum","ptype","vdatum","ddate"])
print("pages", len(pages), "records", len(e), "spatialReference", wk, "with xy", int(e.x.notna().sum()))
print("POINT_TYPE counts", e.ptype.value_counts(dropna=False).head(6).to_dict())
print("A5_HORIZ_DATUM counts", e.hdatum.value_counts(dropna=False).head(6).to_dict())
e = e[e.x.notna()].copy()
wkid = (wk or {}).get("latestWkid") or (wk or {}).get("wkid")
tr = Transformer.from_crs(f"EPSG:{wkid}", "EPSG:6442", always_xy=True)
ex, ey = tr.transform(e.x.values, e.y.values)
pts = shapely.points(ex, ey)
geo = pq.read_table(f"{D}/assemble/buildings_12103.parquet", columns=["building_id","geometry"]).to_pandas()
tr2 = Transformer.from_crs("EPSG:4326", "EPSG:6442", always_xy=True)
g = shapely.transform(shapely.from_wkb(geo.geometry.values), lambda xy: np.c_[tr2.transform(xy[:, 0], xy[:, 1])])
tree = shapely.STRtree(g)
pi, fi = tree.query(pts, predicate="within")
within = np.zeros(len(e), bool); within[pi] = True
idx, dist = tree.query_nearest(pts, return_distance=True, all_matches=False)
d = np.full(len(e), np.nan); d[idx[0]] = dist
e["within"], e["dist_m"] = within, d
print("county EC points: within a footprint", int(within.sum()), f"({within.mean():.3f}); not within:", int((~within).sum()))
nw = e[~within]
bins = [0, 5, 10, 25, 50, 100, 1e9]
print("distance of NOT-within points to the nearest Overture footprint (m):", pd.cut(nw.dist_m, bins).value_counts().sort_index().to_dict())
print("share of not-within with a footprint within 25 m:", round(float((nw.dist_m <= 25).mean()), 3), "; beyond 25 m:", int((nw.dist_m > 25).sum()))
# first-20 sample of those beyond 10 m: distance only
print("sample distances (m) of 20 not-within beyond 10 m:", nw[nw.dist_m > 10].dist_m.round(1).head(20).tolist())
