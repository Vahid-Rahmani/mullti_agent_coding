---
type: test
status: draft
owner: testing
related_component: Component_RunHub
related_task: Task_<Short_Name>
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Test_<Short_Name>

**Type:** test · **Status:** draft · **Owner:** testing

## Title

<One-line human title>

## Scope

<What is being tested — feature, component, behavior. Link the component with [[WikiLinks]].>

## Test Cases

- [ ] TC-1: <description of case 1>
- [ ] TC-2: <description of case 2>
- [ ] TC-3: <description of case 3>

## Expected Results

<What passing looks like for each case.>

## Links

- ↑ Parent: [[Testing_Home]]
- ↔ Related Component: [[Component_RunHub]]
- ↔ Related Task: `[[Task_<Short_Name>]]`
- ↓ Dependencies: *(none)*

---

## How to use this template

1. Copy this file to `06-Testing/Test_<Short_Name>.md`.
2. Fill every frontmatter field. Allowed `status` values: `draft`,
   `passed`, `failed`, `blocked` (plus `active` for hub/index nodes).
3. `related_component` and `related_task` must be node names that exist
   (they render as `[[WikiLinks]]`).
   `related_task` refers to the task the test validates, if any.
4. Add the test to [[Test_Index]].
5. Run `python scripts/vault_validate.py` before committing.
