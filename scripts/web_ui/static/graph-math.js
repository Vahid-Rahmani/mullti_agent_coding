/* ─────────────────────────────────────────────────────────────────────
   graph-math.js — pure graph math for the Phase 24/24B graph explorer.
   Vanilla JS, no DOM access, no randomness: every function is a pure
   function of its inputs, so it runs identically in the browser and under
   Node for unit testing. Loaded before app.js as a global (window.GraphMath).

   Phase 24B rebuild:
   - Layout is section-anchored: each vault section's hub node is pinned to
     a fixed anchor (root + System at center, sections on a ring around it)
     and only member nodes relax around their hub with corrected
     Fruchterman–Reingold physics (repulsion k²/d, attraction d²/k), weak
     cross-section attraction, per-node gravity toward the section hub, and
     a hard minimum-distance enforcement that makes node overlap impossible.
   - LOD edge culling: which edges are drawn depends on the zoom band
     (out = hub↔hub only, normal = any hub-touching edge, in = everything).
   - Section filters + Core/Important view are pure functions over the graph.

   Covers: zoom bands / level-of-detail (LOD), camera + fit math, pan
   clamping, section-anchored layout, edge culling, filtering, minimap
   projection.
   ───────────────────────────────────────────────────────────────────── */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GraphMath = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var MIN_ZOOM = 0.2, MAX_ZOOM = 5;
  var OUT_ZOOM = 0.55, IN_ZOOM = 1.4;
  var HUB_DEGREE = 10;   // degree at/above which a node is "important"

  // Layout world is larger than the viewBox so sections get real space;
  // fitCamera then frames the camera over the content.
  var LAYOUT_W = 1400, LAYOUT_H = 1000;
  var TARGET_EDGE = 85;       // desired edge length == force constant k (compact)
  var MIN_NODE_GAP = 14;      // extra clearance beyond the node radii
  var SECTION_ORDER = ["root", "00-System", "01-Architecture", "02-Agents",
                       "03-Tasks", "04-Decisions", "05-Documentation", "06-Testing"];

  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

  /* ── level of detail ──────────────────────────────────────────── */
  function bandForZoom(z) {
    if (z < OUT_ZOOM) return "out";
    if (z > IN_ZOOM) return "in";
    return "normal";
  }

  function radiusFor(node, band) {
    var deg = node.degree || 0;
    var base = band === "out" ? 3 + Math.min(deg, 18) * 0.16
             : band === "normal" ? 5 + Math.min(deg, 18) * 0.24
             : 8 + Math.min(deg, 18) * 0.42;
    var capped = Math.max(2.5, Math.min(base, 24));
    var hub = (node.folder === "root" || deg >= HUB_DEGREE) ? 1.3 : 1;
    return Math.round(capped * hub * 100) / 100;
  }

  // Zoomed out keeps labels only on the important/root/section nodes;
  // normal shows the same set (leaf labels appear once zoomed in).
  function labelVisibleFor(node, band) {
    if (band === "in") return true;
    return node.folder === "root" || (node.degree || 0) >= HUB_DEGREE;
  }

  function labelYOffset(radius, band) {
    if (band === "out") return 0;
    return radius + (band === "in" ? 5 : 3);
  }

  function edgeOpacity(band) {
    return band === "out" ? 0.28 : band === "normal" ? 0.45 : 0.75;
  }

  function isHub(node) {
    return node.folder === "root" || (node.degree || 0) >= HUB_DEGREE;
  }

  /* ── camera ───────────────────────────────────────────────────── */
  // camera = { scale, tx, ty }; world transform = translate(tx,ty) scale(scale)
  function screenToWorld(cam, sx, sy) {
    return { x: (sx - cam.tx) / cam.scale, y: (sy - cam.ty) / cam.scale };
  }

  function worldToScreen(cam, wx, wy) {
    return { x: cam.tx + wx * cam.scale, y: cam.ty + wy * cam.scale };
  }

  function zoomAtPoint(cam, sx, sy, factor, vw, vh) {
    var scale = clamp(cam.scale * factor, MIN_ZOOM, MAX_ZOOM);
    if (scale === cam.scale) return { scale: scale, tx: cam.tx, ty: cam.ty };
    var w = screenToWorld(cam, sx, sy);
    return { scale: scale, tx: sx - w.x * scale, ty: sy - w.y * scale };
  }

  function panClamp(cam, wb, vw, vh, margin) {
    if (!wb) return { scale: cam.scale, tx: cam.tx, ty: cam.ty };
    margin = margin || 60;
    var scale = cam.scale;
    var tx0 = vw - (wb.maxX + margin) * scale;   // keep right edge inside [1]
    var tx1 = -(wb.minX - margin) * scale;       // keep left edge inside   [2]
    var tx;
    if (tx1 - tx0 > 1e-6) tx = clamp(cam.tx, tx0, tx1);
    else tx = (tx0 + tx1) / 2;                   // world narrower than viewport
    var ty0 = vh - (wb.maxY + margin) * scale;
    var ty1 = -(wb.minY - margin) * scale;
    var ty;
    if (ty1 - ty0 > 1e-6) ty = clamp(cam.ty, ty0, ty1);
    else ty = (ty0 + ty1) / 2;
    return { scale: scale, tx: tx, ty: ty };
  }

  function worldBounds(nodes) {
    if (!nodes || !nodes.length) return null;
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    nodes.forEach(function (n) {
      if (n.x < minX) minX = n.x;
      if (n.x > maxX) maxX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.y > maxY) maxY = n.y;
    });
    if (!isFinite(minX)) return null;
    if (maxX - minX < 1) maxX = minX + 1;
    if (maxY - minY < 1) maxY = minY + 1;
    return { minX: minX, minY: minY, maxX: maxX, maxY: maxY };
  }

  function fitCamera(wb, vw, vh, padding) {
    padding = padding || 40;
    if (!wb) return { scale: 1, tx: vw / 2, ty: vh / 2 };
    var bw = wb.maxX - wb.minX || 1, bh = wb.maxY - wb.minY || 1;
    var scale = Math.min((vw - 2 * padding) / bw, (vh - 2 * padding) / bh);
    scale = clamp(scale, MIN_ZOOM, MAX_ZOOM);
    var cx = (wb.minX + wb.maxX) / 2, cy = (wb.minY + wb.maxY) / 2;
    return { scale: scale, tx: vw / 2 - cx * scale, ty: vh / 2 - cy * scale };
  }

  /* ── minimap ──────────────────────────────────────────────────── */
  function minimapProject(wb, mmW, mmH, pad) {
    pad = pad || 4;
    var bw = (wb.maxX - wb.minX) || 1, bh = (wb.maxY - wb.minY) || 1;
    var s = Math.min((mmW - 2 * pad) / bw, (mmH - 2 * pad) / bh);
    var cx = (wb.minX + wb.maxX) / 2, cy = (wb.minY + wb.maxY) / 2;
    return { s: s, ox: mmW / 2 - cx * s, oy: mmH / 2 - cy * s };
  }

  function worldToMinimap(proj, wx, wy) {
    return { x: proj.ox + wx * proj.s, y: proj.oy + wy * proj.s };
  }

  function minimapToWorld(proj, mx, my) {
    return { x: (mx - proj.ox) / proj.s, y: (my - proj.oy) / proj.s };
  }

  function viewportRect(cam, wb, vw, vh, mmW, mmH) {
    var proj = minimapProject(wb, mmW, mmH);
    var tl0 = screenToWorld(cam, 0, 0);
    var br0 = screenToWorld(cam, vw, vh);
    var tl = worldToMinimap(proj, tl0.x, tl0.y);
    var br = worldToMinimap(proj, br0.x, br0.y);
    var x = clamp(Math.min(tl.x, br.x), 0, mmW - 1);
    var y = clamp(Math.min(tl.y, br.y), 0, mmH - 1);
    return {
      x: x,
      y: y,
      w: Math.max(0, Math.min(mmW - x, Math.abs(br.x - tl.x))),
      h: Math.max(0, Math.min(mmH - y, Math.abs(br.y - tl.y))),
    };
  }

  /* ── interaction helpers ──────────────────────────────────────── */
  function didMove(dx, dy, threshold) {
    return Math.abs(dx) + Math.abs(dy) > (threshold === undefined ? 4 : threshold);
  }

  function neighborsOf(edges, name) {
    var out = [], seen = {};
    edges.forEach(function (p) {
      var other = null;
      if (p[0] === name) other = p[1];
      else if (p[1] === name) other = p[0];
      if (other && !seen[other]) { seen[other] = true; out.push(other); }
    });
    return out;
  }

  /* ── sections / anchors ───────────────────────────────────────── */
  function presentFolders(nodes) {
    var set = {}, out = [];
    nodes.forEach(function (n) {
      if (!set[n.folder]) { set[n.folder] = true; out.push(n.folder); }
    });
    out.sort(function (a, b) {
      return SECTION_ORDER.indexOf(a) - SECTION_ORDER.indexOf(b);
    });
    return out;
  }

  // Fixed, deterministic anchor per present section: root sits top-center,
  // System at the center, the remaining sections on a ring around it.
  function sectionAnchors(nodes, W, H) {
    W = W || LAYOUT_W; H = H || LAYOUT_H;
    var present = presentFolders(nodes);
    var cx = W / 2, cy = H / 2;
    var has = {};
    present.forEach(function (f) { has[f] = true; });
    var anchors = {};
    if (has.root) anchors.root = { x: cx, y: H * 0.11 };
    if (has["00-System"]) anchors["00-System"] = { x: cx, y: cy };
    var ring = present.filter(function (f) {
      return f !== "root" && f !== "00-System";
    });
    var R = Math.min(W, H) * 0.26;
    // ring starts at angle 0 (right side) so no ring section collides with
    // the root anchor at the top center (or the System anchor at the center)
    ring.forEach(function (f, i) {
      var a = (i / Math.max(1, ring.length)) * Math.PI * 2;
      anchors[f] = { x: cx + Math.cos(a) * R, y: cy + Math.sin(a) * R };
    });
    return anchors;
  }

  // Map of the single most important node per section (its highest-degree
  // member) — the set that forms the zoomed-out architecture spine.
  function sectionHubNames(nodes) {
    var byFolder = {};
    nodes.forEach(function (n) { (byFolder[n.folder] = byFolder[n.folder] || []).push(n); });
    var out = {};
    Object.keys(byFolder).forEach(function (f) {
      var best = null;
      byFolder[f].forEach(function (n) {
        if (!best || (n.degree || 0) > (best.degree || 0)) best = n;
      });
      if (best) out[best.name] = true;
    });
    return out;
  }

  function radiusEst(n) {
    return Math.min(22, 7 + (n.degree || 0) * 0.45);
  }

  /* ── layout (deterministic, section-anchored) ─────────────────── */
  function seedPositions(nodes, edges, W, H) {
    W = W || LAYOUT_W; H = H || LAYOUT_H;
    var anchors = sectionAnchors(nodes, W, H);
    var byFolder = {};
    nodes.forEach(function (n) { (byFolder[n.folder] = byFolder[n.folder] || []).push(n); });
    var pos = {};
    Object.keys(byFolder).forEach(function (f) {
      var members = byFolder[f].slice()
        .sort(function (a, b) { return (b.degree || 0) - (a.degree || 0); });
      var anchor = anchors[f] || { x: W / 2, y: H / 2 };
      members.forEach(function (m, i) {
        if (i === 0) { pos[m.name] = { x: anchor.x, y: anchor.y }; return; }
        var a = (i / members.length) * Math.PI * 2;
        var r = 110 + (i % 4) * 34;
        pos[m.name] = { x: anchor.x + Math.cos(a) * r, y: anchor.y + Math.sin(a) * r };
      });
    });
    return pos;
  }

  function runLayout(nodes, edges, opts) {
    opts = opts || {};
    var W = opts.W || LAYOUT_W, H = opts.H || LAYOUT_H;
    var iterations = opts.iterations == null ? 500 : opts.iterations;
    var k = opts.edgeLen || TARGET_EDGE;
    var n = nodes.length;
    var seed;
    if (opts.fixed) {
      // Stability mode: nodes named in opts.fixed keep their opts.seed
      // positions (previously settled); every other node falls back to the
      // deterministic section-anchored seed and relaxes normally.
      var baseSeed = seedPositions(nodes, edges, W, H);
      var givenSeed = opts.seed || {};
      seed = {};
      nodes.forEach(function (nd) {
        seed[nd.name] = givenSeed[nd.name] || baseSeed[nd.name];
      });
    } else {
      seed = opts.seed && opts.seed[nodes[0] && nodes[0].name]
        ? opts.seed
        : seedPositions(nodes, edges, W, H);
    }
    var pos = nodes.map(function (nd, i) {
      var p = seed[nd.name];
      if (p) return { x: p.x, y: p.y };
      var a = (i / Math.max(1, n)) * Math.PI * 2;
      return { x: W / 2 + Math.cos(a) * 90, y: H / 2 + Math.sin(a) * 90 };
    });
    var idx = {};
    nodes.forEach(function (nd, i) { idx[nd.name] = i; });
    var e = edges
      .filter(function (p) { return idx[p[0]] != null && idx[p[1]] != null; })
      .map(function (p) { return [idx[p[0]], idx[p[1]]]; });
    var sameFolder = {};
    e.forEach(function (pair, i) {
      sameFolder[i] = nodes[pair[0]].folder === nodes[pair[1]].folder;
    });

    // Hard pins: each section's highest-degree node sits exactly on its
    // section anchor and never moves (root nodes pin too, via their hub).
    var anchors = sectionAnchors(nodes, W, H);
    var byFolder = {};
    nodes.forEach(function (nd, i) {
      (byFolder[nd.folder] = byFolder[nd.folder] || []).push(i);
    });
    var pinned = {};
    Object.keys(byFolder).forEach(function (f) {
      var list = byFolder[f].slice()
        .sort(function (a, b) { return (nodes[b].degree || 0) - (nodes[a].degree || 0); });
      if (!list.length) return;
      var hi = list[0];
      var anchor = anchors[f];
      if (anchor) {
        pinned[hi] = true;
        pos[hi].x = anchor.x; pos[hi].y = anchor.y;
      }
    });
    // Stability pins: previously-laid-out nodes (opts.fixed, with positions in
    // opts.seed) keep their exact positions, so a re-render or a
    // visibility/topology change never moves an already-settled node. Only
    // nodes absent from opts.fixed relax.
    if (opts.fixed) {
      for (var fi = 0; fi < n; fi++) {
        if (opts.fixed[nodes[fi].name]) pinned[fi] = true;
      }
    }

    var t = 12;
    for (var it = 0; it < iterations; it++) {
      var f = nodes.map(function () { return { x: 0, y: 0 }; });
      // repulsion (k²/d — classic Fruchterman–Reingold); pins never move
      for (var i = 0; i < n; i++) for (var j = i + 1; j < n; j++) {
        if (pinned[i] && pinned[j]) continue;
        var dx = pos[i].x - pos[j].x, dy = pos[i].y - pos[j].y;
        var d2 = dx * dx + dy * dy; if (d2 < 1) d2 = 1;
        var d = Math.sqrt(d2); dx /= d; dy /= d;
        var force = Math.min(k * k / d, k * 2.2);
        if (!pinned[i]) { f[i].x += dx * force; f[i].y += dy * force; }
        if (!pinned[j]) { f[j].x -= dx * force; f[j].y -= dy * force; }
      }
      // attraction (d²/k) — intra-section strong, cross-section weak so the
      // dense hub-star links cannot drag sections back together
      for (var ei = 0; ei < e.length; ei++) {
        var a = e[ei][0], b = e[ei][1];
        if (pinned[a] && pinned[b]) continue;
        var dxe = pos[b].x - pos[a].x, dye = pos[b].y - pos[a].y;
        var de = Math.sqrt(dxe * dxe + dye * dye) || 1;
        var uxe = dxe / de, uye = dye / de;
        var fe = Math.min((de * de) / k * (sameFolder[ei] ? 1 : 0.22), k * 0.8);
        if (!pinned[a]) { f[a].x += uxe * fe; f[a].y += uye * fe; }
        if (!pinned[b]) { f[b].x -= uxe * fe; f[b].y -= uye * fe; }
      }
      // gravity: members toward their own section hub + a gentle center pull
      var hubIdx = {};
      Object.keys(byFolder).forEach(function (fld) {
        var list = byFolder[fld].slice()
          .sort(function (x, y) { return (nodes[y].degree || 0) - (nodes[x].degree || 0); });
        if (list.length) hubIdx[fld] = list[0];
      });
      for (var h = 0; h < n; h++) {
        if (pinned[h]) continue;
        var hi = hubIdx[nodes[h].folder];
        if (hi != null && hi !== h) {
          f[h].x += (pos[hi].x - pos[h].x) * 0.05;
          f[h].y += (pos[hi].y - pos[h].y) * 0.05;
        }
        f[h].x += (W / 2 - pos[h].x) * 0.002;
        f[h].y += (H / 2 - pos[h].y) * 0.002;
      }
      // integrate with cooling
      for (var m = 0; m < n; m++) {
        if (pinned[m]) continue;
        var fl = Math.sqrt(f[m].x * f[m].x + f[m].y * f[m].y) || 1;
        var scl = Math.min(fl, t) / fl;
        pos[m].x += f[m].x * scl;
        pos[m].y += f[m].y * scl;
      }
      // minimum-distance enforcement — node overlap is impossible; pins win
      for (var pi = 0; pi < n; pi++) for (var pj = pi + 1; pj < n; pj++) {
        if (pinned[pi] && pinned[pj]) continue;
        var mdx = pos[pi].x - pos[pj].x, mdy = pos[pi].y - pos[pj].y;
        var md2 = mdx * mdx + mdy * mdy;
        var minD = radiusEst(nodes[pi]) + radiusEst(nodes[pj]) + MIN_NODE_GAP;
        if (md2 >= minD * minD) continue;
        var md = Math.sqrt(md2) || 1;
        var push = (minD - md) / 2;
        var ux = mdx / md, uy = mdy / md;
        if (!pinned[pi]) { pos[pi].x += ux * push; pos[pi].y += uy * push; }
        if (!pinned[pj]) { pos[pj].x -= ux * push; pos[pj].y -= uy * push; }
      }
      t *= 0.94;
      if (t < 0.05) t = 0.05;
    }
    nodes.forEach(function (nd, i) { nd.x = pos[i].x; nd.y = pos[i].y; });
    return nodes;
  }

  /* ── LOD edge culling ─────────────────────────────────────────── */
  // out:    section-hub ↔ section-hub only  (the clean architecture spine)
  // normal: every real edge — every visible node's relationship is drawn
  //         (density is controlled by thin/dim styling, not by hiding links)
  // in:     every edge
  function edgeVisibleFor(edge, band, nodesByName, sectionHubs) {
    var a = nodesByName[edge[0]], b = nodesByName[edge[1]];
    if (!a || !b) return false;
    if (band === "out") {
      return !!(sectionHubs && sectionHubs[a.name] && sectionHubs[b.name]);
    }
    return true;
  }

  function isImportant(node, sectionHubs) {
    return node.folder === "root" || sectionHubs[node.name] ||
           (node.degree || 0) >= HUB_DEGREE;
  }

  /* ── section filter + core view ───────────────────────────────── */
  // Empty selection → everything. Otherwise: keep the selected sections
  // plus their direct neighbors that are *important* (root / section hub /
  // degree ≥ HUB_DEGREE) — because hubs like System_Architecture link to
  // every node, unfiltered 1-hop would just return the whole graph. Edges
  // are restricted to those touching the selected sections plus the
  // section-hub spine, so a filtered view stays clean.
  function applySectionFilter(nodes, edges, selected) {
    if (!selected || !selected.length) {
      return { nodes: nodes.slice(), edges: edges.slice() };
    }
    var sel = {};
    selected.forEach(function (f) { sel[f] = true; });
    var byName = {};
    nodes.forEach(function (n) { byName[n.name] = n; });
    var sectionHubs = sectionHubNames(nodes);
    var member = {};   // snapshot: section members (always kept)
    var keep = {};
    nodes.forEach(function (n) {
      if (sel[n.folder]) { member[n.name] = true; keep[n.name] = true; }
    });
    edges.forEach(function (p) {
      var a = byName[p[0]], b = byName[p[1]];
      if (member[p[0]] && b && isImportant(b, sectionHubs)) keep[p[1]] = true;
      if (member[p[1]] && a && isImportant(a, sectionHubs)) keep[p[0]] = true;
    });
    var outNodes = nodes.filter(function (n) { return keep[n.name]; });
    var outEdges = edges.filter(function (p) {
      if (!keep[p[0]] || !keep[p[1]]) return false;
      if (member[p[0]] || member[p[1]]) return true;      // touches the section
      var a = byName[p[0]], b = byName[p[1]];
      return !!(sectionHubs[a.name] && sectionHubs[b.name]);  // spine context
    });
    return { nodes: outNodes, edges: outEdges };
  }

  // Core/Important view: root + every section hub + all degree ≥ 10 nodes,
  // with only the structural edges: the section-hub spine plus each hub's
  // own intra-section edges. Cross-section member edges are dropped so the
  // result is a clean architecture map, not the whole vault.
  function coreGraph(nodes, edges) {
    var byFolder = {};
    nodes.forEach(function (n) { (byFolder[n.folder] = byFolder[n.folder] || []).push(n); });
    var hubs = {};   // section-hub (and root) spine membership
    var keep = {};
    nodes.forEach(function (n) {
      if (isHub(n)) keep[n.name] = true;
    });
    Object.keys(byFolder).forEach(function (f) {
      var best = null;
      byFolder[f].forEach(function (n) {
        if (!best || (n.degree || 0) > (best.degree || 0)) best = n;
      });
      if (best) { keep[best.name] = true; hubs[best.name] = true; }
    });
    nodes.forEach(function (n) {
      if (n.folder === "root") hubs[n.name] = true;
    });
    var byName = {};
    nodes.forEach(function (n) { byName[n.name] = n; });
    var outNodes = nodes.filter(function (n) { return keep[n.name]; });
    var outEdges = edges.filter(function (p) {
      if (!keep[p[0]] || !keep[p[1]]) return false;
      var a = byName[p[0]], b = byName[p[1]];
      if (hubs[a.name] && hubs[b.name]) return true;       // spine
      if (a.folder === b.folder && (hubs[a.name] || hubs[b.name])) return true;  // intra-section
      return false;
    });
    return { nodes: outNodes, edges: outEdges };
  }

  return {
    MIN_ZOOM: MIN_ZOOM, MAX_ZOOM: MAX_ZOOM,
    OUT_ZOOM: OUT_ZOOM, IN_ZOOM: IN_ZOOM, HUB_DEGREE: HUB_DEGREE,
    LAYOUT_W: LAYOUT_W, LAYOUT_H: LAYOUT_H, TARGET_EDGE: TARGET_EDGE,
    bandForZoom: bandForZoom,
    radiusFor: radiusFor,
    labelVisibleFor: labelVisibleFor,
    labelYOffset: labelYOffset,
    edgeOpacity: edgeOpacity,
    isHub: isHub,
    screenToWorld: screenToWorld,
    worldToScreen: worldToScreen,
    zoomAtPoint: zoomAtPoint,
    panClamp: panClamp,
    worldBounds: worldBounds,
    fitCamera: fitCamera,
    minimapProject: minimapProject,
    worldToMinimap: worldToMinimap,
    minimapToWorld: minimapToWorld,
    viewportRect: viewportRect,
    didMove: didMove,
    neighborsOf: neighborsOf,
    presentFolders: presentFolders,
    sectionAnchors: sectionAnchors,
    seedPositions: seedPositions,
    runLayout: runLayout,
    edgeVisibleFor: edgeVisibleFor,
    sectionHubNames: sectionHubNames,
    isImportant: isImportant,
    applySectionFilter: applySectionFilter,
    coreGraph: coreGraph,
  };
});
