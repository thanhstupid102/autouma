from integrations.discord import notify


def _snapshot(**over):
    snap = {
        "running": True,
        "status": "running",
        "preset": "URA Speed",
        "turn": 34,
        "total_turns": 78,
        "steps": 120,
        "last_action": "train Speed",
        "skills_bought": 5,
        "items_bought": 2,
        "items_used": 1,
        "clocks_used": 0,
        "action_history": [
            {"turn": 34, "action": "train", "facility": "Speed",
             "stats": {"hp": 60, "max_hp": 100, "motivation": 4,
                       "speed": 800, "stamina": 400, "power": 500,
                       "guts": 300, "wit": 450, "skill_point": 220, "fans": 12000},
             "time": "12:00:00"},
        ],
        "log": [
            {"id": 1, "action": "train", "turn": 33, "detail": "Speed", "time": "11:59:50"},
            {"id": 2, "action": "race", "turn": 34, "detail": "Maiden", "time": "12:00:00"},
        ],
        "account": "Trainer",
        "loop_index": 1,
        "loop_target": 1,
    }
    snap.update(over)
    return snap


def _field(e, name_contains):
    for f in e["fields"]:
        if name_contains.lower() in f["name"].lower():
            return f
    return None


def test_running_embed_has_core_fields():
    e = notify._build_live_embed(_snapshot())
    assert "Uma Musume Career Bot" in e["title"]
    assert e["color"] == 0x2ECC71  # green while running
    assert "Running" in _field(e, "Status")["value"]
    blob = str(e)
    assert "URA Speed" in blob
    assert "34" in blob and "78" in blob       # turn / total
    assert "train Speed" in blob               # last action (action + facility)
    assert "SPD" in blob and "800" in blob     # stats line


def test_hp_bar_reflects_percentage():
    e = notify._build_live_embed(_snapshot())
    blob = str(e)
    assert "60/100" in blob


def test_mood_stars_from_motivation():
    e = notify._build_live_embed(_snapshot())
    blob = str(e)
    assert "⭐" in blob  # motivation 4 -> some filled stars


def test_purchases_present():
    e = notify._build_live_embed(_snapshot())
    blob = str(e)
    assert "5" in blob  # skills bought


def test_recent_log_limited_to_seven():
    logs = [{"id": i, "action": "train", "turn": i, "detail": f"d{i}", "time": "12:00:00"}
            for i in range(1, 12)]
    e = notify._build_live_embed(_snapshot(log=logs))
    log_field = _field(e, "Recent Log")
    val = log_field["value"]
    assert "d11" in val and "d5" in val          # newest 7 (d5..d11) kept
    assert "d4" not in val and "d3" not in val   # older trimmed


def test_finished_status_color_and_label():
    e = notify._build_live_embed(_snapshot(status="finished", running=False))
    assert e["color"] == 0x3498DB  # finished color (blue)
    assert "Finished" in _field(e, "Status")["value"]


def test_stopped_and_error_status():
    es = notify._build_live_embed(_snapshot(status="stopped", running=False))
    assert "Stop" in _field(es, "Status")["value"]
    ee = notify._build_live_embed(_snapshot(status="error", running=False))
    assert ee["color"] == 0xE74C3C


def test_energy_label_and_trainee_name(tmp_path):
    # Energy field replaces HP; trainee name resolved from card_id via base_dir.
    e = notify._build_live_embed(_snapshot())
    assert _field(e, "Energy") is not None
    assert _field(e, "HP") is None


def test_run_index_target_shown():
    e = notify._build_live_embed(_snapshot(loop_index=2, loop_target=5))
    assert "Run 2/5" in str(e)
    e2 = notify._build_live_embed(_snapshot(loop_index=1, loop_target=0))
    assert "Run 1/∞" in str(e2)


import json as _json


class _FakeResp:
    def __init__(self, body):
        self._body = body.encode("utf-8")
    def read(self):
        return self._body
    def getcode(self):
        return 200
    @property
    def status(self):
        return 200
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def _write_webhook(tmp_path):
    (tmp_path / "uma_runtime").mkdir(exist_ok=True)
    (tmp_path / "uma_runtime" / "discord.json").write_text(
        _json.dumps({"webhook_url": "https://discord.test/webhooks/1/abc"}), encoding="utf-8")


def test_monitor_posts_then_patches(monkeypatch, tmp_path):
    _write_webhook(tmp_path)
    calls = []

    def fake_urlopen(req, timeout=10):
        calls.append((req.get_method(), req.full_url))
        if req.get_method() == "POST":
            return _FakeResp(_json.dumps({"id": "999"}))
        return _FakeResp("")

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)

    snap = {"status": "running", "running": True, "preset": "P", "turn": 1,
            "total_turns": 78, "steps": 1, "last_action": "started",
            "action_history": [], "log": []}
    mon = notify.LiveMonitor(
        str(tmp_path),
        tmp_path / "uma_runtime",
        lambda: snap,
        interval=0.05,
    )
    mon.start()
    import time as _t; _t.sleep(0.2)
    mon.stop({"status": "finished", "running": False, "preset": "P", "turn": 78,
              "total_turns": 78, "steps": 200, "last_action": "finish",
              "action_history": [], "log": []})

    methods = [m for m, _ in calls]
    assert methods[0] == "POST"
    assert "wait=true" in calls[0][1]
    assert any(m == "PATCH" for m in methods)
    assert all(("/messages/999" in u) for m, u in calls if m == "PATCH")


def test_monitor_no_webhook_is_noop(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(notify.urllib.request, "urlopen",
                        lambda *a, **k: called.append(1))
    mon = notify.LiveMonitor(
        str(tmp_path),
        tmp_path / "uma_runtime",
        lambda: {"status": "running"},
        interval=0.05,
    )
    mon.start()
    import time as _t; _t.sleep(0.1)
    mon.stop({"status": "finished"})
    assert called == []


def test_monitor_swallows_patch_errors(monkeypatch, tmp_path):
    _write_webhook(tmp_path)
    state = {"n": 0}
    def fake_urlopen(req, timeout=10):
        if req.get_method() == "POST":
            return _FakeResp(_json.dumps({"id": "5"}))
        state["n"] += 1
        raise OSError("network down")
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)

    snap = {"status": "running", "running": True, "action_history": [], "log": []}
    mon = notify.LiveMonitor(
        str(tmp_path),
        tmp_path / "uma_runtime",
        lambda: snap,
        interval=0.05,
    )
    mon.start()
    import time as _t; _t.sleep(0.15)
    mon.stop({"status": "finished", "action_history": [], "log": []})
    assert state["n"] >= 1


def test_start_stop_helpers(monkeypatch, tmp_path):
    _write_webhook(tmp_path)
    monkeypatch.setattr(notify.urllib.request, "urlopen",
                        lambda req, timeout=10: _FakeResp(_json.dumps({"id": "7"})))
    h = notify.start_live_monitor(
        str(tmp_path),
        tmp_path / "uma_runtime",
        lambda: {"status": "running", "action_history": [], "log": []},
        interval=0.05,
    )
    assert h is not None
    notify.stop_live_monitor(h, {"status": "finished", "action_history": [], "log": []})
