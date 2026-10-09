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

const DATUM = "Elevations: feet NAVD88 (US survey feet); lidar geoid GEOID12B; certificates: geoid not stated.";

const fmt = (v, d = 2) => (v === null || v === undefined ? "—" : typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(d)) : String(v));
const pct = (v) => (v === null || v === undefined ? "—" : `${(100 * v).toFixed(1)}%`);

function stat(value, label) {
  return el("div", { class: "stat" }, el("b", {}, value), el("span", {}, label));
}

// Both scores side by side, each with its population (review DA1): FDEM held-out is the release gate's set; the
// county certificates are the independent check. Falls back to the single gate score for an old county.json.
function accuracyTable(acc, gate) {
  if (!acc) {
    return el("table", {}, ...[["houses scored (FDEM held-out)", fmt(gate.n)], ["MAE (ft)", fmt(gate.MAE, 3)],
      ["90% band coverage", pct(gate.coverage)]].map(([k, v]) => el("tr", {}, el("td", {}, k), el("td", {}, v))));
  }
  const f = acc.fdem_held_out.all, k = acc.county_independent.all;
  const fe = acc.fdem_held_out["elevated 5-9"] || {}, ke = acc.county_independent["elevated 5-9"] || {};
  const row = (label, a, b) => el("tr", {}, el("td", {}, label), el("td", {}, a), el("td", {}, b));
  return el("table", { class: "acc" },
    el("tr", {}, el("th", {}, ""), el("th", { title: acc.populations.fdem_held_out }, "FDEM held-out"),
      el("th", { title: acc.populations.county_independent }, "County certificates")),
    row("houses scored", fmt(f.n), fmt(k.n)),
    row("MAE (ft)", fmt(f.MAE, 2), fmt(k.MAE, 2)),
    row("within 1 ft", pct(f["within 1 ft"]), pct(k["within 1 ft"])),
    row("BFE side correct", pct(f["BFE side"]), pct(k["BFE side"])),
    row("90% band coverage", pct(f.coverage), pct(k.coverage)),
    row("decided calls correct", pct(f["decided correct"]), pct(k["decided correct"])),
    row("elevated houses (diagram 5-9): MAE ft (n)", `${fmt(fe.MAE, 2)} (${fmt(fe.n)})`, `${fmt(ke.MAE, 2)} (${fmt(ke.n)})`));
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
    el("h2", {}, "Floor model accuracy (two populations)"),
    accuracyTable(c.accuracy, a),
    ...(c.accuracy && c.accuracy.warning ? [el("p", { class: "warn" }, c.accuracy.warning)] : []),
    el("table", {},
      ...[["band calibration", c.band_calibration], ["lidar", c.lidar]].map(([k, v]) => el("tr", {}, el("td", {}, k), el("td", {}, v)))),
    el("p", { class: "datum" }, DATUM),
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
      plainRow("building id", r.building_id),
      plainRow("parcels at the centroid", r.parcels_at_centroid > 1 ? `${r.parcels_at_centroid}: condo / stacked parcel (floor model is for single buildings)` : r.parcels_at_centroid),
      plainRow("footprint", `${fmt(r.footprint_area_m2, 0)} m²`), plainRow("in the risk area", r.in_risk_area)),
    el("h2", {}, "Verdict"),
    el("table", {},
      el("tr", {}, el("td", {}, "floor vs BFE"), el("td", {},
        call ? el("span", { class: `call ${call}` }, call.replace("_", " ")) : el("span", { class: "why" }, `null: ${r.bfe_call_null}`),
        r.bfe_call_basis ? el("span", { class: "src" }, `basis: ${r.bfe_call_basis}`) : null)),
      el("tr", {}, el("td", {}, "floor minus BFE"), el("td", {}, r.floor_minus_bfe_ft === null ? "—" : `${fmt(r.floor_minus_bfe_ft)} ft`,
        r.floor_minus_bfe_band_lo !== null && r.floor_minus_bfe_band_lo !== undefined ? el("span", { class: "src" }, `band ${fmt(r.floor_minus_bfe_band_lo)} to ${fmt(r.floor_minus_bfe_band_hi)} ft`) : null)),
      plainRow("raised (> 3 ft)", r.raised_flag === null || r.raised_flag === undefined ? `null: ${r.raised_flag_null}` : `${r.raised_flag ? "yes" : "no"}${r.raised_flag_source ? ` (rule: ${r.raised_flag_source})` : ""}`),
      r.floor_definition ? plainRow("floor compared", r.floor_definition.replaceAll("_", " ")) : null,
      r.bfe_call_lowest_floor !== undefined ? el("tr", {}, el("td", {}, "lowest floor vs BFE (NFIP)"), el("td", {},
        r.bfe_call_lowest_floor ? el("span", { class: `call ${r.bfe_call_lowest_floor}` }, r.bfe_call_lowest_floor.replace("_", " ")) : el("span", { class: "why" }, `null: ${r.bfe_call_lowest_floor_null}`))) : null),
    el("h2", {}, "Flood context"),
    el("table", {}, plainRow("zones (share of footprint)", zones || `null: ${r.zones_null}`), plainRow("touches SFHA", r.touches_sfha),
      plainRow("FIRM effective", r.firm_effective_date), valueRow(r, "BFE (NAVD88)", "bfe"), plainRow("BFE method", r.bfe_method),
      r.bfe_note ? plainRow("BFE note", r.bfe_note) : null,
      r.firm_status ? plainRow("FIRM status (county)", r.firm_status) : null),
    el("h2", {}, "Floor"),
    el("table", {}, valueRow(r, "first floor height", "ffh"), valueRow(r, "first floor elevation", "ffe"),
      r.lowest_floor_ft !== undefined ? valueRow(r, "lowest floor (certificate C2a)", "lowest_floor") : null,
      r.band_note ? plainRow("band note", r.band_note) : null,
      r.record_stage ? plainRow("certificate stage", r.record_stage.replaceAll("_", " ")) : null,
      r.record_vintage_note ? plainRow("date note", r.record_vintage_note) : null,
      r.record_note ? plainRow("certificate note", r.record_note) : null,
      r.ffe_record_lidar_conflict ? plainRow("check", "certificate conflicts with lidar") : null),
    el("h2", {}, "Ground, roof, building"),
    el("table", {}, valueRow(r, r.ground_suspect === undefined ? "ground (lidar ring minimum)" : "ground (lidar ring median)", "ground"),
      r.ground_suspect !== undefined ? plainRow("ground ring min / range", `${fmt(r.ground_ring_min_ft)} / ${fmt(r.ground_ring_range_ft)} ft${r.ground_suspect ? " (suspect: slope, wall or water next to the house)" : ""}`) : null,
      r.lidar_note ? plainRow("lidar note", r.lidar_note) : null,
      valueRow(r, "roof (above grade)", "roof"),
      valueRow(r, "eave (above grade)", "eave"), valueRow(r, "year built", "year_built", "year_built", ""),
      valueRow(r, "living area", "living_area_sqft", "living_area_sqft", "sq ft")),
    el("h2", {}, "Provenance"),
    el("table", {}, plainRow("release", r.release), plainRow("model", r.model_version), plainRow("inputs", (r.input_licences || []).join(", "))),
    el("p", { class: "datum" }, DATUM),
    flagBox(r),
    el("details", {}, el("summary", {}, "all columns"), el("pre", {}, JSON.stringify(r, null, 1))),
  );
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}

