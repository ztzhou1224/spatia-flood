"""Bee Maps (Hivemapper) views for sampled houses that Mapillary did not read.

Bee Maps imagery is paid ($0.005 per image view) and licensed only within our implementation: no
redistribution, Hivemapper owns the data and derivatives. Every row is tagged provider=beemaps; images
stay in data/. The key comes from BEEMAPS_API_KEY (repo .env) and is never printed.

Per house, in the random sample order of image_sample.csv (houses with a Mapillary door height are
skipped; the answer key is never read):
1. catalog query (`/latest/poly?catalog=true`, cost 0) over the footprint + 50 m;
2. a frame qualifies like a Mapillary perspective view: camera 8-45 m from the footprint, the line to
   the centroid crossing no other building, bearing within the device half-FOV (from `/devices`
   focal) minus 5 deg of the GPS heading (forward camera); best = smallest |offset|, then distance
   nearest 20 m; one view per house;
3. the signed URL comes from a non-catalog query over a ~4 m box around that frame; only the chosen
   frame is downloaded (one billed image view).
Spend is logged to data/harris_mini/beemaps/my_spend.jsonl; the script stops at MAX_VIEWS downloads.
Usage: python beemaps_views.py AREA N_HOUSES MAX_VIEWS
"""
import json, os, sys, time
import numpy as np, pandas as pd, requests
from shapely import wkt
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
from pyproj import Transformer
from mapillary_views import D, DMIN, DMAX, TO_UTM, buildings, fetch_img, perspective_crop, sample

API = "https://beemaps.com/api/developer"
LOG = D / "beemaps" / "my_spend.jsonl"
TO_LL = Transformer.from_crs("EPSG:6344", "EPSG:4326", always_xy=True)


