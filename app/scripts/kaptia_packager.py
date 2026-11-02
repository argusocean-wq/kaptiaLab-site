"""Launch the UPTP JSON-RPC stdio server."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kaptia_packaging.protocol import JsonRpcStdioServer, PackagingService


def main() -> int:
    parser = argparse.ArgumentParser(description="KaptiaLab UPTP JSON-RPC stdio server")
    parser.add_argument("--enable-plugin", action="append", default=[],
                        help="Explicitly approve an installed adapter entry-point name")
    parser.add_argument("--workers", type=int, default=2, choices=range(1, 5))
    args = parser.parse_args()
    service = PackagingService(set(args.enable_plugin))
    JsonRpcStdioServer(service, workers=args.workers).serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