// "Flag this building" (r1 plan docs/09 A4): the note goes to the Worker, which files it under the data team's inbox in
// the private bucket. Nothing on the map changes.
const FLAG_REASONS = [["floor", "floor height / elevation looks wrong"], ["ground", "ground looks wrong (water, seawall, slope)"],
  ["call", "above / below call looks wrong"], ["zone", "flood zone or BFE looks wrong"], ["building", "wrong building / address / condo"], ["other", "other"]];

function flagBox(r) {
  const reason = el("select", {}, ...FLAG_REASONS.map(([v, t]) => el("option", { value: v }, t)));
  const note = el("textarea", { maxlength: "2000", placeholder: "What looks wrong, and how do you know? (no personal data)" });
  const status = el("span", { class: "src" }, "");
  const btn = el("button", { type: "button" }, "Send flag");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    status.textContent = "sending…";
    try {
      const res = await fetch("/flag", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ building_id: r.building_id, release: r.release, reason: reason.value, note: note.value }) });
      if (!res.ok) throw new Error(`${res.status}`);
      status.textContent = `sent (${(await res.json()).id})`;
      note.value = "";
    } catch (err) {
      status.textContent = `not sent: ${err.message}`;
    } finally {
      btn.disabled = false;
    }
  });
  return el("div", { class: "flag" }, el("b", {}, "Flag this building"), el("label", {}, "reason", reason), note, btn, status);
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
