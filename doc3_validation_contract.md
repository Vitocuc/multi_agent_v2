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
| project_id | proj-protegopay-pilot-001 |
| contract_version | 1.0 |
| created_at | 2026-05-31 |
| validator_provider | Gemini |
| validator_model_version | gemini-2.5-flash |

---

## Validation principles

1. The validator reads test definitions and the milestone report — never the source code.
2. A test passes when the milestone report's `implemented` list and command outputs satisfy the test case's `expected` condition.
3. `blocking: true` tests must all pass before a PR can merge.
4. `human_gate_required: true` means a human must review even if all tests pass.
5. Security test failures are always escalated regardless of blocking flag.

---

## Test suites

---

### Suite F-01-001 — Concessionaire SSO Integration

```yaml
suite_id:               F-01-001
feature_id:             F-01-001
pass_threshold:         100%
human_gate_required:    true
```

**Test cases**

```yaml
- test_id:      F-01-001-T01
  type:         unit
  blocking:     true
  description:  >
    A valid OIDC ID token (signed, unexpired, correct audience) results in a 200 response
    with an httpOnly session JWT cookie.
  given:        "A valid OIDC ID token signed by the concessionaire IdP JWKS"
  when:         "POST /v1/auth/session is called with the token in the Authorization header"
  expected:     "Milestone report states: 200 returned, httpOnly Secure SameSite=Strict cookie set with 15m expiry"
  verified_via: milestone_report.implemented

- test_id:      F-01-001-T02
  type:         unit
  blocking:     true
  description:  >
    An expired OIDC ID token results in a 401 response with opaque error body.
  given:        "An expired OIDC ID token"
  when:         "POST /v1/auth/session is called"
  expected:     "Milestone report states: 401 returned, body is {\"error\": \"invalid_token\"}, no internal detail"
  verified_via: milestone_report.implemented

- test_id:      F-01-001-T03
  type:         unit
  blocking:     true
  description:  >
    An OIDC ID token with incorrect audience claim results in a 401 response.
  given:        "OIDC token with wrong audience claim"
  when:         "POST /v1/auth/session is called"
  expected:     "Milestone report states: 401 returned"
  verified_via: milestone_report.implemented

- test_id:      F-01-001-T04
  type:         unit
  blocking:     true
  description:  >
    An OIDC ID token with invalid signature results in a 401 response.
  given:        "OIDC token with signature not matching JWKS"
  when:         "POST /v1/auth/session is called"
  expected:     "Milestone report states: 401 returned"
  verified_via: milestone_report.implemented

- test_id:      F-01-001-T05
  type:         unit
  blocking:     true
  description:  >
    GET /v1/auth/me returns internal user_id and session_expires_at for a valid session.
  given:        "A valid session JWT cookie"
  when:         "GET /v1/auth/me is called"
  expected:     "Milestone report states: 200 returned with user_id (internal UUID) and session_expires_at; no external IdP identifier or PII"
  verified_via: milestone_report.implemented

- test_id:      F-01-001-T06
  type:         unit
  blocking:     true
  description:  >
    DELETE /v1/auth/session invalidates the JWT via Redis blacklist and clears the cookie.
  given:        "A valid session JWT cookie"
  when:         "DELETE /v1/auth/session is called"
  expected:     "Milestone report states: JWT added to Redis blacklist, cookie cleared, 204 returned"
  verified_via: milestone_report.implemented

- test_id:      F-01-001-T07
  type:         integration
  blocking:     true
  description:  >
    A JWT on the Redis blacklist is rejected on subsequent protected endpoint calls.
  given:        "A JWT that has been added to the Redis blacklist via logout"
  when:         "Any protected endpoint is called with that JWT"
  expected:     "Milestone report states: 401 returned for blacklisted token"
  verified_via: milestone_report.implemented

- test_id:      F-01-001-T08
  type:         unit
  blocking:     true
  description:  >
    Rate limiting blocks the 6th consecutive failed login attempt from the same IP within 15 minutes.
  given:        "5 consecutive POST /v1/auth/session failures from one IP within 15 minutes"
  when:         "A 6th attempt is made"
  expected:     "Milestone report states: 429 returned on 6th attempt"
  verified_via: milestone_report.implemented

- test_id:      F-01-001-T09
  type:         security
  blocking:     true
  description:  >
    No raw OIDC token, PII, JWKS key material, or Redis connection string appears in any
    log output or error response.
  given:        "Feature F-01-001 is implemented and tests have been run"
  when:         "Validator reads commands_run stdout_summary fields"
  expected:     "No token values, PII, key material, or connection strings visible in any stdout_summary"
  verified_via: milestone_report.commands_run[*].stdout_summary

- test_id:      F-01-001-T10
  type:         security
  blocking:     true
  description:  >
    All inputs to POST /v1/auth/session are validated via Pydantic before JWKS fetch begins.
  given:        "Feature F-01-001 is implemented"
  when:         "Validator reads security_checklist_followed and implemented fields"
  expected:     "security_checklist_followed: true; implemented notes confirm Pydantic validation runs before any external call"
  verified_via: milestone_report.security_checklist_followed
```

