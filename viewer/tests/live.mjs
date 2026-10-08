// Live check of the deployed viewer (r1 plan docs/09 A4): run after every deploy.
//   node viewer/tests/live.mjs <password> [base-url] [screenshot-dir]
// Playwright is resolved from PLAYWRIGHT_MODULE (default: the container's /opt/node-tools copy).
// Checks: login required (401 without credentials); limitations page present; "screening, not a determination" banner
// on both pages; the county card shows both accuracy populations, the band warning and the datum line; a building
// record shows the datum line and the flag box, and its record JSON carries no OBJECTID / parcel id; the Worker
// rejects a bad flag (400) and a cross-origin flag (403); a real flag round-trips (the id is printed; confirm the
// object exists with `python pipeline/viewer/pull_flags.py --release <release>`).
const pwPath = process.env.PLAYWRIGHT_MODULE || "/opt/node-tools/node_modules/playwright/index.mjs";
const { chromium, request } = await import(pwPath);
const [pw, base = "https://flood.runspatia.com", shots = "."] = process.argv.slice(2);
if (!pw) throw new Error("usage: node viewer/tests/live.mjs <password> [base-url] [screenshot-dir]");

const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); };

const anon = await request.newContext();
check("401 without login", (await anon.get(base + "/")).status() === 401);
await anon.dispose();

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, httpCredentials: { username: "flood", password: pw } });
const page = await ctx.newPage();
const errs = [];
page.on("pageerror", (e) => errs.push(String(e)));

await page.goto(base + "/limitations.html", { waitUntil: "networkidle" });
const lim = await page.textContent("body");
check("limitations page", /What this map can and cannot tell you/.test(lim) && /first living floor/.test(lim));
check("limitations banner", /Screening, not a determination/.test(lim));

await page.goto(base + "/", { waitUntil: "networkidle" });
await page.waitForFunction(() => window.floodMap && window.floodMap.loaded() && window.floodMap.getSource("buildings"), null, { timeout: 60000 });
const card = await page.textContent("#panel");
check("index banner + link", /Screening, not a determination/.test(card) && (await page.$('a[href="/limitations.html"]')) !== null);
check("card: both populations", /FDEM held-out/.test(card) && /County certificates/.test(card));
check("card: band warning", /band not guaranteed for elevated houses/.test(card));
check("card: datum line", /NAVD88 \(US survey feet\); lidar geoid GEOID12B; certificates: geoid not stated/.test(card));

await page.evaluate(() => window.floodMap.jumpTo({ center: [-82.6045, 27.8095], zoom: 16.5 }));
await page.waitForFunction(() => window.floodMap.queryRenderedFeatures({ layers: ["buildings"] }).length > 20, null, { timeout: 60000 });
const pt = await page.evaluate(() => {
  const m = window.floodMap;
  const f = m.queryRenderedFeatures({ layers: ["buildings"] })[0];
  const ring = f.geometry.type === "Polygon" ? f.geometry.coordinates[0] : f.geometry.coordinates[0][0];
  const c = ring.reduce((a, x) => [a[0] + x[0], a[1] + x[1]], [0, 0]).map((v) => v / ring.length);
  const px = m.project(c);
  const r = m.getCanvas().getBoundingClientRect();
  return { x: r.left + px.x, y: r.top + px.y };
});
await page.mouse.click(pt.x, pt.y);
await page.waitForSelector("#record .flag", { timeout: 30000 });
const recText = await page.textContent("#record");
check("record: datum line", /lidar geoid GEOID12B/.test(recText));
check("record: flag box", /Flag this building/.test(recText));
check("record JSON: no OBJECTID / parcel id", !/objectid|parcel_id_native|parcel_key/i.test(await page.textContent("#record pre")));
await page.screenshot({ path: `${shots}/viewer_live.png` });

const cfg = await (await ctx.request.get(base + "/config.json")).json();
const bid = await page.evaluate(() => JSON.parse(document.querySelector("#record pre").textContent).building_id);
const post = (body, headers = {}) => ctx.request.post(base + "/flag", { data: body, headers: { "Content-Type": "application/json", ...headers } });
check("flag: bad id rejected", (await post({ building_id: "../x", release: cfg.release, reason: "floor", note: "" })).status() === 400);
check("flag: cross-origin rejected", (await post({ building_id: bid, release: cfg.release, reason: "floor", note: "" }, { Origin: "https://evil.example" })).status() === 403);
check("flag: wrong release rejected", (await post({ building_id: bid, release: "nope", reason: "floor", note: "" })).status() === 400);

// the real round trip, through the page's own button
await page.selectOption("#record .flag select", "other");
await page.fill("#record .flag textarea", "automated live test (viewer/tests/live.mjs); ignore");
await page.click("#record .flag button");
await page.waitForFunction(() => /^sent \(/.test(document.querySelector("#record .flag .src").textContent), null, { timeout: 30000 });
const sent = await page.textContent("#record .flag .src");
check("flag: sent through the page", /^sent \(/.test(sent), sent);
check("no page errors", errs.length === 0, errs.join(" | "));
await browser.close();

for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.detail ? `: ${r.detail}` : ""}`);
process.exit(results.every((r) => r.ok) ? 0 : 1);
