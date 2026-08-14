"""Deterministic fake ``opencode`` CLI for adapter tests (Phase 5).

Behavior is scripted through environment variables so each test controls the
subprocess deterministically without touching a real OpenCode install:

    FAKE_OPENCODE_EXIT       int exit code (default 0)
    FAKE_OPENCODE_STDOUT     text printed to stdout (default "")
    FAKE_OPENCODE_SLEEP      seconds to sleep before printing/exiting (default 0)
    FAKE_OPENCODE_COUNTER    path to a counter file; incremented per invocation
    FAKE_OPENCODE_FAIL_UNTIL when COUNTER is set: exit 1 while count <= N
                            (lets retry tests script failure→failure→success)
    FAKE_OPENCODE_ARGS       path to a file that receives the full argv (JSON),
                            so tests can assert the exact
                            ``opencode run --agent X --auto -m M "<prompt>"``
"""

import json
import os
import sys
import time


def main() -> int:
    sleep = os.environ.get("FAKE_OPENCODE_SLEEP")
    if sleep:
        time.sleep(float(sleep))

    counter = os.environ.get("FAKE_OPENCODE_COUNTER")
    fail_until = int(os.environ.get("FAKE_OPENCODE_FAIL_UNTIL") or "0")
    exit_code = int(os.environ.get("FAKE_OPENCODE_EXIT") or "0")
    if counter:
        n = 0
        if os.path.exists(counter):
            try:
                n = int(open(counter, "r", encoding="utf-8").read().strip() or "0")
            except (OSError, ValueError):
                n = 0
        n += 1
        with open(counter, "w", encoding="utf-8") as f:
            f.write(str(n))
        if fail_until and n <= fail_until:
            exit_code = 1

    args_path = os.environ.get("FAKE_OPENCODE_ARGS")
    if args_path:
        with open(args_path, "w", encoding="utf-8") as f:
            json.dump(sys.argv, f)

    out = os.environ.get("FAKE_OPENCODE_STDOUT", "")
    if out:
        print(out, flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
