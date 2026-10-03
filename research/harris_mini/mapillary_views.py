"""Pick and crop Mapillary views of a random sample of headline houses.

Sample: a fixed-seed random permutation of headline houses (front door, precision tier A+B, lidar
ground present) in houses.parquet; the first N_CORE are the core sample (coverage), the first N are
processed (N > N_CORE extends the same random order to gain houses with views for accuracy). The answer-key value (ffe) is never read here; the sample and the view
choice use only the footprint, the image index and the image metadata.

A view qualifies when the camera is 8-45 m from the footprint, is not inside a building, the line from
the camera to the footprint centroid crosses no other building footprint (HCAD 2017 + lidar 2018
outlines), and the house is in the field of view:
  perspective  bearing to the centroid within the half-FOV of computed_compass_angle (FOV from
               camera_parameters focal, normalised by the larger image side), minus 3 deg margin;
  panorama     always; a rectilinear crop (>= 70 deg wide) is rendered centred on that bearing.
Ranking: capture date nearest 2019-07-01 (answer key captured 2018-03..2020-01), then distance
nearest 20 m. Up to 2 views per house. Crops are centred on the house, written to
data/harris_mini/<AREA>/views/, and listed in views.parquet.
Usage: python mapillary_views.py AREA N_CORE [N]
"""
import io, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np, pandas as pd, pyarrow.parquet as pq, requests
from PIL import Image
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
GRAPH = "https://graph.mapillary.com/"
DMIN, DMAX, MAXV = 8.0, 45.0, 2
REF = pd.Timestamp("2019-07-01", tz="UTC")
TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:6344", always_xy=True)
HDR = lambda: {"Authorization": f"OAuth {os.environ['MAPILLARY_ACCESS_TOKEN']}"}


def graph(ids: list[str], fields: str) -> dict:
    for attempt in range(6):
        try:
            d = requests.get(GRAPH, params=dict(ids=",".join(ids), fields=fields), headers=HDR(), timeout=120).json()
            if "error" in d:
                if d["error"].get("code") == 190: raise SystemExit("Mapillary rejected the token (error 190)")
                raise RuntimeError(d["error"].get("message"))
            return d
        except (requests.RequestException, ValueError, RuntimeError) as e:
            print("retry", attempt, type(e).__name__, str(e)[:100], file=sys.stderr); time.sleep(2 ** attempt)
    raise RuntimeError("graph failed")


def buildings(area: str) -> list[Polygon]:
    out = []
    for name in ("l25.parquet", "l26.parquet"):
        for r in pq.read_table(D / area / name, columns=["rings"]).to_pylist():
            if r["rings"]:
                rings = json.loads(r["rings"]); p = Polygon(rings[0], rings[1:]).buffer(0)
                if p.area > 20: out.append(p)
    return out


def sample(area: str, n: int) -> pd.DataFrame:
    h = pd.read_parquet(D / area / "houses.parquet",
                        columns=["oid", "loc", "prec", "e2018_lag", "fp_wkt", "x", "y"])
    h = h[(h["loc"] == "Front Door") & (h.prec <= 6) & h.e2018_lag.notna()].sort_values("oid")
    order = np.random.default_rng(20261003).permutation(len(h))
    h = h.iloc[order].assign(rank=np.arange(len(h)))
    return h.head(n).reset_index(drop=True)


def local_images(area: str, hs: pd.DataFrame) -> pd.DataFrame:
    """The area index misses images (about 20% in 0.002 deg spot checks), so also query a small box
    (footprint + 50 m) around every sampled house. Cached in mapillary_local.parquet."""
    cache = D / area / f"mapillary_local_{len(hs)}.parquet"
    if cache.exists(): return pd.read_parquet(cache)
    from mapillary_index import FIELDS, get
    to_ll = Transformer.from_crs("EPSG:6344", "EPSG:4326", always_xy=True)
    def one(fw):
        x0, y0, x1, y1 = wkt.loads(fw).buffer(50).bounds
        (a, b), (c, d) = to_ll.transform(x0, y0), to_ll.transform(x1, y1)
        return get(dict(fields=FIELDS, bbox=f"{a:.6f},{b:.6f},{c:.6f},{d:.6f}", limit=2000)).get("data", [])
    with ThreadPoolExecutor(8) as ex:
        rows = [r for rs in ex.map(one, hs.fp_wkt) for r in rs]
    df = pd.DataFrame(rows).drop_duplicates("id")
    df["lon"] = df.computed_geometry.map(lambda g: g["coordinates"][0] if isinstance(g, dict) else np.nan)
    df["lat"] = df.computed_geometry.map(lambda g: g["coordinates"][1] if isinstance(g, dict) else np.nan)
    df["captured"] = pd.to_datetime(df.captured_at, unit="ms", utc=True)
    df = df.drop(columns=["computed_geometry"])
    df.to_parquet(cache, index=False)
    return df


