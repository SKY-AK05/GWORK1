"""Dependency-light HTTP server for Zerone Prospect Intelligence."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from webapp.discovery import discover_companies
from src.utils.url_utils import is_safe_public_url

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
JOB_ROOT = ROOT / "data" / "jobs"
STATIC = ROOT / "static"
JOB_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_ARTIFACTS = {
    "company_research_report.md": "text/markdown",
    "company_research.json": "application/json",
    "sources.json": "application/json",
    "run_metadata.json": "application/json",
    "prospect.json": "application/json",
    "changes.json": "application/json",
    "researcher_memo.md": "text/markdown",
    "architecture_diagram.png": "image/png",
}

JOBS: dict[str, dict] = {}
CANDIDATES: dict[str, dict] = {}
LOCK = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_job(job: dict) -> dict:
    return {k: v for k, v in job.items() if k not in {"process_log", "candidate"}}


def set_job(job_id: str, **updates: object) -> None:
    with LOCK:
        JOBS[job_id].update(updates, updated_at=now())


def run_research(job_id: str) -> None:
    with LOCK:
        job = JOBS[job_id]
        candidate = dict(job["candidate"])
    workdir = JOB_ROOT / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    set_job(job_id, status="running", stage="initializing", progress=8,
            message="Candidate confirmed. Initializing the existing research engine.")
    command = [
        sys.executable, "-m", "app", "research",
        "--company", candidate["legal_name"],
        "--country", candidate["country"],
        "--depth", job["options"].get("depth", "standard"),
        "--model", job["options"].get("model") or os.getenv("AI_MODEL", "openrouter/gemini-3-flash-preview"),
        "--output-dir", str(workdir / "reports"),
    ]
    if candidate.get("website"):
        if not is_safe_public_url(candidate["website"]):
            set_job(job_id, status="failed", stage="validation", progress=100,
                    message="The selected website failed public-URL validation.")
            return
        command += ["--website", candidate["website"]]
    if job["options"].get("recent"):
        command += ["--recent", job["options"]["recent"]]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT) + os.pathsep + env.get("PYTHONPATH", "")
    set_job(job_id, stage="researching", progress=24,
            message="Running public discovery, fetching permitted sources, and preserving evidence gaps.")
    try:
        completed = subprocess.run(command, cwd=PROJECT, env=env, text=True,
                                   capture_output=True, timeout=60 * 20)
    except subprocess.TimeoutExpired:
        set_job(job_id, status="failed", stage="timeout", progress=100,
                message="Research exceeded the bounded 20-minute job limit.")
        return
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    # Keep a bounded diagnostic log without exposing environment values.
    safe_log = re.sub(r"(?i)(api[_-]?key|token|secret)=\S+", r"\1=[redacted]", output)[-12000:]
    for key in ("AZURE_AI_API_KEY", "AZURE_OPENAI_API_KEY", "OPENROUTER_API_KEY", "TAVILY_API_KEY", "FIRECRAWL_API_KEY", "COMPANIES_HOUSE_API_KEY"):
        value = env.get(key)
        if value:
            safe_log = safe_log.replace(value, "[redacted]")
    (workdir / "job.log").write_text(safe_log, encoding="utf-8")
    reports = next((p for p in (workdir / "reports" / candidate["legal_name"].lower().replace(" ", "-")).glob("*") if p.is_dir()), None)
    if reports is None:
        dirs = [p for p in (workdir / "reports").rglob("*") if p.is_dir()] if (workdir / "reports").exists() else []
        reports = max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None
    if completed.returncode == 0 and reports:
        set_job(job_id, status="completed", stage="complete", progress=100,
                message="Research completed. Review the partial/completed status in the report metadata.",
                artifact_dir=str(reports))
    else:
        set_job(job_id, status="failed", stage="failed", progress=100,
                message="The research engine failed; no fabricated result was created.",
                error="Research subprocess exited with a non-zero status.")


class Handler(BaseHTTPRequestHandler):
    server_version = "ZeroneWeb/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self) -> dict:
        length = min(int(self.headers.get("Content-Length", "0")), 64 * 1024)
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise ValueError("Request body must be valid JSON.")
        if not isinstance(value, dict):
            raise ValueError("Request body must be an object.")
        return value

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"status": "ok", "service": "zerone-prospect-intelligence", "research_engine": "existing app CLI"})
            return
        if parsed.path == "/api/config":
            self.send_json({"ai_model_configured": bool(os.getenv("AZURE_AI_API_KEY") or os.getenv("OPENROUTER_API_KEY")),
                            "search_configured": bool(os.getenv("TAVILY_API_KEY") or os.getenv("FIRECRAWL_API_KEY")),
                            "registry_configured": bool(os.getenv("COMPANIES_HOUSE_API_KEY")),
                            "browser": "public-only by default; authenticated browser not integrated"})
            return
        match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)", parsed.path)
        if match:
            with LOCK:
                job = JOBS.get(match.group(1))
            if not job:
                self.send_json({"error": "Job not found."}, 404)
            else:
                self.send_json(public_job(job))
            return
        match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)/artifacts", parsed.path)
        if match:
            with LOCK:
                job = JOBS.get(match.group(1))
            if not job or not job.get("artifact_dir"):
                self.send_json({"error": "Artifacts are not available yet."}, 404)
                return
            root = Path(job["artifact_dir"]).resolve()
            files = [{"name": name, "url": f"/api/jobs/{match.group(1)}/artifacts/{name}"}
                     for name in ALLOWED_ARTIFACTS if (root / name).is_file()]
            self.send_json({"files": files})
            return
        match = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)/artifacts/([^/]+)", parsed.path)
        if match:
            self.serve_artifact(match.group(1), unquote(match.group(2)))
            return
        if parsed.path == "/manus-routes.json":
            self.serve_file(STATIC / "manus-routes.json", "application/json")
            return
        if parsed.path == "/style.css":
            self.serve_file(STATIC / "style.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self.serve_file(STATIC / "app.js", "text/javascript; charset=utf-8")
            return
        if parsed.path.startswith("/api/"):
            self.send_json({"error": "API route not found."}, 404)
            return
        self.serve_file(STATIC / "index.html", "text/html; charset=utf-8")

    def serve_artifact(self, job_id: str, name: str) -> None:
        if name not in ALLOWED_ARTIFACTS:
            self.send_json({"error": "Artifact is not allowlisted."}, 404)
            return
        with LOCK:
            job = JOBS.get(job_id)
        if not job or not job.get("artifact_dir"):
            self.send_json({"error": "Artifacts are not available yet."}, 404)
            return
        root = Path(job["artifact_dir"]).resolve()
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            self.send_json({"error": "Artifact not found."}, 404)
            return
        self.serve_file(path, ALLOWED_ARTIFACTS[name], download=name)

    def serve_file(self, path: Path, content_type: str, download: str | None = None) -> None:
        if not path.is_file():
            self.send_json({"error": "Not found."}, 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            payload = self.body()
            if self.path == "/api/discover":
                result = discover_companies(
                    str(payload.get("company", "")), str(payload.get("country", "")),
                    website=payload.get("website"), city=payload.get("city"),
                    industry=payload.get("industry"), status=payload.get("status"),
                    page=int(payload.get("page", 1)), page_size=int(payload.get("page_size", 8)),
                )
                with LOCK:
                    for candidate in result.get("candidates", []):
                        CANDIDATES[candidate["candidate_id"]] = candidate
                self.send_json(result, 200 if result.get("status") != "invalid" else 400)
                return
            if self.path == "/api/research":
                candidate_id = str(payload.get("candidate_id", ""))
                with LOCK:
                    candidate = CANDIDATES.get(candidate_id)
                if not candidate:
                    self.send_json({"error": "Select a candidate from discovery before starting research."}, 409)
                    return
                options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
                job_id = "job_" + uuid.uuid4().hex[:16]
                job = {"job_id": job_id, "candidate_id": candidate_id, "candidate": candidate,
                       "options": options, "status": "queued", "stage": "queued", "progress": 0,
                       "message": "Queued after explicit candidate selection.", "created_at": now(), "updated_at": now()}
                with LOCK:
                    JOBS[job_id] = job
                threading.Thread(target=run_research, args=(job_id,), daemon=True).start()
                self.send_json(public_job(job), 202)
                return
            self.send_json({"error": "Not found."}, 404)
        except (ValueError, TypeError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception:
            self.send_json({"error": "Request failed safely; no result was fabricated."}, 500)


def main() -> None:
    port = int(os.getenv("ZERONE_WEB_PORT", "8787"))
    host = os.getenv("ZERONE_WEB_HOST", "0.0.0.0")
    print(f"Zerone Prospect Intelligence listening on http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
