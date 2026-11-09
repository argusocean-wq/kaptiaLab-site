"""Local administrative controls for the Linux Docker Worker Security Core."""
from __future__ import annotations

import argparse
import json

from security.manager import SecurityManager


def main() -> int:
    parser = argparse.ArgumentParser(description="Kaptia Linux Worker security administration")
    parser.add_argument("action", choices=("status", "lock", "unlock"))
    args = parser.parse_args()
    manager = SecurityManager()
    if args.action == "lock":
        manager.lockdown.set_enabled(True, "local_admin_cli")
        manager.event("local_lockdown_enabled", outcome="success")
    elif args.action == "unlock":
        manager.lockdown.set_enabled(False)
        manager.event("local_lockdown_disabled", outcome="success")
    print(json.dumps(manager.status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
