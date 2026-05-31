# Validation contract
<!-- Doc 3 — produced by the CTO orchestrator alongside doc2.
     The validator agent reads THIS file plus the worker's milestone report.
     The validator NEVER reads the implementation code — only test definitions.
     This prevents training-data bias: the validator judges against spec, not impl.
     Each test_suite maps 1-to-1 with a feature block in doc2. -->

---

## Meta

| Field | Value |
|---|---|
| project_id | |
| contract_version | 1.0 |
| created_at | |
| validator_provider | <!-- e.g. different from worker provider, e.g. GPT-4o, Gemini --> |
| validator_model_version | <!-- pin exact version to prevent drift --> |

---

## Validation principles

1. The validator reads test definitions and the milestone report — never the source code.
2. A test passes when the milestone report's `implemented` list and command outputs
   satisfy the test case's `expected` condition.
3. `blocking: true` tests must all pass before a PR can merge.
4. `human_gate_required: true` means a human must review even if all tests pass.
5. Security test failures are always escalated regardless of blocking flag.

---

## Test suites

<!-- One suite per feature. suite_id matches feature_id from doc2. -->

---

### Suite F-01-001 — [Feature name]

```yaml
suite_id:               F-01-001
feature_id:             F-01-001      # ref to doc2
pass_threshold:         100%          # % of blocking tests that must pass to merge
human_gate_required:    false         # true for high-risk or architectural features
```

**Test cases**

```yaml
- test_id:      F-01-001-T01
  type:         unit
  blocking:     true
  description:  >
    [Plain-language description of what is being verified.
     Written before implementation — pure spec, no code.]
  given:        "[system/world state before the action]"
  when:         "[action taken by user or system]"
  expected:     "[observable outcome — what should be true after]"
  verified_via: milestone_report   # validator checks milestone report fields

- test_id:      F-01-001-T02
  type:         integration
  blocking:     true
  description:  >
    [Integration test: two or more components working together]
  given:        ""
  when:         ""
  expected:     ""
  verified_via: milestone_report

- test_id:      F-01-001-T03
  type:         security
  blocking:     true
  description:  >
    All inputs to this feature are validated before processing.
    No secrets appear in logs. Auth is enforced on all protected routes.
  given:        "Feature F-01-001 is implemented"
  when:         "Validator reads security_checklist_followed field in milestone report"
  expected:     "security_checklist_followed: true and all checklist items checked"
  verified_via: milestone_report.security_checklist_followed

- test_id:      F-01-001-T04
  type:         regression
  blocking:     false
  description:  >
    [Check that this feature does not break any previously passing features.
     Add specific regressions discovered during earlier milestones here.]
  given:        ""
  when:         ""
  expected:     ""
  verified_via: milestone_report.commands_run
```

---

### Suite F-01-002 — [Feature name]

<!-- Copy suite block above and fill in -->

---

## Cross-feature security tests
<!-- These run after every milestone, regardless of which feature was implemented. -->

```yaml
- test_id:      SEC-GLOBAL-01
  type:         security
  blocking:     true
  description:  No credentials, tokens, or PII appear in any logged command output.
  verified_via: milestone_report.commands_run[*].stdout_summary

- test_id:      SEC-GLOBAL-02
  type:         security
  blocking:     true
  description:  The security checklist in doc1 was followed for this feature.
  verified_via: milestone_report.security_checklist_followed

- test_id:      SEC-GLOBAL-03
  type:         security
  blocking:     true
  description:  No high or critical CVEs introduced by new dependencies.
  verified_via: milestone_report.commands_run — look for audit command and exit code
```

---

## Validator output format
<!-- The validator must produce a result in this exact format after each run.
     This output is read by the system to update doc4 and shared memory. -->

```yaml
validator_run:
  suite_id:         ""
  run_at:           ""           # ISO 8601
  provider:         ""
  model_version:    ""
  overall:          pass | fail
  blocking_passed:  true | false
  human_gate:       pending | approved | rejected

  results:
    - test_id:      ""
      status:       pass | fail | skip
      notes:        ""           # brief reason if fail or skip

  failures:         []           # list of test_ids that failed
  escalations:      []           # security failures always listed here separately
```

---

## Amendments

| Version | Date | Changed by | Summary |
|---|---|---|---|
| 1.0 | | CTO orchestrator | Initial |