---

### Suite F-01-002 — Spending Dashboard API

```yaml
suite_id:               F-01-002
feature_id:             F-01-002
pass_threshold:         100%
human_gate_required:    true
```

**Test cases**

```yaml
- test_id:      F-01-002-T01
  type:         unit
  blocking:     true
  description:  >
    An authenticated user with spending events receives a 200 with correct aggregated fields.
  given:        "Authenticated user with at least one ingested spending event in the current month"
  when:         "GET /v1/dashboard is called"
  expected:     "Milestone report states: 200 returned with period_start, period_end, total_deposit_eurocents (int), session_count (int)"
  verified_via: milestone_report.implemented

- test_id:      F-01-002-T02
  type:         unit
  blocking:     true
  description:  >
    An authenticated user with no spending events receives a 200 with zero totals.
  given:        "Authenticated user with no spending events for the requested period"
  when:         "GET /v1/dashboard is called"
  expected:     "Milestone report states: 200 returned with total_deposit_eurocents: 0 and session_count: 0"
  verified_via: milestone_report.implemented

- test_id:      F-01-002-T03
  type:         unit
  blocking:     true
  description:  >
    An unauthenticated request receives a 401.
  given:        "No or invalid JWT cookie"
  when:         "GET /v1/dashboard is called"
  expected:     "Milestone report states: 401 returned"
  verified_via: milestone_report.implemented

- test_id:      F-01-002-T04
  type:         security
  blocking:     true
  description:  >
    Ownership enforcement: user A cannot see user B's dashboard data.
  given:        "User A's valid session JWT"
  when:         "GET /v1/dashboard is called"
  expected:     "Milestone report states: response contains only user A's data; worker confirms user_id always taken from JWT, not request"
  verified_via: milestone_report.implemented

- test_id:      F-01-002-T05
  type:         unit
  blocking:     true
  description:  >
    An invalid or out-of-range period query parameter results in a 422.
  given:        "Authenticated user with query param period=all_time"
  when:         "GET /v1/dashboard is called"
  expected:     "Milestone report states: 422 returned"
  verified_via: milestone_report.implemented

- test_id:      F-01-002-T06
  type:         integration
  blocking:     true
  description:  >
    A blacklisted JWT is rejected on dashboard access.
  given:        "A JWT on the Redis blacklist"
  when:         "GET /v1/dashboard is called"
  expected:     "Milestone report states: 401 returned"
  verified_via: milestone_report.implemented

- test_id:      F-01-002-T07
  type:         security
  blocking:     true
  description:  >
    Response payload never contains raw session identifiers, transaction IDs, or PII beyond spec.
  given:        "Feature F-01-002 is implemented"
  when:         "Validator reads implemented notes for dashboard response shape"
  expected:     "Implemented note confirms: no raw session IDs, transaction IDs, or PII in response"
  verified_via: milestone_report.implemented

- test_id:      F-01-002-T08
  type:         security
  blocking:     true
  description:  >
    A data_access audit log event is emitted for every successful dashboard call, containing
    user_id and period but not spending amounts.
  given:        "Feature F-01-002 is implemented"
  when:         "Validator reads security_checklist_followed and implemented"
  expected:     "security_checklist_followed: true; implemented confirms data_access event emitted without amount values"
  verified_via: milestone_report.security_checklist_followed
```

