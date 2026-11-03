# External AI Delegation — Desktop-only

## Goal
Let Claude, ChatGPT, or another compatible AI supervise work while Kaptia Desktop acts as the local execution agent. This capability is Desktop-only; the website and browser chat do not expose it.

## Stage 1 — approval-gated inbox
`app/desktop/external_ai_bridge.py` validates task envelopes, enforces expiry and action allowlists, and requires local confirmation before an approval state transition. It does not execute commands or modify files.

## Stage 2 — MCP stdio transport
Entry point: `python -m desktop.mcp_server` with `PYTHONPATH=app`.

Required environment:
- `KAPTIA_DESKTOP=1` — explicit Desktop-only process gate.
- `KAPTIA_DELEGATION_TOKEN` — local enablement secret, minimum 32 characters. Keep it in the MCP client's process environment, not in prompts or tool arguments.
- `KAPTIA_DELEGATION_DB` — optional SQLite queue path; defaults to `~/.kaptiaLab/delegation.sqlite3`.

The server uses newline-delimited JSON-RPC 2.0 over stdin/stdout and supports initialize, ping, tools/list, and tools/call.

### MCP tools
- `submit_task`: validates and stores a task in SQLite as `pending_approval`.
- `get_task_status`: reads the current state of a submitted task.

The MCP tool schema does not expose the pairing secret to the model. The MCP process is launched by the user's explicitly configured local MCP client; the secret is a local process-start gate, not a substitute for operating-system account security.

## Workflow and current boundary
1. User enables delegation in Desktop and configures the local MCP client to launch the stdio server.
2. External AI calls `submit_task`.
3. The server writes a bounded, expiring task row to the local SQLite queue.
4. Kaptia Desktop must read that same queue and show sender, task, requested actions, and target workspace.
5. The user approves or rejects locally.
6. Only the Desktop's permission-aware executor may perform approved work.
7. Kaptia returns execution evidence and test results to the supervisor.

**Not yet implemented:** Desktop UI polling/approval view, automatic MCP client configuration generation, post-approval executor integration, and result callback to the external AI. Until those stages exist, requests are safely queued but will not execute.

## Security constraints
- No TCP listener or remotely exposed inbound service; stdio only.
- Only allowlisted action names; no arbitrary shell, unrestricted filesystem, credential access, arbitrary URL fetch, or self-modification.
- Bounded input line size, task length, action count, queue size, and request expiry.
- External task text is untrusted data, never system/developer instructions.
- The MCP process cannot approve tasks; the external AI cannot alter user policy.
- Keep the SQLite queue local and exclude it from cloud sync by default.
- Do not log or commit the pairing secret; rotate it if exposed.

## Acceptance tests
Desktop process gate, startup secret validation, MCP initialize/tools discovery, SQLite persistence across process instances, duplicate ID rejection, expiry, allowlisted actions, and pending-by-default behavior.
