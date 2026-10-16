import os
import re
import subprocess
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest
import uvicorn

from backend.app import api_auth, cli, logging_setup
from backend.app.app import create_app
import integrations.game_process.gameproc as gameproc


TEST_TOKEN = "correct-horse-battery-staple"


@pytest.mark.parametrize(
    ("direct", "file_value", "expected"),
    [
        ("env-token", None, "env-token"),
        (None, "file-token", "file-token"),
        ("env-wins", "file-loses", "env-wins"),
        ("  env-token\r\n", None, "env-token"),
        (None, "one-newline\n", "one-newline"),
        (None, "two-newlines\n\n", "two-newlines"),
        (None, "\ufefffile-token\r\n", "file-token"),
        ("   ", "file-after-blank-env", "file-after-blank-env"),
        (None, " \t\r\n", None),
    ],
    ids=[
        "env-only",
        "file-only",
        "direct-precedence",
        "trim-direct",
        "one-trailing-newline",
        "trim-all-trailing-newlines",
        "file-bom",
        "blank-env-file-fallback",
        "whitespace-only-absent",
    ],
)
def test_api_token_resolution_sources(
    tmp_path,
    monkeypatch,
    direct,
    file_value,
    expected,
):
    if direct is not None:
        monkeypatch.setenv(api_auth.API_TOKEN_ENV, direct)
    if file_value is not None:
        token_file = tmp_path / "api-token"
        token_file.write_text(file_value, encoding="utf-8", newline="")
        monkeypatch.setenv(api_auth.API_TOKEN_FILE_ENV, str(token_file))

    assert api_auth.resolve_api_token() == expected


def test_gate_accepts_frontend_normalized_configured_token(tmp_path, monkeypatch):
    monkeypatch.setenv(api_auth.API_TOKEN_ENV, f"  {TEST_TOKEN}\r\n")
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    client = TestClient(app, client=("192.168.1.50", 40000))

    response = client.get(
        "/api/accounts",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )

    assert response.status_code == 200


def test_missing_api_token_file_exits_with_one_actionable_line(tmp_path, monkeypatch):
    missing = tmp_path / "missing-api-token"
    monkeypatch.setenv(api_auth.API_TOKEN_FILE_ENV, str(missing))

    with pytest.raises(api_auth.ApiTokenConfigError) as direct_error:
        api_auth.resolve_api_token()
    assert api_auth.API_TOKEN_FILE_ENV in str(direct_error.value)
    assert str(missing) in str(direct_error.value)
    assert api_auth.API_TOKEN_ENV in str(direct_error.value)

    with pytest.raises(SystemExit) as startup_error:
        api_auth.resolve_api_token_or_exit()
    assert "\n" not in str(startup_error.value)
    assert startup_error.value.__cause__ is None


def test_gate_off_preserves_existing_api_behavior(tmp_path):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    client = TestClient(app, client=("127.0.0.1", 40000))

    status = client.get(api_auth.AUTH_GATE_STATUS_PATH)
    response = client.get("/api/accounts")

    assert status.status_code == 200
    assert status.json() == {"gate_required": False}
    assert response.status_code == 200


