// Internal flood-layer viewer: a login check on every request, the static page, and the release's data read
// server-side from the private R2 bucket. Only keys under _flood/viewer/<FIPS>/<release>/ can be read.

const DATA_PATH = /^\/data\/(\d{5})\/([A-Za-z0-9._-]+)\/((?:geo|rec)\/[0-9a-f]{15}|index|county|coverage)\.json$/;

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
  return i > 0 && same(decoded.slice(0, i), env.VIEWER_USER) && same(decoded.slice(i + 1), env.VIEWER_PASSWORD);
}

export default {
  async fetch(req, env) {
    if (!authorized(req, env)) {
      return new Response("Login required", {
        status: 401,
        headers: { "WWW-Authenticate": 'Basic realm="spatia-flood viewer", charset="UTF-8"', "Cache-Control": "no-store" },
      });
    }
    const url = new URL(req.url);
    if (url.pathname === "/config.json") {
      return Response.json({ fips: env.FIPS, release: env.RELEASE }, { headers: { "Cache-Control": "no-store" } });
    }
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
