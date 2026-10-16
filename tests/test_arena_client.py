"""Unit tests for TopGameAI Arena API client.

All HTTP transport calls are strictly mocked with unittest.mock.
No live network connections or real sessions are initiated during testing.
"""

import io
import json
import socket
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from zenith.arena_client import (
    ArenaClient,
    ArenaError,
    ArenaHttpError,
    ArenaNetworkError,
    ArenaResponseError,
    ArenaTimeoutError,
)


class TestArenaClient(unittest.TestCase):
    """Test suite for ArenaClient transport logic."""

    def setUp(self):
        self.client = ArenaClient(
            base_url="https://topgameai.com/api/arena",
            timeout=5.0,
            default_agent_name="ZENITH",
        )
        # Global safety guard: prevent any unmocked call from touching real network
        self._urlopen_guard_patcher = patch(
            "urllib.request.urlopen",
            side_effect=RuntimeError("Safety violation: Unmocked network call attempted in test!"),
        )
        self._mock_guard = self._urlopen_guard_patcher.start()

    def tearDown(self):
        self._urlopen_guard_patcher.stop()

    def _mock_http_response(self, data: bytes, status: int = 200):
        """Create a mock HTTP response object conforming to urlopen context manager."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = data
        mock_resp.status = status
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        return mock_resp

    @patch("urllib.request.urlopen")
    def test_create_session_success(self, mock_urlopen):
        """create_session must send correct POST request and return parsed response."""
        expected_response = {
            "session_id": "sess-uuid-1234",
            "game": "snake",
            "state": {"width": 12, "height": 12, "score": 0},
            "done": False,
            "won": False,
            "score": 0,
            "steps": 0,
            "message": "Eat 15 foods.",
        }
        mock_urlopen.return_value = self._mock_http_response(
            json.dumps(expected_response).encode("utf-8")
        )

        result = self.client.create_session("snake")

        self.assertEqual(result, expected_response)
        mock_urlopen.assert_called_once()
        req: urllib.request.Request = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://topgameai.com/api/arena/sessions")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.headers["Content-type"], "application/json")
        self.assertEqual(req.headers["Accept"], "application/json")
        self.assertEqual(req.headers["User-agent"], "ZENITH-DecisionLayer/1.0")

        # Verify request body
        sent_body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(sent_body, {"game": "snake", "agent_name": "ZENITH"})

    @patch("urllib.request.urlopen")
    def test_create_session_custom_agent_name(self, mock_urlopen):
        """create_session must use custom agent_name when provided."""
        mock_urlopen.return_value = self._mock_http_response(b'{"session_id":"s1"}')
        self.client.create_session("2048", agent_name="TEST_BOT")

        req: urllib.request.Request = mock_urlopen.call_args[0][0]
        sent_body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(sent_body, {"game": "2048", "agent_name": "TEST_BOT"})

    @patch("urllib.request.urlopen")
    def test_get_session_success(self, mock_urlopen):
        """get_session must send GET request to /sessions/:id without request body."""
        expected_response = {
            "session_id": "sess-uuid-1234",
            "game": "snake",
            "done": False,
            "score": 60,
        }
        mock_urlopen.return_value = self._mock_http_response(
            json.dumps(expected_response).encode("utf-8")
        )

        result = self.client.get_session("sess-uuid-1234")

        self.assertEqual(result, expected_response)
        mock_urlopen.assert_called_once()
        req: urllib.request.Request = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://topgameai.com/api/arena/sessions/sess-uuid-1234")
        self.assertEqual(req.get_method(), "GET")
        self.assertIsNone(req.data)

    @patch("urllib.request.urlopen")
    def test_session_id_url_safe_encoding(self, mock_urlopen):
        """Session IDs containing special characters must be URL-encoded."""
        mock_urlopen.return_value = self._mock_http_response(b'{"session_id":"test"}')
        special_id = "sess/123?foo=bar#baz"
        self.client.get_session(special_id)

        req: urllib.request.Request = mock_urlopen.call_args[0][0]
        expected_encoded_id = "sess%2F123%3Ffoo%3Dbar%23baz"
        self.assertIn(expected_encoded_id, req.full_url)
        self.assertNotIn("sess/123", req.full_url)

    @patch("urllib.request.urlopen")
    def test_submit_action_success(self, mock_urlopen):
        """submit_action must POST {"action": action} to /sessions/:id/action."""
        expected_response = {
            "session_id": "sess-555",
            "game": "snake",
            "done": False,
            "won": False,
            "score": 120,
            "steps": 2,
        }
        mock_urlopen.return_value = self._mock_http_response(
            json.dumps(expected_response).encode("utf-8")
        )

        result = self.client.submit_action("sess-555", "right")

        self.assertEqual(result, expected_response)
        mock_urlopen.assert_called_once()
        req: urllib.request.Request = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://topgameai.com/api/arena/sessions/sess-555/action")
        self.assertEqual(req.get_method(), "POST")

        sent_body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(sent_body, {"action": "right"})

    @patch("urllib.request.urlopen")
    def test_get_leaderboard_success(self, mock_urlopen):
        """get_leaderboard must send GET request to /leaderboard/:game."""
        expected_response = {
            "game": "snake",
            "leaderboard": [{"rank": 1, "agentName": "ZENITH", "score": 1000}],
        }
        mock_urlopen.return_value = self._mock_http_response(
            json.dumps(expected_response).encode("utf-8")
        )

        result = self.client.get_leaderboard("snake")

        self.assertEqual(result, expected_response)
        req: urllib.request.Request = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://topgameai.com/api/arena/leaderboard/snake")
        self.assertEqual(req.get_method(), "GET")

    @patch("urllib.request.urlopen")
    def test_http_4xx_raises_arena_http_error(self, mock_urlopen):
        """HTTP 400 Bad Request must raise ArenaHttpError with status code and body."""
        error_body = b'{"error":"invalid_game","message":"Unknown game requested"}'
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://topgameai.com/api/arena/sessions",
            code=400,
            msg="Bad Request",
            hdrs={},  # type: ignore
            fp=io.BytesIO(error_body),
        )

        with self.assertRaises(ArenaHttpError) as ctx:
            self.client.create_session("invalid-game")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("invalid_game", ctx.exception.response_body)
        self.assertIn("Bad Request", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_http_404_not_found(self, mock_urlopen):
        """HTTP 404 (e.g. session expired) must raise ArenaHttpError with code 404."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://topgameai.com/api/arena/sessions/sess-expired",
            code=404,
            msg="Not Found",
            hdrs={},  # type: ignore
            fp=io.BytesIO(b'{"error":"session_not_found"}'),
        )

        with self.assertRaises(ArenaHttpError) as ctx:
            self.client.get_session("sess-expired")

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("session_not_found", ctx.exception.response_body)

    @patch("urllib.request.urlopen")
    def test_http_5xx_server_error(self, mock_urlopen):
        """HTTP 500 must raise ArenaHttpError with code 500."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://topgameai.com/api/arena/sessions/s1/action",
            code=500,
            msg="Internal Server Error",
            hdrs={},  # type: ignore
            fp=io.BytesIO(b"Server crashed"),
        )

        with self.assertRaises(ArenaHttpError) as ctx:
            self.client.submit_action("s1", "up")

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertEqual(ctx.exception.response_body, "Server crashed")

    @patch("urllib.request.urlopen")
    def test_network_connection_error(self, mock_urlopen):
        """Connection failures (URLError) must raise ArenaNetworkError."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        with self.assertRaises(ArenaNetworkError) as ctx:
            self.client.create_session("snake")

        self.assertIn("Connection refused", str(ctx.exception))
        # Verify it's not converted to timeout
        self.assertNotIsInstance(ctx.exception, ArenaTimeoutError)

    @patch("urllib.request.urlopen")
    def test_request_timeout_socket(self, mock_urlopen):
        """Socket timeout must raise ArenaTimeoutError."""
        mock_urlopen.side_effect = socket.timeout("timed out")

        with self.assertRaises(ArenaTimeoutError) as ctx:
            self.client.submit_action("s1", "up")

        self.assertIn("timed out", str(ctx.exception).lower())
        self.assertIsInstance(ctx.exception, ArenaNetworkError)

    @patch("urllib.request.urlopen")
    def test_request_timeout_urlerror_wrapped(self, mock_urlopen):
        """URLError wrapping a socket timeout must raise ArenaTimeoutError."""
        mock_urlopen.side_effect = urllib.error.URLError(socket.timeout("The read operation timed out"))

        with self.assertRaises(ArenaTimeoutError):
            self.client.get_session("s1")

    @patch("urllib.request.urlopen")
    def test_malformed_json_response(self, mock_urlopen):
        """Unparseable JSON in response must raise ArenaResponseError."""
        mock_urlopen.return_value = self._mock_http_response(b"<html><body>502 Bad Gateway</body></html>")

        with self.assertRaises(ArenaResponseError) as ctx:
            self.client.get_session("s1")

        self.assertIn("malformed json", str(ctx.exception).lower())

    @patch("urllib.request.urlopen")
    def test_empty_response_body(self, mock_urlopen):
        """Empty response body must raise ArenaResponseError."""
        mock_urlopen.return_value = self._mock_http_response(b"")

        with self.assertRaises(ArenaResponseError) as ctx:
            self.client.create_session("snake")

        self.assertIn("empty response body", str(ctx.exception).lower())

    @patch("urllib.request.urlopen")
    def test_non_dict_json_response(self, mock_urlopen):
        """Response that is valid JSON but not an object must raise ArenaResponseError."""
        mock_urlopen.return_value = self._mock_http_response(b'["item1", "item2"]')

        with self.assertRaises(ArenaResponseError) as ctx:
            self.client.create_session("snake")

        self.assertIn("must be a json object", str(ctx.exception).lower())

    @patch("urllib.request.urlopen")
    def test_non_utf8_response(self, mock_urlopen):
        """Non-UTF-8 bytes must raise ArenaResponseError."""
        mock_urlopen.return_value = self._mock_http_response(b"\x80\x81\x82")

        with self.assertRaises(ArenaResponseError) as ctx:
            self.client.get_session("s1")

        self.assertIn("utf-8", str(ctx.exception).lower())

    def test_input_validation_empty_arguments(self):
        """Empty or invalid string arguments must raise ValueError."""
        with self.assertRaises(ValueError):
            self.client.create_session("")
        with self.assertRaises(ValueError):
            self.client.create_session("snake", agent_name="")
        with self.assertRaises(ValueError):
            self.client.get_session("")
        with self.assertRaises(ValueError):
            self.client.submit_action("", "up")
        with self.assertRaises(ValueError):
            self.client.submit_action("s1", "")
        with self.assertRaises(ValueError):
            self.client.get_leaderboard("")

    def test_client_init_validation(self):
        """Client timeout must be positive."""
        with self.assertRaises(ValueError):
            ArenaClient(timeout=0)
        with self.assertRaises(ValueError):
            ArenaClient(timeout=-5.0)


if __name__ == "__main__":
    unittest.main()
