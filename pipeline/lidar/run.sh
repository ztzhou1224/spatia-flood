#!/usr/bin/env bash
# Runs on the throwaway box from cloud-init (box.py). Installs the job's dependencies and runs job.py.
# Any failure before job.py can report is uploaded as status.json through the presigned URL.
set -euo pipefail
export HOME=/root
U=/opt/flood/urls.json
url() { python3 -c "import json,sys; print(json.load(open('$U'))[sys.argv[1]])" "$1"; }
fail() {
  printf '{"stage":"failed","error":"run.sh: %s","t":%s}' "$1" "$(date +%s)" > /tmp/status.json
  curl -sS -X PUT -H 'Content-Type: application/json' --data-binary @/tmp/status.json "$(url status)" || true
  curl -sS -X PUT -H 'Content-Type: text/plain' --data-binary @/var/log/flood-setup.log "$(url log)" || true
  exit 1
}
exec > /var/log/flood-setup.log 2>&1
trap 'fail "setup failed at line $LINENO"' ERR
printf '{"stage":"setup","t":%s}' "$(date +%s)" > /tmp/status.json
curl -sS -X PUT -H 'Content-Type: application/json' --data-binary @/tmp/status.json "$(url status)"
cd /opt/flood
curl -fsS "$(url code)" -o code.tgz && tar xzf code.tgz
curl -LsSf https://astral.sh/uv/install.sh | sh
/root/.local/bin/uv venv --python 3.12 /opt/flood/.venv
/root/.local/bin/uv pip install --python /opt/flood/.venv/bin/python \
  "laspy[lazrs]==2.7.0" lazrs==0.8.2 numpy==2.5.3 pandas==3.0.6 pyarrow==25.0.1 shapely==2.1.2 scipy==1.18.1 \
  rasterio==1.5.2 pyproj==3.8.0 requests==2.34.2
mkdir -p /mnt/work
trap - ERR
OMP_NUM_THREADS=1 /opt/flood/.venv/bin/python /opt/flood/job.py "$U" /mnt/work > /var/log/flood-job.log 2>&1 \
  || exit 1  # job.py has already uploaded its own failed status.json with the traceback
