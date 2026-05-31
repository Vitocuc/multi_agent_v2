#!/usr/bin/env python3
"""
validator.py — runs the Gemini validation pass for a completed feature.

Reads:
  doc3_validation_contract.md   — the test suite for this feature
  reports/{feature_id}_milestone.md — the worker's milestone report

Calls:
  Gemini API (gemini-2.5-flash) — different provider from Claude Code worker

Writes:
  reports/{feature_id}_milestone.md — fills in the validator_result section
  GitHub PR status check            — via gh CLI (optional, skipped if gh not available)

Usage:
  python validator.py F-01-002
  python validator.py F-01-002 --dry-run   # print prompt, skip API call
  python validator.py F-01-002 --no-gh     # skip GitHub status posting

Environment:
  GEMINI_API_KEY   required
"""

import sys
import os
import re
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def load_env():
    """
    Load .env from the repo root into os.environ.
    Uses python-dotenv if installed; silently skips if not.
    Shell environment variables always take precedence over .env values.
    """
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
    except ImportError:
        _parse_env_file(env_path)


def _parse_env_file(path):
    """Minimal .env parser — handles KEY=value and KEY="value", skips comments."""
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


load_env()

ROOT        = Path(__file__).parent
DOC3        = ROOT / "doc3_validation_contract.md"
REPORTS_DIR = ROOT / "reports"

GEMINI_MODEL   = "gemini-2.5-flash"    # swap to gemini-3.1-pro or gemini-3.5-flash when ready
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
DIM    = "\033[2m"
CYAN   = "\033[36m"

def c(colour, text):
    return f"{colour}{text}{RESET}"


# ---------------------------------------------------------------------------
# doc3 parser — extract the test suite for a given feature_id
# ---------------------------------------------------------------------------

def extract_test_suite(feature_id):
    """
    Returns the raw markdown block for this feature's test suite,
    plus the global security tests that always run.
    Returns (suite_block: str, global_tests: str)
    """
    if not DOC3.exists():
        die("doc3_validation_contract.md not found.")

    text = DOC3.read_text()

    # Feature suite block — everything between ### Suite F-XX-XXX and the next ### or ##
    suite_match = re.search(
        rf"### Suite {re.escape(feature_id)}.*?\n(.*?)(?=\n###|\n##|\Z)",
        text,
        re.DOTALL,
    )
    suite_block = suite_match.group(1).strip() if suite_match else ""

    # Global security tests block
    global_match = re.search(
        r"## Cross-feature security tests\s*```yaml\n(.*?)```",
        text,
        re.DOTALL,
    )
    global_tests = global_match.group(1).strip() if global_match else ""

    return suite_block, global_tests


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a strict, spec-driven validator in a software development pipeline.

Your job:
- Read a test suite definition (from the validation contract)
- Read a milestone report (filed by the worker agent who implemented the feature)
- Decide whether the evidence in the milestone report satisfies each test case

Rules you must follow:
1. You NEVER read source code. Your only inputs are the test suite and the milestone report.
2. Judge each test case against the milestone report's evidence — implemented table,
   commands_run, security_checklist_followed, issues_discovered, left_undone.
3. A test PASSES if the milestone report provides clear evidence that the expected
   outcome was achieved. Absence of evidence is a FAIL, not a skip.
4. A test FAILS if the milestone report contradicts the expected outcome, or if
   evidence is missing, vague, or says "N/A" without explanation.
5. Security tests that fail are ALWAYS added to the escalations list, even if
   they are marked blocking: false.
6. security_checklist_followed: false is an automatic escalation — add SEC-GLOBAL-02 to failures.
7. You output ONLY the validator_result YAML block. No preamble. No explanation outside the YAML.
   Do not wrap in markdown fences. Output raw YAML only.

Output format (fill every field):

validator_run:
  suite_id:         ""
  run_at:           ""
  provider:         "gemini"
  model_version:    "{model}"
  overall:          pass | fail
  blocking_passed:  true | false

  results:
    - test_id:  ""
      status:   pass | fail | skip
      notes:    ""

  failures:     []
  escalations:  []
""".format(model=GEMINI_MODEL)


def build_validation_prompt(feature_id, suite_block, global_tests, milestone_text):
    return f"""## Feature under validation: {feature_id}

---

## Test suite (from doc3_validation_contract.md)

{suite_block}

---

## Global security tests (run for every feature)

```yaml
{global_tests}
```

---

## Milestone report (filed by the worker — your only evidence source)

{milestone_text}

---

