"""Clean missing or invalid certificate issue dates with an LLM (owner request 2026-10-07: "batch them into one or
more LLM calls, ask for the best possibility, e.g. 6201 is probably 2016").

Rows: the county's matched certificates (train/labels.py labels_<FIPS>.parquet) whose FDEM issuedAt is missing or
outside 1990-01-01 .. today. Context sent per row, fetched from the FDEM public layer by OBJECTID: the raw issuedAt,
formYear (FEMA form edition), firmPanelEffectiveDate, buildingElevationSource, buildingDiagramNumber. No address,
owner or property id is sent. Model: OPENAI_MODEL below (pinned snapshot), JSON output, batches of 100.
The answer per row is a best single date (or none), a window it must lie in, a confidence and a one-line reason.
Validation (else the row stays unknown): dates parse, lie in 1990-01-01 .. today, start <= estimate <= end.
These are ESTIMATES, never measurements: assemble.py marks every value taken from here in record_vintage_note.
Outputs: data/flood_v1/assemble/dates_clean_<FIPS>.parquet and pipeline/assemble/out/dates_clean_<FIPS>.csv
(certificate OBJECTID, raw fields, answer; no personal data).
Usage: python pipeline/assemble/clean_dates.py 12103
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "flood_v1"
FDEM = (
    "https://services8.arcgis.com/4L6VuYsPSGSEJ0qe/arcgis/rest/services/Public_FDEM_Elevation_Certificates/"
    "FeatureServer/0/query"
)
OPENAI_MODEL = "gpt-5.5-2026-04-23"
FIELDS = "OBJECTID,issuedAt,formYear,firmPanelEffectiveDate,buildingElevationSource,buildingDiagramNumber"
LO = pd.Timestamp("1990-01-01")
PROMPT = """You clean dates in FEMA Elevation Certificate records from the Florida Division of Emergency Management
public layer. Each record below has an issue date (issuedAt) that is missing or invalid. For each record, give the
most likely issue date, using: the raw value if one exists (typos such as swapped or reversed digits, e.g. a year
6201 is probably 2016), formYear (the edition year of the FEMA Elevation Certificate form used; use what you know
about when each edition was in use), the FIRM panel effective date (a certificate is normally issued after it, but
that field can itself be wrong), and the building elevation source. Today is {today}; no date may be after it or
before 1990-01-01.
Return JSON: {{"rows": [{{"objectid": int, "estimate": "YYYY-MM-DD" or null (null when no single date is better than
the window), "window_start": "YYYY-MM-DD", "window_end": "YYYY-MM-DD", "confidence": "high" | "medium" | "low",
"reason": "one short sentence"}}]}} with one row per input record, in the same order.
Records:
{records}"""


def fetch(ids: list[int]) -> pd.DataFrame:
    rows = []
    for k in range(0, len(ids), 400):
        r = requests.post(
            FDEM,
            data={
                "objectIds": ",".join(map(str, ids[k : k + 400])),
                "outFields": FIELDS,
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=120,
        )
        r.raise_for_status()
        rows += [f["attributes"] for f in r.json()["features"]]
    f = pd.DataFrame(rows)
    for c in ("issuedAt", "firmPanelEffectiveDate"):
        f[c] = pd.to_datetime(f[c], unit="ms", errors="coerce").dt.strftime("%Y-%m-%d")
    return f


def ask(batch: pd.DataFrame, today: str) -> list[dict]:
    recs = "\n".join(
        json.dumps(
            {
                "objectid": int(r.OBJECTID),
                "issuedAt_raw": r.issuedAt,
                "formYear": r.formYear,
                "firmPanelEffectiveDate": r.firmPanelEffectiveDate,
                "buildingElevationSource": r.buildingElevationSource,
                "buildingDiagramNumber": r.buildingDiagramNumber,
            }
        )
        for r in batch.itertuples()
    )
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        timeout=600,
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
        json={
            "model": OPENAI_MODEL,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": PROMPT.format(today=today, records=recs)}],
        },
    )
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])["rows"]


def valid(a: dict, today: pd.Timestamp) -> bool:
    try:
        s, e = pd.Timestamp(a["window_start"]), pd.Timestamp(a["window_end"])
        x = pd.Timestamp(a["estimate"]) if a.get("estimate") else None
    except (KeyError, TypeError, ValueError):
        return False
    return LO <= s <= e <= today and (x is None or s <= x <= e) and a.get("confidence") in ("high", "medium", "low")


def main(fips: str) -> None:
    today = pd.Timestamp(dt.datetime.now(dt.UTC).date())
    lab = pd.read_parquet(DATA / "train" / f"labels_{fips}.parquet")
    issued = pd.to_datetime(lab.issued_at, unit="ms", errors="coerce")
    ids = sorted(lab.cert_objectid[~issued.between(LO, today)].astype(int))
    f = fetch(ids)
    print(f"certificates with a missing or invalid issue date: {len(ids)}; fetched {len(f)}")
    out = []
    for k in range(0, len(f), 100):
        part = f.iloc[k : k + 100]
        ans = {int(a["objectid"]): a for a in ask(part, today.date().isoformat()) if "objectid" in a}
        for r in part.itertuples():
            a = ans.get(int(r.OBJECTID), {})
            ok = valid(a, today)
            out.append(
                {
                    "cert_objectid": int(r.OBJECTID),
                    "issued_raw": r.issuedAt,
                    "form_year": r.formYear,
                    "firm_date_raw": r.firmPanelEffectiveDate,
                    "estimate": a.get("estimate") if ok else None,
                    "window_start": a.get("window_start") if ok else None,
                    "window_end": a.get("window_end") if ok else None,
                    "confidence": a.get("confidence") if ok else None,
                    "reason": a.get("reason"),
                    "valid": ok,
                    "model": OPENAI_MODEL,
                }
            )
        print(f"batch {k // 100 + 1}: {len(part)} rows, {sum(o['valid'] for o in out[-len(part) :])} valid", flush=True)
    d = pd.DataFrame(out)
    d.to_parquet(DATA / "assemble" / f"dates_clean_{fips}.parquet", index=False)
    d.to_csv(Path(__file__).parent / "out" / f"dates_clean_{fips}.csv", index=False)
    print(d.groupby(["form_year", "confidence"], dropna=False).size().to_string())
    print(d[d.issued_raw.notna()].to_string())
    print(d.groupby("form_year")[["window_start", "window_end"]].agg(["min", "max"]).to_string())


if __name__ == "__main__":
    main(sys.argv[1])
