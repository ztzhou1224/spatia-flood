"""What 2018 -> 2024 lidar change (lpc_change.py) finds, checked against records and the answer key.

Inputs: data/harris_mini/<AREA>/lpc_change.parquet; HCAD building records 2018 and 2025 (hcad_buildings.py 2018 /
2025: the 2025 roll describes buildings on 1 Jan 2025, the end of the 2024 flight); answer-key capture dates
(RecordedAt, fetched here from the HCFCD layer into key_recorded.parquet; SCORER ONLY, like the key itself: City of
Houston deliveries carry a date, Harris County deliveries do not and per the layer description were captured
2019-11-18 .. 2020-06-16).
A house is "up" when ridge, roof and eave (each above that flight's own ground) all rose > 3 ft. The ridge is the
99th percentile of all non-ground returns over the footprint, so it includes overhanging trees; the ridge-free rule
"roof and eave up > 3 ft" is reported next to it.
Record class (label-free): rebuilt = 2025 year built >= 2018; same building with foundation or stories changed; same
building unchanged; record missing.
Reports per area: (1) up vs record class and the eave rise per class; (2) record foundation slab -> piers vs lidar,
with the 2018 point-cloud estimate (was the house already raised in 2018?); (3) scorer: up vs answer key by key
capture time; (4) scorer: error of benchmark method E / F (5-fold by 1 km block) on houses that changed vs not.
Usage: python eval_change.py A C
"""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from benchmark import predictions  # noqa: E402
from eval_transfer import load  # noqa: E402

R = HERE.parents[1] / "data"
D = R / "harris_mini"
LAYER = "https://services7.arcgis.com/NQSCMzARMhPjRo7j/arcgis/rest/services/Structure_Inventory/FeatureServer/23/query"
BBOX = {"A": "-95.480,29.670,-95.440,29.700", "B": "-95.580,29.950,-95.530,29.990", "C": "-95.130,29.530,-95.080,29.570"}
T = 3.0


def key_dates(area):
    p = D / area / "key_recorded.parquet"
    if not p.exists():
        rows, off = [], 0
        while True:
            q = {"f": "json", "where": "1=1", "geometry": BBOX[area], "geometryType": "esriGeometryEnvelope",
                 "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "OBJECTID,RecordedAt",
                 "returnGeometry": "false", "resultOffset": off, "resultRecordCount": 2000}
            d = json.load(urllib.request.urlopen(LAYER + "?" + urllib.parse.urlencode(q)))
            rows += [x["attributes"] for x in d["features"]]
            if not d.get("exceededTransferLimit"):
                break
            off += len(d["features"])
        r = pd.DataFrame(rows).rename(columns={"OBJECTID": "oid"})
        r["recorded"] = pd.to_datetime(r.RecordedAt, unit="ms", utc=True)
        r[["oid", "recorded"]].to_parquet(p, index=False)
    return pd.read_parquet(p)


def records():
    cols = ["acct", "date_erected", "foundation", "stories"]
    b18 = pd.read_parquet(R / "hcad" / "bld_2018.parquet", columns=cols)
    b25 = pd.read_parquet(R / "hcad" / "bld_2025.parquet", columns=cols)
    return b18.merge(b25, on="acct", how="outer", suffixes=("_18", "_25"))


def rec_class(f):
    return np.select([f.date_erected_18.isna() | f.date_erected_25.isna(),
                      pd.to_numeric(f.date_erected_25, errors="coerce") >= 2018,
                      f.foundation_18 != f.foundation_25, f.stories_18 != f.stories_25],
                     ["record missing", "rebuilt (2025 year built >= 2018)", "same building, foundation changed",
                      "same building, stories changed"], "same building, unchanged")


def is_up(f):
    return (f.d_ridge > T) & (f.d_roof > T) & (f.d_eave > T)


