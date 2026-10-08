"""Covariate shift labelled vs modeled; BFE call counts; interpolated band widths; target semantics via county C2A/C2B."""
import json, sys
from pathlib import Path
import numpy as np, pandas as pd, pyarrow.parquet as pq
ROOT = Path("/home/user/spatia-flood"); W = Path(sys.argv[1])
cols = ['building_id','in_risk_area','footprint_area_m2','zone_main','zone_main_subtype','sfha_share','touches_sfha','bfe_ft','bfe_method','bfe_precision_ft','bfe_band_lo','bfe_band_hi','bfe_source',
        'ground_ft','roof_ft','eave_ft','dor_use_code','year_built','living_area_sqft','raised_flag','ffh_ft','ffh_class','ffh_band_lo','ffh_band_hi','ffe_ft','ffe_class','ffe_band_lo','ffe_band_hi',
        'ffe_record_lidar_conflict','floor_minus_bfe_ft','bfe_call','bfe_call_basis','ffe_source','record_note']
b = pq.read_table(ROOT/"data/flood_v1/assemble/buildings_12103.parquet", columns=cols).to_pandas()
print("rows", len(b))
rec = b.ffe_class == "record"; mod = b.ffe_class == "modeled"
print("record", rec.sum(), "modeled", mod.sum())
def zone4(z, st):
    z = z.astype(str).str.upper(); st = st.astype(str)
    return np.where(z.str.startswith("V"), "VE/V", np.where(z.str.startswith("A"), "A/AE/AH/AO", np.where(st.str.contains("0.2", regex=False), "X 0.2%", np.where(z == "X", "X", "other"))))
b["z4"] = zone4(b.zone_main, b.zone_main_subtype)
print("\nzone_main distribution (share): record vs modeled")
print(pd.concat([b[rec].z4.value_counts(normalize=True).rename("record"), b[mod].z4.value_counts(normalize=True).rename("modeled")], axis=1).round(3))
print("touches_sfha share: record", b[rec].touches_sfha.mean().round(3), "modeled", b[mod].touches_sfha.mean().round(3))
print("raised_flag share (where not null): record", b[rec].raised_flag.dropna().astype(bool).mean().round(3), "modeled", b[mod].raised_flag.dropna().astype(bool).mean().round(3))
print("dor_use_code top: record", b[rec].dor_use_code.value_counts(normalize=True).head(5).round(3).to_dict())
print("dor_use_code top: modeled", b[mod].dor_use_code.value_counts(normalize=True).head(5).round(3).to_dict())
num = ["year_built", "living_area_sqft", "footprint_area_m2", "ground_ft", "roof_ft", "eave_ft", "sfha_share"]
qs = [.01, .05, .25, .5, .75, .95, .99]
rows = []
for c in num:
    r, m = b.loc[rec, c].astype(float), b.loc[mod, c].astype(float)
    rows.append({"feature": c, **{f"rec_q{int(q*100)}": r.quantile(q) for q in (.01,.5,.99)}, **{f"mod_q{int(q*100)}": m.quantile(q) for q in (.01,.5,.99)},
                 "rec_null": r.isna().mean(), "mod_null": m.isna().mean(), "mod_outside_rec_1_99": ((m < r.quantile(.01)) | (m > r.quantile(.99))).mean()})
R = pd.DataFrame(rows); pd.set_option("display.width", 250)
print(R.round(3).to_string())
lo = {c: b.loc[rec, c].astype(float).quantile(.01) for c in num}; hi = {c: b.loc[rec, c].astype(float).quantile(.99) for c in num}
any_out = np.zeros(mod.sum(), bool)
for c in num:
    m = b.loc[mod, c].astype(float).values
    any_out |= (m < lo[c]) | (m > hi[c])
