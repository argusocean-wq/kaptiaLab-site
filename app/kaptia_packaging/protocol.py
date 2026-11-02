"""JSON-RPC 2.0 service and stdio transport for UPTP."""
from __future__ import annotations

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from . import PROTOCOL_VERSION
from .adapters import BUILTIN_ADAPTERS, PackagingError


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class PackagingService:
    """Dispatch UPTP operations to built-in and explicitly approved adapters."""

    def __init__(self, approved_plugin_ids: set[str] | None = None):
        self.adapters: dict[str, Any] = {}
        for adapter in BUILTIN_ADAPTERS:
            for fmt in adapter.formats:
                self.adapters[fmt.lower()] = adapter
        self.plugin_status: list[dict[str, str]] = []
        self._load_plugins(approved_plugin_ids or set())

    def _load_plugins(self, approved: set[str]) -> None:
        # Third-party code runs in-process. Nothing is loaded unless its exact
        # entry-point name was explicitly enabled by the user/operator.
        try:
            candidates = entry_points(group="kaptia.packaging.adapters.v1")
        except TypeError:  # Python 3.10 compatibility
            candidates = entry_points().get("kaptia.packaging.adapters.v1", [])
        for point in candidates:
            if point.name not in approved:
                self.plugin_status.append({"id": point.name, "status": "disabled"})
                continue
            try:
                factory = point.load()
                adapter = factory() if callable(factory) else factory
                manifest = getattr(adapter, "manifest", None)
                if not isinstance(manifest, dict):
                    raise ValueError("adapter must expose a manifest dictionary")
                required = ("schema_version", "plugin_id", "version", "publisher", "formats", "operations")
                if any(key not in manifest for key in required):
                    raise ValueError("manifest is missing required fields")
                if manifest["schema_version"] != 1 or manifest["plugin_id"] != point.name:
                    raise ValueError("manifest schema_version or plugin_id mismatch")
                if not all(isinstance(manifest[key], str) and manifest[key].strip()
                           for key in ("version", "publisher")):
                    raise ValueError("manifest version and publisher must be non-empty strings")
                adapter_id = str(getattr(adapter, "adapter_id", point.name))
                formats = tuple(str(x).lower().lstrip(".") for x in adapter.formats)
                caps = adapter.capabilities()
                declared_formats = tuple(str(x).lower().lstrip(".") for x in manifest["formats"])
                operations = tuple(str(x) for x in caps.get("operations", []))
                declared_operations = tuple(str(x) for x in manifest["operations"])
                if not formats or any(not x or "/" in x or x.find(chr(92)) >= 0 for x in formats):
                    raise ValueError("invalid formats declaration")
                if set(formats) != set(declared_formats) or set(operations) != set(declared_operations):
                    raise ValueError("manifest does not match runtime capabilities")
                if any(not callable(getattr(adapter, operation, None)) for operation in operations):
                    raise ValueError("adapter is missing an advertised operation method")
                for fmt in formats:
                    if fmt in self.adapters:
                        raise ValueError(f"format already registered: {fmt}")
                for fmt in formats:
                    self.adapters[fmt] = adapter
                self.plugin_status.append({"id": adapter_id, "status": "enabled"})
            except Exception as exc:
                self.plugin_status.append({"id": point.name, "status": "rejected",
                                           "reason": f"{type(exc).__name__}: {exc}"[:240]})

    def discover(self) -> dict[str, Any]:
        formats: dict[str, dict[str, Any]] = {}
        seen: set[int] = set()
        for adapter in self.adapters.values():
            if id(adapter) in seen:
                continue
            seen.add(id(adapter))
            caps = adapter.capabilities()
            for fmt in caps["formats"]:
                formats[fmt] = {"adapter_id": adapter.adapter_id,
                                "operations": list(caps["operations"])}
        return {"protocol_version": PROTOCOL_VERSION, "formats": formats,
                "plugins": self.plugin_status}

    def dispatch(self, method: str, params: dict[str, Any], cancel_event: threading.Event | None = None) -> Any:
        if not isinstance(params, dict):
            raise RpcError(-32602, "params must be an object")
        if method in ("rpc.discover", "DISCOVER"):
            return self.discover()
        if method in ("rpc.negotiate", "NEGOTIATE"):
            requested = params.get("protocol_version")
            if requested != PROTOCOL_VERSION:
                raise RpcError(-32001, "No mutually supported UPTP protocol version",
                               {"requested": requested, "supported": [PROTOCOL_VERSION]})
            return {"protocol_version": PROTOCOL_VERSION, "accepted": True}
        if method in ("adapter.capabilities", "CAPABILITIES"):
            fmt = self._format(params)
            adapter = self.adapters.get(fmt)
            if adapter is None:
                raise RpcError(-32601, f"Unsupported format: {fmt}")
            return {"adapter_id": adapter.adapter_id, **adapter.capabilities()}
        if method in ("pack", "PACK"):
            fmt = self._format(params)
            adapter = self._adapter(fmt, "pack")
            source_root = self._path(params, "source_root")
            output = self._path(params, "output")
            inputs = params.get("inputs")
            if not isinstance(inputs, list) or not all(isinstance(x, str) for x in inputs):
                raise RpcError(-32602, "inputs must be an array of relative path strings")
            return adapter.pack(source_root, inputs, output)
        if method in ("unpack", "UNPACK"):
            fmt = self._format(params)
            adapter = self._adapter(fmt, "unpack")
            archive = self._path(params, "archive")
            destination = self._path(params, "destination")
            return adapter.unpack(archive, destination)
        if method in ("inspect", "INSPECT"):
            fmt = self._format(params)
            adapter = self._adapter(fmt, "inspect")
            return adapter.inspect(self._path(params, "archive"))
        if method in ("verify", "VERIFY"):
            fmt = self._format(params)
            adapter = self._adapter(fmt, "verify")
            result = adapter.verify(self._path(params, "archive"))
            expected = params.get("expected_sha256")
            if expected is not None:
                if not isinstance(expected, str) or len(expected) != 64:
                    raise RpcError(-32602, "expected_sha256 must be a 64-character hex digest")
                actual = result.get("sha256")
                if actual is None or actual.lower() != expected.lower():
                    raise RpcError(-32010, "SHA-256 mismatch", {"actual": actual})
            return result
        raise RpcError(-32601, f"Method not found: {method}")

    def _format(self, params: dict[str, Any]) -> str:
        fmt = params.get("format")
        if not isinstance(fmt, str) or not fmt.strip():
            raise RpcError(-32602, "format is required")
        return fmt.lower().lstrip(".")

    def _adapter(self, fmt: str, operation: str) -> Any:
        adapter = self.adapters.get(fmt)
        if adapter is None:
            raise RpcError(-32601, f"Unsupported format: {fmt}")
        if operation not in adapter.capabilities().get("operations", []):
            raise RpcError(-32601, f"{operation} is not supported for {fmt}")
        return adapter

    def _path(self, params: dict[str, Any], key: str) -> Path:
        raw = params.get(key)
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise RpcError(-32602, f"{key} must be a non-empty filesystem path")
        path = Path(raw).expanduser()
        # Resolve the parent, not the leaf: output files may not exist yet.
        try:
            parent = path.parent.resolve(strict=True)
        except OSError as exc:
            raise RpcError(-32602, f"{key} parent directory does not exist") from exc
        if path.exists() and path.is_symlink():
            raise RpcError(-32602, f"{key} may not be a symbolic link")
        return parent / path.name


