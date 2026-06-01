#!/usr/bin/env python3
"""
orchestrator.py — pipeline coordinator for the AI development workflow.

Commands:
  next              Read doc2 DAG, find the next ready feature, print the
                    worker prompt pre-filled with context. You paste it into
                    Claude Code.

  post <feature_id> Run after Claude Code files the milestone report.
                    Extracts memory, updates doc2 status tracker, then calls
                    validator.py to run the Gemini validation pass.

  status            Print the current feature board — what is pending, in
                    progress, blocked, passed, or failed.

  memory <feature_id>
                    Print the filtered memory.json context for a feature.
                    Useful for debugging what a worker will see.

Usage:
  python orchestrator.py next
  python orchestrator.py post F-01-002
  python orchestrator.py status
  python orchestrator.py memory F-01-002
"""

import sys
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import os


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

# ---------------------------------------------------------------------------
# Paths — all relative to the repo root where this script lives
# ---------------------------------------------------------------------------

ROOT        = Path(__file__).parent
DOC2        = ROOT / "doc2_features_contract.md"
DOC3        = ROOT / "doc3_validation_contract.md"
DOC4_TPL    = ROOT / "doc4_milestone_report.md"
MEMORY      = ROOT / "memory.json"
REPORTS_DIR = ROOT / "reports"
PROMPTS_DIR = ROOT / "prompts"

REPORTS_DIR.mkdir(exist_ok=True)
PROMPTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Colours for terminal output (degrade gracefully if not supported)
# ---------------------------------------------------------------------------

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
DIM    = "\033[2m"

def c(colour, text):
    return f"{colour}{text}{RESET}"


# ---------------------------------------------------------------------------
# doc2 parser
# Parses feature blocks and status tracker from the markdown file.
# The format is intentionally simple — YAML fenced blocks inside markdown.
# ---------------------------------------------------------------------------

def parse_doc2():
    """
    Returns:
      features: dict[feature_id -> dict]  — all feature block metadata
      status:   dict[feature_id -> dict]  — tracker rows
    """
    if not DOC2.exists():
        die(f"doc2_features_contract.md not found at {DOC2}")

    text = DOC2.read_text()

    features = {}
    status   = {}

    # --- Parse feature YAML blocks ---
    # Each feature block starts with ### F-XX-XXX and contains a ```yaml block
    feature_sections = re.findall(
        r"###\s+(F-\d+-\d+)\s+—[^\n]*\n(.*?)(?=\n###|\Z)",
        text,
        re.DOTALL,
    )

    for feature_id, body in feature_sections:
        yaml_match = re.search(r"```yaml\n(.*?)```", body, re.DOTALL)
        if not yaml_match:
            continue
        meta = parse_inline_yaml(yaml_match.group(1))
        meta["feature_id"] = feature_id
        meta["_raw_block"] = body.strip()
        features[feature_id] = meta

    # --- Parse status tracker table ---
    tracker_match = re.search(
        r"## Feature status tracker.*?\n(\|.*?\|.*?\n)+",
        text,
        re.DOTALL,
    )
    if tracker_match:
        rows = re.findall(
            r"^\|\s*(F-\d+-\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|",
            tracker_match.group(0),
            re.MULTILINE,
        )
        for row in rows:
            fid, title, milestone, stat, branch, val_result = row
            status[fid] = {
                "feature_id":       fid,
                "title":            title,
                "milestone":        milestone,
                "status":           stat.strip() or "pending",
                "branch":           branch.strip(),
                "validator_result": val_result.strip(),
            }

    return features, status


def parse_inline_yaml(text):
    """
    Minimal YAML parser for the simple key: value pairs in feature blocks.
    Handles: strings, booleans, lists ([] or [item, item]), bare words.
    Not a full YAML parser — just enough for our schema.
    """
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        # Strip inline comments
        raw = raw.split("#")[0].strip()
        # Remove surrounding quotes
        val = raw.strip('"').strip("'")

        # Boolean
        if val.lower() == "true":
            result[key] = True
        elif val.lower() == "false":
            result[key] = False
        # Empty list
        elif val == "[]":
            result[key] = []
        # Inline list  [a, b, c]
        elif val.startswith("[") and val.endswith("]"):
            inner = val[1:-1]
            result[key] = [x.strip().strip('"') for x in inner.split(",") if x.strip()]
        elif val == "":
            result[key] = None
        else:
            result[key] = val

    return result


