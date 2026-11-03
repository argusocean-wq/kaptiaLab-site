# External AI Delegation — MCP transport (Stage 2)

## Desktop MCP stdio server

Entry point: `python -m desktop.mcp_server` with `PYTHONPATH=app`.

Required environment:
- `KAPTIA_DESKTOP=1` — explicit Desktop-only gate.
- `KAPTIA_DELEGATION_TOKEN` — random local pairing token, minimum 32 characters.
- `KAPTIA_DELEGATION_DB` — optional SQLite queue path; defaults to `~/.kaptiaLab/delegation.sqlite3`.

The process speaks newline-delimited JSON-RPC 2.0 over stdin/stdout and supports MCP initialize, ping, tools/list, and tools/call.

### Exposed tools
- `submit_task`: validates and stores an external task in SQLite as `pending_approval`.
- `get_task_status`: reads the request's pending state.

The MCP process never approves, executes, writes project files, or runs shell commands. Approval and execution must be performed by the local Kaptia Desktop UI and its permission-aware executor. The external AI must never be able to invoke approval through MCP.

### Pairing
Generate a cryptographically random token locally in Desktop and configure the same value as `KAPTIA_DELEGATION_TOKEN` in the MCP client process environment. Do not paste the token into prompts or commit it to configuration files. Rotate it if exposed.

### Current integration boundary
This stage supplies the MCP stdio transport and durable SQLite inbox. The Desktop UI polling/approval view, automatic MCP client configuration generation, and post-approval execution adapter remain separate integration tasks. Until those are implemented, submitted tasks are safely queued but will not run automatically.

## Security
- No TCP listener, port exposure, or remote inbound network service.
- Only allowlisted action names; no arbitrary shell/file/URL operation.
- Bounded input size, task length, action count, expiry, and pending queue.
- Pairing token checked with constant-time comparison.
- External text is untrusted data, not privileged instructions.
- SQLite queue is local; do not sync it to third-party cloud storage by default.
