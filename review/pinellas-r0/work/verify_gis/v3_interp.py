import sys, re, numpy as np, pandas as pd, shapely, pyarrow.parquet as pq
from pyproj import Transformer
D = sys.argv[1]
b = pq.read_table(f"{D}/assemble/buildings_12103.parquet", columns=["building_id","lon","lat","bfe_method","bfe_source","bfe_call","firm_effective_date","zone_main"]).to_pandas()
ip = b[b.bfe_method == "interpolated"].reset_index(drop=True)
print("interpolated rows:", len(ip), "zone_main:", ip.zone_main.value_counts().to_dict())
m = ip.bfe_source.str.extract(r"(BFE_LINE|XS) (\S+) ([-\d.]+) ft at (\d+) m; (BFE_LINE|XS) (\S+) ([-\d.]+) ft at (\d+) m")
m.columns = ["t1","l1","e1","d1","t2","l2","e2","d2"]; ip = pd.concat([ip, m], axis=1)
print("parsed:", int(m.l1.notna().sum()))
for k in ("e1","e2","d1","d2"): ip[k] = ip[k].astype(float)
print("|e1-e2| median/p90/n>3:", round(float((ip.e1-ip.e2).abs().median()),2), round(float((ip.e1-ip.e2).abs().quantile(.9)),2), int(((ip.e1-ip.e2).abs()>3).sum()))
lines = pq.read_table(f"{D}/assemble/bfe_lines_12103.parquet").to_pandas()
li = lines.set_index("line_id"); print("line_id unique:", li.index.is_unique, "lines:", len(lines))
eff1 = pd.to_datetime(li.firm_panel_eff_date_max.reindex(ip.l1).values); eff2 = pd.to_datetime(li.firm_panel_eff_date_max.reindex(ip.l2).values)
print("pairs with different panel dates:", int((eff1 != eff2).sum()), "; L1 panel date != building polygon panel date:", int((eff1.strftime('%Y-%m-%d') != ip.firm_effective_date.values).sum()))
# my own geometry: UTM 17N metres (reviewer used EPSG:3086); dissolved SFHA union; fraction of segment inside
tr = Transformer.from_crs("EPSG:4326", "EPSG:26917", always_xy=True)
def proj(g): return shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])
lg = pd.Series(proj(shapely.from_wkb(lines.wkb.values)), index=lines.line_id)
z = pq.read_table(f"{D}/assemble/zones_12103_raw.parquet", columns=["sfha_tf","wkb"]).to_pandas()
sf = shapely.union_all(proj(shapely.make_valid(shapely.from_wkb(z.wkb.values[(z.sfha_tf=="T").values]))))
shapely.prepare(sf)
cen = proj(shapely.points(ip.lon.values, ip.lat.values))
frac, seglen, d1chk = [], [], []
for c, a, bb, d1 in zip(cen, ip.l1, ip.l2, ip.d1):
    p1 = shapely.get_coordinates(shapely.shortest_line(c, lg[a]))[1]; p2 = shapely.get_coordinates(shapely.shortest_line(c, lg[bb]))[1]
    d1chk.append(abs(shapely.distance(c, lg[a]) - d1))
    seg = shapely.LineString([p1, p2]); L = seg.length
    frac.append(shapely.intersection(seg, sf).length / L if L > 0 else 1.0); seglen.append(L)
f = np.array(frac); L = np.array(seglen)
print("distance-to-L1 recomputed vs bfe_source: max abs diff m", round(float(np.max(d1chk)),2))
print("segment L1->L2 length median m:", round(float(np.median(L)),0))
for thr in (0.999, 0.99, 0.95):
    print(f"segments with >= {thr:.3f} of length inside SFHA union: {(f>=thr).sum()} of {len(f)} ({(f>=thr).mean():.3f})")
print("segments with > 25% outside:", int((f < .75).sum()), "; > 50% outside:", int((f < .5).sum()))
ip["frac_in"] = f
print("|e1-e2| median where <75% inside:", round(float((ip[f<.75].e1-ip[f<.75].e2).abs().median()),2), "where fully inside:", round(float((ip[f>=.999].e1-ip[f>=.999].e2).abs().median()),2))
print("calls where <75% inside:", ip[f<.75].bfe_call.value_counts(dropna=False).to_dict())
