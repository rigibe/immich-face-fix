const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync(require("node:path").join(__dirname, "../index.html"), "utf8");
const helper = html.match(/async function canAutoReassign\([\s\S]*?\n}\n/)[0];

async function check(faces, candidates = [{ id: "face" }], reviewedFaces = [{ id: "face" }]) {
  const context = {
    wrongPerson: { id: "wrong" },
    correctPerson: { id: "correct" },
    apiJSON: async () => {
      if (faces instanceof Error) throw faces;
      return faces;
    },
  };
  vm.createContext(context);
  return vm.runInContext(helper + "\ncanAutoReassign", context)("asset", candidates, reviewedFaces);
}

test("automatic reassignment requires unchanged reviewed faces, one candidate and no target face", async () => {
  const face = { id: "face", person: { id: "wrong" } };
  assert.equal(await check([face]), true);
  assert.equal(await check([face, { id: "other", person: { id: "correct" } }]), false);
  assert.equal(await check([face, { id: "other", person: { id: "wrong" } }]), false);
  assert.equal(await check([face, { id: "other", person: { id: "wrong" } }], [face], [face, { id: "other" }]), true);
  assert.equal(await check([face, { id: "new", person: { id: "wrong" } }], [face], [face, { id: "other" }]), false);
  assert.equal(await check([]), false);
  assert.equal(await check(new Error("network")), false);
  assert.equal(await check([face], [face, face]), false);
});

test("countdown does not reassign if review moves to another photo during recheck", async () => {
  const source = html.match(/async function autoReassignCurrent\([\s\S]*?\n}\n/)[0];
  let resolveCheck;
  let writes = 0;
  const context = {
    currentItem: { assetId: "first" },
    countdownAutoFixFaces: [{ id: "face" }],
    canAutoReassign: () => new Promise(resolve => { resolveCheck = resolve; }),
    reassignFaceAPI: async () => { writes++; },
  };
  vm.createContext(context);
  const run = vm.runInContext(source + "\nautoReassignCurrent", context);
  const pending = run();
  context.currentItem = { assetId: "second" };
  resolveCheck(true);
  await pending;
  assert.equal(writes, 0);
});

test("review includes only assets with a verified matching owner", () => {
  const source = html.match(/function ownedAssetIds\([\s\S]*?\n}\n/)[0];
  const filter = vm.runInNewContext(source + "\nownedAssetIds");
  const result = filter([{ id: "mine", ownerId: "me" }, { id: "theirs", ownerId: "other" }], "me");
  assert.equal(JSON.stringify(result), '["mine"]');
  assert.throws(() => filter([{ id: "unknown" }], "me"), /owner could not be verified/);
  assert.throws(() => filter([{ id: "mine", ownerId: "me" }], ""), /owner could not be verified/);
});

test("rechecking refreshes suggestions without starting an auto-fix", async () => {
  const source = html.match(/async function recheckSuggestions\([\s\S]*?\n}\n/)[0];
  const face = { id: "face" };
  const item = { assetId: "asset", wrongFaces: [face], isDup: false };
  const countdowns = [];
  const context = {
    currentItem: item,
    correctPerson: { id: "correct" },
    wrongPerson: { id: "wrong" },
    cancelCountdown() {},
    drawOverlays() {},
    showSuggestions: async (shown, refresh) => {
      assert.equal(shown, item);
      assert.equal(refresh, true);
    },
    startCountdown: (...args) => countdowns.push(args),
    alert() {},
  };
  const recheck = vm.runInNewContext(source + "\nrecheckSuggestions", context);
  await recheck();
  assert.equal(countdowns.length, 0);
});

test("rechecking does not start a countdown after leaving the photo", async () => {
  const source = html.match(/async function recheckSuggestions\([\s\S]*?\n}\n/)[0];
  let resolve;
  let started = false;
  const context = {
    currentItem: { wrongFaces: [{ id: "face" }] },
    cancelCountdown() {},
    drawOverlays() {},
    showSuggestions: () => new Promise(r => { resolve = r; }),
    startCountdown: () => { started = true; },
  };
  const recheck = vm.runInNewContext(source + "\nrecheckSuggestions", context);
  const pending = recheck();
  context.currentItem = null;
  resolve([{ person: { id: "correct" } }]);
  await pending;
  assert.equal(started, false);
});

test("photo dates use the calendar date from Immich and handle missing or invalid values", () => {
  const source = html.match(/function formatPhotoDate\([\s\S]*?\n}\n/)[0];
  const calendar = html.match(/function calendarDate\([\s\S]*?\n}\n/)[0];
  const format = vm.runInNewContext(calendar + source + "\nformatPhotoDate");
  assert.match(format("2020-01-02T23:59:00-08:00"), /2020/);
  assert.notEqual(format("2020-01-02T23:59:00-08:00"), "Photo date unavailable");
  assert.equal(format(null), "Photo date unavailable");
  assert.equal(format("2020-02-30T00:00:00"), "Photo date unavailable");
});

test("only photos with known dates before a known birth date are excluded", () => {
  const calendar = html.match(/function calendarDate\([\s\S]*?\n}\n/)[0];
  const source = html.match(/function isBeforeBirth\([\s\S]*?\n}\n/)[0];
  const before = vm.runInNewContext(calendar + source + "\nisBeforeBirth");
  assert.equal(before("2025-03-14T23:00:00Z", "2025-03-15"), true);
  assert.equal(before("2025-03-15T00:00:00Z", "2025-03-15"), false);
  assert.equal(before("2026-01-01", "2025-03-15"), false);
  assert.equal(before(null, "2025-03-15"), false);
  assert.equal(before("2024-01-01", null), false);
  assert.equal(before("2024-01-01", "2025-02-30"), false);
});