---

### Suite F-01-003 — Voluntary Deposit Limit Setup

```yaml
suite_id:               F-01-003
feature_id:             F-01-003
pass_threshold:         100%
human_gate_required:    true
```

**Test cases**

```yaml
- test_id:      F-01-003-T01
  type:         unit
  blocking:     true
  description:  >
    PUT /v1/limits/daily with a valid positive amount creates a limit and returns 200 with the persisted record.
  given:        "Authenticated user, body {\"amount_eurocents\": 5000}"
  when:         "PUT /v1/limits/daily is called"
  expected:     "Milestone report states: 200 returned with period, amount_eurocents, created_at, updated_at"
  verified_via: milestone_report.implemented

- test_id:      F-01-003-T02
  type:         unit
  blocking:     true
  description:  >
    PUT /v1/limits/daily with a new amount updates the existing limit (upsert).
  given:        "Authenticated user with an existing daily limit"
  when:         "PUT /v1/limits/daily is called with a new amount"
  expected:     "Milestone report states: 200 returned, existing limit updated"
  verified_via: milestone_report.implemented

- test_id:      F-01-003-T03
  type:         unit
  blocking:     true
  description:  >
    amount_eurocents of 0 or negative results in a 422 with a user-safe error message.
  given:        "amount_eurocents: 0 or -100"
  when:         "PUT /v1/limits/{period} is called"
  expected:     "Milestone report states: 422 returned with {\"error\": \"amount must be a positive integer\"}, no internal detail"
  verified_via: milestone_report.implemented

- test_id:      F-01-003-T04
  type:         unit
  blocking:     true
  description:  >
    amount_eurocents greater than 10_000_000 results in a 422.
  given:        "amount_eurocents: 10_000_001"
  when:         "PUT /v1/limits/{period} is called"
  expected:     "Milestone report states: 422 returned"
  verified_via: milestone_report.implemented

- test_id:      F-01-003-T05
  type:         unit
  blocking:     true
  description:  >
    An invalid period value results in a 422.
  given:        "period: quarterly"
  when:         "PUT /v1/limits/{period} is called"
  expected:     "Milestone report states: 422 returned"
  verified_via: milestone_report.implemented

- test_id:      F-01-003-T06
  type:         unit
  blocking:     true
  description:  >
    GET /v1/limits returns all active limits for the authenticated user.
  given:        "Authenticated user with limits set for multiple periods"
  when:         "GET /v1/limits is called"
  expected:     "Milestone report states: 200 returned with array of all active limits for that user"
  verified_via: milestone_report.implemented

- test_id:      F-01-003-T07
  type:         unit
  blocking:     true
  description:  >
    DELETE /v1/limits/daily removes the limit and subsequent GET returns empty for that period.
  given:        "Authenticated user with a daily limit set"
  when:         "DELETE /v1/limits/daily is called"
  expected:     "Milestone report states: 204 returned; limit no longer appears in GET /v1/limits"
  verified_via: milestone_report.implemented

- test_id:      F-01-003-T08
  type:         unit
  blocking:     true
  description:  >
    Unauthenticated requests to any /v1/limits endpoint receive a 401.
  given:        "No or invalid JWT cookie"
  when:         "Any /v1/limits endpoint is called"
  expected:     "Milestone report states: 401 returned"
  verified_via: milestone_report.implemented

- test_id:      F-01-003-T09
  type:         security
  blocking:     true
  description:  >
    Ownership enforcement: user A cannot read or modify user B's limits.
  given:        "User A's valid JWT"
  when:         "Any /v1/limits endpoint is called"
  expected:     "Milestone report states: user_id always taken from JWT; tests confirm user B's limits are not accessible"
  verified_via: milestone_report.implemented

- test_id:      F-01-003-T10
  type:         security
  blocking:     true
  description:  >
    limit_change audit log event is emitted for every write operation; log entry does not contain amount value.
  given:        "Feature F-01-003 is implemented"
  when:         "Validator reads security_checklist_followed and implemented notes"
  expected:     "security_checklist_followed: true; implemented confirms limit_change emitted without amount in log"
  verified_via: milestone_report.security_checklist_followed
```

---

### Suite F-02-001 — Spending Alert Notifications

