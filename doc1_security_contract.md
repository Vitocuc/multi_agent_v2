# Security contract
<!-- Doc 1 — produced by the CTO orchestrator after shared_plan_approved = true.
     Workers MUST read this file before implementing any feature.
     Validators check each feature against the fields marked [ENFORCED].
     Do not edit after approval without bumping contract_version. -->

---

## Meta

| Field | Value |
|---|---|
| project_id | |
| contract_version | 1.0 |
| created_at | |
| approved_by | CTO orchestrator |
| status | draft \| approved \| superseded |

---

## Threat model

### Actors

| Actor | Trust level | Description |
|---|---|---|
| Anonymous user | none | Unauthenticated public internet |
| Authenticated user | low | Verified identity, limited privileges |
| Admin | high | Internal operator with elevated access |
| Third-party service | medium | External APIs called by the system |
| CI/CD pipeline | medium | Automated system with deploy rights |

### Attack vectors

| Vector | Risk level | Mitigation |
|---|---|---|
| SQL / NoSQL injection | high | |
| XSS | high | |
| CSRF | medium | |
| Broken auth / session hijack | high | |
| Secrets in source code | critical | |
| Dependency vulnerabilities | medium | |
| Rate limit abuse | medium | |
| Insecure direct object reference | high | |

<!-- Add project-specific vectors below -->

---

## Authentication  [ENFORCED]

```yaml
mechanism:          # e.g. JWT, session cookie, OAuth2, API key
token_location:     # e.g. httpOnly cookie, Authorization header
token_expiry:       # e.g. access: 15m, refresh: 7d
session_strategy:   # e.g. stateless JWT, server-side session store
mfa_required:       # true | false | optional
logout_strategy:    # e.g. token blacklist, cookie clear, session destroy
password_policy:    # min_length, complexity, bcrypt_rounds
```

---

## Authorization  [ENFORCED]

```yaml
model:              # e.g. RBAC, ABAC, flat permissions
roles:              # list of roles and their allowed actions
ownership_check:    # true | false — users can only access their own resources
admin_separation:   # true | false — admin routes on separate middleware
```

---

## Data security  [ENFORCED]

```yaml
at_rest:
  encryption:       # e.g. AES-256, provider-managed (RDS encryption)
  pii_fields:       # list fields that contain PII
  pii_strategy:     # e.g. encrypted columns, tokenization, not stored

in_transit:
  tls_minimum:      # e.g. TLS 1.2
  hsts:             # true | false
  certificate:      # e.g. Let's Encrypt, provider-managed

secrets_management:
  tool:             # e.g. .env (dev only), Vault, AWS Secrets Manager, GitHub Secrets
  never_in_code:    # true — no secrets hardcoded, ever
  rotation_policy:  # e.g. 90 days, on breach
```

---

## Input validation  [ENFORCED]

```yaml
strategy:           # e.g. schema validation on all endpoints (zod, joi, pydantic)
sanitization:       # e.g. strip HTML, parameterized queries only
file_uploads:       # allowed_types, max_size, scan_for_malware
```

---

## Rate limiting  [ENFORCED]

```yaml
global:             # e.g. 100 req/min per IP
auth_endpoints:     # e.g. 5 attempts / 15 min, then lockout
api_endpoints:      # e.g. 60 req/min per token
strategy:           # e.g. token bucket, sliding window
store:              # e.g. Redis, in-memory (single instance only)
```

---

## Audit logging  [ENFORCED]

```yaml
log_events:
  - auth_success
  - auth_failure
  - privilege_escalation
  - data_export
  - admin_action
  - config_change
log_format:         # e.g. structured JSON
log_destination:    # e.g. stdout → aggregator, CloudWatch, Datadog
retention:          # e.g. 90 days
pii_in_logs:        # false — never log PII in plaintext
```

---

## Dependency policy

```yaml
lock_file_required: true        # package-lock.json / poetry.lock committed
audit_on_install:   true        # npm audit / pip-audit run in CI
allowed_licenses:   []          # e.g. MIT, Apache-2.0, BSD
disallowed_licenses: []         # e.g. GPL (if distributing)
```

---

## Security checklist (worker self-check before milestone report)

Workers MUST confirm each item before marking a feature done:

- [ ] No secrets or credentials in source code or logs
- [ ] All inputs validated and sanitized
- [ ] Auth and authorization applied on every protected route
- [ ] Rate limiting in place on public-facing endpoints
- [ ] PII fields handled per data security policy
- [ ] Dependencies audited (no high/critical CVEs unresolved)
- [ ] Error messages do not leak internal stack traces to clients
- [ ] Audit log events emitted for relevant actions

---

## Amendments

<!-- Record any post-approval changes here. Each amendment bumps contract_version. -->

| Version | Date | Changed by | Summary |
|---|---|---|---|
| 1.0 | | CTO orchestrator | Initial |