def candidates(area: str, hs: pd.DataFrame) -> pd.DataFrame:
    ix0 = pd.read_parquet(D / area / "mapillary_index.parquet")
    loc = local_images(area, hs)
    ix = pd.concat([ix0, loc]).drop_duplicates("id").dropna(subset=["lon", "computed_compass_angle"])
    ix = ix.reset_index(drop=True)
    print(f"{area}: images near sampled houses: local query {len(loc)}, of which missing from the area "
          f"index {len(set(loc.id) - set(ix0.id))}")
    ix["cx"], ix["cy"] = TO_UTM.transform(ix.lon.values, ix.lat.values)
    blds = buildings(area); bt = STRtree(blds)
    it = STRtree([Point(x, y) for x, y in zip(ix.cx, ix.cy)])
    rows = []
    for h in hs.itertuples():
        fp = wkt.loads(h.fp_wkt); c = fp.centroid
        for j in it.query(fp.buffer(DMAX)):
            cam = Point(ix.cx.iat[j], ix.cy.iat[j]); d = fp.distance(cam)
            if not DMIN <= d <= DMAX: continue
            seg = LineString([cam, c])
            blocked = False
            for k in bt.query(seg):
                b = blds[k]
                if b.contains(cam): blocked = True; break
                if b.intersection(fp).area > 0.3 * min(b.area, fp.area): continue  # the target itself
                if b.intersects(seg): blocked = True; break
            if blocked: continue
            brg = np.degrees(np.arctan2(c.x - cam.x, c.y - cam.y)) % 360
            # angular half-width of the footprint seen from the camera
            angs = [np.degrees(np.arctan2(px - cam.x, py - cam.y)) for px, py in fp.exterior.coords]
            half = max(abs((a - brg + 180) % 360 - 180) for a in angs)
            off = (brg - ix.computed_compass_angle.iat[j] + 180) % 360 - 180
            rows.append(dict(oid=h.oid, image_id=ix.id.iat[j], is_pano=bool(ix.is_pano.iat[j]),
                             captured=ix.captured.iat[j], dist_m=d, bearing=brg, off=off, half_w=half,
                             compass=ix.computed_compass_angle.iat[j]))
    return pd.DataFrame(rows)


def rectilinear(pano: Image.Image, yaw: float, hfov: float, W=1024, H=768, pitch=-4.0) -> Image.Image:
    """yaw relative to the pano centre column (deg); bilinear sample of an equirectangular image."""
    a = np.asarray(pano.convert("RGB"), dtype=np.float32); h, w = a.shape[:2]
    f = W / 2 / np.tan(np.radians(hfov / 2))
    i, j = np.meshgrid(np.arange(W) - W / 2 + 0.5, np.arange(H) - H / 2 + 0.5)
    x, y, z = i, -j, np.full_like(i, f)  # camera: x right, y up, z forward
    p = np.radians(pitch)
    y, z = y * np.cos(p) + z * np.sin(p), -y * np.sin(p) + z * np.cos(p)
    lon = np.degrees(np.arctan2(x, z)) + yaw; lat = np.degrees(np.arctan2(y, np.hypot(x, z)))
    u = ((lon / 360 + 0.5) % 1) * w - 0.5; v = (0.5 - lat / 180) * h - 0.5
    u0 = np.floor(u).astype(int); v0 = np.clip(np.floor(v).astype(int), 0, h - 2)
    du, dv = (u - u0)[..., None], np.clip(v - v0, 0, 1)[..., None]
    u0 %= w; u1 = (u0 + 1) % w
    out = (a[v0, u0] * (1 - du) * (1 - dv) + a[v0, u1] * du * (1 - dv)
           + a[v0 + 1, u0] * (1 - du) * dv + a[v0 + 1, u1] * du * dv)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def perspective_crop(img: Image.Image, off: float, half_w: float, focal: float, hfov: float) -> Image.Image:
    """Crop columns around the house (centred on it, grey padding where the frame ends)."""
    w, h = img.size; fpx = focal * max(w, h)
    cx = w / 2 + fpx * np.tan(np.radians(off))
    span = min(max(half_w + 12, 25), 60)
    lim = hfov / 2
    hw = int(max(abs(fpx * np.tan(np.radians(np.clip(off + s, -lim, lim))) - fpx * np.tan(np.radians(off)))
                 for s in (-span, span)))
    hw = max(min(hw, int(0.45 * w)), 64)
    out = Image.new("RGB", (2 * hw, h), (128, 128, 128))
    l = int(cx) - hw
    out.paste(img.crop((max(l, 0), 0, min(l + 2 * hw, w), h)), (max(-l, 0), 0))
    return out


