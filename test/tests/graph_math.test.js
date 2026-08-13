"use strict";
/* graph-math.js unit tests — run with `node test/tests/graph_math.test.js`. */

const assert = require("assert");
const path = require("path");
const M = require(path.join(__dirname, "..", "..", "scripts", "web_ui", "static", "graph-math.js"));

let count = 0;
function ok(cond, msg) {
  count += 1;
  assert.ok(cond, msg);
}
function eq(a, b, msg) {
  count += 1;
  assert.strictEqual(a, b, msg);
}
function approx(a, b, msg, eps) {
  count += 1;
  assert.ok(Math.abs(a - b) < (eps || 1e-6), msg + ` (${a} vs ${b})`);
}

/* ── zoom bands / LOD ─────────────────────────────────────────── */
eq(M.bandForZoom(0.3), "out", "0.3 zoomed out");
eq(M.bandForZoom(0.55), "normal", "0.55 normal");
eq(M.bandForZoom(1), "normal", "1.0 normal");
eq(M.bandForZoom(1.4), "normal", "1.4 still normal");
eq(M.bandForZoom(2), "in", "2.0 zoomed in");

const leaf = { name: "X", degree: 2, type: "system", folder: "00-System" };
const hub = { name: "H", degree: 14, type: "system", folder: "root" };

ok(!M.labelVisibleFor(leaf, "out"), "leaf label hidden when zoomed out");
ok(M.labelVisibleFor(hub, "out"), "hub/root label visible when zoomed out");
ok(!M.labelVisibleFor(leaf, "normal"), "leaf label hidden at normal zoom");
ok(M.labelVisibleFor(hub, "normal"), "hub label visible at normal zoom");
ok(M.labelVisibleFor(leaf, "in"), "leaf label visible when zoomed in");
ok(M.labelVisibleFor(hub, "in"), "hub label visible when zoomed in");

ok(M.radiusFor(hub, "out") < M.radiusFor(hub, "normal"), "node grows between out/normal");
ok(M.radiusFor(hub, "normal") < M.radiusFor(hub, "in"), "node grows between normal/in");
eq(M.labelYOffset(12, "out"), 0, "no label offset when zoomed out");
ok(M.labelYOffset(12, "in") > 12, "zoomed-in label sits below the node");

/* ── camera / zoom ────────────────────────────────────────────── */
const cam0 = { scale: 1, tx: 0, ty: 0 };
eq(M.zoomAtPoint(cam0, 50, 40, 2, 760, 400).scale, 2, "zoom doubles");
const z = M.zoomAtPoint(cam0, 50, 40, 2, 760, 400);
const w0 = M.screenToWorld(cam0, 50, 40);
const w1 = M.screenToWorld(z, 50, 40);
approx(w0.x, w1.x, "cursor-fixed zoom keeps world x", 1e-9);
approx(w0.y, w1.y, "cursor-fixed zoom keeps world y", 1e-9);
eq(M.zoomAtPoint(cam0, 0, 0, 100, 760, 400).scale, M.MAX_ZOOM, "zoom clamps at MAX");
eq(M.zoomAtPoint(cam0, 0, 0, 0.0001, 760, 400).scale, M.MIN_ZOOM, "zoom clamps at MIN");

/* pan clamp keeps the view inside the graph bounds (±margin) */
const wb = { minX: 100, minY: 100, maxX: 300, maxY: 200 };
const c0 = M.panClamp({ scale: 1, tx: 0, ty: 0 }, wb, 760, 440, 60);
eq(c0.tx, 180, "pan clamped/centered on x");
eq(c0.ty, 70, "pan clamped/centered on y");
const c1 = M.panClamp({ scale: 1, tx: 99999, ty: -99999 }, wb, 760, 440, 60);
eq(c1.tx, c0.tx, "pan clamp deterministic on extreme x");
eq(c1.ty, c0.ty, "pan clamp deterministic on extreme y");
eq(M.panClamp({ scale: 1, tx: 10, ty: 10 }, null, 760, 440).tx, 10, "panClamp null-safe");