def test_api_peer_guard_covers_remote_local_and_non_tcp_clients(
    tmp_path,
    monkeypatch,
):
    def build_app(name, token=None):
        monkeypatch.delenv(api_auth.API_TOKEN_ENV, raising=False)
        monkeypatch.delenv(api_auth.API_TOKEN_FILE_ENV, raising=False)
        if token is not None:
            monkeypatch.setenv(api_auth.API_TOKEN_ENV, token)
        base_dir = tmp_path / name
        base_dir.mkdir()
        return create_app(base_dir, state_root=base_dir / "uma_runtime")

    remote_address = ("192.168.1.50", 40000)
    unauthenticated_app = build_app("unauthenticated")
    remote_client = TestClient(unauthenticated_app, client=remote_address)

    blocked = remote_client.get("/api/accounts")
    spoofed_loopback = remote_client.get(
        "/api/accounts",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert blocked.status_code == 401
    detail = blocked.json()["detail"]
    assert "unauthenticated" in detail
    assert "loopback" in detail
    assert api_auth.API_TOKEN_ENV in detail
    assert api_auth.API_TOKEN_FILE_ENV in detail
    assert "A valid API token is required." not in detail
    assert spoofed_loopback.status_code == 401
    assert spoofed_loopback.json() == blocked.json()

    authenticated_app = build_app("authenticated", TEST_TOKEN)
    authenticated_remote = TestClient(authenticated_app, client=remote_address)
    accepted = authenticated_remote.get(
        "/api/accounts",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )
    missing = authenticated_remote.get("/api/accounts")
    wrong = authenticated_remote.get(
        "/api/accounts",
        headers={"X-Api-Token": "wrong"},
    )

    assert accepted.status_code == 200
    for rejected in (missing, wrong):
        assert rejected.status_code == 401
        assert rejected.json() == {
            "success": False,
            "detail": "A valid API token is required.",
        }

    local_app = build_app("local")
    for host in ("127.0.0.1", "::1"):
        local_client = TestClient(local_app, client=(host, 40000))
        assert local_client.get("/api/accounts").status_code == 200

    non_ip_client = TestClient(local_app, client=("attacker.invalid", 40000))
    non_ip_response = non_ip_client.get(
        "/api/accounts",
        headers={"X-Forwarded-For": "attacker.invalid"},
    )
    assert non_ip_response.status_code == 401

    async def app_without_client(scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope)
            scope["client"] = None
        await local_app(scope, receive, send)

    absent_client = TestClient(app_without_client)
    assert absent_client.get("/api/accounts").status_code == 401


def test_gate_matches_protected_routes_beneath_root_path(tmp_path, monkeypatch):
    monkeypatch.setenv(api_auth.API_TOKEN_ENV, TEST_TOKEN)
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    client = TestClient(
        app,
        root_path="/prefix",
        client=("127.0.0.1", 40000),
    )

    blocked = client.get("/prefix/api/accounts")
    accepted = client.get(
        "/prefix/api/accounts",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )

    assert blocked.status_code == 401
    assert accepted.status_code == 200


def test_api_peer_guard_leaves_ungated_surfaces_public(tmp_path):
    dist = tmp_path / "frontend" / "dist"
    static = dist / "static"
    asset_data = tmp_path / "assets" / "data"
    static.mkdir(parents=True)
    asset_data.mkdir(parents=True)
    (dist / "index.html").write_text("<html>dashboard shell</html>", encoding="utf-8")
    (static / "app.js").write_text("console.log('ui')", encoding="utf-8")
    (asset_data / "public.json").write_text('{"public": true}', encoding="utf-8")
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    client = TestClient(app, client=("192.168.1.50", 40000))

    assert client.get("/api/accounts").status_code == 401
    assert client.get("/").status_code == 200
    assert client.get("/account/example/setup").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    asset_response = client.get("/assets/data/public.json")
    assert asset_response.status_code == 200
    assert asset_response.json() == {"public": True}
    assert client.get(api_auth.AUTH_GATE_STATUS_PATH).json() == {
        "gate_required": False,
    }


def test_gate_accepts_both_headers_with_authorization_precedence(
    tmp_path,
    monkeypatch,
    caplog,
):
    monkeypatch.setenv(api_auth.API_TOKEN_ENV, TEST_TOKEN)
    compare_calls = []
    real_compare_digest = api_auth.hmac.compare_digest

    def capture_compare_digest(left, right):
        compare_calls.append((left, right))
        return real_compare_digest(left, right)

    monkeypatch.setattr(api_auth.hmac, "compare_digest", capture_compare_digest)
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    client = TestClient(app)

    no_header = client.get("/api/accounts")
    wrong = client.get("/api/accounts", headers={"X-Api-Token": "wrong"})
    bearer = client.get(
        "/api/accounts",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    )
    alternate = client.get(
        "/api/accounts",
        headers={"X-Api-Token": TEST_TOKEN},
    )
    canonical_wins = client.get(
        "/api/accounts",
        headers={
            "Authorization": f"Bearer {TEST_TOKEN}",
            "X-Api-Token": "wrong",
        },
    )
    canonical_rejects = client.get(
        "/api/accounts",
        headers={
            "Authorization": "Bearer wrong",
            "X-Api-Token": TEST_TOKEN,
        },
    )

    assert no_header.status_code == 401
    assert wrong.status_code == 401
    assert bearer.status_code == 200
    assert alternate.status_code == 200
    assert canonical_wins.status_code == 200
    assert canonical_rejects.status_code == 401
    assert no_header.json() == {
        "success": False,
        "detail": "A valid API token is required.",
    }
    assert TEST_TOKEN not in no_header.text
    assert compare_calls
    assert TEST_TOKEN not in caplog.text


def test_auth_gate_status_is_the_only_unauthenticated_api_route(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(api_auth.API_TOKEN_ENV, TEST_TOKEN)
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    client = TestClient(app)
    api_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
    ]

    assert api_routes
    allowed_paths = set()
    for route in api_routes:
        path = re.sub(r"\{[^}]+\}", "route-coverage-probe", route.path)
        for method in route.methods:
            response = client.request(method, path)
            if response.status_code != 401:
                allowed_paths.add(route.path)
            else:
                assert response.json()["success"] is False

    # Exactly two /api routes may answer without a token, both deliberate:
    #  - the gate-status probe, so the UI knows whether to prompt
    #  - card artwork, requested by <img> tags that cannot send a header
    assert allowed_paths == {
        api_auth.AUTH_GATE_STATUS_PATH,
        "/api/images/{image_name}",
    }
    assert client.get(api_auth.AUTH_GATE_STATUS_PATH).json() == {
        "gate_required": True,
    }


def test_ui_spa_static_and_assets_stay_ungated(tmp_path, monkeypatch):
    monkeypatch.setenv(api_auth.API_TOKEN_ENV, TEST_TOKEN)
    dist = tmp_path / "frontend" / "dist"
    static = dist / "static"
    asset_data = tmp_path / "assets" / "data"
    static.mkdir(parents=True)
    asset_data.mkdir(parents=True)
    (dist / "index.html").write_text("<html>dashboard shell</html>", encoding="utf-8")
    (static / "app.js").write_text("console.log('ui')", encoding="utf-8")
    (asset_data / "public.json").write_text('{"public": true}', encoding="utf-8")
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    client = TestClient(app)

    assert client.get("/").status_code == 200
    assert client.get("/account/example/setup").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    asset_response = client.get("/assets/data/public.json")
    assert asset_response.status_code == 200
    assert asset_response.json() == {"public": True}


@pytest.mark.parametrize(
    ("host", "token", "starts"),
    [
        ("127.0.0.1", None, True),
        ("127.0.0.5", None, True),
        ("::1", None, True),
        ("localhost", None, True),
        ("0.0.0.0", None, False),
        ("::", None, False),
        ("192.168.1.20", None, False),
        ("does-not-resolve.invalid", None, False),
        ("0.0.0.0", TEST_TOKEN, True),
    ],
    ids=[
        "ipv4-loopback",
        "ipv4-loopback-subnet",
        "ipv6-loopback",
        "localhost-name",
        "ipv4-wildcard-refused",
        "ipv6-wildcard-refused",
        "lan-refused",
        "unresolvable-refused",
        "wildcard-with-token",
    ],
)
def test_cli_bind_interlock(monkeypatch, host, token, starts):
    if token is not None:
        monkeypatch.setenv(api_auth.API_TOKEN_ENV, token)
    monkeypatch.setattr(
        gameproc,
        "parse_cli_args",
        lambda _args: (1616, None, False, host),
    )
    monkeypatch.setattr(gameproc, "set_console_topmost", lambda: None)
    monkeypatch.setattr(gameproc, "kill_listeners_on_port", lambda _port: None)
    monkeypatch.setattr(logging_setup, "configure_console_logging", lambda: None)
    uvicorn_calls = []
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda app, host, port, log_level: uvicorn_calls.append(
            (app, host, port, log_level),
        ),
    )
    app = FastAPI()

    if starts:
        cli.run(app)
        assert uvicorn_calls == [(app, host, 1616, "error")]
        assert app.state.api_token == token
    else:
        with pytest.raises(SystemExit) as caught:
            cli.run(app)
        assert host in str(caught.value)
        assert api_auth.API_TOKEN_ENV in str(caught.value)
        assert api_auth.API_TOKEN_FILE_ENV in str(caught.value)
        assert "\n" not in str(caught.value)
        assert uvicorn_calls == []


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("192.168.1.20", "http://192.168.1.20:1717"),
        ("::1", "http://[::1]:1717"),
        ("0.0.0.0", "http://localhost:1717 (bound on all IPv4 interfaces)"),
        ("::", "http://[::1]:1717 (bound on all IPv6 interfaces)"),
    ],
    ids=["lan-host", "ipv6-host", "ipv4-wildcard", "ipv6-wildcard"],
)
def test_web_ui_access_location(host, expected):
    assert cli._web_ui_access_location(host, 1717) == expected


