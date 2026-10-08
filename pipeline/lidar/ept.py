"""Read a USGS Entwine Point Tile (EPT) copy of a lidar project (AWS Open Data, s3://usgs-lidar-public, free).

Used when the LAZ tiles on rockyweb.usgs.gov cannot be reached (down 2026-10-07; option B, owner). The EPT copy is
the same flight re-indexed into an octree of LAZ nodes, reprojected to EPSG:3857 (WGS 84 / Pseudo-Mercator, metres)
and quantised to 0.01 units; ept.json carries the bounds cube, schema and srs. A node key is "D-X-Y-Z"; its cube is
the root cube split 2^D times per axis. Hierarchy pages map key -> point count, -1 = see the page of that key.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import requests


def get_json(url: str) -> dict:
    for attempt in range(6):
        try:
            r = requests.get(url, timeout=(30, 120))
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            time.sleep(2**attempt)
    raise RuntimeError(f"EPT read failed: {url}")


def node_box(key: str, cube: list[float]) -> tuple[float, float, float, float]:
    """XY bounds (EPSG:3857) of node D-X-Y-Z inside the root cube [xmin, ymin, zmin, xmax, ymax, zmax]."""
    d, x, y, _ = map(int, key.split("-"))
    sx, sy = (cube[3] - cube[0]) / 2**d, (cube[4] - cube[1]) / 2**d
    return cube[0] + x * sx, cube[1] + y * sy, cube[0] + (x + 1) * sx, cube[1] + (y + 1) * sy


def hierarchy(base: str, bbox: tuple[float, float, float, float] | None = None, threads: int = 16) -> tuple[dict, dict]:
    """All non-empty nodes (key -> point count) whose XY box touches bbox (EPSG:3857), and ept.json."""
    meta = get_json(f"{base}/ept.json")
    cube = meta["bounds"]

    def touches(key: str) -> bool:
        if bbox is None:
            return True
        x0, y0, x1, y1 = node_box(key, cube)
        return x0 < bbox[2] and bbox[0] < x1 and y0 < bbox[3] and bbox[1] < y1

    nodes: dict[str, int] = {}
    pages = ["0-0-0-0"]
    with ThreadPoolExecutor(threads) as ex:
        while pages:
            nxt = []
            for page in ex.map(lambda k: get_json(f"{base}/ept-hierarchy/{k}.json"), pages):
                for k, n in page.items():
                    if not touches(k):
                        continue
                    if n == -1:
                        nxt.append(k)
                    elif n > 0:
                        nodes[k] = n
            pages = [k for k in nxt if k not in nodes]
    return nodes, meta
