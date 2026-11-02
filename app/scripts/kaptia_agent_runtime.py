"""Permission-gated local workspace tools and bounded Agent planning.

The model may propose a small JSON plan, but cannot execute shell commands or write
files directly. Read access is session-scoped; file changes are staged and require
an explicit UI confirmation plus an unchanged-file check before atomic replacement.
"""
from __future__ import annotations

import hashlib
import difflib
import json
import os
import stat
import re
import threading
import uuid
from pathlib import Path
from typing import Any

MAX_PLAN_STEPS = 6
MAX_FILE_BYTES = 1_000_000
MAX_SEARCH_FILES = 500
MAX_SEARCH_BYTES = 10_000_000
MAX_WRITE_BYTES = 1_000_000
MAX_PENDING_CHANGES = 20
ALLOWED_ACTIONS = {"list_files", "read_file", "search_text", "propose_write"}
IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".kaptia-backups"}


def _safe_relative(value: str, allow_empty: bool = False) -> Path:
    if not isinstance(value, str):
        raise ValueError("工作區路徑必須是文字")
    value = value.strip()
    if not value and allow_empty:
        return Path(".")
    if not value or len(value) > 500:
        raise ValueError("工作區相對路徑不可為空或超過 500 字元")
    raw = Path(value)
    if value.startswith(("/", "\\\\")) or ":" in value or raw.is_absolute() or any(part in {"..", ""} for part in raw.parts):
        raise ValueError("只允許工作區內的相對路徑，不允許 .. 或絕對路徑")
    if any(part.startswith("~") for part in raw.parts):
        raise ValueError("不允許家目錄捷徑")
    if any((part.startswith(".") and part != ".") or part in IGNORED_DIRS for part in raw.parts):
        raise ValueError("隱藏檔案與受保護的相依目錄不可由 Agent 讀取或修改")
    return raw


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_linklike(path: Path) -> bool:
    """Reject symlinks and Windows reparse points (including junctions)."""
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        return False


