// Decides whether a pull request has the approvals that changes to shared contracts need.
//
// evaluate() is pure and unit tested (contract-approval.test.js). main() is the thin GitHub API layer.
// The workflow runs this file from the DEFAULT branch (pull_request_target / workflow_run), never from the PR.

const TEAM = ["atuldhull", "gundatharuntej2006-hue", "ritikakulkarni06-art"];

// The commit status that branch protection must require. Only the trusted workflow posts it.
const STATUS_CONTEXT = "contracts-approval/designated-approvals";

// Changing these needs the whole team. All workflows and scripts are included: any workflow with a write token
// could post a status, and the enforcement files must not be weakened by the pull request they judge.
const PROTECTED = [
  "contracts/",
  ".github/workflows/",
  ".github/scripts/",
  ".github/CODEOWNERS",
];

const norm = (login) => String(login || "").toLowerCase();

function isProtected(path) {
  return typeof path === "string" && PROTECTED.some((p) => (p.endsWith("/") ? path.startsWith(p) : path === p));
}

// A rename counts if either the old or the new path is protected (renaming a file out of contracts/ is a change).
function protectedFiles(files) {
  return files.filter((f) => isProtected(f.filename) || isProtected(f.previous_filename)).map((f) =>
    f.previous_filename && f.previous_filename !== f.filename ? `${f.previous_filename} -> ${f.filename}` : f.filename,
  );
}

// Latest decisive review per designated reviewer, in the order GitHub recorded them.
// COMMENTED and PENDING never change a decision; DISMISSED cancels an earlier approval.
function latestDecisions(reviews, team) {
  const latest = new Map();
  const ordered = [...reviews].sort((a, b) => (a.id ?? 0) - (b.id ?? 0));
  for (const r of ordered) {
    const login = norm(r.user?.login);
    if (!team.includes(login) || r.user?.type === "Bot") continue;
    if (["APPROVED", "CHANGES_REQUESTED", "DISMISSED"].includes(r.state)) latest.set(login, r);
  }
  return latest;
}

/**
 * @param {object} input
 * @param {string} input.author          pull request author login
 * @param {string} input.headSha         current head commit of the pull request
 * @param {Array}  input.files           pulls.listFiles entries ({filename, previous_filename, status})
 * @param {number} [input.changedFiles]  pr.changed_files; if larger than files.length the list was truncated
 * @param {Array}  input.reviews         pulls.listReviews entries ({id, user:{login,type}, state, commit_id})
 * @param {string[]} [input.team]
 * @returns {{ok: boolean, required: string[], approved: string[], missing: Array<{login:string, reason:string}>, files: string[], message: string}}
 */
function evaluate({ author, headSha, files, changedFiles, reviews, team = TEAM }) {
  const members = team.map(norm);
  const touched = protectedFiles(files);

  // Fail closed if GitHub could not list every changed file.
  if (typeof changedFiles === "number" && changedFiles > files.length) {
    return {
      ok: false, required: members, approved: [], missing: [], files: touched,
      message: `Could not inspect all changed files (${files.length} of ${changedFiles}); split the pull request.`,
    };
  }
  if (touched.length === 0) {
    return { ok: true, required: [], approved: [], missing: [], files: [], message: "No protected contract files changed." };
  }

  const required = members.filter((m) => m !== norm(author));
  const latest = latestDecisions(reviews, members);
  const approved = [];
  const missing = [];
  for (const login of required) {
    const r = latest.get(login);
    if (!r) missing.push({ login, reason: "has not approved" });
    else if (r.state === "CHANGES_REQUESTED") missing.push({ login, reason: "requested changes" });
    else if (r.state === "DISMISSED") missing.push({ login, reason: "approval was dismissed" });
    else if (r.commit_id !== headSha) missing.push({ login, reason: `approved an older commit (${String(r.commit_id).slice(0, 7)})` });
    else approved.push(login);
  }

  const ok = missing.length === 0;
  const who = members.includes(norm(author)) ? "both other team members" : "all three team members (author is outside the team)";
  const message = ok
    ? `Protected files changed; approved on ${headSha.slice(0, 7)} by ${approved.join(", ")}.`
    : `Protected files changed: needs approval from ${who} on the current commit ${headSha.slice(0, 7)}. Missing: ` +
      missing.map((m) => `${m.login} (${m.reason})`).join(", ") + ".";
  return { ok, required, approved, missing, files: touched, message };
}

// GitHub limits a status description to 140 characters.
function statusFor(result) {
  const text = result.message.length > 140 ? `${result.message.slice(0, 137)}...` : result.message;
  return { state: result.ok ? "success" : "failure", context: STATUS_CONTEXT, description: text };
}

// Which open pull requests to judge. pull_request_target names its PR. For workflow_run (a review changed),
// GitHub lists same-repository PRs on the run; fork PRs are not listed, so open PRs are matched by head commit.
async function pullRequestsToJudge(github, context) {
  const repo = { owner: context.repo.owner, repo: context.repo.repo };
  if (context.eventName === "pull_request_target") return [context.payload.pull_request.number];
  if (context.eventName !== "workflow_run") return [];
  const run = context.payload.workflow_run;
  const listed = (run.pull_requests || []).map((p) => p.number);
  if (listed.length) return listed;
  const open = await github.paginate(github.rest.pulls.list, { ...repo, state: "open", per_page: 100 });
  return open.filter((p) => p.head.sha === run.head_sha).map((p) => p.number);
}

// Evaluates each affected pull request on its CURRENT head and records the result as a commit status there.
// Nothing from the pull request is executed; only GitHub's records of files and reviews are read.
async function main({ github, context, core }) {
  const repo = { owner: context.repo.owner, repo: context.repo.repo };
  const numbers = await pullRequestsToJudge(github, context);
  if (numbers.length === 0) core.info("No open pull request to evaluate.");
  let allOk = true;
  for (const number of numbers) {
    const base = { ...repo, pull_number: number };
    const { data: pr } = await github.rest.pulls.get(base);
    if (pr.state !== "open") continue;
    const files = await github.paginate(github.rest.pulls.listFiles, { ...base, per_page: 100 });
    const reviews = await github.paginate(github.rest.pulls.listReviews, { ...base, per_page: 100 });
    const result = evaluate({ author: pr.user.login, headSha: pr.head.sha, files, changedFiles: pr.changed_files, reviews });
    await github.rest.repos.createCommitStatus({ ...repo, sha: pr.head.sha, ...statusFor(result) });
    core.info(`#${number}: ${result.message}`);
    allOk &&= result.ok;
  }
  return allOk;
}

module.exports = { TEAM, PROTECTED, STATUS_CONTEXT, evaluate, isProtected, protectedFiles, statusFor, pullRequestsToJudge, main };
