# Time-for-Quality Research Runtime

Status: M1 extension. The engine and test doubles are implemented as adapter-based components. A production search provider, hardened page fetcher and Qwen runtime adapters must still be configured.

## Flow
1. Accept a bounded research request.
2. Search through SearchProvider.
3. Validate URL policy and fetch bounded HTML/plain text through PageFetcher.
4. Treat all retrieved content as untrusted evidence, never instructions.
5. Deduplicate by content hash and preserve URL, domain, dates and provenance.
6. Synthesize with the configured local model and request evidence-gap review.
7. Repeat while quality is insufficient and round, search, source, time and optional energy budgets remain.
8. Archive only reports passing deterministic source/domain gates.

## Resource policy
ResearchBudget independently caps rounds, searches, unique sources, wall time and optional watt-hours. EnergyMeter must use platform telemetry; token counts are not a valid electricity measurement.

## Quality semantics
The deterministic score measures source volume, distinct domains and non-empty synthesis. It is not a fact-checking oracle. The model reviewer may request more searches but cannot override the deterministic archive gate.

## Security
- Page text and search snippets are untrusted input.
- Only HTTP/HTTPS URLs are accepted; local hostnames, credentials and literal non-public IP addresses are rejected.
- A production fetcher must validate DNS answers and every redirect, block private/link-local/reserved IPs, cap redirects, enforce response size/time limits and validate the connected peer to mitigate SSRF and DNS rebinding.
- Never execute page scripts or page-provided commands.
- Never send local_only or private user content to third-party search services. Classify and minimize queries before online research.
- A fetched page must not gain access to prompts, local files, credentials or tools.

## Remaining integration
Configure a real search provider and hardened fetcher; connect Qwen 8B to synthesizer/reviewer; add quality-mode UI and cloud consent; implement watt-hour telemetry; add controlled HTTP security tests; connect archive retrieval to Hybrid Memory with expiry and refresh policies.
