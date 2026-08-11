---
type: test
status: active
owner: testing
related_component: System_Architecture
test_command: python -m unittest discover -s test/tests
created: 2026-08-11
updated: 2026-08-11
---

# Test_Framework

**Type:** test · **Status:** active (documentation) · **Owner:** testing

## Purpose

Documents the project's **existing** test framework and commands (verified from
the codebase). This node is reference documentation, not a test report.

## Framework

- **Python `unittest`** (standard library — no external test dependencies).
- Suite location: `test/tests/` (control-plane tests) and `test/` (sample
  expense-tracker project).

## Test Commands

| Command | Purpose |
|---|---|
| `python -m unittest discover -s test/tests` | Run the full control-plane test suite |
| `python -m unittest test.tests.test_terminal_app` | Run one test module |
| `python -m unittest test.tests.test_agents` | Agent roster/spec tests |
| `python -m unittest test.tests.test_agent_specs` | Spec ↔ opencode.json drift tests |
| `python -m unittest test.tests.test_expense_manager` | Sample-project tests |
| `launch_agents.bat --smoke` | Smoke-test the 7-window launcher |
| `python scripts/terminal_app.py --smoke` | Headless terminal build check |

## Test Files (existing)

- `test/tests/test_agents.py`
- `test/tests/test_agent_specs.py`
- `test/tests/test_expense_manager.py`
- `test/tests/test_terminal_app.py`
- `test/tests/__init__.py`

## Notes

- Reports live in this vault ([[Test_Index]], `Test_Report_*`) — **separate from
  the test source code**, which is never modified by the vault layer.

## Links

- ↑ Parent: [[Testing_Home]]
- ↔ Related: [[Test_Index]], [[System_Architecture]], [[Doc_Development_Guide]]
