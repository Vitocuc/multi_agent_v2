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
| project_id | proj-protegopay-pilot-001 |
| contract_version | 1.0 |
| created_at | 2026-05-31 |
| total_features | 6 |
| total_milestones | 2 |

---

## Milestone map

| Milestone ID | Name | Features | Goal |
|---|---|---|---|
| M-01 | Pilot Foundation | F-01-001, F-01-002, F-01-003 | A concessionaire admin can embed the module; a user can log in via SSO, view their spending dashboard, and set voluntary deposit limits |
| M-02 | Alerts, Pauses & Compliance | F-02-001, F-02-002, F-02-003 | Users receive configurable spending alerts and can trigger reflection pauses; admin and GDPR data-export workflows are operational |

---

## Feature blocks

---

### F-01-001 — Concessionaire SSO Integration (OIDC session bootstrap)

```yaml
feature_id:         F-01-001
title:              "Concessionaire SSO Integration"
milestone_id:       M-01
priority:           critical
complexity:         M
depends_on:         []
parallel_safe:      false
```

**Description**

ProtegoPay receives an OIDC ID token from the concessionaire's Identity Provider (IdP) after the user authenticates on the concessionaire's platform. This feature validates the ID token against the concessionaire's JWKS endpoint, maps the external user identity to an internal UUID (creating a new record on first login), and issues a short-lived ProtegoPay session JWT stored in an httpOnly cookie. No ProtegoPay-managed passwords or KYC flows exist; all authentication authority remains with the concessionaire's IdP. This feature is the authentication foundation for every other feature.

**Security constraints**

- Auth: `doc1 § Authentication — mechanism (OIDC PKCE), token_location (httpOnly cookie), token_expiry (15m access), logout_strategy (Redis blacklist + cookie clear)`
- Input: `doc1 § Input validation — Pydantic schema on all inputs; OIDC claims validated against JWKS before any DB write`
- Logging: `doc1 § Audit logging — auth_success, auth_failure, session_logout events required`
- Data: `doc1 § Data security — at_rest.pii_fields: user_id_external tokenised to internal UUID; no raw OIDC claims persisted`
- Rate limiting: `doc1 § Rate limiting — auth_endpoints: 5 failures / 15 min lockout`

**Acceptance criteria**

- [ ] Given a valid OIDC ID token (signed, unexpired, correct audience) from the concessionaire's IdP, when POST /v1/auth/session is called with the token in the Authorization header, then a 200 response is returned and an httpOnly Secure SameSite=Strict JWT cookie is set with a 15-minute expiry
- [ ] Given an expired OIDC ID token, when POST /v1/auth/session is called, then a 401 response is returned with body `{"error": "invalid_token"}` and no internal detail
- [ ] Given an OIDC ID token with an incorrect audience claim, when POST /v1/auth/session is called, then a 401 response is returned
- [ ] Given an OIDC ID token whose signature does not match the concessionaire's JWKS, when POST /v1/auth/session is called, then a 401 response is returned
- [ ] Given a valid session JWT cookie, when GET /v1/auth/me is called, then a 200 response is returned with `{"user_id": "<internal-uuid>", "session_expires_at": "<ISO8601>"}` — no external IdP identifier or PII in the response
- [ ] Given a valid session JWT cookie, when DELETE /v1/auth/session is called, then the JWT is added to the Redis blacklist, the cookie is cleared, and a 204 response is returned
- [ ] Given a JWT that has been added to the Redis blacklist, when any protected endpoint is called with that JWT, then a 401 response is returned
- [ ] Given 5 consecutive POST /v1/auth/session failures from the same IP within 15 minutes, when a 6th attempt is made, then a 429 response is returned
- [ ] Security: no raw OIDC ID token, user PII, JWKS key material, or Redis connection string appears in any log line or error response
- [ ] Security: all inputs to POST /v1/auth/session are validated via Pydantic before JWKS fetch begins

**Worker instructions**

