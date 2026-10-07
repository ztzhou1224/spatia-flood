"""Lidar feature job that runs on a throwaway box (started by box.py; inputs prepared by prepare.py).

The box holds no credentials: every R2 object it reads or writes is a presigned URL in /opt/flood/urls.json
(written by cloud-init). USGS tiles are public HTTPS. Steps:
  1. fetch buildings.parquet (building_id, footprint WKB in CRS84) and tiles.json (LPC + 1 m DEM tile URLs);
  2. download every tile (size checked against Content-Length);
  3. ground from the DEM per building (features.ground_stats; buildings straddling DEM tiles read a mosaic);
  4. point-cloud features per building (features.lpc_stats), tile by tile in worker processes; a building whose
     search disc crosses tile edges collects its returns from every tile it touches before it is scored;
  5. upload features.parquet and meta.json (CRS read from the files, vertical CRS from the LAZ header, timings).
A heartbeat uploads status.json every 60 s; the log is uploaded at each stage and at the end.
Usage (on the box): python job.py /opt/flood/urls.json /mnt/work [--workers N]
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool
from pathlib import Path

import laspy
import numpy as np
import pandas as pd
import rasterio
import requests
import shapely
from pyproj import CRS, Transformer
from rasterio.merge import merge
from rasterio.windows import from_bounds
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ept import node_box  # noqa: E402
from features import DROP, LPC_COLS, MAX_AREA_M2, USFT, disc_radius, ground_stats, lpc_stats  # noqa: E402

METRIC_TWIN = {6443: 6442, 6438: 6437, 6441: 6440}  # NAD83(2011) Florida West / East / North: ftUS -> metres
LOG = io.StringIO()
STATUS: dict = {"stage": "start", "started": time.time(), "timings_s": {}}
log = logging.getLogger("job")


def setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout), logging.StreamHandler(LOG)):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def fetch(url: str) -> bytes:
    if url.startswith("file://"):  # local test runs
        return Path(url[7:]).read_bytes()
    r = requests.get(url, timeout=600)
    r.raise_for_status()
    return r.content


def put(url: str, data: bytes, ctype: str = "application/octet-stream") -> None:
    if url.startswith("file://"):
        Path(url[7:]).write_bytes(data)
        return
    for attempt in range(5):
        try:
            r = requests.put(url, data=data, headers={"Content-Type": ctype}, timeout=600)
            r.raise_for_status()
            return
        except requests.RequestException:
            time.sleep(2 ** attempt)
    raise RuntimeError("upload failed after 5 attempts")


def heartbeat(urls: dict, stop: threading.Event) -> None:
    while not stop.wait(60):
        try:
            STATUS["t"] = time.time()
            put(urls["status"], json.dumps(STATUS).encode(), "application/json")
        except Exception:  # noqa: BLE001 - a missed heartbeat must not kill the job
            pass


def stage(name: str, urls: dict) -> None:
    now = time.time()
    if "stage_t" in STATUS:
        STATUS["timings_s"][STATUS["stage"]] = round(now - STATUS["stage_t"])
    STATUS.update(stage=name, stage_t=now, t=now)
    log.info("stage %s", name)
    put(urls["status"], json.dumps(STATUS).encode(), "application/json")
    put(urls["log"], LOG.getvalue().encode(), "text/plain")


def download(url: str, dest: Path) -> int:
    if url.startswith("file://"):  # local test runs: link the tile instead of copying it
        if not dest.exists():
            dest.symlink_to(url[7:])
        return dest.stat().st_size
    if dest.exists() and dest.with_suffix(dest.suffix + ".ok").exists():
        return dest.stat().st_size
    for attempt in range(10):  # backoff 1 s .. 8.5 min, ~17 min in all: rides out a short outage of the server
        try:
            with requests.get(url, stream=True, timeout=(30, 300)) as r:
                r.raise_for_status()
                want = int(r.headers.get("Content-Length", -1))
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 22):
                        f.write(chunk)
                if want >= 0 and tmp.stat().st_size != want:
                    raise OSError(f"short read {tmp.stat().st_size} of {want}")
                tmp.rename(dest)
                dest.with_suffix(dest.suffix + ".ok").touch()
                return dest.stat().st_size
        except (requests.RequestException, OSError) as e:
            log.info("retry %s (%s)", dest.name, str(e)[:200])
            time.sleep(2 ** attempt)
    raise RuntimeError(f"download failed: {url}")


# ---------------------------------------------------------------- ground (DEM)

def _dem_worker(args):
    path, all_paths, items = args
    out = []
    with rasterio.open(path) as r:
        b = r.bounds
        for i, g in items:
            x0, y0, x1, y1 = g.bounds
            x0, y0, x1, y1 = x0 - 31, y0 - 31, x1 + 31, y1 + 31
            if b.left < x0 and x1 < b.right and b.bottom < y0 and y1 < b.top:
                win = from_bounds(x0, y0, x1, y1, r.transform).round_offsets().round_lengths()
                a = r.read(1, window=win, masked=True).filled(np.nan).astype("float64")
                t = r.window_transform(win)
                tile = Path(path).name
            else:  # straddles DEM tiles: mosaic of every tile touching the window
                srcs = [rasterio.open(p) for p in all_paths]
                hit = [s for s in srcs if s.bounds.left < x1 and x0 < s.bounds.right and s.bounds.bottom < y1 and y0 < s.bounds.top]
                tile = "+".join(sorted(Path(s.name).name for s in hit))
                if hit:
                    a, t = merge(hit, bounds=(x0, y0, x1, y1), nodata=np.nan, dtype="float64")
                    a = a[0]
                for s in srcs:
                    s.close()
                if not hit:
                    out.append((i, {"dem_tiles": ""}))
                    continue
            a[(a < -1e5) | (a > 1e5)] = np.nan
            rec = ground_stats(g, a, t)
            rec["dem_tiles"] = tile
            out.append((i, rec))
    return out


def ground(fp_dem: list, dem_paths: list[Path], workers: int) -> pd.DataFrame:
    bounds = []
    for p in dem_paths:
        with rasterio.open(p) as r:
            bounds.append(r.bounds)
    cent = shapely.centroid(np.array(fp_dem, dtype=object))
    cx, cy = shapely.get_x(cent), shapely.get_y(cent)
    assign = np.full(len(fp_dem), -1)
    for k, b in enumerate(bounds):  # first tile holding the centroid
        m = (assign < 0) & (cx >= b.left) & (cx < b.right) & (cy >= b.bottom) & (cy < b.top)
        assign[m] = k
    jobs = [(str(dem_paths[k]), [str(p) for p in dem_paths], [(i, fp_dem[i]) for i in np.where(assign == k)[0]])
            for k in range(len(dem_paths))]
    jobs = [j for j in jobs if j[2]]
    rows: dict = {}
    with Pool(workers) as pool:
        for n, res in enumerate(pool.imap_unordered(_dem_worker, jobs), 1):
            rows.update(dict(res))
            STATUS["dem_done"] = n
            log.info("dem tile %d of %d done", n, len(jobs))
    g = pd.DataFrame.from_dict(rows, orient="index")
    g = g.reindex(range(len(fp_dem)))
    g["ground_status"] = np.where(assign < 0, "no_coverage", np.where(g["lag"].notna(), "ok", "not_determinable"))
    return g


# ---------------------------------------------------------------- point cloud

def load_points(src: tuple) -> tuple[np.ndarray, ...]:
    """x, y, z in metres (metric CRS) and class (+100 for single returns), classes in DROP removed.

    ("laz", path, scale): one LAZ tile, US-foot tiles scaled to metres (the metric twin CRS).
    ("ept", base, box, keys, metric): one EPT chunk: the listed nodes, points clipped to box (EPSG:3857,
    half-open, so a point belongs to one chunk only), x / y transformed 3857 -> metric with the 'EPSG:3857' tag
    (always_xy); z is already metres NAVD88 in the EPT build (checked against the LAZ tiles: ept.py docstring)."""
    if src[0] == "laz":
        _, path, scale = src
        las = laspy.read(path)
        cls = np.asarray(las.classification)
        keep = ~np.isin(cls, DROP)
        x = np.asarray(las.x)[keep] * scale
        y = np.asarray(las.y)[keep] * scale
        z = np.asarray(las.z)[keep] * scale
        c = np.where(np.asarray(las.number_of_returns)[keep] == 1, cls[keep] + 100, cls[keep]).astype(np.int16)
        return x, y, z, c
    _, base, box, keys, metric = src
    xs, ys, zs, cs = [], [], [], []
    for k in keys:
        if base.startswith("file://"):
            las = laspy.read(f"{base[7:]}/ept-data/{k}.laz")
        else:
            las = laspy.read(io.BytesIO(fetch_retry(f"{base}/ept-data/{k}.laz")))
        x, y = np.asarray(las.x), np.asarray(las.y)
        cls = np.asarray(las.classification)
        keep = (x >= box[0]) & (x < box[2]) & (y >= box[1]) & (y < box[3]) & ~np.isin(cls, DROP)
        xs.append(x[keep])
        ys.append(y[keep])
        zs.append(np.asarray(las.z)[keep])
        cs.append(np.where(np.asarray(las.number_of_returns)[keep] == 1, cls[keep] + 100, cls[keep]).astype(np.int16))
    x, y = np.concatenate(xs), np.concatenate(ys)
    if len(x):
        x, y = Transformer.from_crs("EPSG:3857", metric, always_xy=True).transform(x, y)
    return np.asarray(x), np.asarray(y), np.concatenate(zs), np.concatenate(cs)


def fetch_retry(url: str) -> bytes:
    for attempt in range(8):
        try:
            r = requests.get(url, timeout=(30, 300))
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"fetch failed: {url}")


def _lpc_worker(args):
    name, src, items = args  # items: (i, cx, cy, r, fp, lag_ft, complete_here)
    x, y, z, c = load_points(src)
    if not len(x):
        return name, [(i, None) for i, *_, done in items if done], [(i, np.empty((0, 4))) for i, *_, done in items if not done]
    # coarse 4 m grid of cells touched by any search disc: points elsewhere are never read
    gx0, gy0, cell = x.min(), y.min(), 4.0
    nx, ny = int((x.max() - gx0) // cell) + 2, int((y.max() - gy0) // cell) + 2
    need = np.zeros((nx, ny), bool)
    for _, cx, cy, r, *_ in items:
        i0, i1 = int(max((cx - r - gx0) // cell, 0)), int(min((cx + r - gx0) // cell + 1, nx - 1))
        j0, j1 = int(max((cy - r - gy0) // cell, 0)), int(min((cy + r - gy0) // cell + 1, ny - 1))
        if i1 >= i0 and j1 >= j0:
            need[i0:i1 + 1, j0:j1 + 1] = True
    k = need[((x - gx0) // cell).astype(int), ((y - gy0) // cell).astype(int)]
    pts = np.c_[x[k], y[k], z[k], c[k]]
    del x, y, z, c, k
    done, partial = [], []
    if len(pts):
        tree = cKDTree(pts[:, :2])
        for i, cx, cy, r, fp, lag, complete in items:
            idx = np.asarray(tree.query_ball_point([cx, cy], r), dtype=int)
            sub = pts[idx]
            if complete:
                done.append((i, lpc_stats(fp, sub, lag) if len(sub) else None))
            else:
                partial.append((i, sub))
    else:
        for i, *_, complete in items:
            if complete:
                done.append((i, None))
            else:
                partial.append((i, np.empty((0, 4))))
    return name, done, partial


def lpc(fp_m: list, lag_ft: np.ndarray, tiles: list[tuple[str, tuple, tuple]], workers: int) -> pd.DataFrame:
    """tiles: (name, (x0, y0, x1, y1) in the metric CRS, load_points source)."""
    n = len(fp_m)
    area = shapely.area(np.array(fp_m, dtype=object))
    cent = shapely.centroid(np.array(fp_m, dtype=object))
    cx, cy = shapely.get_x(cent), shapely.get_y(cent)
    status = np.array(["ok"] * n, dtype=object)
    status[np.isnan(lag_ft)] = "no_ground"
    status[area > MAX_AREA_M2] = "too_large"
    todo = np.where(status == "ok")[0]
    rad = {i: disc_radius(fp_m[i]) for i in todo}
    tb = np.array([b for _, b, _ in tiles])  # x0, y0, x1, y1 in metres (EPT chunks: box of the reprojected chunk)
    per_tile: dict[int, list] = {k: [] for k in range(len(tiles))}
    need = np.zeros(n, int)
    for i in todo:
        r = rad[i]
        hit = np.where((tb[:, 0] < cx[i] + r) & (cx[i] - r < tb[:, 2]) & (tb[:, 1] < cy[i] + r) & (cy[i] - r < tb[:, 3]))[0]
        need[i] = len(hit)
        for k in hit:
            per_tile[k].append(i)
    status[(status == "ok") & (need == 0)] = "no_coverage"
    jobs = [(tiles[k][0], tiles[k][2],
             [(i, cx[i], cy[i], rad[i], fp_m[i], lag_ft[i], need[i] == 1) for i in per_tile[k]])
            for k in sorted(per_tile, key=lambda k: (tb[k, 1], tb[k, 0])) if per_tile[k]]
    rows: dict = {}
    parts: dict[int, list] = {}
    got = np.zeros(n, int)
    with Pool(workers) as pool:
        for m, (name, done, partial) in enumerate(pool.imap_unordered(_lpc_worker, jobs), 1):
            for i, rec in done:
                rows[i] = rec
            for i, sub in partial:
                parts.setdefault(i, []).append(sub)
                got[i] += 1
                if got[i] == need[i]:
                    a = np.vstack(parts.pop(i))
                    rows[i] = lpc_stats(fp_m[i], a, lag_ft[i]) if len(a) else None
            STATUS["lpc_done"] = m
            STATUS["lpc_pending_buildings"] = len(parts)
            log.info("lpc tile %d of %d (%s): %d finished, %d buildings waiting on neighbours",
                     m, len(jobs), name, len(done), len(parts))
    out = pd.DataFrame.from_dict({i: r for i, r in rows.items() if r}, orient="index").reindex(range(n))
    out = out[LPC_COLS]
    status[(status == "ok") & out["n_in"].isna().values] = "no_points"
    status[(status == "ok") & (out["n_in"].fillna(0).values < 5)] = "not_determinable"
    out["lpc_status"] = status
    out["lpc_tiles"] = need
    return out


def ept_chunks(e: dict, metric: str) -> list[tuple[str, tuple, tuple]]:
    """One chunk per depth-D cell (D = e["chunk_depth"]) listed in e["chunks"]: the nodes at depth >= D inside it,
    plus the coarser nodes (ancestors) covering it; its metric box is the box of its four reprojected corners."""
    cube, d0 = e["cube"], e["chunk_depth"]
    deep: dict[tuple[int, int], list[str]] = {}
    coarse: list[tuple[int, int, int, str]] = []
    for k in e["nodes"]:
        d, x, y, _ = map(int, k.split("-"))
        if d >= d0:
            deep.setdefault((x >> (d - d0), y >> (d - d0)), []).append(k)
        else:
            coarse.append((d, x, y, k))
    tr = Transformer.from_crs("EPSG:3857", metric, always_xy=True)
    out = []
    for cx, cy in (tuple(c) for c in e["chunks"]):
        keys = deep.get((cx, cy), []) + [k for d, x, y, k in coarse if (cx >> (d0 - d), cy >> (d0 - d)) == (x, y)]
        box = node_box(f"{d0}-{cx}-{cy}-0", cube)
        xs, ys = tr.transform([box[0], box[2], box[0], box[2]], [box[1], box[1], box[3], box[3]])
        out.append((f"{d0}-{cx}-{cy}", (min(xs), min(ys), max(xs), max(ys)), ("ept", e["base"], box, keys, metric)))
    return out


# ---------------------------------------------------------------- main

def run(urls: dict, work: Path, workers: int) -> None:
    work.mkdir(parents=True, exist_ok=True)
    stage("inputs", urls)
    b = pd.read_parquet(io.BytesIO(fetch(urls["buildings"])))
    tl = json.loads(fetch(urls["tiles"]))
    log.info("buildings %d; lpc tiles %d; dem tiles %d", len(b), len(tl["lpc"]), len(tl["dem"]))

    stage("download", urls)
    (work / "lpc").mkdir(exist_ok=True)
    (work / "dem").mkdir(exist_ok=True)
    lpc_list = [] if "ept" in tl else tl["lpc"]  # an EPT source is streamed chunk by chunk, never stored
    jobs = [(t["url"], work / "lpc" / t["url"].rsplit("/", 1)[1]) for t in lpc_list] + \
           [(t["url"], work / "dem" / t["url"].rsplit("/", 1)[1]) for t in tl["dem"]]
    total = 0
    with ThreadPoolExecutor(16) as ex:
        for k, size in enumerate(ex.map(lambda a: download(*a), jobs), 1):
            total += size
            STATUS["downloaded"] = k
            STATUS["downloaded_gb"] = round(total / 1e9, 2)
    log.info("downloaded %d files, %.1f GB", len(jobs), total / 1e9)

    stage("crs", urls)
    lpc_paths = [work / "lpc" / t["url"].rsplit("/", 1)[1] for t in lpc_list]
    dem_paths = [work / "dem" / t["url"].rsplit("/", 1)[1] for t in tl["dem"]]
    hcrs_set, vcrs_set, tiles = set(), set(), []
    for p in lpc_paths:
        with laspy.open(p) as f:
            c = f.header.parse_crs()
            mins, maxs = f.header.mins, f.header.maxs
        if c is None:
            raise RuntimeError(f"{p.name}: no CRS in the LAZ header")
        h = c.sub_crs_list[0] if c.is_compound else c
        vcrs_set.add(c.sub_crs_list[1].name if c.is_compound else "not in header")
        sc = USFT if "foot" in h.axis_info[0].unit_name.lower() else 1.0
        epsg = h.to_epsg()
        if sc != 1.0:
            if epsg not in METRIC_TWIN:
                raise RuntimeError(f"{p.name}: US-foot CRS EPSG:{epsg} has no metric twin listed")
            epsg = METRIC_TWIN[epsg]
        hcrs_set.add(epsg)
        tiles.append((p.name, (mins[0] * sc, mins[1] * sc, maxs[0] * sc, maxs[1] * sc), ("laz", str(p), sc)))
    if "ept" in tl:
        e = tl["ept"]
        metric = e["metric_crs"]
        vcrs_set.add(e["vertical"])
        tiles = ept_chunks(e, metric)
    else:
        if len(hcrs_set) != 1:
            raise RuntimeError(f"LPC tiles in several CRSs: {hcrs_set}")
        metric = f"EPSG:{hcrs_set.pop()}"
    dem_crs = set()
    for p in dem_paths:
        with rasterio.open(p) as r:
            dem_crs.add(CRS.from_user_input(r.crs).to_string())
    if len(dem_crs) != 1:
        raise RuntimeError(f"DEM tiles in several CRSs: {dem_crs}")
    dem = dem_crs.pop()
    log.info("point cloud CRS -> %s (vertical: %s); DEM CRS %s", metric, vcrs_set, dem)

    geoms = shapely.from_wkb(b["wkb"].values)
    geoms = shapely.make_valid(geoms)
    to_m = Transformer.from_crs("EPSG:4326", metric, always_xy=True)
    to_dem = Transformer.from_crs("EPSG:4326", dem, always_xy=True)
    fp_m = list(shapely.transform(geoms, lambda xy: np.c_[to_m.transform(xy[:, 0], xy[:, 1])]))
    fp_dem = list(shapely.transform(geoms, lambda xy: np.c_[to_dem.transform(xy[:, 0], xy[:, 1])]))

    stage("ground", urls)
    g = ground(fp_dem, dem_paths, workers)
    log.info("ground: %s", g.ground_status.value_counts().to_dict())

    stage("lpc", urls)
    f = lpc(fp_m, g["lag"].values.astype(float), tiles, max(1, workers - 2))
    log.info("lpc: %s", f.lpc_status.value_counts().to_dict())

    stage("upload", urls)
    out = pd.concat([b[["building_id"]].reset_index(drop=True),
                     pd.Series(shapely.area(np.array(fp_m, dtype=object)), name="fp_area_m2"),
                     g.add_prefix("g_").rename(columns={"g_ground_status": "ground_status", "g_dem_tiles": "dem_tiles"}),
                     f], axis=1)
    buf = io.BytesIO()
    out.to_parquet(buf, index=False)
    put(urls["features"], buf.getvalue())
    meta = {"rows": len(out), "metric_crs": metric, "fp_area_crs": metric, "dem_crs": dem,
            "lpc_vertical_crs": sorted(vcrs_set), "units": "ft (US survey) NAVD88 for g_* and heights; m2 for area",
            "lpc_tiles": len(tiles), "lpc_source": "ept" if "ept" in tl else "laz", "dem_tiles": len(dem_paths), "downloaded_gb": STATUS.get("downloaded_gb"),
            "ground_status": g.ground_status.value_counts().to_dict(), "lpc_status": f.lpc_status.value_counts().to_dict(),
            "workers": workers, "cpu_count": os.cpu_count(), "timings_s": STATUS["timings_s"]}
    put(urls["meta"], json.dumps(meta, indent=1, default=str).encode(), "application/json")
    stage("done", urls)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls")
    ap.add_argument("work")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args()
    setup_logging()
    urls = json.loads(Path(a.urls).read_text())
    stop = threading.Event()
    threading.Thread(target=heartbeat, args=(urls, stop), daemon=True).start()
    try:
        run(urls, Path(a.work), a.workers)
    except Exception:  # noqa: BLE001 - report the failure through R2, then exit non-zero
        log.error(traceback.format_exc())
        STATUS.update(stage="failed", error=traceback.format_exc()[-2000:], t=time.time())
        put(urls["status"], json.dumps(STATUS).encode(), "application/json")
        put(urls["log"], LOG.getvalue().encode(), "text/plain")
        sys.exit(1)
    finally:
        stop.set()


if __name__ == "__main__":
    main()
