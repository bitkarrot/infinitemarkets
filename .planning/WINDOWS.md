---
schema_version: 1
open_count: 1
waived_count: 0
fixed_count: 0
total_count: 1
last_updated: 2026-10-16T22:00:19.769Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 07 | deviation | .planning/phases/07-shared-image-editors/07-03-PLAN.md |  | 07-03 verify -k 'image or product' deselects fixture-providing test_collection_zero_members_no_intent; whole-file run used instead (25 green) | open |  | 2026-10-16T22:00:19.769Z |  |

````json
[
  {
    "id": 1,
    "kind": "deviation",
    "phase": "07",
    "file": ".planning/phases/07-shared-image-editors/07-03-PLAN.md",
    "line": null,
    "description": "07-03 verify -k 'image or product' deselects fixture-providing test_collection_zero_members_no_intent; whole-file run used instead (25 green)",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-10-16T22:00:19.769Z",
    "resolved_at": null,
    "milestone": "v1.1"
  }
]
````