def parse_agent_plan(raw: str) -> dict[str, Any]:
    """Parse and strictly validate model-proposed JSON; never execute during parsing."""
    if not isinstance(raw, str) or len(raw) > 100_000:
        raise ValueError("Agent 計畫內容無效或超過大小限制")
    text = raw.strip()
    text = re.sub(r"^\`\`\`(?:json)?\s*|\s*\`\`\`$", "", text, flags=re.I)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Agent 計畫不是有效 JSON；請重新產生計畫") from exc
    if not isinstance(data, dict):
        raise ValueError("Agent 計畫根節點必須是物件")
    goal = data.get("goal")
    if not isinstance(goal, str) or not goal.strip() or len(goal) > 500:
        raise ValueError("Agent 計畫缺少有效 goal")
    steps = data.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_PLAN_STEPS:
        raise ValueError(f"Agent 計畫必須包含 1 到 {MAX_PLAN_STEPS} 個步驟")
    result, seen = [], set()
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise ValueError(f"第 {index} 個步驟格式無效")
        step_id = str(step.get("id", f"S{index}")).strip()
        action = str(step.get("action", "")).strip()
        reason = str(step.get("reason", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", step_id) or step_id in seen:
            raise ValueError(f"第 {index} 個步驟 ID 無效或重複")
        seen.add(step_id)
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"不允許的 Agent 動作：{action}")
        if not reason or len(reason) > 500:
            raise ValueError(f"第 {index} 個步驟缺少有效 reason")
        item = {"id": step_id, "action": action, "reason": reason}
        if action == "list_files":
            item["target"] = str(step.get("target", "."))
            _safe_relative(item["target"], allow_empty=True)
        elif action == "read_file":
            item["target"] = str(step.get("target", ""))
            _safe_relative(item["target"])
        elif action == "search_text":
            query = step.get("query")
            if not isinstance(query, str) or not query.strip() or len(query) > 200:
                raise ValueError(f"第 {index} 個步驟搜尋字串無效")
            item["query"] = query.strip()
        else:
            item["target"] = str(step.get("target", ""))
            _safe_relative(item["target"])
            content = step.get("content")
            if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_WRITE_BYTES:
                raise ValueError(f"第 {index} 個步驟寫入內容無效或超過 1 MB")
            item["content"] = content
        result.append(item)
    return {"goal": goal.strip(), "steps": result}


def build_plan_prompt(user_request: str) -> str:
    if not isinstance(user_request, str) or not user_request.strip() or len(user_request) > 6000:
        raise ValueError("Agent 任務不可為空或超過 6,000 字元")
    schema = {
        "goal": "one-sentence task goal",
        "steps": [
            {"id": "S1", "action": "list_files", "target": ".", "reason": "why this step is needed"},
            {"id": "S2", "action": "read_file", "target": "relative/file.py", "reason": "why this step is needed"},
            {"id": "S3", "action": "search_text", "query": "symbol", "reason": "why this step is needed"},
            {"id": "S4", "action": "propose_write", "target": "relative/file.py", "content": "complete replacement content", "reason": "why this change is needed"},
        ],
    }
    return (
        "你是 Kaptia 的任務規劃器。只輸出 JSON，不要 Markdown。"
        "規劃 1 到 6 個可驗證步驟，僅允許 list_files、read_file、search_text、propose_write。"
        "禁止 shell、命令列、執行程式、網路、刪除檔案、安裝軟體或任何未列出的動作。"
        "所有 target 必須是工作區相對路徑。propose_write 只提出完整內容，不代表已寫入；"
        "寫入一定要由使用者在 UI 預覽後另行確認。資料夾未授權讀取時，不要假設可讀。"
        f"JSON 結構參考：{json.dumps(schema, ensure_ascii=False)}\n\n使用者任務：\n{user_request}"
    )


class WorkspaceSandbox:
    """Session-scoped workspace permissions and staged file changes."""

    def __init__(self):
        self.root: Path | None = None
        self.read_enabled = False
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def set_root(self, root: str | Path) -> str:
        path = Path(root).expanduser()
        if _is_linklike(path) or not path.exists() or not path.is_dir():
            raise ValueError("選取的工作區必須是存在的資料夾，且不能是符號連結")
        resolved = path.resolve(strict=True)
        with self._lock:
            self.root = resolved
            self.read_enabled = False
            self._pending.clear()
        return str(resolved)

    def grant_read(self, enabled: bool) -> bool:
        with self._lock:
            if enabled and self.root is None:
                raise ValueError("請先選擇工作區資料夾")
            self.read_enabled = bool(enabled)
            if not self.read_enabled:
                self._pending.clear()
            return self.read_enabled

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "root": str(self.root) if self.root else "",
                "selected": self.root is not None,
                "read_enabled": self.read_enabled,
                "pending_changes": len(self._pending),
                "write_policy": "每次寫入都必須在 UI 明確確認",
            }

    def _resolve(self, relative: str, allow_empty: bool = False) -> Path:
        with self._lock:
            if self.root is None:
                raise PermissionError("尚未選擇工作區")
            if not self.read_enabled:
                raise PermissionError("尚未授權本工作階段讀取工作區")
            rel = _safe_relative(relative, allow_empty=allow_empty)
            candidate = self.root / rel
            current = self.root
            for part in rel.parts:
                if part == ".":
                    continue
                current = current / part
                if _is_linklike(current):
                    raise PermissionError("工作區路徑包含符號連結，已拒絕存取")
            resolved = candidate.resolve(strict=False)
            try:
                resolved.relative_to(self.root)
            except ValueError as exc:
                raise PermissionError("路徑超出已選取的工作區") from exc
            return resolved

    def list_files(self, relative: str = ".") -> list[dict[str, Any]]:
        folder = self._resolve(relative, allow_empty=True)
        if not folder.is_dir():
            raise ValueError("指定路徑不是資料夾")
        result = []
        for item in sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold())):
            if _is_linklike(item) or item.name in IGNORED_DIRS or item.name.startswith("."):
                continue
            try:
                result.append({"name": item.name, "path": item.relative_to(self.root).as_posix(),
                               "is_dir": item.is_dir(), "size": item.stat().st_size if item.is_file() else None})
            except OSError:
                continue
            if len(result) >= 100:
                break
        return result

    def read_file(self, relative: str) -> dict[str, Any]:
        path = self._resolve(relative)
        if _is_linklike(path) or not path.is_file():
            raise ValueError("指定路徑不是一般檔案")
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError("檔案超過 1 MB 讀取上限")
        data = path.read_bytes()
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("目前只支援 UTF-8 文字檔") from exc
        return {"path": path.relative_to(self.root).as_posix(), "content": content, "sha256": _sha256(data), "bytes": len(data)}

    def search_text(self, query: str) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            raise ValueError("搜尋字串無效")
        root = self._resolve(".")
        results, scanned, scanned_bytes = [], 0, 0
        for base, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")
                       and not _is_linklike(Path(base) / d)]
            for name in files:
                if name.startswith(".") or name in IGNORED_DIRS:
                    continue
                path = Path(base) / name
                try:
                    if _is_linklike(path) or path.stat().st_size > MAX_FILE_BYTES:
                        continue
                    scanned += 1
                    if scanned > MAX_SEARCH_FILES:
                        return results
                    data = path.read_bytes()
                    scanned_bytes += len(data)
                    if scanned_bytes > MAX_SEARCH_BYTES:
                        return results
                    text = data.decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for line_no, line in enumerate(text.splitlines(), 1):
                    if query.casefold() in line.casefold():
                        results.append({"path": path.relative_to(root).as_posix(), "line": line_no, "text": line[:400]})
                        if len(results) >= 20:
                            return results
        return results

    def stage_write(self, relative: str, content: str) -> dict[str, Any]:
        path = self._resolve(relative)
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            raise ValueError("寫入內容必須是 UTF-8 文字且不可超過 1 MB")
        if not path.parent.exists() or not path.parent.is_dir():
            raise ValueError("目標資料夾不存在；不會自動建立目錄")
        if path.exists() and (_is_linklike(path) or not path.is_file()):
            raise ValueError("只允許建立一般文字檔或修改一般檔案")
        if path.exists() and getattr(path.stat(), "st_nlink", 1) > 1:
            raise ValueError("不允許修改具有多個硬連結的檔案")
        old_data = path.read_bytes() if path.exists() else None
        try:
            old_text = old_data.decode("utf-8") if old_data is not None else ""
        except UnicodeDecodeError as exc:
            raise ValueError("目前只允許修改 UTF-8 文字檔") from exc
        diff = "".join(difflib.unified_diff(
            old_text.splitlines(keepends=True), content.splitlines(keepends=True),
            fromfile=f"a/{relative}", tofile=f"b/{relative}",
        ))
        change_id = uuid.uuid4().hex
        change = {
            "change_id": change_id,
            "path": path.relative_to(self.root).as_posix(),
            "original_sha256": _sha256(old_data) if old_data is not None else None,
            "new_content": content,
            "new_sha256": _sha256(content.encode("utf-8")),
            "preview": diff[:12000] if diff else "(檔案內容沒有差異)",
            "created": True if old_data is None else False,
            "bytes": len(content.encode("utf-8")),
        }
        with self._lock:
            if len(self._pending) >= MAX_PENDING_CHANGES:
                raise ValueError(f"待確認變更已達 {MAX_PENDING_CHANGES} 筆上限，請先套用或取消舊變更。")
            self._pending[change_id] = change
        return {k: v for k, v in change.items() if k != "new_content"}

    def apply_staged_write(self, change_id: str, approved: bool = False) -> dict[str, Any]:
        if approved is not True:
            raise PermissionError("檔案寫入必須由使用者明確確認")
        with self._lock:
            if self.root is None or not self.read_enabled:
                raise PermissionError("工作區讀取權限已撤銷；待套用變更已清除")
            change = self._pending.get(str(change_id))
            if not change:
                raise ValueError("找不到待套用的變更，可能已過期")
            path = self._resolve(change["path"])
            current = path.read_bytes() if path.exists() else None
            current_hash = _sha256(current) if current is not None else None
            if current_hash != change["original_sha256"]:
                raise RuntimeError("檔案在預覽後已變更；為避免覆蓋新內容，請重新產生變更預覽")
            if current is not None:
                backup_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Kaptia" / "workspace-backups"
                backup_root.mkdir(parents=True, exist_ok=True)
                backup_path = backup_root / f"{change_id}.bak"
                backup_path.write_bytes(current)
            temp = path.with_name(path.name + f".{change_id}.tmp")
            try:
                temp.write_text(change["new_content"], encoding="utf-8", newline="\n")
                os.replace(temp, path)
            finally:
                if temp.exists():
                    temp.unlink()
            del self._pending[str(change_id)]
            return {"ok": True, "path": change["path"], "backup": str(backup_path) if current is not None else None,
                    "sha256": change["new_sha256"], "created": change["created"]}


def create_agent_plan(generate, user_request: str) -> dict[str, Any]:
    """Ask the local model for a plan and validate it without executing any action."""
    raw = generate([{"role": "user", "content": build_plan_prompt(user_request)}],
                   max_new_tokens=768, temperature=0.1)
    plan = parse_agent_plan(raw)
    plan["plan_id"] = uuid.uuid4().hex
    return plan
