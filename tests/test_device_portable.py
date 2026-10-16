import hashlib
import socket
import sys
import types

import pytest

from uma_api import client as client_mod
from uma_api import device, identity
from uma_api.client import UmaClient


DEVICE_ENV_VARS = (
    "UMA_DEVICE_NAME",
    "UMA_DEVICE_GRAPHICS_DEVICE_NAME",
    "UMA_DEVICE_PLATFORM_OS_VERSION",
    "UMA_DEVICE_IP_ADDRESS",
    "UMA_DEVICE_MACHINE_ID",
)

FINGERPRINT = {
    "device_id": "registered-device-id",
    "device_name": "registered-device-name",
    "graphics_device_name": "registered-gpu",
    "ip_address": "10.20.30.40",
    "platform_os_version": "Windows 11  (10.0.26100) 64bit",
}


@pytest.fixture(autouse=True)
def _clear_device_environment(monkeypatch):
    for name in DEVICE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _set_non_windows_material(monkeypatch, values=None):
    values = values or {}
    monkeypatch.setattr(device.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        device,
        "_read_system_value",
        lambda path: values.get(str(path), ""),
    )
    monkeypatch.setenv("UMA_DEVICE_IP_ADDRESS", "192.0.2.10")


def _install_fake_winreg(
    monkeypatch,
    *,
    product="Known Product",
    vendor="Known Vendor",
    machine_guid="known-machine-guid",
    gpu="Known GPU",
):
    opened = []

    class FakeKey:
        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    def open_key(_root, path):
        opened.append(path)
        return FakeKey(path)

    def query_value(key, name):
        values = {
            (r"HARDWARE\DESCRIPTION\System\BIOS", "SystemProductName"): product,
            (r"HARDWARE\DESCRIPTION\System\BIOS", "BaseBoardManufacturer"): vendor,
            (r"SOFTWARE\Microsoft\Cryptography", "MachineGuid"): machine_guid,
            (
                r"SYSTEM\CurrentControlSet\Control\Video\{ADAPTER}\0000",
                "HardwareInformation.AdapterString",
            ): gpu,
        }
        try:
            return values[(key.path, name)], 1
        except KeyError as exc:
            raise OSError(f"unexpected registry value: {key.path} / {name}") from exc

    fake_winreg = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=open_key,
        QueryValueEx=query_value,
        QueryInfoKey=lambda key: (1, 0, 0),
        EnumKey=lambda key, index: "{ADAPTER}",
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr(device.platform, "system", lambda: "Windows")
    monkeypatch.setattr(device.platform, "version", lambda: "10.0.26100")
    return opened


def _prepare_client_constructor(monkeypatch):
    class StubSession:
        def __init__(self):
            self.headers = {}

    class StubPacingPolicy:
        def dna_uniform(self, low, high):
            return 0.0

    monkeypatch.setattr(client_mod.requests, "Session", StubSession)
    monkeypatch.setattr(client_mod._client_version, "load_client_version", lambda base: {})
    monkeypatch.setattr(
        client_mod._client_version,
        "resolve_versions",
        lambda cv, cfg, app_ver, res_ver: (app_ver, res_ver),
    )
    monkeypatch.setattr(
        client_mod._client_version,
        "get_resource_server",
        lambda base: "",
    )
    return StubPacingPolicy()


def test_non_windows_get_hwid_returns_windows_shaped_profile(monkeypatch):
    _set_non_windows_material(monkeypatch)

    profile = device.get_hwid("portable-seed")

    assert set(profile) == {
        "device_name",
        "graphics_device_name",
        "platform_os_version",
        "ip_address",
        "udid",
        "device_id",
    }
    assert profile["device_name"]
    assert profile["graphics_device_name"]
    assert profile["platform_os_version"].startswith("Windows")
    for field in ("device_name", "graphics_device_name", "platform_os_version"):
        assert "linux" not in profile[field].casefold()


def test_non_windows_device_name_prefers_dmi_product_and_vendor(monkeypatch):
    _set_non_windows_material(monkeypatch, {
        "/sys/class/dmi/id/product_name": "Precision 3660",
        "/sys/class/dmi/id/board_vendor": "Dell Inc.",
        "/etc/machine-id": "machine-id",
    })

    assert device.get_hwid()["device_name"] == "Precision 3660 (Dell Inc.)"