def main(areas):
    b = records()
    for area in areas:
        m = pd.read_parquet(D / area / "lpc_change.parquet")
        h = pd.read_parquet(D / area / "houses.parquet", columns=["oid", "hcad"])
        f = h.merge(m, on="oid").merge(b, left_on="hcad", right_on="acct", how="left")
        f = f[f.d_eave.notna() | f.d_roof.notna()].copy()
        f["record"] = rec_class(f)
        f["lidar"] = np.where(is_up(f), f"up > {T:g} ft", "not up")
        print(f"\n# {area}: houses (all answer-key points, front door) with both flights: {len(f)}\n")
        f["roof & eave"] = np.where((f.d_roof > T) & (f.d_eave > T), f"roof & eave up > {T:g} ft", "not")
        print(pd.crosstab(f.record, [f.lidar, f["roof & eave"]], margins=True).to_markdown())
        print("\neave rise (ft) of houses up, by record class:\n")
        print(f[f.lidar != "not up"].groupby("record").d_eave.describe(percentiles=[.25, .5, .75])[
            ["count", "25%", "50%", "75%"]].round(1).to_markdown())
        rb = f[f.record.str.startswith("rebuilt")]
        print(f"\nrebuilt: {len(rb)}; stories 2018 -> 2025: {rb.groupby(['stories_18', 'stories_25']).size().to_dict()}")
        print("rebuilt but not up: median change (ft)", rb[rb.lidar == "not up"][["d_ridge", "d_roof", "d_eave"]].median().round(1).to_dict())

        # scored houses (tiers A+B): records, 2018 estimate, answer key
        k = key_dates(area)
        g = load(area)
        g["block"] = (g.x // 1000).astype(int).astype(str) + "_" + (g.y // 1000).astype(int).astype(str)
        p = predictions(g, g, True)
        g["E"], g["F"] = p["E + eave estimate"], p["F E, physical override"]
        g = g.merge(m, on="oid", how="left").merge(k, on="oid", how="left").merge(
            b[["acct", "foundation_25", "date_erected_25"]], left_on="hcad", right_on="acct", how="left")
        up = is_up(g)
        sp = (g.foundation == "Slab") & g.foundation_25.astype(str).str.startswith("Piers")
        print("\nscored houses, record foundation slab (2018) -> piers (2025):\n")
        rows = {}
        for nm, mm in (("lidar not up", sp & ~up), ("lidar up", sp & up)):
            x = g[mm]
            rows[nm] = {"n": len(x), "2018 estimate split, median ft": x.est_split.median(),
                        "key door height, median ft": x.dh.median(), "key raised (> 3 ft)": int((x.dh > 3).sum())}
        print(pd.DataFrame(rows).T.round(1).to_markdown())
        g["key_time"] = np.where(g.delivery.str.startswith("Harris County"), "Harris County, 2019-11..2020-06",
                                 np.where(g.recorded < pd.Timestamp("2018-07-01", tz="UTC"), "Houston, 2018-02..06",
                                          "Houston, after 2018-06"))
        g["lidar"] = np.where(up, "up", "not up")
        g["key"] = np.where(g.dh > 3, "key raised", "key not raised")
        print("\nscorer: lidar change vs answer key, by key capture time:\n")
        print(pd.crosstab(g.key_time, [g.lidar, g.key]).to_markdown())
        print("\nscorer: benchmark error (5-fold by 1 km block, screened key):\n")
        rows = {}
        s = g.key_ok
        for nm, mm in (("all", s), ("not up", s & ~up), ("up 2018 -> 2024", s & up)):
            r = mm & (g.dh > 3)
            rows[nm] = {"n": int(mm.sum()), "MAE E": (g.E - g.dh)[mm].abs().mean(), "raised n": int(r.sum()),
                        "raised MAE E": (g.E - g.dh)[r].abs().mean(), "raised MAE F": (g.F - g.dh)[r].abs().mean()}
        print(pd.DataFrame(rows).T.round(2).to_markdown())
        x = g[s & up & (g.dh > 3)]
        print(f"\nscorer: up and key raised ({len(x)} houses): median abs error E {(x.E - x.dh).abs().median():.2f}, "
              f"E + eave rise {(x.E + x.d_eave - x.dh).abs().median():.2f} (signed {(x.E + x.d_eave - x.dh).median():.2f}) ft")


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    main(sys.argv[1:])
