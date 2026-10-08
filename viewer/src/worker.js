// Internal flood-layer viewer: a login check on every request, the static page, and the release's data read
// server-side from the private R2 bucket. Only keys under _flood/viewer/<FIPS>/<release>/ can be read.
// POST /flag files a reviewer's note on one building under _flood/inbox/viewer_flags/<release>/ (write-only from
// here; pulled by pipeline/viewer/pull_flags.py). Nothing else can be written.

const DATA_PATH = /^\/data\/(\d{5})\/([A-Za-z0-9._-]+)\/((?:geo|rec)\/[0-9a-f]{15}|index|county|coverage)\.json$/;

const BUILDING_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const FLAG_REASONS = new Set(["floor", "ground", "call", "zone", "building", "other"]);
const NOTE_MAX = 2000;

async function flag(req, env, user) {
  if (req.method !== "POST") return new Response("Method not allowed", { status: 405, headers: { Allow: "POST" } });
  const origin = req.headers.get("Origin");
  if (origin && origin !== new URL(req.url).origin) return new Response("Forbidden", { status: 403 });
  if (!(req.headers.get("Content-Type") || "").startsWith("application/json")) return new Response("Bad request", { status: 400 });
  const raw = await req.text();
  if (raw.length > 4 * NOTE_MAX) return new Response("Too large", { status: 413 });
  let b;
  try {
    b = JSON.parse(raw);
  } catch {
    return new Response("Bad request", { status: 400 });
  }
  if (typeof b !== "object" || b === null || !BUILDING_ID.test(b.building_id ?? "") || b.release !== env.RELEASE ||
      !FLAG_REASONS.has(b.reason) || typeof (b.note ?? "") !== "string" || (b.note ?? "").length > NOTE_MAX) {
    return new Response("Bad request", { status: 400 });
  }
  const at = new Date().toISOString();
  const id = `${at.replace(/[:.]/g, "")}-${b.building_id}`;
  const rec = { id, received_at: at, user, fips: env.FIPS, release: env.RELEASE, building_id: b.building_id,
    reason: b.reason, note: b.note ?? "" };
  await env.BUCKET.put(`_flood/inbox/viewer_flags/${env.RELEASE}/${id}.json`, JSON.stringify(rec),
    { httpMetadata: { contentType: "application/json" } });
  return Response.json({ id }, { headers: { "Cache-Control": "no-store" } });
}

function same(a, b) {
  // length-independent comparison of two strings
  const x = new TextEncoder().encode(a);
  const y = new TextEncoder().encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

function authorized(req, env) {
  if (!env.VIEWER_PASSWORD) return false; // fail closed when the secret is missing
  const h = req.headers.get("Authorization") || "";
  if (!h.startsWith("Basic ")) return false;
  let decoded;
  try {
    decoded = atob(h.slice(6));
  } catch {
    return false;
  }
  const i = decoded.indexOf(":");
  return i > 0 && same(decoded.slice(0, i), env.VIEWER_USER) && same(decoded.slice(i + 1), env.VIEWER_PASSWORD)
    ? decoded.slice(0, i) : false;
}

export default {
  async fetch(req, env) {
    const user = authorized(req, env);
    if (!user) {
      return new Response("Login required", {
        status: 401,
        headers: { "WWW-Authenticate": 'Basic realm="spatia-flood viewer", charset="UTF-8"', "Cache-Control": "no-store" },
      });
    }
    const url = new URL(req.url);
    if (url.pathname === "/config.json") {
      return Response.json({ fips: env.FIPS, release: env.RELEASE }, { headers: { "Cache-Control": "no-store" } });
    }
    if (url.pathname === "/flag") return flag(req, env, user);
    if (url.pathname.startsWith("/data/")) {
      const m = url.pathname.match(DATA_PATH);
      if (!m) return new Response("Not found", { status: 404 });
      const obj = await env.BUCKET.get(`_flood/viewer/${m[1]}/${m[2]}/${m[3]}.json`);
      if (!obj) return new Response("Not found", { status: 404 });
      return new Response(obj.body, {
        encodeBody: "manual", // the object is stored gzipped; pass the bytes through
        headers: { "Content-Type": "application/json", "Content-Encoding": "gzip", "Cache-Control": "private, max-age=3600" },
      });
    }
    const res = await env.ASSETS.fetch(req);
    const out = new Response(res.body, res);
    out.headers.set("Cache-Control", "private, no-cache");
    out.headers.set("X-Robots-Tag", "noindex");
    return out;
  },
};