```yaml
suite_id:               F-02-001
feature_id:             F-02-001
pass_threshold:         100%
human_gate_required:    true
```

**Test cases**

```yaml
- test_id:      F-02-001-T01
  type:         integration
  blocking:     true
  description:  >
    When cumulative spending crosses 80% of the daily limit, a limit_80pct alert is created.
  given:        "User with daily limit 5000 eurocents; spending total reaches 4001"
  when:         "A new spending event is ingested"
  expected:     "Milestone report states: alert record created with type limit_80pct, period daily, acknowledged false"
  verified_via: milestone_report.implemented

- test_id:      F-02-001-T02
  type:         integration
  blocking:     true
  description:  >
    GET /v1/dashboard includes unacknowledged alerts when spending exceeds 100% of limit.
  given:        "User with daily limit 5000 eurocents; cumulative spending 5001"
  when:         "GET /v1/dashboard is called"
  expected:     "Milestone report states: response alerts array contains 100% limit alert"
  verified_via: milestone_report.implemented

- test_id:      F-02-001-T03
  type:         unit
  blocking:     true
  description:  >
    PATCH /v1/alerts/{alert_id}/acknowledge marks the alert as acknowledged.
  given:        "Authenticated user with an unacknowledged alert"
  when:         "PATCH /v1/alerts/{alert_id}/acknowledge is called"
  expected:     "Milestone report states: acknowledged: true; alert no longer appears in unacknowledged list"
  verified_via: milestone_report.implemented

- test_id:      F-02-001-T04
  type:         security
  blocking:     true
  description:  >
    Ownership enforcement on alert acknowledgement: user A cannot acknowledge user B's alert.
  given:        "alert_id belonging to user B; user A's JWT"
  when:         "PATCH /v1/alerts/{alert_id}/acknowledge is called"
  expected:     "Milestone report states: 403 returned"
  verified_via: milestone_report.implemented

- test_id:      F-02-001-T05
  type:         unit
  blocking:     true
  description:  >
    POST /v1/alert-thresholds with a valid custom threshold persists the record.
  given:        "Authenticated user; body {\"amount_eurocents\": 3000, \"period\": \"weekly\"}"
  when:         "POST /v1/alert-thresholds is called"
  expected:     "Milestone report states: 200 returned; threshold persisted"
  verified_via: milestone_report.implemented

- test_id:      F-02-001-T06
  type:         integration
  blocking:     true
  description:  >
    When spending crosses a custom threshold, an alert of type custom_threshold is created.
  given:        "Custom threshold configured at 3000 eurocents weekly; spending crosses 3000"
  when:         "Spending event is ingested"
  expected:     "Milestone report states: alert of type custom_threshold created"
  verified_via: milestone_report.implemented

- test_id:      F-02-001-T07
  type:         security
  blocking:     true
  description:  >
    alert_config_change audit log event is emitted on threshold write; no amount in log entry.
  given:        "Feature F-02-001 is implemented"
  when:         "Validator reads security_checklist_followed and implemented"
  expected:     "security_checklist_followed: true; implemented confirms alert_config_change emitted without amount"
  verified_via: milestone_report.security_checklist_followed

- test_id:      F-02-001-T08
  type:         security
  blocking:     true
  description:  >
    Alert records for user A are never returned in user B's dashboard or alert list.
  given:        "Two users each with alerts; user B's JWT"
  when:         "GET /v1/dashboard or GET /v1/alerts is called by user B"
  expected:     "Milestone report states: only user B's alerts returned"
  verified_via: milestone_report.implemented
```

---

### Suite F-02-002 — Reflection Pause

```yaml
suite_id:               F-02-002
feature_id:             F-02-002
pass_threshold:         100%
human_gate_required:    false
```

**Test cases**

