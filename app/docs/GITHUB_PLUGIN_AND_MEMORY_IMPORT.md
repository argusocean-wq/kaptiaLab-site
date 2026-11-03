# GitHub Plugin and Memory Import

## GitHub Desktop plugin

The integration is exposed only through Kaptia Desktop's Python bridge. It uses the official GitHub REST API over HTTPS.

### Setup
1. Install the optional dependency after confirming in Desktop: `python -m pip install -r app/requirements-github.txt`.
2. Create a GitHub fine-grained Personal Access Token for the selected repositories. Grant only the required repository permissions:
   - Metadata: read
   - Contents: read and write
   - Pull requests: read and write
   - Actions: read (only needed to inspect CI runs)
3. Paste the token into the Desktop connection field. Kaptia validates it against `GET /user` and stores it with the operating-system credential vault via `keyring`. There is no plaintext-file fallback.
4. Select the repository explicitly.

### Supported operations
- List repositories and branches.
- Read UTF-8 text files (maximum 1 MB).
- Create a branch from a selected base branch.
- Create or update a file on a selected branch.
- Open a draft Pull Request.
- Inspect recent GitHub Actions workflow runs.
- Kaptia's AI tool loop can list accessible repositories, inspect branches/files in the Repository explicitly selected in Desktop, inspect CI, and propose branch/file/PR operations. Repository selection remains a local user action. AI write tools only enqueue a proposal; they cannot execute it.
- Desktop shows the proposed file diff and operation metadata. The user must approve or reject each proposal in the GitHub page. Kaptia file writes (AI proposals and Desktop editor writes) are blocked on the Repository's default branch; create and select a feature branch first.

### Write safety
- Branch creation, file writes and Pull Request creation require a separate local approval on each call.
- Pull Requests are created as drafts.
- AI proposals are held in a bounded in-memory queue for up to 30 minutes; closing Kaptia discards unapproved proposals without making remote changes.
- No merge, delete-file, force-push, arbitrary GitHub API path, shell, or repository-wide permission escalation is exposed.
- File paths and branch names are validated; file and response sizes are bounded.
- Token is not included in model tool schemas, prompts, logs or repository settings. Disconnect removes the stored credential.
- GitHub permissions are ultimately bounded by the token's own scopes. Do not grant access to repositories the user does not want Kaptia to modify.

The plugin does not silently push changes to the default branch. Recommended workflow: inspect → create feature branch → edit → inspect diff locally → create draft PR → review CI → user merges on GitHub.

## Importing existing AI memory

The Memory page supports preview-first import of:
- ChatGPT data export `conversations.json` (conversation mapping format).
- Generic JSON or JSONL with `role` and `content` fields.
- Markdown and plain-text notes.

Limits: 4 MB per file, 2,000 messages, 20,000 characters per message. Unsupported roles (system/tool) are excluded. Markdown/TXT is imported as one user reference message.

Import workflow:
1. Select a file.
2. Inspect source name, SHA-256, message counts and sample excerpts.
3. Confirm import locally.
4. Kaptia appends messages to local conversation history and archives overflow using its existing bounded-history policy.

Imported messages are deduplicated against messages currently in the active conversation file by role and exact content (the compressed archive is not globally scanned for duplicates). Imported text is conversation data, not system instructions; it cannot change Kaptia's policy or grant permissions. The file's SHA-256 is checked again at confirmation so a file changed after preview must be previewed again. Imported content remains on the local device and is not uploaded to GitHub.

## Current limitations
- No OAuth browser flow; users supply a fine-grained PAT themselves.
- No GitHub Issues/Projects, release publishing, merge, deletion, binary-file editing, or automated conflict resolution.
- The first version supports UTF-8 text files only. The AI tool loop reads at most 5,000 characters per file to prevent truncated source from being treated as a complete file; larger files can still be inspected and edited manually in the Desktop editor (up to 1 MB).
- Import currently preserves conversation history rather than automatically distilling it into verified structured facts. Imported statements should be checked before being saved as confirmed personal/project facts.
- External provider export formats other than the documented generic role/content JSON/JSONL and text formats may require an adapter.
