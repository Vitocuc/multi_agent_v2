#!/usr/bin/env python3
"""
cto.py — interactive CTO orchestrator session.

Drives the clarification loop and contract generation via API.
Model-agnostic: supports Claude (Anthropic) and Gemini (Google).
You answer questions in the terminal; the script handles API calls,
appends to doc0's clarification_log, and saves the three contracts.

Usage:
  python cto.py --model claude          # use Claude (needs ANTHROPIC_API_KEY)
  python cto.py --model gemini          # use Gemini (needs GEMINI_API_KEY)
  python cto.py --resume                # continue an interrupted session
  python cto.py --plan-only             # just show the shared plan, no contracts

Environment variables:
  ANTHROPIC_API_KEY    for --model claude
  GEMINI_API_KEY       for --model gemini

Files read:
  doc0_project_brief.md          your project brief (must exist and be filled)
  prompts/cto_system_prompt.md   the CTO system prompt

Files written:
  doc0_project_brief.md          clarification_log and shared plan appended
  doc1_security_contract.md      generated after plan approval
  doc2_features_contract.md      generated after plan approval
  doc3_validation_contract.md    generated after plan approval
"""

import sys
import os
import re
import json
import urllib.request
import urllib.error
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
        load_dotenv(env_path, override=False)  # override=False: shell env wins
    except ImportError:
        # python-dotenv not installed — parse .env manually (no dependencies)
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
        if key and key not in os.environ:   # shell env takes precedence
            os.environ[key] = val


load_env()

ROOT        = Path(__file__).parent
DOC0        = ROOT / "doc0_project_brief.md"
SYSTEM_FILE = ROOT / "prompts" / "cto_system_prompt.md"

CLAUDE_MODEL = "claude-sonnet-4-20250514"
GEMINI_MODEL = "gemini-2.5-flash"

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
GEMINI_API    = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

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
# Doc0 helpers
# ---------------------------------------------------------------------------

def load_doc0():
    if not DOC0.exists():
        die("doc0_project_brief.md not found. Fill it in before running cto.py.")
    return DOC0.read_text()


def append_clarification_round(round_num, question, answer):
    """Append a clarification round to the clarification_log in doc0."""
    text = DOC0.read_text()
    entry = f"""
---
round: {round_num}
question: "{question}"
answer: "{answer}"
resolved: true
---"""

    # Insert before the shared plan section
    if "## Shared plan" in text:
        text = text.replace("## Shared plan", entry + "\n\n## Shared plan")
    elif "## Clarification log" in text:
        # Append after the clarification log header
        text += entry
    else:
        text += entry

    DOC0.write_text(text)


def write_shared_plan(plan_text):
    """Replace the shared plan section in doc0 with the CTO's plan."""
    text = DOC0.read_text()

    # Replace shared_plan_approved: false and the commented placeholders
    new_plan = f"""shared_plan_approved: false

{plan_text.strip()}
"""
    # Replace from shared_plan_approved to end of file
    text = re.sub(
        r"shared_plan_approved: false.*$",
        new_plan,
        text,
        flags=re.DOTALL,
    )
    DOC0.write_text(text)


def mark_plan_approved():
    text = DOC0.read_text()
    text = text.replace("shared_plan_approved: false", "shared_plan_approved: true")
    DOC0.write_text(text)


def save_contract(filename, content):
    path = ROOT / filename
    # Strip the <!-- filename --> comment if the model included it
    content = re.sub(r"<!--.*?-->\n?", "", content).strip()
    path.write_text(content + "\n")
    return path


def get_clarification_round_count():
    text = DOC0.read_text()
    rounds = re.findall(r"^round:\s*(\d+)", text, re.MULTILINE)
    return max([int(r) for r in rounds], default=0)


# ---------------------------------------------------------------------------
# API callers
# ---------------------------------------------------------------------------

