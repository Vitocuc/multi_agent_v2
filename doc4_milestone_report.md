# Milestone report
<!-- Doc 4 — filled by the WORKER AGENT after implementing a feature.
     One file per feature. Stored at: reports/F-{milestone}-{seq}_milestone.md
     The validator reads this file against doc3 to produce a pass/fail verdict.
     The system extracts entries from this file into memory.json after verdict.
     Do not summarize or omit — fill every field completely and literally. -->

---

## Identity

```yaml
feature_id:       ""        # must match doc2 feature_id exactly
milestone_id:     ""        # must match doc2 milestone_id exactly
branch:           ""        # git branch name
commit_sha:       ""        # full SHA of the final commit before PR
pr_id:            ""        # GitHub PR number
timestamp:        ""        # ISO 8601 — time worker completed this report
worker_model:     ""        # model + version used for implementation
```

---

## What was implemented

<!-- List every acceptance criterion from doc2 and mark it. Be specific.
     Do not write "done" — describe what was actually built. -->

| Criterion (from doc2) | Status | Notes |
|---|---|---|
| Given … when … then … | implemented \| partial \| skipped | |
| Given … when … then … | implemented \| partial \| skipped | |

**Summary**

<!-- 3–5 sentences. What was built, how it fits the feature description,
     any notable implementation choices made. -->

---

## What was left undone

<!-- List anything from the acceptance criteria or worker instructions that was NOT
     completed. If nothing, write "none". Never leave this blank. -->

| Item | Reason | Risk if unresolved |
|---|---|---|
| | | |

**Deviation reason**

<!-- If any acceptance criterion was not met, explain why here.
     "Not enough time" is not acceptable — describe the technical blocker. -->

---

## Commands run

<!-- Every command executed during implementation, in order. Include exit codes.
     stdout_summary: one line max — no secrets, no PII, no full stack traces. -->

```yaml
commands:
  - cmd:            ""
    exit_code:      0
    stdout_summary: ""

  - cmd:            ""
    exit_code:      0
    stdout_summary: ""
```

<!-- Include at minimum:
     - dependency install (npm install / pip install)
     - lint / type-check
     - unit test run
     - dependency audit (npm audit / pip-audit)
     - build (if applicable) -->

---

## Issues discovered

<!-- Problems encountered during implementation, whether resolved or not.
     These feed directly into shared memory. Be specific. -->

```yaml
issues:
  - issue_id:       F-01-001-ISS-01
    severity:       low | medium | high | critical
    description:    ""
    resolution:     resolved | workaround | unresolved
    resolution_notes: ""
    do_not_retry:   false     # set true if a specific approach must not be repeated
```

---

## Procedures followed

**Security checklist** (from doc1 § Security checklist)

- [ ] No secrets or credentials in source code or logs
- [ ] All inputs validated and sanitized
- [ ] Auth and authorization applied on every protected route
- [ ] Rate limiting in place on public-facing endpoints
- [ ] PII fields handled per data security policy
- [ ] Dependencies audited — no high/critical CVEs unresolved
- [ ] Error messages do not leak internal stack traces to clients
- [ ] Audit log events emitted for relevant actions

```yaml
security_checklist_followed: true | false
# If false, explain which items were not met and why:
security_checklist_notes: ""
```

**Worker instructions followed** (from doc2 § Worker instructions)

- [ ] Read doc1_security_contract.md before writing code
- [ ] Created correct branch name
- [ ] Implemented only what is in this feature block
- [ ] Ran project test suite
- [ ] Filled this milestone report completely
- [ ] Opened PR with correct title format

```yaml
procedures_followed: true | false
procedures_notes:    ""
```

---

## Validator result

<!-- Filled by the SYSTEM after the validator runs — worker does not touch this section. -->

```yaml
validator_result:
  run_at:           ""
  provider:         ""
  model_version:    ""
  overall:          pending | pass | fail
  blocking_passed:  pending | true | false
  human_gate:       pending | approved | rejected
  failures:         []
  escalations:      []
```

---

## Memory extraction
<!-- Filled by the SYSTEM after validator result is final.
     Indicates what was written to memory.json from this report. -->

```yaml
memory_entries_written:
  architecture_decisions: []   # decision_ids added
  failed_approaches:       []  # entry_ids added
  discovered_constraints:  []  # entry_ids added
  open_risks:              []  # risk_ids added
```
