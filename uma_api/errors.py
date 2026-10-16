"""Typed exceptions for the game API layer.

``ApiError`` is raised by :meth:`UmaClient.call` when the game returns a
``result_code`` other than ``1``. It carries the structured ``result_code`` and
``endpoint`` so callers can branch on ``err.result_code`` instead of
substring-matching ``str(err)``.

The string form is kept **byte-identical** to the historical
``f'API error {rc} on {ep}: {detail}'`` (or an explicit ``message`` for the
special-cased responses) so the many existing ``str()``-matching call sites keep
working unchanged during the migration. ``api_error_result_code`` (defined below) already prefers a ``.result_code``
attribute over regex-parsing the message, so it becomes robust for free on
``ApiError`` instances.
"""

import re


class ApiError(Exception):
    """A game-API call returned a non-success ``result_code``.

    Args:
        result_code: the game's ``data_headers.result_code`` (int).
        endpoint: the API endpoint the call targeted.
        detail: optional human-readable detail (from ``format_api_error``).
        message: optional explicit string form. When omitted it defaults to
            ``f'API error {result_code} on {endpoint}: {detail}'`` -- the
            historical format -- so ``str(err)`` is unchanged for callers that
            still match on the message text.
    """

    def __init__(self, result_code, endpoint, detail=None, *, message=None):
        self.result_code = result_code
        self.endpoint = endpoint
        self.detail = detail
        if message is None:
            message = f'API error {result_code} on {endpoint}: {detail}'
        super().__init__(message)


class NodeDependenciesError(Exception):
    """The Node runtime or Steam Node packages are unavailable locally."""


class GameAuthRequiredError(ApiError):
    """Login was requested without a complete stored game-auth identity."""

    def __init__(self):
        super().__init__(
            0,
            "tool/start_session",
            "game auth is missing",
            message="Game auth is required before starting a session",
        )


class UnsupportedScenarioError(Exception):
    """An active career belongs to a scenario the bot cannot route or drive."""

    def __init__(self, scenario_id):
        self.scenario_id = scenario_id
        super().__init__(
            f"Scenario {scenario_id} is unsupported: the bot has no strategy for it. "
            "Finish or abandon this career in the game client; the bot cannot call "
            "finish for an unrouted scenario."
        )


class SteamAccountRemoveChainedError(ApiError):
    """Steam account linkage must be resolved before another API call."""


_API_ERROR_CODE_RE = re.compile(r"\bAPI error\s+(\d+)\b", re.IGNORECASE)


def api_error_result_code(error):
    """Return the game ``result_code`` for an exception, or ``None``.

    Prefers a typed ``.result_code``/``.response_code`` attribute (as carried by
    :class:`ApiError`); falls back to regex-parsing ``API error <N>`` out of
    ``str(error)`` so plain ``Exception`` messages of the historical form still
    resolve. It lives next to :class:`ApiError` so engine modules
    (``career_bot``/``uma_api``) and application callers can import it without
    depending on the web app.
    """
    for attr in ("result_code", "response_code"):
        value = getattr(error, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    match = _API_ERROR_CODE_RE.search(str(error))
    return int(match.group(1)) if match else None


BLOCKED_STATE_RESULT_CODES = frozenset({102, 1503})


def is_blocked_state_error(error):
    return api_error_result_code(error) in BLOCKED_STATE_RESULT_CODES
