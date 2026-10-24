// node --test .github/scripts/
const test = require("node:test");
const assert = require("node:assert/strict");
const { evaluate } = require("./contract-approval.js");

const HEAD = "a".repeat(40);
const OLD = "b".repeat(40);
const CONTRACT = [{ filename: "contracts/ports.py", status: "modified" }];
let nextId = 1;
const review = (login, state, commit_id = HEAD, type = "User") => ({ id: nextId++, user: { login, type }, state, commit_id });
const run = (over) => evaluate({ author: "atuldhull", headSha: HEAD, files: CONTRACT, reviews: [], ...over });

test("pull request without contract changes passes", () => {
  const r = run({ files: [{ filename: "frontend/src/App.jsx", status: "modified" }] });
  assert.equal(r.ok, true);
  assert.deepEqual(r.required, []);
});

test("zero approvals fails and names both missing teammates", () => {
  const r = run({});
  assert.equal(r.ok, false);
  assert.deepEqual(r.missing.map((m) => m.login), ["gundatharuntej2006-hue", "ritikakulkarni06-art"]);
  assert.match(r.message, /both other team members/);
});

test("one of two required approvals is not enough", () => {
  const r = run({ reviews: [review("gundatharuntej2006-hue", "APPROVED")] });
  assert.equal(r.ok, false);
  assert.deepEqual(r.missing.map((m) => m.login), ["ritikakulkarni06-art"]);
});

test("both other teammates approving the current head passes", () => {
  const r = run({ reviews: [review("gundatharuntej2006-hue", "APPROVED"), review("ritikakulkarni06-art", "APPROVED")] });
  assert.equal(r.ok, true);
  assert.deepEqual(r.approved, ["gundatharuntej2006-hue", "ritikakulkarni06-art"]);
});

test("approvals from unrelated accounts and bots do not count", () => {
  const r = run({
    reviews: [review("someone-else", "APPROVED"), review("ritikakulkarni06-art", "APPROVED", HEAD, "Bot"),
      review("gundatharuntej2006-hue", "APPROVED")],
  });
  assert.equal(r.ok, false);
  assert.deepEqual(r.missing.map((m) => m.login), ["ritikakulkarni06-art"]);
});

test("author self-approval is ignored", () => {
  const r = run({ reviews: [review("atuldhull", "APPROVED"), review("gundatharuntej2006-hue", "APPROVED")] });
  assert.equal(r.ok, false);
  assert.ok(!r.required.includes("atuldhull"));
});

test("a dismissed approval no longer counts", () => {
  const r = run({ reviews: [review("gundatharuntej2006-hue", "DISMISSED"), review("ritikakulkarni06-art", "APPROVED")] });
  assert.equal(r.ok, false);
  assert.deepEqual(r.missing, [{ login: "gundatharuntej2006-hue", reason: "approval was dismissed" }]);
});

test("a later changes-requested review overrides an earlier approval", () => {
  const r = run({
    reviews: [review("gundatharuntej2006-hue", "APPROVED"), review("ritikakulkarni06-art", "APPROVED"),
      review("ritikakulkarni06-art", "CHANGES_REQUESTED")],
  });
  assert.equal(r.ok, false);
  assert.deepEqual(r.missing, [{ login: "ritikakulkarni06-art", reason: "requested changes" }]);
});

test("a comment after an approval keeps the approval", () => {
  const r = run({
    reviews: [review("gundatharuntej2006-hue", "APPROVED"), review("ritikakulkarni06-art", "APPROVED"),
      review("ritikakulkarni06-art", "COMMENTED")],
  });
  assert.equal(r.ok, true);
});

test("approvals of an older commit are stale", () => {
  const r = run({ reviews: [review("gundatharuntej2006-hue", "APPROVED", OLD), review("ritikakulkarni06-art", "APPROVED")] });
  assert.equal(r.ok, false);
  assert.match(r.missing[0].reason, /older commit/);
});

test("an outside author needs all three", () => {
  const two = [review("gundatharuntej2006-hue", "APPROVED"), review("ritikakulkarni06-art", "APPROVED")];
  const r = run({ author: "outside-contributor", reviews: two });
  assert.equal(r.ok, false);
  assert.deepEqual(r.missing.map((m) => m.login), ["atuldhull"]);
  assert.match(r.message, /all three/);
  assert.equal(run({ author: "outside-contributor", reviews: [...two, review("atuldhull", "APPROVED")] }).ok, true);
});

test("renaming a file out of contracts/ is a contract change", () => {
  const r = run({ files: [{ filename: "backend/app/ports.py", previous_filename: "contracts/ports.py", status: "renamed" }] });
  assert.equal(r.ok, false);
  assert.deepEqual(r.files, ["contracts/ports.py -> backend/app/ports.py"]);
});

test("added and removed contract files are detected", () => {
  for (const status of ["added", "removed"]) {
    assert.equal(run({ files: [{ filename: "contracts/events/wf/x.v1.json", status }] }).ok, false);
  }
});

test("editing the enforcement workflow itself needs the whole team", () => {
  assert.equal(run({ files: [{ filename: ".github/workflows/contracts-approval.yml", status: "modified" }] }).ok, false);
  assert.equal(run({ files: [{ filename: ".github/scripts/contract-approval.js", status: "modified" }] }).ok, false);
});

test("logins are compared case-insensitively", () => {
  const r = run({ reviews: [review("GundaTharunTej2006-hue", "APPROVED"), review("RitikaKulkarni06-art", "APPROVED")] });
  assert.equal(r.ok, true);
});

test("a truncated file list fails closed", () => {
  const r = run({ files: [{ filename: "README.md" }], changedFiles: 3500 });
  assert.equal(r.ok, false);
  assert.match(r.message, /Could not inspect all changed files/);
});
