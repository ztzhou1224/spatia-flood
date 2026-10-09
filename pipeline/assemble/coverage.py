"""Coverage map (plan docs/04 §3.3): per H3 cell and per county, what the layer holds and what is missing, so the
owner can see where to request data next.

Input: data/flood_v1/assemble/buildings_<FIPS>.parquet (assemble.py) and the release gate report
(pipeline/train/out/gate_<FIPS>_<release>.json) and the accuracy card (pipeline/train/accuracy.py ->
pipeline/train/out/accuracy_<FIPS>_<release>.json: the model scored on FDEM held-out AND on the independent county
certificates, each with its population; review docs/07 DA1). Cell = H3 cell of the building
centroid (lat, lon order for h3), resolution --res (default 8, ~0.74 km2: coarse enough to hold labels, fine enough
to show gaps; the owner left the choice to the viewer step).
Per cell / county: buildings, in the risk area, touching the SFHA; record floors (labels held) and record floors on
model-flagged (raised) houses; modeled floors; band calibration ('county' where the county has held-out labels on
both flagged and unflagged houses, plan §3.3 / BANDS.md rule; bands are never borrowed across states); lidar work
unit(s) and flight dates; SFHA buildings with a decided call (above / below) and their share; count of each missing
input (no BFE, no floor, no address, no parcel).
Outputs: data/flood_v1/assemble/coverage_<FIPS>_r<res>.parquet (cells, with the cell polygon in CRS84) and
pipeline/assemble/out/coverage_<FIPS>.json (the county row).
Usage: python pipeline/assemble/coverage.py 12103 --release pinellas-r0 [--res 8]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import shapely

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "flood_v1" / "assemble"


def summarise(g: pd.DataFrame) -> pd.Series:
    sf = g.touches_sfha
    dec = g.bfe_call.isin(["above", "below"])
    return pd.Series(
        {
            "buildings": len(g),
            "in_risk_area": int(g.in_risk_area.sum()),
            "touches_sfha": int(sf.sum()),
            "floor_record": int((g.ffh_class == "record").sum()),
            "floor_record_flagged": int(((g.ffh_class == "record") & g.raised_flag.fillna(False)).sum()),
            "floor_modeled": int((g.ffh_class == "modeled").sum()),
            "sfha_decided": int((sf & dec).sum()),
            "sfha_decided_share": float((sf & dec).sum() / sf.sum()) if sf.sum() else np.nan,
            "sfha_below": int((sf & (g.bfe_call == "below")).sum()),
            "missing_bfe_in_sfha": int((sf & g.bfe_ft.isna()).sum()),
            "missing_floor_in_risk": int((g.in_risk_area & g.ffh_ft.isna()).sum()),
            "missing_address": int(g.address.isna().sum()),
            "missing_parcel": int(g.parcel_key.isna().sum()),
            "lidar": "; ".join(
                sorted(
                    {
                        f"{w} ({v})"
                        for w, v in zip(g.lidar_workunit, g.ground_vintage, strict=True)
                        if isinstance(w, str) and isinstance(v, str)
                    }
                )
            ),
        }
    )


def accuracy_card(fips: str, release: str) -> dict:
    """Both populations' scores for the county card (docs/09 A1); fails if accuracy.py has not been run."""
    acc = json.loads((ROOT / "pipeline" / "train" / "out" / f"accuracy_{fips}_{release}.json").read_text())
    keep = ("n", "MAE", "median error", "within 1 ft", "BFE side", "coverage", "coverage CI95", "decided correct")
    pops = {
        pop: {g: ({k: v[k] for k in keep} if "n" in v else v) for g, v in acc[pop].items()}
        for pop in ("fdem_held_out", "county_independent")
    }
    eu = acc["county_independent"].get("elevated 5-9 not flagged", {})
    return {
        "populations": acc["populations"],
        **pops,
        "table_calls_vs_county_certificate": acc.get("table_calls_vs_county_certificate"),
        "warning": (
            "90% band not guaranteed for elevated houses the model does not flag as raised: on county "
            f"certificates its coverage is {eu.get('coverage')} (n {eu.get('n')})"
        )
        if eu
        else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("fips")
    ap.add_argument("--release", required=True)
    ap.add_argument("--res", type=int, default=8)
    a = ap.parse_args()
    cols = [
        "lon",
        "lat",
        "in_risk_area",
        "touches_sfha",
        "ffh_class",
        "ffh_ft",
        "raised_flag",
        "bfe_call",
        "bfe_ft",
        "address",
        "parcel_key",
        "lidar_workunit",
        "ground_vintage",
    ]
    b = pd.read_parquet(OUT / f"buildings_{a.fips}.parquet", columns=cols)
    b["cell"] = [h3.latlng_to_cell(la, lo, a.res) for la, lo in zip(b.lat, b.lon, strict=True)]
    gate = json.loads((ROOT / "pipeline" / "train" / "out" / f"gate_{a.fips}_{a.release}.json").read_text())
    if "scores" in gate:  # gate v1 (r0)
        cand, n_test = gate["scores"]["candidate"], gate["n_test"]
    else:  # gate v2 (r1 on): the benchmark FDEM table
        t = gate["tables"]["benchmark | fdem"]
        cand, n_test = t["candidate"], t["houses"]
    held_flagged = int(((b.ffh_class == "record") & b.raised_flag.fillna(False)).sum())
    calib = "county" if n_test > 0 and held_flagged > 0 else "none"

    cells = b.groupby("cell").apply(summarise, include_groups=False).reset_index()
    cells["county_fips"] = a.fips
    cells["band_calibration"] = calib
    cells["release"] = a.release
    poly = [shapely.Polygon([(lo, la) for la, lo in h3.cell_to_boundary(c)]) for c in cells.cell]
    gpd.GeoDataFrame(cells, geometry=poly, crs="OGC:CRS84").to_parquet(OUT / f"coverage_{a.fips}_r{a.res}.parquet")

    county = summarise(b).to_dict()
    county |= {
        "fips": a.fips,
        "release": a.release,
        "h3_res": a.res,
        "cells": len(cells),
        "band_calibration": calib,
        "held_out_accuracy": {k: round(cand[k], 3) for k in ("n", "MAE", "BFE side", "coverage", "decided correct")},
        "accuracy": accuracy_card(a.fips, a.release),
        "cells_with_sfha": int((cells.touches_sfha > 0).sum()),
        "cells_with_sfha_and_no_record_floor": int(((cells.touches_sfha > 0) & (cells.floor_record == 0)).sum()),
        "cells_sfha_decided_share_quartiles": cells.sfha_decided_share.quantile([0.25, 0.5, 0.75]).round(3).tolist(),
    }
    county["sfha_decided_share"] = round(county["sfha_decided_share"], 3)
    (Path(__file__).parent / "out" / f"coverage_{a.fips}.json").write_text(json.dumps(county, indent=1, default=str))
    print(json.dumps(county, indent=1, default=str))


if __name__ == "__main__":
    main()
