"""Tail split of band misses on test; buildings overlapping several static BFE polygons (the 'highest BFE' rule)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd, shapely, pyarrow.parquet as pq
from pyproj import Transformer
ROOT = Path("/home/user/spatia-flood"); W = Path(sys.argv[1]); OUT = ROOT / "data/flood_v1/assemble"
t = pd.read_parquet(W / "test_scored.parquet")
miss_lo, miss_hi = (t.dh < t.lo), (t.dh > t.hi)
print(f"test band misses: truth below band {miss_lo.sum()} ({miss_lo.mean():.3f}), truth above band {miss_hi.sum()} ({miss_hi.mean():.3f}); by flag:",
      t.groupby("flag").apply(lambda g: (int((g.dh < g.lo).sum()), int((g.dh > g.hi).sum())), include_groups=False).to_dict())
# the 'above' call needs truth >= lo: one-sided miss rate below the band
print("truth below band among SFHA houses:", f"{(miss_lo & t.cert_bfe_ft.notna()).sum()}")
tr = Transformer.from_crs("EPSG:4326", "EPSG:3086", always_xy=True)
def projected(g): return shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])
z = pd.read_parquet(OUT / "zones_12103_raw.parquet")
zg = projected(shapely.make_valid(shapely.from_wkb(z.wkb.map(bytes).values)))
st = np.where((z.sfha_tf.values == "T") & z.static_bfe_navd88_ft.notna().values)[0]
b = pq.read_table(OUT / "buildings_12103.parquet", columns=["building_id", "touches_sfha", "bfe_method", "bfe_ft", "bfe_call", "ffe_class", "ffe_ft", "geometry"]).to_pandas()
sel = np.where((b.bfe_method == "static").values)[0]
ga = projected(shapely.from_wkb(b.geometry.values[sel]))
polys = zg[st]; shapely.prepare(polys)
bi, pi = shapely.STRtree(polys).query(ga)
hit = shapely.intersects(polys[pi], ga[bi]); bi, pi = bi[hit], pi[hit]
area = shapely.area(shapely.intersection(ga[bi], polys[pi])); m = area > 0
pr = pd.DataFrame({"a": sel[bi[m]], "bfe": z.static_bfe_navd88_ft.values[st[pi[m]]], "area": area[m]})
g = pr.groupby("a").bfe.agg(["min", "max", "nunique"])
multi = g[g["nunique"] > 1]
print(f"static-BFE buildings {len(sel)}: overlapping >1 distinct static BFE: {len(multi)} ({len(multi)/len(sel):.3%}); max-min spread quantiles ft {(multi['max']-multi['min']).quantile([.5,.9,1]).to_dict()}")
# largest-share BFE vs highest BFE: how many calls would change?
top = pr.sort_values("area", ascending=False).drop_duplicates("a").set_index("a").bfe
mm = multi.index
ch = b.loc[mm].assign(bfe_top=top.reindex(mm).values)
ffe = ch.ffe_ft.astype(float)
# record calls only (no band): above iff ffe >= bfe
rc = ch.ffe_class == "record"
flip = rc & (ffe >= ch.bfe_top) & (ffe < ch.bfe_ft)
print("record rows on multi-BFE buildings:", rc.sum(), "| called below under highest BFE but above under largest-share BFE:", flip.sum(),
      "| calls on multi-BFE buildings:", ch.bfe_call.value_counts(dropna=False).to_dict())
