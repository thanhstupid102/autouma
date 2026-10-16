import importlib.util
import pathlib
import sys
import threading
import types

from core.settings import Settings


ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK_DIR = Settings.PATH["hooks"]


def test_il2cpp_metadata_hooks_attach_the_frida_thread():
    unsafe_hooks = []
    for hook_path in HOOK_DIR.glob("*.js"):
        source = hook_path.read_text(encoding="utf-8")
        if "il2cpp_class_from_name" in source and "il2cpp_thread_attach" not in source:
            unsafe_hooks.append(hook_path.name)
    assert unsafe_hooks == []


def test_record_traffic_warns_when_no_packet_arrives(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "frida", types.ModuleType("frida"))
    script_path = ROOT / "scripts" / "record_traffic.py"
    spec = importlib.util.spec_from_file_location("record_traffic_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module._warn_if_no_packet(threading.Event(), threading.Event(), grace_seconds=0)

    output = capsys.readouterr().out
    assert "no traffic packet arrived within 0s" in output
    assert "hook may not have bound" in output
