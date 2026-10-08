"""Shift in the MODEL's own feature space (FEATS): modeled rows vs screened labels."""
import sys
from pathlib import Path
import numpy as np, pandas as pd, pyarrow.parquet as pq
ROOT = Path("/home/user/spatia-flood"); W = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / "pipeline" / "train"))
from train import DATA, FEATS, features  # noqa
f = features("12103", "pinellas_2018")
lab = pd.read_parquet(DATA / "train" / "labels_12103.parquet")
d = lab.merge(f, on="building_id"); d = d[d.g_lag.notna() & (d.lpc_status == "ok")].copy(); d["dh"] = d.ffe_ft - d.g_lag
d = d[~((d.roof_p95 - d.dh < 6) | (d.dh < -1))]
b = pq.read_table(ROOT / "data/flood_v1/assemble/buildings_12103.parquet", columns=["building_id", "ffh_class", "touches_sfha", "bfe_call"]).to_pandas()
m = b[b.ffh_class == "modeled"].merge(f, on="building_id")
rows = []; anyo = np.zeros(len(m), bool); anyo_sf = None
for c in FEATS:
    lo, hi = d[c].quantile(.01), d[c].quantile(.99)
    mc = m[c].astype(float).to_numpy(dtype=float, na_value=np.nan); out = (mc < lo) | (mc > hi); anyo |= out
    rows.append({"feat": c, "lab_q1": lo, "lab_q50": d[c].median(), "lab_q99": hi, "mod_q50": m[c].median(), "mod_outside": out.mean()})
R = pd.DataFrame(rows); pd.set_option("display.width", 200); print(R.round(3).to_string())
sf = m.touches_sfha.fillna(False).astype(bool).values
print(f"modeled rows {len(m)}: ANY FEATS outside label 1-99 pct: {anyo.mean():.3f}; SFHA rows {sf.sum()}: {anyo[sf].mean():.3f}; non-SFHA: {anyo[~sf].mean():.3f}")
