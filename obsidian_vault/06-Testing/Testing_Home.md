---
type: test
status: active
owner: testing
created: 2026-08-11
updated: 2026-08-11
related: [Test_Index, Test_Framework, Test_Report_Suite, Tasks_Home, System_Architecture]
---

# Testing_Home

> Hub for test knowledge — the section future Testing agents will read from
> and write to.

**Type:** test · **Status:** active · **Owner:** testing

---

## Purpose

Central index of test plans, test reports, and QA knowledge.

- ↑ Parent: [[System_Core]]
- ↓ Children:
  - [[Test_Index]] — index of all test nodes
  - [[Test_Framework]] — existing test framework & commands
  - [[Test_Report_Suite]] — verified full-suite report (passed)
  - [[_TEST_PLAN_TEMPLATE]] — standard test plan template
  - [[_TEST_REPORT_TEMPLATE]] — standard test-report template
- ↔ Related: [[Tasks_Home]], [[Decisions_Home]], [[System_Architecture]], [[Doc_Development_Guide]]

## Test Statuses

| Status | Meaning |
|---|---|
| `draft` | Test defined, not yet executed |
| `passed` | All test cases pass |
| `failed` | One or more test cases fail |
| `blocked` | Cannot run until a dependency is met |

## How Agents Read, Run, and Report Tests

1. **Read:** the testing agent opens [[Testing_Home]] → [[Test_Index]] →
   `Test_*` nodes (status `draft`, not blocked).
2. **Run:** execute the test cases against the linked component.
3. **Report:** if all cases pass → `status: passed`; otherwise `status:
   failed` with failing cases listed in the body.
4. **Block:** if the component or a prerequisite is missing → `status:
   blocked` with the blocker noted.
5. **Link:** every test node links to the task/feature it validates via
   `related_task` (`[[WikiLinks]]`) and to its component via `related_component`.
6. **Rules:**
   - Only the testing agent (or orchestrator) transitions test status.
   - Every transition bumps `updated`.
   - A test may only reach `passed` when all listed test cases are `[x]`.

## Rules

- Test nodes live in `06-Testing/` and link up to this hub.
- Each test plan/report node follows the [[_TEST_PLAN_TEMPLATE]].
- Link test nodes to the task or feature they validate.

## Future Agent Mapping

Reserved for the future **Testing** agent, which writes test plans and reports
here.
