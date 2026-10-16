import gzip
import hashlib
import json
import urllib.error

import pytest

from career_bot.engine.report import add_api_call, new_report, set_error
from career_bot.engine.runner import CareerRunner
from integrations.discord import notify
from core.settings import Settings
from uma_api.diagnostics import SENSITIVE_ERROR_KEYS
from uma_api.errors import ApiError
from uma_api.trace import TraceLog, iter_trace_records


class _Response:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getcode(self):
        return self.status


def _configure_webhook(state_root, **extra_config):
    state_root.mkdir(parents=True, exist_ok=True)
    (state_root / "discord.json").write_text(
        json.dumps({"webhook_url": "https://discord.test/hook", **extra_config}),
        encoding="utf-8",
    )


def _capture_requests(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout=10):
        requests.append(request)
        return _Response()

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    return requests


def _multipart_parts(request):
    content_type = request.get_header("Content-type")
    boundary = content_type.split("boundary=", 1)[1].encode("ascii")
    parts = {}
    for part in request.data.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        headers, body = part.split(b"\r\n\r\n", 1)
        body = body.removesuffix(b"\r\n")
        if b'name="payload_json"' in headers:
            parts["payload_json"] = json.loads(body)
        elif b'name="files[0]"' in headers:
            parts["file"] = body
            parts["file_headers"] = headers
    return parts


def _make_trace(tmp_path, records, flush_interval=1):
    trace = TraceLog(tmp_path / "trace_logs", flush_interval=flush_interval)
    path = trace.initialize()
    for direction, endpoint, data in records:
        trace.write(direction, endpoint, data)
    trace.close()
    return path


def _error_summary():
    return {
        "status": "error",
        "final_turn": 42,
        "api_failure": {
            "endpoint": "single_mode/exec_command",
            "result_code": 500,
            "turn": 42,
        },
        "error": {
            "type": "ApiError",
            "stack_trace": (
                "Traceback (most recent call last):\n"
                "  File \"runner.py\", line 10, in run\n"
                "    call_api()\n"
                "  File \"client.py\", line 20, in call_api\n"
                "    raise ApiError()\n"
                "ApiError: failed\n"
            ),
        },
    }


def test_error_upload_redacts_every_sensitive_key_but_keeps_disk_full(
    tmp_path, monkeypatch,
):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    secrets = {key: f"secret-{key}" for key in SENSITIVE_ERROR_KEYS}
    path = _make_trace(tmp_path, [
        ("REQ", "test/redact", {"payload": secrets}),
        ("RES", "test/redact", {"data_headers": {"result_code": 500}}),
    ])
    requests = _capture_requests(monkeypatch)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        _error_summary(),
        attachment_path=path,
    ) is True

    on_disk = list(iter_trace_records(path))[0]["data"]["payload"]
    assert on_disk == secrets
    parts = _multipart_parts(requests[0])
    uploaded = [json.loads(line) for line in gzip.decompress(parts["file"]).splitlines()]
    uploaded_payload = uploaded[0]["data"]["payload"]
    assert uploaded_payload == {
        key: "<redacted>" for key in SENSITIVE_ERROR_KEYS
    }
    for secret in secrets.values():
        assert secret.encode("utf-8") not in parts["file"]


