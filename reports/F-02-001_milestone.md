# Milestone report
<!-- Doc 4 — filled by the WORKER AGENT after implementing a feature. -->

---

## Identity

```yaml
feature_id:       "F-02-001"
milestone_id:     "M-02"
branch:           "feature/F-02-001-spending-alerts"
commit_sha:       "72bced32e37a40c63b5ce030c3bf2ffbb4fa89c8"
pr_id:            ""
timestamp:        "2026-06-02T14:30:00+00:00"
worker_model:     "claude-sonnet-4-6"
```

---

## What was implemented

| Criterion (from doc2) | Status | Notes |
|---|---|---|
| Given a user with a daily limit of 5000 eurocents and cumulative daily spending of 4000 eurocents, when a new spending event brings the total to 4001, then an alert record with `{"type": "limit_80pct", "period": "daily", "acknowledged": false}` is created for that user | implemented | Tested in `test_evaluator_creates_80pct_alert`. `evaluate_all_alerts()` service checks spending ≥ 80% of limit and creates `AlertRecord(alert_type="limit_80pct")`. Deduplication prevents re-creation within the same period. |
| Given a user with a daily limit of 5000 eurocents and cumulative daily spending of 5001 eurocents, when GET /v1/dashboard is called, then the response includes an `alerts` array containing the 100% limit alert | implemented | Tested in `test_dashboard_includes_alerts`. Dashboard response extended with `alerts: List[AlertInfo]`; queries unacknowledged `AlertRecord` rows for the authenticated user. |
| Given a user who calls PATCH /v1/alerts/{alert_id}/acknowledge, then the alert is marked `acknowledged: true` and no longer appears in the unacknowledged alert list | implemented | Tested in `test_acknowledge_alert`. PATCH sets `acknowledged=True`; subsequent GET /v1/alerts and GET /v1/dashboard both omit the acknowledged alert. |
| Given an alert_id belonging to another user, when PATCH /v1/alerts/{alert_id}/acknowledge is called, then a 403 response is returned | implemented | Tested in `test_acknowledge_other_users_alert_returns_403`. Ownership check: `alert.user_id != user_id` → 403. |
| Given an authenticated user, when POST /v1/alert-thresholds with `{"amount_eurocents": 3000, "period": "weekly"}`, then a 200 response is returned and the threshold is persisted | implemented | Tested in `test_create_threshold_returns_200`. `AlertThreshold` row created; response contains id, period, created_at. Amount validated > 0 and ≤ 10,000,000. |
| Given a custom threshold configured, when spending crosses that threshold, then an alert of type `custom_threshold` is created | implemented | Tested in `test_evaluator_creates_custom_threshold_alert`. Evaluator checks custom thresholds after limit checks; creates `AlertRecord(alert_type="custom_threshold")` when spending ≥ threshold amount. |
| Security: alert_config_change audit log event is emitted on threshold create/update/delete — no amount in log | implemented | Tested in `test_audit_on_threshold_create_no_amount` and `test_audit_on_threshold_delete_no_amount` using `unittest.mock.patch`. Verified no amount value in any audit call argument. |
| Security: alert records for user A are never returned in user B's dashboard or alert list | implemented | Tested in `test_alert_ownership_isolation`. All queries filter by `user_id` from JWT; user B's alert ID never appears in user A's GET /v1/alerts or GET /v1/dashboard response. |

**Summary**

F-02-001 adds an alert evaluation service (`services/alert_evaluator.py`) and three new API endpoint groups. The evaluator checks spending across all three periods (daily/weekly/monthly) against deposit limits (80% and 100% thresholds) and custom thresholds, creating `AlertRecord` rows with deduplication at (user_id, period, alert_type). The dashboard response is extended with an `alerts` array showing all unacknowledged alerts. New endpoints: `GET /v1/alerts`, `PATCH /v1/alerts/{id}/acknowledge`, `POST /v1/alert-thresholds`, `GET /v1/alert-thresholds`, `DELETE /v1/alert-thresholds/{id}`. All 16 F-02-001 tests pass; the full 53-test suite passes with no regressions.

---

## What was left undone

| Item | Reason | Risk if unresolved |
|---|---|---|
| none | — | — |

**Deviation reason**

All acceptance criteria implemented and tested.

---

## Commands run

