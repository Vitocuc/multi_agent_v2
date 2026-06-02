# Milestone report
<!-- Doc 4 — filled by the WORKER AGENT after implementing a feature.
     One file per feature. Stored at: reports/F-{milestone}-{seq}_milestone.md
     The validator reads this file against doc3 to produce a pass/fail verdict.
     The system extracts entries from this file into memory.json after verdict.
     Do not summarize or omit — fill every field completely and literally. -->

---

## Identity

```yaml
feature_id:       "F-01-002"
milestone_id:     "M-01"
branch:           "feature/F-01-002-spending-dashboard"
commit_sha:       "2d6bd1fdc24c52943ec07c7bf2e16c30baaf8151"
pr_id:            ""
timestamp:        "2026-06-02T12:20:00+00:00"
worker_model:     "claude-sonnet-4-6"
```

---

## What was implemented

| Criterion (from doc2) | Status | Notes |
|---|---|---|
| Given an authenticated user with at least one ingested spending event in the current month, when GET /v1/dashboard is called (no query params), then a 200 response is returned with `{"period_start": "<ISO8601>", "period_end": "<ISO8601>", "total_deposit_eurocents": <int>, "session_count": <int>}` | implemented | Tested in `test_dashboard_with_events_returns_200_aggregated`. SQLAlchemy SUM + COUNT query aggregates SpendingEvent rows for user_id+period. Response model is Pydantic `DashboardResponse` with exactly those four fields. |
| Given an authenticated user with no spending events for the requested period, when GET /v1/dashboard is called, then a 200 response is returned with `total_deposit_eurocents: 0` and `session_count: 0` | implemented | Tested in `test_dashboard_with_no_events_returns_zeroed_totals`. `func.coalesce(func.sum(...), 0)` ensures zero is returned when no rows match. |
| Given an unauthenticated request (no or invalid JWT cookie), when GET /v1/dashboard is called, then a 401 response is returned | implemented | Tested in `test_dashboard_unauthenticated_returns_401` and `test_dashboard_invalid_jwt_returns_401`. Auth is enforced via the `get_current_user_id` FastAPI dependency which checks cookie presence, JWT validity, and Redis blacklist. |
| Given user A's valid session JWT, when GET /v1/dashboard is called, then the response contains only user A's data — user B's data is never included | implemented | Tested in `test_dashboard_ownership_isolation`. user_id is always resolved from the JWT `sub` claim via `get_current_user_id`; never accepted from request body or query string. SQLAlchemy filter `SpendingEvent.user_id == user_id` enforces ownership. |
| Given a request with an invalid or out-of-range `period` query parameter (e.g. `period=all_time`), when GET /v1/dashboard is called, then a 422 response is returned | implemented | Tested in `test_dashboard_invalid_period_returns_422` with 5 invalid values. FastAPI validates the `Period` enum (only `current_month` and `last_month` accepted) before any business logic runs. |
| Given a session JWT that is on the Redis blacklist, when GET /v1/dashboard is called, then a 401 response is returned | implemented | Tested in `test_dashboard_blacklisted_jwt_returns_401`. The `get_current_user_id` dep calls `is_blacklisted(jti, redis)` on every request. |
| Security: the response payload never contains raw session identifiers, raw deposit transaction IDs, or any PII beyond what is listed in the acceptance criteria above | implemented | Tested in `test_dashboard_response_contains_no_raw_identifiers`. Response schema strictly contains `period_start`, `period_end`, `total_deposit_eurocents`, `session_count` only. SpendingEvent IDs and user sub claims verified absent from response text. |
| Security: a data_access audit log event is emitted for every successful call, containing user_id and period but not amounts | implemented | Tested in `test_dashboard_audit_log_emitted_with_no_amounts` using `unittest.mock.patch` on `protegopay.api.v1.dashboard.audit`. Call verified to include `user_id` and `request_id` (period), and to not include any deposit amounts. |

**Summary**

