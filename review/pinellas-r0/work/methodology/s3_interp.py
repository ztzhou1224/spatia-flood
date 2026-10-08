"""Reproduce the static-BFE check of the line interpolation; compare linear vs nearest-line vs same-source pairing."""
import sys
from pathlib import Path
import numpy as np, pandas as pd, shapely, pyarrow.parquet as pq
from pyproj import Transformer
ROOT = Path("/home/user/spatia-flood"); W = Path(sys.argv[1]); OUT = ROOT / "data/flood_v1/assemble"
ALBERS, LINE_SEARCH_M, BFE_ROUND_FT = "EPSG:3086", 1000.0, 0.5
tr = Transformer.from_crs("EPSG:4326", ALBERS, always_xy=True)
def projected(g): return shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])
z = pd.read_parquet(OUT / "zones_12103_raw.parquet")
zg = projected(shapely.make_valid(shapely.from_wkb(z.wkb.map(bytes).values)))
lines = pd.read_parquet(OUT / "bfe_lines_12103.parquet")
lines = lines[lines.elev_ft_navd88_ft.notna()].reset_index(drop=True).rename(columns={"elev_ft_navd88_ft": "elev"})
lg = projected(shapely.from_wkb(lines.wkb.map(bytes).values))
print("lines", len(lines), lines.source_type.value_counts().to_dict(), "| whole-foot elevations: BFE_LINE", (lines[lines.source_type=="BFE_LINE"].elev % 1 == 0).mean().round(3), "XS", (lines[lines.source_type=="XS"].elev % 1 == 0).mean().round(3))
t = pq.read_table(OUT / "buildings_12103.parquet", columns=["building_id", "touches_sfha", "bfe_method", "bfe_ft", "geometry"])
b = t.to_pandas()
sel = (b.touches_sfha.fillna(False).astype(bool) & (b.bfe_method == "static")).values
print("static+touches_sfha buildings", sel.sum())
g = shapely.from_wkb(b.geometry.values[sel]); ga = projected(g); cen = shapely.centroid(ga)
sfha_poly = np.where(z.sfha_tf.values == "T")[0]
# polygons crossed by lines
pi_, li_ = shapely.STRtree(lg).query(zg[sfha_poly], predicate="intersects")
crossed = np.unique(sfha_poly[pi_])
print("SFHA polygons crossed by a line", len(crossed), "of", len(sfha_poly))
# buildings intersecting crossed polygons
bi, pi = shapely.STRtree(zg[crossed]).query(ga, predicate="intersects")
polys_of = {}
for a_, p_ in zip(bi, crossed[pi]): polys_of.setdefault(int(a_), set()).add(int(p_))
print("candidate buildings", len(polys_of))
def interp(cen, polys_of, zg, lines, lg, mode="linear", same_source=False):
    need = sorted({q for ps in polys_of.values() for q in ps})
    li, pi = shapely.STRtree(lg).query(zg[need], predicate="intersects")
    by_poly = {}
    for k, j in zip(np.asarray(need)[li], pi): by_poly.setdefault(int(k), set()).add(int(j))
    rows = []
    for a, ps in polys_of.items():
        cand = sorted(set().union(*(by_poly.get(q, set()) for q in ps)))
        c = cen[a]
        if cand:
            d = shapely.distance(c, lg[cand]); keep = d <= LINE_SEARCH_M; cand, d = np.asarray(cand)[keep], d[keep]
        if not len(cand): rows.append({"a": a, "null": "no_coverage"}); continue
        near = shapely.get_coordinates(shapely.shortest_line(c, lg[cand]))[1::2] - shapely.get_coordinates(c)
        o = np.argsort(d); i1 = o[0]; e1 = lines.elev.values[cand[i1]]
        if mode == "nearest":
            rows.append({"a": a, "bfe": e1, "lo": e1 - BFE_ROUND_FT, "hi": e1 + BFE_ROUND_FT, "d1": d[i1]}); continue
        if d[i1] == 0: i2, e2, f = i1, e1, 0.0
        else:
            opp = [k for k in o[1:] if d[k] > 0 and near[k] @ near[i1] < 0 and (not same_source or lines.source_type.values[cand[k]] == lines.source_type.values[cand[i1]])]
            if not opp: rows.append({"a": a, "null": "not_determinable"}); continue
            i2 = opp[0]; e2 = lines.elev.values[cand[i2]]; f = d[i1] / (d[i1] + d[i2])
        rows.append({"a": a, "bfe": e1 + (e2 - e1) * f, "lo": min(e1, e2) - BFE_ROUND_FT, "hi": max(e1, e2) + BFE_ROUND_FT, "d1": d[i1], "d2": d[i2],
                     "t1": lines.source_type.values[cand[i1]], "t2": lines.source_type.values[cand[i2]], "e1": e1, "e2": e2})
    return pd.DataFrame(rows)
static = b.bfe_ft.values[sel]
res = {}
for name, kw in (("linear", {}), ("nearest", {"mode": "nearest"}), ("linear_same_source", {"same_source": True})):
    r = interp(cen, polys_of, zg, lines, lg, **kw)
    r = r[r.bfe.notna()] if "bfe" in r else r.iloc[0:0]
    err = r.bfe.values - static[r.a.values.astype(int)]
    inb = (static[r.a.values.astype(int)] >= r.lo.values - 1e-9) & (static[r.a.values.astype(int)] <= r.hi.values + 1e-9)
    res[name] = r.assign(err=err)
    print(f"{name}: n {len(r)}, MAE {np.abs(err).mean():.3f}, median |err| {np.median(np.abs(err)):.3f}, within 1 ft {(np.abs(err) <= 1).mean():.3f}, static inside band {inb.mean():.3f}, bias {err.mean():+.3f}, |err|>2 ft: {(np.abs(err) > 2).sum()}")
# compare linear vs nearest on the same buildings (linear's set)
L, N = res["linear"].set_index("a"), res["nearest"].set_index("a")
both = L.index.intersection(N.index)
print(f"same {len(both)} buildings: linear MAE {np.abs(L.loc[both].err).mean():.3f} vs nearest MAE {np.abs(N.loc[both].err).mean():.3f}; linear better on {(np.abs(L.loc[both].err) < np.abs(N.loc[both].err)).sum()}, worse on {(np.abs(L.loc[both].err) > np.abs(N.loc[both].err)).sum()}, tie {(np.abs(L.loc[both].err) == np.abs(N.loc[both].err)).sum()}")
print("linear check pairs by source type:", (L.t1 + "/" + L.t2).value_counts().to_dict())
print("linear check: |e1-e2| quantiles", (L.e1 - L.e2).abs().quantile([.5, .9, 1]).to_dict(), "| static BFE of these buildings quantiles", np.quantile(static[L.index.values.astype(int)], [0, .5, 1]))
print("large errors (>1 ft):"); print(L[np.abs(L.err) > 1][["bfe", "e1", "e2", "d1", "d2", "t1", "t2", "err"]].round(2).to_string())
res["linear"].to_parquet(W / "interp_check_linear.parquet", index=False)