# ---------------------------------------------------------------------------
# memory.json helpers
# ---------------------------------------------------------------------------

def load_memory():
    if not MEMORY.exists():
        die("memory.json not found. Run from repo root.")
    try:
        return json.loads(MEMORY.read_text())
    except json.JSONDecodeError as e:
        die(f"memory.json is malformed: {e}")


def save_memory(mem):
    MEMORY.write_text(json.dumps(mem, indent=2, ensure_ascii=False))


def filter_memory(feature_id, features):
    """
    Return a filtered subset of memory.json relevant to this feature.
    Rules (from memory.json _meta.filter_rules):
      - architecture_decisions: where feature_id is in depends_on chain
      - failed_approaches:      ALL entries always
      - discovered_constraints: where affects_features overlaps with feature_id
      - open_risks:             high/critical severity OR blocks this feature
    """
    mem = load_memory()
    feature = features.get(feature_id, {})
    depends_chain = build_depends_chain(feature_id, features)

    def is_example(entry):
        return "_comment" in entry

    # Architecture decisions: relevant if the decision came from a feature
    # in this feature's dependency chain
    arch = [
        e for e in mem.get("architecture_decisions", [])
        if not is_example(e) and e.get("feature_id") in depends_chain
    ]

    # Failed approaches: always inject all real entries
    failed = [
        e for e in mem.get("failed_approaches", [])
        if not is_example(e)
    ]

    # Discovered constraints: affects_features overlaps with this feature_id
    constraints = [
        e for e in mem.get("discovered_constraints", [])
        if not is_example(e) and (
            feature_id in e.get("affects_features", [])
            or not e.get("affects_features")  # global constraints
        )
    ]

    # Open risks: high/critical OR blocking this feature
    risks = [
        e for e in mem.get("open_risks", [])
        if not is_example(e) and (
            e.get("severity") in ("high", "critical")
            or feature_id in e.get("blocking_features", [])
        )
    ]

    return {
        "architecture_decisions":  arch,
        "failed_approaches":       failed,
        "discovered_constraints":  constraints,
        "open_risks":              risks,
    }


def build_depends_chain(feature_id, features, _visited=None):
    """Walk depends_on recursively and return all ancestor feature_ids."""
    if _visited is None:
        _visited = set()
    if feature_id in _visited:
        return _visited
    _visited.add(feature_id)
    for dep in features.get(feature_id, {}).get("depends_on", []):
        build_depends_chain(dep, features, _visited)
    return _visited


# ---------------------------------------------------------------------------
# DAG resolver
# ---------------------------------------------------------------------------

def ready_features(features, status):
    """
    Return list of feature_ids that are ready to start:
      - status is 'pending' (not in_progress / blocked / passed / failed)
      - all depends_on are 'passed'
    """
    passed = {fid for fid, row in status.items() if row["status"] == "passed"}
    ready  = []
    for fid, meta in features.items():
        row = status.get(fid, {})
        current_status = row.get("status", "pending")
        if current_status != "pending":
            continue
        deps = meta.get("depends_on", []) or []
        if all(dep in passed for dep in deps):
            ready.append(fid)
    return ready


# ---------------------------------------------------------------------------
# Milestone report parser
# Reads a filled doc4 and extracts structured data for memory extraction.
# ---------------------------------------------------------------------------

