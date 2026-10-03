exec(open("backtest.py").read().split("tree=BallTree")[0])
tree=BallTree(np.c_[lat,lon],metric="haversine")
dist,idx=tree.query(np.c_[lat,lon],k=14); dist*=6371000
rng=np.random.default_rng(0)
def nbrs(i,R_m=300,k=5,min_m=0):
    return [j for j,dd in zip(idx[i],dist[i]) if j!=i and min_m<=dd<=R_m and addr[j]!=addr[i]][:k]
pd_={};pfh={}
for min_m in (0,15):
    a=np.full(len(D),np.nan); b=np.full(len(D),np.nan)
    for i in range(len(D)):
        nb=nbrs(i,min_m=min_m)
        if len(nb)>=3: a[i]=np.median(d[nb]); b[i]=np.median(fh[nb])
    pd_[min_m]=a; pfh[min_m]=b
    m=~np.isnan(a)
    e=a[m]-d[m]; print(f"leak test: B1 neighbours >= {min_m} m: n={m.sum()} MAE={np.mean(np.abs(e)):.2f} side-correct={100*np.mean((a[m]>=0)==(d[m]>=0)):.1f}%")
m=~np.isnan(pfh[0])
for sig,lab in [(0,"surveyed LAG (oracle)"),(0.33,"lidar-grade ground, sigma 0.33 ft (~QL2)"),(1.0,"ground sigma 1 ft"),(2.7,"10 m DEM national RMSE, sigma 2.7 ft")]:
    g=L+rng.normal(0,sig,len(L)) if sig else L
    pf=g+pfh[0]; e=(pf-F)[m]; pdd=(pf-B)[m]
    print(f"B2 with {lab:42s} MAE={np.mean(np.abs(e)):.2f} |err|<=1ft {100*np.mean(np.abs(e)<=1):.1f}% side-correct {100*np.mean((pdd>=0)==(d[m]>=0)):.1f}%")
# local: Bonita Springs community 120680
cm=np.array([r["nfipCommunityNumber"]=="120680" for r in D])&m
e=(pd_[0]-d)[cm]; print(f"Bonita Springs subset B1: n={cm.sum()} MAE={np.mean(np.abs(e)):.2f} side-correct={100*np.mean(((pd_[0]>=0)==(d>=0))[cm]):.1f}% truth share above BFE {100*np.mean(d[cm]>=0):.1f}%")
# subject prediction
s_lat,s_lon=np.radians(26.34005),np.radians(-81.81759)
sd,si=tree.query([[s_lat,s_lon]],k=10); sd=sd[0]*6371000
print("subject neighbours:")
for dd,j in zip(sd,si[0]):
    r=D[j]; print(f"  {dd:6.0f} m  {r['streetAddress']:<28} diag {r['buildingDiagramNumber']:<3} BFE {B[j]:5.1f} floor {F[j]:5.1f} LAG {L[j]:5.1f}  floor-BFE {d[j]:+.1f}  floor-LAG {fh[j]:+.1f}  issued {r['issuedAt'] and __import__('datetime').datetime.utcfromtimestamp(r['issuedAt']/1000).date()}")
nb=[j for dd,j in zip(sd,si[0]) if dd<=300][:5]
print("B1 subject: median floor-BFE = %+.1f ft (n=%d)"%(np.median(d[nb]),len(nb)), " -> floor ~ %.1f ft vs current BFE 10"%(10+np.median(d[nb])))
print("B2 subject: median floor-LAG = %+.1f ft; with DEM avg ground 7.4 -> floor ~ %.1f ft"%(np.median(fh[nb]),7.4+np.median(fh[nb])))
