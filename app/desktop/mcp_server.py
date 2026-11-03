"""Minimal MCP stdio server for Desktop-only external AI task submission.

Protocol transport: newline-delimited JSON-RPC 2.0 over stdin/stdout.
This server only queues requests in SQLite. It never executes tools or approves work.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hmac

from .external_ai_bridge import ALLOWED_ACTIONS, MAX_ACTIONS, MAX_TASK_CHARS, MAX_TTL_SECONDS, PROTOCOL_VERSION

SERVER_NAME = "kaptialab-desktop-bridge"
SERVER_VERSION = "0.1.0"
MAX_LINE_BYTES = 64 * 1024


class MCPProtocolError(ValueError):
    pass


class MCPTaskService:
    def __init__(self, db_path: str | Path, pairing_token: str, *, desktop_enabled: bool) -> None:
        if desktop_enabled is not True:
            raise RuntimeError("MCP delegation server is available only in Kaptia Desktop.")
        if not isinstance(pairing_token, str) or len(pairing_token) < 32:
            raise ValueError("KAPTIA_DELEGATION_TOKEN must contain at least 32 characters.")
        self.db_path = str(db_path)
        self._token = pairing_token
        Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS delegated_tasks (
                request_id TEXT PRIMARY KEY, sender TEXT NOT NULL, task TEXT NOT NULL,
                requested_actions TEXT NOT NULL, received_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending_approval'
            )""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def submit_task(self, args: dict[str, Any]) -> dict[str, Any]:
        token = args.get("pairing_token")
        if not isinstance(token, str) or not hmac.compare_digest(token, self._token):
            raise MCPProtocolError("Pairing token rejected.")
        request_id, sender, task = args.get("request_id"), args.get("sender"), args.get("task")
        actions, expires_at = args.get("requested_actions"), args.get("expires_at")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise MCPProtocolError("request_id must be 1–128 characters.")
        if not isinstance(sender, str) or not 1 <= len(sender.strip()) <= 80:
            raise MCPProtocolError("sender must be 1–80 characters.")
        if not isinstance(task, str) or not task.strip() or len(task) > MAX_TASK_CHARS:
            raise MCPProtocolError("task is empty or exceeds the 12,000-character limit.")
        if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
            raise MCPProtocolError("requested_actions must contain 1–8 actions.")
        if any(not isinstance(a, str) or a not in ALLOWED_ACTIONS for a in actions) or len(set(actions)) != len(actions):
            raise MCPProtocolError("requested_actions contains unsupported or duplicate actions.")
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expires.tzinfo is None:
                raise ValueError("timezone required")
        except (AttributeError, TypeError, ValueError):
            raise MCPProtocolError("expires_at must be timezone-aware ISO-8601.") from None
        now = datetime.now(timezone.utc)
        ttl = (expires.astimezone(timezone.utc) - now).total_seconds()
        if ttl <= 0 or ttl > MAX_TTL_SECONDS:
            raise MCPProtocolError("Request expired or exceeds the 15-minute lifetime.")
        with self._connect() as db:
            count = db.execute("SELECT COUNT(*) FROM delegated_tasks WHERE status='pending_approval'").fetchone()[0]
            if count >= 20:
                raise MCPProtocolError("Desktop approval inbox is full.")
            try:
                db.execute("""INSERT INTO delegated_tasks
                    (request_id,sender,task,requested_actions,received_at,expires_at,status)
                    VALUES (?,?,?,?,?,?, 'pending_approval')""",
                    (request_id, sender.strip(), task.strip(), json.dumps(actions), now.isoformat(), expires.astimezone(timezone.utc).isoformat()))
            except sqlite3.IntegrityError:
                raise MCPProtocolError("Duplicate request_id.") from None
        return {"request_id": request_id, "status": "pending_approval", "message": "Queued for local approval; no action has been executed."}

    def get_task_status(self, args: dict[str, Any]) -> dict[str, Any]:
        request_id = args.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise MCPProtocolError("request_id is required.")
        with self._connect() as db:
            row = db.execute("SELECT request_id,sender,requested_actions,received_at,expires_at,status FROM delegated_tasks WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            return {"found": False, "request_id": request_id}
        if row["status"] == "pending_approval" and datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            with self._connect() as db:
                db.execute("DELETE FROM delegated_tasks WHERE request_id=? AND status='pending_approval'", (request_id,))
            return {"found": False, "request_id": request_id, "reason": "expired"}
        return {"found": True, **dict(row), "requested_actions": json.loads(row["requested_actions"])}

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise MCPProtocolError("Expected JSON-RPC 2.0 message.")
        method, msg_id = message.get("method"), message.get("id")
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return {"jsonrpc":"2.0","id":msg_id,"result":{
                "protocolVersion":"2024-11-05",
                "capabilities":{"tools":{"listChanged":False}},
                "serverInfo":{"name":SERVER_NAME,"version":SERVER_VERSION}
            }}
        if method == "ping":
            return {"jsonrpc":"2.0","id":msg_id,"result":{}}
        if method == "tools/list":
            return {"jsonrpc":"2.0","id":msg_id,"result":{"tools":[
                {"name":"submit_task","description":"Submit a task to Kaptia Desktop for local user approval. This tool never executes the task.","inputSchema":{"type":"object","properties":{
                    "pairing_token":{"type":"string","description":"Local Desktop pairing token"},
                    "request_id":{"type":"string"},"sender":{"type":"string"},"task":{"type":"string"},
                    "requested_actions":{"type":"array","items":{"type":"string","enum":sorted(ALLOWED_ACTIONS)}},
                    "expires_at":{"type":"string","description":"Timezone-aware ISO-8601 timestamp, at most 15 minutes ahead"}
                },"required":["pairing_token","request_id","sender","task","requested_actions","expires_at"]}},
                {"name":"get_task_status","description":"Read whether a previously submitted task is still awaiting local approval.","inputSchema":{"type":"object","properties":{"request_id":{"type":"string"}},"required":["request_id"]}}
            ]}}
        if method == "tools/call":
            params = message.get("params") or {}
            name, args = params.get("name"), params.get("arguments") or {}
            try:
                if name == "submit_task":
                    result = self.submit_task(args)
                elif name == "get_task_status":
                    result = self.get_task_status(args)
                else:
                    raise MCPProtocolError("Unknown tool.")
                return {"jsonrpc":"2.0","id":msg_id,"result":{"content":[{"type":"text","text":json.dumps(result, ensure_ascii=False)}],"isError":False}}
            except (MCPProtocolError, TypeError, ValueError) as exc:
                return {"jsonrpc":"2.0","id":msg_id,"result":{"content":[{"type":"text","text":str(exc)}],"isError":True}}
        if msg_id is not None:
            return {"jsonrpc":"2.0","id":msg_id,"error":{"code":-32601,"message":"Method not found"}}
        return None


def main() -> int:
    if os.environ.get("KAPTIA_DESKTOP") != "1":
        print("Kaptia MCP bridge can only run from Kaptia Desktop.", file=sys.stderr)
        return 2
    token = os.environ.get("KAPTIA_DELEGATION_TOKEN", "")
    db_path = os.environ.get("KAPTIA_DELEGATION_DB", str(Path.home() / ".kaptiaLab" / "delegation.sqlite3"))
    try:
        service = MCPTaskService(db_path, token, desktop_enabled=True)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Kaptia MCP bridge startup failed: {exc}", file=sys.stderr)
        return 2
    for raw in sys.stdin.buffer:
        if len(raw) > MAX_LINE_BYTES:
            continue
        try:
            message = json.loads(raw.decode("utf-8"))
            response = service.handle(message)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except (UnicodeDecodeError, json.JSONDecodeError, MCPProtocolError):
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