def parse_milestone_report(report_path):
    """
    Parse a filled milestone report and return a dict with the key fields.
    Returns None if the file doesn't exist or identity block is missing.
    """
    if not report_path.exists():
        return None

    text = report_path.read_text()
    result = {}

    # Identity YAML block
    id_match = re.search(r"## Identity\s*```yaml\n(.*?)```", text, re.DOTALL)
    if id_match:
        result.update(parse_inline_yaml(id_match.group(1)))

    # security_checklist_followed
    sec_match = re.search(r"security_checklist_followed:\s*(true|false)", text)
    result["security_checklist_followed"] = (
        sec_match.group(1).lower() == "true" if sec_match else False
    )

    sec_notes_match = re.search(r"security_checklist_notes:\s*\"?(.*?)\"?\n", text)
    result["security_checklist_notes"] = (
        sec_notes_match.group(1).strip() if sec_notes_match else ""
    )

    # procedures_followed
    proc_match = re.search(r"procedures_followed:\s*(true|false)", text)
    result["procedures_followed"] = (
        proc_match.group(1).lower() == "true" if proc_match else False
    )

    # Issues block
    issues_match = re.search(r"## Issues discovered\s*```yaml\n(.*?)```", text, re.DOTALL)
    result["issues_raw"] = issues_match.group(1).strip() if issues_match else ""
    result["issues"] = parse_issues(result["issues_raw"])

    # Commands block
    cmds_match = re.search(r"## Commands run\s*```yaml\n(.*?)```", text, re.DOTALL)
    result["commands_raw"] = cmds_match.group(1).strip() if cmds_match else ""

    # left_undone section
    undone_match = re.search(
        r"## What was left undone(.*?)(?=\n## )", text, re.DOTALL
    )
    result["left_undone_raw"] = undone_match.group(1).strip() if undone_match else ""
    result["has_undone"] = (
        "none" not in result["left_undone_raw"].lower()
        and result["left_undone_raw"] != ""
    )

    return result


def parse_issues(raw):
    """
    Parse the issues YAML block into a list of dicts.
    Each issue starts with '- issue_id:'.
    """
    issues = []
    blocks = re.split(r"(?=^\s*- issue_id:)", raw, flags=re.MULTILINE)
    for block in blocks:
        block = block.strip()
        if not block or "issue_id" not in block:
            continue
        issue = parse_inline_yaml(
            block.replace("- issue_id:", "issue_id:")
        )
        if issue.get("issue_id"):
            issues.append(issue)
    return issues


# ---------------------------------------------------------------------------
# Memory extractor
# Reads a parsed milestone report and appends entries to memory.json.
# ---------------------------------------------------------------------------

def extract_to_memory(report, feature_id):
    """
    Extract structured memory entries from a milestone report.
    Appends to memory.json. Returns summary of what was added.
    """
    mem      = load_memory()
    now      = datetime.now(timezone.utc).isoformat()
    added    = {"architecture_decisions": [], "failed_approaches": [],
                "discovered_constraints": [], "open_risks": []}

    issues   = report.get("issues", [])

    for issue in issues:
        severity     = issue.get("severity", "low")
        resolution   = issue.get("resolution", "")
        do_not_retry = issue.get("do_not_retry", False)
        description  = issue.get("description", "")
        issue_id     = issue.get("issue_id", "")

        # Failed approaches: unresolved issues where do_not_retry is flagged,
        # or where a workaround was used (approach X failed, approach Y used)
        if resolution in ("unresolved", "workaround") or do_not_retry:
            entry_id = f"FA-{issue_id}"
            entry = {
                "entry_id":        entry_id,
                "feature_id":      feature_id,
                "timestamp":       now,
                "what_was_tried":  description,
                "why_it_failed":   issue.get("resolution_notes", ""),
                "exit_code_ref":   "",
                "do_not_retry":    bool(do_not_retry),
                "alternative_used": issue.get("resolution_notes", "") if resolution == "workaround" else "",
            }
            mem["failed_approaches"].append(entry)
            added["failed_approaches"].append(entry_id)

        # Open risks: high or critical unresolved issues
        if severity in ("high", "critical") and resolution == "unresolved":
            risk_id = f"OR-{issue_id}"
            entry = {
                "risk_id":           risk_id,
                "feature_id":        feature_id,
                "timestamp":         now,
                "severity":          severity,
                "description":       description,
                "mitigation_status": "open",
                "security_deviation": not report.get("security_checklist_followed", True),
                "blocking_features": [],
                "resolution_notes":  issue.get("resolution_notes", ""),
            }
            mem["open_risks"].append(entry)
            added["open_risks"].append(risk_id)

        # Discovered constraints: library or infra issues that affect other features
        if issue.get("source") in ("env", "api", "infra", "library"):
            constraint_id = f"DC-{issue_id}"
            entry = {
                "constraint_id":         constraint_id,
                "feature_id":            feature_id,
                "timestamp":             now,
                "source":                issue.get("source", "library"),
                "description":           description,
                "affects_features":      [],
                "contract_update_needed": severity in ("high", "critical"),
                "workaround":            issue.get("resolution_notes", ""),
            }
            mem["discovered_constraints"].append(entry)
            added["discovered_constraints"].append(constraint_id)

    # Security deviation as a standalone open risk
    if not report.get("security_checklist_followed", True):
        risk_id = f"OR-SEC-{feature_id}"
        notes   = report.get("security_checklist_notes", "No notes provided")
        entry = {
            "risk_id":           risk_id,
            "feature_id":        feature_id,
            "timestamp":         now,
            "severity":          "high",
            "description":       f"Security checklist not fully followed for {feature_id}. Notes: {notes}",
            "mitigation_status": "open",
            "security_deviation": True,
            "blocking_features": [],
            "resolution_notes":  notes,
        }
        mem["open_risks"].append(entry)
        added["open_risks"].append(risk_id)

    save_memory(mem)
    return added


