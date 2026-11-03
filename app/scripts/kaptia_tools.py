"""Allowlisted local tools for Kaptia.

Tools are intentionally narrow: no arbitrary shell, no arbitrary filesystem writes,
no network access, and no destructive commands. Every result includes status metadata.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_READ_BYTES = 256_000
READ_ALLOWLIST = {
    "README.md", "docs/KAPTIA_MODEL_PLAN.md", "knowledge/PROJECT_CONTEXT.md",
    "skills/format_guides.md", "scripts/kaptia_pipeline.py",
}
CHECKS = {
    "python_compile": [sys.executable, "-m", "compileall", "-q", "scripts"],
    "training_data": [sys.executable, "scripts/validate_training_data.py"],
    "code_data": [sys.executable, "scripts/validate_code_dataset.py"],
    "knowledge_tests": [sys.executable, "-m", "unittest", "scripts/test_knowledge_index.py"],
}


def _result(name, ok, **payload):
    return {"tool": name, "ok": bool(ok), **payload}


def search_project_knowledge(query, top_k=4):
    """Search the local source-attributed knowledge index."""
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        return _result("search_project_knowledge", False, error="query 必須為 1–2000 字元")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 10:
        return _result("search_project_knowledge", False, error="top_k 必須介於 1 到 10")
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from query_knowledge import search
        rows = search(query, top_k)
        return _result("search_project_knowledge", bool(rows), query=query,
                       results=[{k: row.get(k) for k in ("score", "id", "source", "section", "text")}
                                for row in rows],
                       note="詞彙匹配分數不是正確率；來源仍需依任務核對。")
    except Exception as exc:
        return _result("search_project_knowledge", False,
                       error=f"{type(exc).__name__}: {exc}")


def read_project_file(path):
    """Read only explicitly allowlisted, bounded UTF-8 project files."""
    if not isinstance(path, str) or path not in READ_ALLOWLIST:
        return _result("read_project_file", False, error="檔案不在唯讀允許清單中")
    target = (ROOT / path).resolve()
    if ROOT.resolve() not in target.parents or not target.is_file():
        return _result("read_project_file", False, error="檔案不存在或路徑不合法")
    try:
        raw = target.read_bytes()
        if len(raw) > MAX_READ_BYTES:
            return _result("read_project_file", False, error="檔案超過讀取大小限制",
                           bytes=len(raw), max_bytes=MAX_READ_BYTES)
        content = raw.decode("utf-8")
        return _result("read_project_file", True, path=path, bytes=len(raw),
                       sha256=hashlib.sha256(raw).hexdigest(), content=content)
    except (OSError, UnicodeDecodeError) as exc:
        return _result("read_project_file", False, error=f"{type(exc).__name__}: {exc}")


def run_project_check(check_name, timeout_seconds=120):
    """Run only named, predefined non-destructive checks; never accepts shell text."""
    if check_name not in CHECKS:
        return _result("run_project_check", False,
                       error="未知檢查名稱", allowed_checks=sorted(CHECKS))
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 180:
        return _result("run_project_check", False, error="timeout_seconds 必須介於 1 到 180")
    try:
        proc = subprocess.run(CHECKS[check_name], cwd=ROOT, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              timeout=timeout_seconds, check=False, shell=False)
        output = proc.stdout[-12000:]
        return _result("run_project_check", proc.returncode == 0,
                       check=check_name, exit_code=proc.returncode, output=output,
                       command=CHECKS[check_name], timed_out=False)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return _result("run_project_check", False, check=check_name,
                       error="檢查逾時", output=output[-12000:], timed_out=True)
    except OSError as exc:
        return _result("run_project_check", False, check=check_name,
                       error=f"{type(exc).__name__}: {exc}", timed_out=False)


def dispatch_tool(name, arguments):
    """Validate and dispatch one known tool; unknown tools fail closed."""
    if not isinstance(arguments, dict):
        return _result(str(name), False, error="arguments 必須是 JSON object")
    registry = {
        "search_project_knowledge": search_project_knowledge,
        "read_project_file": read_project_file,
        "run_project_check": run_project_check,
    }
    # Optional extended tools are loaded lazily so the core CLI still works without RAG deps.
    try:
        from kaptia_extended_tools import dispatch_tool as dispatch_extended_tool
    except ImportError:
        try:
            from scripts.kaptia_extended_tools import dispatch_tool as dispatch_extended_tool
        except ImportError:
            dispatch_extended_tool = None
    if dispatch_extended_tool is not None:
        registry.update({
            "calculate": lambda **kw: dispatch_extended_tool("calculate", kw),
            "web_search": lambda **kw: dispatch_extended_tool("web_search", kw),
            "ingest_user_documents": lambda **kw: dispatch_extended_tool("ingest_user_documents", kw),
            "search_user_documents": lambda **kw: dispatch_extended_tool("search_user_documents", kw),
        })
    # GitHub writes are never performed by the model. The model can only enqueue
    # proposals; the Desktop UI must approve each proposal separately.
    try:
        from plugins.github_plugin import get_default_plugin
        github = get_default_plugin()
        registry.update({
            "github_list_repositories": lambda **kw: {"ok": True, "repositories": github.list_repositories()},
            "github_select_repository": lambda **kw: {"ok": True, **github.set_repository(kw["repository"])},
            "github_list_branches": lambda **kw: {"ok": True, "branches": github.list_branches()},
            "github_read_file": lambda **kw: {"ok": True, **github.read_file(kw["path"], kw["branch"] or None)},
            "github_propose_branch": lambda **kw: github.propose_branch(kw["branch"], kw["base_branch"]),
            "github_propose_file_write": lambda **kw: github.propose_file_write(
                kw["path"], kw["content"], kw["message"], kw["branch"], kw["existing_sha"]),
            "github_propose_pull_request": lambda **kw: github.propose_pull_request(
                kw["title"], kw["body"], kw["head"], kw["base"]),
            "github_list_workflow_runs": lambda **kw: {"ok": True, "runs": github.workflow_runs(kw["branch"] or None)},
        })
    except ImportError:
        pass
    # Attach is a separate, explicit-consent capability family.
    try:
        try:
            import kaptia_attach as attach
        except ImportError:
            from scripts import kaptia_attach as attach
        registry.update({
            "attach_list_running_apps": lambda **kw: attach.list_running_apps(),
            "attach_connect": attach.attach_window,
            "attach_inspect": attach.inspect_attached_window,
            "attach_capture_ocr": attach.capture_window_ocr,
            "attach_propose_vision_click": lambda **kw: attach.propose_vision_action(action="vision_click", **kw),
            "attach_propose_vision_type_text": lambda **kw: attach.propose_vision_action(action="vision_type_text", **kw),
            "attach_list_sessions": lambda **kw: attach.list_attached_sessions(),
            "attach_list_pending": lambda **kw: attach.list_pending_actions(),
            "attach_propose_click": lambda **kw: attach.propose_ui_action(action="click", **kw),
            "attach_propose_type_text": lambda **kw: attach.propose_ui_action(action="type_text", **kw),
            "attach_click": attach.click_ui_element,
            "attach_type_text": attach.type_into_text_field,
            "attach_disconnect": attach.detach_window,
            "attach_disconnect_all": lambda **kw: attach.detach_all(),
        })
    except ImportError:
        pass
    function = registry.get(name)
    if function is None:
        return _result(str(name), False, error="工具不存在或未獲允許",
                       allowed_tools=sorted(registry))
    try:
        result = function(**arguments)
        json.dumps(result, ensure_ascii=False)
        return result
    except TypeError as exc:
        return _result(name, False, error=f"參數不符合工具規格：{exc}")
    except Exception as exc:
        return _result(name, False, error=f"工具執行失敗：{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    print(json.dumps({"tools": sorted(CHECKS), "tool_registry": [
        "search_project_knowledge", "read_project_file", "run_project_check",
        "attach_list_running_apps", "attach_connect", "attach_inspect",
        "attach_click", "attach_type_text", "attach_disconnect",
    ]}, ensure_ascii=False, indent=2))
