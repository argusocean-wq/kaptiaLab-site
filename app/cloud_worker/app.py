"""KaptiaLab remote compute worker with Security Core enforcement.

Run behind a TLS reverse proxy or with the hardened cloud_worker.server launcher.
Submitted jobs are executed only in the existing restricted Docker container.
"""
from __future__ import annotations

import hmac
import os
import sqlite3
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

try:
    from security.manager import SecurityManager
    from security.policy import client_allowed
except ImportError:
    from scripts.security.manager import SecurityManager
    from scripts.security.policy import client_allowed

DB_PATH = Path(os.environ.get("KAPTIA_CLOUD_DB", "./kaptia_cloud_jobs.sqlite3"))
TOKEN = os.environ.get("KAPTIA_CLOUD_TOKEN", "")
MAX_SOURCE = 500_000
JOB_RETENTION_SECONDS = 7 * 24 * 60 * 60
IMAGE_PYTHON = os.environ.get("KAPTIA_CLOUD_PYTHON_IMAGE", "python:3.12-slim")
IMAGE_BLENDER = os.environ.get("KAPTIA_CLOUD_BLENDER_IMAGE", "blender:4.5.0")
LOCK = threading.RLock()
ACTIVE: dict[str, threading.Thread] = {}
SECURITY = SecurityManager()
app = FastAPI(title="KaptiaLab Cloud Worker", version="0.3.0")


