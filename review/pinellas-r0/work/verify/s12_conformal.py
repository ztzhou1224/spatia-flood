import sys, json, numpy as np, pandas as pd, lightgbm as lgb
sys.path.insert(0, "/home/user/spatia-flood/pipeline/train"); import train as T
from sklearn.model_selection import GroupKFold
D="/home/user/spatia-flood/data/flood_v1"
f=T.features("12103","pinellas_2018"); lab=pd.read_parquet(f"{D}/train/labels_12103.parquet")
d=lab.merge(f,on="building_id"); d=d[d.g_lag.notna()&(d.lpc_status=="ok")].copy(); d["dh"]=d.ffe_ft-d.g_lag
d=d[~((d.roof_p95-d.dh<6)|(d.dh<-1))].reset_index(drop=True)
blocks=np.array(sorted(d.block.unique())); rng=np.random.default_rng(0); rng.shuffle(blocks); k=len(blocks)
test_b,cal_b=set(blocks[:round(0.2*k)]),set(blocks[round(0.2*k):round(0.4*k)])
bands=json.load(open(f"{D}/train/bands_12103.json")); print("test blocks equal saved:", test_b==set(bands["test_blocks"]))
part=np.where(d.block.isin(test_b),"test",np.where(d.block.isin(cal_b),"cal","fit"))
fit_d,cal_d,test_d=[d[part==x].reset_index(drop=True) for x in ("fit","cal","test")]
print("sizes", len(fit_d),len(cal_d),len(test_d), "saved", bands["n_fit"],bands["n_cal"],bands["n_test"])
oof=np.full(len(fit_d),np.nan)
for a,b in GroupKFold(5).split(fit_d,groups=fit_d.block): oof[b]=T.fit(fit_d.loc[a,T.FEATS],fit_d.dh.iloc[a]).predict(fit_d.loc[b,T.FEATS])
diff=lgb.LGBMRegressor(**{**T.P,"objective":"l2"}).fit(fit_d[T.FEATS].assign(p=oof),np.abs(fit_d.dh.values-oof))
s_of=lambda x,p: np.maximum(diff.predict(x[T.FEATS].assign(p=p)),0.05)
m_fit=T.fit(fit_d[T.FEATS],fit_d.dh); pc=m_fit.predict(cal_d[T.FEATS]); sc=np.abs(cal_d.dh.values-pc)/s_of(cal_d,pc)
q=T.abs_q(sc,0.9); n=len(sc); kk=int(np.ceil((n+1)*0.9))
print(f"q reproduced {q:.4f} saved {bands['q']:.4f} | n_cal {n} k {kk} | np.quantile(0.9) {np.quantile(sc,0.9):.4f}")
model=T.fit(pd.concat([fit_d,cal_d])[T.FEATS],pd.concat([fit_d,cal_d]).dh)
for name,mdl in (("shipped FIT+CAL",model),("m_fit",m_fit)):
    for nm,dd in (("CAL",cal_d),("TEST",test_d)):
        p=mdl.predict(dd[T.FEATS]); s=s_of(dd,p); print(f"  {name:16s} {nm} coverage {((dd.dh>=p-q*s)&(dd.dh<=p+q*s)).mean():.3f}")
