# KaptiaLab M1 — Core Foundation

Status: implementation slice in progress. This document describes the M1 contract, not a claim that the full employee workforce or cloud runtime is complete.

## Scope

M1 establishes:
- explicit, validated task plans and dependency DAGs;
- durable SQLite task and step records;
- atomic claiming of dependency-ready work;
- capability- and data-classification-aware model routing;
- deterministic output verification;
- an orchestration facade that does not bypass tool permissions.

M1 does not yet implement natural-language multi-agent decomposition, a production model endpoint, distributed cloud scheduling, a desktop task center, or self-modifying code.

## Modules

- `core_foundation/contracts.py`: immutable data contracts.
- `core_foundation/planner.py`: step normalization and DAG validation.
- `core_foundation/repository.py`: SQLite persistence, state transitions, atomic claims and event journal.
- `core_foundation/model_router.py`: local / user-cloud / external model adapter selection.
- `core_foundation/verification.py`: allowlisted deterministic acceptance checks.
- `core_foundation/orchestrator.py`: submission, dispatch and verification-gated completion.

## Data handling

Task steps default to `private`. `local_only` requests are never routed to user-cloud or external providers. A provider must be explicitly registered and must advertise all requested capabilities. External providers are not implicitly enabled.

## Task lifecycle

A step is eligible only when all dependency steps are `completed`. A claimed step enters `running`, then `verifying`. It can enter `completed` only when a structured verification result contains `passed: true`. Unknown verification types fail closed. All state changes are recorded in `task_events`.

## Persistence

The default database is stored under the application state directory. SQLite foreign keys, WAL mode, a busy timeout and immediate write transactions are enabled. Use a separate database file per independent installation or worker.

## Extension points

Model adapters implement `generate(request)`. Executors receive a claimed step and must use the existing allowlisted tool runtime / explicit-consent workflow for side effects. The core orchestrator itself does not expose arbitrary shell or unrestricted filesystem access.

## Validation

Run:

```powershell
$env:PYTHONPATH = "app"
python -m pytest -q app/tests app/cloud_worker/test_app.py
python -m compileall -q app
```
