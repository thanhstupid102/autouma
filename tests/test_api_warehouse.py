from concurrent.futures import ThreadPoolExecutor
import os
import stat
import threading

import pytest

import core.runtime_paths as runtime_paths
from uma_api import api_warehouse  # noqa: E402
from uma_api import secret_store  # noqa: E402
from uma_api.client import UmaClient  # noqa: E402


def sample_response(result_code=1):
    return {
        "response_code": 1,
        "data_headers": {"result_code": result_code, "servertime": 12345},
        "data": {"tp_info": {"current_tp": 10}, "items": [1, 2, 3]},
    }


def test_endpoint_slug_is_readable_and_safe():
    assert api_warehouse.endpoint_slug("load/index") == "load__index"
    assert api_warehouse.endpoint_slug("single_mode_free/load") == "single_mode_free__load"
    assert "/" not in api_warehouse.endpoint_slug("../evil/load")
    assert "\\" not in api_warehouse.endpoint_slug("evil\\load")


def test_write_then_read_latest_round_trips(tmp_path):
    path = api_warehouse.write_latest(tmp_path, "alice", "load/index", sample_response())
    assert path == api_warehouse.response_path(tmp_path, "alice", "load/index")
    record = api_warehouse.read_latest(tmp_path, "alice", "load/index")
    assert record["account"] == "alice"
    assert record["endpoint"] == "load/index"
    assert record["endpoint_slug"] == "load__index"
    assert record["response_code"] == 1
    assert record["result_code"] == 1
    assert record["data"] == sample_response()["data"]
    assert api_warehouse.read_latest_data(tmp_path, "alice", "load/index") == sample_response()["data"]


def test_write_latest_atomically_replaces_complete_record(tmp_path, monkeypatch):
    old_response = sample_response()
    new_response = sample_response()
    new_response["data"]["items"] = [4, 5, 6]
    path = api_warehouse.write_latest(
        tmp_path, "alice", "load/index", old_response,
    )
    replace_ready = threading.Event()
    release_replace = threading.Event()
    real_replace = runtime_paths.os.replace

    def blocked_replace(source, destination):
        replace_ready.set()
        if not release_replace.wait(timeout=5):
            raise TimeoutError("test did not release atomic replace")
        real_replace(source, destination)

    monkeypatch.setattr(runtime_paths.os, "replace", blocked_replace)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            api_warehouse.write_latest,
            tmp_path,
            "alice",
            "load/index",
            new_response,
        )
        assert replace_ready.wait(timeout=5)
        try:
            for _ in range(25):
                assert api_warehouse.read_latest_data(
                    tmp_path, "alice", "load/index",
                ) == old_response["data"]
        finally:
            release_replace.set()
        assert future.result(timeout=5) == path

    assert api_warehouse.read_latest_data(
        tmp_path, "alice", "load/index",
    ) == new_response["data"]


def test_warehouse_skips_fsync_but_secret_store_keeps_it(
    tmp_path, monkeypatch,
):
    fsync_calls = []
    monkeypatch.setattr(
        runtime_paths.os,
        "fsync",
        lambda fd: fsync_calls.append(fd),
    )

    assert api_warehouse.write_latest(
        tmp_path, "alice", "load/index", sample_response(),
    ) is not None
    assert fsync_calls == []

    secret_store._atomic_write(tmp_path / ".keyring", b"wrapped key")
    assert len(fsync_calls) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_warehouse_files_remain_private_on_posix(tmp_path):
    path = api_warehouse.write_latest(
        tmp_path, "alice", "load/index", sample_response(),
    )

    assert path is not None
    assert stat.S_IMODE(path.parent.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_account_name_is_sanitized(tmp_path):
    path = api_warehouse.write_latest(tmp_path, "../evil account", "../../load/index", sample_response())
    warehouse_root = tmp_path / "api_warehouse"
    assert path is not None
    assert path.is_relative_to(warehouse_root)
    assert ".." not in path.relative_to(warehouse_root).parts
    assert path.name.endswith(".json")


def test_clear_account_removes_cache(tmp_path):
    api_warehouse.write_latest(tmp_path, "alice", "load/index", sample_response())
    assert api_warehouse.account_dir(tmp_path, "alice").exists()
    assert api_warehouse.clear_account(tmp_path, "alice") is True
    assert not api_warehouse.account_dir(tmp_path, "alice").exists()
    assert api_warehouse.clear_account(tmp_path, "alice") is True


def test_uma_client_store_api_response_best_effort(tmp_path):
    client = UmaClient.__new__(UmaClient)
    client.api_warehouse_base_dir = tmp_path
    client.api_warehouse_account = "alice"
    client._store_api_response("load/index", sample_response())
    assert api_warehouse.response_path(tmp_path, "alice", "load/index").exists()


def test_uma_client_store_api_response_skips_failed_result(tmp_path):
    client = UmaClient.__new__(UmaClient)
    client.api_warehouse_base_dir = tmp_path
    client.api_warehouse_account = "alice"
    client._store_api_response("load/index", sample_response(result_code=205))
    assert not api_warehouse.response_path(tmp_path, "alice", "load/index").exists()
