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
        self.assertEqual(stop_resp["session"]["status"], "FINISHED")

        # 5. Confirm session is now inactive
        code, final_curr, _ = self._get("/api/session/current")
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


if __name__ == "__main__":
    unittest.main()
