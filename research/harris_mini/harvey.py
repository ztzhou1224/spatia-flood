"""Did the FEMA zone, the floor, or the terrain predict who flooded in Harvey?

Inputs (data/harris_mini/<AREA>): l22 flooded structures (HCFCD; Harvey, Allison, Tax Day 2016...),
l24 structure inventory, l26 footprints, houses.parquet (answer-key houses with lidar ground, from
ground.py), nfhl_28 zones / nfhl_16 BFE lines (current effective NFHL), 2018 1 m DEM tiles.
Measured FFE (answer key) is used here as the physical quantity under test, not as a model input
for floor estimation; rows using our ESTIMATED floor are labelled so.
Usage: python harvey.py AREA [AREA ...]
"""
import glob, json, sys
from pathlib import Path
import numpy as np, pandas as pd, pyarrow.parquet as pq, rasterio
from rasterio.merge import merge
from scipy import ndimage
from shapely import from_geojson
from shapely.geometry import Point, Polygon, shape, LineString, MultiLineString
from shapely.strtree import STRtree
from shapely import wkt as swkt
from skimage.morphology import reconstruction
from sklearn.metrics import roc_auc_score
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
USFT = 1200 / 3937

def esri_poly(g):
    rings = json.loads(g)["rings"]
    return Polygon(rings[0], rings[1:]).buffer(0) if len(rings) else None

def esri_line(g):
    paths = json.loads(g)["paths"]
    return MultiLineString(paths) if len(paths) > 1 else LineString(paths[0])

def terrain(area, pts):
    """Depression depth (fill - DEM) and local relative elevation, 2018 DEM at 2 m, in ft."""
    srcs = [rasterio.open(f) for f in glob.glob(str(D / area / "*2018*.tif"))]
    x0, y0, x1, y1 = pts[:, 0].min() - 1500, pts[:, 1].min() - 1500, pts[:, 0].max() + 1500, pts[:, 1].max() + 1500
    arr, tr = merge(srcs, bounds=(x0, y0, x1, y1), res=2.0, resampling=rasterio.enums.Resampling.average, nodata=np.nan)
    z = arr[0].astype("float64") / USFT
    z = np.where(np.isfinite(z), z, np.nanmax(z))
    seed = z.copy(); seed[1:-1, 1:-1] = z.max()
    filled = reconstruction(seed, z, method="erosion")
    dep = filled - z
    local = ndimage.uniform_filter(z, size=501)  # ~1 km window
    inv = ~tr
    c, r = inv * (pts[:, 0], pts[:, 1])
    r, c = np.clip(r.astype(int), 0, z.shape[0] - 1), np.clip(c.astype(int), 0, z.shape[1] - 1)
    # depression depth: max within 5 px (10 m) of the house point
    depmax = ndimage.maximum_filter(dep, size=5)
    return depmax[r, c], z[r, c] - local[r, c]

def bfe_at(area, pts, zones):
    """BFE (ft NAVD88): static BFE of the covering zone polygon, else inverse-distance between the two
    nearest BFE lines within 1.5 km (screening proxy for the 1% water surface)."""
    out = np.full(len(pts), np.nan)
    st = zones[zones.STATIC_BFE > 0]
    if len(st):
        tree = STRtree(list(st.geom))
        for i, (x, y) in enumerate(pts):
            hit = tree.query(Point(x, y), predicate="intersects")
            if len(hit): out[i] = st.STATIC_BFE.values[hit].max()
    try:
        b = pd.read_parquet(D / area / "nfhl_16.parquet")
    except FileNotFoundError:
        return out
    lines = [esri_line(g) for g in b.geometry]
    elev = b.ELEV.values
    for i, (x, y) in enumerate(pts):
        if np.isfinite(out[i]): continue
        p = Point(x, y); d = np.array([l.distance(p) for l in lines])
        o = np.argsort(d)[:2]
        if d[o[0]] > 1500: continue
        w = 1 / np.maximum(d[o], 1.0)
        out[i] = (elev[o] * w).sum() / w.sum()
    return out

