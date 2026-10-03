"""Index Mapillary images inside one bbox (Graph API `images`, tiles of at most 0.01 deg).

The endpoint silently returns a partial set for a large bbox well below its 2000 cap (a 0.01 deg tile
in Clear Lake gave 1839 images; the same area in 0.005 deg tiles gave 3205), so the area is queried
in 0.005 deg tiles and again in 0.0025 deg tiles and the union is kept.

Mapillary data is CC BY-SA 4.0. The token comes from MAPILLARY_ACCESS_TOKEN and is sent only as a
header; it is never printed. Output: data/harris_mini/<AREA>/mapillary_index.parquet.
Usage: python mapillary_index.py AREA minlon minlat maxlon maxlat
"""
import os, sys, time
from pathlib import Path
import numpy as np, pandas as pd, requests

OUT = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
URL = "https://graph.mapillary.com/images"
FIELDS = "id,captured_at,computed_geometry,computed_compass_angle,is_pano,camera_type,thumb_2048_url"
STEPS = (0.005, 0.0025)


def get(params: dict) -> dict:
    hdr = {"Authorization": f"OAuth {os.environ['MAPILLARY_ACCESS_TOKEN']}"}
    for attempt in range(6):
        try:
            r = requests.get(URL, params=params, headers=hdr, timeout=120)
            d = r.json()
            if "error" in d:
                if d["error"].get("code") == 190:
                    raise SystemExit("Mapillary rejected the token (error 190)")
                raise RuntimeError(d["error"].get("message"))
            return d
        except (requests.RequestException, ValueError, RuntimeError) as e:
            print("retry", attempt, type(e).__name__, str(e)[:120], file=sys.stderr)
            time.sleep(2 ** attempt)
    raise RuntimeError("Mapillary request failed")


def tile(b: tuple[float, float, float, float], depth: int = 0) -> list[dict]:
    """The endpoint caps one response at 2000 images; split the tile in four when it is full."""
    d = get(dict(fields=FIELDS, bbox=",".join(f"{v:.6f}" for v in b), limit=2000))
    rows = d.get("data", [])
    if len(rows) >= 2000 and depth < 6:
        x0, y0, x1, y1 = b
        xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
        rows = [r for q in ((x0, y0, xm, ym), (xm, y0, x1, ym), (x0, ym, xm, y1), (xm, ym, x1, y1))
                for r in tile(q, depth + 1)]
    elif len(rows) >= 2000:
        print("WARNING tile still full at max depth", b, file=sys.stderr)
    return rows


if __name__ == "__main__":
    area = sys.argv[1]
    x0, y0, x1, y1 = (float(v) for v in sys.argv[2:6])
    rows = []
    for step in STEPS:
        for xa in np.arange(x0, x1 - 1e-9, step):
            for ya in np.arange(y0, y1 - 1e-9, step):
                rows += tile((xa, ya, min(xa + step, x1), min(ya + step, y1)))
    df = pd.DataFrame(rows).drop_duplicates("id")
    df["lon"] = df.computed_geometry.map(lambda g: g["coordinates"][0] if isinstance(g, dict) else np.nan)
    df["lat"] = df.computed_geometry.map(lambda g: g["coordinates"][1] if isinstance(g, dict) else np.nan)
    df["captured"] = pd.to_datetime(df.captured_at, unit="ms", utc=True)
    df = df.drop(columns=["computed_geometry"])
    df.to_parquet(OUT / area / "mapillary_index.parquet", index=False)
    print(f"{area}: {len(df)} images, pano {int(df.is_pano.sum())}, with compass "
          f"{int(df.computed_compass_angle.notna().sum())}, with geometry {int(df.lon.notna().sum())}")
    print("by capture year (all / pano):")
    print(pd.crosstab(df.captured.dt.year, df.is_pano).to_string())
