"""Fail-closed source-network policy. Proxy forwarding headers are never trusted."""
from __future__ import annotations

import ipaddress
import os
from typing import Iterable

DEFAULT_TRUSTED_CIDRS = ("127.0.0.1/32", "::1/128")


def trusted_networks(raw: str | None = None) -> tuple[ipaddress._BaseNetwork, ...]:
    value = (os.environ.get("KAPTIA_WORKER_ALLOWED_CIDRS") or os.environ.get("KAPTIA_MAC_ALLOWED_CIDRS", "")) if raw is None else raw
    entries = [part.strip() for part in value.split(",") if part.strip()] if value.strip() else list(DEFAULT_TRUSTED_CIDRS)
    networks = []
    for entry in entries:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid trusted CIDR: {entry}") from exc
        # Prevent accidental exposure of the entire Tailscale CGNAT range or Internet.
        minimum_prefix = 24 if network.version == 4 else 64
        if network.prefixlen < minimum_prefix:
            raise ValueError(
                f"CIDR {entry} is too broad; use a single device (/32 or /128) "
                "or a narrowly scoped subnet (/24 IPv4 or /64 IPv6 or smaller)."
            )
        if network.is_unspecified or network.is_multicast:
            raise ValueError(f"CIDR {entry} is not a valid client network")
        networks.append(network)
    if not networks:
        return tuple(ipaddress.ip_network(item) for item in DEFAULT_TRUSTED_CIDRS)
    return tuple(networks)


def client_allowed(address: str, cidrs: str | None = None) -> bool:
    try:
        ip = ipaddress.ip_address(str(address or "").split("%", 1)[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return any(ip.version == network.version and ip in network for network in trusted_networks(cidrs))
    except (ValueError, TypeError):
        return False


def policy_summary(cidrs: str | None = None) -> dict:
    try:
        networks = trusted_networks(cidrs)
        return {"ok": True, "cidrs": [str(item) for item in networks], "count": len(networks)}
    except ValueError as exc:
        return {"ok": False, "cidrs": [], "count": 0, "error": str(exc)}
