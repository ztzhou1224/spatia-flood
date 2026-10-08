import sys, numpy as np, pandas as pd, shapely, pyarrow.parquet as pq, duckdb
from pyproj import Transformer
D = sys.argv[1]
c = duckdb.connect()
B = f"read_parquet('{D}/assemble/buildings_12103.parquet')"
# candidates: buildings whose zones list has >1 SFHA element (zones column aggregates by zone+subtype, so this is a lower bound; re-overlay them)
cand = c.sql(f"SELECT building_id, bfe_ft, bfe_call, ffe_ft, bfe_method FROM {B} WHERE len(list_filter(zones, z -> z.sfha)) > 1").df()
print("buildings with >1 SFHA zone element:", len(cand))
geo = c.sql(f"SELECT building_id, ST_AsWKB(geometry) wkb FROM {B} WHERE len(list_filter(zones, z -> z.sfha)) > 1").df() if False else None
tab = pq.read_table(f"{D}/assemble/buildings_12103.parquet", columns=["building_id","geometry"]).to_pandas().set_index("building_id")
tr = Transformer.from_crs("EPSG:4326", "EPSG:26917", always_xy=True)
def proj(g): return shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])
z = pq.read_table(f"{D}/assemble/zones_12103_raw.parquet", columns=["fld_zone","sfha_tf","static_bfe_navd88_ft","wkb"]).to_pandas()
zg = proj(shapely.make_valid(shapely.from_wkb(z.wkb.values)))
ga = proj(shapely.from_wkb(tab.geometry.reindex(cand.building_id).values))
bi, pi = shapely.STRtree(zg).query(ga, predicate="intersects")
area = shapely.area(shapely.intersection(ga[bi], zg[pi]))
df = pd.DataFrame({"b": bi, "p": pi, "area": area}); df = df[df.area > 0]
df["sfha"] = z.sfha_tf.values[df.p] == "T"; df["bfe"] = z.static_bfe_navd88_ft.values[df.p]; df["zone"] = z.fld_zone.values[df.p]
s = df[df.sfha & df.bfe.notna()]
nbfe = s.groupby("b").p.nunique(); multi = nbfe[nbfe > 1].index
hi = s[s.b.isin(multi)].groupby("b").bfe.max()
largest = s[s.b.isin(multi)].sort_values("area", ascending=False).drop_duplicates("b").set_index("b").bfe
diff = hi - largest.reindex(hi.index)
print("buildings overlapping >1 SFHA polygon with a static BFE:", len(hi), "; highest != largest-share:", int((diff > 0).sum()), "; median diff", float(diff[diff>0].median()), "max", float(diff.max()))
k = diff[diff > 0].index
sub = cand.iloc[k].copy(); sub["alt"] = largest.reindex(k).values
print("published bfe_ft == highest for those:", int((sub.bfe_ft.values == hi.reindex(k).values).sum()), "of", len(sub), "; methods:", sub.bfe_method.value_counts().to_dict())
print("calls:", sub.bfe_call.value_counts(dropna=False).to_dict())
print("below calls with ffe >= largest-share BFE:", int(((sub.bfe_call == "below") & (sub.ffe_ft >= sub.alt)).sum()))
zc = s[s.b.isin(k)].groupby("b").zone.agg(lambda x: "+".join(sorted(set(x)))).value_counts().head(5).to_dict(); print("zone combos:", zc)
