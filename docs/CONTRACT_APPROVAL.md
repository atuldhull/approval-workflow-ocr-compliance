# Contract approval

Anything under `contracts/` is shared by all three people, so a pull request that changes it must be approved
by the whole team. CODEOWNERS cannot express that (it accepts any one listed owner), so the `contracts-approval`
workflow enforces it and posts the commit status **`contracts-approval/designated-approvals`** on the PR head.

## The rule

| Pull request author | Approvals needed |
|---|---|
| A team member | Both other team members |
| Anyone else | All three team members |

An approval counts only if it comes from one of the three designated accounts (listed in
`.github/scripts/contract-approval.js`), is that person's latest decisive review (a later "changes requested" or
a dismissal cancels it; comments do not), and was given on the **current head commit**. Bots, unrelated accounts
and the author never count.

Protected paths: `contracts/`, every file under `.github/workflows/` and `.github/scripts/`, and
`.github/CODEOWNERS` - added, modified, deleted, or renamed in or out. Any workflow holding a write token can post
statuses, so changes to any workflow need the whole team. If GitHub cannot list every changed file, the check fails.

## How it runs (and why)

| Workflow | Trigger | Which copy GitHub runs | Trusted? | Token |
|---|---|---|---|---|
| `contracts-approval.yml` | `pull_request_target` (opened, synchronize, ...) | default branch | yes | contents, pull-requests read; statuses write |
| `contracts-approval.yml` | `workflow_run` of the review signal | default branch | yes | same |
| `contracts-approval-review-signal.yml` | `pull_request_review` | **the PR's merge ref** | no | none |

Source: GitHub docs, "Events that trigger workflows" - `pull_request_target` and `workflow_run` use the default
branch (`workflow_run` only fires if the triggered workflow exists on the default branch); `pull_request_review`
runs on `refs/pull/N/merge`.

The authority never checks out PR code and never uses data from the signal run: it re-reads the PR, its files and
its reviews from the GitHub API, evaluates the current head, and posts the status on that head. A new push
re-runs it (`synchronize`), so earlier approvals are stale by construction.

`statuses: write` is the only write scope. It is needed because a `workflow_run` job's own check run is attached to
the default branch commit, not to the PR, so the result has to be posted explicitly.

## Branch protection (repo owner, once)

Settings -> Branches -> rule for `main` (private repositories need GitHub Pro or Team):

- Require a pull request before merging, 1 approval, dismiss stale approvals, require approval of the most recent push
- Require review from Code Owners
- Require status checks: `backend`, `frontend`, `workflow-scripts`, and **`contracts-approval/designated-approvals`**
  (remove the old `all-three-approve` if it is listed). The status first appears after the first PR run.
- Require branches to be up to date before merging
- Do not allow bypassing the above settings (include administrators)

## What is and is not guaranteed

| Attack | Outcome |
|---|---|
| PR edits the authority workflow or script to always pass | No effect: the default-branch copy judges the PR, and the edit itself needs all approvals |
| PR renames the workflow, job or status context | No effect: branch protection requires the status context the default-branch script posts |
| Outside contributor (fork) | Fork tokens are read-only, so a fork cannot post statuses; needs all three approvals |
| Approval on an old commit, dismissed, or overridden by "changes requested" | Not counted |
| PR deletes the review-signal workflow | A protected change, so it needs everyone; afterwards, a review **withdrawn** after full approval would not re-trigger the check |
| **A teammate with write access** pushes any branch with a workflow that posts a fake `success` status on a PR head | **Not prevented.** Every `GITHUB_TOKEN` posts as the same "GitHub Actions" source, so branch protection cannot tell them apart. Code-owner review still has to approve the PR, so this needs a teammate acting in bad faith. |

Closing the last row needs a status source a workflow cannot impersonate: a dedicated GitHub App whose private
key is stored as an **environment secret** limited to `main` (environment branch policies on a private repo need
Pro), with branch protection's required check pinned to that App as the expected source. That is the upgrade path;
it is not implemented, because it adds an App and a key to manage.

## Testing

`node --test .github/scripts/contract-approval.test.js` (27 tests): zero, one and both approvals, unrelated and bot
approvals, self-approval, dismissal, changes requested, stale approvals and new commits, outside author, renames
out of `contracts/`, added and removed files, edits to workflows, scripts and CODEOWNERS, a PR weakening the
decision logic, truncated file lists, the status payload, the GitHub API layer with a fake client (current head,
same-repo and fork PRs after a review, closed PRs, other events), and static checks that the authority workflow
uses only default-branch triggers, never checks out PR code, and holds exactly the intended permissions.

These prove the logic and configuration locally. **They do not prove GitHub runs it as described**; confirm on the
first real pull request that touches `contracts/` that the status appears and reacts to a review.
