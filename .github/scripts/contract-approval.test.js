// node --test .github/scripts/contract-approval.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { evaluate, statusFor, main, STATUS_CONTEXT } = require("./contract-approval.js");

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

// ---- wider protected set ----

test("any workflow, script or CODEOWNERS change needs the whole team", () => {
  for (const filename of [".github/workflows/ci.yml", ".github/workflows/contracts-approval-review-signal.yml",
    ".github/scripts/anything.js", ".github/CODEOWNERS"]) {
    assert.equal(run({ files: [{ filename, status: "modified" }] }).ok, false, filename);
  }
});

test("a PR that weakens the decision logic still needs both teammates on its head", () => {
  const files = [{ filename: ".github/scripts/contract-approval.js", status: "modified" }];
  assert.equal(run({ files, reviews: [review("gundatharuntej2006-hue", "APPROVED")] }).ok, false);
  assert.equal(run({ files, reviews: [review("gundatharuntej2006-hue", "APPROVED"), review("ritikakulkarni06-art", "APPROVED")] }).ok, true);
});

test("a new commit after full approval needs fresh approvals", () => {
  const reviews = [review("gundatharuntej2006-hue", "APPROVED", OLD), review("ritikakulkarni06-art", "APPROVED", OLD)];
  const r = run({ reviews });
  assert.equal(r.ok, false);
  assert.equal(r.missing.length, 2);
});

test("status payload carries the required context and fits GitHub's limit", () => {
  const s = statusFor(run({}));
  assert.equal(s.context, STATUS_CONTEXT);
  assert.equal(s.state, "failure");
  assert.ok(s.description.length <= 140);
  assert.equal(statusFor(run({ files: [] })).state, "success");
});

// ---- GitHub API layer (fake client) ----

function fakeGithub({ prs, files = CONTRACT, reviews = [] }) {
  const statuses = [];
  const lists = { list: () => Object.values(prs), listFiles: () => files, listReviews: () => reviews };
  const github = {
    paginate: async (fn) => fn(),
    rest: {
      pulls: {
        get: async ({ pull_number }) => ({ data: prs[pull_number] }),
        list: lists.list, listFiles: lists.listFiles, listReviews: lists.listReviews,
      },
      repos: { createCommitStatus: async (s) => statuses.push(s) },
    },
  };
  return { github, statuses };
}
const pr = (number, sha = HEAD, state = "open") => ({ number, state, user: { login: "atuldhull" }, head: { sha }, changed_files: 1 });
const ctx = (eventName, payload) => ({ eventName, payload, repo: { owner: "o", repo: "r" } });
const core = { info() {} };

test("pull_request_target: status is posted on the current head, not the event's", async () => {
  const { github, statuses } = fakeGithub({ prs: { 7: pr(7, "c".repeat(40)) } });
  const ok = await main({ github, context: ctx("pull_request_target", { pull_request: { number: 7 } }), core });
  assert.equal(ok, false);
  assert.equal(statuses[0].sha, "c".repeat(40));
  assert.equal(statuses[0].context, STATUS_CONTEXT);
});

test("workflow_run after a review: same-repo PR listed by GitHub is re-evaluated", async () => {
  const reviews = [review("gundatharuntej2006-hue", "APPROVED"), review("ritikakulkarni06-art", "APPROVED")];
  const { github, statuses } = fakeGithub({ prs: { 3: pr(3) }, reviews });
  const ok = await main({ github, context: ctx("workflow_run", { workflow_run: { head_sha: HEAD, pull_requests: [{ number: 3 }] } }), core });
  assert.equal(ok, true);
  assert.equal(statuses[0].state, "success");
});

test("workflow_run for a fork PR (not listed) is matched by head commit", async () => {
  const { github, statuses } = fakeGithub({ prs: { 4: pr(4, HEAD), 5: pr(5, OLD) } });
  await main({ github, context: ctx("workflow_run", { workflow_run: { head_sha: HEAD, pull_requests: [] } }), core });
  assert.equal(statuses.length, 1);
  assert.equal(statuses[0].sha, HEAD);
});

test("closed pull requests get no status", async () => {
  const { github, statuses } = fakeGithub({ prs: { 9: pr(9, HEAD, "closed") } });
  await main({ github, context: ctx("pull_request_target", { pull_request: { number: 9 } }), core });
  assert.equal(statuses.length, 0);
});

test("other events judge nothing", async () => {
  const { github, statuses } = fakeGithub({ prs: { 1: pr(1) } });
  await main({ github, context: ctx("pull_request_review", { pull_request: { number: 1 } }), core });
  assert.equal(statuses.length, 0);
});

// ---- the workflow files themselves ----

const wf = (name) => fs.readFileSync(path.join(__dirname, "..", "workflows", name), "utf8");

test("the authority workflow only uses triggers that run the default-branch copy", () => {
  const y = wf("contracts-approval.yml");
  assert.match(y, /pull_request_target:/);
  assert.match(y, /workflow_run:\s*\n\s*workflows: \[contracts-approval-review-signal\]/);
  assert.doesNotMatch(y, /^\s*pull_request_review:/m);
  assert.doesNotMatch(y, /^\s*pull_request:/m);
  assert.doesNotMatch(y, /ref:\s*\$\{\{\s*github\.event\.pull_request\.head/);   // never checks out PR code
  assert.match(y, /persist-credentials: false/);
  const perms = y.match(/^permissions:\n((?: {2}.+\n)+)/m)[1].trim().split("\n").map((l) => l.trim());
  assert.deepEqual(perms, ["contents: read", "pull-requests: read", "statuses: write"]);
});

test("the review signal workflow has no permissions and passes no data", () => {
  const y = wf("contracts-approval-review-signal.yml");
  assert.match(y, /^name: contracts-approval-review-signal$/m);   // must match the workflow_run trigger
  assert.match(y, /^permissions: \{\}$/m);
  assert.doesNotMatch(y, /actions\/checkout|upload-artifact|secrets\./);
});