/* fit / reset */
const fit = M.fitCamera(wb, 760, 440, 40);
ok(fit.scale > 0 && isFinite(fit.scale), "fit produces finite scale");
const bl = M.worldToScreen(fit, wb.minX, wb.minY);
const tr = M.worldToScreen(fit, wb.maxX, wb.maxY);
ok(bl.x >= 40 - 1e-6 && bl.y >= 40 - 1e-6, "fit respects padding top-left");
ok(tr.x <= 760 - 40 + 1e-6 && tr.y <= 440 - 40 + 1e-6, "fit respects padding bottom-right");
const fitEmpty = M.fitCamera(null, 760, 440, 40);
ok(isFinite(fitEmpty.tx) && isFinite(fitEmpty.ty), "fit empty-safe");

/* ── layout determinism / stability ───────────────────────────── */
const ns = [
  { name: "A", folder: "00-System", degree: 5 },
  { name: "B", folder: "02-Agents", degree: 4 },
  { name: "C", folder: "00-System", degree: 3 },
  { name: "D", folder: "02-Agents", degree: 2 },
];
const es = [["A", "C"], ["B", "D"], ["A", "B"]];
const n1 = ns.map((n) => Object.assign({}, n));
const n2 = ns.map((n) => Object.assign({}, n));
M.runLayout(n1, es, { W: 760, H: 440, iterations: 90 });
M.runLayout(n2, es, { W: 760, H: 440, iterations: 90 });
const p1 = n1.map((n) => [Math.round(n.x * 100), Math.round(n.y * 100)]);
const p2 = n2.map((n) => [Math.round(n.x * 100), Math.round(n.y * 100)]);
eq(JSON.stringify(p1), JSON.stringify(p2), "layout is deterministic (stable)");
ok(n1.every((n) => isFinite(n.x) && isFinite(n.y)), "layout yields finite positions");
ok(M.worldBounds(n1).minX < M.worldBounds(n1).maxX, "worldBounds valid");

/* seeded layout reuses positions (refresh stability) */
const n3 = ns.map((n) => Object.assign({}, n));
M.runLayout(n3, es, { W: 760, H: 440, iterations: 90, seed: M.seedPositions(ns, es, 760, 440) });
ok(n3.every((n) => isFinite(n.x) && isFinite(n.y)), "seeded layout finite");

/* ── selection / neighbors ────────────────────────────────────── */
const nb = M.neighborsOf([["A", "B"], ["B", "C"], ["A", "C"]], "A");
eq(nb.length, 2, "neighbors of A are B and C");
ok(nb.includes("B") && nb.includes("C"), "neighbor set exact");

/* ── minimap ──────────────────────────────────────────────────── */
const wb2 = { minX: 100, minY: 50, maxX: 900, maxY: 500 };
const proj = M.minimapProject(wb2, 140, 100);
const P = M.worldToMinimap(proj, 500, 275);
approx(P.x, 70, "minimap maps world center x to minimap center", 1e-6);
approx(P.y, 50, "minimap maps world center y to minimap center", 1e-6);
const back = M.minimapToWorld(proj, P.x, P.y);
approx(back.x, 500, "minimap→world round-trip x", 1e-6);
approx(back.y, 275, "minimap→world round-trip y", 1e-6);
const vp = M.viewportRect(cam0, wb2, 760, 440, 140, 100);
ok(vp.x >= 0 && vp.y >= 0 && vp.w > 0 && vp.w <= 140 && vp.h <= 100,
   "viewport rect lives inside the minimap");
const fitCam = M.fitCamera(wb2, 760, 440, 40);
const vpF = M.viewportRect(fitCam, wb2, 760, 440, 140, 100);
ok(vpF.w > 100, "fit camera fills most of the minimap width");

/* interaction guard */
ok(!M.didMove(2, 1), "small move is not a drag");
ok(M.didMove(5, 0), "big move is a drag");

/* ── Phase 24B: section-anchored layout ─────────────────────────── */
const sec = [
  { name: "Core", folder: "00-System", degree: 29 },
  { name: "Arch", folder: "01-Architecture", degree: 38 },
  { name: "Arch2", folder: "01-Architecture", degree: 19 },
  { name: "Agents", folder: "02-Agents", degree: 34 },
  { name: "A1", folder: "02-Agents", degree: 24 },
  { name: "Docs", folder: "05-Documentation", degree: 22 },
  { name: "D1", folder: "05-Documentation", degree: 8 },
  { name: "Tests", folder: "06-Testing", degree: 16 },
];
const secE = [["Core", "Arch"], ["Core", "Agents"], ["Core", "Docs"], ["Core", "Tests"],
              ["Arch", "Arch2"], ["Arch", "Agents"], ["Arch", "Docs"],
              ["Agents", "A1"], ["Agents", "Docs"], ["Docs", "D1"],
              ["Tests", "Core"], ["Tests", "Arch"]];