def test_uploaded_trace_redacts_identity_paths_and_preserves_gameplay_names(
    tmp_path, monkeypatch,
):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    trainer = "Kaichō"
    circle = "Private Circle"
    device_name = "Operator Workstation"
    graphics_device_name = "Operator GPU"
    ip_address = "192.0.2.10"
    platform_os_version = "Operator OS Build"
    deck = "Deck Alpha"
    uma = "Special Week"
    skill = "Corner Adept"
    path = _make_trace(tmp_path, [
        (
            "REQ",
            "load/index",
            {
                "payload": {
                    "device_name": device_name,
                    "graphics_device_name": graphics_device_name,
                    "ip_address": ip_address,
                    "platform_os_version": platform_os_version,
                    "viewer_id": 123456,
                    "steam_id": "76561198000000000",
                    "user_info": {"name": trainer},
                    "circle_data": {"circle_info": {"name": circle}},
                    "support_card_deck_array": [{"name": deck}],
                    "uma_info": {"name": uma},
                    "skill_info": {"name": skill},
                }
            },
        ),
        (
            "RES",
            "load/index",
            {
                "data_headers": {"result_code": 1},
                "data": {
                    "user_info": {"name": trainer},
                    "circle_data": {"circle_info": {"name": circle}},
                    "support_card_deck_array": [{"name": deck}],
                    "uma_info": {"name": uma},
                    "skill_info": {"name": skill},
                },
            },
        ),
        (
            "RES",
            "pre_single_mode/index",
            {
                "data": {
                    "friend_support_card_data": {
                        "summary_user_info_array": [
                            {"circle_info": {"name": circle}},
                        ],
                    },
                    "succession_trained_chara_data": {
                        "summary_user_info_array": [
                            {"circle_info": {"name": circle}},
                        ],
                    },
                },
            },
        ),
        (
            "RES",
            "single_mode_free/load",
            {
                "data": {
                    "race_start_info": {
                        "race_horse_data": [{
                            "trainer_name": trainer,
                            "owner_trainer_name": trainer,
                            "name": uma,
                        }],
                    },
                    "single_mode_load_common": {
                        "race_start_info": {
                            "race_horse_data": [{
                                "trainer_name": trainer,
                                "owner_trainer_name": trainer,
                                "name": uma,
                            }],
                        },
                    },
                },
            },
        ),
        (
            "RES",
            "single_mode_team/team_race_start",
            {
                "data": {
                    "team_data_set": {
                        "race_result_array": [{
                            "race_horse_data_array": [{
                                "trainer_name": trainer,
                                "owner_trainer_name": trainer,
                                "name": uma,
                            }],
                        }],
                    },
                },
            },
        ),
        (
            "RES",
            "account/get_by_transition_code",
            {"data": {"name": trainer, "request_user_name": trainer}},
        ),
        (
            "RES",
            "account/chain_by_transition_code",
            {"data": {"chained_user_name": trainer}},
        ),
    ])
    source_with_private_name = path.with_name(f"{trainer}_payloads.jsonl.gz")
    path.replace(source_with_private_name)
    requests = _capture_requests(monkeypatch)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        _error_summary(),
        attachment_path=source_with_private_name,
    ) is True

    on_disk = list(iter_trace_records(source_with_private_name))
    assert on_disk[0]["data"]["payload"]["device_name"] == device_name
    assert on_disk[0]["data"]["payload"]["graphics_device_name"] == graphics_device_name
    assert on_disk[0]["data"]["payload"]["ip_address"] == ip_address
    assert on_disk[0]["data"]["payload"]["platform_os_version"] == platform_os_version
    assert on_disk[0]["data"]["payload"]["user_info"]["name"] == trainer
    assert on_disk[1]["data"]["data"]["circle_data"]["circle_info"]["name"] == circle
    assert on_disk[3]["data"]["data"]["race_start_info"]["race_horse_data"][0]["trainer_name"] == trainer
    assert on_disk[5]["data"]["data"]["name"] == trainer

    parts = _multipart_parts(requests[0])
    uploaded = [json.loads(line) for line in gzip.decompress(parts["file"]).splitlines()]
    request_data = uploaded[0]["data"]["payload"]
    load_data = uploaded[1]["data"]["data"]
    pre_data = uploaded[2]["data"]["data"]
    race_data = uploaded[3]["data"]["data"]
    team_data = uploaded[4]["data"]["data"]
    transition_data = uploaded[5]["data"]["data"]
    chain_data = uploaded[6]["data"]["data"]

    assert request_data["user_info"]["name"] == "<redacted>"
    assert request_data["circle_data"]["circle_info"]["name"] == "<redacted>"
    assert request_data["device_name"] == "<redacted>"
    assert request_data["graphics_device_name"] == "<redacted>"
    assert request_data["ip_address"] == "<redacted>"
    assert request_data["platform_os_version"] == "<redacted>"
    assert request_data["viewer_id"] == 123456
    assert request_data["steam_id"] == "76561198000000000"
    assert load_data["user_info"]["name"] == "<redacted>"
    assert load_data["circle_data"]["circle_info"]["name"] == "<redacted>"
    assert pre_data["friend_support_card_data"]["summary_user_info_array"][0]["circle_info"]["name"] == "<redacted>"
    assert pre_data["succession_trained_chara_data"]["summary_user_info_array"][0]["circle_info"]["name"] == "<redacted>"
    assert race_data["race_start_info"]["race_horse_data"][0]["trainer_name"] == "<redacted>"
    assert race_data["race_start_info"]["race_horse_data"][0]["owner_trainer_name"] == "<redacted>"
    assert race_data["single_mode_load_common"]["race_start_info"]["race_horse_data"][0]["trainer_name"] == "<redacted>"
    assert race_data["single_mode_load_common"]["race_start_info"]["race_horse_data"][0]["owner_trainer_name"] == "<redacted>"
    assert team_data["team_data_set"]["race_result_array"][0]["race_horse_data_array"][0]["trainer_name"] == "<redacted>"
    assert team_data["team_data_set"]["race_result_array"][0]["race_horse_data_array"][0]["owner_trainer_name"] == "<redacted>"
    assert transition_data["name"] == "<redacted>"
    assert transition_data["request_user_name"] == "<redacted>"
    assert chain_data["chained_user_name"] == "<redacted>"

    assert load_data["support_card_deck_array"][0]["name"] == deck
    assert load_data["uma_info"]["name"] == uma
    assert load_data["skill_info"]["name"] == skill
    assert race_data["race_start_info"]["race_horse_data"][0]["name"] == uma
    assert team_data["team_data_set"]["race_result_array"][0]["race_horse_data_array"][0]["name"] == uma

    file_headers = parts["file_headers"].decode("utf-8")
    assert 'filename="career_api_trace_redacted.jsonl.gz"' in file_headers
    assert trainer not in file_headers
    outgoing = requests[0].data + str(requests[0].header_items()).encode("utf-8")
    assert trainer.encode("utf-8") not in parts["file"]
    assert circle.encode("utf-8") not in parts["file"]
    assert "Sweepy改二".encode("utf-8") not in outgoing
    assert b"Uma Musume Auto" not in outgoing
    assert b"umamusume-sweepy" not in outgoing
    assert b"----sweepy-" not in outgoing


