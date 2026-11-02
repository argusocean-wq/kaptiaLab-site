# Kaptia CLI

The CLI is a terminal entry point for Kaptia chat, diagnostics, and the consent-based Windows Attach workflow. It is not a general-purpose system shell.

## Start

From the installed Kaptia core directory (or a source checkout):

    python -m scripts.kaptia_cli --help
    python -m scripts.kaptia_cli chat
    python -m scripts.kaptia_cli chat --mode deep
    python -m scripts.kaptia_cli chat --provider openai-compatible
    python -m scripts.kaptia_cli doctor
    python -m scripts.kaptia_cli attach

Running the module without a subcommand starts interactive chat. Chat reuses existing local memory and model/API provider configuration. API credentials remain environment-variable-only.

## Attach console

The Attach console supports listing visible windows, explicitly attaching to one HWND, inspecting UI Automation controls, running OCR, proposing UIA/Vision actions, reviewing pending actions, and explicitly approving or rejecting them.

Example sequence:

    list
    connect 123456
    inspect <session_id>
    ocr <session_id>
    click <session_id> {"name":"Open","control_type":"Button"}
    pending
    approve <pending_id>
    detach <session_id>

For text entry:

    type <session_id> {"control_type":"Edit"} hello

For Vision actions:

    vision-click <session_id> 120 240
    vision-type <session_id> 120,240 hello

The console requires the exact confirmation string ATTACH <window_id> before creating a session and APPROVE <pending_id> before executing each queued action. It detaches all sessions when the console exits. Vision OCR dependencies are optional and can be installed from the Attach page in the desktop UI.

## Safety boundary

- No arbitrary shell command, arbitrary code evaluation, process-memory access, DLL injection, privilege elevation, or application launching.
- Only visible top-level windows can be discovered and attached.
- Each session is scoped to one HWND/PID and expires.
- UIA/Vision operations are bounded by the Attach implementation.
- Every state-changing action is queued and requires a second explicit approval.
- OCR text and coordinates are untrusted observations; review the pending action before approving it.
- The CLI does not bypass Windows UAC or protected desktop surfaces.


## Cloud Compute

Cloud Compute connects to a server rented and managed by the user. It is not an LLM API. Configure the worker endpoint and token in the desktop Cloud Compute page; the token is held in memory only and must be entered again after restarting Kaptia.

List supported hosting options:

    python -m scripts.kaptia_cli cloud providers

Test the configured worker:

    python -m scripts.kaptia_cli cloud test

Submit a Python or Blender script only after reviewing the file and confirming the transfer:

    python -m scripts.kaptia_cli cloud submit --type python_script --file ./job.py --timeout 900
    python -m scripts.kaptia_cli cloud submit --type blender_background --file ./render.py --timeout 1800

Check a remote job:

    python -m scripts.kaptia_cli cloud job <job_id>

Set KAPTIA_CLOUD_ENDPOINT and KAPTIA_CLOUD_TOKEN in the process environment when using the CLI outside the desktop session. The worker must use HTTPS and Docker. Only the documented task types are accepted; arbitrary shell commands are not exposed. See docs/CLOUD_COMPUTE.md for the worker deployment and provider support matrix.