const copy = (arr) => arr.map((o) => Object.assign({}, o));
const laid = copy(sec);
M.runLayout(laid, secE, { iterations: 400 });

/* sections end up in distinct regions (no central cluster) */
const cent = {};
laid.forEach((nd) => {
  (cent[nd.folder] = cent[nd.folder] || { x: 0, y: 0, n: 0 });
  cent[nd.folder].x += nd.x; cent[nd.folder].y += nd.y; cent[nd.folder].n++;
});
const folders = Object.keys(cent);
for (let i = 0; i < folders.length; i++) for (let j = i + 1; j < folders.length; j++) {
  const a = cent[folders[i]], b = cent[folders[j]];
  const d = Math.hypot(a.x / a.n - b.x / b.n, a.y / a.n - b.y / b.n);
  ok(d > 180, `section centroids separated (${folders[i]} vs ${folders[j]}: ${d.toFixed(0)}px)`);
}

/* nodes never overlap */
let minPairD = Infinity;
for (let i = 0; i < laid.length; i++) for (let j = i + 1; j < laid.length; j++) {
  const d = Math.hypot(laid[i].x - laid[j].x, laid[i].y - laid[j].y);
  if (d < minPairD) minPairD = d;
}
ok(minPairD > 24, "nodes never overlap (min distance " + minPairD.toFixed(1) + "px)");

/* section hubs are pinned to their anchors */
const anchors = M.sectionAnchors(sec, M.LAYOUT_W, M.LAYOUT_H);
const byName2 = {};
laid.forEach((nd) => (byName2[nd.name] = nd));
approx(byName2.Arch.x, anchors["01-Architecture"].x, "arch hub pinned x", 1e-6);
approx(byName2.Arch.y, anchors["01-Architecture"].y, "arch hub pinned y", 1e-6);
approx(byName2.Core.x, anchors["00-System"].x, "system hub pinned x", 1e-6);
approx(byName2.Core.y, anchors["00-System"].y, "system hub pinned y", 1e-6);
ok(M.presentFolders(sec).indexOf("00-System") === 0, "present folders sorted by SECTION_ORDER");

/* ── Phase 24C: compact spacing ─────────────────────────────────── */
const anchors3 = M.sectionAnchors(sec, M.LAYOUT_W, M.LAYOUT_H);
const ringR = Math.hypot(anchors3["01-Architecture"].x - anchors3["00-System"].x,
                         anchors3["01-Architecture"].y - anchors3["00-System"].y);
const minDim = Math.min(M.LAYOUT_W, M.LAYOUT_H);
ok(ringR >= 0.20 * minDim && ringR <= 0.30 * minDim,
   "section ring radius reduced ~25% (compact layout, " + ringR.toFixed(0) + "px)");
ok(M.TARGET_EDGE < 100, "target edge length reduced for compact layout");

/* ── Phase 24B: LOD edge culling ────────────────────────────────── */
const nb2 = {};
laid.forEach((nd) => (nb2[nd.name] = nd));
const sh = M.sectionHubNames(laid);
ok(sh.Core && sh.Arch && sh.Agents && sh.Docs && sh.Tests, "section hubs identified per folder");
ok(!sh.Arch2 && !sh.D1 && !sh.A1, "non-highest-degree members are not section hubs");
ok(M.edgeVisibleFor(["Core", "Arch"], "out", nb2, sh), "section-hub edge visible when zoomed out");
ok(!M.edgeVisibleFor(["Arch2", "D1"], "out", nb2, sh), "member edge hidden when zoomed out");
ok(!M.edgeVisibleFor(["Arch", "D1"], "out", nb2, sh), "hub-to-leaf edge hidden when zoomed out");
ok(M.edgeVisibleFor(["Arch2", "D1"], "normal", nb2, sh), "edge visible at normal zoom");
ok(M.edgeVisibleFor(["Arch2", "D1"], "in", nb2, sh), "leaf edge visible when zoomed in");
ok(!M.edgeVisibleFor(["Nope", "D1"], "in", nb2, sh), "edges to unknown nodes are culled");