def test_error_upload_redacts_transfer_id_aliases_in_both_directions(
    tmp_path, monkeypatch,
):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    target_secret = "secret-target-viewer"
    chained_secret = "secret-chained-viewer"
    path = _make_trace(tmp_path, [
        (
            "REQ",
            "account/get_by_transition_code",
            {"payload": {"nested": [{"target_viewer_id": target_secret}]}},
        ),
        (
            "RES",
            "account/chain_by_transition_code",
            {
                "data_headers": {"result_code": 1},
                "data": {"accounts": [{"chained_viewer_id": chained_secret}]},
            },
        ),
    ])
    requests = _capture_requests(monkeypatch)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        _error_summary(),
        attachment_path=path,
    ) is True

    parts = _multipart_parts(requests[0])
    uploaded = [json.loads(line) for line in gzip.decompress(parts["file"]).splitlines()]
    assert uploaded[0]["data"]["payload"]["nested"][0]["target_viewer_id"] == "<redacted>"
    assert uploaded[1]["data"]["data"]["accounts"][0]["chained_viewer_id"] == "<redacted>"
    assert target_secret.encode() not in parts["file"]
    assert chained_secret.encode() not in parts["file"]


@pytest.mark.parametrize("status", ["finished", "stopped", "paused"])
def test_normal_statuses_never_upload_trace_or_ping(tmp_path, monkeypatch, status):
    state_root = tmp_path / "state"
    _configure_webhook(state_root, error_mention={
        "kind": "user", "id": "12345678901234567",
    })
    path = _make_trace(tmp_path, [("REQ", "test/normal", {"password": "secret"})])
    requests = _capture_requests(monkeypatch)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        {"status": status},
        attachment_path=path,
    ) is True

    assert requests[0].get_header("Content-type") == "application/json"
    assert b"files[0]" not in requests[0].data
    payload = json.loads(requests[0].data)
    assert "content" not in payload
    assert "allowed_mentions" not in payload