# ---------------------------------------------------------------------------
# doc2 status tracker updater
# ---------------------------------------------------------------------------

def update_doc2_status(feature_id, new_status, validator_result="", branch=""):
    """Update the feature status tracker table in doc2_features_contract.md."""
    text = DOC2.read_text()

    # Match the exact row for this feature_id in the tracker table
    pattern = rf"(\|\s*{re.escape(feature_id)}\s*\|[^|]*\|[^|]*\|\s*)([^|]*)(\s*\|[^|]*\|[^|]*\|)"

    def replace_row(m):
        before = m.group(1)
        after  = m.group(3)
        return f"{before}{new_status}{after}"

    new_text, count = re.subn(pattern, replace_row, text)

    if count == 0:
        warn(f"Could not find feature {feature_id} in status tracker — update manually.")
        return

    DOC2.write_text(new_text)


# ---------------------------------------------------------------------------
# Worker prompt builder
# ---------------------------------------------------------------------------

def build_worker_prompt(feature_id, features, status):
    """
    Build the full context prompt to paste into Claude Code.
    Writes it to prompts/current_worker.md and also prints it.
    """
    feature = features.get(feature_id)
    if not feature:
        die(f"Feature {feature_id} not found in doc2.")

    filtered_mem = filter_memory(feature_id, features)
    mem_json     = json.dumps(filtered_mem, indent=2)
    feature_block = feature.get("_raw_block", "(feature block not parsed)")

    prompt = f"""# Worker context — {feature_id}

You are a worker agent. Read this entire prompt before doing anything.

## Your feature

{feature_block}

## Filtered memory (what previous workers learned)

```json
{mem_json}
```

## Instructions

1. Read `doc1_security_contract.md` in full before writing any code.
2. Read `CLAUDE.md` if you have not already — it contains your standing rules.
3. Implement the feature block above. Nothing more, nothing less.
4. When done, copy `doc4_milestone_report.md` to `reports/{feature_id}_milestone.md`
   and fill every field.
5. Open a PR with title `[{feature_id}] {feature.get("title", "")}`.
   Use the milestone report as the PR body.
6. Do not merge. Stop after opening the PR.

The filtered memory above shows you what past workers discovered.
Pay special attention to `failed_approaches` — do not repeat them.
"""

    out_path = PROMPTS_DIR / "current_worker.md"
    out_path.write_text(prompt)
    return prompt


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_next():
    features, status = parse_doc2()
    ready = ready_features(features, status)

    if not ready:
        # Check if everything is done
        all_passed = all(
            row["status"] == "passed"
            for row in status.values()
        )
        if all_passed:
            print(c(GREEN, "\n✓ All features passed. Project complete.\n"))
        else:
            blocked = [
                fid for fid, row in status.items()
                if row["status"] not in ("passed", "failed", "skipped")
            ]
            print(c(YELLOW, "\n⚠ No features are ready to start."))
            if blocked:
                print(f"  Blocked or in-progress: {', '.join(blocked)}")
            print("  Check status with: python orchestrator.py status\n")
        return

    # Pick highest-priority ready feature
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ready.sort(key=lambda fid: priority_order.get(
        features[fid].get("priority", "medium"), 2
    ))

    feature_id = ready[0]
    feature    = features[feature_id]
    raw_title  = feature.get("title") or ""
    title      = (raw_title.strip('"') if isinstance(raw_title, str) else "") or "(untitled)"

    print(c(BOLD, f"\n→ Next feature: {feature_id} — {title}"))
    print(c(DIM,  f"  Priority: {feature.get('priority', '?')}  "
                  f"Complexity: {feature.get('complexity', '?')}  "
                  f"Milestone: {feature.get('milestone_id', '?')}"))

    if len(ready) > 1:
        others = ["{} ({})".format(fid, features[fid].get('title', '').strip('"'))
                  for fid in ready[1:]]
        print(c(DIM, f"  Also ready: {', '.join(others)}"))

    prompt = build_worker_prompt(feature_id, features, status)

    print(f"\n  Worker prompt written to: {c(CYAN, 'prompts/current_worker.md')}")
    print(c(DIM, "  Paste that file's contents into Claude Code to start the worker.\n"))

    # Mark as in_progress in tracker
    update_doc2_status(feature_id, "in_progress")
    print(c(DIM, f"  Status tracker updated: {feature_id} → in_progress\n"))