def fetch_img(url: str) -> Image.Image:
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=120); r.raise_for_status(); return Image.open(io.BytesIO(r.content))
        except Exception as e:  # noqa: BLE001
            print("img retry", attempt, type(e).__name__, file=sys.stderr); time.sleep(2 ** attempt)
    raise RuntimeError("image download failed")


def main(area: str, n_core: int, n: int):
    hs = sample(area, n)
    hs.assign(core=hs["rank"] < n_core)[["oid", "rank", "core"]].to_csv(D / area / "image_sample.csv", index=False)
    cand = candidates(area, hs)
    print(f"{area}: {len(hs)} sampled houses; {len(cand)} candidate views for {cand.oid.nunique()} houses "
          f"(geometry + occlusion filter, before FOV)")
    # camera metadata for perspective candidates that could plausibly be in view
    pc = cand[~cand.is_pano & (cand.off.abs() <= 45)]
    ids = sorted(pc.image_id.unique())
    meta = {}
    for s in range(0, len(ids), 50):
        meta.update(graph(ids[s:s + 50], "id,width,height,camera_parameters"))
    def fov(iid):
        m = meta.get(iid, {}); cp = m.get("camera_parameters")
        return 2 * np.degrees(np.arctan(0.5 / cp[0])) if cp and cp[0] > 0 else np.nan
    cand["hfov"] = [fov(i) if not p else 360.0 for i, p in zip(cand.image_id, cand.is_pano)]
    cand["focal"] = [(meta.get(i, {}).get("camera_parameters") or [np.nan])[0] if not p else np.nan
                     for i, p in zip(cand.image_id, cand.is_pano)]
    ok = cand.is_pano | (cand.off.abs() <= cand.hfov / 2 - 3)
    cand = cand[ok].copy()
    cand["age_days"] = (cand.captured - REF).dt.days.abs()
    cand["rank_key"] = (cand.age_days // 182) * 1000 + (cand.dist_m - 20).abs()
    sel = cand.sort_values(["oid", "rank_key"]).groupby("oid").head(MAXV).reset_index(drop=True)
    print(f"{area}: {cand.oid.nunique()} houses with >=1 view in FOV; selected {len(sel)} views "
          f"({int(sel.is_pano.sum())} pano)")
    urls = {}
    ids = sorted(sel.image_id.unique())
    for s in range(0, len(ids), 50):
        for k, v in graph(ids[s:s + 50], "id,thumb_2048_url,thumb_original_url").items():
            urls[k] = v
    out = D / area / "views"; out.mkdir(exist_ok=True)
    def job(r):
        path = out / f"{r.oid}_{r.image_id}.jpg"
        if path.exists(): return str(path)
        u = urls[r.image_id]
        try:
            if r.is_pano:
                im = fetch_img(u.get("thumb_original_url") or u["thumb_2048_url"])
                crop = rectilinear(im, r.off, max(70.0, min(2 * r.half_w + 20, 100.0)))
            else:
                im = fetch_img(u["thumb_2048_url"])
                crop = perspective_crop(im, r.off, r.half_w, r.focal, r.hfov)
            crop.save(path, quality=90)
            return str(path)
        except Exception as e:  # noqa: BLE001
            print("fail", r.image_id, e, file=sys.stderr); return None
    with ThreadPoolExecutor(8) as ex:
        sel["path"] = list(ex.map(job, sel.itertuples()))
    sel.to_parquet(D / area / "views.parquet", index=False)
    print(f"{area}: downloaded {sel.path.notna().sum()} crops; capture year of selected views:")
    print(sel.captured.dt.year.value_counts().sort_index().to_string())


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else int(sys.argv[2]))