def test_card_artwork_is_reachable_without_a_token(tmp_path, monkeypatch):
    """<img src> cannot send Authorization, so artwork must not be gated."""
    monkeypatch.setenv(api_auth.API_TOKEN_ENV, TEST_TOKEN)
    images = tmp_path / "data" / "images"
    images.mkdir(parents=True)
    (images / "100101.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    client = TestClient(app)

    response = client.get("/api/images/100101.png")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")
    # ...while a real API route beside it stays gated.
    assert client.get("/api/accounts").status_code == 401


def test_ungated_artwork_path_cannot_be_widened(tmp_path, monkeypatch):
    """The ungating is one strict segment; it must not become a traversal."""
    monkeypatch.setenv(api_auth.API_TOKEN_ENV, TEST_TOKEN)
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    client = TestClient(app)

    for hostile in (
        "/api/images/../accounts",
        "/api/images/..%2Faccounts",
        "/api/images/.%2E/accounts",
        "/api/images/",
        "/api/images",
    ):
        assert client.get(hostile).status_code != 200, hostile

    assert not api_auth._is_gated_api_path("/api/images/100101.png")
    for hostile in (
        "/api/images/../accounts",
        "/api/images/a/b",
        "/api/images/",
        "/api/accounts",
    ):
        assert api_auth._is_gated_api_path(hostile) is True, hostile


def _make_asset_escape_link(link, outside_dir):
    if os.name != "nt":
        link.symlink_to(outside_dir / "secret.txt")
        return link.name
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside_dir)],
        check=True,
        capture_output=True,
    )
    return rf"{link.name}\secret.txt"


