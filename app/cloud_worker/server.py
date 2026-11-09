"""Hardened launcher for the Linux Docker Worker.

Default bind is loopback for a TLS reverse proxy. Direct non-loopback binding requires
mTLS server credentials and a client CA. Do not launch uvicorn directly on a public IP.
"""
from __future__ import annotations

import ipaddress
import os
import ssl

import uvicorn

from security.identity import build_server_ssl_context, mtls_required


def main() -> None:
    host = os.environ.get("KAPTIA_CLOUD_HOST", "127.0.0.1").strip()
    port = int(os.environ.get("KAPTIA_CLOUD_PORT", "8787"))
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = False

    required = mtls_required()
    if not is_loopback and not required:
        raise RuntimeError(
            "Refusing direct non-loopback bind without mTLS. Set KAPTIA_MTLS_REQUIRED=1 "
            "and configure server certificate, private key and client CA."
        )

    options = {"host": host, "port": port, "log_level": "info", "access_log": False, "proxy_headers": False}
    if required:
        build_server_ssl_context()
        options.update({
            "ssl_certfile": os.environ["KAPTIA_MTLS_SERVER_CERT"],
            "ssl_keyfile": os.environ["KAPTIA_MTLS_SERVER_KEY"],
            "ssl_ca_certs": os.environ["KAPTIA_MTLS_CLIENT_CA_FILE"],
            "ssl_cert_reqs": ssl.CERT_REQUIRED,
            "ssl_version": ssl.PROTOCOL_TLS_SERVER,
        })
    uvicorn.run("cloud_worker.app:app", **options)


if __name__ == "__main__":
    main()
