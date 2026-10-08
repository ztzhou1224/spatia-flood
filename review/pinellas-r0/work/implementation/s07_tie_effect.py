import sys, numpy as np, pandas as pd
sys.argv = [sys.argv[0]] + sys.argv[1:]
exec(open("s06_labels_dedupe.py").read().split("cur, cands = select")[0])  # reuse setup + select()
cur, cands = select(e, "last", "quicksort"); fix, _ = select(e, "first", "stable"); ms, _ = select(e, "last", "mergesort")
bl = pd.read_parquet(D + "/assemble/buildings_12103.parquet", columns=["building_id", "ffe_class", "ffe_ft", "bfe_ft", "bfe_call", "touches_sfha"]).set_index("building_id")
common = cur.index.intersection(fix.index)
for name, alt in (("as-written vs na_first+stable", fix), ("quicksort vs mergesort (same rule)", ms)):
    c = cur.index.intersection(alt.index)
    d = cur.loc[c].OBJECTID != alt.loc[c].OBJECTID
    chg = c[d]
    dv = (cur.loc[chg].ffe_ft - alt.loc[chg].ffe_ft)
    inlayer = bl.loc[chg]
    rec = inlayer.ffe_class == "record"
    newfmb = alt.loc[chg].ffe_ft - inlayer.bfe_ft
    oldfmb = inlayer.ffe_ft - inlayer.bfe_ft
    flip = rec & inlayer.touches_sfha & inlayer.bfe_ft.notna() & (np.sign(newfmb) != np.sign(oldfmb))
    print(f"{name}: certificate differs {int(d.sum())}; ffe differs >0.1 ft {int((dv.abs()>0.1).sum())}; of those record-class in layer {int(((dv.abs()>0.1) & rec).sum())}; sign of floor_minus_bfe would flip {int(flip.sum())}; |dffe| quantiles {dv.abs().quantile([.5,.9,.99,1]).round(2).to_dict()}")