def test_non_windows_device_id_is_deterministic_for_material_and_seed(monkeypatch):
    _set_non_windows_material(monkeypatch, {
        "/sys/class/dmi/id/product_name": "Precision 3660",
        "/sys/class/dmi/id/board_vendor": "Dell Inc.",
        "/etc/machine-id": "stable-machine-id",
    })

    first = device.get_hwid("same-seed")
    second = device.get_hwid("same-seed")
    different = device.get_hwid("different-seed")

    expected = hashlib.sha1(
        b"Precision 3660 (Dell Inc.)_stable-machine-id_same-seed"
    ).hexdigest()
    assert first["device_id"] == second["device_id"] == expected
    assert different["device_id"] != expected


def test_steam_machine_name_uses_stable_device_material(monkeypatch):
    _set_non_windows_material(monkeypatch, {
        "/sys/class/dmi/id/product_name": "Precision 3660",
        "/sys/class/dmi/id/board_vendor": "Dell Inc.",
        "/etc/machine-id": "stable-machine-id",
    })

    digest = hashlib.sha1(
        b"Precision 3660 (Dell Inc.)_stable-machine-id"
    ).digest()
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    expected = "DESKTOP-" + "".join(
        alphabet[value % len(alphabet)] for value in digest[:7]
    )

    assert device.get_steam_machine_name() == expected
    assert device.get_steam_machine_name() == expected


def test_non_windows_environment_overrides_are_honored(monkeypatch):
    _set_non_windows_material(monkeypatch)
    overrides = {
        "UMA_DEVICE_NAME": "Override Workstation (Override Vendor)",
        "UMA_DEVICE_GRAPHICS_DEVICE_NAME": "NVIDIA GeForce RTX 4070",
        "UMA_DEVICE_PLATFORM_OS_VERSION": "Windows 11  (10.0.22631) 64bit",
        "UMA_DEVICE_IP_ADDRESS": "198.51.100.20",
        "UMA_DEVICE_MACHINE_ID": "override-machine-id",
    }
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)

    profile = device.get_hwid("override-seed")

    assert profile["device_name"] == overrides["UMA_DEVICE_NAME"]
    assert profile["graphics_device_name"] == overrides["UMA_DEVICE_GRAPHICS_DEVICE_NAME"]
    assert profile["platform_os_version"] == overrides["UMA_DEVICE_PLATFORM_OS_VERSION"]
    assert profile["ip_address"] == overrides["UMA_DEVICE_IP_ADDRESS"]
    assert profile["device_id"] == hashlib.sha1(
        b"Override Workstation (Override Vendor)_override-machine-id_override-seed"
    ).hexdigest()


def test_get_ip_closes_socket_and_uses_hostname_fallback(monkeypatch):
    class FailingSocket:
        def __init__(self):
            self.closed = False

        def connect(self, address):
            raise OSError(f"no route to {address}")

        def close(self):
            self.closed = True

    failing_socket = FailingSocket()
    monkeypatch.setattr(device.socket, "socket", lambda *args: failing_socket)
    monkeypatch.setattr(device.socket, "gethostname", lambda: "portable-host")
    monkeypatch.setattr(
        device.socket,
        "gethostbyname",
        lambda hostname: "192.0.2.55",
    )

    result = device.get_ip()

    assert result == "192.0.2.55"
    assert socket.inet_aton(result)
    assert failing_socket.closed is True


@pytest.mark.parametrize("source", ["explicit", "captured"])
def test_complete_saved_identity_never_probes_hardware(monkeypatch, source):
    pacing_policy = _prepare_client_constructor(monkeypatch)
    monkeypatch.setattr(
        client_mod,
        "get_hwid",
        lambda seed: pytest.fail("complete saved identity must not probe hardware"),
    )
    if source == "explicit":
        cfg = {"udid": "saved-udid", **FINGERPRINT}
    else:
        cfg = {"udid": "saved-udid", "body": "captured-body"}
        monkeypatch.setattr(
            client_mod.identity,
            "unpack_request",
            lambda body, udid: dict(FINGERPRINT),
        )

    client = UmaClient(
        cfg,
        trace_enabled=False,
        retry_policy=object(),
        pacing_policy=pacing_policy,
    )

    assert client.udid_str == "saved-udid"
    assert client.device_id == FINGERPRINT["device_id"]
    assert client.device_name == FINGERPRINT["device_name"]