@pytest.mark.parametrize(
    ("target", "content", "allowed_mentions"),
    [
        (
            {"kind": "user", "id": "12345678901234567"},
            "<@12345678901234567> Account Test Account: "
            "career stopped with an error.",
            {"parse": [], "users": ["12345678901234567"]},
        ),
        (
            {"kind": "role", "id": "12345678901234567890"},
            "<@&12345678901234567890> Account Test Account: "
            "career stopped with an error.",
            {"parse": [], "roles": ["12345678901234567890"]},
        ),
    ],
)
def test_error_career_sends_minimal_explicit_mention_controls(
    tmp_path, monkeypatch, target, content, allowed_mentions,
):
    state_root = tmp_path / "state"
    _configure_webhook(state_root, error_mention=target)
    requests = _capture_requests(monkeypatch)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        {**_error_summary(), "account": "Test Account"},
    ) is True

    payload = json.loads(requests[0].data)
    assert payload["content"] == content
    assert payload["allowed_mentions"] == allowed_mentions
    assert payload["allowed_mentions"]["parse"] == []


def test_error_mention_and_trace_attachment_share_one_multipart_message(
    tmp_path, monkeypatch,
):
    state_root = tmp_path / "state"
    _configure_webhook(state_root, error_mention={
        "kind": "user", "id": "12345678901234567",
    })
    path = _make_trace(tmp_path, [("REQ", "test/ping", {"value": 1})])
    requests = _capture_requests(monkeypatch)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        {**_error_summary(), "account": "Test Account"},
        attachment_path=path,
    ) is True

    parts = _multipart_parts(requests[0])
    assert "file" in parts
    assert parts["payload_json"]["content"] == (
        "<@12345678901234567> Account Test Account: "
        "career stopped with an error."
    )
    assert parts["payload_json"]["allowed_mentions"] == {
        "parse": [], "users": ["12345678901234567"],
    }


def test_error_without_a_mention_keeps_the_existing_payload_bytes(
    tmp_path, monkeypatch,
):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    requests = _capture_requests(monkeypatch)
    embed = {"title": "Existing error embed"}
    monkeypatch.setattr(notify, "_build_embed", lambda _summary: embed)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        _error_summary(),
    ) is True

    assert requests[0].data == json.dumps({"embeds": [embed]}).encode("utf-8")


def test_oversize_upload_keeps_tail_and_marks_dropped_records(
    tmp_path, monkeypatch,
):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    records = [
        (
            "RES",
            "test/tail",
            {
                "index": index,
                "blob": "".join(
                    hashlib.sha256(f"{index}-{part}".encode()).hexdigest()
                    for part in range(8)
                ),
            },
        )
        for index in range(40)
    ]
    path = _make_trace(tmp_path, records)
    requests = _capture_requests(monkeypatch)
    monkeypatch.setattr(Settings, "UMA_DISCORD_CAREER_TRACE_MAX_BYTES", 1200)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        _error_summary(),
        attachment_path=path,
    ) is True

    parts = _multipart_parts(requests[0])
    assert len(parts["file"]) <= 1200
    uploaded = [json.loads(line) for line in gzip.decompress(parts["file"]).splitlines()]
    marker = uploaded[0]
    assert marker["type"] == "discord_trace_tail"
    assert marker["dropped_records"] > 0
    assert "Earlier records were dropped" in marker["message"]
    assert uploaded[-1]["data"]["index"] == 39