def post(path: str, poly: dict, params: dict) -> dict:
    hdr = {"Authorization": "Basic " + os.environ["BEEMAPS_API_KEY"]}
    for attempt in range(5):
        try:
            r = requests.post(f"{API}/{path}", params=params, json=poly, headers=hdr, timeout=120)
            d = r.json()
            with open(LOG, "a") as f:
                f.write(json.dumps(dict(t=time.time(), kind="query", params=params, http=r.status_code,
                                        frames=len(d.get("frames", [])),
                                        with_url=sum("url" in x for x in d.get("frames", [])),
                                        **{k: v for k, v in d.items() if k != "frames"})) + "\n")
            if r.status_code == 200: return d
            print("HTTP", r.status_code, str(d)[:200], file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print("retry", attempt, type(e).__name__, file=sys.stderr)
        time.sleep(2 ** attempt)
    raise RuntimeError("Bee Maps request failed")


def box(x0, y0, x1, y1) -> dict:
    (a, b), (c, d) = TO_LL.transform(x0, y0), TO_LL.transform(x1, y1)
    return {"type": "Polygon", "coordinates": [[[a, b], [c, b], [c, d], [a, d], [a, b]]]}


def views_downloaded() -> int:
    return sum(1 for l in open(LOG) if '"kind": "view"' in l) if LOG.exists() else 0


def main(area: str, n: int, max_views: int):
    (D / "beemaps").mkdir(parents=True, exist_ok=True)
    out = D / area / "beemaps_views"; out.mkdir(exist_ok=True)
    focal = {k: v["focal"] for k, v in requests.get(f"{API}/devices", timeout=60).json().items()}
    hs = sample(area, 10 ** 6)
    smp = pd.read_csv(D / area / "image_sample.csv")
    hs = hs[hs.oid.isin(smp.oid)]
    rd = pd.read_parquet(D / area / "vlm_reads.parquet")
    have = set(rd.oid[rd.parse_ok & rd.house_visible & rd.front_door_visible
                      & rd.door_threshold_height_above_ground_ft.notna()])
    hs = hs[~hs.oid.isin(have)].head(n)
    blds = buildings(area); bt = STRtree(blds)
    done_path = D / area / "beemaps_views.parquet"
    rows = pd.read_parquet(done_path).to_dict("records") if done_path.exists() else []
    seen = {r["oid"] for r in rows}
    n_cat = 0
    for h in hs.itertuples():
        if h.oid in seen: continue
        if views_downloaded() >= max_views:
            print("MAX_VIEWS reached", file=sys.stderr); break
        fp = wkt.loads(h.fp_wkt); c = fp.centroid
        x0, y0, x1, y1 = fp.buffer(50).bounds
        frames = post("latest/poly", box(x0, y0, x1, y1), {"catalog": "true", "headings": "true"}).get("frames", [])
        n_cat += 1
        best = None
        for f in frames:
            p = f.get("position") or {}
            if p.get("heading") is None or f.get("device") not in focal or f.get("mount", "front") != "front":
                continue
            cx, cy = TO_UTM.transform(p["lon"], p["lat"]); cam = Point(cx, cy)
            d = fp.distance(cam)
            if not DMIN <= d <= DMAX: continue
            hfov = 2 * np.degrees(np.arctan(0.5 / focal[f["device"]]))
            brg = np.degrees(np.arctan2(c.x - cx, c.y - cy)) % 360
            off = (brg - p["heading"] + 180) % 360 - 180
            if abs(off) > hfov / 2 - 5: continue
            seg = LineString([cam, c]); blocked = False
            for k in bt.query(seg):
                b = blds[k]
                if b.contains(cam): blocked = True; break
                if b.intersection(fp).area > 0.3 * min(b.area, fp.area): continue
                if b.intersects(seg): blocked = True; break
            if blocked: continue
            angs = [np.degrees(np.arctan2(px - cx, py - cy)) for px, py in fp.exterior.coords]
            half = max(abs((a - brg + 180) % 360 - 180) for a in angs)
            key = (round(abs(off) / 10), abs(d - 20))
            if best is None or key < best[0]:
                best = (key, dict(oid=h.oid, sequence=f["sequence"], idx=f["idx"], device=f["device"],
                                  captured=pd.Timestamp(f["timestamp"]), dist_m=d, off=off, half_w=half,
                                  hfov=hfov, focal=focal[f["device"]], cx=cx, cy=cy))
        if best is None:
            rows.append(dict(oid=h.oid, path=None)); continue
        v = best[1]
        g = post("latest/poly", box(v["cx"] - 2, v["cy"] - 2, v["cx"] + 2, v["cy"] + 2), {"headings": "true"})
        m = [f for f in g.get("frames", []) if f.get("sequence") == v["sequence"] and f.get("idx") == v["idx"]]
        if not m:
            rows.append(dict(**v, path=None, note="frame not returned by URL query")); continue
        img = fetch_img(m[0]["url"])
        with open(LOG, "a") as fl:
            fl.write(json.dumps(dict(t=time.time(), kind="view", sequence=v["sequence"], idx=v["idx"],
                                     usd=0.005)) + "\n")
        path = out / f"{h.oid}_bm_{v['sequence']}_{v['idx']}.jpg"
        perspective_crop(img.convert("RGB"), v["off"], v["half_w"], v["focal"], v["hfov"]).save(path, quality=90)
        rows.append(dict(**v, path=str(path)))
        pd.DataFrame(rows).assign(provider="beemaps").to_parquet(done_path, index=False)
    df = pd.DataFrame(rows).assign(provider="beemaps")
    df.to_parquet(done_path, index=False)
    nv = views_downloaded()
    print(f"{area}: houses tried {len(df)} (catalog queries this run {n_cat}); with a Bee Maps view "
          f"{int(df.path.notna().sum())}; image views downloaded in total {nv} (${nv * 0.005:.3f})")
    if df.path.notna().any():
        print("capture months:", df.captured.dropna().dt.strftime("%Y-%m").value_counts().sort_index().to_dict())


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