```
1. Read doc1_security_contract.md in full before writing any code.
2. Create branch: git checkout -b feature/F-01-001-sso-session
3. Install dependencies: python-jose (JWT), httpx (JWKS fetch), redis-py, pydantic v2, fastapi.
4. Implement POST /v1/auth/session: validate OIDC ID token via JWKS, upsert user record, issue session JWT in httpOnly cookie.
5. Implement GET /v1/auth/me: verify session JWT (including Redis blacklist check), return internal user_id and expiry.
6. Implement DELETE /v1/auth/session: add JWT to Redis blacklist (TTL = remaining token lifetime), clear cookie.
7. Wire rate-limiter middleware on POST /v1/auth/session (5 failures / 15 min per IP).
8. Add audit log events: auth_success, auth_failure, session_logout.
9. Add Pydantic schema for the session request; reject anything that does not match.
10. Write unit tests for all 10 acceptance criteria. Run pip-audit before filing report.
11. Do NOT store the raw OIDC ID token in the database or logs.
12. Fill in doc4_milestone_report.md for F-01-001.
13. Open a PR against main. Title: "[F-01-001] Concessionaire SSO Integration".
```

**Done definition**

- [ ] All acceptance criteria pass in validator run
- [ ] Security checklist in doc1 fully checked
- [ ] Milestone report filed with milestone_status: passed
- [ ] PR approved by human reviewer

**GitHub**

```yaml
branch_name:        feature/F-01-001-sso-session
github_issue_id:    ""
pr_id:              ""
```

---

### F-01-002 — Spending Dashboard API

```yaml
feature_id:         F-01-002
title:              "Spending Dashboard API"
milestone_id:       M-01
priority:           critical
complexity:         M
depends_on:         [F-01-001]
parallel_safe:      false
```

**Description**

