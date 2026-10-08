import sys, numpy as np, pandas as pd, shapely, pyarrow.parquet as pq
D = sys.argv[1]
b = pq.read_table(f"{D}/assemble/buildings_12103.parquet", columns=["building_id","zones","bfe_ft","bfe_method","bfe_call","ffe_ft","ffe_class","touches_sfha","zone_main"]).to_pandas()
# Need per-polygon BFE per building: rebuild from zones_raw overlay? zones column lacks BFE. Use count of distinct SFHA elements as proxy and instead re-run the overlay on the subset with >1 SFHA element.
z = pq.read_table(f"{D}/assemble/zones_12103_raw.parquet").to_pandas()
from pyproj import Transformer
tr = Transformer.from_crs("EPSG:4326", "EPSG:3086", always_xy=True)
def proj(g): return shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])
zg = proj(shapely.make_valid(shapely.from_wkb(z.wkb.values)))
geo = pq.read_table(f"{D}/assemble/buildings_12103.parquet", columns=["building_id","geometry"]).to_pandas()
multi = b[b.zones.map(lambda L: L is not None and sum(1 for e in L if e["sfha"]) > 1)].index.values
print("buildings with >1 SFHA element", len(multi))
ga = proj(shapely.from_wkb(geo.geometry.values[multi]))
tree = shapely.STRtree(zg)
bi, pi = tree.query(ga, predicate="intersects")
area = shapely.area(shapely.intersection(ga[bi], zg[pi]))
df = pd.DataFrame({"a": multi[bi], "p": pi, "area": area})
df = df[df.area > 0]
df["sfha"] = z.sfha_tf.values[df.p] == "T"
df["bfe"] = z.static_bfe_navd88_ft.values[df.p]
df["zone"] = z.fld_zone.values[df.p]
s = df[df.sfha & df.bfe.notna()]
g = s.groupby("a")
hi = g.bfe.max()
largest = s.sort_values("area", ascending=False).drop_duplicates("a").set_index("a").bfe
diff = (hi - largest.reindex(hi.index))
print("buildings with >1 SFHA polygon carrying a static BFE:", len(hi), "; highest != largest-share BFE:", int((diff > 0).sum()), "; max diff ft", float(diff.max()), "; median diff where >0", float(diff[diff > 0].median()) if (diff > 0).any() else None)
k = diff[diff > 0].index
sub = b.loc[k]
print("calls among those:", sub.bfe_call.value_counts().to_dict())
# would the call flip if the largest-share BFE were used? (record and modeled point only, crude)
sub = sub.assign(alt=largest.reindex(k).values)
flip = sub[(sub.bfe_call == "below") & (sub.ffe_ft >= sub.alt)]
print("below calls that would be at/above the largest-share polygon's BFE:", len(flip))
# zone combos
print(s.groupby("a").zone.agg(lambda x: "+".join(sorted(set(x)))).loc[k].value_counts().head(8).to_dict())
