import assert from "node:assert/strict";

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(value) {
    this.values.add(value);
  }

  remove(value) {
    this.values.delete(value);
  }

  toggle(value, force) {
    const shouldAdd = force ?? !this.values.has(value);
    if (shouldAdd) this.values.add(value);
    else this.values.delete(value);
  }

  contains(value) {
    return this.values.has(value);
  }
}

class FakeElement {
  constructor(selector, dataset = {}) {
    this.selector = selector;
    this.dataset = dataset;
    this.classList = new FakeClassList();
    this.listeners = {};
    this.children = [];
    this.childMap = new Map();
    this.style = { setProperty() {} };
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.value = "";
  }

  set innerHTML(value) {
    this._innerHTML = value;
    this.children = [];
    this.childMap.clear();
  }

  get innerHTML() {
    return this._innerHTML || "";
  }

  addEventListener(type, callback) {
    this.listeners[type] = callback;
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  querySelector(selector) {
    if (!this.childMap.has(selector)) {
      this.childMap.set(selector, new FakeElement(selector));
    }
    return this.childMap.get(selector);
  }

  querySelectorAll(selector) {
    if (selector === "button") return this.children;
    return [];
  }

  getBoundingClientRect() {
    return { left: 0, top: 0, width: 600, height: 400 };
  }

  click() {
    this.listeners.click?.({ preventDefault() {}, button: 0 });
  }
}

class FakeCanvas extends FakeElement {
  constructor(selector) {
    super(selector);
    this.calls = [];
    this.ctx = new Proxy(
      {
        canvas: this,
        fillStyle: "#000",
        strokeStyle: "#000",
        lineWidth: 1,
        font: "16px sans-serif",
        globalAlpha: 1,
        textAlign: "left"
      },
      {
        get: (target, prop) => {
          if (prop === "createLinearGradient" || prop === "createRadialGradient") {
            return () => ({ addColorStop() {} });
          }
          if (prop === "measureText") return (text) => ({ width: String(text).length * 10 });
          if (typeof prop === "string" && prop in target) return target[prop];
          if (typeof prop === "string") {
            return (...args) => {
              this.calls.push({ method: prop, args });
            };
          }
          return undefined;
        },
        set: (target, prop, value) => {
          target[prop] = value;
          return true;
        }
      }
    );
  }

  getContext() {
    return this.ctx;
  }
}

const elements = new Map();
const canvas = new FakeCanvas("#gameCanvas");
elements.set("#gameCanvas", canvas);

[
  "#objectiveLabel",
  "#zoneLabel",
  "#bondLabel",
  "#hintLabel",
  "#promptText",
  "#interactButton",
  "#dashButton",
  "#photoButton",
  "#questButton",
  "#questPanel",
  "#closeQuestButton",
  "#questList",
  "#dialogueSheet",
  "#dialogueKicker",
  "#dialogueText",
  "#dialogueChoices",
  "#closeDialogueButton",
  "#joystick",
  "#joystickKnob",
  "#touchInteractButton",
  "#touchDashButton"
].forEach((selector) => {
  elements.set(selector, new FakeElement(selector));
});

globalThis.localStorage = {
  data: new Map(),
  getItem(key) {
    return this.data.get(key) || null;
  },
  setItem(key, value) {
    this.data.set(key, String(value));
  }
};

globalThis.window = {
  __AI_GF_DISABLE_AUTO_LOOP__: true,
  devicePixelRatio: 1,
  innerWidth: 1280,
  innerHeight: 720,
  matchMedia() {
    return { matches: true, addEventListener() {}, removeEventListener() {} };
  },
  addEventListener() {},
  location: {
    reload() {
      throw new Error("unexpected reload");
    }
  }
};

globalThis.document = {
  querySelector(selector) {
    const element = elements.get(selector);
    assert.ok(element, `missing fake element for ${selector}`);
    return element;
  },
  querySelectorAll() {
    return [];
  },
  createElement(tagName) {
    return new FakeElement(tagName);
  }
};

Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: {
    serviceWorker: {
      addEventListener() {},
      register() {
        return Promise.resolve({ update() {} });
      }
    }
  }
});

globalThis.performance = {
  now() {
    return 0;
  }
};

await import("../src/app.js");

const debug = globalThis.window.__aiGfDebug;
assert.ok(debug, "debug hook should exist");
assert.equal(elements.get("#objectiveLabel").textContent, "先走到林栖身边");
assert.match(elements.get("#promptText").textContent, /房间里等你|说话/);
assert.ok(canvas.calls.length > 0, "canvas should render on bootstrap");

debug.state.player.x = 430;
debug.state.player.y = 410;
debug.interact();
assert.equal(elements.get("#dialogueSheet").hidden, false);
assert.match(elements.get("#dialogueText").textContent, /出去/);
elements.get("#dialogueChoices").children[0].click();
assert.equal(debug.state.questIndex, 1);
assert.equal(elements.get("#objectiveLabel").textContent, "穿过门廊去街区");
debug.closeDialogue();

debug.state.player.x = 980;
debug.state.player.y = 404;
debug.interact();
assert.equal(debug.state.questIndex, 2);
assert.equal(debug.state.dashUnlocked, false);
assert.equal(elements.get("#dashButton").disabled, true);
debug.closeDialogue();

debug.state.player.x = 1540;
debug.state.player.y = 360;
debug.interact();
assert.equal(debug.state.questIndex, 3);
assert.equal(debug.state.dashUnlocked, true);
assert.equal(elements.get("#dashButton").disabled, false);
debug.closeDialogue();

debug.dash();
assert.ok(debug.state.player.dash > 0);

debug.state.player.x = 2480;
debug.state.player.y = 1120;
debug.interact();
elements.get("#dialogueChoices").children[0].click();
assert.equal(debug.state.questIndex, 4);
debug.closeDialogue();

debug.state.player.x = 2810;
debug.state.player.y = 980;
debug.interact();
elements.get("#dialogueChoices").children[0].click();
assert.equal(debug.state.questIndex, 5);
assert.equal(debug.state.photoUnlocked, true);
assert.equal(elements.get("#photoButton").disabled, false);
debug.closeDialogue();

debug.photo();
assert.equal(debug.state.photoCount > 0, true);
assert.equal(elements.get("#dialogueSheet").hidden, false);
assert.match(elements.get("#dialogueText").textContent, /照片|收尾/);

console.log("Runtime smoke checks passed.");
