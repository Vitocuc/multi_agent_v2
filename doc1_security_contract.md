# Security contract
<!-- Doc 1 — produced by the CTO orchestrator after shared_plan_approved = true.
     Workers MUST read this file before implementing any feature.
     Validators check each feature against the fields marked [ENFORCED].
     Do not edit after approval without bumping contract_version. -->

---

## Meta

| Field | Value |
|---|---|
| project_id | proj-protegopay-pilot-001 |
| contract_version | 1.0 |
| created_at | 2026-05-31 |
| approved_by | CTO orchestrator |
| status | approved |

---

## Threat model

### Actors

| Actor | Trust level | Description |
|---|---|---|
| End user (gamer) | low | Authenticated via concessionaire SSO; can only access their own data |
| Concessionaire admin | medium | Operator staff; can view anonymised aggregates and operational metrics |
| ProtegoPay platform admin | high | Internal team; access to system configuration only, no raw user data |
| Concessionaire IdP | medium | External OIDC provider; trusted for identity assertion, not for authorisation decisions |
| Antifraud signal provider (SEON / Sportradar) | medium | External API; receives minimal signals, never receives raw PII or session data |
| Unauthenticated internet | none | No access to any endpoint beyond the public OIDC callback |
| CI/CD pipeline | medium | GitHub Actions; deploy rights scoped to staging/prod with environment gate |

### Attack vectors

