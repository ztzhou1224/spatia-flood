import numpy as np, pandas as pd, shapely, pyarrow.parquet as pq
from pyproj import Transformer
OUT="/home/user/spatia-flood/data/flood_v1/assemble"; ALBERS, LINE_SEARCH_M, BFE_ROUND_FT = "EPSG:3086", 1000.0, 0.5
tr=Transformer.from_crs("EPSG:4326",ALBERS,always_xy=True); proj=lambda g: shapely.transform(g, lambda xy: np.c_[tr.transform(xy[:,0],xy[:,1])])
z=pd.read_parquet(f"{OUT}/zones_12103_raw.parquet"); zg=proj(shapely.make_valid(shapely.from_wkb(z.wkb.map(bytes).values)))
lines=pd.read_parquet(f"{OUT}/bfe_lines_12103.parquet"); lines=lines[lines.elev_ft_navd88_ft.notna()].reset_index(drop=True).rename(columns={"elev_ft_navd88_ft":"elev"}); lg=proj(shapely.from_wkb(lines.wkb.map(bytes).values))
b=pq.read_table(f"{OUT}/buildings_12103.parquet",columns=["building_id","touches_sfha","bfe_method","bfe_ft","bfe_call","ffe_class","geometry"]).to_pandas()
sel=np.where((b.bfe_method=="static").values & b.touches_sfha.fillna(False).values.astype(bool))[0]
ga=proj(shapely.from_wkb(b.geometry.values[sel])); cen=shapely.centroid(ga)
sf=np.where(z.sfha_tf.values=="T")[0]
bi,pi=shapely.STRtree(zg[sf]).query(ga,predicate="intersects")
polys_of={}
for a_,p_ in zip(bi,sf[pi]): polys_of.setdefault(int(a_),set()).add(int(p_))
# M9: distinct static BFEs overlapped per static building
sb=pd.DataFrame({"a":bi,"bfe":z.static_bfe_navd88_ft.values[sf[pi]]}).dropna()
nd=sb.groupby("a").bfe.agg(["nunique","min","max"]); multi=nd[nd["nunique"]>1]
print("M9 static buildings:",len(sel),"| overlapping >1 distinct static BFE:",len(multi),"| spread median/max:",(multi["max"]-multi["min"]).median(),(multi["max"]-multi["min"]).max())
bb=b.iloc[sel].reset_index(drop=True); mm=bb.loc[multi.index]
print("   record rows called below under max BFE that would be above under min BFE (upper bound, polygon share unknown):", int(((mm.ffe_class=="record")&(mm.bfe_call=="below")&(bb.loc[multi.index].bfe_ft.notna())&(pd.Series(multi["min"].values,index=multi.index) <= bb.loc[multi.index].bfe_ft) ).sum()))
need=sorted({q for ps in polys_of.values() for q in ps}); li,pi2=shapely.STRtree(lg).query(zg[need],predicate="intersects")
by_poly={}
for k,j in zip(np.asarray(need)[li],pi2): by_poly.setdefault(int(k),set()).add(int(j))
rows=[]
for a,ps in polys_of.items():
    cand=sorted(set().union(*(by_poly.get(q,set()) for q in ps))); c=cen[a]
    if cand:
        d=shapely.distance(c,lg[cand]); keep=d<=LINE_SEARCH_M; cand,d=np.asarray(cand)[keep],d[keep]
    if not len(cand): continue
    near=shapely.get_coordinates(shapely.shortest_line(c,lg[cand]))[1::2]-shapely.get_coordinates(c); o=np.argsort(d); i1=o[0]; e1=lines.elev.values[cand[i1]]
    if d[i1]==0: i2,e2,f=i1,e1,0.0
    else:
        opp=[k for k in o[1:] if d[k]>0 and near[k]@near[i1]<0]
        if not opp: continue
        i2=opp[0]; e2=lines.elev.values[cand[i2]]; f=d[i1]/(d[i1]+d[i2])
    rows.append(dict(a=a,bfe=e1+(e2-e1)*f,lo=min(e1,e2)-BFE_ROUND_FT,hi=max(e1,e2)+BFE_ROUND_FT,e1=e1,e2=e2,t1=lines.source_type.values[cand[i1]],t2=lines.source_type.values[cand[i2]]))
chk=pd.DataFrame(rows); st=bb.bfe_ft.values[chk.a.values]; err=chk.bfe.values-st
print("M4 check reproduced: n",len(chk),"MAE",round(np.abs(err).mean(),3),"within1",round((np.abs(err)<=1).mean(),3),"inside band",round(((st>=chk.lo-1e-9)&(st<=chk.hi+1e-9)).mean(),3))
print("   pair types:",(chk.t1+"/"+chk.t2).value_counts().to_dict(),"| |e1-e2| median",round((chk.e1-chk.e2).abs().median(),2))
en=chk.e1.values-st; print("   nearest-line MAE",round(np.abs(en).mean(),3),"linear better/worse/tie:",int((np.abs(err)<np.abs(en)-1e-9).sum()),int((np.abs(err)>np.abs(en)+1e-9).sum()),int((np.abs(np.abs(err)-np.abs(en))<=1e-9).sum()))
bl=chk[(chk.t1=="BFE_LINE")&(chk.t2=="BFE_LINE")]; print("   BFE_LINE/BFE_LINE pairs:",len(bl),"errors:",np.round(bl.bfe.values-st[bl.index],2).tolist())
