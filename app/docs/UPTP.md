# UPTP — Universal Packaging Tool Protocol

UPTP is KaptiaLab's local, versioned protocol for discovering packaging capabilities and invoking format adapters. Version 1.0 uses JSON-RPC 2.0 over UTF-8 newline-delimited stdio. JSON carries control metadata only; archive bytes stay in files and are referenced by filesystem paths.

## Transport and framing

- One JSON-RPC request or notification per UTF-8 line.
- Maximum request line: 1 MiB.
- Responses are JSON-RPC 2.0 objects. Notifications do not receive responses.
- stdout is reserved for protocol messages. Diagnostics belong on stderr.
- The server uses a bounded worker pool (1–4 workers; default 2).
- Request IDs are unique strings or integers while in flight.
- File paths are local paths. The caller must grant the packaging process access to the selected files and destination.

Launch:

\`\`\`powershell
python scripts/kaptia_packager.py
\`\`\`

## Methods

| Method | Required parameters | Result |
|---|---|---|
| \`rpc.discover\` | none | protocol version, formats, adapter IDs, supported operations |
| \`adapter.capabilities\` | \`format\` | one adapter's capabilities |
| \`pack\` | \`format\`, \`source_root\`, \`inputs[]\`, \`output\` | output path, SHA-256, entry count and bytes |
| \`unpack\` | \`format\`, \`archive\`, \`destination\` | destination and extracted entry count |
| \`inspect\` | \`format\`, \`archive\` | metadata without executing content |
| \`verify\` | \`format\`, \`archive\`, optional \`expected_sha256\` | structural validation and SHA-256 |
| \`cancel\` | \`request_id\` | best-effort cancellation request for an in-flight task |

Both uppercase operation names (for example \`PACK\`) and lowercase JSON-RPC method names are accepted for compatibility. Unknown methods use \`-32601\`; invalid parameters use \`-32602\`; unsafe or invalid archives use \`-32020\`; checksum mismatch uses \`-32010\`.

Example:

\`\`\`json
{"jsonrpc":"2.0","id":"req-1","method":"rpc.discover","params":{}}
{"jsonrpc":"2.0","id":"req-2","method":"pack","params":{"format":"zip","source_root":"C:/Work/Project","inputs":["README.md","src/main.py"],"output":"C:/Work/out/project.zip"}}
\`\`\`

The stdio implementation supports best-effort cancellation before a queued task starts. Running archive operations are not yet guaranteed to stop immediately; clients must treat cancellation as advisory until adapters implement cooperative cancellation checkpoints.

## Built-in format matrix

| Format | Pack | Unpack | Inspect | Verify | Notes |
|---|---:|---:|---:|---:|---|
| ZIP | yes | yes | yes | yes | CRC and path checks |
| WHL | yes | yes | yes | yes | ZIP container; package installation is not performed |
| TAR | yes | yes | yes | yes | TAR and TAR.GZ/TGZ; links and special files rejected |
| GZIP | yes | yes | yes | yes | Single-file stream |
| EXE | — | — | yes | yes | Header recognition and hashing only; never executed |
| MSI | — | — | yes | yes | Container signature recognition and hashing only; never installed |

7Z and additional formats are added through third-party adapters. UPTP does not execute EXE/MSI installers or install WHL packages.

## Third-party adapter contract

A Python distribution may expose an entry point in group \`kaptia.packaging.adapters.v1\`. The entry-point name is its stable plugin ID. The entry point must resolve to a zero-argument factory returning an adapter with:

- \`adapter_id: str\`
- \`formats: tuple[str, ...]\`
- \`capabilities() -> {"formats": [...], "operations": [...]}\`
- operation methods \`pack\`, \`unpack\`, \`inspect\`, and/or \`verify\` matching the advertised capability set.

Enable an adapter explicitly:

\`\`\`powershell
python scripts/kaptia_packager.py --enable-plugin vendor.adapter-id
\`\`\`

No third-party entry point is loaded by default. Duplicate format registrations are rejected. Adapter errors are returned as bounded error details.

**Trust boundary:** Python entry points execute in the same process and with the same OS permissions as KaptiaLab. Explicit enablement is consent, not sandboxing. Only enable adapters from trusted publishers. A future isolated worker process should be used for untrusted extensions; do not describe in-process adapters as sandboxed.

## Security invariants

- Archive member paths must be relative and remain inside the selected destination.
- ZIP symbolic links and TAR links, devices and FIFOs are rejected.
- Input paths must resolve to regular files inside the selected source root; symlink inputs are rejected.
- Default limits: 2 GiB compressed input, 20,000 entries, 8 GiB expanded data and 200:1 compression ratio.
- ZIP extraction does not call \`extractall\`; TAR extraction does not call \`extractall\`.
- EXE/MSI content is never executed. WHL content is never installed.
- SHA-256 is computed for generated artifacts and during verification.
- Binary payloads never travel inside JSON-RPC messages.

These controls reduce common archive and path attacks. They do not replace Windows ACLs, antivirus scanning, publisher signature validation, or isolation for untrusted plugins.
