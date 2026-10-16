import contextlib
import sqlite3
from pathlib import Path

import lz4.frame
import pytest

import uma_data
import uma_data.master_updater as master_updater
import uma_data.legacy_json as legacy_json
from uma_data.master_updater import (
    ManifestFormatError,
    _integrity_check,
    _resolve_root_url,
    calculate_hname,
    parse_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def _varuint(value):
    groups = [value & 0x7F]
    value >>= 7
    while value:
        groups.append(value & 0x7F)
        value >>= 7
    groups.reverse()
    return bytes(
        group | (0x80 if index < len(groups) - 1 else 0)
        for index, group in enumerate(groups)
    )


def _simplified_manifest(name, size, checksum):
    schema = master_updater.SIMPLIFIED_SCHEMA
    return (
        master_updater.BSV_MAGIC
        + len(schema).to_bytes(2, "big")
        + schema
        + name.encode("utf-8")
        + b"\0"
        + _varuint(size)
        + checksum.to_bytes(8, "big")
    )


def _full_manifest(name, size, checksum):
    schema = master_updater.FULL_SCHEMA
    return (
        master_updater.BSV_MAGIC
        + len(schema).to_bytes(2, "big")
        + schema
        + name.encode("utf-8")
        + b"\0\0\0\0"
        + _varuint(size)
        + checksum.to_bytes(8, "big")
        + (0).to_bytes(8, "big", signed=True)
    )


def _offline_cdn_chain(database_bytes):
    compressed_master = lz4.frame.compress(database_bytes)
    master_checksum = 0x123456789ABCDEF0
    master_manifest = lz4.frame.compress(
        _full_manifest("master.mdb.lz4", len(compressed_master), master_checksum)
    )
    master_manifest_checksum = 0x23456789ABCDEF1
    windows_manifest = lz4.frame.compress(
        _simplified_manifest(
            "master", len(master_manifest), master_manifest_checksum,
        )
    )
    windows_checksum = 0x3456789ABCDEF2
    root_manifest = lz4.frame.compress(
        _simplified_manifest("Windows", len(windows_manifest), windows_checksum)
    )
    return {
        "root": root_manifest,
        master_updater.calculate_hname(
            "Windows", windows_checksum, len(windows_manifest),
        ): windows_manifest,
        master_updater.calculate_hname(
            "master", master_manifest_checksum, len(master_manifest),
        ): master_manifest,
        master_updater.calculate_hname(
            "master.mdb.lz4", master_checksum, len(compressed_master),
        ): compressed_master,
    }


class _OfflineResponse:
    def __init__(self, payload, reads=None, fail_after_first=False):
        self.payload = payload
        self.reads = reads
        self.fail_after_first = fail_after_first
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def getcode(self):
        return 200

    def read(self, size=-1):
        if self.reads is not None:
            self.reads.append(size)
        if self.fail_after_first and self.offset:
            raise OSError("simulated interrupted download")
        if size is None or size < 0:
            chunk = self.payload[self.offset:]
        else:
            end = self.offset + size
            if self.fail_after_first:
                end = min(end, self.offset + max(1, len(self.payload) // 2))
            chunk = self.payload[self.offset:end]
        self.offset += len(chunk)
        return chunk


def _stub_cdn(monkeypatch, chain, *, master_reads=None, interrupt_master=False):
    master_hname = next(reversed(chain))

    def fake_urlopen(request, timeout=30):
        url = request.full_url
        if "root.manifest.bsv.lz4" in url:
            return _OfflineResponse(chain["root"])
        for hname, payload in chain.items():
            if hname != "root" and hname in url:
                return _OfflineResponse(
                    payload,
                    reads=master_reads if hname == master_hname else None,
                    fail_after_first=interrupt_master and hname == master_hname,
                )
        raise AssertionError(f"unexpected offline CDN URL: {url}")

    monkeypatch.setattr(master_updater.urllib.request, "urlopen", fake_urlopen)


MASTER_BSV = bytes.fromhex(
    "bf11000c013011074040111112210813"
    "6d61737465722e6d64622e6c7a3400"
    "00"
    "00"
    "00"
    "82b1e64d"
    "03acb23a7633d49a"
    "0000000000000000"
)

LIVE_ROOT_BSV = bytes.fromhex(
    "bf1100080318200340122108"
    "57696e646f777300852c633605febbe57ea8694f53"
    "694f5300852ca213072b586b6f42"
    "416e64726f696400852c3c7c31a6f80894b3"
)


def test_default_root_url_matches_recovered_client_template(monkeypatch):
    monkeypatch.setattr(master_updater.time, "time", lambda: 1_784_569_087)

    assert _resolve_root_url(
        None,
        "https://assets-umamusume-en.akamaized.net/dl/vertical/",
        "10006910",
    ) == (
        "https://assets-umamusume-en.akamaized.net/dl/vertical/10006910/"
        "manifests/manifestdat/root.manifest.bsv.lz4?r=1784569087"
    )


def test_master_hname_formula_matches_known_cdn_object():
    assert calculate_hname(
        "master.mdb.lz4", 264782442268972186, 5010253
    ) == "EHI22T4Y3GBX52MTWGWBVIZK7OEKYWJ5"


def test_full_bsv_parser_extracts_known_master_entry_offline():
    [entry] = parse_manifest(MASTER_BSV)

    assert entry.name == "master.mdb.lz4"
    assert entry.deps == ""
    assert entry.group == 0
    assert entry.priority == 0
    assert entry.size == 5010253
    assert entry.checksum == 264782442268972186
    assert entry.encryption_key == 0
    assert entry.hname == "EHI22T4Y3GBX52MTWGWBVIZK7OEKYWJ5"


def test_simplified_bsv_parser_extracts_known_master_manifest_node():
    manifest = bytes.fromhex("bf1100082518200340122108") + b"master\x00" + bytes.fromhex(
        "45" "331645059c8bda2d"
    )

    [entry] = parse_manifest(manifest)

    assert entry.name == "//master"
    assert entry.size == 69
    assert entry.checksum == 3681205635825523245
    assert entry.hname == "YNY6OBCCRJSYNSKQEBX75JB2L5HVJP4V"


def test_live_root_bsv_schema_extracts_current_windows_node():
    entries = parse_manifest(LIVE_ROOT_BSV)

    windows = next(entry for entry in entries if entry.name == "//Windows")
    assert windows.size == 684
    assert windows.hname == "KACBMBBX5DCVMX4CB3WJCJDQWORBTXOA"


def test_bsv_parser_rejects_truncated_rows_clearly():
    with pytest.raises(ManifestFormatError, match="truncated BSV checksum"):
        parse_manifest(bytes.fromhex("bf1100082518200340122108") + b"master\x00\x45")


def test_integrity_check_releases_the_database_handle(tmp_path):
    database_path = tmp_path / "validated.mdb"
    with contextlib.closing(sqlite3.connect(database_path)) as database:
        database.execute("create table proof (value integer)")

    assert _integrity_check(database_path) == "ok"
    database_path.replace(tmp_path / "renamed.mdb")


def test_replacement_temp_file_is_created_beside_destination(tmp_path):
    destination = tmp_path / "data-root" / "master" / "master.mdb"

    temp_path = master_updater._write_temp_database(
        b"temporary database payload", destination, dry_run=False,
    )
    try:
        assert temp_path.parent == destination.parent
        assert temp_path.name.startswith(f".{destination.name}.")
    finally:
        temp_path.unlink()


def test_explicit_regeneration_reports_unwritable_state_root(tmp_path, monkeypatch):
    database_path = tmp_path / "master.mdb"
    with contextlib.closing(sqlite3.connect(database_path)):
        pass
    monkeypatch.setattr(
        legacy_json,
        "configured_master_mdb_path",
        lambda base_dir: database_path,
    )
    monkeypatch.setattr(
        legacy_json,
        "load_master_data",
        lambda cursor, tables: ({}, [], []),
    )

    def read_only_failure(base_dir, master_data):
        raise PermissionError("checkout is read-only")

    monkeypatch.setattr(
        legacy_json,
        "synthesize_legacy_jsons",
        read_only_failure,
    )

    result = legacy_json.generate(tmp_path)

    assert result["success"] is False
    assert "Could not regenerate master-derived JSON under state root" in result["detail"]
    assert "checkout is read-only" in result["detail"]


def test_full_headless_bootstrap_walks_offline_cdn_and_generates_json(
    tmp_path, monkeypatch,
):
    source_db = tmp_path / "source.mdb"
    with contextlib.closing(sqlite3.connect(source_db)) as database:
        database.execute("create table proof (value integer)")
        database.execute("insert into proof values (7)")
        database.commit()

    chain = _offline_cdn_chain(source_db.read_bytes())
    master_reads = []
    _stub_cdn(monkeypatch, chain, master_reads=master_reads)

    class StubUmaClient:
        def __init__(self, config, state_root=None):
            self.config = config
            self.state_root = state_root

        def regen_sid(self):
            pass

        def call(self, endpoint, payload):
            assert endpoint == "tool/get_pre_download_resource_version"
            assert payload == {}
            return {
                "data_headers": {
                    "server_list": {"resource_server": "https://offline.example/"},
                },
                "data": {"resource_version": "10000000"},
            }

    monkeypatch.setattr("uma_api.client.UmaClient", StubUmaClient)
    destination = tmp_path / "master" / "master.mdb"
    state_root = tmp_path / "state"
    monkeypatch.setattr(
        uma_data,
        "configured_master_mdb_path",
        lambda base_dir, state_root=None: destination,
    )

    assert master_updater.ensure_current_headless(
        ROOT,
        app_ver="1.32.9",
        state_root=state_root,
    ) is True
    with contextlib.closing(sqlite3.connect(destination)) as database:
        assert database.execute("select value from proof").fetchone() == (7,)

    generated = legacy_json.generate(
        ROOT,
        master_mdb_path=destination,
        state_root=state_root,
    )
    assert generated["success"] is True
    assert {
        item["file"] for item in generated["legacy"]["generated"]
    } == {
        "chara_list.json",
        "support_list.json",
        "skill_data.json",
        "race_map.json",
        "factor_map.json",
    }
    assert master_reads
    assert all(size == master_updater.DOWNLOAD_CHUNK_SIZE for size in master_reads)


def test_interrupted_stream_keeps_existing_master_and_cleans_temps(
    tmp_path, monkeypatch,
):
    source_db = tmp_path / "source.mdb"
    with contextlib.closing(sqlite3.connect(source_db)) as database:
        database.execute("create table proof (value integer)")

    chain = _offline_cdn_chain(source_db.read_bytes())
    _stub_cdn(monkeypatch, chain, interrupt_master=True)
    destination = tmp_path / "master" / "master.mdb"
    destination.parent.mkdir()
    destination.write_bytes(b"existing validated database")

    with pytest.raises(master_updater.DownloadError, match="interrupted download"):
        master_updater.fetch_master_mdb(
            "https://offline.example/",
            "10000000",
            destination,
            retries=0,
        )

    assert destination.read_bytes() == b"existing validated database"
    assert list(destination.parent.glob(".master.mdb.*")) == []
