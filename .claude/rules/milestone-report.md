# Milestone report rules

The milestone report is the single most important output of your work.
The validator reads it. The memory system extracts from it. The human reviewer relies on it.
A vague or incomplete report is a failed feature regardless of code quality.

## File location

```
reports/{feature_id}_milestone.md
```

Copy from `doc4_milestone_report.md` as the template. Fill every field.

## Field-by-field guidance

### implemented table

List every acceptance criterion from your doc2 feature block, word for word.
For each, write the status and a specific note — not just "done".

```
| Given a valid email and password, when POST /login is called,
  then a JWT is returned with 15m expiry | implemented | JWT returned,
  expiry set via AUTH_TOKEN_EXPIRY env var, tested in auth.test.js:42 |
```

### left_undone

If you completed everything: write `none`.
If something is undone, write the criterion exactly as it appears in doc2,
the reason it's undone, and the risk if it stays undone.

Never leave this field blank. A blank field reads as "I didn't check."

### commands_run

Every command. Not a summary — every command, in the order you ran it.
The stdout_summary is one line maximum. No stack traces. No secrets.

```yaml
- cmd: "npm install"
  exit_code: 0
  stdout_summary: "added 142 packages, 0 vulnerabilities"

- cmd: "npm run lint"
  exit_code: 0
  stdout_summary: "no warnings or errors"

- cmd: "npm test"
  exit_code: 0
  stdout_summary: "23 passed, 0 failed, coverage 84%"

- cmd: "npm audit"
  exit_code: 0
  stdout_summary: "found 0 vulnerabilities"
```

### issues_discovered

Log everything unexpected — even things you resolved.
The memory system uses this to build the `failed_approaches` and `discovered_constraints`
sections. If you don't log it, the next worker hits the same wall.

```yaml
- issue_id: "F-01-002-ISS-01"
  severity: medium
  description: "passport-local conflicts with express-session v2 — session is never persisted"
  resolution: workaround
  resolution_notes: "downgraded express-session to v1.17.3, added to package.json"
  do_not_retry: false
```

### security_checklist_followed

Go through the checklist in doc1 item by item.
Tick each one. If you cannot tick an item, set `security_checklist_followed: false`
and explain specifically which item failed and why in `security_checklist_notes`.

Setting this to `true` when items are unticked is the one thing that will cause
a security escalation in the validator — it is checked explicitly.

## Tone

Write the report as if you are handing the project to someone who has never seen it.
They should be able to read your report and understand exactly what was built,
what was not built, what problems exist, and what to watch out for.