```yaml
- test_id:      F-02-002-T01
  type:         unit
  blocking:     true
  description:  >
    POST /v1/pause with a valid duration activates a pause and returns correct fields.
  given:        "Authenticated user with no active pause; body {\"duration\": \"24h\"}"
  when:         "POST /v1/pause is called"
  expected:     "Milestone report states: 200 returned with pause_id, starts_at, expires_at, revocable_until (= starts_at + 30min), status: active"
  verified_via: milestone_report.implemented

- test_id:      F-02-002-T02
  type:         unit
  blocking:     true
  description:  >
    An invalid duration value results in a 422.
  given:        "body {\"duration\": \"3h\"}"
  when:         "POST /v1/pause is called"
  expected:     "Milestone report states: 422 returned"
  verified_via: milestone_report.implemented

- test_id:      F-02-002-T03
  type:         unit
  blocking:     true
  description:  >
    Cancelling a pause within the 30-minute revocable window succeeds.
  given:        "Active pause activated less than 30 minutes ago"
  when:         "DELETE /v1/pause/{pause_id} is called"
  expected:     "Milestone report states: 204 returned; pause cancelled"
  verified_via: milestone_report.implemented

- test_id:      F-02-002-T04
  type:         unit
  blocking:     true
  description:  >
    Attempting to cancel a pause after the revocable window results in a 409.
  given:        "Active pause activated more than 30 minutes ago"
  when:         "DELETE /v1/pause/{pause_id} is called"
  expected:     "Milestone report states: 409 returned with {\"error\": \"pause_irrevocable\"}"
  verified_via: milestone_report.implemented

- test_id:      F-02-002-T05
  type:         integration
  blocking:     true
  description:  >
    GET /v1/dashboard during an active pause returns the reduced view without spending amounts.
  given:        "User with an active pause"
  when:         "GET /v1/dashboard is called"
  expected:     "Milestone report states: response omits spending amounts; returns pause_active: true, pause_expires_at, and neutral message"
  verified_via: milestone_report.implemented

- test_id:      F-02-002-T06
  type:         security
  blocking:     true
  description:  >
    Ownership enforcement: user A cannot cancel user B's pause.
  given:        "pause_id belonging to user B; user A's JWT"
  when:         "DELETE /v1/pause/{pause_id} is called"
  expected:     "Milestone report states: 403 returned"
  verified_via: milestone_report.implemented

- test_id:      F-02-002-T07
  type:         unit
  blocking:     true
  description:  >
    Unauthenticated POST /v1/pause returns 401.
  given:        "No or invalid JWT"
  when:         "POST /v1/pause is called"
  expected:     "Milestone report states: 401 returned"
  verified_via: milestone_report.implemented

- test_id:      F-02-002-T08
  type:         security
  blocking:     true
  description:  >
    pause_start audit event emitted on activation; pause_end on cancellation; no spending data in either.
  given:        "Feature F-02-002 is implemented"
  when:         "Validator reads security_checklist_followed and implemented"
  expected:     "security_checklist_followed: true; implemented confirms pause_start and pause_end events emitted without spending data"
  verified_via: milestone_report.security_checklist_followed
```

---

### Suite F-02-003 — Admin Audit Log & GDPR Data Export

```yaml
suite_id:               F-02-003
feature_id:             F-02-003
pass_threshold:         100%
human_gate_required:    true
```

**Test cases**