def call_claude(messages, system_prompt):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        die("ANTHROPIC_API_KEY not set. Export it before running.")

    payload = json.dumps({
        "model":      CLAUDE_MODEL,
        "max_tokens": 8192,
        "system":     system_prompt,
        "messages":   messages,
    }).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_API,
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
            return raw["content"][0]["text"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        die(f"Anthropic API error {e.code}: {body[:500]}")
    except urllib.error.URLError as e:
        die(f"Network error: {e.reason}")


def call_gemini(messages, system_prompt):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        die("GEMINI_API_KEY not set. Export it before running.")

    # Convert OpenAI-style messages to Gemini format
    gemini_contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        gemini_contents.append({
            "role": role,
            "parts": [{"text": m["content"]}]
        })

    payload = json.dumps({
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents":           gemini_contents,
        "generationConfig": {
            "temperature":     0.3,
            "maxOutputTokens": 8192,
        },
    }).encode("utf-8")

    url = f"{GEMINI_API}?key={api_key}"
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
            return raw["candidates"][0]["content"]["parts"][0]["text"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        die(f"Gemini API error {e.code}: {body[:500]}")
    except urllib.error.URLError as e:
        die(f"Network error: {e.reason}")


def call_model(model, messages, system_prompt):
    print(c(DIM, f"  [{model} thinking...]"), end="", flush=True)
    if model == "claude":
        result = call_claude(messages, system_prompt)
    else:
        result = call_gemini(messages, system_prompt)
    print(f"\r{' ' * 30}\r", end="")  # clear the thinking indicator
    return result


# ---------------------------------------------------------------------------
# Contract extractor
# The model produces all three contracts in one response.
# This splits them out and saves each to a file.
# ---------------------------------------------------------------------------

def extract_and_save_contracts(response_text):
    """
    Parse the model's response and save doc1, doc2, doc3.
    The model is instructed to separate contracts with 'Save the above as docN_...'
    Returns list of (filename, path) tuples for contracts that were saved.
    """
    saved = []

    # Strategy 1: split on "Save the above as docN_..." markers
    parts = re.split(
        r"Save the above as (doc\d+_[\w_]+\.md)",
        response_text,
        flags=re.IGNORECASE,
    )

    if len(parts) > 1:
        # parts alternates: [before_first, filename1, content1, filename2, content2, ...]
        # The content before the first marker is discarded (it's prose)
        i = 1
        while i < len(parts) - 1:
            filename = parts[i].strip()
            content  = parts[i + 1].strip()
            path = save_contract(filename, content)
            saved.append((filename, path))
            i += 2
        return saved

    # Strategy 2: look for markdown level-1 headings with doc names
    # e.g. <!-- doc1_security_contract.md --> or # Security contract
    doc_patterns = [
        ("doc1_security_contract.md",  r"# Security contract"),
        ("doc2_features_contract.md",  r"# Features contract"),
        ("doc3_validation_contract.md", r"# Validation contract"),
    ]

    for filename, pattern in doc_patterns:
        match = re.search(pattern, response_text)
        if match:
            start = match.start()
            # Find next contract heading or end of text
            next_matches = [
                re.search(p, response_text[start + 1:])
                for _, p in doc_patterns
                if re.search(p, response_text[start + 1:])
            ]
            if next_matches:
                end = start + 1 + min(m.start() for m in next_matches)
                content = response_text[start:end].strip()
            else:
                content = response_text[start:].strip()

            path = save_contract(filename, content)
            saved.append((filename, path))

    return saved


# ---------------------------------------------------------------------------
# Session state
# Conversation history is kept in memory only — not persisted between runs.
# Use --resume to restart from current doc0 state.
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, model):
        self.model    = model
        self.messages = []   # list of {role, content}
        self.round    = get_clarification_round_count()
        self.phase    = "clarification"  # clarification | plan_review | contracts

    def user(self, text):
        self.messages.append({"role": "user", "content": text})

    def assistant(self, text):
        self.messages.append({"role": "assistant", "content": text})

    def think(self, system_prompt):
        response = call_model(self.model, self.messages, system_prompt)
        self.assistant(response)
        return response


# ---------------------------------------------------------------------------
# Main interaction loop
# ---------------------------------------------------------------------------

def run_session(model, resume=False, plan_only=False):
    if not SYSTEM_FILE.exists():
        die(f"CTO system prompt not found at {SYSTEM_FILE}.\n"
            "  Make sure prompts/cto_system_prompt.md exists.")

    system_prompt = SYSTEM_FILE.read_text()
    doc0_text     = load_doc0()
    session       = Session(model)

    print(c(BOLD, "\n── CTO Orchestrator session ──────────────────────\n"))
    print(c(DIM,  f"  Model:  {model}  ({CLAUDE_MODEL if model == 'claude' else GEMINI_MODEL})"))
    print(c(DIM,  f"  Doc0:   {DOC0}"))
    print(c(DIM,  f"  Rounds completed so far: {session.round}\n"))

    # -----------------------------------------------------------------------
    # Phase 1: Clarification loop
    # -----------------------------------------------------------------------

    # Initial message: hand the CTO the full doc0
    initial_msg = f"""I have a project I want to build. Here is my project brief (doc0).

{doc0_text}

Please read it and ask me your first clarifying question.
Remember: one question at a time, most important gap first."""

    session.user(initial_msg)
    response = session.think(system_prompt)

    while True:
        # Print model response
        print(c(BOLD, "\nCTO:"))
        print(response)
        print()

        # Detect if the model is presenting the shared plan for approval
        if ("shared plan" in response.lower() or "shared_plan" in response.lower()) \
                and ("approve" in response.lower() or "confirm" in response.lower()
                     or "review" in response.lower()):
            session.phase = "plan_review"

            # Extract and save the plan to doc0
            plan_match = re.search(
                r"(summary:.*?)(?=please|do you|reply|---|\Z)",
                response,
                re.DOTALL | re.IGNORECASE,
            )
            if plan_match:
                write_shared_plan(plan_match.group(1))
                print(c(DIM, "  → Shared plan written to doc0.\n"))

            break

        # Detect if the model jumped straight to contracts (shouldn't happen
        # with the prompt, but handle it gracefully)
        if "# Security contract" in response or "doc1_security_contract" in response:
            session.phase = "contracts"
            break

        # Normal clarification round — get human answer
        print(c(CYAN, "Your answer (or 'skip' to move on, 'done' to approve plan now):"))
        try:
            answer = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(c(YELLOW, "\n\nSession interrupted. Run with --resume to continue."))
            sys.exit(0)

        if answer.lower() == "skip":
            session.round += 1
            append_clarification_round(session.round, response, "[skipped by user]")
            session.user("Let's skip that for now and move on. What is the next most important question?")
        elif answer.lower() in ("done", "approved", "approve"):
            session.user("I'm satisfied with the current level of detail. Please write the shared plan now.")
        else:
            session.round += 1
            append_clarification_round(session.round, response.strip(), answer)
            session.user(answer)

        response = session.think(system_prompt)

    # -----------------------------------------------------------------------
    # Phase 2: Plan review
    # -----------------------------------------------------------------------

    if session.phase == "plan_review":
        print(c(CYAN, "Review the shared plan above. Type 'approved' to proceed, or tell the CTO what to fix:"))

        while True:
            try:
                answer = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print(c(YELLOW, "\n\nSession interrupted."))
                sys.exit(0)

            if answer.lower() in ("approved", "approve", "yes", "ok", "lgtm"):
                mark_plan_approved()
                print(c(GREEN, "\n  ✓ Shared plan approved. Proceeding to contract generation.\n"))
                session.user(
                    "Approved. The shared plan looks good. "
                    "Now please generate all three contracts: "
                    "doc1_security_contract.md, doc2_features_contract.md, "
                    "and doc3_validation_contract.md. "
                    "Output them in full, one after another, separated by "
                    "'Save the above as docN_filename.md'."
                )
                break
            else:
                session.user(f"Not approved yet. Please fix the following: {answer}")
                response = session.think(system_prompt)
                print(c(BOLD, "\nCTO (revised plan):"))
                print(response)
                print()

                if plan_only:
                    print(c(DIM, "  --plan-only mode. Exiting before contract generation."))
                    sys.exit(0)

        if plan_only:
            print(c(DIM, "  --plan-only mode. Exiting before contract generation."))
            sys.exit(0)

    # -----------------------------------------------------------------------
    # Phase 3: Contract generation
    # -----------------------------------------------------------------------

    print(c(BOLD, "Generating contracts...\n"))
    response = session.think(system_prompt)

    print(c(BOLD, "\nCTO (contracts):"))
    # Don't print the full contracts to terminal — they'll be saved to files
    # Just show a preview
    preview_lines = response.split("\n")[:8]
    print("\n".join(preview_lines))
    if len(response.split("\n")) > 8:
        print(c(DIM, f"  ... ({len(response.split(chr(10)))} lines total)"))
    print()

    # Extract and save the three contract files
    saved = extract_and_save_contracts(response)

    if saved:
        print(c(GREEN, "  ✓ Contracts saved:"))
        for filename, path in saved:
            print(c(GREEN, f"    {filename}"))
    else:
        # Model didn't format correctly — save the full response and warn
        raw_path = ROOT / "contracts_raw_output.md"
        raw_path.write_text(response)
        print(c(YELLOW, "  ⚠ Could not auto-parse contracts from response."))
        print(c(YELLOW, f"  Full response saved to: {raw_path}"))
        print(c(YELLOW, "  Manually split into doc1, doc2, doc3 and save to repo root."))

    print()
    print(c(BOLD, "── Session complete ───────────────────────────────\n"))
    print(c(DIM, "  Next step: review the three contract files, then run:"))
    print(c(CYAN, "  python orchestrator.py status\n"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    args      = sys.argv[1:]
    model     = "claude"
    resume    = "--resume"    in args
    plan_only = "--plan-only" in args

    if "--model" in args:
        idx = args.index("--model")
        if idx + 1 < len(args):
            model = args[idx + 1].lower()
        else:
            die("--model requires an argument: claude or gemini")

    if model not in ("claude", "gemini"):
        die(f"Unknown model: {model}. Use 'claude' or 'gemini'.")

    run_session(model=model, resume=resume, plan_only=plan_only)


def die(msg):
    print(c(RED, f"\n✗ {msg}\n"), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
