from pathlib import Path

from backend.app.app import create_app


EXPECTED_ROUTES = {
    '/',
    '/api/auth/login',
    '/api/auth/transition-code/chain',
    '/api/auth/leave-session',
    '/api/auth/steam/unbind/preflight',
    '/api/auth/steam/unbind',
    '/api/auth/session',
    '/api/auth/session/refresh',
    '/api/accounts',
    '/api/career/start',
    '/api/career/run',
    '/api/career/event-info',
    '/api/career/friends',
    '/api/debug/raw-load',
    '/api/settings/turn-delay',
    '/api/bot-config',
    '/api/presets',
    '/api/events/catalog',
    '/api/auth/steam/qr/start',
}


def test_create_app_registers_expected_routes(tmp_path):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    paths = {route.path for route in app.routes}
    missing = EXPECTED_ROUTES - paths
    assert missing == set()
    assert '/api/auth/logout' not in paths
    assert '/api/auth/recapture' not in paths
    assert '/api/auth/recapture/status' not in paths
    assert Path(app.state.ctx.base_dir) == tmp_path
