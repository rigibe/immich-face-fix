const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const html = fs.readFileSync(require("node:path").join(__dirname, "../index.html"), "utf8");
const helper = html.match(/async function canAutoReassign\([\s\S]*?\n}\n/)[0];

async function check(faces, candidates = [{ id: "face" }]) {
  const context = {
    wrongPerson: { id: "wrong" },
    correctPerson: { id: "correct" },
    apiJSON: async () => {
      if (faces instanceof Error) throw faces;
      return faces;
    },
  };
  vm.createContext(context);
  return vm.runInContext(helper + "\ncanAutoReassign", context)("asset", candidates);
}

test("automatic reassignment requires one unchanged candidate and no target face", async () => {
  const face = { id: "face", person: { id: "wrong" } };
  assert.equal(await check([face]), true);
  assert.equal(await check([face, { id: "other", person: { id: "correct" } }]), false);
  assert.equal(await check([face, { id: "other", person: { id: "wrong" } }]), false);
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