print("share of modeled rows with ANY of", num, "outside labelled 1-99 pct:", any_out.mean().round(4), "n", any_out.sum())
# year built: pre-FIRM vs post-FIRM
print("year_built decade shares record vs modeled:")
dec = (b.year_built.astype(float) // 10 * 10)
print(pd.concat([dec[rec].value_counts(normalize=True).rename("record"), dec[mod].value_counts(normalize=True).rename("modeled")], axis=1).sort_index().round(3).to_string())
# modeled population outside SFHA: band + call irrelevant but ffh produced
print("modeled rows by z4 with raised_flag share:", b[mod].groupby("z4").raised_flag.apply(lambda s: s.dropna().astype(bool).mean()).round(3).to_dict())

# ---------------- BFE call analysis
print("\n=== BFE CALL ===")
sf = b.touches_sfha.fillna(False).astype(bool)
print("bfe_precision_ft distribution (SFHA, static):", b.loc[sf & (b.bfe_method == "static"), "bfe_precision_ft"].value_counts(dropna=False).head(8).to_dict())
print("calls by class:", pd.crosstab(b.loc[sf, "ffe_class"].fillna("null"), b.loc[sf, "bfe_call"].fillna("null")).to_string())
ra = rec & (b.bfe_call == "above")
fm = b.floor_minus_bfe_ft.astype(float)
print("record above calls:", ra.sum(), "| within 0.5 ft of BFE:", (ra & (fm <= 0.5)).sum(), "| exactly at BFE (==0):", (ra & (fm == 0)).sum(), "| within 0.1:", (ra & (fm <= 0.1)).sum(), "| within 1.0:", (ra & (fm <= 1.0)).sum())
rb = rec & (b.bfe_call == "below")
print("record below calls:", rb.sum(), "| within 0.5 ft:", (rb & (fm >= -0.5)).sum())
print("record calls with lidar conflict:", (rec & b.ffe_record_lidar_conflict.fillna(False).astype(bool) & b.bfe_call.isin(["above","below"])).sum(),
      pd.crosstab(b.loc[rec & b.ffe_record_lidar_conflict.fillna(False).astype(bool), "bfe_call"].fillna("null"), "n").to_dict())
ma = mod & (b.bfe_call == "above"); mb = mod & (b.bfe_call == "below"); mt = mod & (b.bfe_call == "too_close")
print("modeled calls: above", ma.sum(), "below", mb.sum(), "too_close", mt.sum())
print("modeled above: floor_minus_bfe quantiles", fm[ma].quantile([.05,.25,.5,.75,.95]).round(2).to_dict(), "margin band_lo-bfe quantiles", (b.ffe_band_lo - b.bfe_band_hi.fillna(b.bfe_ft))[ma].quantile([.05,.5,.95]).round(2).to_dict())
print("modeled above by raised_flag:", b.loc[ma, "raised_flag"].value_counts(dropna=False).to_dict())
print("modeled below by raised_flag:", b.loc[mb, "raised_flag"].value_counts(dropna=False).to_dict())
print("modeled too_close by raised_flag:", b.loc[mt, "raised_flag"].value_counts(dropna=False).to_dict())
print("modeled band width quantiles (ffh):", (b.ffh_band_hi - b.ffh_band_lo)[mod].quantile([.05,.25,.5,.75,.9,.95]).round(2).to_dict())
print("modeled band width by raised_flag median:", (b.ffh_band_hi - b.ffh_band_lo)[mod].groupby(b.raised_flag[mod].astype(str)).median().round(2).to_dict())
# share of modeled SFHA below where ground itself is below BFE by > band (i.e. decided by ground alone)
msf = mod & sf & b.bfe_ft.notna()
print("modeled SFHA with BFE:", msf.sum(), "| ground_ft + band_hi < bfe (below decided):", (msf & (b.ffe_band_hi < b.bfe_band_lo.fillna(b.bfe_ft))).sum(),
      "| ground_ft itself below BFE by >= 5 ft:", (msf & (b.bfe_ft - b.ground_ft >= 5)).sum(), "| ground below BFE by >= 8 ft:", (msf & (b.bfe_ft - b.ground_ft >= 8)).sum())
# record SFHA truth share above
rsf = rec & sf & b.bfe_ft.notna()
print("record SFHA: n", rsf.sum(), "share ffe>=bfe", (fm[rsf] >= 0).mean().round(3), "| modeled SFHA decided: share above among decided", (ma.sum() / (ma.sum() + mb.sum())).round(3))
# ---------------- interpolated BFE band widths
ip = b.bfe_method == "interpolated"
wdt = (b.bfe_band_hi - b.bfe_band_lo)[ip]
print("\n=== INTERPOLATED BFE === n", ip.sum(), "band width quantiles", wdt.quantile([.05,.25,.5,.75,.9,.95,.99,1]).round(2).to_dict(), "| width > 2 ft:", (wdt > 2).sum(), "| width > 5 ft:", (wdt > 5).sum())
src = b.loc[ip, "bfe_source"].astype(str)
import re
pat = re.compile(r": (\S+) (\S+) ([-\d.]+) ft at (\d+) m; (\S+) (\S+) ([-\d.]+) ft at (\d+) m")
par = src.str.extract(pat)
par.columns = ["t1","id1","e1","d1","t2","id2","e2","d2"]
for c in ("e1","d1","e2","d2"): par[c] = par[c].astype(float)
print("pair source types:", (par.t1 + "/" + par.t2).value_counts().to_dict())
print("d1 (nearest) quantiles m", par.d1.quantile([.5,.9,.99]).to_dict(), "d2 quantiles", par.d2.quantile([.5,.9,.99]).to_dict(), "| pairs with d1+d2 > 1000 m:", ((par.d1 + par.d2) > 1000).sum())
print("|e1-e2| quantiles", (par.e1 - par.e2).abs().quantile([.5,.9,.95,.99,1]).round(2).to_dict())
print("calls with interpolated BFE:", b.loc[ip, "bfe_call"].value_counts(dropna=False).to_dict())
b.loc[ip, ["building_id","bfe_ft","bfe_band_lo","bfe_band_hi","bfe_source","bfe_call","ffe_class"]].to_parquet(W / "interp_rows.parquet", index=False)

# ---------------- target semantics: diagrams of record rows, county C2A vs C2B
print("\n=== TARGET SEMANTICS ===")
lab = pd.read_parquet(ROOT/"data/flood_v1/train/labels_12103.parquet")
rr = b[rec].merge(lab[["building_id","diagram","ffe_ft"]].rename(columns={"ffe_ft":"lab_ffe"}), on="building_id", how="left")
print("record rows by diagram:", rr.diagram.value_counts(dropna=False).to_dict())
nxt = rr.diagram.astype(str).str[0].isin(list("2346789"))
print("record rows using NEXT HIGHER floor (C2b):", nxt.sum(), "| of which bfe_call above:", (nxt & (rr.bfe_call == "above")).sum(), "below:", (nxt & (rr.bfe_call == "below")).sum(), "too_close:", (nxt & (rr.bfe_call=="too_close")).sum())
# county certificates: C2A and C2B
feats = []
for pth in sorted((ROOT/"data/flood_v1/labels_pinellas/raw/2026-10-07").glob("page_*.json")):
    feats += [f["attributes"] for f in json.loads(pth.read_text())["features"]]
cc = pd.DataFrame(feats)
print("county certificates:", len(cc))
for c in ("C2A_TOP_BOTTOM_FLOOR_EL","C2B_TOP_NEXT_HIGHER_FL_EL","C2a_88","C2b_88","B9_BASE_FLOOD_ELEVATION"): cc[c] = pd.to_numeric(cc[c], errors="coerce")
cc["bottom"] = np.where(cc.C2a_88.notna(), cc.C2a_88, cc.C2A_TOP_BOTTOM_FLOOR_EL)
cc["next"] = np.where(cc.C2b_88.notna(), cc.C2b_88, cc.C2B_TOP_NEXT_HIGHER_FL_EL)
dg = cc.A7_BUILDING_DIAG_NUM.astype(str).str.strip().str.upper()
cc["dg"] = dg
nx = dg.str[0].isin(list("2346789")) & cc.bottom.between(-20, 200) & cc["next"].between(-20, 200)
print("county certs diagrams 2-4/6-9 with both C2A and C2B:", nx.sum(), "| next - bottom quantiles ft", (cc["next"] - cc.bottom)[nx].quantile([.05,.25,.5,.75,.95]).round(2).to_dict())
lp = pd.read_parquet(ROOT/"data/flood_v1/labels_pinellas/labels_pinellas_12103.parquet")
j = rr.merge(lp[["building_id","county_objectid"]].drop_duplicates("building_id"), on="building_id", how="inner").merge(cc[["OBJECTID","bottom","next","dg"]], left_on="county_objectid", right_on="OBJECTID", how="inner")
j = j[j.dg.str[0].isin(list("2346789")) & j.bottom.between(-20,200) & j["next"].between(-20,200)]
print("r0 record rows (diagram 2-4/6-9) with a county certificate on the same building carrying C2A:", len(j),
      "| county next vs r0 ffe agree within 0.5 ft:", ((j["next"] - j.ffe_ft).abs() <= 0.5).sum())
j["lowest_minus_bfe"] = j.bottom - j.bfe_ft
flip = (j.bfe_call == "above") & (j.lowest_minus_bfe < 0)
print("of these, bfe_call above:", (j.bfe_call == "above").sum(), "| would be BELOW on lowest floor (C2A < BFE):", flip.sum(),
      "| C2A - BFE quantiles for the above calls:", j.loc[j.bfe_call=="above","lowest_minus_bfe"].quantile([.05,.25,.5,.75,.95]).round(2).to_dict())
print("county certs overall: diagram share", dg.value_counts(normalize=True).head(10).round(3).to_dict())
j.to_parquet(W / "c2a_flip.parquet", index=False)
