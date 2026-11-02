# Attach — Desktop Application Connection

Attach lets Kaptia connect to a visible, already-running Windows application window.

## User flow

1. Open **Attach 桌面連線**.
2. Scan visible top-level windows.
3. Select one exact window and confirm attachment.
4. Kaptia receives a short-lived session bound to that HWND and PID.
5. Inspect UI Automation controls. Each click or text-entry action requires a fresh user approval.
6. Detach at any time; sessions also expire after one hour and are cleared when the application exits.

## Initial capability boundary

- Windows visible top-level windows only; background services and headless processes are not listed.
- UI Automation inspection, exact-selector click on a small allowlist of control types, and bounded text entry into Edit/Document controls.
- Optional Vision OCR fallback and bounded coordinate click / ASCII text entry for windows with incomplete UI Automation support.
- No process-memory reads, DLL injection, shell execution, app launch, privilege elevation, or arbitrary file access.
- No automatic bypass of application security prompts.
- Some applications expose incomplete or no UI Automation trees. Such applications may be detectable but not controllable in this initial version.
- Actions that submit, save, delete, install, send, purchase, or otherwise create external/irreversible effects must receive a separate user confirmation in the UI.

## Optional dependency

Windows Setup installs pywinauto through the Windows-only entry in requirements.txt. For a separate development environment, install it with:

    python -m pip install -r requirements-attach.txt

If the optional dependency is unavailable, process/window discovery still works, but UI Automation inspection and interaction are unavailable.

## Vision fallback for applications without UI Automation

The Attach page includes an **Install Vision components** action. It runs the fixed requirements file in Kaptia’s own Python environment. Developers can also install the same optional dependencies manually:

    python -m pip install -r requirements-attach-vision.txt

The fallback captures only the attached, visible window using its current screen rectangle and runs RapidOCR in memory. It returns recognized text and coordinates relative to the top-left of that window. Captures are not persisted by this module. OCR can be wrong, and the UI must display that warning.

The current coordinate action queue supports a bounded click and ASCII text entry. The target window must still exist, retain the same PID, be non-minimized, and successfully become the foreground window at approval time. Coordinates are checked against the window bounds. A click or text entry is executed only after a fresh explicit approval in the Attach UI.

Limitations:
- RapidOCR may download its model assets on first initialization; install and warm up the optional engine while online before relying on offline use.
- Vision coordinate text entry currently supports ASCII only. Use UI Automation text fields for Unicode input.
- This initial fallback is not a full desktop recorder, does not capture other windows, and does not bypass secure desktop/UAC prompts.
- Capture currently uses a screen-region grab of the attached window, not the Windows Graphics Capture API. The window must be unobstructed and visible on the desktop; occluded regions, protected surfaces, exclusive full-screen rendering, unusual DPI scaling, or inaccessible windows may not be captured or controlled.
- Vision click/type operations are inherently less reliable than semantic UI Automation. The user should review the target and action before approval.

## Agent tools

- attach_list_running_apps
- attach_connect(window_id, user_approved)
- attach_inspect(session_id)
- attach_click(session_id, selector, user_approved)
- attach_type_text(session_id, selector, text, user_approved)
- attach_disconnect(session_id)
- attach_disconnect_all()

Tool calls that perform actions default to denied unless user_approved=true is supplied by the explicit UI approval path. A model-generated plan is not user approval.
