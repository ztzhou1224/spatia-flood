"""Bee Maps coverage census with catalog=true (metadata only, no signed image URLs).

Bee Maps imagery is paid and licensed only within our implementation (no redistribution); rows are
tagged provider=beemaps. The key comes from BEE_MAP_API_KEY and is never printed. Every response's
cost / credit fields are appended to data/harris_mini/beemaps/spend_log.jsonl.
Output: data/harris_mini/<AREA>/beemaps_catalog.parquet.
Usage: python beemaps_catalog.py AREA minlon minlat maxlon maxlat
"""
import json, os, sys, time
from pathlib import Path
import numpy as np, pandas as pd, requests

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
API = "https://beemaps.com/api/developer"


def post(path: str, body: dict, params: dict) -> dict:
    hdr = {"Authorization": "Basic " + os.environ["BEE_MAP_API_KEY"], "Content-Type": "application/json"}
    for attempt in range(5):
        try:
            r = requests.post(f"{API}/{path}", params=params, json=body, headers=hdr, timeout=180)
            d = r.json()
            meta = {k: v for k, v in d.items() if k != "frames"} if isinstance(d, dict) else {}
            with open(D / "beemaps" / "spend_log.jsonl", "a") as f:
                f.write(json.dumps(dict(t=time.time(), path=path, params=params, http=r.status_code,
                                        frames=len(d.get("frames", [])) if isinstance(d, dict) else None, **meta)) + "\n")
            if r.status_code == 200:
                return d
            print("HTTP", r.status_code, str(d)[:200], file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print("retry", attempt, type(e).__name__, file=sys.stderr)
        time.sleep(2 ** attempt)
    raise RuntimeError("Bee Maps request failed")


if __name__ == "__main__":
    area = sys.argv[1]
    x0, y0, x1, y1 = (float(v) for v in sys.argv[2:6])
    (D / "beemaps").mkdir(parents=True, exist_ok=True)
    rows = []
    for xa in np.arange(x0, x1 - 1e-9, 0.0125):
        for ya in np.arange(y0, y1 - 1e-9, 0.01):
            xb, yb = min(xa + 0.0125, x1), min(ya + 0.01, y1)
            poly = {"type": "Polygon", "coordinates": [[[xa, ya], [xb, ya], [xb, yb], [xa, yb], [xa, ya]]]}
            d = post("latest/poly", poly, {"catalog": "true", "headings": "true", "min_week": "2022-01-03"})
            print(f"tile {xa:.4f},{ya:.4f}: frames {len(d.get('frames', []))} cost {d.get('cost')} "
                  f"credits used {d.get('creditsUsed')}", flush=True)
            rows += d.get("frames", [])
            if d.get("cost"):
                print("NONZERO COST - stopping census", file=sys.stderr); break
    df = pd.json_normalize(rows) if rows else pd.DataFrame()
    df["provider"] = "beemaps"
    df.to_parquet(D / area / "beemaps_catalog.parquet", index=False)
    print(area, len(df), "frames;", list(df.columns)[:30])