/* every visible spine hub keeps a visible edge when zoomed out */
const spineEdges = secE.filter((e) => M.edgeVisibleFor(e, "out", nb2, sh));
const spineNodes = {};
spineEdges.forEach((e) => { spineNodes[e[0]] = true; spineNodes[e[1]] = true; });
Object.keys(sh).forEach((name) => {
  ok(spineNodes[name], `spine hub ${name} has a visible edge when zoomed out`);
});

/* leaf↔leaf relationships are visible at normal/in zoom */
const ll = [
  { name: "L1", folder: "05-Documentation", degree: 3 },
  { name: "L2", folder: "05-Documentation", degree: 4 },
];
const llBy = {};
ll.forEach((n) => (llBy[n.name] = n));
ok(M.edgeVisibleFor(["L1", "L2"], "normal", llBy, {}), "leaf↔leaf edge visible at normal zoom");
ok(M.edgeVisibleFor(["L1", "L2"], "in", llBy, {}), "leaf↔leaf edge visible when zoomed in");
ok(!M.edgeVisibleFor(["L1", "L2"], "out", llBy, {}), "leaf↔leaf edge hidden when zoomed out");

/* ── Phase 24B: section filters ─────────────────────────────────── */
const secE2 = secE.concat([["A1", "D1"]]);   // leaf directly linked to a member
const flt = M.applySectionFilter(sec, secE2, ["02-Agents"]);
ok(flt.nodes.some((nd) => nd.name === "Agents"), "filter keeps section nodes");
ok(flt.nodes.some((nd) => nd.name === "Core"), "filter pulls in important 1-hop neighbors");
ok(!flt.nodes.some((nd) => nd.name === "D1"), "filter skips leaf neighbors (importance rule)");
ok(flt.edges.every((p) =>
  flt.nodes.some((nd) => nd.name === p[0]) && flt.nodes.some((nd) => nd.name === p[1])),
  "filtered edges stay inside the node set");
ok(!flt.edges.some((p) => (p[0] === "A1" && p[1] === "D1") || (p[0] === "D1" && p[1] === "A1")),
  "filtered edges never touch excluded leaves");
ok(flt.nodes.length < sec.length, "filter shrinks the node set");
eq(M.applySectionFilter(sec, secE2, []).nodes.length, sec.length, "empty filter returns all nodes");

/* filtered layout stays deterministic */
const fc1 = copy(M.applySectionFilter(sec, secE, ["05-Documentation"]).nodes);
const fc2 = copy(M.applySectionFilter(sec, secE, ["05-Documentation"]).nodes);
M.runLayout(fc1, M.applySectionFilter(sec, secE, ["05-Documentation"]).edges, { iterations: 200 });
M.runLayout(fc2, M.applySectionFilter(sec, secE, ["05-Documentation"]).edges, { iterations: 200 });
eq(JSON.stringify(fc1.map((nd) => [Math.round(nd.x * 100), Math.round(nd.y * 100)])),
   JSON.stringify(fc2.map((nd) => [Math.round(nd.x * 100), Math.round(nd.y * 100)])),
   "filtered layout is deterministic");

/* ── Phase 24B: core/important view ─────────────────────────────── */
const coreE = secE.concat([["Arch2", "A1"]]);   // cross-section member edge
const core = M.coreGraph(sec, coreE);
ok(core.nodes.some((nd) => nd.name === "Core"), "core keeps the system hub");
ok(!core.nodes.some((nd) => nd.name === "D1"), "core excludes leaf nodes");
ok(core.edges.every((p) =>
  core.nodes.some((nd) => nd.name === p[0]) && core.nodes.some((nd) => nd.name === p[1])),
  "core edges stay inside the core node set");
ok(core.edges.some((p) => (p[0] === "Core" && p[1] === "Arch") || (p[0] === "Arch" && p[1] === "Core")),
  "core keeps the section-hub spine");
ok(core.edges.some((p) => (p[0] === "Arch" && p[1] === "Arch2") || (p[0] === "Arch2" && p[1] === "Arch")),
  "core keeps intra-section hub→core-member edges");
ok(!core.edges.some((p) => (p[0] === "Docs" && p[1] === "D1") || (p[0] === "D1" && p[1] === "Docs")),
  "core drops edges to non-core members");
ok(!core.edges.some((p) => (p[0] === "Arch2" && p[1] === "A1") || (p[0] === "A1" && p[1] === "Arch2")),
  "core drops cross-section member edges");

console.log("graph-math tests passed:", count);