def test_tail_selection_does_not_assume_compressed_sizes_are_monotonic(tmp_path):
    records = [
        {"i": 0, "blob": "token273|token203|token307|token057|token032|token334"},
        {"i": 1, "blob": "token110|token308|token255|token478|token316|token217"},
        {"i": 2, "blob": "token019"},
        {"i": 3, "blob": "token396|token019|token318|token355|token151|token444|token123|token010|token425|token002|token192|token377|token331|token413|token449|token255|token489|token360|token430|token312|token160"},
        {"i": 4, "blob": "token014|token446|token414|token219|token308|token252|token427|token385|token357|token392|token336|token238|token496|token275|token093|token418|token255|token004|token311|token057|token181|token423|token167|token443|token288|token148|token061|token270|token253|token441|token485|token021|token418"},
        {"i": 5, "blob": "token483|token286|token060|token162|token494|token421|token414|token295|token246|token004|token429|token203|token440|token080|token446|token468|token494|token044|token329|token338|token341|token265|token406|token195|token266|token221|token060|token086|token188|token319|token301|token320|token453|token083|token097|token030|token498|token141|token013|token248|token006|token003|token439|token247|token321|token487|token442|token125|token203|token463|token285|token360|token186|token270|token080|token357|token255|token237|token367|token478|token419"},
    ]
    records[0]["head_padding"] = "".join(
        hashlib.sha256(f"head-{index}".encode()).hexdigest()
        for index in range(4)
    )
    path = tmp_path / "nonmonotonic_payloads.jsonl.gz"
    with path.open("wb") as raw_file:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_file, mtime=0) as stream:
            for record in records:
                stream.write(json.dumps(record, separators=(",", ":")).encode() + b"\n")

    attachment = notify._redacted_trace_attachment(path, 442)

    assert attachment is not None
    _filename, data, dropped = attachment
    assert len(data) <= 442
    assert dropped == 2
    uploaded = [json.loads(line) for line in gzip.decompress(data).splitlines()]
    assert uploaded[0]["dropped_records"] == 2
    assert [record["i"] for record in uploaded[1:]] == [2, 3, 4, 5]


def test_runner_attempts_at_most_one_trace_upload(tmp_path, monkeypatch):
    path = _make_trace(tmp_path, [("REQ", "test/once", {"value": 1})])
    runner = CareerRunner(tmp_path, state_root=tmp_path)
    runner.report = new_report()
    runner.report["status"] = "error"
    runner._career_trace_path = path
    runner._report_path = tmp_path / "career.json"
    sent = []
    monkeypatch.setattr(notify, "stop_live_monitor", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "career_bot.engine.runner.write_report",
        lambda *args, **kwargs: runner._report_path,
    )
    monkeypatch.setattr(
        notify,
        "send_career_summary",
        lambda *args, **kwargs: sent.append(kwargs.get("attachment_path")),
    )

    runner._emit_run_outputs()
    runner._emit_run_outputs()

    assert sent == [path, None]


def test_error_embed_includes_failure_exception_and_traceback_frames():
    embed = notify._build_embed(_error_summary())
    fields = {field["name"]: field["value"] for field in embed["fields"]}

    assert "single_mode/exec_command" in fields["Failed API Call"]
    assert "result_code `500`" in fields["Failed API Call"]
    assert "turn `42`" in fields["Failed API Call"]
    assert fields["Exception"] == "`ApiError`"
    assert "client.py" in fields["Last Traceback Frames"]


