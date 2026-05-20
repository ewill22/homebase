"""
guapa_dev_routine.py — Guapa autonomous dev routine

Fires daily at 3 PM via Task Scheduler. Resets the isolated dev clones at
C:\\Users\\eewil\\guapa-dev\\ to pristine latest-origin, invokes Claude Code
headless with the routine prompt (advance one roadmap item, open a PR, never
merge), then emails Eric the outcome.

Pro-only: uses local Claude Code, no cloud routine. Runs entirely inside
guapa-dev/ so the live repos under guapa/ are never touched.

Usage:
  python guapa_dev_routine.py            # full run
  python guapa_dev_routine.py --dry-run  # pick an item + plan only, no PR
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ─── Config ──────────────────────────────────────────────────────────────
DEV_ROOT       = Path(r"C:\Users\eewil\guapa-dev")
REPOS          = ["guapa-data", "guapa-site"]
CLAUDE_EXE     = r"C:\Users\eewil\.local\bin\claude.exe"
GH_CLI_DIR     = r"C:\Program Files\GitHub CLI"
PROMPT_FILE    = Path(r"C:\Users\eewil\guapa\guapa-pm\morning-routine-prompt.md")
RESULT_FILE    = DEV_ROOT / "last-run-result.txt"
LOG_FILE       = DEV_ROOT / "guapa_dev_routine.log"
HOMEBASE_DIR   = Path(r"C:\Users\eewil\homebase")
CLAUDE_TIMEOUT = 35 * 60   # hard cap on the headless session (seconds)

DRY_RUN_SUFFIX = """

## DRY RUN MODE — IMPORTANT
This is a dry run. Stop after Step 2. Do NOT create a branch, implement
anything, push, or open a PR. In Step 5, write the outcome as: first line
`DRY-RUN`, then the item you would have picked and a 3-5 line plan for it.
"""


def git(args, cwd, timeout=180):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


def reset_clone(repo_path: Path) -> None:
    """Force a dev clone to pristine latest-origin default branch.

    Safe to hard-reset here precisely because this is a dedicated scratch
    clone the routine owns — never run against the live repos under guapa/.
    """
    head = git(["rev-parse", "--abbrev-ref", "origin/HEAD"], repo_path)
    default = head.stdout.strip().rsplit("/", 1)[-1] or "main"
    git(["fetch", "origin", "--prune"], repo_path)
    git(["checkout", default], repo_path)
    git(["reset", "--hard", f"origin/{default}"], repo_path)
    git(["clean", "-fd"], repo_path)
    print(f"  {repo_path.name}: reset to origin/{default}")


def extract_prompt() -> str:
    """The prompt file carries a doc preamble; the real prompt is everything
    after the first horizontal rule (a line that is just '---')."""
    raw = PROMPT_FILE.read_text(encoding="utf-8")
    marker = "\n---\n"
    idx = raw.find(marker)
    return raw[idx + len(marker):].strip() if idx != -1 else raw.strip()


def send_outcome_email(subject: str, body: str) -> None:
    """Best-effort — a mail failure logs but doesn't otherwise matter."""
    try:
        sys.path.insert(0, str(HOMEBASE_DIR))
        from emailer import send_email
        from config import get_config
        to = get_config()["user"]["send_to_email"]
        send_email(subject, body, to=to)
        print(f"Outcome emailed to {to}")
    except Exception as e:
        print(f"Warning: could not send outcome email: {e}")


def main():
    parser = argparse.ArgumentParser(description="Guapa autonomous dev routine")
    parser.add_argument("--dry-run", action="store_true",
                        help="Pick an item and plan only — no branch/push/PR")
    args = parser.parse_args()

    # pythonw (Task Scheduler) has no stdout — log to a file instead.
    if sys.stdout is None:
        DEV_ROOT.mkdir(parents=True, exist_ok=True)
        sys.stdout = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout
    print(f"\n=== Dev routine started {datetime.now().isoformat()}"
          f"{' (dry-run)' if args.dry_run else ''} ===")

    # 1. Pristine clones
    try:
        for repo in REPOS:
            reset_clone(DEV_ROOT / repo)
    except Exception as e:
        print(f"FATAL: could not reset dev clones: {e}")
        send_outcome_email("Guapa dev routine - ERROR",
                           f"Could not reset dev clones:\n{e}")
        return

    # 2. Drop any stale result so we never email a previous run's outcome.
    if RESULT_FILE.exists():
        RESULT_FILE.unlink()

    # 3. Build the prompt
    prompt = extract_prompt()
    if args.dry_run:
        prompt += DRY_RUN_SUFFIX

    # 4. Invoke Claude Code headless. Enrich PATH so its Bash tool can find
    #    the GitHub CLI even under Task Scheduler's minimal environment.
    env = os.environ.copy()
    env["PATH"] = GH_CLI_DIR + os.pathsep + env.get("PATH", "")

    print("Invoking Claude Code headless...")
    try:
        proc = subprocess.run(
            [CLAUDE_EXE, "-p",
             "--permission-mode", "bypassPermissions",
             "--model", "sonnet"],
            input=prompt, cwd=str(DEV_ROOT), env=env,
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
            encoding="utf-8", errors="replace",
        )
        print(f"Claude exited with code {proc.returncode}")
        if proc.stdout:
            print("--- claude stdout (tail) ---")
            print(proc.stdout[-3000:])
        if proc.returncode != 0 and proc.stderr:
            print("--- claude stderr (tail) ---")
            print(proc.stderr[-2000:])
    except subprocess.TimeoutExpired:
        print(f"Claude timed out after {CLAUDE_TIMEOUT}s")
        send_outcome_email(
            "Guapa dev routine - TIMEOUT",
            f"The headless session ran past {CLAUDE_TIMEOUT // 60} minutes "
            "and was killed. Check guapa_dev_routine.log.")
        return
    except Exception as e:
        print(f"FATAL: could not run Claude: {e}")
        send_outcome_email("Guapa dev routine - ERROR",
                           f"Could not run Claude Code:\n{e}")
        return

    # 5. Read the outcome and email it.
    if not RESULT_FILE.exists():
        print("No result file written.")
        send_outcome_email(
            "Guapa dev routine - no result",
            "The session finished but wrote no result file. "
            "Check guapa_dev_routine.log for what happened.")
        return

    result = RESULT_FILE.read_text(encoding="utf-8").strip()
    first = result.splitlines()[0] if result else ""
    today = datetime.now().strftime("%a %b %d")

    if first.startswith("PR:"):
        subject = f"Guapa dev routine - PR ready ({today})"
    elif first.startswith("DRY-RUN"):
        subject = f"Guapa dev routine - dry run ({today})"
    elif first.startswith("NOTHING"):
        subject = f"Guapa dev routine - nothing today ({today})"
    elif first.startswith("BLOCKED"):
        subject = f"Guapa dev routine - blocked ({today})"
    else:
        subject = f"Guapa dev routine - ran ({today})"

    send_outcome_email(subject, result)
    print("Done.")


if __name__ == "__main__":
    main()
