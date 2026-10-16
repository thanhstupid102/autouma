import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.app import context
from backend.app.app import create_app
from backend.app.context import get_ctx
import backend.app.domain.rank_point as rank_point


def test_get_ctx_returns_request_app_state_ctx():
    sentinel = object()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=sentinel)))
    assert get_ctx(request) is sentinel


def test_create_app_ctx_base_dir_and_object_identity(tmp_path):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    ctx = app.state.ctx

    assert ctx.base_dir == tmp_path
    # dict/set/store/path fields must alias the SAME live objects the context
    # module owns and the app handlers read/mutate.
    assert ctx.preset_store is context.preset_store
    assert ctx.race_preset_store is context.race_preset_store
    assert ctx.bot_config_store is context.bot_config_store
    assert ctx.session_manager is context.session_manager
    assert ctx.chara_map is rank_point.chara_map
    assert ctx.support_map is rank_point.support_map


def test_master_json_reload_rebinds_live_context_maps(tmp_path):
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    shipped_dir = source_root / "data" / "json"
    shipped_dir.mkdir(parents=True)
    names = {
        "chara_list.json": "chara_map",
        "support_list.json": "support_map",
        "skill_data.json": "skill_data",
        "factor_map.json": "factor_map",
        "race_map.json": "race_map",
    }
    for filename in names:
        (shipped_dir / filename).write_text(
            json.dumps({"origin": "shipped"}), encoding="utf-8",
        )
    ctx = context.create_context(source_root, state_root=state_root)
    state_dir = state_root / "master_json"
    state_dir.mkdir(parents=True)
    for filename in names:
        (state_dir / filename).write_text(
            json.dumps({"origin": filename}), encoding="utf-8",
        )

    assert context.reload_master_json_data(source_root, state_root) is True

    for filename, attr in names.items():
        assert getattr(ctx, attr) == {"origin": filename}
        assert getattr(ctx, attr) is getattr(rank_point, attr)


def test_app_shutdown_stops_qr_child_processes(tmp_path):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    session = app.state.ctx.session_manager.get("shutdown-qr")
    qr = SimpleNamespace(stops=0)

    def stop():
        qr.stops += 1

    qr.stop = stop
    session._qr = qr

    with TestClient(app):
        pass

    assert qr.stops == 1
    assert app.state.ctx.session_manager.names() == []


def test_succession_relation_loaded_is_live_view_of_legacy(tmp_path, monkeypatch):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    ctx = app.state.ctx

    monkeypatch.setattr(rank_point, "succession_relation_loaded", True)
    assert ctx.succession_relation_loaded is True

    monkeypatch.setattr(rank_point, "succession_relation_loaded", False)
    assert ctx.succession_relation_loaded is False


def test_g1_win_saddle_loaded_is_live_view_of_legacy(tmp_path, monkeypatch):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    ctx = app.state.ctx

    monkeypatch.setattr(rank_point, "g1_win_saddle_loaded", True)
    assert ctx.g1_win_saddle_loaded is True

    monkeypatch.setattr(rank_point, "g1_win_saddle_loaded", False)
    assert ctx.g1_win_saddle_loaded is False


def test_default_account_is_live_view_of_context(tmp_path, monkeypatch):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    ctx = app.state.ctx

    monkeypatch.setattr(context, "DEFAULT_ACCOUNT", "some_account")
    assert ctx.default_account == "some_account"

    # Falsy context values (e.g. None) must come back as '' per the property contract.
    monkeypatch.setattr(context, "DEFAULT_ACCOUNT", None)
    assert ctx.default_account == ""


def test_succession_relation_loader_updates_live_ctx_view(tmp_path):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    ctx = app.state.ctx

    from backend.app.context import load_succession_relation_data

    ok = load_succession_relation_data(ctx)
    # The property must reflect whatever the loader just set on the rank_point
    # module -- not a stale value copied at ctx-construction time.
    assert ok is rank_point.succession_relation_loaded
    assert ctx.succession_relation_loaded == rank_point.succession_relation_loaded


def test_g1_win_saddle_loader_updates_live_ctx_view(tmp_path):
    app = create_app(tmp_path, state_root=tmp_path / "uma_runtime")
    ctx = app.state.ctx

    from backend.app.context import load_g1_win_saddle_data

    ok = load_g1_win_saddle_data(ctx)
    assert ok is rank_point.g1_win_saddle_loaded
    assert ctx.g1_win_saddle_loaded == rank_point.g1_win_saddle_loaded