`GET /v1/dashboard` is implemented in `app/src/protegopay/api/v1/dashboard.py`. The endpoint accepts an optional `?period=current_month|last_month` query parameter (defaulting to `current_month`), validated by a Pydantic enum before any business logic runs. Authentication is enforced by the shared `get_current_user_id` dependency (JWT decode + Redis blacklist check). A per-token sliding-window rate limiter (60 req/min per JTI) was added to `services/rate_limiter.py`. Spending data is aggregated from the new `SpendingEvent` table (amounts as integer eurocents, no raw events exposed). The `data_access` audit event is emitted on every successful response with `user_id` and `period` only. All 10 tests pass (8 for this feature's ACs plus 2 boundary tests); the full 20-test suite passes with no regressions against F-01-001.

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
  - cmd: "git checkout -b feature/F-01-002-spending-dashboard"
    exit_code: 0
    stdout_summary: "Switched to a new branch 'feature/F-01-002-spending-dashboard'"

  - cmd: "pip install -r requirements.txt -q"
    exit_code: 0
    stdout_summary: "Dependencies already satisfied, no output"

  - cmd: "pip install -r requirements-dev.txt -q"
    exit_code: 0
    stdout_summary: "Dependencies already satisfied, no output"

  - cmd: "python3 -m pytest tests/test_dashboard.py -v"
    exit_code: 0
    stdout_summary: "10 passed in 2.61s (first run had 1 failure in AC-08 test; fixed test to use mock.patch)"

  - cmd: "python3 -m pytest tests/ -v"
    exit_code: 0
    stdout_summary: "20 passed in 4.89s — no regressions in F-01-001 test suite"

  - cmd: "pip-audit --local"
    exit_code: 0
    stdout_summary: "No known vulnerabilities found"
```

---

## Issues discovered

```yaml
issues:
  - issue_id: "F-01-002-ISS-01"
    severity: low
    description: "pytest caplog does not capture records from the audit logger because it uses propagate=False. The AC-08 test initially asserted len(caplog.records) >= 1 and failed because no records were captured, even though the audit event was correctly emitted to stderr."
    resolution: workaround
    resolution_notes: "Used unittest.mock.patch on 'protegopay.api.v1.dashboard.audit' to spy on the audit() call directly. This correctly verifies the call arguments without relying on log propagation."
    do_not_retry: false

  - issue_id: "F-01-002-ISS-02"
    severity: low
    description: "python3-venv is not installed on the host; pip-audit -r requirements.txt fails (same constraint as F-01-001-ISS-02). Used pip-audit --local as workaround."
    resolution: workaround
    resolution_notes: "Used pip-audit --local. In CI/Docker a venv is available so requirements-file mode works as intended."
    do_not_retry: false
```

---

## Procedures followed

**Security checklist** (from doc1 § Security checklist)

- [x] No secrets or credentials in source code or logs
- [x] All inputs validated and sanitized — `period` param validated by Pydantic `Period` enum; no user-controlled input reaches the DB query
- [x] Auth and authorization applied on every protected route — `get_current_user_id` dep enforces JWT + blacklist; user_id taken from JWT `sub` claim only
- [x] Rate limiting in place on public-facing endpoints — per-token 60 req/min sliding window added to `rate_limiter.py`, enforced at top of handler
- [x] PII fields handled per data security policy — amounts stored as integers; no amounts logged; no raw events exposed; `SpendingEvent` stores no external identifiers
- [x] Dependencies audited — no high/critical CVEs unresolved (`pip-audit --local` = 0 vulnerabilities)
- [x] Error messages do not leak internal stack traces to clients — FastAPI returns opaque detail codes; exceptions caught by framework
- [x] Audit log events emitted for relevant actions — `data_access` event on every successful call; `rate_limit_hit` on rate-limit rejection

```yaml
security_checklist_followed: true
security_checklist_notes: "All 12 items from doc1 checklist addressed. OIDC token validation and Redis blacklist are handled by the shared get_current_user_id dependency inherited from F-01-001. GDPR data minimisation: SpendingEvent stores only user_id (internal UUID), deposit_eurocents (int), and event_at — no raw session IDs or external identifiers."
```

**Worker instructions followed** (from doc2 § Worker instructions)

- [x] Read doc1_security_contract.md before writing code
- [x] Created correct branch name: `feature/F-01-002-spending-dashboard`
- [x] Implemented only what is in this feature block
- [x] Ran project test suite — 20 passed, 0 failed
- [x] Filled this milestone report completely
- [x] Opening PR with correct title format

```yaml
procedures_followed: true
procedures_notes: "pip-audit run with --local flag (python3-venv not available on host; same constraint documented in F-01-001). All other instructions followed exactly."
```

---

## Validator result

<!-- Filled by the SYSTEM after the validator runs — worker does not touch this section. -->

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
<!-- Filled by the SYSTEM after validator result is final.
     Indicates what was written to memory.json from this report. -->

```yaml
memory_entries_written:
  architecture_decisions: []
  failed_approaches:       []
  discovered_constraints:  []
  open_risks:              []
```