def test_error_request_omits_free_form_api_detail(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    requests = _capture_requests(monkeypatch)
    trainer = "Kaichō"
    summary = _error_summary()
    summary["api_failure"]["detail"] = json.dumps({
        "message": f"career failed for trainer {trainer}",
    })

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        summary,
    ) is True

    assert trainer.encode("utf-8") not in requests[0].data
    payload = json.loads(requests[0].data)
    fields = {
        field["name"]: field["value"]
        for field in payload["embeds"][0]["fields"]
    }
    assert fields["Failed API Call"] == (
        "Endpoint `single_mode/exec_command` · result_code `500` · turn `42`"
    )


def test_report_summary_reuses_api_error_formatting(tmp_path):
    runner = CareerRunner(tmp_path, state_root=tmp_path)
    runner.report = new_report()
    add_api_call(runner.report, {
        "endpoint": "single_mode/exec_command",
        "direction": "RES",
        "result_code": 500,
        "turn": 12,
        "data": {
            "response_code": 1,
            "data_headers": {"result_code": 500, "sid": "secret-sid"},
            "data": {"viewer_id": 123, "message": "failed"},
        },
    })
    set_error(runner.report, ApiError(500, "single_mode/exec_command", "failed"))

    failure = runner._build_notify_summary()["api_failure"]

    assert failure["turn"] == 12
    assert '"viewer_id": 123' in failure["detail"]
    assert "secret-sid" not in failure["detail"]


def test_missing_webhook_network_failure_and_missing_file_are_best_effort(
    tmp_path, monkeypatch,
):
    missing = tmp_path / "missing.jsonl.gz"
    assert notify.send_career_summary(
        tmp_path,
        tmp_path / "no-webhook",
        _error_summary(),
        attachment_path=missing,
    ) is False

    mention_only_root = tmp_path / "mention-only"
    mention_only_root.mkdir()
    (mention_only_root / "discord.json").write_text(
        json.dumps({"error_mention": {
            "kind": "user", "id": "12345678901234567",
        }}),
        encoding="utf-8",
    )
    assert notify.send_career_summary(
        tmp_path,
        mention_only_root,
        _error_summary(),
        attachment_path=missing,
    ) is False

    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    requests = _capture_requests(monkeypatch)
    assert notify.send_career_summary(
        tmp_path,
        state_root,
        _error_summary(),
        attachment_path=missing,
    ) is True
    assert requests[-1].get_header("Content-type") == "application/json"

    def fail_urlopen(request, timeout=10):
        raise OSError("network down")

    monkeypatch.setattr(notify.urllib.request, "urlopen", fail_urlopen)
    path = _make_trace(tmp_path, [("REQ", "test/network", {"value": 1})])
    assert notify.send_career_summary(
        tmp_path,
        state_root,
        _error_summary(),
        attachment_path=path,
    ) is False


def test_rejected_attachment_retries_once_as_json_only(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    path = _make_trace(tmp_path, [("REQ", "test/413", {"value": 1})])
    requests = []

    def reject_attachment(request, timeout=10):
        requests.append(request)
        if len(requests) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                413,
                "Payload Too Large",
                hdrs=None,
                fp=None,
            )
        return _Response()

    monkeypatch.setattr(notify.urllib.request, "urlopen", reject_attachment)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        _error_summary(),
        attachment_path=path,
    ) is True

    assert len(requests) == 2
    assert requests[0].get_header("Content-type").startswith("multipart/form-data")
    assert requests[1].get_header("Content-type") == "application/json"
    assert b"files[0]" not in requests[1].data


def test_rate_limited_attachment_is_not_retried(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    _configure_webhook(state_root)
    path = _make_trace(tmp_path, [("REQ", "test/429", {"value": 1})])
    requests = []

    def rate_limited(request, timeout=10):
        requests.append(request)
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(notify.urllib.request, "urlopen", rate_limited)

    assert notify.send_career_summary(
        tmp_path,
        state_root,
        _error_summary(),
        attachment_path=path,
    ) is False
    assert len(requests) == 1
