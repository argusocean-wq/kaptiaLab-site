# Public Windows installer build

The Windows installer is built from the `app/` directory in this public repository.

## Pull requests

A pull request that changes `app/**` runs the Windows build workflow. The workflow:

1. Checks out the exact pull-request commit.
2. Compiles the Python application and runs the Cloud Compute Worker API tests.
3. Creates a source archive with paths relative to the application root.
4. Embeds that archive and the WebView installer UI into `Kaptia-Setup.exe`.
5. Verifies the executable header, embedded archive, build metadata and SHA-256.
6. Uploads a short-lived validation artifact. It does not publish a Release.

## Main branch releases

After changes are merged into `main`, the same workflow builds the installer and publishes `Kaptia-Setup.exe` plus its checksum as a GitHub Release in this repository. The Pages workflow runs again when the Release is published and stages the latest installer on the official site.

No private core repository, private mirror token, Cloudflare Worker, or external model API is required by this release pipeline.

## Important boundaries

- A successful CI build proves packaging checks passed; it does not replace a real installation test on a clean Windows machine.
- The installer currently bootstraps a Python runtime and extracts a commit-pinned source archive. Runtime model weights and third-party assets remain subject to their upstream licenses.
- The Cloud Compute Worker is separately self-hosted by the user. Publishing the desktop installer does not provision a VPS or pay compute costs.
- Release artifacts are generated from the public source commit. Do not upload locally modified executables as official releases.