def zone_class(z):
    if z["FLD_ZONE"] in ("AE", "VE", "A", "AH", "AO", "V"): return "SFHA"
    if z["FLD_ZONE"] == "X" and isinstance(z["ZONE_SUBTY"], str) and "0.2" in z["ZONE_SUBTY"]: return "X 0.2%"
    return "X minimal"

def auc(y, s):
    m = np.isfinite(s)
    return roc_auc_score(y[m], s[m]) if m.sum() > 50 and y[m].nunique() > 1 else np.nan

def main(area):
    zones = pd.read_parquet(D / area / "nfhl_28.parquet")
    zones["geom"] = [esri_poly(g) for g in zones.geometry]
    zones = zones[zones.geom.notna()].copy()
    zones["cls"] = zones.apply(zone_class, axis=1)
    rank = {"SFHA": 0, "X 0.2%": 1, "X minimal": 2}
    ztree = STRtree(list(zones.geom))
    def classify(g):
        hit = ztree.query(g, predicate="intersects")
        return min((zones.cls.values[h] for h in hit), key=rank.get) if len(hit) else "unmapped"

    fl = pd.read_parquet(D / area / "l22.parquet")
    fl["cls"] = [classify(Point(x, y)) for x, y in zip(fl.gx, fl.gy)]
    print(f"\n## Area {area}")
    print("\n### All flooded-structure points by event and current FEMA zone (point location)")
    print(pd.crosstab(fl.Event, fl.cls, margins=True).to_markdown())

    # all SFR structures in the inventory, footprint any-touch zone class
    si = pd.read_parquet(D / area / "l24.parquet")
    si = si[si.WWCStrucType == "SFR"].copy()
    fp = pd.read_parquet(D / area / "l26.parquet")
    fpg = {o: esri_poly(json.dumps({"rings": json.loads(r)})) for o, r in zip(fp.outline_id, fp.rings) if r}
    si["geom"] = [fpg.get(o) or Point(x, y) for o, x, y in zip(si.outline_id, si.gx, si.gy)]
    si["cls"] = [classify(g) for g in si.geom]
    # most flooded records carry no HCAD: match each point to the nearest SFR footprint within 25 m
    stree = STRtree(list(si.geom))
    si["harvey"], si["any_event"] = False, False
    matched = 0
    for x, y, e in zip(fl.gx, fl.gy, fl.Event):
        p = Point(x, y)
        j, dist = stree.query_nearest(p, max_distance=25, return_distance=True)
        if len(j):
            matched += 1
            k = si.index[j[0]]
            si.loc[k, "any_event"] = True
            if e == "Harvey": si.loc[k, "harvey"] = True
    flooded_hcad_h = set(si.HCAD_NUM[si.harvey])
    print(f"\n### All SFR structures ({len(si)}), footprint touching the current FEMA zone")
    t = si.groupby("cls").agg(structures=("harvey", "size"), flooded_harvey=("harvey", "sum"), flooded_any=("any_event", "sum"))
    t["harvey_rate"] = (t.flooded_harvey / t.structures).round(3)
    t["share_of_harvey_flooded"] = (t.flooded_harvey / t.flooded_harvey.sum()).round(3)
    print(t.to_markdown())
    print(f"flooded points matched to an SFR footprint within 25 m: {matched / len(fl):.1%} of {len(fl)} (the rest are other building types or unlocated)")

    # answer-key houses: floor, ground, terrain, BFE
    h = pd.read_parquet(D / area / "houses.parquet")
    h = h[(h["loc"] == "Front Door") & h.e2018_lag.notna()].copy()
    pts = h[["x", "y"]].values
    h["dep"], h["rel"] = terrain(area, pts)
    h["bfe"] = bfe_at(area, pts, zones)
    h["cls"] = [classify(swkt.loads(w)) for w in h.fp_wkt]
    h["flooded"] = h.hcad.isin(flooded_hcad_h)
    h["ffh"] = h.ffe - h.e2018_lag
    h["ffe_minus_bfe"] = h.ffe - h.bfe
    y = h.flooded.astype(int)
    print(f"\n### Answer-key houses: {len(h)}, Harvey-flooded {y.sum()} ({y.mean():.1%}); BFE proxy available {np.isfinite(h.bfe).mean():.0%}")
    def rate(col, bins):
        g = pd.cut(h[col], bins)
        return h.groupby(g, observed=True).flooded.agg(["size", "mean"]).rename(columns={"size": "houses", "mean": "flood_rate"}).round(3)
    print("\nFlood rate by measured front-door floor minus BFE (ft)"); print(rate("ffe_minus_bfe", [-50, -2, 0, 1, 2, 4, 8, 100]).to_markdown())
    print("\nFlood rate by depression depth at the house (ft, 2018 lidar fill)"); print(rate("dep", [-1, 0.25, 1, 2, 4, 100]).to_markdown())
    print("\nFlood rate by door height above lowest adjacent grade (ft)"); print(rate("ffh", [-5, 1, 2, 3, 5, 30]).to_markdown())
    print("\nFlood rate by zone"); print(h.groupby("cls").flooded.agg(["size", "mean"]).round(3).to_markdown())

    # predictive power (higher score = more likely flooded)
    sc = {
        "FEMA zone (SFHA > 0.2% > minimal)": h.cls.map({"SFHA": 2, "X 0.2%": 1, "X minimal": 0, "unmapped": 0}).astype(float),
        "lidar ground elevation (lower = worse)": -h.e2018_lag,
        "ground minus BFE": -(h.e2018_lag - h.bfe),
        "measured floor minus BFE": -h.ffe_minus_bfe,
        "depression depth": h.dep,
        "relative elevation (1 km window)": -h.rel,
    }
    # estimated floor (no answer key for the house itself): LAG + median door height of 5 nearest pool houses (10% pool)
    rng = np.random.default_rng(0); pool = rng.random(len(h)) < 0.10
    from sklearn.neighbors import KDTree
    tree = KDTree(pts[pool]); _, idx = tree.query(pts, k=6)
    pf = h.ffh.values[pool]; pidx = np.where(pool)[0]
    est = []
    for i, row in enumerate(idx):
        nb = [pf[j] for j in row if pidx[j] != i][:5]; est.append(np.median(nb))
    h["ffe_est"] = h.e2018_lag + np.array(est)
    sc["ESTIMATED floor minus BFE (lidar + neighbours)"] = -(h.ffe_est - h.bfe)
    print("\n### How well each signal ranks flooded vs not (ROC AUC; 0.5 = no skill), answer-key houses")
    print(pd.Series({k: auc(y, v.values) for k, v in sc.items()}, name="AUC").round(3).to_markdown())

    # combined model, spatial block CV
    X = pd.DataFrame({"sfha": (h.cls == "SFHA").astype(float), "x02": (h.cls == "X 0.2%").astype(float),
                      "gmb": (h.e2018_lag - h.bfe), "dep": h.dep, "rel": h.rel, "fmb_est": h.ffe_est - h.bfe})
    X = X.fillna(X.median())
    blocks = (h.x // 1000).astype(int).astype(str) + "_" + (h.y // 1000).astype(int).astype(str)
    def cv(cols):
        p = np.zeros(len(h))
        for tr, te in GroupKFold(5).split(X, groups=blocks):
            m = LogisticRegression(max_iter=1000).fit(X.iloc[tr][cols], y.iloc[tr])
            p[te] = m.predict_proba(X.iloc[te][cols])[:, 1]
        return roc_auc_score(y, p)
    print("\n### Combined (logistic, spatial 1 km block CV, AUC)")
    for name, cols in (("zone only", ["sfha", "x02"]), ("terrain only", ["gmb", "dep", "rel"]),
                       ("zone + terrain", ["sfha", "x02", "gmb", "dep", "rel"]),
                       ("zone + terrain + ESTIMATED floor", ["sfha", "x02", "gmb", "dep", "rel", "fmb_est"])):
        print(f"| {name} | {cv(cols):.3f} |")

if __name__ == "__main__":
    pd.set_option("display.width", 200)
    for a in sys.argv[1:]: main(a)
