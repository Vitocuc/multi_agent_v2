# Milestone report
<!-- Doc 4 — filled by the WORKER AGENT after implementing a feature. -->

---

## Identity

```yaml
feature_id:       "F-01-003"
milestone_id:     "M-01"
branch:           "feature/F-01-003-voluntary-limits"
commit_sha:       "39e0cd32706b28dfa9895396939a9429410837c7"
pr_id:            ""
timestamp:        "2026-06-02T13:00:00+00:00"
worker_model:     "claude-sonnet-4-6"
```

---

## What was implemented

| Criterion (from doc2) | Status | Notes |
|---|---|---|
| Given an authenticated user, when PUT /v1/limits/daily with body `{"amount_eurocents": 5000}`, then a 200 response is returned with the persisted limit record including `{"period": "daily", "amount_eurocents": 5000, "created_at": "<ISO8601>", "updated_at": "<ISO8601>"}` | implemented | Tested in `test_put_limit_returns_200_with_all_fields`. Response model `LimitResponse` returns exactly those four fields; Pydantic validates the response shape. |
| Given an authenticated user with an existing daily limit, when PUT /v1/limits/daily with a new amount, then the existing limit is updated (upsert) and a 200 response is returned | implemented | Tested in `test_put_limit_upserts_existing`. SQLAlchemy query checks for existing row; if found, updates `amount_eurocents` and `updated_at` in-place. `created_at` is preserved. |
| Given `amount_eurocents` of 0 or negative, when PUT /v1/limits/{period} is called, then a 422 response is returned with `{"error": "amount must be a positive integer"}` — no internal detail | implemented | Tested in `test_put_zero_amount_returns_422` with values 0, -1, -9999. Manual validation raises `HTTPException(422, detail={"error": "amount must be a positive integer"})` before any DB access. |
| Given `amount_eurocents` greater than 10_000_000, when PUT /v1/limits/{period} is called, then a 422 response is returned | implemented | Tested in `test_put_amount_exceeds_max_returns_422` with 10_000_001. Same `_validate_amount` helper enforces the ceiling. |
| Given an invalid period value (e.g. `quarterly`), when PUT /v1/limits/{period} is called, then a 422 response is returned | implemented | Tested in `test_put_invalid_period_returns_422` with 5 invalid values including `quarterly`, `yearly`, `hour`, `DAILY`. FastAPI validates the `PeriodEnum` path parameter before the handler runs. Also tested for DELETE in `test_delete_invalid_period_returns_422`. |
| Given an authenticated user with limits set, when GET /v1/limits is called, then a 200 response is returned with an array of all active limits for that user | implemented | Tested in `test_get_limits_returns_all_active` (3 limits for all periods) and `test_get_limits_empty_returns_empty_array` (empty array when no limits set). |
| Given an authenticated user with a daily limit set, when DELETE /v1/limits/daily is called, then a 204 response is returned and the limit no longer appears in GET /v1/limits | implemented | Tested in `test_delete_limit_returns_204_and_removes`. DELETE endpoint returns 204; subsequent GET confirms absence. |
| Given an unauthenticated request, when any /v1/limits endpoint is called, then a 401 response is returned | implemented | Tested in `test_unauthenticated_put_returns_401`, `test_unauthenticated_get_returns_401`, `test_unauthenticated_delete_returns_401`. All three endpoints depend on `get_current_user_id` which returns 401 when no cookie is present. |
| Given user A's valid JWT, when PUT /v1/limits/daily is called, then the limit is stored under user A's internal UUID — user B cannot read or modify it | implemented | Tested in `test_limits_ownership_isolation`. user_id from JWT `sub` claim is used in all queries; user B's limit (seeded directly in DB) never appears in user A's GET response. |
| Security: limit_change audit log event is emitted for every create, update, and delete — the log entry must not contain the amount value | implemented | Tested in `test_audit_emitted_on_create_no_amount`, `test_audit_emitted_on_update_no_amount`, `test_audit_emitted_on_delete_no_amount`. Uses `unittest.mock.patch` (known working pattern from F-01-002). Audit call verified to include `user_id` and `request_id` (period:action), but no amount. |

**Summary**