Validate each test case in the suite above against the milestone report.
Then validate the three global security tests.
Output the validator_run YAML block and nothing else.
"""


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------

def call_gemini(prompt, dry_run=False):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        die(
            "GEMINI_API_KEY environment variable is not set.\n"
            "  Export it before running: export GEMINI_API_KEY=your_key_here"
        )

    if dry_run:
        print(c(YELLOW, "\n── DRY RUN: prompt that would be sent to Gemini ──\n"))
        print(c(DIM, SYSTEM_PROMPT))
        print(c(DIM, "─" * 60))
        print(prompt)
        return None

    try:
        import urllib.request
        import urllib.error
    except ImportError:
        die("urllib not available — this should never happen with standard Python.")

    payload = json.dumps({
        "system_instruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature":     0.1,   # low temperature — we want deterministic validation
            "maxOutputTokens": 2048,
        },
    }).encode("utf-8")

    url = f"{GEMINI_API_URL}?key={api_key}"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        die(f"Gemini API error {e.code}: {body}")
    except urllib.error.URLError as e:
        die(f"Network error calling Gemini: {e.reason}")

    # Extract text from response
    try:
        text = raw["candidates"][0]["content"]["parts"][0]["text"]
        return text.strip()
    except (KeyError, IndexError) as e:
        die(f"Unexpected Gemini response shape: {e}\nRaw: {json.dumps(raw)[:500]}")


# ---------------------------------------------------------------------------
# Result parser — parse Gemini's YAML output
# ---------------------------------------------------------------------------

def parse_validator_result(raw_yaml):
    """
    Parse the validator_run YAML block returned by Gemini.
    Returns a dict with the key fields we need to write back.
    Falls back gracefully if parsing fails.
    """
    result = {
        "suite_id":        "",
        "run_at":          datetime.now(timezone.utc).isoformat(),
        "provider":        "gemini",
        "model_version":   GEMINI_MODEL,
        "overall":         "fail",
        "blocking_passed": False,
        "results":         [],
        "failures":        [],
        "escalations":     [],
        "raw":             raw_yaml,
    }

    if not raw_yaml:
        return result

    # Strip any accidental markdown fences
    raw_yaml = re.sub(r"^```ya?ml\n?", "", raw_yaml.strip())
    raw_yaml = re.sub(r"\n?```$",     "", raw_yaml.strip())

    # overall
    m = re.search(r"overall:\s*(pass|fail)", raw_yaml)
    if m:
        result["overall"] = m.group(1)

    # blocking_passed
    m = re.search(r"blocking_passed:\s*(true|false)", raw_yaml)
    if m:
        result["blocking_passed"] = m.group(1) == "true"

    # suite_id
    m = re.search(r"suite_id:\s*\"?([^\"\\n]+)\"?", raw_yaml)
    if m:
        result["suite_id"] = m.group(1).strip()

    # failures list
    fail_match = re.search(r"failures:\s*\[(.*?)\]", raw_yaml, re.DOTALL)
    if fail_match:
        raw_list = fail_match.group(1)
        result["failures"] = [
            x.strip().strip('"').strip("'")
            for x in raw_list.split(",")
            if x.strip() and x.strip() not in ('', '[]')
        ]

    # escalations list
    esc_match = re.search(r"escalations:\s*\[(.*?)\]", raw_yaml, re.DOTALL)
    if esc_match:
        raw_list = esc_match.group(1)
        result["escalations"] = [
            x.strip().strip('"').strip("'")
            for x in raw_list.split(",")
            if x.strip() and x.strip() not in ('', '[]')
        ]

    # individual test results
    test_blocks = re.findall(
        r"- test_id:\s*\"?([^\"\\n]+)\"?.*?status:\s*(pass|fail|skip).*?notes:\s*\"?(.*?)\"?\n",
        raw_yaml,
        re.DOTALL,
    )
    for tid, status, notes in test_blocks:
        result["results"].append({
            "test_id": tid.strip(),
            "status":  status.strip(),
            "notes":   notes.strip(),
        })

    return result


# ---------------------------------------------------------------------------
# Write result back into the milestone report
# ---------------------------------------------------------------------------

def write_result_to_report(report_path, result):
    """
    Replaces the validator_result section in the milestone report with
    the actual result. The section is identified by the YAML fence under
    ## Validator result.
    """
    text = report_path.read_text()
    now  = result.get("run_at", datetime.now(timezone.utc).isoformat())

    failures_yaml    = format_yaml_list(result.get("failures",    []))
    escalations_yaml = format_yaml_list(result.get("escalations", []))

    new_block = f"""```yaml
validator_result:
  run_at:           "{now}"
  provider:         "{result.get('provider', 'gemini')}"
  model_version:    "{result.get('model_version', GEMINI_MODEL)}"
  overall:          {result.get('overall', 'fail')}
  blocking_passed:  {str(result.get('blocking_passed', False)).lower()}
  human_gate:       pending
  failures:         {failures_yaml}
  escalations:      {escalations_yaml}
```"""

    # Replace the existing validator_result yaml fence in the Validator result section
    new_text = re.sub(
        r"(## Validator result.*?```yaml\n).*?(```)",
        lambda m: m.group(1).rstrip() + "\n" + new_block[7:],  # skip leading ```yaml\n
        text,
        flags=re.DOTALL,
        count=1,
    )

    # Fallback: if the section wasn't matched, append it
    if new_text == text:
        new_text = text + f"\n\n## Validator result\n\n{new_block}\n"

    report_path.write_text(new_text)


def format_yaml_list(items):
    if not items:
        return "[]"
    quoted = [f'"{item}"' for item in items]
    return "[" + ", ".join(quoted) + "]"


# ---------------------------------------------------------------------------
# GitHub PR status posting (optional)
# ---------------------------------------------------------------------------

def post_github_status(feature_id, overall, escalations, no_gh=False):
    """Post a commit status to the PR via gh CLI. Skips gracefully if gh unavailable."""
    if no_gh:
        print(c(DIM, "  GitHub status posting skipped (--no-gh)."))
        return

    # Check gh is available
    check = subprocess.run(["which", "gh"], capture_output=True)
    if check.returncode != 0:
        print(c(DIM, "  gh CLI not found — skipping GitHub status. Install with: brew install gh"))
        return

    # Get current commit SHA for the feature branch
    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=ROOT
    )
    if sha_result.returncode != 0:
        print(c(YELLOW, "  Could not get commit SHA — skipping GitHub status."))
        return

    sha   = sha_result.stdout.strip()
    state = "success" if overall == "pass" else "failure"
    desc  = (
        "All tests passed" if overall == "pass"
        else f"Failed: {', '.join(escalations[:3]) if escalations else 'see milestone report'}"
    )

    result = subprocess.run(
        [
            "gh", "api",
            f"repos/{{owner}}/{{repo}}/statuses/{sha}",
            "--method", "POST",
            "--field", f"state={state}",
            "--field", f"description={desc[:139]}",  # GitHub limit: 140 chars
            "--field", "context=orchestrator/validator",
        ],
        capture_output=True, text=True, cwd=ROOT
    )

    if result.returncode == 0:
        print(c(DIM, f"  GitHub status posted: {state}"))
    else:
        print(c(YELLOW, f"  GitHub status post failed: {result.stderr.strip()}"))
        print(c(DIM,    "  You can post manually or set up branch protection rules."))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args     = sys.argv[1:]
    dry_run  = "--dry-run" in args
    no_gh    = "--no-gh"   in args
    args     = [a for a in args if not a.startswith("--")]

    if not args:
        print(__doc__)
        sys.exit(0)

    feature_id  = args[0].upper()
    report_path = REPORTS_DIR / f"{feature_id}_milestone.md"

    print(c(BOLD, f"\n── Validator: {feature_id} ──────────────────────────\n"))

    # 1. Load inputs
    if not report_path.exists():
        die(f"Milestone report not found: {report_path}")

    milestone_text = report_path.read_text()
    suite_block, global_tests = extract_test_suite(feature_id)

    if not suite_block:
        print(c(YELLOW, f"  ⚠ No test suite found in doc3 for {feature_id}."))
        print(c(DIM,    "  Only global security tests will run.\n"))

    # 2. Build prompt and call Gemini
    prompt = build_validation_prompt(feature_id, suite_block, global_tests, milestone_text)
    print(f"  Calling {c(CYAN, GEMINI_MODEL)}...")

    raw_yaml = call_gemini(prompt, dry_run=dry_run)

    if dry_run:
        print(c(YELLOW, "\n── Dry run complete. No files written. ──\n"))
        return

    if not raw_yaml:
        die("Gemini returned an empty response.")

    print(c(DIM, "  Response received.\n"))

    # 3. Parse result
    result = parse_validator_result(raw_yaml)

    # 4. Print summary
    overall  = result.get("overall", "fail")
    failures = result.get("failures",    [])
    escalations = result.get("escalations", [])

    if overall == "pass":
        print(c(GREEN, f"  ✓ PASS — all blocking tests satisfied"))
    else:
        print(c(RED, f"  ✗ FAIL"))
        if failures:
            for f in failures:
                print(c(RED, f"    · {f}"))

    if escalations:
        print(c(RED, f"\n  ⚠ Security escalations:"))
        for e in escalations:
            print(c(RED, f"    · {e}"))

    if result.get("results"):
        print(c(DIM, "\n  Per-test results:"))
        for r in result["results"]:
            icon = {"pass": "✓", "fail": "✗", "skip": "–"}.get(r["status"], "?")
            colour = GREEN if r["status"] == "pass" else (RED if r["status"] == "fail" else DIM)
            notes = f" — {r['notes']}" if r.get("notes") else ""
            print(c(colour, f"    {icon} {r['test_id']}{notes}"))

    print()

    # 5. Write result into milestone report
    write_result_to_report(report_path, result)
    print(c(DIM, f"  Validator result written to {report_path.name}"))

    # 6. Post GitHub status
    post_github_status(feature_id, overall, escalations, no_gh=no_gh)

    print()


def die(msg):
    print(c(RED, f"\n✗ {msg}\n"), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
