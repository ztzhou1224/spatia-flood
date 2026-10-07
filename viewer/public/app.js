// Flood layer viewer: coverage cells when zoomed out, building footprints coloured by the BFE call when zoomed in,
// and a building's full record (every value with its class, source, vintage, band or null reason) on click.
"use strict";

const CALL_COLORS = { below: "#c8352b", too_close: "#e39a1c", above: "#2f8a4c", not_applicable: "#b9bfca" };
const NO_CALL = "#6b7280";
const BUILDING_ZOOM = 14;
const state = { base: "", index: [], loaded: new Map(), records: new Map(), features: [] };

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else e.setAttribute(k, v);
  }
  for (const k of kids) if (k !== null && k !== undefined) e.append(k instanceof Node ? k : String(k));
  return e;
}

async function getJSON(path) {
  const r = await fetch(path, { credentials: "same-origin" });
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

const fmt = (v, d = 2) => (v === null || v === undefined ? "—" : typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(d)) : String(v));
const pct = (v) => (v === null || v === undefined ? "—" : `${(100 * v).toFixed(1)}%`);

function stat(value, label) {
  return el("div", { class: "stat" }, el("b", {}, value), el("span", {}, label));
}

function renderCard(c) {
  const a = c.held_out_accuracy || {};
  const card = document.getElementById("card");
  card.replaceChildren(
    el("h2", {}, `County ${c.fips} · ${c.release}`),
    el("div", { class: "stats" },
      stat(fmt(c.buildings), "buildings"), stat(fmt(c.in_risk_area), "in the risk area"),
      stat(fmt(c.touches_sfha), "touch the SFHA"), stat(pct(c.sfha_decided_share), "SFHA with a decided call"),
      stat(fmt(c.sfha_below), "SFHA below the BFE"), stat(fmt(c.floor_record), "certificate floors")),
    el("h2", {}, "Held-out accuracy (floor model)"),
    el("table", {},
      ...[["houses scored", fmt(a.n)], ["MAE (ft)", fmt(a.MAE, 3)], ["BFE side correct", pct(a["BFE side"])],
        ["90% band coverage", pct(a.coverage)], ["decided calls correct", pct(a["decided correct"])],
        ["band calibration", c.band_calibration], ["lidar", c.lidar]].map(([k, v]) => el("tr", {}, el("td", {}, k), el("td", {}, v)))),
    el("p", { class: "hint" }, "Pilot data: modeled values carry 90% bands; not for decisions without the record."),
  );
}

function valueRow(r, label, stem, valueKey, unit = "ft") {
  const v = r[valueKey ?? `${stem}_ft`];
  const cls = r[`${stem}_class`];
  const td = el("td", {});
  if (v === null || v === undefined) {
    td.append(el("span", { class: "why" }, `null: ${r[`${stem}_null`] ?? "—"}`));
  } else {
    td.append(`${fmt(v)} ${unit} `);
    if (cls) td.append(el("span", { class: `tag ${cls}` }, cls));
    const lo = r[`${stem}_band_lo`], hi = r[`${stem}_band_hi`];
    if (lo !== null && lo !== undefined) td.append(el("span", { class: "src" }, `90% band ${fmt(lo)} to ${fmt(hi)} ${unit}`));
    if (r[`${stem}_precision_ft`] !== null && r[`${stem}_precision_ft`] !== undefined) td.append(el("span", { class: "src" }, `precision ±${fmt(r[`${stem}_precision_ft`])} ft`));
    if (r[`${stem}_source`]) td.append(el("span", { class: "src" }, r[`${stem}_source`]));
    if (r[`${stem}_vintage`]) td.append(el("span", { class: "src" }, `vintage ${r[`${stem}_vintage`]}`));
  }
  return el("tr", {}, el("td", {}, label), td);
}

function plainRow(label, v) {
  return el("tr", {}, el("td", {}, label), el("td", {}, v === null || v === undefined ? el("span", { class: "why" }, "—") : String(v)));
}

