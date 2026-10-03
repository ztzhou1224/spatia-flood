import numpy as np, pyarrow.parquet as pq, re
from sklearn.neighbors import BallTree
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import GroupKFold
T=pq.read_table("ec_joined.parquet").to_pylist()
T=[r for r in T if r["dor_uc"]=="001" and r["act_yr_blt"] and 1900<r["act_yr_blt"]<=2026]
P=[r["act_yr_blt"] for r in pq.read_table("pop_years.parquet").to_pylist() if r["act_yr_blt"] and 1900<r["act_yr_blt"]<=2026]
n=len(T); print("single-family certificates with year built:",n,"| neighbourhood SF parcels:",len(P))
yr=np.array([r["act_yr_blt"] for r in T]); P=np.array(P)
eras=[(1900,1974,"before 1975"),(1975,1989,"1975-1989"),(1990,2001,"1990-2001"),(2002,2011,"2002-2011"),(2012,2026,"2012+")]
def era(y): return next(i for i,(a,b,_) in enumerate(eras) if a<=y<=b)
E=np.array([era(y) for y in yr]); PE=np.array([era(y) for y in P])
print("\nshare by era:   certificates  vs  all single-family homes in the same neighbourhoods")
for i,(_,_,lab) in enumerate(eras): print(f"  {lab:12s}  {100*np.mean(E==i):5.1f}%   {100*np.mean(PE==i):5.1f}%")
F=np.array([r["topOfBottomFloor"] for r in T]); L=np.array([r["lowestAdjacentGrade"] for r in T]); B=np.array([r["baseFloodElevation"] for r in T])
d=F-B; fh=F-L
lat=np.radians([r["lat"] for r in T]); lon=np.radians([r["lon"] for r in T])
addr=[re.sub(r"[^0-9A-Z]","",(r["streetAddress"] or "").upper()) for r in T]
tree=BallTree(np.c_[lat,lon],metric="haversine"); K=30
dist,idx=tree.query(np.c_[lat,lon],k=K); dist*=6371000
# neighbour features (leave-one-out, same address excluded)
feat=np.full((n,12),np.nan); b1=np.full(n,np.nan); b2=np.full(n,np.nan)
for i in range(n):
    ok=[(j,dd) for j,dd in zip(idx[i],dist[i]) if j!=i and addr[j]!=addr[i]]
    js=np.array([j for j,_ in ok]); ds=np.array([dd for _,dd in ok])
    w300=js[ds<=300][:5]
    if len(w300)>=3: b1[i]=np.median(d[w300]); b2[i]=np.median(fh[w300])
    k5=js[:5]; same=js[(np.abs(yr[js]-yr[i])<=5)][:5]
    feat[i]=[np.median(d[k5]),np.median(fh[k5]),np.std(d[k5]),ds[0],d[js[0]],fh[js[0]],
             np.median(d[same]) if len(same) else np.nan, np.median(fh[same]) if len(same) else np.nan,
             (ds<=150).sum(),(ds<=500).sum(),np.median(yr[k5]),np.average(d[js[:10]],weights=1/(ds[:10]+10))]
cov=~np.isnan(b1)
def rep(name,pred_d,mask,w=None):
    e=pred_d[mask]-d[mask]; s=dict(MAE=np.average(np.abs(e),weights=w), w1=np.average(np.abs(e)<=1,weights=w), side=np.average((pred_d[mask]>=0)==(d[mask]>=0),weights=w))
    print(f"  {name:44s} n={mask.sum():6d}  MAE={s['MAE']:.2f} ft  within 1 ft {100*s['w1']:5.1f}%  above/below right {100*s['side']:5.1f}%")
rng=np.random.default_rng(0); g_lidar=L+rng.normal(0,0.33,n)
if 0: print("\n== Neighbour medians (5 within 300 m), by the house's year built ==")
for i,(_,_,lab) in ([] ):
    m=cov&(E==i)
    if m.sum()<100: continue
    print(f" {lab}:"); rep("B1 neighbours' floor-vs-BFE",b1,m); rep("B2 lidar-grade ground + neighbours' floor height",g_lidar+b2-B,m)
# reweight to the neighbourhood population's era mix
wE=np.array([np.mean(PE==i)/max(np.mean(E[cov]==i),1e-9) for i in range(len(eras))])
if 0: print("\n== All eras, reweighted to the real housing stock's age mix ==")
0 and rep("B1 (reweighted)",b1,cov,wE[E[cov]]); rep("B2 lidar-grade (reweighted)",g_lidar+b2-B,cov,wE[E[cov]])
