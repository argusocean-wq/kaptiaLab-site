"""User-authorized GitHub integration for Kaptia Desktop.

Credentials are stored only through an OS keyring backend. Read operations are
available after connection; every repository write requires an explicit
per-call user_approved=True decision from the Desktop UI.
"""
from __future__ import annotations

import base64
import difflib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

API = "https://api.github.com"
SERVICE_NAME = "KaptiaLab.GitHub"
MAX_FILE_BYTES = 1_000_000
MAX_PENDING_PROPOSALS = 20
PROPOSAL_TTL_MINUTES = 30
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,180}$")
_PATH_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_.@/-]{1,500}$")


class GitHubPluginError(RuntimeError):
    pass


class GitHubPlugin:
    """Narrow GitHub REST client with keyring credentials and approval-gated writes."""

    def __init__(self, *, keyring_module=None, opener: Callable | None = None):
        self._keyring_module = keyring_module
        self._opener = opener or urllib.request.urlopen
        self._repository = ""
        self._default_branch = ""
        self._pending_proposals: dict[str, dict[str, Any]] = {}
        self._proposal_lock = threading.RLock()

    @property
    def current_repository(self) -> str:
        return self._repository

    @property
    def default_branch(self) -> str:
        return self._default_branch

    @staticmethod
    def _validate_repo(repository: str) -> str:
        if not isinstance(repository, str) or not _REPO_RE.fullmatch(repository):
            raise GitHubPluginError("Repository 必須使用 owner/repository 格式。")
        owner, name = repository.split("/", 1)
        if owner in {".", ".."} or name in {".", ".."}:
            raise GitHubPluginError("Repository 名稱無效。")
        return repository

    @staticmethod
    def _validate_branch(branch: str) -> str:
        if (not isinstance(branch, str) or not _BRANCH_RE.fullmatch(branch)
                or ".." in branch or "//" in branch or branch.endswith(("/", "."))
                or branch.endswith(".lock") or "@{" in branch):
            raise GitHubPluginError("Branch 名稱格式無效。")
        return branch

    @staticmethod
    def _validate_path(path: str) -> str:
        if not isinstance(path, str) or not _PATH_RE.fullmatch(path) or len(path) > 500:
            raise GitHubPluginError("Repository 檔案路徑無效。")
        if any(part in {"", ".", ".."} for part in path.split("/")):
            raise GitHubPluginError("Repository 檔案路徑含無效目錄片段。")
        return path

    def _get_keyring(self):
        if self._keyring_module is not None:
            return self._keyring_module
        try:
            import keyring
            backend = keyring.get_keyring()
            if getattr(backend, "priority", 0) <= 0:
                raise GitHubPluginError("目前沒有可用的作業系統憑證保存後端；拒絕明文保存 Token。")
            self._keyring_module = keyring
            return keyring
        except GitHubPluginError:
            raise
        except Exception as exc:
            raise GitHubPluginError("無法載入 OS Credential Manager；請安裝 requirements-github.txt。") from exc

    def connect(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or len(token.strip()) < 20 or any(c in token for c in "\r\n"):
            raise GitHubPluginError("GitHub Token 格式無效。")
        # Verify the credential before persisting it.
        self._request("GET", "/user", token=token.strip())
        try:
            self._get_keyring().set_password(SERVICE_NAME, "github-token", token.strip())
        except Exception as exc:
            raise GitHubPluginError("無法安全保存 Token；未改用明文檔案保存。") from exc
        self._repository = ""
        self._default_branch = ""
        self._pending_proposals.clear()
        return {"ok": True, "connected": True, "storage": "OS Credential Manager"}

    def disconnect(self) -> dict[str, Any]:
        try:
            keyring = self._get_keyring()
            try:
                keyring.delete_password(SERVICE_NAME, "github-token")
            except Exception as exc:
                errors = getattr(keyring, "errors", None)
                missing = getattr(errors, "PasswordDeleteError", ())
                if not missing or not isinstance(exc, missing):
                    raise
        except Exception as exc:
            raise GitHubPluginError("無法確認已從 OS Credential Manager 移除 Token。") from exc
        self._repository = ""
        self._default_branch = ""
        self._pending_proposals.clear()
        return {"ok": True, "connected": False, "credential_removed": True}

    def set_repository(self, repository: str) -> dict[str, str]:
        repository = self._validate_repo(repository)
        metadata = self._request("GET", f"/repos/{repository}")
        default_branch = metadata.get("default_branch", "")
        self._repository = repository
        self._default_branch = default_branch if isinstance(default_branch, str) else ""
        return {"repository": self._repository, "default_branch": self._default_branch}

    def _token(self) -> str:
        try:
            token = self._get_keyring().get_password(SERVICE_NAME, "github-token")
        except Exception as exc:
            raise GitHubPluginError("無法讀取 OS Credential Manager 中的 GitHub Token。") from exc
        if not token:
            raise GitHubPluginError("尚未連接 GitHub。")
        return token

    def _request(self, method: str, path: str, *, token: str | None = None,
                 payload: dict | None = None) -> Any:
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "://" in path:
            raise GitHubPluginError("拒絕非 GitHub API 路徑。")
        url = API + path
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=body, method=method, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + (token or self._token()),
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "KaptiaLab-Desktop",
            **({"Content-Type": "application/json"} if body is not None else {}),
        })
        try:
            with self._opener(request, timeout=20) as response:
                raw = response.read(MAX_FILE_BYTES + 1)
                if len(raw) > MAX_FILE_BYTES:
                    raise GitHubPluginError("GitHub 回應超過 1 MB 上限。")
                return json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:
            # Never echo request headers or the credential into logs/UI.
            detail = ""
            try:
                payload = json.loads(exc.read(4096).decode("utf-8"))
                detail = str(payload.get("message", ""))[:300]
            except Exception:
                pass
            raise GitHubPluginError(f"GitHub API 回應 HTTP {exc.code}" + (f"：{detail}" if detail else "")) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubPluginError(f"GitHub 連線失敗：{type(exc).__name__}") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GitHubPluginError("GitHub 回應不是有效 JSON。") from None

    def _repo_path(self, suffix: str) -> str:
        if not self._repository:
            raise GitHubPluginError("請先選擇 Repository。")
        return f"/repos/{self._repository}{suffix}"

    def list_repositories(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/user/repos?per_page=100&sort=updated&affiliation=owner,collaborator")
        return [{"full_name": x.get("full_name"), "private": x.get("private"),
                 "default_branch": x.get("default_branch"), "html_url": x.get("html_url")}
                for x in data if isinstance(x, dict)]

    def list_branches(self) -> list[str]:
        data = self._request("GET", self._repo_path("/branches?per_page=100"))
        return [x["name"] for x in data if isinstance(x, dict) and isinstance(x.get("name"), str)]

    def read_file(self, path: str, branch: str | None = None) -> dict[str, Any]:
        path = self._validate_path(path)
        query = "?ref=" + urllib.parse.quote(self._validate_branch(branch), safe="") if branch else ""
        data = self._request("GET", self._repo_path("/contents/" + urllib.parse.quote(path, safe="/")) + query)
        if data.get("type") != "file" or data.get("encoding") != "base64":
            raise GitHubPluginError("指定路徑不是一般文字檔案。")
        try:
            content = base64.b64decode(data.get("content", ""), validate=False).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            raise GitHubPluginError("檔案不是有效 UTF-8 文字，或內容無法解碼。") from None
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise GitHubPluginError("檔案超過 1 MB 編輯上限。")
        return {"path": path, "sha": data.get("sha"), "content": content,
                "html_url": data.get("html_url")}

    @staticmethod
    def _require_approval(user_approved: bool) -> None:
        if user_approved is not True:
            raise GitHubPluginError("此操作必須由使用者在 Kaptia Desktop 明確確認。")

    def create_branch(self, branch: str, base_branch: str, *, user_approved: bool = False) -> dict:
        self._require_approval(user_approved)
        branch, base_branch = self._validate_branch(branch), self._validate_branch(base_branch)
        base = self._request("GET", self._repo_path("/git/ref/heads/" + urllib.parse.quote(base_branch, safe="/")))
        sha = base.get("object", {}).get("sha")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise GitHubPluginError("無法取得基準分支 Commit SHA。")
        return self._request("POST", self._repo_path("/git/refs"),
                             payload={"ref": "refs/heads/" + branch, "sha": sha})

    def write_file(self, path: str, content: str, message: str, branch: str, *,
                   existing_sha: str | None = None, user_approved: bool = False) -> dict:
        self._require_approval(user_approved)
        path, branch = self._validate_path(path), self._validate_branch(branch)
        if self._default_branch and branch == self._default_branch:
            raise GitHubPluginError("不得直接修改 Repository 預設分支；請先建立功能分支。")
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise GitHubPluginError("新檔案內容必須是 UTF-8 文字且不超過 1 MB。")
        if not isinstance(message, str) or not message.strip() or len(message) > 200:
            raise GitHubPluginError("Commit message 必須為 1–200 字元。")
        if existing_sha is not None and (not isinstance(existing_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", existing_sha)):
            raise GitHubPluginError("既有檔案 SHA 格式無效。")
        payload = {"message": message.strip(), "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                   "branch": branch}
        if existing_sha:
            payload["sha"] = existing_sha
        return self._request("PUT", self._repo_path("/contents/" + urllib.parse.quote(path, safe="/")), payload=payload)

    def create_pull_request(self, title: str, body: str, head: str, base: str, *,
                            user_approved: bool = False) -> dict:
        self._require_approval(user_approved)
        head, base = self._validate_branch(head), self._validate_branch(base)
        if head == base:
            raise GitHubPluginError("Pull Request 的 Head 與 Base 必須不同。")
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise GitHubPluginError("Pull Request 標題必須為 1–200 字元。")
        if not isinstance(body, str) or len(body) > 10000:
            raise GitHubPluginError("Pull Request 描述不得超過 10,000 字元。")
        return self._request("POST", self._repo_path("/pulls"),
                             payload={"title": title.strip(), "body": body, "head": head, "base": base, "draft": True})

    def _queue_proposal(self, kind: str, payload: dict[str, Any], preview: dict[str, Any]) -> dict[str, Any]:
        if not self._repository:
            raise GitHubPluginError("請先在 Desktop 選擇 Repository。")
        now = datetime.now(timezone.utc)
        with self._proposal_lock:
            for key in [k for k, v in self._pending_proposals.items()
                        if datetime.fromisoformat(v["expires_at"]) <= now and v["status"] == "pending"]:
                del self._pending_proposals[key]
            if len([v for v in self._pending_proposals.values() if v["status"] == "pending"]) >= MAX_PENDING_PROPOSALS:
                raise GitHubPluginError("待批准 GitHub 操作已達上限；請先處理既有提案。")
            proposal_id = uuid.uuid4().hex
            item = {
                "proposal_id": proposal_id, "kind": kind, "repository": self._repository,
                "payload": payload, "preview": preview, "status": "pending",
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=PROPOSAL_TTL_MINUTES)).isoformat(),
            }
            self._pending_proposals[proposal_id] = item
            return {"ok": True, "proposal_id": proposal_id, "status": "pending_approval",
                    "repository": self._repository, "kind": kind, "preview": preview,
                    "message": "已建立提案；尚未修改 GitHub。請在 Kaptia Desktop 的 GitHub 待批准清單確認。"}

    def propose_branch(self, branch: str, base_branch: str) -> dict[str, Any]:
        branch, base_branch = self._validate_branch(branch), self._validate_branch(base_branch)
        if branch == base_branch:
            raise GitHubPluginError("新 Branch 必須與基準 Branch 不同。")
        return self._queue_proposal("create_branch", {"branch": branch, "base_branch": base_branch},
                                    {"branch": branch, "base_branch": base_branch})

    def propose_file_write(self, path: str, content: str, message: str, branch: str,
                           existing_sha: str = "") -> dict[str, Any]:
        path, branch = self._validate_path(path), self._validate_branch(branch)
        if self._default_branch and branch == self._default_branch:
            raise GitHubPluginError("AI 提案不得直接修改 Repository 預設分支；請先建立功能分支。")
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise GitHubPluginError("新檔案內容必須是 UTF-8 文字且不超過 1 MB。")
        if not isinstance(message, str) or not message.strip() or len(message) > 200:
            raise GitHubPluginError("Commit message 必須為 1–200 字元。")
        if existing_sha and not re.fullmatch(r"[0-9a-f]{40}", existing_sha):
            raise GitHubPluginError("既有檔案 SHA 格式無效。")
        old_content = ""
        if existing_sha:
            current = self.read_file(path, branch)
            if current["sha"] != existing_sha:
                raise GitHubPluginError("檔案已在讀取後變更；請重新讀取再提出修改。")
            old_content = current["content"]
        diff = "\n".join(difflib.unified_diff(
            old_content.splitlines(), content.splitlines(),
            fromfile="a/" + path if existing_sha else "/dev/null",
            tofile="b/" + path, lineterm="",
        ))
        preview = {"path": path, "branch": branch, "message": message.strip(),
                   "existing_sha": existing_sha or None, "diff": diff[:12000],
                   "diff_truncated": len(diff) > 12000, "new_bytes": len(content.encode("utf-8"))}
        payload = {"path": path, "content": content, "message": message.strip(),
                   "branch": branch, "existing_sha": existing_sha or None}
        return self._queue_proposal("write_file", payload, preview)

    def propose_pull_request(self, title: str, body: str, head: str, base: str) -> dict[str, Any]:
        head, base = self._validate_branch(head), self._validate_branch(base)
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise GitHubPluginError("Pull Request 標題必須為 1–200 字元。")
        if not isinstance(body, str) or len(body) > 10000:
            raise GitHubPluginError("Pull Request 描述不得超過 10,000 字元。")
        return self._queue_proposal("create_pull_request",
            {"title": title.strip(), "body": body, "head": head, "base": base},
            {"title": title.strip(), "head": head, "base": base, "body_preview": body[:1500]})

    def list_pending_proposals(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        with self._proposal_lock:
            result = []
            for item in self._pending_proposals.values():
                if item["status"] != "pending":
                    continue
                if datetime.fromisoformat(item["expires_at"]) <= now:
                    item["status"] = "expired"
                    continue
                result.append({k: item[k] for k in (
                    "proposal_id", "kind", "repository", "preview", "created_at", "expires_at", "status"
                )})
            return result

    def approve_proposal(self, proposal_id: str, *, locally_confirmed: bool = False) -> dict[str, Any]:
        self._require_approval(locally_confirmed)
        with self._proposal_lock:
            item = self._pending_proposals.get(str(proposal_id))
            if not item or item["status"] != "pending":
                raise GitHubPluginError("提案不存在、已處理或已過期。")
            if datetime.fromisoformat(item["expires_at"]) <= datetime.now(timezone.utc):
                item["status"] = "expired"
                raise GitHubPluginError("提案已過期，請重新提出。")
            if item["repository"] != self._repository:
                raise GitHubPluginError("目前選取的 Repository 已變更；請重新選擇原 Repository 後再批准。")
            payload = item["payload"]
            if item["kind"] == "create_branch":
                result = self.create_branch(payload["branch"], payload["base_branch"], user_approved=True)
            elif item["kind"] == "write_file":
                metadata = self._request("GET", f"/repos/{item['repository']}")
                current_default = metadata.get("default_branch", "")
                if current_default and payload["branch"] == current_default:
                    raise GitHubPluginError("Repository 預設分支已變更；拒絕直接寫入預設分支。")
                if payload["existing_sha"]:
                    current = self.read_file(payload["path"], payload["branch"])
                    if current["sha"] != payload["existing_sha"]:
                        raise GitHubPluginError("檔案在提案後又被修改；拒絕覆蓋，請重新讀取並產生提案。")
                result = self.write_file(payload["path"], payload["content"], payload["message"],
                    payload["branch"], existing_sha=payload["existing_sha"], user_approved=True)
            elif item["kind"] == "create_pull_request":
                result = self.create_pull_request(payload["title"], payload["body"], payload["head"],
                    payload["base"], user_approved=True)
            else:
                raise GitHubPluginError("未知的提案類型。")
            item["status"] = "approved"
            item["result"] = result
            return {"ok": True, "proposal_id": item["proposal_id"], "status": "completed",
                    "kind": item["kind"], "result": result}

    def reject_proposal(self, proposal_id: str, *, locally_confirmed: bool = False) -> dict[str, Any]:
        self._require_approval(locally_confirmed)
        with self._proposal_lock:
            item = self._pending_proposals.get(str(proposal_id))
            if not item or item["status"] != "pending":
                raise GitHubPluginError("提案不存在、已處理或已過期。")
            item["status"] = "rejected"
            return {"ok": True, "proposal_id": item["proposal_id"], "status": "rejected"}

    def workflow_runs(self, branch: str | None = None) -> list[dict[str, Any]]:
        query = "?per_page=20"
        if branch:
            query += "&branch=" + urllib.parse.quote(self._validate_branch(branch), safe="")
        data = self._request("GET", self._repo_path("/actions/runs" + query))
        return [{"id": x.get("id"), "name": x.get("name"), "status": x.get("status"),
                 "conclusion": x.get("conclusion"), "html_url": x.get("html_url"),
                 "head_branch": x.get("head_branch"), "head_sha": x.get("head_sha")}
                for x in data.get("workflow_runs", []) if isinstance(x, dict)]

_DEFAULT_PLUGIN: GitHubPlugin | None = None

def get_default_plugin() -> GitHubPlugin:
    """Return the process-wide Desktop GitHub plugin shared by UI and AI tools."""
    global _DEFAULT_PLUGIN
    if _DEFAULT_PLUGIN is None:
        _DEFAULT_PLUGIN = GitHubPlugin()
    return _DEFAULT_PLUGIN
