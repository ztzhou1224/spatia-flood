import sys, json, hashlib
import pyarrow.parquet as pq, pandas as pd, numpy as np
p = sys.argv[1]
md = pq.read_metadata(p).metadata
print("metadata keys:", list(md.keys()))
prov = json.loads(md[b"spatia_flood"])
print(json.dumps(prov, indent=1)[:4000])
cols = [c for c in pq.read_schema(p).names]
print("ncols", len(cols)); print(cols)
h = hashlib.sha256(open(p,'rb').read()).hexdigest(); print("sha256", h)
b = pd.read_parquet(p, columns=["input_licences","provider","ffe_vintage","ffh_vintage","ffe_class","ffh_class","firm_effective_date",
  "year_built","year_built_vintage","year_built_source","ground_geoid","ffe_datum","bfe_datum","bfe_precision_ft","bfe_class","bfe_method","bfe_source","bfe_vintage",
  "footprint_source","footprint_release","address_source","in_risk_area","touches_sfha","zone_main","lidar_workunit","lidar_ql","ground_source","ground_vintage","ground_precision_ft",
  "record_vintage_note","ffe_record_lidar_conflict","lift_or_rebuild","lift_or_rebuild_null","roof_vintage"])
print("rows", len(b))
print("\nprovider:\n", b.provider.value_counts(dropna=False))
print("\ninput_licences combos:\n", b.input_licences.map(lambda x: "|".join(x) if x is not None else None).value_counts(dropna=False).to_string())
allt = pd.Series([t for l in b.input_licences for t in (l if l is not None else [])]).value_counts(); print("\ntags:\n", allt.to_string())
print("\nfootprint_release:", b.footprint_release.value_counts(dropna=False).to_string())
print("\nfootprint_source:", b.footprint_source.value_counts(dropna=False).to_string()[:600])
print("\nground_geoid:", b.ground_geoid.value_counts(dropna=False).to_string())
print("\nground_vintage:", b.ground_vintage.value_counts(dropna=False).to_string())
print("\nground_precision_ft:", b.ground_precision_ft.value_counts(dropna=False).to_string())
print("\nlidar_workunit/ql:", b.groupby(["lidar_workunit","lidar_ql"],dropna=False).size().to_string())
print("\nffe_datum:", b.ffe_datum.value_counts(dropna=False).to_string())
print("\nbfe_datum:", b.bfe_datum.value_counts(dropna=False).to_string())
print("\nbfe_precision_ft x bfe_method:", b.groupby(["bfe_method","bfe_precision_ft"],dropna=False).size().to_string())
print("\nbfe_vintage:", b.bfe_vintage.value_counts(dropna=False).head(20).to_string())
print("\nbfe_source sample:", b.bfe_source.dropna().str[:160].value_counts().head(6).to_string())
print("\nfirm_effective_date:", b.firm_effective_date.value_counts(dropna=False).sort_index().to_string())
rec = b[b.ffe_class=="record"]
print("\nrecord rows", len(rec))
v = rec.ffe_vintage
print("ffe_vintage == ffh_vintage for record rows with ffh:", (rec.ffe_vintage == rec.ffh_vintage)[rec.ffh_class=="record"].all())
win = v.str.contains("/", na=False); print("window vintages", int(win.sum()), "unknown", int((v=="unknown").sum()), "null", int(v.isna().sum()))
d = pd.to_datetime(v.where(~win), errors="coerce")
print("point-dated", int(d.notna().sum()))
print("year dist:\n", d.dt.year.value_counts().sort_index().to_string())
print("predate lidar start 2018-12-07:", int((d < "2018-12-07").sum()), " within flight:", int(((d>="2018-12-07")&(d<="2019-03-08")).sum()), " after 2019-03-08:", int((d>"2019-03-08").sum()), " >=2020:", int((d>="2020-01-01").sum()), " >=2024-09-26 (Helene):", int((d>="2024-09-26").sum()))
ws = pd.to_datetime(v.where(win).str.split("/").str[0], errors="coerce"); we = pd.to_datetime(v.where(win).str.split("/").str[1], errors="coerce")
print("window rows: start<lidar", int((ws<"2018-12-07").sum()), "end<lidar", int((we<"2018-12-07").sum()), "start>flightend", int((ws>"2019-03-08").sum()))
print("window examples:", v[win].value_counts().head(8).to_string())
print("record_vintage_note non-null", int(b.record_vintage_note.notna().sum()))
print("ffe_record_lidar_conflict:", b.ffe_record_lidar_conflict.value_counts(dropna=False).to_string())
# year built
yb = pd.to_numeric(b.year_built, errors="coerce")
print("\nyear_built non-null", int(yb.notna().sum()), " >=2019:", int((yb>=2019).sum()), " >=2020:", int((yb>=2020).sum()), " >=2025:", int((yb>=2025).sum()), " in risk & >=2019:", int(((yb>=2019)&b.in_risk_area).sum()))
print("year_built>=2019 by ffh_class:\n", b[yb>=2019].ffh_class.value_counts(dropna=False).to_string())
print("year_built>=2019 by ffe_class & touches_sfha:\n", b[yb>=2019].groupby(["ffe_class","touches_sfha"],dropna=False).size().to_string())
print("year_built dist tail:\n", yb[yb>=2017].value_counts().sort_index().to_string())
print("year_built_vintage:", b.year_built_vintage.value_counts(dropna=False).head(5).to_string())
print("year_built_source:", b.year_built_source.value_counts(dropna=False).head(5).to_string())
print("lift_or_rebuild:", b.lift_or_rebuild.value_counts(dropna=False).to_string(), b.lift_or_rebuild_null.value_counts(dropna=False).to_string())
print("record rows with year_built>=2019 and ffe_vintage< year_built:")
rr = b[(b.ffe_class=="record")&(yb>=2019)].copy(); rr["d"]=pd.to_datetime(rr.ffe_vintage, errors="coerce")
print(" n", len(rr), " vintage year < year_built:", int((rr.d.dt.year < pd.to_numeric(rr.year_built)).sum()))
# modeled rows on buildings built after lidar
mo = b[(b.ffh_class=="modeled")&(yb>=2019)]; print("modeled & year_built>=2019:", len(mo), " of which year_built>=2020:", int((pd.to_numeric(mo.year_built)>=2020).sum()))
