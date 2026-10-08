"""Fetch Pinellas County's structured elevation-certificate layer (record class: label candidates, never features).

Source: https://egis.pinellas.gov/gis/rest/services/ElevationCertsApp/ElevationCertsApp/MapServer/0
("Pinellas Elevation Certificates", Pinellas County Public Works). The layer JSON (?f=json, with its description and
copyrightText) is saved next to the pages. No licence text is published on the layer; tag rows
`pinellas_county_ec:terms_unread` until the terms are read.

Personal data: owner (A1, F), street address (A2), property description (A3), certifier / official names, licence
numbers, company, contact (D_*, G_* names / phones), comments, file names and editor user names are NEVER requested.
`outFields` is an explicit allowlist (FIELDS below); the script refuses to run if any of it looks like a name / contact
field. Geometry is requested as outSR=4326 (lon, lat).

Output: data/flood_v1/labels_pinellas/raw/<date>/layer.json, page_<NNN>.json (1,000 records each, ordered by
OBJECTID), and fetch.json (counts).
Usage: python pipeline/labels_pinellas/fetch.py [YYYY-MM-DD]
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
URL = "https://egis.pinellas.gov/gis/rest/services/ElevationCertsApp/ElevationCertsApp/MapServer/0"
PAGE = 1000
FIELDS = [
    "OBJECTID",
    "GLOBALID",
    "STR_PIN",  # parcel id: used only to keep one certificate per property, never written out
    "A4_BUILDING_USE",
    "A5_LATITUDE",
    "A5_LONGITUDE",
    "A5_HORIZ_DATUM",
    "A7_BUILDING_DIAG_NUM",
    "B6_FIRM_INDEX_DATE",
    "B7_FIRM_EFFECTIVE_REVISE_DATE",
    "B8_FLOOD_ZONE",
    "B9_BASE_FLOOD_ELEVATION",
    "B10_BFE_SOURCE",
    "B11_ELEVATION_DATUM",
    "BFE_CONVERTED_TO_NAVD88",
    "C1_BUILDING_ELEVATION_SOURCE",
    "C2_BENCHMARK_VERT_DATUM",
    "VERTICAL_DATUM",
    "MEASUREMENT_UNITS",
    "C2A_TOP_BOTTOM_FLOOR_EL",
    "C2B_TOP_NEXT_HIGHER_FL_EL",
    "C2C_BOTTOM_LOW_STRUCT_EL",
    "C2D_ATTACHED_GARAGE_ELEV",
    "C2E_LOWEST_MACHINERY_EQ_EL",
    "C2F_LAG_ELEV",
    "C2G_HAG_ELEV",
    "C2H_LOWEST_ADJACENT_GRADE",
    "C2a_29",
    "C2a_88",
    "C2b_29",
    "C2b_88",
    "C2f_29",
    "C2f_88",
    "C2g_29",
    "C2g_88",
    "D_DATE",
    "D_CERTIFICATE_SEALED",
    "E5_ZONE_AO",
    "G4_PERMIT_NUMBER",
    "G5_DATE_PERMIT_ISSUED",
    "G6_CERT_COMPLIANCE_OCC_IS",
    "G7_PERMIT_ISSUED_FOR",
    "G8_ASBUILT_LOWEST_FL_ELEV",
    "G8_ASBUILT_LOWEST_FL_UNITS",
    "G8_ASBUILT_OWEST_FL_DATUM",
    "DATE_ENTERED",
    "CREATED_DATE",
    "LAST_EDITED_DATE",
    "POINT_TYPE",
    "REDACTED",
]
FORBIDDEN = ("OWNER", "NAME", "ADDRESS", "TELEPHONE", "LICENSE", "COMPANY", "COMMENTS", "_USER", "_BY", "TITLE")
FORBIDDEN_PREFIX = ("A1_", "A2_", "A3_", "D_CITY", "D_STATE", "D_ZIP", "F_", "DELIVERY")


def get(params: dict, tries: int = 5) -> dict:
    q = urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{URL}/query", data=q.encode()), timeout=120) as r:
                d = json.loads(r.read())
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:  # retry any transport / server error, then re-raise
            if i == tries - 1:
                raise
            print(f"retry {i + 1}: {e}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise AssertionError


def main(day: str) -> None:
    bad = [f for f in FIELDS if any(t in f.upper() for t in FORBIDDEN) or f.upper().startswith(FORBIDDEN_PREFIX)]
    assert not bad, f"personal-data fields in the allowlist: {bad}"
    out = ROOT / "data" / "flood_v1" / "labels_pinellas" / "raw" / day
    out.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f"{URL}?f=json", timeout=120) as r:
        layer = json.loads(r.read())
    (out / "layer.json").write_text(json.dumps(layer, indent=1))
    have = {f["name"] for f in layer["fields"]}
    assert set(FIELDS) <= have, f"fields missing from the layer: {set(FIELDS) - have}"
    total = get({"where": "1=1", "returnCountOnly": "true", "f": "json"})["count"]
    n, page = 0, 0
    while n < total:
        d = get(
            {
                "where": "1=1",
                "outFields": ",".join(FIELDS),
                "orderByFields": "OBJECTID",
                "resultOffset": n,
                "resultRecordCount": PAGE,
                "outSR": 4326,
                "returnGeometry": "true",
                "f": "json",
            }
        )
        k = len(d["features"])
        if not k:
            break
        got = set(d["features"][0]["attributes"])
        assert got <= set(FIELDS), f"server returned unrequested fields: {got - set(FIELDS)}"
        (out / f"page_{page:03d}.json").write_text(json.dumps(d))
        n, page = n + k, page + 1
        print(f"page {page}: {n}/{total}")
    res = {
        "url": URL,
        "fetched": day,
        "count_server": total,
        "records_fetched": n,
        "pages": page,
        "out_fields": FIELDS,
        "out_sr": 4326,
        "layer_name": layer.get("name"),
        "layer_has_licence_text": False,
    }
    (out / "fetch.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "out_fields"}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now(dt.UTC).date().isoformat())
