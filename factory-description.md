# Factory Description

## What this factory does

This factory receives a software specification as a task in the BAND Desktop room. It decomposes the task, implements it, verifies it, and repairs failures - without a human directing each step.

## Seats

### Planner Agent
- Decomposes tasks into work units with explicit done criteria
- Assigns to Executor, closes only when Reviewer reports PASS
- Escalates to human only for product/architectural decisions

### Executor Agent
- Implements code to satisfy done criteria exactly
- Hands off to Reviewer with summary of decisions and edge cases
- Fixes issues on FAIL, re-hands off

### Reviewer Agent
- Writes and runs tests against done criteria
- Reports PASS with evidence OR FAIL with specific failures
- Never modifies the implementation

## Handoff protocol

```
Human -> Planner: task description
Planner -> Executor: work unit + done criteria
Executor -> Reviewer: implementation + summary
Reviewer -> Planner: PASS + evidence
         -> Executor: FAIL + specific failures
Planner -> Human: decision requests only
```

## Why mandates are generic

No mandate mentions any domain-specific concept, endpoint path, field name, or project name. The same mandates work for any software project. Domain detail lives only in the task dropped into the room.
