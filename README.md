# Orchestrator system — overview

A three-phase AI pipeline for building software projects. Planning is slow and strategic. Implementation is parallel and code-focused. Validation is independent and spec-driven.

---

## Files in this system

```
doc0_project_brief.md        Written by: USER
doc1_security_contract.md    Written by: CTO orchestrator
doc2_features_contract.md    Written by: CTO orchestrator
doc3_validation_contract.md  Written by: CTO orchestrator
doc4_milestone_report.md     Written by: WORKER agent (one copy per feature)
memory.json                  Written by: SYSTEM (extracted from milestone reports)
```

---

## Three principles

| Phase | Role | Characteristic |
|---|---|---|
| Planning | CTO orchestrator | Slow, careful reasoning. Produces contracts. |
| Implementation | Worker agents | Code fluency. One worker per feature. |
| Validation | Validator agents | Strict spec-following. Different provider than workers. |

---

## Workflow

```
1. USER fills doc0_project_brief.md and passes it to the CTO orchestrator.

2. CTO ↔ USER clarification loop
   - CTO reads doc0 and asks clarifying questions.
   - USER answers. CTO appends each round to clarification_log in doc0.
   - Repeat until shared_plan_approved = true.

3. CTO produces three contracts from the approved plan:
   - doc1_security_contract.md
   - doc2_features_contract.md
   - doc3_validation_contract.md
   All three are written before any implementation begins.

4. USER reviews contracts and approves (or requests amendments).

5. For each feature in doc2 (in DAG order):
   a. WORKER reads:  their feature block from doc2 + doc1 in full + memory.json (filtered)
   b. WORKER creates branch: feature/F-XX-XXX-slug
   c. WORKER implements the feature.
   d. WORKER fills a copy of doc4_milestone_report.md for this feature_id.
   e. WORKER opens a PR. Does not merge.

6. Human checkpoint
   - Human reviews PR diff.
   - If approved: validator runs.
   - If rejected: worker revises on same branch.

7. VALIDATOR reads:
   - The feature's test suite from doc3
   - The worker's milestone report (doc4)
   - NEVER reads source code — validates against spec only.
   - Produces validator_result block (written into doc4).

8. SYSTEM (after validator passes):
   - Extracts memory entries from doc4 → appends to memory.json.
   - Updates feature_status tracker in doc2.
   - Merges PR if human_gate = approved and overall = pass.

9. Repeat from step 5 for next feature.
   CTO receives filtered memory.json as context for next planning round.
```

---

## DAG execution rules

A feature may only start when:
- All `depends_on` feature_ids have `milestone_status: passed` in doc2's status tracker.
- `parallel_safe: true` features with no unmet dependencies can run concurrently.

---

## GitHub mapping

| System concept | GitHub artifact |
|---|---|
| Feature | Issue |
| Feature branch | Branch `feature/F-XX-XXX-slug` |
| Milestone | GitHub Milestone |
| Human checkpoint | Pull Request review |
| Validator pass | PR check / status |
| Merge | PR merge to main |
| Memory + contracts | Committed files in repo root |

---

## Shared memory rules

- `memory.json` is **append-only**. No entry is ever deleted.
- Entries are written by the system, never by workers or the CTO directly.
- A newer architecture decision can supersede an older one via the `supersedes` field — the old entry remains in the log.
- The CTO receives only a **filtered subset** of memory.json, not the full file:
  - Architecture decisions relevant to the current feature's dependency chain
  - ALL failed approaches (workers must always know what not to try)
  - Discovered constraints affecting the current feature
  - Open risks at high/critical severity or blocking the current feature

---

## What the validator never does

- Read source code
- Read git diffs
- Read dependency lock files
- Make judgments about code quality or style

The validator reads only: the test definitions in doc3 and the milestone report in doc4. This is intentional — it prevents the validator from being influenced by the implementation and forces it to judge against the spec alone.

---

## Amending a contract after approval

Contracts are versioned. If a constraint needs to change mid-project:

1. Amend the relevant contract and bump `contract_version`.
2. Add an entry to the Amendments table at the bottom of the file.
3. Update any affected feature blocks in doc2 (add note in `worker_instructions`).
4. Update affected test suites in doc3 if acceptance criteria changed.
5. Log a discovered_constraint or architecture_decision in memory.json explaining the change.
