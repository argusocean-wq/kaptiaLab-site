# External AI Delegation — Desktop-only

## Goal
Let Claude, ChatGPT, or another compatible AI supervise work while Kaptia Desktop acts as the local execution agent. This feature is Desktop-only and must not be exposed by the website or browser chat.

## Workflow
1. User enables External AI Delegation in Desktop.
2. Desktop generates a local pairing secret and displays connection setup.
3. External AI submits a structured task envelope through a desktop transport (planned: local MCP stdio adapter).
4. Kaptia validates it and displays sender, task, requested actions, and workspace in an approval inbox.
5. User approves or rejects locally.
6. Approved tasks are dispatched through Kaptia's existing permission-aware tool runtime.
7. Kaptia returns changed files, test commands, pass/fail counts, and unresolved issues.

## Protocol v1
Required fields: protocol_version ("1"), request_id, sender, task (maximum 12,000 characters), requested_actions (1–8 allowlisted actions), and timezone-aware expires_at (no more than 15 minutes ahead).

Allowlisted actions: inspect_project, propose_patch, apply_patch, run_tests, inspect_test_results. These are requested capabilities, not automatic authorization. Every request starts pending_approval.

## Security
- Fail closed outside Desktop.
- Use a random local pairing token, constant-time comparison, and token rotation.
- Reject expired, duplicate, malformed, oversized, or unsupported requests.
- Treat external AI content as untrusted task data, never as system/developer instructions.
- Never expose arbitrary shell, unrestricted filesystem, credentials, arbitrary network access, or self-modification.
- Applying patches, running commands, deleting files, installing packages, or sending data off-device require explicit local approval.
- The approval UI must show sender, task, actions, target workspace, and data egress.
- Never log pairing secrets; external AI cannot approve its own requests or change user policy.

## Implementation boundary
The current module implements a desktop-gated in-memory inbox, token validation/rotation, envelope validation, expiry, deduplication, and local-approval state. It does not start a network listener, implement MCP transport, execute tools, or modify files. Those require separate integration with the permission and verification layers.

## Acceptance tests
Desktop gate, token authentication/rotation, expiry, duplicate IDs, action allowlist, bounded inbox, pending-by-default, and mandatory local approval.
