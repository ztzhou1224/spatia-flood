# Internal flood-layer viewer (flood.runspatia.com)

Owner + demos only (plan `docs/04-plan-flood-layer-v1.md` decision 16). A Cloudflare Worker checks a login on every
request, serves `public/` (MapLibre page) and streams the release's data from the PRIVATE `spatia-data` R2 bucket,
reading only keys under `_flood/viewer/<FIPS>/<release>/` (path regex in `src/worker.js`). Not reachable on
`*.workers.dev`.

Login: HTTP basic auth, user `flood` (`VIEWER_USER`), password in the Worker secret `VIEWER_PASSWORD` (never in git).
Cloudflare Access (email login) replaces it once Access is enabled on the account (owner, 2026-10-07: one click in
the Zero Trust dashboard); then add an Access application for `flood.runspatia.com` and keep the Worker check as a
second lock or drop it.

## Publish a release's data

```bash
python pipeline/assemble/coverage.py 12103 --release pinellas-r0      # coverage cells + county card
python pipeline/viewer/export.py 12103 --release pinellas-r0          # -> R2 _flood/viewer/12103/pinellas-r0/
```

Then point the Worker at it (`RELEASE` in `wrangler.toml`) and deploy.

## Deploy

```bash
cd viewer
npx wrangler@4.140.0 deploy                               # needs CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID
npx wrangler@4.140.0 secret put VIEWER_PASSWORD           # first deploy, or to rotate the password
```

## Local test (no Cloudflare)

Serve `public/` plus `/config.json` and `/data/...` from `data/flood_v1/viewer/` with any static server that sends
the files with `Content-Encoding: gzip` (they are stored gzipped), then open `http://127.0.0.1:8787/`.
