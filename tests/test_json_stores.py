"""Characterization tests for the four JSON file stores in
backend/app/domain/account_store.py:

  1. account config   (account_store_path / save_account_config / load_account_config)
  2. selection        (selection_store_path / save_selection / load_selection)
  3. auto-delete cfg  (auto_delete_config_store_path / save_auto_delete_config / load_auto_delete_config)
  4. steam token      (steam_token_path / save_steam_token / load_steam_token / clear_steam_token)

These pin the CURRENT on-disk behaviour (path/sanitize rules, serialization,
defaults on missing/corrupt file) before any refactor. They must stay green
across the JsonFileStore extraction in backend/app/domain/jsonstore.py.

The ``tmp_account_store`` fixture (a base-dir-redirected ``account_store``
module) lives in ``tests/conftest.py``.
"""

from uma_api import secret_store


# ---------------------------------------------------------------------------
# 1. account config
# ---------------------------------------------------------------------------

def test_account_store_path_layout(tmp_account_store):
    path = tmp_account_store.account_store_path("alice")
    assert path == tmp_account_store.state_root / "accounts" / "alice.json"


def test_account_store_path_sanitizes_name(tmp_account_store):
    # account_store_path does NOT collapse repeated dots (unlike the other
    # three stores) -- pin that exact, pre-existing behaviour.
    path = tmp_account_store.account_store_path("../evil")
    assert path.name == ".._evil.json"

    path2 = tmp_account_store.account_store_path("My Account 01!")
    assert path2.name == "My_Account_01_.json"


def test_account_store_path_blank_name_defaults(tmp_account_store):
    assert tmp_account_store.account_store_path("").name == "default.json"
    assert tmp_account_store.account_store_path(None).name == "default.json"


def test_account_config_save_load_round_trip(tmp_account_store):
    cfg = {"auth_key": "abc123", "viewer_id": "42", "udid": "u-1"}
    assert tmp_account_store.save_account_config("alice", cfg) is True
    loaded = tmp_account_store.load_account_config("alice")
    assert loaded == cfg


def test_account_config_save_drops_steam_session_ticket(tmp_account_store):
    cfg = {"auth_key": "abc123", "steam_session_ticket": "short-lived"}
    assert tmp_account_store.save_account_config("alice", cfg) is True
    loaded = tmp_account_store.load_account_config("alice")
    assert "steam_session_ticket" not in loaded
    assert loaded == {"auth_key": "abc123"}


def test_account_config_save_rejects_blank_name_or_cfg(tmp_account_store):
    assert tmp_account_store.save_account_config("", {"a": 1}) is False
    assert tmp_account_store.save_account_config("alice", {}) is False
    assert tmp_account_store.save_account_config("alice", None) is False


def test_account_config_load_missing_returns_none(tmp_account_store):
    assert tmp_account_store.load_account_config("nobody") is None
    assert tmp_account_store.load_account_config("") is None
    assert tmp_account_store.load_account_config(None) is None


