# M1.2 Research Runtime Integration

The desktop runtime now exposes explicit research intent through \`/research <question>\` and clear natural-language web-research requests. It connects the existing DuckDuckGo search tool, a bounded HTTP(S) page fetcher, Qwen generation for synthesis/review, and the SQLite verified-knowledge archive.

## Network safety
The fetcher resolves DNS, rejects any non-global answer, pins the socket to the selected public IP, verifies TLS using the original hostname, disables proxy inheritance, manually validates each redirect, restricts ports to 80/443, limits response bytes, and only extracts HTML/plain text. It does not execute page scripts or follow page instructions.

## Research policy
The Qwen reviewer must return a JSON review. Invalid review output fails closed. A model's \`sufficient=true\` cannot bypass the deterministic minimum source and domain gates. Only passed reports are archived. Research is explicit opt-in in chat; ordinary conversation does not silently trigger network access.

## Limits
The current DuckDuckGo HTML adapter may be rate-limited or change markup. This integration does not make search coverage exhaustive. The score is an evidence-coverage heuristic, not a truth probability. Watt-hour telemetry remains optional and is not yet connected to Windows GPU/power APIs.
