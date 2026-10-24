// Decides whether a pull request has the approvals that changes to shared contracts need.
//
// Kept free of GitHub API calls so it can be unit tested (contract-approval.test.js).
// The workflow runs this file from the BASE branch, never from the pull request.

const TEAM = ["atuldhull", "gundatharuntej2006-hue", "ritikakulkarni06-art"];

// Changing these needs the whole team. The enforcement files themselves are included,
// so the rule cannot be weakened by the same pull request it is judging.
const PROTECTED = [
  "contracts/",
  ".github/workflows/contracts-approval.yml",
  ".github/scripts/contract-approval.js",
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

module.exports = { TEAM, PROTECTED, evaluate, isProtected, protectedFiles };
