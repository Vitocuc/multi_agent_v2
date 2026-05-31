# Features contract
<!-- Doc 2 — produced by the CTO orchestrator after shared_plan_approved = true.
     Each feature block is a unit of work for one worker agent.
     Workers read their assigned feature block plus doc1_security_contract.md.
     The depends_on field defines the execution DAG — a feature may only start
     when all its dependencies have milestone_status: passed. -->

---

## Meta

| Field | Value |
|---|---|
| project_id | |
| contract_version | 1.0 |
| created_at | |
| total_features | |
| total_milestones | |

---

## Milestone map

<!-- High-level grouping of features into milestones for GitHub Project tracking.
     A milestone is complete when all its features have milestone_status: passed. -->

| Milestone ID | Name | Features | Goal |
|---|---|---|---|
| M-01 | | | |
| M-02 | | | |

---

## Feature blocks

<!-- One block per feature. Copy the template below for each new feature.
     feature_id format: F-{milestone}-{sequence}, e.g. F-01-001 -->

---

### F-01-001 — [Feature name]

```yaml
feature_id:         F-01-001
title:              ""
milestone_id:       M-01
priority:           critical | high | medium | low
complexity:         S | M | L | XL
depends_on:         []        # list of feature_ids that must pass first
parallel_safe:      true      # can run in parallel with other ready features
```

**Description**

<!-- 2–5 sentences. What this feature does, from the user's perspective and the
     system's perspective. Be specific enough that a worker can start without asking. -->

**Security constraints**
<!-- References to doc1_security_contract.md fields this feature must satisfy. -->

- Auth: `doc1 § Authentication — mechanism, token_expiry`
- Input: `doc1 § Input validation — strategy`
- Logging: `doc1 § Audit logging — log_events: [auth_success, auth_failure]`

<!-- Add or remove lines as relevant to this specific feature. -->

**Acceptance criteria**
<!-- Concrete, binary, testable. Each line becomes a test case in doc3. -->

- [ ] Given [condition], when [action], then [outcome]
- [ ] Given [condition], when [action], then [outcome]
- [ ] Security: all inputs validated before processing
- [ ] Security: no secrets appear in logs or error responses

**Worker instructions**

```
1. Read doc1_security_contract.md in full before writing any code.
2. Create branch: git checkout -b feature/F-01-001-[slug]
3. Implement only what is described in this block — no scope creep.
4. Run the project test suite after implementation.
5. Fill in doc4_milestone_report.md for this feature_id.
6. Open a PR against main. Title: "[F-01-001] Feature name".
7. Do not merge — human gate required before validator runs.
```

**Done definition**
<!-- The worker's branch is merged only when ALL of these are true. -->

- [ ] All acceptance criteria pass in validator run
- [ ] Security checklist in doc1 fully checked
- [ ] Milestone report filed with milestone_status: passed
- [ ] PR approved by human reviewer

**GitHub**

```yaml
branch_name:        feature/F-01-001-slug
github_issue_id:    ""        # filled when issue is created
pr_id:              ""        # filled when PR is opened
```

---

### F-01-002 — [Feature name]

<!-- Copy block above and fill in -->

---

## Feature status tracker
<!-- Updated by the system after each milestone report is accepted. Never edited manually. -->

| feature_id | title | milestone | status | branch | validator_result |
|---|---|---|---|---|---|
| F-01-001 | | M-01 | pending | | |
| F-01-002 | | M-01 | pending | | |

<!-- status values: pending | in_progress | blocked | passed | failed | skipped -->

---

## Amendments

| Version | Date | Changed by | Summary |
|---|---|---|---|
| 1.0 | | CTO orchestrator | Initial |