class JsonRpcStdioServer:
    """One JSON-RPC message per UTF-8 line; binary data always stays in files."""

    def __init__(self, service: PackagingService | None = None, workers: int = 2):
        self.service = service or PackagingService()
        self.executor = ThreadPoolExecutor(max_workers=max(1, min(workers, 4)))
        self.futures: dict[str | int, Future[Any]] = {}
        self.cancel_events: dict[str | int, threading.Event] = {}
        self.write_lock = threading.Lock()
        self.state_lock = threading.Lock()

    def _write(self, stream: Any, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.write_lock:
            stream.write(encoded + "\n")
            stream.flush()

    def _execute(self, request_id: str | int, method: str, params: dict[str, Any],
                 event: threading.Event) -> Any:
        if event.is_set():
            raise RpcError(-32800, "Request cancelled")
        return self.service.dispatch(method, params, event)

    def serve(self, source: Any, sink: Any) -> None:
        for raw in source:
            if len(raw.encode("utf-8")) > 1024 * 1024:
                self._write(sink, {"jsonrpc": "2.0", "id": None,
                                   "error": {"code": -32600, "message": "Request line exceeds 1 MiB"}})
                continue
            try:
                request = json.loads(raw)
                if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                    raise RpcError(-32600, "Invalid JSON-RPC 2.0 request")
                method = request.get("method")
                if not isinstance(method, str):
                    raise RpcError(-32600, "method must be a string")
                request_id = request.get("id")
                params = request.get("params", {})
                if method in ("cancel", "CANCEL"):
                    target = params.get("request_id") if isinstance(params, dict) else None
                    with self.state_lock:
                        event = self.cancel_events.get(target)
                        future = self.futures.get(target)
                        if event is not None:
                            event.set()
                        cancelled = bool(future and future.cancel())
                    if request_id is not None:
                        self._write(sink, {"jsonrpc": "2.0", "id": request_id,
                                           "result": {"cancellation_requested": event is not None,
                                                      "cancelled_before_start": cancelled}})
                    continue
                if request_id is None:
                    # Notifications are accepted only for discovery; all other
                    # notifications are ignored to avoid unobservable work.
                    if method not in ("rpc.discover", "DISCOVER"):
                        continue
                    self._write(sink, {"jsonrpc": "2.0", "method": "rpc.discover.result",
                                       "params": self.service.discover()})
                    continue
                if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
                    raise RpcError(-32600, "id must be a string or integer")
                event = threading.Event()
                with self.state_lock:
                    if request_id in self.futures:
                        raise RpcError(-32600, "Duplicate in-flight request id")
                    future = self.executor.submit(self._execute, request_id, method, params, event)
                    self.futures[request_id] = future
                    self.cancel_events[request_id] = event
                future.add_done_callback(lambda done, rid=request_id: self._complete(rid, done, sink))
            except RpcError as exc:
                if request.get("id") is not None:
                    self._write(sink, {"jsonrpc": "2.0", "id": request.get("id"),
                                       "error": {"code": exc.code, "message": str(exc), "data": exc.data}})
            except (json.JSONDecodeError, UnicodeError):
                self._write(sink, {"jsonrpc": "2.0", "id": None,
                                   "error": {"code": -32700, "message": "Parse error"}})
            except Exception as exc:
                rid = request.get("id") if isinstance(request, dict) else None
                if rid is not None:
                    self._write(sink, {"jsonrpc": "2.0", "id": rid,
                                       "error": {"code": -32603, "message": "Internal error",
                                                 "data": f"{type(exc).__name__}: {exc}"[:240]}})
        self.executor.shutdown(wait=True, cancel_futures=False)

    def _complete(self, request_id: str | int, future: Future[Any], sink: Any) -> None:
        try:
            result = future.result()
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RpcError as exc:
            response = {"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": exc.code, "message": str(exc), "data": exc.data}}
        except PackagingError as exc:
            response = {"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32020, "message": str(exc)}}
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32603, "message": "Internal error",
                                  "data": f"{type(exc).__name__}: {exc}"[:240]}}
        finally:
            with self.state_lock:
                self.futures.pop(request_id, None)
                self.cancel_events.pop(request_id, None)
        self._write(sink, response)
