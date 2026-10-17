"""Unit tests for the Zenith backend HTTP server and health monitor."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import unittest
from typing import Any, Dict, Optional, Tuple

from zenith.server import HealthChecker, LinkHealth, ZenithServer


class TestHealthChecker(unittest.TestCase):
    """Test health checking logic and derived decision layer states."""

    def test_derived_status_inactive_when_links_not_connected(self) -> None:
        checker = HealthChecker(
            arena_check_fn=lambda: (False, 15, "DNS resolution failure"),
            laya_check_fn=lambda: (True, 5, None),
        )
        summary = checker.get_summary(active_session=False)
        self.assertEqual(summary["arena"]["status"], "error")
        self.assertEqual(summary["laya"]["status"], "connected")
        self.assertEqual(summary["decision_layer"]["status"], "INACTIVE")
        self.assertFalse(summary["decision_layer"]["ready_to_start"])

    def test_derived_status_ready_when_both_links_connected(self) -> None:
        checker = HealthChecker(
            arena_check_fn=lambda: (True, 24, None),
            laya_check_fn=lambda: (True, 8, None),
        )
        summary = checker.get_summary(active_session=False)
        self.assertEqual(summary["arena"]["status"], "connected")
        self.assertEqual(summary["laya"]["status"], "connected")
        self.assertEqual(summary["decision_layer"]["status"], "READY")
        self.assertTrue(summary["decision_layer"]["ready_to_start"])

    def test_derived_status_active_when_session_running_and_links_ok(self) -> None:
        checker = HealthChecker(
            arena_check_fn=lambda: (True, 20, None),
            laya_check_fn=lambda: (True, 10, None),
        )
        summary = checker.get_summary(active_session=True)
        self.assertEqual(summary["decision_layer"]["status"], "ACTIVE")

    def test_derived_status_halted_when_link_fails_during_active_session(self) -> None:
        checker = HealthChecker(
            arena_check_fn=lambda: (False, 50, "Connection reset by peer"),
            laya_check_fn=lambda: (True, 10, None),
        )
        summary = checker.get_summary(active_session=True)
        self.assertEqual(summary["decision_layer"]["status"], "HALTED")
        self.assertIn("Arena link error", summary["decision_layer"]["halt_reason"])

    def test_mock_model_marks_laya_as_mock_and_connected(self) -> None:
        checker = HealthChecker(
            arena_check_fn=lambda: (True, 12, None),
            mock_model=True,
        )
        summary = checker.get_summary(active_session=False)
        self.assertEqual(summary["laya"]["status"], "connected")
        self.assertTrue(summary["laya"]["details"]["is_mock"])
        self.assertTrue(summary["mock_mode"])


class TestZenithServer(unittest.TestCase):
    """Test HTTP endpoints and static file serving on an ephemeral port."""

    server: ZenithServer

    @classmethod
    def setUpClass(cls) -> None:
        # Start server with mock health checks on port 0 (ephemeral port)
        cls.server = ZenithServer(
            host="127.0.0.1",
            port=0,
            arena_check_fn=lambda: (True, 18, None),
            laya_check_fn=lambda: (True, 5, None),
            mock_model=True,
        )
        cls.server.start(background=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()

    def _get(self, path: str) -> Tuple[int, Dict[str, Any], bytes]:
        url = f"{self.server.get_url()}{path}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = resp.read()
            parsed = {}
            if "application/json" in resp.headers.get("Content-Type", ""):
                parsed = json.loads(data.decode("utf-8"))
            return resp.status, parsed, data

    def _post(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
        url = f"{self.server.get_url()}{path}"
        body = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return resp.status, data
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read().decode("utf-8"))
            return exc.code, data

    def test_health_endpoint_returns_ready_summary(self) -> None:
        code, body, _ = self._get("/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(body["agent_name"], "ZENITH")
        self.assertEqual(body["decision_layer"]["status"], "READY")
        self.assertTrue(body["decision_layer"]["ready_to_start"])
        self.assertEqual(body["arena"]["status"], "connected")
        self.assertEqual(body["laya"]["status"], "connected")

    def test_post_health_check_forces_refresh(self) -> None:
        code, body = self._post("/api/health/check")
        self.assertEqual(code, 200)
        self.assertEqual(body["decision_layer"]["status"], "READY")

    def test_session_lifecycle_start_and_stop(self) -> None:
        # 1. Start session
        code, start_resp = self._post("/api/session/start", {"game": "snake", "mode": "dry-run"})
        self.assertEqual(code, 200)
        self.assertIn("session", start_resp)
        self.assertEqual(start_resp["session"]["status"], "ACTIVE")

        # 2. Check current session
        code, curr_resp, _ = self._get("/api/session/current")
        self.assertEqual(code, 200)
        self.assertTrue(curr_resp["active"])
        self.assertEqual(curr_resp["session"]["status"], "ACTIVE")

        # 3. Duplicate start is rejected
        dup_code, dup_resp = self._post("/api/session/start", {"game": "snake"})
        self.assertEqual(dup_code, 409)

        # 4. Stop session
        stop_code, stop_resp = self._post("/api/session/stop")
        self.assertEqual(stop_code, 200)
        self.assertIn(stop_resp["session"]["status"], ("STOPPING", "FINISHED"))

        # 5. Confirm session is now or soon inactive
        import time
        for _ in range(20):
            code, final_curr, _ = self._get("/api/session/current")
            if not final_curr["active"]:
                break
            time.sleep(0.05)
        self.assertFalse(final_curr["active"])

    def test_start_session_fails_if_decision_layer_inactive(self) -> None:
        # Create temporary server where Arena link fails
        inactive_server = ZenithServer(
            host="127.0.0.1",
            port=0,
            arena_check_fn=lambda: (False, 0, "Network down"),
            laya_check_fn=lambda: (True, 5, None),
        )
        inactive_server.start(background=True)
        try:
            url = f"{inactive_server.get_url()}/api/session/start"
            req = urllib.request.Request(
                url,
                data=json.dumps({"game": "snake"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=3.0)
            self.assertEqual(ctx.exception.code, 400)
            err_data = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertIn("Cannot start session", err_data["error"])
        finally:
            inactive_server.stop()

    def test_static_index_html_served(self) -> None:
        code, _, data = self._get("/")
        self.assertEqual(code, 200)
        self.assertIn(b"ZENITH", data)
        self.assertIn(b"DECISION LAYER", data)
        self.assertIn(b"ARENA LINK", data)
        self.assertIn(b"LAYA RUNTIME", data)

    def test_static_app_css_served(self) -> None:
        code, _, data = self._get("/app.css")
        self.assertEqual(code, 200)
        self.assertIn(b"--bg-base", data)
        self.assertIn(b"judge-mode", data)

    def test_static_app_js_served(self) -> None:
        code, _, data = self._get("/app.js")
        self.assertEqual(code, 200)
        self.assertIn(b"updateHealthUI", data)

    def test_session_start_2048_and_export_csv(self) -> None:
        import time
        # Start a 2048 dry-run session with 2 moves
        code, start_resp = self._post("/api/session/start", {
            "game": "2048",
            "mode": "dry-run",
            "mock_model": True,
            "max_moves": 2,
        })
        self.assertEqual(code, 200)
        session_id = start_resp["session"]["session_id"]
        self.assertIn("2048", session_id)

        # Wait for session to finish
        for _ in range(30):
            time.sleep(0.05)
            _, curr, _ = self._get("/api/session/current")
            if not curr["active"]:
                break

        # Test CSV export
        code, _, csv_data = self._get(f"/api/logs/export-csv?session_id={session_id}")
        self.assertEqual(code, 200)
        self.assertIn(b"step,action,result", csv_data)
        self.assertIn(b"mock", csv_data)

        # Test verification endpoint
        code, verify_resp, _ = self._get(f"/api/logs/verify?session_id={session_id}")
        self.assertEqual(code, 200)
        self.assertTrue(verify_resp["is_valid"])

        # Test PDF export
        code, _, pdf_data = self._get(f"/api/logs/export-pdf?session_id={session_id}")
        self.assertEqual(code, 200)
        self.assertTrue(pdf_data.startswith(b"%PDF"))

        # Test sessions list
        code, sessions_resp, _ = self._get("/api/sessions")
        self.assertEqual(code, 200)
        self.assertTrue(len(sessions_resp["sessions"]) > 0)
        self.assertTrue(any(s["session_id"] == session_id for s in sessions_resp["sessions"]))

        # Test session records endpoint
        code, log_resp, _ = self._get(f"/api/logs/session?session_id={session_id}")
        self.assertEqual(code, 200)
        self.assertEqual(log_resp["session_id"], session_id)
        self.assertEqual(log_resp["count"], 2)

        # Test CSV export on benchmark log located in subfolder logs/benchmarks/
        code, _, bench_csv = self._get("/api/logs/export-csv?session_id=bench-2048-v3-13")
        self.assertEqual(code, 200)
        # Check UTF-8 BOM prefix
        self.assertTrue(bench_csv.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"step,action,result", bench_csv)

        # Test CSV export with view=inline (no BOM, text/plain)
        code, _, inline_csv = self._get(f"/api/logs/export-csv?session_id={session_id}&view=inline")
        self.assertEqual(code, 200)
        self.assertFalse(inline_csv.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(inline_csv.startswith(b"step,action,result"))

        # Test CSV export without session_id (graceful fallback to most recent log)
        code, _, fallback_csv = self._get("/api/logs/export-csv")
        self.assertEqual(code, 200)
        self.assertTrue(fallback_csv.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"step,action,result", fallback_csv)


if __name__ == "__main__":
    unittest.main()

