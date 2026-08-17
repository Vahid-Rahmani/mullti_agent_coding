"use strict";
/* Graph layout stability tests — run with `node test/tests/graph_stability.test.js`.

   Loads graph-math.js + the real app.js and drives layoutGraph (the Home graph
   position engine) to prove nodes never jump when nothing relevant changed:

     G1. same nodes/edges re-laid out -> identical positions (re-render stable)
     G2. hiding one node (visibility change) -> remaining nodes keep positions
     G3. adding one node (legitimate change) -> existing nodes keep positions,
         the new node still receives a finite position
*/

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const GM = require("../../scripts/web_ui/static/graph-math.js");
const APP_JS = path.join(__dirname, "..", "..", "scripts", "web_ui", "static", "app.js");
const src = fs.readFileSync(APP_JS, "utf8");

let count = 0;
function ok(cond, msg) { count += 1; assert.ok(cond, msg); }
function approx(a, b, msg, eps) {
  count += 1;
  assert.ok(Math.abs(a - b) < (eps || 1e-6), msg + ` (${a} vs ${b})`);
}

/* minimal DOM shim — only window.GraphMath + window/document need to exist at
   eval time; layoutGraph itself is pure (no DOM). */
function makeEl() {
  return {
    children: [], className: "", textContent: "", title: "", value: "",
    dataset: {}, style: {}, parentNode: null,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; },
    setAttribute() {}, addEventListener() {}, querySelector() { return null; },
    querySelectorAll() { return []; },
  };
}
global.window = {
  GraphMath: GM,
  addEventListener() {}, removeEventListener() {},
  innerWidth: 1000, innerHeight: 800,
  localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
};
global.document = {
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement: makeEl, createElementNS: makeEl,
  addEventListener() {}, documentElement: {}, body: { style: { setProperty() {} } },
};
global.getComputedStyle = () => ({ getPropertyValue: () => "" });

eval(src);
const { layoutGraph } = global.window.MACApp;

const mk = () => [
  { name: "Core", folder: "00-System", degree: 12 },
  { name: "SysA", folder: "00-System", degree: 3 },
  { name: "SysB", folder: "00-System", degree: 3 },
  { name: "Agents", folder: "02-Agents", degree: 8 },
  { name: "A1", folder: "02-Agents", degree: 2 },
  { name: "Docs", folder: "05-Documentation", degree: 5 },
  { name: "D1", folder: "05-Documentation", degree: 2 },
];
const edges = [["Core", "SysA"], ["Core", "SysB"], ["Core", "Agents"],
               ["Agents", "A1"], ["Core", "Docs"], ["Docs", "D1"]];
const copy = (a) => a.map((o) => Object.assign({}, o));

/* first layout populates the settled-position cache */
const first = copy(mk());
layoutGraph(first, edges);
const pos = {};
first.forEach((n) => (pos[n.name] = { x: n.x, y: n.y }));

/* G1 — re-render with the SAME nodes/edges: identical positions */
const again = copy(mk());
layoutGraph(again, edges);
again.forEach((n) => {
  approx(n.x, pos[n.name].x, "G1: re-render keeps x stable (" + n.name + ")", 1e-6);
  approx(n.y, pos[n.name].y, "G1: re-render keeps y stable (" + n.name + ")", 1e-6);
});

/* G2 — visibility change (hide D1): remaining nodes keep positions */
const hidden = copy(mk()).filter((n) => n.name !== "D1");
const hiddenEdges = edges.filter((p) => p[0] !== "D1" && p[1] !== "D1");
layoutGraph(hidden, hiddenEdges);
hidden.forEach((n) => {
  approx(n.x, pos[n.name].x, "G2: visibility change keeps x stable (" + n.name + ")", 1e-6);
  approx(n.y, pos[n.name].y, "G2: visibility change keeps y stable (" + n.name + ")", 1e-6);
});

/* G3 — legitimate change (add D2): existing nodes keep positions, new finite */
const grown = copy(mk()).concat([{ name: "D2", folder: "05-Documentation", degree: 1 }]);
const grownEdges = edges.concat([["Docs", "D2"]]);
layoutGraph(grown, grownEdges);
grown.forEach((n) => {
  if (!pos[n.name]) {
    ok(Number.isFinite(n.x) && Number.isFinite(n.y), "G3: new node gets a finite position");
    return;
  }
  approx(n.x, pos[n.name].x, "G3: added node keeps x stable (" + n.name + ")", 1e-6);
  approx(n.y, pos[n.name].y, "G3: added node keeps y stable (" + n.name + ")", 1e-6);
});

console.log("graph stability tests passed:", count);