def cmd_post(feature_id):
    features, status = parse_doc2()

    if feature_id not in features:
        die(f"Feature {feature_id} not found in doc2.")

    report_path = REPORTS_DIR / f"{feature_id}_milestone.md"
    if not report_path.exists():
        die(
            f"Milestone report not found: {report_path}\n"
            f"  Claude Code should have created it. Check the reports/ directory."
        )

    print(c(BOLD, f"\n→ Post-processing {feature_id}"))
    print(c(DIM,  f"  Report: {report_path}\n"))

    # 1. Parse the milestone report
    report = parse_milestone_report(report_path)
    if not report:
        die("Could not parse milestone report. Check the file format.")

    feature_id_in_report = report.get("feature_id", "").strip('"')
    if feature_id_in_report and feature_id_in_report != feature_id:
        warn(f"feature_id in report ({feature_id_in_report}) doesn't match "
             f"argument ({feature_id}). Continuing with argument.")

    # 2. Security check — surface deviations immediately
    if not report.get("security_checklist_followed", False):
        print(c(RED, "  ⚠ SECURITY: security_checklist_followed is false."))
        notes = report.get("security_checklist_notes", "")
        if notes:
            print(c(RED, f"    Notes: {notes}"))
        print()

    if report.get("has_undone"):
        print(c(YELLOW, "  ⚠ Some acceptance criteria were left undone."))
        print(c(DIM,    "    Check left_undone section in the milestone report.\n"))

    # 3. Extract memory entries
    print("  Extracting memory entries...")
    added = extract_to_memory(report, feature_id)
    total = sum(len(v) for v in added.values())
    if total > 0:
        for section, ids in added.items():
            if ids:
                print(c(DIM, f"    + {section}: {', '.join(ids)}"))
    else:
        print(c(DIM, "    No new memory entries (no issues or deviations to log)."))
    print()

    # 4. Run validator
    print("  Running validator...")
    validator_script = ROOT / "validator.py"
    if not validator_script.exists():
        warn("validator.py not found — skipping validation step.")
        print(c(YELLOW, "  Run: python validator.py " + feature_id + " when ready.\n"))
        update_doc2_status(feature_id, "in_progress")
        return

    result = subprocess.run(
        [sys.executable, str(validator_script), feature_id],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print(c(DIM, result.stderr))

    # 5. Read validator result from updated report
    report_fresh = parse_milestone_report(report_path)
    val_result_match = re.search(
        r"validator_result:.*?overall:\s*(pass|fail)",
        report_path.read_text(),
        re.DOTALL,
    )
    overall = val_result_match.group(1) if val_result_match else "unknown"

    # 6. Update doc2 status tracker
    new_status = "passed" if overall == "pass" else "failed"
    update_doc2_status(feature_id, new_status, validator_result=overall)
    print(c(GREEN if overall == "pass" else RED,
            f"  Status tracker updated: {feature_id} → {new_status}"))

    # 7. Show what's now unblocked
    features_fresh, status_fresh = parse_doc2()
    newly_ready = ready_features(features_fresh, status_fresh)
    if newly_ready:
        labels = ["{} ({})".format(fid, features_fresh[fid].get('title', '').strip('"'))
                  for fid in newly_ready]
        print(c(GREEN, f"\n  Now ready to start: {', '.join(labels)}"))
        print(c(DIM,   "  Run: python orchestrator.py next\n"))
    else:
        print(c(DIM, "\n  No new features unblocked yet.\n"))


def cmd_status():
    features, status = parse_doc2()

    status_icons = {
        "pending":     c(DIM,    "○ pending"),
        "in_progress": c(YELLOW, "● in progress"),
        "blocked":     c(RED,    "✗ blocked"),
        "passed":      c(GREEN,  "✓ passed"),
        "failed":      c(RED,    "✗ failed"),
        "skipped":     c(DIM,    "– skipped"),
    }

    # Group by milestone
    milestones = {}
    for fid, row in status.items():
        m = row.get("milestone", "unknown")
        milestones.setdefault(m, []).append(fid)

    print(c(BOLD, "\n── Feature board ──────────────────────────────\n"))

    for milestone_id in sorted(milestones):
        print(c(BOLD, f"  {milestone_id}"))
        for fid in sorted(milestones[milestone_id]):
            row     = status[fid]
            feature = features.get(fid, {})
            raw_title = (feature or {}).get("title") or ""
            title   = row.get("title") or (raw_title.strip('"') if isinstance(raw_title, str) else "") or "(untitled)"
            stat    = row.get("status", "pending")
            icon    = status_icons.get(stat, stat)
            deps    = feature.get("depends_on", []) or []
            dep_str = f"  {c(DIM, 'depends on: ' + ', '.join(deps))}" if deps else ""
            print(f"    {icon}  {fid} — {title}{dep_str}")
        print()

    # Summary counts
    counts = {}
    for row in status.values():
        s = row.get("status", "pending")
        counts[s] = counts.get(s, 0) + 1

    parts = [f"{v} {k}" for k, v in counts.items()]
    print(c(DIM, "  " + " · ".join(parts) + "\n"))


def cmd_memory(feature_id):
    features, _ = parse_doc2()
    if feature_id not in features:
        die(f"Feature {feature_id} not found in doc2.")

    filtered = filter_memory(feature_id, features)
    total = sum(len(v) for v in filtered.values())

    print(c(BOLD, f"\n── Filtered memory for {feature_id} ──────────────\n"))
    print(json.dumps(filtered, indent=2))
    print(c(DIM, f"\n  {total} entries total\n"))


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def die(msg):
    print(c(RED, f"\n✗ Error: {msg}\n"), file=sys.stderr)
    sys.exit(1)


def warn(msg):
    print(c(YELLOW, f"  ⚠ {msg}"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(0)

    command = args[0].lower()

    if command == "next":
        cmd_next()

    elif command == "post":
        if len(args) < 2:
            die("post requires a feature_id argument.\n  Usage: python orchestrator.py post F-01-002")
        cmd_post(args[1].upper())

    elif command == "status":
        cmd_status()

    elif command == "memory":
        if len(args) < 2:
            die("memory requires a feature_id argument.\n  Usage: python orchestrator.py memory F-01-002")
        cmd_memory(args[1].upper())

    else:
        die(f"Unknown command: {command}\n  Valid commands: next, post, status, memory")


if __name__ == "__main__":
    main()
