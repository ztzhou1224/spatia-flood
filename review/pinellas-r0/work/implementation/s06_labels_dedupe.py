"""Re-run train/labels.py's selection on the FDEM public layer (fetched 2026-10-08, no owner fields) and measure
what the default na_position='last' sort does to 'latest certificate wins', plus same-date ties."""
import sys, numpy as np, pandas as pd, shapely
from pyproj import Transformer
D, F = sys.argv[1], sys.argv[2]
e0 = pd.read_parquet(F)
lab = pd.read_parquet(D + "/train/labels_12103.parquet")
b = pd.read_parquet(D + "/lidar/pinellas_2018/buildings.parquet")
g = shapely.from_wkb(b.wkb.values); x0, y0, x1, y1 = shapely.total_bounds(g)
tr = Transformer.from_crs("EPSG:4326", "EPSG:6442", always_xy=True)
gm = shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:, 0], xy[:, 1])])
LIVING_BOTTOM = ("1A", "1B", "5")
e = e0[(e0.verticalDatum == "navd_1988") & (e0.buildingUse == "residential") & e0.lon.between(x0, x1) & e0.lat.between(y0, y1)].copy()
print("fetched", len(e0), "in bbox residential navd88", len(e), "| issuedAt null", e.issuedAt.isna().sum(), "| r0 labels", len(lab), "with null issued_at", lab.issued_at.isna().sum())
print("r0 label OBJECTIDs present in today's fetch:", lab.cert_objectid.isin(e0.OBJECTID).sum())

def select(e, na_position, kind):
    e = e.sort_values("issuedAt", na_position=na_position, kind=kind).drop_duplicates("propertyId", keep="last").copy()
    dg = e.buildingDiagramNumber.astype(str).str.strip().str.upper(); e["diagram"] = dg
    e["ffe_ft"] = pd.to_numeric(np.where(dg.isin(LIVING_BOTTOM), e.topOfBottomFloor, np.where(dg.str[0].isin(list("2346789")), e.topOfNextHigherFloor, np.nan)), errors="coerce")
    e = e[e.ffe_ft.between(-20, 200)].reset_index(drop=True)
    ex, ey = tr.transform(e.lon.values, e.lat.values); pts = shapely.points(ex, ey)
    tree = shapely.STRtree(gm); pi, fi = tree.query(pts, predicate="within")
    match = np.full(len(e), -1); match[pi[::-1]] = fi[::-1]
    rest = np.where(match < 0)[0]
    ri, rf = tree.query_nearest(pts[rest], max_distance=10, return_distance=False, all_matches=False)
    match[rest[ri]] = rf
    e["building_id"] = np.where(match >= 0, b.building_id.values[np.maximum(match, 0)], None)
    m = e[e.building_id.notna()]
    cands = m  # all matched certificates before the per-building dedupe
    out = m.sort_values("issuedAt", na_position=na_position, kind=kind).drop_duplicates("building_id", keep="last")
    return out.set_index("building_id"), cands

cur, cands = select(e, "last", "quicksort")   # labels.py as written
fix, _ = select(e, "first", "stable")          # undated certificates lose; stable tie order
print("\nreplication of labels.py today: labels", len(cur), "| same cert as r0 label for the same building:", int((cur.OBJECTID.reindex(lab.building_id).values == lab.cert_objectid.values).sum()), "of", len(lab))
# (a) undated certificate kept although a dated one exists for the same building
grp = cands.groupby("building_id").issuedAt.agg(["size", "count"])  # size = certificates, count = dated ones
multi = grp[grp["size"] > 1]
print("buildings with >1 matched certificate:", len(multi))
undated_kept = cur.loc[multi.index].issuedAt.isna() & (multi["count"] > 0)
print("(a) buildings where labels.py keeps an UNDATED certificate although a dated one exists:", int(undated_kept.sum()))
# same at the property stage
pg = e.groupby("propertyId").issuedAt.agg(["size", "count"]); pm = pg[(pg["size"] > 1) & (pg["count"] > 0)]
kept_prop = e.sort_values("issuedAt").drop_duplicates("propertyId", keep="last").set_index("propertyId")
print("    at the propertyId stage: properties with >1 cert of which >=1 dated:", len(pm), "| undated one kept:", int(kept_prop.loc[pm.index].issuedAt.isna().sum()))
# (b) do kept certificates differ between the as-written rule and the fixed rule?
common = cur.index.intersection(fix.index)
diff = cur.loc[common].OBJECTID != fix.loc[common].OBJECTID
print("(b) buildings whose chosen certificate changes with na_position='first' + stable sort:", int(diff.sum()), "| of which ffe_ft changes:", int(((cur.loc[common].ffe_ft - fix.loc[common].ffe_ft).abs() > 0.01)[diff].sum()))
dd = (cur.loc[common].ffe_ft - fix.loc[common].ffe_ft)[diff]
print("    ffe difference quantiles (as-written minus fixed):", dd.abs().quantile([.5, .9, 1]).round(2).to_dict())
# (c) exact same-date ties among a building's candidates
ties = cands.groupby(["building_id", "issuedAt"]).size()
tb = ties[ties > 1].reset_index().building_id.nunique()
print("(c) buildings with >=2 candidate certificates on the SAME issuedAt:", tb)
t2 = cands[cands.duplicated(["building_id", "issuedAt"], keep=False) & cands.issuedAt.notna()]
spread = t2.groupby("building_id").ffe_ft.agg(lambda s: s.max() - s.min())
print("    of which the tied certificates disagree on ffe by >0.1 ft:", int((spread > 0.1).sum()), "| >1 ft:", int((spread > 1).sum()))
# which cert the as-written code picks among a tie: compare quicksort vs mergesort
cur2, _ = select(e, "last", "mergesort")
print("    chosen certificate differs between quicksort and mergesort (same rule):", int((cur.loc[common].OBJECTID != cur2.loc[common].OBJECTID).sum()))
# (d) in the r0 labels themselves: how many undated labels sit on buildings that today have a dated certificate
r0 = lab.set_index("building_id")
und = r0[r0.issued_at.isna()].index
has_dated = cands[cands.building_id.isin(und) & cands.issuedAt.notna()].building_id.nunique()
print("(d) r0 labels with null issued_at:", len(und), "| of these buildings, with a DATED residential NAVD88 certificate in today's FDEM layer:", has_dated)
# and did the r0 label on those buildings end up as record ffe in the layer?
bl = pd.read_parquet(D + "/assemble/buildings_12103.parquet", columns=["building_id", "ffe_class", "ffe_ft", "record_vintage_note", "bfe_call"]).set_index("building_id")
und_dated = cands[cands.building_id.isin(und) & cands.issuedAt.notna()].building_id.unique()
x = bl.loc[und_dated]
print("    those buildings in the layer: ffe_class", x.ffe_class.value_counts(dropna=False).to_dict(), "bfe_call", x.bfe_call.value_counts(dropna=False).to_dict())
alt = cands[cands.building_id.isin(und_dated) & cands.issuedAt.notna()].sort_values("issuedAt").drop_duplicates("building_id", keep="last").set_index("building_id")
dv = (x.ffe_ft - alt.ffe_ft.reindex(x.index))
print("    record ffe (undated cert) minus latest DATED cert ffe: |d|>0.1 ft:", int((dv.abs() > 0.1).sum()), "| >1 ft:", int((dv.abs() > 1).sum()), "| quantiles", dv.abs().quantile([.5, .9, 1]).round(2).to_dict())