@pytest.mark.parametrize(
    ("route", "asset_parts"),
    [
        ("/assets/data", ("assets", "data")),
        ("/races", ("assets", "races")),
    ],
)
def test_ungated_asset_routes_reject_path_escapes(
    tmp_path, route, asset_parts,
):
    allowed_dir = tmp_path.joinpath(*asset_parts)
    allowed_dir.mkdir(parents=True)
    (allowed_dir / "legitimate asset.json").write_text("public", encoding="utf-8")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret = outside_dir / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    (tmp_path / "settings.json").write_text("private", encoding="utf-8")
    (tmp_path / "assets" / "settings.json").write_text("private", encoding="utf-8")
    link_name = _make_asset_escape_link(allowed_dir / "escape-link", outside_dir)
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    client = TestClient(app, client=("192.168.1.50", 40000))

    legitimate = client.get(f"{route}/{quote('legitimate asset.json', safe='')}")
    assert legitimate.status_code == 200
    assert legitimate.content == b"public"

    hostile_names = (
        r"..\..\settings.json",
        "../settings.json",
        str(secret.resolve()),
        link_name,
    )
    for hostile_name in hostile_names:
        response = client.get(f"{route}/{quote(hostile_name, safe='')}")
        assert response.status_code == 404, hostile_name
