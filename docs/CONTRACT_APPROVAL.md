# Contract approval

Anything under `contracts/` is shared by all three people, so a pull request that changes it must be approved
by the whole team. CODEOWNERS cannot express that (it accepts any one listed owner), so the
`contracts-approval` workflow enforces it as a status check called `all-three-approve`.

## The rule

| Pull request author | Approvals needed |
|---|---|
| A team member | Both other team members |
| Anyone else | All three team members |

An approval counts only if:

- it comes from one of the three designated accounts (listed in `.github/scripts/contract-approval.js`);
- it is that person's latest decisive review (a later "changes requested" or a dismissal cancels it;
  plain comments do not);
- it was given on the **current head commit**. Pushing a new commit makes earlier approvals stale.

Bots, unrelated accounts and the author's own review never count.

Protected files are everything under `contracts/` (added, modified, deleted, or renamed into or out of it)
and the two files that enforce this rule. If GitHub cannot list every changed file, the check fails.

Pull requests that touch none of these files pass immediately.

## Branch protection (repo owner, once)

Settings -> Branches -> rule for `main` (private repositories need GitHub Pro or Team):

- Require a pull request before merging, 1 approval, **Dismiss stale pull request approvals when new commits are pushed**
- Require review from Code Owners
- Require status checks: `backend`, `frontend`, `workflow-scripts`, `all-three-approve`
- Require branches to be up to date before merging
- Do not allow bypassing the above settings (include administrators)

## Testing

`node --test .github/scripts/contract-approval.test.js` covers: zero, one and both approvals, unrelated and bot
approvals, self-approval, dismissed approvals, changes requested after approval, stale approvals, an outside
author, renames out of `contracts/`, added and removed files, edits to the enforcement files, and a truncated
file list. These tests prove the decision logic; they do not prove the workflow has run on GitHub. Check the
Actions tab of the first real pull request that touches `contracts/`.

## Remaining risk

- `pull_request_target` runs the base-branch copy of the workflow, so a pull request cannot change the rule
  that judges it on that trigger. GitHub runs `pull_request_review` events with the pull request's own copy of
  the workflow file. Someone with write access could therefore edit the workflow in their own pull request and
  then trigger a review event to post a passing check. Such an edit is itself a protected-file change, and
  CODEOWNERS review is still required, so it cannot merge unnoticed. Fully closing this gap needs organisation
  rulesets with a required workflow pinned to `main`, which a personal repository does not have.
- The rule trusts GitHub's review records. An account that is compromised can still approve.