`PUT /v1/limits/{period}`, `GET /v1/limits`, and `DELETE /v1/limits/{period}` are implemented in `app/src/protegopay/api/v1/limits.py`. The `DepositLimit` model (added to `db/models.py`) stores one record per user per period with a unique constraint, enabling upsert logic. Period is validated via `PeriodEnum` (daily/weekly/monthly) as a path parameter; amount is validated manually (>0, ≤10,000,000) before any DB access. All endpoints require authentication via the shared `get_current_user_id` dependency and enforce per-token rate limiting (60 req/min). The `limit_change` audit event is emitted on every write operation with user_id and period:action only — never with the amount. All 17 tests pass; the full 37-test suite passes with no regressions.

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
    stdout_summary: "Fast-forward to 66fe728, F-01-002 files pulled"

  - cmd: "git checkout -b feature/F-01-003-voluntary-limits"
    exit_code: 0
    stdout_summary: "Switched to new branch 'feature/F-01-003-voluntary-limits'"

  - cmd: "pip install -r requirements.txt -q"
    exit_code: 0
    stdout_summary: "All packages already satisfied"

  - cmd: "pip install -r requirements-dev.txt -q"
    exit_code: 0
    stdout_summary: "All packages already satisfied"

  - cmd: "python3 -m pytest tests/test_limits.py -v"
    exit_code: 0
    stdout_summary: "17 passed, 4 deprecation warnings (HTTP_422_UNPROCESSABLE_ENTITY → fixed)"

  - cmd: "python3 -m pytest tests/ -v"
    exit_code: 0
    stdout_summary: "37 passed, 0 warnings, 7.91s — no regressions"

  - cmd: "pip-audit --local"
    exit_code: 0
    stdout_summary: "No known vulnerabilities found"
```

---

## Issues discovered

```yaml
issues:
  - issue_id: "F-01-003-ISS-01"
    severity: low
    description: "FastAPI's status.HTTP_422_UNPROCESSABLE_ENTITY is deprecated in favour of HTTP_422_UNPROCESSABLE_CONTENT. Raised DeprecationWarning during initial test run."
    resolution: resolved
    resolution_notes: "Replaced all occurrences of HTTP_422_UNPROCESSABLE_ENTITY with HTTP_422_UNPROCESSABLE_CONTENT in limits.py. No test failures."
    do_not_retry: false

  - issue_id: "F-01-003-ISS-02"
    severity: low
    description: "python3-venv not installed on host; pip-audit -r requirements.txt fails. Known constraint from F-01-001-ISS-02."
    resolution: workaround
    resolution_notes: "Used pip-audit --local as in prior features."
    do_not_retry: false
```

---

## Procedures followed

**Security checklist** (from doc1 § Security checklist)

- [x] No secrets or credentials in source code or logs — no hardcoded values; all config from Settings
- [x] All inputs validated and sanitized — period validated via PeriodEnum (FastAPI path param); amount validated > 0 and ≤ 10,000,000 before any DB access; Pydantic schema on request body
- [x] Auth and authorization applied on every protected route — `get_current_user_id` dep on all three endpoints; user_id from JWT `sub` only; never from request body or path
- [x] Rate limiting in place on public-facing endpoints — per-token 60 req/min sliding window (`is_api_rate_limited`) applied at top of every handler
- [x] PII fields handled per data security policy — amounts stored as integers; amounts never logged; `DepositLimit` stores only internal user UUID, period string, and integer eurocents
- [x] Dependencies audited — `pip-audit --local` returned 0 vulnerabilities
- [x] Error messages do not leak internal stack traces to clients — validation errors return opaque `{"error": "..."}` detail; framework catches unhandled exceptions
- [x] Audit log events emitted for relevant actions — `limit_change` event on create, update, and delete; payload contains only user_id and period:action

```yaml
security_checklist_followed: true
security_checklist_notes: "All 12 items from doc1 checklist addressed. OIDC validation and Redis blacklist are handled by the shared get_current_user_id dependency (F-01-001). Admin separation: limits endpoints only issue user-scoped session JWTs; no admin role can access individual user limits. GDPR minimisation: DepositLimit stores only the minimum fields required (user_id, period, amount_eurocents, timestamps)."
```

**Worker instructions followed** (from doc2 § Worker instructions)

- [x] Read doc1_security_contract.md before writing code
- [x] Created correct branch name: `feature/F-01-003-voluntary-limits`
- [x] Implemented only what is in this feature block
- [x] Ran project test suite — 37 passed, 0 failed
- [x] Filled this milestone report completely
- [x] Opening PR with correct title format

```yaml
procedures_followed: true
procedures_notes: "pip-audit run with --local flag (python3-venv not available on host). Branched from develop after confirming F-01-002 was merged. Parallel-safe flag respected — no dependency on F-01-002 code paths."
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
