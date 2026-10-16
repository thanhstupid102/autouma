"""Guards the ApiResponse envelope contract (backend/app/schemas/envelope.py).

`response_model=ApiResponse` + `response_model_exclude_unset=True` is applied to
the JSON routes on the promise that it is BYTE-IDENTICAL to the hand-built
response dict: it only documents/validates the `{success, state, detail,
error_code}` envelope, `extra="allow"` passes the domain payload through untouched, and
`exclude_unset` re-emits exactly the keys the handler set. These tests fail if
someone drops `extra="allow"` / the `exclude_unset` flag, or an applied endpoint
stops returning `success`.
"""
import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.schemas.envelope import ApiResponse
from backend.app.app import create_app
from uma_api.bootstrap import BootstrapState


_REPO_ROOT = Path(__file__).resolve().parents[1]
_STATE_SERVICE_PATHS = (
    _REPO_ROOT / "backend/app/routers/auth/services/auth_service.py",
    _REPO_ROOT / "backend/app/routers/steam/services/steam_service.py",
)

_SAMPLES = [
    {"success": True, "skills": [{"id": "a", "x": 1}]},
    {"success": False, "detail": "No cached load/index response", "endpoint": "load/index"},
    {"success": True, "runner": None, "loop_active": False, "account": None},
    {"success": True},
    {"success": True, "detail": None, "min": 2.5, "max": 6.0, "disabled": False},
]


@pytest.mark.parametrize("payload", _SAMPLES)
def test_api_response_round_trips_byte_identical(payload):
    dumped = ApiResponse.model_validate(payload).model_dump(exclude_unset=True)
    assert dumped == payload


def test_api_response_requires_success():
    with pytest.raises(ValidationError):
        ApiResponse.model_validate({"skills": []})


def _emitted_response_states() -> set[str]:
    """Return Bootstrap enum values and literal auth/Steam response states."""
    states = {state.value for state in BootstrapState}
    for path in _STATE_SERVICE_PATHS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not (
                    isinstance(key, ast.Constant)
                    and key.value == "state"
                ):
                    continue
                assert isinstance(value, ast.Constant) and isinstance(value.value, str), (
                    f"{path} must use a string literal for response state values"
                )
                states.add(value.value)
    return states


def test_api_response_accepts_every_auth_and_steam_service_state():
    for state in _emitted_response_states():
        response = ApiResponse.model_validate({"success": False, "state": state})
        assert response.state == state


def test_applied_route_output_has_no_envelope_padding(tmp_path):
    # /api/skills carries response_model=ApiResponse; a tmp app has no skill_data
    # loaded, so the response must be EXACTLY the handler's dict -- no injected
    # detail/error_code keys from the envelope model.
    client = TestClient(
        create_app(tmp_path, state_root=tmp_path / "uma_runtime"),
        client=("127.0.0.1", 40000),
    )
    body = client.get("/api/skills").json()
    assert body == {"success": True, "skills": []}