def test_account_config_load_corrupt_returns_none(tmp_account_store):
    path = tmp_account_store.account_store_path("broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    assert tmp_account_store.load_account_config("broken") is None


def test_account_config_serialized_as_encrypted_bytes(tmp_account_store):
    tmp_account_store.save_account_config("alice", {"auth_key": "plain-secret"})
    path = tmp_account_store.account_store_path("alice")
    blob = path.read_bytes()
    assert blob.startswith(b"UMAENC1")
    assert b"auth_key" not in blob
    assert b"plain-secret" not in blob
    expected_backend = (
        "dpapi" if secret_store._dpapi_is_available() else "passphrase"
    )
    assert secret_store.keyring_backend(
        tmp_account_store.state_root / ".keyring",
    ) == expected_backend


# ---------------------------------------------------------------------------
# 2. selection
# ---------------------------------------------------------------------------

def test_selection_store_path_layout(tmp_account_store):
    path = tmp_account_store.selection_store_path("alice")
    assert path == tmp_account_store.state_root / "selections" / "alice.json"


def test_selection_store_path_sanitizes_and_collapses_dots(tmp_account_store):
    path = tmp_account_store.selection_store_path("../evil")
    assert path.name == "__evil.json"

    path2 = tmp_account_store.selection_store_path("My Account 01!")
    assert path2.name == "My_Account_01_.json"


def test_selection_store_path_blank_name_defaults(tmp_account_store):
    assert tmp_account_store.selection_store_path("").name == "default.json"
    assert tmp_account_store.selection_store_path(None).name == "default.json"


def test_selection_save_load_round_trip(tmp_account_store):
    sel = {"deck": "d1", "trainee": "t1", "friend": "f1", "parents": ["p1", "p2"], "event": "e1"}
    assert tmp_account_store.save_selection("acc-A", sel) is True
    assert tmp_account_store.load_selection("acc-A") == sel


def test_selection_save_rejects_blank_name(tmp_account_store):
    assert tmp_account_store.save_selection("", {"a": 1}) is False


def test_selection_save_none_selection_writes_empty_dict(tmp_account_store):
    assert tmp_account_store.save_selection("acc-A", None) is True
    assert tmp_account_store.load_selection("acc-A") == {}


def test_selection_load_missing_returns_none(tmp_account_store):
    assert tmp_account_store.load_selection("acc-B") is None
    assert tmp_account_store.load_selection("") is None


def test_selection_load_corrupt_returns_none(tmp_account_store):
    path = tmp_account_store.selection_store_path("broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")
    assert tmp_account_store.load_selection("broken") is None


def test_selection_load_non_dict_json_returns_none(tmp_account_store):
    path = tmp_account_store.selection_store_path("listy")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert tmp_account_store.load_selection("listy") is None


# ---------------------------------------------------------------------------
# 3. auto-delete config
# ---------------------------------------------------------------------------

def test_auto_delete_config_store_path_layout(tmp_account_store):
    path = tmp_account_store.auto_delete_config_store_path("alice")
    assert path == tmp_account_store.state_root / "auto_delete_trained" / "alice.json"


def test_auto_delete_config_store_path_sanitizes_and_collapses_dots(tmp_account_store):
    path = tmp_account_store.auto_delete_config_store_path("../evil")
    assert path.name == "__evil.json"


def test_auto_delete_config_store_path_blank_name_defaults(tmp_account_store):
    assert tmp_account_store.auto_delete_config_store_path("").name == "default.json"
    assert tmp_account_store.auto_delete_config_store_path(None).name == "default.json"


def test_auto_delete_config_save_load_round_trip_normalizes(tmp_account_store):
    cfg = {
        "enabled": True,
        "min_blue": "3",
        "min_pink": 2,
        "min_white": 1,
        "min_green": 0,
        "conditions": [{"name": "x", "mode": "exclude", "min_stars": "2"}],
    }
    assert tmp_account_store.save_auto_delete_config("acc-A", cfg) is True
    loaded = tmp_account_store.load_auto_delete_config("acc-A")
    assert loaded == {
        "enabled": True,
        "min_blue": 3,
        "min_pink": 2,
        "min_white": 1,
        "min_green": 0,
        "conditions": [{"name": "x", "mode": "exclude", "min_stars": 2}],
    }


def test_auto_delete_config_save_rejects_blank_name(tmp_account_store):
    assert tmp_account_store.save_auto_delete_config("", {"enabled": True}) is False


def test_auto_delete_config_load_missing_returns_default(tmp_account_store):
    assert tmp_account_store.load_auto_delete_config("nobody") == tmp_account_store.AUTO_DELETE_DEFAULT_CONFIG
    assert tmp_account_store.load_auto_delete_config("") == tmp_account_store.AUTO_DELETE_DEFAULT_CONFIG
    assert tmp_account_store.load_auto_delete_config(None) == tmp_account_store.AUTO_DELETE_DEFAULT_CONFIG


def test_auto_delete_config_load_corrupt_returns_default(tmp_account_store):
    path = tmp_account_store.auto_delete_config_store_path("broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad json", encoding="utf-8")
    assert tmp_account_store.load_auto_delete_config("broken") == tmp_account_store.AUTO_DELETE_DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# 4. steam token
# ---------------------------------------------------------------------------

def test_steam_token_path_layout(tmp_account_store):
    path = tmp_account_store.steam_token_path("bob")
    assert path == tmp_account_store.state_root / "accounts" / "bob.steam.json"


def test_steam_token_path_sanitizes_and_collapses_dots(tmp_account_store):
    path = tmp_account_store.steam_token_path("../evil")
    assert path.name == "__evil.steam.json"


def test_steam_token_path_blank_name_defaults(tmp_account_store):
    assert tmp_account_store.steam_token_path("").name == "default.steam.json"
    assert tmp_account_store.steam_token_path(None).name == "default.steam.json"


def test_steam_token_save_load_round_trip(tmp_account_store):
    assert tmp_account_store.save_steam_token("alice", "tok-123", "765611980000")
    blob = tmp_account_store.steam_token_path("alice").read_bytes()
    assert blob.startswith(b"UMAENC1")
    assert b"refresh_token" not in blob
    assert b"tok-123" not in blob
    loaded = tmp_account_store.load_steam_token("alice")
    assert loaded["refresh_token"] == "tok-123"
    assert loaded["steam_id"] == "765611980000"
    assert isinstance(loaded["saved_at"], (int, float))


def test_steam_token_save_rejects_blank_name_or_token(tmp_account_store):
    assert tmp_account_store.save_steam_token("", "tok") is False
    assert tmp_account_store.save_steam_token("alice", "") is False


def test_steam_token_load_missing_returns_none(tmp_account_store):
    assert tmp_account_store.load_steam_token("nobody") is None
    assert tmp_account_store.load_steam_token("") is None


def test_steam_token_load_corrupt_returns_none(tmp_account_store):
    path = tmp_account_store.steam_token_path("broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad json", encoding="utf-8")
    assert tmp_account_store.load_steam_token("broken") is None


def test_steam_token_clear_removes_file(tmp_account_store):
    tmp_account_store.save_steam_token("carol", "tok", "1")
    assert tmp_account_store.steam_token_path("carol").exists()
    tmp_account_store.clear_steam_token("carol")
    assert not tmp_account_store.steam_token_path("carol").exists()
    assert tmp_account_store.load_steam_token("carol") is None


def test_steam_token_clear_missing_is_safe(tmp_account_store):
    tmp_account_store.clear_steam_token("ghost")
