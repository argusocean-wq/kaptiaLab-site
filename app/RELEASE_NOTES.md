# Windows Setup rebuild

Build date: 2026-11-25

This release rebuilds the self-contained Windows installer from the current `kaptiaLab-site` application source snapshot.

The Windows CI workflow must pass compilation, regression tests, embedded-core archive checks, PE validation, SHA-256 generation, and the frozen-installer import smoke test before publishing the release.

This rebuild does not claim that the separate `kaptiaLab-core` draft pull requests have been merged or integrated into this source snapshot.