def test_incomplete_client_identity_probes_once_and_uses_profile(monkeypatch):
    pacing_policy = _prepare_client_constructor(monkeypatch)
    calls = []
    profile = {"udid": "generated-udid", **FINGERPRINT}

    def fake_hwid(seed):
        calls.append(seed)
        return dict(profile)

    monkeypatch.setattr(client_mod, "get_hwid", fake_hwid)

    client = UmaClient(
        {"udid": "saved-udid"},
        trace_enabled=False,
        retry_policy=object(),
        pacing_policy=pacing_policy,
    )

    assert calls == ["default"]
    assert client.udid_str == "saved-udid"
    assert client.device_id == FINGERPRINT["device_id"]
    assert client.graphics_device == FINGERPRINT["graphics_device_name"]
    assert client.platform_os == FINGERPRINT["platform_os_version"]


def test_materialize_legacy_seed_succeeds_off_windows(monkeypatch):
    _set_non_windows_material(monkeypatch, {
        "/sys/class/dmi/id/product_name": "Legacy Workstation",
        "/sys/class/dmi/id/board_vendor": "Legacy Vendor",
        "/etc/machine-id": "legacy-machine-id",
    })

    resolved = identity.materialize_device_identity({}, "legacy-seed")

    assert all(resolved.values())
    assert resolved["device_name"] == "Legacy Workstation (Legacy Vendor)"
    assert resolved["device_id"] == hashlib.sha1(
        b"Legacy Workstation (Legacy Vendor)_legacy-machine-id_legacy-seed"
    ).hexdigest()
    assert resolved["platform_os_version"].startswith("Windows")


def test_windows_registry_branch_preserves_device_id_formula(monkeypatch):
    opened = _install_fake_winreg(monkeypatch)
    monkeypatch.setenv("UMA_DEVICE_IP_ADDRESS", "192.0.2.60")

    profile = device.get_hwid("known-seed")

    assert profile == {
        "device_name": "Known Product (Known Vendor)",
        "graphics_device_name": "Known GPU",
        "platform_os_version": "Windows 11  (10.0.26100) 64bit",
        "ip_address": "192.0.2.60",
        "udid": profile["udid"],
        "device_id": hashlib.sha1(
            b"Known Product (Known Vendor)_known-machine-guid_known-seed"
        ).hexdigest(),
    }
    assert opened == [
        r"HARDWARE\DESCRIPTION\System\BIOS",
        r"SOFTWARE\Microsoft\Cryptography",
        r"SYSTEM\CurrentControlSet\Control\Video",
        r"SYSTEM\CurrentControlSet\Control\Video\{ADAPTER}\0000",
    ]


def test_windows_environment_overrides_are_honored(monkeypatch):
    _install_fake_winreg(monkeypatch)
    overrides = {
        "UMA_DEVICE_NAME": "Override Desktop (Override Board)",
        "UMA_DEVICE_GRAPHICS_DEVICE_NAME": "AMD Radeon RX 7900 XTX",
        "UMA_DEVICE_PLATFORM_OS_VERSION": "Windows 11  (10.0.22631) 64bit",
        "UMA_DEVICE_IP_ADDRESS": "203.0.113.25",
        "UMA_DEVICE_MACHINE_ID": "override-windows-machine-id",
    }
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)

    profile = device.get_hwid("override-seed")

    assert profile["device_name"] == overrides["UMA_DEVICE_NAME"]
    assert profile["graphics_device_name"] == overrides["UMA_DEVICE_GRAPHICS_DEVICE_NAME"]
    assert profile["platform_os_version"] == overrides["UMA_DEVICE_PLATFORM_OS_VERSION"]
    assert profile["ip_address"] == overrides["UMA_DEVICE_IP_ADDRESS"]
    assert profile["device_id"] == hashlib.sha1(
        b"Override Desktop (Override Board)_override-windows-machine-id_override-seed"
    ).hexdigest()
