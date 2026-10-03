exec(open("ml_head.py").read())
import lightgbm as lgb
from sklearn.ensemble import RandomForestRegressor
diagnames=np.array([r.get("buildingDiagramNumber") for r in T])
cnt=np.array([r["county_fips"] or "0" for r in T]); cnt=np.unique(cnt,return_inverse=True)[1]
zone=np.array([{"AE":0,"AH":1,"A":2}.get(r["floodZone"],3) for r in T])
base=np.c_[B,zone,yr,[r["eff_yr_blt"] or np.nan for r in T],[r["tot_lvg_ar"] or np.nan for r in T],[r["no_buldng"] or np.nan for r in T],
           [r["jv"] or np.nan for r in T],[r["lnd_sqfoot"] or np.nan for r in T],np.degrees(lat),np.degrees(lon),cnt,feat]
groups=(np.floor(np.degrees(lat)/0.1)*10000+np.floor(np.degrees(lon)/0.1)).astype(int)
folds=list(GroupKFold(5).split(base,d,groups))
W=wE[E]
def score(name,pred,mask=cov):
    e=pred[mask]-d[mask]; w=W[mask]
    print(f"  {name:58s} MAE={np.average(np.abs(e),weights=w):.2f} ft  within 1 ft {100*np.average(np.abs(e)<=1,weights=w):5.1f}%  above/below right {100*np.average((pred[mask]>=0)==(d[mask]>=0),weights=w):5.1f}%")
def oof(make,X,cat=None):
    p=np.full(n,np.nan)
    for tr,te in folds:
        m=make(); 
        if cat is not None and isinstance(m,lgb.LGBMRegressor): m.fit(X[tr],d[tr],categorical_feature=cat)
        else: m.fit(X[tr],np.nan_to_num(d[tr]) if False else d[tr])
        p[te]=m.predict(X[te])
    return p
HGB=lambda: HistGradientBoostingRegressor(max_iter=600,learning_rate=0.05,max_leaf_nodes=63,min_samples_leaf=40,l2_regularization=1.0,categorical_features=[10],random_state=0)
LGB=lambda: lgb.LGBMRegressor(n_estimators=1500,learning_rate=0.02,num_leaves=63,min_child_samples=40,subsample=0.8,subsample_freq=1,colsample_bytree=0.7,reg_lambda=1.0,objective="huber",alpha=1.5,verbose=-1,random_state=0)
RF=lambda: RandomForestRegressor(n_estimators=300,min_samples_leaf=5,max_features=0.5,n_jobs=4,random_state=0)
def krig(p):
    # correct each house by the distance-weighted residual of its certificate neighbours (their own out-of-fold residuals)
    r=d-p; out=p.copy()
    for i in range(n):
        js=[j for j,dd in zip(idx[i][:12],dist[i][:12]) if j!=i and addr[j]!=addr[i] and dd<=500][:8]
        if js:
            dd=np.array([dist[i][list(idx[i]).index(j)] for j in js]); out[i]=p[i]+np.average(r[js],weights=1/(dd+25))*0.7
    return out
Xn=np.nan_to_num(base,nan=-999)
def suite(label,X,extra_cat=None):
    print(f"\n== {label} ==")
    ph=oof(HGB,X); score("gradient boosting (sklearn HGB, what I ran before)",ph)
    pl=oof(LGB,X,[10]); score("LightGBM, robust loss",pl)
    pr=oof(RF,np.nan_to_num(X,nan=-999)); score("random forest",pr)
    pk=krig(pl); score("LightGBM + residual kriging from neighbours",pk)
    pe=(pl+pr+pk)/3; score("ensemble (LightGBM, forest, kriged)",pe)
    return pk
rng=np.random.default_rng(1)
g_lidar=L+rng.normal(0,0.33,n)
suite("No ground, no imagery (deployable once certificate numbers are published)",base)
withg=np.c_[base,g_lidar,g_lidar-B]
pk=suite("+ lidar-grade ground (simulated)",withg)
# street-view simulation: foundation class and a noisy direct floor-height reading
fclass={"1A":0,"1B":1,"8":2,"5":3,"6":3,"7":4}
true_cls=np.array([fclass.get(x,np.nan) for x in diagnames],float)
def noisy_cls(acc):
    c=true_cls.copy(); flip=rng.random(n)>acc; c[flip]=rng.integers(0,5,flip.sum()); return c
for acc in (0.85,):
    X=np.c_[withg,noisy_cls(acc)]
    print(f"\n== + lidar ground + street-view FOUNDATION TYPE ({int(acc*100)}% correct, simulated) ==")
    p=oof(LGB,X,[10]); score("LightGBM",p); score("LightGBM + kriging",krig(p))
for sig in (0.72,1.5):
    ffh_obs=fh+rng.normal(0,sig,n)
    X=np.c_[withg,noisy_cls(0.85),ffh_obs,g_lidar+ffh_obs-B]
    print(f"\n== + lidar ground + foundation type + street-view FLOOR-HEIGHT reading, error sigma {sig} ft (simulated) ==")
    p=oof(LGB,X,[10]); score("LightGBM",p); score("LightGBM + kriging",krig(p))
# street view WITHOUT lidar ground: floor-height reading needs a ground reference -> use 10 m DEM-like ground
g_dem=L+rng.normal(0,2.7,n); ffh_obs=fh+rng.normal(0,0.72,n)
X=np.c_[base,g_dem,g_dem-B,noisy_cls(0.85),ffh_obs,g_dem+ffh_obs-B]
print("\n== street-view floor height (sigma 0.72) + foundation, but only 10 m DEM ground (sigma 2.7 ft) ==")
p=oof(LGB,X,[10]); score("LightGBM + kriging",krig(p))
