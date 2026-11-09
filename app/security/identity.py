"""TLS 1.2+ and optional mutual-TLS certificate configuration."""
from __future__ import annotations

import os
import ssl
from pathlib import Path


class SecurityConfigurationError(RuntimeError):
    pass


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def mtls_required(env=None) -> bool:
    source = os.environ if env is None else env
    return _enabled(source.get("KAPTIA_MTLS_REQUIRED"))


def _pair(env, cert_key: str, private_key_key: str) -> tuple[str | None, str | None]:
    cert = str(env.get(cert_key, "")).strip() or None
    key = str(env.get(private_key_key, "")).strip() or None
    if bool(cert) != bool(key):
        raise SecurityConfigurationError(f"{cert_key} and {private_key_key} must be configured together")
    for name, path in ((cert_key, cert), (private_key_key, key)):
        if path and not Path(path).is_file():
            raise SecurityConfigurationError(f"{name} file does not exist")
    return cert, key


def build_client_ssl_context(env=None) -> ssl.SSLContext:
    source = os.environ if env is None else env
    ca = str(source.get("KAPTIA_MTLS_CA_FILE", "")).strip() or None
    if ca and not Path(ca).is_file():
        raise SecurityConfigurationError("KAPTIA_MTLS_CA_FILE does not exist")
    cert, key = _pair(source, "KAPTIA_MTLS_CLIENT_CERT", "KAPTIA_MTLS_CLIENT_KEY")
    if mtls_required(source) and not cert:
        raise SecurityConfigurationError(
            "Mutual TLS is required but KAPTIA_MTLS_CLIENT_CERT / KAPTIA_MTLS_CLIENT_KEY are missing"
        )
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    if cert:
        context.load_cert_chain(certfile=cert, keyfile=key)
    return context


def build_server_ssl_context(env=None) -> ssl.SSLContext:
    source = os.environ if env is None else env
    cert, key = _pair(source, "KAPTIA_MTLS_SERVER_CERT", "KAPTIA_MTLS_SERVER_KEY")
    ca = str(source.get("KAPTIA_MTLS_CLIENT_CA_FILE", "")).strip() or None
    if not cert or not ca:
        raise SecurityConfigurationError(
            "mTLS server requires KAPTIA_MTLS_SERVER_CERT, KAPTIA_MTLS_SERVER_KEY "
            "and KAPTIA_MTLS_CLIENT_CA_FILE"
        )
    if not Path(ca).is_file():
        raise SecurityConfigurationError("KAPTIA_MTLS_CLIENT_CA_FILE does not exist")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=cert, keyfile=key)
    context.load_verify_locations(cafile=ca)
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def identity_status(env=None) -> dict:
    source = os.environ if env is None else env
    required = mtls_required(source)
    server_mode = any(str(source.get(key, "")).strip() for key in (
        "KAPTIA_MTLS_SERVER_CERT", "KAPTIA_MTLS_SERVER_KEY", "KAPTIA_MTLS_CLIENT_CA_FILE"
    ))
    try:
        if server_mode:
            cert, key = _pair(source, "KAPTIA_MTLS_SERVER_CERT", "KAPTIA_MTLS_SERVER_KEY")
            ca = str(source.get("KAPTIA_MTLS_CLIENT_CA_FILE", "")).strip() or None
            if ca and not Path(ca).is_file():
                raise SecurityConfigurationError("KAPTIA_MTLS_CLIENT_CA_FILE does not exist")
            configured = bool(cert and key and ca)
            ok = not required or configured
            return {
                "ok": ok,
                "mtls_required": required,
                "identity_side": "server",
                "server_certificate_configured": bool(cert and key),
                "client_ca_configured": bool(ca),
                "error": None if ok else "mTLS required but server certificate or client CA is missing",
            }

        cert, key = _pair(source, "KAPTIA_MTLS_CLIENT_CERT", "KAPTIA_MTLS_CLIENT_KEY")
        ca = str(source.get("KAPTIA_MTLS_CA_FILE", "")).strip() or None
        if ca and not Path(ca).is_file():
            raise SecurityConfigurationError("KAPTIA_MTLS_CA_FILE does not exist")
        configured = bool(cert and key)
        ok = not required or configured
        return {
            "ok": ok,
            "mtls_required": required,
            "identity_side": "client",
            "client_certificate_configured": configured,
            "server_ca_configured": bool(ca),
            "error": None if ok else "mTLS required but client certificate is missing",
        }
    except SecurityConfigurationError as exc:
        return {
            "ok": False,
            "mtls_required": required,
            "identity_side": "server" if server_mode else "client",
            "client_certificate_configured": False,
            "server_certificate_configured": False,
            "server_ca_configured": False,
            "client_ca_configured": False,
            "error": str(exc),
        }
