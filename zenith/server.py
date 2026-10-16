"""HTTP Server and Health Monitoring for Team ZENITH Decision Layer.

Provides:
1. Safe read-only health checks for TopGameAI Arena and Laya model links.
2. Derived decision layer status: INACTIVE, READY, ACTIVE, HALTED.
3. Threading HTTP server serving static frontend assets and REST/SSE endpoints.
"""

from __future__ import annotations

import json
import mimetypes
import os
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
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from zenith.arena_client import ArenaClient, ArenaError
from zenith.laya_adapter import APPROVED_MODEL_ID

STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    # Handled by custom router
    server_instance: Optional[ZenithServer] = None

    def __init__(self, *args, **kwargs):
        # We serve static files from STATIC_DIR
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

        if path == "/api/health":
            server = getattr(self.server, "zenith_server", None)
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
            server = getattr(self.server, "zenith_server", None)
            if not server:
                self._send_error_json("Server state unavailable", 500)
                return
            self._send_json(server.get_current_session())
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
        server = getattr(self.server, "zenith_server", None)
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
    """Manages the backend HTTP server, health checks, and session lifecycle."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        base_url: str = ArenaClient.DEFAULT_BASE_URL,
        mock_model: bool = False,
        arena_check_fn: Optional[Callable[[], Tuple[bool, int, Optional[str]]]] = None,
        laya_check_fn: Optional[Callable[[], Tuple[bool, int, Optional[str]]]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.base_url = base_url
        self.mock_model = mock_model

        self.health_checker = HealthChecker(
            base_url=base_url,
            mock_model=mock_model,
            arena_check_fn=arena_check_fn,
            laya_check_fn=laya_check_fn,
        )

        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._active_session_data: Optional[Dict[str, Any]] = None
        self._session_lock = threading.RLock()

    @property
    def server_port(self) -> int:
        """Return the actual bound port (useful when port 0 is used in tests)."""
        if self._httpd:
            return self._httpd.server_port
        return self.port

    def get_url(self) -> str:
        """Return full base HTTP URL of the server."""
        return f"http://{self.host}:{self.server_port}"

    def is_session_active(self) -> bool:
        """Check whether a session is currently running."""
        with self._session_lock:
            return self._active_session_data is not None and self._active_session_data.get("status") == "ACTIVE"

    def get_current_session(self) -> Dict[str, Any]:
        """Return current or last active session snapshot."""
        with self._session_lock:
            return {
                "session": self._active_session_data,
                "active": self.is_session_active(),
            }

    def start_session(self, config: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        """Initiate a session if the decision layer is READY."""
        with self._session_lock:
            if self.is_session_active():
                return {"error": "A session is already active."}, 409

            summary = self.health_checker.get_summary(active_session=False)
            if summary["decision_layer"]["status"] != "READY":
                return {
                    "error": f"Cannot start session: Decision layer status is {summary['decision_layer']['status']}. Both Arena and Laya links must be connected.",
                    "health": summary,
                }, 400

            game = config.get("game", "snake")
            mode = config.get("mode", "dry-run")
            session_id = f"{'live' if mode == 'live' else 'mock'}-{game}-{int(time.time() * 1000)}"

            self._active_session_data = {
                "session_id": session_id,
                "game": game,
                "mode": mode,
                "status": "ACTIVE",
                "started_at": _utc_now_iso(),
                "agent_name": "ZENITH",
                "mock_mode": (mode != "live") or self.mock_model,
            }

            return {
                "message": "Session initialized.",
                "session": self._active_session_data,
            }, 200

    def stop_session(self) -> Tuple[Dict[str, Any], int]:
        """Cleanly halt the active session."""
        with self._session_lock:
            if not self._active_session_data or self._active_session_data.get("status") != "ACTIVE":
                return {"message": "No active session to stop."}, 200

            self._active_session_data["status"] = "FINISHED"
            self._active_session_data["ended_at"] = _utc_now_iso()
            return {
                "message": "Session stopped.",
                "session": self._active_session_data,
            }, 200

    def start(self, background: bool = False) -> None:
        """Start the HTTP server."""
        handler_class = ZenithRequestHandler
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler_class)
        # Bind back-reference so handler can reach server methods
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
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None
