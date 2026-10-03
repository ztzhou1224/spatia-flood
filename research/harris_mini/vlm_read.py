"""Read the front-door height of the house in each Mapillary crop with a Gemini VLM (REST).

Input: data/harris_mini/<AREA>/views.parquet + crops. Output: data/harris_mini/<AREA>/vlm_reads.parquet.
Every response is cached as JSON in data/harris_mini/<AREA>/vlm/ (keyed by model + prompt version), so
reruns cost nothing. Every billed call is appended to data/harris_mini/vlm_calls.jsonl; the script
refuses to exceed BUDGET calls in total. The model sees only the image crop, the camera type and the
camera-to-footprint distance; never the answer key.
Usage: python vlm_read.py [--beemaps] AREA [AREA ...]
"""
import base64, io, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
import pandas as pd, requests
from PIL import Image

D = Path(__file__).resolve().parents[2] / "data" / "harris_mini"
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
PROMPT_V = "v2"  # v2 = v1 prompt + mediaResolution HIGH (1290 image tokens vs 258)
BUDGET = 2500
LOG = D / "vlm_calls.jsonl"
LOCK = Lock()

PROMPT = """You are measuring a house from a street-level photo (Mapillary). The TARGET house is the one
in the horizontal CENTRE of this image; ignore other houses. The camera was about {dist:.0f} m from the
target's footprint ({kind}). Grey bars at the image edges are padding, not content.

Estimate how high the front-door threshold (the floor level at the main entry door) sits above the
ground directly in front of the house. Use visible cues: number of steps up to the door (a typical
step is about 0.6 ft / 7 in), stoop or porch height, exposed foundation, piers, crawlspace vents,
garage-door top vs door, brick courses (about 0.22 ft each) and siding laps. Slab-on-grade houses in
Houston usually have the door 0.5-1.5 ft above ground; raised houses can be 3-12 ft.

Return JSON only with exactly these keys:
house_visible (bool), front_door_visible (bool), steps_to_door (integer or null),
door_threshold_height_above_ground_ft (number or null; null if you cannot judge it),
foundation ("slab" | "raised_crawlspace" | "piers_or_stilts" | "unknown"),
lower_level_enclosure_visible (bool; an enclosed or garage level under a raised living floor),
confidence (number 0-1 for the height estimate), notes (string, at most 20 words)."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "house_visible": {"type": "BOOLEAN"},
        "front_door_visible": {"type": "BOOLEAN"},
        "steps_to_door": {"type": "INTEGER", "nullable": True},
        "door_threshold_height_above_ground_ft": {"type": "NUMBER", "nullable": True},
        "foundation": {"type": "STRING", "enum": ["slab", "raised_crawlspace", "piers_or_stilts", "unknown"]},
        "lower_level_enclosure_visible": {"type": "BOOLEAN"},
        "confidence": {"type": "NUMBER"},
        "notes": {"type": "STRING"},
    },
    "required": ["house_visible", "front_door_visible", "steps_to_door",
                 "door_threshold_height_above_ground_ft", "foundation",
                 "lower_level_enclosure_visible", "confidence", "notes"],
}


def calls_so_far() -> int:
    return sum(1 for _ in open(LOG)) if LOG.exists() else 0


def jpeg_b64(path: str, maxside: int = 1536) -> str:
    im = Image.open(path).convert("RGB"); im.thumbnail((maxside, maxside))
    b = io.BytesIO(); im.save(b, "JPEG", quality=90)
    return base64.b64encode(b.getvalue()).decode()


def call(path: str, dist: float, is_pano: bool) -> dict:
    body = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": "image/jpeg", "data": jpeg_b64(path)}},
            {"text": PROMPT.format(dist=dist, kind="crop of a 360 panorama" if is_pano else "phone/dashcam photo")},
        ]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                             "responseSchema": SCHEMA, "mediaResolution": "MEDIA_RESOLUTION_HIGH",
                             "thinkingConfig": {"thinkingBudget": 1024}},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    for attempt in range(6):
        with LOCK:
            if calls_so_far() >= BUDGET: raise SystemExit(f"VLM budget of {BUDGET} calls reached")
        r = requests.post(url, json=body, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, timeout=180)
        if r.status_code == 200 or r.status_code == 400:
            with LOCK, open(LOG, "a") as f:
                f.write(json.dumps({"t": time.time(), "model": MODEL, "status": r.status_code,
                                    "usage": r.json().get("usageMetadata", {})}) + "\n")
        if r.status_code == 200: return r.json()
        print("http", r.status_code, r.text[:200], file=sys.stderr)
        if r.status_code == 400: raise RuntimeError(r.text[:300])
        time.sleep(min(60, 2 ** attempt * 2))
    raise RuntimeError("gemini failed")


def read_one(r) -> dict:
    cache = D / r.area / "vlm" / f"{r.oid}_{r.image_id}_{MODEL}_{PROMPT_V}.json"
    if cache.exists():
        resp = json.loads(cache.read_text())
    else:
        resp = call(r.path, r.dist_m, r.is_pano)
        cache.write_text(json.dumps(resp))
    out = dict(oid=r.oid, image_id=r.image_id)
    try:
        out.update(json.loads(resp["candidates"][0]["content"]["parts"][-1]["text"]))
        out["parse_ok"] = True
    except Exception:  # noqa: BLE001
        out["parse_ok"] = False
    u = resp.get("usageMetadata", {})
    out.update(in_tok=u.get("promptTokenCount"), out_tok=u.get("candidatesTokenCount"),
               think_tok=u.get("thoughtsTokenCount"))
    return out


if __name__ == "__main__":
    limit = int(os.environ.get("VLM_LIMIT", "0"))
    bm = "--beemaps" in sys.argv  # Bee Maps crops (provider=beemaps), read into their own table
    for area in [a for a in sys.argv[1:] if not a.startswith("--")]:
        v = pd.read_parquet(D / area / ("beemaps_views.parquet" if bm else "views.parquet"))
        v = v[v.path.notna()].assign(area=area)
        if bm:
            v = v.assign(image_id="bm_" + v.sequence.astype(str) + "_" + v.idx.astype(int).astype(str), is_pano=False)
        if limit: v = v.head(limit)
        (D / area / "vlm").mkdir(exist_ok=True)
        with ThreadPoolExecutor(6) as ex:
            rows = list(ex.map(read_one, v.itertuples()))
        df = pd.DataFrame(rows)
        if bm: df["provider"] = "beemaps"
        if not limit: df.to_parquet(D / area / ("beemaps_vlm_reads.parquet" if bm else "vlm_reads.parquet"), index=False)
        print(f"{area}: {len(df)} reads, parsed {int(df.parse_ok.sum())}; "
              f"house visible {int(df.get('house_visible', pd.Series(dtype=bool)).fillna(False).sum())}, "
              f"door visible {int(df.get('front_door_visible', pd.Series(dtype=bool)).fillna(False).sum())}, "
              f"height {int(df.get('door_threshold_height_above_ground_ft', pd.Series(dtype=float)).notna().sum())}")
    print("billed calls so far:", calls_so_far())