function renderRecord(r) {
  const call = r.bfe_call;
  const zones = (r.zones || []).map((z) => `${z.zone}${z.subtype ? ` (${z.subtype.toLowerCase()})` : ""} ${pct(z.share)}`).join("; ");
  const box = document.getElementById("record");
  box.replaceChildren(
    el("h2", {}, "Building"),
    el("table", {},
      plainRow("address", r.address ? `${r.address}` : `null: ${r.address_null}`),
      plainRow("address source", r.address_source),
      plainRow("building id", r.building_id), plainRow("parcel", r.parcel_key),
      plainRow("footprint", `${fmt(r.footprint_area_m2, 0)} m²`), plainRow("in the risk area", r.in_risk_area)),
    el("h2", {}, "Verdict"),
    el("table", {},
      el("tr", {}, el("td", {}, "floor vs BFE"), el("td", {},
        call ? el("span", { class: `call ${call}` }, call.replace("_", " ")) : el("span", { class: "why" }, `null: ${r.bfe_call_null}`),
        r.bfe_call_basis ? el("span", { class: "src" }, `basis: ${r.bfe_call_basis}`) : null)),
      el("tr", {}, el("td", {}, "floor minus BFE"), el("td", {}, r.floor_minus_bfe_ft === null ? "—" : `${fmt(r.floor_minus_bfe_ft)} ft`,
        r.floor_minus_bfe_band_lo !== null && r.floor_minus_bfe_band_lo !== undefined ? el("span", { class: "src" }, `band ${fmt(r.floor_minus_bfe_band_lo)} to ${fmt(r.floor_minus_bfe_band_hi)} ft`) : null)),
      plainRow("raised (model flag)", r.raised_flag ?? `null: ${r.raised_flag_null}`)),
    el("h2", {}, "Flood context"),
    el("table", {}, plainRow("zones (share of footprint)", zones || `null: ${r.zones_null}`), plainRow("touches SFHA", r.touches_sfha),
      plainRow("FIRM effective", r.firm_effective_date), valueRow(r, "BFE (NAVD88)", "bfe"), plainRow("BFE method", r.bfe_method)),
    el("h2", {}, "Floor"),
    el("table", {}, valueRow(r, "first floor height", "ffh"), valueRow(r, "first floor elevation", "ffe"),
      r.record_vintage_note ? plainRow("date note", r.record_vintage_note) : null,
      r.ffe_record_lidar_conflict ? plainRow("check", "certificate conflicts with lidar") : null),
    el("h2", {}, "Ground, roof, building"),
    el("table", {}, valueRow(r, "lowest adjacent grade", "lag"), valueRow(r, "roof (above grade)", "roof"),
      valueRow(r, "eave (above grade)", "eave"), valueRow(r, "year built", "year_built", "year_built", ""),
      valueRow(r, "living area", "living_area_sqft", "living_area_sqft", "sq ft")),
    el("h2", {}, "Provenance"),
    el("table", {}, plainRow("release", r.release), plainRow("model", r.model_version), plainRow("inputs", (r.input_licences || []).join(", "))),
    el("details", {}, el("summary", {}, "all columns"), el("pre", {}, JSON.stringify(r, null, 1))),
  );
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}

function legend(metric) {
  const box = document.getElementById("legend");
  const items = [["below", CALL_COLORS.below], ["too close", CALL_COLORS.too_close], ["above", CALL_COLORS.above],
    ["not in SFHA", CALL_COLORS.not_applicable], ["no call", NO_CALL]];
  box.replaceChildren(el("span", {}, "Buildings: "), ...items.map(([k, c]) => el("span", {}, el("i", { style: `background:${c}` }), k)),
    el("span", {}, `Cells: darker = higher ${metric.replaceAll("_", " ")}`));
}

function cellPaint(metric, max) {
  return ["interpolate", ["linear"], ["coalesce", ["get", metric], 0], 0, "#eef2ff", max, "#1e3a8a"];
}

async function loadVisibleChunks(map) {
  if (map.getZoom() < BUILDING_ZOOM) return;
  const b = map.getBounds();
  const todo = state.index.filter((c) => !state.loaded.has(c.cell) &&
    c.bbox[0] <= b.getEast() && c.bbox[2] >= b.getWest() && c.bbox[1] <= b.getNorth() && c.bbox[3] >= b.getSouth());
  for (const c of todo) state.loaded.set(c.cell, "loading");
  await Promise.all(todo.map(async (c) => {
    const fc = await getJSON(`${state.base}/geo/${c.cell}.json`);
    for (const f of fc.features) { f.properties.chunk = c.cell; state.features.push(f); }
    state.loaded.set(c.cell, "done");
  }));
  if (todo.length) map.getSource("buildings").setData({ type: "FeatureCollection", features: state.features });
}

