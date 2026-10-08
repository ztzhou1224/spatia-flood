"""Keep a raw input extract on R2 so a release can name the exact bytes it read (r1 plan docs/09 B5).

Uploads every file under DIR, gzipped, to R2 _flood/inputs/<name>/<date>/ (private bucket), plus a manifest.json
listing each file's sha256 and size; prints the prefix. Nothing is uploaded if the manifest at that prefix already
exists (an extract is kept once).
Usage: python pipeline/keep_input.py pinellas_county_ec 2026-10-07 data/flood_v1/labels_pinellas/raw/2026-10-07
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("date")
    ap.add_argument("dir", type=Path)
    a = ap.parse_args()
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["CLOUDFLARE_R2_ENDPOINT"],
        region_name="auto",
        aws_access_key_id=os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"],
    )
    bucket, prefix = os.environ["CLOUDFLARE_R2_BUCKET"], f"_flood/inputs/{a.name}/{a.date}"
    try:
        s3.head_object(Bucket=bucket, Key=f"{prefix}/manifest.json")
        print(f"{prefix}/ already kept")
        return
    except ClientError:
        pass
    files = sorted(p for p in a.dir.rglob("*") if p.is_file())
    man = []
    for p in files:
        b = p.read_bytes()
        rel = p.relative_to(a.dir).as_posix()
        s3.put_object(Bucket=bucket, Key=f"{prefix}/{rel}.gz", Body=gzip.compress(b, 6), ContentEncoding="gzip")
        man.append({"file": rel, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})
    s3.put_object(Bucket=bucket, Key=f"{prefix}/manifest.json", Body=json.dumps(man, indent=1).encode())
    print(f"{len(files)} files, {sum(m['bytes'] for m in man) / 1e6:.1f} MB -> {prefix}/")


if __name__ == "__main__":
    main()
