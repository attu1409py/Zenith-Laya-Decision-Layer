"""HTTP Server and Real-Time Event Streaming for Team ZENITH Decision Layer.

Provides:
1. Safe read-only health checks for TopGameAI Arena and Laya model links.
2. Derived decision layer status: INACTIVE, READY, ACTIVE, HALTED.
3. Threading HTTP server serving static frontend assets and REST/SSE endpoints.
4. Live SSE event streaming (/api/session/events) for sub-second UI updates.
5. CSV export (/api/logs/export-csv), log verification, and raw download.
"""

from __future__ import annotations

import json
import mimetypes
import os
import queue
import socket
import sys
import threading
import time
import urllib.parse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from zenith.arena_client import ArenaClient, ArenaError
from zenith.csv_export import export_session_to_csv
from zenith.decision_viewer import DecisionViewer
from zenith.game2048_simulator import Deterministic2048Simulator
from zenith.hash_chain import read_jsonl_records, verify_jsonl_file
from zenith.laya_adapter import APPROVED_MODEL_ID, LayaAdapter
from zenith.main import MockSnakeArena, make_mock_decide_fn
from zenith.pdf_export import generate_session_pdf
from zenith.runner import ArenaAdapter, DecideFn, SessionResult, SessionRunner
from zenith.session_logger import SessionLogger

STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_session_log(log_dir: Union[str, Path], session_id: Optional[str]) -> Optional[Path]:
    """Safely locate a session JSONL file in log_dir or its subdirectories.

    Prevents directory traversal and checks root logs/, benchmarks/, and subfolders.
    """
    if not session_id or not isinstance(session_id, str):
        return None
    safe_name = Path(session_id.strip()).name
    if not safe_name or safe_name.startswith("."):
        return None
    base = Path(log_dir).resolve()
    # 1. Direct path
    direct = base / f"{safe_name}.jsonl"
    if direct.exists() and direct.is_file():
        return direct
    # 2. Benchmarks subfolder
    bench = base / "benchmarks" / f"{safe_name}.jsonl"
    if bench.exists() and bench.is_file():
        return bench
    # 3. Recursive glob fallback
    try:
        for p in base.rglob(f"{safe_name}.jsonl"):
            if p.is_file():
                return p
    except Exception:
        pass
    return None


