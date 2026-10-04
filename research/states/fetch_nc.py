"""North Carolina buildings with FIELD-MEASURED first floors (NC Risk Building Footprints, NC Emergency Management /
NC Floodplain Mapping Program; attribution required). FFE_TYP 1000 elevation certificate, 1010 traditional survey,
1020/1030 laser inclinometer high/low confidence, 1040 terrestrial lidar high confidence. Aerial-lidar-derived
estimates (1060) are excluded. Centroids in EPSG:4326. Coded values are decoded from the layer's domains.
Output: data/states/nc_measured.parquet.  Usage: python fetch_nc.py
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

U = "https://services1.arcgis.com/YBWrN5qiESVpqi92/arcgis/rest/services/NC_Risk_Building_Footprints/FeatureServer/0"
OUT = Path(__file__).resolve().parents[2] / "data" / "states" / "nc_measured.parquet"
WHERE = "FFE_TYP IN ('1000','1010','1020','1030','1040')"
FIELDS = "OBJECTID,BLDG_ID,OCCUP_TYPE,BUILD_TYPE,FLD_ZONE,STATIC_BFE,YEAR_BUILT,YRBUILTSRC,FFE,FFE_TYP,LIDAR_LAG,NUM_STORY,HTD_SQ_FT"


def q(params):
    for _ in range(6):
        try:
            r = requests.post(f"{U}/query", data={**params, "f": "json"}, timeout=300).json()
            if "error" not in r:
                return r
        except Exception:  # noqa: BLE001
            pass
    raise RuntimeError(params)


def main():
    meta = requests.get(U, params={"f": "json"}, timeout=120).json()
    doms = {f["name"]: {c["code"]: c["name"] for c in f["domain"]["codedValues"]} for f in meta["fields"]
            if f.get("domain") and f["domain"].get("type") == "codedValue"}
    ids = sorted(q({"where": WHERE, "returnIdsOnly": "true"})["objectIds"])
    print(f"measured buildings: {len(ids)}", flush=True)

    def page(chunk):
        r = q({"objectIds": ",".join(map(str, chunk)), "outFields": FIELDS, "returnGeometry": "false", "returnCentroid": "true",
               "outSR": "4326"})
        return [{**f["attributes"], "lon": f["centroid"]["x"], "lat": f["centroid"]["y"]} for f in r["features"] if f.get("centroid")]
    with ThreadPoolExecutor(6) as ex:
        rows = [r for p in ex.map(page, [ids[i:i + 1000] for i in range(0, len(ids), 1000)]) for r in p]
    d = pd.DataFrame(rows)
    for c, m in doms.items():
        if c in d:
            d[c + "_name"] = d[c].astype(str).map(m)
    d.to_parquet(OUT, index=False)
    print(f"saved {len(d)}; FFE_TYP {d.FFE_TYP_name.value_counts().to_dict() if 'FFE_TYP_name' in d else d.FFE_TYP.value_counts().to_dict()}")
    print("occupancy (top):", d.OCCUP_TYPE_name.value_counts().head(8).to_dict() if "OCCUP_TYPE_name" in d else "")


if __name__ == "__main__":
    main()
