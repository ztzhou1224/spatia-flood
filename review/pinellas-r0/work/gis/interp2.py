import sys, numpy as np, pandas as pd, shapely, pyarrow.parquet as pq
from pyproj import Transformer
D = sys.argv[1]
ip = pd.read_parquet("interp_rows.parquet")
lines = pq.read_table(f"{D}/assemble/bfe_lines_12103.parquet").to_pandas(); lines = lines[lines.elev_ft_navd88_ft.notna()].reset_index(drop=True)
tr = Transformer.from_crs("EPSG:4326", "EPSG:3086", always_xy=True)
def proj(g): return shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])
lgi = pd.Series(proj(shapely.from_wkb(lines.wkb.values)), index=lines.line_id)
z = pq.read_table(f"{D}/assemble/zones_12103_raw.parquet", columns=["fld_zone","sfha_tf","wkb"]).to_pandas()
zg = proj(shapely.make_valid(shapely.from_wkb(z.wkb.values)))
sf = shapely.union_all(zg[(z.sfha_tf == "T").values])
shapely.prepare(sf)
cen = proj(shapely.points(ip.lon.values, ip.lat.values))
outs = []
for c, a, bb in zip(cen, ip.l1, ip.l2):
    p1 = shapely.get_coordinates(shapely.shortest_line(c, lgi[a]))[1]; p2 = shapely.get_coordinates(shapely.shortest_line(c, lgi[bb]))[1]
    seg = shapely.LineString([p1, p2])
    outs.append(1 - shapely.intersection(seg, sf).length / seg.length if seg.length > 0 else 0)
o = np.array(outs)
print("share of L1->L2 segment length OUTSIDE the SFHA: quantiles 50/75/90/99", np.round(np.quantile(o, [.5,.75,.9,.99]),3).tolist(), "; n with >25% outside", int((o > .25).sum()), "; n with >50% outside", int((o > .5).sum()), "of", len(o))
ip["out_share"] = o
print("calls where >25% outside:", ip[o > .25].bfe_call.value_counts(dropna=False).to_dict())
print("|e1-e2| where >25% outside: median", round(float((ip[o > .25].e1 - ip[o > .25].e2).abs().median()),2), "p90", round(float((ip[o > .25].e1 - ip[o > .25].e2).abs().quantile(.9)),2))
