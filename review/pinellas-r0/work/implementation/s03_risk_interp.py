import sys, json
import numpy as np, pandas as pd, shapely, geopandas as gpd
sys.path.insert(0, "/home/user/spatia-flood/pipeline/assemble")
import os; os.environ.setdefault("CLOUDFLARE_R2_ENDPOINT","https://x")
D = sys.argv[1]
b = gpd.read_parquet(D+"/assemble/buildings_12103.parquet")
print("=== in_risk_area vs risk polygon")
r = pd.read_parquet(D+"/risk_12103.parquet")
print("risk parquet cols", list(r.columns), len(r))
rg = shapely.from_wkb(r.geom.iloc[0]) if r.geom.dtype == object else None
if rg is None: rg = shapely.from_wkb(bytes(r.geom.iloc[0]))
print("risk geom type", rg.geom_type, "valid", rg.is_valid)
shapely.prepare(rg)
cen = shapely.centroid(b.geometry.values)
inr = shapely.intersects(rg, cen)
print("centroid in risk polygon:", int(inr.sum()), "| in_risk_area:", int(b.in_risk_area.sum()))
print("in polygon but in_risk_area False:", int((inr & ~b.in_risk_area.values).sum()), "| in_risk_area True but centroid outside polygon:", int((~inr & b.in_risk_area.values).sum()))
# centroid vs published lon/lat: lon/lat column == centroid?
print("lon/lat col == centroid max diff:", np.abs(b.lon.values - shapely.get_x(cen)).max(), np.abs(b.lat.values - shapely.get_y(cen)).max())
# centroid outside footprint
print("centroid outside own footprint:", int((~shapely.contains(b.geometry.values, cen)).sum()))
print("invalid footprints:", int((~shapely.is_valid(b.geometry.values)).sum()))
d = pd.DataFrame({"in_poly": inr, "in_risk": b.in_risk_area.values, "ffh_null": b.ffh_null.fillna("<value>").values, "ground_null": b.ground_null.fillna("<value>").values})
print(d.groupby(["in_poly","in_risk","ground_null"]).size().to_string())

print("\n=== BFE line interpolation: recompute from cached inputs")
from assemble import interpolate_bfe, overlay, projected, ALBERS, LINE_SEARCH_M
z = pd.read_parquet(D+"/assemble/zones_12103_raw.parquet")
zg = projected(shapely.make_valid(shapely.from_wkb(z.wkb.map(bytes).values)), ALBERS)
ga = projected(b.geometry.values, ALBERS)
pr = overlay(ga, zg)
pr["sfha"] = (z.sfha_tf.values[pr.p] == "T")
lines = pd.read_parquet(D+"/assemble/bfe_lines_12103.parquet")
print("lines", len(lines), "elev null", lines.elev_ft_navd88_ft.isna().sum(), "eff null", lines.firm_panel_eff_date_max.isna().sum(), "source_type", lines.source_type.value_counts().to_dict(), "status", lines.elev_ft_navd88_status.value_counts().to_dict(), "elev range", lines.elev_ft_navd88_ft.min(), lines.elev_ft_navd88_ft.max())
lines = lines[lines.elev_ft_navd88_ft.notna()].reset_index(drop=True).rename(columns={"elev_ft_navd88_ft":"elev","elev_ft_navd88_status":"status","firm_panel_eff_date_max":"eff"})
lg = projected(shapely.from_wkb(lines.wkb.map(bytes).values), ALBERS)
cen_a = shapely.centroid(ga)
sp = pr[pr.sfha]
todo = set(np.where(b.bfe_method.values == "interpolated")[0]) | set(np.where((b.bfe_null.isin(["no_coverage","not_determinable"])).values & b.touches_sfha.values)[0])
polys_of = {int(k): set(v) for k, v in sp[sp.a.isin(todo)].groupby("a").p}
ip = interpolate_bfe(cen_a, polys_of, zg, lines, lg).set_index("a")
print("tried", len(ip), "interpolated", ip.bfe.notna().sum(), "null", ip["null"].value_counts().to_dict())
st = b.iloc[ip.index]
dd = (ip.bfe.values - st.bfe_ft.values)
isi = st.bfe_method.values == "interpolated"
print("stored interpolated:", isi.sum(), "| recomputed bfe differs > 1e-6:", int((np.abs(dd[isi]) > 1e-6).sum()), "| recomputed null where stored interpolated:", int((np.isnan(ip.bfe.values) & isi).sum()))
print("band lo/hi mismatch:", int((np.abs(ip.lo.values[isi]-st.bfe_band_lo.values[isi])>1e-6).sum()), int((np.abs(ip.hi.values[isi]-st.bfe_band_hi.values[isi])>1e-6).sum()))
print("null reasons recomputed vs stored:", pd.crosstab(ip["null"].fillna("<bfe>"), st.bfe_null.fillna("<bfe>").values))
# interpolation sanity: band width, bfe outside [min,max] of lines
print("interp bfe outside its band:", int((isi & ((st.bfe_ft.values < st.bfe_band_lo.values) | (st.bfe_ft.values > st.bfe_band_hi.values))).sum()))
w = (st.bfe_band_hi - st.bfe_band_lo)[isi]
print("band width quantiles", w.quantile([0, .5, .9, 1]).round(2).to_dict(), "| >5 ft:", int((w > 5).sum()))
# A-zone only buildings with interpolated BFE
print("interpolated with zone_main A:", int((isi & (st.zone_main.values=="A")).sum()), " zones for these:", [z for z in st.zones.values[isi & (st.zone_main.values=="A")][:3]])

print("\n=== addresses ending with ','")
print(b.address[b.address.fillna("").str.endswith(",")].str.replace(r"^\d+ ", "N ", regex=True).tolist())
print("=== OSM licence tag present on OSM-sourced rows:", int(b[b.address_source.fillna("").str.contains("OpenStreetMap")].input_licences.map(lambda l: "openstreetmap:ODbL-1.0" in list(l)).sum()), "of", int(b.address_source.fillna("").str.contains("OpenStreetMap").sum()))
print("licence tag counts:", pd.Series([x for l in b.input_licences for x in l]).value_counts().to_dict())

print("\n=== parcel table")
p = pd.read_parquet(D+"/assemble/parcels_12103.parquet")
print("rows", len(p), "unique parcel_key", p.parcel_key.is_unique, "cols", list(p.columns))
print("buildings sum", p.buildings.sum(), "| any_below", p.any_building_below_bfe.sum(), "| below sum", p.below.sum(), "| buildings with below call", int((b.bfe_call=="below").sum()))
print("parcel_key in b not in p:", int((~b.parcel_key.dropna().isin(p.parcel_key)).sum()))
print("geom_group sizes top:", p.geom_group.value_counts().head(3).to_dict())
print("primary_building_id null with buildings>0:", int((p.primary_building_id.isna() & (p.buildings>0)).sum()))