Exposes a read-only REST endpoint that returns the authenticated user's aggregated gaming-spending summary for a configurable period (default: current calendar month). Data is ingested from the concessionaire's event feed via a webhook receiver or polling adapter (the ingestion mechanism is a configuration choice, not part of this feature's acceptance criteria — mock data is acceptable for the pilot). The response contains only aggregated totals (total deposit amount, session count, period boundaries) — never individual transaction records or raw event data. This feature must enforce strict ownership: each user sees only their own data.

**Security constraints**

- Auth: `doc1 § Authentication — session JWT required; blacklist check on every request`
- Authorization: `doc1 § Authorization — ownership_check: true; user_id from JWT claim only`
- Data: `doc1 § Data security — spending_amounts stored as integers (eurocents); no raw session events stored or returned`
- Logging: `doc1 § Audit logging — data_access event (user_id + period, no amounts)`
- Rate limiting: `doc1 § Rate limiting — api_endpoints: 60 req/min per token`

**Acceptance criteria**

- [ ] Given an authenticated user with at least one ingested spending event in the current month, when GET /v1/dashboard is called (no query params), then a 200 response is returned with `{"period_start": "<ISO8601>", "period_end": "<ISO8601>", "total_deposit_eurocents": <int>, "session_count": <int>}`
- [ ] Given an authenticated user with no spending events for the requested period, when GET /v1/dashboard is called, then a 200 response is returned with `total_deposit_eurocents: 0` and `session_count: 0`
- [ ] Given an unauthenticated request (no or invalid JWT cookie), when GET /v1/dashboard is called, then a 401 response is returned
- [ ] Given user A's valid session JWT, when GET /v1/dashboard is called, then the response contains only user A's data — user B's data is never included
- [ ] Given a request with an invalid or out-of-range `period` query parameter (e.g. `period=all_time`), when GET /v1/dashboard is called, then a 422 response is returned
- [ ] Given a session JWT that is on the Redis blacklist, when GET /v1/dashboard is called, then a 401 response is returned
- [ ] Security: the response payload never contains raw session identifiers, raw deposit transaction IDs, or any PII beyond what is listed in the acceptance criteria above
- [ ] Security: a data_access audit log event is emitted for every successful call, containing user_id and period but not amounts

**Worker instructions**

```
1. Read doc1_security_contract.md in full before writing any code.
2. Create branch: git checkout -b feature/F-01-002-spending-dashboard
3. F-01-001 must be merged and passing before this branch is started (depends_on).
4. Implement GET /v1/dashboard with optional ?period=current_month|last_month query param.
5. Fetch aggregated data from the SpendingEvent table (seeded with mock data for pilot). Do NOT expose raw events.
6. user_id is always resolved from the validated JWT — never accept it from the query string or body.
7. Emit data_access audit log event on each successful response.
8. Write unit + integration tests covering all 8 acceptance criteria.
9. Run pip-audit before filing report.
10. Fill in doc4_milestone_report.md for F-01-002.
11. Open a PR against main. Title: "[F-01-002] Spending Dashboard API".
```

**Done definition**

- [ ] All acceptance criteria pass in validator run
- [ ] Security checklist in doc1 fully checked
- [ ] Milestone report filed with milestone_status: passed
- [ ] PR approved by human reviewer

**GitHub**

```yaml
branch_name:        feature/F-01-002-spending-dashboard
github_issue_id:    ""
pr_id:              ""
```

---

### F-01-003 — Voluntary Deposit Limit Setup

```yaml
feature_id:         F-01-003
title:              "Voluntary Deposit Limit Setup"
milestone_id:       M-01
priority:           high
complexity:         M
depends_on:         [F-01-001]
parallel_safe:      true
```

**Description**

Allows an authenticated user to configure voluntary advisory deposit limits per period (daily, weekly, monthly). Limits are advisory in the pilot — the system records them and will alert when a limit is approached (F-02-001), but does not block deposits (that is the concessionaire's responsibility). Users can create, update, and delete limits. The endpoint enforces ownership and validates all input. Limit amounts are stored as integers (eurocents). This feature can be developed in parallel with F-01-002 after F-01-001 is merged.

**Security constraints**

- Auth: `doc1 § Authentication — session JWT required; blacklist check on every request`
- Authorization: `doc1 § Authorization — ownership_check: true; admin_separation: true — no admin role can read or modify individual user limits`
- Input: `doc1 § Input validation — Pydantic validation: period must be one of [daily, weekly, monthly]; amount must be integer > 0 and ≤ 10_000_000 eurocents (€100k ceiling for pilot)`
- Logging: `doc1 § Audit logging — limit_change event (user_id, period, action: created|updated|deleted — no amount value in log)`
- Data: `doc1 § Data security — limit_settings stored as integer eurocents; retention governed by GDPR policy`

**Acceptance criteria**

- [ ] Given an authenticated user, when PUT /v1/limits/daily with body `{"amount_eurocents": 5000}`, then a 200 response is returned with the persisted limit record including `{"period": "daily", "amount_eurocents": 5000, "created_at": "<ISO8601>", "updated_at": "<ISO8601>"}`
- [ ] Given an authenticated user with an existing daily limit, when PUT /v1/limits/daily with a new amount, then the existing limit is updated (upsert) and a 200 response is returned
- [ ] Given `amount_eurocents` of 0 or negative, when PUT /v1/limits/{period} is called, then a 422 response is returned with `{"error": "amount must be a positive integer"}` — no internal detail
- [ ] Given `amount_eurocents` greater than 10_000_000, when PUT /v1/limits/{period} is called, then a 422 response is returned
- [ ] Given an invalid period value (e.g. `quarterly`), when PUT /v1/limits/{period} is called, then a 422 response is returned
- [ ] Given an authenticated user with limits set, when GET /v1/limits is called, then a 200 response is returned with an array of all active limits for that user
- [ ] Given an authenticated user with a daily limit set, when DELETE /v1/limits/daily is called, then a 204 response is returned and the limit no longer appears in GET /v1/limits
- [ ] Given an unauthenticated request, when any /v1/limits endpoint is called, then a 401 response is returned
- [ ] Given user A's valid JWT, when PUT /v1/limits/daily is called, then the limit is stored under user A's internal UUID — user B cannot read or modify it
- [ ] Security: limit_change audit log event is emitted for every create, update, and delete — the log entry must not contain the amount value

**Worker instructions**

```
1. Read doc1_security_contract.md in full before writing any code.
2. Create branch: git checkout -b feature/F-01-003-voluntary-limits
3. F-01-001 must be merged and passing before this branch is started (depends_on).
4. This feature may be developed in parallel with F-01-002 (parallel_safe: true).
5. Implement PUT /v1/limits/{period} (upsert), GET /v1/limits, DELETE /v1/limits/{period}.
6. Validate period against Literal["daily", "weekly", "monthly"] via Pydantic.
7. Validate amount_eurocents: int, > 0, ≤ 10_000_000.
8. user_id is always resolved from the validated JWT — never accept it from the body or path.
9. Emit limit_change audit log event on every write operation; do NOT log the amount.
10. Write unit + integration tests covering all 10 acceptance criteria.
11. Run pip-audit before filing report.
12. Fill in doc4_milestone_report.md for F-01-003.
13. Open a PR against main. Title: "[F-01-003] Voluntary Deposit Limit Setup".
```

**Done definition**

- [ ] All acceptance criteria pass in validator run
- [ ] Security checklist in doc1 fully checked
- [ ] Milestone report filed with milestone_status: passed
- [ ] PR approved by human reviewer

**GitHub**

```yaml
branch_name:        feature/F-01-003-voluntary-limits
github_issue_id:    ""
pr_id:              ""
```

---

### F-02-001 — Spending Alert Notifications

```yaml
feature_id:         F-02-001
title:              "Spending Alert Notifications"
milestone_id:       M-02
priority:           high
complexity:         M
depends_on:         [F-01-002, F-01-003]
parallel_safe:      false
```

**Description**

Evaluates the authenticated user's current-period spending against their voluntary deposit limits (F-01-003) whenever a new spending event is ingested. When spending reaches 80% or 100% of a limit, an in-app alert record is created and returned in the dashboard response (F-01-002). Users can also configure custom alert thresholds independently of limits. Alert state is stored per user per period; alerts are not re-sent once acknowledged. No external push notifications in the pilot — in-app only.

**Security constraints**

- Auth: `doc1 § Authentication — session JWT required on all alert endpoints`
- Authorization: `doc1 § Authorization — ownership_check: true`
- Input: `doc1 § Input validation — Pydantic validation on custom threshold configuration`
- Logging: `doc1 § Audit logging — alert_config_change event on threshold create/update/delete`
- Data: `doc1 § Data security — alert_thresholds stored as integer eurocents; no raw amounts in logs`

**Acceptance criteria**

- [ ] Given a user with a daily limit of 5000 eurocents and cumulative daily spending of 4000 eurocents, when a new spending event brings the total to 4001, then an alert record with `{"type": "limit_80pct", "period": "daily", "acknowledged": false}` is created for that user
- [ ] Given a user with a daily limit of 5000 eurocents and cumulative daily spending of 5001 eurocents, when GET /v1/dashboard is called, then the response includes an `alerts` array containing the 100% limit alert
- [ ] Given a user who calls PATCH /v1/alerts/{alert_id}/acknowledge, then the alert is marked `acknowledged: true` and no longer appears in the unacknowledged alert list
- [ ] Given an alert_id belonging to another user, when PATCH /v1/alerts/{alert_id}/acknowledge is called, then a 403 response is returned
- [ ] Given an authenticated user, when POST /v1/alert-thresholds with `{"amount_eurocents": 3000, "period": "weekly"}`, then a 200 response is returned and the threshold is persisted
- [ ] Given a custom threshold configured, when spending crosses that threshold, then an alert of type `custom_threshold` is created
- [ ] Security: alert_config_change audit log event is emitted on threshold create/update/delete — no amount in log
- [ ] Security: alert records for user A are never returned in user B's dashboard or alert list

**Worker instructions**

```
1. Read doc1_security_contract.md in full before writing any code.
2. Create branch: git checkout -b feature/F-02-001-spending-alerts
3. F-01-002 and F-01-003 must be merged and passing before this branch is started.
4. Implement the alert evaluation logic as a service called after spending event ingestion.
5. Implement GET /v1/alerts (list unacknowledged alerts), PATCH /v1/alerts/{id}/acknowledge.
6. Implement POST /v1/alert-thresholds, GET /v1/alert-thresholds, DELETE /v1/alert-thresholds/{id}.
7. Extend GET /v1/dashboard response to include an alerts array.
8. All ownership checks via JWT user_id — never trust path parameters alone.
9. Emit alert_config_change log event on every threshold write.
10. Write unit + integration tests covering all 8 acceptance criteria.
11. Run pip-audit before filing report.
12. Fill in doc4_milestone_report.md for F-02-001.
13. Open a PR against main. Title: "[F-02-001] Spending Alert Notifications".
```

**Done definition**

- [ ] All acceptance criteria pass in validator run
- [ ] Security checklist in doc1 fully checked
- [ ] Milestone report filed with milestone_status: passed
- [ ] PR approved by human reviewer

**GitHub**

```yaml
branch_name:        feature/F-02-001-spending-alerts
github_issue_id:    ""
pr_id:              ""
```

---

### F-02-002 — Reflection Pause

```yaml
feature_id:         F-02-002
title:              "Reflection Pause"
milestone_id:       M-02
priority:           medium
complexity:         S
depends_on:         [F-01-001]
parallel_safe:      true
```

**Description**

Allows an authenticated user to voluntarily activate a reflection pause for a fixed duration (1 hour, 24 hours, or 7 days). During an active pause, the dashboard returns a reduced view (no spending amounts — only the pause expiry time and a neutral message). The pause is revocable during a cooling-off window (30 minutes after activation) and becomes irrevocable after that. Pauses are advisory in the pilot — ProtegoPay records and displays the pause state but does not block deposits (that remains the concessionaire's responsibility). This feature may be developed in parallel with F-02-001.

**Security constraints**

- Auth: `doc1 § Authentication — session JWT required`
- Authorization: `doc1 § Authorization — ownership_check: true; user cannot activate or cancel another user's pause`
- Logging: `doc1 § Audit logging — pause_start and pause_end events required; no spending data in log`
- Input: `doc1 § Input validation — duration must be one of [1h, 24h, 7d]; no other values accepted`

**Acceptance criteria**

- [ ] Given an authenticated user with no active pause, when POST /v1/pause with body `{"duration": "24h"}`, then a 200 response is returned with `{"pause_id": "<uuid>", "starts_at": "<ISO8601>", "expires_at": "<ISO8601>", "revocable_until": "<ISO8601 = starts_at + 30min>", "status": "active"}`
- [ ] Given an invalid duration value (e.g. `"3h"`), when POST /v1/pause is called, then a 422 response is returned
- [ ] Given a user with an active pause activated less than 30 minutes ago, when DELETE /v1/pause/{pause_id} is called, then the pause is cancelled and a 204 response is returned
- [ ] Given a user with an active pause activated more than 30 minutes ago, when DELETE /v1/pause/{pause_id} is called, then a 409 response is returned with `{"error": "pause_irrevocable"}` — the pause cannot be cancelled
- [ ] Given a user with an active pause, when GET /v1/dashboard is called, then the response omits spending amounts and instead returns `{"pause_active": true, "pause_expires_at": "<ISO8601>", "message": "You have an active reflection pause."}`
- [ ] Given user A's JWT, when DELETE /v1/pause/{pause_id_of_user_B} is called, then a 403 response is returned
- [ ] Given an unauthenticated request, when POST /v1/pause is called, then a 401 response is returned
- [ ] Security: pause_start audit log event is emitted on activation; pause_end event is emitted on cancellation or expiry; no spending data in either log entry

**Worker instructions**

```
1. Read doc1_security_contract.md in full before writing any code.
2. Create branch: git checkout -b feature/F-02-002-reflection-pause
3. F-01-001 must be merged and passing (depends_on). May be developed in parallel with F-02-001.
4. Implement POST /v1/pause, GET /v1/pause (current status), DELETE /v1/pause/{id}.
5. Store pause records with starts_at, expires_at, revocable_until, and status fields.
6. Modify GET /v1/dashboard to detect active pause and return the reduced view.
7. Emit pause_start on activation and pause_end on cancellation or expiry.
8. Validate duration as Literal["1h", "24h", "7d"] via Pydantic.
9. Write unit + integration tests covering all 8 acceptance criteria.
10. Run pip-audit before filing report.
11. Fill in doc4_milestone_report.md for F-02-002.
12. Open a PR against main. Title: "[F-02-002] Reflection Pause".
```

**Done definition**

- [ ] All acceptance criteria pass in validator run
- [ ] Security checklist in doc1 fully checked
- [ ] Milestone report filed with milestone_status: passed
- [ ] PR approved by human reviewer

**GitHub**

```yaml
branch_name:        feature/F-02-002-reflection-pause
github_issue_id:    ""
pr_id:              ""
```

---

### F-02-003 — Admin Audit Log & GDPR Data Export

```yaml
feature_id:         F-02-003
title:              "Admin Audit Log & GDPR Data Export"
milestone_id:       M-02
priority:           high
complexity:         L
depends_on:         [F-01-001, F-01-002, F-01-003]
parallel_safe:      false
```

**Description**

Two distinct sub-flows under one feature block:

1. **Concessionaire admin view:** A concessionaire_admin can retrieve anonymised aggregate statistics (total active users, total limits set, total pauses activated) via a protected admin endpoint. The admin cannot access individual user data, limits, amounts, or pause details.

2. **GDPR data export (Art. 20):** An authenticated end user can request an export of all data ProtegoPay holds about them. The export is generated asynchronously, stored in a time-limited pre-signed S3 URL, and delivered in-app as a download link. The export includes: internal user UUID, all limit settings, all alert thresholds, all pause records, and the audit log of their own events. It explicitly excludes: raw spending amounts (those are held by the concessionaire, not ProtegoPay), OIDC claims, and other users' data.

**Security constraints**

- Auth: `doc1 § Authentication — session JWT required; role claim verified for admin endpoints`
- Authorization: `doc1 § Authorization — admin_separation: true; concessionaire_admin JWT cannot access user-scope endpoints and vice versa`
- Data: `doc1 § Data security — GDPR export must not include spending amounts or raw identifiers beyond internal UUID`
- Logging: `doc1 § Audit logging — gdpr_data_export event on every export request (user_id, timestamp); admin_action event on every admin aggregate query`
- Input: `doc1 § Input validation — export request validated; admin filter params validated via Pydantic`

**Acceptance criteria**

- [ ] Given a concessionaire_admin JWT, when GET /v1/admin/stats is called, then a 200 response is returned with `{"active_users_count": <int>, "limits_configured_count": <int>, "pauses_active_count": <int>}` — no individual user data
- [ ] Given a user-scope JWT, when GET /v1/admin/stats is called, then a 403 response is returned
- [ ] Given an unauthenticated request, when GET /v1/admin/stats is called, then a 401 response is returned
- [ ] Given an authenticated end user, when POST /v1/me/export is called, then a 202 response is returned with `{"export_id": "<uuid>", "status": "processing"}`
- [ ] Given a completed export, when GET /v1/me/export/{export_id} is called by the same user, then a 200 response is returned with `{"status": "ready", "download_url": "<pre-signed S3 URL, valid 15 min>"}` — the URL expires after 15 minutes
- [ ] Given an export_id belonging to another user, when GET /v1/me/export/{export_id} is called, then a 403 response is returned
- [ ] Given the export file, then it contains: internal_user_id, limit_settings array, alert_thresholds array, pause_records array, audit_events array (user's own events only) — and explicitly does NOT contain spending amounts or OIDC claims
- [ ] Security: gdpr_data_export audit log event is emitted on every POST /v1/me/export call — the log entry must contain user_id and timestamp only, not the export contents
- [ ] Security: admin_action audit log event is emitted on every GET /v1/admin/stats call — log contains admin user_id and timestamp

**Worker instructions**

```
1. Read doc1_security_contract.md in full before writing any code.
2. Create branch: git checkout -b feature/F-02-003-audit-gdpr-export
3. F-01-001, F-01-002, and F-01-003 must be merged and passing before this branch is started.
4. Implement GET /v1/admin/stats — behind concessionaire_admin role check; returns aggregates only.
5. Implement POST /v1/me/export — enqueue async export job; return 202 with export_id.
6. Implement the export job: collect user's own data, build JSON export, upload to S3, generate 15-min pre-signed URL.
7. Implement GET /v1/me/export/{export_id} — ownership check; return status and URL when ready.
8. Explicitly exclude spending amounts and OIDC claims from the export payload.
9. Emit gdpr_data_export on every POST /v1/me/export; emit admin_action on every GET /v1/admin/stats.
10. For the pilot, an in-process background task (e.g. FastAPI BackgroundTasks or asyncio) is acceptable for the async export job; note in doc4 if a proper queue is needed for production.
11. Write unit + integration tests covering all 9 acceptance criteria.
12. Run pip-audit before filing report.
13. Fill in doc4_milestone_report.md for F-02-003.
14. Open a PR against main. Title: "[F-02-003] Admin Audit Log & GDPR Data Export".
```

**Done definition**

- [ ] All acceptance criteria pass in validator run
- [ ] Security checklist in doc1 fully checked
- [ ] Milestone report filed with milestone_status: passed
- [ ] PR approved by human reviewer

**GitHub**

```yaml
branch_name:        feature/F-02-003-audit-gdpr-export
github_issue_id:    ""
pr_id:              ""
```

---

## Feature status tracker
<!-- Updated by the system after each milestone report is accepted. Never edited manually. -->

| feature_id | title | milestone | status | branch | validator_result |
|---|---|---|---|---|---|
| F-01-001 | Concessionaire SSO Integration | M-01 | passed| | |
| F-01-002 | Spending Dashboard API | M-01 | pending | | |
| F-01-003 | Voluntary Deposit Limit Setup | M-01 | pending | | |
| F-02-001 | Spending Alert Notifications | M-02 | pending | | |
| F-02-002 | Reflection Pause | M-02 | pending | | |
| F-02-003 | Admin Audit Log & GDPR Data Export | M-02 | pending | | |

<!-- status values: pending | in_progress | blocked | passed | failed | skipped -->

---

## Amendments

| Version | Date | Changed by | Summary |
|---|---|---|---|
| 1.0 | 2026-05-31 | CTO orchestrator | Initial — generated from doc0 ProtegoPay pilot brief |