class JobRequest(BaseModel):
    task_id: str = Field(min_length=16, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    task_type: str
    source: str = Field(min_length=1, max_length=MAX_SOURCE)
    timeout_seconds: int = Field(default=900, ge=1, le=3600)


class LockdownRequest(BaseModel):
    enabled: bool


def _auth(authorization: str | None, actor: str = "unknown"):
    if not TOKEN or len(TOKEN) < 24:
        raise HTTPException(503, "Worker token is not configured securely")
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        SECURITY.auth_failed(actor)
        raise HTTPException(401, "Bearer token required")
    supplied = authorization[len(prefix):].strip()
    if not hmac.compare_digest(supplied, TOKEN):
        SECURITY.auth_failed(actor)
        raise HTTPException(401, "Unauthorized")


@app.middleware("http")
async def enforce_security_policy(request: Request, call_next):
    # request.client.host is the TCP peer. Do not trust caller-provided X-Forwarded-For.
    peer = request.client.host if request.client else "unknown"
    if not client_allowed(peer):
        SECURITY.event("network_policy_denied", actor=peer, outcome="denied",
                       reason="source_not_allowlisted")
        return JSONResponse({"detail": "Client network is not allowlisted"}, status_code=403)
    allowed, retry_after = SECURITY.request_allowed(peer)
    if not allowed:
        return JSONResponse(
            {"detail": "Request rate limit exceeded"},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    # Allow health/security inspection and reads during lockdown; reject new workload submissions.
    if request.url.path == "/v1/jobs" and request.method.upper() == "POST" and SECURITY.lockdown.is_enabled():
        return JSONResponse({"detail": "Worker is in emergency lockdown; new jobs are disabled"}, status_code=423)
    return await call_next(request)


@contextmanager
def _db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=15)
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, task_type TEXT NOT NULL, status TEXT NOT NULL,
            created REAL NOT NULL, updated REAL NOT NULL, timeout INTEGER NOT NULL,
            source TEXT NOT NULL, stdout TEXT NOT NULL DEFAULT '',
            stderr TEXT NOT NULL DEFAULT '', exit_code INTEGER)""")
        yield con
        con.commit()
    finally:
        con.close()


def _recover_and_prune():
    """Do not leave queued/running tasks stuck or retain old task source after restart."""
    now = time.time()
    with _db() as con:
        con.execute(
            "UPDATE jobs SET status='failed', updated=?, source='', "
            "stderr='Worker restarted before task completion', exit_code=-2 "
            "WHERE status IN ('queued','running')",
            (now,),
        )
        con.execute(
            "DELETE FROM jobs WHERE updated < ? AND status IN ('completed','failed')",
            (now - JOB_RETENTION_SECONDS,),
        )


@app.on_event("startup")
def _startup():
    _recover_and_prune()
    SECURITY.status()


def _execute(job_id: str):
    try:
        with _db() as con:
            row = con.execute(
                "SELECT task_type,source,timeout FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row:
                return
            task_type, source, timeout = row
            con.execute(
                "UPDATE jobs SET status='running',updated=? WHERE id=?",
                (time.time(), job_id),
            )

        image = IMAGE_PYTHON if task_type == "python_script" else IMAGE_BLENDER
        entry = (
            ["python", "-I", "/job/main.py"]
            if task_type == "python_script"
            else ["blender", "--background", "--python", "/job/main.py"]
        )
        with tempfile.TemporaryDirectory(prefix="kaptia-cloud-") as tmp:
            jobdir = Path(tmp) / "job"
            jobdir.mkdir()
            (jobdir / "main.py").write_text(source, encoding="utf-8")
            cmd = [
                "docker", "run", "--rm", "--network=none", "--read-only",
                "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--user=65534:65534", "--pids-limit=128", "--memory=4g",
                "--cpus=4", "--tmpfs", "/tmp:rw,noexec,nosuid,size=512m",
                "--mount", f"type=bind,src={jobdir},dst=/job,readonly",
                "--workdir", "/tmp", image, *entry,
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout,
                    check=False, shell=False,
                )
                status = "completed" if result.returncode == 0 else "failed"
                stdout = result.stdout[-100_000:]
                stderr = result.stderr[-20_000:]
                code = result.returncode
            except subprocess.TimeoutExpired as exc:
                status, stdout, stderr, code = (
                    "failed", str(exc.stdout or "")[-100_000:],
                    "Task timed out", -1,
                )
            except OSError as exc:
                status, stdout, stderr, code = (
                    "failed", "", f"Worker execution error: {exc}", -1,
                )

        with _db() as con:
            con.execute(
                "UPDATE jobs SET status=?,updated=?,source='',stdout=?,stderr=?,"
                "exit_code=? WHERE id=?",
                (status, time.time(), stdout, stderr, code, job_id),
            )
        SECURITY.event("cloud_job_completed" if status == "completed" else "cloud_job_failed",
                       target=job_id, outcome=status, reason="docker_exit", policy=task_type)
    except Exception as exc:
        # Avoid leaking submitted source into logs; clear it if the worker itself fails.
        with _db() as con:
            con.execute(
                "UPDATE jobs SET status='failed',updated=?,source='',"
                "stderr='Worker internal error',exit_code=-3 WHERE id=?",
                (time.time(), job_id),
            )
        SECURITY.event("cloud_job_failed", target=job_id, outcome="failed",
                       reason=type(exc).__name__)
    finally:
        with LOCK:
            ACTIVE.pop(job_id, None)


def _actor(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@app.get("/v1/health")
def health(request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization, _actor(request))
    with LOCK:
        active_jobs = len(ACTIVE)
    return {
        "ok": True,
        "service": "kaptialab-cloud-worker",
        "version": "0.3.0",
        "active_jobs": active_jobs,
        "max_concurrency": 2,
        "remote_jobs_locked": SECURITY.lockdown.is_enabled(),
    }


@app.get("/v1/capabilities")
def capabilities(request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization, _actor(request))
    return {
        "task_types": ["python_script", "blender_background"],
        "isolation": "docker", "network_access": False, "gpu_execution": False,
        "limits": {
            "source_chars": MAX_SOURCE, "timeout_seconds": 3600,
            "container_memory": "4g", "container_cpus": 4,
            "max_concurrency": 2, "job_retention_days": 7,
        },
        "security_core": True,
        "remote_jobs_locked": SECURITY.lockdown.is_enabled(),
    }


@app.get("/v1/security/status")
def security_status(request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization, _actor(request))
    return {"ok": True, "security": SECURITY.status()}


@app.post("/v1/security/lockdown")
def enable_lockdown(payload: LockdownRequest, request: Request,
                    authorization: str | None = Header(default=None)):
    _auth(authorization, _actor(request))
    if payload.enabled is not True:
        raise HTTPException(403, "Remote API can enable lockdown only; unlock must be performed locally on the Worker.")
    state = SECURITY.lockdown.set_enabled(True, reason="desktop_emergency_lockdown")
    SECURITY.event("emergency_lockdown_enabled", actor=_actor(request), outcome="success")
    return {"ok": True, "lockdown": state,
            "active_jobs_note": "Already running Docker jobs are not force-terminated by this lock."}


@app.post("/v1/jobs")
def submit_job(request: JobRequest, http_request: Request,
               authorization: str | None = Header(default=None)):
    actor = _actor(http_request)
    _auth(authorization, actor)
    if SECURITY.lockdown.is_enabled():
        raise HTTPException(423, "Worker is in emergency lockdown")
    if request.task_type not in {"python_script", "blender_background"}:
        raise HTTPException(400, "Unsupported task_type")
    with LOCK:
        if len(ACTIVE) >= 2:
            raise HTTPException(429, "Worker is at maximum concurrency")
        with _db() as con:
            if con.execute("SELECT 1 FROM jobs WHERE id=?", (request.task_id,)).fetchone():
                raise HTTPException(409, "task_id already exists")
            now = time.time()
            con.execute(
                "INSERT INTO jobs(id,task_type,status,created,updated,timeout,source) "
                "VALUES(?,?,?,?,?,?,?)",
                (request.task_id, request.task_type, "queued", now, now,
                 request.timeout_seconds, request.source),
            )
        thread = threading.Thread(target=_execute, args=(request.task_id,), daemon=True)
        ACTIVE[request.task_id] = thread
        thread.start()
    SECURITY.event("cloud_job_submitted", actor=actor, target=request.task_id,
                   outcome="queued", policy=request.task_type)
    return {"job_id": request.task_id, "status": "queued"}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str, request: Request, authorization: str | None = Header(default=None)):
    _auth(authorization, _actor(request))
    if not job_id or len(job_id) > 80 or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for c in job_id
    ):
        raise HTTPException(400, "Invalid job_id")
    with _db() as con:
        row = con.execute(
            "SELECT id,task_type,status,created,updated,timeout,stdout,stderr,exit_code "
            "FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return {
        "job_id": row[0], "task_type": row[1], "status": row[2],
        "created_at": row[3], "updated_at": row[4], "timeout_seconds": row[5],
        "stdout": row[6][-100_000:], "stderr": row[7][-20_000:],
        "exit_code": row[8],
    }