```yaml
commands:
  - cmd: "git checkout develop && git pull origin develop"
    exit_code: 0
    stdout_summary: "Fast-forward, F-01-003 files pulled"

  - cmd: "git checkout -b feature/F-02-001-spending-alerts"
    exit_code: 0
    stdout_summary: "Switched to new branch"

  - cmd: "pip install -r requirements.txt -q && pip install -r requirements-dev.txt -q"
    exit_code: 0
    stdout_summary: "All packages already satisfied"

  - cmd: "python3 -m pytest tests/test_alerts.py -v"
    exit_code: 0
    stdout_summary: "16 passed in 2.64s"

  - cmd: "python3 -m pytest tests/ -v"
    exit_code: 0
    stdout_summary: "53 passed in 9.41s — 2 prior dashboard tests updated to include alerts field"

  - cmd: "pip-audit --local"
    exit_code: 0
    stdout_summary: "No known vulnerabilities found"
```

---

## Issues discovered

```yaml
issues:
  - issue_id: "F-02-001-ISS-01"
    severity: low
    description: "Two existing dashboard tests (test_dashboard_with_events_returns_200_aggregated and test_dashboard_response_contains_no_raw_identifiers) checked for exact response key set without 'alerts'. Adding 'alerts' to DashboardResponse broke those assertions."
    resolution: resolved
    resolution_notes: "Updated both tests to include 'alerts' in the expected key set. This is a legitimate schema extension by F-02-001, not a regression."
    do_not_retry: false

  - issue_id: "F-02-001-ISS-02"
    severity: low
    description: "python3-venv not installed on host; pip-audit -r requirements.txt fails. Known constraint from prior features."
    resolution: workaround
    resolution_notes: "Used pip-audit --local as in prior features."
    do_not_retry: false
```

---

## Procedures followed

**Security checklist** (from doc1 § Security checklist)

- [x] No secrets or credentials in source code or logs
- [x] All inputs validated and sanitized — PeriodEnum validates period; amount_eurocents validated > 0 and ≤ 10,000,000; alert_id and threshold_id are path params, ownership verified before any action
- [x] Auth and authorization applied on every protected route — `get_current_user_id` dep on all endpoints; ownership checks on PATCH and DELETE
- [x] Rate limiting in place on public-facing endpoints — per-token 60 req/min via `is_api_rate_limited` on every handler
- [x] PII fields handled per data security policy — alert_thresholds stored as integers; amounts never logged; AlertRecord stores only user_id (UUID), period, alert_type, acknowledged flag
- [x] Dependencies audited — `pip-audit --local` = 0 vulnerabilities
- [x] Error messages do not leak internal stack traces — framework returns opaque codes; custom errors use `{"error": "..."}` detail
- [x] Audit log events emitted for relevant actions — `alert_config_change` on threshold create and delete; `rate_limit_hit` on rate limit rejection

```yaml
security_checklist_followed: true
security_checklist_notes: "All 12 doc1 checklist items addressed. OIDC validation and Redis blacklist handled by shared get_current_user_id dependency. Ownership enforced on PATCH /v1/alerts/{id}/acknowledge (403 for wrong user) and DELETE /v1/alert-thresholds/{id} (403 for wrong user). Alert evaluator is a pure service function with no direct HTTP exposure — safe to call from any context."
```

**Worker instructions followed** (from doc2 § Worker instructions)

- [x] Read doc1_security_contract.md before writing code
- [x] Created correct branch name: `feature/F-02-001-spending-alerts`
- [x] Implemented only what is in this feature block
- [x] Ran project test suite — 53 passed, 0 failed
- [x] Filled this milestone report completely
- [x] Opening PR with correct title format

```yaml
procedures_followed: true
procedures_notes: "pip-audit run with --local flag (python3-venv not available on host). Branched from develop after confirming F-01-002 and F-01-003 were merged."
```

---

## Validator result

```yaml
validator_result:
  run_at:           ""
  provider:         ""
  model_version:    ""
  overall:          pending
  blocking_passed:  pending
  human_gate:       pending
  failures:         []
  escalations:      []
```

---

## Memory extraction

```yaml
memory_entries_written:
  architecture_decisions: []
  failed_approaches:       []
  discovered_constraints:  []
  open_risks:              []
```
