# Git and PR rules

## Commit messages

Every commit must reference the feature ID:

```
[F-01-002] Add user login endpoint
[F-01-002] Add session token validation
[F-01-002] Fix input sanitisation on email field
```

Keep the subject line under 72 characters.
Use the body for "why", not "what" — the diff shows what changed.

## What to commit

Commit only files that belong to this feature.
Do not commit:
- Unrelated refactors spotted while working
- Debug print statements or temporary files
- `.env` files or any file containing real secrets
- Lock files unless you added or changed a dependency
- Editor config files unless the project already tracks them

If you find yourself about to commit something unrelated, stop.
Put it in `issues_discovered` as a note for the next worker instead.

## Commit atomicity

Prefer small, coherent commits over one large commit at the end.
A good commit leaves the repo in a working state.
A bad commit is "WIP" or "misc fixes".

## Before pushing

Run the full command sequence from CLAUDE.md (install, lint, test, audit).
All must pass before `git push`.

If a test was failing before you started and is unrelated to your feature,
document it in `issues_discovered` — do not fix it silently, it belongs to another feature.

## PR checklist before opening

- [ ] Branch name matches `feature/{feature_id}-{slug}` format
- [ ] All acceptance criteria from doc2 are addressed (or documented in doc4 as undone)
- [ ] `reports/{feature_id}_milestone.md` exists and is complete
- [ ] Security checklist in doc4 is fully ticked or exceptions explained
- [ ] No secrets in any committed file
- [ ] All commands run with exit code 0 (or failures explained in doc4)
- [ ] PR title is `[{feature_id}] {feature title}`
- [ ] PR body is the full content of the milestone report

## After opening the PR

Stop. Do not merge. Do not push more commits unless the human reviewer requests changes.
The validator and human gate run next — those are not your responsibility.
