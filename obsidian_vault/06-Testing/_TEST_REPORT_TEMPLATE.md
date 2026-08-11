---
type: test
status: draft
owner: testing
related_component: Component_AgentSpecs
related_agent: Agent_David
related_task: Task_<Short_Name>
test_command: python -m unittest discover -s test/tests
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Test_Report_<Name>

**Type:** test · **Status:** draft · **Owner:** testing

## Test Name

<Human-readable test name>

## Related

- ↔ Component: [[Component_AgentSpecs]]
- ↔ Agent: [[Agent_David]]
- ↔ Task: `[[Task_<Short_Name>]]` *(optional)*

## Test Command

`python -m unittest discover -s test/tests`

## Result

<passed / failed / blocked — plus a one-line summary>

## Failures

- *(none)*

OR

- `test_id` — expected: <…>, actual: <…>

## Timestamp

YYYY-MM-DD HH:MM

## Links

- ↑ Parent: [[Testing_Home]]
- ↔ Related: [[Test_Index]]

---

## How to use this template

1. Copy this file to `06-Testing/Test_Report_<Name>.md`.
2. Fill every frontmatter field. Allowed `status`: `draft`, `passed`,
   `failed`, `blocked` (plus `active` for hub/index nodes).
3. `related_component`, `related_agent`, `related_task` must be node names
   that exist (they render as `[[WikiLinks]]`).
4. Add the report to [[Test_Index]].
5. Run `python scripts/vault_validate.py` before committing.
