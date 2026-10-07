"""Throwaway Hetzner box for one lidar run (spatia-data `hetzner-build-publish` skill, run without SSH).

The skill's rules kept: ccx33, data lives in R2, the Hetzner token never reaches the box, the box is DELETED
after the run (a powered-off box still bills). Changed for this sandbox, which has HTTPS only (no port 22): the
job starts from cloud-init (run.sh, job.py) instead of an SSH session; sshd is disabled and the box sits behind a
firewall with no inbound rules; the box holds only presigned R2 URLs (prepare.py), never an R2 key.

    python pipeline/lidar/box.py create RUN [--type ccx33] [--location ash]
    python pipeline/lidar/box.py status RUN          # status.json from R2 + server state + hours billed so far
    python pipeline/lidar/box.py delete RUN          # server (the firewall is kept, it is free)
    python pipeline/lidar/box.py list                # every server in the project: catch a leftover box
Credentials from the environment, never printed: HETZNER_DEFAULT_PROJECT_API_TOKEN, CLOUDFLARE_R2_*.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = "https://api.hetzner.cloud/v1"
FIREWALL = "spatia-flood-lidar"
LABELS = {"managed-by": "spatia-flood", "purpose": "lidar"}


def hz(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {os.environ['HETZNER_DEFAULT_PROJECT_API_TOKEN']}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"hetzner {method} {path}: HTTP {e.code} {e.read()[:300]!r}") from None


def server_name(run: str) -> str:
    return f"flood-lidar-{run}".replace("_", "-")[:63]


def find_server(name: str) -> dict | None:
    s = hz("GET", f"/servers?name={name}")["servers"]
    return s[0] if s else None


def user_data(run: str) -> str:
    urls = (ROOT / "data" / "flood_v1" / "lidar" / run / "urls.json").read_bytes()
    runsh = (Path(__file__).parent / "run.sh").read_bytes()
    return "\n".join([
        "#cloud-config",
        "write_files:",
        "  - path: /opt/flood/urls.json",
        "    permissions: '0600'",
        "    encoding: b64",
        f"    content: {base64.b64encode(urls).decode()}",
        "  - path: /opt/flood/run.sh",
        "    permissions: '0700'",
        "    encoding: b64",
        f"    content: {base64.b64encode(runsh).decode()}",
        "runcmd:",
        "  - [systemctl, disable, --now, ssh.socket, ssh.service]",
        "  - [bash, /opt/flood/run.sh]",
        ""])


def sources_up(run: str) -> None:
    """Range-read the first LPC and DEM tile from here before paying for a box (rockyweb.usgs.gov was down on
    2026-10-07 and the first box spent 30 min failing)."""
    tl = json.loads((ROOT / "data" / "flood_v1" / "lidar" / run / "tiles.json").read_text())
    for k in ("lpc", "dem"):
        url = tl[k][0]["url"]
        req = urllib.request.Request(url, headers={"Range": "bytes=0-1023"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status not in (200, 206):
                    raise SystemExit(f"{k} source answered HTTP {r.status}: not creating a box")
        except (urllib.error.URLError, OSError) as e:
            raise SystemExit(f"{k} source unreachable ({e}): not creating a box") from None
    print("sources reachable: first LPC and DEM tile answered a range read")


def create(a) -> None:
    name = server_name(a.run)
    sources_up(a.run)
    if find_server(name):
        raise SystemExit(f"server {name} already exists")
    fw = hz("GET", f"/firewalls?name={FIREWALL}")["firewalls"]
    if fw:
        fw_id = fw[0]["id"]
    else:
        fw_id = hz("POST", "/firewalls", {"name": FIREWALL, "labels": LABELS, "rules": []})["firewall"]["id"]
        print(f"firewall {FIREWALL}: created id={fw_id} (no inbound rules)")
    ud = user_data(a.run)
    if len(ud) > 32 * 1024:
        raise SystemExit(f"user_data {len(ud)} bytes exceeds Hetzner's 32 KiB")
    r = hz("POST", "/servers", {"name": name, "server_type": a.type, "image": "ubuntu-24.04", "location": a.location,
                                "user_data": ud, "labels": LABELS | {"run": a.run.replace("_", "-")},
                                "firewalls": [{"firewall": fw_id}], "start_after_create": True,
                                "public_net": {"enable_ipv4": True, "enable_ipv6": True}})
    s = r["server"]  # r["root_password"] is never printed; sshd is disabled and inbound is closed anyway
    print(f"server {name}: created id={s['id']} {a.type} in {a.location} at {s['created']}")


def r2_status(run: str) -> dict | None:
    import boto3
    s3 = boto3.client("s3", endpoint_url=os.environ["CLOUDFLARE_R2_ENDPOINT"], region_name="auto",
                      aws_access_key_id=os.environ["CLOUDFLARE_R2_ACCESS_KEY_ID"],
                      aws_secret_access_key=os.environ["CLOUDFLARE_R2_SECRET_ACCESS_KEY"])
    try:
        o = s3.get_object(Bucket=os.environ["CLOUDFLARE_R2_BUCKET"], Key=f"_flood/lidar/{run}/out/status.json")
        return json.loads(o["Body"].read())
    except s3.exceptions.NoSuchKey:
        return None


def status(a) -> None:
    s = find_server(server_name(a.run))
    if s:
        hours = (datetime.now(timezone.utc) - datetime.fromisoformat(s["created"])).total_seconds() / 3600
        print(f"server {s['name']}: {s['status']} {s['server_type']['name']}, up {hours:.2f} h")
    else:
        print("server: none")
    st = r2_status(a.run)
    if st:
        st.pop("error", None) if not a.verbose else None
        age = time.time() - st.get("t", 0)
        print(json.dumps(st | {"status_age_s": round(age)}, default=str))
    else:
        print("status.json: not yet written")


def delete(a) -> None:
    s = find_server(server_name(a.run))
    if not s:
        print("no server to delete")
        return
    hz("DELETE", f"/servers/{s['id']}")
    print(f"server {s['name']} id={s['id']}: deleted")


def list_servers(_a) -> None:
    for s in hz("GET", "/servers")["servers"]:
        print(s["name"], s["status"], s["server_type"]["name"], s["created"], s.get("labels"))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("run")
    c.add_argument("--type", default="ccx33")
    c.add_argument("--location", default="ash")
    for k in ("status", "delete"):
        p = sub.add_parser(k)
        p.add_argument("run")
        p.add_argument("--verbose", action="store_true")
    sub.add_parser("list")
    a = ap.parse_args()
    {"create": create, "status": status, "delete": delete, "list": list_servers}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
