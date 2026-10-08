import sys, re, numpy as np, pandas as pd, shapely, pyarrow.parquet as pq
from pyproj import Transformer
D = sys.argv[1]
b = pq.read_table(f"{D}/assemble/buildings_12103.parquet", columns=["building_id","lon","lat","zone_main","bfe_ft","bfe_method","bfe_source","bfe_vintage","bfe_band_lo","bfe_band_hi","bfe_call","firm_effective_date","zones"]).to_pandas()
ip = b[b.bfe_method == "interpolated"].copy()
print("interpolated rows", len(ip))
rx = re.compile(r": (BFE_LINE|XS) (\S+) ([-\d.]+) ft at (\d+) m; (BFE_LINE|XS) (\S+) ([-\d.]+) ft at (\d+) m")
m = ip.bfe_source.str.extract(rx)
m.columns = ["t1","l1","e1","d1","t2","l2","e2","d2"]
ip = pd.concat([ip, m], axis=1)
print("parsed", m.l1.notna().sum())
ip["dfirm"] = ip.bfe_source.str.extract(r"DFIRM (\w+) ")[0]
print("DFIRM of interpolated BFE:", ip.dfirm.value_counts().to_dict())
print("zone_main of interpolated:", ip.zone_main.value_counts().to_dict())
print("calls:", ip.bfe_call.value_counts(dropna=False).to_dict())
for c in ("d1","d2","e1","e2"): ip[c] = ip[c].astype(float)
print("distance to L1 (m) quantiles", ip.d1.quantile([.1,.5,.9,.99]).round(0).tolist(), "L2", ip.d2.quantile([.1,.5,.9,.99]).round(0).tolist())
print("|e1-e2| quantiles", (ip.e1-ip.e2).abs().quantile([.5,.9,.99,1]).round(2).tolist(), "n |e1-e2|>3 ft", int(((ip.e1-ip.e2).abs()>3).sum()))
print("same line both sides (d1==0):", int((ip.l1 == ip.l2).sum()))
print("type pairs:", (ip.t1 + "/" + ip.t2).value_counts().to_dict())
lines = pq.read_table(f"{D}/assemble/bfe_lines_12103.parquet").to_pandas()
lines = lines[lines.elev_ft_navd88_ft.notna()].reset_index(drop=True)
li = lines.set_index("line_id")
print("line ids unique:", li.index.is_unique)
ip["dfirm1"] = li.dfirm_id.reindex(ip.l1).values; ip["dfirm2"] = li.dfirm_id.reindex(ip.l2).values
ip["eff1"] = li.firm_panel_eff_date_max.reindex(ip.l1).values; ip["eff2"] = li.firm_panel_eff_date_max.reindex(ip.l2).values
print("pairs with lines from different DFIRMs:", int((ip.dfirm1 != ip.dfirm2).sum()), "; different panel eff dates:", int((ip.eff1 != ip.eff2).sum()))
print("line panel date vs the building's largest-share polygon panel date differ:", int((pd.to_datetime(ip.eff1).dt.strftime('%Y-%m-%d') != ip.firm_effective_date).sum()))
print(pd.crosstab(pd.to_datetime(ip.eff1).dt.strftime('%Y-%m-%d'), ip.firm_effective_date))
# straight segment between the two nearest points stays inside the SFHA union?
tr = Transformer.from_crs("EPSG:4326", "EPSG:3086", always_xy=True)
def proj(g): return shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])
lg = proj(shapely.from_wkb(lines.wkb.values)); lgi = pd.Series(lg, index=lines.line_id)
z = pq.read_table(f"{D}/assemble/zones_12103_raw.parquet", columns=["fld_zone","sfha_tf","wkb","static_bfe_navd88_ft","dfirm_id"]).to_pandas()
zg = proj(shapely.make_valid(shapely.from_wkb(z.wkb.values)))
sf = zg[(z.sfha_tf == "T").values]
shapely.prepare(sf)
tree = shapely.STRtree(sf)
cen = proj(shapely.points(ip.lon.values, ip.lat.values))
inside, n = 0, 0
cross_water = 0
rows = []
for i, (c, a, bb) in enumerate(zip(cen, ip.l1, ip.l2)):
    if a not in lgi.index or bb not in lgi.index: continue
    p1 = shapely.get_coordinates(shapely.shortest_line(c, lgi[a]))[1]
    p2 = shapely.get_coordinates(shapely.shortest_line(c, lgi[bb]))[1]
    seg = shapely.LineString([p1, p2]) if a != bb else shapely.LineString([shapely.get_coordinates(c)[0], p1])
    cand = tree.query(seg, predicate="intersects")
    cov = False
    if len(cand):
        u = shapely.union_all(sf[cand]) if len(cand) > 1 else sf[cand[0]]
        cov = bool(shapely.covered_by(seg, u))
    inside += cov; n += 1
    rows.append((ip.building_id.iloc[i], cov, seg.length))
r = pd.DataFrame(rows, columns=["building_id","seg_in_sfha","seg_len_m"])
print(f"segment L1->L2 covered by SFHA union: {inside} of {n} ({inside/n:.3f}); seg length median {r.seg_len_m.median():.0f} m p90 {r.seg_len_m.quantile(.9):.0f}")
out = ip.merge(r, on="building_id")
print("calls where segment leaves the SFHA:", out[~out.seg_in_sfha].bfe_call.value_counts(dropna=False).to_dict())
print("|e1-e2| where segment leaves SFHA, median:", round(float((out[~out.seg_in_sfha].e1 - out[~out.seg_in_sfha].e2).abs().median()),2), "vs inside:", round(float((out[out.seg_in_sfha].e1 - out[out.seg_in_sfha].e2).abs().median()),2))
# where are they: by rounded lat/lon cluster
out["cell"] = out.lat.round(2).astype(str) + "," + out.lon.round(2).astype(str)
print("top 10 0.01-deg cells of interpolated buildings:", out.cell.value_counts().head(10).to_dict())
out.drop(columns=["zones"]).to_parquet("interp_rows.parquet")