async function main() {
  const cfg = await getJSON("/config.json");
  state.base = `/data/${cfg.fips}/${cfg.release}`;
  document.getElementById("release").textContent = `internal · pilot · release ${cfg.release}`;
  const [county, index, coverage] = await Promise.all([getJSON(`${state.base}/county.json`), getJSON(`${state.base}/index.json`), getJSON(`${state.base}/coverage.json`)]);
  state.index = index;
  renderCard(county);
  const map = new maplibregl.Map({
    container: "map",
    style: { version: 8, sources: { osm: { type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19, attribution: "© OpenStreetMap contributors" } },
      layers: [{ id: "osm", type: "raster", source: "osm", paint: { "raster-saturation": -0.7, "raster-opacity": 0.8 } }] },
    bounds: county.bbox, fitBoundsOptions: { padding: 20 },
  });
  window.floodMap = map; // for debugging and the browser test
  map.addControl(new maplibregl.NavigationControl(), "top-right");
  map.on("load", () => {
    const metricSel = document.getElementById("metric");
    const maxOf = (m) => Math.max(1e-9, ...coverage.features.map((f) => f.properties[m] ?? 0));
    map.addSource("coverage", { type: "geojson", data: coverage });
    map.addLayer({ id: "coverage", type: "fill", source: "coverage", maxzoom: BUILDING_ZOOM + 1,
      paint: { "fill-color": cellPaint(metricSel.value, maxOf(metricSel.value)), "fill-opacity": ["interpolate", ["linear"], ["zoom"], 12, 0.7, BUILDING_ZOOM + 1, 0] } });
    map.addLayer({ id: "coverage-line", type: "line", source: "coverage", maxzoom: BUILDING_ZOOM, paint: { "line-color": "#94a3b8", "line-width": 0.4 } });
    map.addSource("buildings", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "buildings", type: "fill", source: "buildings", minzoom: BUILDING_ZOOM - 0.5,
      paint: { "fill-color": ["match", ["coalesce", ["get", "bfe_call"], "none"], "below", CALL_COLORS.below, "too_close", CALL_COLORS.too_close,
        "above", CALL_COLORS.above, "not_applicable", CALL_COLORS.not_applicable, NO_CALL], "fill-opacity": 0.75 } });
    map.addLayer({ id: "buildings-line", type: "line", source: "buildings", minzoom: BUILDING_ZOOM, paint: { "line-color": "#334155", "line-width": 0.3 } });
    map.addLayer({ id: "selected", type: "line", source: "buildings", filter: ["==", ["get", "building_id"], ""], paint: { "line-color": "#111827", "line-width": 3 } });
    legend(metricSel.value);
    metricSel.addEventListener("change", () => {
      map.setPaintProperty("coverage", "fill-color", cellPaint(metricSel.value, maxOf(metricSel.value)));
      legend(metricSel.value);
    });
    map.on("moveend", () => loadVisibleChunks(map).catch(console.error));
    map.on("click", "coverage", (e) => {
      if (map.getZoom() >= BUILDING_ZOOM) return;
      const p = e.features[0].properties;
      new maplibregl.Popup().setLngLat(e.lngLat).setDOMContent(el("div", {},
        el("b", {}, `cell ${p.cell}`), el("br"), `buildings ${p.buildings}, SFHA ${p.touches_sfha}, decided ${pct(p.sfha_decided_share)}, below ${p.sfha_below}, certificates ${p.floor_record}`,
        el("br"), "zoom in to see buildings")).addTo(map);
    });
    map.on("click", "buildings", async (e) => {
      const p = e.features[0].properties;
      if (!state.records.has(p.chunk)) state.records.set(p.chunk, await getJSON(`${state.base}/rec/${p.chunk}.json`));
      map.setFilter("selected", ["==", ["get", "building_id"], p.building_id]);
      renderRecord(state.records.get(p.chunk)[p.building_id]);
    });
    for (const id of ["buildings", "coverage"]) {
      map.on("mouseenter", id, () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", id, () => { map.getCanvas().style.cursor = ""; });
    }
  });
}

main().catch((err) => {
  document.getElementById("card").replaceChildren(el("p", { class: "why" }, `Could not load: ${err.message}`));
});
