# Security rules

These rules extend `doc1_security_contract.md` with implementation-level guidance.
They apply to every file you touch, not just files explicitly about security.

## Secrets

Never hardcode secrets. If a value is secret, it comes from environment variables.

```python
# Wrong
API_KEY = "sk-abc123"

# Right
API_KEY = os.environ["API_KEY"]
```

If the project has no `.env.example` file yet, create one with placeholder values
and add `.env` to `.gitignore` before your first commit.

## Authentication checks

Every route or endpoint that handles user data must verify identity before doing anything else.
Put auth checks at the top of the handler, not after loading data.

```python
# Wrong — loads data before checking auth
def get_user_profile(user_id):
    profile = db.get(user_id)
    if not current_user.is_authenticated:
        return 403

# Right — auth first
def get_user_profile(user_id):
    if not current_user.is_authenticated:
        return 403
    profile = db.get(user_id)
```

## Input validation

Validate at the boundary — the moment data enters the system from outside.
Never trust data from: HTTP requests, query params, headers, file uploads, env vars
that come from user-controlled sources, or inter-service messages.

Use the schema validation library already in the project (zod, pydantic, joi, etc.).
If none exists, note it in `issues_discovered` and use basic type + length checks minimum.

## Error responses

Errors returned to clients must never contain:
- Stack traces
- Internal file paths
- Database error messages
- Query strings
- Environment variable names or values

```python
# Wrong
except Exception as e:
    return {"error": str(e), "trace": traceback.format_exc()}

# Right
except Exception as e:
    logger.error("Internal error", exc_info=True)  # full detail in logs only
    return {"error": "An internal error occurred"}, 500
```

## Logging

Log security-relevant events: auth success, auth failure, privilege checks, data access.
Never log: passwords, tokens, full credit card numbers, raw PII fields.

## Dependency audit

After `npm audit` or `pip-audit`, if high or critical CVEs appear:
- Fix them if a patched version exists
- If no fix exists, document in `issues_discovered` with severity: high
- Never suppress audit output or ignore it