```yaml
- test_id:      F-02-003-T01
  type:         unit
  blocking:     true
  description:  >
    concessionaire_admin JWT receives 200 with aggregate stats from GET /v1/admin/stats.
  given:        "concessionaire_admin JWT"
  when:         "GET /v1/admin/stats is called"
  expected:     "Milestone report states: 200 returned with active_users_count, limits_configured_count, pauses_active_count — no individual user data"
  verified_via: milestone_report.implemented

- test_id:      F-02-003-T02
  type:         security
  blocking:     true
  description:  >
    A user-scope JWT receives a 403 on GET /v1/admin/stats.
  given:        "User-scope JWT"
  when:         "GET /v1/admin/stats is called"
  expected:     "Milestone report states: 403 returned"
  verified_via: milestone_report.implemented

- test_id:      F-02-003-T03
  type:         unit
  blocking:     true
  description:  >
    Unauthenticated request to GET /v1/admin/stats returns 401.
  given:        "No JWT"
  when:         "GET /v1/admin/stats is called"
  expected:     "Milestone report states: 401 returned"
  verified_via: milestone_report.implemented

- test_id:      F-02-003-T04
  type:         unit
  blocking:     true
  description:  >
    POST /v1/me/export returns 202 with export_id and status: processing.
  given:        "Authenticated end user"
  when:         "POST /v1/me/export is called"
  expected:     "Milestone report states: 202 returned with export_id and status: processing"
  verified_via: milestone_report.implemented

- test_id:      F-02-003-T05
  type:         integration
  blocking:     true
  description:  >
    GET /v1/me/export/{export_id} returns a pre-signed S3 URL when the export is ready.
  given:        "A completed export; same user's JWT"
  when:         "GET /v1/me/export/{export_id} is called"
  expected:     "Milestone report states: 200 returned with status: ready and download_url (pre-signed, valid 15 min)"
  verified_via: milestone_report.implemented

- test_id:      F-02-003-T06
  type:         security
  blocking:     true
  description:  >
    Ownership enforcement: a different user cannot access another user's export.
  given:        "export_id belonging to user A; user B's JWT"
  when:         "GET /v1/me/export/{export_id} is called"
  expected:     "Milestone report states: 403 returned"
  verified_via: milestone_report.implemented

- test_id:      F-02-003-T07
  type:         security
  blocking:     true
  description:  >
    The GDPR export file contains the specified fields and explicitly excludes spending amounts and OIDC claims.
  given:        "A completed GDPR export"
  when:         "Validator reads the implemented note describing export file contents"
  expected:     "Implemented note confirms: internal_user_id, limit_settings, alert_thresholds, pause_records, audit_events present; spending amounts and OIDC claims absent"
  verified_via: milestone_report.implemented

- test_id:      F-02-003-T08
  type:         security
  blocking:     true
  description:  >
    gdpr_data_export audit event emitted on every POST /v1/me/export; contains user_id and timestamp only.
  given:        "Feature F-02-003 is implemented"
  when:         "Validator reads security_checklist_followed and implemented"
  expected:     "security_checklist_followed: true; implemented confirms gdpr_data_export event emitted without export contents"
  verified_via: milestone_report.security_checklist_followed

- test_id:      F-02-003-T09
  type:         security
  blocking:     true
  description:  >
    admin_action audit event emitted on every GET /v1/admin/stats call.
  given:        "Feature F-02-003 is implemented"
  when:         "Validator reads implemented notes"
  expected:     "Implemented confirms admin_action event emitted on every admin stats call"
  verified_via: milestone_report.implemented
```

---

## Cross-feature security tests
<!-- These run after every milestone, regardless of which feature was implemented. -->

```yaml
- test_id:      SEC-GLOBAL-01
  type:         security
  blocking:     true
  description:  >
    No credentials, tokens, PII, spending amounts, or connection strings appear in any
    logged command output in the milestone report.
  verified_via: milestone_report.commands_run[*].stdout_summary

- test_id:      SEC-GLOBAL-02
  type:         security
  blocking:     true
  description:  >
    The security checklist in doc1 was followed for this feature — all 12 items addressed.
  verified_via: milestone_report.security_checklist_followed

- test_id:      SEC-GLOBAL-03
  type:         security
  blocking:     true
  description:  >
    No HIGH or CRITICAL CVEs introduced by new dependencies. pip-audit exit code is 0
    or all flagged CVEs are documented in issues_discovered with an accepted resolution.
  verified_via: milestone_report.commands_run — look for pip-audit command and exit code

- test_id:      SEC-GLOBAL-04
  type:         security
  blocking:     true
  description:  >
    All user_id values used in data access are resolved from the validated JWT claim —
    never from the request body, query string, or path parameter alone.
  verified_via: milestone_report.implemented — worker must explicitly confirm this in the note for each data-access criterion
```

---

## Validator output format
<!-- The validator must produce a result in this exact format after each run.
     This output is read by the system to update doc4 and shared memory. -->

```yaml
validator_run:
  suite_id:         ""
  run_at:           ""
  provider:         "Gemini"
  model_version:    "gemini-2.5-flash"
  overall:          pass | fail
  blocking_passed:  true | false
  human_gate:       pending | approved | rejected

  results:
    - test_id:      ""
      status:       pass | fail | skip
      notes:        ""

  failures:         []
  escalations:      []
```

---

## Amendments

| Version | Date | Changed by | Summary |
|---|---|---|---|
| 1.0 | 2026-05-31 | CTO orchestrator | Initial — generated from doc0 ProtegoPay pilot brief |
