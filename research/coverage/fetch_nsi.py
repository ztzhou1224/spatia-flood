"""USACE National Structure Inventory (NSI) points inside one bbox (public API, national coverage).

Kept: fd_id, x, y, occtype, bldgtype, found_type, found_ht (ft), num_story, med_yr_blt,
ground_elv (ft, NSI's own DEM sample), firmzone, static_bfe, ftprntsrc. No owner data exists in NSI.
Output: data/harris_mini/<AREA>/nsi.parquet
Usage: python fetch_nsi.py AREA minlon minlat maxlon maxlat
"""
import sys, time
from pathlib import Path
import numpy as np, pandas as pd, requests

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
KEEP = ["fd_id", "x", "y", "occtype", "bldgtype", "found_type", "found_ht", "num_story", "med_yr_blt",
        "ground_elv", "firmzone", "static_bfe", "ftprntsrc"]

def get(b):
    x0, y0, x1, y1 = b
    ring = f"{x0},{y0},{x1},{y0},{x1},{y1},{x0},{y1},{x0},{y0}"
    for a in range(5):
        try:
            r = requests.get("https://nsi.sec.usace.army.mil/nsiapi/structures", params={"bbox": ring, "fmt": "fc"}, timeout=180)
            return r.json()["features"]
        except Exception as e:  # noqa: BLE001
            print("retry", a, type(e).__name__, file=sys.stderr); time.sleep(2 ** a)
    raise RuntimeError("NSI failed")

if __name__ == "__main__":
    area = sys.argv[1]; x0, y0, x1, y1 = (float(v) for v in sys.argv[2:6])
    rows = []
    for xa in np.arange(x0, x1 - 1e-9, 0.01):
        for ya in np.arange(y0, y1 - 1e-9, 0.01):
            rows += [f["properties"] for f in get((xa, ya, min(xa + 0.01, x1), min(ya + 0.01, y1)))]
    df = pd.DataFrame(rows).drop_duplicates("fd_id")[KEEP]
    df.to_parquet(D / area / "nsi.parquet", index=False)
    print(area, len(df), df.found_type.value_counts().to_dict(), df.groupby("found_type").found_ht.median().to_dict())
