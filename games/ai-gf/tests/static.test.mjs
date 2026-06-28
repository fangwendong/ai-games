import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import assert from "node:assert/strict";

const root = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, root), "utf8");

const requiredFiles = [
  "index.html",
  "src/styles.css",
  "src/app.js",
  "src/scene-tree.js",
  "manifest.webmanifest",
  "sw.js",
  "assets/icon.svg",
  "assets/linqi-2d.png",
  "assets/couple-main.png",
  "assets/hero-2d.png",
  "assets/bg-apartment.png",
  "assets/bg-street.png",
  "assets/bg-park.png",
  "docs/ASSETS.md",
  "docs/GDD.md",
  "docs/2D_GAME_SPEC.md",
  "tests/runtime-smoke.test.mjs",
  "android/app/build.gradle",
  "android/app/src/main/java/com/fangwendong/aigf/MainActivity.java"
];

for (const file of requiredFiles) {
  assert.equal(existsSync(new URL(file, root)), true, `${file} should exist`);
}

const [html, css, js, manifest, sw, gdd, gameSpec] = await Promise.all([
  read("index.html"),
  read("src/styles.css"),
  read("src/app.js"),
  read("manifest.webmanifest"),
  read("sw.js"),
  read("docs/GDD.md"),
  read("docs/2D_GAME_SPEC.md")
]);

assert.match(html, /id="gameCanvas"/, "canvas exists");
assert.match(html, /id="objectiveLabel"/, "objective label exists");
assert.match(html, /id="promptText"/, "prompt text exists");
assert.match(html, /id="interactButton"/, "interact button exists");
assert.match(html, /id="dashButton"/, "dash button exists");
assert.match(html, /id="photoButton"/, "photo button exists");
assert.match(html, /id="joystick"/, "joystick exists");
assert.match(html, /id="questPanel"/, "quest panel exists");
assert.match(html, /id="dialogueSheet"/, "dialogue sheet exists");
assert.match(html, /AI女友/, "title exists");

assert.match(css, /\.game-shell/, "game shell exists");
assert.match(css, /#gameCanvas/, "canvas styles exist");
assert.match(css, /\.prompt-bar/, "prompt bar exists");
assert.match(css, /\.dialogue-sheet/, "dialogue sheet styles exist");
assert.match(css, /\.joystick/, "joystick styles exist");
assert.match(css, /\.quest-panel/, "quest panel styles exist");
assert.match(css, /@media \(pointer: coarse\)/, "touch controls exist");

assert.match(js, /const QUESTS = \[/, "quest data exists");
assert.match(js, /const INTERACTABLES = \[/, "interactables exist");
assert.match(js, /new SceneTree\(\)/, "scene tree exists");
assert.match(js, /function handleQuestInteraction\(/, "quest interaction exists");
assert.match(js, /function handlePhoto\(/, "photo action exists");
assert.match(js, /function triggerDash\(/, "dash action exists");
assert.match(js, /function drawWorld\(/, "canvas renderer exists");
assert.match(js, /function drawPlayer\(/, "player renderer exists");
assert.match(js, /window\.__aiGfDebug/, "debug hook exists");

assert.match(sw, /CACHE_NAME/, "service worker cache exists");
assert.match(sw, /ai-gf-v18/, "service worker cache version is current");
assert.match(sw, /skipWaiting/, "service worker activates updates quickly");

assert.equal(JSON.parse(manifest).display, "standalone", "manifest is installable");
assert.equal(JSON.parse(manifest).orientation, "portrait-primary", "manifest uses portrait orientation");
assert.equal(JSON.parse(manifest).icons.length > 0, true, "manifest has an icon");

assert.match(gdd, /原神/, "GDD describes the new exploration direction");
assert.match(gameSpec, /2D 探索/, "2D spec mentions exploration");

console.log("Static checks passed.");