| Vector | Risk level | Mitigation |
|---|---|---|
| OIDC token theft / session hijacking | critical | httpOnly short-lived JWT, token blacklist on logout, PKCE flow, HSTS |
| Insecure direct object reference (user sees another user's limits or dashboard) | critical | Ownership check on every data endpoint; user_id taken from JWT, never from request body |
| Profiling / inference attack (deducing vulnerability signals from aggregate data) | high | Minimum aggregation period enforced; no raw event data returned; k-anonymity floor on aggregate reports |
| GDPR data scraping via dashboard API | high | Rate limiting per token (60 req/min), pagination limits, export endpoint gated by explicit user consent |
| SQL injection via limit / alert configuration inputs | high | SQLAlchemy ORM parameterised queries only; Pydantic validation at boundary |
| Secrets leakage in logs or error responses | critical | Structured logging with PII scrubbing; errors return opaque codes to client |
| Dependency supply-chain compromise | medium | pip-audit in CI; pinned lock file; no transitive dependency upgrades without review |
| Concessionaire admin privilege escalation | high | RBAC enforced; admin routes on separate middleware; no admin JWT issued to end-user scope |
| False-positive injection via antifraud API | medium | Antifraud signals are advisory only; no automated action without human review; signal failures logged and alerted |
| CSRF on state-changing endpoints | medium | SameSite=Strict cookie attribute; CSRF token on non-idempotent endpoints if cookie auth is used |

---

## Authentication  [ENFORCED]

```yaml
mechanism:          OAuth2/OIDC — delegated to concessionaire's IdP (PKCE authorisation code flow)
token_location:     httpOnly, Secure, SameSite=Strict cookie for session JWT; Authorization header (Bearer) for machine-to-machine
token_expiry:       access: 15m, refresh: 7d (sliding), OIDC id_token: validated at session creation only
session_strategy:   stateless JWT for end-user sessions; token blacklist in Redis for revocation on logout
mfa_required:       false — MFA is the concessionaire IdP's responsibility; ProtegoPay enforces the OIDC flow, not the MFA method
logout_strategy:    JWT added to Redis blacklist (TTL = remaining token lifetime) + httpOnly cookie cleared + OIDC RP-initiated logout if IdP supports it
password_policy:    not applicable — no ProtegoPay-managed passwords in pilot; all credentials managed by concessionaire IdP
```

---

## Authorization  [ENFORCED]

```yaml
model:              RBAC with three roles
roles:
  user:             read and write own dashboard, limits, alerts, and pauses; no access to other users' data
  concessionaire_admin: read anonymised aggregates and operational metrics; cannot read individual user data; cannot modify system config
  protegopay_admin: read/write system configuration; no access to raw user data; audit log access only
ownership_check:    true — user_id is always taken from the validated JWT claim, never from the request body or path parameter alone
admin_separation:   true — concessionaire_admin and protegopay_admin routes are on a separate router with independent middleware; no JWT issued in user scope grants admin access
```

---

## Data security  [ENFORCED]

```yaml
at_rest:
  encryption:       AES-256 via AWS RDS storage encryption (provider-managed keys, KMS)
  pii_fields:
    - user_id_external     # opaque identifier received from concessionaire IdP — tokenised to internal UUID on first session
    - session_events       # gaming session references — pseudonymised, not stored raw
    - spending_amounts     # stored as integer minor currency units (eurocents); never as float
    - limit_settings       # user's voluntary deposit limits
    - alert_thresholds     # user-configured alert values
    - pause_records        # voluntary reflection-pause history
  pii_strategy:     tokenisation — external user_id mapped to internal UUID; spending amounts stored as integers; no raw behavioral event logs stored

in_transit:
  tls_minimum:      TLS 1.3 (TLS 1.2 fallback allowed only for legacy concessionaire integration endpoints, with explicit approval)
  hsts:             true — max-age=63072000; includeSubDomains; preload
  certificate:      AWS ACM (prod), Let's Encrypt (dev)

secrets_management:
  tool:             AWS Secrets Manager (prod and staging), .env file (local dev only, gitignored)
  never_in_code:    true — no secrets hardcoded, ever, including in tests
  rotation_policy:  90 days for API keys; immediately on suspected breach; OIDC client_secret rotation coordinated with concessionaire IdP
```

---

## Input validation  [ENFORCED]

```yaml
strategy:           Pydantic v2 schema validation on all API endpoints; validation runs before any business logic or database access
sanitization:       SQLAlchemy ORM parameterised queries only — no raw SQL string construction; all string fields have explicit max_length; HTML stripped from any free-text fields
file_uploads:       not applicable in pilot — no file upload endpoints; if added in future, requires separate security review
```

---

## Rate limiting  [ENFORCED]

```yaml
global:             100 req/min per IP address (sliding window)
auth_endpoints:     5 failed attempts per 15 min per IP, then 15-min lockout; success resets counter
api_endpoints:      60 req/min per OAuth session token (sliding window)
strategy:           sliding window
store:              Redis (AWS ElastiCache, single-region, with in-memory fallback that fails closed — rejects requests if Redis is unavailable)
```

---

## Audit logging  [ENFORCED]

```yaml
log_events:
  - auth_success           # OIDC session established — log user_id (internal UUID) and timestamp only
  - auth_failure           # OIDC validation failed — log reason code, not raw token
  - session_logout         # user or system terminated session
  - privilege_escalation   # any attempt to access a resource outside the caller's role
  - data_access            # dashboard API called — log user_id and period, not amounts
  - limit_change           # voluntary limit created, updated, or deleted
  - alert_config_change    # alert threshold created, updated, or deleted
  - pause_start            # reflection pause activated
  - pause_end              # reflection pause deactivated or expired
  - admin_action           # any concessionaire_admin or protegopay_admin operation
  - config_change          # system configuration updated
  - gdpr_data_export       # user requested or received a data export (GDPR Art. 20)
  - rate_limit_hit         # request rejected due to rate limit
log_format:         structured JSON — fields: timestamp (ISO 8601 UTC), event_type, user_id (internal UUID or null), request_id, outcome, metadata (event-specific, no PII)
log_destination:    stdout → AWS CloudWatch Logs (via log driver) → CloudWatch Log Group per environment
retention:          90 days in CloudWatch; then archived to S3 (Intelligent-Tiering) for 2 years to meet audit and GDPR accountability requirements
pii_in_logs:        false — amounts, limit values, and alert thresholds must not appear in log lines; user_id logged as internal UUID only
```

---

## Dependency policy

```yaml
lock_file_required: true — poetry.lock committed and checked in CI; pip install must not run without it
audit_on_install:   true — pip-audit runs in CI on every PR; HIGH and CRITICAL CVEs block merge
allowed_licenses:   [MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, PSF-2.0, ISC]
disallowed_licenses: [GPL-2.0, GPL-3.0, LGPL-2.1, AGPL-3.0] — copyleft licenses incompatible with B2B SaaS distribution
```

---

## Security checklist (worker self-check before milestone report)

Workers MUST confirm each item before marking a feature done:

- [ ] No secrets or credentials in source code, test fixtures, or logs
- [ ] All inputs validated and sanitized via Pydantic schema at the API boundary
- [ ] Auth enforced on every protected route — user_id taken from JWT, never from request
- [ ] Ownership check applied — user cannot access another user's resources
- [ ] Rate limiting applied on public-facing and auth endpoints
- [ ] PII fields handled per data security policy — no amounts or raw identifiers in logs
- [ ] Dependencies audited via pip-audit — no HIGH or CRITICAL CVEs unresolved
- [ ] Error messages return opaque codes to client — no stack traces, internal paths, or DB errors exposed
- [ ] Audit log events emitted for all relevant actions in this feature
- [ ] OIDC token validation includes signature check against concessionaire JWKS endpoint
- [ ] Redis-backed token blacklist consulted on every protected request (not just on logout)
- [ ] GDPR data minimisation applied — only data strictly necessary for the feature is stored

---

## Amendments

| Version | Date | Changed by | Summary |
|---|---|---|---|
| 1.0 | 2026-05-31 | CTO orchestrator | Initial — generated from doc0 ProtegoPay pilot brief |
