"""User-authorized GitHub integration for Kaptia Desktop.

Credentials are stored only through an OS keyring backend. Read operations are
available after connection; every repository write requires an explicit
per-call user_approved=True decision from the Desktop UI.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

API = "https://api.github.com"
SERVICE_NAME = "KaptiaLab.GitHub"
MAX_FILE_BYTES = 1_000_000
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

    @staticmethod
    def _validate_repo(repository: str) -> str:
        if not isinstance(repository, str) or not _REPO_RE.fullmatch(repository):
            raise GitHubPluginError("Repository 必須使用 owner/repository 格式。")
        return repository

    @staticmethod
    def _validate_branch(branch: str) -> str:
        if not isinstance(branch, str) or not _BRANCH_RE.fullmatch(branch) or ".." in branch or "//" in branch:
            raise GitHubPluginError("Branch 名稱格式無效。")
        return branch

    @staticmethod
    def _validate_path(path: str) -> str:
        if not isinstance(path, str) or not _PATH_RE.fullmatch(path) or len(path) > 500:
            raise GitHubPluginError("Repository 檔案路徑無效。")
        return path

    def _get_keyring(self):
        if self._keyring is not None:
            return self._keyring
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
        return {"ok": True, "connected": True, "storage": "OS Credential Manager"}

    def disconnect(self) -> dict[str, Any]:
        try:
            self._get_keyring().delete_password(SERVICE_NAME, "github-token")
        except Exception:
            pass
        self._repository = ""
        return {"ok": True, "connected": False}

    def set_repository(self, repository: str) -> dict[str, str]:
        self._repository = self._validate_repo(repository)
        return {"repository": self._repository}

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
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise GitHubPluginError("Pull Request 標題必須為 1–200 字元。")
        if not isinstance(body, str) or len(body) > 10000:
            raise GitHubPluginError("Pull Request 描述不得超過 10,000 字元。")
        return self._request("POST", self._repo_path("/pulls"),
                             payload={"title": title.strip(), "body": body, "head": head, "base": base, "draft": True})

    def workflow_runs(self, branch: str | None = None) -> list[dict[str, Any]]:
        query = "?per_page=20"
        if branch:
            query += "&branch=" + urllib.parse.quote(self._validate_branch(branch), safe="")
        data = self._request("GET", self._repo_path("/actions/runs" + query))
        return [{"id": x.get("id"), "name": x.get("name"), "status": x.get("status"),
                 "conclusion": x.get("conclusion"), "html_url": x.get("html_url"),
                 "head_branch": x.get("head_branch"), "head_sha": x.get("head_sha")}
                for x in data.get("workflow_runs", []) if isinstance(x, dict)]
