"""HTTP client for the official TopGameAI Arena API.

Base URL: https://topgameai.com/api/arena
Official API Docs: https://topgameai.com/arena/docs

This module provides an HTTP transport layer for interacting with the Arena API
using Python's standard library only. It strictly isolates transport mechanics
from move selection, game logic, Laya inference, and session logging.

Design principles:
- Standard library only (urllib.request, json, urllib.error, urllib.parse).
- Configurable base URL and request timeout.
- Explicit path quoting for URL safety.
- Clear, distinct exception hierarchy (HTTP errors, network errors, timeouts, malformed responses).
- No automatic action retries (to avoid duplicate action submission when responses are lost).
- Returns raw session/state data as received without fabricating or mutating fields.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional


class ArenaError(Exception):
    """Base exception for all Arena client errors."""
    pass


class ArenaHttpError(ArenaError):
    """Raised when the Arena API responds with an HTTP 4xx or 5xx status code."""

    def __init__(self, message: str, status_code: int, response_body: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class ArenaNetworkError(ArenaError):
    """Raised when a network connection or transport failure occurs."""
    pass


class ArenaTimeoutError(ArenaNetworkError):
    """Raised when an HTTP request or response reading times out."""
    pass


class ArenaResponseError(ArenaError):
    """Raised when the API response is empty, malformed, or structurally invalid."""
    pass


class ArenaClient:
    """Synchronous HTTP client for TopGameAI Arena API."""

    DEFAULT_BASE_URL: str = "https://topgameai.com/api/arena"
    DEFAULT_TIMEOUT: float = 10.0
    DEFAULT_AGENT_NAME: str = "ZENITH"
    DEFAULT_USER_AGENT: str = "ZENITH-DecisionLayer/1.0"

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        default_agent_name: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        """Initialize the Arena API client.

        Args:
            base_url: Arena API base URL (defaults to official https://topgameai.com/api/arena).
            timeout: Request timeout in seconds (defaults to 10.0).
            default_agent_name: Agent name to use when none specified (defaults to 'ZENITH').
            user_agent: Custom User-Agent header (defaults to 'ZENITH-DecisionLayer/1.0').
        """
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = float(timeout if timeout is not None else self.DEFAULT_TIMEOUT)
        self.default_agent_name = default_agent_name or self.DEFAULT_AGENT_NAME
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT

        if self.timeout <= 0:
            raise ValueError(f"Timeout must be positive, got {self.timeout}")

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform an HTTP request and parse the JSON object response.

        Args:
            method: HTTP method string ('GET', 'POST').
            path: Relative path beginning with '/' (e.g. '/sessions').
            body: Optional dictionary to serialize as JSON body.

        Returns:
            Parsed response dictionary.

        Raises:
            ArenaHttpError: On HTTP 4xx or 5xx responses.
            ArenaTimeoutError: On socket or urllib request timeout.
            ArenaNetworkError: On connection failure, DNS resolution error, etc.
            ArenaResponseError: On empty body, non-UTF-8, or non-JSON response.
        """
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }

        data_bytes: Optional[bytes] = None
        if body is not None:
            data_bytes = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(
            url=url,
            data=data_bytes,
            headers=headers,
            method=method.upper(),
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw_data = resp.read()
        except urllib.error.HTTPError as exc:
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise ArenaHttpError(
                message=f"Arena HTTP {exc.code} {exc.reason} for {method} {url}: {body_text}",
                status_code=exc.code,
                response_body=body_text,
            ) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason).lower():
                raise ArenaTimeoutError(
                    f"Arena request timed out for {method} {url}: {reason}"
                ) from exc
            raise ArenaNetworkError(
                f"Arena connection failed for {method} {url}: {reason}"
            ) from exc
        except (socket.timeout, TimeoutError) as exc:
            raise ArenaTimeoutError(
                f"Arena request timed out for {method} {url}: {exc}"
            ) from exc
        except Exception as exc:
            raise ArenaNetworkError(
                f"Unexpected transport error for {method} {url}: {exc}"
            ) from exc

        if not raw_data or not raw_data.strip():
            raise ArenaResponseError(f"Arena returned empty response body for {method} {url}")

        try:
            decoded_text = raw_data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArenaResponseError(
                f"Arena response could not be decoded as UTF-8 for {method} {url}: {exc}"
            ) from exc

        try:
            parsed = json.loads(decoded_text)
        except json.JSONDecodeError as exc:
            raise ArenaResponseError(
                f"Arena returned malformed JSON for {method} {url}: {exc.msg} at pos {exc.pos}"
            ) from exc

        if not isinstance(parsed, dict):
            raise ArenaResponseError(
                f"Arena response must be a JSON object, got {type(parsed).__name__} for {method} {url}"
            )

        return parsed

    def create_session(
        self,
        game: str,
        agent_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new game session on the Arena.

        Endpoint: POST /sessions
        Body: {"game": "<game>", "agent_name": "<agent_name>"}

        Args:
            game: Game identifier (e.g. 'snake', '2048').
            agent_name: Agent identifier (defaults to self.default_agent_name, e.g. 'ZENITH').

        Returns:
            Session object containing initial state, session_id, and metadata.
        """
        if not game or not isinstance(game, str) or not game.strip():
            raise ValueError("game must be a non-empty string.")

        if agent_name is not None and (not isinstance(agent_name, str) or not agent_name.strip()):
            raise ValueError("agent_name must be a non-empty string.")

        name = agent_name if agent_name is not None else self.default_agent_name
        if not name or not isinstance(name, str) or not name.strip():
            raise ValueError("agent_name must be a non-empty string.")

        payload = {
            "game": game.strip(),
            "agent_name": name.strip(),
        }
        return self._request("POST", "/sessions", body=payload)

    def get_session(self, session_id: str) -> Dict[str, Any]:
        """Retrieve the current state of a session.

        Endpoint: GET /sessions/:session_id

        Args:
            session_id: The unique identifier of the game session.

        Returns:
            Current session object.
        """
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string.")

        quoted_id = urllib.parse.quote(session_id.strip(), safe="")
        return self._request("GET", f"/sessions/{quoted_id}")

    def submit_action(self, session_id: str, action: str) -> Dict[str, Any]:
        """Submit an action move to an active game session.

        Endpoint: POST /sessions/:session_id/action
        Body: {"action": "<action>"}

        NOTE: No automatic retries are performed on network failures or timeouts.
        Retrying action submissions blindly could result in duplicate execution
        or corrupted step synchronization.

        Args:
            session_id: The unique identifier of the game session.
            action: Action move string (e.g. 'up', 'down', 'left', 'right').

        Returns:
            Updated session object with new state, done, won, score, etc.
        """
        if not session_id or not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string.")
        if not action or not isinstance(action, str) or not action.strip():
            raise ValueError("action must be a non-empty string.")

        quoted_id = urllib.parse.quote(session_id.strip(), safe="")
        payload = {"action": action.strip()}
        return self._request("POST", f"/sessions/{quoted_id}/action", body=payload)

    def get_leaderboard(self, game: str) -> Dict[str, Any]:
        """Retrieve the current leaderboard for a game.

        Endpoint: GET /leaderboard/:game

        Args:
            game: Game identifier ('snake', '2048').

        Returns:
            Leaderboard response dictionary.
        """
        if not game or not isinstance(game, str) or not game.strip():
            raise ValueError("game must be a non-empty string.")

        quoted_game = urllib.parse.quote(game.strip(), safe="")
        return self._request("GET", f"/leaderboard/{quoted_game}")