@dataclass
class LinkHealth:
    """Status record for an external link."""
    status: str  # 'disconnected', 'connecting', 'connected', 'error'
    latency_ms: Optional[int] = None
    last_checked: Optional[str] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class HealthChecker:
    """Manages independent health checks for Arena and Laya links."""

    def __init__(
        self,
        base_url: str = ArenaClient.DEFAULT_BASE_URL,
        mock_model: bool = False,
        arena_check_fn: Optional[Callable[[], Tuple[bool, int, Optional[str]]]] = None,
        laya_check_fn: Optional[Callable[[], Tuple[bool, int, Optional[str]]]] = None,
        cache_ttl_sec: float = 2.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.mock_model = mock_model
        self.arena_check_fn = arena_check_fn
        self.laya_check_fn = laya_check_fn
        self.cache_ttl_sec = cache_ttl_sec

        self._lock = threading.RLock()
        self._last_arena: Optional[LinkHealth] = None
        self._last_laya: Optional[LinkHealth] = None
        self._last_arena_time: float = 0.0
        self._last_laya_time: float = 0.0

    def check_arena(self, force: bool = False) -> LinkHealth:
        """Perform a safe, read-only health check for TopGameAI Arena.

        Does NOT create an Arena session. Queries the public leaderboard endpoint.
        """
        now = time.monotonic()
        with self._lock:
            if not force and self._last_arena and (now - self._last_arena_time) < self.cache_ttl_sec:
                return self._last_arena

        ts = _utc_now_iso()
        if self.arena_check_fn:
            try:
                ok, latency, err = self.arena_check_fn()
                status = "connected" if ok else "error"
                res = LinkHealth(
                    status=status,
                    latency_ms=latency,
                    last_checked=ts,
                    error=err,
                    details={"endpoint": self.base_url},
                )
            except Exception as exc:
                res = LinkHealth(
                    status="error",
                    latency_ms=0,
                    last_checked=ts,
                    error=str(exc),
                    details={"endpoint": self.base_url},
                )
        else:
            t0 = time.monotonic()
            client = ArenaClient(base_url=self.base_url, timeout=3.0)
            try:
                # Safe read-only check: requests snake leaderboard without creating a session
                client.get_leaderboard("snake")
                latency = max(1, int((time.monotonic() - t0) * 1000))
                res = LinkHealth(
                    status="connected",
                    latency_ms=latency,
                    last_checked=ts,
                    error=None,
                    details={"endpoint": self.base_url},
                )
            except ArenaError as exc:
                latency = int((time.monotonic() - t0) * 1000)
                res = LinkHealth(
                    status="error",
                    latency_ms=latency,
                    last_checked=ts,
                    error=f"Arena API error: {exc}",
                    details={"endpoint": self.base_url},
                )
            except Exception as exc:
                latency = int((time.monotonic() - t0) * 1000)
                res = LinkHealth(
                    status="error",
                    latency_ms=latency,
                    last_checked=ts,
                    error=f"Connection failed: {exc}",
                    details={"endpoint": self.base_url},
                )

        with self._lock:
            self._last_arena = res
            self._last_arena_time = now
        return res

    def check_laya(self, force: bool = False) -> LinkHealth:
        """Check Laya model / runtime readiness without running an active session."""
        now = time.monotonic()
        with self._lock:
            if not force and self._last_laya and (now - self._last_laya_time) < self.cache_ttl_sec:
                return self._last_laya

        ts = _utc_now_iso()
        if self.laya_check_fn:
            try:
                ok, latency, err = self.laya_check_fn()
                status = "connected" if ok else "error"
                res = LinkHealth(
                    status=status,
                    latency_ms=latency,
                    last_checked=ts,
                    error=err,
                    details={"model_id": APPROVED_MODEL_ID, "is_mock": self.mock_model},
                )
            except Exception as exc:
                res = LinkHealth(
                    status="error",
                    latency_ms=0,
                    last_checked=ts,
                    error=str(exc),
                    details={"model_id": APPROVED_MODEL_ID, "is_mock": self.mock_model},
                )
        elif self.mock_model:
            # Explicit dev / mock mode
            res = LinkHealth(
                status="connected",
                latency_ms=0,
                last_checked=ts,
                error=None,
                details={"model_id": "mock-synthetic-model", "is_mock": True},
            )
        else:
            # Genuine Laya runtime check
            t0 = time.monotonic()
            try:
                import importlib
                mod = importlib.util.find_spec("laya")
                if mod is None:
                    raise RuntimeError("Laya package ('laya') is not installed in current environment. Use --mock-model for development.")
                latency = max(1, int((time.monotonic() - t0) * 1000))
                res = LinkHealth(
                    status="connected",
                    latency_ms=latency,
                    last_checked=ts,
                    error=None,
                    details={"model_id": APPROVED_MODEL_ID, "is_mock": False},
                )
            except Exception as exc:
                latency = int((time.monotonic() - t0) * 1000)
                res = LinkHealth(
                    status="error",
                    latency_ms=latency,
                    last_checked=ts,
                    error=str(exc),
                    details={"model_id": APPROVED_MODEL_ID, "is_mock": False},
                )

        with self._lock:
            self._last_laya = res
            self._last_laya_time = now
        return res

    def get_summary(self, active_session: bool = False, force: bool = False) -> Dict[str, Any]:
        """Compute the full health summary and derived decision layer status."""
        arena = self.check_arena(force=force)
        laya = self.check_laya(force=force)

        # Derived decision layer status
        if active_session:
            if arena.status != "connected" or laya.status != "connected":
                halt_reasons = []
                if arena.status != "connected":
                    halt_reasons.append(f"Arena link {arena.status}: {arena.error or 'unreachable'}")
                if laya.status != "connected":
                    halt_reasons.append(f"Laya link {laya.status}: {laya.error or 'unavailable'}")
                decision_status = "HALTED"
                halt_reason = "; ".join(halt_reasons)
            else:
                decision_status = "ACTIVE"
                halt_reason = None
        else:
            if arena.status == "connected" and laya.status == "connected":
                decision_status = "READY"
            else:
                decision_status = "INACTIVE"
            halt_reason = None

        return {
            "arena": asdict(arena),
            "laya": asdict(laya),
            "decision_layer": {
                "status": decision_status,
                "ready_to_start": decision_status == "READY",
                "halt_reason": halt_reason,
            },
            "timestamp": _utc_now_iso(),
            "agent_name": "ZENITH",
            "mock_mode": self.mock_model or bool(arena.details.get("is_mock")) or bool(laya.details.get("is_mock")),
        }


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server allowing concurrent request handling and SSE streams."""
    daemon_threads = True
    allow_reuse_address = True


class ZenithRequestHandler(SimpleHTTPRequestHandler):
    """HTTP Request Handler for Team ZENITH console."""

    server_instance: Optional[ZenithServer] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard HTTP request logging in test/silent environments."""
        if os.environ.get("ZENITH_VERBOSE_HTTP", "").lower() in ("1", "true"):
            super().log_message(format, *args)

    def end_headers(self) -> None:
        """Inject security and no-cache headers."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def _send_json(self, data: Any, status: int = 200) -> None:
        """Serialize data to JSON and send response."""
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int = 400) -> None:
        """Send standard JSON error envelope."""
        self._send_json({"error": message, "status": status}, status=status)

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight if invoked."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        """Route GET requests to API handlers or static files."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        server: Optional[ZenithServer] = getattr(self.server, "zenith_server", None)

        if path == "/api/health":
            if not server:
                self._send_error_json("Server state unavailable", 500)
                return
            summary = server.health_checker.get_summary(
                active_session=server.is_session_active(),
                force="force" in parsed.query,
            )
            self._send_json(summary)
            return

        if path == "/api/session/current":
            if not server:
                self._send_error_json("Server state unavailable", 500)
                return
            self._send_json(server.get_current_session())
            return

        if path == "/api/session/events":
            if not server:
                self._send_error_json("Server state unavailable", 500)
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            q: queue.Queue = queue.Queue(maxsize=200)
            server.register_sse_client(q)

            # Send initial sync event
            init_data = server.get_current_session()
            sync_payload = json.dumps(init_data)
            try:
                self.wfile.write(f"event: session_sync\ndata: {sync_payload}\n\n".encode("utf-8"))
                self.wfile.flush()
            except Exception:
                server.unregister_sse_client(q)
                return

            try:
                while True:
                    try:
                        event_type, payload = q.get(timeout=10.0)
                        msg = f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
                        self.wfile.write(msg.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                server.unregister_sse_client(q)
            return

        if path == "/api/logs/export-csv":
            query = urllib.parse.parse_qs(parsed.query)
            session_id = query.get("session_id", [None])[0]
            if not session_id and server and server._active_session_data:
                session_id = server._active_session_data.get("session_id")
            log_dir = Path(server.log_dir if server else "logs")
            if not session_id:
                # Graceful fallback: check most recent session in log directory
                all_logs = sorted(log_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
                if all_logs:
                    session_id = all_logs[0].stem
            if not session_id:
                self._send_error_json("Missing session_id parameter", 400)
                return
            log_path = _find_session_log(log_dir, session_id)
            if not log_path or not log_path.exists():
                self._send_error_json(f"Session log not found: {session_id}", 404)
                return
            try:
                csv_text = export_session_to_csv(log_path)
            except Exception as exc:
                self._send_error_json(f"CSV export failed: {exc}", 500)
                return

            clean_id = session_id.replace(".jsonl", "").replace(".csv", "")
            view_mode = query.get("view", ["download"])[0].lower()

            if view_mode in ("inline", "raw"):
                raw_bytes = csv_text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'inline; filename="{clean_id}.csv"')
                self.send_header("Content-Length", str(len(raw_bytes)))
                self.end_headers()
                self.wfile.write(raw_bytes)
                return

            # Add UTF-8 BOM for immediate, seamless opening in Microsoft Excel and Apple Numbers
            csv_bytes = b"\xef\xbb\xbf" + csv_text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{clean_id}.csv"')
            self.send_header("Content-Length", str(len(csv_bytes)))
            self.end_headers()
            self.wfile.write(csv_bytes)
            return

        if path == "/api/logs/download":
            query = urllib.parse.parse_qs(parsed.query)
            session_id = query.get("session_id", [None])[0]
            if not session_id and server and server._active_session_data:
                session_id = server._active_session_data.get("session_id")
            if not session_id:
                self._send_error_json("Missing session_id parameter", 400)
                return
            log_dir = Path(server.log_dir if server else "logs")
            log_path = _find_session_log(log_dir, session_id)
            if not log_path or not log_path.exists():
                self._send_error_json(f"Session log not found: {session_id}", 404)
                return
            with open(log_path, "rb") as f:
                log_bytes = f.read()
            view_mode = query.get("view", ["download"])[0].lower()
            disposition = "inline" if view_mode in ("inline", "raw") else "attachment"
            self.send_response(200)
            self.send_header("Content-Type", "application/x-jsonlines; charset=utf-8")
            self.send_header("Content-Disposition", f'{disposition}; filename="{session_id}.jsonl"')
            self.send_header("Content-Length", str(len(log_bytes)))
            self.end_headers()
            self.wfile.write(log_bytes)
            return

        if path == "/api/logs/verify":
            query = urllib.parse.parse_qs(parsed.query)
            session_id = query.get("session_id", [None])[0]
            if not session_id and server and server._active_session_data:
                session_id = server._active_session_data.get("session_id")
            if not session_id:
                self._send_error_json("Missing session_id parameter", 400)
                return
            log_dir = Path(server.log_dir if server else "logs")
            log_path = _find_session_log(log_dir, session_id)
            if not log_path or not log_path.exists():
                self._send_error_json(f"Session log not found: {session_id}", 404)
                return
            res = verify_jsonl_file(log_path)
            self._send_json({
                "session_id": session_id,
                "is_valid": res.is_valid,
                "error_message": res.error_message,
                "record_count": res.record_count,
                "failing_step": res.error_line_index,
            })
            return

        if path == "/api/logs/export-pdf":
            query = urllib.parse.parse_qs(parsed.query)
            session_id = query.get("session_id", [None])[0]
            if not session_id and server and server._active_session_data:
                session_id = server._active_session_data.get("session_id")
            if not session_id:
                self._send_error_json("Missing session_id parameter", 400)
                return
            log_dir = Path(server.log_dir if server else "logs")
            log_path = _find_session_log(log_dir, session_id)
            if not log_path or not log_path.exists():
                self._send_error_json(f"Session log not found: {session_id}", 404)
                return
            try:
                pdf_bytes = generate_session_pdf(log_path)
            except Exception as exc:
                self._send_error_json(f"PDF export failed: {exc}", 500)
                return
            view_mode = query.get("view", ["download"])[0].lower()
            disposition = "inline" if view_mode in ("inline", "preview") else "attachment"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'{disposition}; filename="{session_id}.pdf"')
            self.send_header("Content-Length", str(len(pdf_bytes)))
            self.end_headers()
            self.wfile.write(pdf_bytes)
            return

        if path == "/api/sessions":
            log_dir = Path(server.log_dir if server else "logs")
            sessions = []
            seen_ids = set()
            if log_dir.exists():
                for p in sorted(log_dir.rglob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True):
                    s_id = p.stem
                    if s_id in seen_ids or s_id.startswith("run_history"):
                        continue
                    seen_ids.add(s_id)
                    mtime_iso = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    game = "snake" if "snake" in s_id.lower() else ("2048" if "2048" in s_id.lower() else "unknown")
                    mode = "live" if s_id.lower().startswith("live") else "mock"
                    final_path = p.with_name(f"{s_id}_final.json")
                    sessions.append({
                        "session_id": s_id,
                        "game": game,
                        "mode": mode,
                        "file_size": p.stat().st_size,
                        "modified_at": mtime_iso,
                        "has_final": final_path.exists(),
                    })
            self._send_json({"sessions": sessions[:100]})
            return

        if path == "/api/logs/session":
            query = urllib.parse.parse_qs(parsed.query)
            session_id = query.get("session_id", [None])[0]
            if not session_id and server and server._active_session_data:
                session_id = server._active_session_data.get("session_id")
            if not session_id:
                self._send_error_json("Missing session_id parameter", 400)
                return
            log_dir = Path(server.log_dir if server else "logs")
            log_path = _find_session_log(log_dir, session_id)
            if not log_path or not log_path.exists():
                self._send_error_json(f"Session log not found: {session_id}", 404)
                return
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            records = read_jsonl_records(lines)
            self._send_json({
                "session_id": session_id,
                "count": len(records),
                "records": records,
            })
            return

        # Map root URL to index.html
        if path == "/" or path == "/index.html":
            self.path = "/index.html"
            return super().do_GET()

        # Regular static files
        return super().do_GET()

    def do_POST(self) -> None:
        """Route POST requests to API control endpoints."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        server: Optional[ZenithServer] = getattr(self.server, "zenith_server", None)
        if not server:
            self._send_error_json("Server state unavailable", 500)
            return

        # Read JSON body if present
        content_length = int(self.headers.get("Content-Length", 0))
        body: Dict[str, Any] = {}
        if content_length > 0:
            try:
                raw_body = self.rfile.read(content_length).decode("utf-8")
                body = json.loads(raw_body)
            except Exception as exc:
                self._send_error_json(f"Invalid JSON payload: {exc}", 400)
                return

        if path == "/api/health/check":
            summary = server.health_checker.get_summary(
                active_session=server.is_session_active(),
                force=True,
            )
            self._send_json(summary)
            return

        if path == "/api/session/start":
            res, code = server.start_session(body)
            self._send_json(res, status=code)
            return

        if path == "/api/session/stop":
            res, code = server.stop_session()
            self._send_json(res, status=code)
            return

        self._send_error_json(f"Not Found: {path}", 404)


class ZenithServer:
    """Manages the backend HTTP server, health checks, session lifecycle, and SSE broadcasting."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        base_url: str = ArenaClient.DEFAULT_BASE_URL,
        mock_model: bool = False,
        log_dir: str = "logs",
        arena_check_fn: Optional[Callable[[], Tuple[bool, int, Optional[str]]]] = None,
        laya_check_fn: Optional[Callable[[], Tuple[bool, int, Optional[str]]]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.base_url = base_url
        self.mock_model = mock_model
        self.log_dir = log_dir

        self.health_checker = HealthChecker(
            base_url=base_url,
            mock_model=mock_model,
            arena_check_fn=arena_check_fn,
            laya_check_fn=laya_check_fn,
        )

        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._session_thread: Optional[threading.Thread] = None

        self._active_session_data: Optional[Dict[str, Any]] = None
        self._active_runner: Optional[SessionRunner] = None
        self._latest_step_data: Optional[Dict[str, Any]] = None
        self._session_result: Optional[Dict[str, Any]] = None

        self._session_lock = threading.RLock()
        self._sse_clients: List[queue.Queue] = []
        self._sse_lock = threading.Lock()

    @property
    def server_port(self) -> int:
        """Return the actual bound port (useful when port 0 is used in tests)."""
        if self._httpd:
            return self._httpd.server_port
        return self.port

    def get_url(self) -> str:
        """Return full base HTTP URL of the server."""
        return f"http://{self.host}:{self.server_port}"

    def register_sse_client(self, q: queue.Queue) -> None:
        """Register a new client queue for SSE broadcasting."""
        with self._sse_lock:
            self._sse_clients.append(q)

    def unregister_sse_client(self, q: queue.Queue) -> None:
        """Unregister a client queue on disconnect."""
        with self._sse_lock:
            if q in self._sse_clients:
                self._sse_clients.remove(q)

    def _broadcast_event(self, event_type: str, data: Any) -> None:
        """Push an event to all connected SSE clients."""
        with self._sse_lock:
            dead_clients = []
            for q in self._sse_clients:
                try:
                    q.put_nowait((event_type, data))
                except queue.Full:
                    dead_clients.append(q)
            for d in dead_clients:
                if d in self._sse_clients:
                    self._sse_clients.remove(d)

    def is_session_active(self) -> bool:
        """Check whether a session is currently running."""
        with self._session_lock:
            return (
                self._active_session_data is not None
                and self._active_session_data.get("status") == "ACTIVE"
            )

    def get_current_session(self) -> Dict[str, Any]:
        """Return current or last active session snapshot and latest move."""
        with self._session_lock:
            return {
                "active": self.is_session_active(),
                "session": self._active_session_data,
                "latest_move": self._latest_step_data,
                "summary": self._session_result,
            }

    def _on_runner_step(self, step_data: Dict[str, Any]) -> None:
        """Callback invoked by SessionRunner on every move."""
        with self._session_lock:
            self._latest_step_data = step_data
        self._broadcast_event("move", step_data)
        if self._active_session_data and self._active_session_data.get("mode") != "live":
            # Give operator visual pacing in simulated web sessions so moves are clearly visible
            pace = float(self._active_session_data.get("step_delay", 0.35))
            if pace > 0:
                time.sleep(pace)

    def _on_runner_complete(self, res: SessionResult) -> None:
        """Callback invoked by SessionRunner upon completion."""
        completion_reason = res.completion_reason or "Session completed."
        outcome = res.outcome or ("GOAL REACHED" if res.won else "GAME OVER")
        goal_reached = res.goal_reached if res.goal_reached is not None else bool(res.won)
        goal_progress = res.goal_progress or ""

        with self._session_lock:
            if self._active_session_data:
                self._active_session_data["status"] = "FINISHED" if not res.error else "FAILED"
                self._active_session_data["ended_at"] = _utc_now_iso()
                self._active_session_data["completion_reason"] = completion_reason
                self._active_session_data["outcome"] = outcome
                self._active_session_data["goal_reached"] = goal_reached
                self._active_session_data["goal_progress"] = goal_progress
                self._active_session_data["final_score"] = res.final_score
                self._active_session_data["won"] = res.won
                self._active_session_data["hash_chain_valid"] = res.hash_chain_valid
                self._active_session_data["total_moves"] = res.total_moves
                self._active_session_data["applied_moves"] = res.applied_moves
                self._active_session_data["rejected_moves"] = res.rejected_moves
                self._active_session_data["fallback_moves"] = res.fallback_moves
                self._active_session_data["log_path"] = res.log_path
                self._active_session_data["error"] = res.error
            self._session_result = {
                "final_score": res.final_score,
                "won": res.won,
                "outcome": outcome,
                "goal_reached": goal_reached,
                "goal_progress": goal_progress,
                "completion_reason": completion_reason,
                "hash_chain_valid": res.hash_chain_valid,
                "total_time_ms": res.total_time_ms,
                "log_path": res.log_path,
                "error": res.error,
            }
        if res.log_path:
            try:
                from zenith.csv_export import export_session_to_csv_file
                export_session_to_csv_file(res.log_path)
            except Exception:
                pass
        self._broadcast_event("session_finished", self._active_session_data or {})

    def _run_session_worker(
        self,
        session_id: str,
        game: str,
        mode: str,
        mock_model: bool,
        prompt_version: str,
        max_moves: Optional[int],
    ) -> None:
        """Background thread executing the session runner loop."""
        try:
            # Step 1: Configure arena adapter
            arena: ArenaAdapter
            if mode == "live":
                client = ArenaClient(
                    base_url=self.base_url,
                    timeout=10.0,
                    default_agent_name="ZENITH",
                )
                session_resp = client.create_session(game=game, agent_name="ZENITH")
                arena = client
            else:
                if game == "snake":
                    mock_arena = MockSnakeArena(session_id=session_id, max_moves=max_moves or 10)
                else:
                    mock_arena = Deterministic2048Simulator(max_moves=max_moves or 100, session_id_prefix=session_id)
                session_resp = mock_arena.create_session(game=game, agent_name="ZENITH")
                arena = mock_arena

            # Step 2: Configure decide function
            if mock_model:
                decide_fn = make_mock_decide_fn()
            else:
                adapter_kwargs = {"model_id": APPROVED_MODEL_ID}
                if prompt_version != "v1":
                    adapter_kwargs["prompt_version"] = prompt_version
                adapter = LayaAdapter(**adapter_kwargs)
                decide_fn = adapter.decide

            # Step 3: Configure logger and viewer
            logger = SessionLogger(session_id=session_id, game=game, log_dir=self.log_dir)
            viewer = DecisionViewer(
                game=game,
                session_id=session_id,
                mock_mode=(mode != "live" or mock_model),
                log_path=str(logger.log_path),
            )

            # Step 4: Configure runner
            runner = SessionRunner(
                arena=arena,
                decide_fn=decide_fn,
                logger=logger,
                viewer=viewer,
                max_moves=max_moves,
                on_step=self._on_runner_step,
                on_complete=self._on_runner_complete,
            )

            with self._session_lock:
                self._active_runner = runner

            # Step 5: Execute runner loop
            runner.run(initial_session_data=session_resp)

        except Exception as exc:
            with self._session_lock:
                if self._active_session_data:
                    self._active_session_data["status"] = "ERROR"
                    self._active_session_data["error"] = str(exc)
            self._broadcast_event("session_error", {"session_id": session_id, "error": str(exc)})
        finally:
            with self._session_lock:
                self._active_runner = None

    def start_session(self, config: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        """Initiate a session in a background thread if the decision layer is READY."""
        with self._session_lock:
            if self.is_session_active():
                return {"error": "A session is already active."}, 409

            summary = self.health_checker.get_summary(active_session=False)
            if summary["decision_layer"]["status"] != "READY":
                return {
                    "error": f"Cannot start session: Decision layer status is {summary['decision_layer']['status']}. Both Arena and Laya links must be connected.",
                    "health": summary,
                }, 400

            game = str(config.get("game", "snake")).strip().lower()
            if game not in ("snake", "2048"):
                return {"error": f"Unsupported game '{game}'. Valid choices: snake, 2048."}, 400

            mode = str(config.get("mode", "dry-run")).strip().lower()
            mock_model = bool(config.get("mock_model", self.mock_model))
            prompt_version = str(config.get("prompt_version", "v1"))
            max_moves_raw = config.get("max_moves")
            max_moves: Optional[int] = None
            if max_moves_raw is not None:
                try:
                    max_moves = int(max_moves_raw)
                except (ValueError, TypeError):
                    max_moves = None

            session_id = f"{'live' if mode == 'live' else 'mock'}-{game}-{int(time.time() * 1000)}"

            self._active_session_data = {
                "session_id": session_id,
                "game": game,
                "mode": mode,
                "status": "ACTIVE",
                "started_at": _utc_now_iso(),
                "agent_name": "ZENITH",
                "mock_mode": (mode != "live") or mock_model,
                "prompt_version": prompt_version,
            }
            self._latest_step_data = None
            self._session_result = None

            # Spawn runner thread
            self._session_thread = threading.Thread(
                target=self._run_session_worker,
                args=(session_id, game, mode, mock_model, prompt_version, max_moves),
                daemon=True,
            )
            self._session_thread.start()

            self._broadcast_event("session_started", self._active_session_data)

            return {
                "message": "Session initialized.",
                "session": self._active_session_data,
            }, 200

    def stop_session(self) -> Tuple[Dict[str, Any], int]:
        """Cleanly halt the active session."""
        with self._session_lock:
            if not self.is_session_active():
                return {"message": "No active session to stop."}, 200

            if self._active_runner:
                self._active_runner.stop()

            if self._active_session_data:
                self._active_session_data["status"] = "STOPPING"

            return {
                "message": "Session stop signal sent.",
                "session": self._active_session_data,
            }, 200

    def start(self, background: bool = False) -> None:
        """Start the HTTP server."""
        handler_class = ZenithRequestHandler
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler_class)
        self._httpd.zenith_server = self  # type: ignore[attr-defined]

        if background:
            self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
            self._thread.start()
        else:
            try:
                self._httpd.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                self.stop()

    def stop(self) -> None:
        """Stop the HTTP server and release port."""
        with self._session_lock:
            if self._active_runner:
                self._active_runner.stop()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._session_thread and self._session_thread.is_alive():
            self._session_thread.join(timeout=2.0)
            self._session_thread = None
