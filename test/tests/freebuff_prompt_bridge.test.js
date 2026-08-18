/* Dashboard prompt bridge contract: FreeBuff bypasses normal dispatch. */
const fs = require("fs");
const src = fs.readFileSync("scripts/web_ui/static/app.js", "utf8");

if (!src.includes("const rawPrompt = input.value")) throw new Error("raw dashboard text missing");
if (!src.includes("/freebuff/submit")) throw new Error("FreeBuff bridge endpoint missing");
if (!src.includes("if (!freebuffBridge) renderUserMessage(rawTarget, prompt)")) {
  throw new Error("FreeBuff synthetic prompt rendering was not bypassed");
}
if (!src.includes("freebuffBridge\n          ? await post")) {
  throw new Error("FreeBuff bridge branch missing");
}
console.log("freebuff prompt bridge contract passed");
