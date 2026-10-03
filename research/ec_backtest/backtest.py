import json,re,numpy as np
from collections import Counter
from sklearn.neighbors import BallTree
R=json.load(open("ec_all.json"))
def norm(a): return re.sub(r"[^0-9A-Z]","",(a or "").upper())[:40]
rows={}
drop=Counter()
for r in R:
    if r["verticalDatum"]!="navd_1988": drop["datum"]+=1; continue
    if r["buildingUse"]!="residential": drop["use"]+=1; continue
    if r["buildingElevationSource"]!="finished_construction": drop["notfinished"]+=1; continue
    if r["floodZone"] not in ("AE","AH","A"): drop["zone"]+=1; continue
    if r["buildingDiagramNumber"] not in ("1A","1B","5","6","7","8"): drop["diagram"]+=1; continue
    f,l,b=r["topOfBottomFloor"],r["lowestAdjacentGrade"],r["baseFloodElevation"]
    if None in (f,l,b) or r["lon"] is None: drop["missing"]+=1; continue
    if not (-5<l<60 and l-3<=f<=l+25 and abs(f-b)<15 and 0<b<40): drop["implausible"]+=1; continue
    key=r["propertyId"] or norm(r["streetAddress"])
    if key in rows and (rows[key]["issuedAt"] or 0)>=(r["issuedAt"] or 0): drop["dup"]+=1; continue
    rows[key]=r
D=list(rows.values()); print("kept",len(D),"dropped",dict(drop))
lat=np.radians([r["lat"] for r in D]); lon=np.radians([r["lon"] for r in D])
F=np.array([r["topOfBottomFloor"] for r in D]); L=np.array([r["lowestAdjacentGrade"] for r in D]); B=np.array([r["baseFloodElevation"] for r in D])
addr=[norm(r["streetAddress"]) for r in D]; diag=np.array([r["buildingDiagramNumber"] for r in D])
d=F-B; fh=F-L
print("truth floor-BFE: median %.2f, p10 %.2f, p90 %.2f, share >=0: %.1f%%"%(np.median(d),*np.percentile(d,[10,90]),100*np.mean(d>=0)))
tree=BallTree(np.c_[lat,lon],metric="haversine")
K=8; dist,idx=tree.query(np.c_[lat,lon],k=K+6)
dist=dist*6371000
def metrics(name,err,mask,pred_d=None):
    e=err[mask]; s="%-46s n=%6d cover=%5.1f%%  MAE=%.2f ft  RMSE=%.2f  |err|<=1ft %5.1f%%  <=2ft %5.1f%%"%(name,mask.sum(),100*mask.mean(),np.mean(np.abs(e)),np.sqrt(np.mean(e**2)),100*np.mean(np.abs(e)<=1),100*np.mean(np.abs(e)<=2))
    if pred_d is not None:
        t=d[mask]>=0; p=pred_d[mask]>=0
        conf=pred_d[mask]>=1  # predicted clearly above
        s+="  side-correct %5.1f%%"%(100*np.mean(t==p))
        if conf.sum(): s+="  'above by>=1ft' precision %5.1f%% (n=%d)"%(100*np.mean(d[mask][conf]>=0),conf.sum())
    print(s)
# baseline: floor at BFE
allm=np.ones(len(D),bool)
metrics("B0 floor = BFE (code minimum)",-d,allm,np.zeros(len(D)))
for R_m,k in [(150,3),(300,5),(500,5),(1000,8)]:
    pd_=np.full(len(D),np.nan); pf=np.full(len(D),np.nan); nd=np.full(len(D),np.nan)
    for i in range(len(D)):
        nb=[j for j,dd in zip(idx[i],dist[i]) if j!=i and dd<=R_m and addr[j]!=addr[i]][:k]
        if len(nb)>=min(3,k):
            pd_[i]=np.median(d[nb]); pf[i]=L[i]+np.median(fh[nb]); nd[i]=dist[i][list(idx[i]).index(nb[0])]
    m=~np.isnan(pd_)
    metrics(f"B1 kNN median(floor-BFE), k={k}, r<={R_m}m",pd_-d,m,pd_)
    metrics(f"B2 own LAG + kNN median(floor-LAG), r<={R_m}m",pf-F,m,pf-B)
    if R_m==300:
        for lo,hi in [(0,50),(50,150),(150,300)]:
            mm=m&(nd>=lo)&(nd<hi)
            metrics(f"   B1 nearest neighbour {lo}-{hi} m",pd_-d,mm,pd_)
        for dg in ["1A","1B","5","6","7","8"]:
            mm=m&(diag==dg)
            if mm.sum()>200: metrics(f"   B1 diagram {dg}",pd_-d,mm,pd_)
        np.save("b1_300.npy",pd_)
