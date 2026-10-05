"""Several Bee Maps (Hivemapper) frames per house, for the triage list plus a random control sample.

Bee Maps imagery is paid (image views billed per frame) and licensed only within our implementation: no
redistribution; Hivemapper owns the data and derivatives. Every row is tagged provider=beemaps; images stay in data/.
The key comes from BEEMAPS_API_KEY (repo .env; a leading "MAP" prefix is stripped for Basic auth) and is never
printed. The answer key is never read.

Houses: data/harris_mini/<AREA>/triage.parquet (eval_stories.py) flagged houses, plus N_CONTROL random unflagged
houses (seed 20261005). Per house:
1. catalog query (`/latest/poly?catalog=true`, cost 0) over the footprint + 60 m;
2. qualifying frames as beemaps_views.py (mount front or unknown: the Bee camera faces forward): camera 8-45 m
   from the footprint, line to the centroid not crossing another
   building, centroid within the device half-FOV - 5 deg of the GPS heading (forward camera);
3. up to K frames, chosen for diversity: best-first by (|bearing offset| in 10 deg bins, |distance - 18 m|), at most
   2 per sequence (drive) and at least 3 m apart from already chosen frames;
4. signed URL from a non-catalog query over a 4 m box around each chosen frame, then the download (one billed view).
Spend is logged to data/harris_mini/beemaps/my_spend.jsonl; the run stops at MAX_VIEWS downloads in total.
Output: data/harris_mini/<AREA>/beemaps_multi.parquet + crops in beemaps_multi/.
Usage: python beemaps_multi.py AREA K N_CONTROL MAX_VIEWS
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd
import requests
from mapillary_views import DMAX, DMIN, TO_UTM, D, buildings, fetch_img, perspective_crop
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

API = "https://beemaps.com/api/developer"
LOG = D / "beemaps" / "my_spend.jsonl"
TO_LL = Transformer.from_crs("EPSG:6344", "EPSG:4326", always_xy=True)


def key() -> str:
    k = os.environ["BEEMAPS_API_KEY"]
    return k[3:] if k.startswith("MAP") else k


def post(poly: dict, params: dict) -> dict:
    hdr = {"Authorization": "Basic " + key()}
    for attempt in range(5):
        try:
            r = requests.post(f"{API}/latest/poly", params=params, json=poly, headers=hdr, timeout=120)
            d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            with open(LOG, "a") as f:
                f.write(json.dumps({"t": time.time(), "kind": "query", "params": params, "http": r.status_code,
                                    "frames": len(d.get("frames", [])),
                                    "with_url": sum("url" in x for x in d.get("frames", [])),
                                    **{k: v for k, v in d.items() if k != "frames"}}) + "\n")
            if r.status_code == 200:
                return d
            print("HTTP", r.status_code, r.text[:120], file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print("retry", attempt, type(e).__name__, file=sys.stderr)
        time.sleep(2 ** attempt)
    raise RuntimeError("Bee Maps request failed")


def box(x0, y0, x1, y1) -> dict:
    (a, b), (c, d) = TO_LL.transform(x0, y0), TO_LL.transform(x1, y1)
    return {"type": "Polygon", "coordinates": [[[a, b], [c, b], [c, d], [a, d], [a, b]]]}


def views_downloaded() -> int:
    return sum(1 for line in open(LOG) if '"kind": "view"' in line) if LOG.exists() else 0


def qualifying(frames, fp, focal, blds, bt):
    c = fp.centroid
    out = []
    for f in frames:
        p = f.get("position") or {}
        if p.get("heading") is None or f.get("device") not in focal or f.get("mount", "front") not in ("front", "unknown"):
            continue
        cx, cy = TO_UTM.transform(p["lon"], p["lat"])
        cam = Point(cx, cy)
        d = fp.distance(cam)
        if not DMIN <= d <= DMAX:
            continue
        hfov = 2 * np.degrees(np.arctan(0.5 / focal[f["device"]]))
        brg = np.degrees(np.arctan2(c.x - cx, c.y - cy)) % 360
        off = (brg - p["heading"] + 180) % 360 - 180
        if abs(off) > hfov / 2 - 5:
            continue
        seg = LineString([cam, c])
        blocked = False
        for k in bt.query(seg):
            b = blds[k]
            if b.contains(cam):
                blocked = True
                break
            if b.intersection(fp).area > 0.3 * min(b.area, fp.area):
                continue
            if b.intersects(seg):
                blocked = True
                break
        if blocked:
            continue
        angs = [np.degrees(np.arctan2(px - cx, py - cy)) for px, py in fp.exterior.coords]
        half = max(abs((a - brg + 180) % 360 - 180) for a in angs)
        out.append({"sequence": f["sequence"], "idx": f["idx"], "device": f["device"],
                    "captured": pd.Timestamp(f["timestamp"]), "dist_m": d, "off": off, "half_w": half, "hfov": hfov,
                    "focal": focal[f["device"]], "cx": cx, "cy": cy,
                    "rank": (round(abs(off) / 10), abs(d - 18))})
    return out


def choose(cands, k):
    chosen, per_seq = [], {}
    for v in sorted(cands, key=lambda v: v["rank"]):
        if per_seq.get(v["sequence"], 0) >= 2:
            continue
        if any(np.hypot(v["cx"] - u["cx"], v["cy"] - u["cy"]) < 3 for u in chosen):
            continue
        chosen.append(v)
        per_seq[v["sequence"]] = per_seq.get(v["sequence"], 0) + 1
        if len(chosen) == k:
            break
    return chosen


def main(area: str, k: int, n_control: int, max_views: int):
    (D / "beemaps").mkdir(parents=True, exist_ok=True)
    out = D / area / "beemaps_multi"
    out.mkdir(exist_ok=True)
    focal = {d: v["focal"] for d, v in requests.get(f"{API}/devices", timeout=60).json().items()}
    tri = pd.read_parquet(D / area / "triage.parquet")
    ctrl = tri[~tri.flagged].sample(n_control, random_state=20261005)
    todo = pd.concat([tri[tri.flagged].assign(group="triage"), ctrl.assign(group="control")])
    hs = pd.read_parquet(D / area / "houses.parquet", columns=["oid", "fp_wkt"]).merge(todo[["oid", "group"]], on="oid")
    blds = buildings(area)
    bt = STRtree(blds)
    done_path = D / area / "beemaps_multi.parquet"
    rows = pd.read_parquet(done_path).to_dict("records") if done_path.exists() else []
    seen = {r["oid"] for r in rows}
    for h in hs.itertuples():
        if h.oid in seen:
            continue
        if views_downloaded() >= max_views:
            print("MAX_VIEWS reached", file=sys.stderr)
            break
        fp = wkt.loads(h.fp_wkt)
        x0, y0, x1, y1 = fp.buffer(60).bounds
        frames = post(box(x0, y0, x1, y1), {"catalog": "true", "headings": "true"}).get("frames", [])
        cands = qualifying(frames, fp, focal, blds, bt)
        chosen = choose(cands, k)
        if not chosen:
            rows.append({"oid": h.oid, "group": h.group, "n_frames": len(frames), "n_qualifying": 0, "path": None})
            continue
        for v in chosen:
            g = post(box(v["cx"] - 2, v["cy"] - 2, v["cx"] + 2, v["cy"] + 2), {"headings": "true"})
            m = [f for f in g.get("frames", []) if f.get("sequence") == v["sequence"] and f.get("idx") == v["idx"]]
            base = {"oid": h.oid, "group": h.group, "n_frames": len(frames), "n_qualifying": len(cands),
                    **{kk: vv for kk, vv in v.items() if kk != "rank"}}
            if not m:
                rows.append({**base, "path": None, "note": "frame not returned by URL query"})
                continue
            img = fetch_img(m[0]["url"])
            with open(LOG, "a") as fl:
                fl.write(json.dumps({"t": time.time(), "kind": "view", "sequence": v["sequence"], "idx": v["idx"],
                                     "usd": 0.005}) + "\n")
            path = out / f"{h.oid}_bm_{v['sequence']}_{v['idx']}.jpg"
            perspective_crop(img.convert("RGB"), v["off"], v["half_w"], v["focal"], v["hfov"]).save(path, quality=90)
            rows.append({**base, "path": str(path)})
        pd.DataFrame(rows).assign(provider="beemaps").to_parquet(done_path, index=False)
    df = pd.DataFrame(rows).assign(provider="beemaps")
    df.to_parquet(done_path, index=False)
    got = df[df.path.notna()]
    per = got.groupby("oid").size()
    print(f"{area}: houses tried {df.oid.nunique()} ({df.groupby('group').oid.nunique().to_dict()}); with >= 1 frame "
          f"{per.size} ({got.groupby('group').oid.nunique().to_dict()}); frames per house {per.describe()[['mean', '50%', 'max']].round(1).to_dict()}; "
          f"image views downloaded in total {views_downloaded()}")
    if len(got):
        print("capture months:", got.captured.dt.strftime("%Y-%m").value_counts().sort_index().to_dict())


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]))
