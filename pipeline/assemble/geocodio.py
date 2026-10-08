"""Phase 1: Geocodio reverse lookups for risk-area buildings that have no free address (owner approval 2026-10-07:
Pinellas, 727 lookups by pipeline/phase0/address_gap.py, inside the 2,500 / day free tier).

Input: data/flood_v1/assemble/buildings_<FIPS>.parquet (assemble.py), rows in the risk area with a null address.
Refuses to call when there are more than --max of them (default 800: the approved 727 plus a small margin for the
footprint-centroid vs Overture lon / lat difference); a larger number needs a new cost estimate approved by the owner.
One batch POST per 1,000 points (building centroid, CRS84). Kept per building: the first result's formatted address,
its source, accuracy and accuracy type, and the lookup date; nothing else from the response.
Output: data/flood_v1/assemble/geocodio_<FIPS>.parquet (assemble.py reads it on its next run); counts in
pipeline/assemble/out/geocodio_<FIPS>.json.
Usage: python pipeline/assemble/geocodio.py 12103 [--max 800]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "flood_v1" / "assemble"
API = "https://api.geocod.io/v1.7/reverse"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("--max", type=int, default=800)
    a = ap.parse_args()
    b = pd.read_parquet(
        OUT / f"buildings_{a.fips}.parquet", columns=["building_id", "lon", "lat", "in_risk_area", "address"]
    )
    todo = b[b.in_risk_area & b.address.isna()].reset_index(drop=True)
    path = OUT / f"geocodio_{a.fips}.parquet"
    done = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["building_id"])
    todo = todo[~todo.building_id.isin(set(done.building_id))].reset_index(drop=True)
    print(f"risk-area buildings without an address and not yet looked up: {len(todo)}")
    if len(todo) > a.max:
        raise SystemExit(f"{len(todo)} lookups > --max {a.max}: needs a cost estimate approved by the owner")
    rows = []
    for k in range(0, len(todo), 1000):
        part = todo.iloc[k : k + 1000]
        r = requests.post(
            API,
            params={"api_key": os.environ["GEOCODIO_API_KEY"]},
            timeout=300,
            json=[f"{la:.6f},{lo:.6f}" for la, lo in zip(part.lat, part.lon, strict=True)],
        )
        r.raise_for_status()
        for bid, res in zip(part.building_id, r.json()["results"], strict=True):
            top = (res.get("response") or {}).get("results") or []
            t = top[0] if top else {}
            rows.append(
                {
                    "building_id": bid,
                    "address": t.get("formatted_address"),
                    "source": t.get("source"),
                    "accuracy": t.get("accuracy"),
                    "accuracy_type": t.get("accuracy_type"),
                    "looked_up": dt.datetime.now(dt.UTC).date().isoformat(),
                }
            )
    new = pd.DataFrame(rows)
    out = pd.concat([done, new], ignore_index=True) if len(done) else new
    out.to_parquet(path, index=False)
    rep = {
        "fips": a.fips,
        "lookups_this_run": len(new),
        "with_address": int(new.address.notna().sum()) if len(new) else 0,
        "accuracy_type": new.accuracy_type.value_counts().to_dict() if len(new) else {},
        "accuracy_median": float(new.accuracy.median()) if len(new) else None,
        "total_cached": len(out),
    }
    (Path(__file__).parent / "out" / f"geocodio_{a.fips}.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
