import sys, numpy as np, pandas as pd, shapely
from pyproj import Transformer
P, B, L = sys.argv[1:4]
e0 = pd.read_parquet(P)                      # untrusted cached FDEM pull (bbox, residential navd88 per the fetcher)
b = pd.read_parquet(B); lab = pd.read_parquet(L)
g = shapely.from_wkb(b.wkb.values); x0,y0,x1,y1 = shapely.total_bounds(g)
tr = Transformer.from_crs("EPSG:4326","EPSG:6442",always_xy=True)
gm = shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:,0],xy[:,1])])
e = e0[(e0.verticalDatum=="navd_1988")&(e0.buildingUse=="residential")&e0.lon.between(x0,x1)&e0.lat.between(y0,y1)].copy()
print("cached rows", len(e0), "after filter", len(e), "issuedAt null", e.issuedAt.isna().sum())
dg = e.buildingDiagramNumber.astype(str).str.strip().str.upper()
e["ffe_ft"] = pd.to_numeric(np.where(dg.isin(("1A","1B","5")), e.topOfBottomFloor, np.where(dg.str[0].isin(list("2346789")), e.topOfNextHigherFloor, np.nan)), errors="coerce")
e = e[e.ffe_ft.between(-20,200)].copy()
# match every certificate to a building (before any dedupe) so the per-building candidate set is complete
ex,ey = tr.transform(e.lon.values,e.lat.values); pts=shapely.points(ex,ey); tree=shapely.STRtree(gm)
pi,fi = tree.query(pts,predicate="within"); match=np.full(len(e),-1); match[pi[::-1]]=fi[::-1]
rest=np.where(match<0)[0]
if len(rest):
    ri,rf=tree.query_nearest(pts[rest],max_distance=10,return_distance=False,all_matches=False); match[rest[ri]]=rf
e["building_id"]=np.where(match>=0,b.building_id.values[np.maximum(match,0)],None)
def select(df, **kw):   # labels.py rule, with optional overrides
    s = df.sort_values("issuedAt", **kw).drop_duplicates("propertyId", keep="last")
    s = s[s.building_id.notna()].sort_values("issuedAt", **kw).drop_duplicates("building_id", keep="last")
    return s.set_index("building_id")
asw = select(e); st = select(e, na_position="first", kind="stable")
print("as-written labels", len(asw), "| r0 labels", len(lab), "| same OBJECTID as r0 for same building:", (asw.OBJECTID.reindex(lab.building_id).values==lab.cert_objectid.values).sum(), "of", len(lab))
cand = e[e.building_id.notna()]
multi = cand.groupby("building_id").OBJECTID.nunique(); multi = multi[multi>1]
print("buildings with >1 matched certificate:", len(multi))
has_dated = cand[cand.issuedAt.notna()].groupby("building_id").size()
undated_kept = asw[asw.issuedAt.isna()]
a = undated_kept.index.isin(has_dated.index)
print("(a) buildings where as-written keeps an UNDATED cert while a dated candidate exists:", int(a.sum()))
# property stage
pc = e.groupby("propertyId").agg(n=("OBJECTID","size"), dated=("issuedAt", lambda s: s.notna().sum()))
pk = e.sort_values("issuedAt").drop_duplicates("propertyId", keep="last").set_index("propertyId")
print("(a') properties with a dated sibling where an undated cert is kept:", int(((pk.issuedAt.isna()) & (pc.loc[pk.index].dated>0)).sum()), "of", int((pc.dated>0).sum() - 0), "properties")
ties = cand.groupby(["building_id","issuedAt"]).OBJECTID.nunique(); ties = ties[ties>1]
print("(c) buildings with >=2 candidates on the same issuedAt:", ties.reset_index().building_id.nunique())
j = asw.join(st, lsuffix="_q", rsuffix="_s", how="inner")
print("chosen certificate differs as-written vs na_first+stable:", int((j.OBJECTID_q!=j.OBJECTID_s).sum()), "| ffe differs >0.1 ft:", int(((j.ffe_ft_q-j.ffe_ft_s).abs()>0.1).sum()))
ms = select(e, kind="mergesort")
j2 = asw.join(ms, lsuffix="_q", rsuffix="_m", how="inner")
print("quicksort vs mergesort (same rule): differs", int((j2.OBJECTID_q!=j2.OBJECTID_m).sum()))
