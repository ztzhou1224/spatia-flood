"""Pull the viewer's building flags (r1 plan docs/09 A4) from R2 _flood/inbox/viewer_flags/<release>/ into
data/inbox/viewer_flags/<release>/ (gitignored: notes are reviewer text) and print a count by reason.
The Worker (viewer/src/worker.js, POST /flag) is the only writer; each object is one flag as JSON.
Usage: python pipeline/viewer/pull_flags.py --release pinellas-r0
"""
from __future__ import annotations

import argparse
import collections
import json
import os
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", required=True)
    a = ap.parse_args()
    s3 = boto3.client("s3", endpoint_url=os.environ["CLOUDFLARE_R2_ENDPOINT"], region_name="auto",
                      aws_access_key_id=os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"])
    bucket, prefix = os.environ["CLOUDFLARE_R2_BUCKET"], f"_flood/inbox/viewer_flags/{a.release}/"
    out = ROOT / "data" / "inbox" / "viewer_flags" / a.release
    out.mkdir(parents=True, exist_ok=True)
    reasons: collections.Counter[str] = collections.Counter()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for o in page.get("Contents", []):
            body = s3.get_object(Bucket=bucket, Key=o["Key"])["Body"].read()
            rec = json.loads(body)
            (out / Path(o["Key"]).name).write_bytes(body)
            reasons[rec["reason"]] += 1
    print(f"{sum(reasons.values())} flags -> {out}: {dict(reasons)}")


if __name__ == "__main__":
    main()
